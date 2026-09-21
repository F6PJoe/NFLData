#!/usr/bin/env python3
"""
Upload the 3 weekly data files to the live site over SFTP, replacing the
manual drag-and-drop into an SFTP client.

    data/utilization_weekly.json         -> s2member-files gateway (members)
    data/utilization_teaser_weekly.json  -> plain public path (weekly teaser)
    data/utilization_teaser_season.json  -> plain public path (season teaser)

This is upload-only. It does not run the fetch/build steps -- run those first
(see "THE WEEKLY PIPELINE" in CLAUDE.md), check the numbers look right, THEN
upload. Keeping that as a separate manual step on purpose: a bad week's data
(a broken source, a half-finished slate) should be something you notice before
it goes out, not something a cron job pushes live unattended.

## One-time setup

1. In SiteGround Site Tools: Site -> SFTP Accounts (or Devs -> SSH Keys
   Manager if you want key-based auth instead of a password). Note the
   hostname, port, and username -- SiteGround SFTP is usually port 18765 or
   22, NOT always 22, and the username is account-specific, not "root" or
   your cPanel login.
2. Copy `.env.example` to `.env` in this folder (gitignored -- never commit
   it) and fill in the SFTP_* values. Use EITHER SFTP_PASSWORD OR
   SFTP_KEY_PATH, not both; if both are set, the key wins.
3. SFTP_REMOTE_ROOT is the path to the WordPress install AS SEEN OVER SFTP --
   often "public_html" or "www/<domain>/public_html", not "/" and not a URL.
   Find it by connecting once with any SFTP client (FileZilla, WinSCP) and
   noting the folder that contains "wp-content".
4. Run `python sftp_upload.py --dry-run` first -- it connects, confirms the
   three remote paths exist (or tells you they don't, rather than silently
   creating a typo'd folder), and uploads nothing.

Usage:
    python sftp_upload.py --dry-run
    python sftp_upload.py
    python sftp_upload.py --only teaser_weekly
"""

import argparse
import os
import stat
import sys
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# local file -> path relative to SFTP_REMOTE_ROOT. Same three paths
# build_teaser.py / fetch_fantasylife_utilization.py already print as the
# upload target -- kept in sync with those by hand, not derived, since they
# live in different scripts.
FILES = {
    "weekly": (
        DATA / "utilization_weekly.json",
        "wp-content/plugins/s2member-files/utilization_weekly.json",
    ),
    "teaser_weekly": (
        DATA / "utilization_teaser_weekly.json",
        "wp-content/uploads/f6p-data/utilization_teaser_weekly.json",
    ),
    "teaser_season": (
        DATA / "utilization_teaser_season.json",
        "wp-content/uploads/f6p-data/utilization_teaser_season.json",
    ),
}


def load_env():
    """Read ff_utilization/.env if present, same convention as
    push_to_wordpress.py. Real environment variables always win."""
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def load_private_key(key_path, passphrase):
    """Try every key type paramiko supports rather than assuming RSA --
    SiteGround's SSH Keys Manager can hand out RSA or Ed25519, and guessing
    wrong used to fail with a confusing parse error instead of just trying
    the next type. Also: a FileZilla "Key file" is very often a PuTTY .ppk,
    which none of these can read directly -- see the docstring's note on
    converting it with PuTTYgen first."""
    errors = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(key_path, password=passphrase)
        except paramiko.SSHException as exc:
            errors.append(f"{cls.__name__}: {exc}")
    detail = "\n  ".join(errors)
    sys.exit(
        f"Could not load {key_path} as any known key type:\n  {detail}\n\n"
        f"If this is a PuTTY .ppk file (common when FileZilla shows 'Key "
        f"file' as the logon type), paramiko can't read it directly -- open "
        f"it in PuTTYgen and use Conversions -> Export OpenSSH key to save a "
        f"copy in the format this script needs, then point SFTP_KEY_PATH at "
        f"that exported copy instead.")


def connect():
    host = os.environ.get("SFTP_HOST")
    username = os.environ.get("SFTP_USERNAME")
    if not host or not username:
        sys.exit("Missing SFTP_HOST or SFTP_USERNAME -- copy .env.example to "
                  ".env and fill in your SiteGround SFTP details first.")
    port = int(os.environ.get("SFTP_PORT", "22"))
    key_path = os.environ.get("SFTP_KEY_PATH")
    password = os.environ.get("SFTP_PASSWORD")
    key_passphrase = os.environ.get("SFTP_KEY_PASSPHRASE") or None

    # AutoAddPolicy trusts an unknown host key on first connect rather than
    # verifying against a pinned fingerprint -- a reasonable tradeoff for a
    # single personal host reached over a stable hostname, not something to
    # copy into anything more sensitive.
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if key_path:
        pkey = load_private_key(key_path, key_passphrase)
        client.connect(host, port=port, username=username, pkey=pkey, timeout=30)
    elif password:
        client.connect(host, port=port, username=username, password=password, timeout=30)
    else:
        sys.exit("Set either SFTP_PASSWORD or SFTP_KEY_PATH in .env.")

    return client


def remote_join(root, rel):
    return root.rstrip("/") + "/" + rel


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="connect and check paths, but upload nothing")
    ap.add_argument("--only", choices=sorted(FILES),
                    help="upload just one of the three files")
    args = ap.parse_args()

    load_env()
    root = os.environ.get("SFTP_REMOTE_ROOT")
    if not root:
        sys.exit("Missing SFTP_REMOTE_ROOT -- the path to the WordPress "
                  "install as seen over SFTP (e.g. 'public_html'). See the "
                  "docstring in this file for how to find it.")

    wanted = [args.only] if args.only else sorted(FILES)
    for key in wanted:
        local, _ = FILES[key]
        if not local.exists():
            sys.exit(f"{local} not found -- run the weekly build steps first "
                      f"(see CLAUDE.md 'THE WEEKLY PIPELINE').")

    client = connect()
    try:
        sftp = client.open_sftp()
        for key in wanted:
            local, rel = FILES[key]
            remote = remote_join(root, rel)
            local_size = local.stat().st_size

            try:
                existing = sftp.stat(remote)
                existing_desc = f"{existing.st_size/1024:.1f} KB currently there"
            except FileNotFoundError:
                existing_desc = "does not exist yet on the server"

            print(f"{key:<16} {local.name} ({local_size/1024:.1f} KB) -> "
                  f"{remote}  [{existing_desc}]")

            if args.dry_run:
                continue

            sftp.put(str(local), remote)
            uploaded = sftp.stat(remote)
            if uploaded.st_size != local_size:
                sys.exit(f"  UPLOAD MISMATCH: local {local_size} bytes, "
                         f"remote now {uploaded.st_size} bytes -- re-run.")
            print(f"  uploaded ({uploaded.st_size/1024:.1f} KB, verified)")
    finally:
        client.close()

    print("\nDry run complete -- nothing uploaded." if args.dry_run else "\nDone.")


if __name__ == "__main__":
    try:
        main()
    except paramiko.AuthenticationException:
        sys.exit("FAILED: SFTP authentication rejected -- check SFTP_USERNAME/"
                 "SFTP_PASSWORD (or SFTP_KEY_PATH) in .env.")
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
