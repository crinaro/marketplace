"""LinkedIn passes: which surfaces were reached, refusals excused, the quota split, crashed passes, and the probe and
gap writers.

Capability module of `journal.py` (S4a, moved unedited)."""

import re
from journaling.journal_file import append, now_iso
from journaling.passes import record_verdict
from journaling.tables import (
    COVERED_REASON_MAX,
    COVERED_REASON_MIN,
    JournalError,
    LINKEDIN_FREE_REFUSALS_PER_DAY,
    MEDIA,
    PROBE_RESULT_RE,
    REASONS,
)


def pass_rows(recs, kind=None, today_only=False):
    rows = [r for r in recs if r.get("event") == "pass"]
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def linkedin_passes_reached(recs, today=None):
    """design-script-first.md §2 item 2 — how many of TODAY's LinkedIn passes count against the
    quota: a `returned` row dated today whose `reached` carries at least one surface (#75 — the
    count comes from surfaces the pass actually REACHED, never from a `dispatched` row, so a
    browserless launch that read nothing never consumes the quota). A `dispatched` row with no
    matching `returned` row is a crashed pass (see `crashed_passes` below) and is not counted
    here either.

    ⭐ dev #812 / public #169 (design §4) -- ONE FREE REFUSAL A DAY (owner ruling, 2026-11-05). A
    `returned` pass is not counted when its run's LATEST `recorded` row (by `at`, ties by file
    order) says `refused`, for at most `LINKEDIN_FREE_REFUSALS_PER_DAY` such passes a day, oldest
    `returned` first; any later one counts. The pairing is by run id and the latest row, never by
    position, so the order in which the dispatcher writes `returned` and `record` writes `recorded`
    does not matter. A `returned` row with NO `recorded` row counts (a record not yet run, or a
    journal from before 0.82.0: the conservative reading), and so does one whose latest verdict is
    anything but `refused` -- including `pass-failed` and `pane-held`: the account was driven. Raises
    `JournalError` on a `recorded` row whose verdict is unreadable (`record_verdict`)."""
    counted, _excused = _linkedin_quota_split(recs, today)
    return len(counted)


def linkedin_refusals_excused(recs, today=None):
    """dev #812 / public #169 -- how many of TODAY's `returned` passes the quota did NOT count
    because their record was refused (0 or `LINKEDIN_FREE_REFUSALS_PER_DAY`). `posture.py --may
    linkedin` prints it, so an admitted rerun is never silent about why."""
    _counted, excused = _linkedin_quota_split(recs, today)
    return len(excused)


def linkedin_excused_rows(recs, today=None):
    """The `returned` pass rows `linkedin_refusals_excused` counts: `run_summary` asks whether THIS
    run's refusal was the excused one, and must not re-derive the rule."""
    return _linkedin_quota_split(recs, today)[1]


def latest_recorded_row(recs, run_id):
    """The LinkedIn `recorded` pass row of `run_id` with the latest `at` (ties by file order), or
    None. The one definition of "the run's outcome" the quota and the run summary both read."""
    best = None
    for i, r in enumerate(recs):
        if (r.get("event") == "pass" and r.get("kind") == "linkedin"
                and r.get("phase") == "recorded" and r.get("run_id") == run_id):
            key = (str(r.get("at", "")), i)
            if best is None or key >= best[0]:
                best = (key, r)
    return best[1] if best else None


def _linkedin_quota_split(recs, today=None):
    today = today or now_iso()[:10]
    returned = sorted(
        ((str(r.get("at", "")), i, r) for i, r in enumerate(recs)
         if r.get("event") == "pass" and r.get("kind") == "linkedin"
         and r.get("phase") == "returned" and str(r.get("at", ""))[:10] == today
         and len(r.get("reached") or []) >= 1),
        key=lambda t: (t[0], t[1]))
    counted, excused = [], []
    for _at, _i, r in returned:
        row = latest_recorded_row(recs, r.get("run_id"))
        if (row is not None and record_verdict(row) == "refused"
                and len(excused) < LINKEDIN_FREE_REFUSALS_PER_DAY):
            excused.append(r)
        else:
            counted.append(r)
    return counted, excused


def crashed_passes(recs):
    """design-script-first.md §2 item 2 — every `dispatched` LinkedIn pass, in a run that has
    ENDED, with no matching `returned` row: dispatched, but nothing proves it ever read a page.
    Printed on its own line by `journal.py --passes` (never `--may`, which journal.py rejects) rather than
    silently folded into
    either "counted" or "not counted" — a crashed pass is neither."""
    ended = {r.get("run_id") for r in recs if r.get("event") == "end"}
    dispatched = {r.get("run_id") for r in recs
                 if r.get("event") == "pass" and r.get("kind") == "linkedin"
                 and r.get("phase") == "dispatched"}
    returned = {r.get("run_id") for r in recs
               if r.get("event") == "pass" and r.get("kind") == "linkedin"
               and r.get("phase") == "returned"}
    return sorted((dispatched & ended) - returned)


def record_probe(root, subject, thread, result, medium="linkedin", mailbox=None, by=None,
                 at=None):
    """⭐ dev #321 item 2 (V0), extended by Query or Citation C1 (D1) — one thread look, on
    either medium. Pointwise: unlike a mailbox sweep, which searches a window, a probe OPENS the
    thread (or, for email, searches an address/name-term set — see brief.py §4.3) and sees
    everything relevant, so one probe at T verifies that thread through T with no interval to
    merge.

    `medium` defaults to `"linkedin"` so every V0 caller (none existed before C1, but the
    default keeps the shape backward-compatible on principle) is unaffected. `mailbox` names the
    email account this probe searched — required when `medium="email"`, refused otherwise (a
    LinkedIn probe has no per-account shape; carrying a stray value there would let a reader
    mistake it for an email probe of that account). `by="owner"` marks the owner's own
    `--i-checked` attestation (brief.py §4.4) rather than a script-run search.

    C1's writers: `brief.py`'s mailbox probe (medium="email", one row per configured account)
    and `journal.py --probe --medium linkedin` (`linkedin-runner`, via --read — see main())."""
    at = at or now_iso()
    if not (subject and thread):
        raise JournalError("record_probe requires subject and thread")
    if medium not in MEDIA:
        raise JournalError("medium %r is not recognised — use 'email' or 'linkedin'" % medium)
    if medium == "email" and not mailbox and by != "owner":
        raise JournalError("record_probe(medium='email') requires mailbox (unless by='owner' "
                           "— the owner's own attestation names no specific account)")
    if medium == "linkedin" and mailbox:
        raise JournalError("record_probe(medium='linkedin') takes no mailbox — a LinkedIn probe "
                           "is not per-account")
    if not PROBE_RESULT_RE.match(result or ""):
        raise JournalError(
            "--result %r is not recognised — use 'empty' or 'thread:<ISO timestamp>' "
            "(Class C's probe vocabulary)" % result)
    rec = {"event": "probe", "medium": medium, "mailbox": mailbox, "subject": subject,
           "thread": thread, "result": result, "at": at}
    if by:
        rec["by"] = by
    return append(root, rec)


def record_gap(root, run_id, scope, reason, closes_when="", covered_by="", at=None,
               covered_reason=""):
    """The ONE writer of a `gap` row (factored out of main()'s `--gap` branch, dev #488 /
    public #105, so `linkedin_sweep.py record` can file a `partial-results` gap without shelling
    out). Returns the gap id. The caller owns scope normalisation and `covered_by` citation
    normalisation; this validates only what a stored gap must carry to be countable.

    ⭐ dev #711 / public #147 — a `covered_by` SUPPRESSES the gap, so it must say why the cited
    issue covers THIS gap's scope: `covered_reason`, required with `covered_by`, stored beside it.
    A reason with no citation is refused too (it would be a claim about nothing). Rows written
    before this field existed carry no reason; they stay valid and read as unverified."""
    at = at or now_iso()
    covered_reason = " ".join((covered_reason or "").split())
    if covered_by:
        if not (COVERED_REASON_MIN <= len(covered_reason) <= COVERED_REASON_MAX):
            raise JournalError(
                "--covered-by needs --covered-reason: %d-%d characters saying why %s covers THIS "
                "gap's scope (got %d). A citation hides the gap from --check, so it has to say "
                "what it is vouching for (dev #711)."
                % (COVERED_REASON_MIN, COVERED_REASON_MAX, covered_by, len(covered_reason)))
    elif covered_reason:
        raise JournalError("--covered-reason without --covered-by: a reason for a citation "
                           "that does not exist")
    if not run_id:
        raise JournalError("record_gap requires run_id")
    if not scope:
        raise JournalError("record_gap requires a scope")
    if reason not in REASONS:
        raise JournalError("record_gap reason %r is not in REASONS %r" % (reason, sorted(REASONS)))
    gid = "%s:%s" % (run_id, re.sub(r"[^A-Za-z0-9:._-]+", "-", scope))
    append(root, {"event": "gap", "run_id": run_id, "gap_id": gid, "scope": scope,
                  "reason": reason, "covered_by": covered_by or "",
                  "covered_reason": covered_reason,
                  "closes_when": closes_when or "", "at": at})
    return gid
