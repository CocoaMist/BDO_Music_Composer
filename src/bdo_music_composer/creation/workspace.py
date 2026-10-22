"""Project/Clip bridge for authoring proposals; no Qt or user-file writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Callable

from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_TO_GM_PREVIEW_ROUTE, Note
from optimization.plugin_api import (
    InvalidOptimizationPreview, OptimizationIntensity,
    OptimizationRequest, apply_preview, build_request, validate_preview,
)
from bdo_music_composer.editor.arrangement_clip import (
    clip_authored_note_indices, clip_editor_notes, clip_editor_scope, plan_clip_note_edit,
    project_track_notes,
)
from bdo_music_composer.editor.bdo_instrument_adaptation import (
    articulation_pairs_by_instrument,
)
from bdo_music_composer.editor.editor_models import (
    ArrangementClipState, TrackState, game_supported_pitches,
)
from bdo_music_composer.editor.game_score_model import inherit_game_instrument_mix
from .brief import CreationAction, CreationBrief, CreationCandidate, CreationFinding, ProposalPart
from .engine import propose_creation, select_parts


def _copy_tracks(tracks) -> list[TrackState]:
    """Detach mutable containers while sharing immutable five-scalar Notes."""
    memo = {
        id(note): note
        for track in tracks for note in track.notes
        if type(note) is Note
    }
    return deepcopy(list(tracks), memo)


def projected_tracks(tracks: list[TrackState] | tuple[TrackState, ...]) -> list[TrackState]:
    """Freeze visible arrangement notes once, without projecting Clips twice."""
    return [replace(t, notes=list(project_track_notes(t)), arrangement_clips=[],
                    duration_scale=1.0, clip_start_ms=None, clip_end_ms=None)
            for t in tracks]


@dataclass(frozen=True)
class CreationContext:
    tracks: tuple[TrackState, ...]
    bpm: int
    meter: int
    denominator: int = 4

    @classmethod
    def capture(cls, tracks, bpm: int, meter: int, denominator: int = 4):
        if sum(len(t.notes) for t in tracks) > 50_000:
            raise ValueError("the score exceeds the authoring note limit")
        if denominator != 4:
            raise ValueError("authoring requires a meter with denominator 4")
        return cls(tuple(_copy_tracks(tracks)), int(bpm), int(meter), int(denominator))

    def assert_current(self, tracks, bpm: int, meter: int, denominator: int = 4):
        # A transaction guard, not a derived-state cache. Include Clip/mixer
        # fields that optimizer API v1's note fingerprint does not represent.
        if (self.bpm, self.meter, self.denominator) != (bpm, meter, denominator) or tuple(tracks) != self.tracks:
            raise InvalidOptimizationPreview("the editor changed after analysis; analyse again")


@dataclass(frozen=True)
class CreationSession:
    context: CreationContext
    request: OptimizationRequest
    base_tracks: tuple[TrackState, ...]
    candidate: CreationCandidate
    clip_id: str = ""
    _prepared_tracks: tuple[TrackState, ...] | None = field(default=None, repr=False, compare=False)
    _part_track_ids: tuple[tuple[str, tuple[int, ...]], ...] = ()

    def materialize(self, keys: frozenset[str]) -> list[TrackState]:
        """Select already-validated parts without reanalyzing the whole song."""
        select_parts(self.candidate, keys)
        if self._prepared_tracks is None:
            raise InvalidOptimizationPreview("authoring candidate is not prepared")
        if self.candidate.brief.action in (CreationAction.DRAFT, CreationAction.ACCOMPANY):
            selected_ids = {
                track_id for key, track_ids in self._part_track_ids if key in keys
                for track_id in track_ids
            }
            tracks = (*self.context.tracks, *(
                track for track in self._prepared_tracks if track.track_id in selected_ids
            ))
        else:
            tracks = self._prepared_tracks if keys else self.context.tracks
        return _copy_tracks(tracks)

    def _prepare_tracks(self) -> list[TrackState]:
        keys = frozenset(part.key for part in self.candidate.parts)
        preview = select_parts(self.candidate, keys)
        result, effects = apply_preview(
            self.base_tracks, self.request, preview,
            note_factory=Note, track_factory=TrackState,
        )
        if effects is not None:
            raise InvalidOptimizationPreview("authoring does not change global effects")
        original = _copy_tracks(self.context.tracks)
        known = {t.track_id for t in original}
        action = self.candidate.brief.action
        if action in (CreationAction.DRAFT, CreationAction.ACCOMPANY):
            start, end = self.candidate.brief.time_range(self.context.bpm, self.context.meter)
            for track in result:
                if track.track_id in known:
                    continue
                track.arrangement_clips = [ArrangementClipState(
                    f"creation-{track.track_id}", start, end, start, end,
                )]
                track.gm_program = BDO_TO_GM_PREVIEW_ROUTE[track.bdo_instrument_id].program
                # Reject conflicting peers rather than choosing an arbitrary
                # lane: v9 stores one Volume/Aux state per game instrument.
                inherit_game_instrument_mix(original, track)
                original.append(track)
            return original
        target_id = self.candidate.brief.source_track_id
        target = next(t for t in original if t.track_id == target_id)
        changed = next(t for t in result if t.track_id == target_id)
        if not preview.operations:
            return original
        if action is CreationAction.EXPRESS and self.clip_id:
            plan = plan_clip_note_edit(target, clip_id=self.clip_id, notes=changed.notes)
            update = plan.updates[0]
            target.notes = list(update.notes)
            target.performance_controls = list(update.performance_controls)
            target.bdo_source_note_records = update.source_note_records
            target.bdo_source_group_index = update.source_group_index
            target.clip_start_ms, target.clip_end_ms = update.clip_start_ms, update.clip_end_ms
            target.arrangement_clips = list(update.arrangement_clips)
        else:
            target.notes = list(changed.notes)
            target.bdo_instrument_id = changed.bdo_instrument_id
            if action is CreationAction.EXPRESS:
                scale = float(target.duration_scale)
                target.notes = [n._replace(dur=n.dur / scale) for n in target.notes]
            if action is CreationAction.ADAPT:
                if target.bdo_instrument_id != next(t.bdo_instrument_id for t in self.context.tracks if t.track_id == target_id):
                    valid = {0, *(n for n, _ in self.request.supported_articulations.get(target.bdo_instrument_id, ()))}
                    if target.articulation_type not in valid:
                        target.articulation_type = None
                    target.marnian_synth_mode = "basic"
                    target.gm_program = BDO_TO_GM_PREVIEW_ROUTE[target.bdo_instrument_id].program
                    inherit_game_instrument_mix(original, target)
        target.notes_optimized = True
        return original


def build_creation_session(context: CreationContext, brief: CreationBrief, clip_id: str = "") -> CreationSession:
    target = next((t for t in context.tracks if t.track_id == brief.source_track_id), None)
    if brief.action is CreationAction.ADAPT:
        base = _copy_tracks(context.tracks)
        clip_id = ""
    else:
        base = projected_tracks(context.tracks)
        if brief.action is CreationAction.EXPRESS:
            if target is None:
                raise ValueError("select a source track")
            index = next(i for i, t in enumerate(base) if t.track_id == target.track_id)
            if target.arrangement_clips and not clip_id:
                raise ValueError("select a Clip before shaping expression")
            if clip_id:
                clip_editor_scope(target, clip_id)
                notes = list(clip_editor_notes(target, clip_id))
            else:
                if not math_is_positive(target.duration_scale):
                    raise ValueError("invalid source duration scale")
                notes = [n._replace(dur=n.dur * target.duration_scale) for n in target.notes]
            base[index] = replace(base[index], notes=notes)
        elif brief.action is CreationAction.ACCOMPANY and clip_id and target is not None:
            index = next(i for i, t in enumerate(base) if t.track_id == target.track_id)
            base[index] = replace(base[index], notes=list(clip_editor_notes(target, clip_id)))
    supported = {i: p for i in BDO_INSTRUMENT_NAMES if (p := game_supported_pitches(i))}
    request = build_request(
        base, context.bpm, context.meter,
        frozenset({brief.source_track_id}) if brief.source_track_id is not None else frozenset(),
        supported, articulation_pairs_by_instrument(), OptimizationIntensity.CONSERVATIVE,
        "global" if brief.action in (CreationAction.DRAFT, CreationAction.ACCOMPANY) else "single_track",
        valid_instrument_ids=frozenset(BDO_INSTRUMENT_NAMES),
    )
    candidate = propose_creation(request, brief)
    if brief.action is CreationAction.EXPRESS and clip_id:
        scope = clip_editor_scope(target, clip_id)
        indices = clip_authored_note_indices(target, clip_id)
        operations = []
        protected = 0
        for operation in candidate.preview.operations:
            authored = target.notes[indices[operation.note_index]]
            visible = operation.before
            if (abs(authored.start + scope.time_offset_ms - visible.start) > 1e-6
                    or abs(authored.dur - visible.dur) > 1e-6):
                # The Clip owns only a cropped view of this long note. Keeping
                # it unchanged lets the existing Clip planner preserve its
                # hidden authored tail instead of replacing it with a crop.
                protected += 1
                continue
            operations.append(replace(operation, after=replace(
                operation.after,
                dur=min(operation.after.dur, scope.timeline_end_ms-operation.after.start),
            )))
        candidate = replace(candidate,
            preview=replace(candidate.preview, operations=tuple(operations)),
            parts=(ProposalPart("expression", tuple(range(len(operations))), len(operations), target.bdo_instrument_id),),
            findings=candidate.findings + ((CreationFinding("protected_clip_edges", protected),) if protected else ()),
        )
        validate_preview(request, candidate.preview)
        selected = select_parts(candidate, frozenset(p.key for p in candidate.parts))
        proposed, _ = apply_preview(base, request, selected, note_factory=Note, track_factory=TrackState)
        notes = next(t.notes for t in proposed if t.track_id == target.track_id)
        if any(not scope.contains_note(n) for n in notes):
            raise ValueError("expression would exceed the selected Clip")
    session = CreationSession(context, request, tuple(base), candidate, clip_id)
    prepared = tuple(session._prepare_tracks())
    known = {track.track_id for track in context.tracks}
    part_track_ids = tuple(
        (part.key, tuple(
            track.track_id for track in prepared
            if track.track_id not in known
            and (track.display_name == part.key or track.display_name.startswith(part.key + " "))
        ))
        for part in candidate.parts
    )
    return replace(session, _prepared_tracks=prepared, _part_track_ids=part_track_ids)


def build_creation_alternatives(
    context: CreationContext,
    brief: CreationBrief,
    clip_id: str = "",
    *,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[CreationSession, ...]:
    """Return distinct musical operations; variant numbers are not evidence of variety."""
    sessions = []
    seen = set()
    count = 3 if brief.action in (CreationAction.DRAFT, CreationAction.ACCOMPANY) else 1
    for variant in range(count):
        if cancelled():
            return ()
        session = build_creation_session(context, replace(brief, variant=variant), clip_id)
        signature = session.candidate.preview.operations
        if signature not in seen:
            sessions.append(session)
            seen.add(signature)
    return tuple(sessions)


def math_is_positive(value: float) -> bool:
    import math
    return math.isfinite(float(value)) and float(value) > 0
