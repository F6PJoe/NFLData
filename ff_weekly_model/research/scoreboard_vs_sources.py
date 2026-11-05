"""Who is actually more accurate at WR / TE (and QB / RB) -- our PUBLISHED finals vs every source.

Joe 2026-11-05: "you say everything we try is worse for us overall, but our projections are
usually bottom of the pack for WR and TE. We have to be missing something."

Backtests compare the model with itself; this compares what we published
(data/projections_<yr>_wk<NN>_final.csv) with each source's archived line for the same week
(ff_weekly_proj/weekly/<yr>-wk<NN>/), scored the same half-PPR way, on the players BOTH
projected who actually played (a stat line that week), 5+ points by either side.
Also splits the miss into bias (too high / too low) and by tier, so "what are we missing"
starts answered.

    python research/scoreboard_vs_sources.py --year 2026 --weeks 3-8 [--pos WR]
"""
import argparse, csv, collections, math, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from audit_vs_sources import norm
W = os.path.join(os.path.dirname(HERE), "ff_weekly_proj", "weekly")
DATA = os.path.join(HERE, "data")
SOURCES = ("consensus", "ftn", "espn", "cbs", "yahoo", "4for4", "fantasydata", "fantasylife", "draftsharks", "fftoday")
f = lambda r, k: float(r.get(k) or 0)


def src_pts(r, pos):
    if pos == "QB":
        return (f(r, "Pass Yds") * .04 + f(r, "Pass TD") * 4 - f(r, "Pass Int") * 2 + f(r, "Rush Yds") * .1
                + f(r, "Rush TD") * 6 - 2 * (f(r, "Fumbles") or f(r, "Fum")))
    return (f(r, "Rec") * .5 + f(r, "Rec Yds") * .1 + f(r, "Rec TD") * 6 + f(r, "Rush Yds") * .1
            + f(r, "Rush TD") * 6 - 2 * (f(r, "Fum") or f(r, "Fumbles")))


def actual_pts(r):
    pos = r["position"]
    if pos == "QB":
        return (f(r, "passing_yards") * .04 + f(r, "passing_tds") * 4 - f(r, "passing_interceptions") * 2
                + f(r, "rushing_yards") * .1 + f(r, "rushing_tds") * 6
                - 2 * (f(r, "sack_fumbles_lost") + f(r, "rushing_fumbles_lost")))
    return (f(r, "receptions") * .5 + f(r, "receiving_yards") * .1 + f(r, "receiving_tds") * 6
            + f(r, "rushing_yards") * .1 + f(r, "rushing_tds") * 6
            - 2 * (f(r, "rushing_fumbles_lost") + f(r, "receiving_fumbles_lost")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--weeks", default="3-8")
    ap.add_argument("--pos", default="WR,TE,QB,RB")
    a = ap.parse_args()
    w0, w1 = (int(x) for x in a.weeks.split("-"))
    act = {}
    for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r.get("season_type", "REG") == "REG" and w0 <= int(r["week"]) <= w1:
            act[(int(r["week"]), r["player_id"])] = (actual_pts(r), r)
    for pos in a.pos.split(","):
        pairs = collections.defaultdict(list)     # source -> [(ours, theirs, actual, week, name, tgt_o, tgt_s, tgt_a)]
        for w in range(w0, w1 + 1):
            fp = os.path.join(DATA, f"projections_{a.year}_wk{w:02d}_final.csv")
            if not os.path.exists(fp):
                continue
            ours = {norm(r["player"]): r for r in csv.DictReader(open(fp, encoding="utf-8-sig")) if r["pos"] == pos}
            for s in SOURCES:
                p = os.path.join(W, f"{a.year}-wk{w:02d}", f"{s}_{pos.lower()}.csv")
                if not os.path.exists(p):
                    continue
                for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                    nm = norm(r.get(pos) or r.get("Player") or "")
                    o = ours.get(nm)
                    if not o:
                        continue
                    ac = act.get((w, o["player_id"]))
                    if not ac:
                        continue                  # did not play
                    op, sp = f(o, "half_ppr"), src_pts(r, pos)
                    if max(op, sp) < 5:
                        continue
                    pairs[s].append((op, sp, ac[0], w, o["player"], f(o, "targets"), f(r, "Targets"),
                                     f(ac[1], "targets")))
        print(f"\n{pos}  weeks {w0}-{w1}: ours vs each source on the same player-weeks (both 5+, played)")
        print(f"  {'source':12s} {'n':>5s} {'our miss':>9s} {'their miss':>10s} {'we win':>7s}"
              f" {'our bias':>9s} {'their bias':>10s}   (miss = avg |proj - actual|; bias = avg proj - actual)")
        rank = []
        for s, v in pairs.items():
            n = len(v)
            mo = sum(abs(o - x) for o, _, x, *_ in v) / n
            ms = sum(abs(t - x) for _, t, x, *_ in v) / n
            win = sum(abs(o - x) < abs(t - x) for o, t, x, *_ in v) / n
            bo = sum(o - x for o, _, x, *_ in v) / n
            bs = sum(t - x for _, t, x, *_ in v) / n
            rank.append((ms - mo, s))
            print(f"  {s:12s} {n:5d} {mo:9.2f} {ms:10.2f} {win:7.0%} {bo:+9.2f} {bs:+10.2f}")
        better = sum(1 for d, _ in rank if d > 0)
        print(f"  -> we beat {better} of {len(rank)} sources at {pos}")
        v = pairs.get("consensus") or []
        if v:
            print("  by tier (consensus points) -- our miss / consensus miss, our bias / consensus bias:")
            for lo, hi in ((15, 99), (10, 15), (7, 10), (5, 7), (0, 5)):
                t = [x for x in v if lo <= x[1] < hi]
                if t:
                    n = len(t)
                    print(f"    cons {lo:>2d}-{hi if hi < 99 else '+':<3}  n={n:3d}  miss {sum(abs(o-x) for o,_,x,*_ in t)/n:5.2f} / {sum(abs(c-x) for _,c,x,*_ in t)/n:5.2f}"
                          f"   bias {sum(o-x for o,_,x,*_ in t)/n:+5.2f} / {sum(c-x for _,c,x,*_ in t)/n:+5.2f}"
                          + (f"   targets ours {sum(x[5] for x in t)/n:4.1f} cons {sum(x[6] for x in t)/n:4.1f} actual {sum(x[7] for x in t)/n:4.1f}"
                             if pos in ("WR", "TE") else ""))


if __name__ == "__main__":
    main()
