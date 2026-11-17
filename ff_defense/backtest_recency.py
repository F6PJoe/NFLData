"""Should recent games count more in the Def Rating and Opp Off EPA columns?

Joe asked 2026-11-10. Both columns currently weight every play in the
season equally. The intuition for recency is obvious -- injuries, scheme
changes, a team that's figured something out in October -- but the whole
point of shrinking toward a prior is that defensive samples are noisy, and
down-weighting old games throws sample away. Which effect wins is an
empirical question.

Method, matching backtest_prior_decay.py so the numbers are comparable:
for each season 2021-25 and each cutoff week W, build the rating from
weeks 1..W, then score it by Spearman rank correlation against the SAME
rating computed over the rest of that season (weeks W+1..end). Higher =
the chart ranks teams better for the games still to come.

Recency is an exponential half-life in weeks: a play from h weeks before
the cutoff counts half as much as one from the cutoff week. "none" is the
current behaviour (every play equal). The decayed weights also feed the
shrinkage as the effective sample size, so a heavily-decayed rating
correctly sits closer to its prior.

Defense is the z-blend of EPA/play allowed + success rate allowed, shrunk
toward the prior season's rank at K=100 (standing in for Joe's preseason
ranks, same as backtest_prior_decay.py). Offense is EPA/play shrunk toward
league average at K=350.
"""
import numpy as np
from scipy.stats import spearmanr
from fetch_nflverse_epa import fetch_pbp
from team_names import normalize

def z(s): return (s - s.mean()) / (s.std(ddof=0) or 1)

def agg(df, W=None, half_life=None):
    """Weighted per-team means plus effective sample size."""
    d = df.copy()
    if half_life is None:
        d["w"] = 1.0
    else:
        lam = 0.5 ** (1.0 / half_life)
        d["w"] = lam ** (W - d["week"])
    g = d.groupby("team").apply(lambda x: pd.Series({
        "e": np.average(x["epa"], weights=x["w"]),
        "s": np.average(x["success"], weights=x["w"]),
        "n": x["w"].sum(),
    }), include_groups=False)
    return g

import pandas as pd

season = {}
for yr in range(2020, 2026):
    p = fetch_pbp(yr, extra_cols=["success"])
    p = p[p["success"].notna() & p["defteam"].notna()].copy()
    p["dteam"] = [normalize(t) for t in p["defteam"]]
    p["oteam"] = [normalize(t) for t in p["posteam"]]
    season[yr] = p

HALF_LIVES = [None, 8, 6, 4, 3, 2]
LABEL = {None: "none (current)"}

def def_rating(df, prior_z, W, hl):
    g = agg(df.rename(columns={"dteam": "team"}), W, hl)
    obs = -(z(g["e"]) + z(g["s"])) / 2
    pr = prior_z.reindex(g.index).fillna(0.0)
    return (obs * g["n"] + pr * 100) / (g["n"] + 100)

def off_rating(df, W, hl):
    g = agg(df.rename(columns={"oteam": "team"}), W, hl)
    mean = np.average(df["epa"])
    return (g["e"] * g["n"] + mean * 350) / (g["n"] + 350)

res = {("def", h): {} for h in HALF_LIVES}
res.update({("off", h): {} for h in HALF_LIVES})
for yr in range(2021, 2026):
    prev = agg(season[yr - 1].rename(columns={"dteam": "team"}))
    # Prior-season rating, z-scored -- higher = better defense. (An earlier
    # draft ranked it and negated, which produced a -1..-32 series that
    # swamped the z-scored observed half and inverted the sign.)
    prior_z = z(-(z(prev["e"]) + z(prev["s"])) / 2)
    cur = season[yr]
    for W in range(3, 15):
        early, late = cur[cur["week"] <= W], cur[cur["week"] > W]
        if late["week"].nunique() < 3: continue
        d_t = -(z(agg(late.rename(columns={"dteam": "team"}))["e"])
                + z(agg(late.rename(columns={"dteam": "team"}))["s"])) / 2
        o_t = agg(late.rename(columns={"oteam": "team"}))["e"]
        for hl in HALF_LIVES:
            d = def_rating(early, prior_z, W, hl)
            idx = sorted(set(d.index) & set(d_t.index))
            res[("def", hl)].setdefault(W, []).append(
                spearmanr(d[idx], d_t[idx]).correlation)
            o = off_rating(early, W, hl)
            idx = sorted(set(o.index) & set(o_t.index))
            res[("off", hl)].setdefault(W, []).append(
                spearmanr(o[idx], o_t[idx]).correlation)

for col in ("def", "off"):
    name = "Def Rating (column G)" if col == "def" else "Opp Off EPA (column H)"
    print(f"\n=== {name} ===")
    print(f"{'half-life':<16}{'wk3-6':>8}{'wk7-10':>9}{'wk11-14':>9}{'overall':>9}")
    for hl in HALF_LIVES:
        m = {W: np.mean(v) for W, v in res[(col, hl)].items()}
        a = np.mean([m[w] for w in m if w <= 6])
        b = np.mean([m[w] for w in m if 7 <= w <= 10])
        c = np.mean([m[w] for w in m if w >= 11])
        lbl = LABEL.get(hl, f"{hl} weeks")
        print(f"{lbl:<16}{a:>8.3f}{b:>9.3f}{c:>9.3f}{np.mean(list(m.values())):>9.3f}")
