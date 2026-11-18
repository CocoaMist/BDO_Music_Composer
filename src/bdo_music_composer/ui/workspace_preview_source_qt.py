"""Preview source selection and diagnostic presentation in the More menu."""

from __future__ import annotations

from bdo_music_composer.app.audio_source_settings import preview_source_mode, source_paths_for_mode
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.game_score_model import preview_tracks
from bdo_music_composer.ui.i18n import tr


class WorkspacePreviewSourceMixin:
    def _refresh_preview_source_status(self, tracks: list[TrackState] | None = None) -> None:
        if tracks is None:
            tracks = list(preview_tracks(self.tracks))
        source_mode = preview_source_mode(self.audio_sources)
        blocker = ""
        if source_mode == "pack":
            # Opening a menu only checks the configured location. Play owns
            # the full media scan and publishes its diagnostic for this scope.
            blocker = self._preview_pack_location_error(tracks)
            diagnostic = self._preview_pack_diagnostic
            if not blocker and diagnostic and diagnostic[0] == self._preview_pack_scope(tracks):
                blocker = str(diagnostic[1])
        if (
            self.realtime_preview_source == "generic"
            and (self.realtime_preview_active or self.realtime_preview_loading)
        ):
            badge_text = tr("内置通用 MIDI · 非游戏原声")
        elif not self.realtime_audio.available():
            badge_text = tr("无可用音频设备")
        elif source_mode == "generic":
            badge_text = tr("内置通用音源")
        elif blocker:
            badge_text = tr("音源包不可用")
        elif self.realtime_audio.status.cache_misses:
            badge_text = tr("等待预取")
        else:
            badge_text = tr("音源包")
        self.preview_source_menu.setTitle(f"{tr('试听音源')} · {badge_text}")
        detail = tr("点击切换试听音源；不会改变导出结果")
        if blocker:
            detail += "\n" + blocker
        self.preview_source_action.setToolTip(detail)
        self._sync_preview_source_menu()

    def _sync_preview_source_menu(self) -> None:
        actions = getattr(self, "preview_source_actions", {})
        mode = preview_source_mode(self.audio_sources)
        for action_mode, action in actions.items():
            action.setChecked(action_mode == mode)
        pack_action = actions.get("pack")
        if pack_action is not None:
            pack_action.setEnabled(any(source_paths_for_mode(self.audio_sources, "pack")))

    def _preview_pack_scope(self, tracks: list[TrackState]) -> tuple:
        return (
            self.audio_sources.get("audio_root", ""),
            self.audio_sources.get("sample_pack", ""),
            tuple((track.bdo_instrument_id, track.marnian_synth_mode, track.display_name) for track in tracks),
        )
