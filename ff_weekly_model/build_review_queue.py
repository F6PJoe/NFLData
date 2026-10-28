#!/usr/bin/env python3
"""The weekly judgement call sheet -- Questionable skill players, nothing else.

Two sources, because one of them is often empty when you need it. The official
injury report is a Wednesday-to-Friday artifact: run this on a Tuesday and it
has nothing. Sleeper carries tags aggregated from beat reporting and is usually
days ahead, so it fills the gap. The `source` column says which one flagged a
player; where both do, the official designation wins.

The model does NOT predict injuries. Official designations and news decide who
plays. But "Questionable" is genuinely ambiguous -- most of them play, some
don't -- and that call is football judgement, not something to infer from
data. So the model surfaces exactly those players and gets out of the way.

Everything here is DEFAULTED so the sheet is optional: leave a row blank and
the player is treated as playing, which is what usually happens. Filling a row
in only overrides a default. Skipping the sheet in a busy week costs accuracy
on a handful of players, never correctness.

Columns you fill:
    decision   OUT | LIMITED | PLAY   (blank = PLAY)
    note       free text, for your own reference later

Usage:
    python build_review_queue.py --year 2026 --week 2
"""

import argparse
import collections
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
POSITIONS = ("QB", "RB", "WR", "TE")
# Sleeper aggregates beat reporting rather than issuing designations, so even
# its Out and Doubtful go on the sheet. They are already applied upstream --
# listing them only gives you the chance to write PLAY and countermand one.
SLEEPER_REVIEWABLE = ("Questionable", "Doubtful", "Out")


def norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())
PRACTICE_SHORT = {"Did Not Participate In Practice": "DNP",
                  "Limited Participation in Practice": "LIMITED",
                  "Full Participation in Practice": "FULL"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()

    inj_path = os.path.join(DATA, f"injuries_{args.year}.csv")
    with open(inj_path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["week"] == str(args.week) and r["position"] in POSITIONS]

    # projected points, so the sheet is ordered by who actually matters
    proj, proj_meta = {}, {}
    pp = os.path.join(DATA, f"projections_{args.year}_wk{args.week:02d}.csv")
    if os.path.exists(pp):
        with open(pp, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                proj[r["player_id"]] = float(r["half_ppr"])
                proj_meta[r["player_id"]] = r

    entries = [{"pid": r["gsis_id"], "name": r["full_name"], "pos": r["position"],
                "team": r["team"], "injury": r["report_primary_injury"],
                "practice": PRACTICE_SHORT.get(r["practice_status"],
                                               r["practice_status"] or "-"),
                "source": "report"}
               for r in rows if r["report_status"] == "Questionable"]

    # Sleeper fills in wherever the official report is silent on a player
    sys.path.insert(0, HERE)
    import availability
    tags, tag_date = availability.sleeper_tags(args.year)
    sl_meta = availability.sleeper_meta(args.year) if tags else {}
    # Sleeper knows about 12,000 people, most of them not on an NFL roster.
    # The depth chart is the answer to "who could actually play this week".
    import project
    roster, _asof = project.current_roster(args.year)
    graded = {r["gsis_id"] for r in rows if r["report_status"]}
    sleeper_q = 0
    if tags:
        for pid in sorted(set(proj) | set(tags),
                          key=lambda k: -proj.get(k, 0)):
            tag, part = tags.get(pid, ("", ""))
            if tag not in SLEEPER_REVIEWABLE or pid in graded:
                continue
            if pid not in roster:
                continue
            meta = proj_meta.get(pid) or sl_meta.get(pid) or {}
            if meta.get("pos", "-") not in POSITIONS:
                continue
            entries.append({"pid": pid, "name": meta.get("player", pid),
                            "pos": meta.get("pos", "-"), "team": meta.get("team", "-"),
                            "injury": part or "(unspecified)", "practice": "-",
                            "source": f"sleeper/{tag[:4].upper()}"})
            sleeper_q += 1
    # PRACTICE (2026-10-22, Joe: "feels like the week 7 status sheet is off").
    # Game statuses for Sunday teams only arrive Friday, but the report carries
    # each day's practice from Wednesday. Every row shows his latest practice,
    # and anyone who did not practice or was limited is listed even before
    # Sleeper or a game status flags him (Breece Hall, Rice, Evans: DNP Wed).
    practice = {r["gsis_id"]: PRACTICE_SHORT.get(r["practice_status"], r["practice_status"])
                for r in rows if r["practice_status"]}
    for e in entries:
        if e["practice"] in ("-", "") and practice.get(e["pid"]):
            e["practice"] = practice[e["pid"]]
    listed = {e["pid"] for e in entries}
    for r in rows:
        p_ = practice.get(r["gsis_id"])
        if r["gsis_id"] in listed or r["report_status"] or p_ not in ("DNP", "LIMITED"):
            continue
        entries.append({"pid": r["gsis_id"], "name": r["full_name"], "pos": r["position"],
                        "team": r["team"],
                        "injury": r["practice_primary_injury"] or r["report_primary_injury"],
                        "practice": p_, "source": f"report/{p_[:3]}"})
    # PLAYED LAST WEEK, NOT PROJECTED NOW (2026-10-22, Joe on Jawhar Jordan,
    # HOU: 6 carries / 11.5 pts wk6 as a practice-squad call-up, then dropped --
    # Sleeper "Out / Undisclosed", off the depth chart). Anyone with a touch
    # last week, on a team that plays this week, whom the model is not
    # projecting gets a row, so a call-up never vanishes unseen.
    listed = {e["pid"] for e in entries}
    stats_p = os.path.join(DATA, f"stats_player_week_{args.year}.csv")
    playing_now = {(r.get("team") or "") for r in proj_meta.values()}
    if os.path.exists(stats_p) and args.week > 1:
        with open(stats_p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["week"] != str(args.week - 1) or r["position"] not in POSITIONS:
                    continue
                pid = r["player_id"]
                touches = float(r.get("carries") or 0) + float(r.get("targets") or 0) \
                    + float(r.get("attempts") or 0)
                if pid in listed or touches < 1 or proj.get(pid, 0) > 0.5:
                    continue
                if r["team"] not in playing_now:
                    continue
                entries.append({"pid": pid, "name": r["player_display_name"],
                                "pos": r["position"], "team": r["team"],
                                "injury": f"not projected (Sleeper: {tags.get(pid, ('-',))[0] or '-'})",
                                "practice": practice.get(pid, "-"),
                                "source": "played last wk"})
                listed.add(pid)
    q = sorted(entries, key=lambda e: -proj.get(e["pid"], 0))

    dest = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    existing, kept = {}, []
    if os.path.exists(dest):          # never clobber calls already made
        # utf-8-sig: Excel's "CSV UTF-8" save adds a byte-order mark, which
        # would rename the player_id column and silently drop every call
        with open(dest, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("decision") or r.get("note"):
                    key = r.get("player_id") or f"~{norm(r.get('player'))}"
                    existing[key] = (r.get("decision", ""), r.get("note", ""))
                    kept.append(r)
    # A row YOU added by hand must survive the rebuild, or the sheet would
    # quietly undo your work every time it is regenerated.
    flagged = {e["pid"] for e in q}
    manual = 0
    for r in kept:
        if (r.get("player_id") or "") in flagged:
            continue
        q.append({"pid": r.get("player_id", ""), "name": r.get("player", ""),
                  "pos": r.get("pos", "-"), "team": r.get("team", "-"),
                  "injury": r.get("injury", ""), "practice": r.get("practice", "-"),
                  "source": "manual"})
        manual += 1

    # written to a temp file and swapped in, so a crash never leaves half a
    # sheet; if Joe has it open in Excel the swap fails and NOTHING changes
    tmp = dest + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["player_id", "player", "pos", "team", "injury", "practice",
                    "source", "proj", "decision", "note"])
        for e in q:
            d, n = existing.get(e["pid"] or f"~{norm(e['name'])}", ("", ""))
            w.writerow([e["pid"], e["name"], e["pos"], e["team"], e["injury"],
                        e["practice"], e["source"],
                        round(proj.get(e["pid"], 0), 1), d, n])
    try:
        os.replace(tmp, dest)
    except PermissionError:
        os.remove(tmp)
        sys.exit(f"  SHEET NOT REBUILT -- {os.path.basename(dest)} is open (Excel?). "
                 f"Close it and run again; your calls are untouched.")
    kept_calls = sum(1 for e in q if existing.get(e["pid"] or f"~{norm(e['name'])}", ("", ""))[0])
    made = sum(1 for d, _ in existing.values() if d)
    if kept_calls != made:
        print(f"  WARNING: {made} calls on the old sheet, {kept_calls} on the new one")

    other = collections.Counter(r["report_status"] for r in rows if r["report_status"])
    sl_block = sum(1 for e in q if e["source"].startswith("sleeper/")
                   and not e["source"].endswith("QUES"))
    print()
    from_report = len(q) - sleeper_q - manual
    print(f"  week {args.week} judgement calls -- {len(q)} rows  "
          f"({from_report} from the report, {sleeper_q} from sleeper, "
          f"{manual} yours)")
    print(f"  (auto-handled: {other.get('Out', 0)} Out, "
          f"{other.get('Doubtful', 0)} Doubtful from the report -- not listed)")
    if sl_block:
        print(f"  {sl_block} of the rows below are sleeper Out/Doubtful, "
              f"ALREADY removed; they are")
        print("  listed only so you can write PLAY to countermand one.")
    if manual:
        print(f"  {manual} row(s) you added by hand, carried through")
    if tag_date:
        print(f"  sleeper snapshot: {tag_date}")
    print()
    print(f"  {'player':<24}{'pos':<5}{'tm':<5}{'injury':<20}"
          f"{'practice':<10}{'source':<9}{'proj':>6}")
    for e in q[:20]:
        print(f"  {e['name']:<24}{e['pos']:<5}{e['team']:<5}"
              f"{(e['injury'] or '-')[:19]:<20}{e['practice']:<10}"
              f"{e['source']:<9}{proj.get(e['pid'], 0):>6.1f}")
    if len(q) > 20:
        print(f"  ... and {len(q) - 20} more")
    print(f"\n  -> {os.path.basename(dest)}   (blank decision = treated as PLAY)\n")


if __name__ == "__main__":
    main()
