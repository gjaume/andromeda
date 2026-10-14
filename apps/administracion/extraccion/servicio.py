"""Aplica el extractor del proveedor a una factura descargada y guarda el resultado."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import FacturaRecibida, LineaFactura
from .base import DatosFactura, Documento, ExtraccionError, registro

logger = logging.getLogger(__name__)

TOLERANCIA = Decimal("0.02")  # redondeos de céntimos entre líneas, base y total


def comprobar(datos: DatosFactura) -> list[str]:
    """Avisos si los importes no cuadran entre sí. Sin avisos, la extracción es fiable."""
    avisos = []
    if datos.lineas and datos.base_imponible is not None:
        suma = sum((linea.importe for linea in datos.lineas), Decimal(0))
        if abs(suma - datos.base_imponible) > TOLERANCIA * len(datos.lineas):
            avisos.append(f"Las líneas suman {suma} y la base imponible es {datos.base_imponible}")
    if datos.base_imponible is not None and datos.impuestos is not None:
        esperado = datos.base_imponible + datos.impuestos
        if abs(esperado - datos.total) > TOLERANCIA:
            avisos.append(
                f"Base {datos.base_imponible} + impuestos {datos.impuestos} = {esperado}, "
                f"pero el total es {datos.total}"
            )
    if not datos.lineas:
        avisos.append("No se han encontrado líneas")
    if datos.moneda not in ("EUR", "USD", "GBP"):
        avisos.append(f"Moneda desconocida: {datos.moneda!r}")
    return avisos


def leer(factura: FacturaRecibida) -> DatosFactura:
    """Extrae los datos sin guardarlos (para probar extractores)."""
    clave = factura.proveedor.extractor
    if clave not in registro:
        raise ExtraccionError(f"El proveedor no tiene un extractor válido ({clave or 'vacío'})")
    with factura.archivo.open("rb") as fichero:
        doc = Documento(fichero.read(), factura.nombre_archivo)
    return registro[clave].extraer(doc)


def extraer_datos(factura: FacturaRecibida) -> FacturaRecibida:
    """Rellena los datos extraídos de la factura. Nunca lanza: el fallo queda en su estado."""
    Estado = FacturaRecibida.Extraccion
    datos, avisos = None, []
    if not factura.proveedor.extractor:
        estado, detalle = Estado.SIN_EXTRACTOR, ""
    else:
        try:
            datos = leer(factura)
        except ExtraccionError as exc:
            estado, detalle = Estado.ERROR, str(exc)
        except Exception as exc:  # un PDF raro no debe parar la sincronización
            logger.exception("Error inesperado extrayendo la factura %s", factura.pk)
            estado, detalle = Estado.ERROR, f"Error inesperado: {exc!r}"
        else:
            avisos = comprobar(datos)
            estado = Estado.REVISAR if avisos else Estado.OK
            detalle = "\n".join(avisos)

    with transaction.atomic():
        factura.lineas.all().delete()
        factura.extraccion_estado = estado
        factura.extraccion_detalle = detalle
        factura.extraida_en = timezone.now()
        if datos:
            factura.tipo = datos.tipo
            factura.numero_factura = datos.numero[:100]
            factura.fecha_factura = datos.fecha
            factura.moneda = datos.moneda
            factura.base_imponible = datos.base_imponible
            factura.impuestos = datos.impuestos
            factura.total = datos.total
            LineaFactura.objects.bulk_create(
                LineaFactura(
                    factura=factura,
                    orden=orden,
                    descripcion=linea.descripcion,
                    cantidad=linea.cantidad,
                    precio_unitario=linea.precio_unitario,
                    importe=linea.importe,
                    impuesto_pct=linea.impuesto_pct,
                )
                for orden, linea in enumerate(datos.lineas, start=1)
            )
        else:
            for campo in ("tipo", "numero_factura", "moneda"):
                setattr(factura, campo, "")
            for campo in ("fecha_factura", "base_imponible", "impuestos", "total"):
                setattr(factura, campo, None)
        factura.save()
    return factura
