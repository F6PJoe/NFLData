"""Defensive matchups: what each defense allows, stat by stat, to each position.

For every defense and position (QB, RB, WR, TE) the model keeps two running
totals over the weeks already played: what opposing players ACTUALLY did
against that defense, and what this model PROJECTED for those same players
that week. The ratio is the defense's effect. Comparing against our own
projection -- not against league averages -- is what adjusts for the offenses
a defense has faced: a unit that drew the Bills and the Chiefs is judged
against the big numbers we already expected from them.

Each ratio is a rate per opportunity, so volume and efficiency stay separate:

    tgt     share of the offense's targets that went to the position
    catch   receptions per target          ypt     receiving yards per target
    rectd   receiving TDs per target       car     carries to the position
    ypc     rushing yards per carry        rushtd  rushing TDs per carry
    QB:     ypa (pass yards/att), int (INTs/att), qbypc (QB rush yards/carry)

and is shrunk toward 1.0 (no effect) by games played: games / (games + K).
So a defense's number is close to neutral in week 3 and earns its weight as
the season goes -- the gradual ramp Joe asked for.

Totals the market already prices stay put. Vegas's implied total knows who
the defense is, so touchdowns only MOVE between positions (each team's
receiving and rushing TD totals are conserved), and targets and carries are
re-split inside the team's existing totals. Yards, catches and INTs adjust
directly, and a QB's passing yards follow his receivers' adjusted yards.
"""

import collections

SKILL = ("RB", "WR", "TE")
KEYS = ("tgt", "rec", "rec_yds", "rec_td", "car", "rush_yds", "rush_td",
        "patt", "pyds", "pint", "qcar", "qryd")


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _proj_line(v, position):
    if position == "QB":
        return {"patt": v.get("pass_att", 0.0), "pyds": v.get("pass_yds", 0.0),
                "pint": v.get("pass_int", 0.0), "qcar": v.get("rush_att", 0.0),
                "qryd": v.get("rush_yds", 0.0)}
    return {"tgt": v.get("targets", 0.0), "rec": v.get("rec", 0.0),
            "rec_yds": v.get("rec_yds", 0.0), "rec_td": v.get("rec_td", 0.0),
            "car": v.get("rush_att", 0.0), "rush_yds": v.get("rush_yds", 0.0),
            "rush_td": v.get("rush_td", 0.0)}


def _act_line(r):
    if r["position"] == "QB":
        return {"patt": _num(r["attempts"]), "pyds": _num(r["passing_yards"]),
                "pint": _num(r["passing_interceptions"]), "qcar": _num(r["carries"]),
                "qryd": _num(r["rushing_yards"])}
    return {"tgt": _num(r["targets"]), "rec": _num(r["receptions"]),
            "rec_yds": _num(r["receiving_yards"]), "rec_td": _num(r["receiving_tds"]),
            "car": _num(r["carries"]), "rush_yds": _num(r["rushing_yards"]),
            "rush_td": _num(r["rushing_tds"])}


class Matchups:
    def __init__(self, k, stats=None, positions=None):
        self.k = k
        self.positions = set(positions) if positions else None   # None = all
        self.stats = set(stats) if stats else None   # None = every factor
        self.acc = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        self.games = collections.defaultdict(set)

    # ------------------------------------------------------------ learning
    def update(self, week, proj, rows):
        """Add one played week: `proj` is the UNADJUSTED projection."""
        for r in rows:
            pid, po = r["player_id"], r["position"]
            if pid not in proj or po not in SKILL + ("QB",):
                continue
            d = r.get("opponent_team")
            if not d:
                continue
            a, p = _act_line(r), _proj_line(proj[pid], po)
            for k in a:
                self.acc[(d, po)][k][0] += a[k]
                self.acc[(d, po)][k][1] += p[k]
            self.games[(d, po)].add(week)

    # ------------------------------------------------------------ factors
    def factors(self, d, po):
        if self.positions is not None and po not in self.positions:
            return {}
        acc = self.acc.get((d, po))
        n = len(self.games.get((d, po), ()))
        if not acc or not n:
            return {}
        w = n / (n + self.k)

        def ratio(num_key, den_key=None):
            an, pn = acc[num_key]
            if den_key is None:
                return an / pn if pn > 0 else 1.0
            ad, pd = acc[den_key]
            if ad <= 0 or pd <= 0 or pn <= 0:
                return 1.0
            return (an / ad) / (pn / pd)

        raw = ({"ypa": ratio("pyds", "patt"), "int": ratio("pint", "patt"),
                "qbypc": ratio("qryd", "qcar")} if po == "QB" else
               {"tgt": ratio("tgt"), "catch": ratio("rec", "tgt"),
                "ypt": ratio("rec_yds", "tgt"), "rectd": ratio("rec_td", "tgt"),
                "car": ratio("car"), "ypc": ratio("rush_yds", "car"),
                "rushtd": ratio("rush_td", "car")})
        out = {}
        for k, v in raw.items():
            if self.stats is not None and k not in self.stats:
                continue
            v = min(max(v, 0.5), 2.0)              # one freak game is not a trait
            out[k] = 1.0 + w * (v - 1.0)
        return out

    # ------------------------------------------------------------ applying
    def apply(self, proj, week, team_of, pos, opp):
        """-> adjusted copy of `proj`. `opp[(team, week)]` is the defense faced."""
        out = {pid: dict(v) for pid, v in proj.items()}
        by_team = collections.defaultdict(list)
        for pid in out:
            by_team[team_of.get(pid)].append(pid)
        for tm, pids in by_team.items():
            d = opp.get((tm, week))
            if not d:
                continue
            f = {pid: self.factors(d, pos.get(pid)) for pid in pids}
            skill = [p for p in pids if pos.get(p) in SKILL]
            old = {k: sum(out[p].get(k, 0.0) for p in skill)
                   for k in ("targets", "rush_att", "rec_td", "rush_td", "rec_yds")}
            # volume: re-split the team's targets and carries by position
            for p in skill:
                v, g = out[p], f[p]
                t0, c0 = v.get("targets", 0.0), v.get("rush_att", 0.0)
                rate = {"catch": v.get("rec", 0.0) / t0 if t0 else 0.0,
                        "ypt": v.get("rec_yds", 0.0) / t0 if t0 else 0.0,
                        "rectd": v.get("rec_td", 0.0) / t0 if t0 else 0.0,
                        "ypc": v.get("rush_yds", 0.0) / c0 if c0 else 0.0,
                        "rushtd": v.get("rush_td", 0.0) / c0 if c0 else 0.0}
                v["_rate"] = rate
                v["targets"] = t0 * g.get("tgt", 1.0)
                v["rush_att"] = c0 * g.get("car", 1.0)
            for key in ("targets", "rush_att"):
                new = sum(out[p][key] for p in skill)
                if new > 0:
                    for p in skill:
                        out[p][key] *= old[key] / new
            # efficiency per opportunity
            for p in skill:
                v, g = out[p], f[p]
                rate = v.pop("_rate")
                t, c = v["targets"], v["rush_att"]
                v["rec"] = t * rate["catch"] * g.get("catch", 1.0)
                v["rec_yds"] = t * rate["ypt"] * g.get("ypt", 1.0)
                v["rec_td"] = t * rate["rectd"] * g.get("rectd", 1.0)
                v["rush_yds"] = c * rate["ypc"] * g.get("ypc", 1.0)
                v["rush_td"] = c * rate["rushtd"] * g.get("rushtd", 1.0)
            # touchdowns move between players; the team totals stay Vegas's
            for key in ("rec_td", "rush_td"):
                new = sum(out[p][key] for p in skill)
                if new > 0:
                    for p in skill:
                        out[p][key] *= old[key] / new
            # the QB throws what his receivers catch
            yds_new = sum(out[p]["rec_yds"] for p in skill)
            for p in pids:
                if pos.get(p) != "QB":
                    continue
                v, g = out[p], f[p]
                if old["rec_yds"] > 0:
                    v["pass_yds"] = v.get("pass_yds", 0.0) * yds_new / old["rec_yds"]
                v["pass_int"] = v.get("pass_int", 0.0) * g.get("int", 1.0)
                v["rush_yds"] = v.get("rush_yds", 0.0) * g.get("qbypc", 1.0)
        return out


# ====================================================================== EPA
# The same adjustments, driven by EPA instead of yards. For each play the
# defense's number is the play's EPA MINUS the offense's own average EPA on
# that kind of play (targets to a RB / WR / TE, RB runs, QB dropbacks), so the
# offense faced is taken out. A defense's rating is its average of those
# residuals over the weeks already played, shrunk toward zero by plays:
# n / (n + EPA_K). Last season can seed it at a fraction of its weight. The
# rating then scales yards and TDs per opportunity by 1 + BETA x rating.

import csv as _csv
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PBP = _os.path.join(_os.path.dirname(_HERE), "ff_utilization", "cached", "nflverse")
CATS = ("RB_tgt", "WR_tgt", "TE_tgt", "RB_rush", "QB_drop")


def _positions(year):
    out = {}
    for y in (year - 1, year):
        p = _os.path.join(_HERE, "data", f"stats_player_week_{y}.csv")
        if _os.path.exists(p):
            with open(p, newline="", encoding="utf-8") as fh:
                for r in _csv.DictReader(fh):
                    out[r["player_id"]] = r["position"]
    return out


def epa_aggregate(year):
    """(week, offense, defense, cat) -> [sum EPA, plays]; cached per season."""
    cache = _os.path.join(_HERE, "data", f"epa_agg_{year}.csv")
    src = _os.path.join(_PBP, f"pbp_{year}.csv")
    if _os.path.exists(cache) and (not _os.path.exists(src) or
                                   _os.path.getmtime(cache) >= _os.path.getmtime(src)):
        out = {}
        with open(cache, newline="", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                out[(int(r["week"]), r["off"], r["def"], r["cat"])] = [float(r["epa"]), int(r["n"])]
        return out
    if not _os.path.exists(src):
        return {}
    posmap = _positions(year)
    agg = collections.defaultdict(lambda: [0.0, 0])
    with open(src, newline="", encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            if r.get("season_type") != "REG" or r.get("two_point_attempt") == "1":
                continue
            epa = r.get("epa")
            if epa in (None, "", "NA"):
                continue
            off, de, wk = r["posteam"], r["defteam"], int(r["week"])
            cats = []
            if r.get("qb_dropback") == "1":
                cats.append("QB_drop")
            rec = r.get("receiver_player_id")
            if r.get("pass") == "1" and rec not in (None, "", "NA"):
                p = posmap.get(rec)
                if p in ("RB", "WR", "TE"):
                    cats.append(f"{p}_tgt")
            if (r.get("rush") == "1" and r.get("qb_scramble") != "1"
                    and posmap.get(r.get("rusher_player_id")) == "RB"):
                cats.append("RB_rush")
            for c in cats:
                a = agg[(wk, off, de, c)]
                a[0] += float(epa)
                a[1] += 1
    with open(cache, "w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(["week", "off", "def", "cat", "epa", "n"])
        for (wk, o, d, c), (e, n) in agg.items():
            w.writerow([wk, o, d, c, round(e, 4), n])
    return dict(agg)


class EpaMatchups(Matchups):
    # which projected stats each play type moves
    MAP = {"RB": {"RB_tgt": ("ypt", "rectd", "catch"), "RB_rush": ("ypc", "rushtd")},
           "WR": {"WR_tgt": ("ypt", "rectd", "catch")},
           "TE": {"TE_tgt": ("ypt", "rectd", "catch")},
           "QB": {"QB_drop": ("ypa",)}}

    def __init__(self, year, beta, k_plays, prior_w=0.0, k_off=200.0,
                 stats=None, positions=None):
        super().__init__(1.0, stats, positions)
        self.beta, self.k_plays, self.k_off = beta, k_plays, k_off
        self.cur = epa_aggregate(year)
        self.prev = epa_aggregate(year - 1) if prior_w else {}
        self.prior_w = prior_w
        self.week = None
        self._ratings = {}

    def update(self, week, proj, rows):   # everything comes from play-by-play
        pass

    def _rate(self, week):
        """defense -> cat -> shrunk residual EPA per play, from weeks < week."""
        if week in self._ratings:
            return self._ratings[week]
        o_sum = collections.defaultdict(lambda: [0.0, 0])
        lg = collections.defaultdict(lambda: [0.0, 0])
        for (wk, o, d, c), (e, n) in self.cur.items():
            if wk < week:
                o_sum[(o, c)][0] += e
                o_sum[(o, c)][1] += n
                lg[c][0] += e
                lg[c][1] += n
        lgm = {c: (e / n if n else 0.0) for c, (e, n) in lg.items()}
        omean = {k: (e + lgm.get(k[1], 0.0) * self.k_off) / (n + self.k_off)
                 for k, (e, n) in o_sum.items()}
        res = collections.defaultdict(lambda: [0.0, 0.0])
        for (wk, o, d, c), (e, n) in self.cur.items():
            if wk < week:
                m = omean.get((o, c), lgm.get(c, 0.0))
                res[(d, c)][0] += e - n * m
                res[(d, c)][1] += n
        if self.prev:
            po = collections.defaultdict(lambda: [0.0, 0])
            for (wk, o, d, c), (e, n) in self.prev.items():
                po[(o, c)][0] += e
                po[(o, c)][1] += n
            for (wk, o, d, c), (e, n) in self.prev.items():
                m = po[(o, c)][0] / po[(o, c)][1]
                res[(d, c)][0] += self.prior_w * (e - n * m)
                res[(d, c)][1] += self.prior_w * n
        out = collections.defaultdict(dict)
        for (d, c), (s, n) in res.items():
            out[d][c] = s / (n + self.k_plays) if n else 0.0
        self._ratings[week] = out
        return out

    def factors(self, d, po):
        if self.positions is not None and po not in self.positions:
            return {}
        r = self._rate(self.week).get(d, {})
        out = {}
        for cat, stats in self.MAP.get(po, {}).items():
            x = r.get(cat, 0.0)
            for s in stats:
                if self.stats is not None and s not in self.stats:
                    continue
                out[s] = min(max(1.0 + self.beta * x, 0.5), 2.0)
        return out

    def apply(self, proj, week, team_of, pos, opp):
        self.week = week
        return super().apply(proj, week, team_of, pos, opp)
