from django.db import migrations
from django.utils import timezone

NOMBRE = "Conciliar pagos (banco y tarjeta)"
FUNC = "apps.administracion.tasks.conciliar_pagos_drive"


def programar(apps, schema_editor):
    # Cada hora: los extractos se actualizan a mano en Drive de vez en cuando
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.get_or_create(
        name=NOMBRE,
        defaults={
            "func": FUNC,
            "schedule_type": "I",  # Schedule.MINUTES
            "minutes": 60,
            "repeats": -1,
            "next_run": timezone.now(),
        },
    )


def desprogramar(apps, schema_editor):
    apps.get_model("django_q", "Schedule").objects.filter(name=NOMBRE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("administracion", "0010_conciliacion_pagos"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [migrations.RunPython(programar, desprogramar)]
