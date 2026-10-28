#!/usr/bin/env python3
"""Shareable workbook: our DFS projections vs the outside sources, one week.

Reads data/projections_<year>_wk<NN>.csv (run project.py --live first) and the
per-source files archived under ff_weekly_proj/weekly/<year>-wk<NN>/, scoring
each source with ff_weekly_proj/scoring.py so every number uses one formula.

Columns: DFS Proj, Consensus, the LOWEST and HIGHEST single-source projection,
how many sources projected the player, Diff (a live formula), then our full
projected stat line. Our DFS number is highlighted when it falls outside the
min-max range of every source -- the disagreements worth a second look.

Usage:
    python build_comparison_xlsx.py --year 2026 --week 3
"""

import argparse
import csv
import datetime
import os
import sys

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_vs_sources as A  # noqa: E402

QB_COLS = [("Pass Att", "pass_att", "0.0"), ("Pass Cmp", "pass_cmp", "0.0"),
           ("Pass Yds", "pass_yds", "0.0"), ("Pass TD", "pass_td", "0.00"),
           ("INT", "pass_int", "0.00"), ("Rush Att", "rush_att", "0.0"),
           ("Rush Yds", "rush_yds", "0.0"), ("Rush TD", "rush_td", "0.00")]
SK_COLS = [("Targets", "targets", "0.0"), ("Rec", "rec", "0.0"),
           ("Rec Yds", "rec_yds", "0.0"), ("Rec TD", "rec_td", "0.00"),
           ("Rush Att", "rush_att", "0.0"), ("Rush Yds", "rush_yds", "0.0"),
           ("Rush TD", "rush_td", "0.00")]
ALL_COLS = QB_COLS[:5] + SK_COLS[:4] + SK_COLS[4:]

HF = Font(name="Arial", bold=True, color="FFFFFF")
BF, BB = Font(name="Arial"), Font(name="Arial", bold=True)
HFILL = PatternFill("solid", fgColor="1F3864")
KFILL = PatternFill("solid", fgColor="DDEBF7")
OUT_FILL = PatternFill("solid", fgColor="F4B084")
LINE = Border(bottom=Side(style="thin", color="BFBFBF"))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def source_ranges(year, week):
    """normalised name -> (min, max, n sources), plus the directory used."""
    directory, label = A.resolve_dir(year, week)
    per = {}
    used = []
    for name in A.SOURCES:
        pts = A.load_source(directory, name)
        if pts:
            used.append(name)
        for k, (p, _pos, _tm) in pts.items():
            per.setdefault(k, []).append(p)
    # rounded like the consensus column, so the three always line up
    return ({k: (round(min(v), 2), round(max(v), 2), len(v)) for k, v in per.items()},
            label, used)


def load_etr(year, week):
    """Establish the Run half-PPR points, if their file was archived for the week."""
    directory, _ = A.resolve_dir(year, week)
    path = os.path.join(directory, "etr.csv")
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("Pos") in ("QB", "RB", "WR", "TE"):
                    out[A.norm(r["Player"])] = num(r.get("Half PPR Proj"))
    return out


TEST_LABELS = {"noqbtd": "Old (no QB-TD)", "epa": "EPA Matchup Test"}


def load_tests(year, week):
    """label -> {player_id: points} for every test version that was run."""
    out = {}
    for name, label in TEST_LABELS.items():
        v = load_test(year, week, name)
        if v:
            out[label] = v
    return out


def load_test(year, week, name="qbtd"):
    """Our TEST version's points (project.py --version NAME), if it was run."""
    path = os.path.join(HERE, "data", f"projections_{year}_wk{week:02d}_{name}.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["player_id"]: num(r["half_ppr"]) for r in csv.DictReader(fh)}


def write_sheet(wb, title, data, cols, ranges, etr=None, test=None):
    ws = wb.create_sheet(title)
    test = test or {}
    extra = list(test)
    head = ["Player", "Pos", "Team", "DFS Proj", "Consensus", "Source Min",
            "Source Max", "# Sources", "Diff (DFS − Cons)", "ETR"] + extra + [c[0] for c in cols]
    ws.append(head)
    for c in range(1, len(head) + 1):
        cell = ws.cell(1, c)
        cell.font, cell.fill = HF, HFILL
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
    for i, r in enumerate(data, start=2):
        lo, hi, n = ranges.get(A.norm(r["player"]), (None, None, None))
        vals = [r["player"], r["pos"], r["team"], num(r.get("dfs") or r["half_ppr"]),
                num(r["consensus"]), lo, hi, n,
                f'=IF(E{i}="","",D{i}-E{i})', (etr or {}).get(A.norm(r["player"]))]
        for lab in extra:
            vals.append(test[lab].get(r["player_id"]))
        for c, v in enumerate(vals, start=1):
            ws.cell(i, c, v)
        for j, (_, key, fmt) in enumerate(cols, start=len(vals) + 1):
            ws.cell(i, j, num(r.get(key))).number_format = fmt
        for c in range(1, len(head) + 1):
            ws.cell(i, c).font = BB if c == 4 else BF
            ws.cell(i, c).border = LINE
        for c in (4, 5, 6, 7, 9, 10) + tuple(range(11, 11 + len(extra))):
            ws.cell(i, c).number_format = "0.0;-0.0;0.0"
        ws.cell(i, 8).number_format = "0"
        ws.cell(i, 4).fill = KFILL
    last = len(data) + 1
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{last}"
    ws.row_dimensions[1].height = 32
    for c, w in enumerate([24, 6, 6, 10, 11, 10, 10, 9, 12, 8] + [10] * len(extra)
                          + [9] * len(cols),
                          start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.conditional_formatting.add(f"I2:I{last}", ColorScaleRule(
        start_type="num", start_value=-5, start_color="F8696B",
        mid_type="num", mid_value=0, mid_color="FFFFFF",
        end_type="num", end_value=5, end_color="63BE7B"))
    # our number outside the range of EVERY source
    ws.conditional_formatting.add(f"D2:D{last}", FormulaRule(
        formula=['AND(ISNUMBER($F2),OR($D2<$F2,$D2>$G2))'], fill=OUT_FILL))


def write_rb_check(wb, rows, ranges):
    """RBs we project ABOVE every source -- a pre-lock checklist, not an input.

    Weeks 2-3 2026: on 41 such backs the market was closer 31 times, mostly
    backups and committee backs whose role shrank that week. Our carry shares
    are right on average; which individual back gets the work is where we miss.
    """
    ws = wb.create_sheet("RB Check", 1)
    ws.append(["RBs we project ABOVE every source -- check the news / depth chart "
               "before lock. In weeks 2-3 the market was right on 31 of 41 of these."])
    ws.cell(1, 1).font = BB
    ws.append([])
    head = ["Player", "Team", "DFS Proj", "Source Max", "Above Max", "Consensus",
            "Our Carries", "Our Targets", "Your Note"]
    ws.append(head)
    for c in range(1, len(head) + 1):
        cell = ws.cell(3, c)
        cell.font, cell.fill = HF, HFILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    flagged = []
    for r in rows:
        if r["pos"] != "RB":
            continue
        rng = ranges.get(A.norm(r["player"]))
        dfs = num(r.get("dfs") or r["half_ppr"])
        if rng and dfs is not None and dfs > rng[1]:
            flagged.append((dfs - rng[1], r, rng, dfs))
    flagged.sort(key=lambda t: -t[0])
    for i, (gap, r, rng, dfs) in enumerate(flagged, start=4):
        vals = [r["player"], r["team"], dfs, rng[1], gap, num(r["consensus"]),
                num(r.get("rush_att")), num(r.get("targets")), None]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(i, c, v)
            cell.font, cell.border = BF, LINE
            if c in (3, 4, 5, 6, 7, 8):
                cell.number_format = "0.0"
        ws.cell(i, 3).fill = OUT_FILL
    for c, w in enumerate([24, 6, 10, 11, 10, 11, 11, 11, 40], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A4"
    return len(flagged)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()

    src = os.path.join(HERE, "data",
                       f"projections_{args.year}_wk{args.week:02d}.csv")
    with open(src, newline="", encoding="utf-8") as fh:
        rows = sorted(csv.DictReader(fh), key=lambda r: -float(r.get("dfs") or r["half_ppr"]))
    ranges, label, used = source_ranges(args.year, args.week)
    etr = load_etr(args.year, args.week)
    test = load_tests(args.year, args.week)

    wb = Workbook()
    wb.remove(wb.active)
    write_sheet(wb, "All", rows, ALL_COLS, ranges, etr, test)
    for p in ("QB", "RB", "WR", "TE"):
        write_sheet(wb, p, [r for r in rows if r["pos"] == p],
                    QB_COLS if p == "QB" else SK_COLS, ranges, etr, test)

    n_rb = write_rb_check(wb, rows, ranges)

    ws = wb.create_sheet("Notes")
    notes = [
        (f"F6P Weekly Projections — Week {args.week}, {args.year} — DFS vs Consensus", True),
        ("", False),
        ("What's in here", True),
        ("DFS Proj — our DFS model: team volume from pace, pass rate and the Vegas "
         "line; each player's share of it (recency-weighted to this season); his "
         "own efficiency shrunk toward the position average by how many touches "
         "back it up; touchdowns split from the team's Vegas implied total, with "
         "proven goal-line runners (QB and RB) given their own rushing-TD rate.", False),
        (f"Consensus — average of the outside sources ({', '.join(used)}) that "
         f"actually projected the player, read from {label}. A source listing a "
         f"player at exactly 0 points is treated as not projecting him: ESPN and "
         f"FantasyData publish hundreds of 0-point placeholder rows, starters "
         f"included, and counting them as real would drag the average down "
         f"(Purdy would read 17.3 instead of 19.8). Benchmark only — never an "
         f"input to our numbers.", False),
        ("Source Min / Source Max — the lowest and highest projection any single "
         "source gave the player, scored with the same formula as ours. "
         "# Sources — how many of them projected him at all.", False),
        ("Orange DFS Proj — our number sits outside the range of every source. "
         "Those are the disagreements worth a second look: sometimes a bug on our "
         "side, sometimes information the market hasn't priced.", False),
        ("Diff — DFS Proj minus Consensus. Green = we're higher, red = lower. "
         "Blank = no consensus projection for that player.", False),
        ("ETR — Establish the Run's half-PPR projection, shown for comparison "
         "only. Not part of the consensus, min or max.", False),
        ("RB Check tab — every running back we project above EVERY outside "
         "source. A checklist for the news and depth chart before lock, never "
         "an input to our numbers: in weeks 2-3 the market was closer on 31 of "
         "41 of these, mostly backups whose role shrank that week.", False),
("Old (no QB-TD) — the main model as it was before 6 Oct 2026, kept as a "
         "test: the current model now lets an elite passer's own touchdown "
         "rate lift his team's passing TDs (it won weeks 3 and 4 live).", False),
        ("EPA Matchup Test — a TEST version with defensive matchups: each "
         "defense's EPA allowed on targets to RBs / WRs / TEs, RB runs and QB "
         "dropbacks, net of the offenses it faced, seeded by last season. It "
         "moves yards, catches and TDs per opportunity; touchdowns only shift "
         "between positions, so each team still scores its Vegas total.", False),
        ("Stat columns — our projected stat line; DFS Proj is computed from "
         "exactly these numbers.", False),
        ("", False),
        ("Scoring", True),
        ("RB/WR/TE: half-PPR (0.5 per reception, 0.1 per rush/rec yard, 6 per TD). "
         "QB: 0.04 per pass yard, 4 per pass TD, −2 per INT, 0.1 per rush yard, "
         "6 per rush TD.", False),
        ("Fumbles ARE projected: every player loses the league fumble rate per "
         "touch (about 0.4 pts for a busy QB like Allen), the same way the "
         "sources subtract them, so the totals compare like for like.", False),
        ("", False),
        ("Caveats", True),
        ("Availability comes from the official injury report where it exists, "
         "Sleeper's injury tags, roster status, the current depth chart, and our "
         "own review of Questionable players. Early in the week the official "
         "report is empty, so re-run after Wednesday's report before relying "
         "on it.", False),
        ("How accurate: on a walk-forward backtest of the 2025 season the DFS "
         "model beat 'project every player at his season average' by 9.4% overall "
         "(QB 18.2%, RB 6.8%, WR 7.7%, TE 6.6%). Weekly projections are noisy — "
         "treat these as expected values, not predictions.", False),
        ("", False),
        (f"Built {datetime.datetime.now():%Y-%m-%d %H:%M}", False),
    ]
    for i, (text, bold) in enumerate(notes, start=1):
        c = ws.cell(i, 1, text)
        c.font = Font(name="Arial", bold=bold, size=13 if i == 1 else 11)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 120

    # No LibreOffice here to pre-compute formulas, so Excel/Sheets do it on open.
    wb.calculation.fullCalcOnLoad = True
    out = os.path.join(HERE, f"F6P Week {args.week} Projections vs Consensus.xlsx")
    wb.save(out)
    matched = sum(1 for r in rows if A.norm(r["player"]) in ranges)
    outside = sum(1 for r in rows if A.norm(r["player"]) in ranges and not
                  (ranges[A.norm(r["player"])][0] <= float(r.get("dfs") or r["half_ppr"])
                   <= ranges[A.norm(r["player"])][1]))
    print(f"  {len(rows)} players, {matched} with source ranges "
          f"({len(used)} sources, {label})")
    print(f"  {outside} DFS projections fall outside every source's range; "
          f"{n_rb} RBs above every source (RB Check tab)")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
