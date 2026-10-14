"""COOIDI Consultores: factura trimestral de honorarios (bonificaciones a la Seguridad Social).

Una página en español, importes en formato ES con "€" pegado ("297,36€"). Cabecera con
"FACTURA #BS26000" y "Fecha 07/01/2026". La tabla de conceptos tiene la cabecera
"CONCEPTO PRECIO UNIDADES SUBTOTAL IVA TOTAL" y cada concepto ocupa varias líneas:

    Bonificaciones por Personal Investigador                      <- título del concepto
    BBSS - Honorarios correspondientes al ahorro del 1er 408,28€ 1 408,28€ 21% 494,02€
    Trimestre 2026                                                <- continuación

En el texto no hay forma de distinguir el título de la continuación más que por la posición:
la línea justo antes de una fila con importes es el título de ese concepto y las demás líneas
entre dos filas son la continuación de la anterior. Los ajustes llegan como conceptos con
importe negativo. Al pie, "BASE IMPONIBLE", una línea "IVA 21% …" por tipo y "TOTAL".

El mismo documento llega a veces con varios nombres de fichero ("BS26000.pdf",
"Factura BS26000.pdf", "BS26000 ANDROMEDA SOLUTIONS SL.pdf"): son copias idénticas.
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

FILA = re.compile(
    rf"^(?P<texto>.*?)\s*(?P<precio>{IMPORTE})€\s+(?P<cantidad>[\d.,]+)\s+"
    rf"(?P<subtotal>{IMPORTE})€\s+(?P<iva>[\d.,]+)%\s+(?P<total>{IMPORTE})€$"
)
CABECERA = re.compile(r"^CONCEPTO\s+PRECIO\s+UNIDADES\s+SUBTOTAL\s+IVA\s+TOTAL$", re.M)
FIN_TABLA = re.compile(r"^BASE IMPONIBLE\b", re.M)
IVA = re.compile(rf"^IVA\s+[\d.,]+%\s+({IMPORTE})€$", re.M)


def _euros(texto: str) -> Decimal:
    return importe(texto, decimal=",")


def _lineas(tabla: str) -> list[Linea]:
    filas = [fila.strip() for fila in tabla.splitlines() if fila.strip()]
    posiciones = [i for i, fila in enumerate(filas) if FILA.match(fila)]
    lineas = []
    for n, pos in enumerate(posiciones):
        anterior = posiciones[n - 1] if n else -1
        siguiente = posiciones[n + 1] - 1 if n + 1 < len(posiciones) else len(filas)
        # Título: la línea justo antes (o todas, si es el primer concepto)
        titulo = " ".join(filas[anterior + 1 : pos]) if n == 0 else filas[pos - 1]
        if n and pos - 1 == anterior:
            titulo = ""  # dos filas seguidas: sin título
        m = FILA.match(filas[pos])
        texto = " ".join([m["texto"], *filas[pos + 1 : siguiente]]).strip()
        descripcion = f"{titulo}: {texto}" if titulo and texto else titulo or texto
        lineas.append(
            Linea(
                descripcion=descripcion,
                cantidad=_euros(m["cantidad"]),
                precio_unitario=_euros(m["precio"]),
                importe=_euros(m["subtotal"]).quantize(Decimal("0.01")),
                impuesto_pct=_euros(m["iva"]),
            )
        )
    return lineas


@registrar
class Cooidi(Extractor):
    clave = "cooidi"
    nombre = "COOIDI (honorarios bonificaciones)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        inicio, fin = CABECERA.search(texto), FIN_TABLA.search(texto)
        if not inicio or not fin:
            raise ExtraccionError("No encuentro la tabla de conceptos (CONCEPTO … TOTAL)")
        lineas = _lineas(texto[inicio.end() : fin.start()])
        if not lineas:
            raise ExtraccionError("No encuentro ningún concepto con importes")

        base = _euros(buscar(rf"^BASE IMPONIBLE\s+({IMPORTE})€", texto, "la base", flags=re.M))
        total = _euros(buscar(rf"^TOTAL\s+({IMPORTE})€", texto, "el total", flags=re.M))
        impuestos = sum((_euros(v) for v in IVA.findall(texto)), Decimal("0.00"))

        return DatosFactura(
            numero=buscar(r"FACTURA\b.*?#\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"^Fecha\s+(\d{1,2}/\d{1,2}/\d{4})", texto, "la fecha", flags=re.M)),
            moneda="EUR",
            tipo="abono" if re.search(r"FACTURA\s+RECTIFICATIVA", texto, re.I) else "factura",
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
