#!/usr/bin/env python3
"""
Generate the weekly Reddit link-post markdown Joe posts to promote the
Stream-O-Matic tool -- matches his own 2025 example format exactly (title
line, three-best-defenses teaser sentence, a "Top 10" markdown table).

Must run AFTER finalize_live_sheet.py in the same session -- it reads the
Live tab's top 10 rows as-is, relying on finalize's sort-by-SCORE-descending
to already have the best defenses at the top.

Rost%/Start% are read via the Sheets API's default FORMATTED_VALUE
rendering, which returns the already-percent-formatted strings ("25%") set
up in push_yahoo_def_to_sheet.py -- no re-formatting needed here. Opp gets
a space inserted after "@" ("@TEN" -> "@ TEN") to match Joe's own example.

The post is written three places, because the Tuesday run now happens on
GitHub where a local file is useless: a local reddit_post.md, stdout (so
it's in the Actions log), and a "Reddit" tab on the sheet itself -- which
is the one Joe actually copies from.

On that tab the body is written ONE LINE PER ROW, not as a single
multi-line cell. A cell containing newlines gets quote-wrapped when you
copy it out to a plain text field like Reddit's; a column of one-line
cells pastes clean.

Usage:
    python generate_reddit_post.py --week 2   # -> reddit_post.md + sheet
    python generate_reddit_post.py --week 2 --no-sheet
"""

import argparse
from pathlib import Path

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"
POST_TAB = "Reddit"
TOOL_URL = "https://fantasysixpack.net/fantasy-football-defense-stream-o-matic/"


def format_opp(opp):
    return f"@ {opp[1:]}" if opp.startswith("@") else opp


def build_post(week, rows):
    top3 = ", ".join(r[1] for r in rows[:2]) + f" and {rows[2][1]}"

    title = (f"Week {week} Fantasy Football Defense Stream-O-Matic! "
              f"What defense should you play this week?")

    lines = [
        f"The [F6P Defense Stream-O-Matic]({TOOL_URL}) is updated and ready for Week {week}.",
        "",
        f"Early week data has the {top3} as the best three defenses for the week.",
        "",
        "Who are you streaming this week?",
        "",
        "Here is the Top 10 from the tool. Check out the rest on Fantasy Six Pack.",
        "",
        "|SCORE|Team|Rost%|Start%|Opp|",
        "|:-|:-|:-|:-|:-|",
    ]
    for score, team, rost, start, opp in rows:
        lines.append(f"|{score}|{team}|{rost}|{start}|{format_opp(opp)}|")

    return title, "\n".join(lines)


def push_to_sheet(sheet, title, body):
    """Publish the post to its own tab: title in A1, body from A3 down."""
    meta = sheet.get(spreadsheetId=SHEET_ID).execute()
    tabs = {sh["properties"]["title"]: sh["properties"]["sheetId"]
            for sh in meta["sheets"]}

    if POST_TAB not in tabs:
        resp = sheet.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
            {"addSheet": {"properties": {"title": POST_TAB}}}
        ]}).execute()
        gid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
        # Wide column A -- these lines are long and the default width makes
        # the post unreadable without clicking into every cell.
        sheet.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
            {"updateDimensionProperties": {
                "range": {"sheetId": gid, "dimension": "COLUMNS",
                          "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 720}, "fields": "pixelSize"}}
        ]}).execute()
        print(f"Created '{POST_TAB}' tab.")

    # Clear first: last week's post may have had more rows than this one,
    # and leftover lines at the bottom would get copied along with it.
    sheet.values().clear(spreadsheetId=SHEET_ID, range=f"{POST_TAB}!A:C",
                         body={}).execute()

    values = [[title], [""]] + [[line] for line in body.splitlines()]
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{POST_TAB}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()

    # Off to the side so it never gets caught in a column-A copy.
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{POST_TAB}!C1",
        valueInputOption="RAW",
        body={"values": [["Post title = A1. Post body = A3 down."],
                         ["Select the cells, copy, paste into Reddit."],
                         ["Overwritten by every Tuesday full run."]]},
    ).execute()

    print(f"Published post to the '{POST_TAB}' tab "
          f"(title A1, body A3:A{len(values)}).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--out", default="reddit_post.md")
    ap.add_argument("--no-sheet", action="store_true",
                    help="write the local file only, don't touch the Reddit tab")
    args = ap.parse_args()

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    resp = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!A2:E11").execute()
    rows = resp.get("values", [])
    if len(rows) < 10:
        raise SystemExit(f"Only found {len(rows)} rows in {TAB}!A2:E11 (need 10) -- "
                          "did finalize_live_sheet.py run first?")

    title, body = build_post(args.week, rows)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(f"{title}\n\n{body}\n")

    print(f"Wrote Reddit post markdown to {args.out}")

    if not args.no_sheet:
        push_to_sheet(sheet, title, body)

    print()
    print("=" * 60)
    print("TITLE:", title)
    print("=" * 60)
    print(body)


if __name__ == "__main__":
    main()
