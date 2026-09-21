#!/usr/bin/env python3
"""
Add RTSports and NFFC Cutline as new columns O/P on the ADP tab (the existing
empty column O and the MAX-summary block shift right to Q:W), populate them
from combined_adp.csv (matched by Player, same row order as the ADP tab),
then update the Cheat Sheet's ADP formula (M column) so the "RTSports" and
"NFFC Cutline" Setup!B2 options VLOOKUP into the real new columns instead of
falling back to Consensus, and widen the ADP!$A:$N lookup range to ADP!$A:$P.
"""

import csv
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

xlShiftToRight = -4161
xlFillCopy = 0
xlUp = -4162


def main():
    # Load combined_adp.csv keyed by Player name
    combined = {}
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            combined[row['Player']] = row

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            adp = wb.Sheets("ADP")
            last_row = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row

            # Insert two new columns at O (current empty separator + summary block shift to Q:W)
            adp.Columns("O:P").Insert(Shift=xlShiftToRight)

            adp.Range("O1").Value = "RTSports"
            adp.Range("P1").Value = "NFFC Cutline"

            players = adp.Range(f"A2:A{last_row}").Value
            out_o = []
            out_p = []
            missing = 0
            for (player,) in players:
                row = combined.get(player)
                if row is None:
                    missing += 1
                    out_o.append([999])
                    out_p.append([999])
                else:
                    out_o.append([float(row['RTSports'])])
                    out_p.append([float(row['NFFC Cutline'])])

            adp.Range(f"O2:O{last_row}").Value = out_o
            adp.Range(f"P2:P{last_row}").Value = out_p
            print(f"ADP: wrote RTSports/NFFC Cutline columns O/P ({last_row - 1} rows, "
                  f"{missing} unmatched players set to 999)")

            # Add summary MAX formulas for the two new columns, matching the existing block style.
            # The summary block now lives at Q:W (was P:V before the insert)
            last_summary_row = adp.Cells(adp.Rows.Count, 17).End(xlUp).Row  # col Q
            new_row = last_summary_row + 1
            adp.Cells(new_row, 17).Value = "RTSports"
            adp.Cells(new_row, 18).Value = "=MAX(O:O)"
            adp.Cells(new_row + 1, 17).Value = "NFFC Cutline"
            adp.Cells(new_row + 1, 18).Value = "=MAX(P:P)"

            # ── Cheat Sheet ADP formula ──────────────────────────────────────
            SOURCES = [
                ("Underdog", 5, "E"),
                ("ESPN", 7, "G"),
                ("CBS", 6, "F"),
                ("Yahoo", 11, "K"),
                ("Sleeper", 12, "L"),
                ("NFL", 10, "J"),
                ("FFPC", 8, "H"),
                ("NFFC", 14, "N"),
                ("NFFC Cutline", 16, "P"),
                ("Fantrax", 13, "M"),
                ("RTSports", 15, "O"),
                ("Other", 2, "B"),
            ]

            def branch(setup_value, idx, col):
                vlookup = f"VLOOKUP($A2,ADP!$A:$P,{idx},FALSE)"
                fallback = f'MAXIFS(ADP!{col}:{col},ADP!{col}:{col},"<999")+1'
                return (
                    f'Setup!B$2="{setup_value}",'
                    f"IFERROR(IF({vlookup}=999,{fallback},{vlookup}),{fallback})"
                )

            formula = "=IFS(" + ",".join(branch(*s) for s in SOURCES) + ")"

            cs = wb.Sheets("Cheat Sheet")
            cs_last_row = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            cs.Range("M2").Formula = formula
            cs.Range("M2").AutoFill(cs.Range(f"M2:M{cs_last_row}"), xlFillCopy)
            print(f"Cheat Sheet: rewrote ADP formula M2:M{cs_last_row}")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
