#!/usr/bin/env python3
"""
The in-season weekly run. Separate from run_all.py, which is left untouched.

    python run_weekly.py                      # this week, half-PPR
    python run_weekly.py --scoring all        # all three formats (13 lists)
    python run_weekly.py --year 2025 --week 12 --gate off   # historical test

What it does, in order:
  1. Work out the week (from FP's own page, not a hardcoded season start) and
     the freshness threshold for this point in the week -- see
     weekly_freshness.freshness_threshold.
  2. Fetch every pool source's list for every needed slot, CONCURRENTLY. This
     is not optional: measured 1.43 s/request, so the 65-request half-PPR pull
     is ~90 s sequentially and a few seconds in parallel. A 12:55 run has no
     room for the sequential version.
  3. Gate each (slot, scoring) on freshness independently and take the top
     MAX_SOURCES that pass, walking down the priority pool and falling back to
     FTN for the sources published there.
  4. Blend, reconcile the flex against the position lists, export.

Outputs land in weekly/<year>-wk<NN>/ so nothing can collide with the
preseason CSVs in the project root.
"""

import argparse
import datetime
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

import cached_source
import ftn_weekly
import weekly_consensus as wc
import weekly_freshness as wf


def resolve_week(session):
    """Ask FP what week it is, rather than deriving it from a season start."""
    info = wf.fetch_list_freshness("FLX", "HALF", session=session)
    return info.get("year"), info.get("week")


def panel_epochs(lists, session, workers=8):
    """{(slot, scoring): {expert_id: epoch}} from FP's own panel data."""
    out = {}

    def one(key):
        slot, scoring = key
        try:
            data = wf.fetch_list_freshness(slot, scoring, session=session)
            return key, {e["expert_id"]: e["last_updated"]
                         for e in data["experts"]}, None
        except Exception as exc:
            return key, {}, f"{type(exc).__name__}: {exc}"

    errors = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, epochs, err in ex.map(one, lists):
            out[key] = epochs
            if err:
                errors.append((key, err))
    return out, errors


def fetch_everything(lists, year, week, session, workers=12):
    """{(label, slot, scoring): players} for every pool source and list."""
    jobs = []
    for slot, scoring in lists:
        for source in wf.sources_for(scoring):
            jobs.append((source, slot, scoring))

    results, errors = {}, []

    def one(job):
        source, slot, scoring = job
        try:
            players, _ = wf.fetch_expert_list(
                source["ids"][0], slot, scoring, year, week, session=session)
            return (source["label"], slot, scoring), players, None
        except Exception as exc:
            return ((source["label"], slot, scoring), None,
                    f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, players, err in ex.map(one, jobs):
            if err:
                errors.append((key, err))
            else:
                results[key] = players
    return results, errors


def _stamp(epoch):
    # %-I is glibc-only; this runs on Windows too.
    if not epoch:
        return "no timestamp"
    return wf.to_et(epoch).strftime("%a %I:%M %p").replace(" 0", " ")


def _fp_candidate(source, slot, scoring, fetched, epochs):
    """FP's own (origin, players, epoch_or_None), or None if FP has no board."""
    players = fetched.get((source["label"], slot, scoring))
    if not players:
        return None
    epoch = next((epochs.get(eid) for eid in source["ids"]
                  if epochs.get(eid)), None)
    return ("FP", players, epoch)


def _backup_candidates(source, slot, scoring, ftn_data, cached):
    """FTN/cache candidates for this source/list, in tie-break preference order."""
    out = []
    if source.get("ftn_analyst") and ftn_data:
        analyst = source["ftn_analyst"]
        rows = ftn_weekly.analyst_list(ftn_data, analyst, slot, scoring)
        if rows:
            stamp = ftn_weekly.submitted_at(ftn_data, analyst, scoring, slot)
            out.append(("FTN", rows, stamp))

    if source["prefix"] in cached:
        payload = cached[source["prefix"]]
        # rows and stamp MUST come from the same call: a source can have a
        # fresher timestamp on one format and stale content on another, and
        # board_for() guarantees the timestamp always describes the format
        # actually being returned, never a different one's capture time.
        rows, stamp = cached_source.board_for(payload, slot, scoring)
        if rows:
            out.append((payload.get("origin", "cache"), rows, stamp))

    return out


def choose_sources(slot, scoring, fetched, epochs, threshold, gate,
                   ftn_data, cached, phase, manual_sources=None):
    """Top MAX_SOURCES for this list, walking the pool in priority order.

    Freshness is evaluated per list, not per source: an analyst can refresh
    their flex and leave QB alone, so the same run can legitimately blend
    different analysts into different slots.

    FP is checked first, on its own. A backup is skipped ONLY during a lock
    phase (`wf.is_lock_phase` -- TNF LOCK, SUNDAY LOCK, or a manual --cutoff)
    where FP's own timestamp already clears the threshold. Joe's rule
    (2026-09-11): "When I'm inside a freshness window and FP is inside that,
    then no, I do not need to check the other source. If we are not inside a
    freshness window, then yes check the backup source and pull the most
    current one." Outside a lock -- EARLY WEEK or POST-TNF -- the backup is
    ALWAYS checked and whichever of FP and the backup(s) is most recent wins,
    even if FP alone would have cleared the threshold. This matters
    concretely: POST-TNF can span 40+ hours, and an FP board that passed the
    instant the window opened does not stay the freshest thing forever.
    Verified live 2026-09-11: Ratcliffe's FP entry (Thu 8:34 PM, correctly
    inside POST-TNF's threshold at the time) was still winning on Friday
    afternoon while his FTN submission had moved to Fri 2:58 PM -- nearly a
    day fresher -- because nothing ever re-checked it once FP had cleared the
    bar once. A known timestamp always beats an unknown one, which beats no
    board at all, in every case.

    Earlier iterations, for the record: v1 only checked a backup once FP
    failed its ACCEPT check, which a manual pick short-circuits to
    always-true, so a manual pick with ANY FP board -- even stale -- beat a
    fresher backup. v2 fixed that by always gathering FP + every backup and
    taking the freshest, for every run -- correct, but more comparing than
    Joe wanted once FP is clearly fine. v3 (this file's previous version)
    over-corrected the other way: it stopped checking backups at all once FP
    passed, in EVERY phase including the long POST-TNF window, which is the
    Ratcliffe gap described above.

    manual_sources, if given, is a set of prefixes: restricts the pool to
    exactly those sources (in their usual priority order) and waives the
    freshness check for them specifically -- for the night the strict gate
    leaves too few (or the wrong) sources and Joe has looked at
    weekly_status.py's timestamps himself and decided a stale board is still
    good enough. It does NOT waive the "does this source have a board at all"
    check, and it has no effect on which ORIGIN wins (that's governed by the
    lock-phase rule above regardless of manual/gate status) -- only on
    whether the winning candidate has to be FRESH to be accepted. The
    freshness TAG shown in output is still the real one (e.g. "Thu 3:01 PM",
    STALE) so a manual call is visibly a manual call.
    """
    pool = wf.sources_for(scoring)
    if manual_sources is not None:
        pool = [s for s in pool if s["prefix"] in manual_sources]

    chosen, skipped = [], []
    for source in pool:
        label = source["label"]
        fp = _fp_candidate(source, slot, scoring, fetched, epochs)

        considered = None  # only set when a backup was actually checked
        if fp is not None:
            fp_freshness = wf.tier_since(fp[2], threshold)
            if wf.is_lock_phase(phase) and fp_freshness == "FRESH":
                origin, players, epoch, freshness = *fp, fp_freshness
            else:
                candidates = [fp] + _backup_candidates(
                    source, slot, scoring, ftn_data, cached)
                origin, players, epoch = max(
                    candidates, key=lambda c: (c[2] is not None, c[2] or 0))
                freshness = wf.tier_since(epoch, threshold)
                if len(candidates) > 1:
                    considered = [(o, e) for o, _, e in candidates]
        else:
            candidates = _backup_candidates(source, slot, scoring, ftn_data, cached)
            if not candidates:
                skipped.append({"label": label,
                                "reason": "no board found for this list, at any origin"})
                continue
            origin, players, epoch = max(
                candidates, key=lambda c: (c[2] is not None, c[2] or 0))
            freshness = wf.tier_since(epoch, threshold)
            if len(candidates) > 1:
                considered = [(o, e) for o, _, e in candidates]

        manual_ok = manual_sources is not None and source["prefix"] in manual_sources
        if not (gate == "off" or manual_ok
                or threshold is None or freshness == "FRESH"):
            skipped.append({"label": label, "reason": f"{origin} {freshness.lower()}"})
            continue

        candidate = {"origin": origin, "players": players,
                     "freshness": freshness, "updated": _stamp(epoch),
                     "considered": [{"origin": o, "updated": _stamp(e)}
                                    for o, e in considered] if considered else None}

        candidate["label"] = label
        chosen.append(candidate)
        if len(chosen) >= wf.MAX_SOURCES:
            break
    return chosen, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scoring", default="HALF",
                    choices=["HALF", "PPR", "STD", "all"],
                    help="format to build (default HALF -- the 5 lists that "
                         "have to fit before lock)")
    ap.add_argument("--cutoff", metavar="HH:MM",
                    help="override the freshness threshold with a time today, ET")
    ap.add_argument("--gate", choices=["strict", "off"], default="strict",
                    help="strict: honour the freshness threshold for this point "
                         "in the week. off: top of the pool regardless")
    ap.add_argument("--sources", metavar="PREFIX,PREFIX,...",
                    help=f"hand-pick who's included (up to {wf.MAX_SOURCES}), "
                         f"bypassing the freshness check for exactly these -- "
                         f"see weekly_status.py for who has updated when. "
                         f"choices: {', '.join(s['prefix'] for s in wf.SOURCE_PRIORITY)}")
    ap.add_argument("--no-ftn", action="store_true",
                    help="skip the FTN fallback (e.g. if the login is down)")
    ap.add_argument("--year")
    ap.add_argument("--week")
    ap.add_argument("--out-root", default="weekly")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--open", action="store_true", dest="open_viewer",
                    help="open the copy page in a browser when the run finishes")
    args = ap.parse_args()

    now_et = datetime.datetime.now(wf.ET)
    session = requests.Session()

    manual_sources = None
    if args.sources:
        valid = {s["prefix"] for s in wf.SOURCE_PRIORITY}
        manual_sources = [p.strip().lower() for p in args.sources.split(",") if p.strip()]
        unknown = [p for p in manual_sources if p not in valid]
        if unknown:
            sys.exit(f"Unknown source prefix(es): {', '.join(unknown)}. "
                     f"Valid: {', '.join(sorted(valid))}")
        if len(manual_sources) > wf.MAX_SOURCES:
            in_priority_order = [s["prefix"] for s in wf.SOURCE_PRIORITY
                                 if s["prefix"] in manual_sources]
            print(f"WARNING: {len(manual_sources)} sources given, only the "
                  f"top {wf.MAX_SOURCES} by priority will be used: "
                  f"{', '.join(in_priority_order[:wf.MAX_SOURCES])}")
        manual_sources = set(manual_sources)

    gate = args.gate
    phase, threshold, why = wf.freshness_threshold(now_et)
    if args.cutoff:
        hh, mm = (int(x) for x in args.cutoff.split(":"))
        threshold = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
        phase, why = "CUSTOM", f"must be updated after {threshold:%I:%M %p} today"
    if gate == "off":
        # Deliberately NOT nulling `threshold` here (as an earlier version
        # did). choose_sources reads "threshold is None" as "no window
        # exists this week at all" -- correct for EARLY WEEK, wrong for gate
        # off, which is an explicit override of a REAL window, not a claim
        # that no window exists. Nulling it made every FP board look
        # "already inside the window" and skip the backup check entirely, so
        # `--gate off` silently stopped finding Ratcliffe's fresher FTN
        # board and fell back to a stale FP one. The real threshold still
        # flows through for the backup-check decision and the freshness TAG
        # shown in output; `gate == "off"` does its actual job -- bypassing
        # accept/reject -- at the one place that checks it, same mechanism
        # as a manual pick.
        why = f"{why} (gate off -- not required to meet it)"

    # FTN covers Ratcliffe and Orginski, whom FP does not list in its panel.
    # One request serves every slot and format, so fetch it up front -- but a
    # dead login must degrade to "FP only", never take the run down.
    ftn_data = None
    if not args.no_ftn and any(s.get("ftn_analyst") for s in wf.SOURCE_PRIORITY):
        try:
            ftn_data = ftn_weekly.fetch(session=session)
        except Exception as exc:
            print(f"WARNING: FTN unavailable ({type(exc).__name__}: {exc}) -- "
                  f"continuing with FantasyPros only.", file=sys.stderr)

    scorings = ["HALF", "PPR", "STD"] if args.scoring == "all" else [args.scoring]
    lists = []
    for sc in scorings:
        for pair in wf.paste_order(sc):
            if pair not in lists:
                lists.append(pair)

    year, week = args.year, args.week
    if not (year and week):
        year, week = resolve_week(session)
        if not (year and week):
            sys.exit("Could not determine the current week from FP.")
    elif gate == "strict":
        # Freshness comes from FP's LIVE panel, which only ever describes the
        # current week. Gating a past week against today's timestamps is
        # meaningless, so refuse rather than hand back a confident wrong answer.
        live_year, live_week = resolve_week(session)
        if (str(year), str(week)) != (str(live_year), str(live_week)):
            sys.exit(
                f"Refusing: you asked for {year} week {week}, but FP's freshness "
                f"data only covers the live week ({live_year} week {live_week}), "
                f"so --gate strict would be judging old boards against today's "
                f"clock.\nRe-run with --gate off to build that week anyway.")
    print(f"Week {week} of {year} | {phase} | {why}")
    if manual_sources:
        print(f"Manual source selection (freshness check waived for these): "
              f"{', '.join(sorted(manual_sources))}")
    print(f"Building {len(lists)} list(s): "
          f"{', '.join(f'{s}/{c}' for s, c in lists)}\n")

    epochs, epoch_errors = panel_epochs(lists, session, workers=args.workers)
    for key, err in epoch_errors:
        print(f"WARNING: freshness for {key[0]}/{key[1]} failed -- {err}",
              file=sys.stderr)

    fetched, fetch_errors = fetch_everything(
        lists, year, week, session, workers=args.workers)
    for key, err in fetch_errors:
        print(f"WARNING: fetch {key[0]} {key[1]}/{key[2]} failed -- {err}",
              file=sys.stderr)

    out_dir = wc.ensure_dir(os.path.join(args.out_root, f"{year}-wk{int(week):02d}"))

    # Boards captured by hand (Jahnke via PFF+, Thorman when a route exists).
    # They compete like any other origin and face the same freshness gate.
    cached = cached_source.load_all(out_dir)
    if cached:
        for p, v in sorted(cached.items()):
            print(f"  cached: {p} ({v.get('origin', '?')}, "
                  f"{len(cached_source.slot_summary(v))} lists)")
            stale_keys = []
            for key, (age_hours, is_stale) in sorted(cached_source.staleness(v).items()):
                if age_hours is None:
                    stale_keys.append(f"{key}: no timestamp")
                elif is_stale:
                    stale_keys.append(f"{key}: {age_hours:.1f}h old")
            if stale_keys:
                print(f"    STALE (>12h, no live check for a newer post): "
                      f"{', '.join(stale_keys)} -- consider refreshing before this run")
        print()
    gating, manifest = {}, []

    for scoring in scorings:
        blends, priorities, stamps = {}, {}, {}
        for slot, slot_scoring in wf.paste_order(scoring):
            chosen, skipped = choose_sources(
                slot, slot_scoring, fetched, epochs.get((slot, slot_scoring), {}),
                threshold, gate, ftn_data, cached, phase, manual_sources=manual_sources)
            gating[(slot, slot_scoring)] = {
                "used": [{"label": c["label"], "freshness": c["freshness"],
                          "updated": c["updated"], "origin": c["origin"],
                          "considered": c["considered"]}
                         for c in chosen],
                "skipped": skipped,
            }
            if not chosen:
                print(f"  {slot:4s}/{slot_scoring:4s}  NO SOURCES PASSED "
                      f"({', '.join(s['reason'] for s in skipped) or 'none'})")
                continue

            priority = [c["label"] for c in chosen]
            priorities[slot] = priority
            stamps[slot] = {c["label"]: c["updated"] for c in chosen}
            lists_by_source = {
                c["label"]: wc.normalize_rows(c["players"]) for c in chosen}
            blends[slot] = wc.blend_slot(lists_by_source, priority)
            weights = wc.source_weights(len(priority))
            def _describe(c, w):
                tag = f"{c['label'].split()[-1]} {w}x [{c['origin']} {c['updated']}]"
                if c["considered"]:
                    # A backup WAS checked (non-lock phase, or FP missed the
                    # window) -- show what lost so "checked, FP still won" is
                    # visibly different from "never checked at all".
                    runners_up = [o for o in c["considered"] if o["origin"] != c["origin"]]
                    if runners_up:
                        tag += " beat " + ", ".join(
                            f"{o['origin']} {o['updated']}" for o in runners_up)
                return tag

            print(f"  {slot:4s}/{slot_scoring:4s}  {len(blends[slot]):>4d} players  "
                  + ", ".join(_describe(c, w) for c, w in zip(chosen, weights)))

        # Reconcile the flex against the position lists, as FP would.
        if "FLX" in blends:
            flex_keys = [k for k, _ in blends["FLX"]]
            pos_lists = {s: [k for k, _ in blends[s]]
                         for s in ("RB", "WR", "TE") if s in blends}
            if pos_lists:
                before = wc.count_inversions(flex_keys, pos_lists)
                fixed = wf.reconcile_flex(flex_keys, pos_lists)
                after = wc.count_inversions(fixed, pos_lists)
                by_key = dict(blends["FLX"])
                blends["FLX"] = [(k, by_key[k]) for k in fixed]
                print(f"  FLX reconciled against positions: "
                      f"{before} inversions -> {after}")

        suffix = {"HALF": "", "PPR": "_ppr", "STD": "_std"}[scoring]
        for slot, records in blends.items():
            wc.write_slot_csv(
                os.path.join(out_dir, f"consensus_{slot.lower()}{suffix}.csv"),
                records, priorities[slot], timestamps=stamps.get(slot))
            wc.write_paste_csv(
                os.path.join(out_dir, f"paste_{slot.lower()}{suffix}.csv"), records)

        if not blends:
            print(f"  NOTHING PASSED THE GATE for {scoring}. Re-run with a "
                  f"later --cutoff, or --gate off to see the boards anyway.")
        book = wc.write_workbook(
            os.path.join(out_dir, f"rankings_{scoring.lower()}.xlsx"),
            blends, scoring, priorities, timestamps=stamps)
        if book is None and blends:
            print("  (openpyxl not installed -- skipped the workbook)")

        viewer = wc.write_viewer(
            os.path.join(out_dir, f"view_{scoring.lower()}.html"),
            blends, gating,
            {"title": f"Week {week} — {scoring} rankings",
             "subtitle": (f"Built {now_et.strftime('%a %b %d, %I:%M %p %Z')} · "
                          f"{phase} — {why} · paste in this order"),
             "order": wf.paste_order(scoring),
             "warning": ("Freshness gate OFF — sources were taken by priority, "
                         "not by update time.") if gate == "off" else None},
        )
        manifest.append({"scoring": scoring, "viewer": os.path.basename(viewer),
                         "slots": {s: len(r) for s, r in blends.items()}})

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({
            "year": year, "week": week,
            "phase": phase, "gate": gate,
            "threshold": threshold.isoformat() if threshold else None,
            "built_at": now_et.isoformat(),
            "formats": manifest,
            "gating": {f"{s}/{c}": v for (s, c), v in gating.items()},
        }, f, indent=2)

    print(f"\nWrote {out_dir}")
    for entry in manifest:
        print(f"  {entry['scoring']:4s} -> "
              f"{os.path.join(out_dir, entry['viewer'])}")

    if args.open_viewer and manifest:
        import webbrowser
        first = os.path.abspath(os.path.join(out_dir, manifest[0]["viewer"]))
        webbrowser.open("file:///" + first.replace("\\", "/"))

    if fetch_errors or epoch_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
