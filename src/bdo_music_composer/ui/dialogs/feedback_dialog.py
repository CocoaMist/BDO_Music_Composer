"""Player-initiated feedback and private receipt lookup."""

import json
import uuid

from PySide6.QtCore import QModelIndex, QPointF, QSignalBlocker, QSize, QTimer, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QColor, QFont, QFontMetrics, QPainter, QTextCharFormat
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QStackedWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from bdo_music_composer.app.diagnostic_report import DiagnosticReport, build_diagnostic_report
from bdo_music_composer.ui.feedback_status_qt import (
    FEEDBACK_PATH,
    FEEDBACK_TIMEOUT_MS,
    MAX_FEEDBACK_AVAILABILITY_BYTES,
    MAX_FEEDBACK_RESPONSE_BYTES,
    QUERY_CODE,
    STATUS_PATH,
    FeedbackStatusTracker,
    FeedbackTicket,
    feedback_network_enabled,
    get_feedback_availability,
    parse_feedback_availability,
    parse_feedback_ticket,
    post_feedback_json,
)
from bdo_music_composer.ui.floating_panel_qt import FloatingPanelDialog
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol
from bdo_music_composer.ui.ui_controls import PillButton


# Only applies to deployments that predate GET /v1/feedback.
FEEDBACK_SUBMISSIONS_OPEN = False
_SUBMISSIONS_PAUSED_NOTICE = "暂停接收新反馈。可查询已提交的反馈。"
_COMPOSE_PLACEHOLDER = "写下问题或建议。请勿填写个人信息。"
_LOOKUP_PRIVACY_HINT = "持有查询码的人可以查看回执。"

_STATUS_LABELS = {
    "submitted": "已提交，等待维护者查收。",
    "received": "维护者已查收，等待处理结果。",
    "resolved": "已发布处理结果。",
}

_MAILBOX_STATUS_LABELS = {
    "submitted": "已提交",
    "received": "已查收",
    "resolved": "已回复",
}

_UNREAD_ROLE = Qt.ItemDataRole.UserRole + 1


class _MailboxRowDelegate(QStyledItemDelegate):
    @staticmethod
    def _reference_font(font: QFont, unread: bool) -> QFont:
        primary = QFont(font)
        primary.setWeight(QFont.Weight.DemiBold if unread else QFont.Weight.Medium)
        return primary

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        row = QStyleOptionViewItem(option)
        self.initStyleOption(row, index)
        primary = self._reference_font(row.font, bool(index.data(_UNREAD_ROLE)))
        height = QFontMetrics(primary).height() + row.fontMetrics.height()
        return QSize(0, max(44, height + hig.CONTROL_GAP + hig.ITEM_GAP))

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex,
    ) -> None:
        row = QStyleOptionViewItem(option)
        self.initStyleOption(row, index)
        reference, _, status = index.data(Qt.ItemDataRole.DisplayRole).partition("\n")
        row.text = ""
        style = row.widget.style() if row.widget is not None else QApplication.style()
        painter.save()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, row, painter, row.widget)
        painter.restore()

        unread = bool(index.data(_UNREAD_ROLE))
        bounds = row.rect.adjusted(hig.PANEL_PADDING + hig.ITEM_GAP, 0, -hig.GROUP_GAP, 0)
        primary_font = self._reference_font(row.font, unread)
        painter.save()
        painter.setClipRect(row.rect, Qt.ClipOperation.IntersectClip)
        painter.setFont(primary_font)
        primary_metrics = painter.fontMetrics()
        painter.setFont(row.font)
        secondary_metrics = painter.fontMetrics()
        text_height = primary_metrics.height() + secondary_metrics.height() + hig.CONTROL_GAP
        top = bounds.y() + (bounds.height() - text_height) // 2

        if unread:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(hig.ACCENT))
            point = QPointF(row.rect.left() + hig.GROUP_GAP, top + primary_metrics.height() / 2)
            painter.drawEllipse(point, 2.5, 2.5)
        painter.setFont(primary_font)
        painter.setPen(QColor(hig.TEXT))
        painter.drawText(
            QPointF(bounds.x(), top + primary_metrics.ascent()),
            primary_metrics.elidedText(reference, Qt.TextElideMode.ElideRight, bounds.width()),
        )
        painter.setFont(row.font)
        painter.setPen(QColor(hig.SECONDARY_TEXT))
        painter.drawText(
            QPointF(bounds.x(), top + primary_metrics.height() + hig.CONTROL_GAP + secondary_metrics.ascent()),
            secondary_metrics.elidedText(status, Qt.TextElideMode.ElideRight, bounds.width()),
        )
        painter.restore()


class _ReadingFooter(QFrame):
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_notice()

    def fit_notice(self) -> None:
        if self.layout() is not None and self.width() > 0:
            # The stack can claim space at the footer's one-line minimum
            # before translations have wrapped at the actual column width.
            height = self.heightForWidth(self.width())
            self.setMinimumHeight(max(0, height))


class FeedbackDialog(FloatingPanelDialog):
    def __init__(
        self, parent: QWidget | None = None, *, tracker: FeedbackStatusTracker | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FeedbackDialog")
        self.setProperty("uiSurface", "utility")
        self.setWindowTitle(tr("反馈"))
        self.resize(840, 510)
        self.setMinimumSize(716, 420)
        self._manager = QNetworkAccessManager(self)
        self._deadline = QTimer(self, singleShot=True, interval=FEEDBACK_TIMEOUT_MS)
        self._deadline.timeout.connect(self._abort)
        self._reply = None
        self._availability_reply: QNetworkReply | None = None
        self._availability_deadline = QTimer(self, singleShot=True, interval=FEEDBACK_TIMEOUT_MS)
        self._availability_deadline.timeout.connect(self._abort_availability)
        self._availability_failed = False
        self._request_submitted: bool | None = None
        self._last_submission = None
        self._diagnostic: DiagnosticReport | None = None
        self._online = feedback_network_enabled()
        self._submissions_open = False
        self._tracker = tracker
        self._displayed_ticket: FeedbackTicket | None = None
        self._displayed_code: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self._panel_header())

        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._mailbox_rail())
        self._tabs = QStackedWidget()
        self._tabs.setObjectName("FeedbackMailStack")
        self._tabs.addWidget(self._submission_page())
        self._tabs.addWidget(self._lookup_page())
        self._tabs.currentChanged.connect(self._mark_displayed_seen)
        self._tabs.currentChanged.connect(self._sync_navigation)
        reading_area = QVBoxLayout()
        reading_area.setSpacing(0)
        reading_area.addWidget(self._tabs, 1)
        self._notice = QLabel()
        self._notice.setObjectName("FeedbackMailNotice")
        self._notice.setWordWrap(True)
        self._reading_footer = _ReadingFooter()
        self._reading_footer.setObjectName("FeedbackReadingFooter")
        self._reading_footer.setProperty("uiRole", "dialogFooter")
        footer_policy = self._reading_footer.sizePolicy()
        footer_policy.setHeightForWidth(True)
        self._reading_footer.setSizePolicy(footer_policy)
        footer = QVBoxLayout(self._reading_footer)
        footer.setContentsMargins(hig.SECTION_GAP, hig.ITEM_GAP, hig.SECTION_GAP, hig.ITEM_GAP)
        footer.setSpacing(hig.ITEM_GAP)
        footer.addWidget(self._notice)
        self._compose_footer = QWidget()
        actions = QHBoxLayout(self._compose_footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(hig.ITEM_GAP)
        actions.addWidget(self._attach)
        actions.addStretch(1)
        actions.addWidget(self._send)
        footer.addWidget(self._compose_footer)
        reading_area.addWidget(self._reading_footer)
        body.addLayout(reading_area, 1)
        layout.addLayout(body, 1)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        if self._tracker is not None:
            self._tracker.receipts_changed.connect(self._refresh_history)
        self._refresh_history()
        self._set_notice()
        self._sync_navigation()
        if self._online:
            self._message.setFocus()
        else:
            self._open_lookup()

    def _panel_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("FeedbackPanelHeader")
        header.setProperty("uiRole", "dialogHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(hig.SECTION_GAP, hig.ITEM_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        label = QLabel(tr("反馈"))
        label.setProperty("uiRole", "dialogTitle")
        close_button = PillButton("", "ghost", FluentSymbol.CLOSE)
        close_button.setObjectName("FloatingPanelClose")
        close_button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close_button.setAccessibleName(tr("关闭窗口"))
        close_button.setToolTip(tr("关闭窗口"))
        close_button.clicked.connect(self.reject)
        layout.addWidget(label, 1)
        layout.addWidget(close_button)
        return header

    def _mailbox_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("FeedbackMailRail")
        rail.setFixedWidth(192)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        actions = QFrame()
        actions.setObjectName("FeedbackMailRailActions")
        action_rows = QVBoxLayout(actions)
        action_rows.setContentsMargins(hig.ITEM_GAP, hig.GROUP_GAP, hig.ITEM_GAP, hig.CONTROL_GAP)
        action_rows.setSpacing(hig.CONTROL_GAP)
        self._compose_action = PillButton(tr("写反馈"), "ghost", FluentSymbol.FEEDBACK)
        self._compose_action.setObjectName("FeedbackMailCompose")
        self._compose_action.clicked.connect(self._open_composer)
        self._lookup_action = PillButton(tr("查回执"), "ghost", FluentSymbol.INFO)
        self._lookup_action.setObjectName("FeedbackMailLookup")
        self._lookup_action.clicked.connect(self._open_lookup)
        for action in (self._compose_action, self._lookup_action):
            action.setCheckable(True)
            action.setFixedHeight(hig.BUTTON_HEIGHT)
            action_rows.addWidget(action)
        layout.addWidget(actions)

        title = QLabel(tr("收件箱"))
        title.setObjectName("FeedbackMailboxTitle")
        title.setContentsMargins(hig.PANEL_PADDING, hig.GROUP_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        layout.addWidget(title)
        self._history = QListWidget()
        self._history.setObjectName("FeedbackMailbox")
        self._history.setProperty("i18nSkipItems", True)
        self._history.setAccessibleName(tr("收件箱"))
        self._history.setFrameShape(QFrame.Shape.NoFrame)
        self._history.setSpacing(1)
        self._history.setItemDelegate(_MailboxRowDelegate(self._history))
        self._history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history.currentRowChanged.connect(self._select_history)
        self._history.itemClicked.connect(self._reopen_history_item)
        self._history.itemActivated.connect(self._reopen_history_item)
        layout.addWidget(self._history, 1)
        self._empty = QLabel(tr("暂无反馈记录"))
        self._empty.setObjectName("FeedbackMailboxEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        self._empty.setContentsMargins(hig.PANEL_PADDING, hig.ITEM_GAP, hig.PANEL_PADDING, hig.GROUP_GAP)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty, 1)
        layout.addSpacing(hig.PANEL_PADDING)
        return rail

    def _submission_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FeedbackComposePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.SECTION_GAP, hig.PANEL_PADDING)
        layout.setSpacing(hig.ITEM_GAP)
        self._message = QPlainTextEdit()
        self._message.setObjectName("FeedbackComposeText")
        self._message.setMinimumHeight(72)
        self._message.setAccessibleName(tr("写反馈"))
        self._message.setAccessibleDescription(tr(_COMPOSE_PLACEHOLDER))
        self._message.setPlaceholderText(tr(_COMPOSE_PLACEHOLDER))
        layout.addWidget(self._message, 1)

        self._attach = QCheckBox(tr("附上诊断日志"))
        preview = QPlainTextEdit()
        self._attachment_preview = preview
        preview.setObjectName("FeedbackAttachmentPreview")
        preview.setReadOnly(True)
        preview.setAccessibleName(tr("诊断日志"))
        preview.setMinimumHeight(56)
        preview.setMaximumHeight(116)
        preview.setVisible(False)
        self._attach.toggled.connect(self._toggle_attachment)
        layout.addWidget(preview)

        self._send = PillButton(tr("提交反馈"), "convert")
        self._send.setObjectName("FeedbackSend")
        self._send.setEnabled(self._online and self._submissions_open)
        self._send.clicked.connect(self._submit)
        self._message.textChanged.connect(self._update_send_label)
        self._attach.toggled.connect(self._update_send_label)
        return page

    def _lookup_page(self) -> QFrame:
        page = QFrame()
        page.setObjectName("FeedbackReadPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.SECTION_GAP, hig.PANEL_PADDING)
        layout.setSpacing(hig.ITEM_GAP)
        self._read_header = QWidget()
        header = QHBoxLayout(self._read_header)
        header.setContentsMargins(0, 0, 0, 0)
        self._read_heading = QLabel()
        self._read_heading.setObjectName("FeedbackReadHeading")
        self._read_heading.setTextFormat(Qt.TextFormat.PlainText)
        self._read_heading.setWordWrap(True)
        header.addWidget(self._read_heading, 1)
        self._copy_code = PillButton(tr("复制查询码"), "ghost")
        self._copy_code.setObjectName("FeedbackCopyCode")
        self._copy_code.setToolTip(tr(_LOOKUP_PRIVACY_HINT))
        self._copy_code.clicked.connect(lambda: QApplication.clipboard().setText(self._code.text().strip()))
        header.addWidget(self._copy_code)
        self._read_header.hide()

        self._lookup_bar = QFrame()
        self._lookup_bar.setObjectName("FeedbackLookupBar")
        lookup_layout = QHBoxLayout(self._lookup_bar)
        lookup_layout.setContentsMargins(0, 0, 0, 0)
        lookup_layout.setSpacing(hig.ITEM_GAP)
        self._code = QLineEdit()
        self._code.setObjectName("FeedbackQueryCode")
        self._code.setMaxLength(64)
        self._code.setPlaceholderText(tr("查询码"))
        self._code.setAccessibleName(tr("查询码"))
        self._code.setAccessibleDescription(tr(_LOOKUP_PRIVACY_HINT))
        self._code.setToolTip(tr(_LOOKUP_PRIVACY_HINT))
        lookup_layout.addWidget(self._code, 1)
        self._code.textEdited.connect(self._lookup_text_edited)
        self._lookup = PillButton(tr("查询"))
        self._lookup.setObjectName("FeedbackLookupSubmit")
        self._lookup.setEnabled(self._online)
        self._lookup.clicked.connect(self._query)
        self._code.returnPressed.connect(self._query)
        lookup_layout.addWidget(self._lookup)
        layout.addWidget(self._lookup_bar)
        layout.addWidget(self._read_header)

        self._status = QLabel()
        self._status.setObjectName("FeedbackReadStatus")
        self._status.setWordWrap(True)
        self._status.hide()
        layout.addWidget(self._status)
        self._result = QPlainTextEdit()
        self._result.setObjectName("FeedbackReadText")
        self._result.setReadOnly(True)
        self._result.setFrameShape(QFrame.Shape.NoFrame)
        self._result.setAccessibleName(tr("处理结果"))
        self._result.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._result.document().setDocumentMargin(0)
        policy = self._result.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self._result.setSizePolicy(policy)
        self._result.hide()
        layout.addWidget(self._result, 1)
        return page

    def _sync_navigation(self) -> None:
        composing = self._tabs.currentIndex() == 0
        self._compose_action.setChecked(composing)
        self._lookup_action.setChecked(not composing and not self._lookup_bar.isHidden())
        self._compose_footer.setVisible(composing)
        self._send.setVisible(composing and self._submissions_open)
        self._reading_footer.setVisible(composing or not self._notice.isHidden())

    def _open_composer(self) -> None:
        self._history.setCurrentRow(-1)
        self._tabs.setCurrentIndex(0)
        self._sync_navigation()
        self._set_notice()
        self._message.setFocus()

    def _open_lookup(self) -> None:
        self._history.setCurrentRow(-1)
        self._clear_displayed_ticket()
        self._lookup_bar.show()
        self._tabs.setCurrentIndex(1)
        self._sync_navigation()
        self._set_notice()
        self._code.setFocus()
        self._code.selectAll()

    def _clear_displayed_ticket(self) -> None:
        self._displayed_ticket = None
        self._displayed_code = None
        self._read_header.hide()
        self._status.clear()
        self._status.hide()
        self._result.clear()
        self._result.hide()

    def _lookup_text_edited(self, text: str) -> None:
        if self._displayed_code is not None and text.strip().lower() != self._displayed_code:
            self._clear_displayed_ticket()
        self._set_notice()

    def _set_notice(self, text: str | None = None) -> None:
        if text is None:
            composing = self._tabs.currentIndex() == 0
            if self._request_submitted == composing or (composing and self._availability_reply is not None):
                text = tr("正在连接反馈服务…")
            elif not self._online:
                text = tr("反馈服务暂未启用。")
            elif composing and self._availability_failed:
                text = tr("连接失败，请稍后重试。")
            elif composing and not self._submissions_open:
                text = tr(_SUBMISSIONS_PAUSED_NOTICE)
            else:
                text = ""
        changed = self._notice.text() != text
        self._notice.setText(text)
        self._notice.setVisible(bool(text))
        self._reading_footer.setVisible(self._tabs.currentIndex() == 0 or bool(text))
        self._reading_footer.fit_notice()
        if changed and text and self._notice.isVisible():
            QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self._notice, text))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._tracker is not None and self._tracker.receipts:
            receipt = next((item for item in self._tracker.receipts if item.unread), self._tracker.receipts[0])
            self._show_saved(receipt.code)
            self._history.setFocus(Qt.FocusReason.OtherFocusReason)
        self._check_availability()

    def _check_availability(self) -> None:
        if not self._online or self._availability_reply is not None:
            return
        self._submissions_open = False
        self._availability_failed = False
        reply = get_feedback_availability(self._manager)
        self._availability_reply = reply
        reply.readyRead.connect(self._bound_availability)
        reply.finished.connect(self._finish_availability)
        self._availability_deadline.start()
        self._sync_navigation()
        self._set_request_busy(self._reply is not None)
        if self._tabs.currentIndex() == 0:
            self._set_notice()

    def _bound_availability(self) -> None:
        reply = self._availability_reply
        if reply is not None and reply.bytesAvailable() > MAX_FEEDBACK_AVAILABILITY_BYTES:
            reply.abort()

    def _abort_availability(self) -> None:
        if self._availability_reply is not None:
            self._availability_reply.abort()

    def _finish_availability(self) -> None:
        reply, self._availability_reply = self._availability_reply, None
        if reply is None:
            return
        self._availability_deadline.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        available = None
        if status == 200 and reply.error() == QNetworkReply.NetworkError.NoError:
            available = parse_feedback_availability(bytes(reply.read(MAX_FEEDBACK_AVAILABILITY_BYTES + 1)))
        elif status in (404, 405):
            available = FEEDBACK_SUBMISSIONS_OPEN
        reply.deleteLater()
        self._submissions_open = available is True
        self._availability_failed = available is None
        self._sync_navigation()
        self._set_request_busy(self._reply is not None)
        if self._tabs.currentIndex() == 0:
            self._set_notice()

    def _refresh_history(self) -> None:
        current_item = self._history.currentItem()
        current_code = current_item.data(Qt.ItemDataRole.UserRole) if current_item is not None else None
        receipts = self._tracker.receipts if self._tracker is not None else ()
        with QSignalBlocker(self._history):
            self._history.setAccessibleName(tr("收件箱"))
            self._history.clear()
            for receipt in sorted(receipts, key=lambda receipt: not receipt.unread):
                label = trf("反馈编号 {id}", id=receipt.ticket.reference)
                status = tr(_STATUS_LABELS[receipt.ticket.status])
                reference = f"#{receipt.ticket.reference}"
                short_status = tr(_MAILBOX_STATUS_LABELS[receipt.ticket.status])
                row = QListWidgetItem(f"{reference}\n{short_status}")
                row.setData(Qt.ItemDataRole.UserRole, receipt.code)
                row.setData(_UNREAD_ROLE, receipt.unread)
                row.setData(Qt.ItemDataRole.AccessibleTextRole, f"{tr('未读')} · {label}" if receipt.unread else label)
                row.setData(Qt.ItemDataRole.AccessibleDescriptionRole, status)
                row.setToolTip(f"{label}\n{status}")
                self._history.addItem(row)
            self._history.setCurrentRow(self._history_row(current_code))
        self._history.setVisible(bool(receipts))
        self._empty.setVisible(not receipts)

    def _history_row(self, code: str | None) -> int:
        for row in range(self._history.count()):
            if self._history.item(row).data(Qt.ItemDataRole.UserRole) == code:
                return row
        return -1

    def _select_history(self, index: int) -> None:
        if index >= 0:
            code = self._history.item(index).data(Qt.ItemDataRole.UserRole)
            if isinstance(code, str):
                self._show_saved(code)

    def _reopen_history_item(self, item: QListWidgetItem) -> None:
        if self._tracker is None:
            return
        code = item.data(Qt.ItemDataRole.UserRole)
        receipt = self._tracker.receipt(code)
        if receipt is not None and (code != self._displayed_code or receipt.ticket != self._displayed_ticket):
            self._show_saved(code)

    def _show_saved(self, code: str) -> None:
        if self._tracker is None:
            return
        receipt = self._tracker.receipt(code)
        if receipt is None:
            return
        with QSignalBlocker(self._history):
            self._history.setCurrentRow(self._history_row(code))
        self._code.setText(code)
        self._lookup_bar.hide()
        self._set_notice("")
        self._present_ticket(receipt.ticket, code)
        self._tabs.setCurrentIndex(1)
        self._sync_navigation()
        self._mark_displayed_seen()

    def _mark_displayed_seen(self) -> None:
        if (self._tracker is None or self._displayed_code is None
                or not self.isVisible() or self._tabs.currentIndex() != 1):
            return
        receipt = self._tracker.receipt(self._displayed_code)
        if receipt is not None and receipt.ticket == self._displayed_ticket:
            self._tracker.mark_seen(receipt)

    def retranslate_dynamic_content(self) -> None:
        self._message.setPlaceholderText(tr(_COMPOSE_PLACEHOLDER))
        self._refresh_history()
        if self._displayed_ticket is not None:
            self._present_ticket(self._displayed_ticket, self._displayed_code)
        if self._reply is None and self._tabs.currentIndex() == 0 and not self._submissions_open:
            self._set_notice()
        self._reading_footer.fit_notice()

    def _update_send_label(self) -> None:
        only_log = self._attach.isChecked() and not self._message.toPlainText().strip()
        self._send.setText(tr("提交诊断日志") if only_log else tr("提交反馈"))

    def _toggle_attachment(self, enabled: bool) -> None:
        if enabled and self._diagnostic is None:
            self._diagnostic = build_diagnostic_report()
            self._attachment_preview.setPlainText(json.dumps(self._diagnostic, indent=2))
        self._attachment_preview.setVisible(enabled)

    def _submit(self) -> None:
        if not self._submissions_open:
            self._set_notice()
            return
        message = self._message.toPlainText().strip()
        if len(message.encode("utf-16-le")) > 2400:
            self._set_notice(tr("请输入反馈内容，长度最多 1200 个字符。"))
            return
        attach = self._attach.isChecked()
        diagnostic = self._diagnostic if attach else None
        if not message and not (diagnostic and diagnostic["log"]):
            self._set_notice(tr("请填写反馈，或勾选并提交已有的诊断日志。"))
            return
        draft = (message, attach)
        if not self._last_submission or self._last_submission[0] != draft:
            self._last_submission = (draft, uuid.uuid4().hex)
        code = self._last_submission[1]
        self._code.setText(code)
        self._post(FEEDBACK_PATH, {
            "code": code,
            "message": message,
            "diagnostic": diagnostic,
        }, submitted=True)

    def _query(self) -> None:
        if not self._online or self._reply is not None:
            return
        code = self._code.text().strip().lower()
        self._clear_displayed_ticket()
        if not QUERY_CODE.fullmatch(code):
            self._set_notice(tr("请输入有效的查询码。"))
            return
        self._post(STATUS_PATH, {"code": code}, submitted=False)

    def _post(self, path: str, payload: dict, *, submitted: bool) -> None:
        if not self._online or self._reply is not None:
            return
        if submitted and not self._submissions_open:
            return
        reply = post_feedback_json(self._manager, path, payload)
        self._reply = reply
        self._request_submitted = submitted
        reply.readyRead.connect(lambda: self._check_size(reply))
        reply.finished.connect(lambda: self._finish(reply, submitted, payload["code"]))
        self._set_request_busy(True)
        self._set_notice()
        self._deadline.start()

    def _set_request_busy(self, busy: bool) -> None:
        submitting = busy and self._request_submitted is True
        self._send.setEnabled(self._online and self._submissions_open and not busy)
        self._lookup.setEnabled(self._online and not busy)
        self._message.setReadOnly(submitting)
        self._code.setReadOnly(busy)
        self._history.setEnabled(not busy)
        self._attach.setEnabled(not submitting)

    def _check_size(self, reply: QNetworkReply) -> None:
        if reply is self._reply and reply.bytesAvailable() > MAX_FEEDBACK_RESPONSE_BYTES:
            reply.abort()

    def _abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def done(self, result: int) -> None:
        availability_reply, self._availability_reply = self._availability_reply, None
        self._availability_deadline.stop()
        if availability_reply is not None:
            availability_reply.abort()
            availability_reply.deleteLater()
        reply, self._reply = self._reply, None
        self._request_submitted = None
        self._deadline.stop()
        if reply is not None:
            reply.abort()
            reply.deleteLater()
            self._set_request_busy(False)
            self._set_notice()
        super().done(result)

    def _finish(self, reply: QNetworkReply, submitted: bool, code: str) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        self._request_submitted = None
        self._deadline.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        ticket = None
        paused = False
        if status in (200, 201) and reply.error() == QNetworkReply.NetworkError.NoError:
            ticket = parse_feedback_ticket(bytes(reply.read(MAX_FEEDBACK_RESPONSE_BYTES + 1)))
        elif submitted and status == 503:
            body = bytes(reply.read(MAX_FEEDBACK_RESPONSE_BYTES + 1))
            if len(body) <= MAX_FEEDBACK_RESPONSE_BYTES:
                try:
                    paused = json.loads(body) == {"error": "submissions_paused"}
                except (ValueError, RecursionError):
                    pass
        reply.deleteLater()
        if paused:
            self._submissions_open = False
            self._sync_navigation()
        self._set_request_busy(False)
        if paused:
            self._set_notice()
            return
        on_request_page = (self._tabs.currentIndex() == 0) == submitted
        if status == 404:
            if on_request_page:
                self._set_notice(tr("没有查到这条反馈。"))
            return
        if status == 429:
            if on_request_page:
                self._set_notice(tr("反馈服务已达接收上限，请稍后再试。"))
            return
        if ticket is not None:
            self._present_ticket(ticket, code)
            self._lookup_bar.hide()
            if submitted:
                self._tabs.setCurrentIndex(1)
            self._sync_navigation()
            self._set_notice()
            if self._tracker is not None:
                shown = self.isVisible() and self._tabs.currentIndex() == 1
                self._tracker.observe(code, ticket, register=True, shown=shown)
                if shown:
                    with QSignalBlocker(self._history):
                        self._history.setCurrentRow(self._history_row(code))
            if submitted:
                self._message.clear()
                self._attach.setChecked(False)
                self._last_submission = None
                self._copy_code.setFocus()
            return
        if on_request_page:
            self._set_notice(tr("连接失败，请稍后重试。"))

    def _present_ticket(self, ticket: FeedbackTicket, code: str | None) -> None:
        self._displayed_ticket = ticket
        self._displayed_code = code
        self._read_heading.setText(trf("反馈编号 {id}", id=ticket.reference))
        self._read_header.show()
        self._status.setText(tr(_STATUS_LABELS[ticket.status]))
        self._status.show()
        sections = [(tr("维护者消息"), message.body) for message in ticket.messages]
        if ticket.result:
            sections.append((tr("处理结果"), ticket.result))
        self._result.clear()
        self._result.setVisible(bool(sections))
        cursor = self._result.textCursor()
        heading = QTextCharFormat()
        heading.setFontWeight(QFont.Weight.DemiBold)
        body = QTextCharFormat()
        cursor.beginEditBlock()
        for index, (label, message) in enumerate(sections):
            if index:
                cursor.insertText("\n\n", body)
            cursor.insertText(label, heading)
            cursor.insertText(f"\n{message}", body)
        cursor.endEditBlock()
        self._result.verticalScrollBar().setValue(0)
