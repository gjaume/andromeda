from django.conf import settings
from django.db import models


class PopeyeApiCall(models.Model):
    """Auditoría de las llamadas que modifican datos en popeye.

    Popeye solo ve el token del backoffice; aquí queda quién hizo cada operación.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="popeye_api_calls",
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    request_body = models.JSONField(null=True, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    response_excerpt = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "llamada al API de popeye"
        verbose_name_plural = "llamadas al API de popeye"

    def __str__(self) -> str:
        return f"{self.method} {self.path} → {self.status_code or self.error}"
