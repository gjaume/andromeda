"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
FACTURA Número: DGFCJ0000000001
Periodo de consumo 15/02/2026 - 14/03/2026
Fecha de emisión 21/03/2026
Fecha de vencimiento 28/03/2026
"""

PORTADA = (
    CABECERA
    + """\
DATOS DE CLIENTE
Empresa Ejemplo Sl
Código de cliente 00000001
NIF/NIE B00000000
Hola, esta es tu factura de marzo
14,
52€
Total a pagar (Impuestos incluidos): Precio final
PRODUCTO O SERVICIO IMPORTE(Imp. incl.)
________________________________________________
EN EL MÓVIL 600000001 12,10 €
EN EL MÓVIL 600000002 2,42 €
________________________________________________
TOTAL FACTURA (imp. incl.) 14,52 €
IMPORTE (base imponible) 12,00 €
IMPUESTOS (21.00% IVA) 2,52 €
________________________________________________
DIGI puede tener un coste máximo de 0,0992 € (0,12 € IVA incl.) el establecimiento.
DIGI Spain Telecom, S.A.U. Pág. 1
"""
)

DESGLOSE = (
    CABECERA
    + """\
DESGLOSE DE SERVICIOS POR LÍNEA
Servicios:600000001 Cantidad Total
(Sin imp.)
P__R_O__D__U_C__T_O__S______________________________
Ilimitado (15 Feb - 14 Mar) 1 10,00 €
TOTAL CUOTAS 10,00 €
C__O__N__S_U_M__O__ _IN__C__L_U_I_D__O__ E_N__ E__L_ P__L_A__N____
Datos en roaming 0,00 MB 0,00 €
Llamadas incluidas en tu producto 120:05 0,00 €
TOTAL CONSUMO 0,00 €
C__O__N__S_U_M__O__ _A_D__I_C_I_O__N_A__L___________
SMS 3 0,12 €
TOTAL CONSUMO ADICIONAL 0,12 €
Servicios:600000002 Cantidad Total
(Sin imp.)
P__R_O__D__U_C__T_O__S______________________________
Tarifa básica (15 Feb - 14 Mar) 1 2,00 €
Descuento promoción 1 -0,12 €
TOTAL CUOTAS 1,88 €
T__o_t_a__l _s_i_n_ i_m__p__u_e_s_t_o__s____________1_2_,_0_0_ _€___
Total 14,52 €
TOTAL SERVICIOS 14,52 €
DIGI Spain Telecom, S.A.U. Pág. 2
"""
)


def test_factura_con_dos_numeros():
    datos = registro["digi"].extraer(Documento.desde_texto([PORTADA, DESGLOSE]))

    assert datos.numero == "DGFCJ0000000001"
    assert datos.fecha == date(2026, 3, 21)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("12.00"),
        Decimal("2.52"),
        Decimal("14.52"),
    )
    assert [(linea.descripcion, linea.cantidad, linea.importe) for linea in datos.lineas] == [
        ("600000001: Ilimitado (15 Feb - 14 Mar)", Decimal("1"), Decimal("10.00")),
        ("600000001: Datos en roaming", None, Decimal("0.00")),
        ("600000001: Llamadas incluidas en tu producto", None, Decimal("0.00")),
        ("600000001: SMS", Decimal("3"), Decimal("0.12")),
        ("600000002: Tarifa básica (15 Feb - 14 Mar)", Decimal("1"), Decimal("2.00")),
        ("600000002: Descuento promoción", Decimal("1"), Decimal("-0.12")),
    ]
    assert {linea.impuesto_pct for linea in datos.lineas} == {Decimal("21.00")}
    assert comprobar(datos) == []


def test_un_solo_numero_no_lo_repite_en_la_descripcion():
    desglose = DESGLOSE.split("Servicios:600000002")[0]
    datos = registro["digi"].extraer(Documento.desde_texto([PORTADA, desglose]))

    assert datos.lineas[0].descripcion == "Ilimitado (15 Feb - 14 Mar)"


def test_sin_desglose_es_un_error():
    with pytest.raises(ExtraccionError):
        registro["digi"].extraer(Documento.desde_texto([PORTADA]))
