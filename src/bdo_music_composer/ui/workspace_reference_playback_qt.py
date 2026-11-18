"""Run the arrangement reference layer on the active project clock."""

from __future__ import annotations

from bdo_music_composer.audio.reference_audio_controller import synchronize_reference_audio
from bdo_music_composer.ui.i18n import tr


class WorkspaceReferencePlaybackMixin:
    def _reference_playback_bounds(
        self,
        loop_range: tuple[float, float] | None,
    ) -> tuple[float, float | None]:
        reference = self.reference_audio
        start = max(0.0, reference.project_start_ms)
        end = reference.project_end_ms if reference.duration_ms > 0.0 else None
        if loop_range is not None:
            start = max(start, loop_range[0])
            end = loop_range[1] if end is None else min(end, loop_range[1])
        return start, end

    def _start_reference_audio_from(self, start_ms: float) -> None:
        if not self.reference_audio.audio_path:
            return
        loop_range = self.timeline.time_range if self.timeline_loop_box.isChecked() else None
        start, end = self._reference_playback_bounds(loop_range)
        if end is not None and end <= start:
            return
        # Without a mixer, begin inside the audible part of the selected range.
        if start_ms < start or (end is not None and start_ms >= end):
            start_ms = start
        self.timeline.set_playhead(start_ms)
        self._sync_reference_to_position(start_ms, play=True, force=True)
        if self.reference_audio.is_playing:
            self.reference_status_timer.start()
            self.status_label.setText(tr("参考音频播放"))
        self._sync_preview_state()

    def _sync_reference_to_position(
        self,
        position_ms: float,
        *,
        play: bool,
        force: bool = False,
    ) -> None:
        if not self.reference_audio.audio_path:
            return
        self.reference_last_resync_at = synchronize_reference_audio(
            self.reference_audio, position_ms, play=play, force=force,
            last_resync_at=self.reference_last_resync_at,
        )

    def _reposition_reference_after_alignment(self) -> None:
        if self.realtime_preview_loading:
            if self.preview_transport_coordinator.pause_requested:
                return
            position = self.timeline.playhead_ms
        elif self.realtime_preview_active:
            status = self.realtime_audio.get_status()
            if status.state != "playing":
                return
            position = status.position_ms
        elif self.reference_status_timer.isActive() and self.reference_audio.is_playing:
            position = self.timeline.playhead_ms
        else:
            return
        self._sync_reference_to_position(position, play=True, force=True)
        if self.realtime_preview_loading and self.reference_audio.is_playing:
            self.reference_status_timer.start()
        elif not self.realtime_preview_active and not self.reference_audio.is_playing:
            self._pause_preview()

    def _extend_arrangement_clock_for_reference(self) -> None:
        if not self.realtime_preview_active:
            return
        end_ms = self.reference_audio.project_end_ms if self.reference_audio.audio_path else 0.0
        set_end = getattr(self.realtime_audio, "set_transport_end_ms", None)
        if callable(set_end):
            set_end(end_ms)

    def _poll_reference_audio_status(self) -> None:
        if self.realtime_preview_active and not self.realtime_preview_loading:
            return
        reference = self.reference_audio
        ended = getattr(reference, "has_ended", False)
        if not (reference.is_playing or ended):
            self.reference_status_timer.stop()
            self._sync_preview_state()
            return
        position = reference.project_position_ms
        loop_range = self.timeline.time_range if self.timeline_loop_box.isChecked() else None
        start, end = self._reference_playback_bounds(loop_range)
        if end is not None and end <= start:
            self._pause_preview()
            return
        # EndOfMedia may reach Qt before the next GUI poll. Keep the timer
        # alive to apply the same range boundary as the moving playhead.
        reached_end = ended or (end is not None and position >= end)
        if reached_end and loop_range is not None:
            self._sync_reference_to_position(start, play=True, force=True)
            if reference.is_playing:
                position = start
                reached_end = False
        if reached_end and end is not None:
            position = min(position, end) if loop_range is not None else end
        self.timeline.set_playhead(position, follow=True)
        if self.realtime_preview_loading:
            self.realtime_preview_start_ms = self.timeline.playhead_ms
        if reached_end:
            if reference.is_playing:
                reference.pause()
            self.reference_status_timer.stop()
            self._sync_preview_state()
