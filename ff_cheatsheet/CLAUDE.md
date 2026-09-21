# Fantasy Football Cheat Sheet — Workbook Update Project

## Goal
Sibling project to `ff_adp` (consensus ADP) and `ff_draft_proj` (consensus
season projections). Where those two projects produce/maintain
`combined_adp.csv` and `consensus_<pos>.csv`, this project takes that data
and pushes it into the live Excel cheat sheet workbook:

```
C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm
```

All workbook-writing scripts here use `win32com.client` (Excel COM
automation), not `openpyxl` — this preserves the workbook's Data Validation
and Conditional Formatting, which `openpyxl`'s `wb.save()` strips.

## Scripts

### Workbook updaters (win32com)
- `full_adp_refresh.py` — the main "update everything" entry point. Runs
  every ADP fetcher in `ff_adp/run_all.py`, merges into
  `../combined_adp.csv`, aligns player names with the Projections sheets,
  and rewrites the workbook's ADP tab (columns A, C, D, B, E:P) from scratch.
- `refresh_adp_tab.py` — re-syncs the ADP tab's value columns (B-P) from
  `../combined_adp.csv` without re-fetching anything. Use after running
  `refresh_sources.py` / `merge_new_sources.py`.
- `add_adp_columns.py` — one-off: inserts new ADP source columns (RTSports,
  NFFC Cutline) into the ADP tab and updates the Cheat Sheet's ADP formula
  (column M) to reference them.
- `load_cheatsheet_players.py` — rebuilds the Cheat Sheet player pool
  (columns A-D) from the QB/RB/WR/TE Projections tabs, sorted by Consensus
  ADP, and extends the formula columns (E:U) to match.
- `update_cheatsheet_com.py` — re-syncs the ADP tab from
  `../combined_adp.csv` via Excel COM (earlier/simpler variant of
  `refresh_adp_tab.py`).

### combined_adp.csv helpers (no workbook access)
- `refresh_sources.py` — refreshes one or more site columns in
  `../combined_adp.csv` from their cached per-source CSVs in `../ff_adp/`,
  then recomputes Consensus.
- `merge_new_sources.py` — one-off: folds RTSports/NFFC Cutline columns into
  `../combined_adp.csv` and recomputes Consensus over the expanded site list.
- `fix_adp_names.py` — renames players in `../combined_adp.csv` to match the
  Projections sheets' spelling/capitalization (e.g. "A.j. Brown" ->
  "A.J. Brown") so the Cheat Sheet's VLOOKUP matches.

## Conventions / ground rules
- All `BASE`/`ADP_DIR` paths resolve via `Path(__file__).resolve().parent.parent`
  (the `FF_ADP` repo root) — `ff_adp`, `ff_draft_proj`, and `ff_cheatsheet`
  are siblings at the same depth, so this resolves correctly regardless of
  which directory a script lives in.
- Scripts that import from `ff_adp/run_all.py` add
  `sys.path.insert(0, str(BASE / "ff_adp"))` before the import.
- Never use `openpyxl` to save this workbook — it strips Data Validation and
  Conditional Formatting. Always use `win32com.client`.
