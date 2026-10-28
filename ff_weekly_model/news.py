#!/usr/bin/env python3
"""Player news from ESPN's public NFL news feed -> data/news_<year>.csv.

    python news.py --year 2026

Pulls the league feed and every team's feed (player-tagged headlines),
maps ESPN athlete ids to our gsis ids through the depth-chart file, and
appends anything new to data/news_<year>.csv (deduped by article + player).
Each item gets keyword TAGS -- OUT, DOUBTFUL, QUESTIONABLE, IR, PROTOCOL,
DNP, LIMITED, FULL_PRACTICE, RETURN, TRADE, SIGNED, STARTER, BENCHED -- so
the review sheet and the player log can show what matters at a glance.

News is information for Joe, never a model input: coach-speak is not
reliable and old news cannot be backtested. Nothing here changes a
projection unless Joe puts a call on the review sheet.
"""

import argparse
import csv
import datetime
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FEED = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
TEAMS = ["ari", "atl", "bal", "buf", "car", "chi", "cin", "cle", "dal", "den", "det",
         "gb", "hou", "ind", "jax", "kc", "lv", "lac", "lar", "mia", "min", "ne", "no",
         "nyg", "nyj", "phi", "pit", "sf", "sea", "tb", "ten", "wsh"]
FIELDS = ["published", "player_id", "player", "team", "pos", "tags", "headline",
          "description", "article_id", "link"]

TAG_RULES = [
    ("EXIT", r"\blose[sd]? (?:\w+ ){0,4}to (?:an? )?(?:\w+ )?injury\b|\bleft (?:the|sunday's|monday's|thursday's) game\b|\bexited\b|\bdid not return\b|\bdidn't return\b|\bknocked out of\b|\bcarted off\b|\bwill not return\b|\bwon't return\b"),
    ("OUT", r"\bruled out\b|\brules? (?:\w+ ){0,4}out\b|\bwill not play\b|\bwon't play\b|\bout (?:for|vs\.?|against|this|sunday|monday|thursday|week)\b|\bsidelined\b"),
    ("DOUBTFUL", r"\bdoubtful\b"),
    ("QUESTIONABLE", r"\bquestionable\b|\bgame-time decision\b|\bunsure if\b|\buncertain\b"),
    ("IR", r"\binjured reserve\b|\bplaced on ir\b|\bto ir\b|\bseason-ending\b"),
    ("PROTOCOL", r"\bconcussion\b|\bprotocol\b"),
    ("DNP", r"\bdid not practice\b|\bdidn't practice\b|\bmissed practice\b|\bsat out practice\b"),
    ("LIMITED", r"\blimited\b"),
    ("FULL_PRACTICE", r"\bfull practice\b|\bfull participant\b|\bpracticed fully\b|\bfully participated\b"),
    ("RETURN", r"\breturn(?:s|ing)?\b|\bactivated\b|\bcleared\b|\bback at practice\b|\bset to play\b|\bexpected to play\b"),
    ("TRADE", r"\btraded\b|\btrade\b|\bacquire[sd]?\b"),
    ("SIGNED", r"\bsigned\b|\belevated\b|\bpromoted\b|\bclaimed\b|\bwaived\b|\breleased\b"),
    ("STARTER", r"\bnamed (?:the )?starter\b|\bwill start\b|\bto start\b|\bgets? the start\b|\bstarting (?:qb|quarterback|rb|running back|role)\b|\bqb1\b"),
    ("BENCHED", r"\bbenched\b|\bdemoted\b|\breduced role\b|\bsnap count\b|\bpitch count\b"),
]


def tags_for(text):
    t = (text or "").lower()
    tags = [name for name, rx in TAG_RULES if re.search(rx, t)]
    # "won't rule out" / "not ruling him out" is the opposite of OUT (the
    # "rules out" pattern, 2026-10-24: "Ravens rule out Lamar Jackson" was missed)
    if "OUT" in tags and re.search(r"\b(?:won'?t|will not|not|can'?t|didn'?t|refused? to)\s+(?:\w+\s+)?rul", t) \
            and not re.search(r"\bruled out\b|\bwill not play\b|\bwon'?t play\b|\bsidelined\b", t):
        tags.remove("OUT")
    return tags


def tags_about(headline, description, last):
    """Tags for ONE player. A multi-item headline ("Week 6 inactives: Williams
    to play; Hurts, Jackson ruled out") is split on ';' and only the clause
    naming him counts -- otherwise Williams read as OUT."""
    h = headline or ""
    if last not in h.lower():
        return []
    if ";" in h:
        clause = next((c for c in h.split(";") if last in c.lower()), h)
        return tags_for(clause.split(":")[-1])
    return tags_for(f"{h}. {description or ''}")


def espn_to_gsis(year):
    """ESPN athlete id -> (gsis_id, name, team, pos) from the depth-chart files."""
    out = {}
    for y in (year - 1, year):
        for path in (os.path.join(DATA, f"depth_charts_{y}.csv"),
                     os.path.join(os.path.dirname(HERE), "ff_projections", "cached",
                                  "nflverse", f"depth_charts_{y}.csv")):
            if not os.path.exists(path):
                continue
            newest = {}
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if r.get("espn_id") and r.get("gsis_id"):
                        if r["dt"] >= newest.get(r["espn_id"], ""):
                            newest[r["espn_id"]] = r["dt"]     # newest snapshot = current team
                            out[r["espn_id"]] = (r["gsis_id"], r["player_name"], r["team"], r["pos_abb"])
            break
    return out


def et(iso):
    """'2026-10-15T22:42:00Z' -> '2026-10-15 18:42' (Eastern)."""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return iso or ""
    # EDT/EST by date (second Sunday of March .. first Sunday of November)
    y = dt.year
    start = datetime.datetime(y, 3, 8 + (6 - datetime.date(y, 3, 8).weekday()) % 7, 7,
                              tzinfo=datetime.timezone.utc)
    end = datetime.datetime(y, 11, 1 + (6 - datetime.date(y, 11, 1).weekday()) % 7, 6,
                            tzinfo=datetime.timezone.utc)
    off = -4 if start <= dt < end else -5
    return (dt + datetime.timedelta(hours=off)).strftime("%Y-%m-%d %H:%M")


def fetch(session, team=None, limit=50):
    params = {"limit": limit}
    if team:
        params["team"] = team
    r = session.get(FEED, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("articles", [])


def load(year):
    path = os.path.join(DATA, f"news_{year}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def update(year, quiet=False):
    """Pull every feed, append new player-tagged items. -> number added."""
    ids = espn_to_gsis(year)
    have = load(year)
    seen = {(r["article_id"], r["player_id"]) for r in have}
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    new = []
    for team in [None] + TEAMS:
        try:
            arts = fetch(session, team)
        except Exception as exc:
            print(f"  news: {team or 'league'} feed failed -- {type(exc).__name__}", file=sys.stderr)
            continue
        for a in arts:
            text = f"{a.get('headline', '')}. {a.get('description', '')}"
            for c in a.get("categories", []):
                if c.get("type") != "athlete":
                    continue
                eid = str(c.get("athleteId") or (c.get("athlete") or {}).get("id") or "")
                hit = ids.get(eid)
                if not hit:
                    continue
                gsis, name, tm, pos = hit
                if pos not in ("QB", "RB", "WR", "TE"):
                    continue
                key = (str(a.get("id")), gsis)
                if key in seen:
                    continue
                # tags only when the story is ABOUT him (his last name in the
                # headline); roundups that merely mention him get none
                last = (c.get("description") or name).split()[-1].lower().strip(".")
                if last in ("jr", "sr", "ii", "iii", "iv"):
                    last = (c.get("description") or name).split()[-2].lower()
                about = last in (a.get("headline") or "").lower()
                seen.add(key)
                new.append({"published": et(a.get("published")), "player_id": gsis,
                            "player": c.get("description") or name, "team": tm, "pos": pos,
                            "tags": " ".join(tags_about(a.get("headline"), a.get("description"), last)),
                            "headline": a.get("headline", ""),
                            "description": (a.get("description") or "").replace("\n", " "),
                            "article_id": key[0],
                            "link": ((a.get("links") or {}).get("web") or {}).get("href", "")})
        time.sleep(0.2)
    rows = sorted(have + new, key=lambda r: r["published"], reverse=True)
    with open(os.path.join(DATA, f"news_{year}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    if not quiet:
        print(f"  news: {len(new)} new player items ({len(rows)} total) -> news_{year}.csv")
    return len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()
    update(args.year)


if __name__ == "__main__":
    main()
