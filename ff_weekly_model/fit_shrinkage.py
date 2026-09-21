#!/usr/bin/env python3
"""Fit the shrinkage constant k for each stat, empirically, from 2025.

The weekly model blends a player's observed usage against a prior:

    estimate = (n * observed_mean + k * prior) / (n + k)

k is "how many games of observed data it takes before you trust the player
over the prior." A stat with k=2 is trustworthy almost immediately; a stat
with k=40 should be regressed hard all season. Guessing k is how projection
models quietly end up chasing three-week noise in October.

So it is fit, not chosen: for each stat, walk every player-week, predict it
from that player's PRIOR weeks blended against the position mean, sweep k
over a grid, and keep the k with the lowest RMSE. That is the same
calculation the model will perform, scored against what actually happened.

Usage:
    python fit_shrinkage.py --year 2025
"""

import argparse
import collections
import csv
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

K_GRID = [0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 30, 40, 55, 75, 100, 150, 250]
MIN_WEEKS = 4          # a player must appear this often to enter the fit
MIN_DENOM = 1          # team-level denominator must be non-zero


def num(v):
    return float(v) if v not in (None, "") else None


def collect_usage(year):
    """player -> pos -> {week: value} for each usage stat."""
    path = os.path.join(DATA, f"nflverse_weekly_{year}_wk1-22.csv")
    stats = ["snaps_pct", "targets_pct", "rush_att_pct", "ez_tgts_pct", "inside5_rush_pct"]
    series = {s: collections.defaultdict(dict) for s in stats}
    pos = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            wk = int(r["week"])
            if wk > 18:
                continue
            pid = r["player_id"]
            pos[pid] = r["pos"]
            for s in stats:
                v = num(r.get(s))
                if v is not None:
                    series[s][pid][wk] = v
    return series, pos


def collect_efficiency(year):
    """Per-week efficiency rates, computed from the actuals file."""
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    series = {"yds_per_target": collections.defaultdict(dict),
              "yds_per_carry": collections.defaultdict(dict),
              "catch_rate": collections.defaultdict(dict)}
    pos = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG" or r["position"] not in ("RB", "WR", "TE"):
                continue
            wk, pid = int(r["week"]), r["player_id"]
            pos[pid] = r["position"]
            tgt, car = num(r["targets"]) or 0, num(r["carries"]) or 0
            if tgt >= 2:
                series["yds_per_target"][pid][wk] = (num(r["receiving_yards"]) or 0) / tgt
                series["catch_rate"][pid][wk] = (num(r["receptions"]) or 0) / tgt
            if car >= 3:
                series["yds_per_carry"][pid][wk] = (num(r["rushing_yards"]) or 0) / car
    return series, pos


def collect_team(year):
    """Team-level series keyed by team instead of player."""
    path = os.path.join(DATA, f"team_weekly_{year}.csv")
    series = {"pass_rate": collections.defaultdict(dict),
              "qb_rush_share": collections.defaultdict(dict),
              "plays": collections.defaultdict(dict)}
    grp = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            wk, tm = int(r["week"]), r["team"]
            grp[tm] = "TEAM"
            for s in series:
                series[s][tm][wk] = float(r[s])
    return series, grp


def fit(series, group, label):
    """Sweep k; return (best_k, rmse_at_best, rmse_k0, rmse_prior_only, n)."""
    entities = {e: wks for e, wks in series.items() if len(wks) >= MIN_WEEKS}
    if not entities:
        return None

    # Prior = group (position) mean over every observation.
    bucket = collections.defaultdict(list)
    for e, wks in entities.items():
        bucket[group.get(e, "?")].extend(wks.values())
    prior = {g: sum(v) / len(v) for g, v in bucket.items() if v}

    # Build (n, observed_mean, prior, actual) once; reuse across the k sweep.
    samples = []
    for e, wks in entities.items():
        p = prior.get(group.get(e, "?"))
        if p is None:
            continue
        for wk in sorted(wks):
            past = [v for w, v in wks.items() if w < wk]
            if not past:
                continue
            samples.append((len(past), sum(past) / len(past), p, wks[wk]))
    if not samples:
        return None

    def rmse(k):
        tot = 0.0
        for n, obs, p, actual in samples:
            pred = (n * obs + k * p) / (n + k)
            tot += (pred - actual) ** 2
        return math.sqrt(tot / len(samples))

    scored = [(rmse(k), k) for k in K_GRID]
    best_rmse, best_k = min(scored)
    prior_only = math.sqrt(sum((p - a) ** 2 for _, _, p, a in samples) / len(samples))
    return best_k, best_rmse, rmse(0), prior_only, len(samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    blocks = []
    u, upos = collect_usage(args.year); blocks.append(("usage", u, upos))
    e, epos = collect_efficiency(args.year); blocks.append(("efficiency", e, epos))
    t, tgrp = collect_team(args.year); blocks.append(("team", t, tgrp))

    print(f"\n  shrinkage constants fit on {args.year} (regular season)\n")
    print(f"  {'stat':<22}{'k':>6}{'RMSE':>9}{'no shrink':>11}{'prior only':>12}{'gain':>8}{'n':>8}")
    print("  " + "-" * 76)
    out = []
    for name, series, group in blocks:
        for stat in series:
            res = fit(series[stat], group, stat)
            if not res:
                continue
            k, r, r0, rp, n = res
            gain = (r0 - r) / r0 * 100
            print(f"  {stat:<22}{k:>6}{r:>9.3f}{r0:>11.3f}{rp:>12.3f}{gain:>7.1f}%{n:>8,}")
            out.append({"stat": stat, "group": name, "k": k, "rmse": round(r, 4),
                        "rmse_no_shrink": round(r0, 4), "rmse_prior_only": round(rp, 4),
                        "samples": n})

    dest = os.path.join(DATA, f"shrinkage_{args.year}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"\n  -> {os.path.basename(dest)}\n")


if __name__ == "__main__":
    main()
