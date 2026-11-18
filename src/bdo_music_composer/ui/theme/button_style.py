"""Application-level button roles and interaction states."""

from string import Template

from . import hig_tokens as hig


BUTTON_QSS = Template("""
QPushButton, QToolButton {
    background: $CONTROL; color: $TEXT; border: 1px solid $CONTROL_BORDER;
    border-radius: ${CONTROL_RADIUS}px; min-height: ${BUTTON_CONTENT_HEIGHT}px;
    padding: 5px 10px;
}
QPushButton[kind="secondary"], QToolButton[kind="secondary"] { background: $PANEL; }
QPushButton[kind="ghost"], QToolButton[kind="ghost"] {
    background: transparent; border-color: $SEPARATOR;
}
QPushButton[kind="primary"] {
    background: $SELECTION; color: $SELECTION_TEXT; border-color: $SELECTION_BORDER;
    font-weight: 600;
}
QPushButton[kind="accent-outline"] {
    background: transparent; color: $SELECTION_TEXT; font-weight: 600;
}
QMessageBox QPushButton:default, QInputDialog QPushButton:default,
QPushButton[kind="convert"] {
    background: $ACCENT; color: $ACCENT_TEXT; border-color: $ACCENT; font-weight: 600;
}
QPushButton[kind="convert"] { min-width: 96px; }
QPushButton:hover, QPushButton[kind]:hover, QToolButton:hover, QToolButton[kind]:hover {
    background: $CONTROL_HOVER; border-color: $SELECTION_BORDER;
}
QPushButton[kind="primary"]:hover, QPushButton[kind="accent-outline"]:hover {
    background: $SELECTION_HOVER; border-color: $SELECTION_BORDER;
}
QMessageBox QPushButton:default:hover, QInputDialog QPushButton:default:hover,
QPushButton[kind="convert"]:hover {
    background: $ACCENT_HOVER; border-color: $ACCENT_HOVER;
}
QPushButton:pressed, QPushButton[kind]:pressed, QToolButton:pressed, QToolButton[kind]:pressed {
    background: $CONTROL_PRESSED; border-color: $SELECTION_BORDER;
}
QMessageBox QPushButton:default:pressed, QInputDialog QPushButton:default:pressed,
QPushButton[kind="convert"]:pressed {
    background: $ACCENT_PRESSED; border-color: $ACCENT_PRESSED;
}
QPushButton:checked, QPushButton[kind]:checked, QToolButton:checked, QToolButton[kind]:checked {
    background: $SELECTION; color: $SELECTION_TEXT; border-color: $SELECTION_BORDER;
}
QPushButton:checked:hover, QPushButton[kind]:checked:hover,
QToolButton:checked:hover, QToolButton[kind]:checked:hover {
    background: $SELECTION_HOVER;
}
QPushButton:checked:pressed, QPushButton[kind]:checked:pressed,
QToolButton:checked:pressed, QToolButton[kind]:checked:pressed {
    background: $CONTROL_PRESSED;
}
QPushButton:focus, QPushButton[kind]:focus, QToolButton:focus,
QToolButton[kind]:focus { border-color: $FOCUS; }
QMessageBox QPushButton:default:focus, QInputDialog QPushButton:default:focus,
QPushButton[kind="convert"]:focus { border-color: $ACCENT_TEXT; }
QPushButton:disabled, QPushButton[kind]:disabled, QPushButton[kind]:checked:disabled,
QToolButton:disabled, QToolButton[kind]:disabled, QToolButton[kind]:checked:disabled,
QMessageBox QPushButton:disabled, QInputDialog QPushButton:disabled {
    background: $PANEL; color: $DISABLED_TEXT; border-color: $SEPARATOR;
}
QPushButton[kind="ghost"]:disabled, QPushButton[kind="ghost"]:checked:disabled,
QToolButton[kind="ghost"]:disabled, QToolButton[kind="ghost"]:checked:disabled {
    background: transparent;
}
""").substitute(vars(hig))
