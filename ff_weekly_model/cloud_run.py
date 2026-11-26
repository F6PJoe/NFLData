#!/usr/bin/env python3
"""Run the weekly model on GitHub Actions (Joe 2026-11-24: "I can't keep my computer open all the
time ... we are going to have to push this to github").

The CODE is in this public repo; everything private -- Joe's calls (review sheets, the Review workbook,
team sheet, team moves, watch list), the news history, the site-projection archive and every output
(projections, rankings files, customer sheet) -- lives in the PRIVATE repo F6PJoe/NFLData-private,
checked out by the workflow into PRIVATE_DIR. Bulky PUBLIC data (nflverse play-by-play, rosters, depth
charts, past seasons' stats, Sleeper snapshots) is re-downloaded or kept in the Actions cache.

    python cloud_run.py gate      --private DIR   -> prints "lock", "refresh" or "skip" (and why)
    python cloud_run.py restore   --private DIR   private state -> working tree (+ ETR upload)
    python cloud_bootstrap        (cloud_run.py bootstrap)  download missing public history
    python cloud_run.py save      --private DIR   working tree -> private state
    python cloud_run.py mark      --private DIR --what lock|refresh   record a finished run

Times are US Eastern: the workflow sets TZ=America/New_York, the same clock the laptop uses.
"""
import argparse
import csv
import datetime
import fnmatch
import json
import os
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REL = "https://github.com/nflverse/nflverse-data/releases/download"

# --- what is PRIVATE STATE (relative to the FF_ADP root) ---------------------------------------
STATE_DIRS = ["ff_weekly_model/data", "ff_weekly_model/customer_sheets", "ff_weekly_model/site_rankings",
              "ff_weekly_proj/weekly"]
STATE_GLOBS = ["ff_weekly_model/F6P Week * Review.xlsx", "ff_weekly_model/F6P Week * Projections vs Consensus.xlsx",
               "ff_utilization/data/utilization_weekly_*.csv"]
# inside STATE_DIRS: bulky or re-downloadable -> never stored in the private repo
SKIP = ["ff_weekly_model/data/participation*", "ff_weekly_model/data/espn_hist*", "ff_weekly_model/data/_backup*",
        "ff_weekly_model/data/nfl_inactives*", "ff_weekly_model/data/exlist_cache*",
        "ff_weekly_model/data/depth_charts_*", "ff_weekly_model/data/roster_*",
        "ff_weekly_model/data/stats_player_week_*", "ff_weekly_model/data/games.csv",
        "ff_weekly_model/data/nflverse_weekly*", "ff_weekly_model/data/pbp_*", "*.bak*", "*.tmp", "*~$*"]

# --- public history the model reads that the daily refresh does not download -------------------
BOOTSTRAP = [
    ("ff_utilization/cached/nflverse/pbp_2025.csv", f"{REL}/pbp/play_by_play_2025.csv"),
    ("ff_utilization/cached/nflverse/snaps_2025.csv", f"{REL}/snap_counts/snap_counts_2025.csv"),
    ("ff_utilization/cached/nflverse/rosters_2025.csv", f"{REL}/weekly_rosters/roster_weekly_2025.csv"),
    ("ff_utilization/cached/nflverse/rosters_2026.csv", f"{REL}/weekly_rosters/roster_weekly_2026.csv"),
    ("ff_utilization/cached/nflverse/players.csv", f"{REL}/players/players.csv"),
    ("ff_projections/cached/nflverse/depth_charts_2025.csv", f"{REL}/depth_charts/depth_charts_2025.csv"),
    ("ff_weekly_model/data/depth_charts_2026.csv", f"{REL}/depth_charts/depth_charts_2026.csv"),
    ("ff_weekly_model/data/games.csv", "https://github.com/nflverse/nfldata/raw/master/data/games.csv"),
] + [(f"ff_weekly_model/data/stats_player_week_{y}.csv", f"{REL}/stats_player/stats_player_week_{y}.csv")
     for y in range(2021, 2027)]

LOCK_BEFORE = (55, 85)     # minutes before a kickoff when a lock runs (game-day inactives post at 90)
REFRESH_AT = (9, 0, 10, 30)  # morning refresh window, ET (h, m, h, m)
RUNS_FILE = "cloud_runs.json"


def _skipped(rel):
    """rel or any of its parent folders matches a SKIP pattern."""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    cands = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    return any(fnmatch.fnmatch(c, p) for c in cands for p in SKIP) or         any(fnmatch.fnmatch(parts[-1], p) for p in SKIP if "/" not in p)


def state_files(base):
    """relative paths of every state file under base (the working tree or the private state dir)."""
    import glob
    out = set()
    for d in STATE_DIRS:
        for dp, _, fs in os.walk(os.path.join(base, d)):
            for f in fs:
                rel = os.path.relpath(os.path.join(dp, f), base).replace("\\", "/")
                if not _skipped(rel):
                    out.add(rel)
    for g in STATE_GLOBS:
        for p in glob.glob(os.path.join(base, g)):
            out.add(os.path.relpath(p, base).replace("\\", "/"))
    return sorted(out)


def copy_tree(src_base, dst_base, rels):
    n = 0
    for rel in rels:
        s, d = os.path.join(src_base, rel), os.path.join(dst_base, rel)
        if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
            with open(s, "rb") as a, open(d, "rb") as b:
                if a.read() == b.read():
                    continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        n += 1
    return n


def restore(private):
    st = os.path.join(private, "state")
    n = copy_tree(st, ROOT, state_files(st)) if os.path.isdir(st) else 0
    print(f"  restored {n} private file(s) into the working tree")
    # ETR uploads: private/etr/<yr>-wk<NN>.csv -> ff_weekly_proj/weekly/<yr>-wk<NN>/etr.csv
    ed = os.path.join(private, "etr")
    if os.path.isdir(ed):
        for f in sorted(os.listdir(ed)):
            if f.endswith(".csv"):
                dst = os.path.join(ROOT, "ff_weekly_proj", "weekly", f[:-4], "etr.csv")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(ed, f), dst)
                print(f"  ETR: {f} -> ff_weekly_proj/weekly/{f[:-4]}/etr.csv")


def save(private):
    st = os.path.join(private, "state")
    n = copy_tree(ROOT, st, state_files(ROOT))
    print(f"  saved {n} changed file(s) to the private repo")


def bootstrap(only=None):
    for rel, url in BOOTSTRAP:
        if only and not rel.endswith(only):
            continue
        dst = os.path.join(ROOT, rel)
        if os.path.exists(dst) and os.path.getsize(dst) > 1000:
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        print(f"  downloading {rel} ...", flush=True)
        tmp = dst + ".tmp"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as fh:
            shutil.copyfileobj(r, fh)
        os.replace(tmp, dst)


def _runs(private):
    p = os.path.join(private, RUNS_FILE)
    return json.load(open(p)) if os.path.exists(p) else {}


def kickoffs():
    """[kickoff datetime (ET, naive)] for this season's regular-season games."""
    path = os.path.join(ROOT, "ff_weekly_model", "data", "games.csv")
    out = []
    if not os.path.exists(path):
        return out
    now = datetime.datetime.now()
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["season"] != str(now.year - (now.month < 3)) or not r.get("gameday"):
            continue
        k = datetime.datetime.strptime(f"{r['gameday']} {r.get('gametime') or '13:00'}", "%Y-%m-%d %H:%M")
        out.append((k, int(r["week"])))
    return out


def gate(private, force=None):
    """lock if a kickoff is LOCK_BEFORE minutes away and that kickoff has no lock yet;
    refresh in the morning window once a day; else skip."""
    if force:
        print(force)
        return
    now = datetime.datetime.now()
    runs = _runs(private)
    for k, wk in sorted(set(kickoffs())):
        mins = (k - now).total_seconds() / 60
        key = f"lock {k:%Y-%m-%d %H:%M}"
        if LOCK_BEFORE[0] <= mins <= LOCK_BEFORE[1] and key not in runs:
            print(f"lock {wk} {k:%Y-%m-%d %H:%M}")
            return
    h1, m1, h2, m2 = REFRESH_AT
    in_season = any(0 < (k - now).total_seconds() < 8 * 86400 for k, _ in kickoffs())
    if datetime.time(h1, m1) <= now.time() <= datetime.time(h2, m2) and f"refresh {now:%Y-%m-%d}" not in runs:
        # only in season: a game within the next 8 days
        if in_season:
            print("refresh")
            return
    if not in_season:
        print("skip")
        return
    # Joe 2026-11-25: "it needs to recognize any changes to the sheet everytime. it should be looking for
    # updated injury news more often than that too incase I miss something"
    try:
        why = calls_changed(private)
        if why:
            print(f"refresh calls -- {why}")
            return
    except Exception as e:
        print(f"  (calls check skipped: {type(e).__name__}: {str(e)[:100]})", file=sys.stderr)
    last = max((v for k_, v in runs.items() if k_.startswith(("refresh", "lock"))), default="")
    if last and (now - datetime.datetime.strptime(last, "%Y-%m-%d %H:%M")).total_seconds() < NEWS_COOLDOWN * 60:
        print("skip")
        return
    try:
        why = news_changed(private)
        if why:
            print(f"refresh news -- {why}")
            return
    except Exception as e:
        print(f"  (news check skipped: {type(e).__name__}: {str(e)[:100]})", file=sys.stderr)
    print("skip")


NEWS_COOLDOWN = 20     # minutes between news-triggered refreshes
NEWS_MIN_PTS = 2.0     # a status change matters for players projected this many half-PPR points


def calls_changed(private):
    """the Google Sheet's calls differ from the ones the last run read -> a short description, else ''."""
    sys.path.insert(0, HERE)
    import calls_gsheet as cg
    st_path = os.path.join(private, "state", "ff_weekly_model", "data", "calls_gsheet_state.json")
    conf_path = os.path.join(private, "state", "ff_weekly_model", "data", "calls_gsheet.json")
    if not (os.path.exists(st_path) and os.path.exists(conf_path)):
        return ""
    st, conf = json.load(open(st_path)), json.load(open(conf_path))
    y, w = week_now()
    if st.get("week") != [y, w]:
        return ""                     # the sheet still holds last week; the new week's first run rebuilds it
    tmp = os.path.join(os.environ.get("RUNNER_TEMP", HERE), "gate_calls.xlsx")
    cg.CONF = conf_path
    cg._export(conf["id"], tmp)
    fp = cg._calls(y, w, tmp)
    return "your calls changed on the Google Sheet" if fp != st.get("read_calls") else ""


def news_changed(private):
    """ESPN's injury list has a new / changed status for a projected player -> description, else ''."""
    import re
    import unicodedata
    import requests
    nm = lambda s: re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "",
                          unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()))
    y, w = week_now()
    data = os.path.join(private, "state", "ff_weekly_model", "data")
    saved_p = os.path.join(data, f"espn_injuries_{y}.json")
    proj_p = os.path.join(data, f"projections_{y}_wk{w:02d}.csv")
    if not (os.path.exists(saved_p) and os.path.exists(proj_p)):
        return ""
    proj = {}
    for r in csv.DictReader(open(proj_p, encoding="utf-8")):
        try:
            if float(r["half_ppr"]) >= NEWS_MIN_PTS:
                proj[(nm(r["player"]), r["team"])] = r["player"]
        except ValueError:
            pass
    old = {(nm(v["player"]), v["team"]): v["status"] for v in json.load(open(saved_p)).get("players", {}).values()}
    d = requests.get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"}).json()
    teams = {"WSH": "WAS", "LAR": "LA"}
    started = {tm for tm, k in _team_kickoffs(y, w).items() if k <= datetime.datetime.now()}
    hits = []
    for t in d.get("injuries", []):
        for i in t.get("injuries", []):
            a = i.get("athlete") or {}
            tm = teams.get((a.get("team") or {}).get("abbreviation", ""), (a.get("team") or {}).get("abbreviation", ""))
            key = (nm(a.get("displayName")), tm)
            if key in proj and tm not in started and old.get(key, "Active") != i.get("status", ""):
                hits.append(f"{proj[key]} {old.get(key, 'not listed')} -> {i.get('status')}")
    return "; ".join(hits[:4])


def _team_kickoffs(y, w):
    out = {}
    path = os.path.join(ROOT, "ff_weekly_model", "data", "games.csv")
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r["season"] == str(y) and r["week"] == str(w) and r.get("gameday"):
            k = datetime.datetime.strptime(f"{r['gameday']} {r.get('gametime') or '13:00'}", "%Y-%m-%d %H:%M")
            out[r["home_team"]] = out[r["away_team"]] = k
    return out


def mark(private, what, key):
    runs = _runs(private)
    runs[f"{what} {key}"] = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    # keep the file small: drop entries older than 21 days
    cut = f"{datetime.date.today() - datetime.timedelta(days=21):%Y-%m-%d}"
    runs = {k: v for k, v in runs.items() if v >= cut}
    json.dump(runs, open(os.path.join(private, RUNS_FILE), "w"), indent=1, sort_keys=True)


def week_now():
    """(season, week): the earliest week with a game not yet over (same rule as ff_weekly_proj)."""
    now = datetime.datetime.now()
    last = {}
    for k, wk in kickoffs():
        last[wk] = max(last.get(wk, k), k)
    live = [wk for wk, k in last.items() if k + datetime.timedelta(hours=4) > now]
    return now.year - (now.month < 3), (min(live) if live else max(last))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gate", "restore", "save", "bootstrap", "mark", "week"])
    ap.add_argument("--private")
    ap.add_argument("--what")
    ap.add_argument("--key", default="")
    ap.add_argument("--force")
    ap.add_argument("--only")
    a = ap.parse_args()
    if a.cmd == "gate":
        gate(a.private, a.force)
    elif a.cmd == "restore":
        restore(a.private)
    elif a.cmd == "save":
        save(a.private)
    elif a.cmd == "bootstrap":
        bootstrap(a.only)
    elif a.cmd == "mark":
        mark(a.private, a.what, a.key or f"{datetime.datetime.now():%Y-%m-%d}")
    elif a.cmd == "week":
        y, w = week_now()
        print(y, w)


if __name__ == "__main__":
    main()
