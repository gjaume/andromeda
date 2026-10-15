"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, registro
from apps.administracion.extraccion.servicio import comprobar

NUMERO_SEGUIDO = (
    "Order Number / Invoice: #11111111-222222222 Payment method: Mastercard card ending 0000"
)
NUMERO_PARTIDO = (
    "Order Number / Invoice: #11111111- Payment method: Mastercard card ending\n222222222 0000"
)

FACTURA = """\
via Paddle.com
Invoice
PAID
Invoice to Invoice from
Empresa de Prueba SL Paddle.com Market Ltd
Your order
{numero}
Billing date: 17 Mar 2026 Currency: EUR
Billing period Quantity Price
Cloud Starter 17 Mar 2026 - 16 Apr 2026 1 €20.00
VAT (0%) €0.00
YOUR ORDER €20.00
No VAT - Supply may be subject to reverse
charge in the country of receipt
"""


@pytest.mark.parametrize("numero", [NUMERO_SEGUIDO, NUMERO_PARTIDO])
def test_factura(numero):
    datos = registro["paddle"].extraer(Documento.desde_texto(FACTURA.format(numero=numero)))

    assert (datos.numero, datos.fecha, datos.moneda) == (
        "11111111-222222222",
        date(2026, 3, 17),
        "EUR",
    )
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("20.00"),
        Decimal("0.00"),
        Decimal("20.00"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == "Cloud Starter (17 Mar 2026 - 16 Apr 2026)"
    assert (linea.cantidad, linea.importe, linea.impuesto_pct) == (
        Decimal("1"),
        Decimal("20.00"),
        Decimal("0"),
    )
    assert comprobar(datos) == []
