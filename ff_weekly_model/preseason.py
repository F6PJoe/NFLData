"""Preseason projections as a starting point (2026-10-13, Joe: "we had
consensus projections, ranks, depth chart data available to us just like
they did").

The early-season gap to the sites -- ESPN beat us at WR in wks 2-4 of 2024
and 2025, and elite WRs run low every September -- is preseason knowledge:
talent, new roles, team changes, rookies. Last season's usage is a weak
stand-in for all of it.

Sources, per season (season-long stat lines, taken before week 1):
  2024, 2025  ESPN's preseason projections (data/espn_hist/espn_<yr>.json,
              statSourceId 1 / statSplitTypeId 0). Checked preseason: CMC
              2024 335 pts, Nabers 2025 301 -- injuries never cut them.
  2026+       Joe's draft-tool consensus, ff_draft_proj/consensus_<pos>.csv
              (11 sources, saved Sept 6, the day before kickoff), frozen as
              data/preseason_<yr>/. Copy next year's in before week 1.

load(year, names, pos) -> pid -> {"tgt", "car", "rec", "rec_yds"} season totals.
"""

import csv
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}


def norm(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s.lower())
    return re.sub(r"[^a-z]", "", s)


def _espn(year):
    path = os.path.join(HERE, "data", "espn_hist", f"espn_{year}.json")
    if not os.path.exists(path):
        return []
    out = []
    for p in json.load(open(path, encoding="utf-8"))["players"]:
        pl = p["player"]
        po = ESPN_POS.get(pl.get("defaultPositionId"))
        if not po:
            continue
        for s in pl.get("stats", []):
            if (s.get("seasonId") == year and s.get("statSourceId") == 1
                    and s.get("statSplitTypeId") == 0):
                st = s.get("stats", {})
                out.append((pl["fullName"], po, {
                    "tgt": st.get("58", 0.0), "car": st.get("23", 0.0),
                    "rec": st.get("53", 0.0), "rec_yds": st.get("42", 0.0)}))
                break
    return out


def _consensus(year):
    # a FROZEN copy (data/preseason_<yr>/) -- the draft tool's own files can be
    # re-pulled in-season and would stop being preseason
    base = os.path.join(HERE, "data", f"preseason_{year}")
    out = []
    for po in ("QB", "RB", "WR", "TE"):
        path = os.path.join(base, f"consensus_{po.lower()}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                f = lambda k: float(r.get(k) or 0)
                out.append((r[po], po, {"tgt": f("Targets"), "car": f("Rush Att"),
                                        "rec": f("Rec"), "rec_yds": f("Rec Yds")}))
    return out


def load(year, names, pos):
    """names: pid -> display name; pos: pid -> position (players we know)."""
    rows = _espn(year) if year <= 2025 else _consensus(year)
    by_key = {}
    for pid, nm in names.items():
        by_key.setdefault((norm(nm), pos.get(pid)), []).append(pid)
    out = {}
    for nm, po, v in rows:
        hit = by_key.get((norm(nm), po))
        if hit and len(hit) == 1:
            out[hit[0]] = v
    return out
