#!/usr/bin/env python3
"""
Week-over-week log of how the published rankings did in FantasyPros' weekly
accuracy contest, so a question like "is Koerner actually good at QB" has
real data behind it instead of one week's gut reaction or 10-year reputation.

One JSON file at the project root (not under weekly/<year>-wk<NN>/, since
this spans every week, not one): accuracy_results.json

Preferred flow, once that week's full leaderboard has been captured (see
accuracy_leaderboard.py's module docstring for the capture steps -- it needs
Joe's logged-in browser, so it can't happen from this script alone):

    python accuracy_tracking.py record --year 2026 --week 1

pulls Joe's own overall/position ranks AND all 7 pool analysts' ranks
straight from that stored leaderboard. If the leaderboard hasn't been
captured yet, fall back to typing Joe's own numbers by hand:

    python accuracy_tracking.py record --year 2026 --week 1 --overall 30 \
        --qb 114 --rb 29 --wr 32 --te 75
    python accuracy_tracking.py show

`record` also pulls which sources actually fed each position that week
straight from that week's manifest.json (the real gating result, not a
guess), so the log always reflects what was actually published.
"""

import argparse
import json
import os

import accuracy_leaderboard

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "accuracy_results.json")
POSITIONS = ("QB", "RB", "WR", "TE")
JOE_DISPLAY_NAME = "Joe Bond - Fantasy Six Pack"


def load():
    if not os.path.exists(DATA_PATH):
        return {"weeks": []}
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def sources_from_manifest(year, week, scoring, out_root):
    """{position: [analyst labels]} actually used, per that week's manifest.

    Falls back to {} (recorded but empty) rather than raising -- a missing
    or malformed manifest shouldn't block logging the contest result itself,
    which is the number that actually matters here.
    """
    path = os.path.join(out_root, f"{year}-wk{int(week):02d}", "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return {}

    gating = manifest.get("gating", {})
    out = {}
    for pos in POSITIONS:
        entry = gating.get(f"{pos}/{scoring}") or gating.get(f"{pos}/ANY")
        if entry:
            out[pos] = [u["label"] for u in entry.get("used", [])]
    return out


def from_stored_leaderboard(year, week, out_root):
    """(overall_rank, position_ranks, pool_accuracy) from a captured
    accuracy_leaderboard.json, or (None, None, None) if none is stored yet.

    pool_accuracy is {prefix: {"rank": ..., "QB": ..., ...}} for all 7 pool
    analysts regardless of whether they were actually used that week --
    this is the piece that lets a later "is Koerner actually good at QB"
    question get answered from real numbers instead of memory.
    """
    payload = accuracy_leaderboard.load(year, week, out_root=out_root)
    if not payload:
        return None, None, None
    joe = accuracy_leaderboard.find(payload["analysts"], JOE_DISPLAY_NAME)
    if not joe:
        return None, None, None
    position_ranks = {pos: joe[pos] for pos in POSITIONS if joe.get(pos) is not None}
    pool_accuracy = accuracy_leaderboard.pool_rows(payload)
    return joe["rank"], position_ranks, pool_accuracy


def record(year, week, overall=None, position_ranks=None, scoring="HALF",
           out_root="weekly", contest="FantasyPros weekly accuracy contest",
           notes=None):
    """Add or replace this week's entry. Re-running with the same
    year/week updates it in place rather than duplicating -- useful if a
    rank gets corrected or you log it again after seeing more positions.

    overall/position_ranks are optional: when omitted, they're pulled from
    that week's stored accuracy_leaderboard.json (see accuracy_leaderboard.py)
    along with every pool analyst's own accuracy, not just Joe's. Passing
    them explicitly (the old manual flow) still works for a week that
    hasn't had its leaderboard captured yet, but won't have pool_accuracy.
    """
    stored_overall, stored_ranks, pool_accuracy = from_stored_leaderboard(
        year, week, out_root)
    if overall is None:
        if stored_overall is None:
            raise ValueError(
                f"No stored leaderboard for {year} week {week} and no "
                f"--overall given -- capture the leaderboard first (see "
                f"accuracy_leaderboard.py) or pass ranks manually.")
        overall = stored_overall
    if not position_ranks:
        position_ranks = stored_ranks or {}

    data = load()
    entry = {
        "year": year,
        "week": week,
        "scoring": scoring,
        "contest": contest,
        "overall_rank": overall,
        "position_ranks": position_ranks,
        "sources_used": sources_from_manifest(year, week, scoring, out_root),
    }
    if pool_accuracy:
        entry["pool_accuracy"] = pool_accuracy
    if notes:
        entry["notes"] = notes

    weeks = [w for w in data["weeks"] if not (w["year"] == year and w["week"] == week)]
    weeks.append(entry)
    weeks.sort(key=lambda w: (w["year"], w["week"]))
    data["weeks"] = weeks
    save(data)
    return entry


def show():
    data = load()
    if not data["weeks"]:
        print("No accuracy results recorded yet.")
        return

    for w in data["weeks"]:
        print(f"Week {w['week']} ({w['year']}, {w['scoring']}) -- "
              f"overall #{w['overall_rank']} -- {w['contest']}")
        ranks = w["position_ranks"]
        sources_used = w.get("sources_used", {})
        for pos in POSITIONS:
            if pos not in ranks:
                continue
            sources = sources_used.get(pos) or []
            tag = f"  {pos:3s} #{ranks[pos]}"
            if sources:
                tag += f"  ({', '.join(s.split()[-1] for s in sources)})"
            print(tag)
        if w.get("pool_accuracy"):
            print("  pool accuracy that week (overall / QB / RB / WR / TE):")
            for prefix, row in w["pool_accuracy"].items():
                if row:
                    print(f"    {prefix:10s} #{row['rank']:<5} "
                          f"{row['QB']!s:>4} {row['RB']!s:>4} "
                          f"{row['WR']!s:>4} {row['TE']!s:>4}")
        if w.get("notes"):
            print(f"  note: {w['notes']}")
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="log one week's contest result")
    rec.add_argument("--year", type=int, required=True)
    rec.add_argument("--week", type=int, required=True)
    rec.add_argument("--overall", type=int,
                      help="overall rank in the accuracy contest -- omit to "
                           "pull it from that week's stored leaderboard")
    rec.add_argument("--qb", type=int)
    rec.add_argument("--rb", type=int)
    rec.add_argument("--wr", type=int)
    rec.add_argument("--te", type=int)
    rec.add_argument("--scoring", default="HALF", choices=["HALF", "PPR", "STD"])
    rec.add_argument("--out-root", default="weekly")
    rec.add_argument("--contest", default="FantasyPros weekly accuracy contest")
    rec.add_argument("--notes")

    sub.add_parser("show", help="print the log so far")

    args = ap.parse_args()

    if args.cmd == "record":
        position_ranks = {pos: getattr(args, pos.lower())
                           for pos in POSITIONS
                           if getattr(args, pos.lower()) is not None}
        entry = record(args.year, args.week, args.overall, position_ranks,
                        scoring=args.scoring, out_root=args.out_root,
                        contest=args.contest, notes=args.notes)
        print(f"Recorded {args.year} week {args.week}: overall "
              f"#{entry['overall_rank']}, {entry['position_ranks']}")
        if entry["sources_used"]:
            for pos, labels in entry["sources_used"].items():
                print(f"  {pos}: {', '.join(labels)}")
        else:
            print("  (no manifest.json found for this week -- sources_used left empty)")
        if entry.get("pool_accuracy"):
            print("  pool accuracy this week:")
            for prefix, row in entry["pool_accuracy"].items():
                if row:
                    print(f"    {prefix:10s} overall #{row['rank']}  "
                          f"QB {row['QB']}  RB {row['RB']}  WR {row['WR']}  TE {row['TE']}")
    elif args.cmd == "show":
        show()


if __name__ == "__main__":
    main()
