"""Focused application settings dialog and background import worker.

The main window supplies current values through a deliberately small structural
contract.  Accepted values are still applied by the window, keeping persistence
and playback lifecycle out of the dialog layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QEvent, QObject, QRect, QSize, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bdo_export import BDO_BPM_MAX
from bdo_music_composer.app.audio_source_settings import (
    classify_audio_source,
    default_game_music_dir,
    preview_source_mode,
    source_paths_for_mode,
)
from bdo_music_composer.audio.bdo_sample_pack import PACK_SUFFIX
from bdo_music_composer.export.bdo_score import read_bdo_score
from bdo_music_composer.core.conversion_settings import (
    VELOCITY_MODE_OFF,
    VELOCITY_MODE_PRESERVE,
)
from bdo_music_composer.ui.floating_panel_qt import FloatingPanelDialog
from bdo_music_composer.ui.i18n import LANGUAGE_CHOICES, tr, trf
from bdo_music_composer.ui.home_welcome_qt import (
    TELEMETRY_CONTENT,
    TELEMETRY_EXCLUSIONS,
    TELEMETRY_INSTALL_ID,
    TELEMETRY_TITLE,
    TIME_ZONE_LABEL,
    TIME_ZONE_NOTE,
    system_time_zone_label,
)
from bdo_music_composer.core.project_paths import GAME_ART_CACHE_DIR, USER_DATA_DIR
from bdo_music_composer.ui.local_game_art_qt import (
    GameArtImportError,
    import_game_instrument_art,
)
from bdo_music_composer.ui.page_transition_qt import NavigationCue, interface_motion_allowed
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.symbols import FluentSymbol, draw_symbol
from bdo_music_composer.ui.ui_controls import ElidedCheckBox, PillButton
from bdo_music_composer.ui.ui_notifications import show_global_toast


DEFAULT_OUTDIR = USER_DATA_DIR / "out" / "bdo"
SETTINGS_FIELD_LABEL_WIDTH = 124


def prompt_for_owner_identity(
    parent: QWidget,
    start_directory: str | Path,
) -> tuple[int, str] | None:
    """Prompt for a game score and return its validated export identity."""

    path, _ = QFileDialog.getOpenFileName(
        parent,
        tr("选择游戏内保存的曲谱文件"),
        str(start_directory),
        tr("黑色沙漠曲谱文件 (*);;所有文件 (*.*)"),
    )
    if not path:
        return None
    try:
        snapshot = read_bdo_score(Path(path), allow_trailing_data=True)
        owner_id = int(snapshot.owner_id)
    except ValueError:
        show_global_toast(
            parent,
            tr("文件无法读取；请使用游戏内保存的曲谱。"),
            kind="error",
        )
        return None
    except Exception as exc:
        show_global_toast(
            parent,
            trf("读取失败：{error}", error=exc),
            kind="error",
        )
        return None
    if not owner_id:
        show_global_toast(
            parent,
            tr("未读取到有效 Owner ID，请选择游戏内保存的曲谱。"),
            kind="warning",
        )
        return None
    character_name = snapshot.character_name_1 or snapshot.character_name_2
    return owner_id, str(character_name or "")


class SettingsHost(Protocol):
    language: str
    char_name: str
    bpm_override: int | None
    transpose: int
    output_dir_path: str
    game_music_dir_path: str
    owner_id: int
    apply_sustain: bool
    flatten_tempo: bool
    velocity_mode: str
    vel_step: tuple[int, int] | int | None
    vel_floor: int | None
    vel_range: tuple[int, int] | None
    audio_sources: dict[str, str]
    instrument_art_dir: str
    update_settings: dict[str, object]
    usage_telemetry_preferences: dict[str, object] | None

    def check_for_updates(self) -> bool: ...


class GameArtImportWorker(QThread):
    """Decrypt the allow-listed game sprite into a local cache off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paz_root: str | Path,
        cache_root: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.paz_root = Path(paz_root)
        self.cache_root = Path(cache_root)

    def run(self) -> None:
        try:
            report = import_game_instrument_art(
                self.paz_root,
                self.cache_root,
            )
        except (OSError, GameArtImportError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(report)

class SettingsDialog(FloatingPanelDialog):
    def __init__(self, parent: SettingsHost) -> None:
        super().__init__(cast(QWidget, parent))
        self.game_art_worker: GameArtImportWorker | None = None
        self._game_art_pending_paz_root = ""
        saved_usage = getattr(parent, "usage_telemetry_preferences", None)
        if not isinstance(saved_usage, dict):
            saved_usage = {}
        enabled = saved_usage.get("enabled")
        self._usage_enabled = enabled if isinstance(enabled, bool) else None
        self.usage_telemetry_combo: QComboBox | None = None
        self.selected_paz_root = str(
            parent.audio_sources.get("paz_root", "") or ""
        )
        self.setObjectName("SettingsDialog")
        self.setProperty("uiSurface", "utility")
        self.setWindowTitle(tr("设置"))
        self.setModal(True)
        self.resize(900, 620)
        self.setMinimumSize(768, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(hig.SECTION_GAP, hig.ITEM_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        header_layout.setSpacing(hig.PANEL_PADDING)
        title = QLabel(tr("设置"))
        title.setObjectName("SettingsTitle")
        title.setProperty("uiRole", "dialogTitle")
        header_layout.addWidget(title, stretch=1)
        close = PillButton("", "ghost", FluentSymbol.CLOSE)
        close.setObjectName("FloatingPanelClose")
        close.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close.setAccessibleName(tr("关闭窗口"))
        close.setToolTip(tr("关闭窗口"))
        close.clicked.connect(self.reject)
        header_layout.addWidget(close, alignment=Qt.AlignVCenter)
        layout.addWidget(header)

        content = QWidget()
        content.setObjectName("SettingsContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("SettingsNav")
        self.settings_nav.setAccessibleName(tr("设置"))
        self.settings_nav.setProperty("i18nTranslateItems", True)
        # Explicit geometry avoids native QListWidget metrics changing the
        # sidebar layout at different Windows scale factors and locales.
        self.settings_nav.setFixedWidth(184)
        self.settings_nav.setIconSize(QSize(16, 16))
        self.settings_nav.setUniformItemSizes(True)
        self.settings_nav.setSpacing(0)
        self.settings_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_pages = QStackedWidget()
        self.settings_pages.setObjectName("SettingsPages")
        general_scroll, general_page_layout = self._settings_page(
            "SettingsScroll", "SettingsGeneralPage"
        )
        midi_scroll, midi_page_layout = self._settings_page(
            "SettingsMidiScroll", "SettingsMidiPage"
        )
        audio_scroll, audio_page_layout = self._settings_page(
            "SettingsAudioScroll", "SettingsAudioPage"
        )
        update_scroll, update_page_layout = self._settings_page(
            "SettingsUpdateScroll", "SettingsUpdatePage"
        )
        privacy_scroll, self._privacy_page_layout = self._settings_page(
            "SettingsPrivacyScroll", "SettingsPrivacyPage"
        )
        for label, symbol, page in (
            (tr("通用与导出"), FluentSymbol.SETTINGS, general_scroll),
            (tr("MIDI 与力度"), FluentSymbol.CURVE, midi_scroll),
            (tr("音源与外观"), FluentSymbol.PLAY, audio_scroll),
            (tr("软件更新"), FluentSymbol.REPEAT, update_scroll),
            (tr("隐私"), FluentSymbol.INFO, privacy_scroll),
        ):
            icon = QIcon()
            for size in (16, 32):
                icon.addPixmap(draw_symbol(symbol, hig.SELECTION_TEXT, size))
            item = QListWidgetItem(icon, label)
            item.setSizeHint(QSize(0, 42))
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            )
            self.settings_nav.addItem(item)
            self.settings_pages.addWidget(page)
        self._privacy_page_index = self.settings_pages.indexOf(privacy_scroll)
        self._settings_motion = NavigationCue(self.settings_nav.viewport())
        self.settings_nav.currentRowChanged.connect(self._select_settings_page)
        self.settings_nav.currentRowChanged.connect(self._show_privacy_settings)
        self.settings_nav.setCurrentRow(0)
        content_layout.addWidget(self.settings_nav)
        content_layout.addWidget(self.settings_pages, stretch=1)
        layout.addWidget(content, stretch=1)

        general, general_layout = self._section()
        form = self._field_grid()
        general_layout.addLayout(form)
        general_page_layout.addWidget(general)

        self.language = QComboBox()
        self.language.setProperty("i18nSkipItems", True)
        for code, label in LANGUAGE_CHOICES:
            self.language.addItem(tr(label), code)
        language_index = self.language.findData(parent.language)
        self.language.setCurrentIndex(language_index if language_index >= 0 else 0)
        self._add_field(form, "界面语言", self.language)

        self.char_name = QLineEdit(parent.char_name)
        self._add_field(form, "写入角色名", self.char_name)

        self.bpm_override = QSpinBox()
        self.bpm_override.setRange(0, BDO_BPM_MAX)
        self.bpm_override.setSpecialValueText(tr("使用 MIDI"))
        self.bpm_override.setValue(parent.bpm_override or 0)
        self._add_field(form, "全局 BPM", self.bpm_override)

        self.transpose = QSpinBox()
        self.transpose.setRange(-48, 48)
        self.transpose.setSuffix(tr(" 半音"))
        self.transpose.setValue(parent.transpose)
        self._add_field(form, "移调", self.transpose)

        self._add_form_heading(form, "输出目录")
        output_row = QHBoxLayout()
        output_row.setSpacing(6)
        self.output_dir = QLineEdit(parent.output_dir_path)
        self.output_dir.setObjectName("OutputDirectoryEdit")
        self.output_dir.setPlaceholderText(tr("输出目录"))
        browse_output = PillButton(tr("选择"), "secondary")
        browse_output.setObjectName("BrowseOutputDirectoryButton")
        browse_output.clicked.connect(self._browse_output_folder)
        output_row.addWidget(browse_output)
        open_output = PillButton(tr("打开"), "ghost")
        open_output.setObjectName("OpenOutputDirectoryButton")
        open_output.clicked.connect(self._open_output_folder)
        output_row.addWidget(open_output)
        self._add_field(form, "导出保存目录", self.output_dir, actions=output_row)

        game_music_row = QHBoxLayout()
        game_music_row.setSpacing(6)
        self.game_music_dir = QLineEdit(parent.game_music_dir_path)
        self.game_music_dir.setObjectName("GameMusicDirectoryEdit")
        self.game_music_dir.setPlaceholderText(tr("游戏曲谱目录"))
        browse_game_music = PillButton(tr("选择"), "secondary")
        browse_game_music.setObjectName("BrowseGameMusicDirectoryButton")
        browse_game_music.clicked.connect(self._browse_game_music_folder)
        game_music_row.addWidget(browse_game_music)
        open_game_music = PillButton(tr("打开"), "ghost")
        open_game_music.setObjectName("OpenGameMusicDirectoryButton")
        open_game_music.clicked.connect(self._open_game_music_folder)
        game_music_row.addWidget(open_game_music)
        self._add_field(form, "游戏曲谱目录", self.game_music_dir, actions=game_music_row)

        owner, owner_layout = self._section("游戏编辑权限")
        self.settings_subtitle = QLabel(tr("选择一份游戏内保存的曲谱，读取角色名和 Owner ID。"))
        self.settings_subtitle.setObjectName("Muted")
        self.settings_subtitle.setWordWrap(True)
        owner_layout.addWidget(self.settings_subtitle)
        general_page_layout.addWidget(owner)
        self.owner_id = parent.owner_id
        self.owner_identity_changed = False
        owner_row = QHBoxLayout()
        self.owner_load_button = PillButton(tr("从游戏曲谱读取"), "secondary")
        self.owner_load_button.setMinimumWidth(124)
        self.owner_load_button.setMaximumWidth(220)
        self.owner_load_button.clicked.connect(self._load_owner_id)
        self.owner_clear_button = PillButton(tr("解除绑定"), "ghost")
        self.owner_clear_button.setObjectName("ClearOwnerIdentityButton")
        self.owner_clear_button.clicked.connect(self._clear_owner_id)
        self.owner_status = QLabel()
        self.owner_status.setObjectName("OwnerStatus")
        self.owner_status.setWordWrap(True)
        self.owner_status.setMinimumWidth(0)
        self.owner_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        owner_row.addWidget(self.owner_load_button, alignment=Qt.AlignTop)
        owner_row.addWidget(self.owner_clear_button, alignment=Qt.AlignTop)
        owner_row.addWidget(self.owner_status, stretch=1)
        owner_layout.addLayout(owner_row)
        self._refresh_owner_status()

        parsing, parsing_layout = self._section(
            "MIDI 解析",
            "这两项仅用于下一次 MIDI 导入；不会重新解析或覆盖当前工程。",
        )
        midi_page_layout.addWidget(parsing)
        self.apply_sustain = ElidedCheckBox(tr("读取并展开 MIDI sustain 踏板"))
        self.apply_sustain.setChecked(parent.apply_sustain)
        parsing_layout.addWidget(self.apply_sustain)

        self.flatten_tempo = ElidedCheckBox(tr("忽略中途 tempo 变化，按主 BPM 拉平"))
        self.flatten_tempo.setChecked(parent.flatten_tempo)
        parsing_layout.addWidget(self.flatten_tempo)

        velocity, vel_layout = self._section(
            "力度处理",
            "选择后会写入当前音符力度；导出阶段不会再做隐藏处理。",
        )
        midi_page_layout.addWidget(velocity)
        modes = QFrame()
        modes.setObjectName("SettingsModeRow")
        modes_layout = QGridLayout(modes)
        modes_layout.setContentsMargins(0, hig.CONTROL_GAP, 0, hig.CONTROL_GAP)
        modes_layout.setHorizontalSpacing(0)
        modes_layout.setVerticalSpacing(10)
        for column in range(3):
            modes_layout.setColumnStretch(column, 1)
        vel_layout.setSpacing(9)
        self.vel_radios: dict[str, QRadioButton] = {
            "layered": QRadioButton(tr("分层")),
            "stepped": QRadioButton(tr("阶梯")),
            "rescale": QRadioButton(tr("重映射")),
            "floor": QRadioButton(tr("抬底")),
            "preserve": QRadioButton(tr("保持原力度")),
        }
        for index, (mode, radio) in enumerate(self.vel_radios.items()):
            radio.setChecked(
                parent.velocity_mode == mode
                or (
                    mode == VELOCITY_MODE_PRESERVE
                    and parent.velocity_mode == VELOCITY_MODE_OFF
                )
            )
            radio.toggled.connect(self._sync_velocity_controls)
            span = 2 if mode == VELOCITY_MODE_PRESERVE else 1
            modes_layout.addWidget(radio, index // 3, index % 3, 1, span)
        vel_layout.addWidget(modes)

        self.vel_step_base = QSpinBox()
        self.vel_step_base.setRange(0, 127)
        step_base = parent.vel_step[0] if isinstance(parent.vel_step, tuple) else (parent.vel_floor or 36)
        step_size = parent.vel_step[1] if isinstance(parent.vel_step, tuple) else (parent.vel_step or 12)
        self.vel_step_base.setValue(step_base)
        self.vel_step = QSpinBox()
        self.vel_step.setRange(1, 64)
        self.vel_step.setValue(step_size)
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel(tr("底")))
        step_row.addWidget(self.vel_step_base)
        step_row.addWidget(QLabel(tr("步长")))
        step_row.addWidget(self.vel_step)
        self.vel_step_row = QWidget()
        self.vel_step_row.setLayout(
            self._labeled_row("阶梯参数", step_row, self.vel_step_base)
        )
        vel_layout.addWidget(self.vel_step_row)

        self.vel_min = QSpinBox()
        self.vel_min.setRange(1, 127)
        self.vel_min.setValue((parent.vel_range or (28, 112))[0])
        self.vel_max = QSpinBox()
        self.vel_max.setRange(1, 127)
        self.vel_max.setValue((parent.vel_range or (28, 112))[1])
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel(tr("最小")))
        range_row.addWidget(self.vel_min)
        range_row.addWidget(QLabel(tr("最大")))
        range_row.addWidget(self.vel_max)
        self.vel_range_row = QWidget()
        self.vel_range_row.setLayout(
            self._labeled_row("重映射范围", range_row, self.vel_min)
        )
        vel_layout.addWidget(self.vel_range_row)

        self.vel_floor = QSpinBox()
        self.vel_floor.setRange(0, 127)
        self.vel_floor.setValue(parent.vel_floor or 36)
        floor_row = QHBoxLayout()
        floor_row.addWidget(self.vel_floor)
        floor_row.addStretch(1)
        self.vel_floor_row = QWidget()
        self.vel_floor_row.setLayout(self._labeled_row("抬底值", floor_row, self.vel_floor))
        vel_layout.addWidget(self.vel_floor_row)

        audio, audio_layout = self._section(
            "本地音源包",
            "切换或锁定试听音源；仅用于本机试听，不会写入曲谱，也不会上传。",
        )
        audio_page_layout.addWidget(audio)
        audio_form = self._field_grid()
        audio_layout.addLayout(audio_form)
        self.preview_mode = QComboBox()
        self.preview_mode.setProperty("i18nSkipItems", True)
        for label, mode in (
            ("内置通用音源", "generic"),
            ("音源包", "pack"),
        ):
            self.preview_mode.addItem(tr(label), mode)
        self._audio_source_mode = preview_source_mode(parent.audio_sources)
        self._audio_source_values = {
            mode: str(sample_pack or audio_root)
            for mode in ("pack",)
            for sample_pack, audio_root in (
                source_paths_for_mode(parent.audio_sources, mode),
            )
        }
        preview_mode_index = self.preview_mode.findData(self._audio_source_mode)
        self.preview_mode.setCurrentIndex(max(0, preview_mode_index))
        self._add_field(audio_form, "试听音源", self.preview_mode)
        self.audio_source = QLineEdit(
            self._audio_source_values.get(self._audio_source_mode, "")
        )
        self.audio_source.setObjectName("AudioSourceEdit")
        self.audio_source.setReadOnly(True)
        self.audio_source.setPlaceholderText(tr("未选择"))
        audio_source_layout = QHBoxLayout()
        audio_source_layout.setSpacing(6)
        self.sample_pack_button = PillButton(tr("选择音源包"), "secondary")
        self.sample_pack_button.setToolTip(tr("选择 .bdosamples 音源包"))
        self.sample_pack_button.clicked.connect(self._browse_sample_pack)
        audio_source_layout.addWidget(self.sample_pack_button)
        self.clear_audio_button = PillButton(tr("清除"), "ghost")
        self.clear_audio_button.clicked.connect(self.audio_source.clear)
        self.clear_audio_button.setEnabled(bool(self.audio_source.text()))
        self.audio_source.textChanged.connect(
            lambda path: self.clear_audio_button.setEnabled(bool(path))
        )
        audio_source_layout.addWidget(self.clear_audio_button)
        self.audio_source_label = self._add_field(
            audio_form, "音源包路径", self.audio_source, actions=audio_source_layout,
            actions_below=True,
        )
        self.preview_mode.currentIndexChanged.connect(
            self._preview_source_mode_changed
        )
        self._sync_audio_source_controls()

        self._add_form_heading(audio_form, "轨道背景")
        self.instrument_art_dir = QLineEdit(parent.instrument_art_dir)
        self.instrument_art_dir.setObjectName("InstrumentArtDirectoryEdit")
        self.instrument_art_dir.setReadOnly(True)
        self.instrument_art_dir.setPlaceholderText(tr("内置原创图标"))
        art_source_layout = QHBoxLayout()
        art_source_layout.setSpacing(6)
        art_folder_button = PillButton(tr("轨道背景"), "secondary")
        art_folder_button.setToolTip(
            tr("选择本地乐器图片目录；未设置时使用内置原创图标")
        )
        art_folder_button.clicked.connect(self._browse_instrument_art_folder)
        art_source_layout.addWidget(art_folder_button)
        self.game_art_button = PillButton(tr("游戏图"), "secondary")
        self.game_art_button.setToolTip(
            tr("从本机游戏 PAZ 解密乐器图；只写入本地缓存")
        )
        self.game_art_button.clicked.connect(self._import_game_art)
        art_source_layout.addWidget(self.game_art_button)
        clear_art_button = PillButton(tr("清除"), "ghost")
        clear_art_button.clicked.connect(self.instrument_art_dir.clear)
        clear_art_button.setEnabled(bool(self.instrument_art_dir.text()))
        self.instrument_art_dir.textChanged.connect(
            lambda path: clear_art_button.setEnabled(bool(path))
        )
        art_source_layout.addWidget(clear_art_button)
        self._add_field(
            audio_form, "乐器图像", self.instrument_art_dir, actions=art_source_layout,
            actions_below=True,
        )

        appearance, appearance_layout = self._section("外观")
        self.interface_motion = QCheckBox(tr("界面切换动效"))
        self.interface_motion.setChecked(interface_motion_allowed(parent))
        self.interface_motion.setToolTip(tr("为页面切换和浮窗打开添加短缓动"))
        appearance_layout.addWidget(self.interface_motion)
        audio_page_layout.addWidget(appearance)

        updates, updates_layout = self._section(
            "无感更新",
            "后台检查并准备经过签名验证的新版本；不会上传工程、Owner ID 或本机路径。",
        )
        update_page_layout.addWidget(updates)
        self.update_enabled = QCheckBox(tr("自动检查更新"))
        self.update_enabled.setChecked(
            parent.update_settings.get("enabled", True) is not False
        )
        updates_layout.addWidget(self.update_enabled)
        self.update_auto_download = ElidedCheckBox(
            tr("发现新版本后在后台自动下载")
        )
        self.update_auto_download.setChecked(
            parent.update_settings.get("auto_download", True) is not False
        )
        self.update_enabled.toggled.connect(self._refresh_update_status)
        self.update_auto_download.toggled.connect(self._refresh_update_status)
        updates_layout.addWidget(self.update_auto_download)

        update_source_row = QHBoxLayout()
        update_source_row.setContentsMargins(0, 0, 0, 0)
        self.update_source = QComboBox()
        self.update_source.setProperty("i18nSkipItems", True)
        self.update_source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.update_source.setMinimumContentsLength(14)
        for label, source in (
            ("自动选择（优先可用镜像）", "auto"),
            ("Gitee 国内镜像", "gitee"),
            ("GitHub", "github"),
        ):
            self.update_source.addItem(tr(label), source)
        source_index = self.update_source.findData(
            str(parent.update_settings.get("source", "auto"))
        )
        self.update_source.setCurrentIndex(max(0, source_index))
        self.update_source.currentIndexChanged.connect(self._refresh_update_status)
        update_source_row.addWidget(self.update_source, stretch=1)
        check_update_button = PillButton(tr("立即检查"), "secondary")
        check_update_button.setObjectName("CheckForUpdatesButton")
        check_update_button.clicked.connect(
            lambda: self._check_for_updates(parent)
        )
        update_source_row.addWidget(check_update_button)
        updates_layout.addLayout(
            self._labeled_row("更新来源", update_source_row, self.update_source)
        )
        self.update_status = QLabel()
        self.update_status.setObjectName("SettingsUpdateStatus")
        self.update_status.setProperty("uiRole", "statusHint")
        self.update_status.setWordWrap(True)
        updates_layout.addWidget(self.update_status)
        self._refresh_update_status()

        general_page_layout.addStretch(1)
        midi_page_layout.addStretch(1)
        audio_page_layout.addStretch(1)
        update_page_layout.addStretch(1)

        self.settings_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.settings_buttons.setObjectName("SettingsButtons")
        self.settings_buttons.setProperty("uiRole", "dialogButtonRow")
        self.settings_buttons.button(QDialogButtonBox.Ok).setText(tr("保存设置"))
        self.settings_buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        self.settings_buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.settings_buttons.accepted.connect(self.accept)
        self.settings_buttons.rejected.connect(self.reject)
        self.settings_footer = QFrame()
        self.settings_footer.setObjectName("SettingsFooter")
        self.settings_footer.setProperty("uiRole", "dialogFooter")
        settings_footer_layout = QHBoxLayout(self.settings_footer)
        settings_footer_layout.setContentsMargins(
            hig.SECTION_GAP, hig.ITEM_GAP, hig.SECTION_GAP, hig.ITEM_GAP,
        )
        settings_footer_layout.setSpacing(0)
        settings_footer_layout.addWidget(self.settings_buttons)
        layout.addWidget(self.settings_footer)
        self._sync_velocity_controls()
        self.settings_nav.setFocus()

    def _show_privacy_settings(self, index: int) -> None:
        if index != self._privacy_page_index or self.usage_telemetry_combo is not None:
            return
        section, layout = self._section(TELEMETRY_TITLE, TELEMETRY_CONTENT)
        for text in (
            TELEMETRY_INSTALL_ID,
            TELEMETRY_EXCLUSIONS,
            "使用感受仅在自愿填写后随统计分享。",
        ):
            note = QLabel(tr(text))
            note.setObjectName("Muted")
            note.setWordWrap(True)
            layout.addWidget(note)

        form = self._field_grid()
        layout.addLayout(form)
        self.usage_telemetry_combo = QComboBox()
        self.usage_telemetry_combo.setAccessibleName(tr("分享使用统计"))
        if self._usage_enabled is None:
            self.usage_telemetry_combo.addItem(tr("尚未选择"), None)
        self.usage_telemetry_combo.addItem(tr("不分享"), False)
        self.usage_telemetry_combo.addItem(tr("允许分享"), True)
        self.usage_telemetry_combo.setCurrentIndex(self.usage_telemetry_combo.findData(self._usage_enabled))
        self._add_field(form, "分享使用统计", self.usage_telemetry_combo)

        time_zone = QLabel(system_time_zone_label())
        time_zone.setObjectName("UsageSystemTimeZone")
        time_zone.setProperty("i18nSkipText", True)
        time_zone.setWordWrap(True)
        time_zone.setToolTip(tr(TIME_ZONE_NOTE))
        time_zone.setAccessibleDescription(tr(TIME_ZONE_NOTE))
        self._add_field(form, TIME_ZONE_LABEL, time_zone)

        self._usage_rating_combo = QComboBox()
        rating_label = "是否帮助你编曲或作曲？（可选）"
        self._usage_rating_combo.setAccessibleName(tr(rating_label))
        for caption, value in (
            ("不填写", ""), ("觉得有帮助", "helpful"), ("一般", "neutral"), ("没有帮助", "not_helpful"),
        ):
            self._usage_rating_combo.addItem(tr(caption), value)
        self._add_field(form, rating_label, self._usage_rating_combo)
        self.usage_telemetry_combo.currentIndexChanged.connect(self._sync_usage_privacy_controls)
        self._sync_usage_privacy_controls()
        self._privacy_page_layout.addWidget(section)

    def _select_settings_page(self, index: int) -> None:
        previous = self.settings_pages.currentIndex()
        self.settings_pages.setCurrentIndex(index)
        if previous == index or min(previous, index) < 0:
            return

        def marker(row: int) -> QRect:
            rect = self.settings_nav.visualItemRect(self.settings_nav.item(row))
            return QRect(rect.x() + 9, rect.y() + 10, 2, max(0, rect.height() - 20))

        self._settings_motion.play(marker(previous), marker(index))

    def _sync_usage_privacy_controls(self) -> None:
        combo = self.usage_telemetry_combo
        sharing = combo is not None and combo.currentData() is True
        self._usage_rating_combo.setEnabled(sharing)

    def telemetry_values(self) -> dict[str, object] | None:
        """Return updated consent for the host to persist after Save."""
        combo = self.usage_telemetry_combo
        if combo is None or not isinstance(enabled := combo.currentData(), bool):
            return None
        if enabled is self._usage_enabled:
            return None
        return {"enabled": enabled, "server": ""}

    def telemetry_usefulness(self) -> str:
        """Return a voluntary rating for an enabled reporting session."""
        if self.usage_telemetry_combo is None or self.usage_telemetry_combo.currentData() is not True:
            return ""
        return str(self._usage_rating_combo.currentData() or "")

    @staticmethod
    def _settings_page(
        scroll_name: str,
        page_name: str,
    ) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName(scroll_name)
        scroll.setProperty("uiRole", "settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName(page_name)
        page.setProperty("uiRole", "settingsPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(hig.ITEM_GAP, hig.ITEM_GAP, hig.ITEM_GAP, hig.PANEL_PADDING)
        page_layout.setSpacing(hig.GROUP_GAP)
        page_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(page)
        return scroll, page_layout

    @staticmethod
    def _section(title_text: str = "", description: str = "") -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("SettingsSection")
        section.setProperty("uiRole", "settingsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(hig.PANEL_PADDING, hig.ITEM_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        layout.setSpacing(hig.ITEM_GAP)
        layout.setAlignment(Qt.AlignTop)
        if title_text:
            layout.addWidget(SettingsDialog._section_heading(title_text))
        if description:
            detail = QLabel(tr(description))
            detail.setObjectName("Muted")
            detail.setWordWrap(True)
            layout.addWidget(detail)
        return section, layout

    @staticmethod
    def _section_heading(title_text: str) -> QLabel:
        title = QLabel(tr(title_text))
        title.setObjectName("SettingsSectionTitle")
        title.setProperty("uiRole", "sectionTitle")
        return title

    @staticmethod
    def _field_grid() -> QGridLayout:
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setColumnStretch(1, 1)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        return form

    @staticmethod
    def _add_form_heading(form: QGridLayout, title_text: str) -> None:
        row = form.rowCount()
        form.setRowMinimumHeight(row, hig.ITEM_GAP)
        form.addWidget(SettingsDialog._section_heading(title_text), row + 1, 0, 1, -1)

    @staticmethod
    def _add_field(
        form: QGridLayout, label_text: str, field: QWidget, *,
        actions: QHBoxLayout | None = None,
        actions_below: bool = False,
    ) -> QLabel:
        row = form.rowCount() if form.count() else 0
        label = SettingsDialog._field_label(label_text, field)
        form.addWidget(label, row, 0)
        inline_actions = actions is not None and not actions_below
        form.addWidget(field, row, 1, 1, 1 if inline_actions else -1)
        if actions is not None:
            actions.setContentsMargins(0, 0, 0, 0)
            actions.insertStretch(0)
            if actions_below:
                form.addLayout(actions, row + 1, 1, 1, -1)
            else:
                form.addLayout(actions, row, 2)
            if isinstance(field, QLineEdit):
                # Paths are user data. The tooltip keeps the full value readable.
                field.setProperty("i18nSkipToolTip", True)
                field.setToolTip(field.text())
                field.textChanged.connect(field.setToolTip)
                field.setCursorPosition(0)
        return label

    @staticmethod
    def _field_label(label_text: str, field: QWidget) -> QLabel:
        label = QLabel(tr(label_text))
        label.setObjectName("SettingsFieldLabel")
        label.setBuddy(field)
        label.setWordWrap(True)
        label.setFixedWidth(SETTINGS_FIELD_LABEL_WIDTH)
        label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return label

    @staticmethod
    def _labeled_row(label_text: str, row: QHBoxLayout, field: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(SettingsDialog._field_label(label_text, field))
        layout.addLayout(row, stretch=1)
        return layout

    def selected_velocity_mode(self) -> str:
        for mode, radio in self.vel_radios.items():
            if radio.isChecked():
                return mode
        return "preserve"

    def _check_for_updates(self, parent: SettingsHost) -> None:
        if parent.check_for_updates():
            show_global_toast(self, tr("正在后台检查更新…"))
        else:
            show_global_toast(
                self,
                tr("当前环境无法启动更新检查"),
                kind="warning",
            )

    def _browse_output_folder(self) -> None:
        current = self.output_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择输出目录"),
            start,
        )
        if selected:
            self.output_dir.setText(selected)

    def _open_output_folder(self) -> None:
        directory = Path(self.output_dir.text().strip() or DEFAULT_OUTDIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                str(exc),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _browse_game_music_folder(self) -> None:
        current = self.game_music_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择游戏曲谱目录"),
            start,
        )
        if selected:
            self.game_music_dir.setText(selected)

    def _open_game_music_folder(self) -> None:
        directory = Path(
            self.game_music_dir.text().strip() or default_game_music_dir()
        ).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("游戏曲谱目录不可用"),
                str(exc),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _browse_sample_pack(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, tr("选择本地音源包"), self.audio_source.text(), f"BDO Sample Pack (*{PACK_SUFFIX})"
        )
        if selected:
            self.audio_source.setText(selected)

    def _preview_source_mode_changed(self) -> None:
        if self._audio_source_mode in self._audio_source_values:
            self._audio_source_values[self._audio_source_mode] = (
                self.audio_source.text().strip()
            )
        self._audio_source_mode = str(
            self.preview_mode.currentData() or "generic"
        )
        self.audio_source.setText(
            self._audio_source_values.get(self._audio_source_mode, "")
        )
        self._sync_audio_source_controls()

    def _sync_audio_source_controls(self) -> None:
        external = self._audio_source_mode == "pack"
        for widget in (
            self.audio_source_label, self.audio_source,
            self.sample_pack_button, self.clear_audio_button,
        ):
            widget.setVisible(external)

    def audio_source_values(self) -> dict[str, str]:
        """Return both remembered pack selections, including the visible edit."""

        if self._audio_source_mode in self._audio_source_values:
            self._audio_source_values[self._audio_source_mode] = (
                self.audio_source.text().strip()
            )
        return dict(self._audio_source_values)

    def _browse_instrument_art_folder(self) -> None:
        current = self.instrument_art_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择乐器背景目录"),
            start,
        )
        if selected:
            self.instrument_art_dir.setText(selected)

    def _import_game_art(self) -> None:
        if self.game_art_worker is not None:
            return
        current = self.selected_paz_root.strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择游戏 PAZ 目录"),
            start,
        )
        if not selected:
            return
        self._game_art_pending_paz_root = selected
        worker = GameArtImportWorker(
            selected,
            GAME_ART_CACHE_DIR,
            self,
        )
        self.game_art_worker = worker
        self.game_art_button.setEnabled(False)
        self.game_art_button.setText(tr("解密中…"))
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(False)
        worker.succeeded.connect(self._game_art_import_succeeded)
        worker.failed.connect(self._game_art_import_failed)
        worker.finished.connect(self._game_art_import_finished)
        worker.start()

    def _game_art_import_succeeded(self, report: object) -> None:
        output_dir = str(getattr(report, "output_dir", "") or "")
        image_count = int(getattr(report, "image_count", 0) or 0)
        if output_dir:
            self.instrument_art_dir.setText(output_dir)
            self.selected_paz_root = self._game_art_pending_paz_root
        show_global_toast(
            self,
            trf("已解密 {count} 张游戏乐器图", count=image_count),
            kind="success",
        )

    def _game_art_import_failed(self, detail: str) -> None:
        QMessageBox.warning(
            self,
            tr("游戏图不可用"),
            trf("无法读取游戏乐器图：{detail}", detail=detail),
        )

    def _game_art_import_finished(self) -> None:
        worker = self.game_art_worker
        self.game_art_worker = None
        self._game_art_pending_paz_root = ""
        self.game_art_button.setText(tr("游戏图"))
        self.game_art_button.setEnabled(True)
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self.game_art_worker is not None:
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().reject()

    def accept(self) -> None:
        """Keep the dialog open until all local path fields are usable."""

        if self.game_art_worker is not None:
            show_global_toast(self, tr("正在解密游戏图"))
            return
        output_dir = Path(
            self.output_dir.text().strip() or DEFAULT_OUTDIR
        ).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            self.settings_nav.setCurrentRow(0)
            self.output_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                tr("请选择有效的输出目录。"),
            )
            return
        game_music_dir = Path(
            self.game_music_dir.text().strip() or default_game_music_dir()
        ).expanduser()
        if game_music_dir.exists() and not game_music_dir.is_dir():
            self.settings_nav.setCurrentRow(0)
            self.game_music_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("游戏曲谱目录不可用"),
                tr("请选择有效的游戏曲谱目录。"),
            )
            return
        art_value = self.instrument_art_dir.text().strip()
        if art_value and not Path(art_value).is_dir():
            self.settings_nav.setCurrentRow(2)
            self.instrument_art_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("背景目录不可用"),
                tr("请选择有效的本地乐器图片目录。"),
            )
            return
        source_mode = str(self.preview_mode.currentData() or "generic")
        source_value = self.audio_source_values().get(source_mode, "")
        try:
            classify_audio_source(source_value)
        except ValueError:
            self.settings_nav.setCurrentRow(2)
            self.audio_source.setFocus()
            QMessageBox.warning(
                self,
                tr("音源不可用"),
                tr("请选择 .bdosamples 音源包或本地音源文件夹。"),
            )
            return
        if source_mode == "pack" and not source_value:
            self.settings_nav.setCurrentRow(2)
            self.audio_source.setFocus()
            QMessageBox.warning(
                self,
                tr("音源不可用"),
                tr("请先选择一个 .bdosamples 音源包。"),
            )
            return
        super().accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.game_art_worker is not None:
            event.ignore()
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().closeEvent(event)

    def _refresh_owner_status(self, error: str = "") -> None:
        self.owner_clear_button.setEnabled(bool(self.owner_id))
        if error:
            self.owner_status.setText(error)
            self.owner_status.setProperty("ownerError", True)
        elif self.owner_id:
            self.owner_status.setText(trf("已读取 Owner ID：0x{owner_id:08x}", owner_id=self.owner_id))
            self.owner_status.setProperty("ownerError", False)
        else:
            self.owner_status.setText(
                tr("未读取 Owner ID；导出的曲谱无法在游戏内编辑。")
            )
            self.owner_status.setProperty("ownerError", False)
        self.owner_status.style().unpolish(self.owner_status)
        self.owner_status.style().polish(self.owner_status)

    def _refresh_update_status(self) -> None:
        """Keep the update page useful when no check is currently running."""
        if not self.update_enabled.isChecked():
            status = tr("状态：已关闭自动检查；可随时手动检查更新。")
        elif self.update_auto_download.isChecked():
            status = tr("状态：已启用自动检查和后台下载；安装会在下次启动完成。")
        else:
            status = tr("状态：已启用自动检查；发现新版本后等待手动下载。")
        source = self.update_source.currentText()
        self.update_status.setText(trf("{status}\n当前来源：{source}", status=status, source=source))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange and hasattr(self, "update_status"):
            self._refresh_update_status()

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择游戏内保存的曲谱文件"),
            self.game_music_dir.text().strip() or str(default_game_music_dir()),
            tr("黑色沙漠曲谱文件 (*);;所有文件 (*.*)"),
        )
        if not path:
            return
        try:
            snapshot = read_bdo_score(Path(path), allow_trailing_data=True)
            owner_id = int(snapshot.owner_id)
            char_name = snapshot.character_name_1 or snapshot.character_name_2
            if owner_id == 0:
                self._refresh_owner_status(
                    tr("未读取到有效 Owner ID，请选择游戏内保存的曲谱。")
                )
                return
        except ValueError:
            self._refresh_owner_status(
                tr("文件无法读取；请使用游戏内保存的曲谱。")
            )
            return
        except Exception as exc:
            self._refresh_owner_status(trf("读取失败：{error}", error=exc))
            return
        self.owner_id = owner_id
        self.owner_identity_changed = True
        if char_name:
            self.char_name.setText(char_name)
        self._refresh_owner_status()

    def _clear_owner_id(self) -> None:
        if not self.owner_id:
            return
        answer = QMessageBox.question(
            self,
            tr("解除绑定"),
            tr("这会清除当前项目和本机配置中的 Owner ID；之后导出前需要重新读取游戏曲谱。"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.owner_id = 0
        self.owner_identity_changed = True
        self._refresh_owner_status()

    def _sync_velocity_controls(self) -> None:
        mode = self.selected_velocity_mode()
        step_enabled = mode == "stepped"
        range_enabled = mode == "rescale"
        floor_enabled = mode in {"floor", "stepped"}
        for widget in (self.vel_step_base, self.vel_step):
            widget.setEnabled(step_enabled)
        for widget in (self.vel_min, self.vel_max):
            widget.setEnabled(range_enabled)
        self.vel_floor.setEnabled(floor_enabled)
        self.vel_step_row.setVisible(step_enabled)
        self.vel_range_row.setVisible(range_enabled)
        self.vel_floor_row.setVisible(floor_enabled)
