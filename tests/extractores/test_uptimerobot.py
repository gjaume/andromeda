"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
Invoice #10000001 May 21, 2026
UptimeRobot s. r. o. Empresa Inventada SL
Calle Inventada 1 Calle Falsa 2
00000 Bratislava Palma
Slovakia Spain
Business ID: 00000000 VAT ID: ESB00000000
VAT ID: SK0000000000
Item Billed Amount
Team 50 monthly € 29.00
SMS credits monthly € 5.00
VAT 0.0 % € 0.00
Total € 34.00
Payment method: Credit card (Stripe)
Note: Reverse charge (according to §74 of Act 222/2004 on value added tax)
Thank you for using UptimeRobot
"""


def test_factura():
    datos = registro["uptimerobot"].extraer(
        Documento.desde_texto([FACTURA, ""], "uptimerobot-invoice-0000.pdf")
    )

    assert datos.tipo == "factura"
    assert datos.numero == "10000001"
    assert datos.fecha == date(2026, 5, 21)
    assert datos.moneda == "EUR"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("34.00"),
        Decimal("0.00"),
        Decimal("34.00"),
    )
    assert [(linea.descripcion, linea.importe) for linea in datos.lineas] == [
        ("Team 50 (monthly)", Decimal("29.00")),
        ("SMS credits (monthly)", Decimal("5.00")),
    ]
    assert datos.lineas[0].impuesto_pct == Decimal("0.0")
    assert comprobar(datos) == []


def test_sin_iva_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["uptimerobot"].extraer(Documento.desde_texto(FACTURA.replace("VAT 0.0 %", "")))
