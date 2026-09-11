"""Localized presentation adapters for transactional editor imports."""

from __future__ import annotations

from pathlib import Path

from bdo_midi import BDO_INSTRUMENT_NAMES
from bdo_midi.instruments import (
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
    localized_gm_program_name,
)
from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.app.game_profile_provider import get_bdo_profile
from bdo_music_composer.editor.editor_import import (
    MidiImportData,
    MidiMeterReadError,
    MidiNoNotesError,
    TrackImportPresentation,
    prepare_midi_import as _prepare_midi_import,
    read_midi_time_signature_denominator,
    tracks_from_bdo_snapshot,
    tracks_from_project_payload as _tracks_from_project_payload,
)
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.ui.editor.editor_ui_helpers import TRACK_COLORS
from bdo_music_composer.ui.i18n import tr, trf


def ui_bdo_instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


def ui_bdo_instrument_source(instrument_id: int) -> str:
    numeric_id = int(instrument_id)
    return BDO_INSTRUMENT_NAMES.get(numeric_id, f"BDO 0x{numeric_id:02X}")


def ui_bdo_instrument_names() -> dict[int, str]:
    return localized_bdo_instrument_names(tr)


TRACK_IMPORT_PRESENTATION = TrackImportPresentation(
    colors=tuple(TRACK_COLORS),
    bdo_instrument_name=ui_bdo_instrument_name,
    gm_program_name=lambda program: localized_gm_program_name(program, tr),
    drum_track_name=lambda: tr("鼓组 · MIDI 通道 10"),
    new_track_name=lambda track_id: trf(
        "新建轨道 {track_id}", track_id=track_id + 1
    ),
)


def source_time_signature_denominator(midi_path: str | Path) -> int:
    try:
        return read_midi_time_signature_denominator(midi_path)
    except MidiMeterReadError as exc:
        raise ValueError(
            trf("无法读取 MIDI 拍号，已阻止导出：{error}", error=exc)
        ) from exc


def track_states_from_bdo_score(snapshot) -> list[TrackState]:
    return list(tracks_from_bdo_snapshot(snapshot, TRACK_IMPORT_PRESENTATION))


def track_states_from_project_payload(payload: dict) -> list[TrackState]:
    return list(_tracks_from_project_payload(payload, TRACK_IMPORT_PRESENTATION))


def prepare_midi_import(
    path: str | Path,
    settings: ConversionSettings,
) -> MidiImportData:
    try:
        profile = get_bdo_profile()

        def pitch_support(instrument_id: int, pitch: int) -> bool:
            rule = profile.instruments.get(int(instrument_id))
            if rule is None:
                return False
            supported = rule.supports_pitch(int(pitch))
            return supported is not False

        return _prepare_midi_import(
            path,
            settings,
            TRACK_IMPORT_PRESENTATION,
            pitch_support=pitch_support,
        )
    except MidiNoNotesError as exc:
        raise ValueError(tr("MIDI 中没有可导入的音符事件。")) from exc
    except MidiMeterReadError as exc:
        raise ValueError(
            trf("无法读取 MIDI 拍号，已阻止导出：{error}", error=exc)
        ) from exc


__all__ = [
    "TRACK_IMPORT_PRESENTATION",
    "prepare_midi_import",
    "source_time_signature_denominator",
    "track_states_from_bdo_score",
    "track_states_from_project_payload",
    "ui_bdo_instrument_name",
    "ui_bdo_instrument_names",
    "ui_bdo_instrument_source",
]
