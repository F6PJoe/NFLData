"""Player-name normalization for joining across sources.

nflverse's depth charts (ESPN-sourced) and rosters (NFL-sourced) don't always
agree on `gsis_id` — some rows carry a blank id on one side or the other — so
a name+team fallback is needed on top of the id join. Same suffix/punctuation
handling as ff_draft_proj uses.
"""

import re
import unicodedata

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize(name):
    """Lowercase, strip accents, punctuation, and generational suffixes.

    "Marvin Harrison Jr." -> "marvin harrison"
    "Ka'ena De Cambra"    -> "kaena de cambra"
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&nbsp;", " ")
    text = re.sub(r"[.'’`]", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    parts = [p for p in text.split() if p]
    while len(parts) > 1 and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def key(name, team):
    """Join key scoped to a team, so same-named players don't collide."""
    return f"{normalize(name)}|{team}"
