"""checks: the row checks every writer shares: the data model (known fields, aliases, required), the whole-store
validator and its problem sets, the introduced-only rules a write may not add, the fields one verb alone writes
(with the writer tokens `employer_posting` and `jd_read` need), the dry-run validator, and the `fields` listings.

Capability module of record.py (an entry point over `recording/`)."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from recording import profile_paths as _paths
from recording.profile_paths import ENGINE_SCRIPTS
from recording.common import _plans_mod, _validator_module
from recording.store_files import STORES, _load_or_empty


# ⭐ ENGINE, not profile — the data MODEL ships with the code; the DATA belongs to the user.
MODEL_PATH = os.path.join(os.path.dirname(ENGINE_SCRIPTS), "docs", "data_model.json")


def model():
    """⭐ THE DEFINITION THE API ENFORCES — docs/data_model.json.

    Added 2026-08-04, after the candidate asked whether the API needed definitions, whether keys
    were guarded against duplicates, and whether any of it was enforced. All three were NO:
    `record.py set <id> nxet_action_owner <candidate>` wrote silently and the validator reported
    **clean**, because only outreach[] had an unknown-key guard. Three guessed contact_ids landed
    the same day.

    Validating AFTER the write was never enough. A typo is already on disk by then, and
    validate_data cannot know that `nxet_action_owner` was meant to be `next_action_owner` — to
    it, an unguarded store simply has a new field.
    """
    with open(MODEL_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def known_fields(store, array=None):
    m = model()["stores"].get(store) or {}
    if array:
        return set((m.get("arrays", {}).get(array) or {}).get("fields") or [])
    return set(m.get("fields") or [])


def check_field(store, field, array=None):
    """Returns None if fine, else the reason to refuse. Refusing BEFORE the write is the point."""
    aliases = model()["banned_aliases"]
    if field in aliases and not field.startswith("_"):
        return ("%r is a BANNED ALIAS for %r. The same meaning under two spellings means a query "
                "written against one silently misses the other." % (field, aliases[field]))
    allowed = known_fields(store, array)
    if allowed and field not in allowed:
        near = [f for f in allowed if abs(len(f) - len(field)) <= 2
                and sum(a != b for a, b in zip(sorted(f), sorted(field))) <= 3]
        hint = ("  Did you mean: %s" % ", ".join(sorted(near)[:3])) if near else ""
        where = "%s[]" % array if array else store
        return ("%r is not a field of %s.%s\n  Known: %s" %
                (field, where, hint, ", ".join(sorted(allowed))))
    return None


def validate(data_dir=None):
    """Run validate_data.py and report (returncode, stdout, stderr).

    ⭐ `data_dir` points the validator at a THROWAWAY copy instead of the real store, via
    CLAUDESEARCH_DATA_DIR — the same override validate_data.py already exposes for a fresh-
    install check. This is what lets --dry-run run the exact validator a real write runs
    (dev #143 / public #23), without the real store ever being touched.

    stderr is captured too, not discarded. A validator that CRASHES (an unguarded value-shape
    assumption, for one) prints NOTHING to stdout — its own summary is only printed after every
    check finishes — so a caller reading stdout alone sees a blank result exactly when it most
    needs an answer. See _diagnostic_lines below."""
    env = os.environ.copy()
    if data_dir:
        env["CLAUDESEARCH_DATA_DIR"] = data_dir
    # dir= is explicit: the suite requires it of every mkstemp here (the store writes must
    # stay in the store's own directory); this sidecar is not a store, so the system tmp.
    fd, sidecar = tempfile.mkstemp(dir=tempfile.gettempdir(),
                                   prefix=".validate-problems-", suffix=".json")
    os.close(fd)
    try:
        env["CLAUDESEARCH_PROBLEMS_OUT"] = sidecar
        r = subprocess.run([sys.executable, os.path.join(ENGINE_SCRIPTS, "validate_data.py")],
                           capture_output=True, text=True, env=env)
        problems = _read_problems(sidecar)
    finally:
        try:
            os.unlink(sidecar)
        except OSError:
            pass
    return r.returncode, r.stdout, r.stderr, problems


def _read_problems(path):
    """The validator's own problem list, or None when it never finished (crashed before its
    summary — the sidecar is written on every finishing path, so an empty or missing one
    means exactly that). None is an honest 'unknown', never treated as clean."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    if not text.strip():
        return None
    try:
        got = json.loads(text)
    except ValueError:
        return None
    return [str(x) for x in got] if isinstance(got, list) else None


def new_problems(pre, post):
    """The problems a write INTRODUCED — post minus pre, as sets — or None when either side is
    unknown (the validator crashed on it), which no comparison can settle.

    ⭐ THIS is the G9 fix (dev/audit 2026-09-02). The carve-out for a pre-existing failure
    used to compare EXIT CODES: with one standing problem the store returns 1 before and 1
    after any write, so a write that added a second, unrelated defect was kept under the
    first one's excuse — "already failing before" — and --dry-run refused to judge anything
    at all. One standing finding disabled the rollback for every write on every worker
    until a human dispositioned it. A set comparison sees the difference an exit code
    cannot: a write is pre-existing-only when every problem after it was already there."""
    if pre is None or post is None:
        return None
    before = set(pre)
    return [x for x in post if x not in before]


def introduced_row_violations(store, before_row, after_row):
    """The introduced-only rules (validate_data.INTRODUCED_ONLY_RULES) that a write to `store`
    NEWLY violates: `after_row` breaks them and `before_row` — the same row as it stood, or None
    for a create — did not break THAT SAME one.

    ⭐ dev #644 item 5 / dev #427. The whole-store validator only WARNS about a row that already
    exists in such a state (so a user whose history predates a rule is never locked out of their
    own store). This is the other half: a row being newly written, or changed INTO the state,
    is refused here, before anything is written. A row that was already in the state and is
    changed in some other field keeps the same message and is therefore not "introduced", so an
    unrelated edit to an old row is accepted. Messages are label-free, so they compare equal."""
    vd = _validator_module()
    gate = (_fit_unavailable_violations(store, before_row, after_row)
            + _manual_board_violations(store, before_row, after_row))
    after = vd.row_rule_violations(store, after_row)
    if not after:
        return gate
    before = set(vd.row_rule_violations(store, before_row)) if before_row is not None else set()
    return gate + [m for m in after if m not in before]


# ---- dev #776 / public #166 (design-employer-posting-confirmation.md section 6.1, 15 N1/N9): THE FIELD HAS ONE WRITER ----
#
# `opportunities[].employer_posting` says a role is confirmed on the employer's OWN posting. A model that could write it
# with `set`, `set-in`, `append` or `create` could write "confirmed" over a posting nobody opened, which is the
# defect the field exists to end. So the field is written by exactly two paths, `record.py posting --from-file` and the
# capture call inside `create --from-item` for a feed item, and every other write that changes it is REFUSED here,
# `--force` included (a flag that lifts the guard would be the second writer).
_POSTING_FIELD = "employer_posting"
# Module-private: no command-line flag, environment variable or JSON payload sets it. It is held only inside
# `_posting_writer()`, by the two sanctioned paths.
_POSTING_WRITER = [False]


@contextlib.contextmanager
def _posting_writer(held=True):
    """Hold (or, with `held=False`, explicitly not hold) the writer token for the checks inside the block."""
    prev = _POSTING_WRITER[0]
    _POSTING_WRITER[0] = bool(held)
    try:
        yield
    finally:
        _POSTING_WRITER[0] = prev


def _posting_keys(row):
    """`{key: value}` of every key of `row` that IS the field or lives under it. A dotted key (`append <id>
    employer_posting.pending ...` writes the dotted key itself, see `introduced_row_violations`' siblings) is the same
    field spelled differently, so it is compared too."""
    if not isinstance(row, dict):
        return {}
    return {k: v for k, v in row.items() if k == _POSTING_FIELD or k.startswith(_POSTING_FIELD + ".")}


def verb_owned_refusal(op, store, before_row, after_row):
    """The refusals (a list of messages, empty when none) for a write of `op` to `store` that CHANGES a field a verb
    owns when it did not come from that verb's sanctioned path. Two fields are owned:

      * `employer_posting` -- written only by `record.py posting --from-file` and the capture of a company-feed role
        (dev #776 / public #166);
      * `jd_read` -- written only by `record.py read-jd`, `read-failed`, `not-attempted` and `read-batch --fetch` (dev #820 / public
        #175, design section 4.2): a read that cannot be told from a typed one is the defect the field exists to end.

    Called at EVERY call site of `introduced_row_violations` (the four shared ones in `cmd_board_sighting` and `main`,
    and `cmd_posting`'s own), on the dry-run and the real path, so no op can bypass it; comparing the row as it stood
    with the row as it would be (`before_row` None for a create) covers `set`, `set-in`, `append`, `create` and any op
    added later without listing them.

    A key that is present with a null value differs from an absent key (`set <id> employer_posting null` is a write),
    and `--force` is not an input: the refusal text says so.

    A third field is owned on the `companies` store (jobsearch 0.86.0, dev #834, design-network-first.md 3.3):
    `raised_on`, the date a company was first raised as a "look into this company?" item, is written only by
    `record.py raise-companies`, which does not pass through this check, so EVERY other op that changes it is refused here:
    one writer per field, because a hand-set date would silently decide which companies a run still has to raise."""
    if store == "companies" and isinstance(after_row, dict):
        out = []
        if (before_row or {}).get(_RAISED_FIELD) != after_row.get(_RAISED_FIELD):
            out.append("%s is written only by `record.py raise-companies --run <run id>` (it raises at most "
                       "`search.company_intake_per_run` companies a run and journals a `companies-raised` event); `%s` cannot "
                       "change it, and --force does not lift this" % (_RAISED_FIELD, op))
        # dev #834 (design-network-first.md 3.3, 4.1): an EXISTING company's `status` and `status_on` are the candidate's decision,
        # written together by `record.py company-status` (which does not pass through this check). `status_on` is what tells an
        # answered `watching` from an unanswered one, so a hand `set <co> status watching` would leave the question looking handled.
        # A `create` (before_row None) is not a decision about an existing company, so it is not refused.
        if isinstance(before_row, dict):
            for f in _COMPANY_DECISION_FIELDS:
                if before_row.get(f) != after_row.get(f):
                    out.append("%s is the candidate's decision about a company and is written only by `record.py company-status "
                               "<company_id> active-target|watching|passed [--motivation <1-5>]` (it writes `status`, `status_on` "
                               "and `motivation` together); `%s` cannot change it, and --force does not lift this" % (f, op))
        return out
    if store == "proposals" and isinstance(after_row, dict) and isinstance(before_row, dict):
        # dev #834 (design-network-first.md 6): a proposal's lifecycle is written by `record.py proposal-status`, which dates the
        # status (`status_on`) and the day it went out (`date`) in ONE write. A hand `set <id> status accepted` would leave a
        # proposal "accepted" with no date the funnel could count it on. A `create` is not a change to an existing row.
        return ["%s is the proposal's lifecycle and is written only by `record.py proposal-status <proposal_id> "
                "sent|accepted|declined|withdrawn|expired [--on <date>]`; `%s` cannot change it, and --force does not lift this"
                % (f, op) for f in _PROPOSAL_LIFECYCLE_FIELDS if before_row.get(f) != after_row.get(f)]
    if store != "opportunities" or not isinstance(after_row, dict):
        return []
    out = []
    if not _POSTING_WRITER[0] and _posting_keys(before_row) != _posting_keys(after_row):
        out.append("%s is written only by `record.py posting --from-file <file>` (research and the scheduled re-check "
                   "write the EMPLOYER-POSTING lines it reads) and by the capture of a company-feed role; `%s` cannot "
                   "change it, and --force does not lift this" % (_POSTING_FIELD, op))
    if not _JD_READ_WRITER[0] and _jd_read_keys(before_row) != _jd_read_keys(after_row):
        out.append("%s is written only by `record.py read-jd`, `read-failed`, `not-attempted` and `read-batch --fetch` (a read is "
                   "recorded with its evidence by the verb that made it); `%s` cannot change it, and --force does "
                   "not lift this" % (_JD_READ_FIELD, op))
    return out


# ---- dev #834 (jobsearch 0.86.0): `companies.raised_on` HAS ONE WRITER, `record.py raise-companies` ----
_RAISED_FIELD = "raised_on"
# dev #834 (design-network-first.md 3.3, 4.1): the two fields of a company the candidate's DECISION writes, in one write, by
# `record.py company-status`. `motivation` is not listed: it is revised by running the verb again, and a hand edit of a number
# the candidate states is not the silent-decision hazard `status` without `status_on` is.
_COMPANY_DECISION_FIELDS = ("status", "status_on")
# dev #834 (design-network-first.md 6): the three fields of a proposal `record.py proposal-status` owns (one writer).
_PROPOSAL_LIFECYCLE_FIELDS = ("status", "status_on", "date")

# ---- dev #820 / public #175 (design-role-pipeline.md section 4.2): `jd_read` HAS ONE WRITER FAMILY ----
_JD_READ_FIELD = "jd_read"
# Module-private, like `_POSTING_WRITER`: no flag, environment variable or JSON payload sets it. It is held only inside
# `_jd_read_writer()`, by `read-jd`, `read-failed` and `read-batch --fetch`.
_JD_READ_WRITER = [False]


@contextlib.contextmanager
def _jd_read_writer(held=True):
    """Hold (or, with `held=False`, explicitly not hold) the `jd_read` writer token for the checks inside the block."""
    prev = _JD_READ_WRITER[0]
    _JD_READ_WRITER[0] = bool(held)
    try:
        yield
    finally:
        _JD_READ_WRITER[0] = prev


def _jd_read_keys(row):
    """`{key: value}` of every key of `row` that IS `jd_read` or lives under it (a dotted key is the same field spelled
    differently, so it is compared too)."""
    if not isinstance(row, dict):
        return {}
    return {k: v for k, v in row.items() if k == _JD_READ_FIELD or k.startswith(_JD_READ_FIELD + ".")}


FIT_UNAVAILABLE_PREFIX = "unavailable"
# the outcomes `read-failed` takes (jd_read.OUTCOMES minus `read`), spelled out in the refusal that points at it
READ_FAILED_REMEDY = ("`record.py read-failed <id> --run <run id> --url <u|-> --via fetch|render|feed|ats-api "
                      "--outcome closed|dead-link|manual-board|no-url|login-wall|challenge|render-failed|"
                      "surface-cannot-read|site-not-allowed --evidence \"<1-200 characters>\"`")


def _touches_fit(before_row, after_row):
    """True when a write changed any `fit` / `fit.*` key (a create counts as touching it)."""
    if not isinstance(before_row, dict):
        return True
    keys = {k for k in set(before_row) | set(after_row) if k == "fit" or k.startswith("fit.")}
    return any(before_row.get(k) != after_row.get(k) for k in keys)


def _manual_board_violations(store, before_row, after_row):
    """dev #765 (design-portfolio-boards.md, review B1) -- a JD cannot be recorded as READ when every
    address the role carries is on a `manual-candidate` channel's `board_hosts`: those sites' terms
    forbid automated access (ADR-037), so the run must not have opened them. The role records
    `read-failed --outcome manual-board` instead (dev #820 / public #175: the read record is `jd_read`, not
    `fit.jd_source`). Lives here because `introduced_row_violations` is the one choke point every write op and
    `--dry-run` passes through.

    WHEN IT FIRES: the row after the write carries a `fit.jd_source` that claims a read (a non-empty
    string not beginning `unavailable`), this write touched `fit`, and `board_hosts.jd_read_plan` finds
    NO readable address (`url` None) while at least one is on a board host. A role that also carries an
    address OFF every board host is not held: the read could have used it. A role whose `fit` this write
    leaves alone is never held, so an old row is not locked out of `decide` or any other edit. A channels
    store that cannot be read is NOT treated as one with no boards: the write is refused with
    `NOT CHECKED`."""
    if store != "opportunities" or not isinstance(after_row, dict):
        return []
    fit = after_row.get("fit")
    src = fit.get("jd_source") if isinstance(fit, dict) else None
    if not (isinstance(src, str) and src.strip()) or src.startswith(FIT_UNAVAILABLE_PREFIX):
        return []
    if not _touches_fit(before_row, after_row):
        return []                                       # this write did not touch fit
    try:
        import board_hosts as _bh
        plan = _bh.jd_read_plan(after_row, _load_or_empty("channels"))
    except (OSError, ValueError) as e:
        return ["NOT CHECKED: the channels store is unreadable (%s), so a JD read cannot be allowed" % e]
    if plan["url"] is None and plan["blocked"]:
        b = plan["blocked"][0]
        return ["fit.jd_source %r claims a read, but every address this role carries is on the manual-candidate "
                "board %r (host %s), which the engine never opens (ADR-037): record `record.py read-failed %s "
                "--outcome manual-board ...` instead" % (src, b["channel_id"], b["host"], after_row.get("id") or "<id>")]
    return []


def _fit_unavailable_violations(store, before_row, after_row):
    """dev #820 / public #175 (design-role-pipeline.md section 4.2, "Retired writes") -- `fit.jd_source` with an
    `unavailable: ...` value is REFUSED. Before 0.82.0 a read that failed was a free string on the research field
    (`unavailable: dead-link` with a placeholder requirement, accepted with no evidence), and a role could be
    marked `surface-cannot-read` only after a bound of days (`search.triage_stuck_days`, retired with the
    `triaging` state). A failed read is a `jd_read` attempt now, with its evidence and the run that made it:
    `read-failed`. The refusal names it, `--force` included.

    WHEN IT FIRES: the row after the write carries `fit.jd_source` (or the dotted key of that name) beginning
    `unavailable` AND this write touched `fit`. A write that leaves every `fit*` key alone is not this rule's
    business, so a legacy row that carries the old value is never locked out of `decide` or any other edit."""
    if store != "opportunities" or not isinstance(after_row, dict):
        return []
    fit = after_row.get("fit")
    src = fit.get("jd_source") if isinstance(fit, dict) else None
    if src is None:
        src = after_row.get("fit.jd_source")
    if not (isinstance(src, str) and src.strip().lower().startswith(FIT_UNAVAILABLE_PREFIX)):
        return []
    if not _touches_fit(before_row, after_row):
        return []
    return ["fit.jd_source %r is a retired write (jobsearch 0.82.0, dev #820): a read that failed is recorded with "
            "%s -- it keeps the evidence and the run, and the role settles to `gone`, `your-read` or a visible "
            "process failure by its outcome. `fit` records research, never a read" % (src, READ_FAILED_REMEDY)]


def dry_run_validate(store, rows, extra=None):
    """Validate `rows` AS IF they were the real store, on a disposable copy of the whole data
    directory — cross-references into companies/channels/messages/asks still resolve, and the
    real files are never opened for writing. Returns the same (rc, stdout, stderr) shape as
    validate().

    ⭐ THIS is the fix for dev #143 / public #23 failure #1: a dry-run create on an enum-invalid
    or wrongly-typed field used to report success, because --dry-run only ran check_field's
    unknown-key/required checks and stopped — it never ran validate_data.py, which is the ONLY
    thing that catches an enum violation or a value of the wrong shape. The identical input as
    a real write was refused and rolled back. A green dry-run that does not predict the real
    write is worse than no dry-run at all, so dry-run now runs the SAME validator, not a lesser
    one.

    ⭐ THE SHADOW IS SHAPED LIKE THE PROFILE, NOT LIKE A BAG OF JSONL (public #61, 0.37.1).
    The first version copied the `*.jsonl` files into a FLAT temp dir and pointed the
    validator at it. validate_data.py resolves AUTHORED files — a declared resume variant's
    page — off `dirname(DATA)`, the profile root; in a flat shadow that parent is the temp
    dir itself, so every declared variant's file-existence check failed and a dry run of a
    NO-OP write (a date field assigned the value it already held) printed that a real write
    would be refused, naming files that existed and were readable. One-directional: the real
    write validates against the real profile and succeeds, so the store was never corrupted —
    what broke was the ability to check anything before writing, and every message looked
    like a legitimate validation failure. Dormant from dev #143's shadow until a variant was
    declared.

    So the shadow is now `<tmp>/data/` with every NON-data sibling of the real data dir
    symlinked into `<tmp>/`: the validator's `dirname(DATA)` lands on a directory whose
    contents ARE the profile root's, and any future authored-file check resolves correctly
    with no second override for every fresh-install path to honour. The validator only reads,
    so a symlink is exactly as safe as the real file. (The repo rule against committed
    symlinks is about TRACKED files, which dangle in every clone; these live in a temp dir
    for one subprocess and are gone with it — they are never tracked.) A symlink failure
    raises rather than falling back to the flat shape: a shadow that silently regressed to
    the flat layout would reintroduce this exact bug and look like a validation failure."""
    base = os.path.dirname(os.path.abspath(_paths.DATA))       # the validator's own _files_base rule
    data_name = os.path.basename(os.path.abspath(_paths.DATA))
    with tempfile.TemporaryDirectory(prefix="record-dryrun-") as shadow:
        for name in os.listdir(base):
            if name == data_name:
                continue
            os.symlink(os.path.join(base, name), os.path.join(shadow, name))
        shadow_data = os.path.join(shadow, data_name)
        os.mkdir(shadow_data)
        for name in os.listdir(_paths.DATA):
            src = os.path.join(_paths.DATA, name)
            if name.endswith(".jsonl") and os.path.isfile(src):
                shutil.copy2(src, os.path.join(shadow_data, name))
        # `extra` ({store: rows}, dev #765): a verb that writes a SECOND store in the same transaction
        # (board-sighting writes companies and opportunities) shadows that store as well.
        for shadowed, shadow_rows in [(store, rows)] + sorted((extra or {}).items()):
            with open(os.path.join(shadow_data, STORES[shadowed]), "w", encoding="utf-8") as fh:
                for r in shadow_rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return validate(data_dir=shadow_data)


def _diagnostic_lines(rc, out, err):
    """The last few informative lines from a validate_data.py run — never blank.

    dev #143 / public #23 failure #2: a refused write's banner named no field, no offending
    value, no rule — even though the validator computes exactly that detail internally for most
    problems (see enum()'s message format, which this reuses verbatim by printing the
    validator's own problem lines rather than inventing a second style of message). The banner
    went blank specifically when the validator CRASHED (docs/schema.md's comp field passed as a
    non-object used to do exactly this — see validate_data.py's comp check): stdout was empty
    because nothing had been printed yet, and the traceback landed on stderr, which record.py
    was throwing away entirely. Fall back to stderr, then to the bare fact of a silent crash, so
    there is always something to act on instead of an empty line."""
    text = (out or "").strip()
    if text:
        return text.split("\n")[-6:]
    err_text = (err or "").strip()
    if err_text:
        return (["(the validator produced no output on stdout — it crashed; last lines of "
                 "its stderr:)"] + err_text.split("\n")[-6:])
    return ["(the validator exited %d with no output on stdout or stderr)" % rc]


# field -> allowed-value SET, keyed by store then field name. Every set here is a REFERENCE to
# a validate_data.py constant, never a restated literal — the values still live in exactly one
# place. ⚠️ If a future enum() call in validate_data.py covers a new field, add it here too, or
# `fields` will silently omit it: this registry is a second place that knows WHICH field maps
# to WHICH constant (unavoidable — that linkage isn't data validate_data.py exposes any other
# way), even though it duplicates no VALUES.
def _enum_registry(_vd):
    return {
        "companies": {"vertical": _vd.VERTICALS, "status": _vd.COMPANY_STATUS},
        "commitments": {"kind": _vd.COMMITMENT_KINDS, "attendance": _vd.ATTENDANCE},     # dev #834
        "channels": {"type": _vd.CHANNEL_TYPES, "review_cadence": _vd.CADENCES,
                    "access": _vd.ACCESS},
        "opportunities": {"status": _vd.OPP_STATUS, "stage": _vd.STAGES,
                          "verdict": _vd.VERDICTS, "next_action_owner": _vd.OWNERS},
        # ADR-031 B4 — `plans`/`plays` join here for the same reason `touches` did in B3: the
        # enum values live in one place (`plans.py`), never restated.
        "plans": {"subject_kind": _plans_mod().SUBJECT_KINDS, "status": _plans_mod().PLAN_STATUS,
                 "resolves_when": _plans_mod().RESOLVES_WHEN},
        "plays": {"status": _plans_mod().PLAY_STATUS},
        # ADR-031 B3 — `touches` is a top-level store now (promoted from
        # opportunities.outreach[]), so its enums move from `_array_enum_registry` below to
        # here, the same move B2 never made for applications/cover_letters (a pre-existing
        # gap this dispatch does not otherwise touch) but is worth making for the store it is
        # actually building.
        "touches": {
            "status": _vd.OUTREACH_STATUS, "outcome": _vd.OUTREACH_OUTCOME,
            "medium": _vd.MEDIA, "touch_type": _vd.TOUCH_TYPES,
            "recipient_role": _vd.RECIPIENT_ROLES, "delivery": _vd.DELIVERY,
            "address_status": _vd.ADDRESS_STATUS, "trigger_kind": _vd.TRIGGER_KINDS,
        },
    }


# (store, array-name) -> {field: allowed-value SET}. Same reference-not-restatement rule.
def _array_enum_registry(_vd):
    return {
        # ADR-031 B3 — `("opportunities", "outreach")` retired along with the array itself;
        # its enums moved to `_enum_registry`'s new `"touches"` entry above.
        ("opportunities", "contacts"): {
            "email_status": _vd.CONTACT_EMAIL_STATUS, "path_type": _vd.PATH_TYPES,
        },
        ("opportunities", "applications"): {
            "method": _vd.APPLICATION_METHODS, "status": _vd.APPLICATION_STATUS,
        },
        ("opportunities", "fit.requirements"): {
            "verdict": _vd.FIT_VERDICTS, "question_status": _vd.FIT_Q_STATUS,
        },
    }


def _object_shaped_fields(store, _vd):
    """Fields whose value is an OBJECT, not a string — the exact class of mistake the report
    cites: a comp-style field (an object with two numeric keys) rendered by `fields` as though
    it accepted free text, with nothing to tell a caller otherwise. The model file only carries
    flat field-name lists, so a caller reading just that has no way to know; state it here."""
    if store != "opportunities":
        return {}
    return {
        "comp": "object — {\"min\": number, \"max\": number}",
        "location": ("object — {\"type\": one of {%s}, \"declared\": string, "
                     "\"primary\": string}" % ", ".join(sorted(_vd.LOC_TYPES))),
        "fit": "object — {\"requirements\": [fit.requirements[] rows, below]}",
    }


def _row_checks(op, before, after, posting_ok=False, jd_read_ok=False):
    """The introduced-only rules AND `verb_owned_refusal` for one row of a batch write (`capture-batch`, `read-batch`):
    `before` is the row as it stood (None for a created one). The writer tokens are held only for the field the verb
    owns -- a capture of a company-feed item writes `employer_posting` (`posting_ok`), `read-batch` writes `jd_read`
    (`jd_read_ok`) -- so the same call refuses either field changed by anything else. The one call site of both checks
    for every batch verb, so a new batch write cannot reach a store without them."""
    with _posting_writer(posting_ok), _jd_read_writer(jd_read_ok):
        return (introduced_row_violations("opportunities", before, after)
                + verb_owned_refusal(op, "opportunities", before, after))
