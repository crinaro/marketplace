"""follow_stop: whether the candidate has stopped following a person up, and the one filter every reader of touches uses to skip
the control rows (jobsearch 0.92.0, dev #951, docs/design-decision-surface.md B.1 and review round 2 H2).

A stop is an append-only touch row (`touch_type` `stop-following`, written by `record.py stop-following`); `--undo` appends a
`resume-following` row. Neither is outreach: both are `status: declined` with no role and no channel, so a reader that counts
`status == "sent"` or joins on a role never sees one. A reader that does neither iterates `ordinary(touches)`.

THE IN-FORCE RULE, over one person's own rows (merges resolved by the caller), in store order. No control row, or the last one a
resume: not in force. Else the last is a stop dated S that stored `inbound_seen` = k, the person's inbound dated S-1, S or S+1
when it was written (`inbound_near`). It is REOPENED by the earliest of: an inbound dated after S+1; `inbound_near(S) > k` (a
message from that window stored after the stop); a `status: sent` touch or an outbound message dated after S. Otherwise it is in
force. The one-day margin either side is there because a message's date is the sender's local day (RFC 5322 section 3.3) and the
engine does not normalise the zone: a reply sent from another zone must never be hidden. The accepted cost (design F3): a message
from that window that the candidate read in their own mail before stopping, stored by a later run, reopens the person once.

Takes plain row lists, never a Graph, and imports nothing from the engine. Python 3.9+, standard library only."""

import datetime

STOP = "stop-following"
RESUME = "resume-following"
# The two control types, spelled here AND as `validation.vocab.FOLLOW_CONTROL_TYPES` (the validator's vocabulary), because an import
# of `validation` from `reach` closes a cycle through validate_data.py and your_move.py (G6). tests/reach/test_follow_stop.py pins
# the two equal.
FOLLOW_CONTROL_TYPES = frozenset({STOP, RESUME})


def is_control(touch):
    """True for a stop or resume row."""
    return isinstance(touch, dict) and touch.get("touch_type") in FOLLOW_CONTROL_TYPES


def ordinary(touches):
    """The rows of `touches` that are not control rows, in order: THE one filter for a reader that does not test
    `status == "sent"` or join on a role."""
    return [t for t in touches or () if not is_control(t)]


def ids_of(people, pid):
    """`pid` plus every `status: merged` row whose `merged_into` chain ends at `pid` (the answer `Graph.resolve_person` gives).
    A chain that loops contributes nothing."""
    into = {p.get("id"): p.get("merged_into") for p in people or () if isinstance(p, dict) and p.get("status") == "merged"
            and p.get("id") and p.get("merged_into")}
    out = {pid}
    for start in into:
        seen, cur = set(), start
        while cur in into and cur not in seen:
            seen.add(cur)
            cur = into[cur]
        if cur == pid and cur not in seen:
            out.add(start)
    return out


def _day(value):
    """The ISO day at the start of `value`, as a date, or None when it does not read."""
    try:
        return datetime.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _inbound_days(touches, messages):
    """Every inbound day of one person's rows: an inbound message's `sent_on`, and an ordinary touch's `responded_on`."""
    days = [_day(m.get("sent_on")) for m in messages or () if m.get("direction") == "inbound"]
    days += [_day(t.get("responded_on")) for t in ordinary(touches) if t.get("responded_on")]
    return [d for d in days if d is not None]


def _outbound_days(touches, messages):
    """Every outbound day: an ordinary `status: sent` touch's `date`, and an outbound message's `sent_on`."""
    days = [_day(t.get("date")) for t in ordinary(touches) if t.get("status") == "sent"]
    days += [_day(m.get("sent_on")) for m in messages or () if m.get("direction") == "outbound"]
    return [d for d in days if d is not None]


def inbound_near(touches, messages, day):
    """How many of the person's stored inbound are dated `day` - 1, `day` or `day` + 1 (`day` an ISO string or a date). The
    writer stores this as `inbound_seen`; the reader compares against it."""
    d = _day(day) if not isinstance(day, datetime.date) else day
    if d is None:
        return 0
    one = datetime.timedelta(days=1)
    return sum(1 for x in _inbound_days(touches, messages) if d - one <= x <= d + one)


def in_force(touches, messages):
    """`(in_force, stop_row, reopened_by)` over one person's own rows, merges resolved by the caller, in store order (the module
    docstring). `stop_row` is the last stop (None when the last control row is a resume, or there is none); `reopened_by` is
    `{"on": ISO day, "by": "inbound" | "outbound"}` when that stop was reopened, else None."""
    controls = [t for t in touches or () if is_control(t)]
    if not controls or controls[-1].get("touch_type") != STOP:
        return False, None, None
    stop = controls[-1]
    s = _day(stop.get("date"))
    if s is None:
        return False, stop, None                     # a stop with no readable day stops nothing (the validator refuses one)
    one = datetime.timedelta(days=1)
    seen = stop.get("inbound_seen")
    seen = seen if isinstance(seen, int) and not isinstance(seen, bool) else 0
    found = [(d, "inbound") for d in _inbound_days(touches, messages) if d > s + one]
    if inbound_near(touches, messages, s) > seen:
        found.append((max(d for d in _inbound_days(touches, messages) if s - one <= d <= s + one), "inbound"))
    found += [(d, "outbound") for d in _outbound_days(touches, messages) if d > s]
    if not found:
        return True, stop, None
    on, by = min(found)
    return False, stop, {"on": on.isoformat(), "by": by}
