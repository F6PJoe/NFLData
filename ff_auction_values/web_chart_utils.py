#!/usr/bin/env python3
"""
Shared helpers for the two web-chart export scripts (export_web_chart_data.py,
export_web_chart_teaser.py).

## Why these exist

Both charts are meant to be pasted as a fragment into an existing WordPress
page, not opened as a standalone document (see CLAUDE.md, "Web value
chart"). The user's site edits that page via the Classic Editor's Text/Code
view, which -- unlike a Gutenberg Custom HTML block -- does NOT bypass
WordPress's wpautop() filter on the front end. wpautop auto-wraps
blank-line-separated content in <p> tags, and has a long-documented history
of doing this INSIDE <script>/<style> blocks too, corrupting the CSS/JS
syntax.

**Round 1 (strip_blank_lines only) was insufficient.** Confirmed with real
evidence, not just theory: a live test showed a `SyntaxError: Invalid or
unexpected token` in the console, and the actual page source had
`<p><script>` -- wpautop had wrapped a paragraph tag right at the script
boundary despite zero blank lines inside the chart files themselves. The
real cause: the *assembly* template (wordpress_page_outline.html) that
splices the chart into the surrounding page still had blank lines
immediately around the [s2If-*] shortcodes and markers -- outside the
chart files' own content, but still enough to trigger wpautop right at the
critical boundary.

**Round 2: collapse_script_style_blocks.** Rather than keep chasing
individual blank lines, this collapses the ENTIRE contents of every
<style>...</style> and <script>...</script> block down to a single line
each. If there's no line boundary left inside those tags, wpautop (or any
other line-based text processor) has nothing to act on except the tags'
own open/close boundaries -- structurally safer than hunting down every
place a blank line could sneak in. Confirmed safe for this codebase
specifically: no `//` line comments exist in either chart's CSS/JS
(checked directly, not assumed -- a `//` comment would silently swallow
everything after it once newlines are collapsed to spaces), so collapsing
whitespace runs to single spaces can't change what the code does.

**Round 3 (abandoned): base64_wrap_script.** Round 2 fixed the duplicated-
section symptom (confirmed by the user), but the chart's data still didn't
load. Working hypothesis at the time was `wptexturize` mangling straight
quotes inside the `<script>` block into "smart" quotes. Built a
base64-encoded payload plus a `document.currentScript`-based self-loader
to sidestep it entirely.

**This hypothesis was WRONG, disproven with real evidence.** The user
pointed at an existing, working script already live on their site (a
position-filter dropdown using plain jQuery, straight quotes, no special
encoding) -- proof `wptexturize` isn't touching `<script>` content on this
site at all. This matches WordPress core's actual, documented behavior:
`wptexturize()` explicitly skips the contents of `<pre>`, `<code>`,
`<style>`, and `<script>` tags (`$no_texturize_tags`) -- it was never going
to touch this in the first place. The base64/self-loader trick also
introduced a real, separate bug: `document.currentScript` only resolves
correctly during *synchronous* script execution. Any caching/performance
plugin that defers, asyncs, or moves inline scripts (WP Rocket,
Autoptimize, LiteSpeed Cache, etc. -- common, often on by default) makes it
return `null`, silently no-opping the whole loader with no console error --
plausibly the actual cause of the "still not loading" symptom, and a
self-inflicted fragility that plain script content never had. Removed
entirely; the chart's `<script>` tag is now the same
plain-jQuery-in-collapsed-single-line pattern as the user's own working
example, `type="text/javascript"` attribute included to match it exactly.
`base64_wrap_script()` is kept in this file only as a documented dead end,
not called by either export script.

**Round 4 (real root cause, found from the user's actual saved page
source, not a simulation): `force_balance_tags()`.** After Round 2's
collapse-to-one-line fix, the script still corrupted, but only in one
place: `render()`'s row-building code, which built table rows via string
concatenation of literal tag fragments like `'<td class="rank">'`.
WordPress's `force_balance_tags()` (run on save, a real tag-aware parser
with known special-case handling for table tags specifically) has no
concept of `<script>` boundaries -- it scans the whole saved content for
tag-shaped text and "balances" what it thinks are unclosed tags,
splicing in stray `<p>`/`</p>` right at each `'<td...>'` boundary,
regardless of the fact that it's JS string data inside a script, not
real markup. Confirmed by diffing the live saved page source line-by-
line: every other part of the script (including the ~120KB embedded
JSON, which has no tag-shaped substrings) survived perfectly; only the
handful of lines containing literal `<td>`/`<span>` fragments broke.
Fixed at the source, not by further escaping: `render()` now builds rows
via `document.createElement`/`.textContent`/`.className` instead of
`innerHTML` string concatenation, so there is no tag-shaped text
anywhere in the script for any HTML parser to misinterpret. This is the
actual, permanent fix -- collapsing whitespace (Round 2) was necessary
but not sufficient, since `force_balance_tags` triggers on tag-shaped
content, not on line breaks.
"""

import base64
import re

_BLOCK_RE = re.compile(r"(<style[^>]*>|<script[^>]*>)(.*?)(</style>|</script>)", re.DOTALL)
_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL)


def strip_blank_lines(html: str) -> str:
    return "\n".join(line for line in html.splitlines() if line.strip())


def collapse_script_style_blocks(html: str) -> str:
    def _collapse(match):
        open_tag, content, close_tag = match.groups()
        return open_tag + re.sub(r"\s+", " ", content).strip() + close_tag

    return _BLOCK_RE.sub(_collapse, html)


def base64_wrap_script(html: str) -> str:
    """Replace <script>...</script> with a base64-encoded payload plus a
    minimal loader, so no WordPress content filter has readable JS/quote
    characters to mangle. Uses document.currentScript.tagName instead of a
    literal "script" string to avoid one more unnecessary quoted string."""
    def _wrap(match):
        content = match.group(1)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        loader = (
            "<script>(function(){"
            "var b=document.currentScript;"
            "var s=document.createElement(b.tagName);"
            "s.textContent=atob('" + encoded + "');"
            "b.parentNode.insertBefore(s,b.nextSibling);"
            "})();</script>"
        )
        return loader

    return _SCRIPT_RE.sub(_wrap, html)
