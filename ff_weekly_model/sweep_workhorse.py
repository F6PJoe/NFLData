#!/usr/bin/env python3
"""Does a stubborn prior help the players it should -- established workhorses,
early in the season?

The aggregate sweeps said no, but they average weeks 2-18 and every player.
By week 8 the current season dominates whatever k is, and most players have no
prior worth defending. The CMC case is narrow: heavy, CONSISTENT history, first
few weeks. This slices to exactly that.

Usage:  python sweep_workhorse.py
"""

import collections
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project as P  # noqa: E402


def main():
    cur_rows, prev_rows = P.load_players(2025), P.load_players(2024)
    teams_cur, teams_prev = P.load_teams(2025), P.load_teams(2024)
    games_cur, games_prev = P.load_games(2025), P.load_games(2024)
    chart = P.load_depth_chart(2025)
    tgt_cur, car_cur, pos, team_cur = P.shares_by_week(cur_rows)
    tgt_prev, car_prev, _, team_prev = P.shares_by_week(prev_rows)
    eff = P.efficiency_means(prev_rows)
    lg = P.league_constants(teams_prev, prev_rows)
    imp_to_td = P.fit_implied_to_td(teams_prev, games_prev)
    tgt_per_att = (sum(P.num(r["targets"]) for r in prev_rows
                       if r["position"] in P.POSITIONS)
                   / sum(int(t["pass_att"]) for t in teams_prev.values()))
    priors = P.build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos,
                            team_cur, team_prev, chart)

    # "workhorse": RB, >=10 prior games, prior carry share >=40%, and CONSISTENT
    work = set()
    for pid, wks in car_prev.items():
        if pos.get(pid) != "RB" or len(wks) < 10:
            continue
        v = list(wks.values())
        if st.mean(v) >= 0.40 and st.pstdev(v) <= 0.18:
            work.add(pid)
    print(f"\n  workhorse RBs identified from 2024: {len(work)}")

    by_week = collections.defaultdict(list)
    for r in cur_rows:
        if r["position"] in P.POSITIONS:
            by_week[int(r["week"])].append(r)

    buckets = {"wk 2-5": range(2, 6), "wk 6-9": range(6, 10), "wk 10-18": range(10, 19)}
    print(f"\n  RMSE for those players only\n")
    print(f"  {'per-game k':>11}" + "".join(f"{b:>11}" for b in buckets))
    rows = []
    for w in (0.0, 0.1, 0.25, 0.5, 1.0, 2.0):
        P.PRIOR_GAME_WEIGHT = w
        err = collections.defaultdict(list)
        for wk in range(2, 19):
            active = {r["player_id"]: r["team"] for r in by_week[wk]}
            proj = P.project_week(wk, teams_cur=teams_cur, games=games_cur,
                                  tgt_cur=tgt_cur, car_cur=car_cur, pos=pos,
                                  priors=priors, eff=eff, lg=lg, imp_to_td=imp_to_td,
                                  tgt_per_att=tgt_per_att, active=active)
            for r in by_week[wk]:
                pid = r["player_id"]
                if pid in proj and pid in work:
                    e = (P.points(proj[pid]) - P.actual_points(r)) ** 2
                    for b, rng in buckets.items():
                        if wk in rng:
                            err[b].append(e)
        line = {b: math.sqrt(sum(v) / len(v)) if v else float("nan")
                for b, v in err.items()}
        rows.append((w, line))
        print(f"  {w:>11.2f}" + "".join(f"{line[b]:>11.3f}" for b in buckets))
    for b in buckets:
        best = min(rows, key=lambda r: r[1][b])
        print(f"\n  {b}: best k-per-game = {best[0]:.2f}  (RMSE {best[1][b]:.3f}, "
              f"vs {rows[0][1][b]:.3f} at 0)")
    P.PRIOR_GAME_WEIGHT = 0.0


if __name__ == "__main__":
    main()
