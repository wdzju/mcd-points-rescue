"""Tests for menu-period detection and store selection helpers.

These guard a defect found on 2026-10-19: the same account scored 17/24
coverage at midday and 7/23 the next morning. Cause: `query-meals` returns the
catalogue that is sellable *right now*, and before ~10:30 that catalogue is
breakfast-only — no 板烧, no 四件套, so most coupons have nothing to price
against.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyze import _menu_size, detect_menu_period  # noqa: E402


def _menu(names, categories=()):
    return {
        "success": True,
        "data": {
            "meals": {f"c{i}": {"name": n} for i, n in enumerate(names)},
            "categories": [{"name": c} for c in categories],
        },
    }


BREAKFAST_NAMES = [
    "猪柳蛋麦满分", "吉士蛋麦满分", "火腿扒麦满分", "原味板烧鸡腿炒双蛋堡",
    "脆香油条", "豆浆", "麦咖啡热美式", "大脆鸡扒麦满分组合",
]
BREAKFAST_CATS = ["超值早餐", "麦满分系列", "炒双蛋堡系列", "一早现磨"]

MAIN_NAMES = [
    "巨无霸", "巨无霸四件套", "板烧鸡腿堡", "板烧四件套", "麦辣鸡腿汉堡",
    "麦辣鸡腿汉堡三件套", "安格斯厚牛堡", "麦乐鸡",
]


class MenuPeriodTests(unittest.TestCase):
    def test_breakfast_menu_detected(self):
        period, stats = detect_menu_period(_menu(BREAKFAST_NAMES, BREAKFAST_CATS))
        self.assertEqual(period, "breakfast")
        self.assertGreaterEqual(stats["breakfast_signals"], 3)

    def test_regular_menu_detected(self):
        period, stats = detect_menu_period(_menu(MAIN_NAMES, ["超值四件套", "汉堡"]))
        self.assertEqual(period, "regular")
        self.assertGreaterEqual(stats["main_signals"], 2)

    def test_single_stray_main_token_does_not_break_breakfast_detection(self):
        """Breakfast menus can contain 麦乐鸡 as a side.

        The first version required main_signals == 0, so one stray token
        classified a breakfast menu as "unknown" and suppressed the warning
        entirely — the user got a much weaker ranking with no explanation.
        """
        names = BREAKFAST_NAMES + ["麦乐鸡"]
        period, stats = detect_menu_period(_menu(names, BREAKFAST_CATS))
        self.assertEqual(stats["main_signals"], 1)
        self.assertEqual(period, "breakfast")

    def test_empty_menu_is_unknown(self):
        period, _ = detect_menu_period(_menu([]))
        self.assertEqual(period, "unknown")

    def test_none_payload_is_unknown(self):
        period, _ = detect_menu_period(None)
        self.assertEqual(period, "unknown")

    def test_malformed_payload_is_unknown(self):
        period, _ = detect_menu_period({"success": True, "data": "not a dict"})
        self.assertEqual(period, "unknown")


class MenuSizeTests(unittest.TestCase):
    def test_counts_meals(self):
        self.assertEqual(_menu_size(_menu(["a", "b", "c"])), 3)

    def test_none_is_zero(self):
        self.assertEqual(_menu_size(None), 0)

    def test_missing_meals_key(self):
        self.assertEqual(_menu_size({"success": True, "data": {}}), 0)


if __name__ == "__main__":
    unittest.main()
