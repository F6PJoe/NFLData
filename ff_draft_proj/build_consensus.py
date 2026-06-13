#!/usr/bin/env python3
"""
Combine per-source season-long (preseason/draft) projections into consensus
CSVs per position.

For each position (QB/RB/WR/TE), reads `<source>_<pos>.csv` for every source
in SOURCES that has a file, matches players by a normalized name, averages
each stat column across the sources that report it (blank cells are
ignored), picks a Team/Bye from whichever source reports one, and computes
fantasy points from the averaged stat line via scoring.py. This is the only
place fantasy points are calculated.

Usage:
    python build_consensus.py
"""

import csv
import unicodedata

import scoring

SOURCES = ["espn", "cbs", "ftn", "yahoo", "fantasysharks", "draftsharks",
           "fantasydata", "4for4", "fantasylife", "fftoday"]

STAT_COLUMNS = {
    "QB": ["Pass Att", "Pass Comp", "Pass Yds", "Pass TD", "Pass Int",
           "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec", "Rec Yds",
           "Rec TD", "Fum"],
    "WR": ["Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att", "Rush Yds", "Rush TD", "Fum"],
    "TE": ["Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att", "Rush Yds", "Rush TD"],
}

OUT_COLUMNS = {
    "QB": ["QB", "Team", "Bye", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles",
           "Fantasy Points"],
    "RB": ["RB", "Team", "Bye", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum",
           "Fantasy Points (Half-PPR)", "Fantasy Points (PPR)", "Fantasy Points (STD)"],
    "WR": ["WR", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum",
           "Fantasy Points (Half)", "Fantasy Points (PPR)", "Fantasy Points (STD)"],
    "TE": ["TE", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD",
           "Fantasy Points (Half-PPR)", "Fantasy Points (PPR)", "TE Premium"],
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Some sources tack an injury-status abbreviation onto the player's name
# (e.g. "Daniel Jones&nbsp;&nbsp;O" for "Out") or report it in the Team
# column instead of a real team. Strip these out.
STATUS_TOKENS = {"o", "q", "d", "ir", "pup", "sus", "na", "dnp", "ps", "nfi", "uns"}

# Canonical team abbreviations. Anything not in this set (including blank,
# or a stray injury-status code that ended up in the Team column) maps to FA.
TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAC", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NYG",
    "NYJ", "NE", "NO", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS", "FA",
}
TEAM_ALIASES = {"JAX": "JAC", "WSH": "WAS", "LA": "LAR", "NA": "FA", "UNS": "FA"}

# Normalized-name aliases for players that different sources spell/nickname
# differently, so they're treated as the same person.
NAME_ALIASES = {
    "cameron skattebo": "cam skattebo",
    "joquavioius marks": "woody marks",
    "joquavious marks": "woody marks",
    "mitchell trubisky": "mitch trubisky",
    "joshua palmer": "josh palmer",
    "mitchell tinsley": "mitch tinsley",
    "matthew hibner": "matt hibner",
    "andrew ogletree": "drew ogletree",
}


def clean_name(name):
    name = name.replace("\xa0", " ").replace("&nbsp;", " ")
    parts = name.split()
    while parts and parts[-1].lower() in STATUS_TOKENS:
        parts.pop()
    return " ".join(parts)


def clean_team(team):
    team = team.strip().upper()
    team = TEAM_ALIASES.get(team, team)
    return team if team in TEAMS else "FA"


def normalize_name(name):
    # Strip accents (e.g. "Estimé" -> "Estime") so names match across
    # sources that spell them with or without diacritics.
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    parts = name.split()
    while parts and parts[-1] in SUFFIXES:
        parts.pop()
    key = " ".join(parts)
    return NAME_ALIASES.get(key, key)


def num(value):
    value = (value or "").strip()
    if not value:
        return None
    return float(value)


def load_source(source, pos):
    fn = f"{source}_{pos.lower()}.csv"
    try:
        with open(fn, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def merge_position(pos):
    players = {}  # normalized name -> player record
    order = []

    for source in SOURCES:
        rows = load_source(source, pos)
        for row in rows:
            name = clean_name(row[pos])
            key = normalize_name(name)
            team = clean_team(row.get("Team", ""))
            if key not in players:
                players[key] = {
                    "name": name,
                    "team": team,
                    "bye": row.get("Bye", ""),
                    "stats": {col: [] for col in STAT_COLUMNS[pos]},
                    "sources": [],
                }
                order.append(key)
            player = players[key]
            player["sources"].append(source)
            if player["team"] == "FA" and team != "FA":
                player["team"] = team
            if not player["bye"]:
                player["bye"] = row.get("Bye", "")
            for col in STAT_COLUMNS[pos]:
                value = num(row.get(col, ""))
                if value is not None:
                    player["stats"][col].append(value)

    records = []
    for key in order:
        player = players[key]
        avg_stats = {}
        for col in STAT_COLUMNS[pos]:
            values = player["stats"][col]
            avg_stats[col] = scoring.round2(sum(values) / len(values)) if values else ""

        record = {pos: player["name"], "Team": player["team"], "Bye": player["bye"]}
        record.update(avg_stats)

        s = {
            "pass_yds": avg_stats.get("Pass Yds") or 0,
            "pass_td": avg_stats.get("Pass TD") or 0,
            "pass_int": avg_stats.get("Pass Int") or 0,
            "rush_yds": avg_stats.get("Rush Yds") or 0,
            "rush_td": avg_stats.get("Rush TD") or 0,
            "rec": avg_stats.get("Rec") or 0,
            "rec_yds": avg_stats.get("Rec Yds") or 0,
            "rec_td": avg_stats.get("Rec TD") or 0,
            "fum": avg_stats.get("Fumbles" if pos == "QB" else "Fum") or 0,
        }

        if pos == "QB":
            record["Fantasy Points"] = scoring.round2(scoring.qb_points(s))
            sort_key = record["Fantasy Points"]
        elif pos == "TE":
            record["Fantasy Points (Half-PPR)"] = scoring.round2(scoring.half_ppr_points(s))
            record["Fantasy Points (PPR)"] = scoring.round2(scoring.ppr_points(s))
            record["TE Premium"] = scoring.round2(scoring.te_premium_points(s))
            sort_key = record["Fantasy Points (PPR)"]
        elif pos == "WR":
            record["Fantasy Points (Half)"] = scoring.round2(scoring.half_ppr_points(s))
            record["Fantasy Points (PPR)"] = scoring.round2(scoring.ppr_points(s))
            record["Fantasy Points (STD)"] = scoring.round2(scoring.std_points(s))
            sort_key = record["Fantasy Points (PPR)"]
        else:
            record["Fantasy Points (Half-PPR)"] = scoring.round2(scoring.half_ppr_points(s))
            record["Fantasy Points (PPR)"] = scoring.round2(scoring.ppr_points(s))
            record["Fantasy Points (STD)"] = scoring.round2(scoring.std_points(s))
            sort_key = record["Fantasy Points (PPR)"]

        if sort_key <= 0:
            continue
        if pos == "QB" and not avg_stats.get("Pass Att"):
            continue
        records.append((sort_key, record))

    records.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in records]


def main():
    for pos in ("QB", "RB", "WR", "TE"):
        records = merge_position(pos)
        if not records:
            print(f"No data found for {pos} (no per-source CSVs present?).")
            continue
        out = f"consensus_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(records)
        print(f"Wrote {len(records)} {pos}s to {out}.")


if __name__ == "__main__":
    main()
