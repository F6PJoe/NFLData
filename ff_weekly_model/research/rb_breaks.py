"""RB weeks where we were 2+/3+ points ABOVE the other sites' average: which piece put us there?

Joe 2026-11-17 (oddity_rate.py: 16 of our 35 breaks were RBs we had too high, net -12 pts).
For each break: carries, yards/carry, rush TD, targets, receiving yards, rec TD -- ours / the other
sites' average / actual, and the points each piece adds to our gap over the field.

    python research/rb_breaks.py --year 2026 --weeks 3-10 [--gap 3]
"""
import argparse, collections, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoreboard_vs_sources import DATA, W, SOURCES, f, src_pts, actual_pts, norm

INDIV = [s for s in SOURCES if s != "consensus"]
KEYS = ("car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026); ap.add_argument("--weeks", default="3-10")
    ap.add_argument("--gap", type=float, default=3.0)
    a = ap.parse_args()
    w0, w1 = (int(x) for x in a.weeks.split("-"))
    act = {}
    for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r.get("season_type", "REG") == "REG" and w0 <= int(r["week"]) <= w1:
            act[(int(r["week"]), r["player_id"])] = (actual_pts(r), {
                "car": f(r, "carries"), "ryd": f(r, "rushing_yards"), "rtd": f(r, "rushing_tds"),
                "tgt": f(r, "targets"), "rec": f(r, "receptions"), "cyd": f(r, "receiving_yards"),
                "ctd": f(r, "receiving_tds")})
    br = []
    for w in range(w0, w1 + 1):
        fp = os.path.join(DATA, f"projections_{a.year}_wk{w:02d}_final.csv")
        if not os.path.exists(fp):
            continue
        ours = {norm(r["player"]): r for r in csv.DictReader(open(fp, encoding="utf-8-sig")) if r["pos"] == "RB"}
        oth = collections.defaultdict(list)
        for s in INDIV:
            p = os.path.join(W, f"{a.year}-wk{w:02d}", f"{s}_rb.csv")
            if os.path.exists(p):
                for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                    nm = norm(r.get("RB") or r.get("Player") or "")
                    if nm in ours:
                        oth[nm].append((src_pts(r, "RB"), {"car": f(r, "Rush Att"), "ryd": f(r, "Rush Yds"),
                                       "rtd": f(r, "Rush TD"), "tgt": f(r, "Targets"), "rec": f(r, "Rec"),
                                       "cyd": f(r, "Rec Yds"), "ctd": f(r, "Rec TD")}))
        for nm, l in oth.items():
            if len(l) < 4:
                continue
            o = ours[nm]
            ac = act.get((w, o["player_id"]))
            if ac is None:
                continue
            ref = sum(x[0] for x in l) / len(l)
            op = f(o, "half_ppr")
            if ref < 5 or op - ref < a.gap:
                continue
            rc = {k: sum(x[1][k] for x in l) / len(l) for k in KEYS}
            oc = {"car": f(o, "rush_att"), "ryd": f(o, "rush_yds"), "rtd": f(o, "rush_td"), "tgt": f(o, "targets"),
                  "rec": f(o, "rec"), "cyd": f(o, "rec_yds"), "ctd": f(o, "rec_td")}
            br.append((w, o["player"], o["team"], op, ref, ac[0], oc, rc, ac[1]))
    pv = lambda d: (d["ryd"] * .1 + d["rtd"] * 6, d["rec"] * .5 + d["cyd"] * .1 + d["ctd"] * 6)
    print(f"RB weeks {w0}-{w1} where we were {a.gap:g}+ pts over the other sites' average: {len(br)}")
    print(f"{'':30} {'pts ours/oth/act':>18} | {'carries':>16} {'ypc':>15} {'rush TD':>15} | {'targets':>15} {'rec pts':>15}")
    tot = collections.defaultdict(float)
    for w, nm, tm, op, ref, ap_, oc, rc, ac in sorted(br, key=lambda x: x[3] - x[4] - abs(x[3] - x[5]) + abs(x[4] - x[5])):
        ypc = lambda d: d["ryd"] / d["car"] if d["car"] else 0
        recp = lambda d: d["rec"] * .5 + d["cyd"] * .1 + d["ctd"] * 6
        # our gap over the field, split: carries (at the field's ypc / TD rate), ypc, TD rate, receiving
        g_car = (oc["car"] - rc["car"]) * (ypc(rc) * .1 + (rc["rtd"] / rc["car"] if rc["car"] else 0) * 6)
        g_ypc = (ypc(oc) - ypc(rc)) * oc["car"] * .1
        g_td = (oc["rtd"] - rc["rtd"]) * 6 - (oc["car"] - rc["car"]) * (rc["rtd"] / rc["car"] if rc["car"] else 0) * 6
        g_rec = recp(oc) - recp(rc)
        for k, v in (("carries", g_car), ("ypc", g_ypc), ("rush TD", g_td), ("receiving", g_rec)):
            tot[k] += v
        print(f"wk{w:2d} {nm:20} {tm:4} {op:5.1f}/{ref:5.1f}/{ap_:5.1f} | {oc['car']:4.1f}/{rc['car']:4.1f}/{ac['car']:4.0f}"
              f"  {ypc(oc):3.1f}/{ypc(rc):3.1f}/{ypc(ac):3.1f}  {oc['rtd']:.2f}/{rc['rtd']:.2f}/{ac['rtd']:.0f}"
              f" | {oc['tgt']:3.1f}/{rc['tgt']:3.1f}/{ac['tgt']:2.0f}  {recp(oc):4.1f}/{recp(rc):4.1f}/{recp(ac):4.1f}"
              f" | gap: car {g_car:+.1f} ypc {g_ypc:+.1f} td {g_td:+.1f} rec {g_rec:+.1f}")
    n = len(br) or 1
    print("\naverage gap over the field from: " + "  ".join(f"{k} {v / n:+.2f}" for k, v in tot.items()))
    m = lambda i, k: sum(x[i][k] for x in br) / n
    print(f"carries ours {m(6,'car'):.1f} field {m(7,'car'):.1f} actual {m(8,'car'):.1f} | "
          f"rush TD {m(6,'rtd'):.2f} / {m(7,'rtd'):.2f} / {m(8,'rtd'):.2f} | targets {m(6,'tgt'):.1f} / {m(7,'tgt'):.1f} / {m(8,'tgt'):.1f}")
    print(f"points ours {sum(x[3] for x in br)/n:.1f} field {sum(x[4] for x in br)/n:.1f} actual {sum(x[5] for x in br)/n:.1f}")


if __name__ == "__main__":
    main()
