"""Extracción de líneas y totales de las facturas en PDF, con un extractor por formato.

Para añadir un formato: crea `extractores/<clave>.py` con una clase decorada con `@registrar`
y asígnala al proveedor en su ficha (campo "formatos de factura"). Se carga sola. Si el
proveedor cambia el diseño de sus facturas, se añade un extractor nuevo y se le asignan los dos.
"""

import importlib
import pkgutil

from . import extractores
from .base import (
    DatosFactura,
    Documento,
    ExtraccionError,
    Extractor,
    Linea,
    NoEsFactura,
    registrar,
    registro,
)

for _modulo in pkgutil.iter_modules(extractores.__path__):
    importlib.import_module(f"{extractores.__name__}.{_modulo.name}")

__all__ = [
    "DatosFactura",
    "Documento",
    "ExtraccionError",
    "Extractor",
    "Linea",
    "NoEsFactura",
    "registrar",
    "registro",
]
