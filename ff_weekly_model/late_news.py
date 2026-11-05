#!/usr/bin/env python3
"""Last-minute inactives check, run right before every lock.

    python late_news.py --year 2026 --week 6

First rebuilds the whole status sheet (refresh_inputs.refresh_sheet: official
report, Sleeper, news, practice -- every call kept; skipped loudly if the
sheet is open in Excel). Then looks for any player
Joe has PLAYING on the review sheet (play, full, a number, or blank) who has
since been ruled OUT -- a Sleeper status of Out / Doubtful / IR / Sus / NA, or
a news item ABOUT him tagged OUT or IR, published after the sheet was last
saved (or within --hours, default 6). Those rows are switched to OUT, with
the reason in `note`, and listed.

Built 2026-10-18 (Joe: "are you able to look up the last second injury news
without me updating?"). Only ever turns a player OFF, never on; a player
Joe already has OUT is left alone. Teams that have kicked off are skipped.
"""

import argparse
import collections
import csv
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import availability   # noqa: E402
import news           # noqa: E402
import refresh_inputs # noqa: E402
import score_week     # noqa: E402

GONE = availability.BLOCKING_REPORT | availability.SLEEPER_BLOCKING
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"


def official_inactives(year, week, started):
    """The OFFICIAL game-day inactives (filed 90 min before kickoff), from ESPN's
    game feed. -> ({gsis: (name, team)} inactive, {team} whose list is posted)."""
    import requests
    ids = news.espn_to_gsis(year)
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    # POSTED = the team has game-day INACTIVE entries (or 5+ outs -- a Friday
    # report rarely has that many). 2026-11-01 11:31: an ESPN "Out" from the
    # injury report marked 23 teams posted with no list up anywhere, and flagged
    # Breece Hall (Joe: OUT) as active.
    out, posted, n_out = {}, set(), collections.Counter()
    with open(os.path.join(DATA, "games.csv"), newline="", encoding="utf-8") as fh:
        games = [r for r in csv.DictReader(fh)
                 if r["season"] == str(year) and r["week"] == str(week) and r.get("espn")]
    for g in games:
        if g["home_team"] in started and g["away_team"] in started:
            continue
        try:
            d = sess.get(SUMMARY, params={"event": g["espn"]}, timeout=30).json()
        except Exception:
            continue
        for t in d.get("injuries", []):
            tm = t.get("team", {}).get("abbreviation", "")
            tm = {"WSH": "WAS", "LAR": "LA"}.get(tm, tm)   # ESPN codes -> ours (2026-11-01: WAS never "posted")
            for i in t.get("injuries", []):
                fs = ((i.get("details") or {}).get("fantasyStatus") or {}).get("abbreviation", "")
                if fs != "INACTIVE" and i.get("status") != "Out":
                    continue
                n_out[tm] += 1
                if fs == "INACTIVE":
                    posted.add(tm)
                hit = ids.get(str((i.get("athlete") or {}).get("id", "")))
                if hit and hit[3] in ("QB", "RB", "WR", "TE"):
                    out[hit[0]] = (hit[1], hit[2])
    posted |= {tm for tm, n in n_out.items() if n >= 5}
    return out, posted


def out_why(tm, posted):
    """The note for a player listed out: the game-day list, or (no list yet)
    the injury report."""
    return "OFFICIAL INACTIVE (game-day list)" if tm in posted else "ruled OUT (injury report)"


def save_nfl_inactives(year, week):
    """nfl.com/inactives, the league's own game-day list (Joe, 2026-10-30: "this
    is supposed to be the official place"). Empty all week, and past weeks are
    404s, so its layout is unknown -- every game-day run keeps a copy, and the
    reader is built from the first filled one. Until then the ESPN game feed
    above is the list we go by."""
    import requests
    try:
        r = requests.get("https://www.nfl.com/inactives/",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001 -- a copy we could not take changes nothing
        print(f"  nfl.com inactives: fetch failed ({type(exc).__name__})")
        return
    d = os.path.join(DATA, "nfl_inactives")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, f"{year}_wk{week:02d}_{datetime.datetime.now():%Y%m%d_%H%M}.html")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(r.text)
    empty = "check back soon" in r.text.lower()
    print(f"  nfl.com inactives: {'nothing posted' if empty else 'LISTS POSTED'}"
          f" -- copy saved as {os.path.basename(dest)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--hours", type=float, default=6.0,
                    help="news window when the sheet is older than this")
    ap.add_argument("--dry-run", action="store_true", help="list, do not change the sheet")
    args = ap.parse_args()

    path = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    # "news since" goes by when JOE last saved the sheet, so read it before
    # the rebuild below touches the file
    saved = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    since = min(saved, datetime.datetime.now() - datetime.timedelta(hours=args.hours))
    since_s = since.strftime("%Y-%m-%d %H:%M")

    # the whole status sheet first: official report, Sleeper, news, practice --
    # rebuilt with every call kept, so this check reads what is current
    if not args.dry_run:
        refresh_inputs.refresh_sheet(args.year, args.week)
    else:
        try:
            refresh_inputs.refresh_sleeper()
        except Exception as exc:
            print(f"  sleeper refresh failed ({type(exc).__name__}) -- using the cached snapshot")
        news.update(args.year, quiet=True)
    tags, tag_date = availability.sleeper_tags(args.year)
    # what Sleeper said BEFORE today: a "play" call made against a tag that was
    # already there is Joe overruling it on purpose (Kirk, SF wk7: on IR when
    # Joe said "probably getting Kirk back"), so that tag must not undo it
    prev_tags, prev_date = availability.sleeper_tags(
        args.year, before=datetime.date.today().isoformat())
    report = availability._injury_report(args.year, args.week)
    kicks = score_week.kickoffs(args.year, args.week)
    inactive, posted = official_inactives(args.year, args.week,
                                          {tm for tm, k in kicks.items() if k <= datetime.datetime.now()})
    # game-day inactives are filed 90 minutes before kickoff; earlier in the
    # week ESPN's "Out" entries are Friday designations, not a posted list
    # (a Saturday run read 19 teams as "posted" and flagged Najee as active)
    soon = {tm for tm, k in kicks.items() if k - datetime.datetime.now() <= datetime.timedelta(hours=3)}
    posted &= soon
    if soon - {tm for tm, k in kicks.items() if k <= datetime.datetime.now()}:
        save_nfl_inactives(args.year, args.week)

    started = {tm for tm, k in score_week.kickoffs(args.year, args.week).items()
               if k <= datetime.datetime.now()}
    fresh = {}
    with open(os.path.join(DATA, f"news_{args.year}.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            t = set((r.get("tags") or "").split())
            if r["published"] >= since_s and t & {"OUT", "IR"} and not t & {"RETURN"}:
                if r["player_id"] not in fresh or r["published"] > fresh[r["player_id"]]["published"]:
                    fresh[r["player_id"]] = r

    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    fields = list(rows[0].keys())
    on_sheet = {r.get("player_id") for r in rows}
    changed = []
    for r in rows:
        pid = r.get("player_id")
        d = (r.get("decision") or "").strip().lower()
        # only Joe's explicit "he plays" calls -- a blank already follows Sleeper
        # and the official report automatically
        if not pid or not d or d == "out" or r.get("team") in started:
            continue
        why = None
        st = tags.get(pid, ("", ""))[0]
        if pid in inactive:
            why = out_why(r.get("team"), posted)
        elif st in GONE and prev_tags.get(pid, ("", ""))[0] not in GONE:
            why = f"Sleeper {st} ({tag_date}, new since {prev_date})"
        elif pid in fresh:
            n = fresh[pid]
            why = f"news {n['published'][5:16]}: {n['headline'][:70]}"
        if why:
            changed.append((r.get("player"), r.get("team"), d or "(blank)", why))
            if not args.dry_run:
                r["decision"] = "out"
                r["note"] = f"auto (late news): {why}"
    # fresh OUT news on a player not on the sheet whom Sleeper has not caught yet
    for pid, n in fresh.items():
        if pid in on_sheet or n["team"] in started or tags.get(pid, ("", ""))[0] in GONE:
            continue
        changed.append((n["player"], n["team"], "(not on sheet)", f"news {n['published'][5:16]}: {n['headline'][:70]}"))
        if not args.dry_run:
            new = {k: "" for k in fields}
            new.update(player_id=pid, player=n["player"], pos=n["pos"], team=n["team"],
                       source="late news", decision="out",
                       note=f"auto (late news): {n['headline'][:80]}")
            rows.append(new)
    # OFFICIAL INACTIVES for everyone else -- a BLANK row or no row at all
    # (2026-10-27: Tyjae Spears TEN wk7 was a game-day inactive with a blank
    # Questionable row, stayed projected at 5.2, and Pollard went for 25
    # carries / 35 pts). The game-day list is final; only Joe's PLAY can
    # countermand it, and that case is handled (and switched) above.
    by_pid = {r.get("player_id"): r for r in rows}
    for pid, (nm, tm) in inactive.items():
        if tm in started:
            continue
        r = by_pid.get(pid)
        if r is not None and (r.get("decision") or "").strip():
            continue                      # Joe's call (handled above, or already OUT)
        changed.append((nm, tm, "(blank)" if r is not None else "(not on sheet)",
                        out_why(tm, posted)))
        if not args.dry_run:
            if r is None:
                r = {k: "" for k in fields}
                r.update(player_id=pid, player=nm, team=tm, source="late news")
                rows.append(r)
            r["decision"] = "out"
            r["note"] = f"auto (late news): {out_why(tm, posted)}"
    # Joe has him OUT but the official inactives are posted and he is NOT on
    # them: he is active -- flag only (this check never turns anyone on)
    active_flags = []
    for r in rows:
        pid = r.get("player_id")
        if (r.get("decision") or "").strip().lower() == "out" and r.get("team") in posted                 and pid not in inactive and r.get("team") not in started                 and report.get(pid, "") not in availability.BLOCKING_REPORT:
            # the posted game-day list outranks a Sleeper tag (2026-11-01: Breece
            # Hall tagged out by Sleeper, not on the Jets' posted inactives: active)
            # players already ruled OUT on the official report are not repeated on
            # the game-day inactives list, so their absence from it means nothing
            active_flags.append((r.get("player"), r.get("team")))
    if changed and not args.dry_run:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    print(f"  late-news check ({'dry run' if args.dry_run else 'applied'}): sheet saved {saved:%a %H:%M}, "
          f"news since {since_s}, Sleeper {tag_date}")
    if not changed:
        print("  nothing new -- every player you have playing is still active")
    for nm, tm, was, why in changed:
        print(f"  -> OUT  {nm} ({tm})  was {was}   [{why}]")
    print(f"  official inactives posted for {len(posted)} teams" + (f": {', '.join(sorted(posted))}" if posted else ""))
    for nm, tm in active_flags:
        print(f"  ?? ACTIVE  {nm} ({tm}) -- you have him OUT, but he is not on the official inactives list")


if __name__ == "__main__":
    main()
