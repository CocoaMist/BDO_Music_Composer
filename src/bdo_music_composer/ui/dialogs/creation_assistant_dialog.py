"""Intent, alternatives, audition and explicit application in one authoring view."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStyle, QStyleOptionComboBox, QVBoxLayout, QWidget,
)

from bdo_midi import BDO_INSTRUMENT_NAMES
from bdo_midi.instruments import localized_bdo_instrument_name
from bdo_music_composer.creation.brief import CreationAction, CreationBrief, MusicalCharacter
from bdo_music_composer.creation.workspace import CreationContext, build_creation_alternatives, projected_tracks
from bdo_music_composer.ui.creation_audition_qt import CreationAudition
from bdo_music_composer.ui.creation_comparison_qt import CreationComparison
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig
from bdo_music_composer.ui.theme.symbols import FluentSymbol, draw_symbol
from bdo_music_composer.ui.ui_controls import ElidedComboBox, dialog_footer, dialog_header

AUDITION_HELP = "使用当前试听音源；最终效果请在游戏内复核。"

ACTION_LABELS = {
    CreationAction.DRAFT: "从空白写起",
    CreationAction.ACCOMPANY: "沿旋律添加伴奏",
    CreationAction.ADAPT: "适配游戏乐器",
    CreationAction.EXPRESS: "调整演奏表达",
}
CHARACTER_LABELS = {MusicalCharacter.LYRICAL: "抒情舒展", MusicalCharacter.LIGHT: "轻快灵动", MusicalCharacter.DRIVING: "鲜明有力"}
PART_LABELS = {"melody": "旋律", "harmony": "和声", "bass": "低音", "drums": "鼓组", "adaptation": "乐器适配", "expression": "演奏表达"}
FINDING_LABELS = {
    "rule_draft": "这是基于音乐规则的创作草稿，可以继续手改。",
    "empty_reference": "所选范围没有旋律依据，暂不添加伴奏。",
    "no_changes": "在这些条件下没有需要应用的改动。",
    "unknown_range": "这个乐器的游戏音域证据不完整；已保留原音高。",
    "explicit_gm_drums": "已按你选择的 GM 鼓编码转换为游戏鼓组。",
    "octave_moves": "调整了 {count} 个音符的八度或鼓键。",
    "articulation_resets": "调整了 {count} 个与目标乐器不兼容的奏法值。",
    "preserved_expression": "保留了 {count} 个已有力度变化的小节。",
    "protected_clip_edges": "保留了 {count} 个跨越片段边界的长音。",
    "sustained_harmony": "和声采用整小节延音，保留旋律空间。",
    "pulsed_harmony": "和声采用半小节脉动，增加节拍推动。",
    "arpeggiated_harmony": "和声采用分解织体，让声部逐音流动。",
}
ERROR_LABELS = {
    "select a source track": "请选择一条参考轨道。",
    "the score exceeds the authoring note limit": "曲谱超过创作助手的音符上限，请先缩小工程。",
    "authoring requires a meter with denominator 4": "创作助手目前需要以四分音符为拍号分母。",
    "authoring currently supports meters 2/4 through 6/4": "创作助手目前支持 2/4 到 6/4 拍。",
    "accompaniment requires a melodic reference": "请选择旋律乐器作为伴奏参考。",
    "select a Clip before shaping expression": "请选择要调整表达的片段。",
    "melodic and percussion tracks cannot exchange roles": "旋律轨和鼓轨需要使用各自的乐器。",
    "the selected instrument cannot represent this pitch class": "所选乐器的已知音域无法保留这些音级，请换一个乐器。",
    "choose GM encoding explicitly for noncanonical drum input": "这些鼓键尚未规范；若来自 GM MIDI，请勾选 GM 鼓编码。",
    "an imported drum pitch has no confirmed BDO mapping": "部分 GM 鼓键没有已确认的游戏映射，请先手动指定。",
    "expression would exceed the selected Clip": "建议音长超出片段边界，请缩小范围或关闭音长调整。",
    "the editor changed after analysis; analyse again": "工程已发生变化，请重新打开创作助手再分析。",
    "destination game instrument has conflicting mixer states": "目标游戏乐器的已有轨道混音不一致，请先统一音量与效果发送。",
}


class _CreationComboBox(ElidedComboBox):
    _CHEVRON_SIZE = 12

    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet(f"""
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox::down-arrow {{ width: 0; height: 0; }}
            QComboBox QAbstractItemView::item:selected {{
                color: {hig.SELECTION_TEXT};
                background: {hig.SELECTION};
            }}
        """)
        self._chevron = None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self)
        scale = self.devicePixelRatioF()
        if self._chevron is None or self._chevron.devicePixelRatio() != scale:
            self._chevron = draw_symbol(
                FluentSymbol.CHEVRON_DOWN, hig.SECONDARY_TEXT, round(self._CHEVRON_SIZE * scale)
            )
            self._chevron.setDevicePixelRatio(scale)
        half_size = self._CHEVRON_SIZE // 2
        with QPainter(self) as painter:
            painter.setOpacity(1.0 if self.isEnabled() else 0.5)
            painter.drawPixmap(arrow.center() - QPoint(half_size, half_size), self._chevron)


class CreationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, context, brief, clip_id, parent):
        super().__init__(parent)
        self.context, self.brief, self.clip_id = context, brief, clip_id

    def run(self):
        try:
            sessions = build_creation_alternatives(
                self.context, self.brief, self.clip_id,
                cancelled=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.succeeded.emit(sessions)
        except Exception as exc:
            self.failed.emit(str(exc))


class CreationAssistantDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        selected = getattr(host, "selected_track", None)
        self.initial_track_id = getattr(selected, "track_id", None)
        self.initial_clip_id = str(getattr(getattr(host, "timeline", None), "_selected_clip_id", "") or "")
        self.context = CreationContext.capture(host.tracks, host.bpm_override or host.bpm, host.time_sig, host.time_sig_denominator)
        self._has_original_score = any(track.notes for track in self.context.tracks)
        self.sessions = ()
        self.worker = None
        self.part_checks = {}
        self._pending_close = False
        self._rendering = False
        self.result_tracks = None
        self.setObjectName("CreationAssistantDialog")
        self.setProperty("uiSurface", "workflow")
        title = "创作助手"
        subtitle = "选择想做的事，比较候选，再把选中的改动加入工程。"
        self.setWindowTitle(tr(title))
        self.setMinimumSize(600, 480)
        available = host.screen().availableGeometry()
        self.resize(
            min(940, available.width()),
            min(810, available.height() - hig.CAPTION_HEIGHT),
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(dialog_header(tr(title), tr(subtitle)))
        scroll = QScrollArea()
        self.content_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        columns = QHBoxLayout(content)
        self.columns = columns
        columns.setSizeConstraint(QLayout.SetNoConstraint)
        columns.setContentsMargins(24, 16, 24, 18)
        self.settings_column = QWidget()
        settings = QVBoxLayout(self.settings_column)
        settings.setContentsMargins(0, 0, 0, 0)
        settings.setSpacing(12)
        review = QFrame()
        self.review_column = review
        review.setObjectName("CreationReview")
        body = QVBoxLayout(review)
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(12)
        columns.addWidget(self.settings_column, 1, Qt.AlignTop)
        columns.addWidget(review, 1, Qt.AlignTop)
        columns.setSpacing(16)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        self.controls = QFrame()
        self.controls.setObjectName("CreationSettings")
        form = QGridLayout(self.controls)
        form.setContentsMargins(14, 12, 14, 12)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        self.action_combo = _CreationComboBox()
        for key, label in ACTION_LABELS.items(): self.action_combo.addItem(tr(label), key.value)
        form.addWidget(QLabel(tr("想做什么")), 0, 0)
        form.addWidget(self.action_combo, 0, 1, 1, 3)
        self.source_combo = _CreationComboBox()
        form.addWidget(QLabel(tr("参考或目标")), 1, 0)
        form.addWidget(self.source_combo, 1, 1, 1, 3)
        self.scope_label = QLabel()
        self.scope_label.setObjectName("Muted")
        self.scope_label.setWordWrap(True)
        form.addWidget(self.scope_label, 2, 0, 1, 4)
        self.start_spin, self.length_spin = QSpinBox(), QSpinBox()
        self.start_spin.setRange(1, 4096)
        self.length_spin.setRange(1, 16)
        self.length_spin.setValue(8)
        form.addWidget(QLabel(tr("起始小节")), 3, 0)
        form.addWidget(self.start_spin, 3, 1)
        form.addWidget(QLabel(tr("小节数")), 3, 2)
        form.addWidget(self.length_spin, 3, 3)
        self.key_combo, self.mode_combo = _CreationComboBox(), _CreationComboBox()
        for i, name in enumerate(("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")): self.key_combo.addItem(name, i)
        self.key_combo.setProperty("i18nSkipItems", True)
        self.mode_combo.addItem(tr("大调"), False)
        self.mode_combo.addItem(tr("小调"), True)
        form.addWidget(QLabel(tr("调性")), 4, 0)
        form.addWidget(self.key_combo, 4, 1)
        form.addWidget(self.mode_combo, 4, 2, 1, 2)
        self.character_combo = _CreationComboBox()
        for key, label in CHARACTER_LABELS.items(): self.character_combo.addItem(tr(label), key.value)
        form.addWidget(QLabel(tr("音乐性格")), 5, 0)
        form.addWidget(self.character_combo, 5, 1, 1, 3)
        self.instrument_combos = {}
        for row, (key, label, default) in enumerate((("melody", "旋律或目标乐器", 17), ("harmony", "和声乐器", 17), ("bass", "低音乐器", 14)), 6):
            combo = _CreationComboBox()
            combo.setProperty("i18nSkipItems", True)
            for instrument in BDO_INSTRUMENT_NAMES:
                combo.addItem(localized_bdo_instrument_name(instrument, tr), instrument)
            combo.setCurrentIndex(combo.findData(default))
            form.addWidget(QLabel(tr(label)), row, 0)
            form.addWidget(combo, row, 1, 1, 3)
            self.instrument_combos[key] = combo
        self.rewrite_box = QCheckBox(tr("重塑已有力度"))
        self.rewrite_box.setToolTip(tr("重塑已有力度（默认只处理平直力度）"))
        self.duration_box = QCheckBox(tr("同时调整音长"))
        self.duration_box.setToolTip(tr("同时调整音长，保留手动奏法"))
        self.gm_box = QCheckBox(tr("输入使用 GM 鼓编码（仅鼓轨）"))
        form.addWidget(self.rewrite_box, 9, 0, 1, 4)
        form.addWidget(self.duration_box, 10, 0, 1, 4)
        form.addWidget(self.gm_box, 11, 0, 1, 4)
        settings.addWidget(self.controls)
        self.generate_button = QPushButton(tr("生成候选"))
        self.generate_button.setProperty("kind", "primary")
        self.generate_button.clicked.connect(self._generate)
        settings.addWidget(self.generate_button)
        settings.addStretch(1)
        self.status_label = QLabel(tr("还没有改动工程。先生成候选，再比较试听。"))
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        body.addWidget(self.status_label)
        self.candidate_panel = QWidget()
        candidates = QVBoxLayout(self.candidate_panel)
        candidates.setContentsMargins(0, 0, 0, 0)
        candidates.setSpacing(10)
        body.addWidget(self.candidate_panel)
        self.candidate_combo = _CreationComboBox()
        self.candidate_combo.setAccessibleName(tr("候选方案"))
        candidates.addWidget(self.candidate_combo)
        candidates.addWidget(QLabel(tr("选择要应用的声部或改动")))
        self.parts_box = QFrame()
        self.parts_layout = QVBoxLayout(self.parts_box)
        self.parts_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_layout.setSpacing(8)
        candidates.addWidget(self.parts_box)
        self.overview = CreationComparison()
        candidates.addWidget(self.overview)
        self.findings_label = QLabel()
        self.findings_label.setObjectName("Muted")
        self.findings_label.setWordWrap(True)
        candidates.addWidget(self.findings_label)
        self.audition_controls = QWidget()
        audition_layout = QVBoxLayout(self.audition_controls)
        audition_layout.setContentsMargins(0, 0, 0, 0)
        audition_layout.setSpacing(body.spacing())
        transport = QHBoxLayout()
        self.original_button = QPushButton(tr("试听原稿"))
        self.original_button.setVisible(self._has_original_score)
        self.candidate_button = QPushButton(tr("试听所选建议"))
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.setEnabled(False)
        for button in (self.original_button, self.candidate_button, self.stop_button): transport.addWidget(button)
        audition_layout.addLayout(transport)
        self.audio_status = QLabel(tr(AUDITION_HELP))
        self.audio_status.setObjectName("Muted")
        self.audio_status.setWordWrap(True)
        audition_layout.addWidget(self.audio_status)
        body.addWidget(self.audition_controls)
        self.audition = CreationAudition(host, self)
        self.audition.active_changed.connect(self._audition_active_changed)
        self.audition.status_changed.connect(self.audio_status.setText)
        self.original_button.clicked.connect(lambda: self._listen(False))
        self.candidate_button.clicked.connect(lambda: self._listen(True))
        self.stop_button.clicked.connect(self.audition.stop)
        self.feedback_box = QCheckBox(tr("记录选择（仅本机，不含曲谱）"))
        self.feedback_box.setToolTip(tr("仅在本机记录这次选择，供后续改进（不含曲谱）"))
        body.addWidget(self.feedback_box)
        self.not_useful_button = QPushButton(tr("记录：这版不合适"))
        self.not_useful_button.setVisible(False)
        self.feedback_box.toggled.connect(self.not_useful_button.setVisible)
        self.not_useful_button.clicked.connect(self._record_not_useful)
        body.addWidget(self.not_useful_button)
        body.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText(tr("应用所选建议"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.apply_button.clicked.connect(self._accept_proposal)
        buttons.rejected.connect(self.reject)
        root.addWidget(dialog_footer(buttons, QDialogButtonBox.Apply))
        for widget, source in (
            (self.action_combo, "想做什么"),
            (self.source_combo, "参考或目标"),
            (self.start_spin, "起始小节"),
            (self.length_spin, "小节数"),
            (self.key_combo, "调性"),
            (self.mode_combo, "调式"),
            (self.character_combo, "音乐性格"),
            (self.instrument_combos["melody"], "旋律或目标乐器"),
            (self.instrument_combos["harmony"], "和声乐器"),
            (self.instrument_combos["bass"], "低音乐器"),
        ):
            widget.setAccessibleName(tr(source))
            if isinstance(widget, QSpinBox):
                widget.lineEdit().setAccessibleName(tr(source))
        self.field_labels = {}
        for index in range(form.count()):
            label = form.itemAt(index).widget()
            if isinstance(label, QLabel):
                row, column, _, span = form.getItemPosition(index)
                item = form.itemAtPosition(row, column + span)
                if item is not None and isinstance(item.widget(), (QComboBox, QSpinBox)):
                    label.setBuddy(item.widget())
                    self.field_labels[item.widget()] = label
        self.action_combo.currentIndexChanged.connect(self._action_changed)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.candidate_combo.currentIndexChanged.connect(self._candidate_changed)
        for widget in (self.key_combo, self.mode_combo, self.character_combo, *self.instrument_combos.values()): widget.currentIndexChanged.connect(self._invalidate)
        for widget in (self.start_spin, self.length_spin): widget.valueChanged.connect(self._invalidate)
        for widget in (self.rewrite_box, self.duration_box, self.gm_box): widget.toggled.connect(self._invalidate)
        self.finished.connect(lambda _: self.audition.stop())
        if self._has_original_score: self.action_combo.setCurrentIndex(1)
        self._action_changed()
        content.installEventFilter(self)
        scroll.viewport().installEventFilter(self)
        self._update_columns()

    def _update_columns(self) -> None:
        margins = self.columns.contentsMargins()
        required = (
            self.settings_column.minimumSizeHint().width()
            + self.review_column.minimumSizeHint().width()
            + self.columns.spacing() + margins.left() + margins.right()
        )
        side_by_side = self.content_scroll.viewport().width() >= required
        direction = QBoxLayout.LeftToRight if side_by_side else QBoxLayout.TopToBottom
        if self.columns.direction() != direction:
            self.columns.setDirection(direction)
            self.columns.setStretch(0, int(side_by_side))
            self.columns.setStretch(1, int(side_by_side))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self._update_columns()
        return super().eventFilter(watched, event)

    @property
    def action(self): return CreationAction(self.action_combo.currentData())

    def _action_changed(self, _=0):
        selected = self.source_combo.currentData() or (self.initial_track_id, self.initial_clip_id)
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        action = self.action
        for track in self.context.tracks:
            if action in (CreationAction.ADAPT, CreationAction.ACCOMPANY) or not track.arrangement_clips:
                self.source_combo.addItem(track.display_name, (track.track_id, ""))
            if action in (CreationAction.EXPRESS, CreationAction.ACCOMPANY):
                for i, clip in enumerate(track.arrangement_clips):
                    self.source_combo.addItem(trf("{track} · 片段 {number}", track=track.display_name, number=i+1), (track.track_id, clip.clip_id))
        # Qt compares opaque Python tuple variants by identity in findData;
        # compare stable track/Clip keys explicitly when rebuilding options.
        preferred = next((i for i in range(self.source_combo.count()) if self.source_combo.itemData(i) == selected), -1)
        if preferred < 0:
            preferred = next((i for i in range(self.source_combo.count()) if self.source_combo.itemData(i)[0] == selected[0]), 0)
        self.source_combo.setCurrentIndex(preferred)
        self.source_combo.setProperty("i18nSkipItems", True)
        self.source_combo.blockSignals(False)
        self.source_combo.refresh_text_tooltip()
        composing = action in (CreationAction.DRAFT, CreationAction.ACCOMPANY)
        for field, visible in (
            (self.source_combo, action is not CreationAction.DRAFT),
            (self.start_spin, action is not CreationAction.ADAPT),
            (self.length_spin, action is not CreationAction.ADAPT),
            (self.key_combo, composing),
            (self.mode_combo, composing),
            (self.character_combo, action is not CreationAction.ADAPT),
            (self.instrument_combos["melody"], action in (CreationAction.DRAFT, CreationAction.ADAPT)),
            (self.instrument_combos["harmony"], composing),
            (self.instrument_combos["bass"], composing),
        ):
            field.setVisible(visible)
            if label := self.field_labels.get(field):
                label.setVisible(visible)
        self.rewrite_box.setVisible(action is CreationAction.EXPRESS)
        self.duration_box.setVisible(action is CreationAction.EXPRESS)
        self.gm_box.setVisible(action is CreationAction.ADAPT)
        self.scope_label.setText(tr({CreationAction.DRAFT: "新增独立声部，保留已有内容。", CreationAction.ACCOMPANY: "读取所选旋律，在指定小节添加新声部，保留原旋律。", CreationAction.ADAPT: "适配整条目标轨道，包括它的所有片段；保留音符数量和节奏。", CreationAction.EXPRESS: "仅调整指定片段和小节；保留音高、起音和手动奏法。"}[action]))
        self._source_changed()

    def _source_changed(self, _=0):
        data = self.source_combo.currentData()
        if data:
            track = next(t for t in self.context.tracks if t.track_id == data[0])
            if self.action is CreationAction.ADAPT:
                combo = self.instrument_combos["melody"]
                combo.setCurrentIndex(combo.findData(track.bdo_instrument_id))
            if data[1]:
                clip = next(c for c in track.arrangement_clips if c.clip_id == data[1])
                bar_ms = 60_000 / self.context.bpm * self.context.meter
                self.start_spin.setValue(int(clip.start_ms // bar_ms) + 1)
                self.length_spin.setValue(min(16, max(1, math.ceil(clip.end_ms / bar_ms) - (self.start_spin.value()-1))))
        self._invalidate()

    def brief(self):
        source = self.source_combo.currentData()
        return CreationBrief(self.action, MusicalCharacter(self.character_combo.currentData()),
            int(self.key_combo.currentData()), bool(self.mode_combo.currentData()), self.start_spin.value()-1, self.length_spin.value(),
            source[0] if source and self.action is not CreationAction.DRAFT else None,
            int(self.instrument_combos["melody"].currentData()), int(self.instrument_combos["harmony"].currentData()), int(self.instrument_combos["bass"].currentData()),
            rewrite_velocity=self.rewrite_box.isChecked(), shape_durations=self.duration_box.isChecked(), drums_are_gm=self.gm_box.isChecked())

    def _invalidate(self, _=None):
        if self._rendering: return
        self.audition.stop()
        self.sessions = ()
        self.result_tracks = None
        self.candidate_combo.clear()
        self.candidate_panel.hide()
        self.candidate_button.hide()
        self.audition_controls.setVisible(self._has_original_score)
        self.feedback_box.hide()
        self.not_useful_button.hide()
        self.apply_button.setEnabled(False)
        self.candidate_button.setEnabled(False)
        self.findings_label.clear()
        self._clear_parts()
        self.status_label.show()
        self.status_label.setText(tr("还没有改动工程。先生成候选，再比较试听。"))

    def _generate(self):
        if self.worker is not None: return
        self._invalidate()
        brief = self.brief()
        source = self.source_combo.currentData()
        self.controls.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.status_label.setText(tr("正在生成创作候选…"))
        worker = CreationWorker(self.context, brief, source[1] if source else "", self)
        self.worker = worker
        worker.succeeded.connect(self._generated)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _generated(self, sessions):
        if self._pending_close: return
        self.sessions = sessions
        self.candidate_combo.blockSignals(True)
        self.candidate_combo.clear()
        for i, _ in enumerate(sessions): self.candidate_combo.addItem(trf("候选 {number}", number=i+1), i)
        self.candidate_combo.blockSignals(False)
        self.candidate_combo.refresh_text_tooltip()
        self.candidate_panel.setVisible(bool(sessions))
        self.candidate_combo.setVisible(len(sessions) > 1)
        self.candidate_button.setVisible(bool(sessions))
        self.audition_controls.setVisible(self._has_original_score or bool(sessions))
        self.feedback_box.setVisible(bool(sessions))
        self.not_useful_button.setVisible(bool(sessions) and self.feedback_box.isChecked())
        self._candidate_changed()
        if sessions:
            QTimer.singleShot(0, self, self._reveal_candidate)

    def _reveal_candidate(self) -> None:
        if self.candidate_panel.isVisible() and self.columns.direction() == QBoxLayout.TopToBottom:
            top = self.review_column.mapTo(self.content_scroll.widget(), QPoint()).y()
            self.content_scroll.verticalScrollBar().setValue(top - hig.GROUP_GAP)

    def _failed(self, error):
        self.status_label.setText(trf("无法生成候选：{error}", error=tr(ERROR_LABELS.get(error, error))))
        self.status_label.show()

    def _worker_finished(self):
        worker, self.worker = self.worker, None
        if worker is not None: worker.deleteLater()
        self.controls.setEnabled(True)
        self.generate_button.setEnabled(True)
        if self._pending_close: super().reject()

    def _clear_parts(self):
        self.part_checks = {}
        while self.parts_layout.count():
            item = self.parts_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()

    def current_session(self):
        i = self.candidate_combo.currentIndex()
        return self.sessions[i] if 0 <= i < len(self.sessions) else None

    def selected_parts(self): return frozenset(key for key, box in self.part_checks.items() if box.isChecked())

    def _candidate_changed(self, _=0, *, keep_parts: frozenset[str] | None = None):
        self.audition.stop()
        self._clear_parts()
        session = self.current_session()
        if session is None: return
        self.not_useful_button.setEnabled(True)
        for part in session.candidate.parts:
            box = QCheckBox(trf(
                "{part} · {instrument} · {count} 音符",
                part=tr(PART_LABELS[part.key]),
                instrument=localized_bdo_instrument_name(part.instrument_id, tr),
                count=part.note_count,
            ))
            box.setChecked(part.key != "drums" if keep_parts is None else part.key in keep_parts)
            box.toggled.connect(self._parts_changed)
            self.part_checks[part.key] = box
            self.parts_layout.addWidget(box)
        self.findings_label.setText("\n".join(trf(FINDING_LABELS[f.code], count=f.count) if "{count}" in FINDING_LABELS[f.code] else tr(FINDING_LABELS[f.code]) for f in session.candidate.findings))
        self.findings_label.setVisible(bool(session.candidate.findings))
        self._parts_changed()

    def _parts_changed(self, _=None):
        self.audition.stop()
        session = self.current_session()
        if session is None: return
        try:
            self.result_tracks = session.materialize(self.selected_parts())
            changed = self.result_tracks != list(self.context.tracks)
            self.apply_button.setEnabled(changed)
            self.candidate_button.setEnabled(changed)
            start, end = self._preview_time_range()
            brief = session.candidate.brief
            original, selected = self._comparison_tracks(brief)
            bar_duration = 60_000.0 / self.context.bpm * self.context.meter
            self.overview.set_comparison(original, selected, start, end, bar_duration)
            self.overview.show()
            self.status_label.setText(tr("候选已准备好。试听并选择要保留的声部或改动。") if changed else tr("在这些条件下没有需要应用的改动。"))
            self.status_label.setVisible(not changed)
        except (ValueError, TypeError) as exc:
            self.result_tracks = None
            self.overview.hide()
            self.apply_button.setEnabled(False)
            self.candidate_button.setEnabled(False)
            self._failed(str(exc))

    def _comparison_tracks(self, brief: CreationBrief):
        original, selected = self.context.tracks, self.result_tracks
        if brief.action in (CreationAction.EXPRESS, CreationAction.ADAPT):
            return ([track for track in original if track.track_id == brief.source_track_id],
                    [track for track in selected if track.track_id == brief.source_track_id])
        return original, selected

    def _preview_time_range(self):
        session = self.current_session()
        brief = session.candidate.brief if session else self.brief()
        if brief.action is CreationAction.ADAPT:
            target = next((t for t in self.context.tracks if t.track_id == brief.source_track_id), None)
            notes = projected_tracks([target])[0].notes if target is not None else []
            if notes:
                return min(n.start for n in notes), max(n.start + n.dur for n in notes)
        return brief.time_range(self.context.bpm, self.context.meter)

    def _listen(self, suggested):
        start, end = self._preview_time_range()
        tracks = self.result_tracks if suggested else list(self.context.tracks)
        if tracks is not None: self.audition.play(tracks, start, end)

    def _audition_active_changed(self, active: bool) -> None:
        self.stop_button.setEnabled(active)
        if not active:
            self.audio_status.setText(tr(AUDITION_HELP))

    def _accept_proposal(self):
        if self.worker is not None or not self.apply_button.isEnabled(): return
        try:
            self.context.assert_current(self.host.tracks, self.host.bpm_override or self.host.bpm, self.host.time_sig, self.host.time_sig_denominator)
        except ValueError as exc:
            self.apply_button.setEnabled(False)
            self._failed(str(exc))
            return
        self.accept()

    def _record_not_useful(self):
        session = self.current_session()
        if session is not None and self.feedback_box.isChecked():
            self.host._record_creation_choice(session, self.selected_parts(), "not_useful")
            self.not_useful_button.setEnabled(False)

    def reject(self):
        self.audition.stop()
        if self.worker is not None:
            self._pending_close = True
            self.worker.requestInterruption()
            return
        super().reject()

    def retranslate_dynamic_content(self):
        if not hasattr(self, "audition"): return
        self._rendering = True
        for combo, labels in ((self.action_combo, ACTION_LABELS), (self.character_combo, CHARACTER_LABELS)):
            combo.blockSignals(True)
            for i in range(combo.count()): combo.setItemText(i, tr(labels[combo.itemData(i)]))
            combo.blockSignals(False)
            combo.refresh_text_tooltip()
        self.source_combo.blockSignals(True)
        for i in range(self.source_combo.count()):
            track_id, clip_id = self.source_combo.itemData(i)
            track = next(t for t in self.context.tracks if t.track_id == track_id)
            if clip_id:
                number = next(j+1 for j,c in enumerate(track.arrangement_clips) if c.clip_id == clip_id)
                self.source_combo.setItemText(i, trf("{track} · 片段 {number}", track=track.display_name, number=number))
        self.source_combo.blockSignals(False)
        self.source_combo.refresh_text_tooltip()
        for combo in self.instrument_combos.values():
            combo.blockSignals(True)
            for index in range(combo.count()):
                combo.setItemText(index, localized_bdo_instrument_name(combo.itemData(index), tr))
            combo.blockSignals(False)
            combo.refresh_text_tooltip()
        if self.current_session() is not None:
            self._candidate_changed(keep_parts=self.selected_parts())
        self._rendering = False
