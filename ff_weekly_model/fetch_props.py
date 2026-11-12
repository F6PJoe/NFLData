#!/usr/bin/env python3
"""Snapshot NFL player prop lines from The Odds API.

    python fetch_props.py                      full pull: every game this week not yet started
    python fetch_props.py --mode early         same, but only if the credit budget allows (see below)
    python fetch_props.py --mode pregame       only games kicking off in the next --within minutes
                                               (default 75) that have no pregame pull yet
    [--year 2026 --week 9]                     default: the week of the next game in games.csv

Joe 2026-11-05: "pull this week's props". Then: "for now, early pulls and then before each set of
games is fine" (live, he'll want pulls all day as injury news hits). Props are a benchmark / future
blend input (see TESTED_SETTINGS.md), never copied as-is. Each pull saves:
  data/props/<yr>_wk<NN>_<YYYYmmdd_HHMM>[_pre].json   raw responses, one per game
  data/props/<yr>_wk<NN>_<YYYYmmdd_HHMM>[_pre].csv    flat: game, book, market, player, side, line, price
  data/props/pull_log.txt                             one line per run
Cost: 1 credit per market returned per game (6 markets -> ~6 a game, ~90 a full week). Listing the
games is free, so a pregame run with nothing due costs nothing.

Budget (free key, 500 a month): pregame pulls come first. An --mode early pull runs only if the
credits left cover it AND every game still to come this month at ~6 apiece.

Keys: ODDS_API_KEY, ODDS_API_KEY_2, ... from ff_weekly_model/.env, else ff_projections/.env; the
first one with enough credits is used. Only the FREE key belongs here -- the paid plan is
reserved for another product (Joe 2026-11-05).
"""
import argparse, csv, datetime, glob, json, os, time, urllib.request, zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "props")
BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
MARKETS = ("player_pass_yds", "player_pass_tds", "player_rush_yds", "player_reception_yds",
           "player_receptions", "player_anytime_td")
PER_GAME = 6
ET = zoneinfo.ZoneInfo("America/New_York")                # games.csv kickoff times are ET


def keys():
    out = []
    for p in (os.path.join(HERE, ".env"), os.path.join(os.path.dirname(HERE), "ff_projections", ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                k, _, v = line.strip().partition("=")
                v = v.strip().strip('"').strip("'")
                if k.startswith("ODDS_API_KEY") and v and v not in out:
                    out.append(v)
    if not out:
        raise SystemExit("no ODDS_API_KEY")
    return out


def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ff-weekly-model"}), timeout=30)
    return json.loads(r.read()), int(r.headers.get("x-requests-remaining") or 0)


def schedule():
    """[(season, week, kickoff datetime)] for regular-season games from games.csv."""
    out = []
    with open(os.path.join(HERE, "data", "games.csv"), newline="", encoding="utf-8") as fh:
        for g in csv.DictReader(fh):
            if g["game_type"] == "REG" and g["gameday"]:
                t = datetime.datetime.fromisoformat(f"{g['gameday']} {g['gametime'] or '13:00'}").replace(tzinfo=ET)
                out.append((int(g["season"]), int(g["week"]), t))
    return out


def log(msg):
    os.makedirs(OUT, exist_ok=True)
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(" ", msg)
    open(os.path.join(OUT, "pull_log.txt"), "a", encoding="utf-8").write(line + "\n")


def pregame_done(year, week):
    """game names already pulled in a pregame snapshot."""
    done = set()
    for p in glob.glob(os.path.join(OUT, f"{year}_wk{week:02d}_*_pre.csv")):
        for r in csv.DictReader(open(p, encoding="utf-8")):
            done.add(r["game"])
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--mode", choices=("full", "early", "pregame"), default="full")
    ap.add_argument("--within", type=int, default=75, help="pregame: minutes before kickoff")
    ap.add_argument("--markets", default=",".join(MARKETS))
    a = ap.parse_args()
    now = datetime.datetime.now(datetime.timezone.utc)
    sched = schedule()
    if a.week is None:
        nxt = min((s for s in sched if s[2] > now - datetime.timedelta(hours=4)), key=lambda s: s[2], default=None)
        if nxt is None:
            return log("no games left in games.csv")
        a.year, a.week = nxt[0], nxt[1]
    elif a.year is None:
        a.year = now.year
    days = [t for s, w, t in sched if s == a.year and w == a.week]
    d0, d1 = min(days).date().isoformat(), max(days).date().isoformat()

    ks = keys()
    events, left = get(f"{BASE}/events?apiKey={ks[0]}")                      # free call
    todo = []
    done = pregame_done(a.year, a.week) if a.mode == "pregame" else set()
    for e in events:
        t = datetime.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        if not (d0 <= t.astimezone(ET).date().isoformat() <= d1) or t <= now:
            continue
        name = f"{e['away_team']} @ {e['home_team']}"
        if a.mode == "pregame" and (t - now > datetime.timedelta(minutes=a.within) or name in done):
            continue
        todo.append(e)
    if not todo:
        if a.mode != "pregame":
            log(f"wk{a.week} {a.mode}: no games to pull")
        return
    need = PER_GAME * len(todo)

    # pick a key with credits (listing is free, so checking each costs nothing)
    key, left = None, 0
    for k in ks:
        _, rem = get(f"{BASE}/events?apiKey={k}")
        if rem >= need:
            key, left = k, rem
            break
        left = max(left, rem)
    if key is None:
        return log(f"wk{a.week} {a.mode}: SKIPPED -- {len(todo)} games need ~{need} credits, {left} left")
    if a.mode == "early":
        # keep enough for a pregame pull of every game still to come this month
        mend = (now.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
        reserve = PER_GAME * sum(1 for s, w, t in sched if now < t < mend)
        total_left = sum(get(f"{BASE}/events?apiKey={k}")[1] for k in ks)
        if total_left - need < reserve:
            return log(f"wk{a.week} early: SKIPPED -- {total_left} credits left, pregame pulls through month end "
                       f"need ~{reserve}, this pull ~{need}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    base = os.path.join(OUT, f"{a.year}_wk{a.week:02d}_{stamp}" + ("_pre" if a.mode == "pregame" else ""))
    raw, rows = [], []
    for e in todo:
        od, left = get(f"{BASE}/events/{e['id']}/odds?apiKey={key}&regions=us&markets={a.markets}&oddsFormat=american")
        raw.append(od)
        for b in od.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    rows.append({"game": f"{e['away_team']} @ {e['home_team']}", "commence": e["commence_time"],
                                 "book": b["key"], "market": m["key"], "player": o.get("description", ""),
                                 "side": o["name"], "line": o.get("point", ""), "price": o["price"]})
        time.sleep(0.5)
    json.dump(raw, open(base + ".json", "w", encoding="utf-8"))
    with open(base + ".csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["game", "commence", "book", "market", "player", "side", "line", "price"])
        w.writeheader(); w.writerows(rows)
    log(f"wk{a.week} {a.mode}: {len(todo)} games, {len(rows)} prices -> {os.path.basename(base)}.csv; "
        f"credits left {left}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                       # scheduled runs have no console -- keep the error
        log(f"ERROR {type(e).__name__}: {e}")
        raise
