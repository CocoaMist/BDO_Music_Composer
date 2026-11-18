"""Compact popup groups for the multitrack timeline command bar."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QActionEvent, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QMenu, QWidget,
    QWidgetAction,
)

from bdo_music_composer.ui.dialogs.composer_prompt import ComposerPrompt
from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.ui_controls import PillButton
from bdo_music_composer.ui.theme.fluent_theme import FluentSymbol, POPUP_MENU_LABEL_INSET


class _ScoreVelocityMenu(QMenu):
    def focusNextPrevChild(self, forward: bool) -> bool:
        # This menu contains a single form, so Tab advances to its fields.
        return QWidget.focusNextPrevChild(self, forward)


def apply_arrangement_tool_toggle(
    timeline,
    marquee: PillButton,
    select: PillButton,
    razor: PillButton,
    tool: str,
    checked: bool,
) -> None:
    """Publish the one explicit tool selected by the exclusive group."""

    if checked:
        timeline.set_arrangement_tool(tool)


def bind_arrangement_tool_buttons(
    timeline, marquee: PillButton, select: PillButton, razor: PillButton
) -> None:
    """Bind explicit Marquee, Move/Resize and Razor tool states."""

    marquee.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "marquee", checked
    ))
    select.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "select", checked
    ))
    razor.toggled.connect(lambda checked: apply_arrangement_tool_toggle(
        timeline, marquee, select, razor, "razor", checked
    ))


def build_arrangement_tool_buttons(
    parent: QWidget,
) -> tuple[QFrame, PillButton, PillButton, PillButton, PillButton]:
    """Build explicit Marquee/Move-resize/Razor controls for the timeline."""

    marquee = PillButton("", "ghost", FluentSymbol.MARQUEE)
    marquee.setObjectName("TimelineToolButton")
    marquee.setCheckable(True)
    marquee.setFixedSize(34, hig.BUTTON_HEIGHT)
    marquee.setToolTip(tr(
        "框选工具：拖动框选多个片段；所选片段只在片段编辑状态下移动"
    ))
    marquee.setAccessibleName(tr("框选工具"))
    select = PillButton("", "ghost", FluentSymbol.SELECT)
    select.setObjectName("TimelineToolButton")
    select.setCheckable(True)
    select.setChecked(True)
    select.setFixedSize(34, hig.BUTTON_HEIGHT)
    select.setToolTip(tr(
        "移动/调整音块：拖动主体移动，拖动右边界改变编辑区域"
    ))
    select.setAccessibleName(tr("移动/调整音块"))
    razor = PillButton("", "ghost", FluentSymbol.RAZOR)
    razor.setObjectName("TimelineToolButton")
    razor.setCheckable(True)
    razor.setFixedSize(34, hig.BUTTON_HEIGHT)
    razor.setToolTip(tr("剃刀工具：单击片段进行切分"))
    razor.setAccessibleName(tr("剃刀工具"))
    snap = PillButton(tr("吸附"), "ghost", FluentSymbol.MAGNET)
    snap.setObjectName("TimelineSnapToggle")
    snap.setCheckable(True)
    snap.setChecked(True)
    snap.setFixedHeight(hig.BUTTON_HEIGHT)
    snap.setMinimumWidth(66)
    snap.toggled.connect(
        lambda checked: _sync_snap_toggle_presentation(snap, checked)
    )
    _sync_snap_toggle_presentation(snap, snap.isChecked())
    tool_panel = QFrame(parent)
    tool_panel.setObjectName("CommandGroup")
    group = QButtonGroup(tool_panel)
    # One tool is always active; Select is the default editing state.
    group.setExclusive(True)
    group.addButton(marquee, 0)
    group.addButton(select, 1)
    group.addButton(razor, 2)
    tool_layout = QHBoxLayout(tool_panel)
    tool_layout.setContentsMargins(*(hig.GROUP_CONTENT_MARGIN,) * 4)
    tool_layout.setSpacing(hig.CONTROL_GAP)
    tool_layout.addWidget(marquee)
    tool_layout.addWidget(select)
    tool_layout.addWidget(razor)
    tool_layout.addWidget(snap)
    return tool_panel, marquee, select, razor, snap


def _sync_snap_toggle_presentation(
    button: PillButton,
    checked: bool,
) -> None:
    """Expose snap as a persistent, visually explicit two-state control."""

    active = bool(checked)
    button.setProperty("snapActive", active)
    if active:
        button.setToolTip(tr(
            "自动吸附已激活：移动或裁切片段时自动对齐；再次点击关闭（Alt 临时关闭）"
        ))
        button.setAccessibleName(tr("自动吸附已激活"))
    else:
        button.setToolTip(tr(
            "自动吸附未激活：移动和裁切片段时不会自动对齐；点击开启"
        ))
        button.setAccessibleName(tr("自动吸附未激活"))
    button.style().unpolish(button)
    button.style().polish(button)


def build_timeline_popup_buttons(
    parent: QWidget,
    global_gain_control: QWidget,
    zoom_label: QWidget,
    zoom_control: QWidget,
    pan_label: QWidget,
    pan_control: QWidget,
) -> tuple[QMenu, PillButton]:
    """Build the score-wide velocity popup and the timeline view menu."""

    mix_menu = _ScoreVelocityMenu(tr("全曲力度"), parent)
    mix_action = QWidgetAction(mix_menu)
    mix_action.setDefaultWidget(global_gain_control)
    mix_menu.addAction(mix_action)

    def refresh_controls(menu: QMenu, action: QWidgetAction) -> None:
        # QWidgetAction does not invalidate QMenu's cached width when its
        # hidden controls change size after switching languages.
        control_layout = action.defaultWidget().layout()
        control_layout.invalidate()
        control_layout.activate()
        QCoreApplication.sendEvent(menu, QActionEvent(QEvent.ActionChanged, action))

    def focus_mix_mode() -> None:
        if mix_menu.isVisible():
            parent.toolbar_global_gain_mode.setFocus(Qt.PopupFocusReason)

    def prepare_mix_menu() -> None:
        refresh_controls(mix_menu, mix_action)
        QTimer.singleShot(0, mix_menu, focus_mix_mode)

    mix_menu.aboutToShow.connect(prepare_mix_menu)

    view_button = PillButton(tr("视图"), "ghost")
    view_button.setFixedHeight(hig.BUTTON_HEIGHT)
    view_button.setToolTip(tr("时间轴视图"))
    view_menu = QMenu(view_button)
    view_menu.addAction(tr("适配宽度 W"), parent._fit_timeline)
    view_menu.addSeparator()
    view_panel = QFrame(view_menu)
    view_panel.setObjectName("TimelineViewPopup")
    layout = QGridLayout(view_panel)
    layout.setContentsMargins(
        POPUP_MENU_LABEL_INSET, hig.ITEM_GAP, POPUP_MENU_LABEL_INSET, hig.ITEM_GAP,
    )
    layout.setSpacing(hig.ITEM_GAP)
    layout.setColumnStretch(2, 1)
    zoom_control.setFixedWidth(pan_control.minimumWidth())
    layout.addWidget(zoom_label, 0, 0)
    layout.addWidget(zoom_control, 0, 1)
    layout.addWidget(pan_label, 1, 0)
    layout.addWidget(pan_control, 1, 1)
    view_action = QWidgetAction(view_menu)
    view_action.setDefaultWidget(view_panel)
    view_menu.addAction(view_action)
    view_menu.addSeparator()
    view_menu.addAction(tr("适配轨道 H"), lambda: parent.timeline.fit_track_rows())
    view_menu.addAction(tr("恢复标准布局"), lambda: parent.timeline.reset_layout_metrics())
    view_menu.addSeparator()
    fold_groups = view_menu.addAction(tr("折叠所有组"), lambda: parent.timeline.set_all_groups_collapsed(True))
    unfold_groups = view_menu.addAction(tr("展开所有组"), lambda: parent.timeline.set_all_groups_collapsed(False))

    def sync_view_actions() -> None:
        fold_groups.setVisible(parent.timeline.can_set_all_groups_collapsed(True))
        unfold_groups.setVisible(parent.timeline.can_set_all_groups_collapsed(False))
        refresh_controls(view_menu, view_action)

    view_menu.aboutToShow.connect(sync_view_actions)
    view_menu.addSeparator()
    shortcut_action = view_menu.addAction(tr("时间轴快捷键…"))
    shortcut_action.setShortcut(QKeySequence("F1"))
    shortcut_action.triggered.connect(
        lambda: parent.timeline.show_shortcut_help()
    )
    view_button.setMenu(view_menu)
    return mix_menu, view_button


def edit_reference_audio_offset(parent: QWidget) -> None:
    controller = parent.reference_audio
    path = controller.audio_path
    if not path:
        return
    editor = parent.active_transcription_editor
    if editor is not None and editor.has_transcription_staging():
        parent.show_toast(tr("请先应用、撤销或清除本次暂存，再修改音频对齐。"), kind="warning")
        return
    offset = controller.project_offset_ms
    input_field = QDoubleSpinBox(parent)
    input_field.setAccessibleName(tr("参考音频偏移"))
    input_field.setSuffix(" ms")
    input_field.setDecimals(3)
    limit = max(86_400_000.0, abs(offset))
    input_field.setRange(-limit, limit)
    input_field.setSingleStep(1.0)
    input_field.setValue(offset)
    prompt = ComposerPrompt(
        parent,
        tr("参考音频偏移"),
        tr("正值延后播放，波形右移。负值提前播放，波形左移。"),
        (("cancel", tr("取消")), ("apply", tr("应用"))),
        default="apply",
        field=input_field,
    )
    input_field.selectAll()
    prompt.exec()
    if prompt.choice == "apply" and controller.audio_path == path:
        controller.set_project_offset_ms(input_field.value())
    prompt.deleteLater()
