#!/usr/bin/env python3
"""
One-time script: replace z-score value formulas with Points Above Replacement (PAR).

Changes made:
  Calculations tab
    Row 8  - update labels
    Row 9  - replacement rank per position (derived from Setup roster/team settings)
    Row 10 - replacement score per position (LARGE/IF array formula, live-updates as
             players are deleted from Cheat Sheet during draft)

  Cheat Sheet tab
    Q  (Overall Value)     - MAX(0, score - positional replacement score)
    R  (QB Value)          - same PAR, only non-zero for QBs
    S  (RB Value)          - same PAR, only non-zero for RBs
    T  (WR Value)          - same PAR, only non-zero for WRs
    U  (TE Value)          - same PAR, only non-zero for TEs
    V:W (new overall value rank / new overall value) - deleted (duplicates, hidden)

The positional multiplier columns in Setup (I:P) are no longer referenced by any
value formula after this change; they can be left hidden or cleared separately.
"""

import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"
xlUp = -4162


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

            # Row 8 — update section label
            calc.Range("A8").Value = "PAR (Points Above Replacement)"

            # Row 9 — replacement rank per position
            # Driven by Setup: E11=teams, E14=QB, E15=RB, E16=WR, E17=TE,
            #                  E18=RB/WR flex, E19=RB/WR, E20=WR/TE, E21=SF
            calc.Range("A9").Value = "repl rank"
            calc.Range("B9").Value = ""  # no single overall rank
            # QB: teams × (QB starters + SF starters) + 3 backup buffer
            calc.Range("C9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$14+Setup!$E$21)+3,0)"
            )
            # RB: teams × (RB starters + half of RB/WR flex slots)
            calc.Range("D9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$15"
                "+Setup!$E$18*0.5+Setup!$E$19*0.33+Setup!$E$21*0.25),0)"
            )
            # WR: teams × (WR starters + other half of RB/WR flex + half of WR/TE flex)
            calc.Range("E9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$16"
                "+Setup!$E$18*0.5+Setup!$E$19*0.33"
                "+Setup!$E$20*0.5+Setup!$E$21*0.25),0)"
            )
            # TE: teams × (TE starters + half of WR/TE flex) + 2 buffer
            calc.Range("F9").Formula = (
                "=ROUND(Setup!$E$11*(Setup!$E$17"
                "+Setup!$E$20*0.5+Setup!$E$21*0.1)+2,0)"
            )
            print("  Calculations row 9 (replacement ranks) written.")

            # Row 10 — replacement score per position (live array formula)
            # LARGE(IF(pos=X, score, 0), rank) → updates as players are deleted
            calc.Range("A10").Value = "repl score"
            calc.Range("B10").Value = ""
            for col, pos, rank_ref in [
                ("C", "QB", "C9"),
                ("D", "RB", "D9"),
                ("E", "WR", "E9"),
                ("F", "TE", "F9"),
            ]:
                calc.Range(f"{col}10").ClearContents()
                calc.Range(f"{col}10").FormulaArray = (
                    f"=LARGE(IF('Cheat Sheet'!$D$2:$D$700=\"{pos}\","
                    f"'Cheat Sheet'!$G$2:$G$700),{rank_ref})"
                )
            print("  Calculations row 10 (replacement scores) written.")

            # ── CHEAT SHEET: Q — Overall Value (PAR) ─────────────────────────
            # Clear existing array formulas before overwriting
            cs.Range(f"Q2:Q{last_row}").ClearContents()
            cs.Range(f"Q2:Q{last_row}").Formula = (
                '=IFS(D2="QB",MAX(0,G2-Calculations!C$10),'
                'D2="RB",MAX(0,G2-Calculations!D$10),'
                'D2="WR",MAX(0,G2-Calculations!E$10),'
                'D2="TE",MAX(0,G2-Calculations!F$10))'
            )
            print(f"  Q column (Overall Value PAR) written.")

            # ── CHEAT SHEET: R–U — Positional Values (PAR, per position) ────
            for col, pos, repl in [
                ("R", "QB", "C"),
                ("S", "RB", "D"),
                ("T", "WR", "E"),
                ("U", "TE", "F"),
            ]:
                cs.Range(f"{col}2:{col}{last_row}").Formula = (
                    f'=IF(D2="{pos}",MAX(0,G2-Calculations!{repl}$10),1-1000)'
                )
            print("  R-U columns (Positional Value PAR) written.")

            # ── CHEAT SHEET: Delete V:W (hidden duplicate columns) ───────────
            cs.Columns("V:W").Delete()
            print("  Columns V:W deleted.")

            wb.Save()
            print("Saved.")

        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
