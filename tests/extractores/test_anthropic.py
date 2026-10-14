"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

Los "\\x00" imitan los signos que la fuente del PDF no tiene (guiones y rayas).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
Anthropic, PBC Bill to
1 Example Street Empresa Inventada SL
San Francisco, California 94000 Calle Falsa 1
United States 07000 Palma
support@anthropic.com Spain
ES NIF B00000000
"""

TABLA = """\
Description Qty Unit price Amount
Claude Pro 2 €18.00 €36.00
Mar 5 – Apr 5, 2026
Subtotal €36.00
Total €36.00
"""

FACTURA = f"""\
Invoice
Invoice number ABCD1234\x000042
Date of issue March 5, 2026
Date due March 5, 2026
{CABECERA}€36.00 due March 5, 2026
Pay online
{TABLA}Amount due €36.00
Page 1 of 1
"""

RECIBO = f"""\
Receipt
Invoice number ABCD1234\x000042
Receipt number 1111\x002222\x003333
Date paid March 6, 2026
{CABECERA}€36.00 paid on March 6, 2026
{TABLA}Amount paid €36.00
Payment history
Payment method Date Amount paid Receipt number
Mastercard - 0000 March 6, 2026 €36.00 1111\x002222\x00
3333
Page 1 of 1
"""


def test_factura():
    datos = registro["anthropic"].extraer(
        Documento.desde_texto(FACTURA, "Invoice-ABCD1234-0042.pdf")
    )

    assert datos.tipo == "factura"
    assert datos.numero == "ABCD1234-0042"
    assert datos.fecha == date(2026, 3, 5)
    assert datos.moneda == "EUR"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("36.00"),
        Decimal("0.00"),
        Decimal("36.00"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == "Claude Pro (Mar 5 – Apr 5, 2026)"
    assert (linea.cantidad, linea.precio_unitario, linea.importe) == (
        Decimal("2"),
        Decimal("18.00"),
        Decimal("36.00"),
    )
    assert comprobar(datos) == []


def test_recibo():
    datos = registro["anthropic"].extraer(
        Documento.desde_texto(RECIBO, "Receipt-1111-2222-3333.pdf")
    )

    assert datos.tipo == "recibo"
    assert datos.numero == "1111-2222-3333"
    assert datos.fecha == date(2026, 3, 6)
    assert datos.total == Decimal("36.00")
    assert comprobar(datos) == []


def test_recibo_sin_numero_en_cabecera_lo_toma_del_archivo():
    texto = RECIBO.replace("Receipt number 1111\x002222\x003333\n", "")
    datos = registro["anthropic"].extraer(
        Documento.desde_texto(texto, "Receipt-1111-2222-3333.pdf")
    )

    assert datos.numero == "1111-2222-3333"


def test_sin_conceptos_es_un_error():
    texto = FACTURA.replace("Claude Pro 2 €18.00 €36.00\n", "")
    with pytest.raises(ExtraccionError):
        registro["anthropic"].extraer(Documento.desde_texto(texto))
