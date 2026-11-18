"""Reusable packaged Qt controls shared by editor surfaces."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent, QPainter, QPalette, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QStyle, QStyleOptionButton, QStyleOptionComboBox,
    QStyleOptionSpinBox,
    QStylePainter, QVBoxLayout, QWidget,
)

from .theme.fluent_theme import FluentSymbol, fluent_icon_size, set_fluent_symbol
from .theme import hig_tokens as hig
from .theme.symbols import paint_centered_symbol


def dialog_header(title: str, subtitle: str) -> QFrame:
    """Shared full-width heading for utility and workflow dialogs."""

    frame = QFrame()
    frame.setProperty("uiRole", "dialogHeader")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 14, 24, 13)
    layout.setSpacing(2)
    heading = QLabel(title)
    heading.setProperty("uiRole", "dialogTitle")
    description = QLabel(subtitle)
    description.setProperty("uiRole", "dialogSubtitle")
    description.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(description)
    return frame


def dialog_footer(
    buttons: QDialogButtonBox,
    primary: QDialogButtonBox.StandardButton | None = None,
) -> QFrame:
    """Keep actions anchored below scrollable content with one commit action."""

    buttons.setProperty("uiRole", "dialogButtonRow")
    if primary is not None:
        button = buttons.button(primary)
        if button is not None:
            button.setProperty("kind", "convert")
    frame = QFrame()
    frame.setProperty("uiRole", "dialogFooter")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(24, 10, 24, 10)
    layout.addWidget(buttons)
    return frame


class CommitSlider(QSlider):
    """Finish edits for groove clicks, keyboard and wheel as well as drags."""

    editingFinished = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self.editingFinished.emit()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        super().keyReleaseEvent(event)
        if not event.isAutoRepeat():
            self.editingFinished.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        super().wheelEvent(event)
        self.editingFinished.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.editingFinished.emit()


class ElidedLabel(QLabel):
    """A one-line label that yields space without hiding its full value."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        maximum_hint_width: int = 240,
    ) -> None:
        super().__init__(text, parent)
        self.maximum_hint_width = max(40, int(maximum_hint_width))
        if text:
            self.setToolTip(text)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(self.maximum_hint_width, hint.width()), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(36, hint.width()), hint.height())

    def setText(self, text: str) -> None:
        value = str(text)
        super().setText(value)
        self.setToolTip(value)

    def paintEvent(self, event) -> None:
        rect = self.contentsRect()
        if self.fontMetrics().horizontalAdvance(self.text()) <= rect.width():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            rect,
            self.alignment(),
            self.fontMetrics().elidedText(
                self.text(), Qt.ElideRight, max(0, rect.width())
            ),
        )


class GlyphSpinBox(QSpinBox):
    """Native spin-box editing and repeat behavior with themed arrows."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        for control, step, symbol in (
            (QStyle.SC_SpinBoxUp, QSpinBox.StepUpEnabled, FluentSymbol.CHEVRON_UP),
            (QStyle.SC_SpinBoxDown, QSpinBox.StepDownEnabled, FluentSymbol.CHEVRON_DOWN),
        ):
            rect = self.style().subControlRect(QStyle.CC_SpinBox, option, control, self)
            if rect.isEmpty():
                continue
            enabled = self.isEnabled() and bool(option.stepEnabled & step)
            hover = bool(option.activeSubControls & control)
            pressed = hover and bool(option.state & QStyle.State_Sunken)
            color = (
                hig.SEPARATOR if not enabled else hig.ACCENT if pressed
                else hig.TEXT if hover else hig.SECONDARY_TEXT
            )
            paint_centered_symbol(painter, QRectF(rect), symbol, color, 15)


class GlyphComboBox(QComboBox):
    """Native popup and focus behavior with a themed disclosure glyph."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self)
        if rect.isEmpty():
            return
        expanded = bool(option.state & QStyle.State_On)
        color = (
            hig.DISABLED_TEXT if not self.isEnabled() else hig.ACCENT if expanded
            else hig.TEXT if self.hasFocus() or self.underMouse() else hig.SECONDARY_TEXT
        )
        painter = QPainter(self)
        paint_centered_symbol(
            painter, QRectF(rect),
            FluentSymbol.CHEVRON_UP if expanded else FluentSymbol.CHEVRON_DOWN, color, 13,
        )


class ElidedComboBox(QComboBox):
    """Display compact dynamic names while retaining the full item text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumContentsLength(10)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setProperty("i18nSkipToolTip", True)
        self.currentTextChanged.connect(self.refresh_text_tooltip)
        self.view().setTextElideMode(Qt.ElideMiddle)
        self.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def refresh_text_tooltip(self) -> None:
        self.setToolTip(self.currentText())

    def paintEvent(self, event) -> None:
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        if self.currentIndex() < 0 and (placeholder := self.placeholderText()):
            option.currentText = placeholder
            option.palette.setBrush(QPalette.ButtonText, option.palette.placeholderText())
        field = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        icon_width = option.iconSize.width() + 4 if not option.currentIcon.isNull() else 0
        option.currentText = self.fontMetrics().elidedText(
            option.currentText, Qt.ElideMiddle, max(0, field.width() - icon_width - 4)
        )
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)


class ElidedCheckBox(QCheckBox):
    """Keep dynamic option names available without widening a whole panel."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setToolTip(text)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(240, hint.width()), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(min(48, hint.width()), hint.height())

    def paintEvent(self, event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        text_rect = self.style().subElementRect(QStyle.SE_CheckBoxContents, option, self)
        option.text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_rect.width())
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_CheckBox, option)


class PillButton(QPushButton):
    def __init__(
        self,
        text: str,
        kind: str = "secondary",
        icon: FluentSymbol | None = None,
    ) -> None:
        super().__init__(text)
        self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        if icon is not None:
            set_fluent_symbol(self, icon)
            self.setIconSize(fluent_icon_size())
