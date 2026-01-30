"""
Server-side HTML renderer — pure HTML, zero JavaScript.

Every page is a complete HTML document rendered on the server.
Navigation is via <a> links. Charts are inline SVG.

Design philosophy: Daily economy briefing, not a trading terminal.
Open it once, understand the entire crypto economy in 30 seconds.
"""

import html as html_mod
from datetime import datetime
from typing import Optional

from .svg_charts import (
    sparkline_svg, line_chart_svg, chart_panel, comparison_table,
    market_heatmap_svg, dominance_bar_svg, sentiment_gauge_svg, mini_trend_svg,
    scatter_plot_svg, THESIS_COLORS,
)


# ================================================================
# FORMAT HELPERS
# ================================================================

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


def css_class(v) -> str:
    if v is None:
        return "muted"
    return "up" if v > 0 else "down" if v < 0 else "muted"


def mvrv_zone(v):
    if v is None:
        return ("N/A", "zone-neutral", "No data")
    if v < 0.7:
        return ("Deep Value", "zone-extreme-low", "Well below realized value — historically strong buying zone")
    if v < 1.0:
        return ("Undervalued", "zone-undervalued", "Below realized value — accumulation territory")
    if v < 1.5:
        return ("Fair Value", "zone-fair", "Near realized value — balanced market")
    if v < 2.5:
        return ("Elevated", "zone-fair-high", "Above realized value — caution warranted")
    if v < 3.5:
        return ("Overvalued", "zone-overvalued", "Well above realized value — distribution risk")
    return ("Euphoria", "zone-extreme-high", "Far above realized value — extreme caution")


def pct_class(v):
    return css_class(v)


def _esc(s):
    return html_mod.escape(str(s)) if s else ""


# ================================================================
# PAGE SHELL
# ================================================================

# Module-level ticker data getter — set by api.py at startup
_ticker_data_fn = None

def set_ticker_data_fn(fn):
    """Set the function that provides ticker data for the header strip."""
    global _ticker_data_fn
    _ticker_data_fn = fn


def page_shell(title: str, body: str, active_nav: str = "", ticker_data: list = None) -> str:
    nav_items = [
        ("briefing", "/", "Briefing"),
        ("insights", "/insights", "Insights"),
        ("explore", "/explore", "Explore"),
        ("screener", "/screener", "Screener"),
        ("valuation", "/valuation", "Valuation"),
        ("compare", "/compare?tokens=bitcoin,ethereum,solana", "Compare"),
        ("watchlist", "/watchlist?tokens=bitcoin,ethereum,solana,cardano,avalanche", "Watchlist"),
        ("sync", "/sync", "Sync"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="nav-link{" active" if key == active_nav else ""}">{label}</a>'
        for key, href, label in nav_items
    )

    # Market ticker strip — use passed data or fetch from global getter
    if ticker_data is None and _ticker_data_fn:
        try:
            ticker_data = _ticker_data_fn()
        except Exception:
            ticker_data = None
    ticker_html = ""
    if ticker_data:
        ticker_items = ""
        for t in ticker_data:
            pct = t.get("change")
            cls = "up" if pct and pct > 0 else "down" if pct and pct < 0 else "muted"
            pct_str = f"{pct:+.1f}%" if pct is not None else ""
            ticker_items += (
                f'<a href="/token/{t["slug"]}" class="ticker-item">'
                f'<span class="ticker-item-name">{_esc(t.get("ticker", ""))}</span>'
                f'<span class="ticker-item-price">{fmt_usd(t.get("price"))}</span>'
                f'<span class="ticker-item-pct {cls}">{pct_str}</span>'
                f'</a>'
            )
        ticker_html = f'<div class="ticker-strip"><div class="ticker-strip-inner">{ticker_items}</div></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(title)} — Onchain Pulse</title>
    <meta name="description" content="Real-time on-chain crypto analytics powered by Santiment. MVRV, active addresses, exchange flows, dev activity across 3500+ tokens.">
    <meta property="og:title" content="{_esc(title)} — Onchain Pulse">
    <meta property="og:description" content="On-chain crypto analytics dashboard. MVRV zones, network health, smart money signals.">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/dashboard.css">
</head>
<body>
    {ticker_html}
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">Onchain<span>Pulse</span></a>
            <input type="checkbox" id="nav-toggle" class="nav-toggle" hidden>
            <label for="nav-toggle" class="nav-toggle-label"><span></span></label>
            <nav class="header-nav">{nav_html}</nav>
        </div>
    </header>
    <main class="main">{body}</main>
    <footer class="footer">
        On-chain data via <strong>Santiment</strong>. Refreshed daily. Not financial advice.
    </footer>
</body>
</html>"""


# ================================================================
# BRIEFING PAGE (Landing — Daily Economy Dashboard)
# ================================================================

def _signal_icon(signal_type: str) -> str:
    icons = {
        "daa_spike": "&#9650;",      # up triangle
        "daa_drop": "&#9660;",       # down triangle
        "accumulation": "&#9679;",   # circle
        "distribution": "&#9675;",   # empty circle
        "dev_surge": "&#9733;",      # star
        "dev_decline": "&#9734;",    # empty star
    }
    return icons.get(signal_type, "&#8226;")


def _signal_label(signal_type: str) -> str:
    labels = {
        "daa_spike": "Activity Surge",
        "daa_drop": "Activity Drop",
        "accumulation": "Accumulation",
        "distribution": "Distribution",
        "dev_surge": "Dev Surge",
        "dev_decline": "Dev Decline",
    }
    return labels.get(signal_type, signal_type)


def _signal_css(signal_type: str) -> str:
    if signal_type in ("daa_spike", "accumulation", "dev_surge"):
        return "up"
    return "down"


def render_briefing_page(briefing: dict, pull_status: str, cache_stats: dict, universe_size: int, sectors: dict = None) -> str:
    if not briefing:
        loading_cards = '<div class="loading-card"><div class="loading-bar w-50"></div><div class="loading-bar w-75"></div><div class="loading-bar w-full"></div></div>' * 4
        return page_shell("Briefing", f"""
        <div class="empty-state">
            <div class="empty-state-icon">&#9201;</div>
            <h2>Building your briefing...</h2>
            <p>On-chain data is being pulled from Santiment. This takes a few minutes on first deploy.</p>
            <p style="margin-top:8px"><a href="/sync">View sync progress &rarr;</a></p>
        </div>
        <div class="loading-grid">{loading_cards}</div>""", active_nav="briefing")

    b = briefing
    parts = []

    # ── Sync banner (compact) ──
    is_syncing = pull_status not in ("ready", "idle", "skipped")
    if is_syncing:
        cs = cache_stats or {}
        parts.append(f"""
        <div class="sync-banner">
            <span class="sync-dot"></span>
            <span>Syncing {b.get("total_tokens", 0)} tokens · {fmt_num(cs.get("timeseries_rows", 0))} data points</span>
            <a href="/sync">Details &rarr;</a>
        </div>""")

    # ── Header ──
    now_str = datetime.utcnow().strftime("%B %d, %Y")
    parts.append(f"""
    <div class="briefing-header">
        <div>
            <h1 class="briefing-title">Daily Economy Briefing</h1>
            <p class="briefing-date">{now_str} &middot; {b.get("total_tokens", 0)} tokens tracked</p>
        </div>
    </div>""")

    # ── Section 1: Market Regime ──
    avg_mvrv = b.get("avg_mvrv")
    breadth = b.get("breadth", {})
    zone_label, zone_css, zone_desc = mvrv_zone(avg_mvrv)

    # Regime verdict
    up = breadth.get("up", 0)
    down = breadth.get("down", 0)
    total_bd = up + down
    breadth_pct = (up / total_bd * 100) if total_bd else 50

    if avg_mvrv is not None and avg_mvrv < 1.0 and breadth_pct < 40:
        regime = ("Bearish", "regime-bear")
    elif avg_mvrv is not None and avg_mvrv > 2.0 and breadth_pct > 65:
        regime = ("Bullish", "regime-bull")
    elif breadth_pct > 55:
        regime = ("Cautiously Bullish", "regime-neutral-bull")
    elif breadth_pct < 45:
        regime = ("Cautiously Bearish", "regime-neutral-bear")
    else:
        regime = ("Neutral", "regime-neutral")

    gauge_svg = sentiment_gauge_svg(avg_mvrv, min_val=0, max_val=4, label="MVRV") if avg_mvrv is not None else ""

    # BTC price trend
    btc_trend = b.get("trends", {}).get("btc_price", [])
    btc_chart = mini_trend_svg(btc_trend, width=200, height=50) if btc_trend and len(btc_trend) > 5 else ""

    parts.append(f"""
    <section class="card regime-card">
        <div class="card-header">
            <h2 class="card-title">Market Regime</h2>
            <span class="regime-badge {regime[1]}">{regime[0]}</span>
        </div>
        <div class="regime-body">
            <div class="regime-gauge">
                {gauge_svg}
                <div class="regime-mvrv">
                    <span class="regime-mvrv-val">{f"{avg_mvrv:.2f}" if avg_mvrv else "—"}</span>
                    <span class="zone {zone_css}">{zone_label}</span>
                </div>
            </div>
            <div class="regime-stats">
                <div class="regime-stat">
                    <div class="regime-stat-label">Total Market Cap</div>
                    <div class="regime-stat-value">{fmt_usd(b.get("total_mcap"))}</div>
                    {f'<div class="regime-stat-trend">{btc_chart}</div>' if btc_chart else ''}
                </div>
                <div class="regime-stat">
                    <div class="regime-stat-label">24h Volume</div>
                    <div class="regime-stat-value">{fmt_usd(b.get("total_vol"))}</div>
                </div>
                <div class="regime-stat">
                    <div class="regime-stat-label">Market Breadth</div>
                    <div class="regime-stat-value">
                        <span class="up">{up}</span>
                        <span class="muted">/</span>
                        <span class="down">{down}</span>
                    </div>
                    <div class="breadth-bar">
                        <div class="breadth-bar-fill" style="width:{breadth_pct:.0f}%"></div>
                    </div>
                </div>
                <div class="regime-stat">
                    <div class="regime-stat-label">Vol. Concentration</div>
                    <div class="regime-stat-value">{b.get("vol_concentration_top10", 0):.0f}% in top 10</div>
                </div>
            </div>
        </div>
        <p class="regime-desc">{zone_desc}</p>
    </section>""")

    # ── Section 2: Valuation Landscape ──
    zones = b.get("mvrv_zones", {})
    zone_total = b.get("mvrv_total", 0) or 1
    zone_defs = [
        ("Deep Value", "deep_value", "zone-extreme-low"),
        ("Undervalued", "undervalued", "zone-undervalued"),
        ("Fair Value", "fair", "zone-fair"),
        ("Elevated", "elevated", "zone-fair-high"),
        ("Overvalued", "overvalued", "zone-overvalued"),
        ("Euphoria", "euphoria", "zone-extreme-high"),
    ]
    zone_bars = ""
    for label, key, css in zone_defs:
        cnt = zones.get(key, 0)
        pct = cnt / zone_total * 100 if zone_total else 0
        zone_bars += f"""
        <div class="zone-row">
            <span class="zone-row-label"><span class="zone {css}">{label}</span></span>
            <div class="zone-row-bar"><div class="zone-row-fill {css}" style="width:{pct:.0f}%"></div></div>
            <span class="zone-row-count">{cnt}</span>
        </div>"""

    parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">Valuation Landscape</h2>
            <span class="card-badge">{zone_total} tokens with MVRV data</span>
        </div>
        <div class="zone-distribution">{zone_bars}</div>
        <div class="card-footer">
            <a href="/valuation">View full valuation scanner &rarr;</a>
        </div>
    </section>""")

    # ── Section 2b: Sector Breakdown ──
    sector_data = b.get("sector_data", {})
    _sectors = sectors or {}
    if sector_data:
        # Sort sectors by market cap
        sorted_sectors = sorted(sector_data.items(), key=lambda x: x[1].get("mcap", 0), reverse=True)
        total_sec_mcap = sum(v["mcap"] for _, v in sorted_sectors) or 1

        sector_items = ""
        for sec_key, sec_vals in sorted_sectors:
            if sec_vals["count"] == 0:
                continue
            sec_label = _sectors.get(sec_key, sec_key.replace("_", " ").title())
            mcap_pct = sec_vals["mcap"] / total_sec_mcap * 100
            sector_items += f"""
            <a href="/explore?sector={sec_key}" class="sector-card sector-{sec_key}">
                <span class="sector-card-name">{_esc(sec_label)}</span>
                <span class="sector-card-count">{sec_vals["count"]}</span>
                <span class="sector-card-mcap">{fmt_usd(sec_vals["mcap"])}</span>
                <div class="sector-card-bar"><div class="sector-card-fill" style="width:{mcap_pct:.0f}%"></div></div>
            </a>"""

        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">Sector Breakdown</h2>
            <span class="card-badge">{len(sorted_sectors)} sectors</span>
        </div>
        <div class="sector-grid">{sector_items}</div>
        <div class="card-footer">
            <a href="/insights">View thesis analysis &rarr;</a>
        </div>
    </section>""")

    # ── Section 3: Network Health ──
    trends = b.get("trends", {})

    health_metrics = []
    daa = b.get("total_daa")
    daa_ch = b.get("avg_daa_change")
    daa_trend = trends.get("daa", [])
    if daa:
        health_metrics.append(("Active Addresses", fmt_num(daa), daa_ch, daa_trend))

    dev = b.get("total_dev")
    dev_ch = b.get("avg_dev_change")
    dev_trend = trends.get("dev", [])
    if dev:
        health_metrics.append(("Developer Activity", fmt_num(dev), dev_ch, dev_trend))

    growth = b.get("total_growth")
    growth_trend = trends.get("growth", [])
    if growth:
        health_metrics.append(("Network Growth", fmt_num(growth), None, growth_trend))

    vol_trend = trends.get("volume", [])
    if vol_trend:
        health_metrics.append(("Aggregate Volume", fmt_usd(b.get("total_vol")), None, vol_trend))

    health_cards = ""
    for label, value, change, trend_data in health_metrics:
        trend_chart = mini_trend_svg(trend_data, width=140, height=36) if trend_data and len(trend_data) > 5 else ""
        change_html = f'<span class="{css_class(change)}">{fmt_pct(change)}</span>' if change is not None else ""
        health_cards += f"""
        <div class="health-card">
            <div class="health-card-header">
                <span class="health-card-label">{label}</span>
                {change_html}
            </div>
            <div class="health-card-value">{value}</div>
            <div class="health-card-trend">{trend_chart}</div>
        </div>"""

    if health_cards:
        # Capital flow signals
        accum = b.get("accumulating", 0)
        distrib = b.get("distributing", 0)
        flow_html = ""
        if accum or distrib:
            flow_html = f"""
            <div class="flow-summary">
                <span class="flow-item up">&#9679; {accum} accumulating</span>
                <span class="flow-item down">&#9675; {distrib} distributing</span>
                <span class="flow-item muted">(exchange balance shift &gt; 1%)</span>
            </div>"""

        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">Network Health</h2>
            <span class="card-badge">Top 20 bellwether tokens · 90 day trends</span>
        </div>
        <div class="health-grid">{health_cards}</div>
        {flow_html}
    </section>""")

    # ── Section 4: On-Chain Signals ──
    signals = b.get("signals", [])
    if signals:
        signal_rows = ""
        for s in signals[:12]:
            slug = s.get("slug", "")
            sig_type = s.get("signal", "")
            signal_rows += f"""
            <a href="/token/{slug}" class="signal-row">
                <span class="signal-icon {_signal_css(sig_type)}">{_signal_icon(sig_type)}</span>
                <span class="signal-name">{_esc(s.get("name", slug)[:20])} <span class="ticker">{_esc(s.get("ticker", ""))}</span></span>
                <span class="signal-type">{_signal_label(sig_type)}</span>
                <span class="signal-metric">{_esc(s.get("metric", ""))}</span>
                <span class="signal-change {css_class(s.get("change"))}">{fmt_pct(s.get("change"))}</span>
            </a>"""

        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">On-Chain Signals</h2>
            <span class="card-badge">Meaningful moves beyond price</span>
        </div>
        <div class="signal-list">{signal_rows}</div>
    </section>""")

    # ── Section 5: Dominance + Heatmap (side by side) ──
    all_tokens = b.get("all_tokens", [])
    if len(all_tokens) > 5:
        dom = sorted(all_tokens, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)
        parts.append(f"""
    <div class="two-col">
        <section class="card">
            <div class="card-header"><h2 class="card-title">Market Dominance</h2></div>
            <div class="dominance-wrap">{dominance_bar_svg(dom)}</div>
        </section>
        <section class="card">
            <div class="card-header">
                <h2 class="card-title">24h Heatmap</h2>
            </div>
            <div class="heatmap-wrap">{market_heatmap_svg(all_tokens, max_tokens=40)}</div>
        </section>
    </div>""")

    # ── Section 6: Movers ──
    gainers = b.get("gainers", [])
    losers = b.get("losers", [])
    if gainers or losers:
        def _mover_rows(items):
            rows = ""
            for i, t in enumerate(items[:8]):
                slug = t.get("slug", "")
                pct = t.get("price_usd_change")
                rows += (
                    f'<a href="/token/{slug}" class="mover-row">'
                    f'<span class="mover-rank">{i+1}</span>'
                    f'<span class="mover-name">{_esc(t.get("name", slug)[:18])} '
                    f'<span class="ticker">{_esc(t.get("ticker", ""))}</span></span>'
                    f'<span class="mover-price">{fmt_usd(t.get("price_usd"))}</span>'
                    f'<span class="mover-pct {css_class(pct)}">{fmt_pct(pct)}</span>'
                    f'</a>'
                )
            return rows

        parts.append(f"""
    <div class="two-col">
        <section class="card">
            <div class="card-header"><h2 class="card-title up-header">Top Gainers</h2></div>
            {_mover_rows(gainers)}
        </section>
        <section class="card">
            <div class="card-header"><h2 class="card-title down-header">Top Losers</h2></div>
            {_mover_rows(losers)}
        </section>
    </div>""")

    # ── Section 7: Top by metrics ──
    top_vol = b.get("top_volume", [])[:8]
    top_daa = b.get("top_daa", [])[:8]
    top_dev = b.get("top_dev", [])[:8]

    def _top_list(items, val_key, fmt_fn):
        rows = ""
        for i, t in enumerate(items):
            slug = t.get("slug", "")
            rows += (
                f'<a href="/token/{slug}" class="top-row">'
                f'<span class="top-rank">{i+1}</span>'
                f'<span class="top-name">{_esc(t.get("name", slug)[:18])} '
                f'<span class="ticker">{_esc(t.get("ticker", ""))}</span></span>'
                f'<span class="top-val">{fmt_fn(t.get(val_key))}</span>'
                f'</a>'
            )
        return rows

    if top_vol or top_daa or top_dev:
        cols = []
        if top_vol:
            cols.append(f'<section class="card"><div class="card-header"><h2 class="card-title">By Volume</h2></div>{_top_list(top_vol, "volume_usd", fmt_usd)}</section>')
        if top_daa:
            cols.append(f'<section class="card"><div class="card-header"><h2 class="card-title">By Active Addresses</h2></div>{_top_list(top_daa, "daily_active_addresses", fmt_num)}</section>')
        if top_dev:
            cols.append(f'<section class="card"><div class="card-header"><h2 class="card-title">By Dev Activity</h2></div>{_top_list(top_dev, "dev_activity", fmt_num)}</section>')
        parts.append(f'<div class="three-col">{"".join(cols)}</div>')

    # ── Footer nav ──
    parts.append("""
    <div class="briefing-footer-nav">
        <a href="/insights" class="footer-nav-card">
            <strong>Insights</strong>
            <span>Scatter plots and thesis categorization</span>
        </a>
        <a href="/explore" class="footer-nav-card">
            <strong>Explore</strong>
            <span>Browse all tokens with full metrics table</span>
        </a>
        <a href="/screener" class="footer-nav-card">
            <strong>Screener</strong>
            <span>Filter by tier, sort by any metric</span>
        </a>
        <a href="/valuation" class="footer-nav-card">
            <strong>Valuation</strong>
            <span>MVRV zone scanner across all tokens</span>
        </a>
        <a href="/compare?tokens=bitcoin,ethereum,solana" class="footer-nav-card">
            <strong>Compare</strong>
            <span>Side-by-side on-chain comparison</span>
        </a>
    </div>""")

    return page_shell("Daily Briefing", "\n".join(parts), active_nav="briefing")


# ================================================================
# INSIGHTS PAGE (Scatter plots + Thesis categories)
# ================================================================

THESIS_LABELS = {
    "smart_money": "Smart Money Accumulating",
    "builder_momentum": "Builder Momentum",
    "deep_value": "Deep Value",
    "distribution_warning": "Distribution Warning",
    "hodler": "HODLer Coins",
    "high_utility": "High Utility",
    "speculative": "Speculative",
    "uncategorized": "Uncategorized",
}

THESIS_DESCRIPTIONS = {
    "smart_money": "Exchange balance dropping while price is flat — insiders may be accumulating off-exchange.",
    "builder_momentum": "Rising developer activity and network growth — the builders are shipping.",
    "deep_value": "MVRV well below realized value with active addresses — historically strong buying zones.",
    "distribution_warning": "Exchange balance rising with elevated MVRV — potential distribution by large holders.",
    "hodler": "Low velocity, moderate valuation — long-term holders dominating supply.",
    "high_utility": "High active address count relative to market cap — real usage, not just speculation.",
    "speculative": "High volume relative to market cap but low active addresses — trading-driven, not usage-driven.",
    "uncategorized": "No strong on-chain signal pattern detected.",
}


def render_insights_page(
    insights: dict,
    view_id: str = "mvrv_nvt",
    scatter_views: list = None,
    sector: str = "all",
    sectors: dict = None,
) -> str:
    if not insights or not insights.get("points"):
        return page_shell("Insights", '<div class="empty-state"><h2>Loading insights...</h2><p>Data is being computed. Try again shortly.</p></div>', active_nav="insights")

    _sectors = sectors or {}
    parts = []

    # Header
    sector_label = _sectors.get(sector, "") if sector != "all" else ""
    subtitle_extra = f" — {sector_label}" if sector_label else ""
    parts.append(f"""
    <h1 class="page-title">On-Chain Insights</h1>
    <p class="page-subtitle">Cross-metric scatter plots and thesis categorization{subtitle_extra} &middot; {len(insights.get("points", []))} tokens plotted</p>""")

    # ── Scatter plot view selector ──
    filter_rows = ""
    if scatter_views:
        view_tabs = ""
        for vid, vtitle, *_ in scatter_views:
            active = " active" if vid == view_id else ""
            short_title = vtitle.split(":")[0] if ":" in vtitle else vtitle
            sec_qs = f"&sector={sector}" if sector != "all" else ""
            view_tabs += f'<a href="/insights?view={vid}{sec_qs}" class="filter-btn{active}">{_esc(short_title)}</a>'
        filter_rows += f'<div class="filter-group"><span class="filter-label">View:</span>{view_tabs}</div>'

    # Sector filter
    if _sectors:
        sector_btns = f'<a href="/insights?view={view_id}" class="filter-btn{" active" if sector == "all" else ""}">All Sectors</a>'
        for key in ["l1", "l2", "defi", "stablecoin", "exchange", "meme", "ai", "gaming", "infrastructure", "oracle", "privacy", "storage", "rwa"]:
            label = _sectors.get(key, key.title())
            sector_btns += f'<a href="/insights?view={view_id}&sector={key}" class="filter-btn{" active" if key == sector else ""}">{_esc(label)}</a>'
        filter_rows += f'<div class="filter-group"><span class="filter-label">Sector:</span>{sector_btns}</div>'

    if filter_rows:
        parts.append(f'<div class="filter-bar filter-bar-stacked">{filter_rows}</div>')

    # ── Scatter plot ──
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
            insights["points"],
            width=720, height=420,
            title=chart_title,
            x_key="x", y_key="y",
            x_label=x_label, y_label=y_label,
            color_key="thesis",
            size_key="marketcap_usd",
            log_x=log_x, log_y=log_y,
        )

        # Legend for thesis colors
        legend_items = ""
        thesis_counts = insights.get("thesis_counts", {})
        for key in ["smart_money", "builder_momentum", "deep_value", "distribution_warning", "hodler", "high_utility", "speculative", "uncategorized"]:
            cnt = thesis_counts.get(key, 0)
            if cnt == 0:
                continue
            color = THESIS_COLORS.get(key, "#9CA3AF")
            label = THESIS_LABELS.get(key, key)
            legend_items += (
                f'<a href="#thesis-{key}" class="scatter-legend-item">'
                f'<span class="scatter-legend-dot" style="background:{color}"></span>'
                f'{_esc(label)} <span class="scatter-legend-count">({cnt})</span>'
                f'</a>'
            )

        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">{_esc(chart_title)}</h2>
            <span class="card-badge">{len(insights["points"])} tokens plotted</span>
        </div>
        <div class="scatter-wrap">{chart_svg}</div>
        <div class="scatter-legend">{legend_items}</div>
    </section>""")

    # ── Thesis categories ──
    thesis_tokens = insights.get("thesis_tokens", {})
    thesis_counts = insights.get("thesis_counts", {})

    if thesis_counts:
        # Summary bar
        total_classified = sum(v for k, v in thesis_counts.items() if k != "uncategorized")
        total_all = sum(thesis_counts.values())
        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title">Thesis Categories</h2>
            <span class="card-badge">{total_classified} of {total_all} tokens classified</span>
        </div>
        <p class="thesis-explainer">Each token is classified into a thesis based on its on-chain profile: exchange flows, developer activity, valuation metrics, and usage patterns.</p>""")

        # Thesis distribution bars
        parts.append('<div class="thesis-distribution">')
        for key in ["smart_money", "builder_momentum", "deep_value", "distribution_warning", "hodler", "high_utility", "speculative"]:
            cnt = thesis_counts.get(key, 0)
            if cnt == 0:
                continue
            pct = cnt / total_all * 100 if total_all else 0
            color = THESIS_COLORS.get(key, "#9CA3AF")
            label = THESIS_LABELS.get(key, key)
            desc = THESIS_DESCRIPTIONS.get(key, "")
            tokens_list = thesis_tokens.get(key, [])

            token_chips = ""
            for t in tokens_list[:8]:
                slug = t.get("slug", "")
                pct_ch = t.get("price_usd_change")
                pct_cls = css_class(pct_ch)
                token_chips += (
                    f'<a href="/token/{slug}" class="thesis-token-chip">'
                    f'<span class="thesis-token-name">{_esc(t.get("ticker", "")[:6])}</span>'
                    f'<span class="thesis-token-pct {pct_cls}">{fmt_pct(pct_ch)}</span>'
                    f'</a>'
                )

            parts.append(f"""
        <div class="thesis-row" id="thesis-{key}">
            <div class="thesis-row-header">
                <span class="thesis-row-dot" style="background:{color}"></span>
                <span class="thesis-row-label">{_esc(label)}</span>
                <span class="thesis-row-count">{cnt}</span>
                <div class="thesis-row-bar-wrap">
                    <div class="thesis-row-bar" style="width:{pct:.0f}%;background:{color}"></div>
                </div>
            </div>
            <p class="thesis-row-desc">{_esc(desc)}</p>
            <div class="thesis-token-list">{token_chips}</div>
        </div>""")

        parts.append('</div></section>')

    # ── Footer nav ──
    parts.append("""
    <div class="briefing-footer-nav">
        <a href="/" class="footer-nav-card">
            <strong>Briefing</strong>
            <span>Daily economy dashboard</span>
        </a>
        <a href="/screener" class="footer-nav-card">
            <strong>Screener</strong>
            <span>Filter by tier, sort by any metric</span>
        </a>
        <a href="/valuation" class="footer-nav-card">
            <strong>Valuation</strong>
            <span>MVRV zone scanner</span>
        </a>
    </div>""")

    return page_shell("Insights", "\n".join(parts), active_nav="insights")


# ================================================================
# EXPLORE PAGE (Full token table with pagination)
# ================================================================

def render_explore_page(
    tokens: list,
    page: int = 1,
    per_page: int = 100,
    total: int = 0,
    sector: str = "all",
    category: str = "all",
    sectors: dict = None,
    categories: dict = None,
    search: str = "",
    briefing: dict = None,
) -> str:
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    briefing = briefing or {}

    parts = []
    sector_label = (sectors or {}).get(sector, "All Sectors") if sector != "all" else ""
    search_note = f' matching "{_esc(search)}"' if search else ""
    subtitle = f"{total} tokens" + (f" in {sector_label}" if sector_label else "") + search_note + " ranked by market cap"
    parts.append(f"""
    <h1 class="page-title">Explore</h1>
    <p class="page-subtitle">{subtitle}</p>""")

    # Market summary bar (from briefing data)
    if briefing and page == 1 and not search:
        total_mcap = briefing.get("total_mcap")
        total_vol = briefing.get("total_vol")
        breadth = briefing.get("breadth", {})
        avg_mvrv = briefing.get("avg_mvrv")
        up, down = breadth.get("up", 0), breadth.get("down", 0)
        total_b = up + down + breadth.get("flat", 0)
        up_pct = round(up / total_b * 100) if total_b else 0

        # Top movers
        gainers = briefing.get("gainers", [])[:5]
        losers = briefing.get("losers", [])[:5]

        gainer_chips = "".join(
            f'<a href="/token/{g["slug"]}" class="mover-chip up">{_esc(g.get("ticker", ""))}: {fmt_pct(g.get("price_usd_change"))}</a>'
            for g in gainers
        )
        loser_chips = "".join(
            f'<a href="/token/{g["slug"]}" class="mover-chip down">{_esc(g.get("ticker", ""))}: {fmt_pct(g.get("price_usd_change"))}</a>'
            for g in losers
        )

        parts.append(f"""
    <div class="explore-summary">
        <div class="explore-summary-stats">
            <div class="explore-stat"><span class="explore-stat-label">Total MCap</span><span class="explore-stat-value">{fmt_usd(total_mcap)}</span></div>
            <div class="explore-stat"><span class="explore-stat-label">24h Volume</span><span class="explore-stat-value">{fmt_usd(total_vol)}</span></div>
            <div class="explore-stat"><span class="explore-stat-label">Breadth</span><span class="explore-stat-value">{up_pct}% up</span></div>
            <div class="explore-stat"><span class="explore-stat-label">Avg MVRV</span><span class="explore-stat-value">{f"{avg_mvrv:.2f}" if avg_mvrv else "&mdash;"}</span></div>
        </div>
        <div class="explore-movers">
            <div class="explore-movers-row"><span class="explore-movers-label up">Top Gainers</span>{gainer_chips}</div>
            <div class="explore-movers-row"><span class="explore-movers-label down">Top Losers</span>{loser_chips}</div>
        </div>
    </div>""")

    # Search bar
    parts.append(f"""
    <form class="search-bar" action="/explore" method="get">
        <input type="text" name="q" value="{_esc(search)}" placeholder="Search by name, ticker, or slug..." class="search-input" autocomplete="off">
        <button type="submit" class="search-btn">Search</button>
        {f'<input type="hidden" name="sector" value="{_esc(sector)}">' if sector != "all" else ""}
        <input type="hidden" name="per_page" value="{per_page}">
    </form>""")

    # Sector filter bar
    if sectors:
        q_param = f"&q={_esc(search)}" if search else ""
        sector_btns = f'<a href="/explore?per_page={per_page}{q_param}" class="filter-btn{"  active" if sector == "all" else ""}">All</a>'
        for key, label in sorted(sectors.items(), key=lambda x: x[1]):
            sector_btns += f'<a href="/explore?sector={key}&per_page={per_page}{q_param}" class="filter-btn{" active" if key == sector else ""}">{_esc(label)}</a>'
        parts.append(f"""
    <div class="filter-bar">
        <div class="filter-group"><span class="filter-label">Sector:</span>{sector_btns}</div>
    </div>""")

    # Table
    parts.append(f"""
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th>
                <th>Name</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">Price</th>
                <th class="col-num">24h</th>
                <th class="col-spark hide-mobile">7d</th>
                <th class="col-num">Market Cap</th>
                <th class="col-num hide-mobile">Volume</th>
                <th class="col-num hide-mobile">MVRV</th>
                <th class="col-tag hide-mobile">Zone</th>
            </tr></thead>
            <tbody>""")

    if not tokens:
        parts.append('<tr><td colspan="10" class="empty-cell">Data is being pulled. Refresh shortly.</td></tr>')
    else:
        _sector_labels = sectors or {}
        for i, t in enumerate(tokens):
            rank = start + i + 1
            slug = t.get("slug", "")
            pct = t.get("price_usd_change")
            mvrv = t.get("mvrv_usd")
            zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv is not None else "&mdash;"
            spark = t.get("sparkline_7d", [])
            spark_html = sparkline_svg(spark, width=80, height=24) if spark else "&mdash;"
            sec = t.get("sector", "other")
            sec_label = _sector_labels.get(sec, sec.replace("_", " ").title())
            parts.append(f"""<tr>
                <td class="col-rank">{rank}</td>
                <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
                <td class="col-tag hide-mobile"><a href="/explore?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a></td>
                <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
                <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
                <td class="col-spark hide-mobile">{spark_html}</td>
                <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
                <td class="col-num hide-mobile">{fmt_usd(t.get("volume_usd"))}</td>
                <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
                <td class="col-tag hide-mobile">{zone_html}</td>
            </tr>""")

    parts.append("</tbody></table></div>")

    # Pagination
    if total_pages > 1:
        qs = f"per_page={per_page}"
        if sector != "all":
            qs += f"&sector={sector}"
        if category != "all":
            qs += f"&category={category}"
        if search:
            qs += f"&q={_esc(search)}"
        pg = []
        pg.append(f'<a href="/explore?page={page-1}&{qs}" class="page-btn">&laquo;</a>' if page > 1 else '<span class="page-btn disabled">&laquo;</span>')
        for p in range(1, total_pages + 1):
            if p == page:
                pg.append(f'<span class="page-btn active">{p}</span>')
            elif p <= 2 or p > total_pages - 1 or abs(p - page) <= 2:
                pg.append(f'<a href="/explore?page={p}&{qs}" class="page-btn">{p}</a>')
            elif (p == 3 and page > 5) or (p == total_pages - 1 and page < total_pages - 4):
                pg.append('<span class="page-btn ellipsis">&hellip;</span>')
        pg.append(f'<a href="/explore?page={page+1}&{qs}" class="page-btn">&raquo;</a>' if page < total_pages else '<span class="page-btn disabled">&raquo;</span>')
        parts.append(f'<div class="pagination">{"".join(pg)}</div>')

    return page_shell("Explore", "\n".join(parts), active_nav="explore")


# ================================================================
# TOKEN PROFILE
# ================================================================

def render_token_profile(token: dict, metrics: dict, slug: str = "", timeframe: str = "all", token_info: dict = None) -> str:
    slug = slug or token.get("slug", "")
    name = _esc(token.get("name", slug))
    ticker = _esc(token.get("ticker", ""))
    infra = _esc(token.get("infrastructure", ""))

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
    changes = []
    price_ts = _data("price_usd")
    if price_ts and len(price_ts) >= 2:
        curr = price_ts[-1].get("value")
        for label, days in [("24h", 1), ("7d", 7), ("30d", 30)]:
            if len(price_ts) > days and curr:
                prev = price_ts[-1 - days].get("value")
                if prev and prev != 0:
                    v = (curr - prev) / prev * 100
                    cls = "up" if v > 0 else "down" if v < 0 else "flat"
                    changes.append(f'<span class="change-pill {cls}">{label} {fmt_pct(v)}</span>')

    # Metric cards
    metric_cards = []
    metric_defs = [
        ("marketcap_usd", "Market Cap"), ("volume_usd", "Volume 24h"),
        ("mvrv_usd", "MVRV"), ("nvt", "NVT Ratio"),
        ("daily_active_addresses", "Active Addresses"),
        ("transaction_volume", "Tx Volume"),
        ("exchange_balance", "Exchange Balance"),
        ("dev_activity", "Dev Activity"),
        ("network_growth", "Network Growth"),
        ("circulation", "Circulation"),
        ("velocity", "Velocity"),
        ("mean_age", "Mean Dollar Age"),
        ("whale_transaction_count_100k_usd_to_inf", "Whale Txs (>$100K)"),
        ("social_volume_total", "Social Volume"),
        ("sentiment_balance_total", "Sentiment"),
    ]
    for key, label in metric_defs:
        latest = _latest(key)
        if latest is None:
            continue
        is_usd = "usd" in key and "mvrv" not in key and "nvt" not in key
        val_str = fmt_usd(latest) if is_usd else f"{latest:,.2f}" if latest < 1000 else fmt_num(latest)
        metric_cards.append(f"""
        <div class="metric-card">
            <div class="metric-label">{_esc(label)}</div>
            <div class="metric-value">{val_str}</div>
        </div>""")

    # Charts
    price_data = _data("price_usd")
    price_chart = line_chart_svg(
        [{"label": "Price USD", "data": price_data, "color": "#0F1419"}],
        width=720, height=300, title="Price History", metric_key="price_usd",
        show_min_max=True,
    ) if price_data else ""

    secondary_charts = []
    chart_defs = [
        ("volume_usd", "Daily Volume", "#3B82F6"),
        ("marketcap_usd", "Market Cap", "#0F1419"),
        ("mvrv_usd", "MVRV Ratio", "#8B5CF6"),
        ("daily_active_addresses", "Active Addresses", "#10B981"),
        ("exchange_balance", "Exchange Balance", "#EF4444"),
        ("dev_activity", "Dev Activity", "#F59E0B"),
        ("network_growth", "Network Growth", "#06B6D4"),
        ("transaction_volume", "Tx Volume", "#EC4899"),
        ("circulation", "Circulation", "#14B8A6"),
        ("whale_transaction_count_100k_usd_to_inf", "Whale Txs", "#F97316"),
        ("social_volume_total", "Social Volume", "#8B5CF6"),
        ("sentiment_balance_total", "Sentiment", "#3B82F6"),
    ]
    for key, title, color in chart_defs:
        data = _data(key)
        if not data or len(data) < 3:
            continue
        secondary_charts.append(line_chart_svg(
            [{"label": title, "data": data, "color": color}],
            width=340, height=200, title=title, metric_key=key,
            show_min_max=False, show_area=True,
        ))

    charts_html = ""
    if price_chart:
        charts_html += f'<div class="chart-wrap">{price_chart}</div>'
    if secondary_charts:
        charts_html += chart_panel(secondary_charts, columns=2)

    # Sector / category tags
    sector_html = ""
    if token_info:
        sec = token_info.get("sector", "other")
        cat = token_info.get("category", "other")
        sec_label = sec.replace("_", " ").title()
        cat_label = cat.replace("_", " ").title()
        sector_html = f'<a href="/explore?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a>'
        if cat != "other" and cat != sec:
            sector_html += f' <span class="profile-cat">{_esc(cat_label)}</span>'

    # Timeframe selector
    tf_btns = ""
    for tf_key, tf_label in [("7d", "7D"), ("30d", "30D"), ("90d", "90D"), ("1y", "1Y"), ("all", "All")]:
        active = " active" if tf_key == timeframe else ""
        tf_btns += f'<a href="/token/{slug}?tf={tf_key}" class="tf-btn{active}">{tf_label}</a>'

    # MVRV zone
    mvrv_html = ""
    if mvrv is not None:
        zone_label, zone_css, zone_desc = mvrv_zone(mvrv)
        mvrv_html = f'<div class="profile-mvrv"><span class="zone {zone_css}">{zone_label}</span> <span class="profile-mvrv-val">MVRV {mvrv:.2f}</span></div>'

    body = f"""
    <div class="profile-nav-row">
        <a href="/" class="back-link">&larr; Briefing</a>
        <a href="/explore" class="back-link">Explore</a>
    </div>

    <div class="profile-hero">
        <div>
            <span class="profile-name">{name}</span>
            <span class="profile-ticker">{ticker}</span>
            {f'<span class="profile-infra">{infra}</span>' if infra else ''}
            <div class="profile-tags">{sector_html}</div>
        </div>
        <div class="profile-price-block">
            <span class="profile-price">{fmt_usd(price)}</span>
            <div class="profile-changes">{"".join(changes)}</div>
            {mvrv_html}
        </div>
    </div>

    {f'<div class="metrics-grid">{"".join(metric_cards)}</div>' if metric_cards else ''}

    <div class="profile-section">
        <div class="profile-section-header">
            <div class="profile-section-title">Charts</div>
            <div class="tf-selector">{tf_btns}</div>
        </div>
        {charts_html if charts_html else '<p class="chart-empty">Chart data is still loading...</p>'}
    </div>
    """
    return page_shell(f"{name} ({ticker})", body)


# ================================================================
# COMPARE PAGE
# ================================================================

def render_compare_page(tokens: list) -> str:
    if not tokens:
        body = """
        <h1 class="page-title">Compare Tokens</h1>
        <p class="page-subtitle">Side-by-side on-chain comparison</p>
        <p class="chart-empty">Usage: /compare?tokens=bitcoin,ethereum,solana</p>
        """
        return page_shell("Compare", body, active_nav="compare")

    presets = [
        ("BTC vs ETH", "bitcoin,ethereum"),
        ("L1 Chains", "bitcoin,ethereum,solana,cardano,avalanche"),
        ("DeFi", "aave,uniswap,maker,compound,curve"),
        ("Memes", "dogecoin,shiba-inu,pepe,bonk"),
        ("L2s", "polygon,immutable-x,stacks,mantle"),
    ]
    chips = "".join(f'<a href="/compare?tokens={slugs}" class="compare-chip">{label}</a>' for label, slugs in presets)

    metric_keys = [
        ("price_usd", "Price"), ("marketcap_usd", "Market Cap"),
        ("volume_usd", "Volume 24h"), ("mvrv_usd", "MVRV"),
        ("nvt", "NVT"), ("daily_active_addresses", "Active Addresses"),
        ("dev_activity", "Dev Activity"), ("exchange_balance", "Exchange Balance"),
    ]
    comp_table = comparison_table(tokens, metric_keys)

    from .svg_charts import COLORS
    overlay_charts = []
    for metric_key, title, show_area in [
        ("price_usd", "Price Comparison", True),
        ("mvrv_usd", "MVRV Comparison", False),
        ("daily_active_addresses", "Active Addresses", False),
        ("volume_usd", "Volume Comparison", False),
    ]:
        series = []
        for i, t in enumerate(tokens):
            data = t.get("metrics", {}).get(metric_key, {}).get("data", [])
            if data:
                series.append({
                    "label": t.get("name", t.get("slug", "")),
                    "data": data,
                    "color": COLORS[i % len(COLORS)],
                })
        if series:
            overlay_charts.append(line_chart_svg(
                series, width=720, height=280, title=title,
                metric_key=metric_key, show_area=show_area and len(series) == 1,
                show_min_max=False,
            ))

    body = f"""
    <h1 class="page-title">Compare Tokens</h1>
    <p class="page-subtitle">Side-by-side on-chain comparison</p>
    <div class="compare-bar">
        <span class="compare-bar-label">Quick:</span>
        {chips}
    </div>
    <div class="section">
        <div class="section-title">Metrics</div>
        {comp_table}
    </div>
    <div class="section">
        <div class="section-title">Charts</div>
        {"".join(f'<div class="chart-wrap">{c}</div>' for c in overlay_charts) if overlay_charts else '<p class="chart-empty">Not enough data yet.</p>'}
    </div>
    """
    return page_shell("Compare", body, active_nav="compare")


# ================================================================
# SCREENER PAGE
# ================================================================

def render_screener_page(
    tokens: list, tier: str = "all",
    min_change: float = None, max_change: float = None,
    sort_by: str = "marketcap_usd", order: str = "desc",
    sector: str = "all", category: str = "all",
    sectors: dict = None, categories: dict = None,
    search: str = "",
) -> str:
    _sectors = sectors or {}
    _categories = categories or {}

    # Build query string base for filter links
    def _qs(**overrides):
        params = {"tier": tier, "sort": sort_by, "order": order, "sector": sector, "category": category}
        params.update(overrides)
        return "&".join(f"{k}={v}" for k, v in params.items() if v not in ("all", None, -999, 999) or k in ("tier",))

    tiers = [
        ("all", "All"), ("mega", "Mega >$100B"), ("large", "Large $10B+"),
        ("mid", "Mid $1B+"), ("small", "Small $100M+"), ("micro", "Micro <$100M"),
    ]
    tier_btns = "".join(
        f'<a href="/screener?{_qs(tier=key)}" '
        f'class="filter-btn{" active" if key == tier else ""}">{label}</a>'
        for key, label in tiers
    )

    # Sector filter
    sector_btns = f'<a href="/screener?{_qs(sector="all", category="all")}" class="filter-btn{" active" if sector == "all" else ""}">All</a>'
    for key in ["l1", "l2", "defi", "stablecoin", "exchange", "meme", "ai", "gaming", "infrastructure", "oracle", "privacy", "storage", "social", "rwa", "other"]:
        label = _sectors.get(key, key.title())
        sector_btns += f'<a href="/screener?{_qs(sector=key, category="all")}" class="filter-btn{" active" if key == sector else ""}">{_esc(label)}</a>'

    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        arrow = " &darr;" if sort_by == col and order == "desc" else " &uarr;" if sort_by == col else ""
        return f'<a href="/screener?{_qs(sort=col, order=new_order)}" class="sort-link">{label}{arrow}</a>'

    rows = []
    for i, t in enumerate(tokens[:200]):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        sec = t.get("sector", "other")
        cat = t.get("category", "other")
        sec_label = _sectors.get(sec, sec.replace("_", " ").title())
        cat_label = _categories.get(cat, cat.replace("_", " ").title())
        spark = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark, width=80, height=24) if spark else "&mdash;"
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-tag hide-mobile"><span class="sector-tag sector-{sec}">{_esc(sec_label)}</span></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-spark hide-mobile">{spark_html}</td>
            <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
            <td class="col-num hide-mobile">{fmt_usd(t.get("volume_usd"))}</td>
            <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
            <td class="col-tag hide-mobile">{zone_html}</td>
        </tr>""")

    search_note = f' matching "{_esc(search)}"' if search else ""
    body = f"""
    <h1 class="page-title">Screener</h1>
    <p class="page-subtitle">Filter and sort {len(tokens)} tokens{search_note}</p>
    <form class="search-bar" action="/screener" method="get">
        <input type="text" name="q" value="{_esc(search)}" placeholder="Search tokens..." class="search-input" autocomplete="off">
        <button type="submit" class="search-btn">Search</button>
        <input type="hidden" name="tier" value="{_esc(tier)}">
        <input type="hidden" name="sort" value="{_esc(sort_by)}">
        <input type="hidden" name="order" value="{_esc(order)}">
        {f'<input type="hidden" name="sector" value="{_esc(sector)}">' if sector != "all" else ""}
    </form>
    <div class="filter-bar">
        <div class="filter-group"><span class="filter-label">Tier:</span>{tier_btns}</div>
    </div>
    <div class="filter-bar">
        <div class="filter-group"><span class="filter-label">Sector:</span>{sector_btns}</div>
    </div>
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th><th>Name</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">{sort_link("price_usd", "Price")}</th>
                <th class="col-num">{sort_link("price_usd_change", "24h")}</th>
                <th class="col-spark hide-mobile">7d</th>
                <th class="col-num">{sort_link("marketcap_usd", "Mkt Cap")}</th>
                <th class="col-num hide-mobile">{sort_link("volume_usd", "Volume")}</th>
                <th class="col-num hide-mobile">{sort_link("mvrv_usd", "MVRV")}</th>
                <th class="col-tag hide-mobile">Zone</th>
            </tr></thead>
            <tbody>{"".join(rows) if rows else '<tr><td colspan="10" class="empty-cell">No tokens match.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return page_shell("Screener", body, active_nav="screener")


# ================================================================
# VALUATION PAGE
# ================================================================

def render_valuation_page(tokens: list) -> str:
    zone_counts = {}
    for t in tokens:
        mvrv = t.get("mvrv_usd")
        if mvrv is not None:
            z = mvrv_zone(mvrv)
            zone_counts[z[0]] = zone_counts.get(z[0], 0) + 1

    legend = "".join(
        f'<span class="legend-item"><span class="zone {cls}">{label}</span> {zone_counts.get(label, 0)}</span>'
        for label, cls in [
            ("Deep Value", "zone-extreme-low"), ("Undervalued", "zone-undervalued"),
            ("Fair Value", "zone-fair"), ("Elevated", "zone-fair-high"),
            ("Overvalued", "zone-overvalued"), ("Euphoria", "zone-extreme-high"),
        ]
    )

    rows = []
    for i, t in enumerate(tokens):
        mvrv = t.get("mvrv_usd")
        if mvrv is None:
            continue
        slug = t.get("slug", "")
        zone_label, zone_css, _ = mvrv_zone(mvrv)
        bar_pct = min(100, max(0, mvrv / 4 * 100))
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num bold">{mvrv:.2f}</td>
            <td class="col-tag"><span class="zone {zone_css}">{zone_label}</span></td>
            <td class="hide-mobile" style="min-width:120px"><div class="mini-bar-track"><div class="mini-bar-fill" style="width:{bar_pct:.0f}%"></div></div></td>
        </tr>""")

    body = f"""
    <h1 class="page-title">Valuation Scanner</h1>
    <p class="page-subtitle">MVRV zones across {len(tokens)} tokens</p>
    <div class="val-legend">{legend}</div>
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th><th>Name</th>
                <th class="col-num">Price</th><th class="col-num">MVRV</th>
                <th class="col-tag">Zone</th><th class="hide-mobile">Bar</th>
            </tr></thead>
            <tbody>{"".join(rows) if rows else '<tr><td colspan="6" class="empty-cell">MVRV data not yet available.</td></tr>'}</tbody>
        </table>
    </div>
    """
    return page_shell("Valuation", body, active_nav="valuation")


# ================================================================
# SYNC PAGE
# ================================================================

def render_sync_page(pull_status: dict, cache_stats: dict, client_stats: dict) -> str:
    status = pull_status.get("status", "unknown")
    cs = cache_stats or {}
    cl = client_stats or {}

    phases = [
        ("Discovery", "phase1_discovery"),
        ("Quick Load", "phase1_pulling"),
        ("Universe Pull", "phase2_universe"),
        ("Deep Pull", "phase3_deep"),
        ("Ready", "ready"),
    ]
    current_idx = -1
    for i, (_, key) in enumerate(phases):
        if key in status:
            current_idx = i
    if status == "ready":
        current_idx = len(phases) - 1

    pipeline_html = ""
    for i, (label, _) in enumerate(phases):
        cls = "done" if (status == "ready" or i < current_idx) else ("active" if i == current_idx else "")
        pipeline_html += f'<span class="sync-step {cls}"><span class="sync-step-dot"></span>{label}</span>'

    stats_grid = f"""
    <div class="sync-stats-grid">
        <div class="sync-stat"><div class="sync-stat-label">Projects</div><div class="sync-stat-value">{fmt_num(cs.get("projects_cached", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Data Points</div><div class="sync-stat-value">{fmt_num(cs.get("total_data_points_pulled", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Timeseries</div><div class="sync-stat-value">{fmt_num(cs.get("timeseries_rows", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">DB Size</div><div class="sync-stat-value">{cs.get("db_size_mb", 0):.0f} MB</div></div>
        <div class="sync-stat"><div class="sync-stat-label">API Requests</div><div class="sync-stat-value">{fmt_num(cl.get("total_requests", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Successful</div><div class="sync-stat-value">{fmt_num(cs.get("successful_pulls", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Errors</div><div class="sync-stat-value">{cl.get("errors", 0)}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Cache Hits</div><div class="sync-stat-value">{fmt_num(cl.get("cache_hits", 0))}</div></div>
    </div>"""

    error_html = ""
    last_err = cl.get("last_error")
    if last_err:
        error_html = f'<div class="sync-error"><strong>Last Error:</strong> {_esc(str(last_err)[:300])}</div>'

    body = f"""
    <h1 class="page-title">Data Sync</h1>
    <p class="page-subtitle">Pipeline status and statistics</p>
    <div class="sync-pipeline">{pipeline_html}</div>
    {stats_grid}
    {error_html}
    <p class="sync-hint">Snapshot — refresh for latest.</p>
    """
    return page_shell("Sync", body, active_nav="sync")


# ================================================================
# WATCHLIST PAGE
# ================================================================

def render_watchlist_page(tokens: list, slug_list: list = None) -> str:
    slug_list = slug_list or []
    slugs_str = ",".join(slug_list)

    parts = []
    parts.append(f"""
    <h1 class="page-title">Watchlist</h1>
    <p class="page-subtitle">Track your favorite tokens &middot; Bookmark this URL to save your list</p>""")

    # Add token form
    parts.append(f"""
    <form class="search-bar watchlist-form" action="/watchlist" method="get">
        <input type="text" name="tokens" value="{_esc(slugs_str)}" placeholder="Enter slugs: bitcoin,ethereum,solana..." class="search-input" autocomplete="off">
        <button type="submit" class="search-btn">Update</button>
    </form>""")

    # Preset watchlists
    presets = [
        ("Top 10", "bitcoin,ethereum,tether,xrp,binance-coin,solana,cardano,dogecoin,tron,avalanche"),
        ("DeFi Blue Chips", "aave,uniswap,maker,compound,curve-dao-token,lido-dao"),
        ("L1 Chains", "bitcoin,ethereum,solana,cardano,avalanche,near-protocol,sui,aptos"),
        ("L2s", "polygon,arbitrum,optimism,starknet,immutable-x,mantle"),
        ("Memes", "dogecoin,shiba-inu,pepe,bonk,floki,dogwifhat"),
        ("AI Tokens", "fetch,singularitynet,render-token,bittensor,akash-network"),
    ]
    chips = "".join(f'<a href="/watchlist?tokens={slugs}" class="compare-chip">{label}</a>' for label, slugs in presets)
    parts.append(f'<div class="compare-bar"><span class="compare-bar-label">Presets:</span>{chips}</div>')

    if not tokens:
        parts.append('<div class="empty-state"><h2>No tokens selected</h2><p>Add token slugs above or pick a preset watchlist.</p></div>')
        return page_shell("Watchlist", "\n".join(parts), active_nav="watchlist")

    # Summary stats
    total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
    avg_change = sum(t.get("price_usd_change") or 0 for t in tokens) / len(tokens) if tokens else 0
    mvrv_vals = [t.get("mvrv_usd") for t in tokens if t.get("mvrv_usd") is not None]
    avg_mvrv = sum(mvrv_vals) / len(mvrv_vals) if mvrv_vals else None

    parts.append(f"""
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-label">Combined MCap</div>
            <div class="stat-value">{fmt_usd(total_mcap)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg 24h Change</div>
            <div class="stat-value {css_class(avg_change)}">{fmt_pct(avg_change)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg MVRV</div>
            <div class="stat-value">{f"{avg_mvrv:.2f}" if avg_mvrv else "&mdash;"}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Tokens</div>
            <div class="stat-value">{len(tokens)}</div>
        </div>
    </div>""")

    # Token table
    rows = ""
    for i, t in enumerate(tokens):
        slug_t = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv_t = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv_t)[1]}">{mvrv_zone(mvrv_t)[0]}</span>' if mvrv_t else "&mdash;"
        spark = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark, width=80, height=24) if spark else "&mdash;"
        sec = t.get("sector", "other")
        sec_label = sec.replace("_", " ").title()
        rows += f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug_t}" class="token-link"><strong>{_esc(t.get("name", slug_t))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-tag hide-mobile"><a href="/explore?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-spark hide-mobile">{spark_html}</td>
            <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
            <td class="col-num hide-mobile">{fmt_usd(t.get("volume_usd"))}</td>
            <td class="col-num hide-mobile">{f"{mvrv_t:.2f}" if mvrv_t else "&mdash;"}</td>
            <td class="col-tag hide-mobile">{zone_html}</td>
        </tr>"""

    parts.append(f"""
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th><th>Name</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">Price</th>
                <th class="col-num">24h</th>
                <th class="col-spark hide-mobile">7d</th>
                <th class="col-num">Mkt Cap</th>
                <th class="col-num hide-mobile">Volume</th>
                <th class="col-num hide-mobile">MVRV</th>
                <th class="col-tag hide-mobile">Zone</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>""")

    # Compare link
    if len(slug_list) >= 2:
        parts.append(f'<div class="card-footer" style="margin-top:12px"><a href="/compare?tokens={_esc(slugs_str)}">Compare these tokens side-by-side &rarr;</a></div>')

    return page_shell("Watchlist", "\n".join(parts), active_nav="watchlist")
