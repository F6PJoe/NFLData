#!/usr/bin/env python3
"""Fetch raw nflverse data (team stats, rosters, depth charts) into cached/.

nflverse publishes plain CSVs to GitHub releases — free, no API key, no rate
limit. Everything is cached on first fetch and never re-downloaded unless
--refresh is passed, same convention as ff_draft_proj/cached/.

Sources: https://github.com/nflverse/nflverse-data/releases

Usage:
    python fetch_nflverse.py                  # default seasons
    python fetch_nflverse.py --refresh        # ignore cache, re-download
    python fetch_nflverse.py --start 2018     # deeper history
"""

import argparse
import gzip
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cached", "nflverse")

# Seasons used to fit shrinkage weights and build the 3-yr weighted trend.
# More history = better-fitted weights; the marginal cost is one small CSV.
DEFAULT_START = 2016
PROJECTION_SEASON = 2026

UA = {"User-Agent": "Mozilla/5.0 (ff_projections; personal use)"}


def _download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    if url.endswith(".gz"):
        raw = gzip.decompress(raw)
    with open(dest, "wb") as fh:
        fh.write(raw)
    return len(raw)


def fetch(url, filename, refresh=False):
    """Download url into the cache as filename. Returns the local path."""
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, filename)
    if os.path.exists(dest) and not refresh:
        print(f"  cached   {filename}")
        return dest
    try:
        size = _download(url, dest)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"  MISSING  {filename}  (404 — not published yet)")
            return None
        raise
    print(f"  fetched  {filename}  ({size // 1024:,} KB)")
    time.sleep(0.3)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=DEFAULT_START)
    ap.add_argument("--end", type=int, default=PROJECTION_SEASON)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    seasons = range(args.start, args.end + 1)

    print(f"Team season stats ({args.start}-{args.end - 1}):")
    for yr in seasons:
        if yr >= PROJECTION_SEASON:
            continue  # no completed stats for the season we're projecting
        fetch(f"{BASE}/stats_team/stats_team_reg_{yr}.csv",
              f"stats_team_reg_{yr}.csv", args.refresh)

    # Rosters: only the projection season matters for "who is on the team now",
    # plus the prior season so we can diff for vacated volume.
    print("\nRosters:")
    for yr in (args.end - 1, args.end):
        fetch(f"{BASE}/rosters/roster_{yr}.csv", f"roster_{yr}.csv", args.refresh)

    print("\nDepth charts:")
    for yr in (args.end - 1, args.end):
        fetch(f"{BASE}/depth_charts/depth_charts_{yr}.csv",
              f"depth_charts_{yr}.csv", args.refresh)

    # Player-level season stats for the last 3 completed seasons — needed to
    # compute each player's historical market share for the workbook defaults.
    print("\nPlayer season stats (last 3 completed):")
    for yr in range(args.end - 3, args.end):
        fetch(f"{BASE}/stats_player/stats_player_reg_{yr}.csv",
              f"stats_player_reg_{yr}.csv", args.refresh)

    # Snap share is the cleanest role indicator there is - it separates "on the
    # field" from "got the ball", which target and carry share can't. Sourced
    # from Pro Football Reference via nflverse; per-game, so it needs
    # aggregating (build_history.py does that).
    print("\nSnap counts (last 3 completed):")
    for yr in range(args.end - 3, args.end):
        fetch(f"{BASE}/snap_counts/snap_counts_{yr}.csv",
              f"snap_counts_{yr}.csv", args.refresh)

    print(f"\nCache: {CACHE}")


if __name__ == "__main__":
    sys.exit(main())
