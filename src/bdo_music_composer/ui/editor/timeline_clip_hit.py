"""Qt-bound Clip hit-testing and marquee selection geometry.

The hit index and selection rules stay independently testable. Callers supply
the painted hit regions and the tool or selection state for each query.
"""

from __future__ import annotations

from collections.abc import Sequence, Set

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QRegion

from bdo_music_composer.editor.editor_models import TrackState


HitRegion = tuple[QRectF, str, object]
"""One resolved interactive region: geometry, action tag, and target item."""


def marquee_rect(
    press_pos: QPointF | None,
    current_pos: QPointF,
    grid_rect: QRectF,
) -> QRectF:
    """Return the normalized marquee rectangle, clipped to the grid area."""

    if press_pos is None:
        return QRectF()
    return QRectF(press_pos, current_pos).normalized().intersected(grid_rect)


def marquee_damage(previous: QRectF, current: QRectF) -> QRegion:
    """Keep both antialiased outlines and omit their common interior fill."""

    if previous == current:
        return QRegion()
    if previous.isEmpty():
        return QRegion(current.toAlignedRect().adjusted(-2, -2, 2, 2))
    if current.isEmpty():
        return QRegion(previous.toAlignedRect().adjusted(-2, -2, 2, 2))
    old = previous.toAlignedRect()
    new = current.toAlignedRect()
    damage = QRegion(old.adjusted(-2, -2, 2, 2)) | QRegion(new.adjusted(-2, -2, 2, 2))
    old_interior = old.adjusted(2, 2, -2, -2)
    new_interior = new.adjusted(2, 2, -2, -2)
    if old_interior.isEmpty() or new_interior.isEmpty():
        return damage
    return damage - QRegion(old_interior.intersected(new_interior))


def clip_keys_intersecting(
    hit_regions: Sequence[HitRegion],
    rect: QRectF,
) -> set[tuple[int, str]]:
    """Return every Clip body region intersecting a marquee rectangle."""

    if rect.isEmpty():
        return set()
    return {
        (int(item.track_id), action.split("|", 1)[1])
        for region, action, item in hit_regions
        if (
            action.startswith("clip_body|")
            and isinstance(item, TrackState)
            and region.intersects(rect)
        )
    }


def clip_action_at(
    hit_regions: Sequence[HitRegion],
    position: QPointF,
    *,
    arrangement_tool: str,
    selected_clip_keys: Set[tuple[int, str]] | None = None,
) -> tuple[TrackState, str, str] | None:
    """Resolve one Clip gesture, with visible handles above the body."""

    selected = selected_clip_keys if selected_clip_keys is not None else frozenset()
    for rect, action, item in reversed(hit_regions):
        action_kind, _separator, clip_id = action.partition("|")
        if (
            action_kind in {"clip_body", "clip_start", "clip_end"}
            and isinstance(item, TrackState)
            and rect.contains(position)
        ):
            key = (int(item.track_id), str(clip_id))
            if (
                action_kind in {"clip_start", "clip_end"}
                and (
                    arrangement_tool != "select"
                    or key not in selected
                )
            ):
                action_kind = "clip_body"
            return item, str(clip_id), action_kind
    return None


class TimelineHitIndex:
    """Reuse the visible paint geometry for pointer and selection queries."""

    _STRIP_HEIGHT = 64.0

    def __init__(self, regions: Sequence[HitRegion] = (), *, defer: bool = False) -> None:
        self._hit_strips: dict[int, list[HitRegion]] = {}
        self._clip_strips: dict[int, list[tuple[tuple[int, str], QRectF]]] = {}
        self._bodies: dict[tuple[int, str], list[tuple[int, QRectF]]] = {}
        self._pending_regions = regions
        if not defer:
            self._prepare()

    def _prepare(self) -> None:
        regions, self._pending_regions = self._pending_regions, ()
        for order, region in enumerate(regions):
            rect, action, item = region
            clip = None
            if action.startswith("clip_body|") and isinstance(item, TrackState):
                key = int(item.track_id), action.split("|", 1)[1]
                clip = key, rect
                self._bodies.setdefault(key, []).append((order, rect))
            for strip in self._strips(rect):
                self._hit_strips.setdefault(strip, []).append(region)
                if clip is not None:
                    self._clip_strips.setdefault(strip, []).append(clip)

    @classmethod
    def _strips(cls, rect: QRectF) -> range:
        return range(
            int(rect.top() // cls._STRIP_HEIGHT),
            int(rect.bottom() // cls._STRIP_HEIGHT) + 1,
        )

    def at(self, point: QPointF) -> tuple[HitRegion, ...]:
        if self._pending_regions:
            self._prepare()
        strip = int(point.y() // self._STRIP_HEIGHT)
        return tuple(region for region in self._hit_strips.get(strip, ()) if region[0].contains(point))

    def clip_keys_intersecting(self, rect: QRectF) -> set[tuple[int, str]]:
        if rect.isEmpty():
            return set()
        if self._pending_regions:
            self._prepare()
        return {
            key for strip in self._strips(rect)
            for key, body in self._clip_strips.get(strip, ())
            if body.intersects(rect)
        }

    def body_rectangles(self, keys: Set[tuple[int, str]]) -> tuple[QRectF, ...]:
        if keys and self._pending_regions:
            self._prepare()
        bodies = sorted(
            (body for key in keys for body in self._bodies.get(key, ())),
            key=lambda body: body[0],
        )
        return tuple(rect for _order, rect in bodies)


__all__ = [
    "HitRegion",
    "TimelineHitIndex",
    "clip_action_at",
    "clip_keys_intersecting",
    "marquee_damage",
    "marquee_rect",
]
