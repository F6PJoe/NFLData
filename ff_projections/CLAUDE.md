# Own NFL Projections — Research & Design

## Goal
Build **my own** season-long stat-line projections from raw NFL data
(Sportradar), rather than averaging other people's projections. Sibling
to `ff_draft_proj`, which pulls 11 sources and averages them into a consensus.

### The shape of the thing: a usage spreadsheet
The deliverable is an **Excel workbook**, not a black-box model. The split:

> **The machine computes team totals. I enter usage. Excel does the math.**

Per team, the model projects season totals (plays, pass/rush attempts, yards,
TDs). Per player, I enter a **share of that team's volume** — target share,
carry share, red-zone share. Excel multiplies share × team total, applies
efficiency rates, and produces the stat line and fantasy points live as I type.

This is how most people build projections by hand, and the division of labor is
right: **volume and rates are a data problem; role and usage are a judgment
problem.** Automating the judgment half is where projection models go wrong —
they can't know that a team just signed a bell-cow back or that a rookie is
running with the ones. I can. So the code's job is to get team totals right, to
pre-fill every share cell with a sane data-driven default, and to make the
arithmetic and the sanity checks free.

Formulas live **in the workbook**, not in Python, so edits recalc instantly
without re-running anything. Python builds the workbook and reads it back out.

*(This section describes the original share/percentage-entry vision — what
v1 built. v2, the active workbook, keeps the same division of labor but has
you type the raw stat line directly instead of a share; see Status below.)*

### This is NOT a consensus source — do not wire it into `ff_draft_proj`
These projections stay **completely separate** from the consensus. They are
never added as a source to `ff_draft_proj/build_consensus.py`, never averaged
in, never blended. The endgame is that this project **replaces** the consensus
as the projection layer feeding the rest of the repo.

Two hard consequences for the design:

1. **No circular input.** This model is built only from raw NFL data
   (Sportradar, plus nflverse for the snap/route gap). It never reads
   `consensus_*.csv` or any per-source projection CSV as an input — not as a
   prior, not as a sanity clamp, not as a fallback for missing players. If it
   borrowed from consensus it would just be laundering other people's numbers,
   which defeats the entire point.
2. **It must stand alone.** Because it eventually replaces consensus rather
   than joining it, it has to cover the full player pool on its own and
   compute its own fantasy points — it can't lean on the consensus layer for
   either. See "Output" in Part 4.

Consensus is still useful as an **offline benchmark** — where my numbers
disagree with the market is worth looking at, and consensus is the yardstick
for accuracy-testing this model against actuals. That's a human-in-the-loop
comparison run separately, not a data dependency in the pipeline.

**Status (current): v2 is the only active workbook. v1 is frozen — do not
extend or fix it, even for a bug found while touching shared code.**

Two workbook designs got built over the course of this project:

| | v1 | v2 — **the one in use** |
|---|---|---|
| script | `build_workbook.py` | `build_workbook_v2.py` |
| file | `my_projections.xlsx` | `my_projections_v2.xlsx` |
| you enter | a **share** (%) of team volume | the **raw stat line** directly (attempts, yards, TDs) |
| yards/TDs | computed, normalized to sum to the team total | typed; footer flags red/amber if your sum strays from the team total |

v1 is the design described in "The shape of the thing" and most of Part 4
below (percentage entry, self-balancing shares) — that write-up is accurate
**history of how v1 works**, not a description of the current workbook. The
user made the v1→v2 call explicitly; v1 gets no further bug fixes or feature
work. If a bug is found in code v1 and v2 both use (`teams.py`, `names.py`,
the fetch/build data-layer scripts, `manual/*.csv`), fix it there — that's
shared and still live — just don't extend `build_workbook.py` itself.

**Everything upstream of the workbook is shared and still fully active**:
Sportradar/nflverse/Sleeper fetch layer, `build_team_totals.py`,
`build_rosters.py`, `build_shares.py`, `build_history.py`,
`manual/overrides.csv`, `manual/coaching_changes.csv`. Both workbooks are
generated from the same CSVs; only the sheet mechanics differ.

Built and verified (**no API key needed for the free sources** — nflverse
CSVs + the public Sleeper endpoint; Sportradar needs the key in `.env`):
- `fetch_nflverse.py` / `fetch_sleeper.py` / `fetch_sportradar.py` — the raw
  data layer. See Part 2/3 below for what each is for.
- `teams.py` / `names.py` — team-abbreviation and player-name normalization,
  used everywhere in this project.
- `build_team_totals.py` → `team_totals_history.csv`, `team_totals_2026.csv`
  — projected team-level control totals (plays, pass rate, yards, TDs),
  regression-to-mean dial included. See "Regression to the mean" finding below.
- `build_rosters.py` → `rosters_2026.csv` — current roster, depth-ordered,
  merging Sleeper (team/injury) + nflverse (depth-chart fallback, id bridge)
  + `manual/overrides.csv` (the last word on anything both sources miss).
- `build_shares.py` → `player_shares.csv` — 3-yr per-player market share,
  role-blended for rookies/team-changers, red-zone ratios, efficiency
  multipliers. The seed data both workbooks are built from.
- `build_history.py` → `player_history_2026.csv` — raw per-season counting
  stats per player (v2-only input; v1 uses shares instead).
- `manual/overrides.csv`, `manual/coaching_changes.csv` — hand-maintained,
  git-tracked, survive every rebuild. **Not optional** — see findings below.

v2-specific:
- `build_workbook_v2.py` → `my_projections_v2.xlsx`. Seeds from
  `--seed consensus|last-season|blank` (default `last-season` — consensus
  is a one-time bootstrap, not a recurring default, see the seeding note
  below). `--merge` preserves every typed cell across a rebuild, keyed by
  (player, team); `--force` discards and backs up; a plain rebuild refuses
  once Excel has saved the file. Tested against a real team-change scenario
  (edits correctly dropped only for the moved player) and a real slot-count
  widening (edits survived, keyed by identity not row position).
- `build_rankings.py` → `my_projections_v2_rankings.xlsx` (or
  `rankings_only.xlsx` — **do not confuse this with the main file**, it's a
  separate static output, position tabs only, no team tabs). Reads the live
  workbook read-only (works even while it's open in Excel) and scores every
  format via `ff_draft_proj/scoring.py` — not reimplemented, imported.
- `compare_to_consensus.py` — sanity-checks against `ff_draft_proj` consensus.
  Benchmark only, never a pipeline input (see "NOT a consensus source" above).

---

## Part 1 — What the methodology actually is

All four reference articles (Footballguys/Brown, Yards Per Fantasy,
TeamRankings, FantasyData) describe the same skeleton. Nobody projects a
player's stat line directly. Everyone builds a **top-down funnel**:

```
team play volume
  └─> pass/run split           → team pass att, team rush att
        └─> player market share → player targets, player carries
              └─> efficiency rates → yards
                    └─> share of team TDs → player TDs
                          └─> × projected games played
                                └─> scoring formula → fantasy points
```
This is exactly the workbook described above: everything above the "market
share" line is computed, the share line is where I type, everything below it is
arithmetic.

The reason this works: **volume is projectable, production is not.** Market
share and play volume are stable year-over-year; yards-per-carry, catch rate,
and especially touchdowns are mostly noise. So you project the stable thing
and apply league-average-ish rates to it.

### The seven inputs, in order

| # | Layer | What you need | Stability |
|---|---|---|---|
| 1 | Team plays/game | 3-yr trend, pace, coaching change | High |
| 2 | Pass rate | 3-yr trend, game script, QB rushing | High |
| 3 | Team TDs | 3-yr team TD rate regressed to mean (Vegas optional) | Medium |
| 4 | Player target share / carry share | Prior-yr share, **vacated volume**, depth chart | **Highest — this is the core** |
| 5 | Efficiency (aDOT, catch%, YPC, YPR) | 3-yr weighted, regressed to positional mean | Low-medium |
| 6 | TD share | Red-zone & goal-line opportunity share, **not prior TDs** | Low |
| 7 | Games played | Age, injury history, depth chart risk | Medium |

### Where the old articles are wrong / dated

The Footballguys piece (2015) and Yards Per Fantasy are directionally right but
predate the analytics that matter. Four corrections:

1. **Don't project TDs from prior TDs.** Season-level TD totals have near-zero
   year-over-year correlation. Project *opportunity* (carries inside the 10,
   targets inside the 10, air yards into the end zone), then apply league TD
   rates by field position. This is "expected TDs" (xTD). Raw red-zone
   aggregation is a blunt instrument — scoring rate changes steeply *within*
   the red zone, so bucket by actual yard line, not by "inside the 20."
2. **Regress efficiency, don't carry it forward.** A WR's catch rate or a RB's
   YPC on 150 carries is mostly sample noise. Shrink each player's rate toward
   the positional mean, weighted by sample size (empirical Bayes / James-Stein
   shrinkage). Volume gets carried forward; rates get shrunk.
3. **Anchor team totals to *something* forward-looking, not raw last year.**
   The articles reach for Vegas here, and for a weekly model that's right —
   implied team total = `(O/U ÷ 2) − (spread ÷ 2)`. For a preseason
   season-long model it matters much less than it sounds: team strength really
   only drives the **team TD** cell, and that cell is a hand-editable input on
   the team tab. 3-yr weighted rates regressed to the league mean, plus my own
   judgment where I have one, is enough. See Part 3.5 for why odds are out.
4. **Model vacated volume explicitly.** The single biggest driver of
   year-over-year fantasy change is *targets and carries that left the
   building* — free agency, trades, retirements, injuries. Sum last year's
   share held by departed players, then redistribute it. This is a data
   problem (roster diff), not a vibes problem, and it's the highest-leverage
   thing to automate.

### The reconciliation step — solved for free by working in shares

Brown's article says: after projecting everyone, check that the sum of
receiving yards matches QB passing yards, and if not, hand-adjust the QB down.
That's a real problem when you project players in **absolute** numbers — you
end up with 32 teams whose parts don't add up, and fixing it by hand is the
most tedious part of building projections. The general solution is iterative
proportional fitting (IPF / raking): rescale players so column sums hit the
team control totals while preserving relative shares.

**We don't need it, because entering usage as a share makes the constraint
structural.** If a team's target shares sum to 100%, player targets sum to team
pass attempts by construction — there's nothing to reconcile afterward. The
only check needed is "does each team's share column sum to 100%," which is one
SUMIF and a conditional format (the `Balance` tab, below).

Keep IPF in the back pocket for one case: a bulk auto-normalize button when
I've been editing a team and drifted off 100% and don't want to hand-balance.

---

## Part 2 — Sportradar: what maps to what

**API:** NFL v7, REST, JSON. Base path pattern:
`https://api.sportradar.com/nfl/official/{access_level}/v7/{lang}/...`
`access_level` is `trial` or `production`. API key goes in the request
**header** (`x-api-key`), not the query string.

### Endpoints that matter, ranked by value

| Rank | Endpoint | Path | Gives us | Calls/season |
|---|---|---|---|---|
| 1 | **Seasonal Statistics** | `/seasons/{yr}/{REG}/teams/{team_id}/statistics.json` | The workhorse. Full player + team stat lines: targets, air yards, YAC, catchable passes, drops, red-zone attempts, red-zone targets, broken tackles, first downs, games played, games started | **32** |
| 2 | **Season Schedule** | `/games/{yr}/{REG}/schedule.json` | Every game ID, bye weeks, opponents, home/away, venue, weather | **1** |
| 3 | **League Hierarchy** | `/league/hierarchy.json` | 32 team GUIDs + conference/division. Needed once to seed everything else | **1** |
| 4 | **Game Statistics** | `/games/{game_id}/statistics.json` | Same fields as #1 but per game → per-game rates, in-season role changes, post-injury splits, "since week N" usage | 272 |
| 5 | **Play-by-Play** | `/games/{game_id}/pbp.json` | Down, distance, yard line, play type, personnel, per-play player stats. **The only way to build a real xTD/xFP model** | 272 |
| 6 | **Weekly Depth Charts** | `/seasons/{yr}/{REG}/{wk}/depth_charts.json` | Starter vs backup (`depth: 1` = starter), by week. Role confirmation + vacated-volume reallocation | 18 |
| 7 | **Weekly Injuries** | `/seasons/{yr}/{REG}/{wk}/injuries.json` | Injury + practice status → games-played model, and explains usage anomalies | 18 |
| 8 | **Team Roster** / **Free Agents** / **Daily Transactions** | `/teams/{id}/full_roster.json`, `/league/free_agents.json`, `/league/{date}/transactions.json` | **Who is where NOW.** Diff vs last season's roster = vacated volume. Critical | 32 + 1 |
| 9 | **Player Profile** | `/players/{player_id}/profile.json` | Age/DOB, draft round & pick, height/weight, per-season career line. Age curves + rookie draft capital | 1/player |
| 10 | **Draft Summary / Prospects** | `/{yr}/draft/summary.json` | Rookie draft capital — the best single predictor of rookie usage | 1 |

Everything else (Awards, Standings, Tournaments, League Leaders, Push feeds)
is irrelevant here. Push feeds are for live in-game apps.

### Field-level: what Sportradar's charted stats give you

Confirmed present in the statistics feeds — this is genuinely good coverage and
better than most free sources:

- **Passing:** air yards, attempts, completions, yards, TD, INT, sacks, sack
  yards, first downs, rating, **pocket time / avg pocket time**, hurries,
  knockdowns, batted passes, **dropped passes**, **on-target throws**, poor
  throws, spikes, **throw aways**, **red zone attempts**, blitzes
- **Rushing:** attempts, yards, TD, avg, first downs, **kneel downs**,
  **scrambles**, **broken tackles**, tackles for loss, **red zone attempts**,
  **yards after contact**
- **Receiving:** receptions, **targets**, yards, TD, **air yards**, avg,
  **yards after catch**, yards after contact, first downs, **broken tackles**,
  **red zone targets**, **catchable passes**, **dropped passes**

Note the bolded ones — throw aways, spikes, and kneel downs let you compute a
*clean* denominator for market share (targets shouldn't be charged for a spike;
team rush attempts shouldn't include victory-formation kneels). Catchable
passes lets you separate a receiver's drops from a QB's bad throws, which
ordinary catch rate conflates.

### What Sportradar does NOT have

Verified absent from the NFL API — these are real gaps, plan around them:

| Missing | Why it matters | Fill from |
|---|---|---|
| **Snap counts / snap share** | Best single role indicator, esp. for RB committees and rookie ramp-ups | nflverse `import_snap_counts()` (PFR-sourced), free |
| **Routes run / YPRR / route participation** | The best WR/TE metric, full stop. Target share alone can't distinguish "low share, few routes" from "low share, many routes" | nflverse (FTN charting), PFF (paid) |
| **Vegas win totals / game lines** | Would anchor team TD totals | **Not used** — see Part 3.5. Season win totals aren't in odds-api anyway, and the team-TD cell is a hand input |
| **Next Gen Stats** (separation, cushion, time to throw) | Marginal for season-long, useful for WR breakout modeling | nflverse `import_ngs_data()`, free |
| **Contracts / cap** | Predicts usage commitment & offseason moves | nflverse contracts, free |
| **Combine / athleticism** | Rookie projection | nflverse `import_combine_data()`, free |
| **Coaching & scheme changes** | Drives pace and pass-rate shifts | Manual — a small hand-maintained CSV |

**Honest assessment:** nflverse (`nflreadpy` / `nfl_data_py`) is free, covers
1999–present, and includes play-by-play, snap counts, participation, NGS, PFR
advanced stats, and depth charts. For a purely private model it would cover
most of this without any Sportradar spend.

Sportradar earns its place for three specific reasons:
1. Its **charted stats** (pocket time, catchable passes, broken tackles, on-target
   throws, throw aways) are cleaner and available in one seasonal call rather
   than assembled from PBP.
2. **Current-season depth charts, injuries, and transactions** via a real API —
   nflverse's offseason roster data is patchier and update timing is less
   predictable.
3. **It's licensed.** This repo publishes to WordPress
   (`ff_auction_values/push_to_wordpress.py`). Publishing numbers derived from
   scraped PFR data is a different risk posture than publishing numbers derived
   from a Sportradar contract.

Recommended: **Sportradar as the spine, nflverse to fill the snap/route gap.**

---

## Part 3 — Call budget (NOT a constraint — see below)

**We are not on the trial.** The 1,000-call/30-day/1-QPS figure below applies
only to Sportradar's free trial tier — our access is well beyond that, so call
budget is **not** a design constraint here. Plan B is on the table. Still cache
everything (a parse bug shouldn't cost a round trip) and throttle politely, but
stop designing around a quota that doesn't apply.

Per season of history, at minimum:

```
league hierarchy         1   (once ever — team GUIDs are stable)
season schedule          1   per season
seasonal statistics     32   per season  ← the workhorse
---------------------------------------
subtotal                34   per season
```

Optional per-game depth:
```
game statistics        272   per season
play-by-play           272   per season
weekly depth charts     18   per season
weekly injuries         18   per season
```

### What Sportradar is actually FOR, now that calls are cheap

nflverse + Sleeper already cover historical team stats, historical player
stats, rosters, injuries, depth charts, snap counts, and play-by-play — all
free. So the question isn't "can we afford Sportradar," it's "what does it add
that we don't already have."

**The answer is red-zone opportunity, and it matters more than it sounds.**

Verified: nflverse's player season stats have **no red-zone data at all**. Its
`passing_10` / `rushing_20` / `receiving_20` columns are *yardage-gain* buckets
(plays that went 10+ or 20+ yards), not field position. To get red-zone carries
and targets from nflverse you must process play-by-play — 272 games a season,
a real chunk of work.

Sportradar returns `red_zone_attempts` and `red_zone_targets` **directly in the
seasonal statistics feed**, 32 calls per season.

That feeds the workbook's TD model straight through:
```
Rec TD  = RZ Target Share % × Team Pass TD
Rush TD = RZ Rush Share %   × Team Rush TD
```
Without it, those two share columns have no data-driven default and start as
guesses. With it, they start from three years of measured goal-area usage. Same
argument applies to `catchable_passes` (separates a receiver's drops from a
QB's bad throws) and `pocket_time`.

**Recommended pull** (~100 calls, trivial at our tier):
```
1   league hierarchy          team GUIDs
3   season schedules          2023-2025
96  seasonal statistics       32 teams × 3 seasons  ← the red-zone data
```
Optionally add game statistics (272/season) for per-game splits, and PBP
(272/season) for a true field-position xTD model. Both are now affordable;
neither is needed for v1.

**Still cache everything.** Not because calls are scarce but because a parse
bug shouldn't cost a round trip, and reruns should be instant. Throttle
politely regardless.

---

## Part 3.5 — Odds: NOT needed for v1

**Decision: don't wire odds into the season-long build. No odds key required.**

Two reasons, and the second is the real one:

1. **the-odds-api doesn't carry NFL season win totals anyway.** Verified —
   `americanfootball_nfl` has `has_outrights: false`; the only NFL futures key
   is `americanfootball_nfl_super_bowl_winner`. Markets are `h2h`, `spreads`,
   `totals` (plus props/alternates on selected books). The one number that
   would most directly anchor preseason team totals isn't in the product.

2. **Win totals aren't needed for player projections.** Team strength flows
   into essentially one cell — **team TD total**. Volume (plays/game, pass
   rate) comes from pace history, not from how good a team is; yards come from
   attempts × efficiency. And since team totals are *editable inputs on the
   team tab*, a view that an offense will be better is just a higher Pass TD
   number typed in directly. A win total would only be picking that cell's
   starting value, which the 3-yr Sportradar baseline regressed to the league
   mean already does acceptably.

Skipping odds costs a little precision on the TD default and nothing else.

### When odds would be worth it (later)
Only if this grows a **weekly in-season** mode. Then implied team total =
`(O/U ÷ 2) − (spread ÷ 2)` is genuinely the best weekly anchor, and it's cheap:
one `/odds` call returns every game for the week at 1 credit per market per
region, so `spreads` + `totals` on the US region is **2 credits/week, ~36 for a
full season**. That fits a free 500/month plan easily — **the separate
20,000/month key is never needed for this project.**

The one genuinely expensive piece is `/historical/odds` backfill for
calibration (10 credits per market per region per snapshot). That would blow a
500/month plan, it's only useful for the weekly version, and it's skippable.
Don't do it unless weekly happens and turns out to need it.

---

## Part 4 — Proposed architecture

```
ff_projections/
  cached/nflverse/                      historical team + player stats, depth charts
  cached/sleeper/players_nfl_<date>.json current rosters + injury status
  cached/sr/{season}/{feed}/{id}.json   raw Sportradar responses (optional)
  fetch_nflverse.py                     free CSVs from GitHub releases
  fetch_sleeper.py                      public endpoint, no auth
  fetch_sportradar.py                   thin API client: auth, 1 QPS throttle, cache
  build_tables.py                       raw JSON → normalized CSVs
  build_shares.py                       normalized → market shares & efficiency rates
  project_teams.py                      2026 team-total defaults (plays, pass rate, TDs)
  build_workbook.py                     ← writes my_projections.xlsx with live formulas
  export_projections.py                 ← reads workbook back → proj_*.csv
  manual/
    overrides.csv                       roster corrections both sources miss
    coaching_changes.csv                hand-maintained: new OC/HC, pace/pass-rate delta
```

(`fetch_odds.py` only if a weekly in-season mode ever happens — see Part 3.5.)

**The pipeline runs in two halves with the workbook in the middle:**
```
Sportradar  →  normalized tables  →  defaults  →  [ my_projections.xlsx ]  →  proj_*.csv
     ( Python, run occasionally )            ( Excel, edited by me )      ( Python )
```
`build_workbook.py` is careful never to clobber usage I've already entered —
on rebuild it refreshes the data/reference tabs and the *default* columns, and
preserves my override columns by player key.

### Layer 1 — normalized tables
- `team_season.csv` — team, season, plays, pass_att, rush_att, yds, TDs, sacks,
  kneels, spikes, red-zone trips, plays/game, pass rate
- `player_season.csv` — the full charted stat line above, plus games/games_started
- `player_game.csv` — same per game (Plan B only); enables role-change detection
- `depth_chart.csv`, `injuries.csv`, `schedule.csv` (byes/opponents), `roster.csv`

Player stats come back keyed to the team you queried, so a mid-season trade
shows up under **both** teams — which is exactly right for market share.

### Layer 2 — derived shares (per player-season, per game where possible)
```
target_share      = targets / (team pass att − spikes − throw aways)
air_yards_share   = air_yards / team air_yards
WOPR              = 1.5 × target_share + 0.7 × air_yards_share
rush_share        = rush_att / (team rush att − kneels − QB scrambles)
rz_target_share, rz_rush_share, gl_rush_share
aDOT              = air_yards / targets
catch_rate        = rec / targets       (and rec / catchable_passes)
YPT, YPR, YPC, YAC/rec, yards_after_contact/att
td_rate_per_opp
```
Weight the last 3 seasons with recency decay (~0.5 / 0.3 / 0.2), computed on a
**per-game** basis so injury-shortened seasons aren't penalized twice.

### Layer 3 — defaults the code computes (every one of these is overridable)
- **Team totals:** weighted plays/game + pace regression to league mean; pass
  rate from 3-yr trend + coaching-change override; TDs from 3-yr weighted team
  TD rate regressed to the league mean (no odds input — see Part 3.5)
- **Player shares:** prior share, then redistribute **vacated share** (roster
  diff vs last season) weighted by depth-chart position and draft capital
- **Efficiency:** shrink toward positional mean by sample size
- **Games:** expected games from age + injury history

The point of these is that the workbook is *already a usable projection* before
I touch it — so I only spend judgment on the players I actually have an opinion
about, instead of filling in 500 rows.

---

## The workbook — `my_projections.xlsx`

40 tabs. `*` marks an editable input (pre-filled with a model default);
everything else is a live Excel formula.

**Structure: 32 team tabs (input) → 4 position tabs (rollup) → support tabs.**
Work happens one team at a time; position tabs assemble the league-wide view.
Formulas flow **team → position**, never back.

### The 32 team tabs — `ARI`, `ATL`, … `WAS`
One offense per screen. Team totals on top, players below allocating them,
share sums in the footer.

```
── TEAM TOTALS (editable*, pre-filled with model defaults) ──────────────
Games* | Plays/G* | Plays | Pass Rate* | Sacks* | Scrambles*
Pass Att | Rush Att | Comp%* | Y/A* | Pass Yds | Pass TD* | INT*
Y/C* | Rush Yds | Rush TD*

  Plays     = Plays/G × Games
  Dropbacks = Plays × Pass Rate
  Pass Att  = Dropbacks − Sacks − Scrambles
  Rush Att  = Plays − Dropbacks + Scrambles
  Pass Yds  = Pass Att × Y/A
  Rush Yds  = Rush Att × Y/C

── PLAYERS (fixed slots: 3 QB, 6 RB, 8 WR, 4 TE = 21 rows) ─────────────
Player | Pos | Depth | Age | Games* | Tgt%* | Rush%* | RZTgt%* | RZRush%*
       | Catch%* | Y/R* | Y/C*
       → Targets | Rec | RecYds | RecTD | RushAtt | RushYds | RushTD | FPts

  Targets  = Tgt%     × Pass Att        Rec TD   = RZTgt%  × Pass TD
  Rec      = Targets  × Catch%          Rush Att = Rush%   × Rush Att
  Rec Yds  = Rec      × Y/R             Rush TD  = RZRush% × Rush TD
                                        Rush Yds = Rush Att × Y/C

── SHARE TOTALS (must equal 100%, conditional-formatted red) ───────────
ΣTgt% | ΣRush% | ΣRZTgt% | ΣRZRush%
```

**This footer row is the whole trick.** Shares that sum to 100% mean player
targets sum to team pass attempts *by construction* — nothing to reconcile
afterward, no cross-checking QB yards against receiver yards the way the
Footballguys article has to. And it's visible on the same screen as the edit
that broke it. Add a "normalize this team to 100%" button for when I've been
editing and drifted.

**Why fixed slots (3/6/8/4).** Fixed row counts per position let the position
tabs be *live formula references* into known cells rather than a Python-written
snapshot — so a usage edit on `DAL` updates the WR tab instantly. Unused slots
sit blank and contribute zero. `build_workbook.py` fills slots by depth chart;
if a team genuinely needs a 9th WR, widen the slot count workbook-wide rather
than making one tab special.

**TDs come from team total × opportunity share**, never from a player's
prior-year TDs — the biggest error in hand-built projections, avoided for free
with no xTD modeling. If Plan B (PBP) happens later, the only thing that
changes is a better default in the RZ share columns.

### The 4 position tabs — `QB`, `RB`, `WR`, `TE`
Every player at that position across all 32 teams, live-referencing the team
tabs (`WR` row N = `DAL` WR slot 3, etc.). This is the ranking view, and it's
what exports to `proj_*.csv`.

```
Player | Team | Bye | Targets | Rec | RecYds | RecTD | RushAtt | RushYds
       | RushTD | Fum | FPts (Half) | FPts (PPR) | FPts (STD)
```
Column layout matches `consensus_<pos>.csv` exactly — see Export below.

Live references can't auto-sort cleanly (ties break Excel's array approaches),
so these carry a RANK helper column and get sorted on demand; `export_
projections.py` sorts properly on the way out. Values are always current even
when the row order is stale.

### Support tabs
- **`Rosters`** — complete current roster per team from Sportradar (name, pos,
  jersey, status, age, experience, college, draft round/pick, depth). The
  answer to "who is even on this team," and the guard against a departed player
  still holding share.
- **`History`** — 3 years of per-player actuals and shares, for reference while
  setting usage.
- **`Balance`** — 32-row dashboard of every team's four share sums, so I can
  see at a glance which teams still need work without clicking through tabs.
- **`Settings`** — games in season, scoring rules, league size.

### Export — a drop-in replacement for `consensus_*.csv`

`export_projections.py` reads the workbook's computed values back out and
writes `proj_qb.csv` / `proj_rb.csv` / `proj_wr.csv` / `proj_te.csv`, matching
the **column layout of `ff_draft_proj`'s `consensus_*.csv`** — including the
fantasy-points columns (QB: "Fantasy Points"; RB/WR: Half-PPR / PPR / STD, with
WR's half column named "Fantasy Points (Half)"; TE: Half-PPR / PPR / TE
Premium / STD, in that trailing order).

Matching that layout is **not** so consensus can read this — it never will.
It's so this can eventually *become* the file everything downstream reads.
Today `consensus_*.csv` feeds `ff_rankings/scoring_adjust.py`,
`ff_cheatsheet`'s updater scripts, and `ff_sfb16/workbook_common.py`, all of
which read by column name via `DictReader`/`pandas`. Identical column names
means the cutover is a path change in those readers, not a rewrite.

Two differences from how per-source CSVs work in `ff_draft_proj`:
- **This project computes its own fantasy points.** The workbook shows them
  live via Excel formulas (so I can see the effect of a usage change as I
  type), and `export_projections.py` recomputes them in Python via
  `ff_draft_proj/scoring.py` on the way out — imported, not forked, so there's
  one scoring rule set in the repo and the CSV can't silently drift from the
  sheet. The `Settings` tab's scoring values are generated *from* `scoring.py`
  so the two can't disagree.
- **Coverage is on us.** Consensus gets pool depth for free from the union of
  11 sources. This model has to project every fantasy-relevant player itself,
  including rookies and backups with no prior-season usage — which is what the
  `Rosters` tab and the depth-chart + draft-capital defaults are for. Expect
  thin-usage players to be the weakest part of v1 and the first thing worth
  testing.

---

---

## Sanity-checking against consensus

`compare_to_consensus.py` reads `ff_draft_proj/consensus_*.csv` **for
comparison only**. It never writes back into the model inputs — if it ever
does, the independence this project exists for is gone. Three levels:

1. **League totals** vs NFL reality. Catches a broken denominator instantly.
   Reads low until every team footer is balanced to 100% (unallocated share).
2. **Spearman rank correlation** per position. The single most useful number.
3. **Per-player divergence**, plus a separate **not-yet-filled-in** list.

First run caught a real bug and then a real measurement artifact:

**The workbook had no passing columns.** QBs were scoring off rushing alone —
Joe Burrow projected 17 points against a consensus 299. Fixed by adding a
`Pass %` share input (share of team pass attempts) driving Pass Yds / Pass TD /
Int from the team totals, plus passing terms in the scoring formula. Nothing
about the shares approach was wrong; a whole stat category was simply missing,
and a per-player eyeball would never have caught it across 955 rows.

**Blanks were being scored as disagreements.** Rookies and team-changers have
nothing to seed from, so they project 0 — which the correlation was reading as
"wildly disagrees with consensus." Separating them moved the numbers a lot:

| | before | after |
|---|---|---|
| QB | 0.748 | **0.834** |
| RB | 0.707 | **0.850** |
| WR | 0.683 | **0.900** |
| TE | 0.730 | **0.933** |

0.85+ means ranking players the same way with different numbers — exactly the
goal. The 229 excluded players become the to-do list, ranked by what consensus
thinks they're worth so the highest-value gaps get filled first.

**Rule of thumb:** a low correlation is a bug hunt, not a difference of
opinion. Individual outliers are where the model might be right and the market
wrong — that's the product. Whole positions drifting is always a defect.

---

## Yards are a SHARE, not a bottom-up rate

Original design built yards bottom-up: `targets x catch% x yards-per-catch`.
Team yards were a "control total" that nothing enforced, so the two never
agreed — mean miss of ~550 receiving yards and ~570 rushing yards per team,
with Dallas overshooting its rushing total by **1,390**. That's the exact flaw
the Footballguys article warns about, and the claim that shares made
reconciliation unnecessary was only true for *targets*, not for yards, because
yards routed through an independent absolute rate.

Yards now split the team total the same way targets do:

    Rec Yds = (Tgt% x Rec Eff x x Games)
              / SUM(all rows: Tgt% x Rec Eff x x Games)
              x Team Pass Yds

The column sums to the team total by construction, whatever anyone types.

**`Rec Eff x` / `Rush Eff x` are yards per opportunity RELATIVE to the team
average** — 1.00 = gains yards in proportion to his targets, 1.30 = deep
threat, 0.75 = checkdown back. Seeded from each player's own 3-year record.

**Yds/Rec and Yds/Car became outputs**, which also makes them a free
diagnostic: if a WR1 shows 7 yards a catch, that team's shares sum to well
over 100% and everyone is being squeezed. ARI seeds at 140%, which drags
McBride to 7.1 Y/R; balanced to 100% he lands at 10.3 against a real 9.8.

The general rule: **never let the user set two things that determine the same
quantity.** Share and absolute rate over-determine yards. Share and a relative
multiplier don't.

## Seed everything or seed nothing

Half-seeded was worse than either extreme — you can't tell "haven't done this
yet" from "the model thinks zero." Every row is now seeded:

- **returning players** — their own recency- and games-weighted record
- **rookies and new arrivals** — league median share for their position and
  depth rank, fitted from 54 position/depth buckets across 2023-25
  (WR1 25.1%, WR2 18.4%, WR3 12.2%; RB1 56.8% of carries, RB2 27.9%;
  TE1 16.7% of targets)

A `seed_basis` column records which, and the Status cell shows `role avg
(from SF)` or `role avg (rookie)` so the basis is visible while working.

Consequence: teams now seed well over 100% (ARI 140%) because role-average
newcomers stack on top of returning players' per-game rates. That's honest —
the sheet is showing you a genuine conflict to resolve, not hiding it.

## Shares must be PER-GAME rates, not season totals

The single worst bug so far, caught by a user question rather than any check.

Season-total share divides a player's targets by the team's whole season — so
anyone who missed games looks like a part-time contributor instead of the
starter he is:

| 2025 | season-total share | per-game rate | games |
|---|---|---|---|
| Garrett Wilson | 12.5% | **30.4%** | 7 |
| Rashee Rice | 14.2% | **30.2%** | 8 |
| Mike Evans | 11.5% | **24.3%** | 8 |
| Terry McLaurin | 13.9% | **23.6%** | 10 |

45 players with 40+ targets missed 3+ games. Seeding from season totals would
have understated every one of them by up to 2.4x — and these are exactly the
buy-low guys a projection is supposed to find.

**The decomposition that fixes it:** share answers "what does he command when
he plays," Games answers "how much will he play." Two inputs, each used once.
Baking availability into the share applies it twice the moment you also set
Games.

    share = (player stat / his games) / (team stat / team games)

Consequences that ripple through the workbook:
- every output formula carries `* (Games / TeamGames)`
- the footer sums **share x games**, not raw share — `SUMPRODUCT(shares, games)
  / team games`. A part-season player only consumes part of the pie.
- teams now open both over and under 100%. Under = vacated volume. Over =
  several players who each commanded a big rate while healthy (three backs at
  40% each sum to 120%). Both are real, and the second one is a question only
  a human can answer. League average went 79% -> 95% of targets.

## QB pass share is the one cell where role beats history
A backup who started six games carries a ~40% pass share that will never
repeat; a real QB1 takes 90-95% of attempts almost deterministically. 11 of 32
depth-chart QB1s seeded under 80% — Malik Willis at 8.2%, Watson at 30.8%,
Brissett at 59.8% — which left those teams' passing 40% short before any
manual work.

QB1 now seeds at `max(history, 0.92)`, QB2 at 0.07, QB3 at 0.01. History still
shows in the reference columns. **Skill positions stay purely historical** —
depth chart is a much weaker signal for them, and a WR2 label says little about
target share.

---

## Efficiency travels with the player; usage does not

The cleanest statement of the whole seeding model:

| | belongs to | on a team change |
|---|---|---|
| YPC / YPR / catch rate | the **player** | **carries over** |
| target share / carry share | the **offense** | **must be re-predicted** |

Efficiency is stored as a multiplier of the team's own rate (1.00 = earns yards
in proportion to opportunity), so it's already team-relative and transfers
cleanly. 123 of 125 team-changers keep theirs.

Usage for anyone without valid history — rookies and new arrivals — comes from
**depth-chart role**, blended 50/50 between the league median for that slot and
the team's own 3-year distribution shape. Some offences feed a bell cow, others
run a committee, and that's durable. Measured on 2025:

| | league median | team's own shape | 50/50 |
|---|---|---|---|
| WR target share | 0.801 | 0.788 | **0.819** |
| RB rush share | 0.882 | 0.863 | **0.885** |

**Efficiency needed the same small-sample guard as the red-zone ratios.** Raw,
a receiver with two end-arounds computed to a 2.74x rushing multiplier and one
QB came out at **-0.32** — which would have produced negative rushing yards.
Now shrunk toward 1.00 by opportunity count (k=20) and clamped to [0.60, 1.50].
Zero impossible values remain.

### Known limit: a displaced starter still out-seeds a rookie bell cow
ARI opens with Jeremiyah Love (RB1, rookie) at 27.8% and James Conner (RB3) at
20.0%. Conner's own history is strong and the 60/40 history/role blend keeps
most of it; Love has no history at all, so he gets the role prior and then
normalization scales the whole room down.

The flat blend is empirically optimal *on average* (tested: 30/70 through 70/30
are all within 0.01 of each other), so tuning it further is fitting noise. This
particular shape — big history, deep depth chart — is the case it can't see,
and it's exactly what the manual pass exists for.

---

## What the data actually said (findings from the first build)

### Where the team totals come from
The full chain, for the record:

```
NFL.com official play-by-play JSON  (the feed behind official box scores)
   └─> nflfastR          parses to tidy PBP, 1999-present, adds EPA/CPOE
        └─> nflverse-pbp aggregates PBP up into stats_team_* / stats_player_*
             └─> nflverse-data  publishes CSV/parquet to GitHub releases,
                                updated nightly during the season
                  └─> fetch_nflverse.py   stats_team_reg_2016..2025.csv
                       └─> build_team_totals.py  -> team_totals_2026.csv
```

So these are **official NFL play-by-play**, aggregated — not a third-party
estimate. (1999-2000 come from a separate compilation; 2001+ from the official
JSON feed. Irrelevant to us, we start at 2016.)

Because they're aggregated *from plays* rather than lifted from published
box-score season totals, small definitional differences are expected — our
`plays` runs ~30 high vs published counts because it includes kneels and spikes.

### Sportradar and nflverse agree exactly — once you use the right yards field
Having both sources for 2023-2025 makes a real cross-check possible. 2025, all
32 teams, Sportradar vs nflverse:

| metric | exact match |
|---|---|
| pass attempts | **32/32** |
| rush attempts | **32/32** |
| pass TD | **32/32** |
| rush TD | **32/32** |
| sacks | **32/32** |
| rush yards | 31/32 (max diff 5) |
| **pass yards** | **0/32 — max diff 464** |

That last row is a trap, not a bug. **Sportradar's `passing.yards` is NET of
sack yardage.** The field that matches everyone else's "passing yards" is
`passing.gross_yards` — which then reconciles **32/32 exactly**.

```
LV 2025:  sr.yards 2851  |  sr.gross_yards 3315  |  nflverse 3315
          sack_yards 464  ->  2851 = 3315 - 464
```

**Always read `gross_yards` from Sportradar.** Using `yards` would silently
understate every passing offense by 150-450 yards and quietly deflate every
receiver projection built on it. Same caution applies anywhere Sportradar
offers a net/gross pair.

With that resolved, the two independent sources agree on every team total we
project from — the foundation is sound.

### Regression to the mean collapses the league — it has to be a dial
Shrinkage weights were **fitted**, not guessed: for each metric, correlate the
3-yr weighted prior against what teams actually did the following season,
pooled over 224 team-seasons. Results:

| metric | fitted w | | metric | fitted w |
|---|---|---|---|---|
| pass_rate | 0.41 | | comp_pct | 0.37 |
| ypa | 0.41 | | ypc | 0.35 |
| sack_rate | 0.39 | | rush_td_rate | 0.24 |
| pass_td_rate | 0.36 | | int_rate | 0.23 |
| | | | **plays_per_game** | **0.22** |

Team pace is far less sticky than intuition suggests — plays/game has r ≈ 0.25
year over year (verified independently against a raw lag-1 correlation).

Applying those weights honestly produces a **useless** projection:

| | full shrinkage | real seasons |
|---|---|---|
| plays | 1040-1066 (27) | 948-1187 (239) |
| pass TD | 22-29 (7) | 11-46 (35) |
| rush TD | 13-19 (6) | 5-32 (27) |

Every offense lands on league average, so nothing differentiates players
downstream. That is the *statistically correct* minimum-error point estimate
and the wrong tool for this job. Hence `--regression`, defaulting to 0.5:

| `--regression` | plays spread | pass TD spread |
|---|---|---|
| 0.0 (pure trend) | 120 | 19 |
| 0.5 (default) | 74 | 13 |
| 1.0 (full shrink) | 27 | 7 |

Even at 0.0 the spread is narrower than reality — correct, since a 3-yr average
is smoother than any single season and part of the real spread is pure noise.
`build_team_totals.py` prints this comparison on every run so over-shrinkage
can't slip through unnoticed. Every rate also gets a `_trend` column (raw 3-yr,
unshrunk) to show beside the editable cell.

**The real lesson:** the information about which 2026 offenses will be good —
new QB, new coordinator, rebuilt line — is not in the historical data at all.
No amount of tuning extracts it. That's exactly the judgment the team tabs
exist to capture, which is why these are defaults and not answers.

### nflverse is the wrong roster source. Sleeper is the right one.
The first build used nflverse for rosters purely because it was already being
pulled for historical stats — never checked whether it was *good* at rosters.
It isn't. Tested against four real August 2026 situations:

| | nflverse roster | nflverse depth | **Sleeper** |
|---|---|---|---|
| Deebo Samuel on SF | absent | SF WR2 | **SF, depth 2** |
| Stefon Diggs → WAS | absent | absent | **WAS, depth 2** |
| Ricky Pearsall out | says `ACT` | buried to WR15 | **IR / Knee-PCL** |
| Brandon Aiyuk out | — | WR8 | **DNR / Knee ACL+MCL / Surgery** |

`GET https://api.sleeper.app/v1/players/nfl` — public, no auth, no key. Sleeper
is a fantasy platform, so being days late on a signing or an IR designation
would be a product failure for them; the blob timestamps player news to the
hour. nflverse has **no 2026 injury file at all** (the dataset stops at 2025),
and its roster file was weeks stale. Pearsall only landed anywhere sane because
ESPN happened to bury him — luck, not signal.

**But it's both, not either.** Each source is used for what it's actually best
at, because Sleeper has real gaps:

| | Sleeper | nflverse |
|---|---|---|
| freshness | **hours** | weeks |
| injury status | **populated** | none for 2026 |
| depth order | 742/991 | **complete** |
| `gsis_id` (stats join key) | 163/991 | **complete** |

So: Sleeper for team assignment and availability, nflverse depth charts to fill
Sleeper's depth gaps, nflverse rosters as the `sportradar_id → gsis_id` bridge
into the historical stats (plus draft capital), overrides last.

Two Sleeper quirks: it retains historical players with a stale last-team
attached (long-retired guys, and a literal `"Duplicate Player"` record) —
filter on `active`, which drops exactly 8 junk skill records. And `status:
Inactive` means out-of-the-league, not injured; that's separate from
`injury_status`.

**Sportradar would also serve here** (Weekly Depth Charts + Team Roster +
Daily Transactions, 4hr TTL) and call budget is no obstacle — but Sleeper still
wins on this specific job, because it carries injury *detail* (body part,
practice participation, notes) that a depth chart doesn't. Sportradar's value
is elsewhere: red-zone opportunity. See Part 3.

### "Out" has causes the data will never encode
Aiyuk is the clean example. Sleeper tags him `DNR / Knee - ACL + MCL / Surgery`
— which is **stale 2024 injury data**. The actual reason he's expected to play
zero snaps in 2026 is a contract standoff: he's on reserve/left squad and
hasn't filed for reinstatement.

Same output (`OUT`), completely different reason, and the difference matters —
a torn ACL doesn't resolve mid-August, a contract might. That's why
`overrides.csv` carries a free-text `note`: the status tells the model what to
do, the note tells a human whether to revisit it. Record the real reason, not
the one the feed happens to show.

### PUP is not "out" — never auto-zero it
First pass treated `IR / PUP / NFI / DNR / Sus / Out` alike and zeroed them all.
That silently deleted **George Kittle** (SF TE1, PUP/Achilles). In August, PUP
and NFI are frequently precautionary — a player can come off in camp and start
Week 1 — so zeroing them destroys a starter on a guess.

Split into two sets:
- **auto-zero** (`IR`, `Out`, `Sus`, `Ret`): genuinely season-ending
- **surface for review** (`PUP`, `NFI`, `DNR`, `COV`): kept at full share,
  printed in a `NEEDS YOUR CALL` block sorted by depth with `<-- STARTER` on
  anyone at depth 1

That block is the tool working as intended: the machine can't know whether
Kittle's Achilles is a camp precaution or a lost season, so it refuses to
guess and puts the decision where the knowledge is. Answer it with one line in
`manual/overrides.csv`.

`Questionable`/`Doubtful` are week-to-week noise, reported separately at depth
1-3 and never acted on.

### The manual override layer is mandatory, not a nice-to-have
Even with Sleeper, the Diggs signing needed a hand-entered depth, and Aiyuk
needed a judgment call the data won't make.

```csv
player,team,pos,depth,status,note
Brandon Aiyuk,SF,WR,,OUT,unlikely to play - DNR is not auto-zeroed
Stefon Diggs,WAS,WR,2,ACT,signed Aug 2026 - depth is an assumption
```
- a player in no source is **added**
- one already present has non-blank fields **overwritten** (`team` = move)
- `OUT` keeps the row, drops them from the depth order, assigns no share
- depth is re-ranked per team+position after, and an explicit depth **wins the
  tie** against the incumbent — forcing a signing in at 2 pushes the existing
  WR2 to 3 rather than silently landing at 3 itself

Joining on ids alone loses players (both sides carry blanks), so `names.py`
provides a normalized name+team fallback throughout.

### Slot sizing needs an "everyone else" row
Measured depth on real 90-man rosters, vs. the slot counts originally proposed:

| pos | proposed | deepest | median/team |
|---|---|---|---|
| QB | 3 | 4 | 4 |
| RB | 6 | 7 | 6 |
| WR | 8 | 15 | 12 |
| TE | 4 | 9 | 6 |

Carrying 15 WR slots per team is absurd — WR9+ are camp bodies who'll be cut.
But shares must still sum to 100%. So each position block needs a trailing
**"Other"** row that absorbs the residual share, letting the visible slots stay
small while the arithmetic stays exact.

### Minor
`plays` here = pass attempts + carries + sacks. That runs ~30 higher than
published play counts (which exclude kneels/spikes). Harmless for shares since
it's consistent on both sides of the ratio, but don't compare the raw number to
someone else's without accounting for it.

---

## Ground rules
- Sportradar key in `ff_projections/.env` as `SPORTRADAR_API_KEY`, never
  committed. `.env.example` documents it. **No odds key needed** — and if
  weekly is ever added, use the free 500/month plan, never the 20k key that
  belongs to another project.
- Header auth (`x-api-key`), 1.1s sleep between calls, cache-first always.
- **Never overwrite my usage edits.** `build_workbook.py` must be safe to
  re-run: refresh reference tabs and default columns, preserve override columns
  keyed by player. Back up the workbook before writing, same as
  `ff_auction_values`/`ff_cheatsheet` do.
- Every raw response hits disk before parsing — a parse bug should never cost
  an API call.
- Same name/team normalization as `ff_draft_proj` (`clean_team`,
  `TEAM_ALIASES`, suffix handling) — not to join against it, but so the
  eventual swap for `consensus_*.csv` is byte-comparable downstream.
- **Never read `consensus_*.csv` or any `ff_draft_proj` per-source CSV as
  model input.** The only import from that project is `scoring.py`.

## Open decisions
1. ~~Trial or production key?~~ **Settled: not on the trial.** Call budget is
   not a constraint. Remaining question is only *what* to pull — see Part 3;
   the red-zone seasonal stats are the piece that earns its keep.
2. **Season-long only, or weekly in-season too?** Weekly needs Game Statistics
   + odds every week and is a much bigger ongoing pull.
3. **Pull nflverse for snaps/routes?** Recommended — free, and closes the one
   real gap in Sportradar's coverage.
4. **Cutover plan.** Once this is trusted, decide whether downstream projects
   (`ff_rankings`, `ff_cheatsheet`, `ff_sfb16`, `ff_auction_values`) repoint
   from `consensus_*.csv` to `proj_*.csv` all at once or one at a time, and
   whether `ff_draft_proj` keeps running as a benchmark or gets retired.
5. **Slot counts per team tab.** Measured against real rosters (see findings) —
   3 QB / 6 RB / 8 WR / 4 TE is right for the *visible* slots, but each block
   needs a trailing "Other" row to absorb residual share so the 100% check
   still works. Confirm before building: widening later means rebuilding every
   position tab's references.
6. **Do K and DST get tabs?** Currently out of scope (`ff_draft_proj` doesn't
   project them either). If they're wanted, K is easy from team FG/XP totals;
   DST doesn't fit the share model at all and would need its own approach.

**Settled:** odds are out for v1 (Part 3.5) — no odds key needed, and the
20k/month key stays untouched.
