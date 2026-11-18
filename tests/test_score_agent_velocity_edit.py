"""Relative velocity proposals operate on authored values and the captured bars."""

from __future__ import annotations

import unittest

from bdo_midi import Note
from bdo_music_composer.creation.score_agent_tools import ScoreAgentToolError, ScoreAgentTools
from bdo_music_composer.creation.workspace import CreationContext, build_creation_session
from bdo_music_composer.editor.editor_models import TrackState


def _capture(tracks):
    context = CreationContext.capture(tracks, 120, 4)
    tools = ScoreAgentTools(context, track_id=7, clip_id="", first_bar=2, bars=1, time_range_ms=(2_000.0, 4_000.0))
    return context, tools


def _apply_scale(tracks, percent):
    context, tools = _capture(tracks)
    result = tools.call("creative_plan", {"action": "express", "velocity_scale_percent": percent})
    assert result["velocity_scale_percent"] == percent and tools.proposal is not None
    session = build_creation_session(context, tools.proposal.brief, tools.proposal.clip_id)
    return session.materialize(frozenset({"expression"}))


class ScoreAgentVelocityEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.notes = [
            Note(60, 62, 500.0, 397.314, 0),
            Note(62, 100, 2_000.0, 397.314, 0),
            Note(64, 80, 2_490.0, 397.314, 0),
            Note(65, 93, 2_800.0, 397.314, 2),
            Note(67, 1, 3_200.0, 397.314, 0),
            Note(71, 66, 4_000.0, 397.314, 0),
        ]
        self.tracks = [
            TrackState(7, self.notes, 0, False, "Scoped melody", 17, duration_scale=1.3),
            TrackState(8, [Note(68, 88, 2_000.0, 210.0, 0)], 0, False, "Control", 17),
        ]

    def test_repeated_scaling_uses_authored_velocity_and_preserves_scope(self) -> None:
        first = _apply_scale(self.tracks, 90)
        second = _apply_scale(first, 90)
        expected = list(self.notes)
        expected[1] = expected[1]._replace(vel=90)
        expected[2] = expected[2]._replace(vel=72)
        self.assertEqual(first[0].notes, expected)
        expected[1] = expected[1]._replace(vel=81)
        expected[2] = expected[2]._replace(vel=65)
        self.assertEqual(second[0].notes, expected)
        self.assertEqual(second[0].duration_scale, 1.3)
        self.assertEqual(second[1], self.tracks[1])

    def test_identity_prioritizes_current_velocity_even_for_flat_bars(self) -> None:
        self.tracks[0].notes = [Note(60, 70, 2_000.0, 300.0, 0), Note(62, 70, 2_500.0, 300.0, 0)]
        self.assertEqual(_apply_scale(self.tracks, 100), self.tracks)
        self.assertEqual([n.vel for n in _apply_scale(self.tracks, 200)[0].notes], [127, 127])

    def test_invalid_proposals_cannot_stage_a_velocity_edit(self) -> None:
        for fields, expected in (
            ({"velocity_scale_percent": True}, "invalid_integer"),
            ({"velocity_scale_percent": 24}, "invalid_integer"),
            ({"velocity_scale_percent": 201}, "invalid_integer"),
            ({"velocity_scale_percent": 90, "rewrite_velocity": True}, "velocity_scale_conflicts_with_rewrite"),
            ({"velocity_scale_percent": 90, "first_bar": 1, "bars": 1}, "outside_bar_scope"),
        ):
            _, tools = _capture(self.tracks)
            with self.subTest(fields=fields), self.assertRaises(ScoreAgentToolError) as raised:
                tools.call("creative_plan", {"action": "express", **fields})
            self.assertEqual(raised.exception.code, expected)
            self.assertIsNone(tools.proposal)
