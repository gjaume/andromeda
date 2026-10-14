"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

PORTADA = """\
Hetzner Online GmbH • Industriestr. 25 • 91710 Gunzenhausen • Germany
Customer ID: K0000000000
Invoice no.: 080000000001
Invoice date: 12/03/2026
Invoice 080000000001
Overview
Service Period Total (excl. VAT) Tax Total
Dedicated Server 02/2026 € 100.50 € 0.00A7 € 100.50
Storage 02/2026 € 10.00 € 0.00A7 € 10.00
Total € 110.50 € 0.00 € 110.50
Tax code Tax rate Total (excl. VAT) Tax Total
A7 0 % € 110.50 € 0.00 € 110.50
Total € 110.50 € 0.00 € 110.50
Amount due: € 110.50
"""

DETALLE = """\
Product
Pos count Product Unit Quantity Unit Price Price (excl. VAT)
Dedicated Server (02/2026)
1 2 1 TB NVMe SSD Months 2 € 9.0000 € 18.0000
2 1 Server Auction Months 1 € 82.5000 € 82.5000
3 1 TB add. Traffic (1 TB incl. traffic) TB 0 € 1.0000 € 0.0000
Subtotal (excl. VAT) € 100.50
Storage (02/2026)
4 1 BX50 Storage Box Months 1 € 10.0000 € 10.0000
Subtotal (excl. VAT) € 10.00
"""


def test_factura_mensual():
    datos = registro["hetzner"].extraer(Documento.desde_texto([PORTADA, DETALLE]))

    assert datos.numero == "080000000001"
    assert datos.fecha == date(2026, 3, 12)
    assert datos.moneda == "EUR"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("110.50"),
        Decimal("0.00"),
        Decimal("110.50"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Dedicated Server: 1 TB NVMe SSD",
        "Dedicated Server: Server Auction",
        "Dedicated Server: TB add. Traffic (1 TB incl. traffic)",
        "Storage: BX50 Storage Box",
    ]
    primera = datos.lineas[0]
    assert (primera.cantidad, primera.precio_unitario, primera.importe) == (
        Decimal("2"),
        Decimal("9.0000"),
        Decimal("18.00"),
    )
    assert primera.impuesto_pct == Decimal("0")
    assert comprobar(datos) == []


def test_sin_detalle_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["hetzner"].extraer(Documento.desde_texto([PORTADA]))
