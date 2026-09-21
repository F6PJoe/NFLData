#!/usr/bin/env python3
"""
Take the 2025 working cheat sheet and update it with 2026 data:
  1. SaveAs  2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm
  2. Overwrite QB/RB/WR/TE Projections tabs (top 64/125/165/65 by half-PPR)
  3. Overwrite ADP tab from combined_adp.csv (col B = Consensus ADP)
  4. Simplify Cheat Sheet M column formula to single ADP tab
  5. Rebuild Cheat Sheet A-D from updated projection tabs, sorted by ADP

NEVER use openpyxl to save this workbook — it strips Data Validation and
Conditional Formatting. Always use win32com.client.
"""

import csv
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent.parent
SOURCE = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2025-Football-Cheat-Sheet-working-copy-new-formula-testing.xlsm"
TARGET = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"

# Top-N cutoffs per position (by half-PPR score)
LIMITS = {"QB": 64, "RB": 125, "WR": 165, "TE": 65}

xlUp = -4162
xlFillCopy = 0
xlOpenXMLWorkbookMacroEnabled = 52  # .xlsm format code

# ADP name → Projections tab name (preserve VLOOKUP matches)
RENAMES = {
    'Matt Stafford': 'Matthew Stafford',
    'C.j. Stroud': 'C.J. Stroud',
    'Dan Jones': 'Daniel Jones',
    'Cam Ward': 'Cameron Ward',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'Mike Penix': 'Michael Penix Jr.',
    # Suffix mismatches (ADP drops Jr./Sr./II/III)
    'Kenneth Walker': 'Kenneth Walker III',
    'Travis Etienne': 'Travis Etienne Jr.',
    'Luther Burden': 'Luther Burden III',
    'Harold Fannin': 'Harold Fannin Jr.',
    'Marvin Harrison': 'Marvin Harrison Jr.',
    'Kyle Pitts': 'Kyle Pitts Sr.',
    'Brian Thomas': 'Brian Thomas Jr.',
    'Aaron Jones': 'Aaron Jones Sr.',
    'Chris Rodriguez': 'Chris Rodriguez Jr.',
    'Omar Cooper': 'Omar Cooper Jr.',
    'Tyrone Tracy': 'Tyrone Tracy Jr.',
    'Brian Robinson': 'Brian Robinson Jr.',
    'Mike Washington': 'Mike Washington Jr.',
    'Chris Brazzell': 'Chris Brazzell II',
    'Marvin Mims': 'Marvin Mims Jr.',
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
    'Mike Pittman': 'Michael Pittman Jr.',
    'Tank Dell': 'Nathaniel Dell',
    'Chris Brooks': 'Christopher Brooks',
    'Hollywood Brown': 'Marquise Brown',
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


# Consensus CSV name → canonical name (must match ADP tab + JB Ranks spellings)
PROJ_RENAMES = {
    'Cam Ward': 'Cameron Ward',
    'Tank Dell': 'Nathaniel Dell',
    'Hollywood Brown': 'Marquise Brown',
    'Chris Brooks': 'Christopher Brooks',
    'Chig Okonkwo': 'Chigoziem Okonkwo',
    'Mitch Evans': 'Mitchell Evans',
    'M. Valdes-Scantling': 'Marquez Valdes-Scantling',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'Mike Penix': 'Michael Penix Jr.',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Mike Pittman': 'Michael Pittman Jr.',
}


def safe_float(v, default=0):
    try:
        return float(v) if v not in (None, '', 'None') else default
    except (TypeError, ValueError):
        return default


def load_consensus():
    """Load combined_adp.csv → {player: consensus_adp}"""
    result = {}
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            c = row.get('Consensus', '')
            if c:
                result[row['Player']] = float(c)
    return result


def load_projections():
    """
    Load consensus_*.csv files and return players grouped by position,
    sorted by half-PPR score descending, trimmed to LIMITS[pos].

    Returns dict: pos -> list of (A, B, C, D, G, H, I, J, K, L, M, N) tuples.
    Only raw stat columns — E/F/O/P/Q are formulas in the workbook, preserved.

    Column mapping per tab:
      QB: A=Player B=Team C=Bye D=Pos  G=PassAtt H=PassCmp I=PassYds J=PassTD
          K=PassInt L=RushAtt M=RushYds N=RushTD  (O=Fum static, P=ru1st formula)
      RB: A=Player B=Team C=Bye D=Pos  G=RushAtt H=RushYds I=RushTD J=Tgt
          K=Rec L=RecYds M=RecTD N=Fum
      WR: A=Player B=Team C=Bye D=Pos  G=Tgt H=Rec I=RecYds J=RecTD
          K=RushAtt L=RushYds M=RushTD N=Fum
      TE: A=Player B=Team C=Bye D=Pos  G=Tgt H=Rec I=RecYds J=RecTD
          K=RushAtt L=RushYds M=RushTD  (N=Fum blank in original)
    """
    out = {}

    # ── QB ──────────────────────────────────────────────────────────────────
    qbs = []
    with open(BASE / "ff_draft_proj" / "consensus_qb.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = PROJ_RENAMES.get(row.get('QB', '').strip(), row.get('QB', '').strip())
            if not name:
                continue
            score = safe_float(row.get('Fantasy Points'))
            qbs.append((score, (
                name,                           # A
                row.get('Team', ''),            # B
                safe_float(row.get('Bye', 0)), # C
                'QB',                           # D
                safe_float(row.get('Pass Att')),   # G
                safe_float(row.get('Pass Comp')),  # H
                safe_float(row.get('Pass Yds')),   # I
                safe_float(row.get('Pass TD')),    # J
                safe_float(row.get('Pass Int')),   # K
                safe_float(row.get('Rush Att')),   # L
                safe_float(row.get('Rush Yds')),   # M
                safe_float(row.get('Rush TD')),    # N
                safe_float(row.get('Fumbles')),    # O (Fum — static in original)
            )))
    qbs.sort(key=lambda x: x[0], reverse=True)
    out['QB'] = [r for _, r in qbs[:LIMITS['QB']]]

    # ── RB ──────────────────────────────────────────────────────────────────
    rbs = []
    with open(BASE / "ff_draft_proj" / "consensus_rb.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = PROJ_RENAMES.get(row.get('RB', '').strip(), row.get('RB', '').strip())
            if not name:
                continue
            score = safe_float(row.get('Fantasy Points (Half-PPR)'))
            rbs.append((score, (
                name,
                row.get('Team', ''),
                safe_float(row.get('Bye', 0)),
                'RB',
                safe_float(row.get('Rush Att')),   # G
                safe_float(row.get('Rush Yds')),   # H
                safe_float(row.get('Rush TD')),    # I
                safe_float(row.get('Targets')),    # J
                safe_float(row.get('Rec')),        # K
                safe_float(row.get('Rec Yds')),    # L
                safe_float(row.get('Rec TD')),     # M
                safe_float(row.get('Fum')),        # N
            )))
    rbs.sort(key=lambda x: x[0], reverse=True)
    out['RB'] = [r for _, r in rbs[:LIMITS['RB']]]

    # ── WR ──────────────────────────────────────────────────────────────────
    wrs = []
    with open(BASE / "ff_draft_proj" / "consensus_wr.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = PROJ_RENAMES.get(row.get('WR', '').strip(), row.get('WR', '').strip())
            if not name:
                continue
            score = safe_float(row.get('Fantasy Points (Half)'))
            wrs.append((score, (
                name,
                row.get('Team', ''),
                safe_float(row.get('Bye', 0)),
                'WR',
                safe_float(row.get('Targets')),    # G
                safe_float(row.get('Rec')),        # H
                safe_float(row.get('Rec Yds')),    # I
                safe_float(row.get('Rec TD')),     # J
                safe_float(row.get('Rush Att')),   # K
                safe_float(row.get('Rush Yds')),   # L
                safe_float(row.get('Rush TD')),    # M
                safe_float(row.get('Fum')),        # N
            )))
    wrs.sort(key=lambda x: x[0], reverse=True)
    # Deduplicate by name (keep highest score, which is first after sort)
    seen_wr = set()
    wrs = [(s, r) for s, r in wrs if r[0] not in seen_wr and not seen_wr.add(r[0])]
    out['WR'] = [r for _, r in wrs[:LIMITS['WR']]]

    # ── TE ──────────────────────────────────────────────────────────────────
    tes = []
    with open(BASE / "ff_draft_proj" / "consensus_te.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            name = PROJ_RENAMES.get(row.get('TE', '').strip(), row.get('TE', '').strip())
            if not name:
                continue
            score = safe_float(row.get('Fantasy Points (Half-PPR)'))
            tes.append((score, (
                name,
                row.get('Team', ''),
                safe_float(row.get('Bye', 0)),
                'TE',
                safe_float(row.get('Targets')),    # G
                safe_float(row.get('Rec')),        # H
                safe_float(row.get('Rec Yds')),    # I
                safe_float(row.get('Rec TD')),     # J
                safe_float(row.get('Rush Att')),   # K
                safe_float(row.get('Rush Yds')),   # L
                safe_float(row.get('Rush TD')),    # M
                None,                              # N Fum (blank in original)
            )))
    tes.sort(key=lambda x: x[0], reverse=True)
    out['TE'] = [r for _, r in tes[:LIMITS['TE']]]

    return out


def update_projection_tab(sh, rows, pos):
    """
    Update projection tab with new data while preserving formula columns.

    Formula cols (preserved from row 2 templates, re-applied via AutoFill):
      E = Player&Team  F = Score (uses Setup weights)  O/P = 1st-down estimates
      Q = RANK.EQ

    Data cols written:
      QB:  A-D (player info) + G-N (pass/rush stats) + O (Fum — static in original)
      RB/WR/TE: A-D + G-N
    """
    xlFillCopy = 0
    old_last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    new_last = 1 + len(rows)

    # Save row-2 formula strings for formula cols before clearing anything
    formula_cols = {}
    for col_letter in ('E', 'F', 'O', 'P', 'Q'):
        formula_cols[col_letter] = sh.Range(f"{col_letter}2").Formula

    # Clear all old data rows (including formula cells) from row 2 down
    clear_to = max(old_last, new_last + 2)
    sh.Range(f"A2:Q{clear_to}").ClearContents()

    # Write data: cols A-D (player info) as a block, then G-N (stats) as a block
    # Each row tuple: (A, B, C, D, G, H, I, J, K, L, M, N[, O_fum for QB])
    ad_block = [[r[0], r[1], r[2], r[3]] for r in rows]   # cols A-D
    sh.Range(f"A2:D{new_last}").Value = ad_block

    if pos == 'QB':
        # G-O (9 cols): PassAtt, PassCmp, PassYds, PassTD, PassInt, RushAtt, RushYds, RushTD, Fum
        gn_block = [[r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12]] for r in rows]
        sh.Range(f"G2:O{new_last}").Value = gn_block
    else:
        # G-N (8 cols)
        gn_block = [[r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]] for r in rows]
        sh.Range(f"G2:N{new_last}").Value = gn_block

    # Re-apply formula cols via AutoFill from row 2 template
    for col_letter, formula in formula_cols.items():
        if not formula or not formula.startswith('='):
            continue
        # Skip O for QB since we just wrote Fum there as a static value
        if pos == 'QB' and col_letter == 'O':
            continue
        sh.Range(f"{col_letter}2").Formula = formula
        if new_last > 2:
            sh.Range(f"{col_letter}2").AutoFill(
                sh.Range(f"{col_letter}2:{col_letter}{new_last}"), xlFillCopy
            )

    print(f"  {pos} Projections: {len(rows)} players written (rows 2-{new_last}), "
          f"formula cols E/F/{'O/' if pos != 'QB' else ''}P/Q restored")


def update_adp_tab(wb, adp_rows):
    """
    Overwrite the ADP tab with 2026 consensus data.
    Column layout: Player | Consensus ADP | Position | Team | Underdog | CBS |
                   ESPN | FFPC | BB10s | NFL | Yahoo! | Sleeper | Fantrax |
                   RTSports | NFFC | NFFC Cutline | Sleeper_2QB
    The Cheat Sheet M formula only needs cols A (Player) and B (Consensus ADP).
    """
    adp = wb.Sheets("ADP")
    old_last = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row

    # Write header
    headers = [
        "Player", "ADP", "Position", "Team",
        "Underdog", "CBS", "ESPN", "FFPC", "BB10s", "NFL",
        "Yahoo!", "Sleeper", "Fantrax", "RTSports", "NFFC", "NFFC Cutline", "Sleeper_2QB"
    ]
    adp.Range(f"A1:Q1").Value = [headers]

    new_last = 1 + len(adp_rows)
    if old_last >= 2:
        adp.Range(f"A2:Q{max(old_last, new_last + 5)}").ClearContents()

    adp.Range(f"A2:Q{new_last}").Value = adp_rows
    print(f"  ADP tab: {len(adp_rows)} players written")


def main():
    # ── Load CSV data ────────────────────────────────────────────────────────
    print("Loading CSV data...")
    consensus = load_consensus()
    projections = load_projections()

    total_proj = sum(len(v) for v in projections.values())
    print(f"  Projections: QB={len(projections['QB'])} RB={len(projections['RB'])} "
          f"WR={len(projections['WR'])} TE={len(projections['TE'])} (total={total_proj})")

    # Build ADP tab rows sorted by Consensus ADP
    print("Building ADP data...")
    adp_source = []
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            c = row.get('Consensus', '')
            if not c:
                continue
            adp_val = float(c)
            adp_source.append((adp_val, [
                row['Player'],
                round(adp_val, 2),
                row.get('Position(s)', ''),
                row.get('Team', ''),
                safe_float(row.get('Underdog')) or None,
                safe_float(row.get('CBS')) or None,
                safe_float(row.get('ESPN')) or None,
                safe_float(row.get('FFPC')) or None,
                safe_float(row.get('BB10s')) or None,
                safe_float(row.get('NFL')) or None,
                safe_float(row.get('Yahoo!')) or None,
                safe_float(row.get('Sleeper')) or None,
                safe_float(row.get('Fantrax')) or None,
                safe_float(row.get('RTSports')) or None,
                safe_float(row.get('NFFC')) or None,
                safe_float(row.get('NFFC Cutline')) or None,
                safe_float(row.get('Sleeper_2QB')) or None,
            ]))
    adp_source.sort(key=lambda x: x[0])
    adp_rows = [row for _, row in adp_source]
    print(f"  ADP: {len(adp_rows)} players")

    # ── Excel COM ────────────────────────────────────────────────────────────
    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        print(f"\nOpening source file...")
        wb = excel.Workbooks.Open(SOURCE)
        try:
            # SaveAs target (xlsm = 52)
            print(f"Saving as 2026ver...")
            wb.SaveAs(TARGET, FileFormat=xlOpenXMLWorkbookMacroEnabled)
            print(f"  Saved: {TARGET}")

            # ── Update projection tabs ────────────────────────────────────────
            print("\nUpdating projection tabs...")
            tab_names = {
                'QB': 'QB Projections',
                'RB': 'RB Projections',
                'WR': 'WR Projections',
                'TE': 'TE Projections',
            }
            for pos, rows in projections.items():
                sh = wb.Sheets(tab_names[pos])
                update_projection_tab(sh, rows, pos)

            # ── Update ADP tab ────────────────────────────────────────────────
            print("\nUpdating ADP tab...")
            update_adp_tab(wb, adp_rows)

            # Rename ADP player names to match Projections spelling
            adp_sh = wb.Sheets("ADP")
            adp_last = adp_sh.Cells(adp_sh.Rows.Count, 1).End(xlUp).Row
            renamed = 0
            for r in range(2, adp_last + 1):
                name = adp_sh.Cells(r, 1).Value
                if name in RENAMES:
                    adp_sh.Cells(r, 1).Value = RENAMES[name]
                    renamed += 1
            if renamed:
                print(f"  Renamed {renamed} ADP player names to match Projections spelling")

            # ── Update Cheat Sheet M column formula ───────────────────────────
            # Simplify from multi-tab VLOOKUP to single ADP tab (col B = Consensus ADP)
            print("\nUpdating Cheat Sheet M column formula...")
            cs = wb.Sheets("Cheat Sheet")
            cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            print(f"  Cheat Sheet: {cs_last - 1} players currently")

            # Write M formula for all existing player rows
            # Missing or 999 ADP → MAXIFS(excluding 999) + 1
            m_formula = (
                '=IFERROR('
                'IF(VLOOKUP(A2,ADP!$A:$B,2,FALSE)<999,'
                    'VLOOKUP(A2,ADP!$A:$B,2,FALSE),'
                    'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1),'
                'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1)'
            )
            cs.Range(f"M2:M{cs_last}").Formula = m_formula
            print(f"  M2:M{cs_last} formula updated to single ADP tab VLOOKUP")

            # ── Rebuild Cheat Sheet A-D from updated projection tabs ──────────
            # Build score lookup from raw CSV data (since col F in tabs is now a formula)
            print("\nRebuilding Cheat Sheet player list (A-D)...")
            raw_scores = {}
            for pos, rows in projections.items():
                for row in rows:
                    # rows tuple: (A=name, B=team, C=bye, D=pos, G, H, ...) — no score
                    # We need score for fallback sort; read from Projections tab col F
                    pass  # scores read below via COM after formulas recalculate

            # Read col F (score) from each projection tab after formulas are set
            proj_scores = {}
            for pos, tab_name in [('QB','QB Projections'),('RB','RB Projections'),
                                   ('WR','WR Projections'),('TE','TE Projections')]:
                sh = wb.Sheets(tab_name)
                n = len(projections[pos])
                if n == 0:
                    continue
                vals = sh.Range(f"A2:F{1+n}").Value
                for r in vals:
                    name = r[0]
                    score = safe_float(r[5]) if r[5] is not None else 0
                    proj_scores[name] = score

            players = []
            for pos, rows in projections.items():
                for row in rows:
                    name = row[0]
                    team = row[1]
                    bye  = row[2]
                    if name in consensus:
                        sortkey = consensus[name]
                    else:
                        score = proj_scores.get(name, 0)
                        sortkey = 1000 - (score / 1000.0)
                    players.append((name, team, bye, pos, sortkey))

            players.sort(key=lambda p: p[4])
            print(f"  Total players: {len(players)}")

            old_last = cs_last
            new_last = 1 + len(players)
            out = [[p[0], p[1], p[2], p[3]] for p in players]
            cs.Range(f"A2:D{new_last}").Value = out

            # Clear leftover rows if new list is shorter
            if new_last < old_last:
                cs.Range(f"A{new_last + 1}:U{old_last}").ClearContents()

            # AutoFill formula columns E onward to new last row
            cs.Range("E2:U2").AutoFill(cs.Range(f"E2:U{new_last}"), xlFillCopy)
            # Re-apply M formula after AutoFill (AutoFill may have overwritten it with old multi-tab formula)
            cs.Range(f"M2:M{new_last}").Formula = m_formula
            print(f"  Wrote {len(players)} players (A2:D{new_last}), AutoFilled E:U")

            wb.Save()
            print("\nSaved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()

    print("\nDone. Run update_joe_bond_ranks.py separately to refresh Joe Bond rankings.")
    print(f"Output: {TARGET}")


if __name__ == "__main__":
    main()
