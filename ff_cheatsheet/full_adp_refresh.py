#!/usr/bin/env python3
"""
Full ADP refresh:
  1. Run every fetcher in ff_adp/run_all.SOURCES live (Sleeper, ESPN, Yahoo,
     CBS, Fantrax, FFPC, BB10s, NFFC, NFFC Cutline, RTSports, Underdog).
  2. Merge into combined_adp.csv (same outlier-detection logic as run_all).
  3. Align player names with the Projections sheets (normalise_name match,
     prefer the Projections spelling/capitalization).
  4. Rewrite the workbook's ADP tab (A, C, D, B, E:P) from scratch.

A fetcher that fails (e.g. missing credentials) just prints a [WARN] and that
source's existing cached CSV is reused for this run.

Does NOT push to the separate Google Sheet (ff_adp/run_all.py's push_to_sheets) -
this script only updates the local combined_adp.csv and the Excel workbook.
"""

import csv
import os
import sys
from pathlib import Path

ADP_DIR = Path(__file__).resolve().parent.parent / "ff_adp"
sys.path.insert(0, str(ADP_DIR))

from run_all import (
    SOURCES, run_fetcher, load_csv, merge, OUTPUT_COLS, normalise_name,
)

import win32com.client as win32

BASE = ADP_DIR.parent
COMBINED = BASE / "combined_adp.csv"
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

xlUp = -4162

PROJECTION_SHEETS = ['QB Projections', 'RB Projections', 'WR Projections', 'TE Projections']

# ADP tab column -> combined_adp.csv column
COL_MAP = {
    'B': 'Consensus',
    'E': 'Underdog',
    'F': 'CBS',
    'G': 'ESPN',
    'H': 'FFPC',
    'I': 'BB10s',
    'J': 'NFL',
    'K': 'Yahoo!',
    'L': 'Sleeper',
    'M': 'Fantrax',
    'N': 'NFFC',
    'O': 'RTSports',
    'P': 'NFFC Cutline',
}


def main():
    print("[1/4] Fetching all ADP sources live...")
    os.chdir(ADP_DIR)
    for module_name, csv_file, adp_col, label, extra_args in SOURCES:
        run_fetcher(module_name, extra_args)

    print("\n[2/4] Merging into combined_adp.csv...")
    all_data = []
    for module_name, csv_file, adp_col, label, extra_args in SOURCES:
        data = load_csv(csv_file, adp_col)
        print(f"  {label:14s}: {len(data):>4} players")
        all_data.append((label, data))
    rows = merge(all_data)
    with open(COMBINED, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {len(rows)} rows -> {COMBINED}")

    print("\n[3/4] Aligning names with Projections sheets...")
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(str(WORKBOOK))
        try:
            proj_names = {}
            for sname in PROJECTION_SHEETS:
                sh = wb.Sheets(sname)
                last_row = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
                for r in range(2, last_row + 1):
                    name = sh.Cells(r, 1).Value
                    if name:
                        proj_names[normalise_name(name)] = name

            renamed = 0
            for row in rows:
                key = normalise_name(row['Player'])
                if key in proj_names and proj_names[key] != row['Player']:
                    row['Player'] = proj_names[key]
                    renamed += 1
            print(f"  Renamed {renamed} players to match Projections spelling")

            with open(COMBINED, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction='ignore')
                w.writeheader()
                w.writerows(rows)

            print("\n[4/4] Rewriting ADP tab...")
            adp = wb.Sheets("ADP")
            old_last_row = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
            new_last_row = 1 + len(rows)

            adp.Range(f"A2:A{new_last_row}").Value = [[r['Player']] for r in rows]
            adp.Range(f"C2:C{new_last_row}").Value = [[r['Position(s)']] for r in rows]
            adp.Range(f"D2:D{new_last_row}").Value = [[r['Team']] for r in rows]

            for col_letter, csv_col in COL_MAP.items():
                values = [[float(r[csv_col]) if r[csv_col] != '' else 999] for r in rows]
                adp.Range(f"{col_letter}2:{col_letter}{new_last_row}").Value = values

            if new_last_row < old_last_row:
                adp.Range(f"A{new_last_row + 1}:P{old_last_row}").ClearContents()

            print(f"  ADP tab rewritten: {len(rows)} rows (was {old_last_row - 1})")
            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
