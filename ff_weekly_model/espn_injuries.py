#!/usr/bin/env python3
"""ESPN's live injury list -> automatic IR / suspension OUTs + flags for Joe (2026-11-24).

Joe 2026-11-24 ("yeah this week is going to be tricky with the crazy schedule"): Terrance Ferguson (IR,
McVay: not coming back) and J.K. Dobbins (suspended a game) were still projected because the official
report (nflverse) lagged a week and the ESPN news feed had nothing new. ESPN's injury list
(site.api.espn.com .../nfl/injuries -- the Rotowire-style blurbs) had both.

  fetch(year)        the list -> data/espn_injuries_<year>.json  {gsis: status, date, comment, ...}
  apply(year, week)  IR / Suspension -> OUT on the review sheet (never over START, never a team that has
                     kicked off); an OUT this module set is CLEARED again once ESPN drops the IR /
                     suspension (activated, reinstated). Out / Doubtful / Questionable are NOT applied:
                     before the game-day list they are not final (2026-11-15: A.J. Brown, McConkey
                     "Out" on ESPN, then played) -- they are listed for Joe on the Calls tab.

    python espn_injuries.py --year 2026 --week 12 [--dry-run]
"""
import argparse
import csv
import datetime
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
AUTO_OUT = ("Injured Reserve", "Suspension")
TAG = "auto (ESPN)"
TEAMS = {"WSH": "WAS", "LAR": "LA"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s))


def path(year):
    return os.path.join(DATA, f"espn_injuries_{year}.json")


def fetch(year, quiet=False):
    """-> {gsis: {...}} (also saved); None if ESPN could not be reached."""
    import requests
    import news
    try:
        d = requests.get(URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()
    except Exception as e:
        print(f"  WARN  ESPN injuries      not reached ({type(e).__name__}) -- using the last copy")
        return None
    ids = news.espn_to_gsis(year)
    # fallback by name + team from this season's player stats / review sheets
    by_name = {}
    sp = os.path.join(DATA, f"stats_player_week_{year}.csv")
    if os.path.exists(sp):
        for r in csv.DictReader(open(sp, encoding="utf-8")):
            by_name[(_norm(r["player_display_name"]), r["team"])] = r["player_id"]
    out = {}
    for t in d.get("injuries", []):
        for i in t.get("injuries", []):
            a = i.get("athlete") or {}
            pos = (a.get("position") or {}).get("abbreviation", "")
            if pos not in ("QB", "RB", "WR", "TE", "FB"):
                continue
            tm = TEAMS.get((a.get("team") or {}).get("abbreviation", ""), (a.get("team") or {}).get("abbreviation", ""))
            hit = ids.get(str(a.get("id", "")))
            gsis = hit[0] if hit else by_name.get((_norm(a.get("displayName")), tm))
            if not gsis:
                continue
            out[gsis] = {"player": a.get("displayName", ""), "team": tm or (hit[2] if hit else ""), "pos": pos,
                         "status": i.get("status", ""), "date": (i.get("date") or "")[:10],
                         "comment": (i.get("shortComment") or "").strip()}
    json.dump({"fetched": f"{datetime.datetime.now():%Y-%m-%d %H:%M}", "players": out},
              open(path(year), "w", encoding="utf-8"), indent=0)
    if not quiet:
        n = sum(1 for v in out.values() if v["status"] != "Active")
        print(f"  ok    ESPN injuries       {n} skill players listed ({sum(1 for v in out.values() if v['status'] in AUTO_OUT)} IR / suspended)")
    return out


def load(year):
    p = path(year)
    if not os.path.exists(p):
        return {}, ""
    d = json.load(open(p, encoding="utf-8"))
    return d.get("players", {}), d.get("fetched", "")


def apply(year, week, dry_run=False, fetch_first=True):
    """IR / suspended -> OUT; this module's OUTs cleared when ESPN drops them. -> list of changes."""
    inj = (fetch(year) if fetch_first else None) or load(year)[0]
    if not inj:
        return []
    sp = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    if not os.path.exists(sp):
        return []
    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))
    fields = list(rows[0].keys()) if rows else ["player_id", "player", "pos", "team", "decision", "note"]
    import score_week
    now = datetime.datetime.now()
    started = {tm for tm, k in score_week.kickoffs(year, week).items() if k <= now}
    playing = set(score_week.kickoffs(year, week))
    by = {r["player_id"]: r for r in rows}
    proj = {}
    pp = os.path.join(DATA, f"projections_{year}_wk{week:02d}_nocalls.csv")
    if not os.path.exists(pp):
        pp = os.path.join(DATA, f"projections_{year}_wk{week:02d}.csv")
    if os.path.exists(pp):
        proj = {r["player_id"]: r for r in csv.DictReader(open(pp, encoding="utf-8"))}
    changes = []
    for gsis, v in inj.items():
        r = by.get(gsis)
        tm = (r or {}).get("team") or (proj.get(gsis) or {}).get("team") or v["team"]
        if tm in started or tm not in playing:
            continue
        if v["status"] in AUTO_OUT:
            dec = (r or {}).get("decision", "").strip().upper()
            if dec in ("OUT", "START") or dec.startswith("CHANCE"):
                continue
            if r is None:
                if gsis not in proj:
                    continue                  # not projected anyway
                r = {k: "" for k in fields}
                r.update(player_id=gsis, player=v["player"], pos=v["pos"], team=tm, source="manual")
                rows.append(r)
                by[gsis] = r
            old = r.get("decision", "")
            r["decision"] = "OUT"
            r["note"] = (f"{TAG}: {v['status']} {v['date']} -- {v['comment'][:140]}"
                         + (f" | was {old}; {r.get('note', '')}" if old or r.get("note") else ""))[:400]
            changes.append(f"-> OUT  {v['player']} ({tm})  was {old or '(blank)'}   [{v['status']}: {v['comment'][:90]}]")
    # undo our own OUTs that ESPN no longer backs
    for r in rows:
        if r.get("decision", "").upper() == "OUT" and r.get("note", "").startswith(TAG) \
                and r.get("team") not in started and inj.get(r["player_id"], {}).get("status") not in AUTO_OUT:
            now_ = inj.get(r["player_id"], {}).get("status", "not listed")
            r["decision"] = ""
            r["note"] = f"{TAG} cleared {now:%m-%d}: ESPN now {now_} | " + r["note"].split(" | was ", 1)[-1][:200]
            changes.append(f"-> back {r['player']} ({r['team']})  OUT cleared [ESPN now {now_}]")
    if changes and not dry_run:
        tmp = sp + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows({k: r.get(k, "") for k in fields} for r in rows)
        os.replace(tmp, sp)
    for c in changes:
        print("  " + c)
    return changes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ch = apply(a.year, a.week, a.dry_run)
    print(f"  ESPN IR / suspensions: {len(ch)} change(s){' (dry run)' if a.dry_run else ''}")
