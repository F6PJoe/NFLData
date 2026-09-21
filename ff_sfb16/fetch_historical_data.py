"""Pull public historical NFL data used to calibrate the SFB16 bonus-event
projection model (see calibrate_rates.py). One-time/rare-rerun fetch — no
auth required, both files are public nflverse GitHub release assets.

Writes two slim, cached CSVs in this directory:
  historical_weekly.csv      - per-player-per-week stat lines, 2022-2024
  historical_pbp_plays.csv   - per-play pass/run plays with a player + yards,
                                2022-2024 (used to count actual 40+ yard plays)
"""
import gzip
import io
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
SEASONS = [2022, 2023, 2024]
HEADERS = {"User-Agent": "Mozilla/5.0 (personal use, fantasy football research)"}

WEEKLY_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
PBP_URL_TMPL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.csv.gz"

WEEKLY_COLS = [
    "player_id", "player_name", "position", "season", "week",
    "completions", "attempts", "passing_yards",
    "carries", "rushing_yards",
    "targets", "receptions", "receiving_yards",
]

PBP_COLS = [
    "season", "play_type", "yards_gained",
    "passer_player_id", "passer_player_name",
    "rusher_player_id", "rusher_player_name",
    "receiver_player_id", "receiver_player_name",
]


def _get(url):
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp.content


def fetch_weekly():
    out_path = BASE / "historical_weekly.csv"
    print(f"Downloading weekly player stats from {WEEKLY_URL} ...")
    raw = _get(WEEKLY_URL)
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    df = df[df["season"].isin(SEASONS)]
    df = df[df["position"].isin(["QB", "RB", "WR", "TE"])]
    cols = [c for c in WEEKLY_COLS if c in df.columns]
    df = df[cols]
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


def fetch_pbp():
    out_path = BASE / "historical_pbp_plays.csv"
    frames = []
    for year in SEASONS:
        url = PBP_URL_TMPL.format(year=year)
        print(f"Downloading play-by-play for {year} from {url} ...")
        raw = _get(url)
        df = pd.read_csv(io.BytesIO(gzip.decompress(raw)), low_memory=False)
        df = df[df["play_type"].isin(["pass", "run"])]
        cols = [c for c in PBP_COLS if c in df.columns]
        df = df[cols]
        frames.append(df)
        print(f"  {year}: {len(df)} pass/run plays")
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(out_path, index=False)
    print(f"Wrote {len(combined)} rows to {out_path}")


if __name__ == "__main__":
    fetch_weekly()
    fetch_pbp()
