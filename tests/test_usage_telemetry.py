"""Telemetry consent, payload privacy, and replay tests. No network is used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from bdo_music_composer.app.usage_telemetry import MAX_COUNT, UsageTelemetryQueue
from bdo_music_composer.ui import usage_telemetry_qt as qt


_PLATFORM = {"os": "windows11", "cpu_threads": "9-16", "ram_gib": "32-63"}


class QueueTests(unittest.TestCase):
    def test_restarts_retry_identical_sealed_batch_and_only_remove_after_matching_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            queue = UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM)
            queue.add({"session": 1, "preview": 2}, {}, False, "", "")
            queue.save()
            reopened = UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM)
            sealed = reopened.prepare()
            reopened.add({"export": 1}, {"import_failed": 1}, True, "helpful", "cn")
            reopened.save()
            restarted = UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM)
            self.assertEqual(restarted.prepare(), sealed)
            self.assertFalse(restarted.acknowledge("e" * 32))
            self.assertTrue(restarted.acknowledge(sealed[0]))
            second = json.loads(restarted.prepare()[1])
            first = json.loads(sealed[1])
            self.assertEqual(first["installation_id"], second["installation_id"])
            self.assertEqual(first["features"], {"session": 1, "preview": 2})
            self.assertNotIn("server", first)
            self.assertNotEqual(first["batch_id"], second["batch_id"])
            self.assertEqual(second["features"], {"export": 1})
            self.assertEqual(second["issues"], {"import_failed": 1})
            self.assertEqual(second["helpfulness"], "helpful")
            self.assertEqual(second["server"], "cn")
            self.assertIs(second["exported"], True)

    def test_non_allowlisted_content_is_dropped_even_from_tampered_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            queue = UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM)
            queue.add({"private_project_path": 1}, {}, False, "", "")
            self.assertIsNone(queue.prepare())
            queue.add({"preview": MAX_COUNT}, {}, False, "private message", "my home")
            queue.add({"preview": 1}, {}, False, "", "")
            _, body = queue.prepare()
            payload = json.loads(body)
            self.assertEqual(payload["features"], {"preview": MAX_COUNT})
            self.assertNotIn("helpfulness", payload)
            self.assertNotIn("server", payload)
            stored = json.loads(path.read_bytes())
            stored["pending"][0]["path"] = "D:/private/song.mid"
            path.write_text(json.dumps(stored), encoding="utf-8")
            self.assertIsNone(UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM).prepare())

    def test_bounded_queue_keeps_an_in_flight_id_under_backlog_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            queue = UsageTelemetryQueue(path, app_version="1.2.3", platform=_PLATFORM)
            queue.add({"session": 1}, {}, False, "", "")
            first = queue.prepare()
            for index in range(50):
                queue.add({"preview": 1}, {}, False, "", "cn" if index % 2 else "eu")
            queue.save()
            stored = json.loads(path.read_bytes())
            self.assertEqual(len(stored["pending"]), 24)
            self.assertLess(path.stat().st_size, 64 * 1024)
            self.assertEqual(queue.prepare(), first)


class _Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, parent: QObject, ack: bytes) -> None:
        super().__init__(parent)
        self.ack = ack
        self.aborted = False

    def attribute(self, attribute):
        return 200

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def setReadBufferSize(self, size: int) -> None:
        pass

    def bytesAvailable(self) -> int:
        return len(self.ack)

    def read(self, size: int) -> bytes:
        return self.ack[:size]

    def abort(self) -> None:
        self.aborted = True


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _until(self, predicate) -> None:
        deadline = monotonic() + 3
        while not predicate() and monotonic() < deadline:
            self.app.processEvents()
            sleep(.005)
        self.assertTrue(predicate())

    def test_consent_delays_delivery_retries_stable_body_and_purges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            requests = []
            endpoint = "https://usage.test.invalid/api/usage/v1"

            class FakeManager(QObject):
                def post(self, request, body):
                    payload = json.loads(body)
                    requests.append((request, bytes(body)))
                    received = "f" * 32 if len(requests) == 1 else payload["batch_id"]
                    reply = _Reply(self, json.dumps({"batch_id": received}).encode("ascii"))
                    QTimer.singleShot(0, reply, reply.finished.emit)
                    return reply

            with (
                patch.dict(os.environ, {"BDO_STARTUP_SELF_TEST": ""}),
                patch.multiple(qt, _FLUSH_MS=10, _FIRST_DELIVERY_MS=20, _DELIVERY_INTERVAL_MS=20),
            ):
                bridge = qt.UsageTelemetryQt(endpoint=endpoint, queue_path=path, manager_factory=FakeManager)
                try:
                    bridge.record("preview")
                    self.app.processEvents()
                    self.assertFalse(path.exists())
                    bridge.configure(enabled=True, server="cn")
                    bridge.record_export()
                    self._until(path.exists)
                    self.assertFalse(requests)
                    bridge.start()
                    self._until(lambda: len(requests) >= 2)
                    self.assertEqual(requests[0][1], requests[1][1])
                    request, body = requests[0]
                    self.assertEqual(request.url().toString(), endpoint)
                    self.assertEqual(
                        request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute),
                        QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
                    )
                    self.assertEqual(json.loads(body)["features"], {"session": 1, "export": 1})
                    self._until(lambda: json.loads(path.read_bytes())["pending"] == [])
                    bridge.configure(enabled=False)
                    self._until(lambda: not path.exists())
                    count = len(requests)
                    bridge.record("preview")
                    bridge.record_helpfulness("neutral")
                    self.app.processEvents()
                    self.assertEqual(len(requests), count)
                    self.assertFalse(path.exists())
                finally:
                    bridge.shutdown()

    def test_startup_self_test_never_creates_or_transmits_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"BDO_STARTUP_SELF_TEST": "1"}):
            path = Path(directory) / "queue.json"
            bridge = qt.UsageTelemetryQt(
                endpoint="https://usage.test.invalid/api/usage/v1", queue_path=path, enabled=True,
            )
            bridge.start()
            bridge.record_export()
            bridge.shutdown()
            self.assertFalse(path.exists())

    def test_external_consent_revocation_purges_without_starting_http(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            config = Path(directory) / "shared-consent"
            config.write_text("on", encoding="ascii")
            managers = []

            def manager_factory(parent):
                managers.append(parent)
                raise AssertionError("revoked settings must never initialize the HTTP manager")

            with (
                patch.dict(os.environ, {"BDO_STARTUP_SELF_TEST": ""}),
                patch.multiple(qt, _FLUSH_MS=10, _FIRST_DELIVERY_MS=20),
            ):
                bridge = qt.UsageTelemetryQt(
                    endpoint="https://usage.test.invalid/api/usage/v1",
                    queue_path=path, enabled=True, manager_factory=manager_factory,
                    consent_check=lambda: config.read_text(encoding="ascii") == "on",
                )
                try:
                    self._until(path.exists)
                    config.write_text("off", encoding="ascii")
                    bridge.start()
                    self._until(lambda: not path.exists())
                    self.assertEqual(managers, [])
                finally:
                    bridge.shutdown()

    def test_opt_out_aborts_an_active_request_and_discards_late_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.json"
            replies = []

            class LateReply(_Reply):
                def abort(self):
                    super().abort()
                    self.finished.emit()

            class FakeManager(QObject):
                def post(self, request, body):
                    reply = LateReply(self, json.dumps({"batch_id": json.loads(body)["batch_id"]}).encode("ascii"))
                    replies.append(reply)
                    return reply

            with (
                patch.dict(os.environ, {"BDO_STARTUP_SELF_TEST": ""}),
                patch.multiple(qt, _FLUSH_MS=10, _FIRST_DELIVERY_MS=20, _DELIVERY_INTERVAL_MS=20),
            ):
                bridge = qt.UsageTelemetryQt(
                    endpoint="https://usage.test.invalid/api/usage/v1",
                    queue_path=path, enabled=True, manager_factory=FakeManager,
                )
                try:
                    bridge.start()
                    self._until(lambda: bool(replies))
                    bridge.configure(enabled=False)
                    self._until(lambda: replies[0].aborted and not path.exists())
                    self.assertEqual(len(replies), 1)
                finally:
                    bridge.shutdown()


if __name__ == "__main__":
    unittest.main()
