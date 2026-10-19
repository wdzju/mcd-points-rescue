"""Preference modelling — objective efficiency vs. what you actually eat.

The distinction
---------------
PPV is a fact: how many RMB a coupon saves per 100 points, derived from menu
prices. It does not know you.

But a coupon for something you never order is worth less *to you* than its
face saving suggests. `order-list` exposes real purchase history, so we can
score each coupon against what this account demonstrably buys:

    affinity   ∈ [0.6, 1.0]   how well a coupon matches your order history
    ppv_personal = ppv × affinity

Design constraints (why the floor is 0.6, not 0)
-----------------------------------------------
1. **Never let a coupon collapse to zero.** "You haven't bought it" means you
   haven't bought it *yet* — not that you never would. Zeroing it would make
   the ranking a self-fulfilling loop that only ever recommends the past.
2. **Recency decays.** A burger bought last month says more than one from ten
   months ago. Monthly half-life of 6 months.
3. **Refuse to guess on thin data.** Fewer than MIN_ORDERS orders returns a
   neutral affinity of 1.0 and says so, instead of building a "profile" from
   two purchases.
4. **Objective PPV always stays visible.** Personalisation is an overlay, not
   a replacement — the reader must be able to see the unadjusted number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .pricing import _tokens, normalize_name

MIN_ORDERS = 3
HALF_LIFE_MONTHS = 6.0
AFFINITY_FLOOR = 0.6


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _months_ago(when: Optional[datetime], today: Optional[date] = None) -> float:
    if when is None:
        return HALF_LIFE_MONTHS * 2  # unknown age -> treat as old
    today = today or date.today()
    delta = (today - when.date()).days
    return max(0.0, delta / 30.0)


@dataclass
class Preference:
    """Purchase history reduced to a weighted item-frequency table."""

    order_count: int = 0
    items: Dict[str, float] = field(default_factory=dict)  # normalised name -> weight
    raw_counts: Dict[str, int] = field(default_factory=dict)
    top_weight: float = 0.0
    basis: str = "none"
    note: str = ""
    span_days: Optional[int] = None

    @property
    def usable(self) -> bool:
        return self.order_count >= MIN_ORDERS and bool(self.items)

    def affinity(self, *texts: Optional[str]) -> Tuple[float, Optional[str]]:
        """Best affinity across several candidate names.

        Returns (affinity, matched_item). Multiple texts are accepted because a
        coupon is known by both its own name and the menu item it resolves to.
        """
        if not self.usable:
            return 1.0, None

        best_score = 0.0
        best_item: Optional[str] = None
        for text in texts:
            if not text:
                continue
            key = normalize_name(text)
            if not key:
                continue
            for item, weight in self.items.items():
                score = 0.0
                if item and (item in key or key in item):
                    score = weight
                else:
                    a, b = set(_tokens(text)), set(_tokens(item))
                    if a and b:
                        overlap = len(a & b) / len(a | b)
                        if overlap >= 0.6:
                            score = weight * overlap
                if score > best_score:
                    best_score, best_item = score, item

        if best_score <= 0 or self.top_weight <= 0:
            return AFFINITY_FLOOR, None

        # Two signals, deliberately weighted toward the binary one.
        #
        # A linear ratio against top_weight collapses everything: when one item
        # (中薯条, 9 orders) dominates, every other purchased item scores ~0.19
        # and lands at 0.68 versus 0.60 for never-bought — indistinguishable.
        # "Did you ever buy this" is the signal that matters; frequency is a
        # refinement on top of it.
        #     floor 0.6  +  0.2 if ever bought  +  0.2 × relative frequency
        ratio = min(1.0, math.log1p(best_score) / math.log1p(self.top_weight))
        return round(AFFINITY_FLOOR + 0.2 + 0.2 * ratio, 3), best_item

    def top_items(self, limit: int = 6) -> List[Tuple[str, float]]:
        return sorted(self.items.items(), key=lambda kv: -kv[1])[:limit]


def build_preference(
    orders_data: Any, today: Optional[date] = None
) -> Preference:
    """Reduce `order-list` output to a recency-weighted frequency table."""
    if isinstance(orders_data, dict):
        records = orders_data.get("list") or []
    elif isinstance(orders_data, list):
        records = orders_data
    else:
        records = []

    pref = Preference()
    if not records:
        pref.note = "未获取到历史订单"
        return pref

    dates: List[date] = []
    for order in records:
        if not isinstance(order, dict):
            continue
        pref.order_count += 1
        when = _parse_dt(order.get("createTime"))
        if when:
            dates.append(when.date())
        decay = 0.5 ** (_months_ago(when, today) / HALF_LIFE_MONTHS)
        for product in order.get("orderProductList") or []:
            if not isinstance(product, dict):
                continue
            _accumulate(pref, product.get("productName"), product.get("quantity"), decay)
            for combo in product.get("comboItemList") or []:
                if isinstance(combo, dict):
                    _accumulate(pref, combo.get("name"), combo.get("quantity"), decay)

    if dates:
        pref.span_days = (max(dates) - min(dates)).days
    pref.top_weight = max(pref.items.values()) if pref.items else 0.0

    if pref.order_count < MIN_ORDERS:
        pref.basis = "insufficient"
        pref.note = f"历史订单仅 {pref.order_count} 单（少于 {MIN_ORDERS} 单），不做个性化调整"
    elif not pref.items:
        pref.basis = "empty"
        pref.note = "历史订单中没有可识别的餐品"
    else:
        pref.basis = "orders"
        pref.note = (
            f"基于 {pref.order_count} 单历史订单"
            + (f"，跨度 {pref.span_days} 天" if pref.span_days else "")
            + f"，按 {HALF_LIFE_MONTHS:g} 个月半衰期加权"
        )
    return pref


def _accumulate(pref: Preference, name: Any, quantity: Any, decay: float) -> None:
    if not name:
        return
    try:
        qty = float(quantity or 1)
    except (TypeError, ValueError):
        qty = 1.0
    key = normalize_name(name)
    if not key:
        return
    weight = qty * decay
    pref.items[key] = pref.items.get(key, 0.0) + weight
    pref.raw_counts[key] = pref.raw_counts.get(key, 0) + int(qty)
