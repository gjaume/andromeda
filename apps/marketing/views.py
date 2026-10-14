from django.views.generic import TemplateView

from core.departments import DepartmentRequiredMixin


class IndexView(DepartmentRequiredMixin, TemplateView):
    department = "marketing"
    template_name = "marketing/index.html"
