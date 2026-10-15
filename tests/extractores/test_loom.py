"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

# El guion del nº de factura sale del PDF como un carácter nulo
FACTURA = """\
Invoice
Invoice number 11111111\x000099
Date of issue February 6, 2026
Date due February 6, 2026
Loom, Inc. Bill to
Empresa de Prueba SL
$31.99 USD due February 6, 2026
Pay online
Description Qty Unit price Amount
Increased quantity of Loom Business + AI from 1 to 2 on 04 Feb 2026 2 $1.99
Feb 4 – Feb 6, 2026
Loom Business + AI 2 $15.00 $30.00
Feb 6 – Mar 6, 2026
Subtotal $31.99
Total $31.99
Amount due $31.99 USD
Page 1 of 1
"""


def test_factura_con_cambio_de_plazas():
    datos = registro["loom"].extraer(Documento.desde_texto(FACTURA))

    assert (datos.numero, datos.fecha, datos.moneda) == ("11111111-0099", date(2026, 2, 6), "USD")
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("31.99"),
        Decimal("0.00"),
        Decimal("31.99"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Increased quantity of Loom Business + AI from 1 to 2 on 04 Feb 2026 (Feb 4 – Feb 6, 2026)",
        "Loom Business + AI (Feb 6 – Mar 6, 2026)",
    ]
    prorrateo, plan = datos.lineas
    assert (prorrateo.cantidad, prorrateo.precio_unitario, prorrateo.importe) == (
        Decimal("2"),
        None,
        Decimal("1.99"),
    )
    assert (plan.cantidad, plan.precio_unitario, plan.importe) == (
        Decimal("2"),
        Decimal("15.00"),
        Decimal("30.00"),
    )
    assert comprobar(datos) == []


def test_sin_conceptos_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["loom"].extraer(Documento.desde_texto(FACTURA.replace("Unit price", "Precio")))
