"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

RESUMEN = """\
DATOS DE FACTURA DE ELECTRICIDAD
IMPORTE FACTURA: 78,82 €
Eni Plenitude Iberia, SL Nº de factura:F26ES-00000001
CIF:B00000000 Periodo de consumo:01/05/2026 a 31/05/2026
Domicilio social:Calle Inventada 1, 00000 Ciudad Fecha de factura :04/06/2026
Fecha de cargo:11/06/2026
FACTURA RESUMEN
Por potencia contratada: 18,00 €
Por energía consumida: 50,00 € EMPRESA EJEMPLO SL
Descuento sobre T. Energía: -7,50 € CALLE INVENTADA 2
Impuesto electricidad: 3,09 €
Alquiler equipos de medida y control: 1,55 €
Impuesto aplicado: 13,68 €
TOTAL IMPORTE FACTURA 78,82 €
Código unificado de punto de suministro CUPS: ES0000000000000000ZZ0F
1
"""

DETALLE = """\
DETALLE FACTURA
Facturación por potencia contratada:
Periodo P1 (01/05/2026 - 31/05/2026): 4,0000 kW * 0,072581 €/kW día * 31 días 9,00 €
Periodo P2 (01/05/2026 - 31/05/2026): 4,0000 kW * 0,072581 €/kW día * 31 días 9,00 €
Facturación por energía consumida:
Importe por coste de la energia:
Consumo Fácil (01/05/2026 - 31/05/2026): 400,0000 kWh * 0,125000 €/kWh 50,00 €
Descuento sobre T. Energia:
Descuento Fácil (01/05/2026 - 31/05/2026): 15,00 % s/ 50,0000 € -7,50 €
Subtotal 60,50 €
Impuesto de electricidad: Impuesto especial al tipo de 5,11% sobre el producto de facturación
Impuesto electricidad (60,5000 * 5,11%) 3,09 €
Alquiler de equipos de medida y control: Precio establecido que se paga por el alquiler.
Alquiler de equipos de medida y control (31 días * 0,050000 €/día) 1,55 €
Subtotal otros conceptos 4,64 €
Base imponible 65,14 €
Impuestos:
IVA General (21%) 21,00 % s/65,14 € 13,68 €
TOTAL IMPORTE FACTURA 78,82 €
Desglose del consumo facturado por periodo: P1: 100,00 kWh; P2: 150,00 kWh; P3: 150,00 kWh;
PEAJES DE ACCESO: P1: 1,0000€; P2: 0,5000€;
2
"""

MAXIMETROS = """\
MAXÍMETROS
PERIODO HORARIO DESDE HASTA LECTURA POTENCIA
MAXIMETRO P1 01/05/2026 31/05/2026 1.2 kW
3
"""


def test_factura_mensual_con_descuento():
    datos = registro["plenitude"].extraer(Documento.desde_texto([RESUMEN, DETALLE, MAXIMETROS]))

    assert datos.numero == "F26ES-00000001"
    assert datos.fecha == date(2026, 6, 4)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("65.14"),
        Decimal("13.68"),
        Decimal("78.82"),
    )
    assert [(linea.descripcion, linea.importe) for linea in datos.lineas] == [
        (
            "Potencia periodo P1 (01/05/2026 - 31/05/2026): "
            "4,0000 kW * 0,072581 €/kW día * 31 días",
            Decimal("9.00"),
        ),
        (
            "Potencia periodo P2 (01/05/2026 - 31/05/2026): "
            "4,0000 kW * 0,072581 €/kW día * 31 días",
            Decimal("9.00"),
        ),
        (
            "Consumo Fácil (01/05/2026 - 31/05/2026): 400,0000 kWh * 0,125000 €/kWh",
            Decimal("50.00"),
        ),
        (
            "Descuento Fácil (01/05/2026 - 31/05/2026): 15,00 % s/ 50,0000 €",
            Decimal("-7.50"),
        ),
        ("Impuesto electricidad (60,5000 * 5,11%)", Decimal("3.09")),
        (
            "Alquiler de equipos de medida y control (31 días * 0,050000 €/día)",
            Decimal("1.55"),
        ),
    ]
    energia = datos.lineas[2]
    assert (energia.cantidad, energia.precio_unitario) == (Decimal("400"), Decimal("0.125"))
    assert {linea.impuesto_pct for linea in datos.lineas} == {Decimal("21")}
    assert comprobar(datos) == []


def test_iva_reducido():
    def reducido(pagina: str) -> str:
        return (
            pagina.replace(
                "IVA General (21%) 21,00 % s/65,14 € 13,68 €",
                "IVA Reducido (10%) 10,00 % s/65,14 € 6,51 €",
            )
            .replace("13,68 €", "6,51 €")
            .replace("78,82 €", "71,65 €")
        )

    datos = registro["plenitude"].extraer(
        Documento.desde_texto([reducido(RESUMEN), reducido(DETALLE)])
    )

    assert (datos.impuestos, datos.total) == (Decimal("6.51"), Decimal("71.65"))
    assert datos.lineas[0].impuesto_pct == Decimal("10")
    assert comprobar(datos) == []


def test_sin_detalle_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["plenitude"].extraer(Documento.desde_texto([RESUMEN, MAXIMETROS]))
