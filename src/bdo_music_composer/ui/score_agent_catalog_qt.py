"""Check an API connection against its OpenAI-compatible model catalog."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from bdo_music_composer.app.score_agent_settings import (
    MAX_MODEL_LENGTH, is_loopback_base_url, normalize_api_key, normalize_base_url,
)


_CATALOG_LIMIT = 2 * 1024 * 1024
_TIMEOUT_MS = 12_000
_HTTP_ERRORS = {
    401: "authentication", 402: "billing", 403: "authentication",
    404: "no_catalog", 405: "no_catalog", 408: "timeout", 429: "rate_limited",
    500: "service_unavailable", 502: "service_unavailable",
    503: "service_unavailable", 504: "timeout",
}


def catalog_model_ids(raw: bytes) -> tuple[str, ...] | None:
    """Read usable IDs from the provider's model catalog, in provider order."""
    if len(raw) > _CATALOG_LIMIT:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    identifiers = {}
    for item in models:
        model_id = item.get("id") if isinstance(item, dict) else None
        if (
            isinstance(model_id, str) and 0 < len(model_id) <= MAX_MODEL_LENGTH
            and model_id == model_id.strip() and model_id.isprintable()
        ):
            identifiers[model_id] = None
    return tuple(identifiers) if identifiers or not models else None


class ModelCatalogCheck(QObject):
    """Issue a cancellable, metadata-only GET without following redirects."""

    completed = Signal(str, tuple)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._complete("timeout"))
        self._reply: QNetworkReply | None = None
        self._body = bytearray()

    def start(self, base_url: str, api_key: str) -> None:
        self.abort()
        try:
            base_url = normalize_base_url(base_url)
            api_key = normalize_api_key(base_url, api_key)
        except ValueError:
            self._complete("invalid_connection")
            return
        endpoint = QUrl(base_url.rstrip("/") + "/models", QUrl.ParsingMode.StrictMode)
        if not endpoint.isValid():
            self._complete("invalid_connection")
            return
        proxy_type = (
            QNetworkProxy.ProxyType.NoProxy if is_loopback_base_url(base_url) else QNetworkProxy.ProxyType.DefaultProxy
        )
        self._manager.setProxy(QNetworkProxy(proxy_type))
        request = QNetworkRequest(endpoint)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setRawHeader(b"Accept", b"application/json")
        if api_key:
            request.setRawHeader(b"Authorization", b"Bearer " + api_key.encode("ascii"))
        reply = self._manager.get(request)
        self._reply = reply
        reply.setReadBufferSize(_CATALOG_LIMIT + 1)
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finish(reply))
        self._timer.start(_TIMEOUT_MS)

    def abort(self) -> None:
        reply, self._reply = self._reply, None
        self._timer.stop()
        self._body.clear()
        if reply is not None:
            if not reply.isFinished():
                reply.abort()
            reply.deleteLater()

    def _read(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if isinstance(status, int) and status != 200:
            self._complete("redirected" if 300 <= status < 400 else _HTTP_ERRORS.get(status, "failed"))
            return
        chunk = bytes(reply.readAll())
        if len(self._body) + len(chunk) > _CATALOG_LIMIT:
            self._complete("invalid_response")
        else:
            self._body.extend(chunk)

    def _finish(self, reply: QNetworkReply) -> None:
        self._read(reply)
        if reply is not self._reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        if status == 200 and error == QNetworkReply.NetworkError.NoError:
            models = catalog_model_ids(self._body)
            if models is None:
                self._complete("invalid_response")
            else:
                self._complete("loaded", models)
        elif error in (QNetworkReply.NetworkError.TimeoutError, QNetworkReply.NetworkError.ProxyTimeoutError):
            self._complete("timeout")
        else:
            self._complete("failed")

    def _complete(self, status: str, models: tuple[str, ...] = ()) -> None:
        self.abort()
        self.completed.emit(status, models)
