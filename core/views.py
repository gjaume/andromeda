from django.db import connection
from django.http import JsonResponse
from django.views.generic import TemplateView


def healthz(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


class HomeView(TemplateView):
    template_name = "core/home.html"
