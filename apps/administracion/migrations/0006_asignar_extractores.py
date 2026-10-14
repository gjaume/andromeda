from django.db import migrations

# Etiqueta de Gmail → extractor (apps/administracion/extraccion/extractores/<clave>.py)
EXTRACTORES = {
    "Alquiler Oficina": "alquiler_oficina",
    "Anthropic Claude": "anthropic",
    "Atlassian": "atlassian",
    "BitWarden": "bitwarden",
    "BrowserStack": "browserstack",
    "COOIDI": "cooidi",
    "Caretta Marketing": "caretta",
    "DIGI": "digi",
    "EvenLabs": "elevenlabs",
    "ExperienceBank": "experiencebank",
    "Fundacio BIT": "fundacio_bit",
    "Google Workspace": "google_workspace",
    "Hetzner": "hetzner",
    "HubSpot": "hubspot",
    "Jaume Sabater": "jaume_sabater",
    "Juana Mulet Limpieza": "juana_mulet",
    "OVH": "ovh",
    "PYR Asesores": "pyr_asesores",
    "Plenitude": "plenitude",
    "UpTimeRobot": "uptimerobot",
    "ib-red": "ib_red",
}


def asignar(apps, schema_editor):
    Proveedor = apps.get_model("administracion", "Proveedor")
    for etiqueta, clave in EXTRACTORES.items():
        Proveedor.objects.filter(etiqueta_gmail__iexact=etiqueta, extractor="").update(
            extractor=clave
        )


class Migration(migrations.Migration):
    dependencies = [("administracion", "0005_datos_extraidos_de_facturas")]

    operations = [migrations.RunPython(asignar, migrations.RunPython.noop)]
