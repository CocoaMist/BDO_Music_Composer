"""Bundled typography for the localized desktop interface."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel

from bdo_music_composer.core.project_paths import ASSETS_DIR
from bdo_music_composer.ui.theme import hig_tokens as hig


FONT_ROOT = ASSETS_DIR / "fonts"

# Keep regional CJK faces first so Qt uses the locale's forms for shared Han
# code points. Qt supplies additional glyphs for mixed-language project data.
LOCALE_FONTS = {
    "zh_CN": ("zh-CN", "LXGW975YuanSC-500W.ttf", "LXGWWenKaiGBLite-Regular.ttf", "Microsoft YaHei UI"),
    "zh_TW": ("zh-TW", "ChironGoRoundTC-500M.otf", "Iansui-Regular.ttf", "Microsoft JhengHei UI"),
    "en_US": ("en", "Nunito[wght].ttf", "DancingScript[wght].ttf", hig.UI_FONT_FAMILY),
    "ja_JP": ("ja", "MPLUSRounded1c-Regular.ttf", "KleeOne-SemiBold.ttf", "Yu Gothic UI"),
    "ko_KR": ("ko", "NanumSquareRoundR.ttf", "NanumPenScript-Regular.ttf", "Malgun Gothic"),
}
_CHINESE_LOCALES = {"zh_CN", "zh_TW"}


def _register_font(app: QApplication, locale: str, role: str, filename: str) -> str:
    # Application font IDs belong to this QApplication's font database.
    cache = getattr(app, "_bdo_font_families", None)
    if cache is None:
        cache = app._bdo_font_families = {}
    path = FONT_ROOT / locale / role / filename
    if path not in cache:
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        cache[path] = families[0] if families else ""
    return cache[path]


def apply_application_fonts(app: QApplication, language: str) -> None:
    locale, ui_file, title_file, fallback = LOCALE_FONTS.get(language, LOCALE_FONTS["en_US"])
    ui_family = _register_font(app, locale, "UI", ui_file)
    title_family = _register_font(app, locale, "Theme", title_file)
    windows = app.platformName() == "windows"
    chinese = language in _CHINESE_LOCALES
    if not windows:
        fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    # The Windows Chinese UI faces include hinting and weight variants for
    # small desktop labels. Keep the bundled round faces as glyph fallbacks.
    use_windows_ui_face = windows and chinese and QFontDatabase.hasFamily(fallback)
    families = (fallback, ui_family) if use_windows_ui_face else (ui_family, fallback)
    ui_families = [family for family in families if family]
    font = app.font()
    font.setFamilies(ui_families)
    font.setPixelSize(hig.TYPE_BODY + int(chinese))
    medium = chinese and ui_family and not use_windows_ui_face
    font.setWeight(QFont.Weight.Medium if medium else QFont.Weight.Normal)
    if windows:
        strategy = QFont.StyleStrategy.PreferAntialias
        if not chinese:
            strategy |= QFont.StyleStrategy.NoSubpixelAntialias
        font.setStyleStrategy(strategy)
        font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setProperty("bdoThemeTitleFamilies", [title_family, *ui_families] if title_family else ui_families)
    if font != app.font():
        app.setFont(font)
        # Restyle existing controls. Qt keeps the font from their first
        # polish until the application stylesheet is reapplied.
        if stylesheet := app.styleSheet():
            app.setStyleSheet(stylesheet)


def canvas_caption_font(font: QFont) -> QFont:
    """Keep dense editor labels just one logical pixel below the UI font."""
    font.setPixelSize(max(hig.TYPE_SECONDARY, font.pixelSize() - 1))
    return font


class ThemeTitle(QLabel):
    """Display a short title in the current locale's handwritten face."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        app = QApplication.instance()
        families = app.property("bdoThemeTitleFamilies") if app is not None else None
        if families:
            font = QFont(app.font())
            font.setFamilies(families)
            font.setWeight(QFont.Weight.Normal)
            font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            self.setFont(font)
