#!/usr/bin/env python3
"""
Locally captured boards, for sources with no fetchable API.

Some analysts can't be pulled on a schedule. Jahnke's weekly rankings are PFF+
premium (nothing usable renders logged out, and the tool calls no data endpoint
without a session), and Thorman has no route yet. But a board captured by hand
is still a real board -- it just needs an honest timestamp attached so the
freshness gate can judge it like any other source.

One JSON file per source per week:

    weekly/<year>-wk<NN>/cached/<prefix>.json
    {
      "source": "Nathan Jahnke",
      "origin": "PFF",
      "boards": {
        "HALF": {"FLX": [{"Player":..,"Team":..,"Position":..}], "RB": [...]},
        "PPR":  {...},
        "STD":  {...},
        "ANY":  {"QB": [...]}
      },
      "timestamps": {
        "HALF": {"published_at": "2026-09-11T14:56:00-04:00", "captured_at": "..."},
        "PPR":  {"published_at": "2026-09-06T20:28:00-04:00", "captured_at": "..."},
        "STD":  {"published_at": "2026-09-06T20:28:00-04:00", "captured_at": "..."},
        "ANY":  {"published_at": "2026-09-11T14:56:00-04:00", "captured_at": "..."}
      }
    }

Boards are keyed by scoring FIRST, because a source can publish genuinely
different lists per format -- verified for Jahnke on 2026-09-07, whose FLX board
hashes differently in all three. Keying this way makes it structurally
impossible to serve a PPR board as Standard; there is no scoring check to
forget.

**Timestamps are keyed the SAME way, one per scoring block, not one for the
whole file.** An earlier version had a single file-wide `published_at` --
verified broken live 2026-09-11: refreshing only Jahnke's HALF boards through
the browser stamped that capture's timestamp onto his PPR/STD boards too, even
though their real content was still six days old from the original capture and
never touched again. That made stale PPR/STD data look freshly current in
`run_weekly.py`'s comparison against FP, silently. The fix is symmetric with
how `boards` already works: `board_for()` looks up entries and their timestamp
from the SAME key, so a format's freshness can never borrow another format's
capture time.

"ANY" holds format-invariant slots. QB/K/DST carry no receptions, so their lists
are identical across formats -- verified for Jahnke (same MD5 across all three
PFF exports) and for Koerner on FantasyPros. A slot captured under a specific
format is still offered for an invariant slot request, since the format made no
difference to it.

`published_at` is preferred for freshness when present, because that is the
question the gate actually asks -- when did the analyst last change this? -- and
it is not flattered by having been read late. `captured_at` is the fallback, and
is deliberately NOT the file's mtime: copying or syncing a file must not make a
stale board look fresh.
"""

import datetime
import glob
import json
import os

import weekly_freshness as wf

CACHE_DIRNAME = "cached"


def cache_dir(week_dir):
    return os.path.join(week_dir, CACHE_DIRNAME)


def load_all(week_dir):
    """{prefix: payload} for every cached source of this week."""
    out = {}
    for path in sorted(glob.glob(os.path.join(cache_dir(week_dir), "*.json"))):
        prefix = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"WARNING: ignoring unreadable cache {path}: {exc}")
            continue
        payload = _migrate(payload)
        if not payload:
            print(f"WARNING: ignoring {path}: no readable boards")
            continue
        out[prefix] = payload
    return out


def _migrate(payload):
    """Accept older shapes: the flat {scoring, lists} form, and the form with
    one file-wide published_at/captured_at instead of per-scoring ones.

    A file-wide timestamp can't be split into true per-format values after
    the fact -- if it was already overwritten by a later single-format
    capture, the original per-format time is gone, not recoverable here. This
    only keeps old files loading; it does not repair lost precision. Best
    effort: apply the file-wide value to every scoring key present.
    """
    if isinstance(payload.get("lists"), dict) and not isinstance(
            payload.get("boards"), dict):
        scoring = (payload.get("scoring") or "HALF").upper()
        boards = {}
        for slot, rows_in in payload["lists"].items():
            key = "ANY" if slot in wf.FORMAT_INVARIANT_SLOTS else scoring
            boards.setdefault(key, {})[slot] = rows_in
        payload = dict(payload)
        payload["boards"] = boards

    if not isinstance(payload.get("boards"), dict):
        return None

    if not isinstance(payload.get("timestamps"), dict):
        shared = {"published_at": payload.get("published_at"),
                  "captured_at": payload.get("captured_at")}
        payload = dict(payload)
        payload["timestamps"] = {key: dict(shared) for key in payload["boards"]}

    return payload


def _parse(text):
    if not text:
        return None
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=wf.ET)
    return int(when.timestamp())


def _keys_for(slot, scoring):
    """Which `boards`/`timestamps` key(s) can answer this (slot, scoring)
    request, in preference order -- mirrors the FP/FTN origin preference:
    the exact format-invariant bucket first, then whichever real format
    happens to have it.
    """
    if slot in wf.FORMAT_INVARIANT_SLOTS:
        return ["ANY", "HALF", "PPR", "STD"]
    return [scoring]


def board_for(payload, slot, scoring):
    """(rows, epoch_or_None) for one (slot, scoring) -- the two ALWAYS come
    from the same scoring key, so a format's freshness can never be reported
    using a different format's capture time.

    Format-specific slots are only ever read from their own format, so a PPR
    board can never be served as Standard.
    """
    boards = payload.get("boards") or {}
    timestamps = payload.get("timestamps") or {}

    for key in _keys_for(slot, scoring):
        entries = (boards.get(key) or {}).get(slot)
        if not entries:
            continue
        out = []
        for entry in entries:
            name = (entry.get("Player") or entry.get("player_name") or "").strip()
            if not name:
                continue
            out.append({
                "player_name": name,
                "player_team_id": (entry.get("Team")
                                   or entry.get("player_team_id") or "FA"),
                "player_position_id": (entry.get("Position")
                                       or entry.get("player_position_id") or slot),
            })
        ts = timestamps.get(key) or {}
        epoch = _parse(ts.get("published_at")) or _parse(ts.get("captured_at"))
        return out, epoch

    return [], None


def slot_summary(payload):
    """(scoring, slot) pairs this source has, for logging."""
    return sorted((sc, slot) for sc, slots in (payload.get("boards") or {}).items()
                  for slot in slots)


def staleness(payload, max_age_hours=12.0, now_et=None):
    """{key: (age_hours, is_stale)} for every scoring key this source has.

    Age-only: this can't know whether the analyst's site has published
    something newer (that needs a live check, e.g. a browser), so it only
    catches the "nobody's looked at this in a while" case. is_stale is True
    once a key's timestamp is older than max_age_hours -- the same threshold
    Joe uses for deciding whether a PFF re-capture is worth doing.
    """
    now_et = now_et or datetime.datetime.now(wf.ET)
    out = {}
    for key, ts in (payload.get("timestamps") or {}).items():
        epoch = _parse(ts.get("published_at")) or _parse(ts.get("captured_at"))
        if epoch is None:
            out[key] = (None, True)
            continue
        age_hours = (now_et.timestamp() - epoch) / 3600
        out[key] = (age_hours, age_hours > max_age_hours)
    return out


def write(week_dir, prefix, source, origin, boards, timestamps):
    """Save captured boards. `boards` and `timestamps` are both keyed the
    same way: {scoring_or_ANY: ...}. Callers merge with any existing file
    themselves (see import_cached_board.py) so importing one format doesn't
    erase another's boards OR its timestamp.
    """
    directory = cache_dir(week_dir)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{prefix}.json")
    payload = {
        "source": source,
        "origin": origin,
        "boards": {sc: {slot: list(rows_in) for slot, rows_in in slots.items()}
                   for sc, slots in boards.items()},
        "timestamps": {sc: dict(ts) for sc, ts in timestamps.items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path
