"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.administracion.extraccion import Documento, ExtraccionError, registro
from apps.administracion.extraccion.servicio import comprobar

FACTURA = """\
Factura
Fecha: 30/04/2026
Nº Factura: IT/20269999
Referencia
Servicios del mes de abril de 2026
Cliente
Empresa de Prueba SL
DNI/NIF: B00000000
PRUEBA EJEMPLO, PERE
Calle Falsa, 1
NIF: 00000000T
07000 - Palma
CL INVENTADA 2
BALEARES
07000 - PALMA
ESPAÑA
Telefono : 600000000
e-mail : pere@example.com
Artículo Descripción Unidades Precio %Dto. %IVA Total
SYS Administración de sistemas 12.5 80,00 € 0,00 21,00 1.000,00 €
CDN Consultoría de desarrollo de negocio 2 50,00 € 0,00 21,00 100,00 €
Observaciones
Forma de pago: 15 días Vencimiento: 15/05/2026 + Base bruta 1.100,00 €
(Transferencia)
Base %IVA %Rec. Cuota
+ Base imponible: 1.100,00 €
IBAN: 1.100,00 € 21,00 231,00 €
+ IVA: 231,00 €
ES0000000000000000000000
- Retención (15%) 165,00 €
Total: 1.166,00 €
"""


def test_factura_con_retencion():
    datos = registro["jaume_sabater"].extraer(Documento.desde_texto(FACTURA))

    assert datos.numero == "IT/20269999"
    assert datos.fecha == date(2026, 4, 30)
    assert datos.moneda == "EUR"
    assert datos.tipo == "factura"
    # impuestos = IVA − IRPF, para que base + impuestos = total a pagar
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("1100.00"),
        Decimal("66.00"),
        Decimal("1166.00"),
    )
    assert [linea.descripcion for linea in datos.lineas] == [
        "Administración de sistemas",
        "Consultoría de desarrollo de negocio",
    ]
    primera = datos.lineas[0]
    assert (primera.cantidad, primera.precio_unitario, primera.importe) == (
        Decimal("12.5"),
        Decimal("80.00"),
        Decimal("1000.00"),
    )
    assert primera.impuesto_pct == Decimal("21.00")
    assert comprobar(datos) == []


def test_sin_lineas_es_un_error():
    texto = FACTURA.replace("Artículo Descripción", "Concepto")
    with pytest.raises(ExtraccionError):
        registro["jaume_sabater"].extraer(Documento.desde_texto(texto))
