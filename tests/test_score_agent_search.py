"""Regression checks for the score agent's fixed-origin search transport."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from bdo_music_composer.app.score_agent_settings import DEFAULT_BASE_URL, DEFAULT_MODEL, ModelConnection
from bdo_music_composer.ui import score_agent_search_qt as search


class ScoreAgentSearchTests(unittest.TestCase):
    def test_results_are_bounded_public_plain_text(self) -> None:
        rows = [
            {"url": "javascript:alert(1)"},
            {"url": "https://user@example.org/private"},
            {"url": "https://127.1/private"},
            {"url": "https://scores.local/private"},
            {"url": "https://Example.ORG/notes?x=a%20b#p", "title": "<b>和声</b>",
             "snippet": "正文 <code>code</code> `private` <script>ignored</script> &amp; 例子\u202e",
             "site_name": "Test News", "content": "not included"},
            {"url": "https://example.org/notes?x=a%20b#p", "title": "duplicate"},
        ] + [{"url": f"https://example.org/{index}", "summary": "a" * 350} for index in range(6)]
        result = search._search_results(json.dumps({"results": rows}, ensure_ascii=False).encode())
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0], {
            "url": "https://example.org/notes?x=a%20b#p", "title": "和声", "snippet": "正文 & 例子",
            "site_name": "Test News", "date": "",
        })
        self.assertEqual(result[1]["title"], "example.org")
        self.assertEqual(result[1]["snippet"], "a" * 320)
        self.assertEqual(search._search_results(b'{"results":[]}'), [])
        with self.assertRaises(ValueError):
            search._search_results(b'{"error":{"message":"untrusted"}}')

    def test_fixed_origin_and_redirect_never_follow(self) -> None:
        with patch.multiple(search, QNetworkAccessManager=Mock(), QTimer=Mock()):
            other = search.DeepSeekWebSearch(ModelConnection("https://models.example.org", DEFAULT_MODEL, "test-key"))
            failures = []
            other.failed.connect(failures.append)
            other.start("music theory")
            self.assertEqual(failures, ["search_unavailable"])
            other._manager.post.assert_not_called()

        with patch.multiple(search, QNetworkAccessManager=Mock(), QTimer=Mock()):
            official = search.DeepSeekWebSearch(ModelConnection(DEFAULT_BASE_URL, DEFAULT_MODEL, "test-key"))
            failures = []
            official.failed.connect(failures.append)
            official.start("谱" * 129)
            self.assertEqual(failures, ["invalid_search_query"])
            official._manager.post.assert_not_called()

            official.start("  乐理\n转位  ")
            request, payload = official._manager.post.call_args.args
            self.assertEqual(request.url().toString(), "https://api.deepseek.com/v1/tools/search")
            self.assertEqual(request.attribute(search.QNetworkRequest.Attribute.RedirectPolicyAttribute),
                             search.QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            self.assertEqual(bytes(request.rawHeader("Authorization")), b"Bearer test-key")
            self.assertEqual(json.loads(payload), {"query": "乐理 转位", "count": 5, "need_content": False})
            reply = official._manager.post.return_value
            reply.attribute.return_value = 302
            reply.isFinished.return_value = False
            official._read(reply)
            official._finish(reply)
            self.assertEqual(failures, ["invalid_search_query", "redirected"])
            official._manager.post.assert_called_once()
            reply.readAll.assert_not_called()
            reply.abort.assert_called_once()

    def test_search_completion_and_abort_ignore_late_reply(self) -> None:
        with patch.multiple(search, QNetworkAccessManager=Mock(), QTimer=Mock()):
            lookup = search.DeepSeekWebSearch(ModelConnection(DEFAULT_BASE_URL, DEFAULT_MODEL, "test-key"))
            replies = []
            lookup.succeeded.connect(replies.append)
            lookup.start("music theory")
            reply = lookup._manager.post.return_value
            reply.attribute.return_value = 200
            reply.isFinished.return_value = True
            reply.error.return_value = search.QNetworkReply.NetworkError.NoError
            reply.readAll.side_effect = [b'{"results":', b'[]}']
            lookup._read(reply)
            lookup._finish(reply)
            self.assertEqual(replies, [[]])
            lookup.start("counterpoint")
            lookup.abort()
            lookup._finish(reply)
            self.assertEqual(replies, [[]])
