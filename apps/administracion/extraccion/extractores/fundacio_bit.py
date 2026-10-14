"""Fundació BIT (ParcBIT): factura de potencia térmica del local, en español con pie en catalán.

Facturas "TC - 2600005" de una página, importes en formato ES ("16,66Eur", "8,330"). Cabecera
con "NÚMERO FACTURA" y "FECHA DE LA FACTURA" en una línea y el valor en la siguiente, mezclado
con la dirección del cliente ("13 de enero de 2026 CIF: …"). Tabla "Concepto Cantidad Precio
Importe" con una fila por concepto, precedida de un código ("2/ 3/ 1"), y líneas de detalle
debajo que se añaden a su descripción:

    2/ 3/ 1 POTENCIA TÉRMICA FIJA PARCBIT 2 8,330 16,66Eur
    Consumo térmico ENERO Y FEBRERO 2026

Al pie, una fila por tipo de IVA bajo "Base imponible % IVA Cuota IVA %Ret. Retención Total
Factura": "16,66 21% 3,50 0% 0,00 20,16Eur". Si hay retención, `impuestos` es IVA − retención,
para que base + impuestos = total (el importe a pagar).

Junto a la factura, el proveedor envía el "DETALLE CONSUMO ENERGÍA TÉRMICA" de cada mes (lecturas
de contadores e "IMPORTE TOTAL"): es un anexo informativo, no una factura (NoEsFactura).
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
    NoEsFactura,
    buscar,
    fecha,
    importe,
    registrar,
)

CABECERA = re.compile(r"^Concepto\s+Cantidad\s+Precio\s+Importe$", re.M)
PIE = re.compile(r"^Base imponible\s+% IVA\s+Cuota IVA.*$", re.M)
FILA = re.compile(
    rf"^(?:\d+/\s*)*\d+\s+(?P<concepto>.+?)\s+(?P<cantidad>{IMPORTE})\s+(?P<precio>{IMPORTE})"
    rf"\s+(?P<importe>{IMPORTE})\s*Eur$"
)
IMPUESTOS = re.compile(
    rf"^(?P<base>{IMPORTE})\s+(?P<iva_pct>[\d,]+)%\s+(?P<iva>{IMPORTE})\s+[\d,]+%\s+"
    rf"(?P<retencion>{IMPORTE})\s+(?P<total>{IMPORTE})\s*Eur$",
    re.M,
)


def _euros(texto: str) -> Decimal:
    return importe(texto, decimal=",")


@registrar
class FundacioBit(Extractor):
    clave = "fundacio_bit"
    nombre = "Fundació BIT (potencia térmica)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        if re.search(r"DETALLE CONSUMO ENERG[ÍI]A T[ÉE]RMICA", texto, re.I):
            raise NoEsFactura(
                "No es una factura: es el detalle de consumo de energía térmica (anexo "
                "informativo de la factura TC)"
            )
        inicio, pie = CABECERA.search(texto), PIE.search(texto)
        if not inicio or not pie:
            raise ExtraccionError("No encuentro la tabla de conceptos (Concepto … Importe)")

        lineas: list[Linea] = []
        for fila in texto[inicio.end() : pie.start()].splitlines():
            fila = fila.strip()
            if m := FILA.match(fila):
                lineas.append(
                    Linea(
                        descripcion=m["concepto"],
                        cantidad=_euros(m["cantidad"]),
                        precio_unitario=_euros(m["precio"]),
                        importe=_euros(m["importe"]).quantize(Decimal("0.01")),
                    )
                )
            elif fila and lineas:
                lineas[-1].descripcion += f" - {fila}"
        if not lineas:
            raise ExtraccionError("No encuentro ningún concepto con importes")

        filas_iva = list(IMPUESTOS.finditer(texto, pie.end()))
        if not filas_iva:
            raise ExtraccionError("No encuentro el cuadro de base, IVA y total")
        base = sum((_euros(m["base"]) for m in filas_iva), Decimal("0.00"))
        impuestos = sum(
            (_euros(m["iva"]) - _euros(m["retencion"]) for m in filas_iva), Decimal("0.00")
        )
        total = sum((_euros(m["total"]) for m in filas_iva), Decimal("0.00"))
        if len(filas_iva) == 1:
            for linea in lineas:
                linea.impuesto_pct = _euros(filas_iva[0]["iva_pct"])

        numero = buscar(r"N[ÚU]MERO FACTURA\s*\n\s*(\w+\s*-\s*\d+)", texto, "el nº de factura")
        return DatosFactura(
            numero=re.sub(r"\s+", "", numero),
            fecha=fecha(
                buscar(r"FECHA DE LA FACTURA.*\n\s*(\d{1,2} de \w+ de \d{4})", texto, "la fecha")
            ),
            moneda="EUR",
            tipo="abono" if re.search(r"RECTIFICATIVA", texto, re.I) else "factura",
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
