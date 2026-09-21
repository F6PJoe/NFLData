#!/usr/bin/env python3
"""
Refresh one or more site columns in combined_adp.csv from their cached
per-source CSVs (matched by normalise_name), then recompute Consensus over
SITE_COLS using the same outlier-detection logic as run_all.merge().

Usage:
    python refresh_sources.py Sleeper:sleeper_adp.csv [Underdog:underdog_adp.csv ...]
"""

import csv
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "ff_adp"))

from run_all import normalise_name, load_csv, OUTPUT_COLS, SITE_COLS
COMBINED = BASE / "combined_adp.csv"


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python refresh_sources.py Label:csv_file [Label:csv_file ...]")

    refreshes = []
    for arg in sys.argv[1:]:
        label, csv_file = arg.split(":", 1)
        refreshes.append((label, csv_file))

    master = {}
    order = []
    with open(COMBINED, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            key = normalise_name(row['Player'])
            master[key] = row
            order.append(key)

    for label, csv_file in refreshes:
        source = load_csv(str(BASE / "ff_adp" / csv_file), label)
        updated = 0
        unmatched = 0
        for key, row in source.items():
            if key in master:
                master[key][label] = row[label]
                updated += 1
            else:
                unmatched += 1
        print(f"  {label}: updated {updated} players ({unmatched} from {csv_file} had no match)")

    for key in order:
        row = master[key]
        site_vals = {}
        for c in SITE_COLS:
            raw = row.get(c, 999)
            try:
                v = float(raw)
            except (TypeError, ValueError):
                v = 999
            if v != 999:
                site_vals[c] = v

        if len(site_vals) >= 2:
            all_v = sorted(site_vals.values())
            mid = len(all_v) // 2
            median = (all_v[mid - 1] + all_v[mid]) / 2 if len(all_v) % 2 == 0 else all_v[mid]
            cleaned = {}
            for c, v in site_vals.items():
                others = [x for k, x in site_vals.items() if k != c]
                if others:
                    other_median = sorted(others)[len(others) // 2]
                    if other_median > 0 and v / other_median > 4:
                        continue
                cleaned[c] = v
            site_vals = cleaned

        for c in SITE_COLS:
            if c not in row or row.get(c, '') == '':
                row[c] = 999
            elif c in site_vals:
                row[c] = round(site_vals[c], 1)
            else:
                row[c] = 999

        real_vals = list(site_vals.values())
        row['Consensus'] = round(sum(real_vals) / len(real_vals), 1) if real_vals else ''

    rows = [master[key] for key in order]
    rows.sort(key=lambda r: r['Consensus'] if r['Consensus'] != '' else 9999)

    with open(COMBINED, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in OUTPUT_COLS})

    print(f"Wrote {len(rows)} rows to {COMBINED}")


if __name__ == "__main__":
    main()
