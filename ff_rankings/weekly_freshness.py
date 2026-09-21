#!/usr/bin/env python3
"""
Per-expert freshness for FantasyPros' WEEKLY rankings.

Shared by the slate sampler (`sample_weekly_freshness.py`) and, later, the
weekly pipeline's source gate. Nothing here touches the season-long/preseason
files -- it is read-only against FP's public rankings pages.

Why this exists
---------------
The partner API's own `last_updated` is date-only ("11/09"), which cannot
answer the only question that matters before a lock: has this analyst touched
their board since the cutoff (12:30 PM ET Sunday, 6 PM ET Thursday)? Every
weekly rankings page instead embeds `var expertGroupsData` whose `expert_data[]`
entries carry `last_updated` as a **unix epoch** -- exact, machine-readable, and
scoped to that one (week, position, scoring) list. That epoch is the primary
freshness signal; `fingerprint_expert_list` is the fallback for sources FP
omits from its panel.

Three limits on the epoch, all real:
  1. It records the last time the expert SAVED the list. An expert who
     reviewed their board and decided nothing needed to change looks identical
     to one who never looked. A strict cutoff is therefore biased toward
     analysts who churn their lists, not necessarily the most accurate ones.
  2. Inactives are official 90 minutes before each game, so a 1 PM-slate
     cutoff says nothing about the late-window and night games a FLX list also
     covers.
  3. It only exists for experts currently in FP's panel -- four of the seven
     sources were absent from every panel page on 2026-09-02.

Slots
-----
FLX is **pulled natively** from FP for weekly (`position=FLX`, ~300 players per
analyst); nothing here builds or derives it. `reconcile_flex` exists for a
different reason -- see its docstring.

The pre-lock run covers FLX/QB/RB/WR/TE: 5 lists per scoring format, 13 across
all three (QB is format-invariant and submitted once). K and DST are published
from a different analyst pool on a slower cadence and are deliberately outside
this path.

Page map
--------
Every list has its own page, and each page self-identifies via `var ecrData`
(year/week/position_id/scoring) -- so the mapping below is verified at runtime,
not assumed. QB/K/DST appear only as Standard pages because those lists are
byte-identical across HALF/PPR/STD (verified on Koerner's 2025 week 5/10/15
boards).
"""

import datetime
import hashlib
import json
import os
import random
import re
import time
import zoneinfo

import requests

ET = zoneinfo.ZoneInfo("America/New_York")
BASE = "https://www.fantasypros.com/nfl/rankings/"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}


def _bust(params=None):
    """Query params plus a unique nonce, to force a cache MISS.

    FantasyPros' rankings pages and the consensus-rankings.php API sit behind
    CloudFront with `max-age=1200` (20 min) / `max-age=600` (10 min) -- verified
    2026-09-09 by comparing headers across three access paths and confirming
    with a cache-busted request that they all echo the identical origin
    timestamp. Nothing is at stake early in the week, when rankings genuinely
    aren't changing -- but in the minutes before a lock they can and do change,
    and a request that happens to land on an already-warm cache entry can
    silently hand back a board from up to 20 minutes ago. That is exactly
    backwards for a freshness gate whose entire job is telling FRESH from STALE
    to the minute: it would false-negative a source that DID update in time,
    just because the read landed on a stale cache hit rather than the origin.
    Confirmed the risk is live, not theoretical: an unbusted call during
    ordinary (quiet) conditions came back `Age: 1186` -- 19+ minutes old, close
    to the full 20-minute ceiling. FTN carries no such caching (checked
    2026-09-09, no cache-control headers at all), so this is FP-only.
    """
    out = dict(params or {})
    out["_"] = str(time.time_ns())
    return out


# (slot, scoring) -> page. Scoring "ANY" = format-invariant list, submit once.
LIST_PAGES = {
    ("QB",  "ANY"):  "qb.php",
    ("K",   "ANY"):  "k.php",
    ("DST", "ANY"):  "dst.php",
    ("RB",  "HALF"): "half-point-ppr-rb.php",
    ("RB",  "PPR"):  "ppr-rb.php",
    ("RB",  "STD"):  "rb.php",
    ("WR",  "HALF"): "half-point-ppr-wr.php",
    ("WR",  "PPR"):  "ppr-wr.php",
    ("WR",  "STD"):  "wr.php",
    ("TE",  "HALF"): "half-point-ppr-te.php",
    ("TE",  "PPR"):  "ppr-te.php",
    ("TE",  "STD"):  "te.php",
    ("FLX", "HALF"): "half-point-ppr-flex.php",
    ("FLX", "PPR"):  "ppr-flex.php",
    ("FLX", "STD"):  "flex.php",
}

# Slots that matter on the clock, in the order Joe pastes them into the FP
# expert portal. FLX goes FIRST because submitting a position list makes FP
# slightly reorder the flex -- it enforces that the flex agrees with the
# position lists on within-position order. So the published flex ends up as:
# cross-position interleaving from the FLX paste (which no position list
# contains), within-position order from the position pastes. See reconcile_flex.
SLATE_SLOT_ORDER = ["FLX", "QB", "RB", "WR", "TE"]

# K and DST are published too, but from a DIFFERENT set of analysts and only
# refreshed a couple of times a week -- they are not part of the pre-lock run
# and are not freshness-gated against a slate cutoff. Their source pool is
# deliberately left unset until Joe names it; nothing should silently blend the
# skill-position sources into a kicker board.
OCCASIONAL_SLOT_ORDER = ["K", "DST"]
OCCASIONAL_SOURCE_PRIORITY = []          # TODO: Joe's K/DST analysts

# Format-invariant slots: byte-identical across HALF/PPR/STD (verified on
# Koerner's 2025 week 5/10/15 boards), so they are submitted once.
FORMAT_INVARIANT_SLOTS = {"QB", "K", "DST"}


def paste_order(scoring):
    """(slot, scoring) pairs in paste order for one format, pre-lock slots only.

    K/DST are excluded -- see OCCASIONAL_SLOT_ORDER.
    """
    return [(slot, "ANY" if slot in FORMAT_INVARIANT_SLOTS else scoring)
            for slot in SLATE_SLOT_ORDER]


def slate_lists(scoring=None):
    """Every (slot, scoring) the pre-lock run needs.

    With no `scoring`, returns all formats: FLX/RB/WR/TE x HALF/PPR/STD plus
    QB once = 13 lists. For a single format it is 5, which is what fits in the
    minutes between a 12:55 run and a 1 PM lock.
    """
    scorings = [scoring] if scoring else ["HALF", "PPR", "STD"]
    out = []
    for sc in scorings:
        for slot, slot_scoring in paste_order(sc):
            if (slot, slot_scoring) not in out:
                out.append((slot, slot_scoring))
    return out


# The half-PPR set Joe publishes first when the clock is tight (5 lists).
HALF_PPR_LISTS = [("FLX", "HALF"), ("QB", "ANY"), ("RB", "HALF"),
                  ("WR", "HALF"), ("TE", "HALF")]


# In-season source pool, best first. The pool is deliberately larger than
# MAX_SOURCES: the run takes the highest-priority sources that are actually
# FRESH for a given list, so the extras are depth against a slow Sunday, not
# additional blend members. Verified 2026-09-02: every id below returned a real
# single-expert weekly list (total_experts=1) for 2025 week 10.
# `ftn_analyst` names the FTN key (last name) where that source is ALSO
# published on FTN -- worth preferring early in the week, because FTN gives a
# precise submission datetime directly rather than depending on FP listing the
# expert in its panel. `no_std` marks a source that never submits a Standard
# board: verified for Boone across 2025 weeks 10 and 12 (0 players for every
# STD list, same as his draft rankings). He is skipped for STD and the next
# priority source takes the slot -- see CLAUDE.md for why that beats deriving
# one from his half-PPR board.
SOURCE_PRIORITY = [
    {"prefix": "boone",     "label": "Justin Boone",    "ids": [317],
     "no_std": True},
    {"prefix": "thorman",   "label": "Patrick Thorman", "ids": [534]},
    {"prefix": "ratcliffe", "label": "Jeff Ratcliffe",  "ids": [125],
     "ftn_analyst": "Ratcliffe"},
    {"prefix": "koerner",   "label": "Sean Koerner",    "ids": [120]},
    {"prefix": "tylero",    "label": "Tyler Orginski",  "ids": [2729],
     "ftn_analyst": "Orginski"},
    {"prefix": "jahnke",    "label": "Nathan Jahnke",   "ids": [540]},
    {"prefix": "deldon",    "label": "Dalton Del Don",  "ids": [285]},
]


def sources_for(scoring):
    """Priority-ordered sources eligible for a scoring format.

    Drops sources that never submit that format, so the caller's top-N is
    taken from analysts who actually have a board rather than silently
    blending a gap.
    """
    if scoring == "STD":
        return [s for s in SOURCE_PRIORITY if not s.get("no_std")]
    return list(SOURCE_PRIORITY)


# How many sources actually go into a blended list. See the 4-vs-6 note in
# CLAUDE.md -- more sources cuts noise but converges toward FP's own consensus,
# and these analysts are highly correlated, so 5 and 6 buy very little.
MAX_SOURCES = 4

TRACKED_EXPERTS = {
    eid: s["label"] for s in SOURCE_PRIORITY for eid in s["ids"]
}
SOURCE_RANK = {
    eid: i for i, s in enumerate(SOURCE_PRIORITY) for eid in s["ids"]
}

# Per-slate publish timing, all ET. `cutoff` is the freshness line: a source
# that hasn't re-saved a list at/after this time is not counted for that list.
#
# The cutoffs are Joe's, not derived -- they reflect how late he is willing to
# trust a board relative to lock, and they are NOT a fixed offset from kickoff
# (Thursday allows a 2h15m-old board, Sunday only 30m). Wednesday/Friday
# one-offs are rare and low-stakes; they default to the Sunday shape and are
# meant to be overridden per game with --kickoff/--cutoff rather than edited.
SLATES = {
    "THU": {"kickoff": datetime.time(20, 15),
            "run_at":  datetime.time(20, 10),
            "cutoff":  datetime.time(18, 0)},
    "SUN": {"kickoff": datetime.time(13, 0),
            "run_at":  datetime.time(12, 55),
            "cutoff":  datetime.time(12, 30)},
    "WED": {"kickoff": datetime.time(20, 15),
            "run_at":  datetime.time(20, 10),
            "cutoff":  datetime.time(19, 45)},
    "FRI": {"kickoff": datetime.time(15, 0),
            "run_at":  datetime.time(14, 55),
            "cutoff":  datetime.time(14, 30)},
}

WEEKDAY_SLATE = {2: "WED", 3: "THU", 4: "FRI", 6: "SUN"}

# Fallback when a run happens on a day with no configured slate.
DEFAULT_CUTOFF = SLATES["SUN"]["cutoff"]


# ---------------------------------------------------------------------------
# Freshness policy: how new a board has to be, given where we are in the week
# ---------------------------------------------------------------------------
# One concept, not four: a run has a THRESHOLD DATETIME, and a source counts
# only if it saved that list at/after it. The threshold moves through the week:
#
#   Tue -> Thu 6 PM      no threshold. Nothing has kicked off; an old board is
#                        still this week's board.
#   Thu 6 PM -> 8:15 PM  Thursday 6 PM. The TNF lock -- Joe's stated line.
#   Thu 8:15 PM -> Sun   Thursday's kickoff. Mild: a board that still predates
#                        TNF hasn't accounted for Thursday's games.
#   Sun 12:30 PM on      Sunday 12:30 PM. The main lock.
#
# Deriving the threshold from a real moment (a kickoff, a lock) rather than a
# bare clock time also kills a trap: a fixed "12:30 PM" cutoff evaluated at
# 10 AM Sunday can never be satisfied, so every source fails and the run looks
# broken. Here the strict window simply hasn't started yet at 10 AM.

TNF_KICKOFF = datetime.time(20, 15)
TNF_LOCK_CUTOFF = datetime.time(18, 0)
SUNDAY_LOCK_CUTOFF = datetime.time(12, 30)

MONDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = 0, 3, 4, 5, 6


def _at(now_et, weekday, when):
    """The given time on the named weekday of now_et's own Mon-Sun week."""
    day = now_et.date() - datetime.timedelta(days=now_et.weekday() - weekday)
    return datetime.datetime.combine(day, when, tzinfo=ET)


def freshness_threshold(now_et=None):
    """(phase, threshold_datetime_or_None, one-line explanation).

    A source's list must have been saved at/after `threshold` to count. None
    means no freshness requirement at all.
    """
    now_et = now_et or datetime.datetime.now(ET)
    wd = now_et.weekday()
    thu_lock = _at(now_et, THURSDAY, TNF_LOCK_CUTOFF)
    thu_kick = _at(now_et, THURSDAY, TNF_KICKOFF)
    sun_lock = _at(now_et, SUNDAY, SUNDAY_LOCK_CUTOFF)

    if wd == SUNDAY and now_et >= sun_lock:
        return ("SUNDAY LOCK", sun_lock,
                "must be updated after 12:30 PM today, before the 1 PM lock")
    if wd == THURSDAY and thu_lock <= now_et < thu_kick:
        return ("TNF LOCK", thu_lock,
                "must be updated after 6:00 PM today, before the 8:15 PM kickoff")
    if (wd == THURSDAY and now_et >= thu_kick) or wd in (FRIDAY, SATURDAY, SUNDAY):
        return ("POST-TNF", thu_kick,
                "must be newer than Thursday night's kickoff -- a board from "
                "before TNF hasn't seen Thursday's games")
    return ("EARLY WEEK", None,
            "no freshness requirement -- nothing has kicked off yet")


def tier_since(epoch, threshold):
    """FRESH / STALE / UNKNOWN against a threshold datetime.

    `threshold` of None means everything with a board counts.
    """
    if not epoch:
        return "UNKNOWN"
    if threshold is None:
        return "FRESH"
    return "FRESH" if to_et(epoch) >= threshold else "STALE"


# Phases where FP passing the threshold is trusted without checking a backup.
# Joe's rule (2026-09-11): "When I'm inside a freshness window and FP is
# inside that, then no, I do not need to check the other source. If we are
# not inside a freshness window, then yes check the backup source and pull
# the most current one." TNF LOCK / SUNDAY LOCK are the narrow, live
# pre-lock windows this whole project is built around; CUSTOM is an explicit
# user-set deadline (--cutoff) and functions the same way. EARLY WEEK and
# POST-TNF are NOT locks -- nothing is time-critical right now, so there is
# no reason to settle for "FP cleared the bar once" over "actually the most
# current thing available." This matters concretely: POST-TNF can span 40+
# hours (Thursday's kickoff to Sunday's lock), and an FP board that passed
# right when the window opened does not stay the freshest thing forever --
# verified live 2026-09-11, Ratcliffe's FP entry (Thu 8:34 PM, correctly
# inside POST-TNF's threshold) was still being used on Friday afternoon while
# his FTN submission had moved to Fri 2:58 PM, nearly a full day fresher,
# because nothing ever re-checked it once FP had cleared the bar.
LOCK_PHASES = {"TNF LOCK", "SUNDAY LOCK", "CUSTOM"}


def is_lock_phase(phase):
    return phase in LOCK_PHASES


def slate_for(now_et=None, override=None):
    """Which slate's timing applies. Returns (name, config).

    Raises for a day with no slate unless overridden, so a stray run can't
    silently borrow someone else's cutoff.
    """
    if override:
        name = override.upper()
        if name not in SLATES:
            raise ValueError(f"Unknown slate {override!r}; expected one of "
                             f"{sorted(SLATES)}")
        return name, SLATES[name]
    now_et = now_et or datetime.datetime.now(ET)
    name = WEEKDAY_SLATE.get(now_et.weekday())
    if not name:
        raise ValueError(
            f"No slate configured for {now_et:%A}; pass an explicit slate "
            f"(one of {sorted(SLATES)}) or a --cutoff.")
    return name, SLATES[name]


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def extract_js_object(text, var_name):
    """Pull `var <var_name> = {...};` out of a page by brace matching.

    Brace matching rather than a lazy regex so a nested `};` inside the
    object can't truncate the match.
    """
    m = re.search(r"var\s+%s\s*=\s*\{" % re.escape(var_name), text)
    if not m:
        return None
    start = m.end() - 1
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return None


FP_API_KEY_ENV = "FANTASYPROS_API_KEY"
_fp_api_key_cache = None


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fp_api_key():
    """The official API key from FANTASYPROS_API_KEY, or None if unset."""
    global _fp_api_key_cache
    if _fp_api_key_cache is None:
        _load_dotenv()
        _fp_api_key_cache = os.environ.get(FP_API_KEY_ENV, "")
    return _fp_api_key_cache or None


def _nfl_season(now_et=None):
    """The season year for the official API's {season} path segment.

    The NFL season is named for the year it starts in, and this project's
    "current week" window only ever runs Sep-Jan -- so the one flip that
    matters is Jan/Feb still belonging to the PRIOR season.
    """
    now_et = now_et or datetime.datetime.now(ET)
    return now_et.year - 1 if now_et.month <= 2 else now_et.year


def _parse_api_timestamp(text):
    """The official API's "YYYY-MM-DD HH:MM:SS" strings are UTC, not ET --
    confirmed 2026-09-09 against a known epoch from the HTML scrape (Boone's
    "2026-09-08 07:51:42" ET matched the API's "2026-09-08 11:51:42" exactly,
    the correct EDT offset). Getting this wrong would silently shift every
    freshness decision by 4-5 hours, so it is parsed as UTC explicitly rather
    than assumed to share the rest of this module's ET convention.
    """
    if not text:
        return None
    try:
        dt = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())


def _fetch_list_freshness_api(slot, scoring, session=None):
    """Per-expert freshness via FantasyPros' official v2 API, if a key exists.

    Verified 2026-09-09 to be genuinely (position, scoring)-specific -- Del
    Don's RB timestamp differs by format, and Boone (who submits no Standard
    board) is correctly absent under scoring=STD. `week` is left for the API
    to default; it was confirmed to resolve to the current week on its own.
    Raises on any failure (missing key, HTTP error, unexpected shape) so the
    caller can fall back to the HTML scrape rather than silently using a
    half-parsed result.
    """
    key = fp_api_key()
    if not key:
        raise RuntimeError(f"{FP_API_KEY_ENV} not set")

    params = {"position": slot}
    if scoring != "ANY":
        params["scoring"] = scoring
    get = (session or requests).get
    url = f"https://api.fantasypros.com/public/v2/json/nfl/{_nfl_season()}/rankings/experts"

    # This is a burst/concurrency limit, not a slow quota -- verified 2026-09-10
    # by reproducing it directly: firing run_weekly.py's own 12-way concurrent
    # freshness lookups (one call per requested slot/scoring) against this
    # endpoint reliably 429s a few of them, and the API sends no Retry-After or
    # X-RateLimit-* header to size a backoff against. But the identical request
    # succeeded immediately on a bare retry, no wait required -- so a couple of
    # quick attempts clear it almost every time, well worth trying before
    # falling all the way back to the HTML scrape (still correct, just a worse
    # signal). random.uniform avoids every thread in the pool retrying in the
    # same instant and re-colliding.
    resp = None
    for attempt in range(3):
        resp = get(url, headers={"x-api-key": key}, params=_bust(params), timeout=30)
        if resp.status_code != 429:
            break
        time.sleep(random.uniform(0.4, 0.9) * (attempt + 1))
    resp.raise_for_status()
    data = resp.json()
    if "experts" not in data:
        raise RuntimeError(f"unexpected response shape: {sorted(data)}")

    experts = [
        {"expert_id": e.get("expert_id"), "expert_name": e.get("name"),
         "last_updated": _parse_api_timestamp(
             (e.get("positions") or {}).get(slot))}
        for e in data["experts"]
    ]
    return {
        "slot": slot, "scoring": scoring, "page": "api:rankings/experts",
        "year": data.get("season"), "week": data.get("week"),
        "page_position": slot, "page_scoring": scoring,
        "ranking_type": "weekly", "mismatch": None, "experts": experts,
    }


def fetch_list_freshness(slot, scoring, session=None):
    """One list's per-expert update times -- official API, HTML scrape as backup.

    The API is strictly better when it works: precise structured JSON instead
    of brace-matching JS out of a page, no chance of markup changes silently
    breaking the parse. But it is a third-party key on someone else's rate
    limits, so a failure here (revoked key, outage, unpublished quota) falls
    back to the scrape rather than taking a freshness-critical run down.
    """
    try:
        return _fetch_list_freshness_api(slot, scoring, session=session)
    except Exception as exc:
        print(f"WARNING: official API freshness lookup failed for "
              f"{slot}/{scoring} ({type(exc).__name__}: {exc}) -- "
              f"falling back to the HTML scrape.")
        return _fetch_list_freshness_html(slot, scoring, session=session)


def _fetch_list_freshness_html(slot, scoring, session=None):
    """Fetch one weekly list's page and return its expert update times.

    Returns a dict with the page's self-reported year/week/position/scoring
    plus one entry per expert on that list. Raises on HTTP failure.
    """
    page = LIST_PAGES[(slot, scoring)]
    get = (session or requests).get
    resp = get(BASE + page, headers=HEADERS, params=_bust(), timeout=30)
    resp.raise_for_status()

    ecr = extract_js_object(resp.text, "ecrData") or {}
    groups = extract_js_object(resp.text, "expertGroupsData") or {}

    page_pos = ecr.get("position_id")
    page_scoring = ecr.get("scoring")
    mismatch = None
    if page_pos and page_pos != slot:
        mismatch = f"page reports position {page_pos}, expected {slot}"
    elif scoring != "ANY" and page_scoring and page_scoring != scoring:
        mismatch = f"page reports scoring {page_scoring}, expected {scoring}"

    experts = []
    for e in groups.get("expert_data", []):
        experts.append({
            "expert_id": e.get("id"),
            "expert_name": e.get("name"),
            "last_updated": e.get("last_updated"),
        })

    return {
        "slot": slot,
        "scoring": scoring,
        "page": page,
        "year": ecr.get("year"),
        "week": ecr.get("week"),
        "page_position": page_pos,
        "page_scoring": page_scoring,
        "ranking_type": ecr.get("ranking_type_name"),
        "mismatch": mismatch,
        "experts": experts,
    }


# ---------------------------------------------------------------------------
# Freshness tiering
# ---------------------------------------------------------------------------

def to_et(epoch):
    if not epoch:
        return None
    return datetime.datetime.fromtimestamp(int(epoch), ET)


def tier(epoch, now_et=None, cutoff=None):
    """Classify one expert's update time for a given list.

    FRESH    -- saved on the run's own day at/after the slate's cutoff. The
                only tier that can reflect late injury news.
    SAME_DAY -- saved earlier the same day. Real weekly rankings, but from
                before the line Joe is willing to trust.
    STALE    -- saved before today. For an in-season pull this is poison:
                it can hand back last week's board.
    UNKNOWN  -- no timestamp published. Note this is NOT the same as "not
                updated" -- an expert absent from FP's panel has no epoch at
                all, which is why fingerprint_expert_list exists.
    """
    if not epoch:
        return "UNKNOWN"
    now_et = now_et or datetime.datetime.now(ET)
    cutoff = cutoff or DEFAULT_CUTOFF
    when = to_et(epoch)
    if when.date() < now_et.date():
        return "STALE"
    return "FRESH" if when.time() >= cutoff else "SAME_DAY"


# ---------------------------------------------------------------------------
# Panel-independent freshness: content fingerprints
# ---------------------------------------------------------------------------
# The panel epoch is the better signal when it exists, but it only exists for
# experts FP currently lists in `expertGroupsData`. As of 2026-09-02 four of
# the seven sources above (Thorman, Ratcliffe, Tyler O, Jahnke) were on no
# panel page while still returning real data from the API. For those, freshness
# has to be measured by watching the list itself change.
#
# This is strictly weaker than the epoch -- it can only say "changed since I
# last looked", never "saved at 12:31" -- so a run that depends on it needs an
# earlier baseline sample to compare against. It is also immune to the panel
# problem, and it catches real edits the epoch would miss if FP ever stopped
# publishing timestamps.

CONSENSUS_URL = "https://partners.fantasypros.com/api/v1/consensus-rankings.php"


def fetch_expert_list(expert_id, slot, scoring, year, week, session=None):
    """One expert's weekly list for one slot. Returns (players, last_updated).

    `scoring="ANY"` means a format-invariant list (QB/K/DST, verified
    byte-identical across HALF/PPR/STD) and is queried as HALF.
    """
    params = {
        "sport": "NFL", "year": str(year), "week": str(week),
        "id": expert_id, "position": slot, "type": "WEEK",
        "scoring": "HALF" if scoring == "ANY" else scoring,
        "filters": expert_id,
    }
    get = (session or requests).get
    resp = get(CONSENSUS_URL, params=_bust(params), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("players", []), data.get("last_updated")


def fingerprint_expert_list(expert_id, slot, scoring, year, week, session=None):
    """Stable hash of an expert's ordered list, for change detection.

    Hashes rank+name only. Tier/min/max/std are deliberately excluded: those
    are consensus-derived fields that move when OTHER experts submit, so
    including them would report phantom updates.
    """
    players, last_updated = fetch_expert_list(
        expert_id, slot, scoring, year, week, session=session)
    payload = "|".join(
        f"{p.get('rank_ecr')}:{p.get('player_name')}" for p in players)
    return {
        "expert_id": expert_id,
        "slot": slot,
        "scoring": scoring,
        "count": len(players),
        "fingerprint": hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16],
        "api_last_updated": last_updated,
    }


# ---------------------------------------------------------------------------
# Flex / position reconciliation
# ---------------------------------------------------------------------------
# FantasyPros enforces that a submitted flex board agrees with the submitted
# position boards on WITHIN-position order: pasting the RB list slightly
# reorders the flex. That is why FLX is pasted first and the positions after --
# the published flex is cross-position interleaving from the FLX paste plus
# within-position order from the position pastes.
#
# This matters because build_consensus.py blends each slot INDEPENDENTLY, over
# a different player pool with different gap-fill continuation ranks. Measured
# on 2025 week 12 with the top 4 sources, that produced **65 disagreements**
# between the blended flex and the blended RB/WR/TE lists. Left alone, FP would
# silently resolve all 65 by paste order, so the published flex would be a
# hybrid nobody designed and would not match the exported CSV.
#
# Reconciling before export makes FP's enforcement a no-op: what gets pasted is
# what gets published.

def reconcile_flex(flex_names, position_lists):
    """Reorder a blended flex board so it agrees with the blended position boards.

    This does NOT build a flex list. Each source's FLX comes straight from FP.
    The conflict appears only after blending: build_consensus.py averages ranks
    per slot over different player pools with different gap-fill continuation
    ranks, so a blend of four real FLX lists and a blend of four real RB lists
    can disagree on which of two RBs is ahead. FP resolves that itself when the
    position lists are pasted -- this makes the exported file match what FP will
    publish, so the CSV can actually be trusted for QA.

    Keeps the flex's cross-position interleaving -- the pattern of RB/WR/TE
    slots down the board, which is the genuinely cross-positional judgment --
    and fills those slots in the order the position lists give, which is what
    FP will enforce regardless.

    `position_lists` maps slot -> ordered player names (e.g. {"RB": [...]}).

    This is a strict permutation of `flex_names`: nobody is added or dropped.
    That matters because the flex blend and the position blends do NOT share a
    player universe -- each is built over its own sources' lists -- so a flex
    member can be absent from every position list and vice versa. Flex members
    with no position list keep their slot; players in a position list but not
    in the flex are simply not in the flex, since FP's flex only holds what was
    submitted to it.
    """
    flex_names = list(flex_names)
    slot_of = {}
    for slot, names in position_lists.items():
        for n in names:
            slot_of.setdefault(n, slot)

    # Rank within each position list, for ordering flex members by it.
    rank_in_pos = {
        slot: {n: i for i, n in enumerate(names)}
        for slot, names in position_lists.items()
    }

    # Per position, the flex's own members of that position, reordered by the
    # position list. The `sentinel` fallback is defensive only: every name here
    # got its slot FROM a position list, so its rank is normally present.
    members = {}
    for idx, name in enumerate(flex_names):
        slot = slot_of.get(name)
        if slot is not None:
            members.setdefault(slot, []).append((idx, name))
    sequences = {}
    for slot, entries in members.items():
        ranks = rank_in_pos.get(slot, {})
        sentinel = len(ranks)
        sequences[slot] = [
            name for _, name in sorted(
                entries, key=lambda e: (ranks.get(e[1], sentinel), e[0]))
        ]

    cursors = {slot: 0 for slot in sequences}
    out = []
    for name in flex_names:
        slot = slot_of.get(name)
        if slot is None:
            out.append(name)                    # no position list: keep as-is
            continue
        out.append(sequences[slot][cursors[slot]])
        cursors[slot] += 1
    return out


# ---------------------------------------------------------------------------
# Capture window: when a manual PFF pull is allowed
# ---------------------------------------------------------------------------
# Joe's rule: pulling Jahnke's CSVs by hand is fine on any day, as long as it is
# more than 15 minutes before a lock. Inside that margin the clock belongs to
# pasting, not to a five-export browser session -- and a capture that lands at
# 12:58 is worth nothing anyway.
#
# Locks are kickoffs, not the freshness cutoffs: TNF at 8:15 PM Thursday and the
# main slate at 1 PM Sunday. Wednesday/Friday one-off games are not tracked here
# because they are irregular; pass an explicit `extra_locks` when one matters.

CAPTURE_MARGIN_MINUTES = 15


def next_lock(now_et=None, extra_locks=()):
    """(name, datetime) of the next kickoff Joe publishes against.

    Rolls into next week once this week's Sunday slate has started, so the
    answer is always in the future.
    """
    now_et = now_et or datetime.datetime.now(ET)
    candidates = [
        ("TNF kickoff", _at(now_et, THURSDAY, TNF_KICKOFF)),
        ("Sunday 1 PM lock", _at(now_et, SUNDAY, SLATES["SUN"]["kickoff"])),
    ]
    candidates.extend(extra_locks)
    upcoming = sorted((dt, name) for name, dt in candidates if dt > now_et)
    if upcoming:
        return upcoming[0][1], upcoming[0][0]
    # Past everything this week -- next week's Thursday.
    return "TNF kickoff", _at(now_et, THURSDAY, TNF_KICKOFF) + datetime.timedelta(days=7)


def capture_window_ok(now_et=None, margin_minutes=CAPTURE_MARGIN_MINUTES,
                      extra_locks=()):
    """(ok, explanation) -- may a manual capture run right now?"""
    now_et = now_et or datetime.datetime.now(ET)
    name, when = next_lock(now_et, extra_locks)
    minutes = (when - now_et).total_seconds() / 60
    if minutes <= margin_minutes:
        return False, (f"{minutes:.0f} min to {name} "
                       f"({when:%a %I:%M %p}) -- inside the {margin_minutes} min "
                       f"margin, do not start a capture")
    if minutes < 120:
        return True, (f"{minutes:.0f} min to {name} ({when:%a %I:%M %p}) -- "
                      f"okay, but tight")
    hours = minutes / 60
    return True, f"{hours:.1f} h to {name} ({when:%a %I:%M %p}) -- plenty of time"


if __name__ == "__main__":
    now = datetime.datetime.now(ET)
    phase, threshold, why = freshness_threshold(now)
    ok, note = capture_window_ok(now)
    print(f"Now:      {now:%a %Y-%m-%d %I:%M %p %Z}")
    print(f"Phase:    {phase} -- {why}")
    print(f"Threshold:{'  none' if threshold is None else threshold:%a %I:%M %p}"
          if threshold else "Threshold: none")
    print(f"Capture:  {'OK' if ok else 'BLOCKED'} -- {note}")
