#!/usr/bin/env python3
"""
Build the VORP-test copy of the cheat sheet workbook.

Copies the working workbook to 2026-Football-Cheat-Sheet-VORP-test.xlsm and
rewires the value engine:

  Calculations H8:L23   : VORP block — positional demand (from Setup roster
                          fields), replacement rank/points (anchored to the
                          Projections tabs, so they stay stable while members
                          delete Cheat Sheet rows during a draft), pre-draft vs
                          remaining surplus, and a live scarcity multiplier.
                          Rows 32-47 sit BELOW the dropdown source lists at
                          A18:B30 (ADP sources / Scoring Format) — never
                          overwrite those.
  Cheat Sheet Q         : Overall Value = (Proj − replacement) × scarcity
                          + elite bonus (per-position weight).
  Cheat Sheet R:U       : positional value = raw VORP points (Proj − replacement).

Everything else (layout, tabs, other columns, the old Setup multiplier grid)
is left untouched.  The original working copy is never opened or modified.

NEVER use openpyxl to save — it strips Data Validation and Conditional Formatting.
"""

import shutil
import sys
from pathlib import Path

import win32com.client as win32

SRC = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"
DST = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-VORP-test.xlsm"

xlUp = -4162

POS = ["QB", "RB", "WR", "TE"]   # columns C, D, E, F of the calc block

# Calculations-tab layout: block lives in columns H-L, rows 8-23 — clear of
# the z-score block (A-F rows 8-10), the dropdown source lists (A-B rows
# 18-29), and the per-format scoring defaults table (A-D rows 33-54) that the
# Setup point-value formulas read.  Labels in H; QB/RB/WR/TE data in I-L.
LBL = "H"
DATA_COLS = "IJKL"
R_TITLE   = 8    # "VORP engine"
R_HEAD    = 9    # QB / RB / WR / TE column headers
R_DEMAND  = 10   # starter demand
R_RANK    = 11   # replacement rank
R_REPL    = 12   # replacement points
R_PRESUR  = 13   # pre-draft surplus pts
R_REMSUR  = 14   # remaining surplus pts
R_PRECNT  = 15   # pre-draft count above repl
R_REMCNT  = 16   # remaining count above repl
R_REMDEM  = 17   # remaining starter demand
R_SCAR    = 18   # scarcity multiplier
R_ELITE   = 19   # elite baseline
R_FLEXLBL = 20   # "Flex shares" label
R_FLEX1   = 21   # RB/WR/TE flex shares
R_FLEX2   = 22   # RB/WR + WR/TE flex shares
R_WEIGHT  = 23   # per-position elite bonus weights
R_DAMP    = 24   # format dampener (QB x0.75 in 1QB standard scoring)
R_MYCNT   = 25   # players I have drafted at each position (from My Team tab)
R_NEED    = 26   # my-need multiplier (1.0 when the My Team tab is empty)
R_DISC1   = 27   # discount once dedicated starters are filled (flex still open)
R_DISC2   = 28   # discount once the position is fully saturated


def build_calc_block(cs):
    """Write the VORP block into Calculations rows 32-47 (labels in B)."""
    cs.Cells(R_TITLE, 8).Value = "VORP engine"
    for i, p in enumerate(POS):
        cs.Cells(R_HEAD, 9 + i).Value = p

    labels = {
        R_DEMAND:  "Starter demand (slots league-wide)",
        R_RANK:    "Replacement rank (flex half-weighted)",
        R_REPL:    "Replacement points",
        R_PRESUR:  "Pre-draft surplus pts (Projections)",
        R_REMSUR:  "Remaining surplus pts (board)",
        R_PRECNT:  "Pre-draft count above repl",
        R_REMCNT:  "Remaining count above repl",
        R_REMDEM:  "Remaining starter demand",
        R_SCAR:    "Scarcity multiplier",
        R_ELITE:   "Elite baseline (mid-starter pts)",
        R_FLEXLBL: "Flex share knobs (Setup E18-E20; superflex E21 counts fully to QB)",
        R_FLEX1:   "Setup E18 RB/WR/TE flex -> RB | WR | TE shares",
        R_FLEX2:   "Setup E19 RB/WR flex -> RB | WR shares; Setup E20 WR/TE flex -> WR | TE shares",
        R_WEIGHT:  "Elite bonus weight (per position)",
    }
    for r, txt in labels.items():
        cs.Cells(r, 8).Value = txt

    # Flex-share knobs (editable values, referenced by the demand formulas).
    # R_FLEX1: shares of the E18 RB/WR/TE flex -> C=RB, D=WR, E=TE
    cs.Cells(R_FLEX1, 9).Value = 0.35
    cs.Cells(R_FLEX1, 10).Value = 0.60
    cs.Cells(R_FLEX1, 11).Value = 0.05
    # R_FLEX2: C=RB share of E19 RB/WR flex, D=WR share of E19,
    #          E=WR share of E20 WR/TE flex, F=TE share of E20
    cs.Cells(R_FLEX2, 9).Value = 0.50
    cs.Cells(R_FLEX2, 10).Value = 0.50
    cs.Cells(R_FLEX2, 11).Value = 0.60
    cs.Cells(R_FLEX2, 12).Value = 0.40

    f1, f2 = R_FLEX1, R_FLEX2

    # Starter demand per position, purely from Setup roster fields
    cs.Range(f"I{R_DEMAND}").Formula = "=Setup!$E$11*(Setup!$E$14+Setup!$E$21)"
    cs.Range(f"J{R_DEMAND}").Formula = f"=Setup!$E$11*(Setup!$E$15+$I${f1}*Setup!$E$18+$I${f2}*Setup!$E$19)"
    cs.Range(f"K{R_DEMAND}").Formula = f"=Setup!$E$11*(Setup!$E$16+$J${f1}*Setup!$E$18+$J${f2}*Setup!$E$19+$K${f2}*Setup!$E$20)"
    cs.Range(f"L{R_DEMAND}").Formula = f"=Setup!$E$11*(Setup!$E$17+$K${f1}*Setup!$E$18+$L${f2}*Setup!$E$20)"

    # Replacement rank: dedicated starters at full weight, flex slots at HALF
    # weight (flex extends startability sub-linearly — full weight buried
    # QB/TE value in deep-flex formats), + small bench buffer.
    # QB: in 1QB formats the effective replacement is the best streamable QB,
    # not QB(teams+bench) — discount the rank to ~75% of teams.  Superflex/
    # 2QB can't stream, so the full starter count applies there.
    # SF: QBs are flexable, so teams roster ~2.5 — replacement is ~QB30 in a
    # 12-teamer (starters + 4-deep backup market), not QB26.
    cs.Range(f"I{R_RANK}").Formula = ("=IF(Setup!$E$14+Setup!$E$21>1,"
                                      "ROUND(Setup!$E$11*(Setup!$E$14+Setup!$E$21)+6,0),"
                                      "ROUND(Setup!$E$11*0.7+MAX(0,Setup!$E$11-12)*0.5,0)+2)")
    cs.Range(f"J{R_RANK}").Formula = f"=ROUND(Setup!$E$11*(Setup!$E$15+0.5*($I${f1}*Setup!$E$18+$I${f2}*Setup!$E$19))+3,0)"
    cs.Range(f"K{R_RANK}").Formula = f"=ROUND(Setup!$E$11*(Setup!$E$16+0.5*($J${f1}*Setup!$E$18+$J${f2}*Setup!$E$19+$K${f2}*Setup!$E$20))+3,0)"
    # TE: in 1-TE leagues TE is streamable like QB — the alternative to
    # rostering a mid TE is the best waiver TE each week, so replacement is
    # ~TE(0.8 x teams), not TE(starters+bench).  Without this, the flat mid-TE
    # tier all shows a false +13-16 pt edge over an artificially deep baseline.
    # 2-TE / TE-premium-flex leagues keep the demand-based formula.
    # TE premium (B24>0): elite/mid TEs are startable difference-makers, the
    # old-guard tier is not — shallower streaming baseline (0.7 x teams).
    # 1-TE standard: TE9+ is one flat streamable band (~20 pts TE9-TE18), so
    # replacement sits at TE8 — only the true difference-makers carry value.
    # TEP keeps the validated deeper TE10 baseline (the premium widens the
    # startable tier); 2-TE leagues stay demand-based.
    cs.Range(f"L{R_RANK}").Formula = (
        "=IF(Setup!$E$17>1,"
        f"ROUND(Setup!$E$11*(Setup!$E$17+0.5*($K${f1}*Setup!$E$18+$L${f2}*Setup!$E$20))+2,0),"
        "IF(Setup!$B$24>0,ROUND(Setup!$E$11*0.7+MAX(0,Setup!$E$11-12)*0.5,0)+2,ROUND(Setup!$E$11*0.66+MAX(0,Setup!$E$11-12)*0.5,0)))"
    )

    # Replacement points, anchored to the Projections tabs (col F = projected
    # score).  Static during a draft; live to Setup scoring changes.
    for col, p in zip(DATA_COLS, POS):
        cs.Range(f"{col}{R_REPL}").Formula = f"=LARGE('{p} Projections'!$F$2:$F$500,{col}{R_RANK})"

    # Pre-draft surplus points above replacement (Projections tabs)
    for col, p in zip(DATA_COLS, POS):
        rng = f"'{p} Projections'!$F$2:$F$500"
        cs.Range(f"{col}{R_PRESUR}").Formula = f"=SUMPRODUCT(({rng}>{col}{R_REPL})*({rng}-{col}{R_REPL}))"

    # Remaining surplus points on the live board (Cheat Sheet)
    for col, p in zip(DATA_COLS, POS):
        d = "'Cheat Sheet'!$D$2:$D$600"
        g = "'Cheat Sheet'!$G$2:$G$600"
        cs.Range(f"{col}{R_REMSUR}").Formula = f'=SUMPRODUCT(({d}="{p}")*({g}>{col}{R_REPL})*({g}-{col}{R_REPL}))'

    # Pre-draft count of above-replacement players (Projections tabs)
    for col, p in zip(DATA_COLS, POS):
        cs.Range(f"{col}{R_PRECNT}").Formula = f"=COUNTIF('{p} Projections'!$F$2:$F$500,\">\"&{col}{R_REPL})"

    # Remaining count of above-replacement players on the board
    for col, p in zip(DATA_COLS, POS):
        cs.Range(f"{col}{R_REMCNT}").Formula = (
            f"=COUNTIFS('Cheat Sheet'!$D$2:$D$600,\"{p}\","
            f"'Cheat Sheet'!$G$2:$G$600,\">\"&{col}{R_REPL})"
        )

    # Remaining starter demand: total demand minus players drafted at the
    # position (drafted = pre-draft count − remaining count)
    for col in DATA_COLS:
        cs.Range(f"{col}{R_REMDEM}").Formula = f"=MAX(1,{col}{R_DEMAND}-({col}{R_PRECNT}-{col}{R_REMCNT}))"

    # Scarcity multiplier: 1.0 pre-draft; rises as a position's points-weighted
    # surplus drains faster than its demand.  SQRT-damped and clamped to
    # [0.95, 1.12]: enough to reorder players whose values are already close
    # (the tier really is drying up), never enough to vault a position
    # wholesale and bait members into chasing a run.
    # RB/WR: points-weighted supply, tight floor (depth demand persists all
    # draft).  QB/TE: COUNT-based supply and a 0.6 floor — onesies are units
    # (any startable body fills the slot), and once most teams have theirs,
    # league demand craters and remaining QB/TEs must deflate like the
    # market does.  Points-weighting would wrongly boost them after the
    # elites (who hold all the surplus points) leave the board.
    for col in "JK":
        cs.Range(f"{col}{R_SCAR}").Formula = (
            f"=MIN(1.12,MAX(0.95,SQRT(({col}{R_REMDEM}/{col}{R_DEMAND})"
            f"/MAX(0.0001,{col}{R_REMSUR}/{col}{R_PRESUR}))))"
        )
    cs.Range(f"I{R_SCAR}").Formula = (
        f"=MIN(1.12,MAX(IF(Setup!$E$14+Setup!$E$21>1,0.95,0.6),SQRT((I{R_REMDEM}/I{R_DEMAND})"
        f"/MAX(0.0001,I{R_REMCNT}/I{R_PRECNT}))))"
    )
    # TE: pure demand-share deflator, never a boost.  Each drafted TE fills a
    # team's only TE slot, shrinking the buyer pool for every remaining TE —
    # and streaming covers the rest of the league, so a thinning startable
    # tier is NOT scarcity.  Multiplier = share of teams still needing a TE.
    cs.Range(f"L{R_SCAR}").Formula = f"=MAX(0.3,L{R_REMDEM}/L{R_DEMAND})"

    # Elite baseline: the position's #3 player (anchored to Projections,
    # static during a draft).  Only players who genuinely separate from the
    # pack at the top clear it — Allen, McBride/Bowers-types — nobody else.
    # QB in superflex is the exception: the whole startable tier carries a
    # leverage premium (24 slots chasing ~24 viable QBs), so the baseline
    # drops to ~QB(1.25 x teams) and the weight rises (see below).
    cs.Range(f"I{R_ELITE}").Formula = (
        "=IF(Setup!$E$14+Setup!$E$21>1,"
        "LARGE('QB Projections'!$F$2:$F$500,ROUND(Setup!$E$11*1.25,0)),"
        "LARGE('QB Projections'!$F$2:$F$500,3))"
    )
    for col, p in zip("JK", POS[1:3]):
        cs.Range(f"{col}{R_ELITE}").Formula = f"=LARGE('{p} Projections'!$F$2:$F$500,3)"
    # TE elite baseline = TE8, same line as 1-TE replacement: the bonus pays
    # the whole startable tier proportionally (Loveland/Warren/Fannin...),
    # while the Kelce-and-below streamer band sits under the line and gets
    # exactly zero.  Same baseline for standard and TEP.
    cs.Range(f"L{R_ELITE}").Formula = "=LARGE('TE Projections'!$F$2:$F$500,8)"
    # Onesie positions only: the weekly-positional-advantage premium is a
    # QB/TE phenomenon in 1QB/1TE leagues.  RB/WR get zero.
    # SF weight 0.5 (on the QB30 baseline) puts the top QB No.1 overall and
    # prices the QB1/QB2 tier near real 2QB ADP.
    # Format dampener: QB VORP x0.75 in 1QB standard scoring — QB points
    # don't shrink with the scoring format while RB/WR do, and the STD
    # market drafts QBs later, not earlier.  All other cells 1.
    cs.Cells(R_DAMP, 8).Value = "Format dampener (QB in 1QB STD)"
    cs.Range(f"I{R_DAMP}").Formula = "=IF(AND(Setup!$B$21<0.5,Setup!$E$14+Setup!$E$21<2),0.75,1)"
    for c in (10, 11, 12):
        cs.Cells(R_DAMP, c).Value = 1
    cs.Range(f"I{R_WEIGHT}").Formula = "=IF(Setup!$E$14+Setup!$E$21>1,0.35,0.08)"
    cs.Cells(R_WEIGHT, 10).Value = 0
    cs.Cells(R_WEIGHT, 11).Value = 0
    # TE weight: PPR trims to 0.25 (reception scoring already lifts TEs);
    # TEP keeps 0.4 regardless of base scoring.
    cs.Range(f"L{R_WEIGHT}").Formula = "=IF(Setup!$B$24>0,0.4,IF(Setup!$B$21>=0.75,0.25,0.4))"

    # ── My-team need engine ───────────────────────────────────────────────
    # Counts what the user has logged on the My Team tab and discounts filled
    # positions.  Discount-only by design: an open slot never inflates a
    # value, so the board can never recommend reaching past a better player
    # just to fill a hole.  Empty My Team tab -> all multipliers 1.0 -> the
    # board is identical to the shared/neutral version.
    for r, txt in {
        R_MYCNT: "My drafted count (My Team tab)",
        R_NEED:  "My-need multiplier",
        R_DISC1: "Discount: starters filled, flex open",
        R_DISC2: "Discount: fully saturated",
    }.items():
        cs.Cells(r, 8).Value = txt

    # QB count is quality-weighted: an at/below-replacement QB counts 0.5
    # (that room still needs a real QB, so the discount only half-fires).
    cs.Range(f"N{R_MYCNT}").Formula2 = (
        "=SUM(IF('My Team'!$A$2:$A$30=\"QB\","
        "LET(sc,IFERROR(XLOOKUP(TRIM('My Team'!$B$2:$B$30),"
        "'QB Projections'!$A:$A,'QB Projections'!$F:$F),0),"
        "qsafe,LARGE('QB Projections'!$F$2:$F$500,MAX(3,ROUND(Setup!$E$11/2,0))),"
        f"IF(sc>=qsafe,1,0.5+0.5*((sc>$I${R_REPL})*(sc-$I${R_REPL}))/MAX(1,qsafe-$I${R_REPL}))),0))")
    cs.Range(f"I{R_MYCNT}").Formula = f"=N{R_MYCNT}"
    cs.Cells(R_MYCNT, 13).Value = "<- QB count (quality-weighted) in N25"
    for col, p in zip("JKL", POS[1:]):
        cs.Range(f"{col}{R_MYCNT}").Formula = f"=COUNTIF('My Team'!$A$2:$A$30,\"{p}\")"

    # Tunable discounts.  Onesies (QB/TE) die hard once filled — a backup QB
    # in a 1QB league is bye insurance.  RB/WR barely move (depth + flex +
    # injuries keep later bodies valuable).
    # Onesies effectively vanish from your board once filled — a backup
    # QB/TE recommendation is noise.  RB/WR stay near full value (depth).
    for c, v in zip((9, 10, 11), (0.05, 0.92, 0.92)):
        cs.Cells(R_DISC1, c).Value = v
    # TEP teams genuinely roster two startable TEs — soften the drop
    cs.Range(f"L{R_DISC1}").Formula = "=IF(Setup!$B$24>0,0.5,0.05)"
    for c, v in zip((9, 10, 11, 12), (0.02, 0.75, 0.75, 0.02)):
        cs.Cells(R_DISC2, c).Value = v

    # Saturation thresholds: dedicated starters, then starters + eligible
    # flex (QB/TE get +1 as their "backup" tier before full saturation).
    cap1 = {
        "I": "(Setup!$E$14+Setup!$E$21)",                       # QB starters
        "J": "Setup!$E$15",                                     # RB starters
        "K": "Setup!$E$16",                                     # WR starters
        "L": "Setup!$E$17",                                     # TE starters
    }
    cap2 = {
        "I": "(Setup!$E$14+Setup!$E$21+1)",                                    # QB + backup
        "J": "(Setup!$E$15+Setup!$E$18+Setup!$E$19)",                          # RB + eligible flex
        "K": "(Setup!$E$16+Setup!$E$18+Setup!$E$19+Setup!$E$20)",              # WR + eligible flex
        "L": "(Setup!$E$17+1)",                                                # TE + backup
    }
    # QB thresholds are format-aware: 1QB discounts after 1, SF after 3
    # (2 QBs is a starting lineup there), 2QB after 4 (bye coverage).
    cs.Range(f"I{R_NEED}").Formula2 = (
        "=LET(capone,IF(Setup!$E$14>=2,Setup!$E$14+Setup!$E$21+2,"
        "IF(Setup!$E$21>=1,Setup!$E$14+Setup!$E$21+1,Setup!$E$14)),"
        f"IF(I{R_MYCNT}>=capone+1,I{R_DISC2},IF(I{R_MYCNT}>=capone,I{R_DISC1},"
        f"IF(I{R_MYCNT}>capone-1,1-(1-I{R_DISC1})*(I{R_MYCNT}-(capone-1)),1))))")
    for col in "JKL":
        cs.Range(f"{col}{R_NEED}").Formula = (
            f"=IF({col}{R_MYCNT}<{cap1[col]},1,"
            f"IF({col}{R_MYCNT}<{cap2[col]},{col}{R_DISC1},{col}{R_DISC2}))"
        )


MATCH_POS = 'MATCH($D2,{"QB","RB","WR","TE"},0)'
REPL  = f"INDEX(Calculations!$I${R_REPL}:$L${R_REPL},{MATCH_POS})"
SCAR  = f"INDEX(Calculations!$I${R_SCAR}:$L${R_SCAR},{MATCH_POS})"
ELITE = f"INDEX(Calculations!$I${R_ELITE}:$L${R_ELITE},{MATCH_POS})"
WT    = f"INDEX(Calculations!$I${R_WEIGHT}:$L${R_WEIGHT},{MATCH_POS})"
NEED  = f"INDEX(Calculations!$I${R_NEED}:$L${R_NEED},{MATCH_POS})"
DAMP  = f"INDEX(Calculations!$I${R_DAMP}:$L${R_DAMP},{MATCH_POS})"


def ensure_my_team_tab(wb):
    """Create the My Team tab (Player + Pos dropdown) if it doesn't exist."""
    for sh in wb.Worksheets:
        if sh.Name == "My Team":
            return sh
    after = wb.Worksheets("Cheat Sheet")
    sh = wb.Worksheets.Add(After=after)
    sh.Name = "My Team"
    sh.Range("A1").Value = "Pos"
    sh.Range("B1").Value = "Player"
    sh.Range("D1").Value = ("Enter each of YOUR picks here (position + name) as you draft. "
                            "Filled positions get discounted on the Cheat Sheet so the board "
                            "recommends what your roster actually needs. Leave empty for a "
                            "neutral board.")
    xlValidateList = 3
    dv = sh.Range("A2:A30").Validation
    dv.Delete()
    dv.Add(Type=xlValidateList, Formula1="QB,RB,WR,TE")
    sh.Range("A1:B1").Font.Bold = True
    sh.Columns("B").ColumnWidth = 24
    return sh


def main():
    print(f"Copying workbook...\n  -> {DST}")
    shutil.copy2(SRC, DST)

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = None
    try:
        wb = excel.Workbooks.Open(DST)
        cs = wb.Worksheets("Calculations")
        ch = wb.Worksheets("Cheat Sheet")

        print("Ensuring My Team tab exists...")
        ensure_my_team_tab(wb)

        print(f"Writing VORP block to Calculations rows {R_TITLE}-{R_WEIGHT}...")
        build_calc_block(cs)

        last = ch.Cells(ch.Rows.Count, 1).End(xlUp).Row
        print(f"Rewriting Cheat Sheet Q and R:U formulas (rows 2-{last})...")

        # V — raw engine value (hidden working column): VORP × live scarcity
        # + elite bonus, × my-need multiplier.
        ch.Range("V1").Value = "Raw Value"
        v = f"=(($G2-{REPL})*IF($G2>{REPL},{SCAR},1)+{WT}*MAX(0,$G2-{ELITE}))*{DAMP}"
        ch.Range(f"V2:V{last}").Formula = v

        # Q — Overall Value, normalised for display.  Piecewise 1-100 scale:
        # above-replacement players span 5-100 (as % of the best remaining),
        # below-replacement players compress into the 1-5 band.  No zeros,
        # no negatives, stable all draft long — and heavily discounted
        # players (filled onesies) genuinely sink instead of floating on a
        # min-max stretch.
        # Piecewise 1-100: above-replacement spans 5-100 (% of best
        # remaining), below-replacement compresses into the 1-5 band.
        # No zeros, no negatives.
        # My-need discount applies AFTER normalisation — inside V it gets
        # erased by the rescale (a 95% cut reads as a rounding error on the
        # z/ratio scales).  Applied here, a filled onesie's 95 becomes a 5.
        q = ("=IFERROR(ROUND(IF($V2>0,"
             "5+95*$V2/MAX($V$2:$V$600),"
             "1+4*($V2-MIN($V$2:$V$600))/MAX(0.0001,-MIN($V$2:$V$600)))"
             f"*{NEED},3),1)")

        ch.Range(f"Q2:Q{last}").Formula = q

        # R:U — positional value, normalised 1-100 within the position's
        # REMAINING players (best remaining at the position = 100), same
        # piecewise scale as Q.  Blank for other positions (no more -999).
        # MAXIFS/MINIFS over G (not over R:U itself) avoids circularity.
        for col, p in zip("RSTU", POS):
            repl = f"Calculations!${chr(ord('I') + POS.index(p))}${R_REPL}"
            raw = f"($G2-{repl})"
            mx = f'(MAXIFS($G:$G,$D:$D,"{p}")-{repl})'
            mn = f'(MINIFS($G:$G,$D:$D,"{p}")-{repl})'
            ch.Range(f"{col}2:{col}{last}").Formula = (
                f'=IF($D2<>"{p}","",IFERROR(ROUND('
                f"IF(AND({raw}>0,{mx}>0),5+95*{raw}/{mx},"
                f"1+4*({raw}-{mn})/MAX(0.0001,0-{mn})),3),1))"
            )

        wb.Application.Calculate()

        # Sanity read-back
        print("\nSpot check (Calculations):")
        for r, name in [(R_DEMAND, "demand"), (R_REPL, "repl pts"), (R_SCAR, "scarcity")]:
            vals = [cs.Cells(r, c).Value for c in range(9, 13)]
            print(f"  {name:10s} QB/RB/WR/TE = {vals}")
        print("Dropdown lists intact (A19:A29, B18:B22):")
        print("  ", [cs.Cells(r, 1).Value for r in range(19, 30)])
        print("  ", [cs.Cells(r, 2).Value for r in range(18, 23)])
        print("Spot check (Cheat Sheet rows 2-4, cols A/D/G/Q):")
        for r in range(2, 5):
            print("  ", [ch.Cells(r, c).Value for c in (1, 4, 7, 17)])

        wb.Save()
        print("\nSaved.")
    finally:
        if wb is not None:
            wb.Close(SaveChanges=False)
        excel.Quit()


if __name__ == "__main__":
    main()
