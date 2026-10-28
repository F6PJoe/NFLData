#!/usr/bin/env python3
"""Gap report: the handful of players where we disagree with BOTH the
consensus and ETR -- and the reason, in football terms.

    python gap_report.py --year 2026 --week 7

Built 2026-10-24. Saquon, Dowdle, David Sills and Aaron Jones were all
found by reading our numbers against ETR and the consensus by eye; each one
turned out to be a model or data problem (team pass rate from games without
Saquon, Dowdle's week 6 thrown out, Sills keeping his old team's share,
Mason removed by a stale roster file). This lists every player projected
5+ by anyone where we are GAP+ points away from the consensus AND from ETR
(same direction), with his stat line against the consensus line and his
team's volume, so the question "why are we different" starts answered.

Writes data/gap_report_<yr>_wk<NN>.csv and prints the list. A gap is not a
bug -- it is where a bug would show up first.
"""

import argparse
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import audit_vs_sources as A   # noqa: E402

GAP = 3.0
MIN_PTS = 5.0
STATS = {"QB": [("pass_att", "Pass Att", "att"), ("pass_yds", "Pass Yds", "pass yds"),
                ("pass_td", "Pass TD", "pass TD"), ("rush_att", "Rush Att", "car"),
                ("rush_yds", "Rush Yds", "rush yds")],
         "SKILL": [("rush_att", "Rush Att", "car"), ("rush_yds", "Rush Yds", "rush yds"),
                   ("rush_td", "Rush TD", "rush TD"), ("targets", "Targets", "tgt"),
                   ("rec_yds", "Rec Yds", "rec yds"), ("rec_td", "Rec TD", "rec TD")]}
TOL = {"att": 2.0, "pass yds": 15, "pass TD": 0.2, "car": 1.5, "rush yds": 8,
       "rush TD": 0.12, "tgt": 1.0, "rec yds": 8, "rec TD": 0.12}


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--gap", type=float, default=GAP)
    args = ap.parse_args()

    ours = list(csv.DictReader(open(os.path.join(DATA, f"projections_{args.year}_wk{args.week:02d}.csv"),
                                    encoding="utf-8")))
    directory, _ = A.resolve_dir(args.year, args.week)
    cons = {}
    for p in ("qb", "rb", "wr", "te"):
        path = os.path.join(directory, f"consensus_{p}.csv")
        if os.path.exists(path):
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                cons[A.norm(r[p.upper()])] = r
    etr = {}
    etr_path = os.path.join(directory, "etr.csv")
    if os.path.exists(etr_path):
        for r in csv.DictReader(open(etr_path, encoding="utf-8-sig")):
            etr[A.norm(r["Player"])] = f(r["Half PPR Proj"])
    sheet = {}
    sp = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    if os.path.exists(sp):
        for r in csv.DictReader(open(sp, encoding="utf-8-sig")):
            if r.get("decision"):
                sheet[r["player_id"]] = r["decision"]

    # team volume, ours vs the consensus lines summed
    tv = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # our tgt, cons tgt, our car, cons car
    for r in ours:
        if r["pos"] in ("RB", "WR", "TE"):
            c = cons.get(A.norm(r["player"]), {})
            tv[r["team"]][0] += f(r["targets"]); tv[r["team"]][1] += f(c.get("Targets"))
            tv[r["team"]][2] += f(r["rush_att"]); tv[r["team"]][3] += f(c.get("Rush Att"))

    # games already under way are locked -- nothing left to fix there
    import datetime
    import score_week
    started = {tm for tm, ko in score_week.kickoffs(args.year, args.week).items()
               if ko <= datetime.datetime.now()}
    out = []
    for r in ours:
        if r["team"] in started:
            continue
        k = A.norm(r["player"])
        o, cn = f(r["half_ppr"]), f(r["consensus"]) if r["consensus"] else None
        e = etr.get(k)
        if cn is None or max(o, cn, e or 0) < MIN_PTS:
            continue
        dc = o - cn
        de = (o - e) if e is not None else None
        if abs(dc) < args.gap or (de is not None and (abs(de) < args.gap or (de > 0) != (dc > 0))):
            continue
        c = cons.get(k, {})
        bits = []
        for col, ccol, lab in STATS["QB" if r["pos"] == "QB" else "SKILL"]:
            a, b = f(r[col]), f(c.get(ccol))
            if abs(a - b) >= TOL[lab]:
                bits.append(f"{lab} {a:.1f} vs {b:.1f}" if lab not in ("pass TD", "rush TD", "rec TD")
                            else f"{lab} {a:.2f} vs {b:.2f}")
        t = tv.get(r["team"])
        if t and r["pos"] != "QB":
            if abs(t[0] - t[1]) >= 2:
                bits.append(f"team targets {t[0]:.0f} vs {t[1]:.0f}")
            if r["pos"] == "RB" and abs(t[2] - t[3]) >= 2:
                bits.append(f"team carries {t[2]:.0f} vs {t[3]:.0f}")
        if r["player_id"] in sheet:
            bits.append(f"your call: {sheet[r['player_id']]}")
        out.append({"player": r["player"], "team": r["team"], "pos": r["pos"], "ours": round(o, 1),
                    "consensus": round(cn, 1), "etr": "" if e is None else round(e, 1),
                    "gap": round(dc, 1), "why (ours vs consensus)": "; ".join(bits) or "efficiency / TD rate"})
    out.sort(key=lambda x: -abs(x["gap"]))
    dest = os.path.join(DATA, f"gap_report_{args.year}_wk{args.week:02d}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["player", "team", "pos", "ours", "consensus", "etr", "gap",
                                           "why (ours vs consensus)"])
        w.writeheader()
        w.writerows(out)
    print(f"\n  gap report, week {args.week}: {len(out)} players {args.gap:g}+ pts from the consensus"
          + (" AND ETR" if etr else " (no ETR file this week)") + f" -> {os.path.basename(dest)}\n")
    for x in out:
        print(f"  {x['player']:22}{x['team']:4}{x['pos']:3} ours {x['ours']:5.1f}  cons {x['consensus']:5.1f}"
              f"  ETR {x['etr'] if x['etr'] != '' else '-':>5}   {x['why (ours vs consensus)']}")
    print()


if __name__ == "__main__":
    main()
