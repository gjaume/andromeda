"""Loom, Inc. (Atlassian): factura mensual de la suscripción, en dólares, en inglés.

Una página. En la cabecera "Invoice number 62386006-0013" (el guion sale del PDF como un
carácter nulo) y "Date of issue January 6, 2026". La tabla de conceptos lleva el periodo en
la fila siguiente; los cambios de plazas a mitad de mes salen sin precio unitario:

    Description Qty Unit price Amount
    Increased quantity of Loom Business + AI from 1 to 2 on 04 Feb 2026 2 $1.99
    Feb 4 – Feb 6, 2026
    Loom Business + AI 2 $24.00 $48.00
    Feb 6 – Mar 6, 2026
    Subtotal $49.99
    Total $49.99

No cobran IVA (inversión del sujeto pasivo): los impuestos son el total menos el subtotal.
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
    registrar,
)

CABECERA = re.compile(r"^Description\s+Qty\s+Unit price\s+Amount$", re.IGNORECASE)
FIN = re.compile(r"^Subtotal\b", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<descripcion>.+?)\s+(?P<cantidad>\d+)\s+(?:\$(?P<precio>{IMPORTE})\s+)?"
    rf"\$(?P<importe>{IMPORTE})$"
)


@registrar
class Loom(Extractor):
    clave = "loom"
    nombre = "Loom (suscripción mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto.replace("\x00", "-")
        lineas, dentro = [], False
        for fila in (f.strip() for f in texto.splitlines()):
            if CABECERA.match(fila):
                dentro = True
            elif dentro and FIN.match(fila):
                break
            elif dentro and (m := LINEA.match(fila)):
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"],
                        cantidad=Decimal(m["cantidad"]),
                        precio_unitario=importe(m["precio"]) if m["precio"] else None,
                        importe=importe(m["importe"]),
                    )
                )
            elif dentro and fila and lineas:  # el periodo, debajo del concepto
                lineas[-1].descripcion += f" ({fila})"
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        base = importe(buscar(rf"^Subtotal\s+\$({IMPORTE})$", texto, "el subtotal", flags=re.M))
        total = importe(buscar(rf"^Total\s+\$({IMPORTE})$", texto, "el total", flags=re.M))
        return DatosFactura(
            numero=buscar(r"Invoice number\s+(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Date of issue\s+(.+)", texto, "la fecha")),
            moneda="USD",
            base_imponible=base,
            impuestos=total - base,
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
