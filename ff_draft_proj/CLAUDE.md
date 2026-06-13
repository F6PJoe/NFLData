# Fantasy Football Draft Projections — Automation Project

## Goal
Sibling project to `ff_adp` (the consensus-ADP automation repo). Where that
project pulls average draft position, this one pulls **full season-long
(preseason/draft) stat-line projections** per player from each platform's own
source, then combines them into **consensus projections** — same "go to the
source" philosophy, no aggregator/collector sites.

## Sources
ESPN, CBS, PFF, Fantasy Sharks, FFToday, Yahoo, Fantasy Life, Draft Sharks,
4for4, FTN, Fantasy Data.

(FantasyPros was considered but dropped — it's itself a consensus that
already blends ESPN and CBS, so we pull those two directly instead.)

| Source | Notes | Status |
|---|---|---|
| ESPN | `lm-api-reads.fantasy.espn.com` players endpoint, `stats` array, `statSourceId==1` (projected) / `statSplitTypeId==0` (season total), individual stat IDs broken out. No login. | **Built** — `fetch_espn_projections.py` |
| CBS | `cbssports.com/fantasy/football/stats/<POS>/<YEAR>/season/projections/ppr/` — server-rendered HTML table, one row per player. No login. | **Built** — `fetch_cbs_projections.py` |
| FTN | `ls.ftnfantasy.com/api/ftn/players/projections/preseason` — requires login. `ftn_auth.py` logs in via `api.ftnfantasy.com/users/login` using `FTN_EMAIL`/`FTN_PASSWORD` from a local `.env` (see `.env.example`), gets a Bearer token. FTN doesn't report fumbles — left blank. | **Built** — `fetch_ftn_projections.py` |
| Yahoo | Official Fantasy API has no preseason projection stat lines (only actuals/ADP). Instead pull the public "Players" table on a Yahoo league page (`football.fantasysports.yahoo.com/f1/<league_id>/players?...&stat1=S_PS_<year>`), no login needed even though it's under a private league URL. Doesn't expose Pass Att/Comp for QBs — left blank. | **Built** — `fetch_yahoo_projections.py` |
| PFF | `pff.com/api/fantasy/projections` exists but unauthenticated requests only return a fixed 10-player teaser (ignores position/limit params). Login at `auth.pff.com` hard-enforces reCAPTCHA v3 server-side ("Recaptcha is required." returned on POST without a valid token) — confirmed dead end for scripted login, can't forge a token without a real browser. | **Skipped** — would require a manually-refreshed browser session cookie (short-lived, high maintenance) |
| Fantasy Sharks | `fantasysharks.com/apps/bert/forecasts/projections.php` "High-Precision" CSV export, no login. Position ids QB=1/RB=2/WR=4/TE=5; `Segment` id changes yearly (scraped from the page's season `<select>`). WR/TE don't report rush attempts — left blank. | **Built** — `fetch_fantasysharks_projections.py` |
| Draft Sharks | Logged in fine (simple Yii2 form login, no reCAPTCHA). The rankings page (`/rankings/half-ppr`) has a "Projections" toggle that loads stat-line columns via `GET /rankings/load-table?pprSuperflexSlug=half-ppr&fantasyPosition=<POS>&researchDepth=projections&playerGroup=all` (htmx). Gives deep per-position pools (~130 RB, ~110 TE, ~207 WR, ~42 QB). Doesn't expose Rush Attempts, Targets, or fumbles for offensive players — left blank. | **Built** — `fetch_draftsharks_projections.py` |
| Fantasy Data | `fantasydata.com/nfl/fantasy-football-weekly-projections?scope=season&season=<YEAR>&position=<qb|rb|wr|te>&scoring=fpts_ppr&order_by=fpts_ppr&sort_dir=desc&page=<N>` — server-rendered table, paginated (~49 rows/page). Logged out, most rows are hidden behind "SIGN UP TO SEE MORE"; requires login via simple form (`/user/login`, csrf_token/email/password, no reCAPTCHA) using `FANTASYDATA_EMAIL`/`FANTASYDATA_PASSWORD`. QB doesn't report fumbles — left blank. | **Built** — `fetch_fantasydata_projections.py` |
| 4for4 | `4for4.com/projections_csv/<set_id>` returns a single CSV covering all positions (QB/RB/WR/TE/K), with bye week and fumbles included. Requires a 4for4 subscription: simple Drupal login at `/user/login` (form_id=user_login, name/pass, no CSRF/reCAPTCHA) using `FOR4FOR4_EMAIL`/`FOR4FOR4_PASSWORD`. Doesn't report Targets — left blank. | **Built** — `fetch_4for4_projections.py` |
| Fantasy Life | `fantasylife.com/api/datatables/projections?limit=65&offset=<N>&orderBy=-projectedFantasyPoints&seasonId=911c9071-892d-470e-aca8-457144b823cb&scoringSystemId=1c56287f-23de-42ca-b077-6b5f09a8f5f1&rosterPositions=<QB\|RB\|WR\|TE>&projectedProvider=aggregate&projectionPeriod=seasonal&projectionType=avg&perGame=false`, paginated 65/page. Auth is Firebase (project `fantasy-life-1b94f`) — sign in directly against Google's Identity Toolkit REST API (`identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<firebase web api key>`) with `FANTASYLIFE_EMAIL`/`FANTASYLIFE_PASSWORD` to get an `idToken`, sent as the `bearer-token` header. Full stat lines including fumbles lost; bye weeks via ESPN proTeamSchedules. | **Built** — `fetch_fantasylife_projections.py` |
| FFToday | `fftoday.com/rankings/playerproj.php?Season=<YEAR>&PosID=<10\|20\|30\|40>&LeagueID=&order_by=FFPts&sort_order=DESC&cur_page=<N>` — server-rendered table, 50 rows/page, no login. Doesn't report Targets or Fumbles for any position — left blank. Bye week provided directly. | **Built** — `fetch_fftoday_projections.py` |

## Known dead ends (from `FF_Projections` folder, do not repeat)
Past attempts to scrape **4for4, FantasyLife, FantasyPros (UI download), PFF**
via browser automation all failed (login walls / no export option / click
errors). Don't retry those with the same scraping approach — either find a
true public API/export endpoint or skip the source. (PFF confirmed again in
this project — reCAPTCHA v3 on login blocks scripted auth. DraftSharks was
re-attempted in this project and succeeded — see table above.)

## Output schema (per source — stat lines only, no points)
Player name is under the position-specific header (e.g. "QB" column header,
player name as the value). All stat columns below are projected season
totals. Per-source CSVs do NOT include fantasy points — those are only
computed once in the consensus output (via `scoring.py`), from the averaged
stat line, so they reflect the blended consensus rather than each source's
own scoring assumptions.

**QB**
```
QB | Team | Bye | Pass Att | Pass Comp | Pass Yds | Pass TD | Pass Int | Rush Att | Rush Yds | Rush TD | Fumbles
```

**RB**
```
RB | Team | Bye | Rush Att | Rush Yds | Rush TD | Targets | Rec | Rec Yds | Rec TD | Fum
```

**WR**
```
WR | Team | Bye | Targets | Rec | Rec Yds | Rec TD | Rush Att | Rush Yds | Rush TD | Fum
```

**TE**
```
TE | Team | Bye | Targets | Rec | Rec Yds | Rec TD | Rush Att | Rush Yds | Rush TD
```

## Consensus
Once per-source CSVs exist with the schemas above (same columns, one row per
player), combine into a consensus CSV per position: average each stat column
across sources that have the player, then compute fantasy points (Fantasy
Points / Fantasy Points (Half-PPR/PPR/STD) / TE Premium, per position) from
the averaged stat line via `scoring.py`. This is the only place fantasy
points are calculated.

## Conventions / ground rules
- Send a normal `User-Agent`. Fetch and cache — don't hammer endpoints.
  Personal use of my own/public data.
- Keep credentials (Yahoo OAuth token, any session cookies) out of the code —
  local `.env` or config file, never commit them.
- Output one CSV per source per position (e.g. `espn_qb.csv`,
  `fantasypros_rb.csv`), plus consensus CSVs (`consensus_qb.csv`, etc.).

## Status / next steps
1. `fetch_espn_projections.py` — **done**. Writes `espn_qb.csv`,
   `espn_rb.csv`, `espn_wr.csv`, `espn_te.csv`.
2. `fetch_cbs_projections.py` — **done**. Writes `cbs_qb.csv`, `cbs_rb.csv`,
   `cbs_wr.csv`, `cbs_te.csv`. (CBS doesn't provide TE rushing stats —
   left blank.)
3. `fetch_ftn_projections.py` — **done**. Writes `ftn_qb.csv`, `ftn_rb.csv`,
   `ftn_wr.csv`, `ftn_te.csv`. Requires `FTN_EMAIL`/`FTN_PASSWORD` in a local
   `.env`. (FTN doesn't report fumbles — left blank.)

   All writers produce full stat lines, bye weeks, and fantasy points
   computed via `scoring.py` (shared scoring module for standard/half/PPR/
   TE-premium, used by all sources for consistency).
3b. `fetch_fantasysharks_projections.py` — **done**. Writes
   `fantasysharks_qb.csv`, `fantasysharks_rb.csv`, `fantasysharks_wr.csv`,
   `fantasysharks_te.csv`. No login. (WR/TE rush attempts left blank.)
3c. `fetch_yahoo_projections.py` — **done**. Writes `yahoo_qb.csv`,
   `yahoo_rb.csv`, `yahoo_wr.csv`, `yahoo_te.csv`. No auth needed — the
   league players page is publicly viewable. (QB Pass Att/Comp left blank.)
3d. `fetch_draftsharks_projections.py` — **done**. Writes `draftsharks_qb.csv`,
   `draftsharks_rb.csv`, `draftsharks_wr.csv`, `draftsharks_te.csv`. Requires
   `DRAFTSHARKS_EMAIL`/`DRAFTSHARKS_PASSWORD` in a local `.env`. (Rush Att,
   Targets, and Fumbles left blank — not exposed in this view.)
3e. `fetch_fantasydata_projections.py` — **done**. Writes `fantasydata_qb.csv`,
   `fantasydata_rb.csv`, `fantasydata_wr.csv`, `fantasydata_te.csv`. Requires
   `FANTASYDATA_EMAIL`/`FANTASYDATA_PASSWORD` in a local `.env`. (QB Fumbles
   left blank — not reported.)
3f. `fetch_4for4_projections.py` — **done**. Writes `4for4_qb.csv`,
   `4for4_rb.csv`, `4for4_wr.csv`, `4for4_te.csv`. Requires
   `FOR4FOR4_EMAIL`/`FOR4FOR4_PASSWORD` in a local `.env`. (Targets left
   blank — not reported.)
3g. `fetch_fantasylife_projections.py` — **done**. Writes `fantasylife_qb.csv`,
   `fantasylife_rb.csv`, `fantasylife_wr.csv`, `fantasylife_te.csv`. Requires
   `FANTASYLIFE_EMAIL`/`FANTASYLIFE_PASSWORD` in a local `.env`. Full stat
   lines, including fumbles lost.
3h. `fetch_fftoday_projections.py` — **done**. Writes `fftoday_qb.csv`,
   `fftoday_rb.csv`, `fftoday_wr.csv`, `fftoday_te.csv`. No login. (Targets
   and Fumbles left blank — not reported.)
4. All sources are now built (PFF skipped — reCAPTCHA v3 hard-enforced
   server-side, confirmed dead end even via direct API POST).
5. `build_consensus.py` — **done**. Reads `<source>_<pos>.csv` for all 10
   sources, matches players by a normalized name (strip accents/diacritics
   e.g. "Estimé"→"Estime", lowercase, strip periods/apostrophes,
   hyphens→spaces, drop Jr/Sr/II/III/IV/V suffixes, plus
   a small `NAME_ALIASES` map for known cross-source nickname mismatches
   e.g. "Cam Skattebo"/"Cameron Skattebo", "Woody Marks"/"Jo'quavioius
   Marks"), strips trailing injury-status tokens some sources append to
   names (e.g. "Daniel Jones&nbsp;&nbsp;O" → "Daniel Jones"), normalizes team
   abbreviations to a fixed 32-team + FA set via `clean_team`/`TEAM_ALIASES`
   (JAX→JAC, WSH→WAS, LA→LAR, NA/UNS/blank/garbage→FA), averages each stat
   column across sources that report it, picks a Team/Bye from whichever
   source has one, computes fantasy points from the averaged stat line via
   `scoring.py`, and drops any player projected for 0 fantasy points. Writes
   `consensus_qb.csv`, `consensus_rb.csv`, `consensus_wr.csv`,
   `consensus_te.csv` — each is the per-source schema plus Fantasy Points
   column(s), matching the live Google Sheet's existing column order/names
   (QB: "Fantasy Points"; RB/WR: Half-PPR/PPR/STD — WR's half column is named
   "Fantasy Points (Half)"; TE: Half-PPR/PPR/"TE Premium" — TE Premium is
   1.5 pts/reception, via `scoring.te_premium_points`), sorted descending by
   the primary fantasy points column.
6. `push_to_sheets.py` — **done**. Pushes each `consensus_<pos>.csv` to the
   live Google Sheet (id `1HoxQZOsM0LFzHxEqCGv5yQJKa_ifdzasZoEHkMGVItQ`),
   tabs "LIVE PROJECTIONS QB/RB/WR/TE", sorted descending by half-PPR points
   (QB sorts by its single "Fantasy Points" column). Writes data starting at
   row 2 — row 1 (headers) is never touched. Uses the same service-account
   credentials as `ff_adp` (`triple-baton-456523-e4-b9ec3cbd6e3d.json`,
   gitignored via `*.json`, copied from the `FF_ADP` repo root).
