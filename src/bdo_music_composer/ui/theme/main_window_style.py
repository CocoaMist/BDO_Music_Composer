"""Canonical stylesheet mixin for the main BDO composer window."""

from __future__ import annotations

from string import Template

from . import hig_tokens as hig
from .fluent_theme import build_fluent_stylesheet, refresh_fluent_icons
from .workbench_style import HIG_QSS


class MainWindowStyleMixin:
    def _apply_style(self) -> None:
        style_sheet = Template("""
            QDialog QLabel { color: $TEXT; }
            QTextEdit#PromptText { background: transparent; border: 0; padding: 0; }
            QDialog#MasterEffectsDialog,
            QDialog#TrackFxDialog, QDialog#CreationAssistantDialog,
            QDialog#TrackPitchDialog, QDialog#ClipVelocityBaseDialog,
            QDialog#ConversionCheckDialog, QDialog#MidiOptimizeDialog,
            QDialog#ReleaseNotesDialog,
            QDialog#SelfUpdateDialog, QDialog#MidiNoteEditorDialog {
                background: $CANVAS;
                color: $TEXT;
            }
            QDialog[uiSurface="workflow"] {
                background: $CANVAS;
                color: $TEXT;
            }
            QFrame#EffectDialogBody {
                background: $CANVAS;
                border: 0;
            }
            QFrame#EffectRack {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${EFFECT_RACK_RADIUS}px;
            }
            QFrame#EffectGroup {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${PANEL_RADIUS}px;
            }
            QLabel#EffectGroupTitle {
                color: $TEXT;
                font-size: ${TYPE_BODY}px;
                font-weight: 700;
            }
            QFrame#EffectControlCard, QFrame#EffectModeCard {
                background: $CONTROL;
                border: 1px solid $SEPARATOR;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QLabel#EffectControlTitle {
                color: $TEXT;
                font-weight: 700;
                min-height: 28px;
            }
            QLabel#EffectControlScale {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_CAPTION}px;
            }
            QLabel#EffectModeEmblem {
                color: $SECONDARY_TEXT;
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${PANEL_RADIUS}px;
                font-size: 31px;
                font-weight: 700;
            }
            QComboBox#MarnianModeSelector {
                min-height: 20px;
                padding: 0 8px;
                font-weight: 700;
            }
            QLabel#EffectModeNote {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_CAPTION}px;
                min-height: 12px;
            }
            QDialog#MasterEffectsDialog QSpinBox[uiRole="effectValue"],
            QDialog#TrackFxDialog QSpinBox[uiRole="effectValue"] {
                min-height: 30px;
                max-height: 30px;
                padding: 0 7px;
                font-size: ${TYPE_DOCUMENT}px;
                font-weight: 700;
            }
            QSpinBox[uiRole="effectValue"]::up-button,
            QSpinBox[uiRole="effectValue"]::down-button {
                width: 0;
                border: 0;
            }
            QLabel#EffectScopeNotice {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${PANEL_RADIUS}px;
            }
            QLabel#EffectScopeNotice { color: $SECONDARY_TEXT; padding: 8px 10px; }
            QLabel#EffectPreviewNote {
                color: $SECONDARY_TEXT;
            }
            QLabel[uiRole="sectionTitle"] {
                color: $TEXT;
                font-size: ${TYPE_DOCUMENT}px;
                font-weight: 700;
            }
            QDialogButtonBox[uiRole="dialogButtonRow"] {
                background: transparent;
                border: 0;
                padding: 0;
            }
            QFrame#EditorQuantizeQuick {
                background: transparent;
                border: 0;
            }
            QLabel#QuantizeQuickLabel {
                color: $SECONDARY_TEXT;
                font-weight: 600;
            }
            QFrame#Inspector {
                background: $PANEL;
                border: 0;
                border-top: 1px solid $SEPARATOR;
                border-radius: 0;
            }
            QWidget#TimelineWorkspace, QWidget#TimelineCanvas {
                background: $PANEL;
                border: 0;
            }
            QFrame#TimelineBody {
                background: $CANVAS;
                border: 0;
            }
            QFrame#ToolbarSelectionVelocityGroup {
                background: transparent;
                border: 0;
            }
            QLabel#ToolbarSelectionVelocityTitle {
                background: transparent;
                border: 0;
                color: #d1d6d1;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 800;
            }
            QLabel#ToolbarSelectionVelocityScope {
                background: transparent;
                border: 0;
                color: #a1aaa4;
                font-size: ${TYPE_CAPTION}px;
                padding: 0 2px;
            }
            QSpinBox#ToolbarSelectionVelocityPercentValue {
                background: $CONTROL;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${CONTROL_RADIUS}px;
                color: $TEXT;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 900;
                padding: 1px 4px;
                selection-background-color: $SELECTION;
                selection-color: $SELECTION_TEXT;
            }
            QSpinBox#ToolbarSelectionVelocityPercentValue:disabled {
                color: $DISABLED_TEXT;
                border-color: $SEPARATOR;
            }
            QSlider#ToolbarSelectionVelocityPercent {
                min-height: 24px;
                max-height: 24px;
            }
            QSlider#ToolbarSelectionVelocityPercent::groove:horizontal {
                height: 4px;
                background: $CANVAS;
                border: 0;
                border-radius: ${SLIDER_TRACK_RADIUS}px;
            }
            QSlider#ToolbarSelectionVelocityPercent::sub-page:horizontal {
                background: $SELECTION_BORDER;
                border-radius: ${SLIDER_TRACK_RADIUS}px;
            }
            QSlider#ToolbarSelectionVelocityPercent::add-page:horizontal {
                background: $CANVAS;
                border-radius: ${SLIDER_TRACK_RADIUS}px;
            }
            QSlider#ToolbarSelectionVelocityPercent::handle:horizontal {
                width: 13px;
                margin: -5px 0;
                background: $SECONDARY_TEXT;
                border: 1px solid $SELECTION_INDICATOR;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QSlider#ToolbarSelectionVelocityPercent::handle:horizontal:disabled {
                background: $CONTROL;
                border-color: $CONTROL_BORDER;
            }
            QFrame#ToolbarGlobalGainGroup {
                background: transparent;
                border: none;
            }
            QLabel#ToolbarGlobalGainTitle {
                color: $TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 600;
                padding: 0 2px;
            }
            QComboBox#ToolbarGlobalGainMode {
                color: $TEXT; background: $CONTROL; border: 1px solid $CONTROL_BORDER;
                border-radius: ${CONTROL_RADIUS}px; padding: 0 27px 0 8px;
                min-height: 28px;
            }
            QComboBox#ToolbarGlobalGainMode:hover { background: $CONTROL_HOVER; }
            QComboBox#ToolbarGlobalGainMode:focus { border-color: $FOCUS; }
            QComboBox#ToolbarGlobalGainMode::drop-down {
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 26px; border: none; background: transparent;
            }
            QComboBox#ToolbarGlobalGainMode::down-arrow { image: none; width: 0; height: 0; }
            QCheckBox#ToolbarGlobalGainEqualize {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 700;
                spacing: 4px;
            }
            QCheckBox#ToolbarGlobalGainEqualize::indicator {
                width: 13px;
                height: 13px;
            }
            QSpinBox#ToolbarGlobalGainValue {
                background: $CONTROL;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${CONTROL_RADIUS}px;
                color: $TEXT;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 900;
                padding: 1px 4px;
                selection-background-color: $SELECTION;
                selection-color: $SELECTION_TEXT;
            }
            QSpinBox#ToolbarSelectionVelocityPercentValue:focus,
            QSpinBox#ToolbarGlobalGainValue:focus {
                border-color: $FOCUS;
            }
            QSlider#ToolbarGlobalGainSlider {
                min-height: 24px;
                max-height: 24px;
            }
            QSlider#ToolbarGlobalGainSlider::groove:horizontal {
                height: 7px;
                background: $CANVAS;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QSlider#ToolbarGlobalGainSlider::sub-page:horizontal {
                background: $SELECTION_BORDER;
                border: 1px solid $SELECTION_BORDER;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QSlider#ToolbarGlobalGainSlider::add-page:horizontal {
                background: $CONTROL;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QSlider#ToolbarGlobalGainSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -6px 0;
                background: $ACCENT;
                border: 2px solid $SELECTION_INDICATOR;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QSlider#ToolbarGlobalGainSlider::handle:horizontal:hover {
                background: $ACCENT_HOVER;
                border-color: $TEXT;
            }
            QSlider#ToolbarGlobalGainSlider:disabled,
            QSpinBox#ToolbarGlobalGainValue:disabled,
            QCheckBox#ToolbarGlobalGainEqualize:disabled,
            QLabel#ToolbarGlobalGainTitle:disabled {
                color: $DISABLED_TEXT;
            }
            QFrame#GlobalBpmControl {
                background: #202425;
                border: 1px solid #414746;
                border-radius: ${GROUP_RADIUS}px;
                min-height: 36px;
                max-height: 36px;
            }
            QFrame#GlobalBpmControl QLabel#TimelineControlLabel {
                color: #aebbb5;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 900;
                padding: 0;
            }
            QSpinBox#GlobalBpmSpin {
                background: #18191b;
                border: 1px solid #414746;
                border-radius: ${CONTROL_RADIUS}px;
                color: #e1e6df;
                font-weight: 900;
                min-height: 26px;
                max-height: 26px;
                padding: 0 5px;
            }
            QToolButton#ReferenceBpmFollow {
                font-size: ${TYPE_CAPTION}px;
                font-weight: 600;
                min-height: 26px;
                max-height: 26px;
                padding: 0 5px;
            }
            QLabel#TimelineControlLabel {
                color: #a78e6a;
                font-size: ${TYPE_CAPTION}px;
            }
            QLabel#EnsembleMetric[ensembleState="over"] {
                color: #ef8178;
            }
            QWidget#TranscriptionEditorPanel,
            QWidget#TranscriptionWaveformLane {
                background: #111313;
                border: 0;
            }
            QFrame#TranscriptionAnalysisBar, QFrame#TranscriptionReviewBar,
            QFrame#TranscriptionReviewMoreBar {
                background: #1d1f1f;
                border: 0;
                border-bottom: 1px solid #383733;
                border-radius: 0;
            }
            QFrame#TranscriptionAdvancedPanel {
                background: #151717;
                border: 0;
                border-bottom: 1px solid #383733;
                border-radius: 0;
            }
            QFrame#TranscriptionTuningToolsBar,
            QFrame#TranscriptionCandidateToolsBar,
            QFrame#TranscriptionGuideToolsBar,
            QFrame#TranscriptionAlignmentToolsBar,
            QFrame#TranscriptionDiagnosticLayersBar {
                background: #1a1c1c;
                border: 1px solid #2d302f;
                border-radius: ${GROUP_RADIUS}px;
            }
            QFrame#TranscriptionDiagnosticLayersBar {
                background: transparent;
                border: 0;
                border-top: 1px solid #30312f;
                border-radius: 0;
            }
            QFrame#TranscriptionReviewBar {
                background: #171919;
                border-top: 1px solid #383733;
                border-bottom: 0;
            }
            QFrame#TranscriptionReviewDisplayGroup,
            QFrame#TranscriptionReviewActionGroup,
            QFrame#TranscriptionReviewCommitGroup {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#TranscriptionReviewMoreBar {
                background: #181a1a;
                border-top: 0;
                border-bottom: 1px solid #383733;
            }
            QLabel#TranscriptionWorkspaceTitle {
                background: transparent;
                border: 0;
                border-right: 1px solid #4d4639;
                border-radius: 0;
                color: #d8c298;
                font-weight: 700;
                padding: 2px 12px 2px 4px;
            }
            QLabel#TranscriptionReviewContext {
                background: transparent;
                border: 0;
                border-right: 1px solid #4d4639;
                border-radius: 0;
                color: #e0c996;
                font-weight: 700;
                padding: 2px 12px 2px 4px;
            }
            QFrame#TranscriptionReviewBar QLabel#Muted {
                color: #a5aaa5;
                padding: 2px 6px;
            }
            QLabel#TranscriptionGroupLabel {
                background: transparent;
                border: 0;
                border-right: 1px solid #4d4639;
                border-radius: 0;
                color: #bda97f;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 700;
                padding: 1px 8px 1px 2px;
            }
            QFrame#TranscriptionPopupSection {
                background: #1b1d1d;
                border: 1px solid #343635;
                border-radius: ${PANEL_RADIUS}px;
            }
            QLabel#TranscriptionPopupSectionTitle {
                background: transparent;
                border: 0;
                color: #dfc894;
                font-weight: 700;
                padding: 0 0 2px 0;
            }
            QLabel#TranscriptionPopupFieldLabel {
                background: transparent;
                border: 0;
                color: #b9b7b1;
                padding: 0;
            }
            QLabel#TranscriptionPopupDescription {
                background: transparent;
                border: 0;
                color: #929892;
                padding: 0 1px 2px 1px;
            }
            QFrame#TranscriptionAnalysisBar QPushButton,
            QFrame#TranscriptionAdvancedPanel QPushButton,
            QFrame#TranscriptionAdvancedPanel QToolButton,
            QFrame#TranscriptionReviewBar QPushButton,
            QFrame#TranscriptionReviewBar QToolButton,
            QFrame#TranscriptionReviewMoreBar QPushButton,
            QFrame#TranscriptionReviewMoreBar QToolButton {
                min-height: 27px;
                padding: 2px 9px;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QFrame#TranscriptionReviewBar QComboBox {
                min-height: 27px;
                padding: 1px 7px;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QToolButton#TranscriptionCandidateLayerButton:checked {
                background: #263332;
                border-color: #c9963b;
                color: #dcebe7;
            }
            QToolButton#TranscriptionCandidateLayerButton:!checked {
                color: #8f938f;
            }
            QToolButton#TranscriptionPitchGuideButton:checked,
            QToolButton#TranscriptionPitchOnlyButton:checked {
                background: #203447;
                border-color: #529dda;
                color: #d9efff;
            }
            QToolButton#TranscriptionPitchGuideButton:!checked,
            QToolButton#TranscriptionPitchOnlyButton:!checked {
                color: #9aabb7;
            }
            QFrame#EditorToolbar {
                background: $WINDOW_SHELL;
                border: 0;
                border-bottom: 1px solid $SEPARATOR;
                border-radius: 0;
            }
            QFrame#EditorToolbar QPushButton {
                min-height: 22px;
                padding: 3px 8px;
            }
            QLabel#EditorTrackTitle {
                color: $TEXT;
                font-size: ${TYPE_DOCUMENT}px;
                font-weight: 600;
            }
            QLabel#EditorTrackMeta {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_CAPTION}px;
            }
            QFrame#EditorTransport {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#EditorWorkspace {
                background: $CANVAS;
                border: 0;
                border-radius: 0;
            }
            QFrame#EditorBody {
                background: $CANVAS;
                border: 0;
            }
            QFrame#EditorToolRail {
                background: $PANEL;
                border: 0;
                border-right: 1px solid $SEPARATOR;
            }
            QFrame#EditorPropertiesBar {
                background: $WINDOW_SHELL;
                border: 0;
                border-top: 1px solid $SEPARATOR;
            }
            QLabel#EditorNoteFieldLabel {
                color: $SECONDARY_TEXT; font-size: ${TYPE_SECONDARY}px;
            }
            QPushButton#EditorToolButton {
                min-height: ${TOOL_BUTTON_CONTENT_HEIGHT}px; padding: 2px;
            }
            QFrame#EditorShortcutHud {
                background: rgba(11, 12, 14, 88);
                border: 1px solid rgba(206, 188, 157, 36);
                border-radius: ${GROUP_RADIUS}px;
            }
            QLabel#ShortcutHudMode {
                background: transparent;
                border: 0;
                border-bottom: 1px solid rgba(206, 188, 157, 38);
                border-radius: 0;
                color: rgba(220, 196, 151, 180);
                font-size: ${TYPE_CAPTION}px;
                font-weight: 700;
                padding: 0 0 4px 1px;
            }
            QFrame#EditorShortcutHud[hudMode="draw"] QLabel#ShortcutHudMode {
                color: rgba(185, 205, 153, 185);
            }
            QFrame#ShortcutHudRow {
                background: transparent;
                border: 0;
            }
            QLabel#ShortcutHudKey {
                background: rgba(206, 188, 157, 18);
                border: 1px solid rgba(206, 188, 157, 32);
                border-radius: ${SMALL_CONTROL_RADIUS}px;
                color: rgba(228, 210, 178, 188);
                font-size: ${TYPE_CAPTION}px;
                font-weight: 600;
                padding: 1px 5px;
            }
            QLabel#ShortcutHudAction {
                background: transparent;
                border: 0;
                color: rgba(216, 210, 201, 174);
                font-size: ${TYPE_CAPTION}px;
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] {
                background: rgba(11, 12, 14, 54);
                border-color: rgba(160, 151, 136, 24);
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudMode,
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudAction {
                color: rgba(174, 169, 160, 118);
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudKey {
                background: rgba(150, 145, 136, 10);
                border-color: rgba(150, 145, 136, 20);
                color: rgba(190, 183, 171, 126);
            }
            QDialog#EditorShortcutHelpDialog {
                background: $WINDOW_SHELL;
                border: 1px solid $WINDOW_OUTLINE;
                border-radius: ${PANEL_RADIUS}px;
            }
            QLabel#ShortcutHelpIcon {
                color: $ACCENT;
                background: $CONTROL;
                border: 1px solid $SEPARATOR;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QLabel#ShortcutHelpTitle {
                color: $TEXT;
                font-size: ${TYPE_DIALOG_HEADING}px;
                font-weight: 700;
            }
            QLabel#ShortcutHelpScopeNote {
                color: $SECONDARY_TEXT;
            }
            QLineEdit#ShortcutHelpSearch {
                min-height: 30px;
                padding: 0 9px;
            }
            QScrollArea#ShortcutHelpScroll,
            QWidget#ShortcutHelpContent {
                background: transparent;
                border: 0;
            }
            QFrame#ShortcutHelpGroup {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${PANEL_RADIUS}px;
            }
            QLabel#ShortcutHelpGroupTitle {
                color: $TEXT;
                font-size: ${TYPE_BODY}px;
                font-weight: 700;
                padding-bottom: 4px;
            }
            QLabel#ShortcutHelpKey {
                background: $CONTROL;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
                padding: 1px 6px;
                color: $TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 600;
            }
            QLabel#ShortcutHelpAction {
                color: $SECONDARY_TEXT;
            }
            QFrame#VelocityHeader {
                background: $PANEL;
                border: none;
                min-height: 32px;
                max-height: 32px;
            }
            QFrame#VelocityPanel {
                background: $PANEL;
                border: 0;
            }
            QLabel#VelocityTitle {
                color: $SECONDARY_TEXT;
                font-weight: 600;
                padding-right: 4px;
            }
            QPushButton#VelocityModeButton {
                background: transparent; border-color: transparent; color: $SECONDARY_TEXT;
                min-height: 20px;
                max-height: 20px;
                min-width: 48px;
                padding: 2px 8px;
            }
            QPushButton#VelocityModeButton:hover { background: $CONTROL_HOVER; color: $TEXT; }
            QPushButton#VelocityModeButton:checked { background: $SELECTION; color: $TEXT; }
            QPushButton#VelocityModeButton:focus { border-color: $FOCUS; }
            QComboBox#VelocityRadiusCombo, QComboBox#VelocityScopeCombo {
                min-height: 22px;
                max-height: 22px;
                min-width: 104px;
                padding: 1px 24px 1px 7px;
            }
            QFrame#NoteInspectorTop {
                background: $PANEL;
                border: none;
            }
            QFrame#NoteInspectorTop QPushButton,
            QFrame#NoteInspectorTop QToolButton {
                min-height: 16px;
                max-height: 16px;
                padding: 4px 8px;
            }
            QLabel#InspectorSelection {
                background: transparent;
                border: 0;
                border-radius: 0;
                color: $SECONDARY_TEXT;
                padding: 2px 4px;
            }
            QFrame#NoteInspectorTop QLineEdit,
            QFrame#NoteInspectorTop QComboBox {
                min-height: 18px;
                padding: 3px 6px;
            }
            QComboBox#ArticulationCombo {
                border-color: $CONTROL_BORDER;
                color: $TEXT;
                font-weight: 600;
                min-height: 18px;
                max-height: 18px;
                padding: 4px 8px;
            }
            QPushButton#ArticulationPreview {
                min-height: 26px;
                max-height: 26px;
                padding: 0;
            }
            QLabel#EditorTime {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_SECONDARY}px;
            }
            QFrame#EditorFooter {
                background: $PANEL;
                border: 0;
                border-top: 1px solid $SEPARATOR;
                border-radius: 0;
                max-height: 31px;
            }
            QWidget#EditorToolbarInset,
            QWidget#EditorInspectorInset,
            QWidget#EditorFooterInset {
                background: $CANVAS;
                border: 0;
            }
            QDialog#MidiNoteEditorDialog QFrame#EditorToolbar,
            QDialog#MidiNoteEditorDialog QFrame#EditorTransport,
            QDialog#MidiNoteEditorDialog QFrame#EditorWorkspace,
            QDialog#MidiNoteEditorDialog QFrame#NoteInspectorTop,
            QDialog#MidiNoteEditorDialog QFrame#EditorFooter,
            QDialog#MidiNoteEditorDialog QLabel#InspectorSelection,
            QDialog#MidiNoteEditorDialog QWidget#EditorPropertiesBar {
                border-radius: 0;
            }
            QSplitter#EditorRollSplitter::handle:vertical { height: 5px; background: $SEPARATOR; }
            QSplitter#EditorRollSplitter::handle:vertical:hover { background: $CONTROL_BORDER; }
            QWidget#PianoScrollCorner { background: $CANVAS; }
            QDialog#MidiNoteEditorDialog QAbstractSpinBox {
                min-height: 20px;
                max-height: 20px;
                padding: 2px 6px;
            }
            QLabel#PanelTitle {
                color: $TEXT;
                font-size: ${TYPE_DOCUMENT}px;
                font-weight: 700;
            }
            QDialog#MultiplayerSyncDialog {
                background: $CANVAS;
                color: $TEXT;
            }
            QDialog#MultiplayerSyncDialog QFrame#RoomSummaryCard,
            QDialog#MultiplayerSyncDialog QFrame#RoomConnectionCard,
            QDialog#MultiplayerSyncDialog QFrame#RoomProtocolCard,
            QDialog#ConversionCheckDialog QWidget#WorkflowDialogHeader,
            QDialog#MidiOptimizeDialog QFrame#OptimizerOptions,
            QDialog#CreationAssistantDialog QFrame#CreationSettings,
            QDialog#CreationAssistantDialog QFrame#CreationReview,
            QFrame#SelfUpdateStatusCard {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${PANEL_RADIUS}px;
            }
            QDialog#MultiplayerSyncDialog QLabel#RoomMetricLabel {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 700;
            }
            QDialog#MultiplayerSyncDialog QLabel#RoomMetricValue {
                color: $TEXT;
                font-size: ${TYPE_BODY}px;
                font-weight: 700;
            }
            QDialog#MultiplayerSyncDialog QLabel#RoomStateValue {
                color: $TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 700;
            }
            QDialog#MultiplayerSyncDialog QLabel#RoomNetworkQuality {
                color: $SUCCESS_TEXT;
                font-size: ${TYPE_CAPTION}px;
                font-weight: 800;
            }
            QLabel#SectionLabel {
                color: $TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 700;
                padding-top: 2px;
            }
            QDialog#ConversionCheckDialog QTextEdit,
            QDialog#ConversionCheckDialog QListWidget,
            QDialog#MultiplayerSyncDialog QListWidget#NetworkRoomMembers,
            QDialog#MidiOptimizeDialog QTextEdit#OptimizerReport,
            QFrame#ThanksTextPanel QTextBrowser#ThanksText,
            QDialog#SelfUpdateDialog QTextBrowser#SelfUpdateNotes {
                background: $PANEL;
                color: $TEXT;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QDialog#ConversionCheckDialog QTextEdit:focus,
            QDialog#ConversionCheckDialog QListWidget:focus,
            QDialog#MultiplayerSyncDialog QListWidget#NetworkRoomMembers:focus,
            QDialog#MidiOptimizeDialog QTextEdit#OptimizerReport:focus,
            QFrame#ThanksTextPanel QTextBrowser#ThanksText:focus,
            QDialog#SelfUpdateDialog QTextBrowser#SelfUpdateNotes:focus {
                border-color: $FOCUS;
            }
            QLabel#OptimizerSummary, QLabel#OptimizerScopeSummary {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 600;
                padding: 2px 0;
            }
            QFrame#OptimizerOptions QCheckBox {
                min-width: 150px;
            }
            QFrame#TrackTitleCard {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QFrame#TrackTitleCard QLabel#TrackTitle {
                color: $TEXT;
                font-size: ${TYPE_DIALOG_HEADING}px;
                font-weight: 700;
            }
            QDialog#TrackPitchDialog QDialogButtonBox,
            QDialog#ClipVelocityBaseDialog QDialogButtonBox,
            QDialog#ConversionCheckDialog QDialogButtonBox {
                border-top: 1px solid $SEPARATOR;
                padding-top: 9px;
            }
            QTextEdit#OptimizerReport {
                padding: 7px;
                font-family: Consolas, "Microsoft YaHei UI";
                font-size: ${TYPE_CAPTION}px;
            }
            QLabel#Muted { color: $SECONDARY_TEXT; }
            QDialog#FeedbackDialog {
                background: $CANVAS;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${PANEL_RADIUS}px;
            }
            QDialog#FeedbackDialog QFrame#FeedbackPanelHeader {
                border-top-left-radius: ${PANEL_INNER_RADIUS}px;
                border-top-right-radius: ${PANEL_INNER_RADIUS}px;
            }
            QDialog#FeedbackDialog QFrame#FeedbackReadingFooter {
                background: transparent;
                border: 0;
                border-bottom-right-radius: ${PANEL_INNER_RADIUS}px;
            }
            QFrame#FeedbackMailRail {
                background: $PANEL;
                border: 0;
                border-right: 1px solid $SEPARATOR;
                border-bottom-left-radius: ${PANEL_INNER_RADIUS}px;
            }
            QFrame#FeedbackMailRailActions {
                background: transparent;
                border: 0;
            }
            QPushButton#FeedbackMailCompose, QPushButton#FeedbackMailLookup {
                color: $SECONDARY_TEXT;
                text-align: left;
                border: 1px solid transparent;
                border-radius: ${CONTROL_RADIUS}px;
                padding: 3px 8px;
            }
            QPushButton#FeedbackMailCompose:hover, QPushButton#FeedbackMailLookup:hover {
                background: $CONTROL_HOVER;
                color: $TEXT;
            }
            QPushButton#FeedbackMailCompose:checked, QPushButton#FeedbackMailLookup:checked {
                background: $SELECTION;
                color: $SELECTION_TEXT;
            }
            QPushButton#FeedbackMailCompose:focus, QPushButton#FeedbackMailLookup:focus {
                border-color: $FOCUS;
            }
            QListWidget#FeedbackMailbox {
                background: transparent;
                border: 0;
                padding: 0 4px;
                outline: 0;
            }
            QListWidget#FeedbackMailbox::item {
                color: $SECONDARY_TEXT;
                background: transparent;
                border: 1px solid transparent;
                border-radius: ${CONTROL_RADIUS}px;
            }
            QListWidget#FeedbackMailbox::item:hover {
                color: $TEXT;
                background: $CONTROL_HOVER;
            }
            QListWidget#FeedbackMailbox::item:selected {
                color: $SELECTION_TEXT;
                background: $SELECTION;
            }
            QListWidget#FeedbackMailbox::item:focus { border-color: $INDICATOR_BORDER; }
            QFrame#FeedbackComposePage, QFrame#FeedbackReadPage, QStackedWidget#FeedbackMailStack {
                background: transparent;
                border: 0;
            }
            QLabel#FeedbackMailboxEmpty, QLabel#FeedbackReadStatus,
            QLabel#FeedbackMailNotice { color: $SECONDARY_TEXT; }
            QLabel#FeedbackMailboxTitle {
                color: $SECONDARY_TEXT;
                font-size: ${TYPE_SECONDARY}px;
                font-weight: 600;
            }
            QLabel#FeedbackReadHeading {
                color: $TEXT;
                font-size: ${TYPE_DOCUMENT}px;
                font-weight: 700;
            }
            QFrame#FeedbackLookupBar { background: transparent; border: 0; }
            QPushButton#FeedbackSend, QPushButton#FeedbackLookupSubmit, QPushButton#FeedbackCopyCode {
                min-height: ${BUTTON_CONTENT_HEIGHT}px;
                padding: 5px 12px;
                border: 1px solid $CONTROL_BORDER;
                border-radius: ${CONTROL_RADIUS}px;
                background: $CONTROL;
                color: $TEXT;
            }
            QPushButton#FeedbackCopyCode {
                background: transparent;
                border-color: transparent;
                color: $SECONDARY_TEXT;
            }
            QPushButton#FeedbackLookupSubmit:hover, QPushButton#FeedbackCopyCode:hover {
                background: $CONTROL_HOVER;
                color: $TEXT;
            }
            QPushButton#FeedbackLookupSubmit:focus, QPushButton#FeedbackCopyCode:focus {
                border-color: $FOCUS;
            }
            QPushButton#FeedbackSend {
                background: $ACCENT;
                border-color: $ACCENT;
                color: $ACCENT_TEXT;
                font-weight: 600;
                min-width: 84px;
            }
            QPushButton#FeedbackSend:hover { background: $ACCENT_HOVER; }
            QPushButton#FeedbackSend:focus { border-color: $ACCENT_TEXT; }
            QPushButton#FeedbackSend:disabled, QPushButton#FeedbackLookupSubmit:disabled {
                background: $PANEL;
                border-color: $SEPARATOR;
                color: $DISABLED_TEXT;
            }
            QPlainTextEdit#FeedbackReadText {
                background: transparent;
                border: 1px solid transparent;
                border-radius: ${CONTROL_RADIUS}px;
                padding: 4px 0;
                font-size: ${TYPE_DOCUMENT}px;
            }
            QPlainTextEdit#FeedbackComposeText {
                background: $PANEL;
                border: 1px solid transparent;
                border-radius: ${CONTROL_RADIUS}px;
                padding: 10px 12px;
                placeholder-text-color: $SECONDARY_TEXT;
                font-size: ${TYPE_DOCUMENT}px;
            }
            QPlainTextEdit#FeedbackAttachmentPreview {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${CONTROL_RADIUS}px;
                padding: 6px 8px;
            }
            QPlainTextEdit#FeedbackComposeText:focus,
            QPlainTextEdit#FeedbackAttachmentPreview:focus,
            QPlainTextEdit#FeedbackReadText:focus { border-color: $SELECTION_BORDER; }
            QLabel#SelfUpdateStatusBadge {
                color: $SELECTION_TEXT;
                background: $SELECTION;
                border: 1px solid $SELECTION_BORDER;
                border-radius: ${CONTROL_RADIUS}px;
                padding: 3px 8px;
                font-weight: 700;
            }
            QLabel#SelfUpdateStatusSummary { color: $SECONDARY_TEXT; }
            QDialog#SelfUpdateDialog QProgressBar#SelfUpdateProgress {
                background: $CONTROL;
                border: 1px solid $SEPARATOR;
                border-radius: 3px;
            }
            QDialog#SelfUpdateDialog QProgressBar#SelfUpdateProgress::chunk {
                background: $ACCENT;
                border-radius: 2px;
            }
            QFrame#ReleaseNotesBody {
                background: #151515;
                border: 0;
            }
            QComboBox#ReleaseVersionSelector {
                min-height: 26px;
                padding: 2px 8px;
            }
            QFrame#UpdateStatusCard {
                background: transparent;
                border: 0;
                border-bottom: 1px solid #3d3932;
            }
            QLabel#UpdateStatusTitle {
                color: #aaa39a;
                font-weight: 700;
            }
            QLabel#UpdateStatusTitle[updateState="available"] {
                color: #f0c66f;
            }
            QLabel#UpdateStatusTitle[updateState="ok"] {
                color: #bcd5b5;
            }
            QLabel#UpdateStatusTitle[updateState="error"] {
                color: #ddd7cf;
            }
            QLabel#ReleaseVersionTitle {
                color: #f0c66f;
                font-size: ${TYPE_DIALOG_HEADING}px;
                font-weight: 900;
            }
            QLabel#ReleaseDate, QLabel#ReleaseSummary {
                color: #aaa39a;
            }
            QTextBrowser#ReleaseHighlights {
                background: transparent;
                border: 0;
                border-radius: 0;
                color: #d8d3cc;
                padding: 4px 0 0 0;
            }
            QLabel#CheckCard {
                background: $PANEL;
                border: 1px solid $SEPARATOR;
                border-radius: ${CONTROL_RADIUS}px;
                color: $TEXT;
                padding: 8px 10px;
                font-weight: 700;
            }
            QListWidget {
                background: #191919;
                border: 1px solid #3a3834;
                border-radius: ${CONTROL_RADIUS}px;
                color: #ddd7cf;
                outline: 0;
                padding: 4px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2c2b29;
                padding: 8px 7px;
            }
            QListWidget::item:selected {
                background: #4a391f;
                color: #fff3d6;
            }
            QDialog QListWidget::item {
                border: 1px solid transparent;
                border-bottom-color: $SEPARATOR;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QDialog QListWidget::item:hover { background: $CONTROL_HOVER; }
            QDialog QListWidget::item:selected {
                background: $SELECTION;
                color: $SELECTION_TEXT;
                border-color: $SELECTION_BORDER;
            }
            QDialog QListWidget::item:focus { border-color: $FOCUS; }
            QScrollArea {
                border: 0;
                background: transparent;
            }
            QWidget#PianoScrollCorner {
                background: #171918;
            }
            QScrollBar:vertical {
                background: #1b1b1b;
                width: 12px;
                margin: 1px;
                border: 0;
                border-left: 1px solid #2c2b29;
            }
            QScrollBar:horizontal {
                background: #1b1b1b;
                height: 12px;
                margin: 1px;
                border: 0;
                border-top: 1px solid #2c2b29;
            }
            QScrollBar::handle:vertical {
                background: #4a4640;
                min-height: 32px;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
                margin: 2px 1px;
            }
            QScrollBar::handle:horizontal {
                background: #4a4640;
                min-width: 32px;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
                margin: 1px 2px;
            }
            QScrollBar::handle:vertical:hover,
            QScrollBar::handle:horizontal:hover {
                background: #766b5e;
            }
            QScrollBar::handle:vertical:pressed,
            QScrollBar::handle:horizontal:pressed {
                background: #b27b25;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QAbstractScrollArea::corner { background: #1b1b1b; }
            QScrollBar#TimelineScroll:vertical {
                background: #171918;
                border-left-color: #292c2a;
            }
            QScrollBar#PianoPitchScroll:vertical {
                background: $CANVAS;
                border-left-color: $SEPARATOR;
            }
            QScrollBar#PianoTimeScroll:horizontal {
                background: $CANVAS;
                border-top-color: $SEPARATOR;
            }
            QScrollBar#TimelineScroll::handle:vertical { background: #626660; }
            QScrollBar#PianoPitchScroll::handle:vertical,
            QScrollBar#PianoTimeScroll::handle:horizontal {
                background: $CONTROL_BORDER;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
            }
            QScrollBar#TimelineScroll::handle:vertical:hover { background: #8b806f; }
            QScrollBar#PianoPitchScroll::handle:vertical:hover,
            QScrollBar#PianoTimeScroll::handle:horizontal:hover {
                background: $INDICATOR_BORDER;
            }
            QScrollBar#TimelineScroll::handle:vertical:pressed,
            QScrollBar#PianoPitchScroll::handle:vertical:pressed,
            QScrollBar#PianoTimeScroll::handle:horizontal:pressed {
                background: #c58a2d;
            }
            QSlider {
                background: transparent;
                border: 0;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: $CONTROL_BORDER;
                border-radius: ${SLIDER_TRACK_RADIUS}px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 16px;
                margin: -6px 0;
                border-radius: ${SMALL_CONTROL_RADIUS}px;
                background: $ACCENT;
            }
            QSlider[editorDisplayControl="true"]::handle:horizontal {
                background: $SELECTION_INDICATOR;
                border: 1px solid transparent;
            }
            QSlider[editorDisplayControl="true"]::handle:horizontal:focus {
                border-color: $FOCUS;
            }
            """).substitute(vars(hig))
        dark = self._system_uses_dark_theme()
        self.setStyleSheet(build_fluent_stylesheet(style_sheet + HIG_QSS, dark))
        refresh_fluent_icons(self, dark)
