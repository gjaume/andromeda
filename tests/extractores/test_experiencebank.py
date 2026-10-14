"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

TREKKSOFT = """\
INVOICE
Invoice number: Date of issue:
INV9001 30/04/2026
Bill To Beneficiary
EMPRESA CLIENTE, S.L.U Proveedor Inventado AG
Calle Falsa 1 Strasse 1
Palma de Mallorca 7000 Zug 6300
Spain Switzerland
PAYMENT DESCRIPTION QUANTITY COMMISSION % FEES
Commission April 2026 12,345.50 2.00% EUR 246.91
Subtotal EUR 246.91
Tax Total EUR 0.00
Payment terms: Net 15
Invoiced amount incl. VAT EUR 246.91
Payment details:
IBAN: CH0000000000000000000
1 of 1
"""

VALIDATED_ID = """\
Validated ID, S.L.U. {titulo}
Validated ID, S.L.U.
C/ Inventada 1
Barcelona 08000 Date 15/03/2026
Spain Total €605.00
www.example.com {etiqueta} # {numero}
VAT Registration No. B00000000
Bill To: Empresa cliente sl
Calle Falsa 1
Palma de Mallorca 07000
Spain
Details Due Date 14/04/2026 VAT Registration Number B11111111
Item Description Quantity Rate Amount
VIDMENTRY VIDSigner Multichannel Entry (CLIENTE 1 €400.00 €400.00
DEMO) ((2026/04/01 to 2027/03/31)
Discount Applied 20%
VIDADDON Paquete de 1.000 firmas 2 €50.00 €100.00
Subtotal €500.00
Tax Total (%) €105.00
Total €605.00
Tax Rate Subtotal Tax Amount
21% 500.00 105.00
"""


def test_comision_trekksoft():
    datos = registro["experiencebank"].extraer(Documento.desde_texto(TREKKSOFT))

    assert datos.numero == "INV9001"
    assert datos.fecha == date(2026, 4, 30)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("246.91"),
        Decimal("0.00"),
        Decimal("246.91"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == "Commission April 2026"
    assert (linea.cantidad, linea.precio_unitario, linea.importe, linea.impuesto_pct) == (
        Decimal("12345.50"),
        Decimal("0.02"),
        Decimal("246.91"),
        Decimal("0.00"),
    )
    assert comprobar(datos) == []


def test_factura_validated_id():
    texto = VALIDATED_ID.format(titulo="INVOICE", etiqueta="Invoice", numero="INV-VID-000009999")
    datos = registro["experiencebank"].extraer(Documento.desde_texto(texto))

    assert datos.numero == "INV-VID-000009999"
    assert datos.fecha == date(2026, 3, 15)
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("500.00"),
        Decimal("105.00"),
        Decimal("605.00"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "VIDMENTRY VIDSigner Multichannel Entry (CLIENTE DEMO) ((2026/04/01 to 2027/03/31) "
        "Discount Applied 20%",
        "VIDADDON Paquete de 1.000 firmas",
    ]
    segunda = datos.lineas[1]
    assert (segunda.cantidad, segunda.precio_unitario, segunda.importe) == (
        Decimal("2"),
        Decimal("50.00"),
        Decimal("100.00"),
    )
    assert segunda.impuesto_pct == Decimal("21")
    assert comprobar(datos) == []


def test_credit_memo_es_un_abono_en_negativo():
    texto = VALIDATED_ID.format(titulo="CREDIT MEMO", etiqueta="Credit", numero="CN-VID-999")
    datos = registro["experiencebank"].extraer(Documento.desde_texto(texto))

    assert datos.numero == "CN-VID-999"
    assert datos.tipo == "abono"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("-500.00"),
        Decimal("-105.00"),
        Decimal("-605.00"),
    )
    assert [linea.importe for linea in datos.lineas] == [Decimal("-400.00"), Decimal("-100.00")]
    assert comprobar(datos) == []


def test_formato_desconocido_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["experiencebank"].extraer(Documento.desde_texto("Hola\nTotal €1.00\n"))
