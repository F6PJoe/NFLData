#!/usr/bin/env python3
"""
Build the Draft Board tab — run once before each draft, after projections
and ADP are up to date.

Creates (or recreates) a "Draft Board" sheet with static pre-draft values
plus live scarcity formulas that update as players are deleted during the draft.

Column layout:
  A  Name          static value
  B  Pos           static value
  C  Team          static value
  D  Bye           static value
  E  JB Rank       Joe Bond personal rank, format-matched, static value
  F  ADP Rank      consensus ADP rank (1 = earliest ADP), static value
  G  Q Static      pre-draft overall value — never changes during draft
  H  Q Bump        scarcity formula: grows as players at that pos are drafted
  I  Q Value       = G + H  (overall value, dynamic)
  J  Overall Rank  RANK of Q Value among remaining players (dynamic)
  K  Pos Value     projected score − positional replacement, static value
  L  Pos Rank      rank within position among remaining players (dynamic)

Scarcity bump (H): k × (N_total_at_pos − COUNTIF remaining on this sheet)
  When 0 drafted → bump = 0.  Each player drafted adds k to all at that pos.

k lives at Calculations!F44 (label at E44).  Edit it before running this
script to tune scarcity sensitivity.  Default = 0.20 per player drafted.
"""

import csv
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"
xlUp = -4162

# Joe Bond Ranks tab: scoring format → (name col, rank col, int col index for Cells())
JB_COLS = {
    "ppr":      ("E", "G", 5),
    "standard": ("I", "K", 9),
    "half_ppr": ("A", "C", 1),  # default / Half-PPR / Custom
}


def detect_jb_format(fmt_str):
    """Map Setup!B3 scoring format string to JB_COLS key."""
    f = (fmt_str or "").strip().upper()
    if "PPR" in f and "HALF" not in f:
        return "ppr"
    if "STANDARD" in f or "STD" in f:
        return "standard"
    return "half_ppr"


def main():
    # ── Consensus ADP → rank (1 = first off board) ───────────────────────
    adp_vals = []
    with open(BASE / "combined_adp.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = row.get("Consensus", "")
            if c:
                adp_vals.append((row["Player"], float(c)))
    adp_vals.sort(key=lambda x: x[1])
    consensus_rank = {name: i + 1 for i, (name, _) in enumerate(adp_vals)}

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(WORKBOOK)
        try:
            cs    = wb.Sheets("Cheat Sheet")
            calc  = wb.Sheets("Calculations")
            setup = wb.Sheets("Setup")

            # ── k value ───────────────────────────────────────────────────
            if calc.Range("F44").Value is None:
                calc.Range("E44").Value = "Draft scarcity k"
                calc.Range("F44").Value = 0.20
            k = calc.Range("F44").Value
            print(f"  Scarcity k = {k}")

            # ── Static values from Calculations ───────────────────────────
            overall_repl = calc.Range("F29").Value
            pos_weight = {
                "QB": calc.Range("F27").Value,
                "RB": calc.Range("G27").Value,
                "WR": calc.Range("H27").Value,
                "TE": calc.Range("I27").Value,
            }
            pos_repl = {
                "QB": calc.Range("F28").Value,
                "RB": calc.Range("G28").Value,
                "WR": calc.Range("H28").Value,
                "TE": calc.Range("I28").Value,
            }
            print(f"  Overall repl: {overall_repl:.2f}")
            print(f"  Weights  QB={pos_weight['QB']:.3f}  RB={pos_weight['RB']:.3f}"
                  f"  WR={pos_weight['WR']:.3f}  TE={pos_weight['TE']:.3f}")

            # ── Joe Bond Ranks ─────────────────────────────────────────────
            fmt_key = detect_jb_format(setup.Range("B3").Value)
            jb_name_col, jb_rank_col, jb_col_idx = JB_COLS[fmt_key]

            jb_sh   = wb.Sheets("Joe Bond Ranks")
            jb_last = jb_sh.Cells(jb_sh.Rows.Count, jb_col_idx).End(xlUp).Row
            jb_ranks = {}
            for r in range(2, jb_last + 1):
                name = jb_sh.Range(f"{jb_name_col}{r}").Value
                rank = jb_sh.Range(f"{jb_rank_col}{r}").Value
                if name and rank is not None:
                    jb_ranks[name] = int(rank)
            print(f"  Joe Bond Ranks: {len(jb_ranks)} players ({fmt_key})")

            # ── Players from Cheat Sheet (A-D + col G = projected score) ──
            last_row = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            raw = cs.Range(f"A2:G{last_row}").Value
            players = []
            for row in raw:
                name, team, bye, pos = row[0], row[1], row[2], row[3]
                score = row[6] or 0          # col G = projected score
                if name and pos:
                    players.append((name, pos, team, bye, float(score)))

            n_total = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
            for _, pos, *_ in players:
                if pos in n_total:
                    n_total[pos] += 1
            print(f"  Players: {len(players)}  |  {n_total}")

            # ── Compute static Q and Pos Value ────────────────────────────
            rows_out = []
            for name, pos, team, bye, score in players:
                q_static = round((score - overall_repl) * pos_weight.get(pos, 0), 4)
                pos_val  = round(score - pos_repl.get(pos, overall_repl), 4)
                rows_out.append([
                    name, pos, team, bye,
                    jb_ranks.get(name, None),       # E: JB Rank
                    consensus_rank.get(name, None),  # F: ADP Rank
                    q_static,                        # G: Q Static
                    None,                            # H: Q Bump (formula)
                    None,                            # I: Q Value (formula)
                    None,                            # J: Overall Rank (formula)
                    pos_val,                         # K: Pos Value
                    None,                            # L: Pos Rank (formula)
                ])

            # ── Build Draft Board tab ─────────────────────────────────────
            try:
                wb.Sheets("Draft Board").Delete()
            except Exception:
                pass
            db = wb.Sheets.Add(After=wb.Sheets(wb.Sheets.Count))
            db.Name = "Draft Board"

            # Header row
            for c, h in enumerate(
                ["Name", "Pos", "Team", "Bye",
                 "JB Rank", "ADP Rank",
                 "Q Static", "Q Bump", "Q Value", "Overall Rank",
                 "Pos Value", "Pos Rank"],
                1
            ):
                db.Cells(1, c).Value = h

            # Bulk write all static values in one shot
            last_data = 1 + len(players)
            db.Range(f"A2:L{last_data}").Value = rows_out

            # ── Dynamic formulas ──────────────────────────────────────────
            nq = n_total["QB"]
            nr = n_total["RB"]
            nw = n_total["WR"]
            nt = n_total["TE"]

            # H: scarcity bump = (N_total_at_pos - remaining at pos) × k
            # N_total embedded at setup time; k referenced live from Calculations
            db.Range(f"H2:H{last_data}").Formula = (
                f'=IF(B2="QB",({nq}-COUNTIF($B:$B,"QB"))*Calculations!$F$44,'
                f'IF(B2="RB",({nr}-COUNTIF($B:$B,"RB"))*Calculations!$F$44,'
                f'IF(B2="WR",({nw}-COUNTIF($B:$B,"WR"))*Calculations!$F$44,'
                f'({nt}-COUNTIF($B:$B,"TE"))*Calculations!$F$44)))'
            )

            # I: Q Value = static + bump
            db.Range(f"I2:I{last_data}").Formula = "=G2+H2"

            # J: overall rank among all remaining players, descending
            db.Range(f"J2:J{last_data}").Formula = (
                f"=RANK.EQ(I2,$I$2:$I${last_data},0)"
            )

            # L: rank within position by Pos Value, descending
            db.Range(f"L2:L{last_data}").Formula = (
                f'=COUNTIFS($B$2:$B${last_data},B2,'
                f'$K$2:$K${last_data},">"&K2)+1'
            )

            print(f"  Draft Board: {len(players)} players, rows 2-{last_data}")
            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
