"""Title-bar feedback entry and unread marker."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy

from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol
from bdo_music_composer.ui.ui_controls import PillButton


class FeedbackToolbarButton(PillButton):
    def __init__(self) -> None:
        super().__init__(tr("反馈"), "ghost", FluentSymbol.FEEDBACK)
        self.setObjectName("ToolbarFeedback")
        self.setFixedHeight(hig.BUTTON_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._unread_count = 0
        self.retranslate_dynamic_content()

    def set_unread_count(self, count: int) -> None:
        self._unread_count = max(0, count)
        self.retranslate_dynamic_content()
        self.update()

    def retranslate_dynamic_content(self) -> None:
        label = tr("反馈")
        summary = (
            trf("{count} 条反馈有新进展", count=self._unread_count)
            if self._unread_count else ""
        )
        self.setAccessibleName(label)
        self.setAccessibleDescription(summary)
        self.setToolTip(summary or label)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._unread_count:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(hig.WINDOW_SHELL), 1))
        painter.setBrush(QColor(hig.ACCENT))
        painter.drawEllipse(QRectF(self.width() - 10, 4, 7, 7))
