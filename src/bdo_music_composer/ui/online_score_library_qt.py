"""A native embedded browser for the public BDO score library."""

from __future__ import annotations

import os
from json import loads
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QPluginLoader, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from bdo_music_composer.app.application_metadata import APP_WEBSITE_URL
from bdo_music_composer.core.project_paths import USER_DATA_DIR
from bdo_music_composer.ui.i18n import localizer, resolve_language, tr
from bdo_music_composer.ui.score_library_downloads import is_score_library_download_url
from bdo_music_composer.ui.score_library_page_scripts import READ_LIBRARY_DOWNLOADS, SETUP_LIBRARY_PAGE
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.symbols import FluentSymbol
from bdo_music_composer.ui.ui_controls import PillButton

if TYPE_CHECKING:
    from PySide6.QtWebView import QWebView, QWebViewLoadingInfo


_LOAD_TIMEOUT_MS = 25_000
_DOWNLOAD_POLL_MS = 250
_LIBRARY_LANGUAGE_PATHS = {
    "en_US": "/en/",
    "zh_TW": "/zh-TW/",
    "ja_JP": "/ja/",
    "ko_KR": "/ko/",
}
_WEBVIEW2_CLIENT_KEY = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_WEBVIEW2_PLUGIN = Path("webview/qtwebview_webview2.dll")


def _library_start_url() -> QUrl:
    translator = localizer()
    language = translator.language if translator is not None else resolve_language("auto")
    return QUrl(APP_WEBSITE_URL).resolved(QUrl(_LIBRARY_LANGUAGE_PATHS.get(language, "/")))


def _load_error_detail(error: str) -> str:
    status = error.removeprefix("COREWEBVIEW2_WEB_ERROR_STATUS_")
    if status.startswith(("CERTIFICATE_", "CLIENT_CERTIFICATE_")):
        return "证书校验失败。"
    if status == "HOST_NAME_NOT_RESOLVED":
        return "无法解析曲谱库域名。"
    if status == "TIMEOUT":
        return "连接曲谱库超时。"
    if status in {"CANNOT_CONNECT", "SERVER_UNREACHABLE", "CONNECTION_ABORTED", "CONNECTION_RESET", "DISCONNECTED"}:
        return "无法建立或维持与曲谱库的连接。"
    if status == "ERROR_HTTP_INVALID_SERVER_RESPONSE":
        return "曲谱库服务器返回了无效响应。"
    if status == "REDIRECT_FAILED":
        return "曲谱库网页跳转失败。"
    return "可在默认浏览器中确认网站能否访问。"


def initialize_online_score_library() -> None:
    """Select the existing Windows WebView2 plugin before QApplication."""
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtWebView import QtWebView
    except (ImportError, OSError):
        return

    os.environ["QT_WEBVIEW_PLUGIN"] = "webview2"
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(USER_DATA_DIR / "score-library-browser"))
    os.environ.setdefault("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", f"FF{hig.CANVAS[1:]}")
    QtWebView.initialize()


def _create_library_view() -> QWebView:
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        raise ImportError("WebView2 requires the native Windows Qt platform")

    # Qt 6.11 terminates on missing plug-ins, so check before constructing QWebView.
    if not _has_webview2_runtime() or not any(
        QPluginLoader(str(Path(directory) / _WEBVIEW2_PLUGIN)).load()
        for directory in QCoreApplication.libraryPaths()
    ):
        raise ImportError("The WebView2 runtime or Qt plug-in is unavailable")

    from PySide6.QtWebView import QWebView, QWebViewSettings

    view = QWebView()
    view.setObjectName("OnlineScoreLibraryView")
    view.settings().setAttribute(QWebViewSettings.WebAttribute.AllowFileAccess, False)
    return view


def _has_webview2_runtime() -> bool:
    import winreg

    executable_folder = os.environ.get("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER")
    if executable_folder and (Path(executable_folder) / "msedgewebview2.exe").is_file():
        return True

    for hive, access in (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY),
    ):
        try:
            with winreg.OpenKey(hive, _WEBVIEW2_CLIENT_KEY, 0, access) as key:
                version, _value_type = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if isinstance(version, str) and any(part.isdecimal() and int(part) for part in version.split(".")):
            return True
    return False


class OnlineScoreLibraryPage(QWidget):
    """Created after the user visits the library from the caption."""

    download_requested = Signal(QUrl)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OnlineScoreLibraryPage")
        self._origin = _library_start_url()
        self._started_origin: QUrl | None = None
        self._retry_url = self._origin
        self._load_pending = False
        self._view: QWebView | None = None
        self._download_hooks_ready = False
        self._download_poll_pending = False
        self._download_timer = QTimer(self)
        self._download_timer.setInterval(_DOWNLOAD_POLL_MS)
        self._download_timer.timeout.connect(self._poll_page_downloads)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._download_notice = QLabel(self)
        self._download_notice.setTextFormat(Qt.TextFormat.PlainText)
        self._download_notice.setWordWrap(True)
        self._download_notice.setProperty("i18nSkipText", True)
        self._download_notice.hide()
        layout.addWidget(self._download_notice)
        self._download_notice_timer = QTimer(self)
        self._download_notice_timer.setSingleShot(True)
        self._download_notice_timer.timeout.connect(self._download_notice.hide)

        self._pages = QStackedWidget(self)
        self._error_page = QWidget(self._pages)
        error_layout = QVBoxLayout(self._error_page)
        error_layout.setContentsMargins(*(hig.PANEL_PADDING,) * 4)
        error_layout.addStretch()
        error_row = QHBoxLayout()
        error_row.addStretch()
        error_body = QWidget(self._error_page)
        error_body.setMaximumWidth(480)
        error_row.addWidget(error_body, stretch=1)
        error_row.addStretch()
        error_layout.addLayout(error_row)
        error_layout.addStretch()
        error_content = QVBoxLayout(error_body)
        error_content.setContentsMargins(0, 0, 0, 0)
        error_content.setSpacing(hig.ITEM_GAP)
        self._error_label = QLabel(tr("无法加载曲谱库。"))
        self._error_label.setObjectName("PanelTitle")
        self._error_detail = QLabel()
        self._error_detail.setObjectName("Muted")
        self._error_detail.hide()
        for label in (self._error_label, self._error_detail):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_content.addWidget(label)

        error_actions = QHBoxLayout()
        error_actions.setSpacing(hig.ITEM_GAP)
        error_actions.setContentsMargins(0, hig.CONTROL_GAP, 0, 0)
        error_actions.addStretch()
        self._retry_button = PillButton(tr("重新加载曲谱库"), "primary")
        error_actions.addWidget(self._retry_button)
        self._browser_button = PillButton(tr("用默认浏览器打开"))
        self._browser_button.setToolTip(tr("在浏览器中打开 BDO 曲谱库"))
        self._browser_button.clicked.connect(self._open_in_browser)
        error_actions.addWidget(self._browser_button)
        error_actions.addStretch()
        error_content.addLayout(error_actions)

        self._browser_error = QLabel(tr("无法启动默认浏览器。"))
        self._browser_error.setObjectName("Muted")
        self._browser_error.setWordWrap(True)
        self._browser_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._browser_error.hide()
        error_content.addWidget(self._browser_error)
        self._pages.addWidget(self._error_page)
        try:
            self._view = _create_library_view()
        except (ImportError, OSError):
            self._error_label.setText(tr("当前安装缺少内置浏览器组件。"))
            self._retry_button.hide()
            self._browser_button.setProperty("kind", "primary")
            self.retranslate_dynamic_content()
            layout.addWidget(self._pages)
            return

        self._container = QWidget.createWindowContainer(self._view, self._pages)
        self._container.setObjectName("OnlineScoreLibraryContainer")
        # The native QWebView rejects QWindow activation. Keep the wrapper
        # outside Qt's tab chain and let WebView2 manage its own input focus.
        self._container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pages.addWidget(self._container)
        self._pages.setCurrentWidget(self._container)

        layout.insertWidget(0, self._create_navigation())
        layout.addWidget(self._pages, stretch=1)

        self._load_timeout = QTimer(self)
        self._load_timeout.setSingleShot(True)
        self._load_timeout.setInterval(_LOAD_TIMEOUT_MS)
        self._load_timeout.timeout.connect(self._show_timeout_error)
        self._retry_button.clicked.connect(self._reload)
        self._view.loadingChanged.connect(self._loading_changed)
        self._view.urlChanged.connect(self._location_changed)
        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        buttons = (self._retry_button, self._browser_button)
        for button in buttons:
            button.ensurePolished()
        width = max(button.sizeHint().width() for button in buttons)
        for button in buttons:
            button.setFixedSize(width, hig.BUTTON_HEIGHT)
        self._origin = _library_start_url()
        if self.isVisible():
            self._load_current_language()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_current_language()
        if self._download_hooks_ready:
            self._download_timer.start()

    def hideEvent(self, event) -> None:
        if self._download_timer.isActive():
            self._poll_page_downloads()
            self._download_timer.stop()
        super().hideEvent(event)

    def _load_current_language(self) -> None:
        if self._view is not None and self._started_origin != self._origin:
            self._started_origin = self._origin
            self._start_load(self._origin)

    def _create_navigation(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("OnlineScoreLibraryNavigation")
        bar.setStyleSheet(
            f"QFrame#OnlineScoreLibraryNavigation {{ "
            f"background: {hig.PANEL}; border-bottom: 1px solid {hig.SEPARATOR}; }}"
        )
        navigation = QHBoxLayout(bar)
        navigation.setContentsMargins(hig.ITEM_GAP, hig.CONTROL_GAP, hig.ITEM_GAP, hig.CONTROL_GAP)
        navigation.setSpacing(hig.CONTROL_GAP)

        self._back = self._navigation_button("←", "网页后退")
        self._back.setEnabled(False)
        self._back.clicked.connect(self._view.goBack)
        navigation.addWidget(self._back)
        self._forward = self._navigation_button("→", "网页前进")
        self._forward.setEnabled(False)
        self._forward.clicked.connect(self._view.goForward)
        navigation.addWidget(self._forward)
        self._refresh_button = self._navigation_button("", "重新加载曲谱库", FluentSymbol.REFRESH)
        self._refresh_button.clicked.connect(self._reload)
        navigation.addWidget(self._refresh_button)

        navigation.addSpacing(hig.ITEM_GAP)
        self._host_label = QLabel(self._origin.host())
        self._host_label.setTextFormat(Qt.TextFormat.PlainText)
        navigation.addWidget(self._host_label)
        navigation.addStretch()
        self._loading_label = QLabel()
        self._loading_label.setObjectName("Muted")
        navigation.addWidget(self._loading_label)
        return bar

    @staticmethod
    def _navigation_button(text: str, label: str, symbol: FluentSymbol | None = None) -> PillButton:
        button = PillButton(text, "ghost", symbol)
        button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        button.setToolTip(tr(label))
        button.setAccessibleName(tr(label))
        return button

    def _begin_load(self) -> None:
        self._download_hooks_ready = False
        self._download_timer.stop()
        self._load_pending = True
        self._load_timeout.start()
        self._pages.setCurrentWidget(self._container)
        self._refresh_button.show()
        self._loading_label.setText(tr("正在加载曲谱库…"))

    def _start_load(self, url: QUrl) -> None:
        self._retry_url = url
        self._begin_load()
        self._view.setUrl(url)

    def _reload(self) -> None:
        if self._pages.currentWidget() is self._error_page:
            self._start_load(self._retry_url)
        else:
            self._begin_load()
            self._view.reload()

    def _location_changed(self, url: QUrl) -> None:
        self._update_location(url)
        if url.isValid():
            self._retry_url = url

    def _update_location(self, url: QUrl) -> None:
        self._host_label.setText(url.host() or self._origin.host())
        self._back.setEnabled(self._view.canGoBack())
        self._forward.setEnabled(self._view.canGoForward())

    def _show_timeout_error(self) -> None:
        self._show_load_error("等待内嵌浏览器响应超时。")

    def _show_load_error(self, detail: str) -> None:
        self._loading_label.clear()
        self._refresh_button.hide()
        self._browser_error.hide()
        self._error_detail.setText(tr(detail))
        self._error_detail.show()
        self._pages.setCurrentWidget(self._error_page)

    def _open_in_browser(self) -> None:
        self._browser_error.setVisible(not QDesktopServices.openUrl(self._origin))

    def show_download_notice(self, message: str, *, kind: str, duration_ms: int) -> None:
        color = hig.SUCCESS_TEXT if kind == "success" else hig.ERROR_TEXT
        self._download_notice.setStyleSheet(
            f"background: {hig.PANEL}; color: {color}; padding: 8px 12px; "
            f"border-bottom: 1px solid {hig.SEPARATOR};"
        )
        self._download_notice.setText(message)
        self._download_notice.show()
        self._download_notice_timer.start(duration_ms)
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self._download_notice, message))

    def _customize_loaded_page(self, url: QUrl) -> None:
        origin = QUrl(APP_WEBSITE_URL)
        if (url.scheme(), url.host(), url.port(443)) != (origin.scheme(), origin.host(), origin.port(443)):
            return
        self._view.runJavaScript(SETUP_LIBRARY_PAGE, lambda _: None)
        self._download_poll_pending = False
        self._download_hooks_ready = True
        if self.isVisible():
            self._download_timer.start()

    def _poll_page_downloads(self) -> None:
        if self._download_poll_pending or not self._download_hooks_ready:
            return
        self._download_poll_pending = True
        self._view.runJavaScript(READ_LIBRARY_DOWNLOADS, self._receive_page_downloads)

    def _receive_page_downloads(self, result: object) -> None:
        if not isValid(self):
            return
        self._download_poll_pending = False
        if not isinstance(result, str):
            return
        try:
            downloads = loads(result)
        except ValueError:
            return
        if isinstance(downloads, list):
            for url in downloads:
                if isinstance(url, str) and is_score_library_download_url(url):
                    self.download_requested.emit(QUrl(url))

    def _loading_changed(self, info: QWebViewLoadingInfo) -> None:
        status = info.status()
        load_status = info.LoadStatus
        self._update_location(info.url())
        if status == load_status.Started:
            if not self._load_pending:
                self._begin_load()
            return

        self._load_pending = False
        self._load_timeout.stop()
        if info.url().isValid():
            self._retry_url = info.url()
        if status == load_status.Failed:
            self._show_load_error(_load_error_detail(info.errorString()))
        else:
            self._loading_label.clear()
            self._refresh_button.show()
            if status == load_status.Succeeded:
                self._customize_loaded_page(info.url())
            self._pages.setCurrentWidget(self._container)
