import logging
import mimetypes
import re
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)
from django.views.generic.detail import SingleObjectMixin
from django_q.models import Task
from django_q.tasks import async_task

from core.departments import DepartmentRequiredMixin
from integrations import gmail

from .extraccion.servicio import extraer_datos
from .facturas import subir_facturas
from .forms import ProveedorForm, SubirFacturasForm
from .models import CorreoFactura, FacturaRecibida, Proveedor

logger = logging.getLogger(__name__)

TAREA_SINCRONIZAR = "apps.administracion.tasks.sincronizar_facturas_gmail"


class IndexView(DepartmentRequiredMixin, TemplateView):
    department = "administracion"
    template_name = "administracion/index.html"


# --- Facturas recibidas ---------------------------------------------------------------------


class FacturasMixin(DepartmentRequiredMixin):
    """Filtro por proveedor y cabecera común de las pestañas de facturas."""

    department = "administracion"
    paginate_by = 50

    def proveedor_filtrado(self) -> Proveedor | None:
        proveedor_id = self.request.GET.get("proveedor", "")
        return Proveedor.objects.filter(pk=proveedor_id).first() if proveedor_id.isdigit() else None

    def filtrar(self, queryset):
        self.proveedor = self.proveedor_filtrado()
        return queryset.filter(proveedor=self.proveedor) if self.proveedor else queryset

    def get_context_data(self, **kwargs):
        facturas = self.filtrar(FacturaRecibida.objects.all())
        sin_factura = self.filtrar(CorreoFactura.objects.pendientes())
        return super().get_context_data(
            proveedores=Proveedor.objects.all(),
            proveedor_actual=self.proveedor,
            total_facturas=facturas.count(),
            total_sin_factura=sin_factura.count(),
            ultima_sincronizacion=Task.objects.filter(func=TAREA_SINCRONIZAR)
            .order_by("-stopped")
            .first(),
            gmail_configurado=gmail.is_configured(),
            **kwargs,
        )


class FacturaListView(FacturasMixin, ListView):
    template_name = "administracion/facturas.html"
    context_object_name = "facturas"

    def get_queryset(self):
        facturas = FacturaRecibida.objects.select_related(
            "proveedor", "correo", "subida_por", "duplicada_de"
        )
        # ?mes=AAAA-MM, al pulsar una casilla de la vista por meses
        self.mes = None
        if match := re.fullmatch(r"(\d{4})-(\d{2})", self.request.GET.get("mes", "")):
            anio, mes = int(match[1]), int(match[2])
            if 1 <= mes <= 12:
                self.mes = date(anio, mes, 1)
                facturas = facturas.filter(recibida_en__year=anio, recibida_en__month=mes)
        return self.filtrar(facturas)

    def get_context_data(self, **kwargs):
        return super().get_context_data(mes_actual=self.mes, **kwargs)


MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


class Importes:
    """Suma de importes por moneda, más las facturas que no tienen importe (no se pudo leer)."""

    def __init__(self) -> None:
        self.por_moneda: dict[str, Decimal] = {}
        self.facturas = 0
        self.sin_importe = 0

    def sumar(self, moneda: str, importe: Decimal | None, facturas: int = 1) -> None:
        self.facturas += facturas
        if importe is None:
            self.sin_importe += facturas
        else:
            self.por_moneda[moneda] = self.por_moneda.get(moneda, Decimal(0)) + importe

    def __iadd__(self, otro: "Importes") -> "Importes":
        for moneda, importe in otro.por_moneda.items():
            self.sumar(moneda, importe, facturas=0)
        self.facturas += otro.facturas
        self.sin_importe += otro.sin_importe
        return self

    @property
    def lista(self) -> list[tuple[str, Decimal]]:
        """[(moneda, importe)], el euro primero."""
        return sorted(self.por_moneda.items(), key=lambda par: (par[0] != "EUR", par[0]))


class FacturasPorMesView(FacturasMixin, TemplateView):
    """Proveedores × meses de un año: qué facturas tenemos, cuáles faltan y cuánto suman.

    Cuentan las facturas y los abonos (estos en negativo). No cuentan los recibos de pago, que
    justifican una factura ya contada, ni las duplicadas.
    """

    template_name = "administracion/facturas_por_mes.html"
    IMPORTES = {"total": "Total (con impuestos)", "base": "Base imponible"}

    def get_context_data(self, **kwargs):
        hoy = timezone.localdate()
        anios = {d.year for d in FacturaRecibida.objects.datetimes("recibida_en", "year")}
        anios.add(hoy.year)
        anio_param = self.request.GET.get("anio", "")
        anio = int(anio_param) if anio_param.isdigit() and int(anio_param) in anios else hoy.year
        importe = self.request.GET.get("importe", "")
        importe = importe if importe in self.IMPORTES else "total"
        campo = "base_imponible" if importe == "base" else "total"

        celdas: dict[tuple[int, int], Importes] = {}
        for fila in (
            FacturaRecibida.objects.sin_duplicados()
            .filter(recibida_en__year=anio)
            .exclude(tipo=FacturaRecibida.Tipo.RECIBO)
            .annotate(mes=ExtractMonth("recibida_en"))
            .values_list("proveedor_id", "mes", "moneda", campo)
        ):
            proveedor_id, mes, moneda, valor = fila
            celdas.setdefault((proveedor_id, mes), Importes()).sumar(moneda, valor)

        # Proveedores activos, más los inactivos que tuvieron facturas ese año
        proveedores = Proveedor.objects.filter(
            Q(activo=True) | Q(facturas__recibida_en__year=anio)
        ).distinct()
        total_meses = [Importes() for _ in range(12)]
        total_anio = Importes()
        filas = []
        for proveedor in proveedores:
            total_fila = Importes()
            meses = []
            for numero in range(1, 13):
                celda = celdas.get((proveedor.pk, numero), Importes())
                total_fila += celda
                total_meses[numero - 1] += celda
                meses.append(
                    {
                        "numero": numero,
                        "nombre": MESES[numero - 1],
                        "importes": celda,
                        "facturas": celda.facturas,
                        "futuro": (anio, numero) > (hoy.year, hoy.month),
                    }
                )
            total_anio += total_fila
            filas.append({"proveedor": proveedor, "meses": meses, "total": total_fila})
        return super().get_context_data(
            anio=anio,
            anios=sorted(anios, reverse=True),
            importe=importe,
            importes=self.IMPORTES,
            meses=MESES,
            mes_en_curso=hoy.month if anio == hoy.year else None,
            filas=filas,
            total_meses=total_meses,
            total_anio=total_anio,
            ocultar_filtro_proveedor=True,
            **kwargs,
        )


class CorreoSinFacturaListView(FacturasMixin, ListView):
    """Correos de proveedores sin PDF adjunto: la factura hay que bajarla a mano."""

    template_name = "administracion/correos_sin_factura.html"
    context_object_name = "correos"

    def get_queryset(self):
        correos = CorreoFactura.objects.pendientes().select_related("proveedor")
        return self.filtrar(correos)


class DescartarCorreoView(DepartmentRequiredMixin, View):
    """Saca de "Correos sin factura" un correo que no trae factura (p. ej. una respuesta)."""

    department = "administracion"

    def post(self, request, pk):
        correo = get_object_or_404(CorreoFactura, pk=pk)
        correo.descartado_en = timezone.now()
        correo.descartado_por = request.user
        correo.save(update_fields=["descartado_en", "descartado_por"])
        messages.success(
            request,
            f"Descartado «{correo.asunto or correo.gmail_id}». "
            "Se puede recuperar desde el admin (Correos de facturas → Descartados).",
        )
        destino = reverse("administracion:correos_sin_factura")
        if proveedor := request.POST.get("proveedor", ""):
            destino += f"?proveedor={proveedor}" if proveedor.isdigit() else ""
        return redirect(destino)


class SubirFacturasView(DepartmentRequiredMixin, FormView):
    """Para correos sin PDF: se sube la factura descargada a mano del portal del proveedor."""

    department = "administracion"
    form_class = SubirFacturasForm
    template_name = "administracion/subir_facturas.html"

    def dispatch(self, request, *args, **kwargs):
        self.correo = get_object_or_404(
            CorreoFactura.objects.select_related("proveedor"), pk=kwargs["pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(correo=self.correo, **kwargs)

    def form_valid(self, form):
        facturas = subir_facturas(self.correo, form.cleaned_data["archivos"], self.request.user)
        nombres = ", ".join(f.nombre_archivo for f in facturas)
        messages.success(self.request, f"Factura añadida a {self.correo.proveedor}: {nombres}.")
        return redirect("administracion:correos_sin_factura")


class SincronizarFacturasView(DepartmentRequiredMixin, View):
    department = "administracion"

    def post(self, request):
        if not gmail.is_configured():
            messages.error(request, "Gmail no está configurado: falta GMAIL_SERVICE_ACCOUNT_JSON.")
        else:
            async_task(TAREA_SINCRONIZAR, task_name="Sincronizar facturas (manual)")
            messages.success(
                request,
                "Buscando facturas nuevas en Gmail. Recarga la página en un minuto para verlas.",
            )
        return redirect("administracion:facturas")


class FacturaDetalleView(DepartmentRequiredMixin, DetailView):
    department = "administracion"
    template_name = "administracion/factura_detalle.html"
    context_object_name = "factura"
    queryset = FacturaRecibida.objects.select_related(
        "proveedor", "correo", "subida_por", "duplicada_de__correo"
    )

    def get_context_data(self, **kwargs):
        lineas = list(self.object.lineas.all())
        suma = sum((linea.importe for linea in lineas), Decimal(0))
        return super().get_context_data(
            lineas=lineas,
            suma_lineas=suma,
            duplicados=self.object.duplicados.select_related("correo").order_by("recibida_en"),
            **kwargs,
        )


class FacturaExtraerView(DepartmentRequiredMixin, View):
    """Vuelve a leer el PDF, p. ej. tras corregir un extractor o asignárselo al proveedor."""

    department = "administracion"

    def post(self, request, pk):
        factura = extraer_datos(get_object_or_404(FacturaRecibida, pk=pk))
        nivel = messages.SUCCESS if factura.extraccion_estado == "ok" else messages.WARNING
        messages.add_message(
            request, nivel, f"PDF leído de nuevo: {factura.get_extraccion_estado_display()}."
        )
        return redirect("administracion:factura_detalle", pk=pk)


class FacturaArchivoView(DepartmentRequiredMixin, SingleObjectMixin, View):
    """Sirve el PDF a través de la app para que solo lo vea el departamento."""

    department = "administracion"
    model = FacturaRecibida

    def get(self, request, *args, **kwargs):
        factura = self.get_object()
        content_type = mimetypes.guess_type(factura.nombre_archivo)[0]
        return FileResponse(
            factura.archivo.open("rb"),
            filename=factura.nombre_archivo,
            content_type=content_type or "application/octet-stream",
        )


# --- Proveedores ----------------------------------------------------------------------------


class ProveedorListView(DepartmentRequiredMixin, ListView):
    department = "administracion"
    template_name = "administracion/proveedores.html"
    context_object_name = "proveedores"
    queryset = Proveedor.objects.annotate(num_facturas=Count("facturas"))


class ProveedorFormMixin(DepartmentRequiredMixin, SuccessMessageMixin):
    department = "administracion"
    model = Proveedor
    form_class = ProveedorForm
    template_name = "administracion/proveedor_form.html"
    success_url = reverse_lazy("administracion:proveedores")

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            etiquetas_gmail=etiquetas_de_gastos(),
            etiqueta_padre=settings.GMAIL["INVOICES_LABEL"],
            **kwargs,
        )


class ProveedorCreateView(ProveedorFormMixin, CreateView):
    success_message = "Proveedor %(nombre)s creado."


class ProveedorUpdateView(ProveedorFormMixin, UpdateView):
    success_message = "Proveedor %(nombre)s guardado."


def etiquetas_de_gastos() -> list[str]:
    """Subetiquetas de "Gastos" en Gmail, para sugerirlas en el formulario de proveedor."""
    if not gmail.is_configured():
        return []
    padre = settings.GMAIL["INVOICES_LABEL"] + "/"
    etiquetas = cache.get("gmail:etiquetas")
    if etiquetas is None:
        try:
            with gmail.get_client() as client:
                etiquetas = sorted(client.labels())
        except gmail.GmailError:
            logger.exception("No se pudieron leer las etiquetas de Gmail")
            return []
        cache.set("gmail:etiquetas", etiquetas, 600)
    return [e[len(padre) :] for e in etiquetas if e.startswith(padre)]
