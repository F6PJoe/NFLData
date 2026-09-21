"""
Find players whose names don't match across tabs.
Signals:
  - In Cheat Sheet but not found in ADP tab (M = max+1)
  - In Cheat Sheet but not found in Joe Bond Ranks (O = max+1)
  - In ADP tab but not in any Projection tab
  - In Joe Bond Ranks but not in Cheat Sheet

For each, show projected score + position so it's easy to judge if it's a real mismatch
vs. a low-value player genuinely not ranked/ADP'd.
"""

import csv
import re
import unicodedata
from pathlib import Path

import win32com.client as win32

BASE = Path(__file__).resolve().parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162


def norm(name):
    if not name:
        return ""
    name = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"['.,-]", "", name.lower())
    name = name.replace("-", " ")
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", name.strip())
    return re.sub(r"\s+", " ", name).strip()


excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
wb = excel.Workbooks.Open(WORKBOOK)

# ── Cheat Sheet: name, pos, score (G), ADP (M), JB rank (O) ──────────────────
cs = wb.Sheets("Cheat Sheet")
cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
cs_data = cs.Range(f"A2:O{cs_last}").Value

cs_players = []
for row in cs_data:
    name = row[0]
    if not name:
        continue
    pos   = row[3]   # col D
    score = row[6]   # col G
    adp   = row[12]  # col M
    jbr   = row[14]  # col O
    cs_players.append((str(name), str(pos or ""), float(score or 0),
                       float(adp or 9999), float(jbr or 9999)))

# Max ADP and max JB rank (the +1 baseline)
max_adp = max(p[3] for p in cs_players if p[3] < 9000)
max_jbr = max(p[4] for p in cs_players if p[4] < 9000)
print(f"Max ADP in sheet: {max_adp:.1f}  |  Max JB rank in sheet: {max_jbr:.0f}\n")

# ── ADP tab names ─────────────────────────────────────────────────────────────
adp_sh = wb.Sheets("ADP")
adp_last = adp_sh.Cells(adp_sh.Rows.Count, 1).End(xlUp).Row
adp_names = {norm(adp_sh.Cells(r, 1).Value) for r in range(2, adp_last + 1)
             if adp_sh.Cells(r, 1).Value}

# ── Joe Bond Ranks names (half-PPR col A) ────────────────────────────────────
jb = wb.Sheets("Joe Bond Ranks")
jb_last = jb.Cells(jb.Rows.Count, 1).End(xlUp).Row
jb_names = {norm(jb.Cells(r, 1).Value) for r in range(2, jb_last + 1)
            if jb.Cells(r, 1).Value}

wb.Close(False)
excel.Quit()

# ── Cheat Sheet players not found in ADP ─────────────────────────────────────
print("=" * 70)
print("CHEAT SHEET PLAYERS WITH NO ADP MATCH (showing top 40 by score)")
print("  (M value equals max+1 — likely a name spelling difference)")
print("=" * 70)
no_adp = [(n, pos, sc, adp) for n, pos, sc, adp, _ in cs_players
          if adp >= max_adp - 0.5 and norm(n) not in adp_names]
no_adp.sort(key=lambda x: -x[2])
for name, pos, score, adp in no_adp[:40]:
    print(f"  {pos:<3} {name:<30} score={score:6.1f}  M={adp:.1f}")

# ── Cheat Sheet players not found in Joe Bond Ranks ──────────────────────────
print()
print("=" * 70)
print("CHEAT SHEET PLAYERS WITH NO JB RANK MATCH (showing top 40 by score)")
print("  (O value equals max+1 — likely a name spelling difference)")
print("=" * 70)
no_jb = [(n, pos, sc, jbr) for n, pos, sc, _, jbr in cs_players
         if jbr >= max_jbr - 0.5 and norm(n) not in jb_names]
no_jb.sort(key=lambda x: -x[2])
for name, pos, score, jbr in no_jb[:40]:
    print(f"  {pos:<3} {name:<30} score={score:6.1f}  JB={jbr:.0f}")

# ── ADP tab players not in Cheat Sheet ───────────────────────────────────────
cs_norm = {norm(n) for n, *_ in cs_players}
adp_only = [n for n in adp_names if n not in cs_norm]
print()
print("=" * 70)
print(f"ADP TAB PLAYERS NOT IN CHEAT SHEET ({len(adp_only)} players)")
print("  (may be K/DST/irrelevant positions or spelling mismatches)")
print("=" * 70)
for n in sorted(adp_only):
    print(f"  {n}")

# ── Joe Bond Rank players not in Cheat Sheet ─────────────────────────────────
jb_only = [n for n in jb_names if n not in cs_norm]
print()
print("=" * 70)
print(f"JB RANKS PLAYERS NOT IN CHEAT SHEET ({len(jb_only)} players)")
print("=" * 70)
for n in sorted(jb_only):
    print(f"  {n}")
