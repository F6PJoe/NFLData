"""
Shared team-name/abbreviation normalization for the ff_defense fetchers.

The Live tab's Team column (B) holds full nicknames ("Buccaneers"); the
Opp column (E) holds abbreviations, sometimes "@"-prefixed ("@KC"). Each
outside source has its own quirks on top of that -- FTN and nflverse both
use "JAX" for the Jaguars, eatdrinkandsleepfootball.com's team-page links
use stale city-based codes (stl/sd/oak) left over from past relocations
even though the displayed team names are current, and nflverse uses "LA"
for the Rams (not "LAR"). normalize() takes any of these forms and
returns one consistent abbreviation to key lookups by.
"""

NAME_TO_ABBR = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF",
    "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN", "Browns": "CLE",
    "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAC", "Chiefs": "KC",
    "Chargers": "LAC", "Rams": "LAR", "Raiders": "LV", "Dolphins": "MIA",
    "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "Seahawks": "SEA",
    "49ers": "SF", "Buccaneers": "TB", "Titans": "TEN", "Commanders": "WAS",
}

TEAM_ALIASES = {"JAX": "JAC", "STL": "LAR", "SD": "LAC", "OAK": "LV", "LA": "LAR"}


def normalize(name_or_abbr):
    """Full nickname, abbreviation, or "@ABBR" -> this sheet's standard abbreviation."""
    abbr = NAME_TO_ABBR.get(name_or_abbr, name_or_abbr.strip().lstrip("@").upper())
    return TEAM_ALIASES.get(abbr, abbr)


ABBR_TO_NAME = {abbr: name for name, abbr in NAME_TO_ABBR.items()}


def abbr_to_nickname(abbr):
    """"PHI" (or "JAX", "@PHI") -> "Eagles" -- what column B actually holds.

    Needed since the team list moved to nflverse's schedule, which speaks
    abbreviations while the sheet's Team column speaks nicknames.
    """
    return ABBR_TO_NAME.get(normalize(abbr), abbr)


def nickname_to_abbr(full_name):
    """"San Francisco 49ers" -> "SF" (matches by the name's last word)."""
    return normalize(full_name.split()[-1])
