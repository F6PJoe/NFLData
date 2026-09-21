"""Team abbreviation normalization, matching the ff_draft_proj convention.

nflverse uses `LA` for the Rams and `JAX` for Jacksonville; the rest of this
repo standardizes on `LAR` and `JAC` (see ff_draft_proj's clean_team /
TEAM_ALIASES). Normalize on the way in so joins downstream are clean.
"""

TEAM_ALIASES = {
    "LA": "LAR",     # nflverse uses LA for the Rams
    "JAX": "JAC",
    "WSH": "WAS",
    "SD": "LAC",     # pre-2017 relocations, present in deep history
    "STL": "LAR",
    "OAK": "LV",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
}

TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAC", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]

TEAM_SET = set(TEAMS)


def clean_team(value):
    """Normalize a team abbreviation. Returns 'FA' for anything unrecognized."""
    if not value:
        return "FA"
    abbr = str(value).strip().upper()
    abbr = TEAM_ALIASES.get(abbr, abbr)
    return abbr if abbr in TEAM_SET else "FA"
