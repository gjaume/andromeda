"""Paddle.com Market Ltd, formato nuevo ("Tax invoice"): suscripciones vendidas a través de
Paddle, como Elfsight. En inglés; la moneda la indica "Currency code".

Una página, ya pagada. Tras cada producto vienen el periodo y el nombre largo del plan:

    Invoice reference: 457-217109
    Billing period: 10th April 2026 - 10th May 2026
    Currency code: USD
    Product Qty Unit price Tax rate Amount
    All Apps Pack 1 $59.50 21% $59.50
    10th April 2026 - 10th May 2026
    All Apps Premium Pack - Monthly
    Subtotal $59.50
    VAT $12.50
    Total $72.00

El importe de cada fila va sin IVA. La fecha de la factura es el inicio del periodo (la que
aparece en la cabecera, "10th April 2026 - $72.00 via Paddle.com").
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
    fecha,
    importe,
    registrar,
)

SIMBOLO = r"[€$£]"
CABECERA = re.compile(r"^Product\s+Qty\s+Unit price\s+Tax rate\s+Amount$", re.IGNORECASE)
FIN = re.compile(r"^Subtotal\b", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<descripcion>.+?)\s+(?P<cantidad>\d+)\s+{SIMBOLO}(?P<precio>{IMPORTE})"
    rf"\s+(?P<iva>\d+(?:[.,]\d+)?)%\s+{SIMBOLO}(?P<importe>{IMPORTE})$"
)


def _total(etiqueta: str, texto: str) -> str:
    return buscar(rf"^{etiqueta}\s+{SIMBOLO}({IMPORTE})$", texto, f"«{etiqueta}»", flags=re.M)


@registrar
class PaddleBilling(Extractor):
    clave = "paddle_billing"
    nombre = "Paddle, formato nuevo (Elfsight)"

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
                        cantidad=importe(m["cantidad"]),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]),
                        impuesto_pct=importe(m["iva"]),
                    )
                )
            elif dentro and fila and lineas:  # periodo y nombre largo del plan
                lineas[-1].descripcion += f" · {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro los conceptos")

        base = importe(_total("Subtotal", texto))
        iva = importe(_total("(?:VAT|Tax)", texto))
        total = importe(_total("Total", texto))
        periodo = buscar(r"Billing period:\s*(.+?)\s+-\s", texto, "el periodo")
        return DatosFactura(
            numero=buscar(r"Invoice reference:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(periodo),
            moneda=buscar(r"Currency code:\s*([A-Z]{3})", texto, "la moneda"),
            base_imponible=base,
            impuestos=iva,
            total=total,
            lineas=lineas,
        )
