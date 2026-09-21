#!/usr/bin/env python3
"""Build my_projections_v3.xlsx - MARKET SHARE workbook.

The design, in one line
-----------------------
You set each player's SHARE of his team's volume plus his efficiency RATES.
Everything else - attempts, yards, touchdowns, fantasy points - is calculated.

Why a v3
--------
v1 had you enter shares but derived yards from a normalized team total, so
yards-per-carry was an output you could only nudge indirectly. v2 flipped to
typing raw counting stats, which gave full rate control but meant balancing
ten columns per team by hand against targets that never quite closed.

v3 keeps v2's rate control and drops the balancing problem, because nothing
has to sum to a locked number:

    team plays x pass rate   -> team pass att / rush att   (you set both)
    team TDs x rush TD rate  -> team rush TD / pass TD     (TDs from Vegas)
    your share % x those     -> each player's opportunity
    x your rates             -> yards, receptions, TDs

Team YARDS are shown at the top as a historical REFERENCE, not a constraint.
Passing yards are built bottom-up (a QB's passing yards = his share of what
his receivers actually catch), so the sheet is internally consistent by
construction and there's no team yardage figure to violate.

TD market share is a SEPARATE input from volume share, deliberately. A
goal-line back can own 35% of a team's rushing TDs on 8% of its carries; a
slot receiver the reverse. Deriving TDs from volume would erase that.

Data sources
------------
  team TDs      Vegas implied points (fetch_odds.py). Validated against
                Sharp Football Analysis at r=0.9997, mean abs diff 0.04 pts/g.
  team plays,   3-yr team history, regressed to mean (build_team_totals.py).
  pass rate,    NOT from Vegas - yards-per-point varies 11.8-21.4 across
  team yards    teams, so predicting yardage from points is worse than history.
  rush TD rate  per-team 3-yr history (league mean 38.2%, range 18.9-55.2%).
  player seeds  3-yr market shares and rates (build_shares/build_history).

Usage:
    python build_workbook_v3.py
    python build_workbook_v3.py --merge     # keep your edits, refresh the rest
    python build_workbook_v3.py --force     # discard edits (backup kept)
"""

import argparse
import csv
import datetime
import os
import sys
from collections import defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import names
from teams import TEAMS

HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = 2026
HIST = [SEASON - 3, SEASON - 2, SEASON - 1]
LAST = HIST[2]
SLOTS = [("QB", 3), ("RB", 6), ("WR", 8), ("TE", 4)]

# 8-digit ARGB required for conditional-formatting fills; a 6-digit hex
# silently serializes with alpha=00 (invisible) inside a dxf.
INPUT = PatternFill("solid", fgColor="DCE9F7")
CALC = PatternFill("solid", fgColor="F2F2F2")
REF = PatternFill("solid", fgColor="FFF6E5")
HDR = PatternFill("solid", fgColor="2F4F6F")
SUBHDR = PatternFill("solid", fgColor="8EA9C1")
BAND = PatternFill("solid", fgColor="E8EEF4")
OTHER = PatternFill("solid", fgColor="EDEDED")
# Conditional-format fills are bgColor, NOT fgColor. Inside a dxf (the
# differential format a CF rule points at) Excel paints the pattern's
# BACKGROUND; fgColor is the pattern's foreground, which a solid fill never
# shows. Written as PatternFill("solid", fgColor=...) - correct for an
# ordinary cell - the rule serializes fine, validates fine, and renders
# nothing. bgColor alone reproduces exactly what Excel writes itself:
#     <patternFill><bgColor rgb="FFFFC7CE"/></patternFill>
OVER = PatternFill(bgColor="FFFFC7CE")
GOOD = PatternFill(bgColor="FFC6EFCE")
WARN = PatternFill(bgColor="FFFFF2CC")

BOLD = Font(bold=True)
SMALL = Font(size=9, color="666666")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
PCT, PCT1, NUM0, NUM1, NUM2 = "0%", "0.0%", "0", "0.0", "0.00"

L = get_column_letter

# ── row layout ──────────────────────────────────────────────────────────────
R_TITLE = 1
R_T1_LBL, R_T1_VAL = 3, 4        # team block row 1: volume
R_T2_LBL, R_T2_VAL = 6, 7        # team block row 2: TDs + yardage reference
R_NOTE = 9                        # vacated / staff note
R_HDR = 11
R_FIRST = 12
R_LAST = R_FIRST + sum(n + 1 for _, n in SLOTS) - 1
R_TOTAL = R_LAST + 2              # YOUR TOTAL
R_REF = R_TOTAL + 1               # reference / target
R_DIFF = R_TOTAL + 2              # difference

# ── team control block ──────────────────────────────────────────────────────
# (label, format, is_input)  - laid out across two rows so it stays readable
TEAM1 = [("Games", NUM0, True), ("Team Plays", NUM0, True),
         ("Plays/G", NUM1, False), ("Pass Play %", PCT1, True),
         ("Pass Att", NUM0, False), ("Rush Att", NUM0, False),
         ("Targets", NUM0, False)]
TEAM2 = [("Total TD", NUM1, True), ("Rush TD %", PCT1, True),
         ("Rush TD", NUM1, False), ("Pass TD", NUM1, False),
         ("~Pass Yds", NUM0, False), ("~Rush Yds", NUM0, False),
         ("~Rec Yds", NUM0, False)]
T1 = {n: i + 2 for i, (n, _, _) in enumerate(TEAM1)}
T2 = {n: i + 2 for i, (n, _, _) in enumerate(TEAM2)}

# Last season's ACTUALS, parked to the right of the projection block on the
# same two rows so each projected figure sits directly across from what the
# team really did. Read-only - this is the yardstick, not an input.
ACT_COL0 = 12                        # column L
# Completion % deliberately NOT here: it's a passer's rate, not a team lever,
# and it already sits on each QB row as 3y Cmp%. A team figure would just be a
# weighted average of the QBs behind it. Y/A earns the slot instead - it's the
# check on whether the bottom-up passing yards came out sane.
ACT1 = [("Plays", NUM0, "plays"), ("Plays/G", NUM1, "plays_per_game"),
        ("Pass%", PCT1, "pass_rate"), ("PassAtt", NUM0, "pass_att"),
        ("RushAtt", NUM0, "rush_att"), ("Y/A", NUM2, "ypa")]
ACT2 = [("PassYds", NUM0, "pass_yds"), ("RushYds", NUM0, "rush_yds"),
        ("PassTD", NUM1, "pass_td"), ("RushTD", NUM1, "rush_td"),
        ("TotTD", NUM1, None), ("RuTD%", PCT1, None)]
A1 = {n: ACT_COL0 + i for i, (n, _, _) in enumerate(ACT1)}
A2 = {n: ACT_COL0 + i for i, (n, _, _) in enumerate(ACT2)}


def t1(name):
    return f"${L(T1[name])}${R_T1_VAL}"


def t2(name):
    return f"${L(T2[name])}${R_T2_VAL}"


# ── player columns ──────────────────────────────────────────────────────────
IDENT = [("Pos", 5), ("Player", 22), ("Dep", 4), ("Age", 4), ("Status", 9)]

# Historical reference - what he actually did. Rates included, since those are
# what you're aiming at when you fill in the input rates.
REFS = [(f"'{str(LAST)[2:]} Tm", 5), (f"'{str(LAST)[2:]} G", 4),
        # Snap share: the cleanest role signal there is. Target and carry
        # share tell you who got the ball; this tells you who was on the
        # field, which is what actually moves first when a role changes.
        ("Snap%", 7),
        (f"'{str(LAST)[2:]} Pass%", 7), ("3y Cmp%", 7), ("3y Y/A", 6),
        ("3y Int%", 7),
        (f"'{str(LAST)[2:]} Rush%", 7), ("3y Y/C", 6),
        # RZ opportunity share sits next to the TD share it justifies. A back
        # with 40% of the red-zone carries but 25% of the TDs is a positive
        # regression candidate - that gap is invisible without both columns.
        (f"'{str(LAST)[2:]} RZRu%", 7), (f"'{str(LAST)[2:]} RuTD%", 7),
        (f"'{str(HIST[1])[2:]} Tgt%", 7), (f"'{str(LAST)[2:]} Tgt%", 7),
        ("3y Ctch", 7), ("3y Y/R", 6),
        (f"'{str(LAST)[2:]} RZTg%", 7), (f"'{str(LAST)[2:]} ReTD%", 7)]

# What you set.
INPUTS = [("Games", 6),
          ("Pass %", 7), ("Comp %", 7), ("Int Rate", 7),
          ("Rush %", 7), ("Y/C", 6), ("Rush TD %", 8),
          ("Tgt %", 7), ("Catch %", 7), ("Y/R", 6), ("Rec TD %", 8)]

# Calculated.
CALCS = [("Pass Att", 8), ("Cmp", 6), ("Pass Yds", 8),
         ("Pass TD", 7), ("Int", 5),
         ("Rush Att", 8), ("Rush Yds", 8), ("Rush TD", 7),
         ("Targets", 7), ("Rec", 6), ("Rec Yds", 8), ("Rec TD", 7),
         ("STD", 7), ("Half", 7), ("PPR", 7)]

COLS = IDENT + REFS + INPUTS + CALCS
C = {n: i + 1 for i, (n, _) in enumerate(COLS)}
INPUT_NAMES = [n for n, _ in INPUTS]
REF_NAMES = [n for n, _ in REFS]
CALC_NAMES = [n for n, _ in CALCS]

# Player calc column -> the team cell it should be compared against.
COMPARE = {"Pass Att": ("Pass Att", 1), "Rush Att": ("Rush Att", 1),
           "Targets": ("Targets", 1), "Pass TD": ("Pass TD", 2),
           "Rush TD": ("Rush TD", 2), "Rec TD": ("Pass TD", 2),
           "Pass Yds": ("~Pass Yds", 2), "Rush Yds": ("~Rush Yds", 2),
           "Rec Yds": ("~Rec Yds", 2),
           # "calc": compare against another CALC column's own R_TOTAL cell,
           # not a team-block cell - a completion IS a reception, so the
           # thing to check Cmp against is this team's Rec total.
           "Cmp": ("Rec", "calc")}

# Share columns that should sum to ~100% across the roster.
SHARE_INPUTS = ["Pass %", "Rush %", "Rush TD %", "Tgt %", "Rec TD %"]

BAD = ("*/", "/*", "**", "//", "+*", "*+", "+/", "-/", "(*", "(/", "*)",
       "/)", "$None", "None", ",,")


def f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def i_(v, d=0):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return d


def read_csv(name, required=True):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        if required:
            sys.exit(f"Missing {name}. Run the earlier build steps first.")
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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


def header_map(ws):
    """This sheet's own column layout - never trust the module's C dict on a
    file that may have been written by an older version of this script."""
    return {c.value: c.column for c in ws[R_HDR] if c.value}


def looks_edited(path):
    wb = None
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
        for sheet in TEAMS[:6]:
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            col = header_map(ws).get("Half")
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
        if wb is not None:
            wb.close()
    return False


def read_existing(path):
    """Hand-set inputs from an existing v3 workbook, keyed by (player, team).

    Team-keyed because a share belongs to an offense: 20% of Denver's targets
    is a different real quantity from 20% of Miami's, so a share can't follow
    a player who changed teams.
    """
    wb = None
    players, teams = {}, {}
    # Every input cell in an existing file is a decision, including the
    # empty ones - a cell cleared to balance a team must not come back as a
    # seed on the next rebuild. This used to gate on looks_edited() (a cached
    # Excel-computed value as proof a human had opened the file), but that
    # signal only exists once Excel itself has recalculated and saved -
    # openpyxl never writes one. Two scripted --merge rebuilds in a row with
    # no real Excel save between them produced a file with NO cached values,
    # so the second rebuild silently treated every cleared cell as never-set
    # and reseeded it. Blank-stays-blank now applies unconditionally to any
    # row found in the file being merged from - see `known` below.
    try:
        wb = load_workbook(path, data_only=False, read_only=True)
        for team in TEAMS:
            if team not in wb.sheetnames:
                continue
            ws = wb[team]
            old = header_map(ws)
            if "Player" not in old:
                continue
            tvals = {}
            for label, _, is_in in TEAM1:
                if is_in:
                    v = ws.cell(R_T1_VAL, T1[label]).value
                    if isinstance(v, (int, float)):
                        tvals[("T1", label)] = v
            for label, _, is_in in TEAM2:
                if is_in:
                    v = ws.cell(R_T2_VAL, T2[label]).value
                    if isinstance(v, (int, float)):
                        tvals[("T2", label)] = v
            if tvals:
                teams[team] = tvals
            for row in range(R_FIRST, R_LAST + 1):
                name = ws.cell(row, old["Player"]).value
                if not name or not isinstance(name, str):
                    continue
                if name.startswith("Other ") and name.endswith("s"):
                    continue
                edits = {}
                # Which input columns this file actually had. A column added
                # to the code since it was written is genuinely absent rather
                # than cleared, so it still gets seeded.
                known = [c for c in INPUT_NAMES if c in old]
                for col in known:
                    v = ws.cell(row, old[col]).value
                    if isinstance(v, (int, float)):
                        edits[col] = v
                # Games alone isn't evidence of a real edit - it's written
                # unconditionally - but the row is still tracked so its known
                # columns stay blank on merge; `real` only affects the
                # "N edits carried over" count printed to the user.
                real = {k: v for k, v in edits.items() if k != "Games"}
                players[(names.normalize(name), team)] = {
                    "edits": edits, "display": name, "known": known,
                    "counted": bool(real)}
    except Exception as exc:
        print(f"  could not read existing workbook ({exc}); building fresh")
        return {}, {}
    finally:
        if wb is not None:
            wb.close()
    return players, teams


# ── sheet construction ──────────────────────────────────────────────────────

def team_block(ws, team, totals, vegas, rush_td_rate, prior_totals,
               last_actual=None):
    pt = prior_totals or {}

    def put(row_lbl, row_val, spec, idx, label, value, is_input):
        h = ws.cell(row_lbl, idx[label], label)
        h.font = Font(bold=True, size=8, color="FFFFFF")
        h.fill = SUBHDR
        h.alignment = Alignment(horizontal="center", wrap_text=True)
        h.border = BOX
        c = ws.cell(row_val, idx[label], value)
        c.number_format = spec
        c.border = BOX
        c.alignment = Alignment(horizontal="center")
        c.fill = INPUT if is_input else CALC
        if is_input:
            c.font = BOLD
        return c

    ws.cell(R_T1_LBL - 1, 1, "TEAM VOLUME").font = BOLD
    ws.cell(R_T1_LBL - 1, 3, "blue = you set it; grey = calculated").font = SMALL

    plays = i_(totals.get("plays"), 1050)
    pass_rate = f(totals.get("pass_rate"), 0.57)

    vals1 = {
        "Games": pt.get(("T1", "Games"), 17),
        "Team Plays": pt.get(("T1", "Team Plays"), plays),
        "Plays/G": f"={t1('Team Plays')}/{t1('Games')}",
        "Pass Play %": pt.get(("T1", "Pass Play %"), round(pass_rate, 4)),
        "Pass Att": f"=ROUND({t1('Team Plays')}*{t1('Pass Play %')},0)",
        # Rush = Plays - Pass, so the two always sum exactly to Plays.
        "Rush Att": f"={t1('Team Plays')}-{t1('Pass Att')}",
        # Not every pass attempt reaches a receiver: throwaways, spikes and
        # batted balls never become targets. ~4.6% league-wide.
        "Targets": f"=ROUND({t1('Pass Att')}*Settings!$B$4,0)",
    }
    for label, fmt, is_in in TEAM1:
        put(R_T1_LBL, R_T1_VAL, fmt, T1, label, vals1[label], is_in)

    actuals_block(ws, last_actual or {})

    ws.cell(R_T2_LBL - 1, 1, "TEAM SCORING & YARDS").font = BOLD
    ws.cell(R_T2_LBL - 1, 3,
            "TDs from Vegas implied points; yards are a historical "
            "REFERENCE, not a cap").font = SMALL

    vals2 = {
        "Total TD": pt.get(("T2", "Total TD"), round(vegas, 1)),
        "Rush TD %": pt.get(("T2", "Rush TD %"), round(rush_td_rate, 4)),
        "Rush TD": f"={t2('Total TD')}*{t2('Rush TD %')}",
        "Pass TD": f"={t2('Total TD')}-{t2('Rush TD')}",
        "~Pass Yds": i_(totals.get("pass_yds")),
        "~Rush Yds": i_(totals.get("rush_yds")),
        # Receiving yards ARE passing yards, seen from the other side.
        "~Rec Yds": f"={t2('~Pass Yds')}",
    }
    for label, fmt, is_in in TEAM2:
        put(R_T2_LBL, R_T2_VAL, fmt, T2, label, vals2[label], is_in)


def actuals_block(ws, act):
    """Last season's real team numbers, for direct comparison."""
    hdr = ws.cell(R_T1_LBL - 1, ACT_COL0, f"{LAST} ACTUAL")
    hdr.font = Font(bold=True, size=9, color="7A6A55")

    def put(row_lbl, row_val, spec, idx, label, fmt, value):
        h = ws.cell(row_lbl, idx[label], label)
        h.font = Font(bold=True, size=8, color="FFFFFF")
        h.fill = SUBHDR
        h.alignment = Alignment(horizontal="center", wrap_text=True)
        h.border = BOX
        c = ws.cell(row_val, idx[label], value)
        c.number_format = fmt
        c.fill = REF
        c.font = Font(size=9, color="7A6A55")
        c.border = BOX
        c.alignment = Alignment(horizontal="center")

    for label, fmt, key in ACT1:
        put(R_T1_LBL, R_T1_VAL, fmt, A1, label, fmt,
            f(act.get(key)) or None)
    ptd, rtd = f(act.get("pass_td")), f(act.get("rush_td"))
    for label, fmt, key in ACT2:
        if key:
            v = f(act.get(key)) or None
        elif label == "TotTD":
            v = (ptd + rtd) or None
        else:                                    # RuTD%
            v = (rtd / (ptd + rtd)) if (ptd + rtd) else None
        put(R_T2_LBL, R_T2_VAL, fmt, A2, label, fmt, v)


def write_header(ws):
    # The team block sits in columns B-H, the same columns the player table
    # sizes for its own narrow fields (Dep=4, Age=4). Excel has one width per
    # column, so the narrow player field wins and team values render as ###.
    # Take whichever is wider rather than hardcoding, so this can't silently
    # break again if either layout shifts.
    minimums = {}
    for label, idx in list(A1.items()) + list(A2.items()):
        minimums[idx] = max(minimums.get(idx, 0), 8)
    for label, idx in list(T1.items()) + list(T2.items()):
        # header text plus a little padding; values are short (e.g. "1064",
        # "46.2%") but the wrapped label is what actually needs the room.
        minimums[idx] = max(minimums.get(idx, 0), 8)

    for name, width in COLS:
        col = C[name]
        ws.column_dimensions[L(col)].width = max(width, minimums.get(col, 0))
        h = ws.cell(R_HDR, C[name], name)
        h.font = Font(bold=True, size=8, color="FFFFFF")
        h.fill = HDR
        h.alignment = Alignment(horizontal="center", wrap_text=True)
        h.border = BOX


def player_formulas(ws, row):
    """Share x team volume -> opportunity; opportunity x rate -> production."""
    def cc(n):
        return f"{L(C[n])}{row}"

    rec_yds_range = f"${L(C['Rec Yds'])}${R_FIRST}:${L(C['Rec Yds'])}${R_LAST}"
    rec_range = f"${L(C['Rec'])}${R_FIRST}:${L(C['Rec'])}${R_LAST}"

    out = {
        "Pass Att": f"=IFERROR({cc('Pass %')}*{t1('Pass Att')},0)",
        # Bottom-up: a QB's passing yards are his share of what his receivers
        # actually catch. No separate team passing-yards input to contradict,
        # and no Y/A field for the QB - that would over-determine the answer.
        "Pass Yds": f"=IFERROR({cc('Pass %')}*SUM({rec_yds_range}),0)",
        # A completion IS a reception, so the TEAM total should equal this
        # team's receptions - but unlike Pass Yds (bottom-up by construction),
        # Comp % is a free input here, same as every other rate in the sheet.
        # It can drift, same as Pass %/Tgt %/etc. can drift off 100% - the
        # footer DIFF row flags it (see COMPARE) instead of the formula
        # making it structurally impossible. A relative multiplier made this
        # un-droppable, but also un-guessable; a plain rate you can type from
        # a player's own history is worth the small risk of drift.
        "Cmp": f"=IFERROR({cc('Pass Att')}*{cc('Comp %')},0)",
        "Pass TD": f"=IFERROR({cc('Pass %')}*{t2('Pass TD')},0)",
        "Int": f"=IFERROR({cc('Pass Att')}*{cc('Int Rate')},0)",
        "Rush Att": f"=IFERROR({cc('Rush %')}*{t1('Rush Att')},0)",
        "Rush Yds": f"=IFERROR({cc('Rush Att')}*{cc('Y/C')},0)",
        # TD share is its own input, NOT derived from carry share.
        "Rush TD": f"=IFERROR({cc('Rush TD %')}*{t2('Rush TD')},0)",
        "Targets": f"=IFERROR({cc('Tgt %')}*{t1('Targets')},0)",
        "Rec": f"=IFERROR({cc('Targets')}*{cc('Catch %')},0)",
        "Rec Yds": f"=IFERROR({cc('Rec')}*{cc('Y/R')},0)",
        "Rec TD": f"=IFERROR({cc('Rec TD %')}*{t2('Pass TD')},0)",
    }
    fmts = {"Pass Att": NUM0, "Cmp": NUM0, "Pass Yds": NUM0,
            "Pass TD": NUM1, "Int": NUM1,
            "Rush Att": NUM0, "Rush Yds": NUM0, "Rush TD": NUM1,
            "Targets": NUM0, "Rec": NUM0, "Rec Yds": NUM0, "Rec TD": NUM1}
    for name, formula in out.items():
        c = ws.cell(row, C[name], formula)
        c.fill = CALC
        c.number_format = fmts[name]

    # Fantasy points, all three formats, from Settings so there is one
    # scoring definition in the workbook.
    base = (f"{cc('Rush Yds')}*Settings!$B$10+{cc('Rush TD')}*Settings!$B$11"
            f"+{cc('Rec Yds')}*Settings!$B$7+{cc('Rec TD')}*Settings!$B$8"
            f"+{cc('Pass Yds')}*Settings!$B$12+{cc('Pass TD')}*Settings!$B$13"
            f"+{cc('Int')}*Settings!$B$14")
    for label, ppr_cell in (("STD", None), ("Half", "Settings!$B$9"),
                            ("PPR", "Settings!$B$15")):
        formula = f"={base}" + (f"+{cc('Rec')}*{ppr_cell}" if ppr_cell else "")
        c = ws.cell(row, C[label], formula)
        c.fill = CALC
        c.number_format = NUM1
        if label == "Half":
            c.font = BOLD


def write_player(ws, row, pos, p, hist, prior, team, seed=True, scale=None):
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX
    ws.cell(row, C["Pos"], pos).font = Font(bold=True, size=9)
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).fill = INPUT

    if p is None:
        ws.cell(row, C["Player"]).fill = INPUT
        player_formulas(ws, row)
        return

    ws.cell(row, C["Player"], p["player"])
    ws.cell(row, C["Dep"], i_(p["depth"])).alignment = Alignment(horizontal="center")
    ws.cell(row, C["Age"], p["age"]).alignment = Alignment(horizontal="center")
    st = ws.cell(row, C["Status"], p["status"])
    st.font = Font(size=8, color="B22222" if p["status"] != "ACT" else "666666")

    h = hist.get(names.normalize(p["player"]), {})
    ref = {
        f"'{str(LAST)[2:]} Tm": h.get(f"{LAST}_team"),
        f"'{str(LAST)[2:]} G": h.get(f"{LAST}_games"),
        "Snap%": f(h.get("snap_pct_3y")) or None,
        f"'{str(LAST)[2:]} Pass%": f(p.get(f"pass_share_{LAST}")) or None,
        "3y Cmp%": f(h.get("comp_pct_3y")) or None,
        "3y Y/A": f(h.get("ypa_3y")) or None,
        "3y Int%": f(h.get("int_pct_3y")) or None,
        f"'{str(LAST)[2:]} Rush%": f(p.get(f"rush_share_{LAST}")) or None,
        "3y Y/C": f(h.get("ypc_3y")) or None,
        f"'{str(LAST)[2:]} RZRu%": f(p.get(f"rz_rush_share_{LAST}")) or None,
        f"'{str(LAST)[2:]} RuTD%": f(p.get(f"rush_td_share_{LAST}")) or None,
        f"'{str(HIST[1])[2:]} Tgt%": f(p.get(f"tgt_share_{HIST[1]}")) or None,
        f"'{str(LAST)[2:]} Tgt%": f(p.get(f"tgt_share_{LAST}")) or None,
        "3y Ctch": f(h.get("catch_3y")) or None,
        "3y Y/R": f(h.get("ypr_3y")) or None,
        f"'{str(LAST)[2:]} RZTg%": f(p.get(f"rz_tgt_share_{LAST}")) or None,
        f"'{str(LAST)[2:]} ReTD%": f(p.get(f"rec_td_share_{LAST}")) or None,
    }
    pct_refs = {f"'{str(LAST)[2:]} Pass%", "3y Cmp%", "3y Int%",
                f"'{str(LAST)[2:]} Rush%",
                f"'{str(LAST)[2:]} RuTD%", f"'{str(HIST[1])[2:]} Tgt%",
                f"'{str(LAST)[2:]} Tgt%", "3y Ctch", f"'{str(LAST)[2:]} ReTD%",
                "Snap%", f"'{str(LAST)[2:]} RZRu%", f"'{str(LAST)[2:]} RZTg%"}
    num2_refs = {"3y Y/A", "3y Y/C", "3y Y/R"}
    for name in REF_NAMES:
        c = ws.cell(row, C[name], ref.get(name))
        c.fill = REF
        c.font = Font(size=8, color="7A6A55")
        c.number_format = (PCT if name in pct_refs
                           else NUM2 if name in num2_refs else NUM0)

    if seed:
        for name, val in seed_inputs(p, h, pos, scale).items():
            ws.cell(row, C[name], val)
    ws.cell(row, C["Games"], 17)

    # Your own prior edit beats any seed.
    restored = prior.get((names.normalize(p["player"]), team)) if prior else None
    if restored:
        for name, val in restored["edits"].items():
            if name in C:
                ws.cell(row, C[name], val)
        # Blanks in an existing row are decisions too - a cell emptied to
        # balance a team stays empty. Only columns the old file didn't have
        # (a brand-new input column) are left holding their fresh seed.
        for name in restored.get("known", ()):
            if name not in restored["edits"] and name in C:
                # .value = None, not cell(row, col, None): openpyxl treats a
                # None third argument as "no value supplied" and leaves the
                # seed sitting there.
                ws.cell(row, C[name]).value = None

    fmts = {"Games": NUM0, "Pass %": PCT1, "Comp %": PCT1,
            "Int Rate": PCT1, "Rush %": PCT1,
            "Y/C": NUM2, "Rush TD %": PCT1, "Tgt %": PCT1, "Catch %": PCT1,
            "Y/R": NUM2, "Rec TD %": PCT1}
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).number_format = fmts[name]

    player_formulas(ws, row)


SEED_KEYS = {"Pass %": "pass_share_w", "Rush %": "rush_share_w",
             "Rush TD %": "rush_td_share_w", "Tgt %": "tgt_share_w",
             "Rec TD %": "rec_td_share_w"}


def seed_scale(pool):
    """Per-team factors that make each seeded share column total 100%.

    Raw 3-yr shares don't add up across a roster - players arrive from other
    teams carrying a share of THEIR old offense, others leave and take theirs
    with them. Unscaled, the seeds came out 71-182% by column. Scaling each
    team's pool preserves the relative ordering history produced while handing
    you a sheet that opens balanced instead of one to repair first.
    """
    scale = {}
    for col, key in SEED_KEYS.items():
        elig = [p for p in pool
                if col != "Pass %" or p.get("pos") == "QB"]
        total = sum(f(p.get(key)) for p in elig)
        scale[col] = (1.0 / total) if total > 0 else 1.0
    return scale


# Rookie rate defaults, measured from 2023-2025 debut seasons vs veteran
# seasons in cached/sr. The interesting result is how SMALL the gap is: a
# rookie's efficiency is close to a veteran's, it's his USAGE that's usually
# lower. So these are league-average rates with a modest rookie discount
# applied, not a big penalty.
#
#   metric        rookie   veteran   gap
#   RB Y/C         4.13     4.37    -5.6%
#   RB Y/R         7.13     7.66    -6.9%
#   RB catch%      .774     .796    -2.7%
#   TE Y/R        10.32    10.42    -1.0%
#   TE catch%      .711     .729    -2.5%
#   WR Y/R        12.84    12.83    +0.1%
#   WR catch%      .619     .632    -2.0%
#
# Efficiency is largely a function of role and scheme, which a rookie inherits
# from the offense he joins - it isn't something he has to earn. Where rookies
# actually lag is opportunity, and that's the share input, which you set.
ROOKIE_RATES = {
    "RB": {"Y/C": 4.13, "Y/R": 7.13, "Catch %": 0.774},
    "WR": {"Y/R": 12.84, "Catch %": 0.619},
    "TE": {"Y/R": 10.32, "Catch %": 0.711},
    # QBs get a rushing rate only. Seeding them a catch rate and Y/R implied
    # they're pass CATCHERS, which they aren't - the receiving columns on a QB
    # row exist purely for the odd trick play, and should stay empty unless
    # you deliberately project one.
    "QB": {"Y/C": 4.50},
}


def seed_inputs(p, h, pos, scale=None):
    """Starting values from 3-yr weighted history, so the sheet is usable
    before you touch it and you only spend judgment where you disagree."""
    out = {}
    sc = scale or {}
    # A QB with two career trick-play targets carries a real but unrepeatable
    # receiving share. Left in, it puts a catch rate and receiving yards on
    # every QB row, which reads as a projection rather than the noise it is.
    skip = ({"Tgt %", "Rec TD %"} if pos == "QB"
            else {"Pass %"})   # see seed_scale - gadget throws aren't a role
    for col, key in SEED_KEYS.items():
        if col in skip:
            continue
        v = f(p.get(key))
        if v:
            out[col] = round(v * sc.get(col, 1.0), 4)
    if pos != "QB" and f(p.get("catch_pct_w")):
        out["Catch %"] = round(f(p.get("catch_pct_w")), 4)
    for col, key, lo, hi in (("Y/C", "ypc_3y", 2.0, 7.0),
                             ("Y/R", "ypr_3y", 4.0, 20.0)):
        if pos == "QB" and col == "Y/R":
            continue               # see note above - QBs don't catch passes
        v = f(h.get(key))
        if lo <= v <= hi:          # ignore absurd small-sample rates
            out[col] = round(v, 2)

    # Anyone with no usable NFL rate history - rookies, and veterans whose
    # sample was too thin to trust - falls back to the position default rather
    # than being left blank. A blank rate silently produces zero yards, which
    # reads as a projection rather than a gap.
    for col, val in ROOKIE_RATES.get("RB" if pos == "FB" else pos, {}).items():
        out.setdefault(col, val)

    if pos == "QB":
        # Seeded from his own weighted rate over whatever seasons clear the
        # 20-attempt floor (1 or 2 years works, not just 3) - league average
        # (~2.2%) only for a QB with no usable sample at all.
        out["Int Rate"] = round(f(h.get("int_pct_3y")), 4) or 0.022
        # Seeded from his own 3-yr completion rate; league average for a
        # rookie or anyone too thin a sample to trust.
        out["Comp %"] = round(f(h.get("comp_pct_3y")), 4) or 0.650
    return out


def write_other(ws, row, pos):
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX
        ws.cell(row, C[name]).fill = OTHER
    ws.cell(row, C["Pos"], pos).font = Font(size=9, color="888888")
    ws.cell(row, C["Player"], f"Other {pos}s").font = Font(
        size=9, italic=True, color="888888")
    for name in INPUT_NAMES:
        ws.cell(row, C[name]).fill = INPUT
    ws.cell(row, C["Games"], 17)
    player_formulas(ws, row)


def write_totals(ws):
    """Running totals vs the team figure, so drift is visible immediately."""
    ws.cell(R_TOTAL, 1, "YOUR TOTAL").font = BOLD
    ws.cell(R_REF, 1, "TEAM").font = Font(size=9, color="666666")
    ws.cell(R_DIFF, 1, "DIFF").font = Font(size=9, color="666666")

    # Share columns: should add to 100%.
    for name in SHARE_INPUTS:
        col = L(C[name])
        c = ws.cell(R_TOTAL, C[name], f"=SUM({col}{R_FIRST}:{col}{R_LAST})")
        c.number_format = PCT1
        c.font = BOLD
        c.border = BOX
        cell = f"{col}{R_TOTAL}"
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"ABS({cell}-1)<=0.01"], fill=GOOD, stopIfTrue=True))
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"{cell}>1"], fill=OVER, stopIfTrue=True))
        ws.conditional_formatting.add(cell, FormulaRule(
            formula=[f"{cell}<1"], fill=WARN))

    for name in CALC_NAMES:
        col = L(C[name])
        c = ws.cell(R_TOTAL, C[name], f"=SUM({col}{R_FIRST}:{col}{R_LAST})")
        c.number_format = NUM1 if name in ("Pass TD", "Rush TD", "Rec TD",
                                           "Int", "STD", "Half",
                                           "PPR") else NUM0
        c.font = BOLD
        c.fill = CALC
        c.border = BOX

        cmp_ = COMPARE.get(name)
        if not cmp_:
            continue
        label, block = cmp_
        # "calc": the reference is another CALC column's own R_TOTAL cell
        # (Cmp checks against this team's Rec total) rather than a cell in
        # the fixed team-control block.
        ref = (f"{L(C[label])}{R_TOTAL}" if block == "calc"
               else t1(label) if block == 1 else t2(label))
        r = ws.cell(R_REF, C[name], f"={ref}")
        r.number_format = c.number_format
        r.font = Font(size=9, color="666666")
        d = ws.cell(R_DIFF, C[name], f"={col}{R_TOTAL}-{ref}")
        d.number_format = c.number_format
        d.font = Font(size=9, color="666666")
        # Yardage is a reference, not a cap - flag only a big gap.
        tol = 0.08 if "Yds" in name else 0.02
        dcell = f"{col}{R_DIFF}"
        ws.conditional_formatting.add(dcell, FormulaRule(
            formula=[f"AND({ref}>0,ABS({dcell}/{ref})<={tol})"],
            fill=GOOD, stopIfTrue=True))
        ws.conditional_formatting.add(dcell, FormulaRule(
            formula=[f"AND({ref}>0,ABS({dcell}/{ref})>{tol})"], fill=WARN))

    ws.cell(R_DIFF + 2, 2,
            "Share columns should total 100%. Attempts/targets/TDs should "
            "match TEAM closely. Yards are a guideline - within ~8% is fine."
            ).font = SMALL


def build_team_tab(ws, team, players, totals, vegas, rush_td_rate, hist,
                   vac, coach, prior_players, prior_totals, last_actual):
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = ws.cell(row=R_FIRST, column=3)
    ws.cell(R_TITLE, 1, f"{team}  -  {SEASON}").font = Font(
        bold=True, size=15, color="2F4F6F")

    team_block(ws, team, totals, vegas, rush_td_rate, prior_totals,
               last_actual)

    tgt_gone, rush_gone = vac
    note = (f"{tgt_gone*100:.0f}% of targets and {rush_gone*100:.0f}% of "
            f"carries left this roster.")
    ws.cell(R_NOTE, 1, "NOTES").font = BOLD
    ws.cell(R_NOTE, 2, note + ("  " + coach if coach else "")
            ).font = Font(size=9, color="A0522D")

    write_header(ws)

    by_pos = defaultdict(list)
    for p in players:
        by_pos["RB" if p["pos"] == "FB" else p["pos"]].append(p)
    for v in by_pos.values():
        v.sort(key=lambda x: i_(x["depth"], 99))

    # Build the full visible pool first so the seed scaling knows the
    # denominator before any row is written.
    visible = []
    for pos, n in SLOTS:
        visible.extend([p for p in by_pos.get(pos, []) if p["status"] != "OUT"][:n])
    scale = seed_scale(visible)

    row = R_FIRST
    for pos, n in SLOTS:
        pool = [p for p in by_pos.get(pos, []) if p["status"] != "OUT"][:n]
        for k in range(n):
            write_player(ws, row, pos, pool[k] if k < len(pool) else None,
                         hist, prior_players, team, True, scale)
            if (row - R_FIRST) % 2:
                for nm, _ in IDENT:
                    ws.cell(row, C[nm]).fill = BAND
            row += 1
        write_other(ws, row, pos)
        row += 1

    write_totals(ws)


def build_settings(ws):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 62
    ws.cell(1, 1, "SETTINGS").font = Font(bold=True, size=14, color="2F4F6F")
    for r, label, val, note in [
            (3, "Games in season", 17, ""),
            (4, "Target rate", 0.954,
             "targets per pass attempt - the gap is throwaways/spikes/bats"),
            (6, "SCORING", None, "one definition, used by all three columns"),
            (7, "Pts / rec yard", 0.1, ""),
            (8, "Pts / rec TD", 6, ""),
            (9, "Pts / reception (Half)", 0.5, ""),
            (10, "Pts / rush yard", 0.1, ""),
            (11, "Pts / rush TD", 6, ""),
            (12, "Pts / pass yard", 0.04, ""),
            (13, "Pts / pass TD", 4, ""),
            (14, "Pts / INT", -2, "negative"),
            (15, "Pts / reception (PPR)", 1.0, "")]:
        ws.cell(r, 1, label).font = BOLD
        if val is not None:
            c = ws.cell(r, 2, val)
            c.fill = INPUT
            c.number_format = "0.000" if isinstance(val, float) else NUM0
        ws.cell(r, 3, note).font = SMALL


def build_start_here(ws, vegas_ok):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 96
    ws.cell(2, 2, f"{SEASON} PROJECTIONS - v3 (market share)").font = Font(
        bold=True, size=18, color="2F4F6F")
    blocks = [
        ("How it works", [
            "You set two kinds of number per player:",
            "   SHARE   his % of the team's pass attempts / carries / targets / TDs",
            "   RATE    his yards per carry, catch rate, yards per catch",
            "Everything else is calculated. Nothing has to be balanced by hand.",
        ]),
        ("The team block up top drives everything", [
            "   Team Plays x Pass Play %  -> pass attempts and rush attempts",
            "   Total TD x Rush TD %      -> rushing TDs and passing TDs",
            "Both are editable. Change the play total or the pass rate and every",
            "player's opportunity moves with it.",
        ]),
        ("Where the team numbers come from", [
            "   Total TD    Vegas implied points, from live betting lines.",
            "               Cross-checked against Sharp Football Analysis:",
            "               r=0.9997, average difference 0.04 pts/game."
            if vegas_ok else
            "   Total TD    historical (run fetch_odds.py for the Vegas version)",
            "   Plays,      3-yr team history regressed toward league average.",
            "   Pass rate   Deliberately NOT from Vegas - yards-per-point varies",
            "               too much between teams to project yardage from points.",
            "   Rush TD %   that team's own 3-yr split (league average 38%).",
        ]),
        ("Yards are a guideline, not a cap", [
            "The ~Pass Yds / ~Rush Yds / ~Rec Yds figures are historical",
            "reference points. Your totals do NOT have to match them - the DIFF",
            "row flags a gap over ~8% so you can decide whether you meant it.",
            "",
            "Passing yards are built bottom-up: a QB's passing yards are his",
            "share of what his receivers actually catch. That's why there's no",
            "Y/A input for the QB - it would over-determine the answer.",
        ]),
        ("TD share is separate from volume share, on purpose", [
            "A goal-line back can own 35% of a team's rushing TDs on 8% of its",
            "carries. A slot receiver can be the reverse. Rush TD % and Rec TD %",
            "are their own inputs, seeded from each player's own 3-yr TD share.",
        ]),
        ("Reading the bottom rows", [
            "   YOUR TOTAL   what your inputs add up to",
            "   TEAM         the team figure it's compared against",
            "   DIFF         the gap  (green = close, amber = worth a look)",
            "Share columns should total 100%: green at 100%, red over, amber under.",
        ]),
        ("Rankings", [
            "Cross-team positional rankings would need formulas scanning all 32",
            "tabs on every keystroke, which is what made earlier versions slow.",
            "Run  python build_rankings.py  instead - it reads this file and",
            "writes ranked QB/RB/WR/TE tabs with all three scoring formats.",
        ]),
        ("Rebuilding without losing work", [
            "   python build_workbook_v3.py --merge    keeps every input you set",
            "A plain rebuild refuses once Excel has saved this file.",
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
    ap.add_argument("--out", default="my_projections_v3.xlsx")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-seed", action="store_true")
    args = ap.parse_args()

    out_path = os.path.join(HERE, args.out)
    if os.path.exists(out_path) and looks_edited(out_path) \
            and not (args.force or args.merge):
        sys.exit(f"\n{args.out} has your edits in it.\n"
                 f"  keep them : python build_workbook_v3.py --merge\n"
                 f"  discard   : python build_workbook_v3.py --force\n")

    prior_players, prior_totals = ({}, {})
    if args.merge and os.path.exists(out_path):
        prior_players, prior_totals = read_existing(out_path)
        n_edited = sum(1 for v in prior_players.values() if v.get("counted"))
        print(f"  read {n_edited} existing player edits to merge "
              f"({len(prior_players)} rows tracked for blank-preservation)")

    shares = read_csv("player_shares.csv")
    totals = {r["team"]: r for r in read_csv(f"team_totals_{SEASON}.csv")}
    hist = {names.normalize(r["player"]): r
            for r in read_csv(f"player_history_{SEASON}.csv")}
    vac_rows = read_csv(f"vacated_{SEASON}.csv")
    actual = {r["team"]: r for r in read_csv("team_totals_history.csv")
              if int(r["season"]) == LAST}
    vegas_rows = read_csv(f"vegas_team_totals_{SEASON}.csv", required=False)

    vegas = {r["team"]: f(r["offensive_td"]) for r in vegas_rows}
    if vegas:
        print(f"  Vegas team TDs for {len(vegas)} teams")
    else:
        print("  no vegas_team_totals found - falling back to historical TDs")

    # Per-team rush TD rate from that team's own 3-yr history.
    rush_rate = {}
    for team, t in totals.items():
        ptd, rtd = f(t.get("pass_td")), f(t.get("rush_td"))
        rush_rate[team] = rtd / (ptd + rtd) if (ptd + rtd) else 0.382

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
    build_start_here(wb.create_sheet("Start Here"), bool(vegas))
    for team in TEAMS:
        t = totals.get(team, {})
        vteam = vegas.get(team) or (f(t.get("pass_td")) + f(t.get("rush_td")))
        build_team_tab(wb.create_sheet(team), team, by_team.get(team, []),
                       t, vteam, rush_rate.get(team, 0.382), hist,
                       vac[team], coaching.get(team),
                       prior_players or None, prior_totals.get(team),
                       actual.get(team, {}))
    build_settings(wb.create_sheet("Settings"))

    validate(wb)

    if os.path.exists(out_path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = out_path.replace(".xlsx", f".backup-{stamp}.xlsx")
        try:
            os.replace(out_path, backup)
        except PermissionError:
            sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n")
        print(f"  previous copy saved as {os.path.basename(backup)}")
    try:
        wb.save(out_path)
    except PermissionError:
        sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n")

    print(f"\nWrote {args.out}")
    print(f"  32 team tabs + Start Here + Settings")
    if prior_players:
        print(f"  {len(prior_players)} player edits carried over")
    print(f"\n  Set share % and rates; attempts, yards, TDs and points calculate.")
    print(f"  Run build_rankings.py for cross-team positional rankings.")


if __name__ == "__main__":
    sys.exit(main())
