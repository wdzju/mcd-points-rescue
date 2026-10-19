"""Action plan — turning the analysis into something you can actually follow.

The gap this closes
-------------------
A ranking answers "which coupon is best". It does not answer "what do I do
now". Users still have to open the app, remember the order, and find each
item — and by the time they do, the expiring points have often expired.

This module emits a checklist: ordered, copy-pasteable, with the points cost
and the saving per line, so the whole plan can be executed in one sitting.
It also states what NOT to do, because "don't draw" is actionable too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .analyze import ReportData


@dataclass
class ActionLine:
    kind: str  # redeem | note | avoid | header
    text: str
    points: Optional[float] = None
    saving: Optional[float] = None
    deadline: str = ""


def build_action_lines(data: ReportData) -> List[ActionLine]:
    """Compose the checklist from a finished analysis."""
    lines: List[ActionLine] = []
    acc = data.account

    headline = (
        f"可用 {_fmt(acc.available, '.1f')} 分"
        + (f"，本月到期 {_fmt(acc.expiring_soon, '.0f')} 分" if acc.expiring_soon else "")
    )
    lines.append(ActionLine("header", headline))

    if data.plan:
        for idx, item in enumerate(data.plan, 1):
            deadline = ""
            match = next((r for r in data.redemptions if r.name == item.name), None)
            if match and match.window_label:
                deadline = match.window_label
            lines.append(
                ActionLine(
                    kind="redeem",
                    text=f"{item.name} × {item.count}",
                    points=item.total_points,
                    saving=item.total_value,
                    deadline=deadline,
                )
            )
        lines.append(
            ActionLine(
                "note",
                f"共消耗 {_fmt(data.plan_points, '.0f')} 分，预计节省 ¥{_fmt(data.plan_value)}"
                + (
                    f"；剩余 {_fmt(data.plan_leftover, '.0f')} 分凑不成整券，可留到下月"
                    if data.plan_leftover > 0
                    else ""
                ),
            )
        )
    else:
        lines.append(ActionLine("note", "当前预算内没有可组合的可估值券。"))

    # Second-loss reminder: redeeming is not the finish line.
    profile = data.profile
    if profile and profile.usable:
        lines.append(
            ActionLine(
                "note",
                f"换到的券记得用掉 —— 你历史 {profile.total_coupons} 张券里 "
                f"{profile.lapsed} 张最后失效了。",
            )
        )
    elif data.plan:
        lines.append(ActionLine("note", "换到的券有有效期，别让它成为第二次损耗。"))

    verdict_kind = data.verdict[0] if data.verdict else ""
    lot = data.lottery
    if verdict_kind == "redeem" and lot:
        lines.append(
            ActionLine(
                "avoid",
                f"别抽奖：折算兑现率后效率约 {_fmt(lot.ppv('realistic'))} 元/百分，"
                f"低于直接兑换的 {_fmt(data.best_ppv)} 元/百分。",
            )
        )
    elif verdict_kind == "coin_flip" and lot:
        lines.append(
            ActionLine(
                "avoid",
                f"抽奖可试但别指望：中性 {_fmt(lot.ppv('realistic'))} 元/百分，"
                f"悲观只有 {_fmt(lot.ppv('pessimistic'))} 元/百分。",
            )
        )

    return lines


def render_markdown(data: ReportData) -> str:
    """Checklist as Markdown, ready to paste into a note or reminder."""
    out: List[str] = ["# 麦麦积分行动清单", ""]
    out.append(f"> 生成于 {data.generated_at} ｜ 锚点门店 {data.store_label or '—'}")
    out.append("")

    for line in build_action_lines(data):
        if line.kind == "header":
            out.append(f"**{line.text}**")
            out.append("")
            out.append("### 兑换")
        elif line.kind == "redeem":
            cost = _fmt(line.points, ".0f")
            save = _fmt(line.saving)
            tail = f"（{line.deadline}）" if line.deadline else ""
            out.append(f"- [ ] {line.text}　`{cost} 分`　省 ¥{save} {tail}")
        elif line.kind == "note":
            out.append(f"- {line.text}")
        elif line.kind == "avoid":
            out.append("")
            out.append("### 不要做")
            out.append(f"- {line.text}")

    out.append("")
    out.append("---")
    out.append("")
    out.append(
        "_本清单由 mcd-points-rescue 生成，估值基于麦当劳 MCP 实时菜单价格推导，仅供参考。_"
    )
    return "\n".join(out)


def _fmt(value: Optional[float], spec: str = ".2f", dash: str = "—") -> str:
    if value is None:
        return dash
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return dash


def render_text(data: ReportData) -> str:
    """Compact plain-text version for terminal output."""
    out: List[str] = []
    for line in build_action_lines(data):
        if line.kind == "header":
            out.append(f"  {line.text}")
            out.append("  " + "─" * 60)
        elif line.kind == "redeem":
            tail = f"  ⚠ {line.deadline}" if line.deadline else ""
            out.append(
                f"    [ ] {line.text[:30]:<32}"
                f"{_fmt(line.points, '.0f'):>6} 分   省 ¥{_fmt(line.saving)}{tail}"
            )
        elif line.kind == "note":
            out.append(f"    · {line.text}")
        elif line.kind == "avoid":
            out.append(f"    ✗ {line.text}")
    return "\n".join(out)
