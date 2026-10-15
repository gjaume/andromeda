"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
Tax invoice PAID
Proveedor Inventado
5th March 2026 - $60.50 via Paddle.com
Invoice to Invoice from
Empresa de Prueba SL Paddle.com Market Ltd
Invoice details
Invoice reference: 111-222333
Billing period: 5th March 2026 - 5th April 2026
Transaction: txn_00000000000000000000000000
Currency code: USD
Transaction
Product Qty Unit price Tax rate Amount
Plan Inventado 1 $50.00 21% $50.00
5th March 2026 - 5th April 2026
Plan Inventado Premium - Monthly
Subtotal $50.00
VAT $10.50
Total $60.50
Amount paid $60.50
Tax breakdown
Tax % Tax
21% $10.50
"""


def test_recibo_con_iva():
    datos = registro["paddle_billing"].extraer(Documento.desde_texto(FACTURA))

    assert (datos.numero, datos.fecha, datos.moneda) == ("111-222333", date(2026, 3, 5), "USD")
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("50.00"),
        Decimal("10.50"),
        Decimal("60.50"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == (
        "Plan Inventado · 5th March 2026 - 5th April 2026 · Plan Inventado Premium - Monthly"
    )
    assert (linea.cantidad, linea.precio_unitario, linea.importe, linea.impuesto_pct) == (
        Decimal("1"),
        Decimal("50.00"),
        Decimal("50.00"),
        Decimal("21"),
    )
    assert comprobar(datos) == []


def test_el_formato_antiguo_de_paddle_no_es_este():
    antiguo = "Billing period Quantity Price\nCloud Starter 1 €24.00\nYOUR ORDER €24.00"
    with pytest.raises(ExtraccionError):
        registro["paddle_billing"].extraer(Documento.desde_texto(antiguo))
