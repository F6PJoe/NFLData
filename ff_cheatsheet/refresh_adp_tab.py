#!/usr/bin/env python3
"""
Re-sync the ADP tab's value columns (B-P) from combined_adp.csv, matched by
Player name (column A unchanged). Use after refreshing any source column(s)
in combined_adp.csv via ff_adp/refresh_sources.py.
"""

import csv
import re
import unicodedata
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

xlUp = -4162

# ADP!column letter -> combined_adp.csv column name (B-P, skipping C/D Position/Team)
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
    'Q': 'Sleeper_2QB',  # 2QB/SF ADP — Cheat Sheet M switches to this when Setup has >1 QB
}


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
    """Same normalisation as run_all.py so ADP tab names match combined_adp.csv keys."""
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


def main():
    # Build exact and normalised lookups so ADP tab names with different
    # capitalisation / suffixes (e.g. "Jonathan Taylor", "James Cook III")
    # still match combined_adp.csv entries ("Jon Taylor", "James Cook").
    combined_exact = {}
    combined_norm  = {}
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            combined_exact[row['Player']] = row
            combined_norm[_norm(row['Player'])] = row

    def lookup(player):
        return combined_exact.get(player) or combined_norm.get(_norm(player))

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            adp = wb.Sheets("ADP")
            last_row = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
            players = adp.Range(f"A2:A{last_row}").Value

            missing = 0
            for col_letter, csv_col in COL_MAP.items():
                values = []
                for (player,) in players:
                    row = lookup(player)
                    if row is None:
                        values.append([999])
                    else:
                        v = row.get(csv_col, '')
                        values.append([float(v) if v not in ('', '999') else 999])
                adp.Range(f"{col_letter}2:{col_letter}{last_row}").Value = values

            for (player,) in players:
                if player not in combined:
                    missing += 1

            print(f"ADP: re-synced columns B,E:P for {last_row - 1} rows "
                  f"({missing} players not found in combined_adp.csv, set to 999)")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
