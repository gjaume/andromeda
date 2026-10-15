from datetime import date

from django.core.management.base import BaseCommand

from apps.administracion.nominas import sincronizar_nominas


class Command(BaseCommand):
    help = "Descarga los PDF de nóminas nuevos desde Gmail (etiqueta GMAIL_NOMINAS_LABEL)."

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
        resultado = sincronizar_nominas(dias, desde=desde)
        for error in resultado.errores:
            self.stderr.write(self.style.ERROR(error))
        estilo = self.style.WARNING if resultado.etiqueta_no_encontrada else self.style.SUCCESS
        self.stdout.write(estilo(str(resultado)))
