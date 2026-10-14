"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
FACTURA #F269999
Fecha: 05/05/2026
Vencimiento: 05/05/2026
Laura Prueba Ejemplo
00000000T
Calle Inventada 1
Pueblo (00000), Provincia, España
laura@example.com
+34 600000000
Cliente:
Empresa de Prueba, S.L.U
B00000000
Calle Falsa 1
Palma (07000), Illes Balears, España
600 000 000
cliente@example.com
CONCEPTO PRECIO UNIDADES SUBTOTAL IVA Retenció TOTAL
n
Gestión de campañas en redes 400,00€ 2 800,00€ 21% -15% 848,00€
sociales
Planificación, seguimiento y
optimización semanal.
Diseño de creatividades 200,00€ 1 200,00€ 21% -15% 212,00€
BASE IMPONIBLE 1.000,00€
IVA 21% 210,00€
Retención 15% -150,00€
TOTAL 1.060,00€
Por favor, realice el pago mediante transferencia bancaria al siguiente número de cuenta: ES00 0000
0000 00 0000000000
Pág. 1 de 1
"""


def test_factura_con_retencion():
    datos = registro["caretta"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "F269999"
    assert datos.fecha == date(2026, 5, 5)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    # impuestos = IVA − IRPF, para que base + impuestos = total a pagar
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1000.00"),
        Decimal("60.00"),
        Decimal("1060.00"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Gestión de campañas en redes sociales Planificación, seguimiento y optimización semanal.",
        "Diseño de creatividades",
    ]
    primera = datos.lineas[0]
    assert (primera.cantidad, primera.precio_unitario, primera.importe) == (
        Decimal("2"),
        Decimal("400.00"),
        Decimal("800.00"),
    )
    assert primera.impuesto_pct == Decimal("21")
    assert comprobar(datos) == []


def test_sin_conceptos_es_un_error():
    texto = FACTURA.replace("CONCEPTO PRECIO", "OTRA COSA")
    with pytest.raises(ExtraccionError):
        registro["caretta"].extraer(Documento.desde_texto(texto))
