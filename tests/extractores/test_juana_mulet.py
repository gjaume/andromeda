"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
Ana Prueba Ejemplo
CALLE INVENTADA 1
07000 PALMA DE MALLORCA
BALEARES
00000000T
600000000
EMPRESA DE PRUEBA SL
CALLE FALSA, 1
DOCUMENTO NÚMERO PÁGINA FECHA
07000 PALMA DE MALLORCA
Factura 269999 1 31/03/2026
BALEARES 100
N.I.F. AGENTE FORMA DE PAGO
B00000000 0 Transferencia BCO EJEMPLO ES00 0000 0000 0000 0000 0000
ARTÍCULO DESCRIPCIÓN CANTIDAD PRECIO UNIDAD SUBTOTAL DTO. TOTAL
Servicio de limpieza y mantenimiento 1,00 80,00 80,00 80,00
Limpieza de cristales 2,00 10,00 20,00 10,00 18,00
PORTES
TIPO IMPORTE DESCUENTO PRONTO PAGO FINANCIACIÓN BASE I.V.A. R.E.
21,00 98,00 98,00 20,58
10,00
2,00
OBSERVACIONES: TOTAL: 118,58
Vencimientos Importe Domiciliación Oficina Número de cuenta
31/03/2026 118,58
PROTECCIÓN DE DATOS:
Responsable: Ana Prueba Ejemplo, 00000000T.
"""


def test_factura_mensual():
    datos = registro["juana_mulet"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "269999"
    assert datos.fecha == date(2026, 3, 31)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("98.00"),
        Decimal("20.58"),
        Decimal("118.58"),
    )
    assert [(linea.descripcion, linea.importe) for linea in datos.lineas] == [
        ("Servicio de limpieza y mantenimiento", Decimal("80.00")),
        ("Limpieza de cristales", Decimal("18.00")),  # con un 10 % de descuento
    ]
    primera = datos.lineas[0]
    assert (primera.cantidad, primera.precio_unitario, primera.impuesto_pct) == (
        Decimal("1.00"),
        Decimal("80.00"),
        Decimal("21.00"),
    )
    assert comprobar(datos) == []


def test_sin_cuadro_de_impuestos_es_un_error():
    texto = FACTURA.replace("21,00 98,00 98,00 20,58\n", "")
    with pytest.raises(ExtraccionError):
        registro["juana_mulet"].extraer(Documento.desde_texto(texto))
