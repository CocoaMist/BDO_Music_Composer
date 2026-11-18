"""Local profiles and build information for the toolbar logo."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QPixmapCache, QRadialGradient
from PySide6.QtWidgets import (
    QBoxLayout, QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from bdo_music_composer.app.application_metadata import (
    APP_AUTHOR_NAME,
    APP_DISPLAY_VERSION,
    APP_NAME,
    GITHUB_OWNER,
)
from bdo_music_composer.core.project_paths import ASSETS_DIR
from bdo_music_composer.ui.dialogs.acknowledgements_dialog import AcknowledgementsPane
from bdo_music_composer.ui.floating_panel_qt import FloatingPanelDialog
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol
from bdo_music_composer.ui.ui_controls import PillButton


APP_MARK_IMAGE = ASSETS_DIR / "icons" / "app_icon.png"
AUTHOR_AVATAR_IMAGE = ASSETS_DIR / "ui" / "about" / "cocoamist_avatar.webp"
CHATGPT_AVATAR_IMAGE = ASSETS_DIR / "ui" / "about" / "chatgpt_avatar.webp"
APP_MARK_SIZE = 40
AUTHOR_PORTRAIT_SIZE = 400
COLLABORATOR_MARK_SIZE = 36
AUTHOR_COLUMNS_WIDTH = 620
COLLABORATOR_COLUMNS_WIDTH = 544


def _profile_mark(path: Path, size: int, pixel_ratio: float) -> QPixmap:
    key = f"bdo.about.{path.stem}.{size}.{pixel_ratio}"
    cached = QPixmapCache.find(key)
    if cached is not None:
        return cached

    image = QPixmap(str(path))
    if not image.isNull():
        edge = round(size * pixel_ratio)
        image = image.scaled(edge, edge, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image.setDevicePixelRatio(pixel_ratio)
        QPixmapCache.insert(key, image)
    return image


def _portrait(path: Path, size: int, pixel_ratio: float) -> QLabel:
    portrait = QLabel()
    portrait.setObjectName("AboutProfilePortrait")
    portrait.setFixedSize(size, size)
    portrait.setAlignment(Qt.AlignCenter)
    mark = _profile_mark(path, size, pixel_ratio)
    if not mark.isNull():
        portrait.setPixmap(mark)
    return portrait


def _profile_details(layout: QVBoxLayout, role: str, description: str) -> None:
    role_label = QLabel(role)
    role_label.setObjectName("AboutProfileRole")
    role_label.setWordWrap(True)
    layout.addWidget(role_label)

    summary = QLabel(description)
    summary.setObjectName("AboutProfileSummary")
    summary.setWordWrap(True)
    layout.addWidget(summary)


def _collaborator(
    name: str, role: str, description: str, portrait: QLabel,
) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(hig.GROUP_GAP)
    layout.addWidget(portrait, 0, Qt.AlignTop)
    details = QVBoxLayout()
    details.setSpacing(hig.CONTROL_GAP)
    name_label = QLabel(name)
    name_label.setObjectName("AboutProfileName")
    details.addWidget(name_label)
    _profile_details(details, role, description)
    details.addStretch(1)
    layout.addLayout(details, 1)
    return layout


class _AuthorPortrait(QWidget):
    def __init__(self, pixel_ratio: float) -> None:
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMinimumHeight(262)
        self.setMaximumHeight(420)
        self._portrait = _profile_mark(AUTHOR_AVATAR_IMAGE, AUTHOR_PORTRAIT_SIZE, pixel_ratio)

    def paintEvent(self, event) -> None:
        if self._portrait.isNull():
            return
        area = QRectF(self.rect())
        panel = QColor(hig.PANEL)
        clear = QColor(panel)
        clear.setAlpha(0)
        wash = QRadialGradient(
            QPointF(area.width() * 0.62, area.height() * 0.44),
            max(area.width() * 0.63, area.height() * 0.75),
        )
        wash.setColorAt(0.0, QColor("#3b423a"))
        wash.setColorAt(0.65, QColor("#2a2e2a"))
        wash.setColorAt(1.0, panel)
        side = min(area.width(), area.height() * 1.18)
        picture = QRectF(
            max(0.0, (area.width() - side) * 0.8), 0, side, side,
        )
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.fillRect(area, wash)
            painter.drawPixmap(picture, self._portrait, QRectF(self._portrait.rect()))
            for gradient in (
                QLinearGradient(0, 0, area.width() * 0.30, 0),
                QLinearGradient(area.right(), 0, area.width() * 0.84, 0),
                QLinearGradient(0, 0, 0, area.height() * 0.09),
                QLinearGradient(0, area.bottom(), 0, area.height() * 0.62),
            ):
                gradient.setColorAt(0, panel)
                gradient.setColorAt(1, clear)
                painter.fillRect(area, gradient)


class _AuthorPage(QScrollArea):
    def __init__(self, pixel_ratio: float) -> None:
        super().__init__()
        self.setObjectName("AboutAuthorsScroll")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("AboutAuthorsBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.SECTION_GAP, hig.PANEL_PADDING)
        content.setSpacing(hig.PANEL_PADDING)

        self._author = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._author.setSpacing(hig.PANEL_PADDING)
        details = QVBoxLayout()
        details.setSpacing(hig.CONTROL_GAP)
        details.addStretch(1)
        name = QLabel(APP_AUTHOR_NAME)
        name.setObjectName("AboutAuthorName")
        details.addWidget(name)
        _profile_details(
            details,
            trf("项目作者 · {handle}", handle=GITHUB_OWNER),
            tr("我做这个工具，是想让《黑色沙漠》的作曲玩家能在本地编曲和试听，再把曲谱带回游戏一起演奏。"),
        )
        details.addStretch(1)
        self._author.addLayout(details, 1)
        self._artwork = _AuthorPortrait(pixel_ratio)
        self._author.addWidget(self._artwork, 1)
        content.addLayout(self._author, 1)

        deepseek_mark = QLabel("D")
        deepseek_mark.setObjectName("AboutModelMark")
        deepseek_mark.setFixedSize(COLLABORATOR_MARK_SIZE, COLLABORATOR_MARK_SIZE)
        deepseek_mark.setAlignment(Qt.AlignCenter)
        self._collaborators = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._collaborators.setSpacing(hig.PANEL_PADDING)
        self._collaborators.addLayout(_collaborator(
            "ChatGPT",
            tr("开发协作"),
            tr("协助界面设计、代码实现与测试。"),
            _portrait(CHATGPT_AVATAR_IMAGE, COLLABORATOR_MARK_SIZE, pixel_ratio),
        ), stretch=1)
        self._collaborators.addLayout(_collaborator(
            "DeepSeek",
            tr("曲谱助手模型"),
            tr("配置后可用于对话和曲谱分析。"),
            deepseek_mark,
        ), stretch=1)
        content.addLayout(self._collaborators)

        summary = QLabel(tr("在多轨时间轴和钢琴卷帘编辑 MIDI、试听编排，并导出 BDO v9 曲谱。"))
        summary.setObjectName("AboutProfileRole")
        summary.setWordWrap(True)
        content.addWidget(summary)
        content.addStretch(1)
        self.setWidget(body)
        self.viewport().setAutoFillBackground(False)

    def resizeEvent(self, event) -> None:
        stacked = self.width() < AUTHOR_COLUMNS_WIDTH
        author_direction = QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        direction = (
            QBoxLayout.Direction.LeftToRight if self.width() >= COLLABORATOR_COLUMNS_WIDTH
            else QBoxLayout.Direction.TopToBottom
        )
        if self._author.direction() != author_direction or self._collaborators.direction() != direction:
            self._author.setDirection(author_direction)
            self._artwork.setMinimumHeight(180 if stacked else 262)
            self._artwork.setMaximumHeight(210 if stacked else 420)
            self._collaborators.setDirection(direction)
            self.widget().layout().activate()
        super().resizeEvent(event)


class AboutDialog(FloatingPanelDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AboutDialog")
        self.setWindowTitle(tr("关于 BDO Music Composer"))
        self.setMinimumSize(440, 340)
        self.setFocusPolicy(Qt.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, hig.ITEM_GAP)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.PANEL_PADDING, hig.ITEM_GAP)
        header.setSpacing(hig.GROUP_GAP)
        header.addWidget(_portrait(APP_MARK_IMAGE, APP_MARK_SIZE, self.devicePixelRatioF()), 0, Qt.AlignVCenter)

        identity = QVBoxLayout()
        identity.setSpacing(hig.CONTROL_GAP)
        title = QLabel(APP_NAME)
        title.setObjectName("AboutTitle")
        version = QLabel(trf("版本 {version}", version=APP_DISPLAY_VERSION))
        version.setObjectName("AboutProfileRole")
        identity.addWidget(title)
        identity.addWidget(version)
        header.addLayout(identity, 1)

        close = PillButton("", "ghost", FluentSymbol.CLOSE)
        close.setObjectName("FloatingPanelClose")
        close.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close.setAutoDefault(False)
        close.setAccessibleName(tr("关闭窗口"))
        close.setToolTip(tr("关闭窗口"))
        close.clicked.connect(self.reject)
        header.addWidget(close, 0, Qt.AlignTop)
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.setObjectName("AboutTabs")
        tabs.setDocumentMode(True)
        tabs.addTab(_AuthorPage(self.devicePixelRatioF()), tr("作者介绍"))
        credits = AcknowledgementsPane(
            dark_theme=self.palette().window().color().lightness() < 128,
            defer_document=True,
        )
        credits.layout().setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.SECTION_GAP, hig.PANEL_PADDING)
        credits.credits_browser.document().setDocumentMargin(0)
        copy = PillButton(tr("复制致谢名单"), "ghost")
        copy.setObjectName("AboutCopyCredits")
        copy.setAutoDefault(False)
        copy.setToolTip(tr("复制为纯文本，便于放入项目说明或发布页面"))
        copy.clicked.connect(credits.copy_credits)
        credits.layout().addWidget(copy, 0, Qt.AlignRight)
        tabs.addTab(credits, tr("致谢"))
        layout.addWidget(tabs, stretch=1)
        self.resize(800, 520)
        self.setFocus(Qt.OtherFocusReason)
