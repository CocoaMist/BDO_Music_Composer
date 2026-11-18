"""A detachable score conversation sharing the workbench's Agent panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeyEvent, QMouseEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizeGrip, QVBoxLayout, QWidget,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.page_transition_qt import interface_motion_allowed
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol

if TYPE_CHECKING:
    from bdo_music_composer.ui.score_agent_panel_qt import ScoreAgentPanel


_DEFAULT_WIDTH = 600
_DEFAULT_HEIGHT = 432
_MIN_WIDTH = 300


class _FloatingCaption(QFrame):
    def __init__(self, window: ScoreAgentFloatingWindow) -> None:
        super().__init__(window)
        self._owner = window
        self._move_offset: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._owner._anchor_position = False
        handle = self._owner.windowHandle()
        if handle is None or not handle.startSystemMove():
            self._move_offset = event.globalPosition().toPoint() - self._owner.pos()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._move_offset is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        self._owner.move(event.globalPosition().toPoint() - self._move_offset)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._move_offset = None
        super().mouseReleaseEvent(event)


class ScoreAgentFloatingWindow(QWidget):
    """Display the existing panel in a movable, non-modal tool window."""

    redock_requested = Signal()
    dismiss_requested = Signal()

    def __init__(
        self, parent: QWidget, panel: ScoreAgentPanel, *, anchor: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("ScoreAgentFloatingWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self._anchor = anchor if anchor is not None else parent
        self._panel: ScoreAgentPanel | None = panel
        self._anchor_position = True
        self._open_requested = False
        self._visibility_motion = QPropertyAnimation(self, b"windowOpacity", self)
        self._visibility_motion.finished.connect(lambda: self._sync_visibility())
        self._compact = False
        self._expanded_height = _DEFAULT_HEIGHT
        self._mode_bottom = 0
        self._placement_timer = QTimer(self)
        self._placement_timer.setSingleShot(True)
        self._placement_timer.timeout.connect(self._place_over_score)
        self._mode_timer = QTimer(self)
        self._mode_timer.setSingleShot(True)
        self._mode_timer.timeout.connect(self._resize_for_mode)
        self._anchor.installEventFilter(self)
        if parent is not self._anchor:
            parent.installEventFilter(self)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        self._surface = QFrame(self)
        self._surface.setObjectName("ScoreAgentFloatingSurface")
        shell.addWidget(self._surface)
        self._content = QVBoxLayout(self._surface)
        self._content.setContentsMargins(hig.ITEM_GAP, 1, hig.ITEM_GAP, 1)
        self._content.setSpacing(0)

        caption = _FloatingCaption(self)
        caption.setObjectName("ScoreAgentFloatingCaption")
        caption.setFixedHeight(hig.CAPTION_BUTTON_HEIGHT + hig.ITEM_GAP)
        caption_row = QHBoxLayout(caption)
        caption_row.setContentsMargins(hig.ITEM_GAP, 0, 0, 0)
        caption_row.setSpacing(1)
        self._heading = QLabel(caption)
        self._heading.setObjectName("ScoreAgentFloatingHeading")
        self._heading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        caption_row.addWidget(self._heading, 1)
        self._collapse_button = self._caption_button(FluentSymbol.MINIMIZE, caption)
        self._collapse_button.clicked.connect(self._toggle_compact)
        self._dock_button = self._caption_button(FluentSymbol.INSPECTOR, caption)
        self._dock_button.clicked.connect(self.redock_requested.emit)
        self._close_button = self._caption_button(FluentSymbol.CLOSE, caption)
        self._close_button.setObjectName("ScoreAgentFloatingClose")
        self._close_button.clicked.connect(self.close)
        for button in (self._collapse_button, self._dock_button, self._close_button):
            caption_row.addWidget(button)
        self._content.addWidget(caption)
        panel.set_floating_caption(caption_row)
        panel.expand_requested.connect(self.expand)
        self._content.addWidget(panel, 1)
        panel.show()

        self._grip = QSizeGrip(self._surface)
        self._grip.setFixedSize(hig.PANEL_PADDING, hig.CONTROL_GAP + hig.ITEM_GAP)
        self._grip.installEventFilter(self)
        self._content.addWidget(self._grip, 0, Qt.AlignmentFlag.AlignRight)
        self._surface.setStyleSheet(f"""
            QFrame#ScoreAgentFloatingSurface {{
                background-color: {hig.PANEL};
                border: 1px solid {hig.WINDOW_OUTLINE};
                border-radius: {hig.PANEL_RADIUS}px;
            }}
            QFrame#ScoreAgentFloatingCaption {{
                background: transparent; border: none;
                border-bottom: 1px solid {hig.SEPARATOR};
            }}
            QLabel#ScoreAgentFloatingHeading {{
                color: {hig.TEXT};
                font-size: {hig.TYPE_DOCUMENT}px;
                font-weight: 600;
            }}
            QFrame#ScoreAgentFloatingCaption QPushButton {{
                background: transparent; border: 1px solid transparent;
            }}
            QFrame#ScoreAgentFloatingCaption QPushButton:hover {{ background: {hig.CONTROL_HOVER}; }}
            QFrame#ScoreAgentFloatingCaption QPushButton:pressed {{ background: {hig.CONTROL_PRESSED}; }}
            QFrame#ScoreAgentFloatingCaption QPushButton:focus {{ border-color: {hig.INDICATOR_BORDER}; }}
        """)
        screen_size = self._anchor.screen().availableGeometry().size()
        usable_width = max(1, screen_size.width() - 2 * hig.ITEM_GAP)
        self.setMinimumWidth(min(_MIN_WIDTH, usable_width))
        self.resize(
            min(_DEFAULT_WIDTH, usable_width, max(self.minimumWidth(), self._anchor.width() - 2 * hig.PANEL_PADDING)),
            min(_DEFAULT_HEIGHT, screen_size.height() - 2 * hig.PANEL_PADDING),
        )
        self.retranslate_dynamic_content()

    @staticmethod
    def _caption_button(symbol: FluentSymbol, parent: QWidget) -> QPushButton:
        button = QPushButton(parent)
        button.setProperty("kind", "ghost")
        button.setFixedSize(hig.BUTTON_HEIGHT, hig.CAPTION_BUTTON_HEIGHT)
        button.setAutoDefault(False)
        set_fluent_symbol(button, symbol)
        return button

    def retranslate_dynamic_content(self) -> None:
        heading = tr("创作 Agent")
        self.setWindowTitle(heading)
        self._heading.setText(heading)
        for button, label in (
            (self._collapse_button, "展开对话" if self._compact else "收起对话"),
            (self._dock_button, "回到侧边栏"),
            (self._close_button, "关闭悬浮对话"),
        ):
            button.setAccessibleName(tr(label))
            button.setToolTip(button.accessibleName())

    def _toggle_compact(self) -> None:
        if self._panel is None:
            return
        self._mode_bottom = self.y() + self.height()
        if not self._compact:
            self._expanded_height = self.height()
        self._compact = not self._compact
        self._panel.set_floating_compact(self._compact)
        if self._compact:
            self._panel.prompt.setFocus(Qt.FocusReason.OtherFocusReason)
        self._grip.setVisible(not self._compact)
        # Query the current minimum after the nested layouts update.
        self._mode_timer.start(0)
        set_fluent_symbol(self._collapse_button, FluentSymbol.RESTORE if self._compact else FluentSymbol.MINIMIZE)
        self.retranslate_dynamic_content()

    def expand(self) -> None:
        if self._compact:
            self._toggle_compact()

    def _resize_for_mode(self, bottom: int | None = None) -> None:
        new_height = self.minimumSizeHint().height() if self._compact else self._expanded_height
        if self.height() == new_height:
            return
        self.resize(self.width(), new_height)
        if self._anchor_position:
            self._place_over_score()
        else:
            self._move_inside_screen(
                QPoint(self.x(), (self._mode_bottom if bottom is None else bottom) - self.height()),
                self.screen().availableGeometry(),
            )

    def _place_over_score(self) -> None:
        if not self._anchor_position or not self._anchor.isVisible() or self._panel is None:
            return
        anchor = QRect(self._anchor.mapToGlobal(QPoint(0, 0)), self._anchor.size())
        screen = self._anchor.screen().availableGeometry()
        gap = hig.PANEL_PADDING
        if not self._compact:
            usable_height = max(self.minimumSizeHint().height(), anchor.height() - 2 * gap)
            self.resize(self.width(), min(self._expanded_height, usable_height))
        position = QPoint(
            anchor.center().x() - self.width() // 2,
            max(anchor.top() + gap, anchor.bottom() + 1 - gap - self.height()),
        )
        self._move_inside_screen(position, screen)

    def _move_inside_screen(self, position: QPoint, screen: QRect) -> None:
        edge = hig.ITEM_GAP
        limits = screen.adjusted(edge, edge, -edge, -edge)
        x = min(max(position.x(), limits.left()), max(limits.left(), limits.right() + 1 - self.width()))
        y = min(max(position.y(), limits.top()), max(limits.top(), limits.bottom() + 1 - self.height()))
        self.move(x, y)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._placement_timer.start(0)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and not self._compact:
            self._toggle_compact()
            event.accept()
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        # QWidget updates the outer min-size constraint in its layout event.
        # Content visibility can cause another pass after the mode timer.
        if event.type() != QEvent.Type.LayoutRequest or not getattr(self, "_compact", False) or self._panel is None:
            return super().event(event)
        bottom = self.y() + self.height()
        handled = super().event(event)
        self._resize_for_mode(bottom)
        return handled

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if watched is getattr(self, "_grip", None) and kind == QEvent.Type.MouseButtonPress:
            self._anchor_position = False
        elif watched is self._anchor or watched is self.parentWidget():
            if kind == QEvent.Type.Hide:
                self._visibility_motion.stop()
                self.setWindowOpacity(1.0)
                self.hide()
            elif kind in (QEvent.Type.Show, QEvent.Type.WindowStateChange):
                self._sync_visibility()
            elif kind in (QEvent.Type.Move, QEvent.Type.Resize) and self.isVisible():
                self._placement_timer.start(0)
        return super().eventFilter(watched, event)

    def set_conversation_visible(self, visible: bool) -> None:
        self._open_requested = visible
        self._sync_visibility(animate=True)

    def _sync_visibility(self, *, animate: bool = False) -> None:
        owner = self.parentWidget()
        exposed = self._anchor.isVisible() and owner.isVisible() and not owner.isMinimized()
        shown = self._open_requested and exposed
        self._visibility_motion.stop()
        if (
            animate and exposed and interface_motion_allowed(owner)
            and QGuiApplication.platformName() in {"windows", "cocoa"}
        ):
            if shown or self.isVisible():
                start = self.windowOpacity() if self.isVisible() else 0.76
                self.setWindowOpacity(start)
                if shown and not self.isVisible():
                    self._place_over_score()
                    self.show()
                self._visibility_motion.setDuration(140 if shown else 115)
                self._visibility_motion.setEasingCurve(QEasingCurve.OutCubic if shown else QEasingCurve.InCubic)
                self._visibility_motion.setStartValue(start)
                self._visibility_motion.setEndValue(1.0 if shown else 0.16)
                self._visibility_motion.start()
                return
        self.setVisible(shown)
        self.setWindowOpacity(1.0)

    def take_panel(self) -> ScoreAgentPanel | None:
        """Remove the panel for immediate reparenting into the sidebar."""
        panel, self._panel = self._panel, None
        self._visibility_motion.stop()
        self._placement_timer.stop()
        self._mode_timer.stop()
        if panel is not None:
            panel.expand_requested.disconnect(self.expand)
            self._content.removeWidget(panel)
            panel.hide()
            panel.set_floating_compact(False)
            panel.set_floating_caption(None)
        return panel

    def closeEvent(self, event: QCloseEvent) -> None:
        self._open_requested = False
        if self._panel is not None:
            self.dismiss_requested.emit()
            event.ignore()
        else:
            super().closeEvent(event)


__all__ = ["ScoreAgentFloatingWindow"]
