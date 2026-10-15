"""Configuración común. Todo lo que cambia entre entornos llega por variables de entorno."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

INSTALLED_APPS = [
    # Unfold debe ir antes de django.contrib.admin
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # Terceros
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "django_q",
    # Propias
    "core",
    "apps.comercial",
    "apps.administracion",
    "apps.marketing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "core.middleware.LoginRequiredMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
SITE_ID = 1

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.navigation",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Ficheros: Cloudflare R2 si está configurado, disco local si no -------------------------
R2_BUCKET = env("R2_BUCKET", default="")
if R2_BUCKET:
    _default_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": R2_BUCKET,
            "endpoint_url": env("R2_ENDPOINT_URL"),
            "access_key": env("R2_ACCESS_KEY_ID"),
            "secret_key": env("R2_SECRET_ACCESS_KEY"),
            "region_name": "auto",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }
else:
    _default_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _default_storage,
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Autenticación: solo Google Workspace ---------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

GOOGLE_WORKSPACE_DOMAINS = env.list("GOOGLE_WORKSPACE_DOMAINS", default=[])

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "core:home"
ACCOUNT_LOGOUT_REDIRECT_URL = "account_login"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_ADAPTER = "core.adapters.NoSignupAccountAdapter"
SOCIALACCOUNT_ADAPTER = "core.adapters.WorkspaceSocialAccountAdapter"
SOCIALACCOUNT_ONLY = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

_google_auth_params = {"prompt": "select_account"}
if len(GOOGLE_WORKSPACE_DOMAINS) == 1:
    # Pista para que Google muestre solo cuentas del dominio. La validación real está en el adapter.
    _google_auth_params["hd"] = GOOGLE_WORKSPACE_DOMAINS[0]

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": env("GOOGLE_OAUTH_CLIENT_ID", default=""),
            "secret": env("GOOGLE_OAUTH_CLIENT_SECRET", default=""),
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": _google_auth_params,
        "OAUTH_PKCE_ENABLED": True,
    }
}

# --- Tareas en segundo plano (django-q2 sobre la propia base de datos) ----------------------
Q_CLUSTER = {
    "name": "andronautic-internal",
    "orm": "default",
    "workers": env.int("Q_WORKERS", default=2),
    "timeout": 300,
    "retry": 360,
    "max_attempts": 3,
    "catch_up": False,
}

# --- API WS de popeye -----------------------------------------------------------------------
POPEYE_API = {
    "BASE_URL": env("POPEYE_API_BASE_URL", default=""),
    "TOKEN": env("POPEYE_API_TOKEN", default=""),
    "AUTH_HEADER": env("POPEYE_API_AUTH_HEADER", default="Authorization"),
    "AUTH_SCHEME": env("POPEYE_API_AUTH_SCHEME", default="Bearer"),
    "TIMEOUT": env.float("POPEYE_API_TIMEOUT", default=15.0),
    "MAX_RETRIES": env.int("POPEYE_API_MAX_RETRIES", default=3),
}

# --- Gmail: facturas de proveedores en el buzón de administración -------------------------
GMAIL = {
    "MAILBOX": env("GMAIL_MAILBOX", default="admin@andronautic.com"),
    # JSON de la clave de la cuenta de servicio (o ruta al fichero), con delegación de dominio
    "SERVICE_ACCOUNT_JSON": env("GMAIL_SERVICE_ACCOUNT_JSON", default=""),
    # Etiqueta padre; cada proveedor tiene una subetiqueta "Gastos/<proveedor>"
    "INVOICES_LABEL": env("GMAIL_INVOICES_LABEL", default="Gastos"),
    # Etiqueta de los correos de la gestoría con las nóminas de cada mes
    "NOMINAS_LABEL": env("GMAIL_NOMINAS_LABEL", default="Gastos/Nominas"),
    # Ventana mínima de búsqueda del botón y, por defecto, de los comandos
    "SYNC_DAYS": env.int("GMAIL_SYNC_DAYS", default=30),
}

# Google Drive: copia de las facturas recibidas para contabilidad, en la carpeta de cada
# empresa (Empresa.carpeta_drive). Usa la misma cuenta de servicio que Gmail, que necesita
# además el scope https://www.googleapis.com/auth/drive.
DRIVE = {
    # Usuario de Workspace en cuyo nombre se actúa: debe tener acceso a la unidad compartida
    "USUARIO": env("DRIVE_USUARIO", default=GMAIL["MAILBOX"]),
    "SERVICE_ACCOUNT_JSON": env(
        "DRIVE_SERVICE_ACCOUNT_JSON", default=GMAIL["SERVICE_ACCOUNT_JSON"]
    ),
    # Dentro de la carpeta del año: contabilidad mueve aquí las facturas ya contabilizadas
    "CARPETA_CONTABILIZADO": env("DRIVE_CARPETA_CONTABILIZADO", default="CONTABILIZADO"),
}

# --- Departamentos --------------------------------------------------------------------------
# Cada departamento es un Group de Django. La navegación y los permisos de las vistas salen de aquí.
# El orden es el del menú lateral.
DEPARTMENTS = {
    "administracion": "Administración",
    "marketing": "Marketing",
    "comercial": "Comercial",
}

# --- Admin (Unfold) -------------------------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": "AndroNautic · Interno",
    "SITE_HEADER": "AndroNautic Interno",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # httpx registra cada petición en INFO: demasiado ruido al recorrer las carpetas de Drive
    "loggers": {"httpx": {"level": "WARNING"}},
}
