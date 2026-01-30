"""
Server-Side Rendering module for the On-Chain Analytics Dashboard.

All HTML is rendered server-side since JS may not execute
in all browser environments. Navigation uses standard <a> links.
"""

import html as html_mod
from datetime import datetime, timezone
from typing import Optional

from .svg_charts import (
    sparkline_svg, line_chart_svg, chart_panel, comparison_table,
    market_heatmap_svg, dominance_bar_svg, sentiment_gauge_svg, mini_trend_svg,
)


# ============================================================
# FORMATTING HELPERS
# ============================================================

def fmt_usd(n) -> str:
    if n is None:
        return "&mdash;"
    a = abs(n)
    if a >= 1e12:
        return f"${n/1e12:.2f}T"
    if a >= 1e9:
        return f"${n/1e9:.2f}B"
    if a >= 1e6:
        return f"${n/1e6:.2f}M"
    if a >= 1e3:
        return f"${n/1e3:.1f}K"
    if a >= 1:
        return f"${n:.2f}"
    if a >= 0.01:
        return f"${n:.4f}"
    return f"${n:.6f}"


def fmt_num(n) -> str:
    if n is None:
        return "&mdash;"
    a = abs(n)
    if a >= 1e12:
        return f"{n/1e12:.2f}T"
    if a >= 1e9:
        return f"{n/1e9:.2f}B"
    if a >= 1e6:
        return f"{n/1e6:.2f}M"
    if a >= 1e3:
        return f"{n/1e3:.1f}K"
    if a >= 100:
        return f"{n:.0f}"
    if a >= 1:
        return f"{n:.2f}"
    if a >= 0.001:
        return f"{n:.4f}"
    return f"{n:.6f}"


def fmt_pct(n) -> str:
    if n is None:
        return "&mdash;"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}%"


def pct_class(n) -> str:
    if n is None:
        return "num-neutral"
    if n > 0:
        return "num-positive"
    if n < 0:
        return "num-negative"
    return "num-neutral"


def fmt_date(dt_str: str) -> str:
    """Format ISO datetime to short date."""
    try:
        d = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return d.strftime("%b %d, %Y")
    except Exception:
        return dt_str[:10] if dt_str else "&mdash;"


def fmt_date_short(dt_str: str) -> str:
    try:
        d = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return d.strftime("%b %d")
    except Exception:
        return dt_str[:10] if dt_str else ""


METRIC_LABELS = {
    "price_usd": "Price",
    "marketcap_usd": "Market Cap",
    "volume_usd": "Volume (24h)",
    "daily_active_addresses": "Active Addresses",
    "active_addresses_24h": "Active Addr (24h)",
    "transaction_volume": "Tx Volume",
    "mvrv_usd": "MVRV",
    "nvt": "NVT Ratio",
    "exchange_balance": "Exchange Balance",
    "exchange_inflow": "Exchange Inflow",
    "exchange_outflow": "Exchange Outflow",
    "dev_activity": "Dev Activity",
    "dev_activity_contributors_count": "Dev Contributors",
    "network_growth": "Network Growth",
    "circulation": "Circulation",
    "velocity": "Velocity",
    "mean_age": "Mean Coin Age",
    "realized_value_usd": "Realized Value",
    "mean_realized_price_usd": "Mean Realized Price",
    "age_consumed": "Age Consumed",
    "whale_transaction_count_100k_usd_to_inf": "Whale Txs (>$100K)",
    "whale_transaction_count_1m_usd_to_inf": "Whale Txs (>$1M)",
    "supply_on_exchanges": "Supply on Exchanges",
    "supply_outside_exchanges": "Supply off Exchanges",
    "percent_of_total_supply_on_exchanges": "% Supply on Exchanges",
    "sentiment_balance_total": "Sentiment Balance",
    "weighted_sentiment_total": "Weighted Sentiment",
    "social_volume_total": "Social Volume",
    "social_dominance_total": "Social Dominance",
    "stock_to_flow": "Stock to Flow",
    "network_profit_loss": "Network P/L",
    "dormant_circulation_90d": "Dormant Circ. (90d)",
    "dormant_circulation_365d": "Dormant Circ. (1Y)",
    "transaction_volume_in_profit": "Tx Vol in Profit",
    "transaction_volume_in_loss": "Tx Vol in Loss",
    "active_deposits": "Active Deposits",
    "active_withdrawals": "Active Withdrawals",
    "miners_balance": "Miners Balance",
    "gas_used": "Gas Used",
    "difficulty": "Difficulty",
}


def metric_label(key: str) -> str:
    return METRIC_LABELS.get(key, key.replace("_", " ").title())


def fmt_metric_val(key: str, val) -> str:
    if val is None:
        return "&mdash;"
    if "usd" in key and "mvrv" not in key and "nvt" not in key and "percent" not in key:
        return fmt_usd(val)
    if "percent" in key:
        return f"{val:.2f}%"
    return fmt_num(val)


# ============================================================
# MVRV ZONE ANALYSIS
# ============================================================

def mvrv_zone(val):
    """Returns (label, css_class, description)."""
    if val is None:
        return ("N/A", "zone-neutral", "Insufficient data")
    if val > 3.5:
        return ("EXTREME HIGH", "zone-extreme-high", "Market is extremely overvalued. Historically signals major correction risk.")
    if val > 2.5:
        return ("OVERVALUED", "zone-overvalued", "Market is overvalued. Profit-taking likely. Consider reducing exposure.")
    if val > 1.5:
        return ("FAIR-HIGH", "zone-fair-high", "Above fair value. Moderate risk. Watch for reversal signals.")
    if val > 1.0:
        return ("FAIR", "zone-fair", "Market valued fairly. Neutral risk positioning.")
    if val > 0.5:
        return ("UNDERVALUED", "zone-undervalued", "Below fair value. Historically a good accumulation zone.")
    return ("EXTREME LOW", "zone-extreme-low", "Extremely undervalued. Strong historical buy signal. High conviction zone.")


def nvt_zone(val):
    if val is None:
        return ("N/A", "zone-neutral", "Insufficient data")
    if val > 200:
        return ("OVERVALUED", "zone-overvalued", "Network value far exceeds transaction utility. Speculative premium.")
    if val > 100:
        return ("FAIR-HIGH", "zone-fair-high", "Moderately high. Value exceeds current utility.")
    if val > 50:
        return ("FAIR", "zone-fair", "Balanced ratio. Value supported by network activity.")
    if val > 20:
        return ("UNDERVALUED", "zone-undervalued", "High utility relative to value. Potentially underpriced.")
    return ("EXTREME LOW", "zone-extreme-low", "Very high transaction utility. Strong fundamentals.")


# ============================================================
# PAGE LAYOUT
# ============================================================

def page_shell(title: str, content: str, active_nav: str = "") -> str:
    """Wrap content in the full page shell with header/footer."""
    def nav_cls(name):
        return "nav-link active" if name == active_nav else "nav-link"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — On-Chain Analytics</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/dashboard.css">
</head>
<body>
<header class="header">
    <div class="header-inner">
        <div class="header-left">
            <a href="/" class="logo">ONCHAIN</a>
            <span class="logo-sub">analytics</span>
        </div>
        <nav class="header-nav">
            <a href="/" class="{nav_cls('market')}">Market</a>
            <a href="/screener" class="{nav_cls('screener')}">Screener</a>
            <a href="/compare" class="{nav_cls('compare')}">Compare</a>
            <a href="/valuation" class="{nav_cls('valuation')}">Valuation</a>
            <a href="/sync" class="{nav_cls('sync')}">Sync</a>
        </nav>
        <div class="header-right">
            <div class="status-indicator live"></div>
        </div>
    </div>
</header>
<main class="main">
{content}
</main>
<footer class="footer">
    <span>Powered by Santiment on-chain data</span>
</footer>
</body>
</html>"""


# ============================================================
# MARKET OVERVIEW PAGE
# ============================================================

def render_market_page(
    tokens: list, pull_status: str, last_pull: str = None,
    page: int = 1, per_page: int = 100, total: int = 0,
    universe_size: int = 0, cache_stats: dict = None,
    gainers: list = None, losers: list = None,
    all_tokens_for_charts: list = None,
    mcap_trend_data: list = None,
    top_by_volume: list = None,
    top_by_daa: list = None,
) -> str:
    """Render the full market overview page with pagination and rich dashboard sections."""
    all_chart_tokens = all_tokens_for_charts or tokens

    # Summary stats
    total_mcap = sum(t.get("marketcap_usd") or 0 for t in all_chart_tokens)
    total_vol = sum(t.get("volume_usd") or 0 for t in all_chart_tokens)
    mvrv_vals = [t["mvrv_usd"] for t in all_chart_tokens if t.get("mvrv_usd") is not None]
    nvt_vals = [t["nvt"] for t in all_chart_tokens if t.get("nvt") is not None]
    avg_mvrv = sum(mvrv_vals) / len(mvrv_vals) if mvrv_vals else None
    avg_nvt = sum(nvt_vals) / len(nvt_vals) if nvt_vals else None

    daa_vals = [t["daily_active_addresses"] for t in all_chart_tokens if t.get("daily_active_addresses")]
    total_daa = sum(daa_vals) if daa_vals else None

    # Count positive / negative tokens
    pos_count = sum(1 for t in all_chart_tokens if (t.get("price_usd_change") or 0) > 0)
    neg_count = sum(1 for t in all_chart_tokens if (t.get("price_usd_change") or 0) < 0)
    unchanged_count = len(all_chart_tokens) - pos_count - neg_count

    update_str = ""
    if last_pull:
        try:
            d = datetime.fromisoformat(last_pull.replace("Z", "+00:00"))
            update_str = f' <span class="view-meta">Updated {d.strftime("%H:%M UTC")}</span>'
        except Exception:
            pass

    # Pagination info
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    start_rank = (page - 1) * per_page

    # ============================================================
    # SYNC BANNER (shown when still pulling)
    # ============================================================
    sync_banner = ""
    is_syncing = pull_status not in ("ready", "idle", "skipped")
    if is_syncing:
        cs = cache_stats or {}
        ts_rows = cs.get("timeseries_rows", 0)
        db_mb = cs.get("db_size_mb", 0)
        pct_done = 0
        if universe_size and total:
            pct_done = min(99, int(total / universe_size * 100))
        phase_labels = {
            "phase1_discovery": "Phase 1: Discovering projects...",
            "phase1_pulling": "Phase 1: Loading top 10 tokens...",
            "phase1_complete": "Phase 1 complete. Starting universe pull...",
            "phase2_universe": f"Phase 2: Pulling core data for all {universe_size} tokens (7yr history)",
            "phase2_complete": "Phase 2 complete. Starting deep pull...",
            "phase3_deep": "Phase 3: Pulling deep metrics for top 200 tokens...",
            "refreshing": "Refreshing latest data...",
        }
        phase_label = phase_labels.get(pull_status, pull_status)

        sync_banner = f"""
    <div class="sync-banner">
        <div class="sync-banner-inner">
            <div class="sync-status-row">
                <span class="sync-dot"></span>
                <strong>Data Sync In Progress</strong>
                <span class="sync-phase">{html_mod.escape(phase_label)}</span>
            </div>
            <div class="sync-progress-bar">
                <div class="sync-progress-fill" style="width:{pct_done}%"></div>
            </div>
            <div class="sync-stats-row">
                <span>{total} / {universe_size} tokens loaded ({pct_done}%)</span>
                <span>{fmt_num(ts_rows)} data points</span>
                <span>{db_mb:.1f} MB cached</span>
                <a href="/sync" class="sync-detail-link">Full details &rarr;</a>
            </div>
        </div>
    </div>"""

    # ============================================================
    # HERO STATS ROW — with mini trend chart
    # ============================================================
    mcap_trend_html = ""
    if mcap_trend_data and len(mcap_trend_data) > 3:
        mcap_trend_html = f'<div class="stat-trend">{mini_trend_svg(mcap_trend_data, width=120, height=32, color="#111111")}</div>'

    # ============================================================
    # MARKET SENTIMENT GAUGE
    # ============================================================
    sentiment_html = ""
    if avg_mvrv is not None:
        sentiment_html = f"""
    <div class="dashboard-sentiment">
        <div class="sentiment-gauge-wrap">
            {sentiment_gauge_svg(avg_mvrv, min_val=0, max_val=4, label="Avg MVRV (Market Sentiment)")}
        </div>
        <div class="sentiment-details">
            <div class="sentiment-zone">
                <span class="zone-tag {mvrv_zone(avg_mvrv)[1]}">{mvrv_zone(avg_mvrv)[0]}</span>
            </div>
            <p class="sentiment-desc">{mvrv_zone(avg_mvrv)[2]}</p>
            <div class="sentiment-stats">
                <span class="sentiment-stat"><strong>{pos_count}</strong> tokens up</span>
                <span class="sentiment-stat"><strong>{neg_count}</strong> tokens down</span>
                <span class="sentiment-stat"><strong>{unchanged_count}</strong> flat</span>
            </div>
        </div>
    </div>"""

    # ============================================================
    # DOMINANCE BAR
    # ============================================================
    dominance_html = ""
    if all_chart_tokens and len(all_chart_tokens) > 3:
        dom_sorted = sorted(all_chart_tokens, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)
        dominance_html = f"""
    <div class="dashboard-section">
        <h3 class="dash-section-title">Market Dominance</h3>
        <div class="chart-container compact">
            {dominance_bar_svg(dom_sorted)}
        </div>
    </div>"""

    # ============================================================
    # MARKET HEATMAP
    # ============================================================
    heatmap_html = ""
    if all_chart_tokens and len(all_chart_tokens) > 5:
        heatmap_html = f"""
    <div class="dashboard-section">
        <h3 class="dash-section-title">Market Heatmap <span class="dash-section-sub">24h Performance</span></h3>
        <div class="chart-container">
            {market_heatmap_svg(all_chart_tokens, max_tokens=50)}
        </div>
    </div>"""

    # ============================================================
    # TOP BY VOLUME / TOP BY ACTIVE ADDRESSES
    # ============================================================
    top_sections_html = ""
    vol_list = top_by_volume or sorted(all_chart_tokens, key=lambda t: t.get("volume_usd") or 0, reverse=True)[:8]
    daa_list = top_by_daa or sorted([t for t in all_chart_tokens if t.get("daily_active_addresses")], key=lambda t: t.get("daily_active_addresses") or 0, reverse=True)[:8]

    if vol_list or daa_list:
        vol_items = ""
        for i, t in enumerate(vol_list[:8]):
            slug = t.get("slug", "")
            pct = t.get("price_usd_change")
            vol_items += (
                f'<a href="/token/{slug}" class="top-item">'
                f'<span class="top-rank">{i+1}</span>'
                f'<span class="top-name"><strong>{html_mod.escape(t.get("name", slug)[:18])}</strong>'
                f' <span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></span>'
                f'<span class="top-metric">{fmt_usd(t.get("volume_usd"))}</span>'
                f'<span class="top-change {pct_class(pct)}">{fmt_pct(pct)}</span>'
                f'</a>'
            )

        daa_items = ""
        for i, t in enumerate(daa_list[:8]):
            slug = t.get("slug", "")
            pct = t.get("price_usd_change")
            daa_items += (
                f'<a href="/token/{slug}" class="top-item">'
                f'<span class="top-rank">{i+1}</span>'
                f'<span class="top-name"><strong>{html_mod.escape(t.get("name", slug)[:18])}</strong>'
                f' <span class="ticker">{html_mod.escape(t.get("ticker", ""))}</span></span>'
                f'<span class="top-metric">{fmt_num(t.get("daily_active_addresses"))}</span>'
                f'<span class="top-change {pct_class(pct)}">{fmt_pct(pct)}</span>'
                f'</a>'
            )

        top_sections_html = f"""
    <div class="top-lists-row">
        <div class="top-list-col">
            <h4 class="top-list-title">Top by Volume</h4>
            <div class="top-list">{vol_items}</div>
        </div>
        <div class="top-list-col">
            <h4 class="top-list-title">Top by Active Addresses</h4>
            <div class="top-list">{daa_items}</div>
        </div>
    </div>"""

    # ============================================================
    # MAIN TABLE
    # ============================================================
    rows = []
    for i, t in enumerate(tokens):
        rank = start_rank + i + 1
        slug = t.get("slug", "")
        pct = t.get("price_usd_change")
        mvrv = t.get("mvrv_usd")
        daa = t.get("daily_active_addresses")

        # MVRV zone tag
        if mvrv is not None:
            zone_label, zone_cls, _ = mvrv_zone(mvrv)
            zone_html = f'<span class="zone-tag {zone_cls}">{zone_label}</span>'
        else:
            zone_html = "&mdash;"

        # 7-day sparkline
        spark_data = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark_data, width=80, height=24) if spark_data else "&mdash;"

        rows.append(f"""<tr>
            <td class="col-rank">{rank}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get('name', slug))}</strong> <span class="ticker">{html_mod.escape(t.get('ticker', ''))}</span></a></td>
            <td class="col-num num-bold">{fmt_usd(t.get('price_usd'))}</td>
            <td class="col-num {pct_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-spark hide-mobile">{spark_html}</td>
            <td class="col-num">{fmt_usd(t.get('marketcap_usd'))}</td>
            <td class="col-num">{fmt_usd(t.get('volume_usd'))}</td>
            <td class="col-num hide-mobile">{f'{mvrv:.2f}' if mvrv is not None else '&mdash;'}</td>
            <td class="col-tag hide-mobile">{zone_html}</td>
            <td class="col-num hide-mobile">{fmt_num(daa)}</td>
        </tr>""")

    table_body = "\n".join(rows) if rows else '<tr><td colspan="10" class="empty-cell">Data is being pulled. Refresh in a few minutes...</td></tr>'

    # Pagination controls
    pagination_html = ""
    if total_pages > 1:
        pages = []
        if page > 1:
            pages.append(f'<a href="/?page={page-1}&per_page={per_page}" class="page-link">&laquo; Prev</a>')
        else:
            pages.append('<span class="page-link disabled">&laquo; Prev</span>')

        for p in range(1, total_pages + 1):
            if p == page:
                pages.append(f'<span class="page-link active">{p}</span>')
            elif p <= 3 or p > total_pages - 2 or abs(p - page) <= 2:
                pages.append(f'<a href="/?page={p}&per_page={per_page}" class="page-link">{p}</a>')
            elif (p == 4 and page > 6) or (p == total_pages - 2 and page < total_pages - 5):
                pages.append('<span class="page-link ellipsis">&hellip;</span>')

        if page < total_pages:
            pages.append(f'<a href="/?page={page+1}&per_page={per_page}" class="page-link">&raquo; Next</a>')
        else:
            pages.append('<span class="page-link disabled">&raquo; Next</span>')

        pagination_html = f'<div class="pagination">{"".join(pages)}</div>'

    # Status subtitle
    data_info = f"{total} tokens with data"
    if universe_size:
        data_info += f" (of {universe_size} discovered)"
    showing_info = f"Showing {start_rank+1}&ndash;{min(start_rank + per_page, total)}" if total > 0 else "No data yet"

    content = f"""
    <div class="view-header">
        <div>
            <h2 class="view-title">Market Overview</h2>
            <p class="view-subtitle">{data_info} &middot; {pull_status}{update_str}</p>
        </div>
    </div>

    {sync_banner}

    <div class="stats-row">
        <div class="stat-card stat-card-hero">
            <div class="stat-label">Total Market Cap</div>
            <div class="stat-value">{fmt_usd(total_mcap)}</div>
            {mcap_trend_html}
        </div>
        <div class="stat-card">
            <div class="stat-label">24h Volume</div>
            <div class="stat-value">{fmt_usd(total_vol)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg MVRV</div>
            <div class="stat-value">{f'{avg_mvrv:.2f}' if avg_mvrv is not None else '&mdash;'}</div>
            <div class="stat-sub">{mvrv_zone(avg_mvrv)[0] if avg_mvrv else ''}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Avg NVT</div>
            <div class="stat-value">{f'{avg_nvt:.1f}' if avg_nvt is not None else '&mdash;'}</div>
        </div>
        <div class="stat-card hide-mobile">
            <div class="stat-label">Active Addresses</div>
            <div class="stat-value">{fmt_num(total_daa)}</div>
        </div>
        <div class="stat-card hide-mobile">
            <div class="stat-label">Market Breadth</div>
            <div class="stat-value breadth-value"><span class="num-positive">{pos_count}</span> / <span class="num-negative">{neg_count}</span></div>
            <div class="stat-sub">up / down</div>
        </div>
    </div>

    {sentiment_html}

    {dominance_html}

    {heatmap_html}

    {_render_gainers_losers(gainers or [], losers or [])}

    {top_sections_html}

    <div class="dashboard-section">
        <h3 class="dash-section-title">All Tokens <span class="dash-section-sub">{showing_info} of {total}</span></h3>

        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th class="col-rank">#</th>
                        <th class="col-name">Name</th>
                        <th class="col-num">Price</th>
                        <th class="col-num">24h</th>
                        <th class="col-spark hide-mobile">7d</th>
                        <th class="col-num">Market Cap</th>
                        <th class="col-num">Volume</th>
                        <th class="col-num hide-mobile">MVRV</th>
                        <th class="col-tag hide-mobile">Zone</th>
                        <th class="col-num hide-mobile">Active Addr</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
        </div>

        {pagination_html}
    </div>
    """
    return page_shell("Market", content, active_nav="market")


# ============================================================
# VALUATION SCANNER PAGE
# ============================================================

def render_valuation_page(tokens_with_valuation: list) -> str:
    """Render the valuation scanner page."""
    rows = []
    for t in tokens_with_valuation:
        slug = t.get("slug", "")
        mvrv = t.get("mvrv_usd")
        nvt_v = t.get("nvt")
        mvrv_label, mvrv_cls, mvrv_desc = mvrv_zone(mvrv)
        nvt_label, nvt_cls, _ = nvt_zone(nvt_v)

        # Valuation bar for MVRV (scale 0-4)
        bar_pct = 0
        if mvrv is not None:
            bar_pct = max(0, min(100, (mvrv / 4.0) * 100))

        mvrv_90 = t.get("mvrv_90d")
        mvrv_365 = t.get("mvrv_365d")

        rows.append(f"""<tr>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get('name', slug))}</strong> <span class="ticker">{html_mod.escape(t.get('ticker', ''))}</span></a></td>
            <td class="col-num num-bold">{fmt_usd(t.get('price_usd'))}</td>
            <td class="col-num num-bold">{f'{mvrv:.2f}' if mvrv is not None else '&mdash;'}</td>
            <td class="col-tag"><span class="zone-tag {mvrv_cls}">{mvrv_label}</span></td>
            <td class="col-bar hide-mobile">
                <div class="mini-bar-track"><div class="mini-bar-fill" style="width:{bar_pct:.0f}%"></div></div>
            </td>
            <td class="col-num">{f'{nvt_v:.1f}' if nvt_v is not None else '&mdash;'}</td>
            <td class="col-tag hide-mobile"><span class="zone-tag {nvt_cls}">{nvt_label}</span></td>
            <td class="col-num hide-mobile">{f'{mvrv_90:.2f}' if mvrv_90 is not None else '&mdash;'}</td>
            <td class="col-num hide-mobile">{f'{mvrv_365:.2f}' if mvrv_365 is not None else '&mdash;'}</td>
        </tr>""")

    table_body = "\n".join(rows) if rows else '<tr><td colspan="9" class="empty-cell">Waiting for valuation data...</td></tr>'

    # Count zones
    zone_counts = {}
    for t in tokens_with_valuation:
        label = mvrv_zone(t.get("mvrv_usd"))[0]
        zone_counts[label] = zone_counts.get(label, 0) + 1

    zone_summary = " &middot; ".join(f'{v} {k}' for k, v in sorted(zone_counts.items(), key=lambda x: -x[1]))

    content = f"""
    <div class="view-header">
        <h2 class="view-title">Valuation Scanner</h2>
        <p class="view-subtitle">MVRV zones and NVT ratios across {len(tokens_with_valuation)} tokens</p>
    </div>

    <div class="valuation-legend">
        <div class="legend-item"><span class="zone-tag zone-extreme-low">EXTREME LOW</span> Strong buy signal</div>
        <div class="legend-item"><span class="zone-tag zone-undervalued">UNDERVALUED</span> Accumulation zone</div>
        <div class="legend-item"><span class="zone-tag zone-fair">FAIR</span> Neutral</div>
        <div class="legend-item"><span class="zone-tag zone-fair-high">FAIR-HIGH</span> Moderate risk</div>
        <div class="legend-item"><span class="zone-tag zone-overvalued">OVERVALUED</span> Caution</div>
        <div class="legend-item"><span class="zone-tag zone-extreme-high">EXTREME HIGH</span> Major correction risk</div>
    </div>

    {f'<p class="zone-summary">{zone_summary}</p>' if zone_summary else ''}

    <div class="table-wrap">
        <table class="data-table">
            <thead>
                <tr>
                    <th class="col-name">Token</th>
                    <th class="col-num">Price</th>
                    <th class="col-num">MVRV</th>
                    <th class="col-tag">Zone</th>
                    <th class="col-bar hide-mobile">Range</th>
                    <th class="col-num">NVT</th>
                    <th class="col-tag hide-mobile">NVT Zone</th>
                    <th class="col-num hide-mobile">MVRV 90d</th>
                    <th class="col-num hide-mobile">MVRV 1Y</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>
    </div>
    """
    return page_shell("Valuation Scanner", content, active_nav="valuation")


# ============================================================
# TOKEN PROFILE PAGE
# ============================================================

def render_token_profile(project: dict, metrics: dict, slug: str) -> str:
    """Render a full in-depth token profile page."""
    name = project.get("name", slug)
    ticker = project.get("ticker", "")
    infra = project.get("infrastructure", "")

    # Price data
    price_m = metrics.get("price_usd", {})
    price = price_m.get("latest")
    price_data = price_m.get("data", [])
    price_change = None
    price_7d = None
    price_30d = None
    if len(price_data) >= 2:
        prev = price_data[-2].get("value")
        if prev and prev != 0:
            price_change = ((price - prev) / prev) * 100
    if len(price_data) >= 7:
        p7 = price_data[-7].get("value")
        if p7 and p7 != 0 and price:
            price_7d = ((price - p7) / p7) * 100
    if len(price_data) >= 30:
        p30 = price_data[-30].get("value")
        if p30 and p30 != 0 and price:
            price_30d = ((price - p30) / p30) * 100

    # Hero section
    change_parts = []
    if price_change is not None:
        change_parts.append(f'<span class="change-badge {pct_class(price_change)}">24h {fmt_pct(price_change)}</span>')
    if price_7d is not None:
        change_parts.append(f'<span class="change-badge {pct_class(price_7d)}">7d {fmt_pct(price_7d)}</span>')
    if price_30d is not None:
        change_parts.append(f'<span class="change-badge {pct_class(price_30d)}">30d {fmt_pct(price_30d)}</span>')
    changes_html = " ".join(change_parts)

    # Key metrics cards
    key_cards = [
        ("marketcap_usd", "Market Cap"),
        ("volume_usd", "Volume 24h"),
        ("mvrv_usd", "MVRV"),
        ("nvt", "NVT"),
        ("daily_active_addresses", "Active Addresses"),
        ("dev_activity", "Dev Activity"),
        ("network_growth", "Network Growth"),
        ("transaction_volume", "Tx Volume"),
        ("exchange_balance", "Exchange Balance"),
        ("circulation", "Circulation"),
        ("velocity", "Velocity"),
        ("mean_age", "Mean Coin Age"),
    ]

    cards_html = ""
    for mkey, label in key_cards:
        m = metrics.get(mkey, {})
        val = m.get("latest")
        avg = m.get("avg_30d")
        if val is None:
            continue
        val_str = fmt_metric_val(mkey, val)
        avg_str = fmt_metric_val(mkey, avg) if avg is not None else ""

        # Change vs 30d avg
        change_vs_avg = ""
        if avg is not None and avg != 0:
            pct_diff = ((val - avg) / abs(avg)) * 100
            change_vs_avg = f'<div class="card-vs-avg {pct_class(pct_diff)}">{fmt_pct(pct_diff)} vs 30d avg</div>'

        cards_html += f"""
        <div class="metric-card">
            <div class="metric-card-label">{label}</div>
            <div class="metric-card-value">{val_str}</div>
            {f'<div class="metric-card-avg">30d avg: {avg_str}</div>' if avg_str else ''}
            {change_vs_avg}
        </div>"""

    # ============================================================
    # VALUATION SECTION
    # ============================================================
    mvrv_val = metrics.get("mvrv_usd", {}).get("latest")
    nvt_val = metrics.get("nvt", {}).get("latest")

    valuation_html = ""
    if mvrv_val is not None or nvt_val is not None:
        valuation_items = []

        if mvrv_val is not None:
            label, cls, desc = mvrv_zone(mvrv_val)
            mvrv_min = metrics.get("mvrv_usd", {}).get("min_365d")
            mvrv_max = metrics.get("mvrv_usd", {}).get("max_365d")
            mvrv_avg = metrics.get("mvrv_usd", {}).get("avg_30d")

            bar_pct = 50
            if mvrv_min is not None and mvrv_max is not None and (mvrv_max - mvrv_min) > 0:
                bar_pct = max(0, min(100, ((mvrv_val - mvrv_min) / (mvrv_max - mvrv_min)) * 100))

            valuation_items.append(f"""
            <div class="val-analysis-card">
                <div class="val-analysis-header">
                    <h4 class="val-metric-name">MVRV Ratio</h4>
                    <span class="zone-tag {cls}">{label}</span>
                </div>
                <div class="val-big-number">{mvrv_val:.3f}</div>
                <p class="val-description">{desc}</p>
                <div class="val-bar-row">
                    <span class="val-bar-label">1Y Range</span>
                    <div class="val-bar-track">
                        <div class="val-bar-fill" style="width:{bar_pct:.0f}%"></div>
                        <div class="val-bar-marker" style="left:{bar_pct:.0f}%"></div>
                    </div>
                    <span class="val-bar-value">{bar_pct:.0f}th pctl</span>
                </div>
                <div class="val-stats-row">
                    <div class="val-stat"><span class="val-stat-label">1Y Low</span> <span class="val-stat-val">{f'{mvrv_min:.2f}' if mvrv_min is not None else '&mdash;'}</span></div>
                    <div class="val-stat"><span class="val-stat-label">30d Avg</span> <span class="val-stat-val">{f'{mvrv_avg:.2f}' if mvrv_avg is not None else '&mdash;'}</span></div>
                    <div class="val-stat"><span class="val-stat-label">1Y High</span> <span class="val-stat-val">{f'{mvrv_max:.2f}' if mvrv_max is not None else '&mdash;'}</span></div>
                </div>
            </div>""")

        if nvt_val is not None:
            label, cls, desc = nvt_zone(nvt_val)
            nvt_min = metrics.get("nvt", {}).get("min_365d")
            nvt_max = metrics.get("nvt", {}).get("max_365d")
            nvt_avg = metrics.get("nvt", {}).get("avg_30d")

            bar_pct = 50
            if nvt_min is not None and nvt_max is not None and (nvt_max - nvt_min) > 0:
                bar_pct = max(0, min(100, ((nvt_val - nvt_min) / (nvt_max - nvt_min)) * 100))

            valuation_items.append(f"""
            <div class="val-analysis-card">
                <div class="val-analysis-header">
                    <h4 class="val-metric-name">NVT Ratio</h4>
                    <span class="zone-tag {cls}">{label}</span>
                </div>
                <div class="val-big-number">{nvt_val:.1f}</div>
                <p class="val-description">{desc}</p>
                <div class="val-bar-row">
                    <span class="val-bar-label">1Y Range</span>
                    <div class="val-bar-track">
                        <div class="val-bar-fill" style="width:{bar_pct:.0f}%"></div>
                        <div class="val-bar-marker" style="left:{bar_pct:.0f}%"></div>
                    </div>
                    <span class="val-bar-value">{bar_pct:.0f}th pctl</span>
                </div>
                <div class="val-stats-row">
                    <div class="val-stat"><span class="val-stat-label">1Y Low</span> <span class="val-stat-val">{f'{nvt_min:.1f}' if nvt_min is not None else '&mdash;'}</span></div>
                    <div class="val-stat"><span class="val-stat-label">30d Avg</span> <span class="val-stat-val">{f'{nvt_avg:.1f}' if nvt_avg is not None else '&mdash;'}</span></div>
                    <div class="val-stat"><span class="val-stat-label">1Y High</span> <span class="val-stat-val">{f'{nvt_max:.1f}' if nvt_max is not None else '&mdash;'}</span></div>
                </div>
            </div>""")

        valuation_html = f"""
        <div class="profile-section">
            <h3 class="section-heading">Valuation Analysis</h3>
            <div class="val-analysis-grid">
                {''.join(valuation_items)}
            </div>
        </div>"""

    # ============================================================
    # ON-CHAIN SECTION
    # ============================================================
    onchain_metrics = [
        ("daily_active_addresses", "Daily Active Addresses"),
        ("network_growth", "Network Growth"),
        ("transaction_volume", "Transaction Volume"),
        ("exchange_balance", "Exchange Balance"),
        ("exchange_inflow", "Exchange Inflow"),
        ("exchange_outflow", "Exchange Outflow"),
        ("circulation", "Circulation"),
        ("velocity", "Token Velocity"),
        ("mean_age", "Mean Coin Age (days)"),
        ("age_consumed", "Age Consumed"),
        ("whale_transaction_count_100k_usd_to_inf", "Whale Txs (>$100K)"),
        ("supply_on_exchanges", "Supply on Exchanges"),
        ("supply_outside_exchanges", "Supply off Exchanges"),
        ("percent_of_total_supply_on_exchanges", "% Supply on Exchanges"),
    ]
    onchain_rows = _build_metric_rows(metrics, onchain_metrics)

    onchain_html = ""
    if onchain_rows:
        onchain_html = f"""
        <div class="profile-section">
            <h3 class="section-heading">On-Chain Activity</h3>
            <div class="table-wrap">
                <table class="data-table compact">
                    <thead><tr>
                        <th class="col-name">Metric</th>
                        <th class="col-num">Current</th>
                        <th class="col-num">30d Avg</th>
                        <th class="col-num hide-mobile">vs Avg</th>
                        <th class="col-num hide-mobile">1Y Low</th>
                        <th class="col-num hide-mobile">1Y High</th>
                        <th class="col-num hide-mobile">Data Pts</th>
                    </tr></thead>
                    <tbody>{''.join(onchain_rows)}</tbody>
                </table>
            </div>
        </div>"""

    # ============================================================
    # SOCIAL & SENTIMENT
    # ============================================================
    social_metrics = [
        ("social_volume_total", "Social Volume"),
        ("social_dominance_total", "Social Dominance"),
        ("sentiment_balance_total", "Sentiment Balance"),
        ("weighted_sentiment_total", "Weighted Sentiment"),
    ]
    social_rows = _build_metric_rows(metrics, social_metrics)

    social_html = ""
    if social_rows:
        social_html = f"""
        <div class="profile-section">
            <h3 class="section-heading">Social &amp; Sentiment</h3>
            <div class="table-wrap">
                <table class="data-table compact">
                    <thead><tr>
                        <th class="col-name">Metric</th>
                        <th class="col-num">Current</th>
                        <th class="col-num">30d Avg</th>
                        <th class="col-num hide-mobile">vs Avg</th>
                        <th class="col-num hide-mobile">1Y Low</th>
                        <th class="col-num hide-mobile">1Y High</th>
                        <th class="col-num hide-mobile">Data Pts</th>
                    </tr></thead>
                    <tbody>{''.join(social_rows)}</tbody>
                </table>
            </div>
        </div>"""

    # ============================================================
    # DEVELOPMENT
    # ============================================================
    dev_metrics = [
        ("dev_activity", "Dev Activity"),
        ("dev_activity_contributors_count", "Dev Contributors"),
    ]
    dev_rows = _build_metric_rows(metrics, dev_metrics)

    dev_html = ""
    if dev_rows:
        dev_html = f"""
        <div class="profile-section">
            <h3 class="section-heading">Development</h3>
            <div class="table-wrap">
                <table class="data-table compact">
                    <thead><tr>
                        <th class="col-name">Metric</th>
                        <th class="col-num">Current</th>
                        <th class="col-num">30d Avg</th>
                        <th class="col-num hide-mobile">vs Avg</th>
                        <th class="col-num hide-mobile">1Y Low</th>
                        <th class="col-num hide-mobile">1Y High</th>
                        <th class="col-num hide-mobile">Data Pts</th>
                    </tr></thead>
                    <tbody>{''.join(dev_rows)}</tbody>
                </table>
            </div>
        </div>"""

    # ============================================================
    # CHARTS SECTION — Visual line charts for key metrics
    # ============================================================
    charts_html = ""

    # Price chart (full history)
    price_chart = ""
    if price_data and len(price_data) > 5:
        price_chart = line_chart_svg(
            [{"label": "Price (USD)", "data": price_data, "color": "#000000"}],
            title=f"{name} Price History ({len(price_data)} days)",
            metric_key="price_usd",
            height=320,
        )

    # Volume chart
    vol_data_full = metrics.get("volume_usd", {}).get("data", [])
    vol_chart = ""
    if vol_data_full and len(vol_data_full) > 5:
        vol_chart = line_chart_svg(
            [{"label": "Volume (USD)", "data": vol_data_full, "color": "#2563EB"}],
            title="Daily Volume",
            metric_key="volume_usd",
            height=220,
        )

    # Market cap chart
    mcap_data_full = metrics.get("marketcap_usd", {}).get("data", [])
    mcap_chart = ""
    if mcap_data_full and len(mcap_data_full) > 5:
        mcap_chart = line_chart_svg(
            [{"label": "Market Cap", "data": mcap_data_full, "color": "#7C3AED"}],
            title="Market Cap",
            metric_key="marketcap_usd",
            height=220,
        )

    # MVRV chart
    mvrv_data = metrics.get("mvrv_usd", {}).get("data", [])
    mvrv_chart = ""
    if mvrv_data and len(mvrv_data) > 5:
        mvrv_chart = line_chart_svg(
            [{"label": "MVRV Ratio", "data": mvrv_data, "color": "#D97706"}],
            title="MVRV Ratio History",
            metric_key="mvrv_usd",
            height=220,
        )

    # Active addresses chart
    daa_data = metrics.get("daily_active_addresses", {}).get("data", [])
    daa_chart = ""
    if daa_data and len(daa_data) > 5:
        daa_chart = line_chart_svg(
            [{"label": "Active Addresses", "data": daa_data, "color": "#16A34A"}],
            title="Daily Active Addresses",
            metric_key="daily_active_addresses",
            height=220,
        )

    # Exchange balance chart
    exch_data = metrics.get("exchange_balance", {}).get("data", [])
    exch_chart = ""
    if exch_data and len(exch_data) > 5:
        exch_chart = line_chart_svg(
            [{"label": "Exchange Balance", "data": exch_data, "color": "#DC2626"}],
            title="Exchange Balance",
            metric_key="exchange_balance",
            height=220,
        )

    # Dev activity chart
    dev_data_full = metrics.get("dev_activity", {}).get("data", [])
    dev_chart = ""
    if dev_data_full and len(dev_data_full) > 5:
        dev_chart = line_chart_svg(
            [{"label": "Dev Activity", "data": dev_data_full, "color": "#0891B2"}],
            title="Development Activity",
            metric_key="dev_activity",
            height=220,
        )

    # Assemble charts
    if price_chart:
        charts_html += f"""
        <div class="profile-section">
            <h3 class="section-heading">Price Chart</h3>
            <div class="chart-container">{price_chart}</div>
        </div>"""

    # Secondary charts in 2-column grid
    secondary_charts = [c for c in [vol_chart, mcap_chart, mvrv_chart, daa_chart, exch_chart, dev_chart] if c]
    if secondary_charts:
        charts_html += f"""
        <div class="profile-section">
            <h3 class="section-heading">Key Metrics Charts</h3>
            {chart_panel(secondary_charts, columns=2)}
        </div>"""

    # ============================================================
    # ALL METRICS TABLE
    # ============================================================
    all_rows = []
    for mkey in sorted(metrics.keys()):
        m = metrics[mkey]
        if not m.get("latest"):
            continue
        all_rows.append(f"""<tr>
            <td class="col-name">{metric_label(mkey)}</td>
            <td class="col-num num-bold">{fmt_metric_val(mkey, m.get('latest'))}</td>
            <td class="col-num">{fmt_metric_val(mkey, m.get('avg_30d'))}</td>
            <td class="col-num hide-mobile">{fmt_metric_val(mkey, m.get('min_365d'))}</td>
            <td class="col-num hide-mobile">{fmt_metric_val(mkey, m.get('max_365d'))}</td>
            <td class="col-num hide-mobile">{m.get('count', 0)}</td>
        </tr>""")

    all_metrics_html = ""
    if all_rows:
        all_metrics_html = f"""
        <div class="profile-section">
            <h3 class="section-heading">All Metrics ({len(all_rows)})</h3>
            <div class="table-wrap">
                <table class="data-table compact">
                    <thead><tr>
                        <th class="col-name">Metric</th>
                        <th class="col-num">Latest</th>
                        <th class="col-num">30d Avg</th>
                        <th class="col-num hide-mobile">1Y Low</th>
                        <th class="col-num hide-mobile">1Y High</th>
                        <th class="col-num hide-mobile">Points</th>
                    </tr></thead>
                    <tbody>{''.join(all_rows)}</tbody>
                </table>
            </div>
        </div>"""

    # ============================================================
    # ASSEMBLE PAGE
    # ============================================================
    content = f"""
    <a href="/" class="back-link">&larr; Back to Market</a>

    <div class="profile-hero">
        <div>
            <h2 class="profile-name">{html_mod.escape(name)}</h2>
            <span class="profile-ticker">{html_mod.escape(ticker)}</span>
            {f'<span class="profile-infra">({html_mod.escape(infra)})</span>' if infra else ''}
        </div>
        <div class="profile-price-block">
            <span class="profile-price">{fmt_usd(price)}</span>
            <div class="profile-changes">{changes_html}</div>
        </div>
    </div>

    <div class="metrics-grid">
        {cards_html}
    </div>

    {charts_html}
    {valuation_html}
    {onchain_html}
    {social_html}
    {dev_html}
    {all_metrics_html}
    """
    return page_shell(f"{name} ({ticker})", content)


def _build_metric_rows(metrics: dict, metric_list: list) -> list:
    """Build table rows for a list of (key, label) metric pairs."""
    rows = []
    for mkey, label in metric_list:
        m = metrics.get(mkey, {})
        val = m.get("latest")
        if val is None:
            continue
        avg = m.get("avg_30d")
        min_v = m.get("min_365d")
        max_v = m.get("max_365d")
        count = m.get("count", 0)

        vs_avg = ""
        vs_avg_cls = "num-neutral"
        if avg is not None and avg != 0:
            pct_diff = ((val - avg) / abs(avg)) * 100
            vs_avg = fmt_pct(pct_diff)
            vs_avg_cls = pct_class(pct_diff)

        rows.append(f"""<tr>
            <td class="col-name">{label}</td>
            <td class="col-num num-bold">{fmt_metric_val(mkey, val)}</td>
            <td class="col-num">{fmt_metric_val(mkey, avg)}</td>
            <td class="col-num {vs_avg_cls} hide-mobile">{vs_avg}</td>
            <td class="col-num hide-mobile">{fmt_metric_val(mkey, min_v)}</td>
            <td class="col-num hide-mobile">{fmt_metric_val(mkey, max_v)}</td>
            <td class="col-num hide-mobile">{count}</td>
        </tr>""")
    return rows


# ============================================================
# GAINERS / LOSERS HELPER
# ============================================================

def _render_gainers_losers(gainers: list, losers: list) -> str:
    """Render the gainers/losers section for the market page."""
    if not gainers and not losers:
        return ""

    def _mover_card(token, idx):
        slug = token.get("slug", "")
        name = html_mod.escape(token.get("name", slug)[:20])
        ticker = html_mod.escape(token.get("ticker", ""))
        price = fmt_usd(token.get("price_usd"))
        pct = token.get("price_usd_change", 0)
        cls = pct_class(pct)
        return (
            f'<a href="/token/{slug}" class="mover-card">'
            f'<span class="mover-rank">{idx+1}</span>'
            f'<span class="mover-name"><strong>{name}</strong> <span class="ticker">{ticker}</span></span>'
            f'<span class="mover-price">{price}</span>'
            f'<span class="mover-change {cls}">{fmt_pct(pct)}</span>'
            f'</a>'
        )

    gainer_cards = "".join(_mover_card(t, i) for i, t in enumerate(gainers[:5]))
    loser_cards = "".join(_mover_card(t, i) for i, t in enumerate(losers[:5]))

    return f"""
    <div class="movers-section">
        <div class="movers-col">
            <h4 class="movers-title movers-up">Top Gainers (24h)</h4>
            <div class="movers-list">{gainer_cards}</div>
        </div>
        <div class="movers-col">
            <h4 class="movers-title movers-down">Top Losers (24h)</h4>
            <div class="movers-list">{loser_cards}</div>
        </div>
    </div>"""


# ============================================================
# COMPARISON PAGE
# ============================================================

def render_compare_page(tokens: list) -> str:
    """Render side-by-side token comparison with charts."""
    if not tokens:
        return page_shell("Compare", '<p>No tokens selected. Use ?tokens=bitcoin,ethereum</p>', active_nav="")

    names = [t.get("name", t.get("slug")) for t in tokens]
    title = " vs ".join(names)

    # Comparison metric rows
    compare_metrics = [
        ("price_usd", "Price"),
        ("marketcap_usd", "Market Cap"),
        ("volume_usd", "Volume (24h)"),
        ("mvrv_usd", "MVRV Ratio"),
        ("nvt", "NVT Ratio"),
        ("daily_active_addresses", "Active Addresses"),
        ("transaction_volume", "Tx Volume"),
        ("dev_activity", "Dev Activity"),
        ("exchange_balance", "Exchange Balance"),
        ("network_growth", "Network Growth"),
        ("circulation", "Circulation"),
        ("velocity", "Token Velocity"),
    ]

    comp_table = comparison_table(tokens, compare_metrics)

    # Overlay charts — price, volume, active addresses
    overlay_charts = []

    # Price overlay
    price_series = []
    for i, t in enumerate(tokens):
        data = t.get("metrics", {}).get("price_usd", {}).get("data", [])
        if data:
            price_series.append({
                "label": t.get("name", t.get("slug")),
                "data": data,
            })
    if len(price_series) >= 2:
        overlay_charts.append(line_chart_svg(
            price_series, title="Price Comparison", metric_key="price_usd",
            show_area=False, height=300,
        ))

    # MVRV overlay
    mvrv_series = []
    for i, t in enumerate(tokens):
        data = t.get("metrics", {}).get("mvrv_usd", {}).get("data", [])
        if data:
            mvrv_series.append({
                "label": t.get("name", t.get("slug")),
                "data": data,
            })
    if len(mvrv_series) >= 2:
        overlay_charts.append(line_chart_svg(
            mvrv_series, title="MVRV Ratio Comparison", metric_key="mvrv_usd",
            show_area=False, height=280,
        ))

    # Active addresses overlay
    daa_series = []
    for i, t in enumerate(tokens):
        data = t.get("metrics", {}).get("daily_active_addresses", {}).get("data", [])
        if data:
            daa_series.append({
                "label": t.get("name", t.get("slug")),
                "data": data,
            })
    if len(daa_series) >= 2:
        overlay_charts.append(line_chart_svg(
            daa_series, title="Active Addresses Comparison",
            metric_key="daily_active_addresses",
            show_area=False, height=280,
        ))

    # Volume overlay
    vol_series = []
    for i, t in enumerate(tokens):
        data = t.get("metrics", {}).get("volume_usd", {}).get("data", [])
        if data:
            vol_series.append({
                "label": t.get("name", t.get("slug")),
                "data": data,
            })
    if len(vol_series) >= 2:
        overlay_charts.append(line_chart_svg(
            vol_series, title="Volume Comparison", metric_key="volume_usd",
            show_area=False, height=280,
        ))

    charts_html = ""
    if overlay_charts:
        charts_section = "".join(f'<div class="chart-container">{c}</div>' for c in overlay_charts)
        charts_html = f'<div class="profile-section"><h3 class="section-heading">Overlay Charts</h3>{charts_section}</div>'

    # Slug links for quick compare
    slug_str = ",".join(t.get("slug", "") for t in tokens)
    quick_links = """
    <div class="compare-quick">
        <span class="compare-quick-label">Quick compare:</span>
        <a href="/compare?tokens=bitcoin,ethereum" class="compare-link">BTC vs ETH</a>
        <a href="/compare?tokens=bitcoin,ethereum,solana" class="compare-link">BTC vs ETH vs SOL</a>
        <a href="/compare?tokens=cardano,polkadot,solana" class="compare-link">ADA vs DOT vs SOL</a>
        <a href="/compare?tokens=uniswap,aave,maker" class="compare-link">UNI vs AAVE vs MKR</a>
    </div>"""

    content = f"""
    <a href="/" class="back-link">&larr; Back to Market</a>

    <div class="view-header">
        <h2 class="view-title">{html_mod.escape(title)}</h2>
        <p class="view-subtitle">Side-by-side comparison of {len(tokens)} tokens</p>
    </div>

    {quick_links}

    <div class="profile-section">
        <h3 class="section-heading">Metrics Comparison</h3>
        {comp_table}
    </div>

    {charts_html}
    """
    return page_shell("Compare", content)


# ============================================================
# SCREENER PAGE
# ============================================================

TIER_LABELS = {
    "all": "All Market Caps",
    "mega": "Mega Cap ($100B+)",
    "large": "Large Cap ($10B–$100B)",
    "mid": "Mid Cap ($1B–$10B)",
    "small": "Small Cap ($100M–$1B)",
    "micro": "Micro Cap (<$100M)",
}


def render_screener_page(
    tokens: list, tier: str = "all",
    min_change: float = -999, max_change: float = 999,
    sort_by: str = "marketcap_usd", order: str = "desc",
) -> str:
    """Render the screener page with filterable token list."""

    tier_label = TIER_LABELS.get(tier, tier)

    # Filter buttons
    def tier_cls(t):
        return "filter-btn active" if t == tier else "filter-btn"

    tier_buttons = "".join(
        f'<a href="/screener?tier={t}&sort={sort_by}&order={order}" class="{tier_cls(t)}">{l}</a>'
        for t, l in [("all", "All"), ("mega", "Mega"), ("large", "Large"),
                     ("mid", "Mid"), ("small", "Small"), ("micro", "Micro")]
    )

    # Change filter links
    change_links = ""
    if min_change != -999 or max_change != 999:
        change_links = f'<a href="/screener?tier={tier}&sort={sort_by}&order={order}" class="filter-btn">Clear change filter</a>'

    change_presets = (
        f'<a href="/screener?tier={tier}&min_change=5&sort=price_usd_change&order=desc" class="filter-btn">Gainers &gt;5%</a>'
        f'<a href="/screener?tier={tier}&max_change=-5&sort=price_usd_change&order=asc" class="filter-btn">Losers &lt;-5%</a>'
        f'<a href="/screener?tier={tier}&min_change=-2&max_change=2&sort={sort_by}&order={order}" class="filter-btn">Stable (&plusmn;2%)</a>'
    )

    # Sort toggle
    def sort_link(col, label):
        new_order = "asc" if sort_by == col and order == "desc" else "desc"
        arrow = " &darr;" if sort_by == col and order == "desc" else (" &uarr;" if sort_by == col else "")
        return f'<a href="/screener?tier={tier}&min_change={min_change}&max_change={max_change}&sort={col}&order={new_order}" class="sort-link">{label}{arrow}</a>'

    # Table rows
    rows = []
    for i, t in enumerate(tokens[:200]):  # Cap at 200 for performance
        slug = t.get("slug", "")
        pct = t.get("price_usd_change", 0)
        mvrv = t.get("mvrv_usd")
        spark_data = t.get("sparkline_7d", [])
        spark_html = sparkline_svg(spark_data, width=70, height=20) if spark_data else ""

        rows.append(f"""<tr>
            <td class="col-rank">{i+1}</td>
            <td class="col-name"><a href="/token/{slug}" class="token-link"><strong>{html_mod.escape(t.get('name', slug)[:30])}</strong> <span class="ticker">{html_mod.escape(t.get('ticker', ''))}</span></a></td>
            <td class="col-num num-bold">{fmt_usd(t.get('price_usd'))}</td>
            <td class="col-num {pct_class(pct)}">{fmt_pct(pct)}</td>
            <td class="col-spark hide-mobile">{spark_html}</td>
            <td class="col-num">{fmt_usd(t.get('marketcap_usd'))}</td>
            <td class="col-num hide-mobile">{fmt_usd(t.get('volume_usd'))}</td>
            <td class="col-num hide-mobile">{f'{mvrv:.2f}' if mvrv is not None else '&mdash;'}</td>
        </tr>""")

    table_body = "\n".join(rows) if rows else '<tr><td colspan="8" class="empty-cell">No tokens match these filters.</td></tr>'

    # Tier distribution summary
    tier_summary = f"{len(tokens)} tokens"
    if tier != "all":
        tier_summary += f" in {tier_label}"

    content = f"""
    <div class="view-header">
        <h2 class="view-title">Token Screener</h2>
        <p class="view-subtitle">{tier_summary}</p>
    </div>

    <div class="filter-bar">
        <div class="filter-group">
            <span class="filter-label">Market Cap:</span>
            {tier_buttons}
        </div>
        <div class="filter-group">
            <span class="filter-label">24h Change:</span>
            {change_presets}
            {change_links}
        </div>
    </div>

    <div class="table-wrap">
        <table class="data-table">
            <thead>
                <tr>
                    <th class="col-rank">#</th>
                    <th class="col-name">{sort_link('name', 'Name')}</th>
                    <th class="col-num">{sort_link('price_usd', 'Price')}</th>
                    <th class="col-num">{sort_link('price_usd_change', '24h')}</th>
                    <th class="col-spark hide-mobile">7d</th>
                    <th class="col-num">{sort_link('marketcap_usd', 'Market Cap')}</th>
                    <th class="col-num hide-mobile">{sort_link('volume_usd', 'Volume')}</th>
                    <th class="col-num hide-mobile">MVRV</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>
    </div>
    """
    return page_shell("Screener", content, active_nav="screener")


# ============================================================
# SYNC STATUS PAGE
# ============================================================

PHASE_DESCRIPTIONS = {
    "idle": ("Idle", "System is starting up."),
    "skipped": ("Skipped", "SANTIMENT_API_KEY not configured."),
    "phase1_discovery": ("Phase 1", "Discovering all projects from Santiment..."),
    "phase1_pulling": ("Phase 1", "Loading core data for top 10 tokens (quick startup)."),
    "phase1_complete": ("Phase 1 Done", "Initial data loaded. Starting universe pull."),
    "phase1_error": ("Phase 1 Error", "Discovery/initial pull failed. Will retry."),
    "phase2_universe": ("Phase 2", "Pulling core metrics (price, volume, market cap) for ALL tokens with 7 years of history."),
    "phase2_complete": ("Phase 2 Done", "Universe core data loaded. Starting deep pull."),
    "phase2_error": ("Phase 2 Error", "Universe pull encountered an error. Continuing with available data."),
    "phase3_deep": ("Phase 3", "Pulling deep analytics (MVRV, NVT, on-chain, social, dev) for top 200 tokens."),
    "partial": ("Partial", "Some data loaded. Deep pull may have encountered errors."),
    "ready": ("Complete", "All data synced. Refreshes every 4 hours."),
    "refreshing": ("Refreshing", "Updating latest data points..."),
}


def render_sync_page(pull_status: dict, cache_stats: dict, client_stats: dict) -> str:
    """Render the full sync status page with detailed progress."""
    status_key = pull_status.get("status", "unknown")
    phase_title, phase_desc = PHASE_DESCRIPTIONS.get(status_key, (status_key, ""))
    universe_size = pull_status.get("universe_size", 0)
    last_pull = pull_status.get("last_pull", "")
    error = pull_status.get("error", "")

    # Cache stats
    cs = cache_stats or {}
    ts_rows = cs.get("timeseries_rows", 0)
    ohlcv_rows = cs.get("ohlcv_rows", 0)
    total_pulls = cs.get("total_pulls", 0)
    success_pulls = cs.get("successful_pulls", 0)
    failed_pulls = cs.get("failed_pulls", 0)
    projects_cached = cs.get("projects_cached", 0)
    db_size_mb = cs.get("db_size_mb", 0)
    total_data_pts = cs.get("total_data_points_pulled", 0)
    metrics_cataloged = cs.get("metrics_cataloged", 0)

    # Client stats
    cl = client_stats or {}
    total_requests = cl.get("total_requests", 0)
    cache_hits = cl.get("cache_hits", 0)
    errors = cl.get("errors", 0)
    last_error = cl.get("last_error", "")

    # Progress calculation
    is_done = status_key in ("ready", "partial")
    is_syncing = status_key not in ("ready", "idle", "skipped", "partial")

    # Phase progress indicator
    phases = [
        ("Discovery", status_key in ("phase1_discovery",)),
        ("Phase 1: Quick Load", status_key in ("phase1_pulling",)),
        ("Phase 2: Universe", status_key in ("phase2_universe",)),
        ("Phase 3: Deep Pull", status_key in ("phase3_deep",)),
        ("Ready", status_key in ("ready",)),
    ]

    phase_steps = []
    past_active = True
    for label, is_active in phases:
        if is_active:
            cls = "sync-step active"
            past_active = False
        elif past_active and not is_done:
            cls = "sync-step done"
        elif is_done:
            cls = "sync-step done"
        else:
            cls = "sync-step pending"
        phase_steps.append(f'<div class="{cls}"><span class="sync-step-dot"></span><span class="sync-step-label">{label}</span></div>')

    # Determine which phases are complete vs pending
    phase_order = ["phase1_discovery", "phase1_pulling", "phase1_complete",
                   "phase2_universe", "phase2_complete",
                   "phase3_deep", "ready", "partial"]
    current_idx = phase_order.index(status_key) if status_key in phase_order else 0

    done_phases = []
    if current_idx >= 2:
        done_phases.append(("Phase 1: Quick Load", "Top 10 tokens, Tier 1 metrics, 1 year", "check"))
    if current_idx >= 4:
        done_phases.append(("Phase 2: Universe Pull", f"{universe_size} tokens, core metrics, 7 years", "check"))
    if current_idx >= 6:
        done_phases.append(("Phase 3: Deep Pull", "Top 200 tokens, Tier 1+2 metrics, 7 years", "check"))

    done_html = ""
    for label, desc, icon in done_phases:
        done_html += f"""
        <div class="sync-phase-card done">
            <div class="sync-phase-icon">&#10003;</div>
            <div><strong>{label}</strong><br><span class="sync-phase-desc">{desc}</span></div>
        </div>"""

    # Error section
    error_html = ""
    if error:
        error_html = f"""
    <div class="sync-error">
        <strong>Error:</strong> {html_mod.escape(str(error)[:500])}
    </div>"""

    if last_error:
        error_html += f"""
    <div class="sync-warning">
        <strong>Last API Error:</strong> {html_mod.escape(str(last_error)[:300])}
    </div>"""

    # Last pull time
    last_pull_str = ""
    if last_pull:
        try:
            d = datetime.fromisoformat(last_pull.replace("Z", "+00:00"))
            last_pull_str = d.strftime("%b %d, %Y %H:%M UTC")
        except Exception:
            last_pull_str = last_pull

    content = f"""
    <div class="view-header">
        <h2 class="view-title">Data Sync Status</h2>
        <p class="view-subtitle">{'Syncing data from Santiment API...' if is_syncing else 'All data synced' if is_done else phase_desc}</p>
    </div>

    <div class="sync-phase-banner">
        <div class="sync-current-phase">
            <span class="sync-phase-badge {'sync-active' if is_syncing else 'sync-done' if is_done else ''}">{phase_title}</span>
            <span class="sync-phase-text">{phase_desc}</span>
        </div>
    </div>

    <div class="sync-pipeline">
        {''.join(phase_steps)}
    </div>

    {done_html}

    {error_html}

    <div class="sync-grid">
        <div class="sync-card">
            <div class="sync-card-label">Projects Discovered</div>
            <div class="sync-card-value">{fmt_num(universe_size)}</div>
        </div>
        <div class="sync-card">
            <div class="sync-card-label">Projects Cached</div>
            <div class="sync-card-value">{fmt_num(projects_cached)}</div>
        </div>
        <div class="sync-card">
            <div class="sync-card-label">Timeseries Rows</div>
            <div class="sync-card-value">{fmt_num(ts_rows)}</div>
        </div>
        <div class="sync-card">
            <div class="sync-card-label">OHLCV Rows</div>
            <div class="sync-card-value">{fmt_num(ohlcv_rows)}</div>
        </div>
        <div class="sync-card">
            <div class="sync-card-label">Data Points Pulled</div>
            <div class="sync-card-value">{fmt_num(total_data_pts)}</div>
        </div>
        <div class="sync-card">
            <div class="sync-card-label">Database Size</div>
            <div class="sync-card-value">{db_size_mb:.1f} MB</div>
        </div>
    </div>

    <div class="profile-section">
        <h3 class="section-heading">API Activity</h3>
        <div class="table-wrap">
            <table class="data-table compact">
                <tbody>
                    <tr><td class="col-name">Total API Requests</td><td class="col-num num-bold">{fmt_num(total_requests)}</td></tr>
                    <tr><td class="col-name">Successful Pulls</td><td class="col-num num-positive">{fmt_num(success_pulls)}</td></tr>
                    <tr><td class="col-name">Failed Pulls</td><td class="col-num {'num-negative' if failed_pulls else 'num-neutral'}">{fmt_num(failed_pulls)}</td></tr>
                    <tr><td class="col-name">Cache Hits</td><td class="col-num">{fmt_num(cache_hits)}</td></tr>
                    <tr><td class="col-name">API Errors</td><td class="col-num {'num-negative' if errors else 'num-neutral'}">{fmt_num(errors)}</td></tr>
                    <tr><td class="col-name">Metrics Cataloged</td><td class="col-num">{fmt_num(metrics_cataloged)}</td></tr>
                    <tr><td class="col-name">Last Updated</td><td class="col-num">{last_pull_str or '&mdash;'}</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <p class="sync-hint">This page shows a snapshot. Refresh to see the latest progress.</p>
    """
    return page_shell("Sync Status", content, active_nav="sync")
