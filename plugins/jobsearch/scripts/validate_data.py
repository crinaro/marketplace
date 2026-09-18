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
# ADR-031 B4 — `plans.py` has no dependency on this module (unlike `plays.py`, which DOES
# import validate_data and is therefore imported LAZILY, inside `_main()`, to avoid the cycle),
# so it is safe as a normal top-level import.
import plans as _plans
# ADR-027 — the one surface vocabulary (also imported by resume_variants.py, presence_set.py);
# zero dependencies of its own, so no cycle risk as a normal top-level import.
import surfaces as _surfaces
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

# ADR-031 B5 (design-b5-assessment.md §2) — `plans.assessments[]`, the weekly assessment's one
# stored row, and its `proposals[]`. The engine writes the dates, the window, the version and the
# proposals; `working`/`not_working`/`next_steps`/`note` are the owner's words only.
ASSESSMENT_PROPOSAL_STATUS = {"proposed", "accepted", "declined", "reported", "superseded"}
# The key decides the direction mechanically (design §27.2): a `parameter` proposal names a value
# the owner controls (a declared parameter of the plan's play, or a `config:<dotted>` key that
# config_keys registers); a `construct` proposal names `<signal>:<step|token>` with the signal in
# funnel_report.CONSTRUCT_SIGNALS — the shape is the engine's. There is no third kind.
ASSESSMENT_PROPOSAL_KINDS = {"parameter", "construct"}
ASSESSMENT_OWNER_PROSE = ("working", "not_working", "next_steps", "note")


def check_assessments(plan, play, model, label, problems):
    """`plans[<id>].assessments[]` — every check the row's own contract states, each a PROBLEM
    with the legal set named (the `enum()` shape, #73): entry key set and dates; proposal key
    set; `kind`/`status` enums; `key` shape BY KIND; `evidence` keys EXACTLY the kind's declared
    set (funnel_report.PROPOSAL_EVIDENCE_KEYS — an undeclared key is refused, never dropped,
    §28.2); `decided_on`/`decision` both-or-neither (the asks contract). Field lists come from
    docs/data_model.json (`model`) so this cannot drift from what record.py enforces; with the
    model unreadable the key-set half is skipped (the caller has already said the guard is OFF)
    and every other check still runs."""
    entries = plan.get("assessments")
    if entries is None:
        return
    if not isinstance(entries, list):
        problems.append("%s: assessments must be a list of entries — got %s"
                        % (label, type(entries).__name__))
        return
    import funnel_report as _fr                    # lazy: resolves the profile at import
    import config_keys as _ck
    spec = (((model or {}).get("stores") or {}).get("plans") or {}).get("arrays") or {}
    spec = spec.get("assessments") or {}
    entry_fields = set(spec.get("fields") or [])
    prop_fields = set((((spec.get("arrays") or {}).get("proposals") or {}).get("fields")) or [])
    declared = set(((play or {}).get("params") or {}).keys())
    for i, e in enumerate(entries):
        el = "%s.assessments[%d]" % (label, i)
        if not isinstance(e, dict):
            problems.append("%s: entry must be an object — got %s" % (el, type(e).__name__))
            continue
        if entry_fields:
            for k in sorted(set(e) - entry_fields):
                problems.append("%s: unknown key %r (known: %s)"
                                % (el, k, ", ".join(sorted(entry_fields))))
        for f in ("date", "as_of", "window_from"):
            v = e.get(f)
            if not is_date(v or ""):
                problems.append("%s: %s must be an ISO date — %r" % (el, f, v))
        if is_date(e.get("as_of") or "") and is_date(e.get("window_from") or "") \
                and e["window_from"] > e["as_of"]:
            problems.append("%s: window_from %s is after as_of %s — the window runs backwards"
                            % (el, e["window_from"], e["as_of"]))
        for f in ASSESSMENT_OWNER_PROSE + ("engine_version",):
            v = e.get(f)
            if v is not None and not isinstance(v, str):
                problems.append("%s: %s must be a string or null — %r" % (el, f, v))
        props = e.get("proposals")
        if not isinstance(props, list):
            problems.append("%s: proposals must be a list (empty is fine) — got %s"
                            % (el, type(props).__name__))
            continue
        seen_ids = set()
        for j, p in enumerate(props):
            pl = "%s.proposals[%d]" % (el, j)
            if not isinstance(p, dict):
                problems.append("%s: must be an object — got %s" % (pl, type(p).__name__))
                continue
            if prop_fields:
                for k in sorted(set(p) - prop_fields):
                    problems.append("%s: unknown key %r (known: %s)"
                                    % (pl, k, ", ".join(sorted(prop_fields))))
            pid = p.get("id")
            if not isinstance(pid, str) or not pid.strip():
                problems.append("%s: id must be a non-empty string (<plan>:<as_of>:<n>)" % pl)
            elif pid in seen_ids:
                problems.append("%s: duplicate proposal id %r within one entry" % (pl, pid))
            seen_ids.add(pid)
            enum(p, "kind", ASSESSMENT_PROPOSAL_KINDS, pl, problems)
            enum(p, "status", ASSESSMENT_PROPOSAL_STATUS, pl, problems)
            kind, key = p.get("kind"), p.get("key")
            if not isinstance(key, str) or not key:
                problems.append("%s: key must be a non-empty string" % pl)
            elif kind == "parameter":
                if key.startswith("config:"):
                    dotted = key[len("config:"):]
                    if dotted not in _ck.READER_KEYS:
                        problems.append("%s: key %r names a config key config_keys does not "
                                        "register (READER_KEYS: %s)"
                                        % (pl, key, ", ".join(sorted(_ck.READER_KEYS))))
                elif play is None:
                    problems.append("%s: key %r is a parameter name but the plan has no play "
                                    "that could declare it — a parameter proposal needs a "
                                    "resolving play or a config:<dotted> key" % (pl, key))
                elif key not in declared:
                    problems.append("%s: key %r is not a parameter play %r declares (declared: "
                                    "%s)" % (pl, key, play.get("id"),
                                             ", ".join(sorted(declared)) or "none"))
            elif kind == "construct":
                sig, _sep, ident = key.partition(":")
                if not _sep or not ident or sig not in _fr.CONSTRUCT_SIGNALS:
                    problems.append("%s: key %r must be <signal>:<step|token> with the signal "
                                    "in the closed catalogue {%s}"
                                    % (pl, key, ", ".join(_fr.CONSTRUCT_SIGNALS)))
            ev = p.get("evidence")
            if not isinstance(ev, dict):
                problems.append("%s: evidence must be an object" % pl)
            elif kind in _fr.PROPOSAL_EVIDENCE_KEYS:
                want = _fr.PROPOSAL_EVIDENCE_KEYS[kind]
                extra, missing = sorted(set(ev) - want), sorted(want - set(ev))
                if extra:
                    problems.append("%s: evidence key(s) %s not declared for kind %r — an "
                                    "undeclared key is refused, never dropped (declared: %s)"
                                    % (pl, ", ".join(extra), kind, ", ".join(sorted(want))))
                if missing:
                    problems.append("%s: evidence is missing declared key(s) %s for kind %r"
                                    % (pl, ", ".join(missing), kind))
            txt = p.get("text")
            if txt is not None and not isinstance(txt, str):
                problems.append("%s: text must be a string or null — %r" % (pl, txt))
            don, dec = p.get("decided_on"), p.get("decision")
            if (don is None) != (dec is None):
                problems.append("%s: decided_on and decision come together — one without the "
                                "other cannot be audited (the asks contract, copied)" % pl)
            if don is not None and not is_date(don):
                problems.append("%s: decided_on not ISO — %r" % (pl, don))
            if dec is not None and not isinstance(dec, str):
                problems.append("%s: decision must be a string or null — %r" % (pl, dec))
            rep = p.get("reported")
            if rep is not None and not isinstance(rep, str):
                problems.append("%s: reported must be a string (the issue url) or null — %r"
                                % (pl, rep))

VERTICALS = {"healthcare-payer", "healthcare-provider", "healthtech", "saas",
             "fintech", "insurtech", "other"}
COMPANY_STATUS = {"active-target", "watching", "passed"}
CHANNEL_TYPES = {"job-board", "aggregator", "company-site", "recruiter",
                 "referral", "alert-email"}
# ⭐ public #83 rule 1 — channel TYPES that carry "a public URL was available at the moment of
# sighting". Recruiter/referral/company-site/alert-email sightings do not carry that guarantee
# (a recruiter can tell you about a role with no public posting at all), so a sighting from any
# other type is never in scope for either half of #83: doctor.py's run-start advisory (#360,
# `check_linkless_sightings`) and record.py's capture-time refusal (this rule's other half)
# both import THIS set rather than re-typing it — it is the one place it is spelled.
URL_BEARING_CHANNEL_TYPES = {"job-board", "aggregator"}
# public #83 rule 1's effective date — the day the capture-time refusal in record.py shipped.
# A sighting dated BEFORE this could not have been refused at write time (it predates the code
# that refuses it), so it stays doctor.py's advisory's business (WARN, non-fatal, and excluded
# there by the same recruiter-sourced/receipt-backed/grace-period rules). Only a sighting dated
# ON OR AFTER this date turns a missing source_url into a hard PROBLEM here — pinned to a
# constant, never "today", so a profile is never turned red retroactively for history it could
# not have prevented.
SOURCE_URL_REQUIRED_SINCE = "2026-09-14"
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
# ⭐⭐ `play_stage`, `PLAY_SEQUENCE`, `PLAY_STAGES`, `POST_APPLICATION_PLAY` — RETIRED in
# ADR-031 B4 (design §19). `play_stage` was a HAND-SET cursor over a fixed sequence; a
# hand-set position not backed by a record is exactly "looks handled and is not". `plays.py`'s
# `next_step()` now DERIVES the position from the stores every time it is asked — the play is
# the authority for content, `plans.jsonl`/`plays.jsonl` the store. The field itself, and
# `next_action` (free text), join `banned_aliases` below (docs/data_model.json); a write of
# either is refused, not merely unknown. See RETIRED_KEYS/`active_retired_keys()` for the B4
# structural-marker gate and `check_retired_reads.py` for the source-code half of the same
# retirement. `record.py set <id> play_stage ...` disappears with it — the way to advance the
# play is to record the act.
# applications[].status values that prove a submission actually happened. States & Views V1
# (design-states-and-views.md §3c) adds `closed` here — a close PRESUPPOSES a submission (you
# cannot close what was never sent), which is exactly what SUBMITTED_APP_STATUS already means
# for every other status in this set. `_CLOSED_STATUSES` scar (§14): this is spelled by hand in
# TWO other places (check_sent_drafts.py, funnel_report.py) and mirrored behind an equality
# test in a third (applications.py) — see APPLICATION_ENDINGS below for the ending vocabulary,
# which is a DIFFERENT set (a subset of statuses that mean "the pursuit is over", not "a
# submission happened").
SUBMITTED_APP_STATUS = {"submitted", "acknowledged", "rejected", "advanced", "closed"}
# ⭐ States & Views V1 §2b/§3c — the ONE imported definition of "an application status that
# means the pursuit through this application is OVER" (the `TERMINAL_OPP_STATUSES` move, one
# layer down). `rejected` (the employer said no), `withdrawn` (they did, after applying) and
# `closed` (we gave up on ATS silence — §3c) are the three; `advanced`/`submitted`/`acknowledged`
# are live, and `not-started`/`started` never reached a submission to end. Read by
# `your_move.ended_because()` and `funnel_report.py`; never re-spelled.
APPLICATION_ENDINGS = frozenset({"rejected", "withdrawn", "closed"})
# States & Views V1 §3a — `opportunities.decision.reason_kind`, required whenever a written
# verdict diverges from `triage_suggestion()`'s own reading at decision time. Proposed by the
# design, not yet vetoed or extended by the owner (§3a's own note).
DECISION_REASON_KINDS = frozenset({"comp-acceptable", "setting-acceptable", "fit-misjudged",
                                   "company-priority", "not-interested", "timing", "other"})
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
                      "rejected", "advanced", "withdrawn", "closed"}
# ADR-031 B2 (design §1/§9, §16 item 3) — a fact about the OPPORTUNITY, not the plan: one
# vocabulary per fact is the rule, shared with the future plans.outcomes. `consulting` was the
# pre-Part-3 wording; amended to `contract`, one word, before anything shipped.
ENGAGEMENT_TYPES = {"full-time", "contract"}
# ADR-031 B2 (design §1) — `cover_letters`, "resume_variants' twin": a status with a terminal
# value, same shape as VARIANT_STATUS. `retired` is TERMINAL, same contract as a resolved ask
# and a retired resume variant. Nullable: a row the 0.45.0 migration preserves verbatim from a
# legacy applications[] row may carry no status at all — the migration cannot know one and must
# not invent it (design §4/§28.2, the gate review's own B2 plant).
COVER_LETTER_STATUS = {"draft", "sent", "retired"}
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

# ⭐⭐ RETIRED NESTED-ARRAY KEYS — ADR-031 §28.1 item 3 / gates-connected-entities.md §1 & Ordering.
# Each connected-entities stage promotes one nested array to its own store and retires the old
# key. This is the ONE place that mapping is declared — check_retired_reads.py's AST scanner
# imports `active_retired_keys()` from here rather than hand-duplicating the three strings, the
# same discipline the field-list guard just above already states: "restating the field list here
# would be the same drift the banned_aliases exist to stop" (line 548 in this file).
#
# `RETIRED_KEYS` names every key ANY stage will eventually retire — declared once, in full, so
# nothing ever hand-types a second copy of these three strings. It is NOT the active refusal set.
#
# ⭐⭐ STAGE-AWARE, ON PURPOSE (the ordering correction this dispatch made — ADR-031 §28.1 item 3,
# re-verified against this file's own guard and against gates-connected-entities.md's Ordering
# section, which requires check_retired_reads.py's own RETIRED_KEYS to "resolve to {} before B1
# ships" for the identical reason). Naming a key here must not REFUSE it before its own stage has
# actually shipped: every tracked profile — including THIS repo's own
# tests/fixtures/profile, read directly by gates.yml's "Data integrity" step — still carries
# `opportunities.contacts[]` until the B1 migration runs, and that migration is explicitly the
# NEXT dispatch's work (ADR-031 §28.1 item 6), not this one's. Confirmed empirically before this
# guard was wired in: patching an unconditional "refuse contacts unconditionally" guard into this
# file flips `validate_data.py` from CLEAN to a hard failure against the tracked fixture, today,
# with no migration yet built to fix the data it would be refusing. ADR-031's own stage rule
# already says why this must not happen: "a store is promoted, its nested source removed, every
# reader re-pointed, the validator and record.py updated, and the migration shipped — in one
# version" (design-connected-entities.md §1) — the validator's refusal and the migration that
# makes the refusal survivable are ONE change, never two commits with a gap between them where
# every existing profile (and this repo's own fixture) fails a validator nobody gave it a way to
# satisfy.
#
# `active_retired_keys()` is that gate: it reads the STAGE'S OWN SHIPPED-NESS FROM THE TREE —
# never a flag a human sets and might forget to update (gates-connected-entities.md's CI-parity
# finding #2, made about check_retired_reads.py but equally true here, since its set must equal
# this one). B1's structural marker is `graph.py`: both the design (§2, "what keeps it honest")
# and the gate review name it as B1's OTHER precondition alongside this guard, and it does not
# exist in this tree until the B1 migration dispatch adds it alongside the migration itself — so
# its presence is exactly the fact that should flip `contacts` from legal to refused. Whoever
# builds B2/B3 names their own analogous marker here (the module or store their own migration
# adds) the same way; the constant grows, the mechanism does not need reinventing.
# ⭐⭐ B4 EXTENDS THE MECHANISM PAST NESTED-ARRAY PROMOTION (2026-09-14). `play_stage` and
# `next_action` are not a nested array being promoted to a store — they are two plain fields on
# `opportunities` being DROPPED outright, their content relocated (design §19: prose to `note`,
# the position to a derivation). The same "the fixture already carries the old shape until the
# migration lands in the same commit" problem applies: `active_retired_keys()` must not refuse
# them until B4's migration (and the fixture regeneration that goes with it) has actually
# shipped. Reusing RETIRED_KEYS/`active_retired_keys()` rather than inventing a second
# mechanism for "a field, not an array" keeps `check_retired_reads.py` a single scanner for
# both retirement shapes — it was already written generically ("every ast.Subscript ... every
# X.get(...) call") and never assumed the key named an array.
RETIRED_KEYS = {"contacts": "B1", "applications": "B2", "outreach": "B3",
               "play_stage": "B4", "next_action": "B4"}

_GRAPH_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph.py")
# ⭐ B2's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). B2 has no cross-store WALKER the way B1's graph.py was already a required
# deliverable — every applications/cover_letters FK is a simple owned pointer, not a
# many-direction graph — so B2's marker is applications.py: the module that owns the
# applications/cover_letters joins every reader used to hand-roll against the nested array (see
# applications.py's own module docstring for the full reasoning). It lands in the SAME commit as
# the 0.45.0 migration and this guard, never ahead of either — exactly graph.py's own timing.
_APPLICATIONS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "applications.py")

# ⭐ B3's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). Unlike B2, B3's `touches` store IS genuinely multi-directional (person, opportunity,
# channel, and §12's object person/company) — exactly the shape `graph.py` exists to walk, and
# `graph.py` gains `touches_for_person()`/`touches_for_opportunity()`/`touches_for_channel()`
# accordingly. But `graph.py` already exists on disk (shipped with B1), so its mere presence
# cannot newly prove B3 shipped the way it proved B1 did — B3 needs its OWN marker file the same
# reason B2 did, even though its join IS a "real" walker this time. `touches.py` is that file:
# the flat load/group module every simple per-opportunity reader (`applying.py`,
# `pipeline_index.py`, `trigger.py`, `precondition.py`, `check_sent_drafts.py`,
# `check_action_claims.py`, `channels_due.py`, `check_followups.py`, `funnel_report.py`,
# `watch.py`, `generate_dashboard.py`) now calls instead of hand-rolling the nested array (see
# touches.py's own module docstring for the full "graph.py vs touches.py" reasoning). It lands
# in the SAME commit as the 0.48.0 migration and this guard, never ahead of either — exactly
# graph.py's own timing for B1, applications.py's for B2.
_TOUCHES_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "touches.py")

# ⭐ B4's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). `plans.py` is B4's flat load/join module (`opportunities.plan_id` is a simple owned
# pointer, not a many-direction graph — the same B2 reasoning `applications.py`'s own docstring
# states). It lands in the SAME commit as the 0.49.0 migration and this guard.
_PLANS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans.py")


def active_retired_keys():
    """The subset of RETIRED_KEYS whose stage has actually shipped in THIS tree — read structurally,
    never all of RETIRED_KEYS and never a human-set flag. Resolves to {} until B1 ships (graph.py
    lands, with the migration, in one commit); see the block comment above RETIRED_KEYS."""
    active = {}
    # ⭐ `_b1_key`/`_b2_key`/`_b3_key` hold the string in a NAME, never a literal subscript on
    # RETIRED_KEYS here — `check_retired_reads.py`'s own scanner matches a Subscript/`.get()`
    # call whose slice is the STRING CONSTANT "contacts"/"applications"/"outreach" (it cannot
    # tell a data-row read from a constant-dict read apart, by design — see its module
    # docstring). `RETIRED_KEYS["contacts"]` would be a real, if harmless, hit on THIS module;
    # reading it through a local variable is not the checker avoided, it is the checker's own
    # documented boundary — a data row is never keyed by a variable holding a compile-time
    # constant a checker can trace back to this exact line.
    _b1_key = "contacts"
    if os.path.exists(_GRAPH_PY):
        active[_b1_key] = RETIRED_KEYS[_b1_key]
    _b2_key = "applications"
    if os.path.exists(_APPLICATIONS_PY):
        active[_b2_key] = RETIRED_KEYS[_b2_key]
    _b3_key = "outreach"
    if os.path.exists(_TOUCHES_PY):
        active[_b3_key] = RETIRED_KEYS[_b3_key]
    _b4_key_1, _b4_key_2 = "play_stage", "next_action"
    if os.path.exists(_PLANS_PY):
        active[_b4_key_1] = RETIRED_KEYS[_b4_key_1]
        active[_b4_key_2] = RETIRED_KEYS[_b4_key_2]
    return active
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
# design-inbound-resolution.md §2 (ADR-029/030) — `messages[].resolved_by`: which of ADR-030's
# three deterministic tiers matched when a message resolves an application. Recorded so the
# EVIDENCE for a status change is auditable later, not just the fact of the change.
RESOLVED_BY = {"req-id", "url", "company-single"}
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
# ⭐ ADR-031 B1: `contact_id` -> `person_id` (docs/data_model.json's banned_aliases carries the
# rename globally). A row still writing `contact_id` is caught by the SAME banned-alias branch
# every unknown-key guard already runs, not a special case here.
# ⭐ ADR-031 B3 — OUTREACH_KEYS retired along with the nested array it governed. `touches` is
# now a top-level store (docs/data_model.json's own field list, gaining `id` and the two §12
# object FKs no nested row ever had) checked by the GENERIC model-driven unknown-key guard
# every other top-level store added since B2 uses — never a second, dedicated set here.
# New required fields apply only from the cutover — backfilled history carries "unknown"
# where no contemporaneous record supports a value. Without this the validator would fail
# against 46 legacy rows on day one and get ignored.
COMMS_CUTOVER = "2026-08-02"
PATH_TYPES = {"warm-referral", "recruiter", "hiring-manager", "hiring-context", "internal", "cold"}
# ADR-031 B1 — `people.status`. `merged` is the ONLY non-active state a person can be in;
# `merged_into` is required iff status is `merged` (checked below, not restated as an enum).
PEOPLE_STATUS = {"active", "merged"}
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
# public #50 — same shape as ADR-013's `expired` and the asks store's `resolved_on`: a fact
# the run knows (a meeting was called off) goes into the queryable store, never into prose.
# Additive; absent means `scheduled` until the 0.40.0 seed migration stamps every existing row
# explicitly (this store's siblings prefer an explicit value over a reader having to know that
# a missing key means the default).
COMMITMENT_STATUS = {"scheduled", "cancelled"}
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

# ---- briefs (Query or Citation C1, design-query-or-citation.md §3.3/§3.7/§4.1) ---------------
# Mirrored as LITERALS — never imported from `your_move.AXIS_FOLD` or `brief.py`'s own module
# constants, because `your_move` imports THIS module and `brief` imports `your_move`; importing
# either back here is the exact load-time cycle `precondition.py`'s lazy import of `brief`
# already exists to avoid. TestBriefVocabularyMirrorsTheReader holds this identical to the
# reader's own tuples, so the copy cannot drift silently.
BRIEF_ID_RE = re.compile(
    r"^brief:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}-[0-9a-f]{4}$")
BRIEF_AXES = {"reply-owed", "accepted", "waiting", "silence-unverified", "silent",
             "nothing-sent"}
BRIEF_REGISTERS = {"reply-owed", "accepted", "premature", "chase", "reconnect",
                   "unverified-silent", "cold", "unverified-cold"}
BRIEF_EVIDENCE_RE = re.compile(
    r"^(?:none-recorded|not-configured|confirmed-empty(?:\(owner, \d{4}-\d{2}-\d{2}\))?|"
    r"confirmed \d+ thread\(s\), latest \d{4}-\d{2}-\d{2}.*|"
    r"candidate \d+ \(by name\)|"
    r"unreachable\([\w-]+\)|"
    r"not-permitted\([\w.-]+\))$")


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


# ── dev #365 (design-connected-entities.md §26.7/§28.2) ──────────────────────────────────────
# Deliberately placed OUTSIDE `_main()`, far from every per-store loop above: this is a
# cross-store completeness check over `migrate.STORE_INTRODUCED`, not another per-section
# validator, and it needs nothing any per-section loop already computed — it re-checks file
# existence directly, so it can be added (and later extended) without touching any of them.
#
# `migrate` is imported LAZILY, inside the function, the same caution this file already applies
# to `plays`/`brief` (`migrate.py` itself lazily imports `validate_data` inside functions, never
# at module level, so there is no real cycle either way — but a top-level import here would be
# the one exception to this file's own pattern, for no benefit).
_STORE_INTRODUCTION_EXEMPT = frozenset({
    # ADR-028 / public #62 — legal-absent FOREVER, not merely pre-introduction: a single-resume
    # profile never gets one, at any stamp. `validate_data.py`'s own `resume_variants` load
    # above already documents this; this is the same rule, never re-litigated here.
    "resume_variants.jsonl",
    # Query or Citation C1 — created lazily by `brief.py`'s `append_ledger()` (`os.makedirs` +
    # append-mode) and deliberately not in `init_profile.STORES`. Absence is this store's normal
    # resting state between the first brief and the first draft that needs one, not a sign of
    # data loss, so it is exempt the same way `resume_variants.jsonl` is. Listed here for the
    # same reason companies/channels/opportunities/messages are below: legible, even though it
    # is currently a no-op — `migrate.STORE_INTRODUCED` deliberately carries no entry for the
    # ledger at all (its own comment says why: naming it there is exactly the bare-literal shape
    # `check_ledger_reads.py`'s rule (a) refuses outside its three readers), so this loop never
    # actually sees "briefs.jsonl" to exempt. If that ever changes, this line is already correct.
    "briefs.jsonl",
    # `companies.jsonl`/`channels.jsonl`/`opportunities.jsonl` already gate `_main()`'s own
    # entry (any one of the three absent returns "pre-migration, nothing to check" before this
    # function is ever reached) — excluded here only so the exclusion is legible; it is a
    # no-op, since this function never runs when any of the three is missing.
    "companies.jsonl", "channels.jsonl", "opportunities.jsonl",
    # `messages.jsonl` is already unconditionally required by the load at its own call site
    # above (`problems += e or []` with no `is None` guard) — including it here too would
    # double-report the same absence under two different messages.
    "messages.jsonl",
})


def check_store_introduction(problems):
    """dev #365 — a governed store absent below the version that introduced it is legal (the
    profile predates it, or was never stamped at all); absent AT OR PAST that version is a
    validator failure naming the store, the stamp, and the version, because a migrated profile
    that lost a file is a materially different fact than one that never had a reason for it
    yet — and nothing before this function told the two apart.

    ⭐ THE STAMP IS READ FROM `DATA`'S OWN PARENT, NEVER FROM THE MODULE-LEVEL `ROOT`. `ROOT` is
    computed once, at import time, from whatever `_profile_root()` resolves for the WHOLE
    process — and a great many existing tests only ever override `DATA` (directly, or via
    `CLAUDESEARCH_DATA_DIR`), because nothing before this function ever cared what `ROOT` was.
    Reading the stamp from `ROOT` while checking file existence against `DATA` mixes two
    profiles whenever they diverge, which — confirmed by running the full suite while building
    this — is most of the time: 23 pre-existing tests failed this way on the first pass, every
    one of them a synthetic profile whose `DATA` pointed at a temp directory with no stamp file
    while `ROOT` still resolved to whatever the test PROCESS had (the tracked fixture, stamped
    0.18.0, in this suite's own case), so every one of those was falsely told it was a stamped,
    migrated profile missing several stores. `os.path.dirname(DATA)` is the profile these
    stores actually belong to — identical to `ROOT` whenever `DATA` is the ordinary
    `<profile>/data`, and correct instead of stale whenever a caller (a test, or a future
    script) points `DATA` somewhere else without also repointing `ROOT`."""
    import migrate as _migrate
    stamp = _migrate.read_stamp(os.path.dirname(DATA))
    for store, introduced_at in sorted(_migrate.STORE_INTRODUCED.items()):
        if store in _STORE_INTRODUCTION_EXEMPT:
            continue
        if os.path.exists(os.path.join(DATA, store)):
            continue
        if _migrate.store_absence_legal(stamp, store):
            continue
        problems.append(
            "%s: absent, but the profile is stamped %s and %s introduced this store at or "
            "before that — a migrated profile is missing a file, not merely pre-dating it"
            % (store, stamp, introduced_at))


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

    # ---- people / involvements (ADR-031 B1) — validated before messages/outreach, both of
    # which now join to `people` by `person_id` rather than to a nested contacts[] row. -------
    people, e = load("people.jsonl")
    if people is None:
        people = []
    else:
        problems += e or []
    involvements, e = load("involvements.jsonl")
    if involvements is None:
        involvements = []
    else:
        problems += e or []

    people_ids = set()
    _company_ids_for_people = {c.get("id") for c in companies}
    for i, pr in enumerate(people):
        pl = "people[%s]" % pr.get("id", i)
        for f in ("id", "name", "status"):
            req(pr, f, pl, problems)
        if pr.get("id") in people_ids:
            problems.append("%s: duplicate id" % pl)
        people_ids.add(pr.get("id"))
        enum(pr, "status", PEOPLE_STATUS, pl, problems)
        em = pr.get("email")
        if em and not re.match(r"^[\w.+-]+@[\w.-]+\.\w{2,}$", em):
            problems.append("%s: email %r is not an address" % (pl, em))
        es = pr.get("email_status")
        if es is not None and es not in CONTACT_EMAIL_STATUS:
            problems.append("%s: email_status %r not in {%s}"
                            % (pl, es, ", ".join(sorted(CONTACT_EMAIL_STATUS))))
        # ADR-031 B4 (design §14) — the first stage that actually READS `people.cadence`:
        # elapsed DAYS (an integer), never a named enum — "last touch + cadence <= today" is
        # arithmetic, unlike a channel's own named CADENCES.
        cad = pr.get("cadence")
        if cad is not None and not (isinstance(cad, int) and not isinstance(cad, bool)
                                    and cad > 0):
            problems.append("%s: cadence %r must be a positive integer (days) or null" % (pl, cad))
        if pr.get("company_id") is not None and pr["company_id"] not in _company_ids_for_people:
            problems.append("%s: company_id %r does not resolve" % (pl, pr["company_id"]))
        mi = pr.get("merged_into")
        if pr.get("status") == "merged" and not mi:
            problems.append("%s: status 'merged' requires 'merged_into'" % pl)
        if mi is not None and pr.get("status") != "merged":
            problems.append("%s: merged_into set but status is %r — merging is what makes "
                            "merged_into meaningful" % (pl, pr.get("status")))
    # merged_into must resolve, and the chain it forms must be ACYCLIC (design §3: "the chain
    # must be acyclic, validator-enforced") — checked as a SECOND pass so forward references
    # (an id merged into one that appears later in the file) are legal.
    for pr in people:
        mi = pr.get("merged_into")
        if mi is None:
            continue
        pl = "people[%s]" % pr.get("id", "?")
        if mi not in people_ids:
            problems.append("%s: merged_into %r does not resolve to any people row" % (pl, mi))
            continue
        seen = {pr.get("id")}
        cur = mi
        by_id = {p.get("id"): p for p in people}
        while cur is not None:
            if cur in seen:
                problems.append("%s: merged_into chain cycles back to itself via %r"
                                % (pl, cur))
                break
            seen.add(cur)
            nxt = by_id.get(cur)
            cur = nxt.get("merged_into") if nxt else None
        for other in pr.get("not_same_as") or []:
            if other not in people_ids:
                problems.append("%s: not_same_as %r does not resolve to any people row"
                                % (pl, other))

    inv_seen_pairs = set()
    for i, ir in enumerate(involvements):
        il = "involvements[%s]" % i
        req(ir, "person_id", il, problems)
        pid = ir.get("person_id")
        if pid is not None and pid not in people_ids:
            problems.append("%s: person_id %r does not resolve to any people row" % (il, pid))
        opp_id, chan_id = ir.get("opp_id"), ir.get("channel_id")
        if bool(opp_id) == bool(chan_id):
            problems.append("%s: exactly one of opp_id/channel_id must be set (got opp_id=%r, "
                            "channel_id=%r)" % (il, opp_id, chan_id))
        if opp_id is not None and opp_id not in {o.get("id") for o in opps}:
            problems.append("%s: opp_id %r does not resolve" % (il, opp_id))
        if chan_id is not None and chan_id not in {c.get("id") for c in (channels or [])}:
            problems.append("%s: channel_id %r does not resolve" % (il, chan_id))
        pt = ir.get("path_type")
        if pt is not None and pt not in PATH_TYPES:
            problems.append("%s: path_type %r not in {%s}"
                            % (il, pt, ", ".join(sorted(PATH_TYPES))))
        pair = (pid, opp_id or chan_id)
        if pair in inv_seen_pairs:
            problems.append("%s: duplicate involvement for (person_id=%r, %s=%r)"
                            % (il, pid, "opp_id" if opp_id else "channel_id", opp_id or chan_id))
        inv_seen_pairs.add(pair)

    all_person_ids = people_ids

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
        # ⭐ A MESSAGE'S person_id MUST RESOLVE — to a `people` row (ADR-031 B1; was: "to an
        # opportunity's contacts[] OR a channel's" before people/involvements existed).
        # Added 2026-08-04 after THREE guessed ids passed unnoticed in one afternoon:
        # 'derek-holland' for 'derek-holland-acme', 'priya-nakamura' for
        # 'priya-nakamura-globex', and a contact anchored to the wrong firm entirely just to
        # satisfy the anchor rule. A join key that does not join is worse than no key: it makes
        # "what is the whole history with X?" silently return nothing instead of failing.
        mpid = m.get("person_id")
        if mpid and mpid not in all_person_ids:
            problems.append("%s: person_id %r resolves to no people row. A guessed id "
                            "silently breaks every person-level query." % (ml, mpid))
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
        # ADR-027 — `surface` is genuinely optional at the schema level (an undeclared surface
        # is resume_variants.py's own 'unplaced' STATE, never a schema violation) — the same
        # `.get()` + validate-only-if-present shape `union_sha`/`union_reconciled_on` already
        # use below, not `enum()`'s `nullable`, which only excuses an explicit `null` and
        # would refuse every row missing the key outright. `visibility` is never stored here
        # at all — it is DERIVED from `surface` by _surfaces.visibility(), never a field.
        sf = r.get("surface")
        if sf is not None and sf not in _surfaces.names():
            problems.append("%s: surface %r not declared in surfaces.py (known: %s) — "
                            "resume_variants.py reports an undeclared surface as 'unplaced', "
                            "loud, never guessed either way"
                            % (label, sf, ", ".join(_surfaces.names())))
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

    # ---- cover_letters (ADR-031 B2) — resume_variants' twin. Validated BEFORE applications so
    # applications[].cover_letter_id can resolve against cover_letter_ids below. -------------
    cover_letters, e = load("cover_letters.jsonl")
    if cover_letters is None:
        cover_letters = []
    else:
        problems += e or []
    cover_letter_ids = set()
    _opp_id_set = {o.get("id") for o in opps if o.get("id")}
    for r in cover_letters:
        clid = r.get("id", "?")
        label = "cover_letters[%s]" % clid
        for f in ("id", "opp_id"):
            req(r, f, label, problems)
        if r.get("id"):
            if r["id"] in cover_letter_ids:
                problems.append("%s: duplicate id" % label)
            cover_letter_ids.add(r["id"])
        oid = r.get("opp_id")
        if oid is not None and oid not in _opp_id_set:
            problems.append("%s: opp_id %r does not resolve" % (label, oid))
        cr = r.get("created")
        if cr is not None and not is_date(cr):
            problems.append("%s: created not ISO — %r" % (label, cr))
        # `status` is deliberately NULLABLE here (not required, unlike resume_variants' own
        # status): a row the 0.45.0 migration preserves verbatim from an inconsistent legacy
        # applications[] row (cover_letter_attached true, cover_letter_doc null) must not have
        # an invented status — "a migration that cannot know a field's type must not interpret
        # it" (design §1). Where present it must still be a real value.
        st = r.get("status")
        if st is not None and st not in COVER_LETTER_STATUS:
            problems.append("%s: status %r not in {%s}"
                            % (label, st, ", ".join(sorted(COVER_LETTER_STATUS))))
        fl = r.get("file")
        if fl is not None and not (isinstance(fl, str) and fl.strip()):
            problems.append("%s: file must be a non-empty path relative to the profile root "
                            "when set" % label)
        doc = r.get("doc")
        if doc is not None and not (isinstance(doc, str) and doc.strip()):
            problems.append("%s: doc must be a non-empty reference when set" % label)

    # ---- applications (ADR-031 B2) — promoted from opportunities.applications[]. `id` is the
    # store's own id_field (= the old app_id, unchanged VALUE); `opp_id` is a required FK —
    # "resolve this application" is now a dictionary lookup, never an own-record array walk
    # (design §1). apps_by_opp is built here once and reused below for every own-record trigger
    # check the removed nested array used to answer locally. ------------------------------------
    applications, e = load("applications.jsonl")
    if applications is None:
        applications = []
    else:
        problems += e or []
    app_ids_seen = set()
    apps_by_opp = {}
    for r in applications:
        aid = r.get("id", "?")
        label = "applications[%s]" % aid
        for f in ("opp_id", "date", "method", "status"):
            req(r, f, label, problems)
        if r.get("id"):
            if not (isinstance(r["id"], str) and SLUG_RE.match(r["id"])):
                problems.append("%s: id %r must be a lowercase slug (minted as <opp_id>-aN)"
                                % (label, r["id"]))
            elif r["id"] in app_ids_seen:
                problems.append("%s: duplicate id" % label)
            app_ids_seen.add(r["id"])
        oid = r.get("opp_id")
        if oid is not None and oid not in _opp_id_set:
            problems.append("%s: opp_id %r does not resolve" % (label, oid))
        if oid:
            apps_by_opp.setdefault(oid, []).append(r)
        if r.get("method") not in APPLICATION_METHODS:
            problems.append("%s: method %r not in {%s}"
                            % (label, r.get("method"), ", ".join(sorted(APPLICATION_METHODS))))
        if r.get("status") not in APPLICATION_STATUS:
            problems.append("%s: status %r not in {%s}"
                            % (label, r.get("status"), ", ".join(sorted(APPLICATION_STATUS))))
        if r.get("status") in SUBMITTED_APP_STATUS and not r.get("date"):
            problems.append("%s: status %r but has no date — that is the field the funnel "
                            "analysis runs on" % (label, r.get("status")))
        # States & Views V1 §3c — `status_on`: when the CURRENT `status` was written. Stamped
        # by every record.py status write and the (future) ADR-030 receipt reader; null on
        # history (§3d's migration seeds it explicitly rather than guessing from `date`) — so
        # only an unreadable non-null value is a problem here, never the null itself.
        son = r.get("status_on")
        if son is not None and not is_date(son):
            problems.append("%s: status_on not ISO or null — %r" % (label, son))
        # Which variant actually WENT (public #26) — retired resolves fine here: history must
        # stay attributable forever. UNRESOLVED (public #70's own sentinel, see below) is a
        # legal escape and never "does not resolve".
        arv = r.get("resume_variant")
        if arv is not None and arv != UNRESOLVED and arv not in variant_ids:
            problems.append("%s: resume_variant %r does not resolve in "
                            "data/resume_variants.jsonl — attribution of outcomes to "
                            "positioning depends on this join" % (label, arv))
        cli = r.get("cover_letter_id")
        if cli is not None and cli not in cover_letter_ids:
            problems.append("%s: cover_letter_id %r does not resolve in "
                            "data/cover_letters.jsonl" % (label, cli))
        # form_answers (public #27) — unchanged shape/logic from the pre-B2 nested check.
        fa = r.get("form_answers")
        if fa is not None:
            if not isinstance(fa, list):
                problems.append("%s: form_answers must be a list of "
                                "{question_key, question, answer, answered_on}, got %s"
                                % (label, type(fa).__name__))
                fa = []
            seen_q = set()
            for j, ans in enumerate(fa):
                fl = "%s.form_answers[%d]" % (label, j)
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
        # ⭐⭐ public #70 — once ANY resume variant is DECLARED, a submitted application must
        # carry one. `UNRESOLVED` (the same marker blocked_until/play_stage already use) is the
        # legal escape for a row that predates variants existing — a human decision, never a
        # default this validator invents.
        if (r.get("status") in SUBMITTED_APP_STATUS and variant_ids
                and not r.get("resume_variant")):
            problems.append(
                "%s: status %r but resume_variant is unset while %d resume variant(s) are "
                "declared — outcomes must be attributable to positioning (set resume_variant, "
                "or %r if this application predates variants existing)"
                % (label, r.get("status"), len(variant_ids), UNRESOLVED))
    # ---- messages[].resolves / resolved_by — the resolution relation as a key (ADR-029, ---
    # design-inbound-resolution.md §2). Same shape as `answers` above (a second pass; a message
    # naming an application that appears later in file order is fine), but joined against
    # `applications` rather than `messages`, so it runs here — after both `sent_msgs` (the
    # messages loop, above) and `applications`/`app_ids_seen` (this store's own loop, just
    # above) exist. Five rules, per §2:
    #   1. `resolves` must name an existing `applications.id`.
    #   2. `resolved_by` is required IFF `resolves` is, and must be one of RESOLVED_BY.
    #   3. never both `answers` and `resolves` on the same row (a message either answers a
    #      person or resolves an application, never both — ADR-029).
    #   4. `direction` must be `inbound` (only an employer's own reply resolves an application).
    #   5. the message's own `opp_id` must equal the resolved application's `opp_id` (a row
    #      cannot point at one role while resolving another's application).
    _apps_by_id = {a.get("id"): a for a in applications if a.get("id")}
    for m in (sent_msgs or []):
        if m.get("id") == "_README":
            continue
        ml = "messages[%s]" % m.get("id", "?")
        resolves, resolved_by = m.get("resolves"), m.get("resolved_by")
        if resolves is None and resolved_by is None:
            continue
        if bool(resolves) != bool(resolved_by):
            problems.append("%s: resolves and resolved_by must be set TOGETHER, or not at "
                            "all (ADR-030: the tier that matched is recorded)" % ml)
            continue
        target = _apps_by_id.get(resolves)
        if target is None:
            problems.append("%s: resolves %r does not resolve to any applications row"
                            % (ml, resolves))
            continue
        if resolved_by not in RESOLVED_BY:
            problems.append("%s: resolved_by %r not in {%s}"
                            % (ml, resolved_by, ", ".join(sorted(RESOLVED_BY))))
        if m.get("answers") is not None:
            problems.append("%s: carries both answers %r and resolves %r — a message either "
                            "answers a person or resolves an application, never both (ADR-029)"
                            % (ml, m.get("answers"), resolves))
        if m.get("direction") != "inbound":
            problems.append("%s: resolves %r but direction is %r — only an inbound message "
                            "(the employer's own statement) resolves an application"
                            % (ml, resolves, m.get("direction")))
        if m.get("opp_id") != target.get("opp_id"):
            problems.append("%s: opp_id %r does not match resolves %r's own opp_id %r — a "
                            "message cannot point at one role while resolving another's "
                            "application" % (ml, m.get("opp_id"), resolves, target.get("opp_id")))

    # ---- plans / plays (ADR-031 B4, design §17, §18, §20) — the owner's strategy as data.
    # Loaded and validated BEFORE `opportunities` so `plan_id` can be checked as a real FK in
    # that loop below (the same ordering `cover_letters` already uses ahead of `applications`).
    # `plays.py` is imported LAZILY here (never at module level) because it imports THIS
    # module — see the comment beside the top-level `import plans as _plans`.
    import plays as _plays_mod
    plans_rows, e = load("plans.jsonl")
    if plans_rows is None:
        plans_rows = []
    else:
        problems += e or []
    plays_rows, e = load("plays.jsonl")
    if plays_rows is None:
        plays_rows = []
    else:
        problems += e or []

    play_ids = set()
    for r in plays_rows:
        rid = r.get("id", "?")
        label = "plays[%s]" % rid
        for f in ("id", "steps", "goal", "status"):
            req(r, f, label, problems)
        if r.get("id") in play_ids:
            problems.append("%s: duplicate id" % label)
        play_ids.add(r.get("id"))
        enum(r, "status", _plans.PLAY_STATUS, label, problems)
        sha = r.get("pattern_sha")
        if sha is not None and not SHA12_RE.match(str(sha)):
            problems.append("%s: pattern_sha %r is not 12 hex chars" % (label, sha))
        prc = r.get("pattern_reconciled_on")
        if prc is not None and not is_date(prc):
            problems.append("%s: pattern_reconciled_on not ISO — %r" % (label, prc))
        steps = r.get("steps")
        if not isinstance(steps, list) or not steps:
            problems.append("%s: steps must be a non-empty list" % label)
            steps = []
        step_ids_seen = set()
        for i, s in enumerate(steps):
            sl = "%s steps[%d]" % (label, i)
            if not isinstance(s, dict):
                problems.append("%s: entry is not an object" % sl)
                continue
            sid = s.get("id")
            if not sid:
                problems.append("%s: missing 'id'" % sl)
            elif sid in step_ids_seen:
                problems.append("%s: duplicate step id %r" % (sl, sid))
            step_ids_seen.add(sid)
            do = s.get("do")
            if not isinstance(do, dict) or do.get("kind") not in _plays_mod.DO_KINDS:
                problems.append("%s: do.kind must be one of {%s}"
                                % (sl, ", ".join(sorted(_plays_mod.DO_KINDS))))
            elif do["kind"] == "research" and do.get("find") not in _plays_mod.RESEARCH_FINDS:
                problems.append("%s: do.find must be one of {%s}"
                                % (sl, ", ".join(sorted(_plays_mod.RESEARCH_FINDS))))
            elif do["kind"] == "touch":
                if do.get("touch_type") not in TOUCH_TYPES:
                    problems.append("%s: do.touch_type %r not in {%s}"
                                    % (sl, do.get("touch_type"), ", ".join(sorted(TOUCH_TYPES))))
                if do.get("to") not in _plays_mod.DO_TO_CLASSES:
                    problems.append("%s: do.to must be one of {%s}"
                                    % (sl, ", ".join(sorted(_plays_mod.DO_TO_CLASSES))))
            for j, entry in enumerate(s.get("say") or []):
                sayl = "%s say[%d]" % (sl, j)
                if isinstance(entry, str):
                    if entry not in _plays_mod.SAY_SLUGS:
                        problems.append("%s: %r not in {%s}"
                                        % (sayl, entry, ", ".join(sorted(_plays_mod.SAY_SLUGS))))
                elif isinstance(entry, dict):
                    if entry.get("content") not in _plays_mod.SAY_SLUGS:
                        problems.append("%s: content %r not in {%s}"
                                        % (sayl, entry.get("content"),
                                           ", ".join(sorted(_plays_mod.SAY_SLUGS))))
                else:
                    problems.append("%s: must be a string or {when, content}" % sayl)

        params = r.get("params")
        if params is not None and not isinstance(params, dict):
            problems.append("%s: params must be an object" % label)
            params = {}
        for name, spec in (params or {}).items():
            pl = "%s params[%s]" % (label, name)
            if isinstance(spec, bool) or not isinstance(spec, (int, float, dict)):
                problems.append("%s: must be an integer or an object" % pl)
                continue
            if isinstance(spec, (int, float)):
                continue
            days = spec.get("days")
            if not isinstance(days, int) or isinstance(days, bool):
                problems.append("%s: 'days' must be an integer" % pl)
            mn, mx = spec.get("min"), spec.get("max")
            if days is not None and mn is not None and mx is not None and not (mn <= days <= mx):
                problems.append("%s: days=%r is outside its own bound [%s, %s]"
                                % (pl, days, mn, mx))
            arms = spec.get("unless") or []
            if arms and not (spec.get("why") or "").strip():
                problems.append("%s: 'why' is required whenever a parameter has more than one "
                                "value (a base plus at least one arm)" % pl)
            elif not arms and not (spec.get("why") or "").strip():
                problems.append("%s: 'why' is required" % pl)
            for j, arm in enumerate(arms):
                al = "%s unless[%d]" % (pl, j)
                if not (arm.get("why") or "").strip():
                    problems.append("%s: 'why' is required on every arm" % al)
                adays = arm.get("days")
                if adays is not None and mn is not None and mx is not None \
                        and not (mn <= adays <= mx):
                    problems.append("%s: days=%r is outside the parameter's bound [%s, %s]"
                                    % (al, adays, mn, mx))
                # ⭐ Predicate-grammar validation for the ARM'S OWN `when` — design §18/§24.1:
                # an arm chooses its value by the SAME closed vocabulary a step does. Caught
                # by PLANT (gate-keeper, this dispatch): a mutated arm token
                # ('not-a-real-token') validated CLEAN until this call was added — the step/
                # goal validation below does not reach INTO params[].unless[].when at all.
                _plays_mod.validate_when(arm.get("when") or [], r, problems, "%s.when" % al)
        # Predicate-grammar validation — every `when` (steps and goal) parsed against THIS
        # play's own step ids and parameter names (design §18: "an unknown token, an undeclared
        # <param>, a <step> not in the play... fails validate_data.py with the token named").
        for s in steps:
            if isinstance(s, dict):
                _plays_mod.validate_when(s.get("when") or [], r, problems,
                                        "%s steps[%r].when" % (label, s.get("id")))
        goal = r.get("goal")
        if goal:
            _plays_mod.validate_when([goal], r, problems, "%s.goal" % label)

    plays_by_id = {r.get("id"): r for r in plays_rows if r.get("id")}
    _plans_by_id = {}
    for r in plans_rows:
        rid = r.get("id", "?")
        label = "plans[%s]" % rid
        for f in ("id", "subject_kind", "subject_id", "status"):
            req(r, f, label, problems)
        if r.get("id") in _plans_by_id:
            problems.append("%s: duplicate id" % label)
        _plans_by_id[r.get("id")] = r
        enum(r, "subject_kind", _plans.SUBJECT_KINDS, label, problems)
        enum(r, "status", _plans.PLAN_STATUS, label, problems)
        sk = r.get("subject_kind")
        outs = r.get("outcomes")
        if sk == "search" and not outs:
            problems.append("%s: subject_kind 'search' requires a non-empty outcomes[]" % label)
        if outs is not None:
            if not isinstance(outs, list) or any(x not in _plans.OUTCOMES for x in outs):
                problems.append("%s: outcomes %r must be a list drawn from {%s}"
                                % (label, outs, ", ".join(sorted(_plans.OUTCOMES))))
        play_id = r.get("play_id")
        if play_id is not None:
            if sk == "person":
                problems.append("%s: subject_kind 'person' governs no pursuit — play_id must "
                                "be null (design §17)" % label)
            elif play_id != _plans.MANUAL_PLAY and play_id not in play_ids:
                problems.append("%s: play_id %r does not resolve in data/plays.jsonl and is "
                                "not the literal 'manual'" % (label, play_id))
        pc = r.get("play_confirmed")
        if play_id not in (None,) and pc is None:
            problems.append("%s: play_confirmed is required whenever play_id names a play "
                            "(design §26.1(d) — an unconfirmed play acts on nothing outward)"
                            % label)
        if pc is not None and not isinstance(pc, bool):
            problems.append("%s: play_confirmed must be a boolean" % label)
        rw = r.get("resolves_when")
        if rw is not None and rw not in _plans.RESOLVES_WHEN:
            problems.append("%s: resolves_when %r not in {%s}"
                            % (label, rw, ", ".join(sorted(_plans.RESOLVES_WHEN))))
        ro, res = r.get("resolved_on"), r.get("resolution")
        if bool(ro) != bool(res):
            problems.append("%s: resolved_on and resolution come together — one without the "
                            "other cannot be audited (the asks contract, copied)" % label)
        if ro is not None and not is_date(ro):
            problems.append("%s: resolved_on not ISO — %r" % (label, ro))
        tg = r.get("targets")
        if tg is not None and not isinstance(tg, dict):
            problems.append("%s: targets must be an object ({\"titles\": [...], "
                            "\"verticals\": [...]})" % label)

    # design §26.5 — two ACTIVE search plans that both source role/contract must differ in
    # their EFFECTIVE targets, or sourcing cannot tell them apart. Compared pairwise, naming
    # both ids on a match (§28.2's own decidability restatement).
    try:
        import profile as _profile_for_targets
        _cfg_for_targets = _profile_for_targets.config()
    except Exception:                                             # noqa: BLE001 — advisory
        _cfg_for_targets = {}
    _sourcing = _plans.sourcing_candidates(plans_rows)
    for i, p1 in enumerate(_sourcing):
        for p2 in _sourcing[i + 1:]:
            if _plans.effective_targets(p1, _cfg_for_targets) == \
                    _plans.effective_targets(p2, _cfg_for_targets):
                problems.append("plans[%s]/plans[%s]: both active search plans source role/"
                                "contract with the SAME effective targets — sourcing cannot "
                                "tell them apart (design §26.5)" % (p1.get("id"), p2.get("id")))

    company_ids, channel_ids = set(), set()

    # ⭐ RETIRED-KEY REFUSAL (ADR-031 §28.1 item 3) — computed once, used by both the
    # opportunities guard below and the channels loop further down. See the block comment on
    # RETIRED_KEYS/active_retired_keys() above: this resolves to {} until B1 ships.
    _active_retired = active_retired_keys()

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
            for _k, _stage in _active_retired.items():
                # A key that is ALSO a banned alias (play_stage/next_action, B4 — design §19)
                # gets its own, more specific message from the banned-alias loop just below;
                # printing both would say the same thing twice.
                if _k in r and _k not in _ali:
                    problems.append("%s: %r is retired (%s promoted it to its own store) — "
                                    "refused, not merely unknown. Run the %s migration before "
                                    "writing this key again." % (_l, _k, _stage, _stage))
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

    # ADR-031 B5 — `plans.assessments[]`, checked once the model is in hand (its field lists come
    # from data_model.json, never restated here). Nothing writes the field yet (item C of
    # design-b5-assessment.md §9); the contract is enforced from the day the field exists.
    for r in plans_rows:
        check_assessments(r, plays_by_id.get(r.get("play_id")), _model,
                          "plans[%s]" % r.get("id", "?"), problems)

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
        # ⭐ RETIRED-KEY REFUSAL, channel side (ADR-031 §28.1 item 3; design §2's "what keeps it
        # honest" item 3: "contacts on a channel join the unknown-key guard"). `_active_retired`
        # is computed once, above, from active_retired_keys() — {} until B1 ships. Iterates the
        # dict (as the opportunities-side check above already does) rather than subscripting a
        # literal key — see `active_retired_keys()`'s own comment on why that also keeps this
        # module out of `check_retired_reads.py`'s own (harmless but avoidable) false positives.
        for _ck, _cstage in _active_retired.items():
            if _ck in r:
                problems.append("%s: %r is retired (%s promoted it to its own store) — "
                                "refused, not merely unknown. Run the %s migration before "
                                "writing this key again." % (label, _ck, _cstage, _cstage))
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

    # ---- messages[].channel_id — the FK half of public #63 ----------------------------------
    # Since ADR-031 B1/B3 a message joins by `person_id` (required to resolve when set) and
    # `opp_id: null` is a LEGAL row (a message to a person about no role — see the anchor check
    # above). What is NOT legal is a `channel_id` that resolves nowhere: asks/commitments/briefs/
    # touches have all checked their own `channel_id` against `channel_ids` since B1 shipped
    # (each below or above this block), but the messages loop runs BEFORE `channel_ids` exists
    # (people/involvements/messages are validated ahead of companies/channels — see that block's
    # own comment) and nothing ever came back to close the gap once the set existed. A dangling
    # `channel_id` here is exactly what a referential check exists for — a message silently
    # unreachable from the relationship it names, which is how a stale thread and a decision to
    # cold-approach the same channel can coexist with nothing in the store admitting it.
    for m in (sent_msgs or []):
        if m.get("id") == "_README":
            continue
        mcid = m.get("channel_id")
        if mcid is not None and mcid not in channel_ids:
            problems.append("messages[%s]: channel_id %r does not resolve"
                            % (m.get("id", "?"), mcid))

    # public #83 rule 1 — channel_id -> type, for the sighting source_url check in the
    # opportunities loop below. Built once from the already-loaded `channels` rows (not
    # `channel_ids`, which only ever tracked membership, never the type).
    channel_type_by_id = {c.get("id"): c.get("type") for c in channels}

    # ---- opportunities ----
    opp_ids = set()
    # States & Views V1b (design §15.3 point 2) — every touches[].message_ref seen, across
    # EVERY touch, so the touched-orphan check below (after the touches section) can tell a
    # `record.py touched` message that landed with no completing touches row apart from
    # one that is genuinely still mid-write from a caller who has not gotten to the second
    # append yet — the SAME half-written case a crash between the two appends produces.
    # ADR-031 B3 — was `outreach_message_refs`; populated from the top-level `touches` store
    # now, never from a nested array.
    touch_message_refs = set()
    # opp id -> plan_id, populated below as each opportunity is validated — read back by the
    # touches loop's own plan_id/play_step check (design §21's re-planned-pursuit warning).
    r_opp_plan_id_by_id = {}
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

        # ⭐ States & Views V1 §3a — `decision{}`, the divergence reason as a FIELD, not a note.
        # {"on": ISO date, "suggested": "pursue"|"pass"|null, "reason_kind": <enum>|null,
        # "reason": str|null}. `suggested` freezes what `your_move.triage_suggestion()` returned
        # AT THE MOMENT the verdict was written — a fact about that event, never re-derived.
        # `reason_kind`/`reason` are required IFF `suggested` is non-null and differs from the
        # verdict actually on the record: an override with no reason is a decision nobody can
        # audit later, which is exactly the gap this field exists to close.
        dec = r.get("decision")
        if dec is not None:
            if not isinstance(dec, dict):
                problems.append("%s: decision must be an object — got %s: %r"
                                % (label, type(dec).__name__, dec))
            else:
                if not is_date(dec.get("on", "")):
                    problems.append("%s: decision.on not ISO — %r" % (label, dec.get("on")))
                sug = dec.get("suggested")
                if sug is not None and sug not in ("pursue", "pass"):
                    problems.append("%s: decision.suggested %r not in {pursue, pass, null}"
                                    % (label, sug))
                rk = dec.get("reason_kind")
                if rk is not None and rk not in DECISION_REASON_KINDS:
                    problems.append("%s: decision.reason_kind %r not in {%s, null}"
                                    % (label, rk, ", ".join(sorted(DECISION_REASON_KINDS))))
                rs = dec.get("reason")
                if rs is not None and not isinstance(rs, str):
                    problems.append("%s: decision.reason must be a string or null — %r"
                                    % (label, rs))
                diverges = sug is not None and sug != r.get("verdict")
                if diverges and not (rk and (rs or "").strip()):
                    problems.append(
                        "%s: decision.suggested=%r differs from verdict=%r — reason_kind and "
                        "reason are required when a decision diverges from the engine's own "
                        "suggestion (design-states-and-views.md §3a)"
                        % (label, sug, r.get("verdict")))

        # ⭐ States & Views V1 §3b — `networking_closed_on`: the owner's decision to stop
        # working the network on this pursuit. Owner-written, dated, NEVER derived (the
        # next_action_date rule) and NEVER cleared — it is compared against the newest
        # outbound event, not reset by a later touch (§3b/§15.3; your_move.networking_in_force()
        # is the reader).
        nco = r.get("networking_closed_on")
        if nco is not None and not is_date(nco):
            problems.append("%s: networking_closed_on not ISO — %r" % (label, nco))

        # ⭐ A DECISION MADE BY ACTING (dev/audit 2026-09-02, Class A / public #44). A row can
        # say `verdict: undecided` while an applications row proves a submission — the human
        # decided by applying and the field never followed. Left alone it renders a
        # pursue-or-pass ask for a role already applied to. m_0_36_0_verdict_from_applications
        # resolves history; this refuses the contradiction from here on.
        submitted = any(a.get("status") in SUBMITTED_APP_STATUS
                        for a in apps_by_opp.get(r.get("id"), []))
        if r.get("verdict") == "undecided" and submitted:
            problems.append("%s: verdict 'undecided' but an applications row is already %s "
                            "— the act decided; the store already answers this (pursue)"
                            % (label, "/".join(sorted(SUBMITTED_APP_STATUS))))

        # ---- plan_id (ADR-031 B4, design §17) — required on every non-terminal opportunity;
        # kept (nullable) once terminal. The subject rule: a `company`-subject plan may only
        # govern a pursuit at that company, an `opportunity`-subject plan only the one it
        # names — enforced here rather than in `plans.py` because it is a fact about THIS row.
        pid_plan = r.get("plan_id")
        if pid_plan:
            r_opp_plan_id_by_id[oid] = pid_plan
        if pid_plan is None:
            if r.get("status") not in TERMINAL_OPP_STATUSES:
                problems.append("%s: plan_id is required while the pursuit is live (design "
                                "§17) — every pursuit is governed by a plan" % label)
        else:
            plan = _plans_by_id.get(pid_plan)
            if plan is None:
                problems.append("%s: plan_id %r does not resolve in data/plans.jsonl" % (label, pid_plan))
            elif not _plans.governs(plan, r):
                problems.append("%s: plan_id %r (subject_kind=%r, subject_id=%r) does not "
                                "govern this pursuit (design §17's subject rule)"
                                % (label, pid_plan, plan.get("subject_kind"), plan.get("subject_id")))
        pad = r.get("plan_assigned_on")
        if pad is not None and not is_date(pad):
            problems.append("%s: plan_assigned_on not ISO — %r" % (label, pad))

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

        # ---- engagement_type (ADR-031 B2, design §1/§16 item 3) — full-time | contract, a
        # fact about the ROLE, defaulted by the 0.45.0 migration; nullable pre-migration. ----
        et = r.get("engagement_type")
        if et is not None and et not in ENGAGEMENT_TYPES:
            problems.append("%s: engagement_type %r not in {%s}"
                            % (label, et, ", ".join(sorted(ENGAGEMENT_TYPES))))

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
        # public #83 rule 1 — the same two exclusions doctor.py's check_linkless_sightings
        # (#360) computes, for the SAME reason: recruiter-sourced (the record's own channel_id,
        # or any of its sightings' channel_id, resolves to a channel of type 'recruiter' — there
        # was never a public posting to link) and receipt-backed (an applications.jsonl row for
        # this opportunity carries a status in SUBMITTED_APP_STATUS — the application itself is
        # durable evidence the role existed). Computed once per record, reused per-sighting below.
        _referenced_channels = {r.get("channel_id")} | {sg.get("channel_id") for sg in sightings}
        _recruiter_sourced = any(channel_type_by_id.get(cid) == "recruiter"
                                 for cid in _referenced_channels if cid)
        _receipted = any(a.get("status") in SUBMITTED_APP_STATUS
                        for a in apps_by_opp.get(r.get("id"), []))
        for i, sg in enumerate(sightings):
            scid = sg.get("channel_id")
            if scid not in channel_ids:
                problems.append("%s: sighting[%d].channel_id %r does not resolve" % (label, i, scid))
            _sg_date_ok = is_date(sg.get("seen_on", ""))
            if not _sg_date_ok:
                problems.append("%s: sighting[%d].seen_on not ISO — %r" % (label, i, sg.get("seen_on")))
            # ⭐ public #83 rule 1, hard PROBLEM half (record.py's capture-time refusal is the
            # other half — this is the backstop for a row that reached the store some other
            # way: a migration, a hand-authored fixture, or a write predating the refusal).
            # Only a sighting dated ON OR AFTER SOURCE_URL_REQUIRED_SINCE is in scope — an
            # older one is doctor.py's advisory's business (#360), never turned red here. Gated
            # on the date actually being ISO (checked just above) so an unparseable seen_on is
            # reported once, as the date problem, never a second time by string-comparing junk.
            if (_sg_date_ok and not sg.get("source_url")
                    and channel_type_by_id.get(scid) in URL_BEARING_CHANNEL_TYPES
                    and not _recruiter_sourced and not _receipted
                    and sg.get("seen_on", "") >= SOURCE_URL_REQUIRED_SINCE):
                problems.append(
                    "%s: sighting[%d] from channel %r (type %r) has no source_url and is "
                    "dated %s (on/after %s) — public #83 rule 1: a sighting from a "
                    "URL-bearing channel (job-board/aggregator) must carry its URL at the "
                    "moment it is captured"
                    % (label, i, scid, channel_type_by_id.get(scid), sg.get("seen_on"),
                       SOURCE_URL_REQUIRED_SINCE))

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
        # ⭐ ADR-031 B3 — `outreach[]` is RETIRED (the retired-key guard above already refuses
        # it on write, once touches.py exists). Every former outreach[] row is now a `touches`
        # row, validated in its OWN top-level section below (mirroring `applications`'/
        # `cover_letters`' own promotion out of this loop in B2) — there is nothing left to
        # check on `r` itself here.
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

    # ---- touches (ADR-031 B3) — promoted from opportunities.outreach[]. `id` is minted
    # `<person_id>-tN` by record.py; `person_id` is a required FK; `opp_id`/`channel_id` are
    # BOTH optional (public #53 — a touch to a person about no role, or anchored only to a
    # channel, is now a legal row; the network capability's basis). Structurally the SAME
    # per-row checks the nested outreach[] loop used to run, moved out to their own top-level
    # section the same way B2 promoted applications[] — this is the one site every reader that
    # used to walk `opportunity["outreach"]` by hand is re-pointed away from. ------------------
    touches, e = load("touches.jsonl")
    if touches is None:
        touches = []
    else:
        problems += e or []
    touch_ids_seen = set()
    # Per-anchor involvement sets, computed ONCE from the GLOBAL `involvements` list (the same
    # join the old per-opportunity `person_ids_for_opp` performed, now needed for touches
    # anchored to either an opportunity OR a channel, never both required at once).
    _inv_by_opp = {}
    _inv_by_channel = {}
    for _i in involvements:
        if _i.get("opp_id") and _i.get("person_id"):
            _inv_by_opp.setdefault(_i["opp_id"], set()).add(_i["person_id"])
        if _i.get("channel_id") and _i.get("person_id"):
            _inv_by_channel.setdefault(_i["channel_id"], set()).add(_i["person_id"])
    for i, t in enumerate(touches):
        tid = t.get("id", "?")
        label = "touches[%s]" % tid
        req(t, "person_id", label, problems)
        if t.get("id"):
            if t["id"] in touch_ids_seen:
                problems.append("%s: duplicate id" % label)
            touch_ids_seen.add(t["id"])
        pid = t.get("person_id")
        if pid and pid not in all_person_ids:
            problems.append("%s: person_id %r does not resolve to any people row" % (label, pid))
        oid2 = t.get("opp_id")
        if oid2 is not None and oid2 not in opp_ids:
            problems.append("%s: opp_id %r does not resolve" % (label, oid2))
        tcid = t.get("channel_id")
        if tcid is not None and tcid not in channel_ids:
            problems.append("%s: channel_id %r does not resolve" % (label, tcid))
        # ⭐⭐ A MEDIUM IS NOT A RELATIONSHIP — enforced HERE, not only in the test suite (see
        # the history in this file's own git log for why this moved out of the test suite once
        # already; carried over verbatim from the pre-B3 nested check).
        if tcid in RETIRED_CHANNEL_IDS:
            problems.append(
                "%s: channel_id %r is a MEDIUM, not a relationship — it is retired. Put the "
                "medium in 'medium' (%s) and leave channel_id null unless a real relationship "
                "(a firm or referrer) carried the message."
                % (label, tcid, ", ".join(sorted(MEDIA))))
        # §12 — the object of the touch, when it is not the recipient (an introduction ask).
        opid_obj = t.get("object_person_id")
        if opid_obj is not None and opid_obj not in all_person_ids:
            problems.append("%s: object_person_id %r does not resolve to any people row"
                            % (label, opid_obj))
        ocid_obj = t.get("object_company_id")
        if ocid_obj is not None and ocid_obj not in company_ids:
            problems.append("%s: object_company_id %r does not resolve" % (label, ocid_obj))
        if t.get("status") not in OUTREACH_STATUS:
            problems.append("%s: status %r not in {%s}"
                            % (label, t.get("status"), ", ".join(sorted(OUTREACH_STATUS))))
        if t.get("outcome") is not None and t["outcome"] not in OUTREACH_OUTCOME:
            problems.append("%s: outcome %r not in {%s}"
                            % (label, t.get("outcome"), ", ".join(sorted(OUTREACH_OUTCOME))))
        # Unknown-key/banned-alias rejection for `touches` is the GENERIC model-driven guard
        # below (same one applications/cover_letters/asks/commitments/variants/briefs use) —
        # never a second, dedicated set here; two lists of one store's field names is exactly
        # the drift this file's own comment on RETIRED_KEYS/`docs/data_model.json` already
        # names. `to` and `date` were never required or type-checked before 2026-08-02.
        if t.get("status") == "sent":
            if not (t.get("to") or "").strip():
                problems.append("%s: status='sent' requires a non-empty 'to'" % label)
            if not is_when(t.get("date") or ""):
                problems.append("%s: status='sent' requires an ISO 'date' — an undated row "
                                "makes check_followups over-report silence" % label)
        elif t.get("date") is not None and not is_when(t.get("date")):
            problems.append("%s: date %r is neither an ISO date nor 'YYYY-MM-DD HH:MM'"
                            % (label, t.get("date")))
        # ---- the reply side, as stored data (dev/audit 2026-09-02, Class B) ----
        ro3 = t.get("responded_on")
        if ro3 is not None:
            if not is_when(ro3):
                problems.append("%s: responded_on %r is neither an ISO date nor "
                                "'YYYY-MM-DD HH:MM'" % (label, ro3))
            elif precedes(ro3, t.get("date")):
                problems.append("%s: responded_on %s is before the row's own date %s — a "
                                "reply cannot precede the message it answers"
                                % (label, ro3, t["date"]))
        # A reply LINKED in the store (messages[].answers names this row's message) while the
        # row still records no response is a contradiction the data itself can see.
        _mref = t.get("message_ref")
        if _mref and _mref in answered_by and not t.get("responded_on"):
            problems.append("%s: still awaiting, but messages[%s] answers its message_ref %r "
                            "— set responded_on (and outcome) on the row"
                            % (label, "/".join(str(x) for x in answered_by[_mref]), _mref))
        for fld, allowed in (("medium", MEDIA), ("touch_type", TOUCH_TYPES),
                             ("recipient_role", RECIPIENT_ROLES), ("delivery", DELIVERY)):
            v = t.get(fld)
            if v is not None and v not in allowed:
                problems.append("%s: %s=%r not in {%s}" % (label, fld, v, ", ".join(sorted(allowed))))
        if t.get("address_status") is not None and t["address_status"] not in ADDRESS_STATUS:
            problems.append("%s: address_status=%r not in {%s}"
                            % (label, t["address_status"], ", ".join(sorted(ADDRESS_STATUS))))
        # An email medium without an address_status can't distinguish a bounce from silence.
        if (t.get("medium") or "").startswith("email") and not t.get("address_status"):
            problems.append("%s: medium=%r requires 'address_status' — otherwise a bounced "
                            "pattern-inferred address is indistinguishable from a non-reply"
                            % (label, t.get("medium")))
        # From the cutover, the comms fields are required (history carries 'unknown').
        if (t.get("date") or "") >= COMMS_CUTOVER and t.get("status") == "sent":
            for fld in ("medium", "touch_type", "recipient_role", "delivery"):
                if not t.get(fld):
                    problems.append("%s: '%s' is required on rows dated %s or later"
                                    % (label, fld, COMMS_CUTOVER))
        # THE JOIN (ADR-031 B1: `person_id`, was `contact_id`). When the touch names an
        # opportunity, the person must be INVOLVED IN THAT OPPORTUNITY — otherwise "what is
        # the whole history with this person?" is unanswerable. A touch with no opp_id (a
        # channel-anchored or fully unanchored network touch, public #53) skips this specific
        # check — there is no single opportunity's involvement list to resolve against, and
        # `person_id` resolving to a real person (checked above) is the join that DOES apply.
        if pid and oid2 and pid not in _inv_by_opp.get(oid2, ()):
            problems.append("%s: person_id %r does not resolve to an involvement on "
                            "opportunity %r" % (label, pid, oid2))

        if t.get("message_ref") and t["message_ref"] not in sent_ids:
            problems.append("%s: message_ref %r does not resolve in data/messages.jsonl — a "
                            "pointer to text that isn't there is worse than no pointer"
                            % (label, t["message_ref"]))
        if t.get("message_ref"):
            touch_message_refs.add(t["message_ref"])
        if t.get("campaign_id") and not re.match(r"^[a-z0-9][a-z0-9-]*$", t["campaign_id"]):
            problems.append("%s: campaign_id %r must be a lowercase slug" % (label, t["campaign_id"]))
        # What caused this touch (public #27) — shared with asks, see check_trigger. Own-record
        # rule: an 'application' ref resolves against THIS TOUCH'S OWN opp_id's applications
        # (never a nested array walk any more — ADR-031 B2's apps_by_opp, filtered here).
        _t_app_refs = set()
        for ap in apps_by_opp.get(oid2, []):
            for h in (ap.get("id"), ap.get("date")):
                if isinstance(h, str) and h.strip():
                    _t_app_refs.add(h)
        check_trigger(t, label, problems, _t_app_refs, sent_ids)
        # Sequence membership (public #27): grouping only — the hold on a staged step lives in
        # **Blocked until:** and is precondition.py's, never restated here.
        sid, sst = t.get("sequence_id"), t.get("sequence_step")
        if (sid is None) != (sst is None):
            problems.append("%s: sequence_id and sequence_step come together — half a "
                            "sequence membership cannot be grouped and must not look like one "
                            "(got id=%r step=%r)" % (label, sid, sst))
        elif sid is not None:
            if not (isinstance(sid, str) and SLUG_RE.match(sid)):
                problems.append("%s: sequence_id %r must be a lowercase slug" % (label, sid))
            if not (isinstance(sst, int) and not isinstance(sst, bool) and sst >= 1):
                problems.append("%s: sequence_step %r must be an integer >= 1" % (label, sst))

        # ---- plan_id / play_step (ADR-031 B4, design §21) — attribution is a fact at WRITE
        # TIME, like responded_on; `play_step` is `unresolved` only as a migration marker.
        t_plan_id = t.get("plan_id")
        if t_plan_id is not None and t_plan_id not in _plans_by_id:
            problems.append("%s: plan_id %r does not resolve in data/plans.jsonl" % (label, t_plan_id))
        play_step = t.get("play_step")
        if play_step is not None and play_step != "unresolved" and t_plan_id:
            _plan_for_step = _plans_by_id.get(t_plan_id)
            _play_for_step = plays_by_id.get((_plan_for_step or {}).get("play_id")) \
                if _plan_for_step else None
            if _play_for_step is not None:
                _known_steps = {s.get("id") for s in (_play_for_step.get("steps") or [])
                                if isinstance(s, dict)}
                if play_step not in _known_steps:
                    problems.append("%s: play_step %r is not a step of plan %r's play %r"
                                    % (label, play_step, t_plan_id, _plan_for_step.get("play_id")))
        if oid2 and t_plan_id:
            _opp_plan = r_opp_plan_id_by_id.get(oid2)
            if _opp_plan and _opp_plan != t_plan_id:
                problems.append("%s: plan_id %r does not match opportunity %r's own plan_id "
                                "%r — a re-planned pursuit (design §21, warning-shaped but "
                                "printed so a hand-typo is caught too)"
                                % (label, t_plan_id, oid2, _opp_plan))

    # ---- record.py touched — the half-written orphan (design §15.3 point 2) ----
    # `record.py touched` appends a message row FIRST, then the completing touches row — two
    # idempotent appends, never one cross-file transaction. A crash between them (or a test's
    # fault injection) leaves a message with `source: 'record.py touched'` and no touches row
    # naming it as `message_ref` — the exact half-written shape §15.3 itself names. Scoped to
    # THIS source string on purpose: a message with no completing touch is entirely normal for
    # every OTHER source (a harvested reply, a relationship message with no touch at all) —
    # only a message this API itself promised to complete can be orphaned by it.
    TOUCHED_SOURCE = "record.py touched"
    for m in (sent_msgs or []):
        if m.get("id") == "_README" or m.get("source") != TOUCHED_SOURCE:
            continue
        if m.get("id") not in touch_message_refs:
            problems.append(
                "messages[%s]: source is %r but no touches row names it as message_ref — a "
                "half-written `record.py touched` call. Re-run the SAME `record.py touched "
                "<opp_id> --to contact:<id> --on <date> --medium <m>` call to complete it "
                "(design §15.3 point 2)."
                % (m.get("id", "?"), TOUCHED_SOURCE))

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
        # 'application' ref resolves against the LINKED opp's applications and therefore
        # requires opp_id: without one there is no record to resolve against, which is the
        # resolves_when-without-opp_id defect in new clothes. ADR-031 B2: resolved against
        # apps_by_opp (the top-level applications store), never a nested array walk.
        if r.get("trigger_kind") == "application" and not r.get("opp_id"):
            problems.append("%s: trigger_kind 'application' without opp_id — there is no "
                            "record whose applications the ref could resolve against" % label)
        else:
            ask_app_refs = set()
            for ap in apps_by_opp.get(r.get("opp_id"), []):
                for h in (ap.get("id"), ap.get("date")):
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
        if "status" in r and r.get("status") is not None and r["status"] not in COMMITMENT_STATUS:
            problems.append("%s: status %r is not one of %s" %
                            (label, r["status"], "/".join(sorted(COMMITMENT_STATUS))))

    # ---- briefs (Query or Citation C1, design-query-or-citation.md §3.3/§8) — brief.py's own
    # ledger. Structure and closed vocabulary only; `person_id` resolving is the one
    # cross-reference check here (people.jsonl is loaded above, B1). Mirrored as LITERALS,
    # never imported from `your_move`/`brief` — `your_move` imports THIS module, and `brief`
    # imports `your_move`, so an import here in either direction is the exact cycle
    # `precondition.py`'s own lazy import of `brief` already exists to avoid.
    briefs, e = load("briefs.jsonl")
    if briefs is None:
        briefs = []
    else:
        problems += e or []
    brief_ids = set()
    for r in briefs:
        bid = r.get("id", "?")
        label = "briefs[%s]" % bid
        for f in ("id", "computed_at", "person_id", "axis", "register", "evidence"):
            req(r, f, label, problems)
        if r.get("id"):
            if not BRIEF_ID_RE.match(str(r["id"])):
                problems.append("%s: id %r is not brief:<offset-bearing ISO ts>-<4 hex>"
                                % (label, r["id"]))
            if r["id"] in brief_ids:
                problems.append("%s: duplicate id" % label)
            brief_ids.add(r["id"])
        pid = r.get("person_id")
        if pid is not None and pid not in people_ids:
            problems.append("%s: person_id %r does not resolve to any people row" % (label, pid))
        if r.get("opp_id") and r["opp_id"] not in opp_ids:
            problems.append("%s: opp_id %r does not resolve" % (label, r["opp_id"]))
        if r.get("channel_id") and r["channel_id"] not in channel_ids:
            problems.append("%s: channel_id %r does not resolve" % (label, r["channel_id"]))
        reg = r.get("register")
        if reg is not None and reg not in BRIEF_REGISTERS:
            problems.append("%s: register %r not in {%s}"
                            % (label, reg, ", ".join(sorted(BRIEF_REGISTERS))))
        axis = r.get("axis")
        if axis is not None and axis not in BRIEF_AXES:
            problems.append("%s: axis %r not in {%s}"
                            % (label, axis, ", ".join(sorted(BRIEF_AXES))))
        ev = r.get("evidence")
        if isinstance(ev, dict):
            for medium in ("email", "linkedin"):
                tok = (ev.get(medium) or {}).get("token") if isinstance(ev.get(medium), dict) else None
                if tok is not None and not BRIEF_EVIDENCE_RE.match(str(tok)):
                    problems.append("%s: evidence.%s.token %r is not in the §4.1 vocabulary"
                                    % (label, medium, tok))
        elif ev is not None:
            problems.append("%s: evidence must be an object" % label)

    # Unknown-key guard for both new stores — same model-driven rule opportunities already
    # gets, because `nxet_action_owner` is exactly the class of typo these fields will grow.
    if _model:
        _ali = {k: v for k, v in _model["banned_aliases"].items() if not k.startswith("_")}
        for store_name, rows_ in (("asks", asks), ("commitments", commitments),
                                  ("resume_variants", variants),
                                  ("applications", applications),
                                  ("cover_letters", cover_letters),
                                  ("touches", touches),
                                  ("briefs", briefs),
                                  ("plans", plans_rows),
                                  ("plays", plays_rows)):
            _sspec = _model["stores"].get(store_name) or {}
            for r in rows_:
                _l = "%s[%s]" % (store_name, r.get("id", "?"))
                for _k in r:
                    if _k in _ali:
                        problems.append("%s: %r is a banned alias for %r" % (_l, _k, _ali[_k]))
                    elif _k not in (_sspec.get("fields") or ()):
                        problems.append("%s: unknown key %r (known: %s)"
                                        % (_l, _k, ", ".join(sorted(_sspec.get("fields") or ()))))

    # dev #365 — cross-store completeness, defined far below (near `main()`), independent of
    # every per-store loop above.
    check_store_introduction(problems)

    print("Data validation — %d companies, %d channels, %d opportunities, %d asks, "
          "%d commitments, %d resume variants, %d applications, %d cover letters, %d touches, "
          "%d plans, %d plays"
          % (len(companies), len(channels), len(opps), len(asks),
             len(commitments), len(variants), len(applications), len(cover_letters),
             len(touches), len(plans_rows), len(plays_rows)))
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
