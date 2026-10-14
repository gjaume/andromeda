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


def test_la_sincronizacion_queda_programada(db):
    tarea = Schedule.objects.get(name="Sincronizar facturas de Gmail")
    assert tarea.func == "apps.administracion.tasks.sincronizar_facturas_gmail"
    assert tarea.minutes == 240


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
    assert "Factura octubre" in html

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
