"""Eni Plenitude Iberia: factura mensual de electricidad, en euros (4 páginas).

Página 1: cabecera ("Nº de factura:F26ES-…", "Fecha de factura :dd/mm/aaaa") y resumen.
Página 2: "DETALLE FACTURA", con secciones ("Facturación por potencia contratada:",
"Descuento sobre T. Energia:"…) y una fila por concepto con el importe sin IVA al final:

    Periodo P1 (01/12/2025 - 31/12/2025): 3,8000 kW * 0,073782 €/kW día * 31 días 8,69 €
    Consumo Fácil (01/12/2025 - 31/12/2025): 158,0000 kWh * 0,099092 €/kWh 15,65 €
    Descuento Fácil (01/04/2026 - 31/05/2026): 15,00 % s/ 55,6400 € -8,34 €
    Subtotal 33,03 €
    Impuesto electricidad (33,0300 * 5,11%) 1,69 €
    Alquiler de equipos de medida y control (31 días * 0,050323 €/día) 1,56 €
    Base imponible 36,28 €
    Impuestos:
    IVA General (21%) 21,00 % s/36,28 € 7,62 €
    TOTAL IMPORTE FACTURA 43,90 €

Se guardan todas las filas hasta "Base imponible" salvo los subtotales: potencia (por periodo),
energía, descuentos (negativos), impuesto eléctrico y alquiler del contador. El impuesto
eléctrico es una línea más porque forma parte de la base del IVA. El IVA cambia de tipo según
el mes (21 % general o 10 % reducido); si hubiera varios tipos se suman todos. Las páginas 3
(maxímetros) y 4 (origen de la electricidad) no se usan.
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
FILA = re.compile(rf"^(?P<concepto>.+?) (?P<importe>{IMPORTE_ES}) €$")
# "158,0000 kWh * 0,099092 €/kWh": cantidad y precio de la energía.
ENERGIA = re.compile(r"(?P<cantidad>[\d.]*\d,\d+) kWh \* (?P<precio>[\d.]*\d,\d+) €/kWh$")
IVA = re.compile(
    rf"^IVA .*?(?P<pct>\d+,\d+) % s/(?:{IMPORTE_ES}) € (?P<importe>{IMPORTE_ES}) €$", re.M
)


@registrar
class Plenitude(Extractor):
    clave = "plenitude"
    nombre = "Plenitude (electricidad)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto

        def total(etiqueta: str, que: str):
            patron = rf"^{etiqueta}\s*({IMPORTE_ES}) €"
            return importe(buscar(patron, texto, que, flags=re.M), decimal=",")

        ivas = IVA.findall(texto)
        if not ivas:
            raise ExtraccionError("No encuentro el IVA")
        tipos = {importe(pct, decimal=",") for pct, _ in ivas}
        impuesto_pct = tipos.pop() if len(tipos) == 1 else None
        total_factura = total("TOTAL IMPORTE FACTURA", "el total")

        lineas = self._lineas(texto, impuesto_pct)
        if not lineas:
            raise ExtraccionError("No encuentro el detalle de la factura")

        cabecera = doc.paginas[0][:500]
        es_abono = total_factura < 0 or re.search(r"rectificativa|abono", cabecera, re.I)
        return DatosFactura(
            numero=buscar(r"Nº de factura:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Fecha de factura\s*:\s*(\d{2}/\d{2}/\d{4})", texto, "la fecha")),
            moneda="EUR",
            base_imponible=total("Base imponible", "la base imponible"),
            impuestos=sum((importe(iva, decimal=",") for _, iva in ivas), Decimal(0)),
            total=total_factura,
            tipo="abono" if es_abono else "factura",
            lineas=lineas,
        )

    def _lineas(self, texto: str, impuesto_pct: Decimal | None) -> list[Linea]:
        _, separador, detalle = texto.partition("DETALLE FACTURA")
        if not separador:
            return []
        lineas = []
        for fila in detalle.splitlines():
            fila = fila.strip()
            if fila.startswith("Base imponible"):
                break
            m = FILA.match(fila)
            if not m or m["concepto"].startswith("Subtotal"):
                continue
            concepto = m["concepto"]
            if concepto.startswith("Periodo "):
                concepto = f"Potencia {concepto[0].lower()}{concepto[1:]}"
            cantidad = precio = None
            if e := ENERGIA.search(concepto):
                cantidad = importe(e["cantidad"], decimal=",")
                precio = importe(e["precio"], decimal=",")
            lineas.append(
                Linea(
                    descripcion=concepto,
                    cantidad=cantidad,
                    precio_unitario=precio,
                    importe=importe(m["importe"], decimal=",").quantize(Decimal("0.01")),
                    impuesto_pct=impuesto_pct,
                )
            )
        return lineas
