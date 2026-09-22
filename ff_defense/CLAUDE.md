# Defensive Stream-O-Matic — data sources

Feeds Joe's "Stream-O-Matic" Google Sheet (id
`1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ`), specifically the "Live"
tab: `SCORE | Team | Rost% | Start% | Opp | Imp | Def Rating | Opp Off EPA |
Pressure | ECR | Proj` (A-K). Sheet writes use the same
service-account credentials as the rest of this repo
(`triple-baton-456523-e4-b9ec3cbd6e3d.json` at the repo root) — Joe shared
the "Live" sheet with that service account's email directly.

`team_names.py` is shared by every fetcher/pusher here: `normalize()` maps
a full nickname ("Buccaneers"), a bare abbreviation, or an "@"-prefixed
abbreviation ("@KC") to this sheet's standard code, aliasing each source's
quirks (FTN's "JAX", eatdrinkandsleepfootball's stale stl/sd/oak codes).
`nickname_to_abbr()` derives the code from a full team name's last word.

## Retired sources — do not wire these back in without checking
Subvertadown (column G + the team list) and FTN DAVE (columns H/I) were
both **paid/borrowed** feeds that stopped working: Subvertadown revoked
Joe's access, and he wanted off DVOA regardless. `fetch_subvertadown_defense.py`,
`push_subvertadown_to_sheet.py`, `fetch_ftn_dave.py` and
`push_ftn_dave_to_sheet.py` are still in the tree for reference but are
**not in the pipeline** and nothing calls them.

Everything they supplied now comes from nflverse's free public release
files (no login, no scraping, nothing revocable):
- team list + matchups → `fetch_schedule.py` (schedules release)
- column G (own defense quality) → `fetch_def_rating.py` (play-by-play)
- column H (opponent offense) → `fetch_nflverse_epa.py` (play-by-play)

**Subvertadown's column was deleted outright** (it sat between Imp and
Def Rating), so the tab went from A–L to **A–K** and everything from Def
Rating rightward shifted one column left. Every push script's target
letter moved with it. If you're reading older code or notes that mention
`H2` for Def Rating or `L2` for Proj, that's the pre-deletion layout.

## Weekly refresh order
```
python fetch_schedule.py --week N && python push_schedule_to_sheet.py
python fetch_def_rating.py && python push_def_rating_to_sheet.py
python fetch_nflverse_epa.py && python push_nflverse_epa_to_sheet.py
python fetch_implied_totals.py && python push_implied_totals_to_sheet.py
python fetch_yahoo_def.py --week N && python push_yahoo_def_to_sheet.py
python fetch_subvertadown_adjustment.py --week N && python push_proj_to_sheet.py
python fetch_fantasypros_dst_ecr.py --week N && python push_fantasypros_ecr_to_sheet.py
python fetch_pressure_rate.py && python push_pressure_rate_to_sheet.py
python finalize_live_sheet.py
```
Or just `python run_all.py` / `python run_frequent.py` (week auto-detected).
`fetch_schedule.py` must run FIRST — it establishes the team list in column
B that every other push matches its rows against. `finalize_live_sheet.py`
must run LAST — see below.

## Two runs a week, and why the split is what it is
Both are GitHub Actions workflows on `workflow_dispatch`, triggered by
cron-job.org (no native `schedule:` — see the workflow comments).

| | `run_all.py` / `defense_full_refresh.yml` | `run_frequent.py` / `defense_frequent_refresh.yml` |
|---|---|---|
| When | Tuesday afternoon, once | Wednesday–Sunday, repeatedly |
| Columns | all of them, + Reddit post | F (odds), C/D (Yahoo), K (Proj), J (ECR) |

**The Tuesday run must land first each week.** It writes the team list in
column B, and every mid-week push matches its rows against that list — so a
mid-week run that goes first just refreshes last week's teams.

Four things are **Tuesday-only**, and three of them are not just about
saving time:
- **Team list + matchups (B/E).** Opponents don't change once a slate is
  set; a flexed game moves the kickoff, not who's playing whom.
- **Def Rating (G) and Opp Off EPA (H).** These are season-to-date per-play
  numbers. Refreshing on a Friday folds in Thursday night's game — and
  *only* Thursday night's game, so 2 of 32 teams get rated on a sample the
  other 30 don't have. Freezing at Tuesday keeps every team's rating over
  the same set of completed weeks, which is what a 1–32 ranking across
  teams actually requires. This is a correctness constraint, not a
  performance one; don't "improve" it by refreshing more often.
- **Pressure rate (I).** Weekly-only at the source.
- **The Reddit post.** Joe posts the top 10 once.

`generate_reddit_post.py` writes the post three places: a local
`reddit_post.md`, stdout (so it's in the Actions log), and a **"Reddit" tab
on the sheet**, which is what Joe actually copies from now that the Tuesday
run happens on GitHub and a file on the runner is useless. Title in A1,
body from A3 down, usage note in C1:C3 — off to the side so it can't get
caught in a column-A copy. The tab is created on first run and cleared
before each write, so a shorter post can't leave last week's rows dangling
below it.

The body is written **one line per row, not one multi-line cell**: a cell
containing newlines gets quote-wrapped when you copy it into a plain text
field like Reddit's, while a column of one-line cells pastes clean.

`finalize_live_sheet.py` needs no `schedule.csv` on a mid-week run: it
falls back to the sheet's own row count, which Tuesday already trimmed to
this week's team count. That's why a fresh CI checkout with no CSVs on
disk still finalizes correctly.

Two row-matching patterns are used throughout, per column:
- **Own team** (columns B, C, D, G, J, K): matched by the row's own Team (B).
- **Opponent** (columns F, H, I): matched by looking up the row's Opp (E)
  in the source's data.

## Column-by-column source map
| Col | Header | Source | Match | Direction |
|---|---|---|---|---|
| B | Team | nflverse schedules | — (establishes row order) | — |
| C | Rost% | Yahoo (`R_O` view) | own team | plain %, written as a real fraction + "0%" format |
| D | Start% | Yahoo (`R_O` view) | own team | same as C |
| E | Opp | nflverse schedules | — | "@ABBR" if away, "ABBR" if home |
| F | Imp | The Odds API | **opponent's** rank | 1 = highest implied total (toughest offense), 32 = lowest |
| G | Def Rating | nflverse pbp + Joe's preseason ranks | own team | already ranked 32 = best own defense, written as-is (no inversion) |
| H | Opp Off EPA | nflverse pbp (offensive EPA/play) | **opponent's** rank | 1 = best offense, used AS-IS (high = weak offense = good matchup, no inversion needed) |
| I | Pressure | Sharp Football Analysis | **opponent's** rank | 1 = allows least pressure, 32 = allows most |
| J | ECR | FantasyPros consensus (DST, 36 experts) | own team | FantasyPros rank inverted (33-rank), so 32 = best |
| K | Proj | Yahoo (`S_PW_<week>` view) **+ Subvertadown adjustment** | own team | Yahoo's projected points plus Subvertadown's situational adjustment, as one plain number — **ranked inside the SCORE formula**, not pre-ranked by a push script |
| A | SCORE | `finalize_live_sheet.py` | — | `=SUM(F:J)+RANK.EQ(K, K:K, 1)+IF(@ in E, 0, 5)` per row, filled by script |

## Per-source fetcher notes

**Schedule / team list** (`fetch_schedule.py`) — nflverse's `schedules`
release (`games.csv.gz`, the whole season, ~272 games). One output row per
team per week, so bye weeks fall out naturally: a team with no game simply
isn't there, and the sheet ends up with however many teams actually play.
Cached locally but **age-checked, not existence-checked** (12h): nflverse
revises this file in-season for flexed and rescheduled games, so a stale
cache would quietly serve the wrong matchups. Verified against the Week 2
board the old Subvertadown scrape produced: all 32 teams and all 32
opponents matched exactly, 0 reciprocity errors.

**Defense rating** (`fetch_def_rating.py`) — column G, the self-owned
answer to Def DAVE. A 50/50 z-blend of **EPA/play allowed** and **success
rate allowed** from nflverse play-by-play, then shrunk toward **Joe's own
preseason defensive ranks** (`preseason_def_ranks.csv`, 1 = best) at
`K_PRIOR = 300` plays (~4.5 games).

The prior is not optional garnish — defense barely carries over year to
year (last season → this season correlates only 0.169), so a few games is
mostly noise, and shrinking toward *league average* instead would flatten
all 32 teams and let that noise decide the ranking. Backtested, the blend
beats both of its own halves: at 100 plays, observed 0.118 / prior 0.161 /
**blended 0.204**; at 300 plays, 0.223 / 0.155 / **0.276**. (That's a
*ranking* result. An earlier RMSE test suggested a prior needs ρ ≥ 0.45 to
help, but that measured value accuracy — this tool only ever uses the rank,
and the conclusion flips.) Success rate is in the blend because it's what
DVOA is built on underneath and it's ~2× more predictive than defensive
EPA early (0.220 vs 0.118 at 100 plays); EPA is in it because the blend is
the most stable of the three late (0.316 at 600 plays).

`preseason_def_ranks.csv` is hand-entered by Joe and is **explicitly
un-ignored** in `.gitignore` (which otherwise ignores `ff_defense/*.csv`)
— nothing regenerates it, and CI needs it. Update it each preseason.

**Offensive EPA** (`fetch_nflverse_epa.py`) — column H, the opponent's
offense. EPA/play regressed toward league average at `K_OFFENSE = 350`.
Every choice was settled by `backtest_epa_regression.py` over 2021-25, not
guessed: garbage time is **included at full weight** (excluding it makes
EPA *less* predictive — 0.122 vs 0.065 — and partial weights were
monotonically worse), there's **no opponent adjustment** (Open Source
Football found it slightly reduces predictive power), and regression is
toward league average rather than last season.

Both nflverse fetchers normalize team codes **before** grouping, because
nflverse carries both `LA` and `LAR` for the Rams across seasons — renaming
after a groupby would leave two half-sized rows for the same team.

**Subvertadown** (`fetch_subvertadown_defense.py`) — **RETIRED, not in the
pipeline.** Kept for reference only. Logged into
subvertadown.com (plain Laravel form POST, not Livewire) via
`SUBVERTADOWN_EMAIL`/`SUBVERTADOWN_PASSWORD`; logged out only 2 of 32 teams
render (confirmed server-side gated, not CSS-blurred). Parses each
`<tr id="row-XXX">`'s team, opponent (`vs.` = home, `@` = away — the Opp
column literally mirrors this), and week's projected D/ST points.

**FTN DAVE** (`fetch_ftn_dave.py`) — **RETIRED, not in the pipeline.**
Kept for reference only (the cookie trick below is genuinely hard-won and
worth not rediscovering). `ftnfantasy.com/stats/nfl/dave` is
cookie-gated (not Bearer-token gated like FTN's rankings API elsewhere in
this repo): login via `api.ftnfantasy.com/users/login` returns
access_token/refresh_token/user_id, and **all three** must be set as
cookies on domain `.ftnfantasy.com` — access_token alone renders 0 real
rows, all three renders the full table. Also needs a normal
Accept/Referer header set or ftnfantasy.com 403s (basic Cloudflare check,
not real bot-fingerprinting).

**Implied totals** (`fetch_implied_totals.py`) — uses The Odds API
(`ODDS_API_KEY` in `.env`) for live spreads/totals rather than
eatdrinkandsleepfootball.com's free page (which the sheet's own "IMP" tab
originally linked to) — Joe wanted a guaranteed-fresh source, and a
manually-curated page has no guaranteed update cadence. Filters
`/v4/sports/americanfootball_nfl/odds/`'s response (which returns ALL
upcoming games, multiple weeks) down to the soonest 16 games by
commence_time — confirmed live this returns a clean 16-game block per
week with a multi-day gap to the next week's block. FanDuel preferred
(matches the original page's own methodology), falls back to whichever
book is available. `implied_total = O/U/2 - team's own spread/2`.

**Subvertadown situational adjustment** (`fetch_subvertadown_adjustment.py`)
— a Google Sheet Subvertadown shares with Joe directly
(`1xGTyPr2LrPBME5G_-jHChjFoWvACg2P-RiQxfoyjV8E`, owned by
subvertadown@gmail.com), read-only via the same service account. Plain
32-row grid, **no header**: A nickname, B abbreviation, C signed adjustment
in fantasy points, D rank. Only column C is used, and it's ADDED to Yahoo's
projection in `push_proj_to_sheet.py` — Joe wanted one projection column,
not two competing ones.

**Staleness is the real risk here, not access.** The sheet carries no week
marker anywhere in its contents, so a copy from three weeks ago is
indistinguishable from a fresh one. What does tell us is Drive's
`modifiedTime`, which is why this fetcher asks for
`drive.metadata.readonly` on top of the usual Sheets scope — the only
script here that needs a second scope. Two thresholds:
- **Older than this week's Tuesday** → warn, still write. On a Tuesday
  morning he may just not have posted yet, and last week's read beats
  nothing. Joe's explicit call: he said he isn't worried about staleness.
- **Older than LAST week's Tuesday** → refuse to write the CSV, exit 1.
  That's the sheet going quiet rather than running late, and silently
  adding month-old adjustments to every projection for the rest of the
  season is the one failure nobody would spot. `push_proj_to_sheet.py`
  falls back to raw Yahoo. `--ignore-staleness` overrides.

The exit 1 is deliberate: it surfaces in run_all's failure summary and
turns the workflow red, so Joe gets told. Degraded output he doesn't know
about is worse than a red check.

**Yahoo D/ST** (`fetch_yahoo_def.py`) — two different `stat1` views on
the same public league Players page (no login — confirmed publicly
viewable even under the private league's URL, same as
`ff_draft_proj/fetch_yahoo_projections.py`): `stat1=R_O` has Rost%/Start%
but no projection; `stat1=S_PW_<week>` has that week's "Fan Pts"
projection but only Rost%, no Start%. Merges both. Yahoo's own OAuth API
(`percent_started`) would give this more cleanly, but the project's
registered Yahoo app returns "This application is not authorized to
perform this action" on every call even with a freshly re-authorized
token — looks like a Yahoo-side approval problem on the app itself, and
Joe can't edit Client Type/API Permissions after creation to fix it. The
page-scrape sidesteps needing that API at all.

**FantasyPros DST ECR** (`fetch_fantasypros_dst_ecr.py`) — same public
partner API (`partners.fantasypros.com/api/v1/consensus-rankings.php`)
already used in `ff_rankings`; omitting `filters=<expert_id>` gives the
full consensus instead of one analyst (confirmed `total_experts=36`).
`player_team_id` already matches this sheet's abbreviation convention
exactly, no aliasing needed.

**Pressure rate** (`fetch_pressure_rate.py`) — **not** PFR, despite that
being Joe's original source and what this column is named after
internally. PFR now sits behind a real Cloudflare "Verify you are human"
interactive challenge (not just a header check) that isn't reliably
clickable by automation — didn't force it. FTN's Stats iQ tool
(`stats.ftnfantasy.com`, Team Offense > Pass Protection > PRESS%) was
tried first: it's a plain public JSON API with no auth needed, but it
only had 1 game logged per team this early in the season, and
specifically the Denver/Kansas City game (they played each other) wasn't
fully charted yet — both showed a suspicious flat 0%, confirmed by
cross-referencing PFR's own row for that game (PktTime/Blitz/Hrry all
exactly 0 there too — the same data gap, not an FTN-specific bug). Joe
ruled FTN out for that lag and asked for Sharp Football Analysis
(`sharpfootballanalysis.com/stats-nfl/nfl-offensive-line-stats/`)
instead — also a plain public page, no login, no Cloudflare wall.

**Important: Sharp, FTN, and PFR do not closely agree with each other**
beyond the extremes (all three currently agree Green Bay is worst-ish and
the 49ers are top-tier) — e.g. PFR had Bengals 19th while Sharp had them
1st, a 15-20 spot swing on several teams. This isn't noise from one bad
data point — "pressure" is a subjectively-charted stat (what counts as a
hurry vs. incidental contact is a judgment call), not an official boxscore
number like sacks, so real cross-source disagreement is normal and won't
resolve as the season goes on. Sharp is simply the source Joe picked given
FTN's specific data-lag problem — not a claim that it's more "correct."

## finalize_live_sheet.py — must run last
Three jobs, using `schedule.csv`'s row count as the authoritative "how
many teams have a game this week" number (bye weeks mean fewer than 32):
1. Deletes any leftover sheet rows beyond that count (up to a fixed
   buffer of row 40) — actual row deletion via `deleteDimension`, not
   just clearing cell contents, so a bye week doesn't leave stale blank
   or (worse) stale non-blank rows sitting around from a fuller previous
   week.
2. Fills column A's SCORE formula down through the last real team row,
   writing each row's formula explicitly since there's no spreadsheet UI
   "fill handle" to rely on headlessly:
   `=SUM(F{r}:J{r})+RANK.EQ(K{r}, K:K, 1)+IF(ISNUMBER(SEARCH("@", E{r})), 0, 5)`

   Three things to know about it:
   - `F:J` is contiguous now that Subvertadown's column is gone.
   - `RANK.EQ(K, K:K, 1)` scores the Yahoo projection. **Order `1` is
     ascending**, so the lowest projection ranks 1 and the highest ranks 32
     — matching every other column, where a bigger number is better. It's
     ranked rather than added raw so one column of fantasy points can't
     outweigh five columns of 1–32 ranks. The whole-column `K:K` reference
     is safe: RANK.EQ ignores the text header and blank rows. This means
     column K is the one scored column with no ranking push script behind
     it — the sheet does it.
   - The "@" home-bonus test reads column **E** (Opp). It used to read
     **D** (Start%), which never contains an "@" — so every team, home and
     road alike, collected the +5. That never changed the ORDER (a constant
     shifts all 32 scores equally), but the home bonus was doing nothing at
     all until it was fixed.
3. Sorts `A2:K<last row>` descending by column A — header row untouched.

Because every other push script re-reads the sheet's current Team/Opp
columns fresh each time rather than assuming a fixed row order, running
`finalize_live_sheet.py` (which reorders rows via the sort) at a
different point in the sequence wouldn't actually break anything — it's
just simplest to reason about as the last step, so that's the documented
order.
