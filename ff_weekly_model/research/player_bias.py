"""Which players are we ROUTINELY high or low on (vs actual and vs consensus)? weeks of PUBLISHED finals.

Joe 2026-11-10: "it feels like there are a couple of players we are routinely low on and some we are
routinely high on". Same pairing as scoreboard_vs_sources.py (our final vs the archived consensus,
played, 5+ either side). Per player with --min-weeks weeks: our avg (proj - actual), consensus avg,
and 'cost' = sum over weeks of (our miss - consensus miss) -- where we lose ground to consensus.

    python research/player_bias.py --year 2026 --weeks 3-9 [--pos TE] [--min-weeks 4]
"""
import argparse, collections, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoreboard_vs_sources import DATA, W, norm, f, src_pts, actual_pts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026); ap.add_argument("--weeks", default="3-9")
    ap.add_argument("--pos", default="QB,RB,WR,TE"); ap.add_argument("--min-weeks", type=int, default=4)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    w0, w1 = (int(x) for x in a.weeks.split("-"))
    act = {}
    for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r.get("season_type", "REG") == "REG" and w0 <= int(r["week"]) <= w1:
            act[(int(r["week"]), r["player_id"])] = (actual_pts(r), f(r, "targets"), f(r, "carries"))
    for pos in a.pos.split(","):
        by = collections.defaultdict(list)
        for w in range(w0, w1 + 1):
            fp = os.path.join(DATA, f"projections_{a.year}_wk{w:02d}_final.csv")
            cp = os.path.join(W, f"{a.year}-wk{w:02d}", f"consensus_{pos.lower()}.csv")
            if not (os.path.exists(fp) and os.path.exists(cp)):
                continue
            ours = {norm(r["player"]): r for r in csv.DictReader(open(fp, encoding="utf-8-sig")) if r["pos"] == pos}
            for r in csv.DictReader(open(cp, encoding="utf-8-sig")):
                o = ours.get(norm(r.get(pos) or r.get("Player") or ""))
                if not o or (w, o["player_id"]) not in act:
                    continue
                op, cp_ = f(o, "half_ppr"), src_pts(r, pos)
                if max(op, cp_) < 5:
                    continue
                ac, at, acar = act[(w, o["player_id"])]
                by[o["player"]].append((w, op, cp_, ac, f(o, "targets"), f(r, "Targets"), at))
        rows = []
        for p, v in by.items():
            if len(v) < a.min_weeks:
                continue
            n = len(v)
            rows.append(dict(p=p, n=n, ob=sum(o - x for _, o, c, x, *_ in v) / n, cb=sum(c - x for _, o, c, x, *_ in v) / n,
                             gap=sum(o - c for _, o, c, *_ in v) / n, cost=sum(abs(o - x) - abs(c - x) for _, o, c, x, *_ in v),
                             to=sum(t for *_, t, _, _ in v) / n, tc=sum(t for *_, t, _ in v) / n, ta=sum(v_[-1] for v_ in v) / n,
                             same=sum((o - c) * (x - c) > 0 for _, o, c, x, *_ in v)))
        print(f"\n{pos} weeks {w0}-{w1}, players with {a.min_weeks}+ weeks -- where we LOSE most to consensus (cost = pts lost)")
        print(f"  {'player':24}{'wks':>4} {'ours-cons':>9} {'our bias':>9} {'cons bias':>9} {'cost':>6}  tgt ours/cons/actual   our lean right")
        for r in sorted(rows, key=lambda r: -r["cost"])[:a.top]:
            print(f"  {r['p']:24}{r['n']:>4} {r['gap']:+9.2f} {r['ob']:+9.2f} {r['cb']:+9.2f} {r['cost']:6.1f}  {r['to']:4.1f} / {r['tc']:4.1f} / {r['ta']:4.1f}      {r['same']}/{r['n']}")
        print(f"  ... where we GAIN most:")
        for r in sorted(rows, key=lambda r: r["cost"])[:4]:
            print(f"  {r['p']:24}{r['n']:>4} {r['gap']:+9.2f} {r['ob']:+9.2f} {r['cb']:+9.2f} {r['cost']:6.1f}  {r['to']:4.1f} / {r['tc']:4.1f} / {r['ta']:4.1f}      {r['same']}/{r['n']}")
        lo = sum(1 for r in rows if r["gap"] <= -1.5); hi = sum(1 for r in rows if r["gap"] >= 1.5)
        print(f"  routinely 1.5+ under consensus: {lo} players; 1.5+ over: {hi} (of {len(rows)})")

if __name__ == "__main__":
    main()
