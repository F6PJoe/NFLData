#!/usr/bin/env python3
"""
Slate sampler: record when every FantasyPros weekly-rankings expert updates.

Run this repeatedly through the hours before a lock (Sunday ~9 AM to 1 PM ET,
or Thursday afternoon into the 8:15 PM kickoff). Each run appends one stateless
snapshot of every panel expert's `last_updated` epoch across the weekly lists;
`analyze_weekly_freshness.py` turns those snapshots into update events.

The point is to answer a question nobody can answer from the outside yet: do
these analysts actually re-save their boards inside the window Joe is willing
to trust -- after 12:30 PM ET on a Sunday, after 6 PM ET on a Thursday? Until
that is measured, any cutoff is a guess, and so is the choice of which four
sources to blend. Two or three sampled slates turn both into data questions.

`--fingerprint` adds a second, panel-independent signal: it hashes each tracked
source's own list, so a source FP does not list in its expert panel (four of
the seven were absent on 2026-09-02) can still be seen to change.

Snapshots are stateless (one file per sample, nothing read back) so concurrent
or retried runs can't corrupt earlier data.

Usage:
    python sample_weekly_freshness.py --until 13:00 --fingerprint
    python sample_weekly_freshness.py --slate THU --until 20:10
    python sample_weekly_freshness.py --half-ppr-only   # just the 5 shipped first
"""

import argparse
import collections
import datetime
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import weekly_freshness as wf


def sample_all(lists, workers=8):
    """Fetch every requested list concurrently. Returns (results, errors)."""
    session = requests.Session()
    results, errors = [], []

    def one(key):
        slot, scoring = key
        try:
            return key, wf.fetch_list_freshness(slot, scoring, session=session), None
        except Exception as exc:                     # network/parse failure
            return key, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, data, err in ex.map(one, lists):
            if err:
                errors.append((key, err))
            else:
                results.append(data)
    return results, errors


def fingerprint_sources(lists, year, week, workers=8):
    """Hash each tracked source's own list for every requested slot.

    The panel epoch is the better signal, but it only exists for experts FP
    currently lists in `expertGroupsData` -- and four of the seven sources were
    absent from every panel page on 2026-09-02 while still returning real data
    from the API. Fingerprints cover those: comparing them across samples shows
    a board changed even with no timestamp to read.
    """
    session = requests.Session()
    jobs = [(eid, slot, scoring)
            for eid in wf.TRACKED_EXPERTS
            for slot, scoring in lists]

    results, errors = [], []

    def one(job):
        eid, slot, scoring = job
        label = f"{wf.TRACKED_EXPERTS[eid]} {slot}/{scoring}"
        try:
            return wf.fingerprint_expert_list(
                eid, slot, scoring, year, week, session=session), None, label
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}", label

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for data, err, label in ex.map(one, jobs):
            if err:
                errors.append((label, err))
            else:
                results.append(data)
    return results, errors


def print_fingerprints(fingerprints):
    """Per-source coverage: which lists this source has actually submitted."""
    if not fingerprints:
        return
    by_expert = collections.defaultdict(list)
    for fp in fingerprints:
        by_expert[fp["expert_id"]].append(fp)
    print("\n  Source list coverage (players per submitted list):")
    for source in wf.SOURCE_PRIORITY:
        for eid in source["ids"]:
            fps = by_expert.get(eid, [])
            filled = [f for f in fps if f["count"]]
            if not fps:
                continue
            detail = ", ".join(
                f"{f['slot']}/{f['scoring']}={f['count']}" for f in
                sorted(filled, key=lambda f: (f["slot"], f["scoring"]))) or "none"
            print(f"    {source['label']:18s} {len(filled)}/{len(fps)} lists  {detail}")


def write_snapshot(results, out_root, sampled_at, cutoff, fingerprints=None):
    """Append one JSONL snapshot. Returns (path, row_count)."""
    year = next((r["year"] for r in results if r.get("year")), "unknown")
    week = next((r["week"] for r in results if r.get("week")), "unknown")
    try:
        week_dir = f"{year}-wk{int(week):02d}"
    except (TypeError, ValueError):
        week_dir = f"{year}-wk{week}"

    out_dir = os.path.join(out_root, week_dir)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"sample-{int(sampled_at.timestamp())}.jsonl")

    rows = 0
    with open(path, "w", encoding="utf-8") as f:
        for fp in (fingerprints or []):
            f.write(json.dumps({
                "kind": "fingerprint",
                "sampled_at": int(sampled_at.timestamp()),
                "sampled_at_et": sampled_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "year": year, "week": week,
                "expert_id": fp["expert_id"],
                "expert_name": wf.TRACKED_EXPERTS.get(fp["expert_id"]),
                "slot": fp["slot"], "scoring": fp["scoring"],
                "count": fp["count"], "fingerprint": fp["fingerprint"],
                "api_last_updated": fp["api_last_updated"],
            }, ensure_ascii=False) + "\n")
            rows += 1
        for r in results:
            for e in r["experts"]:
                when = wf.to_et(e["last_updated"])
                f.write(json.dumps({
                    "kind": "panel",
                    "sampled_at": int(sampled_at.timestamp()),
                    "sampled_at_et": sampled_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "year": r["year"],
                    "week": r["week"],
                    "slot": r["slot"],
                    "scoring": r["scoring"],
                    "expert_id": e["expert_id"],
                    "expert_name": e["expert_name"],
                    "last_updated": e["last_updated"],
                    "last_updated_et": when.strftime("%Y-%m-%d %H:%M:%S %Z") if when else None,
                    "tier": wf.tier(e["last_updated"], now_et=sampled_at,
                                     cutoff=cutoff),
                }, ensure_ascii=False) + "\n")
                rows += 1
    return path, rows


def print_summary(results, sampled_at, slate, cutoff):
    """What a human wants to see at 12:55: who is fresh, right now."""
    print(f"\n=== Sampled {sampled_at.strftime('%a %Y-%m-%d %I:%M %p %Z')} "
          f"| slate {slate} | cutoff {cutoff.strftime('%I:%M %p')} ET ===")

    for r in sorted(results, key=lambda r: (r["slot"], r["scoring"])):
        if r["mismatch"]:
            print(f"  !! {r['slot']}/{r['scoring']}: {r['mismatch']}")
        counts = collections.Counter(
            wf.tier(e["last_updated"], now_et=sampled_at, cutoff=cutoff)
            for e in r["experts"])
        tracked_fresh = [
            wf.TRACKED_EXPERTS[e["expert_id"]]
            for e in r["experts"]
            if e["expert_id"] in wf.TRACKED_EXPERTS
            and wf.tier(e["last_updated"], now_et=sampled_at,
                        cutoff=cutoff) == "FRESH"
        ]
        print(f"  {r['slot']:4s}/{r['scoring']:4s} wk{r['week']:<3s} "
              f"n={len(r['experts']):3d}  "
              f"FRESH={counts['FRESH']:3d} SAME_DAY={counts['SAME_DAY']:3d} "
              f"STALE={counts['STALE']:3d}  "
              f"yours-fresh={sorted(set(tracked_fresh)) or '-'}")

    latest = [(e["last_updated"], e["expert_name"])
              for r in results for e in r["experts"] if e["last_updated"]]
    if latest:
        print("\n  Most recent updates seen across all lists:")
        for epoch, name in sorted(set(latest), reverse=True)[:8]:
            print(f"    {wf.to_et(epoch).strftime('%a %m/%d %I:%M %p %Z')}  {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-root", default="freshness",
                    help="directory for snapshot files (default: freshness)")
    ap.add_argument("--half-ppr-only", action="store_true",
                    help="sample only the 5 half-PPR lists published first")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the summary but write no snapshot file")
    ap.add_argument("--repeat", type=int, default=1,
                    help="number of samples to take (default 1)")
    ap.add_argument("--interval", type=int, default=600,
                    help="seconds between samples when repeating (default 600)")
    ap.add_argument("--until", metavar="HH:MM",
                    help="keep sampling until this ET wall-clock time, e.g. 13:00. "
                         "Takes precedence over --repeat.")
    ap.add_argument("--slate", choices=sorted(wf.SLATES),
                    help="which slate's cutoff to label rows with "
                         "(default: inferred from the weekday)")
    ap.add_argument("--cutoff", metavar="HH:MM",
                    help="override the slate's freshness cutoff, ET")
    ap.add_argument("--fingerprint", action="store_true",
                    help="also hash each tracked source's actual list per slot. "
                         "Slower (one API call per source per list) but works "
                         "for sources FP does not list in its expert panel.")
    ap.add_argument("--year", help="override the year for fingerprint queries "
                                   "(validation against a past season)")
    ap.add_argument("--week", help="override the week for fingerprint queries "
                                   "(validation against a past week)")
    args = ap.parse_args()

    # slate_lists() is the pre-lock set (13 lists); K/DST are excluded because
    # they come from a different analyst pool on a slower cadence.
    lists = wf.HALF_PPR_LISTS if args.half_ppr_only else wf.slate_lists()

    try:
        slate, slate_cfg = wf.slate_for(override=args.slate)
    except ValueError as exc:
        if not args.cutoff:
            sys.exit(f"{exc}")
        slate, slate_cfg = "ADHOC", {}
    if args.cutoff:
        hh, mm = (int(x) for x in args.cutoff.split(":"))
        cutoff = datetime.time(hh, mm)
    else:
        cutoff = slate_cfg["cutoff"]
    print(f"Slate {slate}, freshness cutoff {cutoff.strftime('%I:%M %p')} ET.")

    stop_at = None
    if args.until:
        hh, mm = (int(x) for x in args.until.split(":"))
        now = datetime.datetime.now(wf.ET)
        stop_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if stop_at <= now:
            sys.exit(f"--until {args.until} ET is already past.")
        print(f"Sampling every {args.interval}s until "
              f"{stop_at.strftime('%I:%M %p %Z')}.", flush=True)

    taken, degraded = 0, False
    while True:
        sampled_at = datetime.datetime.now(wf.ET)
        results, errors = sample_all(lists, workers=args.workers)
        for key, err in errors:
            print(f"WARNING: {key[0]}/{key[1]} failed -- {err}", file=sys.stderr)
            degraded = True

        if not results:
            # One bad sample must never kill a multi-hour sampling run.
            print("WARNING: no lists fetched for this sample.", file=sys.stderr)
            degraded = True
        else:
            print_summary(results, sampled_at, slate, cutoff)

            fingerprints = None
            if args.fingerprint:
                year = args.year or next(
                    (r["year"] for r in results if r.get("year")), None)
                week = args.week or next(
                    (r["week"] for r in results if r.get("week")), None)
                if args.year or args.week:
                    print(f"\n  (fingerprints forced to {year} week {week})")
                if year and week:
                    fingerprints, fp_errors = fingerprint_sources(
                        lists, year, week, workers=args.workers)
                    for label, err in fp_errors:
                        print(f"WARNING: fingerprint {label} failed -- {err}",
                              file=sys.stderr)
                        degraded = True
                    print_fingerprints(fingerprints)
                else:
                    print("WARNING: no year/week on any page -- skipping "
                          "fingerprints.", file=sys.stderr)
                    degraded = True

            if args.dry_run:
                print("\n(dry run -- no snapshot written)", flush=True)
            else:
                path, rows = write_snapshot(results, args.out_root, sampled_at,
                                            cutoff, fingerprints)
                print(f"\nWrote {rows} rows to {path}", flush=True)

        taken += 1
        if stop_at is not None:
            nxt = datetime.datetime.now(wf.ET) + datetime.timedelta(seconds=args.interval)
            if nxt > stop_at:
                break
        elif taken >= args.repeat:
            break
        time.sleep(args.interval)

    print(f"\nDone -- {taken} sample(s) taken.")
    if degraded:
        sys.exit(1)


if __name__ == "__main__":
    main()
