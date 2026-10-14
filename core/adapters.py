"""Login exclusivo con Google Workspace y restringido a los dominios corporativos."""

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect


def is_allowed_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    allowed = {d.lower() for d in settings.GOOGLE_WORKSPACE_DOMAINS}
    return domain in allowed


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """Desactiva el registro con usuario y contraseña: solo se entra por Google."""

    def is_open_for_signup(self, request):
        return False


class WorkspaceSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return is_allowed_email(sociallogin.user.email)

    def pre_social_login(self, request, sociallogin):
        email = sociallogin.user.email
        verified = sociallogin.account.extra_data.get("email_verified", True)
        if not (is_allowed_email(email) and verified):
            messages.error(
                request,
                "Esa cuenta de Google no pertenece a AndroNautic. Entra con tu cuenta corporativa.",
            )
            raise ImmediateHttpResponse(redirect(settings.LOGIN_URL))

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.username = (user.email or "").lower()
        return user
