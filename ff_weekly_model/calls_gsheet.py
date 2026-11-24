#!/usr/bin/env python3
"""The Review workbook as a GOOGLE SHEET (Joe 2026-11-24: "would it be safer to put the calls sheet on
google sheets so I can access it easier from my phone?" ... "yes go for it").

One sheet, overwritten each week (the bookmark never changes), owned by Joe and shared with the service
account. The Excel workbook stays the model's working copy; this module just moves it to and from the
sheet:

  pull(year, week)  start of every sync: the sheet -> "F6P Week N Review.xlsx" (Drive export), so
                    review_book.sync() reads Joe's phone edits exactly like Excel edits
  push(year, week)  end of every workbook build: the xlsx -> the sheet (Drive converts it in place:
                    same link, every tab, dropdowns and colours)

Safety:
  - a push is SKIPPED when the sheet changed after the run read it (Joe editing during a run); the
    workbook's build state goes back to what was synced, so his edits are read next run and the
    cloud's own changes (an inactive switched OUT) are not mistaken for him undoing them
  - the sheet holds ONE week; a push for a new week first exports the old week's final sheet to that
    week's workbook (kept in the private repo), so nothing is lost when it is overwritten

Config: data/calls_gsheet.json {"id": "<sheet id>", "from_week": 13, "year": 2026}. Credentials: the
service-account JSON at the FF_ADP root (laptop) or $GOOGLE_SERVICE_ACCOUNT_FILE (GitHub).
"""
import io
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
CONF = os.path.join(DATA, "calls_gsheet.json")
STATE = os.path.join(DATA, "calls_gsheet_state.json")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_svc = None


def config():
    return json.load(open(CONF)) if os.path.exists(CONF) else {}


def active(year, week):
    c = config()
    return bool(c.get("id")) and (year, week) >= (int(c.get("year", year)), int(c.get("from_week", 1)))


def _state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def _save_state(s):
    json.dump(s, open(STATE, "w"), indent=1)


def _drive():
    global _svc
    if _svc is None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") or os.path.join(
            ROOT, "triple-baton-456523-e4-b9ec3cbd6e3d.json")
        cred = service_account.Credentials.from_service_account_file(
            key, scopes=["https://www.googleapis.com/auth/drive"])
        _svc = build("drive", "v3", credentials=cred, cache_discovery=False)
    return _svc


def _modified(fid):
    return _drive().files().get(fileId=fid, fields="modifiedTime").execute()["modifiedTime"]


def _export(fid, dest):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, _drive().files().export_media(fileId=fid, mimeType=XLSX))
    done = False
    while not done:
        _, done = dl.next_chunk()
    tmp = dest + ".gs.tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf.getvalue())
    os.replace(tmp, dest)


def _calls(year, week, path):
    """fingerprint of the calls in a workbook file (player calls + team lines)."""
    import hashlib
    import review_book
    real = review_book.book_path
    review_book.book_path = lambda y, w: path
    try:
        e = review_book.read_edits(year, week) or {}
        t = review_book.read_team_edits(year, week) or {}
    finally:
        review_book.book_path = real
    blob = json.dumps([sorted((k, [str(v.get(x, "")) for x in review_book.EDIT_KEYS]) for k, v in e.items()),
                       sorted((k, sorted(v.items())) for k, v in t.items())], default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def pull(year, week):
    """The sheet -> this week's workbook, when the sheet holds this week. -> True if pulled.
    (Always a fresh export: Drive's modifiedTime lags edits made in Sheets by minutes.)"""
    if not active(year, week):
        return False
    import review_book
    fid, st = config()["id"], _state()
    if st.get("week") != [year, week]:
        return False                         # the sheet still shows an earlier week (nothing to read)
    try:
        dest = review_book.book_path(year, week)
        _export(fid, dest)
        st["read_calls"] = _calls(year, week, dest)
        _save_state(st)
        return True
    except Exception as e:
        print(f"  WARN  calls sheet          could not read the Google Sheet ({type(e).__name__}: "
              f"{str(e)[:150]}) -- using the last copy")
        return False


def after_sync(year, week):
    """the build state as synced -- what a skipped push goes back to."""
    if active(year, week):
        import review_book
        sp = review_book.state_path(year, week)
        if os.path.exists(sp):
            shutil.copy2(sp, sp + ".synced")


def push(year, week):
    """This week's rebuilt workbook -> the sheet. -> True if pushed."""
    if not active(year, week):
        return False
    import review_book
    from googleapiclient.http import MediaFileUpload
    fid, st = config()["id"], _state()
    try:
        if st.get("week") == [year, week]:
            now_ = review_book.book_path(year, week) + ".now.xlsx"
            _export(fid, now_)
            changed = _calls(year, week, now_) != st.get("read_calls")
            os.remove(now_)
            if changed:
                sp = review_book.state_path(year, week)
                if os.path.exists(sp + ".synced"):
                    shutil.copy2(sp + ".synced", sp)
                print("  !! calls sheet: edited on Google during this run -- NOT overwritten; "
                      "those edits are read on the next run")
                return False
        elif st.get("week"):
            oy, ow = st["week"]               # archive the old week's final sheet before overwriting
            _export(fid, review_book.book_path(oy, ow))
            print(f"  calls sheet: week {ow}'s final sheet saved to {os.path.basename(review_book.book_path(oy, ow))}")
        f = _drive().files().update(fileId=fid, media_body=MediaFileUpload(review_book.book_path(year, week),
                                                                           mimetype=XLSX),
                                    fields="modifiedTime").execute()
        # fingerprint what the SHEET now says (its export, not our xlsx: Sheets may store values
        # differently), so the next push compares like with like
        now_ = review_book.book_path(year, week) + ".now.xlsx"
        _export(fid, now_)
        st.update(week=[year, week], pushed=f["modifiedTime"], read_calls=_calls(year, week, now_))
        os.remove(now_)
        _save_state(st)
        print(f"  calls sheet: week {week} -> Google Sheet")
        return True
    except Exception as e:
        print(f"  WARN  calls sheet          could not update the Google Sheet ({type(e).__name__}: "
              f"{str(e)[:150]})")
        return False
