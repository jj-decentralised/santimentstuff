"""
Pure SVG chart generation — no JavaScript required.

Premium chart engine with:
- Smooth bezier curves (cubic spline interpolation)
- Gradient area fills with defs
- Min/max/current value markers
- Refined typography and spacing
- Heatmap grids, dominance bars, sentiment gauges
- Outlier clamping, smart y-axis, clean labels
"""

import html as html_mod
import math
from typing import Optional


# ============================================================
# COLORS — Refined palette
# ============================================================

COLORS = [
    "#111111",   # near-black (primary)
    "#3B82F6",   # blue
    "#EF4444",   # red
    "#10B981",   # emerald
    "#F59E0B",   # amber
    "#8B5CF6",   # violet
    "#06B6D4",   # cyan
    "#EC4899",   # pink
    "#F97316",   # orange
    "#14B8A6",   # teal
]

GRID_COLOR = "#F3F4F6"
LABEL_COLOR = "#9CA3AF"
AXIS_COLOR = "#E5E7EB"
BG_COLOR = "#FAFBFC"

# Heatmap color scale (red -> gray -> green)
HEATMAP_COLORS = {
    "extreme_neg": "#DC2626",
    "neg": "#F87171",
    "slight_neg": "#FCA5A5",
    "neutral": "#E5E7EB",
    "slight_pos": "#86EFAC",
    "pos": "#34D399",
    "extreme_pos": "#059669",
}


# ============================================================
# FORMATTING — Clean, human-readable labels
# ============================================================

def _fmt_compact(v: float) -> str:
    """Compact number for tooltips."""
    if v is None:
        return "–"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e12:
        return f"{sign}{a/1e12:.1f}T"
    if a >= 1e9:
        return f"{sign}{a/1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}{a/1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}{a/1e3:,.0f}"
    if a >= 1:
        return f"{sign}{a:,.2f}"
    if a >= 0.01:
        return f"{sign}{a:.4f}"
    return f"{sign}{a:.6f}"


def _fmt_val(v: float, key: str = "") -> str:
    """Format a value for axis labels — clean, human-readable numbers."""
    if v is None:
        return ""
    a = abs(v)
    sign = "-" if v < 0 else ""
    is_dollar = "usd" in key and "mvrv" not in key and "nvt" not in key and "percent" not in key

    if is_dollar:
        if a >= 1e12:
            return f"{sign}${a/1e12:.1f}T"
        if a >= 1e9:
            return f"{sign}${a/1e9:.1f}B"
        if a >= 1e6:
            return f"{sign}${a/1e6:.1f}M"
        if a >= 1e3:
            return f"{sign}${a/1e3:,.0f}"
        if a >= 1:
            return f"{sign}${a:,.2f}"
        return f"{sign}${a:.4f}"
    # Non-dollar
    if a >= 1e9:
        return f"{sign}{a/1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}{a/1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}{a/1e3:.0f}K"
    if a >= 100:
        return f"{sign}{a:.0f}"
    if a >= 10:
        return f"{sign}{a:.1f}"
    if a >= 1:
        return f"{sign}{a:.2f}"
    if a >= 0.01:
        return f"{sign}{a:.3f}"
    return f"{sign}{a:.4f}"


def _nice_ticks(lo: float, hi: float, n_ticks: int = 5) -> list[float]:
    """Generate 'nice' round tick values for an axis range."""
    if hi <= lo:
        return [lo]
    raw_step = (hi - lo) / max(n_ticks - 1, 1)
    # Find order of magnitude
    mag = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    # Snap to nice step: 1, 2, 2.5, 5, 10 multiples
    nice_steps = [1, 2, 2.5, 5, 10]
    norm = raw_step / mag
    step = mag
    for ns in nice_steps:
        if ns >= norm:
            step = ns * mag
            break

    # Generate ticks
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        if v >= lo - step * 0.01:
            ticks.append(round(v, 10))
        v += step
    return ticks if ticks else [lo, hi]


def _fmt_date(dt_str: str) -> str:
    """Format ISO date for chart labels."""
    try:
        parts = dt_str[:10].split("-")
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{months[int(parts[1])]} {parts[2].lstrip('0')}"
    except Exception:
        return dt_str[:10]


def _fmt_date_year(dt_str: str) -> str:
    """Format date with year for longer charts."""
    try:
        parts = dt_str[:10].split("-")
        months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{months[int(parts[1])]} '{parts[0][2:]}"
    except Exception:
        return dt_str[:7]


def _clamp_outliers(values: list[float], pct: float = 2.0) -> tuple:
    """Return (lo, hi) with extreme outliers clamped at percentile boundaries."""
    if not values:
        return (0, 1)
    sv = sorted(values)
    n = len(sv)
    lo_idx = max(0, int(n * pct / 100))
    hi_idx = min(n - 1, int(n * (100 - pct) / 100))
    lo = sv[lo_idx]
    hi = sv[hi_idx]
    # Ensure some range
    if hi <= lo:
        lo = sv[0]
        hi = sv[-1]
    if hi <= lo:
        lo -= 1
        hi += 1
    return (lo, hi)


def _smooth_path(points: list[tuple[float, float]], tension: float = 0.3) -> str:
    """
    Generate a smooth SVG path using cubic bezier curves (Catmull-Rom to Bezier).
    Returns SVG path d attribute string.
    """
    if len(points) < 2:
        return ""
    if len(points) == 2:
        return f"M{points[0][0]:.1f},{points[0][1]:.1f} L{points[1][0]:.1f},{points[1][1]:.1f}"

    d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"

    for i in range(1, len(points)):
        p0 = points[max(0, i - 2)]
        p1 = points[i - 1]
        p2 = points[i]
        p3 = points[min(len(points) - 1, i + 1)]

        # Control points
        cp1x = p1[0] + (p2[0] - p0[0]) * tension
        cp1y = p1[1] + (p2[1] - p0[1]) * tension
        cp2x = p2[0] - (p3[0] - p1[0]) * tension
        cp2y = p2[1] - (p3[1] - p1[1]) * tension

        d += f" C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {p2[0]:.1f},{p2[1]:.1f}"

    return d


def _gradient_def(gid: str, color: str, opacity_top: float = 0.25, opacity_bottom: float = 0.0) -> str:
    """Generate a vertical linear gradient definition."""
    return (
        f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="{opacity_top}"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="{opacity_bottom}"/>'
        f'</linearGradient>'
    )


# ============================================================
# SPARKLINE — Tiny inline chart for tables
# ============================================================

def sparkline_svg(
    data: list[dict],
    width: int = 80,
    height: int = 24,
    color: str = "#000000",
    show_change_color: bool = True,
) -> str:
    """Tiny inline sparkline SVG with gradient fill."""
    values = [d.get("value") for d in data if d.get("value") is not None]
    if len(values) < 2:
        return ""

    min_v = min(values)
    max_v = max(values)
    v_range = max_v - min_v if max_v != min_v else 1
    n = len(values)

    if show_change_color:
        color = "#10B981" if values[-1] >= values[0] else "#EF4444"

    gid = f"sg{abs(hash(str(values[:3]))) % 99999}"

    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / v_range) * (height - 4) - 2
        points.append((x, y))

    line_d = _smooth_path(points, tension=0.25)
    area_d = line_d + f" L{points[-1][0]:.1f},{height} L{points[0][0]:.1f},{height} Z"

    # Tooltip: show latest value, change, and range
    first_v, last_v = values[0], values[-1]
    if first_v and first_v != 0:
        chg = (last_v - first_v) / first_v * 100
        chg_str = f" ({chg:+.1f}%)"
    else:
        chg_str = ""
    tooltip = f"{_fmt_compact(last_v)}{chg_str} | Range: {_fmt_compact(min_v)}–{_fmt_compact(max_v)}"

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<title>{tooltip}</title>'
        f'<defs>{_gradient_def(gid, color, 0.3, 0.0)}</defs>'
        f'<path d="{area_d}" fill="url(#{gid})"/>'
        f'<path d="{line_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="1.5" fill="{color}"/>'
        f'</svg>'
    )


# ============================================================
# LINE CHART — Full-size with smooth curves, gradients, markers
# ============================================================

def line_chart_svg(
    series: list[dict],
    width: int = 700,
    height: int = 300,
    title: str = "",
    metric_key: str = "",
    show_area: bool = True,
    show_dots: bool = False,
    show_grid: bool = True,
    show_min_max: bool = True,
    y_label_count: int = 5,
    x_label_count: int = 5,
) -> str:
    """
    Generate a premium line chart SVG with smooth curves and gradient fills.

    Key improvements:
    - Outlier clamping (2nd/98th percentile) for stable Y-axis
    - Smart zero baseline: if all values are positive, Y starts at 0 or near-min
    - Nice round tick numbers on Y-axis
    - Fewer, cleaner date labels on X-axis
    - Gradient fill clipped at chart bottom (not below zero)
    """
    if not series or not any(s.get("data") for s in series):
        return '<div class="chart-empty">No chart data available</div>'

    # Chart dimensions
    pad_left = 70
    pad_right = 30
    pad_top = 35 if title else 16
    pad_bottom = 40
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    # Collect all values
    all_values = []
    all_dates = []
    for s in series:
        for d in (s.get("data") or []):
            v = d.get("value")
            if v is not None:
                all_values.append(v)
                all_dates.append(d.get("datetime", ""))

    if not all_values:
        return '<div class="chart-empty">No chart data available</div>'

    # ── Smart Y-axis range with outlier clamping ──
    clamped_lo, clamped_hi = _clamp_outliers(all_values, pct=2.0)

    # If all values are positive, don't show negative Y
    all_positive = min(all_values) >= 0
    if all_positive:
        clamped_lo = max(0, clamped_lo * 0.9)  # start near 0 or 90% of min
        # If min is close to 0, just start at 0
        if clamped_lo < clamped_hi * 0.15:
            clamped_lo = 0

    # Compute nice ticks
    ticks = _nice_ticks(clamped_lo, clamped_hi, y_label_count)
    min_v = ticks[0]
    max_v = ticks[-1]
    v_range = max_v - min_v
    if v_range == 0:
        v_range = 1
        max_v = min_v + 1
        ticks = [min_v, max_v]

    def scale_y(v):
        clamped = max(min_v, min(max_v, v))
        return pad_top + chart_h - ((clamped - min_v) / v_range) * chart_h

    elements = []
    defs = []

    elements.append(
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    )

    # Chart area background
    elements.append(
        f'<rect x="{pad_left}" y="{pad_top}" width="{chart_w}" height="{chart_h}" '
        f'fill="{BG_COLOR}" rx="4"/>'
    )

    # Title
    if title:
        elements.append(
            f'<text x="{pad_left}" y="20" font-size="13" font-weight="700" '
            f'fill="#111827" font-family="Inter,system-ui,sans-serif">{html_mod.escape(title)}</text>'
        )

    # ── Y-axis: nice round tick lines ──
    if show_grid:
        for tick in ticks:
            y = scale_y(tick)
            label = _fmt_val(tick, metric_key)
            elements.append(
                f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + chart_w}" y2="{y:.1f}" '
                f'stroke="{GRID_COLOR}" stroke-width="1"/>'
            )
            elements.append(
                f'<text x="{pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
                f'font-size="10" fill="{LABEL_COLOR}" font-family="Inter,system-ui,sans-serif">{label}</text>'
            )

    # ── Draw each series ──
    for si, s in enumerate(series):
        data = s.get("data") or []
        if not data:
            continue

        color = s.get("color") or COLORS[si % len(COLORS)]
        n = len(data)

        # Build points
        points = []
        min_pt = None
        max_pt = None
        local_min = float('inf')
        local_max = float('-inf')

        for i, d in enumerate(data):
            v = d.get("value")
            if v is None:
                continue
            x = pad_left + (i / max(n - 1, 1)) * chart_w
            y = scale_y(v)
            points.append((x, y))

            if v < local_min:
                local_min = v
                min_pt = (x, y, v)
            if v > local_max:
                local_max = v
                max_pt = (x, y, v)

        if not points:
            continue

        # Gradient definition
        gid = f"grad_{si}_{abs(hash(color)) % 99999}"
        defs.append(_gradient_def(gid, color, 0.15, 0.01))

        # Smooth path
        line_d = _smooth_path(points, tension=0.25)

        # Area fill — clipped to chart bottom
        if show_area and len(series) <= 2:
            clip_id = f"clip_{si}"
            defs.append(
                f'<clipPath id="{clip_id}">'
                f'<rect x="{pad_left}" y="{pad_top}" width="{chart_w}" height="{chart_h}"/>'
                f'</clipPath>'
            )
            area_d = (
                line_d +
                f" L{points[-1][0]:.1f},{pad_top + chart_h:.1f}"
                f" L{points[0][0]:.1f},{pad_top + chart_h:.1f} Z"
            )
            elements.append(
                f'<path d="{area_d}" fill="url(#{gid})" clip-path="url(#{clip_id})"/>'
            )

        # Line
        stroke_w = "2" if len(series) == 1 else "1.5"
        elements.append(
            f'<path d="{line_d}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_w}" stroke-linecap="round" stroke-linejoin="round"/>'
        )

        # Min/Max markers (single series, enough data)
        if show_min_max and len(series) == 1 and len(points) > 20 and min_pt and max_pt:
            mx, my, mv = max_pt
            if pad_left + 40 < mx < pad_left + chart_w - 40:
                elements.append(
                    f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="3" '
                    f'fill="white" stroke="{color}" stroke-width="1.5"/>'
                )

            nx, ny, nv = min_pt
            if pad_left + 40 < nx < pad_left + chart_w - 40:
                elements.append(
                    f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="3" '
                    f'fill="white" stroke="#EF4444" stroke-width="1.5"/>'
                )

        # Latest value endpoint
        if points:
            lx, ly = points[-1]
            lv = None
            for d in reversed(data):
                if d.get("value") is not None:
                    lv = d["value"]
                    break
            if lv is not None:
                label_text = _fmt_val(lv, metric_key)
                elements.append(
                    f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" '
                    f'fill="white" stroke="{color}" stroke-width="2"/>'
                )
                # Position label to avoid clipping
                lbl_x = lx - 8
                anchor = "end"
                if lx < pad_left + chart_w * 0.3:
                    lbl_x = lx + 8
                    anchor = "start"
                lbl_y = ly - 8
                if lbl_y < pad_top + 12:
                    lbl_y = ly + 16
                elements.append(
                    f'<text x="{lbl_x:.1f}" y="{lbl_y:.1f}" text-anchor="{anchor}" '
                    f'font-size="10" font-weight="700" fill="{color}" '
                    f'font-family="Inter,system-ui,sans-serif">{label_text}</text>'
                )

    # ── X-axis date labels — smart spacing ──
    primary_data = series[0].get("data") or []
    if primary_data:
        n = len(primary_data)
        use_year = n > 180
        # Aim for ~5 labels max, evenly spaced
        n_labels = min(x_label_count, max(2, n // 60))
        step = max(1, (n - 1) // n_labels)
        indices = list(range(0, n, step))
        # Always include last point
        if indices[-1] != n - 1:
            indices.append(n - 1)

        for idx in indices:
            dt = primary_data[idx].get("datetime", "")
            x = pad_left + (idx / max(n - 1, 1)) * chart_w
            label = _fmt_date_year(dt) if use_year else _fmt_date(dt)
            elements.append(
                f'<text x="{x:.1f}" y="{pad_top + chart_h + 16}" text-anchor="middle" '
                f'font-size="9" fill="{LABEL_COLOR}" font-family="Inter,system-ui,sans-serif">{label}</text>'
            )

    # X-axis line
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{pad_left + chart_w}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="1"/>'
    )

    # Legend (multi-series)
    if len(series) > 1:
        leg_y = height - 6
        leg_x = pad_left
        for si, s in enumerate(series):
            color = s.get("color") or COLORS[si % len(COLORS)]
            label = s.get("label", f"Series {si+1}")
            elements.append(
                f'<circle cx="{leg_x + 5}" cy="{leg_y - 3}" r="4" fill="{color}"/>'
            )
            elements.append(
                f'<text x="{leg_x + 14}" y="{leg_y}" font-size="10" font-weight="600" fill="#6B7280" '
                f'font-family="Inter,system-ui,sans-serif">{html_mod.escape(label)}</text>'
            )
            leg_x += len(label) * 6.5 + 30

    # Watermark
    elements.append(
        f'<text x="{pad_left + chart_w - 4}" y="{pad_top + chart_h - 6}" text-anchor="end" '
        f'font-size="8" font-weight="600" fill="#D1D5DB" '
        f'font-family="Inter,system-ui,sans-serif" opacity="0.5">Onchain Pulse</text>'
    )

    # Insert defs
    if defs:
        elements.insert(1, f'<defs>{"".join(defs)}</defs>')

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# MULTI-CHART PANEL — Side-by-side or stacked charts
# ============================================================

def chart_panel(
    charts: list[str],
    columns: int = 2,
) -> str:
    """Wrap multiple chart SVGs in a responsive grid."""
    cols_class = f"chart-grid-{columns}"
    items = "".join(f'<div class="chart-cell">{c}</div>' for c in charts)
    return f'<div class="chart-grid {cols_class}">{items}</div>'


# ============================================================
# COMPARISON TABLE — Side-by-side metric comparison
# ============================================================

def comparison_table(
    tokens: list[dict],
    metric_keys: list[tuple],
) -> str:
    """Render a side-by-side metric comparison table."""
    if not tokens:
        return '<p>No tokens selected for comparison.</p>'

    header_cells = '<th class="col-name">Metric</th>'
    for t in tokens:
        name = html_mod.escape(t.get("name", t.get("slug", "")))
        ticker = html_mod.escape(t.get("ticker", ""))
        header_cells += (
            f'<th class="col-num"><a href="/token/{t.get("slug", "")}" class="token-link">'
            f'<strong>{name}</strong> <span class="ticker">{ticker}</span></a></th>'
        )

    rows = []
    for key, label in metric_keys:
        cells = f'<td class="col-name">{html_mod.escape(label)}</td>'
        for t in tokens:
            m = t.get("metrics", {}).get(key, {})
            val = m.get("latest")
            if val is None:
                cells += '<td class="col-num">&mdash;</td>'
            else:
                cells += f'<td class="col-num num-bold">{_fmt_val(val, key)}</td>'
        rows.append(f'<tr>{cells}</tr>')

    return f"""
    <div class="table-wrap">
        <table class="data-table compact">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
    </div>"""


# ============================================================
# MARKET HEATMAP — Grid of colored blocks by performance
# ============================================================

def _heatmap_color(pct_change: float) -> str:
    if pct_change is None:
        return HEATMAP_COLORS["neutral"]
    if pct_change <= -10:
        return HEATMAP_COLORS["extreme_neg"]
    if pct_change <= -5:
        return HEATMAP_COLORS["neg"]
    if pct_change <= -1:
        return HEATMAP_COLORS["slight_neg"]
    if pct_change < 1:
        return HEATMAP_COLORS["neutral"]
    if pct_change < 5:
        return HEATMAP_COLORS["slight_pos"]
    if pct_change < 10:
        return HEATMAP_COLORS["pos"]
    return HEATMAP_COLORS["extreme_pos"]


def _heatmap_text_color(pct_change: float) -> str:
    if pct_change is None:
        return "#6B7280"
    if abs(pct_change) >= 5:
        return "#FFFFFF"
    return "#374151"


def market_heatmap_svg(tokens: list[dict], max_tokens: int = 50) -> str:
    """Treemap-style heatmap of token performance."""
    if not tokens:
        return ""

    sorted_tokens = sorted(tokens, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)[:max_tokens]
    if not sorted_tokens:
        return ""

    total_mcap = sum(t.get("marketcap_usd") or 0 for t in sorted_tokens) or 1

    width = 700
    height = 320
    padding = 2

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    row_count = 5
    tokens_per_row = max(1, len(sorted_tokens) // row_count)
    row_h = height / row_count

    idx = 0
    for row in range(row_count):
        y = row * row_h
        row_end = min(idx + tokens_per_row + (1 if row < len(sorted_tokens) % row_count else 0), len(sorted_tokens))
        row_tokens = sorted_tokens[idx:row_end]
        if not row_tokens:
            break

        row_mcap = sum(t.get("marketcap_usd") or 0 for t in row_tokens) or 1
        x = 0

        for t in row_tokens:
            mcap = t.get("marketcap_usd") or 0
            w = max(30, (mcap / row_mcap) * width)
            pct = t.get("price_usd_change") or 0
            bg = _heatmap_color(pct)
            fg = _heatmap_text_color(pct)
            slug = t.get("slug", "")
            ticker = html_mod.escape(t.get("ticker", "")[:6])
            pct_str = f"{pct:+.1f}%" if pct else "0%"

            elements.append(
                f'<a href="/token/{slug}">'
                f'<rect x="{x + padding:.1f}" y="{y + padding:.1f}" '
                f'width="{w - padding * 2:.1f}" height="{row_h - padding * 2:.1f}" '
                f'rx="4" fill="{bg}"/>'
            )

            if w > 45:
                cx = x + w / 2
                cy = y + row_h / 2
                elements.append(
                    f'<text x="{cx:.1f}" y="{cy - 5:.1f}" text-anchor="middle" '
                    f'font-size="{min(12, max(8, w/8)):.0f}" font-weight="700" fill="{fg}" '
                    f'font-family="Inter,system-ui,sans-serif">{ticker}</text>'
                )
                elements.append(
                    f'<text x="{cx:.1f}" y="{cy + 9:.1f}" text-anchor="middle" '
                    f'font-size="{min(10, max(7, w/10)):.0f}" font-weight="600" fill="{fg}" '
                    f'opacity="0.85" font-family="Inter,system-ui,sans-serif">{pct_str}</text>'
                )
            elements.append('</a>')
            x += w

        idx = row_end

    # Watermark
    elements.append(
        f'<text x="{width - 8}" y="{height - 6}" text-anchor="end" '
        f'font-size="8" font-weight="600" fill="#D1D5DB" '
        f'font-family="Inter,system-ui,sans-serif" opacity="0.5">Onchain Pulse</text>'
    )

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# MARKET DOMINANCE — Horizontal stacked bar
# ============================================================

def dominance_bar_svg(tokens: list[dict], width: int = 700, height: int = 56) -> str:
    """Horizontal stacked bar showing market dominance."""
    if not tokens:
        return ""

    total = sum(t.get("marketcap_usd") or 0 for t in tokens) or 1
    bar_y = 0
    bar_h = 32
    label_y = bar_h + 18

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    x = 0
    top_n = min(8, len(tokens))
    others_mcap = sum(t.get("marketcap_usd") or 0 for t in tokens[top_n:])

    segments = []
    for i, t in enumerate(tokens[:top_n]):
        mcap = t.get("marketcap_usd") or 0
        segments.append({
            "label": t.get("ticker", "?"),
            "value": mcap,
            "pct": (mcap / total) * 100,
            "color": COLORS[i % len(COLORS)],
        })

    if others_mcap > 0:
        segments.append({
            "label": "Others",
            "value": others_mcap,
            "pct": (others_mcap / total) * 100,
            "color": "#D1D5DB",
        })

    for seg in segments:
        w = max(2, (seg["value"] / total) * width)
        elements.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{w:.1f}" height="{bar_h}" '
            f'rx="{"4" if x == 0 else "0"}" fill="{seg["color"]}"/>'
        )
        if w > 40:
            elements.append(
                f'<text x="{x + w/2:.1f}" y="{bar_y + bar_h/2 + 4:.1f}" text-anchor="middle" '
                f'font-size="10" font-weight="700" fill="white" '
                f'font-family="Inter,system-ui,sans-serif">{seg["label"]} {seg["pct"]:.1f}%</text>'
            )
        x += w

    # Legend
    leg_x = 0
    for seg in segments:
        if seg["pct"] < 1:
            continue
        elements.append(
            f'<circle cx="{leg_x + 5}" cy="{label_y}" r="4" fill="{seg["color"]}"/>'
        )
        label = f'{seg["label"]} {seg["pct"]:.1f}%'
        elements.append(
            f'<text x="{leg_x + 13}" y="{label_y + 3.5}" font-size="9" font-weight="600" '
            f'fill="#6B7280" font-family="Inter,system-ui,sans-serif">{label}</text>'
        )
        leg_x += len(label) * 5.5 + 22

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# SENTIMENT GAUGE — Semicircle gauge for market sentiment
# ============================================================

def sentiment_gauge_svg(
    value: float,
    min_val: float = 0,
    max_val: float = 4,
    label: str = "Market Sentiment",
    width: int = 240,
    height: int = 140,
) -> str:
    """Semicircle gauge SVG for aggregate metrics."""
    norm = max(0, min(1, (value - min_val) / (max_val - min_val))) if (max_val - min_val) > 0 else 0.5

    cx = width / 2
    cy = height - 20
    r = min(cx - 20, cy - 10)

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    # Background arc
    elements.append(
        f'<path d="M{cx - r:.1f},{cy:.1f} A{r:.1f},{r:.1f} 0 0 1 {cx + r:.1f},{cy:.1f}" '
        f'fill="none" stroke="#E5E7EB" stroke-width="12" stroke-linecap="round"/>'
    )

    # Color segments
    segments = [
        (0, 0.33, "#10B981"),
        (0.33, 0.66, "#F59E0B"),
        (0.66, 1.0, "#EF4444"),
    ]
    for start_frac, end_frac, color in segments:
        a1 = math.pi * (1 - start_frac)
        a2 = math.pi * (1 - end_frac)
        x1 = cx + r * math.cos(a1)
        y1 = cy - r * math.sin(a1)
        x2 = cx + r * math.cos(a2)
        y2 = cy - r * math.sin(a2)
        elements.append(
            f'<path d="M{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 0 1 {x2:.1f},{y2:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="12" stroke-linecap="butt" opacity="0.2"/>'
        )

    # Needle
    needle_angle = math.pi * (1 - norm)
    nx = cx + (r - 10) * math.cos(needle_angle)
    ny = cy - (r - 10) * math.sin(needle_angle)
    elements.append(
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
        f'stroke="#111827" stroke-width="3" stroke-linecap="round"/>'
    )
    elements.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="#111827"/>')
    elements.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="white"/>')

    # Value
    elements.append(
        f'<text x="{cx:.1f}" y="{cy - r/2 - 2:.1f}" text-anchor="middle" '
        f'font-size="22" font-weight="900" fill="#111827" '
        f'font-family="Inter,system-ui,sans-serif">{value:.2f}</text>'
    )
    elements.append(
        f'<text x="{cx:.1f}" y="{cy + 16:.1f}" text-anchor="middle" '
        f'font-size="10" font-weight="600" fill="#9CA3AF" '
        f'font-family="Inter,system-ui,sans-serif">{html_mod.escape(label)}</text>'
    )

    # Min/Max labels
    elements.append(
        f'<text x="{cx - r - 5:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
        f'font-size="9" fill="#9CA3AF" font-family="Inter,system-ui,sans-serif">Undervalued</text>'
    )
    elements.append(
        f'<text x="{cx + r + 5:.1f}" y="{cy + 4:.1f}" text-anchor="start" '
        f'font-size="9" fill="#9CA3AF" font-family="Inter,system-ui,sans-serif">Overvalued</text>'
    )

    # Watermark
    elements.append(
        f'<text x="{width - 6}" y="{height - 4}" text-anchor="end" '
        f'font-size="7" font-weight="600" fill="#D1D5DB" '
        f'font-family="Inter,system-ui,sans-serif" opacity="0.5">Onchain Pulse</text>'
    )

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# MINI TREND — Small area chart for stat cards
# ============================================================

def mini_trend_svg(
    data: list[dict],
    width: int = 140,
    height: int = 40,
    color: str = "#111111",
) -> str:
    """Small area chart for embedding in stat cards / hero sections."""
    values = [d.get("value") for d in data if d.get("value") is not None]
    if len(values) < 3:
        return ""

    min_v = min(values)
    max_v = max(values)
    v_range = max_v - min_v if max_v != min_v else 1
    n = len(values)

    gid = f"mt{abs(hash(str(values[:3]))) % 99999}"

    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / v_range) * (height - 4) - 2
        points.append((x, y))

    line_d = _smooth_path(points, tension=0.25)
    area_d = line_d + f" L{points[-1][0]:.1f},{height} L{points[0][0]:.1f},{height} Z"

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<defs>{_gradient_def(gid, color, 0.18, 0.0)}</defs>'
        f'<path d="{area_d}" fill="url(#{gid})"/>'
        f'<path d="{line_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


# ============================================================
# SCATTER PLOT — Cross-metric analysis (e.g., MVRV vs NVT)
# ============================================================

THESIS_COLORS = {
    "smart_money": "#10B981",
    "builder_momentum": "#3B82F6",
    "deep_value": "#059669",
    "distribution_warning": "#EF4444",
    "hodler": "#8B5CF6",
    "high_utility": "#06B6D4",
    "speculative": "#F97316",
    "uncategorized": "#9CA3AF",
}


def scatter_plot_svg(
    points: list[dict],
    width: int = 700,
    height: int = 400,
    title: str = "",
    x_key: str = "x",
    y_key: str = "y",
    x_label: str = "",
    y_label: str = "",
    color_key: str = "",
    size_key: str = "",
    log_x: bool = False,
    log_y: bool = False,
) -> str:
    """Render a scatter plot SVG with log scales, color coding, and size scaling."""
    if not points:
        return '<div class="chart-empty">No data for scatter plot</div>'

    valid = [p for p in points if p.get(x_key) is not None and p.get(y_key) is not None]
    if len(valid) < 3:
        return '<div class="chart-empty">Insufficient data for scatter plot</div>'

    def _safe_log(v):
        if v is None or v <= 0:
            return None
        return math.log10(v)

    x_vals = []
    y_vals = []
    for p in valid:
        xv = _safe_log(p[x_key]) if log_x else p[x_key]
        yv = _safe_log(p[y_key]) if log_y else p[y_key]
        if xv is not None and yv is not None:
            x_vals.append(xv)
            y_vals.append(yv)

    if len(x_vals) < 3:
        return '<div class="chart-empty">Insufficient valid data</div>'

    # Chart dimensions
    pad_left = 70
    pad_right = 20
    pad_top = 35 if title else 16
    pad_bottom = 55
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    # Ranges with 5% padding
    x_min, x_max = min(x_vals), max(x_vals)
    y_min, y_max = min(y_vals), max(y_vals)
    x_range = x_max - x_min if x_max != x_min else 1
    y_range = y_max - y_min if y_max != y_min else 1
    x_pad = x_range * 0.05
    y_pad = y_range * 0.05
    x_min -= x_pad
    x_max += x_pad
    y_min -= y_pad
    y_max += y_pad
    x_range = x_max - x_min
    y_range = y_max - y_min

    def scale_x(v):
        return pad_left + ((v - x_min) / x_range) * chart_w

    def scale_y(v):
        return pad_top + chart_h - ((v - y_min) / y_range) * chart_h

    # Size scaling
    size_vals = []
    max_size = 1
    if size_key:
        size_vals = [p.get(size_key) or 0 for p in valid]
        max_size = max(size_vals) if size_vals else 1
    min_r, max_r = 3, 12

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg scatter-chart">'
    ]

    elements.append(
        f'<rect x="{pad_left}" y="{pad_top}" width="{chart_w}" height="{chart_h}" '
        f'fill="{BG_COLOR}" rx="4"/>'
    )

    if title:
        elements.append(
            f'<text x="{pad_left}" y="20" font-size="13" font-weight="700" '
            f'fill="#111827" font-family="Inter,system-ui,sans-serif">{html_mod.escape(title)}</text>'
        )

    # Grid lines
    for i in range(5):
        frac = i / 4
        y = pad_top + chart_h - frac * chart_h
        y_val = y_min + frac * y_range
        label = _fmt_val(10 ** y_val if log_y else y_val, y_key)
        elements.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + chart_w}" y2="{y:.1f}" '
            f'stroke="{GRID_COLOR}" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="9" fill="{LABEL_COLOR}" font-family="Inter,system-ui,sans-serif">{label}</text>'
        )
        x = pad_left + frac * chart_w
        x_val = x_min + frac * x_range
        xlabel = _fmt_val(10 ** x_val if log_x else x_val, x_key)
        elements.append(
            f'<line x1="{x:.1f}" y1="{pad_top}" x2="{x:.1f}" y2="{pad_top + chart_h}" '
            f'stroke="{GRID_COLOR}" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="{x:.1f}" y="{pad_top + chart_h + 16}" text-anchor="middle" '
            f'font-size="9" fill="{LABEL_COLOR}" font-family="Inter,system-ui,sans-serif">{xlabel}</text>'
        )

    # Axis labels
    if x_label:
        elements.append(
            f'<text x="{pad_left + chart_w / 2}" y="{height - 6}" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="{LABEL_COLOR}" '
            f'font-family="Inter,system-ui,sans-serif">{html_mod.escape(x_label)}</text>'
        )
    if y_label:
        elements.append(
            f'<text x="14" y="{pad_top + chart_h / 2}" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="{LABEL_COLOR}" '
            f'font-family="Inter,system-ui,sans-serif" '
            f'transform="rotate(-90, 14, {pad_top + chart_h / 2})">{html_mod.escape(y_label)}</text>'
        )

    # Axis lines
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{pad_left + chart_w}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="1"/>'
    )
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top}" '
        f'x2="{pad_left}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="1"/>'
    )

    # Plot points
    for idx, p in enumerate(valid):
        xv = _safe_log(p[x_key]) if log_x else p[x_key]
        yv = _safe_log(p[y_key]) if log_y else p[y_key]
        if xv is None or yv is None:
            continue

        dot_cx = scale_x(xv)
        dot_cy = scale_y(yv)

        if color_key and p.get(color_key):
            color = THESIS_COLORS.get(p[color_key], "#9CA3AF")
        else:
            color = "#111111"

        if size_key and max_size > 0 and size_vals:
            sv = size_vals[idx] if idx < len(size_vals) else 0
            r = min_r + (sv / max_size) * (max_r - min_r) if max_size else min_r
        else:
            r = 4

        slug = p.get("slug", "")
        ticker = html_mod.escape(p.get("ticker", "")[:6])
        name = html_mod.escape(p.get("name", "")[:20])

        elements.append(
            f'<a href="/token/{slug}">'
            f'<circle cx="{dot_cx:.1f}" cy="{dot_cy:.1f}" r="{r:.1f}" '
            f'fill="{color}" opacity="0.65" class="scatter-dot">'
            f'<title>{name} ({ticker})</title>'
            f'</circle>'
            f'</a>'
        )

        if r > 8 and ticker:
            elements.append(
                f'<text x="{dot_cx:.1f}" y="{dot_cy - r - 3:.1f}" text-anchor="middle" '
                f'font-size="8" font-weight="600" fill="{color}" '
                f'font-family="Inter,system-ui,sans-serif">{ticker}</text>'
            )

    # Watermark
    elements.append(
        f'<text x="{pad_left + chart_w - 4}" y="{pad_top + chart_h - 6}" text-anchor="end" '
        f'font-size="8" font-weight="600" fill="#D1D5DB" '
        f'font-family="Inter,system-ui,sans-serif" opacity="0.5">Onchain Pulse</text>'
    )

    elements.append('</svg>')
    return "\n".join(elements)
