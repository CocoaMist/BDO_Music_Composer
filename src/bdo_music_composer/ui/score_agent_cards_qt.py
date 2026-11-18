"""Native, app-owned result cards inside the Agent conversation document."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPyTextObject, QTextCharFormat, QTextFormat

from bdo_music_composer.ui.theme import hig_tokens as hig


_CARD_OBJECT = int(QTextFormat.ObjectTypes.UserObject) + 1
_TITLE = int(QTextFormat.Property.UserProperty) + 1
_DETAIL = _TITLE + 1
_ACTION = _DETAIL + 1
_CARD_HEIGHT = 64
_CARD_MAX_WIDTH = 400


class ScoreAgentCards(QPyTextObject):
    def __init__(self, document) -> None:
        super().__init__(document)
        document.documentLayout().registerHandler(_CARD_OBJECT, self)

    @staticmethod
    def edit_receipt(title: str, detail: str, action: str, receipt_id: int) -> QTextCharFormat:
        style = QTextCharFormat()
        style.setObjectType(_CARD_OBJECT)
        style.setProperty(_TITLE, title)
        style.setProperty(_DETAIL, detail)
        style.setProperty(_ACTION, action)
        style.setAnchor(True)
        style.setAnchorHref(f"score-edit:/{receipt_id}")
        style.setToolTip(f"{title} · {detail} · {action}")
        return style

    def intrinsicSize(self, document, _position, _style) -> QSizeF:
        width = document.textWidth() - 2 * document.documentMargin() - 2 * hig.ITEM_GAP
        return QSizeF(min(_CARD_MAX_WIDTH, max(80, width)), _CARD_HEIGHT)

    def drawObject(self, painter, bounds, document, _position, style) -> None:
        title, detail, action = (str(style.property(key)) for key in (_TITLE, _DETAIL, _ACTION))
        card = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.save()
        try:
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            painter.setBrush(QColor(hig.CONTROL))
            painter.setPen(QColor(hig.SEPARATOR))
            painter.drawRoundedRect(card, hig.GROUP_RADIUS, hig.GROUP_RADIUS)

            content = card.adjusted(hig.GROUP_GAP, hig.ITEM_GAP, -hig.GROUP_GAP, -hig.ITEM_GAP)
            font = QFont(document.defaultFont())
            font.setPixelSize(hig.TYPE_SECONDARY)
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            action_width = min(content.width() * 0.44, metrics.horizontalAdvance(action) + 2 * hig.ITEM_GAP)
            action_rect = QRectF(content.right() - action_width, content.center().y() - 14, action_width, 28)
            painter.setBrush(QColor(hig.SELECTION))
            painter.drawRoundedRect(action_rect, hig.CONTROL_RADIUS, hig.CONTROL_RADIUS)
            painter.setPen(QColor(hig.TEXT))
            painter.drawText(action_rect, Qt.AlignCenter, metrics.elidedText(
                action, Qt.ElideRight, max(0, action_width - hig.ITEM_GAP),
            ))

            text_width = max(0, action_rect.left() - hig.ITEM_GAP - content.left())
            title_row = QRectF(content.left(), content.top(), text_width, content.height() / 2)
            title_font = QFont(font)
            title_font.setPixelSize(hig.TYPE_BODY)
            title_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(title_font)
            painter.drawText(title_row, Qt.AlignVCenter | Qt.AlignLeft, QFontMetricsF(title_font).elidedText(
                title, Qt.ElideRight, text_width,
            ))
            painter.setFont(font)
            painter.setPen(QColor(hig.SECONDARY_TEXT))
            painter.drawText(title_row.translated(0, title_row.height()), Qt.AlignVCenter | Qt.AlignLeft,
                             metrics.elidedText(detail, Qt.ElideRight, text_width))
        finally:
            painter.restore()
