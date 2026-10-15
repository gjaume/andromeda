from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.administracion.extraccion import Documento, ExtraccionError
from apps.administracion.extraccion.servicio import (
    comprobar,
    extraer_datos,
    leer,
    marcar_todos_los_duplicados,
)
from apps.administracion.models import FacturaRecibida, Proveedor


class Command(BaseCommand):
    help = "Extrae líneas y totales de los PDF de las facturas recibidas."

    def add_arguments(self, parser):
        parser.add_argument("--proveedor", help="Nombre, etiqueta o extractor del proveedor.")
        parser.add_argument("--factura", type=int, action="append", help="Id de factura.")
        parser.add_argument(
            "--todas",
            action="store_true",
            help="Reprocesar todas, no solo las pendientes, con error o sin extractor.",
        )
        parser.add_argument(
            "--probar",
            action="store_true",
            help="Mostrar lo que se extrae sin guardar nada (para desarrollar extractores).",
        )
        parser.add_argument(
            "--duplicados",
            action="store_true",
            help="Solo recalcular qué facturas son duplicadas (mismo proveedor, tipo y nº).",
        )
        parser.add_argument(
            "--texto",
            choices=["plano", "layout"],
            help="Mostrar el texto del PDF tal como lo ve el extractor, sin extraer.",
        )

    def handle(self, *args, proveedor, factura, todas, probar, texto, duplicados, **options):
        if duplicados:
            cambiadas = marcar_todos_los_duplicados()
            n = FacturaRecibida.objects.filter(duplicada_de__isnull=False).count()
            self.stdout.write(self.style.SUCCESS(f"{n} duplicadas ({cambiadas} cambios)"))
            return
        facturas = FacturaRecibida.objects.select_related("proveedor").order_by("recibida_en")
        if proveedor:
            # El filtro por extractor se hace aparte: SQLite no busca dentro de listas JSON
            con_extractor = [p.pk for p in Proveedor.objects.all() if proveedor in p.extractores]
            facturas = facturas.filter(
                Q(proveedor__nombre__iexact=proveedor)
                | Q(proveedor__etiqueta_gmail__iexact=proveedor)
                | Q(proveedor__in=con_extractor)
            )
            if not facturas.exists():
                raise CommandError(f"No hay facturas del proveedor {proveedor!r}")
        if factura:
            facturas = facturas.filter(pk__in=factura)
        if not (todas or probar or texto or factura):
            facturas = facturas.exclude(extraccion_estado=FacturaRecibida.Extraccion.OK)

        if texto:
            return self.mostrar_texto(facturas, texto)
        if probar:
            return self.probar(facturas)

        resumen: dict[str, int] = {}
        for f in facturas:
            extraer_datos(f)
            estado = f.get_extraccion_estado_display()
            resumen[estado] = resumen.get(estado, 0) + 1
            if f.extraccion_estado != FacturaRecibida.Extraccion.OK:
                self.stdout.write(
                    f"[{f.extraccion_estado}] #{f.pk} {f.proveedor} · {f.nombre_archivo}: "
                    f"{f.extraccion_detalle.splitlines()[0] if f.extraccion_detalle else ''}"
                )
        self.stdout.write(self.style.SUCCESS(f"Procesadas {sum(resumen.values())}: {resumen}"))

    def mostrar_texto(self, facturas, modo):
        for f in facturas:
            with f.archivo.open("rb") as fichero:
                doc = Documento(fichero.read(), f.nombre_archivo)
            paginas = doc.paginas_layout if modo == "layout" else doc.paginas
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n#{f.pk} {f.nombre_archivo}"))
            for n, pagina in enumerate(paginas, start=1):
                self.stdout.write(f"--- página {n} ---\n{pagina}")

    def probar(self, facturas):
        bien = 0
        for f in facturas:
            cabecera = f"#{f.pk} {f.proveedor} · {f.nombre_archivo}"
            try:
                clave, datos = leer(f)
            except ExtraccionError as exc:
                self.stdout.write(self.style.ERROR(f"✗ {cabecera}: {exc}"))
                continue
            avisos = comprobar(datos)
            estilo = self.style.WARNING if avisos else self.style.SUCCESS
            bien += not avisos
            self.stdout.write(estilo(f"{'!' if avisos else '✓'} {cabecera}"))
            self.stdout.write(
                f"    [{clave}] {datos.tipo} {datos.numero!r} {datos.fecha} {datos.moneda} "
                f"base={datos.base_imponible} imp={datos.impuestos} total={datos.total}"
            )
            for linea in datos.lineas:
                self.stdout.write(
                    f"      · {linea.descripcion[:70]!r} cant={linea.cantidad} "
                    f"precio={linea.precio_unitario} importe={linea.importe} "
                    f"iva={linea.impuesto_pct}"
                )
            for aviso in avisos:
                self.stdout.write(self.style.WARNING(f"    ! {aviso}"))
        self.stdout.write(f"\n{bien}/{len(facturas)} sin avisos")
