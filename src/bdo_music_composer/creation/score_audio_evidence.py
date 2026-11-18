"""Read a bounded waveform and time-aligned evidence from linked reference audio."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path

import numpy as np

from bdo_music_composer.audio.reference_audio_format import (
    ReferenceAudioFormatError,
    SUPPORTED_REFERENCE_AUDIO_SUFFIXES,
    validate_reference_audio_file,
)


MAX_WAVEFORM_BINS = 96
MAX_REFERENCE_WINDOW_MS = 20_000
_MAX_INTERLEAVED_SAMPLES = 2_000_000
_MAX_CHANNELS = 8
_MAX_SAMPLE_RATE = 192_000
_SILENCE_DBFS = -60.0
_FLOOR_DBFS = -120.0
_DYNAMICS_FRAME_MS = 10
_SPECTRUM_FRAME_MS = 40
_MIN_ENERGY_RISE_DB = 5.0
_MIN_TRANSIENT_DISTANCE_MS = 60
_MAX_TRANSIENTS = 12
_SPECTRAL_BAND_EDGES_HZ = (20, 80, 250, 500, 2_000, 6_000, 20_000)


@dataclass(frozen=True, slots=True)
class ReferenceAudioEvidenceSource:
    """A snapshot of link and alignment state with a process-local path."""

    path: Path | str | None = field(repr=False)
    offset_ms: float = 0.0
    beat_origin_ms: float = 0.0
    bpm: float | None = None
    time_signature_numerator: int = 4
    relink_required: bool = False


class ReferenceAudioEvidenceError(ValueError):
    """An error safe to include in a model tool result."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _dbfs(amplitude: float | np.ndarray) -> float | np.ndarray:
    return 20.0 * np.log10(np.maximum(amplitude, 10.0 ** (_FLOOR_DBFS / 20.0)))


def _anchor(source: ReferenceAudioEvidenceSource, project_ms: float) -> dict:
    anchor = {
        "project_ms": round(project_ms, 3),
        "reference_ms": round(project_ms - source.offset_ms, 3),
    }
    if (
        source.bpm is not None and math.isfinite(source.bpm) and source.bpm > 0.0
        and source.time_signature_numerator > 0
        and math.isfinite(source.beat_origin_ms)
    ):
        pulse_ms = 60_000 / source.bpm
        bar_ms = pulse_ms * source.time_signature_numerator
        grid_beat_offset = (project_ms - source.beat_origin_ms) / pulse_ms
        project_bar_offset = project_ms / bar_ms
        if math.isfinite(pulse_ms) and math.isfinite(grid_beat_offset):
            anchor["grid_beat_offset"] = round(grid_beat_offset, 3)
        if math.isfinite(project_bar_offset) and math.isfinite(bar_ms):
            anchor["project_bar"] = math.floor(project_bar_offset) + 1
    return anchor


def _waveform(samples: np.ndarray, power: np.ndarray, frame_ms: float, count: int) -> dict:
    # Integer frame boundaries tile the decoded samples without gaps or padding.
    boundaries = np.arange(count + 1, dtype=np.int64) * len(samples) // count
    starts, sizes = boundaries[:-1], np.diff(boundaries)
    lo = np.minimum.reduceat(samples.min(axis=1), starts)
    hi = np.maximum.reduceat(samples.max(axis=1), starts)
    rms = np.sqrt(np.add.reduceat(power, starts) / sizes)
    return {
        "columns": ["min_amplitude", "max_amplitude", "rms_dbfs"],
        "amplitude_full_scale": 1.0,
        "bin_duration_ms": round(len(samples) * frame_ms / count, 6),
        "bins": [[round(float(low), 4), round(float(high), 4), round(float(level), 2)]
                 for low, high, level in zip(lo, hi, _dbfs(rms))],
    }


def _measure_dynamics(
    samples: np.ndarray, power: np.ndarray, frames_per_window: int,
) -> tuple[dict, np.ndarray]:
    starts = np.arange(0, len(samples), frames_per_window)
    frame_sizes = np.minimum(frames_per_window, len(samples) - starts)
    window_rms = np.sqrt(np.add.reduceat(power, starts) / frame_sizes)
    window_dbfs = _dbfs(window_rms)
    silence = window_dbfs < _SILENCE_DBFS
    active_levels = window_dbfs[~silence]
    active_range_db = None
    if active_levels.size >= 2:
        quiet, loud = np.percentile(active_levels, [10, 90])
        active_range_db = round(float(loud - quiet), 2)
    magnitudes = np.abs(samples)
    return {
        "peak_dbfs": round(float(_dbfs(np.max(magnitudes))), 2),
        "rms_dbfs": round(float(_dbfs(np.sqrt(power.mean()))), 2),
        "below_threshold_time_ratio": round(float(frame_sizes[silence].sum() / len(samples)), 4),
        "threshold_dbfs": _SILENCE_DBFS,
        "active_p90_minus_p10_db": active_range_db,
        "at_full_scale_sample_ratio": round(float(np.count_nonzero(magnitudes >= 1) / samples.size), 6),
    }, window_dbfs


def _transient_candidates(
    levels: np.ndarray, source: ReferenceAudioEvidenceSource, start_ms: float, hop_ms: float,
) -> list[dict]:
    # Require new energy in the window. The first window has no preceding evidence.
    rises = np.diff(levels)
    candidates = np.flatnonzero((rises >= _MIN_ENERGY_RISE_DB) & (levels[1:] >= _SILENCE_DBFS))
    chosen: list[int] = []
    for index in candidates[np.argsort(-rises[candidates], kind="stable")]:
        if all(abs(int(index) - previous) * hop_ms >= _MIN_TRANSIENT_DISTANCE_MS for previous in chosen):
            chosen.append(int(index))
            if len(chosen) == _MAX_TRANSIENTS:
                break
    return [
        {
            **_anchor(source, start_ms + (index + 1) * hop_ms),
            "rise_db": round(float(rises[index]), 2),
            "rms_dbfs": round(float(levels[index + 1]), 2),
        }
        for index in sorted(chosen)
    ]


def _spectral_bands(samples: np.ndarray, sample_rate: int) -> list[dict]:
    window_size = max(1, round(sample_rate * _SPECTRUM_FRAME_MS / 1000))
    complete_windows = len(samples) // window_size
    if complete_windows:
        samples = samples[:complete_windows * window_size]
    else:
        window_size = len(samples)
    if window_size < max(4, sample_rate // 100):
        return []

    # Average power across channels rather than mixing the signals. An
    # out-of-phase stereo recording must not disappear in the evidence.
    window = np.hanning(window_size)
    blocks = samples.reshape(-1, window_size, samples.shape[1])
    power = np.zeros(window_size // 2 + 1, dtype=np.float64)
    for start in range(0, len(blocks), 16):
        magnitudes = np.abs(np.fft.rfft(blocks[start:start + 16] * window[None, :, None], axis=1))
        power += np.square(magnitudes).sum(axis=(0, 2), dtype=np.float64)

    frequencies = np.fft.rfftfreq(window_size, 1.0 / sample_rate)
    edges = np.searchsorted(frequencies, _SPECTRAL_BAND_EDGES_HZ)
    total = float(power[edges[0]:edges[-1]].sum())
    if total <= 0.0:
        return []
    return [
        {
            "low_hz": low, "high_hz": min(high, sample_rate / 2),
            "energy_share": round(float(power[start:end].sum() / total), 4),
        }
        for low, high, start, end in zip(
            _SPECTRAL_BAND_EDGES_HZ, _SPECTRAL_BAND_EDGES_HZ[1:], edges, edges[1:]
        )
        if start < end
    ]


def inspect_reference_audio(
    source: ReferenceAudioEvidenceSource,
    *,
    start_ms: float,
    end_ms: float,
    bins: int = MAX_WAVEFORM_BINS,
) -> dict:
    """Decode only the intersecting part of a selected project-time window, off the GUI thread."""

    if (
        not math.isfinite(start_ms) or not math.isfinite(end_ms) or end_ms <= start_ms
        or not math.isfinite(source.offset_ms)
        or type(bins) is not int or not 1 <= bins <= MAX_WAVEFORM_BINS
    ):
        raise ReferenceAudioEvidenceError("reference_audio_invalid_range")
    if source.relink_required:
        raise ReferenceAudioEvidenceError("reference_audio_relink_required")
    if not source.path:
        raise ReferenceAudioEvidenceError("reference_audio_not_linked")
    path = Path(source.path)
    if path.suffix.lower() not in SUPPORTED_REFERENCE_AUDIO_SUFFIXES:
        raise ReferenceAudioEvidenceError("reference_audio_unsupported")
    try:
        if not path.is_file():
            raise ReferenceAudioEvidenceError("reference_audio_missing")
        audio_format = validate_reference_audio_file(path)
    except (OSError, ReferenceAudioFormatError):
        raise ReferenceAudioEvidenceError("reference_audio_unreadable") from None

    try:
        import soundfile
    except (ImportError, OSError):
        raise ReferenceAudioEvidenceError("reference_audio_decoder_unavailable") from None

    try:
        with soundfile.SoundFile(path) as clip:
            sample_rate, channels, frame_count = clip.samplerate, clip.channels, clip.frames
            if not 1 <= channels <= _MAX_CHANNELS or not 1 <= sample_rate <= _MAX_SAMPLE_RATE:
                raise ReferenceAudioEvidenceError("reference_audio_unsupported")
            frame_ms = 1000.0 / sample_rate
            duration_ms = frame_count * frame_ms
            start_reference_ms = max(0.0, start_ms - source.offset_ms)
            end_reference_ms = min(duration_ms, end_ms - source.offset_ms)
            if start_reference_ms >= end_reference_ms:
                raise ReferenceAudioEvidenceError("reference_audio_outside_range")
            first_frame = math.ceil(start_reference_ms * sample_rate / 1000)
            last_frame = min(frame_count, math.ceil(end_reference_ms * sample_rate / 1000))
            maximum_frames = min(round(MAX_REFERENCE_WINDOW_MS / frame_ms), _MAX_INTERLEAVED_SAMPLES // channels)
            frames_to_read = min(last_frame - first_frame, maximum_frames)
            if frames_to_read <= 0:
                raise ReferenceAudioEvidenceError("reference_audio_outside_range")
            clip.seek(first_frame)
            samples = clip.read(frames_to_read, dtype="float32", always_2d=True)
    except (OSError, RuntimeError):
        raise ReferenceAudioEvidenceError("reference_audio_unreadable") from None

    if not len(samples) or not np.isfinite(samples).all():
        raise ReferenceAudioEvidenceError("reference_audio_unreadable")
    # Float WAV can exceed full scale. Accumulate in double precision to keep
    # its actual sample values and avoid overflow while squaring them.
    power = np.einsum("ij,ij->i", samples, samples, dtype=np.float64) / channels
    start_reference_ms = first_frame * 1000.0 / sample_rate
    start_project_ms = source.offset_ms + start_reference_ms
    end_reference_ms = (first_frame + len(samples)) * 1000.0 / sample_rate
    end_project_ms = source.offset_ms + end_reference_ms
    waveform = _waveform(samples, power, frame_ms, min(bins, len(samples)))
    frames_per_window = max(1, round(_DYNAMICS_FRAME_MS / frame_ms))
    hop_ms = frames_per_window * frame_ms
    dynamics, levels = _measure_dynamics(samples, power, frames_per_window)
    return {
        "format": audio_format,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "duration_ms": round(duration_ms, 3),
        "alignment": {
            "reference_zero_project_ms": round(source.offset_ms, 3),
            "start": _anchor(source, start_project_ms),
            "end": _anchor(source, end_project_ms),
        },
        "requested_project_range_ms": [round(start_ms, 3), round(end_ms, 3)],
        "analyzed_project_range_ms": [round(start_project_ms, 3), round(end_project_ms, 3)],
        "analyzed_reference_range_ms": [round(start_reference_ms, 3), round(end_reference_ms, 3)],
        "range_limited": (
            len(samples) < last_frame - first_frame
            or start_ms < source.offset_ms
            or end_ms > source.offset_ms + duration_ms
        ),
        "waveform": {
            "start_project_ms": round(start_project_ms, 3),
            "first_reference_frame": first_frame,
            "frame_count": len(samples),
            **waveform,
        },
        "dynamics": dynamics,
        "spectral_bands": _spectral_bands(samples, sample_rate),
        "transient_candidates": _transient_candidates(levels, source, start_project_ms, hop_ms),
    }
