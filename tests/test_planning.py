"""Tests for src/planning.py, src/preference.py and src/mcp_payload.py."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_payload import unwrap, unwrap_data  # noqa: E402
from src.planning import save_up_targets, split_points  # noqa: E402
from src.preference import MIN_ORDERS, build_preference  # noqa: E402


class BucketSplitTests(unittest.TestCase):
    def test_partial_expiry_splits(self):
        b = split_points(556.5, 166.0)
        self.assertAlmostEqual(b.expiring, 166.0)
        self.assertAlmostEqual(b.flexible, 390.5)

    def test_no_expiry_means_all_flexible(self):
        b = split_points(500.0, 0.0)
        self.assertEqual(b.expiring, 0.0)
        self.assertAlmostEqual(b.flexible, 500.0)

    def test_expiry_exceeding_balance_is_clamped(self):
        """Guard against APIs reporting more expiring than available."""
        b = split_points(100.0, 250.0)
        self.assertAlmostEqual(b.expiring, 100.0)
        self.assertEqual(b.flexible, 0.0)

    def test_zero_balance(self):
        self.assertEqual(split_points(0.0, 0.0).total, 0.0)


class _Item:
    def __init__(self, name, points, ppv):
        self.name = name
        self.points = points
        self.ppv = ppv


class SaveUpTests(unittest.TestCase):
    def test_targets_only_include_unaffordable(self):
        items = [_Item("cheap", 50, 8.0), _Item("dear", 800, 20.0)]
        targets = save_up_targets(items, 100.0)
        self.assertEqual([t.name for t in targets], ["dear"])

    def test_gap_is_computed(self):
        targets = save_up_targets([_Item("dear", 800, 20.0)], 556.5)
        self.assertAlmostEqual(targets[0].gap, 243.5)

    def test_weak_gain_is_not_recommended(self):
        """Waiting is only worth it for a materially better coupon."""
        items = [_Item("now", 50, 8.0), _Item("later", 800, 8.5)]
        self.assertEqual(save_up_targets(items, 100.0), [])

    def test_no_items_no_targets(self):
        self.assertEqual(save_up_targets([], 500.0), [])


class PreferenceTests(unittest.TestCase):
    @staticmethod
    def _order(days_ago, products):
        when = (date.today() - timedelta(days=days_ago)).strftime("%Y-%m-%d 12:00:00")
        return {
            "createTime": when,
            "orderProductList": [
                {"productName": name, "quantity": 1, "comboItemList": []} for name in products
            ],
        }

    def test_insufficient_orders_are_neutral(self):
        pref = build_preference({"list": [self._order(1, ["中薯条"])]})
        self.assertFalse(pref.usable)
        self.assertEqual(pref.affinity("中薯条")[0], 1.0)

    def test_bought_beats_never_bought(self):
        orders = {"list": [self._order(i * 30, ["中薯条"]) for i in range(MIN_ORDERS + 2)]}
        pref = build_preference(orders)
        self.assertTrue(pref.usable)
        bought, _ = pref.affinity("中薯条")
        never, _ = pref.affinity("完全没买过的东西")
        self.assertGreater(bought, never)

    def test_affinity_stays_within_bounds(self):
        orders = {"list": [self._order(i * 20, ["中薯条", "麦香鱼"]) for i in range(5)]}
        pref = build_preference(orders)
        for text in ("中薯条", "麦香鱼", "没买过的"):
            score, _ = pref.affinity(text)
            self.assertGreaterEqual(score, 0.6)
            self.assertLessEqual(score, 1.0)

    def test_recent_orders_outweigh_old_ones(self):
        recent = build_preference({"list": [self._order(5, ["巨无霸"])] * MIN_ORDERS})
        old = build_preference({"list": [self._order(700, ["巨无霸"])] * MIN_ORDERS})
        self.assertGreater(recent.top_weight, old.top_weight)


class PayloadUnwrapTests(unittest.TestCase):
    def test_original_response_heading(self):
        text = "# API Response Information\nblah\n## Original Response\n\n" + '{"success":true,"data":{"a":1}}'
        obj = unwrap(text)
        self.assertTrue(obj["success"])
        self.assertEqual(unwrap_data(text), {"a": 1})

    def test_inline_json_without_heading(self):
        """Store responses inline the JSON between prose lines."""
        text = "每个门店的基本信息：\n" + '{"success":true,"code":200,"data":[{"storeCode":"1"}]}\n' + "## 展示结果"
        self.assertEqual(unwrap_data(text)[0]["storeCode"], "1")

    def test_no_json_returns_none(self):
        self.assertIsNone(unwrap("这里没有任何 JSON"))

    def test_failure_envelope_is_still_parsed(self):
        text = '{"success":false,"code":400,"message":"缺少参数"}'
        obj = unwrap(text)
        self.assertFalse(obj["success"])
        self.assertEqual(obj["message"], "缺少参数")

    def test_nested_braces_inside_strings(self):
        text = '{"success":true,"data":{"x":"a{b}c"}}'
        self.assertEqual(unwrap_data(text)["x"], "a{b}c")


if __name__ == "__main__":
    unittest.main()
