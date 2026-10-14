"""ib-red (Red Digital de Telecomunicaciones de las Islas Baleares): fibra, factura de 1 página.

Cabecera con "Factura 1/26/0000000" y "Fecha de factura: dd/mm/aaaa", y una tabla de conceptos
con cantidad de tres decimales ("1,000"). El formato ha cambiado varias veces:

    Descripción Cantidad Precio unitario Descuento (%) Impuestos Importe
    1000/1000 Mb BANDA ANCHA FTTH 1,000 32,23 0,00 IVA 21% (Bienes) 32,23 €
    Total sin impuestos 32,23 € / Impuestos 6,77 € / Total 39,00 €

    Descripción Cantidad Precio unitario Impuestos Importe
    1000/1000 Mb BANDA ANCHA FTTH 1,000 32,23 21% B 32,23 €
    1000/1000 Mb BANDA ANCHA FTTH 1,000 39,00 21% S incl 32,23 €
    Importe base 32,23 € / IVA 21% 6,77 € / Total 39,00 €

El importe de la fila siempre va sin IVA. Con "incl" el precio unitario lleva el IVA incluido,
así que en ese caso no se guarda como precio unitario. La línea de teléfono asociada (solo el
número, a 0,00 €) se guarda tal cual.
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

IMPORTE_ES = r"-?[\d.]*\d,\d{2}"
FILA = re.compile(
    rf"^(?P<descripcion>.+?) (?P<cantidad>-?\d+,\d{{3}}) (?P<precio>{IMPORTE_ES})"
    rf"(?: (?P<descuento>{IMPORTE_ES}))? (?:IVA )?(?P<pct>\d+(?:,\d+)?)%(?P<tipo>.*?)"
    rf" (?P<importe>{IMPORTE_ES}) €$"
)
BASE = re.compile(rf"^(?:Total sin impuestos|Importe base) ({IMPORTE_ES}) €$", re.M)
IMPUESTOS = re.compile(rf"^(?:Impuestos|IVA \d+(?:,\d+)?%) ({IMPORTE_ES}) €$", re.M)


@registrar
class IbRed(Extractor):
    clave = "ib_red"
    nombre = "ib-red (fibra)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        base = importe(buscar(BASE.pattern, texto, "la base imponible", flags=re.M), decimal=",")
        impuestos = IMPUESTOS.findall(texto)
        if not impuestos:
            raise ExtraccionError("No encuentro los impuestos")
        total = importe(
            buscar(rf"^Total ({IMPORTE_ES}) €$", texto, "el total", flags=re.M), decimal=","
        )

        lineas = []
        for fila in texto.splitlines():
            if not (m := FILA.match(fila.strip())):
                continue
            precio = importe(m["precio"], decimal=",")
            lineas.append(
                Linea(
                    descripcion=m["descripcion"],
                    cantidad=importe(m["cantidad"], decimal=","),
                    precio_unitario=None if "incl" in m["tipo"] else precio,
                    importe=importe(m["importe"], decimal=",").quantize(Decimal("0.01")),
                    impuesto_pct=importe(m["pct"], decimal=","),
                )
            )
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos facturados")

        numero = buscar(r"^Factura\s+(?:rectificativa\s+)?(\S+)$", texto, "el nº", flags=re.M)
        es_abono = total < 0 or re.search(r"^Factura rectificativa|^Abono", texto, re.I | re.M)
        return DatosFactura(
            numero=numero,
            fecha=fecha(buscar(r"Fecha de factura:\s*(\d{2}/\d{2}/\d{4})", texto, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=sum((importe(i, decimal=",") for i in impuestos), Decimal(0)),
            total=total,
            tipo="abono" if es_abono else "factura",
            lineas=lineas,
        )
