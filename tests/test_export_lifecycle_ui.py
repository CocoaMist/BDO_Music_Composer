import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class ExportLifecycleUiTests(unittest.TestCase):
    def _run_script(self, script: str) -> None:
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True, text=True, timeout=45, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_final_save_failure_keeps_model_and_explicit_retry_saves(self) -> None:
        self._run_script('''
            import json
            from unittest.mock import patch
            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui
            import bdo_music_composer.ui.project_autosave_qt as autosave

            app = QApplication([])
            for deferred in (False, True):
                window = gui.MidiToBdoWindow()
                window.show()
                window.source_format = "project"
                window.output_name.setText(f"failed-close-{deferred}")
                track = gui.TrackState(1, [gui.Note(60, 90, 0, 100, 0)], 0, False, "lead", 0x12)
                window.tracks = [track]
                window._autosave_project("baseline", immediate=True)
                assert window._wait_for_autosave_idle()
                path = window.autosave_project_dir / "project.json"
                track.notes = [gui.Note(72, 90, 0, 100, 0)]
                with patch.object(autosave, "write_autosave", side_effect=OSError("disk full")) as writer:
                    event = QCloseEvent()
                    if deferred:
                        with patch.object(window, "_wait_for_autosave_idle", return_value=False):
                            window.closeEvent(event)
                    else:
                        window.closeEvent(event)
                    assert not event.isAccepted()
                    assert window._wait_for_autosave_idle()
                    app.processEvents()
                    assert writer.call_count == 4, writer.call_count
                    assert window.isVisible()
                    assert not window.workspace_close_pending
                    assert not window._final_autosave_queued
                    assert window.tracks[0].notes[0].pitch == 72
                    assert json.loads(path.read_text("utf-8"))["tracks"][0]["notes"][0][0] == 60
                    assert "disk full" in window.status_label.text()
                assert window.close()
                assert window._wait_for_autosave_idle()
                assert json.loads(path.read_text("utf-8"))["tracks"][0]["notes"][0][0] == 72
            app.processEvents()
        ''')

    def test_final_snapshot_failure_keeps_window_open(self) -> None:
        self._run_script('''
            from unittest.mock import patch
            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window.source_format = "project"
            window.tracks = [gui.TrackState(1, [gui.Note(60, 90, 0, 100, 0)], 0, False, "lead", 0x12)]
            with patch.object(gui, "freeze_project_tracks", side_effect=ValueError("invalid snapshot")):
                event = QCloseEvent()
                window.closeEvent(event)
                assert not event.isAccepted()
                assert not window._final_autosave_queued
                assert "invalid snapshot" in window.status_label.text()
            assert window.close()
            assert window._wait_for_autosave_idle()
            app.processEvents()
        ''')

    def test_delete_last_track_persists_empty_project(self) -> None:
        self._run_script('''
            import json
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication, QMessageBox
            import bdo_music_composer.ui.main_window as gui

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            # An untouched home window must not create a recovery project.
            assert not window._flush_autosave()
            assert window.autosave_project_dir is None
            window.source_format = "project"
            window.output_name.setText("delete-last-track")
            track = gui.TrackState(1, [gui.Note(60, 90, 0, 100, 0)], 0, False, "lead", 0x12)
            window.tracks = [track]
            window._refresh_tracks()
            window._autosave_project("baseline", immediate=True)
            assert window._wait_for_autosave_idle()
            path = window.autosave_project_dir / "project.json"
            window._select_track(track)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                window._delete_selected_track()
            assert window.tracks == []
            assert window._wait_for_autosave_idle()
            assert json.loads(path.read_text("utf-8"))["tracks"] == []
            assert json.loads(path.with_name("project.index.json").read_text("utf-8"))["instrument_ids"] == []
            from bdo_music_composer.app.project_document import prepare_project_load
            plan = prepare_project_load(
                path, path.read_text("utf-8"), gui._TRACK_IMPORT_PRESENTATION,
                file_exists=lambda candidate: candidate.is_file(),
                midi_meter_reader=lambda candidate: 4,
            )
            assert plan.tracks == ()
            assert window.close()
            assert window._wait_for_autosave_idle()
            assert json.loads(path.read_text("utf-8"))["tracks"] == []
            app.processEvents()
        ''')

    def test_close_drains_snapshot_queued_by_editor_rejection(self) -> None:
        self._run_script('''
            import json
            from PySide6.QtWidgets import QApplication
            import bdo_music_composer.ui.main_window as gui

            app = QApplication([])
            window = gui.MidiToBdoWindow()
            window.source_format = "project"
            track = gui.TrackState(1, [gui.Note(60, 90, 0, 100, 0)], 0, False, "lead", 0x12)
            window.tracks = [track]
            rejected = []
            def close_editors():
                if not rejected:
                    rejected.append(True)
                    track.notes = [gui.Note(72, 90, 0, 100, 0)]
                    window._autosave_project("note editor close", immediate=True)
            window._close_all_note_editors = close_editors
            assert window.close()
            assert window.autosave_worker is None
            path = window.autosave_project_dir / "project.json"
            assert json.loads(path.read_text("utf-8"))["tracks"][0]["notes"][0][0] == 72
            app.processEvents()
        ''')

    def test_close_waits_for_export_worker(self) -> None:
        script = textwrap.dedent(
            """
            import os

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow


            class RunningExport:
                def isRunning(self):
                    return True


            app = QApplication.instance() or QApplication([])
            window = MidiToBdoWindow()
            window._flush_autosave = lambda: None
            window.worker = RunningExport()
            event = QCloseEvent()

            window.closeEvent(event)

            assert not event.isAccepted()
            assert window.workspace_close_pending
            window.worker = None
            window.workspace_close_pending = False
            window.close()
            app.processEvents()
            app.quit()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_close_queues_final_autosave_only_once(self) -> None:
        script = textwrap.dedent(
            """
            import os

            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

            from PySide6.QtGui import QCloseEvent
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.ui.main_window import MidiToBdoWindow


            class SlowAutosave:
                def isRunning(self):
                    return True

                def wait(self, _timeout_ms):
                    return False


            app = QApplication.instance() or QApplication([])
            window = MidiToBdoWindow()
            flushes = []

            def queue_slow_save():
                flushes.append("save")
                window.autosave_worker = SlowAutosave()

            window._flush_autosave = queue_slow_save
            first = QCloseEvent()
            window.closeEvent(first)
            assert not first.isAccepted()
            assert window.workspace_close_pending
            assert flushes == ["save"]

            # A worker completion schedules another closeEvent.  It must not
            # enqueue a second final snapshot even if the first took >30 s.
            window.autosave_worker = None
            second = QCloseEvent()
            window.closeEvent(second)
            assert second.isAccepted()
            assert flushes == ["save"]
            app.processEvents()
            app.quit()
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
