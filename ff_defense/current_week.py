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


if __name__ == "__main__":
    print(current_week())
