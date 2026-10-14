"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

El extractor lee el texto con columnas conservadas: en el cuadro de totales cada importe tiene
que quedar bajo su cabecera, como en el PDF.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
                                                    QR Tributario:
       ASESORIA DE PRUEBA, S.L.
       CL Inventada 1
       07000  Palma de Mallorca
       Tel. 900000000 Fax 900000001
                                                                  Núm. Referencia 269999
       N.I.F. B00000000

                                             EMPRESA DE PRUEBA SL
                                             CL FALSA 1
                                             07000 - PALMA DE MALLORCA
                                             BALEARES
                                             N.I. F: B11111111
      FECHA       CLIENTE Nº FACTURA PÁGINA
       30/04/26      1234 1/999     1

      FECHA DESCRIPCION                UNID. PRECIO U. % DTO. CARGOS ABONOS
"""

CON_SUPLIDOS = (
    CABECERA
    + """\
      30/04/26 Tarifa plana: Sociedad Limitada o 1,00 200,00  200,00
            Asociación (Desde 0 a 2.000 asientos)
      15/04/26 Confección de las Cuentas Anuales 1 ,00 200,00 50 100,00
      30/04/26 Suplidos Cuentas Anuales 1,00  50,00          50,00

      I . V . A . : B A S E % %R.Eq. I . V . A . : B A S E % %R.Eq. I.R.P.F.: %
         300,00    21                   10

      HONORARIOS  GASTOS      SUPLIDOS    I . V . A . + R E C . E Q . I.R.P.F. PROV.FONDOS
          300,00            50,00        63,00

      DOMICILIO DE COBRO        C.C.C
       BANCO DE EJEMPLO          0000-0000-00-000000****
      FORMA DE PAGO                                           IMPORTE LIQUIDO
       Recibo bancario                                          413,00
"""
)

CON_RETENCION = (
    CABECERA
    + """\
      30/04/26 Asesoramiento fiscal          1,00 1.000,00     1.000,00
      I . V . A . : B A S E % %R.Eq. I . V . A . : B A S E % %R.Eq. I.R.P.F.: %
       1.000,00    21                                               15
      HONORARIOS  GASTOS      SUPLIDOS    I . V . A . + R E C . E Q . I.R.P.F. PROV.FONDOS
        1.000,00                        210,00                          150,00
      FORMA DE PAGO                                           IMPORTE LIQUIDO
       Recibo bancario                                        1.060,00
"""
)


def test_factura_con_suplidos():
    datos = registro["pyr_asesores"].extraer(Documento.desde_texto(CON_SUPLIDOS))

    assert datos.numero == "1/999"
    assert datos.fecha == date(2026, 4, 30)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    # los suplidos (sin IVA) van en la base: 300 de honorarios + 50 de suplidos
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("350.00"),
        Decimal("63.00"),
        Decimal("413.00"),
    )
    assert [
        (linea.descripcion, linea.cantidad, linea.importe, linea.impuesto_pct)
        for linea in datos.lineas
    ] == [
        (
            "Tarifa plana: Sociedad Limitada o Asociación (Desde 0 a 2.000 asientos)",
            Decimal("1.00"),
            Decimal("200.00"),
            Decimal("21"),
        ),
        ("Confección de las Cuentas Anuales", Decimal("1.00"), Decimal("100.00"), Decimal("21")),
        ("Suplidos Cuentas Anuales", Decimal("1.00"), Decimal("50.00"), Decimal("0")),
    ]
    assert datos.lineas[1].precio_unitario == Decimal("200.00")  # con un 50 % de descuento
    assert comprobar(datos) == []


def test_factura_con_retencion():
    datos = registro["pyr_asesores"].extraer(Documento.desde_texto(CON_RETENCION))

    # impuestos = IVA − IRPF, para que base + impuestos = importe líquido
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1000.00"),
        Decimal("60.00"),
        Decimal("1060.00"),
    )
    [linea] = datos.lineas
    assert (linea.descripcion, linea.importe) == ("Asesoramiento fiscal", Decimal("1000.00"))
    assert comprobar(datos) == []


def test_sin_cuadro_de_totales_es_un_error():
    texto = CON_SUPLIDOS.replace("HONORARIOS", "OTROS")
    with pytest.raises(ExtraccionError):
        registro["pyr_asesores"].extraer(Documento.desde_texto(texto))
