"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
FACTURA
Núm. IT 2026-9999
FECHA
28/02/2026
VENCIMIENTO
15/03/2026
Factura para
Empresa de Prueba SL - B00000000
Calle Falsa, 1
07000 Palma
"""

SENCILLA = (
    CABECERA
    + """\
Código Descripción Precio Cantidad Importe
003 Administración de sistemas 80,00 € 12.5 1.000,00€
Base imponible 1.000,00 €
IVA (21%) 210,00 €
IRPF (15%) -150,00 €
Total 1.060,00 €
Método de pago: Transferencia Bancaria
"""
)

CON_IMPUESTOS = (
    CABECERA
    + """\
Código Producto Precio Impuesto %IMP. %IRPF Cantidad Importe
003 Administración de sistemas 80,00 € IVA 21% 15% 12.5 1.060,00 €
Impuesto Porcentaje Subtotal
Base imponible 1.000,00 €
Impuestos 210,00 €
IVA 21% 210,00 €
IRPF -150,00 €
IRPF Subtotal
Total 1.060,00 €
15% 150,00 €
Método de pago: Transferencia Bancaria
"""
)


@pytest.mark.parametrize("texto", [SENCILLA, CON_IMPUESTOS])
def test_las_dos_variantes_del_formato_anterior(texto):
    datos = registro["jaume_sabater_anterior"].extraer(Documento.desde_texto(texto))

    assert datos.numero == "IT 2026-9999"
    assert datos.fecha == date(2026, 2, 28)
    assert datos.tipo == "factura"
    # impuestos = IVA − IRPF, para que base + impuestos = total a pagar
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1000.00"),
        Decimal("60.00"),
        Decimal("1060.00"),
    )
    [linea] = datos.lineas
    assert (linea.descripcion, linea.cantidad, linea.precio_unitario, linea.importe) == (
        "Administración de sistemas",
        Decimal("12.5"),
        Decimal("80.00"),
        Decimal("1000.00"),
    )
    assert linea.impuesto_pct == Decimal("21")
    assert comprobar(datos) == []


def test_no_lee_el_formato_nuevo():
    from tests.extractores.test_jaume_sabater import FACTURA

    with pytest.raises(ExtraccionError):
        registro["jaume_sabater_anterior"].extraer(Documento.desde_texto(FACTURA))
