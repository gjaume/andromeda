"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

PORTADA = """\
Empresa Ejemplo
Referencia de la factura: ES9999001
S.L.U.
Tipo de factura: Renovación
NIF: ESB00000000
Fecha de emisión: 09/02/2026
Calle Falsa 1
Orden de pedido: BC000000001 07000 Ciudad
ID de cliente: zz000000-ovh
Factura ES9999001 de 09 Febrero 2026 Información del pago:
El importe de 61.71 € se cargará
Total de la factura, IVA no incl. 51.00 €
con fecha 09-02-2026 en su forma
de pago por defecto.
IVA (21%) 10.71 €
Factura pagadera en el momento de
la recepción.
Importe total de la factura (IVA incl.) 61.71 €
Varios DEDICATED-OPTION
Precio
Suscripción Referencia Cantidad Precio
unitario
64GB DDR4 ECC rental for 1 month prorrateado a 20
ns000001.ip-
días
10-20- 1 0.00 € 0.00 €
Del 09-02-2026 al 28-02-2026
30.eu
Fecha de finalización del compromiso : 09/02/2027
Unlimited traffic prorrateado a 20 días ns000001.ip-
Del 09-02-2026 al 28-02-2026 10-20- 2 3.00 € 6.00 €
Fecha de finalización del compromiso : 09/02/2027 30.eu
SUBTOTAL 6.00 €
Dedicado
Precio
Suscripción Referencia Cantidad Precio
unitario
STOR-2 rental for 1 month prorrateado a 20
días backup.ejemplo.com
Del 09-02-2026 al 28-02-2026 ns000001.ip-10-20- 1 45.00 € 45.00 €
Fecha de finalización del compromiso : 30.eu
09/02/2027
Factura ES9999001 Página 1/2
OVH HISPANO S.L. - C/ Inventada 1, 28000 Madrid (España)
NIF: B00000000 - Inscrita en el Registro Mercantil de Madrid
"""

RESUMEN = """\
Precio
Suscripción Referencia Cantidad Precio
unitario
SUBTOTAL 45.00 €
Suscripción 51.00 €
Precio 51.00 €
IVA (21%) 10.71 €
Total IVA incl. 61.71 €
Servicio prestado por vía electrónica
Factura ES9999001 Página 2/2
"""


def test_factura_con_salto_de_pagina():
    datos = registro["ovh"].extraer(Documento.desde_texto([PORTADA, RESUMEN]))

    assert datos.numero == "ES9999001"
    assert datos.fecha == date(2026, 2, 9)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("51.00"),
        Decimal("10.71"),
        Decimal("61.71"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Varios DEDICATED-OPTION: 64GB DDR4 ECC rental for 1 month prorrateado a 20 días",
        "Varios DEDICATED-OPTION: Unlimited traffic prorrateado a 20 días",
        "Dedicado: STOR-2 rental for 1 month prorrateado a 20 días",
    ]
    segunda = datos.lineas[1]
    assert (segunda.cantidad, segunda.precio_unitario, segunda.importe) == (
        Decimal("2"),
        Decimal("3.00"),
        Decimal("6.00"),
    )
    assert segunda.impuesto_pct == Decimal("21")
    assert comprobar(datos) == []


def test_sin_conceptos_es_un_error():
    portada = PORTADA.split("Varios DEDICATED-OPTION")[0]
    with pytest.raises(ExtraccionError):
        registro["ovh"].extraer(Documento.desde_texto([portada, RESUMEN]))
