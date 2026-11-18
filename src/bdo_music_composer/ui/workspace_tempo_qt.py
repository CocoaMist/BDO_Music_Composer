"""Workspace-level global tempo and reference-audio tempo follow."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)
from shiboken6 import isValid

from bdo_export import BDO_BPM_MAX
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentConfig,
)
from bdo_music_composer.transcription.reference_tempo import estimate_reference_tempo
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol
from bdo_music_composer.ui.ui_controls import GlyphSpinBox


BDO_STATIC_BPM_MAX = BDO_BPM_MAX


class _ReferenceTempoSignals(QObject):
    completed = Signal(object, object)


class ReferenceTempoWorker(QRunnable):

    def __init__(
        self,
        path: str | Path,
        *,
        prior_bpm: float,
    ) -> None:
        super().__init__()
        self.signals = _ReferenceTempoSignals()
        self.path = str(path)
        self.prior_bpm = float(prior_bpm)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def run(self) -> None:
        try:
            estimate = estimate_reference_tempo(
                self.path,
                prior_bpm=self.prior_bpm,
                cancelled=self._cancelled.is_set,
            )
        except Exception:
            estimate = None
        # Qt can tear down the signal object before the process-wide pool
        # has joined a canceled analysis at application shutdown.
        if isValid(self.signals):
            try:
                self.signals.completed.emit(self, estimate)
            except RuntimeError:
                if isValid(self.signals):
                    raise


class WorkspaceTempoHostMixin:
    """Keep one project BPM authoritative across editor consumers."""

    def _displayed_global_bpm(self) -> int:
        return min(BDO_STATIC_BPM_MAX, max(1, int(self.bpm_override or self.bpm)))

    def _build_global_bpm_control(self) -> QWidget:
        self.reference_tempo_worker = None
        self._pending_reference_tempo_path = ""
        control = QFrame()
        self.global_bpm_control = control
        control.setObjectName("GlobalBpmControl")
        control.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.CONTROL_GAP)
        self.global_bpm_label = QLabel("BPM")
        self.global_bpm_label.setObjectName("TimelineControlLabel")
        self.global_bpm_label.setAccessibleName(tr("全局 BPM"))
        self.global_bpm_spin = GlyphSpinBox()
        self.global_bpm_spin.setObjectName("GlobalBpmSpin")
        self.global_bpm_spin.setRange(1, BDO_STATIC_BPM_MAX)
        self.global_bpm_spin.setKeyboardTracking(False)
        self.global_bpm_spin.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.global_bpm_spin.setFixedWidth(72)
        self.global_bpm_spin.setAccessibleName(tr("全局 BPM"))
        self.global_bpm_spin.lineEdit().setAccessibleName(tr("全局 BPM"))
        self.global_bpm_label.setBuddy(self.global_bpm_spin)
        tooltip = tr(
            "所有轨道共用；同步时间网格、试听、分析、自动保存和 BDO 导出。"
            "导出兼容范围 1–200；游戏官方作曲指南当前标注上限 180。"
        )
        control.setToolTip(tooltip)
        self.global_bpm_spin.setToolTip(tooltip)
        self.global_bpm_spin.setValue(self._displayed_global_bpm())
        self.global_bpm_spin.editingFinished.connect(
            self._commit_global_bpm_from_control
        )
        self.reference_bpm_follow = QToolButton()
        self.reference_bpm_follow.setObjectName("ReferenceBpmFollow")
        self.reference_bpm_follow.setProperty("kind", "ghost")
        set_fluent_symbol(
            self.reference_bpm_follow, FluentSymbol.AUTO_TEMPO,
            checked_symbol=FluentSymbol.AUTO_TEMPO_ACTIVE,
        )
        self.reference_bpm_follow.setIconSize(QSize(10, 10))
        self.reference_bpm_follow.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.reference_bpm_follow.setCheckable(True)
        self.reference_bpm_follow.setText(tr("自动跟随"))
        self.reference_bpm_follow.setAccessibleName(tr("跟随参考 BPM"))
        self.reference_bpm_follow.setToolTip(
            tr("参考音频分析得到可靠节拍后，自动更新工程全局 BPM")
        )
        self.reference_bpm_follow.setChecked(
            bool(self.reference_layer_settings.get("follow_reference_bpm", True))
        )
        has_reference = bool(self.reference_audio_path)
        self.reference_bpm_follow.setEnabled(has_reference)
        self.reference_bpm_follow.setVisible(has_reference)
        self.reference_bpm_follow.toggled.connect(
            self._reference_bpm_follow_toggled
        )
        layout.addWidget(self.global_bpm_label)
        layout.addWidget(self.global_bpm_spin)
        layout.addWidget(self.reference_bpm_follow)
        return control

    def _sync_global_bpm_control(self) -> None:
        if not hasattr(self, "global_bpm_spin"):
            return
        self.global_bpm_spin.blockSignals(True)
        self.global_bpm_spin.setValue(self._displayed_global_bpm())
        self.global_bpm_spin.blockSignals(False)
        self._sync_reference_bpm_follow_control()

    def _sync_reference_bpm_follow_control(self) -> None:
        if not hasattr(self, "reference_bpm_follow"):
            return
        self.reference_bpm_follow.blockSignals(True)
        self.reference_bpm_follow.setChecked(
            bool(self.reference_layer_settings.get("follow_reference_bpm", True))
        )
        has_reference = bool(self.reference_audio_path)
        self.reference_bpm_follow.setEnabled(has_reference)
        self.reference_bpm_follow.setVisible(has_reference)
        self.reference_bpm_follow.blockSignals(False)

    def _set_global_bpm_compact(self, compact: bool) -> None:
        if not hasattr(self, "global_bpm_spin"):
            return
        self.global_bpm_label.setVisible(True)
        self.reference_bpm_follow.setText("AUTO" if compact else tr("自动跟随"))
        self.reference_bpm_follow.setFixedWidth(
            max(48 if compact else 72, self.reference_bpm_follow.sizeHint().width())
        )

    def _commit_global_bpm_from_control(self) -> None:
        new_bpm = int(self.global_bpm_spin.value())
        if new_bpm == self._displayed_global_bpm():
            return
        self.reference_layer_settings["follow_reference_bpm"] = False
        self._pending_reference_tempo_path = ""
        self._cancel_reference_tempo_worker()
        self._sync_reference_bpm_follow_control()
        self._apply_global_bpm(
            new_bpm,
            autosave_reason="global bpm",
            toast=trf(
                "全局 BPM 已设为 {bpm}；已停止自动跟随参考音乐",
                bpm=new_bpm,
            ),
        )

    def _apply_global_bpm(
        self,
        new_bpm: int,
        *,
        autosave_reason: str,
        toast: str,
    ) -> bool:
        new_bpm = max(1, min(BDO_STATIC_BPM_MAX, int(new_bpm)))
        if new_bpm == int(self.bpm_override or self.bpm):
            self._autosave_project(autosave_reason, immediate=True)
            return False
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.bpm_override = new_bpm
        self._invalidate_transcription_rhythm_diagnostic()
        self.automatic_harmony_analysis = None
        self.harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.instrument_match_analysis = None
        self._apply_workspace_change(ModelChange.grid())
        self._schedule_timeline_validation_refresh()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis()
            self._start_reference_timbre_analysis(force_restart=True)
        self._autosave_project(autosave_reason, immediate=True)
        self.show_toast(toast, kind="success")
        return True

    def _reference_bpm_follow_toggled(self, checked: bool) -> None:
        self.reference_layer_settings["follow_reference_bpm"] = bool(checked)
        if checked and self.transcription_result is not None:
            self._maybe_start_reference_bpm_follow(interval=False)
        elif checked and self.reference_audio_path:
            self._start_reference_tempo_analysis(self.reference_audio_path)
        elif not checked:
            self._pending_reference_tempo_path = ""
            self._cancel_reference_tempo_worker()
        if not self.loading_project:
            self._autosave_project("reference bpm follow", immediate=True)

    def _maybe_start_reference_bpm_follow(self, *, interval: bool) -> bool:
        if (
            interval
            or not self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
            or self.transcription_rhythm_runner.busy
            or not self.transcription_session.state.cache_key
            or not self.transcription_session.candidates
        ):
            return False
        self._reference_bpm_follow_pending = True
        started = self.transcription_rhythm_runner.start_diagnostic(
            cache_key=self.transcription_session.state.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            settings=self._current_project_rhythm_settings(),
            alignment_config=RhythmAlignmentConfig(profile="auto"),
        )
        if not started:
            self._reference_bpm_follow_pending = False
        return started

    def _consume_reference_bpm_follow_result(self, sidecar: object) -> bool:
        if not getattr(self, "_reference_bpm_follow_pending", False):
            return False
        self._reference_bpm_follow_pending = False
        alignment = getattr(sidecar, "alignment", None)
        estimate = getattr(alignment, "estimate", None)
        self._apply_reference_tempo_estimate(estimate)
        return True

    def _apply_reference_tempo_estimate(self, estimate: object) -> bool:
        reliable = bool(
            estimate is not None
            and not bool(getattr(estimate, "used_project_fallback", False))
            and float(getattr(estimate, "confidence", 0.0)) >= 0.58
            and int(getattr(estimate, "beat_count", 0)) >= 8
            and float(getattr(estimate, "tempo_drift_ratio", 1.0)) <= 0.12
        )
        if not reliable:
            self._set_transcription_status(
                tr("参考 BPM 证据不足；保留当前全局 BPM，可手动调节")
            )
            return False
        detected_value = float(getattr(estimate, "detected_bpm"))
        while detected_value > BDO_STATIC_BPM_MAX:
            detected_value /= 2.0
        while detected_value < 30.0 and detected_value * 2.0 <= BDO_STATIC_BPM_MAX:
            detected_value *= 2.0
        detected = max(1, min(BDO_STATIC_BPM_MAX, round(detected_value)))
        changed = self._apply_global_bpm(
            detected,
            autosave_reason="reference bpm follow",
            toast=trf(
                "已跟随参考音乐：全局 BPM {bpm} · 置信 {confidence}%",
                bpm=detected,
                confidence=round(float(getattr(estimate, "confidence")) * 100),
            ),
        )
        if not changed:
            self._set_transcription_status(
                trf("参考音乐 BPM 与工程一致：{bpm}", bpm=detected)
            )
        return True

    def _reference_bpm_follow_stopped(self) -> None:
        self._reference_bpm_follow_pending = False

    def _reference_bpm_audio_changed(self, path: str) -> None:
        self._sync_reference_bpm_follow_control()
        should_analyze = bool(path) and bool(
            self.reference_layer_settings.get("follow_reference_bpm", True)
        )
        self._pending_reference_tempo_path = path if should_analyze else ""
        self._cancel_reference_tempo_worker()
        if should_analyze and getattr(self, "reference_tempo_worker", None) is None:
            self._start_reference_tempo_analysis(path)

    def _start_reference_tempo_analysis(self, path: str) -> None:
        if getattr(self, "reference_tempo_worker", None) is not None:
            self._pending_reference_tempo_path = path
            return
        self._pending_reference_tempo_path = ""
        worker = ReferenceTempoWorker(
            path,
            prior_bpm=float(self.bpm_override or self.bpm),
        )
        self.reference_tempo_worker = worker
        worker.signals.completed.connect(
            self._reference_tempo_completed, Qt.ConnectionType.QueuedConnection,
        )
        self._set_transcription_status(tr("正在检测参考音乐 BPM…"))
        # The pool owns the running native thread beyond window teardown.
        QThreadPool.globalInstance().start(worker)

    def _reference_tempo_completed(self, worker: ReferenceTempoWorker, estimate: object) -> None:
        if estimate is None:
            self._reference_tempo_failed(worker)
        else:
            self._reference_tempo_succeeded(worker, estimate)
        self._reference_tempo_finished(worker)

    def _reference_tempo_succeeded(
        self,
        worker: ReferenceTempoWorker,
        estimate: object,
    ) -> None:
        if (
            worker is not getattr(self, "reference_tempo_worker", None)
            or getattr(worker, "cancelled", False)
            or worker.path != self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
        ):
            return
        self._apply_reference_tempo_estimate(estimate)

    def _reference_tempo_failed(self, worker: ReferenceTempoWorker) -> None:
        if (
            worker is getattr(self, "reference_tempo_worker", None)
            and not getattr(worker, "cancelled", False)
        ):
            self._set_transcription_status(
                tr("未能可靠检测参考 BPM；保留当前值，可手动调节")
            )

    def _reference_tempo_finished(self, worker: ReferenceTempoWorker) -> None:
        if worker is not getattr(self, "reference_tempo_worker", None):
            return
        self.reference_tempo_worker = None
        if getattr(self, "workspace_close_pending", False):
            self._pending_reference_tempo_path = ""
            QTimer.singleShot(0, self, self.close)
            return
        pending_path = getattr(self, "_pending_reference_tempo_path", "")
        if pending_path:
            self._start_pending_reference_tempo_analysis(pending_path)

    def _start_pending_reference_tempo_analysis(self, path: str) -> None:
        if (
            path != self.reference_audio_path
            or not bool(
                self.reference_layer_settings.get("follow_reference_bpm", True)
            )
        ):
            return
        self._start_reference_tempo_analysis(path)

    def _cancel_reference_tempo_worker(self) -> None:
        worker = getattr(self, "reference_tempo_worker", None)
        if worker is not None:
            worker.cancel()

__all__ = ["BDO_STATIC_BPM_MAX", "WorkspaceTempoHostMixin"]
