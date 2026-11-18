"""Bounded navigation accents and immediate stacked-page changes."""

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget, QWidget

from bdo_music_composer.ui.theme import hig_tokens as hig


MOTION_CONFIG_KEY = "interface_motion_enabled"
MOTION_PROPERTY = "interfaceMotionEnabled"


def interface_motion_allowed(widget: QWidget) -> bool:
    owner = widget
    while owner is not None:
        if owner.property(MOTION_PROPERTY) is False:
            return False
        owner = owner.parentWidget()
    return True


class SurfaceFade(QObject):
    """Animate a Qt overlay without changing any layout geometry."""

    def __init__(self, surface: QWidget) -> None:
        super().__init__(surface)
        self._surface = surface
        self._effect = QGraphicsOpacityEffect(surface)
        self._effect.setOpacity(1.0)
        self._effect.setEnabled(False)
        surface.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.finished.connect(self._settle)
        self._shown = not surface.isHidden()

    def set_visible(self, shown: bool, *, changed_page: bool = False) -> None:
        if shown == self._shown and not changed_page:
            return
        running = self._animation.state() == QAbstractAnimation.State.Running
        start = self._effect.opacity() if running else (0.68 if shown else 1.0)
        self._animation.stop()
        self._shown = shown
        parent = self._surface.parentWidget()
        if not parent.isVisible() or not interface_motion_allowed(parent):
            self._settle()
            return
        self._effect.setOpacity(start)
        self._effect.setEnabled(True)
        if shown:
            self._surface.show()
            self._surface.raise_()
        self._animation.setDuration(145 if shown else 115)
        self._animation.setEasingCurve(QEasingCurve.OutCubic if shown else QEasingCurve.InCubic)
        self._animation.setStartValue(start)
        self._animation.setEndValue(1.0 if shown else 0.0)
        self._animation.start()

    def _settle(self) -> None:
        self._surface.setVisible(self._shown)
        self._effect.setEnabled(False)


class _PageFade(QWidget):
    def __init__(self, stack: QStackedWidget) -> None:
        super().__init__(stack)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._alpha = 0
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(135)
        self._motion.setStartValue(64)
        self._motion.setEndValue(0)
        self._motion.setEasingCurve(QEasingCurve.OutCubic)
        self._motion.valueChanged.connect(self._step)
        self._motion.finished.connect(self.hide)
        stack.installEventFilter(self)
        self.hide()

    def play(self) -> None:
        self.stop()
        self.setGeometry(self.parentWidget().rect())
        self._step(64)
        self.show()
        self.raise_()
        self._motion.start()

    def stop(self) -> None:
        self._motion.stop()
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Resize, QEvent.Hide):
            self.stop()
        return False

    def _step(self, alpha: int) -> None:
        self._alpha = alpha
        self.update()

    def paintEvent(self, event) -> None:
        tint = QColor(hig.WINDOW_SHELL)
        tint.setAlpha(self._alpha)
        with QPainter(self) as painter:
            painter.fillRect(event.rect(), tint)


class NavigationCue(QWidget):
    """Ease a small accent between controls without repainting the page."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("NavigationCue")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self._ink = QColor(hig.ACCENT)
        self._start = QRect()
        self._end = QRect()
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(145)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.hide)
        parent.installEventFilter(self)
        self.hide()

    @property
    def is_running(self) -> bool:
        return self._animation.state() == QAbstractAnimation.State.Running

    def underline_rect(self, widget: QWidget) -> QRect:
        width = min(36, widget.width() - 8)
        rect = widget.rect()
        rect.setWidth(max(0, width))
        rect.setHeight(2)
        rect.moveCenter(widget.rect().center())
        rect.moveBottom(widget.height() - 3)
        rect.moveTopLeft(widget.mapTo(self.parentWidget(), rect.topLeft()))
        return rect

    def play_below(self, previous: QWidget, current: QWidget) -> None:
        self.play(self.underline_rect(previous), self.underline_rect(current))

    def play(self, previous: QRect, current: QRect) -> None:
        parent = self.parentWidget()
        if not parent.isVisible() or not interface_motion_allowed(parent) or current.isEmpty():
            self.finish()
            return
        self._start = self.geometry() if self.is_running else previous
        self._end = current
        self._animation.stop()
        self._advance(0.0)
        self.show()
        self.raise_()
        self._animation.start()

    def finish(self) -> None:
        self._animation.stop()
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if self.isVisible() and event.type() in (QEvent.Resize, QEvent.Hide):
            self.finish()
        return False

    def _advance(self, progress: float) -> None:
        start, end = self._start, self._end
        self.setGeometry(
            round(start.x() + (end.x() - start.x()) * progress),
            round(start.y() + (end.y() - start.y()) * progress),
            round(start.width() + (end.width() - start.width()) * progress),
            round(start.height() + (end.height() - start.height()) * progress),
        )
        self._ink.setAlphaF(min(0.9, (1.0 - progress) * 4.0))
        self.update()

    def paintEvent(self, event) -> None:
        with QPainter(self) as painter:
            painter.fillRect(self.rect(), self._ink)


class StackedPageTransition(QObject):
    """Commit navigation immediately and animate only its toolbar accent."""

    def __init__(self, stack: QStackedWidget, navigation_bar: QWidget) -> None:
        super().__init__(stack)
        self.stack = stack
        self._cue = NavigationCue(navigation_bar)
        self._fade = _PageFade(stack)

    @property
    def is_running(self) -> bool:
        return self._cue.is_running

    def commit_page(
        self,
        page: QWidget,
        focus_anchor: QWidget,
        focus_target: QWidget | None,
        *,
        leaving_native_page: bool,
        entering_native_page: bool = False,
    ) -> None:
        focused = self.stack.window().focusWidget()
        switched = page is not self.stack.currentWidget()
        handoff = switched and (
            leaving_native_page or (focused is not None and self.stack.isAncestorOf(focused))
        )
        if handoff:
            # Qt's focus restore must finish outside any disappearing native web view.
            focus_anchor.setFocus(Qt.FocusReason.OtherFocusReason)
        self.stack.setCurrentWidget(page)
        if focus_target is not None and (handoff or focus_anchor.hasFocus()):
            focus_target.setFocus(Qt.FocusReason.OtherFocusReason)
        if switched:
            self._fade.stop()
            if (
                not leaving_native_page and not entering_native_page
                and self.stack.isVisible() and interface_motion_allowed(self.stack)
            ):
                self._fade.play()

    def capture(self, anchor: QWidget | None) -> QRect | None:
        if anchor is None or not anchor.isVisible() or not interface_motion_allowed(anchor):
            self.finish()
            return None
        if self._cue.is_running:
            return self._cue.geometry()
        return self._cue.underline_rect(anchor)

    def animate(self, previous: QRect, current: QWidget | None) -> None:
        if current is None:
            return
        # The caption owns the navigation group's width when labels appear or hide.
        navigation = self._cue.parentWidget()
        caption = navigation.parentWidget() or navigation
        navigation.updateGeometry()
        if layout := caption.layout():
            layout.invalidate()
            layout.activate()
        if navigation_layout := navigation.layout():
            navigation_layout.activate()
        self._cue.play(previous, self._cue.underline_rect(current))

    def finish(self) -> None:
        self._cue.finish()
        self._fade.stop()
