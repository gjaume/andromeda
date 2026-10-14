"""Eleven Labs Inc.: factura y recibo de Stripe del plan mensual, en dólares, en inglés.

Por cada cobro llegan dos PDF con la misma tabla de conceptos:

- Factura ("Invoice-XXXXXXXX-0011.pdf"): "Invoice number", "Date of issue".
- Recibo ("Receipt-1234-5678-9012.pdf"): "Invoice number" (la factura que paga),
  "Receipt number" y "Date paid".

La tabla ("Description Qty Unit price Tax Amount") tiene una fila por concepto y, debajo, el
periodo. El impuesto lleva la llamada "¹" (inversión del sujeto pasivo, IVA 0 %):

    Pro (per subscription) 1 $99.00 0%¹ $99.00
    Jan 10 – Feb 10, 2026
    Flat fee for first 500,000 0 0%¹ $0.00
    Flexible Credit Usage (per credits) 0 $0.00

Hay varias filas de consumo a cero (créditos de regalo, rollover, uso flexible…); algunas ni
siquiera tienen importe. Solo se guardan las filas con importe distinto de cero. Al final,
"Subtotal", "Total" y "Amount due"/"Amount paid". La fuente del PDF no tiene algunos signos y
pdfplumber los devuelve como "\\x00": los guiones de los números ("615936CE\\x000011"), la raya
de los periodos y la llamada "¹" ("0%\\x001\\x00").
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
    buscar_opcional,
    fecha,
    importe,
    moneda,
    registrar,
)

LINEA = re.compile(
    rf"^(?P<concepto>.+?) (?P<cantidad>[\d,.]+) (?:\$(?P<precio>{IMPORTE}) )?"
    rf"(?P<iva>\d+(?:\.\d+)?)%\S* \$(?P<importe>{IMPORTE})$"
)
PERIODO = re.compile(
    r"^(?P<desde>[A-Z][a-z]{2} \d{1,2}(?:, \d{4})?)\W+(?P<hasta>[A-Z][a-z]{2} \d{1,2}, \d{4})$"
)
RECIBO_ARCHIVO = re.compile(r"Receipt-([\d-]+)\.pdf$", re.IGNORECASE)
CENTIMO = Decimal("0.01")


def _numero(valor: str) -> str:
    """Los guiones que faltan en la fuente del PDF llegan como "\\x00"."""
    return valor.replace("\x00", "-")


@registrar
class ElevenLabs(Extractor):
    clave = "elevenlabs"
    nombre = "ElevenLabs (factura y recibo de Stripe)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        es_recibo = texto.lstrip().startswith("Receipt") or doc.nombre_archivo.startswith("Receipt")
        if es_recibo:
            numero = buscar_opcional(r"^Receipt number (\S+)", texto, flags=re.M)
            if not numero and (m := RECIBO_ARCHIVO.search(doc.nombre_archivo)):
                numero = m[1]
            if not numero:
                raise ExtraccionError("No encuentro el nº de recibo")
            emitida = buscar(r"^Date paid (.+)$", texto, "la fecha de pago", flags=re.M)
        else:
            numero = buscar(r"^Invoice number (\S+)", texto, "el nº de factura", flags=re.M)
            emitida = buscar(r"^Date of issue (.+)$", texto, "la fecha de emisión", flags=re.M)

        total = importe(buscar(rf"^Total \$({IMPORTE})$", texto, "el total", flags=re.M))
        base = importe(buscar(rf"^Subtotal \$({IMPORTE})$", texto, "el subtotal", flags=re.M))
        # Inversión del sujeto pasivo: no hay fila de impuestos y el total es el subtotal (si
        # algún día cobran IVA, `comprobar` avisará de que base + impuestos no da el total).
        impuestos = Decimal("0.00")

        filas: list[Linea] = []
        con_periodo = True  # el periodo va justo debajo de su fila, y solo una vez
        for fila in texto.splitlines():
            if m := LINEA.match(fila):
                filas.append(
                    Linea(
                        descripcion=m["concepto"],
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]) if m["precio"] else None,
                        importe=importe(m["importe"]).quantize(CENTIMO),
                        impuesto_pct=importe(m["iva"]),
                    )
                )
                con_periodo = False
            elif filas and not con_periodo and (m := PERIODO.match(fila)):
                filas[-1].descripcion += f" ({m['desde']} – {m['hasta']})"
                con_periodo = True
        if not filas:
            raise ExtraccionError("No encuentro los conceptos")
        # Las filas de consumo a cero no aportan nada; si todo es cero, se guardan todas.
        lineas = [linea for linea in filas if linea.importe] or filas

        return DatosFactura(
            numero=_numero(numero),
            fecha=fecha(emitida),
            moneda=moneda(texto),
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            tipo="recibo" if es_recibo else "factura",
            lineas=lineas,
        )
