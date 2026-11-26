"""The profile-schema, network, companies-raised and mail-status writers.

Capability module of `journal.py` (S4a, moved unedited)."""

from journaling.journal_file import append, now_iso, read
from journaling.pins import require_pin
from journaling.row_shapes import (
    PIN_EVENT,
    _check_companies_raised_row,
    _check_mail_status_row,
    _check_network_row,
    _check_profile_schema_row,
)
from journaling.search_rows import check_search_on_row, check_search_page_row, check_skip_row, check_warning_row
from journaling.search_state import newest_warning, stamp_utc, utc_of
from journaling.tables import JournalError


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


def record_linkedin_search_skip(root, until, by="owner", at=None):
    """dev 1065 (jobsearch 0.94.0, design-role-first.md 8.1) -- the ONE writer of a `linkedin-search-skip` event: `{event, at, until, by}`,
    no run id. The owner skips the LinkedIn job search until a date at most 30 days on. Needs the 0.94.0 pin; validated before it is
    appended; nothing is written on a refusal. Returns the row."""
    require_pin(root, "a LinkedIn search skip")
    rec = {"event": "linkedin-search-skip", "at": at or now_iso(), "until": until, "by": by}
    check_skip_row(rec)
    return append(root, rec)


def record_linkedin_warning(root, run_id, kind, attended, n, at=None, reason=None, page=None):
    """dev 1065 (design-role-first.md 19.6, WN2) -- the ONE writer of a `linkedin-warning` event: `{event, at, at_utc, run_id, kind, attended, n}`, written when a LinkedIn
    warning page ended a search pass (or a posting or reply read: `page`). `kind` is a word of `search_rows.WARNING_KINDS`, never page text; `n` the plan entry whose page it was
    (1 for a posting or reply page); `reason` the judge's word for an `unclear` page (`no-cards`, `tool-error`, ...); `at_utc` the offset-aware stamp (never an order).
    It turns the scheduled search off (`search_state.scheduled_search_off`) until the owner turns it on. Needs the 0.94.0 pin. Returns the row."""
    require_pin(root, "a LinkedIn warning")
    rec = {"event": "linkedin-warning", "at": at or now_iso(), "run_id": run_id, "kind": kind, "attended": attended, "n": n}
    rec["at_utc"] = stamp_utc(at)
    if reason:
        rec["reason"] = reason
    if page:
        rec["page"] = page
    check_warning_row(rec)
    return append(root, rec)


def record_linkedin_search_on(root, warning, attended, at=None):
    """dev 1065 (design-role-first.md 19.6, WN3) -- the ONE writer of a `linkedin-search-on` event: `{event, at, at_utc, warning, attended}`. The
    only thing that turns the scheduled LinkedIn search back on after a warning. `attended` must be true (a typed word, PARTIAL), and
    `warning` the date (YYYY-MM-DD) of the NEWEST `linkedin-warning` on record (the last in the file): a date that names no warning, or an older one, is refused
    and nothing is written. A turn-on stamped (UTC) BEFORE that warning is refused too, with the two times: a clock set back or a profile copied from another zone
    would otherwise print 'turned back on' for a row that clears nothing. Needs the 0.94.0 pin. Returns the row."""
    require_pin(root, "turning the LinkedIn search back on")
    rec = {"event": "linkedin-search-on", "at": at or now_iso(), "warning": warning, "attended": attended, "at_utc": stamp_utc(at)}
    check_search_on_row(rec)
    newest = newest_warning(read(root))
    if newest is None:
        raise JournalError("there is no linkedin-warning on record, so there is nothing to turn back on (--warning %s)" % warning)
    if warning != str(newest["at"])[:10]:
        raise JournalError("--warning %s is not the newest linkedin-warning (%s, %s): name that date" % (warning, str(newest["at"])[:10], newest["kind"]))
    if utc_of(rec) < utc_of(newest):
        raise JournalError("not turned back on: this turn-on is stamped %s (UTC %s), BEFORE the warning it names (%s, UTC %s). This machine's clock is behind the warning's, or the "
                           "profile came from another time zone. Nothing was written: wait until the clock is past the warning's time (or correct it), then run it again."
                           % (rec["at"], rec["at_utc"], newest["at"], newest.get("at_utc") or utc_of(newest).isoformat()))
    return append(root, rec)


def record_search_page(root, run_id, n, step, count, at=None):
    """dev 1065 (review 2026-11-25, items 3 and 4) -- the ONE writer of a `linkedin-search-page` event: `{event, at, at_utc, run_id, n, step, count}`. `step: page` is one results
    page of plan entry `n` judged ordinary (`count` its cards); `step: links` is the ids the search printed (`count`). The per-page gate counts these rows, so a page is judged once
    and the caps hold across a crash and a resume. Needs the 0.94.0 pin. Returns the row."""
    require_pin(root, "a LinkedIn search page count")
    rec = {"event": "linkedin-search-page", "at": at or now_iso(), "at_utc": stamp_utc(at), "run_id": run_id, "n": n, "step": step, "count": count}
    check_search_page_row(rec)
    return append(root, rec)
