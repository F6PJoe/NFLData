#!/usr/bin/env python3
"""Build my_projections.xlsx - the manual usage workbook.

Structure
---------
  32 team tabs (ARI..WAS)   where you work. Team control totals on top, the
                            vacated-share block under them, players below
                            allocating that volume, share totals in the footer.
  4 position tabs           QB/RB/WR/TE - every player at that position across
                            all 32 teams, LIVE formula references into the team
                            tabs, so a usage edit updates them instantly.
  Vacated                   what walked out the door per team, and where it went
  Settings                  games, scoring, target rate

Every formula lives in the workbook, not in Python, so edits recalc as you type.
Blue cells are inputs. Grey cells are computed - don't type in them.

The share footer is the whole trick: if a team's target shares sum to 100%,
player targets sum to team targets by construction. Nothing to reconcile.

Usage:
    python build_workbook.py                  # seed inputs with weighted history
    python build_workbook.py --blank-usage    # leave inputs empty
"""

import argparse
import csv
import datetime
import os
import sys
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import names
from teams import TEAMS

HERE = os.path.dirname(os.path.abspath(__file__))
SEASON = 2026
HIST = [SEASON - 1, SEASON - 2, SEASON - 3]

# Visible slots per position, plus a trailing "Other" row that absorbs the
# residual share so 100% is always reachable without carrying 15 WRs.
SLOTS = [("QB", 3), ("RB", 6), ("WR", 8), ("TE", 4)]

# ── styling ────────────────────────────────────────────────────────────────
INPUT = PatternFill("solid", fgColor="DCE9F7")     # blue  = type here
CALC = PatternFill("solid", fgColor="F2F2F2")      # grey  = formula
REF = PatternFill("solid", fgColor="FFF6E5")       # cream = historical reference
HDR = PatternFill("solid", fgColor="2F4F6F")
SUBHDR = PatternFill("solid", fgColor="8EA9C1")
OTHER = PatternFill("solid", fgColor="EDEDED")

HDR_FONT = Font(color="FFFFFF", bold=True, size=11)
BOLD = Font(bold=True)
SMALL = Font(size=9, color="666666")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

PCT = "0.0%"
NUM1 = "0.0"
NUM2 = "0.00"
NUM0 = "0"


BAD_FORMULA_PATTERNS = ("*/", "/*", "**", "//", "+*", "*+", "+/", "-/",
                        "(*", "(/", "*)", "/)", "$None", "None", ",,")


def validate_formulas(wb):
    """Fail loudly on malformed formulas instead of shipping a broken file.

    Excel reports a corrupt workbook rather than a bad cell, so a single stray
    operator is genuinely hard to trace from the error. This caught a real one:
    removing a factor from a formula left `L22*O22*/SUMPRODUCT(...)` behind,
    and Excel refused to open the file at all.
    """
    problems = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not isinstance(v, str) or not v.startswith("="):
                    continue
                why = None
                for pat in BAD_FORMULA_PATTERNS:
                    if pat in v:
                        why = f"contains {pat!r}"
                        break
                if why is None and v.count("(") != v.count(")"):
                    why = "unbalanced parentheses"
                if why:
                    problems.append((ws.title, cell.coordinate, why, v[:70]))
    if problems:
        print(f"\n{len(problems)} MALFORMED FORMULA(S) - refusing to save:\n")
        for sheet, coord, why, formula in problems[:8]:
            print(f"  {sheet}!{coord}  {why}\n      {formula}")
        sys.exit("\nFix build_workbook.py and re-run. No file was written.")


def looks_edited(path):
    """True if Excel has opened and saved this workbook.

    openpyxl writes formulas but no cached results. Excel writes both. So a
    populated cached value on a formula cell means a human has been in here.

    Only OUTPUT columns count. Input cells hold values we wrote ourselves, so
    checking those would flag a freshly generated file as edited.
    """
    wb = None
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=True)
        cols = [C[name] for name in ("Half PPR", "Targets", "Rush Att")]
        for sheet in TEAMS[:6]:
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            for row in ws.iter_rows(min_row=R_FIRST, max_row=R_LAST,
                                    min_col=min(cols), max_col=max(cols)):
                for cell in row:
                    if cell.column in cols and isinstance(
                            cell.value, (int, float)) and cell.value:
                        return True
    except Exception:
        return False
    finally:
        # read_only mode keeps the file handle open; without this the
        # subsequent os.replace fails on Windows with WinError 32.
        if wb is not None:
            wb.close()
    return False


def read_existing(path):
    """Pull hand-entered inputs out of an existing workbook.

    Player edits are keyed by (normalized name, TEAM) - deliberately not by
    name alone. A usage share is a share OF A SPECIFIC OFFENSE, so when a
    player changes teams his old number is meaningless on the new roster and
    must not follow him. That's the same rule the whole model runs on; the
    merge would be lying if it made an exception here.
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
            vals = {}
            for label, _ in TOTALS:
                v = ws.cell(R_TOT_VAL, T[label]).value
                if isinstance(v, (int, float)):
                    vals[label] = v
            teams[team] = vals
            for row in range(R_FIRST, R_LAST + 1):
                name = ws.cell(row, C["Player"]).value
                if not name or not isinstance(name, str):
                    continue
                edits = {}
                for col in INPUT_COLS:
                    v = ws.cell(row, C[col]).value
                    if isinstance(v, (int, float)):
                        edits[col] = v
                if name.startswith("Other ") and name.endswith("s"):
                    continue          # residual bucket, not a real player
                if edits:
                    players[(names.normalize(name), team)] = {
                        "edits": edits, "display": name,
                        "depth": ws.cell(row, C["Dep"]).value}
    except Exception as exc:
        print(f"  could not read existing workbook ({exc}); building fresh")
        return {}, {}
    finally:
        if wb is not None:
            wb.close()
    return players, teams


def read_csv(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        sys.exit(f"Missing {name}. Run the build steps first.")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def f(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ── team tab layout ─────────────────────────────────────────────────────────
# Row map (1-indexed). Kept as constants so the position tabs can reference
# exact cells without guessing.
R_TITLE = 1
R_TOT_HDR = 3
R_TOT_LBL = 4
R_TOT_VAL = 5
R_HIST = 7          # 3-year team history block (header + 3 rows)
R_VAC = 12          # who left
R_IN = 13           # who arrived
R_COACH = 14        # coaching change note
R_TBL_HDR = 16
R_FIRST = 17
# Fixed block size: visible slots plus one 'Other' row per position.
R_LAST = R_FIRST + sum(n + 1 for _, n in SLOTS) - 1

COLS = [
    ("Pos", 6), ("Player", 24), ("Dep", 5), ("Age", 5), ("Status", 11),
    (f"{HIST[2]} Tgt%", 9), (f"{HIST[1]} Tgt%", 9), (f"{HIST[0]} Tgt%", 9),
    (f"{HIST[0]} Rush%", 10),
    ("Games", 7), ("Pass %", 9), ("Tgt %", 9), ("Rush %", 9), ("Catch %", 9),
    ("Rec Eff x", 10), ("Rush Eff x", 10), ("RZ Tgt x", 9), ("RZ Rush x", 10),
    ("Pass Yds", 9), ("Pass TD", 8), ("Int", 7),
    ("Targets", 9), ("Rec", 7), ("Rec Yds", 9), ("Yds/Rec", 9), ("Rec TD", 8),
    ("Rush Att", 9), ("Rush Yds", 9), ("Yds/Car", 9), ("Rush TD", 8),
    ("Half PPR", 10),
]
C = {name: i + 1 for i, (name, _) in enumerate(COLS)}
INPUT_COLS = ["Games", "Pass %", "Tgt %", "Rush %", "Catch %", "Rec Eff x",
              "Rush Eff x", "RZ Tgt x", "RZ Rush x"]
REF_COLS = [f"{HIST[2]} Tgt%", f"{HIST[1]} Tgt%", f"{HIST[0]} Tgt%",
            f"{HIST[0]} Rush%"]
OUT_COLS = ["Pass Yds", "Pass TD", "Int", "Targets", "Rec", "Rec Yds",
            "Yds/Rec", "Rec TD", "Rush Att", "Rush Yds", "Yds/Car",
            "Rush TD", "Half PPR"]

# Team totals block: (label, format). Column index derived from order.
TOTALS = [
    ("Games", NUM0), ("Plays/G", NUM1), ("Plays", NUM0), ("Pass Rate", PCT),
    ("Pass Att", NUM0), ("Targets", NUM0), ("Rush Att", NUM0),
    ("Pass Yds", NUM0), ("Pass TD", NUM1), ("Int", NUM1),
    ("Rush Yds", NUM0), ("Rush TD", NUM1),
]
T = {name: i + 2 for i, (name, _) in enumerate(TOTALS)}   # start at col B


def seed_scale(pool):
    """Scale factors that make a team's seeded shares add to 100%.

    The underlying history is a per-game rate - what a player commanded in the
    games he actually played. Those don't sum to 100% across a roster (each is
    measured over a different number of games), and raw they came out at
    111-159% of targets and 117-219% of carries on every single team. Scaling
    each team's pool to 1.0 keeps the relative ordering the history and role
    priors produced, while handing you a sheet that opens BALANCED instead of
    one you have to cut down before you can start.
    """
    scale = {}
    for metric, col in (("tgt_share_w", "Tgt %"), ("rush_share_w", "Rush %"),
                        ("pass_share_w", "Pass %")):
        total = sum(f(p.get(metric)) for p in pool)
        scale[col] = (1.0 / total) if total > 0 else 1.0
    return scale


def build_team_tab(ws, team, players, totals, vacated, prefill,
                   target_rate, history, arrivals, coaching, prior=None,
                   written=None):
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = ws.cell(row=R_FIRST, column=1)

    ws.cell(R_TITLE, 1, f"{team}  -  {SEASON} projections").font = Font(
        bold=True, size=15, color="2F4F6F")

    # ── team control totals ────────────────────────────────────────────────
    ws.cell(R_TOT_HDR, 1, "TEAM TOTALS").font = BOLD
    ws.cell(R_TOT_HDR, 3,
            "blue = edit; everything below divides these up").font = SMALL
    for label, fmt in TOTALS:
        col = T[label]
        h = ws.cell(R_TOT_LBL, col, label)
        h.font = Font(bold=True, size=9, color="FFFFFF")
        h.fill = SUBHDR
        h.alignment = Alignment(horizontal="center")
        h.border = BOX
        c = ws.cell(R_TOT_VAL, col)
        c.number_format = fmt
        c.border = BOX
        c.alignment = Alignment(horizontal="center")

    g, pg = T["Games"], T["Plays/G"]
    L = get_column_letter
    ws.cell(R_TOT_VAL, g, 17).fill = INPUT
    ws.cell(R_TOT_VAL, pg, round(f(totals.get("plays_per_game")), 1)).fill = INPUT
    ws.cell(R_TOT_VAL, T["Plays"],
            f"={L(pg)}{R_TOT_VAL}*{L(g)}{R_TOT_VAL}").fill = CALC
    ws.cell(R_TOT_VAL, T["Pass Rate"], round(f(totals.get("pass_rate")), 4)).fill = INPUT
    ws.cell(R_TOT_VAL, T["Pass Att"], round(f(totals.get("pass_att")))).fill = INPUT
    # Targets < pass attempts: throwaways, spikes and batted balls never reach
    # a receiver. Historical share denominators are targets, so match them.
    ws.cell(R_TOT_VAL, T["Targets"],
            f"=ROUND({L(T['Pass Att'])}{R_TOT_VAL}*Settings!$B$4,0)").fill = CALC
    ws.cell(R_TOT_VAL, T["Rush Att"], round(f(totals.get("rush_att")))).fill = INPUT
    ws.cell(R_TOT_VAL, T["Pass Yds"], round(f(totals.get("pass_yds")))).fill = INPUT
    ws.cell(R_TOT_VAL, T["Pass TD"], round(f(totals.get("pass_td")), 1)).fill = INPUT
    ws.cell(R_TOT_VAL, T["Int"], round(f(totals.get("interceptions")), 1)).fill = INPUT
    ws.cell(R_TOT_VAL, T["Rush Yds"], round(f(totals.get("rush_yds")))).fill = INPUT
    ws.cell(R_TOT_VAL, T["Rush TD"], round(f(totals.get("rush_td")), 1)).fill = INPUT

    # ── 3-year history, so the projection above has visible context ────────
    ws.cell(R_HIST, 1, "LAST 3 YEARS").font = BOLD
    hist_cols = [("Season", 8), ("Plays", 7), ("Plays/G", 8), ("Pass Rate", 9),
                 ("Pass Att", 8), ("Rush Att", 8), ("Pass Yds", 8),
                 ("Rush Yds", 8), ("Pass TD", 7), ("Rush TD", 7), ("Y/A", 6),
                 ("Y/C", 6)]
    for i, (label, _) in enumerate(hist_cols):
        h = ws.cell(R_HIST, 2 + i, label)
        h.font = Font(bold=True, size=8, color="FFFFFF")
        h.fill = SUBHDR
        h.alignment = Alignment(horizontal="center")
        h.border = BOX
    for r_off, yr in enumerate(sorted(HIST), start=1):
        rec = history.get(str(yr), {})
        vals = [yr, rec.get("plays"), rec.get("plays_per_game"),
                rec.get("pass_rate"), rec.get("pass_att"), rec.get("rush_att"),
                rec.get("pass_yds"), rec.get("rush_yds"), rec.get("pass_td"),
                rec.get("rush_td"), rec.get("ypa"), rec.get("ypc")]
        fmts = [NUM0, NUM0, NUM1, PCT, NUM0, NUM0, NUM0, NUM0, NUM0, NUM0,
                NUM1, NUM1]
        for i, (v, fmt) in enumerate(zip(vals, fmts)):
            c = ws.cell(R_HIST + r_off, 2 + i, f(v) if v not in (None, "") else None)
            c.number_format = fmt
            c.fill = REF
            c.font = Font(size=9, color="7A6A55")
            c.border = BOX
            c.alignment = Alignment(horizontal="center")

    # ── roster churn ───────────────────────────────────────────────────────
    tgt_gone, rush_gone, leavers = vacated
    ws.cell(R_VAC, 1, "OUT").font = Font(bold=True, color="A0522D")
    msg = (f"{tgt_gone*100:.0f}% of targets and {rush_gone*100:.0f}% of carries "
           f"left. Share is team-relative - it does NOT follow the player.")
    ws.cell(R_VAC, 2, msg).font = Font(size=9, color="A0522D")
    if leavers:
        ws.cell(R_VAC, 8, ", ".join(
            f"{n} ({t*100:.0f}t/{r*100:.0f}r -> {w})"
            for n, t, r, w in leavers[:5])).font = SMALL

    ws.cell(R_IN, 1, "IN").font = Font(bold=True, color="1F6FB5")
    if arrivals:
        ws.cell(R_IN, 2, f"{len(arrivals)} new: " + ", ".join(
            f"{a['player']} ({a['pos']}, from {a['prior_team']}"
            f"{f' - had {f(a[f'tgt_share_{HIST[0]}'])*100:.0f}% there' if f(a.get(f'tgt_share_{HIST[0]}')) else ''})"
            for a in arrivals[:5])).font = Font(size=9, color="1F6FB5")
    else:
        ws.cell(R_IN, 2, "no incoming players with prior usage").font = SMALL

    note = coaching.get(team)
    ws.cell(R_COACH, 1, "STAFF").font = BOLD
    ws.cell(R_COACH, 2, note or
            "no coaching change recorded - add one in manual/coaching_changes.csv"
            ).font = Font(size=9, bold=bool(note),
                          color="B22222" if note else "999999")

    # ── player table ───────────────────────────────────────────────────────
    for name, width in COLS:
        col = C[name]
        ws.column_dimensions[get_column_letter(col)].width = width
        h = ws.cell(R_TBL_HDR, col, name)
        h.font = Font(bold=True, size=9, color="FFFFFF")
        h.fill = HDR
        h.alignment = Alignment(horizontal="center", wrap_text=True)
        h.border = BOX

    by_pos = defaultdict(list)
    for p in players:
        by_pos[p["pos"] if p["pos"] != "FB" else "RB"].append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: int(p["depth"]))

    pool = []
    for pos, n_slots in SLOTS:
        pool.extend([p for p in by_pos.get(pos, []) if p["status"] != "OUT"]
                    [:n_slots])
    scale = seed_scale(pool)
    # QB pass share has to be solved for the room, not per row: a QB1 whose
    # own history is above the 92% floor (Bo Nix at 99.7%) plus fixed backup
    # floors overshoots 100%. Give QB1 the larger of history and the floor,
    # then split what's left.
    qbs = sorted([p for p in by_pos.get("QB", []) if p["status"] != "OUT"],
                 key=lambda p: int(p["depth"]))[:dict(SLOTS)["QB"]]
    qb1 = min(max(f(qbs[0].get("pass_share_w")), 0.92), 0.97) if qbs else 0.0
    rest = max(0.0, 1.0 - qb1)
    scale["_qb_pass"] = {1: qb1, 2: round(rest * 0.85, 4),
                         3: round(rest * 0.15, 4)}

    row = R_FIRST
    pos_rows = {}
    for pos, n_slots in SLOTS:
        start = row
        pool = [p for p in by_pos.get(pos, []) if p["status"] != "OUT"][:n_slots]
        for i in range(n_slots):
            p = pool[i] if i < len(pool) else None
            if p is not None and written is not None:
                written.append((p["player"], team))
            write_player_row(ws, row, team, pos, p, prefill, prior, scale)
            row += 1
        # "Other" absorbs residual share so 100% is reachable without
        # carrying every camp body on the roster.
        write_other_row(ws, row, pos)
        row += 1
        pos_rows[pos] = (start, row - 1)

    # ── share totals footer ────────────────────────────────────────────────
    foot = row + 1
    ws.cell(foot, 2, "SHARE TOTALS - must equal 100%").font = BOLD
    ws.cell(foot, 5, "each column is a share of this team's season total - "
                     "it must add to 100%").font = SMALL
    first, last = R_FIRST, row - 1
    gcol = get_column_letter(C["Games"])
    tgames = f"${get_column_letter(T['Games'])}${R_TOT_VAL}"
    for col_name in ("Pass %", "Tgt %", "Rush %"):
        col = get_column_letter(C[col_name])
        # Shares are per-game rates, so the constraint is on share x
        # availability, not on the raw share column.
        c = ws.cell(foot, C[col_name], f"=SUM({col}{first}:{col}{last})")
        c.number_format = PCT
        c.font = BOLD
        c.border = BOX
        ws.conditional_formatting.add(
            f"{col}{foot}",
            CellIsRule(operator="between", formula=["0.999", "1.001"],
                       # 8-digit ARGB required here - a bare 6-digit hex
                       # serializes with alpha=00 (invisible) inside a dxf,
                       # even though the rule fires correctly. Confirmed by
                       # inspecting the saved XML.
                       fill=PatternFill("solid", fgColor="FFC6EFCE")))
        ws.conditional_formatting.add(
            f"{col}{foot}",
            CellIsRule(operator="notBetween", formula=["0.999", "1.001"],
                       fill=PatternFill("solid", fgColor="FFFFC7CE")))
    for col_name in OUT_COLS:
        col = get_column_letter(C[col_name])
        c = ws.cell(foot, C[col_name], f"=SUM({col}{first}:{col}{last})")
        c.number_format = NUM1 if "TD" in col_name or "PPR" in col_name else NUM0
        c.font = BOLD
        c.fill = CALC
        c.border = BOX
    ws.cell(foot + 2, 2,
            "Green = balanced. Red = your shares don't add to 100%; "
            "player totals won't match the team totals until they do."
            ).font = SMALL
    return pos_rows


def write_player_row(ws, row, team, pos, p, prefill, prior=None, scale=None):
    V = R_TOT_VAL
    L = get_column_letter
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX

    ws.cell(row, C["Pos"], pos).font = Font(bold=True, size=9)
    if p is None:
        ws.cell(row, C["Player"], "").fill = INPUT
        for name in INPUT_COLS:
            ws.cell(row, C[name]).fill = INPUT
        return

    ws.cell(row, C["Player"], p["player"])
    ws.cell(row, C["Dep"], int(p["depth"])).alignment = Alignment(horizontal="center")
    ws.cell(row, C["Age"], p["age"]).alignment = Alignment(horizontal="center")
    st = ws.cell(row, C["Status"], p["status"])
    st.font = Font(size=8, color="B22222" if p["status"] != "ACT" else "666666")

    # historical reference (read-only)
    for yr, key in ((HIST[2], f"tgt_share_{HIST[2]}"),
                    (HIST[1], f"tgt_share_{HIST[1]}"),
                    (HIST[0], f"tgt_share_{HIST[0]}")):
        c = ws.cell(row, C[f"{yr} Tgt%"], f(p.get(key)) or None)
        c.number_format = PCT
        c.fill = REF
        c.font = Font(size=9, color="7A6A55")
    c = ws.cell(row, C[f"{HIST[0]} Rush%"], f(p.get(f"rush_share_{HIST[0]}")) or None)
    c.number_format = PCT
    c.fill = REF
    c.font = Font(size=9, color="7A6A55")

    # inputs
    seed = (lambda v: (v or None) if prefill else None)
    sc = (lambda col: (scale or {}).get(col, 1.0))

    # QB pass share is the one cell where depth chart beats history. A backup
    # who started six games carries a 40% share that will never repeat, while
    # a real QB1 takes ~90-95% of attempts almost deterministically. Seed QB1
    # from role and let history only raise it. Skill positions stay historical.
    pass_seed = round(f(p.get("pass_share_w")), 4)
    if pos == "QB" and prefill:
        depth = int(p["depth"]) if str(p.get("depth", "")).isdigit() else 9
        # Solved across the whole QB room in seed_scale so the slots add to
        # 100% — a QB1 whose own history sits above the floor (Bo Nix, 99.7%)
        # plus fixed backup floors would otherwise overshoot.
        pass_seed = (scale or {}).get("_qb_pass", {}).get(depth, 0.0)
    elif pos != "QB":
        # A receiver who threw two trick-play passes in three years carries a
        # real but unrepeatable pass share. Left in, those sum to ~3% a team
        # and push the passing column past 100%. Type one in if you actually
        # want a gadget throw projected.
        pass_seed = 0.0

    vals = {
        "Games": 17 if prefill else None,
        "Pass %": ((pass_seed or None) if (prefill and pos == "QB")
                   else seed(pass_seed)),
        "Tgt %": seed(round(f(p.get("tgt_share_w")) * sc("Tgt %"), 4)),
        "Rush %": seed(round(f(p.get("rush_share_w")) * sc("Rush %"), 4)),
        # A QB with four trick-play targets has a catch rate; it's noise.
        "Catch %": (None if pos == "QB"
                    else round(f(p.get("catch_pct_w")), 4) or None),
        "Rec Eff x": round(f(p.get("ypt_mult_w"), 1.0), 2) or None,
        "Rush Eff x": round(f(p.get("ypc_mult_w"), 1.0), 2) or None,
        "RZ Tgt x": round(f(p.get("rz_tgt_ratio"), 1.0), 2) or None,
        "RZ Rush x": round(f(p.get("rz_rush_ratio"), 1.0), 2) or None,
    }
    fmts = {"Pass %": PCT, "Tgt %": PCT, "Rush %": PCT, "Catch %": PCT,
            "Games": NUM0, "Rec Eff x": "0.00", "Rush Eff x": "0.00",
            "RZ Tgt x": "0.00", "RZ Rush x": "0.00"}
    # A previous edit for this exact (player, team) wins over any seed.
    restored = None
    if prior:
        restored = prior.get((names.normalize(p["player"]), team))
        if restored:
            vals.update(restored["edits"])

    for name in INPUT_COLS:
        c = ws.cell(row, C[name], vals[name])
        c.fill = INPUT
        c.number_format = fmts[name]

    if restored:
        old_depth = restored.get("depth")
        new_depth = int(p["depth"]) if str(p["depth"]).isdigit() else None
        if old_depth and new_depth and old_depth != new_depth:
            # Edit kept, but the depth chart moved under it - worth a look.
            n = ws.cell(row, C["Status"], f"depth {old_depth} -> {new_depth}")
            n.font = Font(size=8, color="B8860B", italic=True)

    basis = p.get("seed_basis", "")
    if basis.startswith("role average"):
        prior_team = p.get("prior_team")
        note = f"role avg (from {prior_team})" if prior_team else "role avg (rookie)"
        n = ws.cell(row, C["Status"], note)
        n.font = Font(size=8, color="1F6FB5", italic=True)

    write_formulas(ws, row)


def write_other_row(ws, row, pos):
    for name, _ in COLS:
        ws.cell(row, C[name]).border = BOX
        ws.cell(row, C[name]).fill = OTHER
    ws.cell(row, C["Pos"], pos).font = Font(size=9, color="888888")
    ws.cell(row, C["Player"], f"Other {pos}s").font = Font(
        size=9, italic=True, color="888888")
    for name in INPUT_COLS:
        ws.cell(row, C[name]).fill = INPUT
        ws.cell(row, C[name]).number_format = (
            PCT if "%" in name else NUM1 if name != "Games" else NUM0)
    write_formulas(ws, row)


def write_formulas(ws, row, first=R_FIRST, last=R_LAST):
    """The arithmetic. Every output is a SHARE of a team control total.

    Yards used to be built bottom-up (targets x catch% x yards-per-catch),
    which meant nothing forced them to add up to the team's projected yardage
    -- they missed by ~550 yards a team, and Dallas overshot its rushing total
    by 1,390. Yards are now a normalized share of the team total, exactly like
    targets and carries:

        Rec Yds = (Tgt% x Rec Eff x x Games)
                  / SUM(all players' Tgt% x Rec Eff x x Games)
                  x Team Pass Yds

    so the column always sums to the team total no matter what anyone types.
    'Rec Eff x' is yards per target RELATIVE to the team average: 1.00 means
    he earns yards in proportion to his targets, 1.30 means a deep threat.
    Yds/Rec then falls out as OUTPUT, for eyeballing - it isn't an input,
    because setting both it and a target share over-determines the answer.
    """
    V = R_TOT_VAL
    L = get_column_letter
    tgt_pct = f"{L(C['Tgt %'])}{row}"
    rush_pct = f"{L(C['Rush %'])}{row}"
    team_tgt = f"${L(T['Targets'])}${V}"
    team_rush = f"${L(T['Rush Att'])}${V}"
    team_ptd = f"${L(T['Pass TD'])}${V}"
    team_rtd = f"${L(T['Rush TD'])}${V}"

    pass_pct = f"{L(C['Pass %'])}{row}"
    team_pyds = f"${L(T['Pass Yds'])}${V}"
    team_int = f"${L(T['Int'])}${V}"
    # Shares are SEASON shares - "% of this team's targets for the year".
    # They sum to 100% and need no availability factor: if you expect a player
    # to miss time, that IS a smaller season share. An earlier version used
    # per-game "while active" rates here, which are unintuitive and sum to
    # 130-200% across a roster. The when-active rates survive as the cream
    # reference columns, where they belong.

    # Normalizers for the yardage split. Absolute refs so every row divides by
    # the same team-wide denominator.
    def norm(share_col, eff_col):
        s, e, g = L(C[share_col]), L(C[eff_col]), L(C["Games"])
        return (f"SUMPRODUCT(${s}${first}:${s}${last},"
                f"${e}${first}:${e}${last})")

    rec_norm = norm("Tgt %", "Rec Eff x")
    rush_norm = norm("Rush %", "Rush Eff x")
    # Touchdowns need the same normalization as yards. share x RZ-multiplier
    # only sums to the team total if the multipliers happen to average 1.00
    # across the roster, which they don't - ARI's rush TDs came out 26% over.
    rztd_norm = norm("Tgt %", "RZ Tgt x")
    rzrush_norm = norm("Rush %", "RZ Rush x")

    out = {
        # QB passing: share of the team's passing production. Blank for skill
        # players, so their passing output is simply zero.
        "Pass Yds": f"=IFERROR({pass_pct}*{team_pyds},0)",
        "Pass TD": f"=IFERROR({pass_pct}*{team_ptd},0)",
        "Int": f"=IFERROR({pass_pct}*{team_int},0)",
        "Targets": f"=IFERROR({tgt_pct}*{team_tgt},0)",
        "Rec": f"=IFERROR({L(C['Targets'])}{row}*{L(C['Catch %'])}{row},0)",
        # normalized share of the team's receiving yards -> always reconciles
        "Rec Yds": (f"=IFERROR({tgt_pct}*{L(C['Rec Eff x'])}{row}"
                    f"/{rec_norm}*${L(T['Pass Yds'])}${V},0)"),
        "Yds/Rec": (f"=IFERROR({L(C['Rec Yds'])}{row}/{L(C['Rec'])}{row},0)"),
        # TD from red-zone-weighted share of the TEAM's TDs, never from a
        # player's own prior TDs. RZ multiplier lets one usage input drive both.
        "Rec TD": (f"=IFERROR({tgt_pct}*{L(C['RZ Tgt x'])}{row}"
                   f"/{rztd_norm}*{team_ptd},0)"),
        "Rush Att": f"=IFERROR({rush_pct}*{team_rush},0)",
        "Rush Yds": (f"=IFERROR({rush_pct}*{L(C['Rush Eff x'])}{row}"
                     f"/{rush_norm}*${L(T['Rush Yds'])}${V},0)"),
        "Yds/Car": (f"=IFERROR({L(C['Rush Yds'])}{row}/{L(C['Rush Att'])}{row},0)"),
        "Rush TD": (f"=IFERROR({rush_pct}*{L(C['RZ Rush x'])}{row}"
                    f"/{rzrush_norm}*{team_rtd},0)"),
    }
    for name, formula in out.items():
        c = ws.cell(row, C[name], formula)
        c.fill = CALC
        c.number_format = (NUM2 if name in ("Yds/Rec", "Yds/Car")
                           else NUM1 if ("TD" in name or name == "Int")
                           else NUM0)

    pts = (f"={L(C['Rec Yds'])}{row}*Settings!$B$7"
           f"+{L(C['Rec TD'])}{row}*Settings!$B$8"
           f"+{L(C['Rec'])}{row}*Settings!$B$9"
           f"+{L(C['Rush Yds'])}{row}*Settings!$B$10"
           f"+{L(C['Rush TD'])}{row}*Settings!$B$11"
           f"+{L(C['Pass Yds'])}{row}*Settings!$B$12"
           f"+{L(C['Pass TD'])}{row}*Settings!$B$13"
           f"+{L(C['Int'])}{row}*Settings!$B$14")
    c = ws.cell(row, C["Half PPR"], pts)
    c.fill = CALC
    c.number_format = NUM1
    c.font = BOLD


def build_position_tab(ws, pos, team_rows):
    """Live references into every team tab - edits propagate instantly."""
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    # QBs get the passing block; skill positions don't need the empty columns.
    if pos == "QB":
        stats = ["Pass Yds", "Pass TD", "Int", "Rush Att", "Rush Yds",
                 "Rush TD", "Half PPR"]
        widths = [24, 7, 6, 9, 8, 7, 9, 9, 8, 10]
    else:
        stats = ["Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att", "Rush Yds",
                 "Rush TD", "Half PPR"]
        widths = [24, 7, 6, 9, 8, 9, 8, 9, 9, 8, 10]
    headers = ["Player", "Team", "Pos"] + stats
    ws.cell(1, 1, f"{pos} - all teams (live from the team tabs)").font = Font(
        bold=True, size=13, color="2F4F6F")
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(2, i, h)
        c.font = Font(bold=True, size=9, color="FFFFFF")
        c.fill = HDR
        c.alignment = Alignment(horizontal="center")
        c.border = BOX

    row = 3
    for team in TEAMS:
        start, end = team_rows[team][pos]
        for r in range(start, end + 1):
            ws.cell(row, 1, f"='{team}'!{get_column_letter(C['Player'])}{r}")
            ws.cell(row, 2, team)
            ws.cell(row, 3, pos)
            for i, h in enumerate(stats, start=4):
                c = ws.cell(row, i, f"='{team}'!{get_column_letter(C[h])}{r}")
                c.number_format = (NUM1 if "TD" in h or "PPR" in h or h == "Int"
                                   else NUM0)
            row += 1
    ws.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{row-1}"
    ws.cell(row + 1, 1,
            "Values are live. Row order is not - sort by Half PPR when you want "
            "a ranking (Data > Sort), or run export_projections.py.").font = SMALL


def merge_report(prior_players, prior_teams, written):
    """What the merge could keep, and what it necessarily broke.

    A team change is not a merge failure - it's the model being honest. A
    share belongs to an offense, not a player, so when someone moves:
      - his edit on the OLD team is gone, and that team no longer sums to 100%
      - he arrives on the NEW team with no valid number, seeded from role
    No merge strategy avoids this. The useful thing is to say exactly which
    teams were disturbed so you can re-balance those and ignore the rest.
    """
    # `written` is what actually landed in a visible slot. Comparing against
    # the full player pool would flag every deep-roster body as "new".
    now = {(names.normalize(n), t): {"player": n, "team": t} for n, t in written}
    now_by_name = defaultdict(list)
    for (nm, team), p in now.items():
        now_by_name[nm].append(team)

    kept, moved, gone, arrived = [], [], [], []
    for (nm, team), rec in prior_players.items():
        if (nm, team) in now:
            kept.append((nm, team))
        elif now_by_name.get(nm):
            moved.append((rec["display"], team, now_by_name[nm][0],
                          rec["edits"].get("Tgt %", 0),
                          rec["edits"].get("Rush %", 0)))
        else:
            gone.append((rec["display"], team,
                         rec["edits"].get("Tgt %", 0),
                         rec["edits"].get("Rush %", 0)))
    prior_keys = set(prior_players)
    for key, p in now.items():
        if key not in prior_keys and prior_players:
            arrived.append((p["player"], p["team"]))

    print(f"\n{'=' * 70}")
    print("MERGE REPORT")
    print(f"{'=' * 70}")
    print(f"  kept {len(kept)} player edits")

    disturbed = defaultdict(lambda: [0.0, 0.0])
    for _, old_team, new_team, t, r in moved:
        disturbed[old_team][0] += t
        disturbed[old_team][1] += r
    for _, old_team, t, r in gone:
        disturbed[old_team][0] += t
        disturbed[old_team][1] += r

    if moved:
        print(f"\n  CHANGED TEAMS ({len(moved)}) - edit dropped, share does not "
              f"follow the player:")
        for name, old, new, t, r in sorted(moved, key=lambda x: -max(x[3], x[4]))[:12]:
            print(f"    {name:<24} {old} -> {new}   held {t*100:>4.1f}% tgt / "
                  f"{r*100:>4.1f}% rush on {old}")
    if gone:
        print(f"\n  OFF EVERY ROSTER ({len(gone)}):")
        for name, old, t, r in sorted(gone, key=lambda x: -max(x[2], x[3]))[:8]:
            print(f"    {name:<24} was {old}   held {t*100:>4.1f}% tgt / "
                  f"{r*100:>4.1f}% rush")
    if arrived:
        print(f"\n  NEW ON A ROSTER ({len(arrived)}) - seeded from role average:")
        for name, team in arrived[:10]:
            print(f"    {name:<24} -> {team}")

    if disturbed:
        print(f"\n  TEAMS TO RE-BALANCE ({len(disturbed)}) - these no longer "
              f"sum to 100%:")
        for team, (t, r) in sorted(disturbed.items(), key=lambda x: -max(x[1])):
            bits = []
            if t > 0.001:
                bits.append(f"{t*100:.0f}% of targets")
            if r > 0.001:
                bits.append(f"{r*100:.0f}% of carries")
            print(f"    {team}  freed up {' and '.join(bits)}")
        print(f"\n  Every other team is untouched - your work there stands.")


def build_start_here(ws, seeded):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 104
    ws.cell(2, 2, f"{SEASON} PROJECTIONS - START HERE").font = Font(
        bold=True, size=18, color="2F4F6F")

    blocks = [
        ("How this works", [
            "Team totals are already projected for you from 10 years of NFL data.",
            "Your job is one thing: decide what SHARE of each team's volume every",
            "player gets. Excel does the rest and updates as you type.",
        ]),
        ("Where to work", [
            "The 32 team tabs (ARI ... WAS). One offense per screen:",
            "   top    - team control totals (editable, already filled in)",
            "   then   - LAST 3 YEARS: plays, pass rate, yards, TDs for context",
            "   then   - OUT / IN / STAFF: who left, who arrived, coaching notes",
            "   middle - players, with 3 years of usage beside each input",
            "   footer - SHARE TOTALS, which must read 100%",
        ]),
        ("Colours", [
            "   BLUE  cells are yours to type in",
            "   GREY  cells are formulas - don't type in them",
            "   CREAM cells are historical fact - what actually happened",
        ]),
        ("You do NOT enter yards per catch or yards per carry", [
            "Those are OUTPUTS now. Team yardage is a control total, so yards",
            "are split by share exactly like targets and carries are - the",
            "column always adds up to the team total no matter what you type.",
            "",
            "What you can tune is 'Rec Eff x' / 'Rush Eff x': yards per",
            "opportunity RELATIVE to the team average. 1.00 = he gains yards in",
            "proportion to his targets. 1.30 = a deep threat earning 30% more",
            "per target than his teammates. 0.75 = a checkdown back.",
            "",
            "Yds/Rec and Yds/Car then fall out as computed columns - USE THEM AS",
            "A CHECK. If a WR1 shows 7 yards a catch, your shares add to well",
            "over 100% and everyone is being squeezed. Balance the team and the",
            "number comes right.",
        ]),
        ("The footer is the whole trick", [
            "If a team's target shares sum to 100%, player targets add up to the",
            "team total automatically. Nothing to reconcile afterwards. Green means",
            "balanced, red means you still have volume to allocate.",
        ]),
        ("Teams open both OVER and UNDER 100% - both are correct", [
            "UNDER: about 24% of targets and 21% of carries changed hands this",
            "offseason. Share is team-relative and NEVER follows a player to his",
            "new team, so every departure leaves a hole. The VACATED block on",
            "each tab names who left and what they took.",
            "",
            "OVER: shares are per-game rates - what a player commanded in games",
            "he actually played. Three backs who each carried 40% of the load",
            "while healthy sum to 120%, and only you can decide the real split.",
        ]),
        ("Games matters - it is not decoration", [
            "Because shares are per-game rates, injury history is NOT baked into",
            "them. Garrett Wilson commanded 30% of the Jets' targets in 2025, not",
            "the 12% his season total implies - he only played 7 games.",
            "So: set Tgt% to what he commands when healthy, and use Games to say",
            "how much of the season you expect. Availability is applied once.",
            "A player you expect to miss time gets fewer games, not a lower share.",
        ]),
        ("Touchdowns", [
            "You don't enter TDs. They come from your usage share x the team's TD",
            "total, adjusted by 'RZ Tgt x' / 'RZ Rush x' - how much that player",
            "over- or under-indexes near the goal line, from his own 3-year record.",
            "1.00 = scores in line with his volume. 1.50 = red-zone weapon (most",
            "TEs, goal-line backs). 0.30 = volume-only (slot WRs, receiving backs).",
            "One usage number drives both yards and touchdowns.",
        ]),
        ("When you're done", [
            "The QB / RB / WR / TE tabs pull every player together across all 32",
            "teams, live. Sort by Half PPR for a ranking.",
        ]),
    ]
    row = 4
    for title, lines in blocks:
        c = ws.cell(row, 2, title)
        c.font = Font(bold=True, size=12, color="2F4F6F")
        row += 1
        for line in lines:
            ws.cell(row, 2, line).font = Font(size=10)
            row += 1
        row += 1

    ws.cell(row, 2, f"Usage inputs were {seeded}.").font = Font(
        size=9, italic=True, color="666666")
    row += 1
    ws.cell(row, 2,
            "EVERY player is seeded - returning players from their own record, "
            "rookies and new arrivals from the league median for their role "
            "(shown as 'role avg' in the Status column). Nothing is left blank, "
            "so a number you haven't touched is never mistaken for a zero.").font = Font(
        size=9, italic=True, color="666666")
    ws.cell(row + 1, 2,
            "Rebuild any time with build_workbook.py - it backs up the old file "
            "first, but your edits are NOT carried over yet.").font = Font(
        size=9, italic=True, color="B22222")


def build_settings(ws, target_rate):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 60
    ws.cell(1, 1, "SETTINGS").font = Font(bold=True, size=14, color="2F4F6F")
    rows = [
        (3, "Games in season", 17, "Regular season games"),
        (4, "Target rate", target_rate,
         "Targets / pass attempt. The gap is throwaways, spikes, batted balls."),
        (6, "SCORING (half PPR)", None, "Matches ff_draft_proj/scoring.py"),
        (7, "Points per rec yard", 0.1, ""),
        (8, "Points per rec TD", 6, ""),
        (9, "Points per reception", 0.5, "0 = standard, 1 = full PPR"),
        (10, "Points per rush yard", 0.1, ""),
        (11, "Points per rush TD", 6, ""),
        (12, "Points per pass yard", 0.04, "QB passing"),
        (13, "Points per pass TD", 4, ""),
        (14, "Points per INT", -2, "negative"),
    ]
    for r, label, val, note in rows:
        ws.cell(r, 1, label).font = BOLD
        if val is not None:
            c = ws.cell(r, 2, val)
            c.fill = INPUT
            c.number_format = "0.000" if isinstance(val, float) else NUM0
        ws.cell(r, 3, note).font = SMALL


def build_vacated_tab(ws, vac_rows):
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.cell(1, 1, f"VACATED {SEASON} - usage that left each roster").font = Font(
        bold=True, size=13, color="2F4F6F")
    heads = ["Team", "Tgt% vacated", "Rush% vacated", "Player", "Pos",
             "Tgt%", "Rush%", "Went to"]
    for i, (h, w) in enumerate(zip(heads, [7, 12, 13, 24, 6, 9, 9, 20]), start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
        c = ws.cell(2, i, h)
        c.font = Font(bold=True, size=9, color="FFFFFF")
        c.fill = HDR
        c.border = BOX
    for r, row in enumerate(vac_rows, start=3):
        ws.cell(r, 1, row["team"])
        for i, k in enumerate(["tgt_share_vacated", "rush_share_vacated"], start=2):
            c = ws.cell(r, i, f(row[k]))
            c.number_format = PCT
        ws.cell(r, 4, row["player"])
        ws.cell(r, 5, row["pos"])
        for i, k in enumerate(["tgt_share", "rush_share"], start=6):
            c = ws.cell(r, i, f(row[k]))
            c.number_format = PCT
        ws.cell(r, 8, row["went_to"])
    ws.auto_filter.ref = f"A2:H{len(vac_rows)+2}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blank-usage", action="store_true",
                    help="leave usage inputs empty instead of seeding history")
    ap.add_argument("--out", default="my_projections.xlsx")
    ap.add_argument("--merge", action="store_true",
                    help="rebuild from fresh data but carry your edits over, "
                         "keyed by (player, team). Reports what it could not "
                         "keep and which teams need re-balancing.")
    ap.add_argument("--force", action="store_true",
                    help="rebuild even if the existing workbook has edits "
                         "(they are discarded; a timestamped backup is kept)")
    args = ap.parse_args()
    prefill = not args.blank_usage

    out_path = os.path.join(HERE, args.out)
    prior_players, prior_teams = ({}, {})
    if args.merge and os.path.exists(out_path):
        prior_players, prior_teams = read_existing(out_path)
        print(f"  read {len(prior_players)} existing player edits to merge")

    shares = read_csv("player_shares.csv")
    totals = {r["team"]: r for r in read_csv(f"team_totals_{SEASON}.csv")}
    vac_rows = read_csv(f"vacated_{SEASON}.csv")

    target_rate = 0.954

    # 3-year team history for the context block on each tab
    hist_by_team = defaultdict(dict)
    for r in read_csv("team_totals_history.csv"):
        if int(r["season"]) in HIST:
            hist_by_team[r["team"]][r["season"]] = r

    # Incoming players: on this roster now, but produced somewhere else last
    # year. The other half of the churn story from VACATED.
    arrivals_by_team = defaultdict(list)
    for p in shares:
        if p.get("changed_team") == "Y" and p["status"] != "OUT":
            arrivals_by_team[p["team"]].append(p)
    for team in arrivals_by_team:
        arrivals_by_team[team].sort(
            key=lambda a: -max(f(a.get(f"tgt_share_{HIST[0]}")),
                               f(a.get(f"rush_share_{HIST[0]}"))))

    coaching = {}
    cpath = os.path.join(HERE, "manual", "coaching_changes.csv")
    if os.path.exists(cpath):
        with open(cpath, newline="", encoding="utf-8") as fh:
            lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
        for r in csv.DictReader(lines):
            if r.get("team"):
                coaching[r["team"].strip().upper()] = r.get("note", "")

    by_team = defaultdict(list)
    for p in shares:
        by_team[p["team"]].append(p)

    vac_by_team = defaultdict(lambda: (0.0, 0.0, []))
    for r in vac_rows:
        t = r["team"]
        cur = vac_by_team[t]
        vac_by_team[t] = (f(r["tgt_share_vacated"]), f(r["rush_share_vacated"]),
                          cur[2] + [(r["player"], f(r["tgt_share"]),
                                     f(r["rush_share"]), r["went_to"])])

    wb = Workbook()
    wb.remove(wb.active)
    build_start_here(
        wb.create_sheet("Start Here"),
        "seeded from a recency-weighted 3-year average (players who changed "
        "teams were left blank)" if prefill else "left blank at your request")

    team_rows = {}
    written_players = []
    for team in TEAMS:
        ws = wb.create_sheet(team)
        if prior_teams.get(team):
            totals[team] = dict(totals.get(team, {}))
        team_rows[team] = build_team_tab(
            ws, team, by_team.get(team, []), totals.get(team, {}),
            vac_by_team[team], prefill, target_rate,
            hist_by_team.get(team, {}), arrivals_by_team.get(team, []),
            coaching, prior_players or None, written_players)

    for pos, _ in SLOTS:
        build_position_tab(wb.create_sheet(pos), pos, team_rows)

    build_vacated_tab(wb.create_sheet("Vacated"), vac_rows)
    build_settings(wb.create_sheet("Settings"), target_rate)

    validate_formulas(wb)

    out = os.path.join(HERE, args.out)
    if os.path.exists(out):
        # A rebuild does NOT merge your edits - it writes a fresh workbook.
        # Once Excel has saved the file it carries cached formula values, which
        # is a reliable signal that real work has gone into it. Refuse to
        # clobber that without --force, and always keep a timestamped copy
        # rather than a single backup that the next rebuild would destroy.
        if looks_edited(out) and not (args.force or args.merge):
            sys.exit(
                f"\n{args.out} looks like you've worked in it (Excel has saved "
                f"it).\nA rebuild would DISCARD those edits - it does not merge."
                f"\n\n  keep your work : do nothing, just keep using the file"
                f"\n  rebuild anyway : python build_workbook.py --force"
                f"\n                   (your current file is backed up first)\n")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = out.replace(".xlsx", f".backup-{stamp}.xlsx")
        try:
            os.replace(out, backup)
        except PermissionError:
            sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n"
                     f"Close it and run again.\n")
        print(f"  previous workbook saved as {os.path.basename(backup)}")
    try:
        wb.save(out)
    except PermissionError:
        sys.exit(f"\nCan't write {args.out} - it's open in Excel.\n"
                 f"Close it and run again.\n")

    if args.merge and prior_players:
        merge_report(prior_players, prior_teams, written_players)

    n_players = sum(1 for p in shares if p["status"] != "OUT")
    print(f"Wrote {args.out}")
    print(f"  32 team tabs + {len(SLOTS)} position tabs + Vacated + Settings")
    print(f"  {n_players} active players, usage inputs "
          f"{'seeded from weighted history' if prefill else 'left blank'}")
    print(f"\nStart on any team tab. Blue cells are yours; grey cells are formulas.")
    print(f"The footer must read 100% before that team's numbers mean anything.")


if __name__ == "__main__":
    sys.exit(main())
