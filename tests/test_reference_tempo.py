from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile

from bdo_music_composer.transcription.reference_tempo import (
    ReferenceTempoError,
    estimate_reference_tempo,
)


class ReferenceTempoTests(unittest.TestCase):
    def test_regular_click_track_produces_reliable_tempo(self) -> None:
        sample_rate = 22_050
        duration_seconds = 24
        audio = np.zeros(sample_rate * duration_seconds, dtype=np.float32)
        decay = np.exp(-np.arange(900, dtype=np.float32) / 80.0)
        for beat in np.arange(0.5, duration_seconds - 0.5, 0.5):
            start = round(float(beat) * sample_rate)
            audio[start : start + decay.size] += decay
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "click.wav"
            soundfile.write(path, audio, sample_rate)
            estimate = estimate_reference_tempo(path)

        self.assertAlmostEqual(estimate.detected_bpm, 120.0, delta=4.0)
        self.assertGreaterEqual(estimate.confidence, 0.58)
        self.assertGreaterEqual(estimate.beat_count, 8)
        self.assertLessEqual(estimate.tempo_drift_ratio, 0.12)

    def test_cancelled_estimate_does_not_decode(self) -> None:
        with patch("builtins.__import__", side_effect=AssertionError("must not import DSP")):
            with self.assertRaises(ReferenceTempoError):
                estimate_reference_tempo("unused.wav", cancelled=lambda: True)

    def test_missing_file_does_not_import_audio_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.wav"
            with patch("builtins.__import__", side_effect=AssertionError("must not import DSP")):
                with self.assertRaisesRegex(ReferenceTempoError, "file is missing"):
                    estimate_reference_tempo(missing)


if __name__ == "__main__":
    unittest.main()
