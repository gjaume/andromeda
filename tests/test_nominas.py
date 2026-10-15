"""Nóminas: descarga desde la etiqueta de Gmail y listado. Nombres de empleados inventados."""

from datetime import UTC, date, datetime

import pytest
import respx
from django.urls import reverse

from apps.administracion.models import CorreoNomina, Empresa, Nomina
from apps.administracion.nominas import clasificar, periodo, sincronizar_nominas
from integrations.gmail import get_client
from tests.test_facturas import API, adjunto, mensaje

Tipo = Nomina.Tipo


@pytest.fixture
def empresas(db):
    # Las crea la migración 0009: ANDROMEDA SOLUTIONS y ANDROMEDA TECH GROUP
    return list(Empresa.objects.order_by("nombre"))


@pytest.fixture
def gmail():
    with get_client(token_provider=lambda: "tok", backoff_base=0) as client:
        yield client


@pytest.fixture
def api():
    with respx.mock(base_url=API, assert_all_called=False) as mock:
        mock.get("/labels").respond(
            json={
                "labels": [
                    {"id": "Label_1", "name": "Gastos"},
                    {"id": "Label_9", "name": "Gastos/Nominas"},
                ]
            }
        )
        yield mock


@pytest.mark.parametrize(
    "nombre, tipo",
    [
        ("202609 Nóminas Andromeda Solutions SL.pdf", Tipo.NOMINAS),
        ("202607 Nóminas Andromeda Solutions SL ok.pdf", Tipo.NOMINAS),
        ("202601 Nóminas Andromeda Solutions, S.L.U.pdf", Tipo.NOMINAS),
        ("202609 Resumen nóminas Andromeda Solutions SLU.pdf", Tipo.RESUMEN),
        ("202602 Resumen nóminas Andromeda Solutions SLU OK.pdf", Tipo.RESUMEN),
        ("202609 - Nóminas Andromeda Solutions SL - Pepa Pérez.pdf", Tipo.EMPLEADO),
        ("202605 Nóminas Andromeda Solutions SL-Pepa Pérez.pdf", Tipo.EMPLEADO),
        ("202606 Nóminas Bono Andromeda Solutions SL - PEPA PEREZ.pdf", Tipo.EMPLEADO),
        ("202605 Nómina Bonus - Pepa Pérez.pdf", Tipo.EMPLEADO),
        ("202602 NOMINA PEREZ GARCIA PEPA.pdf", Tipo.EMPLEADO),
        ("202602 PÉREZ GARCÍA, PEPA.pdf", Tipo.EMPLEADO),
        ("202603 Andromeda Solutions SLU - Pepa Pérez.pdf", Tipo.EMPLEADO),
    ],
)
def test_clasifica_los_pdf_por_su_nombre(empresas, nombre, tipo):
    assert clasificar(nombre, empresas) == tipo


def test_el_mes_sale_del_nombre_o_del_correo():
    correo = datetime(2026, 10, 15, 9, tzinfo=UTC)
    assert periodo("202607 Nóminas Andromeda Solutions SL ok.pdf", correo) == date(2026, 7, 1)
    assert periodo("Nóminas.pdf", correo) == date(2026, 10, 1)


def test_guarda_el_de_todos_y_el_resumen_pero_no_los_de_cada_empleado(api, gmail, empresas):
    api.get("/messages", params={"labelIds": "Label_9"}).respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(
        json=mensaje(
            "m1",
            asunto="Nóminas 09/26 - Andromeda Solutions",
            adjuntos=[
                adjunto("1", "logo.png"),
                adjunto("2", "202609 - Nóminas Andromeda Solutions SL - Pepa Pérez.pdf"),
                adjunto("3", "202609 Nóminas Andromeda Solutions SL.pdf"),
                adjunto("4", "202609 Resumen nóminas Andromeda Solutions SLU.pdf"),
            ],
        )
    )

    resultado = sincronizar_nominas(client=gmail)

    assert (resultado.correos_nuevos, resultado.nominas_nuevas) == (1, 2)
    nominas = {n.tipo: n for n in Nomina.objects.all()}
    assert set(nominas) == {Tipo.NOMINAS, Tipo.RESUMEN}
    assert nominas[Tipo.NOMINAS].periodo == date(2026, 9, 1)
    assert nominas[Tipo.NOMINAS].empresa == empresas[0]
    assert nominas[Tipo.NOMINAS].archivo.name.startswith("nominas/andromeda-solutions/2026/09/")


def test_si_falta_el_de_todos_guarda_los_de_cada_empleado(api, gmail, empresas):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(
        json=mensaje(
            "m1",
            asunto="Remisión nóminas - Febrero",
            adjuntos=[
                adjunto("1", "202602 PÉREZ GARCÍA, PEPA.pdf"),
                adjunto("2", "202602 Resumen nóminas Andromeda Solutions SLU.pdf"),
            ],
        )
    )

    sincronizar_nominas(client=gmail)

    tipos = sorted(Nomina.objects.values_list("tipo", flat=True))
    assert tipos == [Tipo.EMPLEADO, Tipo.RESUMEN]
    # El PDF del empleado no nombra la empresa: se toma del resumen
    assert set(Nomina.objects.values_list("empresa", flat=True)) == {empresas[0].pk}


def test_cada_correo_se_procesa_una_sola_vez(api, gmail, empresas):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    detalle = api.get("/messages/m1").respond(json=mensaje("m1"))

    sincronizar_nominas(client=gmail)
    resultado = sincronizar_nominas(client=gmail)

    assert detalle.call_count == 1
    assert resultado.correos_nuevos == 0
    assert CorreoNomina.objects.count() == 1


def test_avisa_si_no_existe_la_etiqueta(gmail, db):
    with respx.mock(base_url=API) as mock:
        mock.get("/labels").respond(json={"labels": [{"id": "Label_1", "name": "Gastos"}]})
        resultado = sincronizar_nominas(client=gmail)
    assert resultado.etiqueta_no_encontrada


@pytest.fixture
def administracion(client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    return client


def test_listado_y_descarga(api, gmail, empresas, administracion):
    api.get("/messages").respond(json={"messages": [{"id": "m1"}]})
    api.get("/messages/m1").respond(
        json=mensaje("m1", adjuntos=[adjunto("1", "202609 Nóminas Andromeda Solutions SL.pdf")])
    )
    sincronizar_nominas(client=gmail)
    nomina = Nomina.objects.get()

    html = administracion.get(reverse("administracion:nominas")).content.decode()
    assert "202609 Nóminas Andromeda Solutions SL.pdf" in html
    assert "Septiembre 2026" in html
    filtrado = administracion.get(reverse("administracion:nominas"), {"tipo": "resumen"})
    assert "202609 Nóminas" not in filtrado.content.decode()

    pdf = administracion.get(reverse("administracion:nomina_archivo", args=[nomina.pk]))
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"


def test_solo_administracion_ve_las_nominas(client, make_user):
    client.force_login(make_user(departments=["Comercial"]))
    assert client.get(reverse("administracion:nominas")).status_code == 403
