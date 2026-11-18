"""Credits and license presentation for About."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QShowEvent, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.app.application_metadata import GITHUB_REPOSITORY_URL
from bdo_music_composer.core.content_boundary import (
    CONTENT_BOUNDARY_PARAGRAPHS,
    CONTENT_BOUNDARY_TITLE,
)
from bdo_music_composer.core.third_party_credits import (
    BASIC_PITCH_LICENSE_URL,
    BASIC_PITCH_MODEL_URL,
    BASIC_PITCH_NOTICE_URL,
    CREDIT_ENTRIES,
    CREDIT_SECTION_SOURCES,
    RESEARCH_CITATIONS,
)
from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig


THIRD_PARTY_NOTICES_URL = (
    f"{GITHUB_REPOSITORY_URL}/blob/master/THIRD_PARTY_NOTICES.md"
)


def _credits_html(*, dark_theme: bool) -> str:
    """Build the translated, escaped HTML used by the credits browser."""

    body_color = hig.SECONDARY_TEXT if dark_theme else "#454651"
    heading_color = hig.TEXT if dark_theme else "#20222b"
    link_color = hig.SELECTION_INDICATOR if dark_theme else "#245992"
    section_sources = dict(CREDIT_SECTION_SOURCES)
    credit_sections: list[str] = []
    for section_key, _source in CREDIT_SECTION_SOURCES:
        rows = []
        for entry in CREDIT_ENTRIES:
            if entry.section != section_key:
                continue
            rows.append(
                '<p class="credit">'
                f"<b>{escape(entry.name)}</b><br>"
                f"{escape(tr('许可证'))}: "
                f"{escape(tr(entry.license_label))}<br>"
                f'<a href="{escape(entry.github_url)}">'
                f"{escape(entry.github_url)}</a>"
                "</p>"
            )
        credit_sections.append(
            f"<h2>{escape(tr(section_sources[section_key]))}</h2>"
            + "".join(rows)
        )

    citation_rows = []
    for citation in RESEARCH_CITATIONS:
        citation_rows.append(
            '<p class="credit">'
            f"<b>{escape(citation.name)}</b><br>"
            f"{escape(citation.citation)}<br>"
            f'<a href="{escape(citation.github_url)}">'
            f"{escape(citation.github_url)}</a><br>"
            f'<a href="{escape(citation.publication_url)}">'
            f"{escape(tr('论文'))}: {escape(citation.publication_url)}</a>"
            "</p>"
        )

    return f"""
        <style>
            body {{ color: {body_color}; font-size: 13px; margin: 0; }}
            h2 {{ color: {heading_color}; font-size: 15px; margin-top: 20px; margin-bottom: 6px; }}
            p {{ margin: 7px 0; line-height: 150%; }}
            b {{ color: {heading_color}; }}
            a {{ color: {link_color}; text-decoration: underline; }}
            .credit {{ margin-bottom: 11px; }}
        </style>
        <h2>{escape(tr("社区、测试与音乐交流"))}</h2>
        <p>• <b>CN Server · Rainbow Club / 彩虹乐队</b></p>
        <p>• <b>{escape(tr("开源维护者、文档作者、测试者与社区玩家"))}</b></p>
        <p>{escape(tr("ChatGPT 协助开发。配置 DeepSeek 后，曲谱助手可使用其模型。"))}</p>

        <h2>{escape(tr(CONTENT_BOUNDARY_TITLE))}</h2>
        {''.join(f'<p>{escape(tr(paragraph))}</p>' for paragraph in CONTENT_BOUNDARY_PARAGRAPHS)}

        <h2>{escape(tr("Basic Pitch 代码与模型许可"))}</h2>
        <p>{escape(tr("Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。"))}</p>
        <p>
          <a href="{escape(BASIC_PITCH_MODEL_URL)}">nmp.onnx · GitHub</a><br>
          <a href="{escape(BASIC_PITCH_LICENSE_URL)}">LICENSE · GitHub</a><br>
          <a href="{escape(BASIC_PITCH_NOTICE_URL)}">NOTICE · GitHub</a>
        </p>

        {''.join(credit_sections)}

        <h2>{escape(tr("论文引用"))}</h2>
        {''.join(citation_rows)}

        <h2>{escape(tr("完整许可清单"))}</h2>
        <p>{escape(tr("这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。"))}</p>
        <p><a href="{THIRD_PARTY_NOTICES_URL}">{THIRD_PARTY_NOTICES_URL}</a></p>
    """


class AcknowledgementsPane(QFrame):
    """Searchable credits and notices."""

    def __init__(
        self,
        *,
        dark_theme: bool,
        defer_document: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dark_theme = dark_theme
        self._document_loaded = not defer_document
        self.setObjectName("ThanksTextPanel")
        self.setProperty("uiRole", "dialogBody")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 18)
        layout.setSpacing(hig.GROUP_GAP)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("ThanksSearch")
        self.search_edit.setPlaceholderText(tr("搜索致谢与许可证"))
        self.search_edit.setAccessibleName(tr("搜索致谢与许可证"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._find_next)
        self.search_edit.installEventFilter(self)
        search_row.addWidget(self.search_edit, stretch=1)
        find_button = QPushButton(tr("查找下一个"))
        find_button.setObjectName("ThanksFindNext")
        find_button.clicked.connect(self._find_next)
        find_button.setEnabled(False)
        self.search_edit.textChanged.connect(lambda text: find_button.setEnabled(bool(text.strip())))
        search_row.addWidget(find_button)
        layout.addLayout(search_row)

        self.search_status = QLabel(tr("没有匹配的结果"))
        self.search_status.setProperty("uiRole", "dialogSubtitle")
        self.search_status.hide()
        self.search_edit.textChanged.connect(self.search_status.hide)
        layout.addWidget(self.search_status)

        self.credits_browser = QTextBrowser()
        self.credits_browser.setObjectName("ThanksText")
        self.credits_browser.setFrameShape(QFrame.NoFrame)
        self.credits_browser.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.credits_browser.document().setDocumentMargin(16)
        self.credits_browser.setReadOnly(True)
        self.credits_browser.setOpenExternalLinks(True)
        self.retranslate_dynamic_content()
        layout.addWidget(self.credits_browser, stretch=1)

    def retranslate_dynamic_content(self) -> None:
        if self._document_loaded:
            self.credits_browser.document().setDefaultFont(QApplication.font())
            self.credits_browser.setHtml(_credits_html(dark_theme=self._dark_theme))
        self.search_status.hide()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._document_loaded:
            self._document_loaded = True
            self.retranslate_dynamic_content()

    def copy_credits(self) -> None:
        QApplication.clipboard().setText(
            self.credits_browser.toPlainText().strip()
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.search_edit
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            # Keep the search key from reaching the dialog's default button.
            self.search_edit.returnPressed.emit()
            return True
        return super().eventFilter(watched, event)

    def _find_next(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        document = self.credits_browser.document()
        match = document.find(query, self.credits_browser.textCursor())
        if match.isNull():
            match = document.find(query)
        self.search_status.setVisible(match.isNull())
        if not match.isNull():
            self.credits_browser.setTextCursor(match)


__all__ = ["AcknowledgementsPane", "THIRD_PARTY_NOTICES_URL"]
