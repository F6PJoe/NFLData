#!/usr/bin/env python3
"""Baseline guard: a model change is only used if the backtest says so.

    python baseline_guard.py                       # current code vs the saved baseline
    python baseline_guard.py --set NAME=VALUE ...  # judge a candidate setting
    python baseline_guard.py --update              # save the current results as the baseline

Built 2026-10-24. Runs the walk-forward backtest for 2024, 2025 and 2026 (in
parallel) and applies Joe's adoption rule (2026-10-22): "Must not hurt 2026,
plus a net gain overall" --
  - the ALL-positions RMSE summed over the three seasons is no worse
    (a net gain to adopt a new setting; equal for a refactor),
  - 2026 is not worse (a change of 0.001 or less counts as even),
  - no single season is clearly worse (0.005+).
When 2026 has a newly graded week the old 2026 number is not comparable; it
is reported, the rule is applied to 2024-25, and --update re-baselines.

Exit code 1 if the rule fails. The baseline lives in
data/backtest_baseline.json.
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "data", "backtest_baseline.json")
YEARS = (2024, 2025, 2026)
POS = ("ALL", "QB", "RB", "WR", "TE")
EVEN, CLEARLY_WORSE = 0.001, 0.005


def run(year, sets):
    cmd = [sys.executable, os.path.join(HERE, "project.py"), "--year", str(year)]
    for s in sets:
        cmd += ["--set", s]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE).stdout
    res = {}
    m = re.search(r"walk-forward backtest, \d+ weeks (\d+)-(\d+)", out)
    res["weeks"] = f"{m.group(1)}-{m.group(2)}" if m else "?"
    for line in out.splitlines():
        m = re.match(r"\s+(ALL|QB|RB|WR|TE)\s+([\d,]+)\s+([\d.]+)", line)
        if m:
            res[m.group(1)] = float(m.group(3))
            if m.group(1) == "ALL":
                res["n"] = int(m.group(2).replace(",", ""))
    return year, res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--update", action="store_true", help="save these results as the baseline")
    ap.add_argument("--note", default="", help="why the baseline changed (with --update)")
    args = ap.parse_args()

    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        now = dict(ex.map(lambda y: run(y, args.set), YEARS))
    if any("ALL" not in now[y] for y in YEARS):
        sys.exit("  backtest did not run -- see project.py output")

    base = json.load(open(BASE, encoding="utf-8")) if os.path.exists(BASE) else None
    label = " ".join(args.set) or "current code"
    print(f"\n  baseline guard: {label}")
    print(f"  {'':8}" + "".join(f"{p:>16}" for p in POS))
    for y in YEARS:
        cells = []
        for p in POS:
            b = base and base["seasons"].get(str(y), {}).get(p)
            d = f" ({now[y][p] - b:+.3f})" if b is not None else ""
            cells.append(f"{now[y][p]:.3f}{d}")
        print(f"  {y:<8}" + "".join(f"{c:>16}" for c in cells) + f"   wks {now[y]['weeks']}")

    if args.update:
        json.dump({"saved": datetime.datetime.now().isoformat(timespec="minutes"),
                   "note": args.note or label,
                   "seasons": {str(y): now[y] for y in YEARS}},
                  open(BASE, "w", encoding="utf-8"), indent=1)
        print(f"\n  baseline saved -> {os.path.basename(BASE)}\n")
        return
    if not base:
        sys.exit("\n  no baseline yet -- run with --update first\n")

    comparable = [y for y in YEARS if base["seasons"].get(str(y), {}).get("weeks") == now[y]["weeks"]]
    for y in YEARS:
        if y not in comparable:
            print(f"\n  {y}: new graded weeks ({base['seasons'][str(y)]['weeks']} -> {now[y]['weeks']})"
                  f" -- not comparable; re-baseline with --update once the code is settled")
    d = {y: now[y]["ALL"] - base["seasons"][str(y)]["ALL"] for y in comparable}
    net = sum(d.values())
    fails = []
    if net > EVEN / 2:
        fails.append(f"net {net:+.3f} over {', '.join(map(str, comparable))} (must not be worse)")
    if 2026 in d and d[2026] > EVEN:
        fails.append(f"2026 worse by {d[2026]:+.3f}")
    fails += [f"{y} clearly worse ({v:+.3f})" for y, v in d.items() if v >= CLEARLY_WORSE]
    verdict = "FAILS the rule" if fails else ("a NET GAIN -- passes" if net < -EVEN / 2 else "even -- passes")
    print(f"\n  net change (ALL, {len(comparable)} seasons): {net:+.3f}   -> {verdict}")
    for f in fails:
        print(f"    - {f}")
    print()
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
