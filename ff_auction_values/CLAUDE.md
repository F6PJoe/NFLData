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

## Output
`auction_values_half_ppr.csv` — all QB/RB/WR/TE from the consensus
projections, sorted by auction value descending.

## Conventions
- Reuses `ff_rankings/name_match.py` for name normalization (same
  accent-stripping/suffix-stripping/alias logic used across the other
  projects) rather than duplicating it.
