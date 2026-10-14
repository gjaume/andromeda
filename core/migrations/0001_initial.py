import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PopeyeApiCall",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("method", models.CharField(max_length=10)),
                ("path", models.CharField(max_length=500)),
                ("request_body", models.JSONField(blank=True, null=True)),
                ("status_code", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_excerpt", models.TextField(blank=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("error", models.CharField(blank=True, max_length=500)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="popeye_api_calls", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "llamada al API de popeye",
                "verbose_name_plural": "llamadas al API de popeye",
                "ordering": ["-created_at"],
            },
        ),
    ]
