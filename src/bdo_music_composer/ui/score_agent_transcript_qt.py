"""Read-only conversation rendering shared by the dock and floating Agent."""

from __future__ import annotations

import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextDocument, QTextFormat,
)
from PySide6.QtWidgets import QTextBrowser

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.ui_controls import PillButton


_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_LIST_ITEM = re.compile(r"^([ \t]*)([-+*]|[0-9]{1,9}[.)])[ \t]+(.+)$")
_QUOTE = re.compile(r"^ {0,3}(?:>[ \t]?)+")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INLINE_PREFIX = "• "
_INLINE_MARKERS = frozenset("\\*_~`[<>&")
_MARKDOWN_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)


def _text(color: str, size: int, *, bold: bool = False) -> QTextCharFormat:
    style = QTextCharFormat()
    style.setForeground(QColor(color))
    style.setProperty(QTextFormat.Property.FontPixelSize, size)
    if bold:
        style.setFontWeight(QFont.Weight.DemiBold)
    return style


def _paragraph(*, left: int = 0, top: int = 0, bottom: int = 0) -> QTextBlockFormat:
    style = QTextBlockFormat()
    style.setLeftMargin(left)
    style.setTopMargin(top)
    style.setBottomMargin(bottom)
    style.setLineHeight(132, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    return style


class _MarkdownText(QTextDocument):
    """Parse Markdown in an isolated document that never resolves resources."""

    def loadResource(self, resource_type: int, name: QUrl) -> None:
        return None


class ScoreAgentTranscript(QTextBrowser):
    """Format turns in one selectable document and follow the reply on demand."""

    def __init__(self) -> None:
        super().__init__()
        self._partial_line = ""
        self._ended_with_cr = False
        self._code_fence = ""
        self._user_role = _text(hig.SECONDARY_TEXT, hig.TYPE_SECONDARY, bold=True)
        self._agent_role = _text(hig.ACCENT, hig.TYPE_SECONDARY, bold=True)
        self._scope = _text(hig.SECONDARY_TEXT, hig.TYPE_CAPTION)
        self._body = _text(hig.TEXT, hig.TYPE_BODY)
        self._heading = _text(hig.TEXT, hig.TYPE_DOCUMENT, bold=True)
        self._quote = _text(hig.SECONDARY_TEXT, hig.TYPE_BODY)
        self._code = _text(hig.TEXT, hig.TYPE_BODY)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._code.setFontFamilies([fixed_font.family()])
        self._inline_code = QTextCharFormat(self._code)
        self._inline_code.setBackground(QColor(hig.CONTROL))
        self._markdown = _MarkdownText(self)

        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setTabChangesFocus(True)
        self.setUndoRedoEnabled(False)
        self.document().setDocumentMargin(2)
        self.document().setMaximumBlockCount(240)
        self._latest = PillButton("", "secondary")
        self._latest.setObjectName("ScoreAgentLatest")
        self._latest.setAutoDefault(False)
        self._latest.setParent(self.viewport())
        self._latest.clicked.connect(self._jump_to_latest)
        self._latest.hide()
        scrollbar = self.verticalScrollBar()
        scrollbar.valueChanged.connect(self._sync_latest)
        scrollbar.rangeChanged.connect(self._sync_latest)
        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        self._latest.setText(tr("回到最新回复"))
        self._latest.adjustSize()
        self._place_latest()

    def clear(self) -> None:
        self._partial_line = ""
        self._ended_with_cr = False
        self._code_fence = ""
        super().clear()

    def start_turn(self, scope: str, instruction: str) -> None:
        self.finish_reply()
        cursor = self._end_cursor()
        cursor.beginEditBlock()
        user = _paragraph(left=hig.SECTION_GAP, top=hig.PANEL_PADDING if not self.document().isEmpty() else 0)
        if not cursor.block().text():
            cursor.setBlockFormat(user)
        else:
            cursor.insertBlock(user)
        cursor.insertText(tr("你"), self._user_role)
        if scope:
            cursor.insertText(f"  ·  {scope}", self._scope)
        message = _paragraph(left=hig.SECTION_GAP, top=hig.CONTROL_GAP)
        message.setBackground(QColor(hig.CONTROL))
        cursor.insertBlock(message)
        cursor.insertText(instruction, self._body)
        cursor.insertBlock(_paragraph(top=hig.PANEL_PADDING, bottom=hig.CONTROL_GAP))
        cursor.insertText(tr("创作 Agent"), self._agent_role)
        cursor.insertBlock(_paragraph())
        cursor.endEditBlock()
        self._jump_to_latest()

    def append_reply(self, text: str) -> None:
        if not text:
            return
        # A provider can split CRLF across stream chunks.
        if self._ended_with_cr and text.startswith("\n"):
            text = text[1:]
        self._ended_with_cr = text.endswith("\r")
        bar = self.verticalScrollBar()
        previous = bar.value()
        follow = bar.maximum() - previous <= 2
        cursor = self._end_cursor()
        cursor.beginEditBlock()
        lines = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n").split("\n")
        for line in lines[:-1]:
            self._partial_line += line
            if self._format_line(cursor):
                cursor.insertBlock(_paragraph(), self._body)
        self._partial_line += lines[-1]
        cursor.insertText(lines[-1], self._code if self._code_fence else self._body)
        cursor.endEditBlock()
        bar.setValue(bar.maximum() if follow else previous)

    def finish_reply(self) -> None:
        bar = self.verticalScrollBar()
        previous = bar.value()
        follow = bar.maximum() - previous <= 2
        if self._partial_line:
            cursor = self._end_cursor()
            cursor.beginEditBlock()
            self._format_line(cursor)
            cursor.endEditBlock()
        self._ended_with_cr = False
        self._code_fence = ""
        bar.setValue(bar.maximum() if follow else previous)

    def append_inline_object(self, format: QTextCharFormat) -> None:
        """Insert an application-generated object in its own selectable block."""
        bar = self.verticalScrollBar()
        previous = bar.value()
        follow = bar.maximum() - previous <= 2
        self.finish_reply()
        cursor = self._end_cursor()
        cursor.beginEditBlock()
        block = _paragraph(top=hig.ITEM_GAP, bottom=hig.ITEM_GAP)
        if cursor.block().text():
            cursor.insertBlock(block, self._body)
        else:
            cursor.setBlockFormat(block)
        cursor.insertText("\ufffc", format)
        cursor.insertBlock(_paragraph(), self._body)
        cursor.endEditBlock()
        bar.setValue(bar.maximum() if follow else previous)

    def append_web_sources(self, rows: list[tuple[str, str, str]]) -> None:
        """Insert app-generated rows (title, host, internal anchor)."""
        if not rows:
            return
        bar = self.verticalScrollBar()
        previous = bar.value()
        follow = bar.maximum() - previous <= 2
        cursor = self._end_cursor()
        cursor.beginEditBlock()
        heading = _paragraph(top=hig.GROUP_GAP, bottom=hig.CONTROL_GAP)
        if cursor.block().text():
            cursor.insertBlock(heading, self._body)
        else:
            cursor.setBlockFormat(heading)
        cursor.insertText(tr("网页来源"), self._user_role)
        for title, host, anchor in rows:
            cursor.insertBlock(_paragraph(bottom=hig.CONTROL_GAP), self._body)
            link = _text(hig.TEXT, hig.TYPE_SECONDARY)
            link.setAnchor(True)
            link.setAnchorHref(anchor)
            link.setFontUnderline(True)
            link.setToolTip(host)
            cursor.insertText(title, link)
            cursor.insertText(f"  ·  {host}", self._scope)
        cursor.insertBlock(_paragraph(), self._body)
        cursor.endEditBlock()
        bar.setValue(bar.maximum() if follow else previous)

    def _end_cursor(self) -> QTextCursor:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor

    def _format_line(self, cursor: QTextCursor) -> bool:
        line, self._partial_line = self._partial_line, ""
        fence = _FENCE.fullmatch(line)
        if self._code_fence:
            if (
                fence and fence.group(1).startswith(self._code_fence)
                and not fence.group(2).strip()
            ):
                self._code_fence = ""
                self._replace_line(cursor, _paragraph())
                return False
            block = _paragraph(left=hig.ITEM_GAP)
            block.setBackground(QColor(hig.CONTROL))
            self._replace_line(cursor, block)
            cursor.insertText(line, self._code)
            return True
        if fence and (fence.group(1).startswith("~") or "`" not in fence.group(2)):
            self._code_fence = fence.group(1)
            self._replace_line(cursor, _paragraph())
            return False

        block = _paragraph()
        style = self._body
        prefix = ""
        quote = _QUOTE.match(line)
        if quote:
            line = line[quote.end():]
            block.setLeftMargin(min(3, quote.group(0).count(">")) * hig.ITEM_GAP)
            style = self._quote
        heading = _HEADING.fullmatch(line)
        item = _LIST_ITEM.fullmatch(line)
        if heading:
            line = heading.group(1)
            block.setTopMargin(hig.ITEM_GAP)
            block.setBottomMargin(hig.CONTROL_GAP)
            style = self._heading
        elif item:
            indent, marker, line = item.groups()
            block.setLeftMargin(
                block.leftMargin() + (1 + min(len(indent.expandtabs(4)) // 2, 3)) * hig.ITEM_GAP,
            )
            block.setBottomMargin(2)
            prefix = ("•" if marker in {"-", "+", "*"} else marker) + " "
        has_inline = not _INLINE_MARKERS.isdisjoint(line)
        if not (quote or heading or item or has_inline):
            visible = cursor.block().text()
            if len(visible) < len(line):
                cursor.insertText(line[len(visible):], self._body)
            return True

        self._replace_line(cursor, block)
        cursor.insertText(prefix, style)
        if has_inline:
            self._write_inline(cursor, line, style)
        else:
            cursor.insertText(line, style)
        return True

    @staticmethod
    def _replace_line(cursor: QTextCursor, block: QTextBlockFormat) -> None:
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.setBlockFormat(block)

    def _write_inline(self, cursor: QTextCursor, source: str, base: QTextCharFormat) -> None:
        # The prefix keeps the scratch parser in a paragraph after we remove
        # block markers. Copy formatting properties, never anchors or images.
        self._markdown.setMarkdown(_INLINE_PREFIX + source, _MARKDOWN_FEATURES)
        fragments = self._markdown.begin().begin()
        skip = len(_INLINE_PREFIX)
        while not fragments.atEnd():
            fragment = fragments.fragment()
            text = fragment.text()
            parsed = fragment.charFormat()
            if skip:
                text, skip = text[skip:], max(0, skip - len(text))
            if parsed.isImageFormat():
                text = parsed.property(QTextFormat.Property.ImageAltText) or ""
            if text:
                style = QTextCharFormat(self._inline_code if parsed.fontFixedPitch() else base)
                if parsed.fontWeight() > QFont.Weight.Normal:
                    style.setFontWeight(QFont.Weight.DemiBold)
                style.setFontItalic(parsed.fontItalic())
                style.setFontStrikeOut(parsed.fontStrikeOut())
                cursor.insertText(text, style)
            fragments += 1

    def resizeEvent(self, event) -> None:
        bar = self.verticalScrollBar()
        follow = bar.maximum() - bar.value() <= 2
        super().resizeEvent(event)
        if follow:
            bar.setValue(bar.maximum())
        self._place_latest()

    def _place_latest(self) -> None:
        viewport = self.viewport()
        self._latest.move(
            max(hig.CONTROL_GAP, viewport.width() - self._latest.width() - hig.ITEM_GAP),
            max(hig.CONTROL_GAP, viewport.height() - self._latest.height() - hig.ITEM_GAP),
        )

    def _sync_latest(self) -> None:
        scrollbar = self.verticalScrollBar()
        show = scrollbar.maximum() - scrollbar.value() > 2
        if show:
            self._place_latest()
        self._latest.setVisible(show)

    def _jump_to_latest(self) -> None:
        if self._latest.hasFocus():
            self.setFocus()
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
