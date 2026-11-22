"""_dates: reading a date off a stored row, loudly for an `as_of` and quietly for a stored value.

Core (standard library only). Moved out of `graph.py` unchanged by split_module.py (jobsearch 0.91.0 step B1-A), so the
dated predicates (`graph.warmth`, `reach.standing`) share one reader; `graph.to_date` / `graph.date_or_none` still resolve."""

import datetime


def to_date(value):
    """A `datetime.date` from a date, a datetime or an ISO string (a `YYYY-MM-DD HH:MM` stamp keeps its
    date). Raises `ValueError` for anything else: an `as_of` nobody can read must be loud, never read as
    today."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    raise ValueError("not a date: %r" % (value,))


def date_or_none(value):
    """`to_date`, or None for a missing or unreadable STORED value (a commitment's literal `unresolved`
    date, a null). A row whose date cannot be read is not evidence of anything on any day."""
    try:
        return to_date(value)
    except ValueError:
        return None
