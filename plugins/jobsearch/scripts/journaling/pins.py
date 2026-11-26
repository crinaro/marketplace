"""The 0.94.0 profile pin as the role-first release reads it: the pin's version, the release instant (the EARLIEST pin at or above
it), and the refusal every writer of a 0.94.0 stored shape gives a profile that has no such pin (jobsearch 0.94.0, dev 1062;
docs/design-role-first.md 3.3, 3.5, 11).

Two things are answered here and nowhere else:

  `earliest_pin_at`   the release instant. Two machines that both migrated give two `profile-schema` events and the EARLIEST `at` wins
                      (the `readmit` precedent), so the instant is the first moment any machine turned the rules on. A tolerant file
                      scan (`earliest_pin_at_scan`) answers for a journal `read` refuses, and `earliest_pin_at` for rows already read.
  `require_pin`       the "no 0.94.0 pin" refusal (RF4). A profile with no pin at or above 0.94.0 must keep behaving as 0.93.0 did, so a
                      writer of a new shape (a `matching` block, a `scope: search` row, a new `roles` field, the three LinkedIn search
                      events, a withdrawal) raises this instead of writing, and says which migration is pending. `pin_refusal` (a pin
                      ABOVE this engine) is a different refusal and stays `journal_file`'s.

Nothing here WRITES the pin: that is `m_0_94_0_role_first` (design 11), which does it first.

Capability module of `journal.py`. Python 3.9+, standard library only."""

import datetime
import json
from journaling.journal_file import path, pin_scan
from journaling.row_shapes import PIN_EVENT, _pin_ver
from journaling.tables import JournalError

ROLE_FIRST_PIN = "0.94.0"
ROLE_FIRST_MIGRATION = "m_0_94_0_role_first"


def _at(value):
    """The naive `datetime` of a stored `at`, or None when it is not an ISO date and time (a pin whose `at` cannot be read
    contributes no instant: the strict row check refuses it at write, and a tolerant scan must not guess)."""
    try:
        d = datetime.datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d is not None else None


def _earliest(rows, minimum):
    want = _pin_ver(minimum)
    best = None
    for r in rows:
        if not isinstance(r, dict) or r.get("event") != PIN_EVENT:
            continue
        v, at = _pin_ver(r.get("min_engine")), _at(r.get("at"))
        if v is not None and v >= want and at is not None and (best is None or at < best[0]):
            best = (at, r["at"])
    return best[1] if best else None


def earliest_pin_at(recs, minimum=ROLE_FIRST_PIN):
    """The `at` of the EARLIEST `profile-schema` event in `recs` (rows `journal.read` returned) whose `min_engine` is at or
    above `minimum`, or None. None means the profile has no such pin, so every rule that keys on it is off (RF4)."""
    return _earliest(recs or (), minimum)


def earliest_pin_at_scan(root, minimum=ROLE_FIRST_PIN):
    """`earliest_pin_at` over the journal file itself, TOLERANT as `pin_scan` is: a line that does not parse, an event of another
    name and a pin that is not `X.Y.Z` are skipped, and nothing else is validated. Not cached: it is asked a few times a run."""
    rows = []
    try:
        with open(path(root), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if PIN_EVENT not in line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return None
    return _earliest(rows, minimum)


def pin_missing_line(root, what, minimum=ROLE_FIRST_PIN, migration=ROLE_FIRST_MIGRATION):
    """`None` when the profile's pin (`pin_scan`, the highest) is at or above `minimum`, else the sentence a writer refuses with:
    what is refused, why, and which migration is pending. An unpinned profile is below it."""
    pin = pin_scan(root)
    have = _pin_ver(pin)
    if have is not None and have >= _pin_ver(minimum):
        return None
    return ("this profile is not pinned to jobsearch %s (its pin is %s), so %s is refused: an older engine sharing the profile "
            "cannot read it, and until the pin is written this engine behaves as 0.93.0 did. The pending migration is %s; it "
            "runs at the next session start (or run `~/.claude/jobsearch/run migrate.py`), and then this call can be repeated. "
            "Nothing was written." % (minimum, pin or "absent", what, migration))


def require_pin(root, what, minimum=ROLE_FIRST_PIN, migration=ROLE_FIRST_MIGRATION):
    """Raise `JournalError` with `pin_missing_line` when the profile has no pin at or above `minimum`. The ONE check every writer
    of a 0.94.0 stored shape calls before it appends; `what` names the shape in the sentence."""
    line = pin_missing_line(root, what, minimum, migration)
    if line:
        raise JournalError(line)
