"""Standard MIDI import for the editor's millisecond note model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import mido

from .compatibility import load_midi_file
from .model import ChannelGroup, MidiGroupEvidence, Note


DEFAULT_BPM = 120
DEFAULT_TIME_SIGNATURE = 4
FLATTENED_TEMPO_BPM = 200
_TEXT_EVENT_TYPES = frozenset({"lyrics", "text", "marker", "cue_marker"})


def _absolute_events(
    tracks: Sequence[mido.MidiTrack],
) -> Iterator[tuple[int, int, Any]]:
    """Merge tracks without cloning messages, preserving file order at equal ticks."""
    timeline: list[tuple[int, int, int, Any]] = []
    order = 0
    for track_index, track in enumerate(tracks):
        tick = 0
        for message in track:
            tick += message.time
            # End-of-track deltas establish the last known sustain boundary.
            timeline.append((tick, order, track_index, message))
            order += 1
    timeline.sort(key=lambda event: (event[0], event[1]))
    for tick, _order, track_index, message in timeline:
        yield tick, track_index, message


def _track_identity(
    tracks: Sequence[mido.MidiTrack],
) -> tuple[dict[int, str], dict[int, str]]:
    track_names: dict[int, str] = {}
    instrument_names: dict[int, str] = {}
    for track_index, track in enumerate(tracks):
        for message in track:
            value = str(getattr(message, "name", "") or "").strip()
            if message.type == "track_name" and value and track_index not in track_names:
                track_names[track_index] = value
            elif (
                message.type == "instrument_name"
                and value
                and track_index not in instrument_names
            ):
                instrument_names[track_index] = value
    return track_names, instrument_names


def _midi_dialect(tracks: Sequence[mido.MidiTrack]) -> str:
    """Recognize common reset dialects without guessing from vendor-only data."""

    detected: set[str] = set()
    for track in tracks:
        for message in track:
            if message.type != "sysex":
                continue
            data = tuple(int(value) for value in message.data)
            if len(data) >= 4 and data[:3] == (0x7E, 0x7F, 0x09):
                if data[3] == 0x03:
                    detected.add("GM2")
                elif data[3] == 0x01:
                    detected.add("GM1")
            elif len(data) >= 4 and data[:4] == (0x41, 0x10, 0x42, 0x12):
                detected.add("GS")
            elif len(data) >= 3 and data[:3] == (0x43, 0x10, 0x4C):
                detected.add("XG")
    if not detected:
        return "unknown"
    return "+".join(name for name in ("GM1", "GM2", "GS", "XG") if name in detected)


def _read_header_events(
    mid: mido.MidiFile,
    *,
    require_quarter_denominator: bool,
) -> tuple[list[tuple[int, int]], int]:
    tempos: list[tuple[int, int]] = []
    numerator = DEFAULT_TIME_SIGNATURE
    signature_found = False
    for track in mid.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == "set_tempo":
                tempos.append((tick, int(message.tempo)))
            elif message.type == "time_signature":
                if (
                    require_quarter_denominator
                    and int(message.denominator) != 4
                ):
                    raise ValueError(
                        f"BDO v9 only supports a /4 meter; MIDI uses "
                        f"{message.numerator}/{message.denominator}"
                    )
                if not signature_found:
                    numerator = int(message.numerator)
                    signature_found = True

    tempos.sort(key=lambda item: item[0])
    default_tempo = int(mido.bpm2tempo(DEFAULT_BPM))
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, default_tempo))

    normalized: list[tuple[int, int]] = []
    for tick, tempo in tempos:
        if tick < 0:
            raise ValueError("Invalid MIDI tempo map")
        if normalized and normalized[-1][0] == tick:
            normalized[-1] = (tick, tempo)
        else:
            normalized.append((tick, tempo))
    return normalized, numerator


def _control_event(message: Any, time_ms: float) -> dict[str, int | float | str] | None:
    common: dict[str, int | float | str] = {
        "time": round(time_ms, 3),
        "kind": str(message.type),
        "channel": int(message.channel),
    }
    if message.type == "control_change":
        common.update(control=int(message.control), value=int(message.value))
    elif message.type == "pitchwheel":
        common["pitch"] = int(message.pitch)
    elif message.type == "aftertouch":
        common["value"] = int(message.value)
    elif message.type == "polytouch":
        common.update(note=int(message.note), value=int(message.value))
    else:
        return None
    return common


def parse_midi(
    midi_path: str | Path,
    apply_sustain: bool = True,
    flatten_tempo: bool = False,
    include_controls: bool = False,
    include_lyrics: bool = False,
    include_group_evidence: bool = False,
    include_compatibility_repairs: bool = False,
    allow_compatibility_repairs: bool = False,
    require_quarter_denominator: bool = True,
) -> tuple:
    """Parse a MIDI file into channel/program groups using real-time milliseconds.

    The variable-length return contract is retained for existing application
    callers: the first four values are BPM, meter numerator, channel groups,
    and normalized tempo-map size. Controls and text events are appended when
    their corresponding flags are enabled.
    """
    mid, compatibility_repairs = load_midi_file(
        midi_path,
        allow_compatibility_repairs=allow_compatibility_repairs,
    )
    if mid.type not in (0, 1):
        raise ValueError(f"MIDI type {mid.type} has asynchronous tracks and is not supported")
    tempo_map, numerator = _read_header_events(
        mid,
        require_quarter_denominator=require_quarter_denominator,
    )
    bpm = (
        FLATTENED_TEMPO_BPM
        if flatten_tempo and len(tempo_map) > 1
        else round(mido.tempo2bpm(tempo_map[0][1]))
    )

    GroupKey = tuple[int, int, int, int, bool]
    notes_by_group: dict[GroupKey, list[Note]] = defaultdict(list)
    controls_by_group: dict[GroupKey, list[dict]] = defaultdict(list)
    source_tracks_by_group: dict[GroupKey, set[int]] = defaultdict(set)
    text_events: list[dict[str, float | str]] = []
    programs: dict[int, int] = defaultdict(int)
    bank_msb: dict[int, int] = defaultdict(int)
    bank_lsb: dict[int, int] = defaultdict(int)
    pedal_down: dict[int, bool] = defaultdict(bool)
    ActiveNote = tuple[int, float, int, int, int, int]
    active: dict[tuple[int, int, int], ActiveNote] = {}
    pedal_held: dict[tuple[int, int, int], ActiveNote] = {}
    track_names, instrument_names = _track_identity(mid.tracks)
    midi_dialect = _midi_dialect(mid.tracks)

    def group_key(
        channel: int,
        program: int,
        group_bank_msb: int | None = None,
        group_bank_lsb: int | None = None,
    ) -> GroupKey:
        percussion = channel == 9
        return (
            channel,
            bank_msb[channel] if group_bank_msb is None else group_bank_msb,
            bank_lsb[channel] if group_bank_lsb is None else group_bank_lsb,
            program,
            percussion,
        )

    def finish_note(
        channel: int,
        pitch: int,
        velocity: int,
        start_ms: float,
        end_ms: float,
        program: int,
        group_bank_msb: int,
        group_bank_lsb: int,
        track_index: int,
    ) -> None:
        duration = end_ms - start_ms
        if duration > 0:
            key = group_key(channel, program, group_bank_msb, group_bank_lsb)
            notes_by_group[key].append(
                Note(pitch, velocity, start_ms, duration, 0)
            )
            source_tracks_by_group[key].add(track_index)

    current_tempo = tempo_map[0][1]
    previous_tick = 0
    elapsed_ms = 0.0
    ticks_per_beat = mid.ticks_per_beat

    for tick, track_index, message in _absolute_events(mid.tracks):
        tick_delta = tick - previous_tick
        if tick_delta:
            elapsed_ms += tick_delta * current_tempo / ticks_per_beat / 1000.0
            previous_tick = tick

        if message.type == "set_tempo":
            current_tempo = int(message.tempo)
            continue
        if message.type in _TEXT_EVENT_TYPES:
            text_events.append({
                "time": round(elapsed_ms, 3),
                "kind": str(message.type),
                "text": str(getattr(message, "text", "")),
            })
        if not hasattr(message, "channel"):
            continue

        channel = int(message.channel)
        if message.type == "program_change":
            programs[channel] = int(message.program)
            continue

        if message.type == "control_change" and int(message.control) in (0, 32):
            if int(message.control) == 0:
                bank_msb[channel] = int(message.value)
            else:
                bank_lsb[channel] = int(message.value)

        control = _control_event(message, elapsed_ms)
        if control is not None:
            controls_by_group[group_key(channel, programs[channel])].append(control)

        if message.type == "control_change":
            if message.control != 64 or not apply_sustain:
                continue
            pedal_down[channel] = message.value >= 64
            if pedal_down[channel]:
                continue
            for identity, held in tuple(pedal_held.items()):
                if identity[0] != channel:
                    continue
                velocity, start_ms, program, msb, lsb, source_track = held
                finish_note(
                    channel, identity[1], velocity, start_ms, elapsed_ms,
                    program, msb, lsb, source_track,
                )
                del pedal_held[identity]
            continue

        identity = (channel, int(getattr(message, "note", -1)), track_index)
        if message.type == "note_on" and message.velocity > 0:
            if identity in pedal_held:
                velocity, start_ms, program, msb, lsb, source_track = pedal_held.pop(identity)
                finish_note(
                    channel, identity[1], velocity, start_ms, elapsed_ms,
                    program, msb, lsb, source_track,
                )
            if identity in active:
                velocity, start_ms, program, msb, lsb, source_track = active.pop(identity)
                finish_note(
                    channel, identity[1], velocity, start_ms, elapsed_ms,
                    program, msb, lsb, source_track,
                )
            active[identity] = (
                int(message.velocity), elapsed_ms, programs[channel],
                bank_msb[channel], bank_lsb[channel], track_index,
            )
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            if identity not in active:
                continue
            if apply_sustain and pedal_down[channel]:
                pedal_held[identity] = active.pop(identity)
            else:
                velocity, start_ms, program, msb, lsb, source_track = active.pop(identity)
                finish_note(
                    channel, identity[1], velocity, start_ms, elapsed_ms,
                    program, msb, lsb, source_track,
                )

    for unfinished in (active, pedal_held):
        for (channel, pitch, _identity_track), (
            velocity, start_ms, program, msb, lsb, source_track,
        ) in unfinished.items():
            key = group_key(channel, program, msb, lsb)
            known_duration = elapsed_ms - start_ms
            notes_by_group[key].append(
                Note(pitch, velocity, start_ms,
                     known_duration if known_duration > 0 else 100.0, 0)
            )
            source_tracks_by_group[key].add(source_track)

    groups: list[ChannelGroup] = []
    aligned_controls: list[list[dict]] = []
    aligned_evidence: list[MidiGroupEvidence] = []
    for key in sorted(notes_by_group):
        group_notes = notes_by_group[key]
        if not group_notes:
            continue
        group_notes.sort(key=lambda note: note.start)
        channel, msb, lsb, source_program, percussion = key
        public_program = 0 if percussion else source_program
        groups.append((group_notes, public_program, percussion))
        aligned_controls.append(controls_by_group.get(key, []))
        source_track_indices = tuple(sorted(source_tracks_by_group[key]))
        aligned_evidence.append(MidiGroupEvidence(
            channel=channel,
            source_program=source_program,
            bank_msb=msb,
            bank_lsb=lsb,
            source_track_indices=source_track_indices,
            track_names=tuple(
                track_names[index]
                for index in source_track_indices
                if index in track_names
            ),
            instrument_names=tuple(
                instrument_names[index]
                for index in source_track_indices
                if index in instrument_names
            ),
            midi_dialect=midi_dialect,
        ))

    result: tuple = (bpm, numerator, groups, len(tempo_map))
    if include_controls:
        result += (aligned_controls,)
    if include_lyrics:
        result += (text_events,)
    if include_group_evidence:
        result += (aligned_evidence,)
    if include_compatibility_repairs:
        result += (compatibility_repairs,)
    return result


__all__ = [
    "DEFAULT_BPM", "DEFAULT_TIME_SIGNATURE", "FLATTENED_TEMPO_BPM",
    "parse_midi",
]
