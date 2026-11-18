"""Reference-audio transport, waveform decode and alignment controller."""

from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
from threading import Event
import time

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioDecoder,
    QAudioFormat,
    QAudioOutput,
    QMediaPlayer,
)
from PySide6.QtWidgets import QFileDialog, QWidget
from shiboken6 import isValid

from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.ui_notifications import show_global_toast
from .reference_clock_sync import reference_clock_decision
from .reference_audio_format import (
    MISSING_REFERENCE_AUDIO_SOURCE,
    ReferenceAudioFormatError,
    validate_reference_audio_file,
)
from .reference_waveform import ReferenceWaveform, TimestampedWaveform, decode_reference_waveform


_ReferenceFileIdentity = tuple[Path, int, int, int]


class _WaveformSignals(QObject):
    completed = Signal(object, object)


class _WaveformTask(QRunnable):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.signals = _WaveformSignals()
        self.cancelled = Event()

    def run(self) -> None:
        if self.cancelled.is_set():
            return
        try:
            waveform = decode_reference_waveform(self.path, self.cancelled.is_set)
        except (ImportError, OSError, RuntimeError, ValueError):
            waveform = None
        if self.cancelled.is_set() or not isValid(self.signals):
            return
        try:
            self.signals.completed.emit(self, waveform)
        except RuntimeError:
            if isValid(self.signals):
                raise


def synchronize_reference_audio(
    reference_audio: object,
    master_project_ms: float,
    *,
    play: bool,
    force: bool,
    last_resync_at: float,
) -> float:
    """Apply the shared master-clock policy to a reference transport."""

    now = time.monotonic()
    offset_ms = float(
        getattr(
            reference_audio,
            "project_offset_ms",
            getattr(reference_audio, "offset_ms", 0.0),
        )
    )
    converter = getattr(reference_audio, "project_to_audio", None)
    audio_ms = (
        float(converter(master_project_ms))
        if callable(converter)
        else float(master_project_ms) - offset_ms
    )
    previous_master_ms = None
    reference_has_ended = False
    if isinstance(reference_audio, ReferenceAudioController):
        previous_master_ms = reference_audio._observe_master_position(
            master_project_ms if play else None
        )
        reference_has_ended = reference_audio.has_ended
    project_position = getattr(reference_audio, "project_position_ms", None)
    if project_position is None:
        project_position = float(reference_audio.player.position()) + offset_ms
    decision = reference_clock_decision(
        master_project_ms=master_project_ms,
        reference_project_ms=float(project_position),
        reference_audio_ms=audio_ms,
        reference_duration_ms=reference_audio.duration_ms,
        reference_is_playing=reference_audio.is_playing,
        want_playback=play,
        force_seek=force,
        now_seconds=now,
        last_resync_seconds=last_resync_at,
        previous_master_project_ms=previous_master_ms,
        reference_has_ended=reference_has_ended,
    )
    if decision.seek:
        reference_audio.set_position(
            offset_ms if decision.seek_to_source_start else master_project_ms
        )
        last_resync_at = now
    if decision.play:
        reference_audio.play()
    elif decision.pause:
        reference_audio.pause()
    return last_resync_at


class ReferenceAudioController(QObject):
    """Local MP3/WAV playback plus bounded waveform-envelope extraction."""

    file_changed = Signal(str)
    volume_changed = Signal(int)
    offset_changed = Signal(float)
    changed = Signal()
    timeline_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio_path: Path | None = None
        self._file_identity: _ReferenceFileIdentity | None = None
        self.before_file_change: Callable[[str], bool] | None = None
        self._last_load_error = ""
        self._project_offset_ms = 0.0
        self._content_duration_ms: float | None = None
        self._waveform_duration_ms: float | None = None
        self.waveform: list[tuple[float, float, float]] = []
        self.waveform_starts: list[float] = []
        self.waveform_loading = False
        self._waveform_task: _WaveformTask | None = None
        self._waveform_cache: tuple[_ReferenceFileIdentity, ReferenceWaveform] | None = None
        self._fallback_decoder: QAudioDecoder | None = None
        self._fallback_waveform: TimestampedWaveform | None = None
        self._waveform_deferred_for_playback = False
        self._pending_project_position_ms: float | None = None
        self._last_master_project_ms: float | None = None
        self._play_when_seekable = False
        self.shutdown_complete = False

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(lambda _position: self.changed.emit())
        self.player.durationChanged.connect(self._duration_changed)
        self.player.seekableChanged.connect(self._seekable_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._playback_error)

    @property
    def audio_path(self) -> str:
        return str(self._audio_path or "")

    @property
    def source_identity(self) -> _ReferenceFileIdentity | None:
        """File version for caches derived from the currently linked source."""
        return self._file_identity

    @property
    def display_name(self) -> str:
        return self._audio_path.name if self._audio_path else tr("未载入参考音频")

    @property
    def duration_ms(self) -> float:
        if self._content_duration_ms is not None:
            return self._content_duration_ms
        if self._waveform_duration_ms is not None:
            return self._waveform_duration_ms
        return self.backend_duration_ms

    @property
    def backend_duration_ms(self) -> float:
        """Raw multimedia duration before an analysed-content correction."""

        waveform_end = self.waveform[-1][1] if self.waveform else 0.0
        return max(float(self.player.duration()), waveform_end)

    @property
    def project_offset_ms(self) -> float:
        """Project time occupied by audio frame zero."""
        return self._project_offset_ms

    @property
    def project_start_ms(self) -> float:
        return self._project_offset_ms

    @property
    def project_end_ms(self) -> float:
        return self._project_offset_ms + self.duration_ms

    @property
    def project_position_ms(self) -> float:
        if self._pending_project_position_ms is not None:
            return self._pending_project_position_ms
        return self.audio_to_project(float(self.player.position()))

    @property
    def is_playing(self) -> bool:
        return self._play_when_seekable or (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )

    @property
    def has_ended(self) -> bool:
        return self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia

    @property
    def volume_percent(self) -> int:
        return round(self.audio_output.volume() * 100)

    def choose_audio(self, parent: QWidget) -> None:
        start = self._audio_path.parent if self._audio_path else Path.home()
        selected, _filter = QFileDialog.getOpenFileName(
            parent,
            tr("选择参考音频"),
            str(start),
            tr("音频文件 (*.mp3 *.wav);;所有文件 (*.*)"),
        )
        if selected:
            if not self.set_audio_path(Path(selected)) and self._last_load_error:
                show_global_toast(
                    parent,
                    tr(self._last_load_error),
                    kind="warning",
                    duration_ms=5200,
                )

    def set_audio_path(self, path: str | Path | None, *, notify: bool = True) -> bool:
        candidate = Path(path) if path else None
        identity = None
        if candidate is not None:
            try:
                validate_reference_audio_file(candidate)
                candidate = candidate.resolve()
                stat = candidate.stat()
                identity = (candidate, stat.st_size, stat.st_mtime_ns, stat.st_ino)
            except ReferenceAudioFormatError as exc:
                self._last_load_error = str(exc)
                return False
            except (OSError, RuntimeError):
                self._last_load_error = MISSING_REFERENCE_AUDIO_SOURCE
                return False

        self._last_load_error = ""
        if identity == self._file_identity:
            return True
        resolved_path = str(candidate) if candidate is not None else ""
        if notify and self.before_file_change is not None:
            if not self.before_file_change(resolved_path):
                return False

        self._cancel_waveform_decode()
        self.stop()
        previous_path = self._audio_path
        self._audio_path = candidate
        self._file_identity = identity
        self._content_duration_ms = None
        self._waveform_duration_ms = None
        self.waveform = []
        self.waveform_starts = []
        self.waveform_loading = False
        if candidate is not None:
            cached = self._waveform_cache
            if cached is not None and cached[0] == identity:
                self.waveform = cached[1].buckets
                self.waveform_starts = cached[1].starts
                self._waveform_duration_ms = cached[1].content_duration_ms
            else:
                self.waveform_loading = True
            if candidate == previous_path:
                # Qt treats an unchanged URL as a no-op even when the file was replaced.
                self.player.setSource(QUrl())
        self.player.setSource(QUrl.fromLocalFile(resolved_path) if resolved_path else QUrl())
        if candidate is not None and self.waveform_loading:
            self._start_waveform_task(candidate)
        if notify:
            self.file_changed.emit(resolved_path)
        self.timeline_changed.emit()
        self.changed.emit()
        return True

    def play(self) -> None:
        if self._audio_path is not None:
            self._play_when_seekable = self._pending_project_position_ms is not None
            if self._play_when_seekable:
                return
            # A second full-file decoder can starve the audible Media
            # Foundation stream on long files. Resume waveform work only after
            # playback pauses or stops.
            if self._fallback_decoder is not None:
                self._waveform_deferred_for_playback = True
                self._stop_fallback_waveform()
            self.player.play()

    def pause(self) -> None:
        self._play_when_seekable = False
        self.player.pause()
        self._resume_fallback_waveform()

    def stop(self) -> None:
        self._last_master_project_ms = None
        self._pending_project_position_ms = None
        self._play_when_seekable = False
        self.player.stop()
        self._resume_fallback_waveform()

    def shutdown(self) -> None:
        """Release multimedia backends before the owning window is destroyed."""

        self.set_audio_path(None, notify=False)
        self._waveform_cache = None
        # A source-less QMediaPlayer can still retain the platform audio backend.
        # Detach it explicitly so headless/no-device Windows processes can exit.
        self.player.setAudioOutput(None)
        self.shutdown_complete = True

    def _observe_master_position(self, project_ms: float | None) -> float | None:
        previous = self._last_master_project_ms
        if project_ms is not None and self._play_when_seekable:
            # Once metadata arrives, enter at the current master position even
            # when the wait was shorter than the normal drift threshold.
            self._pending_project_position_ms = project_ms
        self._last_master_project_ms = project_ms
        return previous

    def project_to_audio(self, project_ms: float) -> float:
        return float(project_ms) - self._project_offset_ms

    def audio_to_project(self, audio_ms: float) -> float:
        return float(audio_ms) + self._project_offset_ms

    def set_project_offset_ms(self, milliseconds: float, *, notify: bool = True) -> None:
        normalized = float(milliseconds)
        if not math.isfinite(normalized):
            return
        if math.isclose(normalized, self._project_offset_ms, abs_tol=0.001):
            return
        self._project_offset_ms = normalized
        self._last_master_project_ms = None
        if notify:
            self.offset_changed.emit(normalized)
        self.timeline_changed.emit()
        self.changed.emit()

    def set_content_duration_ms(
        self,
        milliseconds: float | None,
        *,
        notify: bool = True,
    ) -> None:
        """Set the decoded-content duration shared by analysis and transport.

        Compressed-media backends may expose encoder padding as playable
        duration while the analysis decoder correctly removes it.  Once an
        evidence descriptor is available, its sample-count duration becomes
        the project boundary without changing QMediaPlayer's native seek API.
        """

        normalized: float | None
        if milliseconds is None:
            normalized = None
        else:
            value = float(milliseconds)
            if not math.isfinite(value) or value <= 0.0:
                return
            normalized = value
        if (
            normalized == self._content_duration_ms
            or (
                normalized is not None
                and self._content_duration_ms is not None
                and math.isclose(
                    normalized,
                    self._content_duration_ms,
                    abs_tol=0.001,
                )
            )
        ):
            return
        self._content_duration_ms = normalized
        if notify:
            self.timeline_changed.emit()
            self.changed.emit()

    def set_position(self, milliseconds: float) -> None:
        """Seek with a project-time position.

        All UI callers operate on the shared project timeline. The underlying
        media player remains in source-audio time.
        """
        project_ms = float(milliseconds)
        if not math.isfinite(project_ms):
            return
        audio_ms = self.project_to_audio(project_ms)
        if not math.isfinite(audio_ms) or audio_ms < 0.0:
            self._pending_project_position_ms = None
            self.player.setPosition(0)
            return
        media_duration_ms = float(self.player.duration())
        audio_position = round(audio_ms)
        is_seekable = getattr(self.player, "isSeekable", None)
        media_status = getattr(self.player, "mediaStatus", None)
        loading = media_status is not None and media_status() == QMediaPlayer.MediaStatus.LoadingMedia
        if media_duration_ms <= 0.0 or loading or (is_seekable is not None and not is_seekable()):
            # Qt can announce duration and seekability while still loading.
            first_request = self._pending_project_position_ms is None
            self._pending_project_position_ms = project_ms if audio_position > 0 else None
            if first_request:
                self.player.setPosition(audio_position)
            return
        self._pending_project_position_ms = None
        self.player.setPosition(
            min(audio_position, round(media_duration_ms))
        )

    def _apply_pending_position(self) -> None:
        pending = self._pending_project_position_ms
        if pending is not None:
            self.set_position(pending)
        if self._pending_project_position_ms is None and self._play_when_seekable:
            self._play_when_seekable = False
            if pending is None or 0.0 <= self.project_to_audio(pending) < self.duration_ms:
                self.play()

    def _duration_changed(self, _duration: int) -> None:
        self._apply_pending_position()
        self.timeline_changed.emit()

    def _seekable_changed(self, seekable: bool) -> None:
        if seekable:
            self._apply_pending_position()

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._apply_pending_position()

    def set_volume_percent(self, percent: int, *, notify: bool = True) -> None:
        normalized = max(0, min(100, int(percent)))
        if normalized == self.volume_percent:
            return
        self.audio_output.setVolume(normalized / 100.0)
        if notify:
            self.volume_changed.emit(normalized)
        self.changed.emit()

    def _start_waveform_task(self, path: Path) -> None:
        task = _WaveformTask(path)
        self._waveform_task = task
        task.signals.completed.connect(self._waveform_task_completed)
        QThreadPool.globalInstance().start(task)

    @Slot(object, object)
    def _waveform_task_completed(
        self, task: _WaveformTask, waveform: ReferenceWaveform | None,
    ) -> None:
        if task is not self._waveform_task:
            return
        self._waveform_task = None
        if waveform is None:
            self._waveform_deferred_for_playback = True
            self._resume_fallback_waveform()
            return
        self._publish_waveform(waveform)

    def _cancel_waveform_decode(self) -> None:
        if self._waveform_task is not None:
            self._waveform_task.cancelled.set()
            self._waveform_task = None
        self._waveform_deferred_for_playback = False
        self._stop_fallback_waveform()

    def _stop_fallback_waveform(self) -> None:
        decoder = self._fallback_decoder
        self._fallback_decoder = None
        self._fallback_waveform = None
        if decoder is not None:
            decoder.stop()
            decoder.deleteLater()

    def _resume_fallback_waveform(self) -> None:
        if not self._waveform_deferred_for_playback or self._audio_path is None or self.is_playing:
            return
        self._waveform_deferred_for_playback = False
        decoder = QAudioDecoder(self)
        self._fallback_decoder = decoder
        self._fallback_waveform = TimestampedWaveform()
        decoder.bufferReady.connect(self._read_waveform_buffer)
        decoder.finished.connect(self._waveform_finished)
        decoder.error.connect(self._waveform_error)
        decoder.setSource(QUrl.fromLocalFile(str(self._audio_path)))
        decoder.start()

    def _read_waveform_buffer(self) -> None:
        decoder = self._fallback_decoder
        waveform = self._fallback_waveform
        if decoder is None or waveform is None or self.sender() is not decoder:
            return
        buffer = decoder.read()
        if not buffer.isValid() or buffer.frameCount() <= 0:
            return
        audio_format = buffer.format()
        channels = max(1, audio_format.channelCount())
        sample_rate = max(1, audio_format.sampleRate())
        sample_format = audio_format.sampleFormat()
        raw = buffer.constData().cast("B")
        try:
            if sample_format == QAudioFormat.SampleFormat.UInt8:
                samples = np.frombuffer(raw, dtype=np.uint8)
                amplitudes = np.abs(samples.astype(np.float32) - 128.0) / 128.0
            elif sample_format == QAudioFormat.SampleFormat.Int16:
                samples = np.frombuffer(raw, dtype=np.int16)
                amplitudes = np.abs(samples.astype(np.float32)) / 32768.0
            elif sample_format == QAudioFormat.SampleFormat.Int32:
                samples = np.frombuffer(raw, dtype=np.int32)
                amplitudes = np.abs(samples.astype(np.float32)) / 2147483648.0
            elif sample_format == QAudioFormat.SampleFormat.Float:
                samples = np.frombuffer(raw, dtype=np.float32)
                amplitudes = np.abs(samples)
            else:
                return
        except (BufferError, TypeError, ValueError):
            return

        frame_count = len(amplitudes) // channels
        waveform.append(
            amplitudes[:frame_count * channels].reshape(frame_count, channels),
            sample_rate,
            buffer.startTime() / 1000.0,
        )

    def _waveform_finished(self) -> None:
        if self._fallback_decoder is None or self.sender() is not self._fallback_decoder:
            return
        waveform = self._fallback_waveform
        self._stop_fallback_waveform()
        self._publish_waveform(waveform.finish() if waveform is not None else None)

    def _publish_waveform(self, waveform: ReferenceWaveform | None) -> None:
        if waveform is not None:
            self.waveform = waveform.buckets
            self.waveform_starts = waveform.starts
            self._waveform_duration_ms = waveform.content_duration_ms
            if self._file_identity is not None and self.waveform:
                self._waveform_cache = (self._file_identity, waveform)
        self.waveform_loading = False
        self._apply_pending_position()
        self.timeline_changed.emit()
        self.changed.emit()

    def _playback_state_changed(
        self, state: QMediaPlayer.PlaybackState,
    ) -> None:
        self.changed.emit()
        if state != QMediaPlayer.PlaybackState.PlayingState:
            self._resume_fallback_waveform()

    def _waveform_error(self, _error: QAudioDecoder.Error) -> None:
        if self._fallback_decoder is not None and self.sender() is self._fallback_decoder:
            self._stop_fallback_waveform()
            self._publish_waveform(None)

    def _playback_error(self, _error: QMediaPlayer.Error, error_string: str) -> None:
        self._pending_project_position_ms = None
        self._play_when_seekable = False
        if error_string and isinstance(self.parent(), QWidget):
            show_global_toast(
                self.parent(),
                trf("参考音频无法播放：{error}", error=error_string),
                kind="warning",
                duration_ms=4200,
            )
