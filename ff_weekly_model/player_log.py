#!/usr/bin/env python3
"""Injury / usage / news log for every skill player, week by week.

    python player_log.py --year 2026 --week 6     # rebuild the log, annotate wk6 sheet

data/player_log_<year>.csv -- one row per player-week through the latest
games: snap share, targets, carries, points, the OFFICIAL injury report
(game status, practice, body part), whether he LEFT EARLY (play-by-play
injury exit, or a snap collapse while listed), Joe's review-sheet call that
week, and that week's news (tags + headline).

With --week, the review sheet for that week gets two columns rewritten --
`history` (his last 3 weeks in one line) and `news` (latest tagged item) --
and any player with fresh injury news who is not on the sheet yet is added
with a BLANK decision (blank = no effect). Decisions are never touched.

Built 2026-10-15 so nothing like "Evans left wk2 early" or "Montgomery is
out" has to be remembered by hand.
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

import project as P   # noqa: E402

FIELDS = ["week", "player_id", "player", "team", "pos", "snaps", "targets", "carries",
          "points", "report_status", "practice", "injury", "left_early", "sheet_call", "news"]
HOT_TAGS = {"OUT", "DOUBTFUL", "QUESTIONABLE", "IR", "PROTOCOL", "DNP", "LIMITED",
            "RETURN", "TRADE", "SIGNED", "STARTER", "BENCHED", "FULL_PRACTICE"}
PRACTICE = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "limited",
            "Full Participation in Practice": "full"}


def news_week(published, cutoffs):
    """The week whose games a news item is ABOUT: the first week whose first
    gameday is on or after the item's date."""
    day = (published or "")[:10]
    for w in sorted(cutoffs):
        if cutoffs[w] >= day:
            return w
    return max(cutoffs) if cutoffs else 0


def build(year):
    rows = P.load_players(year)
    played = [r for r in rows if r["position"] in P.ALL_POSITIONS]
    last_wk = max((int(r["week"]) for r in played), default=0)
    cut = P.week_cutoffs(year)
    sp = P.load_snap_pct(year)
    out = {}

    def row(pid, w):
        return out.setdefault((pid, w), {k: "" for k in FIELDS} | {"week": w, "player_id": pid})

    for r in played:
        pid, w = r["player_id"], int(r["week"])
        x = row(pid, w)
        x.update(player=r["player_display_name"], team=r["team"], pos=r["position"],
                 targets=int(P.num(r["targets"])), carries=int(P.num(r["carries"])),
                 points=round(P.actual_points(r), 1))
        if sp.get(pid, {}).get(w) is not None:
            x["snaps"] = f"{sp[pid][w]:.0%}"
    path = os.path.join(DATA, f"injuries_{year}.csv")
    listed = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("position") not in P.ALL_POSITIONS or not r.get("gsis_id"):
                    continue
                w = int(r["week"])
                x = row(r["gsis_id"], w)
                x["player"] = x["player"] or r["full_name"]
                x["team"] = x["team"] or r["team"]
                x["pos"] = x["pos"] or r["position"]
                x["report_status"] = r.get("report_status") or ""
                x["practice"] = PRACTICE.get(r.get("practice_status") or "", r.get("practice_status") or "")
                x["injury"] = r.get("report_primary_injury") or r.get("practice_primary_injury") or ""
                if x["report_status"] or x["practice"]:
                    listed.add((r["gsis_id"], w))
    # left early: play-by-play "was injured" with 15+ min left, or a snap
    # collapse (under half his best earlier game) while on that week's report
    epath = os.path.join(DATA, f"injury_exits_{year}.csv")
    if os.path.exists(epath):
        with open(epath, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("exited") == "1" and P.num(r.get("secs_remaining")) >= P.PBP_EXIT_MIN_SECS:
                    k = (r["player_id"], int(r["week"]))
                    if k in out:
                        out[k]["left_early"] = "injured in game (pbp)"
    for pid, wks in sp.items():
        for w, v in wks.items():
            before = [wks[x] for x in wks if x < w]
            if before and v < 0.5 * max(before) and (pid, w) in out and not out[(pid, w)]["left_early"]:
                out[(pid, w)]["left_early"] = (f"snaps {v:.0%} vs {max(before):.0%} usual"
                                               + (" (on report)" if (pid, w) in listed or (pid, w + 1) in listed else ""))
    # Joe's sheet calls
    for w in range(1, last_wk + 2):
        rp = os.path.join(DATA, f"review_{year}_wk{w:02d}.csv")
        if not os.path.exists(rp):
            continue
        with open(rp, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                d = (r.get("decision") or "").strip()
                if d and r.get("player_id"):
                    x = row(r["player_id"], w)
                    x["sheet_call"] = d
                    x["player"] = x["player"] or r.get("player", "")
                    x["team"] = x["team"] or r.get("team", "")
                    x["pos"] = x["pos"] or r.get("pos", "")
    # news, by the week it is about
    npath = os.path.join(DATA, f"news_{year}.csv")
    if os.path.exists(npath):
        with open(npath, newline="", encoding="utf-8") as fh:
            items = sorted(csv.DictReader(fh), key=lambda r: r["published"])
        for r in items:
            if not r["tags"]:
                continue
            w = news_week(r["published"], cut)
            x = row(r["player_id"], w)
            x["player"] = x["player"] or r["player"]
            x["team"] = x["team"] or r["team"]
            x["pos"] = x["pos"] or r["pos"]
            item = f"{r['published'][5:10]} [{r['tags']}] {r['headline']}"
            x["news"] = (x["news"] + " | " if x["news"] else "") + item
    log = sorted(out.values(), key=lambda x: (str(x["player"]), int(x["week"])))
    with open(os.path.join(DATA, f"player_log_{year}.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(log)
    return log


def history_line(log_rows, pid, week, n=3):
    """His last n weeks before `week`, one line: 'wk3 Q hip, limited, 33% snaps, LEFT EARLY; ...'"""
    mine = sorted((x for x in log_rows if x["player_id"] == pid and int(x["week"]) < week),
                  key=lambda x: int(x["week"]))[-n:]
    parts = []
    for x in mine:
        bits = []
        if x["report_status"]:
            bits.append(x["report_status"][0] + (f" {x['injury'].lower()}" if x["injury"] else ""))
        elif x["injury"]:
            bits.append(x["injury"].lower())
        if x["practice"]:
            bits.append(x["practice"])
        if x["snaps"]:
            bits.append(f"{x['snaps']} snaps")
        elif x["targets"] == "" and x["carries"] == "":
            bits.append("did not play")
        if x["left_early"]:
            bits.append("LEFT EARLY")
        if x["sheet_call"]:
            bits.append(f"you: {x['sheet_call']}")
        parts.append(f"wk{x['week']} " + ", ".join(bits) if bits else f"wk{x['week']} -")
    return "; ".join(parts)


def annotate_review(year, week, log_rows, days=4):
    """Rewrite `history` and `news` on that week's review sheet; add players with
    fresh injury news who are missing (blank decision). Decisions untouched."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    if not os.path.exists(path):
        return 0, 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    fields = list(rows[0].keys()) if rows else []
    for col in ("history", "news"):
        if col not in fields:
            fields.append(col)
    latest = {}
    npath = os.path.join(DATA, f"news_{year}.csv")
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    if os.path.exists(npath):
        with open(npath, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["tags"] and r["published"] >= cutoff and (
                        r["player_id"] not in latest or r["published"] > latest[r["player_id"]]["published"]):
                    latest[r["player_id"]] = r
    on_sheet = {r.get("player_id") for r in rows}
    added = 0
    for pid, n in latest.items():
        if pid in on_sheet or not ({"OUT", "DOUBTFUL", "QUESTIONABLE", "IR", "PROTOCOL", "DNP",
                                    "LIMITED", "RETURN", "TRADE", "SIGNED", "STARTER"} & set(n["tags"].split())):
            continue
        new = {k: "" for k in fields}
        new.update(player_id=pid, player=n["player"], pos=n["pos"], team=n["team"], source="news")
        rows.append(new)
        added += 1
    for r in rows:
        pid = r.get("player_id")
        r["history"] = history_line(log_rows, pid, week) if pid else ""
        n = latest.get(pid)
        r["news"] = f"{n['published'][5:16]} [{n['tags']}] {n['headline']}" if n else ""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    try:
        os.replace(tmp, path)
    except PermissionError:
        os.remove(tmp)
        sys.exit(f"  SHEET NOT ANNOTATED -- {os.path.basename(path)} is open (Excel?)")
    return len(rows), added


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, help="also annotate this week's review sheet")
    args = ap.parse_args()
    log = build(args.year)
    print(f"  player log: {len(log)} player-weeks -> player_log_{args.year}.csv")
    if args.week:
        n, added = annotate_review(args.year, args.week, log)
        print(f"  review sheet wk{args.week}: history + news written on {n} rows"
              + (f", {added} player(s) with fresh injury news added (decision blank)" if added else ""))


if __name__ == "__main__":
    main()
