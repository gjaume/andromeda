"""Piezas comunes para los extractores de facturas.

Cada formato de factura (normalmente, uno por proveedor) es una clase en `extractores/` que
recibe un `Documento` y devuelve `DatosFactura`. Las funciones de este módulo resuelven lo que
todos necesitan: leer importes y fechas en formato español o inglés, detectar la moneda y
buscar valores con expresiones regulares con mensajes de error claros.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cached_property
from typing import ClassVar

# --- Resultado de un extractor --------------------------------------------------------------


@dataclass
class Linea:
    descripcion: str
    importe: Decimal  # sin impuestos
    cantidad: Decimal | None = None
    precio_unitario: Decimal | None = None
    impuesto_pct: Decimal | None = None


@dataclass
class DatosFactura:
    """Datos de un documento. Convenciones comunes a todos los extractores:

    - Importes de las líneas y base imponible, SIN impuestos.
    - Abonos (rectificativas, credit notes): importes en negativo aunque el PDF los muestre en
      positivo, para que sumar facturas y abonos dé el gasto real.
    - Retención de IRPF: `total` es lo que se paga e `impuestos` = IVA − IRPF.
    - Recibos (justificantes de pago de una factura): tipo "recibo"; no son gasto adicional.
    """

    total: Decimal
    moneda: str  # ISO 4217: "EUR", "USD"…
    numero: str = ""
    fecha: date | None = None
    base_imponible: Decimal | None = None
    impuestos: Decimal | None = None
    tipo: str = "factura"  # "factura", "abono" (rectificativa) o "recibo" (justificante de pago)
    lineas: list[Linea] = field(default_factory=list)


class ExtraccionError(Exception):
    """El PDF no tiene el formato esperado o falta un dato imprescindible."""


# --- Documento ------------------------------------------------------------------------------


class Documento:
    """Texto de un PDF, página a página. `texto_layout` conserva columnas (útil en tablas)."""

    def __init__(self, contenido: bytes, nombre_archivo: str = "") -> None:
        self._contenido = contenido
        self.nombre_archivo = nombre_archivo
        self._paginas: list[str] | None = None

    @classmethod
    def desde_texto(cls, texto: str | list[str], nombre_archivo: str = "") -> Documento:
        """Para tests: un documento ya convertido a texto (una cadena por página)."""
        doc = cls(b"", nombre_archivo)
        paginas = [texto] if isinstance(texto, str) else list(texto)
        doc._paginas = paginas
        doc.__dict__["paginas_layout"] = paginas
        return doc

    @property
    def paginas(self) -> list[str]:
        if self._paginas is None:
            self._paginas = [p.extract_text() or "" for p in self._pdf().pages]
        return self._paginas

    @cached_property
    def paginas_layout(self) -> list[str]:
        return [p.extract_text(layout=True) or "" for p in self._pdf().pages]

    @property
    def texto(self) -> str:
        return "\n".join(self.paginas)

    @property
    def texto_layout(self) -> str:
        return "\n".join(self.paginas_layout)

    def _pdf(self):
        import pdfplumber

        if "_pdf_abierto" not in self.__dict__:
            self.__dict__["_pdf_abierto"] = pdfplumber.open(io.BytesIO(self._contenido))
        return self.__dict__["_pdf_abierto"]


# --- Registro de extractores ----------------------------------------------------------------


class Extractor:
    clave: ClassVar[str]  # identificador estable, se guarda en Proveedor.extractor
    nombre: ClassVar[str]  # para mostrar, p. ej. "Hetzner (factura mensual)"

    def extraer(self, doc: Documento) -> DatosFactura:
        raise NotImplementedError


registro: dict[str, Extractor] = {}


def registrar(cls: type[Extractor]) -> type[Extractor]:
    if cls.clave in registro:
        raise ValueError(f"Extractor duplicado: {cls.clave}")
    registro[cls.clave] = cls()
    return cls


# --- Utilidades de lectura ------------------------------------------------------------------


def importe(texto: str, *, decimal: str | None = None) -> Decimal:
    """Convierte "1.234,56 €", "$1,234.56", "-12,00", "(12.00)", "0.125" o "1 234,56" en Decimal.

    Sin `decimal`, el separador decimal se deduce: si aparecen "," y ".", el último es el
    decimal; si solo aparece uno, es de miles únicamente cuando separa grupos de 3 cifras
    ("1.234", "1,234,567"), y decimal en cualquier otro caso ("12,5", "0,125", "1.2345").
    """
    limpio = texto.replace("\u00a0", " ").replace("\u202f", " ").strip()
    negativo = limpio.startswith("-") or limpio.endswith("-") or "(" in limpio
    limpio = re.sub(r"[^\d.,]", "", limpio).strip(".,")
    if not re.search(r"\d", limpio):
        raise ExtraccionError(f"No es un importe: {texto!r}")

    if decimal is None:
        separadores = {c for c in limpio if c in ",."}
        if len(separadores) == 2:
            decimal = "," if limpio.rfind(",") > limpio.rfind(".") else "."
        elif separadores:
            sep = separadores.pop()
            partes = limpio.split(sep)
            es_miles = len(partes) > 2 or (len(partes[-1]) == 3 and partes[0] not in ("", "0"))
            decimal = "" if es_miles else sep
        else:
            decimal = ""
    for sep in ",.":
        if sep != decimal:
            limpio = limpio.replace(sep, "")
    if decimal:
        limpio = limpio.replace(decimal, ".")
    try:
        valor = Decimal(limpio)
    except InvalidOperation as exc:
        raise ExtraccionError(f"No es un importe: {texto!r}") from exc
    return -valor if negativo else valor


MESES = {
    # español
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
    "ene": 1, "abr": 4, "ago": 8, "dic": 12,
    # inglés
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # catalán
    "gener": 1, "febrer": 2, "març": 3, "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
    "setembre": 9, "novembre": 11, "desembre": 12,
}  # fmt: skip


def fecha(texto: str, *, dia_primero: bool = True) -> date:
    """Lee "14/10/2026", "2026-10-14", "14 de octubre de 2026", "October 14, 2026", "14 Oct 2026".

    En fechas numéricas ambiguas (03/04/2026) se asume día/mes salvo `dia_primero=False`.
    """
    t = texto.strip().lower().replace(",", " ").replace(".", " ")
    if m := re.search(r"(\d{4})[-/ ](\d{1,2})[-/ ](\d{1,2})", t):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"(\d{1,2})[-/ ](\d{1,2})[-/ ](\d{2,4})", t):
        a, b, anio = int(m[1]), int(m[2]), int(m[3])
        anio += 2000 if anio < 100 else 0
        dia, mes = (a, b) if dia_primero else (b, a)
        return date(anio, mes, dia)
    palabras = re.findall(r"[a-zçñáéíóú]+|\d+", t)
    mes = next((MESES[p] for p in palabras if p in MESES), None)
    numeros = [int(p) for p in palabras if p.isdigit()]
    anio = next((n for n in numeros if n > 31), None)
    dia = next((n for n in numeros if 1 <= n <= 31), None)
    if mes and anio and dia:
        return date(anio, mes, dia)
    raise ExtraccionError(f"No es una fecha: {texto!r}")


def moneda(texto: str) -> str:
    """Moneda que aparece en el texto: "EUR" o "USD" (la más frecuente si aparecen ambas)."""
    usd = len(re.findall(r"US\$|\bUSD\b|\$", texto))
    eur = len(re.findall(r"€|\bEUR\b|\beuros?\b", texto, re.IGNORECASE))
    if not usd and not eur:
        raise ExtraccionError("No encuentro la moneda")
    return "USD" if usd > eur else "EUR"


def buscar(patron: str, texto: str, que: str, *, grupo: int | str = 1, flags=re.IGNORECASE):
    """Primer grupo que casa con `patron`, o ExtraccionError("No encuentro <que>")."""
    if m := re.search(patron, texto, flags):
        return m[grupo].strip()
    raise ExtraccionError(f"No encuentro {que}")


def buscar_grupos(patron: str, texto: str, que: str, *, flags=re.IGNORECASE) -> tuple[str, ...]:
    """Todos los grupos del primer resultado, o ExtraccionError("No encuentro <que>")."""
    if m := re.search(patron, texto, flags):
        return tuple((g or "").strip() for g in m.groups())
    raise ExtraccionError(f"No encuentro {que}")


def buscar_opcional(patron: str, texto: str, *, grupo: int | str = 1, flags=re.IGNORECASE):
    m = re.search(patron, texto, flags)
    return m[grupo].strip() if m else None


IMPORTE = r"-?\(?[\d.,]*\d[\d.,]*\)?"  # para usar dentro de patrones: rf"Total\s+({IMPORTE})"
