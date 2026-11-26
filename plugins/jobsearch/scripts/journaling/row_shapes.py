"""The strict parsers of each structured row kind (start, drain, readmit, mail-status, profile-schema, network,
companies-raised) and `_ROW_CHECKS`, the table `journal_file.read` checks every row against; the profile-pin version
pattern.

Capability module of `journal.py` (S4a, moved unedited)."""

import datetime
import re
from journaling.search_rows import (
    check_matching_block,
    check_roles_new_fields,
    check_search_on_row,
    check_search_page_row,
    check_search_pass_row,
    check_skip_row,
    check_warning_row,
)
from journaling.tables import JournalError


_MACHINE_RE = re.compile(r"^[0-9a-f]{32}$")
_OFFSET_RE = re.compile(r"^[+-](?:[01]\d|2[0-3]):[0-5]\d$")


# ⭐⭐ dev #834 (jobsearch 0.86.0; design-network-first.md sections 12.1, 13.1, 14.2) -- THE PROFILE PIN.
#
# A `profile-schema` journal event, `{event, at, min_engine, by}`, says "this profile carries shapes an engine
# older than `min_engine` cannot read". It is a JOURNAL event on purpose: the only stop jobsearch 0.83.0-0.85.0
# honour is `journal.read` raising on an event it does not know, so a pin that is anything else (a stamp, a config
# key) would stop none of them. 0.86.0 and later consult THIS pin, never the `.jobsearch-schema` stamp, for the
# forward refusal.
#
# THE PIN IS READ TWO WAYS, AND THE DIFFERENCE IS LOAD-BEARING:
#   `pin_scan(root)`      TOLERANT. Line by line, ignoring every line that does not parse or is not a
#                         `profile-schema` event, and NOTHING else is validated. Why: a LATER engine may add an event
#                         this engine does not know, and the strict reader would raise "unknown event" before it
#                         reached the pin, so the refusal would name the unknown event instead of the pin.
#   `profile_pin(recs)`   the same answer over rows `read()` already returned (the migration's success condition).
# `pin_refusal(root)` is the sentence both `read()` and `append()` raise with when the pin is above this engine, so a
# 0.86.0 machine on a 0.87.0 profile writes nothing and stops at its first journal call (V1).
PIN_EVENT = "profile-schema"
PIN_FIELDS = ("event", "at", "min_engine", "by")
_PIN_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _pin_ver(v):
    """`(major, minor, patch)` for an `X.Y.Z` string, else None (never raises: the tolerant scan ignores a pin it
    cannot parse, and the strict row check refuses one)."""
    m = _PIN_VER_RE.match(v) if isinstance(v, str) else None
    return tuple(int(g) for g in m.groups()) if m else None


# dev #820 / public #175 (design-role-pipeline.md section 4.5, 17) -- the `drain` event: one `planned`
# when a run admits its intake, one `closed` when it checks every admitted role finished (and at most one
# MORE, written on its behalf by the next run when it died). CLOSED vocabularies, validated at write and
# again at read. `lifecycle.CAUSES` is these plus the three causes `stage()` derives and never stores.
DRAIN_PHASES = ("planned", "closed")
CAPACITY_REASONS = ("no-render-route", "time-bound")
DRAIN_RUN_CAUSES = ("run-died", "cause-not-recorded", "not-dispatched", "deadline-reached")
DRAIN_ROLE_CAUSES = ("agent-returned-nothing", "capture-refused", "challenge", "render-failed",
                     "surface-cannot-read", "site-not-allowed")
# 0.85.0 (dev #839 / public #182, dev #840 / public #181; design-hidden-pane-reads.md sections 7.1, 10): a third cause
# class. The page was never read (the Browser pane was hidden, or the reader's tab stayed in the background), so the
# cause is neither the run's fault nor the role's: it breaks both retry-stop chains and counts toward neither.
DRAIN_ENV_CAUSES = ("pane-hidden",)
DRAIN_CLOSE_CAUSES = DRAIN_RUN_CAUSES + DRAIN_ROLE_CAUSES + DRAIN_ENV_CAUSES
# The admission classes. `held` (0.85.0) is a role whose read could not happen for an ENVIRONMENT cause: it waits
# behind retry, returned and legacy, and new roles keep their reserved share ahead of it. The 0.84.0 reader's key set
# is the first four: a stored `admitted_by_class` carries EITHER those four OR those plus `held`, and 0.85.0 WRITES
# `held` ONLY WHEN IT IS NON-ZERO (a journal that never held a role stays readable by 0.84.0).
DRAIN_CLASSES = ("retry", "returned", "legacy", "held", "new")
DRAIN_CLASSES_084 = ("retry", "returned", "legacy", "new")
# ⚠️ ROLLBACK RISK, STATED (0.85.0): an engine older than 0.85.0 raises on any journal holding a `held` admission
# class, a `readmit` event or an environment-class close cause (`read()` refuses them), so after one run on this
# version an older version cannot read this profile's journal. It is the 0.82.0 cutover's accepted behaviour (the
# older machine "stops at the journal read"); `lifecycle.process_report`'s `ENGINE SKEW` line shows it on the newer
# machine. The break starts at the FIRST `held` admission, environment close or `readmit` event, not at upgrade.
# The 0.85.0 release note says: upgrade every machine that shares the profile.
RENDER_ROUTES = ("yes", "no")
DRAIN_PLANNED_FIELDS = ("intake", "capacity", "render_route", "attended", "admitted", "waiting",
                        "retry_stopped", "fanout", "solo", "fetch_calls", "reserved_new",
                        "admitted_by_class", "excluded_open")


def _is_int(v, lo=0, hi=None):
    return isinstance(v, int) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)


def _id_list(label, v, what="drain"):
    if (not isinstance(v, list) or any(not isinstance(i, str) or not i or re.search(r"\s", i) for i in v)
            or len(set(v)) != len(v)):
        raise JournalError("%s %s=%r is not a list of distinct ids (non-empty strings without "
                           "whitespace)" % (what, label, v))


DRAIN_COMPANIES_FIELDS = ("setting", "admitted", "considered", "capped", "split")


def _check_companies_block(c):
    """dev #834 (design-network-first.md 3.5) -- the shape of the `companies` block a `drain planned` event may carry (0.86.0:
    intake is counted in COMPANIES, and the figures sit BESIDE the role fields, which keep their 0.83.0 meaning). Exactly the
    five keys `setting`, `admitted`, `considered`, `capped`, `split`: `setting` an int 1..100; `admitted` and `split` lists of
    distinct company ids with `split` a subset of `admitted`; `considered` an int >= len(admitted); `capped` an int with
    0 <= capped <= considered - len(admitted). ONE function, called by the reader (`_check_drain_row`) and by `record_drain`
    BEFORE it appends, so a row the reader would refuse is never written. A legacy `planned` event with no block is a
    role-unit plan and reads as before."""
    if not isinstance(c, dict) or set(c) != set(DRAIN_COMPANIES_FIELDS):
        raise JournalError("drain planned companies must be exactly {%s} -- got %r"
                           % (", ".join(DRAIN_COMPANIES_FIELDS), c))
    if not _is_int(c["setting"], 1, 100):
        raise JournalError("drain planned companies.setting=%r is not 1..100" % (c["setting"],))
    _id_list("companies.admitted", c["admitted"])
    _id_list("companies.split", c["split"])
    if not set(c["split"]) <= set(c["admitted"]):
        raise JournalError("drain planned companies.split %r names a company that is not in companies.admitted %r"
                           % (c["split"], c["admitted"]))
    n = len(c["admitted"])
    if not _is_int(c["considered"]) or c["considered"] < n:
        raise JournalError("drain planned companies.considered=%r is not an integer >= len(admitted) (%d)"
                           % (c["considered"], n))
    if not _is_int(c["capped"]) or c["capped"] > c["considered"] - n:
        raise JournalError("drain planned companies.capped=%r is not 0..considered-admitted (%d)"
                           % (c["capped"], c["considered"] - n))


def _check_drain_row(rec):
    """The shape of a `drain` event, for the writer and the reader alike. Raises `JournalError`."""
    phase = rec.get("phase")
    if phase not in DRAIN_PHASES:
        raise JournalError("drain phase %r is not one of %r" % (phase, DRAIN_PHASES))
    if not isinstance(rec.get("run_id"), str) or not rec["run_id"]:
        raise JournalError("drain requires run_id")
    if phase == "planned":
        if rec.get("on_behalf_of") is not None:
            raise JournalError("drain planned: a plan is the run's own act (on_behalf_of is for a close)")
        missing = [k for k in DRAIN_PLANNED_FIELDS if rec.get(k) is None]
        if missing:
            raise JournalError("drain planned is missing %s" % ", ".join(missing))
        if not _is_int(rec["intake"], 1, 300):
            raise JournalError("drain planned intake=%r is not 1..300" % (rec["intake"],))
        if not _is_int(rec["capacity"], 0) or rec["capacity"] > rec["intake"]:
            raise JournalError("drain planned capacity=%r is not 0..intake (%r)" % (rec["capacity"], rec["intake"]))
        reason = rec.get("capacity_reason")
        if rec["capacity"] < rec["intake"]:
            if reason not in CAPACITY_REASONS:
                raise JournalError("drain planned capacity %r is below intake %r, so capacity_reason must be "
                                   "one of %r (got %r): a cut is never silent"
                                   % (rec["capacity"], rec["intake"], CAPACITY_REASONS, reason))
        elif reason is not None:
            raise JournalError("drain planned capacity_reason %r with capacity == intake" % (reason,))
        if rec["render_route"] not in RENDER_ROUTES:
            raise JournalError("drain planned render_route %r is not one of %r" % (rec["render_route"], RENDER_ROUTES))
        if rec["render_route"] == "no" and rec["capacity"] != 0:
            raise JournalError("drain planned: no render route admits nothing (capacity must be 0)")
        if not isinstance(rec["attended"], bool):
            raise JournalError("drain planned attended=%r is not a boolean" % (rec["attended"],))
        adm = rec["admitted"]
        if not isinstance(adm, dict) or set(adm) != {"opps", "items"}:
            raise JournalError("drain planned admitted must be {opps: [...], items: [...]} -- got %r" % (adm,))
        _id_list("admitted.opps", adm["opps"])
        _id_list("admitted.items", adm["items"])
        w = rec["waiting"]
        if (not isinstance(w, dict) or set(w) != {"count", "oldest"} or not _is_int(w["count"])
                or not (w["oldest"] is None or re.match(r"^\d{4}-\d{2}-\d{2}$", str(w["oldest"])))):
            raise JournalError("drain planned waiting must be {count: n, oldest: date|null} -- got %r" % (w,))
        _id_list("retry_stopped", rec["retry_stopped"])
        _id_list("solo", rec["solo"])
        if not _is_int(rec["fanout"], 1) or not _is_int(rec["fetch_calls"]) or not _is_int(rec["reserved_new"]):
            raise JournalError("drain planned fanout/fetch_calls/reserved_new are not non-negative integers")
        byc = rec["admitted_by_class"]
        if (not isinstance(byc, dict) or set(byc) not in (set(DRAIN_CLASSES), set(DRAIN_CLASSES_084))
                or any(not _is_int(v) for v in byc.values())):
            raise JournalError("drain planned admitted_by_class must be {%s: n} (`held` is optional: a missing "
                               "one reads as 0) -- got %r" % (", ".join(DRAIN_CLASSES_084), byc))
        if sum(byc.values()) > rec["capacity"]:
            raise JournalError("drain planned admits %d roles with capacity %d" % (sum(byc.values()), rec["capacity"]))
        ex = rec["excluded_open"]
        if not isinstance(ex, dict) or any(not isinstance(k, str) or not k or not _is_int(v, 1) for k, v in ex.items()):
            raise JournalError("drain planned excluded_open must be {run id: count >= 1} -- got %r" % (ex,))
        for k in ("finished", "left", "elapsed_s", "per_role_s"):
            if rec.get(k) is not None:
                raise JournalError("drain planned carries %s, which belongs to a close" % k)
        if "companies" in rec:
            _check_companies_block(rec["companies"])
        if "matching" in rec:                                # jobsearch 0.94.0 (dev 1062, design 4.1): the lane's own figures
            check_matching_block(rec["matching"], rec)
        return
    # --- closed ---
    for k in DRAIN_PLANNED_FIELDS + ("capacity_reason", "companies", "matching"):
        if k != "admitted" and rec.get(k) is not None:       # `admitted` is a count here, a map in a plan
            raise JournalError("drain closed carries %s, which belongs to a plan" % k)
    if not _is_int(rec.get("admitted")) or not _is_int(rec.get("finished")) or rec["finished"] > rec["admitted"]:
        raise JournalError("drain closed needs integers 0 <= finished <= admitted (got admitted=%r finished=%r)"
                           % (rec.get("admitted"), rec.get("finished")))
    left = rec.get("left")
    if not isinstance(left, dict):
        raise JournalError("drain closed left must be {id: cause} -- got %r" % (left,))
    for i, cause in left.items():
        if not isinstance(i, str) or not i or re.search(r"\s", i):
            raise JournalError("drain closed left has the id %r (a non-empty string without whitespace)" % (i,))
        if cause not in DRAIN_CLOSE_CAUSES:
            raise JournalError("drain closed left[%r]=%r is not a cause a close may record (%s); "
                               "retry-stopped, legacy-backlog and unclassified are derived, never stored"
                               % (i, cause, ", ".join(DRAIN_CLOSE_CAUSES)))
    if rec["finished"] + len(left) != rec["admitted"]:
        raise JournalError("drain closed: admitted=%d but finished=%d + left=%d -- every admitted role "
                           "finished or has a cause" % (rec["admitted"], rec["finished"], len(left)))
    obh = rec.get("on_behalf_of")
    if obh is not None:
        if not isinstance(obh, str) or not obh or obh == rec["run_id"]:
            raise JournalError("drain closed on_behalf_of=%r must name ANOTHER run" % (obh,))
        for k in ("elapsed_s", "per_role_s"):
            if rec.get(k) is not None:
                raise JournalError("drain closed on behalf of %s carries %s: a close written for a dead "
                                   "run measures nothing" % (obh, k))
    else:
        if rec.get("elapsed_s") is not None and not _is_int(rec["elapsed_s"]):
            raise JournalError("drain closed elapsed_s=%r is not a non-negative integer" % (rec["elapsed_s"],))
        prs = rec.get("per_role_s")
        if prs is not None and (isinstance(prs, bool) or not isinstance(prs, (int, float)) or prs < 0):
            raise JournalError("drain closed per_role_s=%r is not a non-negative number" % (prs,))


# jobsearch 0.85.0 (dev #840 / public #181; design-hidden-pane-reads.md sections 9, 10) -- the `readmit` event: roles a
# migration put back into intake because their stop was counted under rules that did not know the cause. One
# event, appended once by `record_readmit` (the ONLY writer), naming the role ids. `lifecycle.Ctx.working()` drops
# every admission planned at or before it for those ids; it reads two events of the same `by` as ONE (the union of
# the ids, at the earliest `at`), so two machines that each ran the migration before syncing cannot re-admit twice.
READMIT_FIELDS = ("event", "at", "by", "cause", "ids")
_READMIT_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _check_readmit_row(rec):
    """The shape of a `readmit` event, for the writer and the reader alike. Raises `JournalError`."""
    unknown = sorted(set(rec) - set(READMIT_FIELDS))
    missing = [k for k in READMIT_FIELDS if k not in rec]
    if unknown:
        raise JournalError("readmit has unknown field(s) %s" % ", ".join(unknown))
    if missing:
        raise JournalError("readmit is missing field(s) %s" % ", ".join(missing))
    at = rec["at"]
    if not isinstance(at, str) or not _READMIT_AT_RE.match(at):
        raise JournalError("readmit at=%r is not an ISO date and time" % (at,))
    try:
        datetime.datetime.fromisoformat(at)
    except ValueError:
        raise JournalError("readmit at=%r is not a real date and time" % (at,))
    by = rec["by"]
    if not isinstance(by, str) or not by or re.search(r"\s", by):
        raise JournalError("readmit by=%r is not a non-empty name without whitespace" % (by,))
    if rec["cause"] not in DRAIN_ROLE_CAUSES:
        raise JournalError("readmit cause=%r is not a role-class cause (%s)"
                           % (rec["cause"], ", ".join(DRAIN_ROLE_CAUSES)))
    if not isinstance(rec["ids"], list) or not rec["ids"]:
        raise JournalError("readmit ids=%r must be a non-empty list: a re-admit of nothing is not an event"
                           % (rec["ids"],))
    _id_list("ids", rec["ids"], what="readmit")


MAIL_CLASSES = ("ats-status", "human", "digest", "noise")
MAIL_UNMATCHED_CAP = 200


def _check_mail_status_row(rec):
    if not isinstance(rec.get("run_id"), str) or not rec["run_id"]:
        raise JournalError("mail-status requires run_id")
    mb = rec.get("mailbox")
    if not isinstance(mb, str) or not mb.strip():
        raise JournalError("mail-status mailbox %r is not a non-empty string" % (mb,))
    counts = rec.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(MAIL_CLASSES) \
            or any(not _is_int(v) for v in counts.values()):
        raise JournalError("mail-status counts must be {%s: n >= 0} (every class, no other) -- got %r"
                           % (", ".join(MAIL_CLASSES), counts))
    un = rec.get("unmatched")
    if not isinstance(un, list):
        raise JournalError("mail-status unmatched must be a list -- got %r" % (un,))
    for u in un:
        if (not isinstance(u, dict) or set(u) != {"source", "subject"}
                or not isinstance(u["source"], str) or not u["source"].strip()
                or not isinstance(u["subject"], str)
                or len(u["source"]) > MAIL_UNMATCHED_CAP or len(u["subject"]) > MAIL_UNMATCHED_CAP):
            raise JournalError("mail-status unmatched entries are {source, subject}, each at most %d "
                               "characters, source non-empty -- got %r" % (MAIL_UNMATCHED_CAP, u))
    if len(un) > counts["ats-status"]:
        raise JournalError("mail-status: %d unmatched but only %d ats-status messages -- an unmatched "
                           "message is an ats-status one that matched no application"
                           % (len(un), counts["ats-status"]))


def _check_start_row(rec):
    """dev #836 (N14): the three optional fields a `start` carries. TOLERANT OF ABSENCE (every older start lacks them, and
    a missing field means "not measured"), STRICT ON SHAPE: `machine` a 32-hex id, `dirty_at_start` a list of non-empty
    strings, `utc_offset` `+HH:MM`. A malformed one is refused at write and at read, naming the field, so a hand edit never
    turns into a quiet "nothing was left"."""
    m = rec.get("machine")
    if "machine" in rec and not (isinstance(m, str) and _MACHINE_RE.match(m)):
        raise JournalError("start machine=%r is not a 32-character hex id" % (m,))
    d = rec.get("dirty_at_start")
    if "dirty_at_start" in rec and not (isinstance(d, list) and all(isinstance(x, str) and x for x in d)):
        raise JournalError("start dirty_at_start must be a list of non-empty path strings -- got %r" % (d,))
    o = rec.get("utc_offset")
    if "utc_offset" in rec and not (isinstance(o, str) and _OFFSET_RE.match(o)):
        raise JournalError("start utc_offset=%r is not +HH:MM" % (o,))


# the event -> its row check, read by `read()` (a row of one of these events is validated when it is read)
_ROW_CHECKS = {"start": _check_start_row, "drain": _check_drain_row, "mail-status": _check_mail_status_row, "readmit": _check_readmit_row,
               "profile-schema": lambda rec: _check_profile_schema_row(rec),
               "network": lambda rec: _check_network_row(rec),
               "companies-raised": lambda rec: _check_companies_raised_row(rec),
               # jobsearch 0.94.0 (dev 1065, 1055; design 8.1, 19.6): a `pass` row's `scope: search` half and a `roles` event's new optional
               # fields are checked when present (a row without them is every row written before 0.94.0), and the three LinkedIn search events.
               "pass": check_search_pass_row, "roles": check_roles_new_fields, "linkedin-search-skip": check_skip_row,
               "linkedin-warning": check_warning_row, "linkedin-search-on": check_search_on_row,
               "linkedin-search-page": check_search_page_row}


def _check_profile_schema_row(rec):
    """dev #834 -- the shape of a `profile-schema` (pin) event, for the writer and the reader alike: exactly
    `{event, at, min_engine, by}`, `min_engine` an `X.Y.Z` string, `by` a name without whitespace."""
    unknown = sorted(set(rec) - set(PIN_FIELDS))
    missing = [k for k in PIN_FIELDS if k not in rec]
    if unknown:
        raise JournalError("profile-schema has unknown field(s) %s" % ", ".join(unknown))
    if missing:
        raise JournalError("profile-schema is missing field(s) %s" % ", ".join(missing))
    if _pin_ver(rec["min_engine"]) is None:
        raise JournalError("profile-schema min_engine=%r is not X.Y.Z" % (rec["min_engine"],))
    at = rec["at"]
    if not isinstance(at, str) or not _READMIT_AT_RE.match(at):
        raise JournalError("profile-schema at=%r is not an ISO date and time" % (at,))
    by = rec["by"]
    if not isinstance(by, str) or not by or re.search(r"\s", by):
        raise JournalError("profile-schema by=%r is not a non-empty name without whitespace" % (by,))


NETWORK_FIELDS = ("event", "at", "run_id", "week", "budget", "open_drafts", "sent_this_week", "planned")
_ISO_WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


def _check_network_row(rec):
    """dev #834 -- the shape of a `network` event (one per run that worked the network block): exactly
    `{event, at, run_id, week, budget, open_drafts, sent_this_week, planned}`, the four counts ints >= 0, `week`
    an ISO week `YYYY-Www`. The funnel's weeks-at-budget reads these, so a week counts only when the block ran in
    it, against the budget recorded that week."""
    unknown = sorted(set(rec) - set(NETWORK_FIELDS))
    missing = [k for k in NETWORK_FIELDS if k not in rec]
    if unknown:
        raise JournalError("network has unknown field(s) %s" % ", ".join(unknown))
    if missing:
        raise JournalError("network is missing field(s) %s" % ", ".join(missing))
    at = rec["at"]
    if not isinstance(at, str) or not _READMIT_AT_RE.match(at):
        raise JournalError("network at=%r is not an ISO date and time" % (at,))
    if not isinstance(rec["run_id"], str) or not rec["run_id"].strip():
        raise JournalError("network run_id=%r is not a non-empty string" % (rec["run_id"],))
    if not isinstance(rec["week"], str) or not _ISO_WEEK_RE.match(rec["week"]):
        raise JournalError("network week=%r is not an ISO week YYYY-Www" % (rec["week"],))
    for k in ("budget", "open_drafts", "sent_this_week", "planned"):
        if not _is_int(rec[k]):
            raise JournalError("network %s=%r is not an int >= 0" % (k, rec[k]))


COMPANIES_RAISED_FIELDS = ("event", "at", "run_id", "setting", "raised", "waiting")
# jobsearch 0.92.0 (dev #950, docs/design-decision-surface.md §C.3): `held` is OPTIONAL, `{"undecided", "watching", "passed": n}`
# (exactly those three keys, each an int >= 0), the roles held for a company decision when the step ran (opportunities only).
# Its writer writes it only on a profile pinned at 0.92.0, so an engine that refuses an unknown field never meets it.
COMPANIES_RAISED_OPTIONAL = ("held",)
HELD_KEYS = ("undecided", "watching", "passed")


def _check_companies_raised_row(rec):
    """dev #834 (design-network-first.md 3.3) -- the shape of a `companies-raised` event, for the writer and the reader alike:
    exactly `{event, at, run_id, setting, raised, waiting}`, plus the optional `held` (0.92.0, above). `setting` is `search.companies_raised_per_run` (0.93.0, dev #1021; before, `search.company_intake_per_run`) as it read when the
    step ran (int 1..100); `raised` the company ids newly raised this run (distinct, non-empty, whitespace-free, at most
    `setting`); `waiting` the qualifying companies still unraised (int >= 0). It is written EVEN WHEN `raised` is empty, so
    "the step ran and raised nothing" differs from "the step never ran"."""
    unknown = sorted(set(rec) - set(COMPANIES_RAISED_FIELDS) - set(COMPANIES_RAISED_OPTIONAL))
    missing = [k for k in COMPANIES_RAISED_FIELDS if k not in rec]
    if unknown:
        raise JournalError("companies-raised has unknown field(s) %s" % ", ".join(unknown))
    if missing:
        raise JournalError("companies-raised is missing field(s) %s" % ", ".join(missing))
    at = rec["at"]
    if not isinstance(at, str) or not _READMIT_AT_RE.match(at):
        raise JournalError("companies-raised at=%r is not an ISO date and time" % (at,))
    if not isinstance(rec["run_id"], str) or not rec["run_id"].strip():
        raise JournalError("companies-raised run_id=%r is not a non-empty string" % (rec["run_id"],))
    if not _is_int(rec["setting"], 1, 100):
        raise JournalError("companies-raised setting=%r is not 1..100" % (rec["setting"],))
    _id_list("raised", rec["raised"], what="companies-raised")
    if len(rec["raised"]) > rec["setting"]:
        raise JournalError("companies-raised raised %d companies with a setting of %d: a run never raises more than "
                           "the setting" % (len(rec["raised"]), rec["setting"]))
    if not _is_int(rec["waiting"]):
        raise JournalError("companies-raised waiting=%r is not an int >= 0" % (rec["waiting"],))
    if "held" in rec:
        held = rec["held"]
        if not isinstance(held, dict) or sorted(held) != sorted(HELD_KEYS) or not all(_is_int(held[k]) for k in HELD_KEYS):
            raise JournalError("companies-raised held=%r is not {undecided, watching, passed} of ints >= 0" % (held,))
