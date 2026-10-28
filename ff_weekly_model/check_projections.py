#!/usr/bin/env python3
"""Known-case checks: fail loudly if an old bug comes back.

    python check_projections.py --year 2026 --week 7        # both parts
    python check_projections.py --year 2026 --week 7 --output-only

Built 2026-10-24. Two parts:

OUTPUT CHECKS -- run on this week's projections file before every lock.
Each is a bug we have actually shipped once:
  - a player on a bye-week team                        (wk5 CAR/KC, wk6 CIN/DET...)
  - a player Joe marked OUT still projected
  - a WR/TE handed real carries                        (wk6 Makai Lemon, 13 carries)
  - a team's lead back with every RB carry             (wk7 Bijan, 26.6 carries)
  - a team with no starting QB, or two                 (Winston/McCarthy wk7)
  - team pass attempts or RB carries outside any game ever played

REGRESSION TESTS -- the specific cases, on fixed 2026 history:
  - Dowdle wk6 (27% snaps, first game back) is NOT an injury exit
  - Saquon wk2 / wk4 (16% / 7%) still ARE
  - Jordan Mason wk7 (official Questionable, roster "RES", listed 4th, no
    wk6 snaps) is available
  - a stale roster file is caught by the freshness check
  - the new-team cut hits Sills (ATL -> TB) and not Jacobs (GB, exempt list)
  - Atlanta with one back gets an unnamed backup; Cook-style workhorses
    with a real backup do not
  - a team coming off a bye keeps its depth players (Miami wk7: the
    rotation check read "no snaps in wk6" for a team that did not play)

Exit code 1 if anything fails.
"""

import argparse
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)


def output_checks(year, week):
    """-> list of (ok, name, detail) on data/projections_<yr>_wk<NN>.csv."""
    import read_review
    res = []
    rows = list(csv.DictReader(open(os.path.join(DATA, f"projections_{year}_wk{week:02d}.csv"),
                                    encoding="utf-8")))
    num = lambda v: float(v or 0)
    games = [r for r in csv.DictReader(open(os.path.join(DATA, "games.csv"), encoding="utf-8"))
             if r["season"] == str(year) and r["week"] == str(week)]
    playing = {r["home_team"] for r in games} | {r["away_team"] for r in games}

    bye = [r["player"] for r in rows if r["team"] not in playing and num(r["half_ppr"]) > 0]
    res.append((not bye, "no bye-week players", ", ".join(bye[:5])))

    review, _ = read_review.load(year, week)
    outs = [r["player"] for r in rows if review.get(r["player_id"]) == 0.0 and num(r["half_ppr"]) > 0]
    res.append((not outs, "nobody marked OUT is projected", ", ".join(outs)))

    wr_car = [f"{r['player']} {num(r['rush_att']):.1f}" for r in rows
              if r["pos"] in ("WR", "TE") and num(r["rush_att"]) > 2.5]
    res.append((not wr_car, "no WR/TE with real carries (2.5+)", ", ".join(wr_car)))

    rb = collections.defaultdict(list)
    qb = collections.defaultdict(list)
    tm_att, tm_car = collections.defaultdict(float), collections.defaultdict(float)
    for r in rows:
        if r["pos"] == "RB":
            rb[r["team"]].append(num(r["rush_att"]))
            tm_car[r["team"]] += num(r["rush_att"])
        if r["pos"] == "QB":
            qb[r["team"]].append(num(r["pass_att"]))
            tm_att[r["team"]] += num(r["pass_att"])
    # the lead back against his TEAM's non-QB carries (team_volume file), which
    # include the unnamed backup's -- a lone back over 85% is the Bijan bug
    tvp = os.path.join(DATA, f"team_volume_{year}_wk{week:02d}.csv")
    team_rush = ({r["team"]: num(r["nonqb_rush"]) for r in csv.DictReader(open(tvp, encoding="utf-8"))}
                 if os.path.exists(tvp) else {})
    lone = [f"{t} ({max(c):.1f} of {team_rush[t]:.1f})" for t, c in rb.items()
            if t in team_rush and team_rush[t] and sum(1 for x in c if x >= 1.0) == 1
            and max(c) / team_rush[t] > 0.85]
    res.append((bool(team_rush) and not lone,
                "no lone back with every carry (one-back teams keep a backup's share)",
                ", ".join(lone) if team_rush else "no team_volume file -- re-run project.py"))

    qb_bad = []
    for t in playing:
        a = qb.get(t, [])
        tot = sum(a)
        starters = [x for x in a if tot and x / tot >= 0.5]
        if tot and len(starters) != 1 and max(a) / tot < 0.5:
            # a 50/50 start-chance hedge is allowed only when Joe set one
            qb_bad.append(f"{t} ({', '.join(f'{x:.0f}' for x in sorted(a, reverse=True)[:2])} att)")
        if not tot:
            qb_bad.append(f"{t} (no QB)")
    res.append((not qb_bad, "every team has one starting QB", ", ".join(qb_bad)))
    # ...and he takes the snaps: under 60% of his team's attempts only when Joe
    # set a QB start chance (2026-10-25: a blend for Puka "70 only" benched
    # Stafford in one of the two runs -- 18.9 became 5.1)
    qb_hedged = {r["team"] for r in rows if r["pos"] == "QB" and 0 < review.get(r["player_id"], 1.0) < 1}
    thin = [f"{t} ({max(a) / sum(a):.0%})" for t, a in qb.items()
            if sum(a) and t not in qb_hedged and max(a) / sum(a) < 0.6]
    res.append((not thin, "the starting QB takes 60%+ of his team's attempts (unless a start chance is set)",
                ", ".join(thin)))

    odd = [f"{t} {v:.0f} att" for t, v in tm_att.items() if not 20 <= v <= 50] + \
          [f"{t} {v:.0f} RB car" for t, v in tm_car.items() if not 10 <= v <= 38]
    res.append((not odd, "team pass attempts 20-50, RB carries 10-38", ", ".join(odd)))
    return res


def regression_tests(year=2026):
    """The fixed cases from 2026 -- valid whatever week it is now."""
    import availability
    import check_freshness
    import project as P
    res = []

    # Dowdle wk6: first game back, 27% of snaps -> kept; Saquon wk2/wk4 -> exits
    DOW, SAQ = "00-0036139", "00-0034844"
    back = P.first_games_back(year)
    res.append(((DOW, 6) in back, "Dowdle wk6 is recognised as a first game back", ""))
    tgt = {DOW: {1: .1, 2: .1, 6: .1}, SAQ: {1: .1, 2: .1, 3: .1, 4: .1}}
    car = {DOW: {1: .4, 2: .3, 6: .3}, SAQ: {1: .8, 2: .3, 3: .9, 4: .2}}
    snaps = {DOW: {1: .58, 2: .26, 6: .27}, SAQ: {1: .71, 2: .16, 3: .72, 4: .07}}
    conf = {(DOW, w) for w in (1, 2, 6)} | {(SAQ, w) for w in (1, 2, 3, 4)}
    P.drop_exit_weeks(tgt, car, snaps, positions={DOW: "RB", SAQ: "RB"}, confirmed=conf,
                      returning={(DOW, 6)})
    res.append((6 in car[DOW], "Dowdle wk6 is NOT flagged as an injury exit", ""))
    res.append((2 not in car[DOW], "Dowdle wk2 (left hurt) IS flagged as an exit", ""))
    res.append((2 not in car[SAQ] and 4 not in car[SAQ], "Saquon wk2 / wk4 ARE flagged as exits", ""))
    # EXIT_KEEP_W (2026-10-28): a flagged exit stays -- a back's in full, a
    # receiver's as half a game (Joe: "for WR/TE count the partial game as half")
    JJ = "00-0036322"
    tgt2, car2 = {SAQ: {1: .1, 2: .1}, JJ: {1: .3, 3: .08}}, {SAQ: {1: .8, 2: .3}, JJ: {1: 0.0, 3: 0.0}}
    ew = P.keep_exit_games(tgt2, car2, {(SAQ, 2), (JJ, 3)}, {SAQ: "RB", JJ: "WR"})
    res.append((2 in car2[SAQ] and SAQ not in ew, "a back's exit game counts in full (Saquon wk2)", ""))
    res.append((3 in tgt2[JJ] and ew.get(JJ, {}).get(3) == 0.5,
                "a receiver's exit game counts as half a game (Jefferson wk3)", ""))

    # Mason wk7: official Questionable + roster RES + listed 4th + no wk6 snaps
    MASON, JONES, DALLAS, CLAIB = "00-0037525", "00-0033293", "00-0036425", "00-0041104"
    cands = {MASON: "MIN", JONES: "MIN", DALLAS: "MIN", CLAIB: "MIN"}
    m, why = availability.build(year, 7, candidates=cands,
                                depth_rank={JONES: 1, DALLAS: 2, CLAIB: 3, MASON: 4},
                                positions={p: "RB" for p in cands})
    res.append((m.get(MASON) == 1.0, "Jordan Mason wk7 (Questionable, off IR) is available",
                why.get(MASON, "")))

    # a team coming off a BYE: its depth players are judged on its own last
    # game (wk5), not the league's last week -- Kevin Coleman Jr. MIA wk7
    KCJ, MWASH = "00-0040991", "00-0039880"
    import project as P_
    ids_ = {r["player_display_name"]: r["player_id"] for r in P_.load_players(year)}
    KCJ = ids_.get("Kevin Coleman Jr.", KCJ)
    cands = {KCJ: "MIA", MWASH: "MIA", ids_.get("Caleb Douglas", "x1"): "MIA", ids_.get("Chris Bell", "x2"): "MIA"}
    m, why = availability.build(year, 7, candidates=cands,
                                depth_rank={MWASH: 1, ids_.get("Caleb Douglas", "x1"): 2,
                                            ids_.get("Chris Bell", "x2"): 3, KCJ: 4},
                                positions={p: "WR" for p in cands})
    res.append((m.get(KCJ) == 1.0, "a team off a bye keeps its depth players (Kevin Coleman Jr. MIA wk7)",
                why.get(KCJ, "")))

    # the stale roster file is caught
    rpath = os.path.join(DATA, f"roster_{year}.csv")
    bak = rpath + ".bak_check"
    import shutil
    shutil.copy(rpath, bak)
    try:
        with open(bak, newline="", encoding="utf-8") as fh:
            old = [r for r in csv.DictReader(fh) if r.get("week") in ("1", "2")]
        with open(rpath, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(old[0].keys()))
            w.writeheader()
            w.writerows(old)
        caught = any(lv == "STALE" and nm == "weekly rosters" for lv, nm, _ in check_freshness.check(year, 7))
    finally:
        shutil.move(bak, rpath)
    res.append((caught, "a week-2 roster file is flagged STALE", ""))

    # new team: Sills (ATL -> TB) yes, Jacobs (GB, exempt list) no
    P._PREV_TEAM = P.prev_team_map(P.load_players(year - 1))
    SILLS, JACOBS = "00-0035359", "00-0035700"
    res.append((P.new_team_no_games(SILLS, "TB", False, 6), "new-team cut applies to Sills (ATL -> TB)", ""))
    res.append((not P.new_team_no_games(JACOBS, "GB", False, 6), "new-team cut does NOT apply to Jacobs (GB)", ""))

    # one-back guard
    res.append((P.rb_backup_need([0.9]) > 0, "a team with one back gets an unnamed backup", ""))
    res.append((P.rb_backup_need([0.8, 0.05]) == 0, "a workhorse with a real (small) backup is left alone", ""))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--output-only", action="store_true", help="skip the regression tests")
    args = ap.parse_args()
    res = output_checks(args.year, args.week)
    if not args.output_only:
        res += regression_tests()
    print(f"\n  known-case checks, {args.year} week {args.week}")
    for ok, name, detail in res:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"   <- {detail}" if detail and not ok else ""))
    bad = [r for r in res if not r[0]]
    if bad:
        print(f"\n  STOP: {len(bad)} check(s) failed.\n")
        sys.exit(1)
    print(f"\n  all {len(res)} passed\n")


if __name__ == "__main__":
    main()
