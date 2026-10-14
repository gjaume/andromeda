"""HubSpot Ireland Ltd: cobro mensual de la suscripción con tarjeta, en euros y en inglés.

Los PDF se llaman "RECEIPT" y la página 1 dice "Your payment receipt" ("Receipt #", "Payment
Date"), pero se guardan como FACTURA: es el único documento que HubSpot emite por estos cobros
y tiene todo lo de una factura (NIF de ambas partes, conceptos, base, tipo de IVA, mención a la
inversión del sujeto pasivo del art. 196 de la Directiva del IVA, "services covered by this
invoice"). No justifica el pago de otra factura.

Página 2: tabla con columnas ITEM, DISCOUNT y PRORATED FEES. Cada concepto termina en su línea
"Charge for: <periodo>" (fechas M/D/AAAA), y sus importes quedan a media altura del texto:

    ITEM                                   DISCOUNT
                                                                    FEES
    Starter Customer Platform
    Includes: …                                                     €20.00
    Charge for: 1/2/2026 - 2/1/2026
                                                      €28.80
                                            Price Migration Discount
    3 Additional Core Seats (Starter)
                                         (€9.60 discount on the first 3 €31.20
    Charge for: 1/2/2026 - 2/1/2026
                                                    core seats)
                                                Subtotal            €51.20
                                                VAT (0%)             €0.00
                                                Amount Paid        (€51.20)

Por eso se lee el texto con columnas conservadas: los importes bajo FEES son el importe neto de
cada concepto (ya descontado) y los de bajo DISCOUNT, el descuento, que se anota en la
descripción. Algunas líneas de la descripción del descuento caen después del "Charge for".
"""

import re
from decimal import Decimal

from ..base import (
    IMPORTE,
    DatosFactura,
    Documento,
    ExtraccionError,
    Extractor,
    Linea,
    buscar,
    fecha,
    importe,
    moneda,
    registrar,
)

IMPORTE_EUR = rf"-?€\s*{IMPORTE}"
# Importe suelto: "€20.00" o "(€51.20)", pero no el "(€9.60" del texto de un descuento.
IMPORTE_SUELTO = re.compile(r"(?<!\S)(?:\(€[\d,]*\d\.\d{2}\)|-?€[\d,]*\d\.\d{2})(?!\S)")
TROZO = re.compile(r"\S+(?: \S+)*")  # texto separado por 2 o más espacios
PERIODO = re.compile(r"^Charge for:\s*(.+)$")
CANTIDAD = re.compile(r"^(\d+) ")


class _Concepto:
    def __init__(self) -> None:
        self.textos: list[str] = []
        self.descuento: list[str] = []
        self.cuotas: list[Decimal] = []
        self.descuentos: list[Decimal] = []
        self.periodo = ""

    def linea(self, impuesto_pct: Decimal) -> Linea:
        if not self.textos:
            raise ExtraccionError("Hay un importe sin concepto en la tabla")
        titulo = self.textos[0]
        descripcion = f"{titulo} ({self.periodo})" if self.periodo else titulo
        if self.descuentos:
            texto = " ".join(self.descuento)
            descuento = sum(self.descuentos, Decimal(0))
            descripcion += f", descuento {abs(descuento)} €" + (f": {texto}" if texto else "")
        if len(self.cuotas) != 1:
            raise ExtraccionError(f"No encuentro el importe de «{titulo}»")
        m = CANTIDAD.match(titulo)
        return Linea(
            descripcion=descripcion,
            cantidad=Decimal(m[1]) if m else None,
            importe=self.cuotas[0].quantize(Decimal("0.01")),
            impuesto_pct=impuesto_pct,
        )


def _conceptos(pagina: str) -> list[_Concepto]:
    """Conceptos de la tabla (texto con columnas conservadas)."""
    filas = pagina.splitlines()
    inicio = next((i for i, f in enumerate(filas) if re.search(r"ITEM\s+DISCOUNT", f)), None)
    tasas = next((f.find("FEES") for f in filas if re.fullmatch(r"\s*FEES\s*", f)), -1)
    if inicio is None or tasas < 0:
        raise ExtraccionError("No encuentro la tabla de conceptos (ITEM / DISCOUNT / FEES)")
    x_item, x_descuento = filas[inicio].find("ITEM"), filas[inicio].find("DISCOUNT")
    limite_item = (x_item + x_descuento) / 2  # a la izquierda: texto del concepto
    centro_descuento = x_descuento + len("DISCOUNT") / 2
    centro_tasas = tasas + len("FEES") / 2

    conceptos, actual = [], _Concepto()
    for fila in filas[inicio + 1 :]:
        if re.match(r"\s*Subtotal\b", fila):
            break
        for trozo in TROZO.finditer(fila):
            texto = trozo[0]
            if trozo.start() < limite_item:
                if texto in ("FEES", "Includes:"):
                    continue
                if m := PERIODO.match(texto):
                    actual.periodo = m[1]
                    conceptos.append(actual)
                    actual = _Concepto()
                else:
                    actual.textos.append(texto)
                continue
            # Columnas de importes (y texto del descuento, que puede llevar un importe pegado).
            for m in IMPORTE_SUELTO.finditer(texto):
                centro = trozo.start() + (m.start() + m.end()) / 2
                valor = importe(m[0])
                if abs(centro - centro_tasas) < abs(centro - centro_descuento):
                    actual.cuotas.append(valor)
                else:
                    actual.descuentos.append(valor)
            resto = IMPORTE_SUELTO.sub("", texto).strip()
            if resto and resto != "FEES":
                # El final del texto de un descuento a veces cae tras el "Charge for" de su
                # concepto: si el nuevo concepto aún no tiene nada, sigue con el anterior.
                vacio = not (actual.textos or actual.descuentos or actual.descuento)
                continua = vacio and conceptos and conceptos[-1].descuento
                (conceptos[-1] if continua else actual).descuento.append(resto)
    if actual.textos or actual.cuotas:
        conceptos.append(actual)
    return conceptos


@registrar
class HubSpot(Extractor):
    clave = "hubspot"
    nombre = "HubSpot (cobro mensual con tarjeta)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        base = importe(
            buscar(rf"^\s*Subtotal\s+({IMPORTE_EUR})\s*$", texto, "el subtotal", flags=re.M)
        )
        tipo_iva, impuestos = (
            importe(v)
            for v in (
                buscar(r"^\s*VAT \((\d+(?:[.,]\d+)?)%\)", texto, "el tipo de IVA", flags=re.M),
                buscar(rf"^\s*VAT \([^)]*\)\s+({IMPORTE_EUR})\s*$", texto, "el IVA", flags=re.M),
            )
        )
        # "Amount Paid (€51.20)": entre paréntesis porque se resta del total a pagar.
        total = abs(
            importe(
                buscar(
                    rf"^\s*Amount Paid\s+\(?({IMPORTE_EUR})\)?\s*$", texto, "el total", flags=re.M
                )
            )
        )

        tabla = next((p for p in doc.paginas_layout if re.search(r"ITEM\s+DISCOUNT", p)), None)
        if tabla is None:
            raise ExtraccionError("No encuentro la tabla de conceptos")
        lineas = [concepto.linea(tipo_iva) for concepto in _conceptos(tabla)]

        divisa = re.search(r"fees are listed in ([A-Z]{3})", texto)
        return DatosFactura(
            numero=buscar(r"Receipt #:\s*(\S+)", texto, "el nº de recibo"),
            fecha=fecha(buscar(r"Payment Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", texto, "la fecha")),
            moneda=divisa[1] if divisa else moneda(texto),
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            tipo="factura",
            lineas=lineas,
        )
