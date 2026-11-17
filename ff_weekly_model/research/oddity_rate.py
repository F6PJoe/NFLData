"""How often does each projection break away from the other sites, and are the breaks right?

Joe 2026-11-17: "we just have too many oddities that other sites seem to not have". For every source
(and our published final), each player-week is compared with the AVERAGE OF THE OTHER individual
sites (leave-one-out, 4+ others, that average 5+ points). A 'break' = 3+ points away from it.
Reported per source: breaks per week, how often the break was closer to what he scored, and the
net points the breaks gained (+) or cost (-) vs just using the others' average.

    python research/oddity_rate.py --year 2026 --weeks 3-10 [--gap 3]
"""
import argparse, collections, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoreboard_vs_sources import DATA, W, SOURCES, f, src_pts, actual_pts, norm

INDIV = [s for s in SOURCES if s != "consensus"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026); ap.add_argument("--weeks", default="3-10")
    ap.add_argument("--gap", type=float, default=3.0); ap.add_argument("--list", default="")
    a = ap.parse_args()
    w0, w1 = (int(x) for x in a.weeks.split("-"))
    act = {}
    for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r.get("season_type", "REG") == "REG" and w0 <= int(r["week"]) <= w1:
            act[(int(r["week"]), r["player_id"])] = actual_pts(r)
    stat = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0.0, 0]))  # src->pos->[breaks,right,net,n]
    weeks = set(); listing = []
    for w in range(w0, w1 + 1):
        fp = os.path.join(DATA, f"projections_{a.year}_wk{w:02d}_final.csv")
        if not os.path.exists(fp):
            continue
        weeks.add(w)
        for pos in ("QB", "RB", "WR", "TE"):
            ours = {norm(r["player"]): r for r in csv.DictReader(open(fp, encoding="utf-8-sig")) if r["pos"] == pos}
            val = collections.defaultdict(dict)                 # name -> source -> pts
            for nm, r in ours.items():
                val[nm]["OURS"] = f(r, "half_ppr")
            for s in INDIV:
                p = os.path.join(W, f"{a.year}-wk{w:02d}", f"{s}_{pos.lower()}.csv")
                if os.path.exists(p):
                    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                        nm = norm(r.get(pos) or r.get("Player") or "")
                        if nm in ours:
                            val[nm][s] = src_pts(r, pos)
            for nm, d in val.items():
                ac = act.get((w, ours[nm]["player_id"]))
                if ac is None:
                    continue
                for s, v in d.items():
                    others = [x for k, x in d.items() if k != s and k != "OURS"]
                    if len(others) < 4:
                        continue
                    ref = sum(others) / len(others)
                    if ref < 5:
                        continue
                    st = stat[s][pos]; st[3] += 1
                    if abs(v - ref) >= a.gap:
                        gain = abs(ref - ac) - abs(v - ac)
                        st[0] += 1; st[1] += gain > 0; st[2] += gain
                        if s == a.list:
                            listing.append((w, pos, ours[nm]["player"], ref, v, ac, gain))
    nw = len(weeks)
    print(f"weeks {min(weeks)}-{max(weeks)} ({nw}): breaks = {a.gap:g}+ pts from the other sites' average "
          f"(players they average 5+, played)")
    print(f"  {'source':12} " + "  ".join(f"{p:>22}" for p in ("QB", "RB", "WR", "TE", "ALL")))
    print(f"  {'':12} " + "  ".join(f"{'brk/wk right  net/wk':>22}" for _ in range(5)))
    rows = []
    for s, by in stat.items():
        tot = [sum(by[p][i] for p in by) for i in range(4)]
        rows.append((tot[0] / nw, s, by, tot))
    for _, s, by, tot in sorted(rows, reverse=True):
        cells = []
        for st in [by.get(p, [0, 0, 0, 0]) for p in ("QB", "RB", "WR", "TE")] + [tot]:
            cells.append(f"{st[0] / nw:5.1f} {(st[1] / st[0] if st[0] else 0):5.0%} {st[2] / nw:+6.1f}")
        print(f"  {s:12} " + "  ".join(f"{c:>22}" for c in cells))
    for x in sorted(listing, key=lambda x: x[6]):
        print(f"  wk{x[0]:2d} {x[1]:2} {x[2]:24} others {x[3]:5.1f}  {a.list} {x[4]:5.1f}  actual {x[5]:5.1f}  {x[6]:+5.1f}")


if __name__ == "__main__":
    main()
