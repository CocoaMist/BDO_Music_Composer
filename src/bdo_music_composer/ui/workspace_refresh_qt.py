"""Focused Qt execution of immutable workspace refresh plans."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QSignalBlocker

from bdo_music_composer.app.workspace_refresh_controller import RefreshPlan
from bdo_music_composer.ui.i18n import trf


class WorkspaceRefreshHost(Protocol):
    timeline: object
    tracks: list
    bpm: int
    bpm_override: int | None
    time_sig: int
    beat_origin_ms: float
    _pitch_transform_plan: object

    def _advance_model_revision(self, reason: str) -> object: ...
    def _sync_global_bpm_control(self) -> None: ...
    def _sync_toolbar_global_gain(self) -> None: ...
    def _update_ensemble_metric(self) -> None: ...
    def _refresh_transcription_workspace(self) -> None: ...
    def _schedule_timeline_validation_refresh(self) -> None: ...


def sync_timeline_viewport_controls(host: WorkspaceRefreshHost) -> None:
    """Reflect visual navigation without reporting a project edit."""
    timeline = host.timeline
    if hasattr(host, "timeline_zoom"):
        with QSignalBlocker(host.timeline_zoom):
            host.timeline_zoom.setValue(round(timeline.zoom_factor * 100))
    if hasattr(host, "timeline_pan"):
        with QSignalBlocker(host.timeline_pan):
            host.timeline_pan.setValue(timeline.pan_percent())
            host.timeline_pan.setEnabled(timeline.zoom_factor > 1.0)


def apply_workspace_refresh(host: WorkspaceRefreshHost, plan: RefreshPlan) -> None:
    """Execute one plan while issuing at most one redundant-free paint request."""

    if plan.advance_revision:
        host._advance_model_revision("track state")

    timeline_invalidated = False
    if plan.rebuild_timeline:
        auto_group = getattr(host, "_auto_group_same_instrument_tracks", None)
        if callable(auto_group):
            auto_group()
        host.timeline.set_tracks(host.tracks)
        synchronize_markers = getattr(
            host, "_synchronize_timeline_markers", None
        )
        if callable(synchronize_markers):
            synchronize_markers()
        timeline_invalidated = True
    elif plan.changed_track_ids:
        if plan.reindex_track_ids:
            host.timeline.update_tracks(plan.reindex_track_ids)
        else:
            host.timeline.update_track_presentation(plan.changed_track_ids)
        timeline_invalidated = True

    if plan.refresh_grid:
        host.timeline.set_pitch_transform_plan(host._pitch_transform_plan)
        host.timeline.set_musical_grid(
            host.bpm_override or host.bpm,
            host.time_sig,
            host.beat_origin_ms,
        )
        timeline_invalidated = True

    if plan.refresh_view and not timeline_invalidated:
        host.timeline.update()

    if plan.refresh_metadata and hasattr(host, "timeline_meta"):
        host.timeline_meta.setText(
            trf(
                "{count} 轨 · {meter}/4",
                count=len(host.tracks),
                meter=host.time_sig,
            )
        )
        host._sync_global_bpm_control()
        host._sync_toolbar_global_gain()

    sync_timeline_viewport_controls(host)

    if plan.refresh_ensemble:
        host._update_ensemble_metric()
    if plan.refresh_transcription:
        host._refresh_transcription_workspace()
    if plan.refresh_validation:
        host._schedule_timeline_validation_refresh()
    if hasattr(host, "workbench"):
        host.workbench.refresh()


__all__ = ["WorkspaceRefreshHost", "apply_workspace_refresh", "sync_timeline_viewport_controls"]
