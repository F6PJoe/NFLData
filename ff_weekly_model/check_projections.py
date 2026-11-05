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
    # ...and its route % is not his role (2026-10-31): Jefferson wk3 (6% of routes)
    # is skipped in the route model and as the route anchor; wk5 (played hurt)
    # is skipped in the route model only
    saved_ = (P._EXITS, P._INJ_LIMITED)
    P._EXITS, P._INJ_LIMITED = {(JJ, 3)}, {(JJ, 5)}
    rm_ = P.route_model_weeks(JJ, [1, 2, 3, 5, 7])
    lead_ = P.route_lead_weeks(JJ, {1: .4, 2: .3, 3: .08}, {1: 1.0, 2: 1.0, 3: .06}, 5)
    # ...nor once a FULL call has taken it off the exit list (Jefferson wk8 FULL)
    P._EXITS, P._FULL_LEFT = set(), {(JJ, 3)}
    rm2_ = P.route_model_weeks(JJ, [1, 2, 3, 5, 7])
    lead2_ = P.route_lead_weeks(JJ, {1: .4, 2: .3, 3: .08}, {1: 1.0, 2: 1.0, 3: .06}, 5)
    P._EXITS, P._INJ_LIMITED = saved_
    P._FULL_LEFT = set()
    res.append((rm_ == [1, 2, 7] and lead_ == [1, 2],
                "a game he left hurt is not his route rate (Jefferson wk3)", f"{rm_} {lead_}"))
    res.append((rm2_ == [1, 2, 7] and lead2_ == [1, 2],
                "...nor after a FULL call counts its healthy part (Jefferson wk8)", f"{rm2_} {lead2_}"))
    # FULL measures "usual" by his best game THIS season (2026-10-29): McConkey's
    # short wk1/wk2 count as hurt even with no earlier game to compare against
    ladd = {1: .49, 2: .46, 3: .88, 4: .34, 6: .12}
    got = P.full_dropped_weeks(ladd, 8)
    res.append((got == [1, 2, 4, 6], "FULL finds McConkey's short games (wks 1, 2, 4, 6)", str(got)))
    # ...and splits them (2026-10-29): left hurt -> counted as his healthy part
    # (wk1, wk6); listed Questionable going in -> dropped (wk2, wk4)
    L = "00-0039915"
    drop_, left_ = P.full_plan(L, ladd, 8, {(L, 1), (L, 6)}, {(L, 2), (L, 4)})
    res.append((drop_ == [2, 4] and left_ == [1, 6],
                "FULL: McConkey wks 1, 6 count as healthy part; 2, 4 dropped", f"{drop_} {left_}"))
    # WH_RETURN (2026-10-30): a proven workhorse gets his role back unless his
    # fill-in outscored him (Tracy over Singletary) or he was out 7+ games
    JAC, LLO = "00-0035700", "00-0039811"
    saved = (P._WH_PREV, P._WH_WEEK, P._WH_TEAM_RB)
    P._WH_PREV = {JAC: (0.73, 14.6, 15, 0.67)}
    P._WH_TEAM_RB = {("GB", w): 20.0 for w in range(1, 8)}
    P._WH_WEEK = {JAC: {7: ("GB", 11.0, 17.6)},
                  LLO: {w: ("GB", 9.0, 6.2) for w in range(1, 8)}}
    got = P.workhorse_return(JAC, "GB", {7}, list(range(1, 8)))
    res.append((bool(got) and got[0] == set(range(1, 7)),
                "Jacobs wk8: a workhorse back, his backup did not take the job", str(got)))
    P._WH_WEEK[LLO] = {w: ("GB", 15.0, 16.6) for w in range(1, 8)}
    got = P.workhorse_return(JAC, "GB", {7}, list(range(1, 8)))
    res.append((got is None, "...not when the backup outscored him (Tracy over Singletary)", str(got)))
    # ...unless Joe says FULL on the sheet; SPLIT turns a workhorse return off
    P._WH_FORCE = {JAC: "FULL"}
    got = P.workhorse_return(JAC, "GB", {7}, list(range(1, 8)))
    res.append((bool(got), "...FULL on the sheet forces it anyway", str(got)))
    P._WH_WEEK[LLO] = {w: ("GB", 9.0, 6.2) for w in range(1, 8)}
    P._WH_FORCE = {JAC: "SPLIT"}
    got = P.workhorse_return(JAC, "GB", {7}, list(range(1, 8)))
    import read_review
    res.append((got is None and read_review.parse_decision("split")[1].startswith("SPLIT"),
                "...and SPLIT on the sheet turns it off", str(got)))
    P._WH_FORCE = {}
    P._WH_WEEK[LLO] = {w: ("GB", 9.0, 6.2) for w in range(1, 11)}
    P._WH_TEAM_RB.update({("GB", w): 20.0 for w in range(8, 11)})
    P._WH_WEEK[JAC] = {10: ("GB", 11.0, 17.6)}
    got = P.workhorse_return(JAC, "GB", {10}, list(range(1, 11)))
    res.append((got is None, "...nor after a 7+ game absence (Pacheco 2024, broken leg)", str(got)))
    P._WH_PREV, P._WH_WEEK, P._WH_TEAM_RB = saved

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

    # ...and an injury returner off a bye: Out on his team's LAST report, not
    # week-1's (Tre Harris LAC wk8: Out wk6, bye wk7, no snaps in wk6)
    HARRIS = "00-0040727"
    LADD, QJ = ids_.get("Ladd McConkey", "x3"), ids_.get("Quentin Johnston", "x4")
    cands = {HARRIS: "LAC", LADD: "LAC", QJ: "LAC"}
    m, why = availability.build(year, 8, candidates=cands, depth_rank={LADD: 1, QJ: 2, HARRIS: 3},
                                positions={p: "WR" for p in cands})
    res.append((m.get(HARRIS) == 1.0, "an injury returner off a bye is available (Tre Harris LAC wk8)",
                why.get(HARRIS, "")))

    # ...and a player designated to return from IR with NO game designation
    # plays, even with Sleeper still tagging IR (Jadarian Price SEA wk8)
    PRICE = "00-0041512"
    m, why = availability.build(year, 8, candidates={PRICE: "SEA"}, positions={PRICE: "RB"})
    res.append((m.get(PRICE) == 1.0, "an undesignated IR returner plays (Jadarian Price SEA wk8)",
                why.get(PRICE, "")))

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

    # ROLES from the review workbook (2026-10-31): Price RB2 / Wilson RB3 swap
    # their slots' work, everyone else stays put
    rm_ = P.role_multipliers({"Ch": 12.9, "Wi": 9.1, "Pr": 5.6, "Ho": 4.1, "Ru": 0.2},
                             {"Pr": 2, "Wi": 3})
    res.append((abs(rm_["Pr"] - 9.1 / 5.6) < 1e-9 and abs(rm_["Wi"] - 5.6 / 9.1) < 1e-9
                and rm_["Ch"] == rm_["Ho"] == rm_["Ru"] == 1.0
                and read_review.parse_role("rb 2") == ("RB", 2),
                "a role takes that slot's work; the rest of the group shifts (Price RB2)", str(rm_)))
    # ROLE_NORMAL (2026-10-31): a starter taking his job back gets his own
    # normal usage (McConkey WR1, 6.3 when healthy, over the Chargers' 4.5); a
    # backup moved up takes the slot's work (Boston); a player moved down takes
    # the slot's work, not his old normal (Dobbins RB2)
    lac_ = {"Jo": 4.5, "Ha": 4.4, "Mc": 3.9, "La": 3.1}
    rw_ = P.role_work(lac_, {"Mc": 1}, {"Mc": 6.3})
    cle_ = P.role_work({"Co": 5.7, "Bo": 5.3}, {"Bo": 1}, {"Bo": 3.0})
    # (Dobbins has no game with Coleman ahead of him, so no workload of his own)
    den_ = P.role_work({"Do": 12.9, "Cl": 9.1}, {"Cl": 1, "Do": 2}, {"Cl": 6.0})
    # ...never more than the player placed above him (Price RB2 under Charbonnet);
    # a player left in his own slot is unchanged (Shakir WR2)
    sea_ = P.role_work({"Ch": 12.9, "Wi": 9.1, "Pr": 5.6}, {"Pr": 2}, {"Pr": 16.3})
    # ROLE_NORMAL_DOWN: the fill-in moved back down gets his workload from games
    # with the starter ahead of him, not the slot's -- and moving down never
    # raises him (Johnston under McConkey wk8: 2025 games said 7.0, he is at 4.5)
    dn_ = P.role_work({"Fi": 7.0, "Ot": 4.0, "St": 3.0}, {"St": 1, "Fi": 2}, {"St": 6.5, "Fi": 5.0})
    dn2_ = P.role_work(lac_, {"Mc": 1, "Jo": 2}, {"Mc": 6.3, "Jo": 7.0})
    res.append((dn_ == {"St": 7.0, "Fi": 5.0, "Ot": 3.0} and dn2_["Jo"] == 4.5 and dn2_["Mc"] == 6.3,
                "...the fill-in moved back down gets his workload from games with the starter, never more",
                f"{dn_} {dn2_}"))
    buf_ = P.role_work({"Mo": 5.7, "Sh": 5.5}, {"Mo": 1, "Sh": 2}, {"Sh": 6.5})
    # ROLE_SLOT_CREW (2026-11-01): the changed slots carry the usual split with
    # these players active (Allen RB1 / Hall RB2: 18.9 / 5.9 of the pair's 24.8)
    cr_ = P.role_work({"Ha": 19.0, "Al": 5.8, "Da": 1.4}, {"Al": 1, "Ha": 2}, None, {0: 18.9, 1: 5.9})
    res.append((cr_ == {"Al": 18.9, "Ha": 5.9, "Da": 1.4},
                "a swapped pair splits their work the way it did with both active (Allen RB1 / Hall RB2)", str(cr_)))
    hn_ = P.own_normal([("LAC", 1.0, .15, 0.0), ("LAC", .69, .47, 0.0), ("CHI", 1.0, .30, 0.0)], "LAC", 1)
    res.append((rw_["Mc"] == 6.3 and rw_["Jo"] == 4.4 and rw_["Ha"] == 3.9 and cle_["Bo"] == 5.7
                and den_ == {"Cl": 12.9, "Do": 9.1} and sea_["Pr"] == 12.9 and buf_["Sh"] == 5.5
                and abs(hn_[0] - (.15 + .69 * .47) / 1.69) < 1e-9
                and P.own_normal([("SEA", 1.0, .2, .4)] * 2, "SEA") is None,
                "a starter back in his role gets his normal usage; a backup gets the slot's (McConkey WR1)",
                f"{rw_} {cle_} {den_} {sea_} {buf_} {hn_}"))

    # EVEN (2026-11-03): the marked players share their combined work equally
    ev_ = P.even_goals({"Ha": 4.8, "Al": 18.4, "Da": 2.1}, ["Ha", "Al"])
    res.append((ev_ == {"Ha": 11.6, "Al": 11.6} and P.even_goals({"Ha": 5.0, "Al": 0.0}, ["Ha", "Al"]) == {},
                "EVEN splits the marked players' work equally (Hall / Allen)", str(ev_)))

    # RUSH <n> on a QB (2026-11-03, Daniels): the call reads as his rushing attempts
    import read_review as RR
    res.append((RR.parse_rush("rush 6.5") == 6.5 and RR.parse_rush("Rushes 7") == 7.0
                and RR.parse_rush("65") is None and RR.parse_decision("rush 6.5")[2]
                and RR.parse_rush("rush 6 ypc 6.5") == 6.0 and RR.parse_ypc("rush 6 ypc 6.5") == 6.5
                and RR.parse_ypc("ypc 7") == 7.0 and RR.parse_rush("ypc 7") is None
                and RR.parse_decision("ypc 7")[2] and RR.parse_decision("")[1] == "PLAY",
                "'rush 6.5' / 'ypc 7' / 'rush 6 ypc 6.5' on a QB read as carries / yards per carry", ""))

    # QB carries / QB yds/carry columns (2026-11-04, Joe): their own fields, so a QB can be
    # START and have a rushing call; a blank column falls back to the old text call
    import tempfile
    import review_book as RB
    with tempfile.TemporaryDirectory() as td_:
        with open(os.path.join(td_, "review_2099_wk01.csv"), "w", newline="", encoding="utf-8") as fh:
            fh.write("player_id,player,pos,team,decision,role,rush,ypc,note\n"
                     "A,Qa,QB,WAS,START,,7,6.5,\nB,Qb,QB,BAL,rush 5 ypc 6,,,,\nC,Qc,QB,NYJ,ypc 8,,4,,\n")
        old_data, RR.DATA = RR.DATA, td_
        try:
            ru_, yp_ = RR.load_rush(2099, 1), RR.load_rush(2099, 1, RR.parse_ypc)
        finally:
            RR.DATA = old_data
    res.append((ru_ == {"A": 7.0, "B": 5.0, "C": 4.0} and yp_ == {"A": 6.5, "B": 6.0, "C": 8.0}
                and RB._edit_tuple(["", "OUT", "n"]) == ("", "OUT", "n", "", "")
                and RB._sheet_num("7") == 7 and RB._sheet_num("6.5") == 6.5 and RB._sheet_num("") is None,
                "QB carries / QB yds/carry columns read alongside START (old text calls still work)",
                f"{ru_} {yp_}"))

    # KNEELS_OUT (2026-11-04, Joe): a QB's kneels leave his carries / yards and his team's
    # runs and plays; a non-QB row and the real stat rows are untouched
    with tempfile.TemporaryDirectory() as td_:
        with open(os.path.join(td_, "qb_kneels_2099.csv"), "w", newline="", encoding="utf-8") as fh:
            fh.write("week,team,player_id,kneels,kneel_yds\n3,DET,Q,2,-2.0\n3,DET,T,1,-1.0\n")
        old_data, P.DATA = P.DATA, td_
        try:
            rows_ = [{"player_id": "Q", "week": "3", "team": "DET", "position": "QB", "carries": "3", "rushing_yards": "4"},
                     {"player_id": "T", "week": "3", "team": "DET", "position": "TE", "carries": "1", "rushing_yards": "-1"}]
            kr_, tk_ = P.strip_kneels(rows_, 2099)
        finally:
            P.DATA = old_data
    tm_ = {("DET", 3): {"rush_att": "30", "qb_rush_att": "3", "plays": "70", "dropbacks": "40",
                        "qb_rush_share": "0.1", "pass_rate": "0.5714", "rush_yds": "120"}}
    P.strip_team_kneels(tm_, tk_)
    t3_ = tm_[("DET", 3)]
    res.append((kr_[0]["carries"] == "1.0" and kr_[0]["rushing_yards"] == "6.0" and kr_[1] is rows_[1]
                and rows_[0]["carries"] == "3" and t3_["rush_att"] == "28" and t3_["qb_rush_att"] == "1"
                and t3_["plays"] == "68" and t3_["pass_rate"] == str(round(40 / 68, 4)),
                "kneel-downs come out of a QB's carries / yards and his team's runs and plays", f"{kr_} {t3_}"))

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
