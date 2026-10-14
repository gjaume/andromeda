from django.contrib import admin
from django.urls import include, path

from core.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("comercial/", include("apps.comercial.urls")),
    path("administracion/", include("apps.administracion.urls")),
    path("marketing/", include("apps.marketing.urls")),
    path("", include("core.urls")),
]
