"""Does a near-miss setting move us toward consensus / FTN where Joe has been concerned?
2026 wks 3-8 backtest projections (same conditions for baseline and variant).
gap = mean |ours - source|; change = variant gap - baseline gap (negative = closer).
Joe's tiebreak for near-tie settings (2026-11-04) -- see TESTED_SETTINGS.md.

    python project.py --year 2026 --dump DIR/d_now_2026.csv                 # baseline
    python project.py --year 2026 --set NAME=VALUE --dump DIR/c_<tag>.csv   # each variant
    DUMPS=DIR python research/consensus_closeness.py <tag> [<tag> ...]
"""
import csv, collections, os, sys
sys.path.insert(0, "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model")
from audit_vs_sources import norm
W = "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_proj/weekly"
D = "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model/data"
S = os.environ.get("DUMPS", ".")
f = lambda r, k: float(r.get(k) or 0)
def pts(r, pos):
    if pos == "QB":
        return (f(r, "Pass Yds") * .04 + f(r, "Pass TD") * 4 - f(r, "Pass Int") * 2 + f(r, "Rush Yds") * .1
                + f(r, "Rush TD") * 6 - 2 * f(r, "Fumbles"))
    return (f(r, "Rec") * .5 + f(r, "Rec Yds") * .1 + f(r, "Rec TD") * 6 + f(r, "Rush Yds") * .1
            + f(r, "Rush TD") * 6 - 2 * f(r, "Fum"))
src = {}   # (source, week, normname) -> pts
for w in range(3, 9):
    for s in ("consensus", "ftn"):
        for pos in ("qb", "rb", "wr", "te"):
            try:
                for r in csv.DictReader(open(f"{W}/2026-wk{w:02d}/{s}_{pos}.csv", encoding="utf-8-sig")):
                    src[(s, w, norm(r[pos.upper()]))] = pts(r, pos.upper())
            except FileNotFoundError:
                pass
# WR stars: 25%+ of team targets in earlier games
st = [r for r in csv.DictReader(open(f"{D}/stats_player_week_2026.csv", encoding="utf-8")) if r.get("season_type", "REG") in ("REG", "")]
tt = collections.Counter(); g = collections.defaultdict(dict)
for r in st:
    tm = r.get("team") or r.get("recent_team"); w = int(r["week"]); tt[(tm, w)] += f(r, "targets"); g[r["player_id"]][w] = (tm, f(r, "targets"))
def star(pid, tm, w):
    x = [(wk, t) for wk, (t_, t) in g.get(pid, {}).items() if wk < w and t_ == tm]
    if len(x) < 2: return False
    tot = sum(tt[(tm, wk)] for wk, _ in x); return tot and sum(t for _, t in x) / tot >= 0.25
JOE = {"Jayden Daniels", "Trevor Lawrence", "Brock Purdy", "Sam Darnold", "C.J. Stroud", "Justin Jefferson", "Dallas Goedert",
       "Parker Washington", "Nico Collins", "Zay Flowers"}
def load(p): return {(r["player_id"], int(r["week"])): r for r in csv.DictReader(open(p, encoding="utf-8")) if 3 <= int(r["week"]) <= 8}
base = load(f"{S}/d_now_2026.csv")
groups = lambda r, w: [x for x, ok in (("QB", r["pos"] == "QB"), ("WR stars", r["pos"] == "WR" and star(r["player_id"], r["team"], w)),
                                         ("TE", r["pos"] == "TE"), ("Joe's names", r["player"] in JOE)) if ok]
names = sys.argv[1:]
print(f"{'setting':10}{'group':13}{'n':>5}{'vs cons':>9}{'vs FTN':>8}{'vs actual':>10}   (change in avg gap; - = closer)")
for n in names:
    var = load(f"{S}/c_{n}.csv")
    acc = collections.defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0, 0.0])
    for k, b in base.items():
        v = var.get(k)
        if not v: continue
        w = k[1]; nm = norm(b["player"]); bp, vp, act = f(b, "proj"), f(v, "proj"), f(b, "actual")
        if abs(bp - vp) < 1e-6: continue
        for grp in groups(b, w) + ["all changed"]:
            a = acc[grp]
            c = src.get(("consensus", w, nm)); t = src.get(("ftn", w, nm))
            if c is not None: a[0] += 1; a[1] += abs(vp - c) - abs(bp - c)
            if t is not None: a[4] += 1; a[5] += abs(vp - t) - abs(bp - t)
            a[2] += abs(vp - act) - abs(bp - act); a[3] += 1
    for grp in ("all changed", "QB", "WR stars", "TE", "Joe's names"):
        a = acc.get(grp)
        if not a or not a[3]: continue
        print(f"{n:10}{grp:13}{int(a[3]):5d}{(a[1]/a[0] if a[0] else 0):+9.2f}{(a[5]/a[4] if a[4] else 0):+8.2f}{a[2]/a[3]:+10.2f}")
    print()
