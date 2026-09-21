#!/usr/bin/env python3
"""
FTN as a weekly-rankings fallback for Ratcliffe and Orginski.

FTN's rankings tool has a rank-type dropdown; the redraft view that
`fetch_ftn_rankings.py` uses is `/api/rankings/redraft`, and the weekly view is
the same endpoint with `weekly` in its place. Verified 2026-09-07: it needs the
same login and returns 200 with real data.

The weekly payload is shaped DIFFERENTLY from redraft, which matters:

    redraft -> {"PPR": [...], "Half": [...], "Std": [...], "SF": [...],
                "timestamps": {...}}          # each list is the whole board
    weekly  -> {"PPR": [...], "Half": [...], "Std": [...],
                "QB": [...], "K": [...], "DST": [...], "timestamps": {...}}

In the weekly payload the scoring keys hold the **FLEX** board (RB/WR/TE only,
~348 players) and QB/K/DST are separate lists. There are no per-position RB/WR/TE
lists, so those are derived by filtering the flex board and renumbering -- the
same thing `fetch_ftn_rankings.py` does for redraft, and it has a useful side
effect here: a flex derived this way agrees with its own position lists by
construction, so `reconcile_flex` finds nothing to fix.

Why this is worth having beyond "a backup": FTN publishes a precise submission
datetime per analyst per ranking set (`timestamps`), e.g. Ratcliffe
"9/7/2026 15:36:02". FantasyPros only exposes a timestamp for experts it lists
in its own panel, and as of 2026-09-02 neither Ratcliffe nor Orginski appeared
on any FP panel page. So for these two, FTN is both the more reliable source and
the only precise freshness signal.
"""

import datetime
import re

import requests

import ftn_auth
import name_match
import weekly_freshness as wf

DATA_URL = "https://ls.ftnfantasy.com/api/rankings/weekly"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}

# Scoring format -> the payload key holding that format's FLEX board.
FLEX_KEY = {"HALF": "Half", "PPR": "PPR", "STD": "Std"}
# Slots FTN publishes as their own list rather than inside the flex board.
STANDALONE_KEY = {"QB": "QB", "K": "K", "DST": "DST"}

# FTN ranks a handful of fullbacks; FP has no FB slot and treats them as backs.
POSITION_ALIASES = {"FB": "RB"}

_TS = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4}),?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")


def fetch(session=None):
    """The whole weekly payload. One request covers every format and slot."""
    token = ftn_auth.get_access_token()
    headers = dict(HEADERS, Authorization=f"Bearer {token}")
    get = (session or requests).get
    resp = get(DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_timestamp(text):
    """FTN's 'M/D/YYYY H:MM:SS' (comma optional) -> epoch seconds, ET.

    Returns None for the blank strings FTN uses for analysts who never
    submitted a set -- those must not be read as "very old", they are absent.
    """
    if not text:
        return None
    m = _TS.match(text)
    if not m:
        return None
    month, day, year, hour, minute, second = m.groups()
    dt = datetime.datetime(
        int(year), int(month), int(day), int(hour), int(minute),
        int(second or 0), tzinfo=wf.ET)
    return int(dt.timestamp())


def submitted_at(data, analyst, scoring, slot):
    """When `analyst` last saved the ranking set behind this (slot, scoring)."""
    key = STANDALONE_KEY.get(slot) or FLEX_KEY.get(scoring, "Half")
    block = (data.get("timestamps") or {}).get(key) or {}
    return parse_timestamp(block.get(analyst))


def _rows(players, analyst):
    """FTN players an analyst actually ranked, in that analyst's order."""
    ranked = []
    for p in players:
        rank = (p.get("rankings") or {}).get(analyst)
        if rank in (None, ""):
            continue
        pos = p.get("position") or ""
        ranked.append((
            float(rank),
            {
                "player_name": (p.get("name") or "").strip(),
                "player_team_id": name_match.clean_team(p.get("team") or ""),
                "player_position_id": POSITION_ALIASES.get(pos, pos),
            },
        ))
    ranked.sort(key=lambda t: t[0])
    return [rec for _rank, rec in ranked]


def analyst_list(data, analyst, slot, scoring):
    """One (slot, scoring) list for one analyst, in the FP API's row shape.

    Returns [] when the analyst didn't rank that set, so a caller can treat it
    the same way it treats an FP source with nothing submitted.
    """
    if slot in STANDALONE_KEY:
        return _rows(data.get(STANDALONE_KEY[slot]) or [], analyst)

    flex = _rows(data.get(FLEX_KEY.get(scoring, "Half")) or [], analyst)
    if slot == "FLX":
        return flex
    if slot in ("RB", "WR", "TE"):
        # No per-position lists on FTN -- filter the flex board and renumber.
        return [r for r in flex if r["player_position_id"] == slot]
    return []


def available_analysts(data):
    """Analysts with at least one non-blank timestamp in the weekly payload."""
    found = set()
    for block in (data.get("timestamps") or {}).values():
        for key, value in block.items():
            if key != "RankingSet" and parse_timestamp(value):
                found.add(key)
    return sorted(found)


if __name__ == "__main__":
    payload = fetch()
    print("analysts with weekly submissions:", available_analysts(payload))
    for who in ("Ratcliffe", "Orginski"):
        print(f"\n{who}:")
        for slot in ("FLX", "QB", "RB", "WR", "TE"):
            rows = analyst_list(payload, who, slot, "HALF")
            stamp = submitted_at(payload, who, "HALF", slot)
            when = (wf.to_et(stamp).strftime("%a %m/%d %I:%M %p")
                    if stamp else "no timestamp")
            print(f"  {slot:4s} {len(rows):>4d} players   saved {when}")
