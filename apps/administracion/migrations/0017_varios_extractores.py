"""Cada proveedor puede tener varios extractores (si cambia el diseño de sus facturas), y cada
factura guarda con cuál se leyó."""

from django.db import migrations, models


def a_lista(apps, schema_editor):
    Proveedor = apps.get_model("administracion", "Proveedor")
    FacturaRecibida = apps.get_model("administracion", "FacturaRecibida")
    for proveedor in Proveedor.objects.exclude(extractor=""):
        proveedor.extractores = [proveedor.extractor]
        proveedor.save(update_fields=["extractores"])
        # Las ya leídas se leyeron con el único extractor que tenía
        FacturaRecibida.objects.filter(
            proveedor=proveedor, extraccion_estado__in=["ok", "revisar"]
        ).update(extractor=proveedor.extractor)


def a_uno(apps, schema_editor):
    Proveedor = apps.get_model("administracion", "Proveedor")
    for proveedor in Proveedor.objects.all():
        proveedor.extractor = (proveedor.extractores or [""])[0]
        proveedor.save(update_fields=["extractor"])


class Migration(migrations.Migration):
    dependencies = [
        ("administracion", "0016_tareas_manuales"),
    ]

    operations = [
        migrations.AddField(
            model_name="facturarecibida",
            name="extractor",
            field=models.CharField(blank=True, max_length=50, verbose_name="formato"),
        ),
        migrations.AddField(
            model_name="proveedor",
            name="extractores",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Extractores que leen las líneas y totales de sus PDF; varios si el "
                "proveedor ha cambiado el diseño de sus facturas. Ninguno = no se extraen.",
                verbose_name="formatos de factura",
            ),
        ),
        migrations.RunPython(a_lista, a_uno),
        migrations.RemoveField(model_name="proveedor", name="extractor"),
    ]
