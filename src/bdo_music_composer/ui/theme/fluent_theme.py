"""Canonical native-first Fluent styling for the Qt Widgets interface.

The application keeps its music workspaces custom-painted, while ordinary
controls use the newest native Windows style available.  The QSS layer is
therefore limited to BDO branding and the shared component hierarchy.
"""

from __future__ import annotations

from functools import lru_cache
from string import Template

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QStyleFactory, QWidget

from bdo_music_composer.core.project_paths import ASSETS_DIR
from bdo_music_composer.ui.i18n import localizer

from . import hig_tokens as hig
from .button_style import BUTTON_QSS
from .fonts_qt import apply_application_fonts
from .interaction_style import INTERACTION_QSS, INTERACTION_THEME_MARKER
from .symbols import FluentSymbol, draw_symbol

WINDOWS_STYLE_PRIORITY = ("windows11", "windowsvista", "windows", "fusion")

# Popup windows are painted through a separate native Windows surface.  A
# palette plus a parent-window stylesheet is not sufficient on the Windows 11
# Qt style: enabled menu text can be resolved from the native light-theme role
# and become black on the fixed dark popup.  Keep every popup-menu state under
# one application-level semantic contract.
POPUP_MENU_BACKGROUND = hig.PANEL
POPUP_MENU_BORDER = hig.CONTROL_BORDER
POPUP_MENU_TEXT = hig.TEXT
POPUP_MENU_DISABLED_TEXT = hig.DISABLED_TEXT
POPUP_MENU_SELECTED_BACKGROUND = hig.SELECTION
POPUP_MENU_SELECTED_TEXT = hig.SELECTION_TEXT
POPUP_MENU_SEPARATOR = hig.SEPARATOR
POPUP_MENU_INDICATOR_BACKGROUND = hig.CONTROL
POPUP_MENU_INDICATOR_CHECKED = hig.SELECTION_INDICATOR
_POPUP_ITEM_LABEL_PADDING = 28
POPUP_MENU_LABEL_INSET = _POPUP_ITEM_LABEL_PADDING + hig.GROUP_CONTENT_MARGIN
_POPUP_THEME_MARKER = "bdo-fixed-dark-popup-theme-v1"
_INDICATOR_ASSETS = ASSETS_DIR / "icons" / "indicators"
_CHECK_MARK = (_INDICATOR_ASSETS / "check.png").as_posix()
_MIXED_MARK = (_INDICATOR_ASSETS / "mixed.png").as_posix()
_RADIO_MARK = (_INDICATOR_ASSETS / "radio.png").as_posix()

FIXED_DARK_POPUP_MENU_QSS = f"""
    /* {_POPUP_THEME_MARKER} */
    QMenu {{
        background-color: {POPUP_MENU_BACKGROUND};
        color: {POPUP_MENU_TEXT};
        border: 1px solid {POPUP_MENU_BORDER};
        border-radius: {hig.GROUP_RADIUS}px;
        padding: {hig.GROUP_CONTENT_MARGIN - 1}px 0;
    }}
    QMenu::item {{
        background-color: transparent;
        color: {POPUP_MENU_TEXT};
        min-height: 20px;
        padding: 5px 30px 5px {_POPUP_ITEM_LABEL_PADDING}px;
        margin: 1px {hig.GROUP_CONTENT_MARGIN}px;
        border-radius: {hig.CONTROL_RADIUS}px;
    }}
    QMenu::item:selected {{
        background-color: {POPUP_MENU_SELECTED_BACKGROUND};
        color: {POPUP_MENU_SELECTED_TEXT};
    }}
    QMenu::item:disabled {{
        background-color: transparent;
        color: {POPUP_MENU_DISABLED_TEXT};
    }}
    QMenu::item:selected:disabled {{
        background-color: transparent;
        color: {POPUP_MENU_DISABLED_TEXT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {POPUP_MENU_SEPARATOR};
        margin: 5px 9px;
    }}
    QMenu::indicator {{
        width: 13px;
        height: 13px;
        left: 9px;
        border: 1px solid {hig.INDICATOR_BORDER};
        border-radius: {hig.SMALL_CONTROL_RADIUS}px;
        background: {POPUP_MENU_INDICATOR_BACKGROUND};
    }}
    QMenu::indicator:checked {{
        border-color: {POPUP_MENU_INDICATOR_CHECKED};
        background: {POPUP_MENU_INDICATOR_CHECKED};
        image: url("{_CHECK_MARK}");
    }}
    QMenu::indicator:exclusive {{
        border-radius: 7px;
    }}
    QMenu::indicator:exclusive:checked {{
        image: url("{_RADIO_MARK}");
    }}
    QMenu::indicator:disabled {{
        border-color: {hig.CONTROL_BORDER};
        background: {hig.PANEL};
    }}
    QMenu::indicator:checked:disabled {{
        background: {hig.SELECTION_BORDER};
    }}
"""


def preferred_widget_style(available_styles: list[str]) -> str | None:
    available = {key.casefold(): key for key in available_styles}
    for candidate in WINDOWS_STYLE_PRIORITY:
        if candidate in available:
            return available[candidate]
    return None


def configure_widget_style(app: QApplication) -> str:
    """Select the best installed Windows-like style and return its key."""

    selected = preferred_widget_style(QStyleFactory.keys())
    if selected is not None:
        app.setStyle(selected)
    else:
        selected = app.style().objectName()
    apply_fixed_dark_palette(app)
    translator = localizer()
    apply_application_fonts(app, translator.language if translator is not None else "en_US")
    install_fixed_dark_popup_theme(app)
    if INTERACTION_THEME_MARKER not in app.styleSheet():
        app.setStyleSheet(
            app.styleSheet() + BUTTON_QSS + SHARED_CONTROL_QSS + INTERACTION_QSS
        )
    return selected


def apply_fixed_dark_palette(app: QApplication) -> None:
    """Keep the workstation dark regardless of the operating-system theme."""

    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: hig.CANVAS,
        QPalette.ColorRole.WindowText: hig.TEXT,
        QPalette.ColorRole.Base: hig.PANEL,
        QPalette.ColorRole.AlternateBase: hig.CONTROL,
        QPalette.ColorRole.ToolTipBase: hig.CONTROL,
        QPalette.ColorRole.ToolTipText: hig.TEXT,
        QPalette.ColorRole.Text: hig.TEXT,
        QPalette.ColorRole.Button: hig.CONTROL,
        QPalette.ColorRole.ButtonText: hig.TEXT,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Highlight: hig.SELECTION,
        QPalette.ColorRole.HighlightedText: hig.SELECTION_TEXT,
        QPalette.ColorRole.Link: hig.ACCENT,
        QPalette.ColorRole.PlaceholderText: hig.DISABLED_TEXT,
    }
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
    ):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))

    disabled_colors = dict(colors)
    disabled_colors.update({
        QPalette.ColorRole.WindowText: POPUP_MENU_DISABLED_TEXT,
        QPalette.ColorRole.Text: POPUP_MENU_DISABLED_TEXT,
        QPalette.ColorRole.ButtonText: POPUP_MENU_DISABLED_TEXT,
        QPalette.ColorRole.ToolTipText: POPUP_MENU_DISABLED_TEXT,
        QPalette.ColorRole.Highlight: "#302a20",
        QPalette.ColorRole.HighlightedText: POPUP_MENU_DISABLED_TEXT,
        QPalette.ColorRole.PlaceholderText: "#6f6a65",
    })
    for role, color in disabled_colors.items():
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            role,
            QColor(color),
        )
    app.setPalette(palette)
    app.setProperty("bdoFixedDarkTheme", True)


def install_fixed_dark_popup_theme(app: QApplication) -> None:
    """Install the global popup contract without duplicating application QSS."""

    stylesheet = app.styleSheet()
    if _POPUP_THEME_MARKER not in stylesheet:
        app.setStyleSheet(
            (stylesheet.rstrip() + "\n" + FIXED_DARK_POPUP_MENU_QSS).strip()
        )
    app.setProperty("bdoFixedDarkPopupTheme", True)


def system_uses_dark_theme(app: QApplication | None = None) -> bool:
    app = app or QApplication.instance()
    if app is None:
        return False
    if app.property("bdoFixedDarkTheme"):
        return True
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def set_fluent_symbol(
    button: QAbstractButton,
    symbol: FluentSymbol,
    *,
    checked_symbol: FluentSymbol | None = None,
) -> None:
    button.setProperty("fluentSymbol", symbol.value)
    button.setProperty(
        "fluentCheckedSymbol", checked_symbol.value if checked_symbol else None,
    )
    button.setIconSize(fluent_icon_size())
    _set_symbol_icon(button, symbol, system_uses_dark_theme())


def _set_symbol_icon(
    button: QAbstractButton, symbol: FluentSymbol, dark: bool, *,
    focused: bool | None = None,
) -> None:
    color = hig.TEXT if dark else "#4b4742"
    if button.property("kind") == "convert":
        color = hig.ACCENT_TEXT
    elif button.property("kind") == "accent-outline":
        color = hig.ACCENT
    if focused is None:
        focused = bool(button.property("fluentCaptionFocus")) and button.hasFocus()
    if focused:
        color = hig.FOCUS
    checked_value = button.property("fluentCheckedSymbol")
    checked_symbol = FluentSymbol(checked_value) if checked_value else None
    button.setIcon(_symbol_icon(symbol, color, checked_symbol))


@lru_cache(maxsize=96)
def _symbol_icon(
    symbol: FluentSymbol, color: str, checked_symbol: FluentSymbol | None,
) -> QIcon:
    """Share the fixed palette and size variants across editor controls."""
    icon = QIcon()
    for size in (16, 24, 32, 48):
        icon.addPixmap(draw_symbol(symbol, color, size))
        icon.addPixmap(draw_symbol(symbol, hig.DISABLED_TEXT, size), QIcon.Mode.Disabled)
        if checked_symbol is not None:
            icon.addPixmap(
                draw_symbol(checked_symbol, color, size), QIcon.Mode.Normal, QIcon.State.On,
            )
            icon.addPixmap(
                draw_symbol(checked_symbol, hig.DISABLED_TEXT, size), QIcon.Mode.Disabled, QIcon.State.On,
            )
    return icon


class _CaptionIconFocus(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            value = watched.property("fluentSymbol")
            if isinstance(watched, QAbstractButton) and value:
                _set_symbol_icon(
                    watched, FluentSymbol(value), system_uses_dark_theme(),
                    focused=kind == QEvent.Type.FocusIn,
                )
        return False


def enable_caption_focus_icons(caption: QWidget) -> None:
    """Keep keyboard focus on the caption glyph while leaving the backing flat."""
    focus = _CaptionIconFocus(caption)
    for button in caption.findChildren(QAbstractButton):
        if button.property("fluentSymbol") and button.objectName() != "EnsembleCapacityBadge":
            button.setProperty("fluentCaptionFocus", True)
            button.installEventFilter(focus)


def refresh_fluent_icons(root: QWidget, dark: bool) -> None:
    for button in root.findChildren(QAbstractButton):
        value = button.property("fluentSymbol")
        if not value:
            continue
        _set_symbol_icon(button, FluentSymbol(value), dark)


def fluent_icon_size() -> QSize:
    return QSize(16, 16)


# The legacy stylesheet used dark colors as its source language.  Keeping the
# light mapping here makes theme policy independent from the main window and is
# an intermediate step toward fully semantic color tokens.
LIGHT_COLOR_REPLACEMENTS = {
    "#151515": "#f4f4f4", "#181818": "#f7f7f7", "#202020": "#ffffff",
    "#1f1f1f": "#fafafa", "#1d1d1d": "#f0f0f0", "#222222": "#ffffff",
    "#201f1c": "#fffaf0", "#1b201b": "#f4f8f3",
    "#20251f": "#edf4eb",
    "#2b362a": "#e2eddf", "#151915": "#ffffff", "#111511": "#f4f8f3",
    "#262626": "#ffffff", "#1a1a1a": "#eeeeee", "#1e1e1e": "#ffffff",
    "#2b2b2b": "#f6f6f6", "#343434": "#e7e7e7", "#302a20": "#fff4df",
    "#232323": "#e5e5e5", "#1b1b1b": "#ededed", "#3a3a3a": "#c9c9c9",
    "#333130": "#d7d3ce", "#3b3935": "#d2cec8", "#393735": "#d5d1cb",
    "#353332": "#d9d5cf", "#3d3932": "#d3c9b8", "#3b4939": "#c4d2c1",
    "#40503e": "#b8cab4",
    "#536a50": "#9ab294", "#313d30": "#c8d4c5",
    "#313131": "#d4d4d4", "#3f3a33": "#d4c8b8", "#363636": "#d0d0d0",
    "#404040": "#c8c8c8", "#55504a": "#aaa39b", "#4a4640": "#aaa49c",
    "#56504a": "#9f9890", "#6a6259": "#8f877e", "#55514b": "#aaa49d",
    "#46423d": "#c8c3bd", "#3a3834": "#ccc8c2", "#383531": "#d0cbc4",
    "#2c2b29": "#dedbd7", "#34322f": "#d1cdc7", "#191919": "#ffffff",
    "#4a391f": "#ffe3ae", "#f3f1ea": "#202020", "#ddd7cf": "#2b2b2b",
    "#c7c0b8": "#4b4742", "#bdb6ad": "#55504a", "#aaa39a": "#66605a",
    "#e5dfd6": "#292724", "#d6d1c9": "#3f3b36", "#a8a29e": "#68625d",
    "#d9ead3": "#31552d", "#d8d3cc": "#45413d", "#bcd5b5": "#3f6639",
    "#a8b5a4": "#5d6e59", "#c9c2ba": "#514c47", "#6f6a65": "#92908d",
    "#eee7db": "#332f2a", "#f0c66f": "#8a5a00",
    "#d6b675": "#74500d", "#8f6b2e": "#d89a28",
    "#5d451e": "#ffe0a3", "#e4c17c": "#80550c", "#d9d3ca": "#3e3a35",
    "#fff3d6": "#3b2a12", "#8d8780": "#8a867f",
    hig.CANVAS: "#f4f4f6", hig.PANEL: "#ffffff", hig.CONTROL: "#f4f4f6",
    hig.CONTROL_HOVER: "#e3e3e8", hig.CONTROL_PRESSED: "#d9d9df",
    hig.SEPARATOR: "#d6d6db", hig.CONTROL_BORDER: "#929298",
    hig.INDICATOR_BORDER: "#737377",
    hig.TEXT: "#202020", hig.SECONDARY_TEXT: "#4d4944", hig.DISABLED_TEXT: "#615b53",
    hig.SELECTION: "#e7e7ea", hig.SELECTION_HOVER: "#dcdce0",
    hig.SELECTION_BORDER: "#747478", hig.SELECTION_TEXT: "#252526",
    hig.SELECTION_INDICATOR: "#4f4e4b",
    hig.FOCUS: "#855606", hig.ERROR_TEXT: "#a62920",
}


# Ordinary controls share metrics and interaction states. Dense editor bars
# keep their explicit sizes; they do not acquire a second set of colors.
CONTROL_BACKGROUND = hig.CONTROL
CONTROL_BORDER = hig.CONTROL_BORDER
CONTROL_TEXT = hig.TEXT
CONTROL_DISABLED_TEXT = hig.DISABLED_TEXT
CONTROL_FOCUS = hig.FOCUS

SHARED_CONTROL_QSS = f"""
    QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit {{
        background: {CONTROL_BACKGROUND};
        border: 1px solid {CONTROL_BORDER};
        border-radius: {hig.CONTROL_RADIUS}px;
        color: {CONTROL_TEXT};
        padding: 5px 8px;
        selection-background-color: {hig.SELECTION};
        selection-color: {hig.SELECTION_TEXT};
    }}
    QLineEdit, QComboBox, QAbstractSpinBox {{ min-height: 20px; }}
    QAbstractSpinBox {{ max-height: 20px; }}
    QLineEdit:read-only {{ background: {hig.PANEL}; }}
    QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover,
    QPlainTextEdit:hover, QTextEdit:hover {{
        border-color: {hig.SELECTION_BORDER};
    }}
    QComboBox:on {{
        background: {hig.SELECTION};
        border-color: {hig.SELECTION_BORDER};
    }}
    QLineEdit:focus, QComboBox:focus, QComboBox:on:focus,
    QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {CONTROL_FOCUS};
    }}
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled,
    QPlainTextEdit:disabled, QTextEdit:disabled {{
        color: {CONTROL_DISABLED_TEXT};
        background: {hig.PANEL};
        border-color: {hig.SEPARATOR};
    }}
    QAbstractSpinBox > QLineEdit, QComboBox > QLineEdit {{
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 0;
        min-height: 0;
    }}
    QComboBox QAbstractItemView {{
        background: {hig.PANEL};
        color: {CONTROL_TEXT};
        border: 1px solid {CONTROL_BORDER};
        border-radius: {hig.CONTROL_RADIUS}px;
        selection-background-color: {hig.SELECTION};
        selection-color: {hig.SELECTION_TEXT};
        outline: 0;
    }}
    QCheckBox, QRadioButton {{ color: {hig.TEXT}; spacing: 7px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {CONTROL_DISABLED_TEXT}; }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: {hig.SMALL_CONTROL_RADIUS}px;
        border: 1px solid {hig.INDICATOR_BORDER};
        background: {hig.CONTROL};
    }}
    QRadioButton::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 7px;
        border: 1px solid {hig.INDICATOR_BORDER};
        background: {hig.CONTROL};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        background: {hig.CONTROL_HOVER};
        border-color: {hig.SECONDARY_TEXT};
    }}
    QCheckBox::indicator:pressed, QRadioButton::indicator:pressed {{
        background: {hig.CONTROL_PRESSED};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {hig.SELECTION_INDICATOR};
        border-color: {hig.SELECTION_INDICATOR};
    }}
    QCheckBox::indicator:checked {{ image: url("{_CHECK_MARK}"); }}
    QCheckBox::indicator:indeterminate {{ image: url("{_MIXED_MARK}"); }}
    QRadioButton::indicator:checked {{ image: url("{_RADIO_MARK}"); }}
    QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{
        background: {hig.TEXT};
    }}
    QCheckBox::indicator:checked:pressed, QRadioButton::indicator:checked:pressed,
    QCheckBox::indicator:indeterminate {{
        background: {hig.SELECTION_BORDER};
        border-color: {hig.SELECTION_INDICATOR};
    }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
        border-color: {hig.FOCUS};
    }}
    QCheckBox::indicator:checked:focus, QRadioButton::indicator:checked:focus {{
        border-color: {CONTROL_BACKGROUND};
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        background: {hig.PANEL};
        border-color: {hig.CONTROL_BORDER};
    }}
    QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled,
    QRadioButton::indicator:checked:disabled {{
        background: {hig.SELECTION_BORDER};
        border-color: {hig.CONTROL_BORDER};
    }}
"""


FLUENT_COMPONENT_QSS = Template("""
    QFrame#CommandGroup, QFrame#TransportGroup {
        background: #1a1a1a;
        border: 1px solid #353332;
        border-radius: ${GROUP_RADIUS}px;
    }
    QLabel[uiRole="dialogTitle"] {
        color: #f3f1ea;
        font-size: ${TYPE_DIALOG_HEADING}px;
        font-weight: 700;
    }
    QLabel[uiRole="dialogSubtitle"] {
        color: #aaa39a;
        font-size: ${TYPE_SECONDARY}px;
    }
    QFrame[uiRole="dialogHeader"] {
        background: $PANEL;
        border: 0;
        border-bottom: 1px solid $SEPARATOR;
        border-radius: 0;
    }
    QFrame[uiRole="dialogFooter"] {
        background: $PANEL;
        border: 0;
        border-top: 1px solid $SEPARATOR;
        border-radius: 0;
    }
    QDialog[uiSurface="utility"], QFrame[uiRole="dialogBody"] {
        background: $CANVAS; color: $TEXT;
    }
    QFrame#PerformanceStrip {
        background: #1d1d1f;
        border: 0;
        border-top: 1px solid #3d3932;
        border-radius: 0;
    }
    QLabel#PerformanceCaption {
        color: #f0c66f;
        font-size: ${TYPE_SECONDARY}px;
        font-weight: 700;
    }
    QLabel#PerformanceMetric, QLabel#EnsembleMetric,
    QLabel#ProjectMusicStatus {
        color: #d8d3cc;
        font-size: ${TYPE_SECONDARY}px;
    }
    QLabel#PerformanceMetric { font-family: Consolas, monospace; }
    QLabel#EnsembleMetric { font-weight: 800; }
    QLabel#ProjectMusicStatus { font-weight: 600; }
    QLabel#EditorClipBoundsMusical {
        color: #e4c17c;
        font-size: ${TYPE_CAPTION}px;
        font-weight: 600;
    }
""").substitute(vars(hig))


def build_fluent_stylesheet(base_stylesheet: str, dark: bool) -> str:
    stylesheet = SHARED_CONTROL_QSS + base_stylesheet + FLUENT_COMPONENT_QSS
    if dark:
        return stylesheet
    for dark_color, light_color in LIGHT_COLOR_REPLACEMENTS.items():
        stylesheet = stylesheet.replace(dark_color, light_color)
    return stylesheet
