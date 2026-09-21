"""Auto-discover SFB16 draft sources for compile_sleeper_adp.py, instead of
hand-collecting draft/league IDs.

Every SFB16 league is commissioned under the Sleeper username
"ScottFishBowl" and has "SFB16" in its league name. This script:
  1. Resolves that username to a user_id.
  2. Pulls every one of their NFL leagues for the given season (one API
     call covers all ~400 leagues — cheap).
  3. Filters to leagues with "SFB16" in the name.
  4. Checks each league's draft status, keeping ones that are "complete" OR
     "drafting" (in progress) — Sleeper's picks endpoint returns whatever
     picks have happened so far even mid-draft, so a live draft still
     contributes real signal. Pure "pre_draft" leagues are skipped.
  5. Appends any newly-found drafts to sleeper_draft_sources.csv (skips
     draft_ids already present). Once a draft_id is in the source list,
     re-running compile_sleeper_adp.py always re-fetches its current picks,
     so an in-progress draft naturally gets more complete as it goes — no
     need to touch this script again for a draft already added.

All SFB16 leagues already exist (none get created later) — only their
draft status changes over time. Checking status is the expensive part: one
API call per league, ~400 calls total if done for every league every run.
`league_status_cache.json` avoids that: once a league's draft is seen as
"complete", that's permanent — it's cached and never re-checked again on
later runs. Only leagues still `pre_draft`/`drafting` (which can still
change) get re-queried each time, so the number of API calls this script
makes shrinks as more leagues finish drafting over the season.

After running this, run compile_sleeper_adp.py to recompute ADP from the
current source list.
"""
import csv
import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
SOURCES_CSV = BASE / "sleeper_draft_sources.csv"
STATUS_CACHE = BASE / "league_status_cache.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (personal use, fantasy football research)"}
COMMISSIONER_USERNAME = "ScottFishBowl"
LEAGUE_NAME_FILTER = "SFB16"
RELEVANT_STATUSES = {"complete", "drafting"}

BATCH_SIZE = 50      # pause briefly every N uncached draft checks
BATCH_PAUSE = 2.0    # seconds between batches
MAX_RETRIES = 3      # retry each request up to this many times


def _get_json(url):
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"  [retry {attempt+1}/{MAX_RETRIES}] {e} — waiting {wait}s...")
            time.sleep(wait)


def find_sfb16_leagues(season):
    user = _get_json(f"https://api.sleeper.app/v1/user/{COMMISSIONER_USERNAME}")
    user_id = user["user_id"]
    leagues = _get_json(f"https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}")
    matches = [lg for lg in leagues if LEAGUE_NAME_FILTER.lower() in (lg.get("name") or "").lower()]
    print(f"Found {len(leagues)} total leagues for {COMMISSIONER_USERNAME}, "
          f"{len(matches)} with {LEAGUE_NAME_FILTER!r} in the name")
    return matches


def load_status_cache():
    if not STATUS_CACHE.exists():
        return {}
    return json.loads(STATUS_CACHE.read_text())


def save_status_cache(cache):
    STATUS_CACHE.write_text(json.dumps(cache, indent=2))


def relevant_drafts(leagues):
    cache = load_status_cache()
    found = []
    pre_draft = 0
    checked = 0
    skipped = 0
    for lg in leagues:
        draft_id = lg.get("draft_id")
        if not draft_id:
            continue

        cached_status = cache.get(draft_id)
        if cached_status == "complete":
            status = "complete"
            skipped += 1
        else:
            draft = _get_json(f"https://api.sleeper.app/v1/draft/{draft_id}")
            status = draft.get("status")
            cache[draft_id] = status
            checked += 1
            if checked % BATCH_SIZE == 0:
                save_status_cache(cache)  # save progress in case of later failure
                print(f"  [{checked} checked so far, pausing {BATCH_PAUSE}s...]")
                time.sleep(BATCH_PAUSE)

        if status in RELEVANT_STATUSES:
            note = f"{lg.get('name', '')} ({status})"
            found.append((draft_id, note))
        else:
            pre_draft += 1

    save_status_cache(cache)
    complete_n = sum(1 for _, n in found if n.endswith("(complete)"))
    drafting_n = len(found) - complete_n
    print(f"{complete_n} draft(s) complete, {drafting_n} in progress, {pre_draft} not yet started "
          f"({checked} status checks made, {skipped} skipped via cache)")
    return found


def load_existing_ids():
    if not SOURCES_CSV.exists() or SOURCES_CSV.stat().st_size == 0:
        return set()
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        return {row["id"] for row in csv.DictReader(f) if row.get("id")}


def append_new_sources(found):
    existing_ids = load_existing_ids()
    new_rows = [(draft_id, note) for draft_id, note in found if draft_id not in existing_ids]

    if not new_rows:
        print("No new drafts to add.")
        return

    file_exists = SOURCES_CSV.exists() and SOURCES_CSV.stat().st_size > 0
    with open(SOURCES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["type", "id", "note"])
        for draft_id, note in new_rows:
            w.writerow(["draft", draft_id, note])

    print(f"Appended {len(new_rows)} new draft(s) to {SOURCES_CSV}")


if __name__ == "__main__":
    import sys
    season = sys.argv[1] if len(sys.argv) > 1 else "2026"

    leagues = find_sfb16_leagues(season)
    found = relevant_drafts(leagues)
    append_new_sources(found)
