"""OVH Hispano: factura de servidores dedicados en euros, en español con importes en formato EN.

Cabecera con "Referencia de la factura: ES…", "Fecha de emisión: dd/mm/aaaa" y el resumen:

    Total de la factura, IVA no incl. 14.71 €
    IVA (21%) 3.09 €
    Importe total de la factura (IVA incl.) 17.80 €

Después, una tabla por grupo ("Dedicado", "Varios DEDICATED-OPTION"…) con las columnas
"Suscripción | Referencia | Cantidad | Precio unitario | Precio" y "SUBTOTAL" al final. En el
texto plano la descripción y la referencia del servidor se parten en varias líneas mezcladas:

    RISE-STOR-1 rental for 1 month prorrateado a 8
    días pbs1.example.com
    Del 01-01-2026 al 08-01-2026 ns000.ip-10-0-0- 1 14.71 € 14.71 €
    Fecha de finalización del compromiso : 0.eu
    09/01/2026

Cada concepto termina en la línea con "cantidad precio € importe €". La descripción se rehace
juntando sus líneas y quitando las piezas de la referencia (nombres de host), el periodo
("Del … al …") y la fecha de fin de compromiso. Se guarda con el grupo delante.
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
    buscar,
    buscar_grupos,
    buscar_opcional,
    fecha,
    importe,
    registrar,
)

FILA = re.compile(
    rf"^(?P<texto>.*?)(?:^|\s)(?P<cantidad>\d+) (?P<precio>{IMPORTE}) € (?P<importe>{IMPORTE}) €$"
)
CABECERA = re.compile(r"^\S+ Referencia Cantidad Precio$")
SUBTOTAL = re.compile(rf"^SUBTOTAL {IMPORTE} €$")
FIN_DETALLE = re.compile(rf"^Precio {IMPORTE} €$")
# Líneas que no forman parte de la descripción de ningún concepto.
RUIDO = re.compile(
    r"^(?:Precio|unitario|Fecha de finalización del compromiso.*|\d{2}/\d{2}/\d{4}"
    r"|Factura \S+ Página \d+/\d+|OVH HISPANO.*|NIF: \S+ - Inscrita.*)$"
)
PERIODO = re.compile(r"Del \d{2}-\d{2}-\d{4} al \d{2}-\d{2}-\d{4}")
# Trozos de la columna "Referencia": ns000.ip-10-0-0-, "10-0-", "0.eu", host.example.com…
REFERENCIA = re.compile(r"\S*\.ip-\S*|\d+-\d+-(?:\d+-)?|[\w.-]+\.(?:eu|com|net|org|es|ovh)")


def _descripcion(trozos: list[str]) -> str:
    texto = PERIODO.sub(" ", " ".join(trozos))
    palabras = [p for p in texto.split() if not REFERENCIA.fullmatch(p)]
    return " ".join(palabras)


@registrar
class Ovh(Extractor):
    clave = "ovh"
    nombre = "OVH (servidores dedicados)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto

        def total(etiqueta: str, que: str):
            return importe(
                buscar(rf"^{etiqueta}\s+({IMPORTE}) €", texto, que, flags=re.M), decimal="."
            )

        base = total(r"Total de la factura, IVA no incl\.", "la base imponible")
        iva_pct, iva = buscar_grupos(
            rf"^IVA \((\d+(?:\.\d+)?)%\)\s+({IMPORTE}) €", texto, "el IVA", flags=re.M
        )
        total_factura = total(r"Importe total de la factura \(IVA incl\.\)", "el total")
        impuesto_pct = Decimal(iva_pct)

        lineas = self._lineas(texto, impuesto_pct)
        if not lineas:
            raise ExtraccionError("No encuentro el detalle de conceptos")

        tipo_factura = buscar_opcional(r"Tipo de factura:\s*(.+)", texto) or ""
        es_abono = total_factura < 0 or re.search(r"abono|crédito", tipo_factura, re.I)
        return DatosFactura(
            numero=buscar(r"Referencia de la factura:\s*(\S+)", texto, "el nº de factura"),
            fecha=fecha(buscar(r"Fecha de emisión:\s*(\S+)", texto, "la fecha")),
            moneda="EUR",
            base_imponible=base,
            impuestos=importe(iva, decimal="."),
            total=total_factura,
            tipo="abono" if es_abono else "factura",
            lineas=lineas,
        )

    def _lineas(self, texto: str, impuesto_pct: Decimal) -> list[Linea]:
        filas = texto.splitlines()
        inicio = next(
            (i for i, f in enumerate(filas) if f.startswith("Importe total de la factura")), None
        )
        if inicio is None:
            return []
        lineas, grupo, trozos = [], "", []
        for fila in filas[inicio + 1 :]:
            fila = fila.strip()
            if FIN_DETALLE.match(fila):
                break
            if CABECERA.match(fila):
                # El nombre del grupo es lo único que queda antes de la cabecera de la tabla
                # (tras un salto de página la cabecera se repite sin grupo).
                if trozos:
                    grupo = trozos[-1]
                trozos = []
            elif SUBTOTAL.match(fila):
                trozos = []
            elif m := FILA.match(fila):
                trozos.append(m["texto"])
                descripcion = _descripcion(trozos)
                lineas.append(
                    Linea(
                        descripcion=f"{grupo}: {descripcion}" if grupo else descripcion,
                        cantidad=Decimal(m["cantidad"]),
                        precio_unitario=importe(m["precio"], decimal="."),
                        importe=importe(m["importe"], decimal=".").quantize(Decimal("0.01")),
                        impuesto_pct=impuesto_pct,
                    )
                )
                trozos = []
            elif not RUIDO.match(fila) and _descripcion([fila]):
                trozos.append(fila)
        return lineas
