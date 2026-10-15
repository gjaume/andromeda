"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, NoEsFactura, registro
from apps.administracion.extraccion.servicio import comprobar


def factura(filas: str, desglose: str, total: str = "42,41") -> str:
    return f"""\
DETALLE DE LA ENTREGA
DATOS FISCALES DIRECCIÓN POSTAL
EMPRESA CLIENTE SL EMPRESA CLIENTE SL
N.I.F/C.I.F:B11111111 Cuenta: 00XXX000
DATOS DE LA FACTURA
Factura Nº: 269999000001 Forma de pago: Domiciliación Bancaria
Fecha Factura: 31/01/2026 Últimos dígitos domiciliación: * 00000
Página: 1
IMPORTE TOTAL FACTURA {total} € Fecha de vencimiento: 31/01/2026
Albarán Fecha Descripción Cant. Precio Importe % IVA Nº Pedido
Nº contrato:1||000000 - EMPRESA CLIENTE SL -
{filas}
DESGLOSE FACTURA
BASE IMPONIBLE TIPO IMPUESTO TOTAL IMPUESTO TIPO R.E. TOTAL R.E. TOTALES
{desglose}
Protección de datos de carácter personal
"""


FACTURA = factura(
    "111 08/01/2026 Consumo de Aquaservice 20 L. 1 0,00 0,00 10,00\n"
    "111 08/01/2026 Consumo de Aquaservice 20 L. 3 6,25 18,75 10,00\n"
    "222 20/01/2026 Kit de cuidado e higiene de dispensador 1 18,00 18,00 21,00",
    "18,00 € IVA - 21 % 3,78 € 21,78 €\n18,75 € IVA - 10 % 1,88 € 20,63 €\n36,75 € 5,66 € 42,41 €",
)

ALBARAN = """\
Albarán nº 111
Nombre : EMPRESA CLIENTE SL
Contrato nº 000000
Fecha de entrega 08-ene-2026
PRODUCTO Sin cargo A entregar A recoger Referencia
Botella 20L 0 3 0 XX000000 (3)
"""


def test_factura_con_varios_tipos_de_iva():
    datos = registro["aquaservice"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "269999000001"
    assert datos.fecha == date(2026, 1, 31)
    assert (datos.moneda, datos.tipo) == ("EUR", "factura")
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("36.75"),
        Decimal("5.66"),
        Decimal("42.41"),
    )
    assert [
        (x.descripcion, x.cantidad, x.precio_unitario, x.importe, x.impuesto_pct)
        for x in datos.lineas
    ] == [
        ("Consumo de Aquaservice 20 L. (albarán 111, 08/01/2026)", 1, 0, 0, 10),
        ("Consumo de Aquaservice 20 L. (albarán 111, 08/01/2026)", 3, Decimal("6.25"),
         Decimal("18.75"), 10),
        ("Kit de cuidado e higiene de dispensador (albarán 222, 20/01/2026)", 1, 18, 18, 21),
    ]  # fmt: skip
    assert comprobar(datos) == []


def test_el_albaran_no_es_una_factura():
    with pytest.raises(NoEsFactura, match="albarán de entrega"):
        registro["aquaservice"].extraer(Documento.desde_texto(ALBARAN))


def test_avisa_si_la_cabecera_no_cuadra_con_el_desglose():
    texto = factura(
        "111 08/01/2026 Consumo de Aquaservice 20 L. 3 6,25 18,75 10,00",
        "18,75 € IVA - 10 % 1,88 € 20,63 €\n18,75 € 1,88 € 20,63 €",
        total="99,99",
    )
    with pytest.raises(ExtraccionError, match="no coincide"):
        registro["aquaservice"].extraer(Documento.desde_texto(texto))
