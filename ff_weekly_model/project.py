#!/usr/bin/env python3
"""The weekly projection itself, plus a walk-forward backtest against 2025.

Volume x efficiency, with every piece set by what the data said rather than by
feel (see ff_weekly_model/ notes and the fitted constants in data/):

  plays      team pace, shrunk toward the league mean (k=16 -- team history
             barely predicts play count, so this stays close to league average)
  pass rate  team history (k=8), adjusted down in high wind
  targets    player's share, blended against a prior whose k depends on whether
             he stayed put (3), changed teams (1), or has no history (2, with
             the preseason DEPTH CHART as the prior -- 17% better than a
             position average)
  carries    same, k=0.5 for everyone; backfield roles churn too fast to trust
             last season even for a returning back
  efficiency POSITION MEANS, never the player's own history, which measured
             worse than ignoring the player entirely
  TDs        implied team total from the Vegas line, split pass/rush by the
             projected pass rate, then allocated by target/carry share

STRICTLY walk-forward: projecting week w uses only weeks < w of the current
season, the prior season, the preseason depth chart, and that week's betting
line. Nothing from week w's box score reaches the projection.

Usage:
    python project.py --year 2025            # backtest every week
    python project.py --year 2025 --week 10  # one week's projections
"""

import argparse
import collections
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ff_weekly_proj"))
import scoring  # noqa: E402

POSITIONS = ("RB", "WR", "TE")
HALF_PPR = 0.5

K_PLAYS, K_PASS_RATE, K_QB_RUSH = 16, 8, 3
K_TGT = {"same team": 3.0, "changed team": 1.0, "no history": 2.0}
K_CAR = {"same team": 0.5, "changed team": 0.5, "no history": 0.5}
WIND_THRESHOLD, WIND_PASS_PENALTY = 15.0, 0.026   # measured within-team
PRIOR_GAME_WEIGHT = 0.0   # swept in sweep_prior_weight.py


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def blend(observed, n, prior, k):
    return prior if n + k == 0 else (n * observed + k * prior) / (n + k)


# ---------------------------------------------------------------- loading

def load_players(year):
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("season_type") == "REG"]


def load_teams(year):
    path = os.path.join(DATA, f"team_weekly_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["team"], int(r["week"])): r for r in csv.DictReader(fh)}


def load_games(year):
    """(team, week) -> dict with implied points and wind."""
    path = os.path.join(DATA, "games.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached",
                            "nflverse", "games.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] != str(year) or r.get("game_type") != "REG":
                continue
            tot, spr = num(r["total_line"], None), num(r["spread_line"], None)
            if tot is None or spr is None:
                continue
            wk = int(r["week"])
            wind = num(r["wind"], 0.0) if r["roof"] not in ("dome", "closed") else 0.0
            out[(r["home_team"], wk)] = {"implied": tot / 2 + spr / 2, "wind": wind}
            out[(r["away_team"], wk)] = {"implied": tot / 2 - spr / 2, "wind": wind}
    return out


WEEK1_THURSDAY = {2025: "2025-09-04", 2026: "2026-09-10"}


def chart_positions(year):
    """gsis_id -> position from the newest depth-chart snapshot."""
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] in POSITIONS and r["gsis_id"]:
                snaps[r["dt"]][r["gsis_id"]] = r["pos_abb"]
    return snaps[max(snaps)] if snaps else {}


def current_roster(year):
    """Who is on each team RIGHT NOW, from the newest depth-chart snapshot.

    Distinct from load_depth_chart(), which deliberately freezes at preseason
    because it serves as a PRIOR. This one answers "who could play this week",
    so it must be current.
    """
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] not in POSITIONS or not r["gsis_id"]:
                continue
            snaps[r["dt"]][r["gsis_id"]] = r["team"]
    return (snaps[max(snaps)], max(snaps)) if snaps else ({}, None)


def load_depth_chart(year=2025, cutoff=None):
    """Last depth-chart snapshot before week 1 -- the prior for no-history players.

    Deliberately a PRESEASON snapshot: it is only ever used as a starting guess
    for players with no usage history, and once a player has games those games
    say more than any chart. Matches how the 17% improvement was measured.
    """
    cutoff = cutoff or WEEK1_THURSDAY.get(year, f"{year}-09-10")
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                            "nflverse", f"depth_charts_{year}.csv")
    best, chart = "", {}
    snaps = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["pos_abb"] not in POSITIONS or not r["gsis_id"] or r["dt"] >= cutoff:
                continue
            snaps[r["dt"]][r["gsis_id"]] = (r["pos_abb"], min(int(r["pos_rank"]), 5))
    if snaps:
        best = max(snaps)
        chart = snaps[best]
    return chart


# ------------------------------------------------------- derived constants

def shares_by_week(rows):
    """player -> {week: (tgt_share, carry_share)} over SKILL-position denominators."""
    tt = collections.defaultdict(lambda: [0.0, 0.0])
    skill = [r for r in rows if r["position"] in POSITIONS]
    for r in skill:
        t = tt[(r["team"], int(r["week"]))]
        t[0] += num(r["targets"]); t[1] += num(r["carries"])
    tgt, car, pos, team = (collections.defaultdict(dict), collections.defaultdict(dict),
                           {}, collections.defaultdict(collections.Counter))
    for r in skill:
        pid, wk = r["player_id"], int(r["week"])
        d = tt[(r["team"], wk)]
        pos[pid] = r["position"]; team[pid][r["team"]] += 1
        if d[0]:
            tgt[pid][wk] = num(r["targets"]) / d[0]
        if d[1]:
            car[pid][wk] = num(r["carries"]) / d[1]
    modal = {p: c.most_common(1)[0][0] for p, c in team.items()}
    return tgt, car, pos, modal


def fill_observed_zeros(tgt, car, pos, year, snaps_by_week=None):
    """A player who was ON THE FIELD but recorded nothing got a genuine ZERO.

    stats_player_week only carries rows for players with a stat line, so a back
    who took 3 snaps and no carries is indistinguishable from one who was not
    there -- and the model then projects him from his prior instead of from the
    zero he actually posted. ARI wk1 2026: Bam Knight 3 snaps, Corey Kiner 8,
    neither with a carry, both still drawing ~7 projected carries.
    """
    if snaps_by_week is None:
        snaps_by_week = load_snaps_by_week(year)
    added = 0
    for wk, players in snaps_by_week.items():
        for pid, (snaps, position) in players.items():
            if snaps <= 0:
                continue
            if position not in POSITIONS:
                continue
            pos.setdefault(pid, position)
            if wk not in tgt[pid]:
                tgt[pid][wk] = 0.0; added += 1
            if wk not in car[pid]:
                car[pid][wk] = 0.0
    return added


def load_snaps_by_week(year):
    """week -> {gsis_id: (offense_snaps, position)}."""
    base = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
    xwalk = {}
    px = os.path.join(base, "players.csv")
    if os.path.exists(px):
        with open(px, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("pfr_id") and r.get("gsis_id"):
                    xwalk[r["pfr_id"]] = r["gsis_id"]
    path = os.path.join(base, f"snaps_{year}.csv")
    out = collections.defaultdict(dict)
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type") != "REG":
                continue
            g = xwalk.get(r.get("pfr_player_id"))
            if g:
                out[int(r["week"])][g] = (float(r.get("offense_snaps") or 0),
                                          r.get("position", ""))
    return out


def efficiency_means(rows):
    """Position-level efficiency, fit on the PRIOR season (out of sample)."""
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        if r["position"] not in POSITIONS:
            continue
        a = agg[r["position"]]
        a["tgt"] += num(r["targets"]); a["rec"] += num(r["receptions"])
        a["rec_yds"] += num(r["receiving_yards"]); a["car"] += num(r["carries"])
        a["rush_yds"] += num(r["rushing_yards"])
    return {p: {"ypt": a["rec_yds"] / a["tgt"] if a["tgt"] else 0,
                "catch": a["rec"] / a["tgt"] if a["tgt"] else 0,
                "ypc": a["rush_yds"] / a["car"] if a["car"] else 0}
            for p, a in agg.items()}


def league_constants(teams_prior, rows_prior=()):
    """League means and ratios from the prior season."""
    n = len(teams_prior) or 1
    plays = sum(int(r["plays"]) for r in teams_prior.values()) / n
    pr = sum(float(r["pass_rate"]) for r in teams_prior.values()) / n
    qbr = sum(float(r["qb_rush_share"]) for r in teams_prior.values()) / n
    pass_att = sum(int(r["pass_att"]) for r in teams_prior.values())
    drop = sum(int(r["dropbacks"]) for r in teams_prior.values())
    td = sum(int(r["total_td"]) for r in teams_prior.values())
    ptd = sum(int(r["pass_td"]) for r in teams_prior.values())
    # QBs take ~21% of all rushing TDs (sneaks, scrambles) and it is stable
    # year to year. Handing the whole rushing-TD pool to the backfield
    # over-projected RB touchdowns by 28%.
    qb_rtd = sum(num(r["rushing_tds"]) for r in rows_prior if r["position"] == "QB")
    all_rtd = sum(num(r["rushing_tds"]) for r in rows_prior)
    return {"plays": plays, "pass_rate": pr, "qb_rush_share": qbr,
            "sack_rate": 1 - pass_att / drop if drop else 0.065,
            "pass_td_frac": ptd / td if td else 0.6,
            "qb_rush_td_frac": qb_rtd / all_rtd if all_rtd else 0.21}


def fit_implied_to_td(teams, games):
    """Linear map from a team's implied points to expected touchdowns."""
    xs, ys = [], []
    for (tm, wk), r in teams.items():
        g = games.get((tm, wk))
        if g:
            xs.append(g["implied"]); ys.append(int(r["total_td"]))
    if len(xs) < 10:
        return lambda p: p / 7.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0
    a = my - b * mx
    return lambda p: max(0.0, a + b * p)


# ------------------------------------------------------------- projection

def build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos, team_cur,
                 team_prev, chart, extra_ids=(), depth_weight=0.0):
    """Per player: (group, target_share_prior, carry_share_prior)."""
    # These fallbacks MUST come from the prior season. Deriving them from
    # tgt_cur/car_cur leaks the week being projected into its own prior, and in
    # week 1 there is no current season to derive them from at all.
    rank_tgt, rank_car = collections.defaultdict(list), collections.defaultdict(list)
    for pid, wks in tgt_prev.items():
        if pid in chart and len(wks) >= 4:
            rank_tgt[chart[pid]].append(sum(wks.values()) / len(wks))
    for pid, wks in car_prev.items():
        if pid in chart and len(wks) >= 4:
            rank_car[chart[pid]].append(sum(wks.values()) / len(wks))
    rt = {k: sum(v) / len(v) for k, v in rank_tgt.items()}
    rc = {k: sum(v) / len(v) for k, v in rank_car.items()}

    pmean_t, pmean_c = collections.defaultdict(list), collections.defaultdict(list)
    for pid, wks in tgt_prev.items():
        if pid in pos:
            pmean_t[pos[pid]].extend(wks.values())
    for pid, wks in car_prev.items():
        if pid in pos:
            pmean_c[pos[pid]].extend(wks.values())
    pt = {p: sum(v) / len(v) for p, v in pmean_t.items() if v}
    pc = {p: sum(v) / len(v) for p, v in pmean_c.items() if v}

    out = {}
    # extra_ids covers players on the depth chart with no current-season
    # rows yet -- week-1 inactives and un-debuted rookies. Without them a
    # returning RB1 like Josh Jacobs simply vanishes from the slate.
    for pid in set(tgt_cur) | set(car_cur) | set(extra_ids):
        p = pos.get(pid)
        hist_t, hist_c = tgt_prev.get(pid, {}), car_prev.get(pid, {})
        if len(hist_t) >= 4:
            group = ("same team" if team_prev.get(pid) == team_cur.get(pid)
                     else "changed team")
            pri_t = sum(hist_t.values()) / len(hist_t)
            pri_c = (sum(hist_c.values()) / len(hist_c)) if hist_c else pc.get(p, 0)
            # The depth chart knows things last season's usage does not -- a back
            # listed 5th is not getting last year's carries no matter what he did
            # elsewhere. Pull the prior toward the rank average.
            key = chart.get(pid)
            if depth_weight and key in rt:
                pri_t = (1 - depth_weight) * pri_t + depth_weight * rt[key]
            if depth_weight and key in rc:
                pri_c = (1 - depth_weight) * pri_c + depth_weight * rc[key]
        else:
            group = "no history"
            key = chart.get(pid)
            pri_t = rt.get(key, pt.get(p, 0))
            pri_c = rc.get(key, pc.get(p, 0))
        out[pid] = (group, pri_t, pri_c, len(hist_t), len(hist_c))
    return out


def project_week(week, *, teams_cur, games, tgt_cur, car_cur, pos, priors,
                 eff, lg, imp_to_td, tgt_per_att, active, avail=None):
    """Projections for every active skill player in `week`. No week-`week` data used."""
    # --- team volume from weeks strictly before `week`
    tv = {}
    # every team playing this week gets an entry, even with NO history -- in
    # week 1 there is none, and blend() with n=0 correctly returns the league
    # mean. Building tv only from teams with history silently projected nobody.
    for (tm, wk) in games:
        if wk == week:
            tv.setdefault(tm, [])
    for (tm, wk), r in teams_cur.items():
        if wk >= week:
            continue
        tv.setdefault(tm, []).append(r)
    team_proj = {}
    for tm, hist in tv.items():
        n = len(hist)
        plays = blend(sum(int(h["plays"]) for h in hist) / n if n else 0, n,
                      lg["plays"], K_PLAYS)
        prate = blend(sum(float(h["pass_rate"]) for h in hist) / n if n else 0, n,
                      lg["pass_rate"], K_PASS_RATE)
        qbr = blend(sum(float(h["qb_rush_share"]) for h in hist) / n if n else 0, n,
                    lg["qb_rush_share"], K_QB_RUSH)
        g = games.get((tm, week))
        if g and g["wind"] >= WIND_THRESHOLD:
            prate -= WIND_PASS_PENALTY
        dropbacks = plays * prate
        pass_att = dropbacks * (1 - lg["sack_rate"])
        rush_att = plays * (1 - prate)
        tds = imp_to_td(g["implied"]) if g else lg["plays"] * 0 + 2.4
        team_proj[tm] = {
            "targets": pass_att * tgt_per_att,
            "nonqb_rush": rush_att * (1 - qbr),
            "pass_td": tds * lg["pass_td_frac"],
            "rush_td": tds * (1 - lg["pass_td_frac"]) * (1 - lg["qb_rush_td_frac"]),
        }

    # --- pass 1: raw blended shares
    raw = {}
    for pid, tm in active.items():
        if tm not in team_proj or pos.get(pid) not in eff:
            continue
        group, pri_t, pri_c, n_pt, n_pc = priors.get(
            pid, ("no history", 0.0, 0.0, 0, 0))
        past_t = [v for w, v in tgt_cur.get(pid, {}).items() if w < week]
        past_c = [v for w, v in car_cur.get(pid, {}).items() if w < week]
        # A prior built on 17 consistent games should not be dislodged by one
        # week the way a prior built on 4 games is. PRIOR_GAME_WEIGHT scales k
        # by how much evidence actually backs the prior; 0 keeps the old
        # fixed-k behaviour.
        kt = K_TGT[group] + PRIOR_GAME_WEIGHT * n_pt
        kc = K_CAR[group] + PRIOR_GAME_WEIGHT * n_pc
        # availability scales the share BEFORE normalisation, so a removed
        # player's touches are handed to his teammates rather than vanishing
        m = 1.0 if avail is None else avail.get(pid, 1.0)
        if m <= 0:
            continue
        raw[pid] = (tm,
                    m * blend(sum(past_t) / len(past_t) if past_t else 0, len(past_t),
                              pri_t, kt),
                    m * blend(sum(past_c) / len(past_c) if past_c else 0, len(past_c),
                              pri_c, kc))

    # --- pass 2: RECONCILE. Blending each player independently leaves a team's
    # shares not summing to 1 (measured: 8.8% too many targets league-wide, and
    # up to +47% on individual teams). Normalising restores the identity that
    # every target belongs to exactly one player.
    tot_t, tot_c = collections.defaultdict(float), collections.defaultdict(float)
    for tm, ts, cs in raw.values():
        tot_t[tm] += ts; tot_c[tm] += cs

    out = {}
    for pid, (tm, ts, cs) in raw.items():
        tp = team_proj[tm]
        ts = ts / tot_t[tm] if tot_t[tm] else 0.0
        cs = cs / tot_c[tm] if tot_c[tm] else 0.0
        targets, carries = ts * tp["targets"], cs * tp["nonqb_rush"]
        e = eff[pos[pid]]
        out[pid] = {
            "rec": targets * e["catch"], "rec_yds": targets * e["ypt"],
            "rec_td": ts * tp["pass_td"], "rush_yds": carries * e["ypc"],
            "rush_td": cs * tp["rush_td"], "fum": 0.0,
            "targets": targets, "rush_att": carries,
        }
    return out


def points(stat):
    return (scoring.rushing_points(stat) + scoring.receiving_points(stat, HALF_PPR)
            + scoring.fumble_points(stat))


def actual_points(r):
    return points({"rush_yds": num(r["rushing_yards"]), "rush_td": num(r["rushing_tds"]),
                   "rec": num(r["receptions"]), "rec_yds": num(r["receiving_yards"]),
                   "rec_td": num(r["receiving_tds"]),
                   "fum": num(r["rushing_fumbles_lost"]) + num(r["receiving_fumbles_lost"])})


# ---------------------------------------------------------------- backtest

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--live", action="store_true",
                    help="project an UPCOMING week (no actuals needed)")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    prev_year = args.year - 1

    cur_rows, prev_rows = load_players(args.year), load_players(prev_year)
    teams_cur, teams_prev = load_teams(args.year), load_teams(prev_year)
    games_cur, games_prev = load_games(args.year), load_games(prev_year)
    chart = load_depth_chart(args.year)

    tgt_cur, car_cur, pos, team_cur = shares_by_week(cur_rows)
    tgt_prev, car_prev, _, team_prev = shares_by_week(prev_rows)
    # players who were on the field but posted no stat line recorded a real
    # zero, not a missing week
    fill_observed_zeros(tgt_cur, car_cur, pos, args.year)
    eff = efficiency_means(prev_rows)
    lg = league_constants(teams_prev, prev_rows)
    imp_to_td = fit_implied_to_td(teams_prev, games_prev)          # prior season only
    skill_tgt = sum(num(r["targets"]) for r in prev_rows if r["position"] in POSITIONS)
    pass_att = sum(int(t["pass_att"]) for t in teams_prev.values())
    tgt_per_att = skill_tgt / pass_att if pass_att else 0.95
    priors = build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos,
                          team_cur, team_prev, chart)

    if args.live:
        if not args.week:
            ap.error("--live requires --week")
        roster, asof = current_roster(args.year)
        for pid, p in chart_positions(args.year).items():
            pos.setdefault(pid, p)
        priors = build_priors(tgt_cur, car_cur, tgt_prev, car_prev, pos,
                              team_cur, team_prev, chart, extra_ids=roster)
        played = {r["player_id"]: r["team"] for r in cur_rows
                  if r["position"] in POSITIONS and int(r["week"]) < args.week}
        active = {**roster, **played}          # season usage wins on team
        active = {p: t for p, t in active.items() if p in pos}
        import availability
        import read_review
        # CURRENT ranks (not the preseason prior) -- the rotation check needs to
        # know who is listed where right now.
        rank_now = {pid: rk for pid, (p_, rk) in
                    load_depth_chart(args.year, cutoff="9999-01-01").items()}
        review, problems = read_review.load(args.year, args.week)
        for who, what in problems:
            print(f"  !! review sheet: could not read {what!r} for {who} "
                  f"-- treated as PLAY")
        avail, reason = availability.build(args.year, args.week, candidates=active,
                                           depth_rank=rank_now, review=review)
        proj = project_week(args.week, teams_cur=teams_cur, games=games_cur,
                            tgt_cur=tgt_cur, car_cur=car_cur, pos=pos, priors=priors,
                            eff=eff, lg=lg, imp_to_td=imp_to_td,
                            tgt_per_att=tgt_per_att, active=active, avail=avail)
        name = {r["player_id"]: r["player_display_name"] for r in cur_rows}
        for r in load_players(prev_year):
            name.setdefault(r["player_id"], r["player_display_name"])
        # 61 players -- rookies, and anyone who missed all of last season -- appear
        # on the depth chart but in neither stats file. Take their name from there.
        dpath = os.path.join(DATA, f"depth_charts_{args.year}.csv")
        if os.path.exists(dpath):
            with open(dpath, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("gsis_id") and r.get("player_name"):
                        name.setdefault(r["gsis_id"], r["player_name"])
        rows = sorted(((points(v), pid) for pid, v in proj.items()), reverse=True)
        dest = os.path.join(DATA, f"projections_{args.year}_wk{args.week:02d}.csv")
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["player_id", "player", "pos", "team", "half_ppr",
                        "targets", "rush_att", "rec", "rec_yds", "rush_yds",
                        "rec_td", "rush_td"])
            for pts, pid in rows:
                v = proj[pid]
                w.writerow([pid, name.get(pid, ""), pos[pid], active[pid],
                            round(pts, 2), round(v["targets"], 1), round(v["rush_att"], 1),
                            round(v["rec"], 1), round(v["rec_yds"], 1),
                            round(v["rush_yds"], 1), round(v["rec_td"], 2),
                            round(v["rush_td"], 2)])
        print()
        print(f"  {args.year} week {args.week} projections  "
              f"(depth chart as of {asof})")
        print()
        print(f"  {'#':<4}{'player':<24}{'pos':<5}{'tm':<5}{'proj':>7}{'tgt':>7}{'car':>7}")
        for i, (pts, pid) in enumerate(rows[:args.top], 1):
            v = proj[pid]
            print(f"  {i:<4}{name.get(pid, pid):<24}{pos[pid]:<5}{active[pid]:<5}"
                  f"{pts:>7.1f}{v['targets']:>7.1f}{v['rush_att']:>7.1f}")
        print()
        removed = [(p, reason[p]) for p, m in avail.items() if m == 0.0]
        byreason = collections.Counter(r.split(":")[0] for _, r in removed)
        print(f"  availability: {len(removed)} of {len(active)} removed  "
              + ", ".join(f"{k} {v}" for k, v in byreason.most_common()))
        print(f"  {len(rows):,} players -> {os.path.basename(dest)}")
        print()
        return

    by_week = collections.defaultdict(list)
    for r in cur_rows:
        if r["position"] in POSITIONS:
            by_week[int(r["week"])].append(r)

    ctx = dict(teams_cur=teams_cur, games=games_cur, tgt_cur=tgt_cur, car_cur=car_cur,
               pos=pos, eff=eff, lg=lg, imp_to_td=imp_to_td, tgt_per_att=tgt_per_att)
    globals()["_CTX"] = (ctx, by_week, priors,
                         dict(tgt_cur=tgt_cur, car_cur=car_cur, tgt_prev=tgt_prev,
                              car_prev=car_prev, pos=pos, team_cur=team_cur,
                              team_prev=team_prev, chart=chart))

    weeks = [args.week] if args.week else sorted(w for w in by_week if 2 <= w <= 18)
    err = collections.defaultdict(lambda: collections.defaultdict(list))

    for w in weeks:
        active = {r["player_id"]: r["team"] for r in by_week[w]}
        proj = project_week(w, teams_cur=teams_cur, games=games_cur, tgt_cur=tgt_cur,
                            car_cur=car_cur, pos=pos, priors=priors, eff=eff, lg=lg,
                            imp_to_td=imp_to_td, tgt_per_att=tgt_per_att, active=active)
        for r in by_week[w]:
            pid = r["player_id"]
            if pid not in proj:
                continue
            a = actual_points(r)
            p = points(proj[pid])
            # baselines, all walk-forward
            hist = [actual_points(x) for x in
                    (row for wk in range(1, w) for row in by_week.get(wk, [])
                     if row["player_id"] == pid)]
            std = sum(hist) / len(hist) if hist else None
            l3 = sum(hist[-3:]) / len(hist[-3:]) if hist else None
            grp = r["position"]
            err[grp]["model"].append((p - a) ** 2)
            err["ALL"]["model"].append((p - a) ** 2)
            if std is not None:
                err[grp]["season avg"].append((std - a) ** 2)
                err["ALL"]["season avg"].append((std - a) ** 2)
                err[grp]["last 3"].append((l3 - a) ** 2)
                err["ALL"]["last 3"].append((l3 - a) ** 2)

    def rmse(v):
        return math.sqrt(sum(v) / len(v)) if v else float("nan")

    print(f"\n  walk-forward backtest, {args.year} weeks {weeks[0]}-{weeks[-1]}  "
          f"(half-PPR, RMSE in fantasy points)\n")
    print(f"  {'':<6}{'n':>8}{'MODEL':>9}{'season avg':>13}{'last 3':>10}{'vs best baseline':>19}")
    for grp in ("ALL", "RB", "WR", "TE"):
        e = err.get(grp)
        if not e:
            continue
        m, s, l = rmse(e["model"]), rmse(e["season avg"]), rmse(e["last 3"])
        best = min(s, l)
        print(f"  {grp:<6}{len(e['model']):>8,}{m:>9.3f}{s:>13.3f}{l:>10.3f}"
              f"{(best - m) / best * 100:>18.1f}%")
    print()


if __name__ == "__main__":
    main()
