class PopeyeError(Exception):
    """Error genérico del API WS de popeye."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PopeyeAuthError(PopeyeError):
    """Token inválido o sin permisos (401/403)."""


class PopeyeNotFound(PopeyeError):
    """El recurso no existe (404)."""


class PopeyeClientError(PopeyeError):
    """Petición rechazada por datos inválidos (4xx)."""


class PopeyeUnavailable(PopeyeError):
    """popeye no responde o devuelve 5xx tras agotar los reintentos."""
