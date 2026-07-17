#!/usr/bin/env python3
"""
Push the freshly-built value_chart.html / value_chart_teaser.html into a
WordPress POST (not a page -- the auction values live on a post, confirmed
by the user) via the REST API, replacing ONLY the marker-delimited
sections that hold this chart -- everything else on the post (other text,
embeds, blocks) is left untouched. Designed to run unattended (see
.github/workflows/fetch_draft_projections.yml), so it fails loudly rather
than guessing: if the expected markers aren't found on the post, or a
request fails, it raises and does NOT attempt a partial/best-effort write.

## One-time WordPress post setup

The site's actual member-gating shortcodes are [s2If-paywall] (members)
and [s2If-ads] (everyone else) -- not the generic current_user_can(...)
form assumed in an earlier draft of this script. This script doesn't care
which shortcode syntax wraps the markers (it only searches for its own
HTML comments below), but the post itself needs to look like this once,
by hand, before automation takes over:

    [s2If-paywall]
    <!-- AUCTION_CHART_MEMBER:START -->
    ...(paste value_chart.html contents here once, to start)...
    <!-- AUCTION_CHART_MEMBER:END -->
    [/s2If-paywall]

    [s2If-ads]
    <!-- AUCTION_CHART_TEASER:START -->
    ...(paste value_chart_teaser.html contents here once, to start)...
    <!-- AUCTION_CHART_TEASER:END -->
    [/s2If-ads]

After that one-time setup, this script finds those exact HTML comments and
replaces only what's between them on every run -- the markers themselves,
the [s2If-*] shortcodes, and everything else on the post (the intro copy,
accuracy blurb, ad slot, related-rankings links, etc.) stay exactly as
they are.

## Required environment variables

    WP_URL           e.g. https://yoursite.com  (no trailing slash)
    WP_POST_ID        the numeric post ID (visible in the post-edit URL)
    WP_USERNAME       the WordPress username tied to the Application Password
                       (a dedicated Editor-role account, not the site admin
                       or the post's own author -- Editor has edit_others_posts,
                       so it can update this post regardless of who authored it)
    WP_APP_PASSWORD   a WordPress Application Password (Users -> Profile ->
                       Application Passwords) -- NOT your login password

Usage:
    python push_to_wordpress.py
"""

import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent

SECTIONS = [
    ("AUCTION_CHART_MEMBER", HERE / "value_chart.html"),
    ("AUCTION_CHART_TEASER", HERE / "value_chart_teaser.html"),
]


def replace_section(content, name, new_inner):
    start_marker = f"<!-- {name}:START -->"
    end_marker = f"<!-- {name}:END -->"
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    if not pattern.search(content):
        raise RuntimeError(
            f"Marker pair {start_marker} / {end_marker} not found on the page -- "
            f"refusing to guess. Add the markers once by hand (see this script's "
            f"module docstring), then re-run."
        )
    replacement = f"{start_marker}\n{new_inner}\n{end_marker}"
    # Replacement passed as a function (not a bare string) specifically so
    # re.sub does NOT interpret backslash sequences in `replacement` as
    # backreferences (\1, \g<name>, etc.) -- the minified JSON payload
    # embedded in new_inner can contain literal backslashes.
    return pattern.sub(lambda m: replacement, content, count=1)


def main():
    wp_url = os.environ["WP_URL"].rstrip("/")
    post_id = os.environ["WP_POST_ID"]
    username = os.environ["WP_USERNAME"]
    app_password = os.environ["WP_APP_PASSWORD"]

    api = f"{wp_url}/wp-json/wp/v2/posts/{post_id}"
    auth = (username, app_password)

    print(f"Fetching current content for post {post_id}...")
    resp = requests.get(api, params={"context": "edit"}, auth=auth, timeout=30)
    if not resp.ok:
        print(f"GET failed: {resp.status_code} {resp.reason}", file=sys.stderr)
        print(f"Response headers: {dict(resp.headers)}", file=sys.stderr)
        print(f"Response body (first 2000 chars): {resp.text[:2000]}", file=sys.stderr)
    resp.raise_for_status()
    post = resp.json()
    content = post["content"]["raw"]

    for name, path in SECTIONS:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found -- run export_web_chart_data.py / "
                                     f"export_web_chart_teaser.py first")
        new_inner = path.read_text(encoding="utf-8")
        content = replace_section(content, name, new_inner)
        print(f"  Replaced {name} section ({len(new_inner) / 1024:.0f} KB)")

    print("Pushing updated content back to WordPress...")
    resp = requests.post(api, auth=auth, json={"content": content}, timeout=30)
    if not resp.ok:
        print(f"POST failed: {resp.status_code} {resp.reason}", file=sys.stderr)
        print(f"Response headers: {dict(resp.headers)}", file=sys.stderr)
        print(f"Response body (first 2000 chars): {resp.text[:2000]}", file=sys.stderr)
    resp.raise_for_status()
    print(f"Done. Post {post_id} updated ({resp.json().get('modified', 'unknown time')}).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
