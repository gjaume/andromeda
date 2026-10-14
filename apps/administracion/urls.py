from django.urls import path

from . import views

app_name = "administracion"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("facturas/", views.FacturaListView.as_view(), name="facturas"),
    path(
        "facturas/sin-factura/",
        views.CorreoSinFacturaListView.as_view(),
        name="correos_sin_factura",
    ),
    path(
        "facturas/correos/<int:pk>/subir/",
        views.SubirFacturasView.as_view(),
        name="subir_facturas",
    ),
    path(
        "facturas/correos/<int:pk>/descartar/",
        views.DescartarCorreoView.as_view(),
        name="descartar_correo",
    ),
    path(
        "facturas/sincronizar/",
        views.SincronizarFacturasView.as_view(),
        name="facturas_sincronizar",
    ),
    path("facturas/<int:pk>/archivo/", views.FacturaArchivoView.as_view(), name="factura_archivo"),
    path("proveedores/", views.ProveedorListView.as_view(), name="proveedores"),
    path("proveedores/nuevo/", views.ProveedorCreateView.as_view(), name="proveedor_nuevo"),
    path("proveedores/<int:pk>/", views.ProveedorUpdateView.as_view(), name="proveedor_editar"),
]
