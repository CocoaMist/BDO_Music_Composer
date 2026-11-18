"""Bounded, content-free usage batches and their local retry queue."""

from __future__ import annotations

import ctypes
import json
from math import ceil
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

from bdo_common.atomic_io import atomic_write_json


FEATURES = frozenset({
    "session", "project_open", "midi_import", "arrangement_edit", "note_editor",
    "preview", "reference_audio", "optimizer", "transcription", "export",
})
ISSUES = frozenset({"import_failed", "export_failed", "preview_failed", "startup_failed"})
HELPFULNESS = frozenset({"helpful", "neutral", "not_helpful"})
SERVERS = frozenset({"cn", "na", "eu", "sea", "tw", "jp", "kr", "sa", "ru", "tr", "console", "other"})
MAX_COUNT = 65_535
_MAX_PENDING = 24
_MAX_QUEUE_BYTES = 64 * 1024
_ID = re.compile(r"[0-9a-f]{32}")
_VERSION = re.compile(r"(?:[0-9]{1,6}\.){2,3}[0-9]{1,6}")
_OS = frozenset({"windows10", "windows11", "windows-other", "other"})
_CPU = frozenset({"1-4", "5-8", "9-16", "17-32", "33+"})
_RAM = frozenset({"0-7", "8-15", "16-31", "32-63", "64+", "unknown"})
_REQUIRED = frozenset({"version", "batch_id", "installation_id", "app_version", "platform", "features", "exported"})
_OPTIONAL = frozenset({"issues", "helpfulness", "server"})


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
        ("physical_total", ctypes.c_uint64), ("physical_free", ctypes.c_uint64),
        ("page_total", ctypes.c_uint64), ("page_free", ctypes.c_uint64),
        ("virtual_total", ctypes.c_uint64), ("virtual_free", ctypes.c_uint64),
        ("extended_free", ctypes.c_uint64),
    ]


def _windows_ram() -> int | None:
    if sys.platform != "win32":
        return None
    status = _MemoryStatus()
    status.length = ctypes.sizeof(status)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    return int(status.physical_total) if success and status.physical_total else None


def hardware_buckets() -> dict[str, str]:
    """Read coarse process-local facts without probing hardware IDs or drivers."""
    windows = sys.platform == "win32"
    system = "other"
    if windows:
        release = sys.getwindowsversion().platform_version
        system = (
            "windows11" if release[0] == 10 and release[2] >= 22000
            else "windows10" if release[0] == 10
            else "windows-other"
        )
    threads = os.cpu_count() or 1
    cpu = (
        "1-4" if threads <= 4 else "5-8" if threads <= 8
        else "9-16" if threads <= 16 else "17-32" if threads <= 32 else "33+"
    )
    memory = _windows_ram()
    gib = ceil(memory / (1024 ** 3)) if memory is not None else None
    ram = (
        "unknown" if gib is None else "0-7" if gib < 8 else "8-15" if gib < 16
        else "16-31" if gib < 32 else "32-63" if gib < 64 else "64+"
    )
    return {"os": system, "cpu_threads": cpu, "ram_gib": ram}


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _platform(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.keys() == {"os", "cpu_threads", "ram_gib"}
        and isinstance(value["os"], str) and value["os"] in _OS
        and isinstance(value["cpu_threads"], str) and value["cpu_threads"] in _CPU
        and isinstance(value["ram_gib"], str) and value["ram_gib"] in _RAM
    )


def _counters(value: object, allowed: frozenset[str]) -> bool:
    return isinstance(value, dict) and all(
        key in allowed and type(count) is int and 1 <= count <= MAX_COUNT
        for key, count in value.items()
    )


def _batch(value: object, installation_id: str) -> bool:
    return (
        isinstance(value, dict)
        and _REQUIRED.issubset(value) and value.keys() <= _REQUIRED | _OPTIONAL
        and type(value["version"]) is int and value["version"] == 1
        and _identifier(value["batch_id"])
        and value["installation_id"] == installation_id
        and isinstance(value["app_version"], str) and _VERSION.fullmatch(value["app_version"]) is not None
        and _platform(value["platform"])
        and _counters(value["features"], FEATURES)
        and type(value["exported"]) is bool
        and ("issues" not in value or _counters(value["issues"], ISSUES))
        and ("helpfulness" not in value or (
            isinstance(value["helpfulness"], str) and value["helpfulness"] in HELPFULNESS
        ))
        and ("server" not in value or isinstance(value["server"], str) and value["server"] in SERVERS)
    )


def _merge_counters(target: dict[str, int], delta: dict[str, int]) -> None:
    for key, count in delta.items():
        target[key] = min(MAX_COUNT, target.get(key, 0) + count)


class UsageTelemetryQueue:
    """A single writer stores drafts and immutable, acknowledged wire batches."""

    def __init__(self, path: Path, *, app_version: str, platform: dict[str, str]) -> None:
        if not _VERSION.fullmatch(app_version) or not _platform(platform):
            raise ValueError("invalid telemetry build or platform buckets")
        self.path = path
        self._app_version = app_version
        self._platform = dict(platform)
        self._dirty = False
        self._installation_id = uuid4().hex
        self._pending: list[dict] = []
        self._draft: dict | None = None
        self._load()

    def _load(self) -> None:
        try:
            with self.path.open("rb") as stream:
                body = stream.read(_MAX_QUEUE_BYTES + 1)
            if len(body) > _MAX_QUEUE_BYTES:
                return
            value = json.loads(body)
        except (OSError, ValueError, RecursionError):
            return
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            return
        identifier = value.get("installation_id")
        if not _identifier(identifier):
            return
        self._installation_id = identifier
        pending = value.get("pending")
        seen = set()
        if isinstance(pending, list):
            for item in pending[:_MAX_PENDING]:
                if _batch(item, identifier) and item["batch_id"] not in seen:
                    self._pending.append(item)
                    seen.add(item["batch_id"])
        draft = value.get("draft")
        if _batch(draft, identifier) and draft["batch_id"] not in seen:
            self._draft = draft

    def add(
        self,
        features: dict[str, int],
        issues: dict[str, int],
        exported: bool,
        helpfulness: str,
        server: str,
    ) -> None:
        if not _counters(features, FEATURES) or not _counters(issues, ISSUES) or type(exported) is not bool:
            return
        if not isinstance(helpfulness, str) or helpfulness not in HELPFULNESS:
            helpfulness = ""
        if not isinstance(server, str) or server not in SERVERS:
            server = ""
        if not (features or issues or exported or helpfulness):
            return
        if self._draft is not None and (
            self._draft.get("server", "") != server
            or self._draft["app_version"] != self._app_version
            or self._draft["platform"] != self._platform
        ):
            self._seal_draft()
        if self._draft is None:
            self._draft = {
                "version": 1, "batch_id": uuid4().hex, "installation_id": self._installation_id,
                "app_version": self._app_version, "platform": self._platform,
                "features": {}, "exported": False,
            }
            if server:
                self._draft["server"] = server
        _merge_counters(self._draft["features"], features)
        if issues:
            _merge_counters(self._draft.setdefault("issues", {}), issues)
        self._draft["exported"] = self._draft["exported"] or exported
        if helpfulness:
            self._draft["helpfulness"] = helpfulness
        self._dirty = True

    def _seal_draft(self) -> None:
        if self._draft is None:
            return
        if len(self._pending) >= _MAX_PENDING:
            # The first batch may be in flight. Capacity pressure keeps its ID
            # stable so a retry is always byte-for-byte the same operation.
            self._pending.pop()
        self._pending.append(self._draft)
        self._draft = None
        self._dirty = True

    def save(self) -> None:
        if self._dirty:
            atomic_write_json(self.path, {
                "version": 1, "installation_id": self._installation_id,
                "pending": self._pending, "draft": self._draft,
            })
            self._dirty = False

    def prepare(self) -> tuple[str, bytes] | None:
        if not self._pending:
            self._seal_draft()
        self.save()
        if not self._pending:
            return None
        first = self._pending[0]
        return first["batch_id"], json.dumps(first, separators=(",", ":")).encode("ascii")

    def acknowledge(self, batch_id: str) -> bool:
        if not self._pending or self._pending[0]["batch_id"] != batch_id:
            return False
        removed = self._pending.pop(0)
        self._dirty = True
        try:
            self.save()
        except OSError:
            # Keep the acknowledged ID retryable after a local commit failure.
            self._pending.insert(0, removed)
            raise
        return True
