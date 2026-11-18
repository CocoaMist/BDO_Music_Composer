"""Download activity in the Home library."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidgetItem, QVBoxLayout

from bdo_music_composer.ui.home_widgets import HomeEntryDelegate, HomeListWidget
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.score_library_downloads import ScoreLibraryDownload, ScoreLibraryDownloads
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.ui_controls import PillButton


_PREVIEW_ROWS = 5
_ROW_HEIGHT = 56
_REFRESH_INTERVAL_MS = 80


class HomeDownloadsPage(QFrame):
    content_size_changed = Signal()
    score_open_requested = Signal(object)

    def __init__(self, downloads: ScoreLibraryDownloads) -> None:
        super().__init__()
        self.setObjectName("HomeCard")
        self._downloads = downloads
        self._query = ""
        self._rendered_query = ""
        self._entries: dict[str, ScoreLibraryDownload] = {}
        self._items: dict[str, QListWidgetItem] = {}
        self._labels_dirty = False
        self._layout_key: tuple[int, bool] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.ITEM_GAP)
        self._empty = QLabel()
        self._empty.setObjectName("HomeEmptyState")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._empty.setWordWrap(True)
        self._empty.setMinimumHeight(64)
        layout.addWidget(self._empty)

        self._list = HomeListWidget()
        self._list.setObjectName("HomeList")
        self._list.setProperty("i18nSkipItems", True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._list.setAccessibleName(tr("下载"))
        self._list.setItemDelegate(HomeEntryDelegate(None, self._list))
        self._list.setUniformItemSizes(True)
        self._list.currentItemChanged.connect(self._sync_actions)
        self._list.itemActivated.connect(self._open_score_item)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self._list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self._open_current_score)
        layout.addWidget(self._list)

        footer = QHBoxLayout()
        footer.setSpacing(hig.CONTROL_GAP)
        self._folder_notice = QLabel()
        self._folder_notice.setObjectName("HomeDownloadNotice")
        self._folder_notice.setWordWrap(True)
        footer.addWidget(self._folder_notice, stretch=1)
        self._entry_action = self._footer_button("")
        self._entry_action.clicked.connect(self._run_entry_action)
        footer.addWidget(self._entry_action)
        self._folder_action = self._footer_button(tr("打开下载文件夹"))
        self._folder_action.clicked.connect(self._open_folder)
        self._folder_action.setEnabled(False)
        footer.addWidget(self._folder_action)
        layout.addLayout(footer)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh)
        downloads.changed.connect(self._schedule_refresh)
        self._refresh()
        self._sync_folder_action()

    @staticmethod
    def _footer_button(text: str) -> PillButton:
        button = PillButton(text, "ghost")
        button.setObjectName("HomeLibraryAction")
        button.setFixedHeight(hig.BUTTON_HEIGHT)
        return button

    def set_query(self, query: str) -> None:
        if query != self._query:
            self._query = query
            if self.isVisible():
                self._refresh()

    def retranslate_dynamic_content(self) -> None:
        self._labels_dirty = True
        if self.isVisible():
            self._refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()
        self._sync_folder_action()

    def hideEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().hideEvent(event)

    def _schedule_refresh(self) -> None:
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh(self) -> None:
        entries = self._downloads.entries
        previous = self._entries
        self._entries = {entry.id: entry for entry in entries}
        for entry_id in self._items.keys() - self._entries.keys():
            item = self._items.pop(entry_id)
            self._list.takeItem(self._list.row(item))

        query_changed = self._query != self._rendered_query
        visible_count = 0
        latest_visible = None
        for entry in entries:
            old_entry = previous.get(entry.id)
            item = self._items.get(entry.id)
            if item is None:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, entry.id)
                item.setSizeHint(QSize(0, _ROW_HEIGHT))
                self._items[entry.id] = item
                self._list.insertItem(0, item)
            if self._labels_dirty or entry != old_entry:
                status = self._status_text(entry)
                item.setText(f"{entry.name}\n{status}")
                tooltip = f"{entry.name}\n{status}"
                if entry.error and entry.state == "failed":
                    tooltip += f"\n{entry.error}"
                item.setToolTip(tooltip)
            visible = not self._query or self._query in entry.name.casefold()
            if query_changed or old_entry is None or entry.name != old_entry.name:
                item.setHidden(not visible)
            if visible:
                visible_count += 1
                latest_visible = item

        self._labels_dirty = False
        self._rendered_query = self._query
        empty = not visible_count
        preview_rows = min(_PREVIEW_ROWS, visible_count)
        self._empty.setText(tr("没有匹配的结果" if self._query else "暂无下载"))
        self._empty.setVisible(empty)
        self._list.setVisible(not empty)
        selected = self._list.currentItem()
        if latest_visible is not None and (selected is None or selected.isHidden()):
            self._list.setCurrentItem(latest_visible)
        self._sync_actions()
        if self._entries.keys() != previous.keys():
            self._sync_folder_action()
        layout_key = (preview_rows, empty)
        if self._layout_key != layout_key:
            self._layout_key = layout_key
            if preview_rows:
                self._list.set_preview_height(preview_rows * _ROW_HEIGHT)
            self.updateGeometry()
            self.content_size_changed.emit()

    @staticmethod
    def _status_text(entry: ScoreLibraryDownload) -> str:
        if entry.state == "completed":
            return tr("下载完成")
        if entry.state == "failed":
            return tr("下载失败")
        if entry.state == "cancelled":
            return tr("已取消")
        received = QLocale().formattedDataSize(entry.received)
        if entry.total > 0:
            return trf(
                "下载中 · {received} / {total} · {percent}%",
                received=received,
                total=QLocale().formattedDataSize(entry.total),
                percent=min(100, 100 * entry.received // entry.total),
            )
        return trf("下载中 · {received}", received=received)

    def _current_entry(self) -> ScoreLibraryDownload | None:
        item = self._list.currentItem()
        if item is None or item.isHidden():
            return None
        return self._entries.get(item.data(Qt.ItemDataRole.UserRole))

    def _sync_actions(self, *_args) -> None:
        entry = self._current_entry()
        label = ""
        if self._completed_score(entry) is not None:
            label = "打开曲谱"
        elif entry is not None:
            if entry.state == "downloading":
                label = "取消下载"
            elif entry.state in {"failed", "cancelled"}:
                label = "重新下载"
        self._entry_action.setVisible(bool(label))
        self._entry_action.setText(tr(label) if label else "")

    def _sync_folder_action(self) -> None:
        self._folder_action.setEnabled(self._downloads.directory.is_dir())

    @staticmethod
    def _completed_score(entry: ScoreLibraryDownload | None) -> Path | None:
        if entry is None or entry.state != "completed" or entry.path is None:
            return None
        return entry.path if entry.path.suffix.casefold() in {".bdo", ".bdom"} else None

    def _open_score_item(self, item: QListWidgetItem) -> None:
        self._request_open_score(self._entries.get(item.data(Qt.ItemDataRole.UserRole)))

    def _open_current_score(self) -> None:
        self._request_open_score(self._current_entry())

    def _request_open_score(self, entry: ScoreLibraryDownload | None) -> None:
        if (score := self._completed_score(entry)) is not None:
            self.score_open_requested.emit(score)

    def _run_entry_action(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        if entry.state == "downloading":
            self._downloads.cancel(entry.id)
        elif entry.state in {"failed", "cancelled"}:
            self._downloads.retry(entry.id)
        elif entry.state == "completed":
            self._request_open_score(entry)

    def _open_folder(self) -> None:
        entry = self._current_entry()
        path = entry.path if entry is not None else None
        directory = path.parent if path is not None else self._downloads.directory
        opened = directory.is_dir() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        self._folder_notice.setText("" if opened else tr("无法打开下载文件夹"))
