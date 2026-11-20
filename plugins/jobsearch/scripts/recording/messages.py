"""messages: the one public inbound message writer, `append_message` (lock, validator, rollback), shared by
`received` and `reconcile.py --harvest`.

Capability module of record.py (an entry point over `recording/`)."""

from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.common import _validator_module
from recording.store_files import (
    DEFAULT_WAIT,
    LockError,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


def _stored_source_twin(row, stored):
    """The id of a stored message whose NORMALIZED mail-tag `source` equals `row`'s, else None
    (dev #704 / public #154, D1). `None` for a row whose source is not a mail tag."""
    _vd = _validator_module()
    src = row.get("source")
    if not _vd.is_mail_tag(src):
        return None
    key = _vd.normalize_source_tag(src)
    for m in stored:
        if m.get("id") != row.get("id") and _vd.normalize_source_tag(m.get("source")) == key:
            return m.get("id")
    return None


def append_message(row, already_locked=False, wait=DEFAULT_WAIT):
    """Append `row` (a full messages.jsonl dict, `id` already minted by the caller
    deterministically) under the lock, validator-run, rolled back byte-identical on a new
    problem — the exact `cmd_answered` shape, generalised to a caller-supplied row rather than
    one this function builds itself.

    Idempotent by id: a second call with the SAME `id` (the deterministic mint from `--source`
    means the SAME source mints the SAME id) is a no-op, not a duplicate and not a re-validate
    — this is what makes a re-swept uid safe (design §5).

    ⭐ dev #704 / public #154 (D1) — ALSO idempotent by SOURCE, for a mail tag. The ATS and
    `received` ids are a hash of the source (`in-<sha1(source)[:12]>`), so a stored row whose
    source was written wrapped (`gmail:a:b'101'`) and a fresh write of the same message with the
    clean source (`gmail:a:101`) mint DIFFERENT ids, and the id check alone admitted the
    duplicate. A row whose `source` is a mail tag is therefore also a no-op when a stored row's
    NORMALIZED source equals its own; the message names the stored id. Gated on the mail-tag
    prefix, because LinkedIn thread URLs legitimately repeat across rows (dev #686 P3).

    Returns `(returncode, message)`: 0 with the store landed (or already there) clean, 1
    refused or rolled back. Locking mirrors every other write here: `already_locked=True`
    VERIFIES `lock_is_held()` rather than trusting the caller; the plain path takes and
    releases its own short-lived hold."""
    mid = row.get("id")
    _stored = load("messages")
    if any(m.get("id") == mid for m in _stored):
        return 0, "  · message %s already recorded — nothing further to do" % mid
    _twin = _stored_source_twin(row, _stored)
    if _twin is not None:
        return 0, ("  · message %s already recorded as %s (same source) — nothing further to do"
                   % (mid, _twin))

    if already_locked:
        if not lock_is_held():
            return 1, ("  REFUSED — --already-locked, but NOBODY holds the run lock.\n"
                       "  Take it first (runlock.py --take), or drop the flag.")
    else:
        try:
            take_lock("record.py received %s" % mid, wait=wait)
        except LockError as e:
            return 1, "  REFUSED — %s" % e
    try:
        messages = load("messages")
        if any(m.get("id") == mid for m in messages):
            return 0, "  · message %s already recorded — nothing further to do" % mid
        _twin = _stored_source_twin(row, messages)
        if _twin is not None:
            return 0, ("  · message %s already recorded as %s (same source) — nothing further "
                       "to do" % (mid, _twin))
        before = snapshot("messages")
        pre_rc, _, _, pre_problems = validate()
        messages.append(row)
        save_atomic("messages", messages)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("messages", before)
                return 1, ("  ⛔ REFUSED — this message broke the store; rolled back.\n  "
                           + "\n  ".join(_diagnostic_lines(rc, out, err)))
    finally:
        if not already_locked:
            release_lock()
    return 0, ("  ✦ message %s recorded — written atomically, validator clean" % mid)
