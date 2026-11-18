"""Regression coverage for workbench focus changes and property commits."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class WorkbenchPropertyCommitTests(unittest.TestCase):
    def test_focus_changes_and_effect_drafts(self) -> None:
        source = textwrap.dedent(
            """
            from unittest.mock import patch

            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QDialog

            from bdo_common.bdo_track_effects import TRACK_DELAY_SEND_INDEX, TRACK_REVERB_SEND_INDEX
            from bdo_midi import Note
            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.dialogs.track_settings_dialogs import TrackFxDialog
            from bdo_music_composer.ui.main_window import MidiToBdoWindow

            app = QApplication([])
            window = MidiToBdoWindow()
            window.show()
            window._dismiss_usage_welcome()
            window._create_new_project("Workbench property test")
            first = TrackState(1, [Note(60, 80, 0, 200, 0)], 0, False, "Piano", 17,
                               bdo_track_volume=178)
            second = TrackState(2, [], 0, False, "Piano double", 17, bdo_track_volume=178)
            drum = TrackState(3, [], 0, True, "Drums", 0x0D)
            window.tracks = [first, second, drum]
            window._refresh_tracks()
            window._show_workspace()
            window.activateWindow()
            QTest.qWait(180)
            window._select_track(first)
            window.workbench.inspector_toggle.setChecked(True)
            QTest.qWait(180)
            inspector = window.workbench.inspector

            inspector.volume.setFocus()
            assert inspector.volume.hasFocus() or inspector.volume.lineEdit().hasFocus()
            assert inspector.volume.value() == 100
            inspector.volume.clearFocus()
            assert first.bdo_track_volume == second.bdo_track_volume == 178
            inspector.volume.setFocus()
            inspector.volume.stepDown()
            inspector.volume.clearFocus()
            assert first.bdo_track_volume == second.bdo_track_volume == 99

            inspector.pitch.setFocus()
            inspector.pitch.lineEdit().selectAll()
            QTest.keyClicks(inspector.pitch.lineEdit(), "12")
            window._select_track(drum)
            assert not inspector.pitch.isEnabled()
            assert window._pitch_transform_plan.override_for(drum.track_id) is None

            window.reference_layer_settings["follow_reference_bpm"] = True
            window._sync_global_bpm_control()
            tempo = window.global_bpm_spin
            tempo.setFocus()
            assert tempo.hasFocus() or tempo.lineEdit().hasFocus()
            tempo.clearFocus()
            assert window.reference_layer_settings["follow_reference_bpm"]
            tempo.setFocus()
            tempo.stepUp()
            expected_bpm = tempo.value()
            QTest.keyClick(tempo, Qt.Key_Return)
            assert not window.reference_layer_settings["follow_reference_bpm"]
            assert window.bpm_override == expected_bpm

            window._select_track(first)
            inspector.tabs.setCurrentWidget(inspector.effects_page)
            sends = inspector.fx_dialog._effect_fields
            sends[TRACK_DELAY_SEND_INDEX].setValue(21)

            def edit_reverb(dialog):
                dialog._effect_fields[TRACK_REVERB_SEND_INDEX].setValue(30)
                return QDialog.Accepted

            with patch.object(TrackFxDialog, "exec", edit_reverb):
                window._show_effects_placeholder(first)
            assert sends[TRACK_REVERB_SEND_INDEX].value() == 30
            assert sends[TRACK_DELAY_SEND_INDEX].value() == 21
            assert first.bdo_track_settings[TRACK_DELAY_SEND_INDEX] == 0
            inspector.fx_apply_button.click()
            assert first.bdo_track_settings[TRACK_REVERB_SEND_INDEX] == 30
            assert first.bdo_track_settings[TRACK_DELAY_SEND_INDEX] == 21
            window.close()
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", BDO_USER_DATA_DIR=directory)
            result = subprocess.run(
                [sys.executable, "-c", source],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                capture_output=True,
                text=True,
                timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
