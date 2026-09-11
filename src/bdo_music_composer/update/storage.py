"""Filesystem capacity checks shared by update download and installation."""

from __future__ import annotations

from pathlib import Path
import shutil


UPDATE_DISK_RESERVE_BYTES = 64 * 1024 * 1024


def filesystem_free_bytes(destination: str | Path) -> int:
    """Return free bytes on the nearest existing parent filesystem."""

    candidate = Path(destination).resolve(strict=False)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.is_file():
        candidate = candidate.parent
    return int(shutil.disk_usage(candidate).free)


def has_sufficient_update_space(
    destination: str | Path,
    payload_bytes: int,
    *,
    reserve_bytes: int = UPDATE_DISK_RESERVE_BYTES,
) -> bool:
    required = int(payload_bytes)
    reserve = int(reserve_bytes)
    if required < 0 or reserve < 0:
        return False
    try:
        return filesystem_free_bytes(destination) >= required + reserve
    except OSError:
        return False


__all__ = [
    "UPDATE_DISK_RESERVE_BYTES",
    "filesystem_free_bytes",
    "has_sufficient_update_space",
]
