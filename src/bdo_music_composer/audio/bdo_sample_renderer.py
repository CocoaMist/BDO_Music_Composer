"""Offline preview renderer for locally configured PCM sample maps."""

from __future__ import annotations

import json
import math
import os
import wave
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from bdo_music_composer.audio.pcm_wav import (
    pcm_bytes_to_float32,
    stereo_pcm,
)
from bdo_music_composer.audio.sample_pcm_paths import mapped_sample_paths, sample_search_roots
from bdo_music_composer.editor.arrangement_clip import project_track_notes

from bdo_music_composer.audio.bdo_audio_mixing import (
    apply_articulation_preview_in_place,
    prepare_sample_pcm,
    preview_chord_intervals,
)
from bdo_music_composer.audio.bdo_audio_lifecycle import (
    INSTANCE_LIMIT_RELEASE_MS,
    InstanceTimelineItem,
    VoiceLifecycle,
    detect_active_signal_frames,
    milliseconds_to_frames,
    plan_instance_timeline,
    sample_output_frames,
    voice_lifecycle,
)
from bdo_music_composer.audio.bdo_instrument_samples import (
    BDO_BANK_BY_ID,
    WwiseContainerRotation,
    bank_for_instrument,
    preview_has_native_articulation,
    preview_pitch_offset_semitones,
    preview_route_ntype,
    resolve_bdo_pitch,
    row_instance_limit,
    row_loop_points,
    row_release_ms,
    row_routes_ntype,
    row_volume_gain,
    sample_pitch_ratio,
    select_zone_row,
    select_zone_variants,
    velocity_zone_boundaries,
)
from bdo_midi import _GM_TO_BDO_DRUM as GM_TO_BDO_DRUM
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME, track_volume_preview_gain


SAMPLE_RATE = 36000


@lru_cache(maxsize=4)
def _cached_mapping_payload(
    map_path: str,
    modified_ns: int,
    size: int,
) -> dict:
    """Read one immutable packaged mapping once per runtime path.

    The mapping is large and is consulted by preview validation, the editor
    velocity hints, and optimisation preflight.  Callers treat rows as source
    metadata; code that needs to amend a resolved path makes its own copy.
    """

    return json.loads(Path(map_path).read_text(encoding="utf-8"))


def _mapping_payload(map_path: str | Path) -> dict:
    path, modified_ns, size = _mapping_revision(map_path)
    return _cached_mapping_payload(
        str(path),
        modified_ns,
        size,
    )


def _mapping_revision(map_path: str | Path) -> tuple[Path, int, int]:
    path = Path(map_path)
    metadata = path.stat()
    return path, int(metadata.st_mtime_ns), int(metadata.st_size)


def sample_map_evidence_sha256(map_path: str | Path) -> str | None:
    """Return the mapping evidence identity without reparsing its JSON."""

    value = _mapping_payload(map_path).get("evidence_sha256")
    return str(value) if isinstance(value, str) and value else None


@dataclass(frozen=True)
class RenderResult:
    duration_ms: float
    notes_rendered: int
    missing_instruments: tuple[int, ...]


@dataclass(frozen=True)
class _RenderRequest:
    start_ms: float
    track_order: int
    note_order: int
    track: object
    note: object
    synth_mode: str


@dataclass(frozen=True)
class _PreparedVoice:
    relative_start: int
    velocity: int
    playback_ratio: float
    sample: np.ndarray
    row: dict
    lifecycle: VoiceLifecycle
    loop_points: tuple[int, int] | None
    instrument_id: int
    ntype: int
    native_articulation: bool
    track_volume_gain: float
    gain_scale: float = 1.0
    count_note: bool = True


@dataclass(frozen=True)
class _PreparedEvent:
    relative_start: int
    audible_frames: int
    voice_indices: tuple[int, ...]
    instance_group_id: int = -1
    instance_scope_id: int = -1
    max_instances: int = 0
    kill_newest: bool = False


@dataclass(frozen=True, slots=True)
class _DecodedPreviewSample:
    pcm: np.ndarray
    rate: int
    active_frames: int


def _read_wav(path_string: str) -> _DecodedPreviewSample:
    path = Path(path_string)
    with wave.open(str(path), "rb") as source:
        sample_width = source.getsampwidth()
        if sample_width not in {2, 3}:
            raise ValueError(f"Unsupported sample width: {path}")
        channels = source.getnchannels()
        rate = source.getframerate()
        payload = source.readframes(source.getnframes())
    pcm, _gain = prepare_sample_pcm(stereo_pcm(
        pcm_bytes_to_float32(payload, sample_width, channels)
    ))
    return _DecodedPreviewSample(pcm, rate, detect_active_signal_frames(pcm, rate))


class BdoSampleMap:
    def __init__(
        self,
        map_path: str | Path,
        audio_root: str | Path | None = None,
        *,
        instrument_modes: Iterable[tuple[int, str]] | None = None,
    ) -> None:
        mapping_path = Path(map_path)
        payload = _mapping_payload(mapping_path)
        configured_root = (
            Path(audio_root)
            if audio_root
            else Path(os.environ["BDO_AUDIO_ROOT"])
            if os.environ.get("BDO_AUDIO_ROOT")
            else None
        )
        banks = None if instrument_modes is None else {
            bank_for_instrument(instrument_id, mode)
            for instrument_id, mode in instrument_modes
        }
        relative_roots = sample_search_roots(mapping_path, configured_root)
        resolved_paths: dict[str, str] = {}
        self.by_bank = {
            bank: [
                self._resolve_row_path(
                    row,
                    relative_roots,
                    resolved_paths,
                )
                for row in rows
                if row.get("wav_exists")
            ]
            for bank, rows in payload.get("banks", {}).items()
            if banks is None or bank in banks
        }

    @staticmethod
    def _resolve_row_path(
        row: dict,
        relative_roots: tuple[Path, ...],
        resolved_paths: dict[str, str],
    ) -> dict:
        raw_text = str(row.get("wav_path", "") or "")
        if raw_text in resolved_paths:
            return {**row, "wav_path": resolved_paths[raw_text]}
        raw_path = Path(raw_text)
        if raw_path.is_absolute() or not raw_path.parts:
            return row
        candidates = mapped_sample_paths(raw_path, relative_roots)
        selected = next(
            (candidate for candidate in candidates if candidate.is_file()),
            candidates[0],
        )
        resolved_paths[raw_text] = str(selected)
        return {**row, "wav_path": resolved_paths[raw_text]}

    def has_instrument(
        self, instrument_id: int, synth_mode: str = "basic"
    ) -> bool:
        bank = bank_for_instrument(instrument_id, synth_mode)
        return bool(bank and self.by_bank.get(bank))

    def has_complete_media(
        self,
        instrument_id: int,
        synth_mode: str = "basic",
    ) -> bool:
        """Whether every mapped WAV required by one bank exists locally.

        Mapping metadata describes structural coverage; it must not be used as
        proof that a configured external sample directory is complete.
        """

        bank = bank_for_instrument(instrument_id, synth_mode)
        paths = dict.fromkeys(str(row.get("wav_path", "")) for row in self.by_bank.get(bank or "", ()))
        return bool(paths) and all(Path(path).is_file() for path in paths)

    def supported_pitches(
        self, instrument_id: int, synth_mode: str = "basic"
    ) -> frozenset[int]:
        bank = bank_for_instrument(instrument_id, synth_mode)
        return frozenset(
            pitch
            for row in self.by_bank.get(bank or "", [])
            for pitch in range(int(row["key_min"]), int(row["key_max"]) + 1)
        )

    def choose(
        self,
        instrument_id: int,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        synth_mode: str = "basic",
        variant_index: int = 0,
    ) -> dict | None:
        bank = bank_for_instrument(instrument_id, synth_mode)
        route_ntype = preview_route_ntype(instrument_id, ntype)
        resolved_pitch = resolve_bdo_pitch(
            instrument_id,
            pitch,
            ntype,
        )
        return self.choose_bank(
            bank or "",
            resolved_pitch,
            velocity,
            route_ntype,
            variant_index,
        )

    def choose_variants(
        self,
        instrument_id: int,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        synth_mode: str = "basic",
    ) -> tuple[dict, ...]:
        bank = bank_for_instrument(instrument_id, synth_mode)
        route_ntype = preview_route_ntype(instrument_id, ntype)
        resolved_pitch = resolve_bdo_pitch(
            instrument_id,
            pitch,
            ntype,
        )
        return select_zone_variants(
            self.by_bank.get(bank or "", []),
            resolved_pitch,
            velocity,
            route_ntype,
            bank=bank,
        )

    def choose_bank(
        self,
        bank: str,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        variant_index: int = 0,
    ) -> dict | None:
        rows = self.by_bank.get(bank, [])
        return select_zone_row(
            rows,
            pitch,
            velocity,
            ntype,
            variant_index,
            bank=bank,
        )


@lru_cache(maxsize=4)
def _cached_sample_map(
    map_path: str,
    modified_ns: int,
    size: int,
) -> BdoSampleMap:
    del modified_ns, size
    return BdoSampleMap(map_path)


@lru_cache(maxsize=4)
def _cached_mapping_banks(
    map_path: str,
    modified_ns: int,
    size: int,
) -> dict[str, tuple[dict, ...]]:
    """Load routing metadata without probing thousands of local WAV paths."""
    del modified_ns, size
    payload = _mapping_payload(map_path)
    return {
        str(bank): tuple(rows)
        for bank, rows in payload.get("banks", {}).items()
    }


def _sample_map(map_path: str | Path) -> BdoSampleMap:
    path, modified_ns, size = _mapping_revision(map_path)
    return _cached_sample_map(str(path), modified_ns, size)


def _mapping_banks(map_path: str | Path) -> dict[str, tuple[dict, ...]]:
    path, modified_ns, size = _mapping_revision(map_path)
    return _cached_mapping_banks(str(path), modified_ns, size)



def sample_map_velocity_boundaries(
    map_path: str | Path,
    instrument_id: int,
    pitch: int,
    ntype: int = 0,
    synth_mode: str = "basic",
) -> tuple[int, ...]:
    """Cached metadata-only query for editor-side game mapping hints."""
    bank = bank_for_instrument(instrument_id, synth_mode)
    route_ntype = preview_route_ntype(instrument_id, ntype)
    resolved_pitch = resolve_bdo_pitch(instrument_id, pitch, ntype)
    return velocity_zone_boundaries(
        _mapping_banks(map_path).get(bank or "", ()),
        resolved_pitch,
        route_ntype,
        bank=bank,
    )


def sample_map_supported_pitches(
    map_path: str | Path,
    instrument_id: int,
    synth_mode: str = "basic",
) -> frozenset[int]:
    """Return the exact MIDI keys with a Wwise source zone for an instrument."""
    return _sample_map(map_path).supported_pitches(
        instrument_id, synth_mode
    )


def sample_map_supports_note(
    map_path: str | Path,
    instrument_id: int,
    pitch: int,
    velocity: int,
    ntype: int = 0,
    synth_mode: str = "basic",
) -> bool:
    """Whether Wwise has an exact key-and-velocity zone for this note."""
    return (
        _sample_map(map_path).choose(
            instrument_id,
            pitch,
            velocity,
            ntype,
            synth_mode,
        )
        is not None
    )


def _resample_for_note(
    sample: np.ndarray,
    playback_ratio: float,
    max_frames: int,
    start_output_frame: int = 0,
    *,
    loop_points: tuple[int, int] | None = None,
) -> np.ndarray:
    ratio = max(1.0e-9, float(playback_ratio))
    start_frame = max(0, int(start_output_frame))
    if loop_points is None:
        available_frames = max(
            0,
            math.ceil(len(sample) / ratio) - start_frame,
        )
        output_frames = min(max(0, int(max_frames)), available_frames)
    else:
        output_frames = max(0, int(max_frames))
    if output_frames <= 0:
        return np.empty((0, 2), dtype=np.float32)
    positions = (
        np.arange(output_frames, dtype=np.float64)
        + start_frame
    ) * ratio
    loop_start = loop_end = 0
    if loop_points is None:
        np.clip(
            positions,
            0.0,
            max(0, len(sample) - 1),
            out=positions,
        )
    else:
        loop_start, loop_end = loop_points
        loop_length = loop_end - loop_start
        looping = positions >= loop_end
        positions[looping] = loop_start + np.mod(
            positions[looping] - loop_start,
            loop_length,
        )
    indices = positions.astype(np.intp)
    fractions = positions - indices
    following = np.minimum(indices + 1, len(sample) - 1)
    if loop_points is not None:
        at_loop_boundary = (
            (positions >= loop_start)
            & (following >= loop_end)
        )
        following[at_loop_boundary] = loop_start
    rendered = np.asarray(sample[indices], dtype=np.float32).copy()
    rendered += (sample[following] - rendered) * fractions[:, None]
    return rendered


def render_preview(
    tracks: list,
    map_path: str | Path,
    output_path: str | Path,
    start_ms: float = 0.0,
    audio_root: str | Path | None = None,
) -> RenderResult:
    sample_map = BdoSampleMap(map_path, audio_root)
    missing: set[int] = set()
    requests: list[_RenderRequest] = []
    prepared: list[_PreparedVoice] = []
    prepared_events: list[_PreparedEvent] = []
    container_rotation = WwiseContainerRotation()
    samples: dict[str, _DecodedPreviewSample] = {}
    seek_frame = round(float(start_ms) * SAMPLE_RATE / 1000.0)

    for track_order, track in enumerate(tracks):
        synth_mode = str(
            getattr(track, "marnian_synth_mode", "basic") or "basic"
        )
        if not sample_map.has_instrument(
            track.bdo_instrument_id, synth_mode
        ):
            missing.add(track.bdo_instrument_id)
            continue
        for note_order, note in enumerate(project_track_notes(track)):
            requests.append(_RenderRequest(
                float(note.start),
                track_order,
                note_order,
                track,
                note,
                synth_mode,
            ))

    requests.sort(
        key=lambda request: (
            request.start_ms,
            request.track_order,
            request.note_order,
        )
    )
    for request in requests:
        track = request.track
        note = request.note
        synth_mode = request.synth_mode
        # Per-note velocity is already the game-native value.  The retired
        # ``volume_scale`` field is migration-only and must never create a
        # hidden preview/export difference.
        velocity = max(0, min(127, round(note.vel)))
        ntype = int(
            getattr(note, "ntype", 0)
            or getattr(track, "articulation_type", 0)
            or 0
        )
        variants = sample_map.choose_variants(
            track.bdo_instrument_id,
            note.pitch,
            velocity,
            ntype,
            synth_mode,
        )
        if not variants:
            missing.add(track.bdo_instrument_id)
            continue
        bank = bank_for_instrument(
            track.bdo_instrument_id,
            synth_mode,
        ) or ""
        selected = container_rotation.choose(bank, variants)
        if selected is None:
            missing.add(track.bdo_instrument_id)
            continue
        note_frames = max(
            1,
            round(
                note.dur
                * SAMPLE_RATE
                / 1000.0
            )
        )
        wav_path = str(selected["wav_path"])
        sample = samples.get(wav_path)
        if sample is None:
            sample = samples[wav_path] = _read_wav(wav_path)
        route_ntype = preview_route_ntype(
            track.bdo_instrument_id,
            ntype,
        )
        target_pitch = resolve_bdo_pitch(
            track.bdo_instrument_id,
            note.pitch,
            ntype,
        )
        native_sample_route = row_routes_ntype(
            selected,
            route_ntype,
        )
        native_articulation = preview_has_native_articulation(
            track.bdo_instrument_id,
            selected,
            route_ntype,
        )
        resample_pitch = target_pitch + (
            preview_pitch_offset_semitones(
                ntype,
                native_sample_route,
            )
        )
        ratio = sample_pitch_ratio(
            selected,
            resample_pitch,
            bank=bank,
        ) * sample.rate / SAMPLE_RATE
        # Pitch and device-rate conversion share one interpolation step.
        # Loop bounds stay in integer PCM frames at the source rate.
        loop_points = row_loop_points(selected, len(sample.pcm))
        lifecycle = voice_lifecycle(
            track.bdo_instrument_id,
            ntype,
            note_frames,
            sample_output_frames(
                sample.active_frames,
                ratio,
            ),
            SAMPLE_RATE,
            native_articulation=native_sample_route,
            sample_loops=loop_points is not None,
            release_ms=row_release_ms(selected),
        )
        instance_limit = row_instance_limit(selected)
        relative_start = milliseconds_to_frames(note.start, SAMPLE_RATE) - seek_frame
        can_sound = relative_start + lifecycle.audible_frames > 0
        if not (can_sound or instance_limit.enforceable):
            continue
        first_voice_index = len(prepared)
        if can_sound:
            layer_specs = [(ratio, ntype, native_articulation, 1.0, True)]
            layer_specs.extend(
                (ratio * (2.0 ** (semitones / 12.0)), 0, False, 0.52, False)
                for semitones in preview_chord_intervals(
                    ntype, native_articulation=native_articulation,
                )
            )
            track_gain = track_volume_preview_gain(
                getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
            )
            prepared.extend(
                _PreparedVoice(
                    relative_start=relative_start,
                    velocity=velocity,
                    playback_ratio=layer_ratio,
                    sample=sample.pcm,
                    row=selected,
                    lifecycle=lifecycle,
                    loop_points=loop_points,
                    instrument_id=track.bdo_instrument_id,
                    ntype=layer_ntype,
                    native_articulation=layer_native,
                    track_volume_gain=track_gain,
                    gain_scale=gain_scale,
                    count_note=count_note,
                )
                for layer_ratio, layer_ntype, layer_native, gain_scale, count_note in layer_specs
            )
        # A voice that expired before a seek can still have suppressed a later
        # voice. Keep that history in the planner without queuing PCM work.
        prepared_events.append(_PreparedEvent(
            relative_start=relative_start,
            audible_frames=lifecycle.audible_frames,
            voice_indices=tuple(
                range(first_voice_index, len(prepared))
            ),
            instance_group_id=(
                instance_limit.group_id
                if instance_limit.enforceable
                else -1
            ),
            instance_scope_id=(
                -1
                if instance_limit.global_scope
                else int(
                    getattr(track, "track_id", request.track_order)
                )
            ),
            max_instances=(
                instance_limit.max_instances
                if instance_limit.enforceable
                else 0
            ),
            kill_newest=instance_limit.kill_newest,
        ))

    instance_release_frames = max(
        1,
        round(SAMPLE_RATE * INSTANCE_LIMIT_RELEASE_MS / 1000.0),
    )
    instance_plan = plan_instance_timeline(
        [
            InstanceTimelineItem(
                start_frame=event.relative_start,
                audible_frames=event.audible_frames,
                group_id=event.instance_group_id,
                scope_id=event.instance_scope_id,
                max_instances=event.max_instances,
                kill_newest=event.kill_newest,
            )
            for event in prepared_events
        ],
        instance_release_frames,
    )
    planned_voices: list[_PreparedVoice] = []
    for event_index, event in enumerate(prepared_events):
        if not event.voice_indices or not instance_plan.accepted[event_index]:
            continue
        planned_lifecycle: VoiceLifecycle | None = None
        if instance_plan.forced_release[event_index]:
            planned_audible = instance_plan.audible_frames[event_index]
            planned_lifecycle = VoiceLifecycle(
                note_frames=(
                    prepared[event.voice_indices[0]].lifecycle.note_frames
                ),
                audible_frames=planned_audible,
                fade_out_frames=min(
                    planned_audible,
                    instance_release_frames,
                ),
            )
        for voice_index in event.voice_indices:
            voice = prepared[voice_index]
            planned_voices.append(
                replace(voice, lifecycle=planned_lifecycle)
                if planned_lifecycle is not None
                else voice
            )
    prepared = planned_voices
    end_frame = max(
        (
            voice.relative_start + voice.lifecycle.audible_frames
            for voice in prepared
        ),
        default=0,
    )
    frames = max(1, end_frame)
    mix = np.zeros((frames, 2), dtype=np.float32)
    rendered = 0
    for voice in prepared:
        start_frame = max(0, voice.relative_start)
        age_frames = max(0, -voice.relative_start)
        audible_remaining = max(
            0,
            voice.lifecycle.audible_frames - age_frames,
        )
        rendered_sample = _resample_for_note(
            voice.sample,
            voice.playback_ratio,
            audible_remaining,
            age_frames,
            loop_points=voice.loop_points,
        )
        if rendered_sample.size == 0:
            continue
        sample_end = min(len(mix), start_frame + len(rendered_sample))
        rendered_sample = rendered_sample[:sample_end - start_frame]
        rendered_sample *= (
            (voice.velocity / 127.0)
            * voice.track_volume_gain
            * row_volume_gain(voice.row)
            * voice.gain_scale
        )
        ages = age_frames + np.arange(
            len(rendered_sample), dtype=np.float32
        )
        apply_articulation_preview_in_place(
            rendered_sample,
            voice.instrument_id,
            voice.ntype,
            ages,
            voice.lifecycle.note_frames,
            SAMPLE_RATE,
            native_articulation=voice.native_articulation,
        )
        if voice.lifecycle.fade_out_frames > 0:
            fade = np.clip(
                (
                    voice.lifecycle.audible_frames
                    - ages
                    - 1.0
                )
                / voice.lifecycle.fade_out_frames,
                0.0,
                1.0,
            )
            rendered_sample *= fade[:, None]
        mix[start_frame:sample_end] += rendered_sample
        rendered += int(voice.count_note)

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak
    pcm = np.clip(mix * 32767.0, -32768, 32767).astype("<i2")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(pcm.tobytes())
    return RenderResult((len(mix) / SAMPLE_RATE) * 1000.0, rendered, tuple(sorted(missing)))
