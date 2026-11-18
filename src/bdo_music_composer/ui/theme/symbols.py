"""Scalable workbench glyphs on a shared 24-unit grid."""

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPixmapCache


class FluentSymbol(str, Enum):
    COMPOSER = "composer"
    HOME = "home"
    HOME_ACTIVE = "home_active"
    GLOBE = "globe"
    GLOBE_ACTIVE = "globe_active"
    OPEN = "open"
    LINK = "link"
    SEND = "send"
    REFRESH = "refresh"
    PROJECT = "project"
    NEW_PROJECT = "new_project"
    IMPORT = "import"
    OPTIMIZE = "optimize"
    INFO = "info"
    SETTINGS = "settings"
    EXPORT = "export"
    FIT = "fit"
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    REPEAT = "repeat"
    REPEAT_ACTIVE = "repeat_active"
    AUTO_TEMPO = "auto_tempo"
    AUTO_TEMPO_ACTIVE = "auto_tempo_active"
    ADD_TRACK = "add_track"
    DELETE = "delete"
    CURVE = "curve"
    MARQUEE = "marquee"
    SELECT = "select"
    RAZOR = "razor"
    MAGNET = "magnet"
    UNDO = "undo"
    REDO = "redo"
    NOTES_PANEL = "notes_panel"
    INSPECTOR = "inspector"
    MORE = "more"
    CHEVRON_RIGHT = "chevron_right"
    CHEVRON_DOWN = "chevron_down"
    CHEVRON_UP = "chevron_up"
    KEYBOARD = "keyboard"
    SPEAKER = "speaker"
    SPEAKER_MUTED = "speaker_muted"
    HEADPHONES = "headphones"
    HEADPHONES_ACTIVE = "headphones_active"
    FEEDBACK = "feedback"
    POPOUT = "popout"
    CLOSE = "close"
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    RESTORE = "restore"


def draw_symbol(symbol: FluentSymbol, color: str, size: int = 16) -> QPixmap:
    """Render without snapping control points to device pixels."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    ink = QColor(color)
    pen = QPen(ink, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    def line(*points: tuple[float, float]) -> None:
        painter.drawPolyline([QPointF(x, y) for x, y in points])

    def box(x: float, y: float, w: float, h: float, radius: float = 2) -> None:
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def circle(x: float, y: float, radius: float) -> None:
        painter.drawEllipse(QPointF(x, y), radius, radius)

    def solid() -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)

    match symbol:
        case FluentSymbol.COMPOSER:
            curve = QPainterPath(QPointF(17, 5.5))
            curve.cubicTo(13.4, 2.5, 8.2, 3.6, 5.5, 7.2)
            curve.cubicTo(2.6, 11.1, 4.2, 16.4, 8, 18.9)
            curve.cubicTo(10.5, 20.6, 13.5, 20.9, 16.2, 19.5)
            painter.drawPath(curve)
            line((16, 14.8), (16, 8.4), (21, 10.2))
            solid()
            painter.drawEllipse(QRectF(11.4, 12.8, 5.6, 4.2))
        case FluentSymbol.HOME:
            line((3, 11), (12, 4), (21, 11))
            line((6, 9), (6, 20), (18, 20), (18, 9))
            line((10, 20), (10, 14), (14, 14), (14, 20))
        case FluentSymbol.HOME_ACTIVE:
            solid()
            painter.drawPolygon([
                QPointF(x, y) for x, y in (
                    (2, 11), (12, 3), (22, 11), (19, 11), (19, 21),
                    (14, 21), (14, 14), (10, 14), (10, 21), (5, 21), (5, 11),
                )
            ])
        case FluentSymbol.GLOBE | FluentSymbol.GLOBE_ACTIVE:
            active = symbol is FluentSymbol.GLOBE_ACTIVE
            if active:
                painter.setBrush(ink)
            circle(12, 12, 9)
            if active:
                clip = QPainterPath()
                clip.addEllipse(QRectF(4, 4, 16, 16))
                painter.setClipPath(clip)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
                painter.setPen(QPen(ink, 1.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(8.25, 3, 7.5, 18))
            line((3, 12), (21, 12))
        case FluentSymbol.FEEDBACK:
            bubble = QPainterPath(QPointF(6, 4))
            bubble.lineTo(18, 4)
            bubble.quadTo(21, 4, 21, 7)
            bubble.lineTo(21, 14)
            bubble.quadTo(21, 17, 18, 17)
            bubble.lineTo(10, 17)
            bubble.lineTo(5, 21)
            bubble.lineTo(5, 17)
            bubble.quadTo(3, 16, 3, 14)
            bubble.lineTo(3, 7)
            bubble.quadTo(3, 4, 6, 4)
            painter.drawPath(bubble)
            line((8, 9), (16, 9))
            line((8, 12), (13, 12))
        case FluentSymbol.PROJECT | FluentSymbol.OPEN:
            line((4, 19), (4, 5), (10, 5), (12, 7), (20, 7), (20, 10))
            if symbol == FluentSymbol.OPEN:
                line((4, 19), (8, 10), (22, 10), (18, 19), (4, 19))
            else:
                line((20, 10), (20, 19), (4, 19))
                line((8, 12), (16, 12))
                line((8, 15.5), (13, 15.5))
        case FluentSymbol.LINK:
            chain = QPainterPath(QPointF(10, 7))
            chain.lineTo(13.5, 3.5)
            chain.cubicTo(17, 0, 24, 7, 20.5, 10.5)
            chain.lineTo(17, 14)
            painter.drawPath(chain)
            chain = QPainterPath(QPointF(14, 17))
            chain.lineTo(10.5, 20.5)
            chain.cubicTo(7, 24, 0, 17, 3.5, 13.5)
            chain.lineTo(7, 10)
            painter.drawPath(chain)
            line((8.5, 15.5), (15.5, 8.5))
        case FluentSymbol.NEW_PROJECT:
            line((12, 20), (5, 20), (5, 4), (13, 4), (18, 9), (18, 11))
            line((13, 4), (13, 9), (18, 9))
            line((14, 16), (21, 16))
            line((17.5, 12.5), (17.5, 19.5))
        case FluentSymbol.IMPORT | FluentSymbol.EXPORT:
            line((4, 15), (4, 20), (20, 20), (20, 15))
            line((12, 4), (12, 15))
            if symbol == FluentSymbol.IMPORT:
                line((8, 11), (12, 15), (16, 11))
            else:
                line((8, 8), (12, 4), (16, 8))
        case FluentSymbol.SEND:
            line((12, 20), (12, 4))
            line((6.5, 9.5), (12, 4), (17.5, 9.5))
        case FluentSymbol.OPTIMIZE:
            line((12, 3), (14.5, 9.5), (21, 12), (14.5, 14.5),
                 (12, 21), (9.5, 14.5), (3, 12), (9.5, 9.5), (12, 3))
        case FluentSymbol.REFRESH:
            painter.drawArc(QRectF(4, 4, 16, 16), 35 * 16, 305 * 16)
            line((20, 4), (20, 9), (15, 9))
        case FluentSymbol.INFO:
            circle(12, 12, 8)
            line((12, 11.5), (12, 16))
            solid()
            circle(12, 8, 1.15)
        case FluentSymbol.SETTINGS:
            for y, knob in ((5, 8), (12, 16), (19, 10)):
                line((4, y), (knob - 2.6, y))
                line((knob + 2.6, y), (20, y))
                circle(knob, y, 2)
        case FluentSymbol.FIT:
            line((4, 8), (4, 4), (8, 4))
            line((16, 4), (20, 4), (20, 8))
            line((4, 16), (4, 20), (8, 20))
            line((16, 20), (20, 20), (20, 16))
            line((9, 12), (15, 12))
        case FluentSymbol.PLAY:
            solid()
            painter.drawPolygon([QPointF(7, 4.5), QPointF(20, 12), QPointF(7, 19.5)])
        case FluentSymbol.PAUSE:
            solid()
            box(6, 5, 4, 14, 1)
            box(14, 5, 4, 14, 1)
        case FluentSymbol.STOP:
            solid()
            box(6, 6, 12, 12, 1.5)
        case FluentSymbol.REPEAT | FluentSymbol.REPEAT_ACTIVE:
            line((4, 10), (4, 6.5), (20, 6.5))
            line((17, 3.5), (20, 6.5), (17, 9.5))
            line((20, 14), (20, 17.5), (4, 17.5))
            line((7, 14.5), (4, 17.5), (7, 20.5))
            if symbol == FluentSymbol.REPEAT_ACTIVE:
                solid()
                circle(12, 12, 2.4)
        case FluentSymbol.AUTO_TEMPO | FluentSymbol.AUTO_TEMPO_ACTIVE:
            if symbol == FluentSymbol.AUTO_TEMPO_ACTIVE:
                solid()
            else:
                pen.setWidthF(3)
                painter.setPen(pen)
            circle(12, 12, 6.5)
        case FluentSymbol.ADD_TRACK:
            line((4, 6), (19, 6))
            line((4, 11), (12, 11))
            line((4, 16), (10, 16))
            line((13, 16), (21, 16))
            line((17, 12), (17, 20))
        case FluentSymbol.DELETE:
            line((4, 7), (20, 7))
            line((9, 7), (9, 4), (15, 4), (15, 7))
            line((6, 7), (7, 20), (17, 20), (18, 7))
            line((10, 11), (10.5, 16))
            line((14, 11), (13.5, 16))
        case FluentSymbol.CURVE:
            curve = QPainterPath(QPointF(4, 17))
            curve.cubicTo(8, 17, 8, 8, 12, 11)
            curve.cubicTo(16, 14, 16, 7, 20, 7)
            painter.drawPath(curve)
            solid()
            for x, y in ((4, 17), (12, 11), (20, 7)):
                circle(x, y, 1.9)
        case FluentSymbol.MARQUEE:
            pen.setDashPattern([1.25, 1.75])
            painter.setPen(pen)
            box(4, 5, 16, 14)
        case FluentSymbol.SELECT:
            line((5, 3), (19, 12), (13, 13), (16, 19), (13, 21),
                 (10, 15), (5, 19), (5, 3))
        case FluentSymbol.RAZOR:
            circle(6.5, 17.5, 2.5)
            circle(17.5, 17.5, 2.5)
            line((8, 15.5), (18.5, 4))
            line((16, 15.5), (5.5, 4))
        case FluentSymbol.MAGNET:
            magnet = QPainterPath(QPointF(4, 19))
            magnet.lineTo(4, 11)
            magnet.cubicTo(4, 2, 20, 2, 20, 11)
            magnet.lineTo(20, 19)
            magnet.lineTo(15, 19)
            magnet.lineTo(15, 11)
            magnet.cubicTo(15, 8, 9, 8, 9, 11)
            magnet.lineTo(9, 19)
            magnet.closeSubpath()
            painter.drawPath(magnet)
            line((4, 15), (9, 15))
            line((15, 15), (20, 15))
        case FluentSymbol.UNDO | FluentSymbol.REDO:
            if symbol == FluentSymbol.REDO:
                painter.translate(24, 0)
                painter.scale(-1, 1)
            line((9, 5), (4, 10), (9, 15))
            turn = QPainterPath(QPointF(4, 10))
            turn.lineTo(15, 10)
            turn.cubicTo(21, 10, 21, 19, 15, 19)
            turn.lineTo(12, 19)
            painter.drawPath(turn)
        case FluentSymbol.NOTES_PANEL:
            box(4, 5, 16, 14)
            line((4, 13), (20, 13))
            line((8, 16), (16, 16))
        case FluentSymbol.INSPECTOR:
            box(4, 5, 16, 14)
            line((13, 5), (13, 19))
            line((16, 9), (17, 9))
            line((16, 13), (17, 13))
        case FluentSymbol.MORE:
            solid()
            for x in (5, 12, 19):
                circle(x, 12, 1.6)
        case FluentSymbol.CHEVRON_RIGHT:
            line((9, 5), (16, 12), (9, 19))
        case FluentSymbol.CHEVRON_UP:
            line((5, 15), (12, 8), (19, 15))
        case FluentSymbol.KEYBOARD:
            box(2, 5, 20, 14, 2)
            for x in (6, 10, 14, 18):
                line((x, 9), (x + 0.25, 9))
            line((7, 14), (17, 14))
        case FluentSymbol.SPEAKER | FluentSymbol.SPEAKER_MUTED:
            line((3, 9), (7, 9), (12, 5), (12, 19), (7, 15), (3, 15), (3, 9))
            if symbol is FluentSymbol.SPEAKER_MUTED:
                line((16, 9), (21, 15))
                line((21, 9), (16, 15))
            else:
                painter.drawArc(QRectF(9, 8, 9, 8), -52 * 16, 104 * 16)
                painter.drawArc(QRectF(6, 5, 16, 14), -48 * 16, 96 * 16)
        case FluentSymbol.HEADPHONES | FluentSymbol.HEADPHONES_ACTIVE:
            painter.drawArc(QRectF(3, 3, 18, 18), 0, 180 * 16)
            line((3, 12), (3, 16))
            line((21, 12), (21, 16))
            if symbol is FluentSymbol.HEADPHONES_ACTIVE:
                painter.setBrush(ink)
            box(3, 12, 5, 8, 1.5)
            box(16, 12, 5, 8, 1.5)
        case FluentSymbol.CHEVRON_DOWN:
            line((5, 9), (12, 16), (19, 9))
        case FluentSymbol.POPOUT:
            line((12, 5), (5, 5), (5, 19), (19, 19), (19, 12))
            line((14, 4), (20, 4), (20, 10))
            line((13, 11), (20, 4))
        case FluentSymbol.CLOSE:
            line((7, 7), (17, 17))
            line((17, 7), (7, 17))
        case FluentSymbol.MINIMIZE:
            line((6, 13), (18, 13))
        case FluentSymbol.MAXIMIZE:
            box(6, 6, 12, 12, 1.5)
        case FluentSymbol.RESTORE:
            line((10, 5), (19, 5), (19, 14))
            box(5, 9, 10, 10, 1.5)

    painter.end()
    return pixmap


def paint_centered_symbol(
    painter: QPainter, rect: QRectF, symbol: FluentSymbol, color: str, size: int,
) -> None:
    """Paint a cached glyph at the target device's pixel density."""
    ratio = painter.device().devicePixelRatioF()
    pixels = max(1, round(size * ratio))
    key = f"bdo.symbol.{symbol.value}.{color}.{pixels}.{ratio}"
    pixmap = QPixmapCache.find(key)
    if pixmap is None:
        pixmap = draw_symbol(symbol, color, pixels)
        pixmap.setDevicePixelRatio(ratio)
        QPixmapCache.insert(key, pixmap)
    half = pixels / ratio / 2
    painter.drawPixmap(rect.center() - QPointF(half, half), pixmap)
