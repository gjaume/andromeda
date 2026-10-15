"""Netelip (Telcom Business Solutions SL): factura mensual de telefonía IP y recargas de
saldo, en euros.

La tabla de conceptos está en la primera página (la segunda, si la hay, es una gráfica). Las
extensiones de la centralita salen en una fila aparte que empieza por guion, y en algunas
facturas el concepto de la centralita no lleva importe:

    Conceptos Cantidad Importe
    Numeración (1 mes/es): 34900000000 1 1,95 €
    vPBX Renovación
    - Extensiones 4 4,00 €
    Subtotal 22,80 €
    IVA (21%) 4,79 €
    Total 27,59 €

El importe de cada fila es el total de la línea. El nº y la fecha van al pie: "Factura nº:
N1921026700" y "Fecha de emisión: 01-10-2026 00:30:38" (con o sin dos puntos).
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
    buscar_grupos,
    fecha,
    importe,
    registrar,
)

CABECERA = re.compile(r"^Conceptos\s+Cantidad\s+Importe$", re.IGNORECASE)
FIN = re.compile(r"^Subtotal\b", re.IGNORECASE)
LINEA = re.compile(rf"^(?P<descripcion>.+?)\s+(?P<cantidad>\d+)\s+(?P<importe>{IMPORTE})\s*€$")


@registrar
class Netelip(Extractor):
    clave = "netelip"
    nombre = "Netelip (telefonía y recargas)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        lineas, dentro, anterior = [], False, ""
        for fila in (f.strip() for f in texto.splitlines()):
            if CABECERA.match(fila):
                dentro = True
            elif dentro and FIN.match(fila):
                break
            elif dentro and (m := LINEA.match(fila)):
                descripcion = m["descripcion"]
                if descripcion.startswith("-") and anterior:  # "- Extensiones" de la centralita
                    descripcion = f"{anterior} {descripcion}"
                else:
                    anterior = descripcion
                lineas.append(
                    Linea(
                        descripcion=descripcion,
                        cantidad=importe(m["cantidad"]),
                        importe=importe(m["importe"]),
                    )
                )
            elif dentro and fila:  # concepto sin importe: da nombre a las filas que siguen
                anterior = fila
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        base = importe(buscar(rf"^Subtotal\s+({IMPORTE})\s*€", texto, "el subtotal", flags=re.M))
        pct, iva = buscar_grupos(
            rf"^IVA \((\d+(?:[.,]\d+)?)\s*%\)\s+({IMPORTE})\s*€", texto, "el IVA", flags=re.M
        )
        for linea in lineas:
            linea.impuesto_pct = importe(pct)
        total = importe(buscar(rf"^Total\s+({IMPORTE})\s*€", texto, "el total", flags=re.M))
        return DatosFactura(
            numero=buscar(r"Factura n[º°o]:?\s*(N\d+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Fecha de emisi[óo]n:?\s*(\d{2}-\d{2}-\d{4})", texto, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=importe(iva),
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
