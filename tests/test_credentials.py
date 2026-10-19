"""Tests for src/credentials.py and src/storytelling.py."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import credentials  # noqa: E402
from src.storytelling import PLAIN_GLOSSARY, health_score, money_analogy, plain_summary  # noqa: E402


class TokenValidationTests(unittest.TestCase):
    def test_short_value_rejected(self):
        self.assertFalse(credentials.looks_like_token("abc"))

    def test_value_with_space_rejected(self):
        """A pasted URL or a stray line must not be written to disk."""
        self.assertFalse(credentials.looks_like_token("abc def ghij"))

    def test_plausible_token_accepted(self):
        self.assertTrue(credentials.looks_like_token("FAKE_TOKEN_FOR_TESTS_ONLY_123456"))

    def test_empty_rejected(self):
        self.assertFalse(credentials.looks_like_token(""))


class TokenStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.orig = credentials.token_path
        credentials.token_path = lambda: self.root / "token"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, credentials, "token_path", self.orig)

    def test_roundtrip(self):
        credentials.save_token("TESTFAKETOKEN123")
        self.assertEqual(credentials.load_token(), "TESTFAKETOKEN123")

    def test_clear(self):
        credentials.save_token("TESTFAKETOKEN123")
        self.assertTrue(credentials.clear_token())
        self.assertIsNone(credentials.load_token())

    def test_clear_when_absent(self):
        self.assertFalse(credentials.clear_token())

    def test_status_without_token(self):
        ok, _path, source = credentials.token_status()
        if not ok:
            self.assertIsNone(source)

    def test_saved_token_is_reported(self):
        credentials.save_token("TESTFAKETOKEN123")
        ok, path, source = credentials.token_status()
        self.assertTrue(ok)
        self.assertIsNotNone(source)


class MoneyAnalogyTests(unittest.TestCase):
    ITEMS = [("甜筒", 5.0), ("巨无霸", 26.0), ("麦旋风", 15.0)]

    def test_picks_a_human_scale_item(self):
        """¥10 should read as "2 甜筒", not "0.4 巨无霸"."""
        text = money_analogy(10.0, self.ITEMS)
        self.assertIn("甜筒", text)
        self.assertIn("2", text)

    def test_zero_amount(self):
        self.assertEqual(money_analogy(0, self.ITEMS), "")

    def test_no_items_falls_back_to_yuan(self):
        self.assertIn("¥", money_analogy(12.3, []))

    def test_tiny_amount_falls_back(self):
        """Nothing costs less than 1 yuan here, so no count can be formed."""
        self.assertIn("¥", money_analogy(0.5, self.ITEMS))


class _FakeAccount:
    def __init__(self, available=556.5, accumulated=5358.7, expired=2355.2, expiring=166.0):
        self.available = available
        self.accumulated = accumulated
        self.expired = expired
        self.expiring_soon = expiring
        self.lost_ratio = expired / accumulated if accumulated else None


class _FakeData:
    def __init__(self):
        self.account = _FakeAccount()
        self.profile = None
        self.plan = []
        self.plan_value = 0.0
        self.best_ppv = 8.4
        self.redemptions = []


class HealthAndSummaryTests(unittest.TestCase):
    def test_score_penalises_loss(self):
        data = _FakeData()
        hs = health_score(data)
        self.assertLess(hs.score, 100)
        self.assertTrue(hs.title)

    def test_score_stays_in_range(self):
        data = _FakeData()
        data.account.expired = 9999.0  # absurd loss
        hs = health_score(data)
        self.assertGreaterEqual(hs.score, 0)
        self.assertLessEqual(hs.score, 100)

    def test_summary_mentions_loss_when_large(self):
        data = _FakeData()
        self.assertIn("过期", plain_summary(data))

    def test_summary_mentions_expiring_when_no_big_loss(self):
        data = _FakeData()
        data.account.expired = 10.0
        data.account.accumulated = 5358.7
        self.assertIn("到期", plain_summary(data))

    def test_glossary_covers_the_jargon(self):
        terms = [t for t, _ in PLAIN_GLOSSARY]
        self.assertIn("元/百分", terms)
        self.assertIn("期望值 EV", terms)


if __name__ == "__main__":
    unittest.main()
