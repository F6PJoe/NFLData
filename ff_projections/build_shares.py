#!/usr/bin/env python3
"""Historical usage share per player -> the baseline for manual usage entry.

This is NOT a projection. It computes what players actually *did* in 2023-2025,
so the workbook can show it beside the cell you're typing in and seed a
starting value you overwrite.

Two outputs:

  player_shares.csv    per player: each season's target share, rush share,
                       red-zone shares and efficiency, plus a recency-weighted
                       blend and a red-zone RATIO (how much a player over- or
                       under-indexes near the goal line relative to his overall
                       usage). One usage number then drives both.

  vacated_2026.csv     per team: how much 2025 share walked out the door, and
                       who took it with them. Share is team-relative and never
                       transfers with a player, so every departure leaves a
                       hole that has to be reallocated by hand. League-wide
                       this is ~25% of targets and ~21% of carries.

Denominators are cleaned: kneel-downs come out of rush attempts (victory
formation isn't opportunity). Seasons are weighted by recency AND games played,
so a 4-game sample doesn't count like a 17-game one.

Usage:
    python build_shares.py
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

import names
from teams import TEAMS, clean_team

HERE = os.path.dirname(os.path.abspath(__file__))
SR = os.path.join(HERE, "cached", "sr")

RECENCY = {0: 0.5, 1: 0.3, 2: 0.2}   # offset from most recent season
FULL_SEASON = 17


def _i(d, key):
    try:
        return int(d.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def share(player_stat, team_stat):
    """SEASON share: this player's cut of the team's year.

    Sums to exactly 100% across a roster, which is the whole point - it is the
    quantity the workbook constrains and the one a human can reason about.

    An earlier version used per-game rates ("what he commanded while active").
    Those are a better measure of a healthy player, but across a roster they
    sum to ~143% (ARI 2025), because each is measured over a different number
    of games. Scaling that back to 100% squashed the stars and handed the
    difference to whoever missed the most time: Trey McBride fell 27.4% -> 17.9%
    while James Conner, who played 3 games, was seeded at 20% of the carries.
    """
    return player_stat / team_stat if team_stat else 0.0


def per_game_rate(player_stat, player_games, team_stat, team_games):
    """What he commanded while ACTIVE - reference only, never the seed.

    This is the number that shows Garrett Wilson was a 30% target earner in
    2025, not the 12.5% his season line implies. Displayed beside the input so
    a player who missed time can be bumped up by hand.
    """
    if not player_games or not team_stat or not team_games:
        return 0.0
    team_rate = team_stat / team_games
    return (player_stat / player_games) / team_rate if team_rate else 0.0


def load_season(season):
    """{player_key: usage dict} plus the team denominators, for one season."""
    path = os.path.join(SR, str(season))
    if not os.path.isdir(path):
        return {}
    out = {}
    for fn in sorted(os.listdir(path)):
        with open(os.path.join(path, fn), encoding="utf-8") as fh:
            d = json.load(fh)
        team = clean_team(d["alias"])
        if team == "FA":
            continue
        rec, rush = d["record"]["receiving"], d["record"]["rushing"]
        pas = d["record"]["passing"]

        t_games = _i(d["record"], "games_played") or FULL_SEASON
        t_tgt = _i(rec, "targets")
        t_rzt = _i(rec, "redzone_targets")
        t_att = _i(rush, "attempts") - _i(rush, "kneel_downs")
        t_rza = _i(rush, "redzone_attempts")
        t_pass = _i(pas, "attempts")
        # Team TD pools, for TD market share. Kept SEPARATE from yardage share
        # on purpose: a goal-line back can own 35% of a team's rushing TDs on
        # 8% of its carries, and a slot receiver the reverse. Deriving TDs from
        # volume share would erase exactly that distinction.
        t_td = d["record"].get("touchdowns") or {}
        t_ptd = _i(t_td, "pass")
        t_rtd = _i(t_td, "rush")
        # Team efficiency baselines. Player efficiency is stored RELATIVE to
        # these, so it can scale a share of the team's yardage instead of
        # being an independent absolute rate that never reconciles.
        t_ypt = _i(rec, "yards") / t_tgt if t_tgt else 0.0
        t_ypc = _i(rush, "yards") / t_att if t_att else 0.0

        for p in d["players"]:
            pr, pu = p.get("receiving") or {}, p.get("rushing") or {}
            pp = p.get("passing") or {}
            tgt, att = _i(pr, "targets"), _i(pu, "attempts") - _i(pu, "kneel_downs")
            patt = _i(pp, "attempts")
            if tgt == 0 and att == 0 and patt == 0:
                continue
            games = _i(p, "games_played") or 1
            key = p["id"] or names.normalize(p["name"])
            out[key] = {
                "name": p["name"], "team": team, "pos": p.get("position", ""),
                "games": games, "season": season,
                "name_key": names.normalize(p["name"]),
                "tgt": tgt, "rec": _i(pr, "receptions"),
                "rec_yds": _i(pr, "yards"), "rec_td": _i(pr, "touchdowns"),
                "rz_tgt": _i(pr, "redzone_targets"),
                "att": att, "rush_yds": _i(pu, "yards"),
                "rush_td": _i(pu, "touchdowns"),
                "rz_att": _i(pu, "redzone_attempts"),
                # Sportradar's passing.yards is NET of sacks - gross_yards is
                # what everyone else calls passing yards. See CLAUDE.md.
                "patt": patt, "pass_yds": _i(pp, "gross_yards"),
                "pass_td": _i(pp, "touchdowns"), "pass_int": _i(pp, "interceptions"),
                # PER-GAME shares: the rate a player commanded volume in the
                # games he actually played, not diluted by games he missed.
                # Season-total share badly understates anyone who got hurt --
                # Garrett Wilson read 12.5% in 2025 on a season basis but
                # commanded 30.4% in his 7 games. Projected availability is a
                # separate input (the Games column), so it must not be baked
                # into the share as well or it gets applied twice.
                "pass_share": share(patt, t_pass),
                "tgt_share": share(tgt, t_tgt),
                "rush_share": share(att, t_att),
                "rz_tgt_share": share(_i(pr, "redzone_targets"), t_rzt),
                "rz_rush_share": share(_i(pu, "redzone_attempts"), t_rza),
                "rush_td_share": share(_i(pu, "touchdowns"), t_rtd),
                "rec_td_share": share(_i(pr, "touchdowns"), t_ptd),
                # reference only - what he earned in the games he played
                "tgt_share_pg": per_game_rate(tgt, games, t_tgt, t_games),
                "rush_share_pg": per_game_rate(att, games, t_att, t_games),
                "catch_pct": _i(pr, "receptions") / tgt if tgt else 0.0,
                "ypr": _i(pr, "yards") / _i(pr, "receptions") if _i(pr, "receptions") else 0.0,
                "ypc": _i(pu, "yards") / att if att else 0.0,
                # Efficiency as a MULTIPLIER of the team's own rate. 1.00 = he
                # earns yards in proportion to his opportunity share; 1.30 = a
                # deep threat who earns 30% more per target than his teammates.
                "ypt_mult": ((_i(pr, "yards") / tgt) / t_ypt
                             if tgt and t_ypt else 0.0),
                "ypc_mult": ((_i(pu, "yards") / att) / t_ypc
                             if att and t_ypc else 0.0),
            }
    return out


def weighted(seasons, metric):
    """Recency- and games-weighted average of `metric` across seasons.

    seasons is [(offset, rec)] with offset 0 = most recent.
    Weighting by games as well as recency stops a 4-game sample from carrying
    the same authority as a full season.
    """
    num = den = 0.0
    for offset, rec in seasons:
        if not rec or not rec[metric]:
            continue
        w = RECENCY.get(offset, 0.1) * min(rec["games"], FULL_SEASON) / FULL_SEASON
        num += rec[metric] * w
        den += w
    return num / den if den else 0.0


SHARE_COLS = ["tgt_share", "rush_share", "rz_tgt_share", "rz_rush_share",
              "rush_td_share", "rec_td_share",
              "catch_pct", "ypr", "ypc", "pass_share",
              "ypt_mult", "ypc_mult",
              "tgt_share_pg", "rush_share_pg",
              "tgt", "att", "rz_tgt", "rz_att"]   # counts, used to shrink the RZ ratios


def role_priors(history):
    """League-median per-game share by position and within-team depth rank.

    The seed for anyone with no usable history of his own -- rookies, and
    players who changed teams (whose old share belonged to a different
    offense). Ranking players within each team-position by share is a proxy
    for depth chart, which we don't have historically.
    """
    import statistics
    buckets = defaultdict(list)
    for season in history.values():
        by_team = defaultdict(list)
        for rec in season.values():
            pos = "RB" if rec["pos"] == "FB" else rec["pos"]
            if pos in ("QB", "RB", "WR", "TE"):
                by_team[(rec["team"], pos)].append(rec)
        for (_, pos), players in by_team.items():
            for metric in ("tgt_share", "rush_share", "pass_share"):
                ranked = sorted((p[metric] for p in players if p[metric]),
                                reverse=True)
                for rank, val in enumerate(ranked[:8], start=1):
                    buckets[(metric, pos, rank)].append(val)
    return {k: statistics.median(v) for k, v in buckets.items() if v}


def team_shapes(history):
    """How each TEAM distributes volume by depth rank, over the last 3 years.

    Some offences feed a bell cow, others run a committee; some funnel a WR1
    and others spread it. That is a durable team trait, and it beats the league
    median often enough to be worth blending in. Tested on 2025: for WR target
    share the league median scored r=0.801, a team's own 3-yr shape 0.788, and
    a 50/50 blend 0.819. RB rush share: 0.882 / 0.863 / 0.885.
    """
    import statistics
    buckets = defaultdict(list)
    for season in history.values():
        by_team = defaultdict(list)
        for rec in season.values():
            pos = "RB" if rec["pos"] == "FB" else rec["pos"]
            if pos in ("QB", "RB", "WR", "TE"):
                by_team[(rec["team"], pos)].append(rec)
        for (team, pos), players in by_team.items():
            for metric in ("tgt_share", "rush_share", "pass_share"):
                ranked = sorted((p[metric] for p in players if p[metric]),
                                reverse=True)
                for rank, val in enumerate(ranked[:8], start=1):
                    buckets[(team, metric, pos, rank)].append(val)
    return {k: statistics.mean(v) for k, v in buckets.items() if v}


TEAM_SHAPE_WEIGHT = 0.50   # blend weight vs the league median; see team_shapes


def history_rank(history, rec, metric):
    """Where a player's own usage ranked him on his team that season."""
    if not rec or not rec.get(metric):
        return None
    pos = "RB" if rec["pos"] == "FB" else rec["pos"]
    peers = sorted((v[metric] for v in history.values()
                    if v["team"] == rec["team"]
                    and ("RB" if v["pos"] == "FB" else v["pos"]) == pos
                    and v[metric]), reverse=True)
    return peers.index(rec[metric]) + 1 if rec[metric] in peers else None


def blend_weight(metric, hrank, depth):
    """How much of a player's own record to keep vs the role prior.

    Flat 60/40 for targets. For CARRIES the depth chart is a far more decisive
    signal - bell cow vs backup is close to binary - so the weight drops as the
    player's history-implied rank and his current depth disagree. That is what
    demotes a displaced starter: James Conner ranked RB1 by history but sits
    RB3 on the 2026 chart.

    Measured on 2025 from preseason-known information:
        rush   role-only 0.838 | flat 60/40 0.866 | adaptive 0.876
        target role-only 0.774 | flat 60/40 0.810 | adaptive 0.804
    So adaptive is used for rushing only; it slightly hurts targets.
    """
    if metric != "rush_share" or hrank is None or depth is None:
        return HISTORY_WEIGHT
    return max(0.15, HISTORY_WEIGHT - 0.22 * abs(hrank - depth))


def prior_for(priors, metric, pos, depth, shapes=None, team=None):
    """Role prior: league median for the slot, blended with the team's own shape."""
    pos = "RB" if pos == "FB" else pos
    league = 0.0
    for d in (depth, 8, 6, 4, 3, 2, 1):
        val = priors.get((metric, pos, d))
        if val is not None:
            league = val
            break
    if shapes and team:
        own = shapes.get((team, metric, pos, depth))
        if own:
            return (TEAM_SHAPE_WEIGHT * own
                    + (1 - TEAM_SHAPE_WEIGHT) * league)
    return league

# Red-zone ratio shrinkage. The raw ratio (rz share / overall share) is wildly
# unstable on small samples: a TE with two carries, one of them at the goal
# line, computes to 6.4x. Shrink toward 1.0 (= "no red-zone opinion") by
# opportunity count, then clamp. A player needs real red-zone volume before
# his own tendency is trusted over the neutral prior.
# Empirically optimal blend of a player's own record vs his current role;
# see the seeding block in main() for the test that produced it.
HISTORY_WEIGHT = 0.60

# Efficiency multipliers need the same small-sample treatment as the red-zone
# ratios. A receiver with two end-arounds computed to a 2.7x rushing multiplier,
# and one negative-yardage QB came out at -0.32, which would have produced
# negative rushing yards. Shrink toward 1.00 by opportunity count, then clamp.
EFF_STABILIZE = 20.0     # opportunities for 50% weight on the measured rate
EFF_CLAMP = (0.60, 1.50)

RZ_STABILIZE = 8.0      # RZ opportunities for 50% weight on the measured ratio
RZ_CLAMP = (0.25, 2.50)


def eff_multiplier(raw, count):
    """Sample-size-shrunk efficiency multiplier, floored above zero."""
    if not raw or raw <= 0:
        return 1.0
    weight = count / (count + EFF_STABILIZE) if count else 0.0
    shrunk = 1.0 + (raw - 1.0) * weight
    return max(EFF_CLAMP[0], min(EFF_CLAMP[1], shrunk))


def rz_ratio(rz_share, overall_share, rz_count):
    """Sample-size-shrunk red-zone multiplier."""
    if not overall_share or not rz_share:
        return 1.0
    raw = rz_share / overall_share
    weight = rz_count / (rz_count + RZ_STABILIZE) if rz_count else 0.0
    shrunk = 1.0 + (raw - 1.0) * weight
    return max(RZ_CLAMP[0], min(RZ_CLAMP[1], shrunk))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    hist_seasons = [args.season - 1, args.season - 2, args.season - 3]
    history = {yr: load_season(yr) for yr in hist_seasons}
    if not any(history.values()):
        sys.exit(f"No Sportradar cache in {SR}. Run fetch_sportradar.py first.")
    for yr in hist_seasons:
        print(f"  {yr}: {len(history[yr])} players with usage")

    roster_path = os.path.join(HERE, f"rosters_{args.season}.csv")
    if not os.path.exists(roster_path):
        sys.exit(f"Missing {roster_path}. Run build_rosters.py first.")
    roster = list(csv.DictReader(open(roster_path, encoding="utf-8")))

    # Index history by sportradar id and by normalized name (fallback).
    by_id = {yr: hist for yr, hist in history.items()}
    by_name = {yr: {r["name_key"]: r for r in hist.values()}
               for yr, hist in history.items()}

    priors = role_priors(history)
    shapes = team_shapes(history)
    print(f"  role priors from {len(priors)} position/depth buckets, "
          f"blended with {len(shapes)} team-specific shapes")

    rows, matched = [], 0
    for r in roster:
        seasons = []
        for offset, yr in enumerate(hist_seasons):
            rec = by_id[yr].get(r["sportradar_id"]) if r["sportradar_id"] else None
            if rec is None:
                rec = by_name[yr].get(names.normalize(r["player"]))
            seasons.append((offset, rec))
        if any(rec for _, rec in seasons):
            matched += 1

        out = {
            "player": r["player"], "team": r["team"], "pos": r["pos"],
            "depth": r["depth"], "status": r["status"], "age": r["age"],
            "sportradar_id": r["sportradar_id"],
        }
        for offset, yr in enumerate(hist_seasons):
            rec = seasons[offset][1]
            out[f"team_{yr}"] = rec["team"] if rec else ""
            out[f"games_{yr}"] = rec["games"] if rec else ""
            out[f"tgt_share_{yr}"] = round(rec["tgt_share"], 4) if rec else ""
            out[f"rush_share_{yr}"] = round(rec["rush_share"], 4) if rec else ""
            out[f"rz_tgt_share_{yr}"] = round(rec["rz_tgt_share"], 4) if rec else ""
            out[f"rz_rush_share_{yr}"] = round(rec["rz_rush_share"], 4) if rec else ""
            out[f"pass_share_{yr}"] = round(rec["pass_share"], 4) if rec else ""
            out[f"rush_td_share_{yr}"] = round(rec["rush_td_share"], 4) if rec else ""
            out[f"rec_td_share_{yr}"] = round(rec["rec_td_share"], 4) if rec else ""

        for col in SHARE_COLS:
            out[f"{col}_w"] = round(weighted(seasons, col), 4)

        # Efficiency is a PLAYER trait - it travels with him to a new team,
        # unlike usage. But it has to survive small samples first.
        out["ypt_mult_w"] = round(
            eff_multiplier(out["ypt_mult_w"], out["tgt_w"]), 3)
        out["ypc_mult_w"] = round(
            eff_multiplier(out["ypc_mult_w"], out["att_w"]), 3)

        # ── seed every row, and say what the seed is based on ──────────────
        # A half-filled sheet is worse than either extreme: you can't tell
        # "not done yet" from "the model thinks zero". Players with usable
        # history use it; everyone else gets the league median for his role.
        prior = seasons[0][1]
        changed = bool(prior and prior["team"] != r["team"])
        has_history = any(out[f"{m}_w"] for m in
                          ("tgt_share", "rush_share", "pass_share"))
        depth = int(r["depth"]) if str(r["depth"]).isdigit() else 8

        if has_history and not changed:
            # Blend the player's own record with the league median for the
            # role he currently holds. Neither alone is best: tested on 2025
            # using only preseason-known information, prior-year share scored
            # r=0.878 (targets) / 0.893 (rush), depth-chart role alone 0.857 /
            # 0.877, and a 60/40 blend 0.899 / 0.913. The curve is flat from
            # 30/70 to 70/30, so the exact weight is not worth tuning further.
            #
            # This is what catches a displaced starter (James Conner carrying a
            # 43% rush share into a season where he's listed RB3) and, in the
            # other direction, gives a promoted backup the boost his history
            # can't show.
            out["seed_basis"] = "history + role"
            for metric in ("tgt_share", "rush_share"):
                own = out[f"{metric}_w"]
                role = prior_for(priors, metric, r["pos"], depth,
                                 shapes, r["team"])
                hrank = history_rank(history[hist_seasons[0]], prior, metric)
                w = blend_weight(metric, hrank, depth)
                if own or role:
                    out[f"{metric}_w"] = round(w * own + (1 - w) * role, 4)
                if metric == "rush_share" and hrank and depth and hrank != depth:
                    out["role_change"] = f"was RB{hrank} -> now {depth}"
        else:
            out["seed_basis"] = ("role average (new team)" if changed
                                 else "role average (no history)")
            for metric in ("tgt_share", "rush_share", "pass_share"):
                out[f"{metric}_w"] = round(
                    prior_for(priors, metric, r["pos"], depth,
                              shapes, r["team"]), 4)
            # Neutral efficiency until there's evidence otherwise.
            for metric in ("ypt_mult", "ypc_mult"):
                if not out[f"{metric}_w"]:
                    out[f"{metric}_w"] = 1.0
            if not out["catch_pct_w"]:
                out["catch_pct_w"] = 0.65 if r["pos"] in ("WR", "TE") else 0.75

        # Efficiency multipliers default to neutral rather than zero, so a
        # player with share but no efficiency history still produces yards.
        for metric in ("ypt_mult", "ypc_mult"):
            if not out[f"{metric}_w"]:
                out[f"{metric}_w"] = 1.0

        # Red-zone RATIO: how much this player over/under-indexes near the goal
        # line vs his overall usage. 1.0 = scores in proportion to volume;
        # >1 = red-zone weapon (most TEs, goal-line backs); <1 = volume-only
        # (slot WRs, receiving backs). This is what lets ONE usage input drive
        # both the yardage and the touchdown side.
        out["rz_tgt_ratio"] = round(rz_ratio(
            out["rz_tgt_share_w"], out["tgt_share_w"], out["rz_tgt_w"]), 3)
        out["rz_rush_ratio"] = round(rz_ratio(
            out["rz_rush_share_w"], out["rush_share_w"], out["rz_att_w"]), 3)
        # Did this player play for a different team last year?
        out["prior_team"] = prior["team"] if prior else ""
        out["changed_team"] = "Y" if changed else ""
        rows.append(out)

    cols = (["player", "team", "pos", "depth", "status", "age", "prior_team",
             "changed_team"]
            + [f"{k}_{yr}" for yr in hist_seasons
               for k in ("team", "games", "tgt_share", "rush_share",
                         "rz_tgt_share", "rz_rush_share", "pass_share",
                         "rush_td_share", "rec_td_share")]
            + [f"{c}_w" for c in SHARE_COLS]
            + ["rz_tgt_ratio", "rz_rush_ratio", "seed_basis", "sportradar_id"])

    out_path = os.path.join(HERE, "player_shares.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote player_shares.csv - {len(rows)} players, "
          f"{matched} with prior usage ({len(rows) - matched} rookies/no-snap)")

    build_vacated(history[hist_seasons[0]], roster, hist_seasons[0], args.season)


def build_vacated(last_season, roster, prior_year, season):
    """Per-team report of usage share that left the building."""
    here_now = {}
    for r in roster:
        if r["status"] != "OUT":
            here_now[names.normalize(r["player"])] = r["team"]

    vac = defaultdict(lambda: {"tgt": 0.0, "rush": 0.0, "who": []})
    for rec in last_season.values():
        now = here_now.get(rec["name_key"])
        if now == rec["team"]:
            continue
        if rec["tgt_share"] < 0.01 and rec["rush_share"] < 0.01:
            continue
        v = vac[rec["team"]]
        v["tgt"] += rec["tgt_share"]
        v["rush"] += rec["rush_share"]
        v["who"].append((rec["name"], rec["pos"], rec["tgt_share"],
                         rec["rush_share"], now or "NOT ON ANY ROSTER"))

    out_path = os.path.join(HERE, f"vacated_{season}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "tgt_share_vacated", "rush_share_vacated",
                    "player", "pos", "tgt_share", "rush_share", "went_to"])
        for team in TEAMS:
            v = vac[team]
            for name, pos, tgt, rush, went in sorted(
                    v["who"], key=lambda x: -max(x[2], x[3])):
                w.writerow([team, round(v["tgt"], 4), round(v["rush"], 4),
                            name, pos, round(tgt, 4), round(rush, 4), went])

    print(f"Wrote vacated_{season}.csv")
    print(f"\n{prior_year} usage vacated going into {season}:\n")
    print(f"  {'TM':<5}{'TGT':>7}{'RUSH':>7}   biggest departures")
    print(f"  {'-'*5}{'-'*7}{'-'*7}   {'-'*46}")
    for team in sorted(TEAMS, key=lambda t: -vac[t]["tgt"])[:10]:
        v = vac[team]
        top = sorted(v["who"], key=lambda x: -max(x[2], x[3]))[:2]
        s = "; ".join(f"{n} {t*100:.0f}t/{ru*100:.0f}r->{w}"
                      for n, _, t, ru, w in top)
        print(f"  {team:<5}{v['tgt']*100:>6.0f}%{v['rush']*100:>6.0f}%   {s}")
    avg_t = sum(v["tgt"] for v in vac.values()) / len(TEAMS)
    avg_r = sum(v["rush"] for v in vac.values()) / len(TEAMS)
    print(f"\n  league average: {avg_t*100:.0f}% of targets, "
          f"{avg_r*100:.0f}% of carries need reallocating")


if __name__ == "__main__":
    sys.exit(main())
