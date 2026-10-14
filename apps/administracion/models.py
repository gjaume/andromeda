from pathlib import PurePath

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Proveedor(models.Model):
    nombre = models.CharField(max_length=200, unique=True)
    cif = models.CharField("CIF / NIF", max_length=20, blank=True)
    email = models.EmailField(blank=True)
    etiqueta_gmail = models.CharField(
        "etiqueta de Gmail",
        max_length=200,
        unique=True,
        help_text='Nombre de la subetiqueta dentro de "Gastos" en Gmail, p. ej. Iberdrola.',
    )
    activo = models.BooleanField(
        default=True, help_text="Solo se buscan facturas de los proveedores activos."
    )
    notas = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"

    def __str__(self) -> str:
        return self.nombre

    @property
    def etiqueta_completa(self) -> str:
        return f"{settings.GMAIL['INVOICES_LABEL']}/{self.etiqueta_gmail}"


class CorreoFacturaQuerySet(models.QuerySet):
    def pendientes(self):
        """Sin factura y sin descartar: falta bajar la factura a mano o decidir que no la hay."""
        return self.filter(facturas__isnull=True, descartado_en__isnull=True)


class CorreoFactura(models.Model):
    """Correo de Gmail ya revisado, tenga o no facturas, para no volver a descargarlo."""

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="correos")
    gmail_id = models.CharField(max_length=64, unique=True)
    asunto = models.CharField(max_length=500, blank=True)
    remitente = models.CharField(max_length=320, blank=True)
    recibido_en = models.DateTimeField(db_index=True)
    procesado_en = models.DateTimeField(auto_now_add=True)
    # Correos sin factura que no la necesitan (respuestas, avisos): salen de "Correos sin factura"
    descartado_en = models.DateTimeField(null=True, blank=True)
    descartado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="correos_descartados",
    )

    objects = CorreoFacturaQuerySet.as_manager()

    class Meta:
        ordering = ["-recibido_en"]
        verbose_name = "correo de facturas"
        verbose_name_plural = "correos de facturas"

    def __str__(self) -> str:
        return self.asunto or self.gmail_id

    @property
    def gmail_url(self) -> str:
        return f"https://mail.google.com/mail/u/{settings.GMAIL['MAILBOX']}/#all/{self.gmail_id}"


def factura_upload_to(instance: "FacturaRecibida", filename: str) -> str:
    fecha = instance.correo.recibido_en
    nombre = PurePath(filename)
    limpio = f"{slugify(nombre.stem)[:80] or 'factura'}{nombre.suffix.lower()}"
    return f"facturas/{slugify(instance.proveedor.nombre)}/{fecha:%Y/%m}/{limpio}"


class FacturaRecibida(models.Model):
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="facturas")
    correo = models.ForeignKey(CorreoFactura, on_delete=models.CASCADE, related_name="facturas")
    # Vacío si la factura no venía adjunta y alguien la subió a mano
    gmail_part_id = models.CharField(max_length=32, blank=True)
    subida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="facturas_subidas",
    )
    archivo = models.FileField(upload_to=factura_upload_to, max_length=300)
    nombre_archivo = models.CharField(max_length=255)
    tamano = models.PositiveIntegerField("tamaño (bytes)", default=0)
    recibida_en = models.DateTimeField(db_index=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recibida_en", "-id"]
        verbose_name = "factura recibida"
        verbose_name_plural = "facturas recibidas"
        constraints = [
            models.UniqueConstraint(
                fields=["correo", "gmail_part_id"],
                condition=~models.Q(gmail_part_id=""),
                name="factura_unica_por_adjunto",
            )
        ]

    def __str__(self) -> str:
        return f"{self.proveedor} · {self.nombre_archivo}"

    @property
    def subida_a_mano(self) -> bool:
        return not self.gmail_part_id
