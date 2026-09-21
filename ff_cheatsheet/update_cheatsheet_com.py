#!/usr/bin/env python3
"""
Fix the Cheat Sheet's ADP formula (M column) so that when a player has no
ADP for the selected source - VLOOKUP misses, or the source's value is the
999 "no data" sentinel - it falls back to that source's max real ADP
(excluding 999s) + 1, instead of returning 999 itself.
"""

import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"

xlFillCopy = 0

# Setup!B2 option -> (VLOOKUP column index in ADP!A:N, ADP column letter for MAXIFS range)
SOURCES = [
    ("Underdog", 5, "E"),
    ("ESPN", 7, "G"),
    ("CBS", 6, "F"),
    ("Yahoo", 11, "K"),
    ("Sleeper", 12, "L"),
    ("NFL", 10, "J"),
    ("FFPC", 8, "H"),
    ("NFFC", 14, "N"),
    ("NFFC Cutline", 2, "B"),
    ("Fantrax", 13, "M"),
    ("RTSports", 2, "B"),
    ("Other", 2, "B"),
]


def branch(setup_value, idx, col):
    vlookup = f"VLOOKUP($A2,ADP!$A:$N,{idx},FALSE)"
    fallback = f'MAXIFS(ADP!{col}:{col},ADP!{col}:{col},"<999")+1'
    return (
        f'Setup!B$2="{setup_value}",'
        f"IFERROR(IF({vlookup}=999,{fallback},{vlookup}),{fallback})"
    )


CHEAT_SHEET_ADP_FORMULA = "=IFS(" + ",".join(branch(*s) for s in SOURCES) + ")"


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            ws = wb.Sheets("Cheat Sheet")
            last_row = ws.Cells(ws.Rows.Count, 1).End(-4162).Row  # xlUp
            ws.Range("M2").Formula = CHEAT_SHEET_ADP_FORMULA
            src = ws.Range("M2")
            dest = ws.Range(f"M2:M{last_row}")
            src.AutoFill(dest, xlFillCopy)
            print(f"Cheat Sheet: rewrote ADP formula M2:M{last_row}")
            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
