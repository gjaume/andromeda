from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url

PUBLIC_PREFIXES = ("/accounts/", "/healthz", "/static/", "/admin/login/")


class LoginRequiredMiddleware:
    """Todo el backoffice exige sesión, salvo login, healthcheck y estáticos."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(PUBLIC_PREFIXES):
            # El admin tiene su propio login con contraseña para superusuarios.
            login_url = "admin:login" if request.path.startswith("/admin/") else settings.LOGIN_URL
            return redirect_to_login(request.get_full_path(), resolve_url(login_url))
        return self.get_response(request)
