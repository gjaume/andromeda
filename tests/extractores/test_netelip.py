"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, registro
from apps.administracion.extraccion.servicio import comprobar

CUOTA = """\
Datos del cliente:
Empresa de Prueba SL
Forma de pago
Factura verificable en la sede electrónica de la AEAT Domiciliación bancaria
Conceptos Cantidad Importe
Numeración (1 mes/es): 34900000001 1 2,00 €
vPBX (1 mes/es) 1 0,00 €
- Extensiones 3 3,00 €
Planes de llamadas: Plan Inventado (1 mes/es) 1 5,00 €
Subtotal 10,00 €
IVA (21%) 2,10 €
Total 12,10 €
Factura nº: N1900000001
Fecha de emisión: 01-03-2026 00:30:00
"""

# Formato de principios de año: el concepto de la centralita va sin importe y sin dos puntos
CUOTA_ANTIGUA = (
    CUOTA.replace("vPBX (1 mes/es) 1 0,00 €", "vPBX Renovación")
    .replace("Factura nº:", "Factura nº")
    .replace("emisión:", "emisión")
)


@pytest.mark.parametrize(
    ("texto", "centralita"),
    [
        (CUOTA, ["vPBX (1 mes/es)", "vPBX (1 mes/es) - Extensiones"]),
        (CUOTA_ANTIGUA, ["vPBX Renovación - Extensiones"]),
    ],
)
def test_cuota_mensual(texto, centralita):
    datos = registro["netelip"].extraer(Documento.desde_texto(texto))

    assert (datos.numero, datos.fecha, datos.moneda) == ("N1900000001", date(2026, 3, 1), "EUR")
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("10.00"),
        Decimal("2.10"),
        Decimal("12.10"),
    )
    descripciones = [linea.descripcion for linea in datos.lineas]
    assert descripciones[1:-1] == centralita
    extensiones = datos.lineas[-2]
    assert (extensiones.cantidad, extensiones.importe, extensiones.impuesto_pct) == (
        Decimal("3"),
        Decimal("3.00"),
        Decimal("21"),
    )
    assert comprobar(datos) == []


def test_recarga_de_saldo():
    texto = CUOTA.replace(
        CUOTA[CUOTA.index("Numeración") : CUOTA.index("Subtotal")], "Recarga de saldo 1 10,00 €\n"
    )
    datos = registro["netelip"].extraer(Documento.desde_texto(texto))
    assert [(linea.descripcion, linea.importe) for linea in datos.lineas] == [
        ("Recarga de saldo", Decimal("10.00"))
    ]
