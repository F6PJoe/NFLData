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

NFL_WEEK1_TUESDAY = datetime.date(2026, 9, 8)  # <-- update each new season


def current_week(today=None):
    today = today or datetime.date.today()
    days_since = (today - NFL_WEEK1_TUESDAY).days
    if days_since < 0:
        return 1  # preseason / before kickoff -- default to week 1
    return days_since // 7 + 1


if __name__ == "__main__":
    print(current_week())
