#!/usr/bin/env python3
"""Fetch the Sleeper NFL player blob into cached/.

Sleeper's `/v1/players/nfl` is public, needs no auth, and is the most current
roster/injury source we have — it's a fantasy platform, so being days behind on
a signing or an IR designation would be a product failure for them. As of the
2026 preseason it carried a Diggs->WAS signing, Pearsall's IR (Knee-PCL), and
Aiyuk's DNR (Knee ACL+MCL) that nflverse had none of.

It is a ~10MB response covering every player in their database, so Sleeper asks
that it be pulled at most once per day. Cached accordingly.

Usage:
    python fetch_sleeper.py            # skip if today's copy exists
    python fetch_sleeper.py --refresh  # force
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cached", "sleeper")
URL = "https://api.sleeper.app/v1/players/nfl"

UA = {"User-Agent": "Mozilla/5.0 (ff_projections; personal use)"}


def cache_path(day=None):
    day = day or datetime.date.today().isoformat()
    return os.path.join(CACHE, f"players_nfl_{day}.json")


def latest_cached():
    """Most recent cached copy, or None."""
    if not os.path.isdir(CACHE):
        return None
    files = sorted(f for f in os.listdir(CACHE)
                   if f.startswith("players_nfl_") and f.endswith(".json"))
    return os.path.join(CACHE, files[-1]) if files else None


def fetch(refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    dest = cache_path()
    if os.path.exists(dest) and not refresh:
        print(f"  cached  {os.path.basename(dest)}")
        return dest
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read()
    with open(dest, "wb") as fh:
        fh.write(raw)
    print(f"  fetched {os.path.basename(dest)}  ({len(raw) // 1024:,} KB)")
    return dest


def load(path=None):
    """Load the cached blob. Falls back to the most recent copy on disk."""
    path = path or cache_path()
    if not os.path.exists(path):
        path = latest_cached()
    if not path:
        sys.exit("No Sleeper cache. Run fetch_sleeper.py first.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh), path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    path = fetch(args.refresh)
    players, _ = load(path)

    skill = [p for p in players.values()
             if p.get("team") and p.get("position") in ("QB", "RB", "FB", "WR", "TE")]
    newest = max((p.get("news_updated") or 0) for p in skill)
    stamp = datetime.datetime.fromtimestamp(newest / 1000, datetime.timezone.utc)

    print(f"\n  {len(players):,} players total, {len(skill)} skill players on a roster")
    print(f"  most recent player news: {stamp:%Y-%m-%d %H:%M} UTC")
    print(f"\nCache: {CACHE}")


if __name__ == "__main__":
    sys.exit(main())
