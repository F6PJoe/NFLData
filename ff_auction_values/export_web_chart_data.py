#!/usr/bin/env python3
"""
Export player projections + the 15-combo CALIBRATED table to a single JSON
blob, then splice it into value_chart_template.html to produce the finished
value_chart.html. The chart computes auction values client-side in
JavaScript using the exact same formula as compute_auction_values() in
build_auction_values.py — this script exports RAW POINTS ONCE PER FORMAT
(not 15x precomputed value tables) so the JS does the real math, the same
"raw data + live formula" architecture as the Excel workbook (see
build_live_draft_workbook.py) and for the same reason: one source of truth
for the formula, not 15 baked snapshots that can drift out of sync with
each other.

Both the data export and the template splice used to be separate manual
steps (a one-off inline script) -- consolidated here so the whole chain is
a single command, safe to run unattended in CI (see
.github/workflows/fetch_draft_projections.yml).

Usage:
    python export_web_chart_data.py
    # writes value_chart_data.json and value_chart.html next to this script
"""

import json
from pathlib import Path

from build_auction_values import (
    POINTS_COL, BUDGET, BENCH_SPOTS, STARTERS, FLEX_SLOTS,
    NON_SKILL_SLOTS_PER_TEAM,
    blend_with_personal_ranks, load_personal_ranks, load_projections,
)
from build_teamcount_estimate import CALIBRATED, TEAM_COUNTS, FORMATS
from roster_formula import MIN_EXPONENT
from web_chart_utils import strip_blank_lines, collapse_script_style_blocks

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "value_chart_data.json"
TEMPLATE_FILE = HERE / "value_chart_template.html"
OUT_FILE = HERE / "value_chart.html"


def main():
    players_by_format = {}
    for fmt in FORMATS:
        projections = load_projections(fmt)
        personal_ranks = load_personal_ranks(fmt)
        blended = blend_with_personal_ranks(projections, personal_ranks)
        players_by_format[fmt] = {
            pos: [
                {"name": p["name"], "team": p["team"], "points": round(p["blended_points"], 2)}
                for p in blended[pos]
            ]
            for pos in POINTS_COL
        }

    # Exponent floor mirrors roster_formula.py's MIN_EXPONENT, applied
    # here directly since this export reads CALIBRATED straight from
    # build_teamcount_estimate.py and never goes through
    # estimate_roster_shape() -- the web chart is locked to the baseline
    # roster shape (2RB/3WR), so none of that module's roster-shape
    # machinery (starter damping, cross-position redistribution) applies
    # here anyway, but the exponent floor DOES apply even at baseline and
    # was previously missing from this export entirely. Without it the
    # live site kept using the stored TE exponent (~1.0, the lowest of any
    # position in 14 of 15 combos -- backwards for the most top-heavy
    # position in fantasy), pricing Trey McBride at ~$23 in a 12-team
    # half-PPR league where FantasyPros AND Draft Sharks both independently
    # say ~$33.
    calibrated = {
        f"{teams}|{fmt}": {
            "ranks": CALIBRATED[(teams, fmt)]["ranks"],
            "exponents": {
                pos: max(CALIBRATED[(teams, fmt)]["exponents"][pos], MIN_EXPONENT[pos])
                for pos in POINTS_COL
            },
            "budgetShare": CALIBRATED[(teams, fmt)]["budget_share"],
        }
        for teams in TEAM_COUNTS for fmt in FORMATS
        if (teams, fmt) in CALIBRATED
    }

    data = {
        "playersByFormat": players_by_format,
        "calibrated": calibrated,
        "teamCounts": TEAM_COUNTS,
        "formats": FORMATS,
        "constants": {
            "budget": BUDGET,
            "benchSpots": BENCH_SPOTS,
            "starters": STARTERS,
            "flexSlots": FLEX_SLOTS,
            "nonSkillSlotsPerTeam": NON_SKILL_SLOTS_PER_TEAM,
        },
    }

    data_json = json.dumps(data, separators=(",", ":"))
    DATA_FILE.write_text(data_json)
    print(f"Wrote {DATA_FILE} ({DATA_FILE.stat().st_size / 1024:.0f} KB)")
    print(f"  {sum(len(players_by_format['half_ppr'][p]) for p in POINTS_COL)} players x 3 formats, "
          f"{len(calibrated)} calibrated combos")

    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    if "/*__DATA_PLACEHOLDER__*/" not in template:
        raise RuntimeError(f"{TEMPLATE_FILE} is missing the /*__DATA_PLACEHOLDER__*/ marker")
    spliced = template.replace("/*__DATA_PLACEHOLDER__*/", data_json)
    safe = strip_blank_lines(collapse_script_style_blocks(spliced))
    OUT_FILE.write_text(safe, encoding="utf-8")
    print(f"Wrote {OUT_FILE} ({OUT_FILE.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
