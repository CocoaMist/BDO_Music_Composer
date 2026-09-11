from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MidiCompatibilityImportUiTests(unittest.TestCase):
    def test_repaired_import_is_visible_and_original_stays_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            midi_path = root / "broken-value.mid"
            track_payload = bytes((
                0x00, 0xB0, 0x07, 0xFF,
                0x00, 0x90, 0x3C, 0x64,
                0x83, 0x60, 0x80, 0x3C, 0x00,
                0x00, 0xFF, 0x2F, 0x00,
            ))
            header = b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xE0"
            midi_path.write_bytes(
                header
                + b"MTrk"
                + len(track_payload).to_bytes(4, "big")
                + track_payload
            )
            original = midi_path.read_bytes()
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(root / "user-data")
            script = textwrap.dedent(
                f"""
                from pathlib import Path
                from PySide6.QtWidgets import QApplication
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                path = Path({str(midi_path)!r})
                original = {original!r}
                app = QApplication([])
                window = MidiToBdoWindow()
                window._autosave_project = lambda *args, **kwargs: None
                window._record_recent = lambda *args, **kwargs: None
                window._open_midi_path(path)
                assert len(window.tracks) == 1
                assert window.tracks[0].note_count == 1
                assert sum(r.count for r in window._last_midi_import_repairs) == 1
                assert "已兼容修复 1 个越界数据值" in window.status_label.text()
                assert path.read_bytes() == original
                window.close()
                app.processEvents()
                app.quit()
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
