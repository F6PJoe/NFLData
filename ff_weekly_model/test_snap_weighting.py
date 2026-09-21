#!/usr/bin/env python3
"""Should a partly-played week count as much as a full one?

A back knocked out in the first quarter posts a tiny carry share. Counting
that week in full says his role shrank; dropping it says the week never
happened. Neither is right -- he played a twelfth of a game, so it is a
twelfth of the evidence.

Three ways to use the history, scored on predicting the next week's share:

  equal-weighted   every week counts the same          (what the model does now)
  snap-weighted    each week counts by snaps played
  per-snap rate    touches per snap, x projected snaps -- a Q1 exit leaves the
                   RATE untouched and only the total small

Usage:  python test_snap_weighting.py
"""

import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project as P          # noqa: E402
import analyze_snaps as A    # noqa: E402


def main():
    xw = A.pfr_to_gsis()
    snaps = A.snap_shares(2025, xw)          # player -> {week: offense_pct}
    cur = P.load_players(2025)
    tgt, car, pos, _ = P.shares_by_week(cur)

    # carry share EARNED PER UNIT OF PLAYING TIME -- stays in share units, so a
    # Q1 exit leaves this untouched and only depresses the raw share.
    touches = collections.defaultdict(dict)
    for pid, wks in car.items():
        for wk, share in wks.items():
            sp = snaps.get(pid, {}).get(wk)
            if sp and sp > 0.05:
                touches[pid][wk] = share / sp

    def score(kind, series, minweeks=3):
        errs = []
        for pid, wks in series.items():
            if pos.get(pid) != "RB":
                continue
            sn = snaps.get(pid, {})
            for w in sorted(wks):
                past = [x for x in sorted(wks) if x < w]
                past = [x for x in past if x in sn]
                if len(past) < minweeks or w not in sn or sn[w] <= 0:
                    continue
                if kind == "equal":
                    pred = sum(wks[x] for x in past) / len(past)
                elif kind == "snapw":
                    den = sum(sn[x] for x in past)
                    if not den:
                        continue
                    pred = sum(wks[x] * sn[x] for x in past) / den
                else:   # per-snap rate x this week's snap share
                    rate = sum(touches[pid][x] for x in past
                               if x in touches.get(pid, {}))
                    n = sum(1 for x in past if x in touches.get(pid, {}))
                    if not n:
                        continue
                    pred = (rate / n) * sn[w]
                errs.append((pred - wks[w]) ** 2)
        return math.sqrt(sum(errs) / len(errs)), len(errs)

    print("\n  predicting an RB's carry share from his history\n")
    print(f"  {'method':<18}{'RMSE':>9}{'n':>8}")
    base = None
    for kind, label in (("equal", "equal-weighted"), ("snapw", "snap-weighted"),
                        ("rate", "per-snap rate")):
        r, n = score(kind, car)
        if base is None:
            base = r
        print(f"  {label:<18}{r:>9.4f}{n:>8,}   {(base-r)/base*100:+.1f}%")

    # restricted to the weeks right after a low-snap game -- the case in question
    print("\n  same, but only weeks FOLLOWING a game under 40% snaps\n")
    def score_after_partial(kind):
        errs = []
        for pid, wks in car.items():
            if pos.get(pid) != "RB":
                continue
            sn = snaps.get(pid, {})
            for w in sorted(wks):
                prev = w - 1
                if prev not in sn or sn[prev] >= 0.40:
                    continue
                past = [x for x in sorted(wks) if x < w and x in sn]
                if len(past) < 3 or w not in sn or sn[w] <= 0:
                    continue
                if kind == "equal":
                    pred = sum(wks[x] for x in past) / len(past)
                elif kind == "snapw":
                    den = sum(sn[x] for x in past)
                    pred = sum(wks[x] * sn[x] for x in past) / den if den else 0
                else:
                    vals = [touches[pid][x] for x in past if x in touches.get(pid, {})]
                    if not vals:
                        continue
                    pred = (sum(vals) / len(vals)) * sn[w]
                errs.append((pred - wks[w]) ** 2)
        return math.sqrt(sum(errs) / len(errs)), len(errs)
    base2 = None
    for kind, label in (("equal", "equal-weighted"), ("snapw", "snap-weighted"),
                        ("rate", "per-snap rate")):
        r, n = score_after_partial(kind)
        if base2 is None:
            base2 = r
        print(f"  {label:<18}{r:>9.4f}{n:>8,}   {(base2-r)/base2*100:+.1f}%")
    print()


if __name__ == "__main__":
    main()
