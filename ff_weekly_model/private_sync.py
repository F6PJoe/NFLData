#!/usr/bin/env python3
"""Keep the laptop and the private repo (F6PJoe/NFLData-private) in step (2026-11-24).

GitHub runs the locks when the laptop is off (cloud_run.py); the laptop is where Joe makes calls.
    python private_sync.py pull   # before working: take what the cloud runs wrote
    python private_sync.py push   # after working: send the calls / workbook / outputs up
rerun.py does both on its own (pull first, push at the end), so "Rerun projections.bat" is all Joe
runs. The local clone lives OUTSIDE OneDrive (%USERPROFILE%\\NFLData-private) -- git inside OneDrive
fights with OneDrive's sync.

Conflicts: a file changed on BOTH sides since the last sync keeps the LAPTOP copy (Joe's newer
edit), and the next push sends it up; it is listed so nothing is lost silently.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cloud_run as C  # noqa: E402

CLONE = os.path.join(os.path.expanduser("~"), "NFLData-private")
REPO = "F6PJoe/NFLData-private"
MANIFEST = os.path.join(CLONE, ".laptop_sync.json")
FORCE_CLOUD = True   # see pull()


def _h(p):
    if not os.path.exists(p):
        return None
    with open(p, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def _git(*a, check=True):
    r = subprocess.run(["git", "-C", CLONE, *a], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()[-400:]}")
    return r


def _ensure_clone():
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        r = subprocess.run(["gh", "repo", "clone", REPO, CLONE], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"clone failed: {r.stderr.strip()[-400:]}")


def _manifest():
    return json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}


def pull(quiet=False):
    _ensure_clone()
    _git("pull", "-q", "--rebase", "--autostash")
    st = os.path.join(CLONE, "state")
    man = _manifest()
    took, kept = [], []
    rels = C.state_files(st) if os.path.isdir(st) else []
    # a Review workbook and its build-state file (data/review_book_<yr>_wk<NN>.json) travel as a PAIR:
    # if Joe's edited workbook is kept, the cloud's newer build state must not be taken, or the
    # next sync reads every cell the cloud changed (an inactive switched OUT) as Joe undoing it
    held = set()
    for rel in ([] if FORCE_CLOUD else rels):
        if rel.endswith(" Review.xlsx"):
            src, dst = os.path.join(st, rel), os.path.join(C.ROOT, rel)
            hl, hm = _h(dst), man.get(rel)
            if hl is not None and hl != hm and hl != _h(src):
                wk = int(rel.split("Week ")[1].split()[0])
                held.update(r for r in rels if r.endswith(f"_wk{wk:02d}.json") and "review_book_" in r)
    for rel in rels:
        if rel in held:
            kept.append(rel)
            continue
        src, dst = os.path.join(st, rel), os.path.join(C.ROOT, rel)
        hp, hl, hm = _h(src), _h(dst), man.get(rel)
        if hp == hl:
            man[rel] = hp
            continue
        # 2026-11-26: calls live on the Google Sheet now, so the laptop holds no edits the cloud lacks --
        # the cloud's newer copy wins even when both changed (a laptop rerun pushes its own work at the end)
        if True:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, "rb") as a, open(dst, "wb") as b:
                b.write(a.read())
            man[rel] = hp
            took.append(rel)
        elif hp != hm:                       # both changed
            kept.append(rel)
    # ETR uploaded to the private repo -> the week folder
    ed = os.path.join(CLONE, "etr")
    if os.path.isdir(ed):
        for f in os.listdir(ed):
            if f.endswith(".csv"):
                dst = os.path.join(C.ROOT, "ff_weekly_proj", "weekly", f[:-4], "etr.csv")
                if _h(dst) != _h(os.path.join(ed, f)):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with open(os.path.join(ed, f), "rb") as a, open(dst, "wb") as b:
                        b.write(a.read())
                    took.append(f"etr/{f}")
    json.dump(man, open(MANIFEST, "w"), indent=0, sort_keys=True)
    if not quiet or took or kept:
        print(f"  private repo: pulled {len(took)} file(s) from the cloud runs"
              + (": " + ", ".join(os.path.basename(t) for t in took[:8]) + (" ..." if len(took) > 8 else "")
                 if took else ""))
    for rel in kept:
        print(f"  !! {rel}: changed here AND in the cloud -- kept YOUR copy (it goes up on the next push)")
    return True


def push(msg="laptop: calls / workbook / outputs"):
    _ensure_clone()
    st = os.path.join(CLONE, "state")
    n = C.copy_tree(C.ROOT, st, C.state_files(C.ROOT))
    man = _manifest()
    for rel in C.state_files(C.ROOT):
        man[rel] = _h(os.path.join(C.ROOT, rel))
    json.dump(man, open(MANIFEST, "w"), indent=0, sort_keys=True)
    _git("add", "-A", "state")
    if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("  private repo: nothing new to push")
        return True
    _git("commit", "-q", "-m", msg)
    for _ in range(3):
        if _git("push", "-q", check=False).returncode == 0:
            print(f"  private repo: pushed {n} changed file(s)")
            return True
        _git("pull", "-q", "--rebase", check=False)
    print("  !! private repo: push failed -- run `python private_sync.py push` again")
    return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        pull()
    elif cmd == "push":
        push(" ".join(sys.argv[2:]) or "laptop: calls / workbook / outputs")
    else:
        sys.exit(__doc__)
