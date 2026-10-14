"""Caretta Marketing (autónoma, campañas de Meta Ads): factura en euros, una página.

Cabecera "FACTURA #F260012" y "Fecha: dd/mm/aaaa". Tabla de conceptos (la cabecera
"Retención" sale partida en dos filas, "Retenció" y "n"):

    CONCEPTO PRECIO UNIDADES SUBTOTAL IVA Retenció TOTAL
    Estrategia, configuración y optimización de 1.000,00€ 1 1.000,00€ 21% -15% 1.060,00€
    campaña Meta Ads
    Definición de público objetivo, redacción de …

La descripción continúa en las filas siguientes hasta el siguiente concepto o el resumen, y se
guarda entera. El importe de la línea es el SUBTOTAL (sin IVA ni retención). Resumen:

    BASE IMPONIBLE 1.000,00€
    IVA 21% 210,00€
    Retención 15% -150,00€
    TOTAL 1.060,00€

Lleva retención de IRPF: el `total` es el importe a pagar y `impuestos` = IVA − IRPF, para que
base + impuestos = total.
"""

import re
from decimal import Decimal

from ..base import (
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

NUM = r"-?\d[\d.,]*"
PCT = r"-?\d+(?:[.,]\d+)?"
CABECERA = re.compile(r"^CONCEPTO\s+PRECIO\s+UNIDADES", re.IGNORECASE)
FIN = re.compile(r"^BASE IMPONIBLE\b", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<descripcion>.+?)\s+(?P<precio>{NUM})\s*€\s+(?P<unidades>{NUM})\s+(?P<subtotal>{NUM})\s*€"
    rf"\s+(?P<iva>{PCT})\s*%(?:\s+(?P<retencion>{PCT})\s*%)?\s+(?P<total>{NUM})\s*€$"
)
IVA = re.compile(rf"^IVA\s+{PCT}\s*%\s+(?P<importe>{NUM})\s*€", re.IGNORECASE | re.M)
RETENCION = re.compile(rf"^Retenci[óo]n\s+{PCT}\s*%\s+(?P<importe>{NUM})\s*€", re.IGNORECASE | re.M)


@registrar
class Caretta(Extractor):
    clave = "caretta"
    nombre = "Caretta Marketing (factura de servicios)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
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
                        cantidad=importe(m["unidades"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["subtotal"]).quantize(Decimal("0.01")),
                        impuesto_pct=importe(m["iva"]),
                    )
                )
            elif dentro and lineas and fila:  # la descripción sigue en las filas siguientes
                lineas[-1].descripcion += f" {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos de la factura")

        base = importe(buscar(rf"^BASE IMPONIBLE\s+({NUM})", texto, "la base", flags=re.M))
        ivas = [importe(m["importe"]) for m in IVA.finditer(texto)]
        if not ivas:
            raise ExtraccionError("No encuentro el IVA")
        retencion = sum((abs(importe(m["importe"])) for m in RETENCION.finditer(texto)), Decimal(0))
        total = importe(buscar(rf"^TOTAL\s+({NUM})\s*€", texto, "el TOTAL", flags=re.M))

        return DatosFactura(
            numero=buscar(r"FACTURA\s*#\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"^Fecha:\s*(\S+)", texto, "la fecha", flags=re.M)),
            moneda="EUR",
            base_imponible=base,
            impuestos=sum(ivas, Decimal(0)) - retencion,
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
