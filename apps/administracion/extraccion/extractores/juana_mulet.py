"""Juana Mulet (limpieza): factura mensual en euros, una página, de un programa de facturación.

Cabecera con "DOCUMENTO NÚMERO PÁGINA FECHA" y debajo "Factura 260054 1 31/01/2026". Tabla
de artículos (el código de artículo suele ir vacío):

    ARTÍCULO DESCRIPCIÓN CANTIDAD PRECIO UNIDAD SUBTOTAL DTO. TOTAL
    Servicio de limpieza y mantenimiento 1,00 59,64 59,64 59,64

y cuadro de impuestos, una fila por tipo de IVA (las filas con solo el tipo, sin importes, son
tipos sin uso):

    TIPO IMPORTE DESCUENTO PRONTO PAGO FINANCIACIÓN BASE I.V.A. R.E.
    21,00 59,64 59,64 12,52

De cada fila de impuestos se toman el tipo (primer número) y los dos últimos como base e IVA
(no aplican recargo de equivalencia). El total sale de "TOTAL: 72,16".
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
    fecha,
    importe,
    registrar,
)

NUM = r"-?\d[\d.,]*"
CABECERA_LINEAS = re.compile(r"^ART[ÍI]CULO\s+DESCRIPCI[ÓO]N", re.IGNORECASE)
CABECERA_IMPUESTOS = re.compile(r"^TIPO\s+IMPORTE", re.IGNORECASE)
FIN_LINEAS = re.compile(r"^(PORTES|TIPO\s+IMPORTE)\b", re.IGNORECASE)
FIN_IMPUESTOS = re.compile(r"^OBSERVACIONES", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<descripcion>.*?\D)\s+(?P<cantidad>{NUM})\s+(?P<precio>{NUM})\s+(?P<subtotal>{NUM})"
    rf"(?:\s+(?P<dto>{NUM}))?\s+(?P<importe>{NUM})$"
)


def _bloque(texto: str, inicio: re.Pattern, fin: re.Pattern) -> list[str]:
    """Filas entre la cabecera `inicio` (excluida) y la primera que casa con `fin`."""
    filas, dentro = [], False
    for fila in (f.strip() for f in texto.splitlines()):
        if dentro and fin.match(fila):
            break
        if dentro and fila:
            filas.append(fila)
        dentro = dentro or bool(inicio.match(fila))
    return filas


@registrar
class JuanaMulet(Extractor):
    clave = "juana_mulet"
    nombre = "Juana Mulet Limpieza (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        numero, fecha_texto = buscar_grupos(
            r"^Factura\s+(\d+)\s+\d+\s+(\d{1,2}/\d{1,2}/\d{2,4})\s*$",
            texto,
            "el nº y la fecha de la factura",
            flags=re.M,
        )

        impuestos_por_tipo = []  # (tipo, base, iva)
        for fila in _bloque(texto, CABECERA_IMPUESTOS, FIN_IMPUESTOS):
            numeros = re.findall(NUM, fila)
            if len(numeros) >= 4 and len(numeros) == len(fila.split()):
                impuestos_por_tipo.append(tuple(importe(n) for n in (numeros[0], *numeros[-2:])))
        if not impuestos_por_tipo:
            raise ExtraccionError("No encuentro el cuadro de impuestos")
        tipo_iva = impuestos_por_tipo[0][0] if len(impuestos_por_tipo) == 1 else None

        lineas = []
        for fila in _bloque(texto, CABECERA_LINEAS, FIN_LINEAS):
            if m := LINEA.match(fila):
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"].strip(),
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]).quantize(Decimal("0.01")),
                        impuesto_pct=tipo_iva,
                    )
                )
            elif lineas:  # descripción partida en varias filas
                lineas[-1].descripcion += f" {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de la factura")

        total = importe(buscar(rf"TOTAL:\s*({NUM})", texto, "el TOTAL"))
        return DatosFactura(
            numero=numero,
            fecha=fecha(fecha_texto),
            moneda="EUR",
            base_imponible=sum((base for _, base, _ in impuestos_por_tipo), Decimal(0)),
            impuestos=sum((iva for _, _, iva in impuestos_por_tipo), Decimal(0)),
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
