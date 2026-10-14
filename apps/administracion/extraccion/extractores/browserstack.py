"""BrowserStack Inc.: factura mensual de la suscripción, en dólares y en inglés, de una página.

Cabecera con "Invoice Date: Jan-26-2026", "Invoice #:" y "Currency: USD". Tabla:

    Plan Service Period Units Amount (USD)
    App Live - Individual
    Jan 26, 2026 - Feb 25, 2026 1 user $49.00
    (1 month)
    Subtotal $49.00
    Total Amount $49.00

El nombre del plan va en la línea anterior a la del periodo, unidades e importe. No cobran IVA
(no hay línea de impuestos): los impuestos son la diferencia entre "Total Amount" y "Subtotal".
"""

import re

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
    registrar,
)

FECHA_EN = r"[A-Z][a-z]{2} \d{1,2}, \d{4}"
LINEA = re.compile(
    rf"^(?P<periodo>{FECHA_EN} - {FECHA_EN})\s+(?P<cantidad>\d+) \w+"
    rf"\s+(?P<importe>-?\$\s*{IMPORTE})$"
)
CABECERA = re.compile(r"^Plan\s+Service Period\s+Units\s+Amount")
FIN = re.compile(r"^Subtotal\b")


@registrar
class BrowserStack(Extractor):
    clave = "browserstack"
    nombre = "BrowserStack (suscripción mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        base = importe(
            buscar(rf"^Subtotal\s+(-?\$\s*{IMPORTE})$", texto, "el subtotal", flags=re.M)
        )
        total = importe(
            buscar(rf"^Total Amount\s+(-?\$\s*{IMPORTE})$", texto, "el total", flags=re.M)
        )

        lineas, en_tabla, plan = [], False, []
        for fila in texto.splitlines():
            fila = fila.strip()
            if CABECERA.match(fila):
                en_tabla = True
            elif en_tabla and FIN.match(fila):
                break
            elif en_tabla and (m := LINEA.match(fila)):
                nombre = " ".join(plan) or "Suscripción"
                lineas.append(
                    Linea(
                        descripcion=f"{nombre} ({m['periodo']})",
                        cantidad=importe(m["cantidad"]),
                        importe=importe(m["importe"]).quantize(total),
                    )
                )
                plan = []
            elif en_tabla and not re.fullmatch(r"\(.*\)", fila):
                plan.append(fila)  # nombre del plan; "(1 month)" es la duración, se ignora
        if not lineas:
            raise ExtraccionError("No encuentro la tabla de planes")

        return DatosFactura(
            numero=buscar(r"Invoice #:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Invoice Date:\s*(\w{3}-\d{1,2}-\d{4})", texto, "la fecha")),
            moneda=buscar(r"Currency:\s*([A-Z]{3})", texto, "la moneda"),
            base_imponible=base,
            impuestos=total - base,
            total=total,
            lineas=lineas,
        )
