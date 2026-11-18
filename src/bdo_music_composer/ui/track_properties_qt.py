"""Shared UI commits for dialog and workbench track properties."""

from __future__ import annotations

from bdo_midi.instruments import MARNIAN_SYNTH_INSTRUMENT_IDS
from bdo_common.bdo_track_effects import (
    raw_track_settings, TRACK_REVERB_SEND_INDEX, TRACK_DELAY_SEND_INDEX, TRACK_CHORUS_SEND_INDEX,
)
from bdo_music_composer.editor.game_score_model import (
    inherit_game_instrument_mix, propagate_game_instrument_mix,
)
from bdo_music_composer.ui.i18n import trf


def apply_track_pitch(self, track, selected_offset: int) -> None:
    current = self._pitch_transform_plan.override_for(track.track_id)
    current_offset = current.semitones if current is not None else 0
    if selected_offset == current_offset:
        return
    self._push_project_snapshot()
    self._pitch_transform_plan = (
        self._pitch_transform_plan.with_track_semitones(
            track.track_id,
            selected_offset,
        )
    )
    self._restart_preview_after_timeline_change()
    self._schedule_timeline_validation_refresh()
    self._autosave_project("track transpose", immediate=True)
    self._select_track(track)
    self.show_toast(
        trf(
            "{track} · 轨道移调 {track_transpose:+d} · 最终移调 {effective:+d} 半音",
            track=track.display_name,
            track_transpose=selected_offset,
            effective=self._effective_track_transpose(track),
        ),
        kind="success",
    )


def apply_track_fx(self, track, selection) -> None:
    selected_mode = (
        selection.selected_marnian_synth_mode()
        if track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        else "basic"
    )
    selected_settings = selection.selected_track_settings()
    changed_send_indices = selection.changed_send_indices()
    if (
        selected_mode == track.marnian_synth_mode
        and selected_settings == tuple(track.bdo_track_settings)
    ):
        return
    self._push_project_snapshot()
    previous_mode = str(track.marnian_synth_mode)
    previous_volume = int(track.bdo_track_volume)
    previous_settings = tuple(track.bdo_track_settings)
    track.marnian_synth_mode = selected_mode
    try:
        inherited_from = (
            inherit_game_instrument_mix(self.tracks, track)
            if selected_mode != previous_mode
            else None
        )
        if inherited_from is None:
            base_settings = list(selected_settings)
        else:
            base_settings = list(raw_track_settings(track.bdo_track_settings))
            for index in changed_send_indices:
                base_settings[index] = selected_settings[index]
        track.bdo_track_settings = tuple(base_settings)
        _changed_track_ids = propagate_game_instrument_mix(
            self.tracks,
            track,
            volume=False,
            sends=bool(changed_send_indices),
            send_indices=changed_send_indices,
        )
    except (TypeError, ValueError) as exc:
        track.marnian_synth_mode = previous_mode
        track.bdo_track_volume = previous_volume
        track.bdo_track_settings = previous_settings
        self.timeline.update()
        self.show_toast(
            trf("无法同步游戏乐器 FX：{error}", error=exc),
            kind="error",
        )
        return
    committed_settings = tuple(track.bdo_track_settings)
    self.show_toast(
        (
            f"{track.display_name} · FX "
            f"R{committed_settings[TRACK_REVERB_SEND_INDEX]} "
            f"D{committed_settings[TRACK_DELAY_SEND_INDEX]} "
            f"C{committed_settings[TRACK_CHORUS_SEND_INDEX]}"
        ),
        kind="success",
    )
    self._schedule_timeline_validation_refresh()
    self._on_preview_mapping_changed()
