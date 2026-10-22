"""Deterministic musical baselines behind explicit authoring actions.

These rules create alternatives, not recovered ground truth or a trained
style model. Generation and arrangement never rewrite the reference melody.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import replace
from itertools import product

from bdo_midi import _GM_TO_BDO_DRUM
from optimization.plugin_api import (
    CreateTrack, NoteSnapshot, OptimizationPreview, OptimizationRequest,
    ReplaceNote, SetTrackInstrument, validate_preview,
)
from .brief import (
    CreationAction, CreationBrief, CreationCandidate, CreationFinding,
    MusicalCharacter, ProposalPart,
)


ENGINE_ID = "composer-authoring-rules"
ENGINE_VERSION = "2"
_MAJOR = (0, 2, 4, 5, 7, 9, 11)
_MINOR = (0, 2, 3, 5, 7, 8, 10)
_PROGRESSIONS = ((0, 5, 3, 4), (0, 3, 1, 4), (5, 3, 4, 0))


def _scale(brief: CreationBrief) -> tuple[int, ...]:
    return tuple((brief.tonic + value) % 12 for value in (_MINOR if brief.minor else _MAJOR))


def _chord(scale: tuple[int, ...], degree: int) -> tuple[int, ...]:
    return tuple(scale[(degree + step) % 7] for step in (0, 2, 4))


def _pitch(request: OptimizationRequest, instrument: int, pitch_class: int, near: float) -> int:
    allowed = request.supported_pitches.get(instrument) or frozenset(range(128))
    choices = [p for p in sorted(allowed) if p % 12 == pitch_class % 12]
    if not choices:
        raise ValueError("the selected instrument cannot represent this pitch class")
    return min(choices, key=lambda p: (abs(p - near), p))


def _voicing(request, instrument, pcs, previous) -> tuple[int, ...]:
    candidates = []
    for pc in pcs:
        center = _pitch(request, instrument, pc, 55)
        allowed = request.supported_pitches.get(instrument) or frozenset(range(128))
        candidates.append(tuple(p for p in (center - 12, center, center + 12) if p in allowed))
    combinations = sorted(set(tuple(sorted(combo)) for combo in product(*candidates)))
    return min(combinations, key=lambda chord: (
        sum(abs(a - b) for a, b in zip(chord, previous or (48, 55, 60)))
        + max(0, chord[-1] - chord[0] - 16) * 2,
        chord,
    ))


def _harmony_from_melody(request, brief, notes) -> tuple[int | None, ...]:
    """Small dynamic program over seven diatonic triads; rests remain rests."""
    scale = _scale(brief)
    beat = 60_000.0 / request.bpm
    start, end = brief.time_range(request.bpm, request.time_sig)
    histograms = [[0.0] * 12 for _ in range(brief.bars)]
    # Overlap, not just onset, allows a held melody to support its next bar.
    for note in notes:
        lo, hi = max(start, note.start), min(end, note.start + note.dur)
        if lo >= hi:
            continue
        first = max(0, int((lo - start) // (beat * request.time_sig)))
        last = min(brief.bars - 1, int((hi - start - 1e-6) // (beat * request.time_sig)))
        for bar in range(first, last + 1):
            bar_start = start + bar * beat * request.time_sig
            overlap = max(0.0, min(hi, bar_start + beat * request.time_sig) - max(lo, bar_start)) / beat
            accent = 1.35 if abs((note.start - bar_start) / beat) < 0.12 else 1.0
            histograms[bar][note.pitch % 12] += overlap * accent
    result: list[int | None] = [None] * brief.bars
    position = 0
    while position < brief.bars:
        if not sum(histograms[position]):
            position += 1
            continue
        stop = position
        while stop < brief.bars and sum(histograms[stop]):
            stop += 1
        paths = {d: (0.0, ()) for d in range(7)}
        for bar in range(position, stop):
            histogram = histograms[bar]
            total = sum(histogram)
            updated = {}
            for d in range(7):
                pcs = _chord(scale, d)
                fit = sum(histogram[p] for p in pcs) / total
                # Penalize sustained semitone conflicts, without quantizing or
                # deleting chromatic melody notes to make our harmony fit.
                clash = sum(histogram[p] for p in range(12) if p not in pcs and any((p - c) % 12 in (1, 11) for c in pcs)) / total
                preference = 0.035 if (d + brief.variant) % 3 == 0 else 0.0
                cadence = 0.12 if d == 0 and bar == stop - 1 else 0.0
                options = []
                for prev, (score, path) in paths.items():
                    transition = 0.08 if (prev - d) % 7 in (3, 4) else 0.0
                    repetition = -0.06 if prev == d else 0.0
                    options.append((score + fit - .35 * clash + preference + cadence + transition + repetition, path + (d,)))
                updated[d] = max(options, key=lambda item: (item[0], tuple(-d for d in item[1])))
            paths = updated
        chosen = max(paths.values(), key=lambda item: (item[0], tuple(-d for d in item[1])))[1]
        result[position:stop] = chosen
        position = stop
    return tuple(result)


def _generate_parts(request, brief, degrees):
    beat = 60_000.0 / request.bpm
    meter = request.time_sig
    start, end = brief.time_range(request.bpm, meter)
    scale = _scale(brief)
    character = brief.character
    velocity = {MusicalCharacter.LYRICAL: 67, MusicalCharacter.LIGHT: 77, MusicalCharacter.DRIVING: 88}[character]
    notes_by_role: dict[str, list[NoteSnapshot]] = {key: [] for key in ("melody", "harmony", "bass", "drums")}
    previous_chord = None
    previous_pitch = 72 + brief.tonic
    motif = ((0, 2, 1, 4), (2, 1, 0, 4), (4, 2, 3, 1))[brief.variant % 3]

    def add(role, instrument, pc, near, position, duration, vel):
        pitch = pc if role == "drums" else _pitch(request, instrument, pc, near)
        onset = start + position * beat
        duration = min(duration * beat, end - onset)
        if duration > 0:
            notes_by_role[role].append(NoteSnapshot(pitch, max(1, min(127, int(vel))), onset, duration, 99 if role == "drums" else 0))
        return pitch

    for bar, degree in enumerate(degrees):
        if degree is None:
            continue
        pcs = _chord(scale, degree)
        chord = _voicing(request, brief.harmony_instrument, pcs, previous_chord)
        previous_chord = chord
        phrase_lift = (0, 3, 6, -4)[bar % 4]
        if character is MusicalCharacter.LYRICAL:
            # Texture changes remain audible even when the melody supports
            # only one harmony. Do not force worse chords merely for variety.
            texture = brief.variant % 3
            if texture == 2:
                for i in range(meter):
                    pitch = chord[i % len(chord)]
                    add("harmony", brief.harmony_instrument, pitch % 12, pitch,
                        bar * meter + i, .92, velocity - 20 + phrase_lift)
            else:
                pulses = 1 if texture == 0 else 2
                for pulse in range(pulses):
                    for pitch in chord:
                        add("harmony", brief.harmony_instrument, pitch % 12, pitch,
                            bar * meter + pulse * meter / pulses,
                            meter / pulses * .92, velocity - 20 + phrase_lift)
        else:
            step = .5 if character is MusicalCharacter.LIGHT else 1.0
            for i in range(round(meter / step)):
                pitch = chord[(i + brief.variant) % 3]
                add("harmony", brief.harmony_instrument, pitch % 12, pitch, bar * meter + i * step, step * .82, velocity - 23 + (5 if i % 2 == 0 else 0))
        for i, offset in enumerate((0.0, meter / 2.0)):
            pc = pcs[0 if i == 0 else 2]
            add("bass", brief.bass_instrument, pc, 40 + brief.tonic, bar * meter + offset, meter * .43, velocity - 15 + (5 if i == 0 else 0))
        if brief.action is CreationAction.DRAFT:
            step = 1.0 if character is MusicalCharacter.LYRICAL else .5
            count = round(meter / step)
            for i in range(count):
                # Leave an intentional phrase-end breath rather than filling
                # every rhythmic slot. Final cadence lands on the tonic.
                if bar % 4 == 3 and i == count - 1:
                    continue
                degree_offset = motif[(i + bar // 4) % len(motif)]
                pc = pcs[(i // 2) % 3] if i % 2 == 0 else scale[(degree + degree_offset) % 7]
                if bar == len(degrees) - 1 and i == 0:
                    pc = scale[0]
                near = 72 + brief.tonic if i == 0 and bar % 4 == 0 else previous_pitch
                previous_pitch = add("melody", brief.melody_instrument, pc, near, bar * meter + i * step, step * (.92 if character is MusicalCharacter.LYRICAL else .78), velocity + phrase_lift + (6 if i == 0 else -2))
        for i in range(meter):
            add("drums", 13, 48 if i % 2 == 0 else 50, 0, bar * meter + i, .12, velocity - 12)
            if character is not MusicalCharacter.LYRICAL:
                for off in (0.0, .5):
                    add("drums", 13, 54, 0, bar * meter + i + off, .08, velocity - 35 + (4 if off == 0 else 0))
    return notes_by_role


def _adapt(request, brief, track):
    instrument = brief.melody_instrument
    if track.is_percussion != (instrument == request.drum_instrument_id):
        raise ValueError("melodic and percussion tracks cannot exchange roles")
    supported = request.supported_pitches.get(instrument)
    ntypes = {0, *(n for n, _ in request.supported_articulations.get(instrument, ()))}
    ops, counts = [], defaultdict(int)
    if instrument != track.instrument_id:
        ops.append(SetTrackInstrument(track.track_id, track.instrument_id, instrument))
    for index, note in enumerate(track.notes):
        pitch, ntype = note.pitch, note.ntype
        if track.is_percussion:
            if brief.drums_are_gm:
                if pitch not in _GM_TO_BDO_DRUM:
                    raise ValueError("an imported drum pitch has no confirmed BDO mapping")
                pitch = _GM_TO_BDO_DRUM[pitch]
            elif not 48 <= pitch <= 64:
                raise ValueError("choose GM encoding explicitly for noncanonical drum input")
            ntype = 99
        else:
            if supported and pitch not in supported:
                pitch = _pitch(request, instrument, pitch % 12, pitch)
            # A catalog mismatch in an imported score is not evidence that
            # the player's manual articulation is wrong. Only choosing a
            # different instrument makes a new articulation contract apply.
            if instrument != track.instrument_id and ntype not in ntypes:
                ntype = 0
        after = replace(note, pitch=pitch, ntype=ntype)
        counts["octave_moves"] += int(note.pitch != pitch)
        counts["articulation_resets"] += int(note.ntype != ntype)
        if after != note:
            ops.append(ReplaceNote(track.track_id, index, note, after, "game-adaptation"))
    findings = [CreationFinding(k, v) for k, v in counts.items() if v]
    if not supported and not track.is_percussion:
        findings.append(CreationFinding("unknown_range"))
    if brief.drums_are_gm:
        findings.append(CreationFinding("explicit_gm_drums"))
    return ops, findings


def _express(request, brief, track):
    start, end = brief.time_range(request.bpm, request.time_sig)
    selected = [(i, n) for i, n in enumerate(track.notes) if start <= n.start < end and n.vel > 0]
    beat = 60_000.0 / request.bpm
    groups = defaultdict(list)
    for i, note in selected:
        groups[int((note.start - start) // (beat * request.time_sig))].append((i, note))
    onsets = sorted({n.start for _, n in selected})
    ops, expressive_bars = [], 0
    base = {MusicalCharacter.LYRICAL: 67, MusicalCharacter.LIGHT: 77, MusicalCharacter.DRIVING: 88}[brief.character]
    gate = {MusicalCharacter.LYRICAL: .94, MusicalCharacter.LIGHT: .70, MusicalCharacter.DRIVING: .82}[brief.character]
    for bar, group in sorted(groups.items()):
        flat = max(n.vel for _, n in group) - min(n.vel for _, n in group) <= 6
        rewrite = brief.rewrite_velocity or flat
        expressive_bars += int(not rewrite)
        for index, note in group:
            # Manual note and track articulations encode user intent. The
            # default rule never changes their velocity, length or ntype.
            if note.ntype not in (0, 99) or (track.articulation_type not in (None, 0)):
                continue
            position = (note.start - start) / beat
            bar_phase = position % request.time_sig
            accent = 8 if bar_phase < .08 else (2 if abs(bar_phase - round(bar_phase)) < .08 else -5)
            phrase = (0, 4, 8, -5)[bar % 4]
            vel = max(1, min(127, base + accent + phrase)) if rewrite else note.vel
            dur = note.dur
            if brief.shape_durations:
                next_index = bisect_right(onsets, note.start + 1e-6)
                following = onsets[next_index] if next_index < len(onsets) else min(end, note.start + beat)
                dur = max(1.0, min(beat * (1.5 if brief.character is MusicalCharacter.LYRICAL else 1.0), following - note.start, end - note.start) * gate)
            after = replace(note, vel=vel, dur=dur)
            if after != note:
                ops.append(ReplaceNote(track.track_id, index, note, after, "expression"))
    return ops, [CreationFinding("preserved_expression", expressive_bars)] if expressive_bars else []


def propose_creation(request: OptimizationRequest, brief: CreationBrief) -> CreationCandidate:
    """Return one bounded, game-validated alternative without touching input."""
    if not 2 <= request.time_sig <= 6 or request.bpm <= 0:
        raise ValueError("authoring currently supports meters 2/4 through 6/4")
    track = next((t for t in request.tracks if t.track_id == brief.source_track_id), None)
    if brief.action is not CreationAction.DRAFT and track is None:
        raise ValueError("select a source track")
    if track is not None and brief.action in (CreationAction.ADAPT, CreationAction.EXPRESS) and track.track_id not in request.target_track_ids:
        raise ValueError("the selected track is outside the write scope")
    if brief.action in (CreationAction.DRAFT, CreationAction.ACCOMPANY) and request.scope != "global":
        raise ValueError("new parts require explicit project scope")
    operations, parts, findings, degrees = [], [], [], ()
    if brief.action in (CreationAction.DRAFT, CreationAction.ACCOMPANY):
        if brief.action is CreationAction.ACCOMPANY and track.is_percussion:
            raise ValueError("accompaniment requires a melodic reference")
        progression = _PROGRESSIONS[brief.variant % len(_PROGRESSIONS)]
        degrees = tuple(progression[i % 4] if i < brief.bars - 1 else 0 for i in range(brief.bars)) if brief.action is CreationAction.DRAFT else _harmony_from_melody(request, brief, track.notes)
        if not any(d is not None for d in degrees):
            findings.append(CreationFinding("empty_reference"))
        else:
            roles = _generate_parts(request, brief, degrees)
            instruments = {"melody": brief.melody_instrument, "harmony": brief.harmony_instrument, "bass": brief.bass_instrument, "drums": request.drum_instrument_id}
            for role, notes in roles.items():
                if not notes:
                    continue
                index = len(operations)
                instrument = instruments[role]
                # Names are role IDs until the UI names the created tracks.
                operations.append(CreateTrack(role, instrument, role == "drums", tuple(notes), brief.source_track_id, "creation", .5, "rule-based musical alternative"))
                parts.append(ProposalPart(role, (index,), len(notes), instrument))
            findings.append(CreationFinding("rule_draft"))
            texture = brief.variant % 3 if brief.character is MusicalCharacter.LYRICAL else 2
            findings.append(CreationFinding(("sustained_harmony", "pulsed_harmony", "arpeggiated_harmony")[texture]))
    else:
        operations, findings = _adapt(request, brief, track) if brief.action is CreationAction.ADAPT else _express(request, brief, track)
        affected = len(track.notes) if any(isinstance(o, SetTrackInstrument) for o in operations) else sum(isinstance(o, ReplaceNote) for o in operations)
        parts = [ProposalPart("adaptation" if brief.action is CreationAction.ADAPT else "expression", tuple(range(len(operations))), affected, brief.melody_instrument if brief.action is CreationAction.ADAPT else track.instrument_id)]
    if not operations:
        findings.append(CreationFinding("no_changes"))
    preview = OptimizationPreview(request.source_fingerprint, ENGINE_ID, ENGINE_VERSION, tuple(operations))
    validate_preview(request, preview)
    return CreationCandidate(brief, preview, tuple(parts), tuple(findings), degrees)


def select_parts(candidate: CreationCandidate, keys: frozenset[str]) -> OptimizationPreview:
    known = {part.key for part in candidate.parts}
    if not keys.issubset(known):
        raise ValueError("unknown proposal part")
    indices = {i for part in candidate.parts if part.key in keys for i in part.operation_indices}
    return replace(candidate.preview, operations=tuple(op for i, op in enumerate(candidate.preview.operations) if i in indices))
