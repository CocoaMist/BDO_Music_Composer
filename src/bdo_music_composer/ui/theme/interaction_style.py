"""Application-level surfaces for prompts, native form dialogs, and feedback."""

from string import Template

from . import hig_tokens as hig


INTERACTION_THEME_MARKER = "bdo-interaction-theme-v1"

INTERACTION_QSS = Template("""
/* bdo-interaction-theme-v1 */
QMessageBox, QInputDialog {
    background: $PANEL; color: $TEXT;
}
QMessageBox QLabel, QInputDialog QLabel {
    color: $TEXT; font-size: ${TYPE_BODY}px;
}
QMessageBox QLabel#qt_msgbox_label {
    font-size: ${TYPE_DOCUMENT}px; font-weight: 600;
}
QMessageBox QLabel#qt_msgbox_informativelabel { color: $SECONDARY_TEXT; }
QInputDialog QLineEdit, QInputDialog QComboBox, QInputDialog QAbstractSpinBox,
QInputDialog QListView,
QMessageBox QTextEdit {
    background: $CONTROL; color: $TEXT; border: 1px solid $CONTROL_BORDER;
    border-radius: ${CONTROL_RADIUS}px; padding: 5px 8px;
    selection-background-color: $SELECTION; selection-color: $SELECTION_TEXT;
}
QInputDialog QLineEdit:focus, QInputDialog QComboBox:focus,
QInputDialog QAbstractSpinBox:focus, QInputDialog QListView:focus { border-color: $FOCUS; }
QInputDialog QAbstractSpinBox > QLineEdit { background: transparent; border: 0; padding: 0; }
QMessageBox QPushButton, QInputDialog QPushButton,
QFrame#PromptActions QPushButton { min-width: 72px; }
QFrame#PromptSurface {
    background: $PANEL; border: 1px solid $WINDOW_OUTLINE;
    border-radius: ${PANEL_RADIUS}px;
}
QFrame#PromptCaption, QFrame#PromptActions { background: transparent; border: 0; }
QFrame#PromptCaption { border-bottom: 1px solid $SEPARATOR; }
QLabel#PromptTitle { color: $TEXT; font-size: ${TYPE_DOCUMENT}px; font-weight: 600; }
QTextEdit#PromptText { background: transparent; border: 0; padding: 0; }
QPushButton#PromptClose {
    background: transparent; color: $SECONDARY_TEXT; border: 1px solid transparent;
    border-radius: ${CONTROL_RADIUS}px; padding: 0; min-height: 0;
    font-size: ${TYPE_DOCUMENT}px;
}
QPushButton#PromptClose:hover { background: $CONTROL_HOVER; color: $ERROR_TEXT; }
QPushButton#PromptClose:focus { border-color: $FOCUS; }
QFrame#GlobalToast {
    background: $PANEL; border: 1px solid $WINDOW_OUTLINE;
    border-radius: ${GROUP_RADIUS}px;
}
QLabel#ToastMessage, QLabel#ToastMarker { background: transparent; border: 0; }
QLabel#ToastMessage { color: $TEXT; font-size: ${TYPE_BODY}px; }
QLabel#ToastMarker {
    background: $CONTROL; color: $SECONDARY_TEXT;
    border-radius: ${SMALL_CONTROL_RADIUS}px;
    font-size: ${TYPE_BODY}px; font-weight: 700;
}
QFrame#GlobalToast[toastKind="success"] QLabel#ToastMarker { color: $SUCCESS_TEXT; }
QFrame#GlobalToast[toastKind="warning"] QLabel#ToastMarker { color: $ACCENT; }
QFrame#GlobalToast[toastKind="error"] QLabel#ToastMarker { color: $ERROR_TEXT; }
""").substitute(vars(hig))


PROMPT_OPTIONS_QSS = Template("""
QListWidget#PromptOptions {
    background: $CANVAS; border: 1px solid $CONTROL_BORDER;
    border-radius: ${GROUP_RADIUS}px; padding: ${GROUP_CONTENT_MARGIN}px; outline: 0;
    show-decoration-selected: 1;
}
QListWidget#PromptOptions:focus { border-color: $SECONDARY_TEXT; }
QListWidget#PromptOptions::item {
    color: $TEXT; border: 1px solid transparent; border-radius: ${CONTROL_RADIUS}px;
    min-height: 30px; margin: 1px 0; padding: 1px 8px;
}
QListWidget#PromptOptions::item:hover { background: $CONTROL_HOVER; }
QListWidget#PromptOptions::item:selected {
    color: $SELECTION_TEXT; background: $SELECTION; border-color: $SELECTION_BORDER;
}
QListWidget#PromptOptions::item:focus { border-color: $FOCUS; }
QListWidget#PromptOptions QScrollBar:vertical { width: 8px; background: transparent; }
QListWidget#PromptOptions QScrollBar::handle:vertical {
    min-height: 28px; background: $CONTROL_BORDER; border-radius: ${SMALL_CONTROL_RADIUS}px;
}
QListWidget#PromptOptions QScrollBar::add-line:vertical,
QListWidget#PromptOptions QScrollBar::sub-line:vertical { height: 0; }
QListWidget#PromptOptions QScrollBar::add-page:vertical,
QListWidget#PromptOptions QScrollBar::sub-page:vertical { background: transparent; }
""").substitute(vars(hig))
