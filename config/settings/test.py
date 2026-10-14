from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
GOOGLE_WORKSPACE_DOMAINS = ["andronautic.com"]
POPEYE_API = {
    "BASE_URL": "https://popeye.test/ws",
    "TOKEN": "test-token",
    "AUTH_HEADER": "Authorization",
    "AUTH_SCHEME": "Bearer",
    "TIMEOUT": 2.0,
    "MAX_RETRIES": 3,
}
GMAIL = {
    "MAILBOX": "admin@andronautic.com",
    "SERVICE_ACCOUNT_JSON": "",
    "INVOICES_LABEL": "Gastos",
    "SYNC_DAYS": 30,
}
Q_CLUSTER = {"name": "test", "orm": "default", "sync": True, "timeout": 60, "retry": 120}
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m]  # noqa: F405
