from django.views.generic import TemplateView

from core.departments import DepartmentRequiredMixin


class IndexView(DepartmentRequiredMixin, TemplateView):
    department = "administracion"
    template_name = "administracion/index.html"
