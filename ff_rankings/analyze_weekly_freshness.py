#!/usr/bin/env python3
"""
Turn Sunday freshness snapshots into an answer about the cutoff.

Reads the JSONL snapshots written by `sample_weekly_freshness.py` and reports:

  1. Update events   -- each time an expert's saved timestamp changed during
                        the sampling window, i.e. proof they re-saved a board.
  2. Late leaderboard-- every expert ranked by their last save of that day,
                        so you can see who actually works past inactives.
  3. Cutoff sweep    -- for a range of candidate cutoff times, how many of
                        your sources (and of the whole panel) would pass the
                        gate. This is the output that sets the threshold:
                        pick the latest time that still leaves you enough
                        sources to blend.

Usage:
    python analyze_weekly_freshness.py freshness/2026-wk01
    python analyze_weekly_freshness.py freshness/2026-wk01 --slot FLX --scoring HALF
"""

import argparse
import collections
import datetime
import glob
import json
import os
import sys

import weekly_freshness as wf


def sweep_times(slate_cfg, step_minutes=30, span_hours=4):
    """Candidate cutoffs from `span_hours` before the run time up to it.

    Derived from the slate rather than hardcoded, so a Thursday sweep walks
    the afternoon into the 8:10 PM run and a Sunday sweep walks the morning
    into 12:55 -- the same question, different clock.
    """
    run_at = slate_cfg["run_at"]
    anchor = datetime.datetime(2000, 1, 2, run_at.hour, run_at.minute)
    times = []
    t = anchor - datetime.timedelta(hours=span_hours)
    while t <= anchor:
        times.append(t.time())
        t += datetime.timedelta(minutes=step_minutes)
    # Always include the configured cutoff, even if the step misses it.
    if slate_cfg["cutoff"] not in times:
        times.append(slate_cfg["cutoff"])
    return sorted(times)


def load_rows(sample_dir, slot=None, scoring=None):
    files = sorted(glob.glob(os.path.join(sample_dir, "sample-*.jsonl")))
    if not files:
        sys.exit(f"No snapshots found in {sample_dir}")
    rows = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if slot and r["slot"] != slot:
                    continue
                if scoring and r["scoring"] != scoring:
                    continue
                rows.append(r)
    return rows, files


def panel_rows(rows):
    """Rows carrying a panel epoch. Older snapshots predate the `kind` field."""
    return [r for r in rows if r.get("kind", "panel") == "panel"]


def update_events(rows):
    """Per (expert, list), every observed change in the saved timestamp.

    Panel rows only -- fingerprint rows carry no timestamp to compare.
    """
    seen = collections.defaultdict(list)
    for r in sorted(panel_rows(rows), key=lambda r: r["sampled_at"]):
        key = (r["expert_id"], r["expert_name"], r["slot"], r["scoring"])
        seen[key].append((r["sampled_at"], r["last_updated"]))

    events = []
    for (eid, name, slot, scoring), series in seen.items():
        prev = None
        for sampled_at, last_updated in series:
            if prev is not None and last_updated != prev:
                events.append({
                    "expert_id": eid, "expert_name": name,
                    "slot": slot, "scoring": scoring,
                    "observed_by": sampled_at, "new_last_updated": last_updated,
                })
            prev = last_updated
    return events


def report(rows, files, sample_dir, slate, slate_cfg):
    days = sorted({wf.to_et(r["sampled_at"]).date() for r in rows})
    print(f"=== {sample_dir}: {len(files)} snapshots, {len(rows)} rows, "
          f"day(s) {', '.join(str(d) for d in days)} ===")
    first, last = min(r["sampled_at"] for r in rows), max(r["sampled_at"] for r in rows)
    print(f"    sampling window {wf.to_et(first).strftime('%I:%M %p')} "
          f"-> {wf.to_et(last).strftime('%I:%M %p %Z')}")

    # --- 1. update events -------------------------------------------------
    events = update_events(rows)
    print(f"\n--- Update events observed during the window ({len(events)}) ---")
    if not events:
        print("    none -- nobody re-saved a board while sampling was running.")
    for e in sorted(events, key=lambda e: e["new_last_updated"] or 0):
        when = wf.to_et(e["new_last_updated"])
        mine = " *YOURS*" if e["expert_id"] in wf.TRACKED_EXPERTS else ""
        print(f"    {when.strftime('%I:%M %p') if when else '??':9s} "
              f"{e['expert_name'][:24]:26s} {e['slot']}/{e['scoring']}{mine}")

    # --- 2. late leaderboard ---------------------------------------------
    latest = {}
    for r in panel_rows(rows):
        if not r.get("last_updated"):
            continue
        key = (r["expert_id"], r["expert_name"])
        latest[key] = max(latest.get(key, 0), r["last_updated"])
    print(f"\n--- Last save of the day, latest first ({len(latest)} experts) ---")
    for (eid, name), epoch in sorted(latest.items(), key=lambda kv: -kv[1])[:25]:
        when = wf.to_et(epoch)
        mine = " *YOURS*" if eid in wf.TRACKED_EXPERTS else ""
        print(f"    {when.strftime('%a %m/%d %I:%M %p'):20s} id={eid:<6} {name[:26]:28s}{mine}")

    # --- 3. cutoff sweep --------------------------------------------------
    ref_day = wf.to_et(last).date()
    print(f"\n--- Cutoff sweep ({slate}, for {ref_day}) ---")
    print(f"    {'cutoff':10s} {'panel pass':>11s} {'yours pass':>11s}   your sources passing")
    for t in sweep_times(slate_cfg):
        panel, mine = set(), set()
        for (eid, name), epoch in latest.items():
            when = wf.to_et(epoch)
            if when.date() == ref_day and when.time() >= t:
                panel.add(eid)
                if eid in wf.TRACKED_EXPERTS:
                    mine.add(wf.TRACKED_EXPERTS[eid])
        flag = "  <-- configured cutoff" if t == slate_cfg["cutoff"] else ""
        print(f"    {t.strftime('%I:%M %p'):10s} {len(panel):>11d} {len(mine):>11d}   "
              f"{sorted(mine) or '-'}{flag}")

    print(f"\n    Read this as: the latest cutoff whose 'yours pass' count still")
    print(f"    reaches {wf.MAX_SOURCES} is the threshold you can actually run. If it")
    print(f"    collapses before {slate_cfg['cutoff'].strftime('%I:%M %p')}, your")
    print("    pool doesn't work that late and the priority list should be rebuilt")
    print("    from the panel column -- those are the experts who do.")

    # --- 4. fingerprint changes (panel-independent) -----------------------
    fps = [r for r in rows if r.get("kind") == "fingerprint"]
    if fps:
        seen = collections.defaultdict(list)
        for r in sorted(fps, key=lambda r: r["sampled_at"]):
            seen[(r["expert_id"], r["expert_name"], r["slot"], r["scoring"])].append(
                (r["sampled_at"], r["fingerprint"], r["count"]))
        changes = []
        for (eid, name, slot, scoring), series in seen.items():
            for i in range(1, len(series)):
                if series[i][1] != series[i - 1][1]:
                    changes.append((series[i][0], name, slot, scoring,
                                    series[i - 1][2], series[i][2]))
        print(f"\n--- Fingerprint changes ({len(changes)}) ---")
        print("    Board content actually changed between samples. This is the only")
        print("    freshness signal for a source FP omits from its expert panel.")
        if not changes:
            print("    none observed.")
        for at, name, slot, scoring, n_before, n_after in sorted(changes):
            print(f"    {wf.to_et(at).strftime('%I:%M %p'):9s} {name[:20]:22s} "
                  f"{slot}/{scoring}  {n_before} -> {n_after} players")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sample_dir", help="e.g. freshness/2026-wk01")
    ap.add_argument("--slot", help="restrict to one slot (QB/RB/WR/TE/FLX/K/DST)")
    ap.add_argument("--scoring", help="restrict to one scoring (HALF/PPR/STD/ANY)")
    ap.add_argument("--slate", choices=sorted(wf.SLATES), default="SUN",
                    help="which slate's timing the sweep should walk (default SUN)")
    args = ap.parse_args()

    rows, files = load_rows(args.sample_dir, args.slot, args.scoring)
    report(rows, files, args.sample_dir, args.slate, wf.SLATES[args.slate])


if __name__ == "__main__":
    main()
