"""Alquiler de la oficina (arrendador particular): factura mensual en euros, una página.

El PDF es una carta con el arrendador arriba, "Factura alquiler nº AL/MM-AAAA", "Fecha:
dd/mm/aaaa", un párrafo "Concepto: … correspondiente al mes de <mes> de <año>." y un
cuadro de importes con puntos suspensivos entre etiqueta e importe:

    Alquiler ……………………………… 380,00
    I.V.A. (21%) ……………………………… 79,80
    Retención IRPF (19%) ……………… -72,20
    TOTAL …… …..………………………… 387,60 €

Cada fila que no es IVA, retención ni TOTAL es una línea (normalmente solo "Alquiler"); se le
añade el mes del concepto a la descripción. Al ser un alquiler con retención de IRPF, el
`total` es el importe a pagar y `impuestos` = IVA − IRPF, para que base + impuestos = total.

Rareza: en algunos meses el nº de factura sale con "FF" pegado al final ("AL/04-2026FF"), un
resto de texto del PDF; se quita.
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
    buscar_grupos,
    buscar_opcional,
    fecha,
    importe,
    registrar,
)

NUM = r"-?\d[\d.,]*"
RELLENO = r"[\s….]*"  # puntos suspensivos y espacios entre etiqueta e importe
FILA = re.compile(rf"^(?P<etiqueta>[^\d…\s][^…]*?)\s*…{RELLENO}(?P<importe>{NUM})\s*€?\s*$")
ES_IVA = re.compile(r"^I\.?V\.?A\.?", re.IGNORECASE)
ES_RETENCION = re.compile(r"^Retenci[oó]n", re.IGNORECASE)
ES_TOTAL = re.compile(r"^TOTAL\b", re.IGNORECASE)
PORCENTAJE = re.compile(r"\((\d+(?:[.,]\d+)?)\s*%\)")


@registrar
class AlquilerOficina(Extractor):
    clave = "alquiler_oficina"
    nombre = "Alquiler de la oficina (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        numero = buscar(r"Factura alquiler n[ºo°]\s*(\S+)", texto, "el nº de factura")
        numero = re.sub(r"(?<=\d)F+$", "", numero)
        periodo = buscar_opcional(r"correspondiente al mes de\s+(.+?)\.?\s*$", texto, flags=re.M)

        conceptos, iva, tipo_iva, retencion, total = [], None, None, Decimal(0), None
        for fila in texto.splitlines():
            if not (m := FILA.match(fila.strip())):
                continue
            etiqueta, valor = m["etiqueta"].strip(), importe(m["importe"])
            if ES_TOTAL.match(etiqueta):
                total = valor
            elif ES_IVA.match(etiqueta):
                iva = valor
                if pct := PORCENTAJE.search(etiqueta):
                    tipo_iva = importe(pct[1])
            elif ES_RETENCION.match(etiqueta):
                retencion = abs(valor)
            else:
                conceptos.append((etiqueta, valor))

        if total is None:
            raise ExtraccionError("No encuentro el TOTAL")
        if iva is None:
            raise ExtraccionError("No encuentro el IVA")
        if not conceptos:
            raise ExtraccionError("No encuentro el importe del alquiler")

        lineas = [
            Linea(
                descripcion=f"{etiqueta} ({periodo})" if periodo else etiqueta,
                importe=valor.quantize(Decimal("0.01")),
                impuesto_pct=tipo_iva,
            )
            for etiqueta, valor in conceptos
        ]
        (fecha_texto,) = buscar_grupos(r"^Fecha:\s*(\S+)", texto, "la fecha", flags=re.M)
        return DatosFactura(
            numero=numero,
            fecha=fecha(fecha_texto),
            moneda="EUR",
            base_imponible=sum((linea.importe for linea in lineas), Decimal(0)),
            impuestos=iva - retencion,
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
