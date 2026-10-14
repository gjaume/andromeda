from datetime import date

from django.core.management.base import BaseCommand

from apps.administracion.facturas import sincronizar_facturas


class Command(BaseCommand):
    help = "Descarga las facturas nuevas de los proveedores desde Gmail."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help="Buscar correos de los últimos N días (0 = todo el histórico). "
            "Por defecto, GMAIL_SYNC_DAYS.",
        )
        parser.add_argument(
            "--desde",
            type=date.fromisoformat,
            default=None,
            help="Buscar correos desde esta fecha (AAAA-MM-DD). Tiene prioridad sobre --dias.",
        )

    def handle(self, *args, dias, desde, **options):
        resultado = sincronizar_facturas(dias, desde=desde)
        for etiqueta in resultado.etiquetas_no_encontradas:
            self.stderr.write(self.style.WARNING(f"No existe la etiqueta {etiqueta} en Gmail"))
        for error in resultado.errores:
            self.stderr.write(self.style.ERROR(error))
        self.stdout.write(self.style.SUCCESS(str(resultado)))
