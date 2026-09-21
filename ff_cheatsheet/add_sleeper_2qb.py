#!/usr/bin/env python3
"""
One-time setup: add Sleeper_2QB column (Q) to the ADP tab and update the
Cheat Sheet ADP formula (column M) to automatically switch between PPR ADP
and 2QB ADP based on the league's QB starter count in Setup.

Logic in updated M formula:
  - If Setup!E14 + Setup!E21 > 1 (total QB/SF starters exceeds 1):
      show Sleeper 2QB ADP (ADP tab column Q)
  - Otherwise:
      show whichever source is selected in Setup!B2 (existing IFS behaviour)

Run once after fetch_sleeper_adp.py and run_all.py have been updated to
produce combined_adp.csv with a Sleeper_2QB column.
"""

import csv
import re
import unicodedata
from pathlib import Path

import win32com.client as win32

BASE     = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

FIRST_NAME_ALIASES = {
    'chigoziem': 'chig',
    'cameron': 'cam', 'christopher': 'chris', 'matthew': 'matt',
    'mitchell': 'mitch', 'michael': 'mike', 'robert': 'rob',
    'william': 'will', 'nathaniel': 'nate', 'benjamin': 'ben',
    'joseph': 'joe', 'nicholas': 'nick', 'samuel': 'sam',
    'daniel': 'dan', 'alexander': 'alex', 'joshua': 'josh',
    'jonathan': 'jon', 'timothy': 'tim', 'anthony': 'tony',
    'steven': 'steve', 'zachary': 'zach',
}

def _norm(name):
    name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name.strip(), flags=re.IGNORECASE)
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    name = re.sub(r"[^a-z0-9 ]", '', name.lower())
    name = re.sub(r'\s+', ' ', name).strip()
    parts = name.split(' ', 1)
    if parts:
        parts[0] = FIRST_NAME_ALIASES.get(parts[0], parts[0])
        name = ' '.join(parts)
    return name

xlShiftToRight = -4161
xlFillCopy     = 0
xlUp           = -4162

# Column index of Sleeper_2QB once added at Q (A=1 … Q=17)
SLEEPER_2QB_IDX = 17


def main():
    combined_exact = {}
    combined_norm  = {}
    with open(BASE / "combined_adp.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            combined_exact[row["Player"]] = row
            combined_norm[_norm(row["Player"])] = row

    def lookup(player):
        return combined_exact.get(player) or combined_norm.get(_norm(player))

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            adp      = wb.Sheets("ADP")
            cs       = wb.Sheets("Cheat Sheet")
            last_row = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row

            # ── Add Sleeper_2QB column at Q if not already present ────────────
            if adp.Range("Q1").Value != "Sleeper_2QB":
                print("  Adding Sleeper_2QB column at Q on ADP tab...")
                adp.Range("Q1").Value = "Sleeper_2QB"
            else:
                print("  Sleeper_2QB column already exists at Q — refreshing values.")

            players = adp.Range(f"A2:A{last_row}").Value
            values  = []
            missing = 0
            for (player,) in players:
                row = lookup(player)
                if row is None:
                    values.append([999])
                    missing += 1
                else:
                    try:
                        v = float(row.get("Sleeper_2QB") or 999)
                        values.append([v])
                    except (ValueError, TypeError):
                        values.append([999])
                        missing += 1

            adp.Range(f"Q2:Q{last_row}").Value = values
            print(f"  ADP tab Q: wrote {last_row - 1} rows ({missing} unmatched -> 999)")

            # ── Build the updated Cheat Sheet M formula ───────────────────────
            # Inner IFS: existing source-switcher (unchanged — still used for 1QB leagues)
            lookup_range = "ADP!$A:$Q"  # widen to include new Q column
            sources = [
                ("Underdog",      5,  "E"),
                ("ESPN",          7,  "G"),
                ("CBS",           6,  "F"),
                ("Yahoo",        11,  "K"),
                ("Sleeper",      12,  "L"),
                ("NFL",          10,  "J"),
                ("FFPC",          8,  "H"),
                ("NFFC",         14,  "N"),
                ("NFFC Cutline", 16,  "P"),
                ("Fantrax",      13,  "M"),
                ("RTSports",     15,  "O"),
                ("Other",         2,  "B"),
            ]

            def branch(label, idx, col):
                vl = f"VLOOKUP($A2,{lookup_range},{idx},FALSE)"
                fb = f'MAXIFS(ADP!{col}:{col},ADP!{col}:{col},"<999")+1'
                return (
                    f'Setup!B$2="{label}",'
                    f"IFERROR(IF({vl}=999,{fb},{vl}),{fb})"
                )

            inner_ifs = "IFS(" + ",".join(branch(*s) for s in sources) + ")"

            # 2QB/SF branch: use Sleeper 2QB ADP (col Q); if missing (999),
            # fall back to PPR ADP from whichever source is selected in Setup!B2.
            # Non-QB players often lack 2QB data — PPR ADP is a good proxy since
            # non-QBs shift only ~3-5 picks in 2QB leagues.
            vl_2qb = f"VLOOKUP($A2,{lookup_range},{SLEEPER_2QB_IDX},FALSE)"
            fb_2qb = f'MAXIFS(ADP!Q:Q,ADP!Q:Q,"<999")+1'
            branch_2qb = (
                f"IFERROR("
                f"IF({vl_2qb}>=999,{inner_ifs},{vl_2qb}),"
                f"{inner_ifs})"
            )

            # Outer IF: switch to 2QB ADP when league has >1 QB starter or SF
            formula = (
                f"=IF(Setup!$E$14+Setup!$E$21>1,"
                f"{branch_2qb},"
                f"{inner_ifs})"
            )

            cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            cs.Range("M2").Formula = formula
            cs.Range("M2").AutoFill(cs.Range(f"M2:M{cs_last}"), xlFillCopy)
            print(f"  Cheat Sheet M2:M{cs_last}: formula updated (switches to 2QB ADP when E14+E21>1)")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
