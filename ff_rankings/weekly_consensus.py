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
  * no OVR slot -- weekly is FLX/QB/RB/WR/TE, and FP accepts nothing else
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
        rows.append((
            name_match.normalize_name(raw),
            i + 1,
            name,
            name_match.clean_team(p.get("player_team_id") or ""),
            p.get("player_position_id") or "",
        ))
    return rows


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
