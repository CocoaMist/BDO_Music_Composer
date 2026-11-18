"""Modal utility panels over a single frozen view of the owner window."""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsBlurEffect, QGraphicsScene, QStyle, QStyleOption, QWidget,
)
from shiboken6 import isValid

from bdo_music_composer.ui.page_transition_qt import interface_motion_allowed
from bdo_music_composer.ui.theme import hig_tokens as hig


_MAX_SNAPSHOT_EDGE = 540
_BLUR_RADIUS = 20.0
_DIM = QColor(12, 13, 15, 145)
_PANEL_ATTRIBUTES = (
    Qt.WidgetAttribute.WA_TranslucentBackground,
    Qt.WidgetAttribute.WA_NoSystemBackground,
)
_OWNER_GEOMETRY_EVENTS = {
    QEvent.Type.Resize,
    QEvent.Type.Move,
    QEvent.Type.WindowStateChange,
    QEvent.Type.DevicePixelRatioChange,
}


def _blurred_owner_snapshot(owner: QWidget) -> QPixmap:
    scale = min(1.0, _MAX_SNAPSHOT_EDGE / max(owner.width(), owner.height()))
    size = QSize(ceil(owner.width() * scale), ceil(owner.height() * scale))
    surface_color = QColor(hig.WINDOW_SHELL)
    source = QPixmap(size)
    source.fill(surface_color)
    with QPainter(source) as painter:
        painter.scale(scale, scale)
        owner.render(painter, QPoint())

    # Apply the effect at the snapshot resolution. The visible backdrop only
    # draws this result, even if the score keeps playing behind the panel.
    scene = QGraphicsScene()
    item = scene.addPixmap(source)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(_BLUR_RADIUS * scale)
    blur.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
    item.setGraphicsEffect(blur)
    bounds = QRectF(source.rect())
    result = QPixmap(size)
    result.fill(surface_color)
    with QPainter(result) as painter:
        scene.render(painter, bounds, bounds, Qt.AspectRatioMode.IgnoreAspectRatio)
        painter.fillRect(bounds, _DIM)
    return result


class _RoundedPanelSurface(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            # A translucent window bypasses Qt's ordinary background paint.
            option = QStyleOption()
            option.initFrom(watched)
            with QPainter(watched) as painter:
                watched.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, watched)
        return False


class FloatingPanelDialog(QDialog):
    """Keep the modal dialog alive until its exit animation has settled."""

    _floating_finish = None

    def done(self, result: int) -> None:
        if self._floating_finish is not None and self._floating_finish(result):
            return
        super().done(result)

    def closeEvent(self, event) -> None:
        if self._floating_finish is not None:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)


class _FloatingPanelBackdrop(QWidget):
    def __init__(self, owner: QWidget, dialog: QDialog) -> None:
        web = owner.findChild(QWidget, "OnlineScoreLibraryContainer")
        native = web is not None and web.isVisible()
        snapshot = QPixmap() if native else _blurred_owner_snapshot(owner)
        flags = (
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
            if native else Qt.WindowType.Widget
        )
        super().__init__(owner, flags)
        self._snapshot = snapshot
        self._dim_strength = 1.0
        self._dialog = dialog
        self._preferred_size = dialog.size()
        self.setObjectName("FloatingPanelBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, native)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, native)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, not native)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit_to_owner()
        self.show()
        self.raise_()
        owner.installEventFilter(self)

    def _fit_to_owner(self) -> None:
        owner = self.parentWidget()
        self.setGeometry(
            QRect(owner.mapToGlobal(QPoint()), owner.size()) if self.isWindow() else owner.rect()
        )
        if not isValid(self._dialog) or owner.isMinimized():
            return
        owner_rect = QRect(owner.mapToGlobal(QPoint()), owner.size())
        screen = owner.screen()
        available = screen.availableGeometry() if screen is not None else owner_rect
        area = owner_rect.intersected(available)
        if area.isEmpty():
            area = available
        inset = 2 * hig.PANEL_PADDING
        size = self._preferred_size.boundedTo(area.size() - QSize(inset, inset))
        self._dialog.resize(size.expandedTo(self._dialog.minimumSize()))
        target = area.center() - self._dialog.rect().center()
        left = max(
            available.left(), min(target.x(), available.right() + 1 - self._dialog.width())
        )
        top = max(
            available.top(), min(target.y(), available.bottom() + 1 - self._dialog.height())
        )
        self._dialog.move(left, top)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in _OWNER_GEOMETRY_EVENTS:
            self._fit_to_owner()
        return False

    def follow_panel_opacity(self, opacity: float) -> None:
        if self._snapshot.isNull():
            self._dim_strength = opacity
            self.update()

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            if self._snapshot.isNull():
                # A QWidget snapshot cannot contain the native WebView2 child.
                shade = QColor(_DIM)
                shade.setAlphaF(shade.alphaF() * self._dim_strength)
                painter.fillRect(self.rect(), shade)
            else:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(self.rect(), self._snapshot)


def exec_floating_panel(dialog: QDialog) -> int:
    """Run a utility dialog with its own header, above a dimmed modal backdrop."""
    parent = dialog.parentWidget()
    owner = parent.window() if parent is not None else None
    flags = dialog.windowFlags()
    original_size = dialog.size()
    original_opacity = dialog.windowOpacity()
    original_attributes = tuple(dialog.testAttribute(attribute) for attribute in _PANEL_ATTRIBUTES)
    backdrop = None
    entry = None
    exit_animation = None
    result_code = None
    surface = _RoundedPanelSurface()
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    # Let the stylesheet draw the rounded surface on an alpha-capable window.
    # An integer window mask would make the corner edges jagged at high DPI.
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    dialog.installEventFilter(surface)
    try:
        if owner is not None and owner.isVisible() and not owner.size().isEmpty():
            dialog.ensurePolished()
            if dialog.layout() is not None:
                dialog.layout().activate()
            backdrop = _FloatingPanelBackdrop(owner, dialog)
        if (
            backdrop is not None
            and interface_motion_allowed(dialog)
            and QGuiApplication.platformName() in {"windows", "cocoa"}
        ):
            entry = QPropertyAnimation(dialog, b"windowOpacity", dialog)
            entry.setDuration(135)
            entry.setEasingCurve(QEasingCurve.OutCubic)
            entry.setStartValue(original_opacity * 0.76)
            entry.setEndValue(original_opacity)
            dialog.setWindowOpacity(entry.startValue())
            backdrop.follow_panel_opacity(entry.startValue())
            entry.valueChanged.connect(backdrop.follow_panel_opacity)

            def start_entry() -> None:
                if result_code is not None or entry is None or not isValid(dialog) or not dialog.isVisible():
                    return
                if interface_motion_allowed(dialog):
                    entry.start()
                else:
                    dialog.setWindowOpacity(original_opacity)

            QTimer.singleShot(0, entry, start_entry)
            if isinstance(dialog, FloatingPanelDialog):
                exit_animation = QPropertyAnimation(dialog, b"windowOpacity", dialog)
                exit_animation.setDuration(115)
                exit_animation.setEasingCurve(QEasingCurve.InCubic)
                exit_animation.valueChanged.connect(backdrop.follow_panel_opacity)
                def begin_exit(result: int) -> bool:
                    nonlocal result_code
                    if not dialog.isVisible() or not interface_motion_allowed(dialog):
                        return False
                    if result_code is None:
                        result_code = result
                        entry.stop()
                        exit_animation.setStartValue(dialog.windowOpacity())
                        exit_animation.setEndValue(0.16 * original_opacity)
                        exit_animation.start()
                    return True

                def finish_exit() -> None:
                    dialog._floating_finish = None
                    dialog.done(result_code)

                exit_animation.finished.connect(finish_exit)
                dialog._floating_finish = begin_exit
        return dialog.exec()
    finally:
        # A queued entrance may still dispatch as an immediately cancelled dialog unwinds.
        animation, entry = entry, None
        if animation is not None and isValid(animation):
            animation.stop()
            animation.deleteLater()
        if exit_animation is not None and isValid(exit_animation):
            exit_animation.stop()
            exit_animation.deleteLater()
        if backdrop is not None and isValid(backdrop):
            if owner is not None and isValid(owner):
                owner.removeEventFilter(backdrop)
            backdrop.hide()
            backdrop.deleteLater()
        if isValid(dialog):
            if isinstance(dialog, FloatingPanelDialog):
                dialog._floating_finish = None
            if animation is not None:
                dialog.setWindowOpacity(original_opacity)
            dialog.removeEventFilter(surface)
            dialog.setWindowFlags(flags)
            for attribute, enabled in zip(_PANEL_ATTRIBUTES, original_attributes, strict=True):
                dialog.setAttribute(attribute, enabled)
            dialog.resize(original_size)


__all__ = ["FloatingPanelDialog", "exec_floating_panel"]
