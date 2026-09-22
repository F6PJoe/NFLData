# Goal-Line Guide — weekly updater

Feeds Joe's "Goal-Line Guide" Google Sheet (id
`1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI`), "Off" and "Def" tabs. Same
service-account credentials as the rest of this repo
(`triple-baton-456523-e4-b9ec3cbd6e3d.json` at the repo root) — the sheet is
shared with that service account directly.

## What it does
`update_weekly.py --week N` is **additive, not a recompute**: it reads
whatever's already in the sheet's B/C (run att/TD) and F/G (pass att/TD)
columns, adds one week's nflverse play-by-play numbers on top, and writes
the new season-to-date total back. Column D and H (`%`) are sheet formulas
(`=IFERROR(C2/B2*100, 0)`) and are never touched.

**Run it once per week, after that week is final.** There's no de-dup —
running the same week twice double-counts. Use `--dry-run` first to preview
the deltas.

## Goal-line definition (reverse-engineered, not guessed)
A play counts if `yardline_100` is between 0 and 5 inclusive (line of
scrimmage inside the opponent's 5 — matches `ff_utilization`'s existing
`inside5_rush` convention), **excluding two-point conversion attempts**.
Verified against the sheet's own pre-existing week 1-2 totals: exact match
on 30 of 32 teams, both tabs (60/64 team-rows). The handful of misses trace
to one single ambiguous play — an aborted/fumbled shotgun snap that
nflverse flags `rush_attempt=1` (`play_type=run`) but doesn't fit either
bucket cleanly — not a methodology error worth chasing further, since it's
a single edge-case play out of ~130 goal-line snaps checked.

Two-point attempts matter: including them threw BUF's week 1-2 pass total
off by exactly one attempt (a real goal-line pass attempt is not the same
category as a two-point try, even though both happen inside the 5).

## Team codes
nflverse spells three teams differently than this sheet does:
`ARI`→`ARZ`, `WAS`→`WSH`, `LA`→`LAR`. `TEAM_FIX` in `update_weekly.py`
handles it. (Not the same mapping as `ff_defense/team_names.py` — that
project's sheet uses `ARI`/`WAS` as-is, this one doesn't.)

## Zero convention
The sheet stores a zero count as a **blank cell**, not the literal `"0"`
(the `%` formula's `IFERROR` already handles the resulting division by
zero). The script matches that: it writes `""` rather than `0` when a
season total is zero, so a fresh-zero row looks identical to how the sheet
already looked before this script existed.

## pbp cache is always refreshed, never trusted stale
Same lesson as `ff_utilization/CLAUDE.md` bug #4: `play_by_play_{year}.csv`
is one file per season, overwritten in place on nflverse's end. A cached
copy from earlier in the week would silently omit the games that just
finished. `fetch_pbp()` has no cache-reuse flag on purpose.

## Weekly cadence (once a week is set up like W2/W3)
Each week gets its own tab ("W2", "W3", ...): `Away | Im. Total | GL R
Grade | GL P Grade | | O/U | | Home | Im. Total | GL R Grade | GL P Grade`.
The GL Grade columns (C/D and J/K) are **live VLOOKUP formulas** against
`Off`/`Def`, so a week's grades always reflect the season totals *as of
whenever the tab is read* -- great for the upcoming week, a problem for a
past week once `Off`/`Def` moves on. `Im. Total`/`O/U` (B/F/I) are plain
values, written by `fill_week_odds.py`, not formulas.

Full sequence for moving from one week to the next, **in this order**
(confirmed and run for real going from W2 -> W3):
```
python advance_week.py --from 2 --to 3       # 1-2: duplicate W2->W3 with formulas, freeze W2 to values
python set_week_matchups.py --week 3         # 3: overwrite A/H with this week's real matchups
python fill_week_odds.py --week 3            # 4: live pre-game imp. total + O/U into B/F/I
python update_weekly.py --week 2             # 5: add week 2's just-played goal-line numbers to Off/Def
```
Step 5 runs last and uses the week that just finished (2), not the new week
(3) -- it's catching Off/Def up on the week that's now over, which is also
why it has to come after the freeze in steps 1-2: Off/Def changing is
exactly what step 2 was protecting last week's tab from.
1. **`advance_week.py` duplicates before it freezes**, not the other way
   around. Duplicating first means the new tab (W3) inherits W2's still-live
   formulas, so once Off/Def updates in step 2, W3's grades automatically
   pick up the fresh season-to-date numbers -- correct for a week that
   hasn't been played yet. Freezing W2 right after (paste-values-only over
   its own C:D/J:K) locks in what those grades actually were *entering*
   week 2, permanently, so step 2 can't retroactively corrupt that history.
2. **`update_weekly.py` runs after the freeze, not before** -- see above.
3. **`fill_week_odds.py --source odds_api` (the default) is the normal
   weekly source now.** It only sees upcoming games, so run it early in the
   week, once, before kickoff -- that's the intended cadence going forward,
   not a backfill-after-the-fact. It matches Odds API games to the target
   week by (away, home) team pair against nflverse's full-season schedule
   (already published for the whole year), not a date window -- more
   precise than `ff_defense/fetch_implied_totals.py`'s own date-window
   approach, and it works identically whether the week starts in five days
   or five minutes. `--source nflverse` (free closing lines, no API key)
   is kept only for backfilling a week that's already final, which is how
   week 2 first got filled in.

`advance_week.py` refuses to run if the destination tab already exists,
so it can't be re-run by accident to silently double-duplicate.

**`set_week_matchups.py` has to run between the two** -- a freshly
duplicated tab still has the OLD week's teams in A/H, and
`fill_week_odds.py` matches games by (away, home) pair, so it can't find
anything to update until the matchups themselves are current. Sourced from
nflverse's full-season schedule (already published for every week), sorted
by kickoff time. Handles a bye week shrinking the game count (clears the
now-unused rows) and, just in case, a week needing MORE rows than the
template has (copies the last template row's GL Grade formulas down,
using `PASTE_FORMULA` so the relative VLOOKUP refs adjust per row).

## Automated on GitHub Actions -- split Monday/Tuesday, not one run
`.github/workflows/goalline_monday.yml` and `goalline_tuesday.yml`, both
`workflow_dispatch`-only (no native `schedule:` -- see every other
workflow in this repo for why), driven by cron-job.org.

**Why two workflows and not one Monday run**: most NFL weeks have a Monday
night game that doesn't finish until Monday evening, so a single
Monday-afternoon run of `update_weekly.py` would systematically miss that
week's MNF goal-line plays every week (this is exactly why `ff_defense`'s
own weekly rollup runs Tuesday, not Monday -- same underlying issue). By
design here, that gap is fine: this data feeds a write-up for the site,
and the writer gets a head start with whatever's in by Monday afternoon
(everything except, typically, that one game), then Tuesday's run finishes
the week once MNF has posted. **Verified live**, not just in theory: the
first time this was built, week 2's Monday game (NYG@LA) genuinely hadn't
posted to nflverse yet when `update_weekly.py --week 2` was run that same
Monday, so `Off`/`Def` were missing exactly that one game's plays until a
follow-up run picked it up -- the real bug this design exists to make safe
to leave in place on purpose, once a week, every week.

- **`goalline_monday.yml`** runs `run_monday.py`: advance the week,
  matchups, odds, AND a first pass at `update_weekly.py` for the
  just-played week (picks up whatever's already final).
- **`goalline_tuesday.yml`** runs `run_tuesday.py`: `update_weekly.py`
  again for that same week, now catching the newly-final MNF game. Nothing
  duplicates -- `update_weekly.py` de-dupes per `game_id`
  (`data/counted_games.json`, committed back to the repo by both
  workflows so the manifest persists across runs), so running the exact
  same command twice is what makes the split safe, not a special case.

**Neither script hardcodes a week number.** `sheet_state.latest_week_tab()`
reads the highest existing `"W<N>"` tab directly from the sheet -- Monday
treats that as "the current week" and advances past it; Tuesday treats
`latest - 1` as "the week that just played" (Monday's run already moved
the sheet's latest tab forward). This means the workflows never need
editing as the season progresses, unlike `ff_defense/current_week.py`'s
date-anchor approach, which needs updating every season.

**Known drift risk**: Tuesday's `latest - 1` assumes Monday's run actually
succeeded and created the new tab. If Monday's job fails outright, Tuesday
will target the wrong (already-fully-counted) week and silently no-op --
it won't error, since "nothing new to add" is the same message as "already
caught up." Check a Tuesday run's own log output (it prints which week
it's targeting and whether anything new was found), not just whether the
Actions job went green, if an MNF game seems to be missing from `Off`/`Def`.

**`data/counted_games.json` is intentionally tracked in git**, not
gitignored like `cached/` -- it's small, durable state, not a re-fetchable
cache. It was backfilled once, by hand, with every game_id already folded
into `Off`/`Def` at the time this system was built (weeks 1-2, 31 of the
32 games -- week 2's Monday game was excluded from the backfill because it
genuinely hadn't been counted yet, see above).

Required secrets (`GOOGLE_SERVICE_ACCOUNT`, `ODDS_API_KEY`) already exist
in the repo, shared with `ff_defense`'s workflows -- nothing new to add in
GitHub Settings.
