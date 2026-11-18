"""Shared composition conversation for docked and floating views."""

from __future__ import annotations

from collections.abc import Callable
from math import ceil

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QStackedWidget,
    QVBoxLayout, QWidget,
)

from bdo_music_composer.app.score_agent_settings import (
    DEEPSEEK_MODEL_NAMES, get_session_model_connection, set_session_model_connection,
)
from bdo_music_composer.creation.brief import CreationAction
from bdo_music_composer.creation.score_agent_tools import AgentProposal
from bdo_music_composer.ui.dialogs.creation_assistant_dialog import ACTION_LABELS, ERROR_LABELS
from bdo_music_composer.ui.dialogs.score_agent_settings_dialog import ScoreAgentSettingsDialog
from bdo_music_composer.ui.i18n import localizer, tr, trf
from bdo_music_composer.ui.score_agent_cards_qt import ScoreAgentCards
from bdo_music_composer.ui.score_agent_qt import MAX_INSTRUCTION, MAX_REPLY_LENGTH, ScoreAgent
from bdo_music_composer.ui.score_agent_scope_qt import (
    ScoreAgentCapture, ScoreAgentScope, ScoreAgentScopeError,
)
from bdo_music_composer.ui.score_agent_transcript_qt import ScoreAgentTranscript
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import set_fluent_symbol
from bdo_music_composer.ui.theme.symbols import FluentSymbol, draw_symbol
from bdo_music_composer.ui.ui_controls import ElidedLabel, PillButton


_ERROR_LABELS = {
    "invalid_connection": "请检查模型连接设置。",
    "authentication": "模型服务未接受此密钥。",
    "billing": "模型服务余额不足或需要账单设置。",
    "invalid_model": "请检查接口地址和模型 ID。",
    "invalid_model_request": "模型服务拒绝了请求参数。",
    "rate_limited": "模型服务正在限流，请稍后再试。",
    "timeout": "Agent 等待模型或工具超时。",
    "invalid_response": "模型返回了无法处理的结果。",
    "response_truncated": "回复达到输出上限，已保留已收到的内容。",
    "service_unavailable": "模型服务暂时不可用，请稍后重试。",
    "content_filtered": "模型服务过滤了本次回复。",
    "redirected": "服务返回了重定向。请直接填写最终 API 地址。",
    "tool_limit": "本轮工具调用已达上限，请缩小任务范围。",
    "invalid": "这次请求超出了模型支持的范围。",
    "unsupported_score_meter_or_tempo": "创作助手目前支持 2/4 到 6/4 拍。",
    "invalid_selection": "工程或选区已变化，请重新选择。",
    "stale_audio_scope": "工程或选区已变化，请重新选择。",
    "empty_time_selection": "时间范围和选区没有交集。",
    "score_evidence_too_large": "选区音符过多，请缩小范围后重试。",
    "invalid_search_query": "请在“联网搜索”后输入 128 字以内的搜索主题。",
    "search_unavailable": "联网搜索需要 DeepSeek 官方连接。",
    "search_not_used": "本轮未完成联网搜索，请重试。",
}
_STALE = "工程已修改，请重新分析后再应用建议。"
_STALE_SELECTION = "选区已变化，请在当前范围重新生成建议。"
_ANALYZE_STARTER = ("分析乐句", "分析当前选区的乐句、节奏和力度，标明值得试听的小节。", FluentSymbol.NOTES_PANEL)
_AUDIO_STARTER = ("对照参考音频", "对照当前选区与参考音频，标出起音和需要试听的位置。", FluentSymbol.CURVE)
_BACKING_PROMPT = "给当前选区试写一段简单伴奏，保留原有主旋律。"
_EFFORT_LABELS = {"low": "低强度推理", "high": "高强度推理", "max": "最高强度推理"}


class _AgentPrompt(QPlainTextEdit):
    submitted = Signal()
    focus_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._compact = False
        self._composing = False
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self._fit_height()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._fit_height()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fit_height()

    def _fit_height(self) -> None:
        lines = ceil(self.document().documentLayout().documentSize().height())
        limit = 3 if self._compact else 5
        line_height = self.fontMetrics().lineSpacing()
        desired = line_height * max(1, min(lines, limit)) + 2 * hig.ITEM_GAP
        height = max(36 if self._compact else 42, desired)
        if self.minimumHeight() != height:
            self.setFixedHeight(height)

    def inputMethodEvent(self, event) -> None:
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._composing = False
        self.focus_changed.emit(False)

    def keyPressEvent(self, event) -> None:
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier)
            and not self._composing
        ):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ScoreAgentPanel(QFrame):
    proposal_ready = Signal(object, object)
    edit_seek_requested = Signal(str, float, object)
    floating_requested = Signal()
    expand_requested = Signal()
    dismiss_requested = Signal()

    def __init__(
        self,
        capture: Callable[[], ScoreAgentCapture],
        is_current: Callable[[ScoreAgentCapture], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._capture = capture
        self._is_current = is_current
        self._agent = ScoreAgent(self)
        self._scope = ScoreAgentScope(error="请先打开或新建曲谱。")
        self._stamp: tuple[str, int] | None = None
        self._turn: ScoreAgentCapture | None = None
        self._applying: tuple[ScoreAgentCapture, AgentProposal] | None = None
        self._last_edit: tuple[tuple, dict] | None = None
        self._receipt_id = 0
        self._edit_locations: dict[int, tuple[str, float, int | None]] = {}
        self._source_id = 0
        self._source_urls: dict[int, QUrl] = {}
        self._pending_sources: list[tuple[int, str, QUrl]] = []
        self._pending_text = ""
        self._displayed = 0
        self._streaming = False
        self._chat_status = ""
        self._floating = False
        self._compact = False
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.setInterval(50)
        self._flush.timeout.connect(self._flush_text)
        self.setObjectName("ScoreAgentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(hig.GROUP_GAP,) * 4)
        layout.setSpacing(hig.CONTROL_GAP)
        self._panel_layout = layout

        self.chat_tab = QWidget()
        self.chat_tab.setObjectName("ScoreAgentConversation")

        corner = QWidget()
        corner.setObjectName("ScoreAgentActions")
        head = QHBoxLayout(corner)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(hig.CONTROL_GAP)
        heading = QLabel(tr("创作 Agent"))
        heading.setObjectName("WorkbenchTrackTitle")
        head.addWidget(heading, 1)
        self.new_button = self._icon_button("新建对话", FluentSymbol.NEW_PROJECT, self._clear_conversation)
        self.float_button = self._icon_button("浮动对话", FluentSymbol.POPOUT, self.floating_requested.emit)
        self.close_button = self._icon_button("关闭对话", FluentSymbol.CLOSE, self.dismiss_requested.emit)
        self.close_button.setObjectName("ScoreAgentClose")
        head.addWidget(self.new_button)
        head.addWidget(self.float_button)
        head.addWidget(self.close_button)
        self._conversation_header = corner
        layout.addWidget(corner)
        layout.addWidget(self.chat_tab, 1)
        self._build_chat()

        self._agent.delta.connect(self._delta)
        self._agent.tools_started.connect(self._tools_started)
        self._agent.web_sources.connect(self._record_web_sources)
        self._agent.web_search_started.connect(lambda: self._set_status("正在联网搜索…"))
        self._agent.busy_changed.connect(self._busy_changed)
        self._agent.completed.connect(self._completed)
        self._agent.failed.connect(self._failed)
        self._refresh_controls()
        self._refresh_model_label()

    @staticmethod
    def _icon_button(label: str, icon: FluentSymbol, handler) -> PillButton:
        button = PillButton("", "ghost", icon)
        button.setAutoDefault(False)
        button.setAccessibleName(tr(label))
        button.setToolTip(tr(label))
        button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        button.clicked.connect(handler)
        return button

    def _build_chat(self) -> None:
        chat = QVBoxLayout(self.chat_tab)
        chat.setContentsMargins(0, hig.CONTROL_GAP, 0, 0)
        chat.setSpacing(hig.GROUP_GAP)
        self._chat_layout = chat
        self.reading = QStackedWidget()
        self.reading.setObjectName("ScoreAgentReading")
        self.transcript = ScoreAgentTranscript()
        self.transcript.setObjectName("ScoreAgentTranscript")
        self.transcript.setAccessibleName(tr("创作对话"))
        self._cards = ScoreAgentCards(self.transcript.document())
        self.transcript.anchorClicked.connect(self._edit_anchor_clicked)
        self.transcript.anchorClicked.connect(self._source_anchor_clicked)
        self._build_empty_chat()
        self.reading.addWidget(self.empty_chat)
        self.reading.addWidget(self.transcript)
        self.transcript.textChanged.connect(self._show_chat_content)
        reading_lane = QHBoxLayout()
        reading_lane.setContentsMargins(hig.ITEM_GAP, 0, hig.ITEM_GAP, 0)
        reading_lane.addWidget(self.reading)
        chat.addLayout(reading_lane, 1)
        self.status = QLabel()
        self.status.setObjectName("ScoreAgentStatus")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setProperty("i18nSkipText", True)
        self.status.setWordWrap(True)
        self.status.hide()
        chat.addWidget(self.status)

        self.composer_area = QWidget()
        composer_area = QVBoxLayout(self.composer_area)
        composer_area.setContentsMargins(0, 0, 0, 0)
        composer_area.setSpacing(hig.CONTROL_GAP)
        context = QFrame()
        context.setObjectName("ScoreAgentContext")
        context_row = QHBoxLayout(context)
        context_row.setContentsMargins(hig.ITEM_GAP, 0, hig.ITEM_GAP, hig.CONTROL_GAP)
        context_row.setSpacing(hig.CONTROL_GAP)
        context_icon = QLabel()
        context_icon.setPixmap(draw_symbol(FluentSymbol.MARQUEE, hig.SECONDARY_TEXT, 15))
        context_row.addWidget(context_icon)
        self.scope_label = self._context_label()
        context_row.addWidget(self.scope_label, 1)
        self.audio_label = self._context_label()
        self.audio_label.setObjectName("ScoreAgentAudio")
        self.audio_label.setMaximumWidth(148)
        context_row.addWidget(self.audio_label, 0, Qt.AlignVCenter)
        composer_area.addWidget(context)

        self.composer = QFrame()
        self.composer.setObjectName("ScoreAgentComposer")
        compose = QVBoxLayout(self.composer)
        compose.setContentsMargins(hig.GROUP_GAP, hig.ITEM_GAP, hig.ITEM_GAP, hig.ITEM_GAP)
        compose.setSpacing(hig.CONTROL_GAP)
        self.prompt = _AgentPrompt()
        self.prompt.setObjectName("ScoreAgentPrompt")
        self.prompt.setTabChangesFocus(True)
        self.prompt.setPlaceholderText(tr("描述想写或调整的地方…"))
        self.prompt.setAccessibleName(tr("给 Agent 的指令"))
        self.prompt.setToolTip(tr("按 Enter 发送，按 Shift+Enter 换行。查网页可输入“联网搜索 主题”。"))
        self.prompt.submitted.connect(self._submit)
        self.prompt.textChanged.connect(self._refresh_send)
        self.prompt.focus_changed.connect(self._prompt_focus_changed)
        compose.addWidget(self.prompt)
        footer = QHBoxLayout()
        footer.setSpacing(hig.CONTROL_GAP)
        self.settings_button = PillButton("", "ghost", FluentSymbol.SETTINGS)
        self.settings_button.setObjectName("ScoreAgentModelPicker")
        self.settings_button.setProperty("i18nSkipText", True)
        self.settings_button.setProperty("i18nSkipToolTip", True)
        self.settings_button.setProperty("i18nSkipAccessibleName", True)
        self.settings_button.setAutoDefault(False)
        self.settings_button.clicked.connect(self._configure)
        footer.addWidget(self.settings_button)
        footer.addStretch(1)
        self.send_button = PillButton("", "convert", FluentSymbol.SEND)
        self.send_button.setObjectName("ScoreAgentSend")
        self.send_button.setFixedSize(36, 36)
        self.send_button.setAutoDefault(False)
        self.send_button.clicked.connect(self._send_or_stop)
        footer.addWidget(self.send_button)
        compose.addLayout(footer)
        composer_area.addWidget(self.composer)
        self.disclosure = QLabel()
        self.disclosure.setObjectName("ScoreAgentDisclosure")
        self.disclosure.setProperty("i18nSkipText", True)
        self.disclosure.setWordWrap(True)
        composer_area.addWidget(self.disclosure)
        chat.addWidget(self.composer_area)

    def _build_empty_chat(self) -> None:
        self.empty_chat = QWidget()
        self.empty_chat.setObjectName("ScoreAgentEmpty")
        layout = QVBoxLayout(self.empty_chat)
        layout.setContentsMargins(hig.ITEM_GAP, hig.ITEM_GAP, hig.ITEM_GAP, hig.ITEM_GAP)
        layout.setSpacing(hig.ITEM_GAP)
        layout.addStretch(1)
        self.empty_title = QLabel(tr("从当前曲谱开始"))
        self.empty_title.setObjectName("WorkbenchPanelMessageTitle")
        self.empty_title.setWordWrap(True)
        self.empty_title.setProperty("i18nSkipText", True)
        layout.addWidget(self.empty_title)
        self.empty_hint = QLabel()
        self.empty_hint.setObjectName("WorkbenchPanelMessageBody")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setProperty("i18nSkipText", True)
        layout.addWidget(self.empty_hint)
        self.starters = QWidget()
        starter_layout = QHBoxLayout(self.starters)
        starter_layout.setContentsMargins(0, 0, 0, 0)
        starter_layout.setSpacing(hig.CONTROL_GAP)
        self.analysis_starter = PillButton("", "ghost", _ANALYZE_STARTER[2])
        self.analysis_starter.setProperty("i18nSkipText", True)
        self.analysis_starter.setProperty("i18nSkipToolTip", True)
        self.analysis_starter.clicked.connect(self._draft_analysis)
        backing_starter = PillButton(tr("试写伴奏"), "ghost", FluentSymbol.ADD_TRACK)
        backing_starter.setToolTip(tr(_BACKING_PROMPT))
        backing_starter.clicked.connect(lambda: self._draft_starter(_BACKING_PROMPT))
        for button in (self.analysis_starter, backing_starter):
            button.setObjectName("ScoreAgentStarter")
            button.setAutoDefault(False)
            starter_layout.addWidget(button)
        starter_layout.addStretch()
        layout.addWidget(self.starters)
        layout.addStretch(2)

    def _show_chat_content(self) -> None:
        self.reading.setCurrentWidget(self.empty_chat if self.transcript.document().isEmpty() else self.transcript)

    def _draft_analysis(self) -> None:
        self._draft_starter(self._analysis_starter_content()[1])

    def _analysis_starter_content(self) -> tuple[str, str, FluentSymbol]:
        return _AUDIO_STARTER if self._scope.reference_audio == "attached" else _ANALYZE_STARTER

    def _draft_starter(self, source: str) -> None:
        if not self.prompt.toPlainText().strip():
            self.prompt.setPlainText(tr(source))
            self.prompt.moveCursor(QTextCursor.MoveOperation.End)
        self.prompt.setFocus()

    def _prompt_focus_changed(self, active: bool) -> None:
        self.composer.setProperty("promptFocused", active)
        style = self.composer.style()
        style.unpolish(self.composer)
        style.polish(self.composer)
        self.composer.update()

    @staticmethod
    def _context_label() -> ElidedLabel:
        label = ElidedLabel("")
        label.setObjectName("WorkbenchMuted")
        label.setTextFormat(Qt.PlainText)
        label.setProperty("i18nSkipText", True)
        label.setProperty("i18nSkipToolTip", True)
        return label

    def set_scope(self, scope: ScoreAgentScope, stamp: tuple[str, int]) -> None:
        if (scope, stamp) == (self._scope, self._stamp):
            return
        if self._stamp is not None and stamp[0] != self._stamp[0]:
            self._clear_conversation()
            self.prompt.clear()
        self._scope, self._stamp = scope, stamp
        self._refresh_controls()

    @property
    def follows_playhead(self) -> bool:
        return self._scope.track_id is not None and not self._scope.explicit_range

    def open(self) -> None:
        self._refresh_model_label()
        self.prompt.setFocus()

    def set_floating_caption(self, caption: QHBoxLayout | None) -> None:
        floating = self._floating = caption is not None
        actions = caption if floating else self._conversation_header.layout()
        actions.insertWidget(1, self.new_button)
        self.float_button.setVisible(not floating)
        self.close_button.setVisible(not floating)
        self._conversation_header.setVisible(not floating)
        if not floating:
            self.set_floating_compact(False)
        self.new_button.setVisible(not self._compact)

    def set_floating_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        focused = self.prompt.hasFocus()
        self._compact = compact
        if compact:
            self._panel_layout.addWidget(self.composer_area)
        else:
            self._chat_layout.addWidget(self.composer_area)
        vertical_margin = hig.CONTROL_GAP if compact else hig.GROUP_GAP
        self._panel_layout.setContentsMargins(hig.GROUP_GAP, vertical_margin, hig.GROUP_GAP, vertical_margin)
        self._conversation_header.setVisible(not compact and not self._floating)
        self.new_button.setVisible(not compact)
        self.chat_tab.setVisible(not compact)
        self.prompt.set_compact(compact)
        self.composer_area.show()
        self.disclosure.setVisible(not compact and not self._scope.error)
        if focused:
            self.prompt.setFocus()

    def retranslate_dynamic_content(self) -> None:
        self.status.setText(tr(self._chat_status) if self._chat_status else "")
        self.prompt.setPlaceholderText(tr("描述想写或调整的地方…"))
        self.prompt.setToolTip(tr("按 Enter 发送，按 Shift+Enter 换行。查网页可输入“联网搜索 主题”。"))
        self._refresh_controls()
        self._refresh_model_label()

    def _refresh_model_label(self) -> None:
        connection = get_session_model_connection()
        if connection is None:
            name = tr("模型连接")
        elif connection.is_official_deepseek:
            model = DEEPSEEK_MODEL_NAMES.get(connection.model, connection.model)
            mode = tr(_EFFORT_LABELS[connection.reasoning_effort] if connection.thinking else "快速回复")
            name = f"{model} · {mode}"
        else:
            name = connection.model
        self.settings_button.setToolTip(name)
        self.settings_button.setAccessibleName(name)
        self._fit_model_label()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "settings_button"):
            self._fit_model_label()

    def _fit_model_label(self) -> None:
        surrounding_width = (
            2 * hig.GROUP_GAP + 4 * hig.ITEM_GAP + 2 * hig.CONTROL_GAP
            + self.settings_button.iconSize().width() + self.send_button.width()
        )
        available = max(0, self.width() - surrounding_width)
        name = self.settings_button.accessibleName()
        self.settings_button.setText(self.settings_button.fontMetrics().elidedText(name, Qt.ElideRight, available))

    def _refresh_controls(self) -> None:
        current_scope = self._scope.label()
        turn = self._turn if self._agent.busy else None
        active_scope = turn.scope if turn else self._scope
        self.scope_label.setText(trf("本轮范围 · {scope}", scope=turn.scope.label()) if turn else current_scope)
        audio_status = {
            "attached": "参考音频已关联",
            "relink_required": "参考音频待重新关联",
        }.get(active_scope.reference_audio, "")
        self.audio_label.setText(tr(audio_status))
        self.audio_label.setVisible(bool(audio_status))
        self.disclosure.setText(tr(
            "发送后，模型可按需获取必要的曲谱信息与参考音频分析。" if active_scope.reference_audio == "attached"
            else "发送后，模型会收到你的指令及当前选区的必要曲谱信息。"
        ))
        self.disclosure.setVisible(not self._compact and not active_scope.error)
        self._refresh_empty_chat()
        self._refresh_send()

    def _refresh_empty_chat(self) -> None:
        self.empty_title.setVisible(not self._scope.error)
        self.empty_title.setText(tr("从当前曲谱开始"))
        hint = (
            "对照参考音频检查演奏，或为旋律试写伴奏。"
            if self._scope.reference_audio == "attached"
            else "从选区分析乐句，或为旋律试写伴奏。"
        )
        self.empty_hint.setVisible(not self._scope.error)
        self.empty_hint.setText(tr(hint))
        label, instruction, symbol = self._analysis_starter_content()
        self.analysis_starter.setText(tr(label))
        self.analysis_starter.setToolTip(tr(instruction))
        if self.analysis_starter.property("fluentSymbol") != symbol.value:
            set_fluent_symbol(self.analysis_starter, symbol)

    def _refresh_send(self) -> None:
        busy = self._agent.busy
        applying = self._applying is not None
        action = tr("停止 Agent" if busy else "发送")
        symbol = FluentSymbol.STOP if busy else FluentSymbol.SEND
        if self.send_button.property("fluentSymbol") != symbol.value:
            set_fluent_symbol(self.send_button, symbol)
        self.send_button.setAccessibleName(action)
        tooltip = f"{action}\n{tr(self._chat_status)}" if busy and self._chat_status else action
        self.send_button.setToolTip(tooltip)
        has_draft = bool(self.prompt.toPlainText().strip())
        can_send = not applying and not self._scope.error and has_draft
        self.send_button.setEnabled(busy or can_send)
        self.settings_button.setEnabled(not busy and not applying)
        self.new_button.setEnabled(not busy and not applying)
        self.starters.setVisible(not self._scope.error and not has_draft and not busy and not applying)

    def _stop(self) -> None:
        self._agent.abort()
        self._turn = None
        self._pending_sources.clear()
        self._flush.stop()
        self._pending_text = ""

    def _clear_conversation(self) -> None:
        self._stop()
        self._agent.clear_history()
        self._applying = None
        self._last_edit = None
        self._edit_locations.clear()
        self._source_urls.clear()
        self.transcript.clear()
        self._set_status("")

    def _configure(self) -> None:
        connection = get_session_model_connection()
        dialog = ScoreAgentSettingsDialog(self, connection=connection)
        try:
            if dialog.exec_floating() == QDialog.DialogCode.Accepted:
                updated = dialog.connection
                if updated != connection:
                    set_session_model_connection(updated)
                    self._agent.clear_history()
                    self._last_edit = None
                self._refresh_model_label()
        finally:
            dialog.deleteLater()

    def _capture_or_report(self) -> ScoreAgentCapture | None:
        try:
            return self._capture()
        except ScoreAgentScopeError as error:
            self._set_status(str(error))
        except (ValueError, TypeError) as error:
            source = _ERROR_LABELS.get(str(error), ERROR_LABELS.get(str(error), "工程或选区已变化，请重新选择。"))
            self._set_status(source)
        return None

    def _send_or_stop(self) -> None:
        if self._agent.busy:
            self._flush_text()
            self.transcript.finish_reply()
            self._stop()
            self._set_status("本轮 Agent 已停止。")
        else:
            self._submit()

    def _submit(self) -> None:
        instruction = self.prompt.toPlainText().strip()
        if self._agent.busy or self._applying is not None or self._scope.error or not instruction:
            return
        if len(instruction) > MAX_INSTRUCTION:
            if self._compact:
                self.expand_requested.emit()
            self._set_status(_ERROR_LABELS["invalid"])
            return
        if (connection := get_session_model_connection()) is None:
            self._configure()
            return
        turn = self._capture_or_report()
        if self._compact:
            self.expand_requested.emit()
        if turn is None:
            return
        self._turn = turn
        self._pending_sources.clear()
        self._set_status("Agent 正在思考…")
        self._displayed = 0
        self._streaming = False
        if self.transcript.document().characterCount() > 40_000:
            self.transcript.clear()
            self._edit_locations.clear()
            self._source_urls.clear()
        self.transcript.start_turn(turn.scope.label(), instruction)
        self.prompt.clear()
        language = localizer()
        scope_key = turn.history_key
        latest_edit = self._last_edit[1] if self._last_edit is not None and self._last_edit[0] == scope_key else None
        self._agent.start(
            instruction, connection, turn.tools, language.language if language else "zh-CN",
            scope_key=scope_key, latest_edit=latest_edit,
            audio_is_current=lambda: self._is_current(turn) and turn.scope.same_target(self._scope),
        )

    def _set_status(self, source: str) -> None:
        self.status.setText(tr(source) if source else "")
        self.status.setVisible(bool(source))
        self._chat_status = source
        self._refresh_send()

    def _busy_changed(self, _active: bool) -> None:
        self._refresh_controls()

    def _tools_started(self) -> None:
        if self._displayed:
            self._flush_text()
            self.transcript.append_reply("\n\n")
        self._streaming = False
        self._set_status("正在检查曲谱…")

    def _delta(self, text: str) -> None:
        if text and not self._streaming and self._agent.busy:
            self._streaming = True
            self._set_status("正在生成回复…")
        text = text[:max(0, MAX_REPLY_LENGTH - self._displayed)]
        if not text:
            return
        self._pending_text += text
        self._displayed += len(text)
        if not self._flush.isActive():
            self._flush.start()

    def _flush_text(self) -> None:
        if self._pending_text:
            self.transcript.append_reply(self._pending_text)
            self._pending_text = ""

    def _record_web_sources(self, sources: object) -> None:
        if self._turn is None or not isinstance(sources, list):
            return
        self._pending_sources.clear()
        for number, item in enumerate(sources[:5], 1):
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                continue
            url = QUrl(item["url"], QUrl.ParsingMode.StrictMode)
            if not (url.isValid() and url.scheme() in ("http", "https") and url.host() and not url.userInfo()):
                continue
            title = " ".join(str(item.get("title") or "").split())[:140] or url.host()
            self._pending_sources.append((number, title, url))

    def _append_turn_sources(self) -> None:
        rows = []
        for number, title, url in self._pending_sources:
            self._source_id += 1
            self._source_urls[self._source_id] = url
            rows.append((f"[{number}] {title}", url.host(), f"score-source:/{self._source_id}"))
        self._pending_sources.clear()
        block_limit = self.transcript.document().maximumBlockCount()
        if block_limit > 0:
            while len(self._source_urls) > block_limit:
                self._source_urls.pop(next(iter(self._source_urls)))
        self.transcript.append_web_sources(rows)

    def _completed(self, text: str, proposal: AgentProposal | None) -> None:
        turn, self._turn = self._turn, None
        if turn is None:
            return
        if not self._displayed:
            self._delta(text)
        self._flush_text()
        self.transcript.finish_reply()
        self._append_turn_sources()
        self._set_status("")
        if proposal is not None:
            error = self._proposal_error(turn)
            if error:
                self._set_status(error)
                return
            self._applying = turn, proposal
            self._set_status("正在更新曲谱…")
            self.proposal_ready.emit(turn, proposal)

    def _proposal_error(self, capture: ScoreAgentCapture) -> str:
        if not self._is_current(capture):
            return _STALE
        if not capture.scope.same_target(self._scope):
            return _STALE_SELECTION
        return ""

    def proposal_finished(
        self, capture: ScoreAgentCapture, proposal: AgentProposal, applied: bool,
        error: str = "", changed_track_ids: tuple[int, ...] = (),
        *, committed_stamp: tuple[str, int] | None = None,
    ) -> None:
        pending = self._applying
        if pending is None or pending[0] is not capture or pending[1] is not proposal:
            return
        self._applying = None
        if not applied:
            self._set_status(error or "这次未产生改动。")
            return
        self._set_status("")
        brief = proposal.brief
        first = brief.start_bar + 1
        if committed_stamp is not None and committed_stamp[0] == capture.stamp[0] and committed_stamp != capture.stamp:
            receipt = {"action": brief.action.value, "changed_tracks": len(changed_track_ids)}
            if brief.action is CreationAction.ADAPT:
                receipt.update(whole_track=True, instrument_id=brief.melody_instrument)
            else:
                receipt.update(first_bar=first, bars=brief.bars, character=brief.character.value)
            if brief.action is CreationAction.EXPRESS:
                receipt.update(rewrite_velocity=brief.rewrite_velocity, shape_durations=brief.shape_durations)
                if brief.velocity_scale_percent is not None:
                    receipt["velocity_scale_percent"] = brief.velocity_scale_percent
            self._last_edit = (committed_stamp, capture.history_target), receipt
        if brief.action is CreationAction.ADAPT:
            scope = tr("整条轨道")
        elif brief.bars == 1:
            scope = trf("第 {number} 小节", number=first)
        else:
            scope = trf("第 {start}–{end} 小节", start=first, end=brief.start_bar + brief.bars)
        start_ms = brief.start_bar * 60_000 * capture.context.meter / capture.context.bpm
        track_id = next(iter(changed_track_ids), capture.scope.track_id)
        self._receipt_id += 1
        self._edit_locations[self._receipt_id] = (capture.stamp[0], start_ms, track_id)
        block_limit = self.transcript.document().maximumBlockCount()
        if block_limit > 0 and len(self._edit_locations) > block_limit:
            self._edit_locations.pop(next(iter(self._edit_locations)))
        detail = f"{scope} · {tr('已应用')}"
        if brief.velocity_scale_percent is not None:
            detail = f"{scope} · {trf('力度 × {percent}%', percent=brief.velocity_scale_percent)}"
        self.transcript.append_inline_object(self._cards.edit_receipt(
            tr(ACTION_LABELS[brief.action]), detail, tr("定位到改动"), self._receipt_id,
        ))

    def _edit_anchor_clicked(self, url: QUrl) -> None:
        path = url.path().removeprefix("/")
        if url.scheme() == "score-edit" and path.isascii() and path.isdecimal() and len(path) <= 14:
            location = self._edit_locations.get(int(path))
            if location is not None:
                self.edit_seek_requested.emit(*location)

    def _source_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() != "score-source" or url.authority() or url.hasQuery() or url.hasFragment():
            return
        path = url.path()
        source_id = path[1:]
        if path.startswith("/") and source_id.isascii() and source_id.isdecimal() and len(source_id) <= 14:
            source = self._source_urls.get(int(source_id))
            if source is not None:
                QDesktopServices.openUrl(source)

    def _failed(self, code: str) -> None:
        self._turn = None
        self._flush_text()
        self.transcript.finish_reply()
        self._append_turn_sources()
        self._set_status(_ERROR_LABELS.get(code, "Agent 连接失败，请检查模型服务。"))
