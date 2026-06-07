# Fantasy Football Consensus ADP — Automation Project

## Goal
Stop manually downloading per-site ADP and pasting it into a Google Sheet. The
sheet **already has the merge and consensus formula working** — do NOT rebuild
that. The only job is to **pull each site's ADP directly from that site** (no
aggregators / third-party collector sites) and get the values into the matching
per-site columns. Eventually run it on a schedule on my own machine.

## Hard preference
**Pull each number from the source platform itself**, not from a site that
re-publishes other sites' ADP. The ESPN script (`fetch_espn_adp.py`) is the model:
it calls ESPN's own API. Build every other column the same way.

## The sheet's column layout (match this exactly)
```
Player | Position(s) | Team | Sleeper | ESPN | Yahoo! | CBS | Fantrax | NFL | FFPC | BB10s | NFFC | Consensus
```
`Consensus` is calculated in the sheet — never compute or overwrite it.

## Direct source for each column
| Column | Source platform | How to pull it directly | Status |
|---|---|---|---|
| ESPN | ESPN fantasy API | `fetch_espn_adp.py` — `lm-api-reads.fantasy.espn.com/.../players?view=kona_player_info` + `X-Fantasy-Filter` header; read `ownership.averageDraftPosition` (true decimal). No login. | **Built**, validated on samples, needs a live run |
| NFFC | `nfc.shgn.com/adp/football` (public, no login) | Table loads via a background call and shows "Loading…", but the page has a **Download** button. Open DevTools → Network, click Download, capture the export URL + filter params, replicate with `requests`. | Find endpoint live |
| BB10s | Same `nfc.shgn.com/adp/football` page | Set the contest filter to **BestBall10s**, then use the same Download/export capture. One source covers both NFFC and BB10s. | Find endpoint live |
| Yahoo! | Yahoo Fantasy Sports API (official) | OAuth2 (free Yahoo developer app key/secret + one-time login). Use the player **draft analysis** field for average pick = ADP. Python: `yahoo_fantasy_api` + `yahoo_oauth`, or `yfpy`. | Needs OAuth setup |
| Fantrax | My dummy Fantrax league | Unofficial API via the `fantraxapi` Python package, using my logged-in session cookie. Pull ADP for the league. | Needs my session cookie |
| NFL | NFL.com fantasy (`api.fantasy.nfl.com`) | Open NFL.com's draft rankings/ADP page, DevTools → Network, find the JSON request behind it, replicate. | Find endpoint live |
| FFPC | `myffpc.com` ADP page (public) | DevTools → Network to find the data call (or scrape the table if server-rendered). | Find endpoint live |
| CBS | CBS Sports fantasy ADP page | DevTools → Network on the CBS ADP/draft averages page; replicate the data call (login may be required). | Find endpoint live |
| Sleeper | `api.sleeper.app` | **Hardest — no packaged ADP exists.** Two honest options: (a) compute ADP yourself by pulling recent Sleeper drafts and averaging pick numbers, or (b) use the Sleeper feed FTN publishes daily (`ftnfantasy.com/fantasy/nfl/adp`). Pick one with me. | Decide approach |

## The general technique for any source above
Open the platform's ADP page → browser DevTools → Network tab → filter to
Fetch/XHR → reload or click the page's Download/export → find the request that
returns the ADP (usually JSON or a CSV export) → replicate it in Python with
`requests`. ESPN already works this way; do the same for the rest.

## Conventions / ground rules
- Send a normal `User-Agent`. Fetch each source **once per day and cache**. Don't hammer endpoints. Personal use of my own/public data.
- Output per-site CSVs (or one combined CSV) in the sheet's column order so they import/paste cleanly. Player matching is already handled in my sheet, so each CSV just needs clean Player / Position / Team + the ADP value.
- Keep credentials (Yahoo OAuth token, Fantrax cookie) out of the code — use a local `.env` or config file, never commit them.

## Suggested next steps (in order)
1. Run `fetch_espn_adp.py` live; confirm the real ESPN numbers come back clean.
2. NFFC + BB10s: capture the `nfc.shgn.com` Download/export endpoint and build one puller for both.
3. NFL, FFPC, CBS: capture each page's data call and build a puller each.
4. Yahoo: set up the OAuth app and pull draft-analysis ADP.
5. Fantrax: wire up `fantraxapi` with my session cookie.
6. Sleeper: decide compute-from-drafts vs the FTN feed, then build it.
7. Combine into one runner + daily schedule (cron / Task Scheduler); optional direct write to Google Sheets via the Sheets API.

## Notes
- An earlier aggregator script (`fetch_draftbuddy_adp.py`) was set aside — I want source-of-truth values, not a collector site. Ignore/delete it.
- Scripts here were written in a sandbox **without internet**, so they're validated on sample data only; first task for anything is a live run.
- Deps so far: `requests`, plus `beautifulsoup4` + `lxml` for any HTML scraping. Add `yahoo_fantasy_api`/`yfpy` and `fantraxapi` when you reach those.
