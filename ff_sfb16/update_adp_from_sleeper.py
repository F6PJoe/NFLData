"""Rewrite the SFB16 workbook's ADP tab to use only the compiled Sleeper
ADP (from compile_sleeper_adp.py / sleeper_compiled_adp.csv) — SFB16 uses one
ADP source, not the multi-site consensus the regular cheat sheet uses.

Replaces the ADP tab entirely with 4 columns: Player, Position, Team, ADP.
Simplifies the Cheat Sheet tab's "ADP" column formula from the big multi-site
IFS/VLOOKUP branch (keyed off Setup!B2's site dropdown) down to a single
VLOOKUP against the new ADP tab — undrafted players still fall back to
(worst ADP + 1), same behavior as before, just one source.

Run compile_sleeper_adp.py first to produce sleeper_compiled_adp.csv.

Name matching: the Cheat Sheet tab's player list comes from a different
source (Joe Bond Ranks / consensus projections) than Sleeper's own player
directory, so spellings don't always match exactly — the live VLOOKUP on
Cheat Sheet falls back to (worst ADP + 1) whenever they don't, silently
making a real top-50 player look completely undrafted. Two patterns
account for nearly all of these:
  1. Suffix differences (Jr./Sr./II/III/IV, periods, apostrophes) — handled
     generically below by matching Cheat Sheet names against ADP names with
     suffixes/punctuation stripped, then writing a duplicate ADP row under
     the exact Cheat Sheet spelling so the VLOOKUP succeeds either way.
  2. Nickname differences (e.g. "Cameron Ward" vs. Sleeper's "Cam Ward") —
     no generic rule catches these; NICKNAME_ALIASES is a manually
     maintained list, same pattern as NAME_ALIASES in build_sfb16_workbook.py.
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd
import win32com.client as win32

from workbook_common import get_existing_names, last_data_row, write_range

BASE = Path(__file__).resolve().parent
CHEAT_SHEET_DIR = Path(r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet")
SFB16_WORKBOOK = CHEAT_SHEET_DIR / "2026-Football-SFB16-Cheat-Sheet-working-copy.xlsm"
SLEEPER_ADP_CSV = BASE / "sleeper_compiled_adp.csv"

NEW_ADP_FORMULA = (
    '=IFERROR(VLOOKUP(A{row},ADP!$A:$D,4,FALSE),'
    '_xlfn.MAXIFS(ADP!$D:$D,ADP!$D:$D,"<999")+1)'
)

# Cheat Sheet spelling -> Sleeper spelling, for nickname differences a
# suffix-stripping normalizer can't catch on its own.
NICKNAME_ALIASES = {
    "Cameron Ward": "Cam Ward",
    "Nathaniel Dell": "Tank Dell",
    "Chigoziem Okonkwo": "Chig Okonkwo",
}


def _normalize(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().replace(".", "").replace("'", "")
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def get_cheat_sheet_names(wb):
    return get_existing_names(wb.Sheets("Cheat Sheet"))


def add_name_alias_rows(df, cheat_sheet_names):
    """For every Cheat Sheet name not already an exact match in df, add a
    duplicate row under that exact spelling if a suffix-normalized or
    known-nickname match exists in df. Returns the expanded dataframe."""
    by_exact = set(df["Player"])
    norm_to_row = {}
    for row in df.itertuples(index=False):
        norm_to_row.setdefault(_normalize(row.Player), row)

    extra_rows = []
    matched = []
    for cs_name in cheat_sheet_names:
        if cs_name in by_exact:
            continue
        source_row = None
        if cs_name in NICKNAME_ALIASES:
            sleeper_name = NICKNAME_ALIASES[cs_name]
            match = df[df["Player"] == sleeper_name]
            if not match.empty:
                source_row = match.iloc[0]
        else:
            norm = _normalize(cs_name)
            if norm in norm_to_row:
                source_row = norm_to_row[norm]
        if source_row is not None:
            extra_rows.append({
                "Player": cs_name,
                "Position": source_row.Position if hasattr(source_row, "Position") else source_row["Position"],
                "Team": source_row.Team if hasattr(source_row, "Team") else source_row["Team"],
                "ADP": source_row.ADP if hasattr(source_row, "ADP") else source_row["ADP"],
            })
            matched.append((cs_name, source_row.Player if hasattr(source_row, "Player") else source_row["Player"]))

    if matched:
        print(f"  Added {len(matched)} name-alias rows so VLOOKUP matches both spellings:")
        for cs_name, sleeper_name in matched:
            print(f"    {cs_name!r} -> {sleeper_name!r}")

    if extra_rows:
        df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)
    return df


def rewrite_adp_tab(wb, df):
    ws = wb.Sheets("ADP")
    ws.Cells.ClearContents()  # contents only — preserve existing formatting

    # A blank/NaN Team (e.g. an unsigned free agent) must never reach Excel
    # via win32com as a raw float NaN — it gets stored as the literal value
    # 65535 instead of erroring, silently corrupting that cell (and any
    # formula that reads it). Same failure mode as the earlier 65535 bug.
    df = df.copy()
    df["Team"] = df["Team"].fillna("FA").replace("", "FA")

    headers = ["Player", "Position", "Team", "ADP"]
    write_range(ws, 1, 1, 1, 4, [tuple(headers)])

    rows = [(row.Player, row.Position, row.Team, float(row.ADP)) for row in df.itertuples(index=False)]
    write_range(ws, 2, 1, 1 + len(rows), 4, rows)

    print(f"  ADP tab rewritten: {len(df)} players, columns A:D")


def simplify_cheat_sheet_adp_formula(wb):
    ws = wb.Sheets("Cheat Sheet")
    last_row = last_data_row(ws)

    # Find the "ADP" column by header text rather than hardcoding N, in case
    # the layout shifts.
    last_col = ws.UsedRange.Columns.Count
    adp_col = None
    for c in range(1, last_col + 1):
        if ws.Cells(1, c).Value == "ADP":
            adp_col = c
            break
    if adp_col is None:
        raise RuntimeError('Could not find an "ADP" column header on the Cheat Sheet tab')

    formulas = [(NEW_ADP_FORMULA.format(row=row),) for row in range(2, last_row + 1)]
    write_range(ws, 2, adp_col, last_row, adp_col, formulas, as_formula=True)

    print(f"  Cheat Sheet ADP formula simplified, column {adp_col}, rows 2-{last_row}")


def main():
    if not SLEEPER_ADP_CSV.exists():
        print(f"{SLEEPER_ADP_CSV} not found — run compile_sleeper_adp.py first.")
        return
    df = pd.read_csv(SLEEPER_ADP_CSV)[["Player", "Position", "Team", "ADP"]].sort_values("ADP")

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(SFB16_WORKBOOK))
    try:
        print("Checking Cheat Sheet names for ADP alias matches...")
        cheat_sheet_names = get_cheat_sheet_names(wb)
        df = add_name_alias_rows(df, cheat_sheet_names)

        print("Rewriting ADP tab...")
        rewrite_adp_tab(wb, df)
        print("Simplifying Cheat Sheet ADP formula...")
        simplify_cheat_sheet_adp_formula(wb)
        wb.Save()
        print(f"Saved {SFB16_WORKBOOK}")
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()


if __name__ == "__main__":
    main()
