"""Bitwarden Inc.: factura y recibo de Stripe de la suscripción anual, en dólares, en inglés.

Por cada cobro llegan dos PDF con la misma tabla de conceptos:

- Factura ("Invoice-XXXXXXXX-0005.pdf"): "Invoice number", "Date of issue".
- Recibo ("Receipt-1234-5678.pdf"): "Invoice number" (la factura que paga), "Receipt number"
  y "Date paid".

La tabla ("Description Qty Unit price (excl. tax) Tax Amount (excl. tax)") sale desordenada
porque la descripción ocupa varias líneas en el PDF:

    Premium (Annually) 1 $19.80 21% $19.80
    Jun 9, 2026 – Jun 9, 2027 (on
    Subtotal $19.80
    2026 Premium Renewal Discount (25% off) -$4.95
    Total excluding tax $14.85
    $3.12
    VAT - Spain (21% on $14.85)
    (€2.70)
    Total $17.97

El descuento se guarda como línea negativa, así que las líneas suman "Total excluding tax"
(la base). El IVA español (21 %) viene en dólares y, entre paréntesis, su equivalente en
euros, que se ignora. La fuente del PDF no tiene algunos signos y pdfplumber los devuelve como
"\\x00": los guiones de los números ("395A7BCE\\x000005"), los paréntesis, la raya del periodo y
el signo menos del descuento.
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
    registrar,
)

FALTA = "\x00"  # signo que la fuente del PDF no tiene
LINEA = re.compile(
    rf"^(?P<concepto>.+?) (?P<cantidad>\d+) \$(?P<precio>{IMPORTE}) (?P<iva>\d+(?:\.\d+)?)% "
    rf"\$(?P<importe>{IMPORTE})$"
)
DESCUENTO = re.compile(
    rf"^(?P<concepto>.+?)\s*{FALTA}?(?P<detalle>\d+(?:\.\d+)?% off)\)\s*{FALTA}?\s*-?"
    rf"\$(?P<importe>{IMPORTE})$"
)
PERIODO = re.compile(
    r"^(?P<desde>[A-Z][a-z]{2} \d{1,2}, \d{4})\W+(?P<hasta>[A-Z][a-z]{2} \d{1,2}, \d{4})\b"
)
IMPUESTO = re.compile(rf"^\$(?P<importe>{IMPORTE})\s*\n.*?\b(?P<pct>\d+(?:\.\d+)?)% on \$", re.M)
RECIBO_ARCHIVO = re.compile(r"Receipt-([\d-]+)\.pdf$", re.IGNORECASE)
CENTIMO = Decimal("0.01")


def _numero(valor: str) -> str:
    return valor.replace(FALTA, "-")


@registrar
class Bitwarden(Extractor):
    clave = "bitwarden"
    nombre = "Bitwarden (factura y recibo de Stripe)"

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
        base = importe(
            buscar_opcional(rf"^Total excluding tax \$({IMPORTE})$", texto, flags=re.M)
            or buscar(rf"^Subtotal \$({IMPORTE})$", texto, "el subtotal", flags=re.M)
        )
        impuestos = sum((importe(m["importe"]) for m in IMPUESTO.finditer(texto)), Decimal("0"))

        lineas: list[Linea] = []
        for fila in texto.splitlines():
            if m := LINEA.match(fila):
                lineas.append(
                    Linea(
                        # "Premium \x00Annually)": se queda lo que hay antes del paréntesis
                        descripcion=m["concepto"].split(FALTA)[0].strip(),
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]).quantize(CENTIMO),
                        impuesto_pct=importe(m["iva"]),
                    )
                )
            elif m := DESCUENTO.match(fila):
                lineas.append(
                    Linea(
                        descripcion=f"{m['concepto']} ({m['detalle']})",
                        importe=-abs(importe(m["importe"])).quantize(CENTIMO),
                    )
                )
            elif (
                lineas
                and lineas[-1].cantidad  # los descuentos no tienen periodo
                and "(" not in lineas[-1].descripcion  # ni se añade dos veces
                and (m := PERIODO.match(fila))
            ):
                lineas[-1].descripcion += f" ({m['desde']} – {m['hasta']})"
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        return DatosFactura(
            numero=_numero(numero),
            fecha=fecha(emitida),
            moneda="USD",  # todo en dólares; el IVA repite su importe en euros
            base_imponible=base,
            impuestos=impuestos.quantize(CENTIMO),
            total=total,
            tipo="recibo" if es_recibo else "factura",
            lineas=lineas,
        )
