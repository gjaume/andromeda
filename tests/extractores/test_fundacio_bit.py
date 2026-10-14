"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar


def factura(conceptos: str, impuestos: str) -> str:
    return f"""\
FUNDACIÓ BALEAR D'INNOVACIÓ I TECNOLOGIA
C/INVENTADA, 1
07000 PALMA DE MALLORCA
CIF: G00000000
DATOS FISCALES DE CLIENTE CODIGO: 9999
EMPRESA CLIENTE, S.L.
NÚMERO FACTURA
TC - 2699001
C/. Falsa, 1
FECHA DE LA FACTURA 07000 Palma
9 de marzo de 2026 CIF: B11111111
Concepto Cantidad Precio Importe
{conceptos}
Base imponible % IVA Cuota IVA %Ret. Retención Total Factura
{impuestos}
OBSERVACIONES
Consumo térmico de prueba
FORMA DE PAGO: 1 Giro Bancario Vto/s 16/03/2026.
IBAN: ES00 0000 0000 0000 **** **** BIC: XXXXESXX
Página 1
"""


FACTURA = factura(
    "2/ 3/ 1 POTENCIA TÉRMICA FIJA PARCBIT 3 12,500 37,50Eur\n"
    "Consumo térmico ENERO Y FEBRERO 2026\n"
    "Lectura hasta 28/02/26",
    "37,50 21% 7,88 0% 0,00 45,38Eur",
)

ANEXO = """\
FECHA 9-mar-26
DETALLE CONSUMO ENERGÍA TÉRMICA BLOQUE X
EMET FUNDACIÓ BALEAR D'INNOVACIÓ I TECNOLOGIA
CLIENTE: EMPRESA CLIENTE, S.L.
potencia térmica 0,50000 1.000,00 € x 1 6,25 €
IMPORTE TOTAL 6,25 €
"""


def test_factura_potencia_termica():
    datos = registro["fundacio_bit"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "TC-2699001"
    assert datos.fecha == date(2026, 3, 9)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("37.50"),
        Decimal("7.88"),
        Decimal("45.38"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == (
        "POTENCIA TÉRMICA FIJA PARCBIT - Consumo térmico ENERO Y FEBRERO 2026 - "
        "Lectura hasta 28/02/26"
    )
    assert (linea.cantidad, linea.precio_unitario, linea.importe, linea.impuesto_pct) == (
        Decimal("3"),
        Decimal("12.500"),
        Decimal("37.50"),
        Decimal("21"),
    )
    assert comprobar(datos) == []


def test_retencion_se_resta_de_los_impuestos():
    texto = factura(
        "1/ 1 ALQUILER DESPACHO 1 100,00 100,00Eur", "100,00 21% 21,00 15% 15,00 106,00Eur"
    )
    datos = registro["fundacio_bit"].extraer(Documento.desde_texto(texto))

    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("100.00"),
        Decimal("6.00"),
        Decimal("106.00"),
    )
    assert datos.lineas[0].descripcion == "ALQUILER DESPACHO"
    assert comprobar(datos) == []


def test_detalle_de_consumo_no_es_una_factura():
    with pytest.raises(ExtraccionError, match="No es una factura"):
        registro["fundacio_bit"].extraer(Documento.desde_texto(ANEXO))
