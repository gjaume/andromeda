"""Totales de la vista por meses: por proveedor, por mes y por moneda."""

from datetime import datetime
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from apps.administracion.models import CorreoFactura, FacturaRecibida, Proveedor

ANIO = 2025  # año pasado fijo: ningún mes es "futuro"


@pytest.fixture
def crear(db):
    proveedores: dict[str, Proveedor] = {}

    def crear(proveedor, mes, total, *, moneda="EUR", tipo="factura", base=None, **extra):
        if proveedor not in proveedores:
            proveedores[proveedor] = Proveedor.objects.create(
                nombre=proveedor, etiqueta_gmail=proveedor
            )
        cuando = timezone.make_aware(datetime(ANIO, mes, 10, 12))
        correo = CorreoFactura.objects.create(
            proveedor=proveedores[proveedor],
            gmail_id=f"m{CorreoFactura.objects.count()}",
            recibido_en=cuando,
        )
        factura = FacturaRecibida(
            proveedor=proveedores[proveedor],
            correo=correo,
            gmail_part_id="1",
            nombre_archivo="f.pdf",
            recibida_en=cuando,
            tipo=tipo,
            moneda=moneda,
            total=None if total is None else Decimal(total),
            base_imponible=None if base is None else Decimal(base),
            **extra,
        )
        factura.archivo.save("f.pdf", ContentFile(b"%PDF-1.4"), save=False)
        factura.save()
        return factura

    return crear


@pytest.fixture
def cliente(client, make_user):
    client.force_login(make_user(departments=["Administración"]))
    return client


def ver(cliente, **params):
    return cliente.get(reverse("administracion:facturas_por_mes"), {"anio": ANIO, **params})


def importes(importes):
    return (importes.lista, importes.facturas, importes.sin_importe)


def test_totales_por_proveedor_mes_y_moneda(crear, cliente):
    crear("Acme", 1, "121.00")
    crear("Acme", 1, "-21.00", tipo="abono")
    original = crear("Acme", 2, "50.00")
    crear("Acme", 2, "50.00", duplicada_de=original)  # no cuenta
    crear("Acme", 2, "50.00", tipo="recibo")  # no cuenta
    crear("Acme", 3, None)  # PDF sin leer: cuenta como factura, sin importe
    crear("Nube", 1, "49.00", moneda="USD")
    crear("Nube", 1, "10.00")

    contexto = ver(cliente).context
    acme, nube = contexto["filas"]
    assert importes(acme["meses"][0]["importes"]) == ([("EUR", Decimal("100.00"))], 2, 0)
    assert importes(acme["meses"][1]["importes"]) == ([("EUR", Decimal("50.00"))], 1, 0)
    assert importes(acme["meses"][2]["importes"]) == ([], 1, 1)
    assert importes(acme["total"]) == ([("EUR", Decimal("150.00"))], 4, 1)
    assert importes(nube["total"]) == (
        [("EUR", Decimal("10.00")), ("USD", Decimal("49.00"))],
        2,
        0,
    )
    enero = contexto["total_meses"][0]
    assert enero.lista == [("EUR", Decimal("110.00")), ("USD", Decimal("49.00"))]
    assert contexto["total_anio"].lista == [("EUR", Decimal("160.00")), ("USD", Decimal("49.00"))]


def test_base_imponible(crear, cliente):
    crear("Acme", 1, "121.00", base="100.00")
    contexto = ver(cliente, importe="base").context
    assert contexto["total_anio"].lista == [("EUR", Decimal("100.00"))]


def test_se_muestran_los_importes(crear, cliente):
    crear("Acme", 1, "1234.50")
    crear("Acme", 2, None)
    html = ver(cliente).content.decode()
    assert "1.234,50 €" in html
    assert "+1 sin importe" in html
    assert "Total 2025" in html


def test_por_defecto_manda_la_fecha_de_la_factura(crear, cliente):
    from datetime import date

    crear("Acme", 2, "10.00", fecha_factura=date(ANIO, 1, 31))  # llegó en febrero
    crear("Acme", 3, "20.00")  # sin fecha de factura: cuenta la del correo

    meses = ver(cliente).context["filas"][0]["meses"]
    assert [m["facturas"] for m in meses[:3]] == [1, 0, 1]
    meses = ver(cliente, fecha="correo").context["filas"][0]["meses"]
    assert [m["facturas"] for m in meses[:3]] == [0, 1, 1]


def test_la_fecha_de_la_factura_puede_caer_en_otro_anio(crear, cliente):
    from datetime import date

    crear("Acme", 1, "10.00", fecha_factura=date(ANIO - 1, 12, 30))
    contexto = ver(cliente).context
    assert contexto["total_anio"].facturas == 0
    assert ANIO - 1 in contexto["anios"]


@pytest.mark.parametrize(("fecha", "esperadas"), [({}, 1), ({"fecha": "correo"}, 0)])
def test_el_listado_filtra_el_mes_con_el_mismo_criterio(crear, cliente, fecha, esperadas):
    from datetime import date

    crear("Acme", 2, "10.00", fecha_factura=date(ANIO, 1, 31))
    respuesta = cliente.get(reverse("administracion:facturas"), {"mes": f"{ANIO}-01", **fecha})
    assert len(respuesta.context["facturas"]) == esperadas
