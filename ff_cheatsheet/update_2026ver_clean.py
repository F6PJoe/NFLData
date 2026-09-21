#!/usr/bin/env python3
"""
2026 cheat sheet full update — run once per season.

Touches:
  Projection tabs  : A-D (player info), G-N raw stats (+ O Fum for QB).
                     Formula cols E/F/O/P/Q autofilled down to last player row.
                     Rows beyond last player are fully cleared (no formula orphans).
  ADP tab          : fully replaced from combined_adp.csv, names normalised.
  Cheat Sheet      : A-D written (Name, Team, Bye, Pos).
                     Formula cols E-L and N-U autofilled to last player row.
                     Col M written as ADP VLOOKUP formula (single ADP tab).
                     Rows beyond last player cleared (E-U).
  Joe Bond Ranks   : fetched from Google Drive, names aligned to Cheat Sheet,
                     written into the JB Ranks tab.  Leftover rows cleared.

NEVER use openpyxl to save — it strips Data Validation and Conditional Formatting.
"""

import argparse
import csv
import importlib
import io
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import win32com.client as win32
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE         = Path(__file__).resolve().parent.parent
SOURCE       = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2025-Football-Cheat-Sheet-working-copy-new-formula-testing.xlsm"
TARGET       = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsx"
SERVICE_ACCT = BASE / "triple-baton-456523-e4-b9ec3cbd6e3d.json"

# Google Drive file IDs for Joe Bond rankings
JB_FILES = {
    "half_ppr": "1Hcve5KKV3BHzg2zbbk7jq90TvHxivoFI",
    "ppr":      "1M4ybR_UtAsiOv-HfXk1xqGMDyfwAO-xq",
    "standard": "1yfBiu27-328aEG5Bri6t33gQXQBbwlNG",
}
JB_START_COL = {"half_ppr": "A", "ppr": "E", "standard": "I"}

LIMITS = {"QB": 64, "RB": 125, "WR": 165, "TE": 65}

xlUp       = -4162
xlFillCopy = 0
xlOpenXMLWorkbook             = 51   # .xlsx, no macros — TARGET's format
xlOpenXMLWorkbookMacroEnabled = 52   # .xlsm — SOURCE's format only

# ── Name normalisation maps ───────────────────────────────────────────────────

# Consensus CSV name -> canonical
PROJ_RENAMES = {
    'Cam Ward':            'Cameron Ward',
    'Tank Dell':           'Nathaniel Dell',
    'Hollywood Brown':     'Marquise Brown',
    'Chris Brooks':        'Christopher Brooks',
    'Chig Okonkwo':        'Chigoziem Okonkwo',
    'Mitch Evans':         'Mitchell Evans',
    'M. Valdes-Scantling': 'Marquez Valdes-Scantling',
    'Mike Penix':          'Michael Penix Jr.',
    'Mike Penix Jr.':      'Michael Penix Jr.',
    'Mike Pittman':        'Michael Pittman Jr.',
    'Mike Pittman Jr.':    'Michael Pittman Jr.',
}

# combined_adp.csv name -> canonical (superset of PROJ_RENAMES)
ADP_RENAMES = {
    **PROJ_RENAMES,
    # Suffix drops
    'Kenneth Walker':      'Kenneth Walker III',
    'Travis Etienne':      'Travis Etienne Jr.',
    'Luther Burden':       'Luther Burden III',
    'Harold Fannin':       'Harold Fannin Jr.',
    'Marvin Harrison':     'Marvin Harrison Jr.',
    'Kyle Pitts':          'Kyle Pitts Sr.',
    'Brian Thomas':        'Brian Thomas Jr.',
    'Aaron Jones':         'Aaron Jones Sr.',
    'Chris Rodriguez':     'Chris Rodriguez Jr.',
    'Omar Cooper':         'Omar Cooper Jr.',
    'Tyrone Tracy':        'Tyrone Tracy Jr.',
    'Brian Robinson':      'Brian Robinson Jr.',
    'Mike Washington':     'Mike Washington Jr.',
    'Chris Brazzell':      'Chris Brazzell II',
    'Marvin Mims':         'Marvin Mims Jr.',
    # Capitalisation / full-name differences
    'Dan Jones':           'Daniel Jones',
    'Matt Stafford':       'Matthew Stafford',
    'C.j. Stroud':         'C.J. Stroud',
    'J.j. McCarthy':       'J.J. McCarthy',
    'Tony Richardson Sr.': 'Anthony Richardson Sr.',
    'Jon Taylor':          'Jonathan Taylor',
    "De'von Achane":       "De'Von Achane",
    'James Cook':          'James Cook III',
    "D'andre Swift":       "D'Andre Swift",
    'Treveyon Henderson':  'TreVeyon Henderson',
    'Rj Harvey':           'RJ Harvey',
    'J.k. Dobbins':        'J.K. Dobbins',
    'Marshawn Lloyd':      'MarShawn Lloyd',
    'Dj Giddens':          'DJ Giddens',
    'Nick Singleton':      'Nicholas Singleton',
    'Aj Dillon':           'AJ Dillon',
    'Lequint Allen Jr.':   'LeQuint Allen Jr.',
    "J'mari Taylor":       "J'Mari Taylor",
    'Rob Henry':           'Robert Henry Jr.',
    'Mike Carter':         'Michael Carter',
    "Ja'marr Chase":       "Ja'Marr Chase",
    'Amon-ra St. Brown':   'Amon-Ra St. Brown',
    'Ceedee Lamb':         'CeeDee Lamb',
    'A.j. Brown':          'A.J. Brown',
    'Devonta Smith':       'DeVonta Smith',
    # Projections use the dotted initialisms — canonicalise ADP's undotted forms
    'Dj Moore':            'D.J. Moore',
    'DJ Moore':            'D.J. Moore',
    'Dk Metcalf':          'D.K. Metcalf',
    'DK Metcalf':          'D.K. Metcalf',
    'Kenneth Gainwell':    'Kenny Gainwell',
    'Chris Godwin':        'Chris Godwin Jr.',
    'Mike Wilson':         'Michael Wilson',
    "Wan'dale Robinson":   "Wan'Dale Robinson",
    'Matt Golden':         'Matthew Golden',
    'K.c. Concepcion':     'KC Concepcion',
    'Tre Harris':          "Tre' Harris",
    "Ja'kobi Lane":        "Ja'Kobi Lane",
    "De'zhaun Stribling":  "De'Zhaun Stribling",
    'Kavontae Turpin':     'KaVontae Turpin',
    'Josh Palmer':         'Joshua Palmer',
    'Demario Douglas':     'DeMario Douglas',
    'Mitch Tinsley':       'Mitchell Tinsley',
    'Keandre Lambert-Smith': 'KeAndre Lambert-Smith',
    'Cj Daniels':          'CJ Daniels',
    'Juju Smith-Schuster': 'JuJu Smith-Schuster',
    'Cj Williams':         'CJ Williams',
    'Oronde Gadsden II':   'Oronde Gadsden',
    'T.j. Hockenson':      'T.J. Hockenson',
    'Aj Barner':           'AJ Barner',
    'Mike Mayer':          'Michael Mayer',
    "Ja'tavion Sanders":   "Ja'Tavion Sanders",
    'Dan Bellinger':       'Daniel Bellinger',
    'Mike Trigg':          'Michael Trigg',
    'Matt Hibner':         'Matthew Hibner',
}

# Joe Bond CSV name -> canonical (explicit overrides; norm-based fallback also used)
JB_RENAMES = {
    'Cam Ward':        'Cameron Ward',
    'Chig Okonkwo':    'Chigoziem Okonkwo',
    'Tank Dell':       'Nathaniel Dell',
    'Hollywood Brown': 'Marquise Brown',
    'Chris Brooks':    'Christopher Brooks',
    'Mike Penix':      'Michael Penix Jr.',
    'Mike Penix Jr.':  'Michael Penix Jr.',
    'Mike Pittman':    'Michael Pittman Jr.',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(v, default=0.0):
    try:
        return float(v) if v not in (None, '', 'None') else default
    except (TypeError, ValueError):
        return default


def normalise_name(name):
    """Fold accents, strip punctuation, lowercase, drop suffix — for fuzzy matching."""
    name = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"['.]", "", name.lower()).replace("-", " ")
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", name)
    return name.strip()


def autofill_col(sh, col, last_row):
    """AutoFill a formula from row 2 of `col` down through `last_row`."""
    if last_row > 2:
        sh.Range(f"{col}2").AutoFill(sh.Range(f"{col}2:{col}{last_row}"), xlFillCopy)


# ── Projection data loader ────────────────────────────────────────────────────

def bye_for(team, raw_bye):
    """Free agents carry over a stale bye week from their last team — blank it instead."""
    return "" if team == "FA" else safe_float(raw_bye)


def dedupe_by_name(rows_raw):
    """
    rows_raw: list of (score, canonical_name, csv_row), sorted by score descending.
    PROJ_RENAMES can map two different source spellings (e.g. "Chris Brooks" and
    "Christopher Brooks") onto the same canonical name — keep only the
    highest-scoring row per canonical name.
    """
    seen, rows = set(), []
    for item in rows_raw:
        if item[1] not in seen:
            seen.add(item[1])
            rows.append(item)
    return rows


def load_projections():
    out = {}

    with open(BASE / "ff_draft_proj" / "consensus_qb.csv", newline='', encoding='utf-8') as f:
        rows_raw = sorted(
            [(safe_float(r.get('Fantasy Points')), ADP_RENAMES.get(r['QB'].strip(), r['QB'].strip()), r)
             for r in csv.DictReader(f)],
            reverse=True
        )
        rows = dedupe_by_name(rows_raw)[:LIMITS['QB']]
    out['QB'] = [(name, r.get('Team',''), bye_for(r.get('Team',''), r.get('Bye')), 'QB',
                  safe_float(r.get('Pass Att')), safe_float(r.get('Pass Comp')),
                  safe_float(r.get('Pass Yds')), safe_float(r.get('Pass TD')),
                  safe_float(r.get('Pass Int')), safe_float(r.get('Rush Att')),
                  safe_float(r.get('Rush Yds')), safe_float(r.get('Rush TD')),
                  safe_float(r.get('Fumbles')))
                 for _, name, r in rows]

    with open(BASE / "ff_draft_proj" / "consensus_rb.csv", newline='', encoding='utf-8') as f:
        rows_raw = sorted(
            [(safe_float(r.get('Fantasy Points (Half-PPR)')), ADP_RENAMES.get(r['RB'].strip(), r['RB'].strip()), r)
             for r in csv.DictReader(f)],
            reverse=True
        )
        rows = dedupe_by_name(rows_raw)[:LIMITS['RB']]
    out['RB'] = [(name, r.get('Team',''), bye_for(r.get('Team',''), r.get('Bye')), 'RB',
                  safe_float(r.get('Rush Att')), safe_float(r.get('Rush Yds')),
                  safe_float(r.get('Rush TD')), safe_float(r.get('Targets')),
                  safe_float(r.get('Rec')), safe_float(r.get('Rec Yds')),
                  safe_float(r.get('Rec TD')), safe_float(r.get('Fum')))
                 for _, name, r in rows]

    with open(BASE / "ff_draft_proj" / "consensus_wr.csv", newline='', encoding='utf-8') as f:
        rows_raw = sorted(
            [(safe_float(r.get('Fantasy Points (Half)')), ADP_RENAMES.get(r['WR'].strip(), r['WR'].strip()), r)
             for r in csv.DictReader(f)],
            reverse=True
        )
        rows = dedupe_by_name(rows_raw)[:LIMITS['WR']]
    out['WR'] = [(name, r.get('Team',''), bye_for(r.get('Team',''), r.get('Bye')), 'WR',
                  safe_float(r.get('Targets')), safe_float(r.get('Rec')),
                  safe_float(r.get('Rec Yds')), safe_float(r.get('Rec TD')),
                  safe_float(r.get('Rush Att')), safe_float(r.get('Rush Yds')),
                  safe_float(r.get('Rush TD')), safe_float(r.get('Fum')))
                 for _, name, r in rows]

    with open(BASE / "ff_draft_proj" / "consensus_te.csv", newline='', encoding='utf-8') as f:
        rows_raw = sorted(
            [(safe_float(r.get('Fantasy Points (Half-PPR)')), ADP_RENAMES.get(r['TE'].strip(), r['TE'].strip()), r)
             for r in csv.DictReader(f)],
            reverse=True
        )
        rows = dedupe_by_name(rows_raw)[:LIMITS['TE']]
    out['TE'] = [(name, r.get('Team',''), bye_for(r.get('Team',''), r.get('Bye')), 'TE',
                  safe_float(r.get('Targets')), safe_float(r.get('Rec')),
                  safe_float(r.get('Rec Yds')), safe_float(r.get('Rec TD')),
                  safe_float(r.get('Rush Att')), safe_float(r.get('Rush Yds')),
                  safe_float(r.get('Rush TD')), None)
                 for _, name, r in rows]

    return out


# ── Tab writers ───────────────────────────────────────────────────────────────

def write_projection_tab(sh, rows, pos):
    """
    Write stats to a projection tab.
    - Saves formula strings from row 2 (E, F, O[non-QB], P, Q).
    - Clears the full used range (removes formula orphans beyond new data).
    - Writes A-D and stat cols.
    - AutoFills saved formulas down to the last player row.
    """
    old_last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    new_last = 1 + len(rows)
    clear_to = max(old_last, new_last + 2)

    # Save formula strings before clearing
    saved = {}
    for col in ('E', 'F', 'Q'):
        f = sh.Range(f"{col}2").Formula
        if f and f.startswith('='):
            saved[col] = f
    for col in ('O', 'P'):
        f = sh.Range(f"{col}2").Formula
        if f and f.startswith('='):
            saved[col] = f

    # Clear everything (removes orphan formula rows)
    sh.Range(f"A2:Q{clear_to}").ClearContents()

    # Write player info A-D
    sh.Range(f"A2:D{new_last}").Value = [[r[0], r[1], r[2], r[3]] for r in rows]

    # Write raw stats
    if pos == 'QB':
        # G-O: PassAtt Cmp Yds TD Int RushAtt RushYds RushTD Fum
        sh.Range(f"G2:O{new_last}").Value = [
            [r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12]] for r in rows
        ]
    else:
        # G-N: 8 stat cols
        sh.Range(f"G2:N{new_last}").Value = [
            [r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11]] for r in rows
        ]

    # Re-seed row 2 formulas and autofill down
    for col, formula in saved.items():
        if pos == 'QB' and col == 'O':
            continue  # QB col O = Fum, already written as static value
        sh.Range(f"{col}2").Formula = formula
        autofill_col(sh, col, new_last)

    print(f"  {pos}: {len(rows)} players, formulas filled to row {new_last}, cleared to row {clear_to}")


def write_jb_ranks(wb, drive_svc, cheat_names):
    """Fetch JB rankings from Drive and write to Joe Bond Ranks tab."""
    sh = wb.Sheets("Joe Bond Ranks")

    def align(name):
        canonical = JB_RENAMES.get(name) or JB_RENAMES.get(name.strip())
        if canonical:
            return canonical
        return cheat_names.get(normalise_name(name), name)

    for label, file_id in JB_FILES.items():
        col = JB_START_COL[label]
        col2, col3 = chr(ord(col)+1), chr(ord(col)+2)

        # Download CSV from Drive
        req = drive_svc.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        csv_rows = list(csv.reader(io.StringIO(buf.getvalue().decode("utf-8"))))
        players = [(r[0], r[1]) for r in csv_rows[2:] if r[0].strip()]

        old_last = sh.Cells(sh.Rows.Count, col).End(xlUp).Row
        new_last = 1 + len(players)

        values = [[align(name), team, i + 1] for i, (name, team) in enumerate(players)]
        sh.Range(f"{col}2:{col3}{new_last}").Value = values

        # Clear leftover rows
        if new_last < old_last:
            sh.Range(f"{col}{new_last+1}:{col3}{old_last}").ClearContents()

        print(f"  JB {label}: {len(players)} players -> {col}:{col3}, cleared to {old_last}")


# ── Main ──────────────────────────────────────────────────────────────────────

def pull_projections_from_sheets():
    """
    Pull the 4AM-updated consensus projections from Google Sheets instead of
    re-fetching from all 10 sites.  Keeps cheat sheet projections in sync with
    the published sheet and avoids hammering projection sites on every run.
    Use --force-refresh to bypass this and re-fetch from all sources instead.
    """
    print("Pulling projections from Google Sheet (4AM data)...")
    result = subprocess.run([sys.executable, "pull_from_sheets.py"],
                             cwd=str(BASE / "ff_draft_proj"), capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        print(f"  [WARN] pull_from_sheets.py exited {result.returncode} — falling back to existing CSVs")


PROTECT_PROPS = [
    "AllowFormattingCells", "AllowFormattingColumns", "AllowFormattingRows",
    "AllowInsertingColumns", "AllowInsertingRows", "AllowInsertingHyperlinks",
    "AllowDeletingColumns", "AllowDeletingRows", "AllowSorting", "AllowFiltering",
    "AllowUsingPivotTables",
]


def unprotect_all(wb):
    """Unprotect every protected sheet; return the names/settings found."""
    state = []
    for sh in wb.Worksheets:
        if sh.ProtectContents:
            p = sh.Protection
            state.append((sh.Name, {k: bool(getattr(p, k)) for k in PROTECT_PROPS}))
            sh.Unprotect()   # no password on this workbook
    return state


def dispatch_excel():
    """
    Start Excel via COM, surviving a corrupted win32com type-library cache.

    gencache.EnsureDispatch() writes generated wrappers under
    %LOCALAPPDATA%\\Temp\\gen_py. That cache gets corrupted periodically
    (interrupted run, two processes generating it at once) and then every
    later run dies with "module ... has no attribute CLSIDToClassMap".
    Nuke the cache and retry; if it still fails, fall back to late binding,
    which needs no cache at all. Every Excel constant this script uses is
    already a hardcoded int (xlUp, xlOpenXMLWorkbook, ...), so late binding
    is functionally equivalent here.
    """
    import shutil as _shutil

    import win32com
    import win32com.client.dynamic

    try:
        return win32.gencache.EnsureDispatch("Excel.Application")
    except AttributeError as e:
        print(f"  [WARN] win32com cache corrupted ({e}) — clearing and retrying...")

    # Purge the generated-wrapper cache on disk AND the already-imported
    # stale modules, otherwise the bad module is served straight from
    # sys.modules and the retry fails exactly the same way.
    try:
        _shutil.rmtree(win32com.__gen_path__, ignore_errors=True)
        for mod in [m for m in sys.modules if m.startswith("win32com.gen_py")]:
            del sys.modules[mod]
        importlib.reload(win32com.client.gencache)
        return win32com.client.gencache.EnsureDispatch("Excel.Application")
    except Exception as e2:
        print(f"  [WARN] cache rebuild failed ({e2}) — using late binding instead")

    # dynamic.Dispatch bypasses gencache entirely. Every Excel constant this
    # script uses is a hardcoded int, so nothing here needs early binding.
    return win32com.client.dynamic.Dispatch("Excel.Application")


def refresh_sources():
    """
    Re-fetch projections from all 10 sites and rebuild ADP from all sources.
    Used only with --force-refresh (e.g. midday injury/trade update).
    Individual fetcher failures degrade gracefully — run_all.py keeps going.
    """
    print("Refreshing projections (ff_draft_proj/run_all.py --no-sheets)...")
    result = subprocess.run([sys.executable, "run_all.py", "--no-sheets"],
                             cwd=str(BASE / "ff_draft_proj"), capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    proj_warnings = [l.strip() for l in result.stdout.splitlines() if "[WARN]" in l]
    if result.returncode != 0:
        print(f"  [WARN] ff_draft_proj/run_all.py exited {result.returncode} — continuing with existing CSVs")

    print("Refreshing ADP (ff_adp/run_all.py --no-sheets)...")
    result = subprocess.run([sys.executable, "run_all.py", "--no-sheets"],
                             cwd=str(BASE / "ff_adp"), capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    adp_warnings = [l.strip() for l in result.stdout.splitlines() if "[WARN]" in l]
    if result.returncode != 0:
        print(f"  [WARN] ff_adp/run_all.py exited {result.returncode} — continuing with existing CSV")

    print("\n" + "=" * 60)
    print("SOURCE HEALTH CHECK")
    print("=" * 60)
    if proj_warnings:
        print(f"Projections: {len(proj_warnings)} source(s) FAILED —")
        for w in proj_warnings:
            print(f"  {w}")
    else:
        print("Projections: all 10 sources OK")
    if adp_warnings:
        print(f"ADP: {len(adp_warnings)} source(s) FAILED —")
        for w in adp_warnings:
            print(f"  {w}")
    else:
        print("ADP: all sources OK")
    print("=" * 60 + "\n")


def main():
    ap = argparse.ArgumentParser(description="2026 cheat sheet full update")
    ap.add_argument("--force-refresh", action="store_true",
                    help="Re-fetch projections from all 10 sites instead of pulling from Google Sheet")
    args = ap.parse_args()

    if args.force_refresh:
        refresh_sources()
    else:
        pull_projections_from_sheets()
        print("Refreshing ADP (ff_adp/run_all.py --no-sheets)...")
        result = subprocess.run([sys.executable, "run_all.py", "--no-sheets"],
                                 cwd=str(BASE / "ff_adp"), capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            print(f"  [WARN] ff_adp/run_all.py exited {result.returncode} — continuing with existing CSV")

    # ── Load CSV data ─────────────────────────────────────────────────────────
    print("\nLoading projection CSVs...")
    projections = load_projections()
    for pos, rows in projections.items():
        print(f"  {pos}: {len(rows)} players")

    print("Loading ADP CSV...")
    consensus = {}
    adp_source = []
    with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = r.get('Consensus', '')
            if not c:
                continue
            adp_val = float(c)
            name = r['Player']
            consensus[name] = adp_val
            adp_source.append((adp_val, [
                name, round(adp_val, 2),
                r.get('Position(s)', ''), r.get('Team', ''),
                safe_float(r.get('Underdog'))      or None,
                safe_float(r.get('CBS'))           or None,
                safe_float(r.get('ESPN'))          or None,
                safe_float(r.get('FFPC'))          or None,
                safe_float(r.get('BB10s'))         or None,
                safe_float(r.get('Yahoo!'))        or None,
                safe_float(r.get('Sleeper'))       or None,
                safe_float(r.get('Sleeper_STD'))   or None,
                safe_float(r.get('Sleeper_Half'))  or None,
                safe_float(r.get('Sleeper_2QB'))   or None,
                safe_float(r.get('Fantrax'))       or None,
                safe_float(r.get('RTSports'))      or None,
                safe_float(r.get('NFFC'))          or None,
                safe_float(r.get('NFFC Cutline'))  or None,
            ]))
    adp_source.sort(key=lambda x: x[0])
    adp_rows = [row for _, row in adp_source]
    print(f"  ADP: {len(adp_rows)} players")

    # ── Google Drive auth (do it before opening Excel so we fail fast) ────────
    print("Authenticating Google Drive...")
    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive_svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    print("  OK")

    # ── Open workbook ─────────────────────────────────────────────────────────
    excel = dispatch_excel()
    excel.Visible = False
    excel.DisplayAlerts = False

    if Path(TARGET).exists():
        print(f"\nOpening existing workbook for in-place update...")
        wb = excel.Workbooks.Open(TARGET)
    else:
        # TARGET holds the current VORP/Value+ engine (Calculations tab,
        # My Team tab, etc.) — SOURCE is a stale 2025 file with the old
        # z-score engine.  Silently rebuilding from SOURCE would quietly
        # regress the workbook to that old engine, so fail loudly instead.
        excel.Quit()
        sys.exit(
            f"TARGET not found: {TARGET}\n"
            "Refusing to auto-recreate from the 2025 SOURCE file — it has the "
            "old scoring engine, not the current VORP/Value+ one.\n"
            "Restore TARGET from a Dropbox backup/version history instead."
        )

    try:
        # ── Drop sheet protection if any is present ───────────────────────────
        # Protection blocks writes AND blocks reading .Formula on cells whose
        # format hides formulas, so the update can't run against a protected
        # workbook. Normally the working copy is left unprotected and you add
        # protection by hand before distributing; this is just a safety net if
        # a protected copy gets updated.
        protection_state = unprotect_all(wb)
        if protection_state:
            print(f"  Unprotected {len(protection_state)} sheet(s): "
                  f"{', '.join(n for n, _ in protection_state)}")

        # ── Stamp the update date (Instructions L2, e.g. "Jul 19") ────────────
        from datetime import date
        try:
            wb.Sheets("Instructions").Range("L2").Value = date.today().strftime("%b %d")
            print(f"  Update date stamped: {date.today().strftime('%b %d')}")
        except Exception as e:
            print(f"  [WARN] couldn't stamp Instructions!L2: {e}")

        # ── Delete stale per-source ADP tabs ──────────────────────────────────
        old_adp_tabs = ['Sleeper ADP', 'Underdog ADP', 'NFFC ADP',
                        'Fantrax ADP', 'RTS ADP']
        deleted = []
        for name in old_adp_tabs:
            try:
                wb.Sheets(name).Delete()
                deleted.append(name)
            except Exception:
                pass  # tab doesn't exist — fine
        if deleted:
            print(f"\nDeleted old ADP tabs: {', '.join(deleted)}")

        # ── Projection tabs ───────────────────────────────────────────────────
        print("\nProjection tabs (stats written, formulas autofilled, orphans cleared):")
        tab_names = {'QB': 'QB Projections', 'RB': 'RB Projections',
                     'WR': 'WR Projections', 'TE': 'TE Projections'}
        for pos, rows in projections.items():
            write_projection_tab(wb.Sheets(tab_names[pos]), rows, pos)

        # ── ADP tab ───────────────────────────────────────────────────────────
        print("\nADP tab:")
        adp_sh = wb.Sheets("ADP")
        adp_old_last = adp_sh.Cells(adp_sh.Rows.Count, 1).End(xlUp).Row
        adp_new_last = 1 + len(adp_rows)

        adp_headers = ["Player","ADP","Position","Team","Underdog","CBS","ESPN","FFPC",
                       "BB10s","Yahoo!","Sleeper","Sleeper_STD","Sleeper_Half",
                       "Sleeper_2QB","Fantrax","RTSports","NFFC","NFFC Cutline"]
        adp_last_col = chr(ord('A') + len(adp_headers) - 1)   # 'R' (18 cols)
        # Clear well past the layout — older layouts left stale columns as far
        # out as U (NFL at S/T, Y! at U from pre-2026 versions)
        adp_sh.Range(f"A1:Z{max(adp_old_last, adp_new_last+2)}").ClearContents()
        adp_sh.Range(f"A1:{adp_last_col}1").Value = [adp_headers]
        adp_sh.Range(f"A2:{adp_last_col}{adp_new_last}").Value = adp_rows

        renamed = 0
        for r in range(2, adp_new_last + 1):
            name = adp_sh.Cells(r, 1).Value
            if name in ADP_RENAMES:
                adp_sh.Cells(r, 1).Value = ADP_RENAMES[name]
                renamed += 1
        print(f"  {len(adp_rows)} players, {renamed} names normalised")

        # ── Cheat Sheet A-D ───────────────────────────────────────────────────
        print("\nCheat Sheet:")
        cs = wb.Sheets("Cheat Sheet")
        cs_old_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row

        # Build player list sorted by consensus ADP
        all_players = []
        for pos, rows in projections.items():
            for r in rows:
                name = r[0]
                canonical = ADP_RENAMES.get(name, name)
                sortkey = consensus.get(canonical, consensus.get(name, 1000))
                all_players.append((sortkey, canonical, r[1], r[2], pos))
        all_players.sort(key=lambda x: x[0])

        cs_new_last = 1 + len(all_players)
        cs.Range(f"A2:D{cs_new_last}").Value = [[p[1], p[2], p[3], p[4]] for p in all_players]

        # Clear A-D beyond new last row
        if cs_new_last < cs_old_last:
            cs.Range(f"A{cs_new_last+1}:D{cs_old_last}").ClearContents()

        print(f"  {len(all_players)} players written to A2:D{cs_new_last}")

        # Autofill every formula column from E through however far the tab
        # actually extends (skip M, handled separately below) — detected
        # dynamically from row 1's last used column, not a hardcoded letter,
        # so a column added later (or a stray leftover one) is never silently
        # skipped or silently dragged along.
        # NOTE: End(xlToLeft)/End(xlToRight) are unreliable here (confirmed
        # to report a wrong column even right after a fresh save/reopen) —
        # same class of gotcha as never trusting UsedRange for last row.
        # A direct bounded scan is the only reliable way to find it.
        last_col_idx = 4  # never below D
        for c in range(5, 60):
            if cs.Cells(1, c).Value not in (None, ""):
                last_col_idx = c

        def col_letter(n):
            s = ""
            while n > 0:
                n, r = divmod(n - 1, 26)
                s = chr(65 + r) + s
            return s

        last_col = col_letter(last_col_idx)
        formula_cols = [col_letter(n) for n in range(ord('E') - 64, last_col_idx + 1) if col_letter(n) != 'M']
        filled = []
        for col in formula_cols:
            f = cs.Range(f"{col}2").Formula
            if f and str(f).startswith('='):
                autofill_col(cs, col, cs_new_last)
                filled.append(col)

        # Clear formula cols E-<last> beyond new last row (removes orphan formula rows)
        if cs_new_last < cs_old_last:
            cs.Range(f"E{cs_new_last+1}:{last_col}{cs_old_last}").ClearContents()

        print(f"  Formula cols autofilled: {', '.join(filled)}")
        if cs_new_last < cs_old_last:
            print(f"  Cleared orphan rows {cs_new_last+1}:{cs_old_last} (E-{last_col})")

        # Col M: dynamic ADP VLOOKUP — source driven by Setup!B2, scoring by Setup!B21
        # Setup!B2 dropdown values from Calculations!A19:A29 (NFL removed 2026):
        #   Sleeper, Underdog, ESPN, CBS, Yahoo, NFFC, NFFC Cutline,
        #   FFPC, Fantrax, RTSports, Other   (BB10s is NOT a selectable source)
        # ADP tab column layout (A=Player, B=Consensus, C=Pos, D=Team):
        #   E=Underdog  F=CBS  G=ESPN  H=FFPC  I=BB10s  J=Yahoo
        #   K=Sleeper(PPR)  L=Sleeper_STD  M=Sleeper_Half  N=Sleeper_2QB
        #   O=Fantrax  P=RTSports  Q=NFFC  R=NFFC Cutline
        def vlookup_branch(col_letter, col_index):
            # Fall back to worst-real-ADP+1 both when the player is missing
            # from the ADP tab AND when he's present but the source has no
            # ADP for him (stored as 999 — e.g. Sleeper lacking Evan Engram).
            col = f"ADP!$A:${col_letter}"
            lk = f'VLOOKUP(A2,{col},{col_index},FALSE)'
            max_expr = f'MAXIFS(ADP!${col_letter}:${col_letter},ADP!${col_letter}:${col_letter},"<999")+1'
            return f'IF(IFERROR({lk},999)>=999,{max_expr},{lk})'

        m_formula = (
            '=IFS('
            # 2QB/SF always wins — checked before ADP source
            f'Setup!$E$14+Setup!$E$21>1,{vlookup_branch("N",14)},'
            f'Setup!$B$2="Underdog",{vlookup_branch("E",5)},'
            f'Setup!$B$2="CBS",{vlookup_branch("F",6)},'
            f'Setup!$B$2="ESPN",{vlookup_branch("G",7)},'
            f'Setup!$B$2="FFPC",{vlookup_branch("H",8)},'
            f'Setup!$B$2="Yahoo",{vlookup_branch("J",10)},'
            # Sleeper: route by scoring format (2QB already handled above)
            f'AND(Setup!$B$2="Sleeper",Setup!$B$21>=0.75),{vlookup_branch("K",11)},'
            f'AND(Setup!$B$2="Sleeper",Setup!$B$21>=0.5),{vlookup_branch("M",13)},'
            f'Setup!$B$2="Sleeper",{vlookup_branch("L",12)},'
            f'Setup!$B$2="Fantrax",{vlookup_branch("O",15)},'
            f'Setup!$B$2="RTSports",{vlookup_branch("P",16)},'
            f'Setup!$B$2="NFFC",{vlookup_branch("Q",17)},'
            f'Setup!$B$2="NFFC Cutline",{vlookup_branch("R",18)},'
            # Other → Consensus col B (no per-source data)
            f'TRUE,{vlookup_branch("B",2)}'
            ')'
        )
        cs.Range(f"M2:M{cs_new_last}").Formula = m_formula
        if cs_new_last < cs_old_last:
            cs.Range(f"M{cs_new_last+1}:M{cs_old_last}").ClearContents()
        print(f"  M2:M{cs_new_last}: ADP VLOOKUP (missing/999 -> max+1)")

        # Col O: JB ranking — same B21 scoring threshold as ADP, no 2QB variant
        #   B21 >= 0.75 → PPR   (Joe Bond Ranks E:G col 3)
        #   B21 >= 0.5  → Half  (Joe Bond Ranks A:C col 3)
        #   default     → STD   (Joe Bond Ranks I:K col 3)
        o_formula = (
            "=IFS("
            "Setup!$B$21>=0.75,IFNA(VLOOKUP(A2,'Joe Bond Ranks'!E:G,3,FALSE),MAX('Joe Bond Ranks'!G:G)+1),"
            "Setup!$B$21>=0.5,IFNA(VLOOKUP(A2,'Joe Bond Ranks'!A:C,3,FALSE),MAX('Joe Bond Ranks'!C:C)+1),"
            "TRUE,IFNA(VLOOKUP(A2,'Joe Bond Ranks'!I:K,3,FALSE),MAX('Joe Bond Ranks'!K:K)+1)"
            ")"
        )
        cs.Range(f"O2:O{cs_new_last}").Formula = o_formula
        if cs_new_last < cs_old_last:
            cs.Range(f"O{cs_new_last+1}:O{cs_old_last}").ClearContents()
        print(f"  O2:O{cs_new_last}: JB ranking (PPR/Half/STD via B21 threshold)")

        # ── Joe Bond Rankings ─────────────────────────────────────────────────
        print("\nJoe Bond Rankings:")
        # Build normalised->canonical name map from the cheat sheet we just wrote
        cheat_names = {}
        for r in range(2, cs_new_last + 1):
            v = cs.Cells(r, 1).Value
            if v:
                cheat_names[normalise_name(v)] = v

        write_jb_ranks(wb, drive_svc, cheat_names)

        # ── Sort Cheat Sheet by col P (Overall Rank) ascending ────────────────
        # Recalculate first so col P has real values from the Setup tab defaults.
        print("\nSorting Cheat Sheet by Overall Rank (col P, low to high)...")
        wb.Application.Calculate()
        sort_range = cs.Range(f"A2:U{cs_new_last}")
        sort_range.Sort(
            Key1=cs.Range(f"P2:P{cs_new_last}"),
            Order1=1,           # xlAscending
            Header=2,           # xlNo — range starts at row 2, no header in range
            MatchCase=False,
            Orientation=1,      # xlSortRows
            SortMethod=1,       # xlPinYin (default)
            DataOption1=1,      # xlSortTextAsNumbers
        )
        # Spot-check: report top 5 after sort
        top5 = [(cs.Cells(r,1).Value, cs.Cells(r,4).Value,
                 cs.Cells(r,16).Value)   # col P = 16
                for r in range(2, 7)]
        print("  Top 5 after sort (Name, Pos, Rank):")
        for name, pos, rank in top5:
            print(f"    {str(name):<28} {str(pos):<4} rank={rank}")

        # ── Save (sheets intentionally left UNPROTECTED) ──────────────────────
        # Protection is applied by hand as the final step before distributing
        # to members, so the script never re-adds it.
        if protection_state:
            print(f"  NOTE: left {len(protection_state)} sheet(s) unprotected — "
                  f"re-protect before distributing")

        wb.Save()
        print("\nSaved.")

    except Exception as e:
        print(f"\nERROR: {e}")
        raise
    finally:
        wb.Close(SaveChanges=False)
        excel.Quit()

    print("Done.")


if __name__ == "__main__":
    main()
