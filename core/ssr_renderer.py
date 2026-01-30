"""
Server-side HTML renderer — pure HTML, zero JavaScript.

Every page is a complete HTML document rendered on the server.
Navigation is via <a> links. Charts are inline SVG.
"""

import html as html_mod
from datetime import datetime
from typing import Optional

from .svg_charts import (
    sparkline_svg, line_chart_svg, chart_panel, comparison_table,
    market_heatmap_svg, dominance_bar_svg, sentiment_gauge_svg, mini_trend_svg,
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
        return f"{sign}${a/1e3:,.0f}"
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
    """Return 'up', 'down', or 'muted' for a numeric value."""
    if v is None:
        return "muted"
    return "up" if v > 0 else "down" if v < 0 else "muted"


def mvrv_zone(v):
    """Return (label, css_class, description) for an MVRV value."""
    if v is None:
        return ("N/A", "zone-neutral", "No MVRV data available")
    if v < 0.7:
        return ("Deep Value", "zone-extreme-low", "Market is trading well below realized value — historically a strong buying zone")
    if v < 1.0:
        return ("Undervalued", "zone-undervalued", "Market is below realized value — potential accumulation zone")
    if v < 1.5:
        return ("Fair", "zone-fair", "Market is near realized value — balanced positioning")
    if v < 2.5:
        return ("Elevated", "zone-fair-high", "Market is above realized value — caution warranted")
    if v < 3.5:
        return ("Overvalued", "zone-overvalued", "Market is well above realized value — distribution risk increasing")
    return ("Euphoria", "zone-extreme-high", "Market is far above realized value — historically a distribution zone")


# Keep old names exported for compatibility
def pct_class(v):
    return css_class(v)


# ================================================================
# PAGE SHELL
# ================================================================

def page_shell(title: str, body: str, active_nav: str = "") -> str:
    """Wrap body content in the full HTML page shell."""
    nav_items = [
        ("market", "/", "Market"),
        ("screener", "/screener", "Screener"),
        ("compare", "/compare?tokens=bitcoin,ethereum,solana", "Compare"),
        ("valuation", "/valuation", "Valuation"),
        ("sync", "/sync", "Sync"),
    ]
    nav_html = "".join(
        f'<a href="{href}" class="nav-link{" active" if key == active_nav else ""}">{label}</a>'
        for key, href, label in nav_items
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html_mod.escape(title)} — Onchain Pulse</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/dashboard.css">
</head>
<body>
    <header class="header">
        <div class="header-inner">
            <a href="/" class="logo">Onchain<span>Pulse</span></a>
            <nav class="header-nav">{nav_html}</nav>
            <div class="header-right">
                <span class="status-dot syncing"></span>
                <span>Powered by Santiment</span>
            </div>
        </div>
    </header>
    <main class="main">{body}</main>
    <footer class="footer">On-chain data provided by Santiment. Updated continuously.</footer>
</body>
</html>"""


# ================================================================
# MARKET PAGE (Landing / Dashboard)
# ================================================================

def render_market_page(
    tokens: list,
    pull_status: str,
    last_pull: str = None,
    page: int = 1,
    per_page: int = 100,
    total: int = 0,
    universe_size: int = 0,
    cache_stats: dict = None,
    gainers: list = None,
    losers: list = None,
    all_tokens_for_charts: list = None,
    mcap_trend_data: list = None,
    **kwargs,
) -> str:
    all_t = all_tokens_for_charts or tokens
    gainers = gainers or []
    losers = losers or []

    # Aggregates
    total_mcap = sum(t.get("marketcap_usd") or 0 for t in all_t)
    total_vol = sum(t.get("volume_usd") or 0 for t in all_t)
    mvrv_vals = [t["mvrv_usd"] for t in all_t if t.get("mvrv_usd") is not None]
    avg_mvrv = sum(mvrv_vals) / len(mvrv_vals) if mvrv_vals else None
    daa_vals = [t["daily_active_addresses"] for t in all_t if t.get("daily_active_addresses")]
    total_daa = sum(daa_vals) if daa_vals else None
    pos = sum(1 for t in all_t if (t.get("price_usd_change") or 0) > 0)
    neg = sum(1 for t in all_t if (t.get("price_usd_change") or 0) < 0)

    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page

    parts = []

    # --- Sync banner ---
    is_syncing = pull_status not in ("ready", "idle", "skipped")
    if is_syncing:
        cs = cache_stats or {}
        pct = min(99, int(total / universe_size * 100)) if universe_size and total else 0
        parts.append(f"""
        <div class="sync-banner">
            <span class="sync-dot"></span>
            <span class="sync-banner-text"><strong>Syncing</strong> — {total}/{universe_size} tokens ({pct}%) · {fmt_num(cs.get("timeseries_rows", 0))} points · {cs.get("db_size_mb", 0):.0f} MB</span>
            <div class="sync-bar"><div class="sync-bar-fill" style="width:{pct}%"></div></div>
            <a href="/sync" class="sync-link">Details</a>
        </div>""")

    # --- Page header ---
    parts.append(f"""
    <h1 class="page-title">Market Overview</h1>
    <p class="page-subtitle">{total} tokens tracked{f" of {universe_size} discovered" if universe_size else ""}</p>""")

    # --- Stats row ---
    mcap_trend = mcap_trend_data or kwargs.get("mcap_trend", None)
    trend_svg = mini_trend_svg(mcap_trend, width=110, height=28) if mcap_trend and len(mcap_trend) > 3 else ""
    parts.append(f"""
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-label">Total Market Cap</div>
            <div class="stat-value">{fmt_usd(total_mcap)}</div>
            {f'<div class="stat-trend">{trend_svg}</div>' if trend_svg else ''}
        </div>
        <div class="stat-card">
            <div class="stat-label">24h Volume</div>
            <div class="stat-value">{fmt_usd(total_vol)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg MVRV</div>
            <div class="stat-value">{f"{avg_mvrv:.2f}" if avg_mvrv else "&mdash;"}</div>
            <div class="stat-sub">{mvrv_zone(avg_mvrv)[0] if avg_mvrv else ""}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Active Addresses</div>
            <div class="stat-value">{fmt_num(total_daa)}</div>
        </div>
        <div class="stat-card hide-mobile">
            <div class="stat-label">Market Breadth</div>
            <div class="stat-value"><span class="up">{pos}</span> / <span class="down">{neg}</span></div>
            <div class="stat-sub">up / down</div>
        </div>
    </div>""")

    # --- Sentiment gauge ---
    if avg_mvrv is not None:
        zone_label, zone_css, zone_desc = mvrv_zone(avg_mvrv)
        parts.append(f"""
    <div class="sentiment-panel">
        <div class="sentiment-gauge">{sentiment_gauge_svg(avg_mvrv, min_val=0, max_val=4, label="Avg MVRV")}</div>
        <div class="sentiment-info">
            <div class="sentiment-label">Market Sentiment</div>
            <div class="sentiment-reading">
                <span class="sentiment-value">{avg_mvrv:.2f}</span>
                <span class="zone {zone_css}">{zone_label}</span>
            </div>
            <p class="sentiment-desc">{zone_desc}</p>
            <div class="breadth-row">
                <span><strong class="up">{pos}</strong> tokens up</span>
                <span><strong class="down">{neg}</strong> tokens down</span>
            </div>
        </div>
    </div>""")

    # --- Dominance bar ---
    if len(all_t) > 3:
        dom = sorted(all_t, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)
        parts.append(f"""
    <div class="section">
        <div class="section-title">Market Dominance</div>
        <div class="dominance-wrap">{dominance_bar_svg(dom)}</div>
    </div>""")

    # --- Heatmap ---
    if len(all_t) > 5:
        parts.append(f"""
    <div class="section">
        <div class="section-title">Performance Heatmap <span class="badge">24h change</span></div>
        <div class="heatmap-wrap">{market_heatmap_svg(all_t, max_tokens=50)}</div>
    </div>""")

    # --- Gainers / Losers ---
    if gainers or losers:
        def _mover_rows(items):
            rows = []
            for i, t in enumerate(items[:10]):
                slug = t.get("slug", "")
                pct = t.get("price_usd_change")
                rows.append(
                    f'<a href="/token/{slug}" class="mover-row">'
                    f'<span class="mover-rank">{i+1}</span>'
                    f'<span class="mover-name">{html_mod.escape(t.get("name", slug)[:20])} '
                    f'<span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></span>'
                    f'<span class="mover-price">{fmt_usd(t.get("price_usd"))}</span>'
                    f'<span class="mover-pct {css_class(pct)}">{fmt_pct(pct)}</span>'
                    f'</a>'
                )
            return "".join(rows)

        parts.append(f"""
    <div class="movers-grid">
        <div class="movers-col">
            <div class="movers-header up">Top Gainers</div>
            {_mover_rows(gainers)}
        </div>
        <div class="movers-col">
            <div class="movers-header down">Top Losers</div>
            {_mover_rows(losers)}
        </div>
    </div>""")

    # --- Top by Volume / Active Addresses ---
    vol_sorted = sorted(all_t, key=lambda t: t.get("volume_usd") or 0, reverse=True)[:8]
    daa_sorted = sorted([t for t in all_t if t.get("daily_active_addresses")],
                        key=lambda t: t.get("daily_active_addresses") or 0, reverse=True)[:8]

    if vol_sorted or daa_sorted:
        def _top_rows(items, metric_key, fmt_fn):
            rows = []
            for i, t in enumerate(items):
                slug = t.get("slug", "")
                pct = t.get("price_usd_change")
                rows.append(
                    f'<a href="/token/{slug}" class="top-row">'
                    f'<span class="top-rank">{i+1}</span>'
                    f'<span class="top-name">{html_mod.escape(t.get("name", slug)[:18])} '
                    f'<span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></span>'
                    f'<span class="top-val">{fmt_fn(t.get(metric_key))}</span>'
                    f'<span class="top-pct {css_class(pct)}">{fmt_pct(pct)}</span>'
                    f'</a>'
                )
            return "".join(rows)

        parts.append(f"""
    <div class="top-grid">
        <div class="top-col">
            <div class="top-header">Top by Volume</div>
            {_top_rows(vol_sorted, "volume_usd", fmt_usd)}
        </div>
        <div class="top-col">
            <div class="top-header">Top by Active Addresses</div>
            {_top_rows(daa_sorted, "daily_active_addresses", fmt_num)}
        </div>
    </div>""")

    # --- Main table ---
    showing = f"Showing {start+1}&ndash;{min(start+per_page, total)}" if total else "No data yet"
    parts.append(f"""
    <div class="section">
        <div class="section-title">All Tokens <span class="badge">{showing} of {total}</span></div>
        <div class="table-wrap">
            <table class="data-table">
                <thead><tr>
                    <th class="col-rank">#</th>
                    <th>Name</th>
                    <th class="col-num">Price</th>
                    <th class="col-num">24h</th>
                    <th class="col-spark hide-mobile">7d</th>
                    <th class="col-num">Market Cap</th>
                    <th class="col-num">Volume</th>
                    <th class="col-num hide-mobile">MVRV</th>
                    <th class="col-tag hide-mobile">Zone</th>
                    <th class="col-num hide-mobile">Active Addr</th>
                </tr></thead>
                <tbody>""")

    if not tokens:
        parts.append('<tr><td colspan="10" class="empty-cell">Data is being pulled. Refresh in a moment...</td></tr>')
    else:
        for i, t in enumerate(tokens):
            rank = start + i + 1
            slug = t.get("slug", "")
            pct = t.get("price_usd_change")
            mvrv = t.get("mvrv_usd")
            zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv is not None else "&mdash;"
            spark = t.get("sparkline_7d", [])
            spark_html = sparkline_svg(spark, width=80, height=24) if spark else "&mdash;"

            parts.append(f"""<tr>
                <td class="col-rank">{rank}</td>
                <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get("name", slug))}</strong> <span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></a></td>
                <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
                <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
                <td class="col-spark hide-mobile">{spark_html}</td>
                <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
                <td class="col-num">{fmt_usd(t.get("volume_usd"))}</td>
                <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
                <td class="col-tag hide-mobile">{zone_html}</td>
                <td class="col-num hide-mobile">{fmt_num(t.get("daily_active_addresses"))}</td>
            </tr>""")

    parts.append("</tbody></table></div>")

    # Pagination
    if total_pages > 1:
        pg = []
        pg.append(f'<a href="/?page={page-1}&per_page={per_page}" class="page-btn">&laquo;</a>' if page > 1 else '<span class="page-btn disabled">&laquo;</span>')
        for p in range(1, total_pages + 1):
            if p == page:
                pg.append(f'<span class="page-btn active">{p}</span>')
            elif p <= 2 or p > total_pages - 1 or abs(p - page) <= 2:
                pg.append(f'<a href="/?page={p}&per_page={per_page}" class="page-btn">{p}</a>')
            elif (p == 3 and page > 5) or (p == total_pages - 1 and page < total_pages - 4):
                pg.append('<span class="page-btn ellipsis">&hellip;</span>')
        pg.append(f'<a href="/?page={page+1}&per_page={per_page}" class="page-btn">&raquo;</a>' if page < total_pages else '<span class="page-btn disabled">&raquo;</span>')
        parts.append(f'<div class="pagination">{"".join(pg)}</div>')

    parts.append("</div>")  # close section

    return page_shell("Market", "\n".join(parts), active_nav="market")


# ================================================================
# TOKEN PROFILE
# ================================================================

def render_token_profile(token: dict, metrics: dict, slug: str = "") -> str:
    slug = slug or token.get("slug", "")
    name = html_mod.escape(token.get("name", slug))
    ticker = html_mod.escape(token.get("ticker", ""))
    infra = html_mod.escape(token.get("infrastructure", ""))

    # metrics is a dict of {metric_name: {data: [...], latest: val, count: N, ...}}
    def _m(key):
        """Get metric info dict."""
        return metrics.get(key) or {}

    def _latest(key):
        """Get latest value for a metric."""
        m = _m(key)
        if isinstance(m, dict):
            return m.get("latest")
        return None

    def _data(key):
        """Get timeseries data list for a metric."""
        m = _m(key)
        if isinstance(m, dict):
            return m.get("data") or []
        return []

    price = _latest("price_usd")
    mvrv = _latest("mvrv_usd")

    # Compute change badges from timeseries data
    changes = []
    price_ts = _data("price_usd")
    if price_ts and len(price_ts) >= 2:
        curr = price_ts[-1].get("value")
        for label, days in [("24h", 1), ("7d", 7), ("30d", 30)]:
            idx = -1 - days
            if len(price_ts) > days and curr:
                prev = price_ts[idx].get("value")
                if prev and prev != 0:
                    v = (curr - prev) / prev * 100
                    cls = "up" if v > 0 else "down" if v < 0 else "flat"
                    changes.append(f'<span class="change-pill {cls}">{label} {fmt_pct(v)}</span>')

    # Metrics cards
    metric_cards = []
    metric_defs = [
        ("marketcap_usd", "Market Cap"),
        ("volume_usd", "Volume 24h"),
        ("mvrv_usd", "MVRV"),
        ("nvt", "NVT Ratio"),
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
            <div class="metric-label">{html_mod.escape(label)}</div>
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
        ("dev_activity", "Development Activity", "#F59E0B"),
        ("network_growth", "Network Growth", "#06B6D4"),
        ("transaction_volume", "Transaction Volume", "#EC4899"),
        ("circulation", "Circulation", "#14B8A6"),
        ("whale_transaction_count_100k_usd_to_inf", "Whale Transactions", "#F97316"),
        ("social_volume_total", "Social Volume", "#8B5CF6"),
        ("sentiment_balance_total", "Sentiment Balance", "#3B82F6"),
    ]
    for key, title, color in chart_defs:
        data = _data(key)
        if not data or len(data) < 3:
            continue
        chart = line_chart_svg(
            [{"label": title, "data": data, "color": color}],
            width=340, height=200, title=title, metric_key=key,
            show_min_max=False, show_area=True,
        )
        secondary_charts.append(chart)

    charts_html = ""
    if price_chart:
        charts_html += f'<div class="chart-wrap" style="margin-bottom:14px">{price_chart}</div>'
    if secondary_charts:
        charts_html += chart_panel(secondary_charts, columns=2)

    body = f"""
    <a href="/" class="back-link">&larr; Market</a>

    <div class="profile-hero">
        <div>
            <span class="profile-name">{name}</span>
            <span class="profile-ticker">{ticker}</span>
            {f'<span class="profile-infra">{infra}</span>' if infra else ''}
        </div>
        <div class="profile-price-block">
            <span class="profile-price">{fmt_usd(price)}</span>
            <div class="profile-changes">{"".join(changes)}</div>
        </div>
    </div>

    {f'<div class="metrics-grid">{"".join(metric_cards)}</div>' if metric_cards else ''}

    <div class="profile-section">
        <div class="profile-section-title">Charts</div>
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
        <p class="page-subtitle">Select tokens to compare side by side.</p>
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
        ("price_usd", "Price"),
        ("marketcap_usd", "Market Cap"),
        ("volume_usd", "Volume 24h"),
        ("mvrv_usd", "MVRV"),
        ("nvt", "NVT"),
        ("daily_active_addresses", "Active Addresses"),
        ("dev_activity", "Dev Activity"),
        ("exchange_balance", "Exchange Balance"),
    ]
    comp_table = comparison_table(tokens, metric_keys)

    from .svg_charts import COLORS
    overlay_configs = [
        ("price_usd", "Price Comparison", True),
        ("mvrv_usd", "MVRV Comparison", False),
        ("daily_active_addresses", "Active Addresses", False),
        ("volume_usd", "Volume Comparison", False),
    ]
    overlay_charts = []
    for metric_key, title, show_area in overlay_configs:
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
            chart = line_chart_svg(
                series, width=720, height=280, title=title,
                metric_key=metric_key, show_area=show_area and len(series) == 1,
                show_min_max=False,
            )
            overlay_charts.append(chart)

    body = f"""
    <h1 class="page-title">Compare Tokens</h1>
    <p class="page-subtitle">Side-by-side on-chain metric comparison</p>

    <div class="compare-bar">
        <span class="compare-bar-label">Quick Compare:</span>
        {chips}
    </div>

    <div class="section">
        <div class="section-title">Metrics</div>
        {comp_table}
    </div>

    <div class="section">
        <div class="section-title">Overlay Charts</div>
        {"".join(f'<div class="chart-wrap" style="margin-bottom:14px">{c}</div>' for c in overlay_charts) if overlay_charts else '<p class="chart-empty">Not enough data for overlay charts yet.</p>'}
    </div>
    """
    return page_shell("Compare", body, active_nav="compare")


# ================================================================
# SCREENER PAGE
# ================================================================

def render_screener_page(
    tokens: list,
    tier: str = "all",
    min_change: float = None,
    max_change: float = None,
    sort_by: str = "marketcap_usd",
    order: str = "desc",
) -> str:
    tiers = [
        ("all", "All"),
        ("mega", "Mega >$100B"),
        ("large", "Large $10B-$100B"),
        ("mid", "Mid $1B-$10B"),
        ("small", "Small $100M-$1B"),
        ("micro", "Micro <$100M"),
    ]
    tier_btns = "".join(
        f'<a href="/screener?tier={key}&sort={sort_by}&order={order}" '
        f'class="filter-btn{" active" if key == tier else ""}">{label}</a>'
        for key, label in tiers
    )

    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        arrow = " &darr;" if sort_by == col and order == "desc" else " &uarr;" if sort_by == col else ""
        return f'<a href="/screener?tier={tier}&sort={col}&order={new_order}" class="sort-link">{label}{arrow}</a>'

    rows = []
    for i, t in enumerate(tokens):
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        zone_html = f'<span class="zone {mvrv_zone(mvrv)[1]}">{mvrv_zone(mvrv)[0]}</span>' if mvrv else "&mdash;"
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get("name", slug))}</strong> <span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></a></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num {css_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-num">{fmt_usd(t.get("marketcap_usd"))}</td>
            <td class="col-num">{fmt_usd(t.get("volume_usd"))}</td>
            <td class="col-num hide-mobile">{f"{mvrv:.2f}" if mvrv else "&mdash;"}</td>
            <td class="col-tag hide-mobile">{zone_html}</td>
            <td class="col-num hide-mobile">{fmt_num(t.get("daily_active_addresses"))}</td>
        </tr>""")

    body = f"""
    <h1 class="page-title">Screener</h1>
    <p class="page-subtitle">Filter and sort {len(tokens)} tokens by on-chain metrics</p>

    <div class="filter-bar">
        <div class="filter-group">
            <span class="filter-label">Tier:</span>
            {tier_btns}
        </div>
    </div>

    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th>
                <th>Name</th>
                <th class="col-num">{sort_link("price_usd", "Price")}</th>
                <th class="col-num">{sort_link("price_usd_change", "24h")}</th>
                <th class="col-num">{sort_link("marketcap_usd", "Market Cap")}</th>
                <th class="col-num">{sort_link("volume_usd", "Volume")}</th>
                <th class="col-num hide-mobile">{sort_link("mvrv_usd", "MVRV")}</th>
                <th class="col-tag hide-mobile">Zone</th>
                <th class="col-num hide-mobile">{sort_link("daily_active_addresses", "Active Addr")}</th>
            </tr></thead>
            <tbody>
                {"".join(rows) if rows else '<tr><td colspan="9" class="empty-cell">No tokens match the filter criteria.</td></tr>'}
            </tbody>
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

    legend_items = [
        ("Deep Value", "zone-extreme-low"),
        ("Undervalued", "zone-undervalued"),
        ("Fair", "zone-fair"),
        ("Elevated", "zone-fair-high"),
        ("Overvalued", "zone-overvalued"),
        ("Euphoria", "zone-extreme-high"),
    ]
    legend = "".join(
        f'<span class="legend-item"><span class="zone {cls}">{label}</span> {zone_counts.get(label, 0)}</span>'
        for label, cls in legend_items
    )

    rows = []
    for i, t in enumerate(tokens):
        slug = t.get("slug", "")
        mvrv = t.get("mvrv_usd")
        if mvrv is None:
            continue
        zone_label, zone_css, _ = mvrv_zone(mvrv)
        bar_pct = min(100, max(0, mvrv / 4 * 100))
        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get("name", slug))}</strong> <span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></a></td>
            <td class="col-num bold">{fmt_usd(t.get("price_usd"))}</td>
            <td class="col-num bold">{mvrv:.2f}</td>
            <td class="col-tag"><span class="zone {zone_css}">{zone_label}</span></td>
            <td class="hide-mobile" style="min-width:120px"><div class="mini-bar-track"><div class="mini-bar-fill" style="width:{bar_pct:.0f}%"></div></div></td>
        </tr>""")

    body = f"""
    <h1 class="page-title">Valuation Scanner</h1>
    <p class="page-subtitle">MVRV-based valuation zones across {len(tokens)} tokens</p>

    <div class="val-legend">{legend}</div>

    <div class="table-wrap">
        <table class="data-table">
            <thead><tr>
                <th class="col-rank">#</th>
                <th>Name</th>
                <th class="col-num">Price</th>
                <th class="col-num">MVRV</th>
                <th class="col-tag">Zone</th>
                <th class="hide-mobile">MVRV Bar</th>
            </tr></thead>
            <tbody>
                {"".join(rows) if rows else '<tr><td colspan="6" class="empty-cell">MVRV data not yet available. Check back after sync completes.</td></tr>'}
            </tbody>
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
            break
    if status == "ready":
        current_idx = len(phases) - 1

    pipeline_html = ""
    for i, (label, _) in enumerate(phases):
        if status == "ready" or i < current_idx:
            cls = "done"
        elif i == current_idx:
            cls = "active"
        else:
            cls = ""
        pipeline_html += f'<span class="sync-step {cls}"><span class="sync-step-dot"></span>{label}</span>'

    stats_grid = f"""
    <div class="sync-stats-grid">
        <div class="sync-stat"><div class="sync-stat-label">Projects</div><div class="sync-stat-value">{fmt_num(cs.get("projects_cached", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Data Points</div><div class="sync-stat-value">{fmt_num(cs.get("total_data_points_pulled", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Timeseries Rows</div><div class="sync-stat-value">{fmt_num(cs.get("timeseries_rows", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">DB Size</div><div class="sync-stat-value">{cs.get("db_size_mb", 0):.0f} MB</div></div>
        <div class="sync-stat"><div class="sync-stat-label">API Requests</div><div class="sync-stat-value">{fmt_num(cl.get("total_requests", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Successful Pulls</div><div class="sync-stat-value">{fmt_num(cs.get("successful_pulls", 0))}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Errors</div><div class="sync-stat-value">{cl.get("errors", 0)}</div></div>
        <div class="sync-stat"><div class="sync-stat-label">Cache Hits</div><div class="sync-stat-value">{fmt_num(cl.get("cache_hits", 0))}</div></div>
    </div>"""

    error_html = ""
    last_err = cl.get("last_error")
    if last_err:
        error_html = f'<div class="sync-error"><strong>Last Error:</strong> {html_mod.escape(str(last_err)[:300])}</div>'

    body = f"""
    <h1 class="page-title">Data Sync</h1>
    <p class="page-subtitle">Pipeline status and cache statistics</p>

    <div class="sync-pipeline">{pipeline_html}</div>

    {stats_grid}
    {error_html}

    <p class="sync-hint">This page is a snapshot. Refresh to see latest progress.</p>
    """
    return page_shell("Sync", body, active_nav="sync")
