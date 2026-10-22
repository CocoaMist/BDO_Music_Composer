"""Bounded candidate audition using the existing asynchronous audio engine."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal

from bdo_music_composer.audio.bdo_realtime_audio import AudioEngineError
from bdo_music_composer.app.audio_source_settings import preview_source_mode
from bdo_music_composer.creation.workspace import projected_tracks
from bdo_music_composer.core.project_paths import WWISE_MIDI_MAP_PATH
from bdo_music_composer.ui.i18n import tr, trf


class CreationAudition(QObject):
    status_changed = Signal(str)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self.loading = False
        self.active = False
        self.start_ms = self.end_ms = 0.0

    def play(self, tracks, start_ms: float, end_ms: float) -> None:
        self.stop()
        audio = self.host.realtime_audio
        if not audio.available():
            self.status_changed.emit(tr("无可用音频设备"))
            return
        self.host._claim_playback_focus(None)
        self.host._stop_preview(reset_playhead=False)
        projected = projected_tracks(tracks)
        # Restrict the audible window as well as the timer, so slow UI polling
        # cannot leak the next phrase into an A/B audition.
        prepared = []
        solo = any(t.solo and not t.muted for t in projected)
        for track in projected:
            if track.muted or (solo and not track.solo):
                continue
            notes = [n._replace(start=max(n.start, start_ms), dur=min(n.start + n.dur, end_ms) - max(n.start, start_ms))
                     for n in track.notes if n.start < end_ms and n.start + n.dur > start_ms]
            if notes:
                prepared.append(replace(track, notes=notes))
        if not prepared:
            self.status_changed.emit(tr("所选范围没有可试听的音符"))
            return
        prepared = self.host._project_tracks_for_preview(prepared)
        self.start_ms, self.end_ms = start_ms, end_ms
        try:
            if preview_source_mode(self.host.audio_sources) == "pack":
                blockers = self.host._realtime_preview_blockers(prepared)
                if blockers:
                    self.status_changed.emit(trf("试听失败：{error}", error=blockers[0]))
                    return
                audio.load_project_async(prepared, WWISE_MIDI_MAP_PATH, start_ms, self.host.reverb, self.host.delay, self.host.chorus)
            else:
                audio.load_procedural_project_async(prepared, start_ms, self.host.reverb, self.host.delay, self.host.chorus)
            self.active = self.loading = True
            self.timer.start()
            self.status_changed.emit(tr("正在准备试听…"))
        except (AudioEngineError, ValueError) as exc:
            self.stop()
            self.status_changed.emit(trf("试听失败：{error}", error=exc))

    def _poll(self):
        try:
            audio = self.host.realtime_audio
            if self.loading:
                result = audio.finish_loading(self.start_ms)
                if result is None:
                    return
                audio.play()
                self.loading = False
                self.status_changed.emit(tr("试听播放 · 效果以游戏内为准"))
            status = audio.get_status()
            if status.position_ms >= min(self.end_ms, status.duration_ms) - 1:
                self.stop()
        except (AudioEngineError, ValueError) as exc:
            self.stop()
            self.status_changed.emit(trf("试听失败：{error}", error=exc))

    def stop(self):
        self.timer.stop()
        if self.active:
            self.host.realtime_audio.cancel_loading()
            self.host.realtime_audio.clear_playback()
        self.active = self.loading = False
