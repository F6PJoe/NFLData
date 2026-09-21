"""
Small shared sidecar so each fetch_*.py can record the precise last-updated
timestamp it found for its source, and build_consensus.py can put that
timestamp in the column header (e.g. "Ratcliffe (6/27/2026 9:48:13)").

Stored in source_timestamps.json (gitignore-friendly to regenerate, not
meant to be hand-edited).
"""

import json
import os

PATH = os.path.join(os.path.dirname(__file__), "source_timestamps.json")


def save_timestamp(source, timestamp):
    data = load_timestamps()
    data[source] = timestamp or "unknown"
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_timestamps():
    if not os.path.exists(PATH):
        return {}
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)
