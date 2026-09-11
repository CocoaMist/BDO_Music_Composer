"""Background signed-channel check, download, and exit-time update handoff."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import time
from typing import Callable, Mapping, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import QObject, QThread, Signal

from bdo_music_composer.app.application_metadata import (
    APP_NAME,
    APP_VERSION,
    GITHUB_UPDATE_CHANNEL_URL,
    GITEE_UPDATE_CHANNEL_URL,
)
from bdo_music_composer.app.update_check import SemanticVersion
from bdo_music_composer.update.install import (
    UPDATE_ROOT,
    file_sha256,
    record_ready_update,
)
from bdo_music_composer.update.manifest import (
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    ManifestError,
    UpdateManifest,
    parse_signed_manifest,
)
from bdo_music_composer.update.storage import has_sufficient_update_space
from bdo_music_composer.update.preferences import update_preferences


CHECK_INTERVAL_SECONDS = 24 * 60 * 60
FAILURE_RETRY_SECONDS = 60 * 60
NETWORK_TIMEOUT_SECONDS = 8.0
DOWNLOAD_CHUNK_BYTES = 256 * 1024
INSUFFICIENT_DISK_SPACE_MESSAGE = "insufficient disk space for update"
_CONTENT_RANGE_RE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$", re.ASCII)
_ALLOWED_NETWORK_HOSTS = frozenset({
    "raw.githubusercontent.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "gitee.com",
    "giteeusercontent.com",
    "raw.giteeusercontent.com",
})


class UpdateNetworkError(RuntimeError):
    pass


class UpdateStorageError(UpdateNetworkError):
    pass


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https" or urlsplit(newurl).hostname not in _ALLOWED_NETWORK_HOSTS:
            raise UpdateNetworkError("unsafe update redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_network_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_NETWORK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise UpdateNetworkError("unsafe update URL")


def _opener():
    return build_opener(_SafeRedirectHandler())


def _request(url: str, *, range_start: int = 0) -> Request:
    _validate_network_url(url)
    headers = {
        "Accept": "application/octet-stream",
        "Accept-Encoding": "identity",
        "User-Agent": f"{APP_NAME.replace(' ', '-')}/{APP_VERSION}",
    }
    if range_start > 0:
        headers["Range"] = f"bytes={int(range_start)}-"
    return Request(
        url,
        headers=headers,
        method="GET",
    )


def _fetch_bounded(url: str, limit: int, cancelled: threading.Event) -> bytes:
    try:
        with _opener().open(_request(url), timeout=NETWORK_TIMEOUT_SECONDS) as response:
            _validate_network_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise UpdateNetworkError("update response is too large")
            payload = bytearray()
            while not cancelled.is_set():
                reader = getattr(response, "read1", None) or response.read
                chunk = reader(min(64 * 1024, limit + 1 - len(payload)))
                if not chunk:
                    return bytes(payload)
                payload.extend(chunk)
                if len(payload) > limit:
                    raise UpdateNetworkError("update response is too large")
    except (HTTPError, URLError, OSError, ssl.SSLError, ValueError) as exc:
        raise UpdateNetworkError("update request failed") from exc
    raise UpdateNetworkError("update request cancelled")


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    manifest: UpdateManifest
    executable: Path
    source: str


def _is_linklike(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", lambda: False)
    return path.is_symlink() or bool(is_junction())


def _validate_update_file(path: Path) -> None:
    if not path.exists() and not _is_linklike(path):
        return
    if _is_linklike(path) or not path.is_file() or path.stat().st_nlink != 1:
        raise UpdateNetworkError("update cache file is unsafe")


def _validate_update_directory(path: Path, root: Path) -> None:
    if _is_linklike(path) or not path.is_dir():
        raise UpdateNetworkError("update cache directory is unsafe")
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise UpdateNetworkError("update cache directory is unsafe") from exc
    if resolved_path.parent != resolved_root:
        raise UpdateNetworkError("update cache directory is unsafe")


def _partial_offset(partial: Path, expected_size: int) -> int:
    _validate_update_file(partial)
    if not partial.is_file():
        return 0
    size = int(partial.stat().st_size)
    if size < 0 or size > expected_size:
        partial.unlink(missing_ok=True)
        return 0
    return size


def _response_write_plan(
    response,
    *,
    requested_offset: int,
    expected_size: int,
) -> tuple[int, str]:
    raw_status = getattr(response, "status", None)
    status = int(raw_status if raw_status is not None else response.getcode())
    length_text = response.headers.get("Content-Length")
    length = int(length_text) if length_text is not None else None
    if status == 200:
        if length is not None and length != expected_size:
            raise UpdateNetworkError("artifact size header mismatch")
        return 0, "wb"
    if status != 206:
        raise UpdateNetworkError("artifact response status is invalid")
    match = _CONTENT_RANGE_RE.fullmatch(
        str(response.headers.get("Content-Range", ""))
    )
    if match is None:
        raise UpdateNetworkError("artifact content range is invalid")
    start, end, total = (int(value) for value in match.groups())
    if (
        start != requested_offset
        or end < start
        or end >= expected_size
        or total != expected_size
        or (length is not None and length != end - start + 1)
    ):
        raise UpdateNetworkError("artifact content range is invalid")
    return start, "ab" if start else "wb"


def _download_artifact_attempt(
    url: str,
    partial: Path,
    expected_size: int,
    cancelled: threading.Event,
    progress: Callable[[int, int], None],
) -> None:
    offset = _partial_offset(partial, expected_size)
    if not has_sufficient_update_space(partial.parent, expected_size - offset):
        raise UpdateStorageError(f"{INSUFFICIENT_DISK_SPACE_MESSAGE}: download")
    with _opener().open(
        _request(url, range_start=offset),
        timeout=NETWORK_TIMEOUT_SECONDS,
    ) as response:
        _validate_network_url(response.geturl())
        downloaded, mode = _response_write_plan(
            response,
            requested_offset=offset,
            expected_size=expected_size,
        )
        if downloaded == 0 and not has_sufficient_update_space(
            partial.parent, expected_size
        ):
            raise UpdateStorageError(f"{INSUFFICIENT_DISK_SPACE_MESSAGE}: download")
        with partial.open(mode) as stream:
            progress(downloaded, expected_size)
            while not cancelled.is_set():
                reader = getattr(response, "read1", None) or response.read
                chunk = reader(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > expected_size:
                    raise UpdateNetworkError("artifact is too large")
                stream.write(chunk)
                progress(downloaded, expected_size)
            stream.flush()
            os.fsync(stream.fileno())
    if cancelled.is_set():
        raise UpdateNetworkError("update download cancelled")


class UpdateDownloadWorker(QThread):
    checking = Signal()
    available = Signal(object, str)
    progress = Signal(int, int)
    ready = Signal(object)
    current = Signal()
    failed = Signal(str)

    def __init__(self, preferences: Mapping[str, object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.preferences = dict(preferences)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _source_order(self) -> list[tuple[str, str]]:
        sources = {
            "github": GITHUB_UPDATE_CHANNEL_URL,
            "gitee": GITEE_UPDATE_CHANNEL_URL,
        }
        selected = str(self.preferences.get("source", "auto"))
        if selected in sources:
            return [(selected, sources[selected])]
        last = str(self.preferences.get("last_source", ""))
        order = [last] if last in sources else []
        order.extend(name for name in ("gitee", "github") if name not in order)
        return [(name, sources[name]) for name in order]

    def _discover(self) -> tuple[UpdateManifest, str]:
        errors: list[str] = []
        candidates: list[tuple[UpdateManifest, str]] = []
        for source, manifest_url in self._source_order():
            if self._cancelled.is_set():
                break
            try:
                payload = _fetch_bounded(manifest_url, MAX_MANIFEST_BYTES, self._cancelled)
                signature = _fetch_bounded(
                    f"{manifest_url}.sig",
                    MAX_SIGNATURE_BYTES,
                    self._cancelled,
                )
                candidates.append((parse_signed_manifest(payload, signature), source))
            except (ManifestError, UpdateNetworkError) as exc:
                errors.append(f"{source}:{type(exc).__name__}")
        if candidates:
            # A lagging mirror is normal. Select the highest signed SemVer,
            # preserving source preference when both mirrors agree.
            return max(candidates, key=lambda item: item[0].version)
        raise UpdateNetworkError(",".join(errors) or "no update source available")

    def _download(self, manifest: UpdateManifest, first_source: str) -> PreparedUpdate:
        artifact = manifest.artifact
        sources = [first_source] + [name for name in ("gitee", "github") if name != first_source]
        target_dir = UPDATE_ROOT / str(manifest.version)
        target_dir.mkdir(parents=True, exist_ok=True)
        _validate_update_directory(target_dir, UPDATE_ROOT)
        final_path = target_dir / artifact.filename
        _validate_update_file(final_path)
        if final_path.is_file() and final_path.stat().st_size == artifact.size:
            if file_sha256(final_path) == artifact.sha256:
                if not has_sufficient_update_space(
                    Path(sys.executable).parent, artifact.size
                ):
                    raise UpdateStorageError(
                        f"{INSUFFICIENT_DISK_SPACE_MESSAGE}: installation"
                    )
                return PreparedUpdate(manifest, final_path, first_source)
        final_path.unlink(missing_ok=True)
        partial = target_dir / f".{artifact.filename}.part"
        if _partial_offset(partial, artifact.size) == artifact.size:
            if file_sha256(partial) == artifact.sha256:
                if not has_sufficient_update_space(
                    Path(sys.executable).parent, artifact.size
                ):
                    raise UpdateStorageError(
                        f"{INSUFFICIENT_DISK_SPACE_MESSAGE}: installation"
                    )
                os.replace(partial, final_path)
                return PreparedUpdate(manifest, final_path, first_source)
            partial.unlink(missing_ok=True)
        errors: list[str] = []
        for source in sources:
            url = artifact.url_for(source)
            if url is None or self._cancelled.is_set():
                continue
            try:
                _download_artifact_attempt(
                    url,
                    partial,
                    artifact.size,
                    self._cancelled,
                    self.progress.emit,
                )
                if partial.stat().st_size != artifact.size:
                    raise UpdateNetworkError("artifact download is incomplete")
                if file_sha256(partial) != artifact.sha256:
                    partial.unlink(missing_ok=True)
                    raise UpdateNetworkError("artifact integrity check failed")
                if not has_sufficient_update_space(
                    Path(sys.executable).parent, artifact.size
                ):
                    raise UpdateStorageError(
                        f"{INSUFFICIENT_DISK_SPACE_MESSAGE}: installation"
                    )
                os.replace(partial, final_path)
                return PreparedUpdate(manifest, final_path, source)
            except UpdateStorageError:
                raise
            except (HTTPError, URLError, OSError, ssl.SSLError, ValueError, UpdateNetworkError) as exc:
                errors.append(f"{source}:{type(exc).__name__}")
        raise UpdateNetworkError(",".join(errors) or "no artifact mirror available")

    def run(self) -> None:
        self.checking.emit()
        try:
            manifest, source = self._discover()
            local = SemanticVersion.parse(APP_VERSION)
            highest_text = str(self.preferences.get("highest_version", ""))
            highest = SemanticVersion.parse(highest_text) if highest_text else local
            if manifest.version < highest:
                raise UpdateNetworkError("signed channel attempted a version rollback")
            if manifest.version <= local:
                self.current.emit()
                return
            self.available.emit(manifest, source)
            if not bool(self.preferences.get("auto_download", True)):
                return
            self.ready.emit(self._download(manifest, source))
        except (UpdateNetworkError, ManifestError, ValueError) as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc))


class SelfUpdateController(QObject):
    checking = Signal()
    available = Signal(object, str)
    progress = Signal(int, int)
    ready = Signal(object)
    current = Signal()
    failed = Signal(str)

    def __init__(
        self,
        config: MutableMapping[str, object],
        save_config: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._save_config = save_config
        self.worker: UpdateDownloadWorker | None = None
        self.prepared: PreparedUpdate | None = None

    @property
    def supported(self) -> bool:
        return sys.platform == "win32" and bool(getattr(sys, "frozen", False))

    def start(self, *, manual: bool = False) -> bool:
        if self.worker is not None and self.worker.isRunning():
            return False
        preferences = update_preferences(self.config)
        if not self.supported:
            if manual:
                self.failed.emit("self-update is available only in the packaged Windows application")
            return False
        if os.environ.get("BDO_STARTUP_SELF_TEST"):
            return False
        if not manual:
            if not preferences["enabled"]:
                return False
            if int(time.time()) - int(preferences["last_check"]) < CHECK_INTERVAL_SECONDS:
                return False
        worker = UpdateDownloadWorker(preferences, self)
        self.worker = worker
        worker.checking.connect(self.checking)
        worker.available.connect(self._on_available)
        worker.available.connect(self.available)
        worker.progress.connect(self.progress)
        worker.ready.connect(self._on_ready)
        worker.ready.connect(self.ready)
        worker.current.connect(self._on_current)
        worker.current.connect(self.current)
        worker.failed.connect(self._on_failed)
        worker.failed.connect(self.failed)
        worker.finished.connect(self._worker_finished)
        worker.start()
        return True

    def _record_check(self, *, source: str = "", version: str = "") -> None:
        preferences = update_preferences(self.config)
        preferences["last_check"] = int(time.time())
        if source:
            preferences["last_source"] = source
        if version:
            preferences["highest_version"] = version
        self.config["updates"] = preferences
        self._save_config()

    def _record_failure(self) -> None:
        preferences = update_preferences(self.config)
        preferences["last_check"] = max(
            0,
            int(time.time()) - CHECK_INTERVAL_SECONDS + FAILURE_RETRY_SECONDS,
        )
        self.config["updates"] = preferences
        self._save_config()

    def _on_available(self, manifest: UpdateManifest, source: str) -> None:
        self._record_check(source=source, version=str(manifest.version))

    def _on_ready(self, prepared: PreparedUpdate) -> None:
        self.prepared = prepared
        record_ready_update(
            prepared.executable,
            version=str(prepared.manifest.version),
            sha256=prepared.manifest.artifact.sha256,
        )
        self._record_check(source=prepared.source, version=str(prepared.manifest.version))

    def _on_current(self) -> None:
        self._record_check()

    def _on_failed(self, _message: str) -> None:
        self._record_failure()

    def _worker_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()

    def shutdown(self) -> None:
        worker = self.worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        worker.wait(int((NETWORK_TIMEOUT_SECONDS + 2.0) * 1000))


__all__ = [
    "CHECK_INTERVAL_SECONDS",
    "DOWNLOAD_CHUNK_BYTES",
    "FAILURE_RETRY_SECONDS",
    "INSUFFICIENT_DISK_SPACE_MESSAGE",
    "PreparedUpdate",
    "SelfUpdateController",
    "UpdateDownloadWorker",
]
