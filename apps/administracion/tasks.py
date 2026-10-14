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
