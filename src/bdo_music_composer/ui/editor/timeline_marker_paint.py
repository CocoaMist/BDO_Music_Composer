"""Layout, paint damage, and hit regions for arrangement timeline markers."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRegion


@dataclass(frozen=True, slots=True)
class _MarkerPaint:
    line: QRectF
    line_damage: QRect
    pill: QRectF
    pill_damage: QRect
    label_rect: QRectF
    delete_rect: QRectF
    label: str


class TimelineMarkerLayer:
    """Reuse the visible geometry and draw only markers touching the damage."""

    def __init__(self) -> None:
        self.label_regions: list[tuple[QRectF, dict[str, object]]] = []
        self.delete_regions: list[tuple[QRectF, dict[str, object]]] = []
        self._paint_key: tuple[object, ...] | None = None
        self._paint_regions: list[_MarkerPaint] = []

    def invalidate(self) -> None:
        self._paint_key = None

    def paint(
        self,
        painter: QPainter,
        damage: QRegion,
        *,
        ruler_top: float,
        grid: QRectF,
        visible_start: float,
        visible_duration: float,
        markers: Sequence[dict[str, object]],
        marker_times: Sequence[float],
    ) -> None:
        key = (
            ruler_top, grid, visible_start, visible_duration,
            painter.font(), painter.device().devicePixelRatioF(),
        )
        if key != self._paint_key:
            self._refresh_geometry(
                painter, ruler_top, grid, visible_start, visible_duration,
                markers, marker_times,
            )
            self._paint_key = key
        if not damage.intersects(QRectF(
            grid.left(), ruler_top + 2.0, grid.width() + 1.0,
            grid.height() + grid.top() - ruler_top,
        ).toAlignedRect()):
            return

        line_color = QColor(229, 174, 69, 150)
        pill_color = QColor(48, 40, 25, 246)
        outline = QPen(QColor("#d9a53f"), 1)
        label_color = QColor("#f1d9a3")
        delete_color = QColor("#caa967")
        for marker in self._paint_regions:
            if damage.intersects(marker.line_damage):
                painter.fillRect(marker.line, line_color)
            if damage.intersects(marker.pill_damage):
                painter.setBrush(pill_color)
                painter.setPen(outline)
                painter.drawRect(marker.pill)
                painter.setPen(label_color)
                painter.drawText(marker.label_rect, Qt.AlignVCenter, marker.label)
                painter.setPen(delete_color)
                painter.drawText(marker.delete_rect, Qt.AlignCenter, "×")

    def _refresh_geometry(
        self,
        painter: QPainter,
        ruler_top: float,
        grid: QRectF,
        visible_start: float,
        visible_duration: float,
        markers: Sequence[dict[str, object]],
        marker_times: Sequence[float],
    ) -> None:
        self.label_regions.clear()
        self.delete_regions.clear()
        self._paint_regions.clear()
        first = bisect_left(marker_times, visible_start)
        last = bisect_right(marker_times, visible_start + visible_duration)
        metrics = painter.fontMetrics()
        grid_left = grid.left()
        grid_right = grid.right()
        grid_top = grid.top()
        grid_width = grid.width()
        grid_height = grid.height()
        for marker in markers[first:last]:
            time_ms = float(marker["time_ms"])
            x = grid_left + ((time_ms - visible_start) / visible_duration) * grid_width
            line = QRectF(x, grid_top, 1.0, grid_height)
            label = str(marker["label"])
            width = min(184.0, max(64.0, metrics.horizontalAdvance(label) + 30.0))
            label_x = max(grid_left + 3.0, min(x + 3.0, grid_right - width - 3.0))
            pill = QRectF(label_x, ruler_top + 3.0, width, 20.0)
            delete_rect = QRectF(pill.right() - 21.0, pill.top(), 21.0, pill.height())
            self._paint_regions.append(_MarkerPaint(
                line=line,
                line_damage=line.toAlignedRect(),
                pill=pill,
                pill_damage=pill.adjusted(-1.0, -1.0, 1.0, 1.0).toAlignedRect(),
                label_rect=pill.adjusted(7.0, 0.0, -22.0, 0.0),
                delete_rect=delete_rect,
                label=label,
            ))
            self.label_regions.append((pill, marker))
            self.delete_regions.append((delete_rect, marker))
