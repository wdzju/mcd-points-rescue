"""Data models plus a defensive field resolver for McDonald's MCP payloads.

The official MCP Server documents its tools but not its exact response schema,
so every extraction goes through `dig()`, a tolerant resolver that walks the
payload and matches field aliases (English + Chinese) at any nesting depth.
Unknown payload shapes therefore degrade to None instead of crashing, and
`--dump-raw` lets anyone capture the real shape and extend the alias tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------
# tolerant extraction helpers
# ----------------------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]", "", str(key).lower())


def dig(obj: Any, *names: str, default: Any = None) -> Any:
    """Find the first occurrence of any alias name anywhere inside `obj`.

    Depth-first, top-down. Scalars are compared only against an exact alias
    match of their parent key, so we never accidentally pull a nested number
    from an unrelated subtree before checking shallower keys.
    """
    wanted = {_norm_key(n) for n in names}
    found: List[Any] = []

    def walk(node: Any, depth: int) -> None:
        if found:
            return
        if isinstance(node, dict):
            # shallow keys first
            for key, value in node.items():
                if _norm_key(key) in wanted and value is not None:
                    found.append(value)
                    return
            for value in node.values():
                walk(value, depth + 1)
                if found:
                    return
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)
                if found:
                    return

    walk(obj, 0)
    return found[0] if found else default


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", ""))
        if match:
            try:
                return int(float(match.group()))
            except ValueError:
                return default
    return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _NUMBER_RE.search(value.replace(",", ""))
        if match:
            try:
                return float(match.group())
            except ValueError:
                return default
    return default


def parse_percent(value: Any) -> Optional[float]:
    """0.0825 / 8.25 / "8.25%" / "8.25 %" -> 0.0825 (or None)."""
    raw = to_float(value)
    if raw is None and isinstance(value, str):
        match = _NUMBER_RE.search(value)
        raw = float(match.group()) if match else None
    if raw is None:
        return None
    if isinstance(value, str) and "%" in value:
        return raw / 100.0
    return raw / 100.0 if raw > 1 else raw


_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y%m%d",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # possible epoch seconds / milliseconds
        stamp = float(value)
        if stamp > 1e12:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        # Chinese dates sometimes carry a time part after a space
        text = text.split(" ")[0] if ("年" not in text and " " in text) else text
        for pattern in _DATE_PATTERNS:
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        match = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                return None
    return None


def iter_records(payload: Any) -> List[Dict[str, Any]]:
    """Flatten the common wrapper shapes into a list of dict records."""
    if payload is None:
        return []
    if isinstance(payload, list):
        if all(isinstance(x, dict) for x in payload):
            return list(payload)
        if len(payload) == 1:
            return iter_records(payload[0])
        return []
    if isinstance(payload, dict):
        for key in (
            "items",
            "list",
            "records",
            "data",
            "result",
            "results",
            "products",
            "productList",
            "prizeList",
            "prizes",
            "lotteryPrizes",
        ):
            value = payload.get(key)
            if isinstance(value, list) and (not value or isinstance(value[0], dict)):
                return list(value)
        # text blob pretending to be a payload
        text = payload.get("text")
        if isinstance(text, str):
            try:
                import json

                return iter_records(json.loads(text))
            except Exception:
                return []
    return []


# ----------------------------------------------------------------------
# domain models
# ----------------------------------------------------------------------


@dataclass
class PointAccount:
    """Snapshot of the user's McDonald's point balance.

    Real field names observed on mcp.mcd.cn / query-my-account:

        availablePoint            "556.5"   usable balance
        accumulativePoint         "5358.7"  lifetime earned
        usedPoint                 "2447"    lifetime spent
        frozenPoint               "0"       frozen
        expiredPoint              "2355.2"  ALREADY LOST to expiry
        currentMouthExpirePoint   "166"     expiring this month
        lastMouthExpirePoint      "0"       expired last month
        nextMouthExpirePoint      "0"       expiring next month
        currency                  "麦享会积分"

    Yes — that is "Mouth", not "Month". It is their typo, not ours, and we have
    to spell it their way or nothing parses. The alias table accepts both.

    Every numeric arrives as a STRING and may carry decimals, hence to_float.
    """

    # NOTE: "accumulative" (not the dictionary spelling) is what the API sends.
    available: Optional[float] = None
    accumulated: Optional[float] = None
    used: Optional[float] = None
    frozen: Optional[float] = None
    expired: Optional[float] = None
    expiring_soon: Optional[float] = None
    expiring_next_month: Optional[float] = None
    expired_last_month: Optional[float] = None
    currency: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> "PointAccount":
        payload = payload if isinstance(payload, dict) else {}
        return cls(
            available=to_float(
                dig(
                    payload,
                    "availablePoint",
                    "availablePoints",
                    "available",
                    "balance",
                    "pointsBalance",
                    "usablePoints",
                    "currentPoints",
                    "可用积分",
                    "积分余额",
                )
            ),
            accumulated=to_float(
                dig(
                    payload,
                    "accumulativePoint",
                    "accumulativePoints",
                    "totalPoints",
                    "accumulatedPoints",
                    "cumulativePoints",
                    "累计积分",
                )
            ),
            used=to_float(dig(payload, "usedPoint", "usedPoints", "已使用积分")),
            frozen=to_float(
                dig(payload, "frozenPoint", "frozenPoints", "freezePoints", "冻结积分")
            ),
            expired=to_float(dig(payload, "expiredPoint", "expiredPoints", "已过期积分")),
            expiring_soon=to_float(
                dig(
                    payload,
                    "currentMouthExpirePoint",
                    "currentMonthExpirePoint",
                    "expiringPoint",
                    "expiringPoints",
                    "expiringSoonPoint",
                    "本月将过期积分",
                    "即将过期积分",
                )
            ),
            expiring_next_month=to_float(
                dig(payload, "nextMouthExpirePoint", "nextMonthExpirePoint", "下月将过期积分")
            ),
            expired_last_month=to_float(
                dig(payload, "lastMouthExpirePoint", "lastMonthExpirePoint", "上月已过期积分")
            ),
            currency=dig(payload, "currency", "货币类型"),
            raw_payload=payload,
        )

    @property
    def lost_ratio(self) -> Optional[float]:
        """Share of lifetime points already burned by expiry."""
        if not self.accumulated or self.expired is None or self.accumulated <= 0:
            return None
        return self.expired / self.accumulated


@dataclass
class MallProduct:
    """A redemption item inside 麦麦商城."""

    product_id: Optional[str] = None
    name: str = "未命名商品"
    points: Optional[int] = None
    cash_price: Optional[float] = None
    image: Optional[str] = None
    valid_days: Optional[int] = None
    category: Optional[str] = None
    raw: Any = None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "MallProduct":
        return cls(
            product_id=str(
                dig(payload, "productId", "id", "skuId", "code", "商品编号", "商品ID")
                or ""
            )
            or None,
            name=str(
                dig(payload, "productName", "name", "title", "商品名称", "名称")
                or "未命名商品"
            ),
            points=to_int(
                dig(
                    payload,
                    "points",
                    "point",
                    "pointsPrice",
                    "exchangePoints",
                    "needPoints",
                    "积分价",
                    "所需积分",
                )
            ),
            cash_price=to_float(
                dig(payload, "price", "cashPrice", "salePrice", "rmb", "售价", "价格")
            ),
            image=dig(payload, "image", "imageUrl", "picUrl", "picture", "商品图片"),
            valid_days=to_int(
                dig(payload, "validDays", "validityDays", "有效期", "有效天数")
            ),
            category=dig(payload, "category", "categoryName", "type", "分类"),
            raw=payload,
        )


@dataclass
class Valuation:
    """A mall product scored by how much RMB one point buys."""

    product: MallProduct
    reference_cny: Optional[float]
    reference_source: str
    ppv: Optional[float]  # RMB per 100 points
    match_score: float = 0.0
    total_value: Optional[float] = None

    @property
    def affordable(self) -> bool:
        return self.product.points is not None





@dataclass
class MenuAnchor:
    """A real-menu item used to price a mall redemption product."""

    name: str
    price_cny: float
    product_code: Optional[str] = None
    meal_id: Optional[str] = None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> Optional["MenuAnchor"]:
        price = to_float(
            dig(payload, "price", "salePrice", "originalPrice", "amount", "售价", "价格")
        )
        name = dig(payload, "name", "productName", "mealName", "title", "名称", "餐品名称")
        if price is None or not name:
            return None
        return cls(
            name=str(name),
            price_cny=price,
            product_code=str(dig(payload, "code", "productCode", "mealCode", "编码") or "")
            or None,
            meal_id=str(dig(payload, "mealId", "id", "skuId") or "") or None,
        )
