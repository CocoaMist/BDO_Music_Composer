"""Build the small allow-listed payload used by the support endpoint."""

import re
from collections import deque
from typing import TypedDict

from bdo_music_composer.app.support_bundle import (
    CRASH_LOG_PATH,
    _bounded_log_tail,
    support_metadata,
)


_EVENT_HEADERS = {
    "Unhandled exception": "unhandled_exception",
    "Transcription diagnostic": "transcription_warning",
    "Transcription assist analysis failed": "transcription_failed",
    "Transcription analysis failed": "transcription_failed",
    "Transcription cleanup profile switch failed": "transcription_failed",
    "Transcription range decode failed": "transcription_failed",
    "Transcription rhythm diagnostic failed": "transcription_failed",
    "Reference timbre analysis failed": "transcription_failed",
    "Autosave failed": "autosave_failed",
    "Export consistency verification failed": "export_verification_failed",
    "Convert failed": "conversion_failed",
    "Built-in optimizer analysis failed": "optimizer_failed",
    "Optimizer plugin analysis failed": "optimizer_failed",
}
_EVENT_HEADER = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] (.+)")
_VERSION = re.compile(r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}")
_EXCEPTION_TYPES = frozenset({
    "AssertionError", "AttributeError", "FileNotFoundError", "ImportError",
    "IndexError", "KeyError", "MemoryError", "ModuleNotFoundError", "OSError",
    "PermissionError", "RuntimeError", "TimeoutError", "TypeError", "ValueError",
})
_MAX_EVENTS = 12


class DiagnosticEvent(TypedDict):
    event: str
    exception: str


class DiagnosticReport(TypedDict):
    version: str
    system: str
    system_release: str
    frozen: bool
    event: str
    log: list[DiagnosticEvent]


def _diagnostic_events(tail: str) -> list[DiagnosticEvent]:
    recent: deque[DiagnosticEvent] = deque(maxlen=_MAX_EVENTS)
    current: DiagnosticEvent | None = None
    in_traceback = False
    for line in tail.splitlines():
        header = _EVENT_HEADER.fullmatch(line)
        if header:
            title = header[1]
            event = _EVENT_HEADERS.get(title)
            if title.startswith("Unhandled thread exception: "):
                event = "unhandled_thread_exception"
            current = {"event": event, "exception": "unknown"} if event else None
            if current:
                recent.append(current)
            in_traceback = False
        elif current and line == "Traceback (most recent call last):":
            in_traceback = True
        elif in_traceback and current:
            exception_type = line.partition(":")[0]
            if exception_type in _EXCEPTION_TYPES:
                current["exception"] = exception_type
                in_traceback = False
    return list(recent)


def build_diagnostic_report() -> DiagnosticReport:
    """Return exactly the fields the user will preview and can attach."""
    metadata = support_metadata()
    events = _diagnostic_events(_bounded_log_tail(CRASH_LOG_PATH))

    version = str(metadata["application_version"])
    system = str(metadata["system"])
    release = str(metadata["system_release"])
    return {
        "version": version if _VERSION.fullmatch(version) else "unknown",
        "system": system if system in {"Windows", "Linux", "Darwin"} else "other",
        "system_release": release if _VERSION.fullmatch(release) else "unknown",
        "frozen": bool(metadata["frozen"]),
        "event": events[-1]["event"] if events else "none",
        "log": events,
    }
