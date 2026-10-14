from django.views.generic import TemplateView

from core.departments import DepartmentRequiredMixin


class IndexView(DepartmentRequiredMixin, TemplateView):
    department = "comercial"
    template_name = "comercial/index.html"
