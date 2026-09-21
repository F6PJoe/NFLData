#!/usr/bin/env python3
"""
Priority-based orchestrator for the ff_rankings pipeline.

Tries sources in priority order, selects the first 4 that have data,
writes active_sources.json, then runs the consensus builder and exports.

Source priority:
  1. Koerner      (FP 120)           — no fallback
  2. Ratcliffe    (FP 125)           — fallback: FTN scraper
  3. DraftSharks  (FP 93+145)        — fallback: DraftSharks scraper
  4. Nick Mariano (FP 766)           — fallback: RotoBaller scraper
  5. FootballGuys (FP 3900+3096+4187)— no fallback
  6. Del Don      (FP 285)           — no fallback

Fetcher exit codes:
  0  = data found and written successfully
  2  = source not yet published on FP (try fallback if one exists)
  1  = error

Usage: python run_all.py
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

FP = [sys.executable, "fetch_fantasypros_rankings.py", "--expert"]

SOURCES = [
    {
        "name": "Koerner",
        "label": "Koerner",
        "prefix": "koerner",
        "primary": FP + ["koerner"],
        "fallback": None,
    },
    {
        "name": "Ratcliffe",
        "label": "Ratcliffe",
        "prefix": "ratcliffe",
        "primary": FP + ["ratcliffe"],
        "fallback": [sys.executable, "fetch_ftn_rankings.py"],
    },
    {
        "name": "DraftSharks",
        "label": "DraftSharks",
        "prefix": "draftsharks",
        "primary": FP + ["draftsharks"],
        "fallback": [sys.executable, "fetch_draftsharks_rankings.py"],
    },
    {
        "name": "Nick Mariano",
        "label": "Nick Mariano",
        "prefix": "mariano",
        "primary": FP + ["mariano"],
        "fallback": [sys.executable, "fetch_rotoballer_rankings.py"],
    },
    {
        "name": "FootballGuys",
        "label": "FootballGuys",
        "prefix": "footballguys",
        "primary": FP + ["footballguys"],
        "fallback": None,
    },
    {
        "name": "Del Don",
        "label": "Del Don",
        "prefix": "deldon",
        "primary": FP + ["deldon"],
        "fallback": None,
    },
]

MAX_SOURCES = 4
FRESHNESS_DAYS = 3


def _parse_timestamp_date(ts_str: str) -> date | None:
    """Best-effort parse of the various timestamp formats we write."""
    if not ts_str or ts_str == "unknown":
        return None
    # Strip trailing timezone label ("ET", "ET " etc.)
    s = ts_str.strip().rstrip()
    for suffix in (" ET", "ET"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    # Try formats with year first, then without (assume current year)
    formats_with_year = ["%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"]
    formats_no_year  = ["%m/%d %I:%M %p", "%m/%d"]
    for fmt in formats_with_year:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    for fmt in formats_no_year:
        try:
            return datetime.strptime(s, fmt).replace(year=date.today().year).date()
        except ValueError:
            pass
    return None


def is_fresh(label: str, max_age_days: int = FRESHNESS_DAYS) -> bool:
    """Return True if the saved timestamp for label is within max_age_days of today."""
    ts_file = os.path.join(os.path.dirname(__file__), "source_timestamps.json")
    try:
        with open(ts_file, encoding="utf-8") as f:
            timestamps = json.load(f)
    except FileNotFoundError:
        return True  # no file yet — let it through, fetcher just ran
    ts_str = timestamps.get(label)
    if not ts_str:
        return True  # never saved — treat as fresh (fetcher just wrote it)
    ts_date = _parse_timestamp_date(ts_str)
    if ts_date is None:
        print(f"  WARNING: could not parse timestamp '{ts_str}' for {label} — assuming fresh.")
        return True
    age = date.today() - ts_date
    return age <= timedelta(days=max_age_days)


def run(cmd):
    print(f"\n=== {' '.join(cmd[1:])} ===")
    return subprocess.run(cmd).returncode


def main():
    active = []

    for source in SOURCES:
        if len(active) >= MAX_SOURCES:
            break

        print(f"\n--- Trying {source['name']} (primary) ---")
        rc = run(source["primary"])
        if rc == 0:
            if not is_fresh(source["label"]):
                print(f"--- {source['name']}: data is older than {FRESHNESS_DAYS} days — skipping ---")
                continue
            active.append(source)
            continue

        if rc == 2 and source["fallback"]:
            print(f"--- {source['name']}: not on FP yet — trying fallback ---")
            rc2 = run(source["fallback"])
            if rc2 == 0:
                if not is_fresh(source["label"]):
                    print(f"--- {source['name']}: fallback data is older than {FRESHNESS_DAYS} days — skipping ---")
                    continue
                active.append(source)
                continue

        if rc not in (0, 2):
            print(f"WARNING: {source['name']} primary errored (exit {rc})")
        print(f"--- {source['name']}: skipped (no data available) ---")

    print(f"\n=== Active sources ({len(active)}/{MAX_SOURCES}): "
          f"{[s['name'] for s in active]} ===")

    if not active:
        sys.exit("No sources available — aborting.")

    with open("active_sources.json", "w", encoding="utf-8") as f:
        json.dump(
            [{"name": s["name"], "label": s["label"], "prefix": s["prefix"]}
             for s in active],
            f, indent=2,
        )
    print("Wrote active_sources.json.")

    for step in [
        [sys.executable, "build_consensus.py"],
        [sys.executable, "export_combined.py"],
    ]:
        rc = run(step)
        if rc != 0:
            sys.exit(f"Step failed: {' '.join(step[1:])} (exit {rc})")


if __name__ == "__main__":
    main()
