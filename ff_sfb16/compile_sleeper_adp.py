"""Compile ADP for the SFB16 cheat sheet from real Sleeper drafts (completed
mocks + actual league drafts), instead of a multi-source consensus. SFB16
uses one ADP source only — average pick number across the drafts listed in
sleeper_draft_sources.csv.

sleeper_draft_sources.csv columns:
  type  - "draft" or "league"
  id    - the Sleeper draft_id, or league_id (for "league" rows, every
          completed draft under that league is included)
  note  - free text, ignored by the script (your own reference)

Add rows to that CSV as you collect more drafts/mocks, then re-run this
script — it always recomputes from the full current list.

Writes sleeper_compiled_adp.csv: Player, Position, Team, ADP, Drafts Counted.
ADP = average overall pick number across every draft the player was
selected in (drafts where they weren't picked don't count against them —
standard "average when drafted" ADP, not a penalized one).
"""
import csv
import json
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
SOURCES_CSV = BASE / "sleeper_draft_sources.csv"
PLAYERS_CACHE = BASE / "sleeper_players_cache.json"
OUTPUT_CSV = BASE / "sleeper_compiled_adp.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (personal use, fantasy football research)"}
KEEP_POS = {"QB", "RB", "WR", "TE", "DEF"}


def _get_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def load_sources():
    if not SOURCES_CSV.exists() or SOURCES_CSV.stat().st_size == 0:
        return []
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("id")]


def resolve_draft_ids(sources):
    draft_ids = []
    for row in sources:
        kind = (row.get("type") or "").strip().lower()
        source_id = row.get("id", "").strip()
        if not source_id:
            continue
        if kind == "draft":
            draft_ids.append(source_id)
        elif kind == "league":
            drafts = _get_json(f"https://api.sleeper.app/v1/league/{source_id}/drafts")
            for d in drafts:
                if d.get("status") == "complete":
                    draft_ids.append(d["draft_id"])
        else:
            print(f"  Skipping row with unknown type {kind!r}: {row}")
    return list(dict.fromkeys(draft_ids))  # de-dupe, preserve order


def load_player_directory():
    """Sleeper's full player_id -> name/position/team map. Cached locally —
    it's a multi-MB file that changes rarely."""
    if PLAYERS_CACHE.exists():
        return json.loads(PLAYERS_CACHE.read_text())
    print("Downloading Sleeper player directory (one-time, ~5MB)...")
    data = _get_json("https://api.sleeper.app/v1/players/nfl")
    PLAYERS_CACHE.write_text(json.dumps(data))
    return data


def compile_adp(draft_ids, player_dir):
    pick_lists = {}  # player_id -> list of pick_no
    counted = 0
    for draft_id in draft_ids:
        picks = _get_json(f"https://api.sleeper.app/v1/draft/{draft_id}/picks")
        if not picks:
            print(f"  Draft {draft_id}: no picks found, skipping")
            continue
        counted += 1
        for pick in picks:
            player_id = pick.get("player_id")
            pick_no = pick.get("pick_no")
            if player_id is None or pick_no is None:
                continue
            pick_lists.setdefault(player_id, []).append(pick_no)
        print(f"  Draft {draft_id}: {len(picks)} picks")

    rows = []
    for player_id, picks in pick_lists.items():
        info = player_dir.get(player_id) or {}
        pos = (info.get("position") or "").strip().upper()
        if pos not in KEEP_POS:
            continue
        first = (info.get("first_name") or "").strip()
        last = (info.get("last_name") or "").strip()
        name = f"{first} {last}".strip() or info.get("full_name") or player_id
        rows.append({
            "Player": name,
            "Position": "DST" if pos == "DEF" else pos,
            "Team": (info.get("team") or "").strip() or "FA",
            "ADP": round(sum(picks) / len(picks), 2),
            "Drafts Counted": len(picks),
        })

    rows.sort(key=lambda r: r["ADP"])
    return rows, counted


def main():
    sources = load_sources()
    if not sources:
        print(f"No sources in {SOURCES_CSV} yet — add draft/league rows and re-run.")
        return

    print(f"Resolving {len(sources)} source row(s)...")
    draft_ids = resolve_draft_ids(sources)
    print(f"Resolved to {len(draft_ids)} draft(s): {draft_ids}")

    player_dir = load_player_directory()
    rows, counted = compile_adp(draft_ids, player_dir)

    if not rows:
        print("No picks found across any draft — nothing written.")
        return

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Player", "Position", "Team", "ADP", "Drafts Counted"])
        w.writeheader()
        w.writerows(rows)

    print(f"Compiled ADP from {counted} draft(s) with picks -> {len(rows)} players -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
