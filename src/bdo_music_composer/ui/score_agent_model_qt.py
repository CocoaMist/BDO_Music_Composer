"""Cancellable Qt transport for the score agent's OpenAI-compatible model."""

from __future__ import annotations

import json
import re

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from bdo_music_composer.app.score_agent_settings import ModelConnection


_MAX_REQUEST_BYTES = 256 * 1024
_MAX_THINKING_REQUEST_BYTES = 512 * 1024
_MAX_STREAM_BYTES = 2 * 1024 * 1024
# DeepSeek may send an SSE event per reasoning token. Wire overhead at 32K
# tokens would exhaust the regular budget before the configured token limit.
_MAX_THINKING_STREAM_BYTES = 16 * 1024 * 1024
_MAX_EVENT_BYTES = 64 * 1024
_MAX_TOOL_CALLS = 8
_REQUEST_TIMEOUT_MS = 90_000
_QUICK_MAX_TOKENS = 768
_THINKING_MAX_TOKENS = {"low": 8192, "high": 16_384, "max": 32_768}
_THINKING_TIMEOUTS_MS = {"low": 120_000, "high": 180_000, "max": 300_000}
_HTTP_ERRORS = {
    400: "invalid_model_request", 401: "authentication", 402: "billing",
    403: "authentication", 404: "invalid_model", 405: "invalid_model",
    408: "timeout", 422: "invalid_model_request", 429: "rate_limited",
    500: "service_unavailable", 502: "service_unavailable",
    503: "service_unavailable", 504: "timeout",
}


_STREAM_ERRORS = {
    "api_error": "service_unavailable",
    "server_error": "service_unavailable",
    "overloaded_error": "service_unavailable",
    "rate_limit_error": "rate_limited",
    "timeout": "timeout",
}
_FINISH_ERRORS = {
    "length": "response_truncated",
    "content_filter": "content_filtered",
    "insufficient_system_resource": "service_unavailable",
    "aborted": "service_unavailable",
}


class _ProviderResponseError(ValueError):
    """A provider interruption that can be reported without the remote text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _http_error(status: object) -> str:
    if not isinstance(status, int):
        return "failed"
    if 300 <= status < 400:
        return "redirected"
    return _HTTP_ERRORS.get(status, "failed")


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Expected finite JSON.")


def _token_usage(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    fields = {
        field: raw.get(field) for field in (
            "prompt_tokens", "completion_tokens", "total_tokens",
            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
        )
    }
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict) and fields["prompt_cache_hit_tokens"] is None:
        fields["prompt_cache_hit_tokens"] = details.get("cached_tokens")
    details = raw.get("completion_tokens_details")
    if isinstance(details, dict):
        fields["reasoning_tokens"] = details.get("reasoning_tokens")
    return {field: count for field, count in fields.items() if type(count) is int and count >= 0}


class _ChatStream:
    """Assemble a single assistant message from bounded, possibly split SSE lines."""

    def __init__(self, *, wire_limit: int = _MAX_STREAM_BYTES, collect_usage: bool = False) -> None:
        self._pending = bytearray()
        self._bytes_received = 0
        self._wire_limit = wire_limit
        self._collect_usage = collect_usage
        self._text: list[str] = []
        self._reasoning: list[str] = []
        self._calls: dict[int, dict] = {}
        self._finish_reason: str | None = None
        self._done = False
        self.provider_error: str | None = None
        self.usage: dict[str, int] | None = None

    def feed(self, data: bytes, *, end: bool = False) -> str:
        self._bytes_received += len(data)
        if self._bytes_received > self._wire_limit:
            raise ValueError("Model stream exceeds its size limit.")
        events = (self._pending + data).split(b"\n")
        self._pending = bytearray() if end else events.pop()
        if len(self._pending) > _MAX_EVENT_BYTES:
            raise ValueError("Model event exceeds its size limit.")
        public_text = []
        for event in events:
            public_text.append(self._event(event))
            if self.provider_error is not None:
                break
        return "".join(public_text)

    def _event(self, event: bytes) -> str:
        if len(event) > _MAX_EVENT_BYTES:
            raise ValueError("Model event exceeds its size limit.")
        if not event.startswith(b"data:") or not (data := event[5:].strip()):
            return ""
        if self._done:
            raise ValueError("Model streamed data after completion.")
        if data == b"[DONE]":
            self._done = True
            return ""

        chunk = json.loads(data.decode("utf-8"), parse_constant=_reject_json_constant)
        if not isinstance(chunk, dict):
            raise ValueError("Invalid model event.")
        if (error := chunk.get("error")) is not None:
            if not isinstance(error, dict):
                raise ValueError("Invalid model error.")
            kind = error.get("type")
            self.provider_error = (
                _STREAM_ERRORS.get(kind, "service_unavailable")
                if isinstance(kind, str) else "service_unavailable"
            )
            return ""
        choices = chunk.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise ValueError("Expected one streamed assistant choice.")
        if self._collect_usage and (usage := _token_usage(chunk.get("usage"))):
            self.usage = usage
        if not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index", 0) != 0:
            raise ValueError("Invalid assistant choice.")
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise ValueError("Invalid assistant delta.")
        content = delta.get("content") or ""
        reasoning = delta.get("reasoning_content") or ""
        calls = delta.get("tool_calls") or []
        if not isinstance(content, str) or not isinstance(reasoning, str) or not isinstance(calls, list):
            raise ValueError("Invalid assistant delta fields.")
        if self._finish_reason and (content or reasoning or calls):
            raise ValueError("Model continued an already finished choice.")
        if content:
            self._text.append(content)
        if reasoning:
            self._reasoning.append(reasoning)
        for call in calls:
            self._append_tool_call(call)
        reason = choice.get("finish_reason")
        if reason is not None:
            if not isinstance(reason, str) or self._finish_reason not in (None, reason):
                raise ValueError("Invalid model finish status.")
            self._finish_reason = reason
        return content

    def _append_tool_call(self, fragment: object) -> None:
        if not isinstance(fragment, dict):
            raise ValueError("Invalid tool call fragment.")
        index = fragment.get("index")
        if type(index) is not int or not 0 <= index < _MAX_TOOL_CALLS:
            raise ValueError("Invalid model tool call index.")
        if fragment.get("type", "function") != "function":
            raise ValueError("Unsupported model tool call type.")
        call = self._calls.setdefault(
            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
        if (identifier := fragment.get("id")) is not None:
            if not isinstance(identifier, str) or call["id"] not in ("", identifier):
                raise ValueError("Invalid model tool call identifier.")
            call["id"] = identifier
        function = fragment.get("function")
        if function is None:
            return
        if not isinstance(function, dict):
            raise ValueError("Invalid model tool function.")
        for field, limit in (("name", 64), ("arguments", _MAX_EVENT_BYTES)):
            part = function.get(field)
            if part is None:
                continue
            previous = call["function"][field]
            if not isinstance(part, str) or len(previous) + len(part) > limit:
                raise ValueError("Invalid model tool function fragment.")
            call["function"][field] = previous + part

    def message(self) -> dict:
        if self.provider_error is not None:
            raise _ProviderResponseError(self.provider_error)
        if self._finish_reason in _FINISH_ERRORS:
            raise _ProviderResponseError(_FINISH_ERRORS[self._finish_reason])
        text = "".join(self._text)
        if self._calls:
            if self._finish_reason != "tool_calls" or sorted(self._calls) != list(range(len(self._calls))):
                raise ValueError("Incomplete model tool calls.")
        elif not text.strip() or not (
            self._finish_reason == "stop" or self._finish_reason is None and self._done
        ):
            raise ValueError("Incomplete model response.")

        result = {"role": "assistant", "content": text or None}
        if self._calls:
            calls = [self._calls[index] for index in range(len(self._calls))]
            identifiers = set()
            for call in calls:
                identifier = call["id"]
                if (
                    not re.fullmatch(r"[!-~]{1,256}", identifier)
                    or identifier in identifiers
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", call["function"]["name"])
                    or not isinstance(json.loads(call["function"]["arguments"], parse_constant=_reject_json_constant), dict)
                ):
                    raise ValueError("Invalid completed model tool call.")
                identifiers.add(identifier)
            result["tool_calls"] = calls
        if self._reasoning:
            result["reasoning_content"] = "".join(self._reasoning)
        return result


def _request_body(connection: ModelConnection, messages: list, tools: list) -> dict:
    thinking = connection.is_official_deepseek and connection.thinking
    history = []
    for message in messages:
        item = dict(message)
        if thinking and tools and item.get("role") == "assistant":
            item.setdefault("reasoning_content", "")
        else:
            item.pop("reasoning_content", None)
        history.append(item)
    body = {"model": connection.model, "messages": history, "stream": True}
    if tools:
        body["tools"] = tools
    if connection.is_official_deepseek:
        body["thinking"] = {"type": "enabled" if thinking else "disabled"}
        body["max_tokens"] = _QUICK_MAX_TOKENS
        if thinking:
            effort = connection.reasoning_effort
            body["max_tokens"] = _THINKING_MAX_TOKENS[effort]
            body["reasoning_effort"] = effort
    return body


class ModelRequest(QObject):
    """Send one assistant turn with optional local DeepSeek token counts."""

    delta = Signal(str)
    usage_received = Signal(object)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, connection: ModelConnection, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._manager = QNetworkAccessManager(self)
        if connection.is_loopback:
            self._manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fail("timeout"))
        self._reply: QNetworkReply | None = None
        self._stream: _ChatStream | None = None

    def start(self, messages: list, tools: list) -> None:
        if self._reply is not None:
            return
        thinking = self._connection.is_official_deepseek and self._connection.thinking
        try:
            body = _request_body(self._connection, messages, tools)
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (AttributeError, TypeError, ValueError, RecursionError):
            self._fail("invalid")
            return
        if len(payload) > (_MAX_THINKING_REQUEST_BYTES if thinking else _MAX_REQUEST_BYTES):
            self._fail("invalid")
            return

        endpoint = QUrl(self._connection.base_url.rstrip("/") + "/chat/completions", QUrl.ParsingMode.StrictMode)
        if not endpoint.isValid():
            self._fail("invalid_connection")
            return
        request = QNetworkRequest(endpoint)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"text/event-stream")
        if self._connection.api_key:
            request.setRawHeader(b"Authorization", b"Bearer " + self._connection.api_key.encode("ascii"))

        self._stream = _ChatStream(
            wire_limit=_MAX_THINKING_STREAM_BYTES if thinking else _MAX_STREAM_BYTES,
            collect_usage=self._connection.is_official_deepseek,
        )
        reply = self._manager.post(request, payload)
        self._reply = reply
        reply.setReadBufferSize(_MAX_EVENT_BYTES)
        reply.readyRead.connect(lambda: self._consume(reply))
        reply.finished.connect(lambda: self._finish(reply))
        timeout = _THINKING_TIMEOUTS_MS[self._connection.reasoning_effort] if thinking else _REQUEST_TIMEOUT_MS
        self._timer.start(timeout)

    def abort(self) -> None:
        """Cancel the current stream and discard any partial tool calls."""
        reply, self._reply = self._reply, None
        self._stream = None
        self._timer.stop()
        if reply is not None:
            if not reply.isFinished():
                reply.abort()
            reply.deleteLater()

    def _consume(self, reply: QNetworkReply, *, end: bool = False) -> None:
        if reply is not self._reply or self._stream is None:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status != 200:
            if status is not None:
                self._fail(_http_error(status))
            return
        try:
            text = self._stream.feed(bytes(reply.readAll()), end=end)
        except (ValueError, RecursionError):
            self._fail("invalid_response")
            return
        if text:
            self.delta.emit(text)
        if reply is self._reply and self._stream is not None and self._stream.provider_error is not None:
            self._fail(self._stream.provider_error)

    def _finish(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        network_error = reply.error()
        if status != 200 or network_error != QNetworkReply.NetworkError.NoError:
            if network_error in (QNetworkReply.NetworkError.TimeoutError, QNetworkReply.NetworkError.ProxyTimeoutError):
                self._fail("timeout")
            else:
                self._fail(_http_error(status))
            return
        self._consume(reply, end=True)
        if reply is not self._reply or self._stream is None:
            return
        try:
            message = self._stream.message()
        except _ProviderResponseError as error:
            self._fail(error.code)
            return
        except (ValueError, RecursionError):
            self._fail("invalid_response")
            return
        usage = self._stream.usage
        self.abort()
        if usage is not None:
            self.usage_received.emit(usage)
        self.succeeded.emit(message)

    def _fail(self, code: str) -> None:
        self.abort()
        self.failed.emit(code)


__all__ = ["ModelConnection", "ModelRequest"]
