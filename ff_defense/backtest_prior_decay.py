"""Does the preseason prior in fetch_def_rating.py fade fast enough?

Joe's question (2026-09-22): the prior felt like it lingered far too long
at K_PRIOR=300 -- still 28% of the rating in week 13 -- given preseason
defensive rankings are so often wrong. FTN's DAVE drops preseason entirely
by week 13 and he wanted to go earlier than that.

Backtest 2021-25. Stand-in for his preseason ranks: the PRIOR SEASON's
defensive rating rank, reasonable since his own 2026 ranks correlate
+0.703 with 2025 results -- they largely encode last season.

For each season and cutoff week W:
  observed = def rating from weeks 1..W
  target   = def rating over the REST of the season
  score    = Spearman(blend(observed, prior, K), target)

RESULT -- he was right about the weight, wrong about zeroing it:

    schedule                     wk1-4   wk5-9  wk10-14  overall
    current: K=300 flat          0.268   0.310    0.285    0.289
    K=150 flat                   0.278   0.322    0.309    0.305
    K=100 flat                   0.276   0.321    0.311    0.305
    ramp 400 -> 0 by wk 6        0.266   0.317    0.302    0.297
    ramp 400 -> 0 by wk 8        0.266   0.319    0.302    0.298
    ramp 400 -> 0 by wk 10       0.265   0.314    0.302    0.295
    DAVE-like: 300 to wk13       0.268   0.310    0.296    0.293

K=300 is the second-worst option and a lower K beats it in every bucket.
But EVERY ramp-to-zero lost to simply keeping a small constant prior, and
the DAVE-style week-13 cliff barely beat doing nothing. Past ~600 plays
the prior is only worth ~12% anyway, and at that weight it isn't "using
preseason ranks" -- it's mild regularization that stops one odd stretch of
games from throwing a rank around. Removing it measurably costs accuracy.

K=100 and K=150 are statistically tied; 100 chosen because it decays
faster, which is the direction Joe wanted.

Re-run this if the prior's role is ever questioned again.
"""
import numpy as np
from scipy.stats import spearmanr
from fetch_nflverse_epa import fetch_pbp
from team_names import normalize

def z(s): return (s - s.mean()) / s.std(ddof=0)
def rating(df):
    g = df.groupby("team").agg(e=("epa","mean"), s=("success","mean"), n=("epa","size"))
    return -(z(g["e"]) + z(g["s"]))/2, g["n"]

season = {}
for yr in range(2020, 2026):
    p = fetch_pbp(yr, extra_cols=["success"])
    p = p[p["success"].notna() & p["defteam"].notna()].copy()
    p["team"] = [normalize(t) for t in p["defteam"]]
    season[yr] = p

SCHEDULES = {
    "current: K=300 flat":      lambda w: 300,
    "K=150 flat":               lambda w: 150,
    "K=100 flat":               lambda w: 100,
    "ramp 400 -> 0 by wk 6":    lambda w: max(0.0, 400*(1 - (w-1)/5)),
    "ramp 400 -> 0 by wk 8":    lambda w: max(0.0, 400*(1 - (w-1)/7)),
    "ramp 400 -> 0 by wk 10":   lambda w: max(0.0, 400*(1 - (w-1)/9)),
    "DAVE-like: 300 to wk13":   lambda w: 300 if w < 13 else 0,
}
res = {k: {} for k in SCHEDULES}
for yr in range(2021, 2026):
    prior_r, _ = rating(season[yr-1]); cur = season[yr]
    for W in range(1, 15):
        early, late = cur[cur["week"] <= W], cur[cur["week"] > W]
        if late["week"].nunique() < 3: continue
        obs, n = rating(early); tgt, _ = rating(late)
        teams = sorted(set(obs.index) & set(tgt.index) & set(prior_r.index))
        o, t, pr, nn = obs[teams], tgt[teams], z(prior_r[teams]), n[teams]
        for name, f in SCHEDULES.items():
            K = f(W)
            b = (o*nn + pr*K)/(nn + K) if K > 0 else o
            res[name].setdefault(W, []).append(spearmanr(b, t).correlation)

print(f"{'schedule':<26}{'wk1-4':>8}{'wk5-9':>8}{'wk10-14':>9}{'overall':>9}")
for name in SCHEDULES:
    m = {W: np.mean(v) for W, v in res[name].items()}
    e = np.mean([m[w] for w in m if w <= 4])
    mid = np.mean([m[w] for w in m if 5 <= w <= 9])
    l = np.mean([m[w] for w in m if w >= 10])
    print(f"{name:<26}{e:>8.3f}{mid:>8.3f}{l:>9.3f}{np.mean(list(m.values())):>9.3f}")
