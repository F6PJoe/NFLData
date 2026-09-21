#!/usr/bin/env python3
"""
Push the generated usage-table embeds into their WordPress posts, replacing
only the marker-delimited block on each. Everything else on the post (intro
copy, ads, related links, the [s2If-*] shortcodes themselves) is untouched.

Two posts, one component:
    embed_weekly.html  ->  WP_POST_ID_WEEKLY   (weekly usage)
    embed_season.html  ->  WP_POST_ID_SEASON   (season-long usage)

## One-time setup, already done by hand on each post

    [s2If-paywall]
    <!-- F6P_USAGE:START -->
    <!-- F6P_USAGE:END -->
    [/s2If-paywall]

Put those inside a **Custom HTML block**, not a Paragraph block -- WordPress
runs wpautop on ordinary content and injects <p>/<br> into the <style> and
<script>. From then on this script fills the gap between the markers; the
markers, the shortcodes and the rest of the post stay exactly as they are.

Note the embed files contain their own copy of the markers (they're also meant
to be pasteable by hand). Only the content BETWEEN them is pushed, so the post
never ends up with nested markers.

## This runs rarely, not weekly

Only the uploaded JSON changes on the twice-weekly refresh. The post content
changes only when component.html changes.

## Required environment variables

    WP_URL              e.g. https://fantasysixpack.net  (no trailing slash)
    WP_USERNAME         the Editor-role account tied to the Application Password
    WP_APP_PASSWORD     a WordPress Application Password, NOT a login password
    WP_POST_ID_WEEKLY   numeric post ID of the weekly usage post
    WP_POST_ID_SEASON   numeric post ID of the season-long usage post

Usage:
    python push_to_wordpress.py --dry-run
    python push_to_wordpress.py
    python push_to_wordpress.py --only weekly
"""

import argparse
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent

START = "<!-- F6P_USAGE:START -->"
END = "<!-- F6P_USAGE:END -->"

TARGETS = {
    "weekly": ("embed_weekly.html", "WP_POST_ID_WEEKLY"),
    "season": ("embed_season.html", "WP_POST_ID_SEASON"),
}

# The site's Cloudflare WAF blocks the default "python-requests/x.y.z" UA
# outright, and SiteGround's host-level anti-bot layer needed a /wp-json/*
# exemption on top of that. See ff_auction_values/CLAUDE.md rounds 9-10.
HEADERS = {"User-Agent": "FantasySixPack-UsageTables/1.0 (+https://fantasysixpack.net)"}


def load_env():
    """Read ff_utilization/.env if present, same convention as the other
    projects here. Real environment variables always win, so GitHub Actions
    secrets are unaffected."""
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def diagnose_and_parse_json(resp, label):
    """resp.raise_for_status() alone misses the failure this pipeline actually
    hit: a 200 OK carrying an empty or non-JSON body, because something in
    front of WordPress (Cloudflare, SiteGround's CAPTCHA) answered instead.
    Always dump status/headers/body when the status isn't 2xx OR the body
    isn't JSON, so the next failure leaves real evidence."""
    problem = None
    if not resp.ok:
        problem = f"{label} failed: {resp.status_code} {resp.reason}"
    try:
        data = resp.json()
    except ValueError as exc:
        problem = problem or (f"{label} returned {resp.status_code} but the body "
                              f"isn't valid JSON: {exc}")
        data = None
    if problem:
        print(problem, file=sys.stderr)
        print(f"Response headers: {dict(resp.headers)}", file=sys.stderr)
        print(f"Body (first 2000 chars): {resp.text[:2000]}", file=sys.stderr)
        resp.raise_for_status()
        raise ValueError(problem)
    return data


def inner_block(path):
    """The component only -- the embed file's own markers and banner stripped,
    so pushing can't nest a second pair of markers inside the post's pair."""
    text = path.read_text(encoding="utf-8")
    try:
        start = text.index(START) + len(START)
        end = text.index(END)
    except ValueError:
        raise RuntimeError(f"{path.name} has no {START} / {END} pair -- "
                           f"regenerate it with build_embed.py")
    block = text[start:end].strip("\n")
    if START in block or END in block:
        raise RuntimeError(f"{path.name}: nested markers inside the block")
    return block


def replace_block(content, new_inner, post_id):
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(content):
        raise RuntimeError(
            f"Post {post_id} has no {START} / {END} pair -- refusing to guess "
            f"where the table goes. Add the markers once by hand inside a "
            f"Custom HTML block (see this script's docstring), then re-run."
        )
    replacement = f"{START}\n{new_inner}\n{END}"
    # Pass the replacement as a function, NOT a bare string: re.sub would
    # otherwise read backslash sequences in the CSS/JS (content:"\25BC", "\n")
    # as backreferences and mangle them.
    return pattern.sub(lambda _m: replacement, content, count=1)


def push(session, wp_url, post_id, path, dry_run):
    api = f"{wp_url}/wp-json/wp/v2/posts/{post_id}"
    block = inner_block(path)

    print(f"\n{path.name} -> post {post_id}")
    resp = session.get(api, params={"context": "edit"}, timeout=30)
    post = diagnose_and_parse_json(resp, "GET")
    content = post["content"]["raw"]

    updated = replace_block(content, block, post_id)
    if updated == content:
        print("  already up to date -- nothing to push")
        return

    print(f"  block: {len(block)/1024:.1f} KB   post: "
          f"{len(content)/1024:.1f} -> {len(updated)/1024:.1f} KB")
    if dry_run:
        print("  DRY RUN -- not writing")
        return

    resp = session.post(api, json={"content": updated}, timeout=30)
    result = diagnose_and_parse_json(resp, "POST")
    print(f"  updated ({result.get('modified', 'unknown time')})")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and diff, but don't write")
    ap.add_argument("--only", choices=sorted(TARGETS),
                    help="push just one of the two posts")
    args = ap.parse_args()

    load_env()
    try:
        wp_url = os.environ["WP_URL"].rstrip("/")
        auth = (os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])
    except KeyError as exc:
        sys.exit(f"Missing {exc.args[0]} -- put it in {HERE / '.env'} "
                 f"(see .env.example) or export it.")

    session = requests.Session()
    session.headers.update(HEADERS)
    session.auth = auth

    wanted = [args.only] if args.only else sorted(TARGETS)
    for key in wanted:
        filename, env_var = TARGETS[key]
        post_id = os.environ.get(env_var)
        if not post_id:
            sys.exit(f"Missing {env_var} (needed for the {key} post).")
        path = HERE / filename
        if not path.exists():
            sys.exit(f"{filename} not found -- run build_embed.py first.")
        push(session, wp_url, post_id, path, args.dry_run)

    print("\nDone." if not args.dry_run else "\nDry run complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
