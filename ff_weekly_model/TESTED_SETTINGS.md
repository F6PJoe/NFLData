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

RE-TESTED 2026-10-31 (Joe: "I thought we were looking at the number of routes/targets/
carries etc. a player got for the portion of a game they were active") as PARTIAL_ALL:
FULL's left-hurt treatment for every flagged exit, on top of the exit route fixes, against
EXIT_KEEP_W (5.3585/5.2685/5.0766):
```
WR/TE                       -.0002/+.0027/+.0048  net +.0073  (WR 2026 +.012)
RB/WR/TE                    -.0017/+.0029/+.0074  net +.0087
WR/TE, stints under 25% out -.0003/+.0014/+.0037  net +.0047
RB/WR/TE, under 25% out     -.0015/+.0018/+.0078  net +.0082
```
Worst cases are the NEXT game after the exit, played still banged up: McConkey 2026 wk2
7.9 -> 10.1 (actual 5.0), A.J. Brown wk6 8.1 -> 10.1 (4.2), Flowers wk3 13.2 -> 16.9 (12.9).

## EXIT_KEEP_NEXT
The kept exit game counted only for his NEXT game, then dropped out. Next game as
good as EXIT_KEEP_W, but season-long worse: RB1/WR.5/TE.5 -.001/.000/+.006 net +.005
(2026 clearly worse); full weight -.001/-.001/+.006 net +.004.

# Removed 2026-10-30 -- returning backs (Jacobs wk8)

Tested 2026-10-29/30 while working out why Jacobs (back from the exempt list) was
projected for 11 carries in wk8 -- he got 21 (Lloyd 3, Strong 1). All ALL-position
RMSE changes, 2024/2025/2026 (wks 2-7), vs the baseline of the day. What WAS adopted
from this work: RETURN_MIN_MISSED 1, PRESEASON_ABSENT "scale", the 65% workhorse line
(RETURN_STAR_*), WH_RETURN (proven workhorse, backup didn't take the job, 2-6 missed)
and RETURN_OUT_DEFLATE (unproven back outscored by his fill-in) -- see project.py.
Removing these left every projection identical (3 backtest seasons, wk8 live).

Also tested by value only (no code to remove): SAME_LINEUP_POS with RB +.004;
RETURN_MID_DEFLATE .5 / .75 +.001 / +.002; RETURN_STAR_DEFLATE .8 even, 1.0 +.001;
workhorse line 70% +.001, 70/70 +.003.

## ABSENT_GAME_W (and ABSENT_MIN_RANK / ABSENT_LEAD_SHARE / ABSENT_MIN_RUN)
Joe: backups weighted to the games WITH the returning starter.
```
RB .5 / .25 / .1                          net +.002 / +.003 / +.005
RB .25 + WR/TE .5                          net +.004
No. 3 back only (MIN_RANK 2) .5/.25/.1     net +.001 / +.001 / +.002
No. 3 back, lead back's 2+ game absence
  (LEAD_SHARE .4, MIN_RUN 2) .5/.25/.1/.01 all even (.000/.000/.000)
  ... .25 + FIRST_BACK_SCALE lead 1.176    net +.001
```
The 2024-26 data behind the No. 3 idea: when a lead back returned, the No. 2 back
ran 7.7 projected / 9.0 actual carries, the No. 3+ 1.9 / 1.6 (game 1) -- opposite
misses. The narrow version touched 138 of ~13,200 player-weeks: 67 better, 71 worse.
```
# GAMES WITH THE STARTER COUNT MORE (2026-10-29, Joe on Jacobs wk8: "the backup
# players should be more heavily weighted to the one game too"). Once a bigger
# teammate at his position is back -- active this week, and has played this
# season -- a player's games WITHOUT him count as ABSENT_GAME_W[pos] of a game,
# so the games alongside him carry the weight (needs at least one). Weighting,
# not the same-lineup deflate: the share in those games is not marked down,
# they just count less. None = off.
ABSENT_GAME_W = None
# ...only for a player with ABSENT_MIN_RANK+ bigger teammates at his position:
# 2 = the No. 3 back and deeper (2026-10-30, Joe on Pierre Strong: "a 3rd RB
# ... should [not] be projected for much of anything"). 2024-26, a lead back's
# return: the No. 2 back ran 7.7 projected / 9.0 actual carries (game 1),
# 7.7 / 8.7 (game 2); the No. 3+ 1.9 / 1.6 and 2.4 / 1.5 -- opposite misses
# that cancelled out when every backup was cut the same.
ABSENT_MIN_RANK = 1
# ...and only for games missed by a LEAD back (ABSENT_LEAD_SHARE+ of the
# carries) inside a run of ABSENT_MIN_RUN+ straight missed games.
ABSENT_LEAD_SHARE = 0.0
ABSENT_MIN_RUN = 1
```

## RETURN_EARLY (and RETURN_EARLY_FULL)
Full strength .000/+.001/+.002 (net +.003); mild +.001. Replaced by WH_RETURN, which
counts a start-of-season absence only for a proven workhorse whose backup didn't take
the job.
```
# START-OF-SEASON ABSENCE, AFTER HIS FIRST GAME BACK (2026-10-29, Joe on Jacobs
# wk8: "if Jacobs is getting his normal workload, then Lloyd and Strong should
# not be"). With zero games the teammates' weeks are deflated (RETURN_DEFLATE);
# after one game back the rule only saw absences AFTER a played game, so Lloyd's
# and Strong's wks 1-6 counted in full again. RETURN_EARLY keeps the weeks
# before his first game as an absence, at the zero-games strength.
RETURN_EARLY = False
RETURN_EARLY_FULL = True   # zero-games strength; False = the usual mid-season / workhorse strength
```

## EASE_IN, FIRST_BACK_SCALE (and EASE_MIN_* / FIRST_BACK_MIN_*, scale_first_games_back())
```
EASE_IN all backs .85 / .75 / .6           net +.001 / +.002 / +.005
EASE_IN RB .75 + WR/TE .85                  net +.005
EASE_IN 2+ missed                           net +.003
EASE_IN lead backs (share .4) .85 / .75 / .9, 2+ missed   +.001 each; .85, 3+ missed even
FIRST_BACK_SCALE 1.176 all / lead only / 1.1              +.003 / even / +.001
FIRST_BACK all + ABSENT_GAME_W .5 / .25                   +.004 / +.006
```
Backs who fit WH_RETURN came back at 106% of their old share in game 1 (2022-25), so
no automatic ease-in; Joe eases by hand on the sheet ("85", "85 only").
```
# EASE-IN, FIRST GAME BACK FROM A LONG INJURY (2026-10-29, Joe on Charbonnet wk8:
# "first week back off a major knee injury, I would think they would ease him
# in some" -- 60 by hand). A player who missed EASE_MIN_MISSED+ straight team
# games while on the injury report (any listing; not a suspension -- Jacobs)
# has his share x EASE_IN[pos] in his first game back; teammates absorb the
# rest. A start-of-season absence counts if he has last-season history.
# None = off.
# FIRST GAME BACK = 85% (2026-10-29, Joe: "use the usage from the first game
# back as the baseline for the second game back for all running backs ...
# knowing that the first game was only 85%"). A back's first game after
# missing FIRST_BACK_MIN_MISSED+ team games is scaled by FIRST_BACK_SCALE
# (1/0.85: lead backs got 9.0 carries vs 10.1 projected in that game,
# 2024-26) so it reads as a full workload in every projection after it;
# his backups come down when the shares are normalised. Only players whose
# share before the absence was FIRST_BACK_MIN_SHARE+. None = off.
FIRST_BACK_SCALE = None
FIRST_BACK_MIN_MISSED = 2
FIRST_BACK_MIN_SHARE = 0.0
EASE_IN = None
EASE_MIN_MISSED = 3
EASE_MIN_SHARE = 0.0   # only players whose share before the absence was at least this (a lead back)
_INJ_LISTED = {}   # pid -> weeks on this season's injury report, set in main()
```

## PRESEASON_ABSENT "skip", "implied", PRESEASON_GIVEBACK (and PACE_MIN_G, _absent_factor())
"skip" (no preseason blend for a start-of-season absentee) +.007/+.015/+.006.
"implied" +.001/+.001/.000 (net +.002); GIVEBACK even, nothing on top of WH_RETURN;
implied + giveback +.001. By a returner's first game the preseason half is a third
of his number (Jacobs wk8 11.0 -> 11.2 carries).
```
# PER GAME, NOT THE SEASON TOTAL (2026-10-30, Joe: "we had no idea how many
# games Jacobs would miss. that was a complete guess ... should we be using the
# total carry amount or looking at more of the split in workload?"). Jacobs'
# 118.5 carries at his 2025 pace (15.6/g) = 7.6 games: the projections guessed
# ~9 missed, he missed 6. "implied" scales a start-of-season absentee by
# 17 / (preseason total / his per-game pace last season) -- undoing the guess,
# not the actual -- at most PRESEASON_ABSENT_MAX, never below the "scale"
# factor; needs PACE_MIN_G+ games and a real per-game role last season.
# PRESEASON_GIVEBACK: the carries / targets the scale adds come back off his
# same-position teammates' lines (Lloyd's 189 included the starts he made in
# Jacobs' place), in proportion to their lines, so the team total holds.
# TESTED 2026-10-30, not adopted: "implied" +.001/+.001/.000 (net +.002);
# GIVEBACK .000/.000/.000 (even) and nothing on top of WH_RETURN (RB 2024 -.009
# -> -.007); implied + giveback +.001. By the time a start-of-season absentee
# plays, his preseason half is a third of his number (Jacobs wk8 11.0 -> 11.2
# carries).
PRESEASON_GIVEBACK = False
PACE_MIN_G = 6
_PREV_PACE = {}    # pid -> (targets/g, carries/g, games) last season, set in main()
```

## RETURN_KEPT_DEFLATE (and RETURN_KEPT_MIN)
A stronger cut of the fill-in's games when he did NOT outscore a non-workhorse lead
back (game 2: 12.1 projected vs 13.6 actual carries): .5 even.
```
RETURN_KEPT_DEFLATE = None
RETURN_KEPT_MIN = 0.45
```

## LEAD_SKIP_LIM (2026-10-31)
With LEAD_SKIP_EXIT (adopted), the ROUTE_LEAD_TGT anchor also skipping games he PLAYED
hurt (listed, under INJ_SNAP_FRAC of his usual snaps -- DJ Moore wk4, 39% of routes).
On top of both adopted fixes: 5.3585/5.2692/5.0769 -> 5.360/5.269/5.077 (2024 worse,
RB 2025 +.002); alone 5.360/5.270/5.083. Not adopted -- a FULL call on the sheet drops
those games for one player.
```
LEAD_SKIP_LIM = False
```

## GS_PASS_ID / GS_PASS_BASE / GS_RUSH_ID (2026-10-31) -- code kept, off
Joe: "a strong passing team is likely to get their lead by passing, just early on";
"in close games ... a lot more passing later on". pbp 2021-25 (2,718 team-games, team
type = last season's pass rate tercile), dog by 7 -> favored by 7: pass-first dropbacks
40.4 -> 41.5, runs 22.7 -> 24.3; middle 39.5 -> 39.0, 23.5 -> 26.5; run-first 39.7 ->
37.4, 24.5 -> 27.6. In-game, within 8 at the snap: Q1 57.8% pass, Q2 64.1, Q3 57.7, Q4
61.4; games that stayed close Q4 64.5% vs blowouts 59.4%. But a SMALL SPREAD does not
add dropbacks at the same total (+-1, no pattern), so closeness is not a pregame input.
Rule tested: dropbacks x (1 + margin x (BASE + ID x (team pass rate - league))); the
GS_RUSH run boost x (1 - RUSH_ID x dev) for pass-first teams. vs current code
5.359/5.268/5.077:
```
pass side (.063 / -.0011)      +.001 / +.001 / +.001
run side (9)                    .000 / +.001 /  .000
both                           +.002 / +.002 / +.001
both, half                     +.001 / +.001 /  .000
both, x1.5                     +.003 / +.002 / +.001
```
Half strength week by week: 2024 5 better / 12 worse, 2025 8 / 9, 2026 3 / 4 (all
within +-.007). Only 9 player-weeks moved .3+ pts in 3 seasons, 5 closer (Lamar 2024
wk18 BAL favored: 26.6 -> 25.1 passes, threw 32; A.J. Brown 2024 wk14 13.4 -> 12.9,
scored 6.3). The pattern is real but worth ~1-2 plays a team, and the team's own pass
rate already carries most of it. Not adopted.
```
GS_PASS_ID = None
GS_PASS_BASE = 0.0
GS_RUSH_ID = None
```

## ROOKIE_KEFF_MULT / ROOKIE_KEFF_POS (2026-11-01) -- code kept, off
Joe: "shouldn't we be weighting rookies early season production more than league
average any sooner". A player with no earlier NFL season has the efficiency shrink
weight (K_EFF_TGT / K_EFF_CAR x POS_KEFF_MULT) x ROOKIE_KEFF_MULT. Study first: 2022-25
WRs with 20-60 targets in wks 1-8 kept, into wks 9-18, rookies 26% of a yds/target
edge / 41% catch rate / 14% TD rate / 27% pts per target (n=29); veterans 13 / 18 /
12 / 13% (n=198) -- the model already credits 50% at 40 targets. Backtest vs
5.3585 / 5.2685 / 5.0766 (ALL, 4 decimals; rookie player-weeks in brackets):
```
x0.25 (trust own numbers much more)  +.0001 / +.0018 / -.0010   (-.002 / +.011 / .000)
x0.5  (trust more)                   -.0003 / +.0006 / -.0004   (-.003 / +.004 / .000)
x2    (trust less)                   +.0006 / -.0001 / +.0002   (+.005 / -.001 / .000)
WR rookies only x0.5                 +.0001 / +.0004 / -.0003   (.000 / +.002 / -.001)
```
x0.5 week by week: 2024 9 better / 8 worse, 2025 6 / 11, 2026 5 / 2. Boston 2026 at
x0.5 +0.3 to +0.6 a week (closer wks 2, 4, 5; further wks 3, 6, 7), Concepcion -0.1
to -0.4. Even result (within +-.001) -> Joe's call; not adopted for wk8. Re-test x0.5
at wks 10-12 (the 2026 lean is a 2026-only signal).
```
ROOKIE_KEFF_MULT = None
ROOKIE_KEFF_POS = ("WR", "TE", "RB")
```

## MATCHUP_EPA_HL (2026-11-03) -- code kept, off
Joe: "what if we did a more recent EPA counts more as the season goes on than the full
season EPA, especially for defense played against". This season's games in a defense's
EPA rating weighted 0.5 ** (weeks back / HL); shrinkage still on the real play count.
vs current (EPA matchups at half strength, every game equal), 2024 / 2025 / 2026:
```
HL 3 weeks   +.0003 / -.0003 / -.0003   (weeks better/worse 10-6, 7-9, 3-3)
HL 5 weeks   +.0001 / -.0001 / -.0002   (9-7, 9-7, 3-3)
HL 8 weeks    .0000 / -.0001 / -.0001   (10-6, 10-6, 4-2)
```
Noise. The ratings lean on last season (2x weight) early and are shrunk by plays, and at
half strength a defense rating moves a player only a few tenths, so re-weighting within
the season barely changes anything. Re-test with the EPA re-check at wks 10-12.
```
MATCHUP_EPA_HL = None
```

## QB passing-TD rate strength and QB own yards per carry (2026-11-03)

Joe on Lawrence / Stroud (under consensus) and Daniels (rushing). ALL RMSE vs current,
2024 / 2025 / 2026 (wks 2-8):
```
QB_PASS_TD_K 200          +.001 / +.002 / -.001   fails (net +.002)
QB_PASS_TD_K 100          +.002 / +.003 / -.002   fails; QB weeks better 8/17, 8/17, 4/7
QB_PASS_TD_W 0.75         +.002 / +.006 / -.002   fails (2025 clearly worse)
QB_PASS_TD_W 1.0          +.005 / +.014 / -.002   fails
QB_PASS_TD_HIST_W 0.5     +.000 / +.000 / +.001   fails
QB_PASS_TD_HIST_W 0.25    +.000 / +.000 / +.002   fails
QB_PASS_TD_HIST_W 0       +.001 / +.001 / +.006   fails (2026 clearly worse; QB weeks better 2/7)
K_QB_YPC 50               -.005 / +.002 / +.003   fails (2026 worse; QB 2024 -.037)
K_QB_YPC 100              -.005 / +.002 / +.002   fails (net -.001 but 2026 worse; 2026 QB weeks 3/7, 2025 5/17)
K_QB_YPC 200              -.004 / +.002 / +.002   fails
```
Lawrence barely moves under any of them (TD this season only: +0.3/g) -- his misses are
boom/bust weeks, not a steady under-projection. Own ypc helps the runners we were under
(Maye, Daniels 2026) but over-projects others (Lamar, Murray, Daniels 2025); the "rush N"
sheet call covers a QB Joe expects to run more. Re-test K_QB_YPC 100 at wks 10-12 (2024
liked it a lot).
Mixed the backs' way (K_QB_YPC 120 carries; QB_YPC_SEASONS / QB_YPC_HIST_W = past
seasons used / their weight in the rate, carries behind the shrinkage stay real):
```
1 season x0.2 (backs' setup)  -.003 / +.002 / +.002   fails
1 season x0.5                 -.003 / +.002 / +.002   fails
1 season x1.0                 -.003 / +.002 / +.002   fails
4 seasons x0.2                -.004 / +.002 / +.002   fails
2 seasons x0.5                -.004 / +.002 / +.002   fails
```
The mix barely matters. QB RUSHING YARDS do get more accurate every season (error per game
17.00 -> 16.60, 15.04 -> 14.97, 15.95 -> 15.74 at K 100), but the league rate was hiding
two other misses, so total points get worse in 2025-26:
  - pocket QBs it cuts (Goff, Stafford, Cousins) were already UNDER on passing
    (2026 -44 yds and -0.26 TD a game, 2025 -26 / -0.39), so less rushing makes them worse;
  - runners it boosts (Allen, Maye, Lamar) were already OVER on passing
    (2026 +12 yds / +0.18 TD, 2025 +11 / +0.22);
  - both groups get about 1 carry a game too many.
2024 had neither passing miss, which is why it liked own ypc (-.034 at QB).
```
QB_PASS_TD_K = 400.0, QB_PASS_TD_W = 0.5, QB_PASS_TD_HIST_W = 1.0, K_QB_YPC = None,
QB_YPC_HIST_W = 1.0, QB_YPC_SEASONS = 4
```

## QB passing this-season weight, own INT rate, QB carry trim (2026-11-03)

ALL RMSE vs current, 2024 / 2025 / 2026 (QB in brackets where it moved):
```
QB_YPA_HIST_W 0.5                 .000 / +.001 /  .000   fails
QB_YPA_HIST_W 0.2                 .000 / +.001 /  .000   fails
  either + own ypc (backs' way)  -.003 / +.002-3 / +.002  fails
QB_RUSH_MULT 0.9                 +.003 / +.001 / +.001   fails (QB -.009/-.006 in 2025-26, RB +.005: the carries land on the wrong backs)
QB_RUSH_MULT 0.8                 +.007 / +.004 / +.003   fails
QB_RUSH_MULT 0.9 + own ypc       -.001 / +.002 / +.002   fails
K_QB_INT 300                     +.001 /  .000 / +.002   fails (QB 2026 +.016)
K_QB_INT 1000                     .000 /  .000 / +.001   fails
all together                     -.001 / +.002 / +.004   fails
```
The QB passing miss is VOLUME, not efficiency: running QBs throw ~2.4 fewer passes a game
than projected (2025 32.1 vs 29.7, 2026 31.7 vs 29.4) and pocket QBs 1.3-4 more (2026 34.9
vs 38.9). Next candidate: the QB's style (scramble/rush rate) shaping his team's pass
attempts. Until then own ypc keeps failing because it exposes that miss.
```
QB_YPA_HIST_W = 1.0, K_QB_INT = None, QB_RUSH_MULT = 1.0
```

## QB style shapes team pass volume -- ADOPTED 2026-11-03 (Joe)

QB_STYLE_PASS (team pass rate moves S x (starters' avg carries per attempt - his)),
QB_STYLE_QB_RUNS (share of the run side that is the QB's own scrambles). vs current:
```
S 0.1, runs to backs        +.001 /  .000 / -.002   net -.001
S 0.2, runs to backs        +.001 /  .000 / -.003   net -.002 (RB +.005)
S 0.3, runs to backs        +.002 /  .000 / -.004   net -.002
S 0.2, all to QB            -.002 /  .000 / -.002   net -.004 (QB +.017 2025-26)
S 0.2, half to QB           -.001 / -.001 / -.003   net -.005  <- ADOPTED
S 0.25, half to QB          -.001 / -.001 / -.003   net -.005 (TE 2024 +.004)
S 0.2, quarter to QB         .000 / -.001 / -.003   net -.004
S 0.2 half + own QB ypc     -.003 /  .000 / -.002   net -.005 (2026 less: left off; re-test wks 10-12)
```

## QB form: move a QB toward his season-long miss (2026-11-04)

Joe: Purdy slipping with SF's injuries, Daniels / Lawrence low, Darnold high. QB_FORM_W moves
a QB's projection W x his average (actual - model) this season, shrunk by QB_FORM_K games
(backtest only). vs current, 2024 / 2025 / 2026 (QB in brackets):
```
W .25 K4   -.001 /  .000 / +.001   (QB -.004 / -.002 / +.008)  fails
W .5  K2   +.005 / +.005 / +.008   fails
W .5  K4   +.001 / +.002 / +.004   fails (QB 2026 +.031)
W .5  K8   -.001 / +.001 / +.002   fails
W .75 K4   +.006 / +.008 / +.009   fails
```
QB misses don't carry over: early-season miss vs later-season miss correlates +.12 / +.10 /
+.08, and in 2026 only 9 of 25 QBs kept the same direction (Purdy +4.3 in wks 2-5, -5.9 in
6-8; Goff, Stafford, Young the same flip). Consistent ones: Herbert / Jones over, Burrow /
Cousins under. Wks 3-8 2026 QB error: ours 7.01, consensus 6.85.
```
QB_FORM_W = None
```

## Lead-back carry trim -- ADOPTED 2026-11-04 (Joe)

Backs projected 20+ carries got 2-3 fewer every season (21.3 vs 19.1, 21.3 vs 18.5, 22.2 vs
19.5); top-8 2026 backs 19.7 projected vs 18.0 actual (sites 18.1). In those games the team
ran fewer plays -- other backs +0.6/+0.4/+1.1, team runs -2.2/-3.5/-1.7, passes -1.0/+0.3/-0.7
-- so the trim drops most carries and never makes passes. vs current (2024 / 2025 / 2026):
```
keep .5 above 15, all to backups    +.009 / -.002 / +.006   fails
keep .7 above 15, all to backups    +.003 / -.003 /  .000   even
keep .85 above 15, all to backups   +.001 / -.002 / -.002   net -.003
keep .9 above 12 / above 10         +.001-2 / -.002-3 / -.002   net -.003
keep .85 above 15, 30% to backups   +.001 / -.002 / -.002   net -.003  <- ADOPTED
  same, lead back keeps his TDs     +.001 / -.001 / -.001   net -.001
keep .7 above 15, 30-50%, keep TDs  +.002 / -.002 / -.002   net -.002
```
```
CARRY_TRIM_K = 0.85, CARRY_TRIM_AT = 15.0, CARRY_TRIM_BACKUPS = 0.3, CARRY_TRIM_TD = True
```

## Pass-catcher target trim (2026-11-04)

TGT_TRIM {pos: (keep, above N targets)}, TGT_TRIM_REST = share of the trimmed targets given to
the team's other catchers (rest dropped). When a WR1 was projected 9+ targets his team threw
-1.3 / -0.7 / -1.5 fewer passes than projected and his teammates were not up (-1.08 / -0.16 /
+0.12), so dropping them fits. vs current (2024 / 2025 / 2026, WR in brackets):
```
WR .85 above 8, all to teammates  +.001 / -.001 / -.002   net -.002
WR .7 above 8, 30% to teammates   +.002 / -.002 / -.004   net -.004
WR .7 above 8, dropped            +.002 / -.002 / -.005   net -.005 (WR +.005/-.005/-.012)
WR .7 above 9, dropped            +.001 / -.001 / -.005   net -.005
WR .6 above 9, dropped            +.001 / -.001 / -.006   net -.006 (WR +.003/-.003/-.015)  <- ADOPTED (Joe)
WR .5 above 8, 30% to teammates   +.005 / -.001 / -.004   even (2024 WR +.011)
WR .7 above 7, 30%                +.005 / -.001 / -.002   fails
WR .7/8 + TE .85/7, dropped       +.001 / -.002 / -.005   net -.006 (2026 less than WR .6/9)
TE .85 above 5.5, 50%             -.001 / +.001 / +.001   fails
TE .7 above 5, 50%                 .000 / +.002 / +.003   fails
```

## TE matchup strength, QB own ypc re-test, QB carry trim (2026-11-04)

vs current (after QB style, carry trim, WR target trim), 2024 / 2025 / 2026:
```
MATCHUP_EPA_BETA_POS TE 0 (no TE matchup)  .000 / +.001 / +.003   fails (TE 2026 +.015)
  TE 0.5                                  +.001 / +.001 / -.002   even (TE 2026 -.011)
  TE 0.75                                 +.001 / +.001 / -.003   net -.001, even band (TE +.004/+.006/-.018) -- ADOPTED (Joe 2026-11-04)
  TE 1.0                                  +.002 / +.003 / -.004   fails
K_QB_YPC 120 (backs' mix) / 300 / 300 all -.002 to -.004 / +.001-2 / +.001-2   fail (QB 2024 -.016 to -.026, 2025-26 +.008 to +.016)
QB_CARRY_TRIM .5 above 4 (alone)           +.015 / -.002 / +.001   fails (QB 2024 +.095)
  .5/4 / .7/4 / .5/5 / .3/4 / .5/3 + own ypc  all fail on 2024 (+.003 to +.019)
```
QB rushing: running QBs (6+ projected carries) get 1-2 too many carries at too low a yds/carry
(8.5/7.3 at 4.1 vs 5.2; 8.0/6.0 at 4.6 vs 4.7; 7.3/5.5 at 4.4 vs 5.3) -- the misses cancel in
yards. But their TOTAL miss swings by season (2024 18.2 vs 20.6, 2025 19.3 vs 18.3, 2026
19.1 vs 20.3), so every fix wins one season and loses another. The "rush N" call is the tool.
TE: touchdowns are 44-63% of TE squared error (top-12: 6.19 -> 4.63 / 6.54 -> 3.97 / 6.78 ->
4.30 if the TDs had been known).
```
MATCHUP_EPA_BETA_POS = {"TE": 0.75}, QB_CARRY_TRIM = None, K_QB_YPC = None
```

## QB matchup strength, PASS_RECON_W (2026-11-04)

```
MATCHUP_EPA_BETA_POS QB 0 / 0.5 / 0.75   .000 / .000 / .000 exactly -- the QB_drop (dropback
    EPA) rating is computed but Matchups.apply never uses a QB "ypa" factor: QB passing yards
    only follow the receivers' adjusted yards, INTs use "int" (residual mode only). Not wired.
PASS_RECON_W 0     +.003 / +.001 / -.001   fails
PASS_RECON_W 0.5   -.001 / +.001 / +.001   fails
PASS_RECON_W 0.75  -.002 / +.002 / +.004   fails
```
2026 wks 3-8 QB components vs the sites' stat lines (starters, 15+ att): points error QB1-12
ours 6.92 / sites 7.03, QB13-32 6.39 / 6.47; every component within a hair. Starting QBs'
pass yards projected low every season: 214 vs 229, 216 vs 222, 219 vs 230 (partly selection:
15+ att drops early exits).

## QB matchup wired, in-season league QB efficiency, team's own TDs, own sack rate (2026-11-04)

vs current, 2024 / 2025 / 2026 (QB in brackets):
```
MATCHUP_QB_USE td                +.002 / +.001 / -.003   even (QB +.012 / +.002 / -.017)
MATCHUP_QB_USE td/int            +.003 / +.001 / -.003   fails
MATCHUP_QB_USE yds/td/int        +.005 / +.001 / -.006   fails (QB 2026 -.040, 2024 +.032)
  td/int at QB beta 0.5          +.005 / +.001 / -.005   fails
LG_QB_EFF_K 2000 / 5000           .000 /  .000 /  .000   no effect
TEAM_TD_OWN_W .25                +.002 / +.006 / +.006   fails (Vegas beats team history)
TEAM_TD_OWN_W .5                 +.005 / +.013 / +.014   fails
SACK_OWN_K 500                    .000 /  .000 /  .000   even
SACK_OWN_K 200                    .000 / -.001 / -.001   net -.002 (QB -.004/-.001/-.002)
SACK_OWN_K 100 / 150              .000 / -.001 / -.001   net -.002 (QB -.005/-.003/-.004; QB weeks 9-8, 10-7, 3-4)
SACK_OWN_K 100 + QB_USE td       +.002 / -.001 / -.004   net -.003 (QB +.007/-.001/-.021; QB weeks 7-10, 8-9, 5-2)
```
The QB dropback rating, like the TE one, is a 2026-led signal.
ADOPTED 2026-11-04 (Joe): SACK_OWN_K = 100.0, MATCHUP_QB_USE = ("td",).

## QB own yards per carry, proven runners only / healthy only (2026-11-04)

Joe on Daniels (6.0 ypc 2024, 4.8 in 2025 on the knee, 8.7 this year on 27 carries, model
4.4-4.6 = league QB rate). QB_YPC_PROVEN = (past carries, ypc) -- own rate only for those
QBs, only upward; QB_YPC_HEALTHY skips QBs on that week's injury report. vs current:
```
proven 100/5.0, K 120        -.006 / +.003 / +.002   fails (QB -.034 / +.024 / +.010)
proven 100/5.0, K 300        -.004 / +.002 / +.001   fails
proven 100/5.0, K 60         -.006 / +.004 / +.002   fails
proven 150/5.5, K 120        -.005 / +.003 / +.002   fails
proven 60/5.0, K 120         -.006 / +.003 / +.002   fails
proven 100/5.0 K120, 2 seasons -.005 / +.003 / +.003 fails
+ healthy only (any / status) K 300   -.004 / +.002 / +.001   fails
+ healthy, + QB_CARRY_TRIM .7/6       -.001 / -.001 / +.001   fails (2026)
every QB, healthy only, K 300         -.004 / +.002 / +.002   fails
```
Hurt most: Lamar (2026 6.8 projected carries vs 3.0, 2025 8.7 vs 5.1), Daniels 2025 (+3.6);
helped: Daniels 2026 (-2.2), Maye. Runners' carries are too high, so a higher rate overshoots.
Added the sheet call instead: "ypc 6.5" / "rush 6 ypc 6.5" (Daniels wk9: 15.2 -> 16.9).
```
K_QB_YPC = None, QB_YPC_PROVEN = None, QB_YPC_HEALTHY = None
```

### A backup taking over mid-season (2026-11-04, Joe on Milton / PHI)
Milton (no starts) read the Eagles' pass rate and QB-run share from nothing, so they fell
to the anchor -- half last season's Hurts offense. McKee's wks 6-8 (no Smith/Wicks,
Saquon limited: 61-68 plays, 34-45 passes) were ignored. Joe: McCarthy (2 starts) IS the
Giants' starter -- read his own games; Fagnano is brand new; Lock has history. So the
fair version is "no starts before this week" only. Starts are counted from EARLIER games
(a backtest's qb_patt holds the week being projected -- first run counted it). ALL
change 2024 / 2025 / 2026:
```
NEW_STARTER_GAMES=1               (no prior starts: read the games since the regular went down)   .000 / .000 / .000   even (QB 2024 -.001)
NEW_STARTER_GAMES=1 + NEW_STARTER_LG (and league anchor, not last season's team)   .000 / .000 / .000   even (WR 2024 +.001, QB 2025 +.001)
NEW_STARTER_GAMES=3 + NEW_STARTER_LG                                         -.001 / .000 / .000   net gain, but QB 2025 +.003
```
Rare (a QB taking over after another backup already started). Wk9 it fires only on PHI
(era = McKee's wks 6-8; Lock / Fagnano already have a game with real snaps): pass att 28.5
-> 29.1 (29.4 with LG), Milton 5.3 -> 4.3 carries, Goedert 6.70 -> 6.85. The bigger PHI gap
is PLAYS: the 39.5 total cuts them to 56 (McKee's starts at totals 39.5 / 43.5 / 40.5 ran
61 / 62 / 68).
```
NEW_STARTER_GAMES = 1, NEW_STARTER_LG = False   ADOPTED 2026-11-04 (Joe's tiebreak: tie + toward consensus/FTN)
```

### Near misses re-judged by Joe's tiebreak (2026-11-04)
Joe: "If it is essentially a tie, but making our projections align closer to consensus or at
least other reputable sources, I would be ok with the change." 2026 wks 3-8 backtest, change in
the average |ours - source| on the player-weeks each setting moves (- = closer):
```
setting                                         backtest ALL        QBs vs cons  vs FTN  Joe's names vs cons
proven 100/5 K300 + healthy + QB_CARRY_TRIM .7/6  -.001/-.001/+.001   -0.14        -0.08   -0.11
QB_PASS_TD_HIST_W 0.5                            .000/ .000/+.001    -0.02        -0.01   -0.03
K_QB_YPC 100                                    -.005/+.002/+.002    -0.04         .00    -0.08
K_QB_INT 1000                                    .000/ .000/+.001     .00         +0.02   -0.11
QB_FORM_W .25                                   -.001/ .000/+.001    +0.03        +0.08   +0.07
PASS_RECON_W 0.5                                -.001/+.001/+.001    +0.02        +0.02   +0.04
```
proven/healthy/trim + NEW_STARTER_GAMES 1 together: ALL -.001 / -.001 / +.001, QB -.003 / -.005 /
+.006 -- toward the sources but QBs a bit further from actual in 2026. Asked Joe.
(QB_YPC_HEALTHY via --set "any" ran as "status" -- a --set string becomes a tuple.)
**ADOPTED 2026-11-04 (Joe):** QB_YPC_PROVEN 100/5.0, K_QB_YPC 300, QB_YPC_HEALTHY "status",
QB_CARRY_TRIM 0.7/6 -- "even though I know you're saying it is a small hit to this year. I think
we've seen some weird cases this year with some of the running QBs playing injured." Baseline
saved: 2024 5.367 (QB 7.214), 2025 5.261 (6.896), 2026 5.150 (6.803). The carry trim skips a
QB with Joe's "QB carries" call (his number is never trimmed).

### Designed runs vs scrambles vs kneel-downs (2026-11-04, not a setting)
Joe: "would it be important to figure out avg number of rushes by designed runs and scrambles.
I would think designed runs is more predictable" + "is a scramble considered a pass play in the
run-pass split". Play-by-play 2023-26, starter games (15+ dropbacks),
research/qb_run_types.py + qb_run_types_followup.py. Stat-line carries = designed + scrambles + kneels in
100% of games.
- A starter's game: 1.37 designed (3.1 ypc -- sneaks), 1.87 scrambles (7.5), 0.64 kneels (-1.1).
  Runners (5+ a game): 3.2 / 3.0 / 0.7.
- Joe is right on predictability: odd-vs-even starts r .85 designed, .75 scrambles, .15 kneels;
  next game r .66 / .49 / .07.
- But splitting does NOT help the forecast: next-game carries miss 2.177 one number -> 2.156
  apart, and ALL of that gain is kneels (kneels at league avg, designed+scrambles together:
  2.156). Rushing yards 16.18 -> 16.16. Best pull to league ~2-3 games for both kinds.
- Scrambles follow dropbacks (+10 dropbacks -> +0.46), designed runs follow team runs (+10 ->
  +0.50), but the game's REAL dropbacks didn't improve the scramble forecast (2.165 vs 2.161).
- Injury: runners (4+) on the practice report with no game status (81 games): designed -0.43 a
  game vs his norm, scrambles -0.05 -- the injury shows up in designed runs. Q/D only 8 games.
- Team data: a scramble (and a kneel) counts as a RUN in team_weekly pass_rate / qb_rush_share
  (official stats); a sack counts as a pass. Same definition in history and projection, so
  pass attempts / targets are not biased; QB carries ride team runs, not dropbacks.
Not built. Possible tests: kneels out of QB carries/ypc (game-script item), and a designed-run
cut for a runner on the practice report.
- Per QB 2024-26 (12+ starts) scrambles per dropback: Daniels .131, Fields .105, Maye .101,
  Lamar .086, Allen .083 ... Goff .016, Cousins .010, Stafford .009 (league .053). The model's QB
  carries are already his own (team QB share of runs in his starts, last season as anchor).
- LEG injuries only (Joe: "only cut the designed runs for a QB who has a leg injury maybe?"):
  runners listed with a leg injury (30 games) designed -0.22, scrambles +0.15; other injuries
  (48) designed -0.44. Leg injuries do NOT cut designed runs more -- not built. (nflverse's
  practice_status is mostly the week's last day, "Full", so DNP/limited can't be split out.)

### KNEELS_OUT (2026-11-04) -- FAILS, off
Kneels out of QB carries / yards and team runs / plays (inputs only; grading uses the real
line), league kneel yards per team game added back to the starter. data/qb_kneels_<yr>.csv
(build_qb_kneels.py, 2021-26; in the daily refresh). Baseline = QB rushing set on.
```
KNEELS_OUT=1            ALL -.002 / .000 / +.004   QB -.021 / -.003 / +.025   net +.002 FAILS
 + QB_YPC_PROVEN 100/5.75   identical (no proven runner sits between 5.0 and 5.75 kneel-free)
```
QB rushing yards miss 16.75 -> 16.63 / 14.97 -> 15.06 / 15.72 -> 15.72. Pocket QBs (< 3
projected carries) rush yds 6.0 -> 5.0 (actual 6.1) / 7.2 -> 6.0 (5.6) / 7.8 -> 6.4 (6.2):
closer in 2025-26 -- but in 2026 those QBs are UNDER-projected on everything else by 0.95 pts
a game (2024 -0.24, 2025 +0.21), and the kneel yards were covering it (Cousins, Stafford, Goff,
Burrow worse on total). Herbert 2026 becomes a proven runner kneel-free (+0.57, over-projected
already). Revisit after the 2026 pocket-QB passing gap is understood.
Follow-up (same night): projected starters (20+ projected att), passing points proj vs actual --
pocket QBs +0.95 / +0.76 / -0.53 (2024 / 25 / 26), runners 5+ -0.88 / -0.26 / +0.10. The 2026
pocket gap is nearly all Burrow (6 g, -6.2 a game: 252 yds / 2.2 TD projected vs 310 / 3.2),
then Cousins -3.3, Young -2.3, Love -1.5; Prescott +4.7, Jones +2.8, Darnold +2.1 the other way.
No passing rule to make (2024-25 lean the other way; form-chasing already failed). KNEELS_OUT
goes on the wks 10-12 re-test list -- its 2026 loss is a few QBs over 7 weeks (Herbert +41,
Cousins +21, Burrow +11 squared-error).
Without Burrow (Joe: "is there a trend to go on then?"): 2026 pocket QBs even (-0.02, 9 QBs low /
8 high). Kneel test still loses 2026 QBs without him (+.023; without Burrow + Herbert +.010).
The trend that DOES repeat (projected starters, no Burrow, no injury exits; passing pts):
```
          pocket (<3 car)                       runners (5+)
2024  +0.67 (yds -.06 TD +.64 INT +.09)   -0.93 (yds -.24 TD -.24 INT -.46)
2025  +0.62 (yds +.42 TD +.33 INT -.14)   -0.46 (yds -.32 TD  .00 INT -.15)
2026  -0.02 (yds -.14 TD +.03 INT +.09)   -0.85 (yds -.84 TD +.13 INT -.13)
```
Running QBs' passing is low every season: too many INTs projected (league INT rate for all;
~0.23 / 0.08 / 0.07 a game) and too few yards. Same with QB_STYLE_PASS 0 (pocket +0.49 / +0.71 /
+0.23, runners -0.78 / -0.24 / -0.71) -- not the style rule. Lead: tie the INT rate (maybe
yds/att) to the QB's style -- steadier than his own INT rate (K_QB_INT failed 2026).

### QB_STYLE_INT / QB_STYLE_YPA (2026-11-04, Joe: "sure go ahead and test it") -- FAIL, off
INT rate x (1 - S x rel), ypa x (1 + Y x rel), rel = (his carries per attempt - starters') /
starters' (shrunk QB_STYLE_K 300); one-sided = runners only. QB RMSE change:
```
QB_STYLE_INT .3               -.020 / +.008 / +.015   (ALL -.003 / +.001 / +.002)
QB_STYLE_INT .3 one-sided     -.017 / +.011 / +.007
QB_STYLE_INT .15              -.011 / +.004 / +.007
QB_STYLE_INT .15 one-sided    -.009 / +.005 / +.003
QB_STYLE_YPA .05 one-sided    -.005 / +.003 / +.002
```
Why only 2024: runners' TOTAL points (rushing too) proj - actual, projected starters: -1.81 /
+0.25 / +0.69 (healthy games -1.93 / +0.05 / -0.36). In 2025 their rushing runs a bit high and
cancels the passing gap; in 2026 5 of 48 runner games ended in an injury exit (10%, vs 3% for
both groups over 2024-26). The "no injury exits" table above overstated the 2026 gap. Pocket QBs'
total: +1.09 / +1.14 / -0.59. No stable direction to build on -- nothing to re-test early.

### Big gaps vs consensus -- which part of the model to fix (2026-11-04)
Joe: "it can look bad to be so much higher or lower on a player than the rest that I can't
really defend" ... "I would prefer to fix the model for WR, QB and TE. a review step isn't a bad
intermediary". Review step: the gap report now prints on the workbook's Calls tab (BIG GAPS).
2026 wks 3-8, current model walk-forward vs archived consensus (research/who_is_right.py):
3+ pt gaps 39 of 1850 player-weeks, we were closer 51%; usually we're the HIGH one (30/39); WR
gaps consensus closer 64%, QB we 62%, TE 3 of 4. Fantasy-relevant 3+ gaps: halfway to consensus
6.16 -> 5.83 miss (all the way 6.08).
Which PART holds up (research/gap_parts.py; slope of actual-cons on ours-cons, 1 = ours fully
right): WR targets .23 rec yds .49 TD .50, yds/target .03, TD/target .16; TE targets .32, yds/tgt
.35, TD/tgt .81; QB att .61 yds .57 TD .83 INT .02, carries -.25 rush yds -.02 (2026 QB rush yds
ours 17.4 / cons 16.3 / actual 14.5); RB carries .11 rush yds .00 rush TD .68.
Big WR/TE gaps (2.5+) are 72% TARGETS. With team volume taken out, our target SHARE gaps are
mostly right (slope WR .65, TE .55; when our share is 3+ pts above cons: ours .162 cons .116
actual .157; below: .210 / .253 / .221); team targets slope .59.
```
POS_KEFF_MULT WR:1 (was .5)  ALL -.001 / .000 / +.001 even; WR -.003/+.001/+.002, QB -.004/-.006/+.001
   2026 WR: |vs cons| .964 -> .956, |vs FTN| 1.064 -> 1.044, 3+ gaps 10 -> 8 (2+ 46 -> 49);
   QB 3+ gaps 13 -> 12; WR stars -.01 cons / -.04 FTN / -.02 actual  -> QUALIFIES by the tiebreak,
   position catch WR 2026 +.002 -> asked Joe
POS_KEFF_MULT WR:2           ALL -.002 / .000 / +.004 (WR 2026 +.007) FAILS
POS_KEFF_MULT TE:1           ALL +.001 / .000 / .000 (TE +.002/.000/-.003) FAILS (net +.001)
K_QB_RUSH 6 (was 3)          ALL +.001 / +.002 / +.001 (QB +.009 2025) FAILS
```

### REC_TD_OWN_K -- a receiver's own TD rate (2026-11-05) -- FAILS, off
Joe: "are we using the players usual TD rate or the teams or NFL average for everybody?" ...
"yes please test it, I would assume we need to test TE TD rate too". Receivers' TD weight =
target share x position league TDs/target x red-zone role (RZ_EXP .5) x WR1 season tier,
renormalised to the team's passing TDs. Test: his own TDs/target (last season + this season)
shrunk toward the position rate by K targets, in place of the league rate.
```
REC_TD_OWN_K WR:300    ALL +.004 / +.002 /  .000   WR +.008 / +.005 / -.002   fails
REC_TD_OWN_K WR:1000   ALL +.001 / +.001 /  .000   WR +.003 / +.002 / -.001   fails
REC_TD_OWN_K TE:300    ALL -.002 / +.002 / +.003   TE -.008 / +.010 / +.006   fails
REC_TD_OWN_K TE:1000   ALL -.001 / +.001 / +.001   TE -.004 / +.003 / +.002   fails (near tie)
```
Tiebreak check (2026 wks 3-8): TE 1000 -- TE |vs cons| .912 -> .914, 3+ gaps 4 -> 5 (no help);
WR 300 -- WR stars +.06 further from consensus, +.08 from FTN. The red-zone role (his share of
targets inside the 10) stays the player-specific TD piece.

### POS_SPREAD TE / TOP_SHRINK WR (2026-11-05) -- ADOPTED
Joe: "I thought we were pretty bad for TE too. but yes do any test you think is helpful".
Scoreboard (research/scoreboard_vs_sources.py, wks 3-8, same player-weeks): published WR 5.01
(field 4.96-5.05, tie with consensus), TE 4.80 vs consensus 4.67; today's model rerun WR 4.98,
TE 4.70. Calibration slope of actual on our projection: TE .952 / .938 / .906 every season (top
TEs high -- TDs .51 vs .31, .52 vs .33 in 2024-25 -- low TEs low); WR 1.003 / .952 / .992 but
the 14+ tier high every season (yds/target 9.18 vs 8.94, 8.90 vs 8.65, 9.80 vs 8.68).
```
POS_SPREAD TE:.95                 ALL .000 / .000 / -.001   TE -.002 / -.003 / -.008  passes
TOP_SHRINK WR:14/.85              ALL .000 / -.001 / -.001  WR  .000 / -.002 / -.002  passes
both                              ALL .000 / -.001 / -.002  (net -.003)               ADOPTED
TE .92 + WR 14/.85                TE .000 / -.003 / -.010 -- 2024 gain gone, kept .95
```
2026 wks 3-8 vs consensus: WR stars .16 closer (FTN .26, actual .06); relevant TEs |vs cons|
.912 -> .851, |vs FTN| 1.042 -> .970, 3+ TE gaps 4 -> 1; WR |vs cons| .964 -> .944. Week by
week 2026 TE better 4 / same 1 / worse 2 (all within .03). Wk9: Bowers 13.29 -> 12.83, Kittle
13.05 -> 12.62, McBride 11.81 -> 11.45; Nacua 19.19 -> 18.42, St. Brown -0.36, Lamb -0.32,
Chase -0.29; backup TEs +0.17. Baseline saved 2026-11-05.
SPREAD_TO_QB (same day, Joe: "go ahead and test the QBs, but I feel like we were low on QBs a lot
already"): the receivers' WR/TE change in yards / TDs passed to their QB(s) so each team adds up.
ALL .000 / .000 / -.001, QB .000 / -.001 / -.005 -- ADOPTED; 2026 wks 3-8 QBs .04 closer to
consensus and FTN, QB 3+ gaps 13 -> 10. Wk9: Stafford 18.52 -> 18.25, Cousins -.22, Goff -.16.
QB level check: published 2026 wks 3-8 QBs -0.15 vs actual (consensus -0.09; cons 15+ tier
-0.60 vs -0.35). Today's model on all games, projected starters: -0.35 / +0.48 / +0.40
(2026: 17+ -0.3, 14-17 +0.6, under 14 +1.1) -- the QB rushing / style changes since then lifted
QBs; slope 1.08 / .91 / 1.18, no steady spread fix.
