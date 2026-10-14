"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

La tabla de HubSpot se lee con columnas conservadas, así que el texto imita el de
`paginas_layout`.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

PORTADA = """\
                 HubSpot Ireland Ltd, 1 Example Quay Dublin 2 Ireland (VAT: IE0000000X)
           Your   payment       receipt
           Thank you for your payment. Your VISA ending in 0000 has been charged with €84.70. Visit
           your Account & Billing page to manage your subscription and billing details.
           Company address: Empresa Ficticia SL                 Hub ID: 10000000
                        Calle Inventada 1                     Receipt #: 90000001
                        Ciudad Ficticia               Payment Date: June 7, 2026
           NIF:         ESB00000000
           Billed to: Empresa Ficticia SL               Amount Paid (EUR)
                      Calle Inventada 1                 €84.70
"""

CONCEPTOS = """\
                                                                PRORATED
             ITEM                                   DISCOUNT
                                                                    FEES
             Starter Customer Platform
             Includes:
               Marketing Hub Starter (Includes
               1,000 Marketing Contacts)
                                                                   €20.00
               Sales Hub Starter
               1 Core Seat
             Charge for: 6/7/2026 - 7/6/2026
                                                      €15.00
                                            Loyalty Discount
             2 Additional Core Seats (Starter)
                                         (€7.50 discount on the first 2 €25.00
             Charge for: 6/7/2026 - 7/6/2026
                                                    core seats)
             4 Granted Core Seats
                                                                   €0.00
             Charge for: 6/7/2026 - 7/6/2026
                                                Subtotal            €45.00
                                                VAT (21%)            €9.45
                                                Amount Paid        (€54.45)
                                                Total Due            €0.00
            All fees are listed in EUR and are subject to VAT (21%) (as applicable).
"""


def test_cobro_mensual():
    datos = registro["hubspot"].extraer(Documento.desde_texto([PORTADA, CONCEPTOS]))

    assert datos.numero == "90000001"
    assert datos.fecha == date(2026, 6, 7)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("45.00"),
        Decimal("9.45"),
        Decimal("54.45"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Starter Customer Platform (6/7/2026 - 7/6/2026)",
        "2 Additional Core Seats (Starter) (6/7/2026 - 7/6/2026), descuento 15.00 €: "
        "Loyalty Discount (€7.50 discount on the first 2 core seats)",
        "4 Granted Core Seats (6/7/2026 - 7/6/2026)",
    ]
    assert [linea.importe for linea in datos.lineas] == [
        Decimal("20.00"),
        Decimal("25.00"),  # importe neto, ya descontado
        Decimal("0.00"),
    ]
    assert [linea.cantidad for linea in datos.lineas] == [None, Decimal("2"), Decimal("4")]
    assert datos.lineas[0].impuesto_pct == Decimal("21")
    assert comprobar(datos) == []


def test_sin_tabla_es_un_error():
    totales = CONCEPTOS[
        CONCEPTOS.index("                                                Subtotal") :
    ]
    with pytest.raises(ExtraccionError, match="tabla"):
        registro["hubspot"].extraer(Documento.desde_texto([PORTADA, totales]))
