"""Multi-period planning: what to spend now, what to save for.

The real question
-----------------
A single-period knapsack answers "spend these expiring points optimally".
But a balance is not homogeneous:

    expiring points   — burn them now or lose them
    flexible points   — can be held and combined into a better coupon

Treating the whole balance as one pot is wrong in both directions: it either
recommends cashing out points that were never at risk, or misses the option of
waiting for a coupon with materially better efficiency.

So the balance is split first, then each bucket gets its own treatment:

    expiring  → clearance knapsack (spend it, no debate)
    flexible  → save-up analysis (what would waiting unlock?)

What this deliberately does NOT do
----------------------------------
It does not forecast when you will earn the missing points. Points accrual rate
is not exposed by any MCP tool, and `realTotalAmount` on these orders reads 0
(coupon-funded), so any "you'll get there in 3 weeks" claim would be invented.
We report the gap and let the reader judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

MIN_GAIN_RATIO = 1.25  # only flag a target if it beats current best by 25%


@dataclass
class Bucket:
    """Split of the usable balance by time pressure."""

    expiring: float = 0.0
    flexible: float = 0.0
    note: str = ""

    @property
    def total(self) -> float:
        return self.expiring + self.flexible

    @property
    def has_flexible(self) -> bool:
        return self.flexible > 0


def split_points(
    available: Optional[float], expiring: Optional[float]
) -> Bucket:
    """Partition the balance into at-risk and holdable portions."""
    avail = float(available or 0.0)
    exp = float(expiring or 0.0)
    if avail <= 0:
        return Bucket(note="无可用的积分余额")
    if exp <= 0:
        return Bucket(expiring=0.0, flexible=avail, note="没有即将到期的积分，可以慢慢挑")
    if exp >= avail:
        # Everything at risk (or the API reported more expiring than available).
        return Bucket(
            expiring=avail,
            flexible=0.0,
            note="可用余额已全部处于到期倒计时中，本月内处理完",
        )
    return Bucket(
        expiring=exp,
        flexible=avail - exp,
        note=f"{exp:,.0f} 分本月到期必须花掉，其余 {avail - exp:,.0f} 分可以攒",
    )


@dataclass
class SaveUpTarget:
    """A better coupon just out of reach, and what it would take."""

    name: str
    points: float
    gap: float
    ppv: float
    current_ppv: Optional[float]
    gain_ratio: Optional[float]
    note: str = ""

    @property
    def worth_waiting(self) -> bool:
        return bool(self.gain_ratio and self.gain_ratio >= MIN_GAIN_RATIO)


def save_up_targets(
    items: Sequence, available: Optional[float], limit: int = 3
) -> List[SaveUpTarget]:
    """Coupons the balance cannot yet afford, ranked by efficiency gain.

    `items` are Redemption objects; anything already affordable is skipped.
    An empty result is a real conclusion — it means nothing worth waiting for
    beats what the balance can already buy.
    """
    avail = float(available or 0.0)
    priced = [i for i in items if getattr(i, "ppv", None) and getattr(i, "points", None)]
    if not priced or avail <= 0:
        return []

    affordable = [i for i in priced if i.points <= avail]
    current_best = max((i.ppv for i in affordable), default=None)

    out: List[SaveUpTarget] = []
    for item in sorted(priced, key=lambda i: -i.ppv):
        if item.points <= avail:
            continue
        gap = item.points - avail
        gain = (item.ppv / current_best) if current_best else None
        if gain is not None and gain < MIN_GAIN_RATIO:
            continue  # not meaningfully better — not worth waiting for
        target = SaveUpTarget(
            name=item.name,
            points=float(item.points),
            gap=gap,
            ppv=float(item.ppv),
            current_ppv=current_best,
            gain_ratio=round(gain, 2) if gain else None,
        )
        if current_best:
            target.note = (
                f"效率 {item.ppv:.2f} 元/百分，是当前可达最优 "
                f"{current_best:.2f} 的 {gain:.2f} 倍"
            )
        else:
            target.note = f"效率 {item.ppv:.2f} 元/百分（当前余额换不到任何可估值券）"
        out.append(target)
        if len(out) >= limit:
            break
    return out
