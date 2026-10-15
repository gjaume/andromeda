FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project $( [ -f uv.lock ] && echo --frozen )

COPY . .

RUN DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_SECRET_KEY=build \
    python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app
USER app

ENV DJANGO_SETTINGS_MODULE=config.settings.prod PORT=8080
EXPOSE 8080

CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-3} --timeout 60 --access-logfile -
