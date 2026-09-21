#!/usr/bin/env python3
"""Read the weekly judgement sheet -- deliberately forgiving about spelling.

The decision column accepts, case-insensitively:

    OUT       won't play        -> share 0, removed from the pool entirely,
                                   so his touches redistribute to teammates
    LIMITED   plays reduced     -> 60% of normal usage, the other 40% goes
                                   back to the rest of the position group
    PLAY      plays normally    -> no change (same as leaving it blank)
    <number>  e.g. 40 or 40%    -> that percent of normal usage

Blank always means PLAY, so an unfilled sheet is valid and changes nothing.
Anything it cannot parse is REPORTED rather than silently ignored -- a typo
that quietly does nothing is the worst outcome here.

Usage:
    python read_review.py --year 2026 --week 2          # show how it reads
"""

import argparse
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

OUT_WORDS = {"out", "o", "sit", "no", "n", "inactive", "scratch"}
PLAY_WORDS = {"play", "p", "yes", "y", "active", "go", "full", "in", ""}
LIMITED_WORDS = {"limited", "ltd", "lim", "l", "reduced", "snap count", "pitch count"}
LIMITED_DEFAULT = 0.60


def parse_decision(raw):
    """-> (multiplier, label, ok). multiplier 0.0 means remove from the pool."""
    v = (raw or "").strip().lower().rstrip(".")
    if v in PLAY_WORDS:
        return 1.0, "PLAY", True
    if v in OUT_WORDS:
        return 0.0, "OUT", True
    if v in LIMITED_WORDS:
        return LIMITED_DEFAULT, f"LIMITED ({LIMITED_DEFAULT:.0%})", True
    m = re.fullmatch(r"(\d{1,3})\s*%?", v)
    if m:
        pct = int(m.group(1))
        if 0 <= pct <= 100:
            return pct / 100, f"{pct}% usage", True
    return 1.0, f"UNRECOGNISED {raw!r} -- treated as PLAY", False


def load(year, week):
    """player_id -> multiplier. Missing file or blank rows are fine."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out, problems = {}, []
    if not os.path.exists(path):
        return out, problems
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            mult, label, ok = parse_decision(r.get("decision"))
            if not ok:
                problems.append((r.get("player", "?"), r.get("decision")))
            if mult != 1.0:
                out[r["player_id"]] = mult
    return out, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()
    path = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    if not os.path.exists(path):
        print(f"  no sheet at {path} -- every Questionable player treated as PLAY")
        return
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"\n  reading {os.path.basename(path)}\n")
    print(f"  {'player':<24}{'you wrote':<14}{'read as':<24}{'effect'}")
    bad = 0
    for r in rows:
        mult, label, ok = parse_decision(r.get("decision"))
        bad += not ok
        eff = ("no change" if mult == 1.0 else
               "removed, share goes to teammates" if mult == 0.0 else
               f"usage x{mult:.2f}, rest to teammates")
        print(f"  {r['player']:<24}{(r.get('decision') or '(blank)'):<14}{label:<24}{eff}")
    print(f"\n  {len(rows)} rows, {bad} unrecognised\n")


if __name__ == "__main__":
    main()
