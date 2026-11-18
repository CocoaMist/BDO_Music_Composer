"""Lookup stays local, bounded, and grounded in attributed theory notes."""

import unittest

from bdo_music_composer.creation.score_theory_library import (
    MAX_THEORY_MATCHES,
    MAX_THEORY_QUERY_LENGTH,
    search_music_theory,
)


class ScoreTheoryLibraryTests(unittest.TestCase):
    def test_chinese_and_english_terms_reach_specific_topics(self) -> None:
        for query, expected in (
            ("和弦外音怎么处理", "nonchord-tones"),
            ("How does a half cadence work?", "cadence-and-phrase"),
            ("解释副属和弦并举例", "secondary-dominants"),
            ("MIDI velocity quantization", "dynamics-and-timing"),
            ("ＢＤＯ ６／８ 拍号", "meter-and-groove"),
        ):
            with self.subTest(query=query):
                result = search_music_theory(query, limit=1)
                self.assertEqual(result["coverage"], "local_music_theory")
                self.assertEqual(result["matches"][0]["id"], expected)

    def test_source_metadata_is_available_without_a_match_fallback(self) -> None:
        local = search_music_theory("黑沙导出校验", limit=1)["matches"][0]
        self.assertEqual(local["source"]["path"], "docs/BDO_COMPOSITION_AUTHORING.md")
        outside = search_music_theory("passing tone", limit=1)["matches"][0]
        self.assertTrue(outside["source"]["url"].startswith("https://musictheory.pugetsound.edu/"))
        self.assertEqual(search_music_theory("QQQ404ZZZ")["matches"], [])

    def test_mixed_terms_choose_music_topic_over_game_context(self) -> None:
        for query, expected in (
            ("黑色沙漠 BDO 游戏曲谱导出时，怎么写副属和弦", "secondary-dominants"),
            ("BDO 编曲 V⁷ ⁄ V怎么解决", "secondary-dominants"),
            ("在 C 大调放进 ♭VI 属于什么", "modal-mixture"),
            ("non-chord tones and suspensions", "nonchord-tones"),
            ("低音线用 slash chords", "chord-construction"),
            ("voice-leading调式和声", "chord-voicing"),
        ):
            with self.subTest(query=query):
                matches = search_music_theory(query, limit=1)["matches"]
                self.assertEqual([item["id"] for item in matches], [expected])

    def test_mixture_and_applied_dominants_have_separate_evidence(self) -> None:
        matches = search_music_theory("调式借用和 V7/V 有什么区别", limit=2)["matches"]
        by_id = {match["id"]: match for match in matches}
        self.assertEqual(set(by_id), {"modal-mixture", "secondary-dominants"})
        mixture, applied = by_id["modal-mixture"], by_id["secondary-dominants"]
        self.assertIn("Fm", mixture["practice"])
        self.assertTrue(mixture["source"]["url"].endswith("/modal-mixture/"))
        self.assertIn("D7–G–C", applied["practice"])
        self.assertTrue(applied["source"]["url"].endswith("/tonicization/"))

    def test_real_arranging_questions_rank_the_target_reference_first(self) -> None:
        for query, expected in (
            ("伴奏低音区发糊，左手 C2–E2–G2，贝斯也在弹 C2。", "low-register-clarity"),
            ("主旋律音符很密，和弦伴奏盖住主旋律，如何让出来？", "texture-and-arranging"),
            ("只有旋律 C、E、G、A，怎么选第一个和弦？", "melody-first-harmonization"),
            ("换成音域更窄的乐器，单独折八度等于整轨移调吗？", "instrument-transposition"),
            ("参考录音第2小节晚120ms，第3小节晚160ms。整首音频要前移吗？", "reference-audio-alignment"),
            ("GM MIDI 的鼓键 48 在黑沙也是同一鼓件吗？", "sustain-and-drum-rolls"),
            ("MIDI 力度从80变90，听感一定会响12.5%吗？", "dynamics-and-timing"),
            ("长音横跨小节线，可以当作第二小节新起音吗？", "reference-audio-alignment"),
        ):
            with self.subTest(query=query):
                matches = search_music_theory(query, limit=1)["matches"]
                self.assertEqual([item["id"] for item in matches], [expected])

    def test_rejects_invalid_input_and_limits_fresh_results(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_theory_query"):
            search_music_theory("乐理" * MAX_THEORY_QUERY_LENGTH)
        for limit in (True, 0, MAX_THEORY_MATCHES + 1):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "invalid_theory_limit"):
                search_music_theory("乐句", limit=limit)
        query = "和弦 乐句 终止 切分 力度 黑沙 配器 踏板"
        result = search_music_theory(query, limit=2)
        self.assertEqual(len(result["matches"]), 2)
        result["matches"].clear()
        self.assertEqual(len(search_music_theory(query, limit=2)["matches"]), 2)
