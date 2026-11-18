"""Search order for PCM files referenced by a local sample map."""

from __future__ import annotations

from pathlib import Path


def sample_search_roots(map_path: Path, audio_root: Path | None) -> tuple[Path, ...]:
    configured = (audio_root / "乐器_WAV", audio_root) if audio_root is not None else ()
    return configured + (map_path.parent, Path.cwd())


def mapped_sample_paths(raw_path: Path, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    if raw_path.is_absolute() or not raw_path.parts:
        return (raw_path,)
    return tuple(root / raw_path for root in roots)
