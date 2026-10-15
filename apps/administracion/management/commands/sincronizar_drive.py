from django.core.management.base import BaseCommand, CommandError

from apps.administracion.drive import sincronizar_drive
from integrations.drive import DriveError


class Command(BaseCommand):
    help = (
        "Sube a Google Drive las facturas que falten en la carpeta de su año y marca las que "
        "contabilidad ya ha movido a CONTABILIZADO."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--probar",
            action="store_true",
            help="Solo consultar Drive y contar lo que se haría: no sube ni guarda nada.",
        )
        parser.add_argument("--anio", type=int, help="Solo las facturas de ese año.")

    def handle(self, *args, probar, anio, **options):
        try:
            resumen = sincronizar_drive(probar=probar, anio=anio)
        except DriveError as exc:
            raise CommandError(f"{exc}\n{getattr(exc, 'body', '')}".strip()) from exc

        if probar:
            self.stdout.write(self.style.WARNING("Modo prueba: no se ha subido nada."))
            for nombre in resumen.carpetas_creadas:
                self.stdout.write(f"  Crearía la carpeta {nombre}")
            for nombre in resumen.subidas:
                self.stdout.write(f"  Subiría {nombre}")
            for cambio in resumen.renombradas:
                self.stdout.write(f"  Renombraría {cambio}")
        else:
            for nombre in resumen.subidas:
                self.stdout.write(f"  Subida {nombre}")
            for cambio in resumen.renombradas:
                self.stdout.write(f"  Renombrada {cambio}")
        if resumen.fuera_de_sitio:
            self.stdout.write(
                self.style.WARNING("Fuera de sitio (contabilidad debe moverlas a su año):")
            )
            for linea in resumen.fuera_de_sitio:
                self.stdout.write(f"  {linea}")
        if resumen.sin_empresa:
            self.stdout.write(
                self.style.WARNING("Sin empresa identificada (asígnala en el admin):")
            )
            for linea in resumen.sin_empresa:
                self.stdout.write(f"  {linea}")
        for error in resumen.errores:
            self.stdout.write(self.style.ERROR(f"  {error}"))
        self.stdout.write(self.style.SUCCESS(str(resumen)))
