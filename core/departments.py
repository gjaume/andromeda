"""Departamentos = Groups de Django. Cada usuario ve las herramientas de sus grupos."""

from django.conf import settings
from django.contrib.auth.mixins import AccessMixin


def group_name(slug: str) -> str:
    return settings.DEPARTMENTS[slug]


def user_departments(user) -> list[str]:
    if not user.is_authenticated:
        return []
    if user.is_superuser:
        return list(settings.DEPARTMENTS)
    names = set(user.groups.values_list("name", flat=True))
    return [slug for slug, name in settings.DEPARTMENTS.items() if name in names]


def user_in_department(user, slug: str) -> bool:
    return slug in user_departments(user)


class DepartmentRequiredMixin(AccessMixin):
    """Uso: class MiVista(DepartmentRequiredMixin, TemplateView): department = "comercial"."""

    department: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not user_in_department(request.user, self.department):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)
