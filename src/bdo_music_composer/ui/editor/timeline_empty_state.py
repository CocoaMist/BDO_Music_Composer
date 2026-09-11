"""Small painter for the timeline's persistent empty-score guidance."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen


def paint_empty_score_guidance(
    painter: QPainter,
    grid_rect: QRectF,
    translate: Callable[[str], str],
) -> None:
    hint_top = max(
        grid_rect.top() + 16.0,
        min(grid_rect.center().y() - 37.0, grid_rect.bottom() - 90.0),
    )
    hint_rect = QRectF(
        grid_rect.left() + 24.0,
        hint_top,
        max(180.0, grid_rect.width() - 48.0),
        74.0,
    )
    painter.save()
    painter.setBrush(QColor(20, 18, 16, 210))
    painter.setPen(QPen(QColor("#6f634d"), 1))
    painter.drawRoundedRect(hint_rect, 8.0, 8.0)
    painter.setPen(QColor("#f0d887"))
    painter.drawText(
        hint_rect.adjusted(16.0, 8.0, -16.0, -34.0),
        Qt.AlignCenter,
        translate("双击轨道，打开音符编辑器写下第一个音符"),
    )
    painter.setPen(QColor("#aaa39a"))
    painter.drawText(
        hint_rect.adjusted(16.0, 36.0, -16.0, -8.0),
        Qt.AlignCenter,
        translate("也可以从“项目”菜单导入 MIDI"),
    )
    painter.restore()


__all__ = ["paint_empty_score_guidance"]
