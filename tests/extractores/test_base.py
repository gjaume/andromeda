from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import DatosFactura, ExtraccionError, Linea
from apps.administracion.extraccion.base import fecha, importe, moneda
from apps.administracion.extraccion.servicio import comprobar


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("1.234,56 €", "1234.56"),
        ("$1,234.56", "1234.56"),
        ("-12,00", "-12.00"),
        ("(12.00)", "-12.00"),
        ("0.125", "0.125"),
        ("1 234,56", "1234.56"),
        ("1.234", "1234"),
        ("12,5", "12.5"),
        ("1.2345", "1.2345"),
        ("1,234,567.89", "1234567.89"),
        ("USD 49.00", "49.00"),
    ],
)
def test_importe(texto, esperado):
    assert importe(texto) == Decimal(esperado)


def test_importe_con_separador_decimal_explicito():
    assert importe("1.234", decimal=".") == Decimal("1.234")


def test_importe_invalido():
    with pytest.raises(ExtraccionError):
        importe("n/a")


@pytest.mark.parametrize(
    "texto",
    [
        "14/10/2026",
        "2026-10-14",
        "14.10.26",
        "14 de octubre de 2026",
        "October 14, 2026",
        "14 Oct 2026",
        "Oct 14, 2026",
    ],
)
def test_fecha(texto):
    assert fecha(texto) == date(2026, 10, 14)


def test_moneda():
    assert moneda("Total: USD 12.00") == "USD"
    assert moneda("Total 12,00 €") == "EUR"
    with pytest.raises(ExtraccionError):
        moneda("Total 12")


def test_comprobar_detecta_descuadres():
    datos = DatosFactura(
        total=Decimal("125"),
        moneda="EUR",
        base_imponible=Decimal("100"),
        impuestos=Decimal("21"),
        lineas=[Linea("A", Decimal("60")), Linea("B", Decimal("30"))],
    )
    avisos = comprobar(datos)
    assert len(avisos) == 2
    datos.lineas[1].importe = Decimal("40")
    datos.total = Decimal("121")
    assert comprobar(datos) == []
