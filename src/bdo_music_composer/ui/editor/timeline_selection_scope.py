"""Track/Clip focus-scope helpers for the timeline canvas."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt


def selection_descriptor(canvas) -> dict[str, object]:
    return {
        "scope": canvas.selection_scope,
        "active_track": canvas.selected_track,
        "tracks": canvas.selected_track_items(),
        "clips": canvas.selected_clip_items(),
    }


def select_pointer_track(canvas, track, modifiers: Qt.KeyboardModifiers) -> None:
    track_id = int(track.track_id)
    if not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
        canvas._select_track(track, emit=True)
        return
    selected = (
        set(canvas._selected_track_ids)
        if canvas.selection_scope == "track" else set()
    )
    if modifiers & Qt.ControlModifier and track_id in selected:
        selected.remove(track_id)
    else:
        selected.add(track_id)
    if not selected:
        canvas._clear_arrangement_selection()
        return
    if track_id not in selected:
        active = canvas.selected_track
        track = (
            active if active is not None and int(active.track_id) in selected
            else next(item for item in canvas.tracks if int(item.track_id) in selected)
        )
    canvas._select_track(track, emit=True, track_ids=selected)


def seek_empty_grid(
    canvas,
    x: float,
    modifiers: Qt.KeyboardModifiers,
    *,
    clear_selection: bool = True,
) -> None:
    if clear_selection and not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
        canvas._clear_arrangement_selection()
    canvas.set_playhead(canvas._time_at_x(x))
    canvas.seek_requested.emit(canvas.playhead_ms)


def press_empty_track_space(canvas, event) -> bool:
    pos = event.position()
    if (
        event.button() != Qt.LeftButton
        or canvas.arrangement_tool == "marquee"
        or not canvas.grid_rect.contains(pos)
        or canvas._track_at_position(pos) is None
    ):
        return False
    seek_empty_grid(canvas, pos.x(), event.modifiers())
    event.accept()
    return True


def reset_marquee_selection(canvas) -> None:
    canvas._marquee_press_pos = None
    canvas._marquee_current_pos = QPointF()
    canvas._marquee_active = False
    canvas._marquee_modifiers = Qt.NoModifier
    canvas._marquee_base_clip_keys.clear()
    canvas._marquee_preview_clip_keys.clear()
    canvas._marquee_origin_clip = None


__all__ = [
    "press_empty_track_space", "reset_marquee_selection", "seek_empty_grid",
    "select_pointer_track", "selection_descriptor",
]
