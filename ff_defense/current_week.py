"""
Computes the current NFL week from today's date, so the automated
Wed-Sun runs don't need a human to type --week each time.

Weeks are anchored to Tuesday (the standard fantasy/NFL "new week" boundary
-- matches ff_rankings' own EARLY WEEK phase starting Tuesday): Week 1
starts on NFL_WEEK1_TUESDAY and every 7 days after that is the next week.

NFL_WEEK1_TUESDAY needs updating once a year, at the start of each new
season -- there's no way to derive the season's kickoff date from pure
math, it's just whatever the NFL schedules that year. Verified for 2026:
today (2026-09-16, a Wednesday) computes to week 2, matching what every
other source in this pipeline (Subvertadown, the odds API) already
confirmed live.
"""

import datetime
from zoneinfo import ZoneInfo

NFL_WEEK1_TUESDAY = datetime.date(2026, 9, 8)  # <-- update each new season

ET = ZoneInfo("America/New_York")


def current_week(today=None):
    today = today or datetime.date.today()
    days_since = (today - NFL_WEEK1_TUESDAY).days
    if days_since < 0:
        return 1  # preseason / before kickoff -- default to week 1
    return days_since // 7 + 1


def week_window_utc(week=None):
    """(start, end) UTC datetimes bounding one NFL week, Tue 00:00 ET to the
    following Tue 00:00 ET -- the same Tuesday boundary current_week() uses.

    Used to decide which games belong to "this week." The Odds API returns
    every UPCOMING game, which by late in a week is mostly NEXT week's slate
    (checked live on a Sunday afternoon: only 6 of the 22 games returned
    were still this week's), so filtering by this window is what keeps next
    week's lines from being written in as if they were this week's.
    """
    week = week or current_week()
    start_date = NFL_WEEK1_TUESDAY + datetime.timedelta(days=7 * (week - 1))
    start = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=ET)
    end = start + datetime.timedelta(days=7)
    return start.astimezone(datetime.timezone.utc), end.astimezone(datetime.timezone.utc)


def stale_week(rows, week=None, field="Week"):
    """Return the CSV's stamped week if it ISN'T the week we're pushing.

    Week-specific CSVs (Yahoo projections, FantasyPros ECR) look identical
    whatever week produced them -- same 32 teams, same columns, plausible
    numbers. So a leftover file from last week pushes silently and wrong,
    which is exactly what happened once: a week-2 yahoo_def.csv got blended
    with week-3 Subvertadown adjustments and put the Chargers at 8.51
    projected points in the worst matchup on the board. Only a human
    noticing the number was implausible caught it.

    Returns None when the file is for the right week, or has no stamp at
    all (an old file from before stamping existed -- the pushes warn rather
    than refuse in that case, since there's nothing to check against).
    """
    week = week or current_week()
    for r in rows:
        stamped = r.get(field)
        if stamped:
            return int(stamped) if int(stamped) != week else None
    return None


def guard_week(path, rows, label):
    """Refuse to push a week-specific CSV left over from another week.

    Returns True when it's safe to push. Callers bail out on False rather
    than raising, so one stale file skips its own column instead of
    stopping the whole run -- same contract as the missing-file checks.
    """
    wrong = stale_week(rows)
    if wrong is not None:
        print(f"[SKIP] {path} is stamped week {wrong}, but it's week "
              f"{current_week()} -- refusing to push stale {label}. "
              f"Re-run its fetcher.")
        return False
    if rows and "Week" not in rows[0]:
        print(f"[WARN] {path} has no week stamp (pre-dates stamping) -- "
              f"pushing it unchecked.")
    return True


if __name__ == "__main__":
    print(current_week())
