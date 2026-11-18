"""Shared compact prompts for information and explicit workflow choices."""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor, QMouseEvent, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat, QTextOption,
)
from PySide6.QtWidgets import (
    QBoxLayout, QDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol
from bdo_music_composer.ui.theme.interaction_style import PROMPT_OPTIONS_QSS
from bdo_music_composer.ui.ui_controls import ElidedLabel


_PROMPT_MIN_WIDTH = 440
_PROMPT_MAX_WIDTH = 620
_PROMPT_MAX_HEIGHT = 640


class _PromptCaption(QFrame):
    def mousePressEvent(self, event: QMouseEvent) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.LeftButton and handle is not None and handle.startSystemMove():
            event.accept()
            return
        super().mousePressEvent(event)


class ComposerPrompt(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        actions: Sequence[tuple[str, str]],
        *,
        default: str,
        detail: str = "",
        items: Sequence[str] | None = None,
        field: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setObjectName("ComposerPrompt")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.choice: str | None = None
        screen = parent.screen().availableGeometry()
        screen_inset = 2 * hig.PANEL_PADDING
        max_width = min(_PROMPT_MAX_WIDTH, screen.width() - screen_inset)
        max_height = min(_PROMPT_MAX_HEIGHT, screen.height() - screen_inset)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        surface = QFrame(self)
        surface.setObjectName("PromptSurface")
        root.addWidget(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        caption = _PromptCaption(surface)
        caption.setObjectName("PromptCaption")
        caption.setFixedHeight(hig.CAPTION_HEIGHT)
        caption_row = QHBoxLayout(caption)
        caption_row.setContentsMargins(hig.PANEL_PADDING, 0, hig.ITEM_GAP, 0)
        heading = ElidedLabel(title, maximum_hint_width=530)
        heading.setObjectName("PromptTitle")
        heading.setTextFormat(Qt.PlainText)
        heading.setAttribute(Qt.WA_TransparentForMouseEvents)
        caption_row.addWidget(heading, stretch=1)
        close = QPushButton()
        set_fluent_symbol(close, FluentSymbol.CLOSE)
        close.setObjectName("PromptClose")
        close.setFixedSize(36, hig.CAPTION_BUTTON_HEIGHT)
        close.setAutoDefault(False)
        close.setAccessibleName(tr("关闭窗口"))
        close.setToolTip(close.accessibleName())
        close.clicked.connect(self.reject)
        caption_row.addWidget(close)
        layout.addWidget(caption)

        body = QVBoxLayout()
        body.setContentsMargins(*(hig.PANEL_PADDING,) * 4)
        body.setSpacing(hig.ITEM_GAP)
        body_text = self._text(message, detail, surface)
        body.addWidget(body_text)
        self.items = self._option_list(title, message, items) if items is not None else None
        if self.items is not None:
            self.items.itemActivated.connect(lambda _item: self._choose(default))
            body.addWidget(self.items)
        if field is not None:
            body.addWidget(field)
        layout.addLayout(body)

        footer = QFrame(surface)
        footer.setObjectName("PromptActions")
        row = QHBoxLayout(footer)
        row.setContentsMargins(hig.PANEL_PADDING, 0, hig.PANEL_PADDING, hig.PANEL_PADDING)
        row.setSpacing(hig.ITEM_GAP)
        buttons: list[QPushButton] = []
        for value, label in actions:
            button = QPushButton(label, footer)
            button.setProperty("promptAction", value)
            button.setProperty("kind", "convert" if value == default else "secondary")
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, chosen=value: self._choose(chosen))
            buttons.append(button)
            if value == default:
                button.setDefault(True)
                button.setFocus()
        self._layout_actions(row, buttons, max_width - screen_inset - 2)
        layout.addWidget(footer)
        list_height = 0
        if self.items is not None:
            self.items.ensurePolished()
            visible_rows = min(7, self.items.count())
            row_height = sum(self.items.sizeHintForRow(row) for row in range(visible_rows))
            inset = hig.GROUP_CONTENT_MARGIN + 1
            list_height = row_height + 2 * inset
            self.items.setFocus()

        width = min(max_width, max(_PROMPT_MIN_WIDTH, footer.sizeHint().width() + 2))
        # Measure independently from the text view's viewport, which does not
        # get its final width until after this dialog is laid out.
        document = body_text.document().clone()
        document.setTextWidth(width - screen_inset - 2)
        content_height = ceil(document.size().height()) + 1
        available_height = max_height - caption.height() - footer.sizeHint().height() - screen_inset - 2
        if field is not None:
            available_height -= field.sizeHint().height() + body.spacing()
        if self.items is not None:
            available_height = max(0, available_height - body.spacing())
            text_reserve = min(content_height, available_height // 2)
            list_height = min(list_height, available_height - text_reserve)
            self.items.setFixedHeight(list_height)
            available_height -= list_height
        body_text.setFixedHeight(min(content_height, max(0, available_height)))
        body_text.setFocusPolicy(Qt.StrongFocus if content_height > available_height else Qt.ClickFocus)
        self.setFixedWidth(width)
        self.adjustSize()
        if field is not None:
            field.setFocus()

    @staticmethod
    def _layout_actions(
        row: QHBoxLayout, buttons: list[QPushButton], available_width: int,
    ) -> None:
        for button in buttons:
            button.ensurePolished()
        button_widths = sum(button.sizeHint().width() for button in buttons)
        if button_widths + max(0, len(buttons) - 1) * row.spacing() <= available_width:
            row.addStretch(1)
        else:
            row.setDirection(QBoxLayout.TopToBottom)
        for button in buttons:
            label_capacity = available_width - (
                button.sizeHint().width() - button.fontMetrics().horizontalAdvance(button.text())
            )
            if button.sizeHint().width() > available_width:
                button.setAccessibleName(button.text())
                button.setToolTip(button.text())
                button.setText(button.fontMetrics().elidedText(button.text(), Qt.ElideRight, label_capacity))
            row.addWidget(button)

    @staticmethod
    def _text(message: str, detail: str, parent: QWidget) -> QTextEdit:
        text = QTextEdit(parent)
        text.setObjectName("PromptText")
        text.setReadOnly(True)
        text.setTabChangesFocus(True)
        text.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        text.ensurePolished()
        text.document().setDefaultFont(text.font())
        text.document().setDocumentMargin(0)
        cursor = text.textCursor()
        cursor.insertText(message)
        if detail:
            paragraph = QTextBlockFormat()
            paragraph.setTopMargin(hig.ITEM_GAP)
            style = QTextCharFormat()
            style.setForeground(QColor(hig.SECONDARY_TEXT))
            style.setProperty(QTextFormat.FontPixelSize, hig.TYPE_SECONDARY)
            cursor.insertBlock(paragraph, style)
            cursor.insertText(detail)
        cursor.movePosition(QTextCursor.Start)
        text.setTextCursor(cursor)
        return text

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    @staticmethod
    def _option_list(title: str, message: str, items: Sequence[str]) -> QListWidget:
        options = QListWidget()
        options.setObjectName("PromptOptions")
        # Use the same item geometry for measuring and painting, even when
        # the parent has a stylesheet targeting all dialog item views.
        options.setStyleSheet(PROMPT_OPTIONS_QSS)
        options.setAccessibleName(title)
        options.setAccessibleDescription(message)
        options.setProperty("i18nSkipItems", True)
        options.setProperty("i18nSkipAccessibleDescription", True)
        options.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        options.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        options.setTextElideMode(Qt.ElideRight)
        for text in items:
            option = QListWidgetItem(text)
            option.setToolTip(text)
            options.addItem(option)
        options.setCurrentRow(0)
        return options


def choose_prompt(
    parent: QWidget,
    title: str,
    message: str,
    actions: Sequence[tuple[str, str]],
    *,
    default: str,
    cancel: str,
    detail: str = "",
) -> str:
    prompt = ComposerPrompt(parent, title, message, actions, default=default, detail=detail)
    prompt.exec()
    choice = prompt.choice if prompt.choice is not None else cancel
    prompt.deleteLater()
    return choice


def choose_item(
    parent: QWidget,
    title: str,
    message: str,
    items: Sequence[str],
) -> tuple[str, bool]:
    if not items:
        return "", False
    prompt = ComposerPrompt(
        parent, title, message,
        (("cancel", tr("取消")), ("confirm", tr("确定"))),
        default="confirm", items=items,
    )
    prompt.exec()
    selected = prompt.items.currentItem() if prompt.items is not None else None
    result = ("", False)
    if selected is not None and prompt.choice == "confirm":
        result = (selected.text(), True)
    prompt.deleteLater()
    return result


def prompt_text(
    parent: QWidget, title: str, label: str, initial: str = "",
) -> tuple[str, bool]:
    field = QLineEdit(initial)
    field.setAccessibleName(label)
    prompt = ComposerPrompt(
        parent, title, label,
        (("cancel", tr("取消")), ("confirm", tr("确定"))),
        default="confirm", field=field,
    )
    field.selectAll()
    prompt.exec()
    result = (field.text(), True) if prompt.choice == "confirm" else ("", False)
    prompt.deleteLater()
    return result
