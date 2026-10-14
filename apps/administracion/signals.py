from django.db.models.signals import post_delete
from django.dispatch import receiver

from .extraccion.servicio import clave_duplicado, marcar_duplicados
from .models import FacturaRecibida


@receiver(post_delete, sender=FacturaRecibida)
def recalcular_duplicados(sender, instance: FacturaRecibida, **kwargs) -> None:
    """Si se borra una factura original, la siguiente copia pasa a ser la original."""
    if clave := clave_duplicado(instance):
        marcar_duplicados(*clave)
