"""Clip geometry, selection markers, and metadata for the timeline."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fonts_qt import canvas_caption_font


CLIP_REGION_INSET = 1.0
CLIP_BODY_INSET = 2.0
CLIP_LANE_INSET = CLIP_REGION_INSET + CLIP_BODY_INSET
CLIP_TITLE_HEIGHT = 20
CLIP_TITLE_MIN_WIDTH = 38.0
CLIP_TITLE_MIN_HEIGHT = 34.0
CLIP_CORNER_RADIUS = 4.0


def clip_identity_color(clip: ArrangementClipState, track: TrackState) -> QColor:
    color = QColor(clip.color)
    if not color.isValid():
        color = QColor(track.color)
    return color if color.isValid() else QColor(hig.SECONDARY_TEXT)


def clip_display_rect(clip: ArrangementClipState, region: QRectF, start: float, duration: float) -> QRectF:
    scale = region.width() / duration
    return QRectF(
        region.left() + (clip.start_ms - start) * scale,
        region.top() + CLIP_BODY_INSET,
        max(8.0, (clip.end_ms - clip.start_ms) * scale),
        region.height() - 2 * CLIP_BODY_INSET,
    ).intersected(region)


def clip_end_handle_visible(clip: ArrangementClipState, region: QRectF, start: float, duration: float) -> bool:
    scale = region.width() / duration
    end = (clip.start_ms - start) * scale + max(8.0, (clip.end_ms - clip.start_ms) * scale)
    return 0.0 < end <= region.width() + 1e-6


def paint_clip_selection(
    painter: QPainter, rect: QRectF, identity: QColor, *, focused: bool, has_error: bool, can_trim: bool,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Lighten even dark custom clip colors so selection reads against the fill.
    identity = QColor(hig.ERROR_TEXT) if has_error else identity
    base = QColor(hig.SELECTION_TEXT)
    edge = QColor.fromRgbF(
        0.68 * identity.redF() + 0.32 * base.redF(),
        0.68 * identity.greenF() + 0.32 * base.greenF(),
        0.68 * identity.blueF() + 0.32 * base.blueF(),
        0.94 if focused else 0.64,
    )
    pen_width = 1.5 if focused else 1.0
    inset = 1.5 if has_error else 0.75
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(edge, pen_width))
    painter.drawRoundedRect(
        rect.adjusted(inset, inset, -inset, -inset), CLIP_CORNER_RADIUS, CLIP_CORNER_RADIUS,
    )
    if can_trim and rect.width() >= 24:
        painter.setPen(QPen(edge, 1.1, Qt.SolidLine, Qt.RoundCap))
        y = rect.center().y()
        painter.drawLines(
            [QLineF(x, y - 4, x, y + 4) for x in (rect.right() - 7.0, rect.right() - 4.0)],
        )
    painter.restore()


def paint_track_clip_metadata(
    painter: QPainter, track: TrackState, clip: ArrangementClipState,
    clip_rect: QRectF, *, active: bool, selected: bool,
) -> None:
    """Place the name and any non-default velocity on the clip's title strip."""

    if clip_rect.height() < CLIP_TITLE_MIN_HEIGHT or clip_rect.width() < CLIP_TITLE_MIN_WIDTH:
        return
    painter.save()
    painter.setFont(canvas_caption_font(painter.font()))
    name = clip.display_name.strip() or track.display_name.strip() or tr("音块")
    percent = int(clip.velocity_percent)
    text = name if percent == 100 else trf("{name} · {percent}%", name=name, percent=percent)
    available = int(clip_rect.width() - 16.0)
    text = painter.fontMetrics().elidedText(text, Qt.ElideRight, available)
    text_rect = QRectF(clip_rect.left() + 8, clip_rect.top() + 2, available, CLIP_TITLE_HEIGHT - 2)
    text_color = hig.SELECTION_TEXT if selected else (hig.TEXT if active else hig.DISABLED_TEXT)
    painter.setPen(QColor(text_color))
    painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
    painter.restore()


__all__ = ["paint_clip_selection", "paint_track_clip_metadata"]
