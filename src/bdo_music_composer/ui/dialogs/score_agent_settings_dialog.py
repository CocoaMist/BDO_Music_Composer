"""Floating DeepSeek model and connection settings."""

from __future__ import annotations

from dataclasses import replace
from html import escape
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionComboBox, QTabBar, QToolButton, QVBoxLayout, QWidget,
)
from bdo_music_composer.app.score_agent_settings import (
    DEEPSEEK_MODEL_NAMES, DEEPSEEK_MODELS, DEEPSEEK_REASONING_EFFORTS, DEFAULT_BASE_URL,
    DEFAULT_MODEL, DEFAULT_REASONING_EFFORT, MAX_API_KEY_LENGTH, MAX_BASE_URL_LENGTH, MAX_MODEL_LENGTH,
    ModelConnection, can_remember_model_connection, canonical_model_id,
    clear_saved_model_connection, is_loopback_base_url, load_saved_model_connection,
    model_connection_path, normalize_api_key, normalize_base_url, save_model_connection,
)
from bdo_music_composer.core.project_paths import ASSETS_DIR
from bdo_music_composer.ui.floating_panel_qt import FloatingPanelDialog, exec_floating_panel
from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.score_agent_catalog_qt import ModelCatalogCheck
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol
from bdo_music_composer.ui.theme.symbols import draw_symbol
from bdo_music_composer.ui.ui_controls import ElidedCheckBox, ElidedComboBox, PillButton


_CATALOG_STATUS = {
    "invalid_connection": "请输入可用的 API 地址。",
    "no_catalog": "服务未提供模型目录。",
    "invalid_response": "无法读取服务返回的模型目录。",
    "authentication": "模型服务未接受此密钥。",
    "billing": "模型服务余额不足或需要账单设置。",
    "rate_limited": "模型服务正在限流，请稍后再试。",
    "service_unavailable": "模型服务暂不可用，请稍后再试。",
    "redirected": "服务返回了重定向。请直接填写最终 API 地址。",
    "timeout": "连接测试超时，请检查网络或 API 地址。",
    "failed": "无法连接模型服务，请检查网络或 API 地址。",
}

_MODES = {
    "fast": "快速回复",
    "low": "低强度推理",
    "high": "高强度推理",
    "max": "最高强度推理",
}

_PORTRAIT_PATH = ASSETS_DIR / "ui" / "score_agent_portrait.webp"
_STACKED_LAYOUT_WIDTH = 655
_ARTWORK_WIDTH = 216
_CUSTOM_ENDPOINTS = (
    ("OpenAI 兼容接口", ""),
    ("Ollama", "http://127.0.0.1:11434/v1"),
    ("LM Studio", "http://127.0.0.1:1234/v1"),
)

_PICKER_STYLE = f"""
QDialog#ScoreAgentSettingsDialog {{
    background: {hig.PANEL};
    border: 1px solid {hig.WINDOW_OUTLINE};
    border-radius: {hig.PANEL_RADIUS}px;
}}
QDialog#ScoreAgentSettingsDialog QFrame[uiRole="dialogHeader"] {{
    background: {hig.PANEL};
    border: none;
    border-top-left-radius: {hig.PANEL_INNER_RADIUS}px;
    border-top-right-radius: {hig.PANEL_INNER_RADIUS}px;
}}
QDialog#ScoreAgentSettingsDialog QFrame[uiRole="dialogFooter"] {{
    background: {hig.PANEL};
    border-top: 1px solid {hig.SEPARATOR};
    border-bottom-left-radius: {hig.PANEL_INNER_RADIUS}px;
    border-bottom-right-radius: {hig.PANEL_INNER_RADIUS}px;
}}
QScrollArea#ScoreAgentSettingsScroll, QWidget#ScoreAgentSettingsBody {{
    background: {hig.PANEL};
    border: 0;
}}
QLabel#ScoreAgentSettingsSection {{
    color: {hig.SECONDARY_TEXT};
    font-size: {hig.TYPE_BODY}px;
}}
QTabBar#ScoreAgentProvider {{
    background: {hig.CANVAS};
    border: 1px solid {hig.SEPARATOR};
    border-radius: 8px;
    padding: 3px;
}}
QTabBar#ScoreAgentProvider::tab {{
    min-height: 27px;
    color: {hig.SECONDARY_TEXT};
    background: transparent;
    border: 1px solid transparent;
    border-radius: {hig.CONTROL_RADIUS}px;
    padding: 0 14px;
}}
QTabBar#ScoreAgentProvider::tab:hover {{
    color: {hig.TEXT};
    background: {hig.CONTROL};
}}
QTabBar#ScoreAgentProvider::tab:selected {{
    color: {hig.TEXT};
    background: {hig.SELECTION};
    border-color: {hig.SEPARATOR};
}}
QTabBar#ScoreAgentProvider::tab:selected:focus {{
    border-color: {hig.FOCUS};
}}
QWidget#ScoreAgentSettingsFields QComboBox, QWidget#ScoreAgentSettingsFields QLineEdit {{
    min-height: 26px;
    border-color: {hig.SEPARATOR};
}}
QWidget#ScoreAgentSettingsFields QComboBox:hover, QWidget#ScoreAgentSettingsFields QLineEdit:hover {{
    border-color: {hig.CONTROL_BORDER};
}}
QWidget#ScoreAgentSettingsFields QComboBox:focus, QWidget#ScoreAgentSettingsFields QLineEdit:focus {{
    border-color: {hig.FOCUS};
}}
QComboBox#ScoreAgentSelect::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    background: transparent;
}}
QComboBox#ScoreAgentSelect::down-arrow {{ width: 0; height: 0; }}
QComboBox#ScoreAgentSelect:editable QLineEdit {{
    border: 0;
    padding: 0;
    min-height: 0;
    background: transparent;
}}
QComboBox#ScoreAgentSelect QAbstractItemView::item:selected {{
    color: {hig.SELECTION_TEXT};
    background: {hig.SELECTION};
}}
QPushButton#ScoreAgentQuietAction, QToolButton#ScoreAgentQuietAction {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {hig.CONTROL_RADIUS}px;
    color: {hig.SECONDARY_TEXT};
    padding: 3px {hig.ITEM_GAP}px;
}}
QPushButton#ScoreAgentQuietAction:enabled:hover, QToolButton#ScoreAgentQuietAction:enabled:hover {{
    background: {hig.CONTROL_HOVER};
    color: {hig.TEXT};
}}
QPushButton#ScoreAgentQuietAction:focus, QToolButton#ScoreAgentQuietAction:focus {{
    border-color: {hig.FOCUS};
}}
QPushButton#ScoreAgentQuietAction:disabled {{ color: {hig.DISABLED_TEXT}; }}
QFrame#ScoreAgentConnectionOptions {{
    border-top: 1px solid {hig.SEPARATOR};
}}
QLabel#ScoreAgentOfficialEndpoint {{
    color: {hig.SECONDARY_TEXT};
    font-size: {hig.TYPE_SECONDARY}px;
}}
QPushButton#ScoreAgentApply {{
    background: {hig.ACCENT};
    border-color: {hig.ACCENT};
    color: {hig.ACCENT_TEXT};
}}
QPushButton#ScoreAgentApply:hover {{
    background: {hig.ACCENT_HOVER};
    border-color: {hig.ACCENT_HOVER};
}}
QPushButton#ScoreAgentApply:pressed {{
    background: {hig.ACCENT_PRESSED};
    border-color: {hig.ACCENT_PRESSED};
}}
QPushButton#ScoreAgentApply:focus {{
    border-color: {hig.FOCUS};
}}
QDialog#ScoreAgentSettingsDialog QPushButton#FloatingPanelClose {{
    background: transparent;
    border-color: transparent;
}}
QDialog#ScoreAgentSettingsDialog QPushButton#FloatingPanelClose:hover {{
    background: {hig.CONTROL_HOVER};
}}
QDialog#ScoreAgentSettingsDialog QPushButton#FloatingPanelClose:focus {{
    border-color: {hig.FOCUS};
}}
"""


class _ModelArtwork(QWidget):
    """Draw the shared portrait into a rounded, responsive viewport."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ScoreAgentModelArtwork")
        self._portrait = QPixmap(str(_PORTRAIT_PATH))
        self._stacked = False
        self.set_stacked(False)

    def set_stacked(self, stacked: bool) -> None:
        self._stacked = stacked
        height_policy = QSizePolicy.Policy.Fixed if stacked else QSizePolicy.Policy.Expanding
        self.setSizePolicy(QSizePolicy.Policy.Preferred, height_policy)
        if stacked:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
        else:
            self.setFixedWidth(_ARTWORK_WIDTH)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_ARTWORK_WIDTH, 78 if self._stacked else 285)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 78) if self._stacked else QSize(_ARTWORK_WIDTH, 255)

    def paintEvent(self, event) -> None:
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if bounds.isEmpty():
            return
        surface = QPainterPath()
        surface.addRoundedRect(bounds, hig.PANEL_INNER_RADIUS, hig.PANEL_INNER_RADIUS)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.fillPath(surface, QColor(hig.CANVAS))
            pixmap = self._portrait
            if not pixmap.isNull():
                ratio = bounds.width() / bounds.height()
                width = min(pixmap.width(), pixmap.height() * ratio)
                height = min(pixmap.height(), pixmap.width() / ratio)
                source = QRectF(
                    (pixmap.width() - width) / 2,
                    (pixmap.height() - height) * (0.28 if self._stacked else 0.43),
                    width,
                    height,
                )
                painter.setClipPath(surface)
                painter.drawPixmap(bounds, pixmap, source)
                painter.setClipping(False)
            painter.setPen(QColor(hig.WINDOW_OUTLINE))
            painter.drawPath(surface)


class _PickerCombo(ElidedComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ScoreAgentSelect")
        self._chevron = draw_symbol(FluentSymbol.CHEVRON_DOWN, hig.SECONDARY_TEXT, 12)

    def refresh_text_tooltip(self) -> None:
        text = self.currentText()
        self.setToolTip(f"<qt>{escape(text)}</qt>" if text else "")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self)
        with QPainter(self) as painter:
            painter.drawPixmap(arrow.center() - self._chevron.rect().center(), self._chevron)


class ScoreAgentSettingsDialog(FloatingPanelDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        connection: ModelConnection | None = None,
        profile_path: Path | None = None,
    ) -> None:
        # A detached chat already occupies a small tool window. Center its
        # modal settings over the editor so model and connection controls fit.
        owner = parent.window() if parent is not None else None
        if owner is not None and owner.windowType() == Qt.WindowType.Tool:
            workspace = owner.parentWidget()
            if workspace is not None:
                parent = workspace.window()
        super().__init__(parent)
        self.connection = connection
        self._profile_path = profile_path or model_connection_path()
        self._remember_supported = can_remember_model_connection()
        self._catalog_check: ModelCatalogCheck | None = None
        self._catalog_dirty = True
        self._official = connection is None or connection.is_official_deepseek
        self._input_base: str | None = connection.base_url if connection else DEFAULT_BASE_URL
        self._catalog_timer = QTimer(self)
        self._catalog_timer.setSingleShot(True)
        self._catalog_timer.setInterval(250)
        self._catalog_timer.timeout.connect(self._refresh_catalog)
        self.setObjectName("ScoreAgentSettingsDialog")
        self.setProperty("uiSurface", "utility")
        self.setWindowTitle(tr("模型设置"))
        self.setModal(True)
        self.setMinimumSize(400, 320)
        self.resize(736, 456)
        self.setStyleSheet(_PICKER_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        root.addWidget(self._header())

        scroll = QScrollArea(self)
        scroll.setObjectName("ScoreAgentSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ScoreAgentSettingsBody")
        self._body_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, body)
        self._body_layout.setContentsMargins(hig.SECTION_GAP, hig.CONTROL_GAP, hig.SECTION_GAP, hig.PANEL_PADDING)
        self._body_layout.setSpacing(hig.SECTION_GAP)
        self._artwork = _ModelArtwork(body)
        self._body_layout.addWidget(self._artwork)
        self._body_layout.addWidget(self._fields(body), 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QFrame(self)
        footer.setProperty("uiRole", "dialogFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(hig.SECTION_GAP, hig.ITEM_GAP, hig.SECTION_GAP, hig.ITEM_GAP)
        actions.addStretch(1)
        apply = PillButton(tr("应用"), "primary")
        apply.setObjectName("ScoreAgentApply")
        apply.setMinimumWidth(92)
        apply.setDefault(True)
        apply.clicked.connect(self._apply)
        actions.addWidget(apply)
        root.addWidget(footer)
        self.finished.connect(self._cancel_catalog)
        self.finished.connect(self.api_key.clear)
        self._sync_provider()
        self._stacked_layout = False
        self._reflow_layout(self.width())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._queue_catalog()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_layout(event.size().width())

    def _reflow_layout(self, width: int) -> None:
        stacked = width < _STACKED_LAYOUT_WIDTH
        if stacked == self._stacked_layout:
            return
        self._stacked_layout = stacked
        direction = QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        self._body_layout.setDirection(direction)
        self._body_layout.setSpacing(hig.PANEL_PADDING if stacked else hig.SECTION_GAP)
        self._artwork.set_stacked(stacked)
        self._body_layout.activate()

    def _header(self) -> QWidget:
        header = QFrame(self)
        header.setProperty("uiRole", "dialogHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(hig.SECTION_GAP, hig.ITEM_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        title = QLabel(tr("模型设置"))
        title.setProperty("uiRole", "dialogTitle")
        layout.addWidget(title, 1)
        close = PillButton("", "ghost", FluentSymbol.CLOSE)
        close.setObjectName("FloatingPanelClose")
        close.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close.setAccessibleName(tr("关闭模型设置"))
        close.setToolTip(tr("关闭模型设置"))
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        return header

    def _fields(self, parent: QWidget) -> QWidget:
        fields = QWidget(parent)
        fields.setObjectName("ScoreAgentSettingsFields")
        layout = QVBoxLayout(fields)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.GROUP_GAP)

        self.provider = QTabBar()
        self.provider.setObjectName("ScoreAgentProvider")
        self.provider.setAccessibleName(tr("模型服务"))
        self.provider.setDrawBase(False)
        self.provider.addTab("DeepSeek")
        self.provider.addTab(tr("自定义接口"))
        self.provider.setCurrentIndex(0 if self._official else 1)
        layout.addWidget(self.provider)

        self._form = QFormLayout()
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._form.setHorizontalSpacing(hig.PANEL_PADDING)
        self._form.setVerticalSpacing(hig.GROUP_GAP)
        layout.addLayout(self._form)

        connection = self.connection
        custom_base = connection.base_url if connection and not self._official else ""
        self.preset = _PickerCombo()
        for label, endpoint in _CUSTOM_ENDPOINTS:
            self.preset.addItem(tr(label), endpoint)
        self.preset.setCurrentIndex(max(0, self.preset.findData(custom_base)))
        self._custom_base_draft = custom_base if self.preset.currentIndex() == 0 else ""
        self._add_field("接口预设", self.preset)

        self.base_url = QLineEdit(custom_base)
        self.base_url.setPlaceholderText("https://api.example.com/v1")
        self.base_url.setMaxLength(MAX_BASE_URL_LENGTH)
        self.base_url.setToolTip(tr("可粘贴 API 基础地址或完整的聊天、模型列表端点。"))
        self._add_field("API 地址", self.base_url)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setInputMethodHints(Qt.InputMethodHint.ImhSensitiveData | Qt.InputMethodHint.ImhNoPredictiveText)
        self.api_key.setMaxLength(MAX_API_KEY_LENGTH)
        self._add_field("API 密钥", self.api_key)

        self.model_choice = _PickerCombo()
        self.model_choice.setProperty("i18nSkipItems", True)
        selected = connection.model if connection and self._official else DEFAULT_MODEL
        self._set_official_models((), selected)

        self.model = _PickerCombo()
        self.model.setProperty("i18nSkipItems", True)
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model.lineEdit().setMaxLength(MAX_MODEL_LENGTH)
        self.model.lineEdit().setPlaceholderText(tr("搜索或输入模型 ID"))
        self.model.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        if connection and not self._official:
            self.model.setEditText(connection.model)

        self.model_field = QWidget(fields)
        models = QHBoxLayout(self.model_field)
        models.setContentsMargins(0, 0, 0, 0)
        models.setSpacing(hig.ITEM_GAP)
        models.addWidget(self.model_choice, 1)
        models.addWidget(self.model, 1)
        self.refresh_button = PillButton("", "secondary", FluentSymbol.REFRESH)
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.setFixedWidth(36)
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.refresh_button.setToolTip(tr("刷新模型列表"))
        self.refresh_button.setAccessibleName(self.refresh_button.toolTip())
        self.refresh_button.clicked.connect(lambda: self._refresh_catalog(force=True))
        models.addWidget(self.refresh_button)
        self._add_field("选择模型", self.model_field)
        self.model_choice.setAccessibleName(tr("选择模型"))
        self.model.setAccessibleName(tr("模型 ID"))

        self.mode_choice = _PickerCombo()
        for mode in ("fast", *DEEPSEEK_REASONING_EFFORTS):
            self.mode_choice.addItem(tr(_MODES[mode]), mode)
        mode = connection.reasoning_effort if connection and connection.thinking else "fast"
        self.mode_choice.setCurrentIndex(self.mode_choice.findData(mode))
        self._add_field("响应方式", self.mode_choice)

        self.error_label = QLabel(fields)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setMinimumHeight(42)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.error_label)

        actions = QHBoxLayout()
        self.advanced = QToolButton()
        self.advanced.setObjectName("ScoreAgentQuietAction")
        self.advanced.setText(tr("连接选项"))
        self.advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.advanced.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.advanced.setCheckable(True)
        self.advanced.toggled.connect(self._show_connection_options)
        actions.addWidget(self.advanced)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(self._connection_options(fields))
        layout.addStretch(1)
        self.provider.currentChanged.connect(self._provider_changed)
        self.preset.activated.connect(self._preset_changed)
        self.api_key.textEdited.connect(self._catalog_inputs_changed)
        self.api_key.editingFinished.connect(self._queue_catalog)
        self.base_url.textChanged.connect(self._address_changed)
        self.base_url.editingFinished.connect(self._address_committed)
        return fields

    def _add_field(self, source: str, field: QWidget) -> None:
        label = QLabel(tr(source))
        label.setObjectName("ScoreAgentSettingsSection")
        label.setBuddy(field)
        field.setAccessibleName(label.text())
        self._form.addRow(label, field)

    @staticmethod
    def _quiet_button(source: str) -> PillButton:
        button = PillButton(tr(source), "ghost")
        button.setObjectName("ScoreAgentQuietAction")
        button.setAutoDefault(False)
        return button

    def _connection_options(self, parent: QWidget) -> QFrame:
        self._options = QFrame(parent)
        self._options.setObjectName("ScoreAgentConnectionOptions")
        layout = QVBoxLayout(self._options)
        layout.setContentsMargins(0, hig.ITEM_GAP, 0, 0)
        layout.setSpacing(hig.CONTROL_GAP)
        self._official_endpoint = QLabel(DEFAULT_BASE_URL)
        self._official_endpoint.setObjectName("ScoreAgentOfficialEndpoint")
        self._official_endpoint.setAccessibleName(tr("API 地址"))
        self._official_endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._official_endpoint)

        actions = QHBoxLayout()
        self.remember = ElidedCheckBox(tr("记住连接"), self._options)
        self.remember.setVisible(self._remember_supported)
        if self._remember_supported:
            saved = load_saved_model_connection(self._profile_path)
            self.remember.setChecked(
                saved is not None and self.connection is not None
                and saved == replace(self.connection, thinking=saved.thinking, reasoning_effort=saved.reasoning_effort)
            )
            self.remember.setToolTip(tr("用当前 Windows 账户加密保存"))
            self.remember.setAccessibleDescription(self.remember.toolTip())
            actions.addWidget(self.remember)
            self.api_key.textEdited.connect(lambda _: self.remember.setChecked(False))

        actions.addStretch(1)
        self._clear_button = self._quiet_button("清除连接")
        self._clear_button.clicked.connect(self._clear)
        self._can_clear = self.connection is not None or (self._remember_supported and self._profile_path.is_file())
        self._clear_button.setVisible(self._can_clear)
        actions.addWidget(self._clear_button)
        layout.addLayout(actions)
        return self._options

    def _show_connection_options(self, expanded: bool) -> None:
        set_fluent_symbol(self.advanced, FluentSymbol.CHEVRON_DOWN if expanded else FluentSymbol.CHEVRON_RIGHT)
        self.advanced.setIconSize(QSize(12, 12))
        self._options.setVisible(expanded and not self.advanced.isHidden())


    def exec_floating(self) -> int:
        return exec_floating_panel(self)

    def _notice(self, message: str, color: str) -> None:
        self.error_label.setStyleSheet(f"color: {color};")
        self.error_label.setText(message)

    def _error(self, message: str, field: QWidget | None = None) -> None:
        self._notice(message, hig.ERROR_TEXT)
        if field is not None:
            field.setFocus()

    def _provider_changed(self, index: int) -> None:
        self._official = index == 0
        self._address_changed()
        self._sync_provider()
        self._queue_catalog()

    def _preset_changed(self, index: int) -> None:
        endpoint = self.preset.itemData(index)
        self.base_url.setText(endpoint or self._custom_base_draft)
        self._queue_catalog()

    def _sync_provider(self) -> None:
        self._form.setRowVisible(self.preset, not self._official)
        self._form.setRowVisible(self.mode_choice, self._official)
        self._form.setRowVisible(self.base_url, not self._official)
        self.model_choice.setVisible(self._official)
        self.model.setVisible(not self._official)
        self._form.labelForField(self.model_field).setBuddy(self.model_choice if self._official else self.model)
        self._official_endpoint.setVisible(self._official)
        self.advanced.setVisible(self._official or self._remember_supported or self._can_clear)
        self._show_connection_options(self.advanced.isChecked())
        self._show_catalog_hint()

    def _base_url(self) -> str:
        if self._official:
            return DEFAULT_BASE_URL
        return normalize_base_url(self.base_url.text())

    def _retained_key(self, base: str) -> str:
        if self.connection is not None and base == self.connection.base_url:
            return self.connection.api_key
        return ""

    def _address_changed(self) -> None:
        if not self._official and self.preset.currentIndex() == 0:
            self._custom_base_draft = self.base_url.text()
        try:
            base = self._base_url()
        except ValueError:
            base = None
        if base != self._input_base:
            self._input_base = base
            self.api_key.clear()
            self.remember.setChecked(False)
            self._catalog_inputs_changed()

    def _cancel_catalog(self) -> None:
        self._catalog_timer.stop()
        check, self._catalog_check = self._catalog_check, None
        if check is not None:
            check.abort()
            check.deleteLater()
        self.refresh_button.setEnabled(True)

    def _address_committed(self) -> None:
        self.base_url.setCursorPosition(0)
        self._queue_catalog()

    def _catalog_inputs_changed(self) -> None:
        self._cancel_catalog()
        self._catalog_dirty = True
        self._set_custom_models(())
        self._set_official_models((), self.model_choice.currentData())
        self._show_catalog_hint()

    def _show_catalog_hint(self) -> None:
        base = self._input_base
        placeholder = "输入 API 密钥"
        if base and self._retained_key(base):
            placeholder = "已配置密钥，留空沿用"
        elif base and is_loopback_base_url(base):
            placeholder = "本机接口可留空"
        self.api_key.setPlaceholderText(tr(placeholder))
        if self._official:
            source = "连接后自动更新模型列表。"
        elif base:
            source = "自动读取模型列表，也可以手动输入模型 ID。"
        else:
            source = "粘贴 OpenAI 兼容地址，或选择本机服务预设。"
        self._notice(tr(source), hig.SECONDARY_TEXT)

    def _report_input_error(self, error: ValueError) -> None:
        if str(error) == "base_url":
            self._error(tr("请输入 HTTPS 地址，或使用本机环回 HTTP 地址。"), self.base_url)
        elif str(error) == "model":
            self._error(tr("请输入有效的模型 ID。"), self.model)
        else:
            self._error(tr("请输入此接口的有效 API 密钥。本机环回接口可以留空。"), self.api_key)

    def _input_connection(self) -> ModelConnection | None:
        try:
            base = self._base_url()
            key = normalize_api_key(base, self.api_key.text() or self._retained_key(base))
            if not self._official:
                return ModelConnection(base, self.model.currentText(), key)
            model = self.model_choice.currentData()
            mode = self.mode_choice.currentData()
            return ModelConnection(
                base, model, key, thinking=mode != "fast",
                reasoning_effort=DEFAULT_REASONING_EFFORT if mode == "fast" else mode,
            )
        except ValueError as error:
            self._report_input_error(error)
            return None

    def _queue_catalog(self) -> None:
        if self._catalog_dirty:
            self._catalog_timer.start()

    def _refresh_catalog(self, *, force: bool = False) -> None:
        if not self.isVisible() or not (force or self._catalog_dirty):
            return
        try:
            base = self._base_url()
            key = normalize_api_key(base, self.api_key.text() or self._retained_key(base))
        except ValueError as error:
            if force:
                self._report_input_error(error)
            return
        self._cancel_catalog()
        self._catalog_dirty = False
        check = ModelCatalogCheck(self)
        self._catalog_check = check
        check.completed.connect(self._catalog_finished)
        self.refresh_button.setEnabled(False)
        self._notice(tr("正在检查模型目录…"), hig.SECONDARY_TEXT)
        check.start(base, key)

    def _set_official_models(self, models: tuple[str, ...], selected: str) -> None:
        remote = tuple(model for model in models if canonical_model_id(DEFAULT_BASE_URL, model) == model)
        choices = dict.fromkeys((*DEEPSEEK_MODELS, *remote, selected))
        with QSignalBlocker(self.model_choice):
            self.model_choice.clear()
            for model in choices:
                self.model_choice.addItem(DEEPSEEK_MODEL_NAMES.get(model, model), model)
            self.model_choice.setCurrentIndex(self.model_choice.findData(selected))
        self.model_choice.refresh_text_tooltip()

    def _set_custom_models(self, models: tuple[str, ...]) -> None:
        selected = self.model.currentText()
        with QSignalBlocker(self.model):
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentIndex(self.model.findText(selected, Qt.MatchFlag.MatchExactly))
            self.model.setEditText(selected)
        self.model.refresh_text_tooltip()

    def _catalog_finished(self, result: str, models: tuple[str, ...]) -> None:
        self._cancel_catalog()
        if result == "loaded":
            if self._official:
                self._set_official_models(models, self.model_choice.currentData())
            else:
                self._set_custom_models(models)
            if models:
                self._notice(tr("已读取 {count} 个模型。").format(count=len(models)), hig.SUCCESS_TEXT)
                return
            source = "模型列表为空。"
        else:
            source = _CATALOG_STATUS.get(result, _CATALOG_STATUS["failed"])
        message = tr(source)
        if not self._official:
            message += " " + tr("仍可手动输入模型 ID。")
        color = hig.SECONDARY_TEXT if result in {"loaded", "no_catalog"} else hig.ERROR_TEXT
        self._notice(message, color)

    def _apply(self) -> None:
        connection = self._input_connection()
        if connection is None:
            return
        try:
            if self._remember_supported and self.remember.isChecked():
                save_model_connection(connection, self._profile_path)
        except OSError:
            self._error(tr("无法更新已保存的连接。请检查本地账户的数据目录。"))
            return
        self.api_key.clear()
        self.connection = connection
        self.accept()

    def _clear(self) -> None:
        try:
            if self._remember_supported:
                clear_saved_model_connection(self._profile_path)
        except OSError:
            self._error(tr("无法更新已保存的连接。请检查本地账户的数据目录。"))
            return
        self.api_key.clear()
        self.connection = None
        self.accept()
