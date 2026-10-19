#!/usr/bin/env python3
"""麦麦积分清算局 — CLI entry point.

    # offline demo, no token needed
    python points_rescue.py --demo

    # live data from McDonald's MCP
    export MCD_MCP_TOKEN=xxxxx
    python points_rescue.py --live --city 上海市 --out my-report.html

    # capture the raw envelopes for debugging / calibration
    python points_rescue.py --live --dump-raw raw.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.action_plan import render_markdown, render_text  # noqa: E402
from src.analyze import DEFAULT_CITY, DEFAULT_KEYWORD, ReportData, analyse  # noqa: E402
from src.mcp_client import McpClient, McpError  # noqa: E402
from src.report import render  # noqa: E402

DEFAULT_WEB_PORT = 8723

BANNER = """
  __  __      ___  ___      ___      _          _          ___ ___  ___ _   _ ___
 |  \\/  |__ _|   \\/ __|    / _ \\ _ _(_)__ ___  | |__ _____| _ \\ _ \\/ __| | | | __|
 | |\\/| / _` | |) \\__ \\   | (_) | '_| / _/ -_) | '_ \\_____|  _/   /\\__ \\ |_| | _|
 |_|  |_\\__,_|___/|___/    \\___/|_| |_\\__\\___| |_.__/     |_| |_|_\\|___/\\___/|___|
        积分清算局 · points rescue     v1.0.0
"""


def _fmt(value: Any, spec: str = ".2f", dash: str = "—") -> str:
    """Format a possibly-missing number. `spec` uses str.format syntax.

    Note: this deliberately uses format()-style specs (",.1f") rather than
    printf-style ("%,.1f"). Python's %-operator has no thousands separator,
    so every comma-bearing format silently degrades to "—" if you mix them up.
    """
    if value is None:
        return dash
    try:
        return format(float(value), spec)
    except (TypeError, ValueError):
        return dash


def build_report(data: ReportData) -> Dict[str, Any]:
    """Machine-readable projection of the analysis."""
    acc = data.account
    lot = data.lottery
    return {
        "generated_at": data.generated_at,
        "mode": data.mode,
        "store": data.store_label,
        "menu_items": data.menu_items,
        "account": {
            "available": acc.available,
            "accumulated": acc.accumulated,
            "used": acc.used,
            "frozen": acc.frozen,
            "expired_total": acc.expired,
            "expiring_this_month": acc.expiring_soon,
            "expiring_next_month": acc.expiring_next_month,
            "currency": acc.currency,
            "lost_ratio": round(acc.lost_ratio, 4) if acc.lost_ratio is not None else None,
        },
        "best_ppv": round(data.best_ppv, 4) if data.best_ppv else None,
        "redemptions": [
            {
                "name": r.name,
                "points": r.points,
                "benefit_cny": r.benefit,
                "ppv": round(r.ppv, 4) if r.ppv is not None else None,
                "coupon_kind": r.spec.kind if r.spec else None,
                "basis": r.value.basis if r.value else None,
                "matched": r.value.matched_name if r.value else None,
                "list_price": r.value.list_price if r.value else None,
            }
            for r in data.redemptions
        ],
        "clearance_plan": {
            "budget_points": data.budget,
            "spent_points": data.plan_points,
            "total_saving_cny": data.plan_value,
            "leftover_points": data.plan_leftover,
            "items": [
                {
                    "name": i.name,
                    "count": i.count,
                    "points_each": i.points_each,
                    "benefit_each": i.value_each,
                }
                for i in data.plan
            ],
        },
        "lottery": None
        if not lot
        else {
            "activity": lot.activity_name,
            "cost_points": lot.cost_points,
            "draws_affordable": lot.affordable_draws,
            "scenarios_cny": lot.scenarios,
            "ppv": {k: lot.ppv(k) for k in ("optimistic", "realistic", "pessimistic")},
            "priced_count": lot.priced_count,
            "unpriced": lot.unpriced,
            "prizes": [
                {
                    "name": r.name,
                    "probability": round(r.probability, 6) if r.probability else None,
                    "benefit_cny": r.benefit,
                    "basis": r.value.basis if r.value else None,
                    "matched": r.value.matched_name if r.value else None,
                }
                for r in lot.rows
            ],
        },
        "verdict": {"decision": data.verdict[0], "reason": data.verdict[1]},
        "warnings": data.warnings,
    }


def print_console_summary(data: ReportData) -> None:
    acc = data.account
    print(BANNER)
    print(f"  模式：{'实时 MCP 数据' if data.mode == 'live' else '演示数据（合成）'}   {data.generated_at}")
    print(f"  锚点门店：{data.store_label or '—'}    菜单锚点：{data.menu_items} 项")
    print("─" * 70)

    if acc.accumulated:
        print(f"  累计获得      {_fmt(acc.accumulated, ',.1f'):>12} 分")
    if acc.expired:
        tail = f"（占累计 {acc.lost_ratio * 100:.0f}%）" if acc.lost_ratio else ""
        print(f"  已过期清零    {_fmt(acc.expired, ',.1f'):>12} 分   {tail}")
    if acc.used:
        print(f"  已使用        {_fmt(acc.used, ',.1f'):>12} 分")
    print(f"  可用余额      {_fmt(acc.available, ',.1f'):>12} 分   [{acc.currency or '积分'}]")
    if acc.expiring_soon:
        cash = acc.expiring_soon * (data.best_ppv or 0) / 100
        print(f"  本月到期      {_fmt(acc.expiring_soon, ',.0f'):>12} 分   折约 ¥{cash:.1f}")
    print("─" * 70)

    rows = [r for r in data.redemptions if r.ppv is not None and (r.benefit or 0) > 0]
    if rows:
        priced, total = data.coverage
        print(
            f"  兑换性价比 TOP 6（最优 {_fmt(data.best_ppv)} 元/百分，"
            f"覆盖 {priced}/{total}"
            f"{'·估算 ' + str(data.estimate_count) + ' 件' if data.estimate_count else ''}）："
        )
        for idx, r in enumerate(rows[:6], 1):
            mark = "*" if r.is_estimate else " "
            print(
                f"    {idx}.{mark} {r.name[:26]:<28}{_fmt(r.points, ',.0f'):>7} 分"
                f"   省 ¥{_fmt(r.benefit):<6}  {_fmt(r.ppv):>6} 元/百分"
            )
        unresolved = len(data.redemptions) - len(rows)
        if unresolved:
            print(f"    （另有 {unresolved} 件未能估值；* 标记为估算值）")
        print("─" * 70)

    profile = data.profile
    if profile and profile.usable:
        print(
            f"  二次损耗      历史 {profile.total_coupons} 张券，"
            f"用掉 {profile.honoured} 张，失效 {profile.lapsed} 张"
            f"  →  兑现率 {_fmt((profile.rate or 0) * 100, '.0f')}%"
        )
        if profile.adjusted and profile.rate_raw is not None:
            print(
                f"                （原始 {profile.rate_raw * 100:.0f}%，"
                f"已按 20% 下限调整；置信度 {profile.confidence}）"
            )
        print("─" * 70)

    if data.plan:
        print(f"  清仓方案（预算 {_fmt(data.budget, ',.0f')} 分）：")
        for item in data.plan:
            print(
                f"    × {item.count:<2} {item.name[:26]:<28}"
                f"{_fmt(item.total_points, ',.0f'):>7} 分   ¥{_fmt(item.total_value)}"
            )
        print(f"    合计节省 ¥{_fmt(data.plan_value)}，剩余 {_fmt(data.plan_leftover, ',.0f')} 分")
        print("─" * 70)

    lot = data.lottery
    if lot:
        kind, reason = data.verdict
        lead = {
            "draw": "建议抽奖",
            "redeem": "建议直接兑换",
            "coin_flip": "两者接近，看风险偏好",
            "unknown": "数据不足，无法判定",
        }.get(kind, "无法判定")
        print(
            f"  抽奖活动      {lot.activity_name} ｜ 单次 {_fmt(lot.cost_points, 'g')} 分"
            f" ｜ 可抽 {lot.affordable_draws} 次"
        )
        print(
            f"  EV 情景       乐观 ¥{_fmt(lot.scenarios.get('optimistic'))}"
            f" ｜ 中性 ¥{_fmt(lot.scenarios.get('realistic'))}"
            f" ｜ 悲观 ¥{_fmt(lot.scenarios.get('pessimistic'))}"
        )
        print(
            f"  抽奖效率      中性 {_fmt(lot.ppv('realistic'))} 元/百分"
            f"   vs   兑换 {_fmt(data.best_ppv)} 元/百分"
        )
        print(f"  决策          → {lead}")
        print(f"                {reason}")
        print("─" * 70)

    for warning in data.warnings:
        print(f"  · {warning}")

    print("─" * 70)
    print("  行动清单：")
    print(render_text(data))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="points_rescue",
        description="麦麦积分清算局：把积分换算成人民币，再决定怎么花",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="调用真实麦当劳 MCP（需要 Token）")
    mode.add_argument("--demo", action="store_true", help="使用合成演示数据（无需 Token）")
    parser.add_argument("--token", help="麦当劳 MCP Token，默认读环境变量 MCD_MCP_TOKEN")
    parser.add_argument("--endpoint", default="https://mcp.mcd.cn", help="MCP 接入地址")
    parser.add_argument("--city", default=DEFAULT_CITY, help="门店搜索城市，用于加载菜单价格")
    parser.add_argument("--keyword", default=DEFAULT_KEYWORD, help="门店搜索关键词")
    parser.add_argument("--store", dest="store_code",
                        help="手动指定门店编码，跳过自动选店（不同门店菜单差异很大）")
    parser.add_argument(
        "--risk",
        choices=["conservative", "balanced", "aggressive"],
        default="balanced",
        help="风险偏好，影响抽奖建议的判定阈值",
    )
    parser.add_argument("--budget", type=float, help="清仓预算（分），默认取本月将过期积分")
    parser.add_argument("--out", default="report.html", help="HTML 报告输出路径")
    parser.add_argument("--json", dest="json_out", help="同时输出结构化 JSON")
    parser.add_argument("--plan", dest="plan_out", help="输出可照做的 Markdown 兑换清单")
    parser.add_argument("--dump-raw", dest="dump_raw", help="把 MCP 原始报文落盘，便于排查")
    parser.add_argument(
        "--setup", action="store_true", help="引导申请并本地保存 MCP Token（只需一次）"
    )
    parser.add_argument("--doctor", action="store_true", help="自检上游接口与门店是否可用")
    parser.add_argument("--forget", action="store_true", help="删除本地保存的 Token")
    parser.add_argument(
        "--web", nargs="?", const=str(DEFAULT_WEB_PORT), metavar="PORT",
        help="启动本机配置面板（浏览器内完成配置与分析）",
    )
    args = parser.parse_args(argv)

    if args.web is not None:
        from src.webapp import serve

        try:
            port = int(args.web)
        except ValueError:
            print(f"[error] 端口号无效：{args.web}", file=sys.stderr)
            return 2
        return serve(port=port)

    if args.setup:
        from src.credentials import interactive_setup

        return interactive_setup()
    if args.forget:
        from src.credentials import clear_token

        print("  已删除本地 Token。" if clear_token() else "  本地没有保存过 Token。")
        return 0
    if args.doctor:
        from src.credentials import run_doctor

        return run_doctor(args.endpoint)

    use_live = args.live or (not args.demo and os.environ.get("MCD_MCP_TOKEN"))

    if use_live:
        try:
            client = McpClient(token=args.token, endpoint=args.endpoint)
            client.initialize()
        except McpError as exc:
            print(f"[error] MCP 连接失败：{exc}", file=sys.stderr)
            print("        请到 https://open.mcd.cn/mcp 申请 Token 并设置 MCD_MCP_TOKEN", file=sys.stderr)
            return 2
        data = analyse(
            client=client,
            mode="live",
            city=args.city,
            keyword=args.keyword,
            store_override=args.store_code,
            risk_profile=args.risk,
            budget_override=args.budget,
            raw_dump=args.dump_raw,
        )
    else:
        if not args.demo:
            print("[hint] 未检测到 Token，已自动使用演示数据。加 --live 并配置 MCD_MCP_TOKEN 可跑真实数据。\n")
        data = analyse(
            mode="demo",
            risk_profile=args.risk,
            budget_override=args.budget,
            raw_dump=args.dump_raw,
        )

    print_console_summary(data)

    out = Path(args.out)
    out.write_text(render(data), encoding="utf-8")
    print(f"\n  HTML 报告已生成：{out.resolve()}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(build_report(data), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  JSON 结果已生成：{Path(args.json_out).resolve()}")

    if args.plan_out:
        Path(args.plan_out).write_text(render_markdown(data), encoding="utf-8")
        print(f"  行动清单已生成：{Path(args.plan_out).resolve()}")

    if data.mode != "live":
        print("\n  注：以上数据为脱敏合成样例，不代表任何真实账户。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
