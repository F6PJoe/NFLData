#!/usr/bin/env python3
"""One-off: open live_draft_board.xlsx via Excel COM, force recalculation,
and sanity-check the v1.4 team-count + scoring-format switching model. Not
part of the regular pipeline.

Position blocks are now 38 columns wide (37 data cols + 1 spacer):
start cols QB=1, RB=39, WR=77, TE=115. Within a block, see
build_live_draft_workbook.py's OFF_* constants for the exact layout
(Player/Team, 15 pairs of hidden Tier/WeightedVORP columns keyed by
(format, teams), then Selected Tier/Selected WeightedVORP/Static/Price/Live).
"""

import win32com.client as win32

from build_live_draft_workbook import (
    OFF_PLAYER, OFF_STATIC, OFF_PRICE, OFF_LIVE, BLOCK_WIDTH, SPACER_COLS,
    CONFIG_KEYS, FORMAT_LABEL,
)
from build_teamcount_estimate import TEAM_COUNTS, FORMATS

WORKBOOK = r"C:\Users\jbond\OneDrive\Documents\FF_ADP\ff_auction_values\live_draft_board.xlsx"
POSITIONS = ["QB", "RB", "WR", "TE"]
BLOCK_START = {pos: 1 + i * (BLOCK_WIDTH + SPACER_COLS) for i, pos in enumerate(POSITIONS)}


def find_row(board, pos, name, max_row=250):
    start = BLOCK_START[pos]
    for r in range(2, max_row):
        v = board.Cells(r, start + OFF_PLAYER).Value
        if v == name:
            return r
        if v is None:
            break
    raise ValueError(f"{name} not found in {pos} block")


def get(board, pos, row, offset):
    return board.Cells(row, BLOCK_START[pos] + offset).Value


def count_filled_prices(board):
    total = 0
    for pos, start in BLOCK_START.items():
        col = start + OFF_PRICE
        r = 2
        while board.Cells(r, start + OFF_PLAYER).Value is not None:
            if board.Cells(r, col).Value is not None:
                total += 1
            r += 1
    return total


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            setup = wb.Sheets("Setup")
            board = wb.Sheets("Draft Board")
            calc = wb.Sheets("Live Calc")
            excel.CalculateFullRebuild()

            print("Setup!B3 (Budget):", setup.Cells(3, 2).Value)
            print("Setup!B5 (Teams):", setup.Cells(5, 2).Value)
            print("Setup!B7 (Format):", setup.Cells(7, 2).Value)
            print("Leftover filled Price cells at fresh build (should be 0):",
                  count_filled_prices(board))

            g_row = None
            money_row = None
            for r in range(1, 400):
                if calc.Cells(r, 1).Value == "GLOBAL (whole draft)":
                    g_row = r + 2
                if calc.Cells(r, 1).Value == "Total Money ($)":
                    money_row = r
            print("Global depletion factor (should be 1.0):", calc.Cells(g_row, 10).Value)

            names = [("RB", "Jahmyr Gibbs"), ("WR", "Puka Nacua"), ("QB", "Josh Allen"),
                     ("TE", "Trey McBride")]

            print(f"\n=== All {len(CONFIG_KEYS)} (format, teams) combos: Total Money check ===")
            all_ok = True
            for fmt, teams in CONFIG_KEYS:
                setup.Cells(5, 2).Value = teams
                setup.Cells(7, 2).Value = FORMAT_LABEL[fmt]
                excel.CalculateFullRebuild()
                total_money = calc.Cells(money_row, 2).Value
                expected = teams * 200
                ok = total_money == expected
                all_ok &= ok
                marker = "" if ok else "  *** MISMATCH ***"
                print(f"  {FORMAT_LABEL[fmt]:9} {teams:>2}T  Total Money=${total_money} "
                      f"(expect ${expected}){marker}")
            print("All 15 combos' Total Money correct:" , all_ok)

            print("\n=== Spot-check named players across format x team-count corners ===")
            for fmt, teams in [("std", 8), ("std", 16), ("ppr", 8), ("ppr", 16),
                                ("half_ppr", 12), ("ppr", 12), ("std", 12)]:
                setup.Cells(5, 2).Value = teams
                setup.Cells(7, 2).Value = FORMAT_LABEL[fmt]
                excel.CalculateFullRebuild()
                vals = []
                for pos, name in names:
                    r = find_row(board, pos, name)
                    static = get(board, pos, r, OFF_STATIC)
                    vals.append(f"{name}=${static}")
                print(f"  {FORMAT_LABEL[fmt]:9} {teams:>2}T  " + ", ".join(vals))

            setup.Cells(5, 2).Value = 12
            setup.Cells(7, 2).Value = "Half-PPR"
            excel.CalculateFullRebuild()
            print("\n=== Restored Setup to 12 teams / Half-PPR ===")
            for pos, name in names:
                r = find_row(board, pos, name)
                print(f"  {pos} {name:16} static=${get(board, pos, r, OFF_STATIC)}")

            print("\n=== Budget still live-editable independently ===")
            baseline = {}
            for pos, name in names:
                r = find_row(board, pos, name)
                baseline[(pos, name)] = get(board, pos, r, OFF_STATIC)
            setup.Cells(3, 2).Value = 260
            excel.CalculateFullRebuild()
            for pos, name in names:
                r = find_row(board, pos, name)
                static = get(board, pos, r, OFF_STATIC)
                print(f"  {pos} {name:16} static=${static}  (was ${baseline[(pos, name)]} at $200)")
            setup.Cells(3, 2).Value = 200
            excel.CalculateFullRebuild()

            print("\n=== Sanity-check a live pick still ripples correctly (12T, Half-PPR, $200) ===")
            r = find_row(board, "RB", "Jahmyr Gibbs")
            board.Cells(r, BLOCK_START["RB"] + OFF_PRICE).Value = 100
            excel.CalculateFullRebuild()
            r2 = find_row(board, "RB", "Bijan Robinson")
            print("  Bijan Robinson live value after Gibbs overpay to $100:",
                  get(board, "RB", r2, OFF_LIVE))
            board.Cells(r, BLOCK_START["RB"] + OFF_PRICE).Value = None
            excel.CalculateFullRebuild()
            print("Leftover filled Price cells after clearing test pick (should be 0):",
                  count_filled_prices(board))

            wb.Close(SaveChanges=False)
        finally:
            pass
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
