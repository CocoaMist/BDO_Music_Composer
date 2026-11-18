"""Aligned, read-only note and velocity comparison for a staged score change."""

from __future__ import annotations

from collections import Counter
import math
from typing import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bdo_midi import Note
from bdo_music_composer.editor.arrangement_clip import project_track_notes
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig


_NOTES_PER_LAYER = 1200
_MINIMUM_VELOCITY_SCALE = 127
_UNCHANGED_COLOR = "#8d8985"
_ORIGINAL_EDIT_COLOR = "#d0c9bf"

_Event = tuple[int, Note]


def _visible_notes(tracks: Sequence[TrackState], start: float, end: float) -> list[_Event]:
    return sorted(
        ((track.track_id, note) for track in tracks for note in project_track_notes(track)
         if note.start < end and note.start + note.dur > start),
        key=lambda event: (event[1].start, event[1].pitch, event[0]),
    )


def _sample_layer(events: list[_Event]) -> list[_Event]:
    return events[::max(1, math.ceil(len(events) / _NOTES_PER_LAYER))]


class _ComparisonPlot(QWidget):
    """Paint only prepared, bounded snapshot geometry."""

    def __init__(self, change_color: str):
        super().__init__()
        self.setMinimumHeight(112)
        self._change_color = change_color
        self._pitch_step = 0.05
        self._layers = ((), ())
        self._bar_lines = ()

    def set_data(self, events, common, start, end, pitch_bounds, velocity_max, bar_lines):
        retained = common.copy()
        unchanged, changed = [], []
        for event in events:
            if retained[event] > 0:
                unchanged.append(event)
                retained[event] -= 1
            else:
                changed.append(event)
        low, high = pitch_bounds
        span = max(1.0, end - start)
        self._pitch_step = 1.0 / (high - low)
        self._bar_lines = bar_lines
        layers = []
        for layer in (unchanged, changed):
            geometry = []
            for _, note in _sample_layer(layer):
                left = max(start, note.start)
                right = min(end, note.start + note.dur)
                geometry.append((
                    (left - start) / span, (right - left) / span,
                    (high - note.pitch) / (high - low), note.vel / velocity_max,
                ))
            layers.append(tuple(geometry))
        self._layers = tuple(layers)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(hig.CANVAS))
        bounds = QRectF(self.rect()).adjusted(8, 6, -8, -6)
        velocity_height = 21
        velocity_space = 6
        note_height = bounds.height() - velocity_height - velocity_space
        velocity_top = bounds.bottom() - velocity_height
        painter.setPen(QColor(hig.SEPARATOR))
        for fraction in self._bar_lines:
            x = round(bounds.left() + fraction * bounds.width())
            painter.drawLine(x, round(bounds.top()), x, round(bounds.bottom()))
        baseline = round(velocity_top - velocity_space / 2)
        painter.drawLine(round(bounds.left()), baseline, round(bounds.right()), baseline)
        painter.setClipRect(bounds)
        note_size = max(2.0, min(6.0, self._pitch_step * note_height * 0.7))
        for layer, color in zip(self._layers, (_UNCHANGED_COLOR, self._change_color)):
            notes, velocities = QPainterPath(), QPainterPath()
            for left, width, pitch, velocity in layer:
                x = bounds.left() + left * bounds.width()
                y = bounds.top() + pitch * note_height
                notes.addRect(QRectF(x, y - note_size * 0.5, max(2.0, width * bounds.width() - 1.0), note_size))
                height = max(1.0, velocity * velocity_height)
                velocities.addRect(QRectF(x, bounds.bottom() - height, 1.5, height))
            painter.fillPath(notes, QColor(color))
            stem_color = QColor(color)
            stem_color.setAlpha(194)
            painter.fillPath(velocities, stem_color)


class CreationComparison(QWidget):
    """Compare the same time and pitch scales using the form's current part selection."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(hig.GROUP_GAP)
        self._stats = ((), ())
        self._plots = (_ComparisonPlot(_ORIGINAL_EDIT_COLOR), _ComparisonPlot(hig.ACCENT))
        self._titles = []
        self._summaries = []
        for plot in self._plots:
            card = QVBoxLayout()
            card.setSpacing(hig.CONTROL_GAP)
            header = QHBoxLayout()
            title = QLabel()
            title.setProperty("i18nSkipText", True)
            font = title.font()
            font.setBold(True)
            title.setFont(font)
            summary = QLabel()
            summary.setProperty("i18nSkipText", True)
            summary.setObjectName("Muted")
            header.addWidget(title)
            header.addStretch()
            header.addWidget(summary)
            card.addLayout(header)
            card.addWidget(plot)
            layout.addLayout(card)
            self._titles.append(title)
            self._summaries.append(summary)
        self._legend = QLabel()
        self._legend.setObjectName("Muted")
        self._legend.setProperty("i18nSkipText", True)
        self._legend.setWordWrap(True)
        layout.addWidget(self._legend)
        self._update_labels()

    def set_comparison(self, original, selected, start, end, bar_duration):
        before = _visible_notes(original, start, end)
        after = _visible_notes(selected, start, end)
        common = Counter(before) & Counter(after)
        pitches = [event[1].pitch for notes in (before, after) for event in notes]
        bounds = (min(pitches, default=48) - 2, max(pitches, default=84) + 2)
        velocities = [[event[1].vel for event in notes] for notes in (before, after)]
        maximum = max(_MINIMUM_VELOCITY_SCALE, *(max(values, default=0) for values in velocities))
        self._stats = tuple((len(values), min(values), max(values)) if values else () for values in velocities)
        span = max(1.0, end - start)
        stride = math.ceil(span / (bar_duration * 8)) * bar_duration
        first = math.ceil(start / stride) * stride
        bars = tuple((first + index * stride - start) / span for index in range(9)
                     if first + index * stride < end)
        for plot, notes in zip(self._plots, (before, after)):
            plot.set_data(notes, common, start, end, bounds, maximum, bars)
        self._update_labels()

    def _update_labels(self) -> None:
        for title, plot, summary, label, stats in zip(
            self._titles, self._plots, self._summaries, ("原稿", "所选建议"), self._stats,
        ):
            title.setText(tr(label))
            text = tr("无音符")
            if stats:
                count, low, high = stats
                velocity_range = str(low) if low == high else f"{low}–{high}"
                text = trf("{count} 音符 · 力度 {range}", count=count, range=velocity_range)
            summary.setText(text)
            plot.setAccessibleName(f"{title.text()} · {summary.text()}")
        self._legend.setText(tr("琥珀色标出改动，底部短线显示力度。"))
