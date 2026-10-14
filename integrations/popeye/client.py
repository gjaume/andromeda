"""Cliente único del API WS de popeye.

Las apps de departamento no llaman al API directamente: usan este cliente o, mejor,
funciones de `integrations/popeye/resources/` que devuelven objetos tipados.

- Lecturas (GET): reintentos con backoff ante timeouts y 5xx.
- Escrituras (POST/PUT/PATCH/DELETE): sin reintento automático (pueden no ser idempotentes)
  y siempre auditadas en core.PopeyeApiCall con el usuario que las lanza.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

from .exceptions import (
    PopeyeAuthError,
    PopeyeClientError,
    PopeyeError,
    PopeyeNotFound,
    PopeyeUnavailable,
)

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
RESPONSE_EXCERPT_CHARS = 2000


class PopeyeClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise PopeyeError("POPEYE_API_BASE_URL no está configurado")
        if not token:
            raise PopeyeError("POPEYE_API_TOKEN no está configurado")

        auth_value = f"{auth_scheme} {token}".strip() if auth_scheme else token
        self.max_retries = max(1, max_retries)
        self.backoff_base = backoff_base
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={
                auth_header: auth_value,
                "Accept": "application/json",
                "User-Agent": "andronautic-internal/0.1",
            },
            timeout=timeout,
            transport=transport,
        )

    # --- API pública ------------------------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any = None, *, actor=None) -> Any:
        return self.request("POST", path, json=json, actor=actor)

    def put(self, path: str, json: Any = None, *, actor=None) -> Any:
        return self.request("PUT", path, json=json, actor=actor)

    def patch(self, path: str, json: Any = None, *, actor=None) -> Any:
        return self.request("PATCH", path, json=json, actor=actor)

    def delete(self, path: str, *, actor=None) -> Any:
        return self.request("DELETE", path, actor=actor)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        actor=None,
    ) -> Any:
        method = method.upper()
        path = path.lstrip("/")
        is_write = method not in SAFE_METHODS
        attempts = 1 if is_write else self.max_retries

        started = time.monotonic()
        response: httpx.Response | None = None
        error: PopeyeError | None = None

        try:
            response = self._send_with_retries(method, path, params, json, attempts)
            self._raise_for_status(response)
            return self._parse(response)
        except PopeyeError as exc:
            error = exc
            raise
        finally:
            if is_write:
                self._audit(method, path, json, response, error, actor, started)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PopeyeClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Internos ---------------------------------------------------------------------------

    def _send_with_retries(self, method, path, params, json, attempts) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self._http.request(method, path, params=params, json=json)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                logger.warning(
                    "popeye %s %s: %s (intento %s/%s)", method, path, exc, attempt, attempts
                )
            else:
                if response.status_code < 500 or attempt == attempts:
                    return response
                logger.warning(
                    "popeye %s %s: HTTP %s (intento %s/%s)",
                    method,
                    path,
                    response.status_code,
                    attempt,
                    attempts,
                )
            if attempt < attempts:
                time.sleep(self.backoff_base * 2 ** (attempt - 1))

        raise PopeyeUnavailable(f"popeye no responde: {last_exc}") from last_exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return
        body = response.text[:RESPONSE_EXCERPT_CHARS]
        msg = f"popeye respondió {status} en {response.request.method} {response.request.url.path}"
        if status in (401, 403):
            raise PopeyeAuthError(msg, status, body)
        if status == 404:
            raise PopeyeNotFound(msg, status, body)
        if status >= 500:
            raise PopeyeUnavailable(msg, status, body)
        raise PopeyeClientError(msg, status, body)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    @staticmethod
    def _audit(method, path, body, response, error, actor, started) -> None:
        from core.models import PopeyeApiCall

        try:
            PopeyeApiCall.objects.create(
                user=actor if getattr(actor, "is_authenticated", False) else None,
                method=method,
                path=path[:500],
                request_body=body if isinstance(body, (dict, list)) else None,
                status_code=response.status_code if response is not None else None,
                response_excerpt=response.text[:RESPONSE_EXCERPT_CHARS]
                if response is not None
                else "",
                duration_ms=int((time.monotonic() - started) * 1000),
                error=str(error)[:500] if error else "",
            )
        except Exception:  # la auditoría nunca debe romper la operación
            logger.exception("No se pudo registrar la llamada a popeye")


def get_client(**overrides) -> PopeyeClient:
    cfg = settings.POPEYE_API
    return PopeyeClient(
        base_url=overrides.pop("base_url", cfg["BASE_URL"]),
        token=overrides.pop("token", cfg["TOKEN"]),
        auth_header=cfg["AUTH_HEADER"],
        auth_scheme=cfg["AUTH_SCHEME"],
        timeout=cfg["TIMEOUT"],
        max_retries=cfg["MAX_RETRIES"],
        **overrides,
    )
