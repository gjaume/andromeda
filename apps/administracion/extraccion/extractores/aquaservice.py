"""Viva Aqua Service Spain (Aquaservice): factura mensual del agua, en euros (1 página).

Cabecera ("Factura Nº: 261120312369", "Fecha Factura: 31/01/2026", "IMPORTE TOTAL FACTURA
42,41 €") y una fila por producto entregado, con el albarán y la fecha de entrega delante:

    Albarán Fecha Descripción Cant. Precio Importe % IVA Nº Pedido
    1538237 08/01/2026 Consumo de Aquaservice 20 L. 3 6,25 18,75 10,00
    1538237 08/01/2026 Kit de cuidado e higiene de dispensador 1 18,00 18,00 21,00

Después, el "DESGLOSE FACTURA" con una fila por tipo de IVA y, al final, la de totales
("36,75 € 5,66 € 42,41 €"). Las filas a 0,00 (botellas sin cargo) también se guardan.

Junto a cada factura llega el albarán de entrega ("…_Alb.pdf", "Albarán nº 1538237"): es un
justificante sin importes, no una factura (NoEsFactura).
"""

import re

from ..base import (
    DatosFactura,
    Documento,
    ExtraccionError,
    Extractor,
    Linea,
    NoEsFactura,
    buscar,
    buscar_grupos,
    fecha,
    importe,
    registrar,
)

IMPORTE_ES = r"-?[\d.]*\d,\d{2}"
FILA = re.compile(
    rf"^(?P<albaran>\d+) (?P<fecha>\d{{2}}/\d{{2}}/\d{{4}}) (?P<descripcion>.+?) "
    rf"(?P<cantidad>\d+(?:,\d+)?) (?P<precio>{IMPORTE_ES}) (?P<importe>{IMPORTE_ES}) "
    rf"(?P<iva>\d+,\d{{2}})(?: .*)?$"
)


def _importe(texto: str):
    return importe(texto, decimal=",")


@registrar
class Aquaservice(Extractor):
    clave = "aquaservice"
    nombre = "Aquaservice (agua, mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto
        if "Factura Nº" not in texto and re.search(r"^Albarán nº", texto, re.M):
            raise NoEsFactura("No es una factura: es el albarán de entrega de Aquaservice")

        _, separador, desglose = texto.partition("DESGLOSE FACTURA")
        if not separador:
            raise ExtraccionError("No encuentro el desglose de la factura")
        base, impuestos, total = (
            _importe(v)
            for v in buscar_grupos(
                rf"^({IMPORTE_ES}) € ({IMPORTE_ES}) € ({IMPORTE_ES}) €$",
                desglose,
                "los totales del desglose",
                flags=re.M,
            )
        )

        lineas = [
            Linea(
                descripcion=f"{m['descripcion']} (albarán {m['albaran']}, {m['fecha']})",
                cantidad=_importe(m["cantidad"]),
                precio_unitario=_importe(m["precio"]),
                importe=_importe(m["importe"]),
                impuesto_pct=_importe(m["iva"]),
            )
            for m in map(FILA.match, texto.splitlines())
            if m
        ]
        if not lineas:
            raise ExtraccionError("No encuentro los productos de la factura")

        total_cabecera = _importe(
            buscar(rf"IMPORTE TOTAL FACTURA ({IMPORTE_ES}) €", texto, "el importe total")
        )
        if total_cabecera != total:
            raise ExtraccionError(
                f"El total de la cabecera ({total_cabecera}) no coincide con el del desglose "
                f"({total})"
            )

        return DatosFactura(
            numero=buscar(r"Factura Nº:\s*(\d+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Fecha Factura:\s*(\d{2}/\d{2}/\d{4})", texto, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=impuestos,
            total=total,
            lineas=lineas,
        )
