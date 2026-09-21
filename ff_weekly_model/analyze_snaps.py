#!/usr/bin/env python3
"""Is snap share a better anchor than touch share -- and what to do about
partial games?

Two questions, both raised by real cases:

1. CMC 2026 wk1 split touches 42/58 against Kaelon Black but snaps 55/43 in
   his favour. If snap share is the more stable signal, anchoring on it damps
   exactly that kind of one-week overreaction.

2. A player knocked out in the first quarter posts a tiny snap count and tiny
   touch count. That is an artefact of leaving, not evidence about his role,
   and it should not drag down next week's projection.

Usage:  python analyze_snaps.py
"""

import collections
import csv
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project as P  # noqa: E402

UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")


def pfr_to_gsis():
    out = {}
    with open(os.path.join(UTIL, "players.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("pfr_id") and r.get("gsis_id"):
                out[r["pfr_id"]] = r["gsis_id"]
    return out


def snap_shares(year, xwalk):
    """player -> {week: offense_pct} for skill players."""
    out = collections.defaultdict(dict)
    with open(os.path.join(UTIL, f"snaps_{year}.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("position") not in P.POSITIONS or r.get("game_type") != "REG":
                continue
            g = xwalk.get(r.get("pfr_player_id"))
            pct = r.get("offense_pct")
            if g and pct not in (None, ""):
                out[g][int(r["week"])] = float(pct)
    return out


def autocorr(series):
    """Correlation between consecutive weeks, pooled across players."""
    xs, ys = [], []
    for wks in series.values():
        for w in sorted(wks):
            if w + 1 in wks:
                xs.append(wks[w]); ys.append(wks[w + 1])
    if len(xs) < 30:
        return float("nan"), 0
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return (num / den if den else 0), len(xs)


def main():
    xwalk = pfr_to_gsis()
    snaps = snap_shares(2025, xwalk)
    cur = P.load_players(2025)
    tgt, car, pos, _ = P.shares_by_week(cur)
    print(f"\n  2025 snap data: {len(snaps):,} players joined to gsis_id\n")

    print("  week-to-week stability (correlation of week w with week w+1):")
    for label, series in (("snap share", snaps), ("carry share", car),
                          ("target share", tgt)):
        r, n = autocorr(series)
        print(f"    {label:<15}{r:>7.3f}   (n={n:,})")

    # --- partial games: a week far below the player's own trailing level
    print("\n  partial-game detection (snap pct < 50% of trailing median, 3+ priors)")
    partial = collections.defaultdict(set)
    for pid, wks in snaps.items():
        for w in sorted(wks):
            past = [wks[x] for x in wks if x < w]
            if len(past) >= 3 and st.median(past) > 0.25 and wks[w] < 0.5 * st.median(past):
                partial[pid].add(w)
    total = sum(len(v) for v in partial.values())
    allwk = sum(len(v) for v in snaps.values())
    print(f"    flagged {total:,} of {allwk:,} player-weeks ({total/allwk:.1%})")

    # --- does dropping those weeks improve the next week's carry-share estimate?
    def predict_error(drop_partial):
        errs = []
        for pid, wks in car.items():
            if pos.get(pid) != "RB":
                continue
            for w in sorted(wks):
                past = [wks[x] for x in wks
                        if x < w and not (drop_partial and x in partial.get(pid, ()))]
                if len(past) >= 2:
                    errs.append((sum(past) / len(past) - wks[w]) ** 2)
        return math.sqrt(sum(errs) / len(errs)), len(errs)

    a, n = predict_error(False)
    b, _ = predict_error(True)
    print(f"\n  predicting an RB's next carry share from his trailing average:")
    print(f"    including partial games : {a:.4f}")
    print(f"    excluding partial games : {b:.4f}   ({(a-b)/a*100:+.1f}%)")
    print(f"    (n={n:,})\n")


if __name__ == "__main__":
    main()
