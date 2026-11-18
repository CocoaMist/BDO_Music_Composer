"""Opt-in usage counting and bounded HTTPS delivery off the GUI thread."""

from __future__ import annotations

import json
import os
from pathlib import Path
from random import randint
from typing import Callable

from PySide6.QtCore import (
    QCoreApplication, QLockFile, QMetaObject, QObject, QThread, QTimer, Qt, QUrl, Signal, Slot,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bdo_music_composer.app.application_metadata import APP_VERSION
from bdo_music_composer.app.usage_telemetry import (
    FEATURES, HELPFULNESS, ISSUES, MAX_COUNT, SERVERS, UsageTelemetryQueue, hardware_buckets,
)
from bdo_music_composer.core.project_paths import USER_DATA_DIR


_FIRST_DELIVERY_MS = 15_000
_DELIVERY_INTERVAL_MS = 60_000
_RETRY_LIMIT_MS = 30 * 60_000
_NETWORK_TIMEOUT_MS = 8_000
_MAX_REPLY_BYTES = 1024
_FLUSH_MS = 1_000


def _usage_endpoint(text: str) -> QUrl:
    url = QUrl(text)
    if (
        url.isValid() and url.scheme() == "https" and url.host()
        and not url.userInfo() and not url.hasQuery() and not url.hasFragment()
        and url.path() == "/api/usage/v1"
    ):
        return url
    return QUrl()


class _UsageWorker(QObject):
    def __init__(
        self,
        endpoint: QUrl,
        path: Path,
        manager_factory: Callable[..., QNetworkAccessManager],
        consent_check: Callable[[], bool] | None,
    ) -> None:
        super().__init__()
        self._endpoint = endpoint
        self._path = path
        self._manager_factory = manager_factory
        self._consent_check = consent_check
        self._manager: QNetworkAccessManager | None = None
        self._lock: QLockFile | None = None
        self._queue: UsageTelemetryQueue | None = None
        self._reply: QNetworkReply | None = None
        self._enabled = False
        self._delivery_armed = False
        self._retry_ms = _DELIVERY_INTERVAL_MS
        self._delivery_timer = QTimer(self, singleShot=True)
        self._delivery_timer.timeout.connect(self._deliver)
        self._deadline = QTimer(self, singleShot=True, interval=_NETWORK_TIMEOUT_MS)
        self._deadline.timeout.connect(self._abort)

    def _lock_queue(self) -> bool:
        if self._lock is not None:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        lock = QLockFile(str(self._path) + ".lock")
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            return False
        self._lock = lock
        return True

    def _unlock_queue(self) -> None:
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def _open_queue(self) -> None:
        if self._queue is None and self._lock_queue():
            self._queue = UsageTelemetryQueue(
                self._path, app_version=APP_VERSION, platform=hardware_buckets(),
            )

    def _has_consent(self) -> bool:
        if self._consent_check is None:
            return True
        try:
            return self._consent_check() is True
        except Exception:
            return False

    @Slot(bool)
    def configure(self, enabled: bool) -> None:
        self._enabled = enabled and self._has_consent()
        if self._enabled:
            self._open_queue()
            self._schedule(_FIRST_DELIVERY_MS)
            return
        self._delivery_timer.stop()
        self._cancel_reply()
        self._queue = None
        self._retry_ms = _DELIVERY_INTERVAL_MS
        if self._path.exists() and self._lock_queue():
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass
        self._unlock_queue()

    @Slot()
    def arm_delivery(self) -> None:
        self._delivery_armed = True
        self._schedule(_FIRST_DELIVERY_MS)

    @Slot(object, object, bool, str, str)
    def record(
        self, features: dict[str, int], issues: dict[str, int], exported: bool,
        helpfulness: str, server: str,
    ) -> None:
        if not self._enabled:
            return
        if not self._has_consent():
            self.configure(False)
            return
        self._open_queue()
        if self._queue is None:
            return
        self._queue.add(features, issues, exported, helpfulness, server)
        try:
            self._queue.save()
        except OSError:
            pass
        self._schedule(_DELIVERY_INTERVAL_MS)

    def _schedule(self, delay_ms: int) -> None:
        if (
            self._enabled and self._delivery_armed and self._queue is not None
            and self._reply is None and not self._delivery_timer.isActive()
        ):
            self._delivery_timer.start(delay_ms)

    def _retry(self) -> None:
        delay = min(_RETRY_LIMIT_MS, self._retry_ms + randint(0, self._retry_ms // 8))
        self._retry_ms = min(_RETRY_LIMIT_MS, 2 * self._retry_ms)
        self._schedule(delay)

    def _deliver(self) -> None:
        if not (self._enabled and self._delivery_armed) or self._queue is None or self._reply is not None:
            return
        if not self._has_consent():
            self.configure(False)
            return
        try:
            prepared = self._queue.prepare()
        except OSError:
            self._retry()
            return
        if prepared is None:
            return
        # Another running window can revoke settings consent. Read the shared
        # setting again after any local queue work and before posting bytes.
        if not self._has_consent():
            self.configure(False)
            return
        if self._manager is None:
            self._manager = self._manager_factory(self)
        batch_id, body = prepared
        request = QNetworkRequest(self._endpoint)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        request.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
        request.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)
        reply = self._manager.post(request, body)
        self._reply = reply
        reply.setReadBufferSize(_MAX_REPLY_BYTES + 1)
        reply.readyRead.connect(lambda: self._limit_reply(reply))
        reply.finished.connect(lambda: self._finished(reply, batch_id))
        self._deadline.start()

    def _limit_reply(self, reply: QNetworkReply) -> None:
        if self._reply is reply and reply.bytesAvailable() > _MAX_REPLY_BYTES:
            reply.abort()

    def _abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def _cancel_reply(self) -> None:
        self._deadline.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _finished(self, reply: QNetworkReply, batch_id: str) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        self._deadline.stop()
        if not self._has_consent():
            reply.deleteLater()
            self.configure(False)
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        acknowledged = False
        if (
            reply.error() == QNetworkReply.NetworkError.NoError
            and type(status) is int and 200 <= status < 300
        ):
            raw = bytes(reply.read(_MAX_REPLY_BYTES + 1))
            if len(raw) <= _MAX_REPLY_BYTES:
                try:
                    payload = json.loads(raw)
                except (ValueError, RecursionError):
                    payload = None
                acknowledged = isinstance(payload, dict) and payload.get("batch_id") == batch_id
        reply.deleteLater()
        if acknowledged and self._queue is not None:
            try:
                if self._queue.acknowledge(batch_id):
                    self._retry_ms = _DELIVERY_INTERVAL_MS
                    self._schedule(_DELIVERY_INTERVAL_MS)
                    return
            except OSError:
                pass
        self._retry()

    @Slot()
    def stop(self) -> None:
        self._delivery_timer.stop()
        self._cancel_reply()
        if self._queue is not None:
            if not self._has_consent():
                self.configure(False)
                return
            try:
                self._queue.save()
            except OSError:
                pass
        self._unlock_queue()


class UsageTelemetryQt(QObject):
    """The application's GUI records counters; the worker owns disk and HTTPS."""

    _configured = Signal(bool)
    _armed = Signal()
    _recorded = Signal(object, object, bool, str, str)

    def __init__(
        self, parent: QObject | None = None, *, endpoint: str,
        enabled: bool = False, server: str = "", queue_path: Path | None = None,
        manager_factory: Callable[..., QNetworkAccessManager] = QNetworkAccessManager,
        consent_check: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._endpoint = _usage_endpoint(endpoint)
        self._path = queue_path if queue_path is not None else USER_DATA_DIR / "usage-telemetry-v1.json"
        self._manager_factory = manager_factory
        self._consent_check = consent_check
        self._thread: QThread | None = None
        self._worker: _UsageWorker | None = None
        self._enabled = False
        self._started = False
        self._stopped = False
        self._server = server if isinstance(server, str) and server in SERVERS else ""
        self._features: dict[str, int] = {}
        self._issues: dict[str, int] = {}
        self._helpfulness = ""
        self._exported = False
        self._flush_timer = QTimer(self, singleShot=True, interval=_FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._available = not self._endpoint.isEmpty() and not os.environ.get("BDO_STARTUP_SELF_TEST")
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self.configure(enabled=enabled, server=server)

    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        worker = _UsageWorker(self._endpoint, self._path, self._manager_factory, self._consent_check)
        worker.moveToThread(thread)
        thread.finished.connect(worker.deleteLater)
        self._configured.connect(worker.configure, Qt.ConnectionType.QueuedConnection)
        self._armed.connect(worker.arm_delivery, Qt.ConnectionType.QueuedConnection)
        self._recorded.connect(worker.record, Qt.ConnectionType.QueuedConnection)
        self._thread, self._worker = thread, worker
        thread.start()
        if self._started:
            self._armed.emit()

    def configure(self, *, enabled: bool, server: str = "") -> None:
        if not self._available or self._stopped:
            return
        enabled = enabled is True
        new_server = server if isinstance(server, str) and server in SERVERS else ""
        if enabled == self._enabled:
            if enabled and new_server != self._server:
                self._flush()
            elif not enabled and self._thread is None and self._path.exists():
                self._ensure_worker()
                self._configured.emit(False)
            if enabled:
                self._configured.emit(True)
            self._server = new_server
            return
        self._enabled = enabled
        self._server = new_server
        if enabled:
            self._ensure_worker()
            self._configured.emit(True)
            self.record("session")
        else:
            self._clear_delta()
            self._configured.emit(False)

    @Slot()
    def start(self) -> None:
        """Arm delivery after the main window has first painted."""
        if self._stopped or self._started:
            return
        self._started = True
        if self._thread is not None:
            self._armed.emit()

    def _changed(self) -> None:
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def record(self, feature: str) -> None:
        if self._enabled and isinstance(feature, str) and feature in FEATURES:
            self._features[feature] = min(MAX_COUNT, self._features.get(feature, 0) + 1)
            self._exported |= feature == "export"
            self._changed()

    def record_export(self) -> None:
        self.record("export")

    def record_issue(self, issue: str) -> None:
        if self._enabled and isinstance(issue, str) and issue in ISSUES:
            self._issues[issue] = min(MAX_COUNT, self._issues.get(issue, 0) + 1)
            self._changed()

    def record_helpfulness(self, helpfulness: str) -> None:
        if self._enabled and isinstance(helpfulness, str) and helpfulness in HELPFULNESS:
            self._helpfulness = helpfulness
            self._changed()

    def _clear_delta(self) -> None:
        self._flush_timer.stop()
        self._features = {}
        self._issues = {}
        self._helpfulness = ""
        self._exported = False

    def _flush(self) -> None:
        if self._enabled and (self._features or self._issues or self._exported or self._helpfulness):
            self._recorded.emit(self._features, self._issues, self._exported, self._helpfulness, self._server)
        self._clear_delta()

    @Slot()
    def shutdown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._flush()
        self._enabled = False
        if self._thread is not None and self._worker is not None:
            QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
            self._thread.quit()
            self._thread.wait()
