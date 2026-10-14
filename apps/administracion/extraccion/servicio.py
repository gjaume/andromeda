"""Aplica el extractor del proveedor a una factura descargada y guarda el resultado."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import Empresa, FacturaRecibida, LineaFactura
from ..utils import normalizar
from .base import DatosFactura, Documento, ExtraccionError, NoEsFactura, registro

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


def documento(factura: FacturaRecibida) -> Documento:
    with factura.archivo.open("rb") as fichero:
        return Documento(fichero.read(), factura.nombre_archivo)


def leer(factura: FacturaRecibida, doc: Documento | None = None) -> DatosFactura:
    """Extrae los datos sin guardarlos (para probar extractores)."""
    clave = factura.proveedor.extractor
    if clave not in registro:
        raise ExtraccionError(f"El proveedor no tiene un extractor válido ({clave or 'vacío'})")
    return registro[clave].extraer(doc or documento(factura))


def detectar_empresa(texto: str, empresas: list[Empresa]) -> Empresa | None:
    """Empresa del grupo a la que va emitida: por su CIF y, si no aparece, por su nombre.

    None si no aparece ninguna o aparecen varias sin forma de decidir.
    """
    compacto = re.sub(r"[\s.\-]", "", texto).upper()
    por_cif = [e for e in empresas if e.cif and e.cif.upper() in compacto]
    if por_cif:
        return por_cif[0] if len(por_cif) == 1 else None
    normal = normalizar(texto)
    por_nombre = [e for e in empresas if any(normalizar(n) in normal for n in e.nombres)]
    return por_nombre[0] if len(por_nombre) == 1 else None


def extraer_datos(factura: FacturaRecibida) -> FacturaRecibida:
    """Rellena los datos extraídos de la factura. Nunca lanza: el fallo queda en su estado."""
    Estado = FacturaRecibida.Extraccion
    datos, avisos, anexo, empresa = None, [], False, None
    try:
        doc = documento(factura)
        empresa = detectar_empresa(doc.texto, list(Empresa.objects.all()))
    except Exception:  # el PDF no se puede leer: lo dirá el extractor, si lo hay
        logger.warning("No se pudo leer el texto de la factura %s", factura.pk, exc_info=True)
        doc = None
    if not factura.proveedor.extractor:
        estado, detalle = Estado.SIN_EXTRACTOR, ""
    else:
        try:
            datos = leer(factura, doc)
        except NoEsFactura as exc:
            estado, detalle, anexo = Estado.OK, str(exc), True
        except ExtraccionError as exc:
            estado, detalle = Estado.ERROR, str(exc)
        except Exception as exc:  # un PDF raro no debe parar la sincronización
            logger.exception("Error inesperado extrayendo la factura %s", factura.pk)
            estado, detalle = Estado.ERROR, f"Error inesperado: {exc!r}"
        else:
            avisos = comprobar(datos)
            estado = Estado.REVISAR if avisos else Estado.OK
            detalle = "\n".join(avisos)

    clave_anterior = clave_duplicado(factura)
    with transaction.atomic():
        factura.lineas.all().delete()
        factura.extraccion_estado = estado
        factura.extraccion_detalle = detalle
        factura.extraida_en = timezone.now()
        # Si no se reconoce, se conserva la que hubiera (p. ej. asignada a mano en el admin)
        factura.empresa = empresa or factura.empresa
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
            if anexo:
                factura.tipo = FacturaRecibida.Tipo.ANEXO
            for campo in ("fecha_factura", "base_imponible", "impuestos", "total"):
                setattr(factura, campo, None)
        if not factura.numero_factura:
            factura.duplicada_de = None  # sin nº no se puede saber si es copia de otra
        factura.save()
        for clave in {clave_anterior, clave_duplicado(factura)} - {None}:
            marcar_duplicados(*clave)
        factura.refresh_from_db(fields=["duplicada_de"])
    return factura


# --- Duplicados -----------------------------------------------------------------------------


def clave_duplicado(factura: FacturaRecibida) -> tuple[int, str, str] | None:
    """Lo que identifica una factura: proveedor, tipo y nº. Sin nº no se puede saber."""
    if not factura.numero_factura:
        return None
    return factura.proveedor_id, factura.tipo, factura.numero_factura


def marcar_duplicados(proveedor_id: int, tipo: str, numero: str) -> int:
    """La primera recibida con esa clave es la original; las demás, sus duplicados.

    Se recalcula el grupo entero para que quede bien aunque cambie el nº de una de ellas.
    Devuelve cuántas facturas han cambiado.
    """
    grupo = list(
        FacturaRecibida.objects.filter(
            proveedor_id=proveedor_id, tipo=tipo, numero_factura=numero
        ).order_by("recibida_en", "id")
    )
    original = grupo[0] if grupo else None
    cambiadas = 0
    for factura in grupo:
        duplicada_de = None if factura is original else original.pk
        if factura.duplicada_de_id != duplicada_de:
            factura.duplicada_de_id = duplicada_de
            factura.save(update_fields=["duplicada_de"])
            cambiadas += 1
    return cambiadas


def marcar_todos_los_duplicados() -> int:
    """Recalcula los duplicados de todas las facturas. Devuelve cuántas han cambiado."""
    cambiadas = FacturaRecibida.objects.filter(
        numero_factura="", duplicada_de__isnull=False
    ).update(duplicada_de=None)
    claves = (
        FacturaRecibida.objects.exclude(numero_factura="")
        .values_list("proveedor_id", "tipo", "numero_factura")
        .distinct()
    )
    for clave in claves:
        cambiadas += marcar_duplicados(*clave)
    return cambiadas
