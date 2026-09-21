#!/usr/bin/env python3
"""Build my_projections_v2.xlsx - DIRECT ENTRY workbook.

Difference from v1
------------------
v1 had you enter percentages and derived every counting stat from a team
control total, so nothing could ever exceed the team. The cost was that yards
per carry was an OUTPUT you could only nudge through a multiplier, and 604
players with no efficiency history all showed the identical team-average rate.

v2 inverts it. You type the actual numbers - attempts, yards, touchdowns - and
the workbook computes the rates and shares as CHECKS:

    you type      Rush Att, Rush Yds, Rush TD, Targets, Rec, Rec Yds, Rec TD
    it computes   Yds/Car, Yds/Rec, Catch %, Rush %, Tgt %, per-game rates
    it flags      any column whose sum exceeds the team total, in red

Nothing is auto-reconciled. The footer shows the team total, your running sum,
and what's left to allocate - so an overrun is loud instead of silently
absorbed. That is the trade: full control over every rate, in exchange for
balancing the columns yourself.

v1 is untouched at my_projections.xlsx.

Merge protection
-----------------
Once you've opened and saved this file in Excel, running this script again
WILL DISCARD your typed numbers unless you say otherwise - it refuses outright
in that case. Your options:

    python build_workbook_v2.py --merge    # keep your edits, refresh the rest
    python build_workbook_v2.py --force    # discard them (old file still backed up)

--merge restores every typed cell by (player, team). A player who changed
teams necessarily loses his old numbers - they were earned in a different
offense - and the merge report tells you exactly which teams that touches
so you know what to re-check instead of guessing.

Consensus is a ONE-TIME bootstrap, not a recurring default
------------------------------------------------------------
--seed consensus was used once to give the first build a realistic 2026
starting point instead of a stale last-season line. It is NOT the default -
an ordinary --merge never silently re-pulls it. Cells you've already typed
into always win regardless of --seed; the flag only affects rows nobody has
touched yet (new arrivals, un-seeded rookies).

Usage:
    python build_workbook_v2.py --merge                # normal day-to-day rebuild
    python build_workbook_v2.py --seed consensus --merge   # explicit re-bootstrap
    python build_workbook_v2.py --seed blank               # no seeds
"""

import argparse
import csv
import datetime
import os
import sys
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import names
from teams import TEAMS

HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = 2026
HIST = [SEASON - 3, SEASON - 2, SEASON - 1]
SLOTS = [("QB", 3), ("RB", 6), ("WR", 8), ("TE", 4)]

INPUT = PatternFill("solid", fgColor="DCE9F7")
CALC = PatternFill("solid", fgColor="F2F2F2")
REF = PatternFill("solid", fgColor="FFF6E5")
HDR = PatternFill("solid", fgColor="2F4F6F")
SUBHDR = PatternFill("solid", fgColor="8EA9C1")
# Conditional-formatting fills need an explicit 8-digit ARGB with a real alpha
# channel - a plain 6-digit hex (fine for a normal cell .fill) silently
# serializes with alpha=00 (fully transparent) when used inside a dxf, so the
# rule fires correctly but paints nothing visible. Confirmed by inspecting the
# saved XML: a bare "FFC7CE" came out as rgb="00FFC7CE".
GOOD = PatternFill("solid", fgColor="FFC6EFCE")
OVER = PatternFill("solid", fgColor="FFFFC7CE")
OTHER = PatternFill("solid", fgColor="EDEDED")

BOLD = Font(bold=True)
SMALL = Font(size=9, color="666666")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
PCT, NUM0, NUM1, NUM2 = "0.0%", "0", "0.0", "0.00"

# ── layout ──────────────────────────────────────────────────────────────────
R_TITLE, R_TOT_HDR, R_TOT_LBL, R_TOT_VAL = 1, 3, 4, 5
R_VAC, R_COACH, R_TBL_HDR, R_FIRST = 7, 8, 10, 11
R_LAST = R_FIRST + sum(n + 1 for _, n in SLOTS) - 1

IDENT = [("Pos", 5), ("Player", 23), ("Dep", 4), ("Age", 4), ("Status", 10)]

# Reference: what he actually did. Cream. Read-only.
REFS = [(f"'{str(HIST[0])[2:]} Car", 6), (f"'{str(HIST[1])[2:]} Car", 6),
        (f"'{str(HIST[2])[2:]} Car", 6), (f"'{str(HIST[2])[2:]} RuYd", 7),
        (f"'{str(HIST[0])[2:]} Tgt", 6), (f"'{str(HIST[1])[2:]} Tgt", 6),
        (f"'{str(HIST[2])[2:]} Tgt", 6), (f"'{str(HIST[2])[2:]} ReYd", 7),
        (f"'{str(HIST[2])[2:]} Tm", 5), (f"'{str(HIST[2])[2:]} G", 4),
        ("3y Y/C", 6), ("3y Y/R", 6), ("3y Ctch", 7), ("3y Comp%", 8),
        ("3y Y/A", 6)]

# What you type.
INPUTS = [("Games", 6), ("Pass Att", 8), ("Cmp", 6), ("Pass Yds", 8),
          ("Pass TD", 7), ("Int", 5), ("Rush Att", 8), ("Rush Yds", 8),
          ("Rush TD", 7), ("Targets", 8), ("Rec", 6), ("Rec Yds", 8),
          ("Rec TD", 7)]

# Computed checks.
CHECKS = [("Seed", 6), ("Y/C", 6), ("Y/R", 6), ("Catch%", 7), ("Y/A", 6),
          ("Comp%", 7), ("Rush %", 7), ("Tgt %", 7), ("Pass %", 7),
          ("Car/G", 6), ("Tgt/G", 6), ("dTgt", 6), ("dCar", 6),
          ("Half PPR", 9)]

COLS = IDENT + REFS + INPUTS + CHECKS
C = {n: i + 1 for i, (n, _) in enumerate(COLS)}
INPUT_NAMES = [n for n, _ in INPUTS]
REF_NAMES = [n for n, _ in REFS]

TOTALS = [("Games", NUM0), ("Plays/G", NUM1), ("Plays", NUM0),
          ("Pass Rate", PCT), ("Pass Att", NUM0), ("Targets", NUM0),
          ("Rush Att", NUM0), ("Pass Yds", NUM0), ("Pass TD", NUM1),
          ("Int", NUM1), ("Rush Yds", NUM0), ("Rush TD", NUM1)]
T = {n: i + 2 for i, (n, _) in enumerate(TOTALS)}

# Which player column is constrained by which team total.
CONSTRAINED = {"Pass Att": "Pass Att", "Pass Yds": "Pass Yds",
               "Pass TD": "Pass TD", "Int": "Int",
               "Rush Att": "Rush Att", "Rush Yds": "Rush Yds",
               "Rush TD": "Rush TD", "Targets": "Targets",
               "Rec Yds": "Pass Yds", "Rec TD": "Pass TD"}

L = get_column_letter


def f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def i(v, d=0):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return d


CONSENSUS = os.path.join(HERE, os.pardir, "ff_draft_proj")
CONSENSUS_POS_COL = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE"}
# consensus column -> our input column
CONSENSUS_MAP = {
    "Pass Att": "Pass Att", "Pass Comp": "Cmp", "Pass Yds": "Pass Yds",
    "Pass TD": "Pass TD", "Pass Int": "Int",
    "Rush Att": "Rush Att", "Rush Yds": "Rush Yds", "Rush TD": "Rush TD",
    "Targets": "Targets", "Rec": "Rec", "Rec Yds": "Rec Yds",
    "Rec TD": "Rec TD",
}


def load_consensus():
    """ff_draft_proj consensus stat lines, keyed by normalized name.

    NOTE: this is the one place the project reads consensus as an INPUT rather
    than a benchmark. It only ever lands in editable cells you are expected to
    overwrite, and the Seed column marks every row still carrying it - but be
    honest with yourself that untouched rows are the market's numbers, not
    yours. Use --seed last-season to keep the model fully independent.
    """
    out = {}
    for pos, col in CONSENSUS_POS_COL.items():
        path = os.path.join(CONSENSUS, f"consensus_{pos.lower()}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = row.get(col)
                if not name:
                    continue
                line = {}
                for src, dest in CONSENSUS_MAP.items():
                    v = row.get(src)
                    if v not in (None, ""):
                        line[dest] = i(v)
                if line:
                    out[names.normalize(name)] = line
    return out


def read_csv(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        sys.exit(f"Missing {name}. Run the earlier build steps first.")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


BAD = ("*/", "/*", "**", "//", "+*", "*+", "+/", "-/", "(*", "(/", "*)",
       "/)", "$None", "None", ",,")


def validate(wb):
    bad = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    why = next((p for p in BAD if p in v), None)
                    if why is None and v.count("(") != v.count(")"):
                        why = "unbalanced parens"
                    if why:
                        bad.append((ws.title, c.coordinate, why, v[:70]))
    if bad:
        print(f"\n{len(bad)} MALFORMED FORMULA(S) - refusing to save:\n")
        for s, coord, why, ff in bad[:8]:
            print(f"  {s}!{coord}  {why}\n      {ff}")
        sys.exit("\nNo file written.")


def _header_map(ws):
    """{column name: column index} as THIS SHEET actually has it right now.

    Never trust the current module's C dict to locate a column on a file that
    may have been built by an older version of this script. Every time a
    column gets added (like Comp% here), every column after it shifts right -
    reading an old file by the NEW module's fixed positions would silently
    grab the wrong cell instead of failing loudly. Reading each file's own
    header row makes column layout changes safe regardless of what order they
    happen in, not just the append-only case.
    """
    return {cell.value: cell.column for cell in ws[R_TBL_HDR] if cell.value}


def looks_edited(path):
    """True if Excel has opened and saved this workbook.

    openpyxl writes formulas but no cached results; Excel writes both. A
    populated cached value on a formula-only cell (Half PPR - never a typed
    input) means a human has been in here, same test as v1.
    """
    wb = None
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=True)
        for sheet in TEAMS[:6]:
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            col = _header_map(ws).get("Half PPR")
            if col is None:
                continue
            for row in ws.iter_rows(min_row=R_FIRST, max_row=R_LAST,
                                    min_col=col, max_col=col):
                for cell in row:
                    if isinstance(cell.value, (int, float)) and cell.value:
                        return True
    except Exception:
        return False
    finally:
        # read_only keeps the handle open; without this os.replace fails on
        # Windows with WinError 32.
        if wb is not None:
            wb.close()
    return False


def read_existing(path):
    """Pull hand-typed numbers out of an existing v2 workbook.

    Player rows are keyed by (normalized name, TEAM) - not name alone. A
    typed Rush Att was earned in THAT team's offense (its volume, its
    competing players); porting it unexamined to a new team would present a
    stale judgment as still valid. Same rule v1 uses for shares, applied here
    to raw counts for the same reason.

    Team-total edits are also captured, since the "Start Here" tab tells you
    those are meant to be edited directly.
    """
    from openpyxl import load_workbook
    wb = None
    players, teams = {}, {}
    try:
        wb = load_workbook(path, data_only=False)
        for team in TEAMS:
            if team not in wb.sheetnames:
                continue
            ws = wb[team]
            old_c = _header_map(ws)          # THIS file's own layout, not C
            player_col = old_c.get("Player")
            if player_col is None:
                continue                     # sheet doesn't look like a team tab
            tvals = {}
            for label, _ in TOTALS:
                v = ws.cell(R_TOT_VAL, T[label]).value
                if isinstance(v, (int, float)):
                    tvals[label] = v
            if tvals:
                teams[team] = tvals
            for row in range(R_FIRST, R_LAST + 1):
                name = ws.cell(row, player_col).value
                if not name or not isinstance(name, str):
                    continue
                if name.startswith("Other ") and name.endswith("s"):
                    continue          # residual bucket, not a real player
                edits = {}
                for col in INPUT_NAMES:
                    if col not in old_c:
                        continue      # this column didn't exist in the old file
                    v = ws.cell(row, old_c[col]).value
                    if isinstance(v, (int, float)):
                        edits[col] = v
                # Every row gets Games=17 written unconditionally, seeded or
                # not - so "Games present" alone isn't evidence of a real
                # typed number. Require at least one other stat, or a Games
                # value that actually differs from the default (someone
                # deliberately shortening a season for injury).
                real = {k: v for k, v in edits.items() if k != "Games"}
                if not real and edits.get("Games") == 17:
                    edits = {}
                if edits:
                    dep_col = old_c.get("Dep")
                    players[(names.normalize(name), team)] = {
                        "edits": edits, "display": name,
                        "depth": ws.cell(row, dep_col).value if dep_col else None}
    except Exception as exc:
        print(f"  could not read existing workbook ({exc}); building fresh")
        return {}, {}
    finally:
        if wb is not None:
            wb.close()
    return players, teams


def merge_report(prior_players, written):
    """What the merge kept, and what it necessarily could not.

    A team change isn't a merge failure - a typed Rush Att belongs to a
    specific offense, so it can't just follow a player to a new one. This says
    exactly what moved, what's gone, and who's new, so you know what to
    re-check instead of having to re-diff two workbooks by hand.
    """
    now = {(names.normalize(n), t): n for n, t in written}
    now_by_name = defaultdict(list)
    for (nm, team) in now:
        now_by_name[nm].append(team)

    kept, moved, gone, arrived = [], [], [], []
    for (nm, team), rec in prior_players.items():
        if (nm, team) in now:
            kept.append((nm, team))
        elif now_by_name.get(nm):
            moved.append((rec["display"], team, now_by_name[nm][0], rec["edits"]))
        else:
            gone.append((rec["display"], team, rec["edits"]))
    prior_keys = set(prior_players)
    for key, display_name in now.items():
        if key not in prior_keys and prior_players:
            arrived.append((display_name, key[1]))

    def headline(edits):
        bits = []
        for label in ("Targets", "Rush Att", "Pass Att"):
            if edits.get(label):
                bits.append(f"{i(edits[label])} {label.lower()}")
        return ", ".join(bits) or "0"

    print(f"\n{'=' * 70}")
    print("MERGE REPORT")
    print(f"{'=' * 70}")
    print(f"  kept {len(kept)} player edits")

    if moved:
        print(f"\n  CHANGED TEAMS ({len(moved)}) - typed numbers dropped, "
              f"they belonged to the old offense:")
        for name, old, new, edits in moved[:12]:
            print(f"    {name:<24} {old} -> {new}   had {headline(edits)} on {old}")
    if gone:
        print(f"\n  OFF EVERY ROSTER ({len(gone)}):")
        for name, old, edits in gone[:8]:
            print(f"    {name:<24} was {old}   had {headline(edits)}")
    if arrived:
        # Mostly players who never had consensus/history data to begin with
        # (deep rookies) - a count, not a name dump, since it's baseline
        # inventory rather than something that moved out from under you.
        print(f"\n  {len(arrived)} roster slots with no prior data at all "
              f"(rookies/no stat line) - unseeded before too, nothing lost.")
    if moved or gone:
        teams_touched = {old for _, old, *_ in moved} | {old for _, old, _ in gone}
        print(f"\n  Re-check these teams: {', '.join(sorted(teams_touched))}")
        print(f"  Every other team is untouched - your work there stands.")


def build_team_tab(ws, team, players, totals, hist, vac, coach, seed,
                   consensus=None, tally=None, prior_players=None,
                   prior_totals=None, written=None):
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = ws.cell(row=R_FIRST, column=3)
    ws.cell(R_TITLE, 1, f"{team}  -  {SEASON} projections  (direct entry)").font = \
        Font(bold=True, size=15, color="2F4F6F")

    # ── team control totals ────────────────────────────────────────────────
    ws.cell(R_TOT_HDR, 1, "TEAM TOTALS").font = BOLD
    ws.cell(R_TOT_HDR, 4, "all editable - these are your targets, not hard caps"
            ).font = SMALL
    for label, fmt in TOTALS:
        h = ws.cell(R_TOT_LBL, T[label], label)
        h.font = Font(bold=True, size=9, color="FFFFFF")
        h.fill = SUBHDR
        h.alignment = Alignment(horizontal="center")
        h.border = BOX
        c = ws.cell(R_TOT_VAL, T[label])
        c.number_format = fmt
        c.border = BOX
        c.fill = INPUT
        c.alignment = Alignment(horizontal="center")

    pt = prior_totals or {}
    ws.cell(R_TOT_VAL, T["Games"], pt.get("Games", 17))
    ws.cell(R_TOT_VAL, T["Plays/G"],
            pt.get("Plays/G", round(f(totals.get("plays_per_game")), 1)))
    ws.cell(R_TOT_VAL, T["Plays"],
            f"={L(T['Plays/G'])}{R_TOT_VAL}*{L(T['Games'])}{R_TOT_VAL}").fill = CALC
    ws.cell(R_TOT_VAL, T["Pass Rate"],
            pt.get("Pass Rate", round(f(totals.get("pass_rate")), 4)))
    # Pass Att / Rush Att are DERIVED from Plays x Pass Rate, not typed - the
    # whole point of having Plays/G and Pass Rate as inputs is that changing
    # them should move everything downstream. They used to be independent
    # typed numbers seeded from the same historical data, which happened to
    # start in agreement with Plays/Pass Rate but silently went stale the
    # moment you edited Plays/G or Pass Rate without also re-typing these -
    # nothing told you they'd drifted apart.
    ws.cell(R_TOT_VAL, T["Pass Att"],
            f"=ROUND({L(T['Plays'])}{R_TOT_VAL}*{L(T['Pass Rate'])}{R_TOT_VAL},0)"
            ).fill = CALC
    ws.cell(R_TOT_VAL, T["Targets"],
            f"=ROUND({L(T['Pass Att'])}{R_TOT_VAL}*Settings!$B$4,0)").fill = CALC
    # Rush Att = Plays - Pass Att, not Plays x (1-Pass Rate) separately -
    # guarantees the two always sum exactly to Plays with no rounding gap.
    ws.cell(R_TOT_VAL, T["Rush Att"],
            f"={L(T['Plays'])}{R_TOT_VAL}-{L(T['Pass Att'])}{R_TOT_VAL}").fill = CALC
    ws.cell(R_TOT_VAL, T["Pass Yds"], pt.get("Pass Yds", i(totals.get("pass_yds"))))
    ws.cell(R_TOT_VAL, T["Pass TD"],
            pt.get("Pass TD", round(f(totals.get("pass_td")), 1)))
    ws.cell(R_TOT_VAL, T["Int"],
            pt.get("Int", round(f(totals.get("interceptions")), 1)))
    ws.cell(R_TOT_VAL, T["Rush Yds"], pt.get("Rush Yds", i(totals.get("rush_yds"))))
    ws.cell(R_TOT_VAL, T["Rush TD"],
            pt.get("Rush TD", round(f(totals.get("rush_td")), 1)))

    tgt_gone, rush_gone = vac
    ws.cell(R_VAC, 1, "VACATED").font = BOLD
    ws.cell(R_VAC, 2, f"{tgt_gone*100:.0f}% of targets and {rush_gone*100:.0f}% "
            f"of carries left this roster - that volume is yours to reassign."
            ).font = Font(size=9, color="A0522D")
    ws.cell(R_COACH, 1, "STAFF").font = BOLD
    ws.cell(R_COACH, 2, coach or "no coaching change recorded"
            ).font = Font(size=9, color="1F6FB5")

    # ── header ─────────────────────────────────────────────────────────────
    for name, width in COLS:
        ws.column_dimensions[L(C[name])].width = width
        h = ws.cell(R_TBL_HDR, C[name], name)
        h.font = Font(bold=True, size=8, color="FFFFFF")
        h.fill = HDR
        h.alignment = Alignment(horizontal="center", wrap_text=True)
        h.border = BOX

    by_pos = defaultdict(list)
    for p in players:
        by_pos["RB" if p["pos"] == "FB" else p["pos"]].append(p)
    for v in by_pos.values():
        v.sort(key=lambda p: int(p["depth"]))

    row = R_FIRST
    pos_rows = {}
    for pos, n in SLOTS:
        start = row
        pool = [p for p in by_pos.get(pos, []) if p["status"] != "OUT"][:n]
        for k in range(n):
            p_ = pool[k] if k < len(pool) else None
            if p_ is not None and written is not None:
                written.append((p_["player"], team))
            write_row(ws, row, pos, p_, hist, seed, consensus, tally,
                      prior_players, team)
            row += 1
        write_other(ws, row, pos)
        row += 1
        pos_rows[pos] = (start, row - 1)

    write_footer(ws, row + 1)
    return pos_rows


def write_row(ws, row, pos, p, hist, seed, consensus=None, tally=None,
             prior=None, team=None):
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX
    ws.cell(row, C["Pos"], pos).font = Font(bold=True, size=9)
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).fill = INPUT
    if p is None:
        ws.cell(row, C["Player"]).fill = INPUT
        write_checks(ws, row)
        return

    ws.cell(row, C["Player"], p["player"])
    ws.cell(row, C["Dep"], i(p["depth"])).alignment = Alignment(horizontal="center")
    ws.cell(row, C["Age"], p["age"]).alignment = Alignment(horizontal="center")
    st = ws.cell(row, C["Status"], p["status"])
    st.font = Font(size=8, color="B22222" if p["status"] != "ACT" else "666666")

    h = hist.get(names.normalize(p["player"]), {})
    ref = {
        f"'{str(HIST[0])[2:]} Car": h.get(f"{HIST[0]}_car"),
        f"'{str(HIST[1])[2:]} Car": h.get(f"{HIST[1]}_car"),
        f"'{str(HIST[2])[2:]} Car": h.get(f"{HIST[2]}_car"),
        f"'{str(HIST[2])[2:]} RuYd": h.get(f"{HIST[2]}_ruyd"),
        f"'{str(HIST[0])[2:]} Tgt": h.get(f"{HIST[0]}_tgt"),
        f"'{str(HIST[1])[2:]} Tgt": h.get(f"{HIST[1]}_tgt"),
        f"'{str(HIST[2])[2:]} Tgt": h.get(f"{HIST[2]}_tgt"),
        f"'{str(HIST[2])[2:]} ReYd": h.get(f"{HIST[2]}_reyd"),
        f"'{str(HIST[2])[2:]} Tm": h.get(f"{HIST[2]}_team"),
        f"'{str(HIST[2])[2:]} G": h.get(f"{HIST[2]}_games"),
        "3y Y/C": h.get("ypc_3y"), "3y Y/R": h.get("ypr_3y"),
        "3y Ctch": h.get("catch_3y"), "3y Comp%": h.get("comp_pct_3y"),
        "3y Y/A": h.get("ypa_3y"),
    }
    FLOAT_REFS = ("3y Y/C", "3y Y/R", "3y Ctch", "3y Comp%", "3y Y/A")
    for name in REF_NAMES:
        v = ref.get(name)
        c = ws.cell(row, C[name], (i(v) if str(v).replace('.','',1).isdigit()
                                   and name not in FLOAT_REFS
                                   else (f(v) if name in FLOAT_REFS and v else v))
                    or None)
        c.fill = REF
        c.font = Font(size=8, color="7A6A55")
        c.number_format = (NUM2 if name in ("3y Y/C", "3y Y/R", "3y Y/A")
                           else PCT if name in ("3y Ctch", "3y Comp%") else NUM0)

    src = ""
    if seed:
        line, src = seed_line(p, h, seed, consensus)
        for name, val in line.items():
            ws.cell(row, C[name], val)
        if tally is not None and src:
            tally[src] += 1
    ws.cell(row, C["Games"], 17)

    # A previous typed edit for this exact (player, team) wins over any seed -
    # your own numbers over a consensus or last-season guess.
    restored = prior.get((names.normalize(p["player"]), team)) if prior else None
    if restored:
        for name, val in restored["edits"].items():
            ws.cell(row, C[name], val)
        src = "kept"
        if tally is not None:
            tally["kept"] += 1
        old_depth = restored.get("depth")
        new_depth = i(p["depth"], None)
        if old_depth and new_depth and old_depth != new_depth:
            n = ws.cell(row, C["Status"], f"depth {old_depth} -> {new_depth}")
            n.font = Font(size=8, color="B8860B", italic=True)

    sc = ws.cell(row, C["Seed"], src or None)
    sc.font = Font(size=8, italic=True,
                   color="2E7D32" if src == "kept"
                   else "1F6FB5" if src == "consensus" else "888888")
    sc.fill = CALC
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).number_format = NUM0
    write_checks(ws, row)


def seed_line(p, h, mode, consensus):
    """Starting values for a row. Returns (values, source-label).

    consensus  - the ff_draft_proj blend. Much the better 2026 starting point,
                 since it already prices in team changes and rookies, but it is
                 somebody else's number until you overwrite it.
    last-season - what this player actually did. Fully independent, but blind to
                 every offseason move.
    """
    if mode == "consensus" and consensus:
        line = consensus.get(names.normalize(p["player"]))
        if line:
            return dict(line), "consensus"

    last = HIST[2]
    out = {}
    for col, key in (("Rush Att", "car"), ("Rush Yds", "ruyd"),
                     ("Rush TD", "rutd"), ("Targets", "tgt"), ("Rec", "rec"),
                     ("Rec Yds", "reyd"), ("Rec TD", "retd"),
                     ("Pass Att", "patt"), ("Cmp", "pcmp"),
                     ("Pass Yds", "pyds"), ("Pass TD", "ptd"), ("Int", "pint")):
        v = h.get(f"{last}_{key}")
        if v not in (None, "", 0):
            out[col] = i(v)
    return out, ("'25" if out else "")


def write_checks(ws, row):
    """Rates and shares - all computed from what you typed."""
    V = R_TOT_VAL
    def cc(n):
        return f"{L(C[n])}{row}"
    out = {
        "Y/C": f"=IFERROR({cc('Rush Yds')}/{cc('Rush Att')},\"\")",
        "Y/R": f"=IFERROR({cc('Rec Yds')}/{cc('Rec')},\"\")",
        "Catch%": f"=IFERROR({cc('Rec')}/{cc('Targets')},\"\")",
        "Y/A": f"=IFERROR({cc('Pass Yds')}/{cc('Pass Att')},\"\")",
        "Comp%": f"=IFERROR({cc('Cmp')}/{cc('Pass Att')},\"\")",
        "Rush %": f"=IFERROR({cc('Rush Att')}/${L(T['Rush Att'])}${V},\"\")",
        "Tgt %": f"=IFERROR({cc('Targets')}/${L(T['Targets'])}${V},\"\")",
        "Pass %": f"=IFERROR({cc('Pass Att')}/${L(T['Pass Att'])}${V},\"\")",
        "Car/G": f"=IFERROR({cc('Rush Att')}/{cc('Games')},\"\")",
        "Tgt/G": f"=IFERROR({cc('Targets')}/{cc('Games')},\"\")",
        # change vs what he actually did last season - a big jump is worth a look
        "dTgt": f"=IFERROR({cc('Targets')}-{cc(REF_NAMES[6])},\"\")",
        "dCar": f"=IFERROR({cc('Rush Att')}-{cc(REF_NAMES[2])},\"\")",
        "Half PPR": (f"={cc('Rec Yds')}*Settings!$B$7+{cc('Rec TD')}*Settings!$B$8"
                     f"+{cc('Rec')}*Settings!$B$9+{cc('Rush Yds')}*Settings!$B$10"
                     f"+{cc('Rush TD')}*Settings!$B$11+{cc('Pass Yds')}*Settings!$B$12"
                     f"+{cc('Pass TD')}*Settings!$B$13+{cc('Int')}*Settings!$B$14"),
    }
    fmts = {"Y/C": NUM2, "Y/R": NUM2, "Catch%": PCT, "Y/A": NUM2, "Comp%": PCT,
            "Rush %": PCT, "Tgt %": PCT, "Pass %": PCT, "Car/G": NUM1,
            "Tgt/G": NUM1, "dTgt": NUM0, "dCar": NUM0, "Half PPR": NUM1}
    for name, formula in out.items():
        c = ws.cell(row, C[name], formula)
        c.fill = CALC
        c.number_format = fmts[name]
        if name == "Half PPR":
            c.font = BOLD


def write_other(ws, row, pos):
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX
        ws.cell(row, C[name]).fill = OTHER
    ws.cell(row, C["Pos"], pos).font = Font(size=9, color="888888")
    ws.cell(row, C["Player"], f"Other {pos}s").font = Font(
        size=9, italic=True, color="888888")
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).fill = INPUT
        ws.cell(row, C[name]).number_format = NUM0
    ws.cell(row, C["Games"], 17)
    write_checks(ws, row)


def write_footer(ws, foot):
    """Team total, your running sum, and what's left. Red when you go over."""
    V = R_TOT_VAL
    ws.cell(foot, 1, "YOUR TOTAL").font = BOLD
    ws.cell(foot + 1, 1, "TEAM TARGET").font = BOLD
    ws.cell(foot + 2, 1, "LEFT").font = BOLD
    ws.cell(foot + 3, 2, "Red = you have allocated more than the team total. "
            "Amber = more than 3% under. These are targets, not hard caps - "
            "if you disagree, edit the team total above.").font = SMALL

    for name in INPUT_NAMES:
        col = L(C[name])
        s = ws.cell(foot, C[name], f"=SUM({col}{R_FIRST}:{col}{R_LAST})")
        s.font = BOLD
        s.number_format = NUM0
        s.border = BOX
        team_label = CONSTRAINED.get(name)
        if not team_label:
            continue
        tref = f"${L(T[team_label])}${V}"
        t = ws.cell(foot + 1, C[name], f"={tref}")
        t.number_format = NUM0
        t.font = Font(size=9, color="666666")
        t.border = BOX
        left = ws.cell(foot + 2, C[name], f"={tref}-{col}{foot}")
        left.number_format = NUM0
        left.border = BOX
        cell = f"{col}{foot}"
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"{cell}>{tref}"], fill=OVER, stopIfTrue=True))
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"AND({tref}>0,{cell}<{tref}*0.97)"],
            fill=PatternFill("solid", fgColor="FFFFF2CC")))
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"AND({tref}>0,{cell}>={tref}*0.97,{cell}<={tref})"],
            fill=GOOD))
    # Rec Yds and Rec TD share the passing totals - note it so it isn't confusing
    ws.cell(foot + 3, C["Rec Yds"],
            "Rec Yds / Rec TD are checked against the PASSING totals"
            ).font = SMALL


def build_settings(ws, target_rate):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 58
    ws.cell(1, 1, "SETTINGS").font = Font(bold=True, size=14, color="2F4F6F")
    for r, label, val, note in [
            (3, "Games in season", 17, ""),
            (4, "Target rate", target_rate,
             "Targets / pass attempt. Gap is throwaways, spikes, batted balls."),
            (6, "SCORING (half PPR)", None, "matches ff_draft_proj/scoring.py"),
            (7, "Pts per rec yard", 0.1, ""), (8, "Pts per rec TD", 6, ""),
            (9, "Pts per reception", 0.5, "0 = standard, 1 = full PPR"),
            (10, "Pts per rush yard", 0.1, ""), (11, "Pts per rush TD", 6, ""),
            (12, "Pts per pass yard", 0.04, ""), (13, "Pts per pass TD", 4, ""),
            (14, "Pts per INT", -2, "negative")]:
        ws.cell(r, 1, label).font = BOLD
        if val is not None:
            c = ws.cell(r, 2, val)
            c.fill = INPUT
            c.number_format = "0.000" if isinstance(val, float) else NUM0
        ws.cell(r, 3, note).font = SMALL


def build_start_here(ws, seed_desc):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 100
    ws.cell(2, 2, f"{SEASON} PROJECTIONS - DIRECT ENTRY (v2)").font = Font(
        bold=True, size=18, color="2F4F6F")
    blocks = [
        ("What changed from v1", [
            "v1: you entered percentages, everything else was derived, and nothing",
            "could exceed the team total. Yards per carry was an output.",
            "v2: you type the real numbers. Rates and shares are computed as",
            "checks. Nothing is auto-balanced - the footer tells you when you've",
            "gone over instead of silently absorbing it.",
        ]),
        ("Colours", [
            "   BLUE  you type here",
            "   CREAM what he actually did - 2023/24/25 volume, yards, team, games",
            "   GREY  computed: rates, shares, per-game, change vs last year",
        ]),
        ("The footer is the control", [
            "   YOUR TOTAL   what your rows add up to",
            "   TEAM TARGET  the team total from the block up top",
            "   LEFT         what's still unallocated",
            "",
            "   RED   = over the team total",
            "   AMBER = more than 3% under",
            "   GREEN = within 3%",
            "",
            "Team totals are editable. If you think the team is better than the",
            "model says, raise the total rather than squeezing the players.",
        ]),
        ("Seeds", [
            f"This build's un-typed rows came from: {seed_desc}.",
            "The Seed column (grey, next to Half PPR) shows the source per row -",
            "'consensus', ''25', or 'kept' if it's your own number, restored.",
            "The cream columns show the matching historical number beside it, so",
            "you can see exactly what you're changing and by how much.",
        ]),
        ("Rebuilding without losing your work", [
            "python build_workbook_v2.py --merge  keeps every typed cell, only",
            "refreshes rows nobody has touched. This is the normal command for",
            "every rebuild after the first - a plain rebuild REFUSES once Excel",
            "has saved this file, specifically so you don't do this by accident.",
            "",
            "Consensus seeding was a ONE-TIME bootstrap, not something that",
            "happens again automatically. --merge never re-pulls it. If you want",
            "another fresh consensus pull later, ask for it on purpose:",
            "python build_workbook_v2.py --seed consensus --merge",
        ]),
        ("Sanity checks worth watching", [
            "   Y/C, Y/R, Catch%, Y/A   are your rates believable?",
            "   Car/G, Tgt/G            per-game is easier to judge than a total",
            "   dCar, dTgt              change vs last season - big jumps stand out",
        ]),
    ]
    row = 4
    for title, lines in blocks:
        ws.cell(row, 2, title).font = Font(bold=True, size=12, color="2F4F6F")
        row += 1
        for line in lines:
            ws.cell(row, 2, line).font = Font(size=10)
            row += 1
        row += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", default="last-season",
                    choices=("consensus", "last-season", "blank"),
                    help="what to prefill NEW/unseeded rows with (players you've "
                         "already edited always keep their numbers via --merge, "
                         "regardless of this setting): last season's actual line "
                         "(default - independent, but blind to the offseason), "
                         "the ff_draft_proj consensus blend (a one-time bootstrap "
                         "- pass this explicitly, it is not the default so a "
                         "routine --merge never silently re-pulls it), or nothing")
    ap.add_argument("--out", default="my_projections_v2.xlsx")
    ap.add_argument("--merge", action="store_true",
                    help="rebuild from fresh data but carry your typed numbers "
                         "over, keyed by (player, team). Reports what it could "
                         "not keep.")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the existing workbook has edits "
                         "(they are discarded; a timestamped backup is kept)")
    args = ap.parse_args()

    out_path = os.path.join(HERE, args.out)
    if os.path.exists(out_path) and looks_edited(out_path) \
            and not (args.force or args.merge):
        sys.exit(
            f"\n{args.out} looks like you've worked in it (Excel has saved "
            f"it).\nA plain rebuild would DISCARD those edits.\n"
            f"\n  keep your work : do nothing, just keep using the file"
            f"\n  carry it over  : python build_workbook_v2.py --merge"
            f"\n  discard it     : python build_workbook_v2.py --force"
            f"\n                   (your current file is backed up first either way)\n")

    prior_players, prior_totals = ({}, {})
    if args.merge and os.path.exists(out_path):
        prior_players, prior_totals = read_existing(out_path)
        print(f"  read {len(prior_players)} existing player edits to merge")

    consensus = load_consensus() if args.seed == "consensus" else {}
    if args.seed == "consensus" and not consensus:
        sys.exit("No consensus_*.csv found in ff_draft_proj - "
                 "run its build_consensus.py, or use --seed last-season.")
    tally = defaultdict(int)

    shares = read_csv("player_shares.csv")
    totals = {r["team"]: r for r in read_csv(f"team_totals_{SEASON}.csv")}
    hist = {names.normalize(r["player"]): r
            for r in read_csv(f"player_history_{SEASON}.csv")}
    vac_rows = read_csv(f"vacated_{SEASON}.csv")

    coaching = {}
    cpath = os.path.join(HERE, "manual", "coaching_changes.csv")
    if os.path.exists(cpath):
        with open(cpath, newline="", encoding="utf-8") as fh:
            lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
        for r in csv.DictReader(lines):
            if r.get("team"):
                coaching[r["team"].strip().upper()] = r.get("note", "")

    vac = defaultdict(lambda: (0.0, 0.0))
    for r in vac_rows:
        vac[r["team"]] = (f(r["tgt_share_vacated"]), f(r["rush_share_vacated"]))

    by_team = defaultdict(list)
    for p in shares:
        by_team[p["team"]].append(p)

    wb = Workbook()
    wb.remove(wb.active)
    seed_desc = {"consensus": "the ff_draft_proj consensus blend",
                "last-season": "each player's actual last-season line",
                "blank": "nothing - blank"}[args.seed]
    build_start_here(wb.create_sheet("Start Here"), seed_desc)
    written_players = []
    for team in TEAMS:
        build_team_tab(wb.create_sheet(team), team, by_team.get(team, []),
                       totals.get(team, {}), hist, vac[team],
                       coaching.get(team),
                       None if args.seed == "blank" else args.seed,
                       consensus, tally,
                       prior_players or None, prior_totals.get(team),
                       written_players)
    build_settings(wb.create_sheet("Settings"), 0.954)

    validate(wb)

    out = os.path.join(HERE, args.out)
    if os.path.exists(out):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = out.replace(".xlsx", f".backup-{stamp}.xlsx")
        try:
            os.replace(out, backup)
        except PermissionError:
            sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n")
        print(f"  previous copy saved as {os.path.basename(backup)}")
    try:
        wb.save(out)
    except PermissionError:
        sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n")

    if args.merge and prior_players:
        merge_report(prior_players, written_players)

    print(f"\nWrote {args.out}  (v1 untouched at my_projections.xlsx)")
    print(f"  32 team tabs, seed mode: {args.seed}")
    if tally:
        total = sum(tally.values())
        for src, n in sorted(tally.items(), key=lambda x: -x[1]):
            label = {"consensus": "from consensus",
                     "'25": "from last season (no consensus line)",
                     "kept": "kept from your last edit"}.get(src, src)
            print(f"    {n:>4} rows {label}")
        print(f"    {total:>4} rows seeded; the Seed column marks each one")


if __name__ == "__main__":
    sys.exit(main())
