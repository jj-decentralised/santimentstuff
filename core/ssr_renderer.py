"""
Server-side HTML renderer — pure HTML, zero JavaScript.
Speed-first rewrite: minimal HTML, system fonts, no bloat.
"""

import html as html_mod
from datetime import datetime, timedelta
from typing import Optional

from .svg_charts import (
    sparkline_svg, line_chart_svg, comparison_table,
    market_heatmap_svg, dominance_bar_svg,
    scatter_plot_svg, THESIS_COLORS,
)


# ================================================================
# FORMAT HELPERS
# ================================================================

def _esc(s) -> str:
    if s is None:
        return ""
    return html_mod.escape(str(s))


def _relative_time(iso_str: str) -> str:
    try:
        if "T" in iso_str:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00").replace("+00:00", ""))
        else:
            dt = datetime.strptime(iso_str[:19], "%Y-%m-%d %H:%M:%S")
        delta = datetime.utcnow() - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso_str[:16]


def fmt_usd(v) -> str:
    if v is None:
        return "&mdash;"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}${a/1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a/1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a/1e6:.2f}M"
    if a >= 1e3:
        return f"{sign}${a:,.0f}"
    if a >= 1:
        return f"{sign}${a:,.2f}"
    if a >= 0.01:
        return f"{sign}${a:.4f}"
    return f"{sign}${a:.6f}"


def fmt_num(v) -> str:
    if v is None:
        return "&mdash;"
    a = abs(v)
    if a >= 1e9:
        return f"{v/1e9:.2f}B"
    if a >= 1e6:
        return f"{v/1e6:.2f}M"
    if a >= 1e3:
        return f"{v/1e3:,.0f}K"
    return f"{v:,.0f}"


def fmt_pct(v) -> str:
    if v is None:
        return "&mdash;"
    return f"{v:+.2f}%"


def pct_class(v) -> str:
    if v is None:
        return "mt"
    return "up" if v > 0 else "dn" if v < 0 else "mt"


# Backward-compat alias
css_class = pct_class


def mvrv_zone(v):
    if v is None:
        return ("N/A", "zone-neutral", "No data")
    if v < 0.7:
        return ("Deep Value", "zone-extreme-low", "Well below realized value")
    if v < 1.0:
        return ("Undervalued", "zone-undervalued", "Below realized value")
    if v < 1.5:
        return ("Fair Value", "zone-fair", "Near realized value")
    if v < 2.5:
        return ("Elevated", "zone-fair-high", "Above realized value")
    if v < 3.5:
        return ("Overvalued", "zone-overvalued", "Well above realized value")
    return ("Euphoria", "zone-extreme-high", "Extreme overvaluation")


# ================================================================
# THEME + DATA INJECTION
# ================================================================

_ticker_data_fn = None
_freshness_fn = None
_current_theme = "auto"


def set_ticker_data_fn(fn):
    global _ticker_data_fn
    _ticker_data_fn = fn


def set_freshness_fn(fn):
    global _freshness_fn
    _freshness_fn = fn


def set_theme(theme: str):
    global _current_theme
    _current_theme = theme


THESIS_LABELS = {
    "smart_money": "Smart Money",
    "builder_momentum": "Builder Momentum",
    "deep_value": "Deep Value",
    "distribution_warning": "Distribution Warning",
    "hodler": "HODLer",
    "high_utility": "High Utility",
    "speculative": "Speculative",
    "uncategorized": "Uncategorized",
}

THESIS_DESCRIPTIONS = {
    "smart_money": "Exchange accumulation detected. Historically bullish. Consider building position over 5\u20137 days.",
    "builder_momentum": "Active builder momentum. Favor for 3\u20136 month holds \u2014 dev activity leads price.",
    "deep_value": "Deep value opportunity. High conviction DCA zone. Average in over 2\u20134 weeks.",
    "distribution_warning": "Distribution risk. Take profits or tighten stop-losses. Reduce exposure.",
    "hodler": "Strong holder base with low velocity. Suitable for long-term positions.",
    "high_utility": "Genuine network usage outpacing speculation. Favor for medium-term holds.",
    "speculative": "Speculation-driven. Short-term momentum only \u2014 use tight stops.",
    "uncategorized": "No clear on-chain signal. Wait for thesis to develop before entering.",
}


# ================================================================
# FRESHNESS BADGE
# ================================================================

def _freshness_badge() -> str:
    if not _freshness_fn:
        return ""
    try:
        status = _freshness_fn()
        if isinstance(status, dict):
            last_pull = status.get("last_pull")
            if last_pull:
                rel = _relative_time(last_pull)
                return f'<a href="/sync" class="fresh" title="Last sync: {_esc(last_pull)}">&#10003; {rel}</a>'
            return '<a href="/sync" class="fresh stale">&#9679; Loading</a>'
        return ""
    except Exception:
        return ""


# ================================================================
# PAGE SHELL — Minimal overhead
# ================================================================

def page_shell(title: str, body: str, active_nav: str = "",
               ticker_data: list = None, auto_refresh: int = 0,
               theme: str = "auto", og_description: str = "",
               canonical: str = "") -> str:
    nav_items = [
        ("dashboard", "/", "Dashboard"),
        ("market", "/market", "Market"),
        ("insights", "/insights", "Insights"),
        ("sectors", "/sectors", "Sectors"),
        ("compare", "/compare?tokens=bitcoin,ethereum,solana", "Compare"),
        ("watchlist", "/watchlist?tokens=bitcoin,ethereum,solana,cardano,avalanche", "Watchlist"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="{"active" if key == active_nav else ""}">{label}</a>'
        for key, href, label in nav_items
    )

    refresh = f'<meta http-equiv="refresh" content="{auto_refresh}">' if auto_refresh > 0 else ''
    canon = f'<link rel="canonical" href="{_esc(canonical)}">' if canonical else ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — Onchain Pulse</title>
{refresh}
<meta name="description" content="{_esc(og_description) if og_description else 'On-chain crypto analytics dashboard. MVRV, active addresses, exchange flows, dev activity — powered by Santiment.'}">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%23212529'/><text x='16' y='22' text-anchor='middle' fill='%23ffffff' font-family='sans-serif' font-weight='900' font-size='18'>P</text></svg>">
<link rel="stylesheet" href="/static/css/dashboard.css">
{canon}
</head>
<body>
<a href="#m" class="skip">Skip to content</a>
<header class="hd"><div class="hd-in">
<a href="/" class="logo">Onchain<span>Pulse</span></a>
<nav class="hd-nav">{nav_html}</nav>
<div class="hd-r">
<form action="/market" method="get" class="hd-search"><input type="text" name="q" placeholder="Search..." autocomplete="off"></form>
{_freshness_badge()}
</div>
</div></header>
<main class="main wrap" id="m">{body}</main>
<footer class="ft">Data via <a href="https://santiment.net">Santiment</a> &middot; <a href="/sync">Sync</a> &middot; <a href="/glossary">Glossary</a> &middot; <a href="/api">API</a> &middot; {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC</footer>
</body>
</html>"""


# ================================================================
# BRIEFING PAGE
# ================================================================

def render_briefing_page(briefing: dict, pull_status: str, cache_stats: dict, universe_size: int, sectors: dict = None) -> str:
    if not briefing:
        return page_shell("Dashboard", '<div class="empty"><h2>Building your dashboard...</h2><p>Data is being pulled from Santiment. <a href="/sync">View sync progress</a></p></div>', active_nav="dashboard")

    b = briefing
    p = []

    # Regime
    avg_mvrv = b.get("avg_mvrv")
    breadth = b.get("breadth", {})
    up = breadth.get("up", 0)
    down = breadth.get("down", 0)
    total_bd = up + down
    breadth_pct = (up / total_bd * 100) if total_bd else 50

    if avg_mvrv is not None and avg_mvrv < 1.0 and breadth_pct < 40:
        regime, regime_cls = "Bearish", "dn"
    elif avg_mvrv is not None and avg_mvrv > 2.0 and breadth_pct > 65:
        regime, regime_cls = "Bullish", "up"
    elif breadth_pct > 55:
        regime, regime_cls = "Cautiously Bullish", "up"
    elif breadth_pct < 45:
        regime, regime_cls = "Cautiously Bearish", "dn"
    else:
        regime, regime_cls = "Neutral", "mt"

    # Composite score
    score_parts = []
    if avg_mvrv is not None:
        score_parts.append(min(100, max(0, (avg_mvrv / 3.0) * 100)))
    if total_bd > 0:
        score_parts.append(breadth_pct)
    vol_conc = b.get("vol_concentration_top10", 0)
    if vol_conc > 0:
        score_parts.append(max(0, 100 - vol_conc))
    composite = int(sum(score_parts) / len(score_parts)) if score_parts else 50
    if composite >= 75:
        score_label, score_cls = "Extreme Greed", "score-greed"
    elif composite >= 55:
        score_label, score_cls = "Greed", "score-greed-mild"
    elif composite >= 45:
        score_label, score_cls = "Neutral", "score-neutral"
    elif composite >= 25:
        score_label, score_cls = "Fear", "score-fear-mild"
    else:
        score_label, score_cls = "Extreme Fear", "score-fear"

    zone_label, zone_css, zone_desc = mvrv_zone(avg_mvrv)

    now_str = datetime.utcnow().strftime("%b %d, %Y")

    # ── Hero stats row ──
    p.append(f"""
<h1 class="pg-t">Dashboard</h1>
<p class="pg-sub">{now_str} &middot; {b.get("total_tokens", 0)} tokens &middot; <span class="{regime_cls} bold">{regime}</span></p>

<div class="stats">
<div class="stat stat-hero"><div class="stat-l">Total Market Cap</div><div class="stat-v">{fmt_usd(b.get("total_mcap"))}</div></div>
<div class="stat stat-hero"><div class="stat-l">24h Volume</div><div class="stat-v">{fmt_usd(b.get("total_vol"))}</div></div>
<div class="stat"><div class="stat-l">Breadth</div><div class="stat-v"><span class="up">{up}</span> / <span class="dn">{down}</span></div>
<div class="breadth-bar"><div class="breadth-fill" style="width:{breadth_pct:.0f}%"></div></div></div>
<div class="stat"><div class="stat-l">Avg MVRV</div><div class="stat-v">{f"{avg_mvrv:.2f}" if avg_mvrv else "&mdash;"} <span class="zone {zone_css}">{zone_label}</span></div></div>
<div class="stat"><div class="stat-l">Sentiment</div><div class="stat-v"><span class="score {score_cls}">{composite}</span> {score_label}</div></div>
</div>""")

    # Prescriptive narrative
    narr = []
    if breadth_pct >= 65:
        narr.append(f"Broad strength ({breadth_pct:.0f}% up) \u2014 momentum strategies favored. Consider increasing positions on tokens with positive exchange outflow")
    elif breadth_pct >= 55:
        narr.append(f"Moderate breadth ({breadth_pct:.0f}% up) \u2014 selective buying. Focus on tokens with improving fundamentals")
    elif breadth_pct <= 35:
        narr.append(f"Broad weakness ({breadth_pct:.0f}% up) \u2014 capital preservation. Accumulate Deep Value selectively")
    elif breadth_pct <= 45:
        narr.append(f"Cautious breadth ({breadth_pct:.0f}% up) \u2014 reduce risk. Favor tokens with strong holder bases")
    if vol_conc > 70:
        narr.append(f"Volume concentrated in top 10 ({vol_conc:.0f}%) \u2014 capital is selective. Focus on large-caps with improving on-chain fundamentals")
    if avg_mvrv is not None:
        if avg_mvrv < 0.8:
            narr.append(f"MVRV at {avg_mvrv:.2f} (deep undervaluation). High conviction accumulation zone. DCA into quality assets")
        elif avg_mvrv < 1.0:
            narr.append(f"MVRV at {avg_mvrv:.2f} (undervalued). Favor value plays. Rotate from speculative to fundamentally strong tokens")
        elif avg_mvrv > 3.0:
            narr.append(f"MVRV at {avg_mvrv:.2f} (euphoria). Take profits aggressively. Rotate into stables or hedge positions")
        elif avg_mvrv > 2.5:
            narr.append(f"MVRV at {avg_mvrv:.2f} (overheating). Tighten stop-losses. Rotate from Euphoria-zone to Deep Value tokens")

    # Regime guidance
    if regime == "Bullish":
        narr.append("Regime: Bullish \u2014 favor momentum plays and Smart Money thesis tokens")
    elif regime == "Bearish":
        narr.append("Regime: Bearish \u2014 capital preservation. Accumulate Deep Value selectively")
    elif regime == "Cautiously Bullish":
        narr.append("Regime: Cautiously bullish \u2014 selective exposure. Favor tokens with improving on-chain activity")
    elif regime == "Cautiously Bearish":
        narr.append("Regime: Cautiously bearish \u2014 reduce position sizes. Focus on quality with low MVRV")

    if narr:
        p.append(f'<div class="narrative">{". ".join(narr)}.</div>')

    # Market composite scores
    momentum_sc = min(100, max(0, int((breadth_pct - 30) / 40 * 100))) if total_bd > 0 else 50
    value_sc = min(100, max(0, int((3.5 - (avg_mvrv or 1.5)) / 3.0 * 100))) if avg_mvrv is not None else 50
    risk_sc = min(100, max(0, int(vol_conc))) if vol_conc > 0 else 50
    health_daa = b.get("total_daa") or 0
    health_dev = b.get("total_dev") or 0
    health_sc = min(100, max(0, 50 + (1 if health_daa > 100000 else -10) + (1 if health_dev > 1000 else -10) + int(breadth_pct - 50)))

    def _score_color(v, inverted=False):
        if inverted:
            if v >= 65: return "var(--red)"
            if v <= 35: return "var(--green)"
        else:
            if v >= 65: return "var(--green)"
            if v <= 35: return "var(--red)"
        return "var(--amber)"

    def _score_guide(name, v):
        if name == "Momentum":
            return "Strong \u2014 favor trend-following" if v >= 65 else "Weak \u2014 wait for confirmation" if v <= 35 else "Neutral \u2014 selective entries"
        if name == "Value":
            return "Undervalued \u2014 accumulation opportunities" if v >= 65 else "Overvalued \u2014 tighten stops" if v <= 35 else "Fair \u2014 focus on quality"
        if name == "Risk":
            return "Elevated \u2014 reduce size, tighten stops" if v >= 65 else "Low \u2014 confidence in sizing" if v <= 35 else "Moderate \u2014 standard sizing"
        if name == "Health":
            return "Strong fundamentals \u2014 conviction buy setups" if v >= 65 else "Weak fundamentals \u2014 be cautious" if v <= 35 else "Mixed \u2014 selective"
        return ""

    scores_html = ""
    for sname, sval, inv in [("Momentum", momentum_sc, False), ("Value", value_sc, False), ("Risk", risk_sc, True), ("Health", health_sc, False)]:
        sc = _score_color(sval, inv)
        guide = _score_guide(sname, sval)
        scores_html += f'<div class="stat"><div class="stat-l">{sname}</div><div class="stat-v" style="color:{sc};font-size:1.2rem">{sval}</div><div style="font-size:.68rem;color:var(--tx2)">{guide}</div></div>'

    p.append(f'<div class="card"><div class="card-hd"><span class="card-t">Market Scores</span></div><div class="stats">{scores_html}</div></div>')

    # ── Charts row (2 columns) ──
    trends = b.get("trends", {})
    all_tokens = b.get("all_tokens", [])
    charts_left = ""
    charts_right = ""

    # BTC price chart (left)
    btc_price = trends.get("btc_price", [])
    if btc_price and len(btc_price) >= 5:
        btc_data = [d for d in btc_price if d.get("value") is not None]
        if btc_data:
            btc_series = [{"data": btc_data, "label": "BTC/USD"}]
            btc_svg = line_chart_svg(btc_series, title="", width=600, height=200, show_area=True)
            charts_left = f'<div class="card"><div class="card-hd"><span class="card-t">BTC Price (90d)</span></div><div class="chart-w">{btc_svg}</div></div>'

    # Market heatmap (right)
    if all_tokens and len(all_tokens) >= 10:
        heatmap_tokens = all_tokens[:40]
        charts_right = f'<div class="card"><div class="card-hd"><span class="card-t">Market Heatmap</span></div><div class="chart-w">{market_heatmap_svg(heatmap_tokens, max_tokens=40)}</div></div>'

    if charts_left or charts_right:
        p.append(f'<div class="grid-2">{charts_left}{charts_right}</div>')

    # ── Dominance bar + MVRV zones (2 columns) ──
    dom_html = ""
    zone_html = ""

    # Dominance bar
    if all_tokens and len(all_tokens) >= 5:
        dom_html = f'<div class="card"><div class="card-hd"><span class="card-t">Market Dominance</span></div><div class="chart-w">{dominance_bar_svg(all_tokens[:20], width=600, height=80)}</div></div>'

    # MVRV zone distribution
    zones = b.get("mvrv_zones", {})
    zone_total = b.get("mvrv_total", 0) or 1
    zone_defs = [("Deep Value", "deep_value", "#48bb78"), ("Undervalued", "undervalued", "#38a169"),
                 ("Fair", "fair", "#ecc94b"), ("Elevated", "elevated", "#ed8936"),
                 ("Overvalued", "overvalued", "#fc8181"), ("Euphoria", "euphoria", "#e53e3e")]
    zone_bars = ""
    for label, key, color in zone_defs:
        cnt = zones.get(key, 0)
        pct = cnt / zone_total * 100 if zone_total else 0
        if cnt > 0:
            zone_bars += f'<div class="hist-col"><div class="hist-bar" style="height:{max(2, pct*0.8):.0f}px;background:{color}"></div><div class="hist-ct">{cnt}</div><div class="hist-lb">{label}</div></div>'
    if zone_bars:
        zone_html = f'<div class="card"><div class="card-hd"><span class="card-t">MVRV Zones</span></div><div class="hist">{zone_bars}</div></div>'

    if dom_html or zone_html:
        p.append(f'<div class="grid-2">{dom_html}{zone_html}</div>')

    # ── Signals + Movers (2 columns) ──
    signals_html = ""
    movers_html = ""

    # On-chain signals
    signals = b.get("signals", [])
    if signals:
        sig_rows = ""
        for s in signals[:8]:
            ch = s.get("change", 0)
            cls = "up" if "spike" in s.get("signal", "") or "accumulation" in s.get("signal", "") or "surge" in s.get("signal", "") else "dn"
            sig_rows += f'<tr><td><a href="/token/{s.get("slug","")}">{_esc(s.get("name","")[:16])}</a></td><td>{_esc(s.get("metric",""))}</td><td class="{cls}">{fmt_pct(ch)}</td></tr>'
        signals_html = f'<div class="card"><div class="card-hd"><span class="card-t">On-Chain Signals</span></div><div class="tbl-w"><table><thead><tr><th>Token</th><th>Metric</th><th class="col-r">Change</th></tr></thead><tbody>{sig_rows}</tbody></table></div></div>'

    # Gainers / Losers
    gainers = b.get("gainers", [])[:6]
    losers = b.get("losers", [])[:6]
    if gainers or losers:
        def _mover_rows(tokens):
            return "".join(
                f'<a href="/token/{t.get("slug","")}" class="mover-chip"><span>{_esc(t.get("ticker",""))}</span><span class="{pct_class(t.get("price_usd_change"))}">{fmt_pct(t.get("price_usd_change"))}</span></a>'
                for t in tokens
            )
        movers_html = f'<div class="card"><div class="card-hd"><span class="card-t">Movers</span></div><div class="movers"><div><div class="stat-l" style="margin-bottom:4px">Gainers</div>{_mover_rows(gainers)}</div><div><div class="stat-l" style="margin-bottom:4px">Losers</div>{_mover_rows(losers)}</div></div></div>'

    if signals_html or movers_html:
        p.append(f'<div class="grid-2">{signals_html}{movers_html}</div>')

    # ── Sector performance table ──
    sector_data = b.get("sector_data", {})
    if sector_data:
        sec_rows = ""
        sorted_secs = sorted(sector_data.items(), key=lambda x: x[1].get("mcap", 0), reverse=True)[:12]
        for sec_key, data in sorted_secs:
            sec_label = (sectors or {}).get(sec_key, sec_key.replace("_", " ").title())
            avg_ch = data.get("pct_sum", 0) / max(data.get("count", 1), 1)
            sec_rows += f'<tr><td><a href="/sector/{sec_key}" class="sec-tag">{_esc(sec_label)}</a></td><td class="col-r">{data.get("count",0)}</td><td class="col-r">{fmt_usd(data.get("mcap"))}</td><td class="col-r {pct_class(avg_ch)}">{fmt_pct(avg_ch)}</td></tr>'
        p.append(f'<div class="card"><div class="card-hd"><span class="card-t">Sectors</span><a href="/sectors" class="export-btn">View all</a></div><div class="tbl-w"><table><thead><tr><th>Sector</th><th class="col-r">Tokens</th><th class="col-r">MCap</th><th class="col-r">Avg 24h</th></tr></thead><tbody>{sec_rows}</tbody></table></div></div>')

    # ── Network health ──
    p.append(f"""
<div class="card"><div class="card-hd"><span class="card-t">Network Health</span></div>
<div class="stats">
<div class="stat"><div class="stat-l">Total DAA</div><div class="stat-v">{fmt_num(b.get("total_daa"))}</div></div>
<div class="stat"><div class="stat-l">Dev Activity</div><div class="stat-v">{fmt_num(b.get("total_dev"))}</div></div>
<div class="stat"><div class="stat-l">Accumulating</div><div class="stat-v up">{b.get("accumulating", 0)}</div></div>
<div class="stat"><div class="stat-l">Distributing</div><div class="stat-v dn">{b.get("distributing", 0)}</div></div>
</div></div>""")

    # ── Quick nav ──
    p.append("""
<div class="stats">
<a href="/market" class="stat"><div class="stat-l">Market</div><div class="stat-v" style="font-size:.78rem">Full token table</div></a>
<a href="/market?view=screener" class="stat"><div class="stat-l">Screener</div><div class="stat-v" style="font-size:.78rem">Filter &amp; sort</div></a>
<a href="/market?view=valuation" class="stat"><div class="stat-l">Valuation</div><div class="stat-v" style="font-size:.78rem">MVRV zones</div></a>
<a href="/insights" class="stat"><div class="stat-l">Insights</div><div class="stat-v" style="font-size:.78rem">Scatter plots</div></a>
</div>""")

    return page_shell("Dashboard", "\n".join(p), active_nav="dashboard")


# ================================================================
# EXPLORE PAGE
# ================================================================

def render_explore_page(tokens: list, page: int = 1, per_page: int = 100,
                        total: int = 0, sector: str = "all", category: str = "all",
                        sectors: dict = None, categories: dict = None,
                        search: str = "", briefing: dict = None,
                        sort_by: str = "marketcap_usd", order: str = "desc",
                        view: str = "full") -> str:
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page

    # Sector filter
    sec_btns = f'<a href="/explore" class="fbtn{" on" if sector == "all" else ""}">All</a>'
    for key in ["l1", "l2", "defi", "meme", "ai", "gaming", "exchange", "stablecoin"]:
        label = (sectors or {}).get(key, key.title())
        sec_btns += f'<a href="/explore?sector={key}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'

    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        sec_qs = f"&sector={sector}" if sector != "all" else ""
        arrow = " &darr;" if sort_by == col and order == "desc" else " &uarr;" if sort_by == col else ""
        return f'<a href="/explore?sort={col}&order={new_order}{sec_qs}&page={page}" class="sort-link">{label}{arrow}</a>'

    rows = ""
    for i, t in enumerate(tokens):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        spark = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark, width=60, height=18) if spark and len(spark) >= 2 else ""
        rows += f'<tr><td class="col-rk">{start + i + 1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name", slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker", ""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r {pct_class(pct)}">{fmt_pct(pct)}</td><td class="hide-m">{spark_html}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td><td class="col-r hide-m">{fmt_usd(t.get("volume_usd"))}</td><td class="col-r hide-m">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td><td class="hide-m">{zone_html}</td></tr>'

    # Pagination
    pager = ""
    if total_pages > 1:
        sec_qs = f"&sector={sector}" if sector != "all" else ""
        sort_qs = f"&sort={sort_by}&order={order}"
        pages = []
        if page > 1:
            pages.append(f'<a href="/explore?page={page-1}{sec_qs}{sort_qs}">&laquo;</a>')
        for pg in range(max(1, page - 3), min(total_pages + 1, page + 4)):
            if pg == page:
                pages.append(f'<span class="cur">{pg}</span>')
            else:
                pages.append(f'<a href="/explore?page={pg}{sec_qs}{sort_qs}">{pg}</a>')
        if page < total_pages:
            pages.append(f'<a href="/explore?page={page+1}{sec_qs}{sort_qs}">&raquo;</a>')
        pager = f'<div class="pager">{"".join(pages)}</div>'

    search_qs = f"&q={_esc(search)}" if search else ""
    body = f"""
<h1 class="pg-t">Explore</h1>
<p class="pg-sub">{total} tokens{f' matching "{_esc(search)}"' if search else ''}</p>
<form class="search-bar" action="/explore" method="get">
<input type="text" name="q" value="{_esc(search)}" placeholder="Search tokens..." autocomplete="off">
<button type="submit">Search</button>
</form>
<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">{sort_link("price_usd", "Price")}</th><th class="col-r">{sort_link("price_usd_change", "24h")}</th><th class="hide-m">7d</th><th class="col-r hide-m">{sort_link("marketcap_usd", "MCap")}</th><th class="col-r hide-m">{sort_link("volume_usd", "Vol")}</th><th class="col-r hide-m">{sort_link("mvrv_usd", "MVRV")}</th><th class="hide-m">Zone</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="9" class="empty">No tokens found.</td></tr>'}</tbody>
</table></div>
{pager}
<a href="/explore/csv?sector={sector}{search_qs}" class="export-btn">Export CSV</a>"""

    return page_shell("Explore", body, active_nav="explore")


# ================================================================
# MARKET PAGE — Unified market view
# ================================================================

def _market_overview_table(tokens, start, sort_by, order, view, sector, tier, page):
    sec_qs = f"&sector={sector}" if sector != "all" else ""
    tier_qs = f"&tier={tier}" if tier != "all" else ""

    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        arrow = " &darr;" if sort_by == col and order == "desc" else " &uarr;" if sort_by == col else ""
        return f'<a href="/market?view={view}&sort={col}&order={new_order}{sec_qs}{tier_qs}&page={page}" class="sort-link">{label}{arrow}</a>'

    rows = ""
    for i, t in enumerate(tokens):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        spark = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark, width=60, height=18) if spark and len(spark) >= 2 else ""
        rows += f'<tr><td class="col-rk">{start + i + 1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name", slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker", ""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r {pct_class(pct)}">{fmt_pct(pct)}</td><td class="hide-m">{spark_html}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td><td class="col-r hide-m">{fmt_usd(t.get("volume_usd"))}</td><td class="col-r hide-m">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td><td class="hide-m">{zone_html}</td></tr>'

    return f'''<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">{sort_link("price_usd", "Price")}</th><th class="col-r">{sort_link("price_usd_change", "24h")}</th><th class="hide-m">7d</th><th class="col-r hide-m">{sort_link("marketcap_usd", "MCap")}</th><th class="col-r hide-m">{sort_link("volume_usd", "Vol")}</th><th class="col-r hide-m">{sort_link("mvrv_usd", "MVRV")}</th><th class="hide-m">Zone</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="9" class="empty">No tokens found.</td></tr>'}</tbody>
</table></div>'''


def _market_valuation_table(tokens, sector, zone_filter, view):
    rows = ""
    for i, t in enumerate(tokens[:200]):
        mvrv = t.get("mvrv_usd")
        if mvrv is None:
            continue
        slug = t.get("slug", "")
        zl, zc, _ = mvrv_zone(mvrv)
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name", slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r bold">{mvrv:.2f}</td><td><span class="zone {zc}">{zl}</span></td><td class="hide-m" style="min-width:80px"><div class="mini-bar"><div class="mini-bar-fill" style="width:{min(100, mvrv/4*100):.0f}%"></div></div></td></tr>'

    return f'''<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Price</th><th class="col-r">MVRV</th><th>Zone</th><th class="hide-m">Bar</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="6" class="empty">No MVRV data.</td></tr>'}</tbody>
</table></div>'''


def _market_developers_table(tokens):
    max_dev = max((t.get("dev_activity") or 0 for t in tokens), default=1) or 1
    rows = ""
    for i, t in enumerate(tokens[:100]):
        dev = t.get("dev_activity") or 0
        dev_ch = t.get("dev_activity_change")
        slug = t.get("slug", "")
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name",slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{dev:,.0f}</td><td class="col-r {pct_class(dev_ch)} hide-m">{fmt_pct(dev_ch)}</td><td class="hide-m" style="min-width:80px"><div class="mini-bar"><div class="mini-bar-fill" style="width:{min(100, dev/max_dev*100):.0f}%"></div></div></td><td class="col-r hide-m">{fmt_usd(t.get("price_usd"))}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td></tr>'

    return f'''<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Dev</th><th class="col-r hide-m">Change</th><th class="hide-m">Bar</th><th class="col-r hide-m">Price</th><th class="col-r hide-m">MCap</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="7">No data.</td></tr>'}</tbody>
</table></div>'''


def render_market_page(tokens: list, page: int = 1, per_page: int = 50,
                       total: int = 0, sector: str = "all",
                       sectors: dict = None, search: str = "",
                       sort_by: str = "marketcap_usd", order: str = "desc",
                       view: str = "overview",
                       tier: str = "all",
                       zone_filter: str = "all") -> str:
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page

    # View tabs
    views = [("overview", "Overview"), ("screener", "Screener"), ("valuation", "Valuation"), ("developers", "Developers")]
    sec_qs = f"&sector={sector}" if sector != "all" else ""
    view_tabs = "".join(
        f'<a href="/market?view={v}{sec_qs}" class="fbtn{" on" if v == view else ""}">{label}</a>'
        for v, label in views
    )

    # Sector filter
    sec_btns = f'<a href="/market?view={view}" class="fbtn{" on" if sector == "all" else ""}">All</a>'
    for key in ["l1", "l2", "defi", "meme", "ai", "gaming", "exchange", "stablecoin"]:
        label = (sectors or {}).get(key, key.title())
        sec_btns += f'<a href="/market?view={view}&sector={key}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'

    # Search bar
    search_html = f'''<form class="search-bar" action="/market" method="get">
<input type="text" name="q" value="{_esc(search)}" placeholder="Search tokens..." autocomplete="off">
<button type="submit">Search</button>
<input type="hidden" name="view" value="{_esc(view)}">
</form>'''

    # Build view-specific content
    if view == "valuation":
        table_html = _market_valuation_table(tokens, sector, zone_filter, view)
    elif view == "developers":
        table_html = _market_developers_table(tokens)
    else:
        table_html = _market_overview_table(tokens, start, sort_by, order, view, sector, tier, page)

    # Tier filter (screener only)
    tier_html = ""
    if view == "screener":
        tiers = [("all", "All"), ("mega", ">$100B"), ("large", "$10B+"), ("mid", "$1B+"), ("small", "$100M+"), ("micro", "<$100M")]
        tier_btns = "".join(f'<a href="/market?view=screener&tier={key}{sec_qs}" class="fbtn{" on" if key == tier else ""}">{label}</a>' for key, label in tiers)
        tier_html = f'<div class="fbar"><span class="fbar-l">Tier:</span>{tier_btns}</div>'
        # Quick filters
        tier_html += '''<div class="fbar"><span class="fbar-l">Quick:</span>
<a href="/market?view=screener&sort=mvrv_usd&order=asc" class="fbtn">Undervalued</a>
<a href="/market?view=screener&sort=price_usd_change&order=desc" class="fbtn">Gainers</a>
<a href="/market?view=screener&sort=price_usd_change&order=asc" class="fbtn">Losers</a>
<a href="/market?view=screener&sort=dev_activity&order=desc" class="fbtn">Active Dev</a>
</div>'''

    # Zone filter (valuation only)
    zone_html = ""
    if view == "valuation":
        zone_defs = [("Deep Value", "deep_value"), ("Undervalued", "undervalued"), ("Fair Value", "fair"),
                     ("Elevated", "elevated"), ("Overvalued", "overvalued"), ("Euphoria", "euphoria")]
        zone_btns = f'<a href="/market?view=valuation{sec_qs}" class="fbtn{" on" if zone_filter == "all" else ""}">All</a>'
        zone_counts = {}
        for t in tokens:
            mvrv = t.get("mvrv_usd")
            if mvrv is not None:
                z = mvrv_zone(mvrv)
                zone_counts[z[0]] = zone_counts.get(z[0], 0) + 1
        for label, key in zone_defs:
            zone_btns += f'<a href="/market?view=valuation&zone={key}{sec_qs}" class="fbtn{" on" if zone_filter == key else ""}">{label} ({zone_counts.get(label, 0)})</a>'
        zone_html = f'<div class="fbar"><span class="fbar-l">Zone:</span>{zone_btns}</div>'

    # Pagination
    pager = ""
    if view in ("overview", "screener") and total_pages > 1:
        sort_qs = f"&sort={sort_by}&order={order}"
        tier_qs = f"&tier={tier}" if tier != "all" else ""
        pages = []
        if page > 1:
            pages.append(f'<a href="/market?view={view}&page={page-1}{sec_qs}{sort_qs}{tier_qs}">&laquo;</a>')
        for pg in range(max(1, page - 3), min(total_pages + 1, page + 4)):
            if pg == page:
                pages.append(f'<span class="cur">{pg}</span>')
            else:
                pages.append(f'<a href="/market?view={view}&page={pg}{sec_qs}{sort_qs}{tier_qs}">{pg}</a>')
        if page < total_pages:
            pages.append(f'<a href="/market?view={view}&page={page+1}{sec_qs}{sort_qs}{tier_qs}">&raquo;</a>')
        pager = f'<div class="pager">{"".join(pages)}</div>'

    body = f'''
<div class="pg-t-row"><div><h1 class="pg-t">Market</h1><p class="pg-sub">{total} tokens{f' matching "{_esc(search)}"' if search else ''}</p></div>
<a href="/market/csv?view={view}&sector={_esc(sector)}&sort={_esc(sort_by)}&order={_esc(order)}" class="export-btn">Export CSV</a></div>
{search_html}
<div class="fbar"><span class="fbar-l">View:</span>{view_tabs}</div>
<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>
{tier_html}
{zone_html}
{table_html}
{pager}'''

    return page_shell("Market", body, active_nav="market")


# ================================================================
# INSIGHTS PAGE
# ================================================================

def render_insights_page(insights: dict, view_id: str = "mvrv_nvt",
                         scatter_views: list = None, sector: str = "all",
                         sectors: dict = None, sort_by: str = "marketcap") -> str:
    if not insights or not insights.get("points"):
        return page_shell("Insights", '<div class="empty"><h2>Loading insights...</h2></div>', active_nav="insights")

    p = []
    p.append(f'<h1 class="pg-t">On-Chain Insights</h1>')
    p.append(f'<p class="pg-sub">{len(insights.get("points", []))} tokens plotted</p>')

    # View selector
    if scatter_views:
        btns = ""
        for vid, vtitle, *_ in scatter_views:
            short = vtitle.split(":")[0] if ":" in vtitle else vtitle
            sec_qs = f"&sector={sector}" if sector != "all" else ""
            btns += f'<a href="/insights?view={vid}{sec_qs}" class="fbtn{" on" if vid == view_id else ""}">{_esc(short)}</a>'
        p.append(f'<div class="fbar"><span class="fbar-l">View:</span>{btns}</div>')

    # Sector filter
    if sectors:
        sec_btns = f'<a href="/insights?view={view_id}" class="fbtn{" on" if sector == "all" else ""}">All</a>'
        for key in ["l1", "l2", "defi", "meme", "ai", "gaming"]:
            label = sectors.get(key, key.title())
            sec_btns += f'<a href="/insights?view={view_id}&sector={key}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'
        p.append(f'<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>')

    # Scatter chart
    current_view = None
    if scatter_views:
        for v in scatter_views:
            if v[0] == view_id:
                current_view = v
                break
        if not current_view:
            current_view = scatter_views[0]

    if current_view:
        _, chart_title, x_metric, y_metric, x_label, y_label, log_x, log_y = current_view
        chart_svg = scatter_plot_svg(
            insights["points"], width=600, height=380,
            title=chart_title, x_key="x", y_key="y",
            x_label=x_label, y_label=y_label,
            color_key="thesis", size_key="marketcap_usd",
            log_x=log_x, log_y=log_y,
        )
        legend = ""
        tc = insights.get("thesis_counts", {})
        for key in ["smart_money", "builder_momentum", "deep_value", "distribution_warning", "hodler", "high_utility", "speculative"]:
            cnt = tc.get(key, 0)
            if cnt == 0:
                continue
            color = THESIS_COLORS.get(key, "#9CA3AF")
            label = THESIS_LABELS.get(key, key)
            legend += f'<span style="margin-right:10px"><span class="sig-dot" style="background:{color}"></span>{_esc(label)} ({cnt})</span>'
        # Interpretation guide per view
        INSIGHT_GUIDES = {
            "mvrv_nvt": "Bottom-left = undervalued + high usage (best risk/reward). Top-right = overvalued + low usage (avoid). Green dots = Smart Money accumulation.",
            "daa_mcap": "Above diagonal = overvalued for usage level. Below = value opportunity if usage trending up.",
            "exch_price": "Bottom-right quadrant (price up, exchange down) = smart money buying. Build positions over 5\u20137 days.",
            "dev_growth": "Top-right = strong builders with growing network. Favor for 3\u20136 month holds.",
            "vol_mcap": "High vol/mcap + low DAA = speculation. Low vol/mcap + high DAA = genuine utility.",
        }
        guide = INSIGHT_GUIDES.get(view_id, "")
        guide_html = f'<div class="narrative" style="font-size:.75rem;margin-top:6px">{_esc(guide)}</div>' if guide else ""
        p.append(f'<div class="card"><div class="card-hd"><span class="card-t">{_esc(chart_title)}</span></div><div class="chart-w">{chart_svg}</div><div style="font-size:.72rem;color:var(--tx2);margin-top:4px">{legend}</div>{guide_html}</div>')

    # Thesis categories
    thesis_tokens = insights.get("thesis_tokens", {})
    thesis_counts = insights.get("thesis_counts", {})
    if thesis_counts:
        for key in ["smart_money", "builder_momentum", "deep_value", "distribution_warning", "hodler", "high_utility", "speculative"]:
            cnt = thesis_counts.get(key, 0)
            if cnt == 0:
                continue
            color = THESIS_COLORS.get(key, "#9CA3AF")
            label = THESIS_LABELS.get(key, key)
            desc = THESIS_DESCRIPTIONS.get(key, "")
            tokens_list = thesis_tokens.get(key, [])
            chips = "".join(
                f'<a href="/token/{t.get("slug","")}" class="mover-chip"><span>{_esc(t.get("ticker","")[:6])}</span><span class="{pct_class(t.get("price_usd_change"))}">{fmt_pct(t.get("price_usd_change"))}</span></a>'
                for t in tokens_list[:6]
            )
            p.append(f'<div class="card" style="border-left:3px solid {color}"><div class="card-hd"><span class="card-t">{_esc(label)}</span><span class="card-badge">{cnt}</span></div><p style="font-size:.75rem;color:var(--tx2);margin-bottom:6px">{_esc(desc)}</p><div>{chips}</div></div>')

    sec_qs = f"&sector={sector}" if sector != "all" else ""
    p.append(f'<a href="/insights/export.csv?view={view_id}{sec_qs}" class="export-btn">Export CSV</a>')

    return page_shell("Insights", "\n".join(p), active_nav="insights")


# ================================================================
# VALUATION PAGE
# ================================================================

def render_valuation_page(tokens: list, sector: str = "all", sectors: dict = None, zone_filter: str = "all") -> str:
    zone_counts = {}
    for t in tokens:
        mvrv = t.get("mvrv_usd")
        if mvrv is not None:
            z = mvrv_zone(mvrv)
            zone_counts[z[0]] = zone_counts.get(z[0], 0) + 1

    # Zone filter
    zone_defs = [("Deep Value", "deep_value"), ("Undervalued", "undervalued"), ("Fair Value", "fair"),
                 ("Elevated", "elevated"), ("Overvalued", "overvalued"), ("Euphoria", "euphoria")]
    sec_qs = f"&sector={sector}" if sector != "all" else ""
    zone_btns = f'<a href="/valuation?{sec_qs[1:]}" class="fbtn{" on" if zone_filter == "all" else ""}">All</a>'
    for label, key in zone_defs:
        zone_btns += f'<a href="/valuation?zone={key}{sec_qs}" class="fbtn{" on" if zone_filter == key else ""}">{label} ({zone_counts.get(label, 0)})</a>'

    # Sector filter
    sec_filter = ""
    if sectors:
        sec_btns = f'<a href="/valuation" class="fbtn{" on" if sector == "all" else ""}">All</a>'
        for key, label in sorted(sectors.items(), key=lambda x: x[1]):
            sec_btns += f'<a href="/valuation?sector={key}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'
        sec_filter = f'<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>'

    rows = ""
    for i, t in enumerate(tokens[:200]):
        mvrv = t.get("mvrv_usd")
        if mvrv is None:
            continue
        slug = t.get("slug", "")
        zl, zc, _ = mvrv_zone(mvrv)
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name", slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r bold">{mvrv:.2f}</td><td><span class="zone {zc}">{zl}</span></td><td class="hide-m" style="min-width:80px"><div class="mini-bar"><div class="mini-bar-fill" style="width:{min(100, mvrv/4*100):.0f}%"></div></div></td></tr>'

    body = f"""
<h1 class="pg-t">Valuation Scanner</h1>
<p class="pg-sub">MVRV zones across {len(tokens)} tokens</p>
{sec_filter}
<div class="fbar"><span class="fbar-l">Zone:</span>{zone_btns}</div>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Price</th><th class="col-r">MVRV</th><th>Zone</th><th class="hide-m">Bar</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="6" class="empty">No MVRV data.</td></tr>'}</tbody>
</table></div>
<a href="/valuation/export.csv?sector={sector}&zone={zone_filter}" class="export-btn">Export CSV</a>"""

    return page_shell("Valuation", body, active_nav="valuation")


# ================================================================
# SCREENER PAGE
# ================================================================

def render_screener_page(tokens: list, tier: str = "all",
                         min_change: float = None, max_change: float = None,
                         sort_by: str = "marketcap_usd", order: str = "desc",
                         sector: str = "all", category: str = "all",
                         sectors: dict = None, categories: dict = None,
                         search: str = "", min_mvrv: float = -999, max_mvrv: float = 999) -> str:

    def _qs(**overrides):
        params = {"tier": tier, "sort": sort_by, "order": order, "sector": sector}
        if min_mvrv > -999:
            params["min_mvrv"] = min_mvrv
        if max_mvrv < 999:
            params["max_mvrv"] = max_mvrv
        params.update(overrides)
        return "&".join(f"{k}={v}" for k, v in params.items() if v not in ("all", None, -999, 999) or k == "tier")

    tiers = [("all", "All"), ("mega", ">$100B"), ("large", "$10B+"), ("mid", "$1B+"), ("small", "$100M+"), ("micro", "<$100M")]
    tier_btns = "".join(f'<a href="/screener?{_qs(tier=key)}" class="fbtn{" on" if key == tier else ""}">{label}</a>' for key, label in tiers)

    sec_btns = f'<a href="/screener?{_qs(sector="all")}" class="fbtn{" on" if sector == "all" else ""}">All</a>'
    for key in ["l1", "l2", "defi", "meme", "ai", "gaming", "exchange", "stablecoin"]:
        label = (sectors or {}).get(key, key.title())
        sec_btns += f'<a href="/screener?{_qs(sector=key)}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'

    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        arrow = " &darr;" if sort_by == col and order == "desc" else " &uarr;" if sort_by == col else ""
        return f'<a href="/screener?{_qs(sort=col, order=new_order)}" class="sort-link">{label}{arrow}</a>'

    displayed = tokens[:200]
    rows = ""
    for i, t in enumerate(displayed):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        spark = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark, width=60, height=18) if spark and len(spark) >= 2 else ""
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name", slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r {pct_class(pct)}">{fmt_pct(pct)}</td><td class="hide-m">{spark_html}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td><td class="col-r hide-m">{fmt_usd(t.get("volume_usd"))}</td><td class="col-r hide-m">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td><td class="hide-m">{zone_html}</td></tr>'

    body = f"""
<div class="pg-t-row"><div><h1 class="pg-t">Screener</h1><p class="pg-sub">{len(tokens)} tokens{f' matching "{_esc(search)}"' if search else ''}</p></div>
<a href="/screener/export.csv?tier={_esc(tier)}&sort={_esc(sort_by)}&sector={_esc(sector)}" class="export-btn">Export CSV</a></div>
<form class="search-bar" action="/screener" method="get">
<input type="text" name="q" value="{_esc(search)}" placeholder="Search..." autocomplete="off">
<button type="submit">Search</button>
<input type="hidden" name="tier" value="{_esc(tier)}"><input type="hidden" name="sort" value="{_esc(sort_by)}">
</form>
<div class="fbar"><span class="fbar-l">Tier:</span>{tier_btns}</div>
<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>
<div class="fbar"><span class="fbar-l">Quick:</span>
<a href="/screener?sort=mvrv_usd&order=asc" class="fbtn">Undervalued</a>
<a href="/screener?sort=price_usd_change&order=desc" class="fbtn">Gainers</a>
<a href="/screener?sort=price_usd_change&order=asc" class="fbtn">Losers</a>
<a href="/screener?sort=dev_activity&order=desc" class="fbtn">Active Dev</a>
</div>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">{sort_link("price_usd", "Price")}</th><th class="col-r">{sort_link("price_usd_change", "24h")}</th><th class="hide-m">7d</th><th class="col-r hide-m">{sort_link("marketcap_usd", "MCap")}</th><th class="col-r hide-m">{sort_link("volume_usd", "Vol")}</th><th class="col-r hide-m">{sort_link("mvrv_usd", "MVRV")}</th><th class="hide-m">Zone</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="9">No matches.</td></tr>'}</tbody>
</table></div>"""

    return page_shell("Screener", body, active_nav="screener")


# ================================================================
# TOKEN PROFILE
# ================================================================

def _derived_metrics_panel(derived: dict) -> str:
    if not derived:
        return ""

    def _score_style(key, val):
        """Color-code composite scores: green=good, red=bad."""
        if key in ("momentum_score", "value_score", "health_score"):
            if val >= 65: return ' style="color:var(--green)"'
            if val <= 35: return ' style="color:var(--red)"'
        elif key == "risk_score":
            if val >= 65: return ' style="color:var(--red)"'
            if val <= 35: return ' style="color:var(--green)"'
        elif key == "rsi":
            if val >= 70: return ' style="color:var(--red)"'
            if val <= 30: return ' style="color:var(--green)"'
        elif key == "mvrv_zscore":
            if val >= 2: return ' style="color:var(--red)"'
            if val <= -1: return ' style="color:var(--green)"'
        elif key == "sharpe_ratio":
            if val >= 1: return ' style="color:var(--green)"'
            if val <= 0: return ' style="color:var(--red)"'
        return ""

    items = []
    metric_labels = [
        ("momentum_score", "Momentum", "/100"), ("value_score", "Value", "/100"),
        ("risk_score", "Risk", "/100"), ("health_score", "Health", "/100"),
        ("rsi", "RSI (14d)", ""), ("mvrv_zscore", "MVRV Z-Score", ""),
        ("sharpe_ratio", "Sharpe Ratio", ""), ("volatility", "Volatility", "%"),
        ("max_drawdown", "Max Drawdown", "%"), ("beta_vs_btc", "Beta vs BTC", ""),
        ("nvt_signal", "NVT Signal", ""), ("net_exchange_flow_7d", "Net Exch Flow 7d", ""),
    ]
    for key, label, suffix in metric_labels:
        val = derived.get(key)
        if val is None:
            continue
        style = _score_style(key, val) if isinstance(val, (int, float)) else ""
        if isinstance(val, float):
            display = f"{val:.2f}{suffix}"
        else:
            display = f"{val}{suffix}"
        items.append(f'<div class="derived-item"><div class="derived-label">{label}</div><div class="derived-val"{style}>{display}</div></div>')
    if not items:
        return ""

    # Build one-line thesis summary from composite scores
    summary_parts = []
    mom = derived.get("momentum_score")
    val = derived.get("value_score")
    risk = derived.get("risk_score")
    health = derived.get("health_score")
    if mom is not None:
        summary_parts.append("strong momentum" if mom >= 65 else "weak momentum" if mom <= 35 else "neutral momentum")
    if val is not None:
        summary_parts.append("undervalued" if val >= 65 else "overvalued" if val <= 35 else "fair value")
    if risk is not None:
        summary_parts.append("high risk" if risk >= 65 else "low risk" if risk <= 35 else "moderate risk")
    if health is not None:
        summary_parts.append("strong fundamentals" if health >= 65 else "weak fundamentals" if health <= 35 else "mixed fundamentals")
    summary = ", ".join(summary_parts).capitalize() + "." if summary_parts else ""
    summary_html = f'<div style="font-size:.75rem;color:var(--tx2);margin-top:6px;border-top:1px solid var(--border);padding-top:6px">{summary}</div>' if summary else ""

    return f'<div class="card"><div class="card-hd"><span class="card-t">Derived Metrics</span></div><div class="derived">{"".join(items)}</div>{summary_html}</div>'


def render_token_profile(token: dict, metrics: dict, slug: str = "",
                         timeframe: str = "all", token_info: dict = None,
                         related_tokens: list = None, prev_token: dict = None,
                         next_token: dict = None, mcap_rank: int = None,
                         all_tokens: list = None) -> str:
    slug = slug or token.get("slug", "")
    name = _esc(token.get("name", slug))
    ticker = _esc(token.get("ticker", ""))

    def _m(key):
        return metrics.get(key) or {}

    def _latest(key):
        m = _m(key)
        return m.get("latest") if isinstance(m, dict) else None

    def _data(key):
        m = _m(key)
        return m.get("data") or [] if isinstance(m, dict) else []

    price = _latest("price_usd")
    mvrv = _latest("mvrv_usd")

    # Change badges
    changes = ""
    price_ts = _data("price_usd")
    if price_ts and len(price_ts) >= 2:
        curr = price_ts[-1].get("value")
        for label, days in [("24h", 1), ("7d", 7), ("30d", 30)]:
            if len(price_ts) > days and curr:
                prev_val = price_ts[-1 - days].get("value")
                if prev_val and prev_val != 0:
                    v = (curr - prev_val) / prev_val * 100
                    cls = "up" if v > 0 else "dn"
                    changes += f'<span class="pill {cls}">{label} {fmt_pct(v)}</span>'

    # Nav prev/next
    nav_html = ""
    if prev_token:
        nav_html += f'<a href="/token/{prev_token["slug"]}" style="font-size:.75rem">&laquo; {_esc(prev_token.get("name","")[:15])}</a> '
    if next_token:
        nav_html += f'<a href="/token/{next_token["slug"]}" style="font-size:.75rem">{_esc(next_token.get("name","")[:15])} &raquo;</a>'

    zone_html = ""
    if mvrv is not None:
        zl, zc, zd = mvrv_zone(mvrv)
        zone_html = f'<span class="zone {zc}">{zl}</span>'

    rank_html = f'<span class="card-badge">#{mcap_rank}</span>' if mcap_rank else ""

    p = [f"""
<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:4px">
<div>{nav_html}</div></div>
<h1 class="pg-t">{name} <span style="color:var(--tx3)">{ticker}</span> {rank_html}</h1>
<div style="margin-bottom:10px">
<span style="font-size:1.4rem;font-weight:800">{fmt_usd(price)}</span> {changes} {zone_html}
</div>"""]

    # Timeframe selector
    tf_btns = ""
    for tf_key, tf_label in [("7d", "7D"), ("30d", "30D"), ("90d", "90D"), ("1y", "1Y"), ("all", "All")]:
        tf_btns += f'<a href="/token/{slug}?tf={tf_key}" class="fbtn{" on" if timeframe == tf_key else ""}">{tf_label}</a>'
    p.append(f'<div class="fbar"><span class="fbar-l">Period:</span>{tf_btns}</div>')

    # Key metrics
    p.append(f"""<div class="stats">
<div class="stat"><div class="stat-l">Market Cap</div><div class="stat-v">{fmt_usd(_latest("marketcap_usd"))}</div></div>
<div class="stat"><div class="stat-l">Volume 24h</div><div class="stat-v">{fmt_usd(_latest("volume_usd"))}</div></div>
<div class="stat"><div class="stat-l">MVRV</div><div class="stat-v">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</div></div>
<div class="stat"><div class="stat-l">NVT</div><div class="stat-v">{f"{_latest('nvt'):.1f}" if _latest("nvt") else "&mdash;"}</div></div>
<div class="stat"><div class="stat-l">Active Addr</div><div class="stat-v">{fmt_num(_latest("daily_active_addresses"))}</div></div>
<div class="stat"><div class="stat-l">Dev Activity</div><div class="stat-v">{f"{_latest('dev_activity'):.0f}" if _latest("dev_activity") else "&mdash;"}</div></div>
</div>""")

    # Price chart
    price_data = _data("price_usd")
    if price_data and len(price_data) >= 5:
        from .svg_charts import COLORS
        chart = line_chart_svg(
            [{"label": f"{name} Price", "data": price_data, "color": COLORS[0]}],
            width=600, height=250, title="Price", metric_key="price_usd",
            show_area=True, show_min_max=True,
        )
        p.append(f'<div class="card"><div class="chart-w">{chart}</div></div>')

    # Secondary charts — 2-column grid
    chart_defs = [
        ("mvrv_usd", "MVRV Ratio", "#c92a2a"),
        ("daily_active_addresses", "Active Addresses", "#0c8599"),
        ("volume_usd", "Volume", "#e67700"),
        ("dev_activity", "Dev Activity", "#7048e8"),
        ("exchange_balance", "Exchange Balance", "#d9480f"),
        ("network_growth", "Network Growth", "#2b8a3e"),
    ]
    secondary_charts = []
    for metric_key, title, color in chart_defs:
        data = _data(metric_key)
        if data and len(data) >= 5:
            chart = line_chart_svg(
                [{"label": title, "data": data, "color": color}],
                width=600, height=180, title=title, metric_key=metric_key,
                show_area=False, show_min_max=False,
            )
            secondary_charts.append(f'<div class="card"><div class="chart-w">{chart}</div></div>')
    if secondary_charts:
        p.append(f'<div class="grid-2">{"".join(secondary_charts)}</div>')

    # Derived metrics
    derived = metrics.get("_derived", {})
    p.append(_derived_metrics_panel(derived))

    # Signal summary
    alerts = []
    if mvrv is not None:
        if mvrv < 0.7:
            alerts.append(("Deep Value Zone", "alert-bullish"))
        elif mvrv > 3.5:
            alerts.append(("Euphoria Zone", "alert-bearish"))
        elif mvrv > 2.5:
            alerts.append(("Overvalued", "alert-warn"))
    nvt = _latest("nvt")
    if nvt is not None:
        if nvt > 150:
            alerts.append(("High NVT", "alert-warn"))
        elif nvt < 20:
            alerts.append(("Low NVT", "alert-bullish"))
    if alerts:
        badges = " ".join(f'<span class="alert-badge {cls}">{_esc(label)}</span>' for label, cls in alerts)
        p.append(f'<div style="margin:8px 0">{badges}</div>')

    # Related tokens
    if related_tokens:
        chips = "".join(
            f'<a href="/token/{rt.get("slug","")}" class="mover-chip"><span>{_esc(rt.get("ticker","")[:6])}</span><span class="{pct_class(rt.get("price_usd_change"))}">{fmt_pct(rt.get("price_usd_change"))}</span></a>'
            for rt in related_tokens[:6]
        )
        sec_label = token_info.get("sector", "") if token_info else ""
        p.append(f'<div class="card"><div class="card-hd"><span class="card-t">Related ({_esc(sec_label)})</span></div>{chips}</div>')

    return page_shell(f"{name} ({ticker})", "\n".join(p), og_description=f"{name} on-chain analytics", canonical=f"/token/{slug}")


# ================================================================
# COMPARE PAGE
# ================================================================

def render_compare_page(tokens: list) -> str:
    if not tokens:
        body = """<h1 class="pg-t">Compare</h1><p class="pg-sub">Side-by-side comparison</p>
<div class="empty"><h2>Select tokens</h2><p>Add slugs to URL: /compare?tokens=bitcoin,ethereum</p>
<div class="chip-bar" style="margin-top:8px;justify-content:center"><a href="/compare?tokens=bitcoin,ethereum" class="chip">BTC vs ETH</a><a href="/compare?tokens=bitcoin,ethereum,solana,cardano" class="chip">L1 Chains</a><a href="/compare?tokens=aave,uniswap,maker" class="chip">DeFi</a></div></div>"""
        return page_shell("Compare", body, active_nav="compare")

    presets = [("BTC vs ETH", "bitcoin,ethereum"), ("L1s", "bitcoin,ethereum,solana,cardano,avalanche"),
               ("DeFi", "aave,uniswap,maker,compound"), ("Memes", "dogecoin,shiba-inu,pepe,bonk")]
    chips = "".join(f'<a href="/compare?tokens={slugs}" class="chip">{label}</a>' for label, slugs in presets)

    metric_keys = [("price_usd", "Price"), ("marketcap_usd", "MCap"), ("volume_usd", "Vol 24h"),
                   ("mvrv_usd", "MVRV"), ("nvt", "NVT"), ("daily_active_addresses", "DAA"),
                   ("dev_activity", "Dev"), ("exchange_balance", "Exch Bal")]
    comp_table = comparison_table(tokens, metric_keys)

    from .svg_charts import COLORS
    charts = ""
    for metric_key, title, show_area in [("price_usd", "Price", True), ("mvrv_usd", "MVRV", False), ("daily_active_addresses", "DAA", False)]:
        series = []
        for i, t in enumerate(tokens):
            data = t.get("metrics", {}).get(metric_key, {}).get("data", [])
            if data:
                series.append({"label": t.get("name", t.get("slug", "")), "data": data, "color": COLORS[i % len(COLORS)]})
        if series:
            svg = line_chart_svg(series, width=600, height=220, title=title, metric_key=metric_key,
                                 show_area=show_area and len(series) == 1, show_min_max=False)
            charts += f'<div class="card"><div class="chart-w">{svg}</div></div>'

    slug_list = ",".join(t.get("slug", "") for t in tokens)

    body = f"""
<h1 class="pg-t">Compare</h1>
<div class="chip-bar">{chips}</div>
<div class="tbl-w">{comp_table}</div>
{charts}
<a href="/compare/export.csv?tokens={_esc(slug_list)}" class="export-btn">Export CSV</a>"""

    return page_shell("Compare", body, active_nav="compare")


# ================================================================
# SYNC PAGE
# ================================================================

def render_sync_page(pull_status: dict, cache_stats: dict, client_stats: dict) -> str:
    status = pull_status.get("status", "unknown")
    cs = cache_stats or {}
    cl = client_stats or {}

    phases = [("Discovery", "phase1_discovery"), ("Quick Load", "phase1_pulling"),
              ("Universe", "phase2_universe"), ("Deep Pull", "phase3_deep"), ("Ready", "ready")]
    current_idx = -1
    for i, (_, key) in enumerate(phases):
        if key in status:
            current_idx = i
    if status == "ready":
        current_idx = len(phases) - 1

    progress = 100 if status == "ready" else (int(current_idx / max(len(phases) - 1, 1) * 100) if current_idx >= 0 else 0)

    steps = ""
    for i, (label, _) in enumerate(phases):
        cls = "done" if (status == "ready" or i < current_idx) else ("active" if i == current_idx else "")
        steps += f'<span class="sync-step {cls}">{label}</span>'

    body = f"""
<h1 class="pg-t">Data Sync</h1>
<div class="sync-steps">{steps}</div>
<div class="sync-bar"><div class="sync-bar-fill{" done" if progress == 100 else ""}" style="width:{progress}%"></div></div>
<div style="text-align:center;font-size:.78rem;margin:4px 0">{progress}%</div>
<div class="stats">
<div class="stat"><div class="stat-l">Projects</div><div class="stat-v">{fmt_num(cs.get("projects_cached", 0))}</div></div>
<div class="stat"><div class="stat-l">Data Points</div><div class="stat-v">{fmt_num(cs.get("total_data_points_pulled", 0))}</div></div>
<div class="stat"><div class="stat-l">Timeseries</div><div class="stat-v">{fmt_num(cs.get("timeseries_rows", 0))}</div></div>
<div class="stat"><div class="stat-l">DB Size</div><div class="stat-v">{cs.get("db_size_mb", 0):.0f} MB</div></div>
<div class="stat"><div class="stat-l">API Requests</div><div class="stat-v">{fmt_num(cl.get("total_requests", 0))}</div></div>
<div class="stat"><div class="stat-l">Errors</div><div class="stat-v">{cl.get("errors", 0)}</div></div>
</div>"""

    # Errors
    for k in ("error", "phase1_error", "phase2_error", "phase3_error"):
        v = pull_status.get(k)
        if v:
            body += f'<div class="narrative" style="border-color:var(--dn)">{_esc(str(v)[:300])}</div>'

    if status not in ("phase1_discovery", "phase1_pulling", "phase2_universe", "phase3_deep"):
        body += '<div style="margin-top:8px"><a href="/api/retry-pull" class="export-btn">Retry Pull</a></div>'

    return page_shell("Sync", body, active_nav="sync", auto_refresh=30)


# ================================================================
# DEVELOPERS PAGE
# ================================================================

def render_developers_page(tokens: list, sector: str = "all", sectors: dict = None) -> str:
    if sectors:
        sec_btns = f'<a href="/developers" class="fbtn{" on" if sector == "all" else ""}">All</a>'
        for key, label in sorted(sectors.items(), key=lambda x: x[1]):
            sec_btns += f'<a href="/developers?sector={key}" class="fbtn{" on" if key == sector else ""}">{_esc(label)}</a>'
        sec_filter = f'<div class="fbar"><span class="fbar-l">Sector:</span>{sec_btns}</div>'
    else:
        sec_filter = ""

    rows = ""
    max_dev = max((t.get("dev_activity") or 0 for t in tokens), default=1) or 1
    for i, t in enumerate(tokens[:100]):
        dev = t.get("dev_activity") or 0
        dev_ch = t.get("dev_activity_change")
        slug = t.get("slug", "")
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name",slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{dev:,.0f}</td><td class="col-r {pct_class(dev_ch)} hide-m">{fmt_pct(dev_ch)}</td><td class="hide-m" style="min-width:80px"><div class="mini-bar"><div class="mini-bar-fill" style="width:{min(100, dev/max_dev*100):.0f}%"></div></div></td><td class="col-r hide-m">{fmt_usd(t.get("price_usd"))}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td></tr>'

    body = f"""
<h1 class="pg-t">Developer Activity</h1>
<p class="pg-sub">Top {len(tokens)} projects by dev activity</p>
{sec_filter}
<a href="/developers/export.csv?sector={sector}" class="export-btn">Export CSV</a>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Dev</th><th class="col-r hide-m">Change</th><th class="hide-m">Bar</th><th class="col-r hide-m">Price</th><th class="col-r hide-m">MCap</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="7">No data.</td></tr>'}</tbody>
</table></div>"""

    return page_shell("Developers", body, active_nav="developers")


# ================================================================
# SECTORS PAGE
# ================================================================

def render_sectors_page(sector_details: dict, sector_labels: dict) -> str:
    total_mcap = sum(d["mcap"] for d in sector_details.values())
    sorted_secs = sorted(sector_details.items(), key=lambda x: x[1]["mcap"], reverse=True)

    rows = ""
    for rank, (sec_key, data) in enumerate(sorted_secs, 1):
        label = sector_labels.get(sec_key, sec_key.replace("_", " ").title())
        avg_ch = data.get("avg_change", 0)
        pct = (data["mcap"] / total_mcap * 100) if total_mcap > 0 else 0
        best = data["top_tokens"][0] if data.get("top_tokens") else None
        best_html = f'<a href="/token/{best["slug"]}">{_esc(best.get("ticker",""))}</a>' if best else "&mdash;"
        rows += f'<tr><td class="col-rk">{rank}</td><td><a href="/sector/{sec_key}" class="sec-tag">{_esc(label)}</a></td><td class="col-r">{data.get("count",0)}</td><td class="col-r bold">{fmt_usd(data["mcap"])}</td><td class="col-r">{pct:.1f}%</td><td class="col-r {pct_class(avg_ch)}">{fmt_pct(avg_ch)}</td><td class="col-r">{best_html}</td></tr>'

    body = f"""
<h1 class="pg-t">Sectors</h1>
<p class="pg-sub">Performance by sector</p>
<a href="/sectors/export.csv" class="export-btn">Export CSV</a>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Sector</th><th class="col-r">Tokens</th><th class="col-r">MCap</th><th class="col-r">%</th><th class="col-r">Avg 24h</th><th class="col-r">Top</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>"""

    return page_shell("Sectors", body, active_nav="sectors")


# ================================================================
# SECTOR DETAIL PAGE
# ================================================================

def render_sector_detail_page(tokens: list, sector_key: str, sector_label: str, sectors: dict = None) -> str:
    total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
    pcts = [t.get("price_usd_change") for t in tokens if t.get("price_usd_change") is not None]
    avg_change = sum(pcts) / len(pcts) if pcts else 0

    rows = ""
    for i, t in enumerate(tokens[:100]):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug}"><strong>{_esc(t.get("name",slug)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r {pct_class(pct)}">{fmt_pct(pct)}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td><td class="col-r hide-m">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td><td class="hide-m">{zone_html}</td></tr>'

    body = f"""
<h1 class="pg-t"><span class="sec-tag">{_esc(sector_label)}</span> Sector</h1>
<p class="pg-sub">{len(tokens)} tokens</p>
<div class="stats">
<div class="stat"><div class="stat-l">MCap</div><div class="stat-v">{fmt_usd(total_mcap)}</div></div>
<div class="stat"><div class="stat-l">Avg 24h</div><div class="stat-v {pct_class(avg_change)}">{fmt_pct(avg_change)}</div></div>
<div class="stat"><div class="stat-l">Tokens</div><div class="stat-v">{len(tokens)}</div></div>
</div>
<div class="chip-bar"><a href="/compare?tokens={','.join(t['slug'] for t in tokens[:5])}" class="chip">Compare Top 5</a><a href="/screener?sector={sector_key}" class="chip">Screener</a><a href="/valuation?sector={sector_key}" class="chip">Valuation</a></div>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Price</th><th class="col-r">24h</th><th class="col-r hide-m">MCap</th><th class="col-r hide-m">MVRV</th><th class="hide-m">Zone</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>"""

    return page_shell(f"{sector_label} Sector", body, active_nav="sectors")


# ================================================================
# WATCHLIST PAGE
# ================================================================

def render_watchlist_page(tokens: list, slug_list: list = None) -> str:
    slug_list = slug_list or []
    slugs_str = ",".join(slug_list)

    presets = [("Top 10", "bitcoin,ethereum,tether,xrp,binance-coin,solana,cardano,dogecoin,tron,avalanche"),
               ("DeFi", "aave,uniswap,maker,compound,curve-dao-token,lido-dao"),
               ("L1s", "bitcoin,ethereum,solana,cardano,avalanche,near-protocol,sui"),
               ("Memes", "dogecoin,shiba-inu,pepe,bonk,floki")]
    chips = "".join(f'<a href="/watchlist?tokens={slugs}" class="chip">{label}</a>' for label, slugs in presets)

    if not tokens:
        body = f"""
<h1 class="pg-t">Watchlist</h1>
<p class="pg-sub">Track your tokens &middot; Bookmark URL to save</p>
<form class="search-bar" action="/watchlist" method="get">
<input type="text" name="tokens" value="" placeholder="bitcoin,ethereum,solana..." autocomplete="off">
<button type="submit">Update</button></form>
<div class="chip-bar">{chips}</div>
<div class="empty"><h2>No tokens selected</h2><p>Enter slugs above or pick a preset.</p></div>"""
        return page_shell("Watchlist", body, active_nav="watchlist")

    total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
    avg_change = sum(t.get("price_usd_change") or 0 for t in tokens) / len(tokens) if tokens else 0

    rows = ""
    for i, t in enumerate(tokens):
        slug_t = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv_t = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv_t)[1]}">{mvrv_zone(mvrv_t)[0]}</span>' if mvrv_t else "&mdash;"
        rows += f'<tr><td class="col-rk">{i+1}</td><td class="col-nm"><a href="/token/{slug_t}"><strong>{_esc(t.get("name",slug_t)[:20])}</strong><span class="tk">{_esc(t.get("ticker",""))}</span></a></td><td class="col-r bold">{fmt_usd(t.get("price_usd"))}</td><td class="col-r {pct_class(pct)}">{fmt_pct(pct)}</td><td class="col-r hide-m">{fmt_usd(t.get("marketcap_usd"))}</td><td class="col-r hide-m">{f"{mvrv_t:.2f}" if mvrv_t else "&mdash;"}</td><td class="hide-m">{zone_html}</td></tr>'

    body = f"""
<h1 class="pg-t">Watchlist</h1>
<form class="search-bar" action="/watchlist" method="get">
<input type="text" name="tokens" value="{_esc(slugs_str)}" autocomplete="off">
<button type="submit">Update</button></form>
<div class="chip-bar">{chips}</div>
<div class="stats">
<div class="stat"><div class="stat-l">Combined MCap</div><div class="stat-v">{fmt_usd(total_mcap)}</div></div>
<div class="stat"><div class="stat-l">Avg 24h</div><div class="stat-v {pct_class(avg_change)}">{fmt_pct(avg_change)}</div></div>
<div class="stat"><div class="stat-l">Tokens</div><div class="stat-v">{len(tokens)}</div></div>
</div>
<div class="tbl-w"><table>
<thead><tr><th class="col-rk">#</th><th>Name</th><th class="col-r">Price</th><th class="col-r">24h</th><th class="col-r hide-m">MCap</th><th class="col-r hide-m">MVRV</th><th class="hide-m">Zone</th></tr></thead>
<tbody>{rows}</tbody>
</table></div>
{f'<a href="/compare?tokens={_esc(slugs_str)}" class="chip" style="margin-top:8px">Compare these tokens</a>' if len(slug_list) >= 2 else ''}
{f'<a href="/watchlist/export.csv?tokens={_esc(slugs_str)}" class="export-btn" style="margin-left:8px">Export CSV</a>' if slugs_str else ''}"""

    return page_shell("Watchlist", body, active_nav="watchlist")


# ================================================================
# GLOSSARY PAGE
# ================================================================

def render_glossary_page() -> str:
    categories = [
        ("Valuation", "val", [
            ("MVRV", "mvrv_usd", "Market Value to Realized Value. Below 1.0 = undervalued; above 3.0 = caution."),
            ("NVT", "nvt", "Network Value to Transactions. Crypto P/E ratio. High = overvalued relative to usage."),
        ]),
        ("Network Activity", "act", [
            ("Daily Active Addresses", "daily_active_addresses", "Unique addresses transacting per day. Rising = adoption."),
            ("Network Growth", "network_growth", "New addresses per day. Higher = expanding adoption."),
            ("Transaction Volume", "transaction_volume", "On-chain economic throughput per day."),
        ]),
        ("Supply & Flow", "supply", [
            ("Exchange Balance", "exchange_balance", "Tokens on exchanges. Decreasing = accumulation. Increasing = distribution."),
            ("Whale Txs (>$100K)", "whale_transaction_count_100k_usd_to_inf", "Large transactions. Spikes precede price moves."),
        ]),
        ("Development", "dev", [
            ("Dev Activity", "dev_activity", "GitHub events (commits, PRs). Measures project maintenance."),
        ]),
        ("Social", "social", [
            ("Social Volume", "social_volume_total", "Social media mentions. Spikes = attention/hype."),
            ("Sentiment", "sentiment_balance_total", "Positive vs negative mentions. Extremes = contrarian signal."),
        ]),
    ]

    sections = ""
    for cat_name, cat_id, metrics in categories:
        cards = ""
        for title, key, desc in metrics:
            cards += f'<div class="card glossary-card"><h3>{_esc(title)}</h3><code>{_esc(key)}</code><p>{_esc(desc)}</p></div>'
        sections += f'<div id="{cat_id}"><h2 style="font-size:1rem;margin:14px 0 6px">{_esc(cat_name)}</h2><div class="glossary-grid">{cards}</div></div>'

    cat_nav = "".join(f'<a href="#{cid}" class="fbtn">{_esc(cn)}</a>' for cn, cid, _ in categories)

    body = f"""
<h1 class="pg-t">Metric Glossary</h1>
<p class="pg-sub">On-chain metrics explained</p>
<div class="fbar">{cat_nav}</div>
{sections}"""

    return page_shell("Glossary", body)
