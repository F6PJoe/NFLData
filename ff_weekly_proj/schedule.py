"""
ESPN schedule utility: current NFL week detection and team-opponent lookup.

Uses ESPN's public proTeamSchedules API to determine the current NFL scoring
period (week) and build a {team_abbr: opponent_abbr} dict for that week.
Teams on bye will be absent from the returned opponents dict.

Usage:
    import schedule
    week, opponents = schedule.get_schedule(year=2026)
    week, opponents = schedule.get_schedule(year=2026, week=3)  # override week

Requires: requests
"""

import datetime
import json

SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal projections tool)"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

TEAM_ALIASES = {"JAX": "JAC", "WSH": "WAS"}


def _normalize(abbr):
    return TEAM_ALIASES.get(abbr, abbr)


def _load_schedule_data(year, json_file=None):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    import requests
    resp = requests.get(SCHEDULE_URL.format(year=year), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _detect_week(teams_data):
    """Find the scoring period whose games are closest to (but not yet past) today.
    Falls back to the highest-numbered week with games if all are in the past."""
    now_ms = datetime.datetime.now().timestamp() * 1000
    # Build {period: earliest_game_date_ms}
    period_dates = {}
    for team in teams_data:
        for period_str, games in team.get("proGamesByScoringPeriod", {}).items():
            period = int(period_str)
            for game in games:
                date_ms = game.get("date", 0)
                if not date_ms:
                    continue
                if period not in period_dates or date_ms < period_dates[period]:
                    period_dates[period] = date_ms

    if not period_dates:
        return 1

    # Include periods whose first game starts within the next 4 days (Thu cutoff)
    cutoff = now_ms + 4 * 86400 * 1000
    candidates = {p: d for p, d in period_dates.items() if d <= cutoff}
    if candidates:
        return max(candidates.keys())
    return min(period_dates.keys())


def get_schedule(year, week=None, json_file=None):
    """Return (week_number, {team_abbr: opp_abbr}).

    Teams on bye are absent from the opponents dict — fetchers should default
    to "" for those players.
    """
    data = _load_schedule_data(year, json_file)
    teams = data.get("settings", {}).get("proTeams", []) or data.get("proTeams", [])

    if week is None:
        week = _detect_week(teams)

    id_to_abbr = {t["id"]: ESPN_TEAM.get(t["id"], "") for t in teams}
    week_str = str(week)
    opponents = {}

    for team in teams:
        team_id = team["id"]
        abbr = ESPN_TEAM.get(team_id)
        if not abbr or abbr == "FA":
            continue
        games = team.get("proGamesByScoringPeriod", {}).get(week_str, [])
        if not games:
            continue  # bye
        game = games[0]
        away_id = game.get("awayProTeamId", 0)
        home_id = game.get("homeProTeamId", 0)
        opp_id = home_id if team_id == away_id else away_id
        opp_abbr = id_to_abbr.get(opp_id, "")
        if opp_abbr and opp_abbr != "FA":
            opponents[abbr] = opp_abbr

    return week, opponents
