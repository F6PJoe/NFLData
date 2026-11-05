"""Where we differ from consensus, which PART of the projection is right?
2026 wks 3-8, current model walk-forward dump (DUMP) vs archived consensus / FTN lines.
For each stat: slope of (actual - consensus) on (ours - consensus). 1 = our difference is
fully right, 0.5 = half of it, 0 = it is noise. Also: how much of the points gap each part makes.
"""
import csv, os, sys, collections
import numpy as np
sys.path.insert(0, "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model")
from audit_vs_sources import norm
W = "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_proj/weekly"
DUMP = sys.argv[1]   # a 2026 backtest dump: project.py --year 2026 --dump FILE
SRC = sys.argv[2] if len(sys.argv) > 2 else "consensus"
f = lambda r, k: float(r.get(k) or 0)
cons = {}
for w in range(3, 9):
    for pos in ("qb", "wr", "te", "rb"):
        p = f"{W}/2026-wk{w:02d}/{SRC}_{pos}.csv"
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                cons[(w, norm(r[pos.upper()]))] = r
d = [r for r in csv.DictReader(open(DUMP, encoding="utf-8")) if 3 <= int(r["week"]) <= 8]
STATS = {
    "WR": [("targets", "tgt_p", "tgt_a", "Targets"), ("rec", "rec_p", "rec_a", "Rec"),
           ("rec yds", "recyd_p", "recyd_a", "Rec Yds"), ("rec TD", "rectd_p", "rectd_a", "Rec TD")],
    "QB": [("pass att", "patt_p", "patt_a", "Pass Att"), ("pass yds", "pyds_p", "pyds_a", "Pass Yds"),
           ("pass TD", "ptd_p", "ptd_a", "Pass TD"), ("INT", "int_p", "int_a", "Pass Int"),
           ("carries", "car_p", "car_a", "Rush Att"), ("rush yds", "rushyd_p", "rushyd_a", "Rush Yds"),
           ("rush TD", "rushtd_p", "rushtd_a", "Rush TD")],
}
STATS["TE"] = STATS["WR"]
STATS["RB"] = [("carries", "car_p", "car_a", "Rush Att"), ("rush yds", "rushyd_p", "rushyd_a", "Rush Yds"),
               ("rush TD", "rushtd_p", "rushtd_a", "Rush TD"), ("targets", "tgt_p", "tgt_a", "Targets"),
               ("rec yds", "recyd_p", "recyd_a", "Rec Yds"), ("rec TD", "rectd_p", "rectd_a", "Rec TD")]
PTS = {"rec": .5, "rec yds": .1, "rec TD": 6, "pass yds": .04, "pass TD": 4, "INT": -2, "rush yds": .1, "rush TD": 6}
for pos in ("WR", "TE", "QB", "RB"):
    rows = []
    for r in d:
        if r["pos"] != pos:
            continue
        c = cons.get((int(r["week"]), norm(r["player"])))
        if not c:
            continue
        if pos == "QB" and (f(c, "Pass Att") < 15 or abs(f(r, "patt_p") - f(c, "Pass Att")) > 12):
            continue              # not the same starter call -- a news gap, not a model gap
        if max(f(r, "proj"), sum(PTS.get(s[0], 0) * f(c, s[3]) for s in STATS[pos])) < 5:
            continue              # fantasy-relevant only
        rows.append((r, c))
    print(f"\n{pos}  n={len(rows)} player-weeks (fantasy-relevant{', same starter' if pos == 'QB' else ''})")
    print(f"  {'stat':9s} {'ours':>7s} {'cons':>7s} {'actual':>7s}  {'slope':>5s}  {'r':>5s}   pts gap from it (avg |.|)")
    for lab, kp, ka, kc in STATS[pos]:
        o = np.array([f(r, kp) for r, c in rows]); a = np.array([f(r, ka) for r, c in rows])
        cc = np.array([f(c, kc) for r, c in rows])
        x, y = o - cc, a - cc
        b = (x * y).sum() / (x * x).sum() if (x * x).sum() else float("nan")    # through 0
        rr = np.corrcoef(x, y)[0, 1] if x.std() and y.std() else float("nan")
        pg = np.abs(PTS.get(lab, 0) * x).mean()
        print(f"  {lab:9s} {o.mean():7.2f} {cc.mean():7.2f} {a.mean():7.2f}  {b:5.2f}  {rr:5.2f}   {pg:.2f}")
    # efficiency parts (per target / per attempt) where it applies
    if pos in ("WR", "TE"):
        for lab, num_, den_, cnum, cden in (("yds/tgt", "recyd_p", "tgt_p", "Rec Yds", "Targets"),
                                            ("TD/tgt x100", "rectd_p", "tgt_p", "Rec TD", "Targets")):
            sc = 100 if "x100" in lab else 1
            o = np.array([sc * f(r, num_) / f(r, den_) if f(r, den_) else 0 for r, c in rows])
            cc = np.array([sc * f(c, cnum) / f(c, cden) if f(c, cden) else 0 for r, c in rows])
            # actual rate over many targets -> compare at the player-week level weighted by targets
            t = np.array([f(r, "tgt_a") for r, c in rows])
            a = np.array([sc * f(r, num_.replace("_p", "_a")) / f(r, "tgt_a") if f(r, "tgt_a") else 0 for r, c in rows])
            x, y = o - cc, a - cc
            b = (t * x * y).sum() / (t * x * x).sum()
            print(f"  {lab:11s} ours {np.average(o, weights=t):5.2f} cons {np.average(cc, weights=t):5.2f}"
                  f" actual {np.average(a, weights=t):5.2f}  slope {b:5.2f} (target-weighted)")
