"""PYR Asesores (asesoría fiscal y laboral): factura mensual en euros, de un programa de gestión.

Se lee el texto con columnas conservadas (`texto_layout`), porque el cuadro de totales tiene
columnas que pueden ir vacías. Partes del PDF:

    FECHA CLIENTE Nº FACTURA PÁGINA
    31/01/26 2478 1/58 1                      ← fecha (año con 2 cifras) y nº "serie/número"
    FECHA DESCRIPCION UNID. PRECIO U. % DTO. CARGOS ABONOS
    31/01/26 Tarifa plana: Sociedad Limitada o 1,00 194,65 194,65
          Asociación (Desde 0 a 2.000 asientos)   ← la descripción sigue en la fila siguiente
    30/07/26 Elaboración y preparación RIIB 1,00 400,00 50 200,00   ← con % de descuento
    I . V . A . : B A S E % %R.Eq. …
       840,90    21                   10        ← base del IVA y tipo
    HONORARIOS  GASTOS SUPLIDOS  I . V . A . + R E C . E Q . I.R.P.F. PROV.FONDOS
       840,90         105,91        176,59      ← cada importe bajo su columna (o vacía)
    FORMA DE PAGO                IMPORTE LIQUIDO
     Recibo bancario                1.123,40

Las cantidades salen a veces con un espacio antes de la coma ("1 ,00").

Los "gastos suplidos" (tasas pagadas por cuenta del cliente, p. ej. el depósito de cuentas
anuales) no llevan IVA pero se cobran en la factura. Como `DatosFactura` no tiene un campo
aparte, se suman a `base_imponible` (honorarios + suplidos) y sus líneas (las que empiezan por
"Suplido") llevan impuesto 0 %; así las líneas suman la base y base + impuestos = total. Si
hubiera retención de IRPF, `impuestos` = IVA − IRPF y el `total` es el importe líquido.

Los importes del cuadro de totales se asignan a la columna cuya cabecera empieza antes del
final del número (van alineados a la derecha bajo su cabecera). La columna ABONOS no se
distingue de CARGOS por posición; no ha aparecido nunca, y si apareciera los totales no
cuadrarían y `comprobar` avisaría.
"""

import re
from decimal import Decimal

from ..base import (
    DatosFactura,
    Documento,
    ExtraccionError,
    Extractor,
    Linea,
    buscar_grupos,
    fecha,
    importe,
    registrar,
)

NUM = r"-?\d[\d.,]*"
CANTIDAD = r"-?\d+\s?,\d+"  # "1,00" o "1 ,00"
CABECERA_LINEAS = re.compile(r"^FECHA\s+DESCRIPCION\s+UNID", re.IGNORECASE)
FIN_LINEAS = re.compile(r"^I\s*\.\s*V\s*\.\s*A", re.IGNORECASE)
LINEA = re.compile(
    rf"^(?P<fecha>\d{{2}}/\d{{2}}/\d{{2,4}})\s+(?P<descripcion>.+?)\s+(?P<cantidad>{CANTIDAD})"
    rf"\s+(?P<precio>{NUM})(?:\s+(?P<dto>\d+(?:,\d+)?))?\s+(?P<importe>{NUM})$"
)
# Columnas del cuadro de totales: (campo, texto de la cabecera)
COLUMNAS = [
    ("honorarios", "HONORARIOS"),
    ("suplidos", "GASTOS"),
    ("iva", "I . V . A"),
    ("irpf", "I.R.P.F."),
    ("fondos", "PROV.FONDOS"),
]


def _totales(texto: str) -> dict[str, Decimal]:
    """Importes del cuadro HONORARIOS / SUPLIDOS / IVA / IRPF / PROV.FONDOS por columna."""
    filas = texto.splitlines()
    i = next((i for i, f in enumerate(filas) if "HONORARIOS" in f and "SUPLIDOS" in f), None)
    if i is None:
        raise ExtraccionError("No encuentro el cuadro de honorarios")
    fila = filas[i]
    inicios = []
    for campo, cabecera in COLUMNAS:
        posicion = fila.find(cabecera)
        if posicion < 0:
            raise ExtraccionError(f"No encuentro la columna {cabecera} en los totales")
        inicios.append((posicion, campo))
    valores = next((f for f in filas[i + 1 :] if f.strip()), "")
    totales = {campo: Decimal(0) for campo, _ in COLUMNAS}
    for m in re.finditer(NUM, valores):
        campo = [c for inicio, c in inicios if inicio < m.end()]
        if not campo:
            raise ExtraccionError(f"No sé a qué columna corresponde {m[0]!r}")
        totales[campo[-1]] += importe(m[0])
    return totales


@registrar
class PyrAsesores(Extractor):
    clave = "pyr_asesores"
    nombre = "PYR Asesores (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        texto = doc.texto_layout
        fecha_texto, numero = buscar_grupos(
            r"^\s*(\d{2}/\d{2}/\d{2,4})\s+\d+\s+(\d+/\d+)\s+\d+\s*$",
            texto,
            "la fecha y el nº de factura",
            flags=re.M,
        )
        tipo_iva = importe(
            buscar_grupos(
                rf"^\s*I\s*\.\s*V\s*\.\s*A.*\n\s*{NUM}\s+(\d+(?:,\d+)?)\b",
                texto,
                "el tipo de IVA",
                flags=re.M,
            )[0]
        )

        lineas, dentro = [], False
        for fila in (f.strip() for f in texto.splitlines()):
            if CABECERA_LINEAS.match(fila):
                dentro = True
            elif dentro and FIN_LINEAS.match(fila):
                dentro = False
            elif dentro and (m := LINEA.match(fila)):
                descripcion = re.sub(r"\s+", " ", m["descripcion"])
                lineas.append(
                    Linea(
                        descripcion=descripcion,
                        cantidad=importe(m["cantidad"].replace(" ", "")),
                        precio_unitario=importe(m["precio"]),
                        importe=importe(m["importe"]).quantize(Decimal("0.01")),
                        impuesto_pct=(
                            Decimal(0) if descripcion.lower().startswith("suplido") else tipo_iva
                        ),
                    )
                )
            elif dentro and fila and lineas:  # descripción partida en varias filas
                lineas[-1].descripcion += " " + re.sub(r"\s+", " ", fila)
        if not lineas:
            raise ExtraccionError("No encuentro las líneas de la factura")

        totales = _totales(texto)
        (liquido,) = buscar_grupos(
            rf"IMPORTE LIQUIDO\s*\n.*?({NUM})\s*$", texto, "el importe líquido", flags=re.M
        )
        total = importe(liquido)
        return DatosFactura(
            numero=numero,
            fecha=fecha(fecha_texto),
            moneda="EUR",
            base_imponible=totales["honorarios"] + totales["suplidos"],
            impuestos=totales["iva"] - abs(totales["irpf"]),
            total=total,
            tipo="abono" if total < 0 else "factura",
            lineas=lineas,
        )
