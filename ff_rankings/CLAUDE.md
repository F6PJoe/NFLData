# Fantasy Football Rankings — Automation Project

## Goal
Sibling project to `ff_adp` (ADP) and `ff_draft_proj` (stat-line projections).
This one pulls **expert/consensus overall (and per-position) rankings** —
ordinal ranks, not ADP or projected stats — from each source, then combines
them into a blended consensus rank, same "go to the source" philosophy.

Covers both **preseason draft rankings** and the **weekly in-season
rankings** that will start once the season begins — same sources/fetch
logic, just `type=WEEK` and a real `week` number instead of
`type=PRESEASON`/`week=0`, so it's one project rather than two.

## Picking analysts: use multi-year draft accuracy, not reputation
FantasyPros publishes a dedicated **draft-accuracy** leaderboard, one season
at a time, at `fantasypros.com/nfl/accuracy/draft.php?year=<YEAR>` (omit
`year` for the most recent graded season). A single season is noisy/
volatile — e.g. Andrew Erickson ranked #5 in 2024 but averaged ~98th across
2018-2024 — so when picking a source, pull several recent years and average
per-analyst rank (only over analysts present in every year compared, for a
fair sustained-success read) rather than trusting one season or general
reputation. This is how Matthew Hill was chosen as the 4th source below: over
2021-2024 he averaged rank 18 of 132 analysts present in all four years,
better than Sean Koerner (20.5, also unavailable to us) and better than
Jeff Ratcliffe (23.0, already a source — which is itself a nice confirmation
that source is a good one). The same `expert_data` id and `filters=<id>`
trick documented below works for any analyst found on this leaderboard who's
also in FantasyPros' panel.

## Sources
| Source | Notes | Status |
|---|---|---|
| Justin Boone (FantasyPros, embedded on Yahoo's site) | `partners.fantasypros.com/api/v1/consensus-rankings.php` — public partner API, no login. **Important:** the `id` param alone is just a widget-tracking value — it always returns the full industry consensus (~50+ experts blended), regardless of which id you pass. To isolate **one analyst's personal rankings** you must also pass `filters=<expert_id>` (Boone's expert id is `317`). Confirmed by inspecting Yahoo's live embed on its 2026 Boone rankings article — it calls `fantasypros.com/external/widget/fp-widget.php` with `filters=317&half_positions=ALL&scoring=HALF&week=0`, i.e. `filters=317` is exactly what Yahoo publishes, so this reproduces it faithfully (spot-checked against a manually-pasted copy of Yahoo's actual top-300 list — exact match). Drop `export=csv` and hit the JSON form instead — far richer per-player data (team, bye, pos rank, tier) plus a `last_updated` field (date only, e.g. "6/25"). `position=FLX` returns empty for every analyst (unsupported) — FLX is built locally by merging RB/WR/TE and re-sorting by overall rank. For a precise update **time** (not just date), scrape the expert directory embedded in `fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php` (JS variable `expert_data`) and look up the expert by id — gives e.g. "06/25 10:43 AM ET". **Boone has no real PPR/STD** (his endpoint returns an empty list for those scorings) — those are synthesized, see the PPR/Standard section below. | **Built** — `fetch_fantasypros_rankings.py` (`--expert boone`, default), writes `boone_ovr.csv`/`_qb`/`_rb`/`_wr`/`_te`/`_flx.csv` x3 formats (PPR/STD synthesized) |
| Jeff Ratcliffe, and other FTN analysts on request (e.g. Tyler Orginski) — only published on FTN for now | `ls.ftnfantasy.com/api/rankings/redraft` — same login as FTN projections (`ftn_auth.py`, copied here from `ff_draft_proj`; `FTN_EMAIL`/`FTN_PASSWORD` in a local `.env`, see `.env.example`). Found by reading `tools.ftnfantasy.com/rankings.js`, the JS bundle behind `ftnfantasy.com/fantasy/nfl/rankings?type=redraft` — it calls `${ls.ftnfantasy.com}/api/rankings/redraft`. One request returns every scoring format and position at once: `{"PPR":[...], "Half":[...], "Std":[...], "SF":[...], "timestamps":{...}}` — **these are genuinely separate real submissions per analyst**, not derived (confirmed: Ratcliffe's real Saquon Barkley RB rank is 14/24/11 across Half/PPR/Std). Each player has a `rankings` dict keyed by analyst **last name** (`Ratcliffe`, `Orginski`, `Popielarz`, `Loechner`, `Sousa`) — `--analyst` selects which one. `Loechner` had a blank timestamp across every ranking set as of 2026-06 — listed but not actually active, don't use. `timestamps["Redraft Half"][<analyst>]` gives a precise last-updated datetime — much more precise than FantasyPros' date-only field. OVR = the per-format list (already cross-position ranked) filtered to players the analyst ranked; QB/RB/WR/TE = that filtered by position then renumbered 1..N (FTN has no separate per-position list); FLX = RB+WR+TE filtered from OVR then renumbered. | **Built** — `fetch_ftn_rankings.py --analyst <Ratcliffe\|Orginski>` (Ratcliffe is the default), writes `<analyst>_ovr.csv`/`_qb`/`_rb`/`_wr`/`_te`/`_flx.csv` x3 real formats from one fetch |
| Draft Sharks (`draftsharks.com/rankings/half-ppr`) | **No login needed** — unlike Draft Sharks' *projections* view (`ff_draft_proj/fetch_draftsharks_projections.py`, which does require a session), the *rankings* view's htmx endpoint (`GET /rankings/load-table?pprSuperflexSlug=<half-ppr\|ppr\|"">&fantasyPosition=<...>&researchDepth=rankings&playerGroup=all`) is publicly reachable logged out. `pprSuperflexSlug=""` (empty) is genuinely Standard scoring, not a fallback to half — confirmed by checking real movement (Derrick Henry rises, Christian McCaffrey falls vs. half-PPR, the correct direction). `fantasyPosition=""` (empty) gives the cross-positional overall rank (includes DST/K/IDP rows, filtered out to keep QB/RB/WR/TE); `fantasyPosition=FLEX` (not `FLX`) gives a cross-positional RB/WR/TE-only rank — both confirmed by reading the literal button values in the rankings page's own Alpine.js markup. Each player is a `<tbody data-player-row ... data-fantasy-position="RB" data-player-name="..." data-team-id="...">` block; rank is the first `<span>N</span>` inside it; team comes from the `<img src="/img/icons/teams/<ABBR>.svg">` badge. The page itself reports a clean ISO last-updated timestamp (`<time class="tool-page-header__last-updated-time" datetime="...">`). | **Built** — `fetch_draftsharks_rankings.py`, writes `draftsharks_ovr.csv`/`_qb`/`_rb`/`_wr`/`_te`/`_flx.csv` x3 real formats |
| Matthew Hill (DataForce Fantasy Football, via FantasyPros) | Same mechanism as Boone — FantasyPros expert id `552`, isolated via `filters=552`. Chosen as the 4th source over Sean Koerner (unavailable to us) and Dalton Del Don/Pat Fitzmaurice/Alfredo Brown (all considered) based on the multi-year draft-accuracy leaderboard described above — best sustained 2021-2024 average (rank 18 of 132) of anyone available to us. **Unlike Boone, Hill has real separate PPR/STD rankings** on FantasyPros. | **Built** — `fetch_fantasypros_rankings.py --expert hill`, writes `hill_ovr.csv`/`_qb`/`_rb`/`_wr`/`_te`/`_flx.csv` x3 real formats |

## Consensus
`build_consensus.py` blends the 4 sources into `consensus_<slot>.csv` for
each of OVR/QB/RB/WR/TE/FLX. Players are matched across sources by a
normalized name (`name_match.py`, ported from
`ff_draft_proj/build_consensus.py`, extended with a few extra team-code
aliases FTN uses — ARZ/BLT/HST/INA).

**Gap filling for players missing from a source.** A flat average over only
the sources that ranked a player would reward thin coverage too much (a
deep sleeper ranked by just 1 of 4 sources would get an artificially good
average). Instead each source's list is first extended to cover every
player appearing in ANY source, with missing players appended at the bottom
continuing from that source's own last rank (so a source with a shallower
list gets gaps starting at its own N+1, not some shared arbitrary number).
The 4 sources have a priority order (Ratcliffe, Hill, Boone, Draft Sharks)
used only to build one canonical "union" player order so the gap-filling is
deterministic — see the full algorithm description in the
`build_consensus.py` module docstring, verified against a small synthetic
test before being trusted on real data. The consensus rank is the average of
the 4 extended (real-or-continuation) ranks, re-ranked 1..N. The output CSV
shows each player's REAL reported rank per source (blank if that source
didn't rank them) plus a `Sources` count — the continuation ranks are only
used internally for the averaging, never shown.

**OVR includes K/DST**, even though Draft Sharks' OVR view doesn't rank
them (its `fantasyPosition=""` query only returns QB/RB/WR/TE — it has no
combined K/DST/skill overall board) — this is a deliberate choice, not a
bug: Draft Sharks is simply treated as a source that didn't rank that
player, same as any other missing-from-a-source case, and gets a
gap-filled continuation rank like normal.

## PPR / Standard versions
**Important finding: 3 of the 4 sources actually publish genuinely separate
PPR/STD rankings, not just half-PPR.** This was discovered by directly
querying each source with its PPR/STD scoring param and checking for real,
distinct movement (not the same list repeated):
- Ratcliffe/Orginski (FTN): the one API response already contains separate
  `Half`/`PPR`/`Std` lists per analyst — confirmed distinct (e.g. Ratcliffe's
  real Saquon Barkley RB rank is 14/24/11 across Half/PPR/Std).
- Hill (FantasyPros): `scoring=PPR`/`STD` on the same endpoint returns real,
  different rankings for him.
- Draft Sharks: `pprSuperflexSlug=""` (empty, = Standard) and `="ppr"` each
  return genuinely different boards — confirmed by checking real movement
  (Derrick Henry rises and Christian McCaffrey falls going from half to
  Standard, the correct direction for a low-target/high-target split).
- **Boone (FantasyPros) is the one exception** — `scoring=PPR`/`STD` with
  `filters=317` returns an EMPTY player list. He evidently only submits
  half-PPR rankings to FantasyPros.

So each fetcher now pulls all 3 real formats directly where possible
(`fetch_ftn_rankings.py`, `fetch_fantasypros_rankings.py` for Hill,
`fetch_draftsharks_rankings.py`), writing `<source>_<slot>.csv` (half),
`_ppr.csv`, `_std.csv`. Only for Boone does `fetch_fantasypros_rankings.py`
fall back to **synthesizing** PPR/STD from his real half-PPR list, via
`scoring_adjust.py`, using real reception totals from `ff_draft_proj`'s
projections (`consensus_rb.csv`/`consensus_wr.csv`/`consensus_te.csv`,
matched by the same normalized-name logic).

`scoring_adjust.py`'s method: keep the input half-PPR order as the
backbone (it reflects real analyst judgment a stat-line projection alone
won't capture). For each RB/WR/TE with a projections match, the points
swing from changing the per-reception value (PPR: +0.5/rec, STD: -0.5/rec)
is converted into a rank-value shift using the LOCAL points-vs-rank
relationship for that position (a flat global rate would be wrong — the
points gap between rank 1 and 2 is much bigger than between rank 80 and
81), via a windowed linear regression (5 neighbors each side). **Critically,
the shift uses each player's delta RELATIVE to their window-neighbors'
average delta, not their own delta in isolation** — every player's points
shift when the format changes, so what should move a player's rank is
whether they gain/lose more or less than their neighbors. An earlier
version used the raw per-player delta with no neighbor baseline, which
moved players the WRONG direction (a low-target RB incorrectly fell in STD
instead of rising) — caught by spot-checking Boone's synthesized Saquon
Barkley movement against Ratcliffe's and Draft Sharks' REAL Standard
rankings, which both showed him improving slightly, not worsening. Players
without a projections match are left unadjusted, not dropped; players never
added if not already in the input list. QB/K/DST are never adjusted (~0
receptions) but still take part in the OVR/FLX re-sort.

`build_consensus.py` blends each format independently from that format's
own per-source files (Boone's synthesized files are indistinguishable from
"real" ones to the blending logic) — it no longer adjusts the blended
half-PPR consensus directly; that over-corrected, since it applied the
reception math even to sources whose real PPR/STD submissions already
reflect their own judgment about how much receptions should matter.

One run of `build_consensus.py` writes all 3 formats per slot:
`consensus_<slot>.csv` (half-PPR), `consensus_<slot>_ppr.csv`,
`consensus_<slot>_std.csv`.

## Combined exports
- `export_combined.py` — one file per scoring format
  (`rankings_half.csv`/`_ppr.csv`/`_std.csv`) with all 6 slots
  (OVR/QB/RB/WR/TE/FLX) as side-by-side column blocks separated by a blank
  spacer column — same idea as separate spreadsheet tabs, just in one CSV.
  Each block keeps every column from that slot's consensus file (so all 4
  per-source ranks are still visible, not just the blended one); the first
  column of each block is renamed `<Slot> Rank` (e.g. "Ovr Rank", "QB
  Rank") instead of the generic "Rank".
- `export_for_upload.py` — one simple file per scoring format
  (`upload_half.csv`/`_ppr.csv`/`_std.csv`), OVR only, stripped down to
  just `Rank,Player,Team,Position` — for manually pasting into FantasyPros'
  expert-portal import tool (`experts.fantasypros.com/nfl/ranker/
  draft-half-ppr/all/import/`). **Scripted upload was investigated and
  ruled out**: the import page's session appears to be IP-bound and/or
  behind bot-fingerprinting (identical cookies that work fine in a real
  browser get redirected to a "noexpert" error from a script, even with
  every header replicated) — pushing further into spoofing TLS/HTTP2
  fingerprints to get around that crosses from "use my own login" into
  "evade a site's bot protections," so this step stays manual.

## Running the whole pipeline
`run_all.py` runs every fetcher, `build_consensus.py`, and both combined
exports in one command:
```
python run_all.py
```

## In-season weekly rankings (separate path, does not touch the season-long files)
Verified against the live API and pages on 2026-09-02:

- **`type=WEEK` works fully per expert** — QB/RB/WR/TE/**FLX**/K/DST all
  return real single-analyst lists (2025 wk10 Koerner: 28/91/139/87/317/27/28).
  Unlike the preseason path, **`position=FLX` is native for weekly** and does
  NOT need deriving from OVR. There is **no OVR/overall list in weekly** —
  positions plus FLEX only, which is also all the FP portal accepts.
- **All 9 expert IDs in `run_all.py`'s priority list submit weekly rankings** —
  checked 2025 weeks 5/10/15, every ID returned 180-364 players every week.
  The season-long priority list carries over to weekly unchanged.
- **The API is genuinely week-scoped and does not fall back.** Player counts
  differ per week, and an expert who hasn't submitted for a week returns an
  EMPTY list (2026 wk1 Koerner = 0 players) rather than last week's board. So
  "no data" is distinguishable from "stale data".
- **QB/K/DST are byte-identical across HALF/PPR/STD** (verified on Koerner's
  2025 wk10 boards: 0 positions differ). RB/TE/FLX genuinely differ (67/50/292
  positions move between HALF and STD), and Joe submits QB once.
- **What gets published, and when.** The pre-lock run covers
  **FLX/QB/RB/WR/TE** in Joe's paste order (`SLATE_SLOT_ORDER`): **5 lists per
  scoring format, 13 across all three** (QB format-invariant, submitted once).
  Half-PPR alone is 5 lists, which is what has to fit between a 12:55 run and a
  1 PM lock. **K and DST are published from a DIFFERENT analyst pool** and only
  refreshed a couple of times a week -- they are deliberately outside the
  pre-lock path, are not freshness-gated, and `OCCASIONAL_SOURCE_PRIORITY` is
  intentionally empty until Joe names those analysts, so nothing can silently
  blend the skill-position sources into a kicker board.
- **Freshness signal.** The partner API's `last_updated` is date-only
  ("11/09") and useless for a same-morning gate. Every weekly rankings page
  instead embeds `var expertGroupsData`, whose `expert_data[]` entries carry
  `last_updated` as a **unix epoch** — exact, and scoped to that one
  (week, position, scoring) list. The same pages embed `var ecrData` with
  `year`/`week`/`position_id`/`scoring`, so a page self-identifies which list
  it is (and what the current NFL week is) rather than it being assumed.
  Two limits on the epoch, both real: it records the last **save**, so an
  expert who reviewed after inactives and changed nothing is indistinguishable
  from one who never looked; and 11:30 AM ET inactives cover the 1 PM slate
  only, so a full-slate FLX list can never be entirely post-inactives before a
  1 PM publish.
- **Page map** (one page per distinct list, all confirmed `weekly` type):
  `qb.php`, `k.php`, `dst.php` (Standard-only pages, format-invariant lists);
  `half-point-ppr-{rb,wr,te,flex}.php` (HALF); `ppr-{rb,wr,te,flex}.php` (PPR);
  `{rb,wr,te,flex}.php` (STD).
- **Timing.** Measured 1.43 s/request against the partner API. The full weekly
  matrix is 189 requests (7 slots x 3 scorings x 9 expert IDs) = **~4.5 min
  sequentially, but 33 s with 12 concurrent workers**. The weekly fetcher must
  be concurrent; the existing sequential fetchers cannot hit a 12:50 PM ET run.
- **Freshness tiers** (`weekly_freshness.py`): FRESH = saved today at/after the
  cutoff (default 11:30 AM ET, deliberately provisional); SAME_DAY = saved
  earlier today, i.e. real weekly rankings but blind to inactives; STALE =
  saved before today, which in-season means last week's board.
- **`sample_weekly_freshness.py` / `analyze_weekly_freshness.py`** — the Sunday
  sampler and its analyzer. The sampler appends stateless JSONL snapshots (one
  file per sample, nothing read back, so retries can't corrupt earlier data) of
  every panel expert's epoch across all 15 lists. The analyzer derives update
  events, a "who saves latest" leaderboard, and a **cutoff sweep** showing how
  many sources survive each candidate cutoff — that sweep is what sets the real
  threshold, replacing the provisional 11:30. Driven by
  `.github/workflows/sample_weekly_freshness.yml`.
- **Open question for week 1:** as of 2026-09-02 the weekly panel held only
  22-24 experts (vs 168 on the draft page) and **none of the 7 sources appeared
  in it yet**, because `expert_data` lists panel members with their last save
  and none had submitted week 1. All 7 submitted throughout 2025, so they
  should appear once they post -- but confirm they do, since the epoch gate
  reads panel membership.

## In-season source pool and slate timing
Joe's source pool, best first (`SOURCE_PRIORITY` in `weekly_freshness.py`).
Every id verified 2026-09-02 as returning a real single-expert weekly list
(`total_experts=1`) for 2025 week 10:

| # | Source | FP id | 2025 wk10 FLX depth (H/P/S) |
|---|---|---|---|
| 1 | Justin Boone | 317 | 150 / 152 / **0** |
| 2 | Patrick Thorman | 534 | 318 / 317 / 317 |
| 3 | Jeff Ratcliffe | 125 | 305 / 304 / 304 |
| 4 | Sean Koerner | 120 | 317 / 316 / 316 |
| 5 | Tyler Orginski | 2729 | 145 / 145 / 145 |
| 6 | Nathan Jahnke | 540 | 249 / 249 / 249 |
| 7 | Dalton Del Don | 285 | 206 / 206 / 206 |

Two things to know about this pool:
- **Boone submits no Standard weekly board** (0 players for STD, same as his
  draft rankings). His STD would have to be synthesized via `scoring_adjust.py`
  or he drops out of the STD blend.
- **Boone (150) and Tyler O (145) run shallow** versus Thorman/Koerner/Ratcliffe
  (~305-318). Shallow lists take more gap-fill continuation ranks, so their
  distinctive calls get compressed toward the middle more than a deep list's
  would -- worth remembering given Boone is the #1 priority source.
- As of 2026-09-02, **Thorman, Ratcliffe, Tyler O and Jahnke were on no FP panel
  page at all** (draft or weekly) while still returning real API data. The epoch
  gate reads panel membership, so those four would yield no freshness signal.
  That is why `fingerprint_expert_list` exists -- see below.

**FLX is pulled natively -- nothing here builds it.** For weekly,
`position=FLX` returns a real ~300-player cross-position board per analyst, so
FLX is fetched like any other slot. (Only the *preseason* path has to derive it,
because there `position=FLX` comes back empty.)

**FLX and the position lists are two views of one board, and FP enforces it.**
Verified on 2025 week 12: for 6 of the 7 sources the FLX list contains exactly
the same player set as RB+WR+TE, and for all 7 the FLX ordering has **zero
inversions** against the position lists. That zero is not analyst consistency --
**FP enforces it**: submitting a position list slightly reorders the flex to
agree with it on within-position order. (Boone is the set-equality exception
only because his FLX is a deliberately truncated strict subset, 155 of his 306
ranked skill players.)

Joe therefore pastes **FLX first, then QB, RB, WR, TE** (`PASTE_SLOT_ORDER`), so
the published flex is cross-position interleaving from the FLX paste plus
within-position order from the position pastes. FLX is NOT redundant -- it is
what supplies the cross-position interleaving, which no position list contains.

**This breaks independent per-slot blending, and the fix is `reconcile_flex`.**
`build_consensus.py` blends each slot separately, over its own player universe
with its own gap-fill continuation ranks. Measured on 2025 week 12 with the top
4 sources, that produced **65 disagreements** between the blended flex and the
blended RB/WR/TE lists (and the two universes even differed in size, 319 flex
members vs a 321-player position union). Left alone, FP would silently resolve
all 65 by paste order, so the published flex would be a hybrid nobody designed
and would not match the exported CSV.

`reconcile_flex(flex_names, position_lists)` is therefore NOT a construction
step -- it is a truthfulness step. It pre-applies exactly what FP does:
it keeps the flex's cross-position interleaving and fills those slots in the
order the position lists give. It is a **strict permutation** -- verified on the
real week-12 data to take 65 inversions to 0, preserve the interleaving pattern
exactly, add or drop nobody, and change the occupant of 141 of 319 ranks (the
scale of what FP would otherwise have done behind Joe's back). A flex member
that appears in no position list keeps its own slot, since it has no ordering
constraint. Run it before writing the paste files. Note the benefit is
predictability, not better rankings -- FP resolves the conflict either way. The
gain is that the exported CSV describes the published board (so QA on it means
something) and that a partial paste session, cut short at 12:58, still leaves a
coherent board rather than one half-reconciled against lists never submitted.

**Boone and Standard.** Boone submits no STD board at all (0 players for every
STD list, 2025 weeks 10 and 12). The STD slot goes to the next priority source
instead of synthesizing one from his half-PPR, because: the weekly path would
need weekly reception projections to run `scoring_adjust.py` (the preseason
version leans on `ff_draft_proj` season-long numbers, which don't exist per-week
here), that dependency would sit on the tightest clock of the week, and a real
STD board from Thorman/Ratcliffe/Koerner is worth more than a modelled guess at
what the #1 source would have said. `sources_for("STD")` drops him, so STD
blends Thorman/Ratcliffe/Koerner/Orginski.

**Two sources are also on FTN.** Ratcliffe and Tyler Orginski are both in
`fetch_ftn_rankings.py`'s analyst set, and FTN publishes a precise submission
datetime in its `timestamps` block rather than requiring FP to list the expert
in its panel. For those two, prefer FTN's timestamp over the FP epoch -- it is
the better signal and it is immune to the panel-absence problem entirely.

`MAX_SOURCES = 4`, and the pool is deliberately larger: the run takes the
highest-priority sources that are actually FRESH for a given list, so sources
5-7 are depth against a slow slate, not extra blend members.

**Why 4 and not 6.** More sources cuts independent error (roughly 1/sqrt(N))
and FP's own consensus beats most individual experts -- so on pure accuracy,
6 > 4. But the goal here is placing well on FP's expert accuracy leaderboard,
and you cannot beat the consensus by *becoming* it: a 6-source blend of
mainstream analysts converges toward ECR and lands mid-pack. These analysts are
also highly correlated (same beat reports, same injury news), so the marginal
variance reduction from sources 5 and 6 is small while the dilution of any real
edge is not. The gap-fill mechanism makes this concrete: a player ranked by only
one source gets N-1 continuation ranks pulling them to the middle, so going 4 ->
6 measurably compresses exactly the non-consensus calls that would differentiate
the submission. The better lever against middle-of-the-road output is
**priority weighting** within the 4, not adding a 5th and 6th. Settle it
empirically once FP has graded a few weeks: publish the 4-source blend, log a
6-source blend alongside it, compare after 4-6 weeks.

**Freshness policy: one threshold that moves through the week**
(`freshness_threshold()` in `weekly_freshness.py`). A source counts only if it
saved that list at/after the threshold. The threshold is derived from a real
moment -- a kickoff or a lock -- not a bare clock time:

| When | Phase | Threshold |
|---|---|---|
| Tue -> Thu 6 PM | EARLY WEEK | **none** -- nothing has kicked off, an old board is still this week's board |
| Thu 6 PM -> 8:15 PM | TNF LOCK | Thursday 6:00 PM |
| Thu 8:15 PM -> Sun 12:30 PM | POST-TNF | Thursday's kickoff -- a board predating TNF hasn't seen Thursday's games |
| Sun 12:30 PM on | SUNDAY LOCK | Sunday 12:30 PM |

Deriving it from a moment also removes a trap: a fixed "12:30 PM" cutoff
evaluated at 10 AM Sunday can never be satisfied, so every source fails and the
run looks broken. Here the strict window simply hasn't begun at 10 AM -- the
POST-TNF threshold applies instead. There is no slate to choose and nothing to
configure; `run_weekly.py` prints the phase and the reason on every run.

**FTN as the fallback for Ratcliffe and Orginski** (`ftn_weekly.py`). FTN's
rank-type dropdown maps to the URL path, so the redraft endpoint
`ls.ftnfantasy.com/api/rankings/redraft` becomes `.../weekly`. Same login
(`ftn_auth.py`). Verified 2026-09-07.

The weekly payload is shaped differently from redraft, which is the thing to
watch: the scoring keys (`Half`/`PPR`/`Std`) hold the **FLEX** board (RB/WR/TE,
~348 players) and `QB`/`K`/`DST` are separate lists. There are no per-position
RB/WR/TE lists, so those are filtered out of the flex board and renumbered --
which has a happy side effect: a flex derived that way agrees with its own
position lists by construction.

FTN is worth more than a backup for these two. Its `timestamps` block gives a
precise per-analyst submission datetime ("9/7/2026 15:36:02"), while FP exposes
a timestamp only for experts in its own panel -- and neither Ratcliffe nor
Orginski appears on any FP panel page. So for them FTN is both the more reliable
source and the only precise freshness signal. `run_weekly.py` tries FP first and
falls back to FTN per (slot, scoring); a dead FTN login degrades to FP-only with
a warning rather than failing the run. Note FTN ranks a few fullbacks, mapped
FB -> RB since FP has no FB slot.

**Jahnke / PFF -- works, via Joe's own logged-in Chrome.** There is no
scriptable route (investigated 2026-09-07: the article and the
`/fantasy/rankings/weekly` tool are both PFF+ premium, the tool is a Next.js app
on `beta.pff.com` that calls no data endpoint at all when logged out, and the
login is a React form with a csrf token). But with the Claude-in-Chrome
extension connected and Joe logged in, the tool exports exactly what is needed.

What the tool gives, better than the article did:
- **All three scoring formats.** The scoring control offers PPR / **Half PPR** /
  NON-PPR. The article was PPR-only, so this is what makes Jahnke usable in
  Joe's priority format.
- **A published timestamp** in the page text: "Updated - Sep 06, 2026 8:28pm
  EDT" -- feed that to `--published-at`.
- Position tabs QB / RB / WR / TE / **FL** / SFL / K / DST. FL is the flex.

Capture procedure, and the traps in it:
1. Set the scoring control to Half PPR, then select a position tab.
2. Click **CSV**. It exports **only the currently selected position**, so this
   is five exports (FL, QB, RB, WR, TE), not one.
3. **The CSV click must be a real click.** A programmatic `element.click()` from
   injected JS switches tabs fine but does NOT trigger the download -- Chrome
   requires a genuine user gesture. Use the computer tool's click on the
   button's ref.
4. **Do not install a click/blob interceptor to read the CSV in memory.** An
   override of `HTMLAnchorElement.prototype.click` that swallows anchors with a
   `download` attribute suppresses the download entirely -- it looks like the
   export is broken when it is the interceptor doing it.
5. **Move it out of Downloads immediately**, rather than leaving it there and
   importing from `~/Downloads` directly (the original approach, which left
   Joe's actual Downloads folder collecting `Week-1-rankings-export (11).csv`,
   `(12).csv`, ... forever -- Joe asked 2026-09-11 to stop that). Run:
   `python capture_pff_export.py --slot <SLOT> --scoring <HALF|PPR|STD|ANY>`
   -- it grabs the newest `*rankings-export*.csv` in Downloads, refuses it if
   older than 120s (the click probably silently failed -- see trap 3 below and
   the coordinate-drift note further down), and moves+renames it to
   `weekly/<year>-wk<NN>/pff_raw/<SLOT>_<SCORING>.csv`, overwriting the
   previous capture at that same path rather than accumulating copies.
6. Import from that fixed path: `import_cached_board.py
   weekly/<year>-wk<NN>/pff_raw/<SLOT>_<SCORING>.csv --prefix jahnke --source
   "Nathan Jahnke" --origin PFF --slot <SLOT> --scoring <FMT> --published-at ...`
7. Repeat for all three scoring formats. Jahnke publishes genuinely different
   boards per format -- his FLX export hashes differently in Half / PPR /
   NON-PPR -- so a full capture is **13 exports**: FLX/RB/WR/TE x 3 formats,
   plus QB once. QB is format-invariant on PFF too (identical MD5 across all
   three exports, verified 2026-09-07), so it only needs capturing once and is
   stored under "ANY" -- capture it as `--scoring ANY`.

**A third trap: element refs go stale.** The CSV button's `ref_N` from `find`
stops working after React re-renders on a position-tab switch -- the clicks
report success and silently download nothing. Click by **coordinate** instead
(the button sits on the same row as the position pills), and verify after each
export by diffing the Downloads folder against a recorded baseline rather than
trusting the click.

The export's schema is `Overall Rank, Full Name, Team Abbreviation, Position,
Position Rank, Bye Week, Injury Status`, after a title line and a blank line --
so `import_cached_board.py` scans for the header row rather than assuming line
1, and parses by column name (`parse_csv`) instead of fuzzy-matching a known
schema. The rendered table only shows abbreviated names ("L. Jackson"), which is
why the CSV matters: initial-plus-surname collides badly across a 300-player
board.

Verified 2026 week 1: FL 250 = RB 85 + WR 115 + TE 50, and 246 of Jahnke's 250
flex players matched another source by name, with the 4 unmatched being genuine
deep-bench calls (ranks 190-249, no near-duplicates) rather than mismatches.

**Cache timestamps are now per scoring format, not one for the whole
file** -- the exact gap flagged right after Thursday's first Jahnke capture,
confirmed live and fixed 2026-09-11 once it actually bit. Refreshing only
Jahnke's HALF boards through the browser had stamped that capture's time onto
his untouched PPR/STD boards too, making six-day-old content look freshly
current in `run_weekly.py`'s comparison against FP -- Joe noticed the run
"seemed to have gotten the std and ppr rankings really fast from PFF," which
was the tell: nothing fetched PPR/STD at all, the timestamp just lied.

`cached_source.py`'s schema now mirrors `boards` exactly: `timestamps` is
`{scoring_or_ANY: {published_at, captured_at}}`, one entry per key, same keys
as `boards`. `board_for(payload, slot, scoring)` replaces the old separate
`rows()` + `timestamp()` calls with one that returns both together, guaranteed
from the SAME key -- a format's freshness can no longer be reported using a
different format's capture time, structurally, not by convention.
`import_cached_board.py` merges only the ONE key being imported, leaving every
other format's stored timestamp untouched. The live cache file was corrected
by hand once, restoring PPR/STD to their true original capture
("2026-09-06T20:28:00-04:00", recovered from an earlier verified read in this
session) since a file-wide timestamp that already got overwritten can't be
un-overwritten -- only prevented from happening again, which is what this
fixes going forward.

**Keeping Jahnke's cache fresh -- not a background task, folded into the ask.**
Tried a `mcp__scheduled-tasks` recurring job (every 2h, browser-driven, with the
same 12h/newer-timestamp rule and the 15-min lock-proximity guard from
`capture_window_ok()`) on 2026-09-11. Joe killed it the same day: "I want the
refresh logic built into the normal update rankings script." That can't be
literal -- `run_weekly.py` is a plain script with no path to a browser, and
Claude-in-Chrome is only ever reachable as a tool call, not from a subprocess.
What it actually means in practice: whenever Joe asks for the weekly update to
run, check Jahnke's cache staleness FIRST and do the PFF browser capture myself,
before running `run_weekly.py`, so it reads as one ask even though the browser
step happens in conversation rather than inside the script.

`cached_source.staleness(payload, max_age_hours=12.0)` returns
`{scoring_key: (age_hours, is_stale)}` from the same timestamps already used for
gating -- age-only, since knowing whether PFF has posted something *newer*
needs a live look, not just a clock. `run_weekly.py` prints this for every
cached source right where it already lists cached boards, so a plain manual run
still surfaces "STALE (>12h...)" instead of quietly excluding Jahnke with no
explanation. But printing is the fallback for when Joe runs it directly --
when *I'm* the one running it, the actual habit is: check staleness (or just
ask "has PFF likely posted since <last capture time>?"), and if any format
looks stale, run the PFF capture (see above) before `run_weekly.py`, subject
always to `capture_window_ok()` -- never start a capture inside 15 minutes of
a lock, same rule as the old scheduled task -- standing authorization for this
capture (2026-09-07, updated 2026-09-11) now explicitly covers this
folded-into-the-ask flow, not just an interactive ask each time.

**Cached sources** (`cached_source.py`). Any board obtained by hand -- Jahnke
today, Thorman when a route exists -- can feed the blend as a third origin after
FP and FTN, and faces exactly the same freshness gate. One JSON per source per
week under `weekly/<year>-wk<NN>/cached/<prefix>.json`.

Boards are keyed **by scoring first**, then slot: `{"boards": {"HALF": {...},
"PPR": {...}, "STD": {...}, "ANY": {"QB": [...]}}}`. That shape is deliberate --
it makes serving a PPR board as Standard structurally impossible rather than
something a scoring check has to catch. "ANY" holds the format-invariant slots.
The older flat `{scoring, lists}` shape still loads, via `_migrate`.

Freshness uses `published_at` when present (when the analyst posted) and
`captured_at` otherwise (when it was read) -- never the file mtime, since
copying or OneDrive-syncing a file must not make a stale board look fresh.

**Per-slot source sets are real.** Because freshness is gated per
(slot, scoring), one run can blend Ratcliffe+Orginski into RB and
Ratcliffe+Orginski+Jahnke into FLX. Every consumer must therefore take a
*per-slot* priority list -- `write_workbook` originally took one shared list and
raised KeyError the first time a cached source covered FLX but not RB.

**Boone and Koerner have no alternative source at all**, by Joe's own account --
if FP is stale for them they simply drop out and the next source steps up.

**Slate timing** (`SLATES` in `weekly_freshness.py`, all ET) -- retained for the
sampler, which still reasons in clock times; the pipeline uses the phase
thresholds above instead. `cutoff` is the
freshness line -- a source that hasn't re-saved a list at/after it is not
counted for that list. These are Joe's judgment calls, not a fixed offset from
kickoff (Thursday tolerates a 2h15m-old board; Sunday only 30m):

| Slate | Kickoff | Run at | Cutoff |
|---|---|---|---|
| THU | 8:15 PM | 8:10 PM | 6:00 PM |
| SUN | 1:00 PM | 12:55 PM | 12:30 PM |
| WED | 8:15 PM | 8:10 PM | 7:45 PM |
| FRI | 3:00 PM | 2:55 PM | 2:30 PM |

Wednesday/Friday one-offs are rare and low-stakes; those rows are placeholders
meant to be overridden per game with `--cutoff` rather than edited. `slate_for()`
infers the slate from the weekday and **refuses** rather than guessing on a day
with no configured slate, so a stray run can't silently borrow another slate's
cutoff.

**CDN caching can hide a last-second update, and every FP call is now cache-
busted.** Joe's concern (2026-09-09): rankings are static early in the week, but
in the minutes before a lock they genuinely change -- and that's exactly when a
stale read would hurt most. Verified live: FantasyPros' rankings pages and the
`consensus-rankings.php` API both sit behind CloudFront (`max-age=1200` / 20 min
on the API, `max-age=600` / 10 min on the pages), and an ordinary unbusted call
during quiet conditions came back `Age: 1186` -- 19+ minutes stale, near the
ceiling. Confirmed with a forced cache-bypass that the origin's actual value
matched the stale cache exactly (nothing had changed), so this wasn't visible
damage today -- but the mechanism means a request landing on an already-warm
cache entry during the real pre-lock window could return a board from up to 20
minutes ago, silently. That is backwards for a freshness gate whose whole job is
FRESH-vs-STALE to the minute: it would falsely reject a source that DID update
in time, purely because the read hit a stale cache rather than the origin.

Fixed at the two FP call sites in `weekly_freshness.py` (`fetch_list_freshness`,
`fetch_expert_list`) via `_bust()`, which appends a unique nonce so CloudFront
can never serve a cached hit -- every call is a guaranteed origin read. Applied
at the shared-module level, so every caller (the sampler, `run_weekly.py`, the
fingerprint fetcher) inherits it automatically. FTN carries no such caching
(checked 2026-09-09, no cache-control headers at all) and needs no fix.

**Switched the panel timestamp source to the official v2 API** (2026-09-09,
Joe's call after the CDN-caching finding above). `fetch_list_freshness` now
calls `/rankings/experts` on `api.fantasypros.com` first -- clean structured
JSON instead of brace-matching a JS blob out of a scraped page -- and falls
back to the old HTML scrape (renamed `_fetch_list_freshness_html`) if the key
is missing or the call fails for any reason, printing a WARNING rather than
taking the run down. Verified both paths live, including forcing the fallback.

Two things that had to be gotten exactly right before trusting it:
- **Confirmed it is genuinely (position, scoring)-specific**, not one
  timestamp reused across formats: Del Don's RB timestamp differs by a second
  between HALF/PPR/STD, and Boone -- who submits no Standard board -- is
  correctly absent when `scoring=STD` is requested.
- **The timestamps are UTC, not ET.** Confirmed by cross-checking against the
  already-verified Boone epoch from the HTML scrape: his known
  "2026-09-08 07:51:42" ET matched the API's "2026-09-08 11:51:42" to the
  second, the correct EDT offset. Parsed accordingly in `_parse_api_timestamp`
  rather than assumed to share the rest of this module's ET convention --
  getting that wrong would have silently shifted every freshness decision by
  4-5 hours, exactly the kind of error this system exists to prevent.

Coverage is unchanged: this API's panel is the same one the HTML page reads
from, so it still only covers Boone and Del Don of the 7-source pool. FTN and
`cached_source` remain necessary for Ratcliffe/Orginski/Jahnke/Thorman
regardless -- this swap improves the SIGNAL for the two sources it already
covered, it doesn't add coverage.

**429s from the official API under a --scoring all burst -- fixed with a
quick retry, not less concurrency.** Joe hit this live during a real Thursday
TNF run (2026-09-10): 2 of 13 concurrent freshness lookups came back
`429 Too Many Requests`. The fallback caught both and the run finished with
correct data (HTML scrape stood in for those 2 lists) -- not a failure, just
noisy. Reproduced directly: firing the same 13-way concurrent burst
(`ThreadPoolExecutor(max_workers=12)`, one call per requested slot/scoring,
exactly what `panel_epochs()` does for `--scoring all`) against
`/rankings/experts` reliably 429s a few of them. No `Retry-After` or
`X-RateLimit-*` header on the response -- the API gives no guidance on backoff
-- but a bare retry of an already-429'd request succeeded instantly, with no
wait at all. That's a burst/concurrency limit, not a slow quota, and it clears
itself fast.

Fixed in `_fetch_list_freshness_api`: up to 3 attempts, a short
`random.uniform(0.4, 0.9) * attempt` backoff between them (jittered so the 12
threads retrying together don't re-collide in the same instant), before
raising and letting the existing HTML-fallback take over. Verified by firing
the real 13-list burst 3 times after the fix: 13/13 hit the official API every
time, 0 fallbacks. Concurrency itself was left at 12 -- reducing it would slow
every run for a problem 2-3 quick retries already solves.

**Panel-independent freshness.** `fingerprint_expert_list` hashes an expert's
ordered rank+name list per (slot, scoring). Tier/min/max/std are deliberately
excluded from the hash: those are consensus-derived and move when OTHER experts
submit, which would report phantom updates. Comparing fingerprints across
samples proves a board changed even with no epoch to read. It is strictly weaker
than the epoch -- it can say "changed since I last looked", never "saved at
12:31" -- so it needs an earlier baseline sample from the same day to be useful.
`sample_weekly_freshness.py --fingerprint` collects it.

## Seeing freshness and hand-picking sources (weekly_status.py / --sources)
Built 2026-09-10, the night the strict gate left Joe with exactly one source
(Ratcliffe) for every TNF list -- correct behaviour, but a thin result Joe
wanted the option to override with his own judgment rather than either
accepting a 1-source board or blindly running `--gate off`.

**`weekly_status.py`** -- a fast, read-only glance: for every pool source, per
slot, the most recent known update time and its origin, with a `*` marking
anything that clears the current phase's cutoff. Timestamp-only (reuses
`fetch_list_freshness`/`ftn_weekly`/`cached_source`, never fetches full player
lists), so it's safe to run right before a decision without adding load.

One bug caught before it shipped: the first draft of `best_timestamp()`
stopped at FP's timestamp the moment FP had ANY value, even a stale one --
which hid Ratcliffe's much fresher FTN submission (Thu 6:14 PM vs FP's stale
Wed 8:18 PM) behind his own stale FP entry. Fixed to take the MOST RECENT of
whatever FP/FTN/cache signals exist, not the first one found -- this tool's
job is showing the best evidence per source for a human to judge, which is a
different question from `choose_sources()`'s fall-through order (which decides
who WINS a slot in the real run).

**Source selection: FP is checked first, on its own; a backup is only
skipped during a LOCK phase where FP already clears the bar** (`_fp_candidate`
/ `_backup_candidates` / `wf.is_lock_phase` in `run_weekly.py`, settled
2026-09-11 after three iterations). Final rule, in Joe's words: "When I'm
inside a freshness window and FP is inside that, then no, I do not need to
check the other source. If we are not inside a freshness window, then yes
check the backup source and pull the most current one." LOCK phases are TNF
LOCK, SUNDAY LOCK, and a manual `--cutoff` (CUSTOM) -- the narrow, live
pre-lock windows this whole project is built around. EARLY WEEK and POST-TNF
are NOT locks, so the backup is ALWAYS checked there and whichever of FP and
the backup is most recent wins, even when FP alone would already pass.
Sources with no backup (Boone, Thorman, Koerner, Del Don) are unaffected
either way -- `_backup_candidates` returns nothing for them.

Why POST-TNF specifically needed this: it can span 40+ hours (Thursday's
kickoff to Sunday's lock), and an FP board that passed the INSTANT the window
opened does not stay the freshest thing forever. Verified live 2026-09-11:
Ratcliffe's FP entry (Thu 8:34 PM, correctly inside POST-TNF's threshold at
the time) was still winning on Friday afternoon while his FTN submission had
moved to Fri 2:58 PM -- nearly a day fresher -- because nothing ever
re-checked it once FP had cleared the bar once.

**How it got here, three bugs deep:**
1. Original design: plain fall-through (FP, then FTN only if FP failed its
   accept check, then cache) for automatic runs; a separate always-compare
   path only for manual `--sources` picks. Bug: a manual pick's accept()
   was hard-wired to always succeed, so FP was accepted the instant it had
   ANY board, never even reaching FTN -- `--sources ratcliffe` returned a
   stale FP entry while FTN was current.
2. Fix, take one: unify into a single "always gather every origin, pick the
   freshest" path for every run, manual or not. This surfaced a plain
   `python run_weekly.py` (no flags) that had been silently doing the same
   thing FTN was supposed to prevent -- correct once fixed, verified against
   `weekly_status.py`'s independent answer.
3. Joe's follow-up: comparing FP against a backup on EVERY run, even when FP
   already clearly passes, is more checking than he wants. Restructured so
   ANY time FP passed the threshold, the backup was skipped -- but this
   over-corrected: it stopped checking backups in EVERY phase, including the
   long POST-TNF window, which is the Ratcliffe gap above. Fixing it also
   exposed a bug in `--gate off`'s plumbing: gate off was nulling `threshold`
   to force auto-accept, but `tier_since(epoch, None)` returns FRESH
   unconditionally by design (meant for the genuine no-window EARLY WEEK
   case) -- so under gate off, FP's freshness check always vacuously
   "passed" and the backup was never queried, silently reverting `--gate
   off` to a stale FP pick. Fixed by leaving the real threshold flowing
   through always; `gate == "off"` does its actual job (bypass accept/
   reject) at the one place that checks it.
4. Final fix: replaced the blanket "FP passed -> skip backup" rule with the
   lock-phase-scoped one described above. Verified with a controlled
   synthetic test (fixed timestamps, only the phase changed): under TNF LOCK
   a fresh-but-not-freshest FP entry correctly wins over an even fresher
   FTN one (backup never checked); under POST-TNF, same timestamps, FTN
   correctly wins (backup checked and found better). Also verified all of
   plain/`--sources ratcliffe`/`--gate off` resolve identically to
   `weekly_status.py`'s independent answer under the live POST-TNF state.

**Console output now shows a comparison actually happened, not just the
winner** -- prompted by Joe seeing `Jahnke 1.0x [FP Thu 8:31 PM]` and asking
"it didn't check PFF, did it?" It had (`_backup_candidates` had genuinely
found and compared his cached PFF board), but the printed line looked
identical either way. Now, whenever a backup was actually gathered and lost,
the line says so: `Jahnke 1.0x [FP Thu 8:31 PM] beat PFF Thu 5:48 PM`. Sources
with no backup print exactly as before, with nothing appended. Also carried
into `manifest.json`'s `gating[...].used[].considered`.

**`run_weekly.py --sources <prefix,prefix,...>`** -- restricts the pool to
exactly the named sources (their usual priority order still decides which 2
get the 1.5x weight) and additionally waives the freshness threshold for
them (the origin-selection logic above is identical either way -- this only
changes whether the winning candidate has to be FRESH to be accepted). Does
not waive the "does this source have a board at all" check. Capped at
`MAX_SOURCES`; naming more prints a warning showing which ones (highest
priority first) will actually be used. The freshness tag shown in
output/CSV/viewer stays the REAL one (e.g. "Thu 3:01 PM", not relabeled
FRESH) so a manual call is visibly a manual call.

## Conventions / ground rules
- Send a normal `User-Agent`. Fetch and cache — don't hammer endpoints.
  Personal use of my own/public data.
- Keep credentials out of the code — local `.env`, gitignored at the repo
  root (never `.env.example`, which IS committed as a template). FTN needs
  `FTN_EMAIL`/`FTN_PASSWORD`; FantasyPros' partner API is unauthenticated.
- Output one CSV per source per position (e.g. `boone_qb.csv`,
  `ratcliffe_qb.csv`), plus a combined/consensus CSV once there's more than
  one source per slot.
- These endpoints can lag, especially for weekly/in-season pulls — always
  check the precise last-updated timestamp each fetcher prints before
  trusting a pull is current.

## Status / next steps
1. `fetch_fantasypros_rankings.py` — **done**. Pulls Justin Boone's personal
   rankings (FantasyPros expert id 317, isolated via `filters=317`) for
   OVR/QB/RB/WR/TE (FLX derived locally) to `boone_*.csv`. Prints
   `total_experts` (should be 1 for an isolated single-expert pull),
   `last_updated` (date only), and a precise last-updated date+time scraped
   from the public rankings page. Supports `--expert-id` for other analysts,
   and `--scoring`/`--type`/`--year`/`--week` to adjust the query (e.g.
   `--week 4 --type WEEK` once in-season weekly rankings are needed).
2. `fetch_ftn_rankings.py` — **done**. Pulls an FTN analyst's personal
   half-PPR rankings (default Ratcliffe; `--analyst Orginski` available too)
   for OVR/QB/RB/WR/TE (FLX derived locally) to `<analyst>_*.csv`. Prints a
   precise last-updated datetime from FTN's `timestamps` block. `ftn_auth.py`
   is copied here from `ff_draft_proj` (same login flow/credentials).
3. `fetch_draftsharks_rankings.py` — **done**. Pulls Draft Sharks' half-PPR
   rankings (no login) for OVR/QB/RB/WR/TE/FLX (FLX from Draft Sharks'
   own `fantasyPosition=FLEX`, not derived locally) to `draftsharks_*.csv`.
   Prints the page's own ISO last-updated timestamp.
4. `fetch_fantasypros_rankings.py --expert hill` — **done**. Pulls Matthew
   Hill (FantasyPros expert id 552, isolated via `filters=552`), the chosen
   4th source — see the accuracy rationale above. Writes `hill_*.csv`.
5. `build_consensus.py` — **done**. Blends all 4 sources into
   `consensus_<slot>.csv`/`_ppr.csv`/`_std.csv` per OVR/QB/RB/WR/TE/FLX —
   see the Consensus and PPR/Standard sections above.
6. `scoring_adjust.py` — **done**. Derives PPR/STD from the half-PPR
   consensus using `ff_draft_proj`'s projected receptions — see above.
7. `run_all.py` — **done**. Runs every fetcher then `build_consensus.py` in
   one command.
8. Add more rankings sources if wanted (just add a row to `PRIORITY`/
   `SOURCE_FILES` in `build_consensus.py` once a new `fetch_*.py` exists,
   and a step to `run_all.py`).
