"""
Pure SVG chart generation — no JavaScript required.

All charts are rendered as inline SVG elements in HTML.
Supports: line charts, area charts, sparklines, multi-series overlays.
"""

import html as html_mod
from typing import Optional


# ============================================================
# COLORS
# ============================================================

COLORS = [
    "#000000",   # black (primary)
    "#2563EB",   # blue
    "#DC2626",   # red
    "#16A34A",   # green
    "#D97706",   # amber
    "#7C3AED",   # purple
    "#0891B2",   # cyan
    "#DB2777",   # pink
]

GRID_COLOR = "#E5E5E5"
LABEL_COLOR = "#737373"
AXIS_COLOR = "#A3A3A3"


def _fmt_val(v: float, key: str = "") -> str:
    """Format a value for axis labels."""
    if v is None:
        return ""
    a = abs(v)
    if "usd" in key and "mvrv" not in key and "nvt" not in key and "percent" not in key:
        if a >= 1e12:
            return f"${v/1e12:.1f}T"
        if a >= 1e9:
            return f"${v/1e9:.1f}B"
        if a >= 1e6:
            return f"${v/1e6:.1f}M"
        if a >= 1e3:
            return f"${v/1e3:.0f}K"
        if a >= 1:
            return f"${v:.2f}"
        return f"${v:.4f}"
    if a >= 1e9:
        return f"{v/1e9:.1f}B"
    if a >= 1e6:
        return f"{v/1e6:.1f}M"
    if a >= 1e3:
        return f"{v/1e3:.0f}K"
    if a >= 100:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


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
    """
    Generate a tiny inline sparkline SVG.
    data: list of {"value": float} dicts (ordered chronologically)
    """
    values = [d.get("value") for d in data if d.get("value") is not None]
    if len(values) < 2:
        return ""

    min_v = min(values)
    max_v = max(values)
    v_range = max_v - min_v if max_v != min_v else 1
    n = len(values)

    if show_change_color:
        color = "#16A34A" if values[-1] >= values[0] else "#DC2626"

    points = []
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width
        y = height - ((v - min_v) / v_range) * (height - 2) - 1
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="vertical-align:middle">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


# ============================================================
# LINE CHART — Full-size with axes, grid, labels
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
    y_label_count: int = 5,
    x_label_count: int = 6,
) -> str:
    """
    Generate a full line chart SVG with axes and labels.

    series: list of {
        "label": str,
        "data": [{"datetime": str, "value": float}, ...],
        "color": str (optional),
    }
    """
    if not series or not any(s.get("data") for s in series):
        return '<div class="chart-empty">No chart data available</div>'

    # Chart dimensions
    pad_left = 65
    pad_right = 15
    pad_top = 30 if title else 12
    pad_bottom = 40
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom

    # Compute global min/max across all series
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

    min_v = min(all_values)
    max_v = max(all_values)
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    v_range = max_v - min_v

    # Add 5% padding to y range
    padding = v_range * 0.05
    min_v -= padding
    max_v += padding
    v_range = max_v - min_v

    def scale_y(v):
        return pad_top + chart_h - ((v - min_v) / v_range) * chart_h

    elements = []
    elements.append(
        f'<svg width="100%" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" class="chart-svg">'
    )

    # Background
    elements.append(
        f'<rect x="{pad_left}" y="{pad_top}" width="{chart_w}" height="{chart_h}" '
        f'fill="#FAFAFA" rx="2"/>'
    )

    # Title
    if title:
        elements.append(
            f'<text x="{pad_left}" y="18" font-size="13" font-weight="700" '
            f'fill="#171717" font-family="Inter,sans-serif">{html_mod.escape(title)}</text>'
        )

    # Y-axis grid and labels
    if show_grid:
        for i in range(y_label_count):
            frac = i / (y_label_count - 1)
            y = pad_top + chart_h - frac * chart_h
            val = min_v + frac * v_range
            label = _fmt_val(val, metric_key)

            elements.append(
                f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + chart_w}" y2="{y:.1f}" '
                f'stroke="{GRID_COLOR}" stroke-width="1"/>'
            )
            elements.append(
                f'<text x="{pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
                f'font-size="10" fill="{LABEL_COLOR}" font-family="Inter,sans-serif">{label}</text>'
            )

    # Draw each series
    for si, s in enumerate(series):
        data = s.get("data") or []
        if not data:
            continue

        color = s.get("color") or COLORS[si % len(COLORS)]
        n = len(data)

        points = []
        for i, d in enumerate(data):
            v = d.get("value")
            if v is None:
                continue
            x = pad_left + (i / max(n - 1, 1)) * chart_w
            y = scale_y(v)
            points.append((x, y))

        if not points:
            continue

        # Area fill
        if show_area and len(series) == 1:
            area_pts = [f"{p[0]:.1f},{p[1]:.1f}" for p in points]
            area_pts.append(f"{points[-1][0]:.1f},{pad_top + chart_h:.1f}")
            area_pts.append(f"{points[0][0]:.1f},{pad_top + chart_h:.1f}")
            elements.append(
                f'<polygon points="{" ".join(area_pts)}" '
                f'fill="{color}" fill-opacity="0.08"/>'
            )

        # Line
        line_pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in points)
        elements.append(
            f'<polyline points="{line_pts}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        )

        # Dots (only for small datasets)
        if show_dots and len(points) <= 60:
            for px, py in points:
                elements.append(
                    f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" '
                    f'fill="{color}"/>'
                )

        # Latest value annotation
        if points:
            lx, ly = points[-1]
            lv = data[-1].get("value")
            if lv is not None:
                label_text = _fmt_val(lv, metric_key)
                elements.append(
                    f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" '
                    f'fill="white" stroke="{color}" stroke-width="2"/>'
                )
                # Label to left of dot to avoid clipping
                elements.append(
                    f'<text x="{lx - 8:.1f}" y="{ly - 8:.1f}" text-anchor="end" '
                    f'font-size="10" font-weight="600" fill="{color}" '
                    f'font-family="Inter,sans-serif">{label_text}</text>'
                )

    # X-axis date labels
    primary_data = series[0].get("data") or []
    if primary_data:
        n = len(primary_data)
        use_year = n > 180  # Show year for >6 months of data
        step = max(1, n // x_label_count)
        for i in range(0, n, step):
            dt = primary_data[i].get("datetime", "")
            x = pad_left + (i / max(n - 1, 1)) * chart_w
            label = _fmt_date_year(dt) if use_year else _fmt_date(dt)
            elements.append(
                f'<text x="{x:.1f}" y="{pad_top + chart_h + 18}" text-anchor="middle" '
                f'font-size="10" fill="{LABEL_COLOR}" font-family="Inter,sans-serif">{label}</text>'
            )

    # Legend (for multi-series)
    if len(series) > 1:
        leg_y = height - 6
        leg_x = pad_left
        for si, s in enumerate(series):
            color = s.get("color") or COLORS[si % len(COLORS)]
            label = s.get("label", f"Series {si+1}")
            elements.append(
                f'<line x1="{leg_x}" y1="{leg_y - 3}" x2="{leg_x + 16}" y2="{leg_y - 3}" '
                f'stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
            )
            elements.append(
                f'<text x="{leg_x + 20}" y="{leg_y}" font-size="10" fill="{LABEL_COLOR}" '
                f'font-family="Inter,sans-serif">{html_mod.escape(label)}</text>'
            )
            leg_x += len(label) * 7 + 36

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
    """
    Render a side-by-side metric comparison table.

    tokens: list of {"name", "ticker", "slug", "metrics": {key: {"latest", "avg_30d", ...}}}
    metric_keys: list of (key, label) pairs
    """
    if not tokens:
        return '<p>No tokens selected for comparison.</p>'

    # Header row
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
