"""Composer workbench: arrangement, pinned reference, notes, and inspector."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSignalBlocker, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QMenu, QSizePolicy, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from bdo_music_composer.app.ui_preferences import DEFAULT_UI_PREFERENCES
from bdo_music_composer.ui.editor.workbench_editor_qt import EditorDockAdapter
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.page_transition_qt import SurfaceFade
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol
from bdo_music_composer.ui.ui_controls import PillButton
from bdo_music_composer.ui.workbench_inspector_qt import WorkbenchInspector


OPEN_EDITOR_MIN_HEIGHT = 240


class _AgentEditSignals(QObject):
    finished = Signal(object, object, object, str)


class _AgentEditTask(QRunnable):
    def __init__(self, capture, proposal) -> None:
        super().__init__()
        self.capture = capture
        self.proposal = proposal
        self.signals = _AgentEditSignals()

    def run(self) -> None:
        from bdo_music_composer.creation.workspace import build_creation_session

        session, error = None, ""
        try:
            session = build_creation_session(self.capture.context, self.proposal.brief, self.proposal.clip_id)
        except (ValueError, TypeError, ArithmeticError) as exc:
            error = str(exc)
        self.signals.finished.emit(self.capture, self.proposal, session, error)


class ComposerWorkbench(QWidget):
    def __init__(self, host, timeline_panel) -> None:
        super().__init__()
        self.host = host
        self.adapters: dict[object, EditorDockAdapter] = {}
        self.note_velocity_visible = True
        self._editor_percent = DEFAULT_UI_PREFERENCES["workspace"]["workbench_editor_percent"]
        self._inspector_preferred = DEFAULT_UI_PREFERENCES["workspace"]["workbench_inspector_visible"]
        self.agent_panel = None
        self._agent_window = None
        self.setObjectName("ComposerWorkbench")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.command_bar = self._build_command_bar()
        layout.addWidget(self.command_bar)
        body = self.body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setObjectName("WorkbenchVerticalSplitter")
        self.splitter.setChildrenCollapsible(False)
        timeline_panel.setMinimumSize(0, 160)
        self.splitter.addWidget(timeline_panel)
        self.editors = QStackedWidget()
        self.editors.setObjectName("WorkbenchEditorStack")
        self.editors.setMinimumHeight(OPEN_EDITOR_MIN_HEIGHT)
        self.placeholder = QWidget()
        self.editors.addWidget(self.placeholder)
        self.splitter.addWidget(self.editors)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.splitterMoved.connect(self._remember_editor_percent)
        body_layout.addWidget(self.splitter)
        self.inspector = WorkbenchInspector(host)
        self.inspector.dismiss_requested.connect(lambda: self.inspector_toggle.setChecked(False))
        self.agent_dock = QWidget()
        self.agent_dock.setObjectName("ScoreAgentDock")
        agent_layout = QVBoxLayout(self.agent_dock)
        agent_layout.setContentsMargins(0, 0, 0, 0)
        self.side_pane = QStackedWidget(body)
        self.side_pane.setObjectName("WorkbenchSidePane")
        self.side_pane.addWidget(self.inspector)
        self.side_pane.addWidget(self.agent_dock)
        self.side_pane.hide()
        self._side_motion = SurfaceFade(self.side_pane)
        layout.addWidget(body, 1)
        self.inspector_toggle.toggled.connect(self._show_inspector)
        self.agent_toggle.toggled.connect(self._show_agent_sidebar)
        self.editor_toggle.toggled.connect(self._sync_editor_visibility)
        self.command_bar.installEventFilter(self)
        body.installEventFilter(self)
        self._sync_editor_visibility()
        self._sync_side_pane()
        self.retranslate_dynamic_content()
        host.timeline.setProperty("composerWorkbench", True)
        host.timeline.setMinimumHeight(160)
        host.timeline.set_layout_metrics(header_width=220, lane_height=64, reference_lane_height=68)

    def _build_command_bar(self) -> QFrame:
        host = self.host
        bar = QFrame()
        bar.setObjectName("WorkbenchCommandBar")
        bar.setFixedHeight(48)
        bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(hig.GROUP_GAP, 2, hig.GROUP_GAP, 2)
        layout.setSpacing(hig.GROUP_GAP)

        self.new_track_button = PillButton(tr("新建轨道"), "secondary", FluentSymbol.ADD_TRACK)
        self.new_track_button.setObjectName("WorkbenchNewTrack")
        self.new_track_button.setAccessibleName(tr("新建轨道"))
        self.new_track_button.setToolTip(tr("新建轨道"))
        self.new_track_button.setFixedHeight(hig.BUTTON_HEIGHT)
        self.new_track_button.clicked.connect(self._choose_track_instrument)
        layout.addWidget(self.new_track_button)
        layout.addWidget(host.timeline_edit_tools)

        history = QFrame()
        history.setObjectName("WorkbenchHistoryControls")
        history_layout = QHBoxLayout(history)
        history_layout.setContentsMargins(*(hig.GROUP_CONTENT_MARGIN,) * 4)
        history_layout.setSpacing(hig.CONTROL_GAP)
        for label, icon, callback in (
            ("撤销", FluentSymbol.UNDO, host._undo_project),
            ("重做", FluentSymbol.REDO, host._redo_project),
        ):
            button = PillButton("", "ghost", icon)
            button.setAccessibleName(tr(label))
            button.setToolTip(tr(label))
            button.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
            button.clicked.connect(callback)
            history_layout.addWidget(button)
        layout.addWidget(history)

        host.timeline_view_button.setObjectName("WorkbenchCommandMenu")
        layout.addWidget(host.timeline_view_button)
        layout.addStretch(1)

        self.score_tools_button = PillButton(tr("曲谱工具"), "ghost")
        self.score_tools_button.setObjectName("WorkbenchCommandMenu")
        self.score_tools_button.setAccessibleName(tr("曲谱工具"))
        self.score_tools_button.setToolTip(tr("曲谱工具"))
        self.score_tools_button.setFixedHeight(hig.BUTTON_HEIGHT)
        score_menu = QMenu(self.score_tools_button)
        score_menu.addAction(tr("从想法开始"), host._open_creation_assistant)
        score_menu.addAction(tr("创作 Agent"), host._open_score_agent)
        score_menu.addAction(tr("MIDI 优化"), lambda: host._open_midi_optimizer(None))
        self.score_tools_button.setMenu(score_menu)
        layout.addWidget(self.score_tools_button)

        mix = QFrame()
        mix.setObjectName("WorkbenchGlobalControls")
        self.global_controls = mix
        mix_layout = QHBoxLayout(mix)
        mix_layout.setContentsMargins(*(hig.GROUP_CONTENT_MARGIN,) * 4)
        mix_layout.setSpacing(hig.CONTROL_GAP)
        self.global_gain_button = PillButton(tr("全曲力度"), "ghost", FluentSymbol.CURVE)
        self.global_gain_button.setObjectName("WorkbenchGlobalGain")
        self.global_gain_button.setMenu(host.timeline_mix_menu)
        self.global_effects_button = PillButton(tr("全局效果"), "ghost", FluentSymbol.SETTINGS)
        self.global_effects_button.setObjectName("WorkbenchGlobalEffects")
        self.global_effects_button.clicked.connect(host._open_master_effects)
        for button, name in (
            (self.global_gain_button, "全曲力度"), (self.global_effects_button, "全局效果"),
        ):
            button.setToolTip(tr(name))
            button.setAccessibleName(tr(name))
            button.setFixedHeight(hig.BUTTON_HEIGHT)
            mix_layout.addWidget(button)
        layout.addWidget(mix)

        panels = QFrame()
        panels.setObjectName("WorkbenchPanelControls")
        self.panel_controls = panels
        panel_layout = QHBoxLayout(panels)
        panel_layout.setContentsMargins(*(hig.GROUP_CONTENT_MARGIN,) * 4)
        panel_layout.setSpacing(hig.CONTROL_GAP)
        self.open_editor_button = PillButton(tr("钢琴卷帘"), "ghost", FluentSymbol.NOTES_PANEL)
        self.open_editor_button.setAccessibleName(tr("打开音符编辑器"))
        self.open_editor_button.setToolTip(tr("打开音符编辑器"))
        self.open_editor_button.setEnabled(False)
        self.open_editor_button.setFixedHeight(hig.BUTTON_HEIGHT)
        self.open_editor_button.clicked.connect(self._open_selected)
        panel_layout.addWidget(self.open_editor_button)
        self.editor_toggle = PillButton(tr("钢琴卷帘"), "ghost", FluentSymbol.NOTES_PANEL)
        self.inspector_toggle = PillButton(tr("属性"), "ghost", FluentSymbol.INSPECTOR)
        for button, description in (
            (self.editor_toggle, "显示音符编辑区"),
            (self.inspector_toggle, "显示属性面板"),
        ):
            button.setCheckable(True)
            button.setChecked(True)
            button.setFixedHeight(hig.BUTTON_HEIGHT)
            button.setAccessibleName(tr(description))
            button.setToolTip(tr(description))
            panel_layout.addWidget(button)
        self.agent_toggle = PillButton(tr("创作 Agent"), "ghost", FluentSymbol.COMPOSER)
        self.agent_toggle.setObjectName("WorkbenchScoreAgentToggle")
        self.agent_toggle.setCheckable(True)
        self.agent_toggle.setFixedHeight(hig.BUTTON_HEIGHT)
        self.agent_toggle.setAccessibleName(tr("创作 Agent"))
        self.agent_toggle.setToolTip(tr("创作 Agent"))
        panel_layout.addWidget(self.agent_toggle)
        layout.addWidget(panels)
        return bar

    def retranslate_dynamic_content(self) -> None:
        self._sync_panel_width()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            if watched is self.command_bar:
                self._sync_panel_width(event.size().width())
            elif watched is self.body:
                self._position_side_pane()
        return super().eventFilter(watched, event)

    @staticmethod
    def _command_group_overhead(group: QFrame, controls: int) -> int:
        frame = group.contentsMargins()
        layout = group.layout()
        margins = layout.contentsMargins()
        return (
            frame.left() + frame.right() + margins.left() + margins.right()
            + layout.spacing() * max(0, controls - 1)
        )

    def _sync_panel_width(self, available_width: int | None = None) -> None:
        buttons = (
            (self.open_editor_button, tr("钢琴卷帘")),
            (self.editor_toggle, tr("钢琴卷帘")),
            (self.inspector_toggle, tr("属性")),
            (self.agent_toggle, tr("创作 Agent")),
        )
        globals_ = (
            (self.global_gain_button, tr("全曲力度")),
            (self.global_effects_button, tr("全局效果")),
        )
        visible = [(button, label) for button, label in buttons if not button.isHidden()]
        overhead = self._command_group_overhead(self.panel_controls, len(visible))
        mix_overhead = self._command_group_overhead(self.global_controls, len(globals_))
        label_widths = {
            button: button.fontMetrics().horizontalAdvance(label) + button.iconSize().width() + 30
            for button, label in (*buttons, *globals_)
        }
        snap = self.host.timeline_snap_tool
        snap_label = tr("吸附")
        snap_label_width = max(66, snap.fontMetrics().horizontalAdvance(snap_label) + snap.iconSize().width() + 30)
        new_track = self.new_track_button
        new_track_label = tr("新建轨道")
        new_track_label_width = (
            new_track.fontMetrics().horizontalAdvance(new_track_label) + new_track.iconSize().width() + 22
        )
        command_layout = self.command_bar.layout()
        command_margins = command_layout.contentsMargins()
        tools = self.host.timeline_edit_tools
        responsive = (new_track, tools, self.panel_controls, self.global_controls)
        siblings = [
            item for i in range(command_layout.count())
            if (item := command_layout.itemAt(i)).widget() not in (None, *responsive)
        ]
        sibling_width = sum(item.minimumSize().width() for item in siblings)
        rail_width = sibling_width + command_margins.left() + command_margins.right()
        rail_width += (len(siblings) + len(responsive) - 1) * command_layout.spacing()
        rail_width += self._command_group_overhead(tools, 4)
        rail_width += sum(button.minimumWidth() for button in (
            self.host.timeline_marquee_tool, self.host.timeline_select_tool, self.host.timeline_razor_tool,
        ))
        if available_width is None:
            available_width = self.command_bar.width()
        available_width -= rail_width + overhead + mix_overhead
        full_panel_width = sum(label_widths[button] for button, _ in visible)
        full_mix_width = sum(label_widths[button] for button, _ in globals_)
        compact = available_width < new_track_label_width + snap_label_width + full_panel_width + full_mix_width
        icon_width = hig.BUTTON_HEIGHT + hig.COMPACT_GROUP_CONTENT_MARGIN
        panels_width = len(visible) * icon_width if compact else full_panel_width
        mix_width = len(globals_) * icon_width if compact else full_mix_width
        available_width -= panels_width + mix_width
        for button, label in (*buttons, *globals_):
            button.setText("" if compact else label)
            button.setFixedWidth(icon_width if compact else label_widths[button])
        compact_snap = available_width < new_track_label_width + snap_label_width
        snap.setText("" if compact_snap else snap_label)
        snap.setFixedWidth(icon_width if compact_snap else snap_label_width)
        compact_new_track = available_width < new_track_label_width + snap.width()
        new_track.setText("" if compact_new_track else new_track_label)
        new_track.setFixedWidth(icon_width if compact_new_track else new_track_label_width)
        self.panel_controls.setFixedWidth(overhead + panels_width)
        self.global_controls.setFixedWidth(mix_overhead + mix_width)

    def _choose_track_instrument(self) -> None:
        button = self.new_track_button
        self.host.timeline.show_create_track_menu(button.mapToGlobal(QPoint(0, button.height())))

    def restore_layout(self, values) -> None:
        self._editor_percent = values["workbench_editor_percent"]
        self.note_velocity_visible = values["workbench_velocity_visible"]
        self.editor_toggle.setChecked(values["workbench_editor_visible"])
        self._inspector_preferred = values["workbench_inspector_visible"]
        self._sync_side_pane()
        QTimer.singleShot(0, self, self._restore_splitter)

    def _restore_splitter(self) -> None:
        if not self.editor_toggle.isChecked() or self.editors.currentWidget() is self.placeholder:
            return
        height = max(0, self.splitter.height() - self.splitter.handleWidth())
        editor_height = round(height * self._editor_percent / 100)
        self.splitter.setSizes([height - editor_height, editor_height])

    def _remember_editor_percent(self) -> None:
        if not self.editor_toggle.isChecked() or self.editors.currentWidget() is self.placeholder:
            return
        sizes = self.splitter.sizes()
        if sizes[0] > 0 and sizes[1] > 0:
            self._editor_percent = round(sizes[1] * 100 / sum(sizes))

    def _sync_editor_visibility(self) -> None:
        has_editor = self.editors.currentWidget() is not self.placeholder
        visible = has_editor and self.editor_toggle.isChecked()
        opening = visible and self.editors.isHidden()
        self.editors.setVisible(visible)
        self.open_editor_button.setVisible(not has_editor)
        self.editor_toggle.setVisible(has_editor)
        self._sync_panel_width()
        if opening:
            self._restore_splitter()
        self._refresh_agent_scope()

    def layout_preferences(self) -> dict:
        return {
            "workbench_editor_percent": self._editor_percent,
            "workbench_editor_visible": self.editor_toggle.isChecked(),
            "workbench_inspector_visible": self._inspector_preferred,
            "workbench_velocity_visible": self.note_velocity_visible,
        }

    def select_track(self, track) -> None:
        self.inspector.refresh(track)
        self.open_editor_button.setEnabled(track is not None)
        current = self.editors.currentWidget()
        matching = [editor for editor in self.adapters if int(editor.track.track_id) == int(track.track_id)] if track else []
        if matching:
            active = self.host.active_transcription_editor
            editor = current if current in matching else active if active in matching else matching[-1]
            self._show_editor(editor)
        elif track is None and current in self.adapters:
            self._sync_editor_visibility()
        else:
            self.editors.setCurrentWidget(self.placeholder)
            self.inspector.notes.setCurrentWidget(self.inspector.note_placeholder)
            self._sync_editor_visibility()

    def refresh(self) -> None:
        track = self.host.selected_track
        if track not in self.host.tracks:
            track = None
        for editor in tuple(self.adapters):
            if not any(int(item.track_id) == int(editor.track.track_id) for item in self.host.tracks):
                editor.reject()
        self.select_track(track)

    def _open_selected(self) -> None:
        track = self.host.selected_track
        if track is not None:
            self.host._open_note_editor(track)

    def attach_editor(self, editor) -> None:
        if editor in self.adapters:
            return
        adapter = EditorDockAdapter(editor, self)
        self.adapters[editor] = adapter
        if editor.parentWidget() is not self.editors or editor.isWindow():
            editor.setParent(self.editors, Qt.Widget)
        self.editors.addWidget(editor)
        self.inspector.notes.addWidget(adapter.note_page)
        editor.canvas.selection_changed.connect(self._refresh_agent_scope)
        editor.draft_state_changed.connect(self._refresh_agent_scope)

    def activate_editor(self, editor) -> None:
        if editor not in self.adapters:
            return
        self.editor_toggle.setChecked(True)
        self._show_editor(editor)

    def _show_editor(self, editor) -> None:
        self.editors.setCurrentWidget(editor)
        self._sync_editor_visibility()
        self.inspector.notes.setCurrentWidget(self.adapters[editor].note_page)

    def editor_finished(self, editor) -> None:
        adapter = self.adapters.pop(editor, None)
        if adapter is None:
            return
        self.inspector.notes.removeWidget(adapter.note_page)
        self.editors.removeWidget(editor)
        editor.setParent(self.host, adapter.original_flags)
        editor.canvas.selection_changed.disconnect(self._refresh_agent_scope)
        editor.draft_state_changed.disconnect(self._refresh_agent_scope)
        adapter.restore()
        adapter.note_page.deleteLater()
        self.select_track(self.host.selected_track)

    def pop_out(self, editor) -> None:
        self.editor_finished(editor)
        editor.show()
        editor.raise_()
        editor.activateWindow()
        editor.canvas.setFocus(Qt.OtherFocusReason)

    def open_score_agent(self) -> None:
        self.agent_toggle.setChecked(True)
        if self._agent_window is not None and self._agent_window.isVisible():
            self._agent_window.raise_()
            self._agent_window.activateWindow()
        if self.agent_panel is not None:
            self.agent_panel.open()

    def _show_inspector(self, checked: bool) -> None:
        self._inspector_preferred = checked
        if checked and self.agent_toggle.isChecked() and self._agent_window is None:
            self.agent_toggle.setChecked(False)
        self._sync_side_pane()

    def _show_agent_sidebar(self, checked: bool) -> None:
        if checked:
            self._ensure_score_agent_panel()
            self._refresh_agent_scope()
        if self._agent_window is not None:
            self._agent_window.set_conversation_visible(checked)
        self._sync_side_pane()

    def _dismiss_score_agent(self) -> None:
        self.agent_toggle.setChecked(False)

    def _sync_side_pane(self) -> None:
        agent_visible = self._agent_window is None and self.agent_toggle.isChecked()
        with QSignalBlocker(self.inspector_toggle):
            self.inspector_toggle.setChecked(self._inspector_preferred and not agent_visible)
        shown = agent_visible or self._inspector_preferred
        page = self.agent_dock if agent_visible else self.inspector
        changed = shown and self.side_pane.currentWidget() is not page
        if shown:
            self.side_pane.setCurrentWidget(page)
            self._position_side_pane()
        self._side_motion.set_visible(shown, changed_page=changed)

    def _position_side_pane(self) -> None:
        margin = hig.PANEL_PADDING
        agent = self.side_pane.currentWidget() is self.agent_dock
        width = max(1, min(424 if agent else 384, self.body.width() - 2 * margin))
        height = max(1, min(660 if agent else 414, self.body.height() - 2 * margin))
        self.side_pane.setGeometry(
            self.body.width() - width - margin, self.body.height() - height - margin,
            width, height,
        )

    def _ensure_score_agent_panel(self) -> None:
        if self.agent_panel is not None:
            return
        from bdo_music_composer.ui.score_agent_panel_qt import ScoreAgentPanel

        self.agent_panel = ScoreAgentPanel(self._capture_agent_score, self._agent_capture_current, self.agent_dock)
        self.agent_dock.layout().addWidget(self.agent_panel)
        self.agent_panel.proposal_ready.connect(self._apply_agent_proposal)
        self.agent_panel.edit_seek_requested.connect(self._seek_agent_edit)
        self.agent_panel.floating_requested.connect(self.float_score_agent)
        self.agent_panel.dismiss_requested.connect(self._dismiss_score_agent)
        self.host.timeline.selection_scope_changed.connect(self._refresh_agent_scope)
        self.host.timeline.time_range_changed.connect(self._refresh_agent_scope)
        self.host.reference_audio.timeline_changed.connect(self._schedule_agent_audio_refresh)
        self._agent_scope_timer = QTimer(self)
        self._agent_scope_timer.setInterval(160)
        self._agent_scope_timer.setSingleShot(True)
        self._agent_scope_timer.timeout.connect(self._refresh_agent_scope)
        self.host.timeline.playhead_changed.connect(self._schedule_agent_scope_refresh)

    def _agent_scope(self):
        from bdo_music_composer.ui.score_agent_scope_qt import workspace_agent_scope

        editor = self.editors.currentWidget()
        if editor not in self.adapters or self.editors.isHidden():
            return workspace_agent_scope(self.host)
        return workspace_agent_scope(self.host, editor, editor_dirty=not self.adapters[editor].apply_button.isHidden())

    def _refresh_agent_scope(self) -> None:
        if self.agent_panel is not None:
            self.agent_panel.set_scope(self._agent_scope(), self._agent_stamp())

    def _schedule_agent_scope_refresh(self) -> None:
        if self.agent_panel.isVisible() and self.agent_panel.follows_playhead and not self._agent_scope_timer.isActive():
            self._agent_scope_timer.start()

    def _schedule_agent_audio_refresh(self) -> None:
        if self.agent_panel.isVisible() and not self._agent_scope_timer.isActive():
            self._agent_scope_timer.start()

    def _capture_agent_score(self):
        from bdo_music_composer.ui.score_agent_scope_qt import capture_workspace_score

        scope = self._agent_scope()
        self.agent_panel.set_scope(scope, self._agent_stamp())
        return capture_workspace_score(self.host, scope)

    def _agent_stamp(self) -> tuple[str, int]:
        return self.host.project_id, self.host.model_revision.value

    def _agent_capture_current(self, capture) -> bool:
        from bdo_music_composer.ui.score_agent_scope_qt import workspace_reference_audio_source

        if self.host.loading_project or capture.stamp != self._agent_stamp():
            return False
        if (capture.context.bpm, capture.context.meter, capture.context.denominator, capture.grid_origin_ms) != (
            self.host.bpm_override or self.host.bpm, self.host.time_sig, self.host.time_sig_denominator,
            float(self.host.timeline.beat_origin_ms),
        ):
            return False
        if capture.reference_audio_source != workspace_reference_audio_source(
            self.host, grid_origin_ms=capture.grid_origin_ms,
        ):
            return False
        if capture.scope.editor_notes is not None:
            return capture.scope.editor_notes == self._agent_scope().editor_notes
        return True

    def _agent_edit_scope_error(self, capture) -> str:
        if not self._agent_capture_current(capture):
            return tr("工程已修改，请重新分析后再应用建议。")
        if not capture.scope.same_target(self._agent_scope()):
            return tr("选区已变化，请在当前范围重新生成建议。")
        return ""

    def _apply_agent_proposal(self, capture, proposal) -> None:
        error = self._agent_edit_scope_error(capture)
        if error:
            self.agent_panel.proposal_finished(capture, proposal, False, error)
            return
        task = _AgentEditTask(capture, proposal)
        task.signals.finished.connect(self._agent_edit_prepared, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(task)

    @Slot(object, object, object, str)
    def _agent_edit_prepared(self, capture, proposal, session, reason: str) -> None:
        from bdo_music_composer.ui.dialogs.creation_assistant_dialog import ERROR_LABELS

        error = self._agent_edit_scope_error(capture)
        changed_track_ids = ()
        if not error:
            if session is None:
                error = trf("无法生成候选：{error}", error=tr(ERROR_LABELS.get(reason, reason)))
            else:
                keys = frozenset(part.key for part in session.candidate.parts)
                try:
                    changed_track_ids = self.host._apply_creation_session(session, keys)
                except (ValueError, TypeError, ArithmeticError) as exc:
                    reason = str(exc)
                    error = trf("无法应用建议：{error}", error=tr(ERROR_LABELS.get(reason, reason)))
        committed_stamp = self._agent_stamp() if changed_track_ids else None
        self.agent_panel.proposal_finished(
            capture, proposal, bool(changed_track_ids), error, changed_track_ids, committed_stamp=committed_stamp,
        )

    def _seek_agent_edit(self, project_id: str, position_ms: float, track_id: int | None) -> None:
        if self.host.loading_project or project_id != self.host.project_id or not math.isfinite(position_ms):
            return
        if track_id is not None:
            track = next((track for track in self.host.tracks if int(track.track_id) == track_id), None)
            if track is not None:
                self.host._select_track(track)
        self.host._seek_preview(position_ms)

    def float_score_agent(self) -> None:
        if self._agent_window is not None:
            self.agent_toggle.setChecked(True)
            self._agent_window.raise_()
            return
        from bdo_music_composer.ui.score_agent_floating_qt import ScoreAgentFloatingWindow

        self._ensure_score_agent_panel()
        window = ScoreAgentFloatingWindow(self.host, self.agent_panel, anchor=self.host.timeline)
        window.redock_requested.connect(self._redock_score_agent)
        window.dismiss_requested.connect(self._dismiss_score_agent)
        self._agent_window = window
        self.agent_toggle.setChecked(True)
        self._refresh_agent_scope()
        self._sync_side_pane()
        window.set_conversation_visible(True)

    def _redock_score_agent(self) -> None:
        window, self._agent_window = self._agent_window, None
        if window is None:
            return
        panel = window.take_panel()
        self.agent_dock.layout().addWidget(panel)
        panel.show()
        window.hide()
        window.deleteLater()
        self.agent_toggle.setChecked(True)
        self._sync_side_pane()
