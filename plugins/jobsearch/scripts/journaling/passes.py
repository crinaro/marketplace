"""Sweep, triage, dispatch and pass records: their writers (`record_pass`, carried at 274 lines) and the field checks
they share.

Capability module of `journal.py` (S4a, moved unedited)."""

import re
from journaling.instants import _coverage_field, _journal_at, _parse_iso
from journaling.journal_file import append, now_iso
from journaling.tables import (
    AGENT_PASS_KINDS,
    BATCH_END_STATES,
    BOARD_SWEEPS,
    JOBSEARCH_TOKENS,
    JournalError,
    LINKEDIN_SWEEP_SURFACES,
    OWNED_RULES,
    PASS_KINDS,
    PASS_PHASES,
    REASONS,
    RECORDED_KEPT_PREFIX,
    RECORD_VERDICTS,
    SPLIT_WEEKDAYS,
    TRIAGE_VERDICTS,
    UNREACHED_PASS_KINDS,
)


def record_swept(root, mailbox, frm, through, by, ok, reason=None, at=None, source=None):
    """⭐ dev #321 (V0) — the ONE writer for positive mailbox coverage. `ok=True` needs `frm`
    and `through` (the window this sweep actually searched, ISO timestamps) — a positive
    coverage row with no window is not verifiable, so that shape is refused rather than stored
    with nulls. `ok=False` needs a REASON CODE from `REASONS` (the same "a code can be counted,
    a sentence cannot" rule the rest of this journal already enforces) and stores no window: a
    failed sweep covers nothing, which is the whole point — this is the `!! INCOMPLETE COVERAGE`
    banner stored instead of merely printed, so `covered_through()` for that mailbox does not
    advance past whatever it already had.

    ⭐ dev #799 — `source`, optional and ADDITIVE: `"connector-bundle"` marks a row whose window is the
    span a fetched connector bundle covered. Absent means IMAP, so every old row keeps its meaning; no
    reader refuses an unknown key on a `swept` row (checked at the build: `read()` validates only the
    `dispatch` shape).

    ⭐ dev #807 — `frm` and `through` are INSTANTS: an aware datetime (written through `coverage_iso`) or
    an ISO string that carries a numeric offset. A naive value is REFUSED, because a naive local time in
    the fall-back hour names two instants and the reader cannot tell which one the writer meant. `at`
    keeps the journal-wide naive-local convention (`reconcile.first_swept_at` sorts it as a string), so
    an aware `at` is converted to naive host-local here."""
    at = _journal_at(at) if at else now_iso()
    if not mailbox:
        raise JournalError("record_swept requires a mailbox")
    if ok:
        if not (frm and through):
            raise JournalError(
                "record_swept(ok=True) requires frm and through — the window this sweep "
                "actually searched. A positive coverage row with no window is not verifiable.")
        frm, through = _coverage_field(frm, "frm"), _coverage_field(through, "through")
        rec = {"event": "swept", "mailbox": mailbox, "from": frm, "through": through,
               "at": at, "by": by or "", "ok": True}
        if source:
            rec["source"] = source
    else:
        if reason not in REASONS:
            raise JournalError(
                "record_swept(ok=False) requires reason in REASONS, got %r — a failure without "
                "a reason code cannot be counted or grouped" % reason)
        rec = {"event": "swept", "mailbox": mailbox, "from": None, "through": None,
               "at": at, "by": by or "", "ok": False, "reason": reason}
    return append(root, rec)


def record_triaged(root, mailbox, uid, verdict, by, at=None):
    """⭐ public #99 — the completion mark for one triaged uid. `mailbox` is REQUIRED and stored
    alongside `uid` (never a bare `"<mailbox>:<uid>"` string) so two mailboxes that happen to
    reuse the same IMAP uid number are never confused by a caller that filters on `mailbox`
    first, the same shape `record_swept`'s own `mailbox` field already has.

    ⭐ Call this ONLY after a uid's disposition is actually decided — for `alert_sweep.py`, after
    its header fetch and its own row is built, never before. A run killed between fetching a uid
    and calling this leaves NO row for it, so the next run finds it un-triaged and processes it
    again — the same crash-safety the ATS sweep's own uid mark has (design-inbound-resolution.md
    §5): an unwritten disposition is re-seen next run, never silently skipped, by construction
    rather than by a recovery pass."""
    at = at or now_iso()
    if not mailbox:
        raise JournalError("record_triaged requires a mailbox")
    if not uid:
        raise JournalError("record_triaged requires a uid")
    if verdict not in TRIAGE_VERDICTS:
        raise JournalError(
            "record_triaged verdict %r is not in TRIAGE_VERDICTS %r — a verdict is a code, not "
            "a sentence" % (verdict, sorted(TRIAGE_VERDICTS)))
    rec = {"event": "triaged", "mailbox": mailbox, "uid": str(uid), "verdict": verdict,
           "at": at, "by": by or ""}
    return append(root, rec)


def record_dispatch(root, run_id, agent, agent_id, model, tokens, tool_uses, duration_s,
                    outcome, for_="", at=None):
    """⭐ design-script-first.md §8.2 (public #90/#111) — the ONE writer for a `dispatch` row.
    Every numeric field is required and type-checked: a dispatch row nobody can trust the
    numbers of is worse than none (this file's own "unparseable value must be LOUD" rule,
    applied to the cost ledger the fold below builds). `agent_id` is the fold's idempotence
    key — refused empty, the same way `record_probe` refuses an empty `subject`/`thread`."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_dispatch requires run_id")
    if not agent:
        raise JournalError("record_dispatch requires agent")
    if not agent_id:
        raise JournalError("record_dispatch requires agent_id — it is the fold's idempotence key")
    for name, v in (("tokens", tokens), ("tool_uses", tool_uses), ("duration_s", duration_s)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise JournalError("record_dispatch: %s must be an int >= 0 (got %r)" % (name, v))
    rec = {"event": "dispatch", "run_id": run_id, "agent": agent, "agent_id": agent_id,
           "model": model or "", "tokens": tokens, "tool_uses": tool_uses,
           "duration_s": duration_s, "outcome": outcome or "unknown", "for": for_ or "", "at": at}
    return append(root, rec)


def dispatch_rows(recs, today_only=False):
    rows = [r for r in recs if r.get("event") == "dispatch"]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def _is_count(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def check_recorded_fields(verdict, faults, kept, concluded, not_concluded):
    """dev #812 / public #169 (design §4, §15 N13) -- the ONE validation of a `recorded` pass row's
    fields. PURE: it reads nothing and writes nothing, and raises `JournalError` on any combination
    it refuses. `record_pass` calls it, and so does the `judge` test, which feeds every verdict
    `linkedin_sweep.py` can reach through it: a combination refused here fails that test and is
    never an `apply` exception.

      * `verdict` is one of `RECORD_VERDICTS`;
      * `faults` is an int >= 0: **0** on `clean`, `incomplete` and `refused` (a structural refusal
        judges no lines), **> 0** on `line-faults`, **>= 0** on `pass-failed` and `pane-held` (a
        pass that reached nothing can still carry garbled lines);
      * `kept` is `""` (no copy was kept, or the write failed) or a profile-relative path under
        `.jobsearch/handbacks/` (no `..` segment);
      * `concluded` and `not_concluded` are ints >= 0."""
    if verdict not in RECORD_VERDICTS:
        raise JournalError("a recorded pass row's verdict %r is not one of RECORD_VERDICTS %r"
                           % (verdict, RECORD_VERDICTS))
    if not _is_count(faults):
        raise JournalError("a recorded pass row's faults=%r is not a non-negative integer" % (faults,))
    if verdict == "line-faults" and faults == 0:
        raise JournalError("a recorded pass row with verdict 'line-faults' must carry faults > 0")
    if verdict in ("clean", "incomplete", "refused") and faults != 0:
        raise JournalError("a recorded pass row with verdict %r must carry faults=0 (got %r): "
                           "only line-faults, pass-failed and pane-held carry line faults"
                           % (verdict, faults))
    if not isinstance(kept, str):
        raise JournalError("a recorded pass row's kept=%r is not a string (use '' for no copy)"
                           % (kept,))
    if kept:
        tail = kept[len(RECORDED_KEPT_PREFIX):]
        if (not kept.startswith(RECORDED_KEPT_PREFIX) or not tail or "\\" in kept
                or ".." in kept.split("/")):
            raise JournalError("a recorded pass row's kept=%r is not a path under %s"
                               % (kept, RECORDED_KEPT_PREFIX))
    for label, v in (("concluded", concluded), ("not_concluded", not_concluded)):
        if not _is_count(v):
            raise JournalError("a recorded pass row's %s=%r is not a non-negative integer"
                               % (label, v))


def _check_ids(label, ids, nonempty):
    """A list of distinct ids: strings, non-empty, without whitespace. Opportunity ids, capture item ids
    and company ids all satisfy it."""
    if (not isinstance(ids, (list, tuple)) or (nonempty and not ids)
            or any(not isinstance(i, str) or not i or re.search(r"\s", i) for i in ids)
            or len(set(ids)) != len(ids)):
        raise JournalError("record_pass %s=%r is not %sa list of distinct ids (non-empty strings "
                           "without whitespace)" % (label, ids, "non-empty " if nonempty else ""))


def _check_channels(channels):
    """dev #811 / public #170 (design §5.3) -- a `pass board dispatched` row's `channels`: the ids of
    the call's combined worklist. A non-empty list of DISTINCT non-empty strings without whitespace."""
    if (not isinstance(channels, (list, tuple)) or not channels
            or any(not isinstance(c, str) or not c or re.search(r"\s", c) for c in channels)
            or len(set(channels)) != len(channels)):
        raise JournalError("record_pass channels=%r is not a non-empty list of distinct channel ids "
                           "(non-empty strings without whitespace)" % (channels,))


# dev #826 / public #177 (jobsearch 0.83.0, design-sweep-misfires.md section 2.4) -- what a `recorded` LinkedIn
# pass row says about the Browser pane. `pane` is the state the runner read from the harness (`displayed`,
# `hidden`, `unknown`) or `not-pane` (the pass ran on the Chrome extension); `unreported` is the script's own word
# for a SWEEP block that carried no readable `PANE` line, never something the runner writes. `mode` is whether any
# part of the pass ran in hidden mode; `unreported` goes with `pane == "unreported"` only, because a pass whose
# pane line is missing proves neither mode.
PASS_PANE_STATES = ("displayed", "hidden", "unknown", "not-pane", "unreported")
PASS_PANE_MODES = ("normal", "hidden", "unreported")


def _check_owned_elsewhere(owned):
    """dev #830 / public #180 (C6, owner ruling O2) -- a `pass board dispatched` row's `owned_elsewhere`: a non-empty
    `{channel_id: {"agent": str, "rule": OWNED_RULES}}`, the agent never `board-sweeper` (a channel the sweeper owns is in
    its worklist, not excluded from it)."""
    if not isinstance(owned, dict) or not owned:
        raise JournalError("record_pass owned_elsewhere=%r is not a non-empty {channel_id: {agent, rule}} map" % (owned,))
    for cid, v in owned.items():
        if not isinstance(cid, str) or not cid or re.search(r"\s", cid):
            raise JournalError("record_pass owned_elsewhere has the channel id %r (a non-empty string without "
                               "whitespace)" % (cid,))
        if (not isinstance(v, dict) or set(v) != {"agent", "rule"} or not isinstance(v["agent"], str) or not v["agent"]
                or v["agent"] == "board-sweeper" or v["rule"] not in OWNED_RULES):
            raise JournalError("record_pass owned_elsewhere[%r]=%r is not {agent: <an agent other than board-sweeper>, "
                               "rule: one of %s}" % (cid, v, ", ".join(OWNED_RULES)))


def record_pass(root, run_id, kind, phase, reached=None, unreachable=None, not_attempted=None,
                reason=None, at=None, jobsearch=None, sweep=None, attended=None,
                split_days=None, *, verdict=None, faults=None, kept=None, concluded=None,
                not_concluded=None, channels=None, ids=None, unreached=None,
                pane=None, mode=None, partial=None, batch=None, of=None, t0_utc=None, state=None,
                code=None, handed=None, worklist=None, owned_elsewhere=None):
    """design-script-first.md §2 (public #75/#87/#110) — the ONE writer for a `pass` row.
    `phase` is validated against `PASS_PHASES`, `kind` against `PASS_KINDS`, `reason` against
    `REASONS` (required for `phase="refused"`, refused otherwise — a reason on a row that is not
    a refusal is not a reason for anything). `reached`/`unreachable`/`not_attempted` are each
    validated against `LINKEDIN_SURFACES` when `kind == "linkedin"` when given at all: an
    unrecognised surface token is refused at write, the same "unparseable value must be LOUD"
    rule this whole file applies everywhere else. Every field is stored even when empty ([] is
    written, not omitted) so a reader never has to tell 'absent' from 'empty list' apart.

    dev #812 / public #169 -- `phase="recorded"` (a LinkedIn row only) is what `linkedin_sweep.py
    record` writes after judging a SWEEP hand-back. It REQUIRES the keyword-only `verdict`, `faults`,
    `kept`, `concluded` and `not_concluded`, validated by `check_recorded_fields`; any of the five on
    another phase is refused. dev #811 / public #170 -- the keyword-only `channels` is for a `pass
    board dispatched` row only (the call's combined worklist, `board_worklist` reads it back).

    dev #820 / public #175 (0.82.0) -- the drain's pass kinds. `reader` and `research` rows name the
    ids handed to an agent: `ids` (a non-empty list of distinct ids) is REQUIRED on their `dispatched`
    and `returned` rows and refused anywhere else; a `feeds` row may carry the company ids it covered.
    `capture` and `fetch` take phase `done` ONLY, with the keyword-only `unreached` (the ids the bounded
    call did not reach, `[]` when it reached them all); `done` and `unreached` are refused on any
    other kind. `drain_close` reads the LAST `capture` row's `unreached` to give an admitted item the
    cause `deadline-reached`.

    dev #826 / public #177 (0.83.0) -- the keyword-only `pane`, `mode` and `partial` are a `recorded`
    LinkedIn row's account of the Browser pane: all three or none (a row written before 0.83.0, or a failed
    pass whose block was never read, carries none). `pane` is one of `PASS_PANE_STATES`, `mode` one of
    `PASS_PANE_MODES` (`unreported` exactly when `pane == "unreported"`), and `partial` the surfaces read from
    a pane that was not painting, a subset of `reached`.

    dev #830 / public #180 (0.84.0) -- the board loop's rows. `phase="batch"` (board only) REQUIRES `channels` (the ids
    handed out), `batch` (an int >= 1), `of` (the planned batch count, an int >= batch) and `t0_utc` (an ISO instant WITH a
    UTC offset: batch 1's, copied by later batches). `phase="batch-end"` (board only) REQUIRES `state` (one of
    `BATCH_END_STATES`), `handed` and `worklist` (counts), and may carry `code` (a `REASONS` code). Every one of these
    keywords is refused on any other phase. `owned_elsewhere` is for a `dispatched` board row only: a non-empty
    `{channel_id: {"agent": <owning agent, never board-sweeper>, "rule": one of OWNED_RULES}}`, the channels the worklist
    left out because another agent owns them (`channels_due.owner_elsewhere`)."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_pass requires run_id")
    if kind not in PASS_KINDS:
        raise JournalError("record_pass kind %r is not in PASS_KINDS %r" % (kind, PASS_KINDS))
    if phase not in PASS_PHASES:
        raise JournalError("record_pass phase %r is not in PASS_PHASES %r" % (phase, PASS_PHASES))
    if (phase == "done") != (kind in UNREACHED_PASS_KINDS):
        raise JournalError("record_pass: phase 'done' is for the %s pass kinds and only for them (got "
                           "kind=%r phase=%r)" % (" and ".join(UNREACHED_PASS_KINDS), kind, phase))
    loop_fields = dict(batch=batch, of=of, t0_utc=t0_utc, state=state, code=code, handed=handed, worklist=worklist)
    if phase in ("batch", "batch-end"):
        if kind != "board":
            raise JournalError("record_pass: phase %r is only for a board pass (got kind=%r)" % (phase, kind))
        if phase == "batch":
            need = ("channels", "batch", "of", "t0_utc")
            missing = [k for k in need if (channels if k == "channels" else loop_fields[k]) is None]
            if missing:
                raise JournalError("record_pass(phase='batch') requires %s (missing: %s)" % (", ".join(need),
                                                                                         ", ".join(missing)))
            if not _is_count(batch) or batch < 1 or not _is_count(of) or of < batch:
                raise JournalError("record_pass batch=%r of=%r: batch is an integer >= 1 and of an integer >= batch"
                                   % (batch, of))
            parsed = _parse_iso(t0_utc) if isinstance(t0_utc, str) else None
            if parsed is None or parsed.tzinfo is None:
                raise JournalError("record_pass t0_utc=%r is not an ISO instant with a UTC offset (a naive time "
                                   "cannot be subtracted across a DST change)" % (t0_utc,))
        else:
            missing = [k for k in ("state", "handed", "worklist") if loop_fields[k] is None]
            if missing:
                raise JournalError("record_pass(phase='batch-end') requires state, handed and worklist (missing: %s)"
                                   % ", ".join(missing))
            if state not in BATCH_END_STATES:
                raise JournalError("record_pass state=%r is not one of %r" % (state, BATCH_END_STATES))
            if not _is_count(handed) or not _is_count(worklist) or handed > worklist:
                raise JournalError("record_pass handed=%r worklist=%r: counts, handed <= worklist" % (handed, worklist))
            if code is not None and code not in REASONS:
                raise JournalError("record_pass code=%r is not a REASONS code" % (code,))
    else:
        given_loop = sorted(k for k, v in loop_fields.items() if v is not None)
        if given_loop:
            raise JournalError("record_pass: %s only for phase 'batch' or 'batch-end' (got phase=%r)"
                               % (", ".join(given_loop), phase))
    if owned_elsewhere is not None:
        if kind != "board" or phase != "dispatched":
            raise JournalError("record_pass: owned_elsewhere is only for a board pass with phase='dispatched' "
                               "(got kind=%r phase=%r)" % (kind, phase))
        _check_owned_elsewhere(owned_elsewhere)
    if kind in ("reader", "research", "feeds") and phase not in ("dispatched", "returned", "refused"):
        raise JournalError("record_pass: a %s pass has phases dispatched, returned and refused (got %r)"
                           % (kind, phase))
    if kind in AGENT_PASS_KINDS and phase in ("dispatched", "returned") and ids is None:
        raise JournalError("record_pass: a %s pass %s row names the ids it handed over (ids=[...]); a "
                           "row that names none cannot be checked against what was admitted"
                           % (kind, phase))
    if ids is not None:
        if kind not in AGENT_PASS_KINDS and kind != "feeds":
            raise JournalError("record_pass: ids are for the reader, research and feeds passes (got "
                               "kind=%r)" % kind)
        if kind in AGENT_PASS_KINDS and phase not in ("dispatched", "returned"):
            raise JournalError("record_pass: ids are for a %s pass dispatched or returned row (got "
                               "phase=%r)" % (kind, phase))
        _check_ids("ids", ids, nonempty=kind in AGENT_PASS_KINDS)
    if unreached is not None:
        if kind not in UNREACHED_PASS_KINDS:
            raise JournalError("record_pass: unreached is for the capture and fetch passes (got kind=%r)"
                               % kind)
        _check_ids("unreached", unreached, nonempty=False)
    if phase == "refused" and reason not in REASONS:
        raise JournalError(
            "record_pass(phase='refused') requires --reason from REASONS %r (got %r)"
            % (sorted(REASONS), reason))
    if phase != "refused" and reason is not None:
        raise JournalError("record_pass: --reason is only for phase='refused' (got phase=%r)"
                           % phase)
    # dev #692 / public #140 (R4) -- the explicit JOB SEARCH token. A SEPARATE field, never one of
    # the reached surface tokens: the per-day quota counts a pass that REACHED a list surface, and
    # a pass that only ran its searches must not spend it. Only a LinkedIn `returned` row carries
    # one; the missing-ROLES check keys on `reached`.
    if jobsearch is not None:
        if kind != "linkedin" or phase != "returned":
            raise JournalError("record_pass: --jobsearch is only for a LinkedIn pass with "
                               "phase='returned' (got kind=%r phase=%r)" % (kind, phase))
        if jobsearch not in JOBSEARCH_TOKENS:
            raise JournalError("record_pass jobsearch=%r is not one of %r"
                               % (jobsearch, JOBSEARCH_TOKENS))
    # dev #770-4, owner ruling O4 (jobsearch 0.78.0) -- WHICH board-sweeper work a `board` pass
    # covers: `company` (employer career pages) or `board` (job boards and aggregators), so each kind
    # spends its own weekday slot (`posture.board_spent_on`). An EXTRA FIELD on the existing `board`
    # kind, never a new `kind`: a 0.77.0 `read()` accepts any field on a `pass` row (it validates the
    # event name and `dispatch` rows only), and its missing-ROLES check keys on `kind == "board"`, so
    # a 0.77.0 machine sharing `runs.jsonl` (ADR-012) still expects the sweep's `roles` event. A row
    # without it (any row written before 0.78.0) covered both kinds.
    if sweep is not None:
        if kind != "board":
            raise JournalError("record_pass: sweep is only for a board pass (got kind=%r)" % kind)
        if sweep not in BOARD_SWEEPS:
            raise JournalError("record_pass sweep=%r is not one of %r" % (sweep, BOARD_SWEEPS))
    # dev #770 (/jobsearch:search, jobsearch 0.78.0) -- `attended: true` marks a board pass a person
    # started on demand. It is outside the posture's schedule, so it never spends a scheduled slot
    # (`posture.board_spent_on` skips it): a Monday `/jobsearch:search boards attended` leaves
    # Tuesday's scheduled sweep due. Another EXTRA FIELD, tolerated by a 0.77.0 `read()` for the
    # reason `sweep` is (it validates the event name and `dispatch` rows only).
    if attended is not None:
        if attended is not True or kind != "board" or phase != "dispatched":
            raise JournalError("record_pass: attended=True is only for a board pass with "
                               "phase='dispatched' (got attended=%r kind=%r phase=%r)"
                               % (attended, kind, phase))
    # dev #785 / public #167 (design-sourcing-schedule.md §6, §15 N1) -- `split_days`: the split days
    # whose career pages were in a `company` dispatch's worklist, so each day spends its own slot
    # (`posture.board_spent_on(day=)`). Another EXTRA FIELD on the existing `board` kind, tolerated by an
    # older `read()` for the reason `sweep` is. Refused at WRITE unless the row is an unattended
    # `pass board dispatched` row with sweep `company`, and its value a non-empty list of DISTINCT weekday
    # names in weekday order -- the shape `posture.check_split_days` demands when the journal is read.
    # `None` means "not given" (the field is omitted: every split day, as a pre-0.81.0 row); `[]` is
    # refused, never read as "not given".
    if split_days is not None:
        if kind != "board" or phase != "dispatched" or sweep != "company" or attended:
            raise JournalError(
                "record_pass: split_days is only for an unattended board pass with phase='dispatched' "
                "and sweep='company' (got kind=%r phase=%r sweep=%r attended=%r)"
                % (kind, phase, sweep, attended))
        if (not isinstance(split_days, (list, tuple)) or not split_days
                or any(not isinstance(d, str) or d not in SPLIT_WEEKDAYS for d in split_days)
                or len(set(split_days)) != len(split_days)
                or list(split_days) != sorted(split_days, key=SPLIT_WEEKDAYS.index)):
            raise JournalError(
                "record_pass split_days=%r is not a non-empty list of distinct weekday names (%s) in "
                "weekday order" % (split_days, ", ".join(SPLIT_WEEKDAYS)))
    # dev #812 / public #169 (design §4, §15 N13) -- a `recorded` row says how `linkedin_sweep.py
    # record` judged a SWEEP hand-back. LinkedIn only, and every one of its five fields is required;
    # on any other phase they are refused, never stored (a field on a row that is not a record is not
    # a record of anything).
    recorded_fields = dict(verdict=verdict, faults=faults, kept=kept, concluded=concluded,
                           not_concluded=not_concluded)
    if phase == "recorded":
        if kind != "linkedin":
            raise JournalError("record_pass: phase='recorded' is only for a LinkedIn pass "
                               "(got kind=%r)" % kind)
        missing = sorted(k for k, v in recorded_fields.items() if v is None)
        if missing:
            raise JournalError("record_pass(phase='recorded') requires %s (missing: %s)"
                               % (", ".join(sorted(recorded_fields)), ", ".join(missing)))
        check_recorded_fields(verdict, faults, kept, concluded, not_concluded)
    else:
        given = sorted(k for k, v in recorded_fields.items() if v is not None)
        if given:
            raise JournalError("record_pass: %s only for phase='recorded' (got phase=%r)"
                               % (", ".join(given), phase))
    # dev #826 / public #177 -- the pane account. All three or none; a `recorded` LinkedIn row only.
    pane_fields = dict(pane=pane, mode=mode, partial=partial)
    given_pane = sorted(k for k, v in pane_fields.items() if v is not None)
    if given_pane:
        if kind != "linkedin" or phase != "recorded":
            raise JournalError("record_pass: %s only for a LinkedIn pass with phase='recorded' (got kind=%r "
                               "phase=%r)" % (", ".join(given_pane), kind, phase))
        if len(given_pane) != 3:
            raise JournalError("record_pass: pane, mode and partial go together (missing: %s)"
                               % ", ".join(sorted(set(pane_fields) - set(given_pane))))
        if pane not in PASS_PANE_STATES:
            raise JournalError("record_pass pane=%r is not one of %r" % (pane, PASS_PANE_STATES))
        if mode not in PASS_PANE_MODES:
            raise JournalError("record_pass mode=%r is not one of %r" % (mode, PASS_PANE_MODES))
        if (pane == "unreported") != (mode == "unreported"):
            raise JournalError("record_pass: mode 'unreported' goes with pane 'unreported' and only with it "
                               "(got pane=%r mode=%r)" % (pane, mode))
        if pane == "hidden" and mode != "hidden":
            raise JournalError("record_pass: pane 'hidden' requires mode 'hidden' (a hidden pane is read "
                               "without clicks); got mode=%r" % (mode,))
        if (not isinstance(partial, (list, tuple))
                or any(not isinstance(t, str) for t in partial)
                or len(set(partial)) != len(partial)):
            raise JournalError("record_pass partial=%r is not a list of distinct surface tokens" % (partial,))
        bad = sorted(set(partial) - LINKEDIN_SWEEP_SURFACES)
        if bad:
            raise JournalError("record_pass partial=%r is not in LINKEDIN_SWEEP_SURFACES %r"
                               % (bad, sorted(LINKEDIN_SWEEP_SURFACES)))
        stray = sorted(set(partial) - set(reached or []))
        if stray:
            raise JournalError("record_pass partial=%r names a surface that was not reached (reached=%r)"
                               % (stray, list(reached or [])))
    # dev #811 / public #170 (design §5.3) -- `channels`: the ids of the combined worklist one
    # `channels_due.py --board-decision` call handed the board sweeper, on its `dispatched` row, so
    # `deferred.add_roles` can ask which of them the hand-back accounts for (`board_worklist`). An
    # EXTRA FIELD on the existing `board` kind, tolerated by an older `read()` for the reason `sweep` is.
    if channels is not None:
        if kind != "board" or phase not in ("dispatched", "batch"):
            raise JournalError("record_pass: channels is only for a board pass with "
                               "phase='dispatched' or 'batch' (got kind=%r phase=%r)" % (kind, phase))
        _check_channels(channels)
    reached = list(reached) if reached is not None else []
    unreachable = list(unreachable) if unreachable is not None else []
    not_attempted = list(not_attempted) if not_attempted is not None else []
    if kind == "linkedin":
        for label, tokens in (("reached", reached), ("unreachable", unreachable),
                              ("not_attempted", not_attempted)):
            bad = sorted(set(tokens) - LINKEDIN_SWEEP_SURFACES)
            if bad:
                raise JournalError(
                    "record_pass %s=%r is not in LINKEDIN_SWEEP_SURFACES %r"
                    % (label, bad, sorted(LINKEDIN_SWEEP_SURFACES)))
    rec = {"event": "pass", "run_id": run_id, "kind": kind, "phase": phase,
           "reached": reached, "unreachable": unreachable, "not_attempted": not_attempted,
           "reason": reason or "", "at": at}
    if jobsearch is not None:
        rec["jobsearch"] = jobsearch
    if sweep is not None:
        rec["sweep"] = sweep
    if attended:
        rec["attended"] = True
    if split_days is not None:
        rec["split_days"] = list(split_days)
    if phase == "recorded":
        rec.update(verdict=verdict, faults=faults, kept=kept, concluded=concluded,
                   not_concluded=not_concluded)
    if channels is not None:
        rec["channels"] = list(channels)
    if phase == "batch":
        rec.update(batch=batch, of=of, t0_utc=t0_utc)
    if phase == "batch-end":
        rec.update(state=state, handed=handed, worklist=worklist)
        if code is not None:
            rec["code"] = code
    if owned_elsewhere is not None:
        rec["owned_elsewhere"] = {c: dict(v) for c, v in sorted(owned_elsewhere.items())}
    if given_pane:
        rec.update(pane=pane, mode=mode, partial=list(partial))
    if ids is not None:
        rec["ids"] = list(ids)
    if kind in UNREACHED_PASS_KINDS:
        rec["unreached"] = list(unreached) if unreached is not None else []
    return append(root, rec)


def record_verdict(row):
    """dev #812 / public #169 -- the verdict of a `recorded` pass row. Raises `JournalError` on a row
    that is not one, or whose verdict is outside `RECORD_VERDICTS` (a hand-edited journal): the quota
    count then fails LOUDLY rather than guessing which way an unreadable verdict should lean."""
    if row.get("event") != "pass" or row.get("phase") != "recorded":
        raise JournalError("record_verdict: not a recorded pass row: %r" % (row,))
    verdict = row.get("verdict")
    if verdict not in RECORD_VERDICTS:
        raise JournalError("a recorded pass row (run %r) carries verdict %r, which is not one of "
                           "RECORD_VERDICTS %r" % (row.get("run_id"), verdict, RECORD_VERDICTS))
    return verdict
