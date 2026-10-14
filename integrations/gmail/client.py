"""Cliente de solo lectura del API de Gmail para un buzón de Google Workspace.

Se autentica con una cuenta de servicio con delegación de dominio: la cuenta actúa en nombre
del buzón configurado (GMAIL_MAILBOX) con el scope gmail.readonly, sin que nadie inicie sesión.

- Todas las llamadas son lecturas: reintentos con backoff ante timeouts, 429 y 5xx.
- Los mensajes se devuelven como dataclasses (GmailMessage, GmailAttachment), no JSON crudo.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import httpx
from django.conf import settings

from .exceptions import (
    GmailAuthError,
    GmailConfigError,
    GmailError,
    GmailNotFound,
    GmailUnavailable,
)

logger = logging.getLogger(__name__)

API_URL = "https://gmail.googleapis.com/gmail/v1/users/{mailbox}/"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass(frozen=True)
class GmailAttachment:
    part_id: str
    filename: str
    mime_type: str
    size: int
    attachment_id: str = ""
    inline_data: str = ""  # adjuntos pequeños vienen embebidos en el mensaje (base64url)


@dataclass(frozen=True)
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    received_at: datetime
    attachments: list[GmailAttachment] = field(default_factory=list)


def service_account_token_provider(info: dict, mailbox: str) -> Callable[[], str]:
    """Devuelve una función que entrega un access token válido, renovándolo al caducar."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES, subject=mailbox
    )

    def get_token() -> str:
        if not credentials.valid:
            try:
                credentials.refresh(Request())
            except Exception as exc:
                raise GmailAuthError(
                    f"La cuenta de servicio no puede acceder a {mailbox}: {exc}"
                ) from exc
        return credentials.token

    return get_token


class GmailClient:
    def __init__(
        self,
        mailbox: str,
        token_provider: Callable[[], str],
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not mailbox:
            raise GmailConfigError("GMAIL_MAILBOX no está configurado")
        self.mailbox = mailbox
        self._token_provider = token_provider
        self.max_retries = max(1, max_retries)
        self.backoff_base = backoff_base
        self._http = httpx.Client(
            base_url=API_URL.format(mailbox=mailbox),
            headers={"Accept": "application/json", "User-Agent": "andronautic-internal/0.1"},
            timeout=timeout,
            transport=transport,
        )

    # --- API pública ------------------------------------------------------------------------

    def labels(self) -> dict[str, str]:
        """Etiquetas del buzón como {nombre: id}. Las anidadas se llaman "Padre/Hija"."""
        data = self._get("labels")
        return {label["name"]: label["id"] for label in data.get("labels", [])}

    def message_ids(self, label_id: str, query: str = "") -> Iterator[str]:
        """Ids de los mensajes con esa etiqueta, del más reciente al más antiguo."""
        params: dict[str, Any] = {"labelIds": label_id, "maxResults": 500}
        if query:
            params["q"] = query
        while True:
            data = self._get("messages", params=params)
            for message in data.get("messages", []):
                yield message["id"]
            page_token = data.get("nextPageToken")
            if not page_token:
                return
            params["pageToken"] = page_token

    def message(self, message_id: str) -> GmailMessage:
        data = self._get(f"messages/{message_id}", params={"format": "full"})
        payload = data.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        sender = headers.get("from", "")
        return GmailMessage(
            id=data["id"],
            thread_id=data.get("threadId", ""),
            subject=headers.get("subject", ""),
            sender=sender,
            sender_email=parseaddr(sender)[1].lower(),
            received_at=datetime.fromtimestamp(int(data.get("internalDate", 0)) / 1000, tz=UTC),
            attachments=list(_attachments(payload)),
        )

    def attachment_content(self, message_id: str, attachment: GmailAttachment) -> bytes:
        if attachment.inline_data:
            return _b64decode(attachment.inline_data)
        data = self._get(f"messages/{message_id}/attachments/{attachment.attachment_id}")
        return _b64decode(data["data"])

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GmailClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Internos ---------------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            headers = {"Authorization": f"Bearer {self._token_provider()}"}
            try:
                response = self._http.get(path, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = str(exc)
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code != 429 and response.status_code < 500:
                    self._raise_for_status(response)
                last_error = f"HTTP {response.status_code}"
            logger.warning(
                "gmail GET %s: %s (intento %s/%s)", path, last_error, attempt, self.max_retries
            )
            if attempt < self.max_retries:
                time.sleep(self.backoff_base * 2 ** (attempt - 1))
        raise GmailUnavailable(f"Gmail no responde en GET {path}: {last_error}")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        body = response.text[:2000]
        msg = f"Gmail respondió {status} en GET {response.request.url.path}"
        if status in (401, 403):
            raise GmailAuthError(msg, status, body)
        if status == 404:
            raise GmailNotFound(msg, status, body)
        raise GmailError(msg, status, body)


def _attachments(part: dict) -> Iterator[GmailAttachment]:
    body = part.get("body", {})
    if part.get("filename") and (body.get("attachmentId") or body.get("data")):
        yield GmailAttachment(
            part_id=part.get("partId", ""),
            filename=part["filename"],
            mime_type=part.get("mimeType", ""),
            size=body.get("size", 0),
            attachment_id=body.get("attachmentId", ""),
            inline_data="" if body.get("attachmentId") else body.get("data", ""),
        )
    for child in part.get("parts", []):
        yield from _attachments(child)


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _load_service_account(value: str) -> dict:
    """GMAIL_SERVICE_ACCOUNT_JSON admite el JSON de la clave o la ruta al fichero."""
    if not value:
        raise GmailConfigError("GMAIL_SERVICE_ACCOUNT_JSON no está configurado")
    try:
        if value.lstrip().startswith("{"):
            return json.loads(value)
        return json.loads(Path(value).read_text())
    except (OSError, ValueError) as exc:
        raise GmailConfigError(f"No se puede leer la cuenta de servicio de Gmail: {exc}") from exc


def is_configured() -> bool:
    cfg = settings.GMAIL
    return bool(cfg["MAILBOX"] and cfg["SERVICE_ACCOUNT_JSON"])


def get_client(**overrides) -> GmailClient:
    cfg = settings.GMAIL
    mailbox = overrides.pop("mailbox", cfg["MAILBOX"])
    token_provider = overrides.pop("token_provider", None) or service_account_token_provider(
        _load_service_account(cfg["SERVICE_ACCOUNT_JSON"]), mailbox
    )
    return GmailClient(mailbox, token_provider, **overrides)
