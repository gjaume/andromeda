from django.conf import settings

from .departments import user_departments
from .navigation import DepartmentNav, tools_for


def navigation(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"nav_departments": []}
    return {
        "nav_departments": [
            DepartmentNav(slug=slug, label=settings.DEPARTMENTS[slug], tools=tools_for(slug))
            for slug in user_departments(user)
        ]
    }
