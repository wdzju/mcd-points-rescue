"""Turning "points" into "RMB": the pricing engine.

Why this exists
---------------
A mall item costs N points but has no RMB price tag. A menu item costs M RMB
but no points. Without a bridge, every "is this redemption worth it?" question
is guesswork. This module builds that bridge:

    reference_cny = best real-menu proxy for the mall item
    ppv           = reference_cny / points * 100        (RMB per 100 points)

Everything is scored and its provenance tracked, so the report can say
"this valuation came from an exact menu match" vs "category median fallback".
Unpriced items are reported as unpriced rather than silently counted as zero.
"""

from __future__ import annotations

import re
import statistics
from typing import Dict, List, Optional, Sequence, Tuple

from .models import MallProduct, MenuAnchor, Valuation

# Suffixes that turn a menu meal into a redemption SKU.
_NOISE = [
    "兑换券",
    "优惠券",
    "免费券",
    "电子券",
    "兑换码",
    "券",
    "（）",
    "()",
    "限量",
    "新品",
    "会员专享",
    "专享",
    "麦麦商城",
]

_PAREN_RE = re.compile(r"[（(\[][^）)\]]*[）)\]]")
_QUANTITY_RE = re.compile(r"(\d+)\s*(块|只|份|杯|个|枚| pairs?)")

# Quantity words inside product names ("麦辣鸡翅2块装") destructure the match.
_STOPWORDS = {"套餐", "组合", "单人", "双人", "三人", "家庭", "装", "超值", "精选"}


def normalize_name(raw: str) -> str:
    """Lower-case, unify width, strip send word noise and punctuation."""
    if not raw:
        return ""
    text = str(raw)
    # full-width -> half-width
    text = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in text)
    text = text.lower()
    text = _PAREN_RE.sub("", text)
    for noise in _NOISE:
        text = text.replace(noise, "")
    text = re.sub(r"[^\w一-鿿]+", "", text)
    for stop in _STOPWORDS:
        text = text.replace(stop, "")
    return text.strip()


def _tokens(text: str) -> List[str]:
    """Split a Chinese product name into comparable chunks."""
    norm = normalize_name(text)
    if not norm:
        return []
    # CJK runs are split into 2-grams; latin words stay whole.
    tokens: List[str] = []
    han_run = ""
    for ch in norm:
        if "一" <= ch <= "鿿":
            han_run += ch
        else:
            if han_run:
                tokens.extend(han_run[i : i + 2] for i in range(len(han_run) - 1))
                han_run = ""
            if ch.strip():
                tokens.append(ch)
    if han_run:
        if len(han_run) == 1:
            tokens.append(han_run)
        else:
            tokens.extend(han_run[i : i + 2] for i in range(len(han_run) - 1))
    return tokens


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def match_score(product_name: str, anchor_name: str) -> float:
    """Similarity in [0, 1] between a mall item and a menu item."""
    p, a = normalize_name(product_name), normalize_name(anchor_name)
    if not p or not a:
        return 0.0
    if p == a:
        return 1.0
    if len(p) >= 2 and p in a:
        return 0.95
    if len(a) >= 2 and a in p:
        return 0.92
    pt, at = _tokens(product_name), _tokens(anchor_name)
    return min(0.9, _jaccard(pt, at) * 1.35)


class PriceBook:
    """Maps mall redemption items onto real money using menu anchors."""

    # Below this we refuse to claim a match.
    ACCEPT_THRESHOLD = 0.55

    def __init__(self, anchors: Sequence[MenuAnchor]) -> None:
        self.anchors: List[MenuAnchor] = list(anchors)
        self._index: Dict[str, List[Tuple[MenuAnchor, float]]] = {}
        self.category_prices: Dict[str, List[float]] = {}
        self._build()

    def _build(self) -> None:
        seen: Dict[str, MenuAnchor] = {}
        for anchor in self.anchors:
            key = normalize_name(anchor.name)
            if key and key not in seen:
                seen[key] = anchor
        self.anchors = list(seen.values())
        for anchor in self.anchors:
            for token in set(_tokens(anchor.name)):
                self._index.setdefault(token, []).append((anchor, 1.0))
        for anchor in self.anchors:
            self.category_prices.setdefault(self._category_of(anchor.name), []).append(
                anchor.price_cny
            )

    # Merchandise has no menu proxy whatsoever, so it must never inherit a
    # category median — a limited-edition figure priced at the burger median
    # would look authoritative while being meaningless.
    FOOD_TABLE = [
        ("汉堡", "burger"),
        ("堡", "burger"),
        ("薯条", "side"),
        ("薯格", "side"),
        ("玉米", "side"),
        ("鸡块", "side"),
        ("洋葱圈", "side"),
        ("沙拉", "side"),
        ("鸡翅", "chicken"),
        ("脆汁鸡", "chicken"),
        ("炸鸡", "chicken"),
        ("鸡腿", "chicken"),
        ("鸡", "chicken"),
        ("翅", "chicken"),
        ("甜筒", "dessert"),
        ("旋风", "dessert"),
        ("圣代", "dessert"),
        ("冰淇淋", "dessert"),
        ("派", "dessert"),
        ("蛋糕", "dessert"),
        ("可颂", "dessert"),
        ("咖啡", "drink"),
        ("可乐", "drink"),
        ("雪碧", "drink"),
        ("芬达", "drink"),
        ("牛奶", "drink"),
        ("豆浆", "drink"),
        ("汽水", "drink"),
        ("橙汁", "drink"),
        ("茶", "drink"),
        ("满分", "breakfast"),
        ("早餐", "breakfast"),
        ("粥", "breakfast"),
        ("油条", "breakfast"),
        ("汤", "soup"),
    ]
    MERCH_TABLE = [
        "公仔", "玩偶", "周边", "随行杯", "马克杯", "保温杯", "水杯", "玻璃杯",
        "杯垫", "玩具", "积木", "背包", "帆布袋", "环保袋", "雨伞", "服饰",
        "帽子", "袜子", "手办", "模型", "盲盒", "贴纸", "徽章", "钥匙扣",
        "鼠标垫",
    ]

    @classmethod
    def _category_of(cls, name: str) -> str:
        norm = normalize_name(name)
        for token in cls.MERCH_TABLE:
            if normalize_name(token) in norm or token in str(name):
                return "merch"
        for token, cat in cls.FOOD_TABLE:
            if token in norm:
                return cat
        return "other"

    def best_anchor(self, product_name: str) -> Tuple[Optional[MenuAnchor], float]:
        """Return the closest menu anchor above threshold, if any."""
        best: Optional[MenuAnchor] = None
        best_score = 0.0
        # Candidate filtering keeps this off O(n^2) for large menus.
        wanted = set(_tokens(product_name))
        candidates = list(self.anchors)
        if wanted:
            shortlist: Dict[str, MenuAnchor] = {}
            for token in wanted:
                for anchor, _ in self._index.get(token, []):
                    shortlist[normalize_name(anchor.name)] = anchor
            if shortlist:
                candidates = list(shortlist.values())
        for anchor in candidates:
            score = match_score(product_name, anchor.name)
            if score > best_score:
                best_score, best = score, anchor
        if best_score < self.ACCEPT_THRESHOLD or best is None:
            return None, best_score
        return best, best_score

    def fallback_value(self, product_name: str) -> Tuple[Optional[float], str]:
        """Category median — and only when the item is unambiguously food.

        `merch` and `other` are refused on purpose. We would rather show an
        honest "无法估值" than a fabricated number.
        """
        category = self._category_of(product_name)
        if category in ("merch", "other"):
            return None, "unpriced"
        prices = self.category_prices.get(category)
        if not prices:
            return None, "unpriced"
        return float(statistics.median(prices)), f"category_median:{category}"

    def valuate(self, product: MallProduct) -> Valuation:
        if product.points is None or product.points <= 0:
            return Valuation(
                product=product,
                reference_cny=None,
                reference_source="no_points_price",
                ppv=None,
            )

        if self._category_of(product.name) == "merch":
            return Valuation(
                product=product,
                reference_cny=None,
                reference_source="unpriced_merch",
                ppv=None,
            )

        anchor, score = self.best_anchor(product.name)
        if anchor is not None:
            value, source = anchor.price_cny, "menu_exact"
        else:
            value, source = self.fallback_value(product.name)
            if value is None:
                return Valuation(
                    product=product,
                    reference_cny=None,
                    reference_source="unpriced",
                    ppv=None,
                    match_score=score,
                )

        ppv = value / product.points * 100.0
        return Valuation(
            product=product,
            reference_cny=round(value, 2),
            reference_source=source,
            ppv=round(ppv, 3),
            match_score=round(score, 3),
            total_value=round(value, 2),
        )

    def valuate_all(self, products: Sequence[MallProduct]) -> List[Valuation]:
        return [self.valuate(p) for p in products]

    @property
    def anchor_count(self) -> int:
        return len(self.anchors)
