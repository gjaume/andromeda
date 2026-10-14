"""Texto inventado con la misma forma que el PDF real (sin datos reales de facturas).

Los "\\x00" imitan los signos que la fuente del PDF no tiene (guiones, paréntesis, rayas y el
signo menos del descuento).
"""

from datetime import date
from decimal import Decimal

from apps.administracion.extraccion import Documento, registro
from apps.administracion.extraccion.servicio import comprobar

CABECERA = """\
Bitwarden Inc. Bill to
Address Not For Check Mailing: Empresa Inventada SL
1 Example Street 07000
Santa Barbara, California 93000 Spain
United States admin@example.com
support@bitwarden.com
"""

TABLA = """\
Unit price Amount
Description Qty (excl. tax) Tax (excl. tax)
Teams \x00Annually) 3 $40.00 21% $120.00
Feb 2, 2026\x00Feb 2, 2027 (on
$108.00\x00
Subtotal $120.00
2026 Teams Loyalty Discount \x0010% off) \x00$12.00
Total excluding tax $108.00
$22.68
VAT - Spain \x0021% on $108.00\x00
\x00€19.50\x00
Total $130.68
"""

FACTURA = f"""\
Invoice
Invoice number ABC12345\x000003
Date of issue February 2, 2026
Date due February 2, 2026
{CABECERA}$130.68 USD due February 2, 2026
Pay online
{TABLA}Amount due $130.68 USD
Page 1 of 1
"""

RECIBO = f"""\
Receipt
Invoice number ABC12345\x000003
Receipt number 4444\x005555
Date paid February 9, 2026
{CABECERA}$130.68 paid on February 9, 2026
{TABLA}Amount paid $130.68
Payment history
Payment method Date Amount paid Receipt number
Mastercard - 0000 February 9, 2026 $130.68 4444\x005555
Page 1 of 1
"""


def test_factura_con_descuento_e_iva():
    datos = registro["bitwarden"].extraer(
        Documento.desde_texto(FACTURA, "Invoice-ABC12345-0003.pdf")
    )

    assert datos.tipo == "factura"
    assert datos.numero == "ABC12345-0003"
    assert datos.fecha == date(2026, 2, 2)
    assert datos.moneda == "USD"
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("108.00"),
        Decimal("22.68"),
        Decimal("130.68"),
    )
    plan, descuento = datos.lineas
    assert plan.descripcion == "Teams (Feb 2, 2026 – Feb 2, 2027)"
    assert (plan.cantidad, plan.precio_unitario, plan.importe, plan.impuesto_pct) == (
        Decimal("3"),
        Decimal("40.00"),
        Decimal("120.00"),
        Decimal("21"),
    )
    assert descuento.descripcion == "2026 Teams Loyalty Discount (10% off)"
    assert descuento.importe == Decimal("-12.00")
    assert comprobar(datos) == []


def test_recibo():
    datos = registro["bitwarden"].extraer(Documento.desde_texto(RECIBO, "Receipt-4444-5555.pdf"))

    assert datos.tipo == "recibo"
    assert datos.numero == "4444-5555"
    assert datos.fecha == date(2026, 2, 9)
    assert (datos.base_imponible, datos.impuestos, datos.total) == (
        Decimal("108.00"),
        Decimal("22.68"),
        Decimal("130.68"),
    )
    assert len(datos.lineas) == 2
    assert comprobar(datos) == []
