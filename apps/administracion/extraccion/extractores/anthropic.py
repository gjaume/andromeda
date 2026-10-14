"""Anthropic, PBC (Claude Pro): factura y recibo de Stripe, en euros, en inglés.

Por cada cobro llegan dos PDF con la misma tabla de conceptos:

- Factura ("Invoice-XXXXXXXX-0008.pdf"): "Invoice number", "Date of issue".
- Recibo ("Receipt-1234-5678-9012.pdf"): "Invoice number" (la factura que paga),
  "Receipt number" y "Date paid". Algunos recibos no traen la etiqueta "Receipt number" en la
  cabecera, y entonces el número se toma del nombre del archivo.

La tabla tiene una fila por concepto y, debajo, el periodo facturado:

    Claude Pro 1 €18.00 €18.00
    Jan 17 – Feb 17, 2026

Al final, "Subtotal", "Total" y "Amount due"/"Amount paid". No hay IVA. El PDF usa una fuente
sin algunos signos, que pdfplumber devuelve como "\\x00": los guiones de los números de
factura y recibo ("ABCDEFG1\\x000008") y a veces la raya de los periodos.
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

SIMBOLO = r"[€$£]"
LINEA = re.compile(
    rf"^(?P<concepto>.+?) (?P<cantidad>\d+) {SIMBOLO}(?P<precio>{IMPORTE}) "
    rf"{SIMBOLO}(?P<importe>{IMPORTE})$"
)
PERIODO = re.compile(
    r"^(?P<desde>[A-Z][a-z]{2} \d{1,2})\W+(?P<hasta>[A-Z][a-z]{2} \d{1,2}, \d{4})$"
)
RECIBO_ARCHIVO = re.compile(r"Receipt-([\d-]+)\.pdf$", re.IGNORECASE)
CENTIMO = Decimal("0.01")


def _numero(valor: str) -> str:
    """Los guiones que faltan en la fuente del PDF llegan como "\\x00"."""
    return valor.replace("\x00", "-")


@registrar
class Anthropic(Extractor):
    clave = "anthropic"
    nombre = "Anthropic Claude (factura y recibo de Stripe)"

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

        total = importe(buscar(rf"^Total {SIMBOLO}({IMPORTE})$", texto, "el total", flags=re.M))
        base = importe(
            buscar(rf"^Subtotal {SIMBOLO}({IMPORTE})$", texto, "el subtotal", flags=re.M)
        )

        lineas: list[Linea] = []
        for fila in texto.splitlines():
            if m := LINEA.match(fila):
                lineas.append(
                    Linea(
                        descripcion=m["concepto"],
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]).quantize(CENTIMO),
                    )
                )
            elif lineas and (m := PERIODO.match(fila)):
                lineas[-1].descripcion += f" ({m['desde']} – {m['hasta']})"
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        return DatosFactura(
            numero=_numero(numero),
            fecha=fecha(emitida),
            moneda=moneda(texto),
            base_imponible=base,
            impuestos=Decimal("0.00"),  # Anthropic no repercute IVA
            total=total,
            tipo="recibo" if es_recibo else "factura",
            lineas=lineas,
        )
