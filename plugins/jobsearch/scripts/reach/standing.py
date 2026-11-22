"""standing: does this person work at this company, as the candidate knew it on a date (jobsearch 0.91.0, design-build-reach.md 5.3).

THE ONE PREDICATE every "at the company" reader asks, over one people row, with no store read: `graph.Graph.standing` resolves a
merge and calls it, and `graph.Graph.people_for_company` filters with it. It reads `company_id`, `employment` and `formerly`
(`docs/schema.md`, people) and nothing else; `ties` says how the candidate knows a person, never where the person works.

    the person's link to the company                         at date D                          standing
    it is `company_id`, `employment.status: current`         D >= employment.as_of              current
                                                             D <  employment.as_of              unknown (not learned yet)
    it is `company_id`, `status: unknown` or no employment   any                                unknown
    it is in `formerly` (entry f)                            D >= f.as_of                       former
                                                             f.counted_from <= D < f.as_of      current
                                                             otherwise                          unknown
    neither                                                  any                                None (no recorded link)

Every date read here is the day the engine LEARNED the fact (a verb's write date, or an observed message's date), so a replay at an
earlier date never knows what had not been recorded yet. A stored date that does not read counts as not learned: a `current` with an
unreadable `as_of` is `unknown`, never `current` (an unmigrated or damaged row under-counts, and never over-counts).

`needs_reconfirm` is the stale-current rule (owner O12): a `current` whose `confirmed_on` (else `as_of`) is older than the caller's
`recheck_days` (`access.employment_recheck_days`, default RECHECK_DAYS) is STILL counted and is listed once for re-confirmation.
This module reads no config; the caller resolves the setting and passes it in.

Capability module of `graph.py`. Python 3.9+, standard library only."""

import datetime
from _dates import date_or_none, to_date

STANDINGS = ("current", "unknown", "former")
RECHECK_DAYS = 365


def standing(person, company_id, as_of):
    """`current` · `unknown` · `former` for `person` (one people row, merges already resolved by the caller) at `company_id` on the
    date `as_of`, or None when the row links the person to that company nowhere (see the module docstring's table). Raises
    `ValueError` for an `as_of` that does not read: a date nobody can read is never taken for today."""
    day = to_date(as_of)
    if not isinstance(person, dict) or not company_id:
        return None
    if person.get("company_id") == company_id:
        emp = person.get("employment")
        if isinstance(emp, dict) and emp.get("status") == "current":
            learned = date_or_none(emp.get("as_of"))
            if learned is not None and day >= learned:
                return "current"
        return "unknown"
    for entry in person.get("formerly") or ():
        if not isinstance(entry, dict) or entry.get("company_id") != company_id:
            continue
        left = date_or_none(entry.get("as_of"))
        if left is not None and day >= left:
            return "former"
        counted = date_or_none(entry.get("counted_from"))
        if counted is not None and counted <= day and (left is None or day < left):
            return "current"
        return "unknown"
    return None


def needs_reconfirm(person, as_of, recheck_days=RECHECK_DAYS):
    """True when `person`'s standing on its employer of record is `current` at `as_of` and was last stated (`confirmed_on`, else
    `as_of`) more than `recheck_days` days before it. Such a person is still counted; this only lists them for a re-confirm."""
    if standing(person, (person or {}).get("company_id"), as_of) != "current":
        return False
    emp = person["employment"]
    last = date_or_none(emp.get("confirmed_on")) or date_or_none(emp.get("as_of"))
    return last is not None and (to_date(as_of) - last) > datetime.timedelta(days=int(recheck_days))
