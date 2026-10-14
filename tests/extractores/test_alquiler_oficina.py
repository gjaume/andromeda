"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
MARTA FERRER COLL
C/ INVENTADA, 5, 1º
07000 PUEBLO
ILLES BALEARS
NIF: 00.000.000-T
Factura alquiler nº AL/03-2026{sufijo}
FACTURA
ARRENDATARIO:
EMPRESA DE PRUEBA S.L.
C/ FALSA, 1
PALMA C.P. 07000
ILLES BALEARS
CIF B00000000
Fecha: 04/03/2026
Concepto: Alquiler del local sito en el Edificio Ejemplo, bloque A, local 1,
planta 2ª, del polígono de prueba, km 1, de Palma, (07000),
correspondiente al mes de marzo de 2026.
Alquiler ……………………………………………… 500,00
I.V.A. (21%) ………………………………………… 105,00
Retención IRPF (19%) ………………………………. -95,00
TOTAL …… …..………………………………...…. 510,00 €
Nº Cta. Banco para efectuar el ingreso : ES00 0000 0000 0000 0000 0000
"""


@pytest.mark.parametrize("sufijo", ["", "FF"])
def test_factura_con_retencion(sufijo):
    datos = registro["alquiler_oficina"].extraer(
        Documento.desde_texto(FACTURA.format(sufijo=sufijo))
    )

    assert datos.numero == "AL/03-2026"
    assert datos.fecha == date(2026, 3, 4)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    # impuestos = IVA − IRPF, para que base + impuestos = total a pagar
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("500.00"),
        Decimal("10.00"),
        Decimal("510.00"),
    )
    [linea] = datos.lineas
    assert linea.descripcion == "Alquiler (marzo de 2026)"
    assert (linea.importe, linea.impuesto_pct) == (Decimal("500.00"), Decimal("21"))
    assert comprobar(datos) == []


def test_sin_total_es_un_error():
    texto = FACTURA.format(sufijo="").replace("TOTAL", "SUMA")
    with pytest.raises(ExtraccionError):
        registro["alquiler_oficina"].extraer(Documento.desde_texto(texto))
