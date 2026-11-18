"""Unified track, note, and effect inspector for the composer workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from bdo_common.bdo_track_effects import GAME_PERCENT_MAX
from bdo_midi import BDO_INSTRUMENT_NAMES
from bdo_midi.instruments import localized_bdo_instrument_name
from bdo_music_composer.ui.dialogs.track_settings_dialogs import TrackFxDialog
from bdo_music_composer.ui.dialogs.effect_controls_qt import EffectControlCard, EffectModeCard
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.symbols import FluentSymbol, draw_symbol
from bdo_music_composer.ui.ui_controls import ElidedComboBox, ElidedLabel, GlyphSpinBox, PillButton
from bdo_music_composer.ui.track_properties_qt import apply_track_fx, apply_track_pitch


class WorkbenchInspector(QFrame):
    dismiss_requested = Signal()

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host
        self.track = None
        self.fx_dialog = None
        self.setObjectName("WorkbenchInspector")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("WorkbenchInspectorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(hig.PANEL_PADDING, hig.ITEM_GAP, hig.ITEM_GAP, hig.ITEM_GAP)
        title = QLabel(tr("属性"))
        title.setObjectName("WorkbenchTrackTitle")
        header_layout.addWidget(title, 1)
        close = PillButton("", "ghost", FluentSymbol.CLOSE)
        close.setObjectName("WorkbenchInspectorClose")
        close.setFixedSize(hig.BUTTON_HEIGHT, hig.BUTTON_HEIGHT)
        close.setAccessibleName(tr("关闭"))
        close.setToolTip(tr("关闭"))
        close.clicked.connect(self.dismiss_requested.emit)
        header_layout.addWidget(close)
        layout.addWidget(header)

        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.empty_page = self._empty_page()
        self.pages.addWidget(self.empty_page)
        self.properties_page = QWidget()
        properties_layout = QVBoxLayout(self.properties_page)
        properties_layout.setContentsMargins(0, 0, 0, 0)
        properties_layout.setSpacing(0)
        self.pages.addWidget(self.properties_page)
        context = QFrame()
        context.setObjectName("WorkbenchInspectorContext")
        context_layout = QHBoxLayout(context)
        context_layout.setContentsMargins(
            hig.PANEL_PADDING, hig.GROUP_GAP, hig.PANEL_PADDING, hig.CONTROL_GAP,
        )
        context_layout.setSpacing(hig.ITEM_GAP)
        self.track_identity = QWidget(context)
        self.track_identity.setFixedSize(3, hig.TYPE_DOCUMENT)
        self.track_identity.setAutoFillBackground(True)
        context_layout.addWidget(self.track_identity, alignment=Qt.AlignVCenter)
        self.name = ElidedLabel(tr("未选择轨道"), maximum_hint_width=220)
        self.name.setObjectName("WorkbenchTrackTitle")
        self.name.setTextFormat(Qt.PlainText)
        self.name.setProperty("i18nSkipText", True)
        self.name.setProperty("i18nSkipToolTip", True)
        context_layout.addWidget(self.name, 1)
        self.details = QLabel()
        self.details.setObjectName("WorkbenchInspectorCount")
        context_layout.addWidget(self.details)
        self.track_context = context
        properties_layout.addWidget(context)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("WorkbenchInspectorTabs")
        self.tabs.setDocumentMode(True)
        properties_layout.addWidget(self.tabs, 1)
        self.track_page = QWidget()
        track_layout = QVBoxLayout(self.track_page)
        track_layout.setContentsMargins(hig.PANEL_PADDING, hig.GROUP_GAP, hig.PANEL_PADDING, hig.ITEM_GAP)
        track_layout.setSpacing(hig.GROUP_GAP)
        track_fields = QFrame()
        track_fields.setObjectName("WorkbenchTrackFields")
        fields_layout = QGridLayout(track_fields)
        fields_layout.setContentsMargins(*(hig.GROUP_GAP,) * 4)
        fields_layout.setHorizontalSpacing(hig.GROUP_GAP)
        fields_layout.setVerticalSpacing(hig.CONTROL_GAP)
        fields_layout.setColumnStretch(0, 1)
        fields_layout.setColumnStretch(1, 1)
        self.instrument = ElidedComboBox()
        self.instrument.setObjectName("WorkbenchInspectorInstrument")
        self.instrument.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.instrument.setFixedHeight(hig.BUTTON_HEIGHT)
        for instrument_id in BDO_INSTRUMENT_NAMES:
            self.instrument.addItem(localized_bdo_instrument_name(instrument_id, tr), instrument_id)
        self._field(fields_layout, tr("乐器"), self.instrument, row=0, column=0, span=2)
        self.instrument.activated.connect(self._instrument_changed)
        fields_layout.setRowMinimumHeight(2, hig.CONTROL_GAP)
        self.volume = GlyphSpinBox()
        self.volume.setObjectName("WorkbenchInspectorStep")
        self.volume.setFixedHeight(hig.BUTTON_HEIGHT)
        self.volume.setRange(0, GAME_PERCENT_MAX)
        self.volume.setSuffix("%")
        self.volume.setKeyboardTracking(False)
        self._field(fields_layout, tr("游戏音量"), self.volume, row=3, column=0)
        self.volume.editingFinished.connect(self._volume_changed)
        self.pitch = GlyphSpinBox()
        self.pitch.setObjectName("WorkbenchInspectorStep")
        self.pitch.setFixedHeight(hig.BUTTON_HEIGHT)
        self.pitch.setRange(-48, 48)
        self.pitch.setKeyboardTracking(False)
        self._field(fields_layout, tr("轨道移调"), self.pitch, row=3, column=1)
        self.pitch.editingFinished.connect(self._pitch_changed)
        track_layout.addWidget(track_fields)
        self.velocity_section = host._build_selection_velocity_percent_control()
        self.velocity_section.layout().setContentsMargins(*(hig.GROUP_GAP,) * 4)
        track_layout.addWidget(self.velocity_section)
        track_layout.addStretch(1)
        self.tabs.addTab(self._scroll(self.track_page), tr("轨道"))
        self.notes = QStackedWidget()
        self.note_placeholder = QLabel(tr("双击片段，开始编辑音符。"))
        self.note_placeholder.setWordWrap(True)
        self.note_placeholder.setAlignment(Qt.AlignCenter)
        self.note_placeholder.setContentsMargins(*(hig.PANEL_PADDING,) * 4)
        self.notes.addWidget(self.note_placeholder)
        self.tabs.addTab(self._scroll(self.notes), tr("音符"))
        self.effects = QWidget()
        self.effects_layout = QVBoxLayout(self.effects)
        self.effects_layout.setContentsMargins(*(hig.PANEL_PADDING,) * 4)
        self.effects_page = QWidget()
        effects_page_layout = QVBoxLayout(self.effects_page)
        effects_page_layout.setContentsMargins(0, 0, 0, 0)
        effects_page_layout.setSpacing(0)
        effects_page_layout.addWidget(self._scroll(self.effects), 1)
        actions = QFrame()
        actions.setObjectName("WorkbenchInspectorActions")
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(hig.PANEL_PADDING, hig.ITEM_GAP, hig.PANEL_PADDING, hig.GROUP_GAP)
        self.fx_apply_button = QPushButton(tr("应用效果"))
        self.fx_apply_button.setProperty("kind", "convert")
        self.fx_apply_button.setEnabled(False)
        self.fx_apply_button.clicked.connect(self._apply_effects)
        actions_layout.addWidget(self.fx_apply_button)
        effects_page_layout.addWidget(actions)
        self.tabs.addTab(self.effects_page, tr("效果"))
        self.tabs.currentChanged.connect(self._tab_changed)
        self.notes.currentChanged.connect(self._refresh_pages)
        self._clear_effects()
        self.refresh(None)

    @staticmethod
    def _empty_page() -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(hig.SECTION_GAP, hig.PANEL_PADDING, hig.SECTION_GAP, hig.SECTION_GAP)
        layout.setSpacing(hig.ITEM_GAP)
        layout.addStretch(1)
        icon = QLabel()
        icon.setObjectName("WorkbenchInspectorEmptyIcon")
        ratio = icon.devicePixelRatioF()
        symbol = draw_symbol(FluentSymbol.MARQUEE, hig.SECONDARY_TEXT, round(20 * ratio))
        symbol.setDevicePixelRatio(ratio)
        icon.setPixmap(symbol)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(40, 40)
        layout.addWidget(icon, 0, Qt.AlignLeft)
        title = QLabel(tr("未选择轨道"))
        title.setObjectName("WorkbenchPanelMessageTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        hint = QLabel(tr("选中时间轴上的轨道或片段，即可查看属性。"))
        hint.setObjectName("WorkbenchPanelMessageBody")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(2)
        return page

    @staticmethod
    def _scroll(widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setObjectName("WorkbenchInspectorScroll")
        scroll.verticalScrollBar().setAccessibleName(tr("属性"))
        scroll.verticalScrollBar().setFocusPolicy(Qt.StrongFocus)
        scroll.setWidget(widget)
        return scroll

    @staticmethod
    def _field(
        layout: QGridLayout, text: str, control: QWidget, *, row: int, column: int, span: int = 1,
    ) -> None:
        label = QLabel(text)
        label.setObjectName("WorkbenchMuted")
        label.setWordWrap(True)
        label.setBuddy(control)
        control.setAccessibleName(text)
        if isinstance(control, QSpinBox):
            control.lineEdit().setAccessibleName(text)
        layout.addWidget(label, row, column, 1, span, Qt.AlignBottom)
        layout.addWidget(control, row + 1, column, 1, span)

    def refresh(self, track) -> None:
        if track not in self.host.tracks:
            track = None
        changed = track is not self.track
        self.track = track
        # Disabling or hiding a focused spin box emits editingFinished.
        # Wait until the replacement track's values are loaded to accept edits.
        with QSignalBlocker(self.instrument), QSignalBlocker(self.volume), QSignalBlocker(self.pitch):
            self._refresh_pages()
            for widget in (self.instrument, self.volume, self.velocity_section):
                widget.setEnabled(track is not None)
            self.pitch.setEnabled(
                track is not None and not track.is_percussion and int(track.bdo_instrument_id) != 0x0D
            )
            if track is not None:
                self.instrument.setCurrentIndex(self.instrument.findData(int(track.bdo_instrument_id)))
                self.instrument.refresh_text_tooltip()
                raw_volume = int(track.bdo_track_volume)
                self.volume.setValue(raw_volume)
                self.volume.setToolTip(
                    trf("导入原值 {value}；修改后按 0–100 写入。", value=raw_volume)
                    if raw_volume > GAME_PERCENT_MAX else ""
                )
                override = self.host._pitch_transform_plan.override_for(track.track_id)
                self.pitch.setValue(override.semitones if override is not None else 0)
        self.name.setText(track.display_name if track else tr("未选择轨道"))
        self.details.setText(trf("{count} 个音符", count=f"{len(track.notes):,}") if track else "")
        color = QColor(track.color) if track else QColor()
        if not color.isValid():
            color = QColor(hig.PANEL)
        palette = self.track_identity.palette()
        if palette.color(QPalette.Window) != color:
            palette.setColor(QPalette.Window, color)
            self.track_identity.setPalette(palette)
        dialog = self.fx_dialog
        instrument_changed = (
            track is not None
            and dialog is not None
            and dialog.instrument_id != int(track.bdo_instrument_id)
        )
        if changed or instrument_changed:
            if (
                track is not None and dialog is not None and not instrument_changed
                and self.isVisible() and self.tabs.currentWidget() is self.effects_page
            ):
                dialog.track = track
                dialog.refresh_track_settings()
                self._fx_mode_dirty = False
                self._update_apply_state()
            else:
                self._clear_effects()
        elif dialog is not None:
            dialog.refresh_track_settings(keep_send_edits=True, keep_mode_edit=self._fx_mode_dirty)
            self._update_apply_state()
        self._ensure_visible_effects()

    def _refresh_pages(self) -> None:
        has_track = self.track is not None
        has_notes = self.notes.currentWidget() is not self.note_placeholder
        self.pages.setCurrentWidget(self.properties_page if has_track or has_notes else self.empty_page)
        self.track_context.setVisible(has_track)
        self.tabs.setTabEnabled(0, has_track or not has_notes)
        self.tabs.setTabEnabled(2, has_track or not has_notes)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_visible_effects()

    def retranslate_dynamic_content(self) -> None:
        self.refresh(self.track)

    def _instrument_changed(self) -> None:
        if self.track is None:
            return
        previous = int(self.track.bdo_instrument_id)
        self.track.bdo_instrument_id = int(self.instrument.currentData())
        self.host._on_track_instrument_changed(self.track, previous)
        self.refresh(self.track)

    def _volume_changed(self) -> None:
        track = self.track
        if track is None:
            return
        raw_volume = int(track.bdo_track_volume)
        shown_volume = min(GAME_PERCENT_MAX, max(0, raw_volume))
        next_volume = self.volume.value()
        if next_volume == shown_volume:
            return
        self.host._on_game_instrument_volume_committed(track, raw_volume, next_volume)
        self.refresh(track)

    def _pitch_changed(self) -> None:
        if self.track:
            apply_track_pitch(self.host, self.track, self.pitch.value())

    def _tab_changed(self, _index: int) -> None:
        self._ensure_visible_effects()

    def _ensure_visible_effects(self) -> None:
        if (
            self.isVisible() and self.tabs.currentWidget() is self.effects_page
            and self.track is not None and self.fx_dialog is None
        ):
            self._build_effects()

    def _clear_effects(self) -> None:
        if self.fx_dialog is not None:
            self.fx_dialog.deleteLater()
        self.fx_dialog = None
        self.fx_apply_button.setEnabled(False)
        while self.effects_layout.count():
            item = self.effects_layout.takeAt(0)
            if widget := item.widget():
                widget.hide()
                widget.deleteLater()
        if self.track is None:
            hint = QLabel(tr("请选择轨道或Clip"))
            hint.setObjectName("WorkbenchMuted")
            hint.setWordWrap(True)
            self.effects_layout.addWidget(hint)
            self.effects_layout.addStretch(1)

    def _build_effects(self) -> None:
        # Reuse the dialog's exact dirty-byte and unsupported-instrument rules.
        self._clear_effects()
        dialog = TrackFxDialog(self.host, self.track)
        dialog.setModal(False)
        body = dialog.findChild(QFrame, "EffectDialogBody")
        # Only the controls enter the inspector. Keeping QDialog's default
        # accept/reject handling outside the panel makes Return/Escape safe.
        body.setParent(self.effects)
        body.layout().setContentsMargins(0, 0, 0, 0)
        rack = body.findChild(QFrame, "EffectRack")
        rack.layout().setDirection(QHBoxLayout.TopToBottom)
        rack.layout().setContentsMargins(0, 0, 0, 0)
        for card in rack.findChildren(EffectControlCard) + rack.findChildren(EffectModeCard):
            card.use_compact_layout()
        for label in body.findChildren(QLabel):
            label.setWordWrap(True)
        self.effects_layout.addWidget(body)
        self.effects_layout.addStretch(1)
        self.fx_dialog = dialog
        self._fx_mode_dirty = False
        for field in dialog._effect_fields.values():
            field.valueChanged.connect(self._update_apply_state)
        if dialog.marnian_mode is not None:
            dialog.marnian_mode.activated.connect(self._mark_mode_dirty)
        body.show()

    def _mark_mode_dirty(self) -> None:
        self._fx_mode_dirty = True
        self._update_apply_state()

    def _update_apply_state(self) -> None:
        self.fx_apply_button.setEnabled(bool(
            self.fx_dialog and (self.fx_dialog.changed_send_indices() or self._fx_mode_dirty)
        ))

    def _apply_effects(self) -> None:
        track = self.track
        dialog = self.fx_dialog
        if track is None or dialog is None:
            return
        if dialog.instrument_id != int(track.bdo_instrument_id):
            self.refresh(track)
            return
        # Shared-instrument sends can change while this draft is open.
        dialog.refresh_track_settings(keep_send_edits=True, keep_mode_edit=self._fx_mode_dirty)
        apply_track_fx(self.host, track, dialog)
        dialog.refresh_track_settings()
        self._fx_mode_dirty = False
        self._update_apply_state()
