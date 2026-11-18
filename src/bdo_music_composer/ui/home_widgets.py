"""Packaged Qt widgets for the project home page and toolbar identity."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.app.application_metadata import (
    RELEASE_NOTES_UI_ENABLED,
)
from bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt import InstrumentLaneArtwork
from bdo_midi import BDO_ENSEMBLE_PLAYER_LIMIT
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol
from bdo_music_composer.ui.theme.fonts_qt import ThemeTitle
from bdo_music_composer.ui.theme.symbols import draw_symbol
from bdo_music_composer.core.project_paths import ASSETS_DIR


HOME_BACKGROUND_IMAGE = (
    ASSETS_DIR / "ui" / "home" / "home_moonlit_atelier_v3.webp"
)
SHAI_ENSEMBLE_MARK_IMAGE = ASSETS_DIR / "icons" / "shai_ensemble_mark.png"
APP_ICON_IMAGE = ASSETS_DIR / "icons" / "app_icon.png"
HOME_INSTRUMENT_IDS_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class HomeLibrarySurface(QFrame):
    """Align recent projects and game scores with the command column."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeLibrarySurface")
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(hig.ITEM_GAP)


class HomeHero(QWidget):
    """Compact title block that anchors the home command column."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeHero")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.ITEM_GAP)
        title = ThemeTitle(tr("开始创作"))
        title.setObjectName("HomeTitle")
        layout.addWidget(title)
        subtitle = QLabel(tr("编排和试听多轨 MIDI，编辑音符与力度，导出黑色沙漠曲谱。"))
        subtitle.setObjectName("HomeHeroSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)


class HomeLibraryTabs(QFrame):
    """Align both library tabs with the search and refresh controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeLibraryTabs")
        self.setFixedHeight(hig.BUTTON_HEIGHT)
        self.content_layout = QHBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(hig.CONTROL_GAP)


class HomeListWidget(QListWidget):
    """Prefer the measured preview height and scroll in smaller windows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumHeight(320)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setResizeMode(self.ResizeMode.Adjust)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(self.maximumHeight())
        return hint

    def set_preview_height(self, height: int) -> None:
        self.setMinimumHeight(min(56, height))
        self.setMaximumHeight(height)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            can_activate = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if item is not None and (item.flags() & can_activate) == can_activate:
                # The first double-click must open even when Qt has no current row.
                self.setCurrentItem(item)
                event.accept()
                self.itemActivated.emit(item)
                return
        super().mouseDoubleClickEvent(event)


class HomeFooter(QWidget):
    """Public privacy footer with a dormant internal release-notes hook."""

    release_notes_requested = Signal()

    def __init__(
        self,
        version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.version = str(version)
        self.setObjectName("HomeFooter")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, hig.ITEM_GAP, 0, 0)
        layout.setSpacing(hig.ITEM_GAP)
        self.local_badge = QLabel()
        self.local_badge.setObjectName("HomeLocalBadge")
        self.local_badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.local_badge)
        layout.addStretch(1)
        self.release_notes_button = QPushButton()
        self.release_notes_button.setObjectName("HomeReleaseNotesButton")
        self.release_notes_button.setProperty("kind", "ghost")
        self.release_notes_button.setCursor(Qt.PointingHandCursor)
        self.release_notes_button.clicked.connect(
            self.release_notes_requested.emit
        )
        self.release_notes_button.setVisible(RELEASE_NOTES_UI_ENABLED)
        layout.addWidget(self.release_notes_button)
        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        self.local_badge.setText(tr("本地处理 · 不上传工程"))
        if RELEASE_NOTES_UI_ENABLED:
            self.release_notes_button.setText(
                trf("更新日志 · v{version}", version=self.version)
            )
        else:
            self.release_notes_button.setText("")


class HomeIdentityBadge(QPushButton):
    """Compact Owner-ID status entry for the home brand row."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._primary = tr("Owner ID 未设置")
        self._secondary = tr("Owner ID 未设置；点击前往设置")
        self._owner_id_bound = False
        self.setObjectName("HomeOwnerIdButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(30)
        self.setMinimumWidth(134)
        self.setMaximumWidth(180)
        self.setText(self._primary)

    def set_owner_id(self, owner_id: int) -> None:
        self._owner_id_bound = bool(owner_id)
        if self._owner_id_bound:
            self._primary = tr("Owner ID 已绑定")
            self._secondary = tr("点击头像，从游戏曲谱快速设置 Owner ID")
        else:
            self._primary = tr("Owner ID 未设置")
            self._secondary = tr("点击头像，从游戏曲谱快速设置 Owner ID")
        self.setText(self._primary)
        self.setToolTip(self._secondary)
        self.setAccessibleName(self._primary)
        self.setAccessibleDescription(self._secondary)
        missing = not self._owner_id_bound
        self.setProperty("ownerIdMissing", missing)
        # Kept for callers that used the older generic identity state.
        self.setProperty("identityMissing", missing)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(154, 30)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown() or self.underMouse() or self.hasFocus():
            painter.setBrush(
                QColor(43, 39, 32, 210)
                if self.isDown()
                else QColor(35, 33, 29, 176)
            )
            painter.setPen(QPen(QColor("#5b4c36"), 1))
            radius = hig.CONTROL_RADIUS
            painter.drawRoundedRect(bounds, radius, radius)

        # A compact anonymous avatar makes the direct identity action clear
        # without exposing the character name on the home surface.
        avatar_outline = QColor("#a68a57" if self._owner_id_bound else "#707070")
        painter.setBrush(QColor(29, 29, 29, 210))
        painter.setPen(QPen(avatar_outline, 1.1))
        painter.drawEllipse(QRectF(4.0, 3.0, 24.0, 24.0))
        painter.setBrush(avatar_outline)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(12.0, 8.0, 8.0, 8.0))
        painter.drawEllipse(QRectF(8.5, 16.0, 15.0, 8.0))

        # The status lamp is deliberately neutral while the required ID is
        # absent. It becomes green only after a valid Owner ID is loaded.
        accent = QColor("#8ead77" if self._owner_id_bound else "#777777")
        painter.setBrush(accent)
        painter.setPen(QPen(QColor("#181817"), 1))
        painter.drawEllipse(QRectF(21.0, 20.0, 7.0, 7.0))

        primary_font = QFont(painter.font())
        primary_font.setPointSize(9)
        primary_font.setBold(self._owner_id_bound)
        painter.setFont(primary_font)
        primary_rect = QRectF(
            35.0, 3.0, max(54.0, bounds.width() - 52.0), 24.0
        )
        painter.setPen(
            QColor("#e3ddd2" if self._owner_id_bound else "#999999")
        )
        painter.drawText(
            primary_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(
                self._primary, Qt.ElideRight, int(primary_rect.width())
            ),
        )
        painter.setPen(QColor("#6f6659"))
        painter.drawText(
            QRectF(bounds.right() - 16.0, 0.0, 12.0, bounds.height()),
            Qt.AlignCenter,
            "›",
        )


class EnsembleCapacityBadge(QPushButton):
    """About button with the current score's ensemble context in its description."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EnsembleCapacityBadge")
        self.setFixedSize(hig.LOGO_BUTTON_SIZE, hig.LOGO_BUTTON_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFlat(True)
        set_fluent_symbol(self, FluentSymbol.COMPOSER)
        self._keyboard_focus = False
        self._focus_icon = QIcon()
        for size in (16, 24, 32, 48):
            self._focus_icon.addPixmap(draw_symbol(FluentSymbol.COMPOSER, hig.FOCUS, size))
        self._player_count = 0
        self._description_override = ""
        self._refresh_description()

    def focusInEvent(self, event: QFocusEvent) -> None:
        if event.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            self._keyboard_focus = event.reason() in (
                Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason,
            )
        super().focusInEvent(event)

    def paintEvent(self, event) -> None:
        if not (self.hasFocus() and self._keyboard_focus):
            super().paintEvent(event)
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.icon = self._focus_icon
        painter = QStylePainter(self)
        painter.drawControl(QStyle.CE_PushButton, option)

    @property
    def player_count(self) -> int:
        return self._player_count

    @property
    def is_over_limit(self) -> bool:
        return self._player_count > BDO_ENSEMBLE_PLAYER_LIMIT

    def set_player_count(
        self,
        player_count: int,
        description_override: str = "",
    ) -> None:
        normalized = max(0, int(player_count))
        normalized_description = str(description_override or "").strip()
        if (
            normalized == self._player_count
            and normalized_description == self._description_override
        ):
            return
        self._player_count = normalized
        self._description_override = normalized_description
        self._refresh_description()

    def _refresh_description(self) -> None:
        if self._description_override:
            description = self._description_override
        elif self._player_count <= 0:
            description = tr("当前工程没有需要演奏的实体乐器")
        elif self.is_over_limit:
            description = trf(
                "当前工程预计 {count} 人演奏，超过 {limit} 人队伍上限",
                count=self._player_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        else:
            description = trf(
                "当前工程预计 {count}/{limit} 人演奏；同一实体乐器只计一人",
                count=self._player_count,
                limit=BDO_ENSEMBLE_PLAYER_LIMIT,
            )
        about = tr("关于 BDO Music Composer")
        self.setToolTip(about)
        self.setAccessibleName(about)
        self.setAccessibleDescription(description)

    def retranslate_dynamic_content(self) -> None:
        self._refresh_description()


class HomeBackdrop(QFrame):
    """An inset portrait scene set against the same matte as the home page."""

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeShell")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._source = QPixmap(str(image_path))
        self._cover = QPixmap()
        self._cover_dpr = 0.0
        self._art_rect = self._artwork_rect()
        self._resize_timer = QTimer(self, singleShot=True, interval=72)
        self._resize_timer.timeout.connect(self._refresh_cover)

    @property
    def has_artwork(self) -> bool:
        return not self._source.isNull()

    def _artwork_rect(self) -> QRect:
        side = min(hig.SECTION_GAP, self.width() // 12)
        vertical = min(hig.PANEL_PADDING, self.height() // 12)
        matte = self.rect().adjusted(side, vertical, -side, -vertical)
        if matte.isEmpty():
            return QRect()
        # Keep both the scroll and the open score visible in wide, short windows.
        art_width = min(matte.width(), round(matte.height() * 0.94))
        return QRect(
            matte.x() + (matte.width() - art_width) // 2,
            matte.y(),
            art_width,
            matte.height(),
        )

    def _refresh_cover(self) -> None:
        self._resize_timer.stop()
        self._cover_dpr = self.devicePixelRatioF()
        if self._source.isNull() or self._art_rect.isEmpty():
            self._cover = QPixmap()
            return
        view = self._art_rect.size() * self._cover_dpr
        scaled = self._source.scaled(
            view,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        source_x = max(0, scaled.width() - view.width())
        source_y = max(0, round((scaled.height() - view.height()) * 0.56))
        rect = QRect(QPoint(), self._art_rect.size())
        canvas = QColor(hig.CANVAS)
        self._cover = QPixmap(view)
        self._cover.setDevicePixelRatio(self._cover_dpr)
        self._cover.fill(canvas)
        with QPainter(self._cover) as painter:
            painter.drawPixmap(rect, scaled, QRect(source_x, source_y, view.width(), view.height()))
            self._paint_feathered_edges(painter, QRectF(rect), canvas)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._art_rect = self._artwork_rect()
        if self._cover.isNull() or not event.oldSize().isValid():
            self._refresh_cover()
        else:
            # Reuse the last composited crop while the native resize grip is
            # moving. The expensive smooth scale runs once per settled size.
            self._resize_timer.start()

    def paintEvent(self, event) -> None:
        del event
        if self.devicePixelRatioF() != self._cover_dpr:
            self._refresh_cover()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(hig.CANVAS))
        if not self._cover.isNull():
            painter.drawPixmap(self._art_rect, self._cover)

    @staticmethod
    def _paint_feathered_edges(painter: QPainter, art: QRectF, canvas: QColor) -> None:
        left, top, right, bottom = art.left(), art.top(), art.right(), art.bottom()
        lead = min(120.0, art.width() * 0.22)
        trail = min(42.0, art.width() * 0.08)
        upper = min(50.0, art.height() * 0.08)
        lower = min(76.0, art.height() * 0.11)
        bands = (
            (QRectF(left, top, lead, art.height()), QLinearGradient(left, 0, left + lead, 0)),
            (QRectF(right - trail, top, trail, art.height()), QLinearGradient(right, 0, right - trail, 0)),
            (QRectF(left, top, art.width(), upper), QLinearGradient(0, top, 0, top + upper)),
            (QRectF(left, bottom - lower, art.width(), lower), QLinearGradient(0, bottom, 0, bottom - lower)),
        )
        for band, blend in bands:
            blend.setColorAt(0.0, canvas)
            for position, alpha in ((0.26, 207), (0.72, 48), (1.0, 0)):
                tint = QColor(canvas)
                tint.setAlpha(alpha)
                blend.setColorAt(position, tint)
            painter.fillRect(band, blend)


class HomeEntryDelegate(QStyledItemDelegate):
    """Paint compact library rows with optional instrument art."""

    def __init__(
        self,
        artwork: InstrumentLaneArtwork | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.artwork = artwork

    @staticmethod
    def _row_fonts(base_font: QFont) -> tuple[QFont, QFont]:
        label_font = QFont(base_font)
        label_font.setPixelSize(hig.TYPE_BODY)
        label_font.setWeight(QFont.Weight.DemiBold)
        detail_font = QFont(base_font)
        detail_font.setPixelSize(hig.TYPE_SECONDARY)
        detail_font.setWeight(QFont.Weight.Normal)
        return label_font, detail_font

    @staticmethod
    def _ensemble_text(instrument_count: int) -> str:
        if instrument_count <= 0:
            return ""
        if instrument_count <= BDO_ENSEMBLE_PLAYER_LIMIT:
            return trf("{count} 人", count=instrument_count)
        return trf(
            "上限 {limit} 人",
            limit=BDO_ENSEMBLE_PLAYER_LIMIT,
        )

    def sizeHint(self, option, index) -> QSize:
        explicit = index.data(Qt.ItemDataRole.SizeHintRole)
        if isinstance(explicit, QSize):
            return explicit
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        inherited = super().sizeHint(styled, index)
        if not index.flags() & Qt.ItemFlag.ItemIsSelectable:
            return QSize(inherited.width(), max(40, QFontMetrics(styled.font).height() + 16))
        label_font, detail_font = self._row_fonts(styled.font)
        title_height = QFontMetrics(label_font).height()
        info_height = max(QFontMetrics(detail_font).height() + 2, 20)
        return QSize(
            inherited.width(),
            max(56, 8 + title_height + 5 + info_height + 8),
        )

    def paint(self, painter: QPainter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = str(index.data(Qt.DisplayRole) or "")
        styled.text = ""
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            styled,
            painter,
            styled.widget,
        )

        if not index.flags() & Qt.ItemFlag.ItemIsSelectable:
            painter.save()
            painter.setFont(styled.font)
            painter.setPen(QColor(hig.SECONDARY_TEXT))
            painter.drawText(option.rect.adjusted(12, 0, -10, 0), Qt.AlignVCenter, text)
            painter.restore()
            return

        raw_ids = index.data(HOME_INSTRUMENT_IDS_ROLE)
        instrument_ids = tuple(raw_ids) if isinstance(raw_ids, (list, tuple)) else ()
        max_icons = 3
        visible_ids = instrument_ids[:max_icons]
        overflow = max(0, len(instrument_ids) - len(visible_ids))
        icon_size = 20.0
        icon_gap = 4.0
        icon_slots = len(visible_ids) + int(overflow > 0)
        icon_width = (
            icon_slots * icon_size + max(0, icon_slots - 1) * icon_gap
            if icon_slots
            else 0.0
        )

        content = QRectF(option.rect).adjusted(12.0, 8.0, -10.0, -8.0)
        player_text = self._ensemble_text(len(instrument_ids))
        label_font, detail_font = self._row_fonts(styled.font)
        player_font = detail_font
        painter.save()
        painter.setFont(player_font)
        player_width = (
            float(painter.fontMetrics().horizontalAdvance(player_text)) + 4.0
            if player_text
            else 0.0
        )
        painter.restore()
        right_width = icon_width + player_width
        if icon_slots and player_text:
            right_width += 10.0
        label, _separator, detail = text.partition("\n")
        selected = bool(
            option.state & QStyle.StateFlag.State_Selected
        )

        painter.save()
        painter.setFont(label_font)
        label_color = hig.SELECTION_TEXT if selected else hig.TEXT
        painter.setPen(QColor(label_color))
        title_metrics = painter.fontMetrics()
        label_height = float(title_metrics.height())
        title_rect = QRectF(
            content.left(),
            content.top(),
            content.width(),
            label_height,
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                label, Qt.TextElideMode.ElideRight, max(0, round(content.width())),
            ),
        )

        painter.setFont(detail_font)
        painter.setPen(QColor(hig.SECONDARY_TEXT))
        detail_metrics = painter.fontMetrics()
        info_top = title_rect.bottom() + 4.0
        info_height = max(
            float(detail_metrics.height() + 2),
            icon_size,
        )
        detail_right = content.right() - right_width - (12.0 if right_width else 0.0)
        detail_rect = QRectF(
            content.left(),
            info_top,
            max(24.0, detail_right - content.left()),
            info_height,
        )
        painter.drawText(
            detail_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                detail,
                Qt.TextElideMode.ElideRight,
                max(0, round(detail_rect.width())),
            ),
        )

        icon_x = content.right() - player_width - icon_width
        if player_text:
            icon_x -= 10.0 if icon_slots else 0.0
        icon_y = info_top + (info_height - icon_size) * 0.5
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for instrument_id in visible_ids:
            target = QRectF(icon_x, icon_y, icon_size, icon_size)
            image = self.artwork.pixmap_for(int(instrument_id)) if self.artwork is not None else None
            if image is not None:
                painter.setOpacity(0.78 if selected else 0.62)
                painter.drawImage(target, image, QRectF(image.rect()))
            else:
                painter.setOpacity(0.74)
                painter.setPen(QColor("#d7b15a"))
                painter.drawText(
                    target,
                    Qt.AlignmentFlag.AlignCenter,
                    f"{int(instrument_id):02X}",
                )
            icon_x += icon_size + icon_gap
        if overflow:
            painter.setOpacity(1.0)
            painter.setPen(QColor("#c7b78f"))
            painter.drawText(
                QRectF(icon_x, icon_y, icon_size, icon_size),
                Qt.AlignmentFlag.AlignCenter,
                f"+{overflow}",
            )
        if player_text:
            painter.setOpacity(1.0)
            painter.setFont(player_font)
            painter.setPen(QColor(hig.SELECTION_TEXT if selected else hig.SECONDARY_TEXT))
            painter.drawText(
                QRectF(
                    content.right() - player_width,
                    info_top,
                    player_width,
                    info_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                player_text,
            )
        painter.restore()


__all__ = [
    "APP_ICON_IMAGE",
    "HOME_BACKGROUND_IMAGE",
    "HOME_INSTRUMENT_IDS_ROLE",
    "SHAI_ENSEMBLE_MARK_IMAGE",
    "EnsembleCapacityBadge",
    "HomeBackdrop",
    "HomeEntryDelegate",
    "HomeFooter",
    "HomeHero",
    "HomeIdentityBadge",
    "HomeLibrarySurface",
    "HomeLibraryTabs",
    "HomeListWidget",
]
