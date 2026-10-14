from django.db import migrations
from django.utils import timezone

NOMBRE = "Sincronizar facturas de Gmail"
FUNC = "apps.administracion.tasks.sincronizar_facturas_gmail"


def programar(apps, schema_editor):
    # Cada 4 horas. La frecuencia se cambia desde el admin: Django Q → Tareas programadas.
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        name=NOMBRE,
        defaults={
            "func": FUNC,
            "schedule_type": "I",  # Schedule.MINUTES
            "minutes": 240,
            "repeats": -1,
            "next_run": timezone.now(),
        },
    )


def desprogramar(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name=NOMBRE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("administracion", "0001_initial"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(programar, desprogramar)]
