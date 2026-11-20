"""common: the helpers every verb shares: the engine modules a verb reads (validator, plans, plays, profile), the
run date and clock, the `_Refused` / `_Usage` signals, slugs, and `Mutation`, the one single-store write a store
verb describes before `mutation.run` makes it.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import json
import os
import re
from recording.profile_paths import ENGINE_SCRIPTS


def _validator_module():
    """validate_data.py, imported as a MODULE rather than run as the subprocess `validate()`
    uses — so `fields` can read its enum sets DIRECTLY. docs/data_model.json's own _enums_note
    already states the intended architecture: 'ENUMS ARE NOT DUPLICATED HERE ... record.py
    imports that module' — true now for the first time (dev #143 / public #23 failure #3).
    Lazy: only the `fields` path pays for this."""
    import validate_data as _vd
    return _vd


def _plans_mod():
    """ADR-031 B4 — `plans.py`, the enum-owning module for `plans`/`plays`, imported lazily
    the same way `_validator_module()` is (only the code paths that need it pay for it)."""
    import plans as _pl
    return _pl


def _plays_mod():
    """plays.py — the ONE place ROLE_TO_PATH/PATH_TYPE_CLASS are defined (§26.2's own bridge
    between touches' RECIPIENT_ROLES and involvements' PATH_TYPES), imported lazily the same
    way `_plans_mod()`/`_validator_module()` are — only `_propagate_touch` pays for it."""
    import plays as _pl
    return _pl


def _profile_mod():
    """profile.py, imported lazily — only `_propagate_touch`'s next_action_owner comparison
    needs `owner_token()`, the same lazy-import discipline as `_plays_mod()`."""
    import profile as _pf
    return _pf


def _slug(text, limit=60):
    """A lower-case id fragment: runs of anything but a-z/0-9 become one `-`, trimmed, capped."""
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")[:limit].strip("-")


def _run_date_value(value, flag):
    """An ISO date from `value` (default: today); refuses a malformed one, never coerces it."""
    if value is None:
        return datetime.date.today().isoformat()
    if not _ISO_DATE.match(value):
        raise _Refused("%s must be an ISO date (YYYY-MM-DD), got %r" % (flag, value))
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise _Refused("%s %r is not a calendar date" % (flag, value))
    return value


class _Refused(Exception):
    """A sourcing-screen verb refused its input before the lock; `main()` prints `⛔ REFUSED — `
    plus the message and exits 1. Nothing has been written when this is raised."""


class _Usage(Exception):
    """Wrong arguments for a sourcing-screen verb; `main()` prints the message and exits 2."""


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _engine_version():
    """The plugin version this engine ships as, read from its own plugin.json -- stamped into a
    stored `screen` so a later reader knows which rules computed it. "0.0.0" if unreadable."""
    try:
        with open(os.path.join(os.path.dirname(ENGINE_SCRIPTS), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version") or "0.0.0"
    except (OSError, ValueError):
        return "0.0.0"


def _run_date(args):
    """The date a sourcing-screen write takes: `--on` (an ISO date) or today. Refuses a malformed
    one -- a date is never coerced."""
    if args.on_date is None:
        return datetime.date.today()
    if not _ISO_DATE.match(args.on_date):
        raise _Refused("--on must be an ISO date (YYYY-MM-DD), got %r" % args.on_date)
    try:
        return datetime.date.fromisoformat(args.on_date)
    except ValueError:
        raise _Refused("--on %r is not a calendar date" % args.on_date)


def _now():
    """The clock every 0.82.0 verb reads, to the second. A seam: tests replace it."""
    return datetime.datetime.now().replace(microsecond=0)


def _words(text):
    """Words of three or more letters, case-folded, split on anything that is not a letter (N16)."""
    return set(re.findall(r"[^\W\d_]{3,}", str(text or "").casefold()))


class Mutation(object):
    """One single-store write of record.py, described before anything is touched: the line it prints (`desc`), the
    change to the one existing row (`apply`), or for `create` the row itself (`new_row`), the ids the write mints
    (`minted`), whether `create --from-item` wrote `employer_posting` itself (`feed_posting_written`, the writer
    token the introduced-only rules hold), and the one-item holder through which link-sibling and unlink-sibling
    reach the rows the change is applied to (`apply_rows`: the dry-run's copy, or the rows re-read under the lock).
    A verb's own function builds it; `mutation.run` makes the write."""

    def __init__(self, desc, apply, new_row=None, minted=None, feed_posting_written=False, apply_rows=None):
        self.desc = desc
        self.apply = apply
        self.new_row = new_row
        self.minted = [] if minted is None else minted
        self.feed_posting_written = feed_posting_written
        self.apply_rows = [None] if apply_rows is None else apply_rows
