#!/usr/bin/env python3
"""The weekly review WORKBOOK -- one tab per team, calls made from dropdowns.

Joe, 2026-10-31: "its really hard to look through the review sheet the way its
built ... build it in tabs by team and position group, so I can swap out order
of who will play what role if I want to and add an in/out call or full or 80"
and "I choose who is RB1, RB2, RB3, WR1, WR2, WR3, etc and the call ... I
wouldn't be touching the actual stats. then the projection model would
recalculate".

The CSV sheet (data/review_<yr>_wk<NN>.csv) stays the model's input -- lock,
late news and everything else read it as before. This workbook is where the
calls are made. On each team tab, per player:

    Your role   RB1 / RB2 / WR3 / TE1 / QB1 ... -- he takes the work the model
                projects for that slot on his team; the rest of the group
                shifts down (project.role_multipliers). QB1 = he starts.
    Call        OUT / PLAY / FULL / SPLIT / EVEN / START / a number / "85 only" /
                "chance 50" -- the same words as always (read_review.py)
    QB carries  QB rows only: how many times he runs (a number) -- and
    QB yds/carry  his rushing yards per carry. Their own cells (Joe, 2026-11-04:
                "should there be two separate fields for the QB rush call and
                the original calls"), so a QB can be START / chance 50 / 85
                only AND have a rushing call. Blank = the model's. The extra
                carries come out of his backs; passing untouched. First named
                "QB rushes" / "QB ypc" -- Joe read "rush 7" as yards per carry,
                so they were renamed and the Key tab added the same day.
    Note        free text

The Key tab explains every fill-in column and every call in plain words
(Joe, 2026-11-04: "Maybe there needs to be a tab with a key for all this").

Everything else is information: status, practice, injury, source, news, the
last three games, the model's own projection and the one with your calls.

sync() copies the edits into the CSV: only cells that changed since the
workbook was built (or last synced), so an edit made straight in the CSV is
never overwritten by a stale workbook value. project.py --live and
build_review_queue.py sync first, so a lock never misses a workbook call.

    python review_book.py --year 2026 --week 8           # sync, then build
    python review_book.py --year 2026 --week 8 --sync    # copy edits into the CSV only
"""

import argparse
import collections
import csv
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

GROUPS = ("QB", "RB", "WR", "TE")
GROUP_NAME = {"QB": "QUARTERBACKS", "RB": "RUNNING BACKS", "WR": "WIDE RECEIVERS", "TE": "TIGHT ENDS"}
ROLE_SLOTS = {"QB": 3, "RB": 5, "WR": 6, "TE": 3}
CALLS = ("OUT,PLAY,FULL,SPLIT,EVEN,START,LIMITED,25,50,60,70,75,80,85,90,110,125,150,200,"
         "85 only,70 only,chance 50,chance 25")
RUSHES = "3,4,5,6,7,8,9,10"            # QB carries dropdown (any number can be typed)
YPCS = "4,4.5,5,5.5,6,6.5,7,7.5,8"     # QB yds/carry dropdown
COLS = ["Pos", "Model role", "Player", "Your role", "Call", "QB carries", "QB yds/carry", "Note",
        "Status", "Practice", "Injury", "Source", "Model pts", "With calls", "Change", "Carries",
        "Car chg", "Targets", "Tgt chg", "Pass att", "Consensus", "ETR", "Last 3 games", "News",
        "player_id"]
WIDTH = [5, 7, 22, 9, 10, 9, 9, 18, 16, 26, 14, 12, 8, 8, 7, 7, 7, 7, 7, 7, 9, 6, 70, 70, 12]
C = {name: i + 1 for i, name in enumerate(COLS)}      # column numbers
HEADER_ROW = 4
CALLS_TAB = "Calls"
KEY_TAB = "Key"
# what Joe edits, in the order kept in the sync state (older state files hold
# only the first three -- padded with blanks)
EDIT_KEYS = ("role", "call", "note", "rush", "ypc")
EDIT_COLS = {"role": "Your role", "call": "Call", "note": "Note", "rush": "QB carries",
             "ypc": "QB yds/carry"}
OLD_HEADERS = {"QB rushes": "QB carries", "QB ypc": "QB yds/carry"}   # a workbook built before the rename
SHEET_COLS = {"role": "role", "call": "decision", "note": "note", "rush": "rush", "ypc": "ypc"}


def book_path(year, week):
    return os.path.join(HERE, f"F6P Week {week} Review.xlsx")


def state_path(year, week):
    return os.path.join(DATA, f"review_book_{year}_wk{week:02d}.json")


def sheet_path(year, week):
    return os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")


def _cell(v):
    return "" if v is None else str(v).strip()


# ------------------------------------------------------------------ sync

def _num_cell(v):
    """A number as the workbook shows it: 7 not 7.0, so the sync state and a
    cell Excel re-saves read back the same."""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return _cell(v)


def _sheet_num(x):
    """A sheet value for a number cell: "7" -> 7, "6.5" -> 6.5 (numbers, so
    Excel doesn't flag them as text); anything else as typed, blank -> None."""
    if re.fullmatch(r"\d+(?:\.\d+)?", x or ""):
        f = float(x)
        return int(f) if f == int(f) else f
    return x or None


def _edit_tuple(v):
    """The edit values in EDIT_KEYS order, from a read_edits dict or an older
    3-long state list."""
    vals = [v.get(k, "") for k in EDIT_KEYS] if isinstance(v, dict) else list(v or [])
    return tuple((vals + [""] * len(EDIT_KEYS))[:len(EDIT_KEYS)])


def read_edits(year, week):
    """{pid: {role, call, note, rush, ypc, team, player, pos}} from the team
    tabs, or None if the workbook cannot be read. Locked tabs are skipped.
    Columns are found by their header names, so a workbook built before a
    column was added still reads right (its missing columns read blank)."""
    from openpyxl import load_workbook
    path = book_path(year, week)
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except (PermissionError, OSError) as e:
        print(f"  !! review workbook could not be read ({e.__class__.__name__}) -- its edits are NOT in")
        return None
    out = {}
    for ws in wb.worksheets:
        if ws.title in (CALLS_TAB, KEY_TAB):
            continue
        rows = ws.iter_rows(values_only=True)
        first = next(rows, None)
        if first and _cell(first[0]).startswith("LOCKED"):
            continue
        col = {}
        for row in rows:
            if not col:                       # still above the header row
                names = [_cell(x).replace("▼", "").strip() for x in row]
                names = [OLD_HEADERS.get(n, n) for n in names]
                if "player_id" in names:
                    col = {n: i for i, n in enumerate(names) if n}
                continue

            def get(name):
                i = col.get(name)
                return _num_cell(row[i]) if i is not None and i < len(row) else ""
            pid = get("player_id")
            if not pid:
                continue
            e = {k: get(name) for k, name in EDIT_COLS.items()}
            e["role"] = e["role"].upper()
            e.update(team=ws.title, player=get("Player"), pos=get("Pos"))
            out[pid] = e
    wb.close()
    return out


def _describe(e):
    """'START / rush 7 / ypc 6.5' -- one player's edits, for the sync message."""
    parts = [e["role"], e["call"]] + [f"{k} {e[k]}" for k in ("rush", "ypc") if e.get(k)]
    return "/".join(x for x in parts if x) or "cleared"


def sync(year, week):
    """Copy calls changed in the workbook into the CSV sheet. -> number copied
    (0 if no workbook or nothing changed), None if it could not be done.
    REVIEW_SYNCED=1 in the environment: the caller already synced (rerun.py /
    lock.py, before projecting every version AT ONCE) -- skip, so parallel runs
    never write the sheet together."""
    if os.environ.get("REVIEW_SYNCED") == "1":
        return 0
    if not os.path.exists(book_path(year, week)):
        return 0
    edits = read_edits(year, week)
    if edits is None:
        return None
    sp = state_path(year, week)
    state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    changed = {pid: e for pid, e in edits.items() if _edit_tuple(state.get(pid)) != _edit_tuple(e)}
    if not changed:
        return 0
    path = sheet_path(year, week)
    rows, fields = [], ["player_id", "player", "pos", "team", "injury", "practice", "source",
                        "proj", "decision", "role", "rush", "ypc", "note"]
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            fields = list(rd.fieldnames or fields)
            rows = list(rd)
    for col in ("decision", "note", "role", "rush", "ypc"):
        if col not in fields:
            fields.insert(fields.index("note") if col != "note" and "note" in fields else len(fields), col)
    by_pid = {r.get("player_id"): r for r in rows if r.get("player_id")}
    for pid, e in changed.items():
        r = by_pid.get(pid)
        if r is None:                        # a player not on the sheet yet: a manual row
            r = {k: "" for k in fields}
            r.update(player_id=pid, player=e["player"], pos=e["pos"], team=e["team"], source="manual")
            rows.append(r)
            by_pid[pid] = r
        for k in EDIT_KEYS:
            r[SHEET_COLS[k]] = e[k]
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)
    try:
        os.replace(tmp, path)
    except PermissionError:
        os.remove(tmp)
        print(f"  !! {os.path.basename(path)} is open (Excel?) -- workbook calls NOT copied in; close it")
        return None
    for pid, e in changed.items():
        state[pid] = list(_edit_tuple(e))
    with open(sp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    names = ", ".join(f"{e['player']} {_describe(e)}" for e in changed.values())
    print(f"  review workbook: {len(changed)} change(s) copied into the sheet -- {names}")
    return len(changed)


# ------------------------------------------------------------------ build

def _read_csv(path, enc="utf-8"):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding=enc) as fh:
        return list(csv.DictReader(fh))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _usage(r):
    """The number a role is ranked by: pass attempts (QB), carries + targets
    (RB), targets (WR/TE) -- as project.role_multipliers ranks them."""
    if not r:
        return 0.0
    if r["pos"] == "QB":
        return _num(r.get("pass_att")) or 0.0
    t = _num(r.get("targets")) or 0.0
    return t + ((_num(r.get("rush_att")) or 0.0) if r["pos"] == "RB" else 0.0)


def _games(year, week):
    """team -> {opp, home, kickoff (datetime), label, vegas}."""
    out = {}
    for g in _read_csv(os.path.join(DATA, "games.csv")):
        if g["season"] != str(year) or g["week"] != str(week):
            continue
        try:
            ko = datetime.datetime.strptime(f"{g['gameday']} {g['gametime']}", "%Y-%m-%d %H:%M")
        except ValueError:
            ko = None
        sp, tot = _num(g.get("spread_line")), _num(g.get("total_line"))
        for tm, opp, home in ((g["home_team"], g["away_team"], True), (g["away_team"], g["home_team"], False)):
            vegas = ""
            if sp is not None and tot is not None:
                mine = tot / 2 + (sp / 2 if home else -sp / 2)
                line = -sp if home else sp
                vegas = f"Vegas: {tm} {line:+g}, total {tot:g}, implied {mine:.1f}"
            when = (f"{g.get('weekday', '')[:3]} {ko:%m/%d} {ko:%I:%M %p}".replace(" 0", " ") + " ET") if ko else ""
            out[tm] = {"opp": opp, "home": home, "kickoff": ko, "vegas": vegas,
                       "label": f"{tm} {'vs' if home else '@'} {opp} -- {when}"}
    return out


def _last_games(log_rows, pid, week, n=3):
    mine = sorted((x for x in log_rows if x["player_id"] == pid and int(x["week"]) < week),
                  key=lambda x: int(x["week"]))[-n:]
    parts = []
    for x in mine:
        bits = []
        if x["report_status"]:
            bits.append(x["report_status"][0] + (f" {x['injury'].lower()}" if x["injury"] else ""))
        if x["practice"]:
            bits.append(x["practice"])
        if x["snaps"]:
            use = [x["snaps"] + " snaps"]
            if x["targets"] not in ("", "0"):
                use.append(f"{x['targets']} tgt")
            if x["carries"] not in ("", "0"):
                use.append(f"{x['carries']} car")
            use.append(f"{x['points']} pts")
            bits.append(", ".join(use))
        else:
            bits.append("did not play")
        if x["left_early"]:
            bits.append("LEFT EARLY")
        if x["sheet_call"]:
            bits.append(f"you: {x['sheet_call']}")
        parts.append(f"wk{x['week']}: " + ", ".join(bits))
    return " | ".join(parts)


def _news(year, days=5):
    """pid -> 'MM-DD HH:MM [TAGS] headline' (newest two, last `days` days)."""
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    by = collections.defaultdict(list)
    for r in _read_csv(os.path.join(DATA, f"news_{year}.csv")):
        if r.get("player_id") and r.get("published", "") >= cutoff:
            by[r["player_id"]].append(r)
    return {pid: " | ".join(f"{r['published'][5:16]} " + (f"[{r['tags']}] " if r.get("tags") else "")
                            + r["headline"]
                            for r in sorted(v, key=lambda r: r["published"], reverse=True)[:2])
            for pid, v in by.items()}


# ------------------------------------------------------------------ the Key tab

HEADER_TIPS = {   # hover notes on the fill-in headers
    "Your role": "Move a player to a slot on his team: QB1-3, RB1-5, WR1-6, TE1-3. "
                 "Blank = the model's order. Full list: Key tab.",
    "Call": "Plays or not, and how much: OUT, PLAY, FULL, SPLIT, EVEN, START, LIMITED, "
            "a % like 80, '85 only', 'chance 50'. Full list: Key tab.",
    "QB carries": "QBs only. How many times he RUNS the ball -- e.g. 6. "
                  "Blank = the model's. Extra carries come out of his running backs.",
    "QB yds/carry": "QBs only. His rushing YARDS PER CARRY -- e.g. 7. "
                    "Blank = the model's. Does not change how often he runs.",
}
KEY_FILL_IN = [   # (column, what to type, what it does, example)
    ("Your role", "QB1-QB3, RB1-RB5, WR1-WR6, TE1-TE3",
     "Puts him in that slot on his team. He gets the work the model projects for that slot -- or, moved UP, "
     "his own normal workload from games with the players above him playing, if that is more. Everyone else "
     "at his position shifts down a slot. QB1 = he starts.",
     "RB1 on the backup when the starter is out"),
    ("Call", "a word or number from the CALLS list below",
     "Whether he plays, and how much of his usual work he gets.", "OUT  /  80  /  START"),
    ("QB carries", "a number -- QB rows only",
     "How many times he RUNS the ball. Extra carries come out of his running backs (fewer go back to them). "
     "His rushing TDs follow his carries. His passing does not change. Blank = the model's number.",
     "6  =  six runs"),
    ("QB yds/carry", "a number -- QB rows only",
     "His rushing YARDS PER CARRY. Changes his rushing yards only -- not how often he runs (fill QB carries "
     "for that) and not his TDs. Blank = the model's rate.",
     "7  =  7 yards a run"),
    ("Note", "anything", "For you only -- the model ignores it.", ""),
]
KEY_CALLS = [     # (type this in Call, what it does)
    ("(blank)  or  PLAY", "Plays normally -- no change."),
    ("OUT", "Won't play. His work goes to his teammates."),
    ("LIMITED", "Plays at 60% of his usual work; the other 40% goes to his teammates."),
    ("FULL", "Plays, full go. Any recent game he LEFT hurt is thrown out of his history. A back returning "
             "from 2+ missed games gets his full lead-back job back."),
    ("SPLIT", "A back returning from injury: his backups KEEP the share they earned while he was out. "
              "It does NOT mean 50/50 -- that is EVEN."),
    ("EVEN", "Everyone marked EVEN at one position on a team splits their combined work equally (two backs = "
             "50/50). Each keeps his own yards per touch."),
    ("START", "This QB starts; the others become backups. Nobody has to be marked OUT."),
    ("a number:  80  or  150", "80 = 80% of his usual work, the rest to teammates. 150 = 50% more, taken "
                               "from teammates. On a QB, a number under 100 = the CHANCE HE STARTS "
                               "(blended with his backup)."),
    ("85 only", "His own line x 85%, teammates unchanged -- eased in, and nobody picks up the missing work."),
    ("chance 50", "50% chance he plays. His teammates' numbers blend both cases; HIS number is what he "
                  "scores if he plays."),
    ("rush 6  /  ypc 7  (old way)", "Still works typed in Call, same as the QB cells: 'rush 6' = 6 CARRIES, "
                                    "'ypc 7' = 7 YARDS PER CARRY, 'rush 6 ypc 7' = both. If the QB cells are "
                                    "filled too, they win."),
]
KEY_INFO = [      # the read-only columns
    ("Model role", "Where the model ranks him at his position on his team (RB1 = most work)."),
    ("Status / Practice / Injury", "Official injury report and practice (days in brackets); otherwise his "
                                   "roster status or Sleeper's tag."),
    ("Source", "Why he is listed: injury report, Sleeper, news, played last week -- or manual (you made a call)."),
    ("Model pts", "Half-PPR points from the model alone -- none of your calls."),
    ("With calls", "Half-PPR points with ALL your calls in (his and his teammates')."),
    ("Change", "With calls minus Model pts (green = up, red = down)."),
    ("Carries / Car chg", "Projected carries with your calls, and the change from the model alone."),
    ("Targets / Tgt chg", "Projected targets with your calls, and the change."),
    ("Pass att", "Projected pass attempts (QBs)."),
    ("Consensus / ETR", "The sites' half-PPR projections, to compare."),
    ("Last 3 games", "His last three games: injury, practice, snaps, left early."),
    ("News", "The latest news item about him."),
]


def write_key(ws, Font, PatternFill, Alignment):
    """The Key tab: every fill-in column and every call, in plain words."""
    title = Font(name="Arial", size=14, bold=True)
    sec = Font(name="Arial", size=12, bold=True)
    head, hfill = Font(name="Arial", bold=True, color="FFFFFF"), PatternFill("solid", fgColor="375623")
    bold, body = Font(name="Arial", size=10, bold=True), Font(name="Arial", size=10)
    green = PatternFill("solid", fgColor="E2EFDA")
    wrap = Alignment(wrap_text=True, vertical="top")
    ws.cell(1, 1, "KEY -- what you can fill in, and what it does").font = title
    ws.cell(2, 1, "Fill in the GREEN cells on the team tabs. Save, close the workbook, then run "
                  "'Rerun projections.bat'. Edits on this tab are ignored.").font = body
    r = 4

    def table(r, label, heads, rows, fill_first=False):
        ws.cell(r, 1, label).font = sec
        r += 1
        for i, h in enumerate(heads, start=1):
            c = ws.cell(r, i, h)
            c.font, c.fill, c.alignment = head, hfill, wrap
        r += 1
        for vals in rows:
            for i, v in enumerate(vals, start=1):
                c = ws.cell(r, i, v)
                c.font, c.alignment = bold if i == 1 else body, wrap
                if i == 1 and fill_first:
                    c.fill = green
            r += 1
        return r + 1

    r = table(r, "THE GREEN CELLS", ["Column", "What to type", "What it does", "Example"], KEY_FILL_IN, True)
    r = table(r, "CALLS  (the Call column)", ["Type this", "What it does"], KEY_CALLS, True)
    r = table(r, "THE OTHER COLUMNS  (information only)", ["Column", "What it shows"], KEY_INFO)
    ws.cell(r, 1, "TAB COLOURS").font = sec
    for i, line in enumerate(("orange = a listed player with no call yet",
                              "blue = calls made",
                              "grey = the game has started (locked -- edits there are ignored)"), start=1):
        ws.cell(r + i, 1, line).font = body
    r += i + 2
    ws.cell(r, 1, "BIG GAPS (Calls tab)").font = sec
    for i, line in enumerate((
            "Players we have 3+ points away from the consensus (and from ETR when it has him), with why: "
            "our targets / carries / team volume against theirs.",
            "Nothing to fill in there. Keep it if it is our read; if not, make a call on his team tab "
            "(a role, or a number in Call).",
            "Often the consensus is just behind on news (a new starter, an OUT) -- those are easy to keep."), start=1):
        ws.cell(r + i, 1, line).font = body
    for col, wd in zip("ABCD", (26, 30, 90, 30)):
        ws.column_dimensions[col].width = wd
    ws.sheet_properties.tabColor = "375623"


def build(year, week, run_model=True):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    import audit_vs_sources as A
    import availability
    import read_review

    path = book_path(year, week)
    if os.path.exists(path):
        try:
            open(path, "r+b").close()
        except PermissionError:
            sys.exit(f"  WORKBOOK NOT REBUILT -- {os.path.basename(path)} is open in Excel. "
                     f"Save and close it, then run again.")
    synced = sync(year, week)
    if synced is None:
        sys.exit("  WORKBOOK NOT REBUILT -- its edits could not be copied into the sheet (above)")
    w2 = f"{week:02d}"
    base_p = os.path.join(DATA, f"projections_{year}_wk{w2}_nocalls.csv")
    if run_model:
        r = subprocess.run([sys.executable, os.path.join(HERE, "project.py"), "--year", str(year),
                            "--week", str(week), "--live", "--ignore-sheet", "--out", base_p],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print((r.stderr.strip().splitlines() or ["?"])[-1])
            sys.exit("  model-only projection failed")
    proj = {r["player_id"]: r for r in _read_csv(os.path.join(DATA, f"projections_{year}_wk{w2}.csv"))}
    base = {r["player_id"]: r for r in _read_csv(base_p)}
    sheet = _read_csv(sheet_path(year, week), "utf-8-sig")
    ids = read_review._ids_by_name(year)
    unmatched = []
    sheet_by = {}
    for r in sheet:
        pid = (r.get("player_id") or "").strip() or ids.get(((r.get("player") or "").lower(), r.get("team", "")))
        if pid:
            sheet_by[pid] = r
        elif (r.get("decision") or r.get("role") or "").strip():
            unmatched.append(r)
    inj = {r["gsis_id"]: r for r in _read_csv(os.path.join(DATA, f"injuries_{year}.csv"))
           if r["week"] == str(week) and r.get("gsis_id")}
    days = {r["gsis_id"]: r["days"] for r in _read_csv(os.path.join(DATA, f"team_reports_{year}_wk{w2}.csv"))}
    status = availability._roster_status(year, week)
    dtr = availability._designated_return(year, week)
    tags, _ = availability.sleeper_tags(year)
    log_rows = _read_csv(os.path.join(DATA, f"player_log_{year}.csv"))
    news = _news(year)
    vol = {r["team"]: r for r in _read_csv(os.path.join(DATA, f"team_volume_{year}_wk{w2}.csv"))}
    games = _games(year, week)
    etr = {}
    try:
        directory, _ = A.resolve_dir(year, week)
        for r in _read_csv(os.path.join(directory, "etr.csv"), "utf-8-sig"):
            etr[A.norm(r["Player"])] = _num(r.get("Half PPR Proj"))
    except Exception:
        pass
    short = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "LIMITED",
             "Full Participation in Practice": "FULL"}

    # who goes on which tab
    team_of, pos_of, name_of = {}, {}, {}
    for src in (base, proj):
        for pid, r in src.items():
            team_of[pid], pos_of[pid], name_of[pid] = r["team"], r["pos"], r["player"]
    for pid, r in sheet_by.items():
        if r.get("pos") in GROUPS and r.get("team") in games:
            team_of.setdefault(pid, r["team"]); pos_of.setdefault(pid, r["pos"])
            name_of.setdefault(pid, r.get("player", pid))
    for pid, r in inj.items():         # ruled out on the report: listed so you see who is missing
        if r["position"] in GROUPS and r["team"] in games and r.get("report_status") in ("Out", "Doubtful"):
            team_of.setdefault(pid, r["team"]); pos_of.setdefault(pid, r["position"])
            name_of.setdefault(pid, r["full_name"])
    model_role = {}
    for tm in games:
        for g in GROUPS:
            ranked = sorted((p for p in base if team_of.get(p) == tm and pos_of.get(p) == g),
                            key=lambda p: -_usage(base[p]))
            for i, p in enumerate(ranked):
                model_role[p] = f"{g}{i + 1}"

    def status_of(pid):
        r = inj.get(pid, {})
        if r.get("report_status"):
            return r["report_status"]
        st = status.get(pid, "")
        if st and st not in availability.PLAYABLE_STATUS:
            return availability.STATUS_MEANING.get(st, st) + (" (designated to return)" if pid in dtr else "")
        tag, part = tags.get(pid, ("", ""))
        if tag:
            return f"Sleeper: {tag}" + (f" ({part})" if part else "")
        return ""

    def practice_of(pid):
        s_ = sheet_by.get(pid, {}).get("practice", "")
        if s_ and s_ != "-":
            return s_
        r = inj.get(pid, {})
        p_ = short.get(r.get("practice_status", ""), r.get("practice_status", ""))
        return f"{p_} ({days[pid]})" if p_ and days.get(pid) else p_

    now = datetime.datetime.now()
    HF = Font(name="Arial", bold=True, color="FFFFFF")
    HFILL = PatternFill("solid", fgColor="1F3864")
    GFILL = PatternFill("solid", fgColor="D9E1F2")
    LOCKFILL = PatternFill("solid", fgColor="D9D9D9")
    EDIT = PatternFill("solid", fgColor="FFF2CC")
    # Joe, 2026-10-31: the dropdown arrow only shows on the clicked cell, so the
    # cells he fills in are shaded green and boxed to tell them apart
    INPUT, INHFILL = PatternFill("solid", fgColor="E2EFDA"), PatternFill("solid", fgColor="375623")
    BOX = Border(*(Side(style="thin", color="A9D08E"),) * 4)
    INPUT_COLS = ("Your role", "Call", "Note")
    QB_COLS = ("QB carries", "QB yds/carry")          # input cells on QB rows only
    DROP_COLS = ("Your role", "Call") + QB_COLS
    BF, BB = Font(name="Arial", size=10), Font(name="Arial", size=10, bold=True)
    UP, DOWN = Font(name="Arial", size=10, color="007A33"), Font(name="Arial", size=10, color="C00000")
    WRAP = Alignment(wrap_text=True, vertical="top")
    TOP = Alignment(vertical="top")

    wb = Workbook()
    calls_ws = wb.active
    calls_ws.title = CALLS_TAB
    write_key(wb.create_sheet(KEY_TAB), Font, PatternFill, Alignment)
    state, calls, todo, problems = {}, [], [], []
    order = sorted(games, key=lambda t: (games[t]["kickoff"] or datetime.datetime.max,
                                         min(t, games[t]["opp"]), games[t]["home"]))
    for tm in order:
        gm = games[tm]
        locked = bool(gm["kickoff"] and gm["kickoff"] <= now)
        ws = wb.create_sheet(tm)
        if locked:
            ws.sheet_properties.tabColor = "A6A6A6"
        ws.cell(1, 1, ("LOCKED -- this game has started; edits here are ignored. " if locked else "")
                + gm["label"]).font = Font(name="Arial", size=13, bold=True,
                                           color="C00000" if locked else "000000")
        v = vol.get(tm)
        team_line = gm["vegas"]
        if v:
            team_line += (f"  |  model: {float(v['plays']):.0f} plays, {float(v['pass_att']):.0f} pass att, "
                          f"{float(v['targets']):.0f} targets, {float(v['nonqb_rush']):.1f} RB carries")
        ws.cell(2, 1, team_line).font = BF
        ws.cell(3, 1, "Green cells are yours: click one for its dropdown arrow (right edge), or type. "
                      "What every column and call does: see the KEY tab. "
                      "Save, close, then run 'Rerun projections.bat'."
                      ).font = Font(name="Arial", size=9, italic=True)
        for i, name in enumerate(COLS, start=1):
            c = ws.cell(HEADER_ROW, i, name + (" ▼" if name in DROP_COLS and not locked else ""))
            c.font, c.fill = HF, INHFILL if name in INPUT_COLS + QB_COLS and not locked else HFILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if name in HEADER_TIPS and not locked:      # shows when the mouse is over the header
                c.comment = Comment(HEADER_TIPS[name], "F6P")
                c.comment.width, c.comment.height = 260, 110
        dv_role = {g: DataValidation(type="list", formula1=f'"{",".join(f"{g}{k}" for k in range(1, ROLE_SLOTS[g] + 1))}"',
                                     allow_blank=True, showErrorMessage=False) for g in GROUPS}
        dv_call = DataValidation(type="list", formula1=f'"{CALLS}"', allow_blank=True, showErrorMessage=False)
        dv_qb = {"QB carries": DataValidation(type="list", formula1=f'"{RUSHES}"', allow_blank=True,
                                             showErrorMessage=False),
                 "QB yds/carry": DataValidation(type="list", formula1=f'"{YPCS}"', allow_blank=True,
                                          showErrorMessage=False)}
        if not locked:
            for dv in list(dv_role.values()) + [dv_call] + list(dv_qb.values()):
                ws.add_data_validation(dv)
        row = HEADER_ROW + 1
        has_call = has_todo = False
        for g in GROUPS:
            mine = [p for p in team_of if team_of[p] == tm and pos_of.get(p) == g]
            if not mine:
                continue
            mine.sort(key=lambda p: (p not in base, -_usage(base.get(p)), -_usage(proj.get(p))))
            ws.cell(row, 1, GROUP_NAME[g]).font = BB
            for i in range(1, len(COLS) + 1):
                ws.cell(row, i).fill = GFILL
            row += 1
            for pid in mine:
                s_ = sheet_by.get(pid, {})
                b, q = base.get(pid), proj.get(pid)
                bp = _num(b["half_ppr"]) if b else None
                qp = _num(q["half_ppr"]) if q else (0.0 if b else None)
                role, call, note = (s_.get("role") or "").strip().upper(), (s_.get("decision") or "").strip(), \
                    (s_.get("note") or "").strip()
                rush, ypc = ((s_.get(k) or "").strip() for k in ("rush", "ypc"))
                rush_v, ypc_v = _sheet_num(rush), _sheet_num(ypc)
                st = status_of(pid)
                vals = {"Pos": g, "Model role": model_role.get(pid, "-"), "Player": name_of.get(pid, pid),
                        "Your role": role, "Call": call, "QB carries": rush_v, "QB yds/carry": ypc_v,
                        "Note": note, "Status": st,
                        "Practice": practice_of(pid),
                        "Injury": (s_.get("injury") or inj.get(pid, {}).get("report_primary_injury")
                                   or inj.get(pid, {}).get("practice_primary_injury") or ""),
                        "Source": s_.get("source", ""),
                        "Model pts": bp, "With calls": qp,
                        "Change": (qp - bp) if (qp is not None and bp is not None
                                                and abs(qp - bp) >= 0.05) else None,
                        "Carries": _num(q.get("rush_att")) if q else None,
                        "Targets": _num(q.get("targets")) if q else None,
                        "Pass att": _num(q.get("pass_att")) if q else None,
                        "Consensus": _num((q or b or {}).get("consensus")),
                        "ETR": etr.get(A.norm(name_of.get(pid, ""))),
                        "Last 3 games": _last_games(log_rows, pid, week), "News": news.get(pid, ""),
                        "player_id": pid}
                if q and b:
                    for k, col in (("rush_att", "Car chg"), ("targets", "Tgt chg")):
                        d = (_num(q.get(k)) or 0.0) - (_num(b.get(k)) or 0.0)
                        vals[col] = d if abs(d) >= 0.05 else None
                for name, val in vals.items():
                    c = ws.cell(row, C[name], val)
                    c.font = BF
                    c.alignment = WRAP if name in ("Last 3 games", "News", "Practice", "Status") else TOP
                    if isinstance(val, float):
                        c.number_format = "0.0"
                for name in ("Change", "Car chg", "Tgt chg"):
                    val = vals.get(name)
                    if isinstance(val, float) and abs(val) >= 0.05:
                        ws.cell(row, C[name]).font = UP if val > 0 else DOWN
                if locked:
                    for i in range(1, len(COLS) + 1):
                        ws.cell(row, i).fill = LOCKFILL
                else:
                    for name in INPUT_COLS + (QB_COLS if g == "QB" else ()):
                        ws.cell(row, C[name]).fill, ws.cell(row, C[name]).border = INPUT, BOX
                    dv_role[g].add(ws.cell(row, C["Your role"]))
                    dv_call.add(ws.cell(row, C["Call"]))
                    if g == "QB":
                        for name, dv in dv_qb.items():
                            dv.add(ws.cell(row, C[name]))
                    state[pid] = [role, call, note] + [_num_cell(ws.cell(row, C[n]).value) for n in QB_COLS]
                if call or role or rush or ypc:
                    has_call = True
                    calls.append((tm, pid, vals, locked))
                    if not locked:
                        if call and not read_review.parse_decision(call)[2]:
                            problems.append((tm, vals["Player"], f"call '{call}' not understood -- treated as PLAY"))
                        for name, x in (("QB carries", rush), ("QB yds/carry", ypc)):
                            if x and g != "QB":
                                problems.append((tm, vals["Player"], f"{name} {x} on a {g} -- QBs only, ignored"))
                            elif x and read_review.rush_number(x) is None:
                                problems.append((tm, vals["Player"], f"{name} '{x}' is not a number -- ignored"))
                        if call and (rush or ypc) and (read_review.parse_rush(call) is not None
                                                       or read_review.parse_ypc(call) is not None):
                            problems.append((tm, vals["Player"], f"rushing in both Call ('{call}') and "
                                                                 f"QB carries / QB yds/carry -- the QB columns win"))
                        ro = read_review.parse_role(role) if role else None
                        if role and ro is None:
                            problems.append((tm, vals["Player"], f"role '{role}' not understood -- ignored"))
                        elif ro and ro[0] != g:
                            problems.append((tm, vals["Player"], f"role {role} on a {g} -- ignored"))
                        elif ro and ro[0] != "QB" and pid not in proj:
                            problems.append((tm, vals["Player"], f"role {role}, but he is not projected to "
                                                                 f"play ({st or 'out'}) -- ignored"))
                elif s_ and not locked and st not in ("Out", "Doubtful"):
                    has_todo = True
                    todo.append((tm, pid, vals))
                row += 1
        last = row - 1
        if not locked and last > HEADER_ROW:
            rng = f"{get_column_letter(C['Your role'])}{HEADER_ROW + 1}:{get_column_letter(C['Note'])}{last}"
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"LEN({get_column_letter(C['Your role'])}{HEADER_ROW + 1})>0"],
                                                           fill=EDIT))
            if has_todo:
                ws.sheet_properties.tabColor = "F4B084"
            elif has_call:
                ws.sheet_properties.tabColor = "5B9BD5"
        for i, wd in enumerate(WIDTH, start=1):
            ws.column_dimensions[get_column_letter(i)].width = wd
        ws.column_dimensions[get_column_letter(C["player_id"])].hidden = True
        ws.freeze_panes = ws.cell(HEADER_ROW + 1, C["Your role"])
        ws.row_dimensions[HEADER_ROW].height = 28

    # --- the Calls tab: every call made, and who is listed with no call yet
    ws = calls_ws
    ws.cell(1, 1, f"Week {week} review -- calls").font = Font(name="Arial", size=14, bold=True)
    for i, line in enumerate((
            "Make calls on the team tabs (one per team, in kickoff order). This tab is a summary -- edits here are ignored.",
            "What every column and call means: the KEY tab (next tab).",
            "Tab colours: orange = a listed player with no call yet, blue = calls made, grey = game started (locked).",
            "Then save and close the workbook and run 'Rerun projections.bat' (in the ff_weekly_model folder)."), start=2):
        ws.cell(i, 1, line).font = Font(name="Arial", size=10)
    r0 = i + 2

    def table(r, title, heads, items):
        ws.cell(r, 1, title).font = Font(name="Arial", size=12, bold=True)
        r += 1
        for i, h in enumerate(heads, start=1):
            c = ws.cell(r, i, h)
            c.font, c.fill = HF, HFILL
        r += 1
        for vals in items:
            for i, v in enumerate(vals, start=1):
                c = ws.cell(r, i, v)
                c.font = BF
                if isinstance(v, float):
                    c.number_format = "0.0"
                if i == 1 and v in wb.sheetnames:
                    c.hyperlink = f"#'{v}'!A1"
                    c.font = Font(name="Arial", size=10, color="0563C1", underline="single")
            r += 1
        if not items:
            ws.cell(r, 1, "(none)").font = BF
            r += 1
        return r + 1

    if problems:
        r0 = table(r0, "CHECK THESE -- calls the model could not use", ["Team", "Player", "Problem"], problems)
    # BIG GAPS (Joe 2026-11-04: "it can look bad to be so much higher or lower on a
    # player than the rest that I can't really defend") -- gap_report.py's list, so
    # each one is kept on purpose or gets a call on its team tab
    gaps, gp_ = [], os.path.join(DATA, f"gap_report_{year}_wk{week:02d}.csv")
    if os.path.exists(gp_):
        with open(gp_, newline="", encoding="utf-8-sig") as fh:
            for g in csv.DictReader(fh):
                f_ = lambda k: float(g[k]) if g.get(k) not in (None, "") else ""
                gaps.append((g["team"], g["player"], g["pos"], f_("ours"), f_("consensus"), f_("etr"),
                             f_("gap"), g.get("why (ours vs consensus)", "")))
        stamp = datetime.datetime.fromtimestamp(os.path.getmtime(gp_)).strftime("%a %I:%M %p")
        r0 = table(r0, f"BIG GAPS vs consensus (3+ pts, gap report {stamp}) -- keep it as our read, "
                       "or make a call on the team tab",
                   ["Team", "Player", "Pos", "Ours", "Consensus", "ETR", "Gap", "Why (ours vs consensus)"], gaps)

    def qb_rushing(v):
        parts = [f"{v['QB carries']} carries" if v.get("QB carries") is not None else "",
                 f"{v['QB yds/carry']} yds/carry" if v.get("QB yds/carry") is not None else ""]
        return ", ".join(p for p in parts if p)

    r0 = table(r0, "Your calls", ["Team", "Player", "Pos", "Your role", "Call", "QB rushing", "Note",
                                  "Model pts", "With calls", "Change", "Locked"],
               [(tm, v["Player"], v["Pos"], v["Your role"], v["Call"], qb_rushing(v), v["Note"],
                 v["Model pts"], v["With calls"], v["Change"], "yes" if lk else "")
                for tm, _, v, lk in calls])
    r0 = table(r0, "Listed on the injury report / news -- no call yet", ["Team", "Player", "Pos", "Status",
                                                                         "Practice", "Injury", "Model pts"],
               [(tm, v["Player"], v["Pos"], v["Status"], v["Practice"], v["Injury"], v["Model pts"])
                for tm, _, v in todo])
    if unmatched:
        table(r0, "Rows on the CSV sheet whose player could not be found", ["Team", "Player", "Call", "Role"],
              [(r.get("team", ""), r.get("player", ""), r.get("decision", ""), r.get("role", "")) for r in unmatched])
    for col, wd in zip("ABCDEFGHIJK", (8, 24, 6, 18, 26, 18, 30, 10, 10, 8, 8)):
        ws.column_dimensions[col].width = wd

    tmp = path.replace(".xlsx", ".tmp.xlsx")
    wb.save(tmp)
    try:
        os.replace(tmp, path)
    except PermissionError:
        os.remove(tmp)
        sys.exit(f"  WORKBOOK NOT REBUILT -- {os.path.basename(path)} is open in Excel")
    with open(state_path(year, week), "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    for tm, nm, why in problems:
        print(f"  !! {tm} {nm}: {why}")
    print(f"  review workbook: {len(order)} team tabs, {len(calls)} calls, {len(todo)} listed with no call"
          + (f", {len(problems)} PROBLEM(S) -- see the Calls tab" if problems else "")
          + f" -> {os.path.basename(path)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--sync", action="store_true", help="only copy workbook edits into the CSV sheet")
    ap.add_argument("--no-model-run", action="store_true",
                    help="reuse the existing model-only projection file")
    args = ap.parse_args()
    if args.sync:
        sys.exit(0 if sync(args.year, args.week) is not None else 1)
    build(args.year, args.week, run_model=not args.no_model_run)


if __name__ == "__main__":
    main()
