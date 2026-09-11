from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bdo_music_composer.ui.self_update_qt import (
    CHECK_INTERVAL_SECONDS,
    FAILURE_RETRY_SECONDS,
    SelfUpdateController,
    UpdateDownloadWorker,
    UpdateNetworkError,
    _download_artifact_attempt,
    _validate_network_url,
)
from bdo_music_composer.update.install import (
    CACHE_RETENTION_SECONDS,
    READY_NAME,
    UpdateInstallError,
    _load_ready_update,
    apply_update_plan,
    cleanup_committed_updates,
    create_install_plan,
    file_sha256,
)
from bdo_music_composer.update.manifest import EXPECTED_EXECUTABLE_NAME
from bdo_music_composer.app.application_metadata import (
    UPDATE_APP_ID,
    UPDATE_PROTOCOL_VERSION,
)
from bdo_music_composer.update.storage import has_sufficient_update_space


class _Response:
    def __init__(self, url: str, status: int, headers: dict[str, str], chunks):
        self._url = url
        self.status = status
        self.headers = headers
        self._chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self._url

    def read1(self, _size: int) -> bytes:
        value = next(self._chunks, b"")
        if isinstance(value, BaseException):
            raise value
        return value


class _SequenceOpener:
    def __init__(self, responses: list[_Response]):
        self.responses = iter(responses)
        self.ranges: list[str | None] = []

    def open(self, request, **_kwargs):
        self.ranges.append(request.get_header("Range"))
        return next(self.responses)


class _Artifact:
    filename = EXPECTED_EXECUTABLE_NAME

    def __init__(self, payload: bytes):
        self.size = len(payload)
        self.sha256 = hashlib.sha256(payload).hexdigest()
        self._urls = {
            "github": "https://github.com/example/repo/releases/download/v2/app.exe",
            "gitee": "https://gitee.com/example/repo/releases/download/v2/app.exe",
        }

    def url_for(self, source: str) -> str | None:
        return self._urls.get(source)


class SelfUpdateNetworkReliabilityTests(unittest.TestCase):
    def test_gitee_raw_redirect_host_is_exactly_allowlisted(self) -> None:
        _validate_network_url(
            "https://raw.giteeusercontent.com/owner/repo/raw/master/manifest.json"
        )
        with self.assertRaisesRegex(UpdateNetworkError, "unsafe update URL"):
            _validate_network_url(
                "https://raw.giteeusercontent.com.attacker.example/manifest.json"
            )

    def test_transient_failure_retries_in_one_hour_not_one_day(self) -> None:
        config: dict[str, object] = {}
        saves: list[bool] = []
        controller = SelfUpdateController(config, lambda: saves.append(True))
        with patch("bdo_music_composer.ui.self_update_qt.time.time", return_value=100_000):
            controller._on_failed("temporary network failure")

        preferences = config["updates"]
        self.assertEqual(
            preferences["last_check"],
            100_000 - CHECK_INTERVAL_SECONDS + FAILURE_RETRY_SECONDS,
        )
        self.assertEqual(saves, [True])

    def test_mirror_handoff_resumes_the_existing_partial_download(self) -> None:
        payload = b"abcdef"
        first = _Response(
            "https://github.com/example/repo/releases/download/v2/app.exe",
            200,
            {"Content-Length": "6"},
            [b"abc", OSError("connection lost")],
        )
        second = _Response(
            "https://gitee.com/example/repo/releases/download/v2/app.exe",
            206,
            {"Content-Length": "3", "Content-Range": "bytes 3-5/6"},
            [b"def", b""],
        )
        opener = _SequenceOpener([first, second])
        manifest = SimpleNamespace(version="2.0.0", artifact=_Artifact(payload))
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("bdo_music_composer.ui.self_update_qt.UPDATE_ROOT", Path(directory)),
            patch("bdo_music_composer.ui.self_update_qt._opener", return_value=opener),
            patch(
                "bdo_music_composer.ui.self_update_qt.has_sufficient_update_space",
                return_value=True,
            ),
        ):
            prepared = UpdateDownloadWorker({})._download(manifest, "github")

            self.assertEqual(prepared.executable.read_bytes(), payload)
            self.assertEqual(prepared.source, "gitee")
            self.assertEqual(opener.ranges, [None, "bytes=3-"])

    def test_range_ignored_by_server_restarts_instead_of_appending(self) -> None:
        payload = b"replacement"
        response = _Response(
            "https://github.com/example/repo/releases/download/v2/app.exe",
            200,
            {"Content-Length": str(len(payload))},
            [payload, b""],
        )
        opener = _SequenceOpener([response])
        cancelled = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / ".app.part"
            partial.write_bytes(b"old-prefix")
            with (
                patch("bdo_music_composer.ui.self_update_qt._opener", return_value=opener),
                patch(
                    "bdo_music_composer.ui.self_update_qt.has_sufficient_update_space",
                    return_value=True,
                ),
            ):
                _download_artifact_attempt(
                    "https://github.com/example/repo/releases/download/v2/app.exe",
                    partial,
                    len(payload),
                    cancelled,
                    lambda _downloaded, _total: None,
                )

            self.assertEqual(partial.read_bytes(), payload)
            self.assertEqual(opener.ranges, ["bytes=10-"])

    def test_disk_space_guard_includes_reserve(self) -> None:
        with patch(
            "bdo_music_composer.update.storage.filesystem_free_bytes",
            return_value=100,
        ):
            self.assertTrue(has_sufficient_update_space(".", 60, reserve_bytes=40))
            self.assertFalse(has_sufficient_update_space(".", 61, reserve_bytes=40))


class SelfUpdateStorageReliabilityTests(unittest.TestCase):
    def test_ready_record_rejects_invalid_version_digest_and_external_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "updates"
            version = root / "2.0.0"
            version.mkdir(parents=True)
            staged = version / EXPECTED_EXECUTABLE_NAME
            staged.write_bytes(b"ready")
            ready_path = root / READY_NAME
            valid = {
                "schema_version": 1,
                "app_id": UPDATE_APP_ID,
                "protocol": UPDATE_PROTOCOL_VERSION,
                "version": "2.0.0",
                "sha256": "a" * 64,
                "staged_executable": str(staged),
            }
            ready_path.write_text(json.dumps(valid), encoding="utf-8")
            loaded, loaded_staged = _load_ready_update(ready_path, root)
            self.assertEqual(loaded["version"], "2.0.0")
            self.assertEqual(loaded_staged, staged.resolve())

            cases = (
                {**valid, "version": "not-a-version"},
                {**valid, "sha256": "g" * 64},
                {**valid, "staged_executable": str(Path(directory) / EXPECTED_EXECUTABLE_NAME)},
            )
            (Path(directory) / EXPECTED_EXECUTABLE_NAME).write_bytes(b"external")
            for payload in cases:
                with self.subTest(payload=payload):
                    ready_path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(UpdateInstallError):
                        _load_ready_update(ready_path, root)

    def test_install_space_failure_keeps_the_old_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "installed" / EXPECTED_EXECUTABLE_NAME
            staged = root / "updates" / EXPECTED_EXECUTABLE_NAME
            target.parent.mkdir()
            staged.parent.mkdir()
            target.write_bytes(b"old")
            staged.write_bytes(b"new")
            plan, token = create_install_plan(
                staged,
                version="2.0.0",
                sha256=file_sha256(staged),
                target_executable=target,
                parent_pid=0,
            )
            with (
                patch(
                    "bdo_music_composer.update.install.has_sufficient_update_space",
                    return_value=False,
                ),
                patch("bdo_music_composer.update.install.subprocess.Popen") as launch,
            ):
                result = apply_update_plan(
                    plan,
                    token,
                    running_executable=staged,
                    launch=False,
                )

            self.assertEqual(result, 2)
            self.assertEqual(target.read_bytes(), b"old")
            launch.assert_not_called()

    def test_cleanup_removes_stale_orphans_but_keeps_ready_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protected = root / "2.0.0"
            orphan = root / "1.9.0"
            protected.mkdir()
            orphan.mkdir()
            staged = protected / EXPECTED_EXECUTABLE_NAME
            staged.write_bytes(b"ready")
            (orphan / f".{EXPECTED_EXECUTABLE_NAME}.part").write_bytes(b"partial")
            old = time.time() - CACHE_RETENTION_SECONDS - 60
            for path in (staged, orphan / f".{EXPECTED_EXECUTABLE_NAME}.part", protected, orphan):
                os.utime(path, (old, old))
            (root / READY_NAME).write_text(
                json.dumps({
                    "schema_version": 1,
                    "app_id": UPDATE_APP_ID,
                    "protocol": UPDATE_PROTOCOL_VERSION,
                    "version": "2.0.0",
                    "sha256": "a" * 64,
                    "staged_executable": str(staged),
                }),
                encoding="utf-8",
            )

            cleanup_committed_updates(root)

            self.assertTrue(protected.is_dir())
            self.assertFalse(orphan.exists())
            self.assertTrue((root / READY_NAME).is_file())

            (root / READY_NAME).write_text("not-json", encoding="utf-8")
            cleanup_committed_updates(root)
            self.assertFalse((root / READY_NAME).exists())


if __name__ == "__main__":
    unittest.main()
