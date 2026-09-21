#!/usr/bin/env python3
"""
The FULL FantasyPros weekly accuracy leaderboard (150+ analysts, not just
Joe's own row), so it's possible to actually compare which of the pool
analysts are strongest per position -- the question this was all built for.

There is no API for this: the page requires a logged-in FantasyPros account
to show anyone past the top 10, so it can only be captured through Joe's own
already-authenticated browser (same pattern as the PFF/Jahnke capture --
Claude-in-Chrome driving his real Chrome, never handling the login itself).

Capture procedure:
    1. Navigate to https://www.fantasypros.com/nfl/accuracy/?week=<N>
       (omit ?week= for "season to date"; add &year=<Y> for a past season).
    2. get_page_text the page.
    3. Save that raw text to a file and run:
       python accuracy_leaderboard.py parse <file> --year 2026 --week 1
       -- parses it and writes weekly/<year>-wk<NN>/accuracy_leaderboard.json.

    python accuracy_leaderboard.py show --year 2026 --week 1 --sources
       -- prints just the 7 pool analysts' per-position ranks for that week.
    python accuracy_leaderboard.py show --year 2026 --week 1 --position QB
       -- prints the top of that week's QB-specific accuracy order.

    python accuracy_leaderboard.py trend --position TE
       -- EVERY analyst who has ranked TE in any captured week, with their
       average rank, consistency (stdev), and how many weeks that's based
       on -- so a one-week #5 and a steady #20-#25 analyst don't look the
       same. This is the whole point of storing everyone, not just the pool:
       it's how a genuinely under-used analyst gets noticed, and how a pool
       member coasting on one good week gets caught, rather than either
       being decided from reputation or a single week's snapshot.

Parsing is deliberately tolerant of the copy/paste shape `get_page_text`
returns (one field per line, blank lines collapsed) rather than assuming any
particular HTML structure, since that structure is Not under this project's
control and a page redesign should degrade to "stops parsing" rather than
silently mis-parsing.
"""

import argparse
import glob
import json
import os
import re
import statistics

import weekly_freshness as wf

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST", "IDP")

# Pool analysts' accuracy-leaderboard display names differ from the
# SOURCE_PRIORITY labels used elsewhere (FP shows outlet, not "PFF"/"FTN"
# origin) -- mapped here once so a lookup by prefix always finds the right row.
POOL_DISPLAY_NAMES = {
    "boone": "Justin Boone - Yahoo",
    "thorman": "Patrick Thorman - Establish the Run",
    "ratcliffe": "Jeff Ratcliffe - FTN",
    "koerner": "Sean Koerner - The Action Network",
    "tylero": "Tyler Orginski - FTN",
    "jahnke": "Nathan Jahnke - Pro Football Focus",
    "deldon": "Dalton Del Don - The Deep Shot",
}


def _to_int_or_none(text):
    text = text.strip()
    if text in ("", "—", "-", "--"):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_leaderboard_text(text):
    """Raw page text -> [{"rank", "name", "QB": int_or_None, ...}, ...].

    Finds the header row (RANK / EXPERT NAME / QB / RB / WR / TE / K / DST /
    IDP, one per line) and reads fixed-size 9-field records after it until a
    line that isn't a plausible name/number derails a record -- in practice
    that's the "Featured Tools" footer, which naturally fails to parse as a
    record and stops the scan.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    try:
        header_at = next(i for i in range(len(lines) - 8)
                          if lines[i:i + 9] == ["RANK", "EXPERT NAME", "QB",
                                                 "RB", "WR", "TE", "K", "DST",
                                                 "IDP"])
    except StopIteration:
        raise ValueError("could not find the RANK/EXPERT NAME/... header row "
                          "-- has FantasyPros changed the page layout?")

    rows = []
    i = header_at + 9
    while i + 9 <= len(lines):
        chunk = lines[i:i + 9]
        rank_text, name = chunk[0], chunk[1]
        rank = _to_int_or_none(rank_text)
        if rank is None and rank_text not in ("—", "-", "--"):
            break  # not a data row (e.g. "Featured Tools") -- done
        if " - " not in name and "Site Rankings" not in name:
            break  # doesn't look like "Person - Outlet" -- done
        record = {"rank": rank, "name": name}
        for pos, val in zip(POSITIONS, chunk[2:]):
            record[pos] = _to_int_or_none(val)
        rows.append(record)
        i += 9

    if not rows:
        raise ValueError("found the header but parsed zero data rows -- "
                          "check the input file wasn't truncated")
    return rows


def week_dir(year, week, out_root="weekly"):
    return os.path.join(out_root, f"{year}-wk{int(week):02d}")


def save(year, week, rows, out_root="weekly", scoring_note=None):
    d = week_dir(year, week, out_root)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "accuracy_leaderboard.json")
    payload = {"year": year, "week": week, "analysts": rows}
    if scoring_note:
        payload["note"] = scoring_note
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def load(year, week, out_root="weekly"):
    path = os.path.join(week_dir(year, week, out_root), "accuracy_leaderboard.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find(rows, name):
    return next((r for r in rows if r["name"] == name), None)


def pool_rows(payload):
    """{prefix: row_or_None} for the 7 SOURCE_PRIORITY analysts, matched by
    their accuracy-leaderboard display name (see POOL_DISPLAY_NAMES).
    """
    rows = payload["analysts"]
    out = {}
    for source in wf.SOURCE_PRIORITY:
        prefix = source["prefix"]
        display = POOL_DISPLAY_NAMES.get(prefix)
        out[prefix] = find(rows, display) if display else None
    return out


def discover_weeks(out_root="weekly"):
    """[(year, week), ...] for every week with a captured leaderboard,
    sorted chronologically -- so `trend` always covers everything captured
    so far without being told which weeks exist.
    """
    out = []
    for path in glob.glob(os.path.join(out_root, "*-wk*", "accuracy_leaderboard.json")):
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            continue
        out.append((payload["year"], payload["week"]))
    return sorted(set(out))


def trend(position, out_root="weekly"):
    """{analyst_name: {"ranks": [...], "weeks": [(year, week), ...]}} for
    EVERY analyst who has a rank for `position` in any captured week --
    not just the 7 pool sources. That's the point: a consistently-good
    analyst nobody's using yet only shows up if everyone gets tracked.
    """
    by_analyst = {}
    for year, week in discover_weeks(out_root):
        payload = load(year, week, out_root=out_root)
        for row in payload["analysts"]:
            val = row.get(position)
            if val is None:
                continue
            rec = by_analyst.setdefault(row["name"], {"ranks": [], "weeks": []})
            rec["ranks"].append(val)
            rec["weeks"].append((year, week))
    return by_analyst


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="parse a saved page-text capture and store it")
    p.add_argument("textfile")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--week", type=int, required=True)
    p.add_argument("--out-root", default="weekly")

    s = sub.add_parser("show", help="print a stored week's leaderboard")
    s.add_argument("--year", type=int, required=True)
    s.add_argument("--week", type=int, required=True)
    s.add_argument("--out-root", default="weekly")
    s.add_argument("--sources", action="store_true",
                    help="just the 7 pool analysts, side by side")
    s.add_argument("--position", choices=POSITIONS,
                    help="top of the leaderboard for one position only")
    s.add_argument("--top", type=int, default=15)

    t = sub.add_parser("trend", help="cross-week consistency for one position, "
                                      "across every captured analyst")
    t.add_argument("--position", choices=POSITIONS, required=True)
    t.add_argument("--out-root", default="weekly")
    t.add_argument("--min-weeks", type=int, default=1,
                    help="drop analysts with fewer weeks of data than this "
                         "(default 1 -- no filtering; raise this once "
                         "several weeks are captured to cut one-week noise)")
    t.add_argument("--sort", choices=["avg", "consistency"], default="avg",
                    help="avg: best average rank first. consistency: lowest "
                         "week-to-week variance first (needs 2+ weeks; "
                         "single-week analysts sort last, not first, since "
                         "one data point isn't 'consistent')")
    t.add_argument("--top", type=int, default=25)

    args = ap.parse_args()

    if args.cmd == "parse":
        with open(args.textfile, encoding="utf-8") as f:
            text = f.read()
        rows = parse_leaderboard_text(text)
        path = save(args.year, args.week, rows, out_root=args.out_root)
        print(f"Parsed {len(rows)} analysts -> {path}")
        missing = [p for p, r in pool_rows({"analysts": rows}).items() if r is None]
        if missing:
            print(f"  NOTE: not found on this page for pool prefix(es): "
                  f"{', '.join(missing)} -- check POOL_DISPLAY_NAMES still "
                  f"matches their current FP display name")
        return

    if args.cmd == "trend":
        by_analyst = trend(args.position, out_root=args.out_root)
        rows = []
        for name, rec in by_analyst.items():
            ranks = rec["ranks"]
            n = len(ranks)
            if n < args.min_weeks:
                continue
            avg = statistics.mean(ranks)
            stdev = statistics.stdev(ranks) if n >= 2 else None
            rows.append({"name": name, "n": n, "avg": avg, "stdev": stdev,
                         "best": min(ranks), "worst": max(ranks)})

        if args.sort == "consistency":
            # No-stdev (single-week) rows sort after every multi-week row --
            # one good week is not "consistent," it's just unmeasured yet.
            rows.sort(key=lambda r: (r["stdev"] is None, r["stdev"] if r["stdev"] is not None else 0))
        else:
            rows.sort(key=lambda r: r["avg"])

        total_weeks = len(discover_weeks(args.out_root))
        print(f"{args.position} accuracy across {total_weeks} captured week(s), "
              f"sorted by {args.sort}:")
        header = f"{'Analyst':42s}{'Weeks':>6s}{'Avg':>7s}{'StDev':>8s}{'Best':>6s}{'Worst':>6s}"
        print(header)
        print("-" * len(header))
        for r in rows[:args.top]:
            stdev_str = f"{r['stdev']:.1f}" if r["stdev"] is not None else "--"
            print(f"{r['name']:42s}{r['n']:>6d}{r['avg']:>7.1f}"
                  f"{stdev_str:>8s}{r['best']:>6d}{r['worst']:>6d}")
        if total_weeks < 3:
            print(f"\n(only {total_weeks} week(s) captured so far -- averages "
                  f"and especially stdev are not meaningful yet; this needs "
                  f"several more weeks before trusting it over reputation)")
        return

    payload = load(args.year, args.week, out_root=args.out_root)
    if not payload:
        print(f"No stored leaderboard for {args.year} week {args.week}. "
              f"Run `parse` first.")
        return

    if args.sources:
        rows = pool_rows(payload)
        header = f"{'Analyst':10s}{'Rank':>6s}" + "".join(
            f"{p:>6s}" for p in ("QB", "RB", "WR", "TE"))
        print(header)
        print("-" * len(header))
        for prefix, row in rows.items():
            if row is None:
                print(f"{prefix:10s}  (not found on this week's leaderboard)")
                continue
            cells = "".join(f"{(row.get(p) if row.get(p) is not None else '--'):>6}"
                             for p in ("QB", "RB", "WR", "TE"))
            print(f"{prefix:10s}{row['rank']:>6}{cells}")
        return

    if args.position:
        ranked = [r for r in payload["analysts"] if r.get(args.position) is not None]
        ranked.sort(key=lambda r: r[args.position])
        print(f"Top {args.top} by {args.position} accuracy, "
              f"{payload['year']} week {payload['week']}:")
        for r in ranked[:args.top]:
            print(f"  {r[args.position]:>4d}  {r['name']}")
        return

    for r in payload["analysts"][:args.top]:
        cells = "  ".join(f"{p}:{r.get(p) if r.get(p) is not None else '--'}"
                           for p in ("QB", "RB", "WR", "TE"))
        rank_str = str(r["rank"]) if r["rank"] is not None else "--"
        print(f"{rank_str:>4}  {r['name']:40s}  {cells}")


if __name__ == "__main__":
    main()
