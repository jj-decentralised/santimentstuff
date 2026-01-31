"""
Export all available Santiment data to a comprehensive XLSX for analysis.
Pulls from the live Railway API — requires the deployed server to be running.
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter

BASE = "https://santimentstuff-production-2305.up.railway.app"
TIMEOUT = 60


def api_get(path, retries=3):
    """GET request with retry logic."""
    url = f"{BASE}{path}"
    for attempt in range(retries):
        try:
            resp = urllib.request.urlopen(url, timeout=TIMEOUT)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 422:
                print(f"  422 on {path}, skipping")
                return None
            if e.code == 404:
                print(f"  404 on {path}, skipping")
                return None
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  HTTP {e.code} on {path}, retry in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  FAILED: {path} — {e}")
                return None
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  Error on {path}: {e}, retry in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  FAILED: {path} — {e}")
                return None


def style_header(ws, row=1):
    """Apply Bloomberg-style header formatting."""
    hdr_font = Font(name="Calibri", bold=True, size=10, color="FFFFFF")
    hdr_fill = PatternFill(start_color="0D1117", end_color="0D1117", fill_type="solid")
    hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        bottom=Side(style="thin", color="30363D"),
        right=Side(style="thin", color="30363D"),
    )
    for cell in ws[row]:
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = hdr_align
        cell.border = thin_border


def auto_width(ws, min_w=8, max_w=30):
    """Auto-fit column widths."""
    for col_idx, col_cells in enumerate(ws.columns, 1):
        max_len = 0
        for cell in col_cells:
            val = str(cell.value) if cell.value is not None else ""
            max_len = max(max_len, len(val))
        w = min(max(max_len + 2, min_w), max_w)
        ws.column_dimensions[get_column_letter(col_idx)].width = w


def main():
    wb = Workbook()
    wb.remove(wb.active)

    print("=" * 60)
    print("Onchain Pulse — Full Data Export to XLSX")
    print("=" * 60)

    # ── 1. Market Overview (all tokens with latest metrics) ──
    print("\n[1/7] Pulling market overview (all tokens)...")
    all_tokens = []
    page = 1
    while True:
        data = api_get(f"/api/v1/market?page={page}&per_page=200")
        if not data or not data.get("tokens"):
            break
        all_tokens.extend(data["tokens"])
        total = data.get("total", 0)
        print(f"  Page {page}: got {len(data['tokens'])} tokens (total so far: {len(all_tokens)}/{total})")
        if len(all_tokens) >= total or page >= 50:
            break
        page += 1
        time.sleep(0.3)

    if all_tokens:
        ws = wb.create_sheet("Market Overview")
        headers = [
            "Rank", "Name", "Ticker", "Slug", "Sector", "Category",
            "Price (USD)", "24h Change %", "Market Cap (USD)",
            "MCap Change %", "Volume 24h (USD)", "Vol Change %",
        ]
        ws.append(headers)
        style_header(ws)

        for i, t in enumerate(all_tokens, 1):
            ws.append([
                i,
                t.get("name", ""),
                t.get("ticker", ""),
                t.get("slug", ""),
                t.get("sector", ""),
                t.get("category", ""),
                t.get("price_usd"),
                t.get("price_usd_change"),
                t.get("marketcap_usd"),
                t.get("marketcap_usd_change"),
                t.get("volume_usd"),
                t.get("volume_usd_change"),
            ])

        # Format number columns
        for row in ws.iter_rows(min_row=2, min_col=7, max_col=12):
            for cell in row:
                if cell.value is not None:
                    cell.number_format = '#,##0.00' if cell.column in (7,) else '#,##0'

        auto_width(ws)
        print(f"  ✓ Market Overview: {len(all_tokens)} tokens")
    else:
        print("  ✗ No market data available")

    # ── 2. Determine top tokens for historical data ──
    # Pull profiles for top tokens by market cap
    top_slugs = [t["slug"] for t in all_tokens[:80] if t.get("slug")]
    print(f"\n  Selected {len(top_slugs)} top tokens for historical data")

    # ── 3. Historical timeseries for key metrics ──
    METRICS_TO_PULL = [
        ("price_usd", "Price History"),
        ("marketcap_usd", "Market Cap History"),
        ("volume_usd", "Volume History"),
        ("mvrv_usd", "MVRV History"),
        ("daily_active_addresses", "Active Addresses"),
        ("dev_activity", "Dev Activity"),
        ("exchange_balance", "Exchange Balance"),
        ("nvt", "NVT Ratio"),
        ("network_growth", "Network Growth"),
        ("transaction_volume", "Transaction Volume"),
    ]

    for metric_idx, (metric, sheet_name) in enumerate(METRICS_TO_PULL):
        print(f"\n[{metric_idx + 2}/7] Pulling {sheet_name} ({metric})...")
        ws = wb.create_sheet(sheet_name)

        # Collect all timeseries data for this metric across tokens
        all_dates = set()
        token_data = {}  # slug -> {date: value}

        tokens_for_metric = top_slugs[:50] if metric in ("price_usd", "marketcap_usd", "volume_usd") else top_slugs[:30]

        for idx, slug in enumerate(tokens_for_metric):
            data = api_get(f"/api/v1/metric/{metric}?slug={slug}")
            if not data or not data.get("data"):
                continue

            ts = {}
            for d in data["data"]:
                dt = d.get("datetime", "")[:10]  # YYYY-MM-DD
                val = d.get("value")
                if dt and val is not None:
                    ts[dt] = val
                    all_dates.add(dt)

            if ts:
                token_data[slug] = ts

            if (idx + 1) % 10 == 0:
                print(f"  {idx + 1}/{len(tokens_for_metric)} tokens pulled...")
            time.sleep(0.15)

        if not token_data:
            print(f"  ✗ No data for {metric}")
            continue

        # Sort dates
        sorted_dates = sorted(all_dates)
        slugs_with_data = list(token_data.keys())

        # Get token names for headers
        slug_to_name = {t["slug"]: f"{t.get('name', t['slug'])} ({t.get('ticker', '')})" for t in all_tokens}

        # Write headers
        header_row = ["Date"] + [slug_to_name.get(s, s) for s in slugs_with_data]
        ws.append(header_row)
        style_header(ws)

        # Write data rows
        for dt in sorted_dates:
            row = [dt]
            for slug in slugs_with_data:
                row.append(token_data[slug].get(dt))
            ws.append(row)

        auto_width(ws, max_w=20)
        print(f"  ✓ {sheet_name}: {len(sorted_dates)} dates × {len(slugs_with_data)} tokens")

    # ── 4. Briefing summary ──
    print("\n[7/7] Pulling economy briefing...")
    briefing = api_get("/api/v1/briefing")
    if briefing:
        ws = wb.create_sheet("Economy Briefing")
        ws.append(["Metric", "Value"])
        style_header(ws)

        summary_rows = [
            ("Total Tokens", briefing.get("total_tokens")),
            ("Total Market Cap (USD)", briefing.get("total_mcap")),
            ("Total Volume (USD)", briefing.get("total_volume")),
            ("Average MVRV", briefing.get("avg_mvrv")),
            ("Breadth % Positive", briefing.get("breadth_pct")),
            ("Tokens Up", briefing.get("breadth", {}).get("up")),
            ("Tokens Down", briefing.get("breadth", {}).get("down")),
            ("Vol Concentration Top 10 %", briefing.get("vol_concentration_top10")),
            ("Tokens Accumulating", briefing.get("accumulating")),
            ("Tokens Distributing", briefing.get("distributing")),
            ("Total DAA", briefing.get("total_daa")),
            ("Total Dev Activity", briefing.get("total_dev")),
            ("Signals Count", briefing.get("signals_count")),
        ]
        for label, val in summary_rows:
            ws.append([label, val])

        # MVRV Zones
        ws.append([])
        ws.append(["MVRV Zone", "Count"])
        zones = briefing.get("mvrv_zones", {})
        for zone_name, count in zones.items():
            ws.append([zone_name.replace("_", " ").title(), count])

        auto_width(ws)
        print(f"  ✓ Economy Briefing")

    # ── 5. Sectors breakdown ──
    print("\n  Pulling sectors...")
    sectors = api_get("/api/v1/sectors")
    if sectors and sectors.get("sectors"):
        ws = wb.create_sheet("Sectors")
        ws.append(["Sector", "Label", "Token Count", "Market Cap (USD)", "Volume (USD)", "Up", "Down"])
        style_header(ws)

        for key, data in sorted(sectors["sectors"].items(), key=lambda x: x[1].get("mcap", 0), reverse=True):
            ws.append([
                key,
                data.get("label", key),
                data.get("count", 0),
                data.get("mcap", 0),
                data.get("vol", 0),
                data.get("up", 0),
                data.get("down", 0),
            ])

        auto_width(ws)
        print(f"  ✓ Sectors: {len(sectors['sectors'])} sectors")

    # ── 6. Valuation data for top tokens ──
    print("\n  Pulling valuation summaries (top 30)...")
    ws = wb.create_sheet("Valuations")
    ws.append(["Name", "Ticker", "Slug", "Sector",
               "MVRV Current", "MVRV 90d Avg", "MVRV 365d Avg", "MVRV 365d Min", "MVRV 365d Max",
               "NVT Current", "NVT 90d Avg", "NVT 365d Avg",
               "Price Current", "MCap Current"])
    style_header(ws)

    for idx, slug in enumerate(top_slugs[:30]):
        val = api_get(f"/api/v1/valuation/{slug}")
        if not val or not val.get("valuation"):
            continue

        v = val["valuation"]
        token_name = slug_to_name.get(slug, slug) if 'slug_to_name' in dir() else slug
        # Find from all_tokens
        tinfo = next((t for t in all_tokens if t.get("slug") == slug), {})

        ws.append([
            tinfo.get("name", slug),
            tinfo.get("ticker", ""),
            slug,
            tinfo.get("sector", ""),
            v.get("mvrv_usd", {}).get("current"),
            v.get("mvrv_usd", {}).get("avg_90d"),
            v.get("mvrv_usd", {}).get("avg_365d"),
            v.get("mvrv_usd", {}).get("min_365d"),
            v.get("mvrv_usd", {}).get("max_365d"),
            v.get("nvt", {}).get("current"),
            v.get("nvt", {}).get("avg_90d"),
            v.get("nvt", {}).get("avg_365d"),
            v.get("price_usd", {}).get("current"),
            v.get("marketcap_usd", {}).get("current"),
        ])

        if (idx + 1) % 10 == 0:
            print(f"  {idx + 1}/30 valuations pulled...")
        time.sleep(0.15)

    auto_width(ws)
    print(f"  ✓ Valuations sheet")

    # ── Save ──
    output = "/home/user/santimentstuff/onchain_pulse_data_export.xlsx"
    wb.save(output)
    import os
    size_mb = os.path.getsize(output) / 1e6
    print(f"\n{'=' * 60}")
    print(f"DONE — Saved to: {output}")
    print(f"File size: {size_mb:.1f} MB")
    print(f"Sheets: {wb.sheetnames}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
