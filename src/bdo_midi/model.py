"""Editor-facing MIDI value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Note(NamedTuple):
    """Immutable note shape shared by the editor, optimizer, and exporter."""

    pitch: int
    vel: int
    start: float
    dur: float
    ntype: int


ChannelGroup = tuple[list[Note], int, bool]


@dataclass(frozen=True, slots=True)
class MidiGroupEvidence:
    """Source identity retained beside one imported channel/program group."""

    channel: int
    source_program: int
    bank_msb: int = 0
    bank_lsb: int = 0
    source_track_indices: tuple[int, ...] = ()
    track_names: tuple[str, ...] = ()
    instrument_names: tuple[str, ...] = ()
    midi_dialect: str = "unknown"


__all__ = ["ChannelGroup", "MidiGroupEvidence", "Note"]
