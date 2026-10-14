from django.urls import reverse

from core.adapters import is_allowed_email


def test_healthz_is_public(client, db):
    assert client.get("/healthz").status_code == 200


def test_anonymous_is_redirected_to_login(client, db):
    response = client.get(reverse("core:home"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


def test_login_page_is_public(client, db):
    response = client.get(reverse("account_login"))
    assert response.status_code == 200
    assert "Entrar con Google" in response.content.decode()


def test_only_workspace_domain_is_allowed():
    assert is_allowed_email("ana@andronautic.com")
    assert is_allowed_email("Ana@AndroNautic.com")
    assert not is_allowed_email("ana@gmail.com")
    assert not is_allowed_email("ana@andronautic.com.evil.io")
    assert not is_allowed_email(None)


def test_department_views_require_membership(client, make_user):
    client.force_login(make_user(departments=["Comercial"]))
    assert client.get(reverse("comercial:index")).status_code == 200
    assert client.get(reverse("marketing:index")).status_code == 403


def test_navigation_shows_only_user_departments(client, make_user):
    client.force_login(make_user(departments=["Marketing"]))
    html = client.get(reverse("core:home")).content.decode()
    assert "Inicio de Marketing" in html
    assert "Inicio de Comercial" not in html


def test_superuser_sees_every_department(client, make_user):
    client.force_login(make_user(is_superuser=True, is_staff=True))
    html = client.get(reverse("core:home")).content.decode()
    for label in ("Comercial", "Administración", "Marketing"):
        assert f"Inicio de {label}" in html
