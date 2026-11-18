"""Packaged, visible-range-indexed multitrack timeline canvas."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QRegion,
)
from PySide6.QtWidgets import QApplication, QMenu, QScrollBar, QWidget

from bdo_music_composer.editor.bdo_instrument_adaptation import instrument_editor_display_adaptations
from bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt import (
    InstrumentLaneArtwork,
    instrument_header_background_rect,
    paint_instrument_header_background,
)
from bdo_midi.instruments import (
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
)
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState, note_name
from bdo_music_composer.editor.game_score_model import serialized_game_instrument_id
from .editor_ui_helpers import (
    add_instrument_submenus,
    articulation_color,
)
from .timeline_velocity_curve_qt import TimelineVelocityCurveOverlay
from .timeline_clip_hit import (
    HitRegion,
    TimelineHitIndex,
    clip_action_at,
    marquee_damage,
    marquee_rect,
)
from .timeline_clip_metadata_qt import (
    CLIP_BODY_INSET, CLIP_LANE_INSET, CLIP_REGION_INSET,
    CLIP_CORNER_RADIUS, CLIP_TITLE_HEIGHT, CLIP_TITLE_MIN_HEIGHT, CLIP_TITLE_MIN_WIDTH,
    clip_display_rect, clip_end_handle_visible, clip_identity_color, paint_clip_selection,
    paint_track_clip_metadata,
)
from .timeline_empty_state import paint_empty_score_guidance
from .timeline_marker_paint import TimelineMarkerLayer
from .timeline_reference_audio_qt import (
    ReferenceAudioView,
    build_reference_audio_menu,
    position_reference_audio_controls,
)
from .timeline_selection_scope import (
    press_empty_track_space,
    reset_marquee_selection,
    seek_empty_grid,
    select_pointer_track,
    selection_descriptor,
)
from . import timeline_track_identity as track_identity
from bdo_music_composer.ui.floating_panel_qt import exec_floating_panel
from bdo_music_composer.ui.i18n import tr, trf, trv
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fonts_qt import canvas_caption_font
from bdo_music_composer.ui.theme.symbols import paint_centered_symbol
from bdo_music_composer.ui.ui_controls import PillButton
from bdo_music_composer.editor.interval_index import IntervalIndex
from bdo_music_composer.editor.arrangement_clip import (
    MIN_CLIP_DURATION_MS,
    clip_by_id,
    project_track_notes,
    track_clips,
)
from bdo_music_composer.editor.pitch_transform import (
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
)
from bdo_music_composer.editor.track_group import move_group_block
from bdo_music_composer.editor.timeline_markers import normalize_timeline_markers
from bdo_music_composer.editor.arrangement_snap import (
    ArrangementSnapResult,
    ArrangementSnapIndex,
    ArrangementSnapTarget,
    build_snap_index,
    snap_clip_start,
)
from bdo_music_composer.editor.arrangement_navigation import (
    neighboring_boundary,
    normalized_boundaries,
    timeline_grid_step_ms,
    viewport_for_range,
)
from bdo_music_composer.core.project_paths import ASSETS_DIR


TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background_v2.webp"
TIMELINE_BACKGROUND_OPACITY = 0.24
_METER_LOW = QColor("#83a543")
_METER_HIGH = QColor("#caa24f")
_METER_PEAK = QColor("#d05c4f")
_METER_UNLIT = QColor("#343438")


@dataclass(frozen=True, slots=True)
class _TimelineNoteOverviewBin:
    start: float
    end: float
    pitch_min: int
    pitch_max: int
    pitch_mask: int
    articulation_type: int


@dataclass(frozen=True, slots=True)
class _TimelineNoteOverviewLevel:
    bucket_count: int
    bins: tuple[_TimelineNoteOverviewBin, ...]
    starts: tuple[float, ...]
    max_span: float


@dataclass(frozen=True, slots=True)
class _ArrangementGroupView:
    group_id: str
    first_row: int
    last_row: int
    members: tuple[TrackState, ...]
    instrument_id: int
    color: str
    note_count: int
    clip_count: int

    @property
    def count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class _TimelineTrackNoteIndex:
    intervals: IntervalIndex[object]
    clips: IntervalIndex[ArrangementClipState]
    pitch_min: int
    pitch_max: int
    overview_levels: tuple[_TimelineNoteOverviewLevel, ...]


@dataclass(frozen=True, slots=True)
class TimelineClipEditRequest:
    source_track: TrackState
    target_track: TrackState
    mode: str
    new_start_ms: float
    new_end_ms: float
    clip_id: str


@dataclass(frozen=True, slots=True)
class TimelineClipSplitRequest:
    track: TrackState
    clip_id: str
    split_ms: float


@dataclass(frozen=True, slots=True)
class TimelineClipsMoveRequest:
    selections: tuple[tuple[TrackState, str], ...]
    delta_ms: float
    track_offset: int = 0
    primary_key: tuple[int, str] | None = None


def _paint_track_selection_marker(
    painter: QPainter, left: float, top: float, lane_height: float, color: QColor,
) -> None:
    height = min(14.0, lane_height - 8.0)
    marker = QRectF(left, top + (lane_height - height) / 2, 2, height)
    painter.fillRect(marker, color)


def _ui_bdo_instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


def _ui_bdo_instrument_names() -> dict[int, str]:
    return localized_bdo_instrument_names(tr)

class TimelineCanvas(QWidget):
    changed = Signal()
    viewport_changed = Signal()
    reference_audio_offset_requested = Signal()
    track_state_changed = Signal()
    game_volume_committed = Signal(object, int, int)
    instrument_changed = Signal(object, int)
    mixer_unify_requested = Signal(object)
    merge_track_requested = Signal(object)
    create_track_requested = Signal(int)
    move_track_requested = Signal(object, int)
    delete_track_requested = Signal(object)
    duplicate_track_requested = Signal(object)
    rename_track_requested = Signal(object)
    color_track_requested = Signal(object)
    clear_solo_requested = Signal()
    unmute_all_requested = Signal()
    selected = Signal(object)
    selection_scope_changed = Signal(object)
    effects_requested = Signal(object)
    pitch_requested = Signal(object)
    midi_tools_requested = Signal(object)
    clip_velocity_base_requested = Signal(object)
    note_editor_requested = Signal(object)
    clip_note_editor_requested = Signal(object, str)
    seek_requested = Signal(float)
    time_range_changed = Signal(object)
    playhead_changed = Signal(float)
    velocity_curve_committed = Signal(object, object)
    clip_edit_requested = Signal(object)
    clip_create_requested = Signal(object, float)
    clip_split_requested = Signal(object)
    clip_copy_requested = Signal(object, str)
    clip_duplicate_requested = Signal(object, str)
    clip_repeat_requested = Signal(object, str)
    clip_crop_requested = Signal(object, str)
    clips_consolidate_requested = Signal(object)
    clip_rename_requested = Signal(object, str)
    clip_color_requested = Signal(object, str)
    clip_paste_requested = Signal(object, float)
    clip_delete_requested = Signal(object, str)
    clips_delete_requested = Signal(object)
    clips_move_requested = Signal(object)
    marker_edit_requested = Signal(object)
    group_control_requested = Signal(object, str)
    fit_width_requested = Signal()
    layout_preferences_changed = Signal()
    TRACK_NOTE_QUERY_BLOCK_SIZE = 128
    TRACK_CLIP_QUERY_BLOCK_SIZE = 64
    GRID_MIN_TICK_SPACING_PX = 56.0
    MEASURE_BANDING_MIN_WIDTH_PX = 72.0
    GRID_MIN_GUIDE_SPACING_PX = 10.0
    EDIT_TAIL_MEASURES = 8
    EDIT_TAIL_MIN_MS = 10_000.0
    NOTE_OVERVIEW_BUCKET_PX = 3.0
    NOTE_OVERVIEW_LEVELS = (256,)
    METER_SEGMENT_COUNT = 10
    TRACK_SCROLL_GUTTER = 12
    KEYBOARD_SHORTCUT_HINT = (
        "F1 快捷键；W/H 适配视图；U 折叠/展开组；Ctrl+D 复制片段；"
        "Ctrl+E 在播放头切分；Enter 编辑焦点；方向键导航"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.tracks: list[TrackState] = []
        self._arrangement_group_counts: dict[str, int] = {}
        self._arrangement_groups: dict[str, _ArrangementGroupView] = {}
        self._arrangement_group_by_row: dict[int, _ArrangementGroupView] = {}
        self._collapsed_arrangement_groups: set[str] = set()
        self._visible_track_rows_cache: tuple[tuple[int, TrackState], ...] | None = None
        self._visual_rows_by_identity: dict[int, int] = {}
        self._selected_arrangement_group_id = ""
        self.timeline_markers: list[dict[str, object]] = []
        self._timeline_marker_times: tuple[float, ...] = ()
        self._marker_layer = TimelineMarkerLayer()
        self.hit_regions: list[tuple[QRectF, str, object]] = []
        self.track_validation_notices: dict[int, dict[str, tuple]] = {}
        self._validation_hover_track_id: int | None = None
        self._track_control_hover_pos: QPointF | None = None
        self.reference_audio: ReferenceAudioView | None = None
        self._reference_audio_relink_required = False
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.bpm = 120
        self.time_sig = 4
        self.beat_origin_ms = 0.0
        self.buffer_progress = 0.0
        self.buffer_visible = False
        self.track_levels: dict[int, int] = {}
        self.grid_rect = QRectF()
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.range_start_ms: float | None = None
        self.range_end_ms: float | None = None
        self._range_drag_anchor_ms: float | None = None
        self._range_drag_mode = ""
        self._range_drag_moved = False
        self._volume_drag_track: TrackState | None = None
        self._volume_drag_rect = QRectF()
        self._volume_drag_initial = 70
        self._clip_drag_source: TrackState | None = None
        self._clip_drag_target: TrackState | None = None
        self._clip_drag_mode = ""
        self._clip_drag_active = False
        self._clip_drag_press_ms = 0.0
        self._clip_drag_press_pos = QPointF()
        self._clip_drag_origin_press_ms = 0.0
        self._clip_drag_origin_start_ms = 0.0
        self._clip_drag_origin_end_ms = 0.0
        self._clip_drag_start_ms = 0.0
        self._clip_drag_end_ms = 0.0
        self._clip_drag_max_end_ms = math.inf
        self._clip_drag_id = ""
        self._clip_group_drag_keys: tuple[tuple[int, str], ...] = ()
        self._clip_group_drag_origins: dict[
            tuple[int, str], tuple[float, float]
        ] = {}
        self._clip_group_drag_track_offset = 0
        self._selected_clip_id = ""
        self.clip_paste_available = False
        self._selected_clip_track_id: int | None = None
        self._selected_clip_keys: set[tuple[int, str]] = set()
        self._selected_track_ids: set[int] = set()
        self._focus_scope = "track"
        self._viewport_history: list[tuple[float, float]] = []
        self._header_width = 276
        self._lane_height_px = 68
        self._reference_lane_height_px = 68
        self._reference_load_button = PillButton("", "ghost", FluentSymbol.OPEN)
        self._reference_load_button.setParent(self)
        self._reference_load_button.setObjectName("TimelineReferenceLoad")
        self._reference_load_button.setFixedHeight(hig.BUTTON_HEIGHT)
        self._reference_load_button.clicked.connect(self._choose_reference_audio)
        self._reference_menu_button = PillButton("", "ghost", FluentSymbol.MORE)
        self._reference_menu_button.setParent(self)
        self._reference_menu_button.setObjectName("TimelineReferenceMenu")
        self._reference_menu_button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        self._reference_menu_button.clicked.connect(self._open_reference_audio_menu)
        self._reference_load_button.hide()
        self._reference_menu_button.hide()
        self._layout_drag_mode = ""
        self._layout_hover_handle = ""
        self._layout_drag_origin = QPointF()
        self._layout_drag_initial = 0
        self._marquee_press_pos: QPointF | None = None
        self._marquee_current_pos = QPointF()
        self._marquee_active = False
        self._marquee_modifiers = Qt.NoModifier
        self._marquee_base_clip_keys: set[tuple[int, str]] = set()
        self._marquee_preview_clip_keys: set[tuple[int, str]] = set()
        self._marquee_origin_clip: tuple[TrackState, str] | None = None
        self.snap_enabled = True
        self._clip_snap_targets = ArrangementSnapIndex((), ())
        self._clip_snap_result = ArrangementSnapResult(0.0)
        self.arrangement_tool = "select"
        self._merge_overlap_track_id: int | None = None
        self._merge_overlap_regions: tuple[object, ...] = ()
        self.selected_track: TrackState | None = None
        self.pitch_transform_plan = PitchTransformPlan()
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self._scaled_background = QPixmap()
        self._scaled_background_size = QSize()
        self._instrument_adaptations = instrument_editor_display_adaptations()
        self.instrument_lane_art = InstrumentLaneArtwork()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        self.velocity_curve_overlay = TimelineVelocityCurveOverlay(self)
        self.velocity_curve_overlay.commit_requested.connect(
            self.velocity_curve_committed.emit
        )
        self._track_note_indexes: dict[int, _TimelineTrackNoteIndex] = {}
        self._last_track_note_query_inspections = 0
        self._last_track_clip_query_inspections = 0
        self._conversion_note_keys: dict[int, frozenset[tuple[object, ...]]] = {}
        self._conversion_problem_masks: dict[int, int] = {}
        self._timeline_end_cache = 1.0
        # The multitrack page is mostly static while playback advances.  Keep
        # notes, headers, artwork, text, grid and waveform in one device-local
        # pixmap so a narrow playhead update does not re-run every visible
        # interval query and every text/layout operation at audio-frame rate.
        self._static_timeline_cache = QPixmap()
        self._static_timeline_cache_key: tuple[object, ...] | None = None
        self._static_timeline_hit_regions: list[tuple[QRectF, str, object]] = []
        self._hit_region_index = TimelineHitIndex()
        self._viewport_motion_active = False
        self._viewport_motion_timer = QTimer(self)
        self._viewport_motion_timer.setSingleShot(True)
        self._viewport_motion_timer.setInterval(140)
        self._viewport_motion_timer.timeout.connect(
            self._finish_viewport_motion
        )
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self._track_scroll_changed)
        self.setObjectName("TimelineCanvas")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(tr("轨道时间轴"))
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self.setStatusTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.setMouseTracking(True)
        self.setMinimumHeight(380)

    def set_arrangement_tool(self, tool: str) -> None:
        normalized = str(tool or "select")
        if normalized not in {"marquee", "select", "razor"}:
            normalized = "select"
        self.arrangement_tool = normalized
        self.unsetCursor()
        self.update()

    def set_instrument_art_dir(self, directory: str | Path | None) -> int:
        """Preload optional user artwork; painting remains filesystem-free."""

        loaded = self.instrument_lane_art.reload(
            directory,
            {
                instrument_id: adaptation.visual_key
                for instrument_id, adaptation
                in self._instrument_adaptations.items()
            },
        )
        self._static_timeline_cache_key = None
        self.update()
        return loaded

    def set_tracks(self, tracks: list[TrackState]) -> None:
        self.tracks = tracks
        self._rebuild_track_indexes()
        self._rebuild_arrangement_group_views()
        self.clear_merge_overlap_regions()
        self.velocity_curve_overlay.synchronize_tracks(tracks)
        tracks_by_id = {int(track.track_id): track for track in tracks}
        selected_track_id = (
            int(self.selected_track.track_id)
            if self.selected_track is not None
            else None
        )
        self.selected_track = tracks_by_id.get(selected_track_id)
        valid_clip_keys = {
            (int(track.track_id), str(clip.clip_id))
            for track in tracks
            for clip in self._track_note_indexes[id(track)].clips.items
        }
        self._selected_clip_keys.intersection_update(valid_clip_keys)
        primary_key = (
            self._selected_clip_track_id,
            self._selected_clip_id,
        )
        if self._selected_clip_keys:
            if primary_key not in self._selected_clip_keys:
                primary_key = next(
                    (int(track.track_id), str(clip.clip_id))
                    for track in tracks
                    for clip in self._track_note_indexes[id(track)].clips.items
                    if (int(track.track_id), str(clip.clip_id))
                    in self._selected_clip_keys
                )
            self._selected_clip_track_id = primary_key[0]
            self._selected_clip_id = primary_key[1]
            self.selected_track = tracks_by_id[primary_key[0]]
        else:
            self._clear_clip_selection()
        valid_track_ids = {int(track.track_id) for track in tracks}
        self.track_validation_notices = {
            track_id: notice
            for track_id, notice in self.track_validation_notices.items()
            if track_id in valid_track_ids
        }
        self.track_levels = {
            track_id: level for track_id, level in self.track_levels.items()
            if track_id in valid_track_ids
        }
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self.setMinimumHeight(160 if self.property("composerWorkbench") else 380)
        self._update_track_scrollbar()
        self._update_accessible_track_state()
        self.update()

    def _rebuild_arrangement_group_views(self) -> None:
        rows_by_group: dict[str, list[int]] = {}
        members_by_group: dict[str, list[TrackState]] = {}
        for row, track in enumerate(self.tracks):
            group_id = str(track.arrangement_group_id or "")
            if group_id:
                rows_by_group.setdefault(group_id, []).append(row)
                members_by_group.setdefault(group_id, []).append(track)
        groups: dict[str, _ArrangementGroupView] = {}
        by_row: dict[int, _ArrangementGroupView] = {}
        for group_id, rows in rows_by_group.items():
            members = tuple(members_by_group[group_id])
            if len(members) < 2:
                continue
            view = _ArrangementGroupView(
                group_id, rows[0], rows[-1], members,
                int(members[0].bdo_instrument_id), str(members[0].color),
                sum(len(member.notes) for member in members),
                sum(
                    len(self._track_note_indexes[id(member)].clips.items)
                    for member in members
                ),
            )
            groups[group_id] = view
            for row in rows:
                by_row[row] = view
        self._arrangement_groups = groups
        self._arrangement_group_by_row = by_row
        self._collapsed_arrangement_groups.intersection_update(groups)
        self._visible_track_rows_cache = None
        self._arrangement_group_counts = {
            group_id: view.count for group_id, view in groups.items()
        }
        if self._selected_arrangement_group_id not in groups:
            self._selected_arrangement_group_id = ""

    def _visible_track_rows(self) -> tuple[tuple[int, TrackState], ...]:
        """Return original row identities after presentation-only folding."""

        if self._visible_track_rows_cache is None:
            self._visible_track_rows_cache = tuple(
                (row, track)
                for row, track in enumerate(self.tracks)
                if (
                    not (group_id := str(track.arrangement_group_id or ""))
                    or group_id not in self._collapsed_arrangement_groups
                    or row == self._arrangement_groups[group_id].first_row
                )
            )
            self._visual_rows_by_identity = {
                id(track): visual_row
                for visual_row, (_row, track) in enumerate(self._visible_track_rows_cache)
            }
        return self._visible_track_rows_cache

    def _visual_row_for_track(self, track: TrackState) -> int | None:
        group_id = str(track.arrangement_group_id or "")
        representative = (
            self._arrangement_groups[group_id].members[0]
            if group_id in self._collapsed_arrangement_groups
            else track
        )
        self._visible_track_rows()
        return self._visual_rows_by_identity.get(id(representative))

    def _set_group_collapsed(self, group_id: str, collapsed: bool) -> None:
        group = self._arrangement_groups.get(str(group_id))
        if group is None:
            return
        if collapsed:
            self._collapsed_arrangement_groups.add(group.group_id)
            if self.selected_track in group.members[1:]:
                self._select_track(group.members[0], emit=True)
        else:
            self._collapsed_arrangement_groups.discard(group.group_id)
        self._visible_track_rows_cache = None
        self._static_timeline_cache_key = None
        self._update_track_scrollbar()
        self.update()

    def can_set_all_groups_collapsed(self, collapsed: bool) -> bool:
        """Report whether folding or unfolding all groups would change the view."""

        if collapsed:
            return bool(self._arrangement_groups.keys() - self._collapsed_arrangement_groups)
        return bool(self._collapsed_arrangement_groups)

    def set_all_groups_collapsed(self, collapsed: bool) -> None:
        """Fold or unfold every automatic Group without mutating Tracks."""

        next_groups = set(self._arrangement_groups) if collapsed else set()
        if next_groups == self._collapsed_arrangement_groups:
            return
        self._collapsed_arrangement_groups = next_groups
        if collapsed and self.selected_track is not None:
            group_id = str(self.selected_track.arrangement_group_id or "")
            group = self._arrangement_groups.get(group_id)
            if group is not None and self.selected_track in group.members[1:]:
                self._select_track(group.members[0], emit=True)
        self._visible_track_rows_cache = None
        self._static_timeline_cache_key = None
        self._update_track_scrollbar()
        self.update()

    def fit_track_rows(self) -> None:
        """Fit as many arrangement rows as possible into the current height."""

        row_count = len(self._visible_track_rows())
        if row_count <= 0:
            return
        area, _header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        available = max(
            44,
            int(area.height() - ruler_h - self._reference_audio_lane_height()),
        )
        self.set_layout_metrics(
            lane_height=max(44, min(104, available // row_count)),
            notify=True,
        )

    def reset_layout_metrics(self) -> None:
        """Restore the stable standard timeline density."""

        self.set_layout_metrics(
            header_width=276,
            lane_height=68,
            reference_lane_height=68,
            notify=True,
        )

    def set_timeline_markers(self, markers: object) -> None:
        self.timeline_markers = list(normalize_timeline_markers(markers))
        self._timeline_marker_times = tuple(
            float(marker["time_ms"]) for marker in self.timeline_markers
        )
        self._marker_layer.invalidate()
        self.update()

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = bool(enabled)

    def _snap_drag_time(
        self,
        proposed_ms: float,
        duration_ms: float,
        modifiers: Qt.KeyboardModifier,
    ) -> float:
        """Snap one drag edge using a stable screen-space tolerance."""

        proposed_ms = max(0.0, float(proposed_ms))
        if not self.snap_enabled or modifiers & Qt.AltModifier:
            self._clip_snap_result = ArrangementSnapResult(proposed_ms)
            return proposed_ms
        tolerance = min(
            160.0,
            max(
                1.0,
                self._visible_duration_ms()
                * 12.0
                / max(1.0, self.grid_rect.width()),
            ),
        )
        beat_ms = 60_000.0 / max(1, self.bpm)
        self._clip_snap_result = snap_clip_start(
            proposed_ms,
            max(0.0, float(duration_ms)),
            self._clip_snap_targets,
            tolerance_ms=tolerance,
            grid_ms=beat_ms / 4.0,
            grid_origin_ms=self.beat_origin_ms,
        )
        return self._clip_snap_result.start_ms

    def _update_clip_drag_geometry(
        self,
        pos: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Recompute a clip gesture from its pointer-down geometry."""

        current_ms = self._time_at_x(pos.x())
        delta = current_ms - self._clip_drag_origin_press_ms
        if self._clip_drag_mode == "move":
            duration = (
                self._clip_drag_origin_end_ms
                - self._clip_drag_origin_start_ms
            )
            start = self._snap_drag_time(
                self._clip_drag_origin_start_ms + delta,
                duration,
                modifiers,
            )
            if self._clip_group_drag_origins:
                earliest = min(
                    value[0]
                    for value in self._clip_group_drag_origins.values()
                )
                start = max(
                    start,
                    self._clip_drag_origin_start_ms - earliest,
                )
            target = self._track_at_position(pos)
            if target is not None:
                if self._clip_group_drag_keys:
                    rows_by_id = {
                        int(track.track_id): row
                        for row, track in enumerate(self.tracks)
                    }
                    anchor_row = rows_by_id.get(
                        int(self._clip_drag_source.track_id)
                        if self._clip_drag_source is not None else -1
                    )
                    target_row = rows_by_id.get(int(target.track_id))
                    selected_rows = tuple(
                        rows_by_id[key[0]]
                        for key in self._clip_group_drag_keys
                        if key[0] in rows_by_id
                    )
                    if (
                        anchor_row is not None
                        and target_row is not None
                        and selected_rows
                    ):
                        proposed = target_row - anchor_row
                        minimum = -min(selected_rows)
                        maximum = len(self.tracks) - 1 - max(selected_rows)
                        self._clip_group_drag_track_offset = max(
                            minimum, min(maximum, proposed)
                        )
                        destination_row = anchor_row + self._clip_group_drag_track_offset
                        self._clip_drag_target = self.tracks[destination_row]
                else:
                    self._clip_drag_target = target
            self._clip_drag_start_ms = start
            self._clip_drag_end_ms = start + duration
        elif self._clip_drag_mode == "resize_start":
            # The left edge is fixed; resizing changes only the empty region
            # available at the right without transforming authored notes.
            self._clip_drag_start_ms = self._clip_drag_origin_start_ms
            self._clip_drag_end_ms = self._clip_drag_origin_end_ms
        elif self._clip_drag_mode == "resize_end":
            end = self._snap_drag_time(
                self._clip_drag_origin_end_ms + delta,
                0.0,
                modifiers,
            )
            self._clip_drag_start_ms = self._clip_drag_origin_start_ms
            self._clip_drag_end_ms = max(
                self._clip_drag_origin_start_ms + MIN_CLIP_DURATION_MS,
                end,
            )
            self._clip_drag_end_ms = min(
                self._clip_drag_max_end_ms,
                self._clip_drag_end_ms,
            )

    def _build_clip_snap_targets(
        self,
        source: TrackState,
        clip_id: str,
        *,
        ignored_keys: frozenset[tuple[int, str]] = frozenset(),
    ) -> ArrangementSnapIndex:
        targets: list[ArrangementSnapTarget] = []
        for track in self.tracks:
            for clip in track_clips(track):
                key = (int(track.track_id), str(clip.clip_id))
                if (
                    key in ignored_keys
                    or (track is source and clip.clip_id == clip_id)
                ):
                    continue
                label = str(getattr(track, "display_name", "") or "")
                targets.extend((
                    ArrangementSnapTarget(clip.start_ms, "clip", label),
                    ArrangementSnapTarget(clip.end_ms, "clip", label),
                ))
        targets.extend(
            ArrangementSnapTarget(
                float(marker["time_ms"]), "marker", str(marker["label"])
            )
            for marker in self.timeline_markers
        )
        return build_snap_index(targets)

    def set_merge_overlap_regions(self, track_id: int, regions: object) -> None:
        """Highlight the last merge's review areas until the model changes."""

        self._merge_overlap_track_id = int(track_id)
        self._merge_overlap_regions = tuple(regions)
        self.update()

    def clear_merge_overlap_regions(self) -> None:
        self._merge_overlap_track_id = None
        self._merge_overlap_regions = ()

    def update_tracks(self, track_ids: object) -> None:
        """Rebuild only changed track indexes after a non-structural commit."""

        requested = {int(track_id) for track_id in track_ids}
        if not requested:
            return
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        missing = requested - tracks_by_id.keys()
        if missing:
            raise ValueError(f"unknown timeline track IDs: {sorted(missing)}")
        self.velocity_curve_overlay.invalidate_tracks(requested)
        for track_id in requested:
            track = tracks_by_id[track_id]
            self._track_note_indexes[id(track)] = self._build_track_index(track)
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self._static_timeline_cache_key = None
        self.update()

    def update_track_presentation(self, track_ids: object) -> None:
        """Refresh mute/solo/color state without rebuilding note indexes."""

        requested = {int(track_id) for track_id in track_ids}
        valid = {int(track.track_id) for track in self.tracks}
        if not requested or not requested <= valid:
            return
        self._static_timeline_cache_key = None
        self._update_accessible_track_state()
        self.update()

    def set_validation_notices(
        self,
        notices: dict[int, dict[str, tuple]],
    ) -> None:
        """Apply export errors and non-blocking attention marks by track ID."""

        valid_track_ids = {int(track.track_id) for track in self.tracks}
        normalized: dict[int, dict[str, tuple]] = {}
        for raw_track_id, raw_notice in notices.items():
            track_id = int(raw_track_id)
            if track_id not in valid_track_ids:
                continue
            errors = tuple(
                str(message).strip()
                for message in raw_notice.get("errors", ())
                if str(message).strip()
            )
            attentions = tuple(
                str(message).strip()
                for message in raw_notice.get("attentions", ())
                if str(message).strip()
            )
            invalid_note_keys = tuple(
                tuple(value)
                for value in raw_notice.get("invalid_note_keys", ())
                if isinstance(value, (tuple, list)) and len(value) == 5
            )
            if errors or attentions or invalid_note_keys:
                normalized[track_id] = {
                    "errors": errors,
                    "attentions": attentions,
                    "invalid_note_keys": invalid_note_keys,
                }
        if normalized == self.track_validation_notices:
            return
        self.track_validation_notices = normalized
        self._conversion_note_keys.clear()
        self._conversion_problem_masks.clear()
        self._static_timeline_cache_key = None
        self._validation_hover_track_id = None
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.update()

    def _track_validation_notice(
        self,
        track: TrackState,
    ) -> dict[str, tuple]:
        return self.track_validation_notices.get(
            int(track.track_id),
            {"errors": (), "attentions": (), "invalid_note_keys": ()},
        )

    def _track_validation_tooltip(self, track: TrackState) -> str:
        notice = self._track_validation_notice(track)
        sections: list[str] = []
        errors = notice["errors"]
        attentions = notice["attentions"]
        if errors:
            sections.append(
                tr("导出错误") + "\n" + "\n".join(
                    f"• {message}" for message in errors
                )
            )
        if attentions:
            sections.append(
                tr("需要注意") + "\n" + "\n".join(
                    f"• {message}" for message in attentions
                )
            )
        return "\n\n".join(sections)

    def _track_attention_accent(self, row: int) -> QColor:
        """Use an arrangement Group's identity color for its merge notice."""

        group = self._arrangement_group_by_row.get(int(row))
        return QColor(group.color if group is not None else "#d1a24d")

    def set_reference_audio(self, controller: "ReferenceAudioView") -> None:
        if self.reference_audio is controller:
            return
        if self.reference_audio is not None:
            try:
                self.reference_audio.timeline_changed.disconnect(self._reference_audio_updated)
            except (RuntimeError, TypeError):
                pass
        self.reference_audio = controller
        controller.timeline_changed.connect(self._reference_audio_updated)
        self._reference_audio_updated()

    def set_reference_audio_relink_required(self, required: bool) -> None:
        if self._reference_audio_relink_required != required:
            self._reference_audio_relink_required = required
            self.refresh_reference_audio_controls()

    def refresh_reference_audio_controls(self) -> None:
        controller = self.reference_audio
        if controller is None:
            return
        _, header_w, _, _ = self._timeline_layout_metrics()
        height = self._reference_audio_lane_height()
        position_reference_audio_controls(
            self._reference_load_button,
            self._reference_menu_button,
            controller,
            header_width=header_w,
            lane_top=self.height() - height,
            lane_height=height,
            missing=self._reference_audio_relink_required,
        )

    def _choose_reference_audio(self) -> None:
        if self.reference_audio is not None:
            self.reference_audio.choose_audio(self)

    def _open_reference_audio_menu(self) -> None:
        button = self._reference_menu_button
        self._show_reference_audio_menu(button.mapToGlobal(button.rect().bottomLeft()))

    def _reference_audio_updated(self) -> None:
        # Reference alignment and waveform updates do not mutate editor
        # notes. Rebuilding every interval/overview index here made loading
        # or moving a reference audio file scale with the whole score.
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.refresh_reference_audio_controls()
        self.update()

    def _timeline_row_count(self) -> int:
        return len(self.tracks) + (1 if self.reference_audio is not None else 0)

    def _musical_track_count(self) -> int:
        """Return authored tracks without presentation-only reference lanes."""

        return len(self.tracks)

    def set_track_levels(self, levels: dict[int, float]) -> None:
        normalized = {
            int(track_id): math.ceil(
                max(0.0, min(1.0, float(level))) * self.METER_SEGMENT_COUNT
            )
            for track_id, level in levels.items()
        }
        previous = self.track_levels
        if normalized == previous:
            return
        self.track_levels = normalized
        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        instrument_h = max(
            0.0, max(80, area.bottom() - grid_top) - self._reference_audio_lane_height(),
        )
        first_row, last_row = self._visible_track_row_range(instrument_h)
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        meter_left = area.left() + header_w - 14
        meter_column = QRectF(meter_left - 1, grid_top, 9, instrument_h).toAlignedRect()
        visible_rows = self._visible_track_rows()
        changed_rows = []
        for visual_row in range(first_row, last_row):
            row, track = visible_rows[visual_row]
            group = self._collapsed_group_for_row(row)
            members = group.members if group is not None else (track,)
            if any(
                normalized.get(track_id, 0) != previous.get(track_id, 0)
                for track_id in (int(member.track_id) for member in members)
            ):
                changed_rows.append(visual_row)
                # Dense level changes are cheaper as one narrow stripe.
                if len(changed_rows) > 4:
                    self.update(meter_column)
                    return
        damage = QRegion()
        for visual_row in changed_rows:
            y = grid_top + visual_row * lane_h - scroll_y
            meter = self._track_meter_rect(meter_left, y, lane_h)
            damage |= meter.adjusted(-1, -1, 1, 1).toAlignedRect()
        damage &= meter_column
        if not damage.isEmpty():
            self.update(damage)

    def _build_track_index(
        self,
        track: TrackState,
    ) -> _TimelineTrackNoteIndex:
        identity_clip = (
            not getattr(track, "arrangement_clips", ())
            and getattr(track, "clip_start_ms", None) is None
            and getattr(track, "clip_end_ms", None) is None
            and math.isclose(
                float(getattr(track, "duration_scale", 1.0)),
                1.0,
                abs_tol=1e-12,
            )
        )
        # Imported/default tracks without explicit Clip geometry already use
        # timeline coordinates. Avoid allocating an equal projected Note tuple
        # before the immutable interval index performs its own ordering pass.
        notes = tuple(track.notes) if identity_clip else project_track_notes(track)
        intervals = IntervalIndex.build(
            notes,
            start_of=lambda note: float(note.start),
            duration_of=lambda note: float(note.dur),
            block_size=self.TRACK_NOTE_QUERY_BLOCK_SIZE,
        )
        clips = IntervalIndex.build(
            track_clips(track),
            start_of=lambda clip: float(clip.start_ms),
            duration_of=lambda clip: float(clip.end_ms - clip.start_ms),
            block_size=self.TRACK_CLIP_QUERY_BLOCK_SIZE,
        )
        return _TimelineTrackNoteIndex(
            intervals=intervals,
            clips=clips,
            pitch_min=min(
                (int(note.pitch) for note in intervals.items),
                default=0,
            ),
            pitch_max=max(
                (int(note.pitch) for note in intervals.items),
                default=0,
            ),
            # Dense overview bins are only needed for tracks that are actually
            # painted. Building them lazily avoids blocking the workspace when
            # a large project contains many offscreen tracks.
            overview_levels=(),
        )

    def _rebuild_track_indexes(self) -> None:
        self._track_note_indexes = {}
        self._conversion_note_keys.clear()
        self._conversion_problem_masks.clear()
        for track in self.tracks:
            self._track_note_indexes[id(track)] = self._build_track_index(track)
        self._refresh_timeline_end_cache()

    def _refresh_timeline_end_cache(self) -> None:
        timeline_end = max(
            1.0,
            max(
                (
                    index.intervals.maximum_end
                    for index in self._track_note_indexes.values()
                ),
                default=1.0,
            ),
        )
        timeline_end = max(
            timeline_end,
            max(
                (index.clips.maximum_end for index in self._track_note_indexes.values()),
                default=1.0,
            ),
        )
        if self.reference_audio is not None:
            timeline_end = max(timeline_end, self.reference_audio.project_end_ms)
        # A note-only project still needs blank musical space at its right
        # edge. Otherwise the last note becomes a hard boundary and users
        # cannot pan right to author the next phrase. A loaded reference with
        # known duration remains the authoritative timeline boundary.
        reference_duration = (
            self.reference_audio.duration_ms
            if self.reference_audio is not None
            else 0.0
        )
        if reference_duration <= 0.0:
            measure_ms = 60_000.0 / max(1, self.bpm) * max(1, self.time_sig)
            timeline_end += max(
                self.EDIT_TAIL_MIN_MS,
                measure_ms * self.EDIT_TAIL_MEASURES,
            )
        self._timeline_end_cache = timeline_end

    def _build_note_overview_levels(
        self,
        intervals: IntervalIndex[object],
    ) -> tuple[_TimelineNoteOverviewLevel, ...]:
        """Precompute bounded visual summaries for dense timeline zooms."""

        timeline_end = max(1.0, float(intervals.maximum_end))
        levels: list[_TimelineNoteOverviewLevel] = []
        for bucket_count in self.NOTE_OVERVIEW_LEVELS:
            last_bucket = bucket_count - 1
            starts = [float("inf")] * bucket_count
            ends = [float("-inf")] * bucket_count
            pitch_mins = [128] * bucket_count
            pitch_maxes = [-1] * bucket_count
            pitch_masks = [0] * bucket_count
            articulation_types = [0] * bucket_count
            for note, start, end in zip(intervals.items, intervals.starts, intervals.ends):
                bucket = int(start / timeline_end * bucket_count)
                if bucket < 0:
                    bucket = 0
                elif bucket > last_bucket:
                    bucket = last_bucket
                pitch = int(note.pitch)
                if start < starts[bucket]:
                    starts[bucket] = start
                if end > ends[bucket]:
                    ends[bucket] = end
                if pitch < pitch_mins[bucket]:
                    pitch_mins[bucket] = pitch
                if pitch > pitch_maxes[bucket]:
                    pitch_maxes[bucket] = pitch
                pitch_masks[bucket] |= 1 << (pitch if pitch >= 0 else 0)
                if not articulation_types[bucket]:
                    articulation_types[bucket] = int(getattr(note, "ntype", 0))
            overview_bins = tuple(
                _TimelineNoteOverviewBin(
                    start=starts[bucket],
                    end=ends[bucket],
                    pitch_min=pitch_mins[bucket],
                    pitch_max=pitch_maxes[bucket],
                    pitch_mask=pitch_masks[bucket],
                    articulation_type=articulation_types[bucket],
                )
                for bucket in range(bucket_count)
                if pitch_maxes[bucket] >= 0
            )
            levels.append(
                _TimelineNoteOverviewLevel(
                    bucket_count=bucket_count,
                    bins=overview_bins,
                    starts=tuple(value.start for value in overview_bins),
                    max_span=max(
                        (value.end - value.start for value in overview_bins),
                        default=0.0,
                    ),
                )
            )
        return tuple(levels)

    def _visible_note_overview_bins(
        self,
        track: TrackState,
        visible_start: float,
        visible_duration: float,
        region_width: float,
    ) -> tuple[_TimelineNoteOverviewBin, ...]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            return ()
        if not index.overview_levels:
            index = _TimelineTrackNoteIndex(
                intervals=index.intervals,
                clips=index.clips,
                pitch_min=index.pitch_min,
                pitch_max=index.pitch_max,
                overview_levels=self._build_note_overview_levels(
                    index.intervals
                ),
            )
            self._track_note_indexes[id(track)] = index
        track_duration = max(1.0, float(index.intervals.maximum_end))
        desired_bucket_count = (
            track_duration / max(1.0, visible_duration)
            * max(1.0, region_width)
            / self.NOTE_OVERVIEW_BUCKET_PX
        )
        level = min(
            index.overview_levels,
            key=lambda value: abs(value.bucket_count - desired_bucket_count),
        )
        visible_end = visible_start + visible_duration
        lower = bisect_left(
            level.starts,
            visible_start - level.max_span,
        )
        upper = bisect_right(level.starts, visible_end)
        return tuple(
            value
            for value in level.bins[lower:upper]
            if value.end >= visible_start
        )

    def _visible_group_summary_spans(
        self,
        track: TrackState,
        visible_start: float,
        visible_duration: float,
        bucket_count: int,
    ) -> tuple[tuple[float, float], ...]:
        """Build one pixel-bounded folded-group summary without dense caches.

        A folded group can expose many member tracks inside a single row.  The
        normal per-track overview prepares several zoom levels, which is useful
        while zooming one lane but wasteful when dozens of sub-bands are only a
        few pixels high.  Query the visible intervals once and merge them into
        the number of horizontal buckets the folded row can actually display.
        """

        index = self._track_note_indexes.get(id(track))
        if index is None or not index.intervals.starts:
            return ()
        intervals = index.intervals
        visible_end = visible_start + max(1.0, visible_duration)
        bucket_count = max(1, int(bucket_count))
        bucket_duration = max(1.0, visible_duration) / bucket_count
        spans: list[tuple[float, float]] = []
        for bucket in range(bucket_count):
            start = visible_start + bucket * bucket_duration
            end = (
                visible_end
                if bucket == bucket_count - 1
                else start + bucket_duration
            )
            last_note = bisect_right(intervals.starts, end) - 1
            # The most recent onset usually bounds a dense melodic bucket.
            # Search earlier intervals only when a long sustained note may overlap.
            if last_note >= 0 and (
                intervals.ends[last_note] >= start
                or intervals.intersects_closed(start, end)
            ):
                spans.append((start, end))
        return tuple(spans)

    def _visible_track_clips(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[ArrangementClipState, ...]:
        self._last_track_clip_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return ()
        result = index.clips.query_closed(start, end)
        self._last_track_clip_query_inspections = result.inspected_count
        return result.items

    def _visible_track_note_window(
        self, track: TrackState, start: float, end: float, *, limit: int | None = None,
    ) -> tuple[list, int, int]:
        self._last_track_note_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return [], 0, 0
        result = index.intervals.query_closed(start, end, limit=limit)
        self._last_track_note_query_inspections = result.inspected_count
        visible = list(result.items)
        return visible, 0, len(visible)

    def _track_pitch_bounds(self, track: TrackState) -> tuple[int, int]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return 0, 0
        return index.pitch_min, index.pitch_max

    def set_selected_track(self, track: TrackState | None) -> None:
        preserve_clip = bool(
            track is not None
            and self._focus_scope == "clip"
            and self._selected_clip_track_id == int(track.track_id)
        )
        self._select_track(track, emit=False, preserve_clip_selection=preserve_clip)

    @property
    def selection_scope(self) -> str:
        return self._focus_scope if self.selected_track is not None else "none"

    def selected_track_items(self) -> tuple[TrackState, ...]:
        return tuple(track for track in self.tracks if int(track.track_id) in self._selected_track_ids)

    def selection_descriptor(self) -> dict[str, object]:
        return selection_descriptor(self)

    def _emit_selection_scope(self) -> None:
        self.selection_scope_changed.emit(self.selection_descriptor())

    @property
    def selected_clip_keys(self) -> frozenset[tuple[int, str]]:
        return frozenset(self._selected_clip_keys)

    def selected_clip_items(self) -> tuple[tuple[TrackState, str], ...]:
        """Return selected Clips in stable track/Clip display order."""

        return self._clip_items_for_keys(self._selected_clip_keys)

    def _clip_items_for_keys(
        self, keys: set[tuple[int, str]]
    ) -> tuple[tuple[TrackState, str], ...]:
        if not keys:
            return ()
        track_ids = {track_id for track_id, _clip_id in keys}
        return tuple(
            (track, str(clip.clip_id))
            for track in self.tracks
            if int(track.track_id) in track_ids
            for clip in track_clips(track)
            if (int(track.track_id), str(clip.clip_id)) in keys
        )

    def _clear_clip_selection(self) -> None:
        self._selected_clip_keys.clear()
        self._selected_clip_id = ""
        self._selected_clip_track_id = None
        if self._focus_scope == "clip":
            self._focus_scope = "track"
        self._static_timeline_cache_key = None

    def _clear_arrangement_selection(self) -> None:
        if self.selected_track is not None or self._selected_clip_keys:
            self._select_track(None, emit=True)

    def _set_clip_selection(
        self,
        keys: set[tuple[int, str]],
        *,
        primary_key: tuple[int, str] | None = None,
        emit_track: bool,
    ) -> None:
        ordered = tuple(
            (int(track.track_id), clip_id)
            for track, clip_id in self._clip_items_for_keys(keys)
        )
        normalized = set(ordered)
        if not normalized:
            if emit_track:
                self._clear_arrangement_selection()
                return
            self._clear_clip_selection()
            self._update_accessible_track_state()
            self.update()
            self._emit_selection_scope()
            return
        primary = (
            primary_key if primary_key in normalized else ordered[0]
        )
        track = next(
            item for item in self.tracks
            if int(item.track_id) == primary[0]
        )
        self._selected_clip_keys = normalized
        self._selected_clip_track_id = primary[0]
        self._selected_clip_id = primary[1]
        self._focus_scope = "clip"
        self._static_timeline_cache_key = None
        self._select_track(
            track,
            emit=emit_track,
            preserve_clip_selection=True,
        )

    def _select_pointer_clip(
        self,
        track: TrackState,
        clip_id: str,
        modifiers: Qt.KeyboardModifiers,
    ) -> None:
        key = (int(track.track_id), str(clip_id))
        additive = bool(
            modifiers & (Qt.ControlModifier | Qt.ShiftModifier)
        )
        if not additive:
            selected = {key}
        elif modifiers & Qt.ControlModifier:
            selected = set(self._selected_clip_keys)
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
        else:
            selected = {*self._selected_clip_keys, key}
        self._set_clip_selection(
            selected,
            primary_key=(key if key in selected else None),
            emit_track=True,
        )

    def set_selected_clip(
        self, track: TrackState | None, clip_id: str = ""
    ) -> None:
        """Select one Clip without opening its note editor."""

        if track is None or not clip_id:
            self._select_track(track, emit=False)
            self._clear_clip_selection()
            self.update()
            return
        try:
            clip_by_id(track, clip_id)
        except ValueError:
            self._select_track(track, emit=False)
            self._clear_clip_selection()
            self.update()
            return
        key = (int(track.track_id), str(clip_id))
        self._set_clip_selection(
            {key}, primary_key=key, emit_track=False
        )

    def set_selected_clip_keys(
        self,
        keys,
        *,
        primary_key: tuple[int, str] | None = None,
    ) -> None:
        """Restore a stable multi-selection after a model transaction."""

        self._set_clip_selection(
            {
                (int(track_id), str(clip_id))
                for track_id, clip_id in tuple(keys or ())
            },
            primary_key=(
                (int(primary_key[0]), str(primary_key[1]))
                if primary_key is not None
                else None
            ),
            emit_track=False,
        )

    def _select_track(
        self,
        track: TrackState | None,
        *,
        emit: bool,
        preserve_clip_selection: bool = False,
        track_ids: set[int] | None = None,
    ) -> None:
        if (
            track is None
            or str(track.arrangement_group_id or "")
            != self._selected_arrangement_group_id
        ):
            self._selected_arrangement_group_id = ""
        self.selected_track = track
        if not preserve_clip_selection:
            self._focus_scope = "track"
            self._clear_clip_selection()
        self._selected_track_ids = (
            track_ids if track_ids is not None
            else {int(track.track_id)} if track is not None else set()
        )
        self.velocity_curve_overlay.selected_track_changed(track)
        if emit:
            self.selected.emit(track)
        self._ensure_selected_track_visible()
        self._update_accessible_track_state()
        self.update()
        self._emit_selection_scope()

    def _select_pointer_track(
        self, track: TrackState, modifiers: Qt.KeyboardModifiers
    ) -> None:
        select_pointer_track(self, track, modifiers)

    def _selected_track_index(self) -> int | None:
        return next(
            (
                index
                for index, track in enumerate(self.tracks)
                if track is self.selected_track
            ),
            None,
        )

    def _ensure_selected_track_visible(self) -> None:
        visible_rows = self._visible_track_rows()
        index = next(
            (
                visual_row
                for visual_row, (_row, track) in enumerate(visible_rows)
                if track is self.selected_track
            ),
            None,
        )
        if index is None or not self.track_scroll.isVisible():
            return
        lane_height = self._lane_height()
        top = index * lane_height
        bottom = top + lane_height
        current = self.track_scroll.value()
        page = max(lane_height, self.track_scroll.pageStep())
        if top < current:
            self.track_scroll.setValue(top)
        elif bottom > current + page:
            self.track_scroll.setValue(bottom - page)

    def _update_accessible_track_state(self) -> None:
        track = self.selected_track
        if track is None:
            self.setAccessibleDescription(tr(self.KEYBOARD_SHORTCUT_HINT))
            return
        validation_description = self._track_validation_tooltip(track)
        self.setAccessibleDescription(
            trf(
                "当前轨道：{track}；音量 {volume}。{shortcuts}",
                track=str(track.display_name),
                volume=int(track.bdo_track_volume),
                shortcuts=trv(self.KEYBOARD_SHORTCUT_HINT),
            )
            + (
                "\n" + validation_description
                if validation_description
                else ""
            )
        )

    def set_pitch_transform_plan(self, plan: PitchTransformPlan) -> None:
        if plan == self.pitch_transform_plan:
            return
        self.pitch_transform_plan = plan
        self.conversion_transpose = plan.global_semitones
        self.update()

    def set_musical_grid(
        self,
        bpm: int,
        time_sig: int,
        beat_origin_ms: float,
    ) -> None:
        values = (
            max(1, int(bpm)),
            max(1, int(time_sig)),
            float(beat_origin_ms),
        )
        if values == (self.bpm, self.time_sig, self.beat_origin_ms):
            return
        self.bpm, self.time_sig, self.beat_origin_ms = values
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.update()

    def _visible_musical_ticks(
        self,
        visible_start: float,
        visible_duration: float,
        grid_width: float,
    ) -> list[tuple[float, bool, str]]:
        beat_ms = 60000.0 / max(1, self.bpm)
        beats_per_measure = max(1, self.time_sig)
        beat_pixels = grid_width * beat_ms / max(1.0, visible_duration)
        factor = beats_per_measure if beat_pixels < self.GRID_MIN_TICK_SPACING_PX else 1
        while beat_pixels * factor < self.GRID_MIN_TICK_SPACING_PX:
            factor *= 2
        step_ms = beat_ms * factor
        first_beat = factor * math.ceil(
            (visible_start - self.beat_origin_ms) / step_ms
        )
        end = visible_start + visible_duration
        ticks: list[tuple[float, bool, str]] = []
        for index in range(514):
            beat_index = first_beat + factor * index
            value = self.beat_origin_ms + beat_index * beat_ms
            if value > end:
                break
            measure_index, beat_in_measure = divmod(beat_index, beats_per_measure)
            is_major = beat_in_measure == 0
            label = str(measure_index + 1) if is_major else ""
            ticks.append((value, is_major, label))
        return ticks

    def _show_measure_banding(
        self,
        visible_duration: float,
        grid_width: float,
    ) -> bool:
        measure_ms = (
            60000.0 / max(1, self.bpm) * max(1, self.time_sig)
        )
        measure_width = grid_width * measure_ms / max(1.0, visible_duration)
        return measure_width >= self.MEASURE_BANDING_MIN_WIDTH_PX

    @staticmethod
    def _validation_note_key(note: object) -> tuple[object, ...]:
        return (
            int(getattr(note, "pitch")),
            int(getattr(note, "vel")),
            float(getattr(note, "start")),
            float(getattr(note, "dur")),
            int(getattr(note, "ntype")),
        )

    def _note_has_conversion_problem(
        self,
        track: TrackState,
        note: object,
    ) -> bool:
        invalid_keys = self._conversion_note_key_set(track)
        if isinstance(note, int):
            return any(int(key[0]) == int(note) for key in invalid_keys)
        return self._validation_note_key(note) in invalid_keys

    def _conversion_note_key_set(self, track: TrackState) -> frozenset[tuple[object, ...]]:
        track_id = int(track.track_id)
        keys = self._conversion_note_keys.get(track_id)
        if keys is None:
            keys = frozenset(self._track_validation_notice(track)["invalid_note_keys"])
            self._conversion_note_keys[track_id] = keys
        return keys

    def _conversion_problem_mask(self, track: TrackState) -> int:
        track_id = int(track.track_id)
        cached = self._conversion_problem_masks.get(track_id)
        if cached is not None:
            return cached
        mask = 0
        for key in self._conversion_note_key_set(track):
            pitch = int(key[0])
            if 0 <= pitch < 128:
                mask |= 1 << pitch
        self._conversion_problem_masks[track_id] = mask
        return mask

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scaled_background()
        self._update_track_scrollbar()
        self.refresh_reference_audio_controls()

    @property
    def header_width(self) -> int:
        return int(self._header_width)

    @property
    def lane_height(self) -> int:
        return int(self._lane_height_px)

    @property
    def reference_lane_height(self) -> int:
        return int(self._reference_lane_height_px)

    def set_layout_metrics(
        self,
        *,
        header_width: int | None = None,
        lane_height: int | None = None,
        reference_lane_height: int | None = None,
        notify: bool = False,
    ) -> None:
        """Apply bounded, UI-local timeline density preferences."""

        values = (
            max(220, min(420, int(
                self._header_width if header_width is None else header_width
            ))),
            max(44, min(104, int(
                self._lane_height_px if lane_height is None else lane_height
            ))),
            max(44, min(180, int(
                self._reference_lane_height_px
                if reference_lane_height is None
                else reference_lane_height
            ))),
        )
        previous = (
            self._header_width,
            self._lane_height_px,
            self._reference_lane_height_px,
        )
        if values == previous:
            return
        self._header_width, self._lane_height_px, self._reference_lane_height_px = values
        self._static_timeline_cache_key = None
        self._update_track_scrollbar()
        self.refresh_reference_audio_controls()
        self._ensure_selected_track_visible()
        self.update()
        if notify:
            self.layout_preferences_changed.emit()

    def _refresh_scaled_background(self) -> None:
        if self.background_pixmap.isNull() or self.size().isEmpty():
            self._scaled_background = QPixmap()
            self._scaled_background_size = QSize()
            return
        if self._scaled_background_size == self.size():
            return
        self._scaled_background = self.background_pixmap.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
        )
        self._scaled_background_size = self.size()

    def _lane_height(self) -> int:
        return int(self._lane_height_px)

    def _visible_track_row_range(self, grid_height: float) -> tuple[int, int]:
        lane_height = self._lane_height()
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        first_row = max(0, int(scroll_y // lane_height))
        last_row = min(
            len(self._visible_track_rows()),
            int(math.ceil((scroll_y + grid_height) / lane_height)) + 1,
        )
        return first_row, last_row

    def _timeline_layout_metrics(self) -> tuple[QRectF, int, int, int]:
        # The workspace itself supplies separation from the fixed bars.  Keep
        # the painted track grid full-bleed inside it—no extra canvas gutter.
        area = QRectF(self.rect())
        # Keep the left column compact; pitch-range detail belongs in the
        # inspector/conversion check rather than competing with row controls.
        header_w = int(self._header_width)
        ruler_h = 34
        lane_h = self._lane_height()
        return area, header_w, ruler_h, lane_h

    def _timeline_grid_width(self, area: QRectF, header_w: int) -> float:
        # The scrollbar can appear during splitter movement. Keep the same
        # time-to-pixel mapping and pointer targets for the entire movement.
        return max(0.0, area.width() - header_w - self.TRACK_SCROLL_GUTTER)

    def _reference_audio_lane_height(self) -> int:
        controller = self.reference_audio
        if controller is None:
            return 0
        if controller.audio_path or controller.waveform_loading:
            return int(self._reference_lane_height_px)
        return hig.BUTTON_HEIGHT + 2 * hig.CONTROL_GAP

    def _layout_handle_at(self, position: QPointF) -> str:
        """Resolve presentation splitters without adding nested Qt widgets."""

        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if abs(position.x() - (area.left() + header_w)) <= 5.0:
            return "header"
        grid_top = area.top() + ruler_h
        reference_h = self._reference_audio_lane_height()
        if reference_h and self.reference_audio.audio_path:
            reference_top = area.bottom() - reference_h
            if abs(position.y() - reference_top) <= 5.0:
                return "reference"
        if (
            position.x() < area.left() + header_w
            and position.y() > grid_top + 8.0
            and self._visible_track_rows()
        ):
            scroll_y = (
                self.track_scroll.value()
                if self.track_scroll.isVisible()
                else 0
            )
            relative = (position.y() - grid_top + scroll_y) % lane_h
            if min(relative, lane_h - relative) <= 4.0:
                return "lane"
        return ""

    def _paint_layout_handles(
        self,
        painter: QPainter,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        lane_h: int,
    ) -> None:
        """Expose the three persistent density splitters without new widgets."""

        grid_left = area.left() + header_w
        hovered = self._layout_hover_handle or self._layout_drag_mode
        painter.save()
        painter.setPen(Qt.NoPen)
        header_color = QColor(hig.ACCENT if hovered == "header" else "#343437")
        painter.fillRect(
            QRectF(grid_left, area.top(), 1.0, area.height()),
            header_color,
        )
        painter.fillRect(
            QRectF(grid_left - 1.0, area.top() + 10.0, 3.0, ruler_h - 20.0),
            QColor(hig.ACCENT if hovered == "header" else hig.INDICATOR_BORDER),
        )

        grip_left = area.left() + max(8.0, header_w / 2.0 - 13.0)
        lane_y = area.top() + ruler_h + lane_h
        if lane_y < area.bottom() - 8.0:
            painter.fillRect(
                QRectF(grip_left, lane_y - 1.5, 26.0, 3.0),
                QColor(hig.ACCENT if hovered == "lane" else hig.CONTROL_BORDER),
            )
        reference_h = self._reference_audio_lane_height()
        if reference_h and self.reference_audio.audio_path:
            reference_y = area.bottom() - reference_h
            painter.fillRect(
                QRectF(grip_left, reference_y - 1.5, 26.0, 3.0),
                QColor(hig.ACCENT if hovered == "reference" else hig.CONTROL_BORDER),
            )
        painter.restore()

    def _update_track_scrollbar(self) -> None:
        if not hasattr(self, "track_scroll"):
            return
        area, _header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        grid_h = max(80, area.bottom() - grid_top)
        instrument_view_h = max(
            0,
            grid_h - self._reference_audio_lane_height(),
        )
        content_h = lane_h * len(self._visible_track_rows())
        max_scroll = max(0, content_h - instrument_view_h)
        scrollbar_width = self.TRACK_SCROLL_GUTTER
        self.track_scroll.setGeometry(
            int(area.right() - scrollbar_width),
            int(grid_top),
            scrollbar_width,
            int(instrument_view_h),
        )
        self.track_scroll.setRange(0, int(max_scroll))
        self.track_scroll.setPageStep(int(instrument_view_h))
        self.track_scroll.setSingleStep(lane_h)
        self.track_scroll.setVisible(max_scroll > 0)

    def set_playhead(self, ms: float, follow: bool = False) -> None:
        old_rect = self._playhead_update_rect(self.playhead_ms)
        old_view_start = self.view_start_ms
        old_playhead = self.playhead_ms
        self.playhead_ms = max(0.0, min(float(ms), self._timeline_end_ms()))
        if follow:
            visible_duration = self._visible_duration_ms()
            if self.playhead_ms < self.view_start_ms or self.playhead_ms > self.view_start_ms + visible_duration * 0.92:
                self.view_start_ms = self.playhead_ms - visible_duration * 0.18
                self._clamp_view()
        if self.view_start_ms != old_view_start:
            self.update()
            self.viewport_changed.emit()
            if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
                self.playhead_changed.emit(self.playhead_ms)
            return
        new_rect = self._playhead_update_rect(self.playhead_ms)
        if old_rect != new_rect:
            if old_rect is not None:
                self.update(old_rect)
            if new_rect is not None:
                self.update(new_rect)
        if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
            self.playhead_changed.emit(self.playhead_ms)

    @property
    def time_range(self) -> tuple[float, float] | None:
        if self.range_start_ms is None or self.range_end_ms is None:
            return None
        return (
            min(self.range_start_ms, self.range_end_ms),
            max(self.range_start_ms, self.range_end_ms),
        )

    def set_time_range(
        self,
        start_ms: float | None,
        end_ms: float | None,
        *,
        notify: bool = False,
    ) -> None:
        if start_ms is None or end_ms is None:
            changed = self.time_range is not None
            self.range_start_ms = None
            self.range_end_ms = None
        else:
            start = max(0.0, min(float(start_ms), self._timeline_end_ms()))
            end = max(0.0, min(float(end_ms), self._timeline_end_ms()))
            changed = self.time_range != (min(start, end), max(start, end))
            self.range_start_ms = min(start, end)
            self.range_end_ms = max(start, end)
        if changed:
            self.update()
            if notify:
                self.time_range_changed.emit(self.time_range)

    def _playhead_update_rect(self, position_ms: float):
        visible_duration = self._visible_duration_ms()
        if not self.view_start_ms <= position_ms <= self.view_start_ms + visible_duration:
            return None
        area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
        grid_w = self._timeline_grid_width(area, header_w)
        x = self._playhead_pixel(
            position_ms, area.left() + header_w, grid_w, self.view_start_ms, visible_duration,
        )
        return QRectF(x - 9.0, area.top(), 19.0, area.height()).toAlignedRect()

    @staticmethod
    def _playhead_pixel(
        position_ms: float, grid_left: float, grid_width: float,
        view_start: float, visible_duration: float,
    ) -> int:
        # Keep the transport time precise while only moving the ruler glyph
        # when its pixel changes, especially in a whole-song overview.
        return round(grid_left + (position_ms - view_start) * grid_width / visible_duration)

    def set_buffer_progress(self, progress: float, visible: bool = True) -> None:
        progress = max(0.0, min(1.0, float(progress)))
        visible = bool(visible)
        if self.buffer_progress == progress and self.buffer_visible == visible:
            return
        needs_repaint = self.buffer_visible or visible
        self.buffer_progress = progress
        self.buffer_visible = visible
        if needs_repaint and not self.grid_rect.isEmpty():
            _, _, ruler_h, _ = self._timeline_layout_metrics()
            self.update(QRectF(
                self.grid_rect.left(),
                self.grid_rect.top() + ruler_h - 3,
                self.grid_rect.width(),
                3,
            ).toAlignedRect())

    def set_zoom_percent(self, value: int) -> None:
        new_zoom = max(0.25, min(32.0, value / 100.0))
        if math.isclose(new_zoom, self.zoom_factor):
            return
        old_duration = self._visible_duration_ms()
        center = self.view_start_ms + old_duration / 2
        self.zoom_factor = new_zoom
        self.view_start_ms = center - self._visible_duration_ms() / 2
        self._clamp_view()
        self._publish_viewport_change()

    def set_pan_percent(self, value: int) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        new_start = max_start * max(0, min(1000, value)) / 1000.0
        if math.isclose(new_start, self.view_start_ms, abs_tol=0.5):
            return
        self.view_start_ms = new_start
        self._clamp_view()
        self._publish_viewport_change()

    def pan_percent(self) -> int:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        if max_start <= 0:
            return 0
        return round(self.view_start_ms / max_start * 1000)

    def _track_scroll_changed(self, _value: int) -> None:
        self._begin_viewport_motion()
        self.update()

    def _publish_viewport_change(self) -> None:
        self._begin_viewport_motion()
        self.update()
        self.viewport_changed.emit()

    def _begin_viewport_motion(self) -> None:
        self._viewport_motion_active = True
        self._viewport_motion_timer.start()

    def _finish_viewport_motion(self) -> None:
        if not self._viewport_motion_active:
            return
        self._viewport_motion_active = False
        self.update()

    def _timeline_end_ms(self) -> float:
        return self._timeline_end_cache

    def _visible_duration_ms(self) -> float:
        return max(1.0, self._timeline_end_ms() / self.zoom_factor)

    def _clamp_view(self) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max(0.0, min(self.view_start_ms, max_start))

    def _paint_canvas_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor(hig.CANVAS))
        if self.property("composerWorkbench") or self.background_pixmap.isNull():
            return
        self._refresh_scaled_background()
        target = QRectF(self.rect())
        x = (self.width() - self._scaled_background.width()) / 2
        y = (self.height() - self._scaled_background.height()) / 2
        painter.save()
        painter.setOpacity(TIMELINE_BACKGROUND_OPACITY)
        painter.drawPixmap(int(x), int(y), self._scaled_background)
        painter.restore()
        painter.fillRect(target, QColor(17, 17, 18, 112))

    def _paint_timeline_shell(
        self,
        painter: QPainter,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        grid_w: float,
        grid_h: float,
    ) -> tuple[float, float, float, float]:
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        timeline_clip = QRectF(grid_left, grid_top, grid_w, grid_h)
        workbench = self.property("composerWorkbench")
        ruler = QColor(hig.CONTROL) if workbench else QColor(31, 35, 36, 246)
        track_header = QColor(hig.PANEL) if workbench else QColor(30, 33, 34, 238)
        grid = QColor(hig.CANVAS) if workbench else QColor(28, 28, 30, 204)
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), ruler)
        painter.fillRect(QRectF(left, grid_top, header_w, grid_h), track_header)
        painter.fillRect(timeline_clip, grid)
        painter.setPen(QPen(QColor(hig.SEPARATOR), 1))
        painter.drawLine(grid_left, top, grid_left, area.bottom())
        painter.drawLine(left, grid_top, area.right(), grid_top)
        return left, top, grid_left, grid_top

    def _paint_musical_grid(
        self,
        painter: QPainter,
        grid: QRectF,
        visible_start: float,
        visible_duration: float,
        ticks: list[tuple[float, bool, str]],
    ) -> None:
        beat_ms = 60000.0 / max(1, self.bpm)
        beats_per_measure = max(1, self.time_sig)
        measure_ms = beat_ms * beats_per_measure
        scale = grid.width() / visible_duration
        visible_end = visible_start + visible_duration
        painter.save()
        painter.setClipRect(grid)
        if self._show_measure_banding(visible_duration, grid.width()):
            first = math.floor((visible_start - self.beat_origin_ms) / measure_ms)
            last = math.ceil((visible_end - self.beat_origin_ms) / measure_ms)
            first_odd = first if first % 2 else first + 1
            for index in range(first_odd, last, 2):
                x = grid.left() + (self.beat_origin_ms + index * measure_ms - visible_start) * scale
                painter.fillRect(QRectF(x, grid.top(), measure_ms * scale, grid.height()), QColor(226, 226, 230, 4))

        beat_width = beat_ms * scale
        guides = ticks
        if measure_ms * scale >= self.GRID_MIN_GUIDE_SPACING_PX:
            step = 1 if beat_width >= self.GRID_MIN_GUIDE_SPACING_PX else beats_per_measure
            step_ms = beat_ms * step
            first = math.ceil((visible_start - self.beat_origin_ms) / step_ms)
            last = math.floor((visible_end - self.beat_origin_ms) / step_ms)
            guides = [
                (self.beat_origin_ms + index * step_ms, index * step % beats_per_measure == 0, "")
                for index in range(first, last + 1)
            ]
        for value, is_major, _label in guides:
            x = round(grid.left() + (value - visible_start) * scale)
            painter.fillRect(
                QRectF(x, grid.top(), 1, grid.height()),
                QColor("#29292d" if is_major else "#202023"),
            )
        painter.restore()

    def _paint_playhead(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        height: float,
    ) -> float | None:
        if visible_start <= self.playhead_ms <= visible_end:
            play_x = self._playhead_pixel(
                self.playhead_ms, grid_left, grid_w, visible_start, visible_duration,
            )
            painter.fillRect(QRectF(play_x, grid_top, 1.5, height), QColor(hig.ACCENT))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillPath(marker, QColor(hig.ACCENT))
            painter.restore()
            return play_x
        return None

    def _paint_time_range(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        selected = self.time_range
        if selected is None:
            return
        start, end = selected
        if end < visible_start or start > visible_end:
            return
        left_ms = max(start, visible_start)
        right_ms = min(end, visible_end)
        left_x = grid_left + (
            (left_ms - visible_start) / visible_duration
        ) * grid_w
        right_x = grid_left + (
            (right_ms - visible_start) / visible_duration
        ) * grid_w
        painter.fillRect(
            QRectF(left_x, grid_top, max(1.0, right_x - left_x), grid_h),
            QColor(222, 222, 225, 14),
        )
        for value in (start, end):
            if visible_start <= value <= visible_end:
                x = grid_left + (
                    (value - visible_start) / visible_duration
                ) * grid_w
                painter.fillRect(
                    QRectF(x - 0.5, top, 1.0, grid_h + (grid_top - top)),
                    QColor(hig.SELECTION_BORDER),
                )

    def _paint_arrangement_group_marker(
        self, painter: QPainter, track: TrackState, row: int, left: float,
        grid_left: float, grid_w: float, y: float, lane_h: int,
        has_validation_notice: bool,
    ) -> None:
        group = self._arrangement_group_by_row.get(row)
        if group is None:
            return
        selected = group.group_id == self._selected_arrangement_group_id
        group_color = QColor(group.color)
        group_color.setAlpha(158 if selected else 56)
        group_line_width = grid_left + grid_w - left if selected else grid_left - left
        if row == group.first_row:
            collapsed = group.group_id in self._collapsed_arrangement_groups
            painter.fillRect(
                QRectF(left, y, group_line_width, 1.0),
                group_color,
            )
            control_left = left + 10.0
            group_label = (
                trf(
                    "{tracks} 轨 · {clips} 音块 · {notes} 音符",
                    tracks=group.count, clips=group.clip_count, notes=group.note_count,
                )
                if collapsed
                else f"{_ui_bdo_instrument_name(group.instrument_id)} ×{group.count}"
            )
            control_top = max(25.0, lane_h - 26.0)
            control = QRectF(
                control_left,
                y + control_top,
                grid_left - control_left - 20.0,
                min(22.0, lane_h - control_top - 2.0),
            )
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if selected:
                painter.setBrush(QColor(hig.SELECTION))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(control, hig.SMALL_CONTROL_RADIUS, hig.SMALL_CONTROL_RADIUS)
            fold_rect = QRectF(
                control.left() + 1.0, control.top(), 19.0, control.height()
            )
            painter.setPen(QPen(QColor(hig.SECONDARY_TEXT), 1.4))
            center_y = fold_rect.center().y()
            painter.drawLine(
                fold_rect.left() + 4.0,
                center_y,
                fold_rect.right() - 4.0,
                center_y,
            )
            if collapsed:
                painter.drawLine(
                    fold_rect.center().x(),
                    fold_rect.top() + 5.0,
                    fold_rect.center().x(),
                    fold_rect.bottom() - 5.0,
                )
            group_font = painter.font()
            group_font.setPixelSize(hig.TYPE_CAPTION)
            painter.save()
            painter.setFont(group_font)
            painter.setPen(QColor(hig.SECONDARY_TEXT))
            label_width = max(0, control.width() - 70)
            painter.drawText(
                QRectF(control.left() + 23.0, control.top(), label_width, control.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(group_label, Qt.ElideRight, int(label_width)),
            )
            painter.restore()
            mute_rect = QRectF(control.right() - 48.0, control.top(), 22.0, control.height())
            solo_rect = QRectF(control.right() - 22.0, control.top(), 22.0, control.height())
            for action, rect, checked in (
                ("group_mute", mute_rect, all(item.muted for item in group.members)),
                ("group_solo", solo_rect, all(item.solo for item in group.members)),
            ):
                self._paint_track_toggle(painter, rect, action, checked)
                self.hit_regions.append((rect, action, track))
            self.hit_regions.append((control.adjusted(0, 0, -48, 0), "group_select", track))
            self.hit_regions.append((fold_rect, "group_fold", track))
            painter.restore()
        if selected and row == group.first_row:
            marker = QColor(hig.SELECTION_INDICATOR if self.hasFocus() else hig.SECONDARY_TEXT)
            _paint_track_selection_marker(painter, left, y, lane_h, marker)
        if (
            row == group.last_row
            or (
                row == group.first_row
                and group.group_id in self._collapsed_arrangement_groups
            )
        ):
            painter.fillRect(
                QRectF(
                    left, y + lane_h - 1.0, group_line_width, 1.0,
                ),
                group_color,
            )

    def _is_arrangement_group_start(self, row: int, track: TrackState) -> bool:
        group = self._arrangement_group_by_row.get(row)
        return group is not None and row == group.first_row

    @staticmethod
    def _paint_track_toggle(
        painter: QPainter, rect: QRectF, action: str, checked: bool, *, hovered: bool = False,
    ) -> None:
        kind = action.removeprefix("group_")
        if kind == "mute":
            symbol = FluentSymbol.SPEAKER_MUTED if checked else FluentSymbol.SPEAKER
            active_ink = hig.ERROR_TEXT
            active_fill = "#402b2c"
        elif kind == "solo":
            symbol = FluentSymbol.HEADPHONES_ACTIVE if checked else FluentSymbol.HEADPHONES
            active_ink = hig.ACCENT
            active_fill = "#3c3223"
        else:
            symbol, active_ink, active_fill = FluentSymbol.SETTINGS, hig.TEXT, hig.CONTROL
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(hig.CONTROL_HOVER if hovered else active_fill if checked else hig.CONTROL))
        painter.setPen(QPen(QColor(active_ink if checked else hig.CONTROL_BORDER), 1) if (checked or hovered) else Qt.NoPen)
        painter.drawRoundedRect(
            rect.adjusted(0.5, 0.5, -0.5, -0.5), hig.SMALL_CONTROL_RADIUS, hig.SMALL_CONTROL_RADIUS,
        )
        color = active_ink if checked else hig.TEXT if hovered else hig.SECONDARY_TEXT
        paint_centered_symbol(painter, rect, symbol, color, 15)
        painter.restore()

    def _track_control_at(self, position: QPointF | None) -> HitRegion | None:
        if position is None:
            return None
        return next((
            hit for hit in reversed(self._hit_region_index.at(position))
            if hit[1] in {"mute", "solo", "fx", "group_mute", "group_solo"}
            and isinstance(hit[2], TrackState)
        ), None)

    def _set_track_control_hover(self, position: QPointF | None) -> HitRegion | None:
        previous = self._track_control_at(self._track_control_hover_pos)
        current = self._track_control_at(position)
        self._track_control_hover_pos = position if current else None
        if previous != current:
            for hit in (previous, current):
                if hit is not None:
                    self.update(hit[0].toAlignedRect())
        return current

    def _paint_track_control_hover(self, painter: QPainter, grid_top: float, grid_h: float) -> None:
        hit = self._track_control_at(self._track_control_hover_pos)
        if hit is None:
            return
        rect, action, track = hit
        state = "muted" if action.endswith("mute") else "solo"
        group = self._arrangement_groups.get(track.arrangement_group_id) if action.startswith("group_") else None
        checked = action != "fx" and all(getattr(member, state) for member in (group.members if group else (track,)))
        painter.save()
        painter.setClipRect(QRectF(0, grid_top, self._header_width, grid_h - self._reference_audio_lane_height()))
        self._paint_track_toggle(painter, rect, action, checked, hovered=True)
        painter.restore()

    def _collapsed_group_for_row(
        self, row: int
    ) -> _ArrangementGroupView | None:
        group = self._arrangement_group_by_row.get(row)
        if (
            group is None
            or row != group.first_row
            or group.group_id not in self._collapsed_arrangement_groups
        ):
            return None
        return group

    def _group_validation_notice(
        self, group: _ArrangementGroupView
    ) -> dict[str, tuple]:
        """Keep hidden member warnings visible on the folded summary row."""

        errors: list[object] = []
        attentions: list[object] = []
        for member in group.members:
            notice = self._track_validation_notice(member)
            errors.extend(notice["errors"])
            attentions.extend(notice["attentions"])
        return {"errors": tuple(errors), "attentions": tuple(attentions)}

    def _paint_collapsed_group_summary(
        self,
        painter: QPainter,
        group: _ArrangementGroupView,
        region_rect: QRectF,
        visible_start: float,
        visible_duration: float,
        *,
        active: bool,
    ) -> None:
        """Paint a bounded, read-only overview of every member in one row."""

        members = group.members
        if not members or region_rect.isEmpty():
            return
        visible_end = visible_start + visible_duration
        band_count = max(
            1,
            min(len(members), int(max(1.0, region_rect.height() - 4.0) // 6.0)),
        )
        band_height = max(3.0, (region_rect.height() - 4.0) / band_count)
        painter.save()
        painter.setClipRect(region_rect)
        painter.setPen(Qt.NoPen)
        member_count = len(members)
        clip_budget = max(16, int(region_rect.width() / max(4.0, member_count * 3.0)))
        note_budget = max(8, int(region_rect.width() / max(3.0, member_count * 2.0)))
        for member_index, member in enumerate(members):
            band = min(
                band_count - 1,
                int(member_index * band_count / member_count),
            )
            band_top = region_rect.top() + 2.0 + band * band_height
            band_rect = QRectF(
                region_rect.left(),
                band_top,
                region_rect.width(),
                max(2.0, band_height - 1.0),
            )
            identity = QColor(member.color)
            if not identity.isValid():
                identity = QColor(group.color)
            rail = QColor(identity)
            rail.setAlpha(190 if active else 92)
            painter.fillRect(
                QRectF(band_rect.left(), band_rect.top(), 3.0, band_rect.height()),
                rail,
            )

            clips = self._visible_track_clips(member, visible_start, visible_end)
            clip_stride = max(1, math.ceil(len(clips) / clip_budget))
            for clip in clips[::clip_stride]:
                start = max(visible_start, float(clip.start_ms))
                end = min(visible_end, float(clip.end_ms))
                if end <= start:
                    continue
                x = region_rect.left() + (
                    (start - visible_start) / visible_duration
                ) * region_rect.width()
                width = max(
                    1.0,
                    (end - start) / visible_duration * region_rect.width(),
                )
                clip_color = QColor(
                    str(getattr(clip, "color", "") or member.color)
                )
                if not clip_color.isValid():
                    clip_color = QColor(identity)
                clip_color.setAlpha(72 if active else 34)
                painter.fillRect(
                    QRectF(x, band_rect.top(), width, band_rect.height()),
                    clip_color,
                )

            overview = self._visible_group_summary_spans(
                member,
                visible_start,
                visible_duration,
                note_budget,
            )
            note_color = QColor(identity)
            note_color.setAlpha(228 if active else 108)
            center_y = band_rect.center().y()
            for start, end in overview:
                x = region_rect.left() + (
                    (start - visible_start) / visible_duration
                ) * region_rect.width()
                width = max(
                    1.5,
                    (end - start) / visible_duration * region_rect.width(),
                )
                painter.fillRect(QRectF(x, center_y - 1.0, width, 2.0), note_color)
        painter.restore()
        self.hit_regions.append((region_rect, "group_summary", members[0]))

    def _paint_track_volume_control(
        self,
        painter: QPainter,
        track: TrackState,
        *,
        left: float,
        header_w: int,
        y: float,
        active: bool,
        compact: bool,
    ) -> QRectF:
        """Paint the game Track-volume field and return its label bounds."""

        volume_y = y + (28.0 if compact else 42.0)
        volume_h = 12.0 if compact else 16.0
        volume_rect = QRectF(left + header_w - 101, volume_y, 50, volume_h)
        value_rect = QRectF(left + header_w - 48, volume_y, 26, volume_h)
        label = tr("轨道音量")
        label_width = self._volume_label_width(painter.fontMetrics(), label)
        label_rect = QRectF(
            volume_rect.left() - label_width - 4.0,
            volume_y,
            label_width,
            volume_h,
        )
        painter.setPen(QColor("#a8b2aa" if active else "#827e76"))
        painter.drawText(label_rect, Qt.AlignCenter, label)
        painter.fillRect(volume_rect, QColor("#1c1c1e"))
        painter.setPen(QPen(QColor("#514a3e"), 1))
        painter.drawRect(volume_rect)
        raw_value = int(track.bdo_track_volume)
        fill_width = (
            (volume_rect.width() - 4.0)
            * max(0, min(100, raw_value))
            / 100.0
        )
        painter.fillRect(
            QRectF(
                volume_rect.left() + 2.0,
                volume_rect.top() + 5.0,
                fill_width,
                6.0,
            ),
            QColor("#83a543" if active else "#556042"),
        )
        handle_x = volume_rect.left() + 2.0 + fill_width
        painter.fillRect(
            QRectF(handle_x - 1.0, volume_rect.top() + 3.0, 2.0, 10.0),
            QColor("#d9c07a" if active else "#81735d"),
        )
        painter.setPen(QColor(
            "#ef7772"
            if not 0 <= raw_value <= 100
            else ("#ffedd4" if active else "#77716a")
        ))
        painter.drawText(
            value_rect, Qt.AlignRight | Qt.AlignVCenter, str(raw_value)
        )
        self.hit_regions.append((volume_rect, "track_volume", track))
        return label_rect

    def _paint_track_validation_state(
        self,
        painter: QPainter,
        track: TrackState,
        row: int,
        left: float,
        y: float,
        *,
        errors: tuple,
        attentions: tuple,
    ) -> None:
        """Paint the one winning validation severity in a track header."""

        if errors:
            marker, accent = "!", QColor(hig.ERROR_TEXT)
        elif attentions:
            marker, accent = "=", self._track_attention_accent(row)
        else:
            return
        badge_rect = QRectF(left + 8.0, y + 7.0, 18.0, 18.0)
        badge_fill = QColor(accent)
        badge_fill.setAlpha(24)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(badge_fill)
        painter.setPen(Qt.NoPen)
        painter.drawRect(badge_rect)
        painter.restore()
        badge_font = painter.font()
        badge_font.setPointSize(max(7, badge_font.pointSize() - 1))
        badge_font.setBold(True)
        painter.save()
        painter.setFont(badge_font)
        painter.setPen(QColor("#fff1dc"))
        painter.drawText(badge_rect, Qt.AlignCenter, marker)
        painter.restore()

    def _paint_track_rows(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        *,
        paint_meters: bool = True,
        paint_selected_velocity: bool = True,
    ) -> None:
        any_solo = any(track.solo for track in self.tracks)
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        instrument_grid_bottom = grid_top + instrument_grid_h
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        painter.save()
        painter.setClipRect(QRectF(left, grid_top, header_w + grid_w, instrument_grid_h))
        visible_rows = self._visible_track_rows()
        workbench = bool(self.property("composerWorkbench"))
        selection_scope = self.selection_scope
        clip_track_ids = {track_id for track_id, _clip_id in self._selected_clip_keys}
        focused = self.hasFocus()
        selection_indicator = QColor(
            hig.SELECTION_INDICATOR if focused else hig.SECONDARY_TEXT
        )
        for visual_row in range(first_row, last_row):
            row, track = visible_rows[visual_row]
            y = grid_top + visual_row * lane_h - scroll_y
            group_start = self._is_arrangement_group_start(row, track)
            collapsed_group = self._collapsed_group_for_row(row)
            active = (
                any(
                    not member.muted and (not any_solo or member.solo)
                    for member in collapsed_group.members
                )
                if collapsed_group is not None
                else not track.muted and (not any_solo or track.solo)
            )
            row_selected = (
                collapsed_group is not None
                and collapsed_group.group_id
                == self._selected_arrangement_group_id
            ) or (
                selection_scope == "track"
                and int(track.track_id) in self._selected_track_ids
            )
            clip_context = (
                selection_scope == "clip" and int(track.track_id) in clip_track_ids
            )
            validation_notice = (
                self._group_validation_notice(collapsed_group)
                if collapsed_group is not None
                else self._track_validation_notice(track)
            )
            validation_errors = validation_notice["errors"]
            validation_attentions = validation_notice["attentions"]
            has_validation_notice = bool(
                validation_errors or validation_attentions
            )
            lane_color = QColor(215, 215, 219, 13 if row_selected else 4 * (visual_row % 2))
            painter.fillRect(QRectF(grid_left, y, grid_w, lane_h), lane_color)
            if row_selected:
                header_color = hig.CONTROL_PRESSED
            elif clip_context:
                header_color = hig.CONTROL
            else:
                header_color = "#202022" if active else hig.PANEL
            painter.fillRect(QRectF(left, y, header_w, lane_h), QColor(header_color))
            identity = QColor(track.color)
            identity.setAlpha(158 if active else 80)
            painter.fillRect(QRectF(left, y + 1, 2, lane_h - 2), identity)
            painter.fillRect(QRectF(left, y + lane_h - 1, header_w, 1), QColor("#303033"))
            painter.fillRect(QRectF(grid_left, y + lane_h - 1, grid_w, 1), QColor("#252528"))

            self.hit_regions.append((QRectF(left, y, header_w + grid_w, lane_h), "lane", track))
            row_rect = QRectF(left, y, header_w, lane_h)
            self.hit_regions.append((row_rect, "select", track))

            adaptation = self._instrument_adaptations.get(
                int(track.bdo_instrument_id)
            )
            header_background_rect = instrument_header_background_rect(
                row_rect
            )
            if not workbench and adaptation is not None and not header_background_rect.isEmpty():
                paint_instrument_header_background(
                    painter,
                    header_background_rect,
                    visual_key=adaptation.visual_key,
                    accent=QColor(track.color),
                    pixmap=self.instrument_lane_art.pixmap_for(
                        int(track.bdo_instrument_id)
                    ),
                    active=active,
                )
            if row_selected:
                _paint_track_selection_marker(painter, left, y, lane_h, selection_indicator)

            # One lane has one visible severity. Export blockers always win;
            # details remain available in the lane tooltip.
            self._paint_track_validation_state(
                painter, track, row, left, y,
                errors=validation_errors,
                attentions=validation_attentions,
            )

            controls = [("mute", 26), ("solo", 26), ("fx", 28)]
            if workbench:
                controls = [("mute", 22), ("solo", 22)]
            control_gap = 4.0
            controls_width = sum(width for _action, width in controls)
            controls_width += control_gap * max(0, len(controls) - 1)
            control_x = left + header_w - 20.0 - controls_width
            compact_lane = lane_h < 58
            control_y = y + (4.0 if compact_lane else 8.0)
            if collapsed_group is None:
                for action, width in controls:
                    rect = QRectF(control_x, control_y, width, 20 if compact_lane else 22)
                    checked = (action == "mute" and track.muted) or (action == "solo" and track.solo)
                    self._paint_track_toggle(painter, rect, action, checked)
                    self.hit_regions.append((rect, action, track))
                    control_x += width + control_gap

            # This is the game's track-volume field, not the separate note-
            # velocity scale.  The official authoring UI clamps edits to
            # 0..100 (default 70), although imported score bytes may be above
            # 100.  Such raw values remain visible and untouched until the
            # user deliberately edits this slider.
            volume_label_rect = (
                QRectF(left + header_w - 146.0, y + 36.0, 1.0, 18.0)
                if collapsed_group is not None or self.property("composerWorkbench")
                else self._paint_track_volume_control(
                    painter,
                    track,
                    left=left,
                    header_w=header_w,
                    y=y,
                    active=active,
                    compact=compact_lane,
                )
            )

            if paint_meters and collapsed_group is None:
                self._paint_track_meter(
                    painter,
                    track,
                    left + header_w - 14,
                    y,
                    lane_h,
                    active,
                )

            region_rect = QRectF(
                grid_left, y + CLIP_REGION_INSET, grid_w,
                lane_h - 2 * CLIP_REGION_INSET,
            )
            if not self.property("composerWorkbench"):
                self._paint_track_region_background(
                    painter, region_rect, focused=row_selected, active=active,
                    has_error=bool(validation_errors),
                )

            clip_regions: list[tuple[ArrangementClipState, QRectF, bool]] = []
            if collapsed_group is not None:
                self._paint_collapsed_group_summary(
                    painter,
                    collapsed_group,
                    region_rect,
                    visible_start,
                    visible_duration,
                    active=active,
                )
            else:
                clip_regions = self._paint_track_clip(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    active=active,
                    has_error=bool(validation_errors),
                )

            if clip_regions and track.notes:
                pitch_min, pitch_max = self._track_pitch_bounds(track)
                pitch_span = pitch_max - pitch_min
                has_title_space = region_rect.height() - 2 * CLIP_BODY_INSET >= CLIP_TITLE_MIN_HEIGHT
                title_height = CLIP_TITLE_HEIGHT if has_title_space else 0
                preview_rect = region_rect.adjusted(0, CLIP_BODY_INSET + title_height, 0, -4)
                preview_path = QPainterPath()
                preview_path.setFillRule(Qt.FillRule.WindingFill)
                for _clip, clip_rect, _selected in clip_regions:
                    preview_clip = clip_rect.adjusted(1, 0, -1, 0).intersected(preview_rect)
                    if not preview_clip.isEmpty():
                        preview_path.addRect(preview_clip)
                painter.save()
                painter.setClipPath(preview_path, Qt.ClipOperation.IntersectClip)
                # One extra match selects the overview without enumerating
                # the rest of a dense visible passage.
                ordered, note_lo, note_hi = self._visible_track_note_window(
                    track,
                    visible_start,
                    visible_end,
                    limit=self._note_preview_detail_limit(preview_rect.width()) + 1,
                )
                (
                    normal_rects,
                    articulation_markers,
                    invalid_rects,
                ) = self._timeline_note_rect_batches(
                    track,
                    preview_rect,
                    visible_start,
                    visible_duration,
                    pitch_min,
                    pitch_span,
                    ordered,
                    note_lo,
                    note_hi,
                )
                painter.setPen(Qt.NoPen)
                if normal_rects:
                    note_fill = QColor(track.color if active else hig.DISABLED_TEXT)
                    note_fill.setAlpha(208 if active else 88)
                    painter.setBrush(note_fill)
                    painter.drawRects(normal_rects)
                for color, markers in articulation_markers.items():
                    painter.setBrush(QColor(color))
                    painter.drawRects(markers)
                if invalid_rects:
                    painter.setBrush(QColor("#d94a4a"))
                    painter.setPen(QPen(QColor("#ffb1a8"), 1))
                    painter.drawRects(invalid_rects)
                painter.restore()

            if collapsed_group is None and not self._viewport_motion_active and not self.property("composerWorkbench"):
                self.velocity_curve_overlay.paint_velocity_trace(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    active,
                )
            if (
                collapsed_group is None
                and (row_selected or clip_context)
                and paint_selected_velocity
            ):
                self.velocity_curve_overlay.paint_selected_track(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    self.time_range,
                )
            for clip, clip_rect, selected in clip_regions:
                clip_title_visible = (
                    grid_top <= clip_rect.top()
                    and clip_rect.top() + CLIP_TITLE_HEIGHT <= instrument_grid_bottom
                )
                if clip_title_visible:
                    paint_track_clip_metadata(
                        painter,
                        track,
                        clip,
                        clip_rect,
                        active=active,
                        selected=selected,
                    )
                if selected:
                    paint_clip_selection(
                        painter, clip_rect, clip_identity_color(clip, track),
                        focused=focused, has_error=bool(validation_errors),
                        can_trim=self.arrangement_tool == "select" and clip_end_handle_visible(
                            clip, region_rect, visible_start, visible_duration,
                        ),
                    )

            title_left = left + (34.0 if has_validation_notice else 12.0)
            title_right = left + header_w - (
                20.0 if collapsed_group is not None else (72.0 if workbench else 114.0)
            )
            title_width = max(0.0, title_right - title_left)
            title_color = hig.SELECTION_TEXT if row_selected else (
                hig.TEXT if active else hig.DISABLED_TEXT
            )
            painter.setPen(QColor(title_color))
            instrument_name = track_identity.game_instrument_name(track, tr)
            title_text = (
                trf(
                    "乐器组 · {instrument}",
                    instrument=_ui_bdo_instrument_name(
                        collapsed_group.instrument_id
                    ),
                )
                if collapsed_group is not None
                else track_identity.title(track, tr, compact_lane)
            )
            if grid_top <= y + 8 and y + 32 <= instrument_grid_bottom:
                painter.save()
                title_font = painter.font()
                title_font.setWeight(QFont.Weight.DemiBold)
                painter.setFont(title_font)
                available = max(0, int(title_width - 2.0))
                if painter.fontMetrics().horizontalAdvance(title_text) > available:
                    title_font.setPixelSize(hig.TYPE_SECONDARY)
                    painter.setFont(title_font)
                painter.drawText(
                    QRectF(title_left, y + 8, title_width, 24),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    painter.fontMetrics().elidedText(title_text, Qt.ElideRight, available),
                )
                painter.restore()
            metadata_top = y + lane_h - 26
            metadata_visible = grid_top <= metadata_top and metadata_top + 22 <= instrument_grid_bottom
            if not group_start and not compact_lane and metadata_visible:
                painter.setPen(QColor(hig.SECONDARY_TEXT if active else hig.DISABLED_TEXT))
                metadata = instrument_name if workbench else f"BDO · {instrument_name} · " + trf(
                    "{count} 音符 · {pitch_range}",
                    count=(
                        len(index.intervals.items)
                        if (index := self._track_note_indexes.get(id(track)))
                        is not None else 0
                    ),
                    pitch_range=(
                        f"{note_name(index.pitch_min)} - {note_name(index.pitch_max)}"
                        if index is not None and index.intervals.items else "-"
                    ),
                )
                painter.save()
                painter.setFont(canvas_caption_font(painter.font()))
                metadata_left = left + 12.0
                metadata_right = left + header_w - 20.0 if workbench else volume_label_rect.left() - 6.0
                metadata_width = max(0.0, metadata_right - metadata_left)
                painter.drawText(
                    QRectF(metadata_left, metadata_top, metadata_width, 22),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    painter.fontMetrics().elidedText(
                        metadata, Qt.ElideRight,
                        max(0, int(metadata_width - 4.0)),
                    ),
                )
                painter.restore()
            self._paint_arrangement_group_marker(
                painter, track, row, left, grid_left, grid_w, y, lane_h,
                has_validation_notice,
            )
        painter.restore()
        if self.reference_audio is not None:
            self._paint_reference_audio_row(
                painter,
                left,
                grid_left,
                grid_top,
                header_w,
                grid_w,
                grid_h,
                visible_start,
                visible_duration,
                visible_end,
            )
    @staticmethod
    def _paint_track_region_background(
        painter: QPainter, region_rect: QRectF, *, focused: bool,
        active: bool, has_error: bool,
    ) -> None:
        background = QColor(
            "#391719" if has_error else (hig.SELECTION if focused else "#242427")
        )
        background.setAlpha(184 if has_error else (152 if active else 116))
        painter.setBrush(background)
        painter.setPen(QPen(
            QColor(
                "#d94a4a" if has_error
                else (hig.CONTROL_BORDER if focused else "#3b3b3f")
            ),
            2 if has_error else 1,
        ))
        painter.drawRect(region_rect)

    def _paint_track_clip(
        self,
        painter: QPainter,
        track: TrackState,
        region_rect: QRectF,
        visible_start: float,
        visible_duration: float,
        *,
        active: bool,
        has_error: bool = False,
    ) -> list[tuple[ArrangementClipState, QRectF, bool]]:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip_regions: list[tuple[ArrangementClipState, QRectF, bool]] = []
        for clip in self._visible_track_clips(
            track, visible_start, visible_start + visible_duration
        ):
            selected = (
                int(track.track_id), str(clip.clip_id)
            ) in self._selected_clip_keys
            clip_rect = clip_display_rect(clip, region_rect, visible_start, visible_duration)
            if clip_rect.isEmpty():
                continue
            identity_color = clip_identity_color(clip, track)
            clip_color = QColor(hig.ERROR_TEXT if has_error else identity_color)
            clip_color.setAlpha((65 if selected else 55) if active else 24)
            if has_error:
                border = QColor(hig.ERROR_TEXT)
            else:
                border = QColor(identity_color)
                border.setAlpha(111 if active else 51)
            body = clip_rect.adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(hig.PANEL))
            painter.drawRoundedRect(body, CLIP_CORNER_RADIUS, CLIP_CORNER_RADIUS)
            painter.setBrush(clip_color)
            painter.setPen(QPen(border, 1))
            painter.drawRoundedRect(body, CLIP_CORNER_RADIUS, CLIP_CORNER_RADIUS)
            if clip_rect.height() >= CLIP_TITLE_MIN_HEIGHT and clip_rect.width() >= CLIP_TITLE_MIN_WIDTH:
                title_fill = QColor(identity_color if selected and not has_error else Qt.black)
                title_fill.setAlpha((40 if selected and not has_error else 28) if active else 16)
                painter.fillRect(
                    QRectF(body.left() + 3, body.top() + 1, body.width() - 6, CLIP_TITLE_HEIGHT - 2),
                    title_fill,
                )
                painter.fillRect(
                    QRectF(clip_rect.left() + 4, clip_rect.top() + CLIP_TITLE_HEIGHT,
                           clip_rect.width() - 8, 1),
                    QColor(234, 234, 238, 21 if active else 12),
                )
            clip_regions.append((clip, clip_rect, selected))
            self.hit_regions.append((
                clip_rect, f"clip_body|{clip.clip_id}", track
            ))
            if clip_end_handle_visible(clip, region_rect, visible_start, visible_duration):
                handle_width = min(7.0, clip_rect.width() / 2.0)
                self.hit_regions.append((QRectF(
                    clip_rect.right() - handle_width, clip_rect.top(),
                    handle_width, clip_rect.height(),
                ), f"clip_end|{clip.clip_id}", track))
        painter.restore()
        return clip_regions

    @staticmethod
    def _note_preview_detail_limit(width: float) -> int:
        return max(320, int(width / 2.0))

    def _timeline_note_rect_batches(
        self,
        track: TrackState,
        region: QRectF,
        visible_start: float,
        visible_duration: float,
        pitch_min: int,
        pitch_span: int,
        ordered: list[object],
        note_lo: int,
        note_hi: int,
    ) -> tuple[list[QRectF], dict[str, list[QRectF]], list[QRectF]]:
        """Project visible notes with a pixel-bounded overview LOD.

        At overview zoom, summarize dense onsets with a narrow pitch contour.
        Clipping the buckets to their individual Clips preserves the gaps in
        the arrangement. Conversion and articulation markers stay visible.
        """

        normal_rects: list[QRectF] = []
        articulation_markers: dict[str, list[QRectF]] = {}
        invalid_rects: list[QRectF] = []
        note_count = max(0, note_hi - note_lo)
        detail_limit = self._note_preview_detail_limit(region.width())
        use_overview = note_count > detail_limit
        note_height = 2.0
        pitch_pad = 2.0
        pitch_height = max(0.0, region.height() - 2 * pitch_pad - note_height)
        pitch_step = pitch_height / max(1, pitch_span)
        lowest_pitch_y = (
            region.bottom() - pitch_pad - note_height
            if pitch_span else region.center().y() - note_height / 2
        )
        scale = region.width() / visible_duration
        if use_overview:
            conversion_problem_mask = self._conversion_problem_mask(track)
            clips = self._visible_track_clips(
                track,
                visible_start,
                visible_start + visible_duration,
            )
            overview_bins = self._visible_note_overview_bins(
                track,
                visible_start,
                visible_duration,
                region.width(),
            )
            if self._viewport_motion_active and len(overview_bins) > 1:
                overview_bins = tuple(
                    _TimelineNoteOverviewBin(
                        start=min(value.start for value in pair),
                        end=max(value.end for value in pair),
                        pitch_min=min(value.pitch_min for value in pair),
                        pitch_max=max(value.pitch_max for value in pair),
                        pitch_mask=pair[0].pitch_mask
                        | (pair[1].pitch_mask if len(pair) > 1 else 0),
                        articulation_type=pair[0].articulation_type
                        or (
                            pair[1].articulation_type
                            if len(pair) > 1
                            else 0
                        ),
                    )
                    for index in range(0, len(overview_bins), 2)
                    for pair in (overview_bins[index:index + 2],)
                )
            clip_start_index = 0
            for summary in overview_bins:
                top = lowest_pitch_y - (summary.pitch_max - pitch_min) * pitch_step
                spread = (summary.pitch_max - summary.pitch_min) * pitch_step
                height = min(note_height + spread, max(3.0, pitch_height * 0.42))
                top += (note_height + spread - height) / 2
                while clip_start_index < len(clips) and clips[clip_start_index].end_ms <= summary.start:
                    clip_start_index += 1
                for clip_index in range(clip_start_index, len(clips)):
                    clip = clips[clip_index]
                    if clip.start_ms >= summary.end:
                        break
                    summary_start = max(float(summary.start), clip.start_ms)
                    summary_end = min(float(summary.end), clip.end_ms)
                    if summary_end <= summary_start:
                        continue
                    x = region.left() + (summary_start - visible_start) * scale
                    width = max(1.0, (summary_end - summary_start) * scale)
                    rect = QRectF(x, top, width, height)
                    if summary.pitch_mask & conversion_problem_mask:
                        invalid_rects.append(rect)
                        continue
                    normal_rects.append(rect)
                    if summary.articulation_type != 0:
                        marker_color = articulation_color(summary.articulation_type)
                        articulation_markers.setdefault(marker_color, []).append(
                            QRectF(
                                rect.left(),
                                rect.top(),
                                min(1.5, rect.width()),
                                rect.height(),
                            )
                        )
            return normal_rects, articulation_markers, invalid_rects

        invalid_keys = self._conversion_note_key_set(track)
        for note_index in range(note_lo, note_hi):
            note = ordered[note_index]
            note_start = float(note.start)
            note_end = note_start + float(note.dur)
            if note_end <= note_start or note_end < visible_start or note_start > visible_start + visible_duration:
                continue
            x = region.left() + (note_start - visible_start) * scale
            width = max(1.0, (note_end - note_start) * scale)
            note_y = lowest_pitch_y - (int(note.pitch) - pitch_min) * pitch_step
            has_problem = invalid_keys and self._validation_note_key(note) in invalid_keys
            ntype = int(getattr(note, "ntype", 0))

            note_rect = QRectF(x, note_y, width, note_height)
            if note_rect.width() <= 0.0:
                continue
            if has_problem:
                invalid_rects.append(note_rect)
            else:
                normal_rects.append(note_rect)
                if ntype != 0:
                    marker = QRectF(
                        note_rect.left(),
                        note_rect.top(),
                        min(1.5, note_rect.width()),
                        note_rect.height(),
                    )
                    articulation_markers.setdefault(
                        articulation_color(ntype), []
                    ).append(marker)
        return normal_rects, articulation_markers, invalid_rects

    @staticmethod
    def _volume_label_width(font_metrics, label: str) -> float:
        """Reserve the rendered locale width instead of the Chinese width."""

        return float(
            max(
                25,
                font_metrics.horizontalAdvance(str(label)) + 8,
            )
        )

    @staticmethod
    def _track_volume_from_position(rect: QRectF, x: float) -> int:
        if rect.width() <= 0:
            return 0
        ratio = max(0.0, min(1.0, (float(x) - rect.left()) / rect.width()))
        return max(0, min(100, round(ratio * 100.0)))

    def _set_track_volume_from_position(
        self,
        track: TrackState,
        rect: QRectF,
        x: float,
    ) -> bool:
        value = self._track_volume_from_position(rect, x)
        if int(track.bdo_track_volume) == value:
            return False
        track.bdo_track_volume = value
        if track is self.selected_track:
            self._update_accessible_track_state()
        self.update(rect.adjusted(-4.0, -3.0, 32.0, 3.0).toAlignedRect())
        return True

    def _paint_reference_audio_row(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        controller = self.reference_audio
        if controller is None:
            return
        reference_h = self._reference_audio_lane_height()
        y = grid_top + grid_h - reference_h
        lane_rect = QRectF(left, y, header_w + grid_w, reference_h)
        header_rect = QRectF(left, y, header_w, reference_h)
        painter.fillRect(lane_rect, QColor(28, 28, 31, 238))
        painter.fillRect(QRectF(left, y, lane_rect.width(), 1), QColor(hig.CONTROL_BORDER))
        self.hit_regions.append((lane_rect, "audio_lane", controller))
        if not controller.audio_path:
            return

        waveform_rect = QRectF(grid_left, y + 5, grid_w, reference_h - 10)
        painter.fillRect(QRectF(left, y + 1, header_w, reference_h - 1), QColor("#242425"))
        painter.fillRect(QRectF(grid_left, y + 1, 1, reference_h - 1), QColor(hig.CONTROL_BORDER))
        title_top = header_rect.center().y() - 17
        text_width = self._reference_menu_button.x() - 2 * hig.GROUP_GAP
        painter.setPen(QColor("#eeece8"))
        painter.drawText(
            QRectF(left + 12, title_top, text_width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(tr("参考音频"), Qt.ElideRight, int(text_width)),
        )
        painter.save()
        painter.setFont(canvas_caption_font(painter.font()))
        painter.setPen(QColor("#a6a39e"))
        painter.drawText(
            QRectF(left + 12, title_top + 18, text_width, 17),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(controller.display_name, Qt.ElideMiddle, int(text_width)),
        )
        painter.restore()
        self.hit_regions.append((waveform_rect, "audio_waveform", controller))

        pixels_per_ms = waveform_rect.width() / visible_duration
        audio_start = controller.audio_to_project(0.0)
        audio_end = controller.project_end_ms
        audio_rect = QRectF(
            waveform_rect.left() + (audio_start - visible_start) * pixels_per_ms,
            waveform_rect.top(),
            max(0.0, audio_end - audio_start) * pixels_per_ms,
            waveform_rect.height(),
        ).intersected(waveform_rect)
        center_y = waveform_rect.center().y()
        if not audio_rect.isEmpty():
            painter.fillRect(audio_rect, QColor(201, 150, 82, 21))
            painter.fillRect(QRectF(audio_rect.left(), center_y, audio_rect.width(), 1), QColor("#5a4935"))
            if visible_start <= audio_start < visible_end:
                painter.fillRect(QRectF(audio_rect.left(), audio_rect.top(), 1, audio_rect.height()), QColor("#98734a"))

        if controller.waveform and not audio_rect.isEmpty():
            audio_visible_start = controller.project_to_audio(visible_start)
            audio_visible_end = controller.project_to_audio(visible_end)
            first = max(
                0,
                bisect_left(controller.waveform_starts, audio_visible_start) - 1,
            )
            last = bisect_right(controller.waveform_starts, audio_visible_end)
            max_half_height = max(1.0, waveform_rect.height() / 2.0 - 3.0)
            bars: list[QRectF] = []
            column_peaks: dict[int, float] = {}
            for index in range(first, last):
                bucket_start, bucket_end, peak = controller.waveform[index]
                if peak <= 0.0 or bucket_end <= audio_visible_start:
                    continue
                x = waveform_rect.left() + (audio_start + bucket_start - visible_start) * pixels_per_ms
                width = (bucket_end - bucket_start) * pixels_per_ms
                half_height = max(0.75, min(1.0, peak) * max_half_height)
                if width < 1.0:
                    column = int(max(audio_rect.left(), x))
                    column_peaks[column] = max(column_peaks.get(column, 0.0), half_height)
                else:
                    bars.append(QRectF(x, center_y - half_height, width, half_height * 2.0))
            bars.extend(
                QRectF(x, center_y - half_height, 1, half_height * 2)
                for x, half_height in column_peaks.items()
            )
            if bars:
                painter.save()
                painter.setClipRect(audio_rect, Qt.IntersectClip)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#c99658"))
                painter.drawRects(bars)
                painter.restore()
        elif not controller.waveform:
            painter.setPen(QColor("#a6a39e"))
            placeholder = tr("正在分析波形…") if controller.waveform_loading else tr("暂无波形预览")
            painter.drawText(waveform_rect, Qt.AlignCenter, placeholder)

    def _paint_measure_ruler(
        self,
        painter: QPainter,
        area: QRectF,
        left: float,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        ruler_h: int,
        ticks: list[tuple[float, bool, str]],
        visible_start: float,
        visible_duration: float,
    ) -> None:
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor(hig.PANEL))
        painter.save()
        font = painter.font()
        font.setPixelSize(hig.TYPE_CAPTION)
        painter.setFont(font)
        painter.setPen(QColor(hig.SECONDARY_TEXT))
        painter.drawText(
            QRectF(left + 12, top, grid_left - left - 24, ruler_h),
            Qt.AlignVCenter,
            trf("轨道 · {count}", count=self._musical_track_count()),
        )
        painter.setClipRect(QRectF(grid_left, top, grid_w, ruler_h))
        for value, is_major, label in ticks:
            x = round(grid_left + (value - visible_start) / visible_duration * grid_w)
            tick_height = 7 if is_major else 4
            painter.fillRect(
                QRectF(x, grid_top - tick_height, 1, tick_height),
                QColor(hig.INDICATOR_BORDER if is_major else hig.CONTROL_BORDER),
            )
            if label:
                painter.setPen(QColor(hig.SECONDARY_TEXT))
                painter.drawText(x + 6, int(top + 20), label)
        painter.restore()
        painter.setPen(QPen(QColor(hig.SEPARATOR), 1))
        painter.drawLine(grid_left, top, grid_left, grid_top + grid_h)
        painter.drawLine(left, grid_top, grid_left + grid_w, grid_top)

    def _paint_track_meter(
        self,
        painter: QPainter,
        track: TrackState,
        meter_left: float,
        row_y: float,
        lane_h: int,
        active: bool,
    ) -> None:
        meter_level = (
            self.track_levels.get(int(track.track_id), 0) if active else 0
        )
        self._paint_meter_level(
            painter, meter_left, row_y, lane_h, meter_level
        )

    @staticmethod
    def _track_meter_rect(meter_left: float, row_y: float, lane_h: int) -> QRectF:
        return QRectF(meter_left + 1, row_y + 8, 5, lane_h - 16)

    @classmethod
    def _paint_meter_level(
        cls,
        painter: QPainter,
        meter_left: float,
        row_y: float,
        lane_h: int,
        lit_segments: int,
    ) -> None:
        """Paint one bounded level meter for a Track or folded Group."""

        meter_rect = cls._track_meter_rect(meter_left, row_y, lane_h)
        painter.fillRect(meter_rect, _METER_UNLIT)
        unit = meter_rect.height() / cls.METER_SEGMENT_COUNT
        for lower, upper, color in ((0, 7, _METER_LOW), (7, 9, _METER_HIGH), (9, 10, _METER_PEAK)):
            level = min(lit_segments, upper)
            if level <= lower:
                break
            painter.fillRect(
                QRectF(
                    meter_rect.left(),
                    meter_rect.bottom() - level * unit,
                    meter_rect.width(),
                    (level - lower) * unit,
                ),
                color,
            )

    def _static_timeline_key(
        self,
        *,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
    ) -> tuple[object, ...]:
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        visible_tracks: list[tuple[object, ...]] = []
        for row, track in self._visible_track_rows()[first_row:last_row]:
            index = self._track_note_indexes.get(id(track))
            collapsed_group = self._collapsed_group_for_row(row)
            notice = (
                self._group_validation_notice(collapsed_group)
                if collapsed_group is not None
                else self._track_validation_notice(track)
            )
            member_key = (
                tuple(
                    (
                        id(member),
                        id(member_index.intervals)
                        if member_index is not None else 0,
                        id(member_index.clips)
                        if member_index is not None else 0,
                        int(member.track_id),
                        str(member.display_name),
                        str(member.color),
                        bool(member.muted),
                        bool(member.solo),
                    )
                    for member in collapsed_group.members
                    for member_index in (
                        self._track_note_indexes.get(id(member)),
                    )
                )
                if collapsed_group is not None
                else ()
            )
            visible_tracks.append(
                (
                    id(track),
                    id(index.intervals) if index is not None else 0,
                    int(track.track_id),
                    str(track.display_name),
                    int(track.bdo_instrument_id),
                    bool(track.muted),
                    bool(track.solo),
                    float(track.duration_scale),
                    str(track.marnian_synth_mode),
                    str(track.color),
                    int(track.bdo_track_volume),
                    str(track.arrangement_group_id),
                    id(index.clips) if index is not None else 0,
                    tuple(notice["errors"]),
                    tuple(notice["attentions"]),
                    _ui_bdo_instrument_name(track.bdo_instrument_id),
                    member_key,
                )
            )
        controller = self.reference_audio
        waveform = getattr(controller, "waveform", ()) if controller else ()
        audio_path = getattr(controller, "audio_path", "") if controller else ""
        reference_key = (
            id(controller),
            str(audio_path or ""),
            str(getattr(controller, "display_name", "") or ""),
            tr("参考音频") if controller else "",
            bool(getattr(controller, "waveform_loading", False)),
            id(waveform),
            len(waveform) if waveform is not None else 0,
            round(controller.audio_to_project(0.0), 3) if audio_path else 0.0,
            round(float(getattr(controller, "project_end_ms", 0.0) or 0.0), 3),
        )
        return (
            self.width(),
            self.height(),
            self.font().toString(),
            round(float(self.devicePixelRatioF()), 3),
            round(float(visible_start), 3),
            round(float(visible_duration), 3),
            round(float(grid_h), 3),
            int(self.track_scroll.value()),
            bool(self._viewport_motion_active),
            bool(self.track_scroll.isVisible()),
            int(self.bpm),
            int(self.time_sig),
            round(float(self.beat_origin_ms), 3),
            self.selection_scope,
            tuple(sorted(self._selected_track_ids)),
            self._selected_clip_track_id,
            self._selected_clip_id,
            tuple(sorted(self._selected_clip_keys)),
            self._selected_arrangement_group_id,
            tuple(sorted(self._collapsed_arrangement_groups)),
            bool(self.hasFocus()),
            self.arrangement_tool,
            self.pitch_transform_plan,
            tuple(visible_tracks),
            reference_key,
            tr("轨道"),
            tr("轨道音量"),
            tr("乐器组 ×{count}"),
        )

    def _render_static_timeline(
        self,
        *,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        lane_h: int,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        pixel_size = QSize(
            max(1, round(self.width() * ratio)),
            max(1, round(self.height() * ratio)),
        )
        cache = self._static_timeline_cache
        if cache.size() != pixel_size or cache.devicePixelRatio() != ratio:
            cache = QPixmap(pixel_size)
            cache.setDevicePixelRatio(ratio)
        # The background painter covers the entire pixmap with opaque color.
        # Reuse its storage when panning and skip a transparent clear.
        painter = QPainter(cache)
        painter.setFont(self.font())
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        try:
            self.hit_regions = []
            self._paint_canvas_background(painter)
            left, top, grid_left, grid_top = self._paint_timeline_shell(
                painter,
                area,
                header_w,
                ruler_h,
                grid_w,
                grid_h,
            )
            self.grid_rect = QRectF(
                grid_left,
                top,
                grid_w,
                grid_h + ruler_h,
            )
            ticks = self._visible_musical_ticks(visible_start, visible_duration, grid_w)
            self._paint_musical_grid(
                painter,
                QRectF(grid_left, grid_top, grid_w, grid_h),
                visible_start,
                visible_duration,
                ticks,
            )
            self._paint_track_rows(
                painter,
                left,
                grid_left,
                grid_top,
                header_w,
                grid_w,
                grid_h,
                lane_h,
                visible_start,
                visible_duration,
                visible_end,
                paint_meters=False,
                paint_selected_velocity=False,
            )
            self._paint_measure_ruler(
                painter,
                area,
                left,
                top,
                grid_left,
                grid_top,
                grid_w,
                grid_h,
                ruler_h,
                ticks,
                visible_start,
                visible_duration,
            )
        finally:
            painter.end()
        self._static_timeline_cache = cache
        self._static_timeline_hit_regions = self.hit_regions
        self._hit_region_index = TimelineHitIndex(self.hit_regions, defer=self._viewport_motion_active)

    def _paint_dynamic_track_overlays(
        self,
        painter: QPainter,
        *,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        damage: QRegion,
    ) -> None:
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        meter_left = left + header_w - 14
        meter_column = QRectF(meter_left - 1, grid_top, 9, instrument_grid_h).toAlignedRect()
        meter_damage = damage.intersected(meter_column)
        paint_meters = not meter_damage.isEmpty()
        paint_all_meters = meter_damage.rectCount() == 1 and meter_damage.boundingRect() == meter_column
        any_solo = paint_meters and any(track.solo for track in self.tracks)
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        painter.save()
        painter.setClipRect(
            QRectF(left, grid_top, header_w + grid_w, instrument_grid_h)
        )
        visible_rows = self._visible_track_rows()
        for visual_row in range(first_row, last_row):
            row, track = visible_rows[visual_row]
            y = grid_top + visual_row * lane_h - scroll_y
            paint_meter = paint_meters and (
                paint_all_meters or meter_damage.intersects(
                    self._track_meter_rect(meter_left, y, lane_h).toAlignedRect()
                )
            )
            if not paint_meter and track is not self.selected_track:
                continue
            collapsed_group = self._collapsed_group_for_row(row)
            if paint_meter and collapsed_group is not None:
                group_level = max(
                    (
                        self.track_levels.get(int(member.track_id), 0)
                        for member in collapsed_group.members
                        if not member.muted and (not any_solo or member.solo)
                    ),
                    default=0,
                )
                self._paint_meter_level(
                    painter,
                    meter_left,
                    y,
                    lane_h,
                    group_level,
                )
            elif paint_meter:
                active = not track.muted and (not any_solo or track.solo)
                self._paint_track_meter(
                    painter,
                    track,
                    meter_left,
                    y,
                    lane_h,
                    active,
                )
            if collapsed_group is None and track is self.selected_track:
                region_rect = QRectF(
                    grid_left,
                    y + 9,
                    grid_w,
                    lane_h - 18,
                )
                self._paint_merge_overlap_regions(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                )
                self.velocity_curve_overlay.paint_selected_track(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    self.time_range,
                )
        painter.restore()

    def _paint_merge_overlap_regions(
        self,
        painter: QPainter,
        track: TrackState,
        region_rect: QRectF,
        visible_start: float,
        visible_duration: float,
    ) -> None:
        if int(track.track_id) != self._merge_overlap_track_id:
            return
        visible_end = visible_start + visible_duration
        for region in self._merge_overlap_regions:
            start = max(visible_start, float(region.start_ms))
            end = min(visible_end, float(region.end_ms))
            if end <= start:
                continue
            x = region_rect.left() + (
                (start - visible_start) / visible_duration
            ) * region_rect.width()
            width = max(2.0, (end - start) / visible_duration * region_rect.width())
            rect = QRectF(x, region_rect.top(), width, region_rect.height())
            painter.fillRect(rect, QColor(220, 113, 62, 76))
            painter.setPen(QPen(QColor("#f0a067"), 1, Qt.DashLine))
            painter.drawRect(rect)
    def _paint_clip_drag_preview(
        self,
        painter: QPainter,
        *,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
    ) -> None:
        target = self._clip_drag_target
        if not self._clip_drag_active or self._clip_drag_source is None or target is None:
            return
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        painter.save()
        painter.setClipRect(self.grid_rect, Qt.ClipOperation.IntersectClip)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(214, 184, 103, 62))
        painter.setPen(QPen(QColor(hig.SELECTION_INDICATOR), 1.5))
        if self._clip_group_drag_keys:
            delta = (
                self._clip_drag_start_ms
                - self._clip_drag_origin_start_ms
            )
            height = lane_h - 2 * CLIP_LANE_INSET
            # Keep the preview stroke and its antialiasing at the viewport edges.
            right, bottom = self.width() + 3.0, self.height() + 3.0
            row_offset = self._clip_group_drag_track_offset
            row_tops = {
                int(track.track_id): grid_top + (row + row_offset) * lane_h - scroll_y + CLIP_LANE_INSET
                for track in self.tracks
                if (row := self._visual_row_for_track(track)) is not None
            }
            for key in self._clip_group_drag_keys:
                y = row_tops.get(key[0])
                if y is None or y > bottom or y + height < -3.0:
                    continue
                origin = self._clip_group_drag_origins.get(key)
                if origin is None:
                    continue
                x = grid_left + (
                    (origin[0] + delta - visible_start)
                    / visible_duration
                ) * grid_w
                width = max(
                    8.0,
                    (origin[1] - origin[0])
                    / visible_duration * grid_w,
                )
                if x <= right and x + width >= -3.0:
                    painter.drawRoundedRect(QRectF(x, y, width, height).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        else:
            row = self._visual_row_for_track(target)
            if row is None:
                painter.restore()
                return
            x = grid_left + (
                (self._clip_drag_start_ms - visible_start)
                / visible_duration
            ) * grid_w
            width = max(
                8.0,
                (self._clip_drag_end_ms - self._clip_drag_start_ms)
                / visible_duration * grid_w,
            )
            painter.drawRoundedRect(QRectF(
                x,
                grid_top + row * lane_h - scroll_y + CLIP_LANE_INSET,
                width,
                lane_h - 2 * CLIP_LANE_INSET,
            ).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        snap = self._clip_snap_result
        if snap.target_ms is not None:
            guide_x = grid_left + (
                (snap.target_ms - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(QPen(QColor("#f3ba4f"), 1, Qt.DashLine))
            painter.drawLine(guide_x, grid_top, guide_x, self.grid_rect.bottom())
            kind = {
                "marker": tr("时间轴标记"),
                "clip": tr("片段边界"),
                "grid": tr("网格"),
            }.get(snap.kind, "")
            guide_label = f"{kind} · {snap.label}" if snap.label else kind
            if guide_label:
                label_w = min(180.0, painter.fontMetrics().horizontalAdvance(guide_label) + 14.0)
                label_rect = QRectF(
                    max(grid_left + 3.0, min(guide_x + 4.0, grid_left + grid_w - label_w - 3.0)),
                    grid_top + 3.0,
                    label_w,
                    20.0,
                )
                painter.fillRect(label_rect, QColor(42, 35, 21, 238))
                painter.setPen(QColor("#f3d38b"))
                painter.drawText(label_rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter, guide_label)
        painter.restore()

    def _time_at_x(self, x: float) -> float:
        rel = max(
            0.0,
            min(
                1.0,
                (float(x) - self.grid_rect.left())
                / max(1.0, self.grid_rect.width()),
            ),
        )
        return self.view_start_ms + rel * self._visible_duration_ms()

    def _track_at_position(self, position) -> TrackState | None:
        for _rect, action, item in reversed(self._hit_region_index.at(position)):
            if action == "lane" and isinstance(item, TrackState):
                return item
        return None

    def _clip_action_at(
        self, position, regions: tuple[HitRegion, ...] | None = None,
    ) -> tuple[TrackState, str, str] | None:
        """Resolve one Clip gesture, with visible handles above the body."""

        return clip_action_at(
            self._hit_region_index.at(position) if regions is None else regions,
            position,
            arrangement_tool=self.arrangement_tool,
            selected_clip_keys=self._selected_clip_keys,
        )

    def _restore_arrangement_cursor(self, position, regions: tuple[HitRegion, ...] | None = None) -> bool:
        """Restore the stable hover cursor after a completed gesture."""

        layout_handle = self._layout_handle_at(position)
        if layout_handle:
            self.setCursor(
                Qt.SizeHorCursor
                if layout_handle == "header"
                else Qt.SizeVerCursor
            )
            return True
        clip_action = self._clip_action_at(position, regions)
        if self.arrangement_tool == "razor" and clip_action is not None:
            self.setCursor(Qt.CrossCursor)
            return True
        if self.arrangement_tool == "marquee" and self.grid_rect.contains(position):
            self.setCursor(Qt.CrossCursor)
            return True
        if clip_action is not None:
            if clip_action[2] in {"clip_start", "clip_end"}:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
            return True
        self.unsetCursor()
        return False

    def _marquee_rect(self) -> QRectF:
        return marquee_rect(
            self._marquee_press_pos,
            self._marquee_current_pos,
            self.grid_rect,
        )

    def _clip_keys_intersecting(self, rect: QRectF) -> set[tuple[int, str]]:
        return self._hit_region_index.clip_keys_intersecting(rect)

    def _paint_marquee_selection(self, painter: QPainter, damage: QRegion) -> None:
        if not self._marquee_active:
            return
        preview = self._marquee_preview_clip_keys
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tint = QColor(hig.SELECTION_INDICATOR)
        tint.setAlpha(25)
        painter.setBrush(tint)
        painter.setPen(QPen(QColor(hig.SELECTION_BORDER), 1))
        for rect in self._hit_region_index.body_rectangles(preview):
            if not damage.intersects(rect.toAlignedRect()):
                continue
            # Keep the Clip's own identity or validation border visible.
            inset = min(1.5, rect.width() / 4, rect.height() / 4)
            painter.drawRect(rect.adjusted(inset, inset, -inset, -inset))
        marquee = self._marquee_rect()
        if not marquee.isEmpty():
            painter.setPen(QPen(QColor(hig.SELECTION_INDICATOR), 1.25))
            painter.drawRect(marquee)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if self._timeline_row_count() <= 0:
            if self._static_timeline_hit_regions:
                self.hit_regions = self._static_timeline_hit_regions = []
                self._hit_region_index = TimelineHitIndex()
                self._static_timeline_cache_key = None
            self._paint_canvas_background(painter)
            painter.setPen(QColor("#8d8780"))
            painter.drawText(
                area,
                Qt.AlignCenter,
                tr("导入 MIDI 后显示轨道与音符时间轴"),
            )
            return

        visible_start = self.view_start_ms
        visible_duration = self._visible_duration_ms()
        visible_end = visible_start + visible_duration
        grid_w = self._timeline_grid_width(area, header_w)
        if grid_w <= 0:
            self._paint_canvas_background(painter)
            return
        grid_h = max(80, area.bottom() - (area.top() + ruler_h))
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        cache_key = self._static_timeline_key(
            grid_h=grid_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
        )
        if (
            cache_key != self._static_timeline_cache_key
            or self._static_timeline_cache.isNull()
        ):
            self._render_static_timeline(
                area=area,
                header_w=header_w,
                ruler_h=ruler_h,
                lane_h=lane_h,
                grid_w=grid_w,
                grid_h=grid_h,
                visible_start=visible_start,
                visible_duration=visible_duration,
                visible_end=visible_end,
            )
            self._static_timeline_cache_key = cache_key
        painter.drawPixmap(0, 0, self._static_timeline_cache)
        self.hit_regions = self._static_timeline_hit_regions
        if not self.property("composerWorkbench") and not any(track.notes for track in self.tracks):
            paint_empty_score_guidance(painter, self.grid_rect, tr)
        self.velocity_curve_overlay.begin_frame()
        damage = _event.region()
        self._paint_dynamic_track_overlays(
            painter,
            left=left,
            grid_left=grid_left,
            grid_top=grid_top,
            header_w=header_w,
            grid_w=grid_w,
            grid_h=grid_h,
            lane_h=lane_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
            visible_end=visible_end,
            damage=damage,
        )
        self._paint_layout_handles(
            painter, area, header_w, ruler_h, lane_h
        )
        self._paint_track_control_hover(painter, grid_top, grid_h)
        self._paint_clip_drag_preview(
            painter,
            grid_left=grid_left,
            grid_top=grid_top,
            grid_w=grid_w,
            lane_h=lane_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
        )
        self._paint_marquee_selection(painter, damage)
        self._paint_playhead(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end, grid_h
        )
        self._paint_time_range(
            painter,
            top,
            grid_left,
            grid_top,
            grid_w,
            grid_h,
            visible_start,
            visible_duration,
            visible_end,
        )
        self._marker_layer.paint(
            painter,
            damage,
            ruler_top=top,
            grid=QRectF(grid_left, grid_top, grid_w, grid_h),
            visible_start=visible_start,
            visible_duration=visible_duration,
            markers=self.timeline_markers,
            marker_times=self._timeline_marker_times,
        )
        if self.buffer_visible:
            buffer_y = grid_top - 3
            painter.fillRect(QRectF(grid_left, buffer_y, grid_w, 3), QColor("#30383a"))
            if self.buffer_progress > 0:
                painter.fillRect(
                    QRectF(grid_left, buffer_y, grid_w * self.buffer_progress, 3),
                    QColor("#55b8ad"),
                )

    def _marker_near_x(self, x: float) -> dict[str, object] | None:
        if self.grid_rect.width() <= 0:
            return None
        tolerance = self._visible_duration_ms() * 8.0 / self.grid_rect.width()
        target = self._time_at_x(x)
        position = bisect_left(self._timeline_marker_times, target)
        candidates = (
            self.timeline_markers[index]
            for index in (position - 1, position)
            if 0 <= index < len(self.timeline_markers)
        )
        nearest = min(
            candidates,
            key=lambda marker: abs(float(marker["time_ms"]) - target),
            default=None,
        )
        if nearest is None or abs(float(nearest["time_ms"]) - target) > tolerance:
            return None
        return nearest

    def _show_marker_menu(self, global_pos, local_x: float) -> None:
        menu = QMenu(self)
        marker = self._marker_near_x(local_x)
        if marker is None:
            add_action = menu.addAction(tr("添加时间轴标记…"))
            selected = menu.exec(global_pos)
            menu.deleteLater()
            if selected is add_action:
                self.marker_edit_requested.emit({"action": "add", "time_ms": self._time_at_x(local_x)})
            return
        rename_action = menu.addAction(tr("重命名时间轴标记…"))
        menu.addSeparator()
        delete_action = menu.addAction(tr("删除时间轴标记"))
        selected = menu.exec(global_pos)
        menu.deleteLater()
        if selected is rename_action:
            self.marker_edit_requested.emit({"action": "rename", **marker})
        elif selected is delete_action:
            self.marker_edit_requested.emit({"action": "delete", **marker})

    def _build_clip_context_menu(
        self,
        track: TrackState | None = None,
        clip_id: str = "",
    ) -> tuple[QMenu, dict[str, QAction]]:
        menu = QMenu(self)
        actions = {"open": menu.addAction(tr("打开音符编辑器"))}
        actions["open"].setShortcut(QKeySequence("Enter"))
        menu.addSeparator()
        actions["copy"] = menu.addAction(tr("复制片段"))
        actions["paste"] = menu.addAction(tr("在播放头粘贴片段"))
        actions["duplicate"] = menu.addAction(tr("复制音块"))
        actions["copy"].setShortcut(QKeySequence.Copy)
        actions["paste"].setShortcut(QKeySequence.Paste)
        actions["paste"].setVisible(self.clip_paste_available)
        actions["duplicate"].setShortcut(QKeySequence("Ctrl+D"))

        menu.addSeparator()
        transform = menu.addMenu(tr("片段编辑"))
        actions["split"] = transform.addAction(tr("在播放头切分"))
        actions["repeat"] = transform.addAction(tr("重复音块…"))
        actions["crop"] = transform.addAction(tr("收紧右边界到最后音符"))
        actions["consolidate"] = transform.addAction(tr("合并所选音块"))
        actions["split"].setShortcut(QKeySequence("Ctrl+E"))
        actions["repeat"].setShortcut(QKeySequence("Ctrl+L"))
        actions["crop"].setShortcut(QKeySequence("Ctrl+Shift+J"))
        actions["consolidate"].setShortcut(QKeySequence("Ctrl+J"))
        if track is not None and clip_id:
            clip = clip_by_id(track, clip_id)
            actions["split"].setEnabled(
                clip.start_ms + MIN_CLIP_DURATION_MS
                <= self.playhead_ms
                <= clip.end_ms - MIN_CLIP_DURATION_MS
            )
        selected_items = self.selected_clip_items()
        actions["consolidate"].setVisible(
            len(selected_items) >= 2
            and len({int(item.track_id) for item, _value in selected_items}) == 1
        )

        properties = menu.addMenu(tr("属性"))
        actions["rename"] = properties.addAction(tr("重命名音块…"))
        actions["rename"].setShortcut(QKeySequence("F2"))
        actions["color"] = properties.addAction(tr("音块颜色…"))
        actions["velocity_base"] = properties.addAction(tr("Clip 力度基数…"))
        menu.addSeparator()
        actions["delete"] = menu.addAction(tr("删除片段"))
        actions["delete"].setShortcut(QKeySequence.Delete)
        return menu, actions

    def show_shortcut_help(self) -> None:
        from .editor_shortcut_hud import EditorShortcutHelpDialog

        dialog = EditorShortcutHelpDialog(self, timeline=True)
        exec_floating_panel(dialog)
        dialog.deleteLater()

    def _begin_layout_drag(self, position: QPointF) -> bool:
        handle = self._layout_handle_at(position)
        if not handle:
            return False
        self._layout_drag_mode = handle
        self._layout_drag_origin = QPointF(position)
        self._layout_drag_initial = {
            "header": self._header_width,
            "lane": self._lane_height_px,
            "reference": self._reference_lane_height_px,
        }[handle]
        self.setCursor(
            Qt.SizeHorCursor if handle == "header" else Qt.SizeVerCursor
        )
        return True

    def _delete_marker_at(self, position: QPointF) -> bool:
        marker = next((
            marker
            for rect, marker in reversed(self._marker_layer.delete_regions)
            if rect.contains(position)
        ), None)
        if marker is None:
            return False
        self.marker_edit_requested.emit({"action": "delete", **marker})
        return True

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self.setFocus(Qt.MouseFocusReason)
        if event.button() == Qt.LeftButton and self._begin_layout_drag(pos):
            event.accept()
            return
        if self.velocity_curve_overlay.mouse_press(pos, event.button()):
            return
        if event.button() == Qt.LeftButton and self._delete_marker_at(pos):
            return
        if event.button() == Qt.RightButton:
            area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
            ruler_rect = QRectF(area.left() + header_w, area.top(), self._timeline_grid_width(area, header_w), ruler_h)
            if ruler_rect.contains(pos):
                self._show_marker_menu(event.globalPosition().toPoint(), pos.x())
                return
            regions = self._hit_region_index.at(pos)
            for _rect, action, track in reversed(regions):
                if isinstance(track, TrackState):
                    if action.startswith("group_"):
                        self._select_arrangement_group(track)
                        self._show_arrangement_group_menu(track, event.globalPosition().toPoint())
                        return
                    action_kind, _separator, clip_id = action.partition("|")
                    if action_kind in {"clip_body", "clip_start", "clip_end"}:
                        key = (int(track.track_id), str(clip_id))
                        self._set_clip_selection(
                            (
                                set(self._selected_clip_keys)
                                if key in self._selected_clip_keys
                                else {key}
                            ),
                            primary_key=key,
                            emit_track=True,
                        )
                        menu, actions = self._build_clip_context_menu(
                            track, clip_id
                        )
                        selected = menu.exec(event.globalPosition().toPoint())
                        menu.deleteLater()
                        if selected is actions["open"]:
                            self.clip_note_editor_requested.emit(track, clip_id)
                        elif selected is actions["velocity_base"]:
                            self.clip_velocity_base_requested.emit(self.selected_clip_items())
                        elif selected is actions["duplicate"]:
                            self.clip_duplicate_requested.emit(track, clip_id)
                        elif selected is actions["repeat"]:
                            self.clip_repeat_requested.emit(track, clip_id)
                        elif selected is actions["split"]:
                            self.clip_split_requested.emit(
                                TimelineClipSplitRequest(
                                    track, clip_id, self.playhead_ms
                                )
                            )
                        elif selected is actions["copy"]:
                            self.clip_copy_requested.emit(track, clip_id)
                        elif selected is actions["paste"]:
                            self.clip_paste_requested.emit(track, self.playhead_ms)
                        elif selected is actions["crop"]:
                            self.clip_crop_requested.emit(track, clip_id)
                        elif selected is actions["consolidate"]:
                            self.clips_consolidate_requested.emit(
                                self.selected_clip_items()
                            )
                        elif selected is actions["rename"]:
                            self.clip_rename_requested.emit(track, clip_id)
                        elif selected is actions["color"]:
                            self.clip_color_requested.emit(track, clip_id)
                        elif selected is actions["delete"]:
                            items = self.selected_clip_items()
                            if len(items) > 1:
                                self.clips_delete_requested.emit(items)
                            else:
                                self.clip_delete_requested.emit(track, clip_id)
                        return
                    self._select_track(track, emit=True)
                    self._show_instrument_menu(
                        track,
                        event.globalPosition().toPoint(),
                        create_clip_at_ms=(
                            self._time_at_x(pos.x())
                            if pos.x() >= self.grid_rect.left()
                            else None
                        ),
                    )
                    return
            if any(
                track is self.reference_audio for _rect, _action, track in regions
            ):
                self._show_reference_audio_menu(event.globalPosition().toPoint())
                return
            self.show_create_track_menu(event.globalPosition().toPoint())
            return
        if event.button() == Qt.LeftButton and self.reference_audio is not None:
            for _rect, action, target in reversed(self._hit_region_index.at(pos)):
                if target is self.reference_audio:
                    if action == "audio_waveform":
                        self.set_playhead(self._time_at_x(pos.x()))
                        self.seek_requested.emit(self.playhead_ms)
                    event.accept()
                    return
        clip_action = self._clip_action_at(pos)
        clip_hit = (
            (clip_action[0], clip_action[1])
            if clip_action is not None else None
        )
        clip_hit_key = (
            (int(clip_hit[0].track_id), str(clip_hit[1]))
            if clip_hit is not None
            else None
        )
        if (
            event.button() == Qt.LeftButton
            and self.arrangement_tool == "select"
            and clip_hit is not None
            and clip_action is not None
            and clip_action[2] == "clip_body"
            and clip_hit_key in self._selected_clip_keys
            and not event.modifiers()
        ):
            track, clip_id = clip_hit
            try:
                anchor = clip_by_id(track, clip_id)
                selected_items = self.selected_clip_items()
                origins = {
                    (int(item.track_id), str(selected_id)): (
                        float(selected_clip.start_ms),
                        float(selected_clip.end_ms),
                    )
                    for item, selected_id in selected_items
                    for selected_clip in (clip_by_id(item, selected_id),)
                }
            except ValueError:
                return
            self._clip_group_drag_keys = tuple(origins)
            self._clip_group_drag_origins = origins
            self._clip_group_drag_track_offset = 0
            self._clip_drag_source = track
            self._clip_drag_target = track
            self._clip_drag_id = str(clip_id)
            self._clip_drag_mode = "move"
            self._clip_drag_press_ms = self._time_at_x(pos.x())
            self._clip_drag_press_pos = QPointF(pos)
            self._clip_drag_start_ms = float(anchor.start_ms)
            self._clip_drag_end_ms = float(anchor.end_ms)
            self._clip_drag_origin_press_ms = self._clip_drag_press_ms
            self._clip_drag_origin_start_ms = float(anchor.start_ms)
            self._clip_drag_origin_end_ms = float(anchor.end_ms)
            self._clip_snap_targets = self._build_clip_snap_targets(
                track,
                str(clip_id),
                ignored_keys=frozenset(origins),
            )
            self._clip_snap_result = ArrangementSnapResult(anchor.start_ms)
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and self.arrangement_tool == "marquee"
            and self.grid_rect.contains(pos)
            and self._track_at_position(pos) is not None
        ):
            self._marquee_press_pos = QPointF(pos)
            self._marquee_current_pos = QPointF(pos)
            self._marquee_active = False
            self._marquee_modifiers = event.modifiers()
            self._marquee_base_clip_keys = (
                set(self._selected_clip_keys)
                if event.modifiers()
                & (Qt.ControlModifier | Qt.ShiftModifier)
                else set()
            )
            self._marquee_preview_clip_keys = set(
                self._marquee_base_clip_keys
            )
            self._marquee_origin_clip = clip_hit
            event.accept()
            return
        if clip_hit is None and press_empty_track_space(self, event):
            return
        for rect, action, track in reversed(self._hit_region_index.at(pos)):
            if rect.contains(pos):
                if not isinstance(track, TrackState):
                    continue
                if action in {"group_select", "group_summary"}:
                    self._select_arrangement_group(track)
                    return
                if action == "group_fold":
                    group_id = str(track.arrangement_group_id or "")
                    self._set_group_collapsed(
                        group_id,
                        group_id not in self._collapsed_arrangement_groups,
                    )
                    return
                if action in {"group_mute", "group_solo"}:
                    self._select_arrangement_group(track)
                    self.group_control_requested.emit(
                        str(track.arrangement_group_id),
                        action.removeprefix("group_"),
                    )
                    return
                action_kind, _separator, clip_id = action.partition("|")
                if action_kind in {"clip_body", "clip_start", "clip_end"}:
                    resolved = self._clip_action_at(pos)
                    if resolved is None:
                        return
                    track, clip_id, action_kind = resolved
                    try:
                        clip = clip_by_id(track, clip_id)
                    except ValueError:
                        return
                    if self.arrangement_tool == "razor":
                        self._select_pointer_clip(
                            track, clip.clip_id, Qt.NoModifier
                        )
                        self.clip_split_requested.emit(TimelineClipSplitRequest(
                            track, clip.clip_id, self._time_at_x(pos.x())
                        ))
                        return
                    self._select_pointer_clip(
                        track, clip.clip_id, event.modifiers()
                    )
                    if event.modifiers() & (
                        Qt.ControlModifier | Qt.ShiftModifier
                    ):
                        return
                    self._clip_drag_source = track
                    self._clip_drag_target = track
                    self._clip_drag_id = clip.clip_id
                    self._clip_drag_mode = {
                        "clip_body": "move",
                        "clip_start": "resize_start",
                        "clip_end": "resize_end",
                    }[action_kind]
                    self._clip_drag_press_ms = self._time_at_x(pos.x())
                    self._clip_drag_press_pos = QPointF(pos)
                    self._clip_drag_start_ms = clip.start_ms
                    self._clip_drag_end_ms = clip.end_ms
                    self._clip_drag_origin_press_ms = self._clip_drag_press_ms
                    self._clip_drag_origin_start_ms = clip.start_ms
                    self._clip_drag_origin_end_ms = clip.end_ms
                    siblings = tuple(
                        value for value in track_clips(track)
                        if value.clip_id != clip.clip_id
                    )
                    next_start = min(
                        (
                            value.start_ms for value in siblings
                            if value.start_ms >= clip.end_ms - 1e-6
                        ),
                        default=math.inf,
                    )
                    self._clip_drag_max_end_ms = next_start
                    self._clip_snap_targets = self._build_clip_snap_targets(
                        track, clip.clip_id
                    )
                    self._clip_snap_result = ArrangementSnapResult(
                        clip.start_ms
                    )
                    self.setCursor(
                        Qt.ClosedHandCursor
                        if action_kind == "clip_body"
                        else Qt.SizeHorCursor
                    )
                    return
                if action == "lane":
                    self._select_pointer_track(track, event.modifiers())
                    continue
                self._select_pointer_track(track, event.modifiers())
                if action == "track_volume":
                    self._volume_drag_track = track
                    self._volume_drag_rect = QRectF(rect)
                    self._volume_drag_initial = int(track.bdo_track_volume)
                    self._set_track_volume_from_position(track, rect, pos.x())
                elif action == "mute":
                    track.muted = not track.muted
                    self._update_accessible_track_state()
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "solo":
                    track.solo = not track.solo
                    self._update_accessible_track_state()
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "fx":
                    self.effects_requested.emit(track)
                self.update()
                return
        area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        ruler_rect = QRectF(
            area.left() + header_w,
            area.top(),
            self._timeline_grid_width(area, header_w),
            ruler_h,
        )
        if event.button() == Qt.LeftButton and ruler_rect.contains(pos):
            rel = max(
                0.0,
                min(
                    1.0,
                    (pos.x() - ruler_rect.left())
                    / max(1.0, ruler_rect.width()),
                ),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            selected = self.time_range
            handle_tolerance = self._visible_duration_ms() * 7.0 / max(
                1.0,
                ruler_rect.width(),
            )
            if selected and abs(target - selected[0]) <= handle_tolerance:
                self._range_drag_mode = "start"
                self._range_drag_anchor_ms = selected[1]
            elif selected and abs(target - selected[1]) <= handle_tolerance:
                self._range_drag_mode = "end"
                self._range_drag_anchor_ms = selected[0]
            else:
                self._range_drag_mode = "new"
                self._range_drag_anchor_ms = target
                self.set_time_range(target, target)
            self._range_drag_moved = False
            self.set_playhead(target)
            return
        if self.grid_rect.contains(pos):
            seek_empty_grid(
                self, pos.x(), event.modifiers(),
                clear_selection=event.button() == Qt.LeftButton,
            )
            return
        if event.button() == Qt.LeftButton:
            self.dragging_timeline = True
            self.last_drag_x = pos.x()
            return
        super().mousePressEvent(event)

    def _select_arrangement_group(self, track: TrackState) -> None:
        group_id = str(track.arrangement_group_id or "")
        if group_id not in self._arrangement_groups:
            return
        self._selected_arrangement_group_id = group_id
        self._select_track(track, emit=True)

    def _show_arrangement_group_menu(
        self, track: TrackState, global_pos
    ) -> None:
        group_id = str(track.arrangement_group_id or "")
        group = self._arrangement_groups.get(group_id)
        if group is None:
            return
        menu = QMenu(self)
        title = menu.addAction(trf(
            "乐器组 · {instrument} · {count} 轨",
            instrument=_ui_bdo_instrument_name(group.instrument_id),
            count=group.count,
        ))
        title.setEnabled(False)
        fold_action = menu.addAction(
            tr("展开乐器组")
            if group_id in self._collapsed_arrangement_groups
            else tr("折叠乐器组")
        )
        menu.addSeparator()
        mute_action = menu.addAction(
            tr("取消整组静音")
            if all(item.muted for item in group.members)
            else tr("整组静音")
        )
        solo_action = menu.addAction(
            tr("取消整组独奏")
            if all(item.solo for item in group.members)
            else tr("整组独奏")
        )
        menu.addSeparator()
        fold_all_action = menu.addAction(tr("折叠所有乐器组"))
        expand_all_action = menu.addAction(tr("展开所有乐器组"))
        several_groups = len(self._arrangement_groups) > 1
        fold_all_action.setVisible(several_groups and self.can_set_all_groups_collapsed(True))
        expand_all_action.setVisible(several_groups and self.can_set_all_groups_collapsed(False))
        selected = menu.exec(global_pos)
        menu.deleteLater()
        if selected is mute_action:
            self.group_control_requested.emit(group_id, "mute")
        elif selected is solo_action:
            self.group_control_requested.emit(group_id, "solo")
        elif selected is fold_action:
            self._set_group_collapsed(
                group_id,
                group_id not in self._collapsed_arrangement_groups,
            )
        elif selected is fold_all_action:
            self.set_all_groups_collapsed(True)
        elif selected is expand_all_action:
            self.set_all_groups_collapsed(False)

    def _show_instrument_menu(
        self,
        track: TrackState,
        global_pos,
        *,
        create_clip_at_ms: float | None = None,
    ) -> None:
        menu, actions = self._build_track_context_menu(
            track, create_clip_at_ms=create_clip_at_ms
        )
        selected = menu.exec(global_pos)
        menu.deleteLater()
        if selected is None:
            return
        if selected is actions.get("create_clip"):
            self.clip_create_requested.emit(
                track, max(0.0, float(create_clip_at_ms))
            )
            return
        if selected is actions.get("paste"):
            self.clip_paste_requested.emit(track, self.playhead_ms)
            return
        if selected is actions["edit_notes"]:
            self.note_editor_requested.emit(track)
            return
        if selected is actions["rename_track"]:
            self.rename_track_requested.emit(track)
            return
        if selected is actions["duplicate_track"]:
            self.duplicate_track_requested.emit(track)
            return
        if selected is actions["color_track"]:
            self.color_track_requested.emit(track)
            return
        if selected is actions["pitch"]:
            self.pitch_requested.emit(track)
            return
        if selected is actions["effects"]:
            self.effects_requested.emit(track)
            return
        if selected in {actions["move_up"], actions["move_down"]}:
            return
        if selected is actions["optimize"]:
            self.midi_tools_requested.emit(track)
            return
        if selected is actions["merge"]:
            self.merge_track_requested.emit(track)
            return
        if selected is actions["unify_mixer"]:
            self.mixer_unify_requested.emit(track)
            return
        if selected is actions["delete"]:
            self.delete_track_requested.emit(track)
            return
        if selected is actions["clear_solo"]:
            self.clear_solo_requested.emit()
            return
        if selected is actions["unmute_all"]:
            self.unmute_all_requested.emit()
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == track.bdo_instrument_id:
            return
        previous_instrument_id = int(track.bdo_instrument_id)
        track.bdo_instrument_id = int(inst_id)
        self.instrument_changed.emit(track, previous_instrument_id)
        self.update()

    def _build_track_context_menu(
        self,
        track: TrackState,
        *,
        create_clip_at_ms: float | None = None,
    ) -> tuple[QMenu, dict[str, QAction]]:
        menu = QMenu(self)
        actions: dict[str, QAction] = {}
        if create_clip_at_ms is not None:
            actions["create_clip"] = menu.addAction(tr("在此处创建片段"))
            actions["create_clip"].setData(float(create_clip_at_ms))
            if self.clip_paste_available:
                actions["paste"] = menu.addAction(tr("在播放头粘贴片段"))
                actions["paste"].setShortcut(QKeySequence.Paste)
            menu.addSeparator()
        actions["edit_notes"] = menu.addAction(tr("编辑音符…"))
        actions["edit_notes"].setShortcut(QKeySequence("Enter"))
        instrument_menu = menu.addMenu(tr("更换游戏乐器"))
        menu._instrument_menu = instrument_menu
        add_instrument_submenus(
            instrument_menu,
            track.bdo_instrument_id,
            _ui_bdo_instrument_names(),
        )
        actions["optimize"] = menu.addAction(tr("优化此轨道"))

        menu.addSeparator()
        sound_menu = menu.addMenu(tr("音高与混音"))
        menu._sound_menu = sound_menu
        actions["effects"] = sound_menu.addAction(tr("轨道 FX"))
        actions["effects"].setShortcut(QKeySequence("F"))
        actions["pitch"] = sound_menu.addAction(tr("轨道移调…"))
        actions["pitch"].setVisible(
            not track_uses_percussion_pitch_semantics(track)
        )
        instrument_id = serialized_game_instrument_id(track)
        has_same_instrument = any(
            item is not track and serialized_game_instrument_id(item) == instrument_id
            for item in self.tracks
        )
        actions["unify_mixer"] = sound_menu.addAction(tr("以此轨统一同乐器音量和 FX"))
        actions["unify_mixer"].setVisible(has_same_instrument)

        track_menu = menu.addMenu(tr("轨道管理"))
        menu._track_menu = track_menu
        actions["rename_track"] = track_menu.addAction(tr("重命名轨道…"))
        actions["rename_track"].setShortcut(QKeySequence("F2"))
        actions["color_track"] = track_menu.addAction(tr("轨道颜色…"))
        track_menu.addSeparator()
        actions["duplicate_track"] = track_menu.addAction(tr("复制轨道"))
        actions["duplicate_track"].setShortcut(QKeySequence("Ctrl+Shift+D"))
        actions["merge"] = track_menu.addAction(tr("合并同乐器轨道…"))
        actions["merge"].setVisible(has_same_instrument)
        actions["move_up"], actions["move_down"] = self._add_track_move_actions(track_menu, track)

        monitor_menu = menu.addMenu(tr("监听状态"))
        menu._monitor_menu = monitor_menu
        any_solo = any(item.solo for item in self.tracks)
        any_muted = any(item.muted for item in self.tracks)
        actions["clear_solo"] = monitor_menu.addAction(tr("清除 Solo"))
        actions["unmute_all"] = monitor_menu.addAction(tr("取消静音"))
        actions["clear_solo"].setVisible(any_solo)
        actions["unmute_all"].setVisible(any_muted)
        monitor_menu.menuAction().setVisible(any_solo or any_muted)
        menu.addSeparator()
        actions["delete"] = menu.addAction(tr("删除轨道"))
        return menu, actions

    def _add_track_move_actions(
        self,
        menu: QMenu,
        track: TrackState,
    ) -> tuple[QAction, QAction]:
        move_up_action = menu.addAction(tr("上移轨道"))
        move_down_action = menu.addAction(tr("下移轨道"))
        current = tuple(self.tracks)
        move_up_action.setEnabled(move_group_block(self.tracks, track, -1) != current)
        move_down_action.setEnabled(move_group_block(self.tracks, track, 1) != current)
        move_up_action.setVisible(move_up_action.isEnabled())
        move_down_action.setVisible(move_down_action.isEnabled())
        move_up_action.triggered.connect(
            lambda _checked=False: self.move_track_requested.emit(track, -1)
        )
        move_down_action.triggered.connect(
            lambda _checked=False: self.move_track_requested.emit(track, 1)
        )
        return move_up_action, move_down_action

    def show_create_track_menu(self, global_pos) -> None:
        """Choose a BDO instrument for a new track."""

        menu = QMenu(self)
        title = menu.addAction(tr("选择新轨道的 BDO 乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, -1, _ui_bdo_instrument_names())
        selected = menu.exec(global_pos)
        menu.deleteLater()
        if selected is not None and selected.data() is not None:
            self.create_track_requested.emit(int(selected.data()))

    def _build_reference_audio_menu(self) -> QMenu:
        return build_reference_audio_menu(
            self,
            self.reference_audio,
            self._reference_load_button.text(),
            self._choose_reference_audio,
            self.reference_audio_offset_requested.emit,
        )

    def _show_reference_audio_menu(self, position: QPoint) -> None:
        menu = self._build_reference_audio_menu()
        menu.exec(position)
        menu.deleteLater()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.velocity_curve_overlay.active:
            return
        if event.button() == Qt.LeftButton:
            for rect, marker in reversed(self._marker_layer.label_regions):
                if rect.contains(event.position()):
                    self.marker_edit_requested.emit({"action": "rename", **marker})
                    return
            area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
            ruler_rect = QRectF(area.left() + header_w, area.top(), self._timeline_grid_width(area, header_w), ruler_h)
            if ruler_rect.contains(event.position()):
                self.marker_edit_requested.emit({"action": "add", "time_ms": self._time_at_x(event.position().x())})
                return
            for rect, action, track in reversed(self._hit_region_index.at(event.position())):
                if track is self.reference_audio and rect.contains(event.position()):
                    return
                if (
                    isinstance(track, TrackState)
                    and (
                        action in ("lane", "select", "group_summary")
                        or action.startswith(("clip_body|", "clip_start|", "clip_end|"))
                    )
                    and rect.contains(event.position())
                ):
                    self.setFocus(Qt.MouseFocusReason)
                    if action == "group_summary":
                        group_id = str(track.arrangement_group_id or "")
                        self._select_arrangement_group(track)
                        self._set_group_collapsed(group_id, False)
                        return
                    clip_id = (
                        action.split("|", 1)[1]
                        if action.startswith(("clip_body|", "clip_start|", "clip_end|"))
                        else ""
                    )
                    if clip_id:
                        key = (int(track.track_id), clip_id)
                        self._set_clip_selection({key}, primary_key=key, emit_track=True)
                        self.clip_note_editor_requested.emit(track, clip_id)
                        return
                    self._select_track(track, emit=True)
                    if not track.notes and event.position().x() >= self.grid_rect.left():
                        self.clip_create_requested.emit(
                            track, self._time_at_x(event.position().x())
                        )
                    else:
                        self.note_editor_requested.emit(track)
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._layout_drag_mode:
            delta_x = pos.x() - self._layout_drag_origin.x()
            delta_y = pos.y() - self._layout_drag_origin.y()
            if self._layout_drag_mode == "header":
                self.set_layout_metrics(
                    header_width=round(self._layout_drag_initial + delta_x)
                )
            elif self._layout_drag_mode == "lane":
                self.set_layout_metrics(
                    lane_height=round(self._layout_drag_initial + delta_y)
                )
            else:
                self.set_layout_metrics(
                    reference_lane_height=round(
                        self._layout_drag_initial - delta_y
                    )
                )
            event.accept()
            return
        if self._marquee_press_pos is not None:
            previous_rect = self._marquee_rect()
            previous_keys = self._marquee_preview_clip_keys if self._marquee_active else set()
            self._marquee_current_pos = QPointF(pos)
            if (
                not self._marquee_active
                and (pos - self._marquee_press_pos).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._marquee_active = True
            if self._marquee_active:
                current_rect = self._marquee_rect()
                hits = self._clip_keys_intersecting(current_rect)
                if self._marquee_modifiers & Qt.ControlModifier:
                    self._marquee_preview_clip_keys = (
                        self._marquee_base_clip_keys ^ hits
                    )
                elif self._marquee_modifiers & Qt.ShiftModifier:
                    self._marquee_preview_clip_keys = (
                        self._marquee_base_clip_keys | hits
                    )
                else:
                    self._marquee_preview_clip_keys = hits
                dirty = marquee_damage(previous_rect, current_rect)
                changed = previous_keys ^ self._marquee_preview_clip_keys
                for body in self._hit_region_index.body_rectangles(changed):
                    dirty += QRegion(body.toAlignedRect().adjusted(-2, -2, 2, 2))
                if not dirty.isEmpty():
                    self.update(dirty)
            self.setCursor(Qt.CrossCursor)
            event.accept()
            return
        if self.velocity_curve_overlay.mouse_move(pos):
            return
        if self._volume_drag_track is not None:
            self._set_track_volume_from_position(
                self._volume_drag_track,
                self._volume_drag_rect,
                pos.x(),
            )
            return
        if self._clip_drag_source is not None:
            if not self._clip_drag_active:
                self._clip_drag_active = (
                    (pos - self._clip_drag_press_pos).manhattanLength()
                    >= QApplication.startDragDistance()
                )
            if self._clip_drag_active:
                self._update_clip_drag_geometry(pos, event.modifiers())
                self.update()
            return
        if self._range_drag_anchor_ms is not None:
            area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
            grid_width = max(1.0, self._timeline_grid_width(area, header_w))
            rel = max(
                0.0,
                min(1.0, (pos.x() - (area.left() + header_w)) / grid_width),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            self._range_drag_moved = (
                self._range_drag_moved
                or abs(target - self._range_drag_anchor_ms)
                > self._visible_duration_ms() * 3.0 / grid_width
            )
            self.set_time_range(self._range_drag_anchor_ms, target)
            return
        if self.dragging_timeline:
            dx = pos.x() - self.last_drag_x
            self.last_drag_x = pos.x()
            if self.width() > 0:
                previous_start = self.view_start_ms
                self.view_start_ms -= dx / max(1, self.width()) * self._visible_duration_ms()
                self._clamp_view()
                if self.view_start_ms != previous_start:
                    self._publish_viewport_change()
            return
        hover_track: TrackState | None = None
        hover_on_badge = False
        regions = self._hit_region_index.at(pos)
        previous_control_hover = self._track_control_hover_pos is not None
        track_control = self._set_track_control_hover(pos)
        for _rect, action, item in reversed(regions):
            if (
                action in {"validation_error", "validation_attention"}
                and isinstance(item, TrackState)
            ):
                hover_track = item
                hover_on_badge = True
                break
        if hover_track is None:
            for _rect, action, item in reversed(regions):
                if (
                    action == "lane"
                    and isinstance(item, TrackState)
                ):
                    hover_track = item
                    break
        hover_track_id = (
            int(hover_track.track_id) if hover_track is not None else None
        )
        if hover_track_id != self._validation_hover_track_id or previous_control_hover:
            self._validation_hover_track_id = hover_track_id
            self.setToolTip(
                track_identity.tooltip(
                    hover_track, tr,
                    self._track_validation_tooltip(hover_track),
                )
                if hover_track is not None
                else tr(self.KEYBOARD_SHORTCUT_HINT)
            )
        group_hover = next((
            (item, action) for _rect, action, item in reversed(regions)
            if action.startswith("group_")
            and isinstance(item, TrackState)
        ), None)
        if group_hover is not None:
            group_track, group_action = group_hover
            self.setToolTip(trf(
                (
                    "组摘要 · {instrument} · {count} 轨；双击或 Enter 展开，U 折叠/展开，M/S 控制整组"
                    if group_action == "group_summary"
                    else "乐器组 · {instrument} · {count} 轨；点击组名选择整组，M/S 控制整组"
                ),
                instrument=_ui_bdo_instrument_name(group_track.bdo_instrument_id),
                count=self._arrangement_group_counts.get(
                    group_track.arrangement_group_id, 0
                ),
            ))
        layout_handle = self._layout_handle_at(pos)
        if layout_handle != self._layout_hover_handle:
            self._layout_hover_handle = layout_handle
            self.update()
        if layout_handle:
            self.setToolTip({
                "header": tr("拖动调整轨道头宽度"),
                "lane": tr("拖动调整轨道高度"),
                "reference": tr("拖动调整参考音频高度"),
            }[layout_handle])
        elif track_control is not None:
            self.setToolTip(tr({
                "mute": "轨道静音（M）",
                "solo": "轨道独奏（S）",
                "fx": "轨道效果",
                "group_mute": "整组静音",
                "group_solo": "整组独奏",
            }[track_control[1]]))
        if self._restore_arrangement_cursor(pos, regions):
            pass
        elif hover_on_badge or group_hover is not None or track_control is not None:
            self.setCursor(Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_track_control_hover(None)
        self._validation_hover_track_id = None
        self._layout_hover_handle = ""
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._layout_drag_mode:
            self._layout_drag_mode = ""
            self._layout_drag_origin = QPointF()
            self._layout_drag_initial = 0
            self.layout_preferences_changed.emit()
            self._restore_arrangement_cursor(event.position())
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and self._marquee_press_pos is not None
        ):
            press_pos = QPointF(self._marquee_press_pos)
            origin_clip = self._marquee_origin_clip
            active = self._marquee_active
            preview = set(self._marquee_preview_clip_keys)
            primary_key = (
                (self._selected_clip_track_id, self._selected_clip_id)
                if self._selected_clip_id
                else None
            )
            modifiers = self._marquee_modifiers
            reset_marquee_selection(self)
            self._restore_arrangement_cursor(event.position())
            if active:
                self._set_clip_selection(
                    preview,
                    primary_key=primary_key,
                    emit_track=True,
                )
            elif origin_clip is not None:
                self._select_pointer_clip(
                    origin_clip[0], origin_clip[1], modifiers
                )
            else:
                seek_empty_grid(self, press_pos.x(), modifiers)
            self.update()
            event.accept()
            return
        if self.velocity_curve_overlay.mouse_release(event.button()):
            return
        if self._volume_drag_track is not None:
            track = self._volume_drag_track
            previous_volume = int(self._volume_drag_initial)
            next_volume = int(track.bdo_track_volume)
            changed = (
                next_volume != previous_volume
            )
            self._volume_drag_track = None
            self._volume_drag_rect = QRectF()
            if changed:
                self.game_volume_committed.emit(
                    track,
                    previous_volume,
                    next_volume,
                )
            return
        if self._clip_drag_source is not None:
            # Some platforms deliver the final pointer coordinate only with
            # mouse release, so apply snapping once more before committing.
            distance = (event.position() - self._clip_drag_press_pos).manhattanLength()
            pointer_moved = distance >= QApplication.startDragDistance() or (
                self._clip_drag_active and distance > 0
            )
            if pointer_moved:
                self._update_clip_drag_geometry(
                    event.position(), event.modifiers()
                )
            source = self._clip_drag_source
            target = self._clip_drag_target or source
            request = TimelineClipEditRequest(
                source,
                target,
                self._clip_drag_mode,
                self._clip_drag_start_ms,
                self._clip_drag_end_ms,
                self._clip_drag_id,
            )
            group_selections = (
                self.selected_clip_items()
                if self._clip_group_drag_keys
                else ()
            )
            group_delta = (
                self._clip_drag_start_ms
                - self._clip_drag_origin_start_ms
            )
            group_track_offset = self._clip_group_drag_track_offset
            self._clip_drag_source = None
            self._clip_drag_target = None
            self._clip_drag_mode = ""
            self._clip_drag_active = False
            self._clip_drag_id = ""
            self._clip_group_drag_keys = ()
            self._clip_group_drag_origins.clear()
            self._clip_group_drag_track_offset = 0
            self._clip_drag_max_end_ms = math.inf
            self._clip_drag_press_pos = QPointF()
            self._clip_snap_targets = ArrangementSnapIndex((), ())
            self._clip_snap_result = ArrangementSnapResult(0.0)
            changed = (
                pointer_moved
                and (
                    target is not source
                or not math.isclose(
                    request.new_start_ms,
                    self._clip_drag_origin_start_ms,
                    abs_tol=1e-6,
                )
                or not math.isclose(
                    request.new_end_ms,
                    self._clip_drag_origin_end_ms,
                    abs_tol=1e-6,
                )
                )
            )
            if changed:
                if group_selections:
                    self.clips_move_requested.emit(
                        TimelineClipsMoveRequest(
                            group_selections,
                            group_delta,
                            group_track_offset,
                            (
                                self._selected_clip_track_id,
                                self._selected_clip_id,
                            ) if self._selected_clip_id else None,
                        )
                    )
                else:
                    self.clip_edit_requested.emit(request)
            if not pointer_moved:
                self._restore_arrangement_cursor(event.position())
            elif request.mode in {"resize_start", "resize_end"}:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
            self.update()
            return
        if self._range_drag_anchor_ms is not None:
            if not self._range_drag_moved:
                target = self._range_drag_anchor_ms
                self.set_time_range(None, None)
                self.set_playhead(target)
                self.seek_requested.emit(self.playhead_ms)
            else:
                self.time_range_changed.emit(self.time_range)
            self._range_drag_anchor_ms = None
            self._range_drag_mode = ""
            self._range_drag_moved = False
            return
        self.dragging_timeline = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta()
        delta = angle.x() or angle.y()
        if not delta:
            super().wheelEvent(event)
            return
        old_view = self.zoom_factor, self.view_start_ms
        if event.modifiers() & Qt.ControlModifier:
            step = 1.12 if delta > 0 else 1 / 1.12
            center = self.view_start_ms + self._visible_duration_ms() / 2
            self.zoom_factor = max(0.25, min(32.0, self.zoom_factor * step))
            self.view_start_ms = center - self._visible_duration_ms() / 2
        elif angle.x() or (event.modifiers() & Qt.ShiftModifier) or not self.track_scroll.isVisible():
            self.view_start_ms += (delta / 120.0) * self._visible_duration_ms() * 0.12
        else:
            self.track_scroll.setValue(self.track_scroll.value() - int(delta / 120.0 * self._lane_height()))
            event.accept()
            return
        self._clamp_view()
        if old_view != (self.zoom_factor, self.view_start_ms):
            self._publish_viewport_change()
        event.accept()

    def _navigation_boundaries(self) -> tuple[float, ...]:
        return normalized_boundaries(
            (
                0.0,
                self._timeline_end_ms(),
                *(float(marker["time_ms"]) for marker in self.timeline_markers),
                *(
                    value
                    for track in self.tracks
                    for clip in track_clips(track)
                    for value in (clip.start_ms, clip.end_ms)
                ),
            )
        )

    def _move_playhead_by(self, delta_ms: float, *, extend: bool) -> None:
        previous = self.playhead_ms
        target = max(
            0.0,
            min(self._timeline_end_ms(), previous + float(delta_ms)),
        )
        if extend:
            selected = self.time_range
            anchor = previous if selected is None else selected[0]
            self.set_time_range(anchor, target, notify=True)
        self.set_playhead(target, follow=True)
        self.seek_requested.emit(self.playhead_ms)

    def _jump_playhead_boundary(self, direction: int, *, extend: bool) -> None:
        previous = self.playhead_ms
        target = neighboring_boundary(
            self._navigation_boundaries(), previous, direction
        )
        if extend:
            selected = self.time_range
            anchor = previous if selected is None else selected[0]
            self.set_time_range(anchor, target, notify=True)
        self.set_playhead(target, follow=True)
        self.seek_requested.emit(self.playhead_ms)

    def _nudge_selected_clips(self, delta_ms: float) -> None:
        selections = self.selected_clip_items()
        if not selections:
            return
        primary = (
            (self._selected_clip_track_id, self._selected_clip_id)
            if self._selected_clip_track_id is not None
            and self._selected_clip_id
            else None
        )
        self.clips_move_requested.emit(TimelineClipsMoveRequest(
            selections,
            float(delta_ms),
            0,
            primary,
        ))

    def _focus_time_bounds(self) -> tuple[float, float] | None:
        selected_range = self.time_range
        if selected_range is not None and selected_range[1] > selected_range[0]:
            return selected_range
        clips = tuple(
            clip_by_id(track, clip_id)
            for track, clip_id in self.selected_clip_items()
        )
        if not clips and self.selected_track is not None:
            clips = track_clips(self.selected_track)
        if not clips:
            return None
        return (
            min(float(clip.start_ms) for clip in clips),
            max(float(clip.end_ms) for clip in clips),
        )

    def _zoom_to_focus(self) -> None:
        bounds = self._focus_time_bounds()
        if bounds is None:
            return
        viewport = viewport_for_range(
            self._timeline_end_ms(), bounds[0], bounds[1]
        )
        self._viewport_history.append((self.zoom_factor, self.view_start_ms))
        del self._viewport_history[:-8]
        self.zoom_factor = viewport.zoom_factor
        self.view_start_ms = viewport.start_ms
        self._publish_viewport_change()

    def _restore_viewport(self) -> None:
        if not self._viewport_history:
            return
        self.zoom_factor, self.view_start_ms = self._viewport_history.pop()
        self._clamp_view()
        self._publish_viewport_change()

    def keyPressEvent(self, event) -> None:
        if self.velocity_curve_overlay.key_press(event):
            return
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key_Escape and modifiers == Qt.NoModifier:
            if self._marquee_press_pos is not None:
                reset_marquee_selection(self)
                self.unsetCursor()
                self.update()
            self._clear_arrangement_selection()
            event.accept()
            return
        if key == Qt.Key_F1 and modifiers == Qt.NoModifier:
            self.show_shortcut_help()
            event.accept()
            return
        if key == Qt.Key_Z and modifiers == Qt.NoModifier:
            self._zoom_to_focus()
            event.accept()
            return
        if key == Qt.Key_X and modifiers == Qt.NoModifier:
            self._restore_viewport()
            event.accept()
            return
        if key == Qt.Key_W and modifiers == Qt.NoModifier:
            self.fit_width_requested.emit()
            event.accept()
            return
        if key == Qt.Key_H and modifiers == Qt.NoModifier:
            self.fit_track_rows()
            event.accept()
            return
        if key == Qt.Key_U and modifiers == Qt.NoModifier:
            group_id = (
                str(self.selected_track.arrangement_group_id or "")
                if self.selected_track is not None else ""
            )
            if group_id in self._arrangement_groups:
                self._set_group_collapsed(
                    group_id,
                    group_id not in self._collapsed_arrangement_groups,
                )
            event.accept()
            return
        if (
            key in (Qt.Key_Left, Qt.Key_Right)
            and modifiers & Qt.ControlModifier
            and not modifiers & Qt.AltModifier
        ):
            self._jump_playhead_boundary(
                -1 if key == Qt.Key_Left else 1,
                extend=bool(modifiers & Qt.ShiftModifier),
            )
            event.accept()
            return
        navigation_keys = {
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Home,
            Qt.Key_End,
        }
        if key in navigation_keys and not (
            modifiers & (Qt.ControlModifier | Qt.AltModifier)
        ):
            visible_tracks = tuple(
                track for _row, track in self._visible_track_rows()
            )
            if not visible_tracks:
                event.accept()
                return
            current = next(
                (
                    index
                    for index, track in enumerate(visible_tracks)
                    if track is self.selected_track
                ),
                None,
            )
            if key == Qt.Key_Home:
                target_index = 0
            elif key == Qt.Key_End:
                target_index = len(visible_tracks) - 1
            elif current is None:
                target_index = 0
            else:
                step = -1 if key == Qt.Key_Up else 1
                target_index = max(
                    0,
                    min(len(visible_tracks) - 1, current + step),
                )
            self._clear_clip_selection()
            self._select_track(visible_tracks[target_index], emit=True)
            event.accept()
            return
        if (
            key in (Qt.Key_Left, Qt.Key_Right)
            and not modifiers & (Qt.ControlModifier | Qt.AltModifier)
            and not (
                self._focus_scope == "clip" and self._selected_clip_keys
            )
        ):
            direction = 1 if key == Qt.Key_Right else -1
            self._move_playhead_by(
                direction * timeline_grid_step_ms(
                    self.bpm,
                    coarse=bool(modifiers & Qt.ShiftModifier),
                ),
                extend=bool(modifiers & Qt.ShiftModifier),
            )
            event.accept()
            return

        track_index = self._selected_track_index()
        track = self.tracks[track_index] if track_index is not None else None
        if track is None:
            super().keyPressEvent(event)
            return
        if modifiers & Qt.ControlModifier and key == Qt.Key_C and self._selected_clip_id:
            self.clip_copy_requested.emit(track, self._selected_clip_id)
            event.accept()
            return
        if modifiers & Qt.ControlModifier and key == Qt.Key_V:
            self.clip_paste_requested.emit(track, self.playhead_ms)
            event.accept()
            return
        if (
            modifiers == (Qt.ControlModifier | Qt.ShiftModifier)
            and key == Qt.Key_D
        ):
            self.duplicate_track_requested.emit(track)
            event.accept()
            return
        if (
            modifiers == Qt.ControlModifier
            and key == Qt.Key_D
            and self._selected_clip_id
        ):
            self.clip_duplicate_requested.emit(track, self._selected_clip_id)
            event.accept()
            return
        if key == Qt.Key_F2 and modifiers == Qt.NoModifier:
            if self._selected_clip_id:
                self.clip_rename_requested.emit(track, self._selected_clip_id)
            else:
                self.rename_track_requested.emit(track)
            event.accept()
            return
        if (
            modifiers == Qt.ControlModifier
            and key == Qt.Key_E
            and self._selected_clip_id
        ):
            clip = clip_by_id(track, self._selected_clip_id)
            if (
                clip.start_ms + MIN_CLIP_DURATION_MS
                <= self.playhead_ms
                <= clip.end_ms - MIN_CLIP_DURATION_MS
            ):
                self.clip_split_requested.emit(TimelineClipSplitRequest(
                    track, self._selected_clip_id, self.playhead_ms
                ))
            event.accept()
            return
        if (
            modifiers == Qt.ControlModifier
            and key == Qt.Key_L
            and self._selected_clip_id
        ):
            self.clip_repeat_requested.emit(track, self._selected_clip_id)
            event.accept()
            return
        if (
            modifiers == Qt.ControlModifier
            and key == Qt.Key_J
            and len(self.selected_clip_items()) >= 2
        ):
            self.clips_consolidate_requested.emit(self.selected_clip_items())
            event.accept()
            return
        if (
            modifiers == (Qt.ControlModifier | Qt.ShiftModifier)
            and key == Qt.Key_J
            and self._selected_clip_id
        ):
            self.clip_crop_requested.emit(track, self._selected_clip_id)
            event.accept()
            return
        if (
            key in (Qt.Key_Delete, Qt.Key_Backspace)
            and modifiers == Qt.NoModifier
            and self._selected_clip_keys
        ):
            items = self.selected_clip_items()
            if len(items) > 1:
                self.clips_delete_requested.emit(items)
            elif items:
                self.clip_delete_requested.emit(*items[0])
            event.accept()
            return
        plain_shortcut = not (
            modifiers & (Qt.ControlModifier | Qt.AltModifier)
        )
        if plain_shortcut and key == Qt.Key_M:
            track.muted = not track.muted
            self._update_accessible_track_state()
            self.changed.emit()
            self.track_state_changed.emit()
            self.update()
            event.accept()
            return
        if plain_shortcut and key == Qt.Key_S:
            track.solo = not track.solo
            self._update_accessible_track_state()
            self.changed.emit()
            self.track_state_changed.emit()
            self.update()
            event.accept()
            return
        if plain_shortcut and key == Qt.Key_F:
            self.effects_requested.emit(track)
            event.accept()
            return
        if plain_shortcut and key in (Qt.Key_Return, Qt.Key_Enter):
            group_id = str(track.arrangement_group_id or "")
            if group_id in self._collapsed_arrangement_groups:
                self._set_group_collapsed(group_id, False)
                event.accept()
                return
            if self._focus_scope == "clip" and self._selected_clip_id:
                self.clip_note_editor_requested.emit(
                    track, self._selected_clip_id
                )
            else:
                self.note_editor_requested.emit(track)
            event.accept()
            return
        if (
            key in (Qt.Key_Left, Qt.Key_Right)
            and modifiers & Qt.AltModifier
            and not modifiers & Qt.ControlModifier
        ):
            volume_direction = 1 if key == Qt.Key_Right else -1
            step = 5 if modifiers & Qt.ShiftModifier else 1
            value = max(
                0,
                min(
                    100,
                    int(track.bdo_track_volume)
                    + volume_direction * step,
                ),
            )
            if value != int(track.bdo_track_volume):
                previous_volume = int(track.bdo_track_volume)
                track.bdo_track_volume = value
                self._update_accessible_track_state()
                self.game_volume_committed.emit(
                    track, previous_volume, value
                )
                self.update()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right) and not (
            modifiers & (Qt.ControlModifier | Qt.AltModifier)
        ):
            direction = 1 if key == Qt.Key_Right else -1
            delta = direction * timeline_grid_step_ms(
                self.bpm,
                coarse=bool(modifiers & Qt.ShiftModifier),
            )
            self._nudge_selected_clips(delta)
            event.accept()
            return
        volume_direction = (
            1
            if key in (Qt.Key_Plus, Qt.Key_Equal)
            else -1
            if key == Qt.Key_Minus
            else 0
        )
        if plain_shortcut and volume_direction:
            step = 5 if modifiers & Qt.ShiftModifier else 1
            value = max(
                0,
                min(
                    100,
                    int(track.bdo_track_volume)
                    + volume_direction * step,
                ),
            )
            if value != int(track.bdo_track_volume):
                previous_volume = int(track.bdo_track_volume)
                track.bdo_track_volume = value
                self._update_accessible_track_state()
                self.game_volume_committed.emit(
                    track,
                    previous_volume,
                    value,
                )
                self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        self._update_accessible_track_state()
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)
