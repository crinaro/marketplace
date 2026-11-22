"""weeks: the ISO week and the business-day count the network block's budget and 3B7 timetable read (design-network-first.md 9.1).

`iso_week(today)` is `(label, monday, sunday)` of the ISO week holding a date (2027-01-01 is in `2026-W53`); `business_days_since`
counts the days in `(start, end]` whose ISO weekday is in `network.workdays` (holidays are not modelled). Moved out of
`reachouts.py` unedited (jobsearch 0.91.0 B4 step A) so the weekly measures can share them; `reachouts.py` re-exports both.
Capability module of `reachouts.py`. Python 3.9+, standard library only."""

import datetime


def iso_week(today):
    """`(label, monday, sunday)` of the ISO week containing `today` (a date): `("2026-W46", date, date)`. The ISO year is the
    one the week belongs to, so 2027-01-01 is in `2026-W53`."""
    year, week, _wd = today.isocalendar()
    monday = today - datetime.timedelta(days=today.weekday())
    return "%04d-W%02d" % (year, week), monday, monday + datetime.timedelta(days=6)


def business_days_since(start, end, workdays):
    """How many business days lie in `(start, end]`: the days after `start`, up to and including `end`, whose ISO weekday (1 = Monday
    .. 7 = Sunday) is in `workdays`. A reach-out sent on a Monday is 3 business days old on Thursday; sent on a Thursday it is 3
    business days old on the next Tuesday (Friday, Monday, Tuesday: Saturday and Sunday are skipped). Zero when `end` is not after
    `start`."""
    n, d = 0, start
    while d < end:
        d += datetime.timedelta(days=1)
        if d.isoweekday() in workdays:
            n += 1
    return n
