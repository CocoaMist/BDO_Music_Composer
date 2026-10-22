"""Bounded authoring intent independent of Qt and any model provider."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from optimization.plugin_api import OptimizationPreview


class CreationAction(StrEnum):
    DRAFT = "draft"
    ACCOMPANY = "accompany"
    ADAPT = "adapt"
    EXPRESS = "express"


class MusicalCharacter(StrEnum):
    LYRICAL = "lyrical"
    LIGHT = "light"
    DRIVING = "driving"


@dataclass(frozen=True, slots=True)
class CreationBrief:
    action: CreationAction
    character: MusicalCharacter = MusicalCharacter.LYRICAL
    tonic: int = 0
    minor: bool = False
    start_bar: int = 0
    bars: int = 8
    source_track_id: int | None = None
    melody_instrument: int = 17
    harmony_instrument: int = 17
    bass_instrument: int = 14
    variant: int = 0
    rewrite_velocity: bool = False
    shape_durations: bool = False
    # Imported GM drum pitch 48 is ambiguous with native BDO kick. Conversion
    # therefore needs an explicit encoding decision, never pitch-range guessing.
    drums_are_gm: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, CreationAction) or not isinstance(self.character, MusicalCharacter):
            raise ValueError("invalid creation action or character")
        if not 0 <= self.tonic <= 11 or not 0 <= self.start_bar <= 4095:
            raise ValueError("invalid creation key or start bar")
        if not 1 <= self.bars <= 16 or not 0 <= self.variant <= 31:
            raise ValueError("creation length or variant exceeds its limit")

    def time_range(self, bpm: int, meter: int) -> tuple[float, float]:
        bar_ms = 60_000.0 / bpm * meter
        return self.start_bar * bar_ms, (self.start_bar + self.bars) * bar_ms


@dataclass(frozen=True, slots=True)
class CreationFinding:
    """Stable diagnostic codes; translated only at the presentation boundary."""

    code: str
    count: int = 0


@dataclass(frozen=True, slots=True)
class ProposalPart:
    key: str
    operation_indices: tuple[int, ...]
    note_count: int
    instrument_id: int


@dataclass(frozen=True, slots=True)
class CreationCandidate:
    brief: CreationBrief
    preview: OptimizationPreview
    parts: tuple[ProposalPart, ...]
    findings: tuple[CreationFinding, ...]
    chord_degrees: tuple[int | None, ...] = ()
