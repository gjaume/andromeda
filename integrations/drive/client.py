"""Cliente del API de Google Drive para las unidades compartidas de Google Workspace.

Usa la misma cuenta de servicio con delegación de dominio que Gmail, actuando en nombre de un
usuario (DRIVE_USUARIO) con acceso a la unidad compartida y el scope drive.

- Las lecturas se reintentan con backoff ante timeouts, 429 y 5xx. Las escrituras (crear
  carpeta, subir o renombrar fichero) no se reintentan, para no duplicar nada si la primera
  llegó a hacerse.
- Todas las llamadas incluyen supportsAllDrives: sin ese parámetro Drive ignora las unidades
  compartidas.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

from integrations.gmail.client import _load_service_account

from .exceptions import (
    DriveAuthError,
    DriveConfigError,
    DriveError,
    DriveNotFound,
    DriveUnavailable,
)

logger = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/drive/v3/"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
SCOPES = ["https://www.googleapis.com/auth/drive"]
CARPETA = "application/vnd.google-apps.folder"
HOJA_DE_CALCULO = "application/vnd.google-apps.spreadsheet"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CAMPOS_FICHERO = "id,name,mimeType,md5Checksum,parents"


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    md5: str = ""  # vacío en carpetas y documentos de Google

    @property
    def es_carpeta(self) -> bool:
        return self.mime_type == CARPETA


def service_account_token_provider(info: dict, usuario: str) -> Callable[[], str]:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES, subject=usuario
    )

    def get_token() -> str:
        if not credentials.valid:
            try:
                credentials.refresh(Request())
            except Exception as exc:
                raise DriveAuthError(
                    f"La cuenta de servicio no puede acceder a Drive como {usuario}: {exc}"
                ) from exc
        return credentials.token

    return get_token


def _comillas(texto: str) -> str:
    """Escapa un valor para las consultas q= de Drive."""
    return texto.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token_provider = token_provider
        self.max_retries = max(1, max_retries)
        self.backoff_base = backoff_base
        self._http = httpx.Client(
            headers={"Accept": "application/json", "User-Agent": "andronautic-internal/0.1"},
            timeout=timeout,
            transport=transport,
        )

    # --- API pública ------------------------------------------------------------------------

    def unidad_compartida(self, nombre: str) -> str:
        """Id de la unidad compartida con ese nombre."""
        params: dict[str, Any] = {"pageSize": 100}
        while True:
            data = self._get(API_URL + "drives", params)
            for unidad in data.get("drives", []):
                if unidad["name"] == nombre:
                    return unidad["id"]
            if not data.get("nextPageToken"):
                raise DriveNotFound(f"No encuentro la unidad compartida «{nombre}»")
            params["pageToken"] = data["nextPageToken"]

    def hijos(self, carpeta_id: str, *, solo_carpetas: bool = False) -> Iterator[DriveFile]:
        """Ficheros y carpetas que cuelgan directamente de la carpeta (sin los de la papelera)."""
        q = f"'{_comillas(carpeta_id)}' in parents and trashed = false"
        if solo_carpetas:
            q += f" and mimeType = '{CARPETA}'"
        params: dict[str, Any] = {
            "q": q,
            "fields": f"nextPageToken,files({CAMPOS_FICHERO})",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        while True:
            data = self._get(API_URL + "files", params)
            for f in data.get("files", []):
                yield DriveFile(f["id"], f["name"], f["mimeType"], f.get("md5Checksum", ""))
            if not data.get("nextPageToken"):
                return
            params["pageToken"] = data["nextPageToken"]

    def subcarpeta(self, carpeta_id: str, nombre: str) -> DriveFile | None:
        return next(
            (f for f in self.hijos(carpeta_id, solo_carpetas=True) if f.name == nombre), None
        )

    def ruta(self, unidad: str, ruta: str) -> str:
        """Id de la carpeta "A/B/C" dentro de la unidad compartida."""
        carpeta_id = self.unidad_compartida(unidad)
        recorrido = unidad
        for nombre in filter(None, ruta.split("/")):
            recorrido += f" > {nombre}"
            carpeta = self.subcarpeta(carpeta_id, nombre)
            if carpeta is None:
                raise DriveNotFound(f"No encuentro la carpeta «{recorrido}» en Drive")
            carpeta_id = carpeta.id
        return carpeta_id

    def fichero(self, carpeta_id: str, nombre: str) -> DriveFile | None:
        """Fichero (no carpeta) con ese nombre directamente dentro de la carpeta."""
        return next(
            (f for f in self.hijos(carpeta_id) if f.name == nombre and not f.es_carpeta), None
        )

    def descargar(self, fichero: DriveFile) -> bytes:
        """Contenido del fichero. Las hojas de cálculo de Google se exportan como .xlsx."""
        if fichero.mime_type == HOJA_DE_CALCULO:
            url = f"{API_URL}files/{fichero.id}/export"
            return self._get_bytes(url, {"mimeType": XLSX})
        return self._get_bytes(
            f"{API_URL}files/{fichero.id}", {"alt": "media", "supportsAllDrives": "true"}
        )

    def crear_carpeta(self, padre_id: str, nombre: str) -> DriveFile:
        data = self._enviar(
            "POST",
            API_URL + "files",
            params={"supportsAllDrives": "true", "fields": CAMPOS_FICHERO},
            json={"name": nombre, "mimeType": CARPETA, "parents": [padre_id]},
        )
        return DriveFile(data["id"], data["name"], data["mimeType"])

    def renombrar(self, fichero_id: str, nombre: str) -> DriveFile:
        data = self._enviar(
            "PATCH",
            f"{API_URL}files/{fichero_id}",
            params={"supportsAllDrives": "true", "fields": CAMPOS_FICHERO},
            json={"name": nombre},
        )
        return DriveFile(data["id"], data["name"], data["mimeType"], data.get("md5Checksum", ""))

    def subir(
        self, padre_id: str, nombre: str, contenido: bytes, mime_type: str = "application/pdf"
    ) -> DriveFile:
        frontera = "andronautic-internal-frontera"
        metadatos = json.dumps({"name": nombre, "parents": [padre_id]})
        partes = [
            f"--{frontera}",
            "Content-Type: application/json; charset=UTF-8",
            "",
            metadatos,
            f"--{frontera}",
            f"Content-Type: {mime_type}",
            "",
            "",
        ]
        cuerpo = "\r\n".join(partes).encode() + contenido + f"\r\n--{frontera}--".encode()
        data = self._enviar(
            "POST",
            UPLOAD_URL,
            params={
                "uploadType": "multipart",
                "supportsAllDrives": "true",
                "fields": CAMPOS_FICHERO,
            },
            content=cuerpo,
            headers={"Content-Type": f"multipart/related; boundary={frontera}"},
        )
        return DriveFile(data["id"], data["name"], data["mimeType"], data.get("md5Checksum", ""))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DriveClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Internos ---------------------------------------------------------------------------

    def _auth(self, headers: dict | None = None) -> dict:
        return {**(headers or {}), "Authorization": f"Bearer {self._token_provider()}"}

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        return self._get_response(url, params).json()

    def _get_bytes(self, url: str, params: dict[str, Any]) -> bytes:
        return self._get_response(url, params).content

    def _get_response(self, url: str, params: dict[str, Any]) -> httpx.Response:
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._http.get(url, params=params, headers=self._auth())
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = str(exc)
            else:
                if response.status_code < 400:
                    return response
                if response.status_code != 429 and response.status_code < 500:
                    self._raise_for_status(response)
                last_error = f"HTTP {response.status_code}"
            logger.warning(
                "drive GET %s: %s (intento %s/%s)", url, last_error, attempt, self.max_retries
            )
            if attempt < self.max_retries:
                time.sleep(self.backoff_base * 2 ** (attempt - 1))
        raise DriveUnavailable(f"Drive no responde en GET {url}: {last_error}")

    def _enviar(self, method: str, url: str, *, headers: dict | None = None, **kwargs) -> Any:
        try:
            response = self._http.request(method, url, headers=self._auth(headers), **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise DriveUnavailable(f"Drive no responde en {method} {url}: {exc}") from exc
        if response.status_code >= 400:
            self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        body = response.text[:2000]
        msg = f"Drive respondió {status} en {response.request.method} {response.request.url.path}"
        if status in (401, 403):
            raise DriveAuthError(msg, status, body)
        if status == 404:
            raise DriveNotFound(msg, status, body)
        raise DriveError(msg, status, body)


def is_configured() -> bool:
    cfg = settings.DRIVE
    return bool(cfg["USUARIO"] and cfg["SERVICE_ACCOUNT_JSON"])


def get_client(**overrides) -> DriveClient:
    cfg = settings.DRIVE
    token_provider = overrides.pop("token_provider", None)
    if token_provider is None:
        if not cfg["USUARIO"]:
            raise DriveConfigError("DRIVE_USUARIO no está configurado")
        token_provider = service_account_token_provider(
            _load_service_account(cfg["SERVICE_ACCOUNT_JSON"]), cfg["USUARIO"]
        )
    return DriveClient(token_provider, **overrides)
