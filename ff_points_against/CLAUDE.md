# Fantasy Football Points Against

## Goal
Replace the old manual workflow for the site's "Points Against" tables
(fantasysixpack.net/fantasy-football-points-against-{standard,half-ppr,ppr}/):
download a weekly CSV per position from FantasyData, paste into a Google
Sheet of VLOOKUPs, display via wp-datatables (slow — the whole reason this
project exists; see "Display" below).

## Data source: nflverse, not Sportradar or GSIS gamebooks
This table only needs player BOX SCORE stats grouped by *opponent* — it is
not a participation/snap-count problem the way `ff_utilization` was, so the
constraints that pushed that project to FantasyLife/PFF don't apply here.
`stats_player_week_<year>.csv` (nflverse-data release `stats_player`)
already carries `opponent_team`, `position`, and every counting stat
scoring needs — free, no login, no reason to pay for Sportradar or parse
GSIS gamebook PDFs for this.

**Confirmed live and fresh for the current season**: the file's
Last-Modified timestamp matched same-day during week 2 2026 testing.
`load_player_stats()`'s own documented schedule is a nightly rebuild during
the season (plus extra pulses on game days), so Sunday's games are in by
Monday morning. The NFL issues stat corrections Monday-Wednesday, so a
Thursday pull is nflverse's own recommended "most final" version — same
caveat as everywhere else in this repo that reads nflverse in-season.
https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html

**Team code note**: nflverse spells the Rams "LA"; every table on the site
(and the legacy Google Sheet) uses "LAR". `TEAM_FIX = {"LA": "LAR"}` in
`fetch_nflverse_points_against.py` handles this — no other team code
differs (checked JAX/WAS directly against the live site, both already
match).

## Scoring
Reuses `ff_draft_proj/scoring.py`'s rushing/receiving/fumble/QB formulas
directly (imported, not forked) — one scoring rule set in the repo. One
addition on top: **2-point conversions** (2 pts each, passing or
rushing/receiving), which `scoring.py` doesn't model since preseason
projections never project 2pt conversions. Real games have them, and this
was the entire gap found when the pipeline was checked against the legacy
FantasyData-sourced numbers already live on the site (see Verification).

**Confirmed: the user's league scoring has no bonus thresholds** (300+
passing yards, 100+ rushing/receiving, long-TD bonuses, etc.) — asked
directly rather than guessed, since some FantasyData exports support
custom bonus scoring and a handful of the legacy numbers looked like they
might include one. Plain std/half-PPR/PPR scoring + 2pt conversions is the
whole formula.

## DST (team defense)
Added per user request: "points allowed to defenses" — the mirror image of
the QB/RB/WR/TE tables. Those measure how many fantasy points opposing
offensive players score against a team's DEFENSE; DST measures how many
fantasy points an opposing DEFENSE scores against a team's OFFENSE. Same
"points against" direction throughout this project, just the other side of
the ball — attributed to the OPPONENT (the offense that gave the points up),
not the team whose defense scored them.

**Scoring: standard/ESPN-default team-defense rules**, same regardless of
std/half/PPR (matches QB, which also doesn't vary by format) — sack = 1,
interception = 2, fumble recovery = 2, safety = 2, defensive TD = 6,
special-teams TD = 6, blocked kick (punt/FG/PAT) = 2, plus a points-allowed
tier (0=10, 1-6=7, 7-13=4, 14-20=1, 21-27=0, 28-34=-1, 35+=-4). This is a
genuine assumption, not verified against the user's specific league or the
legacy site (which never published a DST table to check against) — DST
scoring varies more across platforms than offense scoring does, so if the
numbers look off against a real league, the fix is adjusting
`POINTS_ALLOWED_TIERS`/the per-play point values in
`fetch_nflverse_points_against.py`, not the pipeline itself.

**Data**: `stats_player_week` has no team-level defense row, but it DOES
carry individual defenders' own stat lines (`def_sacks`, `def_interceptions`,
`fumble_recovery_opp`, `def_safeties`, `def_tds`, `special_teams_tds`,
`def_punt_blocks`/`def_pat_blocks`/`def_fg_blocks`) — summed by `team` and
`week` across every defender's row, this reconstructs the team total.
`fumble_recovery_opp` specifically (not `fumble_recovery_own`, which is the
offense recovering its own fumble) is what corresponds to a real "Fumble
Recovery" DST stat. **Points allowed** (the tier) needs the game's real
final score, which isn't in `stats_player_week` at all — pulled from
nfldata's `games.csv` (`home_score`/`away_score`), same source
`ff_utilization` already uses for its own schedule needs. A future/unplayed
game has no score yet and is simply skipped, same as a bye.

**Verified for plausibility, not against a known-correct external source**
(no legacy DST page exists to check against, unlike QB/RB/WR/TE): 2025
season averages ranged 2.8 (Bears) to 11.2 (Raiders) points/week, and the
teams at each extreme match known 2025 offensive-quality patterns
(turnover-prone/bad offenses like LV/MIN/CLE at the high end, disciplined
ones like CHI/DAL/BUF at the low end) — the right shape and scale for
standard weekly DST scoring, but this is a sanity check, not a line-by-line
verification like QB got.

**UI**: DST is a 5th position tab (`QB RB WR TE DST`), not a separate
control — it already fits the existing Team x Week x AVG grid and duplicates
across all 3 format buttons identically (same reason QB does).

## Verification against the legacy site data
Spot-checked Minnesota's 2025 QB half-PPR row (18 weeks) against the live
`fantasy-football-points-against-half-ppr` page. Before adding 2pt
conversions: 11/18 weeks exact. After: 12/18 exact, remaining 6 weeks off
by 1-3 points, always LOWER than the legacy number, never higher. Traced
one instance (Lamar Jackson's 2pt conversion, week 10) to confirm the 2pt
fix works correctly. The remaining small, one-directional gap is
unexplained by anything in the raw stat line (checked fumbles, INTs,
passing yards directly) — most likely the legacy page reflects stats as
they stood when captured mid-season, before the NFL's Monday-Wednesday
correction window closed, while nflverse's historical file reflects final,
corrected numbers. **Accepted as a known, minor limitation** — the user
confirmed there's no bonus-scoring configuration that would explain it, and
final/corrected numbers are arguably more correct than what a page written
mid-season 2025 happened to freeze.

## Pipeline
`fetch_nflverse_points_against.py --year <YYYY> [--refresh]`
1. Downloads (caches in `cached/nflverse/`) `stats_player_week_<year>.csv`.
   **Always pass `--refresh` for a real weekly run** — same one-file-per-
   season, overwritten-in-place trap documented in `ff_utilization` (a
   stale cache silently reports last week's numbers forever).
2. Filters to `season_type == REG`, `position in (QB, RB, WR, TE)`.
3. Computes each player-week's fantasy points (std/half_ppr/ppr) via
   `scoring.py` + the 2pt-conversion addition, and sums into
   `points[format][position][opponent_team][week]`.
4. A team's bye week is simply absent from its weekly stats file (no row
   for a game that didn't happen) — tracked via a `played` set per team so
   the JSON output has no entry for that week (renders as a blank cell,
   matching the legacy site) rather than a false zero. AVG divides by
   weeks actually played, not by the full season length.
5. Writes two files per season into `data/`:
   - `points_against_<year>.json` — `{season, weeks:[...], formats:{std|
     half_ppr|ppr: {QB|RB|WR|TE: {TEAM: {weeks:{wk:pts}, avg}}}}}`. What
     the site's grid fetches. All 3 formats + 4 positions in one file
     (~70 KB for a full season) — small enough that splitting per-format
     isn't worth the extra files to keep in sync.
   - `points_against_<year>.csv` — long-form reference
     (season,format,position,team,week,points), one row per team-week.
     Easy to spot-check by hand or diff against old FantasyData exports;
     not used by the site.

## Display — static JSON + vanilla-JS grid, not wp-datatables
Same fix `ff_utilization` already proved out for its own "wp-datatables is
too slow" problem (see that project's CLAUDE.md) — a static JSON file plus
a small dependency-free JS component, no server-side table plugin. This
table is much smaller than utilization's (one file, ~70 KB, vs. utilization's
weekly 700 KB+) so there was never a real scaling question here, just
reusing the proven approach instead of the wp-datatables path that was
already known to be slow.

**`component.html` is the only file to edit** (same convention as
`ff_utilization`/`ff_auction_values`) — a Team x Week pivot table per
position (QB/RB/WR/TE tab buttons, matching the site's current UI) sorted
ascending by season AVG by default (lower AVG = tougher matchup to start
against, matches the live site's existing sort), click the AVG header to
flip direction. Bye weeks render as a blank cell. Sticky Team column +
horizontal scroll handles mobile instead of the old "expand team to see
weeks" wp-datatables behavior — simpler, and consistent with how
`ff_utilization`'s table handles the same problem.

Color scheme matches the site's existing table convention exactly (same
values `ff_utilization` uses): header `#cc5e03` white text, hover/sorted
`#660000` white text. No colored/heat-mapped cells — `ff_utilization`
already established the user doesn't want that (asked twice what a
similar color treatment meant, removed it) — carried that preference over
here without waiting to be asked again.

**Consolidated to a single WordPress post** (`build_embed.py` produces one
`embed.html`), with a Standard/Half-PPR/PPR toggle row above the existing
Position tabs (`.f6p-pa-viewswitch`, styled heavier than the position
buttons — same visual-weight convention `ff_utilization`'s own weekly/
season toggle uses, for the same reason: it switches the whole dataset,
not just narrows within it). The site used to have 3 separate posts
(`/fantasy-football-points-against-{standard,half-ppr,ppr}/`) purely
because wp-datatables was too slow to load all 3 formats' tables on one
page — confirmed with the user this was the only reason for the split,
not an SEO/URL-structure decision, so it doesn't apply to a static-JSON +
JS grid and the posts should be merged into one. Default format on load is
half-PPR (matches the JSON's key order and was the most-referenced of the
3 legacy pages).

**Season selector**: a `<select>` (2026/2025, 2026 default) alongside the
position tabs. `DATA_URL_PATTERN` (`/wp-content/uploads/f6p-data/
points_against_{season}.json`) is filled in per season and fetched lazily
on first use, cached client-side per season after that (switching back to
an already-loaded season doesn't re-fetch). Each season needs its own JSON
uploaded to that same fixed folder (`points_against_2025.json`,
`points_against_2026.json`, ...) — adding a future season means uploading
its file and adding one `<option>` to `component.html`. Verified in a browser against real 2025 data: QB numbers
are identical across all 3 formats (correct — QBs don't get a PPR bonus),
RB numbers visibly change when switching to PPR (reception credit flowing
through), and the meta line/sort/position-tab state all survive a format
switch correctly.

**`build_embed.py`** reuses `ff_auction_values/web_chart_utils.py`'s
`collapse_script_style_blocks`/`strip_blank_lines` directly (imported, not
copied) — that module has the full multi-round history of why wpautop and
`force_balance_tags()` corrupt an inline `<script>`/`<style>` block pasted
into the Classic Editor's Text view, and why the fix is collapsing to one
line + building table rows with `createElement`/`.textContent` rather than
`innerHTML` string concatenation. `component.html` already follows both
rules (no `//` line comments, no tag-shaped JS string literals);
`build_embed.py` asserts both, plus "no `-->` before the start marker" and
"no `s2If` string leaked in," same checks `ff_utilization` runs on its own
embeds.

`preview.html` (repo root of this project) is an uncollapsed dev copy
wired to `data/points_against_2025.json` directly — never goes through
WordPress, same "dev copy stays uncollapsed" convention as
`ff_utilization`'s `usage_table.html`. Serve locally and open, same as
that project:
```
python -m http.server 8791
# then open http://127.0.0.1:8791/preview.html
```

## Not yet done
- **Merging the 3 legacy posts into 1 on the WordPress side.** The old
  standard/half-PPR/PPR posts still exist as 3 separate URLs. Need to
  decide (with the user) which one becomes the single surviving post
  (paste `embed.html` there) and what happens to the other 2 (redirect to
  the survivor, or leave standing) — not yet done, just the component/
  build side.
- **Post content is still pasted by hand.** The user pastes `component.html`
  directly into a Gutenberg **Custom HTML block** — confirmed this bypasses
  `wpautop` entirely (that filter only runs on Classic Editor Text-view
  content), so the uncollapsed source works fine as-is; `component.html`
  already avoids `force_balance_tags()` corruption too (rows built via
  `createElement`/`textContent`, no tag-shaped JS strings), which runs
  regardless of editor. `build_embed.py`/`embed.html` are kept only as a
  fallback for a Classic-Editor Text-view paste — not the normal workflow
  for this project, don't assume it needs rebuilding on every change.
- **Data upload is automated (`sftp_upload.py`), publish-triggering is
  not.** `sftp_upload.py` (same SiteGround SFTP account as
  `ff_utilization`, credentials copied into this project's own `.env`)
  uploads every local `data/points_against_<year>.json` to
  `wp-content/uploads/f6p-data/` in one command, `--dry-run` first to check
  without writing. No cron/GitHub Action calls it yet — still a manual
  `python fetch_nflverse_points_against.py --year 2026 --refresh && python
  sftp_upload.py` after each week's games.
- **Historical seasons.** Only 2025 (verification) and 2026 (live) have
  been pulled so far. Re-running `fetch_nflverse_points_against.py --year
  <YYYY>` for earlier seasons should work unchanged (nflverse's
  `stats_player_week` goes back to 1999) if the site wants a season
  selector added later.
- **Weekly refresh cadence.** Not yet automated (no GitHub Action). Given
  nflverse's own nightly-during-season / Thursday-is-cleanest schedule,
  a reasonable cadence would mirror `ff_utilization`'s (Monday + Tuesday),
  possibly adding a Thursday re-pull for corrected numbers — not decided.
