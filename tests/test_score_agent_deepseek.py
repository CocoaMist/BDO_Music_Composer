"""Official DeepSeek request, saved-profile and streamed-tool regressions."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication

from bdo_music_composer.app import score_agent_settings as settings
from bdo_music_composer.creation.score_agent_tools import is_read_only_request
from bdo_music_composer.ui import score_agent_model_qt as transport
from bdo_music_composer.ui.score_agent_catalog_qt import catalog_model_ids
from bdo_music_composer.ui.score_agent_qt import MAX_REPLY_LENGTH, ScoreAgent, _ToolBatch


_FAKE_KEY = "synthetic-test-key"


def _event(delta: dict, finish_reason: str | None = None) -> bytes:
    return b"data: " + json.dumps({
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }, ensure_ascii=False).encode() + b"\n\n"


class DeepSeekConnectionTests(unittest.TestCase):
    def test_model_catalog_preserves_exact_selectable_ids(self) -> None:
        payload = json.dumps({"data": [
            {"id": "qwen3:8b"}, {"id": "vendor/Model"}, {"id": "vendor/model"},
            {"id": "qwen3:8b"}, {"id": " name "}, {"id": "x" * 257}, {"id": "\n"},
            {"unexpected": "metadata"},
        ]}).encode()
        self.assertEqual(catalog_model_ids(payload), ("qwen3:8b", "vendor/Model", "vendor/model"))
        self.assertEqual(catalog_model_ids(b'{"data":[]}'), ())
        self.assertIsNone(catalog_model_ids(b'{"data":[{"id":false}]}'))
        self.assertIsNone(catalog_model_ids(b'{"error":"unauthorized"}'))

    def test_catalog_and_chat_urls_resolve_to_the_same_custom_base(self) -> None:
        full_url = "https://models.example.org/gateway/openai/v2"
        for suffix in ("", "/models", "/chat/completions/"):
            with self.subTest(suffix=suffix):
                self.assertEqual(settings.normalize_base_url(full_url + suffix), full_url)
        for path in ("/", "/models", "/chat/completions"):
            with self.subTest(path=path):
                self.assertEqual(settings.normalize_base_url("https://models.example.org" + path), "https://models.example.org/")
        local = settings.ModelConnection("http://127.0.0.1:11434", "qwen3:8b", "")
        self.assertEqual(local.base_url, "http://127.0.0.1:11434/v1")
        self.assertTrue(local.is_loopback)

    def test_model_and_effort_from_environment(self) -> None:
        connection = settings.model_connection_from_environment({
            "DEEPSEEK_API_KEY": _FAKE_KEY,
            "BDO_AGENT_MODEL": "deepseek-v4-pro",
            "BDO_AGENT_REASONING_EFFORT": "max",
        })
        self.assertEqual(
            connection, settings.ModelConnection(settings.DEFAULT_BASE_URL, "deepseek-v4-pro", _FAKE_KEY, True, "max")
        )
        self.assertNotIn(_FAKE_KEY, repr(connection))
        disabled = settings.model_connection_from_environment({
            "DEEPSEEK_API_KEY": _FAKE_KEY,
            "BDO_AGENT_MODEL": "deepseek-reasoner",
            "BDO_AGENT_REASONING_EFFORT": "none",
        })
        self.assertEqual(disabled.model, settings.DEFAULT_MODEL)
        self.assertFalse(disabled.thinking)

    def test_saved_legacy_profile_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            settings, can_remember_model_connection=lambda: True,
            _dpapi=lambda data, *, encrypt: data,
        ):
            path = Path(directory) / "fixture.dpapi"
            path.write_text(json.dumps({
                "schema": "bdo.score_agent.connection.v1", "model": "deepseek-reasoner",
                "base_url": settings.DEFAULT_BASE_URL, "api_key": _FAKE_KEY,
            }), encoding="utf-8")
            legacy = settings.load_saved_model_connection(path)
            self.assertEqual(legacy.model, settings.DEFAULT_MODEL)
            self.assertTrue(legacy.thinking)
            picked = settings.ModelConnection(legacy.base_url, "deepseek-v4-pro", _FAKE_KEY, True, "low")
            settings.save_model_connection(picked, path)
            self.assertEqual(settings.load_saved_model_connection(path), picked)

    def test_official_effort_and_tool_history_only(self) -> None:
        messages = [
            {"role": "assistant", "content": "Previous answer", "reasoning_content": "original reasoning"},
            {"role": "assistant", "content": "Another answer"},
        ]
        tools = [{"type": "function"}]
        for effort in settings.DEEPSEEK_REASONING_EFFORTS:
            with self.subTest(effort=effort):
                official = settings.ModelConnection(
                    "https://api.deepseek.com/v1", "deepseek-v4-flash", _FAKE_KEY, True, effort,
                )
                body = transport._request_body(official, messages, tools)
                self.assertEqual(body["thinking"], {"type": "enabled"})
                self.assertEqual(body["reasoning_effort"], effort)
                self.assertEqual(body["model"], settings.DEFAULT_MODEL)
                self.assertEqual(body["messages"][0]["reasoning_content"], "original reasoning")
                self.assertEqual(body["messages"][1]["reasoning_content"], "")
                self.assertNotIn("reasoning_content", transport._request_body(official, messages, [])["messages"][0])

        quick = settings.ModelConnection(settings.DEFAULT_BASE_URL, settings.DEFAULT_MODEL, _FAKE_KEY)
        quick_body = transport._request_body(quick, messages, tools)
        self.assertEqual(quick_body["thinking"], {"type": "disabled"})
        self.assertEqual(quick_body["max_tokens"], 768)
        self.assertGreater(body["max_tokens"], quick_body["max_tokens"])
        other = settings.ModelConnection("https://models.example.org", "deepseek-v4-flash", _FAKE_KEY, True, "max")
        body = transport._request_body(other, messages, tools)
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertNotIn("reasoning_effort", body)
        self.assertNotIn("thinking", body)
        self.assertNotIn("reasoning_content", body["messages"][0])


class DeepSeekStreamTests(unittest.TestCase):
    def test_read_only_review_and_deferred_writes_do_not_stage_edits(self) -> None:
        for instruction in (
            "只审阅第2–3小节的力度表现。",
            "查看第2小节，写一段文字说明力度为什么一直是72。",
            "把第一小节力度减弱但不写入工程。",
            "把力度加一点。先别改谱，只告诉我会怎样。",
            "刚才你调整了哪些小节？",
            "Adjust the first bar but do not actually apply these changes yet.",
            "把全轨力度压低10%会好听一些吗？",
            "先把拉弦降八度是否更合适，别真的动曲谱。",
            "给我配器建议，有没有必要把木管整体移调？",
            "把三个同时响的音自动连成滑音，乐理上靠谱吗？",
            "把力度压低10%，只给方案。",
        ):
            self.assertTrue(is_read_only_request(instruction), instruction)
        for instruction in (
            "请对照参考音频，把第3小节的力度调整得更有推动感。",
            "请不要修改第2小节，只把第3小节的力度改强一点。",
            "先检查第2小节，然后把第3小节的力度改强一点。",
            "照刚才的范围，把力度再降10%。",
            "能不能把第3小节的力度压低10%？",
        ):
            self.assertFalse(is_read_only_request(instruction), instruction)

    def test_web_turn_cannot_replay_or_change_local_score_history(self) -> None:
        app = QCoreApplication.instance() or QCoreApplication([])
        agent = ScoreAgent(app)
        connection = settings.ModelConnection(settings.DEFAULT_BASE_URL, settings.DEFAULT_MODEL, _FAKE_KEY, True, "low")
        tools = Mock()
        tools.scope_summary.return_value = {"available_actions": ["express"], "reference_audio": "missing", "track": {}}
        with patch.object(agent, "_next"):
            agent.start("调整第2小节的力度", connection, tools, "zh-CN")
            agent._remember_turn({"role": "assistant", "content": "local-text", "reasoning_content": "local-thinking"}, "local-text")
            agent.abort()
            agent.start("联网搜索 副属和弦教材", connection, tools, "zh-CN")
            self.assertEqual(agent._web_query, "副属和弦教材")
            offered = {schema["function"]["name"] for schema in agent._offered_tools}
            self.assertIn("search_web", offered)
            self.assertNotIn("creative_plan", offered)
            self.assertNotIn("inspect_reference_audio", offered)
            self.assertEqual(len(agent._messages), 2)
            agent._remember_turn({"role": "assistant", "content": "untrusted-web-text"}, "untrusted-web-text")
            agent.abort()
            agent.start("调整第3小节的力度", connection, tools, "zh-CN")
            self.assertIn("local-thinking", json.dumps(agent._messages))
            self.assertNotIn("untrusted-web-text", json.dumps(agent._messages))
            self.assertNotIn("search_web", {schema["function"]["name"] for schema in agent._offered_tools})
            agent.abort()

    def test_score_agent_limits_visible_text_only(self) -> None:
        agent = ScoreAgent()
        emitted = []
        agent.delta.connect(emitted.append)
        limit = MAX_REPLY_LENGTH
        first = "谱" * (limit - 2)
        agent._publish_delta(first)
        agent._publish_delta("段落")
        agent._publish_delta("其余内容")
        self.assertEqual(emitted, [first, "段…"])
        self.assertEqual(len("".join(emitted)), limit)

    def test_general_question_prefetches_grounded_theory_without_score_reads(self) -> None:
        app = QCoreApplication.instance() or QCoreApplication([])
        agent = ScoreAgent(app)
        connection = settings.ModelConnection(settings.DEFAULT_BASE_URL, settings.DEFAULT_MODEL, _FAKE_KEY)
        tools = Mock()
        tools.scope_summary.return_value = {"available_actions": ["draft"], "reference_audio": "missing", "track": None}
        with patch.object(agent, "_next"):
            agent.start("MIDI 力度从80变90，听起来会更响12.5%吗？", connection, tools, "zh-CN")
            self.assertIn('"id":"dynamics-and-timing"', agent._messages[0]["content"])
            self.assertFalse(agent._allow_plan)
            tools.call.assert_not_called()
            agent.abort()
            agent.start("联网搜索 MIDI 力度与响度", connection, tools, "zh-CN")
            self.assertNotIn("本轮本地乐理资料：", agent._messages[0]["content"])
            agent.abort()

    def test_followup_uses_commit_receipt_and_fresh_evidence(self) -> None:
        app = QCoreApplication.instance() or QCoreApplication([])
        agent = ScoreAgent(app)
        connection = settings.ModelConnection(settings.DEFAULT_BASE_URL, settings.DEFAULT_MODEL, _FAKE_KEY, True, "low")
        tools = Mock()
        tools.scope_summary.return_value = {"available_actions": ["express"], "reference_audio": "missing", "track": {}}
        current_edit = {"action": "express", "first_bar": 3, "bars": 1, "velocity_scale_percent": 90}
        with patch.object(agent, "_next"):
            agent.start("调低力度", connection, tools, "zh-CN", scope_key=("project", 8))
            agent._remember_turn({"role": "assistant", "content": "old-evidence", "reasoning_content": "old-reasoning"}, "old-evidence")
            agent.abort()
            agent.start("刚才你改了什么？", connection, tools, "zh-CN", scope_key=("project", 9), latest_edit=current_edit)
            messages = json.dumps(agent._messages)
            self.assertIn('"velocity_scale_percent":90', agent._messages[0]["content"])
            self.assertNotIn("old-evidence", messages)
            self.assertNotIn("old-reasoning", messages)
            self.assertFalse(agent._allow_plan)
            agent.abort()
            agent.start("联网搜索 力度处理", connection, tools, "zh-CN", scope_key=("project", 9), latest_edit=current_edit)
            self.assertNotIn('"velocity_scale_percent":90', agent._messages[0]["content"])
            agent.abort()

    def test_repeat_reads_reference_same_turn_success_and_recompute_new_ranges(self) -> None:
        tools = Mock(first_bar=2, bars=3)
        tools.call.return_value = {"note_count": 20}
        read_ids = {}
        first = _ToolBatch(tools, [], allow_plan=False, read_ids=read_ids)
        self.assertEqual(json.loads(first._call_content("inspect_music", "{}", "first")), {"note_count": 20})
        second = _ToolBatch(tools, [], allow_plan=False, read_ids=read_ids)
        self.assertEqual(json.loads(second._call_content("inspect_music", '{"bars":3,"first_bar":2}', "next")), {
            "status": "already_available", "previous_tool_call_id": "first",
        })
        self.assertEqual(tools.call.call_count, 1)
        second._call_content("inspect_music", '{"first_bar":2,"bars":1}', "different")
        fresh = _ToolBatch(tools, [], allow_plan=False, read_ids={})
        fresh._call_content("inspect_music", "{}", "fresh")
        self.assertEqual(tools.call.call_count, 3)

    def test_keeps_thinking_private_and_completes_split_tool_call(self) -> None:
        stream = transport._ChatStream()
        data = b": keep-alive\r\n\r\n" + _event({
            "reasoning_content": "乐理上下文",
            "tool_calls": [{"index": 0, "id": "call-inspect", "function": {"name": "inspect_music", "arguments": "{"}}],
        })
        split = data.index("乐".encode()) + 1
        self.assertEqual(stream.feed(data[:split]), "")
        self.assertEqual(stream.feed(data[split:]), "")
        self.assertEqual(stream.feed(
            _event({"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]}, "tool_calls")
            + b"data: [DONE]\n\n"
        ), "")
        result = stream.message()
        self.assertEqual(result["reasoning_content"], "乐理上下文")
        self.assertEqual(result["tool_calls"][0]["function"]["arguments"], "{}")

    def test_thinking_wire_budget_handles_sse_per_reasoning_token(self) -> None:
        chunk = _event({"reasoning_content": "理"}).replace(b'data: {', b'data: {"id":"' + b"x" * 170 + b'",')
        thinking = transport._ChatStream(wire_limit=transport._MAX_THINKING_STREAM_BYTES)
        batch = chunk * 256
        for _ in range(128):
            self.assertEqual(thinking.feed(batch), "")
        thinking.feed(_event({"content": "完成"}, "stop") + b"data: [DONE]\n\n")
        self.assertEqual(thinking.message()["reasoning_content"], "理" * 32_768)

        quick = transport._ChatStream()
        with self.assertRaisesRegex(ValueError, "Model stream exceeds its size limit"):
            quick.feed(batch * (transport._MAX_STREAM_BYTES // len(batch) + 1))
        with self.assertRaisesRegex(ValueError, "Model event exceeds its size limit"):
            transport._ChatStream(wire_limit=transport._MAX_THINKING_STREAM_BYTES).feed(
                b"data: " + b"x" * transport._MAX_EVENT_BYTES + b"\n\n",
            )

    def test_only_official_stream_reports_numeric_usage_outside_message(self) -> None:
        completion = {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 24, "completion_tokens": 9, "total_tokens": 33,
                "prompt_tokens_details": {"cached_tokens": 16}, "prompt_cache_miss_tokens": 8,
                "completion_tokens_details": {"reasoning_tokens": 3, "other": "ignore"},
                "unknown": "ignore",
            },
        }
        response = _event({"content": "完成"}) + b"data: " + json.dumps(completion).encode() + b"\n\ndata: [DONE]\n\n"
        expected = {
            "prompt_tokens": 24, "completion_tokens": 9, "total_tokens": 33,
            "prompt_cache_hit_tokens": 16, "prompt_cache_miss_tokens": 8, "reasoning_tokens": 3,
        }
        for origin in (settings.DEFAULT_BASE_URL, "https://models.example.org"):
            with self.subTest(origin=origin), patch.multiple(transport, QNetworkAccessManager=Mock(), QTimer=Mock()):
                connection = settings.ModelConnection(origin, settings.DEFAULT_MODEL, _FAKE_KEY, True, "max")
                request = transport.ModelRequest(connection)
                reply = request._manager.post.return_value
                reply.attribute.return_value = 200
                reply.error.return_value = transport.QNetworkReply.NetworkError.NoError
                reply.isFinished.return_value = True
                reply.readAll.return_value = response
                usage, messages = [], []
                request.usage_received.connect(usage.append)
                request.succeeded.connect(messages.append)
                request.start([], [])
                self.assertEqual(request._stream._wire_limit,
                                 transport._MAX_THINKING_STREAM_BYTES if connection.is_official_deepseek
                                 else transport._MAX_STREAM_BYTES)
                request._finish(reply)
                self.assertEqual(usage, [expected] if connection.is_official_deepseek else [])
                self.assertEqual(messages, [{"role": "assistant", "content": "完成"}])

        self.assertEqual(transport._token_usage({
            "prompt_tokens": True, "completion_tokens": "9", "total_tokens": -1,
            "prompt_cache_hit_tokens": 0, "completion_tokens_details": {"reasoning_tokens": 2.5},
        }), {"prompt_cache_hit_tokens": 0})

    def test_provider_interruption_preserves_only_public_partial_text(self) -> None:
        stream = transport._ChatStream()
        public = stream.feed(
            _event({"content": "Partial"})
            + b'data: {"error":{"type":"api_error","message":"untrusted"}, "choices":[]}\n\n'
        )
        self.assertEqual(public, "Partial")
        self.assertEqual(stream.provider_error, "service_unavailable")
        with self.assertRaisesRegex(transport._ProviderResponseError, "^service_unavailable$"):
            stream.message()

    def test_unsafe_or_incomplete_finish_never_returns_tool_calls(self) -> None:
        for finish, code in (
            ("length", "response_truncated"), ("content_filter", "content_filtered"),
            ("insufficient_system_resource", "service_unavailable"),
        ):
            with self.subTest(finish=finish):
                stream = transport._ChatStream()
                stream.feed(_event({}, finish) + b"data: [DONE]\n\n")
                with self.assertRaisesRegex(transport._ProviderResponseError, f"^{code}$"):
                    stream.message()
