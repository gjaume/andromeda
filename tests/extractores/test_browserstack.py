"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
Invoice
Bill to: Ship Invoice Date: Mar-14-2026
ejemplo.com to:
Invoice #: INV00000123
Admin Ejemplo ejemplo.com
Spain, 00000 Admin Ejemplo Subscription ID: A-S00000000
Spain, 00000
Account Number: 1234567
VAT Number: B00000000
Currency: USD
Plan Service Period Units Amount (USD)
Automate - Team
Mar 14, 2026 - Apr 13, 2026 3 users $1,029.00
(1 month)
Subtotal $1,029.00
Total Amount $1,029.00
BrowserStack Inc., 1 Example Street, Plano, TX 00000, U.S.A. VAT ES: EU000000000
Page: 1
"""


def test_factura_mensual():
    datos = registro["browserstack"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "INV00000123"
    assert datos.fecha == date(2026, 3, 14)
    assert datos.moneda == "USD"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1029.00"),
        Decimal("0.00"),
        Decimal("1029.00"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == "Automate - Team (Mar 14, 2026 - Apr 13, 2026)"
    assert (linea.cantidad, linea.importe) == (Decimal("3"), Decimal("1029.00"))
    assert comprobar(datos) == []


def test_sin_planes_es_un_error():
    sin_planes = FACTURA.replace("Mar 14, 2026 - Apr 13, 2026 3 users $1,029.00\n", "")
    with pytest.raises(ExtraccionError, match="planes"):
        registro["browserstack"].extraer(Documento.desde_texto(sin_planes))
