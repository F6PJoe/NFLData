"""Refresh every existing player's raw stat line (Att/Yds/TD/Tgt/Rec/etc.)
on the SFB16 workbook's Projections tabs from the current consensus data.

Previously this script pushed the SFB16 bonus-category columns (Exp 300+
Pass Yd Games etc.) as Python-computed values. Those are now live Excel
formulas (see setup_bonus_formulas.py) that recalculate automatically from
the raw stat columns — so this script's job is simpler now: just keep the
raw stat columns themselves current every time projections are refreshed.
Brand new players (not yet a row on any tab) are handled separately by
add_missing_players.py.

Copies the live base workbook to a new SFB16-specific file (only if it
doesn't already exist), then opens it via Excel COM (win32com) — never
openpyxl for saving, since that strips Data Validation/Conditional
Formatting (see ff_cheatsheet/CLAUDE.md).
"""
import shutil

import pandas as pd
import win32com.client as win32

from workbook_common import (
    DRAFT_PROJ_DIR,
    NAME_ALIASES,
    POSITION_CONFIG,
    SFB16_WORKBOOK,
    CHEAT_SHEET_DIR,
    last_data_row,
    normalize,
    read_range,
    write_range,
)

SOURCE_WORKBOOK = CHEAT_SHEET_DIR / "2026-Football-Cheat-Sheet-working-copy.xlsm"


def ensure_workbook_copy():
    if SFB16_WORKBOOK.exists():
        print(f"Using existing {SFB16_WORKBOOK}")
        return
    print(f"Copying {SOURCE_WORKBOOK.name} -> {SFB16_WORKBOOK.name}")
    shutil.copy2(SOURCE_WORKBOOK, SFB16_WORKBOOK)


def refresh_stats(ws, tab_name, csv_name, stat_cols):
    df = pd.read_csv(DRAFT_PROJ_DIR / csv_name)
    name_col = df.columns[0]  # "QB"/"RB"/"WR"/"TE" header holds the player name
    by_name = df.set_index(name_col)
    norm_to_name = {}
    for name in by_name.index:
        norm_to_name.setdefault(normalize(name), name)

    last_row = last_data_row(ws)
    if last_row < 2:
        print(f"  {tab_name}: no rows")
        return

    # stat_cols' keys are a contiguous column block (e.g. 7-15) — bulk
    # read it (and column A) once, build the whole replacement block in
    # memory, then bulk-write it back in one shot. This is the difference
    # between ~2 COM round-trips and thousands (one per cell) for a
    # several-hundred-row tab.
    cols = sorted(stat_cols)
    start_col, end_col = cols[0], cols[-1]
    assert cols == list(range(start_col, end_col + 1)), "stat_cols must be a contiguous block"

    names = [r[0] for r in read_range(ws, 2, 1, last_row, 1)]
    existing_block = read_range(ws, 2, start_col, last_row, end_col)

    new_block = []
    missing = []
    updated = 0
    for player, existing_row in zip(names, existing_block):
        if not player:
            new_block.append(existing_row)
            continue
        lookup_name = NAME_ALIASES.get(player, player)
        if lookup_name not in by_name.index:
            lookup_name = norm_to_name.get(normalize(player))
        if lookup_name is None or lookup_name not in by_name.index:
            missing.append(player)
            new_block.append(existing_row)
            continue
        values = by_name.loc[lookup_name]
        row_vals = []
        for col in cols:
            val = values.get(stat_cols[col])
            row_vals.append(0.0 if pd.isna(val) else float(val))
        new_block.append(tuple(row_vals))
        updated += 1

    write_range(ws, 2, start_col, last_row, end_col, new_block)

    print(f"  {tab_name}: refreshed {updated} players")
    if missing:
        print(f"  {tab_name}: {len(missing)} players on the tab not found in {csv_name}: {missing[:10]}")


def main():
    ensure_workbook_copy()

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(SFB16_WORKBOOK))
    try:
        for tab_name, (csv_name, stat_cols) in POSITION_CONFIG.items():
            print(f"Refreshing {tab_name}...")
            ws = wb.Sheets(tab_name)
            refresh_stats(ws, tab_name, csv_name, stat_cols)
        wb.Save()
        print(f"Saved {SFB16_WORKBOOK}")
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()


if __name__ == "__main__":
    main()
