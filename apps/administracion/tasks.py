"""Tareas en segundo plano de Administración (las ejecuta el qcluster de django-q2)."""

import logging

from integrations import gmail

from .facturas import sincronizar_facturas

logger = logging.getLogger(__name__)


def sincronizar_facturas_gmail(dias: int | None = None) -> str:
    """Programada cada pocas horas (Django Q → Tareas programadas) y lanzable a mano."""
    if not gmail.is_configured():
        logger.warning("Gmail no está configurado: no se buscan facturas")
        return "Gmail no configurado"
    return str(sincronizar_facturas(dias))


def sincronizar_facturas_drive(forzar: bool = False) -> str:
    """Programada cada hora: sube a Drive las facturas nuevas y mira cuáles están contabilizadas.

    `forzar` (el botón "Subir a Drive") la ejecuta aunque la tarea programada esté desactivada.
    """
    from django.conf import settings

    from integrations import drive

    from .drive import sincronizar_drive

    if not (settings.DRIVE["ACTIVO"] or forzar):
        return "Subida a Drive desactivada (DRIVE_FACTURAS_ACTIVO)"
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
