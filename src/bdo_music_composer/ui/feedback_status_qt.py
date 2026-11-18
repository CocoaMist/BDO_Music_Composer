"""Local feedback receipts and bounded asynchronous status checks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from math import ceil
import os
from pathlib import Path
import re
from time import monotonic, time_ns
from typing import Callable

from PySide6.QtCore import QLockFile, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bdo_common.atomic_io import atomic_write_json
from bdo_music_composer.core.project_paths import USER_DATA_DIR


FEEDBACK_ORIGIN = "https://bdo-composer-feedback.sakuraoriyuki.workers.dev"
FEEDBACK_PATH = "/v1/feedback"
STATUS_PATH = "/v1/feedback/status"
QUERY_CODE = re.compile(r"[0-9a-f]{32}")
_REFERENCE = re.compile(r"[0-9a-f]{16}")
_STATUS_ORDER = {"submitted": 0, "received": 1, "resolved": 2}
MAX_FEEDBACK_RESPONSE_BYTES = 64 * 1024
MAX_FEEDBACK_AVAILABILITY_BYTES = 1024
FEEDBACK_TIMEOUT_MS = 8000
_MAX_RECEIPTS = 16
_MAX_STORE_BYTES = 2 * 1024 * 1024
_MAX_MESSAGES = 12
_POLL_INTERVAL_SECONDS = 120
_REQUEST_SPACING_SECONDS = 15
_MAX_RETRY_SECONDS = 600
_WRITE_RETRY_DELAYS_MS = (250, 1000, 4000)


@dataclass(frozen=True)
class FeedbackMessage:
    id: int
    body: str = field(repr=False)
    created_at: int

    def payload(self) -> dict:
        return {"id": self.id, "body": self.body, "created_at": self.created_at}


@dataclass(frozen=True)
class FeedbackTicket:
    reference: str
    status: str
    result: str = field(repr=False)
    messages: tuple[FeedbackMessage, ...] = field(default=(), repr=False)

    @property
    def latest_message_id(self) -> int:
        return self.messages[-1].id if self.messages else 0

    def payload(self) -> dict:
        return {"id": self.reference, "status": self.status, "result": self.result,
                "messages": [message.payload() for message in self.messages]}


@dataclass(frozen=True)
class FeedbackReceipt:
    code: str = field(repr=False)
    ticket: FeedbackTicket
    unread: bool
    changed_at: int

    def payload(self) -> dict:
        return {
            "code": self.code,
            "ticket": self.ticket.payload(),
            "unread": self.unread,
            "changed_at": self.changed_at,
        }


def _parse_ticket(payload: object) -> FeedbackTicket | None:
    if not isinstance(payload, dict):
        return None
    reference, status, result = payload.get("id"), payload.get("status"), payload.get("result")
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        return None
    if not isinstance(status, str) or status not in _STATUS_ORDER:
        return None
    if status == "resolved":
        if not isinstance(result, str) or not result.strip() or len(result) > 2000:
            return None
        result = result.encode("utf-8", errors="replace").decode("utf-8")
    else:
        result = ""
    entries = payload.get("messages", [])
    if not isinstance(entries, list) or len(entries) > _MAX_MESSAGES:
        return None
    messages = []
    latest_id = 0
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        message_id, body, sent_at = entry.get("id"), entry.get("body"), entry.get("created_at")
        if (type(message_id) is not int or not latest_id < message_id < 2**53
                or not isinstance(body, str) or not body.strip() or len(body) > 600
                or type(sent_at) is not int or not 0 < sent_at < 253402214400):
            return None
        messages.append(FeedbackMessage(message_id, body.encode("utf-8", errors="replace").decode(), sent_at))
        latest_id = message_id
    return FeedbackTicket(reference, status, result, tuple(messages))


def parse_feedback_ticket(body: bytes) -> FeedbackTicket | None:
    if len(body) > MAX_FEEDBACK_RESPONSE_BYTES:
        return None
    try:
        return _parse_ticket(json.loads(body))
    except (ValueError, RecursionError):
        return None


def feedback_network_enabled() -> bool:
    return bool(FEEDBACK_ORIGIN) and not os.environ.get("BDO_STARTUP_SELF_TEST")


def _feedback_request(path: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(FEEDBACK_ORIGIN + path))
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
    )
    request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
    request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
    return request


def get_feedback_availability(manager: QNetworkAccessManager) -> QNetworkReply:
    request = _feedback_request(FEEDBACK_PATH)
    request.setAttribute(
        QNetworkRequest.Attribute.CacheLoadControlAttribute, QNetworkRequest.CacheLoadControl.AlwaysNetwork,
    )
    request.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
    reply = manager.get(request)
    reply.setReadBufferSize(MAX_FEEDBACK_AVAILABILITY_BYTES + 1)
    return reply


def parse_feedback_availability(body: bytes) -> bool | None:
    if len(body) > MAX_FEEDBACK_AVAILABILITY_BYTES:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    enabled = payload.get("enabled")
    return enabled if type(version) is int and version == 1 and type(enabled) is bool else None


def post_feedback_json(
    manager: QNetworkAccessManager, path: str, payload: dict,
) -> QNetworkReply:
    request = _feedback_request(path)
    request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
    if path == STATUS_PATH:
        request.setRawHeader(b"X-BDO-Feedback-Messages", b"1")
    reply = manager.post(request, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    reply.setReadBufferSize(MAX_FEEDBACK_RESPONSE_BYTES + 1)
    return reply


def _bounded(receipts: dict[str, FeedbackReceipt]) -> dict[str, FeedbackReceipt]:
    ordered = sorted(receipts.values(), key=lambda receipt: receipt.changed_at, reverse=True)
    return {receipt.code: receipt for receipt in ordered[:_MAX_RECEIPTS]}


def _merge_receipt(stored: FeedbackReceipt | None, pending: FeedbackReceipt) -> FeedbackReceipt:
    if stored is None:
        return pending
    if stored.ticket.reference != pending.ticket.reference:
        return stored
    if stored.ticket == pending.ticket:
        # Either process may have opened this exact result since the last write.
        newest = max(stored, pending, key=lambda item: item.changed_at)
        return replace(newest, unread=stored.unread and pending.unread)
    return max(
        stored, pending,
        key=lambda item: (_STATUS_ORDER[item.ticket.status], item.ticket.latest_message_id, item.changed_at),
    )


def _load_receipts(path: Path) -> dict[str, FeedbackReceipt]:
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_STORE_BYTES + 1)
        if len(data) > _MAX_STORE_BYTES:
            return {}
        records = json.loads(data)
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(records, dict) or not isinstance(records.get("receipts"), list):
        return {}
    receipts = {}
    for record in records["receipts"][:_MAX_RECEIPTS]:
        if not isinstance(record, dict):
            continue
        code = record.get("code")
        ticket = _parse_ticket(record.get("ticket"))
        timestamp = record.get("changed_at")
        unread = record.get("unread")
        if (isinstance(code, str) and QUERY_CODE.fullmatch(code) and ticket is not None
                and type(timestamp) is int and 0 < timestamp < 10**20 and type(unread) is bool):
            receipts[code] = FeedbackReceipt(code, ticket, unread, timestamp)
    return _bounded(receipts)


class FeedbackStatusTracker(QObject):
    """Watch active local receipts and preserve unread state across restarts."""

    unread_changed = Signal(int)
    receipts_changed = Signal()

    def __init__(self, parent: QObject | None = None, *, receipt_path: Path | None = None) -> None:
        super().__init__(parent)
        self._path = receipt_path if receipt_path is not None else USER_DATA_DIR / "feedback_receipts.json"
        self._receipts = _load_receipts(self._path)
        self._pending_writes: dict[str, FeedbackReceipt] = {}
        self._write_attempt = 0
        self._write_timer = QTimer(self, singleShot=True)
        self._write_timer.timeout.connect(self._flush_receipts)
        self._manager = QNetworkAccessManager(self)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._poll)
        self._deadline = QTimer(self, singleShot=True, interval=FEEDBACK_TIMEOUT_MS)
        self._deadline.timeout.connect(self._abort)
        self._reply: QNetworkReply | None = None
        self._next_check: dict[str, float] = {}
        self._missing: set[str] = set()
        self._next_request = monotonic() + 5
        self._retry_seconds = _REQUEST_SPACING_SECONDS
        self._schedule()

    @property
    def receipts(self) -> tuple[FeedbackReceipt, ...]:
        return tuple(self._receipts.values())

    @property
    def unread_count(self) -> int:
        return sum(receipt.unread for receipt in self._receipts.values())

    def receipt(self, code: str) -> FeedbackReceipt | None:
        return self._receipts.get(code)

    def observe(
        self, code: str, ticket: FeedbackTicket, *, register: bool = False, shown: bool = False,
    ) -> None:
        if not QUERY_CODE.fullmatch(code) or (not register and code not in self._receipts):
            return

        def change(previous: FeedbackReceipt | None) -> FeedbackReceipt | None:
            current = ticket
            if previous is not None:
                if (previous.ticket.reference != ticket.reference
                        or _STATUS_ORDER[ticket.status] < _STATUS_ORDER[previous.ticket.status]):
                    return previous
                if current.latest_message_id < previous.ticket.latest_message_id:
                    current = replace(current, messages=previous.ticket.messages)
                if previous.ticket == current:
                    return replace(previous, unread=False) if shown and previous.unread else previous
            unread = not shown and (previous is not None or current.status != "submitted" or bool(current.messages))
            return FeedbackReceipt(code, current, unread, time_ns())

        self._update_receipt(code, change)
        if code in self._receipts:
            self._next_check[code] = monotonic() + _POLL_INTERVAL_SECONDS
        self._missing.discard(code)
        self._schedule()

    def mark_seen(self, receipt: FeedbackReceipt) -> None:
        def change(previous: FeedbackReceipt | None) -> FeedbackReceipt | None:
            if previous is not None and previous.ticket == receipt.ticket and previous.unread:
                return replace(previous, unread=False)
            return previous

        self._update_receipt(receipt.code, change)

    def _update_receipt(
        self, code: str, change: Callable[[FeedbackReceipt | None], FeedbackReceipt | None],
    ) -> None:
        previous = self._receipts
        updated = change(previous.get(code))
        if updated is None or updated == previous.get(code):
            return
        self._receipts = _bounded({**previous, code: updated})
        self._pending_writes[code] = updated
        self._pending_writes = {
            key: item for key, item in self._pending_writes.items() if key in self._receipts
        }
        self._write_attempt = 0
        self._flush_receipts(previous)

    def _flush_receipts(self, previous: dict[str, FeedbackReceipt] | None = None) -> None:
        if previous is None:
            previous = self._receipts
        self._write_timer.stop()
        if self._pending_writes:
            lock = QLockFile(str(self._path) + ".lock")
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                if lock.tryLock(0):
                    stored = _load_receipts(self._path)
                    merged = dict(stored)
                    for key, pending in self._pending_writes.items():
                        merged[key] = _merge_receipt(merged.get(key), pending)
                    merged = _bounded(merged)
                    if merged != stored:
                        atomic_write_json(self._path, {"receipts": [item.payload() for item in merged.values()]})
                    self._receipts = merged
                    self._pending_writes.clear()
            except OSError:
                # Keep showing current results while storage is temporarily unavailable.
                pass
            finally:
                if lock.isLocked():
                    lock.unlock()
        if self._pending_writes and self._write_attempt < len(_WRITE_RETRY_DELAYS_MS):
            self._write_timer.start(_WRITE_RETRY_DELAYS_MS[self._write_attempt])
            self._write_attempt += 1

        if self._receipts != previous:
            active = self._receipts.keys()
            self._next_check = {key: value for key, value in self._next_check.items() if key in active}
            self._missing.intersection_update(active)
            self.receipts_changed.emit()
            if self.unread_count != sum(item.unread for item in previous.values()):
                self.unread_changed.emit(self.unread_count)
            self._schedule()

    def _next_pending(self) -> tuple[float, str] | None:
        pending = (
            (self._next_check.get(receipt.code, 0), receipt.code)
            for receipt in self.receipts
            if receipt.ticket.status != "resolved" and receipt.code not in self._missing
        )
        return min(pending, default=None)

    def _schedule(self) -> None:
        self._timer.stop()
        if self._reply is not None or not feedback_network_enabled():
            return
        pending = self._next_pending()
        if pending is not None:
            delay = max(pending[0], self._next_request) - monotonic()
            self._timer.start(max(1, ceil(delay * 1000)))

    def _poll(self) -> None:
        if self._reply is not None or not feedback_network_enabled():
            return
        pending = self._next_pending()
        if pending is None:
            return
        ready, code = pending
        if max(ready, self._next_request) > monotonic():
            self._schedule()
            return
        reply = post_feedback_json(self._manager, STATUS_PATH, {"code": code})
        self._reply = reply
        reply.readyRead.connect(self._check_size)
        reply.finished.connect(lambda: self._finish_poll(code))
        self._deadline.start()

    def _check_size(self) -> None:
        if self._reply is not None and self._reply.bytesAvailable() > MAX_FEEDBACK_RESPONSE_BYTES:
            self._abort()

    def _abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def _finish_poll(self, code: str) -> None:
        reply = self._reply
        self._reply = None
        self._deadline.stop()
        if reply is None:
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ticket = None
        if status == 200 and reply.error() == QNetworkReply.NetworkError.NoError:
            ticket = parse_feedback_ticket(bytes(reply.read(MAX_FEEDBACK_RESPONSE_BYTES + 1)))
        reply.deleteLater()
        if code in self._receipts:
            self._next_check[code] = monotonic() + _POLL_INTERVAL_SECONDS
        if ticket is not None or status == 404:
            self._retry_seconds = _REQUEST_SPACING_SECONDS
        else:
            self._retry_seconds = min(_MAX_RETRY_SECONDS, self._retry_seconds * 2)
        self._next_request = monotonic() + self._retry_seconds
        if status == 404 and code in self._receipts:
            self._missing.add(code)
        elif ticket is not None:
            self.observe(code, ticket)
        self._schedule()
