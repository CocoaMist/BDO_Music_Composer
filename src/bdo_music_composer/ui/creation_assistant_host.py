"""One undoable bridge from a chosen authoring candidate to the live project."""

from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import QDialog

from bdo_music_composer.core.project_paths import USER_DATA_DIR
from bdo_music_composer.creation.feedback import record_choice
from bdo_music_composer.editor.arrangement_clip import ClipEditPlan, ClipTrackUpdate
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.game_score_model import reconcile_game_velocity_records
from bdo_music_composer.ui.dialogs.creation_assistant_dialog import (
    CHARACTER_LABELS, ERROR_LABELS, PART_LABELS, CreationAssistantDialog,
)
from bdo_music_composer.ui.i18n import tr, trf


class CreationAssistantHostMixin:
    def _open_creation_assistant(self):
        try:
            dialog = CreationAssistantDialog(self)
        except (ValueError, TypeError) as exc:
            self.show_toast(trf("无法生成候选：{error}", error=tr(ERROR_LABELS.get(str(exc), str(exc)))), kind="warning")
            return
        if dialog.exec() != QDialog.Accepted:
            return
        session = dialog.current_session()
        if session is None:
            return
        try:
            self._apply_creation_session(session, dialog.selected_parts())
        except (ValueError, TypeError) as exc:
            self.show_toast(trf("无法应用建议：{error}", error=tr(ERROR_LABELS.get(str(exc), str(exc)))), kind="warning")
            return
        if dialog.feedback_box.isChecked():
            self._record_creation_choice(session, dialog.selected_parts(), "applied")

    def _record_creation_choice(self, session, keys, outcome):
        try:
            record_choice(USER_DATA_DIR / "creation" / "choices.json", session.candidate.brief, keys, outcome)
        except (OSError, ValueError) as exc:
            # Feedback is optional; failure must not report a successful score
            # transaction as failed or roll it back.
            self.show_toast(tr("曲谱操作不受影响，但本次本地反馈未能保存。"), kind="warning")

    def _apply_creation_session(self, session, keys):
        session.context.assert_current(self.tracks, self.bpm_override or self.bpm, self.time_sig, self.time_sig_denominator)
        proposed = session.materialize(keys)
        old_by_id = {t.track_id: t for t in self.tracks}
        changed = []
        for track in proposed:
            previous = old_by_id.get(track.track_id)
            if previous is None:
                role = PART_LABELS.get(track.display_name, track.display_name)
                track.display_name = trf("{part} · {character}", part=tr(role), character=tr(CHARACTER_LABELS[session.candidate.brief.character]))
                changed.append(track.track_id)
            elif track != previous:
                track.bdo_source_note_records = reconcile_game_velocity_records(previous.notes, previous.bdo_source_note_records, track.notes)
                changed.append(track.track_id)
        if not changed:
            return False
        self._stop_preview(reset_playhead=False)
        self._push_project_snapshot()
        # Preserve TrackState identity for open editors; publish only after
        # every proposal has materialized and passed the stale-state guard.
        final = []
        for track in proposed:
            previous = old_by_id.get(track.track_id)
            if previous is not None:
                if track.track_id in changed:
                    for field in fields(TrackState): setattr(previous, field.name, getattr(track, field.name))
                final.append(previous)
            else:
                final.append(track)
        self.tracks = final
        self._refresh_tracks()
        self._schedule_timeline_validation_refresh()
        updates = tuple(ClipTrackUpdate(t.track_id, tuple(t.notes), tuple(t.performance_controls), t.bdo_source_note_records, t.bdo_source_group_index, t.clip_start_ms, t.clip_end_ms, tuple(t.arrangement_clips)) for t in final if t.track_id in changed and t.track_id in old_by_id)
        if updates:
            self._synchronize_open_clip_editors(ClipEditPlan(updates, updates[0].track_id))
        self._autosave_project("creation assistant", immediate=True)
        self._schedule_transcription_assist_refresh()
        self.status_label.setText(tr("创作建议已应用，可撤销并继续编辑。"))
        self.show_toast(tr("创作建议已应用，可撤销并继续编辑。"), kind="success")
        return True
