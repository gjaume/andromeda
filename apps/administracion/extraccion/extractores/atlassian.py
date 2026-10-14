"""Atlassian Pty Ltd: factura mensual de las suscripciones cloud, en dólares y en inglés.

Página 1: cabecera ("Invoice number", "Invoice date") y un cuadro "RECEIPT" con el pago con
tarjeta (es la factura, ya pagada; no un simple justificante). Siguientes páginas: tabla de
productos, repetida en cada página, cuyas columnas cambian de orden según el mes:

    S.no. Product         List price Credits Discounts Amount     Tax    Amount
                            (USD)    (USD)    (USD)   excl. tax  (USD)    (USD)
     1  Confluence, Monthly, 67.00                      67.00              67.00
        Standard (USD,
        Default, 15-10-2025)
        10 users
        Billing period:
        Apr 22, 2026 - May 22,
        2026
        Entitlement number: …
        Increased quantity in 6.14                       6.14              6.14
        previous billing period
        1 users billed from Mar …

Las columnas vacías no se imprimen, así que los importes de cada fila se asignan a su columna
por posición (texto con columnas conservadas). Las filas sin nº ("Increased quantity…") son
prorrateos del producto anterior y se guardan como líneas aparte. Al final, el cuadro de totales
("Total amount excl. tax", "Total tax applied", "Total billed amount"). Facturan con inversión
del sujeto pasivo ("Reverse charge supply"), con impuestos 0.
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
    registrar,
)

CABECERA = re.compile(r"S\.no\.\s+Product")
COLUMNA = re.compile(r"List price|Credits|Discounts|Amount|Tax")
SUBCABECERA = re.compile(r"^(?:\([A-Z]{3}\)|excl\. tax|\s)+$")
FIN_TABLA = re.compile(r"Total list price|Got questions\?|Additional notes")
IMPORTE_FILA = re.compile(r"(?<!\S)-?\(?[\d,]*\d\.\d{2}\)?(?!\S)")
CANTIDAD = re.compile(r"^(\d+) (users?|agents?)$")
ETIQUETA = re.compile(r"^[A-Z][\w ]*:$")
NOMBRES = {"List price": "lista", "Credits": "creditos", "Discounts": "descuentos", "Tax": "iva"}


def _columnas(cabecera: str) -> list[tuple[float, str]]:
    """Centro de cada columna de importes. El primer "Amount" es sin impuestos, el segundo total."""
    columnas, importes = [], 0
    for m in COLUMNA.finditer(cabecera):
        if m[0] == "Amount":
            nombre = "base" if importes == 0 else "total"
            importes += 1
        else:
            nombre = NOMBRES[m[0]]
        columnas.append(((m.start() + m.end()) / 2, nombre))
    return columnas


def _unir(trozos: list[str]) -> str:
    """Une las líneas de una celda partida ("15-10-" + "2025)" → "15-10-2025)")."""
    texto = ""
    for trozo in trozos:
        if texto.endswith("-") and not texto.endswith(" -"):
            texto += trozo
        else:
            texto = f"{texto} {trozo}" if texto else trozo
    return texto


def _filas(doc: Documento) -> list[dict]:
    """Filas de la tabla de productos: importes por columna y líneas de texto de la fila."""
    filas = []
    for pagina in doc.paginas_layout:
        columnas = None
        for linea in pagina.splitlines():
            if CABECERA.search(linea):
                columnas = _columnas(linea)
                continue
            if columnas is None or not linea.strip() or SUBCABECERA.match(linea):
                continue
            if FIN_TABLA.search(linea):
                break
            importes = list(IMPORTE_FILA.finditer(linea))
            if len(importes) >= 2:
                valores = {}
                for m in importes:
                    centro = (m.start() + m.end()) / 2
                    _, nombre = min(columnas, key=lambda c, x=centro: abs(c[0] - x))
                    valores[nombre] = importe(m[0])
                texto = linea[: importes[0].start()].strip()
                numerada = re.match(r"^(\d+)\s+(.*)$", texto)
                filas.append(
                    {
                        "numerada": bool(numerada),
                        "texto": [numerada[2] if numerada else texto],
                        "importes": valores,
                    }
                )
            elif filas:
                filas[-1]["texto"].append(linea.strip())
    return filas


def _linea(fila: dict, producto: str, impuesto_pct: Decimal | None) -> Linea:
    nombre, periodo, cantidad, unidad, etiqueta = [], [], None, "", None
    for texto in fila["texto"]:
        if ETIQUETA.match(texto):
            etiqueta = texto
        elif m := CANTIDAD.match(texto):
            cantidad, unidad = Decimal(m[1]), m[0]
        elif etiqueta == "Billing period:":
            periodo.append(texto)
        elif etiqueta is None:
            nombre.append(texto)
    descripcion = _unir(nombre)
    if not fila["numerada"] and producto:
        descripcion = f"{producto}: {descripcion}"
    if unidad:
        descripcion += f", {unidad}"
    if periodo:
        descripcion += f", periodo {_unir(periodo)}"
    if "base" not in fila["importes"]:
        raise ExtraccionError(f"No encuentro el importe sin impuestos de «{descripcion}»")
    return Linea(
        descripcion=descripcion,
        cantidad=cantidad,
        importe=fila["importes"]["base"].quantize(Decimal("0.01")),
        impuesto_pct=impuesto_pct,
    )


@registrar
class Atlassian(Extractor):
    clave = "atlassian"
    nombre = "Atlassian (suscripciones cloud)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        divisa, total = buscar_grupos(
            rf"Total billed amount\s+([A-Z]{{3}})\s+({IMPORTE})", texto, "el total facturado"
        )
        total = importe(total)
        base = importe(
            buscar(
                rf"Total amount excl\. tax\s+[A-Z]{{3}}\s+({IMPORTE})", texto, "la base imponible"
            )
        )
        impuestos = importe(
            buscar(rf"Total tax applied\s+[A-Z]{{3}}\s+({IMPORTE})", texto, "los impuestos")
        )
        impuesto_pct = Decimal(0) if impuestos == 0 else None

        lineas, producto = [], ""
        for fila in _filas(doc):
            if fila["numerada"]:
                producto = fila["texto"][0].split(",")[0].strip()
            lineas.append(_linea(fila, producto, impuesto_pct))
        if not lineas:
            raise ExtraccionError("No encuentro la tabla de productos")

        abono = re.search(r"Credit note number", doc.paginas[0], re.I) is not None
        return DatosFactura(
            numero=buscar(
                r"(?:Invoice|Credit note) number:\s*(\S+)", doc.paginas[0], "el nº de factura"
            ),
            fecha=fecha(
                buscar(
                    r"(?:Invoice|Credit note) date:\s*(\w{3} \d{1,2}, \d{4})",
                    doc.paginas[0],
                    "la fecha",
                )
            ),
            moneda=divisa,
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            tipo="abono" if abono else "factura",
            lineas=lineas,
        )
