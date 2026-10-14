class GmailError(Exception):
    """Error genérico del API de Gmail."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class GmailConfigError(GmailError):
    """Falta la configuración (cuenta de servicio o buzón)."""


class GmailAuthError(GmailError):
    """La cuenta de servicio no puede actuar en nombre del buzón (401/403)."""


class GmailNotFound(GmailError):
    """El mensaje o adjunto ya no existe (404)."""


class GmailUnavailable(GmailError):
    """Gmail no responde o devuelve 5xx/429 tras agotar los reintentos."""
