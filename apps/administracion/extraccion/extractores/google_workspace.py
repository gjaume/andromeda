"""Google Cloud EMEA Limited: factura mensual de Google Workspace, en euros y en inglés.

Página 1: cabecera ("Invoice number: …") y un recuadro de detalles cuyo texto sale con puntos
de relleno intercalados entre las letras:

    .In..v.o..ic..e. .d.a..t.e.......D..e..c. .3..1.,. .2.0..2.5..... Total in EUR €384.14

Página 2: detalle, una fila por suscripción e intervalo (el intervalo no lleva año):

    Subscription Description Interval Quantity Amount(€)
    Google Workspace Business Standard Usage Dec 1 - Dec 15 23 180.29
    Google Workspace Business Standard Usage Mar 31 22 11.49
    Subtotal in EUR €384.14
    VAT (0%) €0.00
    Total in EUR €384.14

A las líneas se les añade el año del periodo facturado ("Summary for Dec 1, 2025 - …").
Facturan con inversión del sujeto pasivo, IVA 0 %.
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
    buscar_opcional,
    fecha,
    importe,
    moneda,
    registrar,
)

INTERVALO = r"[A-Z][a-z]{2} \d{1,2}(?: - [A-Z][a-z]{2} \d{1,2})?"
LINEA = re.compile(
    rf"^(?P<descripcion>.+?) (?P<intervalo>{INTERVALO}) (?P<cantidad>\d+) (?P<importe>{IMPORTE})$"
)
CABECERA = re.compile(r"^Subscription\s+Description\s+Interval\s+Quantity\s+Amount")
FIN = re.compile(r"^Subtotal in\b")


def _sin_puntos(texto: str) -> str:
    """Quita los puntos de relleno de las líneas del recuadro de detalles (las que empiezan
    por "."), sin tocar el "Total in EUR €384.14" que comparte línea con la fecha."""
    filas = []
    for fila in texto.splitlines():
        if fila.startswith("."):
            recuadro, separador, resto = fila.partition(" Total in ")
            fila = recuadro.replace(".", "") + separador + resto
        filas.append(fila)
    return "\n".join(filas)


@registrar
class GoogleWorkspace(Extractor):
    clave = "google_workspace"
    nombre = "Google Workspace (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        divisa, base = (
            buscar(r"Subtotal in ([A-Z]{3})", texto, "la moneda"),
            importe(
                buscar(rf"^Subtotal in [A-Z]{{3}} \D?({IMPORTE})$", texto, "la base", flags=re.M)
            ),
        )
        tipo_iva, impuestos = (
            importe(buscar(r"^VAT \((\d+(?:[.,]\d+)?)%\)", texto, "el tipo de IVA", flags=re.M)),
            importe(buscar(rf"^VAT \([^)]*\) \D?({IMPORTE})$", texto, "el IVA", flags=re.M)),
        )
        total = importe(
            buscar(rf"^Total in [A-Z]{{3}} \D?({IMPORTE})$", texto, "el total", flags=re.M)
        )
        periodo = buscar_opcional(r"Summary for .*?(\d{4})$", texto, flags=re.M)

        lineas, en_tabla = [], False
        for fila in "\n".join(doc.paginas[1:]).splitlines():
            if CABECERA.match(fila):
                en_tabla = True
            elif en_tabla and FIN.match(fila):
                en_tabla = False
            elif en_tabla and (m := LINEA.match(fila)):
                intervalo = f"{m['intervalo']}, {periodo}" if periodo else m["intervalo"]
                lineas.append(
                    Linea(
                        descripcion=f"{m['descripcion']} ({intervalo})",
                        cantidad=importe(m["cantidad"]),
                        importe=importe(m["importe"]).quantize(total),
                        impuesto_pct=tipo_iva,
                    )
                )
        if not lineas:
            raise ExtraccionError("No encuentro el detalle de suscripciones")

        portada = _sin_puntos(doc.paginas[0])
        return DatosFactura(
            numero=buscar(r"Invoice number:\s*(\S+)", portada, "el nº de factura"),
            fecha=fecha(
                buscar(r"Invoice date\s*:?\s*([A-Z][a-z]{2} \d{1,2}, \d{4})", portada, "la fecha")
            ),
            moneda=divisa if divisa in ("EUR", "USD", "GBP") else moneda(texto),
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            tipo="abono"
            if re.search(r"^Credit (?:note|memo)\b", portada, re.M | re.I)
            else "factura",
            lineas=lineas,
        )
