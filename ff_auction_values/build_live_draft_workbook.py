#!/usr/bin/env python3
"""
Build a standalone Excel workbook that recalculates auction values live as
a real draft happens. New file, no legacy formatting to preserve, so this
uses openpyxl (not win32com like the Cheat Sheet workbook) — simpler, and
doesn't require Excel to be running.

Sheets:
  Setup        - league settings. Starting Budget ($), Number of Teams, AND
                 Scoring Format are all live-editable now. Teams and
                 Format are both restricted dropdowns (see "Why team count
                 and scoring format..." below) — Budget is a free
                 whole-dollar entry. Everything downstream (Static Value
                 AND Live Value, for every player) recalculates
                 automatically when any of the three changes.
  Draft Board  - one column-block per position (QB / RB / WR / TE side by
                 side). Enter the real price paid as players are drafted;
                 Live Value updates automatically for everyone still on
                 the board.
  Live Calc    - the actual recalculation math.
  My Team      - personal budget tracker, unrelated to the live recalc
                 math (see add_my_team_sheet()).

## Why team count AND scoring format need a different architecture than budget

A player's Weighted VORP doesn't depend on BUDGET at all — only the
dollar-conversion step does, so budget is one live Excel formula covering
any value continuously (see the "Phase 2" CLAUDE.md entry).

Team count and scoring format are both different: team count changes
REPLACEMENT_RANK/VORP_EXPONENT (real-market-calibrated per team count —
see CLAUDE.md "Round 5"), and scoring format changes both the underlying
POINTS (STD/Half-PPR/PPR score receptions differently) AND
REPLACEMENT_RANK/VORP_EXPONENT/POSITION_BUDGET_SHARE (real-market-
calibrated per format — see CLAUDE.md, the STD/PPR round). Both change
Weighted VORP itself, not just the $ conversion, and POSITION_BUDGET_SHARE
specifically only varies by format (team count doesn't move it — see
calibrate_teamcount.py's FORMAT_BUDGET_SHARE). Re-deriving any of this as
a live Excel formula would be far more error-prone than keeping it in
Python where it's already verified. So: Weighted VORP and Tier are
precomputed for EACH of the 15 (team count x format) calibrated
combinations and stored as parallel hidden columns per player; Setup!Teams
and Setup!Format (both restricted dropdowns) together pick which pair is
"active" via a single CHOOSE formula whose index is computed from both
dropdowns at once (see CONFIG_KEYS/choose_formula below) — 15 precomputed
configurations, not a continuous live recalculation.

## Live recalibration (unchanged since v1.2): a two-factor model

1. TIER-LEVEL market re-rating (same direction, local):
      tier_factor = SUM(real prices paid so far in this tier)
                    / SUM(those same players' original static values)
2. WHOLE-DRAFT-LEVEL budget depletion (global, all positions combined):
      global_factor = current_whole_draft_rate / initial_whole_draft_rate
Final: live_value = ROUND(static_value * tier_factor * global_factor, 0)
       static_value = ROUND(1 + weighted_vorp * position_rate, 0)

Usage:
    python build_live_draft_workbook.py
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from build_auction_values import (
    POINTS_COL, STARTERS, FLEX_SLOTS, BENCH_SPOTS, BUDGET, TEAMS,
    NON_SKILL_SLOTS_PER_TEAM,
    blend_with_personal_ranks, load_personal_ranks,
    load_projections, compute_auction_values, assign_position_tiers,
)
from build_teamcount_estimate import CALIBRATED, TEAM_COUNTS, FORMATS

OUT_FILE = Path(__file__).resolve().parent / "live_draft_board.xlsx"

POSITION_FILL = {
    "QB": "FFE0B2", "RB": "C8E6C9", "WR": "BBDEFB", "TE": "F8BBD0",
}

FORMAT_LABEL = {"std": "STD", "half_ppr": "Half-PPR", "ppr": "PPR"}
DEFAULT_FORMAT = "half_ppr"

# All 15 (format, teams) combinations, grouped by format then team count —
# this exact order is what choose_formula()'s flattened index arithmetic
# assumes (index = position-within-team-count-block + block-offset, where
# block = which format). Changing this order requires updating
# choose_formula() to match.
CONFIG_KEYS = [(fmt, teams) for fmt in FORMATS for teams in TEAM_COUNTS]

# How many players to show per position on the Draft Board — the fixed row
# list is the UNION of each of the 15 configs' own top-N by that config's
# own weighted VORP (not a single reference config), since scoring format
# (unlike team count alone) actually reorders players within a position —
# a pass-catching RB/WR ranks higher in PPR than STD. Measured empirically
# (see CLAUDE.md, the STD/PPR round): the union came out at 55/143/167/72
# vs a single config's own 55/140/165/70 — QB is exactly invariant (no
# format variation at all), RB/WR/TE gain a handful of extra rows from
# format-driven reordering. Depths below add a small buffer past the
# measured union.
BOARD_DEPTH = {"QB": 55, "RB": 145, "WR": 170, "TE": 75}

TOTAL_ROSTER_SPOTS_PER_TEAM = (
    sum(STARTERS.values()) + FLEX_SLOTS + BENCH_SPOTS + NON_SKILL_SLOTS_PER_TEAM
)

# Columns within one position's block. 15 hidden Tier/WeightedVORP pairs
# (one pair per (format, teams) combination) feed two "Selected" columns
# that live-switch based on Setup!Teams + Setup!Format via CHOOSE/MATCH.
PER_CONFIG_COLS = []
for _fmt, _t in CONFIG_KEYS:
    PER_CONFIG_COLS += [f"Tier ({FORMAT_LABEL[_fmt]} {_t}T)", f"Weighted VORP ({FORMAT_LABEL[_fmt]} {_t}T)"]

BLOCK_COLS = (["Player", "Team"] + PER_CONFIG_COLS +
              ["Tier (active)", "Weighted VORP (active)",
               "Static Value ($)", "Price Paid ($)", "Live Value ($)"])
OFF_PLAYER, OFF_TEAM = 0, 1
# Offsets of each (tier, wvorp) pair within the block, keyed by (fmt, teams)
OFF_TIER = {key: 2 + 2 * i for i, key in enumerate(CONFIG_KEYS)}
OFF_WVORP = {key: 2 + 2 * i + 1 for i, key in enumerate(CONFIG_KEYS)}
_after_pairs = 2 + 2 * len(CONFIG_KEYS)
OFF_SEL_TIER = _after_pairs
OFF_SEL_WVORP = _after_pairs + 1
OFF_STATIC = _after_pairs + 2
OFF_PRICE = _after_pairs + 3
OFF_LIVE = _after_pairs + 4
BLOCK_WIDTH = len(BLOCK_COLS)
SPACER_COLS = 1


def compute_all_configs():
    """Run the full pipeline once per calibrated (format, teams) combo.
    Returns {(fmt, teams): {normalized_key: player_dict_with_tier_and_weighted_vorp}}."""
    from name_match import normalize_name

    blended_by_fmt = {}
    for fmt in FORMATS:
        projections = load_projections(fmt)
        personal_ranks = load_personal_ranks(fmt)
        blended_by_fmt[fmt] = blend_with_personal_ranks(projections, personal_ranks)

    by_config = {}
    for fmt, teams in CONFIG_KEYS:
        cal = CALIBRATED[(teams, fmt)]
        players, pos_stats = compute_auction_values(
            blended_by_fmt[fmt], ranks=cal["ranks"], exponents=cal["exponents"],
            teams=teams, budget_share=cal["budget_share"], verbose=False)
        players, _ = assign_position_tiers(players, pos_stats)
        by_config[(fmt, teams)] = {normalize_name(p["name"]): p for p in players}
    return by_config


def board_player_list(by_config):
    """Fixed row list per position: union of each config's own top-N (by
    that config's own weighted VORP), sorted for display by the MAXIMUM
    weighted VORP any config assigns that player (always defined for
    anyone in the union, unlike picking one reference config)."""
    from name_match import normalize_name

    by_pos = {pos: {} for pos in POINTS_COL}  # pos -> {key: max_weighted_vorp}
    for key in CONFIG_KEYS:
        players_by_pos = {}
        for p in by_config[key].values():
            players_by_pos.setdefault(p["position"], []).append(p)
        for pos in POINTS_COL:
            top = sorted(players_by_pos.get(pos, []), key=lambda p: -p["weighted_vorp"])[:BOARD_DEPTH[pos]]
            for p in top:
                k = normalize_name(p["name"])
                by_pos[pos][k] = max(by_pos[pos].get(k, 0.0), p["weighted_vorp"])

    return {pos: [k for k, _ in sorted(by_pos[pos].items(), key=lambda kv: -kv[1])]
            for pos in POINTS_COL}


def build_block_layout(board_keys):
    layout = {}
    col = 1
    for pos in POINTS_COL:
        n = len(board_keys[pos])
        layout[pos] = {"start_col": col, "n_rows": n, "last_row": n + 1}
        col += BLOCK_WIDTH + SPACER_COLS
    return layout


def block_col(layout, pos, offset):
    return get_column_letter(layout[pos]["start_col"] + offset)


def block_range(layout, pos, offset):
    last_row = layout[pos]["last_row"]
    col = block_col(layout, pos, offset)
    return f"'Draft Board'!${col}$2:${col}${last_row}"


def choose_formula(cell_refs_by_config):
    """=CHOOSE(index, ref1, ..., ref15) where index is computed from BOTH
    Setup!Teams and Setup!Format at once: MATCH(Teams,{8,10,12,14,16},0)
    picks a position within a 5-wide block, and
    (MATCH(Format,{labels},0)-1)*5 picks which block — matching CONFIG_KEYS'
    [(fmt, teams) for fmt in FORMATS for teams in TEAM_COUNTS] order."""
    teams_list = "{" + ",".join(str(t) for t in TEAM_COUNTS) + "}"
    fmt_list = "{" + ",".join(f'"{FORMAT_LABEL[f]}"' for f in FORMATS) + "}"
    index = (f"MATCH(Setup!$B$5,{teams_list},0)"
             f"+(MATCH(Setup!$B$7,{fmt_list},0)-1)*{len(TEAM_COUNTS)}")
    refs = [cell_refs_by_config[key] for key in CONFIG_KEYS]
    return f"CHOOSE({index},{','.join(refs)})"


def add_setup_sheet(wb):
    sheet = wb.create_sheet("Setup", 0)
    sheet["A1"] = "League Setup"
    sheet["A1"].font = Font(bold=True, size=13)

    sheet["A3"] = "Starting Budget ($)"
    sheet["B3"] = BUDGET
    sheet["A3"].font = Font(bold=True)
    dv_budget = DataValidation(type="whole", operator="between", formula1="15", formula2="1000",
                                allow_blank=False, showErrorMessage=True,
                                errorTitle="Invalid budget",
                                error="Enter a whole-dollar budget (15-1000).")
    sheet.add_data_validation(dv_budget)
    dv_budget.add("B3")

    sheet["A5"] = "Number of Teams"
    sheet["B5"] = TEAMS
    sheet["A5"].font = Font(bold=True)
    dv_teams = DataValidation(
        type="list", formula1='"' + ",".join(str(t) for t in TEAM_COUNTS) + '"',
        allow_blank=False, showErrorMessage=True,
        errorTitle="Invalid team count",
        error=f"Choose one of: {', '.join(str(t) for t in TEAM_COUNTS)}.")
    sheet.add_data_validation(dv_teams)
    dv_teams.add("B5")

    sheet["A7"] = "Scoring Format"
    sheet["B7"] = FORMAT_LABEL[DEFAULT_FORMAT]
    sheet["A7"].font = Font(bold=True)
    dv_format = DataValidation(
        type="list", formula1='"' + ",".join(FORMAT_LABEL[f] for f in FORMATS) + '"',
        allow_blank=False, showErrorMessage=True,
        errorTitle="Invalid scoring format",
        error=f"Choose one of: {', '.join(FORMAT_LABEL[f] for f in FORMATS)}.")
    sheet.add_data_validation(dv_format)
    dv_format.add("B7")

    for cell in ("B3", "B5", "B7"):
        sheet[cell].fill = PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid")

    sheet["A9"] = "Roster Shape (fixed for now)"
    sheet["B9"] = "1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX / 1 DEF / 1 K / 6 Bench"

    sheet["A11"] = (
        "Budget, Number of Teams, and Scoring Format are all fully live — change any of "
        "them and every value on the Draft Board updates automatically. Teams and Format "
        "are both restricted to dropdowns because those are the only combinations with "
        "real market-data calibration behind them (see CLAUDE.md) — picking anything else "
        "would silently give wrong numbers, not just an error. Roster shape isn't editable "
        "yet for the same reason: it's also tied to the current calibration.")
    sheet["A11"].font = Font(italic=True)
    sheet["A11"].alignment = Alignment(wrap_text=True)
    sheet.row_dimensions[11].height = 75
    sheet.merge_cells("A11:F11")

    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 45
    return sheet


def build_draft_board_shell(wb, by_config, board_keys, layout):
    board = wb.create_sheet("Draft Board", 1)
    board.freeze_panes = "A2"

    for pos in POINTS_COL:
        start = layout[pos]["start_col"]
        for j, header in enumerate(BLOCK_COLS):
            cell = board.cell(1, start + j, header)
            cell.font = Font(bold=True)
        fill = PatternFill(start_color=POSITION_FILL[pos],
                            end_color=POSITION_FILL[pos], fill_type="solid")

        for i, key in enumerate(board_keys[pos], start=2):
            # Name/team don't vary by config — use whichever config has this
            # player (every board player is in at least one config's top-N,
            # but not necessarily every config's, by construction).
            ref_player = next(by_config[ck][key] for ck in CONFIG_KEYS if key in by_config[ck])
            board.cell(i, start + OFF_PLAYER, ref_player["name"]).fill = fill
            board.cell(i, start + OFF_TEAM, ref_player["team"]).fill = fill
            for ck in CONFIG_KEYS:
                p = by_config[ck].get(key)
                tier = p["tier"] if p else 999
                wvorp = round(p["weighted_vorp"], 4) if p else 0.0
                board.cell(i, start + OFF_TIER[ck], tier).fill = fill
                board.cell(i, start + OFF_WVORP[ck], wvorp).fill = fill
            board.cell(i, start + OFF_STATIC).fill = fill  # formula, filled in later
            board.cell(i, start + OFF_PRICE).fill = fill  # blank, user entry
            board.cell(i, start + OFF_LIVE).fill = fill  # formula, filled in later
            board.cell(i, start + OFF_SEL_TIER).fill = fill  # formula, filled in later
            board.cell(i, start + OFF_SEL_WVORP).fill = fill  # formula, filled in later

        # Column widths; hide all the per-config helper columns
        widths = {OFF_PLAYER: 22, OFF_TEAM: 7, OFF_SEL_TIER: 8, OFF_SEL_WVORP: 14,
                  OFF_STATIC: 13, OFF_PRICE: 12, OFF_LIVE: 12}
        for offset, width in widths.items():
            board.column_dimensions[get_column_letter(start + offset)].width = width
        for ck in CONFIG_KEYS:
            board.column_dimensions[get_column_letter(start + OFF_TIER[ck])].hidden = True
            board.column_dimensions[get_column_letter(start + OFF_WVORP[ck])].hidden = True

        last_row = layout[pos]["last_row"]
        price_col = get_column_letter(start + OFF_PRICE)
        dv = DataValidation(type="whole", operator="between", formula1="0", formula2="400",
                             allow_blank=True, showErrorMessage=True,
                             errorTitle="Invalid price",
                             error="Enter a whole-dollar amount (0-400).")
        board.add_data_validation(dv)
        dv.add(f"{price_col}2:{price_col}{last_row}")

        # Selected Tier / Weighted VORP: CHOOSE among the 15 config columns
        for i in range(2, last_row + 1):
            tier_refs = {ck: f"{get_column_letter(start + OFF_TIER[ck])}{i}" for ck in CONFIG_KEYS}
            wvorp_refs = {ck: f"{get_column_letter(start + OFF_WVORP[ck])}{i}" for ck in CONFIG_KEYS}
            board.cell(i, start + OFF_SEL_TIER).value = f"={choose_formula(tier_refs)}"
            board.cell(i, start + OFF_SEL_WVORP).value = f"={choose_formula(wvorp_refs)}"

    return board


def build_live_calc(wb, by_config, board_keys, layout):
    calc = wb.create_sheet("Live Calc")
    row = 1

    # ── $ SETUP: driven directly by Setup!Teams and Setup!Budget ─────────
    calc.cell(row, 1, "$ SETUP (driven by Setup!Teams and Setup!Budget)").font = Font(bold=True)
    row += 1
    calc.cell(row, 1, "Total Teams")
    calc.cell(row, 2).value = "=Setup!$B$5"
    teams_row = row
    row += 1
    calc.cell(row, 1, "Total Roster Spots")
    calc.cell(row, 2).value = f"=B{teams_row}*{TOTAL_ROSTER_SPOTS_PER_TEAM}"
    spots_row = row
    row += 1
    calc.cell(row, 1, "Total Money ($)")
    calc.cell(row, 2).value = f"=B{teams_row}*Setup!$B$3"
    money_row = row
    row += 1
    calc.cell(row, 1, "Total Discretionary ($)")
    calc.cell(row, 2).value = f"=B{money_row}-B{spots_row}*1"
    discretionary_row = row
    row += 2

    # ── POSITION RATES: Discretionary $ now varies by FORMAT (budget share
    # only, team count doesn't move it — see calibrate_teamcount.py's
    # FORMAT_BUDGET_SHARE), Total Weighted VORP varies by BOTH format and
    # team count. Both are CHOOSE lookups against small side tables on the
    # same row. ────────────────────────────────────────────────────────
    calc.cell(row, 1, "POSITION RATES").font = Font(bold=True)
    row += 1
    for j, h in enumerate(["Position", "Discretionary $", "Total Weighted VORP", "Rate"]):
        calc.cell(row, 1 + j, h).font = Font(bold=True)
    rate_row = {}
    fmt_list = "{" + ",".join(f'"{FORMAT_LABEL[f]}"' for f in FORMATS) + "}"
    for pos in POINTS_COL:
        row += 1
        calc.cell(row, 1, pos)

        # Budget share per format, written to a small side area, CHOOSE'd
        # by Setup!Format alone (3 values, not 15).
        share_cells = []
        for idx, fmt in enumerate(FORMATS):
            col = 6 + idx  # F, G, H
            share = CALIBRATED[(TEAM_COUNTS[0], fmt)]["budget_share"][pos]
            calc.cell(row, col, round(share, 5))
            share_cells.append(f"{get_column_letter(col)}{row}")
        calc.cell(row, 2).value = (
            f"=$B${discretionary_row}*CHOOSE(MATCH(Setup!$B$7,{fmt_list},0),{','.join(share_cells)})"
        )

        # Total Weighted VORP per (format, teams), written to a wider side
        # area (columns J onward), CHOOSE'd by both dropdowns.
        sum_cells = {}
        for idx, ck in enumerate(CONFIG_KEYS):
            fmt, teams = ck
            total_wvorp = sum(by_config[ck][k]["weighted_vorp"] for k in board_keys[pos]
                               if k in by_config[ck])
            col = 10 + idx  # J onward, 15 columns
            calc.cell(row, col, round(total_wvorp, 4))
            sum_cells[ck] = f"{get_column_letter(col)}{row}"
        calc.cell(row, 3).value = f"={choose_formula(sum_cells)}"
        calc.cell(row, 4).value = f"=IFERROR(B{row}/C{row},0)"
        rate_row[pos] = row
    row += 2

    # ── Per-position TIER tables (market re-rating factor). Row set =
    # union of tier values seen across ALL 15 configs for that position's
    # board players, so the table covers whichever config is active
    # regardless of the Setup!Teams/Format selection. ────────────────────
    tier_table_range = {}
    for pos in POINTS_COL:
        calc.cell(row, 1, f"{pos} tiers").font = Font(bold=True)
        row += 1
        for j, h in enumerate(["Tier", "Drafted Price Sum", "Drafted Static Sum", "Tier Factor"]):
            calc.cell(row, 1 + j, h).font = Font(bold=True)
        table_start = row + 1
        all_tiers = set()
        for ck in CONFIG_KEYS:
            for k in board_keys[pos]:
                p = by_config[ck].get(k)
                if p:
                    all_tiers.add(p["tier"])
        tiers = sorted(all_tiers)
        price_rng = block_range(layout, pos, OFF_PRICE)
        static_rng = block_range(layout, pos, OFF_STATIC)
        tier_rng = block_range(layout, pos, OFF_SEL_TIER)
        for t in tiers:
            row += 1
            calc.cell(row, 1, t)
            calc.cell(row, 2).value = f'=SUMIFS({price_rng},{tier_rng},A{row},{price_rng},"<>")'
            calc.cell(row, 3).value = f'=SUMIFS({static_rng},{tier_rng},A{row},{price_rng},"<>")'
            calc.cell(row, 4).value = f"=IFERROR(B{row}/C{row},1)"
        table_end = row
        tier_table_range[pos] = (f"$A${table_start}:$A${table_end}", f"$D${table_start}:$D${table_end}")
        row += 2

    # ── GLOBAL (whole-draft) depletion table ──────────────────────────────
    calc.cell(row, 1, "GLOBAL (whole draft)").font = Font(bold=True)
    row += 1
    g_headers = ["Initial Discretionary $", "Initial Weighted VORP", "Initial Rate",
                 "Drafted $ (all positions)", "Drafted Count (all positions)",
                 "Drafted Weighted VORP (all positions)",
                 "Remaining Discretionary $", "Remaining Weighted VORP",
                 "Current Rate", "Depletion Factor"]
    for j, h in enumerate(g_headers):
        calc.cell(row, 1 + j, h).font = Font(bold=True)
    g_row = row + 1

    calc.cell(g_row, 1).value = f"=B{discretionary_row}"
    rate_cells = "+".join(f"C{rate_row[pos]}" for pos in POINTS_COL)
    calc.cell(g_row, 2).value = f"={rate_cells}"
    calc.cell(g_row, 3).value = f"=IFERROR(A{g_row}/B{g_row},0)"

    price_terms = "+".join(f"SUM({block_range(layout, pos, OFF_PRICE)})" for pos in POINTS_COL)
    count_terms = "+".join(f"COUNT({block_range(layout, pos, OFF_PRICE)})" for pos in POINTS_COL)
    wvorp_terms = "+".join(
        f'SUMIFS({block_range(layout, pos, OFF_SEL_WVORP)},{block_range(layout, pos, OFF_PRICE)},"<>")'
        for pos in POINTS_COL
    )
    calc.cell(g_row, 4).value = f"={price_terms}"
    calc.cell(g_row, 5).value = f"={count_terms}"
    calc.cell(g_row, 6).value = f"={wvorp_terms}"
    calc.cell(g_row, 7).value = f"=A{g_row}-(D{g_row}-E{g_row})"
    calc.cell(g_row, 8).value = f"=B{g_row}-F{g_row}"
    calc.cell(g_row, 9).value = f"=IFERROR(G{g_row}/H{g_row},0)"
    calc.cell(g_row, 10).value = f"=IFERROR(I{g_row}/C{g_row},1)"

    for col, width in zip("ABCDEFGHIJ", (16, 24, 26, 16, 12, 18, 12, 22, 20, 24)):
        calc.column_dimensions[col].width = width

    return calc, rate_row, tier_table_range, g_row


def main():
    by_config = compute_all_configs()
    board_keys = board_player_list(by_config)
    layout = build_block_layout(board_keys)

    wb = Workbook()
    wb.remove(wb.active)

    add_setup_sheet(wb)
    board = build_draft_board_shell(wb, by_config, board_keys, layout)
    calc, rate_row, tier_table_range, g_row = build_live_calc(wb, by_config, board_keys, layout)

    global_factor_cell = f"'Live Calc'!$J${g_row}"

    for pos in POINTS_COL:
        start = layout[pos]["start_col"]
        tier_range, factor_range = tier_table_range[pos]
        sel_wvorp_col = get_column_letter(start + OFF_SEL_WVORP)
        sel_tier_col = get_column_letter(start + OFF_SEL_TIER)
        static_col = get_column_letter(start + OFF_STATIC)
        price_col = get_column_letter(start + OFF_PRICE)
        live_col = get_column_letter(start + OFF_LIVE)
        rate_cell = f"'Live Calc'!$D${rate_row[pos]}"
        for i in range(2, layout[pos]["last_row"] + 1):
            board[f"{static_col}{i}"].value = (
                f"=ROUND(1+{sel_wvorp_col}{i}*{rate_cell},0)"
            )
            board[f"{live_col}{i}"].value = (
                f'=IF({price_col}{i}<>"",{price_col}{i},'
                f"ROUND({static_col}{i}"
                f"*INDEX('Live Calc'!{factor_range},MATCH({sel_tier_col}{i},'Live Calc'!{tier_range},0))"
                f"*{global_factor_cell},0))"
            )

    add_my_team_sheet(wb)

    wb.save(OUT_FILE)
    print(f"Wrote {OUT_FILE}")
    print(f"Change Setup!B3 (Budget), Setup!B5 (Teams, {'/'.join(str(t) for t in TEAM_COUNTS)}), "
          f"or Setup!B7 (Format, {'/'.join(FORMAT_LABEL[f] for f in FORMATS)}) to instantly "
          "recalculate every value.")
    print("Enter real prices in each position's 'Price Paid ($)' column on Draft Board.")
    print("Board is trimmed to top " +
          ", ".join(f"{BOARD_DEPTH[p]} {p}" for p in POINTS_COL) +
          " (union of all 15 configs' own top-N).")
    print("Track your own roster/budget on the My Team sheet (independent of Draft Board).")


def build_roster_slots():
    slots = []
    for pos in ("QB", "RB", "WR", "TE"):
        slots += [pos] * STARTERS[pos]
    slots += ["FLEX (RB/WR/TE)"] * FLEX_SLOTS
    slots += ["DEF", "K"]
    slots += ["Bench"] * BENCH_SPOTS
    return slots


def add_my_team_sheet(wb):
    """Simple personal budget tracker: enter who you drafted and what you
    paid, get real-time remaining budget / max next bid / average $ left
    per remaining spot. Completely independent of Draft Board/Live Calc's
    recalculation math — no formula linkage there — but Total Budget DOES
    reference Setup!Budget, so it stays correct if budget changes. Roster
    Spots (total) stays a fixed constant regardless of team count or
    scoring format — roster SHAPE per team doesn't change with either."""
    slots = build_roster_slots()
    n = len(slots)
    last_row = n + 1

    sheet = wb.create_sheet("My Team")
    sheet.append(["Roster Slot", "Player", "Price Paid ($)"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for i, slot in enumerate(slots, start=2):
        sheet.cell(i, 1, slot)
        fill_color = POSITION_FILL.get(slot)
        if fill_color:
            fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
            sheet.cell(i, 1).fill = fill

    dv = DataValidation(type="whole", operator="between", formula1="0", formula2="400",
                         allow_blank=True, showErrorMessage=True,
                         errorTitle="Invalid price",
                         error="Enter a whole-dollar amount (0-400).")
    sheet.add_data_validation(dv)
    dv.add(f"C2:C{last_row}")

    r0 = last_row + 3
    rows = [
        ("Total Budget ($)", "=Setup!$B$3"),
        ("Roster Spots (total)", n),
        ("Spots Filled", f"=COUNT(C2:C{last_row})"),
        ("Spots Remaining", None),
        ("Total Spent ($)", f"=SUM(C2:C{last_row})"),
        ("Money Remaining ($)", None),
        ("Max Bid on Next Player ($)", None),
        ("Avg $ per Remaining Spot ($)", None),
    ]
    for offset, (label, value) in enumerate(rows):
        r = r0 + offset
        sheet.cell(r, 1, label).font = Font(bold=True)
        if value is not None:
            sheet.cell(r, 2).value = value
    budget_r, spots_r, filled_r, remain_r, spent_r, money_r, max_r, avg_r = range(r0, r0 + 8)
    sheet.cell(remain_r, 2).value = f"=B{spots_r}-B{filled_r}"
    sheet.cell(money_r, 2).value = f"=B{budget_r}-B{spent_r}"
    sheet.cell(max_r, 2).value = (
        f'=IF(B{remain_r}>0,B{money_r}-(B{remain_r}-1)*1,"Roster full")'
    )
    sheet.cell(avg_r, 2).value = f'=IFERROR(B{money_r}/B{remain_r},"Roster full")'

    sheet.column_dimensions["A"].width = 20
    sheet.column_dimensions["B"].width = 26
    sheet.column_dimensions["C"].width = 15


if __name__ == "__main__":
    main()
