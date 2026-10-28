# research/ — one-off studies (not part of the weekly run)

Moved here 2026-10-28 during the model cleanup. Nothing in the weekly pipeline
imports these. They are kept as the record of how some constants were chosen.
Settings that were tested and then removed from project.py are documented in
`../TESTED_SETTINGS.md`.

| script | what it answered | still used? |
|---|---|---|
| fit_dfs_efficiency.py | how hard to shrink a player's own efficiency (K_EFF_TGT 80 / K_EFF_CAR 120) | constants live in project.py |
| fit_qb_rush_td.py | per-QB rushing-TD rate (QB_RUSH_TD_DECAY 0.75) | constants live in project.py |
| fit_shrinkage.py | first pass at the k constants, against a position average | volume k refit in fit_usage_shrinkage |
| fit_usage_shrinkage.py | volume k constants, against the player's own last season | constants live in project.py |
| sweep_depth_weight.py / sweep_prior_weight.py | how much the depth chart should pull a veteran's prior | live model uses depth_weight 0 for veterans |
| sweep_workhorse.py | whether a stubborn prior helps established workhorses early | workhorse returns now handled by RETURN_STAR_* |
| analyze_snaps.py / test_snap_weighting.py | snap share vs touch share; how to count partial games | starting point for partial-game counting |
| neutral.py | neutral-situation pass rate per team-game | not adopted |
| partial_games.py | count a game he left hurt over the plays he was there for; `--calibrate YEAR` checks exit timing against participation data | not adopted (EXIT_KEEP_W instead) |

These scripts call `project.py` as it was when they were written. Several pass
arguments or settings that have since been removed (the old "ranking" model,
QB start carries, the swept settings), so expect to update them before
re-running one. Run from this folder: each one finds `ff_weekly_model/` as its
parent.
