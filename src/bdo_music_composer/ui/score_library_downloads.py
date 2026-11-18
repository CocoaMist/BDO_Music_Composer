"""User-initiated, non-overwriting downloads from the score library."""

from __future__ import annotations

from dataclasses import dataclass, replace
from email.message import Message
from email.utils import collapse_rfc2231_value
from functools import partial
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import BinaryIO
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QObject, QStandardPaths, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from bdo_music_composer.app.application_metadata import APP_NAME, APP_WEBSITE_URL


_LIBRARY_HOST = QUrl(APP_WEBSITE_URL).host()
_DOWNLOAD_PATH = re.compile(r"/(?:dl/[0-9]{15,20}|bulk/download)")
_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
_RESERVED_FILENAME = re.compile(
    r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$", re.IGNORECASE,
)
_READ_CHUNK = 256 * 1024
_TRANSFER_TIMEOUT_MS = 30_000


def _is_library_origin(url: QUrl) -> bool:
    return (
        url.isValid()
        and url.scheme() == "https"
        and url.authority(QUrl.ComponentFormattingOption.FullyEncoded)
        in {_LIBRARY_HOST, f"{_LIBRARY_HOST}:443"}
    )


def is_score_library_download_url(url: QUrl | str) -> bool:
    candidate = QUrl(url)
    return (
        _is_library_origin(candidate)
        and not candidate.hasQuery()
        and not candidate.hasFragment()
        and _DOWNLOAD_PATH.fullmatch(candidate.path(QUrl.ComponentFormattingOption.FullyEncoded)) is not None
    )


@dataclass(frozen=True, slots=True)
class ScoreLibraryDownload:
    id: str
    url: str
    name: str
    state: str = "downloading"
    received: int = 0
    total: int = -1
    path: Path | None = None
    error: str = ""


@dataclass(slots=True)
class _ActiveDownload:
    reply: QNetworkReply
    stream: BinaryIO
    temporary: Path


def _safe_filename(name: str, fallback: str) -> str:
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = _UNSAFE_FILENAME.sub("_", leaf).strip(" .") or fallback
    if _RESERVED_FILENAME.fullmatch(leaf.split(".", 1)[0].rstrip()):
        leaf = f"_{leaf}"
    # Bound UTF-16 units as well as characters to leave room for Windows
    # paths and the collision suffix, even when a title uses emoji.
    filename = Path(leaf)
    stem = filename.stem.encode("utf-16-le")[:240].decode("utf-16-le", "ignore").rstrip(" .")
    suffix = filename.suffix.encode("utf-16-le")[:40].decode("utf-16-le", "ignore").rstrip(" .")
    return f"{stem or fallback}{suffix}"


def _response_filename(reply: QNetworkReply, fallback: str) -> str:
    header = bytes(reply.rawHeader("Content-Disposition")).decode("latin-1")
    if not header:
        return fallback
    message = Message()
    message["Content-Disposition"] = header
    names = [
        value for key, value in message.get_params(header="Content-Disposition", failobj=[])
        if key == "filename"
    ]
    extended = next((value for value in names if isinstance(value, tuple)), None)
    name = collapse_rfc2231_value(extended) if extended is not None else (names[0] if names else "")
    return _safe_filename(name, fallback)


def _publish_download(temporary: Path, directory: Path, name: str) -> Path:
    filename = Path(name)
    for index in range(1000):
        target = directory / (name if index == 0 else f"{filename.stem} ({index}){filename.suffix}")
        try:
            # Windows rename fails when the destination exists. A hard link
            # provides the same atomic, non-replacing publish on other hosts.
            if os.name == "nt":
                temporary.rename(target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            continue
        return target
    raise OSError("Could not choose an unused download filename.")


class ScoreLibraryDownloads(QObject):
    changed = Signal()
    finished = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        directory: Path | None = None,
        network_manager: QNetworkAccessManager | None = None,
    ) -> None:
        super().__init__(parent)
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        download_root = Path(downloads) if downloads else Path.home() / "Downloads"
        self.directory = Path(directory) if directory is not None else download_root / APP_NAME
        self._manager = network_manager if network_manager is not None else QNetworkAccessManager(self)
        self._entries: dict[str, ScoreLibraryDownload] = {}
        self._active: dict[str, _ActiveDownload] = {}
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cancel_all)

    @property
    def entries(self) -> tuple[ScoreLibraryDownload, ...]:
        return tuple(self._entries.values())

    def start(self, url: QUrl | str) -> str | None:
        if not is_score_library_download_url(url):
            return None
        candidate = QUrl(url)
        download_id = uuid4().hex
        name = "BDO Music Archive.zip" if candidate.path() == "/bulk/download" else f"{candidate.fileName()}.bdo"
        entry = ScoreLibraryDownload(download_id, candidate.toString(), name)
        self._begin(entry)
        return download_id

    def retry(self, download_id: str) -> str | None:
        entry = self._entries.get(download_id)
        if entry is None or entry.state not in {"failed", "cancelled"}:
            return None
        self._begin(replace(entry, state="downloading", received=0, total=-1, path=None, error=""))
        return download_id

    def _begin(self, entry: ScoreLibraryDownload) -> None:
        self._entries[entry.id] = entry
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stream = NamedTemporaryFile(
                dir=self.directory, prefix=".bdo-download-", suffix=".part", delete=False,
            )
        except OSError as error:
            self._update(entry.id, state="failed", error=str(error))
            return

        request = QNetworkRequest(QUrl(entry.url))
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy,
        )
        request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
        reply = self._manager.get(request)
        self._active[entry.id] = _ActiveDownload(reply, stream, Path(stream.name))
        reply.setReadBufferSize(_READ_CHUNK)
        reply.metaDataChanged.connect(partial(self._read_metadata, entry.id))
        reply.readyRead.connect(partial(self._read_data, entry.id))
        reply.downloadProgress.connect(partial(self._progress, entry.id))
        reply.finished.connect(partial(self._finish, entry.id))
        self.changed.emit()

    def cancel(self, download_id: str) -> None:
        active = self._active.pop(download_id, None)
        if active is not None:
            active.reply.abort()
            self._dispose(active)
            self._update(download_id, state="cancelled")

    def cancel_all(self) -> None:
        for download_id in tuple(self._active):
            self.cancel(download_id)

    def _read_metadata(self, download_id: str) -> None:
        active = self._active.get(download_id)
        if active is not None and active.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == 200:
            self._update(download_id, name=_response_filename(active.reply, self._entries[download_id].name))

    def _progress(self, download_id: str, received: int, total: int) -> None:
        if download_id in self._active:
            self._update(download_id, received=max(0, received), total=total)

    def _read_data(self, download_id: str) -> None:
        active = self._active.get(download_id)
        if active is None:
            return
        accepting = active.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == 200
        try:
            while active.reply.bytesAvailable():
                chunk = active.reply.read(_READ_CHUNK)
                if not chunk:
                    break
                if accepting:
                    active.stream.write(chunk)
        except OSError as error:
            self._fail(download_id, str(error), abort=True)

    def _finish(self, download_id: str) -> None:
        active = self._active.get(download_id)
        if active is None:
            return
        reply = active.reply
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail(download_id, reply.errorString())
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        disposition = bytes(reply.rawHeader("Content-Disposition")).strip().lower()
        media_type = bytes(reply.rawHeader("Content-Type")).lower().split(b";", 1)[0].strip()
        if status != 200 or not _is_library_origin(reply.url()) or (
            media_type in {b"text/html", b"application/xhtml+xml", b"application/json"}
            and not disposition.startswith(b"attachment")
        ):
            self._fail(download_id, "The score library did not return a downloadable file.")
            return

        self._read_data(download_id)
        if download_id not in self._active:
            return
        try:
            size = active.stream.tell()
            if size == 0:
                raise OSError("The score library returned an empty file.")
            active.stream.flush()
            os.fsync(active.stream.fileno())
            active.stream.close()
            name = _response_filename(reply, self._entries[download_id].name)
            path = _publish_download(active.temporary, self.directory, name)
        except OSError as error:
            self._fail(download_id, str(error))
            return
        self._active.pop(download_id)
        self._dispose(active)
        self._update(download_id, state="completed", path=path, name=path.name, received=size, total=size)

    def _fail(self, download_id: str, error: str, *, abort: bool = False) -> None:
        active = self._active.pop(download_id)
        if abort:
            active.reply.abort()
        self._dispose(active)
        self._update(download_id, state="failed", error=error)

    @staticmethod
    def _dispose(active: _ActiveDownload) -> None:
        active.reply.deleteLater()
        try:
            active.stream.close()
        except OSError:
            pass
        try:
            active.temporary.unlink(missing_ok=True)
        except OSError:
            pass

    def _update(self, download_id: str, **changes: object) -> None:
        old = self._entries[download_id]
        updated = replace(old, **changes)
        if updated != old:
            self._entries[download_id] = updated
            self.changed.emit()
            if old.state == "downloading" and updated.state in {"completed", "failed"}:
                self.finished.emit(updated)
