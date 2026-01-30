"""
Server-side HTML renderer — pure HTML, zero JavaScript.

Every page is a complete HTML document rendered on the server.
Navigation is via <a> links. Charts are inline SVG.

Design philosophy: Daily economy briefing, not a trading terminal.
Open it once, understand the entire crypto economy in 30 seconds.
"""

import html as html_mod
from datetime import datetime, timedelta
from typing import Optional

from .svg_charts import (
    sparkline_svg, line_chart_svg, chart_panel, comparison_table,
    market_heatmap_svg, dominance_bar_svg, donut_chart_svg,
    sentiment_gauge_svg, mini_trend_svg,
    scatter_plot_svg, bar_chart_svg, THESIS_COLORS,
)


# ================================================================
# FORMAT HELPERS
# ================================================================

def _relative_time(iso_str: str) -> str:
    """Convert ISO datetime string to relative time like '3m ago', '2h ago'."""
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


def _breadcrumbs(*crumbs: tuple) -> str:
    """Generate a breadcrumb trail.  Each crumb is (label, url) or just (label,) for the current page."""
    items = ['<a href="/" class="bc-link">Home</a>']
    for c in crumbs:
        if len(c) == 2:
            items.append(f'<a href="{c[1]}" class="bc-link">{_esc(c[0])}</a>')
        else:
            items.append(f'<span class="bc-current">{_esc(c[0])}</span>')
    sep = ' <span class="bc-sep">›</span> '
    return f'<nav class="breadcrumbs" aria-label="Breadcrumb">{sep.join(items)}</nav>'


# ================================================================
# PAGE SHELL
# ================================================================

# Module-level ticker data getter — set by api.py at startup
_ticker_data_fn = None
_current_theme = "auto"
_freshness_fn = None

def set_ticker_data_fn(fn):
    """Set the function that provides ticker data for the header strip."""
    global _ticker_data_fn
    _ticker_data_fn = fn

def set_theme(theme: str):
    """Set the current theme for rendering."""
    global _current_theme
    _current_theme = theme if theme in ("dark", "light") else "auto"

def set_freshness_fn(fn):
    """Set the function that returns the last sync time string."""
    global _freshness_fn
    _freshness_fn = fn


def _freshness_badge() -> str:
    """Return a small badge showing data freshness."""
    if not _freshness_fn:
        return ""
    try:
        info = _freshness_fn()
        if not info:
            return ""
        status = info.get("status", "unknown")
        last_pull = info.get("last_pull", "")
        if status in ("pulling_phase1", "pulling_phase2"):
            return '<a href="/sync" class="freshness-badge syncing" title="Data sync in progress">&#8634; Syncing</a>'
        if last_pull:
            rel = _relative_time(last_pull)
            return f'<a href="/sync" class="freshness-badge" title="Last sync: {_esc(last_pull)}">&#10003; {rel}</a>'
        return '<a href="/sync" class="freshness-badge stale" title="No data yet">&#9679; Loading</a>'
    except Exception:
        return ""


def page_shell(title: str, body: str, active_nav: str = "", ticker_data: list = None, auto_refresh: int = 0, theme: str = "auto", og_description: str = "", canonical: str = "") -> str:
    nav_items = [
        ("briefing", "/", "Briefing"),
        ("explore", "/explore", "Explore"),
        ("sectors", "/sectors", "Sectors"),
        ("screener", "/screener", "Screener"),
        ("insights", "/insights", "Insights"),
        ("valuation", "/valuation", "Valuation"),
        ("developers", "/developers", "Developers"),
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

    effective_theme = theme if theme != "auto" else _current_theme
    html_class = f' class="{effective_theme}"' if effective_theme in ('dark', 'light') else ''
    return f"""<!DOCTYPE html>
<html lang="en"{html_class}>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(title)} — Onchain Pulse</title>
    {f'<meta http-equiv="refresh" content="{auto_refresh}">' if auto_refresh > 0 else ''}
    <meta name="description" content="{_esc(og_description) if og_description else 'Real-time on-chain crypto analytics powered by Santiment. MVRV, active addresses, exchange flows, dev activity across 3500+ tokens.'}">
    <meta property="og:title" content="{_esc(title)} — Onchain Pulse">
    <meta property="og:description" content="{_esc(og_description) if og_description else 'On-chain crypto analytics dashboard. MVRV zones, network health, smart money signals.'}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary">
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%230F1419'/><text x='16' y='22' text-anchor='middle' fill='%2310B981' font-family='sans-serif' font-weight='900' font-size='18'>P</text></svg>">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/dashboard.css">
    {f'<link rel="canonical" href="{_esc(canonical)}">' if canonical else ''}
</head>
<body id="top">
    <a href="#main-content" class="skip-link">Skip to main content</a>
    {ticker_html}
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">Onchain<span>Pulse</span></a>
            <input type="checkbox" id="nav-toggle" class="nav-toggle" hidden>
            <label for="nav-toggle" class="nav-toggle-label"><span></span></label>
            <nav class="header-nav" aria-label="Main navigation">{nav_html}</nav>
            <div class="header-right">
                {_freshness_badge()}
                <a href="?theme=dark" class="theme-toggle" title="Dark mode">&#9790;</a>
                <a href="?theme=light" class="theme-toggle" title="Light mode">&#9788;</a>
            </div>
        </div>
    </header>
    <main class="main" id="main-content" role="main">{body}</main>
    <footer class="footer" role="contentinfo">
        <div class="footer-inner">
            <div class="footer-links">
                <a href="/">Briefing</a>
                <a href="/explore">Explore</a>
                <a href="/sectors">Sectors</a>
                <a href="/screener">Screener</a>
                <a href="/insights">Insights</a>
                <a href="/valuation">Valuation</a>
                <a href="/compare?tokens=bitcoin,ethereum,solana">Compare</a>
                <a href="/watchlist?tokens=bitcoin,ethereum,solana">Watchlist</a>
                <a href="/sync">Sync Status</a>
                <a href="/glossary">Glossary</a>
                <a href="/api">API</a>
            </div>
            <div class="footer-meta">
                On-chain data via <strong>Santiment</strong>. Refreshed daily. Not financial advice.
                <br><span class="footer-timestamp">Rendered {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC</span>
            </div>
            <a href="#top" class="scroll-top" aria-label="Back to top">&uarr; Top</a>
        </div>
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

    # ── Table of Contents ──
    toc_items = [
        ("regime", "Market Regime"),
        ("valuation", "Valuation"),
        ("sectors", "Sectors"),
        ("health", "Network Health"),
        ("signals", "Signals"),
        ("dominance", "Dominance"),
        ("movers", "Movers"),
        ("top-metrics", "Top by Metric"),
    ]
    toc_links = "".join(f'<a href="#{tid}" class="toc-link">{tlabel}</a>' for tid, tlabel in toc_items)
    parts.append(f'<nav class="briefing-toc">{toc_links}</nav>')

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

    # Build narrative summary
    narrative_parts = []
    if breadth_pct >= 60:
        narrative_parts.append(f"Broad strength — {breadth_pct:.0f}% of tokens are up over 24h")
    elif breadth_pct <= 40:
        narrative_parts.append(f"Broad weakness — only {breadth_pct:.0f}% of tokens are up over 24h")
    else:
        narrative_parts.append(f"Mixed market — {breadth_pct:.0f}% of tokens rising")

    vol_conc = b.get("vol_concentration_top10", 0)
    if vol_conc > 70:
        narrative_parts.append(f"Volume heavily concentrated in top 10 ({vol_conc:.0f}%)")
    elif vol_conc < 40:
        narrative_parts.append(f"Volume broadly distributed across the market ({vol_conc:.0f}% in top 10)")

    if avg_mvrv is not None:
        if avg_mvrv < 1.0:
            narrative_parts.append("Aggregate MVRV below 1.0 suggests undervaluation relative to realized value")
        elif avg_mvrv > 2.5:
            narrative_parts.append("Elevated MVRV signals potential overheating — historically a distribution zone")

    regime_narrative = ". ".join(narrative_parts) + "." if narrative_parts else ""

    # Composite Market Score (0-100, fear→greed style)
    score_parts = []
    if avg_mvrv is not None:
        # MVRV component: 0-4 range mapped to 0-100 (inverted — low MVRV = fear)
        mvrv_score = min(100, max(0, (avg_mvrv / 3.0) * 100))
        score_parts.append(mvrv_score)
    if total_bd > 0:
        score_parts.append(breadth_pct)
    if vol_conc > 0:
        # High concentration = lower score
        score_parts.append(max(0, 100 - vol_conc))
    composite_score = int(sum(score_parts) / len(score_parts)) if score_parts else 50
    if composite_score >= 75:
        score_label, score_cls = "Extreme Greed", "score-greed"
    elif composite_score >= 55:
        score_label, score_cls = "Greed", "score-greed-mild"
    elif composite_score >= 45:
        score_label, score_cls = "Neutral", "score-neutral"
    elif composite_score >= 25:
        score_label, score_cls = "Fear", "score-fear-mild"
    else:
        score_label, score_cls = "Extreme Fear", "score-fear"

    score_html = f"""
        <div class="composite-score">
            <div class="composite-score-num {score_cls}">{composite_score}</div>
            <div class="composite-score-label">{score_label}</div>
            <div class="composite-score-bar">
                <div class="composite-score-fill" style="left:{composite_score}%"></div>
            </div>
        </div>"""

    parts.append(f"""
    <section class="card regime-card" id="regime">
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
        {f'<p class="regime-narrative">{regime_narrative}</p>' if regime_narrative else ''}
        {score_html}
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

    # MVRV heatmap tiles (top 30 tokens)
    all_tokens = b.get("all_tokens", [])
    mvrv_tiles = ""
    mvrv_tokens = [t for t in all_tokens if t.get("mvrv_usd") is not None][:30]
    for t in mvrv_tokens:
        mv = t.get("mvrv_usd", 0)
        zl, zc, _ = mvrv_zone(mv)
        mvrv_tiles += (
            f'<a href="/token/{t.get("slug","")}" class="mvrv-tile {zc}" title="{_esc(t.get("name",""))}: MVRV {mv:.2f} ({zl})">'
            f'{_esc(t.get("ticker","")[:5])}'
            f'</a>'
        )
    mvrv_heatmap = f'<div class="mvrv-heatmap">{mvrv_tiles}</div>' if mvrv_tiles else ""

    # Valuation opportunity score: weighted by zone
    # Deep Value=5, Undervalued=4, Fair=3, Elevated=2, Overvalued=1, Euphoria=0
    zone_weights = {"deep_value": 5, "undervalued": 4, "fair": 3, "elevated": 2, "overvalued": 1, "euphoria": 0}
    weighted_sum = sum(zones.get(k, 0) * w for k, w in zone_weights.items())
    val_score = weighted_sum / max(zone_total, 1)
    if val_score >= 3.5:
        val_verdict = "Strong opportunity"
        val_cls = "up"
    elif val_score >= 2.5:
        val_verdict = "Moderate opportunity"
        val_cls = "muted"
    else:
        val_verdict = "Elevated valuations"
        val_cls = "down"

    parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title" id="valuation">Valuation Landscape</h2>
            <span class="card-badge">{zone_total} tokens with MVRV data</span>
        </div>
        <div class="valuation-score-row">
            <div class="valuation-score">
                <span class="valuation-score-num">{val_score:.1f}</span>
                <span class="valuation-score-max">/ 5.0</span>
            </div>
            <div class="valuation-score-bar">
                <div class="valuation-score-fill" style="width:{val_score/5*100:.0f}%"></div>
            </div>
            <span class="valuation-verdict {val_cls}">{val_verdict}</span>
        </div>
        <div class="zone-distribution">{zone_bars}</div>
        {mvrv_heatmap}
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
            <h2 class="card-title" id="sectors">Sector Breakdown</h2>
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

        # Network health narrative
        health_notes = []
        if daa_ch is not None:
            if daa_ch > 5:
                health_notes.append(f"Active addresses growing ({fmt_pct(daa_ch)} avg) — rising user engagement")
            elif daa_ch < -5:
                health_notes.append(f"Active addresses declining ({fmt_pct(daa_ch)} avg) — reduced on-chain activity")
        if dev_ch is not None:
            if dev_ch > 5:
                health_notes.append(f"Developer activity trending up ({fmt_pct(dev_ch)} avg)")
            elif dev_ch < -5:
                health_notes.append(f"Developer activity declining ({fmt_pct(dev_ch)} avg)")
        if accum > distrib and accum > 5:
            health_notes.append(f"Net accumulation pattern — {accum} tokens seeing exchange outflows")
        elif distrib > accum and distrib > 5:
            health_notes.append(f"Distribution pressure — {distrib} tokens seeing exchange inflows")
        health_narrative = ". ".join(health_notes) + "." if health_notes else ""

        parts.append(f"""
    <section class="card">
        <div class="card-header">
            <h2 class="card-title" id="health">Network Health</h2>
            <span class="card-badge">Top 20 bellwether tokens · 90 day trends</span>
        </div>
        <div class="health-grid">{health_cards}</div>
        {flow_html}
        {f'<p class="health-narrative">{health_narrative}</p>' if health_narrative else ''}
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
            <h2 class="card-title" id="signals">On-Chain Signals</h2>
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
            <div class="card-header"><h2 class="card-title" id="dominance">Market Dominance</h2></div>
            <div class="dominance-donut-wrap">{donut_chart_svg(dom)}</div>
            <div class="dominance-wrap">{dominance_bar_svg(dom)}</div>
        </section>
        <section class="card">
            <div class="card-header">
                <h2 class="card-title">24h Heatmap</h2>
            </div>
            <div class="heatmap-wrap">{market_heatmap_svg(all_tokens, max_tokens=40)}</div>
            <div class="heatmap-legend">
                <span class="heatmap-legend-item" style="background:#DC2626;color:#fff">&le;-10%</span>
                <span class="heatmap-legend-item" style="background:#F87171;color:#fff">-5%</span>
                <span class="heatmap-legend-item" style="background:#FCA5A5">-1%</span>
                <span class="heatmap-legend-item" style="background:#E5E7EB">0%</span>
                <span class="heatmap-legend-item" style="background:#86EFAC">+1%</span>
                <span class="heatmap-legend-item" style="background:#34D399;color:#fff">+5%</span>
                <span class="heatmap-legend-item" style="background:#059669;color:#fff">&ge;+10%</span>
            </div>
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
                spark = t.get("sparkline_7d", [])
                spark_html = sparkline_svg(spark, width=60, height=20) if spark and len(spark) >= 2 else ""
                rows += (
                    f'<a href="/token/{slug}" class="mover-row">'
                    f'<span class="mover-rank">{i+1}</span>'
                    f'<span class="mover-name">{_esc(t.get("name", slug)[:18])} '
                    f'<span class="ticker">{_esc(t.get("ticker", ""))}</span></span>'
                    f'<span class="mover-spark">{spark_html}</span>'
                    f'<span class="mover-price">{fmt_usd(t.get("price_usd"))}</span>'
                    f'<span class="mover-pct {css_class(pct)}">{fmt_pct(pct)}</span>'
                    f'</a>'
                )
            return rows

        parts.append(f"""
    <div class="two-col" id="movers">
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
        parts.append(f'<div class="three-col" id="top-metrics">{"".join(cols)}</div>')

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

    return page_shell("Daily Briefing", "\n".join(parts), active_nav="briefing", auto_refresh=300)


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
    parts.append(_breadcrumbs(("Insights",)))
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
    sort_by: str = "marketcap_usd",
    order: str = "desc",
    view: str = "full",
) -> str:
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    briefing = briefing or {}

    parts = []
    sector_label = (sectors or {}).get(sector, "All Sectors") if sector != "all" else ""
    search_note = f' matching "{_esc(search)}"' if search else ""
    subtitle = f"{total} tokens" + (f" in {sector_label}" if sector_label else "") + search_note + " ranked by market cap"
    bc_crumbs = [("Explore",)] if sector == "all" else [("Explore", "/explore"), (sector_label,)]
    parts.append(_breadcrumbs(*bc_crumbs))
    csv_qs_parts = []
    if sector != "all":
        csv_qs_parts.append(f"sector={sector}")
    if category != "all":
        csv_qs_parts.append(f"category={category}")
    if search:
        csv_qs_parts.append(f"q={_esc(search)}")
    if sort_by != "marketcap_usd":
        csv_qs_parts.append(f"sort={sort_by}")
    if order != "desc":
        csv_qs_parts.append(f"order={order}")
    csv_url = "/explore/csv" + ("?" + "&".join(csv_qs_parts) if csv_qs_parts else "")
    compact = view == "compact"
    view_qs_base = "&".join(csv_qs_parts)
    full_url = "/explore?" + (view_qs_base + "&" if view_qs_base else "") + "view=full" + f"&per_page={per_page}"
    compact_url = "/explore?" + (view_qs_base + "&" if view_qs_base else "") + "view=compact" + f"&per_page={per_page}"
    parts.append(f"""
    <div class="page-title-row">
        <div>
            <h1 class="page-title">Explore</h1>
            <p class="page-subtitle">{subtitle}</p>
        </div>
        <div class="page-title-actions">
            <div class="view-toggle">
                <a href="{full_url}" class="view-toggle-btn{' active' if not compact else ''}" title="Full view">&#9776;</a>
                <a href="{compact_url}" class="view-toggle-btn{' active' if compact else ''}" title="Compact view">&#9783;</a>
            </div>
            <a href="{csv_url}" class="export-btn" download>&#8681; Export CSV</a>
        </div>
    </div>""")

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

    # Search bar with popular suggestions
    popular = [("BTC", "bitcoin"), ("ETH", "ethereum"), ("SOL", "solana"),
               ("ADA", "cardano"), ("DOT", "polkadot"), ("AVAX", "avalanche"),
               ("LINK", "chainlink"), ("UNI", "uniswap"), ("AAVE", "aave")]
    suggestions = "".join(f'<a href="/token/{slug}" class="search-suggestion">{ticker}</a>' for ticker, slug in popular)
    parts.append(f"""
    <form class="search-bar" action="/explore" method="get" role="search" aria-label="Search tokens">
        <input type="text" name="q" value="{_esc(search)}" placeholder="Search by name, ticker, or slug..." class="search-input" autocomplete="off">
        <button type="submit" class="search-btn">Search</button>
        {f'<input type="hidden" name="sector" value="{_esc(sector)}">' if sector != "all" else ""}
        <input type="hidden" name="per_page" value="{per_page}">
    </form>
    <div class="search-suggestions"><span class="search-suggestions-label">Popular:</span>{suggestions}</div>""")

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

    # Sort link helper
    def _sort_link(field, label):
        new_order = "asc" if sort_by == field and order == "desc" else "desc"
        arrow = ""
        if sort_by == field:
            arrow = " &#9660;" if order == "desc" else " &#9650;"
        qs = f"sort={field}&order={new_order}&per_page={per_page}"
        if sector != "all":
            qs += f"&sector={sector}"
        if search:
            qs += f"&q={_esc(search)}"
        return f'<a href="/explore?{qs}" class="sort-link">{label}{arrow}</a>'

    # Table
    table_class = "data-table compact-table" if compact else "data-table"
    parts.append(f"""
    <div class="table-wrap">
        <table class="{table_class}">
            <thead><tr>
                <th class="col-rank">#</th>
                <th>{_sort_link("name", "Name")}</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">{_sort_link("price_usd", "Price")}</th>
                <th class="col-num">{_sort_link("price_usd_change", "24h")}</th>
                {"" if compact else f'<th class="col-spark hide-mobile">7d</th>'}
                <th class="col-num">{_sort_link("marketcap_usd", "Mkt Cap")}</th>
                {"" if compact else f'<th class="col-num hide-mobile">{_sort_link("volume_usd", "Volume")}</th>'}
                <th class="col-num hide-mobile">{_sort_link("mvrv_usd", "MVRV")}</th>
                <th class="col-tag hide-mobile">Zone</th>
            </tr></thead>
            <tbody>""")

    col_count = 8 if compact else 10
    if not tokens:
        parts.append(f'<tr><td colspan="{col_count}" class="empty-cell">Data is being pulled. Refresh shortly.</td></tr>')
    else:
        _sector_labels = sectors or {}
        for i, t in enumerate(tokens):
            rank = start + i + 1
            slug = t.get("slug", "")
            pct = t.get("price_usd_change")
            mvrv = t.get("mvrv_usd")
            zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv is not None else "&mdash;"
            sec = t.get("sector", "other")
            sec_label = _sector_labels.get(sec, sec.replace("_", " ").title())
            if compact:
                parts.append(f"""<tr>
                <td class="col-rank">{rank}</td>
                <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
                <td class="col-tag hide-mobile"><a href="/explore?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a></td>
                <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
                <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
                <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
                <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
                <td class="col-tag hide-mobile">{zone_html}</td>
            </tr>""")
            else:
                spark = t.get("sparkline_7d", [])
                spark_html = sparkline_svg(spark, width=80, height=24) if spark else "&mdash;"
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

    # Page size selector + Pagination
    base_qs_parts = []
    if sector != "all":
        base_qs_parts.append(f"sector={sector}")
    if category != "all":
        base_qs_parts.append(f"category={category}")
    if search:
        base_qs_parts.append(f"q={_esc(search)}")
    if sort_by != "marketcap_usd":
        base_qs_parts.append(f"sort={sort_by}")
    if order != "desc":
        base_qs_parts.append(f"order={order}")
    if compact:
        base_qs_parts.append("view=compact")
    base_qs = "&".join(base_qs_parts)

    size_options = ""
    for sz in [25, 50, 100, 200]:
        active = " active" if sz == per_page else ""
        sz_qs = f"per_page={sz}" + (f"&{base_qs}" if base_qs else "")
        size_options += f'<a href="/explore?{sz_qs}" class="page-size-btn{active}">{sz}</a>'
    parts.append(f'<div class="page-controls"><div class="page-size-selector"><span class="page-size-label">Show:</span>{size_options}</div>')

    if total_pages > 1:
        qs = f"per_page={per_page}" + (f"&{base_qs}" if base_qs else "")
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

    parts.append('</div>')  # close page-controls

    # Aggregate stats footer
    if tokens:
        total_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens)
        changes = [t.get("price_usd_change") for t in tokens if t.get("price_usd_change") is not None]
        avg_change = sum(changes) / len(changes) if changes else 0
        up_count = sum(1 for c in changes if c > 0)
        parts.append(f"""
    <div class="explore-footer-stats">
        <span>Page MCap: {fmt_usd(total_mcap)}</span>
        <span>Avg 24h: <span class="{css_class(avg_change)}">{fmt_pct(avg_change)}</span></span>
        <span>{up_count}/{len(changes)} up</span>
        <span>Showing {len(tokens)} of {total}</span>
    </div>""")

    return page_shell("Explore", "\n".join(parts), active_nav="explore")


# ================================================================
# TOKEN PROFILE
# ================================================================

def _render_token_description(token: dict) -> str:
    desc = token.get("description", "")
    website = token.get("website", "")
    if not desc and not website:
        return ""
    parts = []
    if desc:
        # Truncate long descriptions
        if len(desc) > 300:
            desc = desc[:297] + "..."
        parts.append(f'<p class="token-desc">{_esc(desc)}</p>')
    if website:
        parts.append(f'<a href="{_esc(website)}" class="token-website" target="_blank" rel="noopener">{_esc(website)}</a>')
    return f'<div class="token-desc-block">{"".join(parts)}</div>'


def render_token_profile(token: dict, metrics: dict, slug: str = "", timeframe: str = "all", token_info: dict = None, related_tokens: list = None, prev_token: dict = None, next_token: dict = None, mcap_rank: int = None) -> str:
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

    # Alert badges — highlight notable metric thresholds
    alerts = []
    if mvrv is not None:
        if mvrv < 0.7:
            alerts.append(("Deep Value Zone", "alert-bullish", "MVRV well below realized value"))
        elif mvrv > 3.5:
            alerts.append(("Euphoria Zone", "alert-bearish", "MVRV far above realized value — extreme caution"))
        elif mvrv > 2.5:
            alerts.append(("Overvalued", "alert-warn", "MVRV elevated — distribution risk"))
    nvt = _latest("nvt")
    if nvt is not None:
        if nvt > 150:
            alerts.append(("High NVT", "alert-warn", "Network value exceeds transaction throughput"))
        elif nvt < 20:
            alerts.append(("Low NVT", "alert-bullish", "Strong network utilization relative to value"))
    exch = _latest("exchange_balance")
    exch_ts = _data("exchange_balance")
    if exch is not None and exch_ts and len(exch_ts) >= 7:
        exch_7d = exch_ts[-7].get("value")
        if exch_7d and exch_7d > 0:
            exch_chg = (exch - exch_7d) / exch_7d * 100
            if exch_chg < -5:
                alerts.append(("Exchange Outflow", "alert-bullish", f"{exch_chg:.1f}% in 7d — accumulation signal"))
            elif exch_chg > 5:
                alerts.append(("Exchange Inflow", "alert-bearish", f"+{exch_chg:.1f}% in 7d — distribution signal"))
    alerts_html = ""
    if alerts:
        badges = "".join(f'<span class="alert-badge {cls}" title="{_esc(desc)}">{_esc(label)}</span>' for label, cls, desc in alerts)
        alerts_html = f'<div class="alert-badges">{badges}</div>'

    # Metric cards with tooltip explanations
    _metric_tips = {
        "marketcap_usd": "Total supply × current price",
        "volume_usd": "USD trading volume in the last 24 hours",
        "mvrv_usd": "Market Value to Realized Value — above 1 means holders are in profit on average",
        "nvt": "Network Value to Transactions — high = overvalued relative to usage",
        "daily_active_addresses": "Unique addresses active in the last 24h",
        "transaction_volume": "Total on-chain transaction volume in USD",
        "exchange_balance": "Tokens held on known exchange wallets — declining = accumulation",
        "dev_activity": "GitHub development activity score",
        "network_growth": "New addresses joining the network per day",
        "circulation": "Tokens that moved on-chain in the past 24h",
        "velocity": "How frequently tokens change hands — higher = more speculative",
        "mean_age": "Average age of all dollars invested — rising = HODLing",
        "whale_transaction_count_100k_usd_to_inf": "Transactions above $100K — whale activity signal",
        "social_volume_total": "Mentions across social platforms",
        "sentiment_balance_total": "Net positive vs negative social sentiment",
    }
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
        tip = _metric_tips.get(key, "")
        label_html = f'<abbr title="{_esc(tip)}" class="metric-abbr">{_esc(label)}</abbr>' if tip else _esc(label)
        # 24h delta + sparkline
        delta_html = ""
        spark_html = ""
        ts = _data(key)
        if ts and len(ts) >= 2:
            prev_val = ts[-2].get("value")
            if prev_val is not None and prev_val != 0:
                delta_pct = (latest - prev_val) / abs(prev_val) * 100
                d_cls = "up" if delta_pct > 0 else "down" if delta_pct < 0 else "muted"
                delta_html = f'<span class="metric-delta {d_cls}">{delta_pct:+.1f}%</span>'
        if ts and len(ts) >= 5:
            tail = ts[-30:] if len(ts) >= 30 else ts
            spark_color = "#10B981" if delta_html and "up" in delta_html else "#EF4444" if delta_html and "down" in delta_html else "#9CA3AF"
            spark_html = f'<div class="metric-spark">{mini_trend_svg(tail, width=80, height=22, color=spark_color)}</div>'
        metric_cards.append(f"""
        <div class="metric-card">
            <div class="metric-label">{label_html}</div>
            <div class="metric-value">{val_str}{delta_html}</div>
            {spark_html}
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
    bar_metrics = {"volume_usd", "social_volume_total", "whale_transaction_count_100k_usd_to_inf"}
    for key, title, color in chart_defs:
        data = _data(key)
        if not data or len(data) < 3:
            continue
        if key in bar_metrics:
            secondary_charts.append(bar_chart_svg(
                data, width=340, height=200, title=title, color=color, metric_key=key,
            ))
        else:
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

    _bc = _breadcrumbs(("Explore", "/explore"), (f"{name} ({ticker})",))
    prev_link = f'<a href="/token/{prev_token["slug"]}" class="token-nav-link" title="{_esc(prev_token.get("name",""))}">&larr; {_esc(prev_token.get("name","")[:20])}</a>' if prev_token else '<span></span>'
    next_link = f'<a href="/token/{next_token["slug"]}" class="token-nav-link" title="{_esc(next_token.get("name",""))}">{_esc(next_token.get("name","")[:20])} &rarr;</a>' if next_token else '<span></span>'
    body = f"""
    {_bc}
    <div class="token-quick-nav">{prev_link}{next_link}</div>

    <div class="profile-hero">
        <div>
            {f'<span class="rank-badge">#{mcap_rank}</span>' if mcap_rank else ''}
            <span class="profile-name">{name}</span>
            <span class="profile-ticker">{ticker}</span>
            {f'<span class="profile-infra">{infra}</span>' if infra else ''}
            <div class="profile-tags">{sector_html}</div>
        </div>
        <div class="profile-price-block">
            <span class="profile-price">{fmt_usd(price)}</span>
            {mini_trend_svg(_data("price_usd")[-30:], width=120, height=32, color="#0F1419") if len(_data("price_usd")) >= 5 else ""}
            <div class="profile-changes">{"".join(changes)}</div>
            {mvrv_html}
        </div>
    </div>

    {alerts_html}

    {_render_token_description(token)}

    {f'<div class="metrics-grid">{"".join(metric_cards)}</div>' if metric_cards else ''}

    <div class="profile-section">
        <div class="profile-section-header">
            <div class="profile-section-title">Charts</div>
            <div class="tf-selector">{tf_btns}</div>
        </div>
        {charts_html if charts_html else '<p class="chart-empty">Chart data is still loading...</p>'}
    </div>
    """

    # Related tokens section
    if related_tokens:
        sec = (token_info or {}).get("sector", "other")
        sec_label = sec.replace("_", " ").title()
        rel_cards = ""
        for rt in related_tokens:
            rt_pct = rt.get("price_usd_change")
            rt_cls = css_class(rt_pct)
            rel_cards += (
                f'<a href="/token/{rt["slug"]}" class="related-token-card">'
                f'<strong>{_esc(rt.get("ticker", ""))}</strong>'
                f'<span class="related-token-name">{_esc(rt.get("name", ""))}</span>'
                f'<span class="related-token-price">{fmt_usd(rt.get("price_usd"))}</span>'
                f'<span class="related-token-pct {rt_cls}">{fmt_pct(rt_pct)}</span>'
                f'</a>'
            )
        body += f"""
    <div class="profile-section">
        <div class="profile-section-title">Related — {_esc(sec_label)}</div>
        <div class="related-tokens-grid">{rel_cards}</div>
        <div class="card-footer"><a href="/explore?sector={sec}">View all {_esc(sec_label)} tokens &rarr;</a></div>
    </div>"""

    # Quick actions
    body += f"""
    <div class="profile-actions">
        <a href="/compare?tokens=bitcoin,{slug}" class="profile-action-btn">Compare with BTC</a>
        <a href="/compare?tokens=ethereum,{slug}" class="profile-action-btn">Compare with ETH</a>
        <a href="/watchlist?tokens={slug}" class="profile-action-btn">Add to Watchlist</a>
        <a href="/api/v1/profile/{slug}" class="profile-action-btn">API (JSON)</a>
    </div>
    <div class="profile-external-links">
        <span class="profile-external-label">External:</span>
        <a href="https://app.santiment.net/charts?slug={slug}" class="profile-ext-link" target="_blank" rel="noopener">Santiment</a>
        <a href="https://www.coingecko.com/en/coins/{slug}" class="profile-ext-link" target="_blank" rel="noopener">CoinGecko</a>
        <a href="https://coinmarketcap.com/currencies/{slug}/" class="profile-ext-link" target="_blank" rel="noopener">CoinMarketCap</a>
    </div>"""

    og_parts = [f"{name} ({ticker})"]
    if price:
        og_parts.append(f"Price: {fmt_usd(price)}")
    if mvrv is not None:
        zl, _, _ = mvrv_zone(mvrv)
        og_parts.append(f"MVRV: {mvrv:.2f} ({zl})")
    og_desc = " | ".join(og_parts) + " — Onchain Pulse analytics"
    return page_shell(f"{name} ({ticker})", body, og_description=og_desc, canonical=f"/token/{slug}")


# ================================================================
# COMPARE PAGE
# ================================================================

def render_compare_page(tokens: list) -> str:
    if not tokens:
        body = """
        <h1 class="page-title">Compare Tokens</h1>
        <p class="page-subtitle">Side-by-side on-chain comparison</p>
        <div class="empty-state">
            <div class="empty-state-icon">&#8644;</div>
            <h2>Select tokens to compare</h2>
            <p>Add token slugs to the URL or pick a preset:</p>
            <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center">
                <a href="/compare?tokens=bitcoin,ethereum" class="filter-btn">BTC vs ETH</a>
                <a href="/compare?tokens=bitcoin,ethereum,solana,cardano" class="filter-btn">L1 Chains</a>
                <a href="/compare?tokens=aave,uniswap,maker" class="filter-btn">DeFi</a>
                <a href="/compare?tokens=dogecoin,shiba-inu,pepe" class="filter-btn">Memes</a>
            </div>
        </div>"""
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

    # Summary cards for each token with sparkline
    summary_cards = ""
    for t in tokens:
        m = t.get("metrics", {})
        price = m.get("price_usd", {}).get("latest")
        mcap = m.get("marketcap_usd", {}).get("latest")
        mvrv = m.get("mvrv_usd", {}).get("latest")
        daa = m.get("daily_active_addresses", {}).get("latest")
        zone_html = ""
        if mvrv is not None:
            zl, zc, _ = mvrv_zone(mvrv)
            zone_html = f'<span class="zone {zc}">{zl}</span>'
        # 7d sparkline from price data (last 7 entries)
        price_data = m.get("price_usd", {}).get("data", [])
        spark_data = price_data[-7:] if len(price_data) >= 7 else price_data
        spark_svg = sparkline_svg(spark_data, width=120, height=28) if len(spark_data) >= 2 else ""
        summary_cards += f"""
        <div class="compare-summary-card">
            <div class="compare-summary-name"><a href="/token/{t.get('slug', '')}">{_esc(t.get("name", ""))}</a></div>
            <div class="compare-summary-ticker">{_esc(t.get("ticker", ""))}</div>
            <div class="compare-summary-price">{fmt_usd(price)}</div>
            {f'<div class="compare-summary-spark">{spark_svg}</div>' if spark_svg else ""}
            <div class="compare-summary-stats">
                <span>MCap: {fmt_usd(mcap)}</span>
                <span>MVRV: {f"{mvrv:.2f}" if mvrv else "&mdash;"}</span>
                {f"<span>DAA: {int(daa):,}</span>" if daa else ""}
            </div>
            {zone_html}
        </div>"""

    # Current slugs for watchlist link
    slug_list = ",".join(t.get("slug", "") for t in tokens)

    # Correlation matrix (price returns)
    corr_html = ""
    if len(tokens) >= 2:
        # Extract daily returns for each token
        returns = {}
        for t in tokens:
            price_data = t.get("metrics", {}).get("price_usd", {}).get("data", [])
            vals = [d.get("value") for d in price_data if d.get("value") is not None]
            if len(vals) >= 10:
                rets = [(vals[i] - vals[i-1]) / vals[i-1] for i in range(1, len(vals)) if vals[i-1] != 0]
                returns[t.get("ticker", t.get("slug", ""))] = rets

        if len(returns) >= 2:
            tickers = list(returns.keys())
            # Compute Pearson correlation
            def _corr(a, b):
                n = min(len(a), len(b))
                if n < 5:
                    return None
                a, b = a[-n:], b[-n:]
                ma = sum(a) / n
                mb = sum(b) / n
                cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
                sa = sum((x - ma) ** 2 for x in a) ** 0.5
                sb = sum((x - mb) ** 2 for x in b) ** 0.5
                if sa == 0 or sb == 0:
                    return None
                return cov / (sa * sb)

            header = "<th></th>" + "".join(f"<th>{_esc(t)}</th>" for t in tickers)
            rows = ""
            for i, ti in enumerate(tickers):
                cells = f"<td class='col-name'><strong>{_esc(ti)}</strong></td>"
                for j, tj in enumerate(tickers):
                    if i == j:
                        cells += '<td class="corr-cell corr-1">1.00</td>'
                    else:
                        r = _corr(returns[ti], returns[tj])
                        if r is not None:
                            # Color: green for high positive, red for negative
                            if r > 0.7:
                                cls = "corr-high"
                            elif r > 0.3:
                                cls = "corr-med"
                            elif r > -0.3:
                                cls = "corr-low"
                            else:
                                cls = "corr-neg"
                            cells += f'<td class="corr-cell {cls}">{r:.2f}</td>'
                        else:
                            cells += '<td class="corr-cell">&mdash;</td>'
                rows += f"<tr>{cells}</tr>"
            corr_html = f"""
    <div class="section">
        <div class="section-title">Price Correlation Matrix</div>
        <p class="section-subtitle">Based on daily return correlation</p>
        <div class="table-wrap"><table class="data-table corr-table">
            <thead><tr>{header}</tr></thead>
            <tbody>{rows}</tbody>
        </table></div>
    </div>"""

    body = f"""
    {_breadcrumbs(("Compare",))}
    <h1 class="page-title">Compare Tokens</h1>
    <p class="page-subtitle">Side-by-side on-chain comparison</p>
    <div class="compare-bar">
        <span class="compare-bar-label">Quick:</span>
        {chips}
    </div>
    <div class="compare-summary-grid">{summary_cards}</div>
    <div class="compare-actions">
        <a href="/watchlist?tokens={_esc(slug_list)}" class="filter-btn">Save as Watchlist</a>
    </div>
    <div class="section">
        <div class="section-title">Metrics</div>
        {comp_table}
    </div>
    {corr_html}
    <div class="section">
        <div class="section-title">Charts</div>
        <div class="chart-grid chart-grid-2">
            {"".join(f'<div class="chart-cell">{c}</div>' for c in overlay_charts) if overlay_charts else '<p class="chart-empty">Not enough data yet.</p>'}
        </div>
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

    displayed = tokens[:200]
    max_vol = max((t.get("volume_usd") or 0 for t in displayed), default=1) or 1

    rows = []
    for i, t in enumerate(displayed):
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
        vol = t.get("volume_usd") or 0
        vol_pct = min(100, vol / max_vol * 100) if max_vol else 0
        vol_bar = f'<div class="vol-bar-wrap"><div class="vol-bar-fill" style="width:{vol_pct:.0f}%"></div><span class="vol-bar-val">{fmt_usd(vol)}</span></div>'
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-tag hide-mobile"><span class="sector-tag sector-{sec}">{_esc(sec_label)}</span></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-spark hide-mobile">{spark_html}</td>
            <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
            <td class="hide-mobile" style="min-width:130px">{vol_bar}</td>
            <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
            <td class="col-tag hide-mobile">{zone_html}</td>
        </tr>""")

    # MVRV zone distribution
    zone_dist = {}
    for t in tokens:
        mv = t.get("mvrv_usd")
        if mv is not None:
            zl, zc, _ = mvrv_zone(mv)
            zone_dist[zl] = zone_dist.get(zl, 0) + 1
    zone_total = sum(zone_dist.values()) or 1
    zone_order = [("Deep Value", "zone-deep-value"), ("Undervalued", "zone-undervalued"),
                  ("Fair Value", "zone-fair"), ("Overvalued", "zone-overvalued"), ("Euphoria", "zone-euphoria")]
    zone_bar_segs = ""
    zone_legend = ""
    for zl, zcls in zone_order:
        cnt = zone_dist.get(zl, 0)
        if cnt == 0:
            continue
        pct = cnt / zone_total * 100
        zone_bar_segs += f'<div class="zone-bar-seg {zcls}" style="width:{pct:.1f}%" title="{zl}: {cnt} ({pct:.0f}%)"></div>'
        zone_legend += f'<span class="zone-legend-item"><span class="zone-legend-dot {zcls}"></span>{zl} {cnt}</span>'
    zone_summary_html = f"""
    <div class="zone-distribution">
        <div class="zone-bar">{zone_bar_segs}</div>
        <div class="zone-legend">{zone_legend}</div>
    </div>""" if zone_bar_segs else ""

    search_note = f' matching "{_esc(search)}"' if search else ""
    body = f"""
    {_breadcrumbs(("Screener",))}
    <h1 class="page-title">Screener</h1>
    <p class="page-subtitle">Filter and sort {len(tokens)} tokens{search_note}</p>
    {zone_summary_html}
    <form class="search-bar" action="/screener" method="get" role="search" aria-label="Search screener">
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
    <div class="filter-bar">
        <div class="filter-group">
            <span class="filter-label">Quick:</span>
            <a href="/screener?sort=mvrv_usd&order=asc" class="filter-btn preset-btn">Undervalued</a>
            <a href="/screener?sort=price_usd_change&order=desc" class="filter-btn preset-btn">Top Gainers</a>
            <a href="/screener?sort=price_usd_change&order=asc" class="filter-btn preset-btn">Top Losers</a>
            <a href="/screener?sort=volume_usd&order=desc" class="filter-btn preset-btn">High Volume</a>
            <a href="/screener?sort=dev_activity&order=desc" class="filter-btn preset-btn">Active Dev</a>
        </div>
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

def render_valuation_page(tokens: list, sector: str = "all", sectors: dict = None, zone_filter: str = "all") -> str:
    zone_counts = {}
    for t in tokens:
        mvrv = t.get("mvrv_usd")
        if mvrv is not None:
            z = mvrv_zone(mvrv)
            zone_counts[z[0]] = zone_counts.get(z[0], 0) + 1

    zone_defs_list = [
        ("Deep Value", "zone-extreme-low", "deep_value"),
        ("Undervalued", "zone-undervalued", "undervalued"),
        ("Fair Value", "zone-fair", "fair"),
        ("Elevated", "zone-fair-high", "elevated"),
        ("Overvalued", "zone-overvalued", "overvalued"),
        ("Euphoria", "zone-extreme-high", "euphoria"),
    ]
    legend = "".join(
        f'<span class="legend-item"><span class="zone {cls}">{label}</span> {zone_counts.get(label, 0)}</span>'
        for label, cls, _ in zone_defs_list
    )

    # Zone filter
    sec_qs = f"&sector={sector}" if sector != "all" else ""
    zone_btns = f'<a href="/valuation?{sec_qs[1:] if sec_qs else ""}" class="filter-btn{" active" if zone_filter == "all" else ""}">All Zones</a>'
    for label, cls, key in zone_defs_list:
        zone_btns += f'<a href="/valuation?zone={key}{sec_qs}" class="filter-btn{" active" if zone_filter == key else ""}"><span class="zone {cls}" style="font-size:0.68rem">{label}</span></a>'
    zone_filter_html = f'<div class="filter-bar"><div class="filter-group"><span class="filter-label">Zone:</span>{zone_btns}</div></div>'

    # Sector filter
    sector_filter = ""
    if sectors:
        sector_btns = f'<a href="/valuation" class="filter-btn{" active" if sector == "all" else ""}">All</a>'
        for key, label in sorted(sectors.items(), key=lambda x: x[1]):
            sector_btns += f'<a href="/valuation?sector={key}" class="filter-btn{" active" if key == sector else ""}">{_esc(label)}</a>'
        sector_filter = f'<div class="filter-bar"><div class="filter-group"><span class="filter-label">Sector:</span>{sector_btns}</div></div>'

    rows = []
    for i, t in enumerate(tokens):
        mvrv = t.get("mvrv_usd")
        if mvrv is None:
            continue
        slug = t.get("slug", "")
        zone_label, zone_css, _ = mvrv_zone(mvrv)
        bar_pct = min(100, max(0, mvrv / 4 * 100))
        sec = t.get("sector", "other")
        sec_label = (sectors or {}).get(sec, sec.replace("_", " ").title()) if sectors else sec.replace("_", " ").title()
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-tag hide-mobile"><a href="/valuation?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num bold">{mvrv:.2f}</td>
            <td class="col-tag"><span class="zone {zone_css}">{zone_label}</span></td>
            <td class="hide-mobile" style="min-width:120px"><div class="mini-bar-track"><div class="mini-bar-fill" style="width:{bar_pct:.0f}%"></div></div></td>
        </tr>""")

    sector_note = f' in {(sectors or {}).get(sector, sector)}' if sector != "all" else ""
    body = f"""
    {_breadcrumbs(("Valuation",))}
    <h1 class="page-title">Valuation Scanner</h1>
    <p class="page-subtitle">MVRV zones across {len(tokens)} tokens{sector_note}</p>
    {sector_filter}
    {zone_filter_html}
    <div class="val-legend">{legend}</div>
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th><th>Name</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">Price</th><th class="col-num">MVRV</th>
                <th class="col-tag">Zone</th><th class="hide-mobile">Bar</th>
            </tr></thead>
            <tbody>{"".join(rows) if rows else '<tr><td colspan="7" class="empty-cell">MVRV data not yet available.</td></tr>'}</tbody>
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
    return page_shell("Sync", body, active_nav="sync", auto_refresh=30)


# ================================================================
# DEVELOPERS LEADERBOARD
# ================================================================

def render_developers_page(tokens: list, sector: str = "all", sectors: dict = None) -> str:
    parts = []
    sector_note = f' in {(sectors or {}).get(sector, sector)}' if sector != "all" else ""
    parts.append(_breadcrumbs(("Developers",)))
    parts.append(f"""
    <h1 class="page-title">Developer Activity</h1>
    <p class="page-subtitle">Top {len(tokens)} projects by dev activity{sector_note}</p>""")

    # Sector filter
    if sectors:
        sector_btns = f'<a href="/developers" class="filter-btn{" active" if sector == "all" else ""}">All</a>'
        for key, label in sorted(sectors.items(), key=lambda x: x[1]):
            sector_btns += f'<a href="/developers?sector={key}" class="filter-btn{" active" if key == sector else ""}">{_esc(label)}</a>'
        parts.append(f'<div class="filter-bar"><div class="filter-group"><span class="filter-label">Sector:</span>{sector_btns}</div></div>')

    # Summary stats
    if tokens:
        total_dev = sum(t.get("dev_activity") or 0 for t in tokens)
        avg_dev = total_dev / len(tokens)
        with_change = [t for t in tokens if t.get("dev_activity_change") is not None]
        growing = sum(1 for t in with_change if (t.get("dev_activity_change") or 0) > 5)
        declining = sum(1 for t in with_change if (t.get("dev_activity_change") or 0) < -5)
        # Narrative
        dev_narrative_parts = []
        if growing > declining * 2:
            dev_narrative_parts.append(f"Strong builder momentum — {growing} projects with growing dev activity vs {declining} declining")
        elif declining > growing * 2:
            dev_narrative_parts.append(f"Cooling development — {declining} projects losing dev momentum vs {growing} growing")
        else:
            dev_narrative_parts.append(f"Mixed developer trends — {growing} growing, {declining} declining")
        top3 = [t.get("name", "") for t in tokens[:3] if t.get("dev_activity")]
        if top3:
            dev_narrative_parts.append(f"Most active: {', '.join(top3)}")
        dev_narrative = ". ".join(dev_narrative_parts) + "." if dev_narrative_parts else ""

        parts.append(f"""
    <div class="stats-row">
        <div class="stat-card"><div class="stat-label">Total Dev Activity</div><div class="stat-value">{total_dev:,.0f}</div></div>
        <div class="stat-card"><div class="stat-label">Average</div><div class="stat-value">{avg_dev:,.1f}</div></div>
        <div class="stat-card"><div class="stat-label">Growing (&gt;5%)</div><div class="stat-value up">{growing}</div></div>
        <div class="stat-card"><div class="stat-label">Declining (&lt;-5%)</div><div class="stat-value down">{declining}</div></div>
    </div>
    {f'<p class="regime-narrative">{dev_narrative}</p>' if dev_narrative else ''}""")

    # Leaderboard table
    rows = ""
    max_dev = max((t.get("dev_activity") or 0 for t in tokens), default=1) or 1
    for i, t in enumerate(tokens):
        dev = t.get("dev_activity") or 0
        dev_ch = t.get("dev_activity_change")
        bar_pct = min(100, dev / max_dev * 100)
        slug = t.get("slug", "")
        sec = t.get("sector", "other")
        sec_label = (sectors or {}).get(sec, sec.replace("_", " ").title())
        rows += f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{_esc(t.get("name", slug))}</strong> <span class="ticker">{_esc(t.get("ticker", ""))}</span></a></td>
            <td class="col-tag hide-mobile"><a href="/developers?sector={sec}" class="sector-tag sector-{sec}">{_esc(sec_label)}</a></td>
            <td class="col-num bold">{dev:,.0f}</td>
            <td class="col-num {css_class(dev_ch)} hide-mobile">{fmt_pct(dev_ch)}</td>
            <td class="hide-mobile" style="min-width:100px"><div class="mini-bar-track"><div class="mini-bar-fill" style="width:{bar_pct:.0f}%"></div></div></td>
            <td class="col-num hide-mobile">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num hide-mobile">{fmt_usd(t.get("marketcap_usd"))}</td>
        </tr>"""

    parts.append(f"""
    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th><th>Name</th>
                <th class="col-tag hide-mobile">Sector</th>
                <th class="col-num">Dev Activity</th>
                <th class="col-num hide-mobile">Change</th>
                <th class="hide-mobile">Bar</th>
                <th class="col-num hide-mobile">Price</th>
                <th class="col-num hide-mobile">Mkt Cap</th>
            </tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="8" class="empty-cell">No dev activity data available.</td></tr>'}</tbody>
        </table>
    </div>""")

    return page_shell("Developers", "\n".join(parts), active_nav="developers")


# ================================================================
# SECTORS OVERVIEW PAGE
# ================================================================

def render_sectors_page(sector_details: dict, sector_labels: dict) -> str:
    total_mcap = sum(d["mcap"] for d in sector_details.values())
    # Sort sectors by market cap
    sorted_sectors = sorted(sector_details.items(), key=lambda x: x[1]["mcap"], reverse=True)

    parts = []
    parts.append(_breadcrumbs(("Sectors",)))
    parts.append("""
    <h1 class="page-title">Sector Overview</h1>
    <p class="page-subtitle">Performance breakdown by sector</p>""")

    # Sector cards grid
    cards = ""
    for sec_key, data in sorted_sectors:
        sec_label = sector_labels.get(sec_key, sec_key.replace("_", " ").title())
        avg_ch = data.get("avg_change", 0)
        ch_cls = "up" if avg_ch > 0 else "down" if avg_ch < 0 else "muted"
        pct_of_total = (data["mcap"] / total_mcap * 100) if total_mcap > 0 else 0

        # Top tokens list
        top_list = ""
        for t in data["top_tokens"]:
            t_pct = t.get("price_usd_change")
            t_cls = css_class(t_pct)
            top_list += (
                f'<a href="/token/{t["slug"]}" class="sector-top-token">'
                f'<span class="sector-top-name">{_esc(t.get("ticker", ""))}</span>'
                f'<span class="sector-top-price">{fmt_usd(t.get("price_usd"))}</span>'
                f'<span class="sector-top-pct {t_cls}">{fmt_pct(t_pct)}</span>'
                f'</a>'
            )

        cards += f"""
        <div class="sector-overview-card">
            <div class="sector-overview-header">
                <a href="/explore?sector={sec_key}" class="sector-tag sector-{sec_key}" style="font-size:0.72rem">{_esc(sec_label)}</a>
                <span class="sector-overview-change {ch_cls}">{fmt_pct(avg_ch)} avg</span>
            </div>
            <div class="sector-overview-stats">
                <div class="sector-overview-stat">
                    <span class="sector-overview-stat-val">{fmt_usd(data["mcap"])}</span>
                    <span class="sector-overview-stat-label">Market Cap</span>
                </div>
                <div class="sector-overview-stat">
                    <span class="sector-overview-stat-val">{data["count"]}</span>
                    <span class="sector-overview-stat-label">Tokens</span>
                </div>
                <div class="sector-overview-stat">
                    <span class="sector-overview-stat-val">{pct_of_total:.1f}%</span>
                    <span class="sector-overview-stat-label">of Total</span>
                </div>
            </div>
            <div class="sector-overview-bar">
                <div class="sector-overview-bar-fill" style="width:{min(pct_of_total, 100):.1f}%"></div>
            </div>
            <div class="sector-top-tokens">{top_list}</div>
            <div class="sector-tag-cloud">{"".join(
                f'<a href="/token/{t["slug"]}" class="tag-cloud-item" style="font-size:{max(0.55, min(0.85, 0.55 + 0.3 * ((t.get("marketcap_usd") or 0) / max(data["mcap"], 1)) * data["count"])):.2f}rem">{_esc(t.get("ticker", ""))}</a>'
                for t in data.get("all_tokens", data["top_tokens"])[:20]
            )}</div>
            <div class="sector-overview-actions">
                <a href="/explore?sector={sec_key}" class="sector-overview-link">View all {data["count"]} &rarr;</a>
                <a href="/compare?tokens={','.join(t['slug'] for t in data['top_tokens'][:5])}" class="sector-overview-link">Compare top 5</a>
            </div>
        </div>"""

    parts.append(f'<div class="sector-overview-grid">{cards}</div>')

    return page_shell("Sectors", "\n".join(parts), active_nav="sectors")


# ================================================================
# WATCHLIST PAGE
# ================================================================

def render_watchlist_page(tokens: list, slug_list: list = None) -> str:
    slug_list = slug_list or []
    slugs_str = ",".join(slug_list)

    parts = []
    parts.append(_breadcrumbs(("Watchlist",)))
    parts.append(f"""
    <h1 class="page-title">Watchlist</h1>
    <p class="page-subtitle">Track your favorite tokens &middot; Bookmark this URL to save your list</p>""")

    # Add token form
    parts.append(f"""
    <form class="search-bar watchlist-form" action="/watchlist" method="get">
        <input type="text" name="tokens" value="{_esc(slugs_str)}" placeholder="Enter slugs: bitcoin,ethereum,solana..." class="search-input" autocomplete="off">
        <button type="submit" class="search-btn">Update</button>
    </form>""")
    if slug_list:
        parts.append(f"""
    <div class="share-hint">
        <span class="share-hint-icon">&#128279;</span>
        <span>Share this watchlist — copy the URL from your browser's address bar. All tokens are encoded in the URL.</span>
    </div>""")

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
        parts.append('<div class="empty-state"><div class="empty-state-icon">&#9734;</div><h2>No tokens selected</h2><p>Enter token slugs in the box above or pick a preset watchlist to get started.</p></div>')
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


# ================================================================
# GLOSSARY PAGE
# ================================================================

def render_glossary_page() -> str:
    metrics = [
        ("MVRV (Market Value to Realized Value)", "mvrv_usd",
         "Compares current market cap to realized cap (the value when each coin last moved on-chain). "
         "Below 1.0 historically signals undervaluation; above 3.0 often precedes corrections.",
         [("< 0.7", "Deep Value — strong buying zone historically"),
          ("0.7 – 1.0", "Undervalued — accumulation territory"),
          ("1.0 – 1.5", "Fair Value — balanced market"),
          ("1.5 – 2.5", "Elevated — caution warranted"),
          ("2.5 – 3.5", "Overvalued — distribution risk"),
          ("> 3.5", "Euphoria — extreme caution")]),
        ("NVT Ratio (Network Value to Transactions)", "nvt",
         "Crypto equivalent of P/E ratio. Divides market cap by on-chain transaction volume. "
         "High NVT means the network is overvalued relative to its usage; low NVT suggests undervaluation.",
         [("< 20", "Strong utilization — potentially undervalued"),
          ("20 – 80", "Normal range"),
          ("> 150", "Overvalued relative to network throughput")]),
        ("Daily Active Addresses (DAA)", "daily_active_addresses",
         "Count of unique addresses that transacted on-chain in the past 24 hours. "
         "Rising DAA indicates growing network adoption and user engagement.", []),
        ("Exchange Balance", "exchange_balance",
         "Total token supply held on known exchange wallets. "
         "Decreasing balance suggests accumulation; increasing suggests distribution.",
         [("Decreasing", "Accumulation — coins moving to cold storage"),
          ("Increasing", "Distribution — coins moving to exchanges for potential sale")]),
        ("Dev Activity", "dev_activity",
         "Measures GitHub events (commits, PRs, issues) in the project's repositories. "
         "Consistent dev activity signals an actively maintained project.", []),
        ("Network Growth", "network_growth",
         "Number of new addresses created on the network per day. "
         "Higher growth indicates expanding network adoption.", []),
        ("Transaction Volume", "transaction_volume",
         "Total value of on-chain transactions per day. "
         "Captures actual on-chain economic activity, distinct from exchange volume.", []),
        ("Circulation", "circulation",
         "Number of unique tokens transacted on-chain during the period. "
         "High circulation suggests active usage rather than dormant holding.", []),
        ("Velocity", "velocity",
         "Transaction volume divided by circulating supply — how frequently tokens change hands.", []),
        ("Mean Dollar Age", "mean_age",
         "Average age of all tokens weighted by USD value. "
         "Drops indicate older coins moving — often a distribution signal.", []),
        ("Whale Transactions (>$100K)", "whale_transaction_count_100k_usd_to_inf",
         "Count of transactions exceeding $100,000. "
         "Spikes often precede significant price movements.", []),
        ("Social Volume", "social_volume_total",
         "Number of mentions across social platforms. "
         "Spikes indicate growing interest or fear.", []),
        ("Sentiment Balance", "sentiment_balance_total",
         "Ratio of positive to negative social mentions. "
         "Extreme positive can be contrarian bearish; extreme negative can be contrarian bullish.", []),
    ]

    cards = ""
    for title, key, desc, thresholds in metrics:
        threshold_html = ""
        if thresholds:
            items = "".join(f"<li><strong>{_esc(k)}</strong>: {_esc(v)}</li>" for k, v in thresholds)
            threshold_html = f'<ul class="glossary-thresholds">{items}</ul>'
        cards += f"""
        <div class="card glossary-card">
            <h3 class="glossary-metric-name">{_esc(title)}</h3>
            <code class="glossary-key">{_esc(key)}</code>
            <p class="glossary-desc">{_esc(desc)}</p>
            {threshold_html}
        </div>"""

    body = f"""
    {_breadcrumbs(("Glossary",))}
    <h1 class="page-title">Metric Glossary</h1>
    <p class="page-subtitle">Understanding the on-chain metrics used across the dashboard</p>
    <div class="glossary-grid">{cards}</div>"""
    return page_shell("Glossary", body)
