"""Fail-closed recovery for narrowly malformed Standard MIDI files."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import mido


_HEADER_CHUNK = b"MThd"
_TRACK_CHUNK = b"MTrk"
_MAX_COMPATIBILITY_BYTES = 64 * 1024 * 1024
_DATA_BYTE_MAX = 0x7F
_CHANNEL_DATA_LENGTH = {
    0x80: 2,
    0x90: 2,
    0xA0: 2,
    0xB0: 2,
    0xC0: 1,
    0xD0: 1,
    0xE0: 2,
}
_EVENT_NAMES = {
    0x80: "note_off",
    0x90: "note_on",
    0xA0: "polytouch",
    0xB0: "control_change",
    0xC0: "program_change",
    0xD0: "aftertouch",
    0xE0: "pitchwheel",
}


@dataclass(frozen=True, slots=True)
class MidiCompatibilityRepair:
    """One bounded repair applied to an in-memory copy of a source MIDI."""

    kind: str
    count: int
    track_indexes: tuple[int, ...]
    channels: tuple[int, ...]
    event_types: tuple[str, ...]
    original_max: int
    replacement: int = _DATA_BYTE_MAX


class MidiCompatibilityError(ValueError):
    """The file resembles the known defect but is unsafe to repair."""


def _read_vlq(payload: bytearray, position: int, end: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if position >= end:
            raise MidiCompatibilityError("truncated MIDI variable-length value")
        current = payload[position]
        position += 1
        value = (value << 7) | (current & _DATA_BYTE_MAX)
        if current <= _DATA_BYTE_MAX:
            return value, position
    raise MidiCompatibilityError("MIDI variable-length value exceeds four bytes")


def _repair_track(
    payload: bytearray,
    start: int,
    end: int,
    track_index: int,
) -> list[tuple[int, int, str, int]]:
    position = start
    running_status: int | None = None
    repaired: list[tuple[int, int, str, int]] = []
    while position < end:
        _delta, position = _read_vlq(payload, position, end)
        if position >= end:
            raise MidiCompatibilityError("truncated MIDI event")
        first = payload[position]
        explicit_status = first >= 0x80
        if explicit_status:
            status = first
            position += 1
            if 0x80 <= status <= 0xEF:
                running_status = status
            elif status < 0xF8:
                running_status = None
        else:
            if running_status is None:
                raise MidiCompatibilityError("MIDI running status has no owner")
            status = running_status

        if status == 0xFF:
            if position >= end:
                raise MidiCompatibilityError("truncated MIDI meta event")
            position += 1
            size, position = _read_vlq(payload, position, end)
            position += size
        elif status in (0xF0, 0xF7):
            size, position = _read_vlq(payload, position, end)
            position += size
        elif 0x80 <= status <= 0xEF:
            event_type = status & 0xF0
            data_length = _CHANNEL_DATA_LENGTH[event_type]
            for data_index in range(data_length):
                if position >= end:
                    raise MidiCompatibilityError("truncated MIDI channel event")
                value = payload[position]
                if value > _DATA_BYTE_MAX:
                    # A status-like byte in the first data position is
                    # indistinguishable from a missing-data structural defect.
                    # Only the terminal value/velocity byte is safely bounded.
                    if data_index != data_length - 1 or data_length < 2:
                        raise MidiCompatibilityError(
                            "unsafe out-of-range MIDI data position"
                        )
                    payload[position] = _DATA_BYTE_MAX
                    repaired.append((
                        track_index,
                        status & 0x0F,
                        _EVENT_NAMES[event_type],
                        value,
                    ))
                position += 1
        else:
            raise MidiCompatibilityError(
                f"unsupported MIDI status 0x{status:02X}"
            )
        if position > end:
            raise MidiCompatibilityError("MIDI event exceeds its track chunk")
    return repaired


def _repair_out_of_range_data_bytes(
    source: bytes,
) -> tuple[bytes, tuple[MidiCompatibilityRepair, ...]]:
    payload = bytearray(source)
    if len(payload) < 14 or payload[:4] != _HEADER_CHUNK:
        raise MidiCompatibilityError("not a Standard MIDI header")
    header_length = int.from_bytes(payload[4:8], "big")
    if header_length < 6 or 8 + header_length > len(payload):
        raise MidiCompatibilityError("invalid Standard MIDI header length")
    track_count = int.from_bytes(payload[10:12], "big")
    position = 8 + header_length
    repaired: list[tuple[int, int, str, int]] = []
    for track_index in range(track_count):
        if (
            position + 8 > len(payload)
            or payload[position:position + 4] != _TRACK_CHUNK
        ):
            raise MidiCompatibilityError("missing Standard MIDI track chunk")
        track_length = int.from_bytes(payload[position + 4:position + 8], "big")
        track_start = position + 8
        track_end = track_start + track_length
        if track_end > len(payload):
            raise MidiCompatibilityError("truncated Standard MIDI track chunk")
        repaired.extend(
            _repair_track(payload, track_start, track_end, track_index)
        )
        position = track_end
    if not repaired:
        raise MidiCompatibilityError("no safely repairable MIDI data bytes found")
    report = MidiCompatibilityRepair(
        kind="clamped_channel_data",
        count=len(repaired),
        track_indexes=tuple(sorted({item[0] for item in repaired})),
        channels=tuple(sorted({item[1] for item in repaired})),
        event_types=tuple(sorted({item[2] for item in repaired})),
        original_max=max(item[3] for item in repaired),
    )
    return bytes(payload), (report,)


def load_midi_file(
    midi_path: str | Path,
    *,
    allow_compatibility_repairs: bool = False,
) -> tuple[mido.MidiFile, tuple[MidiCompatibilityRepair, ...]]:
    """Load strictly, then retry only a proven bounded data-byte repair."""

    try:
        return mido.MidiFile(midi_path), ()
    except OSError as strict_error:
        if not allow_compatibility_repairs:
            raise
        if "data byte must be in range 0..127" not in str(strict_error):
            raise
        path = Path(midi_path)
        if path.stat().st_size > _MAX_COMPATIBILITY_BYTES:
            raise MidiCompatibilityError(
                "MIDI compatibility repair is limited to 64 MiB"
            ) from strict_error
        try:
            repaired_bytes, repairs = _repair_out_of_range_data_bytes(
                path.read_bytes()
            )
            midi = mido.MidiFile(file=BytesIO(repaired_bytes))
        except Exception as repair_error:
            raise strict_error from repair_error
        return midi, repairs


__all__ = [
    "MidiCompatibilityError",
    "MidiCompatibilityRepair",
    "load_midi_file",
]
