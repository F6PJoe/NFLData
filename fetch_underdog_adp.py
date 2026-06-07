"""
fetch_underdog_adp.py
Pull ADP from Underdog Fantasy's CSV download endpoint.
Outputs: underdog_adp.csv  (Player, Position(s), Team, Underdog)
"""

import os, csv, io, re, requests
from dotenv import load_dotenv, set_key

load_dotenv('.env')

# ── Team name normalisation ───────────────────────────────────────────────────
# Underdog returns full franchise names; convert to standard abbreviations.
TEAM_NAME_TO_ABBREV = {
    'Arizona Cardinals':      'ARI',  'Atlanta Falcons':       'ATL',
    'Baltimore Ravens':       'BAL',  'Buffalo Bills':         'BUF',
    'Carolina Panthers':      'CAR',  'Chicago Bears':         'CHI',
    'Cincinnati Bengals':     'CIN',  'Cleveland Browns':      'CLE',
    'Dallas Cowboys':         'DAL',  'Denver Broncos':        'DEN',
    'Detroit Lions':          'DET',  'Green Bay Packers':     'GB',
    'Houston Texans':         'HOU',  'Indianapolis Colts':    'IND',
    'Jacksonville Jaguars':   'JAC',  'Kansas City Chiefs':    'KC',
    'Las Vegas Raiders':      'LV',   'Los Angeles Chargers':  'LAC',
    'Los Angeles Rams':       'LAR',  'Miami Dolphins':        'MIA',
    'Minnesota Vikings':      'MIN',  'New England Patriots':  'NE',
    'New Orleans Saints':     'NO',   'New York Giants':       'NYG',
    'New York Jets':          'NYJ',  'Philadelphia Eagles':   'PHI',
    'Pittsburgh Steelers':    'PIT',  'San Francisco 49ers':   'SF',
    'Seattle Seahawks':       'SEA',  'Tampa Bay Buccaneers':  'TB',
    'Tennessee Titans':       'TEN',  'Washington Commanders': 'WAS',
}

def normalise_team(raw: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(raw.strip(), raw.strip())

# ── Player name normalisation ─────────────────────────────────────────────────
# Underdog sometimes uses "J. Michael Sturdivant" (initial + middle + last).
# Expand to "John Michael Sturdivant" is impossible without a lookup, but we
# can reformat "J. Michael Last" → "J Michael Last" (drop period) so the merge
# key matches if other sites also abbreviate the first name the same way.
def normalise_player_name(first: str, last: str) -> str:
    first = first.strip().rstrip('.')   # strip trailing period from initials
    last  = last.strip()
    return f"{first} {last}".strip()

# ── Auth ──────────────────────────────────────────────────────────────────────
CLIENT_ID   = 'cQvYz1T2BAFbix4dYR37dyD9O0Thf1s6'
AUTH0_URL   = 'https://login.underdogsports.com/oauth/token'

def get_access_token():
    refresh_token = os.environ.get('UNDERDOG_REFRESH_TOKEN', '')
    if refresh_token:
        r = requests.post(AUTH0_URL, json={
            'grant_type':    'refresh_token',
            'refresh_token': refresh_token,
            'client_id':     CLIENT_ID,
        }, timeout=30)
        if r.status_code == 200:
            data = r.json()
            # Persist new refresh token if rotated
            new_rt = data.get('refresh_token')
            if new_rt and new_rt != refresh_token:
                set_key('.env', 'UNDERDOG_REFRESH_TOKEN', new_rt)
            return data['access_token']
        print(f"Refresh token failed ({r.status_code}), trying password grant…")

    email    = os.environ.get('UNDERDOG_EMAIL', '')
    password = os.environ.get('UNDERDOG_PASSWORD', '')
    r = requests.post(AUTH0_URL, json={
        'grant_type': 'password',
        'username':   email,
        'password':   password,
        'audience':   'https://api.underdogfantasy.com',
        'client_id':  CLIENT_ID,
        'scope':      'offline_access',
    }, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Auth failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    set_key('.env', 'UNDERDOG_REFRESH_TOKEN', data['refresh_token'])
    return data['access_token']

# ── Download endpoint ─────────────────────────────────────────────────────────
SLATE_ID   = 'a9c04e81-1ace-4b16-a31d-4c725a47f16f'
RANKING_ID = 'ccf300b0-9197-5951-bd96-cba84ad71e86'
STYLE_ID   = '9e62863e-1b29-53e8-8aca-2aae06aaac5f'
PARAMS     = ('product=fantasy'
              '&product_experience_id=018e1234-5678-9abc-def0-123456789002'
              '&state_config_id=f4cec80a-aede-451c-a0c2-87887b1a7a16')

DOWNLOAD_URL = (
    f'https://app.underdogsports.com/rankings/download'
    f'/{SLATE_ID}/{RANKING_ID}/{STYLE_ID}?{PARAMS}'
)

def fetch_csv(token):
    headers = {
        'Authorization': token,
        'Accept':        'text/csv,*/*',
        'client-type':   'web',
        'Origin':        'https://app.underdogsports.com',
        'Referer':       f'https://app.underdogsports.com/rankings/nfl/{SLATE_ID}',
        'User-Agent':    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0.0.0 Safari/537.36'),
    }
    r = requests.get(DOWNLOAD_URL, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Download failed: {r.status_code} {r.text[:300]}")
    return r.text

# ── Parse CSV ─────────────────────────────────────────────────────────────────
def parse(raw_csv):
    """
    Underdog CSV columns vary by version; we look for the ADP/pick column
    and the player name/position/team columns by header name.
    """
    reader = csv.DictReader(io.StringIO(raw_csv))
    headers = reader.fieldnames or []
    print(f"CSV headers: {headers}")

    # Normalise header names for lookup
    norm = {h.strip().lower(): h for h in headers}

    def col(*candidates):
        for c in candidates:
            if c in norm:
                return norm[c]
        return None

    # Underdog CSV uses firstName/lastName split, slotName for position, teamName for team
    first_col = col('firstname', 'first name', 'first', 'player')
    last_col  = col('lastname',  'last name',  'last')
    pos_col   = col('slotname', 'position', 'pos', 'slot')
    team_col  = col('teamname', 'team')
    adp_col   = col('adp', 'average pick', 'avg pick', 'pick', 'average draft position')

    print(f"Using columns -> first:{first_col} last:{last_col} pos:{pos_col} team:{team_col} adp:{adp_col}")

    rows = []
    for row in reader:
        first = row.get(first_col, '').strip() if first_col else ''
        last  = row.get(last_col,  '').strip() if last_col  else ''
        name  = normalise_player_name(first, last) if last_col else first
        pos   = row.get(pos_col,  '').strip() if pos_col  else ''
        team  = normalise_team(row.get(team_col, '') if team_col else '')
        adp   = row.get(adp_col,  '').strip() if adp_col  else ''

        if not name or not adp:
            continue
        try:
            adp_val = round(float(adp), 1)
        except ValueError:
            continue
        rows.append({'Player': name, 'Position(s)': pos, 'Team': team, 'Underdog': adp_val})

    return rows

# ── Write output ──────────────────────────────────────────────────────────────
OUT_FILE = 'underdog_adp.csv'

def main():
    print("Getting access token…")
    token = get_access_token()
    print("Token OK. Downloading CSV…")

    raw = fetch_csv(token)
    print(f"Downloaded {len(raw):,} chars")

    # Show first 500 chars so we can verify format
    print("--- raw preview ---")
    print(raw[:500])
    print("-------------------")

    rows = parse(raw)
    print(f"Parsed {len(rows)} players")
    if rows:
        print("Sample:", rows[:3])

    with open(OUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Player', 'Position(s)', 'Team', 'Underdog'])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved -> {OUT_FILE}")

if __name__ == '__main__':
    main()
