# IDP Points Against

## Goal
A "points allowed" tool for IDP (individual defensive player) leagues —
which OFFENSES are the juiciest matchups to stream a defensive lineman,
linebacker, or safety against. Deliberately a **separate project/page**
from `ff_points_against` (offense QB/RB/WR/TE + team DST) — the user asked
for it standalone, since the whole axis is different (3 IDP scoring
systems instead of std/half/PPR, DL/LB/S positions instead of offensive
skill positions) and mixing it into the offense tables would be confusing.

## Same direction as `ff_points_against`'s DST table, generalized per-player
"Points against" always means "how many fantasy points did the opposing
unit score against MY team" — for offense that's an opposing skill player
scoring against my defense; for DST it's the opposing DEFENSE scoring
against my OFFENSE. IDP is the same DST direction, just broken out by
individual defender instead of one combined team number: for each team,
sum how many fantasy points *opposing* DL/LB/S players scored against that
team's offense, attributed to that team (the offense that gave it up).

No points-allowed tier here (unlike DST) — that's a team-defense bonus stat,
not part of individual IDP scoring in any of the 3 systems below. Pure
per-player stat-line scoring summed by team+week.

## Data source: same file as `ff_points_against`, no new sourcing needed
`stats_player_week_<year>.csv` (nflverse) already carries every individual
defender stat all 3 scoring systems need — checked against nflverse's own
`dictionary_playerstats_def.csv` (fetched directly, not guessed) before
writing anything: tackles (solo/assisted), tackles for loss, QB hits, sacks
(+yards), interceptions (+yards), passes defended, forced fumbles, fumble
recoveries (+yards), safeties, blocked kicks, defensive/special-teams TDs.

**Assisted-tackle column**: nflverse has two similarly-named columns,
`def_tackles_with_assist` and `def_tackle_assists`. Checked real 2025 data
directly — `def_tackles_with_assist` is almost always 0 even for players
who clearly picked up special-teams tackle assists (long snappers,
fullbacks show up with nonzero assists in real box scores), while
`def_tackle_assists` matches that real pattern. Used `def_tackle_assists`.

**Position buckets — DL/LB/S only, no CB/DB bucket** (per explicit user
ask). Checked the real distribution of `position` spellings on
defensive-stat rows in 2025 before writing `POS_BUCKET`:
```
DE, DT, NT, DL   -> DL
LB, OLB, MLB, ILB -> LB
S, SS, FS, SAF   -> S
```
`CB`/`DB` rows are excluded entirely, not folded into S — "DB" is genuinely
ambiguous (corner or safety) and the user asked for S specifically, not a
merged secondary bucket. A handful of non-defensive positions (WR, RB, K,
LS, etc.) occasionally show nonzero defensive-stat columns from rare
special-teams plays (a blocked-kick recovery, a trick-play tackle) — these
fall through `POS_BUCKET` unmatched and are correctly excluded too.

## Scoring — 3 systems, all per the user's own bullet lists
All three are pure per-player formulas (`fetch_nflverse_idp_points_against.py`,
`points_123`/`points_big3`/`points_fantasypros`):

**1-2-3** (idparmy.com/idp123): 1pt = assisted tackle, QB hit · 2pt = solo
tackle, TFL · 3pt = pass defended, forced fumble, fumble recovery, safety,
blocked kick · 6pt = interception, sack, touchdown.

**Big 3** (theidpshow.com): .1pt = sack yards, any return yards (INT +
fumble-recovery return yards) · .75pt = assisted tackle · 1.25pt = solo
tackle · 2pt = QB hit · 3pt = fumble recovery, TFL · 4pt = pass defended,
forced fumble · 5pt = blocked kick, sack, safety · 6pt = interception,
touchdown.

**FantasyPros** (fantasypros.com/scoring-settings): solo tackle = 1.5,
assisted tackle = 0.75, TFL = 2.5, sack/forced-fumble/fumble-recovery = 4
**each** (their bullet list lumps all three event types under one shared
"4 pts" line rather than pricing them apart — implemented literally, so a
strip-sack a player both causes and recovers himself stacks 4+4+4; flagged
as an assumption, not verified against FantasyPros' actual settings page
internals), interception = 5, defensive TD = 6, safety = 2, pass defended
= 1.5. No QB-hit/blocked-kick/yardage terms in this system — they simply
score 0, per the bullet list not mentioning them.

**Verified for plausibility** (no external IDP "points against" page exists
to check against, same caveat as DST): 2025 season position ordering is LB
> DL > S in every one of the 3 formats, matching the well-known real-world
IDP pattern that linebackers accumulate the most raw counting stats — the
right shape, not a line-by-line verification.

## Pipeline
`fetch_nflverse_idp_points_against.py --year <YYYY> [--refresh]` — same
fetch/cache pattern as `ff_points_against` (always pass `--refresh` for a
real weekly run). Writes `data/idp_points_against_<year>.json` (`{season,
weeks, formats:{one_two_three|big3|fantasypros: {DL|LB|S: {TEAM:
{weeks:{wk:pts}, avg}}}}}`) and a long-form reference CSV, same shapes as
the sibling project.

## Display — same component pattern as `ff_points_against`
`component.html` (`#f6p-idp` root, distinct from that project's `#f6p-pa`
so both could theoretically sit on the same page without CSS/JS collision,
though they're on separate posts): scoring-system toggle (1-2-3/Big 3/
FantasyPros) where the offense page has its format toggle, DL/LB/S
position tabs where it has QB/RB/WR/TE/DST, same rank column, same
Team/AVG sticky columns, same click-any-column-to-sort, same season
dropdown (2026/2025, `DATA_URL_PATTERN` ->
`/wp-content/uploads/f6p-data/idp_points_against_{season}.json`), same
color scheme. Meta line reads "higher AVG = juicier streaming matchup"
instead of the offense page's "lower AVG = tougher matchup" — the row team
here is the OFFENSE being measured, so a high number is good news for
someone streaming an IDP against them, the opposite framing from a
defense's own points-allowed table.

**Paste `component.html` directly into a Gutenberg Custom HTML block** —
same discovery as `ff_points_against` (that bypasses `wpautop`, and the
component already avoids `force_balance_tags()` corruption via
`createElement`/`textContent`). `build_embed.py`/`embed.html` exist only as
a Classic-Editor fallback, not the normal workflow.

## Publishing
`sftp_upload.py` — same SiteGround account as `ff_points_against`/
`ff_utilization` (credentials copied into this project's own `.env`,
gitignored). Uploads every local `data/idp_points_against_<year>.json` to
`wp-content/uploads/f6p-data/`, `--dry-run` first. Not automated on a
schedule yet — manual `fetch... --refresh && sftp_upload.py` after each
week's games, same as the sibling project.

## Not yet done
- No legacy page/data exists for this to be checked against (unlike the
  offense tables, which had 3 years of a live FantasyData-sourced page to
  verify against) — accuracy rests on the nflverse dictionary + plausibility
  checks above, not a line-by-line match to a known-correct source.
- Weekly refresh cadence not automated (no GitHub Action/cron trigger yet).
- Historical seasons before 2025 not pulled — should work unchanged
  (`stats_player_week` goes back to 1999) if ever wanted.
- WordPress post for this doesn't exist yet — needs to be created before
  `component.html` can be pasted anywhere live.
