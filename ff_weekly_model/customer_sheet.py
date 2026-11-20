#!/usr/bin/env python3
"""The week's projections as a workbook to share with customers.

    python customer_sheet.py --year 2026 --week 11

Joe 2026-11-20: "can I also get a projection spreadsheet created that I would be able to share with
customers? I think I would want it to mimic this setup" (a Google Sheet with tabs LIVE PROJECTIONS QB / RB /
WR / TE). Writes customer_sheets/F6P Week <N> Projections.xlsx from
data/projections_<yr>_wk<NN>.csv (the run with Joe's calls). Only the stat lines and points go out:
no consensus, no diff, no model internals. rerun.py and lock.py call it at the end of every run.
No Update Date tab (Joe 2026-11-20). Not pushed to the Google Sheet yet -- Joe is still testing.
"""
import argparse
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "customer_sheets")
MIN_PTS = 0.5          # players projected under this (half PPR) are left off

f = lambda v: float(v or 0)

# (header, key or function, decimals)
PASS = [("Pass Att", "pass_att", 1), ("Pass Comp", "pass_cmp", 1), ("Pass Yds", "pass_yds", 1),
        ("Pass TD", "pass_td", 2), ("Pass Int", "pass_int", 2)]
RUSH = [("Rush Att", "rush_att", 1), ("Rush Yds", "rush_yds", 1), ("Rush TD", "rush_td", 2)]
REC = [("Targets", "targets", 1), ("Rec", "rec", 1), ("Rec Yds", "rec_yds", 1), ("Rec TD", "rec_td", 2)]
FUM = [("Fumbles", "fum", 2)]
HALF = ("Fantasy Points (Half-PPR)", lambda r: f(r["half_ppr"]), 2)
PPR = ("Fantasy Points (PPR)", lambda r: f(r["half_ppr"]) + 0.5 * f(r["rec"]), 2)
STD = ("Fantasy Points (STD)", lambda r: f(r["half_ppr"]) - 0.5 * f(r["rec"]), 2)
TEP = ("TE Premium (PPR + 0.5)", lambda r: f(r["half_ppr"]) + f(r["rec"]), 2)
TABS = [("QB", "QB", PASS + RUSH + FUM + [("Fantasy Points", lambda r: f(r["half_ppr"]), 2)]),
        ("RB", "RB", RUSH + REC + FUM + [HALF, PPR, STD]),
        ("WR", "WR", REC + RUSH + FUM + [HALF, PPR, STD]),
        ("TE", "TE", REC + RUSH + FUM + [HALF, PPR, TEP])]


def opponents(year, week):
    out = {}
    for r in csv.DictReader(open(os.path.join(DATA, "games.csv"), encoding="utf-8")):
        if r["season"] == str(year) and r["week"] == str(week) and r["game_type"] == "REG":
            out[r["away_team"]] = "@" + r["home_team"]
            out[r["home_team"]] = r["away_team"]
    return out


def build(year, week):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    rows = list(csv.DictReader(open(os.path.join(DATA, f"projections_{year}_wk{week:02d}.csv"), encoding="utf-8")))
    opp = opponents(year, week)
    wb = Workbook()
    wb.remove(wb.active)
    HDR_FILL, HDR_FONT = PatternFill("solid", fgColor="1F3864"), Font(name="Arial", size=10, bold=True, color="FFFFFF")
    BAND = PatternFill("solid", fgColor="EEF2F8")
    BODY, BOLD = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
    n_total = 0
    for tab, pos, cols in TABS:
        ws = wb.create_sheet(f"LIVE PROJECTIONS {tab}")
        hdr = [pos, "Team", "Opp"] + [c[0] for c in cols]
        for j, h in enumerate(hdr, 1):
            c = ws.cell(1, j, h)
            c.fill, c.font = HDR_FILL, HDR_FONT
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30
        recs = [r for r in rows if r["pos"] == pos and f(r["half_ppr"]) >= MIN_PTS]
        recs.sort(key=lambda r: (-f(r["half_ppr"]), r["player"]))
        for i, r in enumerate(recs, 2):
            vals = [r["player"], r["team"], opp.get(r["team"], "")]
            for _, k, nd in cols:
                x = k(r) if callable(k) else f(r.get(k))
                vals.append(round(x, nd))
            for j, x in enumerate(vals, 1):
                c = ws.cell(i, j, x)
                c.font = BOLD if j == 1 or hdr[j - 1] in ("Fantasy Points", HALF[0]) else BODY
                if j > 3:
                    c.number_format = "0.00"
                    c.alignment = Alignment(horizontal="center")
                else:
                    c.alignment = Alignment(horizontal="left" if j == 1 else "center")
                if i % 2 == 1:
                    c.fill = BAND
        n_total += len(recs)
        ws.column_dimensions["A"].width = 24
        ws.column_dimensions["B"].width = 7
        ws.column_dimensions["C"].width = 7
        for j in range(4, len(hdr) + 1):
            ws.column_dimensions[get_column_letter(j)].width = 13 if hdr[j - 1].startswith(("Fantasy", "TE Prem")) else 9
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(hdr))}{max(2, len(recs) + 1)}"
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"F6P Week {week} Projections.xlsx")
    try:
        wb.save(dest)
    except PermissionError:
        print(f"  {os.path.basename(dest)} is open in Excel -- not updated (close it and rerun)")
        return None
    print(f"  customer sheet: {n_total} players -> {dest}")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    a = ap.parse_args()
    build(a.year, a.week)
