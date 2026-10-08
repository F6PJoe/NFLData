#!/usr/bin/env python3
"""
Blending, reconciliation and export for the WEEKLY in-season path.

Deliberately separate from `build_consensus.py`, which stays untouched for the
draft/season-long path. The blending algorithm here is the same one -- union
order by source priority, gap-fill continuation ranks, weighted average, top 2
sources at 1.5x -- reimplemented rather than imported because build_consensus
resolves its source list from `active_sources.json` at module scope and is
built around the preseason file layout. Keeping them apart is the point: the
weekly run must not be able to disturb the season-long outputs.

Differences from the season-long blend, all forced by how weekly works:
  * no OVR slot -- weekly is FLX/QB/RB/WR/TE/K/DST, and FP accepts nothing else
  * FLX comes straight from FP (`position=FLX`), never derived
  * the blended FLX is reconciled against the blended position lists before
    export, because FP enforces that agreement itself -- see reconcile_flex
  * the source set is chosen per (slot, scoring) by freshness, so two slots in
    the same run can legitimately blend different analysts
"""

import collections
import csv
import html
import os

import name_match
import weekly_freshness as wf


def source_weights(n):
    """Top 2 sources 1.5x, remainder 1.0x -- same shape as build_consensus.py."""
    return [1.5 if i < 2 else 1.0 for i in range(n)]


def blend_slot(lists_by_source, priority):
    """Weighted consensus for one slot.

    `lists_by_source` maps source label -> ordered list of
    (key, rank, name, team, position). `priority` is the source labels in
    priority order. Returns a list of (key, record) in final rank order.

    Gap filling: each source's list is extended to cover every player any
    source ranked, with missing players continuing from that source's OWN last
    rank -- so a shallow list starts its gaps at its own N+1 rather than a
    shared number. That matters here more than in preseason, because weekly
    list depth varies wildly between analysts (Orginski 141 vs Koerner 315).
    """
    if not priority:
        return []

    # Union order: the top source's list, then players new to each later source.
    order = [row[0] for row in lists_by_source[priority[0]]]
    seen = set(order)
    for label in priority[1:]:
        for row in lists_by_source[label]:
            if row[0] not in seen:
                order.append(row[0])
                seen.add(row[0])

    extended, real = {}, {}
    for label in priority:
        keys = [row[0] for row in lists_by_source[label]]
        ranks = {k: i + 1 for i, k in enumerate(keys)}
        real[label] = dict(ranks)
        have, nxt = set(keys), len(keys) + 1
        for key in order:
            if key not in have:
                ranks[key] = nxt
                nxt += 1
                have.add(key)
        extended[label] = ranks

    info = {}
    for label in priority:
        for key, _rank, name, team, pos in lists_by_source[label]:
            d = info.setdefault(
                key, {"name": name, "teams": collections.Counter(), "pos": pos})
            if len(name) > len(d["name"]):
                d["name"] = name
            # Majority vote on team, so one stale source can't win by being first.
            if team and team != "FA":
                d["teams"][team] += 1
            if not d["pos"]:
                d["pos"] = pos

    weights = source_weights(len(priority))
    total = sum(weights)

    scored = []
    for key in order:
        avg = sum(weights[i] * extended[priority[i]][key]
                  for i in range(len(priority))) / total
        d = info[key]
        rec = {
            "Player": d["name"],
            "Team": d["teams"].most_common(1)[0][0] if d["teams"] else "FA",
            "Position": d["pos"],
            "Sources": sum(1 for lb in priority if key in real[lb]),
        }
        for lb in priority:
            # Real rank if ranked; otherwise the gap-fill rank as a negative,
            # so it stays numeric and sortable but is obviously not a real one.
            rec[lb] = real[lb][key] if key in real[lb] else -extended[lb][key]
        scored.append((key, avg, rec))

    scored.sort(key=lambda t: t[1])
    return [(k, rec) for k, _avg, rec in scored]


def count_inversions(flex_keys, position_lists):
    """How many within-position pairs the flex disagrees with the positions on."""
    idx = {k: i for i, k in enumerate(flex_keys)}
    total = 0
    for keys in position_lists.values():
        present = [k for k in keys if k in idx]
        total += sum(1 for a, b in zip(present, present[1:]) if idx[a] > idx[b])
    return total


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def write_slot_csv(path, records, priority, timestamps=None):
    """`timestamps` (optional): {source label: display string, e.g. "Tue 7:51 AM"}.

    Baked into the column header itself -- "Justin Boone (Tue 7:51 AM)" --
    matching the convention build_consensus.py already uses for the draft
    pipeline (e.g. "Koerner (08/29 12:03 PM ET)"). Without this, the CSV had
    no record at all of how fresh each source's column was; only the HTML
    viewer tracked it. `priority` stays the lookup key into `rec` -- only the
    header label changes.
    """
    timestamps = timestamps or {}
    headers = ["Rank", "Player", "Team", "Position", "Sources"] + [
        f"{lb} ({timestamps[lb]})" if timestamps.get(lb) else lb
        for lb in priority
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for i, (_key, rec) in enumerate(records, 1):
            w.writerow([i, rec["Player"], rec["Team"], rec["Position"],
                        rec["Sources"]] + [rec[lb] for lb in priority])
    return len(records)


def write_paste_csv(path, records):
    """The stripped-down shape the FP importer wants."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Rank", "Player", "Team", "Position"])
        for i, (_key, rec) in enumerate(records, 1):
            w.writerow([i, rec["Player"], rec["Team"], rec["Position"]])
    return len(records)


# (section label, slot, max rows) in the order FP's own "Weekly Rankings" CSV
# export uses -- the file Joe uploads to his site. Depths are Joe's (2026-10-01).
# Superflex has no slot: Joe doesn't publish one, but his import expects the
# columns, so it's written as an empty block. Note DST before K.
SITE_EXPORT_SECTIONS = [("QB", "QB", 32), ("RB", "RB", 100), ("WR", "WR", 120),
                        ("TE", "TE", 35), ("Flex", "FLX", 300),
                        ("Superflex", None, 0), ("DST", "DST", 32), ("K", "K", 32)]
# One per team: the highest-ranked QB/K/DST on each team, so "all 32" means
# every team's starter and a bye week shrinks the list instead of padding it.
SITE_EXPORT_ONE_PER_TEAM = {"QB", "K", "DST"}
SITE_EXPORT_FIELDS = ["Name", "Team", "Position", "Player ID", "Opp", "Kickoff"]

# Player IDs Joe looked up by hand on FP, for players FP's API couldn't match.
# FP IDs are permanent, so one entry lasts forever. The run appends any
# still-missing player with a blank ID for Joe to fill in.
PLAYER_ID_OVERRIDES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "player_id_overrides.csv")
PLAYER_ID_OVERRIDE_FIELDS = ["Name", "Team", "Position", "Player ID"]


def _override_key(name, team, pos):
    """Same key normalize_rows gives the blend, so lookups line up."""
    if pos == "DST":
        return f"dst:{name_match.clean_team(team)}"
    return name_match.normalize_name(name)


def load_id_overrides(path=PLAYER_ID_OVERRIDES_PATH):
    """{blend key: player id} for every override row with an ID filled in."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {_override_key(r["Name"], r["Team"], r["Position"]): r["Player ID"].strip()
                for r in csv.DictReader(f) if (r.get("Player ID") or "").strip()}


def record_missing_ids(missing, path=PLAYER_ID_OVERRIDES_PATH):
    """Append each missing player (blank ID) unless he's already in the file.
    Returns how many rows were added."""
    existing = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            existing = {_override_key(r["Name"], r["Team"], r["Position"])
                        for r in csv.DictReader(f)}
    # A player is missing once per export section he's in (WR and Flex, say),
    # so dedupe within this run too, not just against the file.
    new = []
    for m in missing:
        key = _override_key(m["name"], m["team"], m["position"])
        if key not in existing:
            existing.add(key)
            new.append(m)
    if not new:
        return 0
    write_header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(PLAYER_ID_OVERRIDE_FIELDS)
        for m in new:
            w.writerow([m["name"], m["team"], m["position"], ""])
    return len(new)


def site_export_meta(rows_by_slot):
    """{blend key: FP player row} from FP consensus lists, keyed exactly the way
    normalize_rows keys the blend so lookups line up (DST by team)."""
    meta = {}
    for rows in rows_by_slot.values():
        for (key, *_rest), row in zip(normalize_rows(rows), rows):
            meta.setdefault(key, row)
    return meta


def _site_opp(text):
    """FP API "vs. NE" / "at CAR" -> the export's "vs NE" / "@ CAR"."""
    text = (text or "").strip()
    if text.startswith("vs."):
        return "vs " + text[3:].strip()
    if text.startswith("at "):
        return "@ " + text[3:].strip()
    return text


def _site_kickoff(ts):
    """Epoch -> "Sun 1:00pm ET", the export's format."""
    if not ts:
        return ""
    dt = wf.to_et(ts)
    return (f"{dt:%a} {dt.hour % 12 or 12}:{dt:%M}"
            f"{'am' if dt.hour < 12 else 'pm'} ET")


def write_site_export(path, blends, meta, id_overrides=None):
    """FP-style weekly rankings CSV: one 6-column block per list, side by side.

    Mirrors FP's own export byte-for-byte in layout (LF line endings, no BOM,
    Name/Position/Opp/Kickoff quoted, Team/ID bare, a blank separator column
    after each block). Every field comes from FP's row for the player, so
    names keep FP's spelling ("Patrick Mahomes II", "JAC").

    Joe's site import needs every Player ID. A player FP can't be matched to
    gets his ID from `id_overrides` (player_id_overrides.csv) if Joe has
    filled it in; otherwise he's still written at his rank -- never dropped --
    with the ID blank and Opp/Kickoff filled from his team's game, and is
    returned as {name, team, position, list, rank} so the run can name him
    and add him to the overrides file. The only players left out are ones FP
    shows with no opponent (bye / no game), which shrinks QB/K/DST on a bye.
    """
    id_overrides = id_overrides or {}
    def q(v):
        return '"' + v.replace('"', '""') + '"' if v else ""

    # Opp/kickoff are per team, so any teammate's FP row supplies them.
    schedule = {}
    for row in meta.values():
        if row.get("player_opponent") and row.get("player_game_kickoff_ts"):
            schedule.setdefault(row.get("player_team_id"),
                                (row["player_opponent"], row["player_game_kickoff_ts"]))

    columns, missing_ids = [], []
    for label, slot, limit in SITE_EXPORT_SECTIONS:
        col, teams = [], set()
        for key, rec in blends.get(slot, []) if slot else []:
            if len(col) >= limit:
                break
            fp = meta.get(key) or {}
            if fp and not fp.get("player_opponent"):
                continue
            team = fp.get("player_team_id") or rec["Team"]
            if slot in SITE_EXPORT_ONE_PER_TEAM:
                if team in teams:
                    continue
                teams.add(team)
            opp, kick = schedule.get(team, ("", None))
            name = fp.get("player_name") or rec["Player"]
            pos = fp.get("player_position_id") or rec["Position"]
            player_id = str(fp.get("player_id") or id_overrides.get(key) or "")
            if not player_id:
                missing_ids.append({"name": name, "team": team, "position": pos,
                                    "list": label, "rank": len(col) + 1})
            col.append([q(name),
                        team,
                        q(pos),
                        player_id,
                        q(_site_opp(fp.get("player_opponent") or opp)),
                        q(_site_kickoff(fp.get("player_game_kickoff_ts") or kick))])
        columns.append(col)

    lines = [",".join(f"{label},,,,,," for label, *_ in SITE_EXPORT_SECTIONS) + ",",
             ",".join(",".join(SITE_EXPORT_FIELDS) + ","
                      for _ in SITE_EXPORT_SECTIONS) + ","]
    for i in range(max((len(c) for c in columns), default=0)):
        lines.append(",".join(
            ",".join(c[i]) + "," if i < len(c) else ",,,,,,"
            for c in columns) + ",")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return missing_ids


def write_workbook(path, blends, scoring, priorities, timestamps=None):
    """One workbook per scoring format, one tab per slot, in paste order.

    Tabs rather than the side-by-side column blocks export_combined.py uses:
    weekly list lengths are ragged (FLX ~320 rows, QB ~28), so a column-block
    layout means selecting a column grabs hundreds of blank rows.

    `priorities` is per slot, not one shared list: freshness is gated per
    (slot, scoring), so a run can legitimately blend Ratcliffe+Orginski into RB
    and Ratcliffe+Orginski+Jahnke into FLX. Each tab therefore carries its own
    source columns. `timestamps`, if given, is {slot: {label: display string}}
    -- also per slot, for the same reason -- and gets baked into each tab's
    header cells the same way write_slot_csv does.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        return None

    wb = Workbook()
    wb.remove(wb.active)
    for slot, _sc in wf.paste_order(scoring):
        records = blends.get(slot)
        if not records:
            continue
        slot_priority = priorities.get(slot, [])
        slot_stamps = (timestamps or {}).get(slot, {})
        headers = [f"{lb} ({slot_stamps[lb]})" if slot_stamps.get(lb) else lb
                   for lb in slot_priority]
        ws = wb.create_sheet(slot)
        ws.append(["Rank", "Player", "Team", "Position", "Sources"] + headers)
        for i, (_key, rec) in enumerate(records, 1):
            ws.append([i, rec["Player"], rec["Team"], rec["Position"],
                       rec["Sources"]] + [rec[lb] for lb in slot_priority])
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        ws.freeze_panes = "A2"
        for i, width in enumerate([6, 24, 7, 9, 8] + [18] * len(slot_priority), 1):
            ws.column_dimensions[get_column_letter(i)].width = width
    if not wb.sheetnames:
        # Every list was gated out. openpyxl refuses to save a sheetless
        # workbook, and this is precisely the case the gate exists to produce,
        # so it must not take the run down with it.
        return None
    wb.save(path)
    return path


VIEWER_CSS = """
:root{color-scheme:light dark;--bg:#fbfbfa;--fg:#1a1a19;--mut:#6b6b68;
--line:#e3e3e0;--card:#fff;--accent:#2f6f4f;--warn:#8a5a12;--warnbg:#fdf6e7}
@media(prefers-color-scheme:dark){:root{--bg:#191918;--fg:#eceae4;--mut:#9a9a95;
--line:#33332f;--card:#212120;--accent:#6fbf8f;--warn:#d8a24a;--warnbg:#2a2416}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);position:sticky;
top:0;background:var(--bg);z-index:5}
h1{margin:0;font-size:17px;letter-spacing:-.01em}
.meta{color:var(--mut);font-size:13px;margin-top:3px}
.wrap{padding:12px 16px 48px;max-width:900px;margin:0 auto}
.list{background:var(--card);border:1px solid var(--line);border-radius:10px;
margin-bottom:12px;overflow:hidden}
.head{display:flex;align-items:center;gap:10px;padding:11px 13px}
.n{font-weight:650;font-size:15px;flex:1}
.n small{font-weight:400;color:var(--mut);margin-left:7px;font-size:13px}
button{font:inherit;font-weight:550;padding:8px 15px;border-radius:7px;
border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;
min-width:104px}
button.done{background:transparent;color:var(--accent)}
button:active{transform:translateY(1px)}
.src{padding:0 13px 10px;color:var(--mut);font-size:12.5px}
.stale{color:var(--warn)}
details{border-top:1px solid var(--line)}
summary{padding:9px 13px;cursor:pointer;color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:4px 13px;text-align:left;border-top:1px solid var(--line)}
th{color:var(--mut);font-weight:550}
td:first-child{color:var(--mut);width:44px}
.note{background:var(--warnbg);border:1px solid var(--line);border-radius:9px;
padding:11px 13px;margin-bottom:13px;font-size:13.5px;color:var(--warn)}
"""

VIEWER_JS = """
document.addEventListener('click', function(e){
  var b = e.target.closest('button[data-for]');
  if(!b) return;
  var t = document.getElementById(b.dataset.for).textContent;
  var done = function(){
    var old = b.textContent; b.textContent = 'Copied'; b.classList.add('done');
    setTimeout(function(){ b.textContent = old; b.classList.remove('done'); }, 1400);
  };
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(t).then(done, function(){ fallback(t, done); });
  } else { fallback(t, done); }
});
function fallback(text, done){
  var ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch(err) { alert('Copy failed'); }
  document.body.removeChild(ta);
}
"""


def write_viewer(path, blends, gating, meta):
    """Self-contained page: one Copy button per list, in paste order.

    Built for a phone at 12:56 -- the lists are pre-rendered as tab-separated
    text so a tap puts the whole board on the clipboard, and each list shows
    which sources went into it and how fresh they were.
    """
    parts = [f"<title>{html.escape(meta['title'])}</title>",
             f"<style>{VIEWER_CSS}</style>",
             "<header>",
             f"<h1>{html.escape(meta['title'])}</h1>",
             f"<div class=meta>{html.escape(meta['subtitle'])}</div>",
             "</header><div class=wrap>"]

    if meta.get("warning"):
        parts.append(f"<div class=note>{html.escape(meta['warning'])}</div>")

    if not any(blends.get(slot) for slot, _sc in meta["order"]):
        # The degraded case the freshness gate is designed to produce. Say what
        # happened and who was rejected, so the decision to relax the cutoff is
        # an informed one rather than a mystery at 12:56.
        parts.append("<div class=note><b>No list passed the freshness gate.</b> "
                     "Nothing here is safe to paste as-is.</div>")
        for slot, scoring in meta["order"]:
            skipped = gating.get((slot, scoring), {}).get("skipped", [])
            detail = ", ".join(
                f"{s['label']} ({s['reason']})" for s in skipped) or "no sources"
            parts.append(
                f"<div class=list><div class=head><div class=n>{slot}</div></div>"
                f"<div class='src stale'>{html.escape(detail)}</div></div>")
        parts.append("</div><script>" + VIEWER_JS + "</script>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
        return path

    for i, (slot, scoring) in enumerate(meta["order"], 1):
        records = blends.get(slot)
        if not records:
            continue
        gate = gating.get((slot, scoring), {})
        used = gate.get("used", [])
        # Origin and update time, not a tier label: at 12:56 what you need to
        # know is where each board came from and how old it is.
        detail = " · ".join(
            f"{u['label']} — {u.get('origin', '?')}, {u.get('updated', '?')}"
            for u in used) or "no sources"
        cls = " class=stale" if any(
            u["freshness"] not in ("FRESH",) for u in used) else ""

        lines = "\n".join(
            f"{n}\t{rec['Player']}\t{rec['Team']}\t{rec['Position']}"
            for n, (_k, rec) in enumerate(records, 1))
        pid = f"L{i}"
        rows = "".join(
            f"<tr><td>{n}</td><td>{html.escape(rec['Player'])}</td>"
            f"<td>{html.escape(rec['Team'])}</td>"
            f"<td>{html.escape(rec['Position'])}</td></tr>"
            for n, (_k, rec) in enumerate(records, 1))

        parts.append(
            f"<div class=list><div class=head>"
            f"<div class=n>{i}. {slot}<small>{len(records)} players</small></div>"
            f"<button data-for={pid}>Copy</button></div>"
            f"<div class='src{cls}'>{html.escape(detail)}</div>"
            f"<details><summary>Show list</summary>"
            f"<table><tr><th>#</th><th>Player</th><th>Tm</th><th>Pos</th></tr>"
            f"{rows}</table></details>"
            f"<pre id={pid} hidden>{html.escape(lines)}</pre></div>")

    parts.append("</div><script>" + VIEWER_JS + "</script>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def normalize_rows(players):
    """API rows -> the (key, rank, name, team, pos) tuples blend_slot wants.

    Every origin -- FP, FTN, cached captures -- arrives in the FP row shape and
    passes through here, so this is the one place display cleaning belongs.
    `display_name(clean_name(...))` mirrors build_consensus.py:126: it drops
    generational suffixes a source tacked on ("James Cook III" -> "James Cook")
    while DISPLAY_OVERRIDES keeps the ones that are genuinely part of a player's
    name ("Kenneth Walker III"). Matching was never affected -- normalize_name
    already strips suffixes -- but without this the blend picks whichever raw
    spelling happened to be longest, so one source's suffix leaked into output.
    """
    rows = []
    for i, p in enumerate(players):
        raw = p.get("player_name") or ""
        name = name_match.display_name(name_match.clean_name(raw))
        team = name_match.clean_team(p.get("player_team_id") or "")
        pos = p.get("player_position_id") or ""
        # DST is keyed by team, not name: FP says "Minnesota Vikings", FTN says
        # "Vikings" (0 of 32 names matched, 32 of 32 team codes did). Keying by
        # name split every defense in two. blend_slot keeps the longest name,
        # so the output still reads "Minnesota Vikings".
        key = f"dst:{team}" if pos == "DST" else name_match.normalize_name(raw)
        rows.append((key, i + 1, name, team, pos))
    return rows


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
