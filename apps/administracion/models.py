from pathlib import PurePath

from django.conf import settings
from django.db import models
from django.db.models.functions import Coalesce, TruncDate
from django.utils.text import slugify


def opciones_extractores():
    from .extraccion import registro

    return [(clave, extractor.nombre) for clave, extractor in sorted(registro.items())]


class Empresa(models.Model):
    """Empresa del grupo a la que va emitida una factura (comparten el buzón de facturas)."""

    nombre = models.CharField(max_length=200, unique=True)
    cif = models.CharField("CIF / NIF", max_length=20, unique=True)
    alias = models.TextField(
        blank=True,
        help_text="Otras formas en que aparece su nombre en las facturas, una por línea. "
        "Se distinguen por el CIF y, si no aparece, por el nombre o estos alias.",
    )
    carpeta_drive = models.CharField(
        "carpeta en Drive",
        max_length=300,
        blank=True,
        help_text="Ruta desde la unidad compartida, separada por /, p. ej. "
        "Administración/ANDROMEDA SOLUTIONS/Facturas recibidas AS. Dentro van las carpetas de "
        "cada año. Vacío = no se suben a Drive.",
    )
    # --- Conciliación de pagos (apps/administracion/conciliacion) ---
    extracto_banco = models.CharField(
        "extracto del banco",
        max_length=300,
        blank=True,
        help_text="Hoja de cálculo en Drive con los movimientos de la cuenta, p. ej. "
        "Administración/ANDROMEDA SOLUTIONS/Extracto anual Banco Sabadell Andromeda "
        "Solutions.xlsx",
    )
    extracto_banco_pestana = models.CharField(
        "pestaña del extracto", max_length=50, blank=True, help_text="p. ej. SABADELL"
    )
    extracto_tarjeta = models.CharField(
        "extracto de la tarjeta",
        max_length=300,
        blank=True,
        help_text="Hoja de cálculo en Drive con una pestaña por mes (ENE…DIC). {anio} se "
        "sustituye por el año, p. ej. Administración/ANDROMEDA SOLUTIONS/VISA/{anio}/Tarjeta de "
        "crédito.xlsx",
    )

    class Meta:
        ordering = ["nombre"]
        verbose_name = "empresa"
        verbose_name_plural = "empresas"

    def __str__(self) -> str:
        return self.nombre

    @property
    def concilia_pagos(self) -> bool:
        return bool(self.extracto_banco or self.extracto_tarjeta)

    @property
    def nombres(self) -> list[str]:
        return [self.nombre, *filter(None, (a.strip() for a in self.alias.splitlines()))]


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
    extractor = models.CharField(
        "formato de factura",
        max_length=50,
        blank=True,
        choices=opciones_extractores,
        help_text="Extractor que lee las líneas y totales de sus PDF. Vacío = no se extraen.",
    )
    textos_pago = models.TextField(
        "textos del pago",
        blank=True,
        help_text="Cómo aparece el proveedor en el extracto del banco o de la tarjeta, uno por "
        "línea (p. ej. HETZNER, PUIGSERVER Y ROMAGUERA). Sirve para conciliar sus facturas con "
        "los pagos; sin textos solo se concilia si el importe es inequívoco.",
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
    def lista_textos_pago(self) -> list[str]:
        return [t.strip() for t in self.textos_pago.splitlines() if t.strip()]

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


class MetodoPago(models.TextChoices):
    TARJETA = "tarjeta", "Tarjeta"
    DOMICILIACION = "domiciliacion", "Domiciliación"
    TRANSFERENCIA = "transferencia", "Transferencia"


class MovimientoPago(models.Model):
    """Un cargo o abono del extracto del banco o de la tarjeta (se importan de Drive)."""

    class Origen(models.TextChoices):
        BANCO = "banco", "Banco"
        TARJETA = "tarjeta", "Tarjeta"

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="movimientos")
    origen = models.CharField(max_length=10, choices=Origen.choices)
    # Identifica el movimiento entre importaciones: origen, fecha, concepto, importe y nº de orden
    # entre los iguales. Así las conciliaciones sobreviven a que se reordene la hoja.
    clave = models.CharField(max_length=64)
    fecha = models.DateField(db_index=True)
    concepto = models.CharField(max_length=500)
    # Positivo = sale dinero (un pago); negativo = entra (una devolución, un abono)
    importe = models.DecimalField(max_digits=12, decimal_places=2, help_text="En euros.")
    importe_original = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Cargos de tarjeta en otra moneda: importe en esa moneda.",
    )
    moneda_original = models.CharField(max_length=3, blank=True)
    metodo = models.CharField("método", max_length=15, choices=MetodoPago.choices)
    hoja = models.CharField(max_length=300, help_text="Fichero, pestaña y fila de origen.")
    importado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fecha", "id"]
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos (banco y tarjeta)"
        constraints = [
            models.UniqueConstraint(fields=["empresa", "clave"], name="movimiento_unico")
        ]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y} {self.concepto} {self.importe} €"


def factura_upload_to(instance: "FacturaRecibida", filename: str) -> str:
    fecha = instance.correo.recibido_en
    nombre = PurePath(filename)
    limpio = f"{slugify(nombre.stem)[:80] or 'factura'}{nombre.suffix.lower()}"
    return f"facturas/{slugify(instance.proveedor.nombre)}/{fecha:%Y/%m}/{limpio}"


class FacturaRecibidaQuerySet(models.QuerySet):
    def sin_duplicados(self):
        return self.filter(duplicada_de__isnull=True)

    def con_fecha(self, criterio: str = "factura"):
        """Anota `fecha`, la que manda en la vista por meses según el criterio:

        - "factura": la fecha de emisión leída del PDF y, si aún no se tiene, la del correo.
        - "correo": el día en que llegó el correo (hora de Madrid).
        """
        del_correo = TruncDate("recibida_en")
        return self.annotate(
            fecha=del_correo if criterio == "correo" else Coalesce("fecha_factura", del_correo)
        )


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

    # --- Datos extraídos del PDF (apps/administracion/extraccion) ---
    class Tipo(models.TextChoices):
        FACTURA = "factura", "Factura"
        ABONO = "abono", "Factura rectificativa / abono"
        RECIBO = "recibo", "Recibo de pago"
        ANEXO = "anexo", "Anexo (no es factura)"

    # Ni los recibos (justifican una factura ya contada) ni los anexos son gasto
    TIPOS_NO_GASTO = (Tipo.RECIBO, Tipo.ANEXO)

    class Extraccion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        OK = "ok", "Extraída"
        REVISAR = "revisar", "Extraída, revisar"  # los importes no cuadran
        ERROR = "error", "Error al extraer"
        SIN_EXTRACTOR = "sin_extractor", "Sin extractor"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, blank=True)
    empresa = models.ForeignKey(
        Empresa,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="facturas",
        help_text="A quién va emitida. Se detecta en el PDF por el CIF o el nombre.",
    )
    numero_factura = models.CharField("nº de factura", max_length=100, blank=True)
    fecha_factura = models.DateField(null=True, blank=True)
    moneda = models.CharField(max_length=3, blank=True, help_text="Código ISO 4217: EUR, USD…")
    base_imponible = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    impuestos = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    extraccion_estado = models.CharField(
        "extracción",
        max_length=15,
        choices=Extraccion.choices,
        default=Extraccion.PENDIENTE,
        db_index=True,
    )
    extraccion_detalle = models.TextField("detalle de la extracción", blank=True)
    extraida_en = models.DateTimeField(null=True, blank=True)
    # Mismo proveedor, tipo y nº de factura que otra recibida antes (p. ej. el PDF reenviado en
    # un recordatorio): no se cuenta para no sumar dos veces el mismo gasto.
    duplicada_de = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="duplicados",
        help_text="Factura original de la que esta es una copia.",
    )

    # --- Copia en Google Drive para contabilidad (apps/administracion/drive.py) ---
    drive_id = models.CharField("id en Drive", max_length=100, blank=True)
    # Nombre con el que la subimos: si sigue igual en Drive, se puede corregir (p. ej. cuando se
    # subió antes de leer la fecha del PDF); si contabilidad lo cambió, no se toca
    drive_nombre = models.CharField("nombre en Drive", max_length=255, blank=True)
    # MD5 del PDF: así lo identifica Drive (md5Checksum). Se calcula la primera vez que hace falta.
    md5 = models.CharField("MD5", max_length=32, blank=True)
    subida_a_drive_en = models.DateTimeField("subida a Drive", null=True, blank=True)
    # Contabilidad la ha movido a la carpeta CONTABILIZADO de su año
    contabilizada_en = models.DateTimeField("contabilizada", null=True, blank=True)

    # --- Conciliación con los pagos (apps/administracion/conciliacion) ---
    pago = models.ForeignKey(
        MovimientoPago,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="facturas",
        help_text="Cargo del banco o de la tarjeta con el que se pagó.",
    )
    metodo_pago = models.CharField(
        "pagada por", max_length=15, choices=MetodoPago.choices, blank=True
    )
    pagada_el = models.DateField(null=True, blank=True)
    # Marcada a mano en el admin: la conciliación automática no la toca
    pago_manual = models.BooleanField(
        "pago marcado a mano",
        default=False,
        help_text="Si está marcado, la conciliación automática respeta lo que se haya puesto.",
    )

    objects = FacturaRecibidaQuerySet.as_manager()

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
    def pagada(self) -> bool:
        return bool(self.metodo_pago)

    @property
    def subida_a_mano(self) -> bool:
        return not self.gmail_part_id

    @property
    def drive_url(self) -> str:
        return f"https://drive.google.com/file/d/{self.drive_id}/view" if self.drive_id else ""


class LineaFactura(models.Model):
    factura = models.ForeignKey(FacturaRecibida, on_delete=models.CASCADE, related_name="lineas")
    orden = models.PositiveSmallIntegerField(default=0)
    descripcion = models.TextField()
    cantidad = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    precio_unitario = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    importe = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="Importe de la línea sin impuestos."
    )
    impuesto_pct = models.DecimalField(
        "% impuesto", max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["factura", "orden"]
        verbose_name = "línea de factura"
        verbose_name_plural = "líneas de factura"

    def __str__(self) -> str:
        return self.descripcion[:80]


# --- Nóminas --------------------------------------------------------------------------------


class CorreoNomina(models.Model):
    """Correo de la etiqueta de nóminas ya revisado, para no volver a descargarlo."""

    gmail_id = models.CharField(max_length=64, unique=True)
    asunto = models.CharField(max_length=500, blank=True)
    remitente = models.CharField(max_length=320, blank=True)
    recibido_en = models.DateTimeField(db_index=True)
    procesado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recibido_en"]
        verbose_name = "correo de nóminas"
        verbose_name_plural = "correos de nóminas"

    def __str__(self) -> str:
        return self.asunto or self.gmail_id

    @property
    def gmail_url(self) -> str:
        return f"https://mail.google.com/mail/u/{settings.GMAIL['MAILBOX']}/#all/{self.gmail_id}"


def nomina_upload_to(instance: "Nomina", filename: str) -> str:
    nombre = PurePath(filename)
    limpio = f"{slugify(nombre.stem)[:80] or 'nominas'}{nombre.suffix.lower()}"
    empresa = slugify(instance.empresa.nombre) if instance.empresa else "sin-empresa"
    return f"nominas/{empresa}/{instance.periodo:%Y/%m}/{limpio}"


class Nomina(models.Model):
    """PDF de nóminas de un mes: el de todos los empleados, el resumen o, si el correo no trae
    el de todos, el de cada empleado."""

    class Tipo(models.TextChoices):
        NOMINAS = "nominas", "Nóminas"
        RESUMEN = "resumen", "Resumen"
        EMPLEADO = "empleado", "Nómina de un empleado"

    correo = models.ForeignKey(CorreoNomina, on_delete=models.CASCADE, related_name="nominas")
    empresa = models.ForeignKey(
        Empresa, null=True, blank=True, on_delete=models.PROTECT, related_name="nominas"
    )
    periodo = models.DateField(help_text="Mes de las nóminas (día 1).")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    gmail_part_id = models.CharField(max_length=32, blank=True)
    nombre_archivo = models.CharField(max_length=255)
    archivo = models.FileField(upload_to=nomina_upload_to, max_length=300)
    tamano = models.PositiveIntegerField("tamaño", default=0)
    recibida_en = models.DateTimeField(db_index=True)
    # La gestoría a veces manda correcciones: el último PDF recibido del mismo documento (mismo
    # mes, empresa, tipo y empleado) es el bueno, y los anteriores apuntan a él
    sustituida_por = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="versiones_anteriores",
        help_text="Versión posterior del mismo documento, que es la buena.",
    )

    class Meta:
        ordering = ["-periodo", "tipo", "-recibida_en"]
        verbose_name = "nómina"
        verbose_name_plural = "nóminas"
        constraints = [
            models.UniqueConstraint(
                fields=["correo", "gmail_part_id"],
                condition=~models.Q(gmail_part_id=""),
                name="nomina_unica_por_adjunto",
            )
        ]

    def __str__(self) -> str:
        return self.nombre_archivo
