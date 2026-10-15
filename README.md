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

Herramienta de Administración: cada proveedor tiene una subetiqueta de Gmail dentro de `Gastos` (p. ej. `Gastos/Iberdrola`), a la que una regla de Gmail envía sus correos. El botón «Buscar facturas ahora» lanza la tarea `sincronizar_facturas_gmail`, que revisa esas etiquetas en el buzón `admin@andronautic.com` (desde una semana antes del último correo procesado, y como poco los últimos `GMAIL_SYNC_DAYS` días), descarga los PDF adjuntos de los correos nuevos y los guarda en **Facturas recibidas**. Cada correo se procesa una sola vez, tenga o no factura.

- Proveedores: `/administracion/proveedores/`. La etiqueta se escribe sin el prefijo `Gastos/`.
- Facturas: `/administracion/facturas/`, con botón para buscar en el momento.
- Histórico completo: `uv run python manage.py sincronizar_facturas --dias 0`.

### Datos de cada factura (líneas, totales y moneda)

Al descargar o subir una factura se lee su PDF con el extractor del formato de su proveedor (`apps/administracion/extraccion/extractores/<clave>.py`, asignado en la ficha del proveedor como «formato de factura»). Se guardan nº, fecha, tipo (factura, abono o recibo), moneda, base, impuestos, total y las líneas. Cada factura queda en uno de estos estados:

- **Extraída**: las líneas suman la base y base + impuestos = total.
- **Extraída, revisar**: se guardó, pero los importes no cuadran (suele indicar que el proveedor cambió el formato).
- **Error al extraer**: el PDF no tiene el formato esperado; el motivo se ve en la ficha de la factura.
- **Sin extractor**: el proveedor no tiene formato asignado.

Para un proveedor nuevo: `uv run python manage.py extraer_facturas --proveedor <nombre> --texto plano` muestra el texto que ve el extractor; se crea `extractores/<clave>.py` siguiendo uno existente (p. ej. `hetzner.py`), con su test en `tests/extractores/`, y se prueba con `--probar`, que no guarda nada. Después, `extraer_facturas --proveedor <nombre>` (o «Volver a leer el PDF» en la ficha) aplica el extractor.

### Acceso al buzón

El proceso lee el buzón sin que nadie inicie sesión, con una cuenta de servicio de Google Workspace:

1. En Google Cloud Console (proyecto de la organización), activa la **Gmail API**.
2. Crea una **cuenta de servicio** y descarga una clave en JSON.
3. En la consola de administración de Workspace → Seguridad → Controles de API → **Delegación de todo el dominio**, autoriza el *client ID* de la cuenta de servicio con el scope `https://www.googleapis.com/auth/gmail.readonly`.
4. Pon en `GMAIL_SERVICE_ACCOUNT_JSON` el contenido del JSON (en Render) o la ruta al fichero (en local, fuera del repo).

El acceso es de solo lectura: el proceso no marca, mueve ni borra correos.

### Copia en Google Drive para contabilidad

Cada factura se emite a una de las empresas del grupo. La aplicación detecta a cuál leyendo en el PDF su CIF o, si no aparece, su nombre. Las empresas se gestionan en el admin.
Cada empresa tiene una carpeta en Drive, dentro de la cual hay una subcarpeta por año, y cada año tiene dentro su `CONTABILIZADO`:

    Administración/ANDROMEDA SOLUTIONS/Facturas recibidas AS/2026/CONTABILIZADO
    Administración/ANDROMEDA TECH GROUP/Facturas recibidas/2026/CONTABILIZADO

El año de cada factura es el de su fecha de factura, o el del correo si todavía no se ha leído del PDF.
El botón «Subir a Drive» de Facturas recibidas lanza la tarea `sincronizar_facturas_drive`, que recorre la carpeta de cada empresa y, para cada factura:

- **Está en `<año>/CONTABILIZADO`**, o en una subcarpeta suya: queda como *contabilizada*.
- **Está en otro sitio dentro de `<año>`**: queda como *subida a Drive*.
- **Está fuera de `<año>`** (en otro año o en un `CONTABILIZADO` fuera de su año): no se vuelve a subir. Sale en la lista de *fuera de sitio* para que contabilidad la mueva.
- **No está**: se sube a la raíz de `<año>`. Si `<año>` o su `CONTABILIZADO` no existen, los crea.

Para encontrar cada factura se usa el id de Drive guardado o, si no lo tiene, el MD5 del PDF. Así se reconoce aunque contabilidad la renombre o alguien la haya subido antes a mano.
No se suben los recibos de pago, los anexos, las facturas duplicadas ni las facturas sin empresa identificada; estas últimas se asignan a mano en el admin.

Usa la misma cuenta de servicio que Gmail, con dos requisitos más:

1. Activar la **Google Drive API** en el proyecto de Google Cloud.
2. Añadir el scope `https://www.googleapis.com/auth/drive` a la delegación de todo el dominio, junto al de Gmail y en la misma línea, separados por coma.

Además, el usuario `DRIVE_USUARIO` (por defecto `admin@andronautic.com`) tiene que ser miembro de la unidad compartida con permiso de gestor de contenido.

```bash
uv run python manage.py sincronizar_drive --probar   # qué subiría, sin tocar nada
uv run python manage.py sincronizar_drive            # sube y actualiza
```

### Conciliación con los pagos

Cada factura se marca como **pagada**, indicando si fue por **tarjeta**, **domiciliación** o **transferencia**, cuando se encuentra su pago en los extractos que Administración mantiene en Drive.
Las rutas se configuran por empresa en el admin:

- **Banco:** el campo `extracto_banco` (y la pestaña) apunta a una hoja con las columnas «F. Operativa», «Concepto», «F. Valor» e «Importe». En ella, las domiciliaciones y las transferencias aparecen una a una.
- **Tarjeta:** el campo `extracto_tarjeta`, con `{anio}`, apunta a un fichero por año con una pestaña por mes (ENE…DIC). La línea «TARJETA CREDITO…» del banco es la liquidación mensual de la tarjeta y se ignora.

Los dos se leen cada hora (tarea «Conciliar pagos») o con `uv run python manage.py conciliar_pagos [--pendientes]`.
Una factura casa con un movimiento si:

- **Importe:** coincide al céntimo. Para los cargos de tarjeta en dólares se usa el «Importe original».
- **Proveedor:** el concepto contiene alguno de los **textos del pago** del proveedor, que se editan en su ficha (por ejemplo `PUIGSERVER` para PYR Asesores). Sin textos, solo se acepta un movimiento con ese importe que sea único y esté cerca de la fecha.
- **Fecha:** el pago está entre 60 días antes y 90 después de la factura. Si hay varias candidatas, gana la más cercana.

Una transferencia que paga varias facturas seguidas del mismo proveedor, como varios meses de alquiler, también se reconoce.
Los pagos se pueden corregir a mano en el admin marcando «pago marcado a mano»; la conciliación automática no toca esas facturas.

## Nóminas (Gmail)

En **Administración → Nóminas**, el botón «Buscar nóminas ahora» descarga los correos de la etiqueta `Gastos/Nominas` (`GMAIL_NOMINAS_LABEL`). De cada correo se guardan el PDF con las nóminas de todos los empleados y el resumen; los de cada empleado, solo si falta el de todos. El mes sale del prefijo `AAAAMM` del fichero. Si llega una corrección se guardan las dos versiones: la última recibida es la buena y las anteriores quedan como sustituidas.

Histórico completo: `uv run python manage.py sincronizar_nominas --dias 0`.

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
