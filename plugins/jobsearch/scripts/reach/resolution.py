"""resolution: what a SENT touch's wait came to, the one classification every reply rate reads (dev #834 M2; jobsearch 0.91.0 B5).

`touch_resolution(x, today)` is `resolved` (a terminal outcome), `resolved-aged` (still `awaiting` after `NO_RESPONSE_AFTER` days:
counted as resolved, never written back), `awaiting`, `bounced`, or `undeliverable-unknown` (a pattern-inferred address with unknown
delivery: evidence of nothing). `touch_is_win` is a reply, a booking or an accepted request. Below `MIN_SAMPLE` no rate is printed.
Moved out of `funnel_report.py` unedited by `split_module.py` (jobsearch 0.91.0 B5 step A) so the weekly measures
(`reach/measures.py`, design-build-reach.md 8, R2 N11) reuse the funnel's own rule instead of a second copy; `funnel_report.py`
re-exports every name. With `today` None the age reads the wall clock (`days_since`), as it always has. Capability module of
`funnel_report.py`. Python 3.9+, standard library only."""

import datetime


# Below this, a percentage is noise dressed up as a finding.
MIN_SAMPLE = 5


# A touch outcome that ENDS the wait — the resolution every reply/resolution rate reads. One
# tuple, read by `resolution()` in main() and by `step_funnel()` below, so the two funnels can
# never disagree about what "resolved" means.
TERMINAL_TOUCH_OUTCOMES = ("replied", "meeting-booked", "accepted", "no-response", "declined")


# ⭐ dev #834 (M2) — the resolution rule, hoisted out of main() so the network section shares it.
# A WIN is a reply, a booking or an accepted connection request.
WIN_OUTCOMES = ("replied", "meeting-booked", "accepted")
NO_RESPONSE_AFTER = 14   # an `awaiting` row older than this is COUNTED as resolved, but the row
                         # is NEVER mutated — the inference stays in the report


def _age_days(d, today=None):
    """Days from ISO date `d` to `today` (a date), or to the wall clock when `today` is None."""
    if today is None:
        return days_since(d)
    try:
        return (today - _iso_to_date(d)).days
    except (ValueError, AttributeError, TypeError):
        return None


def touch_resolution(x, today=None):
    """resolved / resolved-aged / awaiting / bounced / undeliverable-unknown, for one SENT touch."""
    if x.get("delivery") == "bounced":
        return "bounced"
    oc = x.get("outcome")
    if oc in TERMINAL_TOUCH_OUTCOMES:
        return "resolved"
    age = _age_days(x.get("date"), today)
    if oc == "awaiting" and age is not None and age >= NO_RESPONSE_AFTER:
        return "resolved-aged"
    # A pattern-inferred address with unknown delivery cannot distinguish silence from a bounce.
    # It is evidence of NOTHING either way and must not sit in a denominator.
    if (x.get("medium") or "").startswith("email") and \
       x.get("address_status") == "pattern-inferred" and x.get("delivery") == "unknown":
        return "undeliverable-unknown"
    return "awaiting"


def touch_is_win(x):
    return x.get("outcome") in WIN_OUTCOMES


def _iso_to_date(s):
    y, m, d = (int(x) for x in s.split("-"))
    return datetime.date(y, m, d)


def days_since(d):
    if not d:
        return None
    try:
        y, m, dd = (int(x) for x in d.split("-"))
        return (datetime.date.today() - datetime.date(y, m, dd)).days
    except ValueError:
        return None
