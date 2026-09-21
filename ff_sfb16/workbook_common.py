"""Shared config for scripts that write into the SFB16 workbook's
Projections tabs: column layout, name-matching, and (used by
add_missing_players.py and build_sfb16_workbook.py).
"""
import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
DRAFT_PROJ_DIR = BASE.parent / "ff_draft_proj"
CHEAT_SHEET_DIR = Path(r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet")
SFB16_WORKBOOK = CHEAT_SHEET_DIR / "2026-Football-SFB16-Cheat-Sheet-working-copy.xlsm"

# Workbook "Player" spelling -> sfb16_<pos>.csv/consensus spelling, for
# nickname differences a suffix-stripping normalizer can't catch on its own
# (the workbook's player list comes from a separate Joe Bond Ranks source
# that uses full given names; the consensus projections use nicknames).
NAME_ALIASES = {
    "Cameron Ward": "Cam Ward",
    "Nathaniel Dell": "Tank Dell",
    "Chigoziem Okonkwo": "Chig Okonkwo",
    "Kenneth Gainwell": "Kenny Gainwell",
    "Mitchell Trubisky": "Mitch Trubisky",
    "Cameron Skattebo": "Cam Skattebo",
    "Jo'quavioius Marks": "Woody Marks",
    "Jo'quavious Marks": "Woody Marks",
    "Christopher Brooks": "Chris Brooks",
    "Jamarion Miller": "Jam Miller",
    "Joshua Palmer": "Josh Palmer",
    "Mitchell Tinsley": "Mitch Tinsley",
    "M. Valdes-Scantling": "Marquez Valdes-Scantling",
    "Matthew Hibner": "Matt Hibner",
    "Andrew Ogletree": "Drew Ogletree",
}

# Projections tab name -> (consensus csv, {tab column index: consensus column name})
POSITION_CONFIG = {
    "QB Projections": ("consensus_qb.csv", {
        7: "Pass Att", 8: "Pass Comp", 9: "Pass Yds", 10: "Pass TD", 11: "Pass Int",
        12: "Rush Att", 13: "Rush Yds", 14: "Rush TD", 15: "Fumbles",
    }),
    "RB Projections": ("consensus_rb.csv", {
        7: "Rush Att", 8: "Rush Yds", 9: "Rush TD", 10: "Targets",
        11: "Rec", 12: "Rec Yds", 13: "Rec TD", 14: "Fum",
    }),
    "WR Projections": ("consensus_wr.csv", {
        7: "Targets", 8: "Rec", 9: "Rec Yds", 10: "Rec TD",
        11: "Rush Att", 12: "Rush Yds", 13: "Rush TD", 14: "Fum",
    }),
    "TE Projections": ("consensus_te.csv", {
        7: "Targets", 8: "Rec", 9: "Rec Yds", 10: "Rec TD",
        11: "Rush Att", 12: "Rush Yds", 13: "Rush TD",
    }),
}
POSITION_CODE = {"QB Projections": "QB", "RB Projections": "RB", "WR Projections": "WR", "TE Projections": "TE"}


def normalize(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().replace(".", "").replace("'", "")
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _as_rows(value, n_rows, n_cols):
    """win32com's Range.Value returns a proper tuple-of-tuples for any
    range with more than one cell (1-row and 1-column ranges included —
    only a true 1x1 range degrades to a bare scalar). Normalize to a
    consistent list-of-tuples shape so callers never have to special-case it."""
    if n_rows == 1 and n_cols == 1:
        return [(value,)]
    return [tuple(row) for row in value]


def read_range(ws, first_row, first_col, last_row, last_col):
    """Bulk-read a rectangular block in one COM call instead of one Cells()
    call per cell — this is the difference between ~1 round-trip and
    thousands for a full-tab read."""
    if last_row < first_row:
        return []
    rng = ws.Range(ws.Cells(first_row, first_col), ws.Cells(last_row, last_col))
    n_rows = last_row - first_row + 1
    n_cols = last_col - first_col + 1
    return _as_rows(rng.Value, n_rows, n_cols)


def write_range(ws, first_row, first_col, last_row, last_col, rows, as_formula=False):
    """Bulk-write a rectangular block (list of tuples) in one COM call.
    `as_formula=True` writes each cell's text as a formula (e.g. a
    per-row IF/VLOOKUP) instead of as a literal value."""
    if last_row < first_row:
        return
    rng = ws.Range(ws.Cells(first_row, first_col), ws.Cells(last_row, last_col))
    if as_formula:
        rng.Formula = tuple(rows)
    else:
        rng.Value = tuple(rows)


XL_UP = -4162


def last_data_row(ws, col=1):
    """The last row with real data in `col` (default column A — the player
    name). Deliberately NOT `ws.UsedRange.Rows.Count`: Excel doesn't shrink
    UsedRange back down after row deletions, so it can report rows well
    past the real data (bit us once already — ~36 leftover blank-but-
    formula rows on Cheat Sheet got a fresh ADP formula written into them,
    which cascaded into #N/A through a whole-column RANK formula). This
    walks up from the sheet's bottom in `col`, same technique as Excel's
    own Ctrl+Up, so it always finds the true last populated row."""
    bottom = ws.Rows.Count
    return ws.Cells(bottom, col).End(XL_UP).Row


def get_existing_names(ws):
    """Column-A player names already on a win32com worksheet, rows 2..end."""
    last_row = last_data_row(ws)
    if last_row < 2:
        return []
    rows = read_range(ws, 2, 1, last_row, 1)
    return [r[0] for r in rows if r[0]]
