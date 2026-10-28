#!/usr/bin/env python3
"""The weekly projection itself, plus a walk-forward backtest against 2025.

Volume x efficiency, with every piece set by what the data said rather than by
feel (see ff_weekly_model/ notes and the fitted constants in data/):

  plays      team pace, shrunk toward the league mean (k=16 -- team history
             barely predicts play count, so this stays close to league average)
  pass rate  team history (k=8), adjusted down in high wind
  targets    player's share, blended against a prior whose k depends on whether
             he stayed put (3), changed teams (1), or has no history (2, with
             the preseason DEPTH CHART as the prior -- 17% better than a
             position average)
  carries    same, k=0.5 for everyone; backfield roles churn too fast to trust
             last season even for a returning back
  efficiency a player's own rate, blended toward the position mean with
             weight equal to his ACCUMULATED TOUCHES. Efficiency really is
             noise for the many low-volume players who dominate the average;
             it is not noise for a receiver with 60 targets behind him. (The
             old position-mean "ranking" model ran in-form skill players
             0.76p light; it was retired 2026-09-25 and removed 2026-10-28.)
  TDs        implied team total from the Vegas line, split pass/rush by the
             projected pass rate, then allocated by target/carry share

STRICTLY walk-forward: projecting week w uses only weeks < w of the current
season, the prior season, the preseason depth chart, and that week's betting
line. Nothing from week w's box score reaches the projection.

Usage:
    python project.py --year 2025                    # walk-forward backtest
    python project.py --year 2026 --week 3 --live    # project an upcoming week
"""

import argparse
import collections
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ff_weekly_proj"))
import scoring  # noqa: E402

POSITIONS = ("RB", "WR", "TE")          # share DENOMINATORS are skill-only
ALL_POSITIONS = ("QB", "RB", "WR", "TE")  # positions we actually project
HALF_PPR = 0.5

K_PLAYS, K_PASS_RATE, K_QB_RUSH = 16, 8, 3   # K_PASS_RATE re-swept 2026-09-24 (3/5/8/12): flat
K_QB_PASS_SHARE, K_QB_RUSH_SHARE = 12.0, 12.0   # fit: flat optimum 8-20
# TESTED AND REJECTED: blending each QB's own yards-per-attempt into the
# projection. In isolation a passer's own ypa does beat the league mean at
# predicting his next ypa (1.895 vs 1.912), but feeding it into the projection
# made FANTASY POINT accuracy worse at every shrinkage setting tried (7.23 to
# 7.27 QB RMSE, against 7.22 using the league mean). The extra variance costs
# more than the signal is worth once it is multiplied by projected attempts.
# Measured on 2025, conditional on the QB actually taking a snap: the QB listed
# first takes 96% of his team's pass attempts (MEDIAN 100%) and 85% of its QB
# rushing. A QB2 only appears when the starter goes down mid-game -- which is
# not projectable, so the model does not try. Whoever is the highest-ranked
# AVAILABLE quarterback is projected as the starter; the rest split the rest.
QB1_PASS_SHARE, QB1_RUSH_SHARE = 0.96, 0.85
QB1_SKIP_MISSED = True
QB_BACKUP_ON_STARTER_WEEKS = True
# TESTED 2026-09-24, NONE ADOPTED -- all default OFF (flags kept to re-test):
#   TEAM_RATE_STARTER_ONLY  team pass rate + QB-rush share from the current
#                           starter's games only: ALL 5.369 -> 5.371.
#   QBR_STARTER_ONLY        QB-rush share only: 5.369 -> 5.370. It cannot
#                           reach Winston anyway -- the fallback is the TEAM's
#                           prior season, which for NYG was also Dart. The
#                           real fix is QB carries from the QB's OWN history.
#   K_QB_INT                per-QB interception rate: helped 2025 (QB 6.927 ->
#                           6.912) but the league rate beat own rate at
#                           predicting next-week INTs in 2023 AND 2024. Noise.
#   EFF_PRIOR_WEIGHT        lean harder on this season's efficiency (history
#                           x0.5/0.25/0.1): flat to worse. Two cold weeks
#                           (Metcalf, 3.5 yds/tgt) are mostly not signal.
# ON 2026-10-10 (Joe: read Minnesota's lean from Kyler's games, not
# Wentz's). Re-tested on 2024/25/26: dead even (+-0.001), so kept as his rule.
TEAM_RATE_STARTER_ONLY = True
# WHICH GAMES ARE EXITS (EXIT_KEEP_W below decides what happens to them). Joe's
# call (2026-09-25, twice): a game a back LEFT hurt does not count against
# him. ON for RBs, confirmed by the injury report (that week or the next) or a
# current Sleeper tag. Measured: 37 such games in 2025, RB RMSE 5.793 -> 5.799
# -- slightly WORSE, because a back still on the report often plays hurt again.
# Kept on as his judgement; the snap-only version (no confirmation) flagged
# 1,203 player-weeks and was worse again.
SKILL_EXIT_DROP = True
SKILL_EXIT_CONFIRM = True
PBP_EXIT_DROP = True    # neutral in RMSE (77 exit games in 2025), logically right
# EXIT GAMES KEPT, AT A WEIGHT (2026-10-28, Joe: "the season long is not what
# I'm worried about, its the next game effect"). The exits found above are no
# longer thrown out: the game stays at the share he actually had, counted as
# EXIT_KEEP_W of a game (a position left out is still dropped; None = all
# dropped, the old rule). 2024-26, his NEXT game after an exit (241 games):
# dropping it ran +0.93 pts high (backs +0.67 carries, WR/TE +0.33 targets) --
# players come back to a lighter load. Backs in full: next game +1.40 -> +0.51
# pts, season ALL .000/.000/-.001 (passes). WR/TE at half (Joe's call -- in
# full they ran -0.31 targets LOW): next game +0.90 -> +0.02 pts, season
# -.002/+.001/+.001 vs backs-only (2026 a hair past even; kept as his rule).
# Last season's play-by-play exits are still dropped from the prior.
EXIT_KEEP_W = {"RB": 1.0, "WR": 0.5, "TE": 0.5}
_EXIT_W = {}   # pid -> {week: weight} for kept exit games under 1, set in main()
# AUDIT FIXES 2026-09-25. Team TD split now follows the team's projected pass
# rate (the documented behaviour; the code had used one league ratio for every
# team): slope 1.0 best, ALL 5.343 -> 5.341, QB 6.899 -> 6.886. Fumbles are
# projected at the league rate per touch (they were 0 for everyone while actual
# scoring subtracts them): ALL 5.352 -> 5.343, QB 6.941 -> 6.899, bias +0.27
# -> +0.19.
TD_SPLIT_SLOPE = 1.0
# Receiving-TD concentration (2026-09-26). Top WRs/TEs were right on targets
# and yards (more accurate than ESPN, 2024-25) but 0.06 TDs/gm LOW. 1.15 closes
# most of it (+0.063 -> +0.026 in 2024, +0.060 -> +0.017 in 2025) at no RMSE
# cost (2024 5.435 -> 5.435, 2025 5.319 -> 5.321); 1.3+ overshoots and hurts.
TD_CONC_REC = 1.0   # 1.15 until 2026-09-30; REC_TD_POS_EXP now carries this
# TEST VERSIONS (2026-09-26), OFF in the current model -- see VARIANTS.
# Passing TDs: teams of QBs averaging 20+ threw 2.14 pass TDs/gm in 2024
# against 1.65 projected (2025: 1.88 vs 1.79) while the QB's SHARE of them was
# right -- the Vegas total undersold elite passing offences. A QB's own passing
# TD rate (per attempt, shrunk by K attempts toward the league rate) scales his
# team's passing-TD total by W of the difference; CONSERVE of the added TDs
# comes out of the team's rushing TDs. Receivers' TDs move with it.
# PROMOTED TO THE MAIN MODEL 2026-10-06 (Joe) after winning two live weeks
# as a test version: closer on 19 of 24 differing players in wk3, 17 of 27 in
# wk4, best on elite QBs both weeks. The old behaviour runs on as "noqbtd".
QB_PASS_TD_K = 400.0
QB_PASS_TD_W = 0.5
QB_PASS_TD_CONSERVE = 0.5  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
# SAME-LINEUP SHARES (2026-09-30). The QB rule -- a backup is judged only on
# the games this week's starter played -- never existed for skill players. A
# back's share averaged EVERY week, including the ones his starter missed, and
# with K_CAR at 0.5 those weeks carried almost straight into the projection:
# MarShawn Lloyd 12.9 projected carries in wk3 2026, 4 actual. With this on, a
# player's weeks count only if every teammate at his position with a BIGGER
# role who is active this week also played that week. No weeks left -> prior.
SAME_LINEUP_POS = ("WR", "TE")   # deflate mode (2026-10-08)
# League VOLUME anchors (plays, pass rate) learned in-season the same way:
# every team is pulled toward the league mean, and that mean was last
# season's. 2026 wks 2-4: projected 31.9-32.1 pass attempts per team-game
# against 33.1-34.3 actual. None = off.
LG_VOL_K = 32   # ADOPTED 2026-10-22 (net-gain standard): ALL 2024 -.002, 2025 -.002, 2026 +.001; QB best
# ONE PASSING GAME PER TEAM (2026-10-06, Joe: "if elite WRs are getting the
# ball wouldn't that help yards both ways?"). QB passing yards came from the
# QB's own yards per attempt and receiving yards from each receiver's yards
# per target, separately -- wk4 2026 they disagreed by up to 35 yards a team
# (SF QB 270 vs receivers 236; CAR 230 vs 260), though in real games they are
# equal (2025: 224.7 vs 225.0 a team-game). Each team gets ONE total, PASS_
# RECON_W x the QB's figure + the rest x the receivers', and both sides are
# scaled to it; completions and catches the same. None = off.
# ADOPTED at 0.25 -- the receivers' side carries most of the weight, so an
# elite WR room lifts its QB: ALL 2024 5.394 -> 5.389, 2025 5.305 -> 5.303,
# 2026 5.189 -> 5.188; QB 7.239 -> 7.220 / 6.921 -> 6.914 / 6.417 -> 6.405.
# QB-only (1.0) was worst; receivers-only (0) nearly as good as 0.25.
PASS_RECON_W = 0.25
# WEATHER ON PASSING EFFICIENCY (2026-10-07). WR yards per target 2023-25:
# wind under 10 mph 7.94, 10-14 mph 7.45 (-6%), 15+ mph 7.27 (-8.5%); outdoor
# under 40F 7.59 vs 7.70 at 40-69F (-1.5%). Passing yards (QB and receivers)
# are cut by those amounts x WX_SCALE in outdoor games. 0 = off. The wind/temp
# come from games.csv, which only has them AFTER a game -- live use needs a
# forecast.
WX_SCALE = 0.5  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
WX_CUTS = {"wind15": 0.085, "wind10": 0.06, "cold": 0.015}
PLAYS_TOTAL_W = 0.65
# ADOPTED 2026-09-30 for targets at 0.25 (0.5+ overshoots; carries at any
# strength were flat to worse -- an RB's snaps swing with game script).
# RED-ZONE ROLES (redzone.py, 2026-10-01). Touchdowns were split by OVERALL
# share; a goal-line back or a red-zone tight end scores beyond his share, a
# between-the-20s player short of it. Each player's TD weight is scaled by
# his red-zone concentration -- share of team plays inside the 10 / overall
# share, over the same games -- shrunk toward 1 by the team's red-zone plays
# in his games (K_RZ), last season counting RZ_HIST_W. ^RZ_EXP; 0 = off.
# Team TD totals are unchanged (weights are renormalised per team).
# ADOPTED at half strength: ALL 2024 5.410 -> 5.409, 2025 5.308 -> 5.306,
# 2026 5.148 -> 5.146; TE 4.098 -> 4.090 / 4.332 -> 4.329. Small -- TDs are
# noisy even with roles known -- but the same sign in all three seasons.
# Full strength / K 10 / last season at full weight were flat to worse.
RZ_EXP = 0.5
K_RZ = 20.0
RZ_HIST_W = 0.5
# Position-specific shrinkage (2026-10-01): multipliers on the target-share
# prior weight (K_TGT) and the efficiency pull (K_EFF_TGT / K_EFF_CAR).
# Tested TE/RB x0.5 and x2 on both: all mixed (one season up, one down) except
# TE efficiency x0.5 -- better in all three, if barely (TE 4.090 -> 4.087,
# 4.329 -> 4.327, 4.843 -> 4.841): a receiving TE's yards per target is more
# his own than a WR's is.
# WR x0.5 added 2026-10-13 with ROUTE_HIST_W 1.0 (Joe: "elite WR need to be
# paid attention to more"). Last year's top-12 WRs ran LOW in wks 2-5 in all
# three seasons (-0.36 / -0.44 / -2.11), their target share 0.7-1.6 pts under:
# the pulls toward the average WR compress the elite. Together, WR RMSE
# 5.375 -> 5.376 / 4.989 -> 4.987 / 5.256 -> 5.238, ALL 2026 5.203 -> 5.197,
# elite wks 2-5 bias -0.22 / -0.25 / -1.92. The rest of the 2026 gap is their
# TEAMS throwing 36.7 targets a game vs 32.2 projected (league +1.6) and 9.87
# yds/target vs 8.62 -- not seen in 2024-25, so not modelled.
# BY STAGE OF SEASON (2026-10-20, Joe: "6 weeks in, shouldn't we be utilizing
# this season more?"). 1.0 / 0.75 / 0.5 split wks 2-6 / 7-12 / 13-18: WR
# 2024 wk 7-12 5.232 -> 5.233-5.236, wk 13-18 5.444 -> 5.445-5.452; 2025 the
# same pattern -- a lighter prior is no better LATE in the season either
# (n is the game count, so this season's weight already grows: 57% of the
# target share at 6 games, 74% at 13). RBs a hair better lighter (<0.005).
POS_KT_MULT = {"WR": 1.5, "TE": 1.5, "RB": 1.5}   # 1.5 with PRESEASON_W, 2026-10-13
POS_KEFF_MULT = {"TE": 0.5, "WR": 0.5}
# ROUTE PARTICIPATION (fl_routes.py, 2026-10-01): the same rescale as the snap
# version, but by ROUTE % -- the share of dropbacks a player actually ran a
# route on -- which separates a receiving TE from a blocking one in a way
# total snaps cannot. Exponent 0 = off.
# ADOPTED at 0.5, REPLACING the snap version for targets: ALL 2024 5.408 ->
# 5.405, 2025 5.306 -> 5.304, 2026 wks 2-3 5.146 -> 5.147; TE 4.087 -> 4.083,
# 4.327 -> 4.319. FL data: past seasons in data/fl_util (pulled 2026-10-01 with
# Joe's OK), this season read from the usage tool's weekly file.
ROUTE_LEAD_TGT = 0.5
# ROUTE-BASED TARGET MODEL (2026-10-01): a second estimate of each player's
# target share -- his recent route participation x his targets per route run
# (TPRR, this season + last season at ROUTE_HIST_W, shrunk to the position
# mean by K_TPRR routes) -- compared within his team, then blended into the
# usual share at ROUTE_MODEL_W. 0 = off. Players with no route data keep
# their usual share.
# ADOPTED 2026-10-01 at 40% (RBs 75% -- a back's route % IS his passing-down
# role): ALL 2024 5.405 -> 5.396, 2025 5.304 -> 5.293, 2026 wks 2-3 5.147 ->
# 5.136. 75%+ for everyone overshoots; last-game-only route % is worse; K_TPRR
# 75/300 no better than 150.
ROUTE_MODEL_W = 0.4
K_TPRR = 150.0
# back to 0.5 2026-10-18 (Joe: "we should 100% be trusting role changes ...
# we have 5 weeks"): with 2023 route data, preseason priors etc. in, last
# season's routes at half weight are better in all three seasons -- ALL
# 5.380/5.291/5.143 -> 5.379/5.290/5.142 (RB, TE better too). Shorter
# HALF_LIFE (2.5-3), faster-fading share priors and more this-season
# efficiency were all WORSE: trust this season's ROLE, not a short hot streak.
ROUTE_HIST_W = 0.5
# 2 -> 3 (2026-10-13, Joe: WR downgrades off a game or two were wrong). Route
# share averaged over the last 3 games: WR 5.371 -> 5.361 / 4.984 -> 4.981 /
# 5.210 -> 5.209, ALL 5.387 -> 5.382 / 5.296 -> 5.294 / 5.177 -> 5.178. 4-6 and
# a longer WR target half-life (HALF_LIFE_TGT_POS 6-8) were flat or worse.
ROUTE_RECENT_N = 3
# TE 0.2 (2026-10-15, Joe OK'd): a TE's routes are a weaker target signal
# (chips, decoys). TE 4.061/4.298/4.423 -> 4.054/4.304/4.401 (2025 a hair
# worse), ALL 5.381/5.290/5.167 -> 5.379/5.291/5.163; live wks 3-5 TE 6.21 -> 6.19.
ROUTE_MODEL_W_POS = {"RB": 0.75, "TE": 0.2}
SNAP_LEAD_POS = ("RB", "WR", "TE")
# RECEIVING TDs BY POSITION (2026-09-30). A team's receiving TDs were split by
# target share alone, as if a checkdown to the back scored as often as a fade
# to the tight end. League TDs per target: RB 0.029-0.034, WR ~0.050, TE
# 0.047-0.058. We projected RBs at 0.043-0.046 -- 124 RB receiving TDs in 2024
# vs 80 actual, 125 vs 93 in 2025 -- and TEs short every year (157 vs 172, 175
# vs 220). Each player's TD weight is now scaled by his position's league rate
# per target (^ exponent; 0 = off). The team total is unchanged.
# ADOPTED 2026-09-30 with TD_CONC_REC back to 1.0 (the target-share tilt had
# been partly doing this job): RB receiving TDs 124 -> 88 vs 80 actual (2024),
# 125 -> 83 vs 93 (2025); 2026 wks 2-3 RB 5.740 -> 5.726, TE 6.124 -> 6.014.
REC_TD_POS_EXP = 1.0
# DEFENSIVE MATCHUPS (matchups.py): per defense, per position, per stat --
# actual vs our own projection for the players who faced it, shrunk toward
# no effect by games / (games + MATCHUP_K). None = off.
MATCHUP_K = None
MATCHUP_STATS = ()   # () = every factor; else a subset, e.g. ypc,ypt
MATCHUP_POS = ()     # () = every position
# EPA version (matchups.EpaMatchups): MATCHUP_MODE "epa" uses play-by-play EPA
# allowed, net of each offense's own average, shrunk by plays (MATCHUP_EPA_K)
# and scaled into stats by MATCHUP_EPA_BETA; last season seeds it at
# MATCHUP_EPA_PRIOR of its weight. Needs MATCHUP_K set (any value) to switch on.
MATCHUP_MODE = "resid"
MATCHUP_EPA_BETA = 1.0
MATCHUP_EPA_K = 100.0
MATCHUP_EPA_PRIOR = 0.0
SAME_LINEUP_MIN = 0.20   # a teammate "has a role" at this share or more
# Named test versions, run alongside the current model each week and scored
# against it (--version NAME writes projections_<yr>_wk<NN>_<NAME>.csv).
# Backtest 2026-09-26 (QB RMSE, 2024 / 2025; current 7.261 / 6.881):
#   K=400 half-strength  7.241 / 6.930   hot-QB bias -2.38 -> -1.66 / +0.06 -> +0.54
#   K=400 full           7.255 / 7.007   K=1000 7.237 / 6.964   K=150 7.281 / 7.040
#   CONSERVE 0.5 / 1     QB same, RB worse in 2024 (5.473 -> 5.490 / 5.533)
# The seasons disagree -- 2024 wants it, 2025 does not -- so it runs as a test
# version beside the current model instead of replacing it.
# TGT_CONC 1.03 / 1.05 / 1.1 was worse at every position in both seasons and
# pushed star WRs further ABOVE what they scored: not run as a version.
# "epa" (2026-09-30): defensive EPA matchups, last season's ratings at 2x
# weight seeding this season's, half-strength. 2025 ALL 5.322 -> 5.318, 2026
# wks 2-3 5.179 -> 5.165, better at every position in both; 2024 untestable
# (no 2023 play-by-play). This season's early EPA alone was noise.
VARIANTS = {
    "current": {},
    "noqbtd": {"QB_PASS_TD_K": None},   # the main model before 2026-10-06
    "epa": {"MATCHUP_K": 1.0, "MATCHUP_MODE": "epa", "MATCHUP_EPA_BETA": 0.5,
            "MATCHUP_EPA_PRIOR": 2.0},
}
PROJECT_FUMBLES = True
BACKUP_EFF_MULT = 0.92    # ADOPTED 2026-10-24 (Huntley): ALL +.002/-.002/-.004, QB 2026 -.017; .95 -.003 net, .85 -.003 (see starter_wks)
BACKUP_CATCH_MULT = 1.0
BACKUP_START_FRAC = 0.5
TEAM_RATE_RETURN_W = 0.0   # ADOPTED 2026-10-24 (with EXIT_RETURN_FRAC: ALL 2024 -.004, 2025/26 flat; .5 half the gain) -- weight of games a returning workhorse back missed, in the team pass rate
RB_MIN_BACKUP = 0.20   # see the no-team-plays-one-back guard
RB_LONE_MIN = 0.02     # any other back above 2% of the lead back's share = a backup exists; 0.10-0.25 fired on real 2026 workhorses (Cook, Gibbs, Henry: RB 5.011 -> 5.035)
GS_RUSH = 0.01   # fit: RB 5.819 -> 5.806, QB/WR/TE unchanged; 3%+ worse
# Vacated roles (see project_week): 25% of an absent player's share split
# evenly among the teammates at his position. Fit 2026-09-24: ALL 5.370 ->
# 5.357, better at every position; 50%+ hurts TEs (a TE3 is a blocker), and no
# per-position mix beat a flat 25%.
VAC_EQ = 0.25
# Vacated TARGETS to the best target-earners (2026-10-13, Joe: when a stud WR
# is out, the elite target-getter left should absorb the most). This fraction
# of an absent player's target share goes to his remaining teammates by
# route% x targets-per-route (the route model's estimate) ^ VAC_TPRR_EXP --
# volume only, efficiency untouched. Scope "pos" = same position, "team" =
# every pass-catcher. 0 = off. ADOPTED 0.25 / team: ALL 5.395 -> 5.395,
# 5.306 -> 5.305, 5.197 -> 5.193; WR 5.382 -> 5.380, flat, 5.238 -> 5.231.
# Same-position or ^2 helped 2026 more but hurt 2024.
VAC_TPRR = 0.25
# ELITE TARGET-EARNERS, re-judged every week (2026-10-13, Joe: "a way to
# determine who the top guys are weekly ... elite guys who are not hurt, who
# might be just not doing as well"). Rolling targets per route run = this
# season to date + all of last season (ELITE_MIN_ROUTES+), recent route share
# ELITE_MIN_RP+. For WRs at ELITE_TPRR+ the model chased form: projected 0.81
# LOW when slumping (pts/target 20%+ under his last season), 1.00 HIGH when
# hot; the tier below was the reverse (slumps real, +1.16). For the elite,
# last season's efficiency counts ELITE_EFF_PRIOR_W in the rate instead of
# EFF_PRIOR_WEIGHT, so a cold or hot stretch moves them less. None = off.
# ADOPTED .25 / 1.0 as Joe's rule: slump bias -0.81 -> -0.52, hot +1.00 ->
# +0.77, RMSE identical all three seasons (2.0 went further, -0.29 / +0.60,
# but cost a hair: WR 5.383 / 4.988 / 5.239).
ELITE_TPRR = 0.25
ELITE_MIN_ROUTES = 150
ELITE_MIN_RP = 0.6
ELITE_POS = ("WR",)
ELITE_EFF_PRIOR_W = 1.0
# PRESEASON PROJECTIONS as a starting point (preseason.py, 2026-10-13, Joe:
# "we had consensus projections, ranks, depth chart data available to us just
# like they did"). Each player's preseason projected targets / carries, as a
# share of his team's, blended into his share PRIOR at PRESEASON_W
# (PRESEASON_W_NEW for players with no usage history -- rookies, mostly). The
# prior fades as this season's games pile up, exactly like last season's
# usage. PRESEASON_EFF moves the efficiency shrink target (yds/target, catch
# rate) from the position mean toward his preseason rate. 0 = off.
# ADOPTED 0.5 with POS_KT_MULT 1.5 (the prior lasts 1.5x as long): ALL
# 5.395 -> 5.387, 5.305 -> 5.296, 5.193 -> 5.177; WR 5.380 -> 5.371, 4.987 ->
# 4.984, 5.231 -> 5.210; RB and TE better every season too, QB unchanged.
# Rookies at 0.75-1.0 helped 2026, hurt 2024-25. Efficiency at 0.5: ~nothing.
PRESEASON_W = 0.5
VAC_PRIOR_W = 0.5           # vacated offseason roles (apply_vacated). ADOPTED 2026-10-24: ALL +.001/0/-.001 (tie -> 2026; RB 2026 5.014 -> 5.010); 1.0 net worse
PRESEASON_EFF = 0.25  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
_PRESEASON_RATES = {}
# DEPTH-CHART DEMOTION (2026-10-13). nflverse's daily ESPN depth charts: a
# back listed as a BACKUP in the last snapshot before the week, who was the
# STARTER for most of his last 3 games, kept being projected his old workload
# -- 2024-26: 8.0 carries projected, 6.5 actual, 2.1 pts too high (n=50).
# His usage is scaled by DEPTH_DEMOTE[pos] (rest to teammates, like LIMITED).
# Promotions, and every WR/TE move, were already priced in (route data sees a
# role change as fast as the chart does). {} = off. TESTED RB 0.8/0.65/0.5:
# 2025 better (RB 5.698 -> 5.682 at .65), 2024 worse (5.408 -> 5.413), 2026
# flat -- and the promoted back, who inherits the work, went from 0.9 to 1.3
# pts too high: the lost carries do not go cleanly to the new starter. Off.
DEPTH_DEMOTE = {"RB": 0.8}  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
_DEPTH_FLAG = {}
# SUSTAINED ROLE CHANGE (2026-10-15, Joe on Mike Evans: "utilize the fact that
# over the last three full games he has had that kind of volume"). When each
# of a player's last ROLE_N games had a target share at least ROLE_MARGIN
# (relative) above the projected share -- or each was that far below -- the
# share moves ROLE_W of the way to his average over those games. None = off.
# ADOPTED .3 for WRs as Joe's rule: ALL identical all 3 seasons, WR 5.357 ->
# 5.358 / 4.975 / 5.182 -> 5.179. For RB/TE it hurt 2024-25 (streaky usage
# that fades) -- WR only. .5/.7 hurt more.
ROLE_W = 0.3
ROLE_N = 3
ROLE_MARGIN = 0.20
ROLE_POS = ("WR",)
# RETURNING PLAYERS (2026-10-22, Joe on Josh Jacobs, back from the exempt
# list wk7 with no 2026 games: "we should not have to boost Jacobs that high
# ... rely more on historical data for them"). A player active this week with
# NO games this season and a prior role (RETURN_MIN_SHARE of carries for an
# RB, targets otherwise) gets his history -- and every same-position
# teammate's games this season, all played without him, are deflated by
# RETURN_DEFLATE x his prior share, exactly as SAME_LINEUP_MODE "deflate"
# does for WR/TE. Without it Lloyd / Kaleb Johnson / Strong kept their
# Jacobs-less shares and Jacobs (68% of GB RB carries in 2025) got 47%.
# Covers RBs too, which the general deflate does not. None = off.
# ADOPTED 1.0, RBs only: ALL 5.379/5.290/5.106 -> 5.378/5.290/5.106, RB 5.413 ->
# 5.409 (2024: McCaffrey wk10 back 9.9 -> 15.2 carries, got 13), 2025-26
# flat. WR/TE returners came back BELOW their history (A.J. Brown, Godwin,
# Hollywood Brown, Deebo: snaps limited, rust) -- WR 2026 5.082 -> 5.085: off.
RETURN_DEFLATE = 1.0
RETURN_MIN_SHARE = 0.20
RETURN_MIN_TEAM_GAMES = 2
RETURN_POS = ("RB",)
# MID-SEASON RETURNS (2026-10-22, Joe: "is this going to be applied everywhere?
# For when long term absences happen"). A back who played, then missed
# RETURN_MIN_MISSED+ straight games: teammates' weeks INSIDE the absence are
# deflated at RETURN_MID_DEFLATE strength. Full strength was WORSE (RB
# 5.407 -> 5.432 / 5.698 -> 5.708): returners ended +1.7 pts high, since
# their own pre-injury games already rate them right and fill-ins keep
# part of the job (Hunt 2024, Vidal 2025, Tracy 2024). ADOPTED .25 after
# 2 games: RB 5.407 -> 5.404, 5.698 -> 5.697, 5.023 -> 5.022.
RETURN_MID_DEFLATE = 0.25
RETURN_MIN_MISSED = 2
# ESTABLISHED WORKHORSES (2026-10-22, Joe: "if somebody like CMC or Jonathan
# Taylor were to return midseason, they would likely have taken their full
# share of work again"). 2023-26, 11 returns at 65%+ of carries: 76% before
# -> 64% after, fill-ins 64% during -> 27% after (Taylor 89 -> 91, Saquon
# 87 -> 85, Conner 68 -> 69, Mixon 63 -> 77). The exceptions were lesser backs
# (Singletary, Zamir White, Pierce). A returner at RETURN_STAR_SHARE+ this
# season AND RETURN_STAR_PRIOR+ last season gets RETURN_STAR_DEFLATE. The
# prior check keeps out fill-ins inflated by a star's absence (Jordan Mason
# 2024 cutting into McCaffrey). Full strength was worse (returners score
# less per touch at first). ADOPTED .6/.5/.6: RB 5.404 -> 5.401, 5.697 ->
# 5.696, 2026 flat.
RETURN_STAR_SHARE = 0.60
RETURN_STAR_DEFLATE = 0.6
RETURN_STAR_PRIOR = 0.50
RETURN_ROUTES = True   # their route participation too: ALL 2024 5.378 -> 5.377 (RB 5.409 -> 5.407), 2025-26 flat
# TRADED MIDSEASON (Joe, MHJ ARI -> HOU wk6 2026): usage x TRADE_MULT[0] in
# his first game with the new team, x TRADE_MULT[1] in the second. None = off.
# ADOPTED (.5, .75): 2024 5.380 -> 5.379, 2025 5.293 -> 5.291 (19 / 25 midseason
# moves); WR + TE better. (.4,.65) about the same, (.75,.9) about half the gain.
TRADE_MULT = (0.5, 0.75)
_PREV_TEAM = {}   # pid -> his team in his last game LAST season
NEW_TEAM_MULT = 0.5   # ADOPTED 2026-10-24 (last season's team != this one): ALL 2025 -.001, 2026 -.004 (see NEW TEAM, NO GAMES YET in pass 1)
# TEAM-SPECIFIC "WITHOUT HIM" HISTORY (2026-10-16, Joe: "we need to be looking
# at history for each team when there are injured players and how the offense
# runs, divvies up targets, etc. not put a blanket across the whole league").
# When a player with a real role (WOWY_MIN_CAR carry share in his last 2
# games) is OUT this week, the team's own games
# this season WITHOUT him set (a) its pass rate and QB run share, blended
# n:WOWY_K_TEAM, and (b) each remaining player's target / carry share,
# blended n:WOWY_K_SHARE (n = games without him). The league-wide vacated-
# role split (VAC_*) is scaled down by the same weight. None = off.
# Buffalo wk6 2026 without DJ Moore (wk5): 35% passing, Allen 10 runs, Cook
# 25 carries, Shakir 17% / Coleman 11% of targets.
# ADOPTED team part, K 4: ALL 5.379/5.292/5.148 -> 5.380/5.291/5.143, QB
# 7.227/6.924/6.689 -> 7.232/6.914/6.661. The SHARE part lost at every K
# (2-16; K 2: 2024 5.379 -> 5.400): one or two games of target split without a
# player is mostly noise -- left off.
# STUD BACKS ONLY (2026-10-28). The switch-off test said drop the rule (net
# -.005); Joe: "I wonder if its better for when a stud RB is missing, as in
# they pass more?" It is: only when a back with 50%+ of the carries is out,
# ALL -.001/-.001/-.005 (net -.007, 2026 wks 2-7) -- better than off. A missing
# receiver (15%+ of targets, the old trigger) does not change the pass rate.
WOWY_K_TEAM = 4
WOWY_MIN_CAR = 0.50
_TEAM_WEEK = {}
_LAST_TEAM = {}   # team_proj of the last project_week call
_DEBUG_PIDS = set(filter(None, os.environ.get("PROJ_DEBUG", "").split(",")))   # player ids to trace
# TEAM RUN GAME (2026-10-22, Joe: "the Texans run game is kinda bad"; GB's
# all season). An RB's yards per carry was shrunk toward the LEAGUE RB mean;
# with TEAM_YPC_W the mean he is shrunk toward is moved toward his TEAM's
# non-QB yards per carry this season (itself shrunk to the league by
# TEAM_YPC_K carries). A back with a big sample barely moves; a new or
# part-time back on a bad rushing team stops getting league-average yards.
# TESTED 2026-10-22 (.5 / 1.0, K 75-150): 2026 RB better (5.022 -> 5.010-5.017)
# but 2024 and 2025 worse (5.401 -> 5.404, 5.696 -> 5.705) -- a team's
# rushing efficiency is mostly its backs, already in their own rates. Live
# wk7 moved nobody more than 0.2. Off.
TEAM_YPC_W = 0.5   # ADOPTED 2026-10-22 at .5 with LG_VOL_K: net even, 2026 RB 5.022 -> 5.016 (tie -> 2026)
TEAM_YPC_K = 150.0
_TEAM_RUSH = {}    # (team, week) -> (non-QB rush yds, non-QB carries, pass TDs, rush TDs)
# PLAYED HURT (2026-10-15, Joe: don't penalize them for missing time). A game
# where he was on that week's injury report AND played under INJ_SNAP_FRAC of
# his usual snap share is skipped when the route model reads his route
# participation -- Mike Evans wk2-5 2026 (54/33/59/63% snaps, questionable /
# limited) read as a part-timer: 11.5 pts, 13.3 without the route model.
# None = off. TESTED .75/.85/.95: mixed (2025 worse) -- and the premise was
# wrong for Evans: his route% was a normal 72-77%; the route model was
# DILUTING his recent targets-per-route surge (.32/.35 vs .26 in 2025).
INJ_SNAP_FRAC = 0.6  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
_INJ_LIMITED = set()
# TOP-RECEIVER SEASON CALIBRATION (2026-10-13). How teams' top receivers
# convert targets swings by SEASON, not by player: our team-WR1s ran +0.07
# (2024), -0.93 (2025, everyone's WR1 converted worse) and +0.99 (2026) pts a
# game vs projection -- so no fixed elite boost works. Instead: this season's
# WR1s (each team-game's most-targeted WR, weeks before this one) vs last
# season's, per stat (yds/target, catch rate, TDs/target); the ratio, shrunk
# toward 1 by TIER_CAL_K targets, scales this week's projected team-WR1.
# None = off. ADOPTED 100 (better every season at every K, 4000 down to 25):
# ALL 5.382 -> 5.381, 5.294 -> 5.290, 5.178 -> 5.168; WR 5.361 -> 5.358,
# 4.981 -> 4.971, 5.209 -> 5.189. TDs included (without: a bit less gain).
TIER_CAL_K = 100
TIER_CAL_TD = True
# A FILL-IN is not the WR1 (Joe, 2026-10-14: "you can't give Harris Ladd
# McConkey's full efficiency just cause he replaces him"). With True, the team
# gets no calibrated WR1 when an absent WR had the bigger usual share.
# ADOPTED as Joe's rule: 2024-25 identical, 2026 5.168 -> 5.171 (WR 5.189 ->
# 5.193). Wk5 2026: Tre Harris 9.10 -> 8.44 yds/target (13.1 -> 12.3 pts),
# Shakir, Downs, Worthy, Wicks the same way.
TIER_CAL_REAL_WR1 = True
# ...unless the fill-in is an ELITE_TPRR target-earner himself (Davante Adams
# behind Puka, wk2 2026: 35.5). ADOPTED: 2026 5.171 -> 5.167, WR 5.193 ->
# 5.186 -- better than the old blanket boost too (5.168 / 5.189); 2024-25 same.
TIER_CAL_FILLIN_ELITE = True
_TIER_RATIO = {}
# RECEIVERS OUT -> LESS EFFICIENT PASSING (2026-10-13, Joe: LAC wk5 2026 with
# McConkey and Q. Johnston out). 2024-26, team-games missing 35%+ of their
# usual WR targets: pass attempts held (32.0 proj, 32.1 actual) but QB
# passing yards fell 14 short (222 -> 208). Yards per target / per attempt
# are cut by MISS_YPT x the share of team targets the absent WRs had. 0 = off.
# TESTED .15/.3/.5 (with and without the QB): 2024-25 a hair better (ALL
# 5.381 -> 5.378, 5.290 -> 5.289), 2026 worse (5.168 -> 5.169-5.176, QB
# 6.667 -> 6.67-6.71, also via PASS_RECON). Mixed -- off.
MISS_YPT = 0.15  # ADOPTED 2026-10-22 re-test under Joe's rule (6 together: ALL -.002/-.008/-.001)
# TEAM SHEET (2026-10-15, Joe: ATL is run-first whoever plays QB). Live runs
# read data/team_adjust_<yr>_wk<NN>.csv -- team, pass_rate (47 or 0.47),
# plays, qb_rush_share (the QB's share of the team's runs), note -- and a
# filled cell REPLACES the model's team number before
# wind and game script. The QB, backs and receivers all follow from it.
_TEAM_ADJ = {}
# Dud-week floor, SUPERSTARS ONLY (Joe: one bad week from a Chase should not
# crater him). Applied to everyone with 8+ games it was worse at every level
# (floor 50% -> 5.373, 80% -> 5.401); limited to a 25%+ target share (or 60%+
# carry share) backed by 12+ games it helps slightly: 5.357 -> 5.356, WR
# 5.023 -> 5.017. Downward only -- breakouts are never capped.
DUD_MIN_SHARE, DUD_MIN_SHARE_CAR = 0.25, 0.60
DUD_FLOOR = 0.65
# No-history players OFF the depth chart (2026-09-25): WR/TE start from the
# deepest slot, RBs from an RB3's share, instead of the position mean (an RB2's
# workload, taken only over backs who got carries). Plus fullback games now
# count as games (FB_ZEROS). 2025: ALL 5.341 -> 5.316, the largest single gain
# of the project -- RB 5.791 -> 5.752, WR 5.016 -> 4.989, TE 4.374 -> 4.357.
NO_HISTORY_DEEPEST = True
NO_HISTORY_RB_RANK = 3
FB_ZEROS = True
DUD_REPEAT = 3   # fit: release floor after 3 duds in last 4 (ALL 5.341 -> 5.340, RB 5.801 -> 5.793)
DUD_MIN_GAMES = 12
TEAM_PRIOR_W_RATE = 0.5   # fit: 50% best (WR 5.055 -> 5.051); plays anchor TESTED, hurts QB
PBP_EXIT_MIN_SECS = 900
SKILL_EXIT_FRAC, SKILL_EXIT_MIN_REF = 0.5, 0.5
EXIT_PREGAME_KEEP = True    # ADOPTED 2026-10-27: a light game he was listed for BEFORE kickoff is not an exit (Henderson wk6). ALL -.002/-.001/-.002 (2026 wks 2-7), RB 2026 -.005
EXIT_RETURN_FRAC = 0.25   # ADOPTED 2026-10-24: ALL 2024 -.001, 2025/26 flat (Dowdle wk6 kept) -- first game back from an OUT: exit only under this fraction of usual snaps (None = same rule)
# FULL on the review sheet uses a broader cut than the automatic exit rule:
# Joe is vouching that he is back to 100%, so any game under FULL_FRAC of his
# usual snaps is treated as played hurt (2026-10-15: Mike Evans wk2 54% after
# 75% in wk1 -- he left early -- slipped under the automatic 50% cut).
FULL_FRAC = 0.8
# Extended to WR/TE 2026-10-08 (Joe: "if we project him as in he needs to be
# full go"). A snap collapse (under half his usual) confirmed by the injury
# report drops that game for every skill position -- it catches exits the
# play-by-play never logs (Jefferson wk3 2026: 12% of snaps, no "was injured"
# line). Measured cost +0.001-0.003 RMSE (TE mostly): kept as his rule, like
# the RB version, since a player projected to play is projected healthy.
SKILL_EXIT_POSITIONS = ("RB", "WR", "TE")
# THIS SEASON COUNTS FASTER (2026-09-30, Joe: "more emphasis on what is
# happening this year"). Last season's efficiency now counts at 50% per target
# and 20% per carry in a player's RATE; the touch count behind the pull to the
# league mean is unchanged (EFF_PRIOR_N off -- scaling it too was worse).
# Henry wk4 2026: 5.20 YPC on 307 carries in 2025, 4.56 on 66 this year ->
# his own rate 5.08 before, about 4.9 now. Backtest ALL / RB:
#   2024 5.435 -> 5.427 / 5.473 -> 5.455   2025 5.320 -> 5.320 / 5.752 -> 5.757
#   2026 wks 2-3 5.191 -> 5.185 / 4.753 -> 4.723
# The one earlier test (all stats x0.5/0.25/0.1, 2025 only) read as flat -- 2025
# is the one season where it is.
EFF_PRIOR_WEIGHT = 0.5
EFF_PRIOR_WEIGHT_RUSH = 0.2
# Last season's efficiency is IGNORED when he played fewer than this many
# games in it (2026-10-15, Joe on Mike Evans: 8 injured 2025 games at 5.94
# yds/target still dragged a 9.59 2026). None = off. ADOPTED 10 as Joe's
# rule ("don't penalize them for missing time"): ALL 5.379/5.291/5.163 ->
# 5.380/5.293/5.162, WR 5.357/4.972/5.187 -> 5.357/4.975/5.182. Wk6: Evans
# 11.5 -> 12.7, Garrett Wilson 12.7 -> 13.5.
EFF_PRIOR_MIN_G = 10
QB1_MIN_WEEK_SHARE = 0.3   # fit: 30% best (QB 6.990 -> 6.986); typical starter takes ~100%
# Player efficiency -- see player_eff_by_week(). Fitted in research/fit_dfs_efficiency.py:
# on in-form skill players position means ran +0.76p LIGHT, and this closes
# it to +0.03p while nudging RMSE 5.427 -> 5.409. The aggregate number hid this
# for a long time, because elite QBs are over-projected by almost exactly as
# much as elite skill players are under-projected, and the two cancelled.
K_EFF_TGT, K_EFF_CAR = 80.0, 120.0
QB_RUSH_TD_DECAY = 0.75   # per season back; fit in research/fit_qb_rush_td.py
# SUPERSEDED NOTE (kept for the reasoning): giving each QB his own rushing-TD
# rate off a SINGLE prior season was tested and rejected -- The rate IS
# player-specific (0.125 TD/carry at the top vs 0.000 at the bottom, league
# 0.048) and it closes most of the gap to consensus on Allen and Hurts. But
# against ACTUAL 2025 outcomes it made QB RMSE worse (7.037 -> 7.059) and left
# the elite bias untouched (-0.68 -> -0.69), because we already over-project
# in-form QBs. The consensus is the one running hot here, not us. qb_rush_hist
# and the qb_rush parameter are kept so this is cheap to re-test on more data.
# Downward adjustment took the low group from +0.79 to -0.06 with no RMSE cost.
# Upward is gated on a PROVEN role (QB_RUSH_TD_MIN_SEASONS qualifying seasons)
# and conserves the team's touchdowns -- see the CONSERVE block in project_week.
K_QB_RUSH_TD_DOWN = 40.0
# Shrunk by ATTEMPTS, and this is why the first attempt at it failed: that
# version shrank by GAMES off ONE prior season, which gave even a 500-attempt
# starter almost none of his own number. Validated on four target seasons
# predicting next-week passing yards -- k=100 wins in 2023 (+3.5%), 2024
# (+3.4%) and 2025 (+2.3%), and loses only in 2022, the one year with a single
# season of history behind it. Two seasons is the threshold, as it was for the
# QB rushing-TD work.
K_QB_YPA = 100.0
K_RB_RUSH_TD = 150.0   # carries; fit 150-300 flat, 150 best calibrated
QB_RUSH_TD_MIN_SEASONS = 2   # qualifying SEASONS, not weeks -- picks out Allen and Hurts
K_TGT = {"same team": 3.0, "changed team": 1.0, "no history": 2.0}
K_CAR = {"same team": 0.5, "changed team": 0.5, "no history": 0.5}


def _k_tgt(group):
    return K_TGT[group]


def _k_car(group):
    return K_CAR[group]
WIND_THRESHOLD, WIND_PASS_PENALTY = 15.0, 0.026   # measured within-team
# How fast the season's own evidence outweighs what came before it. Fitted:
# RMSE 5.408 flat -> 5.390 at a 4-week half-life, and it is an INTERIOR
# optimum -- 2 weeks is worse than 3, 10 worse than 6 -- which says the model
# is now about as responsive as the signal justifies. Most of a mid-season
# "breakout" is noise, so chasing it harder makes projections worse, not better.
HALF_LIFE = 4.0


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def recent_mean(series, week, half_life=None, weights=None):
    """Mean of prior weeks, weighting recent ones more.

    The flat average could not see a breakout. A receiver who ran 3 targets a
    game for eight weeks and 9 for the next three averages 4.6, so the model
    kept projecting him at 4.6 while his actual role had doubled -- we tracked
    only 22% of a breakout and 7% of a bust. Weighting by recency lets the
    season's own evidence move the number, which is the only way a bust or a
    breakout ever gets picked up.

    half_life=None restores the old flat mean exactly. `weights` ({week: f})
    counts a game as f of a game, in the mean and in n (EXIT_KEEP_W).
    """
    past = [(w, v) for w, v in series.items() if w < week]
    if not past:
        return 0.0, 0
    if weights:
        gw = [weights.get(w, 1.0) for w, _ in past]
        if half_life is None:
            n_ = sum(gw)
            return (sum(g * v for g, (_, v) in zip(gw, past)) / n_ if n_ else 0.0), n_
        tw = tv = 0.0
        for g, (w, v) in zip(gw, past):
            wt = g * 0.5 ** ((week - w - 1) / half_life)
            tw += wt; tv += v * wt
        return (tv / tw if tw else 0.0), sum(gw)
    if half_life is None:
        return sum(v for _, v in past) / len(past), len(past)
    tw = tv = 0.0
    for w, v in past:
        wt = 0.5 ** ((week - w - 1) / half_life)
        tw += wt; tv += v * wt
    # n stays the GAME COUNT -- how much evidence exists is a separate
    # question from what that evidence currently says.
    return (tv / tw if tw else 0.0), len(past)


def blend(observed, n, prior, k):
    return prior if n + k == 0 else (n * observed + k * prior) / (n + k)


# ---------------------------------------------------------------- loading

def load_players(year):
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("season_type") == "REG"]


def load_teams(year):
    path = os.path.join(DATA, f"team_weekly_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["team"], int(r["week"])): r for r in csv.DictReader(fh)}


def load_games(year):
    """(team, week) -> dict with implied points and wind."""
    path = os.path.join(DATA, "games.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached",
                            "nflverse", "games.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] != str(year) or r.get("game_type") != "REG":
                continue
            tot, spr = num(r["total_line"], None), num(r["spread_line"], None)
            if tot is None or spr is None:
                continue
            wk = int(r["week"])
            wind = num(r["wind"], 0.0) if r["roof"] not in ("dome", "closed") else 0.0
            temp = num(r.get("temp"), None) if r["roof"] not in ("dome", "closed") else None
            # margin = expected points for minus against (positive = favoured)
            out[(r["home_team"], wk)] = {"implied": tot / 2 + spr / 2, "wind": wind,
                                         "temp": temp, "margin": spr, "opp": r["away_team"]}
            out[(r["away_team"], wk)] = {"implied": tot / 2 - spr / 2, "wind": wind,
                                         "temp": temp, "margin": -spr, "opp": r["home_team"]}
    return out


WEEK1_THURSDAY = {2024: "2024-09-05", 2025: "2025-09-04", 2026: "2026-09-10"}


def chart_positions(year):
    """gsis_id -> position from the newest depth-chart snapshot."""
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] in ALL_POSITIONS and r["gsis_id"]:
                snaps[r["dt"]][r["gsis_id"]] = r["pos_abb"]
    return snaps[max(snaps)] if snaps else {}


def current_roster(year):
    """Who is on each team RIGHT NOW, from the newest depth-chart snapshot.

    Distinct from load_depth_chart(), which deliberately freezes at preseason
    because it serves as a PRIOR. This one answers "who could play this week",
    so it must be current.
    """
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] not in ALL_POSITIONS or not r["gsis_id"]:
                continue
            snaps[r["dt"]][r["gsis_id"]] = r["team"]
    return (snaps[max(snaps)], max(snaps)) if snaps else ({}, None)


_AUDIT = None


def _audit_mod():
    """audit_vs_sources, imported lazily so a missing benchmark never stops a run."""
    global _AUDIT
    if _AUDIT is None:
        sys.path.insert(0, HERE)
        try:
            import audit_vs_sources
            _AUDIT = audit_vs_sources
        except Exception:
            _AUDIT = False
    return _AUDIT or None


def cons_key(player_name):
    a = _audit_mod()
    return a.norm(player_name) if a else ""


def load_consensus_for(year, week):
    """-> ({normalised name: half-PPR points}, label describing the source).

    The benchmark, written alongside our own number so the two can be eyeballed
    side by side. It is NEVER an input -- nothing downstream reads these
    columns, and the projection is identical whether or not they resolve.
    """
    a = _audit_mod()
    if not a:
        return {}, "unavailable"
    directory, label = a.resolve_dir(year, week)
    # Built from the individual sources rather than the pre-averaged consensus
    # file, because that file counts a source's 0-point placeholder as a real
    # projection (see audit_vs_sources.load_source). Same sources, same
    # scoring, just the average of the ones that actually projected him.
    per = {}
    for name in a.SOURCES:
        for k, v in a.load_source(directory, name).items():
            per.setdefault(k, []).append(v[0])
    if not per:
        return {}, "none found"
    return ({k: sum(v) / len(v) for k, v in per.items()},
            f"mean of sources that projected him, {label}")


def week_cutoffs(year):
    """week -> the first gameday of that week, as a date string."""
    path = os.path.join(DATA, "games.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached",
                            "nflverse", "games.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season") != str(year) or r.get("game_type") != "REG":
                continue
            day = r.get("gameday")
            if day:
                wk = int(r["week"])
                out[wk] = min(out.get(wk, day), day)
    return out


def qb_ranks_as_of(year, cutoff):
    """gsis_id -> depth rank for QBs, from the last chart before `cutoff`.

    Deliberately NOT load_depth_chart()'s preseason snapshot. That one is a
    PRIOR for players with no usage history and must stay frozen; this one
    answers "who is starting", which changes week to week. Reading the
    preseason chart here put Tua ahead of Penix all season and left Atlanta's
    actual starter projected for 0.2 points.
    """
    chart = load_depth_chart(year, cutoff=cutoff)
    return {p: rk for p, (pos, rk) in chart.items() if pos == "QB"}


def load_team_adjust(year, week):
    """team -> {pass_rate, plays} from data/team_adjust_<yr>_wk<NN>.csv (live only)."""
    path = os.path.join(DATA, f"team_adjust_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            tm = (r.get("team") or "").strip().upper()
            a = {}
            pr = (r.get("pass_rate") or "").strip().rstrip("%")
            if pr:
                v = float(pr)
                a["pass_rate"] = v / 100 if v > 1 else v
            pl = (r.get("plays") or "").strip()
            if pl:
                a["plays"] = float(pl)
            qr = (r.get("qb_rush_share") or "").strip().rstrip("%")
            if qr:
                v = float(qr)
                a["qb_rush_share"] = v / 100 if v > 1 else v
            if tm and a:
                out[tm] = a
    return out


def depth_names(year):
    """gsis_id -> name from the depth-chart file (both nflverse schemas)."""
    out = {}
    for path in (os.path.join(DATA, f"depth_charts_{year}.csv"),
                 os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                              "nflverse", f"depth_charts_{year}.csv")):
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    g = r.get("gsis_id")
                    nm = r.get("player_name") or r.get("full_name")
                    if g and nm:
                        out.setdefault(g, nm)
            break
    return out


def tier_ratios(cur_rows, prev_rows, position="WR"):
    """week -> {ypt, catch, tdpt, n}: this season's team-WR1 rates (weeks before
    it) over last season's."""
    def stats(rows, wk_max=None):
        top = {}
        for r in rows:
            if r["position"] != position:
                continue
            w = int(r["week"])
            if wk_max is not None and w >= wk_max:
                continue
            k = (r["team"], w)
            if k not in top or num(r["targets"]) > num(top[k]["targets"]):
                top[k] = r
        a = collections.Counter()
        for r in top.values():
            a["tgt"] += num(r["targets"]); a["rec"] += num(r["receptions"])
            a["yds"] += num(r["receiving_yards"]); a["td"] += num(r["receiving_tds"])
        return a
    pv = stats(prev_rows)
    if not pv["tgt"]:
        return {}
    out = {}
    for w in range(1, 23):
        cu = stats(cur_rows, w)
        if not cu["tgt"]:
            continue
        out[w] = {"ypt": (cu["yds"] / cu["tgt"]) / (pv["yds"] / pv["tgt"]),
                  "catch": (cu["rec"] / cu["tgt"]) / (pv["rec"] / pv["tgt"]),
                  "tdpt": ((cu["td"] / cu["tgt"]) / (pv["td"] / pv["tgt"])) if pv["td"] else 1.0,
                  "n": cu["tgt"]}
    return out


def injury_limited(year, frac):
    """{(pid, week)}: on that week's injury report and under `frac` of his usual
    snap share (his best earlier game this season, else last season's average)."""
    path = os.path.join(DATA, f"injuries_{year}.csv")
    listed = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("gsis_id") and (r.get("report_status") or r.get("practice_status")):
                    listed.add((r["gsis_id"], int(r["week"])))
    sp, spp = load_snap_pct(year), load_snap_pct(year - 1)
    out = set()
    for pid, wks in sp.items():
        prev = list(spp.get(pid, {}).values())
        for w, v in wks.items():
            if (pid, w) not in listed:
                continue
            before = [wks[x] for x in wks if x < w]
            ref = max(before) if before else (sum(prev) / len(prev) if prev else None)
            if ref and v < frac * ref:
                out.add((pid, w))
    return out


def depth_flags(year, cur_rows):
    """(pid, week) -> "demoted" / "promoted", from the last depth-chart snapshot
    before each week's first game vs the snapshots before his last 3 games."""
    import bisect
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        return {}
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] in POSITIONS and r["gsis_id"]:
                d = snaps[r["dt"][:10]]
                d[r["gsis_id"]] = min(d.get(r["gsis_id"], 9), int(r["pos_rank"]))
    dates = sorted(snaps)
    cut = week_cutoffs(year)

    def at(day):
        i = bisect.bisect_left(dates, day) - 1
        return snaps[dates[i]] if i >= 0 else {}
    played = collections.defaultdict(set)
    for r in cur_rows:
        if num(r["targets"]) > 0 or num(r["carries"]) > 0:
            played[r["player_id"]].add(int(r["week"]))
    chart_at = {w: at(day) for w, day in cut.items()}
    out = {}
    for w in cut:
        now_c = chart_at[w]
        for pid, now in now_c.items():
            prev = [chart_at[x].get(pid) for x in sorted(played[pid]) if x < w and x in chart_at][-3:]
            prev = [p_ for p_ in prev if p_]
            if not prev:
                continue
            was = sum(1 for p_ in prev if p_ == 1) / len(prev)
            if now > 1 and was >= 0.5:
                out[(pid, w)] = "demoted"
            elif now == 1 and was < 0.5:
                out[(pid, w)] = "promoted"
    return out


def load_depth_chart(year=2025, cutoff=None):
    """Last depth-chart snapshot before week 1 -- the prior for no-history players.

    Deliberately a PRESEASON snapshot: it is only ever used as a starting guess
    for players with no usage history, and once a player has games those games
    say more than any chart. Matches how the 17% improvement was measured.
    """
    cutoff = cutoff or WEEK1_THURSDAY.get(year, f"{year}-09-10")
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    best, chart = "", {}
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] not in ALL_POSITIONS or not r["gsis_id"] or r["dt"] >= cutoff:
                continue
            snaps[r["dt"]][r["gsis_id"]] = (r["pos_abb"], min(int(r["pos_rank"]), 5))
    if snaps:
        best = max(snaps)
        chart = snaps[best]
    return chart


# ------------------------------------------------------- derived constants

def shares_by_week(rows):
    """player -> {week: (tgt_share, carry_share)} over SKILL-position denominators."""
    tt = collections.defaultdict(lambda: [0.0, 0.0])
    skill = [r for r in rows if r["position"] in POSITIONS]
    for r in skill:
        t = tt[(r["team"], int(r["week"]))]
        t[0] += num(r["targets"]); t[1] += num(r["carries"])
    tgt, car, pos, team = (collections.defaultdict(dict), collections.defaultdict(dict),
                           {}, collections.defaultdict(collections.Counter))
    for r in skill:
        pid, wk = r["player_id"], int(r["week"])
        d = tt[(r["team"], wk)]
        pos[pid] = r["position"]; team[pid][r["team"]] += 1
        if d[0]:
            tgt[pid][wk] = num(r["targets"]) / d[0]
        if d[1]:
            car[pid][wk] = num(r["carries"]) / d[1]
    modal = {p: c.most_common(1)[0][0] for p, c in team.items()}
    return tgt, car, pos, modal


def fill_observed_zeros(tgt, car, pos, year, snaps_by_week=None):
    """A player who was ON THE FIELD but recorded nothing got a genuine ZERO.

    stats_player_week only carries rows for players with a stat line, so a back
    who took 3 snaps and no carries is indistinguishable from one who was not
    there -- and the model then projects him from his prior instead of from the
    zero he actually posted. ARI wk1 2026: Bam Knight 3 snaps, Corey Kiner 8,
    neither with a carry, both still drawing ~7 projected carries.
    """
    if snaps_by_week is None:
        snaps_by_week = load_snaps_by_week(year)
    added = 0
    for wk, players in snaps_by_week.items():
        for pid, (snaps, position) in players.items():
            if snaps <= 0:
                continue
            # A fullback's game is a real game: he is projected off the depth
            # chart (often as a TE), so his empty weeks must count against him.
            # Andrew Beck, NYJ, played wk2 2026 as "FB" with 0 touches and was
            # still projected for 3 targets because FB rows were skipped.
            if position == "FB" and FB_ZEROS:
                if pid not in pos:
                    continue
            elif position not in POSITIONS:
                continue
            pos.setdefault(pid, position)
            if wk not in tgt[pid]:
                tgt[pid][wk] = 0.0; added += 1
            if wk not in car[pid]:
                car[pid][wk] = 0.0
    return added


def load_snaps_by_week(year):
    """week -> {gsis_id: (offense_snaps, position)}."""
    base = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
    xwalk = {}
    px = os.path.join(base, "players.csv")
    if os.path.exists(px):
        with open(px, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("pfr_id") and r.get("gsis_id"):
                    xwalk[r["pfr_id"]] = r["gsis_id"]
    path = os.path.join(base, f"snaps_{year}.csv")
    out = collections.defaultdict(dict)
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type") != "REG":
                continue
            g = xwalk.get(r.get("pfr_player_id"))
            if g:
                out[int(r["week"])][g] = (float(r.get("offense_snaps") or 0),
                                          r.get("position", ""))
    return out


def load_snap_pct(year):
    """gsis_id -> {week: offensive snap share}."""
    base = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
    xwalk = {}
    px = os.path.join(base, "players.csv")
    if os.path.exists(px):
        with open(px, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("pfr_id") and r.get("gsis_id"):
                    xwalk[r["pfr_id"]] = r["gsis_id"]
    out = collections.defaultdict(dict)
    path = os.path.join(base, f"snaps_{year}.csv")
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            g = xwalk.get(r.get("pfr_player_id"))
            if g and r.get("game_type") == "REG":
                out[g][int(r["week"])] = num(r.get("offense_pct"))
    return out


def drop_exit_weeks(tgt, car, pct_cur, pct_prev=None, frac=None, min_ref=None,
                    positions=None, confirmed=None, returning=None, pregame=None,
                    collect=None):
    """Remove games a player LEFT early from his usage history. -> count.
    With `collect` (a set), the exits are added to it instead of removed
    (EXIT_KEEP_W decides what happens to them).

    A regular (min_ref+ of snaps) who suddenly plays under `frac` of his normal
    share almost always got hurt in that game. Saquon Barkley, wk2 2026: 71% of
    snaps in wk1, then 12 snaps (16%) and out -- and his 4 carries were being
    read as a real week, dragging his wk3 number down. Same principle as the
    QB starter rule: a PAST exit discounts PAST usage; nothing predicts a
    future injury. Walk-forward: week w is judged only against weeks before it
    (and last season's average when there are none).
    """
    frac = SKILL_EXIT_FRAC if frac is None else frac
    min_ref = SKILL_EXIT_MIN_REF if min_ref is None else min_ref
    dropped = 0
    for pid, wks in pct_cur.items():
        if positions is not None and positions.get(pid) not in SKILL_EXIT_POSITIONS:
            continue
        prev_avg = None
        if pct_prev and pct_prev.get(pid):
            v = list(pct_prev[pid].values())
            prev_avg = sum(v) / len(v)
        for w in sorted(wks):
            before = [wks[x] for x in wks if x < w]
            ref = max(before) if before else prev_avg
            if ref is None or ref < min_ref:
                continue
            # FIRST GAME BACK (2026-10-24, Joe on Rico Dowdle wk6: 33% of snaps
            # after missing wks 3-5 is a planned ramp, not an exit): a game
            # right after he was ruled out only counts as an exit under
            # EXIT_RETURN_FRAC of his usual snaps
            f_ = EXIT_RETURN_FRAC if (EXIT_RETURN_FRAC is not None and returning
                                      and (pid, w) in returning) else frac
            # LISTED BEFORE THE GAME (EXIT_PREGAME_KEEP, 2026-10-27, Henderson NE
            # wk6: Questionable + limited practice, then 24% of snaps): a light
            # game he was already listed for is a planned reduced role, not an
            # injury exit -- keep it
            if EXIT_PREGAME_KEEP and pregame and (pid, w) in pregame:
                continue
            if wks[w] < f_ * ref:
                # With `confirmed`, a snap collapse only counts as an injury
                # exit when the injury report backs it up -- he is listed that
                # week or the next. Without that check it flagged 1,203 player-
                # weeks in 2025, catching benchings and receiver rotation.
                if confirmed is not None and (pid, w) not in confirmed:
                    continue
                if collect is not None:
                    collect.add((pid, w)); dropped += 1
                    continue
                for d in (tgt, car):
                    if pid in d and w in d[pid]:
                        del d[pid][w]
                dropped += 1
    return dropped


def rb_backup_need(carry_shares):
    """Extra carry share an unnamed backup takes when a team's projected backs
    leave the lead back more than 1 - RB_MIN_BACKUP of the RB carries and no
    other back has RB_LONE_MIN of his share (see NO TEAM PLAYS ONE BACK)."""
    cl = [c for c in carry_shares if c > 0]
    if not RB_MIN_BACKUP or not cl or sum(1 for c in cl if c >= RB_LONE_MIN * max(cl)) >= 2:
        return 0.0
    return max(0.0, max(cl) / (1 - RB_MIN_BACKUP) - sum(cl))


def new_team_no_games(pid, team, played_this_season, team_games):
    """NEW_TEAM_MULT applies: last season's team is not this one, he has not
    played this season, and the team has played 2+ games (Sills TB wk7 yes;
    Jacobs GB wk7 no -- same team, just back from the exempt list)."""
    prev = _PREV_TEAM.get(pid)
    return bool(prev) and prev != team and not played_this_season and team_games >= 2


def prev_team_map(prev_rows):
    """pid -> his team in his last game of the previous season."""
    out = {}
    for r in sorted(prev_rows, key=lambda r: int(r["week"])):
        out[r["player_id"]] = r["team"]
    return out


def listed_pregame(year):
    """{(gsis_id, week)}: listed BEFORE that week's game as Questionable /
    Doubtful, or limited / did not practice -- a known limitation going in."""
    path = os.path.join(DATA, f"injuries_{year}.csv")
    out = set()
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("gsis_id") and (r.get("report_status") in ("Questionable", "Doubtful")
                                     or (r.get("practice_status") or "").startswith(("Limited", "Did Not"))):
                out.add((r["gsis_id"], int(r["week"])))
    return out


def first_games_back(year):
    """{(gsis_id, week)}: his first game after missing one or more games while
    on the injury report (any listing) -- a return from injury. Rico Dowdle
    2026: Out wks 3-4, Questionable and inactive wk5, back wk6."""
    path = os.path.join(DATA, f"injuries_{year}.csv")
    if not os.path.exists(path):
        return set()
    listed = collections.defaultdict(set)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("report_status") or r.get("practice_status")) and r.get("gsis_id"):
                listed[r["gsis_id"]].add(int(r["week"]))
    out = set()
    for pid, wks in load_snap_pct(year).items():
        played = sorted(w for w, v in wks.items() if v > 0)
        for a, b in zip(played, played[1:]):
            if any(a < w < b for w in listed.get(pid, ())):
                out.add((pid, b))
    return out


def injury_confirmed(year, sleeper_now=None, last_week=None):
    """(gsis_id, week) pairs where a snap collapse in that week is backed by an
    injury listing: the official report for that week or the next (any game
    status or practice status), plus -- for the live week only -- a CURRENT
    Sleeper tag on his most recent game. Saquon Barkley, wk2 2026: 12 snaps
    after 71% in wk1, and Questionable (arm) since."""
    out = set()
    path = os.path.join(DATA, f"injuries_{year}.csv")
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if (r.get("report_status") or r.get("practice_status")) and r.get("gsis_id"):
                    w = int(r["week"])
                    out.add((r["gsis_id"], w)); out.add((r["gsis_id"], w - 1))
    if sleeper_now and last_week:
        for pid in sleeper_now:
            out.add((pid, last_week))
    return out


def drop_pbp_exits(tgt, car, year, min_secs=None, collect=None):
    """Remove games a player was KNOCKED OUT of (per play-by-play) from his
    usage history. -> count dropped. With `collect`, add them to it instead.

    Uses data/injury_exits_<year>.csv (build_injury_exits.py): the pbp line
    "X was injured during the play" with no later "has returned". A snap-count
    version of this flagged 1,203 player-weeks in 2025 and made WRs worse,
    because receiver snap shares swing with formations; an actual recorded
    injury does not. `min_secs` = only exits with at least that much game
    time left, so a late-game knock that cost him nothing is kept.
    """
    min_secs = PBP_EXIT_MIN_SECS if min_secs is None else min_secs
    path = os.path.join(DATA, f"injury_exits_{year}.csv")
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("exited") != "1" or num(r.get("secs_remaining")) < min_secs:
                continue
            pid, wk = r["player_id"], int(r["week"])
            if collect is not None:
                if wk in tgt.get(pid, {}) or wk in car.get(pid, {}):
                    collect.add((pid, wk)); n += 1
                continue
            hit = False
            for d in (tgt, car):
                if pid in d and wk in d[pid]:
                    del d[pid][wk]; hit = True
            n += hit
    return n


def keep_exit_games(tgt, car, exits, pos):
    """EXIT_KEEP_W: an exit game stays at the share he actually had, counted
    as EXIT_KEEP_W[position] of a game; a position with no weight is dropped.
    -> {pid: {week: weight}} for weights under 1 (recent_mean's `weights`)."""
    out = collections.defaultdict(dict)
    for pid, w in exits:
        wt = (EXIT_KEEP_W or {}).get(pos.get(pid), 0.0)
        if wt <= 0:
            for d in (tgt, car):
                d.get(pid, {}).pop(w, None)
        elif wt < 1:
            out[pid][w] = wt
    return dict(out)


def qb_shares_by_week(rows, teams):
    """QB -> {week: (share of team pass attempts, share of team QB carries)}.

    Quarterback usage is close to binary -- a healthy starter takes essentially
    every attempt -- so these shares mostly encode who is starting, and the
    availability layer does the rest when he is not.
    """
    patt, ratt = collections.defaultdict(dict), collections.defaultdict(dict)
    for r in rows:
        if r["position"] != "QB":
            continue
        wk, tm = int(r["week"]), r["team"]
        t = teams.get((tm, wk))
        if not t:
            continue
        tpa, tqr = int(t["pass_att"]), int(t["qb_rush_att"])
        pid = r["player_id"]
        if tpa:
            patt[pid][wk] = num(r["attempts"]) / tpa
        if tqr:
            ratt[pid][wk] = num(r["carries"]) / tqr
    return patt, ratt


def team_games(teams, before=None):
    """team -> games played (before `before`, if given)."""
    out = collections.Counter()
    for (tm, wk) in teams:
        if before is None or wk < before:
            out[tm] += 1
    return out


def qb_efficiency_means(rows):
    """League QB rates from the PRIOR season -- same principle as the skill
    positions: a passer's own efficiency history is not worth modelling."""
    a = collections.Counter()
    s_ = collections.Counter()           # STARTS only (15+ attempts)
    for r in rows:
        if r["position"] != "QB":
            continue
        a["att"] += num(r["attempts"]); a["cmp"] += num(r["completions"])
        a["yds"] += num(r["passing_yards"]); a["int"] += num(r["passing_interceptions"])
        if num(r["attempts"]) >= 15:
            s_["att"] += num(r["attempts"]); s_["int"] += num(r["passing_interceptions"])
            s_["cmp"] += num(r["completions"]); s_["yds"] += num(r["passing_yards"])
        a["car"] += num(r["carries"]); a["ryd"] += num(r["rushing_yards"])
        a["rtd"] += num(r["rushing_tds"]); a["ptd"] += num(r["passing_tds"])
    att = a["att"] or 1
    satt = s_["att"] or 1
    # Interceptions per attempt taken over STARTS: the all-QB rate includes
    # backups' and garbage-time throws, and applied to every starter it put
    # elite QBs at 0.71 INTs a game against 0.57 actual (2024-25).
    int_rate = a["int"] / att
    return {"ypa": a["yds"] / att, "comp_pct": a["cmp"] / att,
            "int_rate": int_rate, "ypc": a["ryd"] / (a["car"] or 1),
            "rush_td_rate": a["rtd"] / (a["car"] or 1),
            "ptd_rate": a["ptd"] / att}


def player_eff_by_week(rows, prior_rows=()):
    """pid -> {week: Counter of raw efficiency inputs}, week 0 = prior season.

    Efficiency is noise for MOST players, which is why the position mean is
    the anchor. But that average is dominated by hundreds of low-volume
    players; the elite tier converts touches above the mean consistently. So
    a player's own rate is blended toward the position mean with
    weight equal to his ACCUMULATED TOUCHES -- 60 targets says something about
    a receiver's yards per target, 8 does not.
    """
    out = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    # one prior season (older seasons were tested and rejected -- see
    # TESTED_SETTINGS.md, EFF_HIST_SEASONS)
    seasons = [(prior_rows, 1.0, 0)]
    for src, wt, back in seasons:
        for r in src:
            if r["position"] not in POSITIONS:
                continue
            c = out[r["player_id"]][0]
            if back == 0:
                c["g"] += 1
            for key, col in (("tgt", "targets"), ("rec", "receptions"),
                             ("rec_yds", "receiving_yards"), ("car", "carries"),
                             ("rush_yds", "rushing_yards"), ("rec_td", "receiving_tds"),
                             ("rush_td", "rushing_tds")):
                c[key] += num(r[col]) * wt
    for src, wk_of in (((), None), (rows, lambda r: int(r["week"]))):
        for r in src:
            if r["position"] not in POSITIONS:
                continue
            c = out[r["player_id"]][wk_of(r)]
            c["tgt"] += num(r["targets"]); c["rec"] += num(r["receptions"])
            c["rec_yds"] += num(r["receiving_yards"]); c["car"] += num(r["carries"])
            c["rush_yds"] += num(r["rushing_yards"])
            c["rec_td"] += num(r["receiving_tds"]); c["rush_td"] += num(r["rushing_tds"])
    return out


def qb_rush_td_proven(prior_seasons, min_seasons=QB_RUSH_TD_MIN_SEASONS,
                      min_carries=50, ratio=1.5):
    """QBs who have PROVEN a goal-line role: pid -> their own TD/carry rate.

    The gate is a qualifying SEASON, not an accumulated rate, and that
    distinction is the whole thing. Requiring `min_carries` at `ratio` times
    the league rate in a full season separates Josh Allen (0.135, 0.118, 0.125
    across three straight years) from a quarterback who had one hot November.
    Measured on 2023-25: for QBs clearing this bar the LEAGUE rate under-
    projects them by 3.4 TDs a season, and their own rate cuts that to 1.6.

    An earlier version gated on accumulated rate over 30 carries, swept in the
    flukes, and concluded -- wrongly -- that upward adjustment never works.
    """
    per = collections.defaultdict(dict)
    for i, src in enumerate(prior_seasons):
        for r in src:
            if r["position"] == "QB":
                d = per[r["player_id"]].setdefault(i, [0.0, 0.0])
                d[0] += num(r["carries"]); d[1] += num(r["rushing_tds"])
    lg = {}
    for i, src in enumerate(prior_seasons):
        c = sum(num(r["carries"]) for r in src if r["position"] == "QB")
        t = sum(num(r["rushing_tds"]) for r in src if r["position"] == "QB")
        lg[i] = t / c if c else 0.0
    out = {}
    for pid, seasons in per.items():
        good = [i for i, (c, t) in seasons.items()
                if c >= min_carries and lg[i] and t / c > ratio * lg[i]]
        if len(good) < min_seasons:
            continue
        tc = sum(c for c, _ in seasons.values())
        tt = sum(t for _, t in seasons.values())
        if tc >= 100:
            out[pid] = tt / tc
    return out


def rb_rush_td_proven(prior_seasons, min_seasons=1, min_carries=100, ratio=1.5):
    """RBs with a PROVEN goal-line role: pid -> [carries, rushing TDs] history.

    Same question that fixed Josh Allen, asked of running backs, and it passes:
    for backs with a full season at 1.5x the position rate on 100+ carries,
    the league rate under-projected them by 2.1 rushing TDs a season (2023-25)
    and their own rate, shrunk by K_RB_RUSH_TD carries, took RMSE 3.77 -> 3.08
    with the bias at zero. RECEIVING touchdowns failed the identical test at
    every position (WR, TE and RB), so this is rushing only -- goal-line
    carries are a role a team hands a player; who catches the TD pass is not.
    """
    per = collections.defaultdict(dict)
    lg = {}
    for i, src in enumerate(prior_seasons):
        c_ = t_ = 0.0
        for r in src:
            if r["position"] != "RB":
                continue
            d = per[r["player_id"]].setdefault(i, [0.0, 0.0])
            d[0] += num(r["carries"]); d[1] += num(r["rushing_tds"])
            c_ += num(r["carries"]); t_ += num(r["rushing_tds"])
        lg[i] = t_ / c_ if c_ else 0.0
    out = {}
    for pid, seasons in per.items():
        good = [i for i, (c, t) in seasons.items()
                if c >= min_carries and lg[i] and t / c > ratio * lg[i]]
        if len(good) >= min_seasons:
            out[pid] = [sum(c for c, _ in seasons.values()),
                        sum(t for _, t in seasons.values())]
    return out


def carry_games(rows, prior_seasons=()):
    """RB -> {week key: carries} for every game he recorded a carry; history
    seasons get negative keys so they never collide with this season's weeks."""
    out = collections.defaultdict(dict)
    for back, src in enumerate(reversed(prior_seasons), start=1):
        for r in src:
            if r["position"] == "RB" and num(r["carries"]) > 0:
                out[r["player_id"]][-100 * back + int(r["week"])] = num(r["carries"])
    for r in rows:
        if r["position"] == "RB" and num(r["carries"]) > 0:
            out[r["player_id"]][int(r["week"])] = num(r["carries"])
    return out


def qb_pass_hist(rows, prior_seasons=(), decay=QB_RUSH_TD_DECAY):
    """QB -> {week: [attempts, completions, yards, INTs, TDs]}; week 0 is weighted history.

    Shrunk by ATTEMPTS rather than games, which is the point: a starter with
    500 attempts behind him has earned his own yards-per-attempt, a backup with
    40 has not. The earlier rejection of this used one prior season and shrank
    by games, which gave even Josh Allen barely any of his own number.
    """
    out = collections.defaultdict(lambda: collections.defaultdict(
        lambda: [0.0, 0.0, 0.0, 0.0, 0.0]))
    for back, src in enumerate(reversed(prior_seasons)):
        w = decay ** back
        for r in src:
            if r["position"] != "QB":
                continue
            c = out[r["player_id"]][0]
            c[0] += num(r["attempts"]) * w
            c[1] += num(r["completions"]) * w
            c[2] += num(r["passing_yards"]) * w
            c[3] += num(r["passing_interceptions"]) * w
            c[4] += num(r["passing_tds"]) * w
    for r in rows:
        if r["position"] != "QB":
            continue
        c = out[r["player_id"]][int(r["week"])]
        c[0] += num(r["attempts"]); c[1] += num(r["completions"])
        c[2] += num(r["passing_yards"]); c[3] += num(r["passing_interceptions"])
        c[4] += num(r["passing_tds"])
    return out


def qb_rush_hist(rows, prior_seasons=(), decay=QB_RUSH_TD_DECAY):
    """QB -> {week: [carries, rushing TDs]}. Week 0 holds the weighted history.

    Rushing touchdowns are the most player-specific thing a quarterback does --
    Josh Allen ran at 0.118 then 0.125 per carry while Jared Goff sat on 0.000
    in both seasons, against a league rate of 0.052. Giving everyone the league
    rate projected Allen for 3.8 rushing TDs in a season he scored 12, and gave
    Goff 4.1 in a season he scored none.

    The catch is that ONE season cannot tell a genuinely elite runner from a
    fluke, and the flukes regress hard: personalising off a single prior season
    over-projected the whole high-rate group by +2.07 points a game. So history
    accumulates across seasons with a recency decay, and the shrinkage is by
    ACCUMULATED CARRIES -- which gives a multi-year runner most of his own rate
    and a one-year spike only a partial nudge, rather than all or nothing.

    `prior_seasons` is oldest-first; the most recent gets full weight.
    """
    out = collections.defaultdict(lambda: collections.defaultdict(
        lambda: [0.0, 0.0]))
    for back, src in enumerate(reversed(prior_seasons)):
        w = decay ** back
        for r in src:
            if r["position"] != "QB":
                continue
            c = out[r["player_id"]][0]
            c[0] += num(r["carries"]) * w
            c[1] += num(r["rushing_tds"]) * w
    for r in rows:
        if r["position"] != "QB":
            continue
        c = out[r["player_id"]][int(r["week"])]
        c[0] += num(r["carries"]); c[1] += num(r["rushing_tds"])
    return out


def blended_rates(hist, week, mean, k_tgt, k_car, prior_w=None):
    """A player's own rates, shrunk toward the position mean by his volume."""
    # C. history (week 0) and this season are pooled, but history is scaled by
    # EFF_PRIOR_WEIGHT when computing the RATE -- so this season's form can
    # count for more -- while the touch count behind the shrinkage stays the
    # real one. 1.0 = the old pooled behaviour.
    a = collections.Counter(); n = collections.Counter()
    for wk, c in (hist or {}).items():
        if wk == 0 and EFF_PRIOR_MIN_G and c.get("g", 99) < EFF_PRIOR_MIN_G:
            continue
        if wk < week:
            w = (EFF_PRIOR_WEIGHT if prior_w is None else prior_w) if wk == 0 else 1.0
            wr = (EFF_PRIOR_WEIGHT_RUSH if EFF_PRIOR_WEIGHT_RUSH is not None
                  else EFF_PRIOR_WEIGHT) if wk == 0 else 1.0
            for key, v in c.items():
                w_ = wr if key in ("car", "rush_yds") else w
                a[key] += v * w_
                n[key] += v
    tgt, car = a["tgt"], a["car"]
    ntgt, ncar = n["tgt"], n["car"]
    ypt = blend(a["rec_yds"] / tgt, ntgt, mean["ypt"], k_tgt) if tgt else mean["ypt"]
    catch = blend(a["rec"] / tgt, ntgt, mean["catch"], k_tgt) if tgt else mean["catch"]
    ypc = blend(a["rush_yds"] / car, ncar, mean["ypc"], k_car) if car else mean["ypc"]
    return {"ypt": ypt, "catch": catch, "ypc": ypc}


def efficiency_means(rows):
    """Position-level efficiency, fit on the PRIOR season (out of sample)."""
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        if r["position"] not in POSITIONS:
            continue
        a = agg[r["position"]]
        a["tgt"] += num(r["targets"]); a["rec"] += num(r["receptions"])
        a["rec_yds"] += num(r["receiving_yards"]); a["car"] += num(r["carries"])
        a["rush_yds"] += num(r["rushing_yards"])
        a["rec_td"] += num(r["receiving_tds"]); a["rush_td"] += num(r["rushing_tds"])
    return {p: {"ypt": a["rec_yds"] / a["tgt"] if a["tgt"] else 0,
                "catch": a["rec"] / a["tgt"] if a["tgt"] else 0,
                "ypc": a["rush_yds"] / a["car"] if a["car"] else 0,
                "tdpt": a["rec_td"] / a["tgt"] if a["tgt"] else 0,
                "tdpc": a["rush_td"] / a["car"] if a["car"] else 0}
            for p, a in agg.items()}


def league_constants(teams_prior, rows_prior=()):
    """League means and ratios from the prior season."""
    n = len(teams_prior) or 1
    plays = sum(int(r["plays"]) for r in teams_prior.values()) / n
    pr = sum(float(r["pass_rate"]) for r in teams_prior.values()) / n
    qbr = sum(float(r["qb_rush_share"]) for r in teams_prior.values()) / n
    pass_att = sum(int(r["pass_att"]) for r in teams_prior.values())
    drop = sum(int(r["dropbacks"]) for r in teams_prior.values())
    td = sum(int(r["total_td"]) for r in teams_prior.values())
    ptd = sum(int(r["pass_td"]) for r in teams_prior.values())
    # QBs take ~21% of all rushing TDs (sneaks, scrambles) and it is stable
    # year to year. Handing the whole rushing-TD pool to the backfield
    # over-projected RB touchdowns by 28%.
    qb_rtd = sum(num(r["rushing_tds"]) for r in rows_prior if r["position"] == "QB")
    all_rtd = sum(num(r["rushing_tds"]) for r in rows_prior)
    # Fumbles LOST per touch, so the projection is scored the way the actual
    # game is. They were projected as zero for everyone while actual points and
    # every outside source subtract them -- a small bias always in our favour.
    sk = [r for r in rows_prior if r["position"] in POSITIONS]
    sk_f = sum(num(r["rushing_fumbles_lost"]) + num(r["receiving_fumbles_lost"]) for r in sk)
    sk_t = sum(num(r["carries"]) + num(r["receptions"]) for r in sk)
    qb = [r for r in rows_prior if r["position"] == "QB"]
    qb_f = sum(num(r["sack_fumbles_lost"]) + num(r["rushing_fumbles_lost"]) for r in qb)
    qb_t = sum(num(r["attempts"]) + num(r["carries"]) for r in qb)
    return {"plays": plays, "pass_rate": pr, "qb_rush_share": qbr,
            "fum_skill": sk_f / sk_t if sk_t else 0.0,
            "fum_qb": qb_f / qb_t if qb_t else 0.0,
            "sack_rate": 1 - pass_att / drop if drop else 0.065,
            "pass_td_frac": ptd / td if td else 0.6,
            "qb_rush_td_frac": qb_rtd / all_rtd if all_rtd else 0.21}


def fit_implied_to_td(teams, games):
    """Linear map from a team's implied points to expected touchdowns."""
    xs, ys = [], []
    for (tm, wk), r in teams.items():
        g = games.get((tm, wk))
        if g:
            xs.append(g["implied"]); ys.append(int(r["total_td"]))
    if len(xs) < 10:
        return lambda p: p / 7.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0
    a = my - b * mx
    return lambda p: max(0.0, a + b * p)


# ------------------------------------------------------------- projection


def apply_preseason(priors, pre, team_of, pos):
    """Blend preseason target / carry shares into the share priors (PRESEASON_W)."""
    tt, tc = collections.defaultdict(float), collections.defaultdict(float)
    for pid, v in pre.items():
        tm = team_of.get(pid)
        if tm and pos.get(pid) in POSITIONS:
            tt[tm] += v["tgt"]; tc[tm] += v["car"]
    out = dict(priors)
    for pid, (g, pt, pc, nt, nc) in priors.items():
        v, tm = pre.get(pid), team_of.get(pid)
        if not v or not tm or pos.get(pid) not in POSITIONS:
            continue
        w = PRESEASON_W
        st = v["tgt"] / tt[tm] if tt[tm] else pt
        sc = v["car"] / tc[tm] if tc[tm] else pc
        out[pid] = (g, (1 - w) * pt + w * st, (1 - w) * pc + w * sc, nt, nc)
    return out


def apply_vacated(priors, tgt_prev, car_prev, team_prev, team_cur, chart, pos, pos_prev):
    """VACATED OFFSEASON ROLES (VAC_PRIOR_W, 2026-10-24, Joe: Egbuka when Mike
    Evans left TB; Golden / Watson when Romeo Doubs left GB). A prior was each
    player's own share last season, so a holdover never inherited the targets of
    a starter who LEFT in the offseason -- only the preseason half knew. Per team
    and position: last season's shares of the players who left, minus what the
    newcomers' priors already take, are handed to the holdovers in proportion
    to their own priors (x VAC_PRIOR_W)."""
    out = dict(priors)
    for kind, prev, idx in (("tgt", tgt_prev, 1), ("car", car_prev, 2)):
        dep = collections.defaultdict(float)
        for pid, wks in prev.items():
            tm = team_prev.get(pid)
            p = pos_prev.get(pid) or pos.get(pid)
            if not tm or p not in POSITIONS or len(wks) < 4 or (kind == "car" and p != "RB"):
                continue
            now = team_cur.get(pid)
            if (now and now != tm) or (not now and pid not in chart):
                dep[(tm, p)] += sum(wks.values()) / len(wks)
        new_, hold = collections.defaultdict(float), collections.defaultdict(list)
        for pid, v in priors.items():
            tm, p = team_cur.get(pid), pos.get(pid)
            if not tm or p not in POSITIONS:
                continue
            if v[0] == "same team":
                hold[(tm, p)].append(pid)
            else:
                new_[(tm, p)] += v[idx]
        for key, d in dep.items():
            vac = d - new_.get(key, 0.0)
            hs = hold.get(key, [])
            tot = sum(out[q][idx] for q in hs)
            if vac <= 0 or tot <= 0:
                continue
            for q in hs:
                g, pt, pc, nt, nc = out[q]
                add = VAC_PRIOR_W * vac * out[q][idx] / tot
                out[q] = (g, pt + add, pc, nt, nc) if idx == 1 else (g, pt, pc + add, nt, nc)
    return out


def preseason_rates(pre, pos):
    """pid -> preseason {ypt, catch} for receivers with a real target projection."""
    return {pid: {"ypt": v["rec_yds"] / v["tgt"], "catch": v["rec"] / v["tgt"]}
            for pid, v in pre.items() if v["tgt"] >= 20 and pos.get(pid) in POSITIONS}


def build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos, team_cur,
                 team_prev, chart, extra_ids=(), depth_weight=0.0):
    """Per player: (group, target_share_prior, carry_share_prior)."""
    # These fallbacks MUST come from the prior season. Deriving them from
    # tgt_cur/car_cur leaks the week being projected into its own prior, and in
    # week 1 there is no current season to derive them from at all.
    rank_tgt, rank_car = collections.defaultdict(list), collections.defaultdict(list)
    for pid, wks in tgt_prev.items():
        if pid in chart and len(wks) >= 4:
            rank_tgt[chart[pid]].append(sum(wks.values()) / len(wks))
    for pid, wks in car_prev.items():
        if pid in chart and len(wks) >= 4:
            rank_car[chart[pid]].append(sum(wks.values()) / len(wks))
    rt = {k: sum(v) / len(v) for k, v in rank_tgt.items()}
    rc = {k: sum(v) / len(v) for k, v in rank_car.items()}

    pmean_t, pmean_c = collections.defaultdict(list), collections.defaultdict(list)
    for pid, wks in tgt_prev.items():
        if pid in pos:
            pmean_t[pos[pid]].extend(wks.values())
    for pid, wks in car_prev.items():
        if pid in pos:
            pmean_c[pos[pid]].extend(wks.values())
    pt = {p: sum(v) / len(v) for p, v in pmean_t.items() if v}
    pc = {p: sum(v) / len(v) for p, v in pmean_c.items() if v}

    out = {}
    # extra_ids covers players on the depth chart with no current-season
    # rows yet -- week-1 inactives and un-debuted rookies. Without them a
    # returning RB1 like Josh Jacobs simply vanishes from the slate.
    for pid in set(tgt_cur) | set(car_cur) | set(extra_ids):
        p = pos.get(pid)
        hist_t, hist_c = tgt_prev.get(pid, {}), car_prev.get(pid, {})
        if len(hist_t) >= 4:
            group = ("same team" if team_prev.get(pid) == team_cur.get(pid)
                     else "changed team")
            pri_t = sum(hist_t.values()) / len(hist_t)
            pri_c = (sum(hist_c.values()) / len(hist_c)) if hist_c else pc.get(p, 0)
            # The depth chart knows things last season's usage does not -- a back
            # listed 5th is not getting last year's carries no matter what he did
            # elsewhere. Pull the prior toward the rank average.
            key = chart.get(pid)
            if depth_weight and key in rt:
                pri_t = (1 - depth_weight) * pri_t + depth_weight * rt[key]
            if depth_weight and key in rc:
                pri_c = (1 - depth_weight) * pri_c + depth_weight * rc[key]
        else:
            group = "no history"
            key = chart.get(pid)
            # Off the depth chart at his position -> the DEEPEST slot, not the
            # position mean. That mean is taken over backs who actually got
            # carries, so it is an RB2's workload (~37% of carries): fullbacks
            # and a linebacker listed at RB (Ben VanSumeren, DJ Herman, wk3
            # 2026) were inheriting it. NO_HISTORY_DEEPEST=False restores it.
            off_chart = key not in rt
            if NO_HISTORY_DEEPEST and off_chart and p:
                deep = [k_ for k_ in rt if k_[0] == p]
                key = max(deep, key=lambda k_: k_[1]) if deep else key
            pri_t = rt.get(key, pt.get(p, 0))
            pri_c = rc.get(key, pc.get(p, 0))
            # Backs are the exception: some who were off the preseason chart
            # became real contributors (signings, injuries), so the deepest slot
            # under-shoots them. They start from NO_HISTORY_RB_RANK instead.
            if NO_HISTORY_DEEPEST and off_chart and p == "RB" and NO_HISTORY_RB_RANK:
                pri_c = rc.get(("RB", NO_HISTORY_RB_RANK), pri_c)
                pri_t = rt.get(("RB", NO_HISTORY_RB_RANK), pri_t)
        out[pid] = (group, pri_t, pri_c, len(hist_t), len(hist_c))
    return out


def project_week(week, *, teams_cur, games, tgt_cur, car_cur, pos, priors,
                 eff, lg, imp_to_td, tgt_per_att, active, avail=None,
                 qb_patt=None, qb_ratt=None, qb_eff=None,
                 qb_games=None, team_qbr_prev=None, qb_rank=None,
                 player_eff, qb_rush, qb_pass, qb_td_proven, rb_td_proven,
                 team_prior=None, team_of=None, carry_hist=None,
                 rz_use=None, route_pct=None, route_full=None,
                 half_life=None):
    """Projections for every active skill player in `week`. No week-`week` data used."""
    if half_life is None:            # read at call time, so --set HALF_LIFE works
        half_life = HALF_LIFE
    # --- team volume from weeks strictly before `week`
    tv = {}
    # every team playing this week gets an entry, even with NO history -- in
    # week 1 there is none, and blend() with n=0 correctly returns the league
    # mean. Building tv only from teams with history silently projected nobody.
    for (tm, wk) in games:
        if wk == week:
            tv.setdefault(tm, [])
    for (tm, wk), r in teams_cur.items():
        if wk >= week:
            continue
        tv.setdefault(tm, []).append(r)
    # in-season league rates (LG_TD_SPLIT_K / LG_EFF_K) -- see the constants
    n_tg = sum(1 for (tm, wk) in teams_cur if wk < week)
    if LG_VOL_K and n_tg:
        cur_tg = [r for (tm, wk), r in teams_cur.items() if wk < week]
        pl = sum(num(r["plays"]) for r in cur_tg) / len(cur_tg)
        pr = sum(num(r["pass_rate"]) for r in cur_tg) / len(cur_tg)
        lg = dict(lg)
        lg["plays"] = blend(pl, n_tg, lg["plays"], LG_VOL_K)
        lg["pass_rate"] = blend(pr, n_tg, lg["pass_rate"], LG_VOL_K)
    # A. A team's run/pass lean depends on who is at quarterback. Minnesota
    # passed on 44% of plays in wks 1-2 of 2026 with Carson Wentz under centre;
    # carrying that forward once Kyler Murray returned projected them as a
    # run team. With TEAM_RATE_STARTER_ONLY the pass rate and QB-rush share are
    # read only from games this week's starter started and stayed in.
    starter_wks = {}
    if TEAM_RATE_STARTER_ONLY and qb_patt is not None:
        best = {}
        for pid, tm in active.items():
            if pos.get(pid) != "QB":
                continue
            if avail is not None and avail.get(pid, 1.0) <= 0:
                continue
            rk = (qb_rank or {}).get(pid, 9)
            if tm not in best or rk < best[tm][0]:
                best[tm] = (rk, pid)
        for tm, (_, pid) in best.items():
            starter_wks[tm] = {w for w, v in qb_patt.get(pid, {}).items()
                               if v >= QB1_MIN_WEEK_SHARE}
    # BACKUP QB STARTING (2026-10-24, Joe: "Huntley at 17.1 seems quite high"):
    # receivers' yards per target and catch rate were earned with the regular
    # starter. A team whose starter this week started under BACKUP_START_FRAC
    # of its games so far (3+ played) gets x BACKUP_EFF_MULT. None = off.
    backup_teams = set()
    if BACKUP_EFF_MULT is not None and starter_wks:
        n_games = collections.Counter(t_ for (t_, w_) in games if w_ < week)
        backup_teams = {tm for tm, sw in starter_wks.items()
                        if n_games.get(tm, 0) >= 3
                        and len({w for w in sw if w < week}) < BACKUP_START_FRAC * n_games[tm]}
    # --- who is OUT this week with a real role, and the team's games without him
    wowy_wk, played_wk = {}, collections.defaultdict(set)
    if WOWY_K_TEAM and team_of:
        for d_ in (tgt_cur, car_cur):
            for pid, wks in d_.items():
                played_wk[pid] |= {w for w in wks if w < week}
        absent = collections.defaultdict(list)
        for pid, t_ in team_of.items():
            if pos.get(pid) not in POSITIONS:
                continue
            if pid in active and (avail is None or avail.get(pid, 1.0) > 0):
                continue
            rec = sorted(played_wk.get(pid, ()))[-2:]
            if not rec:
                continue
            cs_ = sum(car_cur.get(pid, {}).get(w, 0.0) for w in rec) / len(rec)
            if cs_ >= WOWY_MIN_CAR:
                absent[t_].append(pid)
        for tm, abs_ in absent.items():
            wk_ = {int(h["week"]) for h in tv.get(tm, []) if int(h["week"]) < week}
            wk_ = {w for w in wk_ if all(w not in played_wk.get(q, ()) for q in abs_)}
            if wk_:
                wowy_wk[tm] = wk_
    # RETURNING WORKHORSE, TEAM SIDE (2026-10-24, Joe on Saquon: "when he
    # returns [he] should get the full workload"). PHI wk7: McKee's only start
    # (wk6, 78% passing) came without Saquon, as did Hurts' 69% wk5; with Hurts
    # AND Saquon PHI threw 50-58%. Games a returning workhorse back (same test
    # as RETURN_STAR_*) missed count TEAM_RATE_RETURN_W toward the team's pass
    # rate. None = off (every game counts 1).
    ret_abs = collections.defaultdict(set)
    if TEAM_RATE_RETURN_W is not None and RETURN_STAR_SHARE:
        tw_all = collections.defaultdict(list)
        for (tm_, wk_) in games:
            if wk_ < week:
                tw_all[tm_].append(wk_)
        for q, tm_ in active.items():
            if pos.get(q) != "RB" or (avail is not None and avail.get(q, 1.0) <= 0):
                continue
            g_, p_t, p_c, _, _ = priors.get(q, ("no history", 0.0, 0.0, 0, 0))
            if g_ == "no history" or p_c < RETURN_STAR_PRIOR:
                continue
            tw_ = sorted(tw_all.get(tm_, []))
            played = {w for w in set(car_cur.get(q, {})) | set(tgt_cur.get(q, {})) if w < week}
            if not played:
                # a back gone ALL season (Jacobs wk7) would wipe out every game
                # the team has played -- mid-season absences only
                continue
            own = [v for w, v in car_cur.get(q, {}).items() if w < week]
            if not own or blend(sum(own) / len(own), len(own), p_c, 2.0) < RETURN_STAR_SHARE:
                continue
            run = []
            for w in tw_ + [None]:
                if w is not None and w not in played and any(x < w for x in played):
                    run.append(w)
                    continue
                if len(run) >= (RETURN_MIN_MISSED or 2):
                    ret_abs[tm_] |= set(run)
                run = []
    team_proj = {}
    for tm, hist in tv.items():
        n = len(hist)
        qhist = ([h for h in hist if int(h["week"]) in starter_wks[tm]]
                 if tm in starter_wks else hist)
        nq = len(qhist)
        # The anchor was the LEAGUE mean for every team, so with two games
        # played Dallas and Cincinnati (36.7 and 37.6 attempts a game in 2025)
        # projected like a 32-attempt league-average offense and every alpha
        # receiver on a pass-heavy team came out low. TEAM_PRIOR_W pulls the
        # anchor toward the team's own last season.
        tpri = (team_prior or {}).get(tm)
        pl_anchor = lg["plays"]
        pr_anchor = lg["pass_rate"] if not tpri else (
            TEAM_PRIOR_W_RATE * tpri[1] + (1 - TEAM_PRIOR_W_RATE) * lg["pass_rate"])
        plays = blend(sum(int(h["plays"]) for h in hist) / n if n else 0, n,
                      pl_anchor, K_PLAYS)
        ph = qhist if TEAM_RATE_STARTER_ONLY else hist
        wt_ = [TEAM_RATE_RETURN_W if int(h["week"]) in ret_abs.get(tm, ()) else 1.0 for h in ph]
        obs_pr = (sum(w_ * float(h["pass_rate"]) for w_, h in zip(wt_, ph)) / sum(wt_)
                  if ph and sum(wt_) else 0)
        prate = blend(obs_pr, sum(wt_), pr_anchor, K_PASS_RATE)
        adj = _TEAM_ADJ.get(tm, {})
        if adj.get("pass_rate"):
            prate = adj["pass_rate"]
        if adj.get("plays"):
            plays = adj["plays"]
        qbr_override = adj.get("qb_rush_share")
        # QB rushing is a property of the quarterback, so the league mean is a
        # poor prior: it drags Washington and Philadelphia down toward pocket
        # passers. Use the team's own prior season where we have it.
        qb_prior = (team_qbr_prev or {}).get(tm, lg["qb_rush_share"])
        qh = qhist if TEAM_RATE_STARTER_ONLY else hist
        qbr = blend(sum(float(h["qb_rush_share"]) for h in qh) / len(qh) if qh else 0, len(qh),
                    qb_prior, K_QB_RUSH)
        if qbr_override:
            qbr = qbr_override
        elif WOWY_K_TEAM and tm in wowy_wk:
            hw = [h for h in hist if int(h["week"]) in wowy_wk[tm]]
            ww_ = [TEAM_RATE_RETURN_W if int(h["week"]) in ret_abs.get(tm, ()) else 1.0 for h in hw]
            if hw and sum(ww_):
                n_ = sum(ww_)
                prate = (sum(w_ * float(h["pass_rate"]) for w_, h in zip(ww_, hw)) + WOWY_K_TEAM * prate) / (n_ + WOWY_K_TEAM)
                qbr = (n_ * sum(float(h["qb_rush_share"]) for h in hw) / n_ + WOWY_K_TEAM * qbr) / (n_ + WOWY_K_TEAM)
        g = games.get((tm, week))
        if g and g["wind"] >= WIND_THRESHOLD:
            prate -= WIND_PASS_PENALTY
        dropbacks = plays * prate
        pass_att = dropbacks * (1 - lg["sack_rate"])
        rush_att = plays * (1 - prate)
        # GAME SCRIPT on the RUN side only: a team expected to trail runs less
        # (and one expected to lead, more), without inventing extra pass
        # attempts (a run<->pass shift was tested: worse -- TESTED_SETTINGS.md).
        if GS_RUSH and g and "margin" in g:
            rush_att *= max(0.6, 1 + GS_RUSH * g["margin"])
        tds = imp_to_td(g["implied"]) if g else lg["plays"] * 0 + 2.4
        # The docstring always said touchdowns split pass/rush by the projected
        # PASS RATE; the code used one league ratio for every team, so Dallas
        # and a run-first team got the same passing-TD share -- and game script
        # changed run volume without touching the rushing-TD share.
        ptf = lg["pass_td_frac"]
        if TD_SPLIT_SLOPE:
            ptf = min(max(ptf + TD_SPLIT_SLOPE * (prate - lg["pass_rate"]), 0.35), 0.85)
        team_proj[tm] = {
            "plays": plays,
            "targets": pass_att * tgt_per_att,
            "pass_att": pass_att,
            "nonqb_rush": rush_att * (1 - qbr),
            "qb_rush": rush_att * qbr,
            "pass_td": tds * ptf,
            "rush_td": tds * (1 - ptf) * (1 - lg["qb_rush_td_frac"]),
            # the 21% of rushing TDs taken OUT of the backfield belongs to QBs
            "qb_rush_td": tds * (1 - ptf) * lg["qb_rush_td_frac"],
        }


    # --- game-level plays (PLAYS_TOTAL_W)
    if PLAYS_TOTAL_W:
        wk_games = {tm: g for (tm, wk), g in games.items() if wk == week}
        tot = {tm: g["implied"] + wk_games[g["opp"]]["implied"]
               for tm, g in wk_games.items() if g.get("opp") in wk_games}
        avg_tot = sum(tot.values()) / len(tot) if tot else 0.0
        base = {tm: tp["plays"] for tm, tp in team_proj.items()}
        for tm, tp in team_proj.items():
            g = wk_games.get(tm)
            if not g or not base[tm]:
                continue
            new = base[tm]
            if tm in tot and avg_tot:
                new *= 1 + PLAYS_TOTAL_W * (tot[tm] / avg_tot - 1)
            f_ = new / base[tm]
            for k in ("plays", "targets", "pass_att", "nonqb_rush", "qb_rush"):
                tp[k] *= f_

    # --- same-lineup weeks (SAME_LINEUP_POS): which past weeks of each player
    # were played with this week's bigger-role teammates on the field
    lineup_keep = {}
    if SAME_LINEUP_POS:
        role = {}
        for pid, tm in active.items():
            po = pos.get(pid)
            if po not in SAME_LINEUP_POS or tm not in team_proj:
                continue
            if avail is not None and avail.get(pid, 1.0) <= 0:
                continue
            g_, p_t, p_c, _, _ = priors.get(pid, ("no history", 0.0, 0.0, 0, 0))
            series, pri, kk = ((car_cur, p_c, _k_car(g_)) if po == "RB"
                               else (tgt_cur, p_t, _k_tgt(g_)))
            o_, n_ = recent_mean(series.get(pid, {}), week, half_life, _EXIT_W.get(pid))
            role[pid] = (tm, po, blend(o_, n_, pri, kk))
        for pid, (tm, po, r_) in role.items():
            mates = [q for q, (t2, p2, r2) in role.items()
                     if q != pid and t2 == tm and p2 == po and r2 >= SAME_LINEUP_MIN]
            weeks = set(tgt_cur.get(pid, {})) | set(car_cur.get(pid, {}))
            bigger = [q for q in mates if role[q][2] >= r_]
            if not bigger:
                continue
            fac = {}
            for w in weeks:
                if w >= week:
                    continue
                m_ = 1.0
                for q in bigger:
                    if not (w in tgt_cur.get(q, {}) or w in car_cur.get(q, {})):
                        m_ *= max(1.0 - role[q][2], 0.2)
                if m_ < 1.0:
                    fac[w] = m_
            if fac:
                lineup_keep[pid] = ("deflate", fac)

    # --- returning players (RETURN_DEFLATE): teammates' games without him.
    # Zero games this season (Jacobs wk7 2026): every teammate week. With
    # RETURN_MIN_MISSED, also a MID-season absence of that many straight team
    # games after he had played: only the weeks inside the absence.
    ret_fac = {}   # pid -> {week: factor}, for the route model too
    if RETURN_DEFLATE:
        team_wks = collections.defaultdict(list)
        if isinstance(games, dict):
            for (tm_, wk_) in games:
                if wk_ < week:
                    team_wks[tm_].append(wk_)
        for q, tm in active.items():
            po = pos.get(q)
            if po not in RETURN_POS or tm not in team_proj:
                continue
            if avail is not None and avail.get(q, 1.0) <= 0:
                continue
            tw = sorted(team_wks.get(tm, []))
            sh_q = car_cur.get(q, {}) if po == "RB" else tgt_cur.get(q, {})
            played = {w for w in set(tgt_cur.get(q, {})) | set(car_cur.get(q, {})) if w < week}
            g_, p_t, p_c, _, _ = priors.get(q, ("no history", 0.0, 0.0, 0, 0))
            pri = p_c if po == "RB" else p_t
            if not played:
                if len(tw) < RETURN_MIN_TEAM_GAMES or g_ == "no history":
                    continue
                gone, role_q = set(tw), pri
            else:
                if not RETURN_MIN_MISSED:
                    continue
                gone, run = set(), []
                for w in tw + [None]:
                    if w is not None and w not in played and any(x < w for x in played):
                        run.append(w)
                        continue
                    if len(run) >= RETURN_MIN_MISSED:
                        gone |= set(run)
                    run = []
                if not gone:
                    continue
                own = [v for w, v in sh_q.items() if w < week]
                role_q = blend(sum(own) / len(own), len(own), pri, 2.0) if own else pri
            if role_q < RETURN_MIN_SHARE:
                continue
            str_ = RETURN_DEFLATE if not played else (
                RETURN_STAR_DEFLATE if RETURN_STAR_SHARE and role_q >= RETURN_STAR_SHARE and pri >= RETURN_STAR_PRIOR
                else RETURN_MID_DEFLATE)
            f_q = max(1.0 - str_ * role_q, 0.2)
            for pid, t2 in active.items():
                if pid == q or t2 != tm or pos.get(pid) != po:
                    continue
                fac = dict(lineup_keep.get(pid, ("deflate", {}))[1])
                for w in set(tgt_cur.get(pid, {})) | set(car_cur.get(pid, {})):
                    if w < week and w in gone:
                        fac[w] = fac.get(w, 1.0) * f_q
                        ret_fac.setdefault(pid, {})[w] = ret_fac.get(pid, {}).get(w, 1.0) * f_q
                lineup_keep[pid] = ("deflate", fac)

    # --- pass 1: raw blended shares
    raw = {}
    role_last = {}
    m_of = {}
    for pid, tm in active.items():
        if tm not in team_proj or pos.get(pid) not in eff:
            continue
        group, pri_t, pri_c, n_pt, n_pc = priors.get(
            pid, ("no history", 0.0, 0.0, 0, 0))
        past_t = [v for w, v in tgt_cur.get(pid, {}).items() if w < week]
        past_c = [v for w, v in car_cur.get(pid, {}).items() if w < week]
        kt = _k_tgt(group) * POS_KT_MULT.get(pos.get(pid), 1.0)
        kc = _k_car(group) * POS_KT_MULT.get((pos.get(pid), "car"), 1.0)
        # availability scales the share BEFORE normalisation, so a removed
        # player's touches are handed to his teammates rather than vanishing
        m = 1.0 if avail is None else avail.get(pid, 1.0)
        if m <= 0:
            continue
        m_of[pid] = m
        if TRADE_MULT and _TEAM_WEEK:
            tw_ = sorted((w_, t_) for (p_, w_), t_ in _TEAM_WEEK.get(pid, {}).items() if w_ < week)                 if isinstance(_TEAM_WEEK.get(pid), dict) else []
            if tw_ and any(t_ != tm for _, t_ in tw_):
                n_new = sum(1 for _, t_ in tw_ if t_ == tm)
                if tw_[-1][1] != tm:
                    m *= TRADE_MULT[0]
                elif n_new == 1 and len(TRADE_MULT) > 1:
                    m *= TRADE_MULT[1]
        # NEW TEAM, NO GAMES YET (2026-10-24, Joe on David Sills, TB wk7: "4.9
        # seems kinda high for a guy who is likely not to see much work"): a
        # player on a new team who has not played for anyone this season kept
        # his OLD team's share (Sills: 10% of ATL's 2025 targets). TRADE_MULT
        # only caught moves made THIS season. x NEW_TEAM_MULT. None = off.
        if NEW_TEAM_MULT is not None and new_team_no_games(
                pid, tm, past_t or past_c, sum(1 for (t_, w_) in games if t_ == tm and w_ < week)):
            m *= NEW_TEAM_MULT
        if DEPTH_DEMOTE and _DEPTH_FLAG.get((pid, week)) == "demoted":
            m *= DEPTH_DEMOTE.get(pos.get(pid), 1.0)
        st_, sc_ = tgt_cur.get(pid, {}), car_cur.get(pid, {})
        if route_pct is not None and ROUTE_LEAD_TGT and pos.get(pid) in SNAP_LEAD_POS:
            rp = route_pct.get(pid) or {}
            seen = [w for w in st_ if w < week and rp.get(w, 0) > 0]
            if seen:
                last_r = rp[max(seen)]
                st_ = {w: (v * min(max((last_r / rp[w]) ** ROUTE_LEAD_TGT, 0.5), 2.0)
                           if w < week and rp.get(w, 0) > 0 else v)
                       for w, v in st_.items()}
        if pid in lineup_keep:
            fac = lineup_keep[pid][1]
            st_ = {w: v * fac.get(w, 1.0) for w, v in st_.items()}
            sc_ = {w: v * fac.get(w, 1.0) for w, v in sc_.items()}
        if DUD_FLOOR:
            # One dud week from an established player should not drag him down
            # as if it were his new role. With a prior backed by DUD_MIN_GAMES+
            # games, a week below DUD_FLOOR x that prior counts only up to the
            # floor. DOWNWARD only -- a breakout is never capped, which is why
            # this is not the rejected PRIOR_GAME_WEIGHT (that slowed both;
            # TESTED_SETTINGS.md).
            # Ja'Marr Chase, wk1 2026: 12% share against a 32% prior.
            # ONE dud is cushioned; repeated duds are believed. If DUD_REPEAT or
            # more of his last 4 games sit below the floor, it is a real role
            # change -- a new alpha, a QB change -- not a bad week.
            def floored(series, pri):
                recent = [v for w, v in sorted(series.items()) if w < week][-4:]
                if DUD_REPEAT and sum(1 for v in recent if v < DUD_FLOOR * pri) >= DUD_REPEAT:
                    return series
                return {w: max(v, DUD_FLOOR * pri) for w, v in series.items()}
            if n_pt >= DUD_MIN_GAMES and pri_t >= DUD_MIN_SHARE:
                st_ = floored(st_, pri_t)
            if n_pc >= DUD_MIN_GAMES and pri_c >= DUD_MIN_SHARE_CAR:
                sc_ = floored(sc_, pri_c)
        ot, nt = recent_mean(st_, week, half_life, _EXIT_W.get(pid))
        oc, nc = recent_mean(sc_, week, half_life, _EXIT_W.get(pid))
        raw[pid] = (tm,
                    m * blend(ot, nt, pri_t, kt),
                    m * blend(oc, nc, pri_c, kc))
        if _DEBUG_PIDS and pid in _DEBUG_PIDS:
            print(f"  [debug {pid}] group {group}  m {m:.2f}")
            print(f"     targets: this season {ot:.3f} over {nt} g, prior {pri_t:.3f} (k {kt:.2f}) -> {raw[pid][1]:.3f}")
            print(f"     carries: this season {oc:.3f} over {nc} g, prior {pri_c:.3f} (k {kc:.2f}) -> {raw[pid][2]:.3f}")
            print(f"     weekly tgt shares {dict((w, round(v, 3)) for w, v in sorted(st_.items()) if w < week)}")
            print(f"     weekly car shares {dict((w, round(v, 3)) for w, v in sorted(sc_.items()) if w < week)}")
        if ROLE_W and pos.get(pid) in ROLE_POS:
            last_ = [st_[w_] for w_ in sorted(w_ for w_ in st_ if w_ < week)][-ROLE_N:]
            if len(last_) == ROLE_N:
                role_last[pid] = (m, sum(last_) / ROLE_N, min(last_), max(last_))

    # --- route-based target model (ROUTE_MODEL_W)
    est = {}
    if ROUTE_MODEL_W and route_full is not None:
        lg_tprr = route_full.get("_lg", {})
        for pid, (tm, ts, cs) in raw.items():
            po = pos.get(pid)
            r_ = route_full.get(pid)
            if not r_ or po not in ("RB", "WR", "TE"):
                continue
            # only games still in his history: one he LEFT hurt (dropped from
            # tgt_cur by the exit rules or FULL) must not count here either --
            # Jefferson wk5 2026 averaged in a 6%-of-routes wk3 exit
            kept = tgt_cur.get(pid, {})
            cur = sorted(w for w in r_ if 0 < w < week and w in kept)
            if not cur:
                continue
            healthy = [w for w in cur if (pid, w) not in _INJ_LIMITED]
            cur_rp = healthy or cur
            nr = int(ROUTE_RECENT_N)
            rp = sum(r_[w]["route_pct"] for w in cur_rp[-nr:]) / len(cur_rp[-nr:])
            # a returning teammate takes his routes back too (Lloyd ran GB's
            # RB routes all 2026 without Jacobs; 2025 backups saw 1-2 targets)
            if RETURN_ROUTES and pid in ret_fac:
                rp *= sum(ret_fac[pid].get(w, 1.0) for w in cur_rp[-nr:]) / len(cur_rp[-nr:])
            rt = sum(r_[w]["routes"] for w in cur); tg = sum(r_[w]["tgt"] for w in cur)
            if 0 in r_:
                rt += ROUTE_HIST_W * r_[0]["routes"]; tg += ROUTE_HIST_W * r_[0]["tgt"]
            m_ = lg_tprr.get(po, 0.2)
            tprr = (tg + m_ * K_TPRR) / (rt + K_TPRR)
            est[pid] = rp * tprr
        by_tm = collections.defaultdict(list)
        for pid in est:
            by_tm[raw[pid][0]].append(pid)
        for tm, pids in by_tm.items():
            tot_est = sum(est[p] for p in pids)
            tot_sh = sum(raw[p][1] for p in pids)
            if tot_est <= 0:
                continue
            for p in pids:
                t0, ts0, cs0 = raw[p]
                rm = est[p] / tot_est * tot_sh
                w_ = ROUTE_MODEL_W_POS.get(pos.get(p), ROUTE_MODEL_W)
                raw[p] = (t0, (1 - w_) * ts0 + w_ * rm, cs0)

    # --- sustained role change (ROLE_W): after the route model, so it has the last word
    if ROLE_W and role_last:
        for pid, (m_, avg_, lo_, hi_) in role_last.items():
            tm_, ts_, cs_ = raw[pid]
            base_ = ts_ / m_ if m_ else ts_
            if base_ > 0 and (lo_ >= base_ * (1 + ROLE_MARGIN) or hi_ <= base_ * (1 - ROLE_MARGIN)):
                raw[pid] = (tm_, (1 - ROLE_W) * ts_ + ROLE_W * m_ * avg_, cs_)

    # --- pass 2: RECONCILE. Blending each player independently leaves a team's
    # shares not summing to 1 (measured: 8.8% too many targets league-wide, and
    # up to +47% on individual teams). Normalising restores the identity that
    # every target belongs to exactly one player.
    # VACATED ROLES. An absent player's share used to be handed out purely in
    # proportion to what his teammates already had, so the RB1 soaked up almost
    # all of an absent RB2's work: Jaylen Warren projected 21 carries in wk3
    # 2026 with Rico Dowdle out, having actually had 10 and 11. With VAC_EQ,
    # that fraction of the vacated share is split EVENLY among the same-
    # position players still available -- the next man up takes a real role --
    # and normalisation spreads the rest as before. "Absent" = played for the
    # team in either of the last two weeks and is not in this week's pool.
    miss_wr = collections.defaultdict(float)
    absent_wr_best = collections.defaultdict(float)
    raw_pre = dict(raw)
    if VAC_EQ and team_of:
        vac = collections.defaultdict(float)          # (tm, pos, kind) -> share
        for pid, t_ in team_of.items():
            po = pos.get(pid)
            if pid in raw or t_ not in team_proj or po not in POSITIONS:
                continue
            recent = [w for w in (week - 1, week - 2)
                      if w in tgt_cur.get(pid, {}) or w in car_cur.get(pid, {})]
            if not recent:
                continue
            g_, p_t, p_c, _, _ = priors.get(pid, ("no history", 0.0, 0.0, 0, 0))
            ot_, nt_ = recent_mean(tgt_cur.get(pid, {}), week, half_life, _EXIT_W.get(pid))
            oc_, nc_ = recent_mean(car_cur.get(pid, {}), week, half_life, _EXIT_W.get(pid))
            vac[(t_, po, "t")] += blend(ot_, nt_, p_t, _k_tgt(g_))
            if po == "WR":
                sh_ = blend(ot_, nt_, p_t, _k_tgt(g_))
                miss_wr[t_] = min(miss_wr[t_] + sh_, 0.6)
                absent_wr_best[t_] = max(absent_wr_best[t_], sh_)
            vac[(t_, po, "c")] += blend(oc_, nc_, p_c, _k_car(g_))
        mates = collections.defaultdict(list)
        for pid, (tm, _, _) in raw.items():
            mates[(tm, pos.get(pid))].append(pid)
        for (tm, po, kind), v in vac.items():
            who = mates.get((tm, po), [])
            if not who or v <= 0:
                continue
            bump = VAC_EQ * v / len(who)
            for pid in who:
                t0, ts0, cs0 = raw[pid]
                raw[pid] = (t0, ts0 + (bump if kind == "t" else 0.0),
                            cs0 + (bump if kind == "c" else 0.0))
            if VAC_TPRR and kind == "t":
                pool = [p_ for (t2, _), l_ in mates.items() if t2 == tm for p_ in l_]
                wts = {p_: est.get(p_, 0.0) for p_ in pool}
                tw = sum(wts.values())
                if tw > 0:
                    for p_, w_ in wts.items():
                        t0, ts0, cs0 = raw[p_]
                        raw[p_] = (t0, ts0 + VAC_TPRR * v * w_ / tw, cs0)

    tot_t, tot_c = collections.defaultdict(float), collections.defaultdict(float)
    for tm, ts, cs in raw.values():
        tot_t[tm] += ts; tot_c[tm] += cs
    # NO TEAM PLAYS ONE BACK (2026-10-24, Joe: "A team never goes into a game
    # with just a single RB. Bijan is a beast, but can't do 100%"). ATL wk7:
    # Brian Robinson out, Herbert / Jam Miller off the depth chart -> Bijan got
    # every RB carry (26.6). 2023-25: a workhorse lead back (60%+ that game)
    # averaged 78% of RB carries, backups 22%; one back with ALL of them in
    # 3.8% of games. When the backs we project leave the lead back more than
    # 1 - RB_MIN_BACKUP of the RB carries, an unnamed backup takes the rest
    # (those carries are not given to anyone we project). None = off.
    if RB_MIN_BACKUP:
        rb_c = collections.defaultdict(list)
        for pid, (tm, ts, cs) in raw.items():
            if pos.get(pid) == "RB" and cs > 0:
                rb_c[tm].append(cs)
        for tm, cl in rb_c.items():
            tot_c[tm] += rb_backup_need(cl)
    # team-WR1s this week and the season calibration for them (TIER_CAL_K)
    tier1, tier_r = set(), None
    if TIER_CAL_K and _TIER_RATIO.get(week):
        t_ = _TIER_RATIO[week]
        tier_r = {k_: blend(t_[k_], t_["n"], 1.0, TIER_CAL_K) for k_ in ("ypt", "catch", "tdpt")}
        best_ = {}
        for pid, (tm, ts, cs) in raw.items():
            if pos.get(pid) == "WR" and (tm not in best_ or ts > best_[tm][0]):
                best_[tm] = (ts, pid)
        tier1 = {v[1] for v in best_.values()}
    # elite target-earners this week (ELITE_TPRR)
    elite_now = set()
    if ELITE_TPRR and route_full is not None:
        for pid in raw:
            r_ = route_full.get(pid)
            if not r_ or pos.get(pid) not in ELITE_POS:
                continue
            cw = sorted(w for w in r_ if 0 < w < week)
            rt = sum(r_[w]["routes"] for w in cw) + (r_[0]["routes"] if 0 in r_ else 0)
            tg = sum(r_[w]["tgt"] for w in cw) + (r_[0]["tgt"] if 0 in r_ else 0)
            rps = [r_[w]["route_pct"] for w in cw[-3:]]
            if (rt >= ELITE_MIN_ROUTES and tg / rt >= ELITE_TPRR
                    and (not rps or sum(rps) / len(rps) >= ELITE_MIN_RP)):
                elite_now.add(pid)
    if TIER_CAL_REAL_WR1 and tier1:
        tier1 = {p_ for p_ in tier1
                 if raw_pre[p_][1] >= absent_wr_best.get(raw_pre[p_][0], 0.0)
                 or (TIER_CAL_FILLIN_ELITE and p_ in elite_now)}

    # --- quarterbacks: same volume x rate shape, own denominators
    if qb_patt is not None:
        qraw, avail_qbs, team_starter = {}, {}, {}
        for pid, tm in active.items():
            if pos.get(pid) != "QB" or tm not in team_proj:
                continue
            m = 1.0 if avail is None else avail.get(pid, 1.0)
            if m <= 0:
                continue
            avail_qbs.setdefault(tm, []).append((qb_rank.get(pid, 9), pid, m))

        # the starter is the best-ranked QB still standing after availability
        for tm, lst in avail_qbs.items():
            lst.sort()
            starter_keep = []
            team_starter[tm] = lst[0][1]
            for i, (rk, pid, m) in enumerate(lst):
                if i == 0:
                    pri_p, pri_r = QB1_PASS_SHARE, QB1_RUSH_SHARE
                else:
                    rest = len(lst) - 1
                    pri_p = (1 - QB1_PASS_SHARE) / rest
                    pri_r = (1 - QB1_RUSH_SHARE) / rest
                pp = [v for w, v in qb_patt.get(pid, {}).items() if w < week]
                pr = [v for w, v in qb_ratt.get(pid, {}).items() if w < week]
                gp = (qb_games or {}).get(tm, 0)
                if i > 0 and QB1_SKIP_MISSED and QB_BACKUP_ON_STARTER_WEEKS:
                    # A BACKUP is judged only on the games this week's starter
                    # started and stayed in. Weeks he filled in while the
                    # starter was out are exactly the bump that has to vanish
                    # when the starter returns -- Wentz started both games
                    # Kyler missed and was still holding 14% of Minnesota's
                    # attempts for week 3.
                    pp = [qb_patt.get(pid, {}).get(w, 0.0) for w in starter_keep]
                    pr = [qb_ratt.get(pid, {}).get(w, 0.0) for w in starter_keep]
                    gp = len(starter_keep)
                if i == 0 and QB1_SKIP_MISSED:
                    # This week's STARTER is judged only on games he actually
                    # started and stayed in. Dividing by team games (right for
                    # backups, whose empty weeks are real zeros) turned a
                    # starter's injury week into a 0% share, and a game he LEFT
                    # (Kyler, wk1 2026: 5 attempts, concussion, Wentz took 19)
                    # into a 21% one. Weeks under QB1_MIN_WEEK_SHARE are dropped;
                    # if none are left -- or he is a new starter with no games
                    # -- he gets the starter default outright. That discounts
                    # PAST usage for a PAST exit; it predicts nothing.
                    keep = [w for w, v in qb_patt.get(pid, {}).items()
                            if w < week and v >= QB1_MIN_WEEK_SHARE]
                    pp = [qb_patt[pid][w] for w in keep]
                    pr = [qb_ratt.get(pid, {}).get(w, 0.0) for w in keep]
                    gp = len(keep)
                    starter_keep = keep
                qraw[pid] = (tm,
                             m * blend(sum(pp) / gp if gp else 0, gp,
                                       pri_p, K_QB_PASS_SHARE),
                             m * blend(sum(pr) / gp if gp else 0, gp,
                                       pri_r, K_QB_RUSH_SHARE))
        qt, qr = collections.defaultdict(float), collections.defaultdict(float)
        for tm, ps, rs in qraw.values():
            qt[tm] += ps; qr[tm] += rs

    lg_qb_td_rate = qb_eff.get("rush_td_rate", 0.0) if qb_eff else 0.0

    def qb_rtd(pid, week, rs, carries, tp):
        """His own goal-line role where we have the carries to justify it."""
        if not lg_qb_td_rate:
            return rs * tp["qb_rush_td"]      # no league rate: league share
        a_car = a_td = 0.0
        for wk, (c, t) in (qb_rush.get(pid) or {}).items():
            if wk < week:
                a_car += c; a_td += t
        # Downward is always trusted: a QB who never runs one in keeps not
        # running one in. Upward needs a PROVEN goal-line role -- two full
        # seasons at 1.5x the league rate on 50+ carries (qb_rush_td_proven).
        # A loose one-accumulated-rate gate swept in flukes and looked like
        # upward adjustment never works; the season gate shows it does.
        proven = (qb_td_proven or {}).get(pid)
        if a_car:
            own = a_td / a_car
            if own >= lg_qb_td_rate:
                # only a PROVEN goal-line role earns an upward move
                rate = (blend(own, a_car, lg_qb_td_rate, K_QB_RUSH_TD_DOWN)
                        if proven else lg_qb_td_rate)
            else:
                rate = blend(own, a_car, lg_qb_td_rate, K_QB_RUSH_TD_DOWN)
        else:
            rate = proven if proven else lg_qb_td_rate
        return carries * rate


    # CONSERVE TEAM TOUCHDOWNS. A QB's own rushing-TD rate used to be added on
    # top of the implied total, so a proven goal-line runner created touchdowns
    # from nothing -- and his total overshot even as his rushing line got right.
    # When Allen runs it in from the 2, that is a score that would otherwise
    # have been a pass or a handoff. So the change from the league-share
    # baseline comes OUT of the rest of the team's pool (or goes back into it
    # for a QB who never runs one in), and the team still scores exactly what
    # the Vegas line says it will.
    if qb_patt is not None and qb_rush is not None:
        shift = collections.defaultdict(float)
        for pid, (tm, ps, rs) in qraw.items():
            tp = team_proj[tm]
            rsn = rs / qr[tm] if qr[tm] else 0.0
            shift[tm] += (qb_rtd(pid, week, rsn,
                                 rsn * tp["qb_rush"], tp)
                          - rsn * tp["qb_rush_td"])
        for tm, x in shift.items():
            tp = team_proj[tm]
            pool = tp["pass_td"] + tp["rush_td"]
            if pool > 0 and x:
                f = max(pool - x, 0.0) / pool
                tp["pass_td"] *= f
                tp["rush_td"] *= f

    # QB's own passing-TD rate (test version, QB_PASS_TD_K) -- see constants.
    if QB_PASS_TD_K and qb_patt is not None and qb_pass is not None and qb_eff:
        lg_ptd = qb_eff.get("ptd_rate", 0.0)
        mult, wsum = collections.defaultdict(float), collections.defaultdict(float)
        for pid, (tm, ps, rs) in qraw.items():
            aa = tt = 0.0
            for wk, v in (qb_pass.get(pid) or {}).items():
                if wk < week:
                    aa += v[0]; tt += v[4]
            m_ = blend(tt / aa, aa, lg_ptd, QB_PASS_TD_K) / lg_ptd if aa and lg_ptd else 1.0
            mult[tm] += ps * m_; wsum[tm] += ps
        for tm, x in mult.items():
            if not wsum[tm]:
                continue
            tp = team_proj[tm]
            m_ = 1 + QB_PASS_TD_W * (x / wsum[tm] - 1)
            add = tp["pass_td"] * (m_ - 1)
            tp["pass_td"] += add
            tp["rush_td"] = max(tp["rush_td"] - QB_PASS_TD_CONSERVE * add, 0.0)

    # TD shares get a per-player multiplier, then are renormalised so each
    # team still scores exactly the touchdowns its implied total says it will.
    tdw_t, tdw_c = {}, {}
    for pid, (tm, ts, cs) in raw.items():
        mt, mc = 1.0, 1.0
        hist = (rb_td_proven or {}).get(pid)
        lg_rate = eff[pos[pid]].get("tdpc", 0.0)
        if hist and lg_rate:
            hc, ht = hist
            for wk, c in (player_eff.get(pid) or {}).items():
                if 0 < wk < week:          # this season, on top of history
                    hc += c["car"]; ht += c["rush_td"]
            mc = blend(ht / hc, hc, lg_rate, K_RB_RUSH_TD) / lg_rate if hc else 1.0
        # Receiving TDs CONCENTRATE on a team's top targets beyond their
        # share -- red-zone looks go to the WR1/TE1. Straight proportion
        # left top WRs at 0.44 TDs a game against 0.51 actual (2024-25),
        # while their targets and yards were already right. The exponent
        # tilts the split toward the top; renormalising below keeps the
        # team's receiving-TD total unchanged.
        tdw_t[pid] = (ts / tot_t[tm] if tot_t[tm] else 0.0) * mt
        if REC_TD_POS_EXP:
            tdw_t[pid] *= eff[pos[pid]].get("tdpt", 0.0) ** REC_TD_POS_EXP
        if tier_r and TIER_CAL_TD and pid in tier1:
            tdw_t[pid] *= tier_r["tdpt"]
        tdw_c[pid] = (cs / tot_c[tm] if tot_c[tm] else 0.0) * mc
        if RZ_EXP and rz_use is not None and rz_use.get(pid):
            a_ = [0.0] * 8
            for wk, c in rz_use[pid].items():
                if wk < week:
                    w_ = RZ_HIST_W if wk == 0 else 1.0
                    for i in range(8):
                        a_[i] += c[i] * w_
            for (rz, trz, al, tal), key in (((0, 1, 4, 5), "c"), ((2, 3, 6, 7), "t")):
                if a_[trz] > 0 and a_[al] > 0 and a_[tal] > 0:
                    conc = (a_[rz] / a_[trz]) / (a_[al] / a_[tal])
                    conc = min(max(blend(conc, a_[trz], 1.0, K_RZ), 0.25), 4.0)
                    if key == "c":
                        tdw_c[pid] *= conc ** RZ_EXP
                    else:
                        tdw_t[pid] *= conc ** RZ_EXP
    st_, sc_ = collections.defaultdict(float), collections.defaultdict(float)
    for pid, (tm, _, _) in raw.items():
        st_[tm] += tdw_t[pid]; sc_[tm] += tdw_c[pid]

    if _DEBUG_PIDS:
        for pid in _DEBUG_PIDS:
            if pid in raw:
                tm_ = raw[pid][0]; tp_ = team_proj[tm_]
                print(f"  [debug {pid}] final raw tgt {raw[pid][1]:.3f} / team {tot_t[tm_]:.3f}, raw car {raw[pid][2]:.3f} / team {tot_c[tm_]:.3f}"
                      f" | {tm_} plays {tp_['plays']:.1f} targets {tp_['targets']:.1f} non-QB rush {tp_['nonqb_rush']:.1f}")
    out = {}
    for pid, (tm, ts, cs) in raw.items():
        tp = team_proj[tm]
        ts = ts / tot_t[tm] if tot_t[tm] else 0.0
        cs = cs / tot_c[tm] if tot_c[tm] else 0.0
        targets, carries = ts * tp["targets"], cs * tp["nonqb_rush"]
        e = eff[pos[pid]]
        td_t, td_c = ts, cs
        km = POS_KEFF_MULT.get(pos[pid], 1.0)
        pr_ = _PRESEASON_RATES.get(pid) if PRESEASON_EFF else None
        if pr_:
            e = dict(e)
            for k_ in ("ypt", "catch"):
                e[k_] = (1 - PRESEASON_EFF) * e[k_] + PRESEASON_EFF * pr_[k_]
        if TEAM_YPC_W and pos[pid] == "RB" and _TEAM_RUSH:
            ty_ = [v for (t_, w_), v in _TEAM_RUSH.items() if t_ == tm and w_ < week]
            ry_, rc_ = sum(v[0] for v in ty_), sum(v[1] for v in ty_)
            if rc_:
                t_ypc = (ry_ + TEAM_YPC_K * e["ypc"]) / (rc_ + TEAM_YPC_K)
                e = dict(e)
                e["ypc"] = (1 - TEAM_YPC_W) * e["ypc"] + TEAM_YPC_W * t_ypc
        e = blended_rates(player_eff.get(pid), week, e, K_EFF_TGT * km, K_EFF_CAR * km,
                          prior_w=ELITE_EFF_PRIOR_W if pid in elite_now else None)
        if tm in backup_teams:
            e = dict(e)
            e["ypt"] *= BACKUP_EFF_MULT; e["catch"] *= BACKUP_CATCH_MULT
        if MISS_YPT and miss_wr.get(tm):
            e = dict(e)
            e["ypt"] *= 1 - MISS_YPT * miss_wr[tm]
        if tier_r and pid in tier1:
            e = dict(e)
            e["ypt"] *= tier_r["ypt"]; e["catch"] *= tier_r["catch"]
        td_t = tdw_t[pid] / st_[tm] if st_[tm] else ts
        td_c = tdw_c[pid] / sc_[tm] if sc_[tm] else cs
        out[pid] = {
            "rec": targets * e["catch"], "rec_yds": targets * e["ypt"],
            "rec_td": td_t * tp["pass_td"], "rush_yds": carries * e["ypc"],
            "rush_td": td_c * tp["rush_td"],
            "fum": (carries + targets * e["catch"]) * lg.get("fum_skill", 0.0) if PROJECT_FUMBLES else 0.0,
            "targets": targets, "rush_att": carries,
        }

    if qb_patt is not None:
        for pid, (tm, ps, rs) in qraw.items():
            tp = team_proj[tm]
            # a team throws exactly 100% of its attempts, however many QBs play
            ps = ps / qt[tm] if qt[tm] else 0.0
            rs = rs / qr[tm] if qr[tm] else 0.0
            att = ps * tp["pass_att"]
            carries = rs * tp["qb_rush"]
            ypa, cmp_pct = qb_eff["ypa"], qb_eff["comp_pct"]
            int_rate = qb_eff["int_rate"]
            aa = ac = ay = ai = 0.0
            for wk, (x, c_, y, i_, _t) in (qb_pass.get(pid) or {}).items():
                if wk < week:
                    aa += x; ac += c_; ay += y; ai += i_
            if aa:
                ypa = blend(ay / aa, aa, qb_eff["ypa"], K_QB_YPA)
                cmp_pct = blend(ac / aa, aa, qb_eff["comp_pct"], K_QB_YPA)
            out[pid] = {
                "pass_att": att, "pass_cmp": att * cmp_pct,
                "pass_yds": att * ypa * (1 - MISS_YPT * miss_wr.get(tm, 0.0)),
                "pass_td": ps * tp["pass_td"],
                "pass_int": att * int_rate,
                "rush_att": carries, "rush_yds": carries * qb_eff["ypc"],
                "rush_td": qb_rtd(pid, week, rs, carries, tp),
                "rec": 0.0, "rec_yds": 0.0, "rec_td": 0.0,
                "fum": (att + carries) * lg.get("fum_qb", 0.0) if PROJECT_FUMBLES else 0.0,
                "targets": 0.0,
            }
    if WX_SCALE:
        for pid, v in out.items():
            tm_ = (raw.get(pid) or (qraw.get(pid) if qb_patt is not None else None) or (None,))[0]
            g_ = games.get((tm_, week)) if tm_ else None
            if not g_:
                continue
            cut = 0.0
            wd = g_.get("wind") or 0.0
            if wd >= 15:
                cut += WX_CUTS["wind15"]
            elif wd >= 10:
                cut += WX_CUTS["wind10"]
            if g_.get("temp") is not None and g_["temp"] < 40:
                cut += WX_CUTS["cold"]
            if cut:
                f_ = 1 - WX_SCALE * cut
                for k in ("rec_yds", "pass_yds"):
                    if k in v:
                        v[k] *= f_
    if PASS_RECON_W is not None and qb_patt is not None:
        team_of_out = {pid: raw[pid][0] for pid in raw if pid in out}
        team_of_out.update({pid: qraw[pid][0] for pid in qraw if pid in out})
        by_t = collections.defaultdict(list)
        for pid, tm in team_of_out.items():
            by_t[tm].append(pid)
        for tm, pids in by_t.items():
            qbs = [p for p in pids if pos.get(p) == "QB" or p in qraw]
            rec = [p for p in pids if p not in qbs]
            for qk, rk in (("pass_yds", "rec_yds"), ("pass_cmp", "rec")):
                q_ = sum(out[p].get(qk, 0.0) for p in qbs)
                r_ = sum(out[p].get(rk, 0.0) for p in rec)
                if q_ <= 0 or r_ <= 0:
                    continue
                t_ = PASS_RECON_W * q_ + (1 - PASS_RECON_W) * r_
                for p in qbs:
                    out[p][qk] = out[p].get(qk, 0.0) * t_ / q_
                for p in rec:
                    out[p][rk] = out[p].get(rk, 0.0) * t_ / r_
    globals()["_LAST_TEAM"] = team_proj   # read by --team-dump (diagnostics)
    return out


def points(stat, position=None):
    if position == "QB":
        return scoring.qb_points(stat)
    return (scoring.rushing_points(stat) + scoring.receiving_points(stat, HALF_PPR)
            + scoring.fumble_points(stat))


def actual_points(r):
    if r["position"] == "QB":
        return points({"pass_yds": num(r["passing_yards"]),
                       "pass_td": num(r["passing_tds"]),
                       "pass_int": num(r["passing_interceptions"]),
                       "rush_yds": num(r["rushing_yards"]),
                       "rush_td": num(r["rushing_tds"]),
                       "fum": num(r["sack_fumbles_lost"])
                              + num(r["rushing_fumbles_lost"])}, "QB")
    return points({"rush_yds": num(r["rushing_yards"]), "rush_td": num(r["rushing_tds"]),
                   "rec": num(r["receptions"]), "rec_yds": num(r["receiving_yards"]),
                   "rec_td": num(r["receiving_tds"]),
                   "fum": num(r["rushing_fumbles_lost"]) + num(r["receiving_fumbles_lost"])})


# ---------------------------------------------------------------- backtest

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--dump", help="backtest: write every projected/actual pair to this CSV")
    ap.add_argument("--live", action="store_true",
                    help="project an UPCOMING week (no actuals needed)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--team-dump", help="backtest: write projected vs actual TEAM volume")
    ap.add_argument("--pool", help="live re-run of a past week: only players in this "
                                   "locked projections file are available")
    ap.add_argument("--version", default="current", choices=sorted(VARIANTS),
                    help="a named test version (see VARIANTS); output files get its name")
    ap.add_argument("--out", help="live: write the projections here instead of data/")
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                    help="override one model constant (testing)")
    args = ap.parse_args()
    for k, v in VARIANTS[args.version].items():
        globals()[k] = v
    for kv in args.set:
        k, v = kv.split("=", 1)
        assert k in globals() and k.isupper(), f"unknown constant {k}"
        if k in ("POS_KT_MULT", "POS_KEFF_MULT", "ROUTE_MODEL_W_POS", "DEPTH_DEMOTE", "EXIT_KEEP_W"):
            globals()[k] = None if v == "None" else {
                a.split(":")[0]: float(a.split(":")[1]) for a in v.split(",") if a}
            continue
        try:
            globals()[k] = float(v)
        except ValueError:
            globals()[k] = (None if v == "None" else v if k in ("MATCHUP_MODE",)
                            else tuple(float(x) if x.replace(".", "", 1).isdigit() else x
                                       for x in v.split(",") if x))
    prev_year = args.year - 1

    cur_rows, prev_rows = load_players(args.year), load_players(prev_year)
    teams_cur, teams_prev = load_teams(args.year), load_teams(prev_year)
    games_cur, games_prev = load_games(args.year), load_games(prev_year)
    chart = load_depth_chart(args.year)

    tgt_cur, car_cur, pos, team_cur = shares_by_week(cur_rows)
    tgt_prev, car_prev, pos_prev, team_prev = shares_by_week(prev_rows)
    # players who were on the field but posted no stat line recorded a real
    # zero, not a missing week
    fill_observed_zeros(tgt_cur, car_cur, pos, args.year)
    exits = set() if EXIT_KEEP_W else None
    if SKILL_EXIT_DROP:
        conf = None
        if SKILL_EXIT_CONFIRM:
            tags_now = None
            if args.live and args.week:
                try:
                    sys.path.insert(0, HERE)
                    import availability as _av
                    tags_now = set(_av.sleeper_tags(args.year)[0])
                except Exception:
                    tags_now = None
            conf = injury_confirmed(args.year, tags_now,
                                    (args.week - 1) if args.week else None)
        drop_exit_weeks(tgt_cur, car_cur, load_snap_pct(args.year),
                        load_snap_pct(args.year - 1), positions=pos, confirmed=conf,
                        returning=first_games_back(args.year),
                        pregame=listed_pregame(args.year) if EXIT_PREGAME_KEEP else None,
                        collect=exits)
    if PBP_EXIT_DROP:
        drop_pbp_exits(tgt_cur, car_cur, args.year, collect=exits)
        drop_pbp_exits(tgt_prev, car_prev, args.year - 1)   # last season's: still dropped
    if exits:
        globals()["_EXIT_W"] = keep_exit_games(tgt_cur, car_cur, exits, pos)
    # shares_by_week only walks skill positions (they define the denominators),
    # so quarterbacks are absent from `pos` until we add them explicitly.
    for r in cur_rows:
        if r["position"] == "QB":
            pos.setdefault(r["player_id"], "QB")
    for r in prev_rows:
        if r["position"] == "QB":
            pos.setdefault(r["player_id"], "QB")
    eff = efficiency_means(prev_rows)
    lg = league_constants(teams_prev, prev_rows)
    imp_to_td = fit_implied_to_td(teams_prev, games_prev)          # prior season only
    skill_tgt = sum(num(r["targets"]) for r in prev_rows if r["position"] in POSITIONS)
    pass_att = sum(int(t["pass_att"]) for t in teams_prev.values())
    tgt_per_att = skill_tgt / pass_att if pass_att else 0.95
    tgt_pri, car_pri = tgt_prev, car_prev
    priors = build_priors(tgt_cur, car_cur, tgt_pri, car_pri, pos,
                          team_cur, team_prev, chart)
    if VAC_PRIOR_W:
        priors = apply_vacated(priors, tgt_prev, car_prev, team_prev, team_cur, chart, pos, pos_prev)
    if DEPTH_DEMOTE:
        globals()["_DEPTH_FLAG"] = depth_flags(args.year, cur_rows)
    if TRADE_MULT:
        tw = collections.defaultdict(dict)
        for r in cur_rows:
            if r["position"] in ALL_POSITIONS:
                tw[r["player_id"]][(r["player_id"], int(r["week"]))] = r["team"]
        globals()["_TEAM_WEEK"] = tw
    if TEAM_YPC_W:
        tr_ = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for r in cur_rows:
            k_ = (r["team"], int(r["week"]))
            if r["position"] in ("RB", "WR", "TE"):
                tr_[k_][0] += num(r.get("rushing_yards")); tr_[k_][1] += num(r.get("carries"))
            tr_[k_][2] += num(r.get("passing_tds"))
            tr_[k_][3] += num(r.get("rushing_tds"))
        globals()["_TEAM_RUSH"] = dict(tr_)
    if NEW_TEAM_MULT is not None:
        globals()["_PREV_TEAM"] = prev_team_map(prev_rows)
    if INJ_SNAP_FRAC:
        globals()["_INJ_LIMITED"] = injury_limited(args.year, INJ_SNAP_FRAC)
    if TIER_CAL_K:
        globals()["_TIER_RATIO"] = tier_ratios(cur_rows, prev_rows)
    pre_now = {}
    if PRESEASON_W or PRESEASON_EFF:
        import preseason
        names_ = {}
        for r in prev_rows + cur_rows:
            names_[r["player_id"]] = r.get("player_display_name") or r.get("player_name", "")
        for pid, nm in depth_names(args.year).items():
            names_.setdefault(pid, nm)
        pre_now = preseason.load(args.year, names_, pos)
        globals()["_PRESEASON_RATES"] = preseason_rates(pre_now, pos)
        if PRESEASON_W:
            priors = apply_preseason(priors, pre_now, team_cur, pos)

    # --- quarterback layer
    qb_patt, qb_ratt = qb_shares_by_week(cur_rows, teams_cur)
    qb_patt_p, qb_ratt_p = qb_shares_by_week(prev_rows, teams_prev)
    qb_eff = qb_efficiency_means(prev_rows)
    # (QB priors are no longer built here: the starter is decided inside
    # project_week from the depth chart, after availability filtering.)
    team_qbr_prev = {}
    for (tm, wk), r in teams_prev.items():
        team_qbr_prev.setdefault(tm, []).append(float(r["qb_rush_share"]))
    team_qbr_prev = {t: sum(v) / len(v) for t, v in team_qbr_prev.items()}
    qb_kw = dict(qb_patt=qb_patt, qb_ratt=qb_ratt,
                 qb_eff=qb_eff, team_qbr_prev=team_qbr_prev)
    cutoffs = week_cutoffs(args.year)
    route_now = route_full_now = None
    if ROUTE_LEAD_TGT or ROUTE_MODEL_W:
        import fl_routes
        fl_cur = fl_routes.load(args.year)
        route_now = {pid: {w: v["route_pct"] for w, v in wks.items()}
                     for pid, wks in fl_cur.items()}
        if ROUTE_MODEL_W:
            fl_prev = fl_routes.load(args.year - 1)
            route_full_now = {pid: dict(wks) for pid, wks in fl_cur.items()}
            lg_ = collections.defaultdict(lambda: [0.0, 0.0])
            pos_prev = {r["player_id"]: r["position"] for r in prev_rows}
            for pid, wks in fl_prev.items():
                rt = sum(v["routes"] for v in wks.values())
                tg = sum(v["tgt"] for v in wks.values())
                route_full_now.setdefault(pid, {})[0] = {"routes": rt, "tgt": tg}
                po = pos.get(pid) or pos_prev.get(pid)
                if po in ("RB", "WR", "TE"):
                    lg_[po][0] += tg; lg_[po][1] += rt
            route_full_now["_lg"] = {po: tg / rt for po, (tg, rt) in lg_.items() if rt}
    rz_now = None
    if RZ_EXP:
        import redzone
        played = collections.defaultdict(lambda: collections.defaultdict(dict))
        for yr, rows_ in ((args.year, cur_rows), (args.year - 1, prev_rows)):
            for r in rows_:
                if r["position"] in POSITIONS:
                    played[yr][r["player_id"]][int(r["week"])] = r["team"]
        rz_now = redzone.usage(args.year, played)
    bt_eff = player_eff_by_week(cur_rows, prev_rows)
    hist_seasons = []
    for yr in range(args.year - 4, args.year):
        try:
            hist_seasons.append(load_players(yr))
        except FileNotFoundError:
            pass
    bt_qbr = qb_rush_hist(cur_rows, hist_seasons)
    bt_qbp = qb_pass_hist(cur_rows, hist_seasons)
    bt_prov = qb_rush_td_proven(hist_seasons, min_seasons=QB_RUSH_TD_MIN_SEASONS)
    bt_rbp = rb_rush_td_proven(hist_seasons)
    tp_acc = collections.defaultdict(list)
    for (tm_, _w), r_ in teams_prev.items():
        tp_acc[tm_].append((int(r_["plays"]), float(r_["pass_rate"])))
    qb_kw["team_of"] = team_cur
    qb_kw["carry_hist"] = carry_games(cur_rows, hist_seasons[-2:])
    qb_kw["team_prior"] = {t: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v))
                           for t, v in tp_acc.items()}

    if args.live:
        if not args.week:
            ap.error("--live requires --week")
        roster, asof = current_roster(args.year)
        for pid, p in chart_positions(args.year).items():
            pos.setdefault(pid, p)
        priors = build_priors(tgt_cur, car_cur, tgt_pri, car_pri, pos,
                              team_cur, team_prev, chart, extra_ids=roster)
        if VAC_PRIOR_W:
            priors = apply_vacated(priors, tgt_prev, car_prev, team_prev,
                                   {**roster, **team_cur}, chart, pos, pos_prev)
        if pre_now and PRESEASON_W:
            priors = apply_preseason(priors, pre_now, {**roster, **team_cur}, pos)
        played = {r["player_id"]: r["team"] for r in cur_rows
                  if r["position"] in ALL_POSITIONS and int(r["week"]) < args.week}
        active = {**roster, **played}          # season usage wins on team
        # ...except after a TRADE: the newest depth chart has him somewhere else
        # than his last game (Marvin Harrison Jr., ARI -> HOU, wk6 2026). The new
        # team wins, and his old team treats him as gone (VAC hands his share
        # to his old teammates, since team_cur still points there).
        for pid_, tm_new in roster.items():
            if pid_ in played and played[pid_] != tm_new:
                print(f"  team change: {pid_} {played[pid_]} -> {tm_new} (newest depth chart)")
                active[pid_] = tm_new
        # BYE WEEKS: only teams with a game this week. Without this the bye teams
        # were projected anyway (wk5 2026 CAR, KC; wk6 CIN, DET, MIA, MIN).
        playing = {tm for (tm, wk_) in games_cur if wk_ == args.week}
        if playing:
            byes = sorted({t for t in active.values() if t not in playing})
            active = {p_: t for p_, t in active.items() if t in playing}
            if byes:
                print(f"  bye week: {', '.join(byes)}")
        active = {p: t for p, t in active.items() if p in pos}
        import availability
        import read_review
        # CURRENT ranks (not the preseason prior) -- the rotation check needs to
        # know who is listed where right now.
        rank_now = {pid: rk for pid, (p_, rk) in
                    load_depth_chart(args.year, cutoff="9999-01-01").items()}
        review, problems = read_review.load(args.year, args.week)
        flags = read_review.load_flags(args.year, args.week)
        # FULL: games he LEFT hurt (snaps under SKILL_EXIT_FRAC of his usual)
        # come out of his history -- Joe's call that he is back at 100%. The
        # blanket version (every confirmed WR/TE exit) tested slightly worse,
        # so it is per player, on the review sheet.
        if flags:
            sp_all = load_snap_pct(args.year)
            for pid, fl in flags.items():
                if fl != "FULL":
                    continue
                sp = sp_all.get(pid, {})
                for w in sorted(sp):
                    before = [sp[x] for x in sp if x < w]
                    if before and sp[w] < FULL_FRAC * max(before):
                        for d_ in (tgt_cur, car_cur):
                            d_.get(pid, {}).pop(w, None)
                        print(f"  FULL: dropped wk{w} for {pid} ({sp[w]:.0%} of snaps)")
        # START: this QB is his team's starter (rank 0 beats every depth rank)
        qrank_live = dict(qb_ranks_as_of(args.year, "9999"))
        for pid, fl in flags.items():
            if fl == "START":
                qrank_live[pid] = 0
                print(f"  START: {pid} set as his team's starting QB")
        for who, what in problems:
            print(f"  !! review sheet: could not read {what!r} for {who} "
                  f"-- treated as PLAY")
        avail, reason = availability.build(args.year, args.week, candidates=active,
                                           depth_rank=rank_now, review=review,
                                           positions=pos)
        globals()["_TEAM_ADJ"] = load_team_adjust(args.year, args.week)
        for tm_, a_ in _TEAM_ADJ.items():
            print(f"  team sheet: {tm_} " + ", ".join(f"{k} {v:g}" for k, v in a_.items()))
        if args.pool:
            # RE-RUN a past week with the player pool as it was LOCKED: today's
            # Sleeper tags would otherwise rule out players who did play then.
            with open(args.pool, newline="", encoding="utf-8") as fh:
                pool = {r["player_id"] for r in csv.DictReader(fh)}
            for pid_ in list(avail):
                if pid_ not in pool:
                    if avail[pid_] > 0:
                        reason[pid_] = "not in the locked pool"
                    avail[pid_] = 0.0
                elif avail[pid_] <= 0 and review.get(pid_) != 0.0:
                    # today's tags removed him; the locked pool says he played
                    # then. An explicit OUT on the sheet stays OUT (2026-10-27:
                    # "or 1.0" turned a re-run's Spears OUT back into a full go)
                    avail[pid_] = review.get(pid_, 1.0)
        name = {r["player_id"]: r["player_display_name"] for r in cur_rows}
        for r in load_players(prev_year):
            name.setdefault(r["player_id"], r["player_display_name"])
        # 61 players -- rookies, and anyone who missed all of last season -- appear
        # on the depth chart but in neither stats file. Take their name from there.
        dpath = os.path.join(DATA, f"depth_charts_{args.year}.csv")
        if os.path.exists(dpath):
            with open(dpath, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("gsis_id") and r.get("player_name"):
                        name.setdefault(r["gsis_id"], r["player_name"])
        # one projection with a given availability (the hedges below run two)
        def _run(av):
            return project_week(args.week, teams_cur=teams_cur, games=games_cur,
                                tgt_cur=tgt_cur, car_cur=car_cur, pos=pos,
                                priors=priors, eff=eff, lg=lg, imp_to_td=imp_to_td,
                                tgt_per_att=tgt_per_att, active=active, avail=av,
                                qb_games=team_games(teams_cur, args.week),
                                qb_rank=qrank_live,
                                player_eff=bt_eff, qb_rush=bt_qbr, qb_pass=bt_qbp,
                                qb_td_proven=bt_prov, rb_td_proven=bt_rbp,
                                rz_use=rz_now, route_pct=route_now,
                                route_full=route_full_now, **qb_kw)
        # QB START CHANCE (2026-10-15). On a quarterback, a review-sheet number
        # under 100 is the chance he STARTS: the team is projected once with him
        # and once with his backup, and every player on it is blended by that
        # chance -- how the sites hedge an uncertain starter. 2026 wks 3-5: on
        # the 91 games with a settled starter our QBs beat consensus (6.53 vs
        # 6.75); the whole gap was three all-or-nothing starter calls (Keenum,
        # Bagent, Mariota). A plain usage cut could not hedge: Lamar at 60% went
        # 18.3 -> 17.8, Huntley 1.2 -> 1.9.
        hedge = {pid_: m for pid_, m in review.items()
                 if pos.get(pid_) == "QB" and 0 < m < 1 and pid_ in active}
        # CHANCE TO PLAY, any position ("chance 25" on the sheet, 2026-10-16):
        # teammates blended by the chance; his OWN line stays "if he plays",
        # since only players who play are graded.
        chances = {pid_: c_ for pid_, c_ in read_review.load_chances(args.year, args.week).items()
                   if pid_ in active and 0 < c_ < 1}
        hedge.update(chances)
        # "N ONLY" PASS-CATCHERS, QB SIDE (2026-10-25, Joe: "we have Puka lower at
        # like 70%, shouldn't that affect Stafford as well"): the receivers keep
        # their numbers (no guessing who replaces him), but his QB is blended
        # N% "he plays" / rest "he sits" -- Stafford 18.9 with Puka, 17.0 without
        only_qb = {pid_: f_ for pid_, f_ in read_review.load_only(args.year, args.week).items()
                   if pid_ in active and 0 < f_ < 1 and pos.get(pid_) in ("WR", "TE", "RB")
                   and pid_ not in hedge}
        hedge.update(only_qb)
        if not hedge:
            proj = _run(avail)
        else:
            av_a, av_b = dict(avail), dict(avail)
            for pid_ in hedge:
                av_a[pid_], av_b[pid_] = (1.0 if pid_ in chances else 1.0), 0.0
            # a QB start chance makes HIM the starter in run A even while the
            # depth chart still lists the old starter first (McCarthy over
            # Winston, NYG wk7 2026): the team's other QBs sit out run A
            for pid_ in hedge:
                if pid_ not in chances and pid_ not in only_qb:
                    for q_, t_ in active.items():
                        if q_ != pid_ and t_ == active[pid_] and pos.get(q_) == "QB":
                            av_a[q_] = 0.0
            pa, pb = _run(av_a), _run(av_b)
            by_team = collections.defaultdict(list)
            for pid_, m in hedge.items():
                by_team[active[pid_]].append(m)
            chance = {t_: sum(v_) / len(v_) for t_, v_ in by_team.items()}
            proj = {}
            only_teams = {active[p_] for p_ in only_qb}
            for pid_ in set(pa) | set(pb):
                c = chance.get(active.get(pid_), 1.0)
                va, vb = pa.get(pid_, {}), pb.get(pid_, {})
                if pid_ in chances or pid_ in only_qb:
                    proj[pid_] = dict(va)
                    continue
                if active.get(pid_) in only_teams and pos.get(pid_) != "QB":
                    proj[pid_] = dict(va)      # receivers / backs unchanged
                    continue
                proj[pid_] = {k: c * va.get(k, 0.0) + (1 - c) * vb.get(k, 0.0)
                                  for k in set(va) | set(vb)}
            for pid_, m in hedge.items():
                what = ("chance to play" if pid_ in chances else
                        "N only (his QB blended)" if pid_ in only_qb else "QB start chance")
                print(f"  {what}: {pid_} {m:.0%} ({active[pid_]} teammates blended)")
        # EPA matchups need only play-by-play, so they run live too (the
        # residual version needs every past week's projection: backtest only)
        if MATCHUP_K and MATCHUP_MODE == "epa":
            import matchups
            mu = matchups.EpaMatchups(args.year, MATCHUP_EPA_BETA, MATCHUP_EPA_K,
                                      MATCHUP_EPA_PRIOR, stats=MATCHUP_STATS or None,
                                      positions=MATCHUP_POS or None)
            opp = {k: g["opp"] for k, g in games_cur.items() if "opp" in g}
            proj = mu.apply(proj, args.week, active, pos, opp)
        # "85 only" on the sheet: his own line scaled, teammates untouched
        for pid_, f_ in read_review.load_only(args.year, args.week).items():
            if pid_ in proj:
                proj[pid_] = {k: v * f_ for k, v in proj[pid_].items()}
                print(f"  his line only: {pid_} x{f_:.2f} (teammates unchanged)")
        rows = sorted(((points(v, pos.get(pid)), pid)
                       for pid, v in proj.items()), reverse=True)
        cons, cons_label = load_consensus_for(args.year, args.week)
        tag = "" if args.version == "current" else f"_{args.version}"
        dest = args.out or os.path.join(DATA, f"projections_{args.year}_wk{args.week:02d}{tag}.csv")
        # team totals beside the projections (check_projections, gap_report):
        # the unnamed-backup carries and team volume are not in the player file
        if _LAST_TEAM and not args.out:
            with open(os.path.join(DATA, f"team_volume_{args.year}_wk{args.week:02d}{tag}.csv"),
                      "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["team", "plays", "pass_att", "targets", "nonqb_rush", "qb_rush"])
                for tm_, tp_ in sorted(_LAST_TEAM.items()):
                    w.writerow([tm_] + [round(tp_.get(k, 0.0), 2) for k in
                                        ("plays", "pass_att", "targets", "nonqb_rush", "qb_rush")])
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["player_id", "player", "pos", "team", "half_ppr",
                        "consensus", "diff",
                        "pass_att", "pass_cmp", "pass_yds", "pass_td", "pass_int",
                        "rush_att", "rush_yds", "rush_td",
                        "targets", "rec", "rec_yds", "rec_td"])
            for pts, pid in rows:
                v = proj[pid]
                # Blank rather than 0 when the market has no number for him --
                # a real 0 and "nobody projected him" are different facts.
                c = cons.get(cons_key(name.get(pid, "")))
                qb = pos[pid] == "QB"

                def col(key, nd=1, only_qb=False):
                    # Blank out the half of the stat line that cannot apply, so
                    # a QB does not show a column of zero targets and a running
                    # back does not show zero pass attempts.
                    if only_qb != qb:
                        return ""
                    return round(v.get(key, 0.0), nd)

                w.writerow([pid, name.get(pid, ""), pos[pid], active[pid],
                            round(pts, 2),
                            "" if c is None else round(c, 2),
                            # model minus consensus -- the workbook's Diff
                            "" if c is None else round(pts - c, 2),
                            col("pass_att", 1, True), col("pass_cmp", 1, True),
                            col("pass_yds", 1, True), col("pass_td", 2, True),
                            col("pass_int", 2, True),
                            round(v.get("rush_att", 0.0), 1),
                            round(v.get("rush_yds", 0.0), 1),
                            round(v.get("rush_td", 0.0), 2),
                            col("targets"), col("rec"), col("rec_yds"),
                            col("rec_td", 2)])
        print()
        print(f"  {args.year} week {args.week} projections  "
              f"(depth chart as of {asof})")
        print()
        print(f"  {'#':<4}{'player':<24}{'pos':<5}{'tm':<5}{'proj':>7}{'tgt':>7}{'car':>7}")
        for i, (pts, pid) in enumerate(rows[:args.top], 1):
            v = proj[pid]
            print(f"  {i:<4}{name.get(pid, pid):<24}{pos[pid]:<5}{active[pid]:<5}"
                  f"{pts:>7.1f}{v['targets']:>7.1f}{v['rush_att']:>7.1f}")
        print()
        removed = [(p, reason[p]) for p, m in avail.items() if m == 0.0]
        byreason = collections.Counter(r.split(":")[0] for _, r in removed)
        print(f"  availability: {len(removed)} of {len(active)} removed  "
              + ", ".join(f"{k} {v}" for k, v in byreason.most_common()))
        print(f"  {len(rows):,} players -> {os.path.basename(dest)}")
        if cons:
            matched = sum(1 for _, pid in rows
                          if cons_key(name.get(pid, "")) in cons)
            print(f"  consensus columns: {matched} of {len(rows)} matched "
                  f"({cons_label})")
        else:
            print(f"  consensus columns: EMPTY -- {cons_label}")

        # The depth chart names the NOMINAL starter and knows nothing about who
        # is hurt, so without an injury source the model will hand a job back to
        # a man who was ruled out days ago. The official report is a Wed-Fri
        # artifact; Sleeper covers the gap but is only as fresh as its cache.
        report = availability._injury_report(args.year, args.week)
        graded = sum(1 for v in report.values()
                     if v in availability.BLOCKING_REPORT)
        tags, tag_date = availability.sleeper_tags()
        print(f"  injury sources: official report {graded} Out/Doubtful"
              f" for wk{args.week}"
              + (f", sleeper snapshot {tag_date}" if tag_date else ", sleeper MISSING"))
        if not graded:
            print()
            print(f"  *** The official week {args.week} injury report has no "
                  "Out/Doubtful designations yet. ***")
            if tag_date:
                print(f"  Sleeper ({tag_date}) is carrying the load. That is a "
                      "good stand-in, not a")
                print("  substitute -- re-run once the Wednesday report lands "
                      "before publishing.")
            else:
                print("  And no Sleeper snapshot was found, so NOTHING is "
                      "filtering injuries.")
                print("  Do not publish these.")
        print()
        return

    by_week = collections.defaultdict(list)
    for r in cur_rows:
        if r["position"] in ALL_POSITIONS:
            by_week[int(r["week"])].append(r)

    ctx = dict(teams_cur=teams_cur, games=games_cur, tgt_cur=tgt_cur, car_cur=car_cur,
               pos=pos, eff=eff, lg=lg, imp_to_td=imp_to_td, tgt_per_att=tgt_per_att)
    globals()["_CTX"] = (ctx, by_week, priors,
                         dict(tgt_cur=tgt_cur, car_cur=car_cur, tgt_prev=tgt_prev,
                              car_prev=car_prev, pos=pos, team_cur=team_cur,
                              team_prev=team_prev, chart=chart))

    weeks = [args.week] if args.week else sorted(w for w in by_week if 2 <= w <= 18)
    err = collections.defaultdict(lambda: collections.defaultdict(list))

    dump_rows = []
    team_rows = []
    mu = None
    if MATCHUP_K:
        import matchups
        if MATCHUP_MODE == "epa":
            mu = matchups.EpaMatchups(args.year, MATCHUP_EPA_BETA, MATCHUP_EPA_K,
                                      MATCHUP_EPA_PRIOR, stats=MATCHUP_STATS or None,
                                      positions=MATCHUP_POS or None)
        else:
            mu = matchups.Matchups(MATCHUP_K, MATCHUP_STATS or None, MATCHUP_POS or None)
        opp = {k: g["opp"] for k, g in games_cur.items() if "opp" in g}
        # week 1 is never scored, but what defenses allowed in it still counts
        if 1 not in weeks and by_week.get(1) and MATCHUP_MODE != "epa":
            act1 = {r["player_id"]: r["team"] for r in by_week[1]}
            p1 = project_week(1, teams_cur=teams_cur, games=games_cur, tgt_cur=tgt_cur,
                              car_cur=car_cur, pos=pos, priors=priors, eff=eff, lg=lg,
                              imp_to_td=imp_to_td, tgt_per_att=tgt_per_att,
                              active=act1, qb_games=team_games(teams_cur, 1),
                              qb_rank=qb_ranks_as_of(args.year, cutoffs.get(1, "9999")),
                              player_eff=bt_eff, qb_rush=bt_qbr, qb_pass=bt_qbp,
                              qb_td_proven=bt_prov, rb_td_proven=bt_rbp,
                              **qb_kw)
            mu.update(1, p1, by_week[1])
    for w in weeks:
        active = {r["player_id"]: r["team"] for r in by_week[w]}
        proj = project_week(w, teams_cur=teams_cur, games=games_cur, tgt_cur=tgt_cur,
                            car_cur=car_cur, pos=pos, priors=priors, eff=eff, lg=lg,
                            imp_to_td=imp_to_td, tgt_per_att=tgt_per_att,
                            active=active, qb_games=team_games(teams_cur, w),
                            qb_rank=qb_ranks_as_of(args.year,
                                                   cutoffs.get(w, "9999")),
                            player_eff=bt_eff, qb_rush=bt_qbr, qb_pass=bt_qbp,
                            qb_td_proven=bt_prov, rb_td_proven=bt_rbp,
                            rz_use=rz_now,
                            route_pct=route_now, route_full=route_full_now, **qb_kw)
        if args.team_dump:
            for tm_, tp_ in globals().get("_LAST_TEAM", {}).items():
                a_ = teams_cur.get((tm_, w))
                g_ = games_cur.get((tm_, w), {})
                if a_:
                    team_rows.append((w, tm_, round(tp_.get("plays", 0), 2), int(a_["plays"]),
                                      round(tp_["pass_att"], 2), int(a_["pass_att"]),
                                      round(tp_["nonqb_rush"] + tp_["qb_rush"], 2), int(a_["rush_att"]),
                                      round(tp_["targets"], 2),
                                      g_.get("implied", ""), g_.get("margin", "")))
        if mu is not None:
            raw_proj = proj
            proj = mu.apply(raw_proj, w, active, pos, opp)
            mu.update(w, raw_proj, by_week[w])
        for r in by_week[w]:
            pid = r["player_id"]
            if pid not in proj:
                continue
            a = actual_points(r)
            p = points(proj[pid], r["position"])
            v_ = proj[pid]
            dump_rows.append((w, pid, r.get("player_display_name") or r.get("player_name", ""),
                              r["position"], r["team"], round(p, 3), round(a, 3),
                              round(v_.get("targets", 0), 2), num(r["targets"]),
                              round(v_.get("rec", 0), 2), num(r["receptions"]),
                              round(v_.get("rec_yds", 0), 1), num(r["receiving_yards"]),
                              round(v_.get("rec_td", 0), 3), num(r["receiving_tds"]),
                              round(v_.get("rush_att", 0), 2), num(r["carries"]),
                              round(v_.get("rush_yds", 0), 1), num(r["rushing_yards"]),
                              round(v_.get("rush_td", 0), 3), num(r["rushing_tds"]),
                              round(v_.get("pass_att", 0), 1), num(r["attempts"]),
                              round(v_.get("pass_yds", 0), 1), num(r["passing_yards"]),
                              round(v_.get("pass_td", 0), 3), num(r["passing_tds"]),
                              round(v_.get("pass_int", 0), 3), num(r["passing_interceptions"])))
            # baselines, all walk-forward
            hist = [actual_points(x) for x in
                    (row for wk in range(1, w) for row in by_week.get(wk, [])
                     if row["player_id"] == pid)]
            std = sum(hist) / len(hist) if hist else None
            l3 = sum(hist[-3:]) / len(hist[-3:]) if hist else None
            grp = r["position"]
            err[grp]["model"].append((p - a) ** 2)
            err["ALL"]["model"].append((p - a) ** 2)
            if std is not None:
                err[grp]["season avg"].append((std - a) ** 2)
                err["ALL"]["season avg"].append((std - a) ** 2)
                err[grp]["last 3"].append((l3 - a) ** 2)
                err["ALL"]["last 3"].append((l3 - a) ** 2)

    if args.dump:
        with open(args.dump, "w", newline="", encoding="utf-8") as fh:
            w_ = csv.writer(fh)
            w_.writerow(["week", "player_id", "player", "pos", "team", "proj", "actual",
                         "tgt_p", "tgt_a", "rec_p", "rec_a", "recyd_p", "recyd_a",
                         "rectd_p", "rectd_a", "car_p", "car_a", "rushyd_p", "rushyd_a",
                         "rushtd_p", "rushtd_a", "patt_p", "patt_a", "pyds_p", "pyds_a",
                         "ptd_p", "ptd_a", "int_p", "int_a"])
            w_.writerows(dump_rows)
    if args.team_dump:
        with open(args.team_dump, "w", newline="", encoding="utf-8") as fh:
            w_ = csv.writer(fh)
            w_.writerow(["week", "team", "plays_p", "plays_a", "patt_p", "patt_a",
                         "rush_p", "rush_a", "tgt_p", "implied", "margin"])
            w_.writerows(team_rows)

    def rmse(v):
        return math.sqrt(sum(v) / len(v)) if v else float("nan")

    print(f"\n  walk-forward backtest, {args.year} weeks {weeks[0]}-{weeks[-1]}  "
          f"(half-PPR, RMSE in fantasy points)\n")
    print(f"  {'':<6}{'n':>8}{'MODEL':>9}{'season avg':>13}{'last 3':>10}{'vs best baseline':>19}")
    for grp in ("ALL", "QB", "RB", "WR", "TE"):
        e = err.get(grp)
        if not e:
            continue
        m, s, l = rmse(e["model"]), rmse(e["season avg"]), rmse(e["last 3"])
        best = min(s, l)
        print(f"  {grp:<6}{len(e['model']):>8,}{m:>9.3f}{s:>13.3f}{l:>10.3f}"
              f"{(best - m) / best * 100:>18.1f}%")
    print()


if __name__ == "__main__":
    main()
