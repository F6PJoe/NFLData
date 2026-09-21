#!/usr/bin/env python3
"""Fetch Sportradar NFL seasonal statistics into cached/sr/.

What this is for
----------------
Everything else in this project runs on free sources (nflverse, Sleeper).
Sportradar is pulled for one thing they don't have: **red-zone opportunity**.

  redzone_targets     (receiving, per player and team)
  redzone_attempts    (rushing, per player and team)
  redzone_attempts    (passing, team)

Those drive the workbook's touchdown model directly:

    Rec TD  = RZ Target Share % x Team Pass TD
    Rush TD = RZ Rush Share %   x Team Rush TD

nflverse has no red-zone data at all — its passing_10 / receiving_20 columns
are yardage-gain buckets, not field position — so without this the two RZ share
columns have no data-driven default.

It also supplies clean share denominators that nflverse lacks: kneel_downs and
scrambles (shouldn't count as RB carries), spikes and throw_aways (shouldn't
count as targets).

Cost: 1 + N calls (hierarchy, then 32 teams x N seasons). Cached on first
fetch and never re-requested — not because calls are scarce but because a
parse bug shouldn't cost a round trip.

Setup: put SPORTRADAR_API_KEY in ff_projections/.env (see .env.example).

Usage:
    python fetch_sportradar.py
    python fetch_sportradar.py --seasons 2021 2022 2023 2024 2025
    python fetch_sportradar.py --refresh
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cached", "sr")
ENV = os.path.join(HERE, ".env")

BASE = "https://api.sportradar.com/nfl/official/{level}/v7/{lang}"
DEFAULT_SEASONS = (2023, 2024, 2025)
THROTTLE = 1.1  # be polite regardless of quota


def load_key():
    key = os.environ.get("SPORTRADAR_API_KEY", "").strip()
    if not key and os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            if line.strip().startswith("SPORTRADAR_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit(
            "No SPORTRADAR_API_KEY found.\n"
            f"  Add it to {ENV} (see .env.example), or export it."
        )
    return key


class Client:
    def __init__(self, key, level="production", lang="en"):
        self.key = key
        self.base = BASE.format(level=level, lang=lang)
        self.calls = 0

    def get(self, path, cache_name, refresh=False):
        """Fetch `path`, caching the raw JSON under cache_name."""
        dest = os.path.join(CACHE, cache_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest) and not refresh:
            with open(dest, encoding="utf-8") as fh:
                return json.load(fh), True

        req = urllib.request.Request(
            f"{self.base}/{path}",
            headers={"x-api-key": self.key, "User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                sys.exit("HTTP 403 - key rejected or endpoint not in your package.")
            if exc.code == 429:
                sys.exit("HTTP 429 - rate limited. Raise THROTTLE and retry.")
            raise
        self.calls += 1
        # Write raw bytes before parsing: a schema surprise shouldn't cost the call.
        with open(dest, "wb") as fh:
            fh.write(raw)
        time.sleep(THROTTLE)
        return json.loads(raw), False


def team_index(client, refresh=False):
    """{alias: team_id} for all 32 teams."""
    data, cached = client.get("league/hierarchy.json", "league_hierarchy.json", refresh)
    teams = {}
    for conf in data.get("conferences", []):
        for div in conf.get("divisions", []):
            for team in div.get("teams", []):
                teams[team["alias"]] = team["id"]
    print(f"  {'cached ' if cached else 'fetched'} league hierarchy - {len(teams)} teams")
    return teams


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    ap.add_argument("--level", default="production", choices=("production", "trial"))
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    client = Client(load_key(), level=args.level)
    print(f"Sportradar NFL v7 ({args.level})\n")

    teams = team_index(client, args.refresh)
    if len(teams) != 32:
        print(f"  WARNING: expected 32 teams, got {len(teams)}")
    print(f"\nSeasonal statistics ({len(args.seasons)} seasons "
          f"x {len(teams)} teams = {len(args.seasons) * len(teams)} calls):")

    hits = misses = 0
    for season in args.seasons:
        fetched_this_season = 0
        for alias in sorted(teams):
            _, cached = client.get(
                f"seasons/{season}/REG/teams/{teams[alias]}/statistics.json",
                os.path.join(str(season), f"{alias}.json"),
                args.refresh,
            )
            hits += cached
            misses += not cached
            fetched_this_season += not cached
        state = "all cached" if not fetched_this_season else f"{fetched_this_season} fetched"
        print(f"  {season} REG - {len(teams)} teams ({state})")

    print(f"\n{misses} fetched, {hits} already cached "
          f"({client.calls} API calls this run)")
    print(f"Cache: {CACHE}")


if __name__ == "__main__":
    sys.exit(main())
