#!/usr/bin/env python3
"""The week's official injury report, read straight from the 32 club sites.

    python team_reports.py --year 2026 --week 8

nflverse's injury file lags the real report by a day or more -- Friday night of
week 8 2026 it still had Thursday's practice and no Sunday game statuses, so
the sheet showed Bucky Irving "DNP" for a Thursday rest day after he practiced
in full Friday (Joe, 2026-10-30: "each team has this kind of page",
buccaneers.com/team/injury-report/). Every club site carries the same page:
each player's Wed/Thu/Fri practice and his game status, for both teams in the
game.

Writes data/team_reports_<yr>_wk<NN>.csv (one row per skill player, with every
practice day), then brings that week's rows in data/injuries_<yr>.csv up to
date from it -- latest practice, game status, injury -- so the sheet, the
availability check and the player log all read the current report. Teams no
page carried keep their nflverse rows. refresh_inputs runs this right after it
downloads the nflverse file, which would otherwise put the stale rows back.
"""

import argparse
import csv
import datetime
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

CLUBS = {"ARI": "azcardinals.com", "ATL": "atlantafalcons.com", "BAL": "baltimoreravens.com",
         "BUF": "buffalobills.com", "CAR": "panthers.com", "CHI": "chicagobears.com",
         "CIN": "bengals.com", "CLE": "clevelandbrowns.com", "DAL": "dallascowboys.com",
         "DEN": "denverbroncos.com", "DET": "detroitlions.com", "GB": "packers.com",
         "HOU": "houstontexans.com", "IND": "colts.com", "JAX": "jaguars.com", "KC": "chiefs.com",
         "LV": "raiders.com", "LAC": "chargers.com", "LA": "therams.com",
         "MIA": "miamidolphins.com", "MIN": "vikings.com", "NE": "patriots.com",
         "NO": "neworleanssaints.com", "NYG": "giants.com", "NYJ": "newyorkjets.com",
         "PHI": "philadelphiaeagles.com", "PIT": "steelers.com", "SF": "49ers.com",
         "SEA": "seahawks.com", "TB": "buccaneers.com", "TEN": "tennesseetitans.com",
         "WAS": "commanders.com"}
# the pages' club-logo codes where they differ from nflverse
LOGO = {"AZ": "ARI", "WSH": "WAS", "JAC": "JAX", "LAR": "LA"}
SKILL = ("QB", "RB", "WR", "TE", "FB")
PRACTICE = {"DNP": "Did Not Participate In Practice",
            "LP": "Limited Participation in Practice",
            "FP": "Full Participation in Practice"}
STATUS = {"OUT": "Out", "DOUBTFUL": "Doubtful", "QUESTIONABLE": "Questionable"}


def _text(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse(page):
    """-> [{team, player, pos, injury, days: [(day, code)], status}] for every
    team table on one club page."""
    out = []
    for block in page.split("nfl-o-injury-report__container")[1:]:
        logo = re.search(r"clubs/logos/([A-Z]+)", block)
        table = re.search(r"<table.*?</table>", block, re.S)
        if not logo or not table:
            continue
        team = LOGO.get(logo.group(1), logo.group(1))
        heads = [_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", table.group(0), re.S)]
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(cells) != len(heads) or len(cells) < 5:
                continue
            days = list(zip(heads[3:-1], cells[3:-1]))
            out.append({"team": team, "player": cells[0], "pos": cells[1], "injury": cells[2],
                        "days": days, "status": STATUS.get(cells[-1].upper(), "")})
    return out


def fetch(week):
    """Every club's page for REG-<week>. -> ({(team, player): row}, {team})."""
    import requests
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    rows, seen = {}, set()
    for club, dom in CLUBS.items():
        try:
            r = sess.get(f"https://www.{dom}/team/injury-report/week/REG-{week}", timeout=30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 -- one club down must not stop the rest
            print(f"  FAIL  {club}: {e}")
            continue
        for p in parse(r.text):
            seen.add(p["team"])
            rows.setdefault((p["team"], p["player"]), p)
    return rows, seen


def latest(days):
    """The last day he was listed: (day, code), or (None, None)."""
    for d, c in reversed(days):
        if c in PRACTICE:
            return d, c
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()

    rows, seen = fetch(args.week)
    rows = {k: v for k, v in rows.items() if v["pos"] in SKILL}
    if not seen:
        sys.exit("  no club page had a report table -- nothing changed")

    import availability
    inj = os.path.join(DATA, f"injuries_{args.year}.csv")
    with open(inj, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        fields, allrows = rd.fieldnames, list(rd)
    wk = [r for r in allrows if r["week"] == str(args.week)]
    by_name = {(availability.norm_name(r["full_name"]), r["team"]): r["gsis_id"] for r in wk}
    pair, solo = availability._gsis_by_name(args.year)

    out, missed = [], []
    for (tm, nm), p in sorted(rows.items()):
        key = (availability.norm_name(nm), tm)
        pid = by_name.get(key) or pair.get(key) or solo.get(key[0])
        if not pid:
            missed.append(f"{nm} ({tm} {p['pos']})")
            continue
        day, code = latest(p["days"])
        out.append({**p, "gsis_id": pid, "day": day, "code": code})

    stamp = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    dest = os.path.join(DATA, f"team_reports_{args.year}_wk{args.week:02d}.csv")
    with open(dest + ".tmp", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gsis_id", "player", "pos", "team", "injury", "days", "practice", "game_status", "fetched"])
        for p in out:
            w.writerow([p["gsis_id"], p["player"], p["pos"], p["team"], p["injury"],
                        # "(-)" = not on that day's report; a blank day is not posted yet
                        ", ".join(f"{d} {'-' if c == '(-)' else c}" for d, c in p["days"] if c),
                        p["code"] or "",
                        p["status"], stamp])
    os.replace(dest + ".tmp", dest)

    # the week's rows in the nflverse file, brought up to date. Only teams a
    # page carried are touched; everyone else keeps what nflverse has.
    have = {r["gsis_id"]: r for r in wk}
    changed = added = 0
    for p in out:
        r = have.get(p["gsis_id"])
        if r is None:
            first, _, last = p["player"].partition(" ")
            r = {f: "" for f in fields}
            r.update(season=str(args.year), season_type="REG", game_type="REG", team=p["team"],
                     week=str(args.week), gsis_id=p["gsis_id"], position=p["pos"],
                     full_name=p["player"], first_name=first, last_name=last)
            allrows.append(r)
            have[p["gsis_id"]] = r
            added += 1
        new = {"report_status": p["status"],
               "practice_status": PRACTICE.get(p["code"], ""),
               "practice_primary_injury": p["injury"],
               "report_primary_injury": p["injury"] if p["status"] else r.get("report_primary_injury", "")}
        if any(r.get(k, "") != v for k, v in new.items()):
            changed += 1
            r.update(new)
    with open(inj + ".tmp", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(allrows)
    os.replace(inj + ".tmp", inj)

    gone = sorted(set(CLUBS) - seen)
    st = {s: sum(1 for p in out if p["status"] == s) for s in ("Out", "Doubtful", "Questionable")}
    print(f"  club pages: {len(seen)} teams, {len(out)} skill players "
          f"({st['Out']} Out, {st['Doubtful']} Doubtful, {st['Questionable']} Questionable)")
    if gone:
        print(f"  no table for: {', '.join(gone)} (bye, or not posted) -- nflverse rows kept")
    if missed:
        print(f"  not matched to a player id: {'; '.join(missed)}")
    print(f"  injuries_{args.year}.csv wk{args.week}: {changed} rows updated, {added} added "
          f"-> {os.path.basename(dest)}")


if __name__ == "__main__":
    main()
