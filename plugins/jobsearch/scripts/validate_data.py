#!/usr/bin/env python3
"""Validate the JSONL sourcing dataset: schema, enums, types, referential integrity.

Companion to docs/schema.md. Runs in the start-of-run hygiene step alongside
check_stale_claims / check_followups / check_sections. This is the piece that
kills the whole data-integrity bug class markdown couldn't prevent: it guarantees
every record is typed, every enum is in range, and every cross-reference resolves.

    python3 scripts/validate_data.py

Exit 0 = clean, 1 = problems found (so a caller CAN gate on it if desired).

Targets Python 3.9+ (see CLAUDE.md), stdlib only.
"""

import json
import os
import re
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import route as _route
import profile as _profile
# ⚠️ `your_move` is imported BELOW the vocabulary block, not here — see the note above
# `def load`. It reads this module's TERMINAL_OPP_STATUSES at import time, so a top-of-file
# import would hand it a half-initialised module whenever validate_data is imported first.

ROOT = _profile_root()
# ⭐ Overridable so a FRESH INSTALL can be verified (2026-08-05). A new user's very first gate run
# must pass against an EMPTY profile; if it fails they conclude the system is broken before they
# have entered anything. Same override as init_profile.py, and the same reason as
# CLAUDESEARCH_DATA_DIR on funnel_report.py: a guarantee nobody tests is a guarantee nobody has.
DATA = os.environ.get("CLAUDESEARCH_DATA_DIR") or os.path.join(ROOT, "data")
# ⭐ THE PROBLEM LIST AS DATA, NOT PROSE (dev/audit 2026-09-02, G9). record.py decides whether
# a write is kept or rolled back by comparing the problems BEFORE the write with the problems
# AFTER it — a set comparison, which needs the list itself, never a re-parse of the printed
# report and never the exit code alone (an exit code cannot tell "the same one problem" from
# "that problem plus a new one", and that is exactly how a second defect was kept under the
# first one's excuse). When this names a path, the list is written there as a JSON array —
# on EVERY finishing path, the clean one included (an empty array), so an absent file means
# the validator never finished (it crashed), which the reader treats as unknown, not as clean.
PROBLEMS_OUT = os.environ.get("CLAUDESEARCH_PROBLEMS_OUT")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VERTICALS = {"healthcare-payer", "healthcare-provider", "healthtech", "saas",
             "fintech", "insurtech", "other"}
COMPANY_STATUS = {"active-target", "watching", "passed"}
CHANNEL_TYPES = {"job-board", "aggregator", "company-site", "recruiter",
                 "referral", "alert-email"}
CADENCES = {"daily", "weekly", "biweekly", "monthly", "on-inbound"}
# `expired` added 2026-08-11 (issue #6): the posting vanished/closed before any decision was
# recorded. TERMINAL, and distinct from `passed` — "I declined this" and "it disappeared before
# I decided" are different signals wanting different remedies, and recording an expiry as a pass
# overstates the pass rate while hiding that the pipeline loses roles to expiry. Existing
# `parked` rows written as an expiry workaround are deliberately NOT reclassified: nothing can
# retroactively distinguish a genuine park from the workaround (adr-013).
OPP_STATUS = {"active-pursuit", "needs-resolution", "in-motion", "backlog", "passed", "expired"}
# ⭐⭐ THE ONE TERMINAL SET — owned HERE, imported by every renderer and check (dev/audit
# 2026-09-02, build item 1). A role is TERMINAL when it has left the funnel for good:
# declined (`passed`) or vanished (`expired`). Everything else — including `backlog`, which
# is a shelved-but-reopenable state that a newly sourced role STARTS in (your_move.py's
# `decide` group) — is live data the surfaces must still account for.
#
# The measured defect this closes: generate_dashboard.py carried its own per-file
# `_CLOSED_STATUSES = {passed, backlog, expired}` and dropped every backlog row as closed,
# while your_move.py treated backlog+undecided as the entry state and the same renderer's own
# sort key four lines below ranked backlog as live. Two files, two silent answers to one
# question. A per-file "closed" set is the inversion that let them disagree: each file named
# what IT wanted to hide. A shared TERMINAL set names what has actually ended, and anything
# a surface still wants to omit has to be a deliberate, visible choice on that surface.
TERMINAL_OPP_STATUSES = frozenset({"passed", "expired"})
STAGES = {"sourced", "contacted", "screening", "interviewing", "offer", "closed"}
# ⭐ `play_stage` — where a pursued role sits in the POST-APPLICATION PLAY (public #19 / dev
# #95). `stage` is the funnel position; the play sequence is finer-grained: which step of the
# apply-then-reach-the-recruiter play is next. It used to be encoded as numbered free-text
# markers prefixed onto `next_action`, which nothing could filter, group, count, sort or
# validate — the fourth instance of "a fact a run knows goes into the queryable store"
# (act_by, precondition.py, location 'unresolved'). ORDERED, so consumers can sort by
# sequence position rather than alphabetically.
PLAY_SEQUENCE = ("needs-application", "applied", "needs-recruiter-contact", "verify-req-live",
                 "identify-recruiter", "reach-insider", "contact-recruiter", "awaiting-reply")
# `unresolved` is the migration marker (same precedent as blocked_until and location.type): a
# play position was detected in prose but could not be structured mechanically. Valid, durable,
# and deliberately NOT part of the sequence — the way out is a human writing the real value.
PLAY_STAGES = set(PLAY_SEQUENCE) | {"unresolved"}
# Every play position from `applied` onward presupposes a submitted application on the record.
POST_APPLICATION_PLAY = set(PLAY_SEQUENCE[1:])
# applications[].status values that prove a submission actually happened.
SUBMITTED_APP_STATUS = {"submitted", "acknowledged", "rejected", "advanced"}
VERDICTS = {"pursue", "pass", "parked", "undecided"}
# `unresolved` added 2026-08-11 (issue #4): a posting that declares two settings at once (e.g.
# tagged both hybrid and remote) previously forced a silent pick, and the pick selected which
# comp floor applied. `unresolved` makes "contested — ask the employer" a representable value
# instead of an absence; the verbatim declared text goes in `location.declared` (required for
# this type), and profile.screen_comp() DECLINES to pick a tier for it (adr-013).
LOC_TYPES = {"remote", "hybrid", "onsite", "relocation", "unresolved"}
# ⭐ Never a hardcoded name. `next_action_owner` ∈ {this candidate's own token, "me"} — "me"
# means the engine/assistant acts next, the candidate's own token (read from user.json via
# profile.owner_token(), never typed here) means the human does. A previous version spelled
# that first value out as one specific candidate's own literal name — correct for exactly one
# installation and silently wrong for anyone whose profile names them anything else.
OWNERS = {_profile.owner_token(), "me"}
CONTACT_EMAIL_STATUS = {"verified-published", "verified-received", "pattern-inferred", "unknown"}
OUTREACH_STATUS = {"drafted", "staged", "sent", "declined"}
# Added 2026-07-21, per the candidate: "We should be tracking who we connected with & when
# i applied to analyze what works and what doesnt." Applications were previously
# stuffed into outreach[] with a person-shaped `to` field reading e.g.
# "<a recognizable employer> careers (direct ATS application)" -- so counting them meant string-matching
# a free-text name, and an ATS submission was indistinguishable from a networking
# note. They are different funnels with different success measures; they get
# different arrays.
APPLICATION_METHODS = {"company-ats", "linkedin-easy-apply", "recruiter-submitted",
                       "email", "referral"}
APPLICATION_STATUS = {"not-started", "started", "submitted", "acknowledged",
                      "rejected", "advanced", "withdrawn"}
# Whether outreach got a reply -- the other half of "what works".
OUTREACH_OUTCOME = {"awaiting", "replied", "no-response", "declined",
                    "meeting-booked", "accepted", "n/a"}
# `accepted` added 2026-08-02 (the candidate's Decision 2). An accepted connection request that drew
# no reply is a REAL positive signal for the connection-note medium — the candidate's own stated
# mechanism is that the accept is what unlocks a better second touch. Scoring it identically
# to "ignored" made the medium the candidate believes in look weaker than it is. Reported on its own
# line, never merged into `replied`.

# ---- Communications: HOW a message was sent, and what kind it was (added 2026-08-02) ----
# WHY: `channel_id` was carrying three meanings at once — relationship (firm:halloway-partners),
# medium (linkedin-direct), and implicitly purpose. Worse, `linkedin-direct`'s own label read
# "exec-to-exec InMail" while the 12 rows stamped with it on 7/31 were CONNECTION-REQUEST NOTES.
# Every question the candidate asked about which comms work turns on distinctions that field erased.
MEDIA = {"linkedin-connection-note", "linkedin-inmail", "linkedin-message",
         "email-cold", "email-reply", "phone", "sms", "other", "unknown"}
# ⭐ Channel ids that still EXIST in channels.jsonl but must never be used again. They resolve,
# so a referential check cannot catch them; only naming them can. Kept as rows rather than
# deleted because historical outreach still points at them and a dangling pointer is worse.
RETIRED_CHANNEL_IDS = {"linkedin-direct", "email-direct"}
TOUCH_TYPES = {"first-touch", "chase", "reply", "referral-ask", "intro-request",
               "thank-you", "reconnect", "apply-path", "unknown"}
RECIPIENT_ROLES = {"hiring-manager", "hiring-line", "talent-acquisition", "recruiter-agency",
                   "warm-contact", "peer-network", "other", "unknown"}
ADDRESS_STATUS = {"verified-published", "verified-received", "pattern-inferred", "unknown"}
# A bounce that looks like a non-reply silently poisons the only comms metric there is.
DELIVERY = {"delivered", "bounced", "unknown"}
# ---- Triggers and sequences (public #27, 2026-08-25) -------------------------------------
# WHAT CAUSED THIS TOUCH OR ASK. The measured defect: a drafted ask generated by an application
# sat in drafts.md unlinked to the opportunity whose application generated it, and stayed
# correct only because a human remembered. `trigger_kind` names the cause class; `trigger_ref`
# names the instance. 'application' resolves against the OWN record's applications[] (app_id,
# or date for pre-migration rows) — the blocked_until own-record rule, because a join to
# another record's application would say this role moved when it did not. 'reply' resolves
# against data/messages.jsonl. 'elapsed' carries the ISO date the clock started. 'manual'
# means a human decided with no recorded cause — a manual trigger carrying a ref is a
# contradiction, refused rather than guessed over.
TRIGGER_KINDS = {"application", "reply", "elapsed", "manual"}
# A multi-step play ("part A sent, part B held until the connection is accepted") was a state
# machine living in a markdown heading — nothing could query "which sequences are unblocked
# today". sequence_id groups the steps; sequence_step orders them (int, 1-based). The HOLD on
# a staged step stays in **Blocked until:** (precondition.py) — a sequence adds grouping,
# never a second way to spell a hold. scripts/trigger.py owns the joins and the daily query.
# ---- Form answers (public #27, 2026-08-25) ------------------------------------------------
# What was actually answered on an application form's own questions — reasoned out once, at
# length, and previously lost to prose, so the next equivalent form re-derived it and
# consistency across two applications to the same employer was a matter of memory. Entry keys
# are REJECTED-unknown like OUTREACH_KEYS; question_key is a shared slug so precedent is a
# join, not a search.
FORM_ANSWER_KEYS = {"question_key", "question", "answer", "answered_on"}
# Unknown keys are REJECTED. Four alias keys (sent_on, replied_on, channel, notes) drifted
# into the data precisely because nothing rejected them.
OUTREACH_KEYS = {"to", "contact_id", "channel_id", "status", "date", "responded_on", "outcome",
                 "medium", "touch_type", "recipient_role", "campaign_id", "address_status",
                 "delivery", "message_ref", "variant", "note",
                 "trigger_kind", "trigger_ref", "sequence_id", "sequence_step"}
# New required fields apply only from the cutover — backfilled history carries "unknown"
# where no contemporaneous record supports a value. Without this the validator would fail
# against 46 legacy rows on day one and get ignored.
COMMS_CUTOVER = "2026-08-02"
PATH_TYPES = {"warm-referral", "recruiter", "hiring-manager", "hiring-context", "internal", "cold"}
# JD fit analysis (added 2026-08-02, per the candidate: "how is the candidate match to the JD?").
# DATA, not a document — requirement/verdict/evidence/question is a dataset, so it lives on
# the opportunity record and is validated like everything else.
FIT_VERDICTS = {"aligned", "partial", "not-aligned", "unknown"}
FIT_Q_STATUS = {"n/a", "open", "answered"}
# ⭐ Issue #34, part 2. This used to be a hand-maintained copy of `route.py`'s vocabulary and it
# drifted: `migrate.py`'s `m_0_14_0` rewrites legacy `access` values to route.py's canonical
# requirements (`login-chrome` -> `login`, `public-bot-limited` -> `bot-limited`, per
# `route.LEGACY`), but this set never gained `login`/`bot-limited` — so a channel the ENGINE
# ITSELF just migrated failed validation immediately after. Deriving from `route.py` (its
# REQUIREMENTS plus the LEGACY values migrate.py has not yet rewritten) makes that drift
# structurally impossible instead of relying on two files being edited together.
# "manual-candidate" is not part of route.py's vocabulary (it predates the requirement/mechanism
# split and is documented in docs/schema.md) - kept here rather than silently invalidating any
# existing data that carries it. Renamed (issue #35) from a value spelling out one specific
# candidate's own name literally: zero live records used that value, so this was a rename with
# no data to migrate, not a schema change.
ACCESS = set(_route.REQUIREMENTS) | set(_route.LEGACY) | {"manual-candidate"}
# ---- Asks and commitments (dev #93 / public #21) ----------------------------------------
# The hand-authored tail of Your Move and the This Week schedule were the last state living in
# focus.md prose, where a hand-written copy of a record went stale beside the generated row.
# They are stores now: an ask is OPEN until `resolved_on` is set (views filter, so expulsion is
# structural), and a commitment's `date` may be the literal `unresolved` — the migration marker
# for a date that could not be parsed, same precedent as blocked_until and play_stage.
ASK_KINDS = {"role", "system"}
# dev #133 / public #22 — the actions record.py can resolve an ask against atomically. An
# unparseable value must be LOUD (the precondition.py rule): a resolves_when nobody can act on
# means an ask that claims it will self-resolve and never does — it looks handled and is not.
ASK_RESOLVES_WHEN = {"application", "outreach"}
UNRESOLVED = "unresolved"
# ---- Resume variants (public #26) --------------------------------------------------------
# The declared printed-resume set. The variant FILES and resume.md (the claim union) are
# authored prose; the RECORDS — which variants exist, which archetype each serves, which one
# an opportunity should receive, which one an application actually sent — live here and are
# validated like everything else. `retired` is TERMINAL: applications[] history may reference
# a retired variant forever, but an opportunity cannot PLAN to send one. Prose-level hygiene
# (claim containment against the union, staleness, orphan claims) is resume_variants.py's job;
# this validator is structure and referential integrity only.
VARIANT_STATUS = {"active", "retired"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA12_RE = re.compile(r"^[0-9a-f]{12}$")


def load(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None, ["%s does not exist" % name]
    recs, errs = [], []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError as e:
            errs.append("%s line %d: invalid JSON — %s" % (name, i, e))
    return recs, errs


def is_date(v):
    return isinstance(v, str) and DATE_RE.match(v)


# ⭐ A COMMUNICATION MAY CARRY A TIME (dev/audit 2026-09-02, Class B). Two messages on one day
# — the outreach and its same-day reply — cannot be ordered from dates alone, which is what
# made the reconcile audit assert ownership it could not know and left `responded_on >= date`
# unprovable within a day. Optional `HH:MM[:SS]` after the date, space or `T` separated.
# Deliberately NOT a widening of DATE_RE for every date field: a commitment carries its time
# in its own `time` field, and every consumer of a plain date field parses ten characters.
# Only the three communication timestamps accept it: messages[].sent_on, outreach[].date,
# outreach[].responded_on. `date_part` is what a consumer compares or parses by — never the
# raw string, which may now be longer than a date.
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def is_when(v):
    return isinstance(v, str) and TIMESTAMP_RE.match(v)


def date_part(v):
    """The ISO date of a timestamp-or-date string ('' for anything unreadable)."""
    s = str(v or "")
    return s[:10] if is_when(s) else ""


def precedes(a, b):
    """Is timestamp `a` PROVABLY before `b`? Different dates decide it; the same date decides
    it only when both carry a time. A same-day pair with a bare date on either side is
    unprovable and returns False — the ambiguity is reported by reconcile.py, never asserted
    here (the Class B rule: an order the data cannot show is not an order)."""
    da, db = date_part(a), date_part(b)
    if not (da and db):
        return False
    if da != db:
        return da < db
    sa, sb = str(a), str(b)
    return len(sa) > 10 and len(sb) > 10 and sa < sb


# ⚠️ Deliberately BELOW the vocabulary: your_move.py imports this module for
# TERMINAL_OPP_STATUSES / SUBMITTED_APP_STATUS at ITS import time, and this module imports
# your_move for parse_blocked_until (used only inside main). Whichever is imported first, the
# names each side needs at import are already bound — a top-of-file import here would hand
# your_move a half-initialised module whenever validate_data is the entry point.
import your_move as _ym  # noqa: E402


def req(rec, field, label, problems):
    if field not in rec:
        problems.append("%s: missing required field '%s'" % (label, field))
        return False
    return True


def enum(rec, field, allowed, label, problems, nullable=False):
    if field not in rec:
        problems.append("%s: missing '%s'" % (label, field))
        return
    v = rec[field]
    if v is None and nullable:
        return
    if v not in allowed:
        problems.append("%s: '%s'=%r not in {%s}" % (label, field, v, ", ".join(sorted(allowed))))


def check_trigger(row, label, problems, app_refs, sent_ids):
    """The trigger pair on an outreach row or an ask (public #27). Shared so the two call
    sites cannot drift. `app_refs` is the set of resolvable application handles for the
    record the trigger belongs to (app_id values plus dates, own-record rule); `sent_ids`
    is the message-id set for 'reply' refs. Absent pair: legal (history predates the field).
    Half a pair, a kind outside the enum, or a dangling ref: LOUD — an unreadable trigger
    looks handled and is not (the precondition.py rule)."""
    tk, tr = row.get("trigger_kind"), row.get("trigger_ref")
    if tk is None and tr is None:
        return
    if tk is None:
        problems.append("%s: trigger_ref %r without trigger_kind — half a trigger cannot be "
                        "resolved and must not look like one" % (label, tr))
        return
    if tk not in TRIGGER_KINDS:
        problems.append("%s: trigger_kind %r not in {%s}" % (label, tk,
                        ", ".join(sorted(TRIGGER_KINDS))))
        return
    if tk == "manual":
        if tr is not None:
            problems.append("%s: trigger_kind 'manual' with trigger_ref %r — manual means no "
                            "recorded cause; a ref here is a contradiction, name the real kind"
                            % (label, tr))
        return
    if not (isinstance(tr, str) and tr.strip()):
        problems.append("%s: trigger_kind %r requires a non-empty trigger_ref" % (label, tk))
        return
    if tk == "application" and tr not in app_refs:
        problems.append("%s: trigger_ref %r resolves to no applications[] row on this record "
                        "(by app_id or date) — a trigger naming an application that is not "
                        "there is the unlinked-draft defect inverted" % (label, tr))
    elif tk == "reply" and tr not in sent_ids:
        problems.append("%s: trigger_ref %r resolves to no message in data/messages.jsonl"
                        % (label, tr))
    elif tk == "elapsed" and not is_date(tr):
        problems.append("%s: trigger_kind 'elapsed' requires an ISO date trigger_ref (the day "
                        "the clock started), got %r" % (label, tr))


def emit_problems(problems):
    """Write the finished problem list to PROBLEMS_OUT as JSON, when asked. Best-effort: a
    reader that cannot find the file treats the run as unknown, which is the honest answer."""
    if not PROBLEMS_OUT:
        return
    try:
        with open(PROBLEMS_OUT, "w", encoding="utf-8") as fh:
            json.dump(list(problems), fh, ensure_ascii=False)
    except OSError:
        pass


def main():
    rc, problems = _main()
    emit_problems(problems)
    return rc


def _main():
    """(exit code, the problem list) — the list is the fact; the code is a summary of it."""
    problems = []
    companies, e = load("companies.jsonl"); problems += e or []
    channels, e = load("channels.jsonl"); problems += e or []
    opps, e = load("opportunities.jsonl"); problems += e or []

    if companies is None or channels is None or opps is None:
        # Files not created yet — this is fine before the migration lands.
        print("Data validation — dataset not present yet (pre-migration). Nothing to check.")
        return 0, []

    # every contact_id known anywhere — opportunities AND channels both carry people
    all_contact_ids = set()
    for _r in opps:
        for _c in (_r.get("contacts") or []):
            if _c.get("contact_id"):
                all_contact_ids.add(_c["contact_id"])
    for _r in (channels or []):
        for _c in (_r.get("contacts") or []):
            if _c.get("contact_id"):
                all_contact_ids.add(_c["contact_id"])

    sent_msgs, e = load("messages.jsonl"); problems += e or []
    sent_ids = set()
    for m in (sent_msgs or []):
        if m.get("id") == "_README":
            continue
        mid = m.get("id", "?")
        ml = "messages[%s]" % mid
        if mid in sent_ids:
            problems.append("%s: duplicate id" % ml)
        sent_ids.add(mid)
        for f in ("direction", "sent_on", "medium", "body"):
            if not m.get(f):
                problems.append("%s: missing required field '%s'" % (ml, f))

        # ⭐ A MESSAGE MAY BELONG TO A RELATIONSHIP RATHER THAN A ROLE (2026-08-04).
        # `opp_id` was unconditionally required, which could not express the single most
        # valuable message type in an executive search: a WARM INTRODUCTION. A run recorded two
        # real ones — a third party introducing the candidate to a search-firm partner, and that
        # partner's reply — and both failed validation because they attach to a FIRM
        # RELATIONSHIP, not to any one role. Forcing an opp_id would have been a lie; dropping
        # them would have deleted the touch that produced the meeting.
        # So: a message must anchor to SOMETHING — an opportunity or a channel — but not both
        # by force.
        if not m.get("opp_id") and not m.get("channel_id"):
            problems.append("%s: needs an anchor — set 'opp_id' for a role-specific message, or "
                            "'channel_id' for one that belongs to a relationship (a warm intro, "
                            "a recruiter thread). A message anchored to nothing is unfindable."
                            % ml)

        # ⭐ THIRD-PARTY is a real direction. A referral endorsement written BY someone else
        # ABOUT the candidate is neither inbound nor outbound — the candidate is cc'd, not a
        # participant — and it is often the highest-value artifact in the whole record.
        if m.get("direction") not in ("inbound", "outbound", "third-party", None):
            problems.append("%s: direction %r must be inbound|outbound|third-party"
                            % (ml, m.get("direction")))
        # Provenance is required: a stored body with no traceable source is an assertion,
        # not a record. Format: gmail:<account>:<uid>, or 'drafts.md' for one the candidate sent directly.
        # ⭐ A MESSAGE'S contact_id MUST RESOLVE — to an opportunity's contacts[] OR a channel's.
        # Added 2026-08-04 after THREE guessed ids passed unnoticed in one afternoon:
        # 'derek-holland' for 'derek-holland-acme', 'priya-nakamura' for
        # 'priya-nakamura-globex', and a contact anchored to the wrong firm entirely just to
        # satisfy the anchor rule. A join key that does not join is worse than no key: it makes
        # "what is the whole history with X?" silently return nothing instead of failing.
        mcid = m.get("contact_id")
        if mcid and mcid not in all_contact_ids:
            problems.append("%s: contact_id %r resolves to no contacts[] entry on any "
                            "opportunity or channel. A guessed id silently breaks every "
                            "person-level query." % (ml, mcid))
        if not m.get("source"):
            problems.append("%s: missing 'source' — a body with no provenance cannot be "
                            "re-verified against the mailbox" % ml)
        if m.get("sent_on") and not is_when(m["sent_on"]):
            problems.append("%s: sent_on is neither an ISO date nor 'YYYY-MM-DD HH:MM' — %r"
                            % (ml, m.get("sent_on")))
        # MEDIA is the OUTREACH taxonomy — it exists to answer "which of the candidate's own
        # channels works". A third-party message is not their outreach, so a plain generic is
        # correct for it and forcing e.g. 'email-cold' would corrupt the funnel denominators.
        msg_media = MEDIA | {"email"} if m.get("direction") == "third-party" else MEDIA
        if m.get("medium") and m["medium"] not in msg_media:
            problems.append("%s: medium %r not in {%s}"
                            % (ml, m["medium"], ", ".join(sorted(msg_media))))

    # ---- messages[].answers — the reply relation as a KEY (dev/audit 2026-09-02, Class B) ----
    # "Which message is this a reply to" lived in prose and in the reader's memory; the
    # reconcile audit re-derived it weekly from header dates and could not tell a same-day
    # pair apart. Optional (history stays valid); where present it must resolve, must not
    # point at itself, must answer a message of a DIFFERENT direction (a chase is not a
    # reply), and must not precede the message it answers. Second pass, so a forward
    # reference in file order is fine.
    _msg_by_id = {m.get("id"): m for m in (sent_msgs or []) if m.get("id") != "_README"}
    answered_by = {}          # answered message id -> [ids of the replies that name it]
    for m in (sent_msgs or []):
        if m.get("id") == "_README" or m.get("answers") is None:
            continue
        ml = "messages[%s]" % m.get("id", "?")
        target = m.get("answers")
        t = _msg_by_id.get(target)
        if t is None:
            problems.append("%s: answers %r resolves to no message — a reply relation that "
                            "points at nothing is worse than none" % (ml, target))
            continue
        if target == m.get("id"):
            problems.append("%s: answers itself" % ml)
            continue
        if t.get("direction") == m.get("direction"):
            problems.append("%s: answers %r but both are %r — a reply answers a message from "
                            "the other side; a follow-up in the same direction is a chase, "
                            "not a reply" % (ml, target, m.get("direction")))
        if precedes(m.get("sent_on"), t.get("sent_on")):
            problems.append("%s: answers %r but is dated %s, before the message it answers (%s)"
                            % (ml, target, m["sent_on"], t["sent_on"]))
        answered_by.setdefault(target, []).append(m.get("id"))

    # ---- resume variants (public #26) — structure + the id sets the loops below join on ----
    # Absence is legal: a single-resume profile has no resume_variants.jsonl and owes it
    # nothing. Present-but-broken is a problem like any other store.
    variants, e = load("resume_variants.jsonl")
    if variants is None:
        variants = []
    else:
        problems += e or []
    variant_ids, active_variant_ids = set(), set()
    _seen_vids = set()
    # The authored files (the union, the variant pages) live at the PROFILE root; this store
    # lives under data/. Resolve siblings off the data dir's parent so the
    # CLAUDESEARCH_DATA_DIR override keeps working.
    _files_base = os.path.dirname(os.path.abspath(DATA))
    for r in variants:
        vid = r.get("id", "?")
        label = "resume_variants[%s]" % vid
        for f in ("id", "archetype", "file", "status", "created"):
            req(r, f, label, problems)
        if r.get("id") in _seen_vids:
            problems.append("%s: duplicate id" % label)
        _seen_vids.add(r.get("id"))
        for f in ("id", "archetype"):
            v = r.get(f)
            if v is not None and not SLUG_RE.match(str(v)):
                problems.append("%s: %s %r must be a lowercase slug" % (label, f, v))
        enum(r, "status", VARIANT_STATUS, label, problems)
        if not is_date(r.get("created", "")):
            problems.append("%s: created not ISO — %r" % (label, r.get("created")))
        vf = r.get("file")
        if vf is not None:
            if not isinstance(vf, str) or not vf.strip():
                problems.append("%s: file must be a non-empty path relative to the profile "
                                "root" % label)
            elif not os.path.exists(os.path.join(_files_base, vf)):
                problems.append("%s: file %r does not exist under the profile root — a "
                                "declared variant pointing at nothing is worse than an "
                                "undeclared one, because it LOOKS first-class" % (label, vf))
        # `retired` is terminal and carries its date — the same contract as a resolved ask.
        if r.get("status") == "retired" and not is_date(r.get("retired_on") or ""):
            problems.append("%s: status 'retired' requires an ISO 'retired_on' — a terminal "
                            "state with no date cannot be audited" % label)
        if r.get("retired_on") and r.get("status") != "retired":
            problems.append("%s: retired_on set but status is %r — either retire it or drop "
                            "the date" % (label, r.get("status")))
        sha = r.get("union_sha")
        if sha is not None and not SHA12_RE.match(str(sha)):
            problems.append("%s: union_sha %r is not 12 hex chars — resume_variants.py "
                            "--stamp writes this; an unreadable stamp means staleness can "
                            "never be computed, which looks reconciled and is not"
                            % (label, sha))
        ro = r.get("union_reconciled_on")
        if ro is not None and not is_date(ro):
            problems.append("%s: union_reconciled_on not ISO — %r" % (label, ro))
        if r.get("id"):
            variant_ids.add(r["id"])
            if r.get("status") != "retired":
                active_variant_ids.add(r["id"])

    company_ids, channel_ids = set(), set()

    # ⭐ UNKNOWN-KEY GUARD FOR EVERY ARRAY, FROM docs/data_model.json (2026-08-04).
    # Only outreach[] had one before, which is why `nxet_action_owner` wrote silently and this
    # validator reported CLEAN. The definition lives in ONE file that record.py also reads —
    # restating the field list here would be the same drift the banned_aliases exist to stop.
    try:
        # ⭐ ENGINE path, not ROOT (2026-08-05). The schema ships with the ENGINE; the data
        # belongs to the USER. Resolving it off ROOT conflated the two and broke the moment
        # a data dir was pointed elsewhere — which is precisely what ADR-007's repo split
        # does permanently. Anchored to this file's own location instead.
        _engine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(_engine, "docs", "data_model.json"), encoding="utf-8") as _fh:
            _model = json.load(_fh)
    except Exception as _e:
        problems.append("cannot read docs/data_model.json (%s) — the key guard is OFF" % _e)
        _model = None
    if _model:
        _ali = {k: v for k, v in _model["banned_aliases"].items() if not k.startswith("_")}
        _spec = _model["stores"]["opportunities"]
        for r in opps:
            _l = "opportunities[%s]" % r.get("id", "?")
            for _k in r:
                if _k in _ali:
                    problems.append("%s: %r is a banned alias for %r — two spellings of one "
                                    "meaning make a query miss half the data" % (_l, _k, _ali[_k]))
                elif _k not in _spec["fields"]:
                    problems.append("%s: unknown key %r. Add it to docs/data_model.json if it is "
                                    "genuinely new; otherwise it is a typo that every query "
                                    "against the real field will silently miss." % (_l, _k))
            for _arr, _aspec in (_spec.get("arrays") or {}).items():
                # Dotted names address a nested array (`fit.requirements`). A plain `r.get()`
                # returns None for those, so the model would declare fields that nothing
                # enforced — a schema that silently checks nothing is worse than no schema.
                _node = r
                for _part in _arr.split(".")[:-1]:
                    _node = _node.get(_part) or {}
                for _i, _item in enumerate(_node.get(_arr.split(".")[-1]) or []):
                    for _k in _item:
                        if _k in _ali:
                            problems.append("%s: %s[%d] %r is a banned alias for %r"
                                            % (_l, _arr, _i, _k, _ali[_k]))
                        elif _k not in _aspec["fields"]:
                            problems.append("%s: %s[%d] unknown key %r (known: %s)"
                                            % (_l, _arr, _i, _k, ", ".join(sorted(_aspec["fields"]))))

    # ---- companies ----
    for r in companies:
        cid = r.get("id", "?")
        label = "companies[%s]" % cid
        for f in ("id", "name", "vertical", "status"):
            req(r, f, label, problems)
        if r.get("id") in company_ids:
            problems.append("%s: duplicate id" % label)
        company_ids.add(r.get("id"))
        enum(r, "vertical", VERTICALS, label, problems)
        enum(r, "status", COMPANY_STATUS, label, problems)
        for entry in r.get("research_log", []):
            if not is_date(entry.get("date", "")):
                problems.append("%s: research_log date not ISO — %r" % (label, entry.get("date")))

    # ---- channels ----
    for r in channels:
        chid = r.get("id", "?")
        label = "channels[%s]" % chid
        for f in ("id", "label", "type", "review_cadence"):
            req(r, f, label, problems)
        if r.get("id") in channel_ids:
            problems.append("%s: duplicate id" % label)
        channel_ids.add(r.get("id"))
        enum(r, "type", CHANNEL_TYPES, label, problems)
        enum(r, "review_cadence", CADENCES, label, problems)
        if "access" in r:
            enum(r, "access", ACCESS, label, problems)
        # alert_sweep.py ORs this across every non-retired channel that sets it (dev #147) —
        # an empty or non-string value would silently drop out of that OR clause and look like
        # "no alerts from this source" rather than a malformed field.
        if "alert_sender" in r and r.get("alert_sender") is not None:
            if not isinstance(r.get("alert_sender"), str) or not r.get("alert_sender").strip():
                problems.append("%s: alert_sender present but not a non-empty string — %r"
                                % (label, r.get("alert_sender")))
        lr = r.get("last_reviewed")
        if lr is not None and not is_date(lr):
            problems.append("%s: last_reviewed not ISO or null — %r" % (label, lr))
        nt = r.get("next_touch")
        if nt is not None and not is_date(nt.get("date", "")):
            problems.append("%s: next_touch.date not ISO — %r" % (label, nt.get("date")))
        for e in r.get("log", []):
            if not is_date(e.get("date", "")):
                problems.append("%s: log date not ISO — %r" % (label, e.get("date")))

    # ---- opportunities ----
    opp_ids = set()
    for r in opps:
        oid = r.get("id", "?")
        label = "opportunities[%s]" % oid
        for f in ("id", "company_id", "title", "status", "stage", "verdict"):
            req(r, f, label, problems)
        if r.get("id") in opp_ids:
            problems.append("%s: duplicate id" % label)
        opp_ids.add(r.get("id"))

        enum(r, "status", OPP_STATUS, label, problems)
        enum(r, "stage", STAGES, label, problems)
        enum(r, "verdict", VERDICTS, label, problems)

        # ---- play_stage: the post-application play position (public #19 / dev #95) ----
        # Optional and nullable — but an unreadable value must be LOUD, never carried: a play
        # position nobody can parse looks handled and is not (the precondition.py rule).
        ps = r.get("play_stage")
        # Resolve against data the store ALREADY has, the same move as act_by and
        # precondition.py: the applications[] array is the evidence of submission.
        submitted = any(a.get("status") in SUBMITTED_APP_STATUS
                        for a in (r.get("applications") or []))
        # ⭐ A DECISION MADE BY ACTING (dev/audit 2026-09-02, Class A / public #44). A row can
        # say `verdict: undecided` while applications[] proves a submission — the human
        # decided by applying and the field never followed. Left alone it renders a
        # pursue-or-pass ask for a role already applied to. m_0_36_0_verdict_from_applications
        # resolves history; this refuses the contradiction from here on.
        if r.get("verdict") == "undecided" and submitted:
            problems.append("%s: verdict 'undecided' but an applications[] row is already %s "
                            "— the act decided; the store already answers this (pursue)"
                            % (label, "/".join(sorted(SUBMITTED_APP_STATUS))))
        if ps is not None:
            if ps not in PLAY_STAGES:
                problems.append("%s: play_stage %r not in {%s} — an unreadable play position "
                                "looks handled and is not; fix the value or null the field"
                                % (label, ps, ", ".join(sorted(PLAY_STAGES))))
            elif ps == "unresolved" and r.get("status") not in TERMINAL_OPP_STATUSES:
                # ⭐ Derivable, so never a printed instruction (dev/audit 2026-09-02, public
                # #42). The migration marker said "a human must name the stage"; the store
                # already answers the one question that matters: applied, or not.
                # m_0_36_0_play_stage_from_applications resolves every historical marker,
                # and record.py's pre-write validation refuses a new one here.
                problems.append("%s: play_stage 'unresolved' is derivable from applications[] "
                                "— the store already answers it: %r"
                                % (label, _ym.derive_play_stage(r)))
            else:
                if ps == "needs-application" and submitted:
                    problems.append("%s: play_stage 'needs-application' but an applications[] "
                                    "row is already %s — the store knows this role was applied "
                                    "to; advance the play_stage" %
                                    (label, "/".join(sorted(SUBMITTED_APP_STATUS))))
                if ps in POST_APPLICATION_PLAY and not submitted:
                    problems.append("%s: play_stage %r presupposes a submitted application, but "
                                    "no applications[] row has status in {%s} — a post-"
                                    "application play on a role never applied to is a claim the "
                                    "store contradicts" %
                                    (label, ps, ", ".join(sorted(SUBMITTED_APP_STATUS))))
                if r.get("status") in TERMINAL_OPP_STATUSES:
                    problems.append("%s: status %r with play_stage %r — a terminal role has no "
                                    "live play position; null the field when a role leaves the "
                                    "funnel" % (label, r.get("status"), ps))

        # referential integrity
        if r.get("company_id") not in company_ids:
            problems.append("%s: company_id %r does not resolve" % (label, r.get("company_id")))
        ch = r.get("channel_id")
        if ch is not None and ch not in channel_ids:
            problems.append("%s: channel_id %r does not resolve" % (label, ch))

        # ---- resume_variant: the variant this role should RECEIVE (public #26) ----
        # This used to survive only as prose in next_action, silently lost on rewrite.
        rv = r.get("resume_variant")
        if rv is not None:
            if rv not in variant_ids:
                problems.append("%s: resume_variant %r does not resolve in "
                                "data/resume_variants.jsonl — the send decision must name a "
                                "DECLARED variant or it is prose wearing a field" % (label, rv))
            elif rv not in active_variant_ids:
                problems.append("%s: resume_variant %r is retired — a role cannot plan to "
                                "send a resume no longer sent; point it at an active variant "
                                "or null the field" % (label, rv))

        # ---- fit analysis (optional block) ----
        fit = r.get("fit")
        if fit is not None:
            if not isinstance(fit, dict):
                problems.append("%s: fit must be an object" % label)
            else:
                if not is_date(fit.get("analyzed_on", "")):
                    problems.append("%s: fit.analyzed_on not ISO — %r" % (label, fit.get("analyzed_on")))
                reqs = fit.get("requirements")
                if not isinstance(reqs, list) or not reqs:
                    problems.append("%s: fit.requirements must be a non-empty list" % label)
                else:
                    for i, q in enumerate(reqs):
                        rl = "%s fit.requirements[%d]" % (label, i)
                        if not (q.get("requirement") or "").strip():
                            problems.append("%s: empty 'requirement'" % rl)
                        enum(q, "verdict", FIT_VERDICTS, rl, problems)
                        enum(q, "question_status", FIT_Q_STATUS, rl, problems)
                        # An alignment claim with no citation is a gap wearing a disguise.
                        if q.get("verdict") in ("aligned", "partial") and not (q.get("evidence") or "").strip():
                            problems.append("%s: verdict=%r requires 'evidence' — an uncited "
                                            "alignment claim is not evidence of alignment"
                                            % (rl, q.get("verdict")))
                        # An unknown with no question is a gap nobody will ever close.
                        # ⭐ act_by — added 2026-08-03. A question with a DATE is a different
                        # object from one without. The candidate: "does the coordinator know to suggest a
                        # draft a nudge to <a recruiter> for today?" It did not. <a recruiter>'s auto-reply
                        # said she returns Monday August 3; that fact went into the question as
                        # PROSE, and nothing can sort or surface prose. A date in a field can be.
                        ab = q.get("act_by")
                        if ab is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(ab)):
                            problems.append("%s: act_by %r is not an ISO date" % (rl, ab))
                        if q.get("verdict") == "unknown" and not (q.get("question_for_candidate") or "").strip():
                            problems.append("%s: verdict='unknown' requires 'question_for_candidate' — "
                                            "otherwise the gap is recorded and never harvested" % rl)
                        if q.get("question_status") == "answered" and not (q.get("landed_in") or "").strip():
                            problems.append("%s: question_status='answered' requires 'landed_in' "
                                            "(projects.md / resume.md-addendum / resume.md / kb_<company>.md)" % rl)
                        if q.get("answered_on") and not is_date(q.get("answered_on")):
                            problems.append("%s: answered_on not ISO — %r" % (rl, q.get("answered_on")))

        # jd_url must be present as string or explicit null
        if "jd_url" not in r:
            problems.append("%s: jd_url missing (use explicit null if none)" % label)

        # comp typed
        #
        # ⭐ dev #143 / public #23: `comp` must be an OBJECT ({"min": ..., "max": ...}), and a
        # caller passing it as a plain string (the exact class of mistake `fields` used to
        # leave nobody warned about) crashed this function outright — `comp.get(...)` on a
        # str has no such method, so the whole validator died before printing a single problem
        # line. That produced the "generic banner naming nothing" failure: record.py's refusal
        # message is built from this script's stdout, and a crash mid-check leaves stdout
        # empty. Guard the shape FIRST so a wrongly-typed comp gets an actionable problem line,
        # like every other typed field here, instead of taking the whole run down with it.
        comp = r.get("comp")
        if comp is not None:
            if not isinstance(comp, dict):
                problems.append("%s: comp must be an object with numeric 'min'/'max' keys — "
                                "got %s: %r" % (label, type(comp).__name__, comp))
            else:
                mn, mx = comp.get("min"), comp.get("max")
                if not isinstance(mn, (int, float)) or not isinstance(mx, (int, float)):
                    problems.append("%s: comp.min/max must be numbers — %r" % (label, comp))
                elif mn > mx:
                    problems.append("%s: comp.min %s > comp.max %s" % (label, mn, mx))

        # location shape
        loc = r.get("location", {})
        if not isinstance(loc, dict) or loc.get("type") not in LOC_TYPES:
            problems.append("%s: location.type not in {%s}" % (label, ", ".join(sorted(LOC_TYPES))))
        if isinstance(loc, dict):
            decl = loc.get("declared")
            if decl is not None and not isinstance(decl, str):
                problems.append("%s: location.declared must be a string — it is the posting's "
                                "own verbatim work-setting text" % label)
            # ⭐ `unresolved` without the verbatim evidence is just a guess deferred. The whole
            # point of the state (issue #4) is that something downstream can revisit what the
            # posting ACTUALLY said — today that information is destroyed at parse time.
            if loc.get("type") == "unresolved" and not (decl if isinstance(decl, str) else "").strip():
                problems.append("%s: location.type 'unresolved' requires 'declared' — the "
                                "posting's verbatim work-setting text is what the question to "
                                "the employer gets asked FROM; without it nothing can revisit "
                                "the conflict" % label)

        # sightings — the overlap records
        sightings = r.get("sightings", [])
        if not sightings:
            problems.append("%s: no sightings (how was it found?)" % label)
        for i, sg in enumerate(sightings):
            scid = sg.get("channel_id")
            if scid not in channel_ids:
                problems.append("%s: sighting[%d].channel_id %r does not resolve" % (label, i, scid))
            if not is_date(sg.get("seen_on", "")):
                problems.append("%s: sighting[%d].seen_on not ISO — %r" % (label, i, sg.get("seen_on")))

        # ownership — required, drives Your Move vs my-tasks generation
        enum(r, "next_action_owner", OWNERS, label, problems)

        # ⭐ blocked_until — GitHub #79. Grammar is precondition.py's VERBATIM, owned by
        # your_move.py (the single place that decides Your Move group membership). Only a
        # genuinely UNREADABLE value is a schema problem: the literal 'unresolved' is valid,
        # durable data (a decided, not-yet-structured state — see your_move.py's docstring),
        # exactly as precondition.py never treats its own `unresolved` marker as a parse
        # error. An unreadable precondition is worse than none because it looks handled and
        # is not, so this fails loudly rather than silently defaulting to 'now'.
        bu = r.get("blocked_until")
        if bu is not None:
            try:
                _ym.parse_blocked_until(bu)
            except _ym.PreconditionError as e:
                problems.append("%s: blocked_until %r is unreadable — %s" % (label, bu, e))
        # contacts — warm paths / hiring managers / internal
        for i, ct in enumerate(r.get("contacts", [])):
            if "name" not in ct:
                problems.append("%s: contact[%d] missing name" % (label, i))
            if ct.get("path_type") and ct["path_type"] not in PATH_TYPES:
                problems.append("%s: contact[%d].path_type %r invalid" % (label, i, ct.get("path_type")))
        # ---- contacts[]: the people, with a stable id so outreach can JOIN to them ----
        # Added 2026-08-02 after the candidate asked whether the structure was managing all the contact
        # data for an opportunity. It wasn't: 20 of 46 outreach rows had NO contact record, and
        # `to` was free text that couldn't match `name` even when both existed.
        contact_ids = set()
        for i, ct in enumerate(r.get("contacts", [])):
            cl = "%s: contacts[%d]" % (label, i)
            cid = ct.get("contact_id")
            if not cid:
                problems.append("%s: missing 'contact_id' — outreach cannot join to it" % cl)
            elif cid in contact_ids:
                problems.append("%s: duplicate contact_id %r" % (cl, cid))
            else:
                contact_ids.add(cid)
            if not (ct.get("name") or "").strip():
                problems.append("%s: missing 'name'" % cl)
            em = ct.get("email")
            if em and not re.match(r"^[\w.+-]+@[\w.-]+\.\w{2,}$", em):
                problems.append("%s: email %r is not an address" % (cl, em))
            # ⭐ A structured address must carry HOW WE KNOW IT. Added 2026-08-03 after
            # a contact's address sat in a prose note marked UNVERIFIED: lifting it
            # into `email` makes it queryable, but without this it would read as confirmed.
            # Same distinction outreach[].address_status already draws.
            es = ct.get("email_status")
            if es is not None and es not in CONTACT_EMAIL_STATUS:
                problems.append("%s: email_status %r not in {%s}"
                                % (cl, es, ", ".join(sorted(CONTACT_EMAIL_STATUS))))

        # The application handles a trigger on THIS record may name (public #27): app_id where
        # minted, date for pre-migration rows. Own-record rule — see check_trigger.
        app_refs = set()
        for ap in r.get("applications") or []:
            for h in (ap.get("app_id"), ap.get("date")):
                if isinstance(h, str) and h.strip():
                    app_refs.add(h)

        # outreach — links drafts to the role (kills the phantom-drafts bug)
        for i, o2 in enumerate(r.get("outreach", [])):
            if o2.get("status") not in OUTREACH_STATUS:
                problems.append("%s: outreach[%d].status %r not in {%s}" % (label, i, o2.get("status"), ", ".join(sorted(OUTREACH_STATUS))))
            ocid = o2.get("channel_id")
            if ocid is not None and ocid not in channel_ids:
                problems.append("%s: outreach[%d].channel_id %r does not resolve" % (label, i, ocid))
            # ⭐⭐ A MEDIUM IS NOT A RELATIONSHIP — enforced HERE, not only in the test suite.
            #
            # `linkedin-direct` and `email-direct` are legacy rows that still RESOLVE in
            # channels.jsonl, so the resolve check above waves them through. The rule that they
            # are media masquerading as relationships lived only in `test_checks.py`, which runs
            # weekly and in CI — **so the write API could not enforce it.** A row stamped
            # `channel_id: linkedin-direct` was written on 2026-08-06, passed validation, passed
            # record.py's post-write check, and persisted; only the regression suite noticed,
            # days later, by which point it is history rather than a rejected keystroke.
            #
            # THE GENERAL LESSON, and it is the reason this moved: **a rule that lives only in
            # the test suite cannot protect a write.** The validator runs on every write; the
            # suite runs on a schedule. Any invariant about DATA belongs in the validator, and
            # the suite's job is to assert that the validator still enforces it.
            if ocid in RETIRED_CHANNEL_IDS:
                problems.append(
                    "%s: outreach[%d].channel_id %r is a MEDIUM, not a relationship — it is "
                    "retired. Put the medium in 'medium' (%s) and leave channel_id null unless a "
                    "real relationship (a firm or referrer) carried the message."
                    % (label, i, ocid, ", ".join(sorted(MEDIA))))
            if o2.get("outcome") is not None and o2["outcome"] not in OUTREACH_OUTCOME:
                problems.append("%s: outreach[%d].outcome %r not in {%s}" % (label, i, o2.get("outcome"), ", ".join(sorted(OUTREACH_OUTCOME))))

            ol = "%s: outreach[%d]" % (label, i)
            # Unknown keys REJECTED — this is what catches the next sent_on/replied_on alias.
            extra = set(o2) - OUTREACH_KEYS
            if extra:
                problems.append("%s: unknown key(s) %s — an alias key that nothing rejects is "
                                "how sent_on/replied_on/channel/notes drifted into the data"
                                % (ol, ", ".join(sorted(extra))))
            # `to` and `date` were never required or type-checked before 2026-08-02.
            if o2.get("status") == "sent":
                if not (o2.get("to") or "").strip():
                    problems.append("%s: status='sent' requires a non-empty 'to'" % ol)
                if not is_when(o2.get("date") or ""):
                    problems.append("%s: status='sent' requires an ISO 'date' — an undated row "
                                    "makes check_followups over-report silence" % ol)
            elif o2.get("date") is not None and not is_when(o2.get("date")):
                problems.append("%s: date %r is neither an ISO date nor 'YYYY-MM-DD HH:MM'"
                                % (ol, o2.get("date")))
            # ---- the reply side, as stored data (dev/audit 2026-09-02, Class B) ----
            ro2 = o2.get("responded_on")
            if ro2 is not None:
                if not is_when(ro2):
                    problems.append("%s: responded_on %r is neither an ISO date nor "
                                    "'YYYY-MM-DD HH:MM'" % (ol, ro2))
                elif precedes(ro2, o2.get("date")):
                    problems.append("%s: responded_on %s is before the row's own date %s — a "
                                    "reply cannot precede the message it answers"
                                    % (ol, ro2, o2["date"]))
            # A reply LINKED in the store (messages[].answers names this row's message) while
            # the row still records no response is a contradiction the data itself can see —
            # the row reads "awaiting" on every surface while the answer sits in
            # messages.jsonl. Derived, so it never depends on a weekly mailbox audit.
            _mref = o2.get("message_ref")
            if _mref and _mref in answered_by and not o2.get("responded_on"):
                problems.append("%s: still awaiting, but messages[%s] answers its message_ref "
                                "%r — set responded_on (and outcome) on the row"
                                % (ol, "/".join(str(x) for x in answered_by[_mref]), _mref))
            for fld, allowed in (("medium", MEDIA), ("touch_type", TOUCH_TYPES),
                                 ("recipient_role", RECIPIENT_ROLES), ("delivery", DELIVERY)):
                v = o2.get(fld)
                if v is not None and v not in allowed:
                    problems.append("%s: %s=%r not in {%s}" % (ol, fld, v, ", ".join(sorted(allowed))))
            if o2.get("address_status") is not None and o2["address_status"] not in ADDRESS_STATUS:
                problems.append("%s: address_status=%r not in {%s}"
                                % (ol, o2["address_status"], ", ".join(sorted(ADDRESS_STATUS))))
            # An email medium without an address_status can't distinguish a bounce from silence.
            if (o2.get("medium") or "").startswith("email") and not o2.get("address_status"):
                problems.append("%s: medium=%r requires 'address_status' — otherwise a bounced "
                                "pattern-inferred address is indistinguishable from a non-reply"
                                % (ol, o2.get("medium")))
            # From the cutover, the comms fields are required (history carries 'unknown').
            if (o2.get("date") or "") >= COMMS_CUTOVER and o2.get("status") == "sent":
                for fld in ("medium", "touch_type", "recipient_role", "delivery"):
                    if not o2.get(fld):
                        problems.append("%s: '%s' is required on rows dated %s or later"
                                        % (ol, fld, COMMS_CUTOVER))
            # THE JOIN. If the candidate messaged someone, they must exist as a contact of this
            # opportunity — otherwise "what is the whole history with this person?" is
            # unanswerable, which is exactly the gap the candidate identified.
            ocid = o2.get("contact_id")
            if not ocid:
                problems.append("%s: missing 'contact_id' — every outreach row must name the "
                                "person it went to (run scripts/migrate_contacts.py)" % ol)
            elif ocid not in contact_ids:
                problems.append("%s: contact_id %r does not resolve to a contacts[] entry on "
                                "this opportunity" % (ol, ocid))

            if o2.get("message_ref") and o2["message_ref"] not in sent_ids:
                problems.append("%s: message_ref %r does not resolve in data/messages.jsonl "
                                "— a pointer to text that isn't there is worse than no pointer"
                                % (ol, o2["message_ref"]))
            if o2.get("campaign_id") and not re.match(r"^[a-z0-9][a-z0-9-]*$", o2["campaign_id"]):
                problems.append("%s: campaign_id %r must be a lowercase slug" % (ol, o2["campaign_id"]))
            # What caused this touch (public #27) — shared with asks, see check_trigger.
            check_trigger(o2, ol, problems, app_refs, sent_ids)
            # Sequence membership (public #27): grouping only — the hold on a staged step
            # lives in **Blocked until:** and is precondition.py's, never restated here.
            sid, sst = o2.get("sequence_id"), o2.get("sequence_step")
            if (sid is None) != (sst is None):
                problems.append("%s: sequence_id and sequence_step come together — half a "
                                "sequence membership cannot be grouped and must not look like "
                                "one (got id=%r step=%r)" % (ol, sid, sst))
            elif sid is not None:
                if not (isinstance(sid, str) and SLUG_RE.match(sid)):
                    problems.append("%s: sequence_id %r must be a lowercase slug" % (ol, sid))
                if not (isinstance(sst, int) and not isinstance(sst, bool) and sst >= 1):
                    problems.append("%s: sequence_step %r must be an integer >= 1" % (ol, sst))
        # applications[] — when the candidate applied, how, and what came back
        for i, ap in enumerate(r.get("applications", [])):
            if ap.get("method") not in APPLICATION_METHODS:
                problems.append("%s: applications[%d].method %r not in {%s}" % (label, i, ap.get("method"), ", ".join(sorted(APPLICATION_METHODS))))
            if ap.get("status") not in APPLICATION_STATUS:
                problems.append("%s: applications[%d].status %r not in {%s}" % (label, i, ap.get("status"), ", ".join(sorted(APPLICATION_STATUS))))
            # A submitted application must carry the date it went out, or the
            # whole point (measuring time-to-response) is lost.
            if ap.get("status") in ("submitted", "acknowledged", "rejected", "advanced") and not ap.get("date"):
                problems.append("%s: applications[%d] is %r but has no date — that is the field the funnel analysis runs on" % (label, i, ap.get("status")))
            # Which variant actually WENT (public #26) — retired resolves fine here: history
            # must stay attributable forever, which is why 'retired' exists instead of delete.
            arv = ap.get("resume_variant")
            if arv is not None and arv not in variant_ids:
                problems.append("%s: applications[%d].resume_variant %r does not resolve in "
                                "data/resume_variants.jsonl — attribution of outcomes to "
                                "positioning depends on this join" % (label, i, arv))
            al = "%s: applications[%d]" % (label, i)
            # app_id (public #27) — the stable handle a trigger names. Optional until the
            # deferred D3 migration backfills history; where present it must be a slug and
            # unique on the record, or two triggers could name different rows with one ref.
            aid = ap.get("app_id")
            if aid is not None:
                if not (isinstance(aid, str) and SLUG_RE.match(aid)):
                    problems.append("%s: app_id %r must be a lowercase slug (mint as "
                                    "<opp_id>-aN)" % (al, aid))
                elif sum(1 for a2 in r.get("applications") or []
                         if a2.get("app_id") == aid) > 1:
                    problems.append("%s: duplicate app_id %r on this record — a trigger "
                                    "naming it would be ambiguous" % (al, aid))
            # form_answers (public #27) — what was actually answered on the form's own
            # questions. Unknown entry keys REJECTED (the sent_on/replied_on lesson);
            # an unreadable answer is LOUD, never skipped — it looks captured and is not.
            fa = ap.get("form_answers")
            if fa is not None:
                if not isinstance(fa, list):
                    problems.append("%s: form_answers must be a list of "
                                    "{question_key, question, answer, answered_on}, got %s"
                                    % (al, type(fa).__name__))
                    fa = []
                seen_q = set()
                for j, ans in enumerate(fa):
                    fl = "%s.form_answers[%d]" % (al, j)
                    if not isinstance(ans, dict):
                        problems.append("%s: entry is %s, not an object" % (fl, type(ans).__name__))
                        continue
                    extra = set(ans) - FORM_ANSWER_KEYS
                    if extra:
                        problems.append("%s: unknown key(s) %s" % (fl, ", ".join(sorted(extra))))
                    qk = ans.get("question_key")
                    if not (isinstance(qk, str) and SLUG_RE.match(qk)):
                        problems.append("%s: question_key %r must be a lowercase slug shared "
                                        "across applications (e.g. salary-expectations, "
                                        "reason-for-leaving, ai-usage) — precedent is a join, "
                                        "not a search" % (fl, qk))
                    elif qk in seen_q:
                        problems.append("%s: duplicate question_key %r on one application — "
                                        "which answer is the precedent?" % (fl, qk))
                    else:
                        seen_q.add(qk)
                    av = ans.get("answer")
                    if not (isinstance(av, str) and av.strip()):
                        problems.append("%s: 'answer' must be a non-empty string — an empty "
                                        "answer looks captured and is not" % fl)
                    ao = ans.get("answered_on")
                    if ao is not None and not is_date(ao):
                        problems.append("%s: answered_on not ISO — %r" % (fl, ao))
        # status vs. stage — orthogonal, but not every pairing is coherent.
        # Added 2026-07-21: the markdown backfill left two live active pursuits
        # (two employers) sitting at stage "closed", which
        # says we're actively pursuing a role we've also marked as out of the
        # funnel. Nothing caught it because each field was independently valid.
        st, stg = r.get("status"), r.get("stage")
        if st in ("active-pursuit", "needs-resolution", "in-motion") and stg == "closed":
            problems.append("%s: status %r with stage 'closed' — a live role cannot be out of the funnel" % (label, st))
        if st == "passed" and stg not in ("closed", None):
            problems.append("%s: status 'passed' but stage %r — passed roles belong at stage 'closed'" % (label, stg))
        # `expired` is terminal (issue #6): out of the funnel, like passed…
        if st == "expired" and stg not in ("closed", None):
            problems.append("%s: status 'expired' but stage %r — an expired role is out of the "
                            "funnel and belongs at stage 'closed'" % (label, stg))
        # …but it records the ABSENCE of a decision. A decided pass is status 'passed';
        # stamping a role both 'expired' and verdict 'pass' would re-create the exact
        # corruption the state exists to remove (an expiry counted as a deliberate pass).
        if st == "expired" and r.get("verdict") == "pass":
            problems.append("%s: status 'expired' with verdict 'pass' — expired records that NO "
                            "decision was made before the posting vanished; if the candidate "
                            "decided to pass, the status is 'passed'" % label)

    # ---- asks (dev #93) — the hand-authored tail of Your Move, structured ----
    # Absence is legal: a profile predating the 0.25.0 migration has no asks.jsonl yet, and
    # the fixture ships without one. Present-but-broken is a problem like any other store.
    asks, e = load("asks.jsonl")
    if asks is None:
        asks = []
    else:
        problems += e or []
    ask_ids = set()
    for r in asks:
        aid = r.get("id", "?")
        label = "asks[%s]" % aid
        for f in ("id", "kind", "title", "ask", "created"):
            req(r, f, label, problems)
        if r.get("id") in ask_ids:
            problems.append("%s: duplicate id" % label)
        ask_ids.add(r.get("id"))
        enum(r, "kind", ASK_KINDS, label, problems)
        if not is_date(r.get("created", "")):
            problems.append("%s: created not ISO — %r" % (label, r.get("created")))
        for f in ("act_by", "resolved_on"):
            v = r.get(f)
            if v is not None and f in r and not is_date(v):
                problems.append("%s: %s not ISO or null — %r" % (label, f, v))
        if r.get("opp_id") and r["opp_id"] not in opp_ids:
            problems.append("%s: opp_id %r resolves to no opportunity" % (label, r["opp_id"]))
        if r.get("channel_id") and r["channel_id"] not in channel_ids:
            problems.append("%s: channel_id %r resolves to no channel" % (label, r["channel_id"]))
        # What caused this ask (public #27) — same shared check as outreach[] triggers. An
        # 'application' ref resolves against the LINKED opp's applications[] and therefore
        # requires opp_id: without one there is no record to resolve against, which is the
        # resolves_when-without-opp_id defect in new clothes.
        if r.get("trigger_kind") == "application" and not r.get("opp_id"):
            problems.append("%s: trigger_kind 'application' without opp_id — there is no "
                            "record whose applications[] the ref could resolve against" % label)
        else:
            ask_app_refs = set()
            for opp in opps or []:
                if opp.get("id") == r.get("opp_id"):
                    for ap in opp.get("applications") or []:
                        for h in (ap.get("app_id"), ap.get("date")):
                            if isinstance(h, str) and h.strip():
                                ask_app_refs.add(h)
            check_trigger(r, label, problems, ask_app_refs, sent_ids)
        # An ask that is resolved must say how it resolved — "expelled" with no outcome is
        # the old delete-the-prose move with less accountability, not more.
        if r.get("resolved_on") and not r.get("resolution"):
            problems.append("%s: resolved_on with no resolution — say how it resolved "
                            "(answered / lapsed / superseded / done)" % label)
        # dev #133 / public #22 — the atomic-resolution contract. Both halves are LOUD on
        # purpose: an unknown resolves_when can never fire, and one with no opp_id has no
        # opportunity to resolve against — either way the ask claims it will self-resolve
        # when the action lands, and it never will.
        if "resolves_when" in r and r.get("resolves_when") is not None:
            if r["resolves_when"] not in ASK_RESOLVES_WHEN:
                problems.append("%s: resolves_when %r is not one of %s — record.py can never "
                                "match it, so the ask would wait forever while looking handled"
                                % (label, r["resolves_when"],
                                   "/".join(sorted(ASK_RESOLVES_WHEN))))
            elif not r.get("opp_id"):
                problems.append("%s: resolves_when without opp_id — there is no opportunity "
                                "for the recorded action to land on, so it can never resolve"
                                % label)

    # ---- commitments (dev #93) — This Week, structured ----
    commitments, e = load("commitments.jsonl")
    if commitments is None:
        commitments = []
    else:
        problems += e or []
    cm_ids = set()
    for r in commitments:
        cid = r.get("id", "?")
        label = "commitments[%s]" % cid
        for f in ("id", "date", "title"):
            req(r, f, label, problems)
        if r.get("id") in cm_ids:
            problems.append("%s: duplicate id" % label)
        cm_ids.add(r.get("id"))
        d = r.get("date")
        if d is not None and not is_date(d) and d != UNRESOLVED:
            # An unreadable date must be LOUD (the precondition.py rule): a commitment nobody
            # can place on a calendar looks handled and is not.
            problems.append("%s: date %r is neither ISO nor the literal %r" % (label, d, UNRESOLVED))
        if r.get("opp_id") and r["opp_id"] not in opp_ids:
            problems.append("%s: opp_id %r resolves to no opportunity" % (label, r["opp_id"]))
        if r.get("channel_id") and r["channel_id"] not in channel_ids:
            problems.append("%s: channel_id %r resolves to no channel" % (label, r["channel_id"]))

    # Unknown-key guard for both new stores — same model-driven rule opportunities already
    # gets, because `nxet_action_owner` is exactly the class of typo these fields will grow.
    if _model:
        _ali = {k: v for k, v in _model["banned_aliases"].items() if not k.startswith("_")}
        for store_name, rows_ in (("asks", asks), ("commitments", commitments),
                                  ("resume_variants", variants)):
            _sspec = _model["stores"].get(store_name) or {}
            for r in rows_:
                _l = "%s[%s]" % (store_name, r.get("id", "?"))
                for _k in r:
                    if _k in _ali:
                        problems.append("%s: %r is a banned alias for %r" % (_l, _k, _ali[_k]))
                    elif _k not in (_sspec.get("fields") or ()):
                        problems.append("%s: unknown key %r (known: %s)"
                                        % (_l, _k, ", ".join(sorted(_sspec.get("fields") or ()))))

    print("Data validation — %d companies, %d channels, %d opportunities, %d asks, "
          "%d commitments, %d resume variants"
          % (len(companies), len(channels), len(opps), len(asks),
             len(commitments), len(variants)))
    if not problems:
        print("\n  Clean. Schema, enums, types, and every cross-reference resolve.")
        return 0, []
    print("\n" + "=" * 68)
    print("%d PROBLEM(S)" % len(problems))
    print("=" * 68)
    for p in problems:
        print("  - " + p)
    return 1, problems


if __name__ == "__main__":
    sys.exit(main())
