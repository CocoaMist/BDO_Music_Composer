"""Cancellable, fixed-origin DeepSeek web search for the score agent."""

from __future__ import annotations

from html import unescape
from ipaddress import ip_address
import json
import re
from unicodedata import category

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bdo_music_composer.app.score_agent_settings import DEFAULT_BASE_URL, ModelConnection
from bdo_music_composer.ui.score_agent_model_qt import _http_error


_ENDPOINT = DEFAULT_BASE_URL + "/v1/tools/search"
_MAX_QUERY_LENGTH = 128
_MAX_RESULTS = 5
_MAX_RESPONSE_BYTES = 128 * 1024
_TIMEOUT_MS = 12_000
_CODE_MARKUP = re.compile(
    r"<(script|style|pre|code)\b[^>]*>.*?(?:</\1\s*>|$)|```.*?(?:```|$)|`[^`\n]*`",
    re.IGNORECASE | re.DOTALL,
)
_HTML = re.compile(r"<!--.*?(?:-->|$)|<[^<>]*>", re.DOTALL)


def _plain_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = unescape(value[:4096])
    text = _HTML.sub(" ", _CODE_MARKUP.sub(" ", text))
    text = "".join(char for char in text if char.isspace() or not category(char).startswith("C"))
    return " ".join(text.split())[:limit].rstrip()


def _public_source_url(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 2048 or any(
        char.isspace() or category(char).startswith("C") for char in value
    ):
        return ""
    url = QUrl(value, QUrl.ParsingMode.StrictMode)
    host = url.host().rstrip(".").lower()
    if not url.isValid() or url.scheme() not in {"http", "https"} or not host or "@" in url.authority():
        return ""
    try:
        address = ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local", ".internal", ".home.arpa")):
            return ""
    else:
        if not address.is_global or address.is_multicast:
            return ""
    return bytes(url.toEncoded()).decode("ascii")


def _search_results(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ValueError("invalid_response")
    payload = json.loads(raw)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("invalid_response")

    sources = []
    seen = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        url = _public_source_url(row.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({
            "url": url,
            "title": _plain_text(row.get("title"), 140) or QUrl(url).host(),
            "snippet": _plain_text(row.get("snippet"), 320) or _plain_text(row.get("summary"), 320),
            "site_name": _plain_text(row.get("site_name"), 70),
            "date": _plain_text(row.get("date"), 32),
        })
        if len(sources) == _MAX_RESULTS:
            break
    return sources


class DeepSeekWebSearch(QObject):
    """Search only the official DeepSeek origin and emit sanitized citations."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, connection: ModelConnection, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._manager = QNetworkAccessManager(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fail("timeout"))
        self._reply: QNetworkReply | None = None
        self._body = bytearray()

    def start(self, query: str) -> None:
        self.abort()
        if not self._connection.is_official_deepseek:
            self._fail("search_unavailable")
            return
        query = " ".join(query.split()) if isinstance(query, str) else ""
        if not 0 < len(query) <= _MAX_QUERY_LENGTH or not query.isprintable():
            self._fail("invalid_search_query")
            return
        request = QNetworkRequest(QUrl(_ENDPOINT))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Authorization", b"Bearer " + self._connection.api_key.encode("ascii"))
        payload = json.dumps({"query": query, "count": _MAX_RESULTS, "need_content": False}, ensure_ascii=False)
        reply = self._manager.post(request, payload.encode("utf-8"))
        self._reply = reply
        reply.setReadBufferSize(_MAX_RESPONSE_BYTES + 1)
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
            self._fail(_http_error(status))
            return
        chunk = bytes(reply.readAll())
        if len(self._body) + len(chunk) > _MAX_RESPONSE_BYTES:
            self._fail("invalid_response")
        else:
            self._body.extend(chunk)

    def _finish(self, reply: QNetworkReply) -> None:
        self._read(reply)
        if reply is not self._reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        if status != 200 or error != QNetworkReply.NetworkError.NoError:
            timeout = error in (QNetworkReply.NetworkError.TimeoutError, QNetworkReply.NetworkError.ProxyTimeoutError)
            self._fail("timeout" if timeout else "failed")
            return
        try:
            results = _search_results(self._body)
        except (ValueError, RecursionError):
            self._fail("invalid_response")
            return
        self.abort()
        self.succeeded.emit(results)

    def _fail(self, code: str) -> None:
        self.abort()
        self.failed.emit(code)
