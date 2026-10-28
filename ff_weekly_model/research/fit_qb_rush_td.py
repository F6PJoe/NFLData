#!/usr/bin/env python3
"""Fit the per-QB rushing-TD rate: how much history, and how hard to shrink it.

The question is not whether the rate is player-specific -- it plainly is, with
Allen at 0.118/0.125 per carry across two seasons against Goff's 0.000/0.000
and a 0.052 league mean. The question is whether we can tell a real one from a
fluke in advance, because off a SINGLE prior season we could not: personalising
over-projected the high-rate group by +2.07 points a game even while it fixed
Allen.

So this sweeps two things together:

  decay  how fast older seasons lose weight (1.0 = all seasons equal)
  k      shrinkage toward the league rate, in CARRIES -- which is what makes a
         multi-year runner keep his own rate while a one-year spike gets only
         a partial nudge

Reported per group (high / mid / low prior rate) so a gain on the average
cannot hide a blow-up at the extremes, which is exactly how the single-season
version looked acceptable at first.

Usage:
    python fit_qb_rush_td.py --year 2025
"""

import argparse
import collections
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # research/ -> ff_weekly_model
sys.path.insert(0, HERE)
import project as P  # noqa: E402
import fit_dfs_efficiency as F  # noqa: E402

LEAGUE_FALLBACK = 0.052


def groups(prior_seasons, decay):
    """QB -> high/mid/low, from weighted prior history only (no lookahead)."""
    acc = collections.defaultdict(lambda: [0.0, 0.0])
    for back, src in enumerate(reversed(prior_seasons)):
        w = decay ** back
        for r in src:
            if r["position"] == "QB":
                a = acc[r["player_id"]]
                a[0] += P.num(r["carries"]) * w
                a[1] += P.num(r["rushing_tds"]) * w
    out = {}
    for pid, (c, t) in acc.items():
        if c < 30:
            continue
        rate = t / c
        out[pid] = ("high" if rate > LEAGUE_FALLBACK * 1.5
                    else "low" if rate < LEAGUE_FALLBACK * 0.5 else "mid")
    return out


def evaluate(inp, qb_rush, grp):
    out = collections.defaultdict(list)
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
            qb_rush=qb_rush)
        for r in inp["byw"][w]:
            pid = r["player_id"]
            if (pid in proj and r["position"] == "QB"
                    and P.num(r["attempts"]) >= 15):
                g = grp.get(pid)
                if g:
                    out[g].append((P.points(proj[pid], "QB"), P.actual_points(r)))
    return out


def summarise(by_group):
    rows = {}
    allv = []
    for g, v in by_group.items():
        allv += v
        rows[g] = (math.sqrt(sum((a - b) ** 2 for a, b in v) / len(v)),
                   st.mean([a - b for a, b in v]), len(v))
    rows["ALL"] = (math.sqrt(sum((a - b) ** 2 for a, b in allv) / len(allv)),
                   st.mean([a - b for a, b in allv]), len(allv))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--history", type=int, default=4,
                    help="how many prior seasons to read")
    args = ap.parse_args()

    inp = F.build_inputs(args.year)
    seasons = []
    for yr in range(args.year - args.history, args.year):
        try:
            seasons.append(P.load_players(yr))
        except FileNotFoundError:
            print(f"  (no data for {yr}, skipping)")
    print(f"\n  target {args.year}, history "
          f"{args.year - len(seasons)}-{args.year - 1} ({len(seasons)} seasons)")
    print("  bias = projected minus actual; positive means we OVER-project\n")

    grp = groups(seasons, 1.0)
    counts = collections.Counter(grp.values())
    print(f"  QBs by prior rushing-TD rate: {dict(counts)}\n")

    base = summarise(evaluate(inp, None, grp))
    hdr = f"  {'setting':<22}"
    for g in ("ALL", "high", "mid", "low"):
        hdr += f"{g:>16}"
    print(hdr)
    print(f"  {'':<22}" + "".join(f"{'RMSE   bias':>16}" for _ in range(4)))

    def line(label, rows):
        s = f"  {label:<22}"
        for g in ("ALL", "high", "mid", "low"):
            if g in rows:
                r, b, _ = rows[g]
                s += f"{r:>8.2f}{b:>+8.2f}"
            else:
                s += f"{'-':>16}"
        print(s)

    line("league rate (now)", base)
    print("  " + "-" * 86)

    best = None
    for decay in (0.6, 0.75, 1.0):
        for k in (25, 60, 120, 250):
            qb_rush = P.qb_rush_hist(inp["cur"], seasons, decay)
            P.K_QB_RUSH_TD = float(k)
            rows = summarise(evaluate(inp, qb_rush, grp))
            line(f"decay {decay}, k={k}", rows)
            worst = max(abs(rows[g][1]) for g in ("high", "mid", "low") if g in rows)
            if best is None or worst < best[0]:
                best = (worst, decay, k, rows["ALL"])
    print(f"\n  best (smallest worst-group bias): decay {best[1]}, k={best[2]}")
    print(f"  -> overall RMSE {best[3][0]:.3f}, bias {best[3][1]:+.2f}, "
          f"worst group {best[0]:.2f}\n")


if __name__ == "__main__":
    main()
