#!/usr/bin/env python3
"""
Align ADP player names with the Projections sheets' spelling/capitalization
(e.g. "A.j. Brown" -> "A.J. Brown", "Ceedee Lamb" -> "CeeDee Lamb",
"Matt Stafford" -> "Matthew Stafford") so that the Cheat Sheet's
VLOOKUP($A2, ADP!$A:$P, ...) matches on exact player name.

Updates combined_adp.csv. The workbook's ADP tab is updated separately.
"""

import csv
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
COMBINED = BASE / "combined_adp.csv"

# ADP name -> Projections name
RENAMES = {
    'Matt Stafford': 'Matthew Stafford',
    'C.j. Stroud': 'C.J. Stroud',
    'Dan Jones': 'Daniel Jones',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'J.j. McCarthy': 'J.J. McCarthy',
    'Tony Richardson Sr.': 'Anthony Richardson Sr.',
    'Jon Taylor': 'Jonathan Taylor',
    "De'von Achane": "De'Von Achane",
    'James Cook': 'James Cook III',
    "D'andre Swift": "D'Andre Swift",
    'Treveyon Henderson': 'TreVeyon Henderson',
    'Rj Harvey': 'RJ Harvey',
    'J.k. Dobbins': 'J.K. Dobbins',
    'Marshawn Lloyd': 'MarShawn Lloyd',
    'Dj Giddens': 'DJ Giddens',
    'Nick Singleton': 'Nicholas Singleton',
    'Aj Dillon': 'AJ Dillon',
    'Lequint Allen Jr.': 'LeQuint Allen Jr.',
    "J'mari Taylor": "J'Mari Taylor",
    'Rob Henry': 'Robert Henry Jr.',
    'Mike Carter': 'Michael Carter',
    "Ja'marr Chase": "Ja'Marr Chase",
    'Amon-ra St. Brown': 'Amon-Ra St. Brown',
    'Ceedee Lamb': 'CeeDee Lamb',
    'A.j. Brown': 'A.J. Brown',
    'Devonta Smith': 'DeVonta Smith',
    'Dj Moore': 'DJ Moore',
    'Dk Metcalf': 'DK Metcalf',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Chris Godwin': 'Chris Godwin Jr.',
    'Mike Wilson': 'Michael Wilson',
    "Wan'dale Robinson": "Wan'Dale Robinson",
    'Matt Golden': 'Matthew Golden',
    'K.c. Concepcion': 'KC Concepcion',
    'Tre Harris': "Tre' Harris",
    "Ja'kobi Lane": "Ja'Kobi Lane",
    "De'zhaun Stribling": "De'Zhaun Stribling",
    'Kavontae Turpin': 'KaVontae Turpin',
    'Josh Palmer': 'Joshua Palmer',
    'Demario Douglas': 'DeMario Douglas',
    'Mitch Tinsley': 'Mitchell Tinsley',
    'Keandre Lambert-Smith': 'KeAndre Lambert-Smith',
    'Cj Daniels': 'CJ Daniels',
    'Juju Smith-Schuster': 'JuJu Smith-Schuster',
    'Cj Williams': 'CJ Williams',
    'Oronde Gadsden II': 'Oronde Gadsden',
    'T.j. Hockenson': 'T.J. Hockenson',
    'Aj Barner': 'AJ Barner',
    'Mike Mayer': 'Michael Mayer',
    "Ja'tavion Sanders": "Ja'Tavion Sanders",
    'Dan Bellinger': 'Daniel Bellinger',
    'Mike Trigg': 'Michael Trigg',
    'Matt Hibner': 'Matthew Hibner',
}


def main():
    with open(COMBINED, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    renamed = 0
    for row in rows:
        if row['Player'] in RENAMES:
            row['Player'] = RENAMES[row['Player']]
            renamed += 1

    with open(COMBINED, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Renamed {renamed} players in {COMBINED}")


if __name__ == "__main__":
    main()
