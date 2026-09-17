#!/usr/bin/env python3
"""
Upload every season's points-against JSON to the live site over SFTP,
replacing the manual drag-and-drop upload. Same account/pattern as
ff_utilization/sftp_upload.py -- see that file's docstring for the one-time
SiteGround SFTP setup (finding the host/port, converting a PuTTY .ppk key,
etc.) if `.env` isn't already filled in.

This is upload-only. It does not run the fetch step -- run
fetch_nflverse_points_against.py first, check the numbers, THEN upload.

Every `data/points_against_<year>.json` found locally is uploaded to
`wp-content/uploads/f6p-data/points_against_<year>.json` -- the same fixed
path component.html's season dropdown fetches from. Adding a new season is
just running the fetch script for that year and re-running this.

Usage:
    python sftp_upload.py --dry-run
    python sftp_upload.py
    python sftp_upload.py --only 2026
"""

import argparse
import os
import re
import sys
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REMOTE_DIR = "wp-content/uploads/f6p-data"


def load_env():
    """Read ff_points_against/.env if present, same convention as
    ff_utilization/sftp_upload.py. Real environment variables always win."""
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
    same reasoning as ff_utilization/sftp_upload.py."""
    errors = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(key_path, password=passphrase)
        except paramiko.SSHException as exc:
            errors.append(f"{cls.__name__}: {exc}")
    detail = "\n  ".join(errors)
    sys.exit(
        f"Could not load {key_path} as any known key type:\n  {detail}\n\n"
        f"If this is a PuTTY .ppk file, convert it in PuTTYgen first "
        f"(Conversions -> Export OpenSSH key) and point SFTP_KEY_PATH at "
        f"that exported copy instead.")


def connect():
    host = os.environ.get("SFTP_HOST")
    username = os.environ.get("SFTP_USERNAME")
    if not host or not username:
        sys.exit("Missing SFTP_HOST or SFTP_USERNAME -- copy .env.example to "
                  ".env and fill in your SiteGround SFTP details (or copy "
                  "ff_utilization/.env, same account).")
    port = int(os.environ.get("SFTP_PORT", "22"))
    key_path = os.environ.get("SFTP_KEY_PATH")
    password = os.environ.get("SFTP_PASSWORD")
    key_passphrase = os.environ.get("SFTP_KEY_PASSPHRASE") or None

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


def discover_files():
    """-> {year: (local_path, remote_rel_path)} for every points_against_
    <year>.json actually on disk."""
    out = {}
    for path in sorted(DATA.glob("points_against_*.json")):
        m = re.match(r"points_against_(\d{4})\.json$", path.name)
        if not m:
            continue
        out[m.group(1)] = (path, f"{REMOTE_DIR}/{path.name}")
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                     help="connect and check paths, but upload nothing")
    ap.add_argument("--only", help="upload just one season, e.g. 2026")
    args = ap.parse_args()

    load_env()
    root = os.environ.get("SFTP_REMOTE_ROOT")
    if not root:
        sys.exit("Missing SFTP_REMOTE_ROOT -- the path to the WordPress "
                  "install as seen over SFTP (e.g. 'public_html'). See "
                  "ff_utilization/sftp_upload.py's docstring for how to "
                  "find it -- same account, same value.")

    files = discover_files()
    if not files:
        sys.exit(f"No data/points_against_<year>.json files found in "
                  f"{DATA} -- run fetch_nflverse_points_against.py first.")

    if args.only:
        if args.only not in files:
            sys.exit(f"No local file for season {args.only} -- found: "
                      f"{', '.join(sorted(files))}")
        wanted = [args.only]
    else:
        wanted = sorted(files)

    client = connect()
    try:
        sftp = client.open_sftp()
        for year in wanted:
            local, rel = files[year]
            remote = remote_join(root, rel)
            local_size = local.stat().st_size

            try:
                existing = sftp.stat(remote)
                existing_desc = f"{existing.st_size/1024:.1f} KB currently there"
            except FileNotFoundError:
                existing_desc = "does not exist yet on the server"

            print(f"{year}  {local.name} ({local_size/1024:.1f} KB) -> "
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
