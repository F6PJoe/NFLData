#!/usr/bin/env python3
"""
Combine per-source weekly projections into consensus CSVs per position.

Same logic as ff_draft_proj/build_consensus.py, but:
  - "Opp" column instead of "Bye"
  - TE has no STD column in the weekly sheet

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
    "QB": ["QB", "Team", "Opp", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles",
           "Fantasy Points"],
    "RB": ["RB", "Team", "Opp", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum",
           "Fantasy Points (Half-PPR)", "Fantasy Points (PPR)", "Fantasy Points (STD)"],
    "WR": ["WR", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum",
           "Fantasy Points (Half)", "Fantasy Points (PPR)", "Fantasy Points (STD)"],
    "TE": ["TE", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD",
           "Fantasy Points (Half-PPR)", "Fantasy Points (PPR)", "TE Premium"],
}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

STATUS_TOKENS = {"o", "q", "d", "ir", "pup", "sus", "na", "dnp", "ps", "nfi", "uns"}

TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET",
    "GB", "HOU", "IND", "JAC", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NYG",
    "NYJ", "NE", "NO", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS", "FA",
}
TEAM_ALIASES = {"JAX": "JAC", "WSH": "WAS", "LA": "LAR", "NA": "FA", "UNS": "FA"}

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
    "kenneth gainwell": "kenny gainwell",
}

DISPLAY_NAME_OVERRIDES = {
    "cam skattebo": "Cam Skattebo",
    "woody marks": "Woody Marks",
    "mitch trubisky": "Mitch Trubisky",
    "josh palmer": "Josh Palmer",
    "mitch tinsley": "Mitch Tinsley",
    "matt hibner": "Matt Hibner",
    "drew ogletree": "Drew Ogletree",
    "chig okonkwo": "Chig Okonkwo",
    "cam ward": "Cam Ward",
    "jam miller": "Jam Miller",
    "tank dell": "Tank Dell",
    "chris brooks": "Chris Brooks",
    "kenny gainwell": "Kenny Gainwell",
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
    players = {}
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
                    "opp": row.get("Opp", ""),
                    "stats": {col: [] for col in STAT_COLUMNS[pos]},
                    "sources": [],
                }
                order.append(key)
            player = players[key]
            player["sources"].append(source)
            if key in DISPLAY_NAME_OVERRIDES:
                player["name"] = DISPLAY_NAME_OVERRIDES[key]
            elif len(name) > len(player["name"]):
                player["name"] = name
            if player["team"] == "FA" and team != "FA":
                player["team"] = team
            if not player["opp"]:
                player["opp"] = row.get("Opp", "")
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

        record = {pos: player["name"], "Team": player["team"], "Opp": player["opp"]}
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
        else:  # RB
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
