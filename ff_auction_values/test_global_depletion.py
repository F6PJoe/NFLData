#!/usr/bin/env python3
"""One-off: confirm the whole-draft depletion factor (the mechanism that
answers "do prices move as an overall PERCENTAGE of money gets spent, not
just within one tier/position") still works correctly after this round's
team-count-switching rebuild, since the POSITION RATES table's Total
Weighted VORP inputs changed from fixed constants to CHOOSE/MATCH lookups
that GLOBAL's own Initial Weighted VORP is summed from. Not part of the
regular pipeline.
"""

import random

import win32com.client as win32

from build_live_draft_workbook import (
    OFF_PLAYER, OFF_STATIC, OFF_PRICE, OFF_LIVE, BLOCK_WIDTH, SPACER_COLS,
)

WORKBOOK = r"C:\Users\jbond\OneDrive\Documents\FF_ADP\ff_auction_values\live_draft_board.xlsx"
POSITIONS = ["QB", "RB", "WR", "TE"]
BLOCK_START = {pos: 1 + i * (BLOCK_WIDTH + SPACER_COLS) for i, pos in enumerate(POSITIONS)}


def board_rows(board, pos, max_row=200):
    start = BLOCK_START[pos]
    rows = []
    r = 2
    while r < max_row and board.Cells(r, start + OFF_PLAYER).Value is not None:
        rows.append(r)
        r += 1
    return rows


def clear_all_prices(board):
    for pos, start in BLOCK_START.items():
        for r in board_rows(board, pos):
            board.Cells(r, start + OFF_PRICE).Value = None


def find_g_row(calc):
    for r in range(1, 400):
        if calc.Cells(r, 1).Value == "GLOBAL (whole draft)":
            return r + 2
    raise ValueError("GLOBAL block not found")


def simulate(board, pct_of_board, overpay_multiplier, seed=42):
    """Draft pct_of_board of each position's rows at overpay_multiplier x
    their static value. Returns the set of (pos, row) drafted and one
    untouched (pos, row) per position to check afterward."""
    rng = random.Random(seed)
    drafted = []
    untouched = {}
    for pos, start in BLOCK_START.items():
        rows = board_rows(board, pos)
        rng.shuffle(rows)
        n = int(len(rows) * pct_of_board)
        for r in rows[:n]:
            static = board.Cells(r, start + OFF_STATIC).Value
            price = max(1, round(static * overpay_multiplier))
            board.Cells(r, start + OFF_PRICE).Value = price
            drafted.append((pos, r))
        # first untouched row (not in the drafted set) for later inspection
        for r in rows[n:]:
            untouched[pos] = r
            break
    return drafted, untouched


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            board = wb.Sheets("Draft Board")
            calc = wb.Sheets("Live Calc")
            excel.CalculateFullRebuild()
            g_row = find_g_row(calc)

            print("=== Baseline (nothing drafted) ===")
            print("Depletion factor (should be 1.0):", calc.Cells(g_row, 10).Value)

            print("\n=== Scenario A: broad HOT market ===")
            print("Draft ~20% of every position's board, each at 1.20x static value")
            _, untouched_a = simulate(board, pct_of_board=0.20, overpay_multiplier=1.20, seed=1)
            excel.CalculateFullRebuild()
            factor_a = calc.Cells(g_row, 10).Value
            print("Depletion factor (expect < 1.0, money burning faster than expected):", factor_a)
            for pos, r in untouched_a.items():
                start = BLOCK_START[pos]
                name = board.Cells(r, start + OFF_PLAYER).Value
                static = board.Cells(r, start + OFF_STATIC).Value
                live = board.Cells(r, start + OFF_LIVE).Value
                print(f"  untouched {pos} {name:22} static=${static}  live=${live}  "
                      f"(expect live < static)")

            clear_all_prices(board)
            excel.CalculateFullRebuild()
            print("\nCleared. Depletion factor back to baseline:", calc.Cells(g_row, 10).Value)

            print("\n=== Scenario B: broad COLD market ===")
            print("Draft ~20% of every position's board, each at 0.75x static value")
            _, untouched_b = simulate(board, pct_of_board=0.20, overpay_multiplier=0.75, seed=1)
            excel.CalculateFullRebuild()
            factor_b = calc.Cells(g_row, 10).Value
            print("Depletion factor (expect > 1.0, money left over vs. expected):", factor_b)
            for pos, r in untouched_b.items():
                start = BLOCK_START[pos]
                name = board.Cells(r, start + OFF_PLAYER).Value
                static = board.Cells(r, start + OFF_STATIC).Value
                live = board.Cells(r, start + OFF_LIVE).Value
                print(f"  untouched {pos} {name:22} static=${static}  live=${live}  "
                      f"(expect live > static)")

            clear_all_prices(board)
            excel.CalculateFullRebuild()

            print("\n=== Scenario C: draft exactly AT static value (normal pace) ===")
            print("Draft ~40% of every position's board, each at exactly 1.00x static value")
            _, untouched_c = simulate(board, pct_of_board=0.40, overpay_multiplier=1.00, seed=2)
            excel.CalculateFullRebuild()
            factor_c = calc.Cells(g_row, 10).Value
            print("Depletion factor (expect ~1.0, unchanged just from progress/spend %):", factor_c)
            for pos, r in untouched_c.items():
                start = BLOCK_START[pos]
                name = board.Cells(r, start + OFF_PLAYER).Value
                static = board.Cells(r, start + OFF_STATIC).Value
                live = board.Cells(r, start + OFF_LIVE).Value
                print(f"  untouched {pos} {name:22} static=${static}  live=${live}  "
                      f"(expect live == static)")

            clear_all_prices(board)
            excel.CalculateFullRebuild()

            total_filled = sum(
                1 for pos in POSITIONS for r in board_rows(board, pos)
                if board.Cells(r, BLOCK_START[pos] + OFF_PRICE).Value is not None
            )
            print("\nLeftover filled Price cells after cleanup (should be 0):", total_filled)

            wb.Close(SaveChanges=False)
        finally:
            pass
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
