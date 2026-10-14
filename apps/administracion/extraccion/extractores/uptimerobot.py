"""UptimeRobot s. r. o.: factura del plan (anual), en euros, en inglés. No envían recibo.

Una sola página, con el nº y la fecha en la primera línea y una tabla corta:

    Invoice #12345678 September 3, 2026
    ...
    Item Billed Amount
    Solo 10 annually € 108.00
    VAT 0.0 % € 0.00
    Total € 108.00

No hay subtotal: la base es el total menos el IVA, y se comprueba con la suma de las líneas.
Facturan con inversión del sujeto pasivo ("Reverse charge"), así que el IVA es 0 %.
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
    buscar_grupos,
    fecha,
    importe,
    moneda,
    registrar,
)

SIMBOLO = r"[€$£]"
LINEA = re.compile(
    rf"^(?P<concepto>.+?) (?P<periodo>\w+ly) {SIMBOLO}\s*(?P<importe>{IMPORTE})$", re.IGNORECASE
)
CENTIMO = Decimal("0.01")


@registrar
class UptimeRobot(Extractor):
    clave = "uptimerobot"
    nombre = "UptimeRobot (factura del plan)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        numero, emitida = buscar_grupos(
            r"^Invoice #(\S+)\s+(.+?)\s*$", texto, "el nº y la fecha de factura", flags=re.M
        )
        pct, impuestos = buscar_grupos(
            rf"^VAT (\d+(?:[.,]\d+)?) % {SIMBOLO}\s*({IMPORTE})$", texto, "el IVA", flags=re.M
        )
        impuestos, pct = importe(impuestos), importe(pct)
        total = importe(buscar(rf"^Total {SIMBOLO}\s*({IMPORTE})$", texto, "el total", flags=re.M))

        lineas = [
            Linea(
                descripcion=f"{m['concepto']} ({m['periodo']})",
                importe=importe(m["importe"]).quantize(CENTIMO),
                impuesto_pct=pct,
            )
            for m in (LINEA.match(fila) for fila in texto.splitlines())
            if m
        ]
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        return DatosFactura(
            numero=numero,
            fecha=fecha(emitida),
            moneda=moneda(texto),
            base_imponible=total - impuestos,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
