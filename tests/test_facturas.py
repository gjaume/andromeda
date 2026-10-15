import base64
from datetime import date

import httpx
import pytest
import respx
from django.urls import reverse
from django_q.models import Schedule

from apps.administracion.facturas import sincronizar_facturas
from apps.administracion.forms import ProveedorForm
from apps.administracion.models import CorreoFactura, FacturaRecibida, Proveedor
from integrations.gmail import GmailAuthError, get_client

API = "https://gmail.googleapis.com/gmail/v1/users/admin@andronautic.com"
PDF = b"%PDF-1.4 factura de prueba"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def mensaje(message_id, *, adjuntos=(), asunto="Factura octubre"):
    """Respuesta de messages.get con format=full."""
    return {
        "id": message_id,
        "threadId": f"t{message_id}",
        "internalDate": "1760000000000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": asunto},
                {"name": "From", "value": "Iberdrola <facturas@iberdrola.es>"},
            ],
            "parts": [
                {"partId": "0", "mimeType": "text/plain", "filename": "", "body": {"size": 5}},
                *adjuntos,
            ],
        },
    }


def adjunto(part_id, filename, *, attachment_id=None, data=None):
    body = {"size": len(PDF)}
    if attachment_id:
        body["attachmentId"] = attachment_id
    else:
        body["data"] = b64(data or PDF)
    return {"partId": part_id, "mimeType": "application/pdf", "filename": filename, "body": body}


@pytest.fixture
def gmail():
    with get_client(token_provider=lambda: "tok", backoff_base=0) as client:
        yield client


@pytest.fixture
def proveedor(db):
    return Proveedor.objects.create(nombre="Iberdrola", etiqueta_gmail="Iberdrola")


@pytest.fixture
def api():
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/labels").respond(
            json={
                "labels": [
                    {"id": "INBOX", "name": "INBOX"},
                    {"id": "Label_1", "name": "Gastos"},
                    {"id": "Label_2", "name": "Gastos/Iberdrola"},
                ]
            }
        )
        yield mock


def test_descarga_los_pdf_de_los_correos_nuevos(api, gmail, proveedor):
    api.get("/messages", params={"labelIds": "Label_2"}).respond(
        json={"messages": [{"id": "m2"}, {"id": "m1"}]}
    )
    api.get("/messages/m1").respond(
        json=mensaje("m1", adjuntos=[adjunto("1", "Factura 001.PDF", attachment_id="a1")])
    )
    api.get("/messages/m2").respond(
        json=mensaje(
            "m2",
            adjuntos=[adjunto("1", "fra-002.pdf"), adjunto("2", "logo.png", data=b"png")],
        )
    )
    route = api.get("/messages/m1/attachments/a1").respond(json={"data": b64(PDF), "size": 26})

    resultado = sincronizar_facturas(client=gmail)

    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert resultado.correos_nuevos == 2
    assert resultado.facturas_nuevas == 2
    assert not resultado.errores
    facturas = {f.nombre_archivo: f for f in FacturaRecibida.objects.all()}
    assert set(facturas) == {"Factura 001.PDF", "fra-002.pdf"}  # el PNG no es factura
    factura = facturas["Factura 001.PDF"]
    assert factura.proveedor == proveedor
    assert factura.archivo.read() == PDF
    assert factura.archivo.name.startswith("facturas/iberdrola/2025/10/factura-001")
    assert factura.correo.remitente == "Iberdrola <facturas@iberdrola.es>"


def test_cada_correo_se_procesa_una_sola_vez(api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    detalle = api.get("/messages/m1").respond(json=mensaje("m1", adjuntos=[adjunto("1", "f.pdf")]))

    sincronizar_facturas(client=gmail)
    resultado = sincronizar_facturas(client=gmail)

    assert detalle.call_count == 1
    assert resultado.correos_nuevos == 0
    assert FacturaRecibida.objects.count() == 1


def test_los_correos_sin_factura_quedan_registrados(api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(json=mensaje("m1"))

    resultado = sincronizar_facturas(client=gmail)

    assert resultado.facturas_nuevas == 0
    assert CorreoFactura.objects.filter(gmail_id="m1").exists()


def test_busca_solo_en_la_ventana_de_dias(api, gmail, proveedor):
    listado = api.get("/messages").respond(json={})
    sincronizar_facturas(client=gmail)
    assert listado.calls.last.request.url.params["q"] == "newer_than:30d"
    sincronizar_facturas(0, client=gmail)
    assert "q" not in listado.calls.last.request.url.params
    sincronizar_facturas(desde=date(2026, 1, 1), client=gmail)
    # 2026-01-01 00:00 en Madrid
    assert listado.calls.last.request.url.params["q"] == "after:1767222000"


def test_avisa_de_etiquetas_que_no_existen(api, gmail, db):
    Proveedor.objects.create(nombre="Repsol", etiqueta_gmail="Repsol")
    Proveedor.objects.create(nombre="Antiguo", etiqueta_gmail="Antiguo", activo=False)

    resultado = sincronizar_facturas(client=gmail)

    assert resultado.etiquetas_no_encontradas == ["Gastos/Repsol"]


def test_un_correo_que_falla_no_bloquea_el_resto_y_se_reintenta(api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m2"}, {"id": "m1"}]})
    api.get("/messages/m1").respond(404)
    api.get("/messages/m2").respond(json=mensaje("m2", adjuntos=[adjunto("1", "f.pdf")]))

    resultado = sincronizar_facturas(client=gmail)

    assert resultado.facturas_nuevas == 1
    assert len(resultado.errores) == 1
    assert not CorreoFactura.objects.filter(gmail_id="m1").exists()


def test_sin_permisos_en_el_buzon_se_aborta(api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(403)

    with pytest.raises(GmailAuthError):
        sincronizar_facturas(client=gmail)


def test_reintenta_ante_limites_de_gmail(api, gmail, proveedor):
    listado = api.get("/messages").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, json={})]
    )
    sincronizar_facturas(client=gmail)
    assert listado.call_count == 2


def test_solo_la_conciliacion_esta_programada(db):
    # Las descargas de Gmail y la subida a Drive se lanzan a mano con los botones
    assert list(Schedule.objects.values_list("func", flat=True)) == [
        "apps.administracion.tasks.conciliar_pagos_drive"
    ]


def test_el_boton_busca_desde_el_ultimo_correo_procesado(proveedor):
    from datetime import timedelta

    from django.utils import timezone

    from apps.administracion.tasks import desde_el_ultimo_correo

    hoy = timezone.localdate()
    assert desde_el_ultimo_correo(CorreoFactura.objects) == hoy - timedelta(days=30)
    hace_90 = timezone.now() - timedelta(days=90)
    CorreoFactura.objects.create(proveedor=proveedor, gmail_id="m1", recibido_en=hace_90)
    assert desde_el_ultimo_correo(CorreoFactura.objects) == (
        timezone.localtime(hace_90).date() - timedelta(days=7)
    )


@pytest.mark.parametrize("valor", ["Iberdrola", "Gastos/Iberdrola", " gastos/Iberdrola/ "])
def test_formulario_normaliza_la_etiqueta(db, valor):
    form = ProveedorForm(data={"nombre": "Iberdrola", "etiqueta_gmail": valor, "activo": True})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["etiqueta_gmail"] == "Iberdrola"


# --- Vistas ---------------------------------------------------------------------------------


@pytest.fixture
def administracion(client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    return client


def test_solo_administracion_ve_las_facturas(client, make_user):
    client.force_login(make_user(departments=["Comercial"]))
    assert client.get(reverse("administracion:facturas")).status_code == 403
    assert client.get(reverse("administracion:proveedores")).status_code == 403


def test_listado_y_descarga_de_facturas(administracion, api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(json=mensaje("m1", adjuntos=[adjunto("1", "f.pdf")]))
    sincronizar_facturas(client=gmail)
    factura = FacturaRecibida.objects.get()

    html = administracion.get(reverse("administracion:facturas")).content.decode()
    assert "f.pdf" in html
    detalle = reverse("administracion:factura_detalle", args=[factura.pk])
    assert detalle in html
    assert "Factura octubre" in administracion.get(detalle).content.decode()

    response = administracion.get(reverse("administracion:factura_archivo", args=[factura.pk]))
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == PDF


def test_alta_de_proveedor(administracion):
    response = administracion.post(
        reverse("administracion:proveedor_nuevo"),
        {"nombre": "Repsol", "etiqueta_gmail": "Gastos/Repsol", "activo": "on"},
    )
    assert response.status_code == 302
    assert Proveedor.objects.get().etiqueta_completa == "Gastos/Repsol"


def test_la_tarea_no_falla_si_gmail_no_esta_configurado(db):
    from apps.administracion.tasks import sincronizar_facturas_gmail

    assert sincronizar_facturas_gmail() == "Gmail no configurado"


def test_correos_sin_factura(administracion, api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m2"}, {"id": "m1"}]})
    api.get("/messages/m1").respond(json=mensaje("m1", asunto="Su factura está en el portal"))
    api.get("/messages/m2").respond(json=mensaje("m2", adjuntos=[adjunto("1", "f.pdf")]))
    sincronizar_facturas(client=gmail)

    html = administracion.get(reverse("administracion:correos_sin_factura")).content.decode()
    assert "Su factura está en el portal" in html
    assert "Factura octubre" not in html
    otro = Proveedor.objects.create(nombre="Repsol", etiqueta_gmail="Repsol")
    url = reverse("administracion:correos_sin_factura")
    html = administracion.get(f"{url}?proveedor={otro.pk}").content.decode()
    assert "Su factura está en el portal" not in html
    assert administracion.get(f"{url}?proveedor=xx").status_code == 200


def test_el_admin_enlaza_cada_adjunto(client, make_user, api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(json=mensaje("m1", adjuntos=[adjunto("1", "f.pdf")]))
    sincronizar_facturas(client=gmail)
    factura = FacturaRecibida.objects.get()
    client.force_login(make_user(is_superuser=True, is_staff=True))

    html = client.get(reverse("admin:administracion_facturarecibida_changelist")).content.decode()
    assert reverse("administracion:factura_archivo", args=[factura.pk]) in html


def test_el_admin_filtra_correos_sin_factura(client, make_user, api, gmail, proveedor):
    api.get("/messages").respond(json={"messages": [{"id": "m2"}, {"id": "m1"}]})
    api.get("/messages/m1").respond(json=mensaje("m1", asunto="Aviso sin PDF"))
    api.get("/messages/m2").respond(json=mensaje("m2", adjuntos=[adjunto("1", "f.pdf")]))
    sincronizar_facturas(client=gmail)
    client.force_login(make_user(is_superuser=True, is_staff=True))

    url = reverse("admin:administracion_correofactura_changelist")
    html = client.get(f"{url}?con_factura=no").content.decode()
    assert "Aviso sin PDF" in html
    assert "Factura octubre" not in html


# --- Subida manual --------------------------------------------------------------------------


@pytest.fixture
def correo_sin_pdf(proveedor):
    from django.utils import timezone

    return CorreoFactura.objects.create(
        proveedor=proveedor,
        gmail_id="m9",
        asunto="Su factura está en el portal",
        recibido_en=timezone.now(),
    )


def pdf(nombre="factura.pdf", contenido=PDF):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(nombre, contenido, content_type="application/pdf")


def test_subir_pdf_a_un_correo_sin_factura(administracion, correo_sin_pdf, make_user):
    url = reverse("administracion:subir_facturas", args=[correo_sin_pdf.pk])
    sin_factura = reverse("administracion:correos_sin_factura")
    assert url in administracion.get(sin_factura).content.decode()

    response = administracion.post(url, {"archivos": [pdf("a.pdf"), pdf("b.pdf")]})

    assert response.status_code == 302
    facturas = FacturaRecibida.objects.filter(correo=correo_sin_pdf).order_by("nombre_archivo")
    assert [f.nombre_archivo for f in facturas] == ["a.pdf", "b.pdf"]
    factura = facturas[0]
    assert factura.subida_a_mano
    assert factura.subida_por.email == "ana@andronautic.com"
    assert factura.recibida_en == correo_sin_pdf.recibido_en
    assert factura.archivo.read() == PDF
    # El correo sale de la pestaña y la factura aparece marcada en el listado
    assert "Su factura está en el portal" not in administracion.get(sin_factura).content.decode()
    html = administracion.get(reverse("administracion:facturas")).content.decode()
    assert "subida a mano" in html


@pytest.mark.parametrize(
    ("archivo", "error"),
    [
        (pdf("foto.png"), "no es un PDF"),
        (pdf("falso.pdf", b"hola, no soy un pdf"), "no parece un PDF"),
    ],
)
def test_solo_se_aceptan_pdf(administracion, correo_sin_pdf, archivo, error):
    url = reverse("administracion:subir_facturas", args=[correo_sin_pdf.pk])
    response = administracion.post(url, {"archivos": [archivo]})
    assert response.status_code == 200
    assert error in response.content.decode()
    assert not FacturaRecibida.objects.exists()


def test_subir_sin_elegir_fichero(administracion, correo_sin_pdf):
    url = reverse("administracion:subir_facturas", args=[correo_sin_pdf.pk])
    response = administracion.post(url, {})
    assert "Elige al menos un PDF" in response.content.decode()


def test_solo_administracion_puede_subir(client, make_user, correo_sin_pdf):
    client.force_login(make_user(email="eva@andronautic.com", departments=["Comercial"]))
    url = reverse("administracion:subir_facturas", args=[correo_sin_pdf.pk])
    assert client.post(url, {"archivos": [pdf()]}).status_code == 403


# --- Descartar ------------------------------------------------------------------------------


def test_descartar_un_correo_sin_factura(administracion, correo_sin_pdf, proveedor):
    sin_factura = reverse("administracion:correos_sin_factura")
    url = reverse("administracion:descartar_correo", args=[correo_sin_pdf.pk])
    assert url in administracion.get(sin_factura).content.decode()

    response = administracion.post(url, {"proveedor": proveedor.pk})

    assert response.url == f"{sin_factura}?proveedor={proveedor.pk}"
    correo_sin_pdf.refresh_from_db()
    assert correo_sin_pdf.descartado_en is not None
    assert correo_sin_pdf.descartado_por.email == "ana@andronautic.com"
    html = administracion.get(sin_factura).content.decode()  # el mensaje cita el asunto
    assert url not in html
    assert "Nada pendiente" in html
    assert '<span class="count">0</span>' in html


def test_descartar_solo_por_post_y_por_administracion(client, make_user, correo_sin_pdf):
    url = reverse("administracion:descartar_correo", args=[correo_sin_pdf.pk])
    client.force_login(make_user(departments=["Administración"]))
    assert client.get(url).status_code == 405
    client.force_login(make_user(email="eva@andronautic.com", departments=["Comercial"]))
    assert client.post(url).status_code == 403
    correo_sin_pdf.refresh_from_db()
    assert correo_sin_pdf.descartado_en is None


def test_recuperar_descartados_desde_el_admin(client, make_user, correo_sin_pdf):
    from django.utils import timezone

    correo_sin_pdf.descartado_en = timezone.now()
    correo_sin_pdf.save()
    client.force_login(make_user(is_superuser=True, is_staff=True))

    url = reverse("admin:administracion_correofactura_changelist")
    assert "Su factura está en el portal" in client.get(f"{url}?descartado=si").content.decode()
    client.post(url, {"action": "recuperar", "_selected_action": [correo_sin_pdf.pk]})

    correo_sin_pdf.refresh_from_db()
    assert correo_sin_pdf.descartado_en is None
    assert CorreoFactura.objects.pendientes().filter(pk=correo_sin_pdf.pk).exists()


# --- Vista por meses ------------------------------------------------------------------------


def crear_factura(proveedor, cuando, gmail_id):
    from django.core.files.base import ContentFile

    correo = CorreoFactura.objects.create(
        proveedor=proveedor, gmail_id=gmail_id, recibido_en=cuando
    )
    factura = FacturaRecibida(
        proveedor=proveedor, correo=correo, gmail_part_id="1", recibida_en=cuando, tamano=1
    )
    factura.nombre_archivo = f"{gmail_id}.pdf"
    factura.archivo.save(f"{gmail_id}.pdf", ContentFile(PDF), save=False)
    factura.save()
    return factura


def madrid(*args):
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    return timezone.datetime(*args, tzinfo=ZoneInfo("Europe/Madrid"))


def test_por_meses_marca_las_facturas_de_cada_mes(administracion, proveedor):
    otro = Proveedor.objects.create(nombre="Repsol", etiqueta_gmail="Repsol")
    Proveedor.objects.create(nombre="Antiguo", etiqueta_gmail="Antiguo", activo=False)
    crear_factura(proveedor, madrid(2025, 3, 10), "a")
    crear_factura(proveedor, madrid(2025, 3, 20), "b")
    # 1 de mayo a las 00:30 en Madrid es 30 de abril en UTC: cuenta como mayo
    crear_factura(proveedor, madrid(2025, 5, 1, 0, 30), "c")
    crear_factura(proveedor, madrid(2024, 7, 1), "d")

    response = administracion.get(reverse("administracion:facturas_por_mes"), {"anio": 2025})

    filas = {f["proveedor"].nombre: f["meses"] for f in response.context["filas"]}
    assert list(filas) == ["Iberdrola", "Repsol"]  # el inactivo sin facturas no aparece
    assert len(filas["Iberdrola"]) == 12
    assert [m["facturas"] for m in filas["Iberdrola"]] == [0, 0, 2, 0, 1, 0, 0, 0, 0, 0, 0, 0]
    assert all(m["facturas"] == 0 for m in filas["Repsol"])
    assert response.context["anios"][-2:] == [2025, 2024]
    html = response.content.decode()
    assert f"?proveedor={proveedor.pk}&amp;mes=2025-03" in html
    assert "Iberdrola, Mar: 2 facturas" in html
    assert otro.nombre in html


def test_por_meses_usa_el_año_actual_por_defecto(administracion, proveedor):
    from django.utils import timezone

    response = administracion.get(reverse("administracion:facturas_por_mes"), {"anio": "xx"})
    assert response.context["anio"] == timezone.localdate().year


def test_filtro_por_mes_en_el_listado(administracion, proveedor):
    crear_factura(proveedor, madrid(2025, 3, 10), "marzo")
    crear_factura(proveedor, madrid(2025, 4, 10), "abril")
    url = reverse("administracion:facturas")

    html = administracion.get(url, {"proveedor": proveedor.pk, "mes": "2025-03"}).content.decode()

    assert "marzo.pdf" in html
    assert "abril.pdf" not in html
    assert "Marzo 2025" in html
    assert administracion.get(url, {"mes": "2025-13"}).status_code == 200


def test_eliminar_un_proveedor_borra_sus_correos_facturas_y_pdf(administracion, proveedor):
    from django.core.files.base import ContentFile
    from django.utils import timezone

    correo = CorreoFactura.objects.create(
        proveedor=proveedor, gmail_id="m1", recibido_en=timezone.now()
    )
    factura = FacturaRecibida(
        proveedor=proveedor, correo=correo, gmail_part_id="1", nombre_archivo="f.pdf",
        recibida_en=correo.recibido_en,
    )  # fmt: skip
    factura.archivo.save("f.pdf", ContentFile(PDF), save=False)
    factura.save()
    storage, nombre = factura.archivo.storage, factura.archivo.name
    otro = Proveedor.objects.create(nombre="Otro", etiqueta_gmail="Otro")
    url = reverse("administracion:proveedor_eliminar", args=[proveedor.pk])

    html = administracion.get(url).content.decode()
    assert "1 factura" in html and "1 correo" in html
    respuesta = administracion.post(url)

    assert respuesta.status_code == 302
    assert list(Proveedor.objects.all()) == [otro]
    assert not CorreoFactura.objects.exists() and not FacturaRecibida.objects.exists()
    assert not storage.exists(nombre)


def test_solo_administracion_puede_eliminar_proveedores(client, make_user, proveedor):
    client.force_login(make_user(departments=["Comercial"]))
    url = reverse("administracion:proveedor_eliminar", args=[proveedor.pk])
    assert client.post(url).status_code == 403
    assert Proveedor.objects.filter(pk=proveedor.pk).exists()
