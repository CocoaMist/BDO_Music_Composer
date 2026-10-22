"""Opt-in, bounded local choice records; no score content or identity fields."""

from __future__ import annotations

import json
from pathlib import Path

from bdo_common.atomic_io import atomic_write_bytes
from .brief import CreationBrief
from .engine import ENGINE_ID, ENGINE_VERSION


MAX_FEEDBACK_RECORDS = 1000
MAX_FEEDBACK_BYTES = 1_000_000


def record_choice(path: Path, brief: CreationBrief, parts: frozenset[str], outcome: str) -> None:
    if outcome not in {"applied", "not_useful"}:
        raise ValueError("invalid creation feedback outcome")
    if not parts.issubset({"melody", "harmony", "bass", "drums", "adaptation", "expression"}):
        raise ValueError("invalid feedback parts")
    previous = []
    if path.exists():
        if path.stat().st_size > MAX_FEEDBACK_BYTES:
            raise ValueError("creation feedback exceeds its local size limit")
        previous = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(previous, list):
            raise ValueError("invalid creation feedback file")
    # Explicit allowlist: exclude source track IDs, project ranges, paths,
    # note data and even score fingerprints from the feedback record.
    record = {"schema": 1, "engine": ENGINE_ID, "version": ENGINE_VERSION,
              "action": brief.action.value, "character": brief.character.value,
              "variant": brief.variant, "minor": brief.minor,
              "parts": sorted(parts), "outcome": outcome}
    payload = json.dumps((previous + [record])[-MAX_FEEDBACK_RECORDS:], ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_FEEDBACK_BYTES:
        raise ValueError("creation feedback exceeds its local size limit")
    atomic_write_bytes(path, payload.encode("utf-8"))
