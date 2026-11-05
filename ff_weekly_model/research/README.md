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
| scoreboard_vs_sources.py | our PUBLISHED finals vs every source, same player-weeks, by position and tier (2026-11-05) | wks 3-8: WR mid-pack (field within 0.1), TE ~0.13 behind |
| who_is_right.py / gap_parts.py / gap_count.py | 2026: when we're far from consensus who was right; which part of the gap (volume / efficiency / TD) holds up; big-gap counts per variant (2026-11-04) | usage in each docstring; DUMPS = folder of backtest dumps |
| qb_run_types.py / qb_run_types_followup.py | QB carries split into designed runs, scrambles, kneels: stability, game script, injury, forecast (2026-11-04) | not built -- splitting didn't help the forecast; kneels did (TESTED_SETTINGS.md) |

These scripts call `project.py` as it was when they were written. Several pass
arguments or settings that have since been removed (the old "ranking" model,
QB start carries, the swept settings), so expect to update them before
re-running one. Run from this folder: each one finds `ff_weekly_model/` as its
parent.

`partial_games.py` moved back into the model on 2026-10-29: FULL uses it.
