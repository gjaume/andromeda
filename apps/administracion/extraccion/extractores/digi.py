"""DIGI Spain Telecom: factura mensual de telefonía móvil, en euros (2–3 páginas).

Página 1: cabecera ("FACTURA Número: DGFC…", "Fecha de emisión dd/mm/aaaa") y resumen:

    TOTAL FACTURA (imp. incl.) 10,10 €
    IMPORTE (base imponible) 8,34 €
    IMPUESTOS (21.00% IVA) 1,76 €

Página 2: "DESGLOSE DE SERVICIOS POR LÍNEA", un bloque por número ("Servicios:600000000")
con secciones (productos, consumo incluido, consumo adicional) cuyos títulos salen con
subrayados intercalados ("P__R_O__D__U_C__T_O__S___"). Cada fila lleva cantidad e importe
sin impuestos:

    Ilimitodo (15 Dic - 14 Ene) 1 8,26 €
    Llamadas incluidas en tu producto 352:39 0,00 €
    SMS 2 0,08 €
    TOTAL CUOTAS 8,26 €

Se guardan las filas de detalle (no los "TOTAL …"). La cantidad solo se guarda cuando es un
número (los minutos "352:39" o los "0,00 MB" no). Si la factura tiene varios números, cada
línea lleva delante el número al que corresponde. La página 3, cuando aparece, es informativa.
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
    rf"^(?P<descripcion>.+?) (?P<cantidad>[\d:.,]+(?: [KMG]B)?) (?P<importe>{IMPORTE_ES}) €$"
)
SERVICIO = re.compile(r"^Servicios:\s*(?P<numero>\d+)", re.M)
IVA = re.compile(rf"^IMPUESTOS \((?P<pct>[\d.,]+)% IVA\) (?P<importe>{IMPORTE_ES}) €$", re.M)


@registrar
class Digi(Extractor):
    clave = "digi"
    nombre = "DIGI (telefonía móvil)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto

        def total(etiqueta: str, que: str):
            patron = rf"^{etiqueta} ({IMPORTE_ES}) €$"
            return importe(buscar(patron, texto, que, flags=re.M), decimal=",")

        ivas = IVA.findall(texto)
        if not ivas:
            raise ExtraccionError("No encuentro el IVA")
        tipos = {Decimal(pct.replace(",", ".")) for pct, _ in ivas}
        impuesto_pct = tipos.pop() if len(tipos) == 1 else None
        total_factura = total(r"TOTAL FACTURA \(imp\. incl\.\)", "el total")

        lineas = self._lineas(texto, impuesto_pct)
        if not lineas:
            raise ExtraccionError("No encuentro el desglose de servicios")

        es_abono = total_factura < 0 or re.search(r"rectificativa|abono", texto[:300], re.I)
        return DatosFactura(
            numero=buscar(r"FACTURA Número:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Fecha de emisión\s+(\d{2}/\d{2}/\d{4})", texto, "la fecha")),
            moneda="EUR",
            base_imponible=total(r"IMPORTE \(base imponible\)", "la base imponible"),
            impuestos=sum((importe(iva, decimal=",") for _, iva in ivas), Decimal(0)),
            total=total_factura,
            tipo="abono" if es_abono else "factura",
            lineas=lineas,
        )

    def _lineas(self, texto: str, impuesto_pct: Decimal | None) -> list[Linea]:
        _, separador, desglose = texto.partition("DESGLOSE DE SERVICIOS POR LÍNEA")
        if not separador:
            return []
        varios_numeros = len(set(SERVICIO.findall(desglose))) > 1
        lineas, numero = [], ""
        for fila in desglose.splitlines():
            fila = fila.strip()
            if m := SERVICIO.match(fila):
                numero = m["numero"]
            elif (m := FILA.match(fila)) and not m["descripcion"].upper().startswith("TOTAL"):
                cantidad = m["cantidad"]
                descripcion = m["descripcion"]
                lineas.append(
                    Linea(
                        descripcion=f"{numero}: {descripcion}" if varios_numeros else descripcion,
                        cantidad=importe(cantidad, decimal=",") if cantidad.isdigit() else None,
                        importe=importe(m["importe"], decimal=",").quantize(Decimal("0.01")),
                        impuesto_pct=impuesto_pct,
                    )
                )
        return lineas
