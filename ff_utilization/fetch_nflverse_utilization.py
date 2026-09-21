#!/usr/bin/env python3
"""
Build the usage table from nflverse (official NFL data) instead of FantasyLife.

Runs ALONGSIDE fetch_fantasylife_utilization.py, not instead of it -- outputs
the same column names and file shape so the same grid renders either one, and
so the two can be diffed.

Why nflverse rather than scraping GSIS gamebooks
------------------------------------------------
They are the same numbers. nflfastR parses the NFL's own play-by-play feed, and
nflverse snap counts trace to the official participation report. Measured
against the GSIS gamebook PDFs for 2025 week 1: **325 of 328 players exact
(99%)** on offensive snaps, the three misses being name-collision artifacts in
the test's matcher. So nflverse gives official numbers already structured --
no PDF parsing, no 16 downloads a week, no format drift mid-season.

Official basis vs PFF basis -- DO NOT MIX THEM
----------------------------------------------
nflverse runs consistently HIGHER than FL/PFF, one-directionally, because PFF
applies charting judgment the official feed doesn't. Measured on 2025 wk1-2:

    snaps           +5.5%   (PFF excludes plays nullified by penalty)
    targets         +3.9%   (PFF declines to credit some throws the official
                             feed marks "intended for" a receiver)
    end zone tgts   +5.6%
    inside-5 rush   +3.3%

Checked directly: all 25 of Malik Nabers' official targets in wk1-2 are real
passes thrown at him; FL says 22. That is a definitional difference, not an
error, and no filter reconciles it. Take every counting stat from ONE basis.

What this CAN'T produce
-----------------------
    routes, routes_pct, tprr   -- needs per-play route charting
    two_min/sdd/ldd snaps      -- needs per-play personnel; nflverse
                                  participation data is post-season only
    catchable_tgts             -- a charting judgment

Those stay FL-only. Everything else here is official-basis and internally
consistent.

Usage:
    python fetch_nflverse_utilization.py --year 2026 --weeks 1-1
    python fetch_nflverse_utilization.py --year 2025 --weeks 1-2 --compare
"""

import argparse
import collections
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cached" / "nflverse"

REL = "https://github.com/nflverse/nflverse-data/releases/download"
SOURCES = {
    "snaps": REL + "/snap_counts/snap_counts_{year}.csv",
    "pbp": REL + "/pbp/play_by_play_{year}.csv",
    "players": REL + "/players/players.csv",
    "rosters": REL + "/weekly_rosters/roster_weekly_{year}.csv",
    "games": "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
}

# GSIS gamebooks: the league's own PDFs, one per game, publicly reachable with
# no credential.
#
# They are NOT a faster snap source, despite appearances. The PDF is posted
# right after the game, but the "Playtime Percentage" section is added LATER --
# measured Monday morning of week 1 2026, all 15 played games had a downloadable
# gamebook but only 3 contained a Playtime section (the two pre-Sunday games
# plus one Sunday game). nflverse/PFR had 2 of 15 over the same window. Both
# wait on the same official participation report.
#
# Keep both anyway: whichever fills in first wins, and they agree once present
# (325/328 exact on 2025 week 1). File existence != data presence -- check for
# the section, never just the HTTP 200.
GAMEBOOK = "https://www.nflgsis.com/{year}/reg/{week:02d}/{gsis}/Gamebook.pdf"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

POSITIONS = ("RB", "WR", "TE")
# nflverse uses LA/LAR and JAX; FL uses LA and JAC. Normalise to FL's spelling
# so the two outputs can be diffed and the grid's team filter matches.
TEAM_FIX = {"LAR": "LA", "JAX": "JAC"}

csv.field_size_limit(10 ** 7)


def fetch(kind, year, refresh=False):
    url = SOURCES[kind].format(year=year)
    dest = CACHE / f"{kind}_{year}.csv" if "{year}" in SOURCES[kind] \
        else CACHE / f"{kind}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not refresh:
        return dest
    print(f"  downloading {kind}...", end="", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    dest.write_bytes(data)
    print(f" {len(data)/1024/1024:.1f} MB")
    return dest


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# --- GSIS gamebook snaps ---------------------------------------------------
# Offensive rows put the percentage BEFORE the snap count ("G.Pickens 92%56WR");
# defensive rows reverse it ("K.Elam 63 100% 5 23%CB"). That ordering is what
# tells the two blocks apart, so the regex anchors on `pct%snaps`.
#
# The trailing lookahead must be (?=\D|$), NOT \b. A player with no special
# teams snaps runs the position straight onto the count -- "92%56WR" -- and
# there is no word boundary between "6" and "W", so \b silently dropped every
# offense-only player and kept only those who also played special teams.
OFF_ROW = re.compile(r"^([A-Z][A-Za-z'\-\.]+)\s+(\d+)%(\d+)(?=\D|$)")


def norm_pos(pos):
    """Gamebook positions are granular and inconsistent; nflverse is coarser.
    Only the skill positions need to agree, so collapse to those.

    Surveyed every offensive row across all of 2026 week 1: WR, TE, RB, T, OL,
    G, QB, C, FB, C/G, G/T, T/G, HB, K, CB, RB/, G/C, DB. The backfield is
    spelled THREE ways -- RB, HB and FB -- and "HB" cost Chase Brown (46 snaps,
    16 carries) his entire snap count until this map covered it. Splitting on
    "/" handles C/G and the truncated RB/.
    """
    p = (pos or "").upper().split("/")[0].strip()
    if p in ("FB", "HB"):
        return "RB"
    return p if p in POSITIONS else ""


def split_name(name):
    """-> (first-name prefix as written, surname) or None."""
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"\b(Jr|Sr|II|III|IV|V)\.?\b", "", name, flags=re.I)
    parts = [p for p in re.split(r"[.\s]+", name.strip()) if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[-1].lower()


def short_key(name, team, pos=""):
    """Group key: team + surname + position. The first name is NOT in the key
    -- it is matched separately as a prefix, because gamebooks abbreviate it to
    a VARIABLE length.

    Two collisions forced this, both real in 2026 week 1:
      * MIN had Justin Jefferson (WR) and Jermar Jefferson (RB). Keying on
        initial alone matched both; position separates them.
      * ATL had Bijan and Brian Robinson, BOTH RB. Position can't separate
        those -- but the gamebook already does, writing "Bi.Robinson" and
        "Br.Robinson". Taking only the first character collapsed them and
        Brian's 15 snaps overwrote Bijan's 46.
    """
    sp = split_name(name)
    if not sp:
        return None
    return (TEAM_FIX.get(team, team), sp[1], norm_pos(pos))


def match_prefix(entries, first_name):
    """entries: {prefix: value} from the gamebook. Pick the entry whose
    abbreviated first name prefixes this player's, longest match wins, so
    'Br' beats 'B' for Brian. Returns None if nothing matches."""
    best, best_len = None, -1
    low = (first_name or "").lower()
    for prefix, val in entries.items():
        p = prefix.lower()
        if low.startswith(p) and len(p) > best_len:
            best, best_len = val, len(p)
    return best


def gamebook_snaps(year, week, gsis, away, home, refresh=False):
    """-> {(team, initial, surname): offensive snaps} for one game."""
    from pypdf import PdfReader

    dest = CACHE / "gamebooks" / f"{year}_w{week:02d}_{gsis}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or refresh:
        url = GAMEBOOK.format(year=year, week=week, gsis=gsis)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as r:
            dest.write_bytes(r.read())
        time.sleep(0.8)

    text = ""
    for page in PdfReader(str(dest)).pages:
        t = page.extract_text() or ""
        if "Playtime" in t or text:
            text += t + "\n"

    out, block = {}, -1
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Offense Defense Special Teams"):
            block += 1
            continue
        m = OFF_ROW.match(line)
        if m and block >= 0:
            # Position is the trailing token: "J.Jefferson 92%60WR" -> WR,
            # "K.Turpin 46%28 8 36%WR" -> WR, "C.Jurgens 100%63C/G" -> C/G.
            pm = re.search(r"([A-Z][A-Za-z/]*)\s*$", line)
            team = (away, home)[min(block, 1)]
            k = short_key(m.group(1), team, pm.group(1) if pm else "")
            sp = split_name(m.group(1))
            if k and sp:
                out.setdefault(k, {})[sp[0]] = (int(m.group(3)),
                                                float(m.group(2)))
    return out


def collect_gamebook_snaps(year, wmin, wmax, refresh=False):
    """-> ({(team,init,surname): (snaps, pct)}, n_games_ok, n_games_failed)"""
    games_path = fetch("games", year, refresh=False)
    with open(games_path, encoding="utf-8") as fh:
        games = [g for g in csv.DictReader(fh)
                 if g["season"] == str(year) and g["game_type"] == "REG"
                 and g["gsis"] and wmin <= int(num(g["week"])) <= wmax]

    snaps, ok, bad = {}, 0, 0
    for g in games:
        try:
            snaps.update(gamebook_snaps(year, int(num(g["week"])), g["gsis"],
                                        g["away_team"], g["home_team"], refresh))
            ok += 1
        except Exception as exc:
            bad += 1
            print(f"    gamebook {g['away_team']}@{g['home_team']} "
                  f"(gsis {g['gsis']}): {exc}")
    return snaps, ok, bad


def coverage(year, wmin, wmax):
    """How many games have snap data yet, from each source?

    Snaps are the slow column -- everything play-derived is available the same
    day, but both the gamebook Playtime section and PFR's snap counts wait on
    the official participation report, and fill in per game over a day or
    three. Run this before publishing rather than assuming.
    """
    import io
    from pypdf import PdfReader

    games_path = fetch("games", year)
    with open(games_path, encoding="utf-8") as fh:
        games = [g for g in csv.DictReader(fh)
                 if g["season"] == str(year) and g["game_type"] == "REG"
                 and g["gsis"] and wmin <= int(num(g["week"])) <= wmax]

    snaps_path = fetch("snaps", year, refresh=True)
    with open(snaps_path, encoding="utf-8") as fh:
        pfr_games = {r["game_id"] for r in csv.DictReader(fh)
                     if wmin <= int(num(r["week"])) <= wmax}

    print(f"{'date':<12}{'game':<12}{'gamebook':<11}{'pfr'}")
    gb_ok = pfr_ok = posted = 0
    for g in games:
        wk = int(num(g["week"]))
        url = GAMEBOOK.format(year=year, week=wk, gsis=g["gsis"])
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            data = urllib.request.urlopen(req, timeout=60).read()
            has = any("Playtime" in (pg.extract_text() or "")
                      for pg in PdfReader(io.BytesIO(data)).pages)
            posted += 1
        except Exception:
            has = None
        gid = f"{year}_{wk:02d}_{g['away_team']}_{g['home_team']}"
        in_pfr = gid in pfr_games
        gb_ok += bool(has)
        pfr_ok += in_pfr
        label = "not posted" if has is None else ("YES" if has else "-")
        print(f"{g['gameday']:<12}{g['away_team']+'@'+g['home_team']:<12}"
              f"{label:<11}{'YES' if in_pfr else '-'}")
        time.sleep(0.5)

    print("")
    print(f"snaps available: gamebook {gb_ok}/{posted} posted games, "
          f"pfr {pfr_ok}/{posted}")
    print("play-derived columns (targets, rush, ez, i5, adot) do not wait on "
          "this -- they are ready same-day from pbp.")


def build(year, wmin, wmax, use_cache=False, snap_source="auto"):
    # players/snaps/pbp/rosters are one file per season, overwritten in place
    # on each download -- so "cached" doesn't mean "this week's data", it means
    # "whatever the last run happened to catch". A real run always needs the
    # current file: pbp in particular is what MNF-vs-cached-Monday-afternoon
    # bug was. use_cache is for fast local iteration on the merge logic only
    # -- never pass it for an actual weekly refresh.
    refresh = not use_cache
    players_path = fetch("players", year, refresh)
    snaps_path = fetch("snaps", year, refresh)
    pbp_path = fetch("pbp", year, refresh)

    # snap_counts is keyed by pfr id, pbp by gsis id -- players.csv bridges them.
    pfr_to_gsis, gsis_name, gsis_pos = {}, {}, {}
    with open(players_path, encoding="utf-8") as fh:
        for p in csv.DictReader(fh):
            g = p.get("gsis_id")
            if not g:
                continue
            if p.get("pfr_id"):
                pfr_to_gsis[p["pfr_id"]] = g
            gsis_name[g] = (p.get("display_name") or "").strip()
            gsis_pos[g] = (p.get("position") or "").strip()

    # --- snaps -------------------------------------------------------------
    snaps = {}
    with open(snaps_path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] != str(year) or r["game_type"] != "REG":
                continue
            wk = int(num(r["week"]))
            if not wmin <= wk <= wmax:
                continue
            if r["position"] not in POSITIONS:
                continue
            gid = pfr_to_gsis.get(r["pfr_player_id"])
            if not gid:
                continue
            team = TEAM_FIX.get(r["team"], r["team"])
            snaps[(gid, wk)] = {
                "team": team,
                "pos": r["position"],
                "player": r["player"],
                "snaps": int(num(r["offense_snaps"])),
                # offense_pct arrives as a 0-1 float
                "snaps_pct": round(num(r["offense_pct"]) * 100, 1),
            }

    # --- gamebook snaps (timely) overlay the PFR-sourced ones (slow) -------
    # Keyed by name because gamebooks carry no player ids; the weekly roster
    # bridges short name -> gsis id.
    if snap_source in ("auto", "gsis"):
        print("  gamebook snaps...", end="", flush=True)
        gb, ok, bad = collect_gamebook_snaps(year, wmin, wmax, refresh)
        print(f" {ok} games ok, {bad} failed, {len(gb)} player entries")

        roster_path = fetch("rosters", year, refresh)
        name_to_gsis = {}
        with open(roster_path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("season") != str(year) or not r.get("gsis_id"):
                    continue
                wk = int(num(r.get("week")))
                if not wmin <= wk <= wmax:
                    continue
                full = r.get("full_name") or ""
                k = short_key(full, r.get("team") or "", r.get("position") or "")
                sp = split_name(full)
                if k and sp:
                    # keyed by gsis id so two players sharing a key both survive
                    name_to_gsis[(r["gsis_id"], wk)] = (
                        k, sp[0], r.get("position") or "",
                        TEAM_FIX.get(r["team"], r["team"]), full)

        added = replaced = ambiguous = 0
        for (gid, wk), (key_, first, pos, team, full) in name_to_gsis.items():
            if pos not in POSITIONS:
                continue
            entries = gb.get(key_)
            if not entries:
                continue
            hit = match_prefix(entries, first)
            if hit is None:
                ambiguous += 1
                continue
            n, pct = hit
            if (gid, wk) in snaps:
                snaps[(gid, wk)]["snaps"] = n
                snaps[(gid, wk)]["snaps_pct"] = round(pct, 1)
                replaced += 1
            else:
                snaps[(gid, wk)] = {"team": team, "pos": pos, "player": full,
                                    "snaps": n, "snaps_pct": round(pct, 1)}
                added += 1
        print(f"    -> {added} players added, {replaced} updated from gamebooks"
              + (f", {ambiguous} unmatched" if ambiguous else ""))

    # --- play-by-play derived stats ----------------------------------------
    stat = collections.defaultdict(collections.Counter)   # (gsis, wk) -> counters
    team_tot = collections.defaultdict(collections.Counter)  # (team, wk) -> counters
    air = collections.defaultdict(float)
    # A player can have pbp stats but no snap row (missed the gamebook match,
    # or PFR hasn't posted). Without this his team came out blank, which then
    # broke the team-total lookup and left every share at 0.
    pbp_team = {}

    with open(pbp_path, encoding="utf-8") as fh:
        for p in csv.DictReader(fh):
            if p["season_type"] != "REG":
                continue
            wk = int(num(p["week"]))
            if not wmin <= wk <= wmax:
                continue
            team = TEAM_FIX.get(p.get("posteam") or "", p.get("posteam") or "")
            if not team:
                continue
            y100 = num(p.get("yardline_100"), -1)

            if p.get("pass_attempt") == "1" and p.get("receiver_player_id"):
                rid = p["receiver_player_id"]
                k = (rid, wk)
                pbp_team.setdefault(k, team)
                stat[k]["targets"] += 1
                team_tot[(team, wk)]["targets"] += 1
                # Receptions are objective (caught or not), unlike targets (was
                # this really intended for him is a judgment call) -- sanity
                # checked against FL's catchable_tgts as a hard upper bound
                # (a completion can never exceed catchable targets): 0
                # violations across 270 players, 2025 wk1-2. Safe either basis.
                if p.get("complete_pass") == "1":
                    stat[k]["rec"] += 1
                ay = p.get("air_yards")
                if ay not in (None, "", "NA"):
                    air[k] += num(ay)
                    if y100 >= 0 and num(ay) >= y100:
                        stat[k]["ez_tgts"] += 1
                        team_tot[(team, wk)]["ez_tgts"] += 1

            if p.get("rush_attempt") == "1" and p.get("rusher_player_id"):
                rid = p["rusher_player_id"]
                k = (rid, wk)
                pbp_team.setdefault(k, team)
                stat[k]["rush_att"] += 1
                team_tot[(team, wk)]["rush_att"] += 1
                if 0 <= y100 <= 5:
                    stat[k]["inside5_rush"] += 1
                    team_tot[(team, wk)]["inside5_rush"] += 1

    # --- team snap totals, for snap share ----------------------------------
    # offense_pct is already per-team, so the denominator is recoverable as
    # snaps / pct -- but snap_counts gives pct directly, so just carry it.

    # --- merge -------------------------------------------------------------
    rows = []
    keys = set(snaps) | {k for k in stat if gsis_pos.get(k[0]) in POSITIONS}
    for gid, wk in sorted(keys, key=lambda k: k[1]):
        base = snaps.get((gid, wk))
        s = stat.get((gid, wk), collections.Counter())
        if base:
            team, pos, name = base["team"], base["pos"], base["player"]
        else:
            # played but recorded no offensive snap row (rare); fall back
            team = pbp_team.get((gid, wk), "")
            pos = gsis_pos.get(gid, "")
            name = gsis_name.get(gid, "")
            if pos not in POSITIONS:
                continue
        tt = team_tot.get((team, wk), collections.Counter())

        def share(n, d):
            return round(n / d * 100, 1) if d else 0.0

        row = {
            "player_id": gid,
            "player": gsis_name.get(gid) or name,
            "team": team,
            "pos": pos,
            "season": year,
            "week": wk,
            "snaps": base["snaps"] if base else 0,
            "snaps_pct": base["snaps_pct"] if base else 0.0,
            "rush_att": s["rush_att"],
            "rush_att_pct": share(s["rush_att"], tt["rush_att"]),
            "targets": s["targets"],
            "targets_pct": share(s["targets"], tt["targets"]),
            "rec": s["rec"],
            "ez_tgts": s["ez_tgts"],
            "ez_tgts_pct": share(s["ez_tgts"], tt["ez_tgts"]),
            "inside5_rush": s["inside5_rush"],
            "inside5_rush_pct": share(s["inside5_rush"], tt["inside5_rush"]),
            "adot": round(air[(gid, wk)] / s["targets"], 1) if s["targets"] else 0.0,
            # Summed air yards, so ADOT re-derives correctly over a week range.
            # Averaging weekly ADOT would weight a 1-target week like a 12.
            "air_yards_total": round(air[(gid, wk)], 1),
            # team denominators, so any week range re-aggregates exactly
            "team_targets": tt["targets"],
            "team_rush_att": tt["rush_att"],
            "team_ez_tgts": tt["ez_tgts"],
            "team_inside5_rush": tt["inside5_rush"],
        }
        rows.append(row)

    rows.sort(key=lambda r: (r["week"], -r["snaps"]))
    return rows


COLUMNS = ["player_id", "player", "team", "pos", "season", "week",
           "snaps", "snaps_pct", "rush_att", "rush_att_pct",
           "targets", "targets_pct", "rec", "ez_tgts", "ez_tgts_pct",
           "inside5_rush", "inside5_rush_pct", "adot", "air_yards_total",
           "team_targets", "team_rush_att", "team_ez_tgts", "team_inside5_rush"]


def write(outdir, rows, suffix):
    outdir.mkdir(parents=True, exist_ok=True)
    cpath = outdir / f"nflverse_weekly_{suffix}.csv"
    with open(cpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    jpath = outdir / "nflverse_weekly.json"
    payload = {"cols": COLUMNS, "rows": [[r.get(c) for c in COLUMNS] for r in rows]}
    jpath.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return cpath, jpath


def compare(rows, year, wmin, wmax):
    """Diff against the FL pull for the same weeks, if it exists."""
    fl_path = HERE / "data" / f"utilization_weekly_{year}_wk{wmin}-{wmax}.csv"
    if not fl_path.exists():
        print(f"\n(no FL file at {fl_path.name} to compare against)")
        return
    fl = {}
    with open(fl_path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            fl[(r["player"].lower(), int(r["week"]))] = r
    mine = {(r["player"].lower(), r["week"]): r for r in rows}
    both = [k for k in mine if k in fl]
    print(f"\n=== vs FantasyLife ({len(both)} matched player-weeks) ===")
    for col in ("snaps", "targets", "rush_att", "ez_tgts", "inside5_rush"):
        ex = sum(1 for k in both if int(num(mine[k][col])) == int(num(fl[k][col])))
        a = sum(int(num(mine[k][col])) for k in both)
        b = sum(int(num(fl[k][col])) for k in both)
        d = f"{100*(a-b)/b:+.1f}%" if b else "n/a"
        print(f"  {col:<14} {ex}/{len(both)} exact ({100*ex/len(both):>3.0f}%)   "
              f"nflverse {a:>5} vs FL {b:>5}  ({d})")
    print("\n  Differences are expected: official basis vs PFF basis. "
          "See this script's docstring.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-22")
    ap.add_argument("--use-cache", action="store_true",
                    help="reuse locally cached players/snaps/pbp/rosters files "
                         "instead of re-downloading -- faster for iterating on "
                         "merge logic locally, but NEVER use this for a real "
                         "weekly refresh: those files are one-per-season and "
                         "overwritten in place, so a stale cache silently "
                         "reports zero rush/targets/rec/EZ/ADOT for any game "
                         "newer than whenever the cache was last written "
                         "(this is what happened to the week 1 Monday game)")
    ap.add_argument("--snap-source", dest="snap_source",
                    choices=("auto", "gsis", "nflverse"), default="auto",
                    help="auto/gsis use GSIS gamebooks (timely); "
                         "nflverse uses PFR snap_counts (lags)")
    ap.add_argument("--coverage", action="store_true",
                    help="report which games have snap data yet, then exit")
    ap.add_argument("--compare", action="store_true",
                    help="diff against the FL pull for the same weeks")
    ap.add_argument("--outdir", default=str(HERE / "data"))
    args = ap.parse_args()

    if "-" in args.weeks:
        wmin, wmax = (int(x) for x in args.weeks.split("-", 1))
    else:
        wmin = wmax = int(args.weeks)

    print(f"nflverse utilization -- {args.year}, weeks {wmin}-{wmax}\n")

    if args.coverage:
        coverage(args.year, wmin, wmax)
        return 0

    rows = build(args.year, wmin, wmax, args.use_cache, args.snap_source)
    weeks = sorted({r["week"] for r in rows})
    print(f"\n{len(rows)} player-week rows, weeks present: {weeks}")

    suffix = f"{args.year}_wk{wmin}-{wmax}"
    cpath, jpath = write(Path(args.outdir), rows, suffix)
    print(f"  {cpath.name}  ({cpath.stat().st_size/1024:.0f} KB)")
    print(f"  {jpath.name}  ({jpath.stat().st_size/1024:.0f} KB)")

    if args.compare:
        compare(rows, args.year, wmin, wmax)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
