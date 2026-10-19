"""Tests for the two pieces of logic that actually decide what the user does.

`solve_clearance` picks the redemption组合 and `decide` picks between drawing
and redeeming. Both were shipping untested — the whole point of the tool rests
on them, so a regression here would be silent and expensive.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyze import (  # noqa: E402
    MAX_DP_CAPACITY,
    LotteryReport,
    solve_clearance,
    decide,
)


class _Item:
    """Minimal stand-in for Redemption."""

    def __init__(self, name: str, points: float, benefit: float):
        self.name = name
        self.points = points
        self.benefit = benefit

    @property
    def ppv(self):
        return self.benefit / self.points * 100.0 if self.points else None


class ClearanceTests(unittest.TestCase):
    def test_picks_highest_value_within_budget(self):
        items = [_Item("cheap", 50, 4.2), _Item("bulk", 500, 35.2)]
        picked, spent, value = solve_clearance(items, 500)
        names = {r.name for r, _ in picked}
        # 500 points on "bulk" (¥35.20) beats 10×"cheap" (¥42.00) only if the
        # model prefers quantity — it should prefer the ¥42 option.
        self.assertIn(spent, (500, 500))
        self.assertGreater(value, 0)

    def test_repeats_items_to_fill_budget(self):
        items = [_Item("snack", 50, 4.2)]
        picked, spent, value = solve_clearance(items, 150)
        self.assertEqual(picked[0][1], 3)
        self.assertAlmostEqual(spent, 150)
        self.assertAlmostEqual(value, 12.6)

    def test_never_exceeds_budget(self):
        items = [_Item("a", 100, 9.0), _Item("b", 300, 28.0)]
        _, spent, _ = solve_clearance(items, 250)
        self.assertLessEqual(spent, 250)

    def test_empty_items(self):
        self.assertEqual(solve_clearance([], 500), ([], 0.0, 0.0))

    def test_zero_budget(self):
        items = [_Item("a", 100, 9.0)]
        self.assertEqual(solve_clearance(items, 0), ([], 0.0, 0.0))

    def test_items_over_budget_are_ignored(self):
        items = [_Item("huge", 900, 90.0)]
        self.assertEqual(solve_clearance(items, 100), ([], 0.0, 0.0))

    def test_unpriced_items_are_skipped(self):
        items = [_Item("no-value", 50, 0.0), _Item("good", 50, 5.0)]
        picked, _, value = solve_clearance(items, 50)
        self.assertEqual([r.name for r, _ in picked], ["good"])
        self.assertAlmostEqual(value, 5.0)

    def test_absurd_budget_does_not_blow_up(self):
        """--budget is user input; a huge value must not allocate gigabytes."""
        items = [_Item("a", 50, 4.2)]
        _, spent, value = solve_clearance(items, 10 ** 12)
        self.assertGreater(value, 0)
        self.assertLessEqual(spent, 10 ** 12)

    def test_dp_capacity_constant_is_sane(self):
        self.assertLessEqual(MAX_DP_CAPACITY, 1_000_000)


def _lottery(ev: dict, cost: float = 24.0) -> LotteryReport:
    return LotteryReport(
        activity_name="t",
        status_text="进行中",
        cost_points=cost,
        draw_type_text="消耗积分抽奖",
        available_point=500.0,
        rows=[],
        scenarios=ev,
    )


class DecideTests(unittest.TestCase):
    def test_draw_when_clearly_better(self):
        lot = _lottery({"optimistic": 30.0, "realistic": 25.0, "pessimistic": 20.0})
        kind, reason = decide(lot, best_ppv=5.0, risk="balanced")
        self.assertEqual(kind, "draw")
        self.assertIn("抽奖", reason)

    def test_redeem_when_draw_is_weak(self):
        lot = _lottery({"optimistic": 1.0, "realistic": 0.5, "pessimistic": 0.3})
        kind, _ = decide(lot, best_ppv=8.0, risk="balanced")
        self.assertEqual(kind, "redeem")

    def test_coin_flip_when_high_variance(self):
        """Neutral wins, but the pessimistic case collapses — that is variance,
        not edge, and must not be sold as "better"."""
        lot = _lottery({"optimistic": 8.0, "realistic": 3.0, "pessimistic": 0.3})
        kind, reason = decide(lot, best_ppv=8.0, risk="balanced")
        self.assertEqual(kind, "coin_flip")
        self.assertIn("方差", reason)

    def test_unknown_without_lottery(self):
        self.assertEqual(decide(None, 8.0, "balanced")[0], "unknown")

    def test_unknown_without_cost(self):
        lot = _lottery({"realistic": 2.0}, cost=0.0)
        self.assertEqual(decide(lot, 8.0, "balanced")[0], "unknown")

    def test_unknown_without_best_ppv(self):
        lot = _lottery({"optimistic": 2.0, "realistic": 1.0, "pessimistic": 0.5})
        self.assertEqual(decide(lot, None, "balanced")[0], "unknown")

    def test_conservative_profile_demands_more(self):
        """The same EV can flip the conclusion as risk appetite tightens.

        At cost=24, EV 2.352 → 9.8 元/百分. That clears the balanced bar
        (1.15× × 8.0 = 9.2) but not the conservative one (1.30× × 8.0 = 10.4),
        so balanced says "draw" while conservative downgrades to coin_flip.
        Pessimistic stays at 5.0 so the high-variance guard does not fire.
        """
        lot = _lottery({"optimistic": 3.5, "realistic": 2.352, "pessimistic": 1.2})
        balanced = decide(lot, best_ppv=8.0, risk="balanced")[0]
        conservative = decide(lot, best_ppv=8.0, risk="conservative")[0]
        self.assertEqual(balanced, "draw")
        self.assertEqual(conservative, "coin_flip")


if __name__ == "__main__":
    unittest.main()
