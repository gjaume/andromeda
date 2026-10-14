from decimal import Decimal

from django import template

register = template.Library()

SIMBOLOS = {"EUR": "€"}


@register.filter
def dinero(valor: Decimal | None, moneda: str = "") -> str:
    """1234.5 + "EUR" → "1.234,50 €"; con otra moneda, su código: "49,00 USD"."""
    if valor is None:
        return "—"
    entero, decimales = f"{abs(valor):,.2f}".split(".")
    texto = f"{'-' if valor < 0 else ''}{entero.replace(',', '.')},{decimales}"
    return f"{texto} {SIMBOLOS.get(moneda, moneda)}".strip()


@register.filter
def numero(valor: Decimal | None) -> str:
    """Cantidades y precios sin ceros de sobra: 35.6000 → "35,6"; 1234.5 → "1.234,5"."""
    if valor is None:
        return ""
    valor = Decimal(valor).normalize()
    signo, entero, _, decimales = ("-" if valor < 0 else "", *f"{abs(valor):,f}".partition("."))
    texto = f"{signo}{entero.replace(',', '.')}"
    return f"{texto},{decimales}" if decimales else texto
