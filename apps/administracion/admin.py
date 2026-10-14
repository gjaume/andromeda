from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from .models import CorreoFactura, FacturaRecibida, Proveedor


@admin.register(Proveedor)
class ProveedorAdmin(ModelAdmin):
    list_display = ("nombre", "cif", "etiqueta_gmail", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "cif", "etiqueta_gmail")


@display(description="Nombre archivo", ordering="nombre_archivo")
def abrir_archivo(factura: FacturaRecibida) -> str:
    return format_html(
        '<a href="{}" target="_blank" rel="noopener">{}</a>',
        reverse("administracion:factura_archivo", args=[factura.pk]),
        factura.nombre_archivo,
    )


class ConFacturaFilter(admin.SimpleListFilter):
    title = "factura adjunta"
    parameter_name = "con_factura"

    def lookups(self, request, model_admin):
        return [("si", "Con factura"), ("no", "Sin factura")]

    def queryset(self, request, queryset):
        if self.value() in ("si", "no"):
            return queryset.filter(facturas__isnull=self.value() == "no").distinct()
        return queryset


class DescartadoFilter(admin.SimpleListFilter):
    title = "descartado"
    parameter_name = "descartado"

    def lookups(self, request, model_admin):
        return [("si", "Descartados"), ("no", "No descartados")]

    def queryset(self, request, queryset):
        if self.value() in ("si", "no"):
            return queryset.filter(descartado_en__isnull=self.value() == "no")
        return queryset


class FacturaInline(TabularInline):
    model = FacturaRecibida
    fields = (abrir_archivo, "tamano")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(CorreoFactura)
class CorreoFacturaAdmin(ModelAdmin):
    list_display = ("recibido_en", "proveedor", "asunto", "remitente", "descartado_en")
    list_filter = (ConFacturaFilter, DescartadoFilter, "proveedor")
    search_fields = ("asunto", "remitente", "gmail_id")
    readonly_fields = [f.name for f in CorreoFactura._meta.fields]
    inlines = [FacturaInline]
    actions = ["recuperar"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Recuperar descartados (vuelven a «Correos sin factura»)")
    def recuperar(self, request, queryset):
        n = queryset.filter(descartado_en__isnull=False).update(
            descartado_en=None, descartado_por=None
        )
        self.message_user(request, f"{n} correos recuperados.")


@admin.register(FacturaRecibida)
class FacturaRecibidaAdmin(ModelAdmin):
    list_display = ("recibida_en", "proveedor", abrir_archivo, "tamano")
    list_filter = ("proveedor",)
    search_fields = ("nombre_archivo", "correo__asunto")
    readonly_fields = [abrir_archivo, *(f.name for f in FacturaRecibida._meta.fields)]

    def has_add_permission(self, request):
        return False
