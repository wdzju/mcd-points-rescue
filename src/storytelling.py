"""Turning analysis output into plain language.

Why this module exists
----------------------
The engine is correct. It is also unreadable to anyone who does not already
know what PPV, EV and shrinkage estimation mean. A report that only a
quant can parse fails at the only job that matters: changing what the reader
does next.

So every number gets a human-facing counterpart:

    "PPV 8.40"                 →  "每 100 积分能换回 8.4 元"
    "plan value ¥12.60"        →  "这波能救回约 2 个甜筒的钱"
    "expired 2,355.2 points"   →  "蒸发的分数够买 N 个巨无霸"

Two rules govern the wording:

1. **Never invent a claim.** Analogies are derived from live menu prices, and
   the source item is always named, so "≈2 甜筒" is checkable.
2. **Keep the technical layer, move it down.** Facts do not disappear; they
   move below the plain-language summary instead of blocking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple


@dataclass
class HealthScore:
    """A single 0-100 number plus a title a human would actually repeat."""

    score: int
    title: str
    comment: str
    drivers: List[str]


_GRADE_TABLE = [
    (85, "精算大师", "你的积分几乎没有被浪费，继续保持"),
    (70, "稳健管家", "大体管住了，还有一点提升空间"),
    (55, "随缘型选手", "想起来才用，大部分在随它去"),
    (40, "积分沉睡户", "积分在你账户里睡过去的居多"),
    (0, "散财童子", "积分基本是在给系统做贡献"),
]


def health_score(data: Any) -> HealthScore:
    """One score from the two things that actually destroy value."""
    score = 100.0
    drivers: List[str] = []

    lost = data.account.lost_ratio
    if lost is not None:
        penalty = lost * 40.0
        score -= penalty
        drivers.append(f"历史损耗 {lost * 100:.0f}%　−{penalty:.0f} 分")

    profile = data.profile
    if profile and profile.usable and profile.rate is not None:
        penalty = (1.0 - profile.rate) * 30.0
        score -= penalty
        drivers.append(f"券兑现率 {profile.rate * 100:.0f}%　−{penalty:.0f} 分")

    expiring = data.account.expiring_soon or 0.0
    if expiring > 0 and not data.plan:
        score -= 10.0
        drivers.append("本月有到期分但没给出方案　−10 分")

    score = max(0.0, min(100.0, score))
    title, comment = _grade(score)
    return HealthScore(score=int(round(score)), title=title, comment=comment, drivers=drivers)


def _grade(score: float) -> Tuple[str, str]:
    for floor, title, comment in _GRADE_TABLE:
        if score >= floor:
            return title, comment
    return "散财童子", "积分基本是在给系统做贡献"


def money_analogy(amount: Optional[float], items: Sequence[Tuple[str, float]]) -> str:
    """Express an amount as a count of a real menu item.

    Prefers a count between 1 and 6 — "约 2 个甜筒" lands, "约 0.4 个巨无霸"
    does not. Falls back to a bare yuan figure when nothing fits.
    """
    if amount is None or amount <= 0:
        return ""
    # No menu to anchor against: fall back to the plain figure rather than
    # dropping the analogy entirely.
    if not items:
        return f"约 ¥{amount:.1f}"

    best: Optional[Tuple[float, float, str]] = None
    for name, price in items:
        if price <= 0:
            continue
        count = amount / price
        if count < 1.0:
            continue
        # prefer a near-whole count in a human-scale range
        penalty = abs(count - round(count)) + (0.0 if count <= 6 else 1.5)
        if best is None or penalty < best[0]:
            best = (penalty, count, name)

    if best is None:
        return f"约 ¥{amount:.1f}"

    _, count, name = best
    if count <= 6:
        rounded = round(count, 1)
        shown = int(rounded) if abs(rounded - round(rounded)) < 0.05 else rounded
        return f"约 {shown} 个{name}"
    return f"约 {count:.0f} 个{name}"


def plain_summary(data: Any) -> str:
    """The one sentence a reader should walk away with."""
    acc = data.account
    lost = acc.lost_ratio
    expiring = acc.expiring_soon or 0.0

    if lost and lost >= 0.2:
        head = f"你的积分里 {lost * 100:.0f}% 已经悄悄过期了"
    elif expiring > 0:
        head = f"你还有 {expiring:,.0f} 分本月到期"
    else:
        head = f"你还有 {_fmt(acc.available)} 分可以用"

    if data.plan:
        tail = f"这次能救回 ¥{data.plan_value:.1f}"
    elif expiring > 0:
        tail = "本月到期的分要尽快处理"
    else:
        tail = "暂时没有到期压力，可以慢慢挑"
    return f"{head}，{tail}。"


def _fmt(value: Optional[float], spec: str = ".1f") -> str:
    if value is None:
        return "—"
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return "—"


def fun_facts(data: Any, menu_items: Sequence[Tuple[str, float]] = ()) -> List[str]:
    """Two or three lines that make the loss tangible."""
    facts: List[str] = []
    acc = data.account

    # What the evaporated points could have bought.
    if acc.expired and acc.expired > 0 and data.best_ppv:
        worth = acc.expired * data.best_ppv / 100.0
        analogy = money_analogy(worth, menu_items)
        if analogy:
            facts.append(f"已经蒸发的 {acc.expired:,.0f} 分，按现在的汇率约 ¥{worth:.0f}，{analogy}。")
        else:
            facts.append(f"已经蒸发的 {acc.expired:,.0f} 分，约等于 ¥{worth:.0f} 凭空消失。")

    # Plan value in food terms.
    if data.plan and menu_items:
        analogy = money_analogy(data.plan_value, menu_items)
        if analogy:
            facts.append(f"这份方案能换回 ¥{data.plan_value:.1f}，{analogy}。")

    # Second loss.
    profile = data.profile
    if profile and profile.usable and profile.lapsed:
        facts.append(
            f"你历史抽到/领到的 {profile.total_coupons} 张券里，"
            f"{profile.lapsed} 张最后没用掉 —— 这是第二次损耗。"
        )

    # The counter-intuitive finding, when it holds.
    priced = [r for r in data.redemptions if r.ppv is not None and (r.benefit or 0) > 0]
    if len(priced) >= 3:
        cheapest = min(priced, key=lambda r: r.points or 0)
        priciest = max(priced, key=lambda r: r.points or 0)
        if cheapest.ppv and priciest.ppv and cheapest.ppv > priciest.ppv * 1.5:
            facts.append(
                f"最划算的不是最贵的：{cheapest.name[:14]} 只要 "
                f"{cheapest.points:,.0f} 分，效率却是 {priciest.name[:14]} 的 "
                f"{cheapest.ppv / priciest.ppv:.1f} 倍。"
            )
    return facts


PLAIN_GLOSSARY: List[Tuple[str, str]] = [
    ("元/百分", "每 100 积分能换回多少人民币，越高越划算"),
    ("期望值 EV", "按概率算，平均一次能赚回多少"),
    ("兑现率", "你历史上拿到券以后，真正用掉的比例"),
    ("二次损耗", "积分过期是第一次，换来的券没用掉是第二次"),
    ("清仓方案", "在到期分预算内，能换回最多钱的组合"),
]
