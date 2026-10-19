"""Single-file HTML report renderer.

Deliberately dependency-free: no CDN, no build step, no web fonts. Open it in
a browser, screenshot it, or share the file. Everything is inlined.

Any value that could be None goes through `n()` first — live upstream data has
plenty of holes, and a template crash would be the worst possible failure mode
for a tool whose entire job is producing this report.
"""

from __future__ import annotations

import html
from typing import Any, List, Optional

from .analyze import ReportData

CSS = """
:root{
  --mcd-red:#DA291C; --mcd-red-dk:#A81E14; --mcd-yellow:#FFC72C; --mcd-cream:#FFF4DC;
  --good:#0B7A4B; --warn:#B25A00; --bad:#C0392B; --info:#1D6FA5;
  --bg:#FFFBF5; --card:#FFFFFF; --ink:#1F1B16; --muted:#7A6F62;
  --line:#EDE3D6; --soft:#FDF7EF;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.6;padding:0 16px 32px;-webkit-font-smoothing:antialiased}
.wrap{max-width:940px;margin:0 auto}

.hero{background:var(--mcd-red);border-radius:0 0 28px 28px;padding:26px 30px 30px;margin:0 -16px 22px;
  color:#fff;position:relative;overflow:hidden}
.hero:after{content:"";position:absolute;right:-70px;top:-46px;width:210px;height:210px;
  border-radius:50%;background:var(--mcd-yellow);opacity:.16}
.hero-top{display:flex;align-items:center;gap:12px;margin-bottom:16px;position:relative}
.arch{width:34px;height:34px;flex:none}
.hero-top .brand{font-size:15px;font-weight:500;letter-spacing:.3px;opacity:.95}
.hero-top .who{margin-left:auto;font-size:11.5px;opacity:.8;text-align:right;line-height:1.5}
.hero-lead{font-size:25px;font-weight:500;line-height:1.45;letter-spacing:-.4px;position:relative;
  max-width:660px}
.hero-lead b{color:var(--mcd-yellow)}
.hero-sub{margin-top:10px;font-size:13px;opacity:.9;position:relative}

.scorewrap{display:flex;gap:18px;align-items:center;background:var(--card);
  border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin-bottom:18px}
.ring{width:96px;height:96px;flex:none;position:relative}
.ring svg{transform:rotate(-90deg)}
.ring .txt{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center}
.ring .num{font-size:27px;font-weight:500;line-height:1;letter-spacing:-1px}
.ring .cap{font-size:10px;color:var(--muted);margin-top:2px}
.scoreinfo{flex:1;min-width:0}
.scoreinfo .grade{font-size:19px;font-weight:500;margin-bottom:3px}
.scoreinfo .cmt{font-size:13px;color:var(--muted);margin-bottom:8px}
.scoreinfo .drv{font-size:11.5px;color:var(--muted);line-height:1.7}

.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin-bottom:18px}
.fact{background:var(--mcd-cream);border:1px solid #F2E0B8;border-radius:14px;padding:15px 16px;
  font-size:13.5px;line-height:1.65}
.fact:before{content:"";display:block;width:22px;height:3px;border-radius:2px;
  background:var(--mcd-red);margin-bottom:9px}
.fact b{color:var(--mcd-red-dk)}

/* These rules were lost when a stale-CSS cleanup over-deleted: without them
   the alerts and metric cards render as bare text below the hero. */
.alert{border-radius:14px;padding:18px 20px;margin-bottom:16px;display:flex;gap:16px;align-items:center}
.alert.red{background:linear-gradient(135deg,#FDECEA,#FFF6F5);border:1px solid #F5C6C0}
.alert.amber{background:linear-gradient(135deg,#FFF8E7,#FFFDF6);border:1px solid #F3DFA8}
.alert.blue{background:linear-gradient(135deg,#EAF3FA,#F7FCFF);border:1px solid #BBD9EF}
.alert .big{font-size:32px;font-weight:800;line-height:1;letter-spacing:-1px;flex:none}
.alert .txt{font-size:14px;color:#5A4A3F}
.alert .txt b{color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px}
.card .k{font-size:12px;color:var(--muted);margin-bottom:5px}
.card .v{font-size:23px;font-weight:700;letter-spacing:-.5px}
.card .v small{font-size:11.5px;font-weight:500;color:var(--muted)}
.card .x{font-size:11px;color:var(--muted);margin-top:3px}

section{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:18px}
h2{font-size:17px;margin-bottom:4px;display:flex;align-items:center;gap:8px}
h2 .n{width:22px;height:22px;border-radius:6px;background:var(--mcd-yellow);color:#3B2C00;
  font-size:12px;display:flex;align-items:center;justify-content:center;font-weight:800;flex:none}
.note{color:var(--muted);font-size:12.5px;margin-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--soft);vertical-align:middle}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}
.bar{height:7px;border-radius:4px;background:var(--soft);overflow:hidden;min-width:70px}
.bar i{display:block;height:100%;border-radius:4px}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border-radius:20px;background:var(--soft);
  color:var(--muted);border:1px solid var(--line);white-space:nowrap}
.tag.exact{background:#EAF7F0;color:var(--good);border-color:#B6E2CB}
.tag.est{background:#FFF8E7;color:var(--warn);border-color:#F3DFA8}
.tag.mute{background:#F4F1EC;color:#9A8E80;border-color:#E5DED3}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700}
.verdict{border-left:4px solid var(--mcd-red);padding:2px 0 2px 16px;margin:6px 0 14px}
.verdict .lead{font-size:19px;font-weight:700;margin-bottom:6px}
.verdict p{font-size:13.5px;color:#5A4A3F}
.split{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:14px}
.mini{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:13px}
.scen{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}
.scen .s{border:1px solid var(--line);border-radius:12px;padding:14px;text-align:center}
.scen .s.main{border-color:var(--mcd-yellow);background:#FFFDF5}
.scen .t{font-size:12px;color:var(--muted)}
.scen .p{font-size:22px;font-weight:800;letter-spacing:-.5px;margin:3px 0}
.scen .d{font-size:11px;color:var(--muted)}
footer{color:var(--muted);font-size:12px;text-align:center;padding:16px 0 4px;line-height:1.8}
ul.warnlist{margin:12px 0 0;padding-left:18px;font-size:13px;color:#6B5B4C}
ul.warnlist li{margin-bottom:5px}
.ap{border:1px solid var(--line);border-radius:12px;overflow:hidden}
.ap-head{padding:12px 14px;background:var(--soft);font-size:13px;font-weight:500;border-bottom:1px solid var(--line)}
.ap-row{display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid var(--soft);font-size:13px}
.ap-row .ap-name{flex:1}
.box-empty{width:14px;height:14px;border:1.5px solid #C9BFB2;border-radius:3px;flex:none}
.ap-note{padding:10px 14px;font-size:12.5px;color:var(--muted);border-bottom:1px solid var(--soft)}
.ap-avoid{padding:11px 14px;font-size:12.5px;color:#8A2018;background:#FDF2F0}
.ap-avoid:last-child{border-bottom:none}

.prod{display:flex;align-items:center;gap:11px}
.prod img{width:44px;height:44px;border-radius:10px;object-fit:cover;flex:none;
  background:var(--soft);border:1px solid var(--line)}
.prod .ph{width:44px;height:44px;border-radius:10px;flex:none;background:var(--mcd-cream);
  display:flex;align-items:center;justify-content:center;font-size:15px;color:var(--mcd-red-dk)}
.prod .nm{min-width:0}
.prod .nm .sm{font-size:11px;color:var(--muted);margin-top:1px}
.prize{display:flex;align-items:center;gap:9px}
.prize img{width:30px;height:30px;border-radius:7px;object-fit:cover;flex:none;background:var(--soft)}
.gloss{border-top:1px dashed var(--line);margin-top:14px;padding-top:12px}
.gloss dt{font-size:12.5px;color:var(--ink);margin-top:7px}
.gloss dd{font-size:12px;color:var(--muted);margin-left:0}
@media (max-width:760px){.grid,.split,.scen{grid-template-columns:1fr 1fr}.hero-lead{font-size:21px}}
"""


def esc(value: Any) -> str:
    return html.escape(str(value))


def n(value: Any, fmt: str = "{:.2f}", dash: str = "—") -> str:
    """Format a possibly-missing number without ever raising."""
    if value is None:
        return dash
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return dash


def _bar(value: Optional[float], best: Optional[float]) -> str:
    if value is None or not best or best <= 0:
        return "<div class='bar'><i style='width:0'></i></div>"
    ratio = min(1.0, value / best)
    color = (
        "linear-gradient(90deg,#DA291C,#FFC72C)"
        if ratio > 0.85
        else "linear-gradient(90deg,#E08A2B,#FFC72C)"
        if ratio > 0.55
        else "linear-gradient(90deg,#C9BFB2,#E3DACE)"
    )
    return f"<div class='bar'><i style='width:{int(ratio * 100)}%;background:{color}'></i></div>"


def render(data: ReportData) -> str:
    return "\n".join(
        [
            _head(data),
            _hero(data),
            _score(data),
            _facts(data),
            _alerts(data),
            _metrics(data),
            _verdict(data),
            _second_loss(data),
            _table(data),
            _clearance(data),
            _lottery(data),
            _history(data),
            _action(data),
            _footer(data),
        ]
    )


def _second_loss(data: ReportData) -> str:
    """The loss nobody counts: coupons that expire before being used."""
    profile = data.profile
    if not profile or not profile.usable:
        return ""

    rate = profile.rate or 0.0
    lost = (1.0 - rate) * 100
    tone = "bad" if rate < 0.5 else "warn" if rate < 0.8 else "good"
    examples = "、".join(profile.examples_lapsed[:3])
    raw_line = ""
    if profile.adjusted and profile.rate_raw is not None:
        raw_line = (
            f"<li>历史原始兑现率为 <b>{profile.rate_raw * 100:.0f}%</b>，"
            f"已按 20% 下限调整 —— 完全归零会让任何建议都变成「什么都别做」，"
            f"而这正是本报告要帮你改变的行为。</li>"
        )

    return f"""<section><h2><span class="n">3</span>二次损耗：换来的券，你用掉了吗</h2>
<p class="note">积分过期是第一次损耗。换来的券没用掉，是第二次 —— 结果一样，积分没了。</p>
<div class="alert" style="background:var(--soft);border:1px solid var(--line)">
  <div class="big" style="color:var(--{tone})">{rate * 100:.0f}%</div>
  <div class="txt">历史 <b>{profile.total_coupons}</b> 张券，用掉 <b>{profile.honoured}</b> 张，
  失效 <b>{profile.lapsed}</b> 张 —— 约 <b>{lost:.0f}%</b> 的券价值从未兑现。
  {"失效样例：" + esc(examples) if examples else ""}
  <br><span class="tag mute">{esc(profile.verdict)}</span>
  <span class="tag mute">置信度 {profile.confidence}</span></div>
</div>
<ul class="warnlist">
  {raw_line}
      <li>抽奖的奖品同样是券，因此奖池期望价值已按此兑现率折算。</li>
      <li>商城券是<b>你主动兑换</b>的，使用意愿高于随机抽中的奖品，因此<b>不套用</b>这个失效率；
          改为在排行中提示兑换截止时间。</li>
      <li>统计口径只含<b>优惠券类</b>奖品；节气门票等非券类奖品不参与兑现率计算。</li>
</ul></section>"""


ARCH = (
    '<svg class="arch" viewBox="0 0 40 40" aria-hidden="true">'
    '<path d="M6 38V20a6 6 0 0 1 12 0v18" fill="none" stroke="#FFC72C" stroke-width="6"/>'
    '<path d="M22 38V20a6 6 0 0 1 12 0v18" fill="none" stroke="#FFC72C" stroke-width="6"/>'
    "</svg>"
)


def _head(data: ReportData) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>麦麦积分清算局 · 积分体检报告</title><style>{CSS}</style></head>
<body><div class="wrap">"""


def _hero(data: ReportData) -> str:
    """The one screen that has to work on its own."""
    from .storytelling import plain_summary

    flag = "演示模式 · 合成数据" if data.mode != "live" else "实时数据"
    summary = plain_summary(data)
    return f"""<div class="hero">
  <div class="hero-top">
    {ARCH}<span class="brand">麦麦积分清算局</span>
    <span class="who">{esc(data.generated_at)}<br>{flag} · {esc(data.store_label or '未指定门店')}</span>
  </div>
  <div class="hero-lead">{esc(summary)}</div>
  <div class="hero-sub">积分过期体检 · 兑换排行 · 抽奖测算 —— 数据来自麦当劳官方 MCP 实时接口</div>
</div>"""


def _score(data: ReportData) -> str:
    from .storytelling import health_score

    hs = health_score(data)
    r, circ = 40, 2 * 3.14159 * 40
    filled = circ * hs.score / 100.0
    drivers = "".join(f"<div>· {esc(d)}</div>" for d in hs.drivers) or (
        "<div>· 没有明显的损耗项</div>"
    )
    return f"""<div class="scorewrap">
  <div class="ring">
    <svg width="96" height="96" viewBox="0 0 96 96">
      <circle cx="48" cy="48" r="{r}" fill="none" stroke="#EDE3D6" stroke-width="9"/>
      <circle cx="48" cy="48" r="{r}" fill="none" stroke="#DA291C" stroke-width="9"
        stroke-linecap="round" stroke-dasharray="{filled:.1f} {circ:.1f}"/>
    </svg>
    <div class="txt"><div class="num">{hs.score}</div><div class="cap">积分健康分</div></div>
  </div>
  <div class="scoreinfo">
    <div class="grade">{esc(hs.title)}</div>
    <div class="cmt">{esc(hs.comment)}</div>
    <div class="drv">{drivers}</div>
  </div>
</div>"""


def _facts(data: ReportData) -> str:
    from .storytelling import fun_facts

    items = fun_facts(data, getattr(data, "menu_price_items", ()))
    if not items:
        return ""
    cards = "".join(f"<div class='fact'>{esc(f)}</div>" for f in items)
    return f"<div class='facts'>{cards}</div>"


def _alerts(data: ReportData) -> str:
    out: List[str] = []

    # A breakfast-hours run prices a早餐 catalogue, so most main-menu coupons
    # cannot be valued. Say it up front — everything below is affected.
    if getattr(data, "menu_period", "") == "breakfast":
        out.append(
            """<div class="alert amber"><div class="big">早餐</div>
<div class="txt">当前拉取的是<b>早餐时段菜单</b>（约 10:30 前），
其中几乎没有正餐单品 —— 所以多数正餐券无法估值、覆盖率会明显偏低。
<b>建议 10:30 之后再跑一次</b>。</div></div>"""
        )

    acc = data.account

    ratio = acc.lost_ratio
    if ratio and acc.expired:
        out.append(
            f"""<div class="alert red"><div class="big">{ratio * 100:.0f}%</div>
<div class="txt">你累计获得 <b>{n(acc.accumulated, '{:,.1f}')}</b> 分，其中
<b>{n(acc.expired, '{:,.1f}')} 分已经过期清零</b>，实际用掉 {n(acc.used, '{:,.1f}')} 分，
现在还剩 <b>{n(acc.available, '{:,.1f}')}</b> 分。</div></div>"""
        )

    expiring = acc.expiring_soon or 0
    cash = expiring * (data.best_ppv or 0) / 100
    if expiring > 0:
        tone = "red" if cash >= 5 else "amber"
        tail = "现在就安排掉，别留到明年。" if cash >= 5 else "金额不大，但仍给出了最优用法。"
        out.append(
            f"""<div class="alert {tone}"><div class="big">本月</div>
<div class="txt"><b>{n(expiring, '{:,.0f}')} 分本月到期</b>，按当前最优兑换效率折算约
<b>¥{cash:.1f}</b>。{tail}</div></div>"""
        )

    lot = data.lottery
    if lot and lot.cost_points:
        draws = f"，按当前余额可抽 <b>{lot.affordable_draws}</b> 次" if lot.affordable_draws else ""
        out.append(
            f"""<div class="alert blue"><div class="big">抽奖</div>
<div class="txt">活动 <b>{esc(lot.activity_name or '未命名')}</b> 单次消耗
<b>{n(lot.cost_points, '{:g}')} 分</b>{draws}。官方未公布逐档概率，
下方给出三种假设下的期望区间。</div></div>"""
        )
    return "".join(out)


def _metrics(data: ReportData) -> str:
    acc = data.account
    draw = data.lottery.ppv("realistic") if data.lottery else None
    return f"""<div class="grid">
  <div class="card"><div class="k">可用积分</div>
    <div class="v">{n(acc.available, '{:,.1f}')}<small> 分</small></div>
    <div class="x">{esc(acc.currency or '积分')}</div></div>
  <div class="card"><div class="k">本月到期</div>
    <div class="v">{n(acc.expiring_soon, '{:,.0f}')}<small> 分</small></div>
    <div class="x">已清零 {n(acc.expired, '{:,.0f}')} 分</div></div>
  <div class="card"><div class="k">商城最优效率</div>
    <div class="v">{n(data.best_ppv)}<small> 元/百分</small></div>
    <div class="x">菜单 {data.menu_items} 项作锚点</div></div>
  <div class="card"><div class="k">抽奖期望效率</div>
    <div class="v">{n(draw)}<small> 元/百分</small></div>
    <div class="x">中性口径</div></div>
</div>"""


def _verdict(data: ReportData) -> str:
    if not data.lottery:
        return """<section><h2><span class="n">1</span>决策建议</h2>
<p class="note">本次未读取到抽奖活动，仅输出兑换侧结论。</p></section>"""
    kind, text = data.verdict
    lead = {
        "draw": "结论：积分拿去抽奖",
        "redeem": "结论：别抽奖，直接兑换",
        "coin_flip": "结论：两者接近，看你愿不愿意赌",
        "unknown": "结论：数据不足，暂无法判定",
    }.get(kind, "结论：数据不足")
    return f"""<section><h2><span class="n">1</span>抽奖 vs 直接兑换</h2>
<p class="note">同一笔积分的两条出路，用期望值对齐后再比。</p>
<div class="verdict"><div class="lead">{lead}</div><p>{esc(text)}</p></div>
<p class="note">口径说明：{esc(data.lottery.note)}</p></section>"""


_UNPRICED_LABEL = {
    "no_menu_match": "菜单无对应餐品",
    "unresolved": "名称无法解析",
    "unknown_kind": "券型无法识别",
    "no_discount": "折算后无价差",
    "needs_ppv": "缺少积分汇率",
}


def _table(data: ReportData) -> str:
    rows: List[str] = []
    shown = 0
    for r in data.redemptions:
        if shown >= 16:
            break
        # zero-spread coupons have a PPV but no value: keep them out of the ranking
        if r.ppv is not None and (r.benefit or 0) <= 0:
            continue
        shown += 1
        if r.ppv is None:
            basis = (r.value.basis if r.value else "") or ""
            label = _UNPRICED_LABEL.get(basis, "无法估值")
            rows.append(
                f"<tr><td class='num'>{shown}</td><td>{_prod_cell(r)}</td>"
                f"<td class='num'>{n(r.points, '{:,.0f}')}</td><td class='num'>—</td>"
                f"<td class='num'>—</td><td><span class='tag mute'>{label}</span></td></tr>"
            )
            continue
        method = (r.value.match_method if r.value else None) or ""
        cls, label = {
            "exact": ("exact", "菜单精确匹配"),
            "fuzzy": ("exact", "菜单模糊匹配"),
            "components": ("est", "单品加总估算"),
            "category": ("est", "同类目估算"),
        }.get(method, ("mute", "按券面值"))
        if r.window_label:
            label += f" · {r.window_label}"
        rows.append(
            f"<tr><td class='num'>{shown}</td><td>{_prod_cell(r)}</td>"
            f"<td class='num'>{n(r.points, '{:,.0f}')}</td>"
            f"<td class='num'>¥{n(r.benefit)}</td>"
            f"<td class='num'><b>{n(r.ppv)}</b>{_you_cell(r)}</td>"
            f"<td>{_bar(r.ppv, data.best_ppv)}"
            f"<div style='margin-top:4px'><span class='tag {cls}'>{label}</span></div></td></tr>"
        )

    priced, total = data.coverage
    pct = f"{data.coverage_pct:.0f}%" if data.coverage_pct else "—"
    est_note = (
        f"，其中 {data.estimate_count} 件为估算值（同类目价格分布或单品加总）"
        if data.estimate_count
        else ""
    )
    return f"""<section><h2><span class="n">2</span>兑换性价比排行</h2>
<p class="note">单位 <b>元 / 100 积分</b>，越高越划算。
「节省」是这张券实际替你省下的人民币 —— 这里的兑换物<b>全部是折扣券</b>，
所以收益等于「原价比应付价格的差额」，而不是券面价格。<br>
估值覆盖 <b>{priced}/{total}</b>（{pct}）{est_note}；
未覆盖的会标注原因，不会用编造的数字凑数。</p>
<table><thead><tr><th>#</th><th>兑换商品</th><th class="num">积分</th>
<th class="num">节省</th><th class="num">元/百分</th><th>效率</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></section>"""


def _prod_cell(r) -> str:
    """Product thumbnail with a graceful fallback.

    Image URLs come from upstream, so they are escaped; a missing or broken
    image degrades to the brand placeholder rather than an empty box.
    """
    if getattr(r, "image", None):
        return (
            f"<div class='prod'><img src='{esc(r.image)}' alt='' loading='lazy' "
            f"onerror=\"this.style.display='none'\"><span class='nm'>{esc(r.name)}</span></div>"
        )
    return (
        f"<div class='prod'><span class='ph'>M</span>"
        f"<span class='nm'>{esc(r.name)}</span></div>"
    )


def _prize_cell(r) -> str:
    if getattr(r, "image", None):
        return (
            f"<div class='prize'><img src='{esc(r.image)}' alt='' loading='lazy' "
            f"onerror=\"this.style.display='none'\"><span>{esc(r.name)}</span></div>"
        )
    return esc(r.name)


def _you_cell(r) -> str:
    """Personalised PPV, only when a preference profile actually exists."""
    if r.ppv_personal is None or r.affinity >= 0.999:
        return ""
    hit = esc(r.affinity_hit) if r.affinity_hit else "未见于历史订单"
    return (
        f"<div style='font-size:11px;color:var(--muted);margin-top:2px'>"
        f"为你 {n(r.ppv_personal)} · {hit}</div>"
    )


def _clearance(data: ReportData) -> str:
    if not data.plan:
        return f"""<section><h2><span class="n">4</span>清仓方案与攒单建议</h2>
<p class="note">在 {n(data.budget, '{:,.0f}')} 分预算内未找到可组合的可估值商品。</p></section>"""
    rows = "".join(
        f"<tr><td>{esc(i.name)}</td><td class='num'>{i.count}</td>"
        f"<td class='num'>{n(i.points_each, '{:,.0f}')}</td>"
        f"<td class='num'>{n(i.total_points, '{:,.0f}')}</td>"
        f"<td class='num'>¥{n(i.total_value)}</td></tr>"
        for i in data.plan
    )
    leftover = (
        f"<li>剩余 <b>{n(data.plan_leftover, '{:,.0f}')}</b> 分凑不成完整组合，可留到下月或搭配现金。</li>"
        if data.plan_leftover > 0
        else ""
    )
    return f"""<section><h2><span class="n">4</span>清仓方案与攒单建议</h2>
<p class="note">预算 {n(data.budget, '{:,.0f}')} 分，完全背包求解「总节省最大」的兑换组合。</p>
<table><thead><tr><th>兑换商品</th><th class="num">数量</th><th class="num">单价(分)</th>
<th class="num">小计(分)</th><th class="num">节省</th></tr></thead>
<tbody>{rows}</tbody></table>
<ul class="warnlist">
  <li>合计消耗 <b>{n(data.plan_points, '{:,.0f}')}</b> 分，预计节省 <b>¥{n(data.plan_value)}</b>。</li>
  {leftover}
</ul>
{_planning_block(data)}
</section>"""


def _planning_block(data: ReportData) -> str:
    """Multi-period view: what is at risk now, and is waiting ever worth it."""
    bucket = data.bucket
    if not bucket or bucket.total <= 0:
        return ""

    split = (
        f"<div class='mini'><div class='k'>本月到期 · 必须花掉</div>"
        f"<div class='v'>{n(bucket.expiring, ',.0f')} 分</div></div>"
        f"<div class='mini'><div class='k'>其余 · 可以攒着</div>"
        f"<div class='v'>{n(bucket.flexible, ',.0f')} 分</div></div>"
    )

    if data.save_up:
        targets = "".join(
            f"<tr><td>{esc(t.name)}</td><td class='num'>{n(t.points, ',.0f')}</td>"
            f"<td class='num'>{n(t.gap, ',.0f')}</td><td class='num'>{n(t.ppv)}</td>"
            f"<td class='num'>{n(t.gain_ratio)}×</td></tr>"
            for t in data.save_up
        )
        targets_html = (
            "<table style='margin-top:12px'><thead><tr><th>攒够可换</th>"
            '<th class="num">需要</th><th class="num">还差</th>'
            '<th class="num">元/百分</th><th class="num">提升</th>'
            f"</tr></thead><tbody>{targets}</tbody></table>"
        )
    else:
        targets_html = (
            "<p class='note' style='margin-top:12px'><b>没有值得攒的目标</b> —— "
            "余额现在能换到的券，效率已经压过所有更高价位的券。"
            "不必为了「换大的」而攒分。</p>"
        )

    return (
        f"<div class='split' style='margin-top:16px'>{split}</div>"
        f"<p class='note' style='margin-top:12px'>{esc(bucket.note)}</p>{targets_html}"
    )


def _lottery(data: ReportData) -> str:
    lot = data.lottery
    if not lot or not lot.rows:
        return """<section><h2><span class="n">5</span>抽奖期望值拆解</h2>
<p class="note">当前没有可分析的抽奖活动。</p></section>"""

    rows: List[str] = []
    for r in lot.rows:
        benefit_cell = (
            f"¥{n(r.benefit)}"
            if r.benefit is not None
            else "<span class='tag mute'>无法估值</span>"
        )
        rows.append(
            f"<tr><td>{_prize_cell(r)}</td>"
            f"<td class='num'>{n((r.probability or 0) * 100, '{:.2f}')}%</td>"
            f"<td class='num'>{benefit_cell}</td>"
            f"<td class='num'>¥{n(r.ev_contribution, '{:.3f}')}</td></tr>"
        )

    def card(key: str, title: str, desc: str, main: bool = False) -> str:
        cls = "s main" if main else "s"
        return (
            f"<div class='{cls}'><div class='t'>{title}</div>"
            f"<div class='p'>¥{n(lot.scenarios.get(key))}</div>"
            f"<div class='d'>{desc}<br>{n(lot.ppv(key))} 元/百分</div></div>"
        )

    scen = (
        card("optimistic", "乐观 · 等概率", "官方若近似均分")
        + card("realistic", "中性 · 幂律衰减", "大奖越难中，主口径", True)
        + card("pessimistic", "悲观 · 三次幂", "大奖几乎抽不到")
    )

    return f"""<section><h2><span class="n">5</span>抽奖期望值拆解</h2>
<p class="note">活动 <b>{esc(lot.activity_name or '未命名')}</b> ｜ 单次消耗
<b>{n(lot.cost_points, '{:g}')}</b> 分 ｜ {esc(lot.draw_type_text or '')} ｜
已估值 <b>{lot.priced_count}</b>/<b>{len(lot.rows)}</b> 项奖品</p>
<div class="scen">{scen}</div>
<table><thead><tr><th>奖品</th><th class="num">中性概率</th>
<th class="num">折算价值</th><th class="num">EV 贡献</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<ul class="warnlist">
  <li>EV = Σ p<sub>i</sub> × V<sub>i</sub>，V<sub>i</sub> 由菜单实时价格推导：
      折扣券按「原价 × (1 − 折扣率)」，组合券按「原价合计 − 实际支付」。</li>
  <li>官方未公布中奖概率，三种假设差异很大 —— <b>请按区间而非单点数字做判断</b>。</li>
</ul></section>"""


def _action(data: ReportData) -> str:
    """The section that makes the report executable rather than informational."""
    from .action_plan import build_action_lines

    lines = build_action_lines(data)
    if not lines:
        return ""
    rows: List[str] = []
    for line in lines:
        if line.kind == "header":
            rows.append(f"<div class='ap-head'>{esc(line.text)}</div>")
        elif line.kind == "redeem":
            dead = f"<span class='tag mute'>{esc(line.deadline)}</span>" if line.deadline else ""
            rows.append(
                f"<div class='ap-row'><span class='box-empty'></span>"
                f"<span class='ap-name'>{esc(line.text)}</span>"
                f"<span class='num'>{n(line.points, '{:,.0f}')} 分</span>"
                f"<span class='num'>省 ¥{n(line.saving)}</span>{dead}</div>"
            )
        elif line.kind == "note":
            rows.append(f"<div class='ap-note'>{esc(line.text)}</div>")
        elif line.kind == "avoid":
            rows.append(f"<div class='ap-avoid'>{esc(line.text)}</div>")

    return f"""<section><h2><span class="n">7</span>行动清单</h2>
<p class="note">照着做就行 —— 用 <code>--plan</code> 可以导出 Markdown 版本，
直接贴进备忘录或提醒事项。</p>
<div class="ap">{''.join(rows)}</div></section>"""


def _history(data: ReportData) -> str:
    if not data.history:
        return ""
    rows = "".join(
        f"<tr><td>{esc(h.get('name'))}</td><td>{esc(h.get('type') or '—')}</td>"
        f"<td>{esc(h.get('record_time') or '—')}</td><td>{esc(h.get('status') or '—')}</td></tr>"
        for h in data.history[:10]
    )
    return f"""<section><h2><span class="n">6</span>我的中奖记录</h2>
<p class="note">用于交叉验证上面的概率假设是否与实际手感吻合。</p>
<table><thead><tr><th>奖品</th><th>类型</th><th>中奖时间</th><th>状态</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""


def _glossary() -> str:
    """Plain-language definitions, so the report never assumes vocabulary."""
    from .storytelling import PLAIN_GLOSSARY

    rows = "".join(f"<dt>{esc(term)}</dt><dd>{esc(mean)}</dd>" for term, mean in PLAIN_GLOSSARY)
    return f"""<section><h2><span class="n">?</span>这些词是什么意思</h2>
<dl class="gloss">{rows}</dl></section>"""


def _footer(data: ReportData) -> str:
    warns = "".join(f"<li>{esc(w)}</li>" for w in data.warnings)
    block = (
        f'<section><h2><span class="n">!</span>运行提示</h2><ul class="warnlist">{warns}</ul></section>'
        if data.warnings
        else ""
    )
    return f"""{block}
{_glossary()}
<footer>
本工具为非官方第三方作品，与麦当劳中国无隶属关系。<br>
所有估值基于麦当劳 MCP 返回的实时菜单价格推导，仅供参考；实际积分、库存与活动状态以麦当劳官方 App 为准。<br>
本项目只读，不执行任何下单、兑换或抽奖操作。<br>
mcd-points-rescue · 2026 麦当劳程序员创意开发大赛参赛作品
</footer></div></body></html>"""
