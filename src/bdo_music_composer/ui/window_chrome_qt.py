"""Windows caption controls, window shape, and native hit testing."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QStyle, QStyleOptionFrame, QStylePainter, QVBoxLayout, QWidget,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol


WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDBLCLK = 0x00A3
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
HTTOPLEFT, HTTOPRIGHT, HTBOTTOM = 13, 14, 15
HTBOTTOMLEFT, HTBOTTOMRIGHT = 16, 17
RESIZE_MARGIN = 6
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
SWP_FRAMECHANGED = 0x0020
SWP_KEEP_GEOMETRY = 0x0001 | 0x0002 | 0x0004 | 0x0010
MONITOR_DEFAULTTONEAREST = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWA_COLOR_NONE = 0xFFFFFFFE


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


class ScoreTitleEdit(QLineEdit):
    """Show the start of long score names while keeping the full edit value."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("i18nSkipToolTip", True)
        self.textChanged.connect(self.setToolTip)

    def paintEvent(self, event) -> None:
        if self.hasFocus() or not self.text():
            super().paintEvent(event)
            return
        option = QStyleOptionFrame()
        self.initStyleOption(option)
        contents = self.style().subElementRect(QStyle.SE_LineEditContents, option, self)
        contents = contents.adjusted(2, 0, -2, 0)
        painter = QStylePainter(self)
        painter.drawPrimitive(QStyle.PE_PanelLineEdit, option)
        title = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, contents.width())
        painter.drawItemText(
            contents, Qt.AlignLeading | Qt.AlignVCenter, option.palette,
            self.isEnabled(), title, QPalette.Text,
        )


class _WorkspaceEdge(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def fit(self, rect: QRect) -> None:
        self.setGeometry(rect)
        radius = hig.WORKSPACE_RADIUS
        # Keep the overlay off the page itself. Only the border and corner
        # squares participate in composition as the editor repaints underneath.
        edge = QRegion(0, 0, rect.width(), 1)
        edge |= QRegion(0, rect.height() - 1, rect.width(), 1)
        edge |= QRegion(0, 0, 1, rect.height())
        edge |= QRegion(rect.width() - 1, 0, 1, rect.height())
        for x in (0, rect.width() - radius):
            for y in (0, rect.height() - radius):
                edge |= QRegion(x, y, radius, radius)
        self.setMask(edge)

    def paintEvent(self, event) -> None:
        rect = QRectF(self.rect())
        cutouts = QPainterPath()
        cutouts.addRect(rect)
        cutouts.addRoundedRect(rect, hig.WORKSPACE_RADIUS, hig.WORKSPACE_RADIUS)
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillPath(cutouts, QColor(hig.PANEL))
            painter.setPen(QPen(QColor(hig.SEPARATOR), 1))
            painter.drawRoundedRect(
                rect.adjusted(0.5, 0.5, -0.5, -0.5),
                hig.WORKSPACE_RADIUS - 0.5,
                hig.WORKSPACE_RADIUS - 0.5,
            )


class WorkspaceSurface(QWidget):
    """Content sheet below the separate title bar, inset inside the shell."""

    def __init__(self) -> None:
        super().__init__()
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(hig.WINDOW_SHELL))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget(self)
        self.pages.setObjectName("MainPages")
        layout.addWidget(self.pages)
        self._edge = _WorkspaceEdge(self)
        self._edge.hide()

    def set_framed(self, framed: bool) -> None:
        inset = hig.WORKSPACE_INSET if framed else 0
        self.layout().setContentsMargins(inset, inset, inset, inset)
        self._edge.setVisible(framed)
        if framed:
            self._fit_edge()
        self.update()

    def _fit_edge(self) -> None:
        self._edge.fit(self.rect().marginsRemoved(self.layout().contentsMargins()))

    def paintEvent(self, event) -> None:
        if self._edge.isHidden():
            return
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(hig.PANEL))
            painter.drawRoundedRect(
                QRectF(self.rect()), hig.WORKSPACE_OUTER_RADIUS, hig.WORKSPACE_OUTER_RADIUS,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._edge.isHidden():
            self._fit_edge()


class WindowChrome(QObject):
    def __init__(self, window, drag_surface: QFrame, workspace: WorkspaceSurface) -> None:
        super().__init__(window)
        self.window = window
        self.drag_surface = drag_surface
        self.workspace = workspace
        self.controls: QFrame | None = None
        if QApplication.platformName() != "windows":
            return

        self._user32 = ctypes.windll.user32
        self._screen_to_client = self._user32.ScreenToClient
        self._screen_to_client.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        self._screen_to_client.restype = wintypes.BOOL
        self._user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        self._user32.GetWindowLongW.restype = ctypes.c_long
        self._user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        self._user32.SetWindowPos.argtypes = (
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        )
        self._user32.IsZoomed.argtypes = (wintypes.HWND,)
        self._user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        self._user32.MonitorFromWindow.restype = wintypes.HMONITOR
        self._user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
        self._set_dwm_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        self._set_dwm_attribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        )
        self._set_dwm_attribute.restype = ctypes.c_long
        window.setWindowFlag(Qt.FramelessWindowHint, True)
        window.installEventFilter(self)
        self.controls = QFrame(drag_surface)
        self.controls.setObjectName("WindowChrome")
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(hig.ITEM_GAP, 0, 0, 0)
        row.setSpacing(0)
        self.minimize_button = self._button(FluentSymbol.MINIMIZE, "最小化", window.showMinimized)
        self.maximize_button = self._button(FluentSymbol.MAXIMIZE, "最大化", self.toggle_maximized)
        self.close_button = self._button(FluentSymbol.CLOSE, "关闭窗口", window.close)
        self.close_button.setObjectName("WindowChromeClose")
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            row.addWidget(button)
        self._sync_maximize_button()

    def _button(self, symbol: FluentSymbol, label: str, action) -> QPushButton:
        button = QPushButton()
        set_fluent_symbol(button, symbol)
        button.setFixedSize(hig.WINDOW_CONTROL_WIDTH, hig.CAPTION_BUTTON_HEIGHT)
        button.setAccessibleName(tr(label))
        button.setToolTip(tr(label))
        button.clicked.connect(action)
        return button

    def toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def _sync_maximize_button(self) -> None:
        maximized = self.window.isMaximized()
        label = tr("还原窗口" if maximized else "最大化")
        symbol = FluentSymbol.RESTORE if maximized else FluentSymbol.MAXIMIZE
        set_fluent_symbol(self.maximize_button, symbol)
        self.maximize_button.setAccessibleName(label)
        self.maximize_button.setToolTip(label)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.window:
            if event.type() == QEvent.Show:
                self._enable_native_resize(int(self.window.winId()))
                self._sync_outline()
            elif event.type() == QEvent.WindowStateChange:
                self._sync_maximize_button()
                self._sync_outline()
        return False

    def _sync_outline(self) -> None:
        rounded = not (self.window.isMaximized() or self.window.isFullScreen())
        self.workspace.set_framed(rounded)
        hwnd = int(self.window.winId())
        color = QColor(hig.WINDOW_OUTLINE)
        border = color.red() | (color.green() << 8) | (color.blue() << 16)
        for attribute, value in (
            (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND if rounded else DWMWCP_DONOTROUND),
            (DWMWA_BORDER_COLOR, border if rounded else DWMWA_COLOR_NONE),
        ):
            parameter = wintypes.DWORD(value)
            self._set_dwm_attribute(hwnd, attribute, ctypes.byref(parameter), ctypes.sizeof(parameter))

    def _enable_native_resize(self, hwnd: int) -> None:
        style = self._user32.GetWindowLongW(hwnd, GWL_STYLE)
        if not style & WS_THICKFRAME:
            # Keep the system sizing loop with a frameless client area.
            self._user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_THICKFRAME)
            self._user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0, SWP_KEEP_GEOMETRY | SWP_FRAMECHANGED,
            )

    def _fit_maximized_client(self, hwnd, address: int) -> None:
        if not self._user32.IsZoomed(hwnd):
            return
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        monitor = self._user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if self._user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            client = wintypes.RECT.from_address(address)
            client.left = max(client.left, info.work.left)
            client.top = max(client.top, info.work.top)
            client.right = min(client.right, info.work.right)
            client.bottom = min(client.bottom, info.work.bottom)

    def native_event(self, message) -> int | None:
        if self.controls is None:
            return None
        event = wintypes.MSG.from_address(int(message))
        if event.message == WM_NCCALCSIZE and event.wParam:
            self._fit_maximized_client(event.hWnd, event.lParam)
            return 0
        if event.message == WM_NCLBUTTONDBLCLK and event.wParam == HTCAPTION:
            self.toggle_maximized()
            return 0
        if event.message != WM_NCHITTEST:
            return None

        point = wintypes.POINT(
            ctypes.c_short(event.lParam & 0xffff).value,
            ctypes.c_short((event.lParam >> 16) & 0xffff).value,
        )
        if not self._screen_to_client(event.hWnd, ctypes.byref(point)):
            return None
        scale = self.window.devicePixelRatioF()
        position = QPoint(round(point.x / scale), round(point.y / scale))
        if not (self.window.isMaximized() or self.window.isFullScreen()):
            edge = self._resize_edge(position)
            if edge is not None:
                return edge
        toolbar_point = self.drag_surface.mapFrom(self.window, position)
        if self.drag_surface.rect().contains(toolbar_point):
            child = self.drag_surface.childAt(toolbar_point)
            if child is None or isinstance(child, (QFrame, QLabel)):
                return HTCAPTION
        return None

    def _resize_edge(self, point: QPoint) -> int | None:
        left = point.x() < RESIZE_MARGIN
        right = point.x() >= self.window.width() - RESIZE_MARGIN
        if point.y() < RESIZE_MARGIN:
            return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
        if point.y() >= self.window.height() - RESIZE_MARGIN:
            return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
        return HTLEFT if left else HTRIGHT if right else None
