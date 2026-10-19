"""Second-loss modelling: a coupon you never use is worth nothing.

Why this exists
---------------
Expiry happens twice, and the standard analysis only counts the first one:

    1st loss — points expire before you redeem them      (what everyone measures)
    2nd loss — the coupon expires before you ever use it (what nobody measures)

The second one is invisible in the balance and brutal in practice. Real
accounts show prize histories full of 「已失效」: the points were spent, the
coupon was issued, and then it quietly lapsed. Net result identical to letting
the points expire — except you also did the work of redeeming.

So a coupon's worth is not its discount. It is:

    expected_value = discount × P(you actually use it)

And P(use it) is observable — `query-my-prizes` returns the status of every
prize the account has ever won. Counting honoured vs lapsed gives a personal
redemption rate grounded in the user's own behaviour, not a guess.

Design rules:
- Only coupon-type prizes are counted (a 节气 门票 is not a discount coupon).
- Small samples are reported, never hidden: sample size ships with the rate.
- Below MIN_SAMPLE the rate is still shown but flagged, and never applied
  silently — the report says which number came from how much evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, List, Optional

MIN_SAMPLE = 3

# Never treat an account as having literally zero chance of using a coupon.
RATE_FLOOR = 0.2

# Statuses that mean the coupon delivered value.
_HONOURED = ("可用", "已使用", "已核销", "已兑换", "生效中", "使用中")
# Statuses that mean it lapsed.
_LAPSED = ("已失效", "已过期", "作废", "失效", "已退")
# Prize types that behave like discount coupons.
_COUPON_TYPES = ("优惠券", "折扣券", "代金券", "兑换券")


@dataclass
class PrizeOutcome:
    name: str
    prize_type: Optional[str]
    status: Optional[str]
    won_at: Optional[date]

    @property
    def is_coupon(self) -> bool:
        if not self.prize_type:
            return False
        return any(t in str(self.prize_type) for t in _COUPON_TYPES)

    @property
    def honoured(self) -> Optional[bool]:
        """True = used, False = lapsed, None = unknown status."""
        if not self.status:
            return None
        text = str(self.status)
        if any(t in text for t in _HONOURED):
            return True
        if any(t in text for t in _LAPSED):
            return False
        return None


@dataclass
class RedemptionProfile:
    """How reliably this account converts a coupon into actual value."""

    total_coupons: int = 0
    honoured: int = 0
    lapsed: int = 0
    unknown: int = 0
    rate: Optional[float] = None
    rate_raw: Optional[float] = None
    confidence: str = "none"
    note: str = ""
    adjusted: bool = False
    examples_lapsed: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Only apply a haircut when there is real evidence behind it."""
        return self.rate is not None and self.total_coupons > 0

    @property
    def haircut_pct(self) -> Optional[float]:
        """Percentage of coupon value historically lost."""
        return None if self.rate is None else (1.0 - self.rate) * 100.0

    @property
    def verdict(self) -> str:
        if not self.usable:
            return "历史中奖记录不足，暂不估算兑现率"
        if self.total_coupons < MIN_SAMPLE:
            return (
                f"样本仅 {self.total_coupons} 张，兑现率 {self.rate * 100:.0f}% "
                f"（参考值，证据不足）"
            )
        return f"历史 {self.total_coupons} 张券，用掉 {self.honoured} 张，兑现率 {self.rate * 100:.0f}%"


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    candidates = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
    for pattern in candidates:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    head = text.split(" ")[0]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def build_profile(prizes_data: Any) -> RedemptionProfile:
    """Derive the redemption rate from `query-my-prizes` → data.prizes."""
    if isinstance(prizes_data, dict):
        records = prizes_data.get("prizes") or []
    elif isinstance(prizes_data, list):
        records = prizes_data
    else:
        records = []

    outcomes: List[PrizeOutcome] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        outcomes.append(
            PrizeOutcome(
                name=str(row.get("name") or ""),
                prize_type=row.get("prizeTypeText"),
                status=row.get("statusText"),
                won_at=_parse_date(row.get("recordTime")),
            )
        )

    coupons = [o for o in outcomes if o.is_coupon]
    if not coupons:
        # Fall back to every prize with a resolvable status, otherwise the
        # haircut would be silently skipped for most accounts.
        coupons = [o for o in outcomes if o.honoured is not None]

    profile = RedemptionProfile(total_coupons=len(coupons))
    if not coupons:
        profile.note = "未找到可判定状态的历史奖品"
        return profile

    for o in coupons:
        flag = o.honoured
        if flag is True:
            profile.honoured += 1
        elif flag is False:
            profile.lapsed += 1
            if len(profile.examples_lapsed) < 4:
                profile.examples_lapsed.append(o.name)
        else:
            profile.unknown += 1

    decided = profile.honoured + profile.lapsed
    if decided == 0:
        profile.note = "历史奖品状态无法判定"
        return profile

    if decided >= MIN_SAMPLE:
        raw = profile.honoured / decided
    else:
        # Laplace smoothing: two coupons that both lapsed give a raw rate of 0,
        # which would zero out the whole lottery EV on two observations.
        raw = (profile.honoured + 1.0) / (decided + 2.0)

    profile.rate_raw = raw
    # Floor the rate. An observed 0% means "in the past you never used them",
    # not "you never will" — and the whole point of this report is to change
    # that behaviour. Zeroing every EV would make the tool useless precisely
    # when it matters most, so we floor and say so.
    if raw < RATE_FLOOR:
        profile.rate = RATE_FLOOR
        profile.adjusted = True
        profile.note = (
            f"历史兑现率 {raw * 100:.0f}%（{decided} 张观测），已按 {RATE_FLOOR * 100:.0f}% 下限调整"
            f"—— 本工具的目的就是提醒你把券用掉"
        )
    else:
        profile.rate = raw

    if decided >= MIN_SAMPLE * 2:
        profile.confidence = "high"
    elif decided >= MIN_SAMPLE:
        profile.confidence = "medium"
    else:
        profile.confidence = "low"
    profile.note = (
        f"统计口径：{decided} 张状态明确的券"
        f"（另有 {profile.unknown} 张状态未知，已排除）"
    )
    return profile


# ----------------------------------------------------------------------
# redemption window
# ----------------------------------------------------------------------


@dataclass
class Window:
    """How long a mall item is still available to redeem."""

    days_left: Optional[int] = None
    closes_at: Optional[date] = None

    @property
    def urgency(self) -> str:
        """Only a FUTURE deadline can be urgent.

        Many live rows carry a `downTime` already in the past while `status`
        still says 上架 (2). That field is evidently not a hard availability
        cutoff, so a past date means "no usable deadline", not "closed" —
        treating it as closed would flag the entire catalogue as expiring.
        """
        if self.days_left is None:
            return "unknown"
        if self.days_left <= 0:
            return "none"
        if self.days_left <= 7:
            return "urgent"
        if self.days_left <= 30:
            return "soon"
        return "normal"


def redemption_window(down_time: Any, today: Optional[date] = None) -> Window:
    """Parse `mall-points-products` → downTime into a countdown."""
    closes = _parse_date(down_time)
    if closes is None:
        return Window()
    today = today or date.today()
    return Window(days_left=(closes - today).days, closes_at=closes)


def apply_haircut(benefit: Optional[float], profile: RedemptionProfile) -> Optional[float]:
    """Discount a coupon's benefit by the account's historical lapse rate.

    Note `profile.rate or 1.0` would be a bug here: a rate of exactly 0.0 is
    falsy, so "every coupon I ever won lapsed" would silently become "every
    coupon gets honoured". Check for None explicitly.
    """
    if benefit is None or not profile.usable or profile.rate is None:
        return benefit
    return round(benefit * profile.rate, 2)
