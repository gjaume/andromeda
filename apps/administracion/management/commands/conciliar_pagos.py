from django.core.management.base import BaseCommand, CommandError

from apps.administracion.conciliacion.hojas import HojaError
from apps.administracion.conciliacion.servicio import conciliar_pagos, facturas_a_conciliar
from apps.administracion.models import Empresa
from integrations.drive import DriveError


class Command(BaseCommand):
    help = (
        "Importa de Drive los extractos del banco y de la tarjeta y marca qué facturas están "
        "pagadas y cómo (tarjeta, domiciliación o transferencia)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pendientes", action="store_true", help="Listar las facturas sin pago encontrado."
        )

    def handle(self, *args, pendientes, **options):
        try:
            resumen = conciliar_pagos()
        except (DriveError, HojaError) as exc:
            raise CommandError(str(exc)) from exc
        for aviso in resumen.avisos:
            self.stdout.write(self.style.WARNING(f"  {aviso}"))
        if pendientes:
            for empresa in Empresa.objects.all():
                if not empresa.concilia_pagos:
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f"Sin pago encontrado: {empresa}"))
                for f in (
                    facturas_a_conciliar(empresa)
                    .filter(metodo_pago="")
                    .order_by("proveedor__nombre", "fecha_factura")
                ):
                    self.stdout.write(
                        f"  {f.proveedor} · {f.numero_factura or f.nombre_archivo} · "
                        f"{f.fecha_factura or ''} · {f.total} {f.moneda}"
                    )
        self.stdout.write(self.style.SUCCESS(str(resumen)))
