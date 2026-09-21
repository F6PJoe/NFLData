#!/usr/bin/env python3
"""How much should the depth chart pull the prior for players who HAVE history?

The chart knows things last season's usage cannot. A back listed 5th is not
getting last year's carries wherever he earned them, and Arizona's 2026 week 1
(Allgeier 17 carries, Love 11, ranks 2 and 1; nothing for ranks 3-5) is the
case in point. Sweeps depth_weight and scores each on the 2025 backtest.

Usage:  python sweep_depth_weight.py
"""

import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project as P  # noqa: E402


def main():
    year, prev_year = 2025, 2024
    cur_rows, prev_rows = P.load_players(year), P.load_players(prev_year)
    teams_cur, teams_prev = P.load_teams(year), P.load_teams(prev_year)
    games_cur, games_prev = P.load_games(year), P.load_games(prev_year)
    chart = P.load_depth_chart(year)
    tgt_cur, car_cur, pos, team_cur = P.shares_by_week(cur_rows)
    tgt_prev, car_prev, _, team_prev = P.shares_by_week(prev_rows)
    eff = P.efficiency_means(prev_rows)
    lg = P.league_constants(teams_prev, prev_rows)
    imp_to_td = P.fit_implied_to_td(teams_prev, games_prev)
    tgt_per_att = (sum(P.num(r["targets"]) for r in prev_rows
                       if r["position"] in P.POSITIONS)
                   / sum(int(t["pass_att"]) for t in teams_prev.values()))

    by_week = collections.defaultdict(list)
    for r in cur_rows:
        if r["position"] in P.POSITIONS:
            by_week[int(r["week"])].append(r)

    print(f"\n  depth_weight sweep -- 2025 walk-forward, half-PPR RMSE\n")
    print(f"  {'weight':>8}{'ALL':>9}{'RB':>9}{'WR':>9}{'TE':>9}")
    best = None
    for w in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
        priors = P.build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos,
                                team_cur, team_prev, chart, depth_weight=w)
        err = collections.defaultdict(list)
        for wk in range(2, 19):
            active = {r["player_id"]: r["team"] for r in by_week[wk]}
            proj = P.project_week(wk, teams_cur=teams_cur, games=games_cur,
                                  tgt_cur=tgt_cur, car_cur=car_cur, pos=pos,
                                  priors=priors, eff=eff, lg=lg, imp_to_td=imp_to_td,
                                  tgt_per_att=tgt_per_att, active=active)
            for r in by_week[wk]:
                if r["player_id"] in proj:
                    e = (P.points(proj[r["player_id"]]) - P.actual_points(r)) ** 2
                    err[r["position"]].append(e); err["ALL"].append(e)
        rm = {k: math.sqrt(sum(v) / len(v)) for k, v in err.items()}
        flag = ""
        if best is None or rm["ALL"] < best[1]:
            best = (w, rm["ALL"]); flag = "  <-"
        print(f"  {w:>8.2f}{rm['ALL']:>9.3f}{rm['RB']:>9.3f}{rm['WR']:>9.3f}"
              f"{rm['TE']:>9.3f}{flag}")
    print(f"\n  best depth_weight = {best[0]:.2f}  (RMSE {best[1]:.3f})\n")


if __name__ == "__main__":
    main()
