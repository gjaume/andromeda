"""Paddle.com Market Ltd: factura de las suscripciones que se venden a través de Paddle (n8n
Cloud), en inglés. Paddle es quien factura, en nombre del fabricante.

Una página, ya pagada ("PAID"). El nº de pedido a veces sale partido en dos filas, porque la
columna de al lado ("Payment method") lo empuja:

    Order Number / Invoice: #72985757- Payment method: Mastercard card ending
    154841894 3018
    Billing date: 17 Jan 2026 Currency: EUR
    Billing period Quantity Price
    Cloud Starter 17 Jan 2026 - 16 Feb 2026 1 €24.00
    VAT (0%) €0.00
    YOUR ORDER €24.00

El precio de cada fila es el importe de la línea. Con inversión del sujeto pasivo el IVA es 0.
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

SIMBOLO = r"[€$£]"
FECHA = r"\d{1,2} \w{3} \d{4}"
CABECERA = re.compile(r"^Billing period\s+Quantity\s+Price$", re.IGNORECASE)
FIN = re.compile(r"^(VAT|Tax)\b", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<descripcion>.+?)(?:\s+(?P<periodo>{FECHA} - {FECHA}))?\s+(?P<cantidad>\d+)"
    rf"\s+{SIMBOLO}(?P<importe>{IMPORTE})$"
)
MONEDAS = {"€": "EUR", "$": "USD", "£": "GBP"}


def numero_de_pedido(texto: str) -> str:
    m = re.search(r"Order Number / Invoice:\s*#(\d+-)(\d*)", texto)
    if not m:
        raise ExtraccionError("No encuentro el nº de pedido")
    if m[2]:
        return m[1] + m[2]
    resto = buscar(r"^\s*(\d+)\b", texto[m.end() :].split("\n", 1)[-1], "el nº de pedido")
    return m[1] + resto


@registrar
class Paddle(Extractor):
    clave = "paddle"
    nombre = "Paddle (n8n Cloud)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        lineas, dentro = [], False
        for fila in (f.strip() for f in texto.splitlines()):
            if CABECERA.match(fila):
                dentro = True
            elif dentro and FIN.match(fila):
                break
            elif dentro and (m := LINEA.match(fila)):
                periodo = f" ({m['periodo']})" if m["periodo"] else ""
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"] + periodo,
                        cantidad=importe(m["cantidad"]),
                        importe=importe(m["importe"]),
                    )
                )
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        pct, impuestos = buscar_grupos(
            rf"^(?:VAT|Tax) \((\d+(?:[.,]\d+)?)%\) {SIMBOLO}({IMPORTE})$",
            texto,
            "el IVA",
            flags=re.M,
        )
        for linea in lineas:
            linea.impuesto_pct = importe(pct)
        simbolo, total = buscar_grupos(
            rf"^YOUR ORDER ({SIMBOLO})({IMPORTE})$", texto, "el total", flags=re.M
        )
        total, impuestos = importe(total), importe(impuestos)
        return DatosFactura(
            numero=numero_de_pedido(texto),
            fecha=fecha(buscar(rf"Billing date:\s*({FECHA})", texto, "la fecha")),
            moneda=MONEDAS[simbolo],
            base_imponible=total - impuestos,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
