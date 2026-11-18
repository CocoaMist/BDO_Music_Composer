"""Non-modal presentation for one signed background update."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.ui.i18n import localizer, tr, trf
from bdo_music_composer.update.manifest import UpdateManifest


def _active_locale() -> str:
    active = localizer()
    return str(active.language) if active is not None else "zh_CN"


class _StatusSummary(QLabel):
    """Reserve all wrapped lines next to a badge of fixed height."""

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.setMinimumHeight(max(0, self.heightForWidth(self.width())))


class SelfUpdateDialog(QDialog):
    """Show authenticated release notes without blocking background work."""

    def __init__(
        self,
        manifest: UpdateManifest,
        source: str,
        *,
        auto_download: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.source = str(source)
        self.auto_download = bool(auto_download)
        self._ready = False
        self._progress_percent: int | None = None
        self._release_notes = ""
        self.setObjectName("SelfUpdateDialog")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(620, 440)
        self.setMinimumSize(500, 340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("PanelTitle")
        layout.addWidget(self.title_label)

        self.source_label = QLabel()
        self.source_label.setObjectName("Muted")
        layout.addWidget(self.source_label)

        self.status_card = QFrame()
        self.status_card.setObjectName("SelfUpdateStatusCard")
        self.status_card.setProperty("uiRole", "statusCard")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(12, 8, 12, 8)
        status_layout.setSpacing(8)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_layout.addLayout(status_row)
        self.status_badge = QLabel()
        self.status_badge.setObjectName("SelfUpdateStatusBadge")
        self.status_badge.setProperty("uiRole", "statusBadge")
        status_row.addWidget(self.status_badge)
        self.status_summary = _StatusSummary()
        self.status_label = self.status_summary
        self.status_summary.setObjectName("SelfUpdateStatusSummary")
        self.status_summary.setWordWrap(True)
        status_row.addWidget(self.status_summary, stretch=1)
        self.progress_row = QWidget()
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("SelfUpdateProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar, stretch=1)
        self.progress_value = QLabel()
        self.progress_value.setObjectName("Muted")
        self.progress_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_layout.addWidget(self.progress_value)
        status_layout.addWidget(self.progress_row)
        layout.addWidget(self.status_card)

        self.notes_label = QLabel()
        self.notes_label.setObjectName("SectionLabel")
        layout.addWidget(self.notes_label)

        self.notes_view = QTextBrowser()
        self.notes_view.setObjectName("SelfUpdateNotes")
        self.notes_view.setOpenExternalLinks(False)
        self.notes_view.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.addWidget(self.notes_view, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.close_button = buttons.button(QDialogButtonBox.Close)
        buttons.rejected.connect(self.hide)
        layout.addWidget(buttons)
        self._render()

    def _render(self) -> None:
        version = str(self.manifest.version)
        self.setWindowTitle(trf("更新日志 · v{version}", version=version))
        self.title_label.setText(trf("更新日志 · v{version}", version=version))
        source_label = {"github": "GitHub", "gitee": "Gitee"}.get(
            self.source.casefold(),
            self.source,
        )
        self.source_label.setText(
            trf("更新来源：{source}", source=source_label)
        )
        self.notes_label.setText(tr("本次更新"))
        notes = self.manifest.localized_notes(_active_locale()).strip() or tr("此版本暂无详细说明。")
        if notes != self._release_notes:
            self._release_notes = notes
            self.notes_view.setPlainText(notes)
        self.close_button.setText(tr("稍后"))
        self._render_status()

    def _render_status(self) -> None:
        if self._ready:
            self.status_badge.setText(tr("已准备"))
            self.status_summary.setText(
                tr("更新包已通过验证；将在下次启动时自动安装。")
            )
        elif self.auto_download:
            self.status_badge.setText(tr("下载中"))
            self.status_summary.setText(tr("正在后台下载更新…"))
        else:
            self.status_badge.setText(tr("可更新"))
            self.status_summary.setText(tr("已发现新版本；可在软件更新设置中启用后台下载。"))
        self.progress_bar.setAccessibleName(self.status_badge.text())
        self._render_progress()

    def _render_progress(self) -> None:
        self.progress_row.setVisible(self._ready or self.auto_download)
        self.progress_value.setText(
            f"{self._progress_percent}%" if self._progress_percent is not None else ""
        )
        self.progress_value.setVisible(self._progress_percent is not None)
        if self._ready:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat(tr("准备完成"))
        elif self.auto_download:
            if self._progress_percent is None:
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat("")
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(self._progress_percent)
                self.progress_bar.setFormat(
                    trf("下载进度：{percent}%", percent=self._progress_percent)
                )

    def set_progress(self, downloaded: int, total: int) -> None:
        if self._ready or total <= 0:
            return
        percent = max(0, min(100, round(int(downloaded) * 100 / int(total))))
        if percent != self._progress_percent:
            self._progress_percent = percent
            self._render_progress()

    def set_ready(self) -> None:
        self._ready = True
        self._progress_percent = 100
        self._render_status()

    def retranslate_dynamic_content(self) -> None:
        self._render()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange:
            self._render()


__all__ = ["SelfUpdateDialog"]
