"""Smoke tests for report rendering and the local server's guards.

Neither had any coverage. The report is the product's only output, so a crash
there fails everything; the server writes tokens and accepts a city string, so
its input handling is worth pinning down.
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyze import analyse  # noqa: E402
from src.report import render  # noqa: E402
from src.webapp import _Handler  # noqa: E402


class ReportRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = analyse(mode="demo")
        cls.html = render(cls.data)

    def test_document_is_complete(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertTrue(self.html.rstrip().endswith("</html>"))

    def test_no_unrendered_placeholders(self):
        for bad in ("None", "undefined", "nan", "Traceback", "object at 0x"):
            self.assertNotIn(bad, self.html, f"报告里出现了未处理的 {bad}")

    def test_key_sections_present(self):
        for heading in ("积分健康分", "兑换性价比排行", "抽奖期望值拆解", "行动清单"):
            self.assertIn(heading, self.html)

    def test_css_rules_not_lost(self):
        """A stale-CSS cleanup once deleted .alert/.grid/.card wholesale, which
        dumped the alerts as bare text. Guard the class rules explicitly."""
        for rule in (".alert{", ".grid{", ".card{", ".hero{", ".fact{"):
            self.assertIn(rule, self.html, f"缺少样式规则 {rule}")

    def test_divs_are_balanced(self):
        self.assertEqual(self.html.count("<div"), self.html.count("</div>"))

    def test_user_content_is_escaped(self):
        """Product names come from an external API and land in HTML."""
        data = analyse(mode="demo")
        data.redemptions[0].name = '<script>alert(1)</script>'
        out = render(data)
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)


class LocalServerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_index_served(self):
        body = urllib.request.urlopen(self._url("/"), timeout=10).read().decode()
        self.assertIn("麦麦积分清算局", body)

    def test_status_returns_json(self):
        data = json.loads(urllib.request.urlopen(self._url("/api/status"), timeout=10).read())
        self.assertIn("configured", data)

    def test_cross_site_post_is_rejected(self):
        """A page the user visits must not be able to plant a token."""
        req = urllib.request.Request(
            self._url("/api/token"),
            data=json.dumps({"token": "ATTACKERTOKEN123"}).encode(),
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 403)

    def test_same_origin_post_is_allowed(self):
        req = urllib.request.Request(
            self._url("/api/token"),
            data=json.dumps({"token": "short"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{self.port}",
            },
            method="POST",
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        # Reaches the validator (and is rejected for being too short) rather
        # than being blocked by the origin guard.
        self.assertFalse(data["ok"])

    def test_oversized_body_is_ignored(self):
        big = json.dumps({"token": "x" * 200_000}).encode()
        req = urllib.request.Request(
            self._url("/api/token"), data=big,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self.assertFalse(data["ok"])

    def test_unknown_route_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self._url("/nope"), timeout=10)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
