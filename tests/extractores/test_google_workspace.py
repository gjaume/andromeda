"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

PORTADA = """\
Google Cloud EMEA Limited
Invoice Calle Inventada
Dublin 2
Ireland
Invoice number: 1000000001
VAT number: IE0000000XX
Bill to
Persona Ficticia
Empresa Ficticia S.L.
VAT number: ES B00000000
Details Google Workspace
.In..v.o..ic..e. .n.u..m..b..e.r........................1..0..0.0..0.0..0.0..0.1......
.In..v.o..ic..e. .d.a..t.e.......N..o..v. .3..0.,. .2.0..2.5..... Total in EUR €223.60
.B.i.l.li.n.g.. I.D.................................0..0..0.0..-0..0.0..0.-.0..0.0..0.
Summary for Nov 1, 2025 - Nov 30, 2025
Subtotal in EUR €223.60
VAT (0%) €0.00
Total in EUR €223.60
Services subject to the reverse charge - VAT to be accounted for by the recipient as per \
Article 196 of Council Directive 2006/112/EC
Page 1 of 2
"""

DETALLE = """\
Invoice
Invoice number: 1000000001
Subscription Description Interval Quantity Amount(€)
Google Workspace Business Standard Usage Nov 1 - Nov 9 12 43.20
Google Workspace Business Standard - Archived User Usage Nov 1 - Nov 30 2 6.40
Google Workspace Business Standard Usage Nov 10 - Nov 29 13 160.00
Google Workspace Business Standard Usage Nov 30 14 14.00
Subtotal in EUR €223.60
VAT (0%) €0.00
Total in EUR €223.60
Page 2 of 2
"""


def test_factura_mensual():
    datos = registro["google_workspace"].extraer(Documento.desde_texto([PORTADA, DETALLE]))

    assert datos.numero == "1000000001"
    assert datos.fecha == date(2025, 11, 30)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("223.60"),
        Decimal("0.00"),
        Decimal("223.60"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Google Workspace Business Standard Usage (Nov 1 - Nov 9, 2025)",
        "Google Workspace Business Standard - Archived User Usage (Nov 1 - Nov 30, 2025)",
        "Google Workspace Business Standard Usage (Nov 10 - Nov 29, 2025)",
        "Google Workspace Business Standard Usage (Nov 30, 2025)",
    ]
    primera = datos.lineas[0]
    assert (primera.cantidad, primera.importe, primera.impuesto_pct) == (
        Decimal("12"),
        Decimal("43.20"),
        Decimal("0"),
    )
    assert comprobar(datos) == []


def test_sin_detalle_es_un_error():
    with pytest.raises(ExtraccionError, match="detalle"):
        registro["google_workspace"].extraer(Documento.desde_texto([PORTADA]))
