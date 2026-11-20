"""The profile pins (0.86.0 network-first, 0.90.0 browser-fallback): each pin's version and whether a profile's journal still needs it.

One module of `migrations/` (design-component-segmentation.md §5); the 0.86.0 half moved out of `migrate.py` unedited by S2; the
0.90.0 half (dev 858) is read by `m_0_90_0_browser_fallback` and `init_profile.py`, which both need the pin and the asks reader."""

import json
import os
from journaling.journal_file import profile_pin
from migrations.stamp import ver


NETWORK_FIRST_PIN = "0.86.0"
BROWSER_FALLBACK_PIN = "0.90.0"


def _network_first_pin_needed(profile, recs=None):
    """True when the profile's journal carries no pin at or above 0.86.0. `recs` is the journal as `journal.read` returned
    it, or None to scan (tolerantly, `journal.pin_scan`)."""
    import journal as _journal
    pin = _journal.profile_pin(recs) if recs is not None else _journal.pin_scan(profile)
    return pin is None or ver(pin) < ver(NETWORK_FIRST_PIN)


def _browser_fallback_pin_needed(recs):
    """True when the journal rows `recs` (as `journal.read` returned them) carry no pin at or above 0.90.0."""
    pin = profile_pin(recs)
    return pin is None or ver(pin) < ver(BROWSER_FALLBACK_PIN)


def _browser_fallback_asks(profile):
    """`(rows, error)` for data/asks.jsonl: the parsed rows, or a string when the file is present but unreadable, a line does
    not parse or a row is not an object. Absent is `([], None)`."""
    path = os.path.join(profile, "data", "asks.jsonl")
    if not os.path.exists(path):
        return [], None
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return [], "data/asks.jsonl cannot be read (%s)" % e
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            return [], "data/asks.jsonl line %d does not parse: %s" % (n, e)
        if not isinstance(row, dict):
            return [], "data/asks.jsonl line %d is not an object" % n
        rows.append(row)
    return rows, None
