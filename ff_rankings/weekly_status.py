#!/usr/bin/env python3
"""
At-a-glance: when did each pool source last update, per list, right now.

For the moment the strict gate leaves too few (or the wrong) sources -- like
one analyst alone on TNF night -- this answers "who's actually current" so a
manual --sources choice (see run_weekly.py) is an informed one, not a guess.

Timestamp-only: it does NOT fetch full player lists, just the freshness
signals (FP panel epoch, FTN submission time, cached-capture time), so it's
fast and safe to run right before a decision without adding load.

    python weekly_status.py                  # half-PPR, all 5 pre-lock slots
    python weekly_status.py --scoring PPR
    python weekly_status.py --slot FLX        # one list only
"""

import argparse
import datetime

import requests

import cached_source
import ftn_weekly
import weekly_freshness as wf


def resolve_week(session):
    info = wf.fetch_list_freshness("FLX", "HALF", session=session)
    return info.get("year"), info.get("week")


def best_timestamp(source, slot, scoring, panel_epochs, ftn_data, cached):
    """(epoch_or_None, origin) for one source/list -- the MOST RECENT of
    whatever FP/FTN/cache signals exist, not the first one found.

    This deliberately does NOT mirror choose_sources()'s fall-through order
    (FP, then FTN only if FP fails, then cache). That order picks which
    origin WINS a slot in the real run, but this tool's job is different: show
    the best evidence available for each source so a human can judge freshness
    for themselves. Stopping at FP's timestamp just because FP has one -- even
    a stale one -- would hide a fresher FTN submission sitting right there,
    exactly the kind of thing a manual override is meant to catch. Timestamp
    only: unlike the real run this doesn't confirm the source has actual
    player rows for the winning origin, so treat it as a fast glance.
    """
    candidates = []

    epoch = next((panel_epochs.get(eid) for eid in source["ids"]
                  if panel_epochs.get(eid)), None)
    if epoch:
        candidates.append((epoch, "FP"))

    if source.get("ftn_analyst") and ftn_data:
        ts = ftn_weekly.submitted_at(ftn_data, source["ftn_analyst"], scoring, slot)
        if ts:
            candidates.append((ts, "FTN"))

    payload = cached.get(source["prefix"])
    if payload:
        # rows and ts from the SAME call: a cached source's timestamp is per
        # scoring format now, so it must never be read separately from which
        # format's rows are actually being offered.
        rows, ts = cached_source.board_for(payload, slot, scoring)
        if rows and ts:
            candidates.append((ts, payload.get("origin", "cache")))

    if not candidates:
        return None, None
    return max(candidates, key=lambda c: c[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scoring", default="HALF", choices=["HALF", "PPR", "STD"])
    ap.add_argument("--slot", choices=["FLX", "QB", "RB", "WR", "TE"],
                    help="one list only (default: all 5 pre-lock slots)")
    ap.add_argument("--out-root", default="weekly")
    args = ap.parse_args()

    now_et = datetime.datetime.now(wf.ET)
    session = requests.Session()
    year, week = resolve_week(session)
    phase, threshold, why = wf.freshness_threshold(now_et)

    print(f"Week {week} of {year} | {phase} | {why}")
    print(f"(cutoff: {'none' if threshold is None else threshold.strftime('%a %I:%M %p ET')})\n")

    slots = [args.slot] if args.slot else ["FLX", "QB", "RB", "WR", "TE"]
    week_dir = f"{args.out_root}/{year}-wk{int(week):02d}"
    cached = cached_source.load_all(week_dir)

    ftn_data = None
    try:
        ftn_data = ftn_weekly.fetch(session=session)
    except Exception as exc:
        print(f"(FTN unavailable: {type(exc).__name__}: {exc} -- "
              f"Ratcliffe/Orginski will show FP or cache only)\n")

    panel = {}
    for slot in slots:
        list_scoring = "ANY" if slot in wf.FORMAT_INVARIANT_SLOTS else args.scoring
        info = wf.fetch_list_freshness(slot, list_scoring, session=session)
        panel[slot] = {e["expert_id"]: e["last_updated"] for e in info["experts"]}

    col_w = 18
    header = f"{'Source':18s}" + "".join(f"{s:>{col_w}s}" for s in slots)
    print(header)
    print("-" * len(header))

    for source in wf.SOURCE_PRIORITY:
        cells = []
        for slot in slots:
            list_scoring = "ANY" if slot in wf.FORMAT_INVARIANT_SLOTS else args.scoring
            epoch, origin = best_timestamp(
                source, slot, list_scoring, panel[slot], ftn_data, cached)
            if not epoch:
                cells.append("no board".rjust(col_w))
                continue
            tier = wf.tier_since(epoch, threshold)
            when = wf.to_et(epoch).strftime("%a %I:%M%p").lstrip("0")
            mark = "*" if tier == "FRESH" else " "
            cells.append(f"{when} {origin}{mark}".rjust(col_w))
        print(f"{source['label']:18s}" + "".join(cells))

    print(f"\n(* = updated after the {phase} cutoff. \"no board\" = nothing "
          f"found for that list at all, at any origin.)")
    print(f"\nTo hand-pick who's included regardless of freshness:")
    print(f'  python run_weekly.py --sources <comma-separated prefixes, up to {wf.MAX_SOURCES}>')
    print(f"  prefixes: " + ", ".join(s["prefix"] for s in wf.SOURCE_PRIORITY))


if __name__ == "__main__":
    main()
