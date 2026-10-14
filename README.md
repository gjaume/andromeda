# AndroNautic Interno

Backoffice de utilidades para los departamentos internos de AndroNautic (Comercial, Administración, Marketing…). Se despliega en cloud (Render), fuera de la infraestructura interna, y se comunica con popeye **solo** a través del API WS.

## Stack

Django 5.2 LTS · HTMX + Alpine.js · django-unfold (admin) · django-allauth (SSO Google Workspace) · django-q2 (tareas en segundo plano sobre Postgres) · httpx (cliente de popeye) · Cloudflare R2 (ficheros) · Sentry · uv + ruff + pytest.

## Arrancar en local

```bash
cp .env.example .env          # rellena GOOGLE_OAUTH_* y, si lo necesitas, POPEYE_API_*
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser   # para entrar en /admin sin Google
uv run python manage.py runserver
```

Tareas en segundo plano en otra terminal: `uv run python manage.py qcluster`.

Tests y calidad: `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`

## Login con Google Workspace

1. En Google Cloud Console, crea un OAuth client de tipo **Aplicación web** dentro del proyecto de la organización y márcalo como **Interno** en la pantalla de consentimiento.
2. URIs de redirección autorizadas:
   - `http://localhost:8000/accounts/google/login/callback/`
   - `https://interno.andronautic.com/accounts/google/login/callback/`
3. Copia client ID y secret en `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.
4. `GOOGLE_WORKSPACE_DOMAINS` define qué dominios pueden entrar (separados por comas). Cualquier otra cuenta se rechaza.

El registro con contraseña está desactivado. El primer login crea el usuario sin departamento; un administrador lo asigna a sus grupos desde `/admin`.

## Departamentos y permisos

Cada departamento es un `Group` de Django (creados por la migración `core/0002`). Un usuario ve en el menú y puede abrir solo las herramientas de sus grupos; los superusuarios ven todo.

### Añadir una herramienta

1. Crea la vista en la app del departamento con `DepartmentRequiredMixin`:

   ```python
   class InformeComisionesView(DepartmentRequiredMixin, TemplateView):
       department = "administracion"
       template_name = "administracion/informe_comisiones.html"
   ```
2. Añade la URL en `apps/<departamento>/urls.py`.
3. Regístrala en el menú desde `apps/<departamento>/apps.py` con `register_tool(...)`.

### Añadir un departamento

Crea la app en `apps/`, añádela a `INSTALLED_APPS` y a `DEPARTMENTS` en `config/settings/base.py`, incluye sus URLs en `config/urls.py` y crea su `Group` con una migración de datos.

## Integración con popeye

Todo acceso a popeye pasa por `integrations/popeye/`:

- `get_client()` devuelve un `PopeyeClient` configurado con `POPEYE_API_*`.
- Las lecturas reintentan con backoff ante timeouts y 5xx; las escrituras no se reintentan automáticamente.
- Los errores llegan tipados: `PopeyeAuthError`, `PopeyeNotFound`, `PopeyeClientError`, `PopeyeUnavailable`.
- Toda escritura queda auditada en `PopeyeApiCall` con el usuario que la hizo (`actor=request.user`), visible en el admin.
- Las funciones por recurso (reservas, barcos, agentes…) van en `integrations/popeye/resources/` y devuelven dataclasses, no JSON crudo.

Si el API usa otra cabecera o esquema de autenticación, ajusta `POPEYE_API_AUTH_HEADER` y `POPEYE_API_AUTH_SCHEME` (por ejemplo `X-Api-Key` y esquema vacío).

## Facturas de proveedores (Gmail)

Herramienta de Administración: cada proveedor tiene una subetiqueta de Gmail dentro de `Gastos` (p. ej. `Gastos/Iberdrola`), a la que una regla de Gmail envía sus correos. Cada 4 horas la tarea `sincronizar_facturas_gmail` revisa esas etiquetas en el buzón `admin@andronautic.com`, descarga los PDF adjuntos de los correos nuevos y los guarda en **Facturas recibidas**. Cada correo se procesa una sola vez, tenga o no factura.

- Proveedores: `/administracion/proveedores/`. La etiqueta se escribe sin el prefijo `Gastos/`.
- Facturas: `/administracion/facturas/`, con botón para buscar en el momento.
- Frecuencia: admin → Django Q → Tareas programadas → «Sincronizar facturas de Gmail».
- Histórico completo: `uv run python manage.py sincronizar_facturas --dias 0`.

### Acceso al buzón

El proceso lee el buzón sin que nadie inicie sesión, con una cuenta de servicio de Google Workspace:

1. En Google Cloud Console (proyecto de la organización), activa la **Gmail API**.
2. Crea una **cuenta de servicio** y descarga una clave en JSON.
3. En la consola de administración de Workspace → Seguridad → Controles de API → **Delegación de todo el dominio**, autoriza el *client ID* de la cuenta de servicio con el scope `https://www.googleapis.com/auth/gmail.readonly`.
4. Pon en `GMAIL_SERVICE_ACCOUNT_JSON` el contenido del JSON (en Render) o la ruta al fichero (en local, fuera del repo).

El acceso es de solo lectura: el proceso no marca, mueve ni borra correos.

## Despliegue en Render

`render.yaml` define un Blueprint con web service, worker y Postgres gestionado en Frankfurt:

1. Sube el repo a GitHub y en Render elige **New → Blueprint** apuntando a él.
2. Rellena en el grupo de variables `andronautic-internal-shared` los valores marcados como secretos.
3. Añade el dominio `interno.andronautic.com` al web service y crea el CNAME en Cloudflare.

Cada push a `main` despliega automáticamente; las migraciones se ejecutan antes de cada deploy (`preDeployCommand`). El healthcheck es `/healthz`.

La aplicación es un contenedor sin estado: si en algún momento se aloja en la infraestructura interna, basta con la misma imagen Docker, un Postgres y las mismas variables de entorno.

## Estructura

```
config/          settings por entorno (base, dev, test, prod), urls, wsgi
core/            SSO, departamentos, navegación, auditoría de popeye, layout
apps/            una app por departamento
integrations/    clientes de servicios externos (popeye, gmail)
templates/       base, login y plantillas por departamento
static/          estilos
tests/           pytest
```
