"""Hetzner Online GmbH: factura mensual en euros, en inglés.

Página 1: cabecera ("Invoice no.", "Invoice date") y resumen por grupo con
"Total € base € impuesto € total". Siguientes páginas: detalle por grupo
("Dedicated Server (12/2025)", "Project "Default" (12/2025)"…) con una fila por producto:

    5 11 Primary IPv4 Months 11 € 1.7000 € 18.7000
    pos cantidad producto unidad cantidad precio importe

Se guarda el detalle, con el grupo delante de la descripción. Facturan con inversión del sujeto
pasivo (IVA 0 %), así que el % de impuesto sale del cuadro "Tax code / Tax rate".
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

LINEA = re.compile(
    rf"^\d+\s+\d+\s+(?P<producto>.+?)\s+\S+\s+(?P<cantidad>[\d.]+)\s+€\s*(?P<precio>{IMPORTE})"
    rf"\s+€\s*(?P<importe>{IMPORTE})$"
)
GRUPO = re.compile(r"^(?P<grupo>.+?) \(\d{2}/\d{4}\)$")


@registrar
class Hetzner(Extractor):
    clave = "hetzner"
    nombre = "Hetzner (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        portada, detalle = doc.paginas[0], "\n".join(doc.paginas[1:])
        base, impuestos, total = (
            importe(v)
            for v in buscar_grupos(
                rf"^Total € ({IMPORTE}) € ({IMPORTE}) € ({IMPORTE})$",
                portada,
                "los totales",
                flags=re.M,
            )
        )
        tipo_iva = importe(
            buscar(r"^\w+ (\d+(?:[.,]\d+)?) % €", portada, "el tipo de IVA", flags=re.M)
        )

        lineas, grupo = [], ""
        for fila in detalle.splitlines():
            if m := GRUPO.match(fila):
                grupo = m["grupo"]
            elif m := LINEA.match(fila):
                lineas.append(
                    Linea(
                        descripcion=f"{grupo}: {m['producto']}" if grupo else m["producto"],
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]).quantize(total),
                        impuesto_pct=tipo_iva,
                    )
                )
        if not lineas:
            raise ExtraccionError("No encuentro el detalle de productos")

        return DatosFactura(
            numero=buscar(r"Invoice no\.:\s*(\S+)", portada, "el nº de factura"),
            fecha=fecha(buscar(r"Invoice date:\s*(\S+)", portada, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
