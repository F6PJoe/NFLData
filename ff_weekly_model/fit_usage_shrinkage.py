#!/usr/bin/env python3
"""Fit shrinkage for the VOLUME stats, using last season as the prior.

The first pass (fit_shrinkage.py) used a position average as the prior, which
is fine for efficiency -- players really do cluster around the position mean --
but meaningless for usage, where a WR1 and a WR5 share a position and nothing
else. So the usage constants it produced were not measuring usage; they were
measuring a bad prior.

This refits them against the prior the live model would actually use: the
player's OWN share from last season. It also splits the result three ways,
which answers the question directly --

    same team    : played 2024 and 2025 for the same club
    changed team : played both years, different club
    no history   : rookies and anyone without a 2024 baseline

-- so "how much is last year's usage worth when a guy switches teams, and what
do you do about rookies" stops being a judgment call and becomes a number.

Everything joins on nflverse player_id, so there is no name matching anywhere.

Usage:
    python fit_usage_shrinkage.py --prior-year 2024 --year 2025
"""

import argparse
import collections
import csv
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

K_GRID = [0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 30, 40, 55, 75, 100]
MIN_PRIOR_WEEKS = 4
MIN_WEEKS = 4
POSITIONS = ("RB", "WR", "TE")


def num(v):
    return float(v) if v not in (None, "") else 0.0


def weekly_shares(year):
    """player -> {week: (target_share, carry_share)}, plus position and modal team."""
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r.get("season_type") == "REG" and r["position"] in POSITIONS]

    team_tot = collections.defaultdict(lambda: [0.0, 0.0])   # (team, wk) -> [tgts, carries]
    for r in rows:
        t = team_tot[(r["team"], int(r["week"]))]
        t[0] += num(r["targets"]); t[1] += num(r["carries"])

    tgt = collections.defaultdict(dict)
    car = collections.defaultdict(dict)
    pos, teams = {}, collections.defaultdict(collections.Counter)
    for r in rows:
        pid, wk = r["player_id"], int(r["week"])
        pos[pid] = r["position"]
        teams[pid][r["team"]] += 1
        tt, tc = team_tot[(r["team"], wk)]
        if tt:
            tgt[pid][wk] = num(r["targets"]) / tt * 100
        if tc:
            car[pid][wk] = num(r["carries"]) / tc * 100
    modal = {p: c.most_common(1)[0][0] for p, c in teams.items()}
    return {"targets_pct": tgt, "rush_att_pct": car}, pos, modal


def rmse(samples, k):
    tot = 0.0
    for n, obs, prior, actual in samples:
        pred = (n * obs + k * prior) / (n + k) if (n + k) else prior
        tot += (pred - actual) ** 2
    return math.sqrt(tot / len(samples)) if samples else float("nan")


def best_k(samples):
    scored = [(rmse(samples, k), k) for k in K_GRID]
    r, k = min(scored)
    return k, r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--prior-year", type=int, default=2024)
    args = ap.parse_args()

    cur, pos, team_now = weekly_shares(args.year)
    old, _, team_before = weekly_shares(args.prior_year)

    print(f"\n  usage shrinkage: {args.year} weeks predicted from a "
          f"{args.prior_year} prior\n")

    out = []
    for stat in ("targets_pct", "rush_att_pct"):
        series, prev = cur[stat], old[stat]

        # position mean, the fallback prior for anyone with no history
        bypos = collections.defaultdict(list)
        for pid, wks in series.items():
            bypos[pos[pid]].extend(wks.values())
        posmean = {p: sum(v) / len(v) for p, v in bypos.items() if v}

        groups = collections.defaultdict(list)
        for pid, wks in series.items():
            if len(wks) < MIN_WEEKS:
                continue
            hist = prev.get(pid, {})
            if len(hist) >= MIN_PRIOR_WEEKS:
                prior = sum(hist.values()) / len(hist)
                g = ("same team" if team_before.get(pid) == team_now.get(pid)
                     else "changed team")
            else:
                prior = posmean.get(pos[pid])
                g = "no history"
            if prior is None:
                continue
            for wk in sorted(wks):
                past = [v for w, v in wks.items() if w < wk]
                if not past:
                    continue
                groups[g].append((len(past), sum(past) / len(past), prior, wks[wk]))

        allsamp = [s for v in groups.values() for s in v]
        k, r = best_k(allsamp)
        print(f"  {stat}   overall k = {k}   RMSE {r:.3f}   "
              f"(no shrink {rmse(allsamp, 0):.3f})")
        print(f"    {'group':<15}{'n':>8}{'k':>6}{'RMSE':>9}{'prior only':>12}{'vs no shrink':>14}")
        for g in ("same team", "changed team", "no history"):
            s = groups.get(g)
            if not s:
                continue
            gk, gr = best_k(s)
            po = math.sqrt(sum((p - a) ** 2 for _, _, p, a in s) / len(s))
            r0 = rmse(s, 0)
            print(f"    {g:<15}{len(s):>8,}{gk:>6}{gr:>9.3f}{po:>12.3f}"
                  f"{(r0 - gr) / r0 * 100:>13.1f}%")
            out.append({"stat": stat, "group": g, "k": gk, "rmse": round(gr, 4),
                        "rmse_prior_only": round(po, 4),
                        "rmse_no_shrink": round(r0, 4), "samples": len(s)})
        print()

    dest = os.path.join(DATA, f"usage_shrinkage_{args.year}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"  -> {os.path.basename(dest)}\n")


if __name__ == "__main__":
    main()
