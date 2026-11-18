"""Controls in the timeline's reference audio lane."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSlider, QWidget, QWidgetAction

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.fluent_theme import (
    FluentSymbol,
    POPUP_MENU_LABEL_INSET,
    set_fluent_symbol,
)
from bdo_music_composer.ui.ui_controls import PillButton


class ReferenceAudioView(Protocol):
    audio_path: str
    display_name: str
    duration_ms: float
    project_end_ms: float
    volume_percent: int
    waveform: Sequence[tuple[float, float, float]]
    waveform_loading: bool
    waveform_starts: Sequence[float]
    timeline_changed: object

    def audio_to_project(self, position_ms: float) -> float: ...
    def project_to_audio(self, position_ms: float) -> float: ...
    def choose_audio(self, parent: QWidget) -> None: ...
    def set_audio_path(self, path: Path | None) -> None: ...
    def set_volume_percent(self, value: int) -> None: ...


def position_reference_audio_controls(
    load_button: PillButton,
    menu_button: PillButton,
    controller: ReferenceAudioView,
    *,
    header_width: int,
    lane_top: int,
    lane_height: int,
    missing: bool,
) -> None:
    has_audio = bool(controller.audio_path)
    label = tr("重新关联音频" if missing else "添加参考音频")
    if load_button.text() != label:
        load_button.setText(label)
        load_button.setAccessibleName(label)
        load_button.setToolTip(label)
    if load_button.property("referenceMissing") != missing:
        load_button.setProperty("referenceMissing", missing)
        set_fluent_symbol(load_button, FluentSymbol.LINK if missing else FluentSymbol.OPEN)
        style = load_button.style()
        style.unpolish(load_button)
        style.polish(load_button)
    inset = hig.GROUP_GAP
    load_width = min(header_width - 2 * inset, load_button.sizeHint().width())
    load_button.resize(load_width, load_button.height())
    load_button.move(inset, lane_top + (lane_height - load_button.height()) // 2)
    load_button.setVisible(not has_audio)

    label = tr("参考音频选项")
    menu_button.setAccessibleName(label)
    menu_button.setToolTip(f"{label}\n{controller.display_name}" if has_audio else label)
    menu_button.move(
        header_width - inset - menu_button.width(),
        lane_top + (lane_height - menu_button.height()) // 2,
    )
    menu_button.setVisible(has_audio)


def build_reference_audio_menu(
    parent: QWidget,
    controller: ReferenceAudioView | None,
    load_label: str,
    choose_audio: Callable[[], None],
    request_offset: Callable[[], None],
) -> QMenu:
    menu = QMenu(parent)
    if controller is None or not controller.audio_path:
        menu.addAction(load_label, choose_audio)
        return menu

    menu.addAction(tr("参考音频偏移…"), request_offset)
    volume = QWidget(menu)
    layout = QHBoxLayout(volume)
    layout.setContentsMargins(POPUP_MENU_LABEL_INSET, 4, POPUP_MENU_LABEL_INSET, 4)
    layout.setSpacing(8)
    label = QLabel(tr("参考音频音量"), volume)
    slider = QSlider(Qt.Horizontal, volume)
    slider.setProperty("editorDisplayControl", True)
    slider.setAccessibleName(label.text())
    slider.setRange(0, 100)
    slider.setSingleStep(5)
    slider.setValue(controller.volume_percent)
    slider.setMinimumWidth(95)
    volume.setFocusPolicy(Qt.StrongFocus)
    volume.setFocusProxy(slider)
    label.setBuddy(slider)
    value = QLabel(f"{slider.value()}%", volume)
    value.setMinimumWidth(value.fontMetrics().horizontalAdvance("100%") + 2)
    value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    slider.valueChanged.connect(controller.set_volume_percent)
    slider.valueChanged.connect(lambda percent: value.setText(f"{percent}%"))
    layout.addWidget(label)
    layout.addWidget(slider, 1)
    layout.addWidget(value)
    action = QWidgetAction(menu)
    action.setDefaultWidget(volume)
    menu.addAction(action)
    menu.addSeparator()
    menu.addAction(tr("替换参考音频…"), choose_audio)
    menu.addSeparator()
    menu.addAction(tr("移除参考音频"), lambda: controller.set_audio_path(None))
    return menu
