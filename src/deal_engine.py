"""Deal valuation engine — what a coupon is actually worth.

The discovery that forced this module
-------------------------------------
Live McDonald's data shows every points redemption is a **discount coupon**,
not a product:

    mall item   "21.9元巨无霸可乐组合"   800 分  →  the item IS a right to pay ¥21.9
    lottery     "板烧三件套5折券"          →  the prize is 50% off a set meal

So the naive model (product worth = its price) is wrong twice over:

    ✗  value = 21.9            you still pay that money
    ✓  value = list price − 21.9

The payout of any points redemption is the **discount**, never the sticker.
Everything below exists to compute that number defensibly from the live menu.

Estimation ladder
-----------------
Point matching alone only covers about a third of the catalogue, which makes
any "best option" claim a local optimum over a minority of items. So pricing
falls through a ladder, each rung weaker but still honest:

    exact → fuzzy → components → category → interval → unresolved

Every rung is labelled and reported, so a median-derived estimate never
masquerades as a matched price.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pricing import _tokens, normalize_name

# Bundle sizes must agree. A 两件套 is not a 三件套, and treating them alike
# inflates the reference price by roughly 50%.
_BUNDLE_COUNT = {
    "两件套": 2, "两件": 2, "2件": 2,
    "三件套": 3, "三件": 3, "3件": 3,
    "四件套": 4, "四件": 4, "4件": 4,
    "五件套": 5, "五件": 5, "5件": 5,
    "单人餐": 1, "双人餐": 2, "三人餐": 3,
}


def _is_large_format(name: str) -> bool:
    """Sharing-size items: platter, family bucket, multi-person sets."""
    return any(token in str(name) for token in _LARGE_FORMAT)


def bundle_count(text: str) -> Optional[int]:
    """Extract how many items a bundle contains, if stated."""
    raw = str(text or "")
    for token, count in _BUNDLE_COUNT.items():
        if token in raw:
            return count
    m = re.search(r"(\d+)\s*件套", raw)
    return int(m.group(1)) if m else None


# Words that carry no pricing signal when decomposing a bundle name.
_STOPWORDS = {"任选", "组合", "套餐", "指定", "兑换券", "券", "兑换", "活动", "应援", "专享", "随心配"}

# Categories dominated by sharing-size items. Matching these from a vague
# coupon name is how a snack coupon gets priced like a party platter.
_LARGE_FORMAT = ("多人餐", "拼盘", "双人", "三人", "分享", "全家桶", "四宫格", "八件套", "十翅", "盘")


def _as_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _quantile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile; avoids a numpy dependency."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


@dataclass
class MenuItem:
    name: str
    current_price: float
    original_price: float
    code: str = ""
    categories: List[str] = field(default_factory=list)

    @property
    def list_price(self) -> float:
        """Reference "before discount" price."""
        return self.original_price or self.current_price


@dataclass
class CategoryStats:
    """Price distribution of one menu category."""

    name: str
    prices: List[float]

    @property
    def median(self) -> float:
        return statistics.median(self.prices) if self.prices else 0.0

    @property
    def low(self) -> float:
        return _quantile(self.prices, 0.25)

    @property
    def high(self) -> float:
        return _quantile(self.prices, 0.75)

    @property
    def size(self) -> int:
        return len(self.prices)


class MealIndex:
    """Resolved-price lookup over everything the menu currently sells."""

    # Below this, a token-overlap match is a guess rather than a match.
    FUZZY_THRESHOLD = 0.6

    def __init__(
        self,
        items: Sequence[MenuItem],
        categories: Optional[Sequence[CategoryStats]] = None,
    ) -> None:
        best: Dict[str, MenuItem] = {}
        for item in items:
            if not item.name or item.list_price <= 0:
                continue
            key = normalize_name(item.name)
            if key not in best or item.list_price < best[key].list_price:
                best[key] = item
        self.items: List[MenuItem] = list(best.values())
        self._by_norm: Dict[str, MenuItem] = {normalize_name(i.name): i for i in self.items}
        # Longest-first so "板烧鸡腿堡" is consumed before its own substrings.
        # The third field flags sharing-size items so decomposition can skip
        # them too — the large-format guard must apply at every rung, not just
        # the category one.
        self._components: List[Tuple[str, float, bool]] = sorted(
            ((normalize_name(i.name), i.list_price, _is_large_format(i.name)) for i in self.items),
            key=lambda t: len(t[0]),
            reverse=True,
        )
        self.categories: List[CategoryStats] = [c for c in (categories or []) if c.prices]

    @classmethod
    def from_payload(
        cls, meals: Dict[str, Any], categories: Optional[List[Dict[str, Any]]] = None
    ) -> "MealIndex":
        """Build from `query-meals` → data.meals + data.categories.

        `meals` is a code → detail map; `categories` groups those codes under
        display names. The grouping is what lets a vague coupon like
        「指定小食任选」 fall back to a category price range instead of nothing.
        """
        items: List[MenuItem] = []
        for code, detail in (meals or {}).items():
            if not isinstance(detail, dict):
                continue
            name = detail.get("name")
            if not name:
                continue
            items.append(
                MenuItem(
                    name=str(name),
                    current_price=_as_float(detail.get("currentPrice")),
                    original_price=_as_float(detail.get("originalPrice")),
                    code=str(code),
                )
            )

        by_code: Dict[str, MenuItem] = {i.code: i for i in items}
        stats: List[CategoryStats] = []
        for cat in categories or []:
            if not isinstance(cat, dict):
                continue
            cat_name = str(cat.get("name") or "").strip()
            if not cat_name:
                continue
            prices: List[float] = []
            for entry in cat.get("meals") or []:
                code = entry.get("code") if isinstance(entry, dict) else entry
                item = by_code.get(str(code))
                if item and item.list_price > 0:
                    prices.append(item.list_price)
                    item.categories.append(cat_name)
            if prices:
                stats.append(CategoryStats(name=cat_name, prices=prices))

        return cls(items, stats)

    def __len__(self) -> int:
        return len(self.items)

    # ------------------------------------------------------------------
    def _direct(self, desc: str) -> Optional[Tuple[float, str, float]]:
        """Locate one menu row satisfying most tokens of the description."""
        wanted = _tokens(desc)
        if not wanted:
            return None
        want_count = bundle_count(desc)
        want_large = _is_large_format(desc)
        scored: List[Tuple[float, float, str]] = []
        for item in self.items:
            # A coupon that never mentions sharing must not resolve to a
            # ¥124 platter just because "小食" appears in its name.
            if not want_large and _is_large_format(item.name):
                continue
            hay = normalize_name(item.name)
            hits = sum(1 for t in wanted if t in hay)
            if not hits:
                continue
            if want_count is not None:
                got = bundle_count(item.name)
                if got is not None and got != want_count:
                    continue
            scored.append((hits / len(wanted), item.list_price, item.name))
        if not scored:
            return None
        scored.sort(key=lambda r: (-r[0], r[1]))
        best_score, best_price, best_name = scored[0]
        if best_score < self.FUZZY_THRESHOLD:
            return None
        return best_price, best_name, best_score

    def _decompose(self, desc: str) -> Optional[Tuple[float, List[str]]]:
        """Sum component prices: "巨无霸可乐组合" → 巨无霸(¥26) + 可乐(¥9.5)."""
        remaining = normalize_name(desc)
        picked: List[str] = []
        total = 0.0
        want_large = _is_large_format(desc)

        progressed = True
        while progressed and len(remaining) >= 2:
            progressed = False
            for comp, price, is_large in self._components:
                # Single-character menu items ("派" ¥8.5) are legitimate dishes,
                # so no minimum length here. Longest-first ordering means they
                # are only reached after every longer component has been tried.
                if not comp or comp in picked or comp in _STOPWORDS:
                    continue
                if not want_large and is_large:
                    continue
                if comp in remaining:
                    picked.append(comp)
                    total += price
                    remaining = remaining.replace(comp, "", 1)
                    progressed = True
                    break

        # A lone component is acceptable when the name also says it is a bundle
        # or pick-any-one deal ("香芋派任选"): the wrapper promises at least one
        # item, so the single matched component is a fair lower-bound proxy.
        has_wrapper = any(w in str(desc) for w in ("任选", "组合", "套餐", "拼盘"))
        if len(picked) < 2 and not has_wrapper:
            return None
        if not picked:
            return None
        return round(total, 2), picked

    def _category(self, desc: str) -> Optional[Tuple[CategoryStats, float]]:
        """Match a vague description onto a menu category.

        Handles coupons like 「指定小食任选」 or 「小食四件套」 that name a
        category rather than a dish. No dish-level price exists, but the
        category's own price distribution is real data.
        """
        # Strip filler words BEFORE tokenising, not after. Tokenising first and
        # filtering later leaves junk bigrams that straddle the removed words —
        # "指定小食任选" becomes 指定/定小/小食/食任/任选, and only one of those
        # five is real signal, capping the score at 0.2 and rejecting a
        # perfectly good category match.
        cleaned = normalize_name(desc)
        for stop in _STOPWORDS:
            if stop:
                cleaned = cleaned.replace(stop, "")
        wanted = _tokens(cleaned)
        if not wanted:
            return None

        # "指定小食任选" tokenises to 小食, which matches BOTH 小食甜品/其他 and
        # 小食拼盘/多人餐. The latter is full of ¥120 sharing platters, so
        # picking it turns a ¥13 snack coupon into an ¥89 one. Unless the
        # coupon itself says sharing/platter, those categories are out.
        want_large = _is_large_format(desc)

        scored: List[Tuple[float, CategoryStats]] = []
        for cat in self.categories:
            if not want_large and any(t in cat.name for t in _LARGE_FORMAT):
                continue
            hay = normalize_name(cat.name)
            hits = sum(1 for t in wanted if t in hay)
            if not hits:
                continue
            scored.append((hits / len(wanted), cat))

        if not scored:
            return None
        best_score = max(s for s, _ in scored)
        if best_score < 0.5:
            return None
        # Ties are common; among equally good matches prefer the cheaper
        # category. Over-estimating a coupon is the expensive mistake here.
        tied = [c for s, c in scored if s >= best_score]
        chosen = min(tied, key=lambda c: c.median)
        return chosen, best_score

    # ------------------------------------------------------------------
    def resolve(self, desc: str) -> Optional["PriceEstimate"]:
        """Walk the estimation ladder and return the best available estimate."""
        if not desc:
            return None
        norm = normalize_name(desc)

        exact = self._by_norm.get(norm)
        if exact is not None:
            return PriceEstimate(
                point=exact.list_price, low=exact.list_price, high=exact.list_price,
                method="exact", matched=exact.name, confidence=1.0,
            )

        # "2份板烧鸡腿堡" — a count times a single item. Without this branch the
        # count is ignored and the coupon is priced as ONE burger, understating
        # the saving by half (¥1.10 instead of ¥25.10 on the live account).
        #
        # Exact-lookup ONLY. A fuzzy base here is dangerous: "麦辣鸡腿堡" would
        # fuzzy-match 麦辣鸡腿堡四件套 (¥58, already a bundle) and then get
        # doubled to ¥116 — a bundle inside a multipack, compounding twice.
        # If the single item is not in the menu verbatim, fall through to the
        # normal ladder instead of inventing a multiplied price.
        m = re.match(r"^(\d{1,2})\s*份\s*(.+)$", str(desc).strip())
        if m:
            count = int(m.group(1))
            base = self._by_norm.get(normalize_name(m.group(2)))
            if 1 < count <= 10 and base is not None:
                return PriceEstimate(
                    point=round(base.list_price * count, 2),
                    low=round(base.list_price * count, 2),
                    high=round(base.list_price * count, 2),
                    method="exact",
                    matched=f"{count}×{base.name}",
                    confidence=1.0,
                )

        hit = self._direct(desc)
        if hit is not None:
            price, name, score = hit
            return PriceEstimate(
                point=price, low=price, high=price,
                method="fuzzy", matched=name, confidence=min(0.9, score),
            )

        combo = self._decompose(desc)
        if combo is not None:
            total, parts = combo
            return PriceEstimate(
                point=total, low=total, high=total,
                method="components", matched="+".join(parts), confidence=0.7,
            )

        cat = self._category(desc)
        if cat is not None:
            stats, score = cat
            return PriceEstimate(
                point=stats.median, low=stats.low, high=stats.high,
                method="category", matched=f"{stats.name}（{stats.size} 项）",
                confidence=min(0.55, score),
                note="按菜单同类目价格分布估算",
            )

        return None


@dataclass
class PriceEstimate:
    """A reference price with an explicit uncertainty band."""

    point: float
    low: float
    high: float
    method: str  # exact | fuzzy | components | category
    matched: Optional[str] = None
    confidence: float = 0.0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "point": round(self.point, 2),
            "low": round(self.low, 2),
            "high": round(self.high, 2),
            "method": self.method,
            "matched": self.matched,
            "confidence": round(self.confidence, 2),
        }


# ----------------------------------------------------------------------
# coupon parsing
# ----------------------------------------------------------------------


@dataclass
class CouponSpec:
    raw: str
    kind: str = "unknown"  # bundle | discount | instant | points | unknown
    price_off: Optional[float] = None
    rate: Optional[float] = None
    amount_off: Optional[float] = None
    award_points: Optional[float] = None
    subject: str = ""

    @property
    def is_resolvable(self) -> bool:
        return self.kind in ("bundle", "discount", "instant", "points")


_BUNDLE_RE = re.compile(r"^([\d.]+)\s*元\s*(.+)$")
_DISCOUNT_RE = re.compile(r"([\d.]+)\s*折")
_INSTANT_RE = re.compile(r"(?:立减|减免|减)\s*([\d.]+)\s*元")
_POINTS_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*积分$")


def parse_coupon(raw: str) -> CouponSpec:
    """Classify a coupon name into an actionable spec."""
    text = str(raw or "").strip()
    spec = CouponSpec(raw=text)

    m = _POINTS_RE.search(text)
    if m:
        spec.kind = "points"
        spec.award_points = float(m.group(1))
        return spec

    m = _INSTANT_RE.search(text)
    if m:
        spec.kind = "instant"
        spec.amount_off = float(m.group(1))
        spec.subject = text
        return spec

    m = _DISCOUNT_RE.search(text)
    if m:
        rate = float(m.group(1))
        if rate > 10:  # "95折" means 95%, not 9.5%
            rate /= 10.0
        spec.kind = "discount"
        spec.rate = rate / 10.0 if rate > 1 else rate
        spec.subject = _DISCOUNT_RE.sub("", text).replace("券", "").strip()
        return spec

    m = _BUNDLE_RE.match(text)
    if m:
        spec.kind = "bundle"
        spec.price_off = float(m.group(1))
        spec.subject = m.group(2).strip()
        return spec

    return spec


@dataclass
class DealValue:
    """Result of valuing one coupon against the live menu.

    `benefit_cny` is the point estimate; `benefit_low`/`benefit_high` carry the
    band so a category-derived estimate is never presented as a matched price.
    """

    spec: CouponSpec
    benefit_cny: Optional[float] = None
    benefit_low: Optional[float] = None
    benefit_high: Optional[float] = None
    basis: str = "unresolved"
    list_price: Optional[float] = None
    matched_name: Optional[str] = None
    match_method: Optional[str] = None
    confidence: float = 0.0
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.benefit_cny is not None

    @property
    def is_estimate(self) -> bool:
        return self.match_method in ("category", "components")


def value_coupon(
    spec: CouponSpec, index: MealIndex, points_ppv: Optional[float] = None
) -> DealValue:
    """Turn a coupon spec into an RMB benefit band.

    bundle   → [list_low, list_high] − cash_price
    discount → list × (1 − rate)
    instant  → amount_off
    points   → award × PPV
    """
    if spec.kind == "instant":
        amount = spec.amount_off or 0.0
        return DealValue(
            spec=spec, benefit_cny=amount, benefit_low=amount, benefit_high=amount,
            basis="face_value", confidence=1.0, note="券面直接标注金额",
        )

    if spec.kind == "points":
        if spec.award_points is None or not points_ppv:
            return DealValue(spec=spec, basis="needs_ppv", note="缺少积分汇率，暂不估值")
        value = spec.award_points * points_ppv / 100.0
        return DealValue(
            spec=spec, benefit_cny=value, benefit_low=value, benefit_high=value,
            basis="points_converted", confidence=0.8,
            note=f"按 {points_ppv:.2f} 元/百分折算",
        )

    estimate = index.resolve(spec.subject) if spec.subject else None
    if estimate is None:
        return DealValue(spec=spec, basis="no_menu_match", note="菜单中找不到对应商品或类目")

    low, high, point = estimate.low, estimate.high, estimate.point

    if spec.kind == "bundle":
        pay = spec.price_off or 0.0
        benefit = point - pay
        if benefit <= 0:
            return DealValue(
                spec=spec, benefit_cny=0.0, benefit_low=0.0, benefit_high=0.0,
                basis="no_discount", list_price=point, matched_name=estimate.matched,
                match_method=estimate.method, note="折算后无价差，兑换不产生收益",
            )
        return DealValue(
            spec=spec,
            benefit_cny=round(benefit, 2),
            benefit_low=round(max(0.0, low - pay), 2),
            benefit_high=round(max(0.0, high - pay), 2),
            basis="bundle_spread", list_price=point, matched_name=estimate.matched,
            match_method=estimate.method, confidence=estimate.confidence,
            note=estimate.note,
        )

    if spec.kind == "discount":
        keep = 1.0 - (spec.rate or 1.0)
        return DealValue(
            spec=spec,
            benefit_cny=round(point * keep, 2),
            benefit_low=round(low * keep, 2),
            benefit_high=round(high * keep, 2),
            basis="discount_spread", list_price=point, matched_name=estimate.matched,
            match_method=estimate.method, confidence=estimate.confidence,
            note=estimate.note,
        )

    return DealValue(spec=spec, basis="unknown_kind", note="券型无法识别")
