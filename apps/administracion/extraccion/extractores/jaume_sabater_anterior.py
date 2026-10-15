"""Jaume Sabater, formato anterior (facturas IT 2026-0001 a 0004, hasta abril de 2026).

Antes de cambiar de programa de facturación (ver `jaume_sabater.py`), con "Núm. IT 2026-0002" y
"FECHA" en líneas separadas. La tabla tuvo dos variantes:

    Código Descripción Precio Cantidad Importe
    003 Administración de sistemas 100,00 € 17.5 1.750,00€

    Código Producto Precio Impuesto %IMP. %IRPF Cantidad Importe
    003 Administración de sistemas 100,00 € IVA 21% 15% 17.5 1.855,00 €

(en la segunda, el importe de la línea ya incluye IVA e IRPF: el de la línea se calcula como
precio × cantidad). Al pie:

    Base imponible 1.750,00 €
    IVA (21%) 367,50 €        (o "IVA 21% 367,50 €")
    IRPF (15%) -262,50 €      (o "IRPF -262,50 €")
    Total 1.855,00 €

Lleva retención de IRPF: el `total` es el importe a pagar y `impuestos` = IVA − IRPF.
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

NUM = r"-?\d[\d.,]*"
LINEA = re.compile(
    rf"^(?P<codigo>\d+)\s+(?P<descripcion>.+?)\s+(?P<precio>{NUM})\s*€"
    rf"(?:\s+IVA\s+(?P<iva>{NUM})%\s+{NUM}%)?\s+(?P<cantidad>{NUM})\s+{NUM}\s*€$"
)


@registrar
class JaumeSabaterAnterior(Extractor):
    clave = "jaume_sabater_anterior"
    nombre = "Jaume Sabater (hasta abril de 2026)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        filas = [f.strip() for f in texto.splitlines()]
        iva_pct = buscar(rf"^IVA\s*\(?({NUM})%", texto, "el % de IVA", flags=re.M)
        lineas = []
        for fila in filas:
            if m := LINEA.match(fila):
                cantidad, precio = importe(m["cantidad"], decimal="."), importe(m["precio"])
                lineas.append(
                    Linea(
                        descripcion=m["descripcion"],
                        cantidad=cantidad,
                        precio_unitario=precio,
                        importe=(cantidad * precio).quantize(Decimal("0.01")),
                        impuesto_pct=importe(m["iva"] or iva_pct),
                    )
                )
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de la factura")

        base = importe(buscar(rf"^Base imponible\s+({NUM})", texto, "la base", flags=re.M))
        iva = importe(buscar(rf"^IVA\s*\(?{NUM}%\)?\s+({NUM})\s*€", texto, "el IVA", flags=re.M))
        irpf = buscar(rf"^IRPF(?:\s*\({NUM}%\))?\s+({NUM})\s*€", texto, "el IRPF", flags=re.M)
        total = importe(buscar(rf"^Total\s+({NUM})", texto, "el total", flags=re.M))

        return DatosFactura(
            numero=buscar(r"N[úu]m\.\s*(IT\s*\d{4}-\d+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"^FECHA\s+(\d{1,2}/\d{1,2}/\d{4})", texto, "la fecha", flags=re.M)),
            moneda="EUR",
            base_imponible=base,
            impuestos=iva - abs(importe(irpf)),
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
