"""Dock the existing note editor without creating a second editing model."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, set_fluent_symbol


# The expanded row includes localized labels and the Apply action for a dirty
# draft. Keep their space available when the right-hand inspector is open.
_COMPACT_BAR_WIDTH = 1024


def _add_velocity_tools_menu(editor) -> QMenu:
    menu = editor.editor_view_menu.addMenu(tr("音符力度"))
    menu.setObjectName("EditorVelocityToolsMenu")
    modes = QActionGroup(menu)
    for button in (editor.velocity_point_button, editor.velocity_brush_button):
        action = menu.addAction(button.text())
        modes.addAction(action)
        action.setCheckable(True)
        action.triggered.connect(button.click)

    option_groups = []
    for combo in (editor.velocity_radius_combo, editor.velocity_scope_combo):
        menu.addSeparator()
        group = QActionGroup(menu)
        for index in range(combo.count()):
            action = menu.addAction(combo.itemText(index))
            group.addAction(action)
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked, combo=combo, index=index: combo.setCurrentIndex(index)
            )
        option_groups.append((combo, group))

    def sync_checks() -> None:
        modes.actions()[0 if editor.velocity_point_button.isChecked() else 1].setChecked(True)
        for combo, group in option_groups:
            group.actions()[combo.currentIndex()].setChecked(True)

    sync_checks()
    menu.aboutToShow.connect(sync_checks)
    return menu


class EditorDockAdapter(QObject):
    def __init__(self, editor, workbench) -> None:
        super().__init__(editor)
        self.editor = editor
        self.workbench = workbench
        self.placements: list[tuple] = []
        self.hidden: list[QWidget] = []
        self.original_flags = editor.standalone_window_flags
        self.original_size = editor.size()
        self.original_velocity_maximum = editor.velocity_panel.maximumHeight()
        self.original_velocity_height = editor._preferred_velocity_panel_height
        self.original_velocity_minimum = editor.velocity_lane.minimumHeight()
        self.original_canvas_minimum_height = editor.canvas.minimumHeight()
        self.original_summary_wrap = editor.selection_summary.wordWrap()
        self.original_root_margins = editor.layout().contentsMargins()
        self.original_root_constraint = editor.layout().sizeConstraint()
        self.note_field_metrics = []
        self.note_label_metrics = []
        self.original_rail_width = editor.editor_tool_rail.width()
        self.original_rail_margins = editor.editor_tool_rail.layout().contentsMargins()
        self.original_rail_spacing = editor.editor_tool_rail.layout().spacing()
        self.original_tool_sizes = [(button, button.size()) for button in editor.editor_tool_rail.findChildren(QPushButton)]
        self.note_page = QWidget(workbench.inspector.notes)
        note_layout = QVBoxLayout(self.note_page)
        note_layout.setContentsMargins(*(hig.PANEL_PADDING,) * 4)
        note_layout.setSpacing(hig.GROUP_GAP)
        self._move(editor.selection_summary, note_layout)
        editor.selection_summary.setWordWrap(True)
        for group in editor.note_field_groups:
            self._move(group, note_layout)
            group.layout().setDirection(QHBoxLayout.LeftToRight)
            field = group.findChild(QLineEdit)
            self.note_field_metrics.append((field, field.minimumSize(), field.maximumSize(), field.sizePolicy()))
            field.setMinimumWidth(90)
            field.setMaximumWidth(16777215)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for label in group.findChildren(QLabel):
                self.note_label_metrics.append((label, label.minimumSize(), label.maximumSize(), label.wordWrap()))
                label.setFixedWidth(74)
                label.setWordWrap(True)
                label.show()
        self._move(editor.articulation_context_label, note_layout)
        articulation_row = QHBoxLayout()
        articulation_row.setSpacing(hig.CONTROL_GAP)
        note_layout.addLayout(articulation_row)
        self._move(editor.articulation_combo, articulation_row)
        editor.articulation_combo.setFixedHeight(hig.EDITOR_COMMAND_HEIGHT)
        self._move(editor.articulation_preview_button, articulation_row, width=30)
        editor.articulation_preview_button.setFixedHeight(hig.EDITOR_COMMAND_HEIGHT)
        if editor.clip_bounds_frame is not None:
            note_layout.addSpacing(hig.ITEM_GAP)
            self._move(editor.clip_bounds_frame.findChild(QLabel, "EditorClipBoundsTitle"), note_layout)
            self._move(editor.clip_bounds_music_label, note_layout)
            self._move(editor.clip_end_spin, note_layout)
        note_layout.addStretch(1)

        self.bar = QFrame(editor)
        self.bar.setObjectName("WorkbenchEditorBar")
        self.bar.setProperty("noteCommandSurface", True)
        self.bar.setFixedHeight(hig.CAPTION_HEIGHT)
        self.bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._compact_bar: bool | None = None
        self._compact_rail: bool | None = None
        self._velocity_skip_text = editor.velocity_toggle.property("i18nSkipText")
        self._velocity_accessible_name = editor.velocity_toggle.accessibleName()
        self._quantize_label_hidden = editor.quantize_quick_label.isHidden()
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(hig.GROUP_GAP, 3, hig.GROUP_GAP, 3)
        bar.setSpacing(hig.ITEM_GAP)
        title = QHBoxLayout()
        title.setSpacing(hig.CONTROL_GAP)
        bar.addLayout(title)
        self._move(editor.editor_track_color, title)
        editor.editor_track_color.setFixedSize(3, 18)
        self._move(editor.editor_track_title, title)
        editor.editor_track_title.setMaximumWidth(180)
        editor.editor_track_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        transport_group = QFrame()
        transport_group.setObjectName("WorkbenchNoteTransport")
        transport = QHBoxLayout(transport_group)
        transport.setContentsMargins(*(hig.COMPACT_GROUP_CONTENT_MARGIN,) * 4)
        transport.setSpacing(hig.CONTROL_GAP)
        bar.addWidget(transport_group)
        for button in (editor.draft_play_button, editor.draft_stop_button, editor.loop_box):
            self._move(button, transport, width=hig.BUTTON_HEIGHT)
            button.setFixedHeight(hig.BUTTON_HEIGHT)
        self._move(editor.playback_time_label, transport)
        editor.playback_time_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid_group = QFrame()
        grid_group.setObjectName("WorkbenchNoteGrid")
        grid = QHBoxLayout(grid_group)
        grid.setContentsMargins(*(hig.COMPACT_GROUP_CONTENT_MARGIN,) * 4)
        grid.setSpacing(hig.CONTROL_GAP)
        bar.addWidget(grid_group)
        for widget in (editor.quantize_quick, editor.quantize_now_button, editor.editor_edit_button):
            self._move(widget, grid)
            widget.setFixedHeight(hig.EDITOR_COMMAND_HEIGHT)
            widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        editor.quantize_quick_label.show()
        bar.addStretch(1)
        view_group = QFrame()
        view_group.setObjectName("WorkbenchNoteView")
        view = QHBoxLayout(view_group)
        view.setContentsMargins(*(hig.COMPACT_GROUP_CONTENT_MARGIN,) * 4)
        view.setSpacing(hig.CONTROL_GAP)
        bar.addWidget(view_group)
        for button in (editor.velocity_toggle, editor.editor_view_button):
            self._move(button, view)
            button.setFixedHeight(hig.EDITOR_COMMAND_HEIGHT)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        editor.velocity_toggle.setAccessibleName(tr("力度"))
        action_group = QFrame()
        action_group.setObjectName("WorkbenchNoteActions")
        actions = QHBoxLayout(action_group)
        actions.setContentsMargins(*(hig.COMPACT_GROUP_CONTENT_MARGIN,) * 4)
        actions.setSpacing(hig.CONTROL_GAP)
        bar.addWidget(action_group)
        for button in editor.editor_toolbar_action_buttons.values():
            self._move(button, actions, width=hig.BUTTON_HEIGHT)
            button.setFixedHeight(hig.BUTTON_HEIGHT)
        popout = QPushButton()
        popout.setProperty("kind", "ghost")
        set_fluent_symbol(popout, FluentSymbol.POPOUT)
        popout.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        popout.setAccessibleName(tr("独立窗口"))
        popout.setToolTip(tr("独立窗口"))
        popout.setObjectName("WorkbenchQuietButton")
        popout.clicked.connect(lambda: workbench.pop_out(editor))
        actions.addWidget(popout)
        self.apply_button = QPushButton(tr("应用"))
        self.apply_button.setProperty("kind", "convert")
        self.apply_button.clicked.connect(editor.apply_notes)
        editor.draft_state_changed.connect(self._sync_apply_state)
        self._sync_apply_state()
        actions.addWidget(self.apply_button)
        close = QPushButton()
        close.setProperty("kind", "ghost")
        set_fluent_symbol(close, FluentSymbol.CLOSE)
        close.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close.setAccessibleName(tr("关闭"))
        close.setToolTip(tr("关闭"))
        close.clicked.connect(editor.reject)
        actions.addWidget(close)
        root = editor.layout()
        for index in range(root.count()):
            widget = root.itemAt(index).widget()
            if widget and widget.objectName() not in {"EditorBody", "EditorFooterInset"}:
                if not widget.isHidden():
                    self.hidden.append(widget)
                widget.hide()
        root.insertWidget(0, self.bar)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        editor.setProperty("workbenchEmbedded", True)
        editor.canvas.sync_harmony_lane()
        self.velocity_header = editor.velocity_panel.findChild(QFrame, "VelocityHeader")
        self.velocity_header_was_hidden = self.velocity_header.isHidden()
        self.velocity_header.hide()
        self.velocity_separator = editor.editor_view_menu.addSeparator()
        self.velocity_menu = _add_velocity_tools_menu(editor)
        # Fit against the space assigned by the dock, including when the
        # standalone canvas minimum would extend past the velocity splitter.
        editor.canvas.setMinimumHeight(0)
        editor.velocity_lane.setMinimumHeight(52)
        editor.setMinimumSize(0, 240)
        editor.shortcut_help_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        editor.editor_tool_rail.setFixedWidth(46)
        editor.editor_splitter.setChildrenCollapsible(True)
        editor._preferred_velocity_panel_height = 68
        editor.velocity_toggle.setChecked(workbench.note_velocity_visible)
        editor.velocity_toggle.toggled.connect(self._velocity_toggled)
        editor.transcription_mode_toggle.toggled.connect(self._transcription_toggled)
        editor.canvas.setFocusPolicy(Qt.StrongFocus)
        editor.refresh_fields()
        self.bar.installEventFilter(self)
        editor.editor_tool_rail.installEventFilter(self)
        self._sync_rail_density()
        QTimer.singleShot(0, editor, self._fit_initial_view)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if watched is self.bar:
                self._sync_bar_density()
            elif watched is self.editor.editor_tool_rail:
                self._sync_rail_density()
        return super().eventFilter(watched, event)

    def _sync_rail_density(self) -> None:
        rail = self.editor.editor_tool_rail
        compact = rail.height() < 196
        if compact == self._compact_rail:
            return
        self._compact_rail = compact
        inset = hig.CONTROL_GAP if compact else hig.ITEM_GAP
        rail.layout().setContentsMargins(6, inset, 6, inset)
        rail.layout().setSpacing(2 if compact else hig.CONTROL_GAP)
        for button, _size in self.original_tool_sizes:
            button.setFixedSize(34, 28 if compact else hig.BUTTON_HEIGHT)

    def _sync_bar_density(self) -> None:
        compact = self.bar.width() < _COMPACT_BAR_WIDTH
        if compact == self._compact_bar:
            return
        self._compact_bar = compact
        inset = hig.ITEM_GAP if compact else hig.GROUP_GAP
        self.bar.layout().setContentsMargins(inset, 3, inset, 3)
        self.bar.layout().setSpacing(hig.CONTROL_GAP if compact else hig.ITEM_GAP)
        editor = self.editor
        editor.editor_track_title.setMaximumWidth(116 if compact else 180)
        editor.quantize_quick_label.setVisible(not compact)
        editor.playback_time_label.setVisible(not compact)
        velocity = editor.velocity_toggle
        velocity.setProperty("i18nSkipText", compact or self._velocity_skip_text)
        velocity.setText("" if compact else tr("力度"))
        velocity.setMinimumWidth(hig.BUTTON_HEIGHT if compact else 0)
        velocity.setMaximumWidth(hig.BUTTON_HEIGHT if compact else 16777215)

    def _fit_initial_view(self) -> None:
        if self.editor.property("workbenchEmbedded"):
            self.editor.fit_note_view(
                with_context=True, initial_anchor_ms=self.workbench.host.timeline.playhead_ms,
            )

    def _sync_apply_state(self) -> None:
        editor = self.editor
        notes_changed = (
            editor.canvas.notes != editor.last_applied
            and editor.edited_notes() != editor.last_applied
        )
        pending = notes_changed or editor.has_transcription_staging()
        self.apply_button.setEnabled(pending)
        self.apply_button.setVisible(pending)

    def _transcription_toggled(self, enabled: bool) -> None:
        if enabled and self.editor.property("workbenchEmbedded"):
            self.workbench.pop_out(self.editor)

    def _velocity_toggled(self, visible: bool) -> None:
        self.workbench.note_velocity_visible = visible
        self.workbench.host.ui_preference_binding.schedule()

    def _move(self, widget, layout, *, width=None) -> None:
        parent = widget.parentWidget()
        old_layout = parent.layout() if parent is not None else None
        index = old_layout.indexOf(widget) if old_layout is not None else -1
        self.placements.append((
            widget, parent, old_layout, index, widget.minimumSize(),
            widget.maximumSize(), widget.sizePolicy(), widget.isHidden(),
        ))
        layout.addWidget(widget)
        widget.setMinimumSize(0, 0)
        widget.setMaximumSize(16777215, 16777215)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if width is not None:
            widget.setFixedWidth(width)
        widget.show()

    def restore(self) -> None:
        editor = self.editor
        self.bar.removeEventFilter(self)
        editor.editor_tool_rail.removeEventFilter(self)
        editor.velocity_toggle.setProperty("i18nSkipText", self._velocity_skip_text)
        editor.velocity_toggle.setText(tr("力度"))
        editor.velocity_toggle.setAccessibleName(self._velocity_accessible_name)
        editor.quantize_quick_label.setVisible(not self._quantize_label_hidden)
        editor.draft_state_changed.disconnect(self._sync_apply_state)
        for widget, parent, layout, index, minimum, maximum, policy, hidden in reversed(self.placements):
            widget.setParent(parent)
            if layout is not None:
                layout.insertWidget(max(0, index), widget)
            widget.setMinimumSize(minimum)
            widget.setMaximumSize(maximum)
            widget.setSizePolicy(policy)
            widget.setVisible(not hidden)
        self.placements.clear()
        for group in editor.note_field_groups:
            group.layout().setDirection(QVBoxLayout.TopToBottom)
        for field, minimum, maximum, policy in self.note_field_metrics:
            field.setMinimumSize(minimum)
            field.setMaximumSize(maximum)
            field.setSizePolicy(policy)
        for label, minimum, maximum, wrap in self.note_label_metrics:
            label.setMinimumSize(minimum)
            label.setMaximumSize(maximum)
            label.setWordWrap(wrap)
        editor.selection_summary.setWordWrap(self.original_summary_wrap)
        for widget in self.hidden:
            widget.show()
        editor.layout().removeWidget(self.bar)
        editor.layout().setContentsMargins(self.original_root_margins)
        editor.layout().setSizeConstraint(self.original_root_constraint)
        self.bar.deleteLater()
        editor.setProperty("workbenchEmbedded", False)
        editor.canvas.sync_harmony_lane()
        editor.velocity_lane.setMinimumHeight(self.original_velocity_minimum)
        editor.editor_view_menu.removeAction(self.velocity_menu.menuAction())
        editor.editor_view_menu.removeAction(self.velocity_separator)
        self.velocity_menu.deleteLater()
        self.velocity_separator.deleteLater()
        self.velocity_header.setVisible(not self.velocity_header_was_hidden)
        editor.velocity_panel.setMaximumHeight(self.original_velocity_maximum)
        editor._preferred_velocity_panel_height = self.original_velocity_height
        editor.editor_tool_rail.setFixedWidth(self.original_rail_width)
        editor.editor_tool_rail.layout().setContentsMargins(self.original_rail_margins)
        editor.editor_tool_rail.layout().setSpacing(self.original_rail_spacing)
        for button, size in self.original_tool_sizes:
            button.setFixedSize(size)
        editor.transcription_mode_toggle.toggled.disconnect(self._transcription_toggled)
        editor.velocity_toggle.toggled.disconnect(self._velocity_toggled)
        editor.setMinimumSize(920, 680)
        editor.canvas.setMinimumHeight(self.original_canvas_minimum_height)
        editor.resize(self.original_size)
        editor._editor_controls_compact = None
        editor._apply_editor_responsive_density()
        editor.shortcut_help_shortcut.setContext(Qt.WindowShortcut)
        editor.refresh_fields()
        self.deleteLater()
