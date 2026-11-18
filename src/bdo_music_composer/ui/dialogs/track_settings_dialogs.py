"""Focused dialogs for track pitch and per-track BDO effects.

The dialogs depend on a small structural track contract instead of importing
the main GUI module.  The main window remains responsible only for opening the
dialogs and applying accepted values.
"""

from __future__ import annotations

from typing import Protocol

from bdo_music_composer.ui.floating_panel_qt import FloatingPanelDialog

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bdo_midi.instruments import (
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
    instrument_supports_composer_effects,
    localized_bdo_instrument_name,
)
from bdo_common.bdo_track_effects import (
    GAME_PERCENT_MAX,
    MasterEffects,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.ui_controls import ElidedComboBox, ElidedLabel
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan
from bdo_music_composer.ui.dialogs.effect_controls_qt import (
    EffectControlCard,
    EffectModeCard,
)


class TrackDialogState(Protocol):
    """Minimal editor-track surface consumed by these dialogs."""

    track_id: int
    display_name: str
    bdo_instrument_id: int
    bdo_track_settings: tuple[int, ...]
    marnian_synth_mode: str


_MARNIAN_SYNTH_MODE_LABELS = {
    "basic": "单声道（Basic）",
    "stereo": "双声（Stereo）",
    "super": "增强（Super）",
    "superoct": "超级增强（Super Octave）",
}
MARNIAN_SYNTH_MODES = tuple(
    (_MARNIAN_SYNTH_MODE_LABELS[mode], mode)
    for mode in MARNIAN_SYNTH_MODE_OFFSETS
)


def _instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


def _track_title(text: str) -> QFrame:
    card = QFrame()
    card.setObjectName("TrackTitleCard")
    layout = QHBoxLayout(card)
    layout.setContentsMargins(10, 8, 10, 8)
    title = ElidedLabel(text, maximum_hint_width=380)
    title.setObjectName("TrackTitle")
    title.setTextFormat(Qt.PlainText)
    title.setProperty("i18nSkip", True)
    layout.addWidget(title)
    return card


class TrackPitchDialog(QDialog):
    """Explicit chromatic per-track transpose over the global transpose."""

    def __init__(
        self,
        parent: QWidget,
        track: TrackDialogState,
        plan: PitchTransformPlan,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("TrackPitchDialog")
        self.setProperty("uiSurface", "workflow")
        self.setWindowTitle(tr("轨道移调"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.track = track
        self.plan = plan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        layout.addWidget(_track_title(track.display_name))

        hint = QLabel(
            tr(
                "只改变当前轨道的试听、检查与导出音高，不改写工程中的原始音符。"
            )
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)
        self.semitone_offset = QSpinBox()
        self.semitone_offset.setObjectName("TrackSemitoneOffset")
        self.semitone_offset.setRange(-48, 48)
        self.semitone_offset.setSuffix(tr(" 半音"))
        current = plan.override_for(track.track_id)
        current_offset = current.semitones if current is not None else 0
        self.semitone_offset.setValue(current_offset)
        form.addRow(tr("轨道移调"), self.semitone_offset)

        preset_row = QHBoxLayout()
        preset_row.addStretch(1)
        reset_button = QPushButton(tr("重置"))
        reset_button.setObjectName("TrackPitchReset")
        reset_button.setToolTip(tr("恢复为不移调"))
        reset_button.clicked.connect(lambda: self.semitone_offset.setValue(0))
        preset_row.addWidget(reset_button)
        for value in (-12, 12):
            button = QPushButton(f"{value:+d}")
            button.setObjectName("TrackPitchPreset")
            button.setToolTip(tr("常用八度移调"))
            button.clicked.connect(lambda _checked=False, v=value: self.semitone_offset.setValue(v))
            preset_row.addWidget(button)
        form.addRow("", preset_row)

        self.effective_label = QLabel()
        self.effective_label.setObjectName("Muted")
        self.effective_label.setWordWrap(True)
        layout.addWidget(self.effective_label)
        self.semitone_offset.valueChanged.connect(
            self._refresh_effective_label
        )
        self._refresh_effective_label()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_effective_label(self) -> None:
        effective = (
            self.plan.global_semitones + self.selected_semitone_offset()
        )
        self.effective_label.setText(
            trf(
                "全局 {global_transpose:+d} + 轨道 {track_transpose:+d} = 最终 {effective:+d} 半音",
                global_transpose=self.plan.global_semitones,
                track_transpose=self.selected_semitone_offset(),
                effective=effective,
            )
        )

    def selected_semitone_offset(self) -> int:
        return int(self.semitone_offset.value())


class ClipVelocityBaseDialog(QDialog):
    """One-shot baseline mapping for one or more selected Clips."""

    def __init__(self, parent: QWidget, display_name: str, count: int) -> None:
        super().__init__(parent)
        self.setObjectName("ClipVelocityBaseDialog")
        self.setProperty("uiSurface", "workflow")
        self.setWindowTitle(tr("Clip 力度基数（分贝）"))
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        safe_name = str(display_name).strip()
        if safe_name.startswith(("track-", "clip-", "track:", "clip:")):
            safe_name = tr("所选片段")
        title = _track_title(
            safe_name
            if int(count) == 1
            else trf("已选择 {count} 个Clip", count=int(count))
        )
        layout.addWidget(title)

        hint = QLabel(
            tr(
                "修改所选Clip的可恢复力度基准，再重新应用各自的分贝比例；不会重置百分比或影响其他Clip。"
            )
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(hig.CONTROL_GAP)
        self.velocity_base = QSpinBox()
        self.velocity_base.setObjectName("ClipVelocityBase")
        self.velocity_base.setMinimumHeight(hig.BUTTON_HEIGHT)
        self.velocity_base.setRange(-127, 127)
        self.velocity_base.setValue(0)
        form.addRow(tr("力度基数"), self.velocity_base)

        self.equalize = QCheckBox(tr("均化到 0–127"))
        self.equalize.setObjectName("TrackVelocityEqualize")
        self.equalize.setMinimumHeight(hig.SEGMENT_HEIGHT)
        form.addRow("", self.equalize)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.retranslate_dynamic_content()

    def retranslate_dynamic_content(self) -> None:
        # Fit the wrapped help at the dialog's narrowest supported width.
        layout = self.layout()
        self.setMinimumHeight(max(0, layout.totalHeightForWidth(self.minimumWidth())))

    def selected_velocity_base(self) -> int:
        return int(self.velocity_base.value())

    def equalize_enabled(self) -> bool:
        return bool(self.equalize.isChecked())


class TrackFxDialog(QDialog):
    def __init__(self, parent: QWidget, track: TrackDialogState) -> None:
        super().__init__(parent)
        self.setObjectName("TrackFxDialog")
        self.setProperty("uiSurface", "workflow")
        self.setWindowTitle(tr("轨道 FX"))
        self.setModal(True)
        self.resize(650, 440)
        self.setMinimumSize(570, 430)
        self.track = track
        self.instrument_id = int(track.bdo_instrument_id)
        self._effect_dirty: set[int] = set()
        self._effect_fields: dict[int, QSpinBox] = {}
        self._effect_cards: dict[int, tuple[EffectControlCard, str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("EffectDialogHeader")
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 13)
        header_layout.setSpacing(2)
        heading = QLabel(tr("轨道 FX"))
        heading.setObjectName("EffectDialogTitle")
        heading.setProperty("uiRole", "dialogTitle")
        self.instrument_title = QLabel(_instrument_name(track.bdo_instrument_id))
        self.instrument_title.setObjectName("EffectDialogSubtitle")
        self.instrument_title.setProperty("uiRole", "dialogSubtitle")
        self.instrument_title.setProperty("i18nSkip", True)
        header_layout.addWidget(heading)
        header_layout.addWidget(self.instrument_title)
        layout.addWidget(header)

        body = QFrame()
        body.setObjectName("EffectDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 16, 18, 14)
        body_layout.setSpacing(12)

        effects_supported = instrument_supports_composer_effects(self.instrument_id)
        self._effects_supported = effects_supported
        if not effects_supported:
            capability_hint = QLabel(
                tr(
                    "当前初级乐器在游戏中不提供 Effector/AuxSend；现有曲谱字节会原样保留。"
                )
            )
            capability_hint.setObjectName("EffectScopeNotice")
            capability_hint.setWordWrap(True)
            body_layout.addWidget(capability_hint)

        rack = QFrame()
        rack.setObjectName("EffectRack")
        rack_layout = QHBoxLayout(rack)
        rack_layout.setContentsMargins(*(hig.EFFECT_RACK_CONTENT_MARGIN,) * 4)
        rack_layout.setSpacing(8)

        for label, index, object_name, help_text in (
            (
                "混响发送",
                TRACK_REVERB_SEND_INDEX,
                "TrackReverbSend",
                "混响发送：控制此轨道进入共享混响的比例；0 为干声。",
            ),
            (
                "延迟发送",
                TRACK_DELAY_SEND_INDEX,
                "TrackDelaySend",
                "延迟发送：控制此轨道进入回声总线的比例；主“延迟反馈”决定重复次数与衰减。",
            ),
            (
                "合唱发送",
                TRACK_CHORUS_SEND_INDEX,
                "TrackChorusSend",
                "合唱发送：控制此轨道进入合唱/Flanger 总线的比例；用于加宽并产生流动感。",
            ),
        ):
            field = QSpinBox()
            field.setObjectName(object_name)
            field.setRange(0, GAME_PERCENT_MAX)
            field.setEnabled(effects_supported)
            field.valueChanged.connect(
                lambda _value, effect_index=index: self._effect_dirty.add(
                    effect_index
                )
            )
            self._effect_fields[index] = field
            card = EffectControlCard(tr(label), field)
            self._effect_cards[index] = card, help_text
            rack_layout.addWidget(card)

        body_layout.addWidget(rack)

        is_marnian = self.instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        self.marnian_mode: QComboBox | None = None
        if is_marnian:
            self.resize(840, 440)
            self.setMinimumWidth(760)
            self.marnian_mode = ElidedComboBox()
            for label, value in MARNIAN_SYNTH_MODES:
                self.marnian_mode.addItem(tr(label), value)
            rack_layout.addWidget(
                EffectModeCard(
                    tr("玛勒尼斯音源"),
                    self.marnian_mode,
                    tr("Basic 默认；其他模式待验证"),
                )
            )
        preview_hint = QLabel(tr("游戏参数 · 本地 FX 试听为未校准近似"))
        preview_hint.setObjectName("EffectPreviewNote")
        preview_hint.setWordWrap(True)
        body_layout.addWidget(preview_hint)
        layout.addWidget(body, stretch=1)

        footer = QFrame()
        footer.setObjectName("EffectDialogFooter")
        footer.setProperty("uiRole", "dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 10, 18, 10)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.setProperty("uiRole", "dialogButtonRow")
        apply_button = buttons.button(QDialogButtonBox.Apply)
        apply_button.setText(tr("应用"))
        apply_button.setProperty("kind", "convert")
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        cancel_button.setText(tr("取消"))
        cancel_button.setAutoDefault(False)
        apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)
        apply_button.setDefault(True)
        self.refresh_track_settings()

    def refresh_track_settings(
        self, *, keep_send_edits: bool = False, keep_mode_edit: bool = False,
    ) -> None:
        """Read the current track while optionally keeping the inspector's draft."""

        try:
            self._original_track_settings = raw_track_settings(self.track.bdo_track_settings)
        except ValueError:
            self._original_track_settings = (0,) * 8
        if not keep_send_edits:
            self._effect_dirty.clear()
        for index, (card, help_text) in self._effect_cards.items():
            field = card.field
            raw_value = self._original_track_settings[index]
            shown_value = min(GAME_PERCENT_MAX, raw_value)
            if index not in self._effect_dirty and field.value() != shown_value:
                with QSignalBlocker(field), QSignalBlocker(card.dial):
                    field.setValue(shown_value)
                    card.dial.setValue(shown_value)
            tooltip = tr(help_text)
            if raw_value > GAME_PERCENT_MAX:
                tooltip += "\n" + trf(
                    "导入原值 {value}；修改后按 0–100 写入。",
                    value=raw_value,
                )
            if field.toolTip() != tooltip:
                field.setToolTip(tooltip)
                card.dial.setToolTip(tooltip)
        if self.marnian_mode is not None and not keep_mode_edit:
            mode_index = max(0, self.marnian_mode.findData(self.track.marnian_synth_mode))
            if self.marnian_mode.currentIndex() != mode_index:
                self.marnian_mode.setCurrentIndex(mode_index)

    def selected_marnian_synth_mode(self) -> str:
        if self.marnian_mode is None:
            return "basic"
        return str(self.marnian_mode.currentData() or "basic")

    def retranslate_dynamic_content(self) -> None:
        self.instrument_title.setText(_instrument_name(self.track.bdo_instrument_id))

    def selected_track_settings(self) -> tuple[int, ...]:
        """Return edited Aux sends while preserving untouched wire bytes."""

        settings = list(self._original_track_settings)
        if self._effects_supported:
            for index in self._effect_dirty:
                settings[index] = self._effect_fields[index].value()
        return tuple(settings)

    def track_effects_changed(self) -> bool:
        return self._effects_supported and bool(self._effect_dirty)

    def changed_send_indices(self) -> frozenset[int]:
        """Return only Aux fields explicitly edited in this dialog."""

        if not self._effects_supported:
            return frozenset()
        return frozenset(self._effect_dirty)


class MasterEffectsDialog(FloatingPanelDialog):
    """Edit score-wide effect parameters without touching track Aux sends."""

    def __init__(
        self,
        parent: QWidget,
        current: MasterEffects | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MasterEffectsDialog")
        self.setProperty("uiSurface", "workflow")
        self.setWindowTitle(tr("全局主效果"))
        self.setModal(True)
        self.resize(900, 520)
        self.setMinimumSize(840, 510)

        self._original = current or MasterEffects()
        self._dirty_fields: set[str] = set()
        self._fields: dict[str, QSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("EffectDialogHeader")
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 13)
        header_layout.setSpacing(2)
        title = QLabel(tr("全局主效果"))
        title.setObjectName("EffectDialogTitle")
        title.setProperty("uiRole", "dialogTitle")
        subtitle = QLabel(
            tr(
                "整首曲子共用这些参数；轨道使用多少效果仍由每条轨道的 FX 发送量决定。"
            )
        )
        subtitle.setObjectName("EffectDialogSubtitle")
        subtitle.setProperty("uiRole", "dialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QFrame()
        body.setObjectName("EffectDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 20, 22, 22)
        body_layout.setSpacing(14)

        rack_row = QHBoxLayout()
        rack_row.setContentsMargins(0, 0, 0, 0)
        rack_row.setSpacing(12)

        ambience, ambience_layout = self._section(
            "混响与延迟",
            "混响时间控制空间尾音；延迟反馈控制回声重复次数。",
        )
        ambience_rack = self._effect_rack()
        ambience_layout.insertLayout(1, ambience_rack)
        self.reverb = self._new_field(
            "MasterReverbTime",
            "混响时间",
            "reverb_time",
            self._original.reverb_time,
            "混响时间：控制混响尾音长度；本地试听按 0.2–8.0 秒近似。",
        )
        self.delay = self._new_field(
            "MasterDelayFeedback",
            "延迟反馈",
            "delay_feedback",
            self._original.delay_feedback,
            "延迟反馈：控制回声返回延迟线的比例；游戏说明约 2–20 次延迟声，本地试听固定约 250 ms 并按该范围近似。",
        )
        ambience_rack.addWidget(EffectControlCard(tr("混响时间"), self.reverb), 1, Qt.AlignTop)
        ambience_rack.addWidget(EffectControlCard(tr("延迟反馈"), self.delay), 1, Qt.AlignTop)
        rack_row.addWidget(ambience, stretch=2)

        chorus, chorus_layout = self._section(
            "合唱（游戏中为 Flanger）",
            "反馈决定旋动感，LFO 深度决定摆动幅度，LFO 频率决定摆动速度。",
        )
        chorus_rack = self._effect_rack()
        chorus_layout.insertLayout(1, chorus_rack)
        self.chorus_feedback = self._new_field(
            "MasterChorusFeedback",
            "合唱反馈",
            "chorus_feedback",
            self._original.chorus_feedback,
            "合唱反馈：控制调制延迟的反馈强度；越高，梳状与旋动感越明显。",
        )
        self.chorus_depth = self._new_field(
            "MasterChorusLfoDepth",
            "LFO 深度",
            "chorus_lfo_depth",
            self._original.chorus_lfo_depth,
            "LFO 深度：控制合唱延迟时间的摆动幅度；越高，空间宽度与音高摆动越明显。",
        )
        self.chorus_freq = self._new_field(
            "MasterChorusLfoFrequency",
            "LFO 频率",
            "chorus_lfo_frequency",
            self._original.chorus_lfo_frequency,
            "LFO 频率：控制合唱起伏速度；0 仍为慢速运动，本地试听按约 0.03–0.30 Hz 近似。",
        )
        chorus_rack.addWidget(
            EffectControlCard(tr("合唱反馈"), self.chorus_feedback), 1, Qt.AlignTop,
        )
        chorus_rack.addWidget(EffectControlCard(tr("LFO 深度"), self.chorus_depth), 1, Qt.AlignTop)
        chorus_rack.addWidget(EffectControlCard(tr("LFO 频率"), self.chorus_freq), 1, Qt.AlignTop)
        rack_row.addWidget(chorus, stretch=3)
        body_layout.addLayout(rack_row)
        preview_note = QLabel(tr("游戏参数 · 本地 FX 试听为未校准近似"))
        preview_note.setObjectName("EffectPreviewNote")
        preview_note.setWordWrap(True)
        body_layout.addWidget(preview_note)
        body_layout.addStretch(1)
        layout.addWidget(body, stretch=1)

        footer = QFrame()
        footer.setObjectName("EffectDialogFooter")
        footer.setProperty("uiRole", "dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 10, 22, 10)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        buttons.setObjectName("MasterEffectsButtons")
        buttons.setProperty("uiRole", "dialogButtonRow")
        buttons.button(QDialogButtonBox.Apply).setText(tr("应用"))
        buttons.button(QDialogButtonBox.Apply).setProperty("kind", "convert")
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer_layout.addWidget(buttons)
        layout.addWidget(footer)

    @staticmethod
    def _section(title_text: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("EffectGroup")
        section.setProperty("uiRole", "effectGroup")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(16, 14, 16, 15)
        section_layout.setSpacing(9)
        section_layout.setAlignment(Qt.AlignTop)
        title = QLabel(tr(title_text))
        title.setObjectName("EffectGroupTitle")
        detail = QLabel(tr(description))
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        section_layout.addWidget(title)
        section_layout.addWidget(detail)
        return section, section_layout

    @staticmethod
    def _effect_rack() -> QHBoxLayout:
        rack = QHBoxLayout()
        rack.setContentsMargins(0, 2, 0, 0)
        rack.setSpacing(9)
        return rack

    def _new_field(
        self,
        object_name: str,
        accessible_name: str,
        field_name: str,
        raw_value: int,
        help_text: str,
    ) -> QSpinBox:
        field = QSpinBox()
        field.setObjectName(object_name)
        field.setRange(0, GAME_PERCENT_MAX)
        field.setValue(max(0, min(GAME_PERCENT_MAX, int(raw_value))))
        tooltip = tr(help_text)
        if int(raw_value) > GAME_PERCENT_MAX:
            tooltip += "\n" + trf(
                "导入原值 {value}；修改后按 0–100 写入。",
                value=int(raw_value),
            )
        field.setToolTip(tooltip)
        field.setAccessibleName(tr(accessible_name))
        field.valueChanged.connect(
            lambda _value, name=field_name: self._dirty_fields.add(name)
        )
        self._fields[field_name] = field
        return field

    def selected_master_effects(self) -> MasterEffects:
        """Preserve unedited imported bytes above the current UI range."""

        values = {
            "reverb_time": self._original.reverb_time,
            "delay_feedback": self._original.delay_feedback,
            "chorus_feedback": self._original.chorus_feedback,
            "chorus_lfo_depth": self._original.chorus_lfo_depth,
            "chorus_lfo_frequency": self._original.chorus_lfo_frequency,
        }
        for name in self._dirty_fields:
            values[name] = self._fields[name].value()
        return MasterEffects(**values)
