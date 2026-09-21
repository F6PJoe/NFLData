#!/usr/bin/env python3
"""
Apply PAR v3 to the Cheat Sheet.

Q (Overall Value) = (projected_score - overall_repl) × position_weight

  overall_repl   = demand-weighted average of positional replacement scores.
                   Dynamic — drops as players are drafted → remaining Q values rise.
                   Formula: Σ(pos_repl × eligible_slots) / Σ(eligible_slots)

  position_weight = eligible_slots_for_pos / total_eligible_slots.
                   Eligible slots = designated starters + any flex slot the position
                   can fill (binary: 0 or 1 per slot type, not fractional splits).
                   Sums to 1.0 across all positions.

V (PAR) = projected score − positional replacement level (row 10, dynamic)
R-U     = within-position z-scores using live replacement levels (row 12)

Calculations tab layout written by this script:
  Row 9  C-F : Replacement rank per position (teams × starters + buffer)
  Row 10 C-F : Replacement score per position (LARGE, dynamic from Cheat Sheet)
  Row 12 C-F : Z-score cutoff score (LARGE, dynamic — for R-U columns)

  Rows 15-29 cols E-J : POSITIONAL WEIGHTS TABLE
    Row 15     : Section header
    Row 16     : Column headers (Lineup Slot / QB / RB / WR / TE / Total)
    Rows 17-24 : Eligible slots per lineup slot type:
                   17 = QB starters (QB only)
                   18 = RB starters (RB only)
                   19 = WR starters (WR only)
                   20 = TE starters (TE only)
                   21 = SF/2QB (QB only)
                   22 = RB/WR flex (+1 to both RB and WR)
                   23 = 3-way flex (+1 to RB, WR, and TE)
                   24 = WR/TE flex (+1 to WR and TE)
    Row 26     : Adjusted eligible slots (raw × demand multiplier from table below)
    Row 27     : Position weights (adjusted / grand total, sums to 1.0)
    Row 28     : Replacement scores (mirrors row 10)
    Row 29 F   : Overall replacement level (dynamic, used in Q formula)

  Rows 31-37 cols E-I : DEMAND MULTIPLIERS TABLE (user-editable)
    Row 31     : Section header
    Row 32     : Col headers (Std / Half PPR / PPR / SF+2QB)
    Rows 33-36 : QB / RB / WR / TE multipliers per format (default 1.0 = no change)
    Row 37 F   : Active column selector (SF/2QB overrides scoring format)

  Rows 23-35 cols A-B : ADP/Scoring Format dropdown data (restored every run)

NEVER use openpyxl to save this workbook — it strips Data Validation and
Conditional Formatting. Always use win32com.client.
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

            # ── PAR SECTION rows 9-10, 12 ────────────────────────────────────
            # Row 9: replacement ranks (starters only + small buffer)
            calc.Range("C9").Formula = "=Setup!$E$11*Setup!$E$14+2"
            calc.Range("D9").Formula = "=Setup!$E$11*Setup!$E$15+4"
            calc.Range("E9").Formula = "=Setup!$E$11*Setup!$E$16+4"
            calc.Range("F9").Formula = "=Setup!$E$11*Setup!$E$17+2"

            # Row 10: replacement scores (Nth-best at each position, dynamic).
            # H/I/J/K columns use -999 sentinel for off-position rows so LARGE
            # naturally returns the correct positional Nth score.
            # Row 12: same pattern for z-score cutoff (row 11 = deeper rank from v2).
            calc.Range("C10:F10").ClearContents()
            calc.Range("C12:F12").ClearContents()
            for calc_col, cs_col in [("C","H"), ("D","I"), ("E","J"), ("F","K")]:
                sr = f"'Cheat Sheet'!${cs_col}$2:${cs_col}$700"
                calc.Range(f"{calc_col}10").Formula = f"=LARGE({sr},{calc_col}9)"
                calc.Range(f"{calc_col}12").Formula = f"=LARGE({sr},{calc_col}11)"
            print("  Rows 9/10 (repl ranks/scores) and row 12 (z-score cutoffs) written.")

            # ── AGGRESSIVE CLEAR of rows 15-42, cols C-L ─────────────────────
            # Wipes stale data from ALL previous script versions in one shot.
            # Safe: ADP data lives in cols A-B only; PAR section is rows 8-14.
            calc.Range("C15:L42").ClearContents()
            print("  C15:L42 cleared (all stale data removed).")

            # ── RESTORE ADP/SCORING FORMAT DROPDOWN DATA (A23:B35) ───────────
            # Source lists for Setup page B2 (ADP site) and B3 (scoring format).
            # Blank B values = no scoring-format default for that site.
            adf_rows = [
                (23, "ADP",          "Scoring Format"),
                (24, "Sleeper",      "Half-PPR"),
                (25, "Underdog",     "PPR"),
                (26, "ESPN",         "Standard"),
                (27, "CBS",          "Custom"),
                (28, "Yahoo",        ""),
                (29, "NFL",          ""),
                (30, "NFFC",         ""),
                (31, "NFFC Cutline", ""),
                (32, "FFPC",         ""),
                (33, "Fantrax",      ""),
                (34, "RTSports",     ""),
                (35, "Other",        ""),
            ]
            for row, adp, fmt in adf_rows:
                calc.Range(f"A{row}").Value = adp
                calc.Range(f"B{row}").Value = fmt
            # Clear any stale rows below the ADP table in cols A-B
            calc.Range("A36:B42").ClearContents()
            print("  A23:B35 (ADP/Scoring Format lookup) restored.")

            # ── POSITIONAL WEIGHTS TABLE (rows 15-29, cols E-J) ──────────────
            # One table shows how every lineup slot type contributes to each
            # position's effective demand. Weight = eff / grand total.
            # Flex rows 22-24 pull split fractions from the Flex Weights table
            # at rows 33-39 via INDEX, using the scoring format col at F40.

            calc.Range("E15").Value = "POSITION WEIGHTS"

            for col, label in [("E","Lineup Slot"),("F","QB"),("G","RB"),
                                ("H","WR"),("I","TE"),("J","Total")]:
                calc.Range(f"{col}16").Value = label

            # QB starters: fill only QB column (F)
            calc.Range("E17").Value = "QB starters"
            calc.Range("F17").Formula = "=Setup!$E$14"
            calc.Range("G17").Value = 0
            calc.Range("H17").Value = 0
            calc.Range("I17").Value = 0
            calc.Range("J17").Formula = "=F17"

            # RB starters
            calc.Range("E18").Value = "RB starters"
            calc.Range("F18").Value = 0
            calc.Range("G18").Formula = "=Setup!$E$15"
            calc.Range("H18").Value = 0
            calc.Range("I18").Value = 0
            calc.Range("J18").Formula = "=G18"

            # WR starters
            calc.Range("E19").Value = "WR starters"
            calc.Range("F19").Value = 0
            calc.Range("G19").Value = 0
            calc.Range("H19").Formula = "=Setup!$E$16"
            calc.Range("I19").Value = 0
            calc.Range("J19").Formula = "=H19"

            # TE starters
            calc.Range("E20").Value = "TE starters"
            calc.Range("F20").Value = 0
            calc.Range("G20").Value = 0
            calc.Range("H20").Value = 0
            calc.Range("I20").Formula = "=Setup!$E$17"
            calc.Range("J20").Formula = "=I20"

            # SF / 2QB extra QB slots (Setup!E21 = 0 in standard leagues)
            calc.Range("E21").Value = "SF / 2QB slots"
            calc.Range("F21").Formula = "=Setup!$E$21"
            calc.Range("G21").Value = 0
            calc.Range("H21").Value = 0
            calc.Range("I21").Value = 0
            calc.Range("J21").Formula = "=F21"

            # RB/WR flex: each slot is eligible for both RB and WR (binary, no split)
            calc.Range("E22").Value = "RB/WR flex"
            calc.Range("F22").Value = 0
            calc.Range("G22").Formula = "=Setup!$E$18"
            calc.Range("H22").Formula = "=Setup!$E$18"
            calc.Range("I22").Value = 0
            calc.Range("J22").Formula = "=2*Setup!$E$18"

            # 3-way flex: each slot eligible for RB, WR, and TE
            calc.Range("E23").Value = "3-way flex (RB/WR/TE)"
            calc.Range("F23").Value = 0
            calc.Range("G23").Formula = "=Setup!$E$19"
            calc.Range("H23").Formula = "=Setup!$E$19"
            calc.Range("I23").Formula = "=Setup!$E$19"
            calc.Range("J23").Formula = "=3*Setup!$E$19"

            # WR/TE flex: each slot eligible for WR and TE
            calc.Range("E24").Value = "WR/TE flex"
            calc.Range("F24").Value = 0
            calc.Range("G24").Value = 0
            calc.Range("H24").Formula = "=Setup!$E$20"
            calc.Range("I24").Formula = "=Setup!$E$20"
            calc.Range("J24").Formula = "=2*Setup!$E$20"

            # Row 26: adjusted eligible slots = raw eligible × demand multiplier.
            # Multipliers live in rows 33-36 (F=Std, G=Half, H=PPR, I=SF/2QB).
            # F37 = active column (1-4). Default 1.0 = no adjustment.
            calc.Range("E26").Value = "Adj eligible slots"
            calc.Range("F26").Formula = "=SUM(F17:F24)*INDEX($F$33:$I$33,1,$F$37)"  # QB
            calc.Range("G26").Formula = "=SUM(G17:G24)*INDEX($F$34:$I$34,1,$F$37)"  # RB
            calc.Range("H26").Formula = "=SUM(H17:H24)*INDEX($F$35:$I$35,1,$F$37)"  # WR
            calc.Range("I26").Formula = "=SUM(I17:I24)*INDEX($F$36:$I$36,1,$F$37)"  # TE
            calc.Range("J26").Formula = "=SUM(F26:I26)"

            # Row 27: position weights (simple ratio, must sum to 1.0)
            calc.Range("E27").Value = "Position weight"
            for col in ("F", "G", "H", "I"):
                calc.Range(f"{col}27").Formula = f"={col}26/$J$26"
            calc.Range("J27").Formula = "=SUM(F27:I27)"

            # Row 28: replacement score per position (mirrors PAR section row 10)
            calc.Range("E28").Value = "Repl score (row 10)"
            calc.Range("F28").Formula = "=C10"
            calc.Range("G28").Formula = "=D10"
            calc.Range("H28").Formula = "=E10"
            calc.Range("I28").Formula = "=F10"

            # Row 29: overall replacement level (demand-weighted avg, dynamic)
            # As players are drafted, row 10 (→ row 28) drops → this drops
            # → all remaining players' Q values rise.
            calc.Range("E29").Value = "Overall repl (dynamic)"
            calc.Range("F29").Formula = "=SUMPRODUCT(F26:I26,F28:I28)/J26"
            print("  Positional Weights Table (rows 15-29, cols E-J) written.")

            # ── DEMAND MULTIPLIERS TABLE (rows 31-37, cols E-I) ──────────────
            # User-editable. Multiplies each position's eligible slot count before
            # normalizing weights. 1.0 = no change. SF/2QB column overrides the
            # scoring-format column when Setup!E21 > 0.
            # Default values: PPR boosts WR demand, reduces RB; SF/2QB doubles QB.
            calc.Range("E31").Value = "DEMAND MULTIPLIERS"

            for col, label in [("E", ""),    ("F", "Std"), ("G", "Half PPR"),
                                ("H", "PPR"), ("I", "SF / 2QB")]:
                calc.Range(f"{col}32").Value = label

            mult_data = [
                # (row, label,  std,  half,  ppr,  sf  )
                (33, "QB",     1.00,  1.00,  1.00,  2.00),
                (34, "RB",     1.00,  0.95,  0.90,  1.00),
                (35, "WR",     1.00,  1.05,  1.10,  1.00),
                (36, "TE",     1.00,  1.00,  1.00,  1.00),
            ]
            for row, label, std, half, ppr, sf in mult_data:
                calc.Range(f"E{row}").Value = label
                calc.Range(f"F{row}").Value = std
                calc.Range(f"G{row}").Value = half
                calc.Range(f"H{row}").Value = ppr
                calc.Range(f"I{row}").Value = sf

            # F37: active column (SF/2QB takes priority over scoring format)
            calc.Range("E37").Value = "Active col"
            calc.Range("F37").Formula = (
                "=IFS(Setup!$E$21>0,4,"
                "Setup!$B$21=0,1,"
                "Setup!$B$21<0.75,2,"
                "TRUE,3)"
            )
            print("  Demand Multipliers Table (rows 31-37, cols E-I) written.")

            # ── Q COLUMN: (score - overall_repl) × position_weight ───────────
            # Cells referenced:
            #   F29 = overall replacement level (dynamic)
            #   F27 = QB position weight
            #   G27 = RB position weight
            #   H27 = WR position weight
            #   I27 = TE position weight
            # H/I/J/K = position score columns in Cheat Sheet (-999 for off-pos)
            # V column (positional PAR from v2) guards against blank/non-player rows.
            cs.Range(f"Q2:Q{last_row}").ClearContents()
            cs.Range(f"Q2:Q{last_row}").Formula = (
                "=IF(ISNUMBER(V2),"
                "IF(D2=\"QB\",(H2-Calculations!$F$29)*Calculations!$F$27,"
                "IF(D2=\"RB\",(I2-Calculations!$F$29)*Calculations!$G$27,"
                "IF(D2=\"WR\",(J2-Calculations!$F$29)*Calculations!$H$27,"
                "(K2-Calculations!$F$29)*Calculations!$I$27))),"
                "-999)"
            )
            print("  Q column ((score - overall_repl) × position_weight) written.")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
