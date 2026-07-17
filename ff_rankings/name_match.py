"""
Name/team normalization for matching players across rankings sources.

Ported from ff_draft_proj/build_consensus.py (same approach: strip accents,
punctuation, suffixes, and a small alias map for known cross-source nickname
mismatches). Extended here with a few extra team-code aliases seen in FTN's
rankings feed (ARZ/BLT/HST/INA), which uses different abbreviations than the
other three sources.
"""

import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

DST_NAMES = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAC": "Jacksonville Jaguars",
    "KC":  "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV":  "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE":  "New England Patriots",
    "NO":  "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SF":  "San Francisco 49ers",
    "SEA": "Seattle Seahawks",
    "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


def dst_name(team_code):
    """Return the canonical full DST name for a team code, or None if unknown."""
    return DST_NAMES.get(team_code)

STATUS_TOKENS = {"o", "q", "d", "ir", "pup", "sus", "na", "dnp", "ps", "nfi", "uns"}

TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAC", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NYG",
    "NYJ", "NE", "NO", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS", "FA",
}
TEAM_ALIASES = {
    "JAX": "JAC", "WSH": "WAS", "LA": "LAR", "NA": "FA", "UNS": "FA",
    "ARZ": "ARI", "BLT": "BAL", "HST": "HOU", "INA": "IND",
}

NAME_ALIASES = {
    "cameron skattebo": "cam skattebo",
    "joquavioius marks": "woody marks",
    "joquavious marks": "woody marks",
    "mitchell trubisky": "mitch trubisky",
    "joshua palmer": "josh palmer",
    "mitchell tinsley": "mitch tinsley",
    "matthew hibner": "matt hibner",
    "andrew ogletree": "drew ogletree",
    "m valdes scantling": "marquez valdes scantling",
    "chigoziem okonkwo": "chig okonkwo",
    "cameron ward": "cam ward",
    "jamarion miller": "jam miller",
    "nathaniel dell": "tank dell",
    "christopher brooks": "chris brooks",
    "kenny gainwell": "kenneth gainwell",
    "james cook iii": "james cook",
}


def clean_name(name):
    name = name.replace("\xa0", " ").replace("&nbsp;", " ")
    parts = name.split()
    while parts and parts[-1].lower() in STATUS_TOKENS:
        parts.pop()
    return " ".join(parts)


def clean_team(team):
    team = (team or "").strip().upper()
    team = TEAM_ALIASES.get(team, team)
    return team if team in TEAMS else "FA"


DISPLAY_OVERRIDES = {
    "kenneth walker": "Kenneth Walker III",
}


def display_name(name):
    """Strip generational suffixes from a display name, then restore any
    that are part of the player's official name via DISPLAY_OVERRIDES."""
    parts = name.split()
    while parts and parts[-1].rstrip(".").lower() in SUFFIXES:
        parts.pop()
    result = " ".join(parts)
    return DISPLAY_OVERRIDES.get(result.lower(), result)


def normalize_name(name):
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    parts = name.split()
    while parts and parts[-1] in SUFFIXES:
        parts.pop()
    key = " ".join(parts)
    return NAME_ALIASES.get(key, key)
