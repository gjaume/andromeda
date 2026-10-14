"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

Los "\\x00" imitan los signos que la fuente del PDF no tiene (guiones, rayas y la llamada "¹").
"""

from datetime import date
from decimal import Decimal

from apps.administracion.extraccion import Documento, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
Eleven Labs Inc. Bill to Ship to
1 Example Ave Empresa Inventada SL Empresa Inventada SL
New York, New York 10000 admin@example.com 07000 Palma
United States ES VAT ESB00000000 Spain
EU OSS VAT EU000000000
"""

PAGINA_1 = """\
Description Qty Unit price Tax Amount
Flexible Credit Usage (per credits) 0 $0.00
Feb 3\x00Mar 3, 2026
First 500,000 0 $0.00 0%\x001\x00 $0.00
Flat fee for first 500,000 0 0%\x001\x00 $0.00
Gift Credit Usage 0 $0.00 0%\x001\x00 $0.00
Feb 3\x00Mar 3, 2026
Page 1 of 2
"""

PAGINA_2 = """\
Creator (per subscription) 1 $22.00 0%\x001\x00 $22.00
Mar 3\x00Apr 3, 2026
Extra seats 2 $5.50 0%\x001\x00 $11.00
Mar 3\x00Apr 3, 2026
Subtotal $33.00
Total $33.00
{pie}
\x001\x00 Tax to be paid on reverse charge basis
Page 2 of 2
"""

FACTURA = [
    f"""\
Invoice
Invoice number 1A2B3C4D\x000007
Date of issue March 3, 2026
Date due March 3, 2026
{CABECERA}$33.00 USD due March 3, 2026
Pay online
{PAGINA_1}""",
    PAGINA_2.format(pie="Amount due $33.00 USD"),
]

RECIBO = [
    f"""\
Receipt
Invoice number 1A2B3C4D\x000007
Receipt number 9999\x008888\x007777
Date paid March 3, 2026
{CABECERA}$33.00 paid on March 3, 2026
{PAGINA_1}""",
    PAGINA_2.format(
        pie="Amount paid $33.00\nPayment history\nPayment method Date Amount paid Receipt number\n"
        "Mastercard - 0000 March 3, 2026 $33.00 9999\x008888\x00\n7777"
    ),
]


def test_factura_guarda_solo_conceptos_con_importe():
    datos = registro["elevenlabs"].extraer(
        Documento.desde_texto(FACTURA, "Invoice-1A2B3C4D-0007.pdf")
    )

    assert datos.tipo == "factura"
    assert datos.numero == "1A2B3C4D-0007"
    assert datos.fecha == date(2026, 3, 3)
    assert datos.moneda == "USD"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("33.00"),
        Decimal("0.00"),
        Decimal("33.00"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Creator (per subscription) (Mar 3 – Apr 3, 2026)",
        "Extra seats (Mar 3 – Apr 3, 2026)",
    ]
    seats = datos.lineas[1]
    assert (seats.cantidad, seats.precio_unitario, seats.importe, seats.impuesto_pct) == (
        Decimal("2"),
        Decimal("5.50"),
        Decimal("11.00"),
        Decimal("0"),
    )
    assert comprobar(datos) == []


def test_recibo():
    datos = registro["elevenlabs"].extraer(
        Documento.desde_texto(RECIBO, "Receipt-9999-8888-7777.pdf")
    )

    assert datos.tipo == "recibo"
    assert datos.numero == "9999-8888-7777"
    assert datos.moneda == "USD"
    assert datos.total == Decimal("33.00")
    assert len(datos.lineas) == 2
    assert comprobar(datos) == []


def test_si_todo_es_cero_guarda_todas_las_filas():
    texto = [
        FACTURA[0],
        "Subtotal $0.00\nTotal $0.00\nAmount due $0.00 USD\n",
    ]
    datos = registro["elevenlabs"].extraer(Documento.desde_texto(texto))

    assert [linea.descripcion for linea in datos.lineas] == [
        "First 500,000",
        "Flat fee for first 500,000",
        "Gift Credit Usage (Feb 3 – Mar 3, 2026)",
    ]
    assert comprobar(datos) == []
