#!/usr/bin/env python3
"""Game-time weather for outdoor games -- forecast (live) and history (backtests). 2026-11-26.

Joe 2026-11-26 (KC@BUF, 35 mph gusts + heavy rain): "I thought we had weather pulling ahead of time. please fix
that". The adopted wind / cold rules (project.py WX_SCALE, WIND_PASS_PENALTY) read wind and temp from nflverse's
games.csv, which fills them only AFTER a game -- so they never fired on a live projection. This fills the gap:

  forecast(year, week)  Open-Meteo forecast at each outdoor game's kickoff hour ->
                        data/weather_<yr>_wk<NN>.csv (wind / gust mph, temp F, rain mm over the game's 3 hours)
  history(seasons)      Open-Meteo archive for every outdoor game 2021+ -> data/weather_hist.csv (same columns),
                        for the heavy-rain study and backtests

Open-Meteo is free with no key (api.open-meteo.com / archive-api.open-meteo.com). Times are asked in ET (the
schedule's clock). Domes and closed roofs are skipped; retractable roofs ("open" / blank) count as outdoors.

    python weather.py --year 2026 --week 12
    python weather.py --history 2021 2026
"""
import argparse
import csv
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# stadium_id (nflverse games.csv) -> (lat, lon)
STADIUMS = {
    "ATL97": (33.755, -84.401), "BAL00": (39.278, -76.623), "BOS00": (42.091, -71.264),
    "BUF00": (42.774, -78.787), "BUF01": (42.774, -78.787), "CAR00": (35.226, -80.853), "CHI98": (41.862, -87.617),
    "CIN00": (39.095, -84.516), "CLE00": (41.506, -81.700), "DAL00": (32.748, -97.093),
    "DEN00": (39.744, -105.020), "DET00": (42.340, -83.046), "GNB00": (44.501, -88.062),
    "HOU00": (29.685, -95.411), "IND00": (39.760, -86.164), "JAX00": (30.324, -81.637),
    "KAN00": (39.049, -94.484), "LAX01": (33.953, -118.339), "MIA00": (25.958, -80.239),
    "MIN01": (44.974, -93.258), "NAS00": (36.166, -86.771), "NOR00": (29.951, -90.081),
    "NYC01": (40.814, -74.074), "PHI00": (39.901, -75.168), "PHO00": (33.528, -112.263),
    "PIT00": (40.447, -80.016), "SEA00": (47.595, -122.332), "SFO01": (37.403, -121.970),
    "TAM00": (27.976, -82.503), "VEG00": (36.091, -115.184), "WAS00": (38.908, -76.864),
    "LON00": (51.556, -0.280), "LON01": (51.456, -0.341), "LON02": (51.604, -0.066), "GER00": (48.219, 11.625),
    "MUN01": (48.219, 11.625), "FRA00": (50.069, 8.645), "MEX00": (19.303, -99.150),
    "SAO00": (-23.545, -46.474), "MAD01": (40.453, -3.688), "RIO00": (-22.912, -43.230),
    "PAR00": (48.924, 2.360), "MEL00": (-37.820, 144.983), "DUB00": (53.361, -6.251),
}
COVERED = ("dome", "closed")
RETRACTABLE = ("ATL97", "DAL00", "HOU00", "IND00", "PHO00")   # counted only when the roof was OPEN (known after)
COLS = ["game_id", "season", "week", "home_team", "away_team", "gameday", "gametime", "roof",
        "wind", "gust", "temp", "rain_mm", "source"]
HOURLY = "wind_speed_10m,wind_gusts_10m,temperature_2m,precipitation"


def _get(url, params, tries=3):
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "weekly-model"}),
                                        timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def _games(filter_fn):
    out = []
    for r in csv.DictReader(open(os.path.join(DATA, "games.csv"), encoding="utf-8")):
        if r.get("game_type") != "REG" or not filter_fn(r):
            continue
        if (r.get("roof") or "").lower() in COVERED or r.get("stadium_id") not in STADIUMS:
            continue
        if r.get("stadium_id") in RETRACTABLE and (r.get("roof") or "").lower() != "open":
            continue                          # before the game: assume the roof is closed
        out.append(r)
    return out


def _at_game(h, gameday, gametime):
    """the game's 3 hours from the hourly block (times are ET) -> wind, gust, temp at kickoff, rain total."""
    t0 = datetime.datetime.strptime(f"{gameday} {gametime or '13:00'}", "%Y-%m-%d %H:%M")
    idx = {t: i for i, t in enumerate(h["time"])}
    hrs = [idx.get((t0.replace(minute=0) + datetime.timedelta(hours=k)).strftime("%Y-%m-%dT%H:%M")) for k in range(4)]
    hrs = [i for i in hrs if i is not None]
    if not hrs:
        return None
    k = hrs[0]
    v = lambda key, i: h[key][i] if h.get(key) and h[key][i] is not None else None
    return {"wind": v("wind_speed_10m", k), "gust": v("wind_gusts_10m", k), "temp": v("temperature_2m", k),
            "rain_mm": round(sum(v("precipitation", i) or 0.0 for i in hrs[:3]), 2)}


def _row(r, w, source):
    return dict(game_id=r["game_id"], season=r["season"], week=r["week"], home_team=r["home_team"],
                away_team=r["away_team"], gameday=r["gameday"], gametime=r.get("gametime", ""),
                roof=r.get("roof", ""), wind=_r(w["wind"]), gust=_r(w["gust"]), temp=_r(w["temp"]),
                rain_mm=w["rain_mm"], source=source)


def _r(x):
    return "" if x is None else round(x, 1)


def forecast_path(year, week):
    return os.path.join(DATA, f"weather_{year}_wk{week:02d}.csv")


def forecast(year, week, quiet=False):
    """the week's outdoor games: forecast at kickoff (or the archive for games already played)."""
    games = _games(lambda r: r["season"] == str(year) and r["week"] == str(week))
    rows = []
    today = datetime.date.today()
    for r in games:
        lat, lon = STADIUMS[r["stadium_id"]]
        day = datetime.date.fromisoformat(r["gameday"])
        try:
            if (day - today).days > 15:
                continue
            h = _get("https://api.open-meteo.com/v1/forecast",
                     {"latitude": lat, "longitude": lon, "hourly": HOURLY, "wind_speed_unit": "mph",
                      "temperature_unit": "fahrenheit", "timezone": "America/New_York",
                      "start_date": r["gameday"], "end_date": (day + datetime.timedelta(days=1)).isoformat()})["hourly"]
            w = _at_game(h, r["gameday"], r.get("gametime"))
            if w:
                rows.append(_row(r, w, f"forecast {datetime.datetime.now():%m-%d %H:%M}"))
        except Exception as e:
            print(f"  WARN  weather            {r['away_team']}@{r['home_team']}: {type(e).__name__}")
    if rows:
        with open(forecast_path(year, week), "w", newline="", encoding="utf-8") as fh:
            w_ = csv.DictWriter(fh, fieldnames=COLS)
            w_.writeheader()
            w_.writerows(rows)
    if not quiet:
        bad = [f"{x['away_team']}@{x['home_team']} wind {x['wind']} gust {x['gust']} rain {x['rain_mm']}mm"
               for x in rows if (x["wind"] or 0) >= 10 or (x["rain_mm"] or 0) >= 2]
        print(f"  ok    weather            {len(rows)} outdoor games" + (f"; notable: {'; '.join(bad)}" if bad else ""))
    return rows


def load(year, week=None):
    """{(home_team, week): row} from the week's forecast file (live) and the history file (backtests)."""
    out = {}
    hp = os.path.join(DATA, "weather_hist.csv")
    if os.path.exists(hp):
        for r in csv.DictReader(open(hp, encoding="utf-8")):
            if r["season"] == str(year):
                out[(r["home_team"], int(r["week"]))] = r
    import glob
    for fp in sorted(glob.glob(os.path.join(DATA, f"weather_{year}_wk*.csv"))):
        for r in csv.DictReader(open(fp, encoding="utf-8")):
            out.setdefault((r["home_team"], int(r["week"])), r)     # the archive (actual) wins over a forecast
    return out


def history(y0, y1):
    """archive weather for every outdoor game in seasons y0..y1 -> data/weather_hist.csv"""
    games = _games(lambda r: y0 <= int(r["season"]) <= y1 and r.get("home_score") not in ("", None))
    by_st = {}
    for r in games:
        by_st.setdefault(r["stadium_id"], []).append(r)
    rows = []
    for sid, gs in sorted(by_st.items()):
        lat, lon = STADIUMS[sid]
        d0 = min(g["gameday"] for g in gs)
        d1 = max(g["gameday"] for g in gs)
        d1 = (datetime.date.fromisoformat(d1) + datetime.timedelta(days=1)).isoformat()
        try:
            h = _get("https://archive-api.open-meteo.com/v1/archive",
                     {"latitude": lat, "longitude": lon, "hourly": HOURLY, "wind_speed_unit": "mph",
                      "temperature_unit": "fahrenheit", "timezone": "America/New_York",
                      "start_date": d0, "end_date": d1})["hourly"]
        except Exception as e:
            print(f"  {sid}: archive failed ({type(e).__name__})")
            continue
        for g in gs:
            w = _at_game(h, g["gameday"], g.get("gametime"))
            if w:
                rows.append(_row(g, w, "archive"))
        print(f"  {sid}: {len(gs)} games", flush=True)
        time.sleep(1)
    with open(os.path.join(DATA, "weather_hist.csv"), "w", newline="", encoding="utf-8") as fh:
        w_ = csv.DictWriter(fh, fieldnames=COLS)
        w_.writeheader()
        w_.writerows(sorted(rows, key=lambda x: x["game_id"]))
    print(f"  weather history: {len(rows)} outdoor games -> weather_hist.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--history", type=int, nargs=2)
    a = ap.parse_args()
    if a.history:
        history(*a.history)
    else:
        forecast(a.year, a.week)
