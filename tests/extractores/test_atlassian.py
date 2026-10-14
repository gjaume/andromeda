"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

Atlassian se lee con columnas conservadas, así que el texto imita el de `paginas_layout`.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

PORTADA = """\
                                                                   Invoice
      Atlassian Pty Ltd,
      Level 6, 341 George St,                     Invoice number: IN-EU-009-000-111
      Sydney NSW 2000, Australia                    Invoice date:  Mar 5, 2026
      VAT Number: EU000000000
     Bill to:                              Sold to:
     Empresa Ficticia S.L.                 Empresa Ficticia S.L.
     Calle Inventada 1                     Calle Inventada 1
     Spain                                 Spain
     VAT No.: ESB00000000                  VAT No.: ESB00000000
                                     RECEIPT
                               Invoice Total: USD 160.80
                     Amount paid via credit card: USD 160.80
                            Payment due:  USD  0.00
    Got questions? Contact us: https://www.atlassian.com/contact      Page 1 of 3
"""

PRODUCTOS_1 = """\
                                                                   Invoice
    S.no. Product         List price Credits Discounts Amount     Tax    Amount
                            (USD)    (USD)    (USD)   excl. tax  (USD)    (USD)
                                                        (USD)
     1  Confluence, Monthly, 50.00                      50.00              50.00
        Standard (USD,
        Default, 01-02-2024)
        5 users
        Site Address:
        ejemplo.atlassian.net
        Billing period:
        Mar 4, 2026 - Apr 4,
        2026
        Entitlement number:
        E-000-AAA-BBB-CCC
        Licensed to:
        Empresa Ficticia
        S.L.
        Increased quantity in 4.80                       4.80              4.80
        previous billing period
        1 users billed from Feb
        10, 2026 for 22 days
        (USD 4.80)
    Got questions? Contact us: https://www.atlassian.com/contact      Page 2 of 3
"""

PRODUCTOS_2 = """\
                                                                   Invoice
    S.no. Product           List price Discounts Credits Amount      Tax Amount
                              (USD)     (USD)    (USD)   excl. tax (USD)  (USD)
                                                          (USD)
     2  Service Collection,  120.00    -14.00              106.00          106.00
        Monthly, Standard (USD,
        Default, 01-02-2024)
        4 agents
        Billing period:
        Mar 4, 2026 - Apr 4, 2026
        Entitlement number:
        E-000-DDD-EEE-FFF
                                                    Total list price USD 174.80
                                                     Total credits    USD  0.00
                                 Sub Total (Total list price - Total credits) USD 174.80
                                                   Total discounts    USD -14.00
                                              Total amount excl. tax USD 160.80
                                                  Total tax applied   USD  0.00
                                               Total billed amount   USD 160.80
                                           Total amount  paid     USD  160.80
                                                    Payment due       USD  0.00
    Got questions? Contact us: https://www.atlassian.com/contact      Page 3 of 3
"""


def test_factura_mensual():
    datos = registro["atlassian"].extraer(
        Documento.desde_texto([PORTADA, PRODUCTOS_1, PRODUCTOS_2])
    )

    assert datos.numero == "IN-EU-009-000-111"
    assert datos.fecha == date(2026, 3, 5)
    assert datos.moneda == "USD"
    assert datos.tipo == "factura"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("160.80"),
        Decimal("0.00"),
        Decimal("160.80"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Confluence, Monthly, Standard (USD, Default, 01-02-2024), 5 users, "
        "periodo Mar 4, 2026 - Apr 4, 2026",
        "Confluence: Increased quantity in previous billing period 1 users billed from "
        "Feb 10, 2026 for 22 days (USD 4.80)",
        "Service Collection, Monthly, Standard (USD, Default, 01-02-2024), 4 agents, "
        "periodo Mar 4, 2026 - Apr 4, 2026",
    ]
    assert [linea.importe for linea in datos.lineas] == [
        Decimal("50.00"),
        Decimal("4.80"),
        Decimal("106.00"),  # el importe sin impuestos, ya descontado
    ]
    assert [linea.cantidad for linea in datos.lineas] == [Decimal("5"), None, Decimal("4")]
    assert datos.lineas[0].impuesto_pct == Decimal("0")
    assert comprobar(datos) == []


def test_sin_tabla_de_productos_es_un_error():
    totales = "\n".join(fila for fila in PRODUCTOS_2.splitlines() if "Total" in fila)
    with pytest.raises(ExtraccionError, match="tabla de productos"):
        registro["atlassian"].extraer(Documento.desde_texto([PORTADA, totales]))
