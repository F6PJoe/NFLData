"""Does the PLAY-CALLER's pass tendency predict a team's next-season pass rate better than the team's own?

Joe 2026-11-08: "with coaches that change teams, we use some sort of blend between past years pass
rate and the coaches pass rates from other teams, as long as the same QB is there and they didn't
bring in some superstar RB". Play-callers: playcallers.csv (2016-26; opening caller + mid-season
changes with from_week; rows noted UNVERIFIED are unconfirmed).

Per team-WEEK from nflverse play-by-play (regular season, plays with an xpass value):
  pass rate  share of plays that were passes (dropbacks incl. scrambles / sacks)
  PROE       pass rate minus nflverse's expected pass rate (down, distance, score, time)
Each week is credited to whoever called plays that week. Test unit = a team-season's OPENING caller,
scored on the weeks he called. Predicting it from the season before:
  team      team's last-season pass rate (what the model's prior leans on)
  caller    team's last rate + (caller's PROE in his most recent season with 8+ games called, any team
            - team's last-season PROE) -- differs only when the caller is new to the team
Blends shown at caller weight 0 / .25 / .5 / .75 / 1; and the model-style prior w x team + (1-w) x league.

    python research/playcaller_proe.py [--verified-only]
"""
import argparse, csv, collections, os, statistics as st
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PBP = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
FIX = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LA"}
YEARS = range(2016, 2027)


def team_weeks(years):
    """(season, team, week) -> [plays, passes, xpass, Counter(passer)]"""
    out = {}
    for y in years:
        p = os.path.join(PBP, f"pbp_{y}.csv")
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["season_type"] != "REG" or not r["xpass"] or not r["posteam"]:
                    continue
                if r["qb_kneel"] == "1" or r["qb_spike"] == "1" or r["two_point_attempt"] == "1" or r["pass"] not in ("0", "1"):
                    continue
                k = (y, FIX.get(r["posteam"], r["posteam"]), int(r["week"]))
                a = out.setdefault(k, [0, 0.0, 0.0, collections.Counter()])
                a[0] += 1; a[1] += float(r["pass"]); a[2] += float(r["xpass"])
                if r["passer_player_id"]:
                    a[3][r["passer_player_id"]] += 1
    return out


def agg(cells):
    n = sum(c[0] for c in cells)
    if not n:
        return None
    q = collections.Counter()
    for c in cells:
        q.update(c[3])
    return {"n": n, "g": len(cells), "rate": sum(c[1] for c in cells) / n,
            "proe": (sum(c[1] for c in cells) - sum(c[2] for c in cells)) / n, "qb": q.most_common(1)[0][0] if q else ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verified-only", action="store_true")
    a = ap.parse_args()
    calls = collections.defaultdict(list)          # (season, team) -> [(from_week, caller, unverified)]
    for r in csv.DictReader(open(os.path.join(HERE, "playcallers.csv"), encoding="utf-8")):
        calls[(int(r["season"]), r["team"])].append((int(r["from_week"] or 1), r["playcaller"], "UNVERIFIED" in r["note"]))
    for v in calls.values():
        v.sort()
    def caller_at(y, tm, wk):
        c = None
        for fw, name, _ in calls.get((y, tm), []):
            if fw <= wk:
                c = name
        return c
    tw = team_weeks(YEARS)
    by_team = collections.defaultdict(list); by_caller = collections.defaultdict(list); opener_cells = collections.defaultdict(list)
    for (y, tm, wk), c in tw.items():
        by_team[(y, tm)].append(c)
        cl = caller_at(y, tm, wk)
        if cl:
            by_caller[(cl, y)].append(c)
            if calls[(y, tm)][0][1] == cl:
                opener_cells[(y, tm)].append(c)
    team = {k: agg(v) for k, v in by_team.items()}
    caller = {k: agg(v) for k, v in by_caller.items()}
    lg = {y: st.mean(v["rate"] for (yy, _), v in team.items() if yy == y) for y in YEARS if any(k[0] == y for k in team)}
    def main_caller(y, tm):
        cnt = collections.Counter(caller_at(y, tm, wk) for (yy, t, wk) in tw if yy == y and t == tm)
        return cnt.most_common(1)[0][0] if cnt else None
    rows = []
    for (y, tm), opens in calls.items():
        if (y - 1, tm) not in team or (y, tm) not in opener_cells:
            continue
        cl = opens[0][1]; unver = opens[0][2]
        if a.verified_only and unver:
            continue
        cur = agg(opener_cells[(y, tm)]); last = team[(y - 1, tm)]
        if cur["g"] < 4:
            continue
        changed = cl != main_caller(y - 1, tm)
        hist = next((caller[(cl, yy)] for yy in range(y - 1, y - 4, -1) if (cl, yy) in caller and caller[(cl, yy)]["g"] >= 8), None)
        cal = last["rate"] + (hist["proe"] - last["proe"]) if (changed and hist) else last["rate"]
        rows.append(dict(y=y, tm=tm, cl=cl, changed=changed, hist=hist is not None, qb_same=cur["qb"] == last["qb"],
                         actual=cur["rate"], team=last["rate"], cal=cal, lg=lg[y - 1],
                         proe=cur["proe"], last_proe=last["proe"], hist_proe=hist["proe"] if hist else None))
    mae = lambda g, f: 100 * st.mean(abs(r["actual"] - f(r)) for r in g)
    G = {"ALL": rows,
         "caller NEW to team, has history": [r for r in rows if r["changed"] and r["hist"]],
         "  ... same starting QB": [r for r in rows if r["changed"] and r["hist"] and r["qb_same"]],
         "  ... new starting QB": [r for r in rows if r["changed"] and r["hist"] and not r["qb_same"]],
         "caller new, first-time caller": [r for r in rows if r["changed"] and not r["hist"]],
         "same caller": [r for r in rows if not r["changed"]]}
    print(f"seasons {min(r['y'] for r in rows)}-{max(r['y'] for r in rows)}{' (verified rows only)' if a.verified_only else ''}")
    print("A) team's last pass rate shifted toward the caller's PROE (mean abs error, pass-rate pts)")
    print(f"{'':36}{'n':>4}   caller wt 0    .25     .5    .75      1")
    for k, g in G.items():
        if g:
            print(f"{k:36}{len(g):>4}   " + "  ".join(f"{mae(g, lambda r, w=w: r['team'] + w * (r['cal'] - r['team'])):6.2f}"
                                                   for w in (0, .25, .5, .75, 1)))
    print("\nB) model-style prior: w x team last + (1-w) x league last, w =  0 / .25 / .5 / .75 / 1")
    for k, g in G.items():
        if g:
            print(f"{k:36}{len(g):>4}   " + "  ".join(f"{mae(g, lambda r, w=w: w * r['team'] + (1 - w) * r['lg']):6.2f}"
                                                   for w in (0, .25, .5, .75, 1)))
    print("\nC) model-style 50/50 prior + caller shift at weight s (s = 0 / .25 / .5 / .75 / 1)")
    for k, g in G.items():
        if g:
            print(f"{k:36}{len(g):>4}   " + "  ".join(f"{mae(g, lambda r, s=s: .5 * r['team'] + .5 * r['lg'] + s * (r['cal'] - r['team'])):6.2f}"
                                                   for s in (0, .25, .5, .75, 1)))
    g = G["caller NEW to team, has history"]
    print("\nPROE year to year:")
    s = G["same caller"]
    print(f"  same caller                       n={len(s):3}  r={st.correlation([r['last_proe'] for r in s], [r['proe'] for r in s]):.2f}")
    print(f"  new caller: team's last PROE      n={len(g):3}  r={st.correlation([r['last_proe'] for r in g], [r['proe'] for r in g]):.2f}")
    print(f"  new caller: CALLER's last PROE    n={len(g):3}  r={st.correlation([r['hist_proe'] for r in g], [r['proe'] for r in g]):.2f}")
    for lab, sub in (("same QB", [r for r in g if r["qb_same"]]), ("new QB", [r for r in g if not r["qb_same"]])):
        if len(sub) > 3:
            print(f"    {lab:8} n={len(sub):3}  team r={st.correlation([r['last_proe'] for r in sub], [r['proe'] for r in sub]):.2f}"
                  f"  caller r={st.correlation([r['hist_proe'] for r in sub], [r['proe'] for r in sub]):.2f}")


if __name__ == "__main__":
    main()
