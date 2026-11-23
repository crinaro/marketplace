"""Network-store checks: person resolution, ties, chats, `via`, proposals and suggestion asks.

Capability module of `validate_data.py` (S4a, moved unedited)."""

import config_keys as _config_keys
import datetime
import re
from validation.basics import is_date
from validation.vocab import (
    ATTENDANCE,
    COMMITMENT_KINDS,
    CONCEPTUAL_AGREEMENT_LISTS,
    CURRENCY_RE,
    EMPLOYMENT_KEYS,
    EMPLOYMENT_OWNED_FIELDS,
    EMPLOYMENT_SOURCES,
    EMPLOYMENT_STATUS,
    FOLLOW_CONTROL_TYPES,
    FORMERLY_KEYS,
    PROPOSAL_NEEDS_SENT_ON,
    PROPOSAL_STATUS,
    RATE_PER,
    SLUG_RE,
    SUGGEST_COMPANY_KEYS,
    SUGGEST_OPS,
    SUGGEST_PERSON_KEYS,
    SUGGEST_PLAN_SUBJECT_KINDS,
    SUGGEST_SHAPE_KEYS,
    TIE_KINDS,
    TIE_VIA_PERSON,
    BUILD_KINDS,
    BUILD_KIND_SHAPE,
)


def resolve_person(pid, merged_into):
    """The person a (possibly merged) id stands for: follow `merged_into` to the survivor. Cycle-safe (a cycle is its own problem,
    reported by the people loop), so this never loops: it stops at the first id it has seen."""
    seen = set()
    while pid in merged_into and pid not in seen:
        seen.add(pid)
        pid = merged_into[pid]
    return pid


def _relative_path_problem(v):
    """`None` when `v` is a relative path inside the profile (no `..` component, not absolute, not `~`-rooted), else why not."""
    if not (isinstance(v, str) and v.strip()):
        return "must be a non-empty relative path"
    if v.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:[\\/]", v):
        return "must be relative to the profile root, not absolute"
    if ".." in re.split(r"[\\/]", v):
        return "must not contain a `..` component"
    return None


def check_ties(r, label, problems, company_ids=None, people=None):
    """dev #834 (design-network-first.md 4.3): `people.ties` is absent (unknown: never "no ties") or a list of `{kind, via?}` where `kind`
    is one of TIE_KINDS and `via`, when present, is a non-empty string. Any other key in an entry, a non-list, or an entry that is not an
    object is refused: the field is the candidate's own statement, and a malformed one must be loud, not read as "knows no one".

    jobsearch 0.91.0: given `company_ids` (the companies store's ids), the row's employment fields are checked too
    (`check_employment`), so `validate_data.py`'s people loop keeps one call per row for the person's network fields. Given `people`
    (the whole people store), a `via` that begins `person:` must name a living (non-merged) people row other than this one: that
    one spelling gates a message ("X suggested I connect with you", design-build-reach.md 6.3), so it gets a strict parser; any
    other `via` stays free text."""
    if people is not None:
        _check_via_people(r, label, problems, people)
    if company_ids is not None:
        check_employment(r, label, problems, company_ids)
    if "ties" not in r:
        return
    ties = r["ties"]
    if not isinstance(ties, list):
        problems.append("%s: ties must be a list of {kind, via?} (or absent when unknown), got %r" % (label, ties))
        return
    for i, e in enumerate(ties):
        if not isinstance(e, dict):
            problems.append("%s: ties[%d] must be an object {kind, via?}, got %r" % (label, i, e))
            continue
        extra = sorted(set(e) - {"kind", "via"})
        if extra:
            problems.append("%s: ties[%d] has unknown key(s) %s -- an entry is {kind, via?}" % (label, i, ", ".join(extra)))
        if e.get("kind") not in TIE_KINDS:
            problems.append("%s: ties[%d].kind %r is not one of %s" % (label, i, e.get("kind"), "/".join(TIE_KINDS)))
        if "via" in e and not (isinstance(e["via"], str) and e["via"].strip()):
            problems.append("%s: ties[%d].via must be a non-empty string when present, got %r" % (label, i, e["via"]))


def _check_via_people(r, label, problems, people):
    """A `ties[].via` of `person:<id>` must name a living people row that is not `r` itself (see `check_ties`)."""
    ties = r.get("ties")
    if not isinstance(ties, list):
        return
    living = {p.get("id") for p in people if isinstance(p, dict) and p.get("status") != "merged"}
    for i, e in enumerate(ties):
        via = e.get("via") if isinstance(e, dict) else None
        if not (isinstance(via, str) and via.startswith(TIE_VIA_PERSON)):
            continue
        pid = via[len(TIE_VIA_PERSON):].strip()
        if pid not in living:
            problems.append("%s: ties[%d].via %r names no living people row (a merged or unknown id never stands for who introduced "
                            "this person; record that person first, or write the via as plain text)" % (label, i, via))
        elif pid == r.get("id"):
            problems.append("%s: ties[%d].via %r names this person themself" % (label, i, via))


def check_touch_build(t, label, problems, company_ids, involvements):
    """A touch's object company and its `build_kind` (jobsearch 0.91.0, design-build-reach.md 6.2). `object_company_id`, when set,
    must resolve. `build_kind`, when set, is one of BUILD_KINDS and fits its touch: `advice-ask` is a `first-touch` with no `opp_id`
    and an `object_company_id`; `side-door` is an `intro-request` with an `opp_id` and an `object_company_id` whose recipient holds a
    `side-contact` involvement on that role. A wrong shape is refused, never read as "not from a BUILD line": the field is what the
    week's counts and `access._open_intros` read."""
    check_follow_control(t, label, problems)                      # 0.92.0: the stop / resume control rows
    ocid = t.get("object_company_id")
    if ocid is not None and ocid not in company_ids:
        problems.append("%s: object_company_id %r does not resolve" % (label, ocid))
    bk = t.get("build_kind")
    if bk is None:
        return
    if bk not in BUILD_KINDS:
        problems.append("%s: build_kind %r is not one of %s (absent means not from a BUILD line)" % (label, bk, "/".join(BUILD_KINDS)))
        return
    want = BUILD_KIND_SHAPE[bk]
    if t.get("touch_type") != want:
        problems.append("%s: build_kind %r belongs on a `%s` touch, not %r" % (label, bk, want, t.get("touch_type")))
    if not ocid:
        problems.append("%s: build_kind %r needs object_company_id (the company the BUILD line is for)" % (label, bk))
    if bk == "advice-ask" and t.get("opp_id"):
        problems.append("%s: build_kind 'advice-ask' carries no opp_id (an advice ask is about a company, not a role)" % label)
    if bk == "side-door":
        oid = t.get("opp_id")
        side = any(isinstance(i, dict) and i.get("opp_id") == oid and i.get("person_id") == t.get("person_id")
                   and i.get("path_type") == "side-contact" for i in involvements or ()) if oid else False
        if not oid:
            problems.append("%s: build_kind 'side-door' needs the opp_id of the role the ask is about" % label)
        elif not side:
            problems.append("%s: build_kind 'side-door' needs a recipient holding a `side-contact` involvement on %r" % (label, oid))


# The fields a follow-control row must leave empty (design-decision-surface.md B.1): no role, no channel, nothing it is about, no
# message, no reply and no cause. These are what keep the row out of every reader that joins on a role or counts a send.
FOLLOW_CONTROL_EMPTY = ("opp_id", "channel_id", "object_person_id", "object_company_id", "message_ref", "responded_on",
                        "trigger_kind", "trigger_ref", "build_kind")


def check_follow_control(t, label, problems):
    """A `stop-following` / `resume-following` touch (jobsearch 0.92.0, dev #951, design-decision-surface.md B.1) is a control row,
    never outreach: `status` declined, `medium` other, `outcome` null or n/a, an ISO-day `date`, every field of
    FOLLOW_CONTROL_EMPTY empty, and on a stop an int `inbound_seen` >= 0 (the inbound stored within a day of the stop when it was
    written). Any other row carrying `inbound_seen` is refused: the field belongs to the stop alone. A bool is not an int here."""
    kind = t.get("touch_type")
    if kind not in FOLLOW_CONTROL_TYPES:
        if "inbound_seen" in t:
            problems.append("%s: inbound_seen belongs only on a stop-following row (written by `record.py stop-following`), "
                            "not on a %r touch" % (label, kind))
        return
    for fld, want in (("status", ("declined",)), ("medium", ("other",)), ("outcome", (None, "n/a"))):
        if t.get(fld) not in want:
            problems.append("%s: a %s row has %s %s, got %r" % (label, kind, fld, " or ".join(str(w) for w in want), t.get(fld)))
    if not is_date(t.get("date") or ""):
        problems.append("%s: a %s row's date is an ISO day (YYYY-MM-DD), got %r" % (label, kind, t.get("date")))
    for fld in FOLLOW_CONTROL_EMPTY:
        if t.get(fld) not in (None, ""):
            problems.append("%s: a %s row carries no %s (it is a control row, not outreach), got %r" % (label, kind, fld, t.get(fld)))
    seen = t.get("inbound_seen")
    if kind == "stop-following":
        if isinstance(seen, bool) or not isinstance(seen, int) or seen < 0:
            problems.append("%s: a stop-following row's inbound_seen is an integer of 0 or more, got %r" % (label, seen))
    elif "inbound_seen" in t:
        problems.append("%s: inbound_seen belongs only on a stop-following row, not on %s" % (label, kind))


def check_employment(r, label, problems, company_ids):
    """jobsearch 0.91.0 (design-build-reach.md 5.2, owner O2): `people.employment` is absent or `{status, as_of, confirmed_on?, source}` on
    the employer of record (`company_id`), and `people.formerly` is absent or a list of `{company_id, as_of, until?, counted_from?}`.

      employment  requires `company_id`. `status` is `current` or `unknown`; a stored `former` is refused, because "used to work there"
                  has one spelling, an entry in `formerly`. `as_of` is the ISO date the engine learned a `current` (required) and null
                  for `unknown`; `confirmed_on`, when set, is a date no earlier than `as_of`, on a `current` only; `source` is one of
                  EMPLOYMENT_SOURCES. Null is not a spelling of "not stated": the field is absent then.
      formerly    each entry's `company_id` resolves, appears once in the list, and differs from the row's own `company_id`; `as_of`
                  (the day the departure was learned) is a date; `until` (as the candidate states it, display only) and
                  `counted_from` (the `employment.as_of` the row carried while current there) are dates or null, and
                  `counted_from <= as_of`.

    Absent `employment` is legal on any row: a row with no employer of record, or one the 0.91.0 migration has not reached yet (every
    reader treats it as `unknown`). The rule that a NEW row with a `company_id` states it is `record.py create`'s
    (`recording.employment.stamp_people_create`), not this whole-store check's."""
    if "employment" in r:
        _check_employment_object(r, label, problems)
    if "formerly" not in r:
        return
    formerly = r["formerly"]
    if not isinstance(formerly, list):
        problems.append("%s: formerly must be a list of {company_id, as_of, until?, counted_from?} (or absent), got %r" % (label, formerly))
        return
    seen = set()
    for i, f in enumerate(formerly):
        fl = "%s: formerly[%d]" % (label, i)
        if not isinstance(f, dict):
            problems.append("%s must be an object {company_id, as_of, until?, counted_from?}, got %r" % (fl, f))
            continue
        extra = sorted(set(f) - FORMERLY_KEYS)
        if extra:
            problems.append("%s has unknown key(s) %s" % (fl, ", ".join(extra)))
        cid = f.get("company_id")
        if cid not in company_ids:
            problems.append("%s.company_id %r does not resolve" % (fl, cid))
        if cid in seen:
            problems.append("%s.company_id %r appears twice: one entry per former employer" % (fl, cid))
        seen.add(cid)
        if cid is not None and cid == r.get("company_id"):
            problems.append("%s.company_id %r is also the employer of record: a person is current or former at a company, never both"
                            % (fl, cid))
        if not is_date(f.get("as_of")):
            problems.append("%s.as_of %r must be the ISO date the departure was learned" % (fl, f.get("as_of")))
        for k in ("until", "counted_from"):
            if f.get(k) is not None and not is_date(f.get(k)):
                problems.append("%s.%s %r must be an ISO date or null" % (fl, k, f.get(k)))
        if is_date(f.get("counted_from")) and is_date(f.get("as_of")) and f["counted_from"] > f["as_of"]:
            problems.append("%s.counted_from %s is after its as_of %s" % (fl, f["counted_from"], f["as_of"]))


def _check_employment_object(r, label, problems):
    """The `employment` object of one people row (see `check_employment`)."""
    e = r["employment"]
    if not isinstance(e, dict):
        problems.append("%s: employment must be an object {status, as_of, confirmed_on?, source} (absent when not stated), got %r"
                        % (label, e))
        return
    extra = sorted(set(e) - EMPLOYMENT_KEYS)
    if extra:
        problems.append("%s: employment has unknown key(s) %s" % (label, ", ".join(extra)))
    if not r.get("company_id"):
        problems.append("%s: employment requires company_id: it describes the employer of record" % label)
    status = e.get("status")
    if status == "former":
        problems.append("%s: employment.status 'former' is refused: a past employer is an entry in formerly "
                        "(`record.py employment <id> former` moves it there)" % label)
    elif status not in EMPLOYMENT_STATUS:
        problems.append("%s: employment.status %r is not one of %s" % (label, status, "/".join(EMPLOYMENT_STATUS)))
    if e.get("source") not in EMPLOYMENT_SOURCES:
        problems.append("%s: employment.source %r is not one of %s" % (label, e.get("source"), "/".join(EMPLOYMENT_SOURCES)))
    if status == "current" and not is_date(e.get("as_of")):
        problems.append("%s: employment.as_of %r: a current standing needs the ISO date it was learned" % (label, e.get("as_of")))
    if status == "unknown" and e.get("as_of") is not None:
        problems.append("%s: employment.as_of must be null for an unknown standing, got %r" % (label, e.get("as_of")))
    conf = e.get("confirmed_on")
    if conf is not None:
        if status != "current":
            problems.append("%s: employment.confirmed_on is a re-confirmation of a current standing; this one is %r" % (label, status))
        elif not is_date(conf):
            problems.append("%s: employment.confirmed_on %r must be an ISO date or null" % (label, conf))
        elif is_date(e.get("as_of")) and conf < e["as_of"]:
            problems.append("%s: employment.confirmed_on %s is before its as_of %s" % (label, conf, e["as_of"]))


def employment_owned_refusal(op, before_row, after_row):
    """The refusals (messages; empty when none) for a write of `op` that CHANGES an employment-owned field (EMPLOYMENT_OWNED_FIELDS:
    `company_id`, `employment`, `formerly`) of an EXISTING people row. Those fields are written only by `record.py employment`,
    `record.py moved` and `record.py merge-person`, which date what they learn (jobsearch 0.91.0, design-build-reach.md 5.2: no verb
    takes a date for `as_of`); none of them passes through this check. Called by `recording.row_checks.verb_owned_refusal`, so a
    `set`, `set-in` or `append` that would hand-write a standing, or move a person's employer without moving the standing with it,
    is refused before a byte lands. A `create` states the first standing through `recording.employment.stamp_people_create`."""
    out = []
    for f in EMPLOYMENT_OWNED_FIELDS:
        if (before_row or {}).get(f) != (after_row or {}).get(f):
            out.append("people.%s is written only by `record.py employment <person_id> current|unknown|former [--left YYYY-MM-DD]`, "
                       "`record.py moved <person_id> --to <company_id> [--left YYYY-MM-DD]` and `record.py merge-person ... "
                       "[--current <company_id|none>]`, which date what they learn; `%s` cannot change it, and --force does not "
                       "lift this" % (f, op))
    return out


def check_chat_fields(r, label, problems, people_ids, company_ids, touch_by_id, merged_into, today=None):
    """dev #834 (jobsearch 0.86.0, design-network-first.md 5.2, 13.1): the fields a CHAT widens `commitments` with. Every one is
    optional; an absent field means "not recorded" and is never read as a value (a legacy meeting has none of them).

      person_id     FK people (a merged row resolves). REQUIRED when `kind` is `chat`: a chat is with someone
      kind          `chat` | `interview`
      touch_id      FK touches: the `meeting-booked` touch this chat came from, and that touch's person must equal `person_id`
                    after merge resolution (so a booking is joined to its chat, never to someone else's)
      attendance    `held` | `no-show`, only on a commitment dated on or before today, and only with `attendance_on` (ISO)
      attendance_on written WITH `attendance`, never alone
      notes_ref     a relative path (no `..`, not absolute); a missing FILE is a checkup warning, never a validator problem
      intros_given  a list of `{person_id?, company_id?, on?}`; each names at least one FK and every FK resolves"""
    today = today or datetime.date.today().isoformat()
    pid = r.get("person_id")
    if "person_id" in r and pid is not None and not (isinstance(pid, str) and pid in people_ids):
        problems.append("%s: person_id %r does not resolve to any people row" % (label, pid))
    kind = r.get("kind")
    if "kind" in r and kind is not None and kind not in COMMITMENT_KINDS:
        problems.append("%s: kind %r is not one of %s (absent means a legacy meeting not yet classified)"
                        % (label, kind, "/".join(sorted(COMMITMENT_KINDS))))
    if kind == "chat" and not pid:
        problems.append("%s: a `kind: chat` commitment needs `person_id` -- a chat is with someone (record it with `record.py chat "
                        "<person_id> --on <date>`)" % label)
    if kind == "event":           # 0.91.0 (design-build-reach.md 6.5): a public event, from its own page, with nobody named
        src = r.get("source")
        if pid:
            problems.append("%s: a `kind: event` commitment names no person (an event is a place to meet people, not a chat)" % label)
        if not (isinstance(src, str) and src.startswith(("https://", "http://"))):
            problems.append("%s: a `kind: event` commitment needs `source`, the event page's address -- got %r" % (label, src))
    tid = r.get("touch_id")
    if "touch_id" in r and tid is not None:
        t = touch_by_id.get(tid) if isinstance(tid, str) else None
        if t is None:
            problems.append("%s: touch_id %r does not resolve to any touches row" % (label, tid))
        elif t.get("outcome") != "meeting-booked":
            problems.append("%s: touch_id %r is not a `meeting-booked` touch (its outcome is %r)" % (label, tid, t.get("outcome")))
        elif not pid:
            problems.append("%s: touch_id %r needs the commitment's `person_id`: a booking is joined to the chat with the SAME "
                            "person" % (label, tid))
        elif resolve_person(t.get("person_id"), merged_into) != resolve_person(pid, merged_into):
            problems.append("%s: touch_id %r is a touch to %r, but this chat is with %r (they are not the same person after "
                            "merges)" % (label, tid, t.get("person_id"), pid))
    att = r.get("attendance")
    if "attendance" in r and att is not None:
        if att not in ATTENDANCE:
            problems.append("%s: attendance %r is not one of %s (absent means unrecorded)"
                            % (label, att, "/".join(sorted(ATTENDANCE))))
        d = r.get("date")
        if not (is_date(d) and d <= today):
            problems.append("%s: attendance %r on a commitment dated %r: a meeting that has not happened yet has no attendance"
                            % (label, att, d))
        if not is_date(r.get("attendance_on")):
            problems.append("%s: attendance needs `attendance_on` (an ISO date), written with it" % label)
    if r.get("attendance_on") is not None:
        if att is None:
            problems.append("%s: attendance_on without attendance -- the date is written WITH the attendance, never alone" % label)
        elif not is_date(r.get("attendance_on")):
            problems.append("%s: attendance_on must be an ISO date (YYYY-MM-DD) -- %r" % (label, r["attendance_on"]))
    if "notes_ref" in r and r["notes_ref"] is not None:
        why = _relative_path_problem(r["notes_ref"])
        if why:
            problems.append("%s: notes_ref %s -- %r" % (label, why, r["notes_ref"]))
    if "intros_given" in r and r["intros_given"] is not None:
        ig = r["intros_given"]
        if not isinstance(ig, list):
            problems.append("%s: intros_given must be a list of {person_id?, company_id?, on?}, got %s"
                            % (label, type(ig).__name__))
            ig = []
        for j, e in enumerate(ig):
            il = "%s.intros_given[%d]" % (label, j)
            if not isinstance(e, dict):
                problems.append("%s: entry is %s, not an object" % (il, type(e).__name__))
                continue
            extra = set(e) - {"person_id", "company_id", "on"}
            if extra:
                problems.append("%s: unknown key(s) %s (an entry is {person_id?, company_id?, on?})"
                                % (il, ", ".join(sorted(extra))))
            if not (e.get("person_id") or e.get("company_id")):
                problems.append("%s: names neither person_id nor company_id -- an introduction is to someone or to somewhere" % il)
            if e.get("person_id") and e["person_id"] not in people_ids:
                problems.append("%s: person_id %r does not resolve to any people row" % (il, e["person_id"]))
            if e.get("company_id") and e["company_id"] not in company_ids:
                problems.append("%s: company_id %r does not resolve to any company" % (il, e["company_id"]))
            if e.get("on") is not None and not is_date(e["on"]):
                problems.append("%s: on must be an ISO date (YYYY-MM-DD) -- %r" % (il, e["on"]))


def check_via_fields(r, label, problems, people_ids, commitment_by_id, merged_into):
    """dev #834 (jobsearch 0.86.0, design-network-first.md 5.3): where a role or an application CAME FROM, as a person and/or a
    conversation. Both are nullable foreign keys on `opportunities` and `applications`:

      via_person_id      FK people
      via_commitment_id  FK commitments (the chat that surfaced it)

    When BOTH are set the chat must be with that person: the commitment's `person_id` equals `via_person_id` after merge
    resolution, so a role is never credited to a conversation with somebody else. A commitment that names NO person cannot make that
    claim and is refused beside a `via_person_id` (record the person on the chat first). Absent on both means "source not recorded",
    reported as such and never inferred from a recent chat."""
    vp, vc = r.get("via_person_id"), r.get("via_commitment_id")
    if vp is not None and not (isinstance(vp, str) and vp in people_ids):
        problems.append("%s: via_person_id %r does not resolve to any people row" % (label, vp))
    cm = None
    if vc is not None:
        cm = commitment_by_id.get(vc) if isinstance(vc, str) else None
        if cm is None:
            problems.append("%s: via_commitment_id %r does not resolve to any commitments row" % (label, vc))
    if vp is not None and cm is not None and vp in people_ids:
        cp = cm.get("person_id")
        if not cp:
            problems.append("%s: via_commitment_id %r names no person, so it cannot be the conversation with via_person_id %r "
                            "(record the person on the chat first)" % (label, vc, vp))
        elif resolve_person(cp, merged_into) != resolve_person(vp, merged_into):
            problems.append("%s: via_commitment_id %r is a conversation with %r, but via_person_id is %r (they are not the same "
                            "person after merges)" % (label, vc, cp, vp))


def check_proposal_row(r, label, problems, opp_by_id, ids_seen):
    """dev #834 (jobsearch 0.86.0, design-network-first.md 6, owner ruling 3): one row of `proposals`, a proposal to a prospective
    client of a non-employee engagement. The rules, each a problem naming the field and the verb that writes it:

      id                 required, unique, a lowercase slug (minted `<opp_id>-pN` by `record.py proposal`)
      opp_id             required FK to an opportunity whose `engagement_type` is one of `config_keys.ENGAGEMENT_NON_EMPLOYEE`
                         (`fractional`, `interim`, `advisory`, `contract`): a full-time role's path is `applications`
      status             one of PROPOSAL_STATUS; `status_on` is an ISO date, written with every status
      date            an ISO date or null; REQUIRED for `sent`, `accepted`, `declined` and `expired` (each presupposes the proposal went
                         out), and never after `status_on`
      conceptual_agreement  null, or `{on, objectives[], measures[], value[]}`: each list non-empty, of non-empty strings, `on` ISO and no
                         unknown key (the client agreed what success looks like BEFORE the proposal; the proposal confirms, it does not
                         explore)
      rate               null, or `{amount, per, currency}`: `amount` a positive number, `per` one of RATE_PER, `currency` three
                         upper-case letters
      scope, doc_ref, note   a non-empty string or null (`doc_ref` a relative path, never absolute and never with `..`)"""
    pid = r.get("id")
    if pid is not None:
        if not (isinstance(pid, str) and SLUG_RE.match(pid)):
            problems.append("%s: id %r must be a lowercase slug (minted as <opp_id>-pN by `record.py proposal`)" % (label, pid))
        elif pid in ids_seen:
            problems.append("%s: duplicate id" % label)
        ids_seen.add(pid)
    oid = r.get("opp_id")
    if oid is not None:
        opp = opp_by_id.get(oid) if isinstance(oid, str) else None
        if opp is None:
            problems.append("%s: opp_id %r does not resolve to any opportunity" % (label, oid))
        elif opp.get("engagement_type") not in _config_keys.ENGAGEMENT_NON_EMPLOYEE:
            problems.append("%s: opportunity %r has engagement_type %r, and a proposal belongs to one of %s (a full-time role's path is "
                            "`applications`; set the engagement first: record.py set %s engagement_type <type>)"
                            % (label, oid, opp.get("engagement_type"), "/".join(_config_keys.ENGAGEMENT_NON_EMPLOYEE), oid))
    st = r.get("status")
    if st is not None and st not in PROPOSAL_STATUS:
        problems.append("%s: status %r is not one of %s" % (label, st, "/".join(PROPOSAL_STATUS)))
    if "status_on" in r and not is_date(r.get("status_on")):
        problems.append("%s: status_on must be an ISO date (YYYY-MM-DD), written with every status -- %r" % (label, r.get("status_on")))
    so = r.get("date")
    if so is not None and not is_date(so):
        problems.append("%s: date must be an ISO date (YYYY-MM-DD) or null -- %r" % (label, so))
    if st in PROPOSAL_NEEDS_SENT_ON and so is None:
        problems.append("%s: status %r needs `date` -- the day the proposal went out (record.py proposal-status %s %s --on <date>)"
                        % (label, st, pid, st))
    if is_date(so) and is_date(r.get("status_on")) and so > r["status_on"]:
        problems.append("%s: date %s is after status_on %s" % (label, so, r["status_on"]))
    ca = r.get("conceptual_agreement")
    if ca is not None:
        if not isinstance(ca, dict):
            problems.append("%s: conceptual_agreement must be an object {on, objectives[], measures[], value[]} or null, got %s"
                            % (label, type(ca).__name__))
        else:
            extra = set(ca) - {"on", *CONCEPTUAL_AGREEMENT_LISTS}
            if extra:
                problems.append("%s: conceptual_agreement has unknown key(s) %s (it is {on, objectives, measures, value})"
                                % (label, ", ".join(sorted(extra))))
            if not is_date(ca.get("on")):
                problems.append("%s: conceptual_agreement.on must be an ISO date -- the day the client agreed it" % label)
            for f in CONCEPTUAL_AGREEMENT_LISTS:
                v = ca.get(f)
                if not (isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v)):
                    problems.append("%s: conceptual_agreement.%s must be a non-empty list of non-empty strings -- %r (what the client "
                                    "agreed BEFORE the proposal)" % (label, f, v))
    rate = r.get("rate")
    if rate is not None:
        if not isinstance(rate, dict):
            problems.append("%s: rate must be an object {amount, per, currency} or null, got %s" % (label, type(rate).__name__))
        else:
            extra = set(rate) - {"amount", "per", "currency"}
            if extra:
                problems.append("%s: rate has unknown key(s) %s (it is {amount, per, currency})" % (label, ", ".join(sorted(extra))))
            amt = rate.get("amount")
            if not (isinstance(amt, (int, float)) and not isinstance(amt, bool) and amt > 0):
                problems.append("%s: rate.amount must be a positive number -- %r" % (label, amt))
            if rate.get("per") not in RATE_PER:
                problems.append("%s: rate.per %r is not one of %s" % (label, rate.get("per"), "/".join(RATE_PER)))
            if not (isinstance(rate.get("currency"), str) and CURRENCY_RE.match(rate["currency"])):
                problems.append("%s: rate.currency must be three upper-case letters (e.g. USD) -- %r" % (label, rate.get("currency")))
    for f in ("scope", "note"):
        if f in r and r[f] is not None and not (isinstance(r[f], str) and r[f].strip()):
            problems.append("%s: %s must be a non-empty string or null -- %r" % (label, f, r[f]))
    if "doc_ref" in r and r["doc_ref"] is not None:
        why = _relative_path_problem(r["doc_ref"])
        if why:
            problems.append("%s: doc_ref %s -- %r" % (label, why, r["doc_ref"]))


def check_suggestion_ask(r, label, problems, plan_fields):
    """dev #834 (jobsearch 0.86.0, design-network-first.md 8.2): an ask of `kind: suggestion` carries `suggests`, the one write it stands
    for, and nothing has written that row yet. `plan_fields` is the plan model's field list (a plan suggestion's closed key set).

      suggests.store / .op   one of SUGGEST_OPS: companies `set`, plans `create`, people `set`
      suggests.id            the target row's id (a `create` names the id the new row will take)
      suggests.fields        a non-empty object; the keys are closed per store (a company: status, motivation, and `status` can only
                             be `active-target`; a person: cadence; a plan: the plan model's fields, with a `subject_kind` of search,
                             company or person)
      suggests.before        optional: the values the target's fields held when the suggestion was made (`confirm` refuses when they
                             have changed); each key is one of `fields`' keys

    ⚠️ What is checked is the ask's OWN shape, never the stores it points at. A suggestion whose target has since been deleted, merged
    away or created by hand is STALE, not corrupt: `record.py confirm` refuses it naming why, and `record.py decline` closes it. A
    validator problem here would refuse the candidate's own legitimate write (creating the plan by hand, say) because an unanswered
    question sat open, and would leave the whole profile reading invalid over a decision nobody has taken."""
    s = r.get("suggests")
    if r.get("kind") != "suggestion":
        if s is not None:
            problems.append("%s: `suggests` belongs to `kind: suggestion` asks only (this one is %r)" % (label, r.get("kind")))
        return
    if not isinstance(s, dict):
        problems.append("%s: a `kind: suggestion` ask needs `suggests` {store, op, id, fields} -- the write it asks the owner to confirm"
                        % label)
        return
    extra = set(s) - SUGGEST_SHAPE_KEYS
    if extra:
        problems.append("%s: suggests has unknown key(s) %s (it is {store, op, id, fields, before})" % (label, ", ".join(sorted(extra))))
    store, op = s.get("store"), s.get("op")
    if (store, op) not in SUGGEST_OPS:
        problems.append("%s: suggests names %r %r, which is not a suggestable write (one of %s); a person row itself is never "
                        "suggested" % (label, store, op, ", ".join("%s %s" % (a, b) for a, b in sorted(SUGGEST_OPS))))
        return
    tid, fields = s.get("id"), s.get("fields")
    if not (isinstance(tid, str) and tid.strip()):
        problems.append("%s: suggests.id must name the target row" % label)
    if not (isinstance(fields, dict) and fields):
        problems.append("%s: suggests.fields must be a non-empty object" % label)
        return
    allowed = {"companies": SUGGEST_COMPANY_KEYS, "people": SUGGEST_PERSON_KEYS}.get(store) or set(plan_fields)
    bad = sorted(set(fields) - set(allowed))
    if bad:
        problems.append("%s: suggests.fields names %s, which a %s suggestion may not carry (allowed: %s)"
                        % (label, ", ".join(bad), store, ", ".join(sorted(allowed))))
    if store == "companies" and "status" in fields and fields["status"] != "active-target":
        problems.append("%s: a company suggestion proposes `status: active-target` -- got %r" % (label, fields["status"]))
    if store == "plans" and fields.get("subject_kind") not in SUGGEST_PLAN_SUBJECT_KINDS:
        problems.append("%s: a plan suggestion's subject_kind must be one of %s -- got %r"
                        % (label, "/".join(sorted(SUGGEST_PLAN_SUBJECT_KINDS)), fields.get("subject_kind")))
    before = s.get("before")
    if before is not None:
        if not isinstance(before, dict) or set(before) - set(fields):
            problems.append("%s: suggests.before must be an object whose keys are among suggests.fields' keys" % label)
