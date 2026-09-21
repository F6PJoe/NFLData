#!/usr/bin/env python3
"""
Apply PAR v2 to the Cheat Sheet.

Q  (Overall Value)  = Positional PAR — points above the last startable player
                      at that position. Negative = below starter quality but
                      still draftable. Updates live as players are deleted.
R  (QB Value)       = Within-QB z-score vs the draftable QB pool (top ~25 QBs)
S  (RB Value)       = Within-RB z-score vs the draftable RB pool (top ~60 RBs)
T  (WR Value)       = Within-WR z-score vs the draftable WR pool (top ~84 WRs)
U  (TE Value)       = Within-TE z-score vs the draftable TE pool (top ~26 TEs)
V  (PAR)            = same as Q — kept as a visible PAR reference column

Calculations tab layout after this script:
  Row 9  : PAR replacement rank  (shallow — starters only, for Q)
  Row 10 : PAR replacement score (LARGE/IF, dynamic)
  Row 11 : z-score cutoff rank   (deep — includes bench spots, for R-U)
  Row 12 : z-score cutoff score  (LARGE/IF, dynamic)
  Row 13 : positional mean       (AVERAGEIF of above-cutoff players, for R-U)
  Row 14 : positional stdev      (STDEV.P/IF, dynamic, for R-U)
"""

import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"
xlUp = -4162

# Cheat Sheet positional score columns (H=QB, I=RB, J=WR, K=TE), -999 for others
POS_COLS = {"QB": ("C", "H"), "RB": ("D", "I"), "WR": ("E", "J"), "TE": ("F", "K")}


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            cs   = wb.Sheets("Cheat Sheet")
            calc = wb.Sheets("Calculations")
            last_row = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            print(f"Cheat Sheet: {last_row - 1} players")

            # ── CALCULATIONS TAB ─────────────────────────────────────────────

            calc.Range("A8").Value = "PAR + Positional Z-Score"
            for col in ["B","C","D","E","F"]:
                calc.Range(f"{col}8").Value = {
                    "B": "overall", "C": "QB", "D": "RB", "E": "WR", "F": "TE"
                }[col]

            # Row 9 — PAR replacement rank (starter depth only)
            # QB: teams × (QB starters + SF) + 3 backup buffer
            # RB: teams × (RB + RB/WR flex × 0.5 + ...)
            # WR: teams × (WR + WR/TE flex × 0.5 + ...)
            # TE: teams × (TE + WR/TE flex × 0.5) + 2 buffer
            calc.Range("A9").Value = "PAR repl rank"
            calc.Range("B9").Value = ""
            calc.Range("C9").Formula = "=ROUND(Setup!$E$11*(Setup!$E$14+Setup!$E$21)+3,0)"
            calc.Range("D9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$15+Setup!$E$18*0.5"
                "+Setup!$E$19*0.33+Setup!$E$21*0.25),0)"
            )
            calc.Range("E9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$16+Setup!$E$18*0.5"
                "+Setup!$E$19*0.33+Setup!$E$20*0.5+Setup!$E$21*0.25),0)"
            )
            calc.Range("F9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$17+Setup!$E$20*0.5"
                "+Setup!$E$21*0.1)+2,0)"
            )

            # Row 10 — PAR replacement score (live, updates as players deleted)
            calc.Range("A10").Value = "PAR repl score"
            calc.Range("B10").Value = ""
            for calc_col, cs_col in [("C","H"),("D","I"),("E","J"),("F","K")]:
                rank_ref = f"{calc_col}9"
                calc.Range(f"{calc_col}10").ClearContents()
                calc.Range(f"{calc_col}10").FormulaArray = (
                    f"=LARGE(IF('Cheat Sheet'!${cs_col}$2:${cs_col}$700<>-999,"
                    f"'Cheat Sheet'!${cs_col}$2:${cs_col}$700),{rank_ref})"
                )
            print("  Calculations rows 9-10 (PAR replacement) written.")

            # Row 11 — z-score cutoff rank (deep — starters + bench spots)
            # Roughly: teams × positional_starters × 2.5 for RB, × 2 for WR, × 2+1 for QB/TE
            calc.Range("A11").Value = "z-score cutoff rank"
            calc.Range("B11").Value = ""
            calc.Range("C11").Formula = "=ROUND(Setup!$E$11*(Setup!$E$14+Setup!$E$21)*2+1,0)"
            calc.Range("D11").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$15+Setup!$E$18*0.5"
                "+Setup!$E$19*0.33+Setup!$E$21*0.25)*2.5,0)"
            )
            calc.Range("E11").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$16+Setup!$E$18*0.5"
                "+Setup!$E$19*0.33+Setup!$E$20*0.5+Setup!$E$21*0.25)*2,0)"
            )
            calc.Range("F11").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$17+Setup!$E$20*0.5"
                "+Setup!$E$21*0.1)*2+2,0)"
            )

            # Row 12 — z-score cutoff score (Nth best score at position, dynamic)
            calc.Range("A12").Value = "z-score cutoff score"
            calc.Range("B12").Value = ""
            for calc_col, cs_col in [("C","H"),("D","I"),("E","J"),("F","K")]:
                rank_ref = f"{calc_col}11"
                calc.Range(f"{calc_col}12").ClearContents()
                calc.Range(f"{calc_col}12").FormulaArray = (
                    f"=LARGE(IF('Cheat Sheet'!${cs_col}$2:${cs_col}$700<>-999,"
                    f"'Cheat Sheet'!${cs_col}$2:${cs_col}$700),{rank_ref})"
                )

            # Row 13 — positional mean (average of players above z-score cutoff)
            calc.Range("A13").Value = "positional mean (top N)"
            calc.Range("B13").Value = ""
            for calc_col, cs_col in [("C","H"),("D","I"),("E","J"),("F","K")]:
                cutoff_ref = f"{calc_col}12"
                calc.Range(f"{calc_col}13").Formula = (
                    f"=AVERAGEIF('Cheat Sheet'!${cs_col}$2:${cs_col}$700,"
                    f"\">=\"&{cutoff_ref})"
                )

            # Row 14 — positional stdev (of players above z-score cutoff)
            calc.Range("A14").Value = "positional stdev (top N)"
            calc.Range("B14").Value = ""
            for calc_col, cs_col in [("C","H"),("D","I"),("E","J"),("F","K")]:
                cutoff_ref = f"{calc_col}12"
                calc.Range(f"{calc_col}14").ClearContents()
                calc.Range(f"{calc_col}14").FormulaArray = (
                    f"=STDEV.P(IF('Cheat Sheet'!${cs_col}$2:${cs_col}$700>={cutoff_ref},"
                    f"'Cheat Sheet'!${cs_col}$2:${cs_col}$700,\"\"))"
                )
            print("  Calculations rows 11-14 (z-score population) written.")

            # ── CHEAT SHEET Q — Positional PAR, negatives allowed ────────────
            cs.Range(f"Q2:Q{last_row}").ClearContents()
            cs.Range(f"Q2:Q{last_row}").Formula = (
                '=IFS(D2="QB",G2-Calculations!C$10,'
                'D2="RB",G2-Calculations!D$10,'
                'D2="WR",G2-Calculations!E$10,'
                'D2="TE",G2-Calculations!F$10)'
            )
            print("  Q column (PAR, negatives allowed) written.")

            # ── CHEAT SHEET R–U — Within-position z-score ────────────────────
            # Compares player against the draftable pool at their position only.
            # Positive = above average draftable player at that position.
            # Negative = below average draftable player (borderline/bench).
            for col, pos, calc_col in [
                ("R","QB","C"), ("S","RB","D"), ("T","WR","E"), ("U","TE","F")
            ]:
                cs.Range(f"{col}2:{col}{last_row}").Formula = (
                    f'=IF(D2="{pos}",'
                    f'($G2-Calculations!{calc_col}$13)/Calculations!{calc_col}$14,'
                    f'1-1000)'
                )
            print("  R-U columns (within-position z-score) written.")

            # ── CHEAT SHEET V — PAR label (same as Q, explicit reference col) ─
            cs.Range("V1").Value = "PAR"
            cs.Range(f"V2:V{last_row}").Formula = (
                '=IFS(D2="QB",G2-Calculations!C$10,'
                'D2="RB",G2-Calculations!D$10,'
                'D2="WR",G2-Calculations!E$10,'
                'D2="TE",G2-Calculations!F$10)'
            )
            print("  V column (PAR label reference) written.")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
