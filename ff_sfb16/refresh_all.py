"""One-command full refresh for the SFB16 cheat sheet:

  1. Pull fresh projections from every source and rebuild the consensus
     CSVs (ff_draft_proj/run_all.py --no-sheets).
  2. Refresh every existing player's stat line on the Projections tabs from
     that fresh consensus data (build_sfb16_workbook.py). The SFB16 bonus
     columns (Exp 300+ Pass Yd Games etc.) are live Excel formulas (see
     setup_bonus_formulas.py) that recalculate automatically from those
     stat columns — no separate push step needed for them.
  3. Add any consensus player who isn't a row on the Projections/Cheat
     Sheet tabs yet (add_missing_players.py) — e.g. a newly-added source
     surfaces a player nobody had projected before.
  4. Discover any newly started/finished SFB16 drafts on Sleeper
     (discover_sfb16_drafts.py).
  5. Recompile ADP from every known SFB16 draft, including further-along
     in-progress ones (compile_sleeper_adp.py).
  6. Push that ADP into the workbook's ADP tab + Cheat Sheet formula,
     including the Jr./Sr./III and nickname alias matching
     (update_adp_from_sleeper.py).

Each step is its own existing script — this just runs them in the right
order and stops at the first failure. Close the workbook in Excel before
running this; the win32com steps need an exclusive lock on the file.

Usage:
    python refresh_all.py
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DRAFT_PROJ_DIR = BASE.parent / "ff_draft_proj"

STEPS = [
    ("Refresh all projection sources + rebuild consensus",
     [sys.executable, "run_all.py", "--no-sheets"], DRAFT_PROJ_DIR),
    ("Refresh existing players' stat lines in the workbook",
     [sys.executable, "build_sfb16_workbook.py"], BASE),
    ("Add any new consensus players not yet on the sheet",
     [sys.executable, "add_missing_players.py"], BASE),
    ("Discover new/updated SFB16 Sleeper drafts",
     [sys.executable, "discover_sfb16_drafts.py"], BASE),
    ("Compile ADP from all known SFB16 drafts",
     [sys.executable, "compile_sleeper_adp.py"], BASE),
    ("Push ADP into the workbook",
     [sys.executable, "update_adp_from_sleeper.py"], BASE),
]


def main():
    for label, cmd, cwd in STEPS:
        print(f"\n=== {label} ===")
        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            sys.exit(f"\n[FAILED] {label} (exit {result.returncode}) — stopping.")
    print("\nSFB16 cheat sheet fully refreshed.")


if __name__ == "__main__":
    main()
