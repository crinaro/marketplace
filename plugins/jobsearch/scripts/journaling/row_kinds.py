"""The profile-schema, network, companies-raised and mail-status writers.

Capability module of `journal.py` (S4a, moved unedited)."""

from journaling.journal_file import append, now_iso
from journaling.row_shapes import (
    PIN_EVENT,
    _check_companies_raised_row,
    _check_mail_status_row,
    _check_network_row,
    _check_profile_schema_row,
)


def record_profile_schema(root, min_engine, by, at=None):
    """dev #834 -- the ONE writer of the profile pin: `{event: "profile-schema", at, min_engine, by}`. Validated
    before it is appended; a profile already pinned above this engine refuses it (`append`'s own rule). Returns
    the row."""
    rec = {"event": PIN_EVENT, "at": at or now_iso(), "min_engine": min_engine, "by": by}
    _check_profile_schema_row(rec)
    return append(root, rec)


def record_network(root, run_id, at=None, **fields):
    """dev #834 -- the ONE writer of a `network` event; `fields` are exactly `week`, `budget`, `open_drafts`,
    `sent_this_week`, `planned`. Validated before it is appended; nothing is written on a refusal. Returns the row."""
    rec = {"event": "network", "at": at or now_iso(), "run_id": run_id}
    rec.update(fields)
    _check_network_row(rec)
    return append(root, rec)


def record_companies_raised(root, run_id, setting, raised, waiting, at=None, held=None):
    """dev #834 -- the ONE writer of a `companies-raised` event: `{event, at, run_id, setting, raised, waiting}`, plus `held`
    when given (jobsearch 0.92.0, dev #950: the held counts; the caller passes it only on a profile pinned at 0.92.0). Validated
    before it is appended; nothing is written on a refusal. Returns the row."""
    rec = {"event": "companies-raised", "at": at or now_iso(), "run_id": run_id, "setting": setting,
           "raised": list(raised), "waiting": waiting}
    if held is not None:
        rec["held"] = dict(held)
    _check_companies_raised_row(rec)
    return append(root, rec)


def record_mail_status(root, run_id, mailbox, counts, unmatched, at=None):
    """dev #820 / public #175 (design section 8.2, M818) -- the ONE writer of a `mail-status` event: what
    one mailbox's status-mail search found in a run. `counts` is `{ats-status, human, digest, noise: n}`
    (`reconcile.classify_status_mail`'s four classes, every one given); `unmatched` is a list of
    `{source, subject}` for each `ats-status` message that matched no application. `coverage` reads the
    latest event per mailbox. Validated at write; an unknown class or an `unmatched` longer than the
    `ats-status` count is refused."""
    at = at or now_iso()
    rec = {"event": "mail-status", "run_id": run_id, "mailbox": mailbox, "counts": dict(counts or {}),
           "unmatched": [dict(u) if isinstance(u, dict) else u for u in (unmatched or [])], "at": at}
    _check_mail_status_row(rec)
    return append(root, rec)
