"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
COOIDI CONSULTORES SL
Calle Inventada, 1, 2-3
Ciudad Ficticia (00000), Barcelona, España
B00000000
facturas@example.com
Cliente
EMPRESA CLIENTE SL
Cl. Falsa 123
Palma (07000), Illes Balears,
España
B11111111
VAT B11111111
FACTURA #BS99001
Fecha 05/02/2026
Vencimiento: 07/03/2026
CONCEPTO PRECIO UNIDADES SUBTOTAL IVA TOTAL
"""

UN_CONCEPTO = (
    CABECERA
    + """\
Bonificaciones por Personal Investigador
BBSS - Honorarios correspondientes al ahorro del 4o 1.250,00€ 1 1.250,00€ 21% 1.512,50€
Trimestre 2025
BASE IMPONIBLE 1.250,00€
IVA 21% 262,50€
TOTAL 1.512,50€
Pagar por transferencia bancaria al siguiente número de cuenta ES00 0000 0000 0000 0000 0000
"""
)

CON_AJUSTE = (
    CABECERA
    + """\
Bonificaciones por Personal Investigador
BBSS - Honorarios correspondientes al ahorro del 1er 100,00€ 1 100,00€ 21% 121,00€
Trimestre 2026
Bonificaciones por Personal Investigador - Ajuste
BBSS - Honorarios correspondientes a la regulación del -10,50€ 1 -10,50€ 21% -12,71€
ahorro generado en el año 2025
BASE IMPONIBLE 89,50€
IVA 21% 18,80€
TOTAL 108,30€
"""
)


def test_factura_con_un_concepto():
    datos = registro["cooidi"].extraer(Documento.desde_texto(UN_CONCEPTO))

    assert datos.numero == "BS99001"
    assert datos.fecha == date(2026, 2, 5)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1250.00"),
        Decimal("262.50"),
        Decimal("1512.50"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == (
        "Bonificaciones por Personal Investigador: BBSS - Honorarios correspondientes al "
        "ahorro del 4o Trimestre 2025"
    )
    assert (linea.cantidad, linea.precio_unitario, linea.importe, linea.impuesto_pct) == (
        Decimal("1"),
        Decimal("1250.00"),
        Decimal("1250.00"),
        Decimal("21"),
    )
    assert comprobar(datos) == []


def test_factura_con_ajuste_negativo():
    datos = registro["cooidi"].extraer(Documento.desde_texto(CON_AJUSTE))

    assert [linea.descripcion for linea in datos.lineas] == [
        "Bonificaciones por Personal Investigador: BBSS - Honorarios correspondientes al "
        "ahorro del 1er Trimestre 2026",
        "Bonificaciones por Personal Investigador - Ajuste: BBSS - Honorarios correspondientes "
        "a la regulación del ahorro generado en el año 2025",
    ]
    assert [linea.importe for linea in datos.lineas] == [Decimal("100.00"), Decimal("-10.50")]
    assert datos.base_imponible == Decimal("89.50")
    assert comprobar(datos) == []


def test_sin_conceptos_es_un_error():
    texto = CABECERA + "BASE IMPONIBLE 0,00€\nIVA 21% 0,00€\nTOTAL 0,00€\n"
    with pytest.raises(ExtraccionError):
        registro["cooidi"].extraer(Documento.desde_texto(texto))
