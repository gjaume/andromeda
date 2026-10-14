"""Jaume Sabater (autónomo, servicios de sistemas/consultoría): factura en euros, una página.

Cabecera con "Fecha: dd/mm/aaaa" y "Nº Factura: IT/20260005". Tabla de artículos:

    Artículo Descripción Unidades Precio %Dto. %IVA Total
    SYS Administración de sistemas 17.5 100,00 € 0,00 21,00 1.750,00 €

(las unidades son horas y usan punto decimal). Al pie, el resumen:

    + Base imponible: 1.750,00 €
    + IVA: 367,50 €
    - Retención (15%) 262,50 €
    Total: 1.855,00 €

Se guarda una línea por artículo (sin el código, que va al principio). Lleva retención de
IRPF: el `total` es el importe a pagar y `impuestos` = IVA − IRPF, para que base + impuestos =
total.
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
    buscar_opcional,
    fecha,
    importe,
    registrar,
)

NUM = r"-?\d[\d.,]*"
CABECERA = re.compile(r"^Art[íi]culo\s+Descripci[óo]n\s+Unidades", re.IGNORECASE)
FIN = re.compile(r"^Observaciones", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<articulo>\S+)\s+(?P<descripcion>.+?)\s+(?P<unidades>{NUM})\s+(?P<precio>{NUM})\s*€"
    rf"\s+(?P<dto>{NUM})\s+(?P<iva>{NUM})\s+(?P<importe>{NUM})\s*€$"
)


@registrar
class JaumeSabater(Extractor):
    clave = "jaume_sabater"
    nombre = "Jaume Sabater (factura de servicios)"

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
                        importe=importe(m["importe"]).quantize(Decimal("0.01")),
                        impuesto_pct=importe(m["iva"]),
                    )
                )
            elif dentro and fila and lineas:  # descripción partida en varias filas
                lineas[-1].descripcion += f" {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de la factura")

        base = importe(buscar(rf"Base imponible:\s*({NUM})", texto, "la base imponible"))
        iva = importe(buscar(rf"\+\s*IVA:\s*({NUM})", texto, "el IVA"))
        retencion = buscar_opcional(rf"Retenci[óo]n\s*\([\d.,]+\s*%\)\s*({NUM})", texto)
        retencion = abs(importe(retencion)) if retencion else Decimal(0)
        total = importe(buscar(rf"^Total:\s*({NUM})", texto, "el total", flags=re.M))

        return DatosFactura(
            numero=buscar(r"N[º°o]\s*Factura:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"\bFecha:\s*(\S+)", texto, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=iva - retencion,
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
