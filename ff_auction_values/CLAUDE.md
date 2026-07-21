# Fantasy Football Auction Values

## Goal
Sibling project to `ff_draft_proj` (consensus projections), `ff_rankings`
(consensus expert ranks), and `ff_cheatsheet` (personal ranks + the Excel
PAR/VBD engine). This project converts projected points into dollar-value
auction prices, intended as a standalone page on the site (paywalled),
separate from the Excel cheat sheet.

## Phased plan
1. **Done** — static table, one standard league shape, half-PPR only.
   Heavily calibrated against real market data; see the full history below.
2. **Budget: done. Team count: done (8/10/12/14/16 only). Roster shape:
   not started.** Starting Budget is live-editable in the live draft
   workbook's `Setup` sheet — see "Phase 2 begins" section below. Number
   of Teams is now also live-editable, restricted to a dropdown of the 5
   team counts with real calibration behind them — see "Live draft mode
   v1.3" below. Roster shape is still NOT exposed — `POSITION_BUDGET_SHARE`
   was tuned specifically for this project's roster spots, and changing
   roster shape would need its own recalibration effort, same reasoning
   as team count had before v1.3.
3. **Not started** — let users assign how much of their budget goes to
   each position; put the static table on the site.
4. **v1/v1.1/v1.2 built** — live draft mode: manager enters actual winning
   bids as players are drafted, remaining values recalculate live in Excel
   (`build_live_draft_workbook.py`). Done ahead of phases 2/3 per user
   request — see "Live draft mode" sections below. Still Excel-only, not
   yet on the site.

## v1 methodology (`build_auction_values.py`)
- **League shape**: 12 teams, $200 budget, 1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX
  (RB/WR/TE) / 1 DEF / 1 K + 6 bench = 15 roster spots/team. Chosen as the
  closest match to ESPN/FantasyPros defaults per user preference ("closer to
  ESPN/FP" over a higher custom budget).
- **Points source**: `ff_draft_proj`'s consensus half-PPR projections
  (`consensus_<pos>.csv`).
- **Personal-rank nudge**: pulls each player's points toward what their
  `ff_cheatsheet/joe_bond_half_ppr.csv` personal rank implies, using that
  position's own points-vs-rank curve (so a 1-rank move near the top of RB
  swings more points than a 1-rank move at RB40) — same idea as
  `ff_rankings/scoring_adjust.py`'s windowed rank-to-points conversion, just
  simpler (direct curve interpolation, no neighbor-relative windowing).
  Damped at `NUDGE_WEIGHT = 0.5` — a 50/50 blend of projections and personal
  rank, not a full override. Players in the projections but not in the
  personal-rank file are left unadjusted (not dropped).
- **Replacement level**: fixed per-position rank (`REPLACEMENT_RANK`),
  **not** a `teams × starters` formula. v1 used a "teams × starters + small
  buffer" heuristic (borrowed from `ff_cheatsheet/apply_par_v3.py`'s Q-score
  formula) and it produced badly inflated top-end values (RB1 at $91 of
  $200) — confirmed too shallow against Bryan Harstad's "A Better Way to
  Determine VBD Baselines" (footballguys.com/article/HarstadVBDBaselines),
  which analyzed real MFL league box scores and found replacement level runs
  much deeper than naive "teams × starters" math suggests, because byes and
  injuries force real rosters to start far more players over a season than
  a static roster count implies. His 12-team-league findings, now used
  directly: **QB ~19, RB ~34, WR ~54, TE ~21**. (v3's buffer convention is
  fine for its own purpose — a blended cross-positional rank *score* — but
  isn't the right tool for a literal dollar-value replacement line; don't
  reuse it here again.)
  - Sanity-checked against a second independent source (Matt Waldman's
    cap-allocation auction method, mattwaldmanrsp.com): #1 overall player at
    ~31% of budget → ~$62 of $200, which is within a dollar of this build's
    #1 player ($62). v1's shallow baseline had put the #1 player at $91 —
    clearly wrong by that same cross-check.
- **VORP**: `blended points - replacement points`, floored at 0.
- **Dollars**: discretionary-money VBD-to-$ formula, confirmed directly
  against the Footballguys forum thread the user originally pointed at
  ("Simple Formula For Value of Auction $ On the Fly" — the forum itself
  blocks scripted fetches, but the user pasted the actual formula text):
  - `total_money = teams × budget`
  - `discretionary = total_money - (roster_spots_per_team × teams × $1)`
  - Split `discretionary` across positions using `POSITION_BUDGET_SHARE`
    (see below) — **not** a single shared rate across all positions.
  - Within each position: `$/VORP-point = position_discretionary /
    sum(VORP over that position's positive-VORP players)`
  - `player $ = $1 + VORP × that position's $/VORP-point`
- **Position budget share** (`POSITION_BUDGET_SHARE`): added after
  comparing against real $200 half-PPR market data the user supplied
  (FantasyPros full export + a 4for4 CSV export — see
  `compare_to_market.py`). A single shared $/VORP-point rate across all 4
  positions systematically overpaid QB/TE and underpaid RB relative to both
  real sources — real auction money gives RB a scarcity premium beyond what
  points-based VORP captures (waiver-wire RB replacements are worse than
  backup QBs/TEs), which is exactly the well-known "spend up at RB, punt
  QB/TE" pattern. Fix: allocate `discretionary` across positions first using
  real market shares (average of FantasyPros/4for4 actual $ totals,
  normalized to 100%: **QB 5.85% / RB 43.1% / WR 43.45% / TE 7.6%**), then
  distribute within a position by VORP as before. Result after the fix:
  position shares landed at QB 6.6% / RB 41.9% / WR 43.2% / TE 8.3% — within
  ~1pt of target across the board (`compare_to_market.py` output).
- **K/DST**: intentionally **not** included in v1 — no projections pipeline
  exists for them yet (`ff_draft_proj` only covers QB/RB/WR/TE). Their 2
  roster spots/team are still counted in the `$1-floor` deduction (so the
  discretionary math is correct), but they don't appear as rows in the
  output. Real auctions mostly treat K/DST as flat $1 picks anyway, so this
  is a reasonable v1 gap, not a real distortion — revisit if the site page
  needs K/DST rows for completeness.

## Sanity check / calibration history
1. First run (naive `teams × starters + buffer` replacement level) put the
   top overall player at $91 of $200 (~45% of one team's budget) — user
   flagged this as visibly too high.
2. Switched to Harstad's real-season-data replacement ranks
   (QB19/RB34/WR54/TE21) — top player dropped to $62, matching Waldman's
   independent ~31%-of-budget benchmark. But comparing full output against
   real $200 half-PPR market data (FantasyPros export + 4for4 CSV, both
   supplied by the user) showed position budget shares still off: we had
   QB 8.7%/RB 36.2%/WR 44.6%/TE 10.6% vs. real ~6-7%/41-45%/42-45%/7-8%.
3. Added `POSITION_BUDGET_SHARE` (see above) to anchor cross-position
   balance to the real data. Shares now within ~1pt of target.

4. User supplied two more real references: a full Draft Sharks export
   (`reference_draftsharks_export.csv`, 12-team/$200/half-PPR/1QB-2RB-3WR-
   1TE-1FLEX, ~1000 players, all positions) and a Footballguys top-15
   snippet. Draft Sharks has two value columns — "Market $" (their tracked
   real-auction-price consensus) and "Auction $" (their own 3D-model value)
   — generated with their "value starters over depth" slider engaged per
   the user, so raw DS totals run ~1.6-1.8x higher than FantasyPros/4for4
   (matched-total sum ~3900-4200 vs ~2350) and can't be averaged in directly
   without correcting for that scale difference.
5. Built `calibrate_replacement_rank.py`: blends FantasyPros + 4for4 + Draft
   Sharks Market/Auction into a single target per player, first rescaling
   Draft Sharks so its total-per-position matches FantasyPros' (removes the
   slider-driven scale inflation while keeping DS's shape information).
   Grid-searches `REPLACEMENT_RANK` per position, minimizing RMSE against
   that blended target for each position's top-12 (most-scrutinized)
   players, holding `POSITION_BUDGET_SHARE` fixed.
6. User supplied a second Draft Sharks export, this time with a "balanced
   roster" setting instead of "starters over depth"
   (`reference_draftsharks_balanced_export.csv`) — much closer to
   FantasyPros/4for4 in absolute scale (rescale factor near 1.0), so this
   became the trusted DS reference for calibration; the "starters" export
   is kept only for display/directional comparison in `compare_to_market.py`
   (`DS-Start Mkt/Auc` columns vs. `DS-Bal Mkt/Auc`). Notably, QB/TE budget
   share came out nearly identical between the two DS configurations
   (~11-13% QB, ~11-13% TE in both) — confirming DS's higher QB/TE
   valuation vs. FantasyPros/4for4 is a real difference of opinion between
   sources, not an artifact of the "starters" slider.
7. First calibration attempt with the balanced DS export: WR (54) already
   right; RB moved 34→42 and TE moved 21→26, both looking like genuine
   improvements in isolated player checks (Gibbs $72→$54, McBride $24→$19).
   **This turned out to be wrong** — the user caught it by comparing raw
   numbers directly: "I still see sources with higher values for many of
   the top-end players... Puka, Gibbs, Bijan in the 60s easily." Checking
   raw FP/4for4/DS-balanced values for those players (e.g. Gibbs $61/$68/
   $64/$59, all genuinely clustered in the 60s) confirmed they were right
   and the calibration target was wrong.
8. Root cause: `build_target()`'s Draft Sharks rescale computed each
   source's *whole-position total* ($ summed over every player DS lists —
   ~1000 players) and divided by FantasyPros' whole-position total (~150-200
   players). Draft Sharks simply lists far more $1-$5 bench filler than
   FantasyPros does, so that ratio conflated "is DS's top end inflated"
   with "does DS just cover way more depth" — a coverage-depth artifact,
   not a real scale difference. It silently dragged the blended target
   down at the top of every position, which is exactly what pointed the
   first calibration pass at RB 42 / TE 26. Fixed by rescaling on the
   *overlapping player set only* (Draft Sharks' values restricted to
   FantasyPros' own player list) — RMSE dropped sharply across the board,
   and the search re-converged on QB 19 / WR 54 / TE 21 (Harstad's
   original numbers, unchanged) with only **RB moving slightly, 34 → 40**.
   This is the current, verified-correct state (`build_auction_values.py`'s
   `REPLACEMENT_RANK` comment has the full account).

9. WR still undershot at the very top even with the corrected
   REPLACEMENT_RANK target (Puka/Chase $55 vs. ~$62-65 blended target).
   User's hypothesis: "the lower tier players have too much value across
   all positions, which is keeping the value of the top end players so
   much lower... Jordan Addison at $7, Rachaad White at $6 seems too high."
   Verified directly with a rank-banded comparison (top 10 / 11-25 / 26+
   per position vs. FantasyPros/4for4 totals) — confirmed real overshoot in
   the depth tiers: QB ranks 11-25 at 1.14x FP, WR ranks 26-59 at 1.14x FP,
   **TE ranks 11-25 at 1.48x FP**. Since each position's total $ is fixed
   by `POSITION_BUDGET_SHARE`, that depth-tier overshoot was directly
   stealing budget from the top 10 (which undershot by a symmetric amount
   at those same 3 positions). RB's depth tier was already thin relative to
   FP/4for4 (0.87x), not fat, so this wasn't a universal problem — just
   QB/WR/TE.
10. Root cause: linear VORP-to-dollar scaling. Real auction markets pay a
    "stud premium" for elite talent beyond straight points-above-
    replacement — a shape no single `REPLACEMENT_RANK` choice can produce,
    since deepening/shallowing the baseline shifts the WHOLE curve, not
    just the top. Added `VORP_EXPONENT` (weighted_vorp = VORP ** exponent,
    exponent > 1 = convex = more $ to the top, less to depth — see the
    constant's comment in `build_auction_values.py`) and
    `calibrate_vorp_exponent.py`, which grid-searches it the same way
    `calibrate_replacement_rank.py` does. **Important: had to widen the
    calibration scoring window from top-12 to each position's FULL real
    pool** (`score(..., top_n=len(target[pos]))` in both calibration
    scripts) — a top-12 window is blind to exactly the TE 11-25 overshoot
    that started this, since most of that range falls outside rank 12.
11. Final result: `VORP_EXPONENT = {"QB": 1.1, "RB": 1.0, "WR": 1.2,
    "TE": 1.2}`. Re-ran the band comparison after applying: **WR now
    matches almost exactly** (top 10 at 1.00x FP, depth at 1.00x FP, both
    were 0.90/1.14 before). Puka Nacua jumped to **$65** (exact FP match).
    Jordan Addison $7 → $6 (close to FP's $5); Rachaad White stayed $6
    (already below FP's $8 — wasn't actually the problem, WR depth was).
    TE improved but not fully (depth tier 1.48x → 1.29x FP) — a higher TE
    exponent tests roughly flat on the aggregate RMSE metric (1.2 vs. 1.4+
    are close), so there's a bit more headroom there if it's worth chasing
    further. QB/TE aggregate budget share still runs a bit hot against
    FantasyPros/4for4 alone, but sits between FP/4for4 and Draft Sharks
    (both DS configs agree QB/TE deserve more) — reads as an honest split
    between sources, not a bug.
12. The WR-exponent fix in step 11 created a new problem, caught by the
    user: it pushed Puka Nacua/Chase ($65/$55) above Gibbs/Bijan ($61/$61)
    in raw dollars, despite Gibbs/Bijan having ~22% more VORP and sitting
    #1/#2 in the user's own personal rankings. Checked all 4 references
    directly: FantasyPros has WR on top (Nacua $65 > Gibbs $61), but 4for4
    (Gibbs $68 > Chase $64, and RB1-5 all clear $60 while only WR1-3 do —
    a broad pattern, not just a 2-player edge) and Draft Sharks' real
    "Market $" column (Bijan $66 > Nacua $62) both have RB on top; only
    Draft Sharks' own "Auction $" model column favored WR. That's 3 of 4
    *real tracked-price* sources favoring RB, with the 4th data point being
    a model's own output, not real market data. Fix: rebuilt
    `calibrate_replacement_rank.py`'s `build_target()` to drop Draft
    Sharks' "Auction $" from the blended target entirely (keep only
    FantasyPros, 4for4, and Draft Sharks' "Market $" — three real-price
    signals), then re-ran both calibration scripts. Result: `REPLACEMENT_RANK`
    barely moved (QB 19→16, others unchanged) but `VORP_EXPONENT` gave RB
    its own convexity too (1.1, not 1.0) rather than leaving it flat while
    WR got steeper. **Final: Gibbs, Bijan, Nacua, and Chase all land tied
    at $65** — RB no longer prices below WR at the top, matching the
    VORP/personal-rank signal and the majority of real-price sources, while
    the WR depth-tier fix from step 11 stays fully intact (still 1.00x FP
    in both top-10 and depth bands). Final constants:
    `REPLACEMENT_RANK = {"QB": 16, "RB": 40, "WR": 54, "TE": 21}`,
    `VORP_EXPONENT = {"QB": 1.1, "RB": 1.1, "WR": 1.2, "TE": 1.0}`.

**Lesson for future calibration work on this project:** don't blend a
source's own *model output* into a "real market" calibration target
alongside genuine tracked/crowd price data — Draft Sharks' "Market $" and
"Auction $" columns look superficially similar (both are dollar figures on
the same export) but only one of them is actual market data. This cost two
rounds of chasing the wrong signal before being caught by the user
cross-checking raw numbers by hand both times (once for the RB42/TE26
rescale bug, once for this WR-over-RB ordering issue) — the lesson being
that automated RMSE-minimization against a blended target is only as
trustworthy as the target, and spot-checking a handful of well-known
players against raw source numbers is a cheap, high-value sanity check to
run before trusting any calibration result.

13. User then flagged a third issue: Gibbs/Bijan/Nacua/Chase all landing at
    exactly $65 "seems weird." Traced to an actual bug in
    `blend_with_personal_ranks()`, not a coincidence: `NUDGE_WEIGHT` was
    `0.5`, and for ANY two players who simply swap ranks between
    projections and personal rankings (Gibbs projected #1/personal #2,
    Bijan projected #2/personal #1 — a common pattern, not rare), the nudge
    algebra works out so a 0.5 weight makes their blended points exactly
    equal regardless of how different their real points were:
    `A_new = P_i + w(P_j - P_i)`, `B_new = P_j + w(P_i - P_j)`,
    `A_new == B_new  <=>  (1 - 2w)(P_i - P_j) == 0`, true only when `w ==
    0.5` (since `P_i != P_j` for two different players). This wasn't a
    same-after-rounding coincidence — the underlying blended points were
    bit-for-bit identical. Fixed by changing `NUDGE_WEIGHT` to `0.4` (any
    value other than exactly 0.5 avoids the pathology) — see the
    constant's comment in `build_auction_values.py` for the full algebra.
    Re-verified all prior fixes (band ratios, RB>=WR ordering) still hold
    after the change; they do, within noise. Gibbs/Bijan and Nacua/Chase
    still round to close/identical whole-dollar values after this fix
    ($65/$65, $64/$64) — that part is fine and expected (they ARE close in
    real value per every reference too); what's fixed is that the
    underlying numbers are no longer artificially forced together by the
    blend math itself.

**Sources tried but not usable via WebFetch (needed a user-supplied
export/paste instead):** draftsharks.com/auction-values/half-ppr and
football.fantasysports.yahoo.com/f1/draftanalysis?type=salcap are both
client-side-rendered — WebFetch either returns no real data (Yahoo) or
data that looks misaligned/untrustworthy (values not even in rank order).
Draft Sharks was eventually obtained anyway via a full CSV export the user
downloaded from their site directly (`reference_draftsharks_export.csv`,
see item 4 above) — Yahoo remains unused. Footballguys' own
`salary-cap-auction-values` tool DID work via WebFetch for a paywall-free
partial view (RB top 10 first, then confirmed unnecessary once Draft
Sharks' full export arrived).

## Live draft mode (`build_live_draft_workbook.py`) — v1, Excel test bed
Phase 4 from the original plan, built once the static table was validated
(the whole history above). Per user's direction: test the live recalc math
in Excel first, figure out site/config integration later — this is
deliberately scoped to *just* the live adjustment, not yet the "adjustable
budget/roster/league size" piece from Phase 2/3.

**Formula**: the same discretionary-money math confirmed directly against
the user-supplied Footballguys forum thread ("Simple Formula For Value of
Auction $ On the Fly" — the forum blocks scripted fetches, but the user
pasted the actual formula text), re-run after each pick with that player's
price and weighted-VORP removed from the pool. Applied **separately within
each position's own pool** (not one flattened global pool like the
thread's original single-position example) — that's what preserves the
QB/RB/WR/TE-specific `REPLACEMENT_RANK`/`VORP_EXPONENT`/
`POSITION_BUDGET_SHARE` calibration work instead of undoing it on the first
pick:
```
remaining_discretionary[pos] = initial_discretionary[pos] - SUM(price_paid - 1) over drafted players in pos
remaining_weighted_vorp[pos] = initial_weighted_vorp[pos] - SUM(weighted_vorp) over drafted players in pos
current_rate[pos] = remaining_discretionary[pos] / remaining_weighted_vorp[pos]
live_value(player) = price_paid if drafted else 1 + weighted_vorp * current_rate[pos]
```

**Workbook** (`live_draft_board.xlsx`, generated fresh each run — openpyxl,
not win32com; no legacy formatting to preserve since it's a new file, and
openpyxl doesn't need Excel installed/running):
- `Draft Board` — one row per player, columns Player/Position/Team/Weighted
  VORP/Static Value/**Price Paid (blank, user fills in)**/Live Value
  (formula). AutoFilter enabled — filter Price Paid to blanks + sort Live
  Value descending to see the current board.
- `Live Calc` — one row per position, SUMIFS-driven running totals
  (drafted $ spent, drafted weighted VORP, remaining pool, current rate).
  This is where the actual re-inflation math lives; Draft Board just reads
  the current rate per position via INDEX/MATCH.

**A "Big Board" sheet using Excel 365 dynamic-array `SORT`/`FILTER`
formulas was tried and abandoned** — openpyxl doesn't write the special
spill-formula XML markup Excel's strict parser requires, and the resulting
file failed to even OPEN in Excel (not a formula error, a file-open
failure — confirmed by reproducing with a minimal 2-cell test file
containing only a SORT/FILTER formula). Also caught in the same pass: an
openpyxl `DataValidation` created with `formula1`/`formula2` as raw ints
instead of strings had the same failure-to-open symptom. **Lesson: avoid
writing Excel 365-only dynamic array formulas via openpyxl entirely** —
stick to plain formulas (SUMIFS, INDEX/MATCH, IF) and let the user sort/
filter manually via AutoFilter, which works in any Excel version and
carries no corruption risk.

**Verified via `verify_live_workbook.py`** (one-off Excel-COM script, opens
the workbook, forces recalculation, checks real values — not part of the
regular pipeline, kept for re-verification if the formulas are touched
again): before any picks, Live Value ≈ Static Value for spot-checked
players. After Gibbs is entered at $100 (an overpay vs. his ~$65 static
value), Bijan Robinson's live value *drops* slightly (RB pool rate
0.198 → 0.191) — this is CORRECT, not a bug, confirmed against the
Footballguys thread's own worked example (Chris Johnson overpays, Andre
Johnson's price drops too, "because extra money that should have gone to
the other players went to CJ instead"). After Gibbs is instead entered at
$20 (a big underpay), the rate rises (0.191 → 0.209) and Bijan's live value
inflates up to ~$68 — confirming both directions work. Puka Nacua (WR) was
unaffected by either RB-pool change, confirming the per-position pool
isolation works as intended.

Also fixed: `Live Value` was showing decimals (e.g. $65.39) — real auction
bids are always whole dollars. Wrapped the formula in `ROUND(...,0)` and
switched the `Price Paid` `DataValidation` from `type="decimal"` to
`type="whole"` so entries themselves can't be fractional either.

## Live draft mode v1.1: per-TIER pools, not per-position (`tiers.py`)
User's concern, illustrated concretely: "say CeeDee Lamb goes for $5 more
and is the first WR taken, then DK Metcalf goes for $3 more and is the
second WR taken. I'm not sure that should affect the amount for Chase or
Puka who are in a tier of their own." Correct — v1's single position-wide
rate meant ANY WR pick, regardless of tier, proportionally moved every
other WR's price, including elite players nowhere near that tier. This is
the same concern from way earlier in the project (the original "per-
position live recalibration" idea, before it was scoped out as too complex
for v1) — now addressed with a scoped-down, buildable version of it.

**Tier source — deliberately NOT Draft Sharks' tiers.** First instinct was
to reuse the `Pos. Tier` column already sitting in
`reference_draftsharks_export.csv` (less work, "expert-defined"). User
correctly rejected this: Draft Sharks' tiers come from their own
projections/valuation model, which we've already established differs from
ours in specific, deliberate ways throughout this whole project (different
replacement levels, different convexity) — there's no reason an external
tier boundary would line up with an actual gap in *our* curve. Two players
we compute as very close in value could land split across a DS tier
boundary for reasons that have nothing to do with our own numbers.

**Method (`tiers.py`)**: derive tiers from natural gaps in each position's
own weighted-VORP curve. Walk players sorted descending; a tier break goes
after player i if the gap to player i+1 is at least `GAP_RATIO` (1.8x)
times the local median gap (the `WINDOW`=5 gaps on either side) — relative
to its neighborhood, not an absolute threshold, since gap sizes shrink
naturally deeper in a position. This is a standard "find the elbow"
heuristic, not a novel algorithm — kept deliberately simple/auditable
rather than reaching for full 1D clustering (Jenks natural breaks etc.),
since the goal is a transparent, debuggable rule for a live tool, not
statistical optimality. Zero-weighted-VORP players (below replacement) all
land in one final catch-all tier per position, since there's no meaningful
curve shape left to find breaks in down there.

**Validated on real output before wiring anything in**: WR Tier 1 = Puka
Nacua, Ja'Marr Chase, Jaxon Smith-Njigba, Amon-Ra St. Brown (gap after
rank 4 is 90.6, vs. 1-40 for surrounding gaps — an obvious real cliff);
Tier 2 = CeeDee Lamb, Drake London, Justin Jefferson; D.K. Metcalf lands
all the way down in Tier 8. Exactly separates the pair the user named.

**Integration**: `assign_position_tiers()` in `build_auction_values.py`
runs after `compute_auction_values()`, tags each player with a `tier`
(1-indexed within their position), and splits each position's existing
`discretionary_dollars`/`total_weighted_vorp` across its tiers,
proportional to each tier's share of the position's total weighted VORP.
This is a pure split, not a new allocation: before any picks, a tier's own
rate is mathematically identical to the position's old rate (both
numerator and denominator scale by the same tier share), so **static
Auction Values are completely unchanged by adding tiers** — verified by
rebuilding and diffing Gibbs/Bijan/Puka/Chase, still $65/$65/$64/$64.
Only how LIVE recalibration ripples changes.

`build_live_draft_workbook.py`'s `Live Calc` sheet now has one row per
(position, tier) pair (keyed by a `Pos-Tier` text column, e.g. `"WR-1"`)
instead of one row per position — SUMIFS/formulas otherwise unchanged in
structure, just filtered on the combined key instead of position alone.
Draft Board gained a helper `Pos-Tier` column (`=Position&"-"&Tier`,
hidden) so the Live Value formula's MATCH can look up the right tier's
current rate.

**Verified via `verify_live_workbook.py`** (rewritten for the new layout):
CeeDee Lamb (Tier 2) entered at $44 (+$5 over static) and D.K. Metcalf
(Tier 8) entered at $15 (+$3 over static) — Ja'Marr Chase and Puka Nacua
(Tier 1) stayed at exactly $64.00/$64.00, completely unmoved. Justin
Jefferson (Tier 2, same tier as Lamb) dropped $38 → $35; Courtland Sutton
(Tier 8, same tier as Metcalf) dropped $12 → $11 — real, appropriately
localized ripples within each pick's own tier, none of it reaching the
elite tier. Exactly the behavior requested.

**Note for future sessions**: mid-verification, a win32com `wb.Close()`
call threw a COM error but appears to have saved the workbook's in-memory
test state anyway (Lamb/Metcalf's test prices were found baked into the
file on the next run, despite `SaveChanges=False`) — a known-flaky pattern
with this Excel automation setup, not a script logic bug. If a
verification run ends in a COM error, **rebuild the workbook from Python
again before handing it to the user** rather than assuming
`SaveChanges=False` actually discarded the test edits — confirmed clean by
checking `Price Paid` cell count == 0 after rebuilding.

## Two things this tool intentionally does NOT model
Discussed with the user, worth recording so it doesn't get "fixed" as a bug
later:
1. **Values don't decay just from the draft progressing.** Verified both
   algebraically and in the actual workbook: if every pick in a bucket goes
   for exactly its currently-computed live value, that bucket's rate is
   provably identical before and after (drafted 3 RB-Tier-5 players each at
   their exact live value — the tier's rate barely moved, ~0.3%, entirely
   explained by whole-dollar rounding noise; an untouched player still in
   that tier, Josh Jacobs, showed the exact same live value, $33, before
   and after). Values only move when a REAL price deviates from what the
   model expected — never from time/pick-count alone.
2. **No individual team-budget tracking across the whole draft.** The
   user's intuition ("shouldn't players drop in value across the board as
   overall money runs out?") is pointing at a real phenomenon — in actual
   auctions, individual teams run out of cash near the end and are forced
   into $1 bids on decent players regardless of the model's price, purely
   because they have no money left. This tool can't see that: it tracks
   aggregate position/tier pools, not which of the 12 teams still has
   money and which needs that position. Modeling it properly would need
   real per-team draft tracking (who bought whom, for how much), which is
   a materially bigger scope than a pricing board — deliberately not
   built. Worth noting: none of the real sources calibrated against in
   this project (FantasyPros, 4for4, Draft Sharks) track this either — it's
   a common simplification across auction tools generally, not something
   uniquely missing here.

## `My Team` sheet: personal budget tracker (scoped-down version of #2 above)
Full per-team tracking (all 12 teams, live) was offered and explicitly
declined as too big a scope change for now — user asked for a much simpler
version instead: just track *your own* roster/budget, not the whole
league's. Added as a third sheet in `build_live_draft_workbook.py`
(`add_my_team_sheet()`), completely independent of Draft Board/Live Calc
(no formula linkage — deliberately simple, no dropdown/lookup, since DEF/K
aren't on the Draft Board at all and this needed to stay easy to reason
about under "a simple tracking sheet").

- One row per real roster spot (`build_roster_slots()`, generated from the
  same `STARTERS`/`FLEX_SLOTS`/`BENCH_SPOTS` constants used everywhere
  else — QB/RB/RB/WR/WR/TE/FLEX/DEF/K/Bench×6 = 15 total). **DEF and K get
  slots here even though they're not projected/valued anywhere in this
  project** — they still cost real money out of a real budget, and the
  whole point of this sheet is accurate real-money math for the user
  specifically, not player valuation.
- Free-text Player column + whole-dollar-validated Price Paid column.
- Summary block: Total Budget, Spots Filled/Remaining, Total Spent, Money
  Remaining, Max Bid on Next Player (money remaining minus $1 reserved for
  every OTHER remaining spot), Avg $ per Remaining Spot.

**Verified via win32com**: before any picks, $200 budget / 15 spots →
$13.33 avg, $186 max bid (reserving $1 × 14 other spots) — both exact.
After 3 picks totaling $89 ($25 + $61 + $3), remaining budget correctly
drops to $111 across 12 spots → $9.25 avg, $100 max bid. All numbers
matched hand-calculated expectations exactly.

**Recurring gotcha, now happened 3 times across this project's Excel
verification runs**: a win32com `wb.Close(SaveChanges=False)` sometimes
still leaves test data saved into the file (COM error during close, or
just flaky behavior) — confirmed again here (a verification run's test
picks were found saved into `My Team` on the next open). Standing
practice: **always rebuild fresh from Python and confirm 0 filled cells on
both Draft Board and My Team before considering a verification pass
"done"** — don't trust `SaveChanges=False` alone.

## Live draft mode v1.2: two-factor model + position-block layout
This closes out the "per-position live recalibration" open question from
v1.1 above — the user's original concern (tier-level budget conservation
isn't a real constraint) turned out to be correct, confirmed by working
through the economics carefully rather than just re-asserting the old
design.

**Why v1.1's tier-level budget-depletion model was wrong, not just
debatable**: it implicitly assumed each tier has its own fixed sub-budget
that must balance out immediately after every pick. That's not a real
constraint — there's no rule forcing "the WR2 tier collectively spends
exactly $X"; that number was only ever a historical average. The ONE place
a genuinely hard, mechanical "total money is finite" constraint exists is
the WHOLE DRAFT (all 180 roster spots across 12 teams, $2400 total, every
team must fill every spot). And even that constraint really resolves at
the TEAM level (Team A overpaying leaves Team A, specifically, with less
money for the rest of ITS OWN roster — any position) rather than "the
WR2 tier broadly has less money," which we can't see anyway without
per-team tracking (declined earlier as too big a scope).

**Two separate signals, not one blended formula** (user explicitly asked
for a hybrid rather than picking one or the other):
1. **Tier-level market re-rating** (local, same-direction):
   `tier_factor = SUM(real prices paid in this tier) / SUM(those players'
   original static values)`. A real price is treated as evidence about
   what this specific room currently values that tier at — if a tier runs
   hot, the REST of that same tier gets repriced UP, matching the
   well-documented real "positional run" phenomenon (a tier running hot
   tends to keep running hot for the next few picks, not immediately
   reverse).
2. **Whole-draft-level budget depletion** (global, all positions
   combined): the same discretionary-money formula from v1, but computed
   ONCE across every position together, not per tier — this is where the
   real hard constraint actually lives.
   `global_factor = current_whole_draft_rate / initial_whole_draft_rate`

Final: `live_value = ROUND(static_value * tier_factor * global_factor, 0)`.

**Verified via `verify_live_workbook.py`**: drafted CeeDee Lamb (+$5) and
D.K. Metcalf (+$3), both WR — Justin Jefferson (Lamb's own tier) moved UP
$38→$43, Courtland Sutton (Metcalf's tier) moved UP $12→$15 (same
direction, as designed), while Chase/Nacua (a different, untouched tier)
and Gibbs (a different position) stayed exactly unchanged — confirming
tier isolation still holds. Separately, drafted 40 RB players each 25%
over their static value (a bigger, more realistic simulated run) — the
global depletion factor dropped to 0.73, and an untouched WR (Emeka
Egbuka, zero WR picks in this test) correctly dropped $17→$12 purely from
the global factor, even though nothing in his own position or tier moved.
That's the "if enough overall money is spent, everything trends down a
little" effect from the user's original question — now correctly modeled
as its own separate, uniformly-applied signal instead of leaking through
the tier mechanism.

**Position-block layout**: Draft Board rebuilt as side-by-side column
blocks (QB / RB / WR / TE each in their own columns, e.g. QB at column A,
RB at column I, etc. — matches the layout convention already used
elsewhere in this repo, e.g. `ff_rankings/export_combined.py`'s combined
exports), instead of one long vertical list with a Position column. Each
block: Player / Team / Tier / Weighted VORP (hidden helper) / Static Value
/ Price Paid / Live Value. Per user request, trimmed to a realistic
draftable depth instead of the full ~700-player pool:
`BOARD_DEPTH = {"QB": 40, "RB": 100, "WR": 120, "TE": 50}`.

**Live Calc restructured** to match: one mini-table per position (Tier /
Drafted Price Sum / Drafted Static Sum / Tier Factor, matched by plain
Tier number now that each position has its own columns — no more text
`Pos-Tier` concatenation key needed), plus one `GLOBAL (whole draft)` table
tracking the same discretionary-money math as v1 but summed across all 4
position blocks via `SUM()`/`COUNT()`/`SUMIFS()` over each block's own
column ranges.

**Approximation accepted, documented in the script**: the global table's
"Initial Discretionary $" / "Initial Weighted VORP" constants come from
the full, untrimmed calibration (`pos_stats`, already verified throughout
this whole project), not a fresh sum over just the trimmed/visible board.
The tiny amount of weighted VORP sitting in players below the trim depth
(QB41+, RB101+, etc.) is negligible — they're all near replacement level,
which is exactly why they got trimmed — so this doesn't meaningfully bias
the depletion factor, but it means those players can never be "seen" as
drafted by the global tracker even in principle (they're not on the
board). Acceptable; not worth a fresh recomputation for this.

**Also fixed while rebuilding**: `Workbook()`'s default blank `"Sheet"`
tab was never removed in v1/v1.1 — sat there unused the whole time. Now
explicitly removed (`wb.remove(wb.active)`) right after creation.

**Same recurring win32com gotcha, 4th occurrence**: a verification run's
test prices were found saved into the file on the next open despite
`SaveChanges=False`. Same standing practice applies — rebuild fresh from
Python and confirm 0 filled price cells (now checked across all 4 position
blocks AND My Team) before considering any verification pass "done."

## Phase 2 begins: live-editable Starting Budget (`Setup` sheet)
First real-world signal: user had other people test-draft with the tool
and they liked it. First customization requested: recalculate everything
based on starting budget, with an explicit heads-up that team count and
roster-shape configurability are coming next — asked to be designed with
that in mind.

**Key realization that made this simpler than expected**: a player's
Weighted VORP doesn't depend on budget at all — only on projections/
personal rankings/replacement level/convexity exponent (all fixed
calibration). Only the FINAL dollar-conversion step depends on budget. So
rather than requiring a Python rerun for every budget test, that
conversion step — previously computed once in Python and baked into the
workbook as a literal number — became a live Excel formula referencing a
`Setup!Budget` cell. Change the number, every Static Value AND Live Value
on the whole board recalculates instantly.

**Why team count ISN'T exposed as editable yet, even though the $
arithmetic would technically "work"**: `REPLACEMENT_RANK` (which player
rank counts as replacement level per position) was calibrated against real
market data specifically for a 12-team league (the whole Harstad-baseline/
market-comparison history above). Changing team count would silently
produce wrong numbers — the totals would still compute and look plausible,
but the underlying replacement-level assumption wouldn't match a
different-sized league — without a real recalibration effort first, not
just a formula change. `POSITION_BUDGET_SHARE` has the same problem tied
to roster shape. Exposing either as editable now would be misleading, so
`Setup` shows them as fixed reference info with an explicit note, not
editable cells. **Do not casually make these editable later without first
addressing recalibration** — that's the real work, not the UI change.

**Architecture** (`build_live_draft_workbook.py`, restructured):
- `Setup` sheet: `Starting Budget ($)` (editable, whole-dollar validated,
  default 200) plus read-only `Number of Teams` / `Roster Shape` labels.
- `Live Calc` gained a `$ SETUP` block (Total Teams / Roster Spots / Money
  / Discretionary — all formulas chained from `Setup!Budget`) and a
  `POSITION RATES` table (`discretionary $ per position` ÷ `that
  position's total weighted VORP` = `$/VORP rate`, one row per position).
  Total Weighted VORP per position is a fixed constant computed from the
  TRIMMED/visible board specifically (not the full untrimmed pool used
  elsewhere in this project) — Static Value now has to be computed live
  from what's actually sitting on the sheet, so the denominator has to
  match what can actually be marked "drafted" here. Negligible difference
  in practice (the trimmed-out tail is near-zero VORP, which is exactly
  why it got trimmed).
- Draft Board's `Static Value ($)` column changed from a literal number to
  a formula: `=ROUND(1 + WeightedVORP * position_rate_cell, 0)`. Tier
  Factor and Global Factor formulas (v1.2) are unchanged in structure —
  they just now read a Static Value that's itself dynamic, which cascades
  correctly through Excel's normal dependency graph, no special handling
  needed.
- Because Draft Board's formulas need Live Calc's cell addresses (and vice
  versa isn't true), build order changed: `build_draft_board_shell()`
  writes headers/Player/Team/Tier/WeightedVORP/Price columns only, THEN
  `build_live_calc()` runs and returns its addresses, THEN `main()` goes
  back and fills in Draft Board's Static Value and Live Value formulas.
- `My Team`'s `Total Budget ($)` now references `=Setup!$B$3` instead of a
  hardcoded literal, so it stays correct when budget changes too.

**Bug caught before shipping, worth remembering**: while composing the
`$ SETUP` block, `Total Teams` was accidentally written as
`=Setup!$B$3` (the BUDGET cell) instead of `=Setup!$B$5` (the actual Teams
cell) — would have computed Total Money as `Budget × Budget` instead of
`Teams × Budget`. Caught by verifying actual numbers in Excel rather than
trusting the formula looked right on read-through — same lesson as the
Draft Sharks rescale bug earlier in this project: always verify computed
values against hand-calculated expectations, don't just eyeball formula
text.

**Verified via `verify_live_workbook.py`**: at the default $200 budget,
global discretionary = $2220 (exactly matches the value this whole project
has been calibrated against throughout). Changed `Setup!B3` to $260 —
discretionary rose to $2940 (a 1.324x increase, appropriately MORE than
the raw 1.3x budget ratio, because the fixed $180 roster-spot floor
becomes a smaller fraction of a bigger budget — confirmed Gibbs's Static
Value grew from $66 to $87, slightly ahead of pure-proportional $86,
matching that predicted nonlinearity). Stress-tested a $20 budget (near
the $180 roster-spot floor) — discretionary correctly dropped to a small
but positive $60, Gibbs fell to $3, nothing broke or went negative. My
Team's budget cell correctly tracked the change back to $200 after
resetting.

**Also fixed**: an `Alignment.copy(wrap_text=True)` deprecation warning
from openpyxl — replaced with a direct `Alignment(wrap_text=True)`
construction.

## 12-team baseline, round 4: re-pulled after a suspected source-settings issue
User re-pulled all 3 reference sources weeks after the original 12-team
calibration, suspecting a settings error (top-end $ values had shifted
down noticeably at FantasyPros/4for4 — e.g. Gibbs $61→$55, Nacua $65→$51 —
while Draft Sharks stayed close to its original numbers). Couldn't fully
disentangle from the data alone whether this was a genuine setting fix, or
real market movement over the elapsed time (projections update
continuously; the file timestamps were ~1 week apart), or both. Decision:
treat the new pull as the more current signal and recalibrate against it
rather than trying to adjudicate the "why" — same practical stance as
always in this project (trust real data over reasoning about what should
be true).

Files: `reference_fantasypros_12team_v2.csv` (raw site export — needed
`compare_teamcount.py`'s `load_fp_raw_export()`, not the manually-
transcribed format used originally), `reference_4for4_12team_v2.csv`,
`reference_draftsharks_12team_v2.csv`. Recalibration script:
`calibrate_12team_v2.py` (one-off, same grid-search methodology as
`calibrate_replacement_rank.py`/`calibrate_vorp_exponent.py`).

**Raw grid-search result**: `REPLACEMENT_RANK` suggested QB 16→22, RB
40→42, WR 54→60, TE 21→26. **Caught the same flaw as before on QB/TE**:
verified individual players before accepting anything, and QB22/TE26
improved the unweighted top-12 RMSE by degrading the single most-
scrutinized player specifically — Josh Allen would drop to $21 against a
real blended target of ~$29 (worse), McBride to $19 against ~$24 (worse).
QB16/TE21 (unchanged from round 3) already matched those two almost
exactly. RB/WR were different: the deeper ranks (42/60) genuinely tightened
the fit for Gibbs/Bijan/Chase/Nacua specifically, not just in aggregate.
**Decision: kept QB/TE at their round-3 values, adopted RB→42 and WR→60.**
Then re-ran the exponent search with the corrected ranks held fixed (not
the ranks from the flawed QB22/TE26 pass) — final: QB 1.1→1.0, RB
1.1→1.15, WR unchanged at 1.2, TE 1.0→0.9.

**Final verification against real data** (not just the aggregate metric):
Amon-Ra St. Brown $45 — exact match to FantasyPros' $45. Brock Bowers $22
— exact match to FantasyPros' $22. Gibbs $60, Bijan $59, Chase $54, Nacua
$54 — all land centered within the FantasyPros/4for4/Draft-Sharks spread
rather than outside it (previously overshot all three by $7-10). Josh
Allen $28, McBride $22 — both close to FantasyPros specifically, in the
middle of the wider 4for4-to-Draft-Sharks range.

**Production constants updated**:
`REPLACEMENT_RANK = {"QB": 16, "RB": 42, "WR": 60, "TE": 21}`,
`VORP_EXPONENT = {"QB": 1.0, "RB": 1.15, "WR": 1.2, "TE": 0.9}`.
Rebuilt `auction_values_half_ppr.csv`/`.xlsx` and `live_draft_board.xlsx`
(tiers recompute automatically from the new weighted-VORP curve via
`assign_position_tiers()` — no separate tier recalibration needed).
Verified the live workbook's Static Value formulas match the Python
output exactly (Gibbs $60, Nacua $54, Allen $28) and the file has zero
leftover price entries.

**Not touched**: the 10-team calibration (`CALIBRATED[10]` in
`build_teamcount_estimate.py`) — it was fit directly against real 10-team
data via an independent grid search, not derived as a delta from the
12-team baseline, so changing the 12-team numbers doesn't invalidate it.
`POSITION_BUDGET_SHARE` also left unchanged — the new data's aggregate
position split wasn't clearly different enough from the original pattern
to justify touching it; only within-position shape (`REPLACEMENT_RANK`/
`VORP_EXPONENT`) needed correction this round.

## Team count: testing math-only scaling before committing to full recalibration
User asked how sites like FantasyPros/4for4/Draft Sharks derive their
numbers "just using math." Honest answer: they almost certainly don't —
they run real drafts at massive scale on their own platforms (mock drafts,
live draft tools), giving them proprietary Average Auction Value (AAV)
datasets. What looks like a pure formula from the outside is a formula
calibrated against real prices they don't publish the sourcing for. This
project has been using their *published output* as a proxy for that same
real-market signal, one step removed — which is why gathering value charts
from those sites has been the core validation method throughout.

That said, real math-based shortcuts DO exist for some of what's
calibrated here, just not all of it:
- `REPLACEMENT_RANK` has a real mathematical basis: Harstad's original
  methodology is about counting total player-STARTS a league needs (teams
  x starters x weeks), which scales linearly with team count — arithmetic,
  not empirical fitting. We don't have Harstad's underlying real
  games-played dataset (only his published 12-team findings), so we can't
  fully re-derive it, but proportionally scaling the *already-validated*
  12-team rank by team-count ratio is a principled approximation of that
  same logic.
- `POSITION_BUDGET_SHARE` and `VORP_EXPONENT` have no equivalent
  shortcut — they're about human bidding psychology (how much of a
  budget people allocate to RB vs. WR, how much premium they pay for
  elite talent), not roster math. No games-played statistic predicts
  that; it's fundamentally empirical.

**Test set up**: `build_teamcount_estimate.py` builds a full auction-value
table for any team count using `REPLACEMENT_RANK` scaled by
`teams/12` from the validated 12-team values, while holding
`POSITION_BUDGET_SHARE`/`VORP_EXPONENT` **constant** at their 12-team
values — a hypothesis, not a derivation. Chose 10 teams as the test case
(`python build_teamcount_estimate.py 10` → `auction_values_10team_half_ppr.csv`).
Scaled ranks: QB 16→13, RB 40→33, WR 54→45, TE 21→18. Resulting top values
run a bit higher than at 12 teams (Nacua/Chase $70, Gibbs/Bijan $68 vs.
$65/$64 at 12 teams) — directionally correct (smaller leagues have more
relative talent depth, so replacement level is shallower and elite players
command a bigger share of a proportionally smaller budget — standard
real-world auction advice for smaller leagues).

Required code change to support this: `compute_auction_values()` gained a
`teams` override parameter (matching the existing `ranks`/`exponents`
override pattern used by the calibration scripts), replacing the
module-level `TEAMS` constant with a parameter that defaults to it —
backward compatible, verified the default 12-team output is unchanged
after the change.

**Result: the math-only hypothesis did NOT hold up well enough.** User
pulled real $200/half-PPR/10-team data from all three sources
(`reference_fantasypros_10team.csv`, `reference_4for4_10team.csv`,
`reference_draftsharks_10team.csv` — the FantasyPros file needed a new
loader, `compare_teamcount.py`'s `load_fp_raw_export()`, since it's a raw
site export in a different format than the manually-transcribed 12-team
reference file). Aggregate position share was in a similar ballpark to
the 12-team FP/4for4-vs-DS disagreement pattern (not obviously broken),
but individual top-of-position values were badly off: Puka Nacua
estimated $70 vs. real $52 (FP)/$54 (4for4)/$61-62 (DS); Jahmyr Gibbs $68
vs. $57/$60/$57-61. Holding `VORP_EXPONENT` constant while shrinking
`REPLACEMENT_RANK` compounded rather than offset — both push toward
concentrating value at the top simultaneously.

**Real recalibration (`calibrate_teamcount.py`), against the same real
10-team data, produced a genuine surprise**: `REPLACEMENT_RANK` barely
moved from the 12-team values — QB 16→19, RB 40→38, **WR 54→54
(unchanged)**, TE 21→24 — nowhere near the much-shallower QB13/RB33/WR45/
TE18 the proportional scaling had predicted. Likely explanation: the real
games-played curve underlying Harstad's methodology isn't linear — a
modest team-count change (10 vs. 12, ~17%) may land in a relatively flat
part of that curve, so the actual rank shift is much smaller than
proportional arithmetic assumes. `VORP_EXPONENT` moved only modestly too
(QB 1.1→1.2, RB 1.1→1.05, WR unchanged at 1.2, TE 1.0→1.1).
`POSITION_BUDGET_SHARE` was left untouched — the aggregate-share data
didn't clearly contradict holding it constant, unlike replacement rank/
exponent which clearly did need real recalibration.

**Re-verified with the corrected constants**: Nacua $53 vs. $52/$54 real
(was $70), Chase $53 vs. $50/$56 (was $70), Gibbs $60 vs. $57/$60 (was
$68), Josh Allen $22 vs. $24/$24 (was $38) — all now closely matched
across the rest of the WR/RB/TE top-15 too. `build_teamcount_estimate.py`
updated with a `CALIBRATED` lookup dict (team count → real
ranks/exponents) — team counts present in that dict use validated real
numbers; anything not yet calibrated falls back to proportional scaling,
clearly flagged in the script's own output as unvalidated.

**Lesson for 14/16/8 teams later**: do NOT assume proportional scaling is
"probably fine" without checking, even though it felt like a reasonable
shortcut going in. 14 teams is a smaller relative change from 12 than 10
was, so more likely to behave similarly to the modest 10-team shift seen
here — but 8 teams is a 33% reduction, a much bigger extrapolation, and
should get its own real-data check before trusting it, not be assumed
from the 10-team pattern.

## Round 5: full 8/10/12/14/16-team recalibration + live team-count switching (v1.3)
User replaced every reference file in the folder with a single, internally
consistent pull: `reference_<source>_<teams>team.csv` for all 3 sources
(fantasypros/4for4/draftsharks) x all 5 team counts, all timestamped within
the same ~45-minute window — first time this project had one clean,
simultaneous dataset instead of team counts calibrated at different times
against differently-vintage data (the earlier 10-team-only pull, the
12-team "v2" re-pull, etc.). Asked for: real calibration of all 5, live
team-count switching built into `live_draft_board.xlsx` as a restricted
dropdown (not a command-line arg), and the total dollar amount surfacing
correctly as team count changes.

**Confirmed again, now across all 5 team counts, not just 10: proportional
rank scaling from the 12-team baseline is not safe to trust.** Every team
count needed its own real grid-search calibration (`calibrate_teamcount.py`,
generalized from the single-team-count `calibrate_teamcount.py`/
`calibrate_12team_v2.py` scripts to take a team count and load that team
count's own `reference_*_<teams>team.csv` files). Final validated numbers
(also in `build_teamcount_estimate.py`'s `CALIBRATED` dict, the single
source of truth both the CSV builder and the live workbook now read from):

| Teams | QB rank | RB rank | WR rank | TE rank | QB exp | RB exp | WR exp | TE exp |
|-------|---------|---------|---------|---------|--------|--------|--------|--------|
| 8     | 15      | 34      | 45      | 16      | 1.15   | 1.2    | 1.15   | 1.0    |
| 10    | 16      | 40      | 54      | 18      | 1.0    | 1.2    | 1.15   | 0.9    |
| 12    | 19      | 44      | 64      | 24      | 1.05   | 1.15   | 1.15   | 0.9    |
| 14    | 19      | 44      | 60      | 24      | 0.9    | 0.85   | 1.0    | 0.7    |
| 16    | 16      | 44      | 60      | 24      | 0.7    | 0.7    | 0.85   | 0.5    |

12-team's numbers shifted slightly from Round 4 (RB 42→44, WR 60→64, TE
21→24, QB unchanged at 19 vs. the mid-round value) against this fresh pull
— `build_auction_values.py`'s production constants were updated to match
and the static table/xlsx rebuilt.

**Two real bugs caught and fixed in the calibration tooling itself** (not
data/methodology issues — actual tooling bugs):
1. **Non-deterministic scoring.** `score()`'s top-N selection had no
   tiebreaker (`sorted(target_pos, key=lambda k: -target_pos[k])`), so
   Python's per-process hash randomization could pick a different "best"
   candidate across identical re-runs when players tied near the cutoff —
   caught because 14-team's QB=19 candidate scored RMSE 2.14 on one run and
   0.95 on another. Fixed by sorting on `(-target_pos[k], k)` (deterministic
   tiebreak on the name itself) in every affected script.
2. **Exponent search holding stale defaults instead of this-round's
   already-converged values.** Ad hoc widening tests used
   `dict(VORP_EXPONENT)` (the current PRODUCTION default, i.e. still the
   12-team numbers) as the "hold other positions constant" baseline while
   testing one position's exponent at a time for 14/16-team — not the
   values already converged earlier in that SAME calibration round. This
   let 14-team's first-pass RB/WR exponents look "optimal" on aggregate
   RMSE while badly overshooting individual players (Gibbs $68 vs. $56.6
   target, Chase $65 vs. $52.4 target) — the same "aggregate metric hides
   an individual miss" trap seen earlier in this project (see the Round 4
   QB22/TE26 story above), but this time from a genuine search-methodology
   flaw, not just an aggressive-fit tradeoff. Fixed by holding ALL 4
   positions' exponents in an explicit `baseline` dict, testing one at a
   time, updating `baseline[pos]` after each, and iterating 2 rounds to
   confirm convergence. Re-verified 12-team's already-accepted exponents
   with the same iterative method too — confirmed stable, no change needed.

**Recurring pattern, now documented directly in `build_auction_values.py`'s
constant comments**: several rank searches (12-team RB/WR/TE, 14-team's
first narrow pass, 16-team) initially returned the deepest or shallowest
candidate in the tested range as "best" — a signal the true optimum sits
outside the window, not that the edge value is actually correct. Always
re-test with a wider range when this happens.

### Live team-count switching architecture (`build_live_draft_workbook.py`)
Team count needed a fundamentally different mechanism than budget did.
Budget doesn't affect Weighted VORP at all (only the final $ conversion), so
it could be one live Excel formula covering any value continuously. Team
count changes `REPLACEMENT_RANK`/`VORP_EXPONENT` — real, market-calibrated
per-team-count values — which changes Weighted VORP itself. Re-deriving
that rank-cutoff logic as a Google-Sheets-style live formula would be far
more error-prone than Python, where it's already verified. So: **team count
is a discrete switch between 5 fully precomputed configurations, not a
continuous recalculation.**

- **`Setup!B5` (Number of Teams)** is now a real editable cell, restricted
  by `DataValidation` to a dropdown of exactly `8,10,12,14,16` — picking
  anything else isn't just unsupported, it would silently produce numbers
  with no calibration behind them, so the dropdown enforces it can't
  happen by construction, not just by convention.
- **Fixed row list, shared across all 5 configs.** Each position's board
  rows are the same players regardless of which team count is selected —
  Excel can't have a different number of rows appear/disappear based on a
  dropdown. The row list/sort order is determined using the DEEPEST
  calibrated team count (16, the one needing the most roster depth); every
  other team count's Weighted VORP/Tier for those same specific players is
  computed too, even for players who wouldn't have made THAT team count's
  own top-N cut on their own. `BOARD_DEPTH` scaled up from the original
  12-team-sized values (`{"QB":40,"RB":100,"WR":120,"TE":50}`) to
  `{"QB":55,"RB":140,"WR":165,"TE":70}` (roughly the 16/12 team ratio with
  a buffer) to comfortably cover 16-team's deeper roster requirement.
- **Per-player, 5 hidden Tier/Weighted-VORP column pairs** (one pair per
  calibrated team count), computed once in Python
  (`compute_all_team_counts()`, which just loops
  `build_teamcount_estimate.CALIBRATED`/`TEAM_COUNTS` and runs the full
  `compute_auction_values()` + `assign_position_tiers()` pipeline once per
  team count) and written as static values. Two live "Selected Tier" /
  "Selected Weighted VORP" columns then pick the active pair via
  `=CHOOSE(MATCH(Setup!$B$5,{8,10,12,14,16},0), col_8T, col_10T, col_12T,
  col_14T, col_16T)` — same CHOOSE/MATCH pattern used everywhere else this
  needed to switch (position rates, tier tables). Static Value and Live
  Value formulas read from the Selected columns, not any specific
  team-count column directly, so they automatically follow whichever
  config is active.
- **`Live Calc`'s POSITION RATES table**: Total Weighted VORP per position
  now also varies by team count (the board's own players have different
  Weighted VORP values under each config), so it's the same CHOOSE/MATCH
  pattern over 5 precomputed sums (written to a small side area of the same
  row, columns F-J) rather than a single fixed constant like the v1.2
  budget-only version had.
- **Per-position TIER tables**: row set is the UNION of tier values seen
  across ALL 5 team-count configs for that position's board players (not
  just the currently-active config), so the table has a row ready for
  whichever tier number the CHOOSE formula might select regardless of what
  Setup!B5 is currently set to.
- **`$ SETUP` block**: `Total Teams` now reads `=Setup!$B$5` directly (that
  cell IS the live value now, not a fixed label) — `Total Money`/
  `Total Discretionary`/`Total Roster Spots` all cascade from it exactly as
  budget already did, giving the "total dollar amount" the user asked for
  automatically as team count changes (verified: 8T→$1600, 10T→$2000,
  12T→$2400, 14T→$2800, 16T→$3200, all exact `teams × $200`).
- **`POSITION_BUDGET_SHARE` stays constant** across all team counts — this
  hypothesis was never contradicted by any of the 5 fresh calibrations;
  only `REPLACEMENT_RANK`/`VORP_EXPONENT` needed real per-team-count values.

**Verified via `verify_live_workbook.py`** (rewritten for the new 18-
column-wide block layout — 17 data columns + 1 spacer per position, up
from 7, to hold the 5 hidden team-count pairs): switched `Setup!B5` through
all 5 dropdown values, confirmed Total Money matched `teams × $200` exactly
every time, confirmed named players' Static Values changed sensibly at
each team count (e.g. Gibbs $56/$59/$59/$56/$57 across 8→16 teams — values
cluster in a plausible range rather than drifting monotonically, consistent
with the calibration not being a simple linear function of team count,
same non-linearity already seen in the Round 5 grid-search results
themselves). Confirmed budget still works independently of team count
(260/200 test at fixed 12 teams). Confirmed a live pick still ripples
correctly through the tier/global-factor mechanism unchanged (Gibbs
overpay to $100 pushed tier-mate Bijan Robinson's live value up
proportionally — same tier-factor mechanics as v1.2, untouched by this
round's changes). Confirmed 0 leftover filled Price cells both before and
after the verification run's own test picks.

**Separately verified the whole-draft depletion factor still works correctly
after this round's rebuild** (`test_global_depletion.py`) — this round
changed how each position's Total Weighted VORP feeds `Live Calc`'s GLOBAL
block (now a CHOOSE/MATCH lookup instead of a fixed constant), so the
mechanism that makes "money running out across the WHOLE draft" pull down
prices in positions nobody has even touched needed its own re-check, not
just an assumption that an unchanged-looking formula pattern still works.
First pass gave a confusing result (an untouched RB with picks made
elsewhere in its OWN tier rose in price during a broad "hot market" test)
until isolating the two signals properly: with RB held at zero picks (so
its own tier factors stay neutral at 1.0), a broad overpay run across
QB/WR/TE alone dropped the global depletion factor to 0.935 and correctly
pulled Jahmyr Gibbs from $59 static down to $55 live — a position with zero
of its own picks, moved purely by the rest of the draft's money running out
faster than expected. Opposite direction (broad underpay) correctly pushed
prices up; drafting everyone at exactly static value kept the factor within
~1% of 1.0 (rounding noise, same as documented in v1.2). Confirms the
global mechanism is independent of the local tier mechanism and both
survived this round's architecture change intact.

**Known loose end, not yet cleaned up**: `calibrate_teamcount.py`'s own
module-level `RANK_CANDIDATES`/`EXPONENT_CANDIDATES` dicts were not updated
to the wider ranges discovered via ad hoc widening during this round's
calibration work (all widening was done through separate one-off `python
-c` snippets, not by editing this file). Re-running
`python calibrate_teamcount.py <N>` directly could hit the same
edge-of-range issue described above for a team count that needs
recalibrating again later — widen the candidate lists first if that
happens, don't trust the file's current defaults blindly.

## Round 6: scoring format (STD/PPR) added to team-count switching (v1.4)
User's request, once the team-count round shipped: "I would like to get
the initial values on my site too... this being a bit dynamic due to
number of teams, total money available" — but before designing a site
publish pipeline, the user correctly flagged that the site would also need
STD and full-PPR versions eventually (this project only ever had
half-PPR), which meant deciding the Sheets/site structure ahead of that
would be designing around a guess. So: build STD/PPR calibration into the
Excel tool first (which already had the team-count-switching architecture
to extend), figure out the true size of the site's matrix once real
values exist, THEN design publishing. Site publishing itself is still
parked, pending that.

**TE STD prerequisite**: `ff_draft_proj`'s consensus projections only had
Half-PPR/PPR/"TE Premium" for TE (STD was deliberately swapped out
originally to match the live sheet's then-current layout, not an
oversight) — RB/WR already had all 3 formats. Added TE's STD column
(`ff_draft_proj/build_consensus.py`, reuses `scoring.std_points()`
identically to RB/WR — a 2-line change), appended as the LAST column so no
existing column shifted position on the live Google Sheet. Verified safe
against every downstream consumer of `consensus_te.csv`
(`ff_rankings/scoring_adjust.py`, `ff_cheatsheet`'s two updater scripts,
`ff_sfb16/workbook_common.py`) — all read by column name
(`csv.DictReader`/`pandas`), none positionally. See `ff_draft_proj/CLAUDE.md`
for the full account.

### Calibration: 10 new (teams, format) combinations
User pulled the FULL grid unprompted — all 5 team counts x STD/PPR x 3
sources (30 new `reference_<source>_<teams>team_<std|ppr>.csv` files,
matching the existing half-PPR naming with a format suffix added), not
just the 12-team-first pass that was originally scoped. `POINTS_COL`
became `POINTS_COL_BY_FORMAT` (`std`/`half_ppr`/`ppr`, keyed the same as
before for backward compat — every other script imports `POINTS_COL` only
as a stand-in for "the 4 position keys," so nothing else needed to
change), `load_projections()` gained an `fmt=` parameter, and
`compute_auction_values()` gained a `budget_share=` override (mirroring
the existing `ranks`/`exponents`/`teams` overrides) — needed because,
unlike team count, real market data shows `POSITION_BUDGET_SHARE`
genuinely DOES shift by scoring format (STD real budget share ran
44-50% RB / 37-43% WR across all 5 team counts vs. half-PPR's ~43/43;
PPR flipped it to 40-44% RB / 43-47% WR) — exactly the well-known
real-world "PPR favors pass-catchers" pattern, not noise, confirmed by
being directionally consistent across every team count within a format.

**Real bug caught before trusting any of this** (same discipline as every
prior round — individual-player verification before the aggregate metric):
the first calibration pass's rank/exponent grid search used the OLD
half-PPR `POSITION_BUDGET_SHARE` default the whole time — a `budget_share`
override parameter had just been added to `compute_auction_values()`, but
the search loop never actually passed it in; a separate function measured
the real per-format share and only printed it for reference afterward.
Since `budget_share` directly scales a position's total dollar pool,
calibrating rank/exponent against the WRONG pool size let the exponent
search silently over-concentrate value at the top to hit the top-12 target
despite too little money — then applying the correct, larger budget share
afterward overshot for real: Jahmyr Gibbs $67 / Bijan Robinson $66 at
12-team STD vs. $56-61 / $53-63 real (a $10+ miss on the two most-scrutinized
RBs in the whole project). Fixed by computing the format-level budget share
FIRST (`FORMAT_BUDGET_SHARE` in `calibrate_teamcount.py` — the average of
the real per-team-count measurement across all 5 team counts within a
format, mirroring how half-PPR's single constant was derived) and using it
CONSISTENTLY through the entire search, not just for reporting. Re-verified
after the fix: same two players landed at $61/$61 — squarely inside the
real FantasyPros/4for4/Draft-Sharks spread, not blown out past it.

**`calibrate_teamcount.py`'s candidate ranges were also widened** (rank/
exponent both, all 4 positions) — this file previously carried the same
"never actually widened past the original team-count-only search" gap
flagged as a known loose end after Round 5. Every one of the 10 new
combinations hit at least one edge-of-range warning on a first pass at the
old ranges (16-team STD WR replacement rank eventually needed 90, nearly
2.5x the original 12-team half-PPR value of 64) — each was re-tested wider
until the "best" candidate was no longer sitting at the tested edge, using
a warning the script now prints automatically instead of requiring manual
inspection of every result.

**Final validated constants** for all 10 new (teams, format) combinations
live in `build_teamcount_estimate.py`'s `CALIBRATED` dict, now keyed by
`(teams, format)` tuples (15 entries total) instead of just `teams` —
`FORMATS = ["std", "half_ppr", "ppr"]`. Each entry also carries its own
`budget_share` now (previously a single shared module constant) since that
value is format-, not team-count-, dependent.

### Excel: Scoring Format becomes a third live dropdown (v1.4)
Same reasoning as team count originally: a player's Weighted VORP depends
on scoring format (both the underlying POINTS and the calibrated
rank/exponent/budget-share all change), so format is a discrete switch
between precomputed configurations, not a continuous formula — same as
team count, and for the same reason (re-deriving replacement-rank logic
live in Excel would be far more error-prone than keeping it in Python).

**Architecture generalized from a 1-key to a 2-key CHOOSE lookup.** Every
player now carries 15 hidden Tier/Weighted-VORP pairs (one per
`(format, teams)` combination, `CONFIG_KEYS = [(fmt, teams) for fmt in
FORMATS for teams in TEAM_COUNTS]`) instead of 5. A single flattened
`CHOOSE` picks among all 15 using one computed index:
`MATCH(Setup!Teams,{8,10,12,14,16},0) + (MATCH(Setup!Format,{labels},0)-1)*5`
— the team-count MATCH picks a position within a 5-wide block, the format
MATCH picks which block, avoiding a genuinely nested `CHOOSE(CHOOSE(...))`
formula. `Setup!B7` (Scoring Format) is a third restricted dropdown
(STD/Half-PPR/PPR display labels), alongside Teams (B5, unchanged) and
Budget (B3, unchanged, still a free continuous value).

**Fixed row list generalized too** — the union of each of the 15 configs'
own top-N (by that config's own Weighted VORP), not one reference config's
sort order. This matters in a way it didn't for team-count-only: within a
single scoring format, sort order among a position's players is provably
invariant to which team count or exponent is active (VORP = points minus a
constant, weighted_vorp = VORP^exponent — a monotonic transform for any
positive exponent, so relative order only depends on POINTS, never on
replacement level or exponent shape). But POINTS themselves genuinely
differ by scoring format (a pass-catching RB/WR ranks higher in PPR than
STD), so a single format's sort order isn't safe to reuse for the others.
Measured empirically: QB's union came out byte-identical to any single
config's own top-55 (QB has no format variation at all — same "Fantasy
Points" column regardless), while RB/WR/TE gained a handful of extra rows
(140→143, 165→167, 70→72) from format-driven reordering near the cut line.
`BOARD_DEPTH` bumped slightly to `{"QB":55,"RB":145,"WR":170,"TE":75}` to
comfortably clear the measured union with a small buffer. Sort key for
display purposes: the MAXIMUM weighted VORP any of the 15 configs assigns
a player (always defined for anyone in the union set, unlike anchoring to
one specific reference config that might not include them).

**`Live Calc`'s POSITION RATES table** also generalized: Discretionary $
is now a 3-way `CHOOSE` on Format alone (budget share doesn't vary by team
count), Total Weighted VORP is the same 15-way `CHOOSE` pattern as Draft
Board's Selected columns. Per-position TIER tables' row set is the union
of tier values across all 15 configs, same reasoning as before, just more
configs to union over.

**Verified via `verify_live_workbook.py`** (rewritten for the new 38-
column-wide block layout — 37 data columns + 1 spacer per position, up
from 17): switched through all 15 `(format, teams)` combinations,
confirmed Total Money matched `teams × $200` exactly every single time (no
exceptions). Spot-checked named players across format/team-count corners
(8T/16T x STD/PPR, plus 12T for all 3 formats) — every value matched the
direct Python calibration output exactly, e.g. 12-team STD Gibbs $61
identical to the terminal verification run. Confirmed PPR correctly raises
WR/pass-catching-TE values vs. STD at matched team counts (Nacua
$50→$58, McBride $20→$25 at 8 teams) — the expected real-world direction,
not just a plausible-looking number. Confirmed budget still works
independently of both dropdowns (260/200 test at fixed 12T/Half-PPR), and
a live pick still ripples through the tier/global-factor mechanism
unchanged. Confirmed 0 leftover filled Price cells both before and after
the verification run's own test picks.

**Third bug caught, this time by the user asking a clarifying question
before agreeing to commit** (not by this project's own verification
discipline — worth being honest about that): `PERSONAL_RANKINGS` was a
single hardcoded path to `joe_bond_half_ppr.csv`, and `load_personal_ranks()`
took no format argument — every STD/PPR calibration run above was blending
STD/PPR projected points against the user's HALF-PPR personal rankings the
whole time. This wasn't a hypothetical concern: the user has three genuinely
different personal-rank files (`joe_bond_standard.csv`/`_half_ppr.csv`/
`_ppr.csv`, confirmed by spot-checking — e.g. the half-PPR/PPR files rank
Bijan Robinson #1 RB while the standard file ranks Jahmyr Gibbs #1 RB
instead), reflecting real format-specific preference differences, not
copies of one file. Fixed: `PERSONAL_RANKINGS_BY_FORMAT` dict, `load_personal_ranks(fmt=)`
parameter, updated every caller that needed to pass the right format
(`calibrate_teamcount.py`, `build_teamcount_estimate.py`,
`build_live_draft_workbook.py`'s `compute_all_configs()` — moved the
personal-rank load inside the per-format loop instead of once outside it).
Re-ran all 10 STD/PPR calibrations against the corrected blend — drift was
real but modest (e.g. 10-team STD RB rank 40→36, 16-team STD TE exponent
0.9→0.8), consistent with `NUDGE_WEIGHT=0.4` being a damped blend rather
than a full override; `FORMAT_BUDGET_SHARE` was completely unaffected
(it's measured from real market $ data alone, with no personal-rank
involvement at all). Re-verified individually and rebuilt/re-verified the
Excel workbook end to end again — all 15 combos still landed within the
real reference spread and Total Money still matched `teams × $200` exactly
throughout.

**Lesson**: this project's calibration discipline (individual-player
verification, deterministic scoring, edge-of-range checks) is good at
catching problems INSIDE the search/scoring math itself, but doesn't catch
a wrong INPUT feeding a technically-correct search — the STD/PPR
calibration numbers all looked plausible and landed near the real
reference spread even with the wrong personal-rank file, because the
personal-rank nudge is a modest, damped signal on top of real market-
calibrated projections, not the dominant one. A wrong input that still
produces plausible-looking output is exactly the kind of bug that
verification-by-spot-check can miss — this one only surfaced because the
user asked a direct clarifying question ("this will use the correct
rankings to blend for the scoring formats right?") before agreeing to
commit, not because any built-in check caught it.

**Still open / not done this round**: the site-publishing pipeline (Google
Sheets structure, whether budget becomes a real client-side calculator or
stays a few fixed reference points) — deliberately parked until the full
STD/PPR matrix existed to design against, per the user's own instinct.
`calibrate_teamcount.py`'s `RANK_CANDIDATES`/`EXPONENT_CANDIDATES` are now
wide enough to have covered all 10 new combinations without a manual
re-widen, but there's no guarantee they're wide enough forever — the
edge-of-range warning is now automatic, but widening on demand is still a
manual step when it fires.

## Round 7: roster configuration
User's request: let people type in their own starter counts (QB/RB/WR/TE,
multiple flex types including superflex/QB-RB-WR-TE, bench, DEF/K) rather
than being limited to this project's one fixed roster shape. Explicitly
free-form, not a short curated dropdown list like team count/format —
which matters architecturally, since real-market calibration (the
approach used for every dimension so far) can't cover an effectively
infinite input space the way it could cover 5 team counts or 3 formats.

**Fourth bug found, this time surfaced by the user while scoping the new
feature, not by this project's own checks**: while confirming what roster
shape to validate the new feature against, the user clarified their real
roster is QB1/RB2/**WR3**/TE1/FLEX(RB-WR-TE)1/DEF1/K1/6-bench (16 roster
spots/team) — but `STARTERS["WR"]` had been `2`, not `3`, since the very
first round of this entire project. Every reference pull ever calibrated
against (all 15 team-count/format combinations, going back to the original
12-team baseline) was real data for a 3-WR-starter league; the constant
just mislabeled it. Impact confirmed to be narrow: `REPLACEMENT_RANK`/
`VORP_EXPONENT`/`POSITION_BUDGET_SHARE` are fit directly against real $
data by grid search, not derived from `STARTERS`, so those calibrated
values were unaffected. The only real input `STARTERS` feeds is
`TOTAL_ROSTER_SPOTS_PER_TEAM`, which drives the discretionary-money $1-
floor deduction — off by 1 spot/team (15 vs. the correct 16), a ~0.5%
shift in the discretionary pool (12-team: $2220 -> $2208). Re-ran the
calibration search at 3 representative combinations (12-team half-PPR,
12-team STD, 16-team PPR) against the corrected pool to confirm the
optimal rank/exponent candidates didn't move — they didn't (identical
results both before and after) — so this was a constant fix + rebuild, not
a full recalibration. `STARTERS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}` is
now correct; rebuilt and re-verified `live_draft_board.xlsx` and the
static table against it.

**Plan for the free-form feature itself** (not yet built — this section
will grow as the work proceeds):
1. A formula-based estimate for arbitrary roster shapes — a Harstad-style
   "required starts" model (`teams x (starters_at_position +
   flex_share_at_position x flex_slots)`, adjusted for the real bye/injury
   depth factor already implicit in the calibrated baseline), with the
   flex-demand split across RB/WR/TE derived by working backward from the
   now-corrected, real-calibrated 12-team baseline — a principled anchor,
   not an arbitrary assumption. Same honesty convention as
   `build_teamcount_estimate.py`'s existing "UNVALIDATED math-only
   estimate" fallback for uncalibrated team counts: clearly flagged as an
   estimate for roster shapes without their own real calibration.
2. Superflex/2QB gets real calibration, not just the formula — real
   markets are known to push QB budget share to 25-35%+ (vs. this
   project's single-QB ~5-8%), the same "real bidding behavior, not
   derivable from roster math alone" category `POSITION_BUDGET_SHARE`
   already fell into for scoring format. User pulling real
   `reference_<source>_12team_superflex.csv` data (same 3 sources, 12
   teams, half-PPR, $200, same RB/WR/TE/flex/bench shape, QB slot ->
   superflex) to calibrate this properly.
3. Excel architecture still to be designed — unlike team count/format
   (discrete dropdown over a small calibrated set), the formula-based tier
   might be reproducible as a genuine live Excel formula (like Budget
   already is) rather than a precomputed lookup, since it's real math, not
   a market-calibrated constant — worth exploring once the formula itself
   is validated in Python first.

## Fifth bug: the Draft Sharks total-based rescale was silently erasing its own signal for QB/TE (affects everything calibrated before this fix)
Caught by the user directly questioning a superflex QB1 value ("Josh Allen
at $80 — that's way over what Draft Sharks and FantasyPros has him at")
— the single most consequential catch in this project's history, since
tracing it down revealed the bug wasn't specific to superflex.

**Mechanism**: `calibrate_teamcount.py`'s `build_target()` rescaled Draft
Sharks so its position TOTAL (on the FantasyPros-matched key set) equaled
FantasyPros' total, before averaging — `ds_scale = fp_total/ds_total`,
applied to every player's DS value. This rescale was originally built (much
earlier in the project) to fix a real, different problem: comparing
WHOLE-POOL totals conflated "DS values the top higher" with "DS just lists
~1000 players vs FantasyPros' ~150-200, so of course its raw total is
bigger." Restricting the total comparison to the matched-key set (done
years ago) fully fixed that specific problem on its own — but the rescale
kept being applied on top of the already-fixed comparison, and for QB/TE
specifically, `ds_scale` turned out to be nowhere near 1.0 even on the
matched set (QB: 0.47-0.52 in every half-PPR/STD/PPR combo, i.e. Draft
Sharks values the position's matched players at roughly 2x FantasyPros'
total; TE: 0.55-0.60). That's not a coverage artifact anymore — it's Draft
Sharks and FantasyPros genuinely disagreeing by ~2x about how much of the
budget QB/TE deserve. Forcing DS's total to match FP's before averaging
doesn't correct anything real at that point; it just silently overwrites
DS's independent opinion with FantasyPros', which then gets called a
"3-source blend" when it's effectively FantasyPros' opinion wearing a
DS-shaped hat.

**Why it wasn't caught by this project's own verification discipline**:
the regular 3-source blends (FP + 4for4 + DS-scaled) weren't visibly
broken in spot checks — 4for4 (never rescaled) anchors the average to a
sane range even when DS's contribution is distorted, and individual-player
checks kept landing "close enough" to the real spread. Superflex was the
first calibration to use a 2-source blend (FP + DS only — 4for4 excluded
for an unrelated, separately-verified data-quality reason, see above) —
with no 4for4 anchor, the same distortion had nothing masking it, and
produced a target ABOVE both raw sources ($81 vs. $54 FP / $75 DS,
mathematically impossible for a genuine average of the two to exceed both).
That's what made it visible enough for the user to catch on a single
glance at one player. **Lesson**: an aggregate-blend bug can hide behind
enough real signals even while actively corrupting one of them — reducing
the source count (as superflex did, for good reason) removed the camouflage,
it didn't introduce a new bug.

**Scope check before deciding whether to redo everything**: spot-checked
QB/TE production values (already-committed, from the 15-combo team-count/
format round) against raw FP/4for4/DS at a 20% tolerance — zero flags.
Confirmed empirically that the 4for4-anchoring effect really was masking
the bug rather than the bug not mattering. Measured the REAL shift the fix
produces: QB budget share rises ~20-30% relative in every combo (e.g.
half-PPR 5.9%→7.2% averaged across team counts), TE similarly (7.6%→8.9%)
— real and worth fixing properly, not within noise.

**Fix**: removed the per-position `ds_scale` rescale entirely from
`build_target()` (both `calibrate_teamcount.py`'s and
`calibrate_superflex.py`'s copies) — blend raw FantasyPros + 4for4 +
Draft-Sharks-Market values directly on the matched-key set. Re-ran the
FULL calibration (budget share, then rank, then exponent, in that order,
each depending on the last) for all 15 team-count/format combinations —
every one converged with no edge-of-range warnings. Re-verified
individually: Trey McBride now lands almost exactly on FantasyPros
($28 vs. $28 at 12-team half-PPR) — resolving a TE-undervaluation pattern
this project had accepted as "honest source disagreement" for multiple
prior rounds, when it was actually this bug suppressing Draft Sharks'
(correctly higher) TE opinion the whole time. Josh Allen and other QBs now
land properly centered between FP and DS instead of hugging FP/4for4's
level. Updated production constants (`build_auction_values.py`'s
`REPLACEMENT_RANK`/`VORP_EXPONENT`/`POSITION_BUDGET_SHARE`, all 15 entries
in `build_teamcount_estimate.py`'s `CALIBRATED` dict, `calibrate_teamcount.py`'s
`FORMAT_BUDGET_SHARE`), rebuilt the static table and `live_draft_board.xlsx`,
and re-ran the full end-to-end Excel verification — all 15 combos still
land on exact `teams × $200` totals, budget still independently live, tier/
global-factor live-draft mechanics unaffected.

**Superflex re-verified with the fix too**: Josh Allen now $63 (was the
broken $80), sitting properly between FP $54 and DS $75 instead of
exceeding both. Real superflex QB budget share corrected from the broken
37.7% down to **29.7%** — still a massive real premium (~4x single-QB's
~7%, matching known real-market superflex behavior), just no longer
artificially inflated by the bug. Final validated superflex numbers (not
yet wired into the live workbook — that's the roster-configuration
feature still in progress):
`ranks={"QB":26,"RB":40,"WR":60,"TE":22}`,
`exponents={"QB":1.0,"RB":1.2,"WR":1.3,"TE":1.0}`,
`budget_share={"QB":0.2971,"RB":0.2936,"WR":0.3306,"TE":0.0787}`.

## Round 7 completion: methodology defense, the 3-flex anchor, and a live-formula roster-shape architecture (v2)

### A methodology challenge, resolved with evidence rather than argument
Partway through this round the user pushed back hard on the whole
real-data-calibration approach, prompted by advice from Gemini describing
a pure VBD formula (find peak VBD, apply one $/point rate, let values
decrease naturally) as sufficient on its own. Rather than re-assert the
existing approach, ran the actual comparison with current players/
projections: pure VBD (no position split, no convexity, naive `teams x
starters` baseline) put the top overall player at **$93** of $200 — the
same $91-of-$200 problem from this project's very first round, reproduced
live with today's data, not old history. Every named player ($20-40 over
every real source) confirmed it wasn't a fluke. Followed up on two more
rounds of Gemini's specific suggested fixes (deepen the baseline; re-weight
QB/TE by a guessed multiplier; account for the flex spot with an assumed
60/40 WR/RB split): in each case the *direction* was right but the
*magnitude* was a real, measurable miss when checked against this
project's already-calibrated numbers (e.g. Gemini's guessed 1.3x QB
multiplier would have landed at 4.2% budget share against a real 7.2% —
a needed 2.25x, not 1.3x). The conclusion wasn't "trust me" — it was three
independently-checked, wrong-by-a-checkable-margin guesses, laid out
side by side with what real calibration produces. User accepted this and
asked to proceed.

### The 3-flex anchor: the user's actual league, and the second real data point needed
User pulled real reference data for their upcoming league (14-team, Full
PPR, 1QB/2RB/3WR/1TE/**3FLEX**) — `reference_<source>_14team_ppr_3flex.csv`.
4for4's tool has no genuine FLEX concept (confirmed: only raw
QB/RB/WR/TE-to-start number fields, which explains retroactively why its
earlier superflex attempt was broken — there was never a way to represent
QB-flex-eligibility in that tool at all) — but the user found their tool
accepts FRACTIONAL starter counts, and approximating 3 RB/WR/TE-flex spots
as weighted fractional additions (1QB, 3.2RB, 4.2WR, 1.6TE) produced
values landing plausibly between FantasyPros and Draft Sharks for every
player checked, unlike superflex's attempt (no fractional workaround
exists for flex-QB-eligibility, since it isn't "more of the same" the way
flex-RB/WR/TE volume is). Used all 3 sources. Calibrated
(`calibrate_3flex.py`, same methodology as every other round — real
budget share measured first, used consistently through the rank/exponent
search, individually verified against named players): `ranks=
{"QB":22,"RB":56,"WR":75,"TE":30}`, `exponents=
{"QB":1.2,"RB":1.15,"WR":1.2,"TE":1.1}`, `budget_share=
{"QB":6.0%,"RB":42.1%,"WR":42.8%,"TE":9.1%}`. QB rank landed at EXACTLY
22, identical to the existing 14-team/PPR/1-flex baseline — a clean
internal consistency check (QB isn't flex-eligible in this shape, so its
demand genuinely shouldn't move at all, and it didn't).

### `roster_formula.py`: the general model, with an honest split of what's trustworthy
Two fundamentally different treatments, because rank and budget-share/
exponent behave differently under roster changes:

- **`REPLACEMENT_RANK`**: a smooth "required demand" formula,
  `demand(pos) = starters[pos] + flex_share[pos] * flex_slots`, anchored to
  whichever (teams, fmt) is already real-calibrated.
  `FLEX_SHARE_STANDARD` (RB 0.182, WR 0.250, TE 0.083) is solved directly
  from the 1-flex vs. 3-flex comparison — QB correctly came out exactly 0
  (not flex-eligible in that shape), confirming the model isn't just
  curve-fitting noise. `FLEX_SHARE_SUPERFLEX` decomposes a QB-eligible
  flex slot into a QB portion (0.625, from the superflex vs. baseline
  comparison) and an RB/WR/TE remainder split using
  `FLEX_SHARE_STANDARD`'s own proportions — an ASSUMPTION, since the
  superflex rank data alone is confounded by budget share moving
  dramatically at the same time and can't isolate the RB/WR/TE split
  independently. `RB_WR`-only and `WR_TE`-only flex types (added per user
  request — real leagues use these) are derived by renormalizing
  `FLEX_SHARE_STANDARD` to exclude the ineligible position — no real
  reference data exists for either variant, always flagged "estimated."
- **`VORP_EXPONENT` / `POSITION_BUDGET_SHARE`**: NOT the same smooth
  formula — proven not to work that way (a naive demand-ratio model
  predicted superflex QB budget share at ~11.6%; real is 29.7%, a 2.5x
  miss). Uses a REGIME SWITCH instead: QB starters=1 and 0 superflex slots
  applies a LINEAR INTERPOLATION by RB/WR/TE-type flex count (see below);
  QB starters=2 OR >=1 superflex slot applies the real observed superflex
  shift (a per-position ratio measured once at 12-team/half-PPR) on top of
  whichever (teams, fmt) baseline is active — an extrapolation for any
  other (teams, fmt), flagged as such.

**Real bug caught by building the Excel version and checking real numbers,
not by the Python self-tests alone**: an earlier version of this file flat-
held exponent/budget_share at the (teams, fmt) baseline for ALL non-
superflex roster changes, on the reasoning that budget share only drifted
1-2 points between 1-flex and 3-flex (true — tested directly). But
exponent was never separately tested, and it turns out TE's exponent
shifts a full **0.85 -> 1.10** between 1-flex and 3-flex — a real, meaningful
move that a flat hold missed entirely. First version of the live workbook
landed $5-6 off the real 3-flex calibration (Gibbs $49 vs. real $54,
McBride $19 vs. real $24) specifically because of this. Fixed by replacing
the flat hold with a LINEAR INTERPOLATION by flex count
(`EXPONENT_SLOPE_PER_FLEX` / `BUDGET_SHARE_SLOPE_PER_FLEX`), fit through
the two real anchors (1-flex, 3-flex) — only valid for RB/WR/TE-type flex
(the only type with two real data points at different flex counts); an
`RB_WR`/`WR_TE` flex still flat-holds, since no flex-count-varying data
exists for either. After the fix, 3-flex landed at $53/$49/$23/$24 vs. the
real $54/$49/$23/$24 — 3 of 4 exact, 1 off by $1 (rounding noise, not the
same systematic gap). **Lesson, consistent with this whole project**:
"verified stable" for one parameter (budget share) doesn't imply another
(exponent) is also stable — each needs its own check, not inherited
confidence.

### Excel v2: a live formula, not a bigger precomputed lookup, and why that got SIMPLER not more complex
Team count and scoring format (15 real combinations total) precompute
Weighted VORP for all 15 and let Excel pick among them — feasible because
the combination count is small and every combination has real data.
Roster shape has hundreds of theoretical combinations, most without real
data, so v1.4's "precompute every combo" pattern doesn't extend here.

Instead: raw player points (3 columns, one per scoring format) sit
directly in the sheet, and `LARGE(range, k)` — a single native Excel
function returning "the k-th largest value" — replaces the need for any
custom rank-to-points interpolation formula. This is what makes a live
version of Harstad-style replacement-level lookup safe to build at all:
no array/dynamic-array construct (the category that corrupted a file
outright earlier in this project — see the "Big Board" postmortem, v1
section). `replacement_points(pos) = LARGE(that position's Selected
Points column, adjusted_rank(pos))`, `weighted_vorp(player) = MAX(0,
player_points - replacement_points) ^ exponent(pos)` — both computed live,
per player, from Setup's roster inputs. Net result: the Draft Board block
went from 37 columns (v1.4, precomputed per 15 configs) down to **11**
(v2) — genuinely simpler, not just more flexible, because nothing needs
precomputing anymore except the 15 (teams, fmt) baseline anchors
themselves (now living in `Live Calc` as a small reference table, not
per-player hidden columns).

**Tier is simplified, a real and disclosed downgrade**: the natural-gap-
detection algorithm (`tiers.py`) can't be replicated as a live formula
without the same array-formula risk. Replaced with fixed-width RANK bands
(every 5 players by Weighted VORP = one tier) — still gives localized
live re-rating (a hot pick moves its own band, not the whole position),
just with mechanically fixed band sizes instead of detected natural
breaks.

**Setup sheet gains a full Roster Shape section**: QB/RB/WR/TE Starters
(bounded dropdowns matching the user's specified range), Flex Type
(RB/WR/TE, RB/WR, WR/TE — a dropdown, applies to the "Flex Count" slots),
Flex Count (0-6), Superflex Count (0-2, always QB/RB/WR/TE-eligible,
mixable with a same-league standard flex per the user's explicit ask —
"that flex or one of them changes to a superflex spot, not all of them"),
DEF/K/Bench (free — mechanical only, no calibration dependency). `My
Team`'s roster-slot list is now formula-driven from these live inputs
instead of a fixed constant list.

**Real bug caught during Excel verification, not Python testing**: the
Tier formula (`RANK.EQ`) showed `#NAME?` on every single row immediately
after file open, even with zero picks made — traced by checking the exact
win32com error code (`-2146826259`) against known Excel error constants,
not guessed. Root cause: `RANK.EQ` is an Excel 2010+ function, and
openpyxl writes formula strings directly into the XLSX XML without adding
the `_xlfn.` prefix Excel's own UI silently adds when a formula is typed
normally — so a formula typed live via COM (which goes through Excel's
own formula parser) evaluated fine, while the byte-identical text written
by openpyxl to the file failed on open. Confirmed the diagnosis was right
before applying the fix (reproduced `#NAME?`'s exact error code with a
deliberately-unknown function name, matched it byte-for-byte against the
broken cells) rather than guessing. Fixed by writing `_xlfn.RANK.EQ`
instead of `RANK.EQ`; checked every other function used in the workbook
against the Excel-2010-cutoff list and confirmed none of the others
(`SUMIFS`/`COUNTIFS`/`IFERROR`/`MATCH`/`INDEX`/`CHOOSE`/`LARGE`/etc., all
2007-or-earlier) needed the same treatment.

**Final verification, after both fixes**: zero formula errors across the
entire Draft Board (every position, every row — not just a sample).
Baseline (12-team/half-PPR/standard roster) reproduces the production
static table exactly (Gibbs $58, Nacua $52, Allen $36, McBride $28).
3-flex reproduces the real calibration within $1 (3 of 4 exact). Superflex
reproduces Josh Allen's real calibrated value exactly ($63). QB
Starters=2 correctly triggers the same regime switch as Superflex Count
but produces a genuinely different number ($35 vs. $63) since 2 mandatory
starters create more replacement-level depth demand than 1 optional
superflex slot even under the same budget-share treatment — a sensible,
not coincidental, distinction. Budget independence, live-pick tier
ripple mechanics, and `My Team`'s live roster-slot labels all confirmed
still working after the full rewrite.

### Round 7 extension: 0/1 for every position, and independent multi-flex-type counts
User's follow-up ask, after seeing the first version: allow 0 (and 1) as
options for every starter position, and support MULTIPLE flex types
active simultaneously in the same league (e.g. 1 RB/WR + 1 WR/TE + 1
Superflex all at once — "that flex or one of them changes to a superflex
spot, not all of them"), matching the user's own cheat sheet convention
of one independent count per flex type rather than a single type-selector.

**Setup redesigned**: QB/RB/WR/TE Starters dropdowns now all include 0
(RB/WR/TE previously started at 1 or 2, WR at 2). The single "Flex Type +
Flex Count" pair was replaced with FOUR independent counts — "Flex:
RB/WR/TE", "Flex: RB/WR", "Flex: WR/TE", "Superflex" — each 0-6,
combinable freely. `roster_formula.py`'s `_demand()` already summed over
an arbitrary list of (flex_type, count) pairs from the start, so the
Python model needed no changes; only the Excel side (which previously
used a single CHOOSE/MATCH on one type-selector cell) needed rebuilding to
sum four independent Setup cells directly — actually simpler than before,
since each flex type's own constant share can be multiplied directly
against its own dedicated cell with no lookup needed at all.

**Two real bugs found while testing the wider input range, both from
positions with very little configured demand — not from the mainstream
range this project has mostly tested**:

1. **A leftover Excel process from earlier automation held a file lock**,
   causing a `PermissionError` on rebuild. Not a workbook bug, but worth
   recording the resolution: enumerating the Running Object Table
   (`pythoncom.GetRunningObjectTable()`) confirmed both stray processes
   had only `live_draft_board.xlsx` open (one via the OneDrive path, one
   an Excel-generated temp "Copy of..." artifact) — consistent with
   leftover COM automation, not a user's own window — closed via
   `GetActiveObject` + `Workbook.Close()`, not a force process kill.

2. **A real, reproducible calculation bug**: configuring a position with
   very little real demand (confirmed case: TE Starters=0, only 1 RB/WR/TE
   flex slot active, everything else at baseline) produced a wildly wrong
   value ($198) for the position's top player instead of a sensible
   near-$1 floor. Root cause: `Total Weighted VORP` for that position
   collapsed to 1.89 (a healthy position's pool runs in the hundreds to
   thousands), and dividing a real discretionary-$ amount by a
   near-empty pool produced an absurd rate (104) that then multiplied out
   to $198 for the one player with any nonzero weighted VORP. An earlier,
   narrower guard (`IF(TotalWeightedVORP<1,...)`) didn't catch this
   specific case (1.89 > 1) — widened to a threshold of 20, comfortably
   below every real baseline pool size measured in this project, still
   comfortably above what a genuinely-degenerate pool produces.
   **Caught by disciplined re-testing, not the first pass**: an initial
   "clean" isolated test of this exact scenario showed a DIFFERENT,
   plausible-looking number ($96) that masked the bug — traced to cross-
   script Setup-state leakage (the same well-documented win32com
   `Close(SaveChanges=False)` flakiness this project has hit multiple
   times before, see `My Team` sheet history above — this time affecting
   Setup inputs, not just Draft Board price cells). Only became visible
   once every test case ran inside a single continuous Excel session with
   an explicit, complete reset between each one — the standing lesson
   ("always rebuild fresh and confirm state before trusting a
   verification pass") applies to Setup state now too, not just leftover
   price entries.

**Final re-verification after both fixes**, all within one continuous,
fully-reset session: baseline, 3-flex, superflex, and a 4-simultaneous-
flex-type test all still land exactly where they did before; the
reproducible degenerate-TE case now correctly floors to $1 instead of
spiking to $198; zero formula errors across every test; budget
independence, live-pick ripple mechanics, and zero leftover price cells
all confirmed clean.

## Round 8: unbounded tier/global re-rating (real bug, found through actual use)

The user found this by hand-testing the finished v2 workbook (not through
any of this project's own scripted tests), reporting two symptoms: (1) a
modest $3 overpay for Ashton Jeanty appeared to lower Jahmyr Gibbs's live
value, and (2) giving a $1-static player a $5 winning bid pushed "the rest
of the $1 players in his tier" to $5 too.

**Investigation discipline**: rather than theorize from the formulas alone,
reproduced both scenarios directly against a scratch copy of the real
workbook via win32com (never touched the user's own open Excel session —
it was live, mid-test, on their machine; attaching to or closing someone
else's in-progress session is not a reasonable move even read-only, so a
fresh copy was used instead).

**Bug 2 (tier blowup) confirmed and root-caused, worse than reported.**
`TIER_BAND_SIZE=5` fixed-width bands don't account for value composition —
directly measured: roughly two-thirds of a 160+-deep RB board sits at the
$1 static-value floor (107 of 161 rows in the test file), so any
tier straddling that floor mixes near-zero-differentiation players with
slightly-better ones. Real example: one 5-player RB tier held statics
$4/$3/$2/$2/$1. Giving the $1 player (Braelon Allen) a $5 winning bid
produced `tier_factor = SUM(price)/SUM(static) = 5/1 = 5.0`, applied
uniformly to the whole tier — the $4 player (Brian Robinson Jr.) jumped to
$20, not just the other $1 players moving to $5 as the user described (the
actual effect was broader than what was visible/reported).

**Bug 1 (Jeanty -> Gibbs) not reproducible in isolation.** Directly tested:
Jeanty and Gibbs sit in different tiers (confirmed via the Tier column —
RANK.EQ-based tier assignment depends only on points, never on draft
state, so it can't drift once Setup is fixed), so the tier mechanism
cannot connect them. The only channel that touches every undrafted player
at once is the whole-draft global depletion factor, and that was measured
to need a huge single-pick overpay (~$150-200 over static) to move Gibbs
by even $1 — a lone $3 overpay produced zero visible change in every
tested configuration (isolated, after 55 fair-value picks, and under the
user's real 14-team/PPR/3-flex league shape). Most likely explanation:
what the user saw was the *cumulative* global depletion effect of a real
draft session (many picks, not just one) crossing a rounding threshold
right after the Jeanty entry — a real, working-as-intended signal, just
surprising when attributed to the single most recent action. Not
independently confirmed, since reproducing a whole real draft session
wasn't practical, but the fix below adds a direct safety net against this
class of problem regardless of root cause.

**Fix**: clamp both multiplicative re-rating factors instead of leaving
them unbounded — `MEDIAN(lo, hi, raw_ratio)` in Excel is a clean two-sided
clamp (verified: `MEDIAN(0.5, 2, 5) = 2`, `MEDIAN(0.5, 2, 0.1) = 0.5`,
`MEDIAN(0.5, 2, 1) = 1`). `TIER_FACTOR_MIN/MAX = 0.5/2.0`,
`GLOBAL_FACTOR_MIN/MAX = 0.7/1.3` (build_live_draft_workbook.py). Bounds
were chosen, then verified, against real measurements: normal fair-value
drafting keeps both factors at/near 1.0 (untouched by the cap), a wild
single-player $200 overpay (previously measured at global factor 0.9275)
stays comfortably inside the cap, and a deliberately extreme test
(15 RBs each overpaid to 3x-static+$20) drove the *uncapped* ratio down to
0.121 (an 88% board-wide crash) — the capped version correctly held at the
0.7 floor. Post-fix, the original bug-2 repro (Braelon Allen $1->$5) now
moves tier-mates from $1 to $2 (capped at 2.0x) instead of $1 to $5, and
the $4 player moves to $8 instead of $20 — still a real, visible signal,
no longer an unbounded blowup.

**Not fixed / accepted as-is**: tier granularity itself (`TIER_BAND_SIZE=5`)
was left unchanged. Reasoned through, not just assumed: even perfect
natural-gap-detection tiering (the pre-v2 `tiers.py` approach) would still
group large numbers of near-replacement players into one tier, since
there's genuinely no differentiation to detect that deep — the instability
was about unbounded *magnitude*, not tier *boundaries*, so the clamp
directly addresses the actual mechanism rather than working around it via
finer-grained tiers.

**Follow-up from the user, same round: the cap wasn't enough.** Pushback,
verbatim reasoning: "I'm not even sure the $3 player should move to $5,
even if somebody in their tier was overpaid for... maybe wait for 2+
players in a tier to get bid on before changing the overall market value
of players around them." Correct instinct — even bounded, one drafted
player is one bidder's opinion on one specific player, not evidence about
the tier as a whole, and the $4/$3/$2/$2/$1 example above shows
`TIER_BAND_SIZE=5` doesn't guarantee tier-mates are actually similar in
value. Fixed by requiring a minimum sample: `tier_factor` now stays at
exactly 1.0 (no re-rating at all) until `TIER_MIN_SAMPLE=2` players in that
tier have been drafted, added as a `Drafted Count` column in each
position's Live Calc tier table, gating the (still-clamped) ratio.
Verified on the real file: a single $1->$5 bid now leaves every tier-mate
exactly at their static value; drafting a *second* player in the same tier
(a $4 real overpay on a $3-static player) then correctly moves the
remaining tier-mates a modest amount ($1 static -> $2 live), showing the
gate opens as intended once there's an actual second data point.

## Round 8 extension: Setup/Draft Board formatting and renaming

Also from direct use of the finished file, three formatting requests, all
implemented in `build_live_draft_workbook.py`:

- **Setup sheet now reads as an actual input table**: every configurable
  `[Label | Value]` row gets a thin box border (`Border`/`Side`, gray
  `B0B0B0`) via a new `input_row()` helper that consolidated what used to
  be repeated per-section code; the value column narrowed from width 20 to
  10 (was sized for nothing in particular, held 1-2 digit numbers or short
  format labels); the value cells got centered horizontal alignment. The
  long italic methodology paragraph previously merged across the bottom of
  the sheet was removed at the user's request — that reasoning now lives
  only in CLAUDE.md, not duplicated in the workbook.
- **Draft Board column renames**: `Selected Points` -> `Proj Pts`,
  `Static Value ($)` -> `Starting Value`, `Price Paid ($)` -> `Price Paid`,
  `Live Value ($)` -> `Market Value`. User offered two name choices for two
  of these and asked for a recommendation; picked `Starting Value` over
  `Proj Value` (pairs with `Market Value` as its live-adjusted counterpart,
  avoids redundancy with `Proj Pts` sitting right next to it) and
  `Price Paid` over `Win Bid` (clearer at a glance; length stopped
  mattering once headers wrap). Note: `Points (STD/Half-PPR/PPR)`, `Tier`,
  and `Weighted VORP` were already hidden columns before this round — the
  visible surface was already close to the user's requested 6-column list,
  this was a rename, not a restructuring.
- **Header row now wraps** (`Alignment(wrap_text=True, horizontal="center",
  vertical="bottom")`, row height 30) so multi-word headers like
  `Starting Value` don't force wide columns — let the visible column
  widths shrink (Player 22->18, Team 7->6, Proj Pts 11->8, Starting
  Value/Price Paid/Market Value 12-13->9 each) so more of the position
  block fits on screen at once, the user's stated goal ("so we can see all
  positions at once").

Rebuilt and reverified end-to-end after all of the above: zero formula
errors in Draft Board and Live Calc, headers read correctly, Setup borders/
width/centering confirmed via COM, tier-gate behavior reconfirmed on the
real (not scratch-copy) file, zero leftover price cells before save.

## Round 8 second extension: value-proportional tiers, factor dampening, sortable blocks

Three more pieces of user feedback on the same finished file, all correct
and all implemented in `build_live_draft_workbook.py`:

**1. Tier factor still moved low-value tiers too much.** User: "even if two
players are overpaid for in a $1 tier, I'm not sure the $3 player should
almost double... that value really shouldn't change much." Right call —
the `TIER_MIN_SAMPLE=2` gate from the first Round 8 fix stopped a *single*
bid from re-rating a tier, but once 2 bids landed, the same unbounded-in-
spirit ratio still applied. Added `TIER_DAMPEN_BUDGET_FRACTION = 0.10`:
each tier's factor is now scaled by `MIN(1, tier_avg_static /
(Setup!Budget * 0.10))` before the existing `[0.5, 2.0]` clamp — a tier
averaging $20+ (in a $200-budget league) gets the full signal, a tier
averaging a couple dollars gets almost none. Verified on the real file: in
a 129-player catch-all tier (avg static ~$1.3), overpaying the tier's two
highest-static members (+$4 each) moved *zero* of the other 127 members
even one whole dollar — the dampened effect is real but rounds away at
that value level, exactly the "shouldn't change much" behavior asked for.

**2. Tier boundaries didn't reflect real value gaps.** User, with a
specific example: "there is a 90 point VORP difference between Bijan and
CMC yet they are in the same tier... Tiers are likely smaller at the top
than the farther you go down the player list, make sense?" Verified the
90-point gap exactly (615.3 vs 525.4 WVORP) — correct diagnosis. Replaced
the fixed-5-player-band Tier formula entirely with a value-proportional
one: `Tier = CEILING(cumulative_share_of_position_WVORP, 5%) / 5%`, where
cumulative share is computed per-player via
`SUMIF(wvorp_range,">="&own_wvorp,wvorp_range)/total_wvorp` (no array
formula, same SUMIF-cumulative trick used elsewhere in this project).
Because cumulative share always runs 0->1 regardless of position depth or
Setup, tier count is always exactly `MAX_TIER = 1/TIER_VALUE_BAND = 20` --
fixed at Python build time, not data-dependent the way the old
`n_rows/TIER_BAND_SIZE` count was. Verified against real data before and
after: at 5% bands, Gibbs/Bijan/McCaffrey/Taylor/Cook each land in their
own separate tier (were previously all tier 1 together); the bottom of a
160-deep RB board collapses into one ~120-130-player catch-all tier, the
same shape the pre-Excel gap-detection tiering used to produce. One real
bug caught and fixed during verification: floating-point drift from the
CEILING/division math produced values like `3.0000000000000004` instead of
exactly `3`, which silently broke the Live Calc tier table's exact-match
`MATCH()` lookup (12 real `#N/A`-class errors on Draft Board, confirmed via
the same error-scanning check used throughout this project) — fixed by
wrapping the whole Tier formula in `ROUND(...,0)`.

**3. No way to sort a position block after switching scoring format.**
Real, independent bug report: switching `Setup!Format` changes each
player's `Proj Pts` live, but row order was fixed at Python build time
(sorted once by each player's max points across all 3 formats), so the
displayed order stops matching the newly-selected format's ranking. User
asked for a way to re-sort per position. Rather than rebuild rows on
format change (would need a volatile/array formula, the exact risk
category this project avoids after the "Big Board" postmortem), gave each
position its own Excel Table (`openpyxl.worksheet.table.Table`, name
`f"{pos}Board"`, `TableStyleLight1` with all banding/striping disabled so
it doesn't fight the existing per-position `POSITION_FILL` header colors)
-- a plain worksheet `AutoFilter` can't do this since Excel restricts it to
one range per sheet, but independent Tables have no such limit. This adds
native sort/filter dropdown buttons to each position's own header row,
scoped only to that block. Verified this is safe for a formula-heavy
sheet, not just assumed: sorted the RB block (161 rows) by Proj Pts inside
one continuous COM session and compared every player's Static Value, Tier,
and Live Value before vs. after -- zero mismatches, because every cross-
row formula in this workbook uses absolute whole-column ranges (`SUMIF`,
`SUMIFS`, `COUNTIFS` over `$col$2:$col$N`), which don't care what order
the rows are in, and same-row formulas move as a physical unit with the
row during a native Excel sort. Also confirmed the position color fills
survive the Table styling untouched (compared `.Interior.Color` byte-for-
byte against `POSITION_FILL` before/after, matched exactly for all 4
positions).

**Verification discipline note**: an early combined test script produced a
misleading "Jahmyr Gibbs's value changed after sorting" result -- traced
to two separate causes, neither a real bug: (a) the well-documented
win32com `Close(SaveChanges=False)` flakiness this project has hit several
times before (a fresh re-open showed stale state from a supposedly-
discarded prior session), fixed by always rebuilding fresh before a
verification pass rather than trusting a reopened file's state; and (b) a
plain off-by-one in the test script's own row-scan range (`range(2,162)`
excludes row 162, and Gibbs sorted to exactly that row). Re-tested cleanly
in one continuous session with the correct range: zero mismatches across
all 161 RB players.

Rebuilt and reverified end-to-end after all three fixes: zero formula
errors at default settings, at 14-team/PPR/3-flex, and after also adding
2-QB-starters + 1 superflex slot; zero leftover price cells; Setup reverted
to defaults before final save.

## Round 8 third extension: value-proportional tiers shipped with no tier 1

Shipped the value-proportional tier formula above, then the user caught a
real bug immediately by just looking at the sheet: "why is there no tier 1
in any position? these tiers went too far the other way" -- correct, and a
structural problem, not a rare edge case.

**Root cause**: the shipped formula was `Tier = CEILING(cum_share, band) /
band`, where `cum_share` included the player's own Weighted VORP (share of
value at-or-above them, inclusive). Diagnosed by computing the real number:
Jahmyr Gibbs alone is ~6.2% of the entire RB pool's total Weighted VORP --
already past one whole 5% band by himself. `CEILING(0.062, 0.05)/0.05 = 2`,
so the single most valuable player at a position always got pushed straight
to tier 2, and tier 1 was mathematically unreachable at every position,
every time. (A test script written during the earlier verification pass
had actually already shown this exact symptom -- an empty phantom "tier 1:
0 players" -- and it was wrongly dismissed as a cosmetic loop artifact
instead of investigated. Lesson: an unexplained empty bucket in a test
script's own output is a signal to chase, not wave off, even when the
headline numbers look right.)

**Fix**: switched to an *exclusive* share -- share of value strictly ABOVE
this player, i.e. subtract the player's own Weighted VORP before dividing --
and `FLOOR(...)+ 1` instead of `CEILING(...)`. The single most valuable
player then always has exactly 0% share above them, so tier 1 always
exists structurally, not just in the common case. Verified against real
data: Gibbs=1, Bijan=2, McCaffrey=3, Taylor=4, Cook=5 -- the original
per-player separation goal is preserved, now correctly starting at tier 1.

**Second bug caught during the SAME fix, before shipping this time**: the
exclusive-share formula has its own edge case -- every player at or below
replacement has Weighted VORP = 0, and `SUMIF(range,">="&0,range)` matches
everyone (nothing is ever negative), so `share_above` computes to exactly
`1.0`, not just-under-1. `FLOOR(1.0/0.05)+1 = 21`, one past `MAX_TIER=20`,
which has no row in the Live Calc tier table -- confirmed this produced
363 real `#N/A`-class errors on Draft Board (every below-replacement
player, all 4 positions) on the first rebuild after the fix. Fixed by
wrapping the result in `MIN(MAX_TIER, ...)`. Re-verified clean afterward:
zero formula errors at default settings, 14-team/PPR/3-flex, and with
2-QB-starters + 1 superflex added; tier 1 confirmed present and tier
range confirmed within `[1, MAX_TIER]` at all 4 positions; Setup reverted
to defaults before final save.

## Round 8 fifth extension: gap-detection tiers replace value-proportional bands entirely

The value-proportional bucket scheme above was still wrong at a design
level, and the user caught it precisely: "personally I would put Gibbs and
Bijan in the same tier. they are very close to each other. same with Puka
and Ja'Marr and McBride and Bowers" and, separately, "Why are there
missing tiers in QB, I would think it would also go in incremental order
no matter what the separation is." Both are the same root cause: a
boundary placed every fixed % of cumulative value has no relationship to
where the real gaps in the curve actually are.

**Replaced the whole mechanism with genuine nearest-neighbor gap
detection** in `build_live_draft_workbook.py`. `GAP_THRESHOLD = 0.08`
(8%) was chosen empirically, not guessed: tested 5/6/8/10/12% against real
Weighted VORP data until one cleanly matched every case the user named.
At 8%: Gibbs/Bijan (0.8% gap), Puka Nacua/Ja'Marr Chase, and Trey
McBride/Brock Bowers all land in the *same* tier; Bijan/McCaffrey (14.6%
gap) and Jonathan Taylor/James Cook (21.9% gap) correctly split apart —
exactly the pattern the user described.

New formula, computed with two new hidden Draft Board columns ("Row Num" —
a literal integer written once at Python build time, not a live formula —
and "Tier Start", a 0/1 flag):
```
Tier Start(i) = 1 if i is the canonical (lowest-Row-Num) player at its own
                Weighted VORP AND EITHER no one ranks above it OR the
                relative drop from the player immediately above exceeds
                GAP_THRESHOLD; else 0
Tier(i) = COUNTIFS(wvorp_range, ">="&own_wvorp, tier_start_range, 1)
```
Tier is a running *count* of gap-crossings, not a bucket-index computation,
so tier numbers are consecutive by construction — no skip is possible
regardless of how large any individual gap is. This structurally fixes the
QB complaint as a side effect of fixing the Gibbs/Bijan one; both were
never going to be independently patchable within the bucket-scheme design.

**Real bug caught before shipping this time (not after)**: the "canonical
representative" tie-break exists because `MINIFS(">"&own)` skips over
exactly-tied values (most commonly Weighted VORP = 0, at/below
replacement — confirmed 100+ tied players at zero on a 160-deep RB board)
to the next *distinct* value, so without picking one canonical
representative per tied group, every tied player would independently see
the same gap and each flag as its own tier start, fragmenting the intended
single catch-all tier into dozens. Handled by only running the gap check
for the player with the smallest Row Num among ties.

**Second real bug, caught the same way the RANK.EQ and MINIFS-adjacent
issues were caught before**: first rebuild after implementing this showed
998 formula errors, all `#NAME?` (`-2146826259`). Root cause: `MINIFS` is
an Excel 2019+ function, same class of issue as `RANK.EQ` earlier in this
project — openpyxl writes formula text directly into the XLSX XML without
adding the `_xlfn.` prefix Excel's own UI adds silently, so it shows
`#NAME?` on open. Fixed by prefixing every `MINIFS` call; re-verified zero
errors immediately after.

**Also fixed in this round**: default row order on load. Independent bug
report — switching `Setup!Format` changes each player's `Proj Pts` live,
but row order was fixed at Python build time using each player's *max*
points across all 3 formats, so it stopped matching the newly-selected
format's ranking. Since `DEFAULT_FORMAT` (Half-PPR) is what's selected on
load, `board_player_list()` now sorts each position's initial row order by
that format's own points specifically (falling back to the max-across-
formats value only for players who don't appear in that format's own top-N
depth cut). Verified: every position's default row order is descending by
`Proj Pts` on a fresh open.

**Verification discipline note, again**: after one clean verification pass
(zero errors, all 5 named pairs correct, tier table consecutive at all 4
positions, Table sort re-tested safe with the 2 new helper columns), a
final read-only re-open showed the RB block in the *wrong* (sorted, not
default) order — the same well-documented win32com `Close(SaveChanges=
False)` flakiness this project has hit repeatedly, this time apparently
persisting a sort-test's changes despite the explicit no-save close.
Rebuilt fresh from Python (which always starts from an empty Workbook, so
it can't inherit stale state) and did one final read-only check with zero
further modifications — confirmed clean. Standing lesson reinforced: don't
trust a reopened file's state, even your own just-closed one: rebuild
fresh before the verification that actually gets reported to the user.

## Round 8 sixth extension: cumulative tier-width cap

Immediately after the gap-detection tiers above shipped and tested clean,
the user found a real, legitimate follow-on issue by using the file: a
15-player RB tier spanned James Cook ($39) down to Cam Skattebo ($25) — a
56% swing — because every *individual* neighbor gap in that chain was
under GAP_THRESHOLD (8%), even though the *cumulative* range was wide.
Confirmed the exact gaps: Cook→Achane 0.7%, Achane→Jeanty 5.5%, ...,
Etienne→Skattebo 0.6% — no single link over 7.6%, but 15 links add up.
User: "not sure a max width cap is the right call here, but a 15 player
tier 3 that has a 50 proj point gap is quite large. What advice do you
have?"

Recommended and implemented a second, independent trigger: a tier also
splits wherever the cumulative range from its own top exceeds
`MAX_TIER_WIDTH`, even with no single big neighbor gap. Tested 20/25/30/
35% against the real Cook-Skattebo chain and confirmed none of the pairs
named earlier in this round were affected: **25%** split the chain into
Cook-Jacobs (406→318 Weighted VORP, 9 players) and Love-Skattebo
(301→258, 6 players) -- reasonably sized, and Gibbs/Bijan, Puka/Chase, and
McBride/Bowers all stayed together.

**Implementation required a real design decision to keep it non-recursive.**
A naive single-pass check ("is this player >25% below the ORIGINAL
gap-tier's top") would fragment the tail of a long chain into one-player
tiers, since every player past the first split point is independently
>25% below the original top. What's actually needed is *sequential*
behavior (each split resets the reference point for what follows), which
would normally require row-by-row recursion -- unsafe in this project's
Excel-formula-only approach. Solved without recursion by comparing
*width-bucket indices* instead of raw thresholds: `own_bucket =
FLOOR((gaptier_top - own_wvorp)/gaptier_top / MAX_TIER_WIDTH, 1)`, and a
split fires when `own_bucket <> prev_bucket` (the same computation for
whoever's ranked immediately above). Because bucket index is a smooth,
monotonically-increasing step function of value, comparing it to the
immediate neighbor's bucket reproduces correct sequential-split behavior
using only single-pass aggregations (`MINIFS`) -- verified by hand against
the real Cook-Skattebo numbers before implementing, and confirmed to match
exactly after.

Two new hidden Draft Board columns: "Gap Start" (the pure gap-only flag,
renamed from what was simply "Tier Start" before this round) and "Gap
Tier Top" (`MINIFS(wvorp_range, wvorp_range, ">="&own, gapstart_range, 1)`
-- the Weighted VORP of this player's own gap-tier starter; always
resolves correctly since gap-tier starters partition the position into
non-overlapping ranges). "Tier Start" now means the width-refined flag,
and "Tier" is the same cumulative-COUNTIFS pattern as before, just fed by
the refined flag instead of the gap-only one. Same canonical-tie handling
(smallest Row Num) applied to the width check too, since two exactly-tied
players compute identical own/prev buckets and would otherwise both
independently flag.

Verified end-to-end: zero formula errors at default settings, 14-team/
PPR/3-flex, and 2-QB-starters + 1 superflex; all 5 named pairs still
correct; tier numbers still consecutive with tier 1 present at every
position; Table sort re-confirmed safe (161 RB players, zero mismatches
in Static/Tier/Market Value before vs. after sorting) despite the larger
column layout. Rebuilt fresh from Python one final time before saving,
per the standing lesson above.

## Round 8 seventh extension: stale REPLACEMENT_RANK caught, 12-team/half-PPR baseline recalibrated

User question, testing the tier work above: "There should not be QB16+ all
with $1 values in a 12 team half-ppr setup." Investigated before touching
anything -- this isn't a tiering issue at all (tiers only affect how *live*
market data re-rates already-drafted-adjacent players; how many players
hit the $1 floor is purely `REPLACEMENT_RANK`, a calibrated constant with
no connection to `GAP_THRESHOLD`/`MAX_TIER_WIDTH`).

Re-ran the actual calibration script (`calibrate_teamcount.py 12
half_ppr`) against current reference data rather than trust the stored
constant, and it's genuinely stale -- the reference CSVs (FantasyPros/
4for4/Draft Sharks snapshots) drift over time as this project pulls from
live sources, and this hadn't been re-verified in a while:
```
                 stored    fresh RMSE-best    RMSE(stored)  RMSE(fresh)
QB rank            16           20               2.89          1.77
QB exponent        1.1          1.2                -             -
TE rank             20           24                -             -
WR exponent         1.2         1.25               -             -
RB (unchanged)      44/1.2       44/1.2            -             -
```

**User then re-raised this project's original, already-settled
methodology question**: "the baseline should be set by the number of
needed starters right? ... its not like there are undraftable players
past say QB16 or RB36 ... right?" This is exactly the "pure VBD" argument
tested and found wrong earlier in this project (see the Gemini-pure-VBD
discussion further up this file) -- rather than re-argue from memory,
pulled the actual current market $ data to show it directly: QB12 (pure
roster-math replacement, 12 teams x 1 starter) still commands real market
$5.70; RB36 (12 teams x (2 starters+flex)) still commands $7.70; RB50 is
still $3.70. Value doesn't actually thin to near-zero until QB23-26 /
well past RB50 -- real bidders pay for bench/bye-week/injury-insurance
depth that pure roster math has no way to represent, which is the whole
reason this project calibrates REPLACEMENT_RANK against real auction $
instead of computing it from roster math directly.

**Scope decision**: fixing this properly for all 15 team/format combos
plus superflex and 3-flex would mean re-pulling/re-verifying reference
data for every combo -- a much larger undertaking. User's question stayed
focused on the 12-team/half-PPR baseline being tested, so that's what got
fixed: `REPLACEMENT_RANK` (`build_auction_values.py`) QB 16->20, TE 20->24
(RB/WR ranks unchanged, confirming this is real per-position drift, not a
global artifact); `VORP_EXPONENT` QB 1.1->1.2, WR 1.2->1.25. Also updated
the matching hardcoded copy in `build_teamcount_estimate.py`'s
`CALIBRATED[(12, "half_ppr")]` entry, which doesn't auto-derive from the
production constants. **The other 14 combos + superflex + 3-flex are
still on their original calibration and may have the same kind of drift
-- not yet re-verified, flagged here for a future pass.**

Verified: `build_auction_values.py` standalone CLI run confirms the new
ranks/exponents (QB replacement 263.6pts, TE replacement 103.2pts) with
no errors; rebuilt live workbook shows QB16 now at $3 (previously
floored to $1 at that rank) with real value continuing through ~QB18;
zero formula errors at default settings, 14-team/PPR/3-flex, and 2-QB/
superflex; zero leftover price cells; rebuilt fresh from Python one final
time before saving.

## Round 8 eighth extension: full 15-combo + superflex recalibration

User's direct follow-up to the 12-team/half-PPR fix above: "I would say
the baseline needs to get fixed across all league sizes and formats."
Re-ran `calibrate_teamcount.py <teams> <fmt>` for all 5 team counts x 3
formats = 15 combinations against the existing on-disk reference CSVs (no
new data pull needed -- these files were already current, the *stored*
`CALIBRATED` dict was just out of sync with them). No candidate hit the
edge of `RANK_CANDIDATES`/`EXPONENT_CANDIDATES` in any of the 15 re-runs.

**Drift was systematic, not noise**: nearly every combo moved toward
deeper ranks and higher exponents, consistent with the same 12-team/
half-PPR finding repeating everywhere -- real depth/convexity in the
current reference data genuinely exceeds what was calibrated before.
Independently re-measured budget share for all 15 combos too, out of
caution -- found it still accurate everywhere (every fresh aggregate
share matched `_STD_SHARE`/`_PPR_SHARE`/`POSITION_BUDGET_SHARE` to within
0.001), so only `ranks`/`exponents` needed updating in
`build_teamcount_estimate.py`'s `CALIBRATED` dict, not budget shares.

**User re-raised this project's original methodology question, tested
directly rather than re-argued from memory**: "the baseline should be set
by the number of needed starters right? ... not like there are
undraftable players past say QB16 or RB36 ... right?" Pulled current
blended-target $ data to show directly: QB12 (pure roster math, 12 teams
x 1 starter) still commands real market $5.70; RB36 (12 teams x (2
starters+flex)) still $7.70; RB50 still $3.70. Value doesn't thin to
near-zero until QB23-26 / well past RB50 -- real bidders pay for bench/
bye-week/injury-insurance depth pure roster math has no way to represent,
reconfirming (with fresh data, not old test results) why this project
calibrates against real auction $ instead of computing rank from roster
math directly.

**Discovered consequence, found during verification, not asked for**:
`roster_formula.py`'s self-test explicitly proves the roster-shape
formula exactly reproduces the real 3-flex and superflex anchors (its own
stated purpose: "do the two REAL anchors round-trip exactly?"). The
15-combo refresh moved `(14, "ppr")`'s WR/TE ranks (65->70, 26->28) and
`(12, "half_ppr")`'s QB rank (16->20) -- both anchors the demand-ratio
rank formula is scaled from -- which silently broke that exact
round-trip (confirmed: WR off by 8%, TE by 6.7% for 3-flex; QB off by
14.3% for superflex). Root cause: `FLEX_SHARE_STANDARD` (WR/TE) and
`_SF_QB_SHARE` were never independently measured constants -- they were
*solved* to make the demand-ratio formula land exactly on the real 3-flex/
superflex targets against the *old* baseline ranks. Moving the baseline
without re-solving these left them solving the wrong equation. Re-solved
algebraically against the new baselines: `FLEX_SHARE_STANDARD["WR"]`
0.25->0.1111, `["TE"]` 0.0833->0.037 (RB unchanged at 0.1818 -- its
baseline rank didn't move, so the old share still round-trips exactly);
`_SF_QB_SHARE` 0.625->0.40. Verified via the self-test after: 3-flex now
round-trips exactly on all 4 positions again; superflex QB (the only
position with real, unconfounded data there) round-trips exactly again.
Superflex RB/WR/TE are still off (not new -- confirmed the *pre-existing*
misses were already nonzero before this round, e.g. RB was already 7.5%
off; this was always documented as "an ASSUMPTION, not independently
verified" in the module docstring, since the superflex data alone can't
cleanly isolate the RB/WR/TE split the way the 3-flex comparison could).
Their exact miss magnitude shifted with this update but their fundamental
nature (unverified assumption, not real data) didn't change.

**Also updated**: `SUPERFLEX_ANCHOR` in `roster_formula.py` (QB rank
26->28, QB exponent 1.0->1.4, re-run via `calibrate_superflex.py` against
current reference data) -- needed regardless of the round-trip fix above,
since it's an independent real calibration in its own right, not just a
formula input.

Verified end-to-end: `roster_formula.py` self-test confirms exact
round-trip restored (3-flex all 4 positions, superflex QB); rebuilt live
workbook shows **zero formula errors across all 15 team/format combos**
(swept every one via Setup, not spot-checked); zero errors on the 3-flex
and superflex roster configs specifically; superflex Josh Allen lands at
$66, a plausible real-market superflex QB1 price (consistent with the
"$80 was way over real sources" bug this project caught and fixed much
earlier); zero leftover price cells; rebuilt fresh from Python one final
time before saving, per the standing lesson.

**Not done this pass**: 3-flex's own calibration (`calibrate_3flex.py`)
was re-run and confirmed NOT stale (identical result with current
candidate ranges), so it was trusted as the correct real target for the
`FLEX_SHARE_STANDARD` re-solve above rather than independently re-verified
against fresh reference data pulls. If a future pass finds 3-flex itself
needs a genuine data refresh (not just a re-run against existing files),
`FLEX_SHARE_STANDARD` would need re-solving again.

## Round 9: web value chart on the site, fully automated (phase 3 begins)

The site-publishing piece deliberately parked at the end of Round 6 finally
got built: an interactive, client-side value chart (team count/format/
budget dropdowns, position filters, search, print) embedded directly in a
WordPress post, member/non-member gated via S2Member's real
`[s2If-paywall]`/`[s2If-ads]` shortcodes (a top-5 static teaser for
non-members). Full build/embedding history — the wpautop paragraph-
injection bug, the `force_balance_tags()` bug (tag-shaped JS string
literals like `'<td class="rank">'` getting "balanced" by WordPress's
save-time HTML parser, fixed by building table rows via
`document.createElement`/`.textContent` instead of `innerHTML` string
concatenation), and why the base64/`document.currentScript` self-loader
idea was abandoned — lives in `web_chart_utils.py`'s module docstring, not
duplicated here.

**IMPORTANT — automation is bundled into `fetch_draft_projections.yml`,
not its own workflow.** That workflow now does two things in one run:
fetch projections → Sheets (its original job), AND pull personal ranks →
rebuild the auction chart → publish to WordPress (added this round). One
run, two outputs — easy to forget since the workflow's name only mentions
the first one.

- `pull_personal_ranks.py` — downloads Joe Bond's rankings straight from
  the same Google Drive folder `ff_cheatsheet/update_joe_bond_ranks.py`
  reads, using the same (already-configured) `GOOGLE_SERVICE_ACCOUNT`
  credential, and saves them directly as `ff_cheatsheet/joe_bond_<fmt>.csv`
  — no Excel/win32com involved (GitHub's Linux runners can't run Excel
  anyway, and the raw Drive CSV's wide multi-block format already matches
  what `load_personal_ranks()` expects, so no reformatting is needed
  either). Means the personal-rank nudge reflects current rankings on
  every automated run, not a manually-pushed snapshot.
- `push_to_wordpress.py` — marker-based partial-content REST API update
  (`<!-- AUCTION_CHART_MEMBER:START/END -->` / `TEASER` comments), targets
  a WordPress **post** (`/wp/v2/posts/{id}`, not `/pages/`), authenticated
  via a dedicated `f6p-automation` Editor-role account's Application
  Password (least-privilege — can't touch plugins/themes/other users if
  the credential ever leaks). Real deploy bug found via an actual test
  run: the site's Cloudflare WAF blocks the default
  `python-requests/x.y.z` User-Agent outright (it's explicitly on a
  bot/scraper blocklist alongside curl/wget/scan tools) — fixed by
  sending a real, identifiable User-Agent string on every request, no
  Cloudflare-side changes needed.
- **No native GitHub `schedule:` trigger on this workflow, on purpose.**
  User has had reliability issues with GitHub's own scheduler before and
  already runs both this workflow and `fetch_adp.yml` via cron-job.org
  (`workflow_dispatch`, once/day each). A `schedule:` trigger was added
  and then deliberately removed once this was confirmed — it wasn't a
  redundant safety net, it was a real double-run risk: `run_all.py`
  re-scrapes all 10 projection sources fresh on every invocation (Sheets
  is the *output*, never an input), so running twice a day would have
  doubled real scraping load on every source, the exact kind of thing
  that's gotten sources blocked before in this project's history.

## Round 10: a second, unrelated bot block, this time at the host level

Round 9's `push_to_wordpress.py` worked cleanly for a day after the
Cloudflare `python-requests` User-Agent fix, then broke again on
2026-07-18 — a *different* failure, not a regression of the first one.

**Symptom**: `FAILED: Expecting value: line 1 column 1 (char 0)` — a bare
`JSONDecodeError`. The existing `if not resp.ok` diagnostic branch never
fired because the response was HTTP 200; the problem was an empty/non-JSON
body on an otherwise-"successful" status, a failure shape the script
couldn't previously see into. Fixed the diagnostics first, before
diagnosing the actual bug: added `diagnose_and_parse_json()`, which logs
status/headers/a body preview whenever *either* the HTTP status isn't 2xx
*or* the body fails to parse as JSON, not just the first case. Re-ran and
got the real evidence on the next failure: an `sg-captcha: challenge`
response header and a redirect to `/.well-known/sgcaptcha/?r=%2Fwp-json%2F...`.

**Root cause**: SiteGround's own hosting-level "AI Anti-Bot" / CAPTCHA
system (separate from the user's own Cloudflare account and its WAF rules
— a second, independent layer, hosting-side rather than DNS-side),
intercepting the REST API request with a CAPTCHA challenge page before it
ever reached WordPress. Confirmed via `curl`-equivalent evidence, not
guessed: response `Content-Type: text/html`, a `<meta refresh>` redirect
to the SG CAPTCHA flow, `Server: cloudflare` (the user's own Cloudflare
account still sits in front, uninvolved in *this* particular block —
correctly ruled out early since the earlier User-Agent fix was still
working the day before).

**Why this one couldn't be fixed client-side at all**: a JS-rendered
CAPTCHA challenge page fundamentally cannot be solved by a server-to-server
script — there's no browser to execute the challenge's JavaScript. Unlike
the Cloudflare block (fixable by changing what the client sends), this
required a change on SiteGround's own infrastructure. Two rounds of
guessing at Site Tools' UI for a self-service toggle (a "Security
Optimizer" WordPress plugin's tabs, then Site Tools' native "Blocked
Traffic" IP/country blocklist) both turned out to be the wrong feature —
neither had anything CAPTCHA-related, confirmed by checking rather than
assuming. Opened a SiteGround support ticket instead, with concrete,
verifiable specifics rather than a vague description: affected path
(`/wp-json/wp/v2/posts/165937`), both failure timestamps in UTC, the
example source IP (`40.65.55.33`) cross-checked against GitHub's own
published Actions IP ranges (`https://api.github.com/meta`, confirmed
within `40.65.0.0/18`) with an explicit note that IP allowlisting
wouldn't work since GitHub Actions rotates across 7,000+ CIDR blocks, the
exact User-Agent string, both HTTP methods used (`GET ?context=edit` then
`POST`), and the exact path format (plain `/wp-json/...`, not
`/index.php/wp-json/...`). SiteGround's support confirmed the diagnosis
(no matching entries in origin access logs at all, meaning the request
really was being stopped before reaching WordPress) and applied a
path-based exemption for `/wp-json/*` on their end.

**Verified, not just assumed fixed**: three consecutive successful daily
runs (2026-07-19, 07-20, 07-21) after the fix landed, via `gh run list`
against the real workflow history — not just taking "it should be fixed
now" at face value, consistent with this project's standing practice
throughout.

**Lesson for next time a hosting-side block shows up**: don't assume the
first bot-block found (Cloudflare, in Round 9) is the *only* one. Sites
behind multiple layers (DNS-level CDN/WAF + host-level anti-bot) can block
the same-looking traffic for two completely independent reasons at two
different points in the request path — fixing one doesn't rule out
needing to separately diagnose the other when a similar-looking failure
resurfaces days later.

## Output
`auction_values_half_ppr.csv` — all QB/RB/WR/TE from the consensus
projections, sorted by auction value descending.

## Conventions
- Reuses `ff_rankings/name_match.py` for name normalization (same
  accent-stripping/suffix-stripping/alias logic used across the other
  projects) rather than duplicating it.
