#!/usr/bin/env python3
"""Audit our projections against the ff_weekly_proj consensus -- and, where the
week has been played, against what actually happened.

The consensus is a BENCHMARK, never an input (see the project notes). Two uses:

  sanity floor  -- large disagreements are usually a bug in our model, not an
                   opinion. This is the real point of the audit.
  scoreboard    -- once the week is played, who was closer.

Consensus files are keyed by player name, ours by gsis_id, so the join is on a
normalised name plus team.

Usage:
    python audit_vs_consensus.py --year 2026 --week 1
"""

import argparse
import csv
import math
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEEKLY_PROJ = os.path.join(os.path.dirname(HERE), "ff_weekly_proj")

SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
TEAM_FIX = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "ARZ": "ARI"}


def norm(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = SUFFIX.sub("", n.lower())
    return re.sub(r"[^a-z]", "", n)


def load_consensus():
    out = {}
    for pos in ("qb", "rb", "wr", "te"):
        path = os.path.join(WEEKLY_PROJ, f"consensus_{pos}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                name = r.get(pos.upper()) or r.get("Player") or ""
                # header differs per file: WR says "(Half)", the rest "(Half-PPR)"
                pts = next((r[c] for c in ("Fantasy Points (Half-PPR)",
                                           "Fantasy Points (Half)",
                                           "Fantasy Points")
                            if c in r and r[c] not in (None, "")), None)
                if not name or pts in (None, ""):
                    continue
                out[norm(name)] = {"pos": pos.upper(), "pts": float(pts),
                                   "team": TEAM_FIX.get(r.get("Team", ""), r.get("Team", "")),
                                   "name": name}
    return out


def load_ours(year, week):
    path = os.path.join(DATA, f"projections_{year}_wk{week:02d}.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["player"].strip():
                out[norm(r["player"])] = {"pts": float(r["half_ppr"]), "pos": r["pos"],
                                          "team": r["team"], "name": r["player"],
                                          "pid": r["player_id"]}
    return out


def load_actuals(year, week):
    import project as P
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["week"] == str(week) and r["position"] in ("QB", "RB", "WR", "TE"):
                out[norm(r["player_display_name"])] = P.actual_points(r)
    return out


def rmse(pairs):
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs)) if pairs else float("nan")


def main():
    import sys
    sys.path.insert(0, HERE)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    cons, ours = load_consensus(), load_ours(args.year, args.week)
    actual = load_actuals(args.year, args.week)
    common = [k for k in ours if k in cons and cons[k]["pos"] != "QB"]
    print(f"\n  consensus rows {len(cons):,} | ours {len(ours):,} | matched {len(common):,}")

    # sanity floor -- biggest disagreements
    diffs = sorted(((ours[k]["pts"] - cons[k]["pts"], k) for k in common),
                   key=lambda t: -abs(t[0]))
    print(f"\n  biggest disagreements (ours minus consensus)\n")
    print(f"  {'player':<24}{'pos':<5}{'tm':<5}{'ours':>7}{'cons':>7}{'diff':>8}"
          f"{'actual':>8}")
    for d, k in diffs[:args.top]:
        o, c = ours[k], cons[k]
        a = actual.get(k)
        print(f"  {o['name']:<24}{o['pos']:<5}{o['team']:<5}{o['pts']:>7.1f}"
              f"{c['pts']:>7.1f}{d:>+8.1f}{(f'{a:.1f}' if a is not None else '-'):>8}")

    # scoreboard, if the week has been played
    scored = [k for k in common if k in actual]
    if scored:
        ours_p = [(ours[k]["pts"], actual[k]) for k in scored]
        cons_p = [(cons[k]["pts"], actual[k]) for k in scored]
        ro, rc = rmse(ours_p), rmse(cons_p)
        mo = sum(abs(a - b) for a, b in ours_p) / len(ours_p)
        mc = sum(abs(a - b) for a, b in cons_p) / len(cons_p)
        print(f"\n  scored against actual week {args.week} results  (n={len(scored):,})\n")
        print(f"  {'':<14}{'RMSE':>9}{'MAE':>9}")
        print(f"  {'ours':<14}{ro:>9.3f}{mo:>9.3f}")
        print(f"  {'consensus':<14}{rc:>9.3f}{mc:>9.3f}")
        verdict = "ours" if ro < rc else "consensus"
        print(f"\n  closer on RMSE: {verdict}  ({abs(ro-rc)/max(ro,rc)*100:.1f}% apart)")
        for p in ("RB", "WR", "TE"):
            sub = [k for k in scored if ours[k]["pos"] == p]
            if len(sub) > 20:
                print(f"    {p}: ours {rmse([(ours[k]['pts'], actual[k]) for k in sub]):.2f}"
                      f"   consensus {rmse([(cons[k]['pts'], actual[k]) for k in sub]):.2f}"
                      f"   (n={len(sub)})")
    print()


if __name__ == "__main__":
    main()
