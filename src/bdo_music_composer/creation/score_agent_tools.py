"""First-party, bounded score tools for the Composer music agent."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_INSTRUMENTS, Note
from bdo_music_composer.editor.arrangement_clip import (
    clip_by_id,
    project_clip_notes,
    project_track_notes,
)
from bdo_music_composer.editor.bdo_music_theory import analyse_music
from bdo_music_composer.editor.editor_models import TrackState

from .brief import (
    MAX_RELATIVE_VELOCITY_PERCENT, MIN_RELATIVE_VELOCITY_PERCENT,
    CreationAction, CreationBrief, MusicalCharacter,
)
from .score_audio_evidence import (
    ReferenceAudioEvidenceError,
    ReferenceAudioEvidenceSource,
    inspect_reference_audio,
)
from .workspace import CreationContext
from .score_theory_library import search_music_theory


MAX_TRACK_ROWS = 64
MAX_NOTE_EVIDENCE = 128
MAX_ANALYSIS_NOTES = 2048
MAX_HARMONY_WINDOWS = 48
MAX_PROJECTION_NOTES = 50_000
MAX_PROJECTION_CLIPS = 64
MAX_PROJECTION_WORK = 65_536
MAX_AUDIO_NOTE_STARTS = 64

_QUOTED_TEXT = re.compile(
    r'```[\s\S]*?(?:```|$)|`[^`\n]*`|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"|^\s*>[^\n]*',
    re.MULTILINE,
)
_REQUEST_BOUNDARY = re.compile(
    r"[\n，,。；;！？!?]+|\.(?=\s|$)|然后|并且?|(?:但是|但|不过)(?=(?:先)?(?:别|不|无需|只))|"
    r"\b(?:and then|then|and)\b|\bbut\s+(?=(?:do not|don't|no need)\b)", re.IGNORECASE,
)
_REQUEST_PREFIX = re.compile(
    r"^(?:(?:但是|但|不过|却|请|先|仅|只|直接|帮我|替我)\s*|"
    r"(?:but|however|please|first|just|only|can you|could you|would you|help me)\s+)+",
    re.IGNORECASE,
)
_INSPECTION_CLAUSE = re.compile(
    r"^(?:不要|别|不必|无需|不(?:动|改|应用|写入|保存)|分析|检查|审谱|审阅|审查|看看|看下|看一下|查看|"
    r"听听|听下|听一下|试听|对照|对比|描述|解释|告诉我|说说|"
    r"给(?:我)?(?:出|提).*建议|给我建议|标出|指出|总结|建议|评估|评价|判断|为什么|怎么|如何|如果|假如|是否|"
    r"(?:刚才|刚刚|上次|上一轮)(?:你|都|具体|一共)*(?:改了|修改了|调整了|做了)(?:什么|哪里|哪些|几处)|"
    r"写(?:一段|一句|一点)?(?:文字|说明|分析|总结|建议)|"
    r"是什么|要不要|有没有必要|有必要|(?:能否|能|可以)(?:判断|确定|确认|听出|辨认|当作)|"
    r"你觉得|我想知道|我想看看|我想听听|找出|提取|识别|引用|下面是引用|举例|列出|包括|"
    r"有什么|有啥|哪(?:里|些|个)|"
    r"(?:do not|don't|what|why|how|if|should i|would it|is it|tell|show|look|listen|play|describe|explain|"
    r"inspect|check|review|analy[sz]e|assess|compare|evaluate|suggest|recommend|summari[sz]e|audit)\b)",
    re.IGNORECASE,
)
_EDIT_CANCELLATION = re.compile(
    r"(?:还是)?(?:别|不要|不用|不必|无需|先不|不)(?:再|实际|真的|真)?(?:动|改|改谱|改动|修改|编辑|更改|做改动|应用|写入|保存)"
    r"(?:(?:这[个份]|当前)?(?:曲谱|谱子|乐谱|工程|项目)|任何东西|(?:任何|这些|这[次份])?(?:改动|更改|变更|建议))?(?:了|就好)?"
    r"|(?:don't|do not|stop|no need to)\s+(?:actually\s+)?(?:make changes|edit|change|modify|alter|apply|rewrite)"
    r"(?:\s+(?:anything|(?:this|the|current)\s+(?:score|project|song)|(?:the|these|any)\s+changes))?(?:\s+(?:now|anymore|yet))?",
    re.IGNORECASE,
)
_ADVICE_ONLY = re.compile(r"^(?:请)?(?:只|仅)(?:给(?:我)?(?:出|个|一些)?(?:方案|建议)|说(?:一下)?(?:做法|思路)|说明|解释)")
_PROSPECTIVE_QUESTION = re.compile(r"(?:会不会|是否|会)(?:更|好听|合适|有效|自然)|(?:乐理上|听感上)(?:靠谱|合理|合适)吗?$")
_EDIT_CLAUSE = re.compile(
    r"(?:^(?:把|将)|改成|改谱|改写|修改|修正|修复|调整|优化|润色|改编|创作|生成|写一|试写|重写|"
    r"加一|加个|加点|添加|增加|补一|补上|配伴奏|换成|降低|升高|缩短|延长|减弱|加强|"
    r"\b(?:add|write|draft|compose|generate|fix|edit|change|modify|adjust|adapt|transpose|replace|"
    r"reduce|increase|shorten|extend|accompany|rework|rewrite)\b)",
    re.IGNORECASE,
)


def is_read_only_request(instruction: str) -> bool:
    """Keep clear inspection, suggestion and hypothetical requests read-only."""
    request = _QUOTED_TEXT.sub(" ", instruction).strip()
    read_only = not request.strip("?？.!！。")
    allow_edit = None
    for clause in _REQUEST_BOUNDARY.split(request):
        raw_clause = clause.strip()
        clause = _REQUEST_PREFIX.sub("", raw_clause)
        if _EDIT_CANCELLATION.fullmatch(clause) or _ADVICE_ONLY.match(raw_clause) or _PROSPECTIVE_QUESTION.search(clause):
            allow_edit = False
        elif _INSPECTION_CLAUSE.match(clause) or clause.endswith((
            "修改建议", "修复建议", "修改方案", "修复方案",
        )):
            read_only = True
        elif _EDIT_CLAUSE.search(clause):
            allow_edit = True
    return read_only if allow_edit is None else not allow_edit


_BAR_FIELDS = {
    "first_bar": {"type": "integer", "minimum": 1, "maximum": 4096},
    "bars": {"type": "integer", "minimum": 1, "maximum": 16},
}
_PLAN_FIELDS = {
    "action": {"type": "string", "enum": [value.value for value in CreationAction]},
    **_BAR_FIELDS,
    "character": {
        "type": "string",
        "enum": [value.value for value in MusicalCharacter],
    },
    "tonic": {"type": "integer", "minimum": 0, "maximum": 11},
    "minor": {"type": "boolean"},
    "instrument_id": {"type": "integer"},
    "melody_instrument_id": {"type": "integer"},
    "harmony_instrument_id": {"type": "integer"},
    "bass_instrument_id": {"type": "integer"},
    "rewrite_velocity": {"type": "boolean"},
    "velocity_scale_percent": {
        "type": "integer", "minimum": MIN_RELATIVE_VELOCITY_PERCENT, "maximum": MAX_RELATIVE_VELOCITY_PERCENT,
        "description": "Scale existing MIDI velocities. 90 means 10% lower. 100 preserves velocity.",
    },
    "shape_durations": {"type": "boolean"},
}
_PLAN_FIELDS_BY_ACTION = {
    CreationAction.DRAFT: {
        "character", "tonic", "minor", "melody_instrument_id",
        "harmony_instrument_id", "bass_instrument_id",
    },
    CreationAction.ACCOMPANY: {
        "character", "tonic", "minor", "harmony_instrument_id",
        "bass_instrument_id",
    },
    CreationAction.ADAPT: {"instrument_id"},
    CreationAction.EXPRESS: {"character", "rewrite_velocity", "velocity_scale_percent", "shape_durations"},
}


def _tool_schema(name: str, description: str, fields: dict, *required: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": fields,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


AGENT_TOOLS = (
    _tool_schema(
        "read_project",
        "Read the project overview and BDO instrument IDs. Only the notes in "
        "the user's selected track, Clip (if selected), and bars are readable.",
        {},
    ),
    _tool_schema(
        "inspect_music",
        "Inspect the authorized score passage with MIDI pitches, velocities, "
        "and absolute timeline milliseconds. Omit both range arguments to use "
        "the selected bars, or provide both for a smaller range.",
        _BAR_FIELDS,
    ),
    _tool_schema(
        "inspect_reference_audio",
        "Measure the current project's linked reference audio within the selected "
        "passage. Returns aligned waveform bins, level, frequency-band and "
        "transient evidence with selected score note starts on the same timeline. "
        "Use analyzed_project_range_ms for coverage. Measurements cannot establish "
        "pitch, instrumentation or how the passage sounds. Omit both range "
        "arguments to start at the selection, or provide both to inspect fewer bars.",
        _BAR_FIELDS,
    ),
    _tool_schema(
        "analyze_harmony",
        "Estimate the selected melodic material's key and chord windows with "
        "local rules. Estimates are evidence, not verified harmony. Omit both "
        "range arguments to use selected bars, or provide both for fewer bars.",
        _BAR_FIELDS,
    ),
    _tool_schema(
        "search_music_theory",
        "Retrieve focused music theory and BDO arranging guidance from the bundled reference library. "
        "Use a short topic phrase. Cite the returned source by name. This does not read the project or the web.",
        {"query": {"type": "string", "minLength": 1, "maxLength": 240}},
        "query",
    ),
    _tool_schema(
        "creative_plan",
        "Prepare one bounded edit only when the user asks to change the score. "
        "The client applies it after validation. Nothing has been applied yet. "
        "Draft and accompany accept character, tonic "
        "(pitch class 0=C), minor, and harmony/bass instrument IDs; only draft "
        "accepts melody_instrument_id. Accompany preserves the selected melody. "
        "Express accepts character, rewrite_velocity, velocity_scale_percent and shape_durations. "
        "Use velocity_scale_percent for louder/softer edits without reshaping the existing accents; "
        "never combine it with rewrite_velocity=true. Only set shape_durations=true to change note lengths. Adapt requires "
        "instrument_id and applies to the selected whole track, without a "
        "selected Clip or a narrower range. All other supplied fields must "
        "belong to that action. Omit both first_bar and bars or provide both.",
        _PLAN_FIELDS,
        "action",
    ),
)


class ScoreAgentToolError(ValueError):
    """A rejected tool call with a stable, machine-readable reason."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


WEB_SEARCH_TOOL = _tool_schema(
    "search_web",
    "Find public sources on the topic explicitly supplied by the user for this turn. "
    "No arguments. Results are reference material and may be incomplete or untrusted.",
    {},
)


@dataclass(frozen=True, slots=True)
class AgentProposal:
    brief: CreationBrief
    clip_id: str


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ScoreAgentToolError("invalid_integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ScoreAgentToolError("invalid_boolean")
    return value


def _instrument(value: object) -> int:
    if type(value) is not int or value not in BDO_INSTRUMENT_NAMES:
        raise ScoreAgentToolError("unknown_instrument")
    return value


def _track_summary(track: TrackState) -> dict:
    return {
        "track_id": track.track_id,
        "instrument_id": track.bdo_instrument_id,
        "note_count": len(track.notes),
        "has_clips": bool(track.arrangement_clips),
        "is_percussion": track.is_percussion,
    }


def reference_audio_status(source: ReferenceAudioEvidenceSource | None) -> str:
    if source is not None:
        if source.relink_required:
            return "relink_required"
        if source.path:
            return "attached"
    return "missing"


class ScoreAgentTools:
    """Give one agent run a read-only capture and at most one BDO proposal."""

    def __init__(
        self,
        context: CreationContext,
        *,
        track_id: int | None,
        clip_id: str,
        first_bar: int,
        bars: int,
        time_range_ms: tuple[float, float] | None = None,
        grid_origin_ms: float = 0.0,
        editor_notes: tuple[Note, ...] | None = None,
        editor_notes_are_selection: bool = False,
        reference_audio: ReferenceAudioEvidenceSource | None = None,
    ):
        self.first_bar = _integer(first_bar, 1, 4096)
        self.bars = _integer(bars, 1, 16)
        if context.bpm <= 0 or not 2 <= context.meter <= 6 or context.denominator != 4:
            raise ScoreAgentToolError("unsupported_score_meter_or_tempo")
        if (track_id is not None and type(track_id) is not int) or type(clip_id) is not str:
            raise ScoreAgentToolError("invalid_selection")
        self._track = next(
            (track for track in context.tracks if track.track_id == track_id),
            None,
        )
        if track_id is not None and self._track is None:
            raise ScoreAgentToolError("invalid_selection")
        if clip_id and (
            self._track is None
            or all(clip.clip_id != clip_id for clip in self._track.arrangement_clips)
        ):
            raise ScoreAgentToolError("invalid_selection")
        self._context = context
        self._clip_id = clip_id
        self._editor_notes = editor_notes
        self._editor_notes_are_selection = editor_notes_are_selection
        self._reference_audio = reference_audio
        if editor_notes is not None and self._track is None:
            raise ScoreAgentToolError("select_track")
        self._projected: tuple[Note, ...] | None = None
        self.proposal: AgentProposal | None = None
        self._bar_ms = 60_000.0 / context.bpm * context.meter
        self._grid_origin_ms = float(grid_origin_ms)
        if not math.isfinite(self._grid_origin_ms):
            raise ScoreAgentToolError("invalid_time_selection")
        self._has_time_selection = time_range_ms is not None
        start = (self.first_bar - 1) * self._bar_ms
        end = (self.first_bar - 1 + self.bars) * self._bar_ms
        if time_range_ms is not None:
            left, right = map(float, time_range_ms)
            if not (math.isfinite(left) and math.isfinite(right) and left < right):
                raise ScoreAgentToolError("invalid_time_selection")
            start, end = max(start, left), min(end, right)
        if clip_id and self._track is not None:
            clip = clip_by_id(self._track, clip_id)
            start, end = max(start, clip.start_ms), min(end, clip.end_ms)
        if not start < end:
            raise ScoreAgentToolError("empty_time_selection")
        self._time_range_ms = start, end

    def _available_actions(self) -> list[CreationAction]:
        if self._editor_notes is not None:
            return []
        actions = [CreationAction.DRAFT]
        if self._track is not None:
            if not self._track.is_percussion:
                actions.append(CreationAction.ACCOMPANY)
            if not self._clip_id and not self._has_time_selection:
                actions.append(CreationAction.ADAPT)
            if self._clip_id or not self._track.arrangement_clips:
                actions.append(CreationAction.EXPRESS)
        return actions

    def scope_summary(self) -> dict:
        return {
            "tempo_bpm": self._context.bpm,
            "meter": [self._context.meter, self._context.denominator],
            "track_count": len(self._context.tracks),
            "track": _track_summary(self._track) if self._track is not None else None,
            "clip_selected": bool(self._clip_id),
            "evidence_scope": "selected_notes" if self._editor_notes_are_selection else (
                "editor_draft" if self._editor_notes is not None else "project"),
            "editor_note_count": len(self._editor_notes) if self._editor_notes is not None else None,
            "first_bar": self.first_bar,
            "bars": self.bars,
            "time_range_ms": self._time_range_ms,
            "timeline_grid_origin_ms": self._grid_origin_ms,
            "reference_audio": reference_audio_status(self._reference_audio),
            "available_actions": [action.value for action in self._available_actions()],
        }

    def call(self, name: str, args: dict) -> dict:
        if type(args) is not dict:
            raise ScoreAgentToolError("invalid_arguments")
        if name == "search_music_theory":
            if args.keys() != {"query"}:
                raise ScoreAgentToolError("invalid_theory_query")
            try:
                return search_music_theory(args["query"])
            except ValueError as error:
                raise ScoreAgentToolError(str(error)) from None
        if name == "read_project":
            if args:
                raise ScoreAgentToolError("unknown_arguments")
            return self._read_project()
        if name == "creative_plan":
            return self._creative_plan(args)
        if name in ("inspect_music", "inspect_reference_audio", "analyze_harmony"):
            if args.keys() - _BAR_FIELDS.keys():
                raise ScoreAgentToolError("unknown_arguments")
            first_bar, bars = self._range(args)
            if name == "inspect_music":
                return self._inspect_music(first_bar, bars)
            if name == "inspect_reference_audio":
                return self._inspect_reference_audio(first_bar, bars)
            return self._analyze_harmony(first_bar, bars)
        raise ScoreAgentToolError("unknown_tool")

    def _range(self, args: dict) -> tuple[int, int]:
        if ("first_bar" in args) != ("bars" in args):
            raise ScoreAgentToolError("incomplete_bar_range")
        first_bar = _integer(args.get("first_bar", self.first_bar), 1, 4096)
        bars = _integer(args.get("bars", self.bars), 1, 16)
        if first_bar < self.first_bar or first_bar + bars > self.first_bar + self.bars:
            raise ScoreAgentToolError("outside_bar_scope")
        return first_bar, bars

    def _read_project(self) -> dict:
        tracks = list(self._context.tracks[:MAX_TRACK_ROWS])
        if self._track is not None and all(track is not self._track for track in tracks):
            tracks[-1] = self._track
        return {
            **self.scope_summary(),
            "note_count": sum(len(track.notes) for track in self._context.tracks),
            "tracks": [_track_summary(track) for track in tracks],
            "tracks_truncated": len(self._context.tracks) > MAX_TRACK_ROWS,
            "instruments": [
                {"id": instrument_id, "key": key}
                for key, instrument_id in BDO_INSTRUMENTS.items()
            ],
        }

    def _bounds(self, first_bar: int, bars: int) -> tuple[float, float]:
        start = max((first_bar - 1) * self._bar_ms, self._time_range_ms[0])
        end = min((first_bar - 1 + bars) * self._bar_ms, self._time_range_ms[1])
        if not start < end:
            raise ScoreAgentToolError("empty_time_selection")
        return start, end

    def _projected_notes(self) -> tuple[Note, ...]:
        if self._editor_notes is not None:
            if len(self._editor_notes) > MAX_PROJECTION_NOTES:
                raise ScoreAgentToolError("score_evidence_too_large")
            return self._editor_notes
        track = self._track
        if track is None:
            raise ScoreAgentToolError("select_track")
        if not track.notes:
            return ()
        clips = max(1, len(track.arrangement_clips))
        # Unowned notes can consult other Clips to establish source ownership.
        # Bound that work as well as the number of notes sent to the model.
        weight = clips if self._clip_id else clips * clips
        if (
            len(track.notes) > MAX_PROJECTION_NOTES
            or clips > MAX_PROJECTION_CLIPS
            or len(track.notes) * weight > MAX_PROJECTION_WORK
        ):
            raise ScoreAgentToolError("score_evidence_too_large")
        if self._projected is None:
            if self._clip_id:
                self._projected = project_clip_notes(track, self._clip_id)
            else:
                self._projected = project_track_notes(track)
        return self._projected

    def _notes(self, first_bar: int, bars: int) -> list[Note]:
        start, end = self._bounds(first_bar, bars)
        result = []
        for note in self._projected_notes():
            if not (math.isfinite(note.start) and math.isfinite(note.dur)):
                continue
            visible_start = max(start, note.start)
            visible_end = min(end, note.start + note.dur)
            if visible_end > visible_start and 0 <= note.pitch <= 127 and 0 <= note.vel <= 127:
                result.append(note._replace(start=visible_start, dur=visible_end - visible_start))
        return result

    def _inspect_music(self, first_bar: int, bars: int) -> dict:
        notes = self._notes(first_bar, bars)
        return {
            "first_bar": first_bar,
            "bars": bars,
            "pitch_range": [min(n.pitch for n in notes), max(n.pitch for n in notes)] if notes else None,
            "velocity_range": [min(n.vel for n in notes), max(n.vel for n in notes)] if notes else None,
            "note_count": len(notes),
            "notes_truncated": len(notes) > MAX_NOTE_EVIDENCE,
            "notes": [
                {"pitch": n.pitch, "start_ms": round(n.start, 3),
                 "duration_ms": round(n.dur, 3), "velocity": n.vel}
                for n in notes[:MAX_NOTE_EVIDENCE]
            ],
        }

    def _inspect_reference_audio(self, first_bar: int, bars: int) -> dict:
        """Measure a bounded passage with the same score scope on a worker."""
        start, end = self._bounds(first_bar, bars)
        if self._reference_audio is None:
            raise ScoreAgentToolError("reference_audio_not_linked")
        try:
            evidence = inspect_reference_audio(self._reference_audio, start_ms=start, end_ms=end)
        except ReferenceAudioEvidenceError as error:
            raise ScoreAgentToolError(error.code) from None
        alignment = []
        if self._track is not None:
            audio_start, audio_end = evidence["analyzed_project_range_ms"]
            evidence["score_note_starts"], alignment = self._note_starts_in_audio_range(
                max(start, audio_start), min(end, audio_end), evidence["transient_candidates"],
            )
        evidence["transient_score_alignment"] = alignment
        return {"first_bar": first_bar, "bars": bars, **evidence}

    def _note_starts_in_audio_range(
        self, start_ms: float, end_ms: float, transients: list[dict],
    ) -> tuple[dict, list[dict]]:
        from bisect import bisect_left

        try:
            notes = self._projected_notes()
        except ScoreAgentToolError as error:
            return {"error": error.code}, []
        visible = sorted(
            (note for note in notes if start_ms <= note.start < end_ms and 0 <= note.pitch <= 127),
            key=lambda note: (note.start, note.pitch),
        )
        alignment = []
        for transient in transients:
            audio_ms = transient["project_ms"]
            bar_index = int(audio_ms // self._bar_ms)
            bar_start = bar_index * self._bar_ms
            bar_end = (bar_index + 1) * self._bar_ms
            # Search the whole common range, including onsets omitted from the
            # separately capped list. Avoid turning a sustained note into an attack.
            index = bisect_left(visible, bar_start, key=lambda note: note.start)
            onset = visible[index].start if index < len(visible) and visible[index].start < bar_end else None
            # The audio result rounds timestamps to the nearest microsecond.
            full_bar = (not self._editor_notes_are_selection
                        and start_ms <= bar_start + 0.0005 and end_ms >= bar_end - 0.0005)
            alignment.append({
                "project_ms": audio_ms,
                "project_bar": bar_index + 1,
                "first_visible_score_onset_ms": round(onset, 3) if onset is not None else None,
                "delta_ms": round(audio_ms - onset, 3) if onset is not None else None,
                "bar_coverage": "full" if full_bar else "partial",
            })
        return {
            "total": len(visible),
            "truncated": len(visible) > MAX_AUDIO_NOTE_STARTS,
            "notes": [
                {"project_ms": round(note.start, 3), "pitch": note.pitch}
                for note in visible[:MAX_AUDIO_NOTE_STARTS]
            ],
        }, alignment

    def _analyze_harmony(self, first_bar: int, bars: int) -> dict:
        if self._track is not None and self._track.is_percussion:
            raise ScoreAgentToolError("melodic_track_required")
        notes = self._notes(first_bar, bars)
        sampled = notes[:MAX_ANALYSIS_NOTES]
        result = analyse_music(sampled, self._context.bpm, self._context.meter, 420.0)
        return {
            "first_bar": first_bar,
            "bars": bars,
            "evidence": "rule_based_estimate",
            "key_pitch_class": result.key_root,
            "key_mode": result.key_mode,
            "key_confidence": round(result.tonal_confidence, 3),
            "analyzed_note_count": len(sampled),
            "notes_truncated": len(notes) > len(sampled),
            "windows_truncated": len(result.harmony) > MAX_HARMONY_WINDOWS,
            "harmony": [
                {"start_ms": round(window.start, 3),
                 "pitch_classes": sorted(window.pitch_classes),
                 "chord_root": window.root, "chord_quality": window.quality}
                for window in result.harmony[:MAX_HARMONY_WINDOWS]
            ],
        }

    def _creative_plan(self, args: dict) -> dict:
        if self.proposal is not None:
            raise ScoreAgentToolError("proposal_already_staged")
        try:
            action = CreationAction(args.get("action"))
        except (TypeError, ValueError) as exc:
            raise ScoreAgentToolError("unknown_creation_action") from exc
        allowed = {"action", *_BAR_FIELDS, *_PLAN_FIELDS_BY_ACTION[action]}
        if args.keys() - allowed:
            raise ScoreAgentToolError("unknown_arguments")
        if action not in self._available_actions():
            raise ScoreAgentToolError("action_outside_selection")
        first_bar, bars = self._range(args)
        track = self._track
        clip_id = "" if action is CreationAction.DRAFT else self._clip_id
        if action is not CreationAction.ADAPT:
            start, end = self._bounds(first_bar, bars)
            if ((first_bar - 1) * self._bar_ms < start - 1e-6
                    or (first_bar - 1 + bars) * self._bar_ms > end + 1e-6):
                raise ScoreAgentToolError("proposal_requires_complete_bars")
        try:
            character = MusicalCharacter(args.get("character", MusicalCharacter.LYRICAL))
        except (TypeError, ValueError) as exc:
            raise ScoreAgentToolError("unknown_musical_character") from exc
        melody = _instrument(args.get("melody_instrument_id", 17))
        harmony = _instrument(args.get("harmony_instrument_id", 17))
        bass = _instrument(args.get("bass_instrument_id", 14))
        drum_set = BDO_INSTRUMENTS["drum_set"]
        if action is CreationAction.ADAPT:
            if (first_bar, bars) != (self.first_bar, self.bars):
                raise ScoreAgentToolError("adapt_requires_whole_track")
            melody = _instrument(args.get("instrument_id"))
            if track.is_percussion != (melody == drum_set):
                raise ScoreAgentToolError("instrument_role_mismatch")
        elif drum_set in (melody, harmony, bass):
            raise ScoreAgentToolError("instrument_role_mismatch")
        rewrite_velocity = _boolean(args.get("rewrite_velocity", False))
        scale_percent = None
        if "velocity_scale_percent" in args:
            scale_percent = _integer(
                args["velocity_scale_percent"], MIN_RELATIVE_VELOCITY_PERCENT, MAX_RELATIVE_VELOCITY_PERCENT,
            )
            if rewrite_velocity:
                raise ScoreAgentToolError("velocity_scale_conflicts_with_rewrite")
        brief = CreationBrief(
            action=action,
            character=character,
            tonic=_integer(args.get("tonic", 0), 0, 11),
            minor=_boolean(args.get("minor", False)),
            start_bar=first_bar - 1,
            bars=bars,
            source_track_id=None if action is CreationAction.DRAFT else track.track_id,
            melody_instrument=melody,
            harmony_instrument=harmony,
            bass_instrument=bass,
            rewrite_velocity=rewrite_velocity,
            shape_durations=_boolean(args.get("shape_durations", False)),
            velocity_scale_percent=scale_percent,
        )
        self.proposal = AgentProposal(brief, clip_id)
        result = {
            "status": "prepared_for_application",
            "action": action.value,
            "first_bar": first_bar,
            "bars": bars,
            "whole_track": action is CreationAction.ADAPT,
        }
        if scale_percent is not None:
            result["velocity_scale_percent"] = scale_percent
        return result
