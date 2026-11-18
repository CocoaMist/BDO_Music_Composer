"""Capture the workbench's live track, Clip, and time selection for the Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from bdo_midi import Note
from bdo_music_composer.creation.score_agent_tools import ScoreAgentTools, reference_audio_status
from bdo_music_composer.creation.score_audio_evidence import ReferenceAudioEvidenceSource
from bdo_music_composer.creation.workspace import CreationContext
from bdo_music_composer.editor.arrangement_clip import track_clips
from bdo_music_composer.ui.i18n import tr, trf


_MAX_AGENT_BARS = 16
_MAX_START_BAR = 4096


class ScoreAgentScopeError(ValueError):
    """A user-actionable, source-language selection error."""


@dataclass(frozen=True, slots=True)
class ScoreAgentScope:
    track_id: int | None = None
    clip_id: str = ""
    source_clip_id: str = ""
    track_name: str = ""
    clip_number: int = 0
    from_notes: bool = False
    first_bar: int = 1
    bars: int = 8
    time_range_ms: tuple[float, float] | None = None
    error: str = ""
    draft: bool = False
    explicit_range: bool = False
    editor_notes: tuple[Note, ...] | None = field(default=None, compare=False, repr=False)
    reference_audio: str = "missing"

    def label(self) -> str:
        if self.error:
            return tr(self.error)
        if self.from_notes:
            name = trf("{track} · 选中的音符", track=self.track_name)
        elif self.clip_number:
            name = trf("{track} · 片段 {number}", track=self.track_name, number=self.clip_number)
        elif self.track_id is not None:
            name = self.track_name
        else:
            name = tr("工程概览")
        if self.draft:
            name = trf("{scope} · 钢琴卷帘草稿 · 只读", scope=name)
        if self.time_range_ms is None:
            return name
        start, end = self.time_range_ms
        return trf("{scope} · {start:.2f}–{end:.2f} 秒", scope=name, start=start / 1000.0, end=end / 1000.0)

    def same_target(self, other: ScoreAgentScope) -> bool:
        return (
            self.track_id, self.source_clip_id, self.from_notes, self.draft, self.error,
            self.time_range_ms if self.explicit_range else None,
        ) == (
            other.track_id, other.source_clip_id, other.from_notes, other.draft, other.error,
            other.time_range_ms if other.explicit_range else None,
        )


@dataclass(frozen=True, slots=True)
class ScoreAgentCapture:
    scope: ScoreAgentScope
    stamp: tuple[str, int]
    context: CreationContext
    tools: ScoreAgentTools
    grid_origin_ms: float
    reference_audio_source: ReferenceAudioEvidenceSource | None = field(default=None, repr=False)

    @property
    def history_key(self) -> tuple:
        """Use the actual read scope, including private editor state, within this process."""
        return self.stamp, self.history_target

    @property
    def history_target(self) -> tuple:
        return (
            self.scope.track_id, self.scope.clip_id, self.scope.source_clip_id, self.scope.first_bar,
            self.scope.bars, self.scope.time_range_ms, self.scope.editor_notes, self.scope.from_notes, self.scope.draft,
            self.context.bpm, self.context.meter, self.context.denominator, self.grid_origin_ms,
            self.reference_audio_source,
        )


def workspace_reference_audio_source(
    host, *, grid_origin_ms: float,
) -> ReferenceAudioEvidenceSource | None:
    """Capture only the already-linked source and its project-time conversion."""
    relink_required = bool(getattr(host, "reference_audio_relink_required", False))
    controller = getattr(host, "reference_audio", None)
    path = getattr(host, "reference_audio_path", getattr(controller, "audio_path", None))
    if not path and not relink_required:
        return None
    return ReferenceAudioEvidenceSource(
        path=path if not relink_required else None,
        offset_ms=float(host.reference_audio_offset_ms),
        beat_origin_ms=grid_origin_ms,
        bpm=float(host.bpm_override or host.bpm),
        time_signature_numerator=int(host.time_sig),
        relink_required=relink_required,
    )


def workspace_agent_scope(host, editor=None, *, editor_dirty: bool = False) -> ScoreAgentScope:
    if host.loading_project:
        return ScoreAgentScope(error="请先打开或新建曲谱。")
    timeline = host.timeline
    selection = timeline.selection_descriptor()
    clips, tracks = selection["clips"], selection["tracks"]
    if len(clips) > 1 or (not clips and len(tracks) > 1):
        return ScoreAgentScope(error="请选择一个轨道或片段。")
    track = selection["active_track"]
    clip_id = ""
    clip_number = 0
    intervals = []
    if clips:
        track, clip_id = clips[0]
    if track is not None and not any(track is current for current in host.tracks):
        return ScoreAgentScope(error="工程或选区已变化，请重新选择。")
    track_id = int(track.track_id) if track is not None else None
    from_notes = False
    draft = False
    editor_notes = None
    if editor is not None and int(editor.track.track_id) == track_id:
        editor_clip = str(editor.arrangement_clip_id or "")
        if not clip_id or editor_clip == clip_id:
            canvas = editor.canvas
            selected = tuple(canvas.notes[i] for i in sorted(canvas.selected) if 0 <= i < len(canvas.notes))
            if selected or editor_dirty:
                clip_id = editor_clip
                from_notes = bool(selected)
                draft = editor_dirty and canvas.notes != editor.last_applied
                editor_notes = selected if from_notes else tuple(canvas.notes)
                if from_notes:
                    intervals.append((
                        min(float(note.start) for note in selected),
                        max(float(note.start + note.dur) for note in selected),
                    ))
    if clip_id:
        clip_number, clip = next(
            ((i, clip) for i, clip in enumerate(track_clips(track), 1) if clip.clip_id == clip_id),
            (0, None),
        )
        if clip is None:
            return ScoreAgentScope(error="工程或选区已变化，请重新选择。")
        intervals.append((clip.start_ms, clip.end_ms))
    if timeline.time_range is not None and timeline.time_range[0] < timeline.time_range[1]:
        intervals.append(timeline.time_range)

    # The creation engine's bar coverage is zero-origin. Exact selected times
    # are preserved separately from the aligned window the local editor edits.
    bpm = float(host.bpm_override or host.bpm)
    bar_ms = 60_000.0 * host.time_sig / bpm if bpm > 0 else 0.0
    if not math.isfinite(bar_ms) or bar_ms <= 0:
        return ScoreAgentScope(error="创作助手目前支持 2/4 到 6/4 拍。")
    if intervals:
        start = max(0.0, max(interval[0] for interval in intervals))
        end = min(interval[1] for interval in intervals)
        if not (math.isfinite(start) and math.isfinite(end) and end > start):
            return ScoreAgentScope(error="时间范围和选区没有交集。")
        bar_index = int(start // bar_ms)
        end = min(end, (bar_index + _MAX_AGENT_BARS) * bar_ms)
        bars = min(_MAX_AGENT_BARS, max(1, math.ceil(end / bar_ms) - bar_index))
        captured_range = (start, end)
    elif track_id is not None:
        bar_index = int(max(0.0, float(timeline.playhead_ms)) // bar_ms)
        bars = 8
        captured_range = (bar_index * bar_ms, (bar_index + bars) * bar_ms)
    else:
        bar_index, bars, captured_range = 0, _MAX_AGENT_BARS, None
    if bar_index + 1 > _MAX_START_BAR:
        return ScoreAgentScope(error="这次请求超出了模型支持的范围。")
    # Implicit Clips supply a time span only. The creation workflow edits
    # these via their owner track until the project creates explicit Clips.
    native_clip_id = clip_id if track is not None and track.arrangement_clips else ""
    reference_audio = workspace_reference_audio_source(
        host, grid_origin_ms=float(timeline.beat_origin_ms),
    )
    return ScoreAgentScope(
        track_id=track_id, clip_id=native_clip_id, source_clip_id=clip_id,
        track_name=track.display_name if track is not None else "", clip_number=clip_number,
        from_notes=from_notes, first_bar=bar_index + 1, bars=bars, time_range_ms=captured_range,
        draft=draft, explicit_range=bool(intervals), editor_notes=editor_notes,
        reference_audio=reference_audio_status(reference_audio),
    )


def capture_workspace_score(host, scope: ScoreAgentScope) -> ScoreAgentCapture:
    if scope.error:
        raise ScoreAgentScopeError(scope.error)
    context = CreationContext.capture(host.tracks, host.bpm_override or host.bpm, host.time_sig, host.time_sig_denominator)
    grid_origin_ms = float(host.timeline.beat_origin_ms)
    reference_audio = workspace_reference_audio_source(host, grid_origin_ms=grid_origin_ms)
    tools = ScoreAgentTools(
        context, track_id=scope.track_id, clip_id=scope.clip_id, first_bar=scope.first_bar,
        bars=scope.bars, time_range_ms=scope.time_range_ms if scope.explicit_range else None,
        grid_origin_ms=grid_origin_ms, editor_notes=scope.editor_notes,
        editor_notes_are_selection=scope.from_notes,
        reference_audio=reference_audio,
    )
    return ScoreAgentCapture(
        scope, (host.project_id, host.model_revision.value), context, tools, grid_origin_ms, reference_audio,
    )
