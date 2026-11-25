#!/usr/bin/env python3
"""The week's projections -> Joe's "Weekly Football Projections" Google Sheet (2026-11-24, Joe: "could we
put the projection output on google sheets too? I need to be able to access it and so does the rankings
process").

Tabs (same names every week, so links and readers never change):
  Projections  data/projections_<yr>_wk<NN>.csv as it stands after the latest run (with Joe's calls) --
               exactly the CSV's columns, so ff_rankings/model_source.py can read it in place of the file
  Locked       the frozen lock (projections_<yr>_wk<NN>_final.csv) -- what gets scored
  Info         season, week, when each tab was written, and by which run

Called at the end of lock.py and rerun.py; a failure never fails the run. Config:
data/projections_gsheet.json {"id": "<sheet id>"}; credentials as calls_gsheet.py.

    python projections_gsheet.py --year 2026 --week 12
"""
import argparse
import csv
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CONF = os.path.join(DATA, "projections_gsheet.json")
sys.path.insert(0, HERE)


def _sheets():
    import calls_gsheet
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=calls_gsheet._drive()._http.credentials, cache_discovery=False)


def _vals(path):
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.reader(fh)):
            if i == 0:
                out.append(row)
                continue
            r = []
            for x in row:
                try:
                    r.append(float(x) if x not in ("",) and not x.startswith("00-") else x)
                except ValueError:
                    r.append(x)
            out.append(r)
    return out


def push(year, week, what="run"):
    if not os.path.exists(CONF):
        return False
    sid = json.load(open(CONF))["id"]
    base = os.path.join(DATA, f"projections_{year}_wk{week:02d}")
    try:
        s = _sheets()
        meta = s.spreadsheets().get(spreadsheetId=sid, fields="sheets(properties(sheetId,title))").execute()
        tabs = {x["properties"]["title"]: x["properties"]["sheetId"] for x in meta["sheets"]}
        reqs = []
        if "Projections" not in tabs and "Sheet1" in tabs:
            reqs.append({"updateSheetProperties": {"properties": {"sheetId": tabs.pop("Sheet1"), "title": "Projections"},
                                                   "fields": "title"}})
            tabs["Projections"] = None
        for t in ("Projections", "Locked", "Info"):
            if t not in tabs:
                reqs.append({"addSheet": {"properties": {"title": t}}})
        if reqs:
            s.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
        now = f"{datetime.datetime.now():%Y-%m-%d %I:%M %p} ET"
        info = {}
        try:
            for row in s.spreadsheets().values().get(spreadsheetId=sid, range="Info!A1:B10").execute().get("values", []):
                if len(row) >= 2:
                    info[row[0]] = row[1]
        except Exception:
            pass
        done = []
        for tab, path in (("Projections", base + ".csv"), ("Locked", base + "_final.csv")):
            if not os.path.exists(path):
                continue
            if tab == "Locked" and info.get("Locked file") == f"{os.path.getmtime(path):.0f}" \
                    and info.get("Week") == str(week):
                continue                          # the lock has not changed since it was written
            v = _vals(path)
            s.spreadsheets().values().clear(spreadsheetId=sid, range=tab).execute()
            s.spreadsheets().values().update(spreadsheetId=sid, range=f"{tab}!A1", valueInputOption="RAW",
                                             body={"values": v}).execute()
            info[f"{tab} written"] = now
            if tab == "Locked":
                info["Locked file"] = f"{os.path.getmtime(path):.0f}"
            done.append(f"{tab} {len(v) - 1}")
        if not os.path.exists(base + "_final.csv") and info.get("Week") != str(week):
            s.spreadsheets().values().clear(spreadsheetId=sid, range="Locked").execute()
            info["Locked written"] = "(no lock yet this week)"
            info.pop("Locked file", None)
        info.update({"Season": str(year), "Week": str(week), "Last run": f"{what} {now}"})
        order = ["Season", "Week", "Last run", "Projections written", "Locked written", "Locked file"]
        s.spreadsheets().values().clear(spreadsheetId=sid, range="Info").execute()
        s.spreadsheets().values().update(spreadsheetId=sid, range="Info!A1", valueInputOption="RAW",
                                         body={"values": [[k, info[k]] for k in order if k in info]}).execute()
        print(f"  projections sheet: {', '.join(done) or 'nothing new'} rows -> Google Sheet (week {week})")
        return True
    except Exception as e:
        print(f"  WARN  projections sheet  not updated ({type(e).__name__}: {str(e)[:150]})")
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--what", default="manual")
    a = ap.parse_args()
    push(a.year, a.week, a.what)
