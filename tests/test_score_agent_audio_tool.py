"""Score Agent reference audio shares the captured score's exact time scope."""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import wave

from bdo_midi import Note
from bdo_music_composer.creation.score_agent_tools import AGENT_TOOLS, ScoreAgentToolError
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.ui.score_agent_scope_qt import (
    capture_workspace_score,
    workspace_agent_scope,
    workspace_reference_audio_source,
)


class ScoreAgentAudioToolTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio = Path(directory.name) / "private reference title.wav"
        rate = 8_000
        frames = [round(10_000 * math.sin(2 * math.pi * 330 * index / rate)) for index in range(4 * rate)]
        with wave.open(str(self.audio), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            output.writeframes(struct.pack(f"<{len(frames)}h", *frames))

        track = TrackState(17, [
            Note(58, 75, 1_600.0, 180.0, 0),
            Note(60, 75, 1_700.0, 180.0, 0),
            Note(62, 75, 2_100.0, 180.0, 0),
            Note(64, 75, 2_400.0, 180.0, 0),
        ], 0, False, "Private named track", 0)
        timeline = SimpleNamespace(
            time_range=(1_630.0, 2_375.0), playhead_ms=0.0, beat_origin_ms=125.0,
            selection_descriptor=lambda: {"clips": [], "tracks": [track], "active_track": track},
        )
        self.host = SimpleNamespace(
            loading_project=False, timeline=timeline, tracks=[track], bpm=120, bpm_override=0,
            time_sig=4, time_sig_denominator=4, project_id="test", model_revision=SimpleNamespace(value=0),
            reference_audio_path=str(self.audio), reference_audio_offset_ms=400.0,
            reference_audio_relink_required=False,
        )

    def capture(self):
        return capture_workspace_score(self.host, workspace_agent_scope(self.host))

    def test_tool_measures_exact_selected_passage_without_file_identity(self) -> None:
        names = [schema["function"]["name"] for schema in AGENT_TOOLS]
        self.assertIn("inspect_reference_audio", names)
        capture = self.capture()
        self.assertEqual(capture.scope.reference_audio, "attached")
        result = capture.tools.call("inspect_reference_audio", {})
        self.assertEqual(result["requested_project_range_ms"], [1_630.0, 2_375.0])
        self.assertEqual(result["analyzed_reference_range_ms"], [1_230.0, 1_975.0])
        self.assertEqual(result["score_note_starts"]["notes"], [
            {"project_ms": 1_700.0, "pitch": 60}, {"project_ms": 2_100.0, "pitch": 62},
        ])
        payload = json.dumps({"summary": capture.tools.scope_summary(), "result": result}, allow_nan=False)
        self.assertNotIn(self.audio.name, payload)
        self.assertNotIn("Private named track", payload)

    def test_tool_rejects_outside_scope_and_supports_narrower_bar(self) -> None:
        capture = self.capture()
        for args, code in (
            ({"first_bar": 1}, "incomplete_bar_range"),
            ({"first_bar": 3, "bars": 1}, "outside_bar_scope"),
            ({"path": str(self.audio)}, "unknown_arguments"),
        ):
            with self.subTest(args=args), self.assertRaises(ScoreAgentToolError) as raised:
                capture.tools.call("inspect_reference_audio", args)
            self.assertEqual(raised.exception.code, code)
        result = capture.tools.call("inspect_reference_audio", {"first_bar": 2, "bars": 1})
        self.assertEqual(result["requested_project_range_ms"], [2_000.0, 2_375.0])
        self.assertEqual(result["score_note_starts"]["total"], 1)

    def test_transients_compare_with_first_visible_score_onset_in_each_bar(self) -> None:
        self.host.timeline.time_range = (1_630.0, 6_000.0)
        self.host.tracks[0].notes.extend(Note(61, 75, 1_800.0 + step, 15.0, 0) for step in range(64))
        rate = 8_000
        frames = [0] * (4 * rate)
        for project_ms in (1_760, 2_060, 4_050):
            start = (project_ms - 400) * rate // 1_000
            for index in range(rate // 25):
                frames[start + index] = round(10_000 * math.sin(2 * math.pi * 330 * index / rate))
        with wave.open(str(self.audio), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            output.writeframes(struct.pack(f"<{len(frames)}h", *frames))

        result = self.capture().tools.call("inspect_reference_audio", {})
        self.assertTrue(result["score_note_starts"]["truncated"])
        self.assertEqual(result["transient_score_alignment"], [
            {"project_ms": 1_760.0, "project_bar": 1, "first_visible_score_onset_ms": 1_700.0,
             "delta_ms": 60.0, "bar_coverage": "partial"},
            {"project_ms": 2_060.0, "project_bar": 2, "first_visible_score_onset_ms": 2_100.0,
             "delta_ms": -40.0, "bar_coverage": "full"},
            {"project_ms": 4_050.0, "project_bar": 3, "first_visible_score_onset_ms": None,
             "delta_ms": None, "bar_coverage": "partial"},
        ])

    def test_capture_tracks_alignment_and_relink_without_reading_audio(self) -> None:
        previous = self.capture()
        self.host.reference_audio_offset_ms += 250
        current = self.capture()
        self.assertNotEqual(previous.history_key, current.history_key)
        self.assertEqual(current.reference_audio_source, workspace_reference_audio_source(
            self.host, grid_origin_ms=self.host.timeline.beat_origin_ms,
        ))
        self.audio.unlink()
        self.host.reference_audio_relink_required = True
        relink = self.capture()
        self.assertEqual(relink.scope.reference_audio, "relink_required")
        self.assertNotIn(self.audio.name, repr(relink))
        with self.assertRaisesRegex(ScoreAgentToolError, "reference_audio_relink_required"):
            relink.tools.call("inspect_reference_audio", {})


if __name__ == "__main__":
    unittest.main()
