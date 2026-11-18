"""The note editor's onset-indexed velocity chart and brush."""

from __future__ import annotations

from collections.abc import Iterable
import math

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from bdo_midi import Note
from bdo_music_composer.editor.velocity_curve import velocity_neighbor_weight, velocity_time_points
from bdo_music_composer.ui.i18n import tr, trf
from bdo_music_composer.ui.theme import hig_tokens as hig


_PLOT = "#19191b"
_SCALE = "#202023"
_MEASURE_GUIDE = "#303035"
_LEVEL_GUIDE = "#28282d"
_AXIS_TEXT = "#a3a3aa"


class VelocityLaneCanvas(QWidget):
    """Discrete note-velocity lane with an explicit weighted brush."""

    POINT_DETAIL_MIN_SPACING = 12.0
    PASSIVE_STEM_MIN_SPACING = 4.0

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.editor = editor
        self._chart = QPixmap()
        self._chart_key: tuple[object, ...] | None = None
        self._chart_selection: frozenset[int] = frozenset()
        self._chart_damage = QRectF()
        self.before_notes: list = []
        self.before_selected: set[int] = set()
        self.active_point_time: float | None = None
        self.active_point_velocity = 0.0
        self.active_indices: tuple[int, ...] = ()
        self.active_weights: dict[int, float] = {}
        self.hover_velocity: int | None = None
        self.influence_beats = 2.0
        self.edit_mode = "brush"
        self.scope_mode = "track"
        self.game_velocity_boundaries: tuple[int, ...] = ()
        self.game_velocity_status = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeVerCursor)
        self.setMinimumHeight(104)
        self.setMaximumHeight(144)
        self.setAccessibleName(tr("力度"))
        self.set_game_velocity_boundaries(())

    def set_edit_mode(self, mode: str) -> None:
        self.edit_mode = "point" if mode == "point" else "brush"
        self.update()

    def set_scope_mode(self, mode: str) -> None:
        self.scope_mode = "selection" if mode == "selection" else "track"
        self.update()

    def set_influence_beats(self, beats: float) -> None:
        self.influence_beats = max(0.5, min(8.0, float(beats)))
        self.update()

    def set_game_velocity_boundaries(
        self,
        boundaries: Iterable[int],
        status: str = "",
    ) -> None:
        self.game_velocity_boundaries = tuple(sorted({
            int(value) for value in boundaries if 0 < int(value) < 128
        }))
        self.game_velocity_status = str(status)
        description = "\n".join(filter(None, (
            tr("拖动力度杆；柔化刷按时间距离衰减，滚轮可调整影响范围。"),
            self.game_velocity_status,
            " · ".join(trf("游戏层 {value}", value=value) for value in self.game_velocity_boundaries),
        )))
        self.setToolTip(description)
        self.setAccessibleDescription(description)
        self.update()

    @property
    def influence_radius_ms(self) -> float:
        return max(self.editor.quantize_ms(), self.editor.canvas.beat_ms * self.influence_beats)

    def _velocity_at(self, y: float) -> int:
        usable = max(1.0, self.height() - 10.0)
        return max(0, min(127, round((1.0 - (y - 5.0) / usable) * 127)))

    def _y_for_velocity(self, velocity: float) -> float:
        bounded = max(0.0, min(127.0, float(velocity)))
        return 5.0 + (1.0 - bounded / 127.0) * max(1.0, self.height() - 10.0)

    def _visible_points(
        self, left_x: float, right_x: float,
    ) -> list[tuple[float, tuple[int, ...], float]]:
        canvas = self.editor.canvas
        left_ms = canvas.scroll_ms + (left_x - canvas.KEY_W) / canvas.px_per_ms
        right_ms = canvas.scroll_ms + (right_x - canvas.KEY_W) / canvas.px_per_ms
        return velocity_time_points(
            canvas.notes,
            canvas._note_indices_at_onsets(left_ms - 0.001, right_ms + 0.001),
        )

    def _point_for_index(self, index: int) -> tuple[float, tuple[int, ...], float]:
        canvas = self.editor.canvas
        note = canvas.notes[index]
        onset = round(float(note.start), 3)
        indices = tuple(
            point_index for point_index in sorted(
                canvas._note_indices_at_onsets(onset - 0.001, onset + 0.001)
            )
            if round(float(canvas.notes[point_index].start), 3) == onset
        )
        velocity = sum(float(canvas.notes[item].vel) for item in indices) / len(indices)
        return onset, indices, velocity

    def _bar_rect(self, index: int) -> QRectF:
        """Compatibility hit rectangle; the velocity lane now paints points."""
        onset, _indices, velocity = self._point_for_index(index)
        x = self.editor.canvas.x_at_time(onset)
        y = self._y_for_velocity(velocity)
        return QRectF(x - 6.0, y - 6.0, 12.0, 12.0)

    def _point_at(self, x: float) -> tuple[float, tuple[int, ...], float] | None:
        canvas = self.editor.canvas
        candidates = self._visible_points(max(canvas.KEY_W, x - 9.0), x + 9.0)
        if not candidates:
            return None
        nearest = min(
            candidates,
            key=lambda point: abs(canvas.x_at_time(point[0]) - x),
        )
        if abs(canvas.x_at_time(nearest[0]) - x) > 9.0:
            return None
        return nearest

    def paintEvent(self, _event) -> None:
        self._refresh_chart()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._chart)
        if self.hover_velocity is not None:
            self._paint_hover(painter, self.hover_velocity)

    def _paint_hover(self, painter: QPainter, velocity: int) -> None:
        key_width = self.editor.canvas.KEY_W
        y = self._y_for_velocity(velocity)
        dragging = self.active_point_time is not None
        painter.setPen(QColor(243, 190, 94, 160) if dragging else QColor("#63636b"))
        painter.drawLine(QLineF(key_width, y, self.width(), y))
        badge = self._hover_badge_rect(y)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(hig.ACCENT) if dragging else QColor("#38383e"))
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(QColor(hig.ACCENT_TEXT if dragging else hig.TEXT))
        painter.drawText(badge, Qt.AlignCenter, str(velocity))

    def _hover_badge_rect(self, y: float) -> QRectF:
        top = max(1.0, min(self.height() - 17.0, y - 8.0))
        return QRectF(self.editor.canvas.KEY_W - 38, top, 34, 16)

    def _set_passive_hover(self, velocity: int | None) -> None:
        previous = self.hover_velocity
        if previous == velocity:
            return
        self.hover_velocity = velocity
        key_width = self.editor.canvas.KEY_W
        for value in (previous, velocity):
            if value is None:
                continue
            y = self._y_for_velocity(value)
            self.update(QRectF(key_width, y - 1.5, self.width() - key_width, 3).toAlignedRect())
            self.update(self._hover_badge_rect(y).adjusted(-1, -1, 1, 1).toAlignedRect())

    def _refresh_chart(self) -> None:
        canvas = self.editor.canvas
        dpr = self.devicePixelRatioF()
        if canvas.selected != self._chart_selection:
            self._chart_selection = frozenset(canvas.selected)
        chart_key = (
            self.width(), self.height(), dpr, self.font().toString(),
            canvas._note_index_revision, id(canvas.notes), canvas.KEY_W,
            canvas.scroll_ms, canvas.px_per_ms,
            self.editor.time_sig, getattr(self.editor, "beat_origin_ms", 0.0),
            tr("力度") if self.editor.property("workbenchEmbedded") else None,
            canvas._editable_note_base_color().rgba(),
            self._chart_selection, self.game_velocity_boundaries,
            self.active_point_time,
            self.influence_radius_ms
            if self.active_point_time is not None and self.edit_mode == "brush"
            else None,
        )
        if chart_key != self._chart_key or self._chart.isNull():
            if self._chart_key is None or self._chart_key[:3] != chart_key[:3] or self._chart.isNull():
                self._chart = QPixmap(
                    max(1, round(self.width() * dpr)),
                    max(1, round(self.height() * dpr)),
                )
                self._chart.setDevicePixelRatio(dpr)
            self._chart_key = chart_key
            self._chart_damage = QRectF(self.rect())
        if self._chart_damage.isEmpty():
            return
        painter = QPainter(self._chart)
        try:
            painter.setFont(self.font())
            painter.setClipRect(self._chart_damage)
            self._paint_chart(painter, self._chart_damage)
        finally:
            painter.end()
        self._chart_damage = QRectF()

    def _paint_chart(self, painter: QPainter, damage: QRectF) -> None:
        canvas = self.editor.canvas
        key_width = canvas.KEY_W
        painter.fillRect(self.rect(), QColor(_PLOT))
        self._paint_scale(painter, key_width)

        curve_rect = QRectF(key_width, 0, max(0.0, self.width() - key_width), self.height())
        painter.save()
        painter.setClipRect(curve_rect, Qt.IntersectClip)

        origin = float(getattr(self.editor, "beat_origin_ms", 0.0))
        measure_spacing = (
            canvas.beat_ms
            * max(1, self.editor.time_sig)
            * canvas._measure_guide_stride(canvas.MEASURE_GUIDE_MIN_SPACING)
        )
        guide_x = (
            round(canvas.x_at_time(origin + index * measure_spacing))
            for index in canvas._visible_grid_indices(
                damage.left() - 1.0, damage.right() + 1.0, origin, measure_spacing,
            )
        )
        guide_lines = [QLineF(x, 0, x, self.height()) for x in guide_x]
        if guide_lines:
            painter.setPen(QColor(_MEASURE_GUIDE))
            painter.drawLines(guide_lines)

        if self.active_point_time is not None and self.edit_mode == "brush":
            left = canvas.x_at_time(
                self.active_point_time - self.influence_radius_ms
            )
            right = canvas.x_at_time(
                self.active_point_time + self.influence_radius_ms
            )
            gradient = QLinearGradient(left, 0, right, 0)
            gradient.setColorAt(0.0, QColor(243, 190, 94, 0))
            gradient.setColorAt(0.5, QColor(243, 190, 94, 26))
            gradient.setColorAt(1.0, QColor(243, 190, 94, 0))
            painter.fillRect(QRectF(left, 0, max(1.0, right - left), self.height()), gradient)

        for boundary in self.game_velocity_boundaries:
            y = self._y_for_velocity(boundary)
            pen = QPen(QColor(107, 148, 160, 115), 1.0, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QLineF(key_width, y, self.width(), y))

        # Include neighbouring onsets when repainting a narrow brush range so
        # the point's density-dependent cap does not change at the clip edge.
        margin = self.POINT_DETAIL_MIN_SPACING + 6.0
        points = self._visible_points(
            max(float(key_width), damage.left() - margin),
            min(float(self.width()), damage.right() + margin),
        )
        if points:
            self._paint_velocity_points(painter, points)
        painter.restore()

    def _paint_scale(self, painter: QPainter, key_width: int) -> None:
        height = self.height()
        painter.fillRect(QRectF(0, 0, key_width, height), QColor(_SCALE))
        painter.setPen(QColor(_MEASURE_GUIDE))
        painter.drawLine(QLineF(key_width - 1, 0, key_width - 1, height))
        painter.drawLine(QLineF(0, 0, self.width(), 0))
        font = self.font()
        font.setPixelSize(hig.TYPE_CAPTION)
        painter.setFont(font)
        for value in ((127, 64, 0) if height < 80 else (127, 96, 64, 32, 0)):
            y = self._y_for_velocity(value)
            painter.setPen(QColor(_MEASURE_GUIDE if value in (0, 127) else _LEVEL_GUIDE))
            painter.drawLine(QLineF(key_width, y, self.width(), y))
            painter.drawLine(QLineF(key_width - 5, y, key_width - 1, y))
            painter.setPen(QColor(_AXIS_TEXT))
            label_top = max(1.0, min(height - 15.0, y - 7.0))
            painter.drawText(
                QRectF(key_width - 36, label_top, 26, 14),
                Qt.AlignRight | Qt.AlignVCenter,
                str(value),
            )
        if self.editor.property("workbenchEmbedded"):
            title_width = max(1, key_width - 30)
            title = painter.fontMetrics().elidedText(tr("力度"), Qt.ElideRight, title_width)
            painter.drawText(QRectF(7, height - 15, title_width, 14), Qt.AlignVCenter, title)

    def _paint_velocity_points(
        self, painter: QPainter, points: list[tuple[float, tuple[int, ...], float]],
    ) -> None:
        canvas = self.editor.canvas
        scale = canvas.px_per_ms
        positions = [canvas.KEY_W + (onset - canvas.scroll_ms) * scale for onset, _, _ in points]
        baseline = max(1.0, self.height() - 10.0) + 5.0
        velocity_scale = (baseline - 5.0) / 127.0

        def velocity_y(value: float) -> float:
            return baseline - max(0, min(127, value)) * velocity_scale

        stems: list[QLineF] = []
        caps: list[QLineF] = []
        dense_columns: dict[int, tuple[float, float]] = {}
        chord_ticks: list[QLineF] = []
        selected_stems: list[QLineF] = []
        selected_ticks: list[QLineF] = []
        brushed_ticks: list[QLineF] = []
        active_marker: tuple[float, float] | None = None
        selection = canvas.selected

        for point_index, (onset, indices, velocity) in enumerate(points):
            x = positions[point_index]
            previous_x = positions[point_index - 1] if point_index else -math.inf
            next_x = positions[point_index + 1] if point_index + 1 < len(points) else math.inf
            spacing = min(x - previous_x, next_x - x)
            spacious = spacing >= self.POINT_DETAIL_MIN_SPACING
            selected_indices = [index for index in indices if index in selection] if selection else []
            active = self.active_point_time is not None and math.isclose(
                onset, self.active_point_time, abs_tol=0.001,
            )
            weight = max(self.active_weights.get(index, 0.0) for index in indices) if self.active_weights else 0.0
            marker_velocity = canvas.notes[selected_indices[0]].vel if len(selected_indices) == 1 else velocity
            y = velocity_y(marker_velocity)
            if active:
                active_marker = (x, y)
            elif selected_indices:
                selected_stems.append(QLineF(x, baseline, x, y))
                half_width = 3.5 if spacious else 1.5
                selected_ticks.append(QLineF(x - half_width, y, x + half_width, y))
            elif weight > 0.0:
                half_width = 1.0 + 2.5 * weight
                brushed_ticks.append(QLineF(x - half_width, y, x + half_width, y))
            elif spacing < self.PASSIVE_STEM_MIN_SPACING:
                column = round(x)
                top, bottom = dense_columns.get(column, (y, y))
                dense_columns[column] = (min(top, y), max(bottom, y))
            else:
                stems.append(QLineF(x, baseline, x, y))
                half_width = 2.5 if spacious else 1.2
                caps.append(QLineF(x - half_width, y, x + half_width, y))

            if len(indices) <= 1 or not (spacious or selected_indices or active):
                continue
            values = [canvas.notes[index].vel for index in indices]
            high_y = velocity_y(max(values))
            low_y = velocity_y(min(values))
            if high_y == low_y:
                continue
            chord_ticks.append(QLineF(x, high_y, x, low_y))
            for item, (index, value) in enumerate(zip(indices, values)):
                if not spacious and index not in selection:
                    continue
                note_y = velocity_y(value)
                offset = -4.0 + 8.0 * item / (len(indices) - 1) if spacious else 0.0
                ticks = selected_ticks if index in selection else chord_ticks
                ticks.append(QLineF(x + offset - 1, note_y, x + offset + 1, note_y))

        track = canvas._editable_note_base_color()
        cap = canvas._blend_note_colors(QColor("#93939d"), track, 0.62)
        plot = QColor(_PLOT)
        stem = canvas._blend_note_colors(plot, cap, 0.41)
        chord = canvas._blend_note_colors(plot, cap, 0.51)
        selected = canvas._blend_note_colors(QColor(hig.SELECTION_TEXT), track, 0.2)
        selected_stem = canvas._blend_note_colors(plot, selected, 0.51)
        brushed = QColor(229, 199, 148, 170)
        # At low zoom, represent a screen column once. Original onsets remain
        # available for hit-testing and appear separately when zoomed in.
        dense_marks = [
            QLineF(x, min(top, baseline - 1.0), x, min(baseline, max(top + 1.0, bottom)))
            for x, (top, bottom) in dense_columns.items()
        ]
        for lines, color, width in (
            (stems, stem, 1.0),
            (chord_ticks, chord, 1.0),
            (dense_marks, cap, 1.0),
            (caps, cap, 1.0),
            (selected_stems, selected_stem, 1.0),
            (brushed_ticks, brushed, 1.5),
            (selected_ticks, selected, 2.0),
        ):
            if lines:
                painter.setPen(QPen(color, width))
                painter.drawLines(lines)

        if active_marker is not None:
            x, y = active_marker
            painter.setPen(QPen(QColor(hig.ACCENT), 1.4))
            painter.drawLine(QLineF(x, baseline, x, y))
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor(_PLOT), 1.0))
            painter.setBrush(QColor(hig.ACCENT))
            painter.drawEllipse(QRectF(x - 3.5, y - 3.5, 7, 7))

    def _apply_drag(self, target_velocity: int) -> None:
        if self.active_point_time is None or not self.before_notes:
            return
        canvas = self.editor.canvas
        delta = float(target_velocity) - self.active_point_velocity
        updates: list[tuple[int, Note]] = []
        for index, weight in self.active_weights.items():
            source = self.before_notes[index]
            velocity = max(0, min(127, round(float(source.vel) + delta * weight)))
            if velocity != canvas.notes[index].vel:
                updates.append((index, source._replace(vel=velocity)))
        if updates:
            canvas._apply_live_note_updates(updates)
            x_values = [canvas.x_at_time(note.start) for _, note in updates]
            left = math.floor(min(x_values) - 7.0)
            right = math.ceil(max(x_values) + 7.0)
            self._chart_damage = self._chart_damage.united(
                QRectF(left, 0, right - left, self.height()).intersected(QRectF(self.rect()))
            )
        self.update()

    def _prepare_drag(self, point: tuple[float, tuple[int, ...], float]) -> None:
        onset, point_indices, average_velocity = point
        selected_here = tuple(index for index in point_indices if index in self.before_selected)
        anchor_indices = selected_here if len(selected_here) == 1 else point_indices
        if self.edit_mode == "point":
            candidate_indices = anchor_indices
        else:
            candidate_indices = tuple(self.editor.canvas.visible_note_indices(
                onset - self.influence_radius_ms,
                onset + self.influence_radius_ms,
            ))
            if self.scope_mode == "selection" and self.before_selected:
                candidate_indices = tuple(index for index in candidate_indices
                                          if index in self.before_selected)
            if not candidate_indices:
                candidate_indices = anchor_indices
        self.active_indices = tuple(sorted(set(candidate_indices)))
        self.active_weights = {}
        for index in self.active_indices:
            weight = (1.0 if self.edit_mode == "point" else velocity_neighbor_weight(
                float(self.before_notes[index].start) - onset,
                self.influence_radius_ms,
            ))
            if weight > 0.0:
                self.active_weights[index] = weight
        self.active_point_velocity = (
            float(self.before_notes[anchor_indices[0]].vel)
            if len(anchor_indices) == 1
            else average_velocity
        )
        self.editor.canvas.selected = set(anchor_indices)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        point = self._point_at(event.position().x())
        if point is None:
            return
        onset, indices, velocity = point
        self.before_notes = list(self.editor.canvas.notes)
        self.before_selected = set(self.editor.canvas.selected)
        self.active_point_time = onset
        self._prepare_drag(point)
        self.hover_velocity = self._velocity_at(event.position().y())
        self.editor.canvas.selection_changed.emit()
        self._apply_drag(self.hover_velocity)

    def mouseMoveEvent(self, event) -> None:
        dragging = event.buttons() & Qt.LeftButton and self.active_point_time is not None
        if dragging:
            self.hover_velocity = self._velocity_at(event.position().y())
            self._apply_drag(self.hover_velocity)
            return
        velocity = (
            self._velocity_at(event.position().y())
            if event.position().x() >= self.editor.canvas.KEY_W
            else None
        )
        self._set_passive_hover(velocity)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.before_notes
            and self.editor.canvas.notes != self.before_notes
        ):
            self.editor.push_snapshot(self.before_notes, self.before_selected)
            self.editor.canvas.notes_changed.emit()
        self.before_notes = []
        self.before_selected = set()
        self.active_point_time = None
        self.active_indices = ()
        self.active_weights = {}
        self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        self.set_influence_beats(self.influence_beats + (0.5 if delta > 0 else -0.5))
        callback = getattr(self.editor, "_sync_velocity_radius_control", None)
        if callable(callback):
            callback()
        self.editor.status.setText(
            trf("力度曲线影响范围：前后 {beats:.1f} 拍", beats=self.influence_beats)
        )
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        if self.active_point_time is None:
            self._set_passive_hover(None)
        super().leaveEvent(event)
