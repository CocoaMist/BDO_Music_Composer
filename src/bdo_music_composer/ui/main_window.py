#!/usr/bin/env python3
"""GarageBand-style PySide6 MIDI workspace for BDO music conversion."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from functools import lru_cache
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[3]
)
from bdo_music_composer.core.project_paths import (
    ASSETS_DIR,
    SAMPLE_PACK_CACHE_DIR,
    USER_DATA_DIR,
    WWISE_MIDI_MAP_PATH,
)
# Source and frozen launches share the same user-writable boundary.  Keeping
# autosaves/configuration beside the source tree made ordinary test and
# developer runs pollute the repository and could expose private project data.
WRITABLE_ROOT = USER_DATA_DIR
DEFAULT_OUTDIR = WRITABLE_ROOT / "out" / "bdo"
DEFAULT_MIDI_DIR = ROOT / "samples"
CONFIG_PATH = WRITABLE_ROOT / ".pyside_bdo_gui.json"
AUTO_SAVE_DIR = WRITABLE_ROOT / "auto_save"
EXAMPLE_PROJECTS_DIR = USER_DATA_DIR / "examples"
BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH
AUDIO_VALIDATION_PATH = DEFAULT_OUTDIR / "bdo_audio_validation_matrix.json"
TRANSCRIPTION_REVIEW_QUEUE_LIMIT = 240
# The product surface is intentionally a practical note-extraction workflow.
# Harmony, phrase, voice-group, and timbre suggestion code remains readable for
# old project compatibility, but production sessions do not start its worker.
TRANSCRIPTION_SEMANTIC_ASSIST_ENABLED = False

def _session_candidate_annotations(
    result: TranscriptionResult | None,
) -> tuple[CandidateAnnotation, ...]:
    report = result.postprocess_report if result is not None else None
    if report is None:
        return ()
    return tuple(
        CandidateAnnotation(
            candidate_id=item.candidate_id,
            flags=frozenset(item.flags),
            lineage_ids=frozenset(item.lineage_ids),
            disposition=item.disposition,
        )
        for item in report.annotations
    )


try:
    import mido
    from PySide6.QtCore import (
        QEvent,
        QEventLoop,
        QFile,
        QObject,
        Qt,
        QThread,
        QTimer,
        QUrl,
        Signal,
    )
    from PySide6.QtGui import QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPainterPath, QShortcut
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import (
        QApplication,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressDialog,
        QPushButton,
        QSizePolicy,
        QSlider,
        QStackedWidget,
        QStyle,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:
    raise SystemExit(
        "PySide6/mido is not installed.\n"
        "Install dependencies with:\n"
        "  .\\.venv\\Scripts\\python.exe -m pip install -r requirements\\desktop.txt"
    ) from exc

from bdo_midi import (  # noqa: E402
    BDO_ENSEMBLE_PLAYER_LIMIT,
    BDO_INSTRUMENT_NAMES,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    Note,
    _GM_TO_BDO_DRUM,
    gm_to_bdo_instrument,
    unique_performance_instrument_ids,
)
from optimization import OptimizerConfig  # noqa: E402
from optimization.plugin_api import InvalidOptimizationPreview, OptimizationIntensity  # noqa: E402
from optimization.plugin_host import (  # noqa: E402
    BUILTIN_SAFE_ID,
    HostOptimizationError,
    analyse_with_algorithm,
    discover_host_algorithms,
    optimizer_plugin_dir,
)
from bdo_music_composer.app.game_profile_provider import (  # noqa: E402
    get_bdo_profile,
)
from bdo_common.bdo_track_effects import (  # noqa: E402
    GAME_PERCENT_MAX,
    MasterEffects,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from bdo_music_composer.editor.bdo_instrument_adaptation import (  # noqa: E402
    instrument_editor_display_adaptations,
)
from bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt import (  # noqa: E402
    InstrumentLaneArtwork,
    instrument_header_background_rect,
    paint_instrument_header_background,
)
from bdo_music_composer.audio.bdo_audio_research import sample_coverage_for_tracks  # noqa: E402
from bdo_music_composer.audio.bdo_audio_validation import (  # noqa: E402
    verified_instrument_articulations,
)
from bdo_music_composer.export.bdo_score import (  # noqa: E402
    BdoUnsupportedVersionError, read_score, snapshot_from_decoded_score,
)
from bdo_music_composer.export.bdo_validation import (  # noqa: E402
    ValidationContext,
    ValidationIssue,
    evidence_status_source,
    issues_report,
    validation_issue_disposition,
    validate_tracks,
)
from bdo_music_composer.project.project_schema import (  # noqa: E402
    CURRENT_PROJECT_SCHEMA,
    DEFAULT_REFERENCE_LAYER_SETTINGS,
    normalize_reference_layer_settings,
    project_relative_file_reference,
)
from bdo_music_composer.editor.editor_commands import ProjectCommandStack, ProjectSnapshot  # noqa: E402
from bdo_music_composer.app.crash_logging import (  # noqa: E402
    CRASH_LOG_PATH,
    append_crash_log,
    install_crash_logging,
    redact_log_paths as _redact_log_paths,
)
from bdo_music_composer.editor.editor_models import (  # noqa: E402
    ARTICULATION_ONSET_TOLERANCE_MS,
    BDO_DRUM_MAX,
    BDO_DRUM_MIN,
    BDO_DRUM_PITCH_NAMES,
    BDO_EDITOR_PITCH_RANGES,
    BDO_SAMPLE_ONLY_PERCUSSION,
    GhostNoteProjection,
    ArrangementClipState,
    TrackState,
    game_supported_pitches,
    note_name,
    same_onset_articulation_indices,
    track_uses_canonical_drum_lanes,
)
from bdo_music_composer.editor.preview_midi_writer import build_filtered_midi  # noqa: E402
from bdo_music_composer.editor.arrangement_clip import (  # noqa: E402
    default_empty_clip,
    prepare_clip_editor,
    project_track_notes,
    reconcile_track_clips_after_note_edit,
    track_clips,
)
from bdo_music_composer.transcription.transcription_commit_plan import (  # noqa: E402
    CommitCandidateRecord,
    CommitPlanError,
    CommitPlanInput,
    CommitTrackView,
    TranscriptionCommitPlan,
    plan_transcription_commit,
)
from bdo_music_composer.editor.editor_import import (  # noqa: E402
    read_midi_time_signature_denominator,
)
from bdo_music_composer.ui.editor.editor_ui_helpers import (  # noqa: E402
    BDO_DYNAMIC_ARTICULATION_COLORS,
    BDO_INSTRUMENT_MENU_GROUPS,
    TRACK_COLORS,
    add_instrument_submenus,
    articulation_color,
)
from bdo_music_composer.core.conversion_settings import (  # noqa: E402
    MATERIALIZED_VELOCITY_MODES,
    VELOCITY_MODE_PRESERVE,
    ConversionSettings,
    DEFAULT_CONVERSION_BPM_OVERRIDE,
    DEFAULT_CONVERSION_TRANSPOSE,
)
from bdo_music_composer.editor.game_score_model import (  # noqa: E402
    bake_game_velocity_transform,
    decode_serialized_game_instrument_id,
    formal_score_tracks,
    inherit_game_instrument_mix,
    preview_tracks,
    propagate_game_instrument_mix,
    reconcile_track_game_velocity_records,
)
from bdo_music_composer.editor.pitch_transform import (  # noqa: E402
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
    transpose_notes,
)
from bdo_music_composer.app.audio_source_settings import (  # noqa: E402
    PREVIEW_SOURCE_MODES,
    activate_audio_source,
    audio_source_config,
    classify_audio_source,
    default_game_music_dir,
    displayed_audio_source,
    preview_source_mode,
    remember_source_paths,
    source_paths_for_mode,
)
from bdo_music_composer.ui.dialogs.application_settings_dialog import (  # noqa: E402
    GameArtImportWorker,
    SettingsDialog,
    prompt_for_owner_identity,
)
from bdo_music_composer.app.application_config import (  # noqa: E402
    load_config as _load_application_config,
    owner_identity,
    safe_filename,
    save_config as _save_application_config,
    set_owner_identity,
)
from bdo_music_composer.ui.dialogs.track_settings_dialogs import (  # noqa: E402
    MARNIAN_SYNTH_MODES,
    MasterEffectsDialog,
    TrackFxDialog,
    TrackPitchDialog,
)
from bdo_music_composer.ui.track_ordering import TrackOrderingMixin  # noqa: E402
from bdo_music_composer.ui.track_merge_qt import TrackMergeHostMixin  # noqa: E402
from bdo_music_composer.ui.track_group_qt import TrackGroupHostMixin  # noqa: E402
from bdo_music_composer.ui.editor_workspace_qt import EditorWorkspaceHostMixin  # noqa: E402
from bdo_music_composer.ui.arrangement_import_qt import ArrangementImportHostMixin  # noqa: E402
from bdo_music_composer.ui.arrangement_clip_qt import ArrangementClipHostMixin  # noqa: E402
from bdo_music_composer.ui.midi_export_qt import MidiExportHostMixin  # noqa: E402
from bdo_music_composer.ui.creation_assistant_host import CreationAssistantHostMixin  # noqa: E402
from bdo_music_composer.ui.editor_import_qt import (  # noqa: E402
    TRACK_IMPORT_PRESENTATION as _TRACK_IMPORT_PRESENTATION,
    prepare_midi_import,
    source_time_signature_denominator,
    track_states_from_bdo_score,
    track_states_from_project_payload,
    ui_bdo_instrument_name as _ui_bdo_instrument_name,
    ui_bdo_instrument_names as _ui_bdo_instrument_names,
    ui_bdo_instrument_source as _ui_bdo_instrument_source,
)
from bdo_music_composer.ui.timeline_velocity_curve_host import TimelineVelocityCurveHostMixin  # noqa: E402
from bdo_music_composer.ui.timeline_toolbar_qt import (  # noqa: E402
    bind_arrangement_tool_buttons,
    build_arrangement_tool_buttons,
    build_timeline_popup_buttons,
    edit_reference_audio_offset,
)
from bdo_music_composer.ui.workspace_tempo_qt import WorkspaceTempoHostMixin  # noqa: E402
from bdo_music_composer.ui.workspace_usage_qt import (  # noqa: E402
    WorkspaceUsageHostMixin,
    mark_startup_usage_failure,
)
from bdo_music_composer.ui.workspace_preview_source_qt import WorkspacePreviewSourceMixin  # noqa: E402
from bdo_music_composer.ui.workspace_reference_playback_qt import WorkspaceReferencePlaybackMixin  # noqa: E402
from bdo_music_composer.ui.ui_controls import (  # noqa: E402
    ElidedLabel,
    PillButton,
)
from bdo_music_composer.ui.ui_notifications import (  # noqa: E402
    GlobalToast,
    show_global_toast,
)
from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas  # noqa: E402
from bdo_music_composer.ui.editor.piano_roll_canvas import PianoRollCanvas, VelocityLaneCanvas  # noqa: E402
from bdo_music_composer.ui.editor.midi_note_editor import MidiNoteEditorDialog  # noqa: E402
from bdo_music_composer.ui.dialogs.optimizer_dialog import (  # noqa: E402
    MidiOptimizeDialog,
    OptimizerAnalysisWorker,
    _optimizer_diagnostic_value,
    _optimizer_host_message_value,
)
from bdo_music_composer.audio.reference_audio_controller import (  # noqa: E402
    ReferenceAudioController,
)
from bdo_music_composer.ui.transcription.transcription_workers import (  # noqa: E402
    SamplePackPrepareWorker,
    TranscriptionAnalysisWorker,
    TranscriptionAssistAnalysisBundle,
    TranscriptionAssistAnalysisWorker,
    TranscriptionCacheLoadWorker,
    TranscriptionRedecodeWorker,
)
from bdo_music_composer.ui.reference_timbre_qt import ReferenceTimbreHostMixin  # noqa: E402
from bdo_music_composer.ui.project_autosave_qt import (  # noqa: E402
    AutosaveWriteWorker,
    ProjectAutosaveHostMixin,
)
from bdo_music_composer.ui.transcription_rhythm_diagnostic import (  # noqa: E402
    TranscriptionRhythmDiagnosticMixin,
)
from bdo_music_composer.ui.theme.main_window_style import MainWindowStyleMixin  # noqa: E402
from bdo_music_composer.ui.ui_preferences_qt import WorkspaceUiPreferenceBinding  # noqa: E402
from bdo_music_composer.ui.editor.editor_articulation_data import (  # noqa: E402
    BDO_ARTICULATIONS,
)
from bdo_music_composer.ui.transcription_ui_helpers import (  # noqa: E402
    transcription_cleanup_ui_labels as _transcription_cleanup_ui_labels,
)
from bdo_music_composer.export.export_workflow import (  # noqa: E402
    build_export_request,
    ExportRequest,
    ExportRequestSpec,
    execute_export,
    install_export_to_game,
    serialized_bdo_instrument_id,
)
from bdo_music_composer.export.export_verification import (  # noqa: E402
    ExportVerificationReport,
    format_export_verification_report,
)
from bdo_common.atomic_io import atomic_write_bytes  # noqa: E402
from bdo_music_composer.app.home_catalog import (  # noqa: E402
    HomeEntry,
    IncrementalHomeScan,
    home_timestamp as _home_timestamp,
    merge_home_project_entries as _merge_home_project_entries,
    scan_example_projects as _scan_example_projects,
    scan_game_scores,
    scan_local_projects,
)
from bdo_music_composer.ui.home_downloads_qt import HomeDownloadsPage  # noqa: E402
from bdo_music_composer.ui.home_widgets import (  # noqa: E402
    HOME_BACKGROUND_IMAGE,
    HOME_INSTRUMENT_IDS_ROLE,
    APP_ICON_IMAGE,
    SHAI_ENSEMBLE_MARK_IMAGE,
    EnsembleCapacityBadge,
    HomeBackdrop,
    HomeEntryDelegate,
    HomeFooter,
    HomeHero,
    HomeIdentityBadge,
    HomeLibrarySurface,
    HomeLibraryTabs,
    HomeListWidget,
)
from bdo_music_composer.ui.page_transition_qt import (  # noqa: E402
    MOTION_CONFIG_KEY, MOTION_PROPERTY, NavigationCue, StackedPageTransition,
)
from bdo_music_composer.ui.score_library_downloads import (  # noqa: E402
    ScoreLibraryDownload,
    ScoreLibraryDownloads,
)
from bdo_music_composer.ui.startup_widgets import FirstVisiblePaint, place_startup_window  # noqa: E402
from bdo_music_composer.project.project_persistence import (  # noqa: E402
    AutosaveRequest,
    ProjectMetadataSnapshot,
    freeze_project_tracks,
    new_project_id,
    normalize_project_id,
    rename_project,
)
from bdo_music_composer.audio.bdo_sample_renderer import (  # noqa: E402
    BdoSampleMap,
    sample_map_evidence_sha256,
    sample_map_supported_pitches,
    sample_map_supports_note,
)
from bdo_music_composer.audio.bdo_realtime_audio import AudioEngineError, BdoRealtimeAudioEngine  # noqa: E402
from bdo_music_composer.app.process_metrics import (  # noqa: E402
    ProcessMetricsSampler,
)
from bdo_music_composer.transcription.bdo_transcription import (  # noqa: E402
    DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
    DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    POSTPROCESS_VERSION,
    TranscriptionCancelled,
    TranscriptionCandidate,
    TranscriptionError,
    TranscriptionResult,
    load_cached_transcription_result,
    load_transcription_evidence,
    load_transcription_frame_times,
    prune_transcription_workspaces,
    redecode_transcription_full,
    redecode_transcription_interval,
    transcription_audio_fingerprint,
    transcription_backend_quick_status,
    transcribe_reference_audio,
)
from bdo_music_composer.transcription.bdo_transcription_harmony import (  # noqa: E402
    ChordSegment,
    HarmonyAnalysisCancelled,
    HarmonyAnalysis,
    KeyEstimate,
    analyse_harmony,
    apply_harmony_overrides,
    harmony_cache_key,
)
from bdo_music_composer.transcription.bdo_transcription_instruments import (  # noqa: E402
    BdoInstrumentDescriptor,
    InstrumentAnalysisCancelled,
    InstrumentMatchAnalysis,
    VoiceGroup,
    group_voice_candidates,
    match_bdo_instruments,
    overlay_manual_voice_groups,
    refine_voice_groups_by_timbre,
)
from bdo_music_composer.transcription.bdo_transcription_timbre import (  # noqa: E402
    FramePitchEvidence,
    TimbreProfileError,
    extract_group_timbre_profiles,
    load_or_build_timbre_profile_index,
    remap_group_timbre_profiles,
)
from bdo_music_composer.transcription.bdo_transcription_assist import (  # noqa: E402
    KeyReviewOverride,
    LockedChordReview,
    ManualVoiceGroupReview,
    TranscriptionAssistReviewState,
    isolate_assist_review_for_audio,
    recover_assist_review,
    stable_assist_review_id,
)
from bdo_music_composer.transcription.bdo_transcription_policy import candidate_is_invalid_for_track  # noqa: E402
from bdo_music_composer.transcription.bdo_transcription_session import (  # noqa: E402
    CandidateAnnotation,
    TranscriptionEditorCommit,
    TranscriptionEditorCommitReport,
    TranscriptionSession,
    TranscriptionSessionState,
)
from bdo_music_composer.ui.transcription.transcription_editor_qt import (  # noqa: E402
    TranscriptionEditorPanel,
    TranscriptionWaveformLane,
    voice_role_label,
    voice_role_source_label,
)
from bdo_music_composer.audio.bdo_sample_pack import (  # noqa: E402
    SamplePackCancelled,
    SamplePackError,
    extract_sample_pack,
)
from bdo_music_composer.ui.track_properties_qt import apply_track_fx, apply_track_pitch
from bdo_music_composer.ui.workbench_qt import ComposerWorkbench
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.window_chrome_qt import ScoreTitleEdit, WindowChrome, WorkspaceSurface
from bdo_music_composer.ui.i18n import (  # noqa: E402
    defer_tr,
    install_localizer,
    localizer,
    tr,
    trf,
    trfv,
    tr_joinv,
    trv,
)
from bdo_music_composer.ui.theme.fluent_theme import (  # noqa: E402
    FluentSymbol,
    enable_caption_focus_icons,
    build_fluent_stylesheet,
    configure_widget_style,
    fluent_icon_size,
    refresh_fluent_icons,
    set_fluent_symbol,
    system_uses_dark_theme,
)
from bdo_music_composer.app.application_metadata import (  # noqa: E402
    APP_DISPLAY_VERSION, APP_NAME,
    APP_VERSION,
    RELEASE_NOTES_UI_ENABLED,
    WINDOWS_APP_USER_MODEL_ID,
)
from bdo_music_composer.ui.self_update_qt import (  # noqa: E402
    SelfUpdateController,
)
from bdo_music_composer.ui.self_update_host import SelfUpdateHostMixin  # noqa: E402
from bdo_music_composer.update.preferences import update_preferences  # noqa: E402
from bdo_music_composer.ui.dialogs.about_dialog import AboutDialog  # noqa: E402
from bdo_music_composer.ui.dialogs.composer_prompt import choose_item, choose_prompt, prompt_text  # noqa: E402
from bdo_music_composer.ui.dialogs.feedback_dialog import FeedbackDialog  # noqa: E402
from bdo_music_composer.ui.dialogs.release_notes_dialog import ReleaseNotesDialog  # noqa: E402
from bdo_music_composer.ui.feedback_status_qt import FeedbackStatusTracker  # noqa: E402
from bdo_music_composer.ui.feedback_toolbar_qt import FeedbackToolbarButton  # noqa: E402
from bdo_music_composer.ui.floating_panel_qt import exec_floating_panel  # noqa: E402
from bdo_music_composer.app.conversion_validation_controller import (  # noqa: E402
    ConversionValidationController,
)
from bdo_music_composer.editor.model_revision import ModelRevision  # noqa: E402
from bdo_music_composer.editor.model_change import ModelChange  # noqa: E402
from bdo_music_composer.app.workspace_refresh_controller import (  # noqa: E402
    RefreshPlan,
    WorkspaceRefreshController,
)
from bdo_music_composer.audio.preview_transport_controller import (  # noqa: E402
    PreviewPlayAction,
    PreviewTransportCoordinator,
)
from bdo_music_composer.ui.global_velocity_gain_qt import (  # noqa: E402
    GlobalVelocityGainHostMixin,
)
from bdo_music_composer.ui.timeline_validation_host import (  # noqa: E402
    TimelineValidationHostMixin,
)
from bdo_music_composer.ui.performance_probe_qt import (  # noqa: E402
    install_ui_performance_probe,
)
from bdo_music_composer.ui.workspace_refresh_qt import (  # noqa: E402
    apply_workspace_refresh, sync_timeline_viewport_controls,
)
from bdo_music_composer.project.project_lifecycle_controller import (  # noqa: E402
    ProjectLifecycleController,
)
from bdo_music_composer.app.project_document import (  # noqa: E402
    ProjectLoadError,
    ProjectLoadErrorCode,
    ProjectLoadPlan,
    prepare_project_load,
)
from bdo_music_composer.transcription.transcription_workspace_controller import (  # noqa: E402
    restored_audio_review_requires_isolation,
    TranscriptionAnalysisCoordinator,
    TranscriptionReviewController,
)

decode_marnian_instrument = decode_serialized_game_instrument_id


def scan_example_projects(directory: Path, limit: int = 8) -> list[HomeEntry]:
    """Compatibility wrapper that injects localized example presentation."""

    return _scan_example_projects(
        directory,
        limit,
        unknown_source=str(trv("未知来源")),
        format_detail=lambda source: str(
            trf("示例 · 来源：{source}", source=source)
        ),
    )


def merge_home_project_entries(
    entries: list[HomeEntry], limit: int = 80,
) -> list[HomeEntry]:
    """Compatibility wrapper that injects localized version presentation."""

    return _merge_home_project_entries(
        entries,
        limit,
        timestamp=_home_timestamp,
        format_version=lambda value, index, count: str(trf(
            "{time} · 版本 {index}/{count}",
            time=value,
            index=index,
            count=count,
        )),
    )


def game_pitch_range_label(
    instrument_id: int, synth_mode: str = "basic"
) -> str:
    return str(game_pitch_range_value(instrument_id, synth_mode))


def game_pitch_range_value(
    instrument_id: int,
    synth_mode: str = "basic",
) -> object:
    """Return a live-switch-safe game-range label."""

    pitches = game_supported_pitches(instrument_id, synth_mode)
    if not pitches:
        return trv("游戏音域待验证")
    low, high = min(pitches), max(pitches)
    gap_count = high - low + 1 - len(pitches)
    if gap_count:
        return trfv(
            "游戏 {low}-{high}（缺少 {gap_count} 个音）",
            low=note_name(low),
            high=note_name(high),
            gap_count=gap_count,
        )
    return trfv(
        "游戏 {low}-{high}",
        low=note_name(low),
        high=note_name(high),
    )


def copy_export_to_game(out_path: Path, game_dir: Path) -> Path:
    """Compatibility wrapper for the atomic export installer."""

    return install_export_to_game(out_path, game_dir)


def load_config() -> dict:
    return _load_application_config(CONFIG_PATH)


def save_config(config: dict) -> None:
    _save_application_config(CONFIG_PATH, config)



@dataclass(frozen=True, slots=True)
class _TrackCommitCheckpoint:
    track: TrackState
    notes: tuple[Note, ...]
    notes_optimized: bool
    articulation_type: int | None
    bdo_source_note_records: tuple[tuple, ...]


class ConvertWorker(QThread):
    conversion_finished = Signal(str, int, object, str, str)
    failed = Signal(str)

    def __init__(self, params: ExportRequest):
        super().__init__()
        self.params = params

    def run(self) -> None:
        try:
            self.conversion_finished.emit(*execute_export(self.params))
        except BaseException as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


def _instrument_preferred_roles(instrument_id: int) -> frozenset[str]:
    if instrument_id in {0x0E, 0x0F}:
        return frozenset({"bass", "rhythm"})
    if instrument_id in {0x06, 0x10, 0x07, 0x11}:
        return frozenset({"harmony", "pad", "primary_melody"})
    if instrument_id in {0x08, 0x12, 0x01, 0x02, 0x0B, 0x27, 0x28}:
        return frozenset({"primary_melody", "secondary_melody", "harmony"})
    if instrument_id in {0x00, 0x0A, 0x24, 0x25, 0x26}:
        return frozenset({"primary_melody", "harmony", "rhythm"})
    if instrument_id == 0x13:
        return frozenset({"harmony", "rhythm", "ornament"})
    if instrument_id in {0x14, 0x18, 0x1C, 0x20}:
        return frozenset({"pad", "fx", "ornament"})
    return frozenset({"harmony"})


def _instrument_articulation_profile(instrument_id: int) -> str:
    if instrument_id in {0x01, 0x02, 0x08, 0x0B, 0x0F, 0x10, 0x12, 0x27, 0x28}:
        return "sustain"
    if instrument_id in {0x04, 0x05, 0x0D, 0x13}:
        return "short"
    return "versatile"


@lru_cache(maxsize=1)
def bdo_transcription_instrument_descriptors() -> tuple[BdoInstrumentDescriptor, ...]:
    """Build advisory descriptors from the same verified profile as export."""

    descriptors: list[BdoInstrumentDescriptor] = []
    for instrument_id, rule in sorted(get_bdo_profile().instruments.items()):
        is_percussion = instrument_id in {0x04, 0x05, 0x0D}
        descriptors.append(
            BdoInstrumentDescriptor(
                instrument_id=instrument_id,
                pitch_min=rule.pitch_min,
                pitch_max=rule.pitch_max,
                available_pitches=rule.allowed_pitches,
                preferred_roles=_instrument_preferred_roles(instrument_id),
                articulation_profile=_instrument_articulation_profile(
                    instrument_id
                ),
                is_percussion=is_percussion,
                # Program-generated Marnian families remain range/role-only
                # until an explicit in-game A/B evidence profile exists.
                timbre_evidence_approved=instrument_id
                not in {0x14, 0x18, 0x1C, 0x20},
            )
        )
    return tuple(descriptors)


class MidiToBdoWindow(
    CreationAssistantHostMixin,
    EditorWorkspaceHostMixin,
    ProjectAutosaveHostMixin,
    TranscriptionRhythmDiagnosticMixin,
    ReferenceTimbreHostMixin,
    ArrangementImportHostMixin,
    ArrangementClipHostMixin,
    MidiExportHostMixin,
    TrackMergeHostMixin,
    TrackGroupHostMixin,
    TrackOrderingMixin,
    TimelineVelocityCurveHostMixin,
    WorkspaceTempoHostMixin,
    WorkspaceUsageHostMixin,
    WorkspacePreviewSourceMixin,
    WorkspaceReferencePlaybackMixin,
    GlobalVelocityGainHostMixin,
    TimelineValidationHostMixin,
    SelfUpdateHostMixin,
    MainWindowStyleMixin,
    QMainWindow,
):
    _usage_config_path = CONFIG_PATH

    @property
    def transcription_assist_review_undo(
        self,
    ) -> list[TranscriptionAssistReviewState]:
        return self.transcription_review_controller.assist_undo

    @transcription_assist_review_undo.setter
    def transcription_assist_review_undo(
        self,
        value: Sequence[TranscriptionAssistReviewState],
    ) -> None:
        self.transcription_review_controller.assist_undo = list(value)

    @property
    def transcription_assist_review_redo(
        self,
    ) -> list[TranscriptionAssistReviewState]:
        return self.transcription_review_controller.assist_redo

    @transcription_assist_review_redo.setter
    def transcription_assist_review_redo(
        self,
        value: Sequence[TranscriptionAssistReviewState],
    ) -> None:
        self.transcription_review_controller.assist_redo = list(value)

    @property
    def transcription_review_action_undo(self) -> list[str]:
        return self.transcription_review_controller.action_undo

    @transcription_review_action_undo.setter
    def transcription_review_action_undo(self, value: Sequence[str]) -> None:
        self.transcription_review_controller.action_undo = list(value)

    @property
    def transcription_review_action_redo(self) -> list[str]:
        return self.transcription_review_controller.action_redo

    @transcription_review_action_redo.setter
    def transcription_review_action_redo(self, value: Sequence[str]) -> None:
        self.transcription_review_controller.action_redo = list(value)

    @property
    def loading_project(self) -> bool:
        return self.project_lifecycle_controller.loading

    @loading_project.setter
    def loading_project(self, value: bool) -> None:
        self.project_lifecycle_controller.set_loading(
            bool(value),
            "compatibility assignment",
        )

    @property
    def workspace_transcription_generation(self) -> int:
        return self.transcription_analysis_coordinator.workspace_generation

    @workspace_transcription_generation.setter
    def workspace_transcription_generation(self, value: int) -> None:
        self.transcription_analysis_coordinator.workspace_generation = int(value)

    @property
    def transcription_assist_generation(self) -> int:
        return self.transcription_analysis_coordinator.assist_generation

    @transcription_assist_generation.setter
    def transcription_assist_generation(self, value: int) -> None:
        self.transcription_analysis_coordinator.assist_generation = int(value)

    @property
    def transcription_assist_restart_pending(self) -> bool:
        return self.transcription_analysis_coordinator.assist_restart_pending

    @transcription_assist_restart_pending.setter
    def transcription_assist_restart_pending(self, value: bool) -> None:
        self.transcription_analysis_coordinator.assist_restart_pending = bool(value)

    @property
    def transcription_assist_restart_harmony_only(self) -> bool:
        return (
            self.transcription_analysis_coordinator
            .assist_restart_harmony_only
        )

    @transcription_assist_restart_harmony_only.setter
    def transcription_assist_restart_harmony_only(self, value: bool) -> None:
        self.transcription_analysis_coordinator.assist_restart_harmony_only = (
            bool(value)
        )

    @property
    def transcription_assist_restart_allow_review_recovery(self) -> bool:
        return (
            self.transcription_analysis_coordinator
            .assist_restart_allow_review_recovery
        )

    @transcription_assist_restart_allow_review_recovery.setter
    def transcription_assist_restart_allow_review_recovery(
        self,
        value: bool,
    ) -> None:
        coordinator = self.transcription_analysis_coordinator
        coordinator.assist_restart_allow_review_recovery = bool(value)

    @property
    def preview_generation(self) -> int:
        return self.preview_transport_coordinator.generation

    @preview_generation.setter
    def preview_generation(self, value: int) -> None:
        self.preview_transport_coordinator.generation = int(value)

    @property
    def realtime_preview_active(self) -> bool:
        return self.preview_transport_coordinator.active

    @realtime_preview_active.setter
    def realtime_preview_active(self, value: bool) -> None:
        self.preview_transport_coordinator.active = bool(value)

    @property
    def realtime_preview_loading(self) -> bool:
        return self.preview_transport_coordinator.loading

    @realtime_preview_loading.setter
    def realtime_preview_loading(self, value: bool) -> None:
        self.preview_transport_coordinator.loading = bool(value)

    @property
    def realtime_preview_source(self) -> str:
        return self.preview_transport_coordinator.source

    @realtime_preview_source.setter
    def realtime_preview_source(self, value: str) -> None:
        self.preview_transport_coordinator.source = str(value)

    @property
    def realtime_preview_start_ms(self) -> float:
        return self.preview_transport_coordinator.start_ms

    @realtime_preview_start_ms.setter
    def realtime_preview_start_ms(self, value: float) -> None:
        self.preview_transport_coordinator.start_ms = float(value)

    @property
    def realtime_preview_tracks(self) -> list[object]:
        return self.preview_transport_coordinator.tracks

    @realtime_preview_tracks.setter
    def realtime_preview_tracks(self, value: Sequence[object]) -> None:
        self.preview_transport_coordinator.tracks = list(value)

    @property
    def realtime_validation_state(self) -> str:
        return self.preview_transport_coordinator.validation_state

    @realtime_validation_state.setter
    def realtime_validation_state(self, value: str) -> None:
        self.preview_transport_coordinator.validation_state = str(value)

    def _advance_model_revision(self, reason: str) -> int:
        return self.model_revision.advance(reason)

    def _set_conversion_settings(
        self,
        settings: ConversionSettings,
        *,
        preserve_pitch_overrides: bool = True,
    ) -> None:
        previous_settings = getattr(self, "_conversion_settings", None)
        self._conversion_settings = settings
        current = getattr(self, "_pitch_transform_plan", None)
        overrides = (
            current.track_overrides
            if preserve_pitch_overrides
            and isinstance(current, PitchTransformPlan)
            else ()
        )
        self._pitch_transform_plan = PitchTransformPlan(
            settings.transpose,
            overrides,
        )
        if previous_settings is not None and previous_settings != settings:
            self._advance_model_revision("conversion settings")

    @property
    def bpm_override(self) -> int | None:
        return self._conversion_settings.bpm_override

    @bpm_override.setter
    def bpm_override(self, value: int | None) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(bpm_override=value)
        )

    @property
    def transpose(self) -> int:
        return self._conversion_settings.transpose

    @transpose.setter
    def transpose(self, value: int) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(transpose=value)
        )

    @property
    def apply_sustain(self) -> bool:
        return self._conversion_settings.apply_sustain

    @apply_sustain.setter
    def apply_sustain(self, value: bool) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(apply_sustain=value)
        )

    @property
    def flatten_tempo(self) -> bool:
        return self._conversion_settings.flatten_tempo

    @flatten_tempo.setter
    def flatten_tempo(self, value: bool) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(flatten_tempo=value)
        )

    @property
    def velocity_mode(self) -> str:
        return self._conversion_settings.velocity_mode

    @velocity_mode.setter
    def velocity_mode(self, value: str) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(velocity_mode=value)
        )

    @property
    def vel_range(self) -> tuple[int, int] | None:
        return self._conversion_settings.vel_range

    @vel_range.setter
    def vel_range(self, value: object) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(vel_range=value)
        )

    @property
    def vel_floor(self) -> int | None:
        return self._conversion_settings.vel_floor

    @vel_floor.setter
    def vel_floor(self, value: int | None) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(vel_floor=value)
        )

    @property
    def vel_step(self) -> tuple[int, int] | int | None:
        return self._conversion_settings.vel_step

    @vel_step.setter
    def vel_step(self, value: object) -> None:
        self._set_conversion_settings(
            self._conversion_settings.with_updates(vel_step=value)
        )

    def __init__(self) -> None:
        super().__init__()
        self.ui_performance_probe = None
        self.model_revision = ModelRevision()
        self.workspace_refresh_controller = WorkspaceRefreshController()
        self.conversion_validation_controller = (
            ConversionValidationController(validate_tracks)
        )
        self.transcription_analysis_coordinator = (
            TranscriptionAnalysisCoordinator()
        )
        self.transcription_review_controller = (
            TranscriptionReviewController[TranscriptionAssistReviewState]()
        )
        self._initialize_transcription_rhythm_diagnostic()
        self.project_lifecycle_controller = ProjectLifecycleController()
        self.preview_transport_coordinator = PreviewTransportCoordinator()
        app = QApplication.instance()
        if app is not None:
            self.widget_style_name = configure_widget_style(app)
            app.aboutToQuit.connect(self._wait_for_background_writers_on_quit)
        else:
            self.widget_style_name = ""
        self.setWindowTitle(f"{APP_NAME} v{APP_DISPLAY_VERSION}")
        self.resize(1360, 820)
        self.setMinimumSize(1160, 720)
        self.setAcceptDrops(True)

        self.config = load_config()
        self.setProperty(MOTION_PROPERTY, self.config.get(MOTION_CONFIG_KEY) is not False)
        self.update_settings = update_preferences(self.config)
        configured_owner_id, configured_character_name = owner_identity(self.config)
        self.language = str(self.config.get("language", "auto"))
        self.owner_id = configured_owner_id
        self.source_format = "midi"
        self.bdo_source_document = None
        self.tracks: list[TrackState] = []
        self.lyric_events: list[dict] = []
        self.reference_audio_path = ""
        self.reference_audio_relink_required = False
        self.reference_audio_offset_ms = 0.0
        self.beat_origin_ms = 0.0
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result: TranscriptionResult | None = None
        self.workspace_transcription_worker: QThread | None = None
        self._pending_transcription_cleanup_profile: (
            tuple[int, str, str] | None
        ) = None
        self.transcription_assist_worker: QThread | None = None
        self.reference_timbre_worker = None
        self.reference_timbre_analysis = None
        self.reference_timbre_prediction = None
        self.reference_timbre_analysis_busy = False
        self.reference_timbre_analysis_error = False
        self.sample_pack_worker: SamplePackPrepareWorker | None = None
        self.automatic_harmony_analysis: HarmonyAnalysis | None = None
        self.automatic_instrument_match_analysis: InstrumentMatchAnalysis | None = None
        self.transcription_timbre_profile_index: object | None = None
        self.transcription_group_timbre_profiles: object | None = None
        self.transcription_group_timbre_revision = ""
        self.harmony_analysis: HarmonyAnalysis | None = None
        self.instrument_match_analysis: InstrumentMatchAnalysis | None = None
        self.transcription_assist_review = TranscriptionAssistReviewState()
        self.transcription_assist_previous_candidates: tuple[object, ...] = ()
        self.active_voice_group_id = ""
        self.loop_current_voice_group = False
        self.transcription_assist_refresh_timer = QTimer(self)
        self.transcription_assist_refresh_timer.setSingleShot(True)
        self.transcription_assist_refresh_timer.setInterval(320)
        self.workspace_close_pending = False
        self._final_autosave_queued = False
        self.active_transcription_editor: MidiNoteEditorDialog | None = None
        self._note_editors: dict[object, MidiNoteEditorDialog] = {}
        self.transcription_analysis_busy = False
        self.transcription_analysis_progress: int | None = None
        self._transcription_ui_status_spec = trv(
            "载入音频，然后分析"
        )
        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        self.selected_track: TrackState | None = None
        self.bpm = 120
        self.time_sig = 4
        self.time_sig_denominator: int | None = 4
        self.tempo_changes = 1
        self.worker: ConvertWorker | None = None
        self.audio_sources = audio_source_config(self.config)
        self.instrument_art_dir = str(
            self.config.get("instrument_art_dir", "") or ""
        )
        self.config.setdefault("audio_sources", self.audio_sources)
        self.realtime_audio = BdoRealtimeAudioEngine(self, self.audio_sources)
        self.realtime_status_timer = QTimer(self)
        # The mixer owns its own thread. A ~60 FPS playhead feels continuous,
        # while visible-range painting keeps dense projects responsive.
        self.realtime_status_timer.setInterval(16)
        self.realtime_status_timer.timeout.connect(self._poll_realtime_audio_status)
        self.reference_status_timer = QTimer(self)
        self.reference_status_timer.setInterval(16)
        self.reference_status_timer.timeout.connect(self._poll_reference_audio_status)
        self.reference_last_resync_at = 0.0
        self.last_reported_underruns = 0
        self.process_metrics_sampler = ProcessMetricsSampler()
        self.output_dir_path = str(
            self.config.get("output_dir", "") or DEFAULT_OUTDIR
        )
        self.last_output_dir = Path(self.output_dir_path)
        self.game_music_dir_path = str(
            self.config.get("game_music_dir", "") or default_game_music_dir()
        )
        self.project_id = new_project_id()
        self.autosave_project_dir: Path | None = None
        self.autosave_source_copy: Path | None = None
        self.home_scan_session: IncrementalHomeScan | None = None
        self.home_scan_generation = 0
        self.research_metadata = {
            "profile_id": get_bdo_profile().profile_id,
            "ab_experiments": [],
            "timeline_markers": [],
        }
        self.project_commands = ProjectCommandStack()
        self.timeline_validation_timer = QTimer(self)
        self.timeline_validation_timer.setSingleShot(True)
        self.timeline_validation_timer.setInterval(80)
        self.timeline_validation_timer.timeout.connect(
            self._refresh_timeline_validation
        )
        self._timeline_validation_toast_signature: tuple[object, ...] = ()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self._flush_autosave)
        self.pending_autosave_reason = ""
        self.autosave_worker: AutosaveWriteWorker | None = None
        self.pending_autosave_request: AutosaveRequest | None = None
        self._autosave_retry_request: AutosaveRequest | None = None
        self._autosave_retry_count = 0
        self._autosave_error = ""
        saved_settings = self.config.get("conversion_settings", {})
        if not isinstance(saved_settings, dict):
            saved_settings = {}
        self.char_name = saved_settings.get("char_name", configured_character_name or "MIDI")
        self._set_conversion_settings(
            ConversionSettings.from_preferences(saved_settings),
            preserve_pitch_overrides=False,
        )
        # Master effects belong to the open score, never to application-wide
        # preferences. Projects and BDO imports restore their own values.
        self.reverb = 0
        self.delay = 0
        self.chorus = None

        self._build_ui()
        self.ui_preference_binding = WorkspaceUiPreferenceBinding(self, self.config, self.persist_ui_config)
        self._apply_responsive_density()
        self.project_undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.project_undo_shortcut.activated.connect(self._undo_project)
        self.project_redo_shortcut = QShortcut(QKeySequence.Redo, self)
        self.project_redo_shortcut.activated.connect(self._redo_project)
        self.project_save_shortcut = QShortcut(QKeySequence.Save, self)
        self.project_save_shortcut.activated.connect(self._save_current_project)
        self.project_save_as_shortcut = QShortcut(QKeySequence.SaveAs, self)
        self.project_save_as_shortcut.activated.connect(self._save_project_as)
        self._project_window_shortcuts = (
            self.project_undo_shortcut, self.project_redo_shortcut,
            self.project_save_shortcut, self.project_save_as_shortcut,
        )
        self._library_shortcut_states: tuple[bool, ...] | None = None
        self._apply_style()
        self._sync_caption_button_widths()
        self._sync_preview_state()
        self._update_ensemble_metric()
        self.self_update_controller = SelfUpdateController(
            self.config,
            lambda: save_config(self.config),
            self,
        )
        self._manual_update_check = False
        self.self_update_controller.available.connect(
            self._on_update_available
        )
        self.self_update_controller.progress.connect(self._on_update_progress)
        self.self_update_controller.ready.connect(self._on_update_ready)
        self.self_update_controller.current.connect(self._on_update_current)
        self.self_update_controller.failed.connect(self._on_update_failed)
        self.ui_performance_probe = install_ui_performance_probe(self)
        QTimer.singleShot(25_000, self._start_background_update)

    def _build_ui(self) -> None:
        self.online_score_library_page: QWidget | None = None
        self._library_return_page: QWidget | None = None
        self.score_library_downloads = ScoreLibraryDownloads(self)
        self.score_library_downloads.finished.connect(self._notify_score_library_download)
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.workspace_surface = WorkspaceSurface()
        root.addWidget(self._build_toolbar(self.workspace_surface))

        self.page_stack = self.workspace_surface.pages
        self.home_page = self._home_with_usage_welcome(self._build_home_page())
        self.workspace_page = QWidget()
        self.workspace_page.setObjectName("WorkspacePage")
        workspace_layout = QVBoxLayout(self.workspace_page)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self._create_workspace_status_state()
        timeline_panel = self._build_timeline_panel()
        self.workbench = ComposerWorkbench(self, timeline_panel)
        workspace_layout.addWidget(self.workbench, stretch=1)
        workspace_layout.addWidget(self._build_performance_strip())
        self.page_stack.addWidget(self.home_page)
        self.page_stack.addWidget(self.workspace_page)
        self.main_page_transition = StackedPageTransition(
            self.page_stack, self.toolbar_home_btn.parentWidget(),
        )
        root.addWidget(self.workspace_surface, stretch=1)
        self._refresh_home()
        self._set_home_toolbar_mode(True)

    def _build_toolbar(self, workspace: WorkspaceSurface) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(hig.CAPTION_HEIGHT)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(hig.GROUP_GAP, 0, hig.ITEM_GAP, 0)
        layout.setSpacing(hig.ITEM_GAP)

        project_side = QHBoxLayout()
        project_side.setSpacing(hig.CONTROL_GAP)
        layout.addLayout(project_side, stretch=1)

        self.ensemble_capacity_badge = EnsembleCapacityBadge(parent=bar)
        self.ensemble_capacity_badge.clicked.connect(self._show_about)
        project_side.addWidget(self.ensemble_capacity_badge)

        command_group = QFrame()
        command_group.setObjectName("ToolbarNavigation")
        command_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        command_layout = QHBoxLayout(command_group)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(hig.CONTROL_GAP)

        self.toolbar_home_btn = PillButton(tr("主页"), "ghost")
        set_fluent_symbol(
            self.toolbar_home_btn, FluentSymbol.HOME, checked_symbol=FluentSymbol.HOME_ACTIVE,
        )
        self.toolbar_home_btn.setFixedHeight(hig.CAPTION_BUTTON_HEIGHT)
        self.toolbar_home_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toolbar_home_btn.setAccessibleName(tr("主页"))
        self.toolbar_home_btn.setToolTip(tr("主页"))
        self.toolbar_home_btn.setCheckable(True)
        self.toolbar_home_btn.clicked.connect(self._show_home)
        command_layout.addWidget(self.toolbar_home_btn)

        self.toolbar_project_btn = PillButton(
            tr("项目"), "ghost", FluentSymbol.PROJECT
        )
        self.toolbar_project_btn.setObjectName("ToolbarProject")
        self.toolbar_project_btn.setFixedHeight(hig.CAPTION_BUTTON_HEIGHT)
        self.toolbar_project_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toolbar_project_btn.setAccessibleName(tr("项目"))
        self.toolbar_project_btn.setToolTip(tr("项目"))
        self.project_file_menu = QMenu(self.toolbar_project_btn)
        new_action = self.project_file_menu.addAction(tr("新建项目"))
        new_action.triggered.connect(self._new_project)
        open_action = self.project_file_menu.addAction(tr("打开工程或曲谱"))
        open_action.triggered.connect(self._open_project)
        self.project_file_menu.addSeparator()
        import_action = self.project_file_menu.addAction(tr("导入 MIDI"))
        import_action.triggered.connect(self._browse_midi)
        self._install_arrangement_import_menu(self.project_file_menu)
        self.project_file_menu.addSeparator()
        save_action = self.project_file_menu.addAction(tr("保存项目"))
        save_action.triggered.connect(self._save_current_project)
        save_as_action = self.project_file_menu.addAction(tr("另存为"))
        save_as_action.triggered.connect(self._save_project_as)
        self.project_file_menu.addSeparator()
        self._install_midi_export_action(self.project_file_menu)
        self.toolbar_project_btn.setMenu(self.project_file_menu)
        command_layout.addWidget(self.toolbar_project_btn)
        website_label = tr("音乐库")
        self.toolbar_website_btn = PillButton(website_label, "ghost")
        set_fluent_symbol(
            self.toolbar_website_btn, FluentSymbol.GLOBE, checked_symbol=FluentSymbol.GLOBE_ACTIVE,
        )
        self.toolbar_website_btn.setObjectName("ToolbarWebsite")
        self.toolbar_website_btn.setFixedHeight(hig.CAPTION_BUTTON_HEIGHT)
        self.toolbar_website_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toolbar_website_btn.setAccessibleName(website_label)
        self.toolbar_website_btn.setToolTip(tr("在线曲谱库"))
        self.toolbar_website_btn.setCheckable(True)
        self.toolbar_website_btn.clicked.connect(self._toggle_online_score_library)
        command_layout.addWidget(self.toolbar_website_btn)

        project_side.addWidget(command_group)

        self.document_title_group = QFrame()
        self.document_title_group.setObjectName("DocumentTitleGroup")
        self.document_title_group.setMinimumWidth(96)
        self.document_title_group.setMaximumWidth(320)
        title_layout = QVBoxLayout(self.document_title_group)
        title_layout.setContentsMargins(hig.GROUP_GAP, 0, 0, 0)
        title_layout.setSpacing(0)
        self.file_label = ElidedLabel(
            tr("未导入 MIDI"), maximum_hint_width=320
        )
        self.file_label.setObjectName("ToolbarText")

        self.output_name = ScoreTitleEdit()
        self.output_name.setObjectName("DocumentTitle")
        self.output_name.setPlaceholderText(tr("曲谱名"))
        self.output_name.setAccessibleName(tr("曲谱名"))
        self.output_name.editingFinished.connect(lambda: self._autosave_project("output name"))
        title_layout.addWidget(self.output_name)
        title_layout.addWidget(self.file_label)
        project_side.addWidget(
            self.document_title_group, stretch=1, alignment=Qt.AlignVCenter,
        )
        # A capped title leaves the remaining width available as a drag surface.
        project_side.addStretch()

        self.toolbar_playback_group = QFrame()
        self.toolbar_playback_group.setObjectName("ToolbarPlaybackGroup")
        playback_layout = QHBoxLayout(self.toolbar_playback_group)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(hig.ITEM_GAP)
        self.transport_group = self._build_preview_transport()
        playback_layout.addWidget(self.transport_group)
        playback_layout.addWidget(self._build_global_bpm_control())
        layout.addWidget(self.toolbar_playback_group, alignment=Qt.AlignVCenter)

        action_side = QHBoxLayout()
        action_side.setSpacing(hig.ITEM_GAP)
        action_side.addStretch(1)
        layout.addLayout(action_side, stretch=1)
        actions = QHBoxLayout()
        actions.setSpacing(hig.ITEM_GAP)
        action_side.addLayout(actions)

        utilities = PillButton("", "ghost", FluentSymbol.MORE)
        self.toolbar_more_button = utilities
        utilities.setObjectName("ToolbarMore")
        utilities.setFixedSize(hig.BUTTON_HEIGHT, hig.CAPTION_BUTTON_HEIGHT)
        utilities.setAccessibleName(tr("更多"))
        utilities.setToolTip(tr("更多"))
        utility_menu = QMenu(utilities)
        utility_menu.addAction(tr("设置"), lambda: self._open_settings())
        self.preview_source_menu = QMenu(tr("试听音源"), utility_menu)
        self.preview_source_action = utility_menu.addMenu(self.preview_source_menu)
        self._preview_pack_diagnostic = None
        utility_menu.aboutToShow.connect(self._refresh_preview_source_status)
        self.preview_source_action.setToolTip(
            tr("点击切换试听音源；不会改变导出结果")
        )
        self.preview_source_action_group = QActionGroup(
            self.preview_source_menu
        )
        self.preview_source_action_group.setExclusive(True)
        self.preview_source_actions = {}
        for mode, label in (
            ("generic", "内置通用音源"),
            ("pack", "音源包"),
        ):
            action = self.preview_source_menu.addAction(tr(label))
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, selected_mode=mode:
                self._set_preview_source_mode(selected_mode)
            )
            self.preview_source_action_group.addAction(action)
            self.preview_source_actions[mode] = action
        self.preview_source_menu.addSeparator()
        self.preview_source_menu.addAction(
            tr("选择音源包…"), lambda: self._open_settings(2, "pack")
        )
        self._sync_preview_source_menu()
        utility_menu.addAction(tr("运行状态"), self._show_runtime_status)
        utilities.setMenu(utility_menu)

        self.convert_button = PillButton(tr("导出 BDO"), "accent-outline", FluentSymbol.EXPORT)
        self.convert_button.setObjectName("ToolbarExport")
        self.convert_button.setFixedHeight(hig.CAPTION_BUTTON_HEIGHT)
        self.convert_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.convert_button.clicked.connect(self._convert)
        actions.addWidget(self.convert_button)
        self.feedback_status = FeedbackStatusTracker(self)
        self.toolbar_feedback_btn = FeedbackToolbarButton()
        self.toolbar_feedback_btn.clicked.connect(self._show_feedback)
        self.feedback_status.unread_changed.connect(self.toolbar_feedback_btn.set_unread_count)
        self.toolbar_feedback_btn.set_unread_count(self.feedback_status.unread_count)
        actions.addWidget(self.toolbar_feedback_btn)
        actions.addWidget(utilities)
        self.window_chrome = WindowChrome(self, bar, workspace)
        if self.window_chrome.controls is not None:
            action_side.addWidget(self.window_chrome.controls, alignment=Qt.AlignVCenter)
        enable_caption_focus_icons(bar)
        return bar

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("HomePage")
        self.home_instrument_art = InstrumentLaneArtwork()
        self._home_instrument_visual_keys = {
            instrument_id: adaptation.visual_key
            for instrument_id, adaptation
            in instrument_editor_display_adaptations().items()
        }
        self.home_instrument_art.reload(
            self.instrument_art_dir,
            self._home_instrument_visual_keys,
        )
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        overlay = QFrame()
        overlay.setObjectName("HomeOverlay")
        overlay.setFixedWidth(600)
        overlay.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.home_sidebar = overlay
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setContentsMargins(
            hig.PAGE_PADDING + hig.ITEM_GAP, 2 * hig.SECTION_GAP,
            hig.PAGE_PADDING - hig.CONTROL_GAP, hig.SECTION_GAP,
        )
        overlay_layout.setSpacing(0)

        self.home_hero = HomeHero()
        overlay_layout.addWidget(self.home_hero)
        overlay_layout.addSpacing(hig.SECTION_GAP)

        command_deck = QFrame()
        command_deck.setObjectName("HomeCommandDeck")
        quick_actions = QHBoxLayout(command_deck)
        quick_actions.setContentsMargins(0, 0, 0, 0)
        quick_actions.setSpacing(hig.ITEM_GAP)
        self.home_new_btn = PillButton(
            tr("新建项目"),
            "convert",
            FluentSymbol.NEW_PROJECT,
        )
        self.home_open_btn = PillButton(
            tr("打开"),
            "ghost",
            FluentSymbol.OPEN,
        )
        self.home_open_btn.setAccessibleName(tr("打开工程或曲谱"))
        self.home_quick_convert_btn = PillButton(
            tr("MIDI 转 BDO"),
            "ghost",
            FluentSymbol.IMPORT,
        )
        action_descriptions = (
            (self.home_new_btn, "新建空白项目\n从一条空白轨道开始"),
            (self.home_quick_convert_btn, "导入 MIDI 后选择导出或继续编辑"),
            (self.home_open_btn, "打开工程或曲谱\n支持 JSON、BDO 和 BDOM"),
        )
        for action_button, description in action_descriptions:
            action_button.setToolTip(tr(description).replace("\n", " · "))
            action_button.setAccessibleDescription(tr(description))
        for action in (self.home_new_btn, self.home_open_btn, self.home_quick_convert_btn):
            action.setObjectName("HomeQuickAction")
            action.setFixedHeight(hig.PAGE_ACTION_HEIGHT)
            quick_actions.addWidget(action, 1)
        self.home_new_btn.clicked.connect(self._new_project)
        self.home_quick_convert_btn.clicked.connect(self._quick_convert_midi)
        self.home_open_btn.clicked.connect(self._open_project)
        overlay_layout.addWidget(command_deck)
        overlay_layout.addSpacing(hig.SECTION_GAP)

        library_surface = HomeLibrarySurface()
        self.home_library_surface = library_surface
        library_surface_layout = library_surface.content_layout
        library_bar = QFrame()
        library_bar.setObjectName("HomeLibraryBar")
        library_layout = QVBoxLayout(library_bar)
        library_layout.setContentsMargins(0, 0, 0, hig.ITEM_GAP)
        library_layout.setSpacing(hig.ITEM_GAP)
        search_row = QHBoxLayout()
        search_row.setSpacing(hig.ITEM_GAP)
        library_layout.addLayout(search_row)

        library_tabs = HomeLibraryTabs()
        self.home_library_motion = NavigationCue(library_tabs)
        library_tabs_layout = library_tabs.content_layout
        self.home_nav_group = QButtonGroup(self)
        self.home_nav_group.setExclusive(True)
        self.home_project_nav = QPushButton(tr("最近项目"))
        self.home_project_nav.setObjectName("HomeNavButton")
        self.home_project_nav.setCheckable(True)
        self.home_project_nav.setAccessibleDescription(
            tr("最近项目、自动保存与示例")
        )
        self.home_game_nav = QPushButton(tr("游戏曲谱"))
        self.home_game_nav.setObjectName("HomeNavButton")
        self.home_game_nav.setCheckable(True)
        self.home_game_nav.setAccessibleDescription(
            tr("Black Desert Music 目录中的曲谱")
        )
        self.home_downloads_nav = QPushButton(tr("下载"))
        self.home_downloads_nav.setObjectName("HomeNavButton")
        self.home_downloads_nav.setCheckable(True)
        for nav_button in (self.home_project_nav, self.home_game_nav, self.home_downloads_nav):
            nav_button.setProperty("kind", "ghost")
            nav_button.setCursor(Qt.PointingHandCursor)
            nav_button.setFixedHeight(hig.SEGMENT_HEIGHT)
            self.home_nav_group.addButton(nav_button)
            library_tabs_layout.addWidget(nav_button)
        library_tabs_layout.addStretch(1)
        self.home_project_nav.setChecked(True)
        library_layout.addWidget(library_tabs)

        self.home_search = QLineEdit()
        self.home_search.setObjectName("HomeSearch")
        self.home_search.setFixedHeight(hig.BUTTON_HEIGHT)
        self.home_search.setPlaceholderText(tr("搜索项目或曲谱"))
        self.home_search.setAccessibleName(tr("搜索项目或曲谱"))
        self.home_search.setClearButtonEnabled(True)
        self.home_search.textChanged.connect(self._apply_home_filter)
        search_row.addWidget(self.home_search, stretch=1)
        self.home_refresh_btn = PillButton("", "ghost", FluentSymbol.REFRESH)
        self.home_refresh_btn.setObjectName("HomeRefreshButton")
        self.home_refresh_btn.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        self.home_refresh_btn.setToolTip(tr("刷新"))
        self.home_refresh_btn.setAccessibleName(tr("刷新"))
        self.home_refresh_btn.clicked.connect(self._refresh_home)
        search_row.addWidget(self.home_refresh_btn)
        library_surface_layout.addWidget(library_bar)

        self.home_library_stack = QStackedWidget()
        self.home_library_stack.setObjectName("HomeLibraryStack")
        (
            project_card, self.project_list, project_footer, self.project_count,
            self.project_empty_label,
        ) = self._build_home_card("项目", "打开所选项目", "暂无项目")
        project_card.setProperty("homeKind", "project")
        self.project_open_button = project_footer
        project_footer.clicked.connect(
            lambda: self._open_selected_home_item(self.project_list)
        )
        (
            game_card, self.game_score_list, game_footer, self.game_score_count,
            self.game_score_empty_label,
        ) = self._build_home_card("游戏曲谱", "打开游戏目录", "未找到游戏曲谱")
        game_card.setProperty("homeKind", "game")
        game_footer.clicked.connect(self._open_game_music_directory)
        self.home_library_stack.addWidget(project_card)
        self.home_library_stack.addWidget(game_card)
        self.home_downloads_page = HomeDownloadsPage(self.score_library_downloads)
        self.home_downloads_page.content_size_changed.connect(self._fit_home_library_page)
        self.home_downloads_page.score_open_requested.connect(self._open_bdo_score_path)
        self.home_library_stack.addWidget(self.home_downloads_page)
        library_surface_layout.addWidget(self.home_library_stack, stretch=1)

        self.home_footer = HomeFooter(APP_DISPLAY_VERSION)
        if RELEASE_NOTES_UI_ENABLED:
            self.home_footer.release_notes_requested.connect(
                self._show_release_notes
            )
        overlay_layout.addWidget(library_surface)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(self.home_footer)

        self.home_backdrop = HomeBackdrop(HOME_BACKGROUND_IMAGE)
        outer.addWidget(overlay)
        outer.addWidget(self.home_backdrop, stretch=1)

        self.home_project_nav.clicked.connect(
            lambda: self._show_home_library("project")
        )
        self.home_game_nav.clicked.connect(
            lambda: self._show_home_library("game")
        )
        self.home_downloads_nav.clicked.connect(
            lambda: self._show_home_library("downloads")
        )
        self.project_list.currentItemChanged.connect(
            lambda *_args: self._home_selection_changed()
        )
        self.game_score_list.currentItemChanged.connect(
            lambda *_args: self._home_selection_changed()
        )
        self._show_home_library("project")

        self.game_score_list.itemActivated.connect(self._open_home_item)
        self.project_list.itemActivated.connect(self._open_home_item)
        self.project_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(
            self._show_project_context_menu
        )
        return page

    def _show_home_library(self, library: str) -> None:
        if not hasattr(self, "home_library_stack"):
            return
        page_index = {"game": 1, "downloads": 2}.get(library, 0)
        previous_index = self.home_library_stack.currentIndex()
        self.home_library_stack.setCurrentIndex(page_index)
        self._fit_home_library_page()
        self.home_project_nav.setChecked(page_index == 0)
        self.home_game_nav.setChecked(page_index == 1)
        self.home_downloads_nav.setChecked(page_index == 2)
        search_hint = tr("搜索下载" if page_index == 2 else "搜索项目或曲谱")
        self.home_search.setPlaceholderText(search_hint)
        self.home_search.setAccessibleName(search_hint)
        self.home_refresh_btn.setVisible(page_index != 2)
        self._update_toolbar_ensemble_badge()
        if 0 <= previous_index != page_index:
            tabs = (self.home_project_nav, self.home_game_nav, self.home_downloads_nav)
            self.home_library_motion.play_below(tabs[previous_index], tabs[page_index])

    def _home_selection_changed(self) -> None:
        self._update_home_action_states()
        self._update_toolbar_ensemble_badge()

    def _update_home_action_states(self) -> None:
        if not hasattr(self, "project_open_button"):
            return
        item = self.project_list.currentItem()
        can_open = (
            item is not None
            and not item.isHidden()
            and isinstance(item.data(Qt.UserRole), dict)
        )
        self.project_open_button.setEnabled(can_open)
        self.project_open_button.setVisible(can_open)
        self.project_open_button.parentWidget().setVisible(
            can_open or not self.project_count.isHidden()
        )

    def _build_home_card(
        self,
        title: str,
        action: str,
        empty_message: str,
    ) -> tuple[QWidget, QListWidget, QPushButton, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("HomeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.ITEM_GAP)
        card_header_frame = QFrame()
        card_header_frame.setObjectName("HomeCardHeader")
        card_header = QHBoxLayout(card_header_frame)
        card_header.setContentsMargins(0, 0, 0, 0)
        card_header.setSpacing(hig.ITEM_GAP)
        count_label = QLabel("0")
        count_label.setObjectName("HomeCount")
        count_label.setAccessibleName(tr(title))
        count_label.hide()
        action_button = PillButton(tr(action), "ghost")
        action_button.setObjectName("HomeLibraryAction")
        action_button.setFixedHeight(hig.BUTTON_HEIGHT)
        card_header.addWidget(count_label)
        card_header.addStretch(1)
        card_header.addWidget(action_button)
        item_list = HomeListWidget()
        item_list.setObjectName("HomeList")
        item_list.setProperty("i18nSkipItems", True)
        item_list.setSpacing(0)
        item_list.hide()
        item_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        item_list.setTextElideMode(Qt.ElideRight)
        item_list.setAccessibleName(tr(title))
        item_list.setItemDelegate(
            HomeEntryDelegate(self.home_instrument_art, item_list)
        )
        empty_label = QLabel(tr(empty_message))
        empty_label.setObjectName("HomeEmptyState")
        empty_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        empty_label.setWordWrap(True)
        empty_label.setMinimumHeight(64)
        layout.addWidget(empty_label)
        layout.addWidget(item_list)
        layout.addWidget(card_header_frame)
        return card, item_list, action_button, count_label, empty_label

    @staticmethod
    def _add_home_entry(target: QListWidget, entry: HomeEntry) -> None:
        item = QListWidgetItem(f"{entry.label}\n{entry.detail}")
        item.setData(Qt.UserRole, {
            "kind": entry.kind,
            "path": str(entry.path),
            "label": entry.label,
            "project_id": entry.project_id,
            "version_index": entry.version_index,
            "version_count": entry.version_count,
            "instrument_ids": list(entry.instrument_ids),
            "performance_instrument_ids": list(entry.performance_instrument_ids),
            "instrument_count": entry.instrument_count,
            "required_players": entry.required_players,
            "ensemble_limit_exceeded": entry.exceeds_ensemble_limit,
        })
        item.setData(HOME_INSTRUMENT_IDS_ROLE, entry.performance_instrument_ids)
        tooltip_details = [entry.detail] if entry.detail else []
        if entry.instrument_ids:
            player_text = HomeEntryDelegate._ensemble_text(entry.instrument_count)
            tooltip_details.extend((
                trf("{count} 种乐器", count=entry.instrument_count),
                player_text,
            ))
            item.setData(
                Qt.ItemDataRole.AccessibleDescriptionRole,
                " · ".join(tooltip_details),
            )
        if entry.version_count > 1:
            tooltip_details.append(f"v{entry.version_index}/{entry.version_count}")
        tooltip = entry.label
        if tooltip_details:
            tooltip += "\n" + " · ".join(tooltip_details)
        item.setToolTip(tooltip)
        target.addItem(item)
        if target.currentRow() < 0:
            target.setCurrentRow(0)

    def _refresh_home(self) -> None:
        if not hasattr(self, "game_score_list"):
            return
        previous = self.home_scan_session
        if previous is not None:
            previous.cancel()
        self.home_scan_generation += 1
        generation = self.home_scan_generation
        self.game_score_list.clear()
        self.project_list.clear()
        self._update_home_action_states()
        for entry in scan_example_projects(EXAMPLE_PROJECTS_DIR):
            self._add_home_entry(self.project_list, entry)
        recent_entries: list[HomeEntry] = []
        for raw in self.config.get("recent_items", []):
            if not isinstance(raw, dict):
                continue
            path = Path(str(raw.get("path") or ""))
            kind = str(raw.get("kind") or "")
            if kind not in {"midi", "project", "bdo"} or not path.is_file():
                continue
            try:
                opened_at = float(raw.get("opened_at") or path.stat().st_mtime)
            except (OSError, TypeError, ValueError):
                continue
            label = str(raw.get("label") or path.stem)
            recent_entries.append(HomeEntry(
                kind,
                label,
                path,
                _home_timestamp(opened_at),
                opened_at,
                project_id=normalize_project_id(raw.get("project_id")),
            ))
        self._home_recent_entries = recent_entries
        self.home_scan_session = IncrementalHomeScan(
            Path(self.game_music_dir_path),
            AUTO_SAVE_DIR,
            game_limit=80,
            project_limit=400,
        )
        self._apply_home_filter()
        self._scan_home_batch(generation)

    def _quick_load_owner_id(self) -> None:
        identity = prompt_for_owner_identity(
            self, self.game_music_dir_path or default_game_music_dir()
        )
        if identity is None:
            return
        self.owner_id, character_name = identity
        if character_name:
            self.char_name = character_name
        set_owner_identity(self.config, self.owner_id, self.char_name)
        save_config(self.config)
        self._autosave_project("owner id")
        self.show_toast(
            trf("已读取 Owner ID：0x{owner_id:08x}", owner_id=self.owner_id),
            kind="success",
        )

    def _scan_home_batch(self, generation: int) -> None:
        session = self.home_scan_session
        if generation != self.home_scan_generation or session is None:
            return
        if not session.step(64):
            QTimer.singleShot(0, self, lambda: self._scan_home_batch(generation))
            return
        game_entries, project_entries = session.results()
        self.home_scan_session = None
        for entry in game_entries:
            self._add_home_entry(self.game_score_list, entry)
        project_entries.extend(self._home_recent_entries)
        for entry in merge_home_project_entries(project_entries):
            self._add_home_entry(self.project_list, entry)
        for target, message in (
            (self.game_score_list, "未找到游戏曲谱"),
            (self.project_list, "暂无项目"),
        ):
            if target.count() == 0:
                item = QListWidgetItem(tr(message))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                target.addItem(item)
        self._apply_home_filter()
        self._update_home_action_states()

    def _apply_home_filter(self, *_args) -> None:
        if not hasattr(self, "home_search"):
            return
        query = " ".join(self.home_search.text().casefold().split())
        self.home_downloads_page.set_query(query)
        for target, count_label, empty_label, empty_message in (
            (self.game_score_list, self.game_score_count,
             self.game_score_empty_label, "未找到游戏曲谱"),
            (self.project_list, self.project_count,
             self.project_empty_label, "暂无项目"),
        ):
            visible_count = 0
            preview_rows: list[int] = []
            for index in range(target.count()):
                item = target.item(index)
                data = item.data(Qt.UserRole)
                if not isinstance(data, dict):
                    item.setHidden(True)
                    continue
                searchable = f"{data.get('label', '')} {item.text()}".casefold()
                visible = not query or query in searchable
                item.setHidden(not visible)
                visible_count += int(visible)
                if visible and len(preview_rows) < 5:
                    preview_rows.append(index)
            count_label.setText(trf("共 {count} 项", count=visible_count))
            count_label.setVisible(bool(preview_rows))
            target.setVisible(bool(preview_rows))
            empty_label.setVisible(not preview_rows)
            if not preview_rows:
                empty_label.setText(tr("没有匹配的结果" if query else empty_message))
                target.setCurrentRow(-1)
                continue
            row_height = sum(target.sizeHintForRow(row) for row in preview_rows)
            target.set_preview_height(min(320, row_height))
            selected = target.currentItem()
            if selected is None or selected.isHidden():
                target.setCurrentRow(preview_rows[0])
        self._update_home_action_states()
        self._fit_home_library_page()

    def _fit_home_library_page(self) -> None:
        page = self.home_library_stack.currentWidget()
        self.home_library_stack.setMaximumHeight(page.sizeHint().height())

    def _show_home(self) -> None:
        self._stop_preview(reset_playhead=False)
        self._refresh_home()
        self._switch_main_page(self.home_page, home=True)

    def _show_workspace(self) -> None:
        self._switch_main_page(self.workspace_page, home=False)

    def _toggle_online_score_library(self) -> None:
        previous = self.page_stack.currentWidget()
        if previous is self.online_score_library_page:
            target = self._library_return_page or self.home_page
            self._switch_main_page(target, home=target is self.home_page)
            return
        if self.online_score_library_page is None:
            self.toolbar_website_btn.setChecked(False)
            choice = choose_prompt(
                self, tr("音乐库"),
                tr("您即将进入由 CN服务器 温尘梦 玩家收集数据制作搭建的公益网站"),
                (("cancel", tr("取消")), ("enter", tr("进入音乐库"))),
                default="enter",
                cancel="cancel",
            )
            if choice != "enter":
                return
            from bdo_music_composer.ui.online_score_library_qt import OnlineScoreLibraryPage

            self.online_score_library_page = OnlineScoreLibraryPage(self.page_stack)
            self.online_score_library_page.download_requested.connect(
                self.score_library_downloads.start
            )
            self.page_stack.addWidget(self.online_score_library_page)
        self._library_return_page = previous
        if previous is self.workspace_page:
            self._stop_preview(reset_playhead=False)
        self._switch_main_page(self.online_score_library_page, home=False)

    def _notify_score_library_download(self, entry: ScoreLibraryDownload) -> None:
        if entry.state == "completed":
            message = trf("下载完成 · {name}", name=entry.name)
            kind, duration = "success", 4200
        else:
            message = trf("下载失败 · {name}", name=entry.name)
            if entry.error:
                message = f"{message}\n{entry.error}"
            kind, duration = "error", 7000

        page = self.online_score_library_page
        if page is not None and self.page_stack.currentWidget() is page:
            page.show_download_notice(message, kind=kind, duration_ms=duration)
        else:
            self.show_toast(message, kind=kind, duration_ms=duration)

    def _set_library_project_shortcuts(self, browsing: bool) -> None:
        if browsing and self._library_shortcut_states is None:
            self._library_shortcut_states = tuple(
                shortcut.isEnabled() for shortcut in self._project_window_shortcuts
            )
            for shortcut in self._project_window_shortcuts:
                shortcut.setEnabled(False)
        elif not browsing and self._library_shortcut_states is not None:
            for shortcut, enabled in zip(
                self._project_window_shortcuts, self._library_shortcut_states,
            ):
                shortcut.setEnabled(enabled)
            self._library_shortcut_states = None

    def _switch_main_page(self, page: QWidget, *, home: bool) -> None:
        """Commit page and keyboard focus together; ease the navigation marker."""

        previous = self.page_stack.currentWidget()
        browsing = page is self.online_score_library_page
        leaving_library = previous is self.online_score_library_page
        anchors = {
            self.home_page: self.toolbar_home_btn,
            self.workspace_page: self.toolbar_project_btn,
            self.online_score_library_page: self.toolbar_website_btn,
        }
        motion_origin = (
            self.main_page_transition.capture(anchors.get(previous)) if previous is not page else None
        )
        if browsing or leaving_library:
            self._set_library_project_shortcuts(browsing)
        self._set_home_toolbar_mode(home, browsing=browsing)
        self.main_page_transition.commit_page(
            page, self.toolbar_website_btn if browsing else self.toolbar_home_btn,
            self.timeline if page is self.workspace_page else None,
            leaving_native_page=leaving_library, entering_native_page=browsing,
        )
        self._update_ensemble_metric()
        if motion_origin is not None:
            self.main_page_transition.animate(motion_origin, anchors.get(page))

    def _set_reference_audio_relink_required(self, required: bool) -> None:
        self.reference_audio_relink_required = required
        self.timeline.set_reference_audio_relink_required(required)

    def _is_reference_audio_relink(self, path: str) -> bool:
        return bool(self.reference_audio_relink_required and not self.reference_audio_path and path)

    def _replaces_reference_audio_review(self, path: str) -> bool:
        review_state = self.transcription_session.state
        return not self.loading_project and not self._is_reference_audio_relink(path) and bool(
            self.reference_audio_path or review_state.cache_key or self.transcription_result is not None
        )

    def _confirm_reference_audio_change(self, path: str) -> bool:
        if not self._replaces_reference_audio_review(path):
            return True
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            self.show_toast(
                tr("请先应用、撤销或清除本次暂存，再更换音频或重新分析。"),
                kind="warning",
            )
            return False
        if not self.transcription_session.state.pending_routes:
            return True
        from bdo_music_composer.ui.dialogs.composer_prompt import ComposerPrompt

        prompt = ComposerPrompt(
            editor if editor is not None and editor.isVisible() else self,
            tr("更换参考音频") if path else tr("移除参考音频"),
            tr(
                "当前仍有尚未应用的扒谱路由。更换或卸载音频会丢弃这些"
                "审阅路由；已应用的正式音符不受影响。是否继续？"
            ),
            (("cancel", tr("取消")), ("continue", tr("继续"))),
            default="cancel",
        )
        prompt.exec()
        confirmed = prompt.choice == "continue"
        prompt.deleteLater()
        return confirmed

    def _reference_audio_changed(self, path: str) -> None:
        previous_path = self.reference_audio_path
        review_state = self.transcription_session.state
        relinking_saved_audio = self._is_reference_audio_relink(path)
        if self._replaces_reference_audio_review(path):
            editor = self.active_transcription_editor
            # Invalidate queued success/failure callbacks before cancelling.
            # The worker pointer remains until its own finished signal so a
            # second analysis cannot start while the old thread is draining.
            self._invalidate_transcription_rhythm_diagnostic()
            self._rollback_cleanup_profile_transaction()
            self.transcription_analysis_coordinator.invalidate_all()
            if self.workspace_transcription_worker is not None:
                cancel = getattr(self.workspace_transcription_worker, "cancel", None)
                if callable(cancel):
                    cancel()
            if self.transcription_assist_worker is not None:
                cancel = getattr(self.transcription_assist_worker, "cancel", None)
                if callable(cancel):
                    cancel()
            self._clear_reference_timbre_analysis(cancel_worker=True)
            if editor is not None:
                editor.release_transcription_resources()
            self.transcription_assist_previous_candidates = tuple(
                self.transcription_session.candidates
            )
            self.transcription_assist_review = (
                isolate_assist_review_for_audio(
                    self.transcription_assist_review,
                    "",
                )
            )
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.transcription_result = None
            self.transcription_session = TranscriptionSession(
                state=TranscriptionSessionState(
                    region=review_state.region,
                    analysis_mode=review_state.analysis_mode,
                    sensitivity=review_state.sensitivity,
                    cleanup_profile=review_state.cleanup_profile,
                )
            )
            self._clear_transcription_review_history()
        self.reference_audio_path = path
        if path and path != previous_path and not self.loading_project:
            self._record_usage_feature("reference_audio")
        self._set_reference_audio_relink_required(False)
        self._reference_bpm_audio_changed(path)
        self._refresh_transcription_workspace()
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio", immediate=True)
        if (
            relinking_saved_audio
            and review_state.cache_key
            and not self.transcription_session.candidates
            and self.workspace_transcription_worker is None
        ):
            # The cache worker validates the newly linked audio fingerprint
            # before restoring review state; relinking itself must not erase it.
            QTimer.singleShot(0, self._restore_cached_transcription)
        self._sync_preview_state()

    def _reference_volume_changed(self, _volume: int) -> None:
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio volume")

    def _reference_offset_changed(self, offset_ms: float) -> None:
        editor = self.active_transcription_editor
        if (
            editor is not None
            and editor.has_transcription_staging()
            and not math.isclose(
                float(offset_ms),
                float(self.reference_audio_offset_ms),
                abs_tol=0.001,
            )
        ):
            self.show_toast(
                tr("请先应用、撤销或清除本次暂存，再修改音频对齐。"),
                kind="warning",
            )
            self.reference_audio.set_project_offset_ms(
                self.reference_audio_offset_ms,
                notify=False,
            )
            return
        self._invalidate_transcription_rhythm_diagnostic()
        self.reference_audio_offset_ms = float(offset_ms)
        self._reposition_reference_after_alignment()
        self._refresh_transcription_workspace()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(harmony_only=True)
        if self.tracks and not self.loading_project:
            self._autosave_project("reference audio offset")

    def _set_reference_alignment(
        self,
        offset_ms: float,
        beat_origin_ms: float,
        *,
        autosave: bool = False,
    ) -> None:
        self._invalidate_transcription_rhythm_diagnostic()
        self.reference_audio_offset_ms = float(offset_ms)
        self.beat_origin_ms = float(beat_origin_ms)
        self.reference_audio.set_project_offset_ms(
            self.reference_audio_offset_ms,
            notify=False,
        )
        if hasattr(self, "timeline"):
            self.timeline.set_musical_grid(
                self.bpm_override or self.bpm,
                self.time_sig,
                self.beat_origin_ms,
            )
        self._refresh_transcription_workspace()
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(harmony_only=True)
        if autosave and self.tracks and not self.loading_project:
            self._autosave_project("reference alignment", immediate=True)

    def _reference_playback_state_changed(
        self, _state: QMediaPlayer.PlaybackState,
    ) -> None:
        self._sync_preview_state()

    def _set_home_toolbar_mode(self, home: bool, *, browsing: bool = False) -> None:
        editing = not (home or browsing)
        self._toolbar_navigation_compact = editing
        for widget in (
            self.document_title_group,
            self.toolbar_playback_group,
            self.convert_button,
        ):
            widget.setVisible(editing)
        self.toolbar_home_btn.setChecked(home)
        self.toolbar_website_btn.setChecked(browsing)
        if home:
            self.toolbar_home_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        elif browsing:
            self.toolbar_website_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_convert_button_enabled(editing=editing)
        self._apply_responsive_density()

    def _sync_convert_button_enabled(self, *, editing: bool | None = None) -> None:
        if editing is None:
            editing = self.page_stack.currentWidget() is self.workspace_page
        self.convert_button.setEnabled(editing and self.worker is None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toolbar_home_btn"):
            self._apply_responsive_density()

    def nativeEvent(self, event_type, message):
        chrome = getattr(self, "window_chrome", None)
        if chrome is not None and event_type == b"windows_generic_MSG":
            result = chrome.native_event(message)
            if result is not None:
                return True, result
        return super().nativeEvent(event_type, message)

    def _apply_home_responsive_density(self) -> None:
        if not hasattr(self, "home_sidebar"):
            return
        width = self.width()
        sidebar_width = max(600, min(704, round(width * 0.54)))
        margins = self.home_sidebar.layout().contentsMargins()
        action_space = sidebar_width - margins.left() - margins.right() - 2 * hig.ITEM_GAP
        # Keep the three action columns equal after Qt rounds to whole pixels.
        sidebar_width -= action_space % 3
        self.home_sidebar.setFixedWidth(sidebar_width)
        self._fit_home_library_page()

    def _apply_responsive_density(self) -> None:
        """Keep both command rails usable at the supported narrow width."""

        self._apply_home_responsive_density()

        if not hasattr(self, "workbench"):
            return
        self.document_title_group.setMinimumWidth(0 if self.width() < 1280 else 96)
        self._sync_caption_button_widths()
        self._set_global_bpm_compact(True)

    def _sync_caption_button_widths(self) -> None:
        navigation = (
            (self.toolbar_home_btn, tr("主页")),
            (self.toolbar_project_btn, tr("项目")),
            (self.toolbar_website_btn, tr("音乐库")),
        )
        compact = self._toolbar_navigation_compact
        for button, label in navigation:
            text = "" if compact else label
            if button.text() != text:
                button.setText(text)
                if bool(button.property("captionIconOnly")) != compact:
                    button.setProperty("captionIconOnly", compact)
                    style = button.style()
                    style.unpolish(button)
                    style.polish(button)
        width = (
            hig.CAPTION_BUTTON_HEIGHT + hig.ITEM_GAP
            if compact else max(button.sizeHint().width() for button, _ in navigation)
        )
        for button, _ in navigation:
            button.setFixedWidth(width)
        export_button = self.convert_button
        export_button.setFixedWidth(max(108, export_button.sizeHint().width()))

    def _new_project(self) -> None:
        name, accepted = prompt_text(
            self,
            tr("新建项目"),
            tr("项目名称"),
            tr("未命名项目"),
        )
        if accepted and name.strip():
            self._create_new_project(name)

    def _reset_new_score_conversion_defaults(self) -> None:
        """Restore saved preferences or the defaults for a newly authored score."""

        preferences = ConversionSettings.from_preferences(
            self.config.get("conversion_settings")
        )
        self._set_conversion_settings(
            # A velocity recipe is meaningful only while importing existing
            # notes.  A blank authored score has nothing to materialize and
            # must never carry a deferred export transform.
            preferences.with_updates(
                velocity_mode=VELOCITY_MODE_PRESERVE
            ),
            preserve_pitch_overrides=False,
        )

    def _create_new_project(self, name: str) -> None:
        project_name = safe_filename(name.strip(), tr("未命名项目"))
        stamp = time.strftime("%Y%m%d_%H%M%S")
        project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}"
        suffix = 2
        while project_dir.exists():
            project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}_{suffix}"
            suffix += 1

        loading_generation = self.project_lifecycle_controller.begin_loading(
            "new project"
        )
        try:
            self._stop_preview()
            self.project_commands.clear()
            self._close_all_note_editors()
            self.reference_layer_settings = normalize_reference_layer_settings(
                DEFAULT_REFERENCE_LAYER_SETTINGS
            )
            self.transcription_session = TranscriptionSession()
            self.transcription_result = None
            self.transcription_assist_review = (
                TranscriptionAssistReviewState()
            )
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self._clear_reference_timbre_analysis(cancel_worker=True)
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self._clear_transcription_review_history()
            self._clear_track_selection()
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(self.ui_preference_binding.reference_volume_percent, notify=False)
            self._set_reference_alignment(0.0, 0.0)
            self.reference_audio_path = ""
            self._set_reference_audio_relink_required(False)
            self.source_format = "project"
            self._reset_project_timeline_metadata()
            self.bdo_source_document = None
            self.midi_path = ""
            self.project_id = new_project_id()
            self.autosave_project_dir = project_dir
            self.autosave_source_copy = None
            self.owner_id, configured_character_name = owner_identity(self.config)
            self.char_name = configured_character_name or self.char_name
            self.bpm = 120
            self.time_sig = 4
            self.time_sig_denominator = 4
            self.tempo_changes = 1
            self.lyric_events = []
            self._reset_new_score_conversion_defaults()
            self._reset_master_effects()
            instrument_id = gm_to_bdo_instrument(0, False)
            instrument_name = _ui_bdo_instrument_name(instrument_id)
            self.tracks = [
                TrackState(
                    track_id=0,
                    notes=[],
                    gm_program=0,
                    is_percussion=False,
                    display_name=trf(
                        "新建轨道 {number} · {instrument}",
                        number=1,
                        instrument=instrument_name,
                    ),
                    bdo_instrument_id=instrument_id,
                    color=TRACK_COLORS[0],
                    effect_settings_placeholder={
                        "track_effects_enabled": False,
                        "note_effects_reserved": True,
                    },
                    arrangement_clips=[
                        default_empty_clip(0, duration_ms=2_000.0)
                    ],
                )
            ]
            self.file_label.setProperty("i18nSkip", False)
            self.file_label.setProperty("i18nSkipText", False)
            self.file_label.setText(
                trf("{project} · 空白项目", project=project_name)
            )
            self.output_name.setText(project_name)
            self._refresh_tracks()
            self._reset_timeline_position()
            self._select_track(self.tracks[0])
            self._sync_preview_state()
        finally:
            self.project_lifecycle_controller.finish_loading(
                loading_generation
            )

        self._autosave_project("new project", immediate=True)
        self._schedule_timeline_validation_refresh()
        project_path = project_dir / "project.json"
        self._record_recent("project", project_path, project_name)
        self._show_workspace()
        self.status_label.setText(tr("空白项目已创建"))
        self.show_toast(
            tr("空白项目已创建；双击轨道即可添加音符。"),
            kind="success",
        )

    def show_toast(
        self,
        text: str,
        kind: str = "info",
        duration_ms: int = 2600,
    ) -> GlobalToast:
        return show_global_toast(self, text, kind=kind, duration_ms=duration_ms)

    def _open_game_music_directory(self) -> None:
        directory = Path(self.game_music_dir_path)
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _open_selected_home_item(self, target: QListWidget) -> None:
        item = target.currentItem()
        if item is None or not isinstance(item.data(Qt.UserRole), dict):
            self.show_toast(tr("请先选择一个项目或曲谱"))
            return
        self._open_home_item(item)

    def _show_project_context_menu(self, position) -> None:
        item = self.project_list.itemAt(position)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        menu = QMenu(self.project_list)
        menu.addAction(tr("打开工程"), lambda: self._open_home_item(item))
        if str(data.get("kind") or "") == "project":
            menu.addAction(tr("重命名项目"), lambda: self._rename_home_project(item))
            menu.addSeparator()
            menu.addAction(tr("移到回收站"), lambda: self._trash_home_project(item))
        menu.exec(self.project_list.mapToGlobal(position))

    def _rename_home_project(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        project_path = Path(str(data.get("path") or ""))
        if not project_path.is_file():
            return
        old_name = str(data.get("label") or project_path.parent.name)
        new_name, accepted = prompt_text(
            self,
            tr("重命名项目"),
            tr("项目名称"),
            old_name,
        )
        new_name = new_name.strip()
        if not accepted or not new_name or new_name == old_name:
            return
        try:
            current_project = (
                self.autosave_project_dir is not None
                and self.autosave_project_dir.resolve() == project_path.parent.resolve()
            )
        except OSError:
            current_project = False
        if current_project and not self._wait_for_autosave_idle():
            QMessageBox.warning(
                self,
                tr("重命名项目失败"),
                tr("仍有项目写入正在进行，请稍后重试。"),
            )
            return
        try:
            project_id = rename_project(project_path, new_name)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("重命名项目失败"),
                trf("无法重命名项目：{error}", error=exc),
            )
            return
        if current_project:
            self.project_id = project_id
            self.output_name.setText(new_name)
        for recent in self.config.get("recent_items", []):
            if not isinstance(recent, dict):
                continue
            try:
                same_path = Path(str(recent.get("path") or "")).resolve() == project_path.resolve()
            except OSError:
                same_path = False
            if same_path:
                recent["label"] = new_name
                recent["project_id"] = project_id
        save_config(self.config)
        self._refresh_home()
        self.show_toast(tr("项目已重命名"), kind="success")

    def _trash_home_project(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        project_path = Path(str(data.get("path") or ""))
        project_dir = project_path.parent
        try:
            project_dir.resolve().relative_to(AUTO_SAVE_DIR.resolve())
        except (OSError, ValueError):
            QMessageBox.warning(
                self,
                tr("无法删除项目"),
                tr("只能把自动保存目录中的项目移到回收站。"),
            )
            return
        try:
            is_current = (
                self.autosave_project_dir is not None
                and self.autosave_project_dir.resolve() == project_dir.resolve()
            )
        except OSError:
            is_current = False
        if is_current:
            QMessageBox.warning(
                self,
                tr("无法删除项目"),
                tr("当前打开的项目不能删除；请先打开其他项目。"),
            )
            return
        label = str(data.get("label") or project_dir.name)
        answer = QMessageBox.question(
            self,
            tr("移到回收站"),
            trf("要把项目“{project}”移到回收站吗？", project=label),
        )
        if answer != QMessageBox.Yes:
            return
        if not QFile.moveToTrash(str(project_dir)):
            QMessageBox.warning(
                self,
                tr("无法删除项目"),
                tr("系统未能把项目移到回收站。"),
            )
            return
        kept_recents = []
        for recent in self.config.get("recent_items", []):
            if not isinstance(recent, dict):
                continue
            try:
                recent_path = Path(str(recent.get("path") or "")).resolve()
                recent_path.relative_to(project_dir.resolve())
            except (OSError, ValueError):
                kept_recents.append(recent)
        self.config["recent_items"] = kept_recents
        save_config(self.config)
        self._refresh_home()
        self.show_toast(tr("项目已移到回收站"), kind="success")

    def _open_home_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        path = Path(str(data.get("path") or ""))
        kind = str(data.get("kind") or "")
        if kind in {"project", "example"} and path.is_file():
            self._load_project(path)
        elif kind == "midi" and path.is_file():
            self._open_midi_path(path)
        elif kind in {"game", "bdo"} and path.is_file():
            self._open_bdo_score_path(path)

    def _record_recent(self, kind: str, path: Path, label: str) -> None:
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path)
        recent = [
            item for item in self.config.get("recent_items", [])
            if isinstance(item, dict) and str(item.get("path") or "").casefold() != normalized.casefold()
        ]
        recent.insert(0, {
            "kind": kind,
            "path": normalized,
            "label": label,
            "opened_at": time.time(),
            "project_id": self.project_id if kind == "project" else "",
        })
        self.config["recent_items"] = recent[:12]
        try:
            save_config(self.config)
        except OSError:
            # A recent-item preference is independent of opening the score.
            append_crash_log("Recent list save failed", traceback.format_exc())

    def _build_timeline_panel(self) -> QWidget:
        workspace = QWidget()
        workspace.setObjectName("TimelineWorkspace")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        (
            self.timeline_edit_tools,
            self.timeline_marquee_tool, self.timeline_select_tool,
            self.timeline_razor_tool, self.timeline_snap_tool,
        ) = build_arrangement_tool_buttons(self)
        self.timeline_zoom_label = QLabel(tr("缩放"))
        self.timeline_zoom_label.setObjectName("TimelineControlLabel")
        self.timeline_zoom = QSlider(Qt.Horizontal)
        self.timeline_zoom.setRange(25, 3200)
        self.timeline_zoom.setValue(100)
        self.timeline_zoom.setFixedWidth(104)
        self.timeline_zoom.setToolTip(tr("时间轴缩放"))
        self.timeline_zoom.setAccessibleName(tr("时间轴缩放"))
        self.timeline_zoom_label.setBuddy(self.timeline_zoom)
        self.timeline_pan_label = QLabel(tr("位置"))
        self.timeline_pan_label.setObjectName("TimelineControlLabel")
        self.timeline_pan = QSlider(Qt.Horizontal)
        self.timeline_pan.setRange(0, 1000)
        self.timeline_pan.setValue(0)
        self.timeline_pan.setFixedWidth(112)
        self.timeline_pan.setToolTip(tr("时间轴位置"))
        self.timeline_pan.setAccessibleName(tr("时间轴位置"))
        self.timeline_pan_label.setBuddy(self.timeline_pan)
        global_gain_control = self._build_global_velocity_gain_control()

        self.timeline_mix_menu, self.timeline_view_button = (
            build_timeline_popup_buttons(
                self,
                global_gain_control,
                self.timeline_zoom_label,
                self.timeline_zoom,
                self.timeline_pan_label,
                self.timeline_pan,
            )
        )
        self.timeline = TimelineCanvas()
        self.timeline.setObjectName("TimelineCanvas")
        self.timeline.set_instrument_art_dir(self.instrument_art_dir)
        self.timeline.fit_width_requested.connect(self._fit_timeline)
        self.timeline.changed.connect(self._on_track_changed)
        self.timeline.viewport_changed.connect(lambda: sync_timeline_viewport_controls(self))
        self.timeline.track_state_changed.connect(self._on_track_filter_changed)
        self.timeline.game_volume_committed.connect(
            self._on_game_instrument_volume_committed
        )
        self.timeline.instrument_changed.connect(self._on_track_instrument_changed)
        self.timeline.mixer_unify_requested.connect(
            self._unify_game_instrument_mix
        )
        self.timeline.merge_track_requested.connect(
            self._merge_same_instrument_track
        )
        self.timeline.create_track_requested.connect(self._create_track)
        self.timeline.move_track_requested.connect(self._move_track)
        self.timeline.delete_track_requested.connect(
            self._delete_requested_track
        )
        self._connect_arrangement_action_signals()
        self.timeline.clear_solo_requested.connect(self._clear_solo)
        self.timeline.unmute_all_requested.connect(self._unmute_all)
        self.timeline.selected.connect(self._select_track)
        self.timeline.selection_scope_changed.connect(
            self._sync_selection_velocity_percent
        )
        self.timeline.effects_requested.connect(self._show_effects_placeholder)
        self.timeline.pitch_requested.connect(self._show_track_pitch_dialog)
        self.timeline.midi_tools_requested.connect(self._open_midi_tool)
        self.timeline.clip_velocity_base_requested.connect(
            self._show_clip_velocity_base_dialog
        )
        self.timeline.note_editor_requested.connect(self._open_note_editor)
        self.timeline.clip_note_editor_requested.connect(
            self._open_clip_note_editor
        )
        self.timeline.velocity_curve_committed.connect(self._commit_timeline_velocity_curve)
        self.timeline.clip_edit_requested.connect(self._commit_timeline_clip_edit)
        self.timeline.clip_create_requested.connect(self._create_timeline_clip)
        self.timeline.clip_split_requested.connect(self._split_timeline_clip)
        self.timeline.clip_copy_requested.connect(self._copy_timeline_clip)
        self.timeline.clip_paste_requested.connect(self._paste_timeline_clip)
        self.timeline.clip_delete_requested.connect(self._delete_timeline_clip)
        self.timeline.clips_delete_requested.connect(self._delete_timeline_clips)
        self.timeline.clips_move_requested.connect(
            self._move_timeline_clips
        )
        self.timeline.marker_edit_requested.connect(self._edit_timeline_marker)
        self.timeline.group_control_requested.connect(self._apply_arrangement_group_control)
        self.timeline_snap_tool.toggled.connect(self.timeline.set_snap_enabled)
        self.timeline.set_snap_enabled(self.timeline_snap_tool.isChecked())
        bind_arrangement_tool_buttons(
            self.timeline, self.timeline_marquee_tool,
            self.timeline_select_tool, self.timeline_razor_tool,
        )
        self.timeline.seek_requested.connect(self._seek_preview)
        self.timeline.time_range_changed.connect(self._timeline_range_changed)
        self.timeline_zoom.valueChanged.connect(self.timeline.set_zoom_percent)
        self.timeline_pan.valueChanged.connect(self.timeline.set_pan_percent)
        timeline_body = QFrame()
        timeline_body.setObjectName("TimelineBody")
        timeline_body_layout = QHBoxLayout(timeline_body)
        timeline_body_layout.setContentsMargins(0, 0, 0, 0)
        timeline_body_layout.setSpacing(0)
        timeline_body_layout.addWidget(self.timeline, stretch=1)
        layout.addWidget(timeline_body, stretch=1)
        self.reference_audio = ReferenceAudioController(self)
        self.reference_audio.before_file_change = self._confirm_reference_audio_change
        self.reference_audio.set_project_offset_ms(
            self.reference_audio_offset_ms,
            notify=False,
        )
        self.reference_audio.file_changed.connect(self._reference_audio_changed)
        self.reference_audio.volume_changed.connect(self._reference_volume_changed)
        self.reference_audio.offset_changed.connect(self._reference_offset_changed)
        self.reference_audio.player.playbackStateChanged.connect(
            self._reference_playback_state_changed
        )
        self.timeline.set_reference_audio(self.reference_audio)
        self.reference_audio.timeline_changed.connect(self._extend_arrangement_clock_for_reference)
        self.timeline.reference_audio_offset_requested.connect(lambda: edit_reference_audio_offset(self))
        return workspace

    def _build_preview_transport(self) -> QFrame:
        group = QFrame()
        group.setObjectName("TransportGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.CONTROL_GAP)
        self.play_button = PillButton("", "ghost", FluentSymbol.PLAY)
        self.play_button.setObjectName("TransportPlayButton")
        self.play_button.clicked.connect(self._play_preview)
        self.pause_button = PillButton("", "ghost", FluentSymbol.PAUSE)
        self.pause_button.clicked.connect(self._pause_preview)
        self.stop_button = PillButton("", "ghost", FluentSymbol.STOP)
        self.stop_button.clicked.connect(lambda: self._stop_preview(reset_playhead=True))
        for button in (self.play_button, self.pause_button, self.stop_button):
            button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
            layout.addWidget(button)
        for button, label in ((self.pause_button, "暂停"), (self.stop_button, "停止")):
            button.setAccessibleName(tr(label))
            button.setToolTip(tr(label))
        self.timeline_loop_box = PillButton("", "ghost")
        self.timeline_loop_box.setObjectName("TransportLoopButton")
        set_fluent_symbol(
            self.timeline_loop_box, FluentSymbol.REPEAT, checked_symbol=FluentSymbol.REPEAT_ACTIVE,
        )
        self.timeline_loop_box.setCheckable(True)
        self.timeline_loop_box.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        self.timeline_loop_box.setAccessibleName(tr("循环区间"))
        self.timeline_loop_box.setToolTip(tr("循环播放 A–B 时间区间"))
        layout.addWidget(self.timeline_loop_box)
        return group

    def _build_performance_strip(self) -> QWidget:
        """Compact process/audio telemetry below the multitrack timeline."""

        strip = QFrame()
        strip.setObjectName("PerformanceStrip")
        strip.setFixedHeight(30)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(hig.GROUP_GAP, 2, hig.GROUP_GAP, 2)
        layout.setSpacing(hig.PANEL_PADDING)
        self.timeline_meta = ElidedLabel(tr("等待 MIDI"), maximum_hint_width=130)
        self.timeline_meta.setObjectName("TimelineMeta")
        self.process_cpu_label = QLabel("CPU --")
        self.process_cpu_label.setObjectName("PerformanceMetric")
        self.process_ram_label = QLabel("RAM --")
        self.process_ram_label.setObjectName("PerformanceMetric")
        self.ensemble_metric_label = QLabel(trf(
            "乐器 {count} · {players}/{limit} 人",
            count=0,
            players=0,
            limit=BDO_ENSEMBLE_PLAYER_LIMIT,
        ))
        self.ensemble_metric_label.setObjectName("EnsembleMetric")
        self.audio_load_label = QLabel(tr("音频 --"))
        self.audio_load_label.setObjectName("PerformanceMetric")
        self.active_voice_label = QLabel(tr("声部 --"))
        self.active_voice_label.setObjectName("PerformanceMetric")
        self.project_note_status = ElidedLabel(tr("未选择轨道"))
        self.project_note_status.setObjectName("ProjectMusicStatus")
        self.project_note_status.setTextFormat(Qt.PlainText)
        self.project_note_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.timeline_meta)
        layout.addWidget(self.ensemble_metric_label)
        layout.addStretch(1)
        for widget in (
            self.project_note_status, self.audio_load_label, self.active_voice_label,
            self.process_cpu_label, self.process_ram_label,
        ):
            widget.setParent(strip)
            widget.hide()
        return strip

    def _show_runtime_status(self) -> None:
        self._update_process_metrics()
        details = "\n".join(label.text() for label in (
            self.process_cpu_label, self.process_ram_label,
            self.audio_load_label, self.active_voice_label,
        ))
        choose_prompt(
            self, tr("运行状态"), details, (("confirm", tr("确定")),),
            default="confirm", cancel="confirm",
        )

    def _update_process_metrics(self) -> None:
        if not hasattr(self, "process_cpu_label"):
            return
        metrics = self.process_metrics_sampler.sample()
        self.process_cpu_label.setText(f"CPU {metrics.cpu_percent:.1f}%")
        self.process_ram_label.setText(f"RAM {metrics.working_set_mib:.0f} MB")
        audio_load = 0.0
        active_voices = 0
        underruns = self.last_reported_underruns
        if self.realtime_preview_active:
            try:
                status = self.realtime_audio.get_status()
            except AudioEngineError:
                status = None
            if status is not None:
                audio_load = max(0.0, float(status.render_p95_load))
                active_voices = max(0, int(status.active_voices))
                underruns = max(underruns, int(status.underruns))
        self.audio_load_label.setText(
            trf("音频 {load:.0f}% · XRUN {count}", load=audio_load * 100.0, count=underruns)
        )
        self.active_voice_label.setText(trf("声部 {count}", count=active_voices))

    def _active_ensemble_instrument_ids(self) -> tuple[int, ...]:
        return unique_performance_instrument_ids(
            serialized_bdo_instrument_id(track)
            for track in formal_score_tracks(self.tracks)
            if track.notes
        )

    def _update_ensemble_metric(self) -> None:
        instrument_count = len(self._active_ensemble_instrument_ids())
        self._update_toolbar_ensemble_badge(instrument_count)
        if not hasattr(self, "ensemble_metric_label"):
            return
        over_limit = instrument_count > BDO_ENSEMBLE_PLAYER_LIMIT
        if over_limit:
            text = trf(
                "乐器 {count} · 超过 {limit} 人",
                count=instrument_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        else:
            text = trf(
                "乐器 {count} · {players}/{limit} 人",
                count=instrument_count,
                players=instrument_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        self.ensemble_metric_label.setText(text)
        state = "over" if over_limit else "ok"
        if self.ensemble_metric_label.property("ensembleState") != state:
            self.ensemble_metric_label.setProperty("ensembleState", state)
            style = self.ensemble_metric_label.style()
            style.unpolish(self.ensemble_metric_label)
            style.polish(self.ensemble_metric_label)
        self.ensemble_metric_label.setToolTip(tr(
            "按当前参与演奏且含音符的轨道统计；同一实体乐器只计一次"
        ))

    def _update_toolbar_ensemble_badge(
        self,
        workspace_player_count: int | None = None,
    ) -> None:
        if not hasattr(self, "ensemble_capacity_badge"):
            return
        on_home = (
            hasattr(self, "page_stack")
            and hasattr(self, "home_page")
            and self.page_stack.currentWidget() is self.home_page
        )
        if on_home and hasattr(self, "home_library_stack"):
            page_index = self.home_library_stack.currentIndex()
            target = {0: self.project_list, 1: self.game_score_list}.get(page_index)
            item = target.currentItem() if target is not None else None
            data = item.data(Qt.UserRole) if item is not None else None
            if isinstance(data, dict):
                try:
                    player_count = max(
                        0,
                        int(data.get("required_players", 0)),
                    )
                except (TypeError, ValueError, OverflowError):
                    player_count = 0
                self.ensemble_capacity_badge.set_player_count(
                    player_count,
                    item.toolTip() if item is not None else "",
                )
                return
            self.ensemble_capacity_badge.set_player_count(0)
            return
        player_count = (
            len(self._active_ensemble_instrument_ids())
            if workspace_player_count is None
            else max(0, int(workspace_player_count))
        )
        self.ensemble_capacity_badge.set_player_count(player_count)

    def _open_transcription_mode(self) -> None:
        melodic_tracks = [
            track
            for track in self.tracks
            if not track.is_percussion
            and int(track.bdo_instrument_id) != 0x0D
        ]
        if not melodic_tracks:
            QMessageBox.information(
                self,
                tr("音乐参考"),
                tr("当前工程没有可用于音乐参考的旋律乐器轨，请先新建乐器轨。"),
            )
            return
        target = (
            self.selected_track
            if self.selected_track in melodic_tracks
            else None
        )
        if target is None:
            labels = [
                (
                    f"{track.display_name}  [#{track.track_id} · "
                    f"{_ui_bdo_instrument_name(int(track.bdo_instrument_id))}]"
                )
                for track in melodic_tracks
            ]
            tracks_by_label = dict(zip(labels, melodic_tracks, strict=True))
            selected_label, accepted = choose_item(
                self,
                tr("选择音乐参考目标轨"),
                tr("请选择要打开的旋律乐器轨："),
                labels,
            )
            if not accepted:
                return
            target = tracks_by_label.get(selected_label)
            if target is None:
                return
        self._open_note_editor(target, transcription_mode=True)

    def _effective_track_transpose(self, track: TrackState) -> int:
        return self._pitch_transform_plan.effective_track_semitones(
            track
        )

    def _project_tracks_for_preview(
        self,
        tracks: Sequence[TrackState],
    ) -> list[TrackState]:
        """Freeze pitch-projected copies before asynchronous audio preload."""

        return [
            replace(
                track,
                is_percussion=track_uses_percussion_pitch_semantics(track),
                notes=list(
                    transpose_notes(
                        track.notes,
                        self._effective_track_transpose(track),
                    )
                ),
            )
            for track in tracks
        ]

    def _candidate_invalid_for_track(
        self,
        candidate: TranscriptionCandidate,
        track: TrackState | None,
    ) -> bool:
        if track is None:
            return True
        supported = game_supported_pitches(
            int(track.bdo_instrument_id), track.marnian_synth_mode
        )
        return candidate_is_invalid_for_track(
            candidate,
            reference_audio_offset_ms=self.reference_audio_offset_ms,
            is_percussion=track.is_percussion,
            instrument_id=track.bdo_instrument_id,
            transpose=self._effective_track_transpose(track),
            supported_pitches=supported,
        )

    def _refresh_transcription_workspace(self) -> None:
        """Refresh the only transcription view: the active note editor.

        The method name is retained as an internal compatibility seam while
        older callers are migrated.  It no longer owns or refreshes a main-page
        transcription workspace.
        """

        state = self.transcription_session.state
        self.timeline.set_time_range(
            *(state.region if state.region is not None else (None, None))
        )
        editor = self.active_transcription_editor
        if editor is None:
            return
        editor.beat_origin_ms = float(self.beat_origin_ms)
        editor.refresh_transcription_projection()
        editor.set_transcription_analysis_ui(
            self.transcription_analysis_busy,
            self.transcription_analysis_progress,
            status=self._transcription_ui_status_spec,
        )
        self._sync_transcription_rhythm_editor(editor)

    def _refresh_transcription_action_state(self) -> None:
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()

    def _transcription_selection_changed(
        self, candidate_ids: Iterable[str],
    ) -> None:
        self.transcription_session.set_selection(candidate_ids)
        self._activate_voice_group_for_candidates(candidate_ids)
        self._refresh_transcription_workspace()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription selection")

    def _set_transcription_region(
        self, value: tuple[float, float] | None,
    ) -> None:
        if value is None:
            self.transcription_session.clear_region()
        else:
            self.transcription_session.set_region(value[0], value[1])
        region = self.transcription_session.state.region
        self.timeline.set_time_range(
            *(region if region is not None else (None, None))
        )
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription A-B")

    def _timeline_range_changed(
        self, value: tuple[float, float] | None,
    ) -> None:
        self._set_transcription_region(value)

    def _transcription_sensitivity_changed(self, sensitivity: str) -> None:
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_sensitivity(
                self.transcription_session.state.sensitivity
            )
            return
        self.transcription_session.set_sensitivity(sensitivity)
        self._refresh_transcription_action_state()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription sensitivity")
        if (
            self.transcription_session.state.cache_key
            and self.workspace_transcription_worker is None
        ):
            self._stop_preview(reset_playhead=False)
            self._restore_cached_transcription()

    def _transcription_cleanup_profile_changed(
        self,
        cleanup_profile: str,
    ) -> None:
        previous = self.transcription_session.state.cleanup_profile
        requested = str(cleanup_profile)
        if requested == previous:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_cleanup_profile(previous)
            return
        if self.workspace_transcription_worker is not None:
            if editor is not None:
                editor.transcription_panel.set_cleanup_profile(previous)
            return
        if self.transcription_session.state.cache_key:
            self._stop_preview(reset_playhead=False)
            profile_label = _transcription_cleanup_ui_labels(requested, None)[0]
            try:
                generation = self._restore_cached_transcription(
                    status=trf(
                        "正在按“{profile}”从缓存证据重新解码；"
                        "不会再次运行模型。",
                        profile=profile_label,
                    ),
                    cleanup_profile=requested,
                    rollback_cleanup_profile=previous,
                )
            except Exception:
                append_crash_log(
                    "Transcription cleanup profile switch failed",
                    traceback.format_exc(),
                )
                self._rollback_cleanup_profile_transaction()
                generation = None
                self._set_transcription_status(
                    tr("碎音处理切换失败；已恢复原档位。")
                )
            if generation is None and editor is not None:
                editor.transcription_panel.set_cleanup_profile(previous)
            return
        self.transcription_session.set_cleanup_profile(requested)
        self._refresh_transcription_action_state()
        if self.tracks and not self.loading_project:
            self._autosave_project("transcription fragment cleanup")
        if editor is not None:
            self._set_transcription_status(
                trf(
                    "已选择“{profile}”；下次分析将使用该档位。",
                    profile=_transcription_cleanup_ui_labels(requested, None)[0],
                )
            )

    def _select_suspected_transcription_fragments(self) -> None:
        plan = self.transcription_review_controller.plan_fragment_selection(
            self.transcription_session,
            reference_audio_offset_ms=self.reference_audio_offset_ms,
        )
        self._transcription_selection_changed(plan.candidate_ids)
        self._set_transcription_status(
            trf(
                "已选择 {count} 个疑似碎音候选",
                count=len(plan.candidate_ids),
            )
        )

    def _transcription_analysis_mode_changed(
        self, analysis_mode: str,
    ) -> None:
        previous = self.transcription_session.state
        if str(analysis_mode) == previous.analysis_mode:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            editor.transcription_panel.set_analysis_mode(
                previous.analysis_mode
            )
            return
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        self._invalidate_transcription_rhythm_diagnostic()
        self.transcription_session = TranscriptionSession(
            state=TranscriptionSessionState(
                region=previous.region,
                analysis_mode=str(analysis_mode),
                sensitivity=previous.sensitivity,
                cleanup_profile=previous.cleanup_profile,
            )
        )
        self.transcription_result = None
        self.automatic_harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.harmony_analysis = None
        self.instrument_match_analysis = None
        self._clear_reference_timbre_analysis(cancel_worker=True)
        self.transcription_group_timbre_profiles = None
        self.transcription_group_timbre_revision = ""
        self.transcription_assist_review = TranscriptionAssistReviewState()
        self._clear_transcription_review_history()
        if editor is not None:
            editor.release_transcription_resources()
        self._refresh_transcription_workspace()
        self._set_transcription_status(
            tr("识别模式已更改；请重新分析整首。")
        )
        if self.tracks and not self.loading_project:
            self._autosave_project(
                "transcription analysis mode",
                immediate=True,
            )

    def _reject_transcription_candidates(self) -> None:
        plan = self.transcription_review_controller.plan_reject_candidates(
            self.transcription_session,
            reference_audio_offset_ms=self.reference_audio_offset_ms,
        )
        rejected = self.transcription_session.reject(plan.candidate_ids)
        if rejected:
            self._invalidate_transcription_rhythm_diagnostic()
        self._refresh_transcription_workspace()
        if rejected:
            self._record_transcription_review_action("session")
            self._autosave_project("transcription reject")
            self._set_transcription_status(
                trf("已拒绝 {count} 个候选", count=len(rejected))
            )

    def _restore_transcription_candidates(self) -> None:
        plan = self.transcription_review_controller.plan_restore_candidates(
            self.transcription_session,
            reference_audio_offset_ms=self.reference_audio_offset_ms,
        )
        restored = self.transcription_session.restore_rejected(
            plan.candidate_ids
        )
        if restored:
            self._invalidate_transcription_rhythm_diagnostic()
        self._refresh_transcription_workspace()
        if restored:
            self._record_transcription_review_action("session")
            self._autosave_project("transcription restore")
            self._set_transcription_status(
                trf("已恢复 {count} 个候选", count=len(restored))
            )

    def _undo_transcription_review(self) -> None:
        kind = self.transcription_review_controller.take_undo_action()
        changed = False
        if kind == "assist":
            changed, review = self.transcription_review_controller.undo_assist(
                self.transcription_assist_review
            )
            if changed:
                self.transcription_assist_review = review
        else:
            changed = self.transcription_session.undo()
        if not changed:
            return
        if kind == "session":
            self._invalidate_transcription_rhythm_diagnostic()
        self.transcription_review_controller.complete_undo(kind)
        self._reapply_transcription_assist_review()
        self._refresh_transcription_workspace()
        self._start_transcription_assist_analysis()
        self._autosave_project(
            "transcription review undo",
            immediate=True,
        )

    def _redo_transcription_review(self) -> None:
        kind = self.transcription_review_controller.take_redo_action()
        changed = False
        if kind == "assist":
            changed, review = self.transcription_review_controller.redo_assist(
                self.transcription_assist_review
            )
            if changed:
                self.transcription_assist_review = review
        else:
            changed = self.transcription_session.redo()
        if not changed:
            return
        if kind == "session":
            self._invalidate_transcription_rhythm_diagnostic()
        self.transcription_review_controller.complete_redo(kind)
        self._reapply_transcription_assist_review()
        self._refresh_transcription_workspace()
        self._start_transcription_assist_analysis()
        self._autosave_project(
            "transcription review redo",
            immediate=True,
        )

    def _align_reference_audio_to_playhead(self) -> None:
        if not self.reference_audio.audio_path:
            self.show_toast(tr("请先载入参考音频。"), kind="warning")
            return
        editor = self.active_transcription_editor
        playhead_ms = (
            float(editor.playhead_ms)
            if editor is not None
            else float(self.timeline.playhead_ms)
        )
        audio_position = float(self.reference_audio.player.position())
        offset = playhead_ms - audio_position
        self._set_reference_alignment(
            offset,
            self.beat_origin_ms,
            autosave=True,
        )
        self._refresh_transcription_workspace()
        self.show_toast(
            tr("当前音频位置已对齐到播放头。"),
            kind="success",
        )

    def _set_playhead_as_beat_origin(self) -> None:
        editor = self.active_transcription_editor
        playhead_ms = (
            float(editor.playhead_ms)
            if editor is not None
            else float(self.timeline.playhead_ms)
        )
        self._set_reference_alignment(
            self.reference_audio_offset_ms,
            playhead_ms,
            autosave=True,
        )
        self.show_toast(
            tr("第一拍锚点已更新；正式音符位置未移动。"),
            kind="success",
        )

    def _set_transcription_status(self, text: object) -> None:
        self._transcription_ui_status_spec = defer_tr(text)
        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_status(self._transcription_ui_status_spec)

    def retranslate_dynamic_content(self) -> None:
        """Refresh localized widths and cached status text."""

        self._sync_caption_button_widths()
        self.timeline.refresh_reference_audio_controls()
        self.timeline.update()
        self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_status(self._transcription_ui_status_spec)

    def _transcription_audio_time_notes(self) -> tuple[Note, ...]:
        """Snapshot current formal/draft notes once for background harmony."""

        draft_track_id = None
        draft_notes: tuple[Note, ...] = ()
        editor = self.active_transcription_editor
        if editor is not None:
            draft_track_id = int(editor.track.track_id)
            draft_notes = tuple(editor.canvas.notes)
        offset_ms = float(self.reference_audio_offset_ms)
        projected: list[Note] = []
        for track in self.tracks:
            if track.is_percussion or int(track.bdo_instrument_id) == 0x0D:
                continue
            notes = (
                draft_notes
                if draft_track_id is not None
                and int(track.track_id) == draft_track_id
                else tuple(track.notes)
            )
            for note in notes:
                projected.append(
                    note._replace(start=float(note.start) - offset_ms)
                )
        projected.sort(
            key=lambda note: (
                float(note.start),
                int(note.pitch),
                float(note.dur),
                int(note.vel),
                int(note.ntype),
            )
        )
        return tuple(projected)

    def _schedule_transcription_assist_refresh(self) -> None:
        """Debounce semantic recomputation after draft/formal note edits."""

        if not TRANSCRIPTION_SEMANTIC_ASSIST_ENABLED:
            return

        result = self.transcription_result
        descriptor = (
            result.evidence_descriptor if result is not None else None
        )
        if (
            descriptor is None
            or not descriptor.cache_key
            or self.workspace_close_pending
        ):
            return
        self.transcription_assist_refresh_timer.start()

    def _start_transcription_assist_analysis(
        self,
        *,
        harmony_only: bool = False,
        allow_review_recovery: bool = True,
    ) -> None:
        if not TRANSCRIPTION_SEMANTIC_ASSIST_ENABLED:
            self.transcription_analysis_coordinator.clear_assist_restart()
            self.transcription_assist_refresh_timer.stop()
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            return
        if self.workspace_close_pending:
            self.transcription_analysis_coordinator.clear_assist_restart()
            return
        result = self.transcription_result
        descriptor = (
            result.evidence_descriptor if result is not None else None
        )
        if result is None or descriptor is None or not descriptor.cache_key:
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self._refresh_transcription_workspace()
            return
        if self.transcription_assist_worker is not None:
            self.transcription_analysis_coordinator.queue_assist_restart(
                harmony_only=harmony_only,
                allow_review_recovery=allow_review_recovery,
            )
            cancel = getattr(self.transcription_assist_worker, "cancel", None)
            if callable(cancel):
                cancel()
            return
        self.transcription_analysis_coordinator.clear_assist_restart()
        generation = (
            self.transcription_analysis_coordinator.next_assist_generation()
        )
        effective_bpm = float(max(1, self.bpm_override or self.bpm))
        worker = TranscriptionAssistAnalysisWorker(
            cache_key=descriptor.cache_key,
            candidates=tuple(self.transcription_session.candidates),
            audio_time_notes=self._transcription_audio_time_notes(),
            descriptors=bdo_transcription_instrument_descriptors(),
            bpm=effective_bpm,
            time_signature=max(1, int(self.time_sig)),
            beat_origin_audio_ms=(
                float(self.beat_origin_ms)
                - float(self.reference_audio_offset_ms)
            ),
            duration_ms=float(descriptor.duration_ms),
            midi_min=int(descriptor.midi_min),
            reference_audio_path=str(
                self.reference_audio.audio_path or ""
            ),
            sample_map_path=BDO_SAMPLE_MAP_PATH,
            audio_root=str(self.audio_sources.get("audio_root", "") or ""),
            manual_voice_groups=(
                self.transcription_assist_review.active_voice_groups
            ),
            audio_fingerprint=str(
                getattr(descriptor, "audio_fingerprint", "") or ""
            ),
            pitch_offset=int(self.transpose),
            review_state=self.transcription_assist_review,
            previous_candidates=(
                self.transcription_assist_previous_candidates
            ),
            reuse_instrument_matches=(
                self.automatic_instrument_match_analysis
                if harmony_only
                else None
            ),
            reuse_timbre_profile_index=(
                self.transcription_timbre_profile_index
            ),
            reuse_group_timbre_profiles=(
                self.transcription_group_timbre_profiles
            ),
            reuse_group_timbre_revision=(
                self.transcription_group_timbre_revision
            ),
            allow_review_recovery=allow_review_recovery,
            parent=self,
        )
        self.transcription_assist_worker = worker
        worker.succeeded.connect(
            lambda bundle, token=generation:
            self._transcription_assist_succeeded(token, bundle)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._transcription_assist_failed(token, message)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._transcription_assist_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _transcription_assist_succeeded(
        self,
        generation: int,
        bundle: TranscriptionAssistAnalysisBundle,
    ) -> None:
        if not self.transcription_analysis_coordinator.is_current_assist(
            generation
        ):
            return
        self.automatic_harmony_analysis = bundle.harmony
        self.automatic_instrument_match_analysis = bundle.instrument_matches
        self.transcription_timbre_profile_index = (
            bundle.timbre_profile_index
        )
        self.transcription_group_timbre_profiles = (
            bundle.group_timbre_profiles
        )
        self.transcription_group_timbre_revision = (
            bundle.group_timbre_revision
        )
        previous_review = self.transcription_assist_review
        review = (
            bundle.recovered_review
            if bundle.recovered_review is not None
            else previous_review
        )
        self.transcription_assist_review = review
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        key_review = review.active_key_override
        key_override = (
            KeyEstimate(
                key_review.root_pc,
                key_review.mode,
                1.0,
                (),
                "manual",
            )
            if key_review is not None
            else None
        )
        chord_overrides = tuple(
            ChordSegment(
                item.segment_id,
                item.start_audio_ms,
                item.end_audio_ms,
                item.root_pc,
                item.quality,
                item.bass_pc,
                1.0,
                (),
                "manual",
                bool(item.locked),
            )
            for item in review.active_chord_segments
        )
        self.harmony_analysis = apply_harmony_overrides(
            bundle.harmony,
            key_override=key_override,
            chord_overrides=chord_overrides,
        )
        group_reviews = {
            item.group_id: item for item in review.active_voice_groups
        }
        reviewed_groups = tuple(
            VoiceGroup(
                group.group_id,
                group_reviews[group.group_id].candidate_ids,
                group_reviews[group.group_id].start_audio_ms,
                group_reviews[group.group_id].end_audio_ms,
                group_reviews[group.group_id].role,
                group.confidence,
            )
            if group.group_id in group_reviews
            else group
            for group in bundle.instrument_matches.groups
        )
        self.instrument_match_analysis = replace(
            bundle.instrument_matches,
            groups=reviewed_groups,
        )
        group_ids = {
            group.group_id for group in reviewed_groups
        }
        if self.active_voice_group_id not in group_ids:
            self.active_voice_group_id = (
                reviewed_groups[0].group_id
                if reviewed_groups
                else ""
            )
        self._refresh_transcription_workspace()
        if (
            not self.loading_project
            and bundle.recovered_review is not None
            and review != previous_review
        ):
            self._autosave_project(
                "transcription assist review recovery",
                immediate=True,
            )

    def _reapply_transcription_assist_review(
        self, *, autosave_reason: str | None = None
    ) -> None:
        harmony = self.automatic_harmony_analysis
        matches = self.automatic_instrument_match_analysis
        if harmony is None or matches is None:
            return
        review = self.transcription_assist_review
        key_review = review.active_key_override
        key_override = (
            KeyEstimate(
                key_review.root_pc,
                key_review.mode,
                1.0,
                (),
                "manual",
            )
            if key_review is not None
            else None
        )
        chord_overrides = tuple(
            ChordSegment(
                item.segment_id,
                item.start_audio_ms,
                item.end_audio_ms,
                item.root_pc,
                item.quality,
                item.bass_pc,
                1.0,
                (),
                "manual",
                bool(item.locked),
            )
            for item in review.active_chord_segments
        )
        self.harmony_analysis = apply_harmony_overrides(
            harmony,
            key_override=key_override,
            chord_overrides=chord_overrides,
        )
        group_reviews = {
            item.group_id: item for item in review.active_voice_groups
        }
        groups = tuple(
            VoiceGroup(
                group.group_id,
                group_reviews[group.group_id].candidate_ids,
                group_reviews[group.group_id].start_audio_ms,
                group_reviews[group.group_id].end_audio_ms,
                group_reviews[group.group_id].role,
                group.confidence,
            )
            if group.group_id in group_reviews
            else group
            for group in matches.groups
        )
        self.instrument_match_analysis = replace(matches, groups=groups)
        self._refresh_transcription_workspace()
        if autosave_reason and not self.loading_project:
            self._autosave_project(autosave_reason, immediate=True)

    def _current_analysis_fingerprint(self) -> str:
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        return str(
            getattr(descriptor, "audio_fingerprint", "") or ""
        )

    def _record_transcription_review_action(self, kind: str) -> None:
        value = self.transcription_review_controller.record_action(kind)
        if value == "assist":
            self.transcription_session.commands.discard_redo()

    def _set_transcription_assist_review_state(
        self, state: TranscriptionAssistReviewState
    ) -> bool:
        if state == self.transcription_assist_review:
            return False
        self.transcription_review_controller.record_assist_change(
            self.transcription_assist_review
        )
        self.transcription_assist_review = state
        self.transcription_session.commands.discard_redo()
        return True

    def _clear_transcription_review_history(self) -> None:
        self.transcription_review_controller.clear()
        self.transcription_session.commands.clear()

    def _can_undo_transcription_review(self) -> bool:
        return self.transcription_review_controller.can_undo(
            session_can_undo=self.transcription_session.commands.can_undo
        )

    def _can_redo_transcription_review(self) -> bool:
        return self.transcription_review_controller.can_redo(
            session_can_redo=self.transcription_session.commands.can_redo
        )

    def _set_assist_key_override(
        self,
        root_pc: int,
        mode: str,
        *,
        manual: bool,
        locked: bool,
    ) -> None:
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                key_override=KeyReviewOverride(
                    int(root_pc),
                    str(mode),
                    manual=manual,
                    locked=locked,
                ),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription key review"
        )

    def _set_assist_chord_review(
        self,
        segment: ChordSegment,
        *,
        root_pc: int | None = None,
        quality: str | None = None,
        bass_pc: int | None = None,
        manual: bool,
        locked: bool,
    ) -> None:
        chosen_quality = str(quality or segment.quality)
        chosen_root = (
            segment.root_pc if root_pc is None else int(root_pc)
        )
        if chosen_quality == "N":
            chosen_root = None
            bass_pc = None
        candidate_ids = self._candidate_ids_for_audio_range(
            segment.start_audio_ms,
            segment.end_audio_ms,
        )
        existing = [
            item
            for item in self.transcription_assist_review.locked_chord_segments
            if not (
                item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
            )
        ]
        existing.append(
            LockedChordReview(
                "",
                segment.segment_id,
                segment.start_audio_ms,
                segment.end_audio_ms,
                chosen_root,
                chosen_quality,
                segment.bass_pc if bass_pc is None else bass_pc,
                candidate_ids,
                manual=manual,
                locked=locked,
            )
        )
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                locked_chord_segments=tuple(existing),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription chord review"
        )

    def _candidate_ids_for_audio_range(
        self, start_audio_ms: float, end_audio_ms: float
    ) -> tuple[str, ...]:
        return self.transcription_session.candidate_ids_overlapping_audio_range(
            start_audio_ms,
            end_audio_ms,
        )

    def _replace_assist_chord_reviews(
        self,
        removed_segments: Iterable[ChordSegment],
        additions: Iterable[LockedChordReview],
        *,
        reason: str,
    ) -> None:
        removed = tuple(removed_segments)
        retained = [
            item
            for item in self.transcription_assist_review.locked_chord_segments
            if not any(
                item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
                for segment in removed
            )
        ]
        retained.extend(additions)
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                locked_chord_segments=tuple(retained),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason=reason
        )

    def _split_transcription_chord_segment(
        self, segment_id: str, project_ms: float
    ) -> None:
        harmony = self.harmony_analysis
        if harmony is None:
            return
        segment = next(
            (
                item
                for item in harmony.chord_segments
                if item.segment_id == str(segment_id)
            ),
            None,
        )
        if segment is None:
            return
        split_audio_ms = (
            float(project_ms) - float(self.reference_audio_offset_ms)
        )
        if not (
            segment.start_audio_ms + 1.0
            < split_audio_ms
            < segment.end_audio_ms - 1.0
        ):
            self.show_toast(
                tr("请先将播放头放在所选和弦段内部。"),
                kind="warning",
            )
            return
        left_id = stable_assist_review_id(
            "chord-segment",
            segment.segment_id,
            round(segment.start_audio_ms, 3),
            round(split_audio_ms, 3),
        )
        right_id = stable_assist_review_id(
            "chord-segment",
            segment.segment_id,
            round(split_audio_ms, 3),
            round(segment.end_audio_ms, 3),
        )
        additions = (
            LockedChordReview(
                "",
                left_id,
                segment.start_audio_ms,
                split_audio_ms,
                segment.root_pc,
                segment.quality,
                segment.bass_pc,
                self._candidate_ids_for_audio_range(
                    segment.start_audio_ms, split_audio_ms
                ),
                manual=True,
                locked=True,
            ),
            LockedChordReview(
                "",
                right_id,
                split_audio_ms,
                segment.end_audio_ms,
                segment.root_pc,
                segment.quality,
                segment.bass_pc,
                self._candidate_ids_for_audio_range(
                    split_audio_ms, segment.end_audio_ms
                ),
                manual=True,
                locked=True,
            ),
        )
        self._replace_assist_chord_reviews(
            (segment,),
            additions,
            reason="transcription chord split",
        )

    def _merge_transcription_chord_segments(
        self,
        first_segment_id: str,
        second_segment_id: str,
        retained_segment_id: str,
    ) -> None:
        harmony = self.harmony_analysis
        if harmony is None:
            return
        by_id = {
            segment.segment_id: segment
            for segment in harmony.chord_segments
        }
        first = by_id.get(str(first_segment_id))
        second = by_id.get(str(second_segment_id))
        retained = by_id.get(str(retained_segment_id))
        if (
            first is None
            or second is None
            or retained not in {first, second}
        ):
            return
        left, right = sorted(
            (first, second),
            key=lambda segment: (
                segment.start_audio_ms,
                segment.end_audio_ms,
            ),
        )
        if abs(left.end_audio_ms - right.start_audio_ms) > 1.0:
            self.show_toast(
                tr("只能合并相邻的和弦段。"),
                kind="warning",
            )
            return
        start_audio_ms = left.start_audio_ms
        end_audio_ms = right.end_audio_ms
        merged = LockedChordReview(
            "",
            stable_assist_review_id(
                "chord-segment",
                left.segment_id,
                right.segment_id,
                retained.root_pc,
                retained.quality,
            ),
            start_audio_ms,
            end_audio_ms,
            retained.root_pc,
            retained.quality,
            retained.bass_pc,
            self._candidate_ids_for_audio_range(
                start_audio_ms, end_audio_ms
            ),
            manual=True,
            locked=True,
        )
        self._replace_assist_chord_reviews(
            (first, second),
            (merged,),
            reason="transcription chord merge",
        )

    def _confirm_assist_instrument_match(
        self, group_id: str, instrument_id: int
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        legal_matches = analysis.matches_for_group(group.group_id)
        if int(instrument_id) not in {
            int(match.instrument_id) for match in legal_matches
        }:
            self.show_toast(
                tr("该乐器不在当前声部的 Top-3 建议中。"),
                kind="warning",
            )
            return
        reviews = [
            item
            for item in self.transcription_assist_review.voice_groups
            if item.group_id != group.group_id
        ]
        reviews.append(
            ManualVoiceGroupReview(
                "",
                group.group_id,
                group.candidate_ids,
                group.start_audio_ms,
                group.end_audio_ms,
                group.role,
                int(instrument_id),
            )
        )
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                voice_groups=tuple(reviews),
            ),
        )
        self._reapply_transcription_assist_review(
            autosave_reason="transcription instrument confirmation"
        )
        self.show_toast(
            trf(
                "已确认声部的 BDO 乐器建议：{instrument}",
                instrument=trv(_ui_bdo_instrument_source(int(instrument_id))),
            ),
            kind="success",
        )

    def _replace_manual_voice_group_reviews(
        self,
        removed_group_ids: Iterable[str],
        additions: Iterable[ManualVoiceGroupReview],
        *,
        reason: str,
    ) -> None:
        removed = {str(group_id) for group_id in removed_group_ids}
        retained = [
            item
            for item in self.transcription_assist_review.voice_groups
            if item.group_id not in removed
        ]
        retained.extend(additions)
        self._set_transcription_assist_review_state(
            replace(
                self.transcription_assist_review,
                audio_fingerprint=self._current_analysis_fingerprint(),
                voice_groups=tuple(retained),
            ),
        )
        self._autosave_project(reason, immediate=True)
        self._start_transcription_assist_analysis()

    def _split_transcription_voice_group(
        self, group_id: str, project_ms: float
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        split_audio_ms = float(project_ms) - float(
            self.reference_audio_offset_ms
        )
        group_candidates = {
            candidate_id: candidate
            for candidate_id in group.candidate_ids
            if (
                candidate := self.transcription_session.candidate_for_id(
                    candidate_id
                )
            )
            is not None
        }
        left_ids = tuple(
            candidate_id
            for candidate_id, candidate in group_candidates.items()
            if (
                float(candidate.start_ms)
                + float(candidate.duration_ms) * 0.5
            )
            < split_audio_ms
        )
        left_id_set = set(left_ids)
        right_ids = tuple(
            candidate_id
            for candidate_id in group.candidate_ids
            if candidate_id not in left_id_set
            and candidate_id in group_candidates
        )
        if not left_ids or not right_ids:
            self.show_toast(
                tr("播放头两侧必须都包含候选，才能分割声部。"),
                kind="warning",
            )
            return
        existing = next(
            (
                item
                for item in self.transcription_assist_review.voice_groups
                if item.group_id == group.group_id
            ),
            None,
        )
        confirmed = (
            existing.confirmed_instrument_id
            if existing is not None
            else None
        )
        left_group_id = stable_assist_review_id(
            "voice", tuple(sorted(left_ids))
        )
        right_group_id = stable_assist_review_id(
            "voice", tuple(sorted(right_ids))
        )
        additions = (
            ManualVoiceGroupReview(
                "",
                left_group_id,
                left_ids,
                group.start_audio_ms,
                split_audio_ms,
                group.role,
                confirmed,
            ),
            ManualVoiceGroupReview(
                "",
                right_group_id,
                right_ids,
                split_audio_ms,
                group.end_audio_ms,
                group.role,
                confirmed,
            ),
        )
        self._replace_manual_voice_group_reviews(
            (group.group_id,),
            additions,
            reason="transcription voice split",
        )

    def _merge_transcription_voice_groups(
        self, first_group_id: str, second_group_id: str
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None or first_group_id == second_group_id:
            return
        groups = {
            group.group_id: group for group in analysis.groups
        }
        first = groups.get(str(first_group_id))
        second = groups.get(str(second_group_id))
        if first is None or second is None:
            return
        candidate_ids = tuple(
            sorted(set(first.candidate_ids).union(second.candidate_ids))
        )
        reviews = {
            item.group_id: item
            for item in self.transcription_assist_review.voice_groups
        }
        confirmations = {
            review.confirmed_instrument_id
            for group_id in (first.group_id, second.group_id)
            if (review := reviews.get(group_id)) is not None
            and review.confirmed_instrument_id is not None
        }
        confirmed = (
            next(iter(confirmations)) if len(confirmations) == 1 else None
        )
        merged = ManualVoiceGroupReview(
            "",
            stable_assist_review_id("voice", candidate_ids),
            candidate_ids,
            min(first.start_audio_ms, second.start_audio_ms),
            max(first.end_audio_ms, second.end_audio_ms),
            first.role,
            confirmed,
        )
        self._replace_manual_voice_group_reviews(
            (first.group_id, second.group_id),
            (merged,),
            reason="transcription voice merge",
        )

    def _set_transcription_voice_group_color(
        self, group_id: str, color: str
    ) -> None:
        ui_config = self.config.setdefault("transcription_ui", {})
        if not isinstance(ui_config, dict):
            return
        colors = ui_config.setdefault("voice_group_colors", {})
        if not isinstance(colors, dict):
            colors = {}
            ui_config["voice_group_colors"] = colors
        colors[str(group_id)] = str(color)
        # Bound stale local-only color preferences.
        while len(colors) > 256:
            colors.pop(next(iter(colors)))
        save_config(self.config)
        self._refresh_transcription_workspace()

    def _set_transcription_voice_group_role(
        self, group_id: str, role: str
    ) -> None:
        analysis = self.instrument_match_analysis
        if analysis is None:
            return
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        if group is None:
            return
        existing = next(
            (
                item
                for item in self.transcription_assist_review.voice_groups
                if item.group_id == group.group_id
            ),
            None,
        )
        updated = ManualVoiceGroupReview(
            "",
            group.group_id,
            group.candidate_ids,
            group.start_audio_ms,
            group.end_audio_ms,
            str(role),
            (
                existing.confirmed_instrument_id
                if existing is not None
                else None
            ),
        )
        self._replace_manual_voice_group_reviews(
            (group.group_id,),
            (updated,),
            reason="transcription voice role",
        )

    def _transcription_assist_failed(
        self, generation: int, message: str
    ) -> None:
        if not self.transcription_analysis_coordinator.is_current_assist(
            generation
        ):
            return
        self.automatic_harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.harmony_analysis = None
        self.instrument_match_analysis = None
        append_crash_log("Transcription assist analysis failed", message)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_assist_available(False)

    def _transcription_assist_finished(
        self, generation: int, worker: QThread
    ) -> None:
        if self.transcription_assist_worker is not worker:
            return
        self.transcription_assist_worker = None
        restart = (
            self.transcription_analysis_coordinator.consume_assist_restart()
        )
        if restart is not None:
            QTimer.singleShot(
                0,
                lambda value=restart.harmony_only,
                recover=restart.allow_review_recovery:
                self._start_transcription_assist_analysis(
                    harmony_only=value,
                    allow_review_recovery=recover,
                ),
            )
        elif self.workspace_close_pending:
            workspace_worker = self.workspace_transcription_worker
            if workspace_worker is None or not workspace_worker.isRunning():
                self.workspace_close_pending = False
                QTimer.singleShot(0, self.close)

    def _active_voice_group(self) -> VoiceGroup | None:
        analysis = self.instrument_match_analysis
        if analysis is None or not analysis.groups:
            return None
        for group in analysis.groups:
            if group.group_id == self.active_voice_group_id:
                return group
        selected = self.transcription_session.state.selected_candidate_ids
        if selected:
            matching = [
                group
                for group in analysis.groups
                if selected.intersection(group.candidate_ids)
            ]
            if matching:
                return min(
                    matching,
                    key=lambda group: (
                        group.start_audio_ms,
                        group.group_id,
                    ),
                )
        return analysis.groups[0]

    def _activate_voice_group_for_candidates(
        self, candidate_ids: Iterable[str]
    ) -> None:
        analysis = self.instrument_match_analysis
        selected = {str(item) for item in candidate_ids}
        if analysis is None or not selected:
            return
        matching = [
            group
            for group in analysis.groups
            if selected.intersection(group.candidate_ids)
        ]
        if matching:
            self.active_voice_group_id = min(
                matching,
                key=lambda group: (
                    group.start_audio_ms,
                    group.group_id,
                ),
            ).group_id

    def _open_transcription_review_queue(self) -> None:
        editor = self.active_transcription_editor
        if editor is None:
            return
        offset_ms = float(self.reference_audio_offset_ms)
        items: list[tuple[str, float, float, str]] = []
        queue_truncated = False

        def append_item(
            item: tuple[str, float, float, str],
        ) -> bool:
            nonlocal queue_truncated
            if len(items) >= TRANSCRIPTION_REVIEW_QUEUE_LIMIT:
                queue_truncated = True
                return False
            items.append(item)
            return True

        invalid_ids = set()
        duplicate_ids = set()
        tracks_by_id = {
            int(track.track_id): track for track in self.tracks
        }
        fallback_region = (
            self.transcription_session.state.region
            or (
                float(editor.playhead_ms),
                float(editor.playhead_ms) + float(editor.canvas.beat_ms),
            )
        )
        for route in self.transcription_session.state.pending_routes:
            candidate = self.transcription_session.candidate_for_id(
                route.candidate_id
            )
            target = tracks_by_id.get(int(route.track_id))
            orphaned = candidate is None or target is None
            invalid = (
                not orphaned
                and self._candidate_invalid_for_track(candidate, target)
            )
            if not orphaned and not invalid:
                continue
            if candidate is None:
                start_ms, end_ms = fallback_region
            else:
                start_ms = float(candidate.start_ms) + offset_ms
                end_ms = (
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms
                )
            if not append_item(
                (
                    trf(
                        "{state} · 轨道 {track_id}",
                        state=(
                            trv("孤立路由")
                            if orphaned
                            else trv("失效路由")
                        ),
                        track_id=int(route.track_id),
                    ),
                    start_ms,
                    end_ms,
                    "",
                )
            ):
                break
        cached_flags = getattr(
            editor, "_transcription_candidate_flag_cache", None
        )
        if cached_flags is not None:
            invalid_ids.update(cached_flags[1])
            duplicate_ids.update(cached_flags[2])
        for alternate_id, primary_id in (
            editor.canvas._folded_candidate_primary.items()
        ):
            duplicate_ids.add(alternate_id)
            duplicate_ids.add(primary_id)
        for candidate_id in sorted(invalid_ids):
            candidate = self.transcription_session.candidate_for_id(
                candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "越界候选 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        for candidate_id in sorted(duplicate_ids.difference(invalid_ids)):
            candidate = self.transcription_session.candidate_for_id(
                candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "重叠或重复 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        reviewed_fragment_ids = (
            invalid_ids
            | duplicate_ids
            | set(self.transcription_session.state.rejected_candidate_ids)
        )
        for annotation in self.transcription_session.annotations:
            if (
                annotation.candidate_id in reviewed_fragment_ids
                or not {
                    "review_fragment",
                    "pitch_flicker",
                }.intersection(annotation.flags)
            ):
                continue
            candidate = self.transcription_session.candidate_for_id(
                annotation.candidate_id
            )
            if candidate is None:
                continue
            if not append_item(
                (
                    trf(
                        "疑似碎音 · {note}",
                        note=note_name(int(candidate.pitch)),
                    ),
                    float(candidate.start_ms) + offset_ms,
                    float(candidate.start_ms + candidate.duration_ms)
                    + offset_ms,
                    "",
                )
            ):
                break
        harmony = self.harmony_analysis
        if harmony is not None:
            conflicts = {item.segment_id for item in harmony.conflicts}
            for segment in harmony.chord_segments:
                if (
                    segment.segment_id not in conflicts
                    and (
                        segment.quality == "N"
                        or float(segment.confidence) >= 0.55
                    )
                ):
                    continue
                if not append_item(
                    (
                        trf(
                            "和声不确定 · {chord}",
                            chord=(
                                "N"
                                if segment.root_pc is None
                                else (
                                    f"{editor._pitch_class_label(segment.root_pc)} "
                                    f"{segment.quality}"
                                )
                            ),
                        ),
                        segment.start_audio_ms + offset_ms,
                        segment.end_audio_ms + offset_ms,
                        "",
                    )
                ):
                    break
        analysis = self.instrument_match_analysis
        if analysis is not None:
            confirmed_group_ids = {
                item.group_id
                for item in self.transcription_assist_review.active_voice_groups
                if item.confirmed_instrument_id is not None
            }
            for group in analysis.groups:
                matches = analysis.matches_for_group(group.group_id)
                confirmed = next(
                    (
                        item.confirmed_instrument_id
                        for item in self.transcription_assist_review.active_voice_groups
                        if item.group_id == group.group_id
                    ),
                    None,
                )
                if (
                    group.group_id in confirmed_group_ids
                    and confirmed is not None
                    and int(confirmed)
                    in {match.instrument_id for match in matches}
                ):
                    continue
                if (
                    matches
                    and matches[0].timbre_score is not None
                    and matches[0].total_score >= 0.45
                ):
                    continue
                if not append_item(
                    (
                        trf(
                            "乐器匹配待确认 · {role}",
                            role=trv(voice_role_source_label(group.role)),
                        ),
                        group.start_audio_ms + offset_ms,
                        group.end_audio_ms + offset_ms,
                        group.group_id,
                    )
                ):
                    break
        if not items:
            self.show_toast(tr("当前没有待审项目。"), kind="success")
            return
        if queue_truncated:
            self.show_toast(
                trf(
                    "待审项目较多，当前只显示优先级最高的 {count} 项。",
                    count=TRANSCRIPTION_REVIEW_QUEUE_LIMIT,
                ),
                kind="warning",
            )
        labels = [
            f"{index + 1}. {label} · {start_ms / 1000.0:.1f}s"
            for index, (label, start_ms, _end_ms, _group_id)
            in enumerate(items)
        ]
        selected, accepted = choose_item(
            editor,
            tr("待审队列"),
            tr("选择后只定位并设置 A–B，不会自动选择或写入音符："),
            labels,
        )
        if not accepted:
            return
        selected_index = labels.index(str(selected))
        _label, start_ms, end_ms, group_id = items[selected_index]
        self._set_transcription_region((start_ms, end_ms))
        if group_id and analysis is not None:
            group = next(
                (
                    item
                    for item in analysis.groups
                    if item.group_id == group_id
                ),
                None,
            )
            if group is not None:
                self.active_voice_group_id = group.group_id
        editor.focus_transcription_time_range(start_ms, end_ms)
        self._refresh_transcription_workspace()

    def _set_transcription_analysis_state(
        self,
        busy: bool,
        progress: int | None = None,
        *,
        status: object | None = None,
    ) -> None:
        self.transcription_analysis_busy = bool(busy)
        self.transcription_analysis_progress = (
            None
            if progress is None
            else max(0, min(100, int(progress)))
        )
        if status is not None:
            self._transcription_ui_status_spec = defer_tr(status)
            self.transcription_ui_status = str(self._transcription_ui_status_spec)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.refresh_transcription_projection()
            editor.set_transcription_analysis_ui(
                self.transcription_analysis_busy,
                self.transcription_analysis_progress,
                status=self._transcription_ui_status_spec,
            )

    def _start_workspace_transcription_analysis(self) -> None:
        audio_path = self.reference_audio.audio_path
        if not audio_path:
            self.show_toast(
                tr("请先载入 MP3/WAV 参考音频。"),
                kind="warning",
            )
            return
        if self.workspace_transcription_worker is not None:
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            return
        available, reason = transcription_backend_quick_status()
        if not available:
            QMessageBox.warning(
                self,
                tr("无法开始扒谱"),
                str(defer_tr(reason)),
            )
            return
        self._invalidate_transcription_rhythm_diagnostic()
        self._stop_preview(reset_playhead=False)
        generation = (
            self.transcription_analysis_coordinator
            .next_workspace_generation()
        )
        # The simplified UI deliberately has no expert parameter controls.
        # Always analyze with the conservative production contract instead of
        # silently reusing an experimental setting from an older project.
        self.transcription_session.set_analysis_mode("standard")
        self.transcription_session.set_sensitivity("balanced")
        self.transcription_session.set_cleanup_profile("preserve")
        state = self.transcription_session.state
        if editor is not None:
            editor.transcription_panel.set_analysis_mode(state.analysis_mode)
            editor.transcription_panel.set_sensitivity(state.sensitivity)
            editor.transcription_panel.set_cleanup_profile(
                state.cleanup_profile
            )
        worker = TranscriptionAnalysisWorker(
            audio_path,
            self,
            analysis_mode=state.analysis_mode,
            sensitivity=state.sensitivity,
            cleanup_profile=state.cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.progress_changed.connect(
            lambda value, token=generation:
            self._workspace_transcription_progress(token, value)
        )
        worker.succeeded.connect(
            lambda result, token=generation:
            self._workspace_transcription_succeeded(token, result, False)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            0,
            status=tr("正在分析参考音频…"),
        )
        worker.start()
        self._record_usage_feature("transcription")

    def _redecode_transcription_range(self) -> None:
        state = self.transcription_session.state
        if (
            self.workspace_transcription_worker is not None
            or not state.cache_key
            or state.region is None
        ):
            return
        editor = self.active_transcription_editor
        if editor is not None and editor.has_transcription_staging():
            editor.warn_transcription_staging_blocked()
            return
        self._invalidate_transcription_rhythm_diagnostic()
        start_ms, end_ms = state.region
        self._stop_preview(reset_playhead=False)
        generation = (
            self.transcription_analysis_coordinator
            .next_workspace_generation()
        )
        worker = TranscriptionRedecodeWorker(
            state.cache_key,
            start_ms - self.reference_audio_offset_ms,
            end_ms - self.reference_audio_offset_ms,
            state.sensitivity,
            self,
            cleanup_profile=state.cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.succeeded.connect(
            lambda result, token=generation:
            self._workspace_transcription_succeeded(token, result, True)
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            status=tr("正在从缓存证据重新解码 A–B；不会再次运行模型。"),
        )
        worker.start()

    def _restore_cached_transcription(
        self,
        *,
        status: str | None = None,
        cleanup_profile: str | None = None,
        rollback_cleanup_profile: str | None = None,
    ) -> int | None:
        cache_key = self.transcription_session.state.cache_key
        if (
            not cache_key
            or self.workspace_transcription_worker is not None
            or self._pending_transcription_cleanup_profile is not None
        ):
            return None
        self._invalidate_transcription_rhythm_diagnostic()
        requested_cleanup_profile = str(
            cleanup_profile
            if cleanup_profile is not None
            else self.transcription_session.state.cleanup_profile
        )
        if requested_cleanup_profile not in {
            "preserve",
            "balanced",
            "clean",
        }:
            raise ValueError(
                "unknown transcription cleanup profile: "
                f"{requested_cleanup_profile}"
            )
        generation = (
            self.transcription_analysis_coordinator
            .next_workspace_generation()
        )
        if rollback_cleanup_profile is not None:
            self._pending_transcription_cleanup_profile = (
                generation,
                str(rollback_cleanup_profile),
                requested_cleanup_profile,
            )
        worker = TranscriptionCacheLoadWorker(
            cache_key,
            self,
            audio_path=str(self.reference_audio.audio_path or ""),
            expected_audio_fingerprint=(
                self.transcription_session.state.analysis_fingerprint
            ),
            analysis_mode=self.transcription_session.state.analysis_mode,
            sensitivity=self.transcription_session.state.sensitivity,
            cleanup_profile=requested_cleanup_profile,
        )
        self.workspace_transcription_worker = worker
        worker.succeeded.connect(
            lambda result, token=generation, current=worker:
            self._workspace_transcription_succeeded(
                token,
                result,
                False,
                True,
                current.current_audio_fingerprint,
            )
        )
        worker.failed.connect(
            lambda message, token=generation:
            self._workspace_transcription_failed(token, message, quiet=True)
        )
        worker.cancelled.connect(
            lambda token=generation:
            self._workspace_transcription_cancelled(token)
        )
        worker.finished.connect(
            lambda token=generation, current=worker:
            self._workspace_transcription_finished(token, current)
        )
        worker.finished.connect(worker.deleteLater)
        self._set_transcription_analysis_state(
            True,
            status=(
                str(status)
                if status is not None
                else tr("正在校验并恢复扒谱缓存…")
            ),
        )
        try:
            worker.start()
        except Exception:
            if self.workspace_transcription_worker is worker:
                self.workspace_transcription_worker = None
            self._rollback_cleanup_profile_transaction(generation)
            worker.deleteLater()
            raise
        return generation

    def _cleanup_profile_transaction(
        self,
        generation: int,
    ) -> tuple[int, str, str] | None:
        pending = self._pending_transcription_cleanup_profile
        if pending is None or pending[0] != generation:
            return None
        return pending

    def _rollback_cleanup_profile_transaction(
        self,
        generation: int | None = None,
    ) -> bool:
        pending = self._pending_transcription_cleanup_profile
        if pending is None:
            return False
        if generation is not None and pending[0] != generation:
            return False
        _token, previous, _requested = pending
        self._pending_transcription_cleanup_profile = None
        self.transcription_session.set_cleanup_profile(previous)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_cleanup_profile(previous)
        self._refresh_transcription_action_state()
        return True

    def _commit_cleanup_profile_transaction(
        self,
        generation: int,
        result: TranscriptionResult,
    ) -> bool:
        pending = self._cleanup_profile_transaction(generation)
        if pending is None:
            return True
        _token, _previous, requested = pending
        report = result.postprocess_report
        descriptor = result.evidence_descriptor
        result_profile = str(
            report.profile
            if report is not None
            else descriptor.cleanup_profile
            if descriptor is not None
            else ""
        )
        if result_profile != requested:
            self._rollback_cleanup_profile_transaction(generation)
            return False
        self.transcription_session.set_cleanup_profile(requested)
        self._pending_transcription_cleanup_profile = None
        editor = self.active_transcription_editor
        if editor is not None:
            editor.transcription_panel.set_cleanup_profile(requested)
        self._refresh_transcription_action_state()
        return True

    def _workspace_transcription_progress(
        self, generation: int, value: int,
    ) -> None:
        if self.transcription_analysis_coordinator.is_current_workspace(
            generation
        ):
            self._set_transcription_analysis_state(True, value)

    def _isolate_transcription_review_for_changed_audio(
        self,
        previous: TranscriptionSessionState,
        restored_audio_fingerprint: str,
    ) -> None:
        """Discard derived review state while retaining safe session settings."""

        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        self.transcription_assist_review = isolate_assist_review_for_audio(
            self.transcription_assist_review,
            restored_audio_fingerprint,
        )
        self.automatic_harmony_analysis = None
        self.automatic_instrument_match_analysis = None
        self.harmony_analysis = None
        self.instrument_match_analysis = None
        self._clear_reference_timbre_analysis(cancel_worker=True)
        self.transcription_group_timbre_profiles = None
        self.transcription_group_timbre_revision = ""
        self.transcription_session = TranscriptionSession(
            state=TranscriptionSessionState(
                region=previous.region,
                analysis_mode=previous.analysis_mode,
                sensitivity=previous.sensitivity,
                cleanup_profile=previous.cleanup_profile,
            )
        )
        self.transcription_result = None
        self._clear_transcription_review_history()
        editor = self.active_transcription_editor
        if editor is not None:
            editor.release_transcription_resources()

    def _workspace_transcription_succeeded(
        self,
        generation: int,
        result: TranscriptionResult | None,
        interval: bool,
        restoring: bool = False,
        restored_audio_fingerprint: str = "",
    ) -> None:
        if not self.transcription_analysis_coordinator.is_current_workspace(
            generation
        ):
            return
        self._invalidate_transcription_rhythm_diagnostic()
        previous = self.transcription_session.state
        saved_fingerprint = (
            previous.analysis_fingerprint
            or self.transcription_assist_review.audio_fingerprint
        )
        restore_identity_mismatch = restored_audio_review_requires_isolation(
            restoring=restoring,
            restored_audio_fingerprint=restored_audio_fingerprint,
            saved_fingerprint=saved_fingerprint,
            has_reference_audio=bool(self.reference_audio.audio_path),
        )
        if restore_identity_mismatch:
            self._rollback_cleanup_profile_transaction(generation)
            self._isolate_transcription_review_for_changed_audio(
                previous,
                restored_audio_fingerprint,
            )
            self._refresh_transcription_workspace()
            self._set_transcription_status(
                tr("参考音频已变化；旧审阅状态已隔离，请重新分析整首。")
            )
            if not self.loading_project:
                self._autosave_project(
                    "transcription audio identity changed",
                    immediate=True,
                )
            return
        if result is None:
            self._rollback_cleanup_profile_transaction(generation)
            self._set_transcription_status(
                tr("扒谱缓存不存在或校验失败；请重新分析整首。")
            )
            return
        if not self._commit_cleanup_profile_transaction(generation, result):
            self._set_transcription_status(
                tr("碎音处理切换失败；已恢复原档位。")
            )
            return
        previous = self.transcription_session.state
        self.transcription_assist_previous_candidates = tuple(
            self.transcription_session.candidates
        )
        descriptor = result.evidence_descriptor
        if descriptor is not None:
            self.reference_audio.set_content_duration_ms(
                float(descriptor.duration_ms)
            )
        fingerprint = (
            descriptor.audio_fingerprint if descriptor is not None else ""
        )
        backend_id = descriptor.backend_id if descriptor is not None else ""
        annotations = _session_candidate_annotations(result)
        if interval:
            start_ms, end_ms = previous.region or (0.0, 0.0)
            replaced = self.transcription_session.replace_region_candidates(
                result.candidates,
                start_ms - self.reference_audio_offset_ms,
                end_ms - self.reference_audio_offset_ms,
                annotations=annotations,
            )
            if (
                replaced.added_candidate_ids
                or replaced.removed_candidate_ids
            ):
                self._record_transcription_review_action("session")
            self.transcription_result = TranscriptionResult(
                tuple(self.transcription_session.candidates),
                result.cache_key,
                result.evidence_layers,
                True,
                descriptor,
                result.postprocess_report,
            )
            fragment_report = result.postprocess_report
            profile_label, profile_state = (
                _transcription_cleanup_ui_labels(
                    (
                        fragment_report.profile
                        if fragment_report is not None
                        else previous.cleanup_profile
                    ),
                    fragment_report,
                )
            )
            self._set_transcription_status(
                trf(
                    "区间重解码完成 · {profile} · {profile_state} · "
                    "新增 {added} · 替换 {removed} · 保护 {protected} · "
                    "自动合并 {merged} · 疑似碎音 {suspected} · "
                    "已隐藏 {suppressed}",
                    profile=profile_label,
                    profile_state=profile_state,
                    added=len(replaced.added_candidate_ids),
                    removed=len(replaced.removed_candidate_ids),
                    protected=len(replaced.protected_candidate_ids),
                    merged=(
                        fragment_report.automatic_merge_count
                        if fragment_report is not None
                        else 0
                    ),
                    suspected=(
                        fragment_report.suspected_fragment_count
                        if fragment_report is not None
                        else 0
                    ),
                    suppressed=(
                        fragment_report.suppressed_count
                        if fragment_report is not None
                        else 0
                    ),
                )
            )
        else:
            project_candidates = tuple(result.candidates)
            same_analysis = bool(
                previous.cache_key
                and previous.cache_key == result.cache_key
            )
            if same_analysis:
                restored_state = previous
                replaced = self.transcription_session.replace_all_candidates(
                    project_candidates,
                    annotations=annotations,
                )
                if (
                    replaced.added_candidate_ids
                    or replaced.removed_candidate_ids
                ):
                    self._record_transcription_review_action("session")
            else:
                restored_state = TranscriptionSessionState(
                    cache_key=result.cache_key,
                    analysis_fingerprint=fingerprint,
                    region=previous.region,
                    analysis_mode=(
                        descriptor.analysis_mode
                        if descriptor is not None
                        else previous.analysis_mode
                    ),
                    sensitivity=(
                        descriptor.decode_sensitivity
                        if descriptor is not None
                        else previous.sensitivity
                    ),
                    cleanup_profile=(
                        descriptor.cleanup_profile
                        if descriptor is not None
                        else previous.cleanup_profile
                    ),
                )
                self.transcription_session = TranscriptionSession(
                    project_candidates,
                    cache_key=result.cache_key,
                    backend_id=backend_id,
                    analysis_fingerprint=fingerprint,
                    state=restored_state,
                    annotations=annotations,
                )
            project_candidates = tuple(
                self.transcription_session.candidates
            )
            self.transcription_result = TranscriptionResult(
                tuple(project_candidates),
                result.cache_key,
                result.evidence_layers,
                result.cache_hit,
                descriptor,
                result.postprocess_report,
            )
            fragment_report = result.postprocess_report
            profile_label, profile_state = (
                _transcription_cleanup_ui_labels(
                    (
                        fragment_report.profile
                        if fragment_report is not None
                        else self.transcription_session.state.cleanup_profile
                    ),
                    fragment_report,
                )
            )
            self._set_transcription_status(
                trf(
                    "{prefix}{profile} · {profile_state} · "
                    "{count} 个候选 · 自动合并 {merged} · "
                    "疑似碎音 {suspected} · 已隐藏 {suppressed}",
                    prefix=trv(
                        "已恢复缓存 · "
                        if restoring or result.cache_hit
                        else "分析完成 · "
                    ),
                    profile=profile_label,
                    profile_state=profile_state,
                    count=len(project_candidates),
                    merged=(
                        fragment_report.automatic_merge_count
                        if fragment_report is not None
                        else 0
                    ),
                    suspected=(
                        fragment_report.suspected_fragment_count
                        if fragment_report is not None
                        else 0
                    ),
                    suppressed=(
                        fragment_report.suppressed_count
                        if fragment_report is not None
                        else 0
                    ),
                )
            )
        self._refresh_transcription_workspace()
        self._maybe_start_reference_bpm_follow(interval=interval)
        self._start_transcription_assist_analysis()
        self._start_reference_timbre_analysis(force_restart=True)
        self._autosave_project(
            "transcription interval decode"
            if interval
            else "transcription analysis",
            immediate=True,
        )

    def _workspace_transcription_failed(
        self,
        generation: int,
        message: str,
        *,
        quiet: bool = False,
    ) -> None:
        if not self.transcription_analysis_coordinator.is_current_workspace(
            generation
        ):
            return
        cleanup_rolled_back = self._rollback_cleanup_profile_transaction(
            generation
        )
        self._set_transcription_status(
            tr("碎音处理切换失败；已恢复原档位。")
            if cleanup_rolled_back
            else
            tr("缓存无法恢复；请重新分析整首。")
            if quiet
            else tr("扒谱分析失败。")
        )
        if not quiet:
            QMessageBox.warning(self, tr("扒谱分析失败"), message)

    def _workspace_transcription_cancelled(self, generation: int) -> None:
        if self.transcription_analysis_coordinator.is_current_workspace(
            generation
        ):
            cleanup_rolled_back = (
                self._rollback_cleanup_profile_transaction(generation)
            )
            self._set_transcription_status(
                tr("碎音处理切换已取消；已恢复原档位。")
                if cleanup_rolled_back
                else tr("扒谱分析已取消。")
            )

    def _workspace_transcription_finished(
        self,
        generation: int,
        worker: QThread,
    ) -> None:
        # Generation gates result validity; identity gates thread ownership.
        # A stale worker may finish after a new one has been installed and
        # must never clear that replacement.
        if self.workspace_transcription_worker is not worker:
            return
        self.workspace_transcription_worker = None
        orphaned_cleanup_switch = (
            self._rollback_cleanup_profile_transaction(generation)
        )
        available, reason = transcription_backend_quick_status()
        self._set_transcription_analysis_state(False)
        editor = self.active_transcription_editor
        if editor is not None:
            editor.set_transcription_analysis_ui(
                False,
                status=self._transcription_ui_status_spec,
                available=available,
                unavailable_reason=(
                    reason if not available else ""
                ),
            )
        self._refresh_transcription_action_state()
        if not available:
            self._set_transcription_status(reason)
        elif not self.reference_audio.audio_path:
            self._set_transcription_status(
                tr("载入音频，然后分析")
            )
        elif orphaned_cleanup_switch:
            self._set_transcription_status(
                tr("碎音处理切换失败；已恢复原档位。")
            )
        if self.workspace_close_pending:
            self.workspace_close_pending = False
            QTimer.singleShot(0, self.close)

    @staticmethod
    def _normalise_editor_draft(
        draft_notes: Iterable[object],
    ) -> tuple[Note, ...] | None:
        """Validate the editor wire shape without changing musical meaning."""

        normalised: list[Note] = []
        try:
            for value in draft_notes:
                pitch = int(getattr(value, "pitch"))
                velocity = int(getattr(value, "vel"))
                start = float(getattr(value, "start"))
                duration = float(getattr(value, "dur"))
                note_type = int(getattr(value, "ntype"))
                if (
                    not 0 <= pitch <= 127
                    or not 0 <= velocity <= 127
                    or not math.isfinite(start)
                    or not math.isfinite(duration)
                    or start < 0.0
                    or duration <= 0.0
                ):
                    return None
                normalised.append(
                    Note(pitch, velocity, start, duration, note_type)
                )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        return tuple(
            sorted(
                normalised,
                key=lambda note: (
                    float(note.start),
                    int(note.pitch),
                    float(note.dur),
                    int(note.vel),
                    int(note.ntype),
                ),
            )
        )

    def _prepare_transcription_commit_tracks(
        self,
        request: TranscriptionEditorCommit,
        tracks_by_id: dict[int, TrackState],
        historical_track_ids: set[int],
    ) -> tuple[dict[int, TrackState], set[int]]:
        """Create unpublished target tracks and record failed specifications."""

        existing_track_ids = set(tracks_by_id)
        new_tracks_by_id: dict[int, TrackState] = {}
        failed_new_track_ids: set[int] = set()
        for track_id, instrument_id in request.new_track_specs:
            if (
                int(track_id) in existing_track_ids
                or int(track_id) in historical_track_ids
                or int(instrument_id) not in BDO_INSTRUMENT_NAMES
                or int(instrument_id) in {0x04, 0x05, 0x0D}
            ):
                failed_new_track_ids.add(int(track_id))
                continue
            instrument_name = _ui_bdo_instrument_name(int(instrument_id))
            new_track = TrackState(
                track_id=int(track_id),
                notes=[],
                gm_program=0,
                is_percussion=False,
                display_name=trf(
                    "扒谱：{instrument}",
                    instrument=instrument_name,
                ),
                bdo_instrument_id=int(instrument_id),
                color=TRACK_COLORS[
                    (len(self.tracks) + len(new_tracks_by_id))
                    % len(TRACK_COLORS)
                ],
            )
            try:
                inherit_game_instrument_mix(
                    (*tracks_by_id.values(), new_track),
                    new_track,
                )
            except (TypeError, ValueError):
                failed_new_track_ids.add(int(track_id))
                continue
            new_tracks_by_id[int(track_id)] = new_track
            tracks_by_id[int(track_id)] = new_track
        return new_tracks_by_id, failed_new_track_ids

    def _capture_transcription_commit_candidates(
        self,
        candidate_ids: list[str],
    ) -> tuple[CommitCandidateRecord, ...]:
        """Capture the same raw/aligned candidate view shown by the editor."""

        state = self.transcription_session.state
        sidecar = self.transcription_rhythm_sidecar
        alignment = None if sidecar is None else sidecar.alignment
        editor = self.active_transcription_editor
        if alignment is not None and (
            editor is None
            or not bool(
                getattr(
                    editor,
                    "transcription_rhythm_projection_enabled",
                    True,
                )
            )
            or not alignment.is_current(
                evidence_cache_key=state.cache_key,
                candidates=tuple(self.transcription_session.candidates),
            )
        ):
            alignment = None
        captured: list[CommitCandidateRecord] = []
        for candidate_id in candidate_ids:
            candidate = self.transcription_session.candidate_for_id(candidate_id)
            if candidate is None:
                continue
            if alignment is not None:
                candidate = alignment.apply_to(candidate)
            captured.append(
                CommitCandidateRecord.capture(candidate_id, candidate)
            )
        return tuple(captured)

    def _build_transcription_commit_plan(
        self,
        request: TranscriptionEditorCommit,
        draft_notes: tuple[Note, ...],
        tracks_by_id: dict[int, TrackState],
        new_tracks_by_id: dict[int, TrackState],
        failed_new_track_ids: set[int],
    ) -> TranscriptionCommitPlan:
        """Freeze UI/session values before invoking the pure route planner."""

        state = self.transcription_session.state
        route_candidate_ids = sorted({
            route.candidate_id
            for route in (*state.pending_routes, *request.routes)
        })
        candidates = self._capture_transcription_commit_candidates(
            route_candidate_ids
        )
        required_track_ids = {
            int(request.current_track_id),
            *(
                int(route.track_id)
                for route in (*state.pending_routes, *request.routes)
            ),
            *new_tracks_by_id,
        }
        tracks = tuple(
            CommitTrackView.from_track(
                tracks_by_id[track_id],
                effective_transpose=self._effective_track_transpose(
                    tracks_by_id[track_id]
                ),
            )
            for track_id in sorted(required_track_ids)
            if track_id in tracks_by_id
        )
        return plan_transcription_commit(CommitPlanInput(
            current_track_id=int(request.current_track_id),
            draft_notes=draft_notes,
            local_routes=request.routes,
            pending_routes=state.pending_routes,
            applied_routes=state.applied_routes,
            rejected_candidate_ids=state.rejected_candidate_ids,
            candidates=candidates,
            tracks=tracks,
            failed_new_track_ids=frozenset(failed_new_track_ids),
            provisional_new_track_ids=frozenset(new_tracks_by_id),
            request_cache_key=request.cache_key,
            request_fingerprint=request.analysis_fingerprint,
            session_cache_key=state.cache_key,
            session_fingerprint=state.analysis_fingerprint,
            reference_audio_offset_ms=self.reference_audio_offset_ms,
        ))

    def _restore_transcription_track_checkpoint(
        self,
        published_tracks: list[TrackState],
        checkpoint: tuple[_TrackCommitCheckpoint, ...],
    ) -> None:
        """Restore the original TrackState objects after a failed publish."""

        published_tracks[:] = [item.track for item in checkpoint]
        self.tracks = published_tracks
        for item in checkpoint:
            item.track.notes = list(item.notes)
            item.track.notes_optimized = item.notes_optimized
            item.track.articulation_type = item.articulation_type
            item.track.bdo_source_note_records = item.bdo_source_note_records

    def _log_transcription_commit_failure(self, stage: str) -> None:
        append_crash_log(
            f"Transcription commit {stage} failed",
            traceback.format_exc(),
        )

    def _refresh_transcription_commit_views(
        self,
        current_track: TrackState,
    ) -> None:
        try:
            self._select_track(current_track)
            self._apply_workspace_change(ModelChange.structure())
        except Exception:
            self._log_transcription_commit_failure("timeline refresh")
        try:
            self._schedule_timeline_validation_refresh()
        except Exception:
            self._log_transcription_commit_failure("validation refresh")

    def _finish_transcription_commit(
        self,
        plan: TranscriptionCommitPlan,
        request: TranscriptionEditorCommit,
        current_track: TrackState,
    ) -> None:
        """Run compensable UI and persistence work after model commit."""

        try:
            self._clear_transcription_review_history()
        except Exception:
            self._log_transcription_commit_failure("review cleanup")
        self._refresh_transcription_commit_views(current_track)
        try:
            self._autosave_project(
                (
                    "transcription editor apply"
                    if request.routes or plan.successful_routes
                    else "note edit"
                ),
                immediate=True,
            )
        except Exception:
            self._log_transcription_commit_failure("autosave schedule")
        try:
            self.status_label.setText(
                trf(
                    "已更新 {track} · {count} 音符",
                    track=current_track.display_name,
                    count=len(current_track.notes),
                )
            )
            self.show_toast(
                tr("音符编辑已作为一个工程操作写入；可整批撤销。"),
                kind="success",
            )
        except Exception:
            self._log_transcription_commit_failure("status refresh")
        try:
            self._schedule_transcription_assist_refresh()
        except Exception:
            self._log_transcription_commit_failure("assist refresh")

    def _apply_transcription_commit_plan(
        self,
        plan: TranscriptionCommitPlan,
        *,
        request: TranscriptionEditorCommit,
        current_track: TrackState,
        tracks_by_id: dict[int, TrackState],
        new_tracks_by_id: dict[int, TrackState],
    ) -> None:
        """Atomically publish model state, then run compensable side effects."""

        before = self._project_snapshot()
        published_tracks = self.tracks
        track_checkpoint = tuple(
            _TrackCommitCheckpoint(
                track,
                tuple(track.notes),
                bool(track.notes_optimized),
                track.articulation_type,
                tuple(track.bdo_source_note_records),
            )
            for track in published_tracks
        )
        previous_state = self.transcription_session.state
        review_history = self.transcription_session.commands.checkpoint()
        project_history = self.project_commands.checkpoint()
        self._stop_preview(reset_playhead=False)
        try:
            if plan.sidecar_changed:
                self.transcription_session.commit_project_routes(
                    plan.successful_routes,
                    pending_routes=plan.final_pending_routes,
                )
            for track_id in plan.created_track_ids:
                published_tracks.append(new_tracks_by_id[track_id])
            if plan.clear_legacy_articulation:
                current_track.articulation_type = None
            for track_id, notes in plan.final_notes_by_track:
                track = tracks_by_id[track_id]
                if tuple(track.notes) == notes:
                    continue
                reconcile_track_game_velocity_records(track, notes)
                track.notes = list(notes)
                track.arrangement_clips = list(
                    reconcile_track_clips_after_note_edit(track, notes)
                )
                track.notes_optimized = False
            self.project_commands.push(before)
        except Exception:
            self._restore_transcription_track_checkpoint(
                published_tracks,
                track_checkpoint,
            )
            self.transcription_session.state = previous_state
            self.transcription_session.commands.restore_checkpoint(
                review_history
            )
            self.project_commands.restore_checkpoint(project_history)
            raise
        self._finish_transcription_commit(
            plan,
            request,
            current_track,
        )

    def _commit_note_editor(
        self,
        request: TranscriptionEditorCommit,
    ) -> TranscriptionEditorCommitReport | None:
        """Commit a normalized draft and staged routes as one project action."""

        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        current_track = tracks_by_id.get(int(request.current_track_id))
        draft_notes = self._normalise_editor_draft(request.draft_notes)
        if len(tracks_by_id) != len(self.tracks) or current_track is None or draft_notes is None:
            QMessageBox.warning(
                self,
                tr("无法应用音符编辑"),
                tr("目标轨道已经失效，或草稿包含无效音符。"),
            )
            return None

        if request.arrangement_clip_id:
            return self._commit_arrangement_clip_note_editor(
                request, current_track, draft_notes
            )

        state = self.transcription_session.state
        historical_track_ids = {
            int(route.track_id)
            for route in (*state.pending_routes, *state.applied_routes)
        }
        new_tracks_by_id, failed_new_track_ids = self._prepare_transcription_commit_tracks(
            request, tracks_by_id, historical_track_ids
        )
        try:
            plan = self._build_transcription_commit_plan(
                request,
                draft_notes,
                tracks_by_id,
                new_tracks_by_id,
                failed_new_track_ids,
            )
        except CommitPlanError:
            logging.exception("transcription commit preflight failed")
            QMessageBox.warning(
                self,
                tr("无法应用音符编辑"),
                tr("目标轨道已经失效，或草稿包含无效音符。"),
            )
            return None

        if plan.project_changed:
            try:
                self._apply_transcription_commit_plan(
                    plan,
                    request=request,
                    current_track=current_track,
                    tracks_by_id=tracks_by_id,
                    new_tracks_by_id=new_tracks_by_id,
                )
            except Exception:
                self._log_transcription_commit_failure("model publish")
                QMessageBox.warning(
                    self,
                    tr("无法应用音符编辑"),
                    tr("目标轨道已经失效，或草稿包含无效音符。"),
                )
                return None

        report = plan.report()
        if plan.project_changed:
            self._record_usage_feature("arrangement_edit")
        self._set_transcription_status(
            trf(
                "已应用 {created} 个音符 · 已满足 {satisfied} · "
                "保留失效 {invalid} · 孤立 {orphaned}",
                created=report.created_count,
                satisfied=report.satisfied_count,
                invalid=report.invalid_count,
                orphaned=report.orphaned_count,
            )
        )
        return report

    def _create_workspace_status_state(self) -> None:
        """Keep legacy status sinks without reserving a visible bottom bar."""

        # Async paths still publish status and diagnostic summaries through
        # these labels.  Toasts are the visible surface; the labels remain
        # hidden state owned by the workspace for compatibility with those
        # paths and tests.
        self.status_label = QLabel(tr("就绪"), self.workspace_page)
        self.status_label.setObjectName("Status")
        self.status_label.hide()
        self.inspector_text = QLabel("", self.workspace_page)
        self.inspector_text.setObjectName("InspectorText")
        self.inspector_text.hide()


    @staticmethod
    def _system_uses_dark_theme() -> bool:
        return system_uses_dark_theme()

    def _browse_midi(self) -> None:
        self._pick_midi()

    def _quick_convert_midi(self) -> None:
        if self.worker is not None or not self._pick_midi():
            return
        summary = trf(
            "{tracks} 轨 · {notes} 音符 · {numerator}/{denominator} 拍",
            tracks=len(self.tracks),
            notes=sum(len(track.notes) for track in self.tracks),
            numerator=self.time_sig,
            denominator=self.time_sig_denominator,
        )
        if not self.owner_id:
            summary += "\n" + tr("导出时需要读取 Owner ID。")
        choice = choose_prompt(
            self, tr("MIDI 转 BDO"), trf("曲谱：{name}", name=self.output_name.text()),
            (("edit", tr("继续编辑")), ("export", tr("导出 BDO"))),
            detail=summary, default="export", cancel="edit",
        )
        if choice == "export":
            self._convert()

    def _pick_midi(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择 MIDI 文件"),
            str(DEFAULT_MIDI_DIR),
            tr("MIDI 文件 (*.mid *.midi);;所有文件 (*.*)"),
        )
        return bool(path) and self._open_midi_path(Path(path))

    def _open_midi_path(self, path: Path) -> bool:
        import_settings = ConversionSettings.from_preferences(
            self.config.get("conversion_settings")
        )
        if not self._load_midi_info(
            str(path),
            conversion_settings=import_settings,
        ):
            self._record_usage_issue("import_failed")
            return False
        self.autosave_project_dir = None
        self.autosave_source_copy = None
        self.file_label.setProperty("i18nSkip", True)
        self.file_label.setProperty("i18nSkipText", True)
        self.file_label.setText(path.name)
        self.output_name.setText(path.stem)
        self.project_id = new_project_id()
        self._autosave_project("import midi", immediate=True)
        self._schedule_timeline_validation_refresh()
        self._record_recent("midi", path, path.stem)
        self._show_workspace()
        self._record_usage_feature("midi_import")
        repair_count = sum(
            int(repair.count)
            for repair in getattr(self, "_last_midi_import_repairs", ())
        )
        if repair_count:
            notice = trf(
                "MIDI 已载入 · 已兼容修复 {count} 个越界数据值；原文件未修改",
                count=repair_count,
            )
            self.status_label.setText(notice)
            self.inspector_text.setText(notice)
            self.show_toast(notice, kind="warning", duration_ms=5200)
        else:
            self.status_label.setText(tr("MIDI 已载入"))
            self.inspector_text.clear()
            self.show_toast(
                tr("MIDI 已载入，可在多音轨中继续编辑。"),
                kind="success",
                duration_ms=2800,
            )

        return True

    def _open_bdo_score_path(self, path: Path) -> None:
        if not self._load_bdo_info(path):
            self._record_usage_issue("import_failed")
            return
        self.project_id = new_project_id()
        self.autosave_project_dir = None
        self.autosave_source_copy = None
        self.file_label.setProperty("i18nSkip", True)
        self.file_label.setProperty("i18nSkipText", True)
        self.file_label.setText(path.name)
        self.output_name.setText(path.stem or path.name)
        self.midi_path = str(path)
        self._autosave_project("open bdo score", immediate=True)
        self._schedule_timeline_validation_refresh()
        self._record_recent("bdo", path, path.stem or path.name)
        self._show_workspace()
        self._record_usage_feature("project_open")

    def _load_bdo_info(self, path: Path) -> bool:
        try:
            document = read_score(path)
            snapshot = snapshot_from_decoded_score(document, allow_trailing_data=True)
            tracks = track_states_from_bdo_score(snapshot)
            if not tracks:
                raise ValueError(tr("游戏曲谱不包含乐器轨道"))
        except BdoUnsupportedVersionError as error:
            self.status_label.setText(tr("打开游戏曲谱失败"))
            self._show_bdo_version_notice(error)
            return False
        except Exception as exc:
            self.status_label.setText(tr("打开游戏曲谱失败"))
            message = trf("无法读取游戏曲谱：{error}", error=exc)
            self.inspector_text.setText(message)
            self.show_toast(message, kind="error", duration_ms=7000)
            return False

        self._close_all_note_editors()
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result = None
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(self.ui_preference_binding.reference_volume_percent, notify=False)
        self._set_reference_alignment(0.0, 0.0)
        self.reference_audio_path = ""
        self._set_reference_audio_relink_required(False)
        self._stop_preview()
        self.project_commands.clear()
        self._clear_track_selection()
        self.source_format = "bdo"
        self._reset_project_timeline_metadata()
        self.bdo_source_document = document
        self.bpm = int(snapshot.bpm)
        self.time_sig = int(snapshot.time_signature)
        self.time_sig_denominator = 4
        self.tempo_changes = 1
        self.lyric_events = []
        self.owner_id = int(snapshot.owner_id)
        self.char_name = snapshot.character_name_1 or snapshot.character_name_2 or self.char_name
        self._set_conversion_settings(
            ConversionSettings.bdo_import_defaults(),
            preserve_pitch_overrides=False,
        )
        settings = next((track.settings for track in snapshot.tracks if track.settings), ())
        if len(settings) >= 8:
            self.reverb = int(settings[1])
            self.delay = int(settings[3])
            chorus = (int(settings[5]), int(settings[6]), int(settings[7]))
            self.chorus = chorus if any(chorus) else None
        self.tracks = tracks
        self.selected_track = None
        self._refresh_tracks()
        self._reset_timeline_position()
        self.status_label.setText(tr("游戏曲谱已打开"))
        self.inspector_text.setText(trf(
            "已打开游戏曲谱：{file} · {tracks} 轨 · {notes} 音符",
            file=path.name,
            tracks=len(self.tracks),
            notes=sum(len(track.notes) for track in self.tracks),
        ))
        self._sync_preview_state()
        return True

    def _open_project(self) -> None:
        start_dir = str(AUTO_SAVE_DIR if AUTO_SAVE_DIR.is_dir() else ROOT)
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("打开工程或曲谱"),
            start_dir,
            ";;".join((
                tr("工程与曲谱 (*.json *.bdo *.bdom)"),
                tr("BDO 曲谱 (*.bdo *.bdom)"),
                tr("JSON 文件 (*.json)"),
                tr("所有文件 (*.*)"),
            )),
        )
        if not path:
            return
        document = Path(path)
        if document.suffix.casefold() in {".bdo", ".bdom"}:
            self._open_bdo_score_path(document)
        else:
            self._load_project(document)

    def _save_current_project(self) -> None:
        if not self.tracks:
            self.show_toast(tr("当前没有可保存的项目"))
            return
        self._autosave_project("manual save", immediate=True)
        if self.autosave_project_dir is not None:
            self._record_recent(
                "project",
                self.autosave_project_dir / "project.json",
                self.output_name.text().strip() or self.autosave_project_dir.name,
            )
        self.status_label.setText(tr("项目保存已排入队列"))

    def _save_project_as(self) -> None:
        if not self.tracks:
            self.show_toast(tr("当前没有可保存的项目"))
            return
        parent = QFileDialog.getExistingDirectory(
            self,
            tr("选择另存位置"),
            str(AUTO_SAVE_DIR),
        )
        if not parent:
            return
        if not self._wait_for_autosave_idle():
            QMessageBox.warning(
                self,
                tr("另存为失败"),
                tr("仍有项目写入正在进行，请稍后重试。"),
            )
            return
        project_name = safe_filename(
            self.output_name.text().strip(),
            tr("未命名项目"),
        )
        target = Path(parent) / project_name
        suffix = 2
        while target.exists():
            target = Path(parent) / f"{project_name}_{suffix}"
            suffix += 1
        self.project_id = new_project_id()
        self.autosave_project_dir = target
        self.autosave_source_copy = None
        self._autosave_project("save as", immediate=True)
        self._record_recent(
            "project",
            target / "project.json",
            self.output_name.text().strip() or project_name,
        )
        self.status_label.setText(tr("项目副本保存已排入队列"))

    def _project_snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot.capture(
            self.tracks,
            self.reverb,
            self.delay,
            self.chorus,
            self.transcription_session.to_payload(),
            self.transcription_assist_review.to_payload(),
            self._conversion_settings,
            self._pitch_transform_plan,
            self.lyric_events, self.research_metadata.get("timeline_markers", ()),
            self._capture_arrangement_selection(),
        )
    def _push_project_snapshot(self) -> None:
        self.project_commands.push(self._project_snapshot())

    def _restore_project_snapshot(self, snapshot: ProjectSnapshot, action: str) -> None:
        arrangement_selection = snapshot.restored_arrangement_selection() or self._capture_arrangement_selection()
        self._stop_preview(reset_playhead=False)
        tracks_changed = tuple(self.tracks) != snapshot.tracks
        if tracks_changed:
            self._close_all_note_editors()
        self.tracks = snapshot.restored_tracks()
        self.reverb, self.delay, self.chorus = snapshot.reverb, snapshot.delay, snapshot.chorus
        restored_conversion_settings = snapshot.restored_conversion_settings()
        if isinstance(restored_conversion_settings, ConversionSettings):
            self._set_conversion_settings(
                restored_conversion_settings,
                preserve_pitch_overrides=False,
            )
        restored_pitch_plan = snapshot.restored_pitch_transform_plan()
        if isinstance(restored_pitch_plan, PitchTransformPlan):
            self._pitch_transform_plan = restored_pitch_plan.with_global(
                self.transpose
            )
        restored_lyrics = snapshot.restored_lyric_events()
        if restored_lyrics is not None:
            self.lyric_events = list(restored_lyrics)
        restored_markers = snapshot.restored_timeline_markers()
        if restored_markers is not None:
            self.research_metadata["timeline_markers"] = list(restored_markers)
        restored_review = snapshot.restored_transcription_state()
        if restored_review is not None:
            self.transcription_session = TranscriptionSession.from_payload(
                restored_review,
                self.transcription_session.candidates,
                backend_id=(
                    self.transcription_result.evidence_descriptor.backend_id
                    if self.transcription_result is not None
                    and self.transcription_result.evidence_descriptor is not None
                    else ""
                ),
            )
        allow_assist_review_recovery = True
        restored_assist = snapshot.restored_transcription_assist_state()
        if restored_assist is not None:
            restored_assist_review = (
                TranscriptionAssistReviewState.from_payload(restored_assist)
            )
            current_audio_fingerprint = self._current_analysis_fingerprint()
            assist_identity_matches = bool(
                current_audio_fingerprint
                and restored_assist_review.audio_fingerprint
                == current_audio_fingerprint
            )
            self.transcription_assist_review = (
                isolate_assist_review_for_audio(
                    restored_assist_review,
                    current_audio_fingerprint,
                )
            )
            if not assist_identity_matches:
                allow_assist_review_recovery = False
                # Project undo may restore a sidecar captured for reference
                # audio that is no longer loaded.  Do not let current-song
                # candidates masquerade as the old recovery anchors and
                # reactivate its key/chord/voice decisions.
                self.transcription_assist_previous_candidates = ()
        self._clear_transcription_review_history()
        self.selected_track = None
        self._refresh_tracks()
        self._restore_arrangement_selection(arrangement_selection)
        self._synchronize_timeline_markers()
        self.timeline.set_time_range(
            *(
                self.transcription_session.state.region
                if self.transcription_session.state.region is not None
                else (None, None)
            )
        )
        if self.transcription_result is not None:
            self._start_transcription_assist_analysis(
                allow_review_recovery=allow_assist_review_recovery,
            )
            self._start_reference_timbre_analysis(force_restart=True)
        self._schedule_timeline_validation_refresh()
        self._autosave_project(action, immediate=True)
        self.status_label.setText(tr("已撤销工程修改" if action == "project undo" else "已重做工程修改"))

    def _undo_project(self) -> None:
        if self._route_focused_editor_history(redo=False):
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not focus.isReadOnly():
            focus.undo()
            return
        if not self._project_history_is_safe():
            return
        snapshot = self.project_commands.undo(self._project_snapshot())
        if snapshot is not None:
            self._restore_project_snapshot(snapshot, "project undo")

    def _redo_project(self) -> None:
        if self._route_focused_editor_history(redo=True):
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)) and not focus.isReadOnly():
            focus.redo()
            return
        if not self._project_history_is_safe():
            return
        snapshot = self.project_commands.redo(self._project_snapshot())
        if snapshot is not None:
            self._restore_project_snapshot(snapshot, "project redo")

    def _load_project(self, project_path: Path) -> None:
        try:
            project_text = project_path.read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("打开工程失败"),
                trf("无法读取工程文件：{error}", error=exc),
            )
            return

        try:
            plan = prepare_project_load(
                project_path,
                project_text,
                _TRACK_IMPORT_PRESENTATION,
                file_exists=lambda candidate: candidate.is_file(),
                midi_meter_reader=read_midi_time_signature_denominator,
            )
        except ProjectLoadError as exc:
            self._warn_project_load_error(exc)
            return
        self._commit_project_load(plan)

    def _warn_project_load_error(self, error: ProjectLoadError) -> None:
        if error.code is ProjectLoadErrorCode.MISSING_SOURCE:
            message = tr("工程里的源文件和自动保存副本都不存在。")
        elif error.code is ProjectLoadErrorCode.INVALID_SOURCE_REFERENCE:
            message = trf(
                "工程源文件路径无效（{path}）：{error}",
                path=error.path,
                error=error.detail,
            )
        elif error.code is ProjectLoadErrorCode.INVALID_TRACKS:
            message = trf(
                "工程轨道数据无效（{path}）：{error}",
                path=error.path,
                error=error.detail,
            )
        else:
            message = trf(
                "无法读取工程文件（{path}）：{error}",
                path=error.path,
                error=error.detail,
            )
        QMessageBox.warning(self, tr("打开工程失败"), message)

    def _commit_project_load(self, plan: ProjectLoadPlan) -> None:
        """Apply one fully prepared project plan as a single UI transition."""

        open_request = plan.open_request
        project_path = open_request.project_path
        midi_path = open_request.source_path
        source_format = open_request.source_format.value
        research_profile_id = (
            plan.research.profile_id or get_bdo_profile().profile_id
        )

        source_document = None
        if source_format == "bdo" and midi_path is not None:
            try:
                source_document = read_score(midi_path)
            except Exception:
                # The project snapshot remains authoritative. Only exact-byte
                # reuse is unavailable when its provenance cannot be reread.
                source_document = None

        loading_generation = self.project_lifecycle_controller.begin_loading(
            "restore project"
        )
        try:
            self.reference_audio.set_audio_path(None, notify=False)
            self.reference_audio.set_volume_percent(
                plan.reference.volume_percent,
                notify=False,
            )
            self._set_reference_alignment(
                plan.reference.offset_ms,
                plan.reference.beat_origin_ms,
            )
            self.reference_layer_settings = plan.reference.layers_payload()
            self.reference_audio_path = ""
            self._set_reference_audio_relink_required(False)
            self.project_id = open_request.project_id
            self.autosave_project_dir = project_path.parent
            self.autosave_source_copy = open_request.source_copy_path
            self.midi_path = str(midi_path) if midi_path is not None else ""
            self.file_label.setProperty(
                "i18nSkipText",
                True,
            )
            self.file_label.setProperty(
                "i18nSkip",
                True,
            )
            self.file_label.setText(
                midi_path.name
                if midi_path is not None
                else open_request.output_name
            )
            self.output_name.setText(open_request.output_name)
            self.research_metadata = {
                "profile_id": research_profile_id,
                "ab_experiments": plan.research.experiments_payload(),
                "timeline_markers": plan.research.timeline_markers_payload(),
            }
            # Project tracks/notes are authoritative for every provenance
            # type.  Never rebuild a project from MIDI/BDO and overlay it:
            # that resurrects deleted lanes and drops newly authored lanes.
            self._stop_preview()
            self.project_commands.clear()
            self._clear_track_selection()
            self._set_conversion_settings(
                plan.conversion,
                preserve_pitch_overrides=False,
            )
            self.reverb, self.delay, self.chorus = (
                plan.master_effects.legacy_values()
            )
            self.bdo_source_document = source_document
            self.bpm = plan.bpm
            self.time_sig = plan.time_signature
            self.time_sig_denominator = plan.time_signature_denominator
            self.tempo_changes = plan.tempo_changes
            self.tracks = list(plan.tracks)
            self._pitch_transform_plan = plan.pitch_plan
            self.source_format = source_format
            self.owner_id = plan.owner_id
            self.char_name = plan.character_name
            self.lyric_events = plan.lyric_payload()
            self._close_all_note_editors()
            self.transcription_result = None
            self.transcription_session = TranscriptionSession(
                state=plan.transcription_state,
            )
            self.transcription_assist_review = plan.assist_review
            self._clear_transcription_review_history()
            self.automatic_harmony_analysis = None
            self.automatic_instrument_match_analysis = None
            self.harmony_analysis = None
            self.instrument_match_analysis = None
            self._clear_reference_timbre_analysis(cancel_worker=True)
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.transcription_assist_previous_candidates = ()
            try:
                reference_audio_restored = bool(
                    plan.reference.candidate_path is not None
                    and self.reference_audio.set_audio_path(
                        plan.reference.candidate_path,
                        notify=False,
                    )
                )
            except Exception:
                reference_audio_restored = False
            if reference_audio_restored:
                self.reference_audio_path = self.reference_audio.audio_path
            self._set_reference_audio_relink_required(
                plan.reference.was_attached and not reference_audio_restored
            )
            self._refresh_tracks()
            self._reset_timeline_position()
            self.timeline.set_time_range(
                *(
                    self.transcription_session.state.region
                    if self.transcription_session.state.region is not None
                    else (None, None)
                )
            )
            if plan.reference.was_attached and not reference_audio_restored:
                self.status_label.setText(
                    tr("工程已恢复；参考音频未随工程保存，请重新载入。")
                )
            else:
                self.status_label.setText(tr("工程已恢复"))
            self.inspector_text.setText(trf("已恢复自动保存工程：{project}", project=project_path))
            self._sync_preview_state()
        finally:
            self.project_lifecycle_controller.finish_loading(
                loading_generation
            )
        self._autosave_project("restore project", immediate=True)
        self._schedule_timeline_validation_refresh()
        self._record_recent(
            "project",
            project_path,
            self.output_name.text() or project_path.parent.name,
        )
        self._show_workspace()
        self._record_usage_feature("project_open")

    def _apply_conversion_settings(
        self,
        settings: object,
        *,
        source_format: str = "midi",
        default_master: MasterEffects | None = None,
    ) -> None:
        master = default_master or MasterEffects()
        self.reverb, self.delay, self.chorus = master.legacy_values()
        payload = settings if isinstance(settings, dict) else {}
        self.char_name = payload.get("char_name", self.char_name)
        self._set_conversion_settings(
            ConversionSettings.from_project_payload(
                payload,
                source_format=source_format,
            ),
            preserve_pitch_overrides=False,
        )
        self.reverb = int(payload.get("reverb", master.reverb_time))
        self.delay = int(payload.get("delay", master.delay_feedback))
        if "chorus" in payload:
            saved_chorus = payload.get("chorus")
            if isinstance(saved_chorus, dict):
                self.chorus = (
                    int(saved_chorus.get("feedback", 0)),
                    int(saved_chorus.get("depth", 0)),
                    int(saved_chorus.get("freq", 0)),
                )
            else:
                self.chorus = tuple(saved_chorus) if saved_chorus else None

    def _conversion_settings_payload(self) -> dict:
        return {
            **self._conversion_settings.to_payload(),
            "char_name": self.char_name,
            "reverb": self.reverb,
            "delay": self.delay,
            "chorus": list(self.chorus) if self.chorus else None,
        }

    def _ensure_autosave_project(self) -> tuple[Path | None, Path | None]:
        self.project_id = normalize_project_id(self.project_id) or new_project_id()
        midi_path = Path(getattr(self, "midi_path", "") or "")
        if self.source_format == "project":
            if self.autosave_project_dir is None:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                project_name = safe_filename(self.output_name.text().strip(), "project")
                self.autosave_project_dir = AUTO_SAVE_DIR / f"{project_name}_{stamp}"
            self.autosave_source_copy = None
            return None, None
        if not midi_path.is_file():
            # Recovered project snapshots remain self-contained even when the
            # original provenance file and its old recovery copy are gone.
            if self.autosave_project_dir is None:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                project_name = safe_filename(
                    self.output_name.text().strip(),
                    "project",
                )
                self.autosave_project_dir = (
                    AUTO_SAVE_DIR / f"{project_name}_{stamp}"
                )
            self.autosave_source_copy = None
            return None, None
        if self.autosave_project_dir is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self.autosave_project_dir = AUTO_SAVE_DIR / f"{safe_filename(midi_path.stem)}_{stamp}"
        fallback_suffix = ".bdo" if self.source_format == "bdo" else ".mid"
        source_name = f"source{midi_path.suffix or fallback_suffix}"
        target = self.autosave_project_dir / source_name
        self.autosave_source_copy = target
        try:
            same_file = midi_path.resolve() == target.resolve()
        except OSError:
            same_file = False
        return (None, None) if same_file else (midi_path, target)

    def _autosave_project(self, reason: str, immediate: bool = False) -> bool:
        if immediate:
            self.pending_autosave_reason = reason
            self.autosave_timer.stop()
            return self._flush_autosave()
        self.pending_autosave_reason = reason
        self.autosave_timer.start(700)
        return True

    def _flush_autosave(self) -> bool:
        reason = self.pending_autosave_reason or "autosave"
        self.pending_autosave_reason = ""
        if (
            self.loading_project
            or (not self.tracks and self.autosave_project_dir is None)
        ):
            return False
        try:
            self._autosave_error = ""
            source_path, source_copy = self._ensure_autosave_project()
            if self.autosave_project_dir is None:
                return False
            saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
            source_reference = project_relative_file_reference(
                self.autosave_project_dir,
                self.autosave_source_copy,
            )
            metadata = ProjectMetadataSnapshot.capture(
                schema_version=CURRENT_PROJECT_SCHEMA,
                project_id=self.project_id,
                saved_at=saved_at,
                reason=reason,
                source_format=self.source_format,
                # Only the project-local recovery copy is serialized. External
                # MIDI/BDO and reference paths remain runtime-only choices.
                source_reference=source_reference,
                output_name=self.output_name.text().strip(),
                owner_id=self.owner_id,
                character_name=self.char_name,
                bpm=self.bpm,
                time_signature=self.time_sig,
                time_signature_denominator=self.time_sig_denominator,
                tempo_changes=self.tempo_changes,
                lyric_events=self.lyric_events,
                reference_audio_attached=bool(
                    self.reference_audio_path
                    or self.reference_audio_relink_required
                ),
                reference_audio_volume=self.reference_audio.volume_percent,
                reference_audio_offset_ms=self.reference_audio_offset_ms,
                beat_origin_ms=self.beat_origin_ms,
                transcription_review=self.transcription_session.to_payload(),
                transcription_assist_review=(
                    self.transcription_assist_review.to_payload()
                ),
                reference_layers=normalize_reference_layer_settings(
                    self.reference_layer_settings
                ),
                conversion_settings=self._conversion_settings_payload(),
                pitch_transform=self._pitch_transform_plan.pruned(
                    track.track_id for track in self.tracks
                ).to_payload(),
                research=self.research_metadata,
            )
            request = AutosaveRequest(
                project_dir=self.autosave_project_dir,
                metadata=metadata,
                tracks=freeze_project_tracks(self._autosave_track_view()),
                source_path=source_path,
                source_copy=source_copy,
            )
            self._queue_autosave_request(request)
            return True
        except Exception as exc:
            append_crash_log("Autosave failed", traceback.format_exc())
            self._autosave_error = str(exc) or type(exc).__name__
            self.status_label.setText(trf("自动保存失败：{error}", error=exc))
            return False

    def _queue_autosave_request(self, request: AutosaveRequest) -> None:
        worker = self.autosave_worker
        if worker is not None:
            # Autosave is a latest-state checkpoint. Coalesce intermediate
            # requests while the single disk writer drains the current one.
            self.pending_autosave_request = request
            return
        self._start_autosave_worker(request)

    def _wait_for_autosave_idle(self, timeout_ms: int = 30_000) -> bool:
        """Drain queued disk writes; used by tests and final process shutdown."""

        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        while self.autosave_worker is not None or self.pending_autosave_request is not None:
            worker = self.autosave_worker
            if worker is not None and worker.isRunning():
                remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
                if remaining_ms <= 0:
                    return False
                worker.wait(min(50, remaining_ms))
            QApplication.processEvents()
            if time.monotonic() >= deadline:
                return False
        return True

    def _wait_for_background_writers_on_quit(self) -> None:
        deadline = time.monotonic() + 30.0
        export_worker = self.worker
        if export_worker is not None and export_worker.isRunning():
            export_worker.wait(max(0, round((deadline - time.monotonic()) * 1000)))
        remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
        self._wait_for_autosave_idle(remaining_ms)

    def _open_midi_tool(self, request) -> None:
        if isinstance(request, TrackState):
            self._open_midi_optimizer(int(request.track_id))
        else:
            self._open_midi_optimizer(None)

    def _open_note_editor(
        self,
        track: TrackState,
        selected_note_indices: tuple[int, ...] = (),
        *,
        transcription_mode: bool = False,
        arrangement_clip_id: str = "",
    ) -> None:
        if track not in self.tracks:
            return
        if self.selected_track is not track:
            self._select_track(track)
        if not transcription_mode and not arrangement_clip_id:
            clips = track_clips(track)
            if len(clips) == 1:
                arrangement_clip_id = clips[0].clip_id
            elif len(clips) > 1:
                labels = [
                    trf(
                        "片段 {number} · {start:.3f}s–{end:.3f}s",
                        number=index + 1,
                        start=clip.start_ms / 1000.0,
                        end=clip.end_ms / 1000.0,
                    )
                    for index, clip in enumerate(clips)
                ]
                selected, accepted = choose_item(
                    self,
                    tr("选择要编辑的片段"),
                    tr("此轨道包含多个片段，请明确选择编辑范围："),
                    labels,
                )
                if not accepted:
                    return
                arrangement_clip_id = clips[labels.index(selected)].clip_id
        track_id = int(track.track_id)
        existing = next((
            value for value in self._note_editors.values()
            if int(value.track.track_id) == track_id
            and str(getattr(value, "arrangement_clip_id", "") or "")
            == arrangement_clip_id
        ), None)
        if existing is not None and (existing.isVisible() or existing.property("workbenchEmbedded")):
            if not existing.property("workbenchEmbedded"):
                existing.showNormal()
                existing.raise_()
                existing.activateWindow()
            self._activate_note_editor(existing)
            existing.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        editor_key: object = (
            track_id
            if track_id not in self._note_editors
            else (track_id, arrangement_clip_id)
        )
        editor_track = track
        editor_clip_scope = None
        if arrangement_clip_id:
            editor_clip_scope, editor_notes = prepare_clip_editor(track, arrangement_clip_id)
            # The editor owns its mutable metadata. Sibling notes and Clip
            # geometry have no role in that draft and need no deep copy.
            editor_track = deepcopy(replace(track, notes=[], arrangement_clips=[]))
            editor_track.notes = list(editor_notes)
        dialog = MidiNoteEditorDialog(
            self,
            editor_track,
            self.bpm_override or self.bpm,
            self.time_sig,
            self._effective_track_transpose(track),
            transcription_mode=transcription_mode,
            pitch_plan=self._pitch_transform_plan,
            clip_scope=editor_clip_scope,
            embedded_parent=None if transcription_mode else self.workbench.editors,
        )
        dialog.arrangement_clip_id = arrangement_clip_id
        dialog.arrangement_clip_fingerprint = (
            editor_clip_scope.fingerprint
            if editor_clip_scope is not None else ""
        )
        if arrangement_clip_id:
            dialog.clip_draft_changed.connect(
                lambda notes, current=dialog:
                self._sync_arrangement_clip_editor(current, notes)
            )
            dialog.clip_resize_requested.connect(
                lambda mode, value, current=dialog:
                self._resize_arrangement_clip_from_editor(
                    current, mode, value
                )
            )
        if selected_note_indices:
            dialog.canvas.selected = {
                index for index in selected_note_indices if 0 <= index < len(dialog.canvas.notes)
            }
            dialog.canvas.update()
            dialog.refresh_fields()
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._note_editors[editor_key] = dialog
        if not transcription_mode:
            self.workbench.attach_editor(dialog)
        self._activate_note_editor(dialog)
        if transcription_mode and self.transcription_session.candidates:
            QTimer.singleShot(0, self._start_reference_timbre_analysis)
        if (
            transcription_mode
            and self.transcription_session.state.cache_key
            and not self.transcription_session.candidates
            and self.workspace_transcription_worker is None
        ):
            QTimer.singleShot(0, self._restore_cached_transcription)
        def editor_finished(_result: int) -> None:
            self.workbench.editor_finished(dialog)
            if transcription_mode:
                self._invalidate_transcription_rhythm_diagnostic()
            if self.active_transcription_editor is dialog:
                self.active_transcription_editor = None
            if self._note_editors.get(editor_key) is dialog:
                self._note_editors.pop(editor_key, None)
            dialog.release_transcription_resources()
            if dialog._draft_autosave_revision > 0:
                # The editor may have been rejected after draft checkpoints.
                # With no active overlay, this request restores the formal
                # TrackState as the latest crash-recovery snapshot.
                self._autosave_project("note editor close", immediate=True)
            if transcription_mode:
                # A cancelled dialog may have launched a harmony snapshot from
                # draft notes.  Recompute from formal tracks so discarded
                # notes cannot leak into the persistent semantic view.
                self._schedule_transcription_assist_refresh()
        dialog.finished.connect(editor_finished)
        dialog.show()
        self._record_usage_feature("note_editor")
        dialog.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _open_clip_note_editor(
        self, track: TrackState, clip_id: str
    ) -> None:
        self._open_note_editor(track, arrangement_clip_id=str(clip_id))


    def _focus_validation_issue(self, issue: ValidationIssue) -> None:
        target_track_id = issue.track_id
        if target_track_id is None and issue.related_track_ids:
            target_track_id = issue.related_track_ids[0]
        if target_track_id is None:
            return
        track = next(
            (
                item
                for item in self.tracks
                if int(item.track_id) == int(target_track_id)
            ),
            None,
        )
        if track is None:
            return
        self._select_track(track)
        if issue.note_indices:
            # Validator indices address the projected whole-track sequence;
            # Clip editors use a local sequence and must not reuse them.
            self._open_note_editor(
                track,
                () if track.arrangement_clips else issue.note_indices,
            )

    def create_midi_optimize_dialog(
        self,
        target_track_id: int | None,
        *,
        source_tracks: list[TrackState] | None = None,
    ) -> "MidiOptimizeDialog":
        """Factory exposed to the extracted note editor host contract."""

        return MidiOptimizeDialog(
            self,
            target_track_id,
            source_tracks=source_tracks,
            scope_locked=True,
        )

    def persist_ui_config(self) -> None:
        """Persist UI preferences already updated by a child editor."""

        save_config(self.config)

    def _open_midi_optimizer(self, target_track_id: int | None = None) -> None:
        if not self.tracks:
            self.show_toast(tr("请先导入 MIDI。"))
            return
        scoped_tracks = (
            self.tracks
            if target_track_id is None
            else [
                track for track in self.tracks
                if int(track.track_id) == int(target_track_id)
            ]
        )
        if any(track.arrangement_clips for track in scoped_tracks):
            self.show_toast(
                tr("包含片段的轨道请双击具体片段，在音符编辑器中执行优化。"),
                kind="warning",
                duration_ms=4600,
            )
            return
        dialog = MidiOptimizeDialog(self, target_track_id)
        self._record_usage_feature("optimizer")
        if dialog.exec() != QDialog.Accepted:
            return
        applied_target_track_id = dialog.target_track_id
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks = dialog.optimized_tracks()
        optimized_effects = dialog.optimized_effects()
        if optimized_effects is not None:
            self.reverb, self.delay, self.chorus = optimized_effects
        self.selected_track = None
        self._refresh_tracks()
        self._schedule_timeline_validation_refresh()
        self._autosave_project("midi optimize", immediate=True)
        self._schedule_transcription_assist_refresh()
        scope = (
            trfv("轨道 {track_id}", track_id=applied_target_track_id)
            if applied_target_track_id is not None
            else trv("全局 MIDI")
        )
        self.status_label.setText(trf("{scope} 已优化", scope=scope))
        effect_text = "，并应用游戏声音效果建议" if optimized_effects is not None else ""
        self.show_toast(trf(
            "已应用 {scope} 优化{effects}。",
            scope=scope,
            effects=trv(effect_text) if effect_text else "",
        ), kind="success", duration_ms=3600)

    def _suggest_global_transpose(self) -> int | None:
        active = formal_score_tracks(self.tracks)
        pitches = [
            int(note.pitch)
            + self._pitch_transform_plan.resolve(
                track.track_id
            ).track_semitones
            for track in active
            if not track.is_percussion and track.bdo_instrument_id != 0x0d
            for note in track.notes
        ]
        if not pitches:
            return None
        low = min(pitches)
        high = max(pitches)
        if high - low > BDO_NOTE_MAX - BDO_NOTE_MIN:
            return None
        lower_bound = BDO_NOTE_MIN - low
        upper_bound = BDO_NOTE_MAX - high
        if lower_bound <= self.transpose <= upper_bound:
            return None
        if lower_bound <= 0 <= upper_bound:
            return 0
        return lower_bound if abs(lower_bound) <= abs(upper_bound) else upper_bound

    def _analyze_conversion(self) -> dict:
        issues = self._validation_issues()
        structured_report = issues_report(
            issues,
            translate=tr,
            format_translate=trf,
        )
        profile = get_bdo_profile()
        raw_evidence_status = profile.evidence.status
        status_source = evidence_status_source(raw_evidence_status)
        report = trf(
            "BDO Profile: {profile} · {status}\n时间差比较容差: {tolerance} ms\n\n{report}",
            profile=profile.profile_id,
            status=(
                trv(status_source)
                if status_source is not None
                else raw_evidence_status
            ),
            tolerance="0.001",
            report=structured_report,
        )
        issue_count = sum(item.severity == "error" for item in issues)
        warning_count = sum(item.severity == "warning" for item in issues)
        invalid_fx = sum(item.fix_id == "clear_track_articulation" for item in issues)
        suggested_transpose = self._suggest_global_transpose()
        fixable_count = invalid_fx + (1 if suggested_transpose is not None else 0)
        return {
            "report": report,
            "issues": issues,
            "issue_count": issue_count,
            "warning_count": warning_count,
            "invalid_fx": invalid_fx,
            "suggested_transpose": suggested_transpose,
            "fixable_count": fixable_count,
        }

    def _validation_issues(self) -> tuple[ValidationIssue, ...]:
        active_ids = frozenset(
            int(track.track_id) for track in formal_score_tracks(self.tracks)
        )
        context = ValidationContext(
            transpose=int(self.transpose),
            active_track_ids=active_ids,
            instrument_names=_ui_bdo_instrument_names(),
            gm_drum_map=_GM_TO_BDO_DRUM,
            serialize_instrument=serialized_bdo_instrument_id,
            sample_only_percussion_ids=frozenset(BDO_SAMPLE_ONLY_PERCUSSION),
            velocity_mode=str(self.velocity_mode),
            effects=(int(self.reverb), int(self.delay), self.chorus),
            pitch_plan=self._pitch_transform_plan,
        )
        active_localizer = localizer()
        scope_key = (
            active_localizer.language
            if active_localizer is not None
            else "source"
        )
        return self.conversion_validation_controller.snapshot(
            revision=self.model_revision.value,
            scope_key=scope_key,
            tracks=self.tracks,
            profile=get_bdo_profile(),
            context=context,
        ).issues

    def _show_about(self) -> None:
        dialog = AboutDialog(parent=self)
        exec_floating_panel(dialog)
        dialog.deleteLater()

    def _show_feedback(self) -> None:
        dialog = FeedbackDialog(self, tracker=self.feedback_status)
        exec_floating_panel(dialog)
        dialog.deleteLater()

    def _show_release_notes(self) -> None:
        if not RELEASE_NOTES_UI_ENABLED:
            return
        dialog = getattr(self, "_release_notes_dialog", None)
        if dialog is None:
            dialog = ReleaseNotesDialog.from_resource(parent=self)
            self._release_notes_dialog = dialog
        dialog.exec()

    def _load_midi_info(
        self,
        path: str,
        *,
        conversion_settings: ConversionSettings | None = None,
    ) -> bool:
        settings = conversion_settings or self._conversion_settings
        self._last_midi_import_repairs = ()
        try:
            imported = prepare_midi_import(path, settings)
        except Exception as exc:
            self.status_label.setText(tr("载入失败"))
            self.inspector_text.setText(trf("MIDI 载入失败：{error}", error=exc))
            return False

        # Everything above this point is read-only.  Commit only after the
        # complete source has parsed and transformed successfully so a broken
        # import cannot erase the user's open score or its undo history.
        self._stop_preview()
        self.project_commands.clear()
        self._clear_track_selection()
        self._close_all_note_editors()
        self.reference_layer_settings = normalize_reference_layer_settings(
            DEFAULT_REFERENCE_LAYER_SETTINGS
        )
        self.transcription_session = TranscriptionSession()
        self.transcription_result = None
        self.reference_audio.set_audio_path(None, notify=False)
        self.reference_audio.set_volume_percent(self.ui_preference_binding.reference_volume_percent, notify=False)
        self._set_reference_alignment(0.0, 0.0)
        self.reference_audio_path = ""
        self._set_reference_audio_relink_required(False)
        self.midi_path = str(path)
        self.bpm = imported.bpm
        self.source_format = "midi"
        self._reset_project_timeline_metadata()
        self.bdo_source_document = None
        # A raw MIDI has no BDO master-effect layer. Starting from neutral
        # values prevents the previously open score from leaking into it.
        self._reset_master_effects()
        self.time_sig = imported.time_signature
        self.time_sig_denominator = imported.time_signature_denominator
        self.tempo_changes = imported.tempo_changes
        self.lyric_events = list(imported.lyric_events)
        self.tracks = list(imported.tracks)
        self._last_midi_import_repairs = tuple(
            imported.compatibility_repairs
        )
        self._set_conversion_settings(
            imported.conversion_settings,
            preserve_pitch_overrides=False,
        )
        self._refresh_tracks()
        self._reset_timeline_position()
        self.status_label.setText(tr("MIDI 已载入"))
        self._show_project_summary()
        self._sync_preview_state()
        return True

    def _clear_track_selection(self) -> None:
        self.selected_track = None
        if hasattr(self, "timeline") and self.timeline.selected_track is not None:
            self.timeline.set_selected_track(None)
        if hasattr(self, "workbench"):
            self.workbench.select_track(None)
        if hasattr(self, "project_note_status"):
            self.project_note_status.setText(tr("未选择轨道"))
        self._sync_toolbar_global_gain()

    def _refresh_tracks(self) -> None:
        self._apply_workspace_change(ModelChange.structure())
    def _apply_workspace_change(self, change: ModelChange) -> None:
        self._apply_workspace_refresh(
            self.workspace_refresh_controller.plan((change,))
        )

    def _apply_workspace_refresh(self, plan: RefreshPlan) -> None:
        apply_workspace_refresh(self, plan)

    def _on_track_changed(self, *, model_changed: bool = True) -> None:
        """Compatibility adapter for callers not yet carrying track scope."""

        self._apply_workspace_refresh(RefreshPlan(
            advance_revision=model_changed,
            refresh_view=True,
            refresh_grid=True,
            refresh_metadata=True,
            refresh_ensemble=True,
            refresh_transcription=True,
            refresh_validation=True,
            refresh_preview=model_changed,
        ))

    def _restart_preview_after_timeline_change(
        self,
        change: ModelChange | None = None,
    ) -> None:
        was_playing = self.realtime_preview_active and self.realtime_audio.status.state == "playing"
        current_ms = self.timeline.playhead_ms
        if self.realtime_preview_active:
            self._stop_preview(reset_playhead=False)
        self._apply_workspace_change(change or ModelChange.structure())
        if was_playing:
            self._start_preview_from(current_ms)

    def _on_track_filter_changed(self) -> None:
        self._restart_preview_after_timeline_change()
        self._autosave_project("track filter")

    def _on_game_instrument_volume_committed(
        self,
        track: TrackState,
        previous_volume: int,
        next_volume: int,
    ) -> None:
        """Commit one game-instrument Volume edit as a shared project action."""

        track.bdo_track_volume = int(previous_volume)
        self._push_project_snapshot()
        track.bdo_track_volume = int(next_volume)
        try:
            changed_ids = propagate_game_instrument_mix(
                self.tracks,
                track,
                volume=True,
                sends=False,
            )
        except (TypeError, ValueError) as exc:
            track.bdo_track_volume = int(previous_volume)
            self.timeline.update()
            self._sync_toolbar_global_gain(track)
            self.show_toast(
                trf("无法同步游戏乐器音量：{error}", error=exc),
                kind="error",
            )
            return
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change()
        self._autosave_project("game instrument volume")
        if changed_ids:
            self.show_toast(
                trf(
                    "已同步 {count} 条同乐器轨道的游戏音量",
                    count=len(changed_ids),
                ),
                kind="success",
            )
        self._sync_toolbar_global_gain(track)

    def _on_preview_mapping_changed(self) -> None:
        self._restart_preview_after_timeline_change()
        self._autosave_project("track mapping")

    def _unify_game_instrument_mix(self, source: TrackState) -> None:
        """Explicitly resolve legacy mixer conflicts using the chosen lane."""

        try:
            source_mix = (
                int(source.bdo_track_volume),
                raw_track_settings(source.bdo_track_settings),
            )
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("所选轨道的游戏混音数据无效：{error}", error=exc),
                kind="error",
            )
            return
        del source_mix
        self._push_project_snapshot()
        try:
            changed_ids = propagate_game_instrument_mix(
                self.tracks,
                source,
                volume=True,
                sends=True,
            )
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法统一游戏乐器混音：{error}", error=exc),
                kind="error",
            )
            return
        if not changed_ids:
            self.show_toast(tr("同乐器轨道已经一致"), kind="info")
            return
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change()
        self._autosave_project("unify game instrument mixer", immediate=True)
        self.show_toast(
            trf(
                "已按所选轨道统一 {count} 条同乐器轨道",
                count=len(changed_ids),
            ),
            kind="success",
        )

    def _on_track_instrument_changed(
        self,
        track: TrackState,
        previous_instrument_id: int,
    ) -> None:
        next_instrument_id = int(track.bdo_instrument_id)
        previous_mode = str(track.marnian_synth_mode)
        track.bdo_instrument_id = int(previous_instrument_id)
        self._push_project_snapshot()
        track.bdo_instrument_id = next_instrument_id
        if track.bdo_instrument_id not in BDO_ARTICULATIONS:
            track.articulation_type = None
        if track.bdo_instrument_id not in MARNIAN_SYNTH_INSTRUMENT_IDS:
            track.marnian_synth_mode = "basic"
        try:
            inherited_from = inherit_game_instrument_mix(self.tracks, track)
        except (TypeError, ValueError) as exc:
            track.bdo_instrument_id = int(previous_instrument_id)
            track.marnian_synth_mode = previous_mode
            self.timeline.update()
            self.show_toast(
                trf("目标游戏乐器存在混音冲突：{error}", error=exc),
                kind="error",
            )
            return
        self._apply_workspace_change(ModelChange.structure())
        for editor in tuple(self._note_editors.values()):
            if int(editor.track.track_id) == int(track.track_id):
                editor.refresh_game_instrument_identity(next_instrument_id)
        self._select_track(track)
        self._refresh_transcription_workspace()
        self._schedule_timeline_validation_refresh()
        self._on_preview_mapping_changed()
        if inherited_from is not None:
            self.show_toast(
                tr("已采用目标游戏乐器的共享音量和 FX"),
                kind="success",
            )

    def _reserved_track_ids(self) -> set[int]:
        """Return every ID that still has project or route-history meaning."""

        reserved = {int(track.track_id) for track in self.tracks}
        session = getattr(self, "transcription_session", None)
        state = getattr(session, "state", None)
        if state is not None:
            reserved.update(
                int(route.track_id)
                for route in (
                    *state.pending_routes,
                    *state.applied_routes,
                )
            )
        return reserved

    def _create_track(self, instrument_id: int) -> None:
        self._stop_preview(reset_playhead=False)
        track_id = max(self._reserved_track_ids(), default=-1) + 1
        instrument_name = _ui_bdo_instrument_name(instrument_id)
        track = TrackState(
            track_id=track_id,
            notes=[],
            gm_program=0,
            is_percussion=instrument_id == 0x0D,
            display_name=trf(
                "新建轨道 {number} · {instrument}",
                number=track_id + 1,
                instrument=instrument_name,
            ),
            bdo_instrument_id=instrument_id,
            color=TRACK_COLORS[track_id % len(TRACK_COLORS)],
            effect_settings_placeholder={
                "track_effects_enabled": False,
                "note_effects_reserved": True,
            },
            arrangement_clips=[default_empty_clip(
                track_id,
                duration_ms=(
                    60_000.0
                    / max(1, int(self.bpm_override or self.bpm))
                    * max(1, int(self.time_sig))
                ),
            )],
        )
        try:
            inherit_game_instrument_mix((*self.tracks, track), track)
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法新建同乐器轨道：{error}", error=exc),
                kind="error",
            )
            return
        self._push_project_snapshot()
        self.tracks.append(track)
        self._select_track(track)
        self._apply_workspace_change(ModelChange.structure())
        self._schedule_timeline_validation_refresh()
        self._autosave_project("create track", immediate=True)
        self.status_label.setText(trf(
            "已新建 Track {track_id} · {instrument}",
            track_id=track_id,
            instrument=trv(_ui_bdo_instrument_source(instrument_id)),
        ))
        self.show_toast(
            tr("空轨道已创建；双击轨道可进入音符编辑器添加音符。"),
            kind="success",
        )

    def _delete_selected_track(self) -> None:
        track = self.selected_track
        if track is None or track not in self.tracks:
            QMessageBox.information(
                self,
                tr("删除轨道"),
                tr("请先在时间轴中选择要删除的轨道。"),
            )
            return
        answer = QMessageBox.question(
            self,
            tr("删除轨道"),
            trf(
                "确定删除“{track}”及其中的 {count} 个音符吗？\n此操作可通过自动保存工程恢复。",
                track=track.display_name,
                count=len(project_track_notes(track)),
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._push_project_snapshot()
        self._stop_preview(reset_playhead=False)
        self.tracks.remove(track)
        self._pitch_transform_plan = self._pitch_transform_plan.without_track(
            track.track_id
        )
        self._clear_track_selection()
        self._apply_workspace_change(ModelChange.structure())
        self._schedule_timeline_validation_refresh()
        self._autosave_project("delete track", immediate=True)
        if track.notes:
            self._schedule_transcription_assist_refresh()
        self.status_label.setText(trf("已删除 {track}", track=track.display_name))
        self.inspector_text.clear()
        self.show_toast(tr("轨道已删除。请选择其他轨道，或新建一条空轨道。"))

    def _delete_requested_track(self, track: TrackState) -> None:
        if track not in self.tracks:
            return
        self._select_track(track)
        self._delete_selected_track()

    def _select_track(self, track: TrackState | None) -> None:
        if track is None:
            self._clear_track_selection()
            self.inspector_text.clear()
            return
        self.selected_track = track
        if hasattr(self, "workbench"):
            self.workbench.select_track(track)
        if self.timeline.selected_track is not track:
            self.timeline.set_selected_track(track)
        if hasattr(self, "project_note_status"):
            note_summary = trf("{count} 个音符", count=track.note_count)
            self.project_note_status.setText(
                f"{track.display_name} · BDO "
                f"{_ui_bdo_instrument_name(track.bdo_instrument_id)} · "
                f"{note_summary}"
            )
        self.timeline.update()

    def _show_project_summary(self) -> None:
        notes = [
            note for track in self.tracks for note in project_track_notes(track)
        ]
        end_ms = max(
            (note.start + note.dur for note in notes), default=0.0
        )
        minutes, seconds = divmod(int(end_ms / 1000), 60)
        pitch = "-"
        if notes:
            pitch = f"{note_name(min(n.pitch for n in notes))} - {note_name(max(n.pitch for n in notes))}"
        self.inspector_text.setText(trf(
            "{file} · {tracks} 轨 · {notes} 音符 · {minutes}m {seconds:02d}s · {pitch}",
            file=Path(getattr(self, "midi_path", "")).name, tracks=len(self.tracks),
            notes=len(notes), minutes=minutes, seconds=seconds, pitch=pitch,
        ))

    def _show_track_pitch_dialog(self, track: TrackState) -> None:
        if (
            track not in self.tracks
            or track.is_percussion
            or int(track.bdo_instrument_id) == 0x0D
        ):
            return
        self.selected_track = track
        dialog = TrackPitchDialog(self, track, self._pitch_transform_plan)
        if dialog.exec() != QDialog.Accepted:
            return
        apply_track_pitch(self, track, dialog.selected_semitone_offset())

    def _show_effects_placeholder(self, track: TrackState) -> None:
        self.selected_track = track
        dialog = TrackFxDialog(self, track)
        if dialog.exec() != QDialog.Accepted:
            return
        apply_track_fx(self, track, dialog)
        if hasattr(self, "workbench"):
            self.workbench.inspector.refresh(self.selected_track)

    def _clear_solo(self) -> None:
        for track in self.tracks:
            track.solo = False
        self._refresh_tracks()
        self._on_track_filter_changed()

    def _unmute_all(self) -> None:
        for track in self.tracks:
            track.muted = False
        self._refresh_tracks()
        self._on_track_filter_changed()

    def _fit_timeline(self) -> None:
        self.ui_preference_binding.reset_timeline_position(fit=True)
        self._apply_workspace_change(ModelChange.view())

    def _reset_timeline_position(self) -> None:
        if not hasattr(self, "timeline"):
            return
        self.ui_preference_binding.reset_timeline_position()

    def _sync_preview_state(self) -> None:
        tracks = list(preview_tracks(self.tracks))
        has_reference = bool(self.reference_audio.audio_path)
        bdo_running = self.realtime_preview_active
        bdo_loading = self.realtime_preview_loading
        reference_state = self.reference_audio.player.playbackState()
        reference_running = self.reference_audio.is_playing or reference_state != QMediaPlayer.PlaybackState.StoppedState
        running = bdo_running or reference_running
        paused = running and (
            self.preview_transport_coordinator.pause_requested
            if bdo_loading
            else (
                (not bdo_running or self.realtime_audio.status.state != "playing")
                and not self.reference_audio.is_playing
            )
        )
        can_play = bool(tracks) or has_reference
        self.play_button.setEnabled(can_play and (not running or paused))
        play_label = tr("播放" if can_play else "无法原声试听")
        self.play_button.setAccessibleName(play_label)
        self.play_button.setToolTip(play_label)
        if hasattr(self, "preview_source_menu"):
            if self.preview_source_menu.parentWidget().isVisible():
                self._refresh_preview_source_status(tracks)
            else:
                self._sync_preview_source_menu()
        self.pause_button.setEnabled(running and not paused)
        self.stop_button.setEnabled(running)

    def _set_preview_source_mode(self, mode: str) -> None:
        selected_mode = str(mode or "").casefold()
        if selected_mode not in PREVIEW_SOURCE_MODES:
            return
        if selected_mode == "pack":
            sample_pack, audio_root = source_paths_for_mode(
                self.audio_sources, selected_mode
            )
            if not sample_pack and not audio_root:
                self._sync_preview_source_menu()
                self._open_settings(2, selected_mode)
                return
        if selected_mode == preview_source_mode(self.audio_sources):
            self._sync_preview_source_menu()
            self._sync_preview_state()
            return
        was_playing = bool(
            self.realtime_preview_active or self.reference_audio.is_playing
        )
        retained_position = self.timeline.playhead_ms
        self._stop_preview(reset_playhead=False)
        activate_audio_source(self.audio_sources, selected_mode)
        self.realtime_audio.set_source_config(self.audio_sources)
        self.config["audio_sources"] = dict(self.audio_sources)
        save_config(self.config)
        self._sync_preview_source_menu()
        self._sync_preview_state()
        label = {
            "generic": "内置通用音源",
            "pack": "音源包",
        }[selected_mode]
        self.show_toast(
            trf("试听音源已切换：{source}", source=tr(label)),
            kind="success",
        )
        if was_playing and preview_tracks(self.tracks):
            QTimer.singleShot(
                0, lambda position=retained_position:
                self._start_preview_from(position)
            )

    def _preview_pack_location_error(self, tracks: list[TrackState]) -> str:
        if not tracks:
            return tr("没有可试听轨道")
        if not BDO_SAMPLE_MAP_PATH.is_file():
            return tr("缺少解包后的 BDO Wwise 映射")
        if not self.audio_sources.get("audio_root") or not Path(self.audio_sources["audio_root"]).is_dir():
            return trf(
                "BDO 音源目录不可用：{path}",
                path=self.audio_sources.get("audio_root", ""),
            )
        return ""

    def _realtime_preview_blockers(self, tracks: list[TrackState]) -> list[str]:
        location_error = self._preview_pack_location_error(tracks)
        if location_error:
            return [location_error]
        try:
            sources: dict[tuple[int, str], str] = {}
            for track in tracks:
                mode = str(getattr(track, "marnian_synth_mode", "basic") or "basic")
                sources.setdefault((track.bdo_instrument_id, mode), track.display_name)
            sample_map = BdoSampleMap(
                BDO_SAMPLE_MAP_PATH,
                self.audio_sources["audio_root"],
                instrument_modes=sources,
            )
            for (instrument_id, mode), track_name in sources.items():
                if not sample_map.has_instrument(instrument_id, mode):
                    return [tr("存在未绑定已命名游戏 BNK 的乐器")]
                if not sample_map.has_complete_media(instrument_id, mode):
                    return [
                        trf(
                            "{track} 的 {mode} 游戏 WAV 音源不完整",
                            track=track_name,
                            mode=mode,
                        )
                    ]
        except Exception as exc:
            return [trf("无法读取游戏采样映射：{error}", error=exc)]
        return []

    @staticmethod
    def _validation_state(tracks: list[TrackState], unverified: list[str]) -> str:
        """Return verified only when every selected instrument/ntype A/B cell passed."""
        if unverified or not AUDIO_VALIDATION_PATH.is_file():
            return "approximate"
        try:
            payload = json.loads(AUDIO_VALIDATION_PATH.read_text(encoding="utf-8"))
            passed = verified_instrument_articulations(
                payload,
                sample_map_evidence_sha256(BDO_SAMPLE_MAP_PATH),
            )
        except (OSError, ValueError, TypeError, KeyError):
            return "approximate"
        required = {
            (track.bdo_instrument_id, int(getattr(note, "ntype", 0) or track.articulation_type or 0))
            for track in tracks for note in track.notes
        }
        return "verified" if required and required.issubset(passed) else "approximate"

    def _stop_bdo_audio(self) -> None:
        # Kept as a compatibility shim for callers that previously stopped the
        # temporary-file preview player.
        if self.realtime_preview_active:
            try:
                # Ordinary transport Stop must discard queued PCM, but closing
                # the sink and decode pools here makes every subsequent play a
                # cold start.  ``closeEvent`` still calls the full engine stop.
                self.realtime_audio.clear_playback()
            except AudioEngineError:
                pass

    def _play_preview(self) -> None:
        self._claim_playback_focus(None)
        action = self.preview_transport_coordinator.play_action()
        if action is PreviewPlayAction.WAIT_FOR_LOAD:
            resume_reference = self.preview_transport_coordinator.pause_requested
            self.preview_transport_coordinator.request_play()
            if resume_reference:
                self._sync_reference_to_position(
                    self.realtime_preview_start_ms, play=True, force=True,
                )
                if self.reference_audio.is_playing:
                    self.reference_status_timer.start()
                self._sync_preview_state()
            self.status_label.setText(
                tr(
                    "正在准备通用 MIDI 预览…"
                    if self.realtime_preview_source == "generic"
                    else "正在准备游戏音源…"
                )
            )
            return
        if action is PreviewPlayAction.RESUME:
            self.preview_transport_coordinator.request_play()
            try:
                self.realtime_audio.play()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
            self._sync_reference_to_position(
                self.realtime_audio.get_status().position_ms,
                play=True,
                force=True,
            )
            self.realtime_status_timer.start()
            self.status_label.setText(tr("试听播放"))
            self._sync_preview_state()
            return
        self._start_preview_from(self.timeline.playhead_ms)

    def _start_preview_from(self, start_ms: float) -> None:
        loop_range = (
            self.timeline.time_range
            if self.timeline_loop_box.isChecked()
            else None
        )
        if loop_range is not None and not (
            loop_range[0] <= start_ms < loop_range[1]
        ):
            start_ms = loop_range[0]
            self.timeline.set_playhead(start_ms)
        source_tracks = list(preview_tracks(self.tracks))
        if not source_tracks:
            if self.reference_audio.audio_path:
                self._start_reference_audio_from(start_ms)
                return
            QMessageBox.warning(
                self,
                tr("没有可试听轨道"),
                tr("当前没有可试听轨道，请取消静音或 Solo。"),
            )
            return
        if not self.realtime_audio.available():
            # QAudioSink construction can block inside the Windows backend when
            # the machine has no output device.  Fail before starting either
            # the real-time engine or the reference QMediaPlayer.
            self.status_label.setText(tr("无可用音频设备"))
            self.show_toast(tr("无可用音频设备"), kind="warning")
            self._sync_preview_state()
            return
        if start_ms >= self.timeline._timeline_end_ms() - 1:
            start_ms = 0.0
            self.timeline.set_playhead(0.0)
        self.preview_transport_coordinator.invalidate()
        self.last_reported_underruns = 0
        source_mode = preview_source_mode(self.audio_sources)
        use_generic = source_mode == "generic"
        blockers = self._realtime_preview_blockers(source_tracks) if not use_generic else []
        if source_mode == "pack":
            self._preview_pack_diagnostic = (
                (self._preview_pack_scope(source_tracks), defer_tr(blockers[0]))
                if blockers else None
            )
        if source_mode == "pack" and blockers:
            self.status_label.setText(tr("音源包不可用"))
            self.show_toast(
                trf(
                    "当前音源包无法试听：{reason}",
                    reason=blockers[0],
                ),
                kind="warning",
                duration_ms=4400,
            )
            self._sync_preview_state()
            return
        tracks = self._project_tracks_for_preview(source_tracks)
        try:
            if use_generic:
                self.realtime_audio.load_procedural_project_async(
                    tracks,
                    start_ms,
                    self.reverb,
                    self.delay,
                    self.chorus,
                )
                self.realtime_preview_source = "generic"
            else:
                self.realtime_audio.load_project_async(
                    tracks,
                    BDO_SAMPLE_MAP_PATH,
                    start_ms,
                    self.reverb,
                    self.delay,
                    self.chorus,
                )
                self.realtime_preview_source = "bdo"
        except AudioEngineError as exc:
            self._on_preview_failed(str(exc))
            self._sync_preview_state()
            return
        self.preview_transport_coordinator.begin_loading(
            start_ms=start_ms,
            tracks=tracks,
            source=self.realtime_preview_source,
            advance=False,
        )
        self.timeline.set_buffer_progress(0.0, True)
        self.realtime_status_timer.start()
        # Use the reference clock until the real-time engine is ready.
        self._sync_reference_to_position(start_ms, play=True, force=True)
        if self.reference_audio.is_playing:
            self.reference_status_timer.start()
        self.status_label.setText(
            tr(
                "正在准备通用 MIDI 预览…"
                if use_generic
                else "正在准备游戏音源…"
            )
        )
        self._sync_preview_state()

    def _pause_preview(self) -> None:
        self.preview_transport_coordinator.request_pause()
        reference_was_playing = self.reference_audio.is_playing
        if self.realtime_preview_active and not self.realtime_preview_loading:
            try:
                self.realtime_audio.pause()
                status = self.realtime_audio.get_status()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
            # Freeze the transport at the engine's acknowledged pause frame.
            # Leaving the 60 FPS poller alive lets one or more queued timeout
            # callbacks advance the timeline after Pause has returned.
            self.realtime_status_timer.stop()
            self.timeline.set_playhead(status.position_ms, follow=True)
            self.timeline.set_track_levels({})
        self.reference_audio.pause()
        self.reference_status_timer.stop()
        if reference_was_playing and (
            self.realtime_preview_loading or not self.realtime_preview_active
        ):
            self.timeline.set_playhead(self.reference_audio.project_position_ms, follow=True)
            if self.realtime_preview_loading:
                self.realtime_preview_start_ms = self.timeline.playhead_ms
        self.status_label.setText(tr("试听暂停"))
        self._sync_preview_state()

    def _stop_preview(self, reset_playhead: bool = False) -> None:
        retained_position = self.timeline.playhead_ms if hasattr(self, "timeline") else 0.0
        self.preview_transport_coordinator.invalidate()
        self._stop_bdo_audio()
        self.reference_audio.stop()
        self.reference_status_timer.stop()
        self.preview_transport_coordinator.clear_session(advance=False)
        if hasattr(self, "timeline"):
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
        self.realtime_status_timer.stop()
        if reset_playhead and hasattr(self, "timeline"):
            self._reset_timeline_position()
        elif self.reference_audio.audio_path:
            self.reference_audio.set_position(retained_position)
        if hasattr(self, "status_label"):
            self.status_label.setText(tr("就绪"))
        if hasattr(self, "play_button"):
            self._sync_preview_state()

    def _on_preview_failed(self, message: str, generation: int | None = None) -> None:
        if (
            generation is not None
            and not self.preview_transport_coordinator.is_current(generation)
        ):
            return
        self._record_usage_issue("preview_failed")
        QMessageBox.warning(self, tr("试听不可用"), message)

    def _poll_realtime_audio_status(self) -> None:
        if not self.realtime_preview_active:
            return
        try:
            if self.realtime_preview_loading:
                preload_status = self.realtime_audio.get_status()
                self.timeline.set_buffer_progress(
                    preload_status.preload_progress if preload_status.preload_total else 0.0,
                    True,
                )
                result = self.realtime_audio.finish_loading(self.realtime_preview_start_ms)
                if result is None:
                    return
                self.timeline.set_buffer_progress(1.0, True)
                details = result.get("unverified", [])
                self.preview_transport_coordinator.mark_ready(
                    self._validation_state(self.realtime_preview_tracks, details)
                )
                self._extend_arrangement_clock_for_reference()
                resume_position = self.realtime_preview_start_ms
                if self.reference_audio.is_playing:
                    resume_position = max(
                        0.0, self.reference_audio.project_position_ms
                    )
                    if abs(resume_position - self.realtime_preview_start_ms) > 1.0:
                        self.realtime_audio.seek(resume_position)
                if self.preview_transport_coordinator.pause_requested:
                    self.reference_audio.pause()
                    self.reference_status_timer.stop()
                    self.realtime_status_timer.stop()
                    self.timeline.set_buffer_progress(1.0, False)
                    self.status_label.setText(tr("试听暂停"))
                    self._sync_preview_state()
                    return
                self.realtime_audio.play()
                self._record_usage_feature("preview")
                self.reference_status_timer.stop()
                self._sync_reference_to_position(
                    resume_position,
                    play=True,
                    force=False,
                )
                self.status_label.setText(
                    tr("通用 MIDI 预览（非游戏原声）")
                    if self.realtime_preview_source == "generic"
                    else (
                        tr("BDO 实时原声试听")
                        if not details
                        else trf(
                            "BDO 实时试听（{count} 项待验证）",
                            count=len(details),
                        )
                    )
                )
            status = self.realtime_audio.get_status()
        except AudioEngineError as exc:
            self._record_usage_issue("preview_failed")
            self.realtime_status_timer.stop()
            self.preview_transport_coordinator.clear_session()
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
            self.status_label.setText(tr("实时音频引擎已停止"))
            self.realtime_audio.last_error = str(exc)
            self._sync_preview_state()
            return
        loop_range = (
            self.timeline.time_range
            if self.timeline_loop_box.isChecked()
            else None
        )
        if (
            loop_range is not None
            and status.state != "paused"
            and not getattr(self.realtime_audio, "last_error", "")
            and status.position_ms >= loop_range[1]
        ):
            try:
                self.realtime_audio.seek(loop_range[0])
                self.realtime_audio.play()
                self._sync_reference_to_position(
                    loop_range[0],
                    play=True,
                    force=True,
                )
                self.timeline.set_playhead(loop_range[0], follow=True)
                return
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
                return
        self.timeline.set_playhead(status.position_ms, follow=True)
        self.timeline.set_track_levels(getattr(status, "track_levels", {}))
        if status.state == "playing":
            self._sync_reference_to_position(status.position_ms, play=True)
        if status.underruns > self.last_reported_underruns:
            self.last_reported_underruns = status.underruns
            self.status_label.setText(trf(
                "实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms",
                count=status.underruns, p95=status.render_p95_ms,
            ))
        if status.state == "stopped" or (status.position_ms >= status.duration_ms and status.duration_ms > 0):
            self.realtime_preview_active = False
            self.timeline.set_buffer_progress(0.0, False)
            self.timeline.set_track_levels({})
            self.realtime_status_timer.stop()
            if self.reference_audio.is_playing:
                self.reference_status_timer.start()
            if self.realtime_audio.last_error:
                self.status_label.setText(trf("音频输出停止：{error}", error=self.realtime_audio.last_error))
            self._sync_preview_state()

    def _seek_preview(self, ms: float) -> None:
        self.timeline.set_playhead(ms, follow=True)
        ms = self.timeline.playhead_ms
        play_reference = self.reference_audio.is_playing
        if self.realtime_preview_loading:
            self.realtime_preview_start_ms = ms
            play_reference = not self.preview_transport_coordinator.pause_requested
        elif self.realtime_preview_active:
            play_reference = self.realtime_audio.status.state == "playing"
            try:
                self.realtime_audio.seek(ms)
                if play_reference:
                    self.realtime_audio.play()
            except AudioEngineError as exc:
                self._on_preview_failed(str(exc))
        if play_reference:
            self._sync_reference_to_position(ms, play=True, force=True)
            if self.realtime_preview_loading and self.reference_audio.is_playing:
                self.reference_status_timer.start()
        else:
            self.reference_audio.set_position(ms)
            self.reference_last_resync_at = time.monotonic()
        self._sync_preview_state()

    def _prepare_sample_pack(self, pack_path: str) -> str | None:
        """Prepare a local sample pack while keeping the Qt event loop live."""

        if self.sample_pack_worker is not None:
            return None
        progress_dialog = QProgressDialog(
            tr("正在校验并准备本地音源包…"),
            tr("取消"),
            0,
            100,
            self,
        )
        progress_dialog.setWindowTitle(tr("准备本地音源包"))
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)

        worker = SamplePackPrepareWorker(
            pack_path,
            SAMPLE_PACK_CACHE_DIR,
            self,
        )
        self.sample_pack_worker = worker
        loop = QEventLoop(self)
        outcome: dict[str, str | bool] = {
            "audio_root": "",
            "error": "",
            "cancelled": False,
        }

        def mark_success(audio_root: str) -> None:
            outcome["audio_root"] = str(audio_root)

        def mark_failure(message: str) -> None:
            outcome["error"] = str(message)

        def mark_cancelled() -> None:
            outcome["cancelled"] = True

        def request_cancel() -> None:
            progress_dialog.setLabelText(tr("正在取消…"))
            worker.cancel()

        worker.progress_changed.connect(progress_dialog.setValue)
        worker.succeeded.connect(mark_success)
        worker.failed.connect(mark_failure)
        worker.cancelled.connect(mark_cancelled)
        worker.finished.connect(loop.quit)
        progress_dialog.canceled.connect(request_cancel)
        worker.start()
        progress_dialog.show()
        loop.exec()
        progress_dialog.close()
        self.sample_pack_worker = None
        worker.deleteLater()

        if self.workspace_close_pending:
            self.workspace_close_pending = False
            QTimer.singleShot(0, self.close)
            return None
        if outcome["cancelled"]:
            return None
        if outcome["error"]:
            QMessageBox.warning(
                self,
                tr("音源包不可用"),
                str(outcome["error"]),
            )
            return None
        audio_root = str(outcome["audio_root"])
        return audio_root or None

    def _reset_master_effects(self) -> None:
        self.reverb = 0
        self.delay = 0
        self.chorus = None

    def _current_master_effects(self) -> MasterEffects:
        try:
            return MasterEffects.from_legacy(
                self.reverb,
                self.delay,
                self.chorus,
            )
        except (TypeError, ValueError):
            return MasterEffects()

    def _open_master_effects(self) -> None:
        dialog = MasterEffectsDialog(self, self._current_master_effects())
        if exec_floating_panel(dialog) != QDialog.Accepted:
            return
        self._apply_master_effects(dialog.selected_master_effects())

    def _apply_master_effects(self, selected: MasterEffects) -> bool:
        """Commit only the score-wide layer as one undoable project action."""

        current = self._current_master_effects()
        if selected == current:
            return False
        self._push_project_snapshot()
        self.reverb, self.delay, self.chorus = selected.legacy_values()
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change()
        self._autosave_project("master effects")
        self.status_label.setText(tr("全局主效果已更新"))
        self.show_toast(tr("全局主效果已更新"), kind="success")
        return True

    def _materialize_game_velocity_settings(
        self,
        settings: ConversionSettings,
        *,
        record_undo: bool,
    ) -> tuple[ConversionSettings, int]:
        """Apply export-only velocity policies to the visible score model."""

        def has_non_neutral_legacy_scale(track: TrackState) -> bool:
            try:
                scale = float(getattr(track, "volume_scale", 1.0))
            except (TypeError, ValueError, OverflowError):
                return True
            return not math.isfinite(scale) or not math.isclose(
                scale,
                1.0,
                abs_tol=1e-12,
            )

        has_legacy_scale = any(
            has_non_neutral_legacy_scale(track) for track in self.tracks
        )
        needs_transform = (
            settings.velocity_mode not in MATERIALIZED_VELOCITY_MODES
        )
        if not has_legacy_scale and not needs_transform:
            return settings.with_updates(
                velocity_mode=VELOCITY_MODE_PRESERVE
            ), 0
        if record_undo:
            self._push_project_snapshot()
        note_count = 0
        for track in self.tracks:
            next_notes = tuple(bake_game_velocity_transform(
                track.notes,
                settings,
                legacy_scale=getattr(track, "volume_scale", 1.0),
            ))
            reconcile_track_game_velocity_records(track, next_notes)
            track.notes = list(next_notes)
            track.volume_scale = 1.0
            note_count += len(track.notes)
        return settings.with_updates(
            velocity_mode=VELOCITY_MODE_PRESERVE
        ), note_count

    def _open_settings(
        self,
        initial_page: int = 0,
        initial_preview_mode: str | None = None,
    ) -> None:
        old_effective_bpm = float(max(1, self.bpm_override or self.bpm))
        old_transpose = int(self.transpose)
        dialog = SettingsDialog(self)
        dialog.settings_nav.setCurrentRow(
            max(0, min(dialog.settings_nav.count() - 1, int(initial_page)))
        )
        if initial_preview_mode in PREVIEW_SOURCE_MODES:
            mode_index = dialog.preview_mode.findData(initial_preview_mode)
            dialog.preview_mode.setCurrentIndex(max(0, mode_index))
        while True:
            if exec_floating_panel(dialog) != QDialog.Accepted:
                dialog.deleteLater()
                return

            selected_output_dir = Path(
                dialog.output_dir.text().strip() or DEFAULT_OUTDIR
            ).expanduser()
            try:
                selected_output_dir = selected_output_dir.resolve()
            except OSError:
                pass
            selected_game_music_dir = Path(
                dialog.game_music_dir.text().strip()
                or default_game_music_dir()
            ).expanduser()
            try:
                selected_game_music_dir = selected_game_music_dir.resolve()
            except OSError:
                pass

            selected_instrument_art_dir = dialog.instrument_art_dir.text().strip()
            if selected_instrument_art_dir:
                selected_instrument_art_dir = str(
                    Path(selected_instrument_art_dir).resolve()
                )

            selected_preview_mode = str(dialog.preview_mode.currentData() or "generic")
            selected_source_values = dialog.audio_source_values()
            selected_source_value = selected_source_values.get(
                selected_preview_mode,
                "",
            )
            sample_pack, audio_root = classify_audio_source(
                selected_source_value
            )
            if sample_pack:
                prepared_root = self._prepare_sample_pack(sample_pack)
                if prepared_root is None:
                    if self.workspace_close_pending:
                        dialog.deleteLater()
                        return
                    # Re-open the same dialog instance so every edit survives
                    # a cancelled or failed package preparation.
                    continue
                audio_root = prepared_root
            break

        self.char_name = dialog.char_name.text().strip() or "MIDI"
        self.language = str(dialog.language.currentData() or "auto")
        self.owner_id = dialog.owner_id
        if dialog.owner_identity_changed:
            set_owner_identity(self.config, self.owner_id, self.char_name)
        selected_velocity_mode = dialog.selected_velocity_mode()
        selected_vel_range = None
        if selected_velocity_mode == "rescale":
            selected_vel_range = (
                min(dialog.vel_min.value(), dialog.vel_max.value()),
                max(dialog.vel_min.value(), dialog.vel_max.value()),
            )
        selected_vel_floor = (
            dialog.vel_floor.value()
            if selected_velocity_mode == "floor"
            else None
        )
        selected_vel_step = None
        if selected_velocity_mode == "stepped":
            selected_vel_floor = dialog.vel_step_base.value()
            selected_vel_step = (
                dialog.vel_step_base.value(),
                dialog.vel_step.value(),
            )
        selected_conversion = ConversionSettings(
            bpm_override=dialog.bpm_override.value() or None,
            transpose=dialog.transpose.value(),
            apply_sustain=dialog.apply_sustain.isChecked(),
            flatten_tempo=dialog.flatten_tempo.isChecked(),
            velocity_mode=selected_velocity_mode,
            vel_range=selected_vel_range,
            vel_floor=selected_vel_floor,
            vel_step=selected_vel_step,
        )
        selected_conversion, materialized_velocity_count = (
            self._materialize_game_velocity_settings(
                selected_conversion,
                record_undo=True,
            )
        )
        self._set_conversion_settings(selected_conversion)
        effective_bpm_changed = not math.isclose(
            old_effective_bpm,
            float(max(1, self.bpm_override or self.bpm)),
            abs_tol=1e-9,
        )
        transpose_changed = old_transpose != int(self.transpose)

        old_preview_mode = preview_source_mode(self.audio_sources)
        old_sample_pack = str(self.audio_sources.get("sample_pack", "") or "")
        old_audio_root = str(self.audio_sources.get("audio_root", "") or "")
        sample_source_changed = (
            old_sample_pack != sample_pack or old_audio_root != audio_root
        )
        for source_mode in ("pack",):
            remembered_pack, remembered_root = source_paths_for_mode(
                self.audio_sources,
                source_mode,
            )
            next_pack, next_root = classify_audio_source(
                selected_source_values.get(source_mode, "")
            )
            if next_pack == remembered_pack and Path(remembered_root).is_dir():
                next_root = remembered_root
            if source_mode == selected_preview_mode:
                next_pack, next_root = sample_pack, audio_root
            remember_source_paths(
                self.audio_sources,
                source_mode,
                next_pack,
                next_root,
            )
        self.audio_sources["paz_root"] = dialog.selected_paz_root.strip()
        activate_audio_source(self.audio_sources, selected_preview_mode)
        preview_mode_changed = (
            old_preview_mode != preview_source_mode(self.audio_sources)
        )
        if sample_source_changed:
            # Sample timbre descriptors are scoped to one local pack.  Never
            # reuse them after a hot source change, otherwise Top-3 results
            # would silently describe the previous pack until restart.
            self.transcription_timbre_profile_index = None
            self.transcription_group_timbre_profiles = None
            self.transcription_group_timbre_revision = ""
            self.automatic_instrument_match_analysis = None
            self.instrument_match_analysis = None
        if effective_bpm_changed:
            self._invalidate_transcription_rhythm_diagnostic()
            self.automatic_harmony_analysis = None
            self.harmony_analysis = None
        if effective_bpm_changed or transpose_changed:
            # BPM changes the beat-sized phrase gap and articulation scores;
            # transpose changes BDO range/sample-pitch matching.  Neither may
            # reuse a stale Top-3 result while the replacement worker runs.
            self.automatic_instrument_match_analysis = None
            self.instrument_match_analysis = None
        self.realtime_audio.set_source_config(self.audio_sources)
        self.config["audio_sources"] = dict(self.audio_sources)
        if sample_source_changed or preview_mode_changed:
            self._stop_preview(reset_playhead=False)
        self._sync_preview_source_menu()
        self.output_dir_path = str(selected_output_dir)
        self.last_output_dir = selected_output_dir
        self.config["output_dir"] = self.output_dir_path
        self.game_music_dir_path = str(selected_game_music_dir)
        self.config["game_music_dir"] = self.game_music_dir_path
        self.instrument_art_dir = selected_instrument_art_dir
        self.config["instrument_art_dir"] = self.instrument_art_dir
        motion_enabled = dialog.interface_motion.isChecked()
        self.config[MOTION_CONFIG_KEY] = motion_enabled
        self.setProperty(MOTION_PROPERTY, motion_enabled)
        if not motion_enabled:
            self.main_page_transition.finish()
            self.home_library_motion.finish()
        self.update_settings = {
            **update_preferences(self.config),
            "enabled": dialog.update_enabled.isChecked(),
            "auto_download": dialog.update_auto_download.isChecked(),
            "source": str(dialog.update_source.currentData() or "auto"),
        }
        usage_preferences = dialog.telemetry_values()
        usage_rating = dialog.telemetry_usefulness()
        dialog.deleteLater()
        self.config["updates"] = dict(self.update_settings)
        loaded_art_count = self.timeline.set_instrument_art_dir(
            self.instrument_art_dir
        )
        if hasattr(self, "home_instrument_art"):
            self.home_instrument_art.reload(
                self.instrument_art_dir,
                self._home_instrument_visual_keys,
            )
            self.project_list.viewport().update()
            self.game_score_list.viewport().update()

        self.config["language"] = self.language
        self.config["conversion_settings"] = {
            **self._conversion_settings.to_payload(),
            "char_name": self.char_name,
        }
        if usage_preferences is not None:
            self.config["usage_telemetry"] = usage_preferences
            if not usage_preferences["enabled"]:
                self._configure_usage_reporting(usage_preferences)
        save_config(self.config)
        if usage_preferences is not None and usage_preferences["enabled"]:
            self._configure_usage_reporting(usage_preferences)
        self._record_usage_helpfulness(usage_rating)
        active_localizer = localizer()
        if active_localizer is not None:
            active_localizer.set_language(self.language)
        self._apply_responsive_density()
        self._refresh_home()
        self._sync_preview_state()
        if (
            effective_bpm_changed
            or transpose_changed
            or materialized_velocity_count
        ):
            self._apply_workspace_change(
                ModelChange.structure()
                if materialized_velocity_count
                else ModelChange.grid(advance_revision=True)
            )
        if (
            self.transcription_result is not None
            and (
                sample_source_changed
                or effective_bpm_changed
                or transpose_changed
            )
        ):
            self._start_transcription_assist_analysis()
            if effective_bpm_changed:
                self._start_reference_timbre_analysis(force_restart=True)
        velocity_source = {
            "layered": "分层",
            "stepped": "阶梯",
            "rescale": "重映射",
            "floor": "抬底",
            "off": "保持原力度",
            "preserve": "保持原力度",
        }.get(self.velocity_mode)
        velocity_label = (
            trv(velocity_source)
            if velocity_source is not None
            else str(self.velocity_mode)
        )
        self.inspector_text.setText(
            trf(
                "转换设置：力度 {velocity} · 移调 {transpose:+d} · BPM {bpm} · 踏板 {sustain}",
                velocity=velocity_label,
                transpose=self.transpose,
                bpm=self.bpm_override or "MIDI",
                sustain=trv("开" if self.apply_sustain else "关"),
            )
        )
        if self.instrument_art_dir:
            self.show_toast(
                trf("已载入 {count} 张轨道背景", count=loaded_art_count),
                kind="success" if loaded_art_count else "warning",
            )
        self._autosave_project("settings")

    def _build_params(self) -> ExportRequest:
        midi_path = getattr(self, "midi_path", "")
        formal_tracks = formal_score_tracks(self.tracks)
        if not formal_tracks:
            raise ValueError(tr("当前工程没有可导出的轨道"))
        if not self.owner_id:
            raise ValueError(
                tr("尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。")
            )
        denominator = self.time_sig_denominator
        if denominator is None and midi_path and Path(midi_path).is_file():
            denominator = source_time_signature_denominator(midi_path)
        if denominator is None:
            raise ValueError(
                tr(
                    "工程未保存原 MIDI 的拍号分母，且源文件已不可用；已阻止导出以避免静默写入错误拍号。"
                )
            )
        if denominator != 4:
            raise ValueError(
                trf(
                    "当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。",
                    denominator=denominator,
                )
            )

        out_dir = Path(self.output_dir_path or DEFAULT_OUTDIR)
        out_name = self.output_name.text().strip() or (Path(midi_path).stem if midi_path else tr("未命名项目"))
        if any(ch in out_name for ch in '<>:"/\\|?*'):
            raise ValueError(tr("曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*"))
        out_path = out_dir / out_name

        # Re-reading the MIDI here would discard editor changes. The Qt-free
        # factory freezes every formal track and derives all game projections.
        return build_export_request(
            self.tracks,
            ExportRequestSpec(
                bpm=int(self.bpm),
                time_signature=int(self.time_sig),
                out_path=out_path,
                character_name=str(self.char_name),
                owner_id=int(self.owner_id),
                conversion=self._conversion_settings,
                pitch_plan=self._pitch_transform_plan.with_global(
                    self.transpose
                ),
                master_effects=MasterEffects.from_legacy(
                    self.reverb,
                    self.delay,
                    self.chorus,
                ),
                game_dir=Path(self.game_music_dir_path),
                source_path=str(midi_path),
                source_document=(
                    self.bdo_source_document
                    if self.source_format == "bdo"
                    else None
                ),
            ),
        )

    def _convert(self) -> None:
        analysis = self._analyze_conversion()
        blockers = [
            item for item in analysis["issues"]
            if validation_issue_disposition(item) == "block"
        ]
        if blockers:
            answer = QMessageBox.warning(
                self,
                tr("无法导出：存在阻断项"),
                trf(
                    "当前有 {count} 项必须先处理的问题。选择“打开”可定位到第一个相关轨道或音符。",
                    count=len(blockers),
                ),
                QMessageBox.Open | QMessageBox.Cancel,
                QMessageBox.Open,
            )
            if answer == QMessageBox.Open:
                self._focus_validation_issue(blockers[0])
            return
        confirmable = [
            item for item in analysis["issues"]
            if validation_issue_disposition(item) in {
                "approximate", "auto_fix", "user_choice", "quality_warning"
            }
        ]
        if confirmable:
            answer = QMessageBox.question(
                self,
                tr("确认导出变化"),
                trf(
                    "检查发现 {count} 项错误、近似结果或预期变化。\n仍可尝试导出，但可能出现丢音、音域或映射异常；Owner ID、非 /4 拍号等格式硬约束仍会阻止导出。确认继续吗？",
                    count=len(confirmable),
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        if not self.owner_id and not self._resolve_owner_id_for_export():
            return
        try:
            params = self._build_params()
        except Exception as exc:
            QMessageBox.warning(self, tr("参数错误"), str(exc))
            return
        self._stop_preview()
        self.convert_button.setEnabled(False)
        self.status_label.setText(tr("正在转换..."))
        self.worker = ConvertWorker(params)
        self.worker.conversion_finished.connect(self._on_convert_finished)
        self.worker.failed.connect(self._on_convert_failed)
        self.worker.finished.connect(
            lambda current=self.worker: self._convert_worker_finished(current)
        )
        self.worker.start()

    def _resolve_owner_id_for_export(self) -> bool:
        """Offer direct recovery for the most common export precondition."""

        choice = choose_prompt(
            self,
            tr("无法导出：缺少 Owner ID"),
            tr(
                "BDO 曲谱必须包含有效 Owner ID。可以立即从游戏曲谱读取，"
                "也可以打开设置手动处理。"
            ),
            (
                ("later", tr("稍后处理")),
                ("settings", tr("去设置")),
                ("load", tr("从游戏曲谱读取")),
            ),
            default="load", cancel="later",
        )
        if choice == "load":
            self._quick_load_owner_id()
        elif choice == "settings":
            self._open_settings(0)
        return bool(self.owner_id)

    def _on_convert_finished(
        self,
        out_path: str,
        byte_count: int,
        summary: object,
        installed: str,
        installation_error: str,
    ) -> None:
        self._sync_convert_button_enabled()
        self.last_output_dir = Path(out_path).parent
        self.last_export_path = Path(out_path)
        self.status_label.setText(tr("转换完成"))
        summary = dict(summary)
        extra_parts: list[object] = []
        verification = summary.get("verification_report")
        verification_failed = not (
            isinstance(verification, ExportVerificationReport)
            and verification.matches
            and verification.stage_matches("primary")
        )
        if verification_failed:
            self._record_usage_issue("export_failed")
            issue_count = (
                verification.issue_count
                if isinstance(verification, ExportVerificationReport)
                else 1
            )
            extra_parts.append(trfv(
                " · 一致性检查发现 {count} 项差异",
                count=issue_count,
            ))
            diagnostic = (
                format_export_verification_report(verification)
                if isinstance(verification, ExportVerificationReport)
                else "export verification report missing from worker result"
            )
            append_crash_log("Export consistency verification failed", diagnostic)
            self.status_label.setText(tr("转换完成（数据一致性检查失败）"))
        else:
            self._record_usage_export()
            extra_parts.append(trv(" · 编辑器→BDO v9 数据一致"))

        if installed:
            game_copy_matches = (
                isinstance(verification, ExportVerificationReport)
                and verification.stage_matches("game_copy")
            )
            if game_copy_matches:
                extra_parts.append(trv(" · 游戏目录副本一致"))
            else:
                extra_parts.append(trv(
                    " · 主文件已保存，但游戏目录副本未通过一致性检查"
                ))
        elif installation_error:
            extra_parts.append(
                trfv(
                    " · 未复制到游戏目录：{error}",
                    error=installation_error,
                )
            )
        result_text = trf(
            "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}",
            file=Path(out_path).name, bytes=byte_count, instruments=summary["instruments"],
            tracks=summary["tracks"], notes=summary["total_notes"],
            extra=tr_joinv(extra_parts, separator=""),
        )
        self.inspector_text.setText(result_text)
        self.inspector_text.setToolTip(tr(
            "本次检查仅验证编辑器中的可导出字段、BDO v9 文件写入和已安装副本；不代表程序绝对无 Bug，也不证明游戏内音色、效果或响度已验证。"
        ))
        if installation_error and not verification_failed:
            self.status_label.setText(tr("转换完成（未复制到游戏目录）"))
        self.show_toast(
            result_text,
            kind=(
                "warning"
                if verification_failed or installation_error
                else "success"
            ),
            duration_ms=5200,
        )
        self._autosave_project("convert finished", immediate=True)

    def _on_convert_failed(self, message: str) -> None:
        self._record_usage_issue("export_failed")
        self._sync_convert_button_enabled()
        self.status_label.setText(tr("转换失败"))
        safe_message = _redact_log_paths(message)
        append_crash_log("Convert failed", safe_message)
        log_path = DEFAULT_OUTDIR / "last_convert_error.log"
        try:
            atomic_write_bytes(log_path, safe_message.encode("utf-8"))
        except Exception:
            log_path = None
        brief = (
            safe_message.splitlines()[0]
            if safe_message
            else tr("未知错误")
        )
        detail = (
            trf("\n\n详细错误已写入：{path}", path=log_path)
            if log_path
            else ""
        )
        if not self.workspace_close_pending:
            QMessageBox.critical(self, tr("转换失败"), f"{brief}{detail}")

    def _convert_worker_finished(self, worker: ConvertWorker) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        self._sync_convert_button_enabled()
        worker.deleteLater()
        if self.workspace_close_pending:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event) -> None:
        self.main_page_transition.finish()
        self.autosave_timer.stop()
        self.transcription_assist_refresh_timer.stop()
        if not self._final_autosave_queued:
            # Queue exactly one final immutable snapshot.  Waiting happens via
            # the worker's finished signal, keeping the GUI responsive and
            # preventing each close retry from starting another autosave.
            self._final_autosave_queued = True
            if self._flush_autosave() is False and self._autosave_error:
                self._keep_open_after_autosave_failure()
                event.ignore()
                return
        if (
            self.autosave_worker is not None
            or self.pending_autosave_request is not None
        ):
            # Ordinary snapshots finish in milliseconds.  Drain a short,
            # bounded window so embedding tests and temporary workspaces do not
            # tear down beneath a live writer; genuinely slow disks remain
            # asynchronous and trigger close again from ``finished``.
            if self._wait_for_autosave_idle(timeout_ms=3_000):
                return self.closeEvent(event)
            self.workspace_close_pending = True
            self.status_label.setText(tr("正在完成最终自动保存…"))
            event.ignore()
            return
        if self._autosave_error:
            self._keep_open_after_autosave_failure()
            event.ignore()
            return
        self._pending_reference_tempo_path = ""
        self._cancel_reference_tempo_worker()
        running_workers = [
            worker
            for worker in (
                self.workspace_transcription_worker,
                self.transcription_assist_worker,
                self.reference_timbre_worker,
                self.sample_pack_worker,
                self.worker,
            )
            if worker is not None and worker.isRunning()
        ]
        if running_workers:
            self.transcription_analysis_coordinator.clear_assist_restart()
            for worker in running_workers:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
            self.workspace_close_pending = True
            event.ignore()
            return
        self._close_all_note_editors()
        # Rejecting an ordinary editor may replace its recovery draft with a
        # formal-track snapshot. That last write must pass the same close gate.
        if (
            self.autosave_worker is not None
            or self.pending_autosave_request is not None
            or self._autosave_error
        ):
            return self.closeEvent(event)
        self._stop_preview()
        self.reference_audio.shutdown()
        self.realtime_audio.stop()
        self.self_update_controller.shutdown()
        self._shutdown_usage_reporting()
        self.workspace_close_pending = False
        super().closeEvent(event)


def _report_fatal_error(
    parent: QWidget | None,
    context: str,
    exc: BaseException,
) -> None:
    append_crash_log(context, f"{exc}\n\n{traceback.format_exc()}")
    QMessageBox.critical(
        parent,
        tr("程序错误"),
        trf(
            "程序发生错误，日志已写入：\n{path}\n\n{error}",
            path=CRASH_LOG_PATH,
            error=exc,
        ),
    )


def main() -> int:
    install_crash_logging()
    from PySide6.QtCore import QThreadPool
    from bdo_music_composer.app.windows_recovery import (
        register_frozen_application_restart,
    )
    from bdo_music_composer.ui.online_score_library_qt import initialize_online_score_library

    register_frozen_application_restart()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                WINDOWS_APP_USER_MODEL_ID
            )
        except (AttributeError, OSError):
            pass
    initialize_online_score_library()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_DISPLAY_VERSION)
    install_localizer(app, str(load_config().get("language", "auto")))
    icon_path = APP_ICON_IMAGE
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    ready = False
    try:
        window = MidiToBdoWindow()
        place_startup_window(window)

        def maintain_local_files() -> None:
            try:
                prune_transcription_workspaces()
                plugin_discovery = discover_host_algorithms()
                if plugin_discovery.diagnostics:
                    append_crash_log(
                        "Optimizer bundle discovery",
                        "\n".join(plugin_discovery.diagnostics),
                    )
            except Exception:
                append_crash_log("Startup maintenance", traceback.format_exc())

        def report_ready() -> None:
            nonlocal ready
            try:
                window.toolbar_home_btn.setFocus()
                window._show_startup_notice()
                window._schedule_usage_reporting()
                QThreadPool.globalInstance().start(maintain_local_files)
                ready = True
            except BaseException as exc:
                mark_startup_usage_failure(CONFIG_PATH)
                _report_fatal_error(window, "Fatal error during startup", exc)
                app.exit(1)

        FirstVisiblePaint(window, report_ready)
        window.show()
        result = app.exec()
        append_crash_log("Application exited", f"exit_code={result}")
        return result
    except BaseException as exc:
        if not ready:
            mark_startup_usage_failure(CONFIG_PATH)
        _report_fatal_error(None, "Fatal error in main()", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
