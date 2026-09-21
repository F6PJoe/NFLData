#!/usr/bin/env python3
"""Historical team totals -> projected 2026 team totals.

Reads the cached nflverse team season stats and produces two files:

  team_totals_history.csv   every team-season, with derived per-game and
                            per-attempt rates (the "past trends" reference)
  team_totals_2026.csv      the projected control totals that drive the
                            workbook — one row per team

Method
------
Everything is projected as a *rate* (per game, or per attempt), never as a
season total, so the 2020 COVID season and the 16 -> 17 game change don't
distort anything. Totals are rebuilt from the rates at the end.

For each rate we take a recency-weighted average of the last 3 seasons
(0.5 / 0.3 / 0.2) and then shrink it toward the league mean:

    projected = w * team_weighted + (1 - w) * league_mean

`w` is not guessed. It's fitted from the data: for every metric we correlate
"3-yr weighted value through season Y" against "what the team actually did in
season Y+1", pooled over every team and every season available. A metric that
predicts itself well keeps most of its team-specific signal; a noisy one gets
pulled toward league average. That is the whole regression-to-the-mean story,
measured instead of assumed.

The --regression dial (important)
--------------------------------
The fitted weights are low. Team pace is genuinely unsticky (plays/game has
r ~= 0.25 year over year), so full statistical shrinkage collapses all 32 teams
toward the league mean: pass TDs come out in a 22-29 band when real seasons
range 15-46. That is the *correct* minimum-error point estimate and a *useless*
starting point, because if every offense looks average then no player
differentiation flows through to the position tabs.

So shrinkage is a dial, not a decision:

    --regression 0    pure 3-yr weighted trend, realistic spread, noisier
    --regression 0.5  default; half way (a judgment call, not a fitted value)
    --regression 1    full fitted shrinkage, minimum error, very flat

These are *starting values for editable cells*. The real information about
which offenses will be good in 2026 — new QB, new coordinator, rebuilt line —
isn't in the historical data at all, and that's the judgment the team tab
exists to capture. Every metric also gets a `_trend` column (raw 3-yr weighted,
no shrinkage) so the workbook can show "what they've been doing" beside the
regressed default.

Usage:
    python build_team_totals.py
    python build_team_totals.py --regression 0      # trust the trend
    python build_team_totals.py --season 2026 --games 17
"""

import argparse
import csv
import os
import sys

from teams import TEAMS, clean_team

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cached", "nflverse")

RECENCY_WEIGHTS = [0.5, 0.3, 0.2]  # [Y-1, Y-2, Y-3]

# Rates we project. (name, numerator, denominator) where the denominator is a
# derived field computed in derive_season(). Order matters for the report.
RATES = [
    ("plays_per_game", "plays", "games"),
    ("pass_rate", "dropbacks", "plays"),
    ("sack_rate", "sacks", "dropbacks"),
    ("comp_pct", "completions", "pass_att"),
    ("ypa", "pass_yds", "pass_att"),
    ("pass_td_rate", "pass_td", "pass_att"),
    ("int_rate", "interceptions", "pass_att"),
    ("ypc", "rush_yds", "rush_att"),
    ("rush_td_rate", "rush_td", "rush_att"),
]


def _f(row, key):
    val = row.get(key)
    return float(val) if val not in (None, "", "NA") else 0.0


def load_history(start, end):
    """Return {(team, season): derived-stats dict} for completed seasons."""
    seasons = {}
    for year in range(start, end):
        path = os.path.join(CACHE, f"stats_team_reg_{year}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                team = clean_team(row["team"])
                if team == "FA":
                    continue
                seasons[(team, year)] = derive_season(row, team, year)
    return seasons


def derive_season(row, team, year):
    """Turn one nflverse team-season row into the fields we actually project."""
    games = _f(row, "games") or 17
    pass_att = _f(row, "attempts")
    rush_att = _f(row, "carries")
    sacks = _f(row, "sacks_suffered")

    # Offensive plays from scrimmage. Sacks are charted separately from pass
    # attempts in nflverse, so they have to be added back in explicitly.
    dropbacks = pass_att + sacks
    plays = pass_att + rush_att + sacks

    out = {
        "team": team,
        "season": year,
        "games": games,
        "plays": plays,
        "dropbacks": dropbacks,
        "sacks": sacks,
        "pass_att": pass_att,
        "rush_att": rush_att,
        "completions": _f(row, "completions"),
        "pass_yds": _f(row, "passing_yards"),
        "pass_td": _f(row, "passing_tds"),
        "interceptions": _f(row, "passing_interceptions"),
        "rush_yds": _f(row, "rushing_yards"),
        "rush_td": _f(row, "rushing_tds"),
    }
    for name, num, den in RATES:
        denom = out[den]
        out[name] = out[num] / denom if denom else 0.0
    return out


def weighted_prior(history, team, year, metric):
    """Recency-weighted value of `metric` over the 3 seasons before `year`."""
    total = weight_used = 0.0
    for offset, weight in enumerate(RECENCY_WEIGHTS, start=1):
        season = history.get((team, year - offset))
        if season and season[metric]:
            total += season[metric] * weight
            weight_used += weight
    return total / weight_used if weight_used else None


def pearson(pairs):
    n = len(pairs)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / (sxx * syy) ** 0.5


def fit_shrinkage(history, start, end):
    """Fit w per metric: corr(3-yr weighted prior, following season actual).

    This matches exactly how the prior gets used, so the weight is calibrated
    to the real prediction task rather than to a single-season autocorrelation
    (which would understate a 3-yr blend's reliability and over-shrink).
    """
    weights, samples = {}, {}
    for metric, _, _ in RATES:
        pairs = []
        for year in range(start + 3, end):
            for team in TEAMS:
                actual = history.get((team, year))
                prior = weighted_prior(history, team, year, metric)
                if actual and prior and actual[metric]:
                    pairs.append((prior, actual[metric]))
        r = pearson(pairs)
        weights[metric] = max(0.0, min(1.0, r))
        samples[metric] = len(pairs)
    return weights, samples


def league_means(history, season, metric):
    vals = [s[metric] for (t, y), s in history.items() if y == season and s[metric]]
    return sum(vals) / len(vals) if vals else 0.0


def project(history, weights, target_season, games, regression=0.5):
    """Build the projected control totals for every team.

    `regression` dials between the raw 3-yr trend (0.0) and the fitted
    shrinkage weights (1.0). See the module docstring — this is a judgment
    knob, not a fitted parameter.
    """
    # League baseline = recency-weighted league average, same 3-yr window.
    baseline = {}
    for metric, _, _ in RATES:
        vals, wts = 0.0, 0.0
        for offset, weight in enumerate(RECENCY_WEIGHTS, start=1):
            mean = league_means(history, target_season - offset, metric)
            if mean:
                vals += mean * weight
                wts += weight
        baseline[metric] = vals / wts if wts else 0.0

    rows = []
    for team in TEAMS:
        proj = {"team": team, "games": games}
        for metric, _, _ in RATES:
            prior = weighted_prior(history, team, target_season, metric)
            mean = baseline[metric]
            proj[metric + "_trend"] = prior if prior is not None else mean
            if prior is None:
                proj[metric] = mean
            else:
                # regression=0 -> w=1 (pure trend); regression=1 -> w=fitted
                w = 1.0 - regression * (1.0 - weights[metric])
                proj[metric] = w * prior + (1 - w) * mean

        # Rebuild season totals from the projected rates.
        plays = proj["plays_per_game"] * games
        dropbacks = plays * proj["pass_rate"]
        sacks = dropbacks * proj["sack_rate"]
        pass_att = dropbacks - sacks
        rush_att = plays - dropbacks

        proj.update({
            "plays": plays,
            "dropbacks": dropbacks,
            "sacks": sacks,
            "pass_att": pass_att,
            "rush_att": rush_att,
            "completions": pass_att * proj["comp_pct"],
            "pass_yds": pass_att * proj["ypa"],
            "pass_td": pass_att * proj["pass_td_rate"],
            "interceptions": pass_att * proj["int_rate"],
            "rush_yds": rush_att * proj["ypc"],
            "rush_td": rush_att * proj["rush_td_rate"],
        })
        proj["total_td"] = proj["pass_td"] + proj["rush_td"]
        rows.append(proj)
    return rows


HISTORY_COLUMNS = [
    "team", "season", "games", "plays", "plays_per_game", "pass_rate",
    "sack_rate", "pass_att", "rush_att", "sacks", "completions", "comp_pct",
    "pass_yds", "ypa", "pass_td", "pass_td_rate", "interceptions", "int_rate",
    "rush_yds", "ypc", "rush_td", "rush_td_rate",
]

PROJECTION_COLUMNS = [
    "team", "games", "plays_per_game", "plays", "pass_rate", "sacks",
    "pass_att", "rush_att", "comp_pct", "completions", "ypa", "pass_yds",
    "pass_td", "interceptions", "ypc", "rush_yds", "rush_td", "total_td",
    # raw 3-yr weighted trend, no shrinkage — reference beside each input
    "plays_per_game_trend", "pass_rate_trend", "ypa_trend",
    "pass_td_rate_trend", "ypc_trend", "rush_td_rate_trend",
]

# Columns that are counts rather than rates — rounded to whole numbers.
COUNT_COLUMNS = {
    "plays", "pass_att", "rush_att", "sacks", "completions", "pass_yds",
    "pass_td", "interceptions", "rush_yds", "rush_td", "total_td",
    "dropbacks", "games",
}


def fmt(column, value):
    if not isinstance(value, float):
        return value
    if column in COUNT_COLUMNS:
        return round(value)
    return round(value, 4)


def report_spread(history, projected, target_season, regression):
    """Show projected spread against recent real seasons.

    The point of this table is to make over-shrinkage impossible to miss: if
    the projected range is far tighter than what actually happens, the team
    totals can't differentiate players and --regression should come down.
    """
    print(f"\nSpread check  (--regression {regression})")
    print("  How wide is the projected league vs. what real seasons look like?\n")
    print(f"  {'metric':<10} {'projected':>18}   {'last 3 seasons':>18}")
    print(f"  {'-' * 10} {'-' * 18}   {'-' * 18}")

    for metric in ("plays", "pass_att", "rush_att", "pass_td", "rush_td"):
        proj_vals = sorted(r[metric] for r in projected)
        actuals = [s[metric] for (_, y), s in history.items()
                   if target_season - 3 <= y < target_season]
        lo, hi = min(actuals), max(actuals)
        print(f"  {metric:<10} {proj_vals[0]:>7.0f} - {proj_vals[-1]:<7.0f}"
              f"({proj_vals[-1] - proj_vals[0]:>3.0f})   "
              f"{lo:>7.0f} - {hi:<7.0f}({hi - lo:>3.0f})")


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([fmt(c, row.get(c, "")) for c in columns])
    print(f"  wrote {os.path.basename(path)}  ({len(rows)} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026, help="season to project")
    ap.add_argument("--start", type=int, default=2016, help="first history season")
    ap.add_argument("--games", type=int, default=17)
    ap.add_argument("--regression", type=float, default=0.5,
                    help="0 = pure 3-yr trend, 1 = full fitted shrinkage")
    args = ap.parse_args()
    if not 0.0 <= args.regression <= 1.0:
        sys.exit("--regression must be between 0 and 1")

    history = load_history(args.start, args.season)
    if not history:
        sys.exit(f"No cached team stats in {CACHE}. Run fetch_nflverse.py first.")

    years = sorted({y for _, y in history})
    print(f"Loaded {len(history)} team-seasons ({years[0]}-{years[-1]})\n")

    weights, samples = fit_shrinkage(history, args.start, args.season)
    print("Fitted shrinkage weights  (w = how much of the team's own 3-yr")
    print("trend survives; 1-w is pulled to the league mean)\n")
    print(f"  {'metric':<16} {'w':>6}   {'n':>5}   trust")
    print(f"  {'-' * 16} {'-' * 6}   {'-' * 5}   {'-' * 5}")
    for metric, _, _ in RATES:
        w = weights[metric]
        bar = "#" * int(round(w * 20))
        print(f"  {metric:<16} {w:>6.3f}   {samples[metric]:>5}   {bar}")

    history_rows = [history[k] for k in sorted(history, key=lambda k: (k[0], k[1]))]
    projected = project(history, weights, args.season, args.games,
                        regression=args.regression)

    print()
    write_csv(os.path.join(HERE, "team_totals_history.csv"),
              HISTORY_COLUMNS, history_rows)
    write_csv(os.path.join(HERE, f"team_totals_{args.season}.csv"),
              PROJECTION_COLUMNS, projected)

    report_spread(history, projected, args.season, args.regression)

    print(f"\n{args.season} projected team totals (sorted by plays):\n")
    print(f"  {'TM':<4} {'PLAYS':>6} {'PASS':>6} {'RUSH':>6} {'PYDS':>6} "
          f"{'PTD':>5} {'RYDS':>6} {'RTD':>5} {'TTD':>5}")
    for row in sorted(projected, key=lambda r: -r["plays"]):
        print(f"  {row['team']:<4} {row['plays']:>6.0f} {row['pass_att']:>6.0f} "
              f"{row['rush_att']:>6.0f} {row['pass_yds']:>6.0f} "
              f"{row['pass_td']:>5.1f} {row['rush_yds']:>6.0f} "
              f"{row['rush_td']:>5.1f} {row['total_td']:>5.1f}")


if __name__ == "__main__":
    sys.exit(main())
