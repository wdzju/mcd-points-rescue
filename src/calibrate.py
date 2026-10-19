"""Calibrating lottery odds from the account's own prize history.

The problem
-----------
`query-lottery-info` returns a prize pool with **no probabilities at all**.
Publishing a single EV number from that is storytelling, so v1 shipped three
assumptions (uniform / zipf-1.2 / zipf-3.0) and told the reader the spread.

This module does better: `query-my-prizes` returns every prize the account has
ever won, which is real evidence about the pool. Counting those wins gives an
observed frequency per prize.

The estimator
-------------
Observed frequencies alone are unusable at small N — one lucky win on a
top-tier coupon would flip the whole ranking. So we shrink toward the prior:

    p = (N · p_observed + α · p_prior) / (N + α)

where `p_prior` is the zipf decay (expensive prizes are rare) and α controls
how much evidence is needed before we trust the data. α = 8 means "roughly
eight observations before the data outweighs the prior".

The three scenarios then become three different degrees of trust in the data
rather than three unrelated guesses:

    optimistic   α = 2    trust the observations sooner
    realistic    α = 8    balanced (headline)
    pessimistic  α = 30   trust the prior; assume the big prizes are rare

Every result reports how much evidence actually backed it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .pricing import _tokens, normalize_name

# How many observations before the data outweighs the prior.
ALPHA_OPTIMISTIC = 2.0
ALPHA_REALISTIC = 8.0
ALPHA_PESSIMISTIC = 30.0

# Zipf exponent for the prior: larger = steeper drop-off for top prizes.
PRIOR_EXPONENT = 1.2


@dataclass
class Calibration:
    """Per-prize probabilities plus the evidence behind them."""

    probabilities: Dict[str, float] = field(default_factory=dict)
    observations: Dict[str, int] = field(default_factory=dict)
    total_observations: int = 0
    matched_prizes: int = 0
    pool_size: int = 0
    alpha: float = ALPHA_REALISTIC
    note: str = ""

    @property
    def basis(self) -> str:
        if self.total_observations == 0:
            return "prior_only"
        if self.total_observations < 5:
            return "weak_evidence"
        return "observed"

    @property
    def basis_label(self) -> str:
        return {
            "prior_only": "纯先验（无历史观测）",
            "weak_evidence": "弱证据（观测不足 5 次）",
            "observed": "历史观测校准",
        }.get(self.basis, self.basis)

    def probability_of(self, name: str) -> float:
        return self.probabilities.get(name, 0.0)


def _prior_distribution(pool_size: int, exponent: float = PRIOR_EXPONENT) -> List[float]:
    """Zipf-ish prior over prizes ordered richest-first."""
    if pool_size <= 0:
        return []
    weights = [1.0 / (pool_size - i) ** exponent for i in range(pool_size)]
    total = sum(weights)
    return [w / total for w in weights]


def _match_key(name: str) -> str:
    """Loose key so 「麦旋风5折券」 in the pool matches the same prize in history."""
    return normalize_name(name)


def count_observations(prize_names: Sequence[str], history: Sequence[Dict]) -> Dict[str, int]:
    """Map each pool prize onto how many times it appears in win history.

    Matching is exact on the normalised name first, then falls back to token
    overlap, because the same prize can be recorded with slightly different
    wording across campaigns (e.g. a 「二等奖：」 prefix).
    """
    counts: Dict[str, int] = {name: 0 for name in prize_names}

    # index history names once
    history_keys: List[str] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        raw = row.get("name")
        if raw:
            history_keys.append(str(raw))

    if not history_keys:
        return counts

    by_norm: Dict[str, List[str]] = {}
    for raw in history_keys:
        by_norm.setdefault(_match_key(raw), []).append(raw)

    for prize in prize_names:
        key = _match_key(prize)
        if key in by_norm:
            counts[prize] += len(by_norm[key])
            continue
        # token-overlap fallback for prefixed / reworded records
        wanted = set(_tokens(prize))
        if not wanted:
            continue
        prize_nums = set(re.findall(r"\d+", prize))
        for hist_key, originals in by_norm.items():
            hay = set(_tokens(hist_key))
            if not hay:
                continue
            # Guard against numeric collisions. 「下单立减3元券」 and
            # 「下单立减1元券」 differ by one character yet share almost every
            # token — without this check a ¥1 win would be credited to the ¥3
            # prize and inflate the whole EV.
            hist_nums = set(re.findall(r"\d+", hist_key))
            if prize_nums and hist_nums and prize_nums != hist_nums:
                continue
            overlap = len(wanted & hay) / len(wanted | hay)
            if overlap >= 0.6:
                counts[prize] += len(originals)
    return counts


def calibrate(
    ordered_prizes: Sequence[str],
    values: Sequence[Optional[float]],
    history: Sequence[Dict],
    alpha: float = ALPHA_REALISTIC,
) -> Calibration:
    """Shrink observed frequencies toward the zipf prior.

    `ordered_prizes` must be sorted richest-first so the prior's decay lines up
    with prize value (same ordering requirement as the zipf scenarios).
    """
    pool_size = len(ordered_prizes)
    if pool_size == 0:
        return Calibration(note="奖池为空")

    prior = _prior_distribution(pool_size)
    observations = count_observations(ordered_prizes, history)
    total_n = sum(observations.values())

    probabilities: Dict[str, float] = {}
    for idx, name in enumerate(ordered_prizes):
        observed = (observations.get(name, 0) / total_n) if total_n else 0.0
        p = (total_n * observed + alpha * prior[idx]) / (total_n + alpha)
        probabilities[name] = p

    # renormalise against float drift
    total = sum(probabilities.values())
    if total > 0:
        probabilities = {k: v / total for k, v in probabilities.items()}

    matched = len([n for n in ordered_prizes if observations.get(n, 0) > 0])
    note = (
        f"收缩估计：{total_n} 次历史观测 × 观测频率 + α={alpha:g} × 幂律先验。"
        f"奖池 {pool_size} 项中有 {matched} 项命中历史记录。"
    )
    if total_n == 0:
        note = "无历史中奖记录可用于校准，退化为纯幂律先验。"

    return Calibration(
        probabilities=probabilities,
        observations=observations,
        total_observations=total_n,
        matched_prizes=matched,
        pool_size=pool_size,
        alpha=alpha,
        note=note,
    )


def scenario_probabilities(
    ordered_prizes: Sequence[str],
    values: Sequence[Optional[float]],
    history: Sequence[Dict],
) -> Dict[str, Calibration]:
    """The three trust levels, as three shrinkage strengths."""
    return {
        "optimistic": calibrate(ordered_prizes, values, history, ALPHA_OPTIMISTIC),
        "realistic": calibrate(ordered_prizes, values, history, ALPHA_REALISTIC),
        "pessimistic": calibrate(ordered_prizes, values, history, ALPHA_PESSIMISTIC),
    }
