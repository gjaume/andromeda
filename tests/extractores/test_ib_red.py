"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
Page 1 / 1
EMPRESA EJEMPLO SL
CALLE INVENTADA 12
07000 Ciudad (Baleares / Illes Balears)
España
ESB00000000
Factura {numero}
Descripción: ZZ00000
Fecha de factura: 03/05/2026
Due Date: 03/05/2026
Código de cliente: 400000000 Dirección de instalación:
Referencia: {numero} CALLE INVENTADA 12
Contrato: EMPRESA EJEMPLO SL
Origen: ZZ00000 07000, Ciudad
Baleares / Illes Balears, España
"""

PIE = """\
Atención al cliente 900 00 00 00
RED DIGITAL DE TELECOMUNICACIONES DE LAS ISLAS BALEARES S.L. CIF B-00000000
"""

IVA_INCLUIDO = (
    CABECERA.format(numero="1/26/0000123")
    + """\
Descripción Cantidad Precio unitario Impuestos Importe
600/600 Mb BANDA ANCHA FTTH 1,000 36,30 21% S incl 30,00 €
900000000 1,000 0,00 21% S incl 0,00 €
Importe base 30,00 €
IVA 21% 6,30 €
Total 36,30 €
"""
    + PIE
)

CON_DESCUENTO = (
    CABECERA.format(numero="1/26/0000045")
    + """\
Descripción Cantidad Precio unitario Descuento (%) Impuestos Importe
900000000 1,000 0,00 0,00 IVA 21% (Bienes) 0,00 €
600/600 Mb BANDA ANCHA FTTH 1,000 30,00 0,00 IVA 21% (Bienes) 30,00 €
Router 2,000 5,00 0,00 IVA 21% (Bienes) 10,00 €
Total sin impuestos 40,00 €
Impuestos 8,40 €
Total 48,40 €
"""
    + PIE
)


def test_precio_con_iva_incluido():
    datos = registro["ib_red"].extraer(Documento.desde_texto(IVA_INCLUIDO))

    assert datos.numero == "1/26/0000123"
    assert datos.fecha == date(2026, 5, 3)
    assert datos.moneda == "EUR"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("30.00"),
        Decimal("6.30"),
        Decimal("36.30"),
    )
    fibra = datos.lineas[0]
    assert fibra.descripcion == "600/600 Mb BANDA ANCHA FTTH"
    # El precio unitario lleva IVA: no se guarda.
    assert (fibra.cantidad, fibra.precio_unitario, fibra.importe, fibra.impuesto_pct) == (
        Decimal("1.000"),
        None,
        Decimal("30.00"),
        Decimal("21"),
    )
    assert comprobar(datos) == []


def test_formato_antiguo_con_columna_de_descuento():
    datos = registro["ib_red"].extraer(Documento.desde_texto(CON_DESCUENTO))

    assert datos.numero == "1/26/0000045"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("40.00"),
        Decimal("8.40"),
        Decimal("48.40"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "900000000",
        "600/600 Mb BANDA ANCHA FTTH",
        "Router",
    ]
    router = datos.lineas[2]
    assert (router.cantidad, router.precio_unitario, router.importe) == (
        Decimal("2.000"),
        Decimal("5.00"),
        Decimal("10.00"),
    )
    assert comprobar(datos) == []


def test_sin_conceptos_es_un_error():
    texto = "\n".join(f for f in IVA_INCLUIDO.splitlines() if "incl" not in f)
    with pytest.raises(ExtraccionError):
        registro["ib_red"].extraer(Documento.desde_texto(texto))
