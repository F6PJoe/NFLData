# Defensive Stream-O-Matic — data sources

Feeds Joe's "Stream-O-Matic" Google Sheet (id
`1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ`), specifically the "Live"
tab: `SCORE | Team | Rost% | Start% | Opp | Imp | Subvertadown | Def DAVE |
Opp Off DAVE | Pressure | ECR | Proj` (A-L). Sheet writes use the same
service-account credentials as the rest of this repo
(`triple-baton-456523-e4-b9ec3cbd6e3d.json` at the repo root) — Joe shared
the "Live" sheet with that service account's email directly.

`team_names.py` is shared by every fetcher/pusher here: `normalize()` maps
a full nickname ("Buccaneers"), a bare abbreviation, or an "@"-prefixed
abbreviation ("@KC") to this sheet's standard code, aliasing each source's
quirks (FTN's "JAX", eatdrinkandsleepfootball's stale stl/sd/oak codes).
`nickname_to_abbr()` derives the code from a full team name's last word.

## Weekly refresh order
```
python fetch_subvertadown_defense.py && python push_subvertadown_to_sheet.py
python fetch_ftn_dave.py && python push_ftn_dave_to_sheet.py
python fetch_implied_totals.py && python push_implied_totals_to_sheet.py
python fetch_yahoo_def.py --week N && python push_yahoo_def_to_sheet.py
python fetch_fantasypros_dst_ecr.py --week N && python push_fantasypros_ecr_to_sheet.py
python fetch_pressure_rate.py && python push_pressure_rate_to_sheet.py
python finalize_live_sheet.py
```
`--week N` (Yahoo, FantasyPros) needs bumping each week. `finalize_live_sheet.py`
must run LAST — see below.

Two row-matching patterns are used throughout, per column:
- **Own team** (columns B, C, D, G, H, L): matched by the row's own Team (B).
- **Opponent** (columns F, I, J, K... wait K is own-team too — see per-source
  notes below): matched by looking up the row's Opp (E) in the source's data.

## Column-by-column source map
| Col | Header | Source | Match | Direction |
|---|---|---|---|---|
| B | Team | Subvertadown | — (establishes row order) | — |
| C | Rost% | Yahoo (`R_O` view) | own team | plain %, written as a real fraction + "0%" format |
| D | Start% | Yahoo (`R_O` view) | own team | same as C |
| E | Opp | Subvertadown | — | "@ABBR" if away, "ABBR" if home |
| F | Imp | The Odds API | **opponent's** rank | 1 = highest implied total (toughest offense), 32 = lowest |
| G | Subvertadown | Subvertadown | own team | 1 = worst projected D/ST, 32 = best |
| H | Def DAVE | FTN `/stats/nfl/dave` | own team | FTN's Def Rank inverted (33-rank), so 32 = best own defense |
| I | Opp Off DAVE | FTN `/stats/nfl/dave` | **opponent's** rank | FTN's Off Rank AS-IS (1 = best offense already means high = weak offense = good matchup, no inversion needed) |
| J | Pressure | Sharp Football Analysis | **opponent's** rank | 1 = allows least pressure, 32 = allows most |
| K | ECR | FantasyPros consensus (DST, 36 experts) | own team | FantasyPros rank inverted (33-rank), so 32 = best |
| L | Proj | Yahoo (`S_PW_<week>` view) | own team | that week's Yahoo-projected fantasy points, plain number |
| A | SCORE | `finalize_live_sheet.py` | — | `=SUM(F:K)+IF(@ in Opp, 0, 5)` per row, filled by script |

## Per-source fetcher notes

**Subvertadown** (`fetch_subvertadown_defense.py`) — logs into
subvertadown.com (plain Laravel form POST, not Livewire) via
`SUBVERTADOWN_EMAIL`/`SUBVERTADOWN_PASSWORD`; logged out only 2 of 32 teams
render (confirmed server-side gated, not CSS-blurred). Parses each
`<tr id="row-XXX">`'s team, opponent (`vs.` = home, `@` = away — the Opp
column literally mirrors this), and week's projected D/ST points.

**FTN DAVE** (`fetch_ftn_dave.py`) — `ftnfantasy.com/stats/nfl/dave` is
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
Three jobs, using `subvertadown_defense.csv`'s row count as the
authoritative "how many teams have a game this week" number (bye weeks
mean fewer than 32):
1. Deletes any leftover sheet rows beyond that count (up to a fixed
   buffer of row 40) — actual row deletion via `deleteDimension`, not
   just clearing cell contents, so a bye week doesn't leave stale blank
   or (worse) stale non-blank rows sitting around from a fuller previous
   week.
2. Fills column A's SCORE formula down through the last real team row,
   writing each row's formula explicitly (`=SUM(F{r}:K{r})+IF(...)`) since
   there's no spreadsheet UI "fill handle" to rely on headlessly.
3. Sorts `A2:L<last row>` descending by column A — header row untouched.

Because every other push script re-reads the sheet's current Team/Opp
columns fresh each time rather than assuming a fixed row order, running
`finalize_live_sheet.py` (which reorders rows via the sort) at a
different point in the sequence wouldn't actually break anything — it's
just simplest to reason about as the last step, so that's the documented
order.
