"""The writer of a `pass linkedin` row that carries `scope: search` (jobsearch 0.94.0, dev 1065; docs/design-role-first.md 8.1, 19.5, 19.6).

The LinkedIn job search is its own dispatch but not its own pass KIND (a first draft used a new kind, which every accounting
consumer of a `pass` row would have missed): it is a `pass linkedin` row with `scope: search`, so the reply quota, `roles_missing`,
`crashed_passes` and `pass_durations` see it unchanged. Two rows make one search, as for every pass:

  Both rows carry `at_utc`, the offset-aware stamp the cadence counts elapsed hours from (`search_state.next_due_utc`); it orders nothing.
  dispatched   `attended` (a boolean, ALWAYS present: a person typed the word, or the scheduled dispatch did not) and `plan`, the stored
               query list (`search_rows.check_plan`). Written by `linkedin_sweep.py search-plan`, so it cannot be forgotten.
  returned     `jobsearch` (`reached` | `unreachable` | `not-attempted`) and, when it was `unreachable`, a `reason` from `SEARCH_REASONS`.

`record_pass` delegates here the moment it is given a `scope` or a `plan`, so the one function every caller already uses still refuses
`scope` on a board pass and `plan` anywhere else. The profile must carry the 0.94.0 pin (`pins.require_pin`): the row is a stored shape an
older engine cannot read. The shape check is `search_rows.check_search_pass_row`, the same one the reader runs.

Capability module of `journal.py`. Python 3.9+, standard library only."""

from journaling.journal_file import append, now_iso
from journaling.pins import require_pin
from journaling.search_rows import check_search_pass_row
from journaling.search_state import stamp_utc
from journaling.tables import JournalError, SEARCH_SCOPE


def record_search_pass(root, run_id, kind, phase, *, scope=SEARCH_SCOPE, attended=None, plan=None, reached=None, unreachable=None,
                       not_attempted=None, jobsearch=None, reason=None, at=None):
    """The ONE writer of a `scope: search` pass row. Validated against `search_rows.check_search_pass_row` before anything is appended, and
    against the pin before that: a refusal writes nothing. Returns the row."""
    if not run_id:
        raise JournalError("record_pass requires run_id")
    if scope != SEARCH_SCOPE:
        raise JournalError("record_pass scope=%r is not %r" % (scope, SEARCH_SCOPE))
    require_pin(root, "a LinkedIn search pass (`scope: search`)")
    rec = {"event": "pass", "run_id": run_id, "kind": kind, "phase": phase, "reached": list(reached or []),
           "unreachable": list(unreachable or []), "not_attempted": list(not_attempted or []), "reason": reason or "",
           "at": at or now_iso(), "at_utc": stamp_utc(at), "scope": scope}
    if jobsearch is not None:
        rec["jobsearch"] = jobsearch
    if attended is not None:
        rec["attended"] = attended
    if plan is not None:
        rec["plan"] = plan
    check_search_pass_row(rec)
    return append(root, rec)
