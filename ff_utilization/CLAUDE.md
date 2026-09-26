# Utilization Report (RB/WR/TE usage data for the site)

## Goal
Pull Fantasy Life's Utilization Report (PFF-charted usage) for RB/WR/TE and
publish it to fantasysixpack.net as two paywalled tables — a **season totals**
table and a **weekly game log** — replacing the manual, team-by-team slog on
FL's own site. Feeds the weekly Usage Report article series
(`/2025-fantasy-football-week-N-usage-report-...`).

## Why Fantasy Life, and not something else
Settled after checking every alternative directly, not from docs alone:

| Source | Routes / route % / TPRR | Snap counts | Verdict |
|---|---|---|---|
| **Fantasy Life (PFF)** | **yes** | yes | **chosen** — the only in-season route source we can actually reach |
| Sportradar | **no** — impossible, not a pricing tier | no | see below |
| nflverse `load_participation()` | no in-season — FTN donates it **post-season only** | — | dead end for weekly |
| nflverse `load_pfr_advstats(rec)` | **no** — downloaded the real 2025 file: only drops/broken tackles/int/rating | — | dead end |
| nflverse `load_snap_counts()` | — | **yes**, free, weekly | good free fallback for snaps only |
| PFF direct | yes | yes | API is B2B-only; user has no subscription |
| FTN StatsHub | yes (paid tier) | — | user has FTN, tier unconfirmed; unnecessary now |

**Sportradar can never produce routes run**, and this is worth remembering so
it doesn't get re-litigated: its per-play `statistics[]` array only contains
players who *touched the ball* (or made a defensive play). There is no
personnel/participation list in the payload at any package level. Verified by
opening real cached PBP JSON in `SabotageFantasy/cached/sr/2025/pbp/`.
Sportradar *is* excellent for what it does have (native `play_action` boolean,
`inside_20`/`goaltogo`, per-target `att_yards`, down/distance/clock on every
play, all charted ~3 hours after kickoff) — just not for anything snap- or
route-based.

**Timing reality**: routes and true snap-participation are gated by the NFL's
own participation report / All-22 film, so nobody — at any price — has them
before Monday. FL/PFF publishing Monday morning is already the fast path;
there is no earlier source to chase.

## The API (both endpoints need Firebase `bearer-token` auth)
Same auth as `ff_draft_proj/fetch_fantasylife_projections.py` — sign in
against Google Identity Toolkit with `FANTASYLIFE_FIREBASE_API_KEY`, use the
returned `idToken` as the `bearer-token` header. Credentials live in
`ff_draft_proj/.env`.

```
season totals   GET /api/datatables/season-stats
                    ?year=&weeksMin=&weeksMax=&scoringSystem=
weekly game log GET /api/datatables/game-logs
                    ?year=&team=&weeksMin=&weeksMax=&scoringSystem=
```

Findings that cost real probing time:
- **`season-stats` returns ALL 642 players in one call.** No pagination.
  `limit`/`offset`/`position` params are accepted and then **silently
  ignored** — you always get everyone. Don't build paging for it.
- **`game-logs` is one team per call.** Omitting `team` silently returns just
  one team (PHI); `team=ALL` returns `items: null` with `total: 642`, which
  looks like success but has no rows. Loop the 32 aliases.
- Each `game-logs` player carries a nested `log_items` array, one entry per
  week actually played (a 3-game player has exactly 3 entries).
- The endpoint names are NOT guessable from the page URL — the season page is
  served via `/api/content/page?path=...`, and every `utilization-*` guess
  404s. The real names came from the user's DevTools Network tab.

## Raw vs. percentage — the one real schema gotcha
Only **`player_snaps_raw`** and **`routes_raw`** come back as true raw counts.
Every other counting stat is delivered as `<stat>_per_game` + `<stat>_percent`
only. So:

- **weekly rows** — `_per_game` *is* that week's raw count (one game), used as-is
- **season rows** — raw total = `_per_game * games_played`, rounded

`--verify` checks this reconstruction against the two fields that *do* have a
raw form. Result on the 2025 wk1-2 pull: **368 players, 0 off by more than 1**
(the ±1 tolerance is FL's own rounding), and 736/736 raw-field passthroughs
exact. The reconstruction is sound.

FL's UI has a raw/percentage toggle; the API always returns both, so the
toggle is display-only. Our tables show raw and % **side by side, no toggle**
(user's call).

## Columns collected
Identity: `player, team, pos, season`, then `games` (season) or `week` (weekly).

Raw+% pairs: `snaps`, `routes`, `rush_att`, `targets`, `catchable_tgts`,
`ez_tgts`, `inside5_rush`, `sdd_snaps`, `ldd_snaps`, `two_min_snaps`.
Plus `tprr` (a rate, single column).

Team denominators, stored but likely not displayed — they make any custom
week range re-aggregatable later: `team_sdd_snaps`, `team_ldd_snaps`,
`team_ez_tgts`, `team_third_fourth_pass`, `team_inside5_rush`.

**Deliberately dropped**: `utilization_score` (FL proprietary), `ppr_fantasy`,
`ppr_fantasy_rank`, `ppg`, `ppg_rank` (scoring-dependent, user doesn't want
points on these tables); `adot`, `air_yards_*`, `play_action_targets_*`,
`third_fourth_targets_*` (user cut them); and the QB-shaped fields that are
always 0 for RB/WR/TE (`drop_backs_*`, `pass_plays_*`,
`pass_completions_percent`, `sacks_*`, `scrambles_*`, `qb_adot`, `ypa`).

## Ball Possession/Drive Chart: no player data — do not use for snaps
Checked directly (`SEA_DriveChart.pdf`): it's drive-level only — one row per
drive (how it started/ended, plays, yards, time of possession), zero player
names anywhere in the document. It cannot substitute for the gamebook's
"Playtime Percentage" page, which remains the only source of per-player
snap counts.

## Players with no FL route match are DROPPED, not zero-filled
By decision: no player is published with an incomplete row. Checked on 2026
wk1 — of 43 unmatched official players, 32 had zero snaps/rush/targets
(inactive/practice squad) and the rest were fullbacks/emergency backs FL's
own game-log excludes too (same pattern independently seen on 2025 wk1-2).
Not a matching bug. `build_published.py` prints a WARNING (not a silent drop)
for anyone dropped with real volume (3+ targets or 6+ rushes), in case a
future week's miss is a genuine name mismatch rather than an FL exclusion —
check that list before trusting a fully-clean run.

## THE WEEKLY PIPELINE — user runs ALL of this every week (their choice,
## overriding the "teaser can lag" default below)
```
python fetch_nflverse_utilization.py --year 2026 --weeks 1-N    # official
python fetch_fantasylife_utilization.py --year 2026 --weeks 1-N # FL (routes)
python build_published.py --year 2026 --weeks 1-N                # merge
python build_teaser.py --year 2026 --weeks 1-N --view weekly
python build_teaser.py --year 2026 --weeks 1-N --view season
```
`run_weekly.py --year 2026 --weeks 1-N` runs all five of those plus the SFTP
upload as one command -- it stops immediately if any build step fails, then
runs `sftp_upload.py --dry-run` and asks for a `y` before the real upload
(`--yes` skips that prompt for a true one-shot run). The prompt is the one
thing it deliberately doesn't automate away, same reasoning as
`sftp_upload.py` being a separate step in the first place -- see below.
**3 files to upload, every week:**
- `data/utilization_weekly.json` → s2member-files gateway (members, both posts)
- `data/utilization_teaser_weekly.json` → plain public path (weekly teaser)
- `data/utilization_teaser_season.json` → plain public path (season teaser)

`sftp_upload.py` uploads all three in one command (`--dry-run` first to check
credentials/paths without writing). Deliberately still a separate, manual step
from the build commands above, not chained into one script or a cron job --
the point is to replace the drag-and-drop, not the human glance at the numbers
before they go out. See that file's docstring for one-time SiteGround SFTP
setup and the `.env` values it reads.

**`--weeks` is ALWAYS `1-N`, N = the current week — never just the new week
alone.** All five commands read/write off `wk1-N`-suffixed files, and the
season view/teaser works by *summing every week present in that file*. Passing
just the new week (e.g. `--weeks 3-3` in week 3) would silently make "season"
mean "this week only" — the file would be internally consistent, just wrong.
Week 1 example above used `1-1` because week 1 IS the whole season so far;
week 5 would be `1-5`, etc.

**The embed HTML files are NOT part of this weekly cycle.** `embed_weekly.html`
/ `embed_season.html` / `embed_teaser_weekly.html` / `embed_teaser_season.html`
only need re-pasting into WordPress when `component.html` or
`component_teaser.html` changes — a column added/removed, a design tweak.
Never on a plain data refresh.
`build_published.py` merges them: **official basis for everything, FL for
routes only**. The rule that keeps that honest is **no ratio may cross
sources** — every percentage takes its numerator and denominator from the same
feed. TPRR was the sole violator (official targets ÷ FL routes) and is
therefore NOT published; it stays in the FL spreadsheet, as do catchable_tgts
and sdd/ldd/2min.

Published columns: snaps, snap%, rush, rush%, I5, I5%, routes, rte%, targets,
tgt%, EZ, EZ%, ADOT.

### Three bugs this merge introduced, all fixed — watch for them again
1. **`csv.DictReader` yields strings.** Written into the JSON untouched, the
   season view computed `"0" + "46"` = `"046"` and every derived rate came out
   `NaN`. `coerce()` now casts before writing. The FL pipeline never hit this
   because it builds rows from numbers directly.
2. **No `team_snaps` in the official build** — it carries snap *percentage*
   from the gamebook but no team total, so season snap% divided by nothing.
   Recovered as median(`snaps / pct`) per team-week.
3. **ADOT is not a percentage.** Running it through `RATES` (which multiplies
   by 100) rendered −3.0 as −300. Non-percentage ratios now go through a
   separate `RATIOS` map, and `air_yards_total` is carried so ADOT re-derives
   over a week range instead of averaging weekly ADOTs.
4. **Stale pbp cache silently zeroed a whole game's stats.** `players`/`snaps`/
   `pbp`/`rosters` are one file per season, overwritten in place on each
   download -- `fetch()` only re-downloads when told to. `snaps` was already
   hardcoded to always refresh (see `collect_gamebook_snaps`), but `pbp`
   wasn't, and only `pbp` feeds the play-derived columns (rush/targets/rec/
   EZ/ADOT). Hit for real: week 1's Monday game (DEN@KC) got correct snap
   counts (gamebook-sourced, always-fresh path) but rush/targets/rec/EZ/ADOT
   all silently read 0 for every DEN/KC player, because the cached
   `pbp_2026.csv` on disk predated Monday's game and nothing forced a
   re-download. No error, no warning -- the numbers just looked like nobody
   on either team touched the ball. Fixed at the source, not just by
   remembering a flag: `build()` now always re-downloads players/snaps/pbp/
   rosters by default (`use_cache=False` in the function, no CLI flag needed).
   `--use-cache` opts back into the stale-allowed behavior for fast local
   iteration on merge logic only -- **never pass it for a real weekly run.**
5. **Same bug, opposite direction, in `games.csv`.** Found immediately
   after fixing #4: `games.csv` lists the full season's schedule from day
   one, but its `gsis` column (the game id gamebook fetching keys off) fills
   in progressively per game, not all at once. `collect_gamebook_snaps()`
   hardcoded `fetch("games", year, refresh=False)` on the theory that "the
   schedule doesn't change" -- true for the matchups, false for `gsis`. A
   cache from right after week 1 had week 2's `gsis` cells still blank, so
   `wmin <= week <= wmax` filtering silently dropped 15 already-completed
   week 2 games before gamebook fetching even started -- no error,
   `--coverage` just quietly reported week 1's 16 games and stopped, as if
   week 2 hadn't happened. Fixed the same way as #4: `games` now follows the
   same always-refresh policy as players/snaps/pbp/rosters.

   Fixing #5 immediately created a new, opposite problem: with `games`
   forced fresh, `gamebook_snaps()`'s per-game PDF fetch was *also* being
   re-triggered on every run (it received the same blanket refresh flag),
   which meant re-downloading all 30+ already-final gamebook PDFs every
   single time instead of just the one still-pending game -- correct, but
   needlessly slow. Fixed by decoupling the two caching policies entirely:
   `gamebook_snaps()` now caches by **content validity**, not existence or a
   shared flag -- if the saved PDF already parses to real snap rows, it's
   trusted with zero network calls (a posted gamebook doesn't get revised,
   so this is safe indefinitely); if it parses to nothing (fetched before
   the Playtime section existed, same lag `coverage()` warns about), it's
   retried from scratch on every call until it succeeds. Verified directly:
   ran the full fetch twice back to back, confirmed via `stat`'s mtime that
   an already-good week 1 gamebook PDF was byte-identical and untouched
   both times, while the one not-yet-posted game (this week's MNF) kept
   re-attempting and correctly reporting the failure each run.
6. **Multi-week gamebook snaps collided across weeks -- week 1 silently
   inherited week 2's snap counts.** `short_key()` (team, surname, position)
   deliberately excludes week -- it's scoped to matching names within ONE
   game's gamebook PDF, where a week component would be meaningless.
   `collect_gamebook_snaps()` reused that same key as the accumulator key
   across the ENTIRE requested week range, so `snaps.update(...)` for week
   2's game silently overwrote week 1's entry for the same player (same
   key, since team/surname/position don't change week to week). Every row
   for that player -- regardless of which week it belonged to -- then read
   back whichever week was processed last. This bug existed from the start
   but could never trigger until a multi-week range was actually built,
   which didn't happen until this week (every prior build was `--weeks
   1-1`, one single week, wmin==wmax, no collision possible). Caught by the
   user eyeballing the live site: Tyler Allgeier's week 1 row showed 32
   snaps -- his real week 2 count -- instead of his actual 44. Fixed by
   keying the accumulator (and the corresponding lookup in `build()`) as
   `(week, key)` instead of bare `key`, so weeks never collide. Verified
   directly against the published CSV: Allgeier/Love's week 1 snaps are
   back to 44/32 (matching the very first Week 1 build, done before this
   bug could exist) while week 2 stays 32/20, independently. Re-uploaded
   the corrected data immediately.
7. **A Friday-morning run (TNF only) can wipe the whole new week, silently.**
   Official-basis data is ready same-day from pbp, but FL's own routes data
   lags -- confirmed for real on a Friday 7:30 AM cron run: FL hadn't posted
   ANY week 3 routes yet, so literally every skill player from both Thursday
   teams (Drake London, Bijan Robinson, Matthew Golden, Christian Watson...)
   had no FL match and got dropped by the by-design "drop, don't zero-fill"
   policy. With zero surviving rows for the new week, the live table's
   "show the latest week present" logic quietly fell back to showing the
   PRIOR week instead -- reading as "the cron job didn't work" rather than
   "FL is running behind." `build_published.py` now detects this specific
   case (the newest week in the official fetch has zero published rows) and
   prints an unmissable `*** WARNING ***` block naming the likely cause and
   that it resolves on its own -- not a fix for the underlying FL lag (that
   isn't a bug to fix, it's just how early a Friday run catches things), just
   making the symptom self-diagnosing in the Action's log instead of a silent
   fallback. Separately, this exposed a real UX gap that's still open: EVEN
   ONCE FL catches up (as it does for the Thursday game specifically, often
   same day or next), "Weekly" shows only the ~2 teams that have played the
   new week so far -- correct data, but reads as "empty/broken" to a visitor
   checking the site before Sunday. Flagged to the user, not yet decided:
   options are leaving it as-is (accurate, just sparse until Sunday), adding
   a meta-line callout when the newest week's team count is well under 32,
   or something else. Revisit before treating this as settled.

## Parallel build: `fetch_nflverse_utilization.py` (official-basis)
Second pipeline, run alongside the FL one, same column names and file shape so
the grid renders either and the two can be diffed (`--compare`).

**nflverse IS the official data.** nflfastR parses the NFL's own play-by-play
feed; nflverse snap counts trace to the official participation report. Verified
against the GSIS gamebook PDFs for 2025 week 1: **325/328 offensive snaps exact
(99%)**. So there's no reason to scrape gamebooks wholesale — it's the same
numbers, already structured.

**Covers**: snaps, snaps_pct, rush_att, targets, ez_tgts, inside5_rush, adot,
plus team denominators.

**End zone targets are NOT an FL-only stat** — a recurring assumption worth
killing. `air_yards >= yardline_100` reproduces them:
*player level* 619/635 exact (97%), 100% within 1;
*team denominator* 50/64 team-weeks exact (78%), every miss within ±1, +4.4%.
`yardline_100` is already distance to the opponent's end zone, so no field-
position reconstruction is needed. Teams average ~2.2 end zone targets a game,
so the denominator is small and EZ% is noisy week to week — it reads far better
over a range, which the season view handles by summing both sides before
dividing.
**Cannot cover**: routes / routes_pct / tprr (needs route charting),
two_min / sdd / ldd snaps (needs per-play personnel — nflverse participation is
post-season only), catchable_tgts (a charting judgment). Those stay FL-only.

### Official basis ≠ PFF basis. Never mix them within a rate.
nflverse runs consistently HIGHER than FL, one-directionally (2025 wk1-2,
635 matched player-weeks):

| stat | exact | nflverse vs FL |
|---|---|---|
| snaps | 29% | **+5.2%** |
| targets | 87% | +4.5% |
| rush_att | 97% | +1.4% |
| ez_tgts | 97% | +4.5% |
| inside5_rush | 99% | +6.7% |

Cause: PFF applies charting judgment the official feed doesn't (it excludes
plays nullified by penalty, and declines to credit some throws the feed marks
"intended for" a receiver). Checked by hand: all 25 of Malik Nabers' official
wk1-2 targets are real passes thrown at him; FL says 22. **No filter reconciles
this** — don't try. Take every counting stat from one basis.

### Timing: pbp is fast, snaps are slow — from BOTH sources
Measured Monday morning of week 1, 2026:

| | games with data |
|---|---|
| nflverse **pbp** | **15 of 15** |
| GSIS gamebooks *with a Playtime section* | 3 of 15 |
| nflverse **snap_counts** (PFR) | 2 of 15 |

**A gamebook being downloadable does not mean it has snap data.** All 15 played
games returned HTTP 200 with a full-size PDF; only 3 contained "Playtime
Percentage" — that section is added later. An earlier conclusion here that
gamebooks were the timely snap source was wrong for exactly that reason: it
checked the HTTP status, not the content.

Re-measured several hours later the same day: **still 3/15 and 2/15 — neither
moved.** The three with data were the Wednesday and Thursday games plus one
Sunday game (NYJ@TEN), so it fills in **per game at uneven times**, not on a
clean delay. GSIS runs marginally ahead of PFR.

**This is why FL works for a Tuesday slot and the official sources may not.**
PFF charts from film rather than waiting on the league's participation report,
so FL has snaps Monday. The choice is not between equivalent options — it's
~5% definitional difference (official basis) against one to three days of
latency on the snaps column specifically. Everything play-derived
(targets, rush, ez, i5, adot) is same-day from pbp either way.

**RESOLVED for week 1: snaps landed Monday.** Re-checked later the same
Monday and both sources had gone 3/15 → **15/15** (gamebook and PFR together).
So Sunday games' snaps are available Monday evening, and a Tuesday publish on
official-basis data is comfortable. One week observed, not a guarantee — keep
checking until the pattern is established:
```
python fetch_nflverse_utilization.py --year 2026 --weeks 1-1 --coverage
```
prints per-game availability for both sources and exits without building.

### Gamebook name matching: two collisions that silently corrupted data
Both real in 2026 week 1, both caught only by invariant checks:

1. **MIN had Justin Jefferson (WR) and Jermar Jefferson (RB).** Keying on
   (team, initial, surname) matched both, so Justin's 60 snaps were copied onto
   Jermar, who had none. **Position is now in the key.**
2. **ATL had Bijan and Brian Robinson, both RB** — position can't separate
   them. The gamebook already does, writing `Bi.Robinson 77%46RB` and
   `Br.Robinson 25%15...RB`: **when initials collide it lengthens the prefix.**
   Taking the first character alone collapsed them and Brian's 15 overwrote
   Bijan's 46 — on a top-5 fantasy back, next to 21 carries. The first name is
   therefore NOT in the key; `match_prefix()` matches it as a variable-length
   prefix, longest wins.

### Position is spelled three ways for the backfield
Surveyed every offensive row in week 1: `RB` (74), `FB` (12), `HB` (3), plus a
truncated `RB/`. **`HB` alone cost Chase Brown his entire snap count** (46
snaps, 16 carries, showing 0) until `norm_pos()` covered it. Full observed set:
WR, TE, RB, T, OL, G, QB, C, FB, C/G, G/T, T/G, HB, K, CB, RB/, G/C, DB.

### Invariant sweep — run it after any parser change
These caught every bug above; none were visible in the summary counts:
```python
touches > snaps          # physically impossible
touches but zero snaps   # failed name match
blank team               # pbp-only player, breaks every share
snap% > 100
```
Currently 0 on all four for 2026 week 1 (361 rows, 30 teams).

### Gamebook playtime parsing gotcha
Offensive rows are `NAME PCT%SNAPS POS` (`G.Pickens 92%56WR`); defensive rows
reverse to `NAME SNAPS PCT%`. The trailing match must be `(?=\D|$)`, **not**
`\b` — a player with no special-teams snaps runs the position straight onto the
count (`92%56WR`), where `\b` finds no boundary between `6` and `W` and
silently drops every offense-only player. That bug kept only players who also
played special teams: 58 entries instead of ~300.

## DECIDED (for the FL pipeline): don't source part of it elsewhere.
Investigated substituting Sportradar for some columns and rejected it. Two
findings, both measured on 2025 weeks 1-2:

1. **Snaps, routes and TPRR are structurally impossible from Sportradar** —
   its per-play `statistics[]` lists only players who touched the ball. No
   participation data at any tier. So FL is still needed for the half that
   matters most, and a split saves nothing real.
2. **The two sources disagree on what a target is.** Sportradar counted 1,760
   targets to FL's 1,600 over 148 players — **+10%, systematic** (higher on 92
   players, lower on 1). The extras are interceptions, batted balls, and throws
   where Sportradar names an intended receiver and PFF doesn't credit a target.

That second one is why mixing is actively unsafe, not just redundant: every
`%` column is player ÷ team, so a Sportradar numerator against an FL
denominator produces rows that reconcile with neither site. Worst on small
denominators — a team sees only 3-7 end zone targets a week, so one extra
target moves EZ% by 15-25 points.

End-zone targets *are* derivable from Sportradar and validate well on their own
(`att_yards >= distance_to_goal`; 93% exact vs FL, 100% within 1, `att_yards`
present on 821/991 incompletions). The derivation isn't the problem — the
denominator is.

**Where Sportradar would still earn a place: additive columns FL doesn't have
at all** — play-action targets, third/fourth-down targets, true ADOT, red-zone
context. Additive doesn't corrupt existing rates. Substitutive does.

## Real goal: not be a clone of FL's Utilization Report
The user's concern was never load or cost — it's that the table shouldn't just
replicate FL's tool. Already acting on that: Utilization Score dropped (FL's
signature metric), fantasy points and rank dropped, SDD/LDD dropped as "very
much a FantasyLife thing", and the game log shows every team at once with an
arbitrary week range plus a Total/Per-Game toggle, none of which FL's own game
log does. Keep differentiating through column choice and framing, not by
swapping the data source.

## Mid-season movers get the wrong team — fixed, don't remove the fix
**FL's `game-logs` is scoped to a player's CURRENT roster, and `log_items`
carry no team field of their own** (verified by dumping the raw payload: the
only team info anywhere is `player.team.alias`). So a traded player's earlier
weeks come back labelled with his NEW team — Rashid Shaheed's pre-trade weeks
appeared under SEA though he played them for NO; likewise Jakobi Meyers
(LV→JAC), Brandin Cooks (NO→BUF), Adam Thielen (MIN→PIT), Ray-Ray McCloud
(ATL→NYG). FL's own UI shows the same thing. **~3-4% of player-weeks**, and
they skew toward exactly the mid-season-movement players a usage column is
about.

Detected by deriving implied team snaps (`snaps / snaps_pct`) and finding rows
that disagree with the rest of their labelled team-week. Fixed in
`reattribute_teams()`: each row still carries its REAL team's weekly
denominators, so `(team_sdd_snaps, team_ldd_snaps, team_ez_tgts,
team_third_fourth_pass, implied_team_snaps)` fingerprints the true team. Take
each team-week's modal fingerprint (the majority of a team's players are
correctly labelled) and re-attribute anyone matching a different team.

The 4 `team_*` fields **alone are not enough** — they collided for one team in
one week; adding implied snaps made all 32 distinct in every week tested. The
function skips any week whose fingerprints aren't unique rather than guessing.
Verified on 2025 wk1-2: 22 mislabeled rows → **0**, 28 rows re-attributed, and
every re-attribution matches a real 2025 transaction.

**Season totals are not corrected this way** and can't be — FL aggregates a
traded player's whole season under his current team, which is a defensible
convention for a season view, but his `team_*` denominators are a blend of two
teams. Don't compute team-relative rates from a season row for anyone who moved.

## ONE file powers both tables — season totals are recomputed client-side
FL sends snaps/routes/targets/rush-att/2-min as a player share with no team
total attached (unlike sdd/ldd/ez/inside5, which carry explicit `team_*`
fields). But `raw / pct` recovers the total, and **once teams are correctly
attributed it agrees across every player on a team-week**: routes 64/64,
targets 64/64, rush att 45/45, two-min 49/49, snaps 57/64 (worst spread 1.9,
pure rounding). This only works *after* the fix above — pre-fix, mislabeled
movers made routes and targets look underivable.

`add_derived_team_totals()` stores those five as real columns, so the season
view is just: sum the counting stats, recompute every rate from summed
numerator ÷ summed denominator. **Never average weekly percentages** — that
would weight a 5-snap week the same as a 60-snap week.

Two rates are personal, not team shares (verified against Courtland Sutton's
season line: 5.105 / 7.053 = 0.724 = his `catchable_targets_percent`):
`catchable_tgts_pct` = catchable ÷ **his own** targets, and `tprr` = targets ÷
routes. Both still aggregate as summed-numerator ÷ summed-denominator.

**Verified exactly** (`verify_aggregation.py`): aggregating weeks 1-2 locally
reproduces FL's own `season-stats` output for `weeksMin=1&weeksMax=2` with
**0 deviations across 3,550 counting stats and 3,905 rates — every rate exact
to 0.0 percentage points.** Re-run it after any change to the stat list.

Consequence: no second file, no pre-generated ranges, and the site gets an
*arbitrary* week range (weeks 2-8, last 4, whatever) which FL's own site
can't do as flexibly.

**13 players appear in `season-stats` but never in `game-logs`** — fullbacks
(Juszczyk, Ingold, Gilliam, Prentice, Luepke), emergency/gadget players
(Cooper DeJean, Jalen Ramsey), and camp bodies. All have 0 rush attempts and
near-zero targets, so FL is filtering game-logs to fantasy-relevant players.
They can't appear in a weekly-derived season view; `verify_aggregation.py`
treats this as expected but WARNS if one ever shows real usage.

## Join on `player_id`, never on name
The two endpoints spell the same player differently: `season-stats` returns a
single `player_name` **with** suffixes and punctuation ("Brian Thomas Jr.",
"D.K. Metcalf", "Calvin Austin III"); `game-logs` returns firstName/lastName
**without** them ("Brian Thomas", "DK Metcalf", "Calvin Austin"). Joining on
name silently lost 39 of 368 players (~10%), including Metcalf, Pittman,
Marvin Harrison Jr. and Brian Thomas Jr. — all stars, all present in both
feeds.

Both feeds carry `player_id` (a UUID), which is now the first column of both
outputs and the only join key used. The fetch also builds a
`{player_id: player_name}` map from the season feed and applies it to weekly
rows, so display names get the fuller spelling the weekly feed lacks. The
season call therefore runs even under `--weekly-only` (it's one cheap call).

## Storage / display decision
**Static JSON file + a JS grid, NOT MySQL and NOT wpDataTables.** Measured,
not assumed:

| | rows | raw | gzipped |
|---|---|---|---|
| season (full yr, projected) | ~561 | ~67 KB | ~20 KB |
| weekly (full 22-wk season) | **6,025** | 707 KB | **187 KB** |

187 KB gzipped for the entire season's weekly log is smaller than one photo.
Cloudflare already fronts the site and gzips automatically. JSON is written
**columnar** (`{"cols":[...], "rows":[[...]]}`, array-of-arrays) rather than
array-of-objects — keys appear once instead of per row, roughly a 3x saving.

Why not the alternatives:
- **wpDataTables is out.** Its Google-Sheets source can't use server-side
  processing at all and its own docs cap Sheets at ~5,000 rows — we're at
  6,025 on day one and growing weekly. Its MySQL mode handles the size but
  server-side processing is documented to break/restrict the advanced filters,
  including the numeric range slider we'd need for week ranges.
- **MySQL is out** on the user's own stated criteria (least resources, easiest
  to manage): it needs a query layer (custom PHP REST endpoint — new code to
  write, secure, maintain, since wpDataTables is ruled out), turns every sort/
  filter/page into PHP+DB work on shared hosting instead of a cached static
  file, and adds schema management. The write path from GitHub Actions is also
  awkward: direct remote MySQL on SiteGround shared hosting wants IP
  allowlisting, and Actions rotates across 7,000+ CIDR blocks — a problem this
  repo already hit and documented in `ff_auction_values/CLAUDE.md` round 10.
  Revisit only if this ever reaches hundreds of thousands of rows; 5 seasons
  would still only be ~30k rows / ~950 KB gzipped.

## Table design (agreed with user)
- **One combined RB/WR/TE table**, not split by position — switching positions
  on FL's site is a stated annoyance. Irrelevant columns for a position just
  sit empty.
- **Two tables, same grid component**, so presentation matches: season totals
  (one row per player) and weekly game log (one row per player-week).
- **Game log shows every player, all teams** — no forced team dropdown (FL's
  worst UX problem). Defaults keep it from being overwhelming:
  **week defaults to the most recent completed week** (~400-500 rows, not
  6,000) and **sort defaults to snaps descending** (the one metric comparable
  across RB/WR/TE, so real starters surface first). Team/position/player-search
  are optional filters.
- **Season table**: optional team filter, plus the same week-range filter.
- Big scrollable table is fine (user's call), plus a CSV download.
- Article-facing "key" stats stay: RB `snaps/rush att/targets/inside-5`;
  WR/TE `snaps/routes/targets/ez targets`. The rest is the paywalled extra.

**Custom week ranges work in both views** off the single weekly file — see the
aggregation section above.

## The grid — `component.html` is the ONLY file to edit
```
component.html      <- source of truth. Edit this.
build_embed.py      -> embed_weekly.html   paste into the weekly post
                    -> embed_season.html   paste into the season post
                    -> usage_table.html    local dev copy (both views)
build_preview.py    -> usage_preview.html  design snapshot, data inlined
```
The generated embeds carry a one-line "GENERATED — do not edit" banner;
hand-edits there are lost on the next build.

**Never put paste instructions inside an embed file.** The first version's
banner was a multi-line HTML comment containing an example
`<!-- F6P_USAGE:START -->` and a `[/s2If-paywall]`. HTML comments don't nest,
so the inner `-->` closed the banner early and dumped the rest onto the live
page as visible text — and the stray closing shortcode ended the real paywall
block early, so the component never initialized. The banner is now a single
dumb line, `build_embed.py` asserts no `-->` appears before the START marker
and no `s2If` string appears anywhere in the file, and the instructions live in
`PASTE_INSTRUCTIONS.txt`.

## RESOLVED: Gutenberg Custom HTML block + collapsed embed
**This is the working configuration — confirmed live.** Both posts render
correctly inside `[s2If-paywall]`, fetching from the s2Member gateway.

**Re-paste BOTH embeds after any `component.html` change.** The season post
failed once with a stale embed against current JSON: controls rendered, but the
header row, the rows and the count line were all missing. That signature —
controls present, everything downstream absent — means `render()` threw partway,
not that the fetch failed (a failed fetch shows the error message and no
controls at all). Fixed by pasting the current file. Before debugging further,
always confirm which build is actually on the page.

Two things together got it there, after a false start:
1. The embed's `<style>` and `<script>` collapsed to one line each (below).
2. Pasting into a **Gutenberg Custom HTML block**, which bypasses `wpautop`.

The auction chart lives in the Classic editor's Text view; this post does not.
Don't assume a new post inherits the auction chart's editor.

## wpautop: the embeds MUST stay collapsed to one line per block
The user edits posts through the **Classic Editor's Text view**, which — unlike
a Gutenberg Custom HTML block — does **not** bypass `wpautop()` on the front
end. (Earlier advice in this file to "use a Custom HTML block" was wrong for
this site.) `wpautop` wraps blank-line-separated content in `<p>` tags and has
a long history of doing that *inside* `<script>`/`<style>`, corrupting both.
Symptom: the markup renders, the table stays empty, and **no error message
appears** — the `.catch()` never runs because the script never parsed.

`ff_auction_values` fought this across four rounds; see `web_chart_utils.py`
there for the full account, including the abandoned base64/`currentScript`
self-loader. The settled fix, now applied here in `build_embed.py`:

1. **Collapse each `<style>`/`<script>` body to a single line.** No line
   boundaries inside the tags means a line-based filter has nothing to act on.
2. **Strip every blank line** from the whole block — round 1 there failed
   because blank lines *around* the markers still triggered `wpautop` right at
   the `<script>` boundary, producing `<p><script>`.
3. **No `//` line comments, ever** — collapsing turns newlines into spaces, so
   one would swallow the rest of the script. `component.html` uses `/* */`
   exclusively and `assert_no_line_comments()` fails the build otherwise (its
   guard character class lets `https://` through).
4. **No tag-shaped strings in the JS** — WordPress's `force_balance_tags()`
   scans saved content for tag-shaped text and splices `<p>` into things like
   `'<td class="rank">'`, with no concept of `<script>` boundaries. Already
   satisfied: rows are built with `createElement`/`textContent`.

Verified after collapsing: `node --check` passes, and the collapsed embed was
rendered in a browser against real data — full table, styling and share bars
intact. The **dev copy stays uncollapsed** (`collapse=False`) since it never
goes through WordPress and readable source is the point. `usage_preview.html` is a frozen record of
the approved design (published as an Artifact for review) and does NOT
regenerate from `component.html` — it has its own copy so it can show two grids
on one page. If the component changes materially, either rebuild the preview by
hand or treat it as stale.

Vanilla JS, no library or CDN — matches `ff_auction_values`' approach and keeps
the embed dependency-free. Only external request is the Google Fonts `@import`
for Barlow Condensed (used for uppercase labels/headers); it degrades to
Arial Narrow. All CSS is scoped under `#f6p-usage` so nothing leaks into the
site theme, and form controls reset `margin`/`height`/`width` explicitly
because WordPress themes style those aggressively.

**Design — matches the site's own table convention**, taken from the user's
TablePress CSS (wpDataTables is styled the same):
```
header            background #cc5e03, white text
sorted / hover    background #660000, white text
```
So `--f6p-head` / `--f6p-head-fg` / `--f6p-head-active` carry those exactly.
`--f6p-accent` is the same orange (buttons, focus ring, active filter pills),
`--f6p-heat` the maroon (values ≥70%), `--f6p-bar` an orange tint.

**Single theme, deliberately.** The site is light-only, so there is NO
`prefers-color-scheme` block. An earlier version had one and viewers whose OS
was in dark mode got a dark table sitting inside the white page — visible in
the user's own screenshot of the live post. Every colour is stated explicitly
rather than inherited from the theme.

**Column groups.** Rushing and receiving never interleave. `gstart:true` on a
column marks the start of a group and draws a 2px `--f6p-rule` vertical line
down the full table:
```
Player Tm Pos Wk | Snaps Snap% SDD SDD% LDD LDD% 2Min 2Min%
                 | Rush Rush% I5 I5%
                 | Routes Rte% Tgts Tgt% TPRR Catch Catch% EZ EZ%
```
SDD/LDD/2Min are snap counts, not touches, so they group with Snaps rather
than with either touch group.

**No coloured text anywhere.** An earlier version turned values ≥70% maroon;
the user asked for it gone. `--f6p-heat` and the `.hot` rule are removed —
don't reintroduce emphasis colour without asking.

**SDD and LDD are collected but NOT displayed** — the user finds them too
FantasyLife-flavoured for the site, while still wanting them in the weekly
spreadsheet. They remain in the CSV (37 columns), in the JSON, and in
`SUM_COLS`/`RATES`; only their `COLUMNS` entries are commented out. This is
exactly the split the "everything in the file, a subset on the page" design
exists for — re-adding is two lines plus `python build_embed.py`, no re-fetch
and no re-upload.

**Season view has a Total / Per Game toggle** (`basis` state, season only).
Per Game divides the `type:"int"` columns by `games` to one decimal; `games`
and `week` are excluded, and every rate column is left alone because a
percentage or TPRR means the same thing on either basis. Verified on Puka
Nacua over 2 games: 76 snaps / 51 routes / 20 targets → 38 / 25.5 / 10, with
Snap% and TPRR identical across both. The meta line and the CSV filename both
record which basis is active.

`pct` cells are plain text (`.f6p-pct`), no share bar. An earlier version drew
a CSS-gradient bar behind each percentage; removed after the user asked twice
what the tan/yellow marks were -- not self-evident, cut rather than explained.
Player column is sticky on horizontal scroll; headers sticky on vertical.

The Weekly/Season toggle (`"both"` mode) renders into its own `.f6p-viewswitch`
row, separate from `.f6p-controls` (Team/Position/Search/week-range), with
heavier button styling (bigger padding, bold, thicker border). Reasoning: the
toggle changes the whole dataset and column set (Wk vs G), while the filters
only narrow within whichever dataset is already showing -- worth a visual
weight difference, not just a shared row. `.f6p-controls` gets a top border
+ padding only when `.f6p-viewswitch` is non-empty (`:not(:empty) +` sibling
selector), so a single-view build (empty viewswitch div) shows no orphaned
divider. `component_teaser.html` mirrors this with `.f6pt-viewswitch` (no
divider needed there since the teaser has no separate filter row).

**Column-definition key** (`component_key.html`) is a collapsible "What do
these stats mean?" glossary, plain `<details>/<summary>` -- no JS at all, so
it can't be broken by the wpautop fights the rest of this file is written
around. It briefly lived as two copies, one inside `component.html` and one
inside `component_teaser.html`, before the user pointed out the definitions
don't depend on membership status and asked whether it needed to be there
twice. It doesn't: `build_key()` in `build_embed.py` builds it once, and
`main()` places that one copy at the very top of `wp_page.html`, above both
the `[s2If-paywall]` and `[s2If-ads]` blocks (and therefore above each
component's own Weekly/Season toggle too) -- every visitor sees the same
single copy regardless of membership. `embed_key.html` is the standalone
build output; `usage_table.html`/`teaser_preview.html` (dev previews) each
splice it in for visual parity with the real page.

**`VIEW_MODE`** (`"weekly"` | `"season"` | `"both"`) is what makes two posts
work off one component: each post's build pins one view and the Weekly/Season
toggle is removed entirely. `"both"` is local dev only.

- **One component, both views.** A Weekly/Season toggle; Season aggregates
  client-side. Column list (`COLUMNS`) is one array — edit it alone to change
  what's displayed. Every column stays in the file and the CSV regardless, so
  cutting a column from the site doesn't lose it from your reference data.
- **Defaults** resolve from the data, so a new upload needs no code edit: week
  options are built from the weeks present, and the default is the newest week
  (~330-500 rows, not 6,000). Default sort is snaps descending — the one
  column comparable across RB/WR/TE.
- **`fetch(url, {cache:"no-cache"})`** revalidates instead of pinning `?v=` in
  the URL — a fresh upload is picked up with no code change, and an unchanged
  file returns 304 rather than re-downloading.
- Raw and % sit side by side (no toggle). Sticky header and sticky player
  column, horizontal scroll, CSV export of the current filtered view.
- Rows are built with `createElement`/`textContent` into a single
  `DocumentFragment` — required for WordPress (`force_balance_tags`), and it
  also avoids visible reflow at 6k rows.

Test locally (the fetch is relative, so it needs HTTP — opening the file
directly gives a `data:`/`file:` URL and the fetch fails):
```
python -m http.server 8765
# then open http://127.0.0.1:8765/usage_table.html
```

## Publishing (planned — reuse `ff_auction_values`, don't reinvent)
That project already solved this exact problem end to end; see its CLAUDE.md
rounds 9-10 before writing anything:
- S2Member gating via the site's real `[s2If-paywall]` / `[s2If-ads]` shortcodes
- WordPress REST API partial update against marker comments
  (`<!-- SECTION:START/END -->`), so only our block is overwritten
- Dedicated `f6p-automation` Editor-role account + Application Password
- **Build table rows with `document.createElement`/`.textContent`, never
  `innerHTML` string concat** — WordPress's `force_balance_tags()` mangles
  tag-shaped JS string literals on save
- Send a real User-Agent (Cloudflare blocks `python-requests` outright)
- SiteGround's host-level anti-bot CAPTCHA already has a `/wp-json/*` exemption
- Automation runs via GitHub Actions triggered by cron-job.org
  `workflow_dispatch` — **not** GitHub's native `schedule:` (user has had
  reliability problems with it, and double-runs mean double scraping load)

Difference from the auction chart: that one embeds its dataset inline in the
post. 707 KB is too big for that (post size, WP revision bloat) — host the
JSON as a separate uploaded file and have the grid `fetch()` it.

## Usage
```
python fetch_fantasylife_utilization.py --year 2026 --weeks 1-1   # in-season
python fetch_fantasylife_utilization.py --year 2025 --verify      # full season
python verify_aggregation.py --year 2025 --weeks 1-2              # after edits
python build_embed.py                                             # after component edits
```
1 call for season totals, 32 for the weekly log (0.4s throttle), ~40s total.
Writes dated CSV + JSON into `data/`, **plus an undated
`data/utilization_weekly.json`** — that fixed name is what gets uploaded each
week so the embed URL never changes and nothing needs renaming by hand.

Keep the dated CSVs: they're the full-fat reference copy (every column,
including ones the site doesn't display).

## Hosting the JSON (decided)
**Manual upload during testing** — user uploads the JSON by hand, no automation
yet. Target a fixed path, NOT the WordPress Media Library:
`/wp-content/uploads/f6p-data/utilization_{weekly,season}.json`.

Why not the Media Library: uploads land in date folders (`/uploads/2026/09/`)
that change monthly; re-uploading the same filename appends `-1`/`-2` instead
of overwriting, so the URL changes weekly; and WordPress rejects
`application/json` by default (`get_allowed_mime_types()` has no json entry)
unless an `upload_mimes` filter is added. A fixed folder avoids all three.

Called same-origin from the page, so no CORS:
```js
const res = await fetch('/wp-content/uploads/f6p-data/utilization_weekly.json?v=2026-w2');
const {cols, rows} = await res.json();
```
The `?v=` cache-buster matters because Cloudflare fronts the site.

**Unresolved: the JSON itself is public.** Anything under `/wp-content/uploads/`
is readable by anyone with the URL, so the *page* is paywalled but the *data*
is not. Options if this matters later: accept it (obscure URL); a small
mu-plugin REST route with an S2Member `permission_callback`, file stored
outside the web root; or a public teaser file plus a gated full file.

**Cadence when automated: twice weekly** — Monday (Sunday games) and Tuesday
(picks up Monday Night Football). Reuse `ff_auction_values`' publish stack
(see its CLAUDE.md rounds 9-10) and cron-job.org `workflow_dispatch`.

## Gating: use s2Member's own protected directory
The site already has `/wp-content/plugins/s2member-files/`, which s2Member
protects with an `.htaccess` deny and serves through a gateway URL:
`/?s2member_file_download=utilization_weekly.json`. Same-origin, so the
browser sends the session cookie and `fetch()` just works — no mu-plugin
needed, and it closes the "the page is gated but the JSON isn't" hole.

Two things to confirm on a real page before relying on it: s2Member **counts
file downloads** and can cap them per member (a table that fetches on every
page load would burn an allowance — set that level to unlimited), and it
typically serves files as attachments, so check the JSON parses rather than
triggering a download prompt.

## Publishing — MANUAL. The user pastes; nothing pushes to the site.
**The post is created once and then left alone.** The user pastes the embed
into a Custom HTML block inside the paywall shortcodes, by hand:
```
[s2If-paywall]
<!-- F6P_USAGE:START -->
...contents of embed_weekly.html...
<!-- F6P_USAGE:END -->
[/s2If-paywall]
```
The **twice-weekly refresh replaces only the uploaded JSON**, same filename
every time — the post content never changes on a data update. The only reason
to re-paste is a `component.html` change (a column cut, a rename), and that's
rebuild-and-repaste, not a recurring step.

Do NOT push to the live site. `push_to_wordpress.py` exists (marker-based,
dry-run capable, verified offline) but is **unused by choice** — it was built
on a misread and kept only in case automation is ever wanted. The markers stay
useful regardless: they delimit the block for a clean manual re-paste.

Three things carried over from `ff_auction_values` (its CLAUDE.md rounds 9-10
has the full history), all still required:
- **Real User-Agent** — Cloudflare blocks `python-requests` outright.
- **`diagnose_and_parse_json()`** — a 200 OK with a non-JSON body is a real
  failure mode here (SiteGround's anti-bot CAPTCHA answering instead of
  WordPress). Dump status/headers/body whenever the status isn't 2xx *or* the
  body won't parse, or the next failure is a bare `JSONDecodeError`.
- **`re.sub` replacement passed as a function, never a string** — the CSS/JS
  contains `content:"\25BC"` and `"\n"`, which `re.sub` would otherwise read as
  backreferences and corrupt.

The embed files contain their own marker pair (they're also hand-pasteable), so
`inner_block()` pushes only what's *between* them — otherwise the post ends up
with nested markers. Verified offline before first use: shortcodes and
surrounding copy preserved, backslash sequences intact, idempotent on a repeat
push, and it refuses a post with no markers rather than guessing.

Credentials come from `ff_utilization/.env` (see `.env.example`) or the real
environment, which wins — so GitHub Actions secrets are unaffected. Confirmed
`ff_utilization/.env` is covered by the repo's root `.gitignore`.

## FINAL, SETTLED architecture: exactly ONE post, both audiences, both views
This took three passes to land on — recorded here so it doesn't get
re-litigated. In order: (1) built a weekly/season toggle thinking that's what
"one page" meant; (2) that turned out wrong — the user's live weekly post
actually paired the single-view member embed with its teaser via
`[s2If-paywall]`/`[s2If-ads]` on ONE post, so I built a matching single-view
season post; (3) the user then clarified they want ONE POST TOTAL — the
toggle from step 1, but with the teaser ALSO given a toggle so non-members
can preview both views too, not just one.

**What ships**: a single `wp_page.html`, generated whole by `build_embed.py`,
containing both audiences:
```
[s2If-paywall]
...embed_combined.html content (member, Weekly/Season toggle)...
[/s2If-paywall]

[s2If-ads]
...embed_teaser_combined.html content (non-member, Weekly/Season toggle, locked columns)...
[/s2If-ads]
```
Paste `wp_page.html` whole into the one post's Custom HTML block. No other
file goes on the site.

**Why the teaser needed its own toggle, not just one flavor**: the member
side already advertises both views exist (that's the whole toggle). Showing
a non-member only a weekly-flavored (or only season-flavored) teaser would
undersell the product — they'd have no way to know season data is even part
of what they're paying for. Matching toggles on both sides keeps the preview
honest about what membership actually includes.

**Real bug caught in testing, not just plausible-looking code**: the
teaser's `render()` appended new `<th>`/`<td>` elements on every call without
clearing the previous ones first — harmless for a single-fetch single-render
teaser, but the new toggle calls `render()` on every click, so switching
Weekly→Season→Weekly would have silently duplicated every header and row.
Fixed by clearing `hrow`/`tbody` at the top of `render()`, same as the member
table already did. Verified directly: toggled the teaser three times in a
row and confirmed header count held at 17 and row count at 30 throughout, not
accumulating.

**`embed_weekly.html` / `embed_season.html` (single-view member) are still
generated by the build** — harmless leftovers of the build loop, not
deleted, but NOT what's published. Only `wp_page.html` (built from
`embed_combined.html` + `embed_teaser_combined.html`) goes on the site.
Don't assume any of the single-view or split-teaser files from earlier in
this project's history are still live without checking `wp_page.html`
itself first — this file was rebuilt from scratch twice already as the real
requirement got clarified.

## Where it goes on the site
**Posts, not pages** — verified against the live site: every existing tool is
a post (`/fantasy-football-auction-values/` → `postid-165937`, which is the
same id `push_to_wordpress.py` targets; `/fantasy-football-adp/` →
`postid-130172`; `/fantasy-football-rb-projections/` → `postid-128392`).
WordPress marks pages `page-id-` instead.

**One post** — settled after two revisions, see "FINAL, SETTLED architecture"
above. Both the season-long and weekly search intents are served by the SAME
post/URL, since the member table's toggle covers both views. The earlier
two-posts-for-SEO plan is superseded.

Only the three JSONs change on the user's cycle (they chose to update the
teasers every week too, not just occasionally); the post content
(`wp_page.html`) is written once and only changes when `component.html` or
`component_teaser.html` does. `push_to_wordpress.py` is therefore an
occasional tool here, not part of the recurring cycle.

## Non-member teaser — ONE, with its own Weekly/Season toggle
`build_teaser.py --view weekly|season` writes the two data files
(`utilization_teaser_weekly.json` / `utilization_teaser_season.json`) as
before, but `component_teaser.html` now fetches BOTH up front (each ~1KB, no
reason to make the toggle trigger a network request) and switches between
them client-side with a segmented button matching the member table's own
toggle style. `build_embed.py` emits one `embed_teaser_combined.html` from
this, not two separate files. **No CSV export in the teaser at all** —
verified directly (`grep`/DOM search for "export csv", zero hits) — and
confirmed the member table's export button survived untouched.

**No player-count cap, and a real Position/Team/Search filter row** (added
after the top-10-per-position design above). The user's reasoning: showing
four raw counting stats (Snaps, Rush, Targets, Rec) isn't enough of the actual
product to also justify rationing the list down to 10-per-position or hiding
the filter controls -- both restrictions existed to make a small curated list
presentable, and once the list isn't small there's nothing left to ration.
`build_teaser.py --top` still exists (for a smaller manual preview) but
defaults to `None` = no cap; a typical weekly run now produces every RB/WR/TE
in the published file (~300+ rows) rather than 30. `component_teaser.html`
grew the same three filters as the member table -- Position pills (All/RB/
WR/TE), a Team `<select>`, and a Search input -- built into `.f6pt-controls`
(previously always empty) with the same divider-only-when-non-empty CSS
pattern component.html uses between `.f6p-viewswitch` and `.f6p-controls`.
No column-header sorting was added (out of scope for what was asked); the
list keeps the server's snaps-descending order and filters narrow it.

**Season teaser is a plain sum, not a rate recomputation** — genuinely
simpler than the member table's season aggregation, because none of the
three shown columns (Rush, Targets, Rec) is a percentage. Sum rush_att/
targets/rec per player across every week in the published file, no
numerator/denominator pairing needed. Validated by hand: summed Bijan
Robinson across 2025 wk1-2 both by script and by manually adding the two
weekly rows -- 34 rush / 12 targets, exact match. (That test's `rec`
happened to read 0/0 because the 2025 wk1-2 nflverse CSV predates the
receptions column entirely -- stale test fixture, not a bug; confirmed by
checking the file has no `rec` column at all. The season-SUM logic itself
was still genuinely exercised and correct.)

The meta line above the table now reads client-side-computed count + label,
e.g. "318 players — Week 1", mirroring the member table's bold-count-plus-
label pattern (`mCount`/`mRange`) instead of the old server-baked "Top 10 per
position — Week 1" string -- the count has to be client-side now since it
depends on which filters are active, not just which JSON loaded. The JSON's
`label` field is unchanged; `top` is still written (`null` when uncapped) but
no longer drives the displayed text.

**Unlocked** (the user's own reasoning: these already appear in any ordinary
box score, so nothing competitive is lost): Player, Team, Pos, Snaps, Rush,
Targets, Rec. **Locked** (the actual product): Snap%, Rush%, I5, I5%, Routes,
Rte%, Tgt%, EZ, EZ%, ADOT — full header shown (so visitors see what exists),
cell shows a lock icon instead of blurring real text (blur-over-text renders
inconsistently and looks broken more than "premium"). Snaps moved from locked
to unlocked in the same change that removed the player-count cap and added
the filter row -- see above.

**Must live OUTSIDE the s2member-files gateway.** That gateway checks
membership before serving anything in its folder — gating the teaser there
would defeat the entire point. Needs its own plain public path, e.g.
`/wp-content/uploads/f6p-data/utilization_teaser.json` (`build_teaser.py`
prints the reminder every run).

**Real CSS bug hit and fixed**: a generic `.f6pt-table td{background:...}`
rule silently beat the more-specific-looking `.f6pt-locked-cell{background:
...}` rule, because the generic rule carries a `td` type selector and the
locked rule was class-only — specificity, not source order, decides ties.
Locked cells rendered pure white with zero visible tint until the locked
selector was rewritten to repeat `td` and match that weight. Caught by
reading `getComputedStyle(...).backgroundColor` directly rather than trusting
a screenshot — the tint is genuinely subtle at normal viewing size.

**Join URL and promo copy are live**: `https://fantasysixpack.net/plans`, plus
a promo-code line ("F6PNFL26", 15% off) under the button — the CTA action
area is a flex column (button + promo stacked) nested inside the outer flex
row (description text | action), so the promo text doesn't wrap into the row
and float away from its button.

## Teaser refresh cadence: weekly, same as everything else
An earlier plan here called for refreshing the teaser JSONs only occasionally
(monthly, or when the top-10 list looked obviously wrong), reasoning that a
non-member had no baseline to know a curated list was stale. Superseded: the
user decided to just refresh all three files every week
(`utilization_weekly.json`, `utilization_teaser_weekly.json`,
`utilization_teaser_season.json`), and the teaser dropping its player-count
cap makes that the only sensible choice now anyway -- a full, filterable
player list going stale is a lot more visible than a curated top-10 list
going stale. See "Where it goes on the site" above for the actual 3-upload
cycle.

## Removed after user feedback: the percentage share-bars
Every `pct` cell briefly had a background bar sized to its value. Cut — the
user asked what it was **twice**, which is itself the verdict. Don't
reintroduce a "clever" visualization without a clear read on why the plain
number wasn't enough.

## Position filter is multi-select, in both component.html and component_teaser.html
Was a single-select segmented control (`pos = "ALL"|"RB"|"WR"|"TE"`, clicking
one turned the others off) -- user asked to select multiple positions at
once (e.g. RB+WR together). Now `posSet` (a `Set`, default all three) backs
the filter predicate (`!posSet.has(r.pos)` instead of `pos !== "ALL" &&
r.pos !== pos`).

Click semantics (user-specified, not the first thing shipped -- see below):
starting from the default all-three-on state, clicking one position
**isolates** to just that one (`posSet.clear(); posSet.add(p)`) rather than
toggling it off the full set -- toggling off would have left the other two
on, which reads as "I clicked RB and RB turned off." From a narrowed
selection, clicking a *different*, not-yet-active position **adds** it
(ordinary multi-select toggle-on). Clicking the last remaining active
position is a no-op (`if (posSet.size > 1) { posSet.delete(p); }`) -- never
zero positions selected, which would just show "no players match." Getting
back to all-on works two ways: click through the remaining unselected
positions one at a time (naturally lands on all three, at which point "All"
re-lights itself), or click "All" directly as a shortcut that sets all three
at once. "All" is styled "on" only when `posSet.size === POS_OPTIONS.length`
-- a derived display state, not a fourth value stored alongside RB/WR/TE.

First pass shipped plain independent toggles (click any button, it flips
just that one, floor of one stays selected) -- functioned, but felt wrong
the moment you clicked a single position from the default all-on state,
since it just turned that one off and left the other two, not what "select
only this position" should do. Corrected to the isolate-from-all behavior
above once described. Identical implementation copied into both files since
they don't share JS. Verified in-browser end to end: RB-only isolates
correctly, WR click after that adds (RB+WR), TE click after that completes
the set and re-lights "All", and the "All" shortcut restores the full row
count from any narrowed state.

## Rams display as LAR, not LA (Chargers stay LAC)
User request: "LA" alone read as ambiguous sitting next to "LAC" in the
team filter/dropdown -- which team is "LA"? Fixed at the source in both
fetch scripts, not just relabeled after the fact, since the team code
feeds a real join, not just display:

- `fetch_nflverse_utilization.py`'s `TEAM_FIX` flipped from `{"LAR": "LA",
  ...}` to `{"LA": "LAR", ...}` -- nflverse's own source files disagree
  with each other on LA vs LAR depending on which one you're reading, and
  `TEAM_FIX.get(team, team)` already normalizes whichever spelling shows
  up to one consistent value; only the target spelling changed.
- `fetch_fantasylife_utilization.py` needed a separate, explicit fix:
  FL's API expects `"LA"` as the query parameter (that's still in the
  `TEAMS` list, unchanged -- renaming the query itself would risk
  breaking the actual API call), but the OUTPUT row's team label is
  rewritten `"LA" -> "LAR"` right after FL's response is read.
- Both had to change together, not just the display-facing one:
  `build_published.py`'s surname-fallback match key (used when the two
  feeds spell a name differently) is `(surname, team, week, pos)` --
  built from FL's team on one side, looked up using nflverse's team on
  the other. Changing only one side's spelling would have silently
  broken that fallback path for any Rams player who needed it (the
  primary match, on normalized full name, doesn't involve team at all,
  so it wouldn't have failed loudly -- just quietly dropped a player).
  Verified after rebuilding: join rate unchanged (685/771, 89%, same
  single non-Rams warning as before), and confirmed by name that Kyren
  Williams/Blake Corum/Davante Adams/Terrance Ferguson all still have
  real snap/route/target data under `team=LAR`, not zeros.

The grid's team dropdown needed no code change at all -- `component.html`/
`component_teaser.html` build it dynamically from whatever team codes are
actually in the fetched data (see "Position filter is multi-select" above
for the equivalent pattern on positions), so once the data said `LAR` the
tool just showed it.

## Season view didn't actually default to the full season
`buildControls()` ran exactly once, at page load. The Week/Range label, the
season-only Total/Per Game toggle, and the default `wkFrom`/`wkTo` were all
fixed at whatever `view` happened to be at that one moment (`"weekly"`,
since that's the initial default) and never touched again -- the Weekly/
Season toggle's click handler only changed the `view` variable and called
`render()`, nothing rebuilt the controls themselves. Consequence: clicking
over to Season kept showing "Week" as the label, kept the single-week range
Weekly had been on, and the Total/Per Game buttons never appeared at all --
Season silently behaved like "Weekly aggregated over one week," which looks
identical to Weekly and defeats the entire point of the tab. Caught by the
user asking for Season to default to the full range; testing confirmed it
currently didn't default to anything sensible in either direction.

Fixed by pulling the view-dependent pieces (the label, the two week
`<select>`s, and the Total/Per Game group) into their own
`buildWeekControls()`, called once at startup like before AND again inside
the toggle's click handler, alongside resetting `wkFrom`/`wkTo`/`basis` each
time using the same expression the original startup code used
(`wkFrom = (view === "season") ? WEEKS[0] : WEEKS[WEEKS.length - 1]`) --
Season now always opens on week 1 -> current, Weekly always resets back to
just the current week, symmetrically. The rebuilt container
(`weekHolder`) uses `display:contents` so re-filling it on every toggle
doesn't disturb the flex layout of the filter row it sits in alongside
Position/Team/Search. `component_teaser.html` never had this bug -- it has
no week-range selector at all, just a straight swap between two already-
fetched datasets. Verified in-browser: Season now opens on "Range" / week
1-3 / with Total+Per Game buttons present; toggling to Per Game changes
values as expected; switching back to Weekly resets to "Week" / week 3-3
with no Total/Per Game group, and the cycle repeats correctly on repeat
toggles.

## FL-not-ready now aborts the whole run instead of just warning
The loud `*** WARNING ***` added earlier (see the FL-lag bug in
`fetch_nflverse_utilization.py`'s section above) printed but still let
`run_weekly.py` carry on to build the teasers and upload -- harmless in
practice (re-uploading a file that's a near-duplicate of what's already
live), but the user's actual requirement is stronger: if FL isn't ready,
NOTHING downstream should run at all, and they want to be notified rather
than have to notice a warning buried in a log they weren't looking at.

`build_published.py` now `sys.exit(FL_NOT_READY_EXIT_CODE)` (== 3, chosen
to not collide with argparse's own exit(2)) right after printing that
warning, instead of continuing on to write the upload-bound JSON as if
everything were fine. `run_weekly.py` defines the identical constant and
checks for it specifically in `run()` (an `allow_exit_code` parameter --
that one exact code returns normally instead of being treated as a crash),
then stops the whole chain with its own clear message before `build_teaser.py`
or `sftp_upload.py` ever run. Any OTHER nonzero exit from `build_published.py`
still hits the generic FAILED path, unchanged.

A failed exit here is also what makes GitHub's own "workflow run failed"
email fire for a scheduled cron-job.org-triggered run -- that's the
notification mechanism, no new integration built. Caveat: this depends on
the account's GitHub notification settings for Actions actually being
enabled; worth the user double-checking that rather than assuming it's on
by default.

Verified with a synthetic test (fake year 9999, one official-basis row with
zero matching FL rows at all) rather than waiting for a real FL-lag window:
confirmed `build_published.py` alone exits 3 with the right message, and that
`run_weekly.py`'s `run()` correctly treats exit 3 as "stop cleanly," not "crash."
Test files were written under the shared `data/utilization_weekly.json`
filename (same file `sftp_upload.py` reads) since `build_published.py` writes
there unconditionally before the newest-week check runs -- caught immediately
after (before any upload), restored by rebuilding the real 2026 week 1-3 data,
confirmed via `sftp_upload.py --dry-run` that local matched what was already
live. The live site itself was never touched by the test; only a local file
briefly held test data, and only between build steps that never reached SFTP.

## Open / next
1. ~~Point the teaser CTA at the real join URL.~~ Done — `https://fantasysixpack.net/plans` + promo code F6PNFL26 text.
2. ~~Decide whether the teaser goes on one post or both.~~ Done — one post,
   both views via matching toggles. See "FINAL, SETTLED architecture" above.
3. ~~Automate the upload.~~ Done — `sftp_upload.py` (SFTP, SSH key or
   password) and `run_weekly.py` (all 5 build steps + upload, with a
   dry-run + confirm prompt before it writes). Still one manual weekly
   invocation, by choice -- see `run_weekly.py`'s docstring for why the
   confirm step stays.
4. Confirm the s2Member download-count and content-type behaviour noted
   earlier for the gated file (unaffected by the teaser, which bypasses
   s2Member entirely).
