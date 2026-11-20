"""The validator's shared helpers: loading a store from the dataset directory, date and timestamp tests, and the
`req` / `enum` field checks every store's rules use.

Capability module of `validate_data.py` (S4a, moved unedited apart from `load` reading `data_root.DATA`)."""

import json
import os
import re
from validation import data_root as _data_root
from validation.vocab import DATE_RE


def load(name):
    path = os.path.join(_data_root.DATA, name)
    if not os.path.exists(path):
        return None, ["%s does not exist" % name]
    recs, errs = [], []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError as e:
            errs.append("%s line %d: invalid JSON — %s" % (name, i, e))
    return recs, errs


def is_date(v):
    return isinstance(v, str) and DATE_RE.match(v)


# ⭐ A COMMUNICATION MAY CARRY A TIME (dev/audit 2026-09-02, Class B). Two messages on one day
# — the outreach and its same-day reply — cannot be ordered from dates alone, which is what
# made the reconcile audit assert ownership it could not know and left `responded_on >= date`
# unprovable within a day. Optional `HH:MM[:SS]` after the date, space or `T` separated.
# Deliberately NOT a widening of DATE_RE for every date field: a commitment carries its time
# in its own `time` field, and every consumer of a plain date field parses ten characters.
# Only the three communication timestamps accept it: messages[].sent_on, outreach[].date,
# outreach[].responded_on. `date_part` is what a consumer compares or parses by — never the
# raw string, which may now be longer than a date.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def is_when(v):
    return isinstance(v, str) and TIMESTAMP_RE.match(v)


def date_part(v):
    """The ISO date of a timestamp-or-date string ('' for anything unreadable)."""
    s = str(v or "")
    return s[:10] if is_when(s) else ""


def precedes(a, b):
    """Is timestamp `a` PROVABLY before `b`? Different dates decide it; the same date decides
    it only when both carry a time. A same-day pair with a bare date on either side is
    unprovable and returns False — the ambiguity is reported by reconcile.py, never asserted
    here (the Class B rule: an order the data cannot show is not an order)."""
    da, db = date_part(a), date_part(b)
    if not (da and db):
        return False
    if da != db:
        return da < db
    sa, sb = str(a), str(b)
    return len(sa) > 10 and len(sb) > 10 and sa < sb


def req(rec, field, label, problems):
    if field not in rec:
        problems.append("%s: missing required field '%s'" % (label, field))
        return False
    return True


def enum(rec, field, allowed, label, problems, nullable=False):
    if field not in rec:
        problems.append("%s: missing '%s'" % (label, field))
        return
    v = rec[field]
    if v is None and nullable:
        return
    if v not in allowed:
        problems.append("%s: '%s'=%r not in {%s}" % (label, field, v, ", ".join(sorted(allowed))))
