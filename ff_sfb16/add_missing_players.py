"""Add players that exist in the full 10-source consensus but were never
added as rows to the SFB16 workbook's Projections tabs or Cheat Sheet tab
(those tabs' player pool was a one-time copy, not auto-synced — adding a
new source, like Draft Sharks, surfaces real players the pool never had).

For each Projections tab: copies an existing fully-formula-intact row
(row 2) down into new rows at the bottom via Excel's own Copy(Destination=)
— this lets Excel auto-adjust every relative formula (Score, ru1st/re1st,
rank, Player&Team) correctly for each new row, rather than me trying to
reconstruct formula text by hand. Then overwrites just the raw data columns
(Name/Team/Bye/Position + stat columns) with each new player's real values
from consensus. The new "Exp ..." bonus columns are left blank — they get
filled on the next run of build_sfb16_workbook.py (which matches by name).

Then does the same for the Cheat Sheet tab's separate player list, so the
new players show up there too (Cheat Sheet's own formulas pull each
player's Score from whichever Projections tab matches their Position).

No row-count cutoff is applied here — every consensus player missing from
the workbook gets added, regardless of how marginal. Trim later if desired.
"""
import pandas as pd
import win32com.client as win32

from workbook_common import (
    DRAFT_PROJ_DIR,
    NAME_ALIASES,
    POSITION_CONFIG,
    POSITION_CODE,
    SFB16_WORKBOOK,
    get_existing_names,
    last_data_row,
    normalize,
    write_range,
)


def find_missing(existing_names, consensus_df, name_col):
    """Consensus rows not already present on this tab (alias-aware)."""
    existing_norm = set()
    for name in existing_names:
        existing_norm.add(normalize(name))
        if name in NAME_ALIASES:
            existing_norm.add(normalize(NAME_ALIASES[name]))

    norm_col = consensus_df[name_col].apply(normalize)
    return consensus_df[~norm_col.isin(existing_norm)].copy()


def add_to_projections_tab(wb, tab_name, csv_name, stat_cols):
    ws = wb.Sheets(tab_name)
    last_row = last_data_row(ws)
    last_col = ws.UsedRange.Columns.Count

    df = pd.read_csv(DRAFT_PROJ_DIR / csv_name)
    name_col = df.columns[0]
    missing = find_missing(get_existing_names(ws), df, name_col)

    if missing.empty:
        print(f"  {tab_name}: nothing missing")
        return

    dest_start = last_row + 1
    dest_end = last_row + len(missing)

    source = ws.Range(ws.Cells(2, 1), ws.Cells(2, last_col))
    dest = ws.Range(ws.Cells(dest_start, 1), ws.Cells(dest_end, last_col))
    source.Copy(Destination=dest)

    pos_code = POSITION_CODE[tab_name]
    name_block = []
    stat_cols_sorted = sorted(stat_cols)
    stat_block = []
    for _, row in missing.iterrows():
        # A missing Bye (e.g. an unsigned free agent with no team/schedule)
        # should stay blank, not 0 — 0 isn't a real bye week and looks like
        # a data entry, not "doesn't apply." None clears the cell, and is
        # a real Python value (not float NaN), so it's safe via win32com —
        # unlike NaN, which silently becomes the literal 65535 in Excel.
        bye = None if pd.isna(row["Bye"]) else int(row["Bye"])
        name_block.append((row[name_col], row["Team"], bye, pos_code))
        stat_block.append(tuple(
            0.0 if pd.isna(row.get(stat_cols[c])) else float(row.get(stat_cols[c]))
            for c in stat_cols_sorted
        ))

    write_range(ws, dest_start, 1, dest_end, 4, name_block)
    write_range(ws, dest_start, stat_cols_sorted[0], dest_end, stat_cols_sorted[-1], stat_block)

    print(f"  {tab_name}: added {len(missing)} players (rows {dest_start}-{dest_end})")


def add_to_cheat_sheet(wb):
    """Cheat Sheet's player list is separate from the Projections tabs —
    same missing-player set, but only needs Name/Team/Bye/Pos; every other
    column is a formula that pulls from the matching Projections tab."""
    ws = wb.Sheets("Cheat Sheet")
    last_row = last_data_row(ws)
    last_col = ws.UsedRange.Columns.Count

    # Source of truth here is "every consensus player for each position",
    # checked against what's missing from the Cheat Sheet's OWN list — not
    # against the Projections tabs, which were just filled in by the
    # earlier step and would make everything look "not missing" anymore.
    existing_on_cheat_sheet = get_existing_names(ws)
    all_missing = []
    for tab_name, (csv_name, _) in POSITION_CONFIG.items():
        df = pd.read_csv(DRAFT_PROJ_DIR / csv_name)
        name_col = df.columns[0]
        missing = find_missing(existing_on_cheat_sheet, df, name_col)
        for _, row in missing.iterrows():
            all_missing.append((row[name_col], row["Team"], row["Bye"], POSITION_CODE[tab_name]))

    if not all_missing:
        print("  Cheat Sheet: nothing missing")
        return

    dest_start = last_row + 1
    dest_end = last_row + len(all_missing)

    source = ws.Range(ws.Cells(2, 1), ws.Cells(2, last_col))
    dest = ws.Range(ws.Cells(dest_start, 1), ws.Cells(dest_end, last_col))
    source.Copy(Destination=dest)

    rows = [(name, team, None if pd.isna(bye) else int(bye), pos) for name, team, bye, pos in all_missing]
    write_range(ws, dest_start, 1, dest_end, 4, rows)

    print(f"  Cheat Sheet: added {len(all_missing)} players (rows {dest_start}-{dest_end})")


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(SFB16_WORKBOOK))
    try:
        print("Adding missing players to Projections tabs...")
        for tab_name, (csv_name, stat_cols) in POSITION_CONFIG.items():
            add_to_projections_tab(wb, tab_name, csv_name, stat_cols)

        print("Adding missing players to Cheat Sheet...")
        add_to_cheat_sheet(wb)

        wb.Save()
        print(f"Saved {SFB16_WORKBOOK}")
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()


if __name__ == "__main__":
    main()
