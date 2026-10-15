"""Tareas en segundo plano de Administración (las ejecuta el qcluster de django-q2).

Las descargas de Gmail y la subida a Drive se lanzan con los botones de cada pantalla; solo la
conciliación de pagos está programada (Django Q → Tareas programadas).
"""

import logging
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from integrations import gmail

from .facturas import sincronizar_facturas
from .models import CorreoFactura, CorreoNomina

logger = logging.getLogger(__name__)

MARGEN_DIAS = 7  # correos etiquetados con algo de retraso


def desde_el_ultimo_correo(correos) -> date:
    """Desde cuándo buscar al pulsar el botón: unos días antes del último correo procesado, para
    no perder nada aunque pase tiempo entre búsquedas, y como poco GMAIL_SYNC_DAYS días."""
    hoy = timezone.localdate()
    minimo = hoy - timedelta(days=settings.GMAIL["SYNC_DAYS"])
    ultimo = correos.order_by("-recibido_en").values_list("recibido_en", flat=True).first()
    if ultimo is None:
        return minimo
    return min(minimo, timezone.localtime(ultimo).date() - timedelta(days=MARGEN_DIAS))


def sincronizar_facturas_gmail() -> str:
    """Descarga las facturas nuevas (botón "Buscar facturas ahora")."""
    if not gmail.is_configured():
        logger.warning("Gmail no está configurado: no se buscan facturas")
        return "Gmail no configurado"
    return str(sincronizar_facturas(desde=desde_el_ultimo_correo(CorreoFactura.objects)))


def sincronizar_facturas_drive() -> str:
    """Sube a Drive las facturas nuevas y mira cuáles están contabilizadas (botón "Subir a
    Drive")."""
    from integrations import drive

    from .drive import sincronizar_drive

    if not drive.is_configured():
        logger.warning("Drive no está configurado: no se suben facturas")
        return "Drive no configurado"
    resumen = sincronizar_drive()
    for error in resumen.errores:
        logger.error("Drive: %s", error)
    for aviso in resumen.fuera_de_sitio + resumen.sin_empresa:
        logger.warning("Drive: %s", aviso)
    return str(resumen)


def conciliar_pagos_drive() -> str:
    """Programada cada hora: importa los extractos del banco y la tarjeta y concilia los pagos."""
    from integrations import drive

    from .conciliacion.servicio import conciliar_pagos

    if not drive.is_configured():
        logger.warning("Drive no está configurado: no se concilian pagos")
        return "Drive no configurado"
    resumen = conciliar_pagos()
    for aviso in resumen.avisos:
        logger.warning("Conciliación: %s", aviso)
    return str(resumen)


def sincronizar_nominas_gmail() -> str:
    """Descarga las nóminas nuevas (botón "Buscar nóminas ahora")."""
    from .nominas import sincronizar_nominas

    if not gmail.is_configured():
        logger.warning("Gmail no está configurado: no se buscan nóminas")
        return "Gmail no configurado"
    return str(sincronizar_nominas(desde=desde_el_ultimo_correo(CorreoNomina.objects)))
