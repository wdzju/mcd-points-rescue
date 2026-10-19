"""Tests for the estimation ladder in src/deal_engine.py.

Each test here corresponds to a defect found against live data, so these are
regression guards, not coverage padding.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.deal_engine import (  # noqa: E402
    CategoryStats,
    MealIndex,
    MenuItem,
    parse_coupon,
    value_coupon,
)


def _meal(name: str, price: float) -> MenuItem:
    return MenuItem(name=name, current_price=price, original_price=price)


class CouponParsingTests(unittest.TestCase):
    def test_bundle_coupon(self):
        spec = parse_coupon("21.9元巨无霸可乐组合")
        self.assertEqual(spec.kind, "bundle")
        self.assertAlmostEqual(spec.price_off, 21.9)
        self.assertEqual(spec.subject, "巨无霸可乐组合")

    def test_discount_coupon_uses_chinese_per_ten(self):
        spec = parse_coupon("板烧三件套5折券")
        self.assertEqual(spec.kind, "discount")
        self.assertAlmostEqual(spec.rate, 0.5)

    def test_discount_with_decimal(self):
        spec = parse_coupon("小食四件套5.5折券")
        self.assertAlmostEqual(spec.rate, 0.55)

    def test_ninety_five_zhe_is_95_percent_not_9_5(self):
        spec = parse_coupon("95折券")
        self.assertAlmostEqual(spec.rate, 0.95)

    def test_instant_coupon(self):
        spec = parse_coupon("下单立减3元券")
        self.assertEqual(spec.kind, "instant")
        self.assertAlmostEqual(spec.amount_off, 3.0)

    def test_points_prize(self):
        spec = parse_coupon("30积分")
        self.assertEqual(spec.kind, "points")
        self.assertAlmostEqual(spec.award_points, 30.0)


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            _meal("巨无霸", 26.0),
            _meal("可乐", 9.5),
            _meal("派", 8.5),
            _meal("麦辣鸡腿汉堡", 23.0),
            _meal("麦辣鸡腿汉堡三件套", 47.5),
            _meal("板烧鸡腿堡三件套", 48.5),
            _meal("BFF四宫格小食盘双人餐", 124.5),
            _meal("薯条", 14.5),
            _meal("麦乐鸡", 14.5),
        ]
        self.cats = [
            CategoryStats("小食甜品", [14.5, 8.5, 13.0]),
            CategoryStats("小食拼盘/多人餐", [124.5, 117.5, 89.0]),
        ]
        self.index = MealIndex(self.items, self.cats)

    def test_exact_match(self):
        est = self.index.resolve("巨无霸")
        self.assertEqual(est.method, "exact")
        self.assertAlmostEqual(est.point, 26.0)

    def test_bundle_size_constraint_rejects_mismatched_set(self):
        """两件套 must not borrow the 三件套 price (≈50% inflation)."""
        est = self.index.resolve("麦辣鸡腿汉堡两件套")
        self.assertIsNotNone(est)
        self.assertNotAlmostEqual(est.point, 47.5)

    def test_decomposition_sums_components(self):
        est = self.index.resolve("巨无霸可乐组合")
        self.assertEqual(est.method, "components")
        self.assertAlmostEqual(est.point, 35.5)

    def test_category_fallback_engages_for_vague_coupon(self):
        est = self.index.resolve("指定小食任选")
        self.assertIsNotNone(est)
        self.assertEqual(est.method, "category")

    def test_large_format_category_is_excluded(self):
        """A snack coupon must not be priced like a sharing platter.

        Live bug: 指定小食 matched 小食拼盘/多人餐 (median ¥89) and produced a
        ¥79 saving on a coupon worth about ¥4.
        """
        est = self.index.resolve("指定小食任选")
        self.assertLess(est.point, 30.0)

    def test_tied_categories_prefer_cheaper(self):
        est = self.index.resolve("小食")
        self.assertLessEqual(est.point, 20.0)

    def test_single_character_menu_item_is_usable(self):
        est = self.index.resolve("香芋派任选")
        self.assertIsNotNone(est)

    def test_unresolvable_returns_none(self):
        self.assertIsNone(self.index.resolve("完全不存在的商品名称xyz"))


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.index = MealIndex([_meal("巨无霸", 26.0), _meal("可乐", 9.5)], [])

    def test_bundle_benefit_is_the_spread(self):
        value = value_coupon(parse_coupon("21.9元巨无霸可乐组合"), self.index)
        self.assertAlmostEqual(value.benefit_cny, 35.5 - 21.9)

    def test_bundle_reports_a_band(self):
        value = value_coupon(parse_coupon("21.9元巨无霸可乐组合"), self.index)
        self.assertIsNotNone(value.benefit_low)
        self.assertIsNotNone(value.benefit_high)

    def test_no_discount_when_price_exceeds_value(self):
        value = value_coupon(parse_coupon("99元巨无霸"), self.index)
        self.assertEqual(value.basis, "no_discount")
        self.assertEqual(value.benefit_cny, 0.0)

    def test_points_prize_needs_a_rate(self):
        value = value_coupon(parse_coupon("30积分"), self.index)
        self.assertEqual(value.basis, "needs_ppv")

    def test_points_prize_with_rate(self):
        value = value_coupon(parse_coupon("30积分"), self.index, points_ppv=2.0)
        self.assertAlmostEqual(value.benefit_cny, 0.6)


if __name__ == "__main__":
    unittest.main()
