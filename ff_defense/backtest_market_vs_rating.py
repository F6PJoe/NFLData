"""Does the EPA rating still add anything once you have the Vegas line?

Joe asked (2026-11-10) whether major injuries/trades -- Puka out for the
Rams, Cousins to Minnesota -- could be factored into the Def Rating and
Opp Off EPA columns, noting the lines and site projections help but might
not be enough.

Before building anything: the chart ALREADY has three columns that react
to news within hours (implied totals, ECR, Yahoo projection). The ratings
are deliberately the slow part. So the question is whether making them
chase news adds information, or just double-counts the market inside a
roto sum.

Test: for each team-week, predict that team's ACTUAL offensive EPA/play in
the upcoming week from
  (a) its season-to-date offensive EPA through the prior week, shrunk
      toward league average at K=350 -- i.e. what column H does today
  (b) its market implied total for that game (total/2 - spread/2), from
      nflverse's historical closing lines
  (c) both, as an equal-weight blend of ranks
Spearman against the actual result, pooled over 2021-25.

A market line already prices every injury and trade. If (b) beats (a) by a
wide margin and (c) barely beats (b), news-chasing in the rating is
redundant. If (a) and (c) hold up, the rating is carrying something the
line doesn't.
"""
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from fetch_nflverse_epa import fetch_pbp
from fetch_schedule import fetch_schedule
from team_names import normalize

games = fetch_schedule()
games = games[games["spread_line"].notna() & games["total_line"].notna()]

lines = []
for _, g in games.iterrows():
    tot, spr = g["total_line"], g["spread_line"]   # spread_line is HOME-relative
    lines.append({"season": g["season"], "week": g["week"],
                  "team": normalize(g["home_team"]), "implied": tot / 2 + spr / 2})
    lines.append({"season": g["season"], "week": g["week"],
                  "team": normalize(g["away_team"]), "implied": tot / 2 - spr / 2})
lines = pd.DataFrame(lines)

rows = []
for yr in range(2021, 2026):
    p = fetch_pbp(yr)
    p = p[p["epa"].notna() & p["posteam"].notna()].copy()
    p["team"] = [normalize(t) for t in p["posteam"]]
    wk_epa = p.groupby(["team", "week"])["epa"].agg(["mean", "size"]).reset_index()
    league = p["epa"].mean()
    for W in range(3, 17):
        prior = p[p["week"] <= W].groupby("team")["epa"].agg(["mean", "size"])
        rated = (prior["mean"] * prior["size"] + league * 350) / (prior["size"] + 350)
        actual = wk_epa[wk_epa["week"] == W + 1].set_index("team")
        actual = actual[actual["size"] >= 20]            # drop sliver samples
        ln = lines[(lines.season == yr) & (lines.week == W + 1)].set_index("team")["implied"]
        idx = sorted(set(rated.index) & set(actual.index) & set(ln.index))
        if len(idx) < 8: continue
        for t in idx:
            rows.append({"rating": rated[t], "implied": ln[t],
                         "actual": actual.loc[t, "mean"]})

df = pd.DataFrame(rows)
r_rating = spearmanr(df["rating"], df["actual"]).correlation
r_implied = spearmanr(df["implied"], df["actual"]).correlation
blend = df["rating"].rank(pct=True) + df["implied"].rank(pct=True)
r_blend = spearmanr(blend, df["actual"]).correlation

print(f"{len(df):,} team-weeks, 2021-25\n")
print(f"  season-to-date EPA rating (column H today) : {r_rating:.3f}")
print(f"  Vegas implied total alone                  : {r_implied:.3f}")
print(f"  both, equal-weight rank blend              : {r_blend:.3f}")
print(f"\n  rating's correlation with the line itself  : "
      f"{spearmanr(df['rating'], df['implied']).correlation:.3f}")
