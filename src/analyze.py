"""Orchestration layer: fetch -> resolve -> value -> optimise -> decide.

Live pipeline (the real one, discovered against mcp.mcd.cn):

    query-my-account            balance + expiry buckets
    query-nearby-stores         needs city+keyword -> storeCode
    query-meals                 needs storeCode    -> the ONLY source of RMB prices
    mall-points-products        redemption catalogue (all discount coupons)
    query-lottery-info          prize pool (also all coupons)
    query-my-prizes             win history, used to sanity-check the pool

Two findings drive the design:

1. `query-meals` refuses to run without a storeCode, so pricing depends on a
   store lookup first. No store means no prices, which means no valuations --
   the tool must fail loudly rather than silently return zeros.

2. Every redemption is a discount coupon, so its payout is always a SPREAD
   (list price minus what you pay), never a sticker price. See deal_engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .calibrate import Calibration, calibrate
from .deal_engine import CouponSpec, DealValue, MealIndex, parse_coupon, value_coupon
from .models import PointAccount, to_float
from .mcp_payload import ApiError, check_response, unwrap, unwrap_data
from .planning import Bucket, SaveUpTarget, save_up_targets, split_points
from .preference import Preference, build_preference
from .redeem_rate import (
    RedemptionProfile,
    Window,
    apply_haircut,
    build_profile,
    redemption_window,
)

try:  # package import
    from .demo_data import fake_account, fake_lottery, fake_mall_products, fake_menu, fake_my_prizes
except ImportError:  # script-mode import
    from demo_data import fake_account, fake_lottery, fake_mall_products, fake_menu, fake_my_prizes


DEFAULT_CITY = "上海市"
DEFAULT_KEYWORD = "麦当劳"
ORDER_TYPE_INSTORE = 1
BE_TYPE_PICKUP = 1
# Upper bound on the knapsack table size; keeps a pathological --budget from
# allocating gigabytes.
MAX_DP_CAPACITY = 200_000


@dataclass
class Redemption:
    """One points redemption item, valued end-to-end."""

    product_id: Optional[str]
    name: str
    points: Optional[float]
    spec: Optional[CouponSpec]
    value: Optional[DealValue]
    category: Optional[str] = None
    window: Optional[Window] = None
    image: Optional[str] = None

    @property
    def benefit(self) -> Optional[float]:
        """Gross saving, before the second-loss haircut."""
        return self.value.benefit_cny if self.value else None

    affinity: float = 1.0
    affinity_hit: Optional[str] = None

    @property
    def ppv(self) -> Optional[float]:
        """RMB saved per 100 points (objective, gross)."""
        if self.benefit is None or not self.points or self.points <= 0:
            return None
        return self.benefit / self.points * 100.0

    @property
    def ppv_personal(self) -> Optional[float]:
        """Objective PPV scaled by how much you actually buy this item."""
        return None if self.ppv is None else round(self.ppv * self.affinity, 3)

    @property
    def is_estimate(self) -> bool:
        return bool(self.value and self.value.is_estimate)

    @property
    def closing_soon(self) -> bool:
        return bool(self.window and self.window.urgency in ("urgent", "soon"))

    @property
    def window_label(self) -> str:
        if not self.window or self.window.days_left is None:
            return ""
        days = self.window.days_left
        if days <= 0:
            return ""
        if days <= 7:
            return f"{days} 天后停止兑换"
        if days <= 30:
            return f"{days} 天后截止"
        return ""


@dataclass
class ClearanceItem:
    name: str
    count: int
    points_each: float
    value_each: float

    @property
    def total_points(self) -> float:
        return self.count * self.points_each

    @property
    def total_value(self) -> float:
        return round(self.count * self.value_each, 2)


@dataclass
class PrizeRow:
    name: str
    spec: CouponSpec
    value: Optional[DealValue]
    probability: Optional[float] = None
    image: Optional[str] = None

    @property
    def benefit(self) -> Optional[float]:
        return self.value.benefit_cny if self.value else None

    @property
    def ev_contribution(self) -> float:
        return (self.benefit or 0.0) * (self.probability or 0.0)


@dataclass
class LotteryReport:
    activity_name: Optional[str]
    status_text: Optional[str]
    cost_points: Optional[float]
    draw_type_text: Optional[str]
    available_point: Optional[float]
    rows: List[PrizeRow]
    scenarios: Dict[str, float] = field(default_factory=dict)
    probability_basis: str = "unavailable"
    calibration: Optional["Calibration"] = None
    priced_count: int = 0
    unpriced: List[str] = field(default_factory=list)
    affordable_draws: Optional[int] = None
    note: str = ""

    @property
    def headline_ev(self) -> Optional[float]:
        return self.scenarios.get("realistic")

    def ppv(self, scenario: str = "realistic") -> Optional[float]:
        ev = self.scenarios.get(scenario)
        if ev is None or not self.cost_points:
            return None
        return ev / self.cost_points * 100.0


@dataclass
class ReportData:
    mode: str
    generated_at: str
    account: PointAccount
    store_label: Optional[str]
    menu_items: int
    redemptions: List[Redemption]
    best_ppv: Optional[float]
    plan: List[ClearanceItem]
    plan_points: float
    plan_value: float
    plan_leftover: float
    budget: float
    lottery: Optional[LotteryReport]
    history: List[Dict[str, Any]]
    verdict: Tuple[str, str]
    profile: Optional[RedemptionProfile] = None
    plan_net_value: float = 0.0
    preference: Optional[Preference] = None
    bucket: Optional[Bucket] = None
    save_up: List[SaveUpTarget] = field(default_factory=list)
    menu_price_items: List[Tuple[str, float]] = field(default_factory=list)
    menu_period: str = "unknown"
    warnings: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def coverage(self) -> Tuple[int, int]:
        """(priced, total) — how much of the catalogue we could actually value."""
        return (len([r for r in self.redemptions if r.ppv is not None]), len(self.redemptions))

    @property
    def coverage_pct(self) -> Optional[float]:
        priced, total = self.coverage
        return (priced / total * 100.0) if total else None

    @property
    def estimate_count(self) -> int:
        """Items valued by category/component estimation rather than a match."""
        return len([r for r in self.redemptions if r.ppv is not None and r.is_estimate])

    @property
    def expired_points(self) -> Optional[float]:
        payload = self.account.raw_payload or {}
        return to_float(payload.get("expiredPoint"))

    @property
    def expired_ratio(self) -> Optional[float]:
        """Share of lifetime points already lost to expiry. The headline metric."""
        total = self.account.accumulated
        expired = self.expired_points
        if not total or expired is None or total <= 0:
            return None
        return expired / total


# ----------------------------------------------------------------------
# fetching
# ----------------------------------------------------------------------


def _call(client: Any, tool: str, args: Optional[Dict[str, Any]] = None) -> Any:
    """Call a tool, unwrap the Markdown envelope, raise on business failure."""
    raw = client.call_json(tool, args or {})
    return check_response(raw, tool)


def fetch_store_candidates(client: Any, city: str, keyword: str) -> List[Dict[str, Any]]:
    """Return candidate stores. Tries city+keyword first, then favourites."""
    attempts = [
        {"beType": BE_TYPE_PICKUP, "searchType": 2, "city": city, "keyword": keyword},
        {"beType": BE_TYPE_PICKUP, "searchType": 1},
    ]
    for args in attempts:
        try:
            resp = client.call_json("query-nearby-stores", args)
            obj = unwrap(resp)
        except ApiError:
            continue
        if obj is None or obj.get("success") is not True:
            continue
        data = unwrap_data(resp)
        records = data if isinstance(data, list) else (data or {}).get("list")
        if records:
            return [r for r in records if isinstance(r, dict) and r.get("storeCode")]
    return []


def _menu_size(menu_envelope: Any) -> int:
    data = unwrap_data(menu_envelope) or {}
    meals = data.get("meals") if isinstance(data, dict) else None
    return len(meals or {})


# Breakfast-only markers vs. main-menu markers. McDonald's swaps the whole
# catalogue around 10:30, and `query-meals` returns whatever is sellable *now*.
_BREAKFAST_MARKERS = ("早餐", "麦满分", "炒双蛋", "现磨", "早餐卡", "油条", "豆浆")
_MAIN_MEAL_MARKERS = ("四件套", "三件套", "巨无霸", "安格斯", "麦辣鸡腿汉堡", "板烧鸡腿堡", "麦乐鸡")


def detect_menu_period(menu_envelope: Any) -> Tuple[str, Dict[str, int]]:
    """Tell apart the breakfast catalogue from the main one.

    This matters more than it looks. During breakfast hours the menu simply
    does not contain most main-menu items, so coupons referencing 板烧/麦辣/四件套
    cannot be priced at all and coverage collapses (observed: 17/24 at midday
    vs 7/23 at 10am, same account, same code). The honest response is to say so
    rather than quietly publish a much weaker ranking.
    """
    data = unwrap_data(menu_envelope) or {}
    if not isinstance(data, dict):
        return "unknown", {}
    meals = data.get("meals") or {}
    names = [str(v.get("name")) for v in meals.values() if isinstance(v, dict) and v.get("name")]
    cats = [str(c.get("name") or "").replace("\n", "") for c in (data.get("categories") or [])]

    breakfast_hits = sum(1 for t in _BREAKFAST_MARKERS if any(t in n for n in names))
    breakfast_cats = sum(1 for c in cats if any(t in c for t in _BREAKFAST_MARKERS))
    main_hits = sum(1 for t in _MAIN_MEAL_MARKERS if any(t in n for n in names))

    breakfast_signal = breakfast_hits + breakfast_cats
    stats = {
        "items": len(names),
        "breakfast_signals": breakfast_signal,
        "main_signals": main_hits,
    }

    # Compare signal STRENGTH rather than requiring a clean zero. A breakfast
    # menu can still contain one main-menu token by accident (麦乐鸡 as a side,
    # or 板烧 inside 板烧鸡腿麦满分) — demanding main_hits == 0 left that
    # boundary case classified as "unknown" and silently suppressed the warning.
    if breakfast_signal >= 3 and breakfast_signal > main_hits * 3:
        return "breakfast", stats
    if main_hits >= 2:
        return "regular", stats
    if breakfast_signal == 0 and main_hits == 0:
        return "unknown", stats
    return ("breakfast" if breakfast_signal > main_hits else "regular"), stats


def resolve_store_and_menu(
    client: Any,
    city: str,
    keyword: str,
    store_override: Optional[str] = None,
    probe: int = 5,
) -> Tuple[Optional[str], Optional[str], Any, List[str]]:
    """Pick a store and load its menu.

    Store search returns the nearest few branches, ordered by distance — which
    is derived from IP geolocation and therefore unstable. Menus differ
    materially between branches (73 vs 101 items in the same city), and a
    thinner menu means fewer single items to price coupons against, which
    silently collapses coverage.

    So: never trust the first result. Probe the first few and keep the one with
    the richest menu. `store_override` lets the caller pin an exact branch.
    """
    notes: List[str] = []

    def load(code: str) -> Any:
        return _call(
            client,
            "query-meals",
            {"storeCode": code, "orderType": ORDER_TYPE_INSTORE, "beType": BE_TYPE_PICKUP},
        )

    if store_override:
        code = str(store_override).strip()
        try:
            menu = load(code)
            return code, f"手动指定（{code}）", menu, [f"使用手动指定的门店 {code}"]
        except Exception as exc:  # noqa: BLE001
            notes.append(f"手动指定的门店 {code} 菜单加载失败：{exc}")
            return None, None, None, notes

    candidates = fetch_store_candidates(client, city, keyword)
    if not candidates:
        notes.append("未能搜索到门店，请用 --city / --keyword 指定可搜索到的门店")
        return None, None, None, notes

    best: Optional[Tuple[int, Dict[str, Any], Any]] = None
    probed = 0
    for cand in candidates[: max(1, probe)]:
        code = str(cand.get("storeCode"))
        try:
            menu = load(code)
        except Exception:  # noqa: BLE001
            continue
        probed += 1
        size = _menu_size(menu)
        if size > 0 and (best is None or size > best[0]):
            best = (size, cand, menu)

    if best is None:
        notes.append("候选门店的菜单都加载失败")
        return None, None, None, notes

    size, cand, menu = best
    code = str(cand.get("storeCode"))
    label = f"{cand.get('storeName') or '未命名门店'}（{code}）"
    if probed > 1:
        notes.append(f"对比了 {probed} 家门店，选用菜单最全的一家（{size} 项餐品）")
    return code, label, menu, notes


def load_live(
    client: Any, city: str, keyword: str, store_override: Optional[str] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """Pull every upstream resource needed for an analysis."""
    warnings: List[str] = []
    bundle: Dict[str, Any] = {}

    try:
        bundle["account"] = _call(client, "query-my-account")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"query-my-account 不可用：{exc}")
        bundle["account"] = None

    store_code, store_label, menu, store_notes = resolve_store_and_menu(
        client, city, keyword, store_override
    )
    warnings.extend(store_notes)
    bundle["store_label"] = store_label
    bundle["menu"] = menu
    period, period_stats = detect_menu_period(menu)
    bundle["menu_period"] = period
    bucket = bundle.setdefault("_meta", {})
    bucket["menu_period"] = period
    bucket["menu_stats"] = period_stats
    if period == "breakfast":
        warnings.append(
            "当前拉取的是早餐时段菜单（约 10:30 前），其中几乎没有正餐单品，"
            "因此多数正餐券无法估值、覆盖率会显著偏低。"
            "建议在 10:30 之后重跑，或直接参考 docs/sample-report.html 的正餐时段结果。"
        )
    if store_code is None:
        warnings.append(
            "未能获取可用门店的菜单 —— 没有价格锚点就无法给任何券估值。"
            "请用 --city / --keyword 指定城市，或用 --store 指定门店编码。"
        )

    for key, tool in (
        ("mall", "mall-points-products"),
        ("lottery", "query-lottery-info"),
        ("prizes", "query-my-prizes"),
        ("orders", "order-list"),
    ):
        try:
            bundle[key] = _call(client, tool)
        except Exception as exc:  # noqa: BLE001
            # order-list is an enhancement, not a requirement.
            if key != "orders":
                warnings.append(f"{tool} 不可用：{exc}")
            bundle[key] = None

    return bundle, warnings


# ----------------------------------------------------------------------
# valuation
# ----------------------------------------------------------------------


def build_menu_index(menu_envelope: Any) -> MealIndex:
    data = unwrap_data(menu_envelope) or {}
    if not isinstance(data, dict):
        return MealIndex.from_payload({})
    # Categories are what make vague coupons ("指定小食任选") estimable at all.
    return MealIndex.from_payload(data.get("meals") or {}, data.get("categories") or [])


def value_redemptions(
    mall_envelope: Any, index: MealIndex, provisional_ppv: Optional[float] = None
) -> List[Redemption]:
    """Value every points-based mall item.

    Runs twice on purpose: anything denominated in points (e.g. a prize of
    "30积分") needs an exchange rate, which we can only derive after the
    cash coupons have been priced.
    """
    data = unwrap_data(mall_envelope) or []
    records = data if isinstance(data, list) else (data or {}).get("list") or []
    out: List[Redemption] = []

    for row in records:
        if not isinstance(row, dict):
            continue
        points = to_float(row.get("point"))
        # point=0 rows are straight cash purchases, not redemptions
        if points is None or points <= 0:
            continue
        name = str(row.get("spuName") or "").strip()
        if not name:
            continue
        spec = parse_coupon(name)
        value = value_coupon(spec, index, points_ppv=provisional_ppv)
        out.append(
            Redemption(
                product_id=str(row.get("spuId")) if row.get("spuId") is not None else None,
                name=name,
                points=points,
                spec=spec,
                value=value,
                category=row.get("catName"),
                window=redemption_window(row.get("downTime")),
                image=row.get("spuImage"),
            )
        )

    if provisional_ppv:
        for item in out:
            if item.benefit is None and item.value and item.value.basis == "needs_ppv":
                item.value = value_coupon(item.spec, index, points_ppv=provisional_ppv)
    return out


def provisional_rate(redemptions: Sequence[Redemption]) -> Optional[float]:
    """A rough PPV from the median of already-valued items."""
    rates = sorted(r.ppv for r in redemptions if r.ppv is not None and r.ppv > 0)
    if not rates:
        return None
    return rates[len(rates) // 2]


# ----------------------------------------------------------------------
# lottery scenarios
# ----------------------------------------------------------------------


def _probabilities(n: int, scenario: str) -> List[float]:
    """Envelope distributions used as the optimistic / pessimistic bounds.

    The headline scenario is no longer an assumption — see `calibrate`, which
    shrinks toward these priors using the account's own win history.
    """
    if n <= 0:
        return []
    if scenario == "optimistic":
        return [1.0 / n] * n

    # Prizes arrive sorted richest-first, so a real lottery hands out the cheap
    # coupons often and the headline prize rarely: probability must DECREASE
    # with position. Rank is therefore reversed (richest gets the largest rank),
    # otherwise the expensive prize would end up the most likely one and every
    # "pessimistic" number would come out larger than the optimistic one.
    exponent = 1.2 if scenario == "realistic" else 3.0
    weights = [1.0 / (n - i) ** exponent for i in range(n)]
    total = sum(weights)
    return [w / total for w in weights]


def build_lottery(
    lottery_envelope: Any,
    index: MealIndex,
    points_ppv: Optional[float],
    available: Optional[float],
    profile: Optional[RedemptionProfile] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[LotteryReport]:
    data = unwrap_data(lottery_envelope)
    if not isinstance(data, dict) or not data.get("prizes"):
        return None

    rows: List[PrizeRow] = []
    for row in data.get("prizes") or []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        spec = parse_coupon(name)
        value = value_coupon(spec, index, points_ppv=points_ppv)

        # Prizes are coupons too, and this account's prize history is exactly
        # what measures how often such coupons actually get used.
        gross = value.benefit_cny
        net = apply_haircut(gross, profile) if profile else gross
        if net is not None and gross:
            value.benefit_cny = net
            # Only annotate when a haircut actually happened. The previous
            # form appended a dangling "；" whenever the profile was unusable,
            # leaving notes like "同类目估算；".
            if profile and profile.usable and net != gross:
                value.note = (
                    (value.note + "；" if value.note else "")
                    + f"已按历史兑现率 {profile.rate * 100:.0f}% 折算"
                )
        rows.append(PrizeRow(name=name, spec=spec, value=value, image=row.get("imageUrl")))
    if not rows:
        return None

    # Richest first so decaying probability lines up with prize value.
    #
    # Unpriced prizes are spliced into the MIDDLE rather than left at the tail.
    # Left at the tail they inherit the largest prior probability (the tail is
    # where cheap prizes live) while contributing zero EV — in the live account
    # that parked ~46% of all probability mass on two coupons we simply could
    # not price, crushing the headline EV for the wrong reason. Their value is
    # unknown, not low, so the middle of the distribution is the honest slot.
    priced_rows = [r for r in rows if r.benefit is not None]
    unpriced_rows = [r for r in rows if r.benefit is None]
    priced_rows.sort(key=lambda r: (r.benefit or 0.0), reverse=True)
    mid = len(priced_rows) // 2
    rows = priced_rows[:mid] + unpriced_rows + priced_rows[mid:]

    # Headline scenario is calibrated on this account's own win history; the
    # other two remain pure assumptions and serve as the envelope.
    calibration = calibrate(
        [r.name for r in rows], [r.benefit for r in rows], history or []
    )
    dist = {
        "optimistic": _probabilities(len(rows), "optimistic"),
        "realistic": [calibration.probability_of(r.name) for r in rows],
        "pessimistic": _probabilities(len(rows), "pessimistic"),
    }

    scenarios: Dict[str, float] = {}
    for scenario, probabilities in dist.items():
        scenarios[scenario] = round(sum((r.benefit or 0.0) * p for r, p in zip(rows, probabilities)), 4)
    for row, p in zip(rows, dist["realistic"]):
        row.probability = p

    cost = to_float(data.get("drawPoint"))
    draws = int(available // cost) if cost and available is not None else None
    priced = [r for r in rows if r.benefit is not None]

    return LotteryReport(
        activity_name=data.get("activityName"),
        status_text=data.get("activityStatusText"),
        cost_points=cost,
        draw_type_text=data.get("drawTypeText"),
        available_point=to_float(data.get("availablePoint")),
        rows=rows,
        scenarios=scenarios,
        probability_basis=calibration.basis,
        calibration=calibration,
        priced_count=len(priced),
        unpriced=[r.name for r in rows if r.benefit is None],
        affordable_draws=draws,
        note=(
            "官方未公布逐档中奖概率。主口径（realistic）由你自己的历史中奖记录"
            "收缩校准得出："
            + calibration.basis_label
            + f"（{calibration.total_observations} 次观测）。"
            "optimistic 为均分假设上界，pessimistic 为三次幂衰减下界。"
        ),
    )


def decide(lottery: Optional[LotteryReport], best_ppv: Optional[float], risk: str) -> Tuple[str, str]:
    """Draw vs redeem recommendation."""
    if lottery is None:
        return ("unknown", "未读取到抽奖活动，本次只输出兑换侧结论。")
    if not lottery.headline_ev or not lottery.cost_points:
        return ("unknown", "抽奖奖池缺少可估算收益，无法给出对比结论。")

    draw_ppv = lottery.ppv("realistic")
    if draw_ppv is None or not best_ppv:
        return ("unknown", "缺少可比的兑换效率基准，无法判定抽奖是否划算。")

    low_ppv = lottery.ppv("pessimistic") or 0.0
    high_ppv = lottery.ppv("optimistic") or 0.0

    bands = {"conservative": (1.30, 1.30), "balanced": (1.15, 0.85), "aggressive": (1.00, 0.70)}
    need, floor_ = bands.get(risk, (1.15, 0.85))

    base = (
        f"抽奖单次消耗 {lottery.cost_points:g} 积分，中性口径收益期望 ¥{lottery.headline_ev:.2f}"
        f"（{draw_ppv:.2f} 元/百分）；商城最优档 {best_ppv:.2f} 元/百分。"
    )
    spread = f"EV 区间 {low_ppv:.2f} ~ {high_ppv:.2f} 元/百分（悲观~乐观）。"

    # High-variance guard: when the neutral case wins but the pessimistic case
    # collapses below half the safe option, the "edge" is variance, not value.
    # Reporting that as "go draw" would be irresponsible.
    if draw_ppv > best_ppv and low_ppv < 0.5 * best_ppv:
        return (
            "coin_flip",
            base + spread
            + "中性口径占优，但悲观口径下只有 "
            f"{low_ppv:.2f} 元/百分（不足直接兑换的一半）—— 优势来自波动而非价值，"
            "不适合当作「更划算」来推荐。求稳请直接兑换，愿意承担方差再抽。",
        )

    if draw_ppv >= need * best_ppv:
        extra = "即使按中性口径，抽奖仍明显占优，推荐抽奖。"
        return ("draw", base + spread + extra) if low_ppv >= best_ppv * 0.5 else (
            "draw",
            base + spread + "中性口径下抽奖占优，且悲观口径未跌破兑换的一半，可以抽奖。",
        )

    if draw_ppv > best_ppv:
        return (
            "coin_flip",
            base + spread + "中性口径略占优但不稳健；能接受波动就试抽，求稳则直接兑换。",
        )
    return ("redeem", base + spread + "中性口径下抽奖不如直接兑换。")


# ----------------------------------------------------------------------
# knapsack
# ----------------------------------------------------------------------


def solve_clearance(
    redemptions: Sequence[Redemption], budget: float
) -> Tuple[List[Tuple[Redemption, int]], float, float]:
    """Unbounded knapsack over redemptions maximising RMB saved."""
    usable = [r for r in redemptions if r.ppv is not None and r.ppv > 0 and r.points and r.benefit]
    if not usable or budget <= 0:
        return [], 0.0, 0.0

    # Coarsen the DP table until it fits. `--budget` is user input, so a huge
    # value (or a corrupt upstream figure) would otherwise allocate a
    # multi-gigabyte list and hang. Scaling the weights keeps the solve exact
    # to within `scale` points, which is irrelevant at those magnitudes.
    scale = 100 if budget > 60_000 else (10 if budget > 20_000 else 1)
    capacity = int(budget // scale)
    while capacity > MAX_DP_CAPACITY:
        scale *= 10
        capacity = int(budget // scale)

    items = [(max(1, int(r.points // scale)), float(r.benefit)) for r in usable]
    if capacity <= 0 or any(w <= 0 for w, _ in items):
        return [], 0.0, 0.0

    dp = [0.0] * (capacity + 1)
    choice: List[Optional[int]] = [None] * (capacity + 1)
    for cap in range(1, capacity + 1):
        for idx, (weight, value) in enumerate(items):
            if weight <= cap:
                candidate = dp[cap - weight] + value
                if candidate > dp[cap]:
                    dp[cap], choice[cap] = candidate, idx

    counts: Dict[int, int] = {}
    remaining, spent_scaled = capacity, 0
    while remaining > 0 and choice[remaining] is not None:
        idx = choice[remaining]
        counts[idx] = counts.get(idx, 0) + 1
        remaining -= items[idx][0]
        spent_scaled += items[idx][0]

    picked = [(usable[i], c) for i, c in counts.items() if c > 0]
    picked.sort(key=lambda pair: pair[0].ppv or 0, reverse=True)
    return picked, spent_scaled * scale, dp[capacity]


# ----------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------


def analyse(
    client: Any = None,
    mode: str = "demo",
    city: str = DEFAULT_CITY,
    keyword: str = DEFAULT_KEYWORD,
    store_override: Optional[str] = None,
    risk_profile: str = "balanced",
    budget_override: Optional[float] = None,
    raw_dump: Optional[str] = None,
) -> ReportData:
    """Run the full analysis. `client=None` uses offline fixtures."""
    warnings: List[str] = []

    if client is not None:
        bundle, upstream = load_live(client, city, keyword, store_override)
        warnings.extend(upstream)
        try:
            tools = {t.name for t in client.list_tools()}
            missing = sorted({"query-my-account", "mall-points-products", "query-meals"} - tools)
            warnings.extend(f"MCP Server 未提供工具：{name}" for name in missing)
        except Exception:  # noqa: BLE001
            pass
    else:
        warnings.append("演示模式：使用脱敏合成数据，不代表任何真实账户。")
        # Wrap fixtures the same way the live server wraps its payloads, so the
        # demo exercises the identical unwrap path rather than a shortcut.

        def _env(data: Any) -> Dict[str, Any]:
            return {"success": True, "code": 200, "message": "请求成功", "data": data}

        bundle = {
            "account": _env(fake_account()),
            "menu": _env(fake_menu()),
            "mall": _env(fake_mall_products()),
            "lottery": _env(fake_lottery()),
            "prizes": _env(fake_my_prizes()),
            "store_label": "演示门店",
        }

    if raw_dump:
        with open(raw_dump, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, ensure_ascii=False, indent=2, default=str)

    index = build_menu_index(bundle.get("menu"))
    if len(index) == 0:
        warnings.append("菜单价格索引为空，所有券都无法估值 —— 请检查门店与菜单加载情况。")
    # Live menu prices double as the anchor for money analogies ("≈2 甜筒").
    menu_price_items = [(i.name, i.list_price) for i in index.items]

    raw_payload = unwrap_data(bundle.get("account"))
    account = PointAccount.from_payload(raw_payload if isinstance(raw_payload, dict) else {})

    # Prize history feeds two separate models: the second-loss profile (how
    # often a won coupon gets used) and the odds calibration (which prizes the
    # pool actually pays out). Same source, different questions.
    prizes_data = unwrap_data(bundle.get("prizes"))
    profile = build_profile(prizes_data)
    history_records: List[Dict[str, Any]] = []
    if isinstance(prizes_data, dict):
        history_records = [r for r in (prizes_data.get("prizes") or []) if isinstance(r, dict)]

    redemptions = value_redemptions(bundle.get("mall"), index)
    rate = provisional_rate(redemptions)
    lottery = build_lottery(bundle.get("lottery"), index, rate, account.available, profile, history_records)

    # second pass now that a provisional exchange rate exists
    for item in redemptions:
        if item.benefit is None and item.spec is not None:
            item.value = value_coupon(item.spec, index, points_ppv=rate)

    # Preference overlay: objective PPV stays untouched, affinity rides alongside.
    preference = build_preference(unwrap_data(bundle.get("orders")))
    if preference.usable:
        for item in redemptions:
            matched = item.value.matched_name if item.value else None
            item.affinity, item.affinity_hit = preference.affinity(item.name, matched)
    elif preference.order_count:
        warnings.append(preference.note)

    # Items whose "discount" turned out to be zero or negative carry no value
    # and must not crowd the leaderboard, even though they technically have PPV.
    redemptions.sort(
        key=lambda r: (r.ppv is not None and (r.benefit or 0) > 0, r.ppv or 0), reverse=True
    )
    priced = [r for r in redemptions if r.ppv is not None]
    best_ppv = max((r.ppv for r in priced), default=None)

    if lottery and lottery.unpriced:
        warnings.append(f"奖池有 {len(lottery.unpriced)} 项无法估值，EV 为保守下界。")
    unpriced = [r for r in redemptions if r.ppv is None]
    if unpriced:
        warnings.append(
            f"{len(unpriced)} 件商城商品仍未估值（名称无法解析到任何餐品或类目）"
        )
    if profile.usable and profile.rate is not None and profile.rate < 0.999:
        warnings.append(
            f"二次损耗：历史 {profile.total_coupons} 张券中 {profile.lapsed} 张失效，"
            f"兑现率 {profile.rate * 100:.0f}% —— 抽奖奖品的期望价值已按此折算。"
        )
    if profile.confidence == "low" and profile.usable:
        warnings.append(
            f"兑现率样本仅 {profile.total_coupons} 张，置信度低，仅供参考。"
        )

    budget = float(budget_override) if budget_override is not None else 0.0
    if budget <= 0:
        budget = float(_expiring_bucket(account) or 0.0)
        if budget <= 0 and account.available:
            budget = float(account.available)
            warnings.append("未读到「本月将过期积分」，已按全部可用积分做清仓测算。")

    picked, spent, total_value = solve_clearance(redemptions, budget)
    plan = [
        ClearanceItem(
            name=r.name,
            count=count,
            points_each=float(r.points or 0),
            value_each=float(r.benefit or 0),
        )
        for r, count in picked
    ]

    # Multi-period view: split the balance, then see what waiting would unlock.
    bucket = split_points(account.available, _expiring_bucket(account))
    save_up = save_up_targets(redemptions, account.available)
    _ = bucket, save_up  # consumed in the ReportData below
    # Deliberately NOT haircut by the redemption profile. That rate is measured
    # from *won* prizes — coupons the user never chose. A mall coupon is
    # redeemed on purpose, so its holder is far more likely to use it; applying
    # the lottery lapse rate here would punish deliberate choices for the sins
    # of random ones. Mall coupons get a validity reminder instead.
    plan_net = round(sum(i.total_value for i in plan), 2)

    return ReportData(
        mode=mode,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        account=account,
        store_label=bundle.get("store_label"),
        menu_items=len(index),
        redemptions=redemptions,
        best_ppv=best_ppv,
        plan=plan,
        plan_points=spent,
        plan_value=round(total_value, 2),
        plan_leftover=max(0.0, budget - spent),
        budget=budget,
        lottery=lottery,
        history=_build_history(bundle.get("prizes")),
        verdict=decide(lottery, best_ppv, risk_profile),
        profile=profile,
        plan_net_value=plan_net,
        preference=preference,
        bucket=bucket,
        save_up=save_up,
        menu_price_items=menu_price_items,
        menu_period=str((bundle.get("_meta") or {}).get("menu_period", "unknown")),
        warnings=warnings,
        raw=bundle,
    )


def _expiring_bucket(account: PointAccount) -> Optional[float]:
    """Current-month expiry is the actionable bucket; fall back to next month."""
    payload = account.raw_payload or {}
    for key in ("currentMouthExpirePoint", "nextMouthExpirePoint", "currentMonthExpirePoint"):
        value = to_float(payload.get(key))
        if value:
            return value
    return None


def _build_history(prizes_envelope: Any) -> List[Dict[str, Any]]:
    data = unwrap_data(prizes_envelope)
    if isinstance(data, dict):
        records = data.get("prizes") or []
    elif isinstance(data, list):
        records = data
    else:
        records = []
    out: List[Dict[str, Any]] = []
    for row in records[:12]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "name": row.get("name"),
                "type": row.get("prizeTypeText"),
                "record_time": row.get("recordTime"),
                "status": row.get("statusText"),
            }
        )
    return out
