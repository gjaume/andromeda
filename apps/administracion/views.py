import logging
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db.models import Count
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView
from django.views.generic.detail import SingleObjectMixin
from django_q.models import Task
from django_q.tasks import async_task

from core.departments import DepartmentRequiredMixin
from integrations import gmail

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
        sin_factura = self.filtrar(CorreoFactura.objects.filter(facturas__isnull=True))
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
        facturas = FacturaRecibida.objects.select_related("proveedor", "correo", "subida_por")
        return self.filtrar(facturas)


class CorreoSinFacturaListView(FacturasMixin, ListView):
    """Correos de proveedores sin PDF adjunto: la factura hay que bajarla a mano."""

    template_name = "administracion/correos_sin_factura.html"
    context_object_name = "correos"

    def get_queryset(self):
        correos = CorreoFactura.objects.filter(facturas__isnull=True).select_related("proveedor")
        return self.filtrar(correos)


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
