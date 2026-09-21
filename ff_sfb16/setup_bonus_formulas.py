"""One-time conversion: turn the SFB16 bonus-category columns (Exp 300+/
400+ Pass Yd Games, Exp 100+/200+ Scrim Yd Games, Exp 40+ Rush Plays,
Exp 20+ Yd Rec Plays, Exp 40+ Pass Plays) from Python-pushed static values
into live Excel formulas, the same way `ru1st`/`re1st` are already
`=0.079*M2`-style formulas instead of pasted numbers.

Why: once the calibrated constants (sigma per position, slope/intercept per
play type — see calibrate_rates.py) are sitting in Setup cells, every bonus
column recalculates itself automatically whenever the raw stat columns
change. No Python push step needed for these columns ever again.

Writes the calibration constants to Setup!B44:B54 (labels in A44:A54), then
rewrites every row of every "Exp ..." column on QB/RB/WR/TE Projections as
a formula referencing those Setup cells + that row's own stat columns.

Math, mirrored from project_sfb16_stats.py:
  Game-threshold columns (lognormal): mu_game = SeasonYds/17,
    P(game>=threshold) = 1 - NORM.S.DIST((LN(threshold)-(LN(mu_game)-sigma^2/2))/sigma, TRUE),
    expected = 17 * P.
  Big-play columns (linear rate): expected = Opportunities *
    MAX(0, slope*(Yards/Opportunities) + intercept).

Run once. Safe to re-run (idempotent — just rewrites the same formulas).
"""
import json
import win32com.client as win32

from workbook_common import BASE, SFB16_WORKBOOK, last_data_row

CALIBRATION = json.loads((BASE / "calibration_params.json").read_text())

# Setup row layout for the new constants block.
SETUP_ROWS = {
    "qb_pass_sigma": 44,
    "qb_scrim_sigma": 45,
    "rb_scrim_sigma": 46,
    "wr_scrim_sigma": 47,
    "te_scrim_sigma": 48,
    "pass_slope": 49,
    "pass_intercept": 50,
    "rush_slope": 51,
    "rush_intercept": 52,
    "rec_slope": 53,
    "rec_intercept": 54,
}
SETUP_LABELS = {
    "qb_pass_sigma": "QB Pass Sigma",
    "qb_scrim_sigma": "QB Scrim Sigma",
    "rb_scrim_sigma": "RB Scrim Sigma",
    "wr_scrim_sigma": "WR Scrim Sigma",
    "te_scrim_sigma": "TE Scrim Sigma",
    "pass_slope": "Pass Big Play Slope",
    "pass_intercept": "Pass Big Play Intercept",
    "rush_slope": "Rush Big Play Slope",
    "rush_intercept": "Rush Big Play Intercept",
    "rec_slope": "Rec Big Play Slope",
    "rec_intercept": "Rec Big Play Intercept",
}
SETUP_VALUES = {
    "qb_pass_sigma": CALIBRATION["sigma"]["qb_pass"],
    "qb_scrim_sigma": CALIBRATION["sigma"]["qb_scrim"],
    "rb_scrim_sigma": CALIBRATION["sigma"]["rb_scrim"],
    "wr_scrim_sigma": CALIBRATION["sigma"]["wr_scrim"],
    "te_scrim_sigma": CALIBRATION["sigma"]["te_scrim"],
    "pass_slope": CALIBRATION["big_play_rate"]["pass"]["slope"],
    "pass_intercept": CALIBRATION["big_play_rate"]["pass"]["intercept"],
    "rush_slope": CALIBRATION["big_play_rate"]["rush"]["slope"],
    "rush_intercept": CALIBRATION["big_play_rate"]["rush"]["intercept"],
    "rec_slope": CALIBRATION["big_play_rate"]["rec"]["slope"],
    "rec_intercept": CALIBRATION["big_play_rate"]["rec"]["intercept"],
}


def write_setup_constants(wb):
    setup = wb.Sheets("Setup")
    setup.Cells(43, 1).Value = "SFB Bonus Calibration Constants"
    for key, row in SETUP_ROWS.items():
        setup.Cells(row, 1).Value = SETUP_LABELS[key]
        setup.Cells(row, 2).Value = SETUP_VALUES[key]
    print("  Setup constants written (rows 44-54)")


def _game_threshold_formula(threshold, yards_expr, sigma_cell):
    """P(game yards >= threshold) — use for the upper tier (400+, 200+)."""
    return (
        f'=IF(({yards_expr})<=0,0,'
        f'17*(1-NORM.S.DIST((LN({threshold})-(LN(({yards_expr})/17)-Setup!${sigma_cell}^2/2))'
        f'/Setup!${sigma_cell},TRUE)))'
    )


def _game_bracket_formula(lower, upper, yards_expr, sigma_cell):
    """P(lower <= game yards < upper) — for the lower mutually-exclusive tier
    (300-399, 100-199). The scoring page shows these as separate non-stacking
    brackets: a 400-yd game earns only the 400+ bonus, not the 300-399 bonus
    too. Formula: CDF(z_upper) - CDF(z_lower) where z = (LN(T)-mu_log)/sigma."""
    mu_log = f'(LN(({yards_expr})/17)-Setup!${sigma_cell}^2/2)'
    z_lower = f'(LN({lower})-{mu_log})/Setup!${sigma_cell}'
    z_upper = f'(LN({upper})-{mu_log})/Setup!${sigma_cell}'
    return (
        f'=IF(({yards_expr})<=0,0,'
        f'17*(NORM.S.DIST({z_upper},TRUE)-NORM.S.DIST({z_lower},TRUE)))'
    )


def _big_play_formula(opp_cell, yards_expr, slope_cell, intercept_cell):
    return (
        f'=IF({opp_cell}<=0,0,'
        f'{opp_cell}*MAX(0,Setup!${slope_cell}*(({yards_expr})/{opp_cell})+Setup!${intercept_cell}))'
    )


# tab -> {bonus column index: formula-builder(row) -> formula string}
def _qb_formulas(r):
    sigma_pass = f"B${SETUP_ROWS['qb_pass_sigma']}"
    sigma_scrim = f"B${SETUP_ROWS['qb_scrim_sigma']}"
    pass_slope, pass_int = f"B${SETUP_ROWS['pass_slope']}", f"B${SETUP_ROWS['pass_intercept']}"
    rush_slope, rush_int = f"B${SETUP_ROWS['rush_slope']}", f"B${SETUP_ROWS['rush_intercept']}"
    return {
        18: _game_threshold_formula(300, f"I{r}", sigma_pass),                       # Exp 300+ Pass Yd Games
        19: _game_threshold_formula(400, f"I{r}", sigma_pass),                       # Exp 400+ Pass Yd Games (extra)
        20: _big_play_formula(f"G{r}", f"I{r}", pass_slope, pass_int),               # Exp 40+ Pass Plays
        21: _game_threshold_formula(100, f"M{r}", sigma_scrim),                      # Exp 100+ Scrim Yd Games
        22: _game_threshold_formula(200, f"M{r}", sigma_scrim),                      # Exp 200+ Scrim Yd Games (extra)
        23: _big_play_formula(f"L{r}", f"M{r}", rush_slope, rush_int),               # Exp 40+ Rush Plays
        24: "0",                                                                      # Exp 20+ Yd Rec Plays (n/a for QB)
    }


def _skill_formulas(sigma_key):
    sigma_cell = f"B${SETUP_ROWS[sigma_key]}"
    rush_slope, rush_int = f"B${SETUP_ROWS['rush_slope']}", f"B${SETUP_ROWS['rush_intercept']}"
    rec_slope, rec_int = f"B${SETUP_ROWS['rec_slope']}", f"B${SETUP_ROWS['rec_intercept']}"

    def build(r):
        return {
            18: _game_threshold_formula(100, f"(H{r}+L{r})", sigma_cell),   # Exp 100+ Scrim Yd Games
            19: _game_threshold_formula(200, f"(H{r}+L{r})", sigma_cell),   # Exp 200+ Scrim Yd Games (extra)
            20: _big_play_formula(f"G{r}", f"H{r}", rush_slope, rush_int),  # Exp 40+ Rush Plays
            21: _big_play_formula(f"J{r}", f"L{r}", rec_slope, rec_int),    # Exp 20+ Yd Rec Plays
        }
    return build


# RB's raw-stat columns are Att(7)/rYds(8)/.../Tgt(10)/Rec(11)/Yds(12) —
# scrim = rYds(H) + Yds(L). WR/TE are Tgt(7)/Rec(8)/Yds(9)/.../Att(11)/rYds(12)
# — scrim = rYds(L) + Yds(I), and rush opportunities are Att(K)/rYds(L),
# rec opportunities are Tgt(G)/Yds(I). Different column layout, same shape.
def _wr_te_formulas(sigma_key):
    sigma_cell = f"B${SETUP_ROWS[sigma_key]}"
    rush_slope, rush_int = f"B${SETUP_ROWS['rush_slope']}", f"B${SETUP_ROWS['rush_intercept']}"
    rec_slope, rec_int = f"B${SETUP_ROWS['rec_slope']}", f"B${SETUP_ROWS['rec_intercept']}"

    def build(r):
        return {
            18: _game_threshold_formula(100, f"(L{r}+I{r})", sigma_cell),   # Exp 100+ Scrim Yd Games
            19: _game_threshold_formula(200, f"(L{r}+I{r})", sigma_cell),   # Exp 200+ Scrim Yd Games (extra)
            20: _big_play_formula(f"K{r}", f"L{r}", rush_slope, rush_int),  # Exp 40+ Rush Plays
            21: _big_play_formula(f"G{r}", f"I{r}", rec_slope, rec_int),    # Exp 20+ Yd Rec Plays
        }
    return build


TAB_FORMULA_BUILDERS = {
    "QB Projections": _qb_formulas,
    "RB Projections": _skill_formulas("rb_scrim_sigma"),
    "WR Projections": _wr_te_formulas("wr_scrim_sigma"),
    "TE Projections": _wr_te_formulas("te_scrim_sigma"),
}


def convert_tab(ws, tab_name):
    builder = TAB_FORMULA_BUILDERS[tab_name]
    last_row = last_data_row(ws)
    for r in range(2, last_row + 1):
        formulas = builder(r)
        for col, formula in formulas.items():
            if formula == "0":
                ws.Cells(r, col).Value = 0.0
            else:
                ws.Cells(r, col).Formula = formula
    print(f"  {tab_name}: converted rows 2-{last_row}")


def main():
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    wb = excel.Workbooks.Open(str(SFB16_WORKBOOK))
    try:
        print("Writing Setup calibration constants...")
        write_setup_constants(wb)

        print("Converting bonus columns to formulas...")
        for tab_name in TAB_FORMULA_BUILDERS:
            ws = wb.Sheets(tab_name)
            convert_tab(ws, tab_name)

        wb.Save()
        print(f"Saved {SFB16_WORKBOOK}")
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()


if __name__ == "__main__":
    main()
