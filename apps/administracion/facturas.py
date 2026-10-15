"""Descarga de facturas de proveedores desde el buzón de Gmail de administración.

Por cada proveedor activo busca los correos con su etiqueta "Gastos/<proveedor>", y de los que
aún no se han procesado guarda los adjuntos PDF como FacturaRecibida. Cada correo se procesa una
sola vez (CorreoFactura), tenga o no facturas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import PurePath

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.gmail import GmailAuthError, GmailClient, GmailError, GmailMessage, get_client

from .extraccion.servicio import extraer_datos
from .models import CorreoFactura, FacturaRecibida, Proveedor

logger = logging.getLogger(__name__)

EXTENSIONES_FACTURA = {".pdf"}


@dataclass
class ResultadoSincronizacion:
    correos_nuevos: int = 0
    facturas_nuevas: int = 0
    etiquetas_no_encontradas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        partes = [f"{self.facturas_nuevas} facturas nuevas en {self.correos_nuevos} correos"]
        if self.etiquetas_no_encontradas:
            partes.append(f"etiquetas no encontradas: {', '.join(self.etiquetas_no_encontradas)}")
        if self.errores:
            partes.append(f"{len(self.errores)} errores")
        return "; ".join(partes)


def es_factura(nombre_archivo: str) -> bool:
    return PurePath(nombre_archivo).suffix.lower() in EXTENSIONES_FACTURA


def consulta_gmail(dias: int | None = None, desde: date | None = None) -> str:
    """Filtro de búsqueda de Gmail: desde una fecha o los últimos `dias` días (0 = todo)."""
    if desde:
        # Marca de tiempo exacta: con "after:AAAA/MM/DD" Gmail usa la hora del Pacífico
        inicio = timezone.make_aware(datetime.combine(desde, time.min))
        return f"after:{int(inicio.timestamp())}"
    dias = settings.GMAIL["SYNC_DAYS"] if dias is None else dias
    return f"newer_than:{dias}d" if dias else ""


def sincronizar_facturas(
    dias: int | None = None, *, desde: date | None = None, client: GmailClient | None = None
) -> ResultadoSincronizacion:
    """Busca facturas nuevas desde la fecha `desde`, o de los últimos `dias` días (0 = todas)."""
    query = consulta_gmail(dias, desde)
    resultado = ResultadoSincronizacion()

    gmail = client or get_client()
    try:
        etiquetas = {nombre.casefold(): id_ for nombre, id_ in gmail.labels().items()}
        for proveedor in Proveedor.objects.filter(activo=True):
            label_id = etiquetas.get(proveedor.etiqueta_completa.casefold())
            if not label_id:
                logger.warning("No existe la etiqueta de Gmail %s", proveedor.etiqueta_completa)
                resultado.etiquetas_no_encontradas.append(proveedor.etiqueta_completa)
                continue
            _sincronizar_proveedor(gmail, proveedor, label_id, query, resultado)
    finally:
        if client is None:
            gmail.close()

    logger.info("Sincronización de facturas: %s", resultado)
    return resultado


def _sincronizar_proveedor(gmail, proveedor, label_id, query, resultado) -> None:
    ids = list(gmail.message_ids(label_id, query))
    ya_procesados = set(
        CorreoFactura.objects.filter(gmail_id__in=ids).values_list("gmail_id", flat=True)
    )
    # Del más antiguo al más reciente. Un correo que falla no se marca y se reintenta luego.
    for message_id in reversed(ids):
        if message_id in ya_procesados:
            continue
        try:
            mensaje = gmail.message(message_id)
            resultado.facturas_nuevas += _guardar_correo(gmail, proveedor, mensaje)
            resultado.correos_nuevos += 1
        except IntegrityError:
            # Otra sincronización simultánea ya lo guardó
            logger.info("El correo %s ya estaba procesado", message_id)
        except GmailAuthError:
            raise
        except GmailError as exc:
            logger.exception("Error procesando el correo %s de %s", message_id, proveedor)
            resultado.errores.append(f"{proveedor}: correo {message_id}: {exc}")


def _guardar_correo(gmail: GmailClient, proveedor: Proveedor, mensaje: GmailMessage) -> int:
    adjuntos = [a for a in mensaje.attachments if es_factura(a.filename)]
    contenidos = [(a, gmail.attachment_content(mensaje.id, a)) for a in adjuntos]

    facturas = []
    with transaction.atomic():
        correo = CorreoFactura.objects.create(
            proveedor=proveedor,
            gmail_id=mensaje.id,
            asunto=mensaje.subject[:500],
            remitente=mensaje.sender[:320],
            recibido_en=mensaje.received_at,
        )
        for adjunto, contenido in contenidos:
            factura = FacturaRecibida(
                proveedor=proveedor,
                correo=correo,
                gmail_part_id=adjunto.part_id,
                nombre_archivo=adjunto.filename[:255],
                tamano=len(contenido),
                recibida_en=mensaje.received_at,
            )
            factura.archivo.save(adjunto.filename, ContentFile(contenido), save=False)
            factura.save()
            facturas.append(factura)
    for factura in facturas:
        extraer_datos(factura)
    return len(facturas)


def subir_facturas(correo: CorreoFactura, archivos, usuario) -> list[FacturaRecibida]:
    """Adjunta a un correo las facturas que el proveedor no mandó en PDF (descargadas a mano)."""
    facturas = []
    with transaction.atomic():
        for archivo in archivos:
            factura = FacturaRecibida(
                proveedor=correo.proveedor,
                correo=correo,
                nombre_archivo=archivo.name[:255],
                tamano=archivo.size,
                recibida_en=correo.recibido_en,
                subida_por=usuario,
            )
            factura.archivo.save(archivo.name, archivo, save=False)
            factura.save()
            facturas.append(factura)
    for factura in facturas:
        extraer_datos(factura)
    return facturas
