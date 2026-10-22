from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bdo_codec import decode_score, encode_score
from bdo_midi import Note
from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.creation.brief import CreationAction as Action, CreationBrief, MusicalCharacter
from bdo_music_composer.creation.feedback import record_choice
from bdo_music_composer.creation.workspace import (
    CreationContext, build_creation_alternatives, build_creation_session,
)
from bdo_music_composer.editor.arrangement_clip import clip_editor_notes, project_track_notes
from bdo_music_composer.editor.editor_models import ArrangementClipState, TrackState, game_supported_pitches
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan
from bdo_music_composer.export.export_workflow import ExportRequest, freeze_export_tracks, prepare_export
from optimization.plugin_api import InvalidOptimizationPreview


def track(notes=(), *, track_id=1, instrument=17, **kwargs):
    return TrackState(track_id, list(notes), 0, instrument == 13, "reference", instrument, **kwargs)


def session(tracks=(), action=Action.DRAFT, **kwargs):
    return build_creation_session(CreationContext.capture(list(tracks), 120, 4), CreationBrief(action, **kwargs))


class CreationAssistantTests(unittest.TestCase):
    def test_blank_project_materializes_real_editable_notes_and_optional_parts(self):
        value = session()
        result = value.materialize(frozenset({"melody", "harmony", "bass"}))
        self.assertEqual(len(result), 3)
        self.assertTrue(all(t.notes and isinstance(t.notes[0], Note) for t in result))
        self.assertTrue(all(t.arrangement_clips for t in result))
        self.assertEqual(value.materialize(frozenset()), [])
        self.assertEqual(tuple(value.context.tracks), ())
        with self.assertRaisesRegex(ValueError, "unknown"):
            value.materialize(frozenset({"nonexistent"}))

    def test_creation_is_deterministic_and_variants_change_music(self):
        scores = [session(variant=i).materialize(frozenset({"melody", "harmony"})) for i in range(3)]
        self.assertEqual(scores[0], session().materialize(frozenset({"melody", "harmony"})))
        self.assertEqual(len({tuple(t.notes[0].pitch for t in score) + tuple(n.pitch for n in score[0].notes) for score in scores}), 3)

    def test_generated_notes_obey_key_game_ranges_time_scope_and_drum_encoding(self):
        for minor in (False, True):
            for tonic in (0, 3, 11):
                with self.subTest(minor=minor, tonic=tonic):
                    value = session(tonic=tonic, minor=minor, start_bar=3, bars=16, character=MusicalCharacter.LIGHT)
                    result = value.materialize(frozenset({p.key for p in value.candidate.parts}))
                    scale = {(tonic + i) % 12 for i in ((0,2,3,5,7,8,10) if minor else (0,2,4,5,7,9,11))}
                    for t in result:
                        self.assertLessEqual(len(t.notes), 680)
                        supported = game_supported_pitches(t.bdo_instrument_id)
                        for n in t.notes:
                            self.assertTrue(6000 <= n.start < n.start+n.dur <= 38000)
                            self.assertTrue(1 <= n.vel <= 127)
                            if supported: self.assertIn(n.pitch, supported)
                            if t.is_percussion:
                                self.assertTrue(48 <= n.pitch <= 64)
                                self.assertEqual(n.ntype, 99)
                            else:
                                self.assertIn(n.pitch % 12, scale)

    def test_created_parts_do_not_inherit_reference_mute_clips_mixer_or_source_records(self):
        source = track([Note(60,80,0,100,0)], muted=True, solo=True, volume_scale=.5,
                       performance_controls=[{"type":"user"}], bdo_source_note_records=((60,80,0.,100.,0,33),),
                       arrangement_clips=[ArrangementClipState("source",0,2000,0,2000)])
        before = deepcopy(source)
        result = session([source]).materialize(frozenset({"harmony"}))
        self.assertEqual(result[0], before)
        self.assertFalse(result[1].muted or result[1].solo)
        self.assertEqual(result[1].volume_scale, 1)
        self.assertEqual(result[1].performance_controls, [])
        self.assertEqual(result[1].bdo_source_note_records, ())
        self.assertNotEqual(result[1].arrangement_clips, source.arrangement_clips)
        self.assertEqual(source, before)

    def test_accompaniment_preserves_melody_and_an_intentional_empty_bar(self):
        source = track([Note(60,80,0,400,0),Note(64,86,1000,400,0),Note(67,84,4000,400,0)])
        value = session([source], Action.ACCOMPANY, source_track_id=1, bars=4)
        result = value.materialize(frozenset({"harmony", "bass"}))
        self.assertEqual(result[0], source)
        self.assertIsNone(value.candidate.chord_degrees[1])
        self.assertTrue(all(not (2000 <= n.start < 4000) for t in result[1:] for n in t.notes))
        self.assertEqual(len(result), 3)
        self.assertTrue(all(t.notes for t in result[1:]))

    def test_empty_reference_abstains(self):
        value = session([track()], Action.ACCOMPANY, source_track_id=1)
        self.assertEqual(value.candidate.preview.operations, ())
        self.assertIn("empty_reference", [f.code for f in value.candidate.findings])

    def test_accompaniment_has_distinct_textures_even_for_one_unambiguous_chord(self):
        source = track([Note(p, 80, bar * 2000 + beat * 500, 400, 0)
                        for bar in range(4) for beat, p in enumerate((60, 64, 67, 64))])
        context = CreationContext.capture([source], 120, 4)
        values = build_creation_alternatives(context, CreationBrief(Action.ACCOMPANY, source_track_id=1, bars=4))
        self.assertEqual(len(values), 3)
        harmonies = []
        for value in values:
            result = value.materialize(frozenset({"harmony"}))
            self.assertEqual(result[0], source)
            self.assertEqual(value.candidate.chord_degrees, (0, 0, 0, 0))
            harmonies.append(tuple(result[1].notes))
        self.assertEqual(len(set(harmonies)), 3)
        self.assertEqual(values, build_creation_alternatives(context, CreationBrief(Action.ACCOMPANY, source_track_id=1, bars=4)))

    def test_alternatives_deduplicate_noops_and_cooperate_with_cancellation(self):
        context = CreationContext.capture([track()], 120, 4)
        brief = CreationBrief(Action.ACCOMPANY, source_track_id=1)
        values = build_creation_alternatives(context, brief)
        self.assertEqual(len(values), 1)
        self.assertFalse(values[0].candidate.preview.operations)
        self.assertEqual(build_creation_alternatives(context, brief, cancelled=lambda: True), ())

    def test_selection_reuses_prepared_proposals_and_returns_detached_containers(self):
        source = track([Note(60, 80, 0, 400, 0)],
                       effect_settings_placeholder={"nested": [1]},
                       performance_controls=[{"time": 0, "value": [2]}])
        value = session([source], Action.ACCOMPANY, source_track_id=1)
        with patch("bdo_music_composer.creation.workspace.apply_preview") as apply, patch(
            "bdo_music_composer.creation.workspace.project_track_notes"
        ) as project:
            first = value.materialize(frozenset({"harmony"}))
            second = value.materialize(frozenset({"bass"}))
            apply.assert_not_called()
            project.assert_not_called()
        first[0].notes.clear()
        first[0].effect_settings_placeholder["nested"].append(3)
        first[0].performance_controls[0]["value"].append(4)
        self.assertEqual(second[0], source)
        self.assertEqual(value.context.tracks[0], source)
        source.notes.clear()
        self.assertEqual(len(value.context.tracks[0].notes), 1)
        self.assertEqual(value.context.tracks[0].effect_settings_placeholder, {"nested": [1]})

    def test_remapping_inherits_destination_mix_and_remains_exportable(self):
        source = track([Note(60, 80, 0, 400, 0)], instrument=17, bdo_track_volume=100)
        peer = track([Note(64, 80, 0, 400, 0)], track_id=2, instrument=11,
                     bdo_track_volume=30, bdo_track_settings=(21, 0, 32, 0, 43, 0, 0, 0))
        before = deepcopy([source, peer])
        value = session([source, peer], Action.ADAPT, source_track_id=1, melody_instrument=11)
        result = value.materialize(frozenset({"adaptation"}))
        self.assertEqual([t.bdo_track_volume for t in result], [30, 30])
        self.assertEqual(result[0].bdo_track_settings, peer.bdo_track_settings)
        self.assertEqual(result[1], peer)
        self.assertEqual([source, peer], before)
        request = ExportRequest(direct_tracks=freeze_export_tracks(result), bpm=120, time_signature=4,
            out_path=Path("unused"), character_name="Test", owner_id=123,
            conversion=ConversionSettings.bdo_import_defaults(), pitch_plan=PitchTransformPlan(0),
            reverb=0, delay=0, chorus=None, game_dir=Path("unused-game"))
        document = decode_score(prepare_export(request).data)
        self.assertEqual(sum(len(t.notes) for g in document.groups for t in g.tracks), 2)
        self.assertEqual(document.groups[0].tracks[0].volume, 30)

    def test_conflicting_destination_peers_are_not_resolved_by_picking_the_first(self):
        tracks = [track([Note(60, 80, 0, 400, 0)]),
                  track([Note(64, 80, 0, 400, 0)], track_id=2, instrument=11, bdo_track_volume=30),
                  track([Note(67, 80, 0, 400, 0)], track_id=3, instrument=11, bdo_track_volume=40)]
        before = deepcopy(tracks)
        with self.assertRaisesRegex(ValueError, "conflicting mixer"):
            session(tracks, Action.ADAPT, source_track_id=1, melody_instrument=11)
        self.assertEqual(tracks, before)

    def test_game_adaptation_preserves_note_count_pitch_classes_timing_and_valid_manual_types(self):
        source = track([Note(100,80,10,300,11),Note(15,65,510,250,253)], instrument=17)
        value = session([source], Action.ADAPT, source_track_id=1, melody_instrument=11)
        result = value.materialize(frozenset({"adaptation"}))[0]
        self.assertEqual(len(result.notes), len(source.notes))
        from bdo_midi import BDO_TO_GM_PREVIEW_ROUTE
        self.assertEqual(result.gm_program,BDO_TO_GM_PREVIEW_ROUTE[11].program)
        self.assertEqual([n.pitch % 12 for n in result.notes], [n.pitch % 12 for n in source.notes])
        self.assertEqual([(n.start,n.dur,n.vel) for n in result.notes], [(n.start,n.dur,n.vel) for n in source.notes])
        self.assertTrue(all(n.pitch in game_supported_pitches(11) for n in result.notes))
        again = session([result], Action.ADAPT, source_track_id=1, melody_instrument=11)
        self.assertFalse(again.candidate.preview.operations)
        manual = track([Note(60,80,0,100,11)])
        preserved = session([manual], Action.ADAPT, source_track_id=1).materialize(frozenset({"adaptation"}))
        self.assertEqual(preserved[0].notes, manual.notes)
        legacy = track([Note(110,80,0,100,99)], articulation_type=253)
        preserved = session([legacy], Action.ADAPT, source_track_id=1).materialize(frozenset({"adaptation"}))
        self.assertEqual(preserved[0].notes[0].ntype,99)
        self.assertNotEqual(preserved[0].notes[0].pitch,110)
        self.assertEqual(preserved[0].articulation_type,253)

    def test_native_and_gm_drum_keys_are_never_guessed_from_pitch_range(self):
        source = track([Note(48,80,0,100,0)], instrument=13)
        native = session([source], Action.ADAPT, source_track_id=1, melody_instrument=13).materialize(frozenset({"adaptation"}))[0]
        gm = session([source], Action.ADAPT, source_track_id=1, melody_instrument=13, drums_are_gm=True).materialize(frozenset({"adaptation"}))[0]
        self.assertEqual((native.notes[0].pitch,native.notes[0].ntype), (48,99))
        self.assertEqual((gm.notes[0].pitch,gm.notes[0].ntype), (60,99))
        bad = track([Note(80,80,0,100,0)], instrument=13)
        with self.assertRaises(ValueError):
            session([bad], Action.ADAPT, source_track_id=1, melody_instrument=13, drums_are_gm=True)
        self.assertEqual(bad.notes[0].pitch,80)

    def test_expression_is_scoped_preserves_manual_articulation_and_is_idempotent(self):
        source = track([Note(60+i,80,i*500,430,0) for i in range(8)] + [Note(72,75,750,700,11)])
        other = track([Note(40,90,100,800,0)], track_id=2, instrument=14)
        brief = dict(source_track_id=1, bars=1, rewrite_velocity=True, shape_durations=True, character=MusicalCharacter.LIGHT)
        value = session([source, other], Action.EXPRESS, **brief)
        result = value.materialize(frozenset({"expression"}))
        self.assertEqual(result[1], other)
        self.assertEqual(result[0].notes[4:], source.notes[4:])
        self.assertEqual([(n.pitch,n.start,n.ntype) for n in result[0].notes], [(n.pitch,n.start,n.ntype) for n in source.notes])
        self.assertNotEqual(result[0].notes[:4], source.notes[:4])
        self.assertFalse(session(result, Action.EXPRESS, **brief).candidate.preview.operations)

    def test_default_expression_preserves_existing_dynamic_range(self):
        source = track([Note(60,45,0,400,0),Note(64,97,500,400,0),Note(67,70,1000,400,0)])
        value = session([source], Action.EXPRESS, source_track_id=1, bars=1)
        self.assertFalse(value.candidate.preview.operations)

    def test_clip_expression_preserves_sibling_and_hidden_authored_content(self):
        source = track([Note(60,80,0,300,0),Note(64,80,500,300,0),Note(67,80,1000,1200,0),Note(72,90,4000,300,0)],
            arrangement_clips=[ArrangementClipState("a",2000,4000,0,2000,2000),ArrangementClipState("b",8000,10000,4000,6000,4000)])
        before = deepcopy(source)
        context = CreationContext.capture([source],120,4)
        value = build_creation_session(context, CreationBrief(Action.EXPRESS, source_track_id=1, start_bar=1, bars=1, rewrite_velocity=True), "a")
        result = value.materialize(frozenset({"expression"}))[0]
        self.assertEqual(clip_editor_notes(result,"b"),clip_editor_notes(before,"b"))
        self.assertEqual(source,before)
        self.assertEqual(len(result.notes),len(before.notes))
        self.assertIn(Note(67,80,1000,1200,0),result.notes)
        self.assertNotEqual(clip_editor_notes(result,"a"),clip_editor_notes(before,"a"))

    def test_clip_expression_does_not_reset_track_duration_scale_or_change_siblings(self):
        for scale in (.75, 1.5):
            for shape in (False, True):
                with self.subTest(scale=scale, shape=shape):
                    source = track([Note(60,80,0,300,0), Note(64,80,500,300,0), Note(67,80,4000,300,0)],
                        duration_scale=scale, arrangement_clips=[
                            ArrangementClipState("a",0,2000,0,2000),
                            ArrangementClipState("b",4000,6000,4000,6000)])
                    before = deepcopy(source)
                    value = build_creation_session(CreationContext.capture([source],120,4),
                        CreationBrief(Action.EXPRESS,source_track_id=1,bars=1,
                                      rewrite_velocity=True,shape_durations=shape), "a")
                    result = value.materialize(frozenset({"expression"}))[0]
                    self.assertEqual(result.duration_scale, scale)
                    self.assertEqual(result.notes[-1], source.notes[-1])
                    self.assertEqual([n for n in project_track_notes(result) if n.start >= 4000],
                                     [n for n in project_track_notes(source) if n.start >= 4000])
                    self.assertNotEqual(result.notes[:2], source.notes[:2])
                    self.assertEqual(source, before)

    def test_transaction_guard_covers_clip_mixer_tempo_and_source_edits(self):
        source = track([Note(60,80,0,100,0)], arrangement_clips=[ArrangementClipState("a",0,2000,0,2000)])
        context = CreationContext.capture([source],120,4)
        context.assert_current([source],120,4)
        for kind in ("clip", "volume", "note", "tempo"):
            modified = deepcopy(source)
            bpm = 120
            if kind == "clip": modified.arrangement_clips[0] = replace(modified.arrangement_clips[0], time_offset_ms=100)
            if kind == "volume": modified.bdo_track_volume = 30
            if kind == "note": modified.notes[0] = modified.notes[0]._replace(vel=90)
            if kind == "tempo": bpm = 121
            with self.subTest(kind=kind), self.assertRaises(InvalidOptimizationPreview): context.assert_current([modified],bpm,4)

    def test_draft_exports_the_current_generated_model_losslessly(self):
        value = session(bars=16, character=MusicalCharacter.LIGHT)
        tracks = value.materialize(frozenset(p.key for p in value.candidate.parts))
        tracks[0].notes[0] = tracks[0].notes[0]._replace(vel=93)
        request = ExportRequest(direct_tracks=freeze_export_tracks(tracks), bpm=120,time_signature=4,
            out_path=Path("unused"),character_name="Test",owner_id=123,
            conversion=ConversionSettings.bdo_import_defaults(),pitch_plan=PitchTransformPlan(0),
            reverb=0,delay=0,chorus=None,game_dir=Path("unused-game"))
        payload = prepare_export(request).data
        document = decode_score(payload)
        actual = Counter((n.pitch,n.velocity_a,n.start_ms,n.duration_ms,n.ntype) for g in document.groups for t in g.tracks for n in t.notes)
        expected = Counter(tuple(n) for t in tracks for n in project_track_notes(t))
        self.assertEqual(actual,expected)
        self.assertEqual(encode_score(document),payload)
        self.assertTrue(all(not g.tracks[-1].notes for g in document.groups))
        self.assertTrue(all(len(t.notes)<=730 for g in document.groups for t in g.tracks))

    def test_feedback_is_bounded_optional_and_contains_no_score_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"choice.json"
            self.assertFalse(path.exists())
            record_choice(path,CreationBrief(Action.DRAFT,source_track_id=123456,start_bar=42),frozenset({"melody"}),"applied")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["outcome"],"applied")
            self.assertNotIn("123456",path.read_text())
            self.assertEqual(set(payload[0]),{"schema","engine","version","action","character","variant","minor","parts","outcome"})
            before = path.read_bytes()
            with self.assertRaises(ValueError): record_choice(path,CreationBrief(Action.DRAFT),frozenset(),"unknown")
            self.assertEqual(path.read_bytes(),before)

    def test_invalid_generation_intent_is_rejected_without_changes(self):
        with self.assertRaises(ValueError): CreationBrief(Action.DRAFT,bars=17)
        with self.assertRaises(ValueError): CreationContext.capture([],120,6,8)
        with self.assertRaises(ValueError): session([track([],instrument=13)],Action.ACCOMPANY,source_track_id=1)
        with self.assertRaises(InvalidOptimizationPreview): session(melody_instrument=999)


if __name__ == "__main__":
    unittest.main()
