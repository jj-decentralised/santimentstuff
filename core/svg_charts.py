"""
Pure SVG chart generation — no JavaScript required.

WSJ-inspired chart engine with:
- Clean, minimal design with generous whitespace
- Thin, precise lines (1–1.5px)
- Light dotted horizontal gridlines
- Professional serif/sans-serif typography
- Muted, authoritative color palette (navy, slate, warm gray)
- Right-aligned Y-axis labels
- High data-to-ink ratio
- No gratuitous gradients or decorative effects
"""

import html as html_mod
import math
from typing import Optional


# ============================================================
# WSJ-INSPIRED COLOR PALETTE
# ============================================================

# Primary series colors — muted, professional, WSJ-like
COLORS = [
    "#0A2463",   # deep navy (primary)
    "#C84630",   # WSJ red/brick
    "#2D7D9A",   # teal-blue
    "#7D5A3C",   # warm brown
    "#5B7065",   # sage green
    "#8E6C88",   # muted plum
    "#B8860B",   # dark goldenrod
    "#4A6FA5",   # steel blue
    "#C17817",   # amber/ochre
    "#3D5A80",   # slate blue
]

GRID_COLOR = "#E8E8E8"
LABEL_COLOR = "#666666"
AXIS_COLOR = "#333333"
BG_COLOR = "none"  # transparent — let the container handle background

# WSJ typography stack — serif for data labels, clean and authoritative
FONT_LABEL = '"Georgia","Cambria","Times New Roman",serif'
FONT_DATA = '"Helvetica Neue","Arial",sans-serif'
FONT_TITLE = '"Helvetica Neue","Arial",sans-serif'

# Heatmap color scale — more muted, WSJ editorial style
HEATMAP_COLORS = {
    "extreme_neg": "#B91C1C",
    "neg": "#DC6B50",
    "slight_neg": "#E8A998",
    "neutral": "#E8E8E8",
    "slight_pos": "#93C5A4",
    "pos": "#3D8B5F",
    "extreme_pos": "#1B5E3B",
}


# ============================================================
# FORMATTING — Clean, human-readable labels
# ============================================================

def _fmt_compact(v: float) -> str:
    """Compact number for tooltips."""
    if v is None:
        return "\u2013"
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
    mag = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    nice_steps = [1, 2, 2.5, 5, 10]
    norm = raw_step / mag
    step = mag
    for ns in nice_steps:
        if ns >= norm:
            step = ns * mag
            break

    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.01:
        if v >= lo - step * 0.01:
            ticks.append(round(v, 10))
        v += step
    return ticks if ticks else [lo, hi]


def _fmt_date(dt_str: str) -> str:
    """Format ISO date for chart labels — WSJ style: 'Jan 5'."""
    try:
        parts = dt_str[:10].split("-")
        months = ["", "Jan.", "Feb.", "Mar.", "Apr.", "May", "June",
                  "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
        day = str(int(parts[2]))
        return f"{months[int(parts[1])]} {day}"
    except Exception:
        return dt_str[:10]


def _fmt_date_year(dt_str: str) -> str:
    """Format date with year for longer charts — WSJ style: 'Jan. 2024'."""
    try:
        parts = dt_str[:10].split("-")
        months = ["", "Jan.", "Feb.", "Mar.", "Apr.", "May", "June",
                  "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
        return f"{months[int(parts[1])]} {parts[0]}"
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
    color: str = "#0A2463",
    show_change_color: bool = True,
) -> str:
    """Tiny inline sparkline SVG — clean single line, no fill."""
    values = [d.get("value") for d in data if d.get("value") is not None]
    if len(values) < 2:
        return ""

    min_v = min(values)
    max_v = max(values)
    v_range = max_v - min_v if max_v != min_v else 1
    n = len(values)

    if show_change_color:
        color = "#1B5E3B" if values[-1] >= values[0] else "#B91C1C"

    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / v_range) * (height - 4) - 2
        points.append((x, y))

    line_d = _smooth_path(points, tension=0.2)

    # Tooltip
    first_v, last_v = values[0], values[-1]
    if first_v and first_v != 0:
        chg = (last_v - first_v) / first_v * 100
        chg_str = f" ({chg:+.1f}%)"
    else:
        chg_str = ""
    tooltip = f"{_fmt_compact(last_v)}{chg_str}"

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<title>{tooltip}</title>'
        f'<path d="{line_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="1.5" fill="{color}"/>'
        f'</svg>'
    )


# ============================================================
# LINE CHART — WSJ-style: clean, precise, authoritative
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
    ref_lines: list[tuple] = None,
) -> str:
    """
    WSJ-style line chart: thin precise lines, dotted gridlines,
    right-side Y labels, serif typography, high data-ink ratio.
    """
    if not series or not any(s.get("data") for s in series):
        return '<div class="chart-empty">No chart data available</div>'

    # Chart dimensions — generous left padding for labels
    pad_left = 12
    pad_right = 62
    pad_top = 40 if title else 20
    pad_bottom = 36
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    # Collect all values
    all_values = []
    for s in series:
        for d in (s.get("data") or []):
            v = d.get("value")
            if v is not None:
                all_values.append(v)

    if not all_values:
        return '<div class="chart-empty">No chart data available</div>'

    # Smart Y-axis range with outlier clamping
    clamped_lo, clamped_hi = _clamp_outliers(all_values, pct=2.0)

    all_positive = min(all_values) >= 0
    if all_positive:
        range_span = clamped_hi - clamped_lo
        if range_span > 0 and clamped_lo < range_span * 0.08:
            clamped_lo = 0
        else:
            clamped_lo = max(0, clamped_lo * 0.92)

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

    # Title — WSJ uses bold sans-serif above chart
    if title:
        elements.append(
            f'<text x="{pad_left}" y="18" font-size="14" font-weight="700" '
            f'fill="#222222" font-family={FONT_TITLE} letter-spacing="-0.3">{html_mod.escape(title)}</text>'
        )

    # Y-axis: thin dotted gridlines + right-side labels (WSJ style)
    if show_grid:
        for tick in ticks:
            y = scale_y(tick)
            label = _fmt_val(tick, metric_key)
            # Dotted gridline
            elements.append(
                f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + chart_w}" y2="{y:.1f}" '
                f'stroke="{GRID_COLOR}" stroke-width="0.7" stroke-dasharray="2,3"/>'
            )
            # Right-side label (WSJ convention)
            elements.append(
                f'<text x="{pad_left + chart_w + 8}" y="{y + 3.5:.1f}" text-anchor="start" '
                f'font-size="10" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>{label}</text>'
            )

    # Reference lines (horizontal annotations)
    if ref_lines:
        for ref_val, ref_label, ref_color in ref_lines:
            if clamped_lo <= ref_val <= clamped_hi:
                ry = scale_y(ref_val)
                elements.append(
                    f'<line x1="{pad_left}" y1="{ry:.1f}" x2="{pad_left + chart_w}" y2="{ry:.1f}" '
                    f'stroke="{ref_color}" stroke-width="0.8" stroke-dasharray="5,3" opacity="0.7"/>'
                )
                elements.append(
                    f'<text x="{pad_left + chart_w + 8}" y="{ry + 3:.1f}" text-anchor="start" '
                    f'font-size="9" font-weight="600" fill="{ref_color}" '
                    f'font-family={FONT_LABEL}>{html_mod.escape(ref_label)}</text>'
                )

    # Draw each series
    for si, s in enumerate(series):
        data = s.get("data") or []
        if not data:
            continue

        color = s.get("color") or COLORS[si % len(COLORS)]

        # Downsample dense data
        max_points = 350
        if len(data) > max_points:
            step = len(data) / max_points
            sampled = []
            for j in range(max_points):
                idx = int(j * step)
                sampled.append(data[min(idx, len(data) - 1)])
            if sampled[-1] is not data[-1]:
                sampled[-1] = data[-1]
            data = sampled

        n = len(data)
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

        # Very subtle area fill — WSJ occasionally uses light fills
        gid = f"grad_{si}_{abs(hash(color)) % 99999}"
        if show_area and len(series) == 1:
            grad_opacity = 0.06
            defs.append(_gradient_def(gid, color, grad_opacity, 0.0))
            clip_id = f"clip_{si}"
            defs.append(
                f'<clipPath id="{clip_id}">'
                f'<rect x="{pad_left}" y="{pad_top}" width="{chart_w}" height="{chart_h}"/>'
                f'</clipPath>'
            )
            area_d = (
                _smooth_path(points, tension=0.15 if len(points) > 200 else 0.2) +
                f" L{points[-1][0]:.1f},{pad_top + chart_h:.1f}"
                f" L{points[0][0]:.1f},{pad_top + chart_h:.1f} Z"
            )
            elements.append(
                f'<path d="{area_d}" fill="url(#{gid})" clip-path="url(#{clip_id})"/>'
            )

        # Main line — precise, thin
        tension = 0.12 if len(points) > 200 else 0.2
        line_d = _smooth_path(points, tension=tension)
        stroke_w = "1.2" if len(points) > 250 else "1.5"
        if len(series) > 2:
            stroke_w = "1.2"
        elements.append(
            f'<path d="{line_d}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_w}" stroke-linejoin="round"/>'
        )

        # Latest value — small dot with label (WSJ highlights current)
        if points:
            lx, ly = points[-1]
            lv = None
            for d in reversed(data):
                if d.get("value") is not None:
                    lv = d["value"]
                    break
            if lv is not None and len(series) <= 2:
                label_text = _fmt_val(lv, metric_key)
                elements.append(
                    f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" '
                    f'fill="{color}" stroke="white" stroke-width="1.5"/>'
                )
                # Label always on right side near the dot
                elements.append(
                    f'<text x="{pad_left + chart_w + 8}" y="{ly + 4:.1f}" text-anchor="start" '
                    f'font-size="11" font-weight="700" fill="{color}" '
                    f'font-family={FONT_DATA}>{label_text}</text>'
                )

    # X-axis date labels
    primary_data = series[0].get("data") or []
    if primary_data:
        n = len(primary_data)
        use_year = n > 180
        n_labels = min(x_label_count, max(2, n // 60))
        step = max(1, (n - 1) // n_labels)
        indices = list(range(0, n, step))
        if indices[-1] != n - 1:
            indices.append(n - 1)

        for idx in indices:
            dt = primary_data[idx].get("datetime", "")
            x = pad_left + (idx / max(n - 1, 1)) * chart_w
            label = _fmt_date_year(dt) if use_year else _fmt_date(dt)
            elements.append(
                f'<text x="{x:.1f}" y="{pad_top + chart_h + 18}" text-anchor="middle" '
                f'font-size="9" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>{label}</text>'
            )

    # Bottom axis line — the only solid line (WSJ style)
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{pad_left + chart_w}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="0.8"/>'
    )

    # Legend (multi-series) — clean, left-aligned
    if len(series) > 1:
        leg_y = height - 4
        leg_x = pad_left
        for si, s in enumerate(series):
            color = s.get("color") or COLORS[si % len(COLORS)]
            label = s.get("label", f"Series {si+1}")
            elements.append(
                f'<line x1="{leg_x}" y1="{leg_y - 3}" x2="{leg_x + 14}" y2="{leg_y - 3}" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            elements.append(
                f'<text x="{leg_x + 18}" y="{leg_y}" font-size="9" font-weight="500" fill="#555" '
                f'font-family={FONT_DATA}>{html_mod.escape(label)}</text>'
            )
            leg_x += len(label) * 5.8 + 32

    # Source line — small, bottom-left (WSJ convention)
    elements.append(
        f'<text x="{pad_left}" y="{height - 2}" text-anchor="start" '
        f'font-size="8" fill="#AAAAAA" font-family={FONT_LABEL} '
        f'font-style="italic">Source: Santiment</text>'
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

    lower_is_better = {"nvt"}

    rows = []
    for key, label in metric_keys:
        vals = []
        for t in tokens:
            m = t.get("metrics", {}).get(key, {})
            v = m.get("latest")
            vals.append(v)
        numeric_vals = [v for v in vals if v is not None]
        if numeric_vals:
            best = min(numeric_vals) if key in lower_is_better else max(numeric_vals)
        else:
            best = None

        cells = f'<td class="col-name">{html_mod.escape(label)}</td>'
        for v in vals:
            if v is None:
                cells += '<td class="col-num">&mdash;</td>'
            else:
                is_best = (best is not None and v == best and len(numeric_vals) > 1)
                cls = "col-num num-bold compare-best" if is_best else "col-num num-bold"
                cells += f'<td class="{cls}">{_fmt_val(v, key)}</td>'
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
        return "#555555"
    if abs(pct_change) >= 5:
        return "#FFFFFF"
    return "#333333"


def market_heatmap_svg(tokens: list[dict], max_tokens: int = 50) -> str:
    """Treemap-style heatmap — WSJ editorial style with clean typography."""
    if not tokens:
        return ""

    sorted_tokens = sorted(tokens, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)[:max_tokens]
    if not sorted_tokens:
        return ""

    total_mcap = sum(t.get("marketcap_usd") or 0 for t in sorted_tokens) or 1

    width = 700
    height = 320
    padding = 1.5

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
                f'rx="1" fill="{bg}"/>'
            )

            if w > 45:
                cx = x + w / 2
                cy = y + row_h / 2
                elements.append(
                    f'<text x="{cx:.1f}" y="{cy - 5:.1f}" text-anchor="middle" '
                    f'font-size="{min(11, max(8, w/8)):.0f}" font-weight="700" fill="{fg}" '
                    f'font-family={FONT_DATA}>{ticker}</text>'
                )
                elements.append(
                    f'<text x="{cx:.1f}" y="{cy + 9:.1f}" text-anchor="middle" '
                    f'font-size="{min(10, max(7, w/10)):.0f}" font-weight="500" fill="{fg}" '
                    f'opacity="0.9" font-family={FONT_LABEL}>{pct_str}</text>'
                )
            elements.append('</a>')
            x += w

        idx = row_end

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# MARKET DOMINANCE — Horizontal stacked bar
# ============================================================

def dominance_bar_svg(tokens: list[dict], width: int = 700, height: int = 56) -> str:
    """Horizontal stacked bar — WSJ style with clean segments."""
    if not tokens:
        return ""

    total = sum(t.get("marketcap_usd") or 0 for t in tokens) or 1
    bar_y = 0
    bar_h = 28
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
            "color": "#CCCCCC",
        })

    for seg in segments:
        w = max(2, (seg["value"] / total) * width)
        elements.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{w:.1f}" height="{bar_h}" '
            f'fill="{seg["color"]}"/>'
        )
        if w > 45:
            elements.append(
                f'<text x="{x + w/2:.1f}" y="{bar_y + bar_h/2 + 4:.1f}" text-anchor="middle" '
                f'font-size="9" font-weight="700" fill="white" '
                f'font-family={FONT_DATA}>{seg["label"]} {seg["pct"]:.1f}%</text>'
            )
        x += w

    # Legend — clean line items
    leg_x = 0
    for seg in segments:
        if seg["pct"] < 1:
            continue
        elements.append(
            f'<rect x="{leg_x}" y="{label_y - 6}" width="10" height="10" rx="1" fill="{seg["color"]}"/>'
        )
        label = f'{seg["label"]} {seg["pct"]:.1f}%'
        elements.append(
            f'<text x="{leg_x + 14}" y="{label_y + 3}" font-size="9" font-weight="500" '
            f'fill="#555" font-family={FONT_DATA}>{label}</text>'
        )
        leg_x += len(label) * 5.5 + 22

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# DONUT CHART — Market dominance / allocation visualization
# ============================================================

def donut_chart_svg(
    tokens: list[dict],
    width: int = 260,
    height: int = 260,
    inner_ratio: float = 0.62,
    max_slices: int = 8,
) -> str:
    """Donut chart — WSJ style with muted palette and clean labels."""
    if not tokens:
        return ""

    total = sum(t.get("marketcap_usd") or 0 for t in tokens) or 1
    sorted_tokens = sorted(tokens, key=lambda t: t.get("marketcap_usd") or 0, reverse=True)

    slices = []
    for i, t in enumerate(sorted_tokens[:max_slices]):
        mcap = t.get("marketcap_usd") or 0
        slices.append({
            "label": t.get("ticker", "?"),
            "value": mcap,
            "pct": (mcap / total) * 100,
            "color": COLORS[i % len(COLORS)],
        })

    others = sum(t.get("marketcap_usd") or 0 for t in sorted_tokens[max_slices:])
    if others > 0:
        slices.append({
            "label": "Others",
            "value": others,
            "pct": (others / total) * 100,
            "color": "#CCCCCC",
        })

    cx, cy = width / 2, height / 2 - 10
    r_outer = min(width, height) / 2 - 22
    r_inner = r_outer * inner_ratio

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    angle = -math.pi / 2
    for s in slices:
        if s["pct"] < 0.3:
            continue
        sweep = (s["value"] / total) * 2 * math.pi
        x1_o = cx + r_outer * math.cos(angle)
        y1_o = cy + r_outer * math.sin(angle)
        x2_o = cx + r_outer * math.cos(angle + sweep)
        y2_o = cy + r_outer * math.sin(angle + sweep)
        x1_i = cx + r_inner * math.cos(angle + sweep)
        y1_i = cy + r_inner * math.sin(angle + sweep)
        x2_i = cx + r_inner * math.cos(angle)
        y2_i = cy + r_inner * math.sin(angle)

        large = 1 if sweep > math.pi else 0

        d = (
            f"M {x1_o:.2f} {y1_o:.2f} "
            f"A {r_outer:.2f} {r_outer:.2f} 0 {large} 1 {x2_o:.2f} {y2_o:.2f} "
            f"L {x1_i:.2f} {y1_i:.2f} "
            f"A {r_inner:.2f} {r_inner:.2f} 0 {large} 0 {x2_i:.2f} {y2_i:.2f} Z"
        )

        elements.append(
            f'<path d="{d}" fill="{s["color"]}" stroke="white" stroke-width="2">'
            f'<title>{html_mod.escape(s["label"])}: {s["pct"]:.1f}%</title></path>'
        )

        # External label
        mid_angle = angle + sweep / 2
        label_r = r_outer + 16
        lx = cx + label_r * math.cos(mid_angle)
        ly = cy + label_r * math.sin(mid_angle)
        anchor = "start" if lx > cx else "end"
        if abs(lx - cx) < 10:
            anchor = "middle"

        if s["pct"] >= 4:
            elements.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                f'font-size="9" font-weight="600" fill="#444" '
                f'font-family={FONT_DATA}>'
                f'{html_mod.escape(s["label"])} {s["pct"]:.0f}%</text>'
            )

        angle += sweep

    # Center text
    elements.append(
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" '
        f'font-size="11" font-weight="700" fill="#222" '
        f'font-family={FONT_DATA}>Market</text>'
    )
    elements.append(
        f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" '
        f'font-size="9" font-weight="400" fill="#777" '
        f'font-family={FONT_LABEL}>Dominance</text>'
    )

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
    """Semicircle gauge — WSJ-clean with muted color bands."""
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
        f'fill="none" stroke="#E8E8E8" stroke-width="10" stroke-linecap="round"/>'
    )

    # Color segments — muted tones
    segments = [
        (0, 0.33, "#3D8B5F"),
        (0.33, 0.66, "#B8860B"),
        (0.66, 1.0, "#B91C1C"),
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
            f'fill="none" stroke="{color}" stroke-width="10" stroke-linecap="butt" opacity="0.25"/>'
        )

    # Needle — thin, elegant
    needle_angle = math.pi * (1 - norm)
    nx = cx + (r - 8) * math.cos(needle_angle)
    ny = cy - (r - 8) * math.sin(needle_angle)
    elements.append(
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
        f'stroke="#222222" stroke-width="2" stroke-linecap="round"/>'
    )
    elements.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="#222222"/>')
    elements.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="white"/>')

    # Value
    elements.append(
        f'<text x="{cx:.1f}" y="{cy - r/2 - 2:.1f}" text-anchor="middle" '
        f'font-size="22" font-weight="800" fill="#222222" '
        f'font-family={FONT_DATA}>{value:.2f}</text>'
    )
    elements.append(
        f'<text x="{cx:.1f}" y="{cy + 16:.1f}" text-anchor="middle" '
        f'font-size="9" font-weight="500" fill="#888" '
        f'font-family={FONT_LABEL}>{html_mod.escape(label)}</text>'
    )

    # Min/Max labels
    elements.append(
        f'<text x="{cx - r - 4:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
        f'font-size="8" fill="#999" font-family={FONT_LABEL}>Undervalued</text>'
    )
    elements.append(
        f'<text x="{cx + r + 4:.1f}" y="{cy + 4:.1f}" text-anchor="start" '
        f'font-size="8" fill="#999" font-family={FONT_LABEL}>Overvalued</text>'
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
    color: str = "#0A2463",
) -> str:
    """Small line chart for stat cards — minimal, WSJ style."""
    values = [d.get("value") for d in data if d.get("value") is not None]
    if len(values) < 3:
        return ""

    min_v = min(values)
    max_v = max(values)
    v_range = max_v - min_v if max_v != min_v else 1
    n = len(values)

    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / v_range) * (height - 4) - 2
        points.append((x, y))

    line_d = _smooth_path(points, tension=0.2)

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<path d="{line_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


# ============================================================
# SCATTER PLOT — Cross-metric analysis
# ============================================================

THESIS_COLORS = {
    "smart_money": "#1B5E3B",
    "builder_momentum": "#2D7D9A",
    "deep_value": "#3D8B5F",
    "distribution_warning": "#B91C1C",
    "hodler": "#8E6C88",
    "high_utility": "#4A6FA5",
    "speculative": "#C17817",
    "uncategorized": "#999999",
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
    """Scatter plot — WSJ style: clean axes, dotted grid, muted dots."""
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

    pad_left = 12
    pad_right = 62
    pad_top = 40 if title else 20
    pad_bottom = 52
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    x_min, x_max = min(x_vals), max(x_vals)
    y_min, y_max = min(y_vals), max(y_vals)
    x_range = x_max - x_min if x_max != x_min else 1
    y_range = y_max - y_min if y_max != y_min else 1
    x_pad_v = x_range * 0.05
    y_pad_v = y_range * 0.05
    x_min -= x_pad_v
    x_max += x_pad_v
    y_min -= y_pad_v
    y_max += y_pad_v
    x_range = x_max - x_min
    y_range = y_max - y_min

    def scale_x(v):
        return pad_left + ((v - x_min) / x_range) * chart_w

    def scale_y(v):
        return pad_top + chart_h - ((v - y_min) / y_range) * chart_h

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

    if title:
        elements.append(
            f'<text x="{pad_left}" y="18" font-size="14" font-weight="700" '
            f'fill="#222" font-family={FONT_TITLE}>{html_mod.escape(title)}</text>'
        )

    # Dotted gridlines
    for i in range(5):
        frac = i / 4
        y = pad_top + chart_h - frac * chart_h
        y_val = y_min + frac * y_range
        label = _fmt_val(10 ** y_val if log_y else y_val, y_key)
        elements.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + chart_w}" y2="{y:.1f}" '
            f'stroke="{GRID_COLOR}" stroke-width="0.7" stroke-dasharray="2,3"/>'
        )
        elements.append(
            f'<text x="{pad_left + chart_w + 8}" y="{y + 3.5:.1f}" text-anchor="start" '
            f'font-size="9" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>{label}</text>'
        )
        x = pad_left + frac * chart_w
        x_val = x_min + frac * x_range
        xlabel = _fmt_val(10 ** x_val if log_x else x_val, x_key)
        elements.append(
            f'<text x="{x:.1f}" y="{pad_top + chart_h + 16}" text-anchor="middle" '
            f'font-size="9" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>{xlabel}</text>'
        )

    # Axis labels
    if x_label:
        elements.append(
            f'<text x="{pad_left + chart_w / 2}" y="{height - 4}" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#555" '
            f'font-family={FONT_DATA}>{html_mod.escape(x_label)}</text>'
        )
    if y_label:
        elements.append(
            f'<text x="10" y="{pad_top + chart_h / 2}" text-anchor="middle" '
            f'font-size="10" font-weight="600" fill="#555" '
            f'font-family={FONT_DATA} '
            f'transform="rotate(-90, 10, {pad_top + chart_h / 2})">{html_mod.escape(y_label)}</text>'
        )

    # Axis lines
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{pad_left + chart_w}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="0.8"/>'
    )

    # Plot points — slightly larger, less opacity for overlap
    for idx_p, p in enumerate(valid):
        xv = _safe_log(p[x_key]) if log_x else p[x_key]
        yv = _safe_log(p[y_key]) if log_y else p[y_key]
        if xv is None or yv is None:
            continue

        dot_cx = scale_x(xv)
        dot_cy = scale_y(yv)

        if color_key and p.get(color_key):
            color = THESIS_COLORS.get(p[color_key], "#999999")
        else:
            color = "#0A2463"

        if size_key and max_size > 0 and size_vals:
            sv = size_vals[idx_p] if idx_p < len(size_vals) else 0
            r = min_r + (sv / max_size) * (max_r - min_r) if max_size else min_r
        else:
            r = 4.5

        slug = p.get("slug", "")
        ticker = html_mod.escape(p.get("ticker", "")[:6])
        name = html_mod.escape(p.get("name", "")[:20])

        elements.append(
            f'<a href="/token/{slug}">'
            f'<circle cx="{dot_cx:.1f}" cy="{dot_cy:.1f}" r="{r:.1f}" '
            f'fill="{color}" opacity="0.55" stroke="{color}" stroke-width="0.5" stroke-opacity="0.3" class="scatter-dot">'
            f'<title>{name} ({ticker})</title>'
            f'</circle>'
            f'</a>'
        )

        if r > 8 and ticker:
            elements.append(
                f'<text x="{dot_cx:.1f}" y="{dot_cy - r - 3:.1f}" text-anchor="middle" '
                f'font-size="8" font-weight="600" fill="#444" '
                f'font-family={FONT_DATA}>{ticker}</text>'
            )

    # Source line
    elements.append(
        f'<text x="{pad_left}" y="{height - 2}" text-anchor="start" '
        f'font-size="8" fill="#AAA" font-family={FONT_LABEL} '
        f'font-style="italic">Source: Santiment</text>'
    )

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# BAR CHART — Vertical bars for volume / discrete data
# ============================================================

def bar_chart_svg(
    data: list[dict],
    width: int = 340,
    height: int = 180,
    title: str = "",
    color: str = "#0A2463",
    metric_key: str = "",
) -> str:
    """Vertical bar chart — WSJ style: uniform color, clean gridlines."""
    if not data or len(data) < 2:
        return '<div class="chart-empty">No bar data</div>'

    values = [d.get("value") for d in data if d.get("value") is not None]
    if not values:
        return '<div class="chart-empty">No bar data</div>'

    pad_left = 10
    pad_right = 52
    pad_top = 30 if title else 12
    pad_bottom = 28
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    max_val = max(values) if values else 1
    if max_val == 0:
        max_val = 1

    n = len(data)
    bar_w = max(1.5, chart_w / n - 1)
    gap = max(0.5, (chart_w - bar_w * n) / max(1, n - 1))

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    if title:
        elements.append(
            f'<text x="{pad_left}" y="18" font-size="12" font-weight="700" '
            f'fill="#222" font-family={FONT_TITLE}>{html_mod.escape(title)}</text>'
        )

    # Dotted gridlines with right-side labels
    for i in range(5):
        gy = pad_top + (chart_h / 4) * i
        gv = max_val * (1 - i / 4)
        elements.append(
            f'<line x1="{pad_left}" y1="{gy:.1f}" x2="{pad_left + chart_w}" y2="{gy:.1f}" '
            f'stroke="{GRID_COLOR}" stroke-width="0.7" stroke-dasharray="2,3"/>'
        )
        elements.append(
            f'<text x="{pad_left + chart_w + 6}" y="{gy + 3:.1f}" text-anchor="start" '
            f'font-size="8" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>'
            f'{_fmt_val(gv, metric_key)}</text>'
        )

    # Bars — uniform color, no opacity gradient
    for i, d in enumerate(data):
        v = d.get("value")
        if v is None:
            continue
        bx = pad_left + i * (bar_w + gap)
        bh = max(1, (v / max_val) * chart_h)
        by = pad_top + chart_h - bh
        elements.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
            f'fill="{color}" opacity="0.75">'
            f'<title>{_fmt_val(v, metric_key)}</title></rect>'
        )

    # Bottom axis line
    elements.append(
        f'<line x1="{pad_left}" y1="{pad_top + chart_h}" '
        f'x2="{pad_left + chart_w}" y2="{pad_top + chart_h}" '
        f'stroke="{AXIS_COLOR}" stroke-width="0.8"/>'
    )

    # X-axis date labels
    for idx_d in [0, n // 2, n - 1]:
        if idx_d < len(data):
            dt = data[idx_d].get("datetime") or data[idx_d].get("date", "")
            label = _fmt_date(dt) if len(dt) >= 10 else dt[:10]
            lx = pad_left + idx_d * (bar_w + gap) + bar_w / 2
            elements.append(
                f'<text x="{lx:.1f}" y="{pad_top + chart_h + 14}" text-anchor="middle" '
                f'font-size="8" fill="{LABEL_COLOR}" font-family={FONT_LABEL}>{html_mod.escape(label)}</text>'
            )

    elements.append('</svg>')
    return "\n".join(elements)


# ============================================================
# RADAR CHART — Spider/radar for multi-dimensional comparison
# ============================================================

def radar_chart_svg(
    items: list[dict],
    axes: list[tuple[str, str]],
    width: int = 360,
    height: int = 360,
) -> str:
    """Radar chart — WSJ editorial style: thin lines, muted fills."""
    if not items or len(axes) < 3:
        return '<div class="chart-empty">Need at least 3 axes for radar</div>'

    n_axes = len(axes)
    cx, cy = width / 2, height / 2
    r_max = min(width, height) / 2 - 40

    elements = [
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    ]

    axis_max = {}
    for key, _ in axes:
        vals = [item["values"].get(key, 0) for item in items]
        axis_max[key] = max(vals) if vals and max(vals) > 0 else 1

    # Concentric rings — dotted
    for level in range(1, 6):
        r = r_max * level / 5
        ring_pts = []
        for i in range(n_axes):
            angle = -math.pi / 2 + (2 * math.pi * i / n_axes)
            ring_pts.append(f"{cx + r * math.cos(angle):.1f},{cy + r * math.sin(angle):.1f}")
        elements.append(
            f'<polygon points="{" ".join(ring_pts)}" '
            f'fill="none" stroke="{GRID_COLOR}" stroke-width="0.5" stroke-dasharray="2,2"/>'
        )

    # Axis lines and labels
    for i, (key, label) in enumerate(axes):
        angle = -math.pi / 2 + (2 * math.pi * i / n_axes)
        ex = cx + r_max * math.cos(angle)
        ey = cy + r_max * math.sin(angle)
        elements.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="{GRID_COLOR}" stroke-width="0.5"/>'
        )
        lx = cx + (r_max + 16) * math.cos(angle)
        ly = cy + (r_max + 16) * math.sin(angle)
        anchor = "middle"
        if lx < cx - 10:
            anchor = "end"
        elif lx > cx + 10:
            anchor = "start"
        elements.append(
            f'<text x="{lx:.1f}" y="{ly + 3:.1f}" text-anchor="{anchor}" '
            f'font-size="9" font-weight="500" fill="#555" '
            f'font-family={FONT_DATA}>{html_mod.escape(label)}</text>'
        )

    # Data polygons
    for item in items:
        color = item.get("color", "#0A2463")
        pts = []
        for i, (key, _) in enumerate(axes):
            val = item["values"].get(key, 0)
            norm_v = (val / axis_max[key]) if axis_max[key] > 0 else 0
            norm_v = min(1.0, max(0, norm_v))
            r = r_max * norm_v
            angle = -math.pi / 2 + (2 * math.pi * i / n_axes)
            pts.append(f"{cx + r * math.cos(angle):.1f},{cy + r * math.sin(angle):.1f}")

        elements.append(
            f'<polygon points="{" ".join(pts)}" '
            f'fill="{color}" fill-opacity="0.1" '
            f'stroke="{color}" stroke-width="1.2" stroke-linejoin="round">'
            f'<title>{html_mod.escape(item.get("label", ""))}</title></polygon>'
        )
        for pt in pts:
            px, py = pt.split(",")
            elements.append(
                f'<circle cx="{px}" cy="{py}" r="2.5" fill="{color}" stroke="white" stroke-width="1"/>'
            )

    # Legend
    leg_y = height - 14
    leg_x = 10
    for item in items:
        color = item.get("color", "#0A2463")
        label = item.get("label", "")[:15]
        elements.append(
            f'<line x1="{leg_x}" y1="{leg_y}" x2="{leg_x + 12}" y2="{leg_y}" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        elements.append(
            f'<text x="{leg_x + 16}" y="{leg_y + 3.5}" font-size="9" font-weight="500" '
            f'fill="#444" font-family={FONT_DATA}>{html_mod.escape(label)}</text>'
        )
        leg_x += len(label) * 5.5 + 28

    elements.append('</svg>')
    return "\n".join(elements)
