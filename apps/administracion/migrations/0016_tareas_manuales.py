"""Las descargas de Gmail (facturas y nóminas) y la subida a Drive pasan a ser solo manuales,
con los botones de cada pantalla. La conciliación de pagos sigue programada."""

from django.db import migrations
from django.utils import timezone

TAREAS = {
    "Sincronizar facturas de Gmail": ("apps.administracion.tasks.sincronizar_facturas_gmail", 240),
    "Sincronizar nóminas de Gmail": ("apps.administracion.tasks.sincronizar_nominas_gmail", 240),
    "Sincronizar facturas con Drive": ("apps.administracion.tasks.sincronizar_facturas_drive", 60),
}


def desprogramar(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name__in=TAREAS).delete()


def programar(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    for nombre, (func, minutos) in TAREAS.items():
        Schedule.objects.get_or_create(
            name=nombre,
            defaults={
                "func": func,
                "schedule_type": "I",  # Schedule.MINUTES
                "minutes": minutos,
                "repeats": -1,
                "next_run": timezone.now(),
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("administracion", "0015_versiones_de_nominas"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(desprogramar, programar)]
