# SFB16 Bonus-Event Projections

## Goal
Sibling project to `ff_adp` (ADP), `ff_draft_proj` (consensus season-total
stat projections), and `ff_cheatsheet` (Excel workbook updater) — built
specifically for **Scott Fish Bowl 16 (SFB16)**, a bonus-scoring league.
SFB16 awards points for big-play/big-game events on top of standard scoring:

- 300+ / 400+ yard passing games
- 100+ / 200+ yard rushing+receiving (combined "scrimmage") games
- 40+ yard passing / rushing plays, 20+ yard receiving plays (this league's
  three Sleeper receiving brackets — 20-29/30-39/40+ — are all worth the
  same bonus, so they're modeled as one combined 20+ threshold, not three
  separate stacking bonuses)

The other two projects only carry **season-total** projections (e.g. "Pass
Yds: 3726.87" for the season) — that tells you nothing about how many
*individual games or plays* will clear one of these fixed thresholds. This
project converts those season totals into **projected season-long
occurrence counts** for each bonus category, live in the workbook, as
Excel formulas — not point totals. SFB16's point value per bonus category
is set by the user directly in `Setup`, same as every other stat category.

## Why historical data is needed
A player's season total alone can't tell you how often they clear a per-game
threshold (that depends on game-to-game *variance*, not just the average) or
how many individual big plays they'll have (that depends on *big-play rate*,
which correlates with efficiency, not raw volume). Both are calibrated from
3 seasons (2022-2024) of public NFL historical data
([nflverse](https://github.com/nflverse/nflverse-data) — no auth required).
This calibration is a rare/one-time step — see "Calibration" below — not
part of the regular refresh.

## Full refresh: one command
**`refresh_all.py`** — the normal way to update the SFB16 cheat sheet. Close
the workbook in Excel first, then `python refresh_all.py`. Runs in order:

1. Refresh all projection sources + rebuild consensus
   (`ff_draft_proj/run_all.py --no-sheets`).
2. Refresh every existing player's stat line on the Projections tabs from
   that fresh consensus data (`build_sfb16_workbook.py`). The SFB16 bonus
   columns are live formulas (see "Bonus columns are formulas" below) that
   recalculate automatically from those stat columns — no separate push
   step needed for them.
3. Add any consensus player who isn't a row on the Projections/Cheat Sheet
   tabs yet (`add_missing_players.py`) — e.g. a newly-added source surfaces
   a player nobody had projected before.
4. Discover new/updated SFB16 Sleeper drafts (`discover_sfb16_drafts.py`).
5. Recompile ADP from every known draft (`compile_sleeper_adp.py`).
6. Push that ADP into the workbook (`update_adp_from_sleeper.py`).

## Bonus columns are formulas, not Python-pushed values
The `Exp ...` columns (e.g. `Exp 300+ Pass Yd Games`) are live Excel
formulas on each Projections tab — set up once by `setup_bonus_formulas.py`
— that recalculate automatically whenever the raw stat columns
(Att/Yds/TD/Tgt/Rec/etc.) change. Same pattern as the existing
`ru1st`/`re1st` first-down columns (`=0.079*M2`-style), just driven by the
calibrated constants instead of a single multiplier:

- **Game-threshold columns** (`Exp 300+/400+ Pass Yd Games`,
  `Exp 100+/200+ Scrim Yd Games`): lognormal model, replicated via Excel's
  built-in `NORM.S.DIST`:
  `=17*(1-NORM.S.DIST((LN(threshold)-(LN(SeasonYds/17)-sigma^2/2))/sigma,TRUE))`
- **Big-play columns** (`Exp 40+ Rush Plays`, `Exp 20+ Yd Rec Plays`,
  `Exp 40+ Pass Plays`): linear rate model:
  `=Opportunities*MAX(0,slope*(Yards/Opportunities)+intercept)`

The calibrated constants (`sigma` per position/stat, `slope`/`intercept`
per play type) live in `Setup!B44:B54` (labels in `A44:A54`) — written once
by `setup_bonus_formulas.py`, read by every row's formula via `Setup!$B$xx`
references. Re-run `setup_bonus_formulas.py` only if the calibration itself
changes (re-running `calibrate_rates.py` with a different historical
window, different weighting, etc.) — it overwrites the Setup constants and
every formula, so it's idempotent/safe to re-run, but isn't part of the
regular refresh since the constants rarely change.

**Consequence:** because the bonus columns are formulas, `build_sfb16_workbook.py`
only needs to keep the raw stat columns current — it does **not** need
`project_sfb16_stats.py`'s output (`sfb16_*.csv`) anymore. Those CSVs and
the script that makes them are still useful for offline validation/sanity
checks of the calibration, but are no longer part of the live workbook
pipeline.

## Adding new players
The Projections/Cheat Sheet tabs' player list is **not auto-synced** from
consensus — it's a copy that only grows when something adds rows to it.
`add_missing_players.py` finds every consensus player (alias-aware, so it
won't re-add someone already on the sheet under a nickname/suffix variant)
who isn't a row yet, and adds them: copies an existing fully-formula-intact
row (row 2) down via Excel's own `Copy(Destination=)` so every formula
(Score, `ru1st`/`re1st`, rank, bonus columns, Player&Team) auto-adjusts
correctly for the new row, then overwrites just the raw data columns
(Name/Team/Bye/Position + stats) with that player's real values. Does the
same for the Cheat Sheet tab's separate list. No point-total cutoff is
applied — every consensus player gets added, including very marginal ones;
trim manually if desired. Safe/idempotent to re-run — finds nothing to add
once everyone's already there.

`workbook_common.py` holds the shared config both this script and
`build_sfb16_workbook.py` use: the per-tab stat-column mapping, the
nickname `NAME_ALIASES` dict (suffix differences like Jr./Sr./III are
handled generically by `normalize()`; true nicknames — e.g. "Cameron Ward"
on the sheet vs. consensus's "Cam Ward" — need a manual entry here), and
the win32com workbook path.

## Calibration (rare — only re-run when the model itself needs revisiting)
1. **`fetch_historical_data.py`** — fetch nflverse weekly player stats and
   play-by-play data (2022-2024), cached locally as `historical_weekly.csv`
   and `historical_pbp_plays.csv`. Re-run to extend/refresh the window.
2. **`calibrate_rates.py`** — reads the cached historical CSVs, fits two
   models, and writes `calibration_params.json`:
   - **Per-game yardage variance (lognormal sigma)**, one per position/stat
     (`qb_pass`, `qb_scrim`, `rb_scrim`, `wr_scrim`, `te_scrim`) — pooled
     from log-yardage residuals around each player-season's own mean.
   - **Big-play rate vs. efficiency**, one linear fit per play type (`pass`,
     `rush` — both 40+ yard buckets; `rec` — a 20+ yard bucket, since this
     league's receiving threshold is lower than passing/rushing).
   - Regular-season weeks only (`week <= 18`).
   - Both models weight the 3 seasons by recency (`SEASON_WEIGHTS`, a
     Marcel-style 5:4:3 ratio favoring 2024 over 2023 over 2022). The rate
     fits also weight by sample size (sqrt of that player-season's
     opportunities) — this is what handles injury-shortened/small-sample
     seasons without needing to specially detect them: fewer qualifying
     attempts/carries/targets means less weight, automatically.
3. **`setup_bonus_formulas.py`** — pushes the new `calibration_params.json`
   values into `Setup!B44:B54` and rewrites every bonus-column formula
   across all 4 Projections tabs to reference them. Run this after any
   `calibrate_rates.py` change to actually apply it to the live workbook.

`project_sfb16_stats.py` (reads consensus CSVs + `calibration_params.json`,
writes `sfb16_qb/rb/wr/te.csv`) is kept around for offline validation of
the calibration math against the live formulas, not for the regular
pipeline.

`GAMES_PER_SEASON = 17` (NFL regular season length) is the only hardcoded
season-length assumption, shared between `project_sfb16_stats.py`'s Python
math and the Excel formulas (`17*(1-NORM.S.DIST(...))`).

## ADP: single-source, from real Sleeper drafts
The regular cheat sheet (`ff_adp`/`ff_cheatsheet`) blends ADP from ~10 sites.
SFB16 uses **one ADP source only**: the average pick number across actual
completed/in-progress Sleeper drafts — not a published ADP feed.

1. **`sleeper_draft_sources.csv`** — append-only list of sources, columns
   `type` (`draft` or `league`), `id` (the Sleeper draft_id or league_id),
   `note` (free text, ignored). For `league` rows, every draft under that
   league with `status == "complete"` is included automatically.
2. **`discover_sfb16_drafts.py`** — auto-discovers sources instead of
   hand-collecting IDs: every SFB16 league is commissioned under Sleeper
   username `ScottFishBowl` with "SFB16" in the league name. Resolves that
   username, pulls all their NFL leagues for a season (default 2026),
   filters to name match, and appends any draft that is `complete` **or**
   `drafting` (in progress) to `sleeper_draft_sources.csv` — Sleeper's picks
   endpoint returns whatever's happened so far even mid-draft, so live
   drafts still contribute real signal. Skips draft_ids already present, so
   it's safe to re-run any time. A draft already in the source list doesn't
   need to be re-added as it progresses — `compile_sleeper_adp.py` always
   re-fetches current picks on every run.
3. **`compile_sleeper_adp.py`** — resolves every source row to a draft_id,
   pulls each draft's picks (`api.sleeper.app/v1/draft/<id>/picks`), and
   computes each player's ADP as the average overall `pick_no` across the
   drafts they were picked in. Player names/positions/teams come from
   Sleeper's player directory (`api.sleeper.app/v1/players/nfl`), cached
   locally as `sleeper_players_cache.json` (delete to force a refresh).
   Blank/unsigned team is written as `"FA"` (never leave it `NaN` — see
   "win32com NaN gotcha" below). Writes `sleeper_compiled_adp.csv`.
4. **`update_adp_from_sleeper.py`** — opens the SFB16 workbook via win32com
   and: (a) rewrites the `ADP` tab down to 4 columns (Player/Position/
   Team/ADP) from `sleeper_compiled_adp.csv` — also re-scans the live Cheat
   Sheet names every run and adds suffix/nickname alias rows so the VLOOKUP
   matches regardless of spelling (e.g. "Kyle Pitts Sr." vs. consensus's
   "Kyle Pitts"); (b) simplifies the `Cheat Sheet` tab's `ADP` column
   formula to a single `VLOOKUP` against the new ADP tab, keeping the
   "undrafted -> worst ADP + 1" fallback.

## Conventions / ground rules
- `BASE = Path(__file__).resolve().parent` for this project's own files;
  `ff_draft_proj`'s consensus CSVs are referenced via
  `BASE.parent / "ff_draft_proj"` (siblings at the same repo-root depth, same
  pattern as `ff_cheatsheet`). `workbook_common.py` centralizes these paths.
- No `scipy` dependency — the lognormal CDF is computed via stdlib
  `math.erf` in Python and `NORM.S.DIST` in Excel; the linear fits use
  `numpy.polyfit`.
- `ff_draft_proj/.env` holds the credentialed sources' login info (FTN,
  Draft Sharks, Fantasy Data, 4for4, Fantasy Life) — gitignored, never
  commit it. Without it those 5 fetchers fail silently (non-fatal in
  `run_all.py`) and the consensus quietly degrades to only the
  no-login sources (ESPN/CBS/Fantasy Sharks/FFToday) — always check
  `run_all.py`'s output for fetcher warnings, not just that it exited 0.
- **win32com NaN gotcha**: writing a Python `float('nan')` into an Excel
  cell via `win32com` doesn't error — it silently stores the literal value
  `65535`, which then poisons any formula that reads that cell. Bit us
  twice (a missing `Team` and a missing `Bye` for unsigned free agents).
  Any value written via `ws.Cells(...).Value = ...` that *might* be
  `NaN`/missing must be defused first (`0 if pd.isna(x) else x`, or map to
  a sentinel like `"FA"`) — never pass a raw possibly-missing pandas value
  straight through.
- This project intentionally stops at occurrence counts/formulas. SFB16
  bonus point values per category are set by the user in `Setup`, same as
  every other stat category — not computed here.
- **Never trust `ws.UsedRange.Rows.Count` for "last data row".** Excel
  doesn't shrink `UsedRange` back down after row deletions — it can keep
  reporting rows well past the real data indefinitely. Bit us once: ~36
  leftover blank-but-formula rows survived several refreshes undetected,
  then a batch formula-write touched them for the first time and a
  whole-column `RANK.EQ` cascaded into `#N/A` for every row on Cheat Sheet.
  Always use `workbook_common.last_data_row(ws)` instead (walks up from the
  sheet's bottom in column A, same as Ctrl+Up) — every script here does.
- **Performance: batch Excel I/O, don't loop `ws.Cells(r, c)`.** Each
  `.Cells()` access is its own COM round-trip — looping it across hundreds
  of rows is what made refreshes slow. `workbook_common.read_range`/
  `write_range` read or write an entire rectangular block in one call
  (passing a 2D tuple to `Range.Value`/`Range.Formula`); every script here
  uses them for any column wider/taller than a handful of cells. Cut the
  three main scripts from several minutes combined down to ~3-4 seconds
  each. Only safe for contiguous, all-data column blocks — never for a
  range that mixes in formula cells (those still get set individually via
  `Range.Formula` with one formula string per row, also batchable the same
  way — see `setup_bonus_formulas.py`/`simplify_cheat_sheet_adp_formula`).
