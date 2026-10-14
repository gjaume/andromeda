class DriveError(Exception):
    """Error genérico del API de Google Drive."""

    def __init__(self, message: str, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class DriveConfigError(DriveError):
    """Falta la configuración (cuenta de servicio, usuario o carpeta)."""


class DriveAuthError(DriveError):
    """La cuenta de servicio no puede actuar en nombre del usuario (401/403)."""


class DriveNotFound(DriveError):
    """404, o una carpeta de la ruta configurada que no existe."""


class DriveUnavailable(DriveError):
    """Drive no responde tras los reintentos (timeouts, 429, 5xx)."""
