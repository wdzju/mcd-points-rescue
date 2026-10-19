"""Tests for src/calibrate.py and src/redeem_rate.py.

Both modules encode decisions that are easy to get subtly wrong, and both
bugs that were actually shipped before these tests existed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibrate import calibrate, count_observations  # noqa: E402
from src.redeem_rate import (  # noqa: E402
    RATE_FLOOR,
    apply_haircut,
    build_profile,
    redemption_window,
)


class ObservationMatchingTests(unittest.TestCase):
    def test_numeric_collision_is_rejected(self):
        """下单立减3元券 must not absorb a 下单立减1元券 win."""
        counts = count_observations(
            ["下单立减3元券", "下单立减1元券"],
            [{"name": "下单立减1元券"}],
        )
        self.assertEqual(counts["下单立减3元券"], 0)
        self.assertEqual(counts["下单立减1元券"], 1)

    def test_exact_name_counts(self):
        counts = count_observations(["30积分"], [{"name": "30积分"}, {"name": "30积分"}])
        self.assertEqual(counts["30积分"], 2)

    def test_empty_history_yields_zero(self):
        counts = count_observations(["30积分"], [])
        self.assertEqual(counts["30积分"], 0)


class CalibrationTests(unittest.TestCase):
    def test_no_observations_falls_back_to_prior(self):
        cal = calibrate(["a", "b", "c"], [3.0, 2.0, 1.0], [])
        self.assertEqual(cal.basis, "prior_only")
        self.assertEqual(cal.total_observations, 0)

    def test_probabilities_sum_to_one(self):
        cal = calibrate(["a", "b", "c", "d"], [4.0, 3.0, 2.0, 1.0], [{"name": "a"}])
        self.assertAlmostEqual(sum(cal.probabilities.values()), 1.0, places=6)

    def test_observed_prize_gets_higher_probability_than_unobserved(self):
        history = [{"name": "a"}] * 6
        cal = calibrate(["a", "b"], [1.0, 2.0], history)
        self.assertGreater(cal.probability_of("a"), cal.probability_of("b"))

    def test_cheap_prior_still_dominates_when_evidence_is_thin(self):
        """One observation must not flip the whole ordering."""
        cal = calibrate(["a", "b"], [10.0, 1.0], [{"name": "a"}], alpha=8.0)
        # "b" is cheap, prior says it is common; one "a" win should not
        # overwhelm that yet.
        self.assertGreater(cal.probability_of("b"), cal.probability_of("a"))

    def test_more_evidence_moves_toward_observation(self):
        thin = calibrate(["a", "b"], [10.0, 1.0], [{"name": "a"}] * 2, alpha=8.0)
        thick = calibrate(["a", "b"], [10.0, 1.0], [{"name": "a"}] * 40, alpha=8.0)
        self.assertGreater(thick.probability_of("a"), thin.probability_of("a"))


class RedemptionProfileTests(unittest.TestCase):
    def test_all_lapsed_is_floored_not_zeroed(self):
        profile = build_profile(
            {"prizes": [{"name": "麦旋风5折券", "prizeTypeText": "优惠券", "statusText": "已失效"}] * 6}
        )
        self.assertAlmostEqual(profile.rate_raw, 0.0)
        self.assertEqual(profile.rate, RATE_FLOOR)
        self.assertTrue(profile.adjusted)

    def test_honoured_statuses_count_as_used(self):
        profile = build_profile(
            {
                "prizes": [
                    {"name": "a券", "prizeTypeText": "优惠券", "statusText": "已使用"},
                    {"name": "b券", "prizeTypeText": "优惠券", "statusText": "已失效"},
                ]
            }
        )
        self.assertEqual(profile.honoured, 1)
        self.assertEqual(profile.lapsed, 1)

    def test_no_history_is_unusable(self):
        profile = build_profile(None)
        self.assertFalse(profile.usable)

    def test_haircut_does_not_silently_ignore_zero_rate(self):
        """rate 0.0 is falsy — `rate or 1.0` would make the discount vanish."""
        profile = build_profile(
            {"prizes": [{"name": "a券", "prizeTypeText": "优惠券", "statusText": "已失效"}] * 6}
        )
        self.assertLess(apply_haircut(10.0, profile), 10.0)

    def test_haircut_preserves_none(self):
        profile = build_profile(None)
        self.assertIsNone(apply_haircut(None, profile))


class WindowTests(unittest.TestCase):
    def test_past_deadline_is_not_urgent(self):
        """Many live rows are 上架 with an expired downTime."""
        window = redemption_window("2020-01-01 00:00:00")
        self.assertEqual(window.urgency, "none")

    def test_future_deadline_within_week_is_urgent(self):
        from datetime import date, timedelta

        soon = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        self.assertEqual(redemption_window(soon).urgency, "urgent")

    def test_unparseable_deadline(self):
        self.assertEqual(redemption_window(None).urgency, "unknown")


if __name__ == "__main__":
    unittest.main()
