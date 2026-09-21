#!/usr/bin/env python3
"""
1. Rename ADP!A entries to match the Projections sheets' name spelling/
   capitalization (e.g. "A.j. Brown" -> "A.J. Brown") so the Cheat Sheet's
   VLOOKUP($A2, ADP!$A:$P, ...) matches.
2. Copy the full player pool (Name, Team, Bye, Pos) from the QB/RB/WR/TE
   Projections sheets into the Cheat Sheet (columns A-D), sorted by
   Consensus ADP (players with no ADP sorted to the bottom by projected
   score), then AutoFill the formula columns (E:U) down to the new last row.
   Conditional formatting on column D is range-based (D2:D996) and already
   covers the new rows, so it's untouched.
"""

import csv
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

xlUp = -4162
xlFillCopy = 0

# ADP name -> Projections name (same as ff_adp/fix_adp_names.py)
RENAMES = {
    'Matt Stafford': 'Matthew Stafford',
    'C.j. Stroud': 'C.J. Stroud',
    'Dan Jones': 'Daniel Jones',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'J.j. McCarthy': 'J.J. McCarthy',
    'Tony Richardson Sr.': 'Anthony Richardson Sr.',
    'Jon Taylor': 'Jonathan Taylor',
    "De'von Achane": "De'Von Achane",
    'James Cook': 'James Cook III',
    "D'andre Swift": "D'Andre Swift",
    'Treveyon Henderson': 'TreVeyon Henderson',
    'Rj Harvey': 'RJ Harvey',
    'J.k. Dobbins': 'J.K. Dobbins',
    'Marshawn Lloyd': 'MarShawn Lloyd',
    'Dj Giddens': 'DJ Giddens',
    'Nick Singleton': 'Nicholas Singleton',
    'Aj Dillon': 'AJ Dillon',
    'Lequint Allen Jr.': 'LeQuint Allen Jr.',
    "J'mari Taylor": "J'Mari Taylor",
    'Rob Henry': 'Robert Henry Jr.',
    'Mike Carter': 'Michael Carter',
    "Ja'marr Chase": "Ja'Marr Chase",
    'Amon-ra St. Brown': 'Amon-Ra St. Brown',
    'Ceedee Lamb': 'CeeDee Lamb',
    'A.j. Brown': 'A.J. Brown',
    'Devonta Smith': 'DeVonta Smith',
    'Dj Moore': 'DJ Moore',
    'Dk Metcalf': 'DK Metcalf',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Chris Godwin': 'Chris Godwin Jr.',
    'Mike Wilson': 'Michael Wilson',
    "Wan'dale Robinson": "Wan'Dale Robinson",
    'Matt Golden': 'Matthew Golden',
    'K.c. Concepcion': 'KC Concepcion',
    'Tre Harris': "Tre' Harris",
    "Ja'kobi Lane": "Ja'Kobi Lane",
    "De'zhaun Stribling": "De'Zhaun Stribling",
    'Kavontae Turpin': 'KaVontae Turpin',
    'Josh Palmer': 'Joshua Palmer',
    'Demario Douglas': 'DeMario Douglas',
    'Mitch Tinsley': 'Mitchell Tinsley',
    'Keandre Lambert-Smith': 'KeAndre Lambert-Smith',
    'Cj Daniels': 'CJ Daniels',
    'Juju Smith-Schuster': 'JuJu Smith-Schuster',
    'Cj Williams': 'CJ Williams',
    'Oronde Gadsden II': 'Oronde Gadsden',
    'T.j. Hockenson': 'T.J. Hockenson',
    'Aj Barner': 'AJ Barner',
    'Mike Mayer': 'Michael Mayer',
    "Ja'tavion Sanders": "Ja'Tavion Sanders",
    'Dan Bellinger': 'Daniel Bellinger',
    'Mike Trigg': 'Michael Trigg',
    'Matt Hibner': 'Matthew Hibner',
}

PROJECTION_SHEETS = ['QB Projections', 'RB Projections', 'WR Projections', 'TE Projections']


def main():
    # Consensus ADP lookup, keyed by exact (post-rename) player name
    consensus = {}
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            c = row.get('Consensus', '')
            if c != '':
                consensus[row['Player']] = float(c)

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            # ── 1. Rename ADP!A entries ──────────────────────────────────────
            adp = wb.Sheets("ADP")
            adp_last_row = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
            renamed = 0
            for r in range(2, adp_last_row + 1):
                name = adp.Cells(r, 1).Value
                if name in RENAMES:
                    adp.Cells(r, 1).Value = RENAMES[name]
                    renamed += 1
            print(f"ADP: renamed {renamed} player names to match Projections spelling")

            # ── 2. Collect full player pool from Projections ────────────────
            players = []  # (Player, Team, Bye, Pos, sortkey)
            for sname in PROJECTION_SHEETS:
                sh = wb.Sheets(sname)
                last_row = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
                rng = sh.Range(f"A2:F{last_row}").Value
                for row in rng:
                    name, team, bye, pos, _, score = row[0], row[1], row[2], row[3], row[4], row[5]
                    if not name:
                        continue
                    if name in consensus:
                        sortkey = consensus[name]
                    else:
                        try:
                            sortkey = 1000 - (float(score) / 1000.0)
                        except (TypeError, ValueError):
                            sortkey = 1000.0
                    players.append((name, team, bye, pos, sortkey))

            players.sort(key=lambda p: p[4])
            print(f"Collected {len(players)} players from Projections")

            # ── 3. Write A2:D into Cheat Sheet ───────────────────────────────
            cs = wb.Sheets("Cheat Sheet")
            old_last_row = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            new_last_row = 1 + len(players)

            out = [[p[0], p[1], p[2], p[3]] for p in players]
            cs.Range(f"A2:D{new_last_row}").Value = out

            # If the new list is shorter than the old one, clear leftover rows
            if new_last_row < old_last_row:
                cs.Range(f"A{new_last_row + 1}:U{old_last_row}").ClearContents()

            # ── 4. AutoFill formula columns E:U down to the new last row ────
            cs.Range("E2:U2").AutoFill(cs.Range(f"E2:U{new_last_row}"), xlFillCopy)
            print(f"Cheat Sheet: wrote {len(players)} players (A2:D{new_last_row}), "
                  f"AutoFilled E:U to row {new_last_row}")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
