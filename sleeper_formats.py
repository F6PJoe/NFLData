"""
sleeper_formats.py
------------------
Fetch Sleeper ADP in all four scoring formats and write to Excel.

Output: sleeper_adp_formats.xlsx  (same folder as this script)
  - One sheet per format: Standard, Half-PPR, PPR, 2QB
  - Each sheet sorted by that format's ADP (999 = unranked, pushed to bottom)
  - Filters to QB / RB / WR / TE only

Run from anywhere:
    python sleeper_formats.py
    python sleeper_formats.py --season 2026
    python sleeper_formats.py --out my_file.xlsx

Does NOT affect GitHub, Google Sheets, or any other pipeline.
Requires: requests, openpyxl  (both already installed in your Python env)
"""

import argparse
import requests
from datetime import datetime
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

API_URL = "https://api.sleeper.app/projections/nfl/{season}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

KEEP_POS = {"QB", "RB", "WR", "TE"}

# ADP field name → display label
FORMATS = [
    ("adp_std",      "Standard"),
    ("adp_half_ppr", "Half-PPR"),
    ("adp_ppr",      "PPR"),
    ("adp_2qb",      "2QB-Superflex"),
]

# Header row background colours (one per sheet)
SHEET_COLOURS = ["4472C4", "ED7D31", "70AD47", "7030A0"]  # blue, orange, green, purple


def fetch(season: str):
    r = requests.get(API_URL.format(season=season),
                     params={"season_type": "regular", "order_by": "adp_ppr"},
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def build_rows(data):
    """Return list of dicts with all four ADP fields for every kept player."""
    rows = []
    for entry in data:
        player = entry.get("player") or {}
        pos = (player.get("position") or "").strip().upper()
        if pos not in KEEP_POS:
            continue

        stats = entry.get("stats") or {}
        first = (player.get("first_name") or "").strip()
        last  = (player.get("last_name")  or "").strip()
        name  = f"{first} {last}".strip()
        team  = (player.get("team") or "").strip()

        row = {"Player": name, "Position": pos, "Team": team}
        for field, _ in FORMATS:
            try:
                val = float(stats.get(field) or 999)
            except (TypeError, ValueError):
                val = 999.0
            row[field] = val if val < 999 else 999.0

        rows.append(row)
    return rows


def write_sheet(wb, title: str, adp_field: str, rows: list, hex_colour: str):
    ws = wb.create_sheet(title=title)

    # Header style
    hdr_fill = PatternFill("solid", fgColor=hex_colour)
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_align = Alignment(horizontal="center")

    headers = ["Player", "Position", "Team", "ADP"]
    col_widths = [28, 10, 8, 8]

    for col_idx, (hdr, width) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=hdr)
        cell.fill   = hdr_fill
        cell.font   = hdr_font
        cell.alignment = hdr_align
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A2"

    # Sort: ranked players first (by ADP), then 999s at bottom
    sorted_rows = sorted(rows, key=lambda r: (r[adp_field] >= 999, r[adp_field]))

    for row_idx, r in enumerate(sorted_rows, start=2):
        adp = r[adp_field]
        ws.cell(row=row_idx, column=1, value=r["Player"])
        ws.cell(row=row_idx, column=2, value=r["Position"])
        ws.cell(row=row_idx, column=3, value=r["Team"])
        adp_cell = ws.cell(row=row_idx, column=4,
                           value=round(adp, 1) if adp < 999 else "—")
        adp_cell.alignment = Alignment(horizontal="center")

        # Zebra stripe
        if row_idx % 2 == 0:
            fill = PatternFill("solid", fgColor="F2F2F2")
            for c in range(1, 5):
                ws.cell(row=row_idx, column=c).fill = fill


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=str(datetime.now().year))
    ap.add_argument("--out", default=str(Path(__file__).parent / "sleeper_adp_formats.xlsx"))
    args = ap.parse_args()

    print(f"Fetching Sleeper ADP for {args.season}...")
    data = fetch(args.season)
    rows = build_rows(data)
    print(f"  {len(rows)} players across QB/RB/WR/TE")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)   # remove default blank sheet

    for (field, label), colour in zip(FORMATS, SHEET_COLOURS):
        ranked = sum(1 for r in rows if r[field] < 999)
        print(f"  {label}: {ranked} players ranked")
        write_sheet(wb, label, field, rows, colour)

    wb.save(args.out)
    print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
