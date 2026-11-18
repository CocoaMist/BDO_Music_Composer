"""First-run Home, including the optional usage-report choice."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt, QTimeZone, Signal
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QHBoxLayout, QLabel, QLayout, QScrollArea,
    QVBoxLayout, QWidget,
)

from bdo_music_composer.app.application_metadata import APP_NAME
from bdo_music_composer.ui.home_widgets import HOME_BACKGROUND_IMAGE, HomeBackdrop
from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.symbols import FluentSymbol, draw_symbol
from bdo_music_composer.ui.ui_controls import PillButton


WELCOME_TITLE = "欢迎使用 BDO Music Composer"
TELEMETRY_TITLE = "匿名使用统计"
TELEMETRY_CONTENT = "统计系统版本、CPU 线程与内存档位、功能与导出次数、错误类别。"
TELEMETRY_INSTALL_ID = "随机安装编号用于合并同一安装的统计。"
TELEMETRY_EXCLUSIONS = "统计内容不包含曲谱、音符、文件名、路径、Owner ID 或 IP 地址。"
TIME_ZONE_LABEL = "系统时区"
TIME_ZONE_NOTE = "自动读取系统设置，仅在本机显示。"


def system_time_zone_label() -> str:
    """Display the operating system's time zone and current UTC offset."""
    zone_id = bytes(QTimeZone.systemTimeZoneId()).decode("utf-8", errors="replace")
    offset = QDateTime.currentDateTime().offsetFromUtc()
    hours, minutes = divmod(abs(offset) // 60, 60)
    sign = "-" if offset < 0 else "+"
    offset_label = f"UTC{sign}{hours:02d}:{minutes:02d}"
    return f"{zone_id} · {offset_label}" if zone_id else offset_label


def _copy(source: str, object_name: str = "WelcomeCopy") -> QLabel:
    label = QLabel(tr(source))
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class HomeWelcomePage(QWidget):
    """Let the user make an explicit consent choice in the home window."""

    decision_requested = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeWelcomePage")
        self.setAccessibleName(tr(WELCOME_TITLE))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(hig.PAGE_PADDING, 0, hig.PAGE_PADDING, hig.PANEL_PADDING)
        layout.setSpacing(hig.GROUP_GAP)
        body = QHBoxLayout()
        body.setSpacing(hig.SECTION_GAP)
        scroll = QScrollArea()
        scroll.setObjectName("HomeWelcomeScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMaximumWidth(640)
        column = QWidget()
        column.setObjectName("HomeWelcomeBody")
        content = QVBoxLayout(column)
        content.setContentsMargins(0, hig.PAGE_PADDING + hig.ITEM_GAP, hig.ITEM_GAP, hig.PANEL_PADDING)
        content.setSpacing(hig.ITEM_GAP)
        content.addWidget(_copy(WELCOME_TITLE, "WelcomeTitle"))
        content.addWidget(_copy("编排和试听多轨 MIDI，编辑音符与力度，导出黑色沙漠曲谱。", "WelcomeLead"))
        content.addSpacing(hig.SECTION_GAP)

        statistics = QVBoxLayout()
        statistics.setSpacing(hig.CONTROL_GAP)
        statistics.addWidget(_copy(TELEMETRY_TITLE, "WelcomeSection"))
        statistics.addWidget(_copy("你可以分享统计，帮助我们了解常用功能和需要修复的问题。"))
        statistics.addSpacing(hig.CONTROL_GAP)
        statistics.addWidget(_copy(TELEMETRY_CONTENT))
        statistics.addWidget(_copy(TELEMETRY_INSTALL_ID))
        statistics.addWidget(_copy(TELEMETRY_EXCLUSIONS))
        statistics.addSpacing(hig.CONTROL_GAP)
        statistics.addWidget(_copy("可随时在「设置 → 隐私」更改分享选择。"))
        content.addLayout(statistics)

        content.addSpacing(hig.GROUP_GAP)
        reading_rule = QFrame()
        reading_rule.setObjectName("HomeWelcomeRule")
        reading_rule.setFixedHeight(1)
        content.addWidget(reading_rule)
        local = QVBoxLayout()
        local.setSpacing(hig.CONTROL_GAP)
        local.addWidget(_copy(TIME_ZONE_LABEL, "WelcomeTimeZoneLabel"))
        zone_text = _copy(system_time_zone_label(), "WelcomeSystemTimeZone")
        zone_text.setProperty("i18nSkipText", True)
        local.addWidget(zone_text)
        local.addWidget(_copy(TIME_ZONE_NOTE))
        content.addLayout(local)
        content.addStretch(1)
        scroll.setWidget(column)
        self.artwork = HomeBackdrop(HOME_BACKGROUND_IMAGE)
        body.addWidget(scroll, 5)
        body.addWidget(self.artwork, 4)
        layout.addLayout(body, 1)

        rule = QFrame()
        rule.setObjectName("HomeWelcomeRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        self._footer = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._footer.setSpacing(hig.GROUP_GAP)
        brand = QHBoxLayout()
        brand.setSpacing(hig.ITEM_GAP)
        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scale = self.devicePixelRatioF()
        logo = draw_symbol(FluentSymbol.COMPOSER, hig.TEXT, round(23 * scale))
        logo.setDevicePixelRatio(scale)
        mark.setPixmap(logo)
        brand.addWidget(mark)
        name = QLabel(APP_NAME)
        name.setObjectName("WelcomeBrand")
        brand.addWidget(name)
        brand.addStretch(1)
        self._footer.addLayout(brand, 1)
        actions_panel = QWidget()
        actions_panel.setMaximumWidth(480)
        self._actions = QBoxLayout(QBoxLayout.Direction.LeftToRight, actions_panel)
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(hig.ITEM_GAP)
        self.decline_button = PillButton(tr("继续使用，无需分享"))
        self.join_button = PillButton(tr("同意分享并继续"))
        for button in (self.decline_button, self.join_button):
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setFixedHeight(hig.PAGE_ACTION_HEIGHT)
            self._actions.addWidget(button, stretch=1)
        self._footer.addWidget(actions_panel, 1)
        layout.addLayout(self._footer)
        self.setTabOrder(self.decline_button, self.join_button)
        self.decline_button.clicked.connect(lambda: self.decision_requested.emit(False))
        self.join_button.clicked.connect(lambda: self.decision_requested.emit(True))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = event.size().width()
        margin = hig.PAGE_PADDING if width >= 600 else hig.PANEL_PADDING
        self.layout().setContentsMargins(margin, 0, margin, hig.PANEL_PADDING)
        self.artwork.setVisible(width >= 840 and self.artwork.has_artwork)
        action_width = max(self.decline_button.sizeHint().width(), self.join_button.sizeHint().width())
        for button in (self.decline_button, self.join_button):
            button.setMinimumWidth(action_width)
        action_inline = width - 2 * margin >= 2 * action_width + self._actions.spacing()
        self._actions.setDirection(
            QBoxLayout.Direction.LeftToRight if action_inline else QBoxLayout.Direction.TopToBottom
        )
        left = self._footer.itemAt(0).minimumSize().width()
        right = self._footer.itemAt(1).minimumSize().width()
        inline = action_inline and width - 2 * margin >= left + right + self._footer.spacing()
        self._footer.setDirection(
            QBoxLayout.Direction.LeftToRight if inline else QBoxLayout.Direction.TopToBottom
        )
