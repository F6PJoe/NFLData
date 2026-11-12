#!/usr/bin/env python3
"""The week's projections as the three site rankings files (Half PPR, PPR, Standard).

    python site_rankings_export.py --year 2026 --week 10

Joe 2026-11-12: "I want to run it and have it output the rankings file like the normal run does."
rerun.py and lock.py call this at the end, so every run leaves fresh files in
site_rankings/<yr>-wk<NN>/NFL_<yr>_Week_<N>_{Half_PPR,PPR,Standard}_Weekly_Rankings.csv
(kept apart from ff_rankings/weekly/, Joe's own rankings run). Ranks data/projections_<yr>_wk<NN>.csv
by position (QB, RB, WR, TE, Flex); PPR adds half a point per projected catch, Standard takes it
off. The model has no kickers or defenses: those two lists are FantasyPros' consensus order.
Uses ff_rankings' own writer, so player IDs, names, opponents and kickoff times match Joe's files.
"""
import argparse, csv, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
RK = os.path.join(os.path.dirname(HERE), "ff_rankings")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    a = ap.parse_args()
    Y, W = a.year, a.week
    os.chdir(RK); sys.path.insert(0, RK)
    import requests, site_exports as se, weekly_freshness as wf
    out = os.path.join(HERE, "site_rankings", f"{Y}-wk{W:02d}")
    os.makedirs(out, exist_ok=True)
    rows = list(csv.DictReader(open(os.path.join(HERE, "data", f"projections_{Y}_wk{W:02d}.csv"), encoding="utf-8")))
    f = lambda v: float(v or 0)
    pts = lambda r, s: f(r["half_ppr"]) + {"HALF": 0, "PPR": .5, "STD": -.5}[s] * f(r["rec"])

    def write(name, recs):
        with open(os.path.join(out, name), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["Rank", "Player", "Team", "Position", "Points"])
            for i, (r, p) in enumerate(recs, 1):
                w.writerow([i, r[0], r[1], r[2], f"{p:.2f}"])
    for s, suf in (("HALF", ""), ("PPR", "_ppr"), ("STD", "_std")):
        for slot, poss in (("QB", {"QB"}), ("RB", {"RB"}), ("WR", {"WR"}), ("TE", {"TE"}), ("FLX", {"RB", "WR", "TE"})):
            if slot == "QB" and s != "HALF":
                continue
            recs = [((r["player"], r["team"], r["pos"]), pts(r, s)) for r in rows if r["pos"] in poss and pts(r, s) > 0.05]
            recs.sort(key=lambda x: (-x[1], x[0]))
            write(f"consensus_{slot.lower()}{suf}.csv", recs)
    sess = requests.Session()
    for slot in ("K", "DST"):
        fp = wf.fetch_consensus_list(slot, Y, W, session=sess)
        write(f"consensus_{slot.lower()}.csv", [((p["player_name"], p["player_team_id"], slot), 0.0) for p in fp])
    json.dump({"year": str(Y), "week": str(W), "phase": "F6P MODEL"}, open(os.path.join(out, "manifest.json"), "w"))
    missing = se.write_exports(out, ["HALF", "PPR", "STD"], session=sess)
    if missing:
        print("  no FantasyPros ID: " + ", ".join(f"{m['name']} ({m['team']} {m['list']} #{m['rank']})" for m in missing))
    print(f"  rankings files -> {out}")


if __name__ == "__main__":
    main()
