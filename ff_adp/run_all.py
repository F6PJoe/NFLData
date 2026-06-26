"""
run_all.py
Run every ADP fetcher, merge results by player name, compute consensus
(average of only the sites that have an ADP for each player), write
combined_adp.csv, and push the data to Google Sheets.

Sheet column order:
  Player | Position(s) | Team | Sleeper | ESPN | Yahoo! | CBS | Fantrax |
  NFL | FFPC | BB10s | NFFC | Underdog | Consensus

Only outputs: QB, RB, WR, TE (offense) + K (kicker) + DST (team defense).
Defense players are normalised to "<Nickname>" with position DST.
"""

import argparse, csv, os, subprocess, sys, unicodedata, re
from pathlib import Path

# ── Column config ─────────────────────────────────────────────────────────────
# (module, csv_file, adp_col, label, extra_args)
SOURCES = [
    ('fetch_sleeper_adp',   'sleeper_adp.csv',   'Sleeper',     'Sleeper',     []),
    ('fetch_sleeper_adp',   'sleeper_adp.csv',   'Sleeper_STD', 'Sleeper_STD', []),  # STD scoring, not in consensus
    ('fetch_sleeper_adp',   'sleeper_adp.csv',   'Sleeper_Half','Sleeper_Half',[]),  # Half-PPR, not in consensus
    ('fetch_sleeper_adp',   'sleeper_adp.csv',   'Sleeper_2QB', 'Sleeper_2QB', []),  # 2QB/SF ADP, not in consensus
    ('fetch_espn_adp',      'espn_adp.csv',      'ESPN',     'ESPN',     []),
    ('fetch_yahoo_adp',     'yahoo_adp.csv',      'Yahoo!',   'Yahoo!',   []),
    ('fetch_cbs_adp',       'cbs_adp.csv',        'CBS',      'CBS',      []),
    ('fetch_fantrax_adp',   'fantrax_adp.csv',    'Fantrax',  'Fantrax',  []),
    ('fetch_ffpc_adp',      'ffpc_adp.csv',       'FFPC',     'FFPC',     []),
    ('fetch_nffc_adp',      'bb10s_adp.csv',      'BB10s',    'BB10s',    ['--contest', 'bb10s']),
    ('fetch_nffc_adp',      'nffc_adp.csv',       'NFFC',     'NFFC',     []),
    ('fetch_nffc_adp',      'nffc_cutline_adp.csv', 'NFFC Cutline', 'NFFC Cutline', ['--contest', 'cutline']),
    ('fetch_rts_adp',       'rts_adp.csv',        'RTSports', 'RTSports', []),
    ('fetch_underdog_adp',  'underdog_adp.csv',   'Underdog', 'Underdog', []),
]

OUTPUT_COLS = ['Player', 'Position(s)', 'Team',
               'Sleeper', 'Sleeper_STD', 'Sleeper_Half', 'Sleeper_2QB',
               'ESPN', 'Yahoo!', 'CBS', 'Fantrax',
               'NFL', 'FFPC', 'BB10s', 'NFFC', 'NFFC Cutline', 'RTSports',
               'Underdog', 'Consensus']

# Columns written to Google Sheets — must match the header row already in the sheet.
# Extra columns (Sleeper_2QB, NFFC Cutline, RTSports) stay in combined_adp.csv
# for the cheatsheet but are NOT pushed to the public ADP Google Sheet tab.
SHEET_COLS = ['Player', 'Position(s)', 'Team',
              'Sleeper', 'ESPN', 'Yahoo!', 'CBS', 'Fantrax',
              'NFL', 'FFPC', 'BB10s', 'NFFC', 'Underdog', 'Consensus']

# Sleeper format variants are reference columns only — only Sleeper (PPR) enters consensus
SITE_COLS = [c for c in OUTPUT_COLS
             if c not in ('Player', 'Position(s)', 'Team', 'NFL',
                          'Sleeper_STD', 'Sleeper_Half', 'Sleeper_2QB', 'Consensus')]

# ── Google Sheets config ──────────────────────────────────────────────────────
SHEET_ID     = '1fQxZjVIHcvi41wDxGK13Sx4lD3odFV-DBVsNPg8pvyU'
SERVICE_ACCT = str(Path(__file__).parent / 'triple-baton-456523-e4-b9ec3cbd6e3d.json')
SHEET_TAB    = 'ADP'
SHEET_RANGE  = f'{SHEET_TAB}!A1'

# ── Position filtering & normalisation ───────────────────────────────────────
# Raw position codes that mean "team defense"
DST_POS    = {'DST', 'DEF', 'DF', 'TDSP', 'D/ST'}
# Offensive positions we keep as-is
OFFENSE_POS = {'QB', 'RB', 'WR', 'TE'}
# Kickers are excluded entirely

def normalise_position(raw: str) -> str:
    """Return canonical position or '' if this row should be dropped."""
    p = raw.strip().upper()
    if p in OFFENSE_POS:
        return p
    if p in DST_POS:
        return 'DST'
    return ''   # drop (includes K/PK/TK kickers)

# ── Defense name mapping ──────────────────────────────────────────────────────
# Every variant that appears across sources → canonical nickname

# Full city / franchise name → nickname  (Fantrax uses city names)
CITY_TO_NICK = {
    'arizona':       'Cardinals',
    'atlanta':       'Falcons',
    'baltimore':     'Ravens',
    'buffalo':       'Bills',
    'carolina':      'Panthers',
    'chicago':       'Bears',
    'cincinnati':    'Bengals',
    'cleveland':     'Browns',
    'dallas':        'Cowboys',
    'denver':        'Broncos',
    'detroit':       'Lions',
    'green bay':     'Packers',
    'houston':       'Texans',
    'indianapolis':  'Colts',
    'jacksonville':  'Jaguars',
    'kansas city':   'Chiefs',
    'la chargers':   'Chargers',
    'la rams':       'Rams',
    'las vegas':     'Raiders',
    'miami':         'Dolphins',
    'minnesota':     'Vikings',
    'new england':   'Patriots',
    'new orleans':   'Saints',
    'new york':      'Giants',   # ambiguous — handled below
    'ny giants':     'Giants',
    'ny jets':       'Jets',
    'philadelphia':  'Eagles',
    'pittsburgh':    'Steelers',
    'san francisco': '49ers',
    'seattle':       'Seahawks',
    'tampa bay':     'Buccaneers',
    'tennessee':     'Titans',
    'washington':    'Commanders',
}

# 2-3 letter abbreviations → nickname  (FFPC uses these)
ABBREV_TO_NICK = {
    'ARI': 'Cardinals',  'ATL': 'Falcons',   'BAL': 'Ravens',
    'BUF': 'Bills',      'CAR': 'Panthers',  'CHI': 'Bears',
    'CIN': 'Bengals',    'CLE': 'Browns',    'DAL': 'Cowboys',
    'DEN': 'Broncos',    'DET': 'Lions',     'GB':  'Packers',
    'HOU': 'Texans',     'IND': 'Colts',     'JAC': 'Jaguars',
    'JAX': 'Jaguars',    'KC':  'Chiefs',    'LAC': 'Chargers',
    'LAR': 'Rams',       'LV':  'Raiders',   'MIA': 'Dolphins',
    'MIN': 'Vikings',    'NE':  'Patriots',  'NO':  'Saints',
    'NYG': 'Giants',     'NYJ': 'Jets',      'PHI': 'Eagles',
    'PIT': 'Steelers',   'SF':  '49ers',     'SEA': 'Seahawks',
    'TB':  'Buccaneers', 'TEN': 'Titans',    'WAS': 'Commanders',
    'WSH': 'Commanders', 'OAK': 'Raiders',
}

# Nickname → standard 2-3 letter abbreviation  (used for DST Team field)
NICK_TO_ABBREV = {
    'Cardinals': 'ARI',  'Falcons':    'ATL',  'Ravens':     'BAL',
    'Bills':     'BUF',  'Panthers':   'CAR',  'Bears':      'CHI',
    'Bengals':   'CIN',  'Browns':     'CLE',  'Cowboys':    'DAL',
    'Broncos':   'DEN',  'Lions':      'DET',  'Packers':    'GB',
    'Texans':    'HOU',  'Colts':      'IND',  'Jaguars':    'JAC',
    'Chiefs':    'KC',   'Chargers':   'LAC',  'Rams':       'LAR',
    'Raiders':   'LV',   'Dolphins':   'MIA',  'Vikings':    'MIN',
    'Patriots':  'NE',   'Saints':     'NO',   'Giants':     'NYG',
    'Jets':      'NYJ',  'Eagles':     'PHI',  'Steelers':   'PIT',
    '49ers':     'SF',   'Seahawks':   'SEA',  'Buccaneers': 'TB',
    'Titans':    'TEN',  'Commanders': 'WAS',
}

# Known nicknames (for ESPN "Rams D/ST", Yahoo "Rams", Sleeper, etc.)
NICKNAMES = {
    'Cardinals', 'Falcons', 'Ravens', 'Bills', 'Panthers', 'Bears',
    'Bengals', 'Browns', 'Cowboys', 'Broncos', 'Lions', 'Packers',
    'Texans', 'Colts', 'Jaguars', 'Chiefs', 'Chargers', 'Rams',
    'Raiders', 'Dolphins', 'Vikings', 'Patriots', 'Saints', 'Giants',
    'Jets', 'Eagles', 'Steelers', '49ers', 'Seahawks', 'Buccaneers',
    'Titans', 'Commanders',
}

def normalise_dst_name(raw: str) -> str:
    """
    Convert any defense name variant to the canonical team nickname.
    Returns '' if we can't resolve it.
    """
    name = raw.strip()

    # Strip common suffixes first
    for suffix in (' D/ST', ' DST', ' DEF', ' Defense', ' Team Defense',
                   ' d/st', ' dst', ' def', ' defense', ' team defense'):
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()

    # Check if it's already a known nickname
    if name in NICKNAMES:
        return name

    # Check abbreviation map (FFPC 2-3 letter codes)
    upper = name.upper()
    if upper in ABBREV_TO_NICK:
        return ABBREV_TO_NICK[upper]

    # Check city/franchise name map (lower-cased)
    lower = name.lower()
    if lower in CITY_TO_NICK:
        return CITY_TO_NICK[lower]

    # Partial match: if any nickname appears in the name
    for nick in NICKNAMES:
        if nick.lower() in lower:
            return nick

    return ''   # couldn't resolve

# ── First-name nickname map (common name → canonical short form) ──────────────
# Maps the long/formal version to the short version used on most sites.
FIRST_NAME_ALIASES = {
    'chigoziem':   'chig',
    'cameron':     'cam',
    'christopher': 'chris',
    'matthew':     'matt',
    'mitchell':    'mitch',
    'irvin':       'irv',
    'michael':     'mike',
    'robert':      'rob',
    'william':     'will',
    'nathaniel':   'nate',
    'benjamin':    'ben',
    'joseph':      'joe',
    'nicholas':    'nick',
    'samuel':      'sam',
    'alexander':   'alex',
    'joshua':      'josh',
    'timothy':     'tim',
    'anthony':     'tony',
    'steven':      'steve',
    'zachary':     'zach',
    'kenny':       'kenneth',
    'jon':         'jonathan',
}

# Explicit full-name aliases for typos / alternate spellings.
# Maps normalised bad name → normalised good name.
NAME_TYPO_MAP = {
    'max tomzcak':        'max tomczak',
    'lawrance toafili':   'lawrence toafili',
    'lawrence toafill':   'lawrence toafili',
    'lawrance toafill':   'lawrence toafili',
}

# ── Player name normalisation (for merge key) ─────────────────────────────────
def normalise_name(name: str) -> str:
    """Lower-case, strip accents, normalise nicknames, remove punctuation/suffixes."""
    name = name.strip()
    # Strip name suffixes
    name = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name, flags=re.IGNORECASE)
    # Decompose accents
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    # Lower-case and strip punctuation
    name = re.sub(r"[^a-z0-9 ]", '', name.lower())
    name = re.sub(r'\s+', ' ', name).strip()
    # Apply first-name nickname normalisation
    parts = name.split(' ', 1)
    if parts:
        parts[0] = FIRST_NAME_ALIASES.get(parts[0], parts[0])
        name = ' '.join(parts)
    # Apply explicit typo/alias map
    name = NAME_TYPO_MAP.get(name, name)
    return name

def canonical_display_name(name: str) -> str:
    """Return the preferred display form: short first name, correct spelling."""
    parts = name.strip().split(' ', 1)
    if not parts:
        return name
    first = FIRST_NAME_ALIASES.get(parts[0].lower(), parts[0])
    # Uppercase only the first character — .capitalize() would lowercase "A.J." → "A.j."
    first = first[0].upper() + first[1:] if first else first
    result = (first + ' ' + parts[1]) if len(parts) > 1 else first
    # Apply explicit typo map (title-cased lookup)
    result_lower = result.lower()
    if result_lower in NAME_TYPO_MAP:
        fixed = NAME_TYPO_MAP[result_lower]
        result = ' '.join(w.capitalize() for w in fixed.split())
    return result

# ── Run fetchers ──────────────────────────────────────────────────────────────
ALREADY_RUN = set()

def run_fetcher(module_name: str, extra_args: list = None):
    """Run a fetcher script once per unique (module, args) combination."""
    extra_args = extra_args or []
    run_key = f"{module_name}:{' '.join(extra_args)}"
    if run_key in ALREADY_RUN:
        return
    ALREADY_RUN.add(run_key)
    script = Path(module_name + '.py')
    if not script.exists():
        print(f"  [SKIP] {script} not found")
        return
    label = f"{script}{' ' + ' '.join(extra_args) if extra_args else ''}"
    print(f"  Running {label} ...")
    result = subprocess.run([sys.executable, str(script)] + extra_args,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [WARN] {label} exited {result.returncode}")
        if result.stderr:
            print("  stderr:", result.stderr[-400:])
    else:
        lines = result.stdout.strip().splitlines()
        if lines:
            print(f"    -> {lines[-1]}")

# ── Load a CSV ────────────────────────────────────────────────────────────────
def load_csv(csv_file: str, adp_col: str) -> dict:
    """
    Returns {merge_key: {'Player': ..., 'Position(s)': ..., 'Team': ..., adp_col: float}}
    Only keeps QB/RB/WR/TE/K/DST rows.
    DST players are normalised to canonical nickname + DST position.
    """
    data = {}
    path = Path(csv_file)
    if not path.exists():
        print(f"  [WARN] {csv_file} missing - skipping")
        return data

    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            raw_name = row.get('Player', '').strip()
            raw_pos  = row.get('Position(s)', '').strip()
            raw_team = row.get('Team', '').strip()
            raw_adp  = row.get(adp_col, '').strip()

            if not raw_name or not raw_adp:
                continue
            try:
                adp_val = float(raw_adp)
            except ValueError:
                continue

            # FFPC assigns ~350 to players in their system but never actually drafted.
            # Treat anything >= 349 from FFPC as unranked (skip this source for that player).
            if 'ffpc' in csv_file.lower() and adp_val >= 349:
                continue

            # Normalise position — empty means unknown (position filled later from other sources)
            norm_pos = normalise_position(raw_pos) if raw_pos else ''

            # Non-empty position that isn't in our keep list → drop immediately
            if raw_pos and not norm_pos:
                continue

            # Defense: resolve to canonical nickname
            if norm_pos == 'DST':
                canon = normalise_dst_name(raw_name)
                if not canon:
                    continue   # couldn't map — skip
                player_out = canon
                team_out   = NICK_TO_ABBREV.get(canon, canon)  # e.g. Broncos → DEN
                merge_key  = f'dst_{canon.lower()}'
            else:
                player_out = canonical_display_name(raw_name)
                team_out   = raw_team
                merge_key  = normalise_name(raw_name)

            if merge_key not in data:
                data[merge_key] = {
                    'Player':      player_out,
                    'Position(s)': norm_pos,
                    'Team':        team_out,
                    adp_col:       adp_val,
                }
            else:
                # Update position/team if we got better data
                if not data[merge_key].get('Position(s)') and norm_pos:
                    data[merge_key]['Position(s)'] = norm_pos
                if not data[merge_key].get('Team') and team_out:
                    data[merge_key]['Team'] = team_out
                data[merge_key][adp_col] = adp_val

    return data

# ── Merge all sources ─────────────────────────────────────────────────────────
def merge(all_data: list) -> list:
    master = {}

    for label, source in all_data:
        for merge_key, row in source.items():
            if merge_key not in master:
                master[merge_key] = {
                    'Player':      row['Player'],
                    'Position(s)': row['Position(s)'],
                    'Team':        row['Team'],
                }
            if not master[merge_key].get('Position(s)') and row.get('Position(s)'):
                master[merge_key]['Position(s)'] = row['Position(s)']
            if not master[merge_key].get('Team') and row.get('Team'):
                master[merge_key]['Team'] = row['Team']
            master[merge_key][label] = row[label]

    rows = []
    for merge_key, row in master.items():
        site_vals = {c: row[c] for c in SITE_COLS if isinstance(row.get(c), float)}

        # ── Outlier detection ──────────────────────────────────────────────────
        # If a site's ADP is more than 4x the median of all other sites that have
        # a value, treat it as a placeholder/bad data (exclude from consensus and
        # show as 999).  This catches ESPN's ~170 default for top players, etc.,
        # without needing a hard cutoff that would discard real late-round picks.
        if len(site_vals) >= 2:
            all_v = sorted(site_vals.values())
            mid   = len(all_v) // 2
            median = (all_v[mid - 1] + all_v[mid]) / 2 if len(all_v) % 2 == 0 else all_v[mid]
            cleaned = {}
            for c, v in site_vals.items():
                others = [x for k, x in site_vals.items() if k != c]
                if others:
                    other_median = sorted(others)[len(others) // 2]
                    if other_median > 0 and v / other_median > 4:
                        continue   # outlier — exclude this site's value
                cleaned[c] = v
            site_vals = cleaned

        real_vals = list(site_vals.values())
        consensus = round(sum(real_vals) / len(real_vals), 1) if real_vals else None
        out = {
            'Player':      row['Player'],
            'Position(s)': row.get('Position(s)', ''),
            'Team':        row.get('Team', ''),
            'NFL':         999,   # no fetcher yet; 999 keeps sheet sorting correct
        }
        for c in SITE_COLS:
            v = site_vals.get(c)
            # 999 for missing/outlier — keeps sheet sorting working
            out[c] = round(v, 1) if v is not None else 999

        # Reference columns excluded from consensus — pass through raw values
        for ref_col in ('Sleeper_STD', 'Sleeper_Half', 'Sleeper_2QB'):
            raw = row.get(ref_col)
            out[ref_col] = round(float(raw), 1) if raw else 999

        out['Consensus'] = consensus if consensus is not None else ''
        rows.append(out)

    # Drop players whose position is still unknown after merging all sources
    rows = [r for r in rows if r['Position(s)'] in ('QB', 'RB', 'WR', 'TE', 'DST')]

    # Drop players with no real ADP on any site (all 999 — only existed as FFPC phantoms)
    rows = [r for r in rows if any(r.get(c, 999) != 999 for c in SITE_COLS)]

    # Drop players whose only data point is ESPN ~170 (placeholder for unranked players).
    # Keep them if any other site has a real ADP.
    def espn_is_placeholder(r):
        espn = r.get('ESPN', 999)
        return isinstance(espn, (int, float)) and 168 <= espn <= 172

    rows = [r for r in rows if not (
        espn_is_placeholder(r) and
        all(r.get(c, 999) == 999 for c in SITE_COLS if c != 'ESPN')
    )]

    rows.sort(key=lambda r: r['Consensus'] if r['Consensus'] != '' else 9999)
    return rows

# ── Write to Google Sheets ────────────────────────────────────────────────────
def push_to_sheets(rows: list):
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        print("  [SKIP] google-api-python-client not installed")
        return

    print(f"  Authenticating with service account...")
    creds = Credentials.from_service_account_file(
        SERVICE_ACCT,
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    sheet   = service.spreadsheets()

    # Data rows only — never touch row 1 (headers) so WP DataTables keeps its
    # column mapping. Add/rename columns in the sheet manually; script just fills data.
    values = []
    for r in rows:
        values.append([r.get(col, '') for col in SHEET_COLS])

    print(f"  Clearing data rows in '{SHEET_TAB}' (row 1 header preserved)...")
    sheet.values().clear(
        spreadsheetId=SHEET_ID,
        range=f'{SHEET_TAB}!A2:Z',
    ).execute()

    print(f"  Writing {len(rows)} data rows...")
    sheet.values().update(
        spreadsheetId=SHEET_ID,
        range=f'{SHEET_TAB}!A2',
        valueInputOption='RAW',
        body={'values': values},
    ).execute()

    print(f"  Google Sheet updated -> {len(rows)} players written")

    # Stamp the Update Date tab B2 with current date/time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo('America/New_York'))
    ts = f"{now.month}/{now.day} {now.strftime('%I').lstrip('0')}:{now.strftime('%M')}{now.strftime('%p')}"
    sheet.values().update(
        spreadsheetId=SHEET_ID,
        range='Update Date!B2',
        valueInputOption='RAW',
        body={'values': [[ts]]},
    ).execute()
    print(f"  Timestamp written -> 'Update Date'!B2 = {ts}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sheets", action="store_true",
                     help="Skip pushing combined_adp.csv to the Google Sheet")
    args = ap.parse_args()

    print("=" * 60)
    print("FF ADP Combined Runner")
    print("=" * 60)

    print("\n[1/4] Fetching data from all sources...")
    for module_name, csv_file, adp_col, label, extra_args in SOURCES:
        run_fetcher(module_name, extra_args)

    print("\n[2/4] Loading & filtering CSVs...")
    all_data = []
    for module_name, csv_file, adp_col, label, extra_args in SOURCES:
        data = load_csv(csv_file, adp_col)
        print(f"  {label:10s}: {len(data):>4} players  ({csv_file})")
        all_data.append((label, data))

    print("\n[3/4] Merging...")
    rows = merge(all_data)

    # Breakdown by position
    from collections import Counter
    pos_counts = Counter(r['Position(s)'] for r in rows)
    print(f"  Total: {len(rows)} players")
    for pos in ['QB', 'RB', 'WR', 'TE', 'DST']:
        print(f"    {pos}: {pos_counts.get(pos, 0)}")

    out_file = 'combined_adp.csv'
    with open(out_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved -> {out_file}")

    if not args.no_sheets:
        print("\n[4/4] Pushing to Google Sheets...")
        push_to_sheets(rows)
    else:
        print("\n[4/4] [SKIP] Pushing to Google Sheets (--no-sheets)")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)

    # Top 10 sanity check
    print("\nTop 10 by Consensus:")
    print(f"  {'Player':<25} {'Pos':<5} {'SLR':>5} {'ESPN':>5} {'YAH':>5} "
          f"{'CBS':>5} {'FTX':>5} {'FFPC':>5} {'BB10':>5} {'NFFC':>5} "
          f"{'UD':>5} {'CON':>6}")
    print("  " + "-" * 80)
    for r in rows[:10]:
        print(f"  {r['Player']:<25} {r.get('Position(s)',''):<5} "
              f"{str(r.get('Sleeper','')):>5} {str(r.get('ESPN','')):>5} "
              f"{str(r.get('Yahoo!','')):>5} {str(r.get('CBS','')):>5} "
              f"{str(r.get('Fantrax','')):>5} {str(r.get('FFPC','')):>5} "
              f"{str(r.get('BB10s','')):>5} {str(r.get('NFFC','')):>5} "
              f"{str(r.get('Underdog','')):>5} {str(r.get('Consensus','')):>6}")

    # Show DST sample
    print("\nDefense sample:")
    dst_rows = [r for r in rows if r['Position(s)'] == 'DST']
    for r in dst_rows[:5]:
        print(f"  {r['Player']:<15} "
              f"SLR:{str(r.get('Sleeper','')):>5}  ESPN:{str(r.get('ESPN','')):>5}  "
              f"YAH:{str(r.get('Yahoo!','')):>5}  CON:{str(r.get('Consensus','')):>6}")

if __name__ == '__main__':
    main()
