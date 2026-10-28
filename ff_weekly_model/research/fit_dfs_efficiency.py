#!/usr/bin/env python3
"""Fit the DFS variant's efficiency shrinkage, on TWO metrics at once.

The ranking model and the DFS model want different things and the same knob
moves them in opposite directions:

  RMSE         rewards compression. Shrinking everyone toward the mean always
               lowers squared error when you are uncertain, which is why the
               position-mean model scores well and reads flat.
  CALIBRATION  is what DFS needs -- a projected 18 has to mean 18, because the
               number is used on its own rather than as a sort key.

So this reports both, plus the bias on the elite tier specifically, and leaves
the trade-off visible instead of collapsing it to one number.

Usage:
    python fit_dfs_efficiency.py --year 2025
"""

import argparse
import collections
import math
import statistics as st
import sys
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # research/ -> ff_weekly_model
sys.path.insert(0, HERE)
import project as P  # noqa: E402


def build_inputs(year):
    cur, prev = P.load_players(year), P.load_players(year - 1)
    tc, tp = P.load_teams(year), P.load_teams(year - 1)
    gc, gp = P.load_games(year), P.load_games(year - 1)
    chart = P.load_depth_chart(year)
    cut = P.week_cutoffs(year)
    tg, ca, pos, tm_c = P.shares_by_week(cur)
    tg2, ca2, _, tm_p = P.shares_by_week(prev)
    P.fill_observed_zeros(tg, ca, pos, year)
    for r in cur + prev:
        if r["position"] == "QB":
            pos.setdefault(r["player_id"], "QB")
    eff = P.efficiency_means(prev)
    lg = P.league_constants(tp, prev)
    i2t = P.fit_implied_to_td(tp, gp)
    tpa = (sum(P.num(r["targets"]) for r in prev if r["position"] in P.POSITIONS)
           / sum(int(t["pass_att"]) for t in tp.values()))
    pri = P.build_priors(tg, ca, tg2, ca2, pos, tm_c, tm_p, chart)
    qpa, qra = P.qb_shares_by_week(cur, tc)
    qeff = P.qb_efficiency_means(prev)
    tqr = {}
    for (t, w), r in tp.items():
        tqr.setdefault(t, []).append(float(r["qb_rush_share"]))
    tqr = {t: sum(v) / len(v) for t, v in tqr.items()}
    byw = collections.defaultdict(list)
    for r in cur:
        if r["position"] in P.ALL_POSITIONS:
            byw[int(r["week"])].append(r)
    peff = P.player_eff_by_week(cur, prev)
    return dict(cur=cur, tc=tc, gc=gc, tg=tg, ca=ca, pos=pos, pri=pri, eff=eff,
                lg=lg, i2t=i2t, tpa=tpa, qpa=qpa, qra=qra, qeff=qeff, tqr=tqr,
                byw=byw, cut=cut, peff=peff, year=year)


def run(inp, player_eff):
    """-> list of (projected, actual, form-coming-in, position)."""
    hist = collections.defaultdict(list)
    out = []
    for w in range(2, 19):
        active = {r["player_id"]: r["team"] for r in inp["byw"][w]}
        proj = P.project_week(
            w, teams_cur=inp["tc"], games=inp["gc"], tgt_cur=inp["tg"],
            car_cur=inp["ca"], pos=inp["pos"], priors=inp["pri"], eff=inp["eff"],
            lg=inp["lg"], imp_to_td=inp["i2t"], tgt_per_att=inp["tpa"],
            active=active, qb_patt=inp["qpa"], qb_ratt=inp["qra"],
            qb_eff=inp["qeff"], qb_games=P.team_games(inp["tc"], w),
            team_qbr_prev=inp["tqr"],
            qb_rank=P.qb_ranks_as_of(inp["year"], inp["cut"].get(w, "9999")),
            player_eff=player_eff)
        for r in inp["byw"][w]:
            pid = r["player_id"]
            if pid in proj:
                h = hist[pid]
                out.append((P.points(proj[pid], r["position"]),
                            P.actual_points(r),
                            st.mean(h) if len(h) >= 3 else None,
                            r["position"]))
        for r in inp["byw"][w]:
            hist[r["player_id"]].append(P.actual_points(r))
    return out


def score(pairs):
    rmse = math.sqrt(sum((a - b) ** 2 for a, b, _, _ in pairs) / len(pairs))
    x = [a for a, _, _, _ in pairs]
    y = [b for _, b, _, _ in pairs]
    mx, my = st.mean(x), st.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    var = sum((a - mx) ** 2 for a in x)
    slope = cov / var if var else float("nan")
    def eb(sel):
        e = [(a, b) for a, b, f, po in pairs
             if f is not None and f >= 15 and sel(po)]
        return (st.mean([b - a for a, b in e]) if e else float("nan")), len(e)
    bias, n = eb(lambda po: True)
    skill, ns = eb(lambda po: po != "QB")
    qb, nq = eb(lambda po: po == "QB")
    return rmse, slope, bias, skill, qb, (n, ns, nq)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    args = ap.parse_args()
    inp = build_inputs(args.year)

    print(f"\n  fitting on {args.year}. lower RMSE is better; slope should be 1.00;")
    print("  elite bias is how far UNDER we are on in-form players (0 is right).\n")
    print(f"  {'setting':<24}{'RMSE':>8}{'slope':>8}{'all':>9}{'skill':>9}{'QB':>9}")

    base = run(inp, None)
    r, sl, bi, sk, qb, ns = score(base)
    print(f"  {'position means (now)':<24}{r:>8.3f}{sl:>8.3f}"
          f"{bi:>+8.2f}p{sk:>+8.2f}p{qb:>+8.2f}p")
    print("  " + "-" * 53)

    best = None
    for kt, kc in [(10, 15), (20, 30), (40, 60), (80, 120), (160, 240), (320, 480)]:
        P.K_EFF_TGT, P.K_EFF_CAR = float(kt), float(kc)
        r, sl, bi, sk, qb, ns = score(run(inp, inp["peff"]))
        if best is None or abs(sk) < abs(best[0]):
            best = (sk, kt, kc, r, sl)
        print(f"  {f'own eff, k={kt}/{kc}':<24}{r:>8.3f}{sl:>8.3f}"
              f"{bi:>+8.2f}p{sk:>+8.2f}p{qb:>+8.2f}p")
    print(f"\n  elite n: all {ns[0]}, skill {ns[1]}, QB {ns[2]}")
    print(f"  best SKILL calibration at k={best[1]}/{best[2]}: "
          f"{best[0]:+.2f}p, RMSE {best[3]:.3f}, slope {best[4]:.3f}\n")


if __name__ == "__main__":
    main()
