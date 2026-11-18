"""Accessible controls shared by the effect dialogs."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDial,
    QFrame,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bdo_music_composer.ui.theme import hig_tokens as hig


class GameEffectDial(QDial):
    """An effect dial that pairs a visible input value with direct adjustment."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GameEffectDial")
        self.setRange(0, 100)
        self.setNotchesVisible(False)
        self.setWrapping(False)
        self.setTracking(True)
        self.setFixedSize(112, 112)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        painter.translate((self.width() - side) / 2, (self.height() - side) / 2)
        painter.scale(side / 112.0, side / 112.0)
        center = QPointF(56.0, 56.0)
        radius = 49.0
        enabled = self.isEnabled()

        face_radius = radius - 7.0
        painter.setPen(QPen(QColor(hig.SEPARATOR), 1.0))
        painter.setBrush(QColor(hig.PANEL))
        painter.drawEllipse(center, face_radius, face_radius)

        arc_rect = QRectF(
            center.x() - face_radius + 4.0,
            center.y() - face_radius + 4.0,
            (face_radius - 4.0) * 2.0,
            (face_radius - 4.0) * 2.0,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(hig.CONTROL_BORDER), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc_rect, 225 * 16, -270 * 16)

        ratio = (self.value() - self.minimum()) / max(
            1,
            self.maximum() - self.minimum(),
        )
        if ratio > 0.0:
            active = QColor(hig.ACCENT if enabled else hig.INDICATOR_BORDER)
            painter.setPen(QPen(active, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, 225 * 16, int(-270.0 * ratio * 16.0))

        for tick in range(11):
            tick_ratio = tick / 10.0
            angle = math.radians(135.0 + 270.0 * tick_ratio)
            outer = face_radius - 8.0
            inner = outer - (5.0 if tick in (0, 5, 10) else 3.0)
            color = QColor(hig.SECONDARY_TEXT if tick_ratio <= ratio and enabled else hig.CONTROL_BORDER)
            painter.setPen(QPen(color, 1.2))
            painter.drawLine(
                QPointF(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner),
                QPointF(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer),
            )

        angle = math.radians(135.0 + 270.0 * ratio)
        painter.setPen(QPen(QColor("#f3eee4") if enabled else QColor("#77736d"), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            QPointF(center.x() + math.cos(angle) * 9.0, center.y() + math.sin(angle) * 9.0),
            QPointF(center.x() + math.cos(angle) * (face_radius - 13.0), center.y() + math.sin(angle) * (face_radius - 13.0)),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d8b66b") if enabled else QColor("#68645d"))
        painter.drawEllipse(center, 3.0, 3.0)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(hig.FOCUS), 1.25))
            painter.drawEllipse(center, radius + 3.0, radius + 3.0)


class EffectControlCard(QFrame):
    """An effect rack slot backed by a numeric spin box."""

    def __init__(
        self,
        title: str,
        field: QSpinBox,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EffectControlCard")
        self.setProperty("uiRole", "effectControlCard")
        self.setMinimumWidth(132)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 11, 10, 12)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        label = QLabel(title)
        label.setObjectName("EffectControlTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.title_label = label

        self.dial = GameEffectDial(self)
        self.dial.setRange(field.minimum(), field.maximum())
        self.dial.setValue(field.value())
        self.dial.setEnabled(field.isEnabled())
        self.dial.setAccessibleName(field.accessibleName() or title)
        self.dial.setToolTip(field.toolTip())
        self.dial.valueChanged.connect(field.setValue)
        field.valueChanged.connect(self.dial.setValue)
        layout.addWidget(self.dial, alignment=Qt.AlignmentFlag.AlignHCenter)

        field.setParent(self)
        field.setProperty("uiRole", "effectValue")
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setFixedSize(88, 32)
        layout.addWidget(field, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.field = field

        scale = QLabel("0     100")
        scale.setObjectName("EffectControlScale")
        scale.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scale.setProperty("i18nSkip", True)
        layout.addWidget(scale)
        self.scale_label = scale

    def use_compact_layout(self) -> None:
        """Keep the same dial/field binding in a narrow inspector row."""
        layout = self.layout()
        while layout.count():
            layout.takeAt(0)
        layout.setDirection(QVBoxLayout.Direction.LeftToRight)
        layout.setContentsMargins(8, 8, 10, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.dial.setFixedSize(72, 72)
        layout.addWidget(self.dial)
        column = QVBoxLayout()
        column.setSpacing(6)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(self.title_label)
        self.field.setMinimumWidth(0)
        self.field.setMaximumWidth(16777215)
        self.field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.field.setAccessibleName(self.dial.accessibleName())
        self.field.lineEdit().setAccessibleName(self.dial.accessibleName())
        column.addWidget(self.field)
        layout.addLayout(column, 1)
        self.scale_label.hide()


class EffectModeCard(QFrame):
    """A special source-mode slot that belongs visually to the effect rack."""

    def __init__(
        self,
        title: str,
        selector: QComboBox,
        note: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EffectModeCard")
        self.setProperty("uiRole", "effectModeCard")
        self.setMinimumWidth(230)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 11, 10, 12)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        label = QLabel(title)
        label.setObjectName("EffectControlTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)

        emblem_stage = QWidget(self)
        emblem_stage.setObjectName("EffectModeStage")
        emblem_stage.setFixedSize(112, 112)
        emblem_layout = QVBoxLayout(emblem_stage)
        emblem_layout.setContentsMargins(0, 0, 0, 0)
        emblem_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        emblem = QLabel("M")
        emblem.setObjectName("EffectModeEmblem")
        emblem.setProperty("i18nSkip", True)
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emblem.setFixedSize(92, 92)
        emblem_layout.addWidget(emblem)
        layout.addWidget(emblem_stage, alignment=Qt.AlignmentFlag.AlignHCenter)

        selector.setParent(self)
        selector.setObjectName("MarnianModeSelector")
        selector.setProperty("uiRole", "effectModeSelector")
        selector.setAccessibleName(title)
        selector.setAccessibleDescription(note)
        selector.setMinimumWidth(208)
        selector.setFixedHeight(32)
        layout.addWidget(selector)

        hint = QLabel(note)
        hint.setObjectName("EffectModeNote")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def use_compact_layout(self) -> None:
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout().setContentsMargins(10, 10, 10, 10)
        self.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        self.findChild(QWidget, "EffectModeStage").hide()
        self.findChild(QLabel, "EffectModeNote").hide()
        title = self.findChild(QLabel, "EffectControlTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setWordWrap(True)
        selector = self.findChild(QComboBox, "MarnianModeSelector")
        selector.setMinimumWidth(0)
        selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)


__all__ = ["EffectControlCard", "EffectModeCard", "GameEffectDial"]
