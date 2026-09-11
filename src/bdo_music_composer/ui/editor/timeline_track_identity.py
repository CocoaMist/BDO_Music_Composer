"""Presentation helpers for persistent Track-to-game-instrument identity."""

from __future__ import annotations

from collections.abc import Callable

from bdo_midi.instruments import localized_bdo_instrument_name
from bdo_music_composer.editor.editor_models import TrackState


Translator = Callable[[str], str]


def game_instrument_name(track: TrackState, translate: Translator) -> str:
    return localized_bdo_instrument_name(
        int(track.bdo_instrument_id), translate
    )


def tooltip(
    track: TrackState,
    translate: Translator,
    validation: str = "",
) -> str:
    identity = (
        f"{track.display_name}\n"
        f"BDO · {game_instrument_name(track, translate)}"
    )
    return f"{identity}\n\n{validation}" if validation else identity


def title(track: TrackState, translate: Translator, compact: bool) -> str:
    if not compact:
        return track.display_name
    return f"{game_instrument_name(track, translate)} · {track.display_name}"


__all__ = ["game_instrument_name", "title", "tooltip"]
