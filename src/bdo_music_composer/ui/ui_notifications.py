"""Reusable packaged toast notification for Qt editor surfaces."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from bdo_music_composer.ui.page_transition_qt import MOTION_PROPERTY, interface_motion_allowed

_TOAST_EDGE_MARGIN = 16
_TOAST_ANCHOR_GAP = 8
_TOAST_MAX_TEXT_WIDTH = 480
_BOTTOM_ANCHOR_NAMES = (
    "EditorFooter",
    "SettingsFooter",
    "PerformanceStrip",
)


class GlobalToast(QFrame):
    """One non-blocking message surface shared by each top-level window."""

    MARKERS = {
        "info": "i",
        "success": "✓",
        "warning": "!",
        "error": "×",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("GlobalToast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setProperty("i18nSkipAccessibleName", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(9)
        self.marker = QLabel(self.MARKERS["info"])
        self.marker.setObjectName("ToastMarker")
        self.marker.setFixedSize(20, 20)
        self.marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.marker, 0, Qt.AlignmentFlag.AlignVCenter)
        self.message = QLabel()
        self.message.setObjectName("ToastMessage")
        self.message.setTextFormat(Qt.PlainText)
        self.message.setProperty("i18nSkipText", True)
        self.message.setWordWrap(True)
        layout.addWidget(self.message, stretch=1)

        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setEnabled(False)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._animation_finished)
        self._animation_phase = ""
        self._hold_duration_ms = 2600
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self.fade_out)
        self._apply_kind_style("info")
        parent.installEventFilter(self)
        self.hide()

    def _apply_kind_style(self, kind: str) -> None:
        if self.property("toastKind") == kind:
            return
        self.setProperty("toastKind", kind)
        self.marker.style().unpolish(self.marker)
        self.marker.style().polish(self.marker)
        self.marker.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent():
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
            }:
                QTimer.singleShot(0, self, self._reposition)
            elif (
                event.type() == QEvent.Type.DynamicPropertyChange
                and event.propertyName() == MOTION_PROPERTY.encode("ascii")
                and self._animation_phase
                and not interface_motion_allowed(self)
            ):
                self.animation.stop()
                self._animation_finished()
        return super().eventFilter(watched, event)

    def show_message(self, text: str, kind: str = "info", duration_ms: int = 2600) -> None:
        if not text:
            return
        resolved_kind = kind if kind in self.MARKERS else "info"
        self.animation.stop()
        self.hold_timer.stop()
        initial_opacity = self.opacity.opacity() if self.isVisible() else 0.0
        fade_in = initial_opacity < 1.0 and interface_motion_allowed(self)
        self._animation_phase = ""
        self._hold_duration_ms = max(0, duration_ms)
        self._apply_kind_style(resolved_kind)
        self.marker.setText(self.MARKERS[resolved_kind])
        self.message.setText(text)
        self.message.ensurePolished()
        self.setAccessibleName(text)
        self.opacity.setOpacity(initial_opacity if fade_in else 1.0)
        self.opacity.setEnabled(fade_in)
        self.show()
        self._reposition()
        self.raise_()
        # Windows can play a system sound for an accessibility Alert.
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self, text))
        if fade_in:
            self._start_fade("in", 170, 1.0)
        else:
            self.hold_timer.start(self._hold_duration_ms)

    def fade_out(self) -> None:
        self.animation.stop()
        if self.isVisible() and interface_motion_allowed(self):
            self._start_fade("out", 260, 0.0)
        else:
            self._animation_phase = "out"
            self._animation_finished()

    def _start_fade(self, phase: str, duration: int, target: float) -> None:
        self._animation_phase = phase
        self.opacity.setEnabled(True)
        self.animation.setDuration(duration)
        self.animation.setStartValue(self.opacity.opacity())
        self.animation.setEndValue(target)
        self.animation.start()

    def _animation_finished(self) -> None:
        phase = self._animation_phase
        self._animation_phase = ""
        if phase == "in":
            self.opacity.setOpacity(1.0)
            self.hold_timer.start(self._hold_duration_ms)
        elif phase == "out":
            self.hide()
        self.opacity.setEnabled(False)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return

        contents = parent.contentsRect()
        self._fit_message(contents.width() - 2 * _TOAST_EDGE_MARGIN)
        left = contents.left() + _TOAST_EDGE_MARGIN
        right = contents.right() + 1 - _TOAST_EDGE_MARGIN
        centered_x = contents.left() + (contents.width() - self.width()) // 2
        # Clamp both sides.  The old top placement only guarded the left edge,
        # allowing a long localized message to run beyond a narrow dialog.
        x = max(left, min(centered_x, right - self.width()))

        bottom_boundary = contents.bottom() + 1 - _TOAST_EDGE_MARGIN
        for object_name in _BOTTOM_ANCHOR_NAMES:
            anchor = parent.findChild(QWidget, object_name)
            if (
                anchor is None
                or anchor.window() is not parent
                or not anchor.isVisibleTo(parent)
            ):
                continue
            anchor_top = anchor.mapTo(parent, anchor.rect().topLeft()).y()
            bottom_boundary = min(
                bottom_boundary,
                anchor_top - _TOAST_ANCHOR_GAP,
            )
            break

        y = max(
            contents.top() + _TOAST_EDGE_MARGIN,
            bottom_boundary - self.height(),
        )
        self.move(int(x), int(y))

    def _fit_message(self, available_width: int) -> None:
        margins = self.layout().contentsMargins()
        decoration_width = margins.left() + margins.right() + 2 * self.frameWidth()
        decoration_width += self.marker.width() + self.layout().spacing()
        max_width = max(1, min(_TOAST_MAX_TEXT_WIDTH, available_width - decoration_width))
        metrics = self.message.fontMetrics()
        widest_line = max(metrics.horizontalAdvance(line) for line in self.message.text().split("\n"))
        text_width = min(max_width, max(120, widest_line + 2))
        text_height = max(metrics.height(), self.message.heightForWidth(text_width))
        if self.message.width() != text_width or self.message.height() != text_height:
            self.message.setFixedSize(text_width, text_height)
            self.adjustSize()


def show_global_toast(
    host: QWidget,
    text: str,
    kind: str = "info",
    duration_ms: int = 2600,
) -> GlobalToast:
    top_level = host.window()
    toast = getattr(top_level, "_global_toast", None)
    if not isinstance(toast, GlobalToast):
        toast = GlobalToast(top_level)
        setattr(top_level, "_global_toast", toast)
    # Callers translate fixed copy before it reaches this dynamic display
    # boundary.  Re-translating here could corrupt a filename or track name
    # that happens to equal a catalog value such as "Play".
    toast.show_message(text, kind=kind, duration_ms=duration_ms)
    return toast
