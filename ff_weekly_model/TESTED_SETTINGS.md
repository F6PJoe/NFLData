# Settings tested and switched off -- removed from project.py 2026-10-28

Kept as a record of what was tried, why, and what the backtest said. Each entry is the
comment block and the setting as they stood in project.py before the cleanup (Joe,
2026-10-28: "do we need to simplify things"). Re-adding one means re-testing it with
baseline_guard.py under the adoption rule (net gain over 2024-26, 2026 not worse).

Also switched off on 2026-10-28 by the rule-by-rule switch-off test (removing each was
a net gain or zero): NEWS_EXIT_FRAC (news-reported exits), QB_CARRIES_TO_RBS,
K_QB_INT (per-QB interception rate), QB_OWN_CARRIES (QB carries from his own history;
removing it improved QB RMSE by .021 over three seasons).

## QBR_STARTER_ONLY
```
QBR_STARTER_ONLY = False
```

## PRIOR_SHARE_SEASONS
```
PRIOR_SHARE_SEASONS = 1   # 2-3 TESTED, worse (5.371 -> 5.376)
```

## PRIOR_SHARE_POS
```
# Positions the older seasons apply to (None = all). Added 2026-10-13 for
# Joe's down-year stars (Jefferson, Nabers): the September test was every
# position at once. WR-only TESTED 2026-10-13, not adopted: the down-year
# group (top-12 two years ago, not last year) 2026 wks 2-5 bias -0.84 -> -0.44,
# but WR RMSE 5.238 -> 5.272 in 2026 (2025 4.987 -> 4.979, 2024 flat) -- the
# older season holds back the risers. 3 seasons worse still. Efficiency the
# same way (EFF_HIST_SEASONS 2-3, WR only): 2024 better, 2025-26 worse.
PRIOR_SHARE_POS = None
```

## TEAM_PRIOR_W_PLAYS
```
TEAM_PRIOR_W_PLAYS = 0.0
```

## TD_CONC_REC
```
# Receiving-TD concentration (2026-09-26). Top WRs/TEs were right on targets
# and yards (more accurate than ESPN, 2024-25) but 0.06 TDs/gm LOW. 1.15 closes
# most of it (+0.063 -> +0.026 in 2024, +0.060 -> +0.017 in 2025) at no RMSE
# cost (2024 5.435 -> 5.435, 2025 5.319 -> 5.321); 1.3+ overshoots and hurts.
TD_CONC_REC = 1.0   # 1.15 until 2026-09-30; REC_TD_POS_EXP now carries this
```

## TGT_CONC
```
# Target concentration: star WR targets ran slightly low both seasons (-0.1,
# -0.8/gm for WRs averaging 15+). Shares ^ exponent, renormalised per team.
TGT_CONC = 1.0
```

## LG_TD_SPLIT_K
```
# IN-SEASON LEAGUE RATES (2026-09-30). Every league constant -- the pass/rush
# split of a team's touchdowns, and each position's yards per carry, catch
# rate, yards per target and TD rates that every player is shrunk toward --
# came from LAST season and never learned from this one. 2026 wks 1-3: RB
# rushing TDs 0.57 per team-game against 0.70 in 2024-25, YPC 4.13 vs 4.35,
# passing TDs 1.65 vs 1.48 -- RBs projected +1.55 pts too high with carries
# exactly right. Each rate is blended with last season's by team-games played
# this season (K = team-games of weight on last season; None = off).
LG_TD_SPLIT_K = None
```

## PASS_CAL_K
```
# SELF-CALIBRATING PASS VOLUME (2026-10-06): after each week, league pass
# attempts we projected vs what teams threw. Every team's pass attempts (and
# targets) are scaled by that ratio, shrunk toward 1 by team-games:
# n / (n + PASS_CAL_K). Unbiased seasons (2024-25 within 1%) are left alone;
# 2026 ran 3-5% short all three scored weeks. None = off.
PASS_CAL_K = None
```

## PLAYS_OPP_W
```
# SNAP SHARE LEADS TOUCHES (2026-09-30). A role change shows up in snaps a
# week before it shows up in touches: an RB whose snap share jumped 10+ points
# last week beat our carry projection by +0.7 the next week (2024 and 2025
# alike), one whose snaps fell 10+ points missed by -0.4 to -0.7. With this on,
# every past week's share is rescaled to the player's MOST RECENT snap level:
# share_w x (snap_latest / snap_w) ^ exponent, capped at 0.5x-2x. Exponent 0 =
# off. Separate exponents for carries and targets.
# GAME-LEVEL PLAYS (2026-09-30, Joe). Each team's plays came from its own pace
# only. PLAYS_OPP_W: a fast opponent means more possessions for you too --
# plays += W x (opponent's projected plays - league mean). PLAYS_TOTAL_W:
# plays x (1 + W x (game total / slate-average total - 1)). Volume only;
# touchdowns still come from the implied total. 0 = off.
# ADOPTED 2026-09-30: the game total, as Joe guessed ("more points, more
# plays"); opponent pace added nothing (0.25/0.5 flat). Backtest ALL, with
# SNAP_LEAD_TGT 0.25:  2024 5.425 -> 5.410   2025 5.322 -> 5.308
# 2026 wks 2-3 5.179 -> 5.148 -- better at EVERY position in 2024 and 2025
# (QB 7.261 -> 7.247 / 6.881 -> 6.861, RB 5.452 -> 5.412 / 5.754 -> 5.745,
# TE 4.108 -> 4.098 / 4.352 -> 4.332, WR 5.406 -> 5.404 / 5.006 -> 4.993).
# 0.5-0.8 all close; 1.0 overshoots in 2024-25.
PLAYS_OPP_W = 0.0
```

## RZ_EXP_TGT
```
# red-zone exponent for RECEIVING TDs only (None = RZ_EXP). 2026-10-18 test:
# big-play receivers score from outside the 10 (Parker Washington 4 TD in 5
# games, projected 0.30) and get no red-zone credit for it.
RZ_EXP_TGT = None
```

## ROUTE_HIST2_W
```
# The season BEFORE last in the route model's targets-per-route (2026-10-13,
# Joe: let target rate decide who is elite). TPRR holds year to year (r 0.73
# vs 0.66 for points per game) and barely depends on the QB: Jefferson's 2025
# was 9.4 ppg on a 0.252 TPRR. 0 = off. Only for players WITH older route
# data (FL from 2024). TESTED 2026 only (no FL 2023 yet): 1.0 moved the
# down-year stars (Nabers, Evans, Higgins) -0.84 -> -0.57 but also held up
# decliners (BTJ) and held back risers (P. Washington): WR 5.238 -> 5.249.
# Joe's plan is to catch risers/decliners by hand on the review sheet.
ROUTE_HIST2_W = 0.0
```

## SNAP_LEAD_CAR
```
SNAP_LEAD_CAR = 0.0
```

## SNAP_LEAD_TGT
```
SNAP_LEAD_TGT = 0.0   # 0.25 until routes replaced it (2026-10-01)
```

## REC_TD_POS_EXP
```
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
```

## LG_EFF_K
```
LG_EFF_K = None
```

## SAME_LINEUP_MODE
```
# "deflate" (2026-10-08): instead of DROPPING the weeks a bigger-role teammate
# missed (worse in both backtests), keep them but take the bump out -- his
# share that week x (1 - ALPHA x the absent teammate's share), the share his
# absence handed out. Nico Collins wk5 2026: missed wks 2-3, his teammates'
# shares from those weeks squeezed him to 23% against 27%/31% in the games he
# played. "drop" = the original rule.
# ADOPTED for WR/TE: ALL 2024 5.390 -> 5.387 (WR 5.375 -> 5.369), 2025 flat,
# 2026 5.191 -> 5.190 (WR 5.269 -> 5.264). RBs hurt 2025 (5.718 -> 5.734): out.
SAME_LINEUP_MODE = "deflate"
```

## QB_RATES_FROM_STARTS
```
QB_RATES_FROM_STARTS = None   # TESTED 'int'/'all': no effect (starts rate ~= all-QB rate)
```

## GS_BETA
```
GS_BETA = 0.0   # TESTED: run<->pass shift, worse overall at 0.5-2%/pt
```

## TOTAL_PASS_BETA
```
# TOTAL_PASS_BETA: pass rate per point of game total vs the slate (see team
# volume). TESTED 2026-10-22 at .002/.0035/.005: worse every season (ALL
# 5.378/5.290/5.106 -> 5.382/5.292/5.107 at .002, worse as it grows) -- the
# total already drives plays (PLAYS_TOTAL_W) and TDs (implied totals), so a
# pass tilt on top double-counts it. Off.
TOTAL_PASS_BETA = None
```

## TEAM_RATE_RETURN_ZERO
```
TEAM_RATE_RETURN_ZERO = False   # also for a back with NO games this season (all team games)
```

## PASS_RAMP_WEEKS
```
# PASS_RAMP_WEEKS / PASS_SHIFT_*: early or big-change trust in a team's pass
# rate (team volume block). TESTED 2026-10-22: ramp 6/10 and shift x.5/x.25
# all worse overall in every season incl. 2026 (ALL +.001 to +.009); QBs
# gained in 2026 (-.010 to -.021) but RB/WR lost more. Early pass rates are
# mostly game script (HOU wk2 75% trailing 6-20). Off.
PASS_RAMP_WEEKS = None
```

## CARRY_CAP
```
CARRY_CAP = None   # TESTED: career max / p95 / p90 all neutral-to-worse
```

## VAC_EQ_POS
```
VAC_EQ_POS = {}
```

## PRESEASON_W_NEW
```
PRESEASON_W_NEW = None      # None = PRESEASON_W
```

## PRESEASON_W_CHANGED
```
PRESEASON_W_CHANGED = None  # preseason weight for players on a NEW team. TESTED 2026-10-24 .75 flat-worse, 1.0 worse all 3 seasons: old-team usage still predicts. Off.
```

## PRESEASON_ACTIVE_DENOM
```
# Preseason SHARES among players actually in this season's pool only
# (2026-10-15, Joe on Mike Evans): his preseason line assumed Pearsall,
# Jennings et al. would play; with them out all year, dividing by a team total
# that still holds their preseason targets kept his share prior too low.
PRESEASON_ACTIVE_DENOM = False
```

## ROLE_UP_K_MULT
```
# RISING ROLES, TRUSTED SOONER (2026-10-18, Joe). When a player's recent
# share is ABOVE his prior, the prior's weight is x ROLE_UP_K_MULT (targets;
# ROLE_UP_K_MULT_CAR for carries); a falling share keeps the full prior, so a
# cold game or two still does not sink anyone. None = off. TESTED .75/.5/.25
# (targets), .5 carries, both: worse every time, most in 2026 (ALL 5.142 ->
# 5.145-5.150): rising shares mostly regress (often a teammate's absence,
# which VAC / same-lineup already cover). Off.
ROLE_UP_K_MULT = None
```

## TREND_K_MULT
```
# THIS SEASON'S TREND, WITH THE ROOM FULL (2026-10-20, Joe: "prioritize this
# season if it was a trend ... more than one big game, needs to not be due to
# other WR being hurt -- as soon as the other WR return all targets go back
# to normal"). ROLE_UP_K_MULT failed because rising shares were mostly a
# teammate's absence. Here only CLEAN games count: every same-position
# teammate with a role (SAME_LINEUP_MIN) who plays THIS week also played that
# one. With TREND_MIN_G+ clean games whose median share (so one big game is
# not enough) is TREND_MARGIN above his prior, his share is built from the
# clean games alone and the prior's weight is x TREND_K_MULT. None = off.
# TESTED 2026-10-20 (ALL 5.379/5.290/5.106 base): K .5 5.381/5.290/5.110,
# .25 worse, WR only / 4 games / big earners only (TREND_MIN_SHARE .20/.24)
# all flat-to-worse. The players it lifts were ALREADY projected high
# (+1.6 pts 2024 and 2026, -1.0 2025): routes, recency and ROLE_W already
# credit a rising role. 2026's short #1 receivers are team VOLUME (32.4
# targets a team-game vs 30.4 projected) with shares right -- but scaling
# volume up (PASS_CAL_K 32-128, LG_VOL_K 32) made 2026 worse too, since the
# points were not short. Off.
TREND_K_MULT = None
```

## SAME_LINEUP_ANY
```
# SAME_LINEUP_ANY: the same-lineup deflate (above) counts ANY absent teammate
# with a role, not just a bigger one -- a WR1 whose share rose while the WR2
# was out gives that bump back when the WR2 returns. False = bigger only.
# TESTED 2026-10-20: 5.380/5.290/5.107 vs 5.379/5.290/5.106 -- flat. Off.
SAME_LINEUP_ANY = False
```

## RETURN_APPEARED
```
RETURN_APPEARED = False   # count every game he appeared in as played. TESTED 2026-10-27: net +.001 (2025 worse) -- off; EXIT_PREGAME_KEEP fixes Henderson on its own
```

## WOWY_K_SHARE
```
WOWY_K_SHARE = None
```

## TEAM_TD_SPLIT_K
```
# TEAM TD SPLIT: a team's pass/rush TD split came only from its pass rate.
# With TEAM_TD_SPLIT_K the team's own pass-TD share this season (pass TDs /
# offensive TDs) is blended in, TEAM_TD_SPLIT_K TDs of weight on the model's
# split -- a team that cannot run near the goal line scores through the air.
# TESTED 2026-10-22 (K 10/20/40): 2026 QB better (6.574 -> 6.524) but 2025 QB
# much worse (6.915 -> 6.946-6.985) and RB worse -- a team's TD split does
# not persist; TDs are too few to read a team's tendency from. Off.
TEAM_TD_SPLIT_K = None
```

## TIER_CAL_ELITE_ONLY
```
TIER_CAL_ELITE_ONLY = False   # only team-WR1s who are also ELITE_TPRR target-earners. TESTED: 2026 better (5.167, WR 5.184) but 2025 worse (5.293, WR 4.980) -- off
```

## TIER_CAL_TE_K
```
# The same season calibration for each team's top TE (2026-10-15): TE1 yds/
# target ran 7.53 vs 7.58 projected (2024), 7.59 vs 7.48 (2025), 6.96 vs 7.51
# (2026, TEs down while WR1s are up). None = off.
TIER_CAL_TE_K = None
```

## MISS_YPT_QB
```
MISS_YPT_QB = None   # None = MISS_YPT; the QB's own yards can be cut separately
```

## VAC_TPRR_EXP
```
VAC_TPRR_EXP = 1.0
```

## DRAFT_PRIOR_MODE
```
# ROOKIES BY DRAFT CAPITAL (2026-10-07). A rookie had no history, so he started
# from his depth-chart slot -- or the deepest slot. First-round WRs then ran
# 8.6 projected vs 12.3 actual (2024 wks 2-5), 8.9 vs 11.1 (2025); 2025 second-
# round RBs 6.6 vs 9.3. The sites know draft capital; we did not. A rookie's
# prior is now his draft range's average share in the first month of a rookie
# season (data/draft_picks.csv, learned from the seasons BEFORE this one), or
# his slot prior if that is higher ("max"), or the two averaged ("blend").
# None = off.
DRAFT_PRIOR_MODE = None
```

## EFF_PRIOR_N
```
EFF_PRIOR_N = False
```

## EFF_HIST_SEASONS
```
# Seasons of efficiency history (1 = last season only) and the positions the
# older ones apply to (None = all) -- see PRIOR_SHARE_POS.
EFF_HIST_SEASONS = 1
```

## K_TD_RATE
```
# TESTED AND REJECTED: a per-player touchdown-rate multiplier. Swept both
# directions and down-only (the asymmetry that worked for QB rushing TDs), at
# k=150/80/40 touches. Every setting was worse than having no player TD term
# at all (5.390 -> 5.392/5.395/5.399) and TD tracking moved 14% -> 15%. Who
# scores is dominated by team context and volume; individual scoring ability
# does not survive out of sample. K_TD_RATE huge = the term is OFF.
K_TD_RATE = 1e9
```

## TD_CAP_UP
```
TD_CAP_UP = False
```

## PRIOR_GAME_WEIGHT
```
PRIOR_GAME_WEIGHT = 0.0   # swept in sweep_prior_weight.py
```

## HALF_LIFE_TGT_POS
```
# Target-share half-life by position (2026-10-13, Joe: WR downgrades off a
# game or two were wrong -- consensus right 58 times). None = HALF_LIFE.
HALF_LIFE_TGT_POS = {}
```

## LOW_K_MULT
```
# Depth-player shrinkage (2026-09-25, closing the gap to ETR): a player whose
# prior is under 8% of targets / 15% of carries has his prior weight cut to a
# quarter, so this season's empty games count. 2025: RMSE unchanged (5.341),
# RB3+ gap -0.54 -> -0.37, WR4+ -0.20 -> -0.10, TE1 +0.59 -> +0.49, but WR1
# -0.39 -> -0.48 (the freed targets flow up). Adopted because 2025 is the
# season everything was tuned on, and every independent signal -- ETR, the
# consensus, wk2 2026 actuals -- says stars were LOW and depth HIGH.
# REMOVED 2026-09-25 after the 2024 holdout: switching it off IMPROVED both
# seasons (2024 -0.004, 2025 -0.001). LOW_K_MULT=1.0 means no effect; the code
# path is kept so it can be re-tested.
LOW_SHARE_T, LOW_SHARE_C, LOW_K_MULT = 0.08, 0.15, 1.0
```

## NEWS_EXIT_FRAC
```
# NEWS-REPORTED EXITS (2026-10-15, Joe: the injury log should help the model,
# not just him). A news item ABOUT the player tagged EXIT ("49ers lose WR
# Deebo Samuel to hamstring injury", "did not return") marks the game he left;
# if his snaps that day were under NEWS_EXIT_FRAC of his usual, the game is
# dropped like a play-by-play exit. A looser snap cut confirmed only by the
# injury report was WORSE (2025 5.292 -> 5.306): listed players with reduced
# snaps usually stay limited. An actual "left the game" report is different.
NEWS_EXIT_FRAC = None
```

## QB_OWN_CARRIES
```
QB_OWN_CARRIES = False# DFS model only -- see main()
```

## QB_CARRIES_TO_RBS
```
QB_CARRIES_TO_RBS = False
```

## K_QB_INT
```
# Per-QB interception rate with HEAVY shrinkage (2026-09-26). Light shrinkage
# (20-150 att) lost to the league rate in 2023-24; at k=500 attempts elite QBs'
# INT over-projection falls 2024 +0.19 -> +0.13, 2025 +0.12 -> +0.06, with QB
# RMSE flat (2024 7.261) to better (2025 6.886 -> 6.881). Good passers really
# do throw fewer picks; it just takes a lot of attempts to trust it.
K_QB_INT = 1e9
```


## The position-mean "ranking" model (`--ranking`, `--dfs`)
Retired as the default 2026-09-25 (Joe: "I'm only worried about the DFS"): it used
league position means for every player's efficiency and ran in-form skill players
+0.76 points light. Live runs still computed it and then discarded it until it was
removed 2026-10-28. The DFS model is now simply "the model"; its efficiency inputs
(player_eff, qb_rush, qb_pass, the proven-TD tables) are required, not optional.
The removal left every projection identical (3 backtest seasons, week 7 live).

## qb_start_carries() (QB start-carries table)
Only QB_OWN_CARRIES read it. Removed with that rule, along with the unused
qb_ypa_by_week() helper.

## PARTIAL_GAME (and PARTIAL_MIN_F / _PBP_ONLY / _SNAP_ORDER / _MATES)
Joe 2026-10-28: "build the partial game so it gets counted, but not counted as a he
didn't play in 3 qtrs." An exit game's share was measured over the plays before he
left and counted as that fraction of a game (research/partial_games.py, with the
2024-25 participation calibration: the play-by-play exit moment is exact; snap-only
exits were half in-and-out games). Against dropping the game (ALL 2024/2025/2026 wks 2-7):
```
partial, every exit              -.003/+.004/+.003  net +.004  (WR +.008/+.011)
+ clean-exit timing (SNAP_ORDER)  -.003/+.005/+.003  net +.005
+ backups deflated, WR/TE         -.003/+.004/+.003  net +.004
+ backups deflated, RB/WR/TE      -.002/+.006/+.005  net +.009
stints under 25% still dropped    -.002/+.002/+.001  net +.001
stints under 50% still dropped    -.002/ .000/+.001  net -.001  (2026 just past even)
play-by-play exits only           -.002/+.001/+.003  net +.002
pbp only, under 25% dropped       -.002/ .000/+.001  net -.001  (2026 just past even)
```
None passed. Every partial version helped 2026 QBs (-.006 to -.013): 2026-only,
re-test around wk 10-12. Replaced by EXIT_KEEP_W (the game as it happened, at a weight).

## EXIT_KEEP_NEXT
The kept exit game counted only for his NEXT game, then dropped out. Next game as
good as EXIT_KEEP_W, but season-long worse: RB1/WR.5/TE.5 -.001/.000/+.006 net +.005
(2026 clearly worse); full weight -.001/-.001/+.006 net +.004.
