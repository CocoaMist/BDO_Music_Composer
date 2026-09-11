from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import mido

from bdo_midi import (
    BDO_INSTRUMENTS,
    Note,
    gm_program_name,
    gm_to_bdo_instrument,
    map_drum_notes,
    parse_midi,
    plan_gm_to_bdo_instrument,
)


class MidiParserTests(unittest.TestCase):
    def _save(self, tracks: list[list[mido.Message | mido.MetaMessage]]) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "fixture.mid"
        midi = mido.MidiFile(type=1 if len(tracks) > 1 else 0, ticks_per_beat=480)
        for messages in tracks:
            track = mido.MidiTrack()
            track.extend(messages)
            midi.tracks.append(track)
        midi.save(path)
        return path

    def _save_raw_track(self, track_payload: bytes) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "raw-fixture.mid"
        header = b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xE0"
        track = b"MTrk" + len(track_payload).to_bytes(4, "big") + track_payload
        path.write_bytes(header + track)
        return path

    def test_terminal_out_of_range_data_byte_is_repaired_and_reported(self) -> None:
        path = self._save_raw_track(bytes((
            0x00, 0xB0, 0x07, 0xFF,
            0x00, 0x90, 0x3C, 0x64,
            0x83, 0x60, 0x80, 0x3C, 0x00,
            0x00, 0xFF, 0x2F, 0x00,
        )))
        original = path.read_bytes()

        parsed = parse_midi(
            path,
            include_controls=True,
            include_compatibility_repairs=True,
            allow_compatibility_repairs=True,
        )

        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(parsed[2][0][0]), 1)
        self.assertEqual(parsed[4][0][0]["value"], 127)
        repairs = parsed[5]
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0].count, 1)
        self.assertEqual(repairs[0].channels, (0,))
        self.assertEqual(repairs[0].event_types, ("control_change",))
        self.assertEqual(repairs[0].original_max, 255)

    def test_out_of_range_first_data_byte_remains_fail_closed(self) -> None:
        path = self._save_raw_track(bytes((
            0x00, 0xB0, 0xFF, 0x40,
            0x00, 0xFF, 0x2F, 0x00,
        )))

        with self.assertRaisesRegex(OSError, "data byte must be in range"):
            parse_midi(
                path,
                include_compatibility_repairs=True,
                allow_compatibility_repairs=True,
            )

    def test_default_tempo_and_note_on_zero(self) -> None:
        path = self._save([[
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=0, time=480),
        ]])
        bpm, meter, groups, tempo_count = parse_midi(path)
        self.assertEqual((bpm, meter, tempo_count), (120, 4, 1))
        self.assertAlmostEqual(groups[0][0][0].dur, 500.0)

    def test_program_changes_split_groups_and_channel_ten_is_percussion(self) -> None:
        path = self._save([[
            mido.Message("program_change", channel=0, program=40, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=120),
            mido.Message("program_change", channel=0, program=24, time=0),
            mido.Message("note_on", channel=0, note=64, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=64, velocity=0, time=120),
            mido.Message("program_change", channel=9, program=99, time=0),
            mido.Message("note_on", channel=9, note=36, velocity=100, time=0),
            mido.Message("note_off", channel=9, note=36, velocity=0, time=120),
        ]])
        groups = parse_midi(path)[2]
        self.assertEqual([(program, drums) for _notes, program, drums in groups], [
            (24, False), (40, False), (0, True),
        ])

    def test_repeated_note_closes_previous_voice(self) -> None:
        path = self._save([[
            mido.Message("note_on", channel=0, note=60, velocity=70, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=240),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=240),
        ]])
        notes = parse_midi(path)[2][0][0]
        self.assertEqual([note.vel for note in notes], [70, 90])
        self.assertEqual([round(note.dur) for note in notes], [250, 250])

    def test_sustain_extends_note_and_control_is_aligned(self) -> None:
        path = self._save([[
            mido.Message("control_change", channel=0, control=64, value=127, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=240),
            mido.Message("control_change", channel=0, control=64, value=0, time=240),
        ]])
        parsed = parse_midi(path, include_controls=True)
        self.assertAlmostEqual(parsed[2][0][0][0].dur, 500.0)
        self.assertEqual([event["value"] for event in parsed[4][0]], [127, 0])

    def test_controls_text_and_dangling_note_are_preserved(self) -> None:
        path = self._save([[
            mido.MetaMessage("lyrics", text="hello", time=0),
            mido.Message("pitchwheel", channel=0, pitch=1000, time=0),
            mido.Message("aftertouch", channel=0, value=60, time=0),
            mido.Message("polytouch", channel=0, note=62, value=50, time=0),
            mido.Message("note_on", channel=0, note=62, velocity=80, time=0),
        ]])
        parsed = parse_midi(path, include_controls=True, include_lyrics=True)
        self.assertEqual(parsed[2][0][0][0].dur, 100.0)
        self.assertEqual({event["kind"] for event in parsed[4][0]}, {
            "pitchwheel", "aftertouch", "polytouch",
        })
        self.assertEqual(parsed[5][0]["text"], "hello")

    def test_unreleased_sustain_uses_file_end_instead_of_short_fallback(self) -> None:
        path = self._save([[
            mido.Message("control_change", control=64, value=127, time=0),
            mido.Message("note_on", note=60, velocity=90, time=0),
            mido.Message("note_off", note=60, velocity=0, time=480),
            mido.MetaMessage("end_of_track", time=1440),
        ]])
        self.assertEqual(parse_midi(path, apply_sustain=False)[2][0][0][0].dur, 500.0)
        self.assertEqual(parse_midi(path, apply_sustain=True)[2][0][0][0].dur, 2000.0)

    def test_unfinished_note_preserves_short_known_end_time(self) -> None:
        path = self._save([[
            mido.Message("note_on", note=60, velocity=90, time=0),
            mido.MetaMessage("end_of_track", time=48),
        ]])
        self.assertEqual(parse_midi(path)[2][0][0][0].dur, 50.0)

    def test_duplicate_tempo_tick_uses_last_event_and_flatten_mode(self) -> None:
        path = self._save([[
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(90), time=0),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100), time=0),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(140), time=480),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=480),
        ]])
        self.assertEqual(parse_midi(path)[:2], (100, 4))
        self.assertEqual(parse_midi(path, flatten_tempo=True)[0], 200)
        self.assertEqual(parse_midi(path)[3], 2)

    def test_non_quarter_denominator_is_rejected(self) -> None:
        path = self._save([[
            mido.MetaMessage("time_signature", numerator=6, denominator=8, time=0),
        ]])
        with self.assertRaisesRegex(ValueError, "only supports a /4 meter"):
            parse_midi(path)

        bpm, numerator, groups, _tempo_count = parse_midi(
            path,
            require_quarter_denominator=False,
        )
        self.assertEqual((bpm, numerator, groups), (120, 6, []))

    def test_asynchronous_type_two_file_is_rejected(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "type2.mid"
        midi = mido.MidiFile(type=2, ticks_per_beat=480)
        midi.tracks.append(mido.MidiTrack())
        midi.tracks.append(mido.MidiTrack())
        midi.save(path)
        with self.assertRaisesRegex(ValueError, "asynchronous tracks"):
            parse_midi(path)

    def test_group_evidence_preserves_bank_names_dialect_and_drum_kit(self) -> None:
        path = self._save([[
            mido.MetaMessage("track_name", name="Electric Piano Layer", time=0),
            mido.MetaMessage("instrument_name", name="DX EP", time=0),
            mido.Message("sysex", data=(0x7E, 0x7F, 0x09, 0x03), time=0),
            mido.Message("control_change", channel=0, control=0, value=8, time=0),
            mido.Message("control_change", channel=0, control=32, value=2, time=0),
            mido.Message("program_change", channel=0, program=4, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=120),
            mido.Message("program_change", channel=9, program=25, time=0),
            mido.Message("note_on", channel=9, note=36, velocity=90, time=0),
            mido.Message("note_off", channel=9, note=36, velocity=0, time=120),
        ]])

        parsed = parse_midi(path, include_group_evidence=True)
        evidence = parsed[4]

        melodic = next(item for item in evidence if item.channel == 0)
        drums = next(item for item in evidence if item.channel == 9)
        self.assertEqual((melodic.bank_msb, melodic.bank_lsb), (8, 2))
        self.assertEqual(melodic.track_names, ("Electric Piano Layer",))
        self.assertEqual(melodic.instrument_names, ("DX EP",))
        self.assertEqual(melodic.midi_dialect, "GM2")
        self.assertEqual(drums.source_program, 25)

    def test_same_program_in_different_banks_stays_in_separate_groups(self) -> None:
        path = self._save([[
            mido.Message("program_change", channel=0, program=4, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=120),
            mido.Message("control_change", channel=0, control=0, value=1, time=0),
            mido.Message("note_on", channel=0, note=64, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=64, velocity=0, time=120),
        ]])
        parsed = parse_midi(path, include_group_evidence=True)
        self.assertEqual(len(parsed[2]), 2)
        self.assertEqual([item.bank_msb for item in parsed[4]], [0, 1])


class MidiMappingTests(unittest.TestCase):
    def test_every_gm_program_has_a_name_and_deterministic_mapping(self) -> None:
        for program in range(128):
            self.assertNotEqual(gm_program_name(program), f"Program {program}")
            self.assertEqual(
                gm_to_bdo_instrument(program),
                gm_to_bdo_instrument(program),
            )
            self.assertIn(gm_to_bdo_instrument(program), BDO_INSTRUMENTS.values())

    def test_pitched_timpani_never_maps_to_drum_pitch_semantics(self) -> None:
        plan = plan_gm_to_bdo_instrument(47, pitches=(36, 48, 60))
        self.assertNotEqual(plan.instrument_id, BDO_INSTRUMENTS["drum_set"])

    def test_synth_families_select_marnian_modes_and_fx_are_explicitly_unsupported(self) -> None:
        square = plan_gm_to_bdo_instrument(80)
        saw = plan_gm_to_bdo_instrument(81)
        pad = plan_gm_to_bdo_instrument(89)
        sound_fx = plan_gm_to_bdo_instrument(120)
        self.assertEqual(square.instrument_id, BDO_INSTRUMENTS["marnian_secret"])
        self.assertEqual(saw.instrument_id, BDO_INSTRUMENTS["marnian_wavy"])
        self.assertEqual(pad.marnian_mode, "stereo")
        self.assertEqual(sound_fx.disposition, "unsupported")

    def test_pitch_coverage_overrides_a_timbre_candidate_that_cannot_play_notes(self) -> None:
        plan = plan_gm_to_bdo_instrument(
            112,
            pitches=(48, 72),
            pitch_support=lambda instrument_id, pitch: (
                instrument_id == BDO_INSTRUMENTS["piano"]
            ),
        )
        self.assertEqual(plan.instrument_id, BDO_INSTRUMENTS["piano"])

    def test_canonical_drum_is_not_remapped(self) -> None:
        mapped = map_drum_notes([Note(48, 90, 0.0, 120.0, 99)])
        self.assertEqual((mapped[0].pitch, mapped[0].ntype), (48, 99))

    def test_unmapped_gm_drum_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "General MIDI drum pitch 62 has no BDO mapping",
        ):
            map_drum_notes([Note(62, 90, 0.0, 120.0, 0)])

    def test_unmapped_gm_drum_uses_only_an_explicit_canonical_fallback(self) -> None:
        mapped = map_drum_notes(
            [Note(75, 90, 0.0, 120.0, 0)],
            unmapped_fallback_pitch=50,
        )

        self.assertEqual(
            (mapped[0].pitch, mapped[0].dur, mapped[0].ntype),
            (50, 80.0, 99),
        )


if __name__ == "__main__":
    unittest.main()
