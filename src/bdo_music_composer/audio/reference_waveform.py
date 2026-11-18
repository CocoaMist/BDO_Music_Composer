"""Build a reference waveform on the source sample clock with bounded reads."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import math
from pathlib import Path
import wave

import numpy as np

from .pcm_wav import pcm_bytes_to_float32


_MAX_READ_SAMPLES = 131_072
_MAX_WAVEFORM_BUCKETS = 36_000
_WAVEFORM_BUCKETS_PER_SECOND = 20


@dataclass(slots=True)
class ReferenceWaveform:
    buckets: list[tuple[float, float, float]]
    starts: list[float]
    content_duration_ms: float | None = None


class TimestampedWaveform:
    """Bounded envelope for Qt buffers whose decoder supplies timestamps."""

    def __init__(self) -> None:
        self._width_ms = 1000.0 / _WAVEFORM_BUCKETS_PER_SECOND
        self._peaks = np.zeros(_MAX_WAVEFORM_BUCKETS, dtype=np.float32)
        self._end_ms = 0.0

    def append(
        self, amplitudes: np.ndarray, sample_rate: int, start_ms: float,
    ) -> None:
        frame_count = len(amplitudes)
        if frame_count == 0:
            return
        if start_ms < 0.0:
            start_ms = self._end_ms
        frame_ms = 1000.0 / sample_rate
        self._end_ms = max(self._end_ms, start_ms + frame_count * frame_ms)
        while self._end_ms > self._width_ms * _MAX_WAVEFORM_BUCKETS:
            midpoint = _MAX_WAVEFORM_BUCKETS // 2
            self._peaks[:midpoint] = np.maximum(self._peaks[::2], self._peaks[1::2])
            self._peaks[midpoint:] = 0.0
            self._width_ms *= 2.0

        first = int(start_ms / self._width_ms)
        last = int((start_ms + (frame_count - 1) * frame_ms) / self._width_ms)
        if first == last:
            peak = np.fmax.reduce(amplitudes, axis=None, initial=0.0)
            self._peaks[first] = max(self._peaks[first], peak)
            return

        # Split at envelope boundaries rather than decoder buffer boundaries.
        boundaries = np.arange(first + 1, last + 1) * self._width_ms
        offsets = np.ceil((boundaries - start_ms) / frame_ms).astype(np.intp)
        offsets = np.unique(np.clip(np.concatenate(([0], offsets)), 0, frame_count - 1))
        indices = ((start_ms + offsets * frame_ms) / self._width_ms).astype(np.intp)
        peaks = np.fmax.reduce(np.fmax.reduceat(amplitudes, offsets, axis=0), axis=1)
        # An unusually low sample rate can jump past one or more bins.
        np.fmax.at(self._peaks, indices, peaks)

    def finish(self) -> ReferenceWaveform | None:
        if self._end_ms <= 0.0:
            return None
        count = min(len(self._peaks), math.ceil(self._end_ms / self._width_ms))
        starts = [index * self._width_ms for index in range(count)]
        return ReferenceWaveform(
            [
                (start, min(start + self._width_ms, self._end_ms), min(1.0, float(peak)))
                for start, peak in zip(starts, self._peaks)
            ],
            starts,
        )


def _source_blocks(
    read: Callable[[int], np.ndarray],
    channels: int,
    cancelled: Callable[[], bool],
) -> Iterator[np.ndarray]:
    block_frames = max(1, _MAX_READ_SAMPLES // channels)
    while not cancelled():
        block = read(block_frames)
        if not block.size:
            return
        yield block


def _collect_waveform(
    read: Callable[[int], np.ndarray],
    rate: int,
    channels: int,
    expected_frames: int,
    cancelled: Callable[[], bool],
) -> ReferenceWaveform | None:
    frames_per_bucket = max(
        1,
        round(rate / _WAVEFORM_BUCKETS_PER_SECOND),
        (expected_frames + _MAX_WAVEFORM_BUCKETS - 1) // _MAX_WAVEFORM_BUCKETS,
    )
    peaks: list[float] = []
    trailing_frames = 0
    trailing_peak = 0.0
    for block in _source_blocks(read, channels, cancelled):
        np.abs(block, out=block)
        if trailing_frames:
            leading_frames = min(len(block), frames_per_bucket - trailing_frames)
            leading_peak = np.fmax.reduce(block[:leading_frames], axis=None, initial=0.0)
            trailing_peak = max(trailing_peak, float(leading_peak))
            trailing_frames += leading_frames
            if trailing_frames < frames_per_bucket:
                continue
            peaks.append(trailing_peak)
            trailing_frames = 0
            trailing_peak = 0.0
            block = block[leading_frames:]

        buckets_in_block, trailing_frames = divmod(len(block), frames_per_bucket)
        end = buckets_in_block * frames_per_bucket
        if buckets_in_block:
            windows = block[:end].reshape(buckets_in_block, frames_per_bucket, channels)
            block_peaks = np.fmax.reduce(windows, axis=(1, 2), initial=0.0)
            peaks.extend(block_peaks.tolist())
        if trailing_frames:
            trailing_peak = float(np.fmax.reduce(block[end:], axis=None, initial=0.0))

        # A compressed stream can report an underestimate of its decoded length.
        # Merge complete adjacent buckets before the envelope grows without bound.
        if len(peaks) + bool(trailing_frames) > _MAX_WAVEFORM_BUCKETS:
            if len(peaks) % 2:
                trailing_peak = max(peaks.pop(), trailing_peak)
                trailing_frames += frames_per_bucket
            peaks = [max(left, right) for left, right in zip(peaks[::2], peaks[1::2])]
            frames_per_bucket *= 2

    if cancelled() or (not peaks and not trailing_frames):
        return None
    total_frames = len(peaks) * frames_per_bucket + trailing_frames
    if trailing_frames:
        peaks.append(trailing_peak)

    bucket_ms = frames_per_bucket * 1000.0 / rate
    end_ms = total_frames * 1000.0 / rate
    starts = [index * bucket_ms for index in range(len(peaks))]
    return ReferenceWaveform(
        [
            (start, min((index + 1) * bucket_ms, end_ms), min(1.0, peak))
            for index, (start, peak) in enumerate(zip(starts, peaks))
        ],
        starts,
        end_ms,
    )


def _pcm_waveform(path: Path, cancelled: Callable[[], bool]) -> ReferenceWaveform | None:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()

        def read(frames: int) -> np.ndarray:
            payload = source.readframes(frames)
            if width == 1:
                samples = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)
                samples -= 128.0
                samples *= 1.0 / 128.0
                return samples.reshape(-1, channels)
            if width == 4:
                samples = np.frombuffer(payload, dtype="<i4").astype(np.float32)
                samples *= 1.0 / 2147483648.0
                return samples.reshape(-1, channels)
            return pcm_bytes_to_float32(payload, width, channels)

        return _collect_waveform(
            read, source.getframerate(), channels, source.getnframes(), cancelled,
        )


def decode_reference_waveform(
    path: Path, cancelled: Callable[[], bool],
) -> ReferenceWaveform | None:
    if path.suffix.lower() == ".wav":
        try:
            return _pcm_waveform(path, cancelled)
        except (EOFError, OSError, ValueError, wave.Error):
            if cancelled():
                return None

    # The full application already ships libsndfile for audio analysis. The
    # minimal desktop install can hand other encodings to its Qt backend.
    import soundfile

    with soundfile.SoundFile(str(path)) as source:
        return _collect_waveform(
            lambda frames: source.read(frames, dtype="float32", always_2d=True),
            source.samplerate,
            source.channels,
            source.frames,
            cancelled,
        )
