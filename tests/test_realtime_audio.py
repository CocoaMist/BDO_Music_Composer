import unittest

from bdo_midi import Note
from bdo_music_composer.audio.bdo_realtime_audio import BdoRealtimeAudioEngine
from bdo_music_composer.editor.editor_models import TrackState


class ProceduralPreviewTests(unittest.TestCase):
    def test_preload_reuses_only_same_rate_samples(self):
        engine = BdoRealtimeAudioEngine(None, {})
        self.addCleanup(engine.stop)
        tracks = [
            TrackState(1, [Note(60, 90, 0, 120, 0)], 0, False, "Piano", 0x11),
            TrackState(2, [Note(48, 90, 250, 90, 99)], 0, True, "Drums", 0x0D),
        ]
        cold = engine._prepare_procedural_project(tracks, 0, 0, 0, None)
        engine._commit_project(*cold, start_ms=0)
        engine.clear_playback()

        repeated = engine._prepare_procedural_project(tracks, 0, 0, 0, None)
        self.assertEqual(repeated[0], cold[0])
        for key, sample in repeated[1].items():
            self.assertIs(sample, cold[1][key])
            self.assertFalse(sample.pcm.flags.writeable)

        engine._sample_rate = 36_000
        changed_rate = engine._prepare_procedural_project(tracks, 0, 0, 0, None)
        for key, sample in changed_rate[1].items():
            self.assertIsNot(sample, cold[1][key])
            self.assertEqual(sample.rate, 36_000)
        self.assertEqual(changed_rate[0][1].frame, 9_000)
