"""HIG surfaces for the home page, editor workbench, and settings."""

from string import Template

from . import hig_tokens as hig


HIG_QSS = Template("""
QWidget#Root, QStackedWidget#MainPages, QWidget#WorkspacePage, QWidget#HomePage,
QWidget#ComposerWorkbench {
    background: $CANVAS; color: $TEXT;
}
QFrame#Toolbar { background: $WINDOW_SHELL; border: none; }
QFrame#WorkbenchCommandBar {
    background: $WINDOW_SHELL; border: none; border-bottom: 1px solid $SEPARATOR;
}
QFrame#Toolbar QFrame#ToolbarNavigation,
QFrame#Toolbar QFrame#ToolbarPlaybackGroup,
QFrame#Toolbar QFrame#TransportGroup,
QFrame#Toolbar QFrame#GlobalBpmControl,
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteTransport,
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteGrid,
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteView,
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteActions,
QFrame#WorkbenchEditorBar QFrame#EditorQuantizeQuick {
    background: transparent; border: none;
}
QFrame#Toolbar QFrame#WindowChrome {
    background: transparent; border: 0; border-left: 1px solid $SEPARATOR;
}
QFrame#Toolbar QFrame#DocumentTitleGroup {
    background: transparent; border: 0; border-left: 1px solid $SEPARATOR;
}
QFrame#WorkbenchCommandBar QFrame#CommandGroup,
QFrame#WorkbenchHistoryControls, QFrame#WorkbenchPanelControls {
    background: transparent; border: none; border-left: 1px solid $SEPARATOR;
}
QFrame#HomeCommandDeck { background: transparent; border: none; }

/* Caption focus belongs to the glyph or the active input, inside stable geometry. */
QFrame#Toolbar QAbstractButton {
    background: transparent; border: 1px solid transparent;
    border-radius: ${CONTROL_RADIUS}px;
    border-left-width: 2px;
}
QFrame#Toolbar QAbstractButton:checked {
    background: transparent; border-color: transparent; color: $TEXT;
}
QFrame#Toolbar QAbstractButton:hover,
QFrame#Toolbar QAbstractButton:checked:hover {
    background: $CONTROL_HOVER;
}
QFrame#Toolbar QAbstractButton:pressed,
QFrame#Toolbar QAbstractButton:checked:pressed {
    background: $CONTROL_PRESSED;
}
QFrame#Toolbar QAbstractButton:disabled {
    background: transparent; color: $DISABLED_TEXT; border-color: transparent;
}
QFrame#Toolbar QAbstractButton:focus,
QFrame#Toolbar QAbstractButton:checked:focus {
    border-color: transparent;
}
QFrame#Toolbar QPushButton#ToolbarExport {
    background: rgba(243, 190, 94, 15); color: $ACCENT;
    border: 1px solid rgba(243, 190, 94, 72);
    padding: 2px 11px; font-weight: 500;
}
QFrame#Toolbar QPushButton#ToolbarExport:enabled:hover {
    background: rgba(243, 190, 94, 27); border-color: rgba(243, 190, 94, 116);
}
QFrame#Toolbar QPushButton#ToolbarExport:enabled:pressed {
    background: rgba(243, 190, 94, 39); border-color: rgba(243, 190, 94, 134);
}
QFrame#Toolbar QPushButton#ToolbarExport:enabled:focus { border-color: $FOCUS; }
QFrame#Toolbar QPushButton#ToolbarExport:disabled {
    background: $PANEL; color: $DISABLED_TEXT; border-color: $SEPARATOR;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"] {
    background: transparent; border: 1px solid transparent;
    border-radius: ${CONTROL_RADIUS}px;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:hover {
    background: $CONTROL_HOVER;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:checked {
    background: $TOOL_SELECTED_GLASS; color: $SELECTION_TEXT;
    border-color: $TOOL_SELECTED_EDGE;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:checked:hover {
    background: $TOOL_SELECTED_GLASS_HOVER;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:pressed,
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:checked:pressed {
    background: $CONTROL_PRESSED;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:disabled,
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:checked:disabled {
    background: transparent; color: $DISABLED_TEXT; border-color: transparent;
}
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:focus,
QFrame[noteCommandSurface="true"] QPushButton[kind="ghost"]:checked:focus {
    border-color: $FOCUS;
}
QFrame#Toolbar QFrame#WindowChrome QPushButton {
    color: $SECONDARY_TEXT; padding: 0;
    min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px;
    font-size: ${TYPE_DOCUMENT}px;
}
QFrame#Toolbar QFrame#WindowChrome QPushButton:hover { color: $TEXT; }
QFrame#Toolbar QFrame#WindowChrome QPushButton#WindowChromeClose:enabled:hover {
    background: rgba(255, 147, 138, 36);
}
QFrame#Toolbar QFrame#WindowChrome QPushButton#WindowChromeClose:enabled:pressed {
    background: rgba(255, 147, 138, 58);
}
QFrame#HomeShell,
QFrame#HomeOverlay, QFrame#HomeLibraryBar,
QWidget#HomeHero, QStackedWidget#HomeLibraryStack, QFrame#HomeCard {
    background: transparent; border: none;
}
QFrame#Toolbar QLineEdit#DocumentTitle,
QFrame#Toolbar QSpinBox#GlobalBpmSpin {
    background: transparent; border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
}
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo {
    background: transparent; border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
    color: $TEXT; font-weight: 600; padding: 0 4px 0 8px;
}
QFrame#Toolbar QLineEdit#DocumentTitle:hover,
QFrame#Toolbar QSpinBox#GlobalBpmSpin:hover {
    background: $CONTROL_HOVER; border-color: transparent;
}
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo:hover {
    background: $CONTROL_HOVER; border-color: transparent;
}
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo:on {
    background: $TOOL_SELECTED_GLASS; border-color: $TOOL_SELECTED_EDGE;
}
QFrame#Toolbar QLineEdit#DocumentTitle:focus {
    border-color: transparent;
}
QFrame#Toolbar QSpinBox#GlobalBpmSpin:focus { border-color: $FOCUS; }
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo:focus,
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo:on:focus {
    border-color: $FOCUS;
}
QFrame[noteCommandSurface="true"] QComboBox#QuantizeGridCombo:disabled {
    background: transparent; border-color: transparent; color: $DISABLED_TEXT;
}
QFrame#Toolbar QLineEdit#DocumentTitle {
    color: $TEXT; min-height: 20px; max-height: 20px; padding: 0 4px;
    font-size: ${TYPE_DOCUMENT}px; font-weight: 600;
}
QFrame#Toolbar QSpinBox#GlobalBpmSpin {
    padding: 0 0 0 7px;
    font-size: ${TYPE_BODY}px;
    font-weight: 600;
}
QFrame#Toolbar QSpinBox#GlobalBpmSpin::up-button {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 21px; height: 13px; border: none; border-top-right-radius: 4px;
    background: transparent;
}
QFrame#Toolbar QSpinBox#GlobalBpmSpin::down-button {
    subcontrol-origin: padding; subcontrol-position: bottom right;
    width: 21px; height: 13px; border: none; border-bottom-right-radius: 4px;
    background: transparent;
}
QFrame#Toolbar QSpinBox#GlobalBpmSpin::up-button:hover,
QFrame#Toolbar QSpinBox#GlobalBpmSpin::down-button:hover { background: $CONTROL_HOVER; }
QFrame#Toolbar QSpinBox#GlobalBpmSpin::up-button:pressed,
QFrame#Toolbar QSpinBox#GlobalBpmSpin::down-button:pressed { background: $CONTROL_PRESSED; }
QFrame#Toolbar QSpinBox#GlobalBpmSpin::up-arrow,
QFrame#Toolbar QSpinBox#GlobalBpmSpin::down-arrow { image: none; width: 0; height: 0; }
QFrame#Toolbar QSpinBox#GlobalBpmSpin:disabled {
    color: $DISABLED_TEXT;
}
QFrame#Toolbar QToolButton#ReferenceBpmFollow { padding: 0; }
QFrame#Toolbar QLabel#ToolbarText {
    color: $SECONDARY_TEXT; padding: 0 5px; font-size: ${TYPE_CAPTION}px;
}
QFrame#Toolbar QPushButton#EnsembleCapacityBadge {
    border-width: 1px; padding: 0; text-align: center;
    min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px;
}
QFrame#WorkbenchCommandBar QFrame#CommandGroup QPushButton[kind="ghost"],
QFrame#WorkbenchHistoryControls QPushButton[kind="ghost"],
QFrame#WorkbenchPanelControls QPushButton[kind="ghost"],
QFrame#WorkbenchCommandBar QPushButton#WorkbenchCommandMenu,
QFrame#WorkbenchCommandBar QPushButton#WorkbenchNewTrack {
    border-color: transparent;
}
QFrame#WorkbenchCommandBar QFrame#CommandGroup QPushButton[kind="ghost"]:enabled:checked,
QFrame#WorkbenchPanelControls QPushButton[kind="ghost"]:enabled:checked,
QFrame#EditorToolRail QPushButton#EditorToolButton:enabled:checked {
    background: $TOOL_SELECTED_GLASS; color: $SELECTION_TEXT;
    border-color: $TOOL_SELECTED_EDGE;
}
QFrame#WorkbenchCommandBar QFrame#CommandGroup QPushButton[kind="ghost"]:enabled:checked:hover,
QFrame#WorkbenchPanelControls QPushButton[kind="ghost"]:enabled:checked:hover,
QFrame#EditorToolRail QPushButton#EditorToolButton:enabled:checked:hover {
    background: $TOOL_SELECTED_GLASS_HOVER;
}
QFrame#WorkbenchCommandBar QFrame#CommandGroup QPushButton[kind="ghost"]:enabled:checked:pressed,
QFrame#WorkbenchPanelControls QPushButton[kind="ghost"]:enabled:checked:pressed,
QFrame#EditorToolRail QPushButton#EditorToolButton:enabled:checked:pressed {
    background: $CONTROL_PRESSED;
}
QFrame#WorkbenchCommandBar QPushButton:enabled:focus,
QFrame#WorkbenchCommandBar QFrame#CommandGroup QPushButton[kind="ghost"]:enabled:focus,
QFrame#WorkbenchHistoryControls QPushButton[kind="ghost"]:enabled:focus,
QFrame#WorkbenchPanelControls QPushButton[kind="ghost"]:enabled:focus,
QFrame#EditorToolRail QPushButton#EditorToolButton:enabled:focus {
    border-color: $INDICATOR_BORDER;
}
QFrame#Toolbar QPushButton[kind], QFrame#WorkbenchCommandBar QPushButton,
QFrame#WorkbenchEditorBar QPushButton[kind] {
    min-height: ${TOOL_BUTTON_CONTENT_HEIGHT}px; padding: 2px 8px;
}
QPushButton#TimelineReferenceLoad {
    background: $PANEL; border: 1px solid $CONTROL_BORDER;
    color: $TEXT; border-radius: ${CONTROL_RADIUS}px;
    padding: 2px 11px; text-align: left; min-height: ${TOOL_BUTTON_CONTENT_HEIGHT}px;
}
QPushButton#TimelineReferenceLoad[referenceMissing="true"] {
    border-color: #615540;
}
QPushButton#TimelineReferenceLoad:enabled:hover {
    background: $CONTROL_HOVER; border-color: $SELECTION_BORDER;
}
QPushButton#TimelineReferenceLoad:enabled:pressed {
    background: $CONTROL_PRESSED; border-color: $SELECTION_BORDER;
}
QPushButton#TimelineReferenceLoad:enabled:focus { border-color: $FOCUS; }
QPushButton#TimelineReferenceLoad:disabled {
    background: $PANEL; color: $DISABLED_TEXT; border-color: $SEPARATOR;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[kind] {
    border-width: 1px; padding: 2px 5px; text-align: left;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[captionIconOnly="true"] {
    text-align: center;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton#ToolbarProject[captionIconOnly="true"] {
    text-align: left;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton::menu-indicator {
    subcontrol-origin: padding; subcontrol-position: right center;
    right: 2px; width: 10px;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton#ToolbarProject[captionIconOnly="true"]::menu-indicator {
    right: 0;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[kind]:enabled:hover,
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[kind]:enabled:checked:hover {
    background: $CONTROL_HOVER;
}
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[kind]:enabled:pressed,
QFrame#Toolbar QFrame#ToolbarNavigation QPushButton[kind]:enabled:checked:pressed {
    background: $CONTROL_PRESSED;
}
QFrame#WorkbenchCommandBar QPushButton#TimelineToolButton,
QFrame#WorkbenchHistoryControls QPushButton,
QFrame#Toolbar QPushButton#ToolbarMore,
QFrame#Toolbar QFrame#TransportGroup QPushButton {
    min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px; padding: 0;
}
QFrame#Toolbar QFrame#TransportGroup QPushButton#TransportLoopButton {
    border-width: 1px;
}
QFrame#Toolbar QFrame#TransportGroup QPushButton#TransportLoopButton:enabled:checked {
    background: rgba(243, 190, 94, 24); border-color: rgba(243, 190, 94, 68);
}
QFrame#Toolbar QFrame#TransportGroup QPushButton#TransportLoopButton:enabled:checked:hover {
    background: rgba(243, 190, 94, 36);
}
QFrame#Toolbar QFrame#TransportGroup QPushButton#TransportLoopButton:enabled:checked:pressed {
    background: rgba(243, 190, 94, 48);
}
QFrame#Toolbar QPushButton#ToolbarMore { font-size: ${TYPE_DIALOG_HEADING}px; }
QFrame#Toolbar QPushButton#ToolbarMore::menu-indicator { image: none; width: 0; }
QFrame#Toolbar QLabel#TimelineControlLabel,
QFrame#TimelineViewPopup QLabel#TimelineControlLabel { color: $SECONDARY_TEXT; }
QLabel#TimelineMeta { color: $SECONDARY_TEXT; padding: 0 5px; }

QFrame#HomeLibrarySurface, QFrame#HomeLibraryTabs {
    background: transparent; border: none;
}
QFrame#HomeLibraryBar {
    background: transparent; border: none; border-bottom: 1px solid $SEPARATOR;
}
QLabel#HomeTitle { color: $TEXT; font-size: ${TYPE_HOME_HEADING}px; font-weight: 400; }
QLabel#HomeHeroSubtitle { color: $SECONDARY_TEXT; font-size: ${TYPE_DOCUMENT}px; }
QLabel#HomeLocalBadge { color: $SECONDARY_TEXT; font-size: ${TYPE_CAPTION}px; }
QWidget#HomeFooter {
    background: transparent; border: 0;
}
QFrame#HomeCardHeader {
    background: transparent; border: 0; min-height: ${BUTTON_HEIGHT}px;
}
QLabel#HomeCount { color: $SECONDARY_TEXT; font-size: ${TYPE_SECONDARY}px; }
QLabel#HomeDownloadNotice { color: $ERROR_TEXT; font-size: ${TYPE_SECONDARY}px; }
QLabel#HomeEmptyState {
    background: transparent; color: $SECONDARY_TEXT; border: none;
    font-size: ${TYPE_SECONDARY}px;
}
QWidget#HomePage QPushButton#HomeQuickAction {
    padding: 0 14px; text-align: left; font-weight: 600;
    min-height: ${PAGE_ACTION_CONTENT_HEIGHT}px;
}
QWidget#HomePage QPushButton#HomeQuickAction[kind="ghost"] {
    background: $PANEL; border-color: transparent; color: $TEXT;
}
QWidget#HomePage QPushButton#HomeQuickAction[kind="ghost"]:hover { background: $CONTROL; }
QWidget#HomePage QPushButton#HomeQuickAction[kind="ghost"]:pressed { background: $CONTROL_PRESSED; }
QWidget#HomePage QPushButton#HomeQuickAction[kind="ghost"]:focus {
    border-color: $INDICATOR_BORDER;
}
QPushButton#HomeNavButton {
    border-color: transparent; min-height: ${SEGMENT_CONTENT_HEIGHT}px;
    color: $SECONDARY_TEXT; font-weight: 600; padding: 0 10px;
}
QPushButton#HomeNavButton[kind="ghost"]:checked {
    background: $SELECTION; color: $SELECTION_TEXT;
}
QPushButton#HomeNavButton[kind="ghost"]:checked:hover { background: $SELECTION_HOVER; }
QPushButton#HomeNavButton[kind="ghost"]:focus,
QPushButton#HomeNavButton[kind="ghost"]:checked:focus { border-color: $INDICATOR_BORDER; }
QLineEdit#HomeSearch {
    padding: 0 10px; min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px;
    background: $PANEL; border-color: $SEPARATOR;
}
QLineEdit#HomeSearch:hover { border-color: $CONTROL_BORDER; }
QLineEdit#HomeSearch:focus { border-color: $INDICATOR_BORDER; }
QPushButton#HomeRefreshButton, QPushButton#HomeLibraryAction { border-color: transparent; }
QPushButton#HomeRefreshButton { padding: 0; min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px; }
QPushButton#HomeRefreshButton:focus, QPushButton#HomeLibraryAction:focus {
    border-color: $INDICATOR_BORDER;
}
QListWidget#HomeList { background: transparent; border: 0; padding: 0; outline: 0; }
QListWidget#HomeList::item {
    background: transparent; border: 1px solid transparent;
    border-bottom-color: $SEPARATOR; padding: 0;
}
QListWidget#HomeList::item:hover {
    background: $PANEL; border-radius: ${CONTROL_RADIUS}px;
}
QListWidget#HomeList::item:selected {
    background: $SELECTION; border-bottom-color: $SEPARATOR;
    border-radius: ${CONTROL_RADIUS}px;
}
QListWidget#HomeList::item:selected:hover { background: $SELECTION_HOVER; }
QListWidget#HomeList::item:focus, QListWidget#HomeList::item:selected:focus {
    border-color: $INDICATOR_BORDER; border-radius: ${CONTROL_RADIUS}px;
}
QListWidget#HomeList QScrollBar:vertical { width: 8px; background: transparent; }
QListWidget#HomeList QScrollBar::handle:vertical {
    min-height: 28px; background: $CONTROL_BORDER; border-radius: ${SMALL_CONTROL_RADIUS}px;
}
QListWidget#HomeList QScrollBar::add-line:vertical,
QListWidget#HomeList QScrollBar::sub-line:vertical { height: 0; }
QPushButton#HomeReleaseNotesButton { padding: 0 4px; }

QTabWidget#WorkbenchInspectorTabs QTabBar { qproperty-drawBase: 0; }
QTabWidget#WorkbenchInspectorTabs QTabBar::tab {
    color: $SECONDARY_TEXT; background: transparent;
    border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
    margin: 2px 3px 7px; padding: 4px 11px; min-height: 18px;
}
QTabWidget#WorkbenchInspectorTabs QTabBar::tab:first { margin-left: ${PANEL_PADDING}px; }
QTabWidget#WorkbenchInspectorTabs QTabBar::tab:hover {
    background: $CONTROL_HOVER; color: $TEXT;
}
QTabWidget#WorkbenchInspectorTabs QTabBar::tab:selected {
    color: $SELECTION_TEXT; background: $SELECTION; border-color: $CONTROL_BORDER;
}
QTabWidget#WorkbenchInspectorTabs QTabBar::tab:focus {
    border-color: $FOCUS;
}
QTabWidget#WorkbenchInspectorTabs QTabBar::tab:disabled { color: $DISABLED_TEXT; }
QDialog#AboutDialog {
    background: $PANEL; color: $TEXT;
    border: 1px solid $CONTROL_BORDER; border-radius: ${PANEL_RADIUS}px;
}
QScrollArea#AboutAuthorsScroll, QWidget#AboutAuthorsBody,
QDialog#AboutDialog QFrame#ThanksTextPanel {
    background: transparent; color: $TEXT; border: none;
}
QTabWidget#AboutTabs::pane { border: none; }
QTabWidget#AboutTabs QTabBar { qproperty-drawBase: 0; }
QTabWidget#AboutTabs QTabBar::tab {
    background: transparent; color: $SECONDARY_TEXT;
    border: 1px solid transparent; border-bottom-width: 2px;
    margin-right: 12px; padding: 4px 5px; min-height: 24px;
}
QTabWidget#AboutTabs QTabBar::tab:first { margin-left: ${SECTION_GAP}px; }
QTabWidget#AboutTabs QTabBar::tab:hover { color: $TEXT; }
QTabWidget#AboutTabs QTabBar::tab:selected {
    color: $TEXT; border-bottom-color: $SELECTION_INDICATOR;
}
QTabWidget#AboutTabs QTabBar::tab:focus { border-color: $FOCUS; }
QTabWidget#AboutTabs QTabBar::tab:selected:focus { border-bottom-color: $SELECTION_INDICATOR; }
QLabel#AboutTitle { color: $TEXT; font-size: ${TYPE_DIALOG_HEADING}px; font-weight: 600; }
QLabel#AboutAuthorName { color: $TEXT; font-size: ${TYPE_HOME_HEADING}px; font-weight: 600; }
QLabel#AboutProfilePortrait { background: transparent; }
QLabel#AboutProfileName {
    color: $TEXT; font-size: ${TYPE_DOCUMENT}px; font-weight: 600;
}
QLabel#AboutProfileSummary { color: $TEXT; }
QLabel#AboutProfileRole { color: $SECONDARY_TEXT; font-size: ${TYPE_SECONDARY}px; }
QLabel#AboutModelMark {
    background: $SELECTION; color: $SELECTION_TEXT;
    border-radius: 18px; font-size: ${TYPE_DOCUMENT}px; font-weight: 600;
}
QDialog#AboutDialog QFrame#ThanksTextPanel QTextBrowser#ThanksText {
    background: transparent; border: 1px solid transparent;
}
QDialog#AboutDialog QFrame#ThanksTextPanel QTextBrowser#ThanksText:focus {
    border: 1px solid $FOCUS;
}
QDialog#AboutDialog QLineEdit#ThanksSearch {
    background: $CONTROL; border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
}
QDialog#AboutDialog QLineEdit#ThanksSearch:focus { border-color: $FOCUS; }
QDialog#AboutDialog QPushButton#AboutCopyCredits, QDialog#AboutDialog QPushButton#ThanksFindNext {
    background: transparent; border: 1px solid transparent;
}
QDialog#AboutDialog QPushButton#AboutCopyCredits:hover, QDialog#AboutDialog QPushButton#ThanksFindNext:enabled:hover {
    background: $CONTROL;
}
QDialog#AboutDialog QPushButton#AboutCopyCredits:focus, QDialog#AboutDialog QPushButton#ThanksFindNext:focus {
    border-color: $FOCUS;
}

QFrame#WorkbenchEditorBar {
    background: $WINDOW_SHELL; border: none; border-top: 1px solid $SEPARATOR;
}
QFrame#WorkbenchInspectorActions,
QDialog[workbenchEmbedded="true"] QFrame#EditorFooter {
    background: $PANEL; border: none; border-top: 1px solid $SEPARATOR;
}
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteGrid,
QFrame#WorkbenchEditorBar QFrame#WorkbenchNoteActions {
    border-left: 1px solid $SEPARATOR;
}
QFrame#WorkbenchEditorBar QPushButton#VelocityToggle {
    padding-left: 5px; padding-right: 5px;
}
QFrame#WorkbenchEditorBar QPushButton[kind="convert"] { min-width: 48px; }
QStackedWidget#WorkbenchSidePane {
    background: $PANEL; border: 1px solid $CONTROL_BORDER;
    border-radius: ${PANEL_RADIUS}px;
}
QFrame#WorkbenchInspector {
    background: transparent; border: none;
}
QFrame#WorkbenchInspector QScrollArea, QFrame#WorkbenchInspector QStackedWidget,
QFrame#WorkbenchInspector QScrollArea > QWidget > QWidget,
QFrame#WorkbenchInspector QFrame#EffectDialogBody,
QFrame#WorkbenchInspector QFrame#EffectRack {
    background: transparent; border: none;
}
QFrame#WorkbenchInspectorHeader, QWidget#ScoreAgentActions {
    background: transparent; border: none; border-bottom: 1px solid $SEPARATOR;
}
QPushButton#WorkbenchInspectorClose {
    padding: 0; min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px;
    background: transparent; border-color: transparent;
}
QPushButton#WorkbenchInspectorClose:enabled:hover { background: $CONTROL_HOVER; }
QPushButton#WorkbenchInspectorClose:enabled:pressed { background: $CONTROL_PRESSED; }
QPushButton#WorkbenchInspectorClose:focus { border-color: $FOCUS; }
QLabel#WorkbenchTrackTitle { color: $TEXT; font-size: ${TYPE_DOCUMENT}px; font-weight: 600; }
QLabel#WorkbenchMuted { color: $SECONDARY_TEXT; background: transparent; }
QLabel#WorkbenchInspectorCount {
    background: $CONTROL; color: $SECONDARY_TEXT;
    padding: 3px 8px; border-radius: ${CONTROL_RADIUS}px;
    font-size: ${TYPE_SECONDARY}px;
}
QLabel#WorkbenchInspectorEmptyIcon {
    background: $CONTROL; border: 1px solid $SEPARATOR; border-radius: ${GROUP_RADIUS}px;
}
QLabel#WorkbenchPanelMessageTitle { color: $TEXT; font-size: ${TYPE_DIALOG_HEADING}px; font-weight: 600; }
QLabel#WorkbenchPanelMessageBody { color: $SECONDARY_TEXT; background: transparent; }
QFrame#WorkbenchInspector QLabel#ToolbarSelectionVelocityTitle {
    color: $TEXT; font-size: ${TYPE_BODY}px; font-weight: 600;
}
QFrame#WorkbenchInspector QLabel#ToolbarSelectionVelocityScope {
    color: $SECONDARY_TEXT; font-size: ${TYPE_SECONDARY}px;
}
QFrame#WorkbenchInspector QFrame#ToolbarSelectionVelocityGroup {
    background: $WINDOW_SHELL; border: 1px solid $SEPARATOR; border-radius: ${GROUP_RADIUS}px;
}
QComboBox#WorkbenchInspectorInstrument, QSpinBox#WorkbenchInspectorStep {
    background: $CONTROL; color: $TEXT; border: 1px solid $CONTROL_BORDER;
    border-radius: ${CONTROL_RADIUS}px; padding: 0 8px; min-height: 30px;
}
QComboBox#WorkbenchInspectorInstrument:hover, QSpinBox#WorkbenchInspectorStep:hover { border-color: $SELECTION_BORDER; }
QComboBox#WorkbenchInspectorInstrument:focus, QSpinBox#WorkbenchInspectorStep:focus { border-color: $FOCUS; }
QSpinBox#WorkbenchInspectorStep:disabled { color: $DISABLED_TEXT; border-color: $SEPARATOR; }
QSpinBox#WorkbenchInspectorStep::up-button, QSpinBox#WorkbenchInspectorStep::down-button {
    subcontrol-origin: border; width: 25px; height: 15px;
    border: none; background: transparent;
}
QSpinBox#WorkbenchInspectorStep::up-button { subcontrol-position: top right; border-top-right-radius: ${CONTROL_RADIUS}px; }
QSpinBox#WorkbenchInspectorStep::down-button { subcontrol-position: bottom right; border-bottom-right-radius: ${CONTROL_RADIUS}px; }
QSpinBox#WorkbenchInspectorStep::up-button:hover, QSpinBox#WorkbenchInspectorStep::down-button:hover { background: $CONTROL_HOVER; }
QSpinBox#WorkbenchInspectorStep::up-button:pressed, QSpinBox#WorkbenchInspectorStep::down-button:pressed { background: $CONTROL_PRESSED; }
QSpinBox#WorkbenchInspectorStep::up-arrow, QSpinBox#WorkbenchInspectorStep::down-arrow { image: none; width: 0; height: 0; }
QComboBox#WorkbenchInspectorInstrument QAbstractItemView::item:selected {
    background: $SELECTION; color: $SELECTION_TEXT;
}
QTabWidget#WorkbenchInspectorTabs::pane { border: none; border-top: 1px solid $SEPARATOR; }
QFrame#ScoreAgentPanel { background: transparent; border: none; }
QWidget#ScoreAgentActions QPushButton, QFrame#ScoreAgentComposer QPushButton[kind="ghost"] {
    background: transparent; border: 1px solid transparent;
}
QWidget#ScoreAgentActions QPushButton:enabled:hover,
QFrame#ScoreAgentComposer QPushButton[kind="ghost"]:enabled:hover { background: $CONTROL_HOVER; }
QWidget#ScoreAgentActions QPushButton:enabled:pressed,
QFrame#ScoreAgentComposer QPushButton[kind="ghost"]:enabled:pressed { background: $CONTROL_PRESSED; }
QWidget#ScoreAgentActions QPushButton:focus,
QFrame#ScoreAgentComposer QPushButton[kind="ghost"]:focus { border-color: $INDICATOR_BORDER; }
QStackedWidget#ScoreAgentReading, QTextEdit#ScoreAgentTranscript {
    color: $TEXT; background: transparent; border: none;
}
QTextEdit#ScoreAgentTranscript { padding: 10px 3px 4px; border-left: 1px solid transparent; }
QTextEdit#ScoreAgentTranscript:focus { border-left-color: $FOCUS; }
QPushButton#ScoreAgentStarter {
    color: $TEXT; background: $CONTROL; border: 1px solid $SEPARATOR;
    border-radius: ${CONTROL_RADIUS}px; padding: 3px 9px; font-size: ${TYPE_SECONDARY}px;
}
QPushButton#ScoreAgentStarter:enabled:hover { color: $TEXT; background: $CONTROL_HOVER; }
QPushButton#ScoreAgentStarter:enabled:pressed { background: $CONTROL_PRESSED; }
QPushButton#ScoreAgentStarter:focus { border-color: $FOCUS; }
QPushButton#ScoreAgentStarter:disabled { color: $DISABLED_TEXT; }
QFrame#ScoreAgentComposer {
    background: $WINDOW_SHELL;
    border: 1px solid $CONTROL_BORDER;
    border-radius: ${PANEL_RADIUS}px;
}
QFrame#ScoreAgentComposer[promptFocused="true"] { border-color: $INDICATOR_BORDER; }
QFrame#ScoreAgentContext {
    background: transparent; border: none;
}
QPlainTextEdit#ScoreAgentPrompt {
    color: $TEXT; background: transparent;
    border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px; padding: 2px 3px;
}
QPlainTextEdit#ScoreAgentPrompt:focus { border-color: transparent; }
QLabel#ScoreAgentStatus, QLabel#ScoreAgentDisclosure, QFrame#ScoreAgentContext QLabel#WorkbenchMuted {
    color: $SECONDARY_TEXT; font-size: ${TYPE_SECONDARY}px; background: transparent;
}
QLabel#ScoreAgentStatus { padding: 0 8px; }
QLabel#ScoreAgentDisclosure { padding: 0 4px; }
QPushButton#ScoreAgentModelPicker {
    color: $SECONDARY_TEXT; min-height: 26px; padding: 2px 6px;
    font-size: ${TYPE_SECONDARY}px; border-radius: ${GROUP_RADIUS}px;
}
QPushButton#ScoreAgentModelPicker:enabled:hover { color: $TEXT; }
QLabel#ScoreAgentAudio {
    color: $SECONDARY_TEXT; background: transparent; border: 0;
    padding: 2px 0; font-size: ${TYPE_SECONDARY}px;
}
QPushButton#ScoreAgentLatest {
    border-radius: ${PANEL_RADIUS}px; font-size: ${TYPE_SECONDARY}px; padding: 4px 10px;
}
QPushButton#ScoreAgentSend {
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;
    color: $ACCENT_TEXT; background: $ACCENT; border: 1px solid transparent;
    border-radius: 18px; padding: 0;
}
QPushButton#ScoreAgentSend:enabled:hover { background: $ACCENT_HOVER; }
QPushButton#ScoreAgentSend:enabled:pressed { background: $ACCENT_PRESSED; }
QPushButton#ScoreAgentSend:focus { border-color: $FOCUS; }
QPushButton#ScoreAgentSend:disabled { color: $DISABLED_TEXT; background: $SELECTION; }
QFrame#WorkbenchTrackFields {
    background: $WINDOW_SHELL; border: 1px solid $SEPARATOR; border-radius: ${GROUP_RADIUS}px;
}
QSplitter#WorkbenchVerticalSplitter::handle {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 $CANVAS, stop:0.474 $CANVAS, stop:0.476 $CONTROL_BORDER,
        stop:0.524 $CONTROL_BORDER, stop:0.526 $CANVAS, stop:1 $CANVAS);
    height: 5px;
}
QSplitter#WorkbenchVerticalSplitter::handle:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 $PANEL, stop:0.474 $PANEL, stop:0.476 $ACCENT,
        stop:0.524 $ACCENT, stop:0.526 $PANEL, stop:1 $PANEL);
}
QDialog[workbenchEmbedded="true"], QDialog[workbenchEmbedded="true"] QFrame#EditorBody,
QDialog[workbenchEmbedded="true"] QFrame#EditorWorkspace {
    background: $CANVAS; border: none;
}
QDialog[workbenchEmbedded="true"] QFrame#EditorToolRail {
    background: $PANEL; border: none; border-right: 1px solid $SEPARATOR;
}
QDialog[workbenchEmbedded="true"] QPushButton#EditorToolButton {
    padding: 0; min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px;
}
QFrame#EditorToolRail QPushButton#EditorToolButton:disabled {
    background: transparent; border-color: transparent;
}

QWidget#SettingsContent, QStackedWidget#SettingsPages,
QScrollArea[uiRole="settingsScroll"], QWidget[uiRole="settingsPage"] {
    background: $CANVAS; color: $TEXT; border: none;
}
QWidget#HomeWelcomePage, QScrollArea#HomeWelcomeScroll, QWidget#HomeWelcomeBody {
    background: $CANVAS; color: $TEXT; border: none;
}
QLabel#WelcomeTitle { color: $TEXT; font-size: ${TYPE_HOME_HEADING}px; font-weight: 600; }
QLabel#WelcomeLead, QLabel#WelcomeSection { color: $TEXT; font-size: ${TYPE_DOCUMENT}px; }
QLabel#WelcomeSystemTimeZone { color: $TEXT; font-size: ${TYPE_BODY}px; }
QLabel#WelcomeSection, QLabel#WelcomeBrand, QLabel#WelcomeTimeZoneLabel {
    color: $TEXT; font-weight: 600;
}
QLabel#WelcomeCopy { color: $SECONDARY_TEXT; font-size: ${TYPE_BODY}px; }
QFrame#HomeWelcomeRule { background: $SEPARATOR; border: none; }
QDialog#SettingsDialog {
    background: $PANEL; color: $TEXT; border: 1px solid $CONTROL_BORDER;
    border-radius: ${PANEL_RADIUS}px;
}
QPushButton#FloatingPanelClose {
    min-height: ${ICON_BUTTON_CONTENT_HEIGHT}px; padding: 0;
    background: transparent; border: 1px solid transparent;
    border-radius: ${CONTROL_RADIUS}px;
}
QPushButton#FloatingPanelClose:hover { background: $CONTROL_HOVER; }
QPushButton#FloatingPanelClose:pressed { background: $CONTROL_PRESSED; }
QPushButton#FloatingPanelClose:focus { border-color: $FOCUS; }
QDialog#SettingsDialog QFrame#SettingsHeader {
    background: $PANEL; border: none; border-bottom: 1px solid $SEPARATOR;
    border-top-left-radius: ${PANEL_INNER_RADIUS}px;
    border-top-right-radius: ${PANEL_INNER_RADIUS}px;
}
QDialog#SettingsDialog QFrame#SettingsFooter {
    background: $PANEL; border: none; border-top: 1px solid $SEPARATOR;
    border-bottom-left-radius: ${PANEL_INNER_RADIUS}px;
    border-bottom-right-radius: ${PANEL_INNER_RADIUS}px;
}
QDialog#SettingsDialog QLabel { color: $TEXT; }
QDialog#SettingsDialog QLabel#Muted,
QDialog#SettingsDialog QLabel#SettingsFieldLabel,
QDialog#SettingsDialog QLabel#OwnerStatus { color: $SECONDARY_TEXT; }
QDialog#SettingsDialog QLabel#OwnerStatus[ownerError="true"] { color: $ERROR_TEXT; }
QListWidget#SettingsNav {
    background: $PANEL; border: 0; border-right: 1px solid $SEPARATOR;
    border-radius: 0; padding: 12px 0; outline: 0; show-decoration-selected: 1;
}
QListWidget#SettingsNav::item {
    background: transparent; color: $SECONDARY_TEXT;
    border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
    margin: 3px 8px; padding-left: 9px; font-weight: 600;
}
QListWidget#SettingsNav::item:hover { background: $CONTROL_HOVER; color: $TEXT; }
QListWidget#SettingsNav::item:selected {
    background: $SELECTION; color: $SELECTION_TEXT;
}
QListWidget#SettingsNav::item:focus { border-color: $FOCUS; }
QFrame#SettingsSection {
    background: transparent; border: none;
}
QFrame#SettingsModeRow { background: transparent; border: none; }
QDialog#SettingsDialog QLabel#SettingsUpdateStatus {
    background: transparent; color: $SECONDARY_TEXT; border: none;
}
""").substitute(vars(hig))
