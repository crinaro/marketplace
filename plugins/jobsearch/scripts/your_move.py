#!/usr/bin/env python3
"""The single owner of "which group does this row belong in?" for Your Move. GitHub #79.

⭐ THE DEFECT THIS CLOSES
-------------------------
The "needs you" queue used to select rows by OWNERSHIP ALONE: `next_action_owner ==
<candidate> and status in live`. That is a necessary condition, not a sufficient one — a
role future-dated weeks out, one waiting on someone else entirely, and one genuinely overdue
all rendered identically. `next_action_date` was read ONLY as a sort key, never as a cutoff,
and a channel's `next_touch.date` being merely truthy was enough to list it forever, even
after the touch it asked for had already happened.

`generate_dashboard.py` must never re-derive group membership. It imports this module and
renders exactly what `classify_opportunities` / `classify_channels` say.

## Role states, in precedence order

    unresolved   blocked_until is the literal `unresolved`, or unparseable. Its own loud
                 callout — NEVER the primary "needs you" group.
    waiting      blocked_until parses, but no outreach touch to that contact has reached a
                 listed outcome yet.
    scheduled    no unfired trigger, and next_action_date is in the future.
    now          owner is the candidate, status is live, no unfired trigger, and the date is
                 today or in the past (or absent).
    decide       owner is the candidate, status is `backlog`, verdict is `undecided`, no
                 unfired trigger — REGARDLESS of next_action_date, and the system has already
                 triaged the role (`triage_missing` is empty) or has waited too long to. See below.
    triaging     the same backlog + undecided row, but the system has not finished reading it
                 (dev #713 / public #145). SYSTEM-OWNED: not in NEEDS_YOU_ROLE_STATES, so the
                 candidate is never asked pursue-or-pass on a role nobody has read. See below.

## ⭐ `decide` — a decision owed is not an action scheduled (dev #142 / public #24)

Issue #79 correctly stopped ownership alone from being the filter: it added the LIVE-status
gate and the date cutoff so future-dated, resolved and other-party-conditional rows stop
cluttering the "needs you" queue. But the restriction also swallowed the intuitive way to
record a NEWLY SOURCED role: `status: backlog` + `verdict: undecided` + the user as owner +
a future act-by date produced a row visible on NO Your Move group, silently.

The two complaints are in tension only if the date is read as the membership key. It is not:
`next_action_date` answers *"when is the action scheduled"*, while this surface asks *"is a
decision owed"*. The schema already distinguishes the two backlog meanings — `verdict:
undecided` (pursue/pass still owed → `decide`, shown with its act-by date as a DEADLINE, not
a reveal date) versus `verdict: parked` (a decided "not now" → stays off the surface, which
is what keeps #79's clutter out). `blocked_until` keeps its full precedence here: an
undecided row genuinely gated on another party is `waiting`/`unresolved`, never `decide`.

## ⭐ `triaging` — a role is the candidate's decision only once the system has read it (dev #713 / public #145)

A role used to reach `decide` the moment it was captured, so the candidate was asked pursue-or-pass
on roles nobody had read: no JD read, no pay as written, no work setting, no screen, no lean.
`triage_missing()` is the ONE definition of what a role still lacks; non-empty means the role is
`triaging` and system-owned. It is DERIVED, never stored (design-sourcing-screen.md §7.1): on
upgrade every existing undecided backlog role lacking a field simply reads `triaging` and drains
through the daily run's triage step (`--triage-queue` below), which takes at most
`search.triage_per_run` roles per run, oldest first.

⭐ THE GATE ALWAYS EXITS (design R3). A gate that can wait forever is a role the candidate never
sees. Two bounds, both applied HERE and nowhere else:

  * a read that was TRIED AND FAILED satisfies `jd-read` — `fit.jd_source` is `unavailable:
    <reason>` for a closed set of reasons (`TRIAGE_UNAVAILABLE_REASONS`). The role goes to
    `decide` with the lean defaulted to `ask` and the line `not read: <reason>`. A null
    `jd_source` still means NOT TRIED.
  * a role still `triaging` after `search.triage_stuck_days` days surfaces in `decide` as
    `not yet read (waited K days)` with the lean `ask`. The age runs from the role's FIRST
    SIGHTING. A role with no readable sighting date has no age to wait out, so it surfaces
    at once (`age unknown`) — an unknown age is never invented as zero.

## The `blocked_until` field

Grammar is `precondition.py`'s VERBATIM: `contact:<id> outcome:<v>|<v>` (ADR-031 B1: `<id>` is
now a `people` id, resolved via `outreach[].person_id` — was `contact_id`), resolved against
the RECORD'S OWN `outreach[]` — never the global pipeline, because a join to another
opportunity's touch would say this role moved when it did not. Plus the literal `unresolved`.
No `date:` form: a time trigger already lives in `next_action_date`, and inventing a second
way to spell the same thing is the exact duplication issue #6 removed for drafts.

## Channel touches are DERIVED, never a hand-authored `last_touch`

`last_touch` is gone from the schema (nothing ever wrote it — see `migrate.py`'s note). A
channel's last touch is computed here, always: the max of (the latest OUTBOUND message in
`messages.jsonl` whose `person_id` joins any person INVOLVED IN THAT CHANNEL — ADR-031 B1:
`involvements.channel_id`, was `channels.contacts[].contact_id`) and (the latest `log[]`
entry date).

⭐ THE FULFILMENT RULE'S SHARP EDGE. A derived touch dated ON OR AFTER `next_touch.date`
fulfils the plan. An EARLIER touch does NOT — the row stays `now`, because the cheap error is
a look at a handled row and the expensive one is a phantom fulfilment cancelling a call that
is still owed.

`next_touch` itself gets no mechanical write path here, deliberately: it is a plan authored
by judgement (`record.py`), and nothing in this module ever advances or clears it.

Usage:
    python3 your_move.py            # human-readable: every role and channel, with its state
    python3 your_move.py --json
    python3 your_move.py --check    # exit 1 on an unresolved / unreadable blocked_until
    python3 your_move.py --triage-queue [--per-run N]
                                    # JSON: the roles this run's triage step reads next (at most
                                    # search.triage_per_run, oldest first) and the waiting counts
    python3 your_move.py --triage-report --batch ID,ID
                                    # AFTER the reads: prints `triaging: N waiting, M triaged
                                    # this run, K over the stuck bound`

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root                                      # noqa: E402
import precondition as _pre                                         # noqa: E402
import profile as _profile                                          # noqa: E402
# ⭐ The status vocabulary has ONE owner — validate_data.py. This module used to carry its
# own copy of the terminal pair, and generate_dashboard.py a third, wider "closed" set that
# silently disagreed with the membership rule below (dev/audit 2026-09-02, build item 1).
# validate_data imports this module too; both sides bind only what they need at import
# time, and validate_data places its import of us below its vocabulary for that reason.
import validate_data as _vd                                         # noqa: E402
import config_keys                                                   # noqa: E402
# public #95 (terminal-transition cascade) — `letter_state`/`touch_state` below read these
# two top-level stores directly; neither imports this module (or validate_data), so this is
# safe at module top level, unlike the lazy `import your_move` precondition.py/watch.py do.
import applications as _apps                                         # noqa: E402
import touches as _touches                                           # noqa: E402

# Re-exported so a caller (validate_data.py) needs exactly one import to validate the field.
PreconditionError = _pre.PreconditionError

# The statuses on which a role can be OWNER-ACTIONABLE right now — Your Move MEMBERSHIP, not
# liveness. `in-motion` and `backlog` are live (not terminal) but reach this surface only
# through the rules below; see validate_data.TERMINAL_OPP_STATUSES for what has ended.
LIVE_OPP_STATUSES = {"active-pursuit", "needs-resolution"}

ROLE_STATES = ("unresolved", "waiting", "scheduled", "now", "decide", "triaging")
CHANNEL_STATES = ("now", "scheduled", "fulfilled")

# ⭐ ATTENTION — the router's two counts, as a per-row value (public #48, stage 1). The
# published page used to carry "in flight" as a SECTION: every live role not in the
# needs-you queue rendered again under "⏳ In flight — not yours to do", so one role could
# render in up to three places and no list could be narrowed. The owner named it noise:
# "in flight" is not a kind of record, it is a STATE of an opportunity. It is now a filter
# dimension on the one opportunity list, and this is its vocabulary — owned here, beside
# the membership rule it derives from, never restated by the renderer (the
# `_CLOSED_STATUSES` lesson: a renderer-private set is how 23 rows vanished).
#
# needs-you  ⇔ classify_opportunities places the role in `now` or `decide` — the two
#              states generate_dashboard's needs-you queue renders (your_move_roles /
#              your_move_decides). `unresolved` and `waiting` are loud callouts, not
#              queue rows, and the router has always counted them in flight.
# in-flight  ⇔ every other LIVE role (not terminal): waiting on the other side,
#              scheduled, owned by the run, or a decided backlog row.
ATTENTION = ("needs-you", "in-flight")
#
# `triaging` (dev #713 / public #145) is deliberately in NEITHER count: it is system-owned, so a
# role the run is still reading is in flight, and "needs you" never includes it.
NEEDS_YOU_ROLE_STATES = frozenset({"now", "decide"})


def attention_by_id(opps, owner_token, today=None, stuck_days=None):
    """{opp id: ATTENTION value} for every LIVE opportunity — the one definition the
    dashboard's state filter and its router in-flight count both read, so the label
    population and the router number cannot disagree."""
    needs = {o.get("id") for o, st, _w in classify_opportunities(opps, owner_token, today,
                                                                 stuck_days)
             if st in NEEDS_YOU_ROLE_STATES and o.get("id")}
    out = {}
    for o in opps:
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES or not o.get("id"):
            continue
        out[o["id"]] = "needs-you" if o["id"] in needs else "in-flight"
    return out


# ⭐ OWNER — whose move a live role is, as a per-row value (public #54, the 0.37.0 visibility
# regression). Issue #79 retired OWNERSHIP ALONE as the "needs you" QUEUE key, correctly: a
# role the candidate owns but has dated weeks out is not today's work. Stage 1 of public #48
# then replaced the opportunity list's ownership sort tier and its "Waiting on you" chip with
# ATTENTION — and ATTENTION cannot express ownership: a candidate-owned `scheduled` row, or a
# candidate-owned row outside Your Move's membership (`in-motion`), is `in-flight` by its
# definition. Measured on the profile that reported it: every one of 74 live rows was
# `in-flight`, so the state chip did not even render, and the three candidate-owned rows
# sorted past the cap and appeared nowhere on the page. Ownership is the wrong QUEUE key and
# the right FILTER: "which of these is mine" is a question the reader asks, and it is answered
# by the record's own `next_action_owner`, never re-derived by the renderer. Vocabulary owned
# here, beside `is_your_move_candidate`, the predicate that already reads the same field.
#
# you  ⇔ next_action_owner is the candidate's own token (profile.owner_token()).
# run  ⇔ anything else validate_data.OWNERS admits — "me", the engine acts next.
OWNER = ("you", "run")


def owner_by_id(opps, owner_token):
    """{opp id: OWNER value} for every LIVE opportunity — the one definition the
    dashboard's owner filter, its reading order and its "you / the run" row label read."""
    out = {}
    for o in opps:
        if o.get("status") in _vd.TERMINAL_OPP_STATUSES or not o.get("id"):
            continue
        out[o["id"]] = "you" if o.get("next_action_owner") == owner_token else "run"
    return out

def has_submitted_application(apps):
    """Does this opportunity's own applications prove a submission? `apps` is the record's own
    slice of the top-level `applications` store (ADR-031 B2 — `applications.group_by_opp(...)`
    filtered to this opportunity's id, e.g. `apps_by_opp.get(o["id"], [])`; the caller already
    has that mapping built once, not re-derived per row). The evidence of a decision made by
    ACTING (dev/audit 2026-09-02, Class A / public #44): a row can still read `verdict:
    undecided` while an application went in, and the surface must not ask a question the store
    already answers. SUBMITTED_APP_STATUS is validate_data's.

    ⭐ Pre-B2 nested reads do NOT belong here any more — migrate.py's own m_0_36_0 historical
    migration (the one caller that ever needed the PRE-migration nested shape) keeps its own
    small inline copy of this predicate rather than depend on this signature, because it always
    runs before B2's own promotion in the migration chain and reads the nested array on
    purpose. See that function's docstring."""
    return any(a.get("status") in _vd.SUBMITTED_APP_STATUS for a in (apps or []))


# ⭐⭐ `derive_play_stage` / `unresolved_play_stages` — RETIRED in ADR-031 B4 (design §19).
# `play_stage` itself is gone (retired, see validate_data.RETIRED_KEYS/banned_aliases); the
# position it used to name a hand-set cursor for is now DERIVED, every time it is asked, by
# `plays.next_step()` — a real derivation over the stores, not a floor a migration could only
# guess at from `applications`. `plays.py --check` is `unresolved_play_stages`'s successor: it
# reports every pursuit whose play is `stalled`, a check that can actually fire (design §19).


def open_asks(asks, kind=None):
    """The OPEN rows of data/asks.jsonl — the one definition of ask membership (dev #93).

    An ask leaves every surface the moment `resolved_on` is set; nothing ever rewrites one
    into a "✅ CONFIRMED" line in place, because the views only render what this returns.
    That is focus.md's expel-resolved-items invariant made structural. Sorted soonest
    act_by first (undated last), then by created, so the most time-sensitive ask leads.
    `kind` narrows to "role" (the Your Move queue) or "system" (System & tooling)."""
    rows = [a for a in asks
            if not a.get("resolved_on") and (kind is None or a.get("kind") == kind)]
    return sorted(rows, key=lambda a: (str(a.get("act_by") or "9999"),
                                       str(a.get("created") or "")))


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION AXIS — Query or Citation C1 (design-query-or-citation.md §3.7), States & Views'
# declared home. ONE computation over BOTH homes a reply can live in — message rows and
# `outreach[].outcome`/`responded_on` — because a LinkedIn reply (or any pre-harvest reply)
# often exists ONLY as the second. A store-only register (the pre-C1 shape) disagreed with a
# thread-aware one on exactly that row: the store said `chase`/`cold`, the thread said
# `reply-owed`, and the drafter wrote a cold opener to someone who had already replied
# (public #79, rebuilt by the mechanism meant to close it — the audit's D6).
# ─────────────────────────────────────────────────────────────────────────────

# The closed axis vocabulary, in FOLD PRECEDENCE (design §3.7): the newest event on a thread
# decides the axis, and this is the tie-break order when more than one signal could apply to
# the same newest moment (an outbound touch carrying BOTH an `accepted` outcome and a bounced
# delivery, say). Never reordered ad hoc — a fold order is a closed vocabulary, not a heuristic.
AXIS_FOLD = ("reply-owed", "accepted", "waiting", "silence-unverified", "silent", "nothing-sent")


def _touch_rows(record):
    """The ONE accessor for an opportunity record's touches. ADR-031 B3 promoted
    `outreach[]` to the top-level `touches` store — this is the one site that changed
    (design §3.7 / §15 — 'so B3's read gate finds one site'). Reads `record["_touches"]`, the
    caller's own join against that store (`touches.enrich_opportunities(root, opps)`, called
    once after loading opportunities — the exact ADR-031 B2 `_applications` shape), never a
    nested array on `record` itself. A caller that never enriched `opps` gets `()` here
    (`touches.attach`'s own default), the honest "no touches known" answer rather than a
    crash."""
    return record.get("_touches") or []


def _resolves_to(graph_, maybe_id, target_id):
    """Does `maybe_id` (a people id, possibly an absorbed alias) resolve, through any merge
    chain, to the SURVIVOR `target_id`? `graph_` is a `graph.Graph` INSTANCE (named with a
    trailing underscore so it never shadows the `graph` MODULE the rest of this section
    imports). False for anything unresolved or cyclic — never raises past this function; a
    graph walk error is not this caller's problem to solve."""
    if not maybe_id:
        return False
    try:
        resolved = graph_.resolve_person(maybe_id)
    except Exception:                                     # noqa: BLE001 — defensive only
        return False
    return resolved is not None and resolved.get("id") == target_id


def _journal_medium(medium_value):
    """A message/outreach `medium` (validate_data.MEDIA — 'email-cold', 'linkedin-message', …)
    folded to the two journal probe media (D1: 'email' | 'linkedin'). Never raises: an
    unrecognised medium (phone, sms, other) folds to 'email' — the mailbox-search evidence
    path is the only probe this engine has for anything that is not LinkedIn."""
    m = str(medium_value or "").lower()
    return "linkedin" if m.startswith("linkedin") else "email"


def _thread_events(graph, person_id, kind, thread_id):
    """Every event on one thread (`kind` 'opp', 'channel' or 'person', `thread_id` the
    record's own id — for 'person', the survivor's own id) touching the SURVIVOR `person_id` —
    sorted oldest first. dev #686 / public #139: a 'person' thread is the relationship with no
    role and no channel — exactly the messages and touches carrying NEITHER `opp_id` NOR
    `channel_id`. One dict per event:
    `{direction, date, medium, source, outcome, delivery}` (the last three vary by source).

    DEDUPLICATION (design §3.7): an outreach touch naming a `message_ref` that resolves to a
    message row already counted from `messages.jsonl` is NOT counted twice — only the message
    row is an event, though the touch's own `outcome`/`delivery` are folded onto it, since a
    message row carries neither. An outreach touch whose `outcome` is 'replied' with
    `responded_on` set synthesizes an INBOUND event at that date UNLESS a message row already
    stands at that same date — the D6 case (a reply that lives only in outreach[]) produces
    exactly one inbound event, never a duplicate of one messages.jsonl already carries.
    `outcome: 'no-response'` is IGNORED as a signal (never trusted as terminal) — the axis
    recomputes silence from sent_on + journal coverage instead of a possibly-stale label."""
    events = []
    message_ids = set()
    inbound_dates = set()
    for m in graph.stores["messages"]:
        if kind == "person":
            if m.get("opp_id") or m.get("channel_id") or thread_id != person_id:
                continue
        elif (m.get("opp_id") if kind == "opp" else m.get("channel_id")) != thread_id:
            continue
        if not _resolves_to(graph, m.get("person_id"), person_id):
            continue
        events.append({"direction": m.get("direction"), "date": m.get("sent_on"),
                       "medium": _journal_medium(m.get("medium")), "source": "message",
                       "id": m.get("id"), "outcome": None, "delivery": None,
                       "body": m.get("body")})
        if m.get("id"):
            message_ids.add(m["id"])
        if m.get("direction") == "inbound" and m.get("sent_on"):
            inbound_dates.add(m["sent_on"])

    touches = []
    if kind == "opp":
        for t in graph.touches_for_opportunity(thread_id):
            if _resolves_to(graph, t.get("person_id"), person_id):
                touches.append(t)
    elif kind == "person" and thread_id == person_id:
        # dev #686: a touch with NO opp and NO channel is the person-only relationship. A
        # channel-only touch stays excluded (see the scope note just below).
        for t in graph.stores["touches"]:
            if (not t.get("opp_id") and not t.get("channel_id")
                    and _resolves_to(graph, t.get("person_id"), person_id)):
                touches.append(t)
    # kind == "channel": ADR-031 B3 — touches CAN now be channel-anchored with no opp_id
    # (public #53, the network capability's basis), but design §3.7's own scope stays: a
    # channel-scoped THREAD (this function's own concept, keyed by opp_id/channel_id as the
    # counterpart) still carries message events only here — a channel-anchored touch with no
    # opp_id is a person-to-channel fact, not a per-thread one, and belongs to
    # `derive_channel_last_touch`'s own reading of channels, not to this per-thread walk.

    for t in touches:
        outcome = t.get("outcome")
        ref = t.get("message_ref")
        if ref and ref in message_ids:
            for e in events:
                if e.get("source") == "message" and e.get("id") == ref:
                    e["outcome"] = outcome
                    e["delivery"] = t.get("delivery")
        else:
            events.append({"direction": "outbound", "date": t.get("date"),
                           "medium": _journal_medium(t.get("medium")), "source": "outreach",
                           "id": None, "outcome": outcome, "delivery": t.get("delivery"),
                           "body": t.get("note")})
        responded = t.get("responded_on")
        if outcome == "replied" and responded and responded not in inbound_dates:
            events.append({"direction": "inbound", "date": responded,
                           "medium": _journal_medium(t.get("medium")), "source": "outreach",
                           "id": None, "outcome": None, "delivery": None, "body": None})
            inbound_dates.add(responded)

    events.sort(key=lambda e: str(e.get("date") or ""))
    return events


def _outbound_axis(newest, today, window, journal_recs, person_id):
    """The axis for a thread whose NEWEST event is `newest`, an outbound touch nobody has
    answered since. `outcome: 'no-response'` is ignored as a signal (design §3.7) — folded
    to the same path as no outcome at all, so a possibly-stale label never overrides a fresh
    recomputation from sent_on + journal coverage."""
    outcome = newest.get("outcome") if newest.get("outcome") != "no-response" else None
    if outcome == "accepted":
        return "accepted"          # the owner's move — NEVER ages (design §3.7)
    if newest.get("delivery") == "bounced":
        return "nothing-sent"      # a bounced touch never reached anyone — never "waiting"
    sent_on = str(newest.get("date") or "")
    if not sent_on:
        return "waiting"
    import journal as _journal
    thread = "contact:%s" % person_id
    medium = newest.get("medium") or "email"
    verified_through = _journal.probe_covered_through(journal_recs, thread, medium)
    if verified_through and str(verified_through) >= sent_on:
        elapsed = (_parse_date(verified_through) - _parse_date(sent_on)).days
        return "silent" if elapsed >= window else "waiting"
    # No thread-scoped probe verifies past sent_on. Fall back to wall-clock age ONLY to
    # decide 'waiting' (too soon to even ask) vs 'silence-unverified' (old enough that the
    # silence NEEDS verifying) — never to assert 'silent' itself, which requires a real probe.
    age = (_parse_date(today) - _parse_date(sent_on)).days
    return "waiting" if age < window else "silence-unverified"


def _parse_date(s):
    return datetime.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def conversation_axis(root, subject, counterpart=None, today=None, window=None):
    """`{thread_id: (axis_token, events)}` for every thread touching person `subject` (a
    `people.jsonl` id, resolved through any merge) — or exactly the one thread `counterpart`
    names (`"opp:<id>"` / `"channel:<id>"` / `"person:<id>"`, the last being the dev #686
    person-only thread), narrowed before anything is computed so a caller
    that already knows its scope pays for one thread's worth of work, not the whole graph's.

    `today`/`window` are test seams (window otherwise has no engine-wide default — the caller
    is expected to pass `config_keys.describe(cfg, config_keys.CHASE_AFTER_DAYS)[0]`, brief.py's
    own job per design §6; a caller that passes neither gets `config_keys.CHASE_AFTER_DAYS_DEFAULT`
    so this function is still usable standalone).

    The axis token is folded from the thread's newest event (design §3.7):
    `reply-owed` (newest event is inbound) · `accepted` (an 'accepted' outbound outcome, and
    this NEVER ages past it) · `waiting` (an outbound touch too recent to chase, or one whose
    silence nothing has verified yet) · `silence-unverified` (old enough to chase, but no
    thread-scoped probe covers it) · `silent` (verified, via `journal.probe_covered_through`,
    through at least `window` days past the send) · `nothing-sent` (no outbound event at all,
    or the only one bounced)."""
    import graph as _graph
    import journal as _journal
    today = today or datetime.date.today().isoformat()
    window = config_keys.CHASE_AFTER_DAYS_DEFAULT if window is None else window
    g = _graph.Graph(os.path.join(root, "data"))
    try:
        person = g.resolve_person(subject)
    except _graph.MergeCycleError:
        person = None
    person_id = person["id"] if person else subject

    threads = set()
    if person is not None:
        for i in g.involvements_for_person(person_id):
            if i.get("opp_id"):
                threads.add(("opp", i["opp_id"]))
            if i.get("channel_id"):
                threads.add(("channel", i["channel_id"]))
        for m in g.messages_for_person(person_id):
            if m.get("opp_id"):
                threads.add(("opp", m["opp_id"]))
            if m.get("channel_id"):
                threads.add(("channel", m["channel_id"]))
        # ADR-031 B3 — touches are their own top-level store now; walk it directly rather
        # than per-opportunity (`_touch_rows` stays the per-record accessor for callers that
        # already have an enriched opportunity in hand, e.g. `role_state`). A touch anchored
        # to no opportunity (channel-only or fully unanchored, public #53) never opens an
        # "opp" thread here — the scope note above `_thread_events`'s own touches branch.
        for t in g.stores["touches"]:
            if t.get("opp_id") and _resolves_to(g, t.get("person_id"), person_id):
                threads.add(("opp", t["opp_id"]))
        # dev #686 / public #139 — A THIRD THREAD KIND: the person themselves. A message or a
        # touch carrying NEITHER opp_id NOR channel_id (a relationship with no role and no
        # channel) opens ONE ("person", <id>) thread, so a reply to a stored inbound in it is
        # `reply-owed` rather than falling through to `nothing-sent` -> `unverified-cold`.
        # The thread id is `person:<id>` in the returned dict, so a person id can never
        # collide with an opportunity's or a channel's.
        for m in g.messages_for_person(person_id):
            if not m.get("opp_id") and not m.get("channel_id"):
                threads.add(("person", person_id))
        for t in g.stores["touches"]:
            if (not t.get("opp_id") and not t.get("channel_id")
                    and _resolves_to(g, t.get("person_id"), person_id)):
                threads.add(("person", person_id))

    if counterpart:
        kind, _sep, tid = str(counterpart).partition(":")
        threads = {(k, i) for (k, i) in threads if k == kind and i == tid}

    recs = _journal.read(root)
    out = {}
    for kind, tid in threads:
        events = _thread_events(g, person_id, kind, tid)
        key = ("person:%s" % tid) if kind == "person" else tid
        if not events:
            out[key] = ("nothing-sent", events)
            continue
        newest = events[-1]
        if newest["direction"] == "inbound":
            out[key] = ("reply-owed", events)
        else:
            out[key] = (_outbound_axis(newest, today, window, recs, person_id), events)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# STATES & VIEWS V1 (design-states-and-views.md) — the application axis, the ending
# dimension (§2b), the stop-networking in-force flag (§3b), the triage suggestion (§3a) and
# the two-axis workflow state (§2). The conversation axis ABOVE is ADOPTED unchanged (§15.2's
# own words: "never build a second one") — everything below folds or composes its events,
# never re-derives them.
# ─────────────────────────────────────────────────────────────────────────────

# One imported definition (validate_data.py owns it) — never a second spelling here.
APPLICATION_ENDINGS = _vd.APPLICATION_ENDINGS


def ended_because(opp, apps):
    """§2b — why a pursuit STOPPED, or `None` if it is still live. `apps` is this
    opportunity's own slice of the top-level applications store (same contract as
    `has_submitted_application` — `applications.group_by_opp(...)[opp_id]`, or `[]`).

    Precedence, top to bottom (§2b's table, RE-ORDERED 2026-09-13 — public #94): `rejected`
    (the employer said no) > `closed-silence` (we closed it after ATS silence, §3c) >
    `withdrawn` (they did, after applying) > `expired` (the posting vanished) >
    `unrecorded` (a submitted application on a now-terminal opportunity, with nothing saying
    why it ended) > `passed` (a verdict of `pass`, or an opportunity `status: passed` — they,
    or we, walked away before applying) > `unrecorded` a second time (a `stage: closed` req
    with NO application and NO passed verdict either — genuinely nothing says why).

    ⭐ `passed` now runs BEFORE the second `unrecorded` check, not after. Before this fix a
    closed-and-never-applied-to opportunity that WAS in fact passed on (`verdict: pass`) hit
    the `stage == closed and not past_started` branch first and read as `unrecorded` — the
    exact shape public #94 traced the migration's over-count to (`m_0_47_0_application_
    endings` only ever printed what this function returned). A `passed` verdict is a fact
    already on hand; treating it as merely "closed" threw that fact away. Each fact stays
    where it already lives (application status vs. opportunity status/stage/verdict); this
    only composes them, and never invents a reason a value older than this vocabulary should
    have recorded (§3d)."""
    apps = sorted(apps or [], key=lambda a: str(a.get("date") or ""))
    newest = apps[-1] if apps else None
    app_status = newest.get("status") if newest else None
    opp_status = opp.get("status")
    stage = opp.get("stage")
    verdict = opp.get("verdict")

    if app_status == "rejected":
        return "rejected"
    if app_status == "closed":
        return "closed-silence"
    if app_status == "withdrawn":
        return "withdrawn"
    if opp_status == "expired":
        return "expired"

    terminal_opp = opp_status == "passed" or stage == "closed"
    submitted_like = app_status in ("submitted", "acknowledged", "advanced")
    past_started = any((a.get("status") or "not-started") not in ("not-started", "started")
                       for a in apps)
    if terminal_opp and submitted_like:
        return "unrecorded"

    # ⭐ public #94 — MOVED ABOVE the `stage == "closed"` catch-all below: a passed verdict is
    # a fact already on hand and must win over a bare "it's closed" guess.
    if (verdict == "pass" or opp_status == "passed") and not past_started:
        return "passed"

    if stage == "closed" and not past_started:
        # §15.4 finding 6 — a dead req with NO application at all is not "still pursuing".
        # Nothing says whether they passed or the posting vanished, so this is unrecorded too,
        # never guessed as `expired` (only the posting's OWN status says that) — and, since
        # the `passed` check above already ran, never guessed as `passed` either: this is
        # reached only when NEITHER a verdict nor a status says why.
        return "unrecorded"

    return None


# ─────────────────────────────────────────────────────────────────────────────
# THE TERMINAL-TRANSITION CASCADE — public #95. `ended_because()` above is the ending
# oracle States & Views V1 already built; nothing about an ending is re-derived here. What
# was missing is the DRAIN: two stores whose own rows carry no field a terminal transition
# ever updates, so work that hung off the prior state (a cover letter still "pending" for a
# role already decided, an outreach touch still "due" for a pursuit already over) survived
# indefinitely, looking exactly like live work.
#
# Both derivations below are PURE — computed fresh from the stores every call, never stored
# back (this module's own stated contract: `report()`'s own docstring, `workflow_state()`'s
# precedent). No migration accompanies this: nothing on disk changes shape or gains a field:
# `cover_letters.status: null` stays exactly as legal as it always was
# (`validate_data.COVER_LETTER_STATUS` — nullable on purpose, design §1's "a migration that
# cannot know a field's type must not interpret it"); this only computes, on top of what is
# already there, the fact a reader actually needs.
# ─────────────────────────────────────────────────────────────────────────────


def build_ended_context(root):
    """{'opps_by_id', 'apps_by_opp', 'apps_by_letter'} — built ONCE by a caller that scores
    many `cover_letters`/`touches` rows through `letter_state`/`touch_state` below, so N rows
    cost one load of `opportunities.jsonl` + `applications.jsonl`, never N. Every key reads
    through the SAME `applications.py` joins every other B2/B3 reader in this engine uses —
    `group_by_opp` for `ended_because()`'s own contract, and the new `group_by_cover_letter`
    for "which application (if any) actually carries this letter's id"."""
    opps = _load_jsonl(root, "opportunities.jsonl")
    opps_by_id = {o.get("id"): o for o in opps if o.get("id")}
    apps_rows, _errs, _present = _apps.load(root)
    return {"opps_by_id": opps_by_id,
            "apps_by_opp": _apps.group_by_opp(apps_rows),
            "apps_by_letter": _apps.group_by_cover_letter(apps_rows)}


# The five states `letter_state()` can return, in PRECEDENCE order (the first that applies
# wins) — the vocabulary is closed, the same convention ROLE_STATES/CHANNEL_STATES set.
LETTER_STATES = ("used", "retired", "moot", "sent", "pending")


def letter_state(letter, ctx):
    """(state, why) for one `data/cover_letters.jsonl` row — public #95's cover-letter half,
    named in design-inbound-resolution.md §8 as the explicit remainder ("`cover_letters.
    status` has no terminal value on an ending"). `ctx` is `build_ended_context(root)`'s own
    dict, built once and reused across every row.

    Precedence, top to bottom — the first that applies wins:

        used     some application's own `cover_letter_id` names THIS letter, and that
                 application's status proves a submission actually happened
                 (`applications.SUBMITTED_APP_STATUS`). Outranks `moot` on purpose: a used
                 letter attached to an application that later gets rejected is still
                 `used` forever — "we sent this" is a permanent fact history must not
                 relabel as "we never got around to it" just because the pursuit later
                 ended.
        retired  the letter's own `status` is the explicit literal `retired`.
        moot     never used, but the opportunity it was written for (`letter['opp_id']`)
                 has ENDED (`ended_because()`, the one ending oracle) — nothing will ever
                 attach this letter now.
        sent     the letter's own `status` is the explicit literal `sent` — recorded, but
                 with no application FK corroborating it (a legacy or hand-recorded row).
        pending  none of the above: still awaiting the owner. `status` is NULLABLE here by
                 design (a migration-minted row's explicit unknown — the same
                 `status_on: null` shape `applications` already uses) — a null status is
                 reported as **unrecorded**, counted exactly like any other pending row,
                 and the `why` string never calls it a "draft": a reader that defaults a
                 missing/null status to `draft` manufactures a fact (someone actually
                 drafted this) the store never asserted."""
    lid = letter.get("id")
    using = ctx["apps_by_letter"].get(lid) or []
    used_app = next((a for a in using if a.get("status") in _apps.SUBMITTED_APP_STATUS), None)
    if used_app is not None:
        return "used", ("application %s (status %r) carries this letter's id"
                        % (used_app.get("id") or "?", used_app.get("status")))
    if letter.get("status") == "retired":
        return "retired", "cover letter's own status is retired"
    opp = ctx["opps_by_id"].get(letter.get("opp_id"))
    if opp is not None:
        ending = ended_because(opp, ctx["apps_by_opp"].get(letter.get("opp_id"), []))
        if ending:
            return "moot", ("opportunity %s has ended (%s) — nothing will attach this "
                            "letter now" % (letter.get("opp_id"), ending))
    if letter.get("status") == "sent":
        return "sent", "cover letter's own status is sent"
    raw = letter.get("status")
    if raw is None:
        return "pending", ("status is unrecorded (null) — a migration-minted row nothing "
                           "has stamped yet")
    return "pending", "recorded status is %r, not yet sent" % raw


# `touch_state()`'s own vocabulary. `ended` is rung 0 — checked before anything else a
# caller might otherwise compute (silence age, cadence, …), because a touch whose
# opportunity has ended cannot be "due" for a follow-up under any of those rules: there is
# nothing left to follow up ON. `active` is every other touch — this function does not
# invent the rest of a due/not-due ladder; it only answers the one question its callers
# actually need (design-inbound-resolution.md's own "the cascade is a derivation" framing,
# scoped to what public #95 reported: an ended pursuit's touch still counting as live work).
TOUCH_STATES = ("ended", "active")


def touch_state(touch, ctx):
    """(state, why) for one `data/touches.jsonl` row. `ended` fires when the touch's own
    `opp_id` resolves to an opportunity that `ended_because()` says has ended — independent
    of the touch's own `outcome`/`status` fields, because those describe what happened
    ON the touch, not whether the pursuit it was FOR is still open. A touch with no
    `opp_id` at all (a channel-only or fully unanchored touch — ADR-031 B3 / public #53) can
    never be `ended` by this rule: there is no opportunity for it to end WITH, so it is
    always `active`. `ctx` is `build_ended_context(root)`'s own dict."""
    opp_id = touch.get("opp_id")
    if not opp_id:
        return "active", "no opp_id — not anchored to a pursuit that can end"
    opp = ctx["opps_by_id"].get(opp_id)
    if opp is None:
        return "active", "opp_id %r does not resolve" % opp_id
    ending = ended_because(opp, ctx["apps_by_opp"].get(opp_id, []))
    if ending:
        return "ended", ("opportunity %s has ended (%s) — not due for a follow-up"
                         % (opp_id, ending))
    return "active", "opportunity is still live"


def application_axis(opp, apps):
    """§2 — the application axis, precedence `ended` > `parked` > `undecided` >
    `in-process` > `applied` > `pursuing`. `apps` is this opportunity's own applications
    slice, same contract as `ended_because`/`has_submitted_application`."""
    if ended_because(opp, apps) is not None:
        return "ended"
    verdict = opp.get("verdict")
    if verdict == "parked":
        return "parked"
    if verdict == "undecided":
        return "undecided"
    apps = sorted(apps or [], key=lambda a: str(a.get("date") or ""))
    newest = apps[-1] if apps else None
    advanced = newest is not None and newest.get("status") == "advanced"
    if opp.get("stage") in ("screening", "interviewing", "offer") or advanced:
        return "in-process"
    if newest is not None and newest.get("status") in ("submitted", "acknowledged"):
        return "applied"
    if verdict == "pursue":
        return "pursuing"
    return "undecided"          # defensive: validate_data.VERDICTS admits nothing else here


def networking_in_force(opp, newest_outbound_on=None):
    """§3b/§15.3 — is the stop-networking flag actually IN FORCE right now? Set, and no
    outbound event dated after it — NEVER cleared, only compared, so no writer has to
    remember to reset it on a later touch (the flag says *reopened by touch <date>*, both
    facts still on file). `newest_outbound_on` is the caller's own reading of the newest
    outbound event across every thread on this pursuit (see
    `opportunity_conversation_axis`'s second return value), or None if there never was one."""
    closed_on = opp.get("networking_closed_on")
    if not closed_on:
        return False
    if newest_outbound_on and str(newest_outbound_on) > str(closed_on):
        return False              # reopened by construction — a later touch, not a writer
    return True


def opportunity_conversation_scan(root, opp_id, today=None, window=None):
    """§2/§15.2 — the conversation axis for an OPPORTUNITY subject, folded over every
    counterpart thread on it, with the facts the same scan already visits. `conversation_axis()`
    above is person-centred (subject = a people id); this reads the SAME events from the
    opposite direction — one counterpart at a time, through that same function, folded by
    `AXIS_FOLD` precedence (§2: "one thread still within its window keeps the subject
    waiting; the subject is silent only when every outstanding thread is"). Never a second
    derivation of what an event is.

    Returns a dict: `token` (the folded axis token), `newest_outbound_on` (feeds
    `networking_in_force()` without a second scan of the same rows), and — dev #494 / public
    #58, design-one-dashboard-surface.md r3 §3.1 — two facts the thread scan already walks and
    used to discard: `inbound_ever` (has ANY inbound event ever arrived on ANY thread of this
    subject; the pursuit bar's "In live conversation" needs it, because a thread whose newest
    event is an outbound touch is `waiting` whether or not they ever answered) and
    `newest_event_on` (the newest event of either direction, the dashboard's "days since
    anything last happened" sort key). No new scan, no new store, no new field.

    ⭐ A SEPARATE FUNCTION, NOT A THIRD RETURN VALUE. `opportunity_conversation_axis` below keeps
    its two-tuple: `record.py` unpacks exactly two and is not this change's to edit. The old
    function is now a one-line projection of this one, so the two cannot disagree."""
    import graph as _graph
    g = _graph.Graph(os.path.join(root, "data"))
    opp = g.by_id["opportunities"].get(opp_id)
    none = {"token": "nothing-sent", "newest_outbound_on": None, "inbound_ever": False,
            "newest_event_on": None}
    if opp is None:
        return dict(none)

    person_ids = set()
    for t in g.touches_for_opportunity(opp_id):
        pid = t.get("person_id")
        if not pid:
            continue
        try:
            resolved = g.resolve_person(pid)
        except Exception:                                   # noqa: BLE001 — defensive only
            resolved = None
        person_ids.add(resolved["id"] if resolved else pid)
    for m in g.stores["messages"]:
        if m.get("opp_id") != opp_id or not m.get("person_id"):
            continue
        try:
            resolved = g.resolve_person(m["person_id"])
        except Exception:                                   # noqa: BLE001 — defensive only
            resolved = None
        person_ids.add(resolved["id"] if resolved else m["person_id"])

    if not person_ids:
        return dict(none)

    best_token, newest_outbound, newest_event, inbound_ever = None, None, None, False
    for pid in person_ids:
        axes = conversation_axis(root, pid, counterpart="opp:%s" % opp_id,
                                 today=today, window=window)
        token, events = axes.get(opp_id, ("nothing-sent", []))
        if best_token is None or AXIS_FOLD.index(token) < AXIS_FOLD.index(best_token):
            best_token = token
        for e in events:
            if e.get("direction") == "inbound":
                inbound_ever = True
            if e.get("date"):
                if newest_event is None or str(e["date"]) > str(newest_event):
                    newest_event = e["date"]
                if e.get("direction") == "outbound":
                    if newest_outbound is None or str(e["date"]) > str(newest_outbound):
                        newest_outbound = e["date"]
    return {"token": best_token or "nothing-sent", "newest_outbound_on": newest_outbound,
            "inbound_ever": inbound_ever, "newest_event_on": newest_event}


def opportunity_conversation_axis(root, opp_id, today=None, window=None):
    """(token, newest_outbound_on) — `opportunity_conversation_scan()`'s first two facts, kept
    as a two-tuple for the callers that unpack exactly two (`record.py`, `workflow_state`'s
    older readers). The second value feeds `networking_in_force()`."""
    scan = opportunity_conversation_scan(root, opp_id, today=today, window=window)
    return scan["token"], scan["newest_outbound_on"]


def triage_suggestion(opp, cfg, company=None, fit=None):
    """§3a — the engine's OWN pursue/pass suggestion, recomputed fresh every call (never
    stored — only `decision.suggested` freezes what THIS returned at decision time).
    Returns (suggestion, missing): suggestion is `'pursue'` | `'pass'` | `None`; `missing`
    names the input a `None` suggestion is waiting on (`profile.screen_comp()`'s own verdict,
    or `'fit-misjudged'` when CLEARS but neither company nor fit supports pursuing)."""
    tag, _detail = _profile.screen_comp(opp, cfg)
    if tag == _profile.BELOW:
        return "pass", None
    if tag in (_profile.UNDISCLOSED, _profile.UNRESOLVED, _profile.NEEDS_COMMUTE):
        return None, tag
    if tag == _profile.CLEARS:
        active = bool(company) and company.get("status") == "active-target"
        aligned = None
        if fit is not None:
            reqs = fit.get("requirements") or []
            if reqs:
                met = sum(1 for q in reqs if q.get("verdict") == "aligned")
                aligned = met * 2 >= len(reqs)
        if active or aligned or (company is None and fit is None):
            return "pursue", None
        if aligned is False and not active:
            return None, "fit-misjudged"
        return "pursue", None
    return None, tag


def workflow_state(root, opp, apps, today=None, window=None):
    """§2 — the nine-cell state of one opportunity as a dict: `application` (the axis
    token), `conversation` (the folded axis token), `networking_closed_in_force` (bool),
    `ended_because` (the ending, or None while live), plus — dev #494 / public #58 — the facts
    the same thread scan carries: `inbound_ever`, `newest_outbound_on` and `newest_event_on`
    (`opportunity_conversation_scan`). `apps` is this opportunity's own applications slice.
    Reads through `opportunity_conversation_scan()` for the conversation half — one thread
    scan, reused for the axis, the networking-in-force reading (§15.3) and the pursuit
    projection below."""
    app_axis = application_axis(opp, apps)
    scan = opportunity_conversation_scan(root, opp.get("id"), today=today, window=window)
    return {"application": app_axis, "conversation": scan["token"],
            "networking_closed_in_force": networking_in_force(opp, scan["newest_outbound_on"]),
            "ended_because": ended_because(opp, apps),
            "inbound_ever": scan["inbound_ever"],
            "newest_outbound_on": scan["newest_outbound_on"],
            "newest_event_on": scan["newest_event_on"]}


# ─────────────────────────────────────────────────────────────────────────────
# THE PURSUIT PROJECTION — dev #494 / public #58, dev #540 / public #132 (design-one-
# dashboard-surface.md r3 §3.1, "kept from r2 §1"). ADR-031 §5 decision 11 named a
# `pursuit_state()` and ADR-033 §2 reconciled it as a PROJECTION of `workflow_state()`, never
# a second derivation; nothing built it, and the opportunities bar offered four engine
# vocabularies (ATTENTION, OWNER, STAGES, COVERAGE) instead. This is that projection.
#
# THE OPTIONS, in bar order, each with the states-and-views CELLS it is the projection of
# (design-states-and-views.md §2: 1 `new`, 2 `pursue-unapplied`, 3 `applied-no-outreach`,
# 4 `reply-owed`, A `accepted-your-move`, 6 `awaiting-reply`, 7 `silent-decide`, 8 `ats-only`,
# + `in-process`, plus the application axis' own `parked` and `ended`):
#
#   your-move       a DECLARED CROSS-CUT, not a partition cell: the roles ATTENTION says need the
#                   candidate today (`attention_by_id`'s `needs-you`: classify_opportunities
#                   `now` or `decide`). OURS: r2 listed cells 1,3,4,5,A,7 for it, and r3 §3.4
#                   says its rows ARE the old `phase-pipeline-now` opportunity rows - that
#                   membership already drives the router's pipeline number, so the chip, the
#                   list and the router are one query (attention_by_id's own invariant).
#   decide          a DECLARED CROSS-CUT (dev #713 / public #145, design R4): the roles
#                   `classify_opportunities` puts in `decide` — a pursue/pass owed — i.e.
#                   `decide_ids`, the ONE definition. `your-move` is `decide_ids` plus the `now`
#                   roles, and a test proves both against the rendered page.
#   triaging        a PARTITION option (same issue; owner decision 2026-10-14: unread roles leave
#                   the decision list until read): the roles the system is still reading,
#                   `triaging_ids`. System-owned: in neither `your-move` nor `decide`, and NOT in
#                   `new` - `pursuit_state` still projects such a role as `new` (it is an
#                   undecided role), and the dashboard's `pursuit_by_id` moves it to `triaging`
#                   because only the role classification knows it is unread. A role is in `new`
#                   or in `triaging`, never both.
#   new             cell 1 - the application axis `undecided`, READ (not `triaging`)
#   conversation    cells 4, A and cell 6 where an inbound has EVER arrived
#   sent            cells 3, 6 (no inbound ever), 7, 8 - an application or a touch is out
#   not-sent        cell 2 - verdict pursue, nothing submitted: "queued to apply" (r3's label)
#   interviews      the `in-process` application axis
#   parked          the `parked` application axis
#   ended           `ended_because()` is non-null (the cause stays on the row)
#   unclassifiable  a live row whose state cannot be derived - LOUD, rendered only when
#                   non-empty, naming the field it could not read
#
# Everything except the cross-cuts PARTITIONS the live rows: `pursuit_state` returns exactly one.
# ⚠️ Cell 3 (applied, no outreach since) sits under `sent`, not `not-sent`: r2 grouped it with
# "nothing sent yet", but r3 relabelled that option "queued to apply", and an application that
# already went in is not queued. The router's `applying` count is this option's population.
PURSUIT_CROSS_CUTS = ("your-move", "decide")
PURSUIT_STATES = {
    "your-move": ("needs-you",),
    "decide": ("decide",),
    "triaging": ("triaging",),
    "new": ("new",),
    "conversation": ("reply-owed", "accepted-your-move", "awaiting-reply+inbound-ever"),
    "sent": ("applied-no-outreach", "awaiting-reply", "silent-decide", "ats-only"),
    "not-sent": ("pursue-unapplied",),
    "interviews": ("in-process",),
    "parked": ("parked",),
    "ended": ("ended",),
    "unclassifiable": (),
}
PURSUIT_PARTITION = tuple(t for t in PURSUIT_STATES if t not in PURSUIT_CROSS_CUTS)


def entry_keys(kind, titles):
    """[key, ...] aligned with `titles` (the `## ` titles of ONE staged file, in file order) -
    the ONE coverage key of a staged message (dev #496 / public #48, design r3 D5).

    A draft's title is not unique: two entries may legitimately share one (a follow-up and its
    reminder), and a key made of the title alone collapsed them into one ledger record, one
    `data-rec` and one `id` - the second was either invisible to the checker or a false
    EXACTLY ONCE gap. The key is the title for the first occurrence (so every existing key is
    unchanged) and `<title>#<n>` for the nth (n >= 2). The renderer and
    `check_dashboard_coverage.expected_records` both call this, so the ledger, `data-rec`, the
    `id="rec-..."` hash, every `data-ref` and `apply_correction.py` address one entry by one
    key, and neither side can drift. Ordinals count ALL entries of the file in order, terminal
    ones included, so a key does not change when an earlier twin is sent."""
    seen, out = {}, []
    for t in titles:
        n = seen.get(t, 0) + 1
        seen[t] = n
        out.append("%s:%s" % (kind, t) if n == 1 else "%s:%s#%d" % (kind, t, n))
    return out


def _latest_application_date(apps):
    dates = [str(a.get("date")) for a in (apps or []) if a.get("date")]
    return max(dates) if dates else None


def pursuit_state(root, opp, apps, today=None, window=None, ws=None):
    """The ONE partition token of an opportunity, as a dict: `state` (one of
    `PURSUIT_PARTITION` except `triaging`, which needs the role classification and is assigned by
    the dashboard's `pursuit_by_id`, never here), `cell` (the states-and-views cell it came from, the row's own
    finer chip), `ended_because` (the cause while `state == 'ended'`), `missing` (the field a
    loud `unclassifiable` could not read, else None) and `last_activity_on` (the newest event
    or application date - the sort key's "days since anything last happened", None when the
    record carries none: an unknown is never invented).

    A PROJECTION of `workflow_state()`, never a second derivation: `ws` may be a result the
    caller already holds, else it is computed here. A derivation that REFUSES is
    `unclassifiable` naming why - a record with no `status`, a `verdict` outside
    `validate_data.VERDICTS`, or a thread scan that raised - never silently dropped and never
    guessed into another option (design r3 §3.1; the rulebook's "an unparseable value must be
    loud")."""
    base = {"state": "unclassifiable", "cell": None, "ended_because": None, "missing": None,
            "last_activity_on": None}
    if not opp.get("status"):
        return dict(base, missing="status")
    if opp.get("verdict") not in _vd.VERDICTS:
        return dict(base, missing="verdict")
    if ws is None:
        try:
            ws = workflow_state(root, opp, apps, today=today, window=window)
        except Exception as e:                              # noqa: BLE001 - loud, not fatal
            return dict(base, missing="thread scan failed (%s)" % type(e).__name__)
    last = max([d for d in (ws.get("newest_event_on"), _latest_application_date(apps)) if d],
               default=None)
    out = dict(base, missing=None, last_activity_on=last)
    app, conv = ws["application"], ws["conversation"]
    if app == "undecided" and has_submitted_application(apps):
        # public #44 (Class A): the act decided. A row still reading `verdict: undecided` with
        # a submitted application must never be offered as `New — pursue or pass?` - project
        # it with the verdict the act implies (the one the 0.36.0 migration writes, `pursue`),
        # so it lands where its application puts it. validate_data still names the record.
        app = application_axis(dict(opp, verdict="pursue"), apps)
    if app == "ended":
        return dict(out, state="ended", cell="ended", ended_because=ws.get("ended_because"))
    if app == "parked":
        return dict(out, state="parked", cell="parked")
    if app == "in-process":
        return dict(out, state="interviews", cell="in-process")
    # reply-owed outranks every remaining application cell: a human is waiting (§2 precedence)
    if conv == "reply-owed":
        return dict(out, state="conversation", cell="reply-owed")
    if app == "undecided":
        return dict(out, state="new", cell="new")
    if conv == "accepted":
        return dict(out, state="conversation", cell="accepted-your-move")
    if app == "pursuing":
        return dict(out, state="not-sent", cell="pursue-unapplied")
    if app == "applied":
        if ws.get("networking_closed_in_force"):
            return dict(out, state="sent", cell="ats-only")
        applied_on = _latest_application_date(
            [a for a in (apps or []) if a.get("status") in _vd.SUBMITTED_APP_STATUS])
        out_on = ws.get("newest_outbound_on")
        if not out_on or (applied_on and str(out_on) < str(applied_on)):
            return dict(out, state="sent", cell="applied-no-outreach")
        if conv == "silent":
            return dict(out, state="sent", cell="silent-decide")
        if ws.get("inbound_ever"):
            return dict(out, state="conversation", cell="awaiting-reply")
        return dict(out, state="sent", cell="awaiting-reply")
    return dict(out, missing="application axis %r" % app)


# ─────────────────────────────────────────────────────────────────────────────
# READY STAGED MESSAGES WITH NO ASK — dev #154 (GitHub issue #154).
#
# Your Move was built from asks.jsonl (plus the derived role/channel views), so a draft
# fully staged and cleared to send — precondition state `sendable` — with no corresponding
# ask appeared NOWHERE on the queue: it read as "nothing is waiting" rather than as work in
# hand. ⛔ NOT fixed by auto-creating an ask: dev #142 established that a silently
# manufactured (or closed) ask is worse than the gap, because an ask that appears and
# vanishes without a decision is unreviewable. The drafts store is the source of truth for
# drafts, so the queue line is DERIVED from it — exactly how role rows are derived from
# opportunities.jsonl — and leaves by itself when the draft is sent (the sent-and-logged
# rule retires the `## ` entry) or an ask takes over.
#
# Composition with dev #169: membership starts from precondition.report(), which owns the
# staged-message pair (drafts.md AND cover_letters.md) and keys rows by (file, title). Only
# state `sendable` is a candidate here — a HELD message (any precondition.NOT_SENDABLE
# state) is a different state with its own dashboard section and must never read as ready.
# ─────────────────────────────────────────────────────────────────────────────

# Generic words that carry no identifying signal between an ask and a draft title.
_COVER_STOP = frozenset(
    "the a an and or of for to in on with at by from this that draft message note email "
    "send sent follow following".split())

# The same duplicate threshold check_sections.py uses for its ONE-ITEM-ONE-SECTION rule:
# >= 2 shared distinctive words covering >= 60% of the smaller keyword set. Copied shape,
# same constants — a second, different notion of "the same subject" would let an item pass
# one check and fail the other.
_COVER_MIN_SHARED = 2
_COVER_RATIO = 0.6


def _subject_keywords(text):
    t = re.sub(r"\[.*?\]\(.*?\)", " ", str(text).lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return {w for w in t.split() if len(w) > 3 and w not in _COVER_STOP}


def ask_covers_staged_message(ask, title):
    """Does this OPEN ask already put a queue line on the surface for the staged message
    `title`? Keyword overlap between the draft's title and the ask's title+text, at
    check_sections.py's duplicate threshold.

    Direction of error, deliberately: a MISSED cover renders two lines about one subject —
    visible, annoying, and the exact duplication dev #142's reporter hit, but self-evident
    on the page. A FALSE cover suppresses only the derived queue line; the ask's own line
    still names the same subject and the full draft still renders in its panel, so the
    message is never invisible — which is the failure #154 exists to close."""
    kd = _subject_keywords(title)
    ka = _subject_keywords("%s %s" % (ask.get("title") or "", ask.get("ask") or ""))
    if not kd or not ka:
        return False
    overlap = kd & ka
    return (len(overlap) >= _COVER_MIN_SHARED
            and len(overlap) >= min(len(kd), len(ka)) * _COVER_RATIO)


def ready_staged_without_ask(root, asks=None, pre_rows=None):
    """[{'file','title','why'}] — every staged message precondition.py reports `sendable`
    that no open ask covers. These are the queue's derived draft lines; a covered draft's
    queue line is the ask itself (one item, one section), and a held/unreadable/unresolved
    one belongs to the held sections, never here."""
    if pre_rows is None:
        pre_rows = _pre.report(root)
    open_ = open_asks(asks if asks is not None else _load_jsonl(root, "asks.jsonl"))
    out = []
    for r in pre_rows:
        if r.get("state") != "sendable":
            continue
        if any(ask_covers_staged_message(a, r["title"]) for a in open_):
            continue
        out.append({"file": r.get("file", _pre.FILES[0]), "title": r["title"],
                    "why": "staged and cleared to send; no open ask points at it"})
    return out


def _load_jsonl(root, name):
    path = os.path.join(root, "data", name)
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except OSError:
        pass
    return out


def parse_blocked_until(raw):
    """'contact:x outcome:accepted|replied' -> {'contact': 'x', 'outcomes': {...}}, or the
    sentinel `_pre.UNRESOLVED` for the literal `unresolved`. Raises `PreconditionError` on
    anything else — never guessed over, same rule precondition.py enforces for drafts."""
    if _pre.UNRESOLVED_RE.match(str(raw)):
        return _pre.UNRESOLVED
    return _pre.parse(raw)


def role_state(o, today):
    """(state, why) for one LIVE, owner-owned opportunity row. See the module docstring for
    the precedence order this implements."""
    raw = o.get("blocked_until")
    if raw is not None:
        try:
            parsed = parse_blocked_until(raw)
        except _pre.PreconditionError as e:
            return "unresolved", "blocked_until is unreadable: %s" % e
        if parsed == _pre.UNRESOLVED:
            return "unresolved", ("blocked_until is the literal 'unresolved' — no structured "
                                  "join yet; write contact:<id> outcome:<...>")
        # THE RECORD'S OWN touches, never the global pipeline (see module docstring).
        # ADR-031 B1 — `person_id`, was `contact_id`. ADR-031 B3 — `_touch_rows(o)`, the
        # caller's own join against the top-level `touches` store, never a nested array.
        touches = {}
        for r in _touch_rows(o):
            cid = r.get("person_id")
            if cid:
                touches.setdefault(cid, []).append(r)
        ok, why = _pre.resolve(parsed, touches)
        if not ok:
            return "waiting", why
        # Precondition satisfied — an unfired trigger has fired, so fall through to the date
        # check below exactly as an opportunity with no blocked_until at all would.
    d = o.get("next_action_date")
    if d and str(d) > today:
        return "scheduled", "next_action_date %s is in the future" % d
    return "now", ""


def is_your_move_candidate(o, owner_token):
    """Does this opportunity row belong on the Your Move surface AT ALL (in some group)?
    The ONE membership predicate — `classify_opportunities` and `check_sections.py`'s
    duplicate-ask rule both use it; nothing re-derives it.

    Membership = owned by `owner_token` AND (a LIVE status, or — dev #142 — `backlog` with
    `verdict: undecided`, the state a newly sourced role starts in). `backlog` with any
    DECIDED verdict (`parked`, `pass`) stays off: that is the clutter issue #79 removed.

    ⭐ And a decision made by ACTING counts as decided (public #44): a backlog row whose own
    applications prove a submission does not owe a pursue-or-pass answer, whatever its
    `verdict` field still says — the ask would be about a role already applied to.
    validate_data flags that row as a contradiction and the 0.36.0 migration sets the
    verdict the act implies; this predicate stops asking in the meantime.

    ⭐ ADR-031 B2: reads `o["_applications"]` — the caller's own join against the top-level
    `applications` store (`applications.enrich_opportunities(root, opps)`, called once after
    loading opportunities), never a nested array on `o` itself. A caller that never enriched
    `opps` gets `()` here (`applications.attach`'s own default), which is the honest "no
    applications known" answer rather than a crash."""
    if o.get("next_action_owner") != owner_token:
        return False
    return (o.get("status") in LIVE_OPP_STATUSES
            or (o.get("status") == "backlog" and o.get("verdict") == "undecided"
                and not has_submitted_application(o.get("_applications"))))


def invisible_reason(o, owner_token):
    """None if this row reaches some Your Move group, else ONE line saying why it never
    will — the record-creation advisory's text (dev #142 / public #24: the reporter's row
    was invisible *silently*, and the silence, not just the membership, was the defect).
    Only meaningful for rows that name `owner_token`; others return None (a row owned by
    someone else is invisible by design, not by accident)."""
    if o.get("next_action_owner") != owner_token:
        return None
    if is_your_move_candidate(o, owner_token):
        return None
    st = o.get("status")
    if st == "backlog" and o.get("verdict") == "undecided":
        return ("status 'backlog' with verdict 'undecided' but a submitted application on "
                "the record — the act decided; set verdict to 'pursue' (the row still "
                "renders in the opportunity list, never as a pursue/pass ask)")
    if st == "backlog":
        return ("status 'backlog' with verdict %r is a decided \"not now\" and never "
                "surfaces on Your Move; if a pursue/pass decision is still owed, set "
                "verdict to 'undecided'" % (o.get("verdict"),))
    return ("status %r is outside what Your Move reads (%s, or 'backlog' with verdict "
            "'undecided')" % (st, " / ".join(sorted(LIVE_OPP_STATUSES))))


# ─────────────────────────────────────────────────────────────────────────────
# THE TRIAGE GATE — dev #713 / public #145 (design-sourcing-screen.md §7.1, R3).
# See the module docstring's `triaging` section for the rule; this is its one implementation.
# ─────────────────────────────────────────────────────────────────────────────

# Why a JD read was TRIED AND FAILED (R3). A closed set: the validator (validate_data.py) checks
# the same prefix, and an unlisted reason does NOT satisfy `jd-read` here — an unreadable value is
# loud (the role keeps waiting, then surfaces as stuck), never silently accepted.
TRIAGE_UNAVAILABLE_PREFIX = "unavailable:"
TRIAGE_UNAVAILABLE_REASONS = ("login-wall", "dead-link", "no-url", "surface-cannot-read")
# What a lean may say. `ask` is the default when the system could not form one.
TRIAGE_LEANS = ("pursue", "pass", "ask")
# Everything a role must carry before the candidate is asked about it, in the order the triage
# step fills them. These are `triage_missing()`'s tokens.
TRIAGE_FIELDS = ("jd-read", "pay-as-written", "setting-as-written", "screen", "lean")

# The two bounds (R3). Read by their dotted `config.json` path, with the registered default and
# range, so this module works on a profile whose file predates the keys (the 0.67.0 migration seeds
# them). An out-of-range or non-integer value falls back to the default here, and doctor.py's
# CONFIG CURRENCY is what names it — this reader never raises into a dashboard render.
TRIAGE_STUCK_DAYS_KEY = "search.triage_stuck_days"
TRIAGE_STUCK_DAYS_DEFAULT = 3
TRIAGE_STUCK_DAYS_BOUNDS = (1, 14)
TRIAGE_PER_RUN_KEY = "search.triage_per_run"
TRIAGE_PER_RUN_DEFAULT = 10
TRIAGE_PER_RUN_BOUNDS = (1, 50)


def _triage_setting(key, default, bounds, cfg=None):
    if cfg is None:
        try:
            cfg = _profile.config()
        except (OSError, ValueError, KeyError):
            cfg = {}
    node = cfg
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, bool) or not isinstance(node, int):
        return default
    return node if bounds[0] <= node <= bounds[1] else default


def triage_stuck_days(cfg=None):
    """Days a role may stay `triaging` before it surfaces in Decide as not yet read."""
    return _triage_setting(TRIAGE_STUCK_DAYS_KEY, TRIAGE_STUCK_DAYS_DEFAULT,
                           TRIAGE_STUCK_DAYS_BOUNDS, cfg)


def triage_per_run(cfg=None):
    """At most this many roles are read by one run's triage step."""
    return _triage_setting(TRIAGE_PER_RUN_KEY, TRIAGE_PER_RUN_DEFAULT,
                           TRIAGE_PER_RUN_BOUNDS, cfg)


def jd_unavailable_reason(opp):
    """The closed reason a JD read was tried and failed, or None. `fit.jd_source` null (or any
    other string) is NOT this: null means not tried, and an `unavailable:` value whose reason is
    not in `TRIAGE_UNAVAILABLE_REASONS` is unreadable, so it returns None too."""
    fit = opp.get("fit")
    src = fit.get("jd_source") if isinstance(fit, dict) else None
    if not isinstance(src, str) or not src.startswith(TRIAGE_UNAVAILABLE_PREFIX):
        return None
    reason = src[len(TRIAGE_UNAVAILABLE_PREFIX):].strip()
    return reason if reason in TRIAGE_UNAVAILABLE_REASONS else None


def _recorded_lean(opp):
    """The stored `lean` object when it is well-formed, else None: a `lean` in
    `TRIAGE_LEANS` and a non-empty one-line `line` (design §3.7)."""
    ln = opp.get("lean")
    if (isinstance(ln, dict) and ln.get("lean") in TRIAGE_LEANS
            and isinstance(ln.get("line"), str) and ln["line"].strip()):
        return ln
    return None


_TITLE_PROFILE_CACHE = {"key": None, "profile": None}


def _title_profile():
    """The merged profile `profile.title_keys` hashes (config + user, as `profile.load()`), cached on
    the two files' size and mtime so a dashboard render that asks per role reads them once. None
    when it cannot be read: an unreadable profile must never make every stored screen look stale."""
    try:
        key = tuple((st.st_mtime_ns, st.st_size) for st in
                    (os.stat(_profile.CONFIG_PATH), os.stat(_profile.USER_PATH)))
    except OSError:
        return None
    if _TITLE_PROFILE_CACHE["key"] != key:
        try:
            _TITLE_PROFILE_CACHE.update(key=key, profile=_profile.load())
        except (OSError, ValueError):
            return None
    return _TITLE_PROFILE_CACHE["profile"]


def triage_missing(opp, title_profile=None):
    """[token, ...] naming each thing this role still lacks before it is the candidate's
    decision — the ONE definition of the triage gate (dev #713 / public #145, design §7.1).
    Empty means triaged. Tokens are `TRIAGE_FIELDS`, in that order.

      jd-read             `fit.analyzed_on` and `fit.jd_source`, or a read that was tried and
                          failed (`unavailable: <reason>`, R3)
      pay-as-written      `listed_pay` (even `none-shown`), or the candidate's own `comp.max`
      setting-as-written  `location.declared`, the posting's verbatim text (`none stated` counts)
      screen              the stored hard-screen result (`screen.verdict`), computed under TODAY'S
                          title keys (dev #722 / public #156, R2: a stored screen whose
                          `title_keys` is not today's hash, or has none once a
                          `screen.title_floor` is set, is re-screened -- once, through this path)
      lean                a well-formed `lean`; WAIVED when the read is unavailable, because the
                          lean then defaults to `ask` (`decide_lean`)

    A stale screen is otherwise not re-derived here: staleness needs an edit timestamp the store
    does not carry, and a second derivation is how Decide and needs-you drifted apart. The one
    staleness this DOES read is the title keys' (`profile.screen_is_title_stale`), because it is a
    hash the screen stored about itself, not an edit time. `title_profile` is the merged profile to
    hash against (default: the one on disk)."""
    missing = []
    reason = jd_unavailable_reason(opp)
    fit = opp.get("fit") if isinstance(opp.get("fit"), dict) else {}
    src = fit.get("jd_source")
    read = bool(fit.get("analyzed_on")) and isinstance(src, str) and bool(src.strip()) \
        and not src.startswith(TRIAGE_UNAVAILABLE_PREFIX)
    if not (read or reason):
        missing.append("jd-read")
    lp, comp = opp.get("listed_pay"), opp.get("comp")
    if not ((isinstance(lp, dict) and lp.get("state"))
            or (isinstance(comp, dict) and comp.get("max") is not None)):
        missing.append("pay-as-written")
    loc = opp.get("location")
    declared = loc.get("declared") if isinstance(loc, dict) else None
    if not (isinstance(declared, str) and declared.strip()):
        missing.append("setting-as-written")
    scr = opp.get("screen")
    if not (isinstance(scr, dict) and scr.get("verdict")):
        missing.append("screen")
    else:
        tp = title_profile if title_profile is not None else _title_profile()
        if tp is not None and _profile.screen_is_title_stale(scr, tp):
            missing.append("screen")
    if not (_recorded_lean(opp) or reason):
        missing.append("lean")
    return missing


def _iso_day(v):
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def first_seen(opp):
    """ISO date of the role's first sighting (the earliest readable `sightings[].seen_on`), or
    None. The triage clock and the oldest-first drain order both run from here."""
    days = [d for d in (_iso_day(s.get("seen_on")) for s in (opp.get("sightings") or [])
                        if isinstance(s, dict)) if d]
    return min(days).isoformat() if days else None


def triage_waited_days(opp, today):
    """Whole days since the first sighting, or None when there is no readable sighting date or
    it lies in the future — an unknown age is never invented as zero."""
    seen, now = _iso_day(first_seen(opp)), _iso_day(today)
    if seen is None or now is None:
        return None
    n = (now - seen).days
    return n if n >= 0 else None


def triage_is_stuck(opp, today, stuck_days):
    """Has this untriaged role waited past the bound? An UNKNOWN age counts as stuck: a gate
    that cannot measure its own wait must not be able to hold a role forever."""
    waited = triage_waited_days(opp, today)
    return waited is None or waited >= stuck_days


def _stuck_line(opp, today):
    """The Decide label for a role that surfaced without being fully triaged: why there is no
    real lean. A read that was tried and failed says so; otherwise it is the wait."""
    reason = jd_unavailable_reason(opp)
    if reason:
        return "not read: %s" % reason
    waited = triage_waited_days(opp, today)
    return ("not yet read (waited %d days)" % waited if waited is not None
            else "not yet read (age unknown)")


def age_first_move_line(opp):
    """`FIRST MOVE: <text>` when the role's STORED screen carries the age flag (an over-age or
    unknown-age recruiter role, dev #716 / public #142, design §6.2), else None. One text with the
    screen's own age line (`profile.age_flag_first_move`)."""
    text = _profile.age_flag_first_move(opp.get("screen"))
    return "FIRST MOVE: %s" % text if text else None


def decide_lean(opp, today=None, stuck_days=None):
    """The lean the Decide card shows for `opp`: {"lean", "line", "signals", "source"} or None.
    `source` says where it came from:

      recorded     the role is fully triaged and the triage step wrote the lean (with any
                   matched likely-pass `signals`)
      unavailable  fully triaged around a read that was tried and failed: `ask`, `not read:
                   <reason>` (R3). When the stored screen also carries the age flag (an over-age
                   or unknown-age recruiter role, design §6.2) the line adds `FIRST MOVE: <text>`;
                   the default for an age-flagged role is `ask` whichever way the lean is reached
                   (`record.py lean` with no `--lean` writes it, dev #716)
      stuck        NOT fully triaged but past the bound: `ask`, `not yet read (waited K days)`;
                   a stored lean on a half-triaged role is not trusted over the label

    None for a role still inside the bound. A lean NEVER removes a role."""
    today = today or datetime.date.today().isoformat()
    if triage_missing(opp):
        stuck_days = triage_stuck_days() if stuck_days is None else stuck_days
        if triage_is_stuck(opp, today, stuck_days):
            return {"lean": "ask", "line": _stuck_line(opp, today), "signals": [],
                    "source": "stuck"}
        return None
    rec = _recorded_lean(opp)
    if rec:
        sigs = rec.get("signals")
        return {"lean": rec["lean"], "line": rec["line"].strip(),
                "signals": [x for x in sigs if isinstance(x, dict)] if isinstance(sigs, list)
                else [], "source": "recorded"}
    line = _stuck_line(opp, today)
    first_move = age_first_move_line(opp)
    if first_move:
        line = "%s; %s" % (line, first_move)
    return {"lean": "ask", "line": line, "signals": [], "source": "unavailable"}


def classify_opportunities(opps, owner_token, today=None, stuck_days=None):
    """[(opp, state, why)] for every opportunity `is_your_move_candidate` admits — the ONE
    definition of Your Move role-group membership. `generate_dashboard.py` consumes this;
    it must never re-derive the filter itself.

    A `backlog`+`undecided` row lands in `decide` regardless of its date (dev #142 — the
    date is a deadline on a decision already owed, not a reveal date), unless an unfired or
    unreadable `blocked_until` outranks it exactly as it would for a live row.

    ⭐ dev #713 / public #145 — it lands in `decide` only once the system has triaged it
    (`triage_missing` empty). Until then it is `triaging`, system-owned and not "needs you",
    UNLESS it has waited `stuck_days` (default `search.triage_stuck_days`) from its first
    sighting: then it surfaces in `decide` as `not yet read (waited K days)` (R3 — the gate
    always exits). `stuck_days` is resolved once per call, not per row."""
    today = today or datetime.date.today().isoformat()
    out = []
    for o in opps:
        if not is_your_move_candidate(o, owner_token):
            continue
        state, why = role_state(o, today)
        if o.get("status") == "backlog" and state in ("scheduled", "now"):
            d = o.get("next_action_date")
            act = " (act by %s)" % d if d else ""
            missing = triage_missing(o)
            if not missing:
                state = "decide"
                why = "verdict is 'undecided' — a pursue/pass decision is owed%s" % act
            else:
                if stuck_days is None:
                    stuck_days = triage_stuck_days()
                if triage_is_stuck(o, today, stuck_days):
                    state = "decide"
                    why = ("verdict is 'undecided' — a pursue/pass decision is owed%s; %s, "
                           "lean: ask" % (act, _stuck_line(o, today)))
                else:
                    state = "triaging"
                    why = "the system is still reading this role — missing: %s" % ", ".join(missing)
        out.append((o, state, why))
    return out


def decide_ids(opps, owner_token, today=None, stuck_days=None):
    """{opp id} the candidate owes a pursue/pass decision on — the ONE definition of the Decide
    group (dev #713 / public #145, design R4). The dashboard's Decide group and its needs-you
    filter (`decide_ids` plus the `now` roles) both render exactly this set, and a test proves
    it against the rendered page."""
    return {o["id"] for o, st, _w in classify_opportunities(opps, owner_token, today, stuck_days)
            if st == "decide" and o.get("id")}


def triaging_ids(opps, owner_token, today=None, stuck_days=None):
    """{opp id} the system is still reading — the `triaging` group, owned by nobody's queue."""
    return {o["id"] for o, st, _w in classify_opportunities(opps, owner_token, today, stuck_days)
            if st == "triaging" and o.get("id")}


def _untriaged(opps, owner_token, today, stuck_days):
    """[(opp, state)] for every role the triage step should read: `triaging`, and `decide`
    rows that surfaced only by the stuck rule (still missing fields). Oldest first sighting
    first, an unknown age before any known one (it is the one most likely to be starved),
    then id for a stable order."""
    rows = [(o, st) for o, st, _w in classify_opportunities(opps, owner_token, today, stuck_days)
            if st in ("triaging", "decide") and triage_missing(o)]
    rows.sort(key=lambda r: (first_seen(r[0]) or "", str(r[0].get("id") or "")))
    return rows


def triage_queue(opps, owner_token, today=None, per_run=None, stuck_days=None):
    """What one run's triage step does next, as a dict: `cap` (roles this run may read),
    `waiting` (roles in `triaging`), `over_stuck_bound` (roles surfaced in Decide by the stuck
    rule and still unread) and `batch` — at most `cap` rows `{id, title, state, missing,
    first_seen, waited_days}`, oldest capture first. The cap is the bound that makes the drain
    finite (R3): a backlog of any size empties in ceil(waiting / cap) runs."""
    today = today or datetime.date.today().isoformat()
    stuck_days = triage_stuck_days() if stuck_days is None else stuck_days
    cap = triage_per_run() if per_run is None else per_run
    rows = _untriaged(opps, owner_token, today, stuck_days)
    return {
        "cap": cap,
        "waiting": sum(1 for _o, st in rows if st == "triaging"),
        "over_stuck_bound": sum(1 for _o, st in rows if st == "decide"),
        "batch": [{"id": o.get("id"), "title": o.get("title"), "state": st,
                   "missing": triage_missing(o), "first_seen": first_seen(o),
                   "waited_days": triage_waited_days(o, today)}
                  for o, st in rows[:cap]],
    }


def triage_line(waiting, triaged, over):
    """The one line the triage step prints (design R3): the measure of the drain."""
    return ("triaging: %d waiting, %d triaged this run, %d over the stuck bound"
            % (waiting, triaged, over))


def triage_report(opps, owner_token, batch_ids, today=None, stuck_days=None):
    """The counts behind `triage_line`, measured AFTER the run's reads: `waiting` roles still
    `triaging`, `triaged` of this run's `batch_ids` that no longer lack anything (or left the
    queue because the screen removed them), `over_stuck_bound` roles in Decide by the stuck
    rule and still unread. Returns {"waiting", "triaged", "over_stuck_bound", "line"}."""
    today = today or datetime.date.today().isoformat()
    stuck_days = triage_stuck_days() if stuck_days is None else stuck_days
    rows = _untriaged(opps, owner_token, today, stuck_days)
    still = {o.get("id") for o, _st in rows}
    waiting = sum(1 for _o, st in rows if st == "triaging")
    over = sum(1 for _o, st in rows if st == "decide")
    known = {o.get("id") for o in opps}
    triaged = sum(1 for b in dict.fromkeys(batch_ids) if b in known and b not in still)
    return {"waiting": waiting, "triaged": triaged, "over_stuck_bound": over,
            "line": triage_line(waiting, triaged, over)}


def derive_channel_last_touch(channel, messages, involvements=()):
    """(date, evidence) — the ISO date of the channel's most recently derived touch and a
    short string naming what produced it, or (None, None) if it has neither.

    max of: the latest OUTBOUND message.person_id joining any person INVOLVED IN THIS
    CHANNEL (ADR-031 B1 — `channels.contacts[]` is retired; `involvements.channel_id` is the
    join now, `person_id` resolved against it rather than `contact_id` against a nested
    array), and the latest log[] entry date. Never a hand-authored field. `involvements`
    defaults to `()` so a caller with none yet still gets the log-only half of the answer."""
    person_ids = {i.get("person_id") for i in involvements
                 if i.get("channel_id") == channel.get("id") and i.get("person_id")}
    candidates = []
    if person_ids:
        for m in messages:
            if m.get("direction") == "outbound" and m.get("person_id") in person_ids:
                d = m.get("sent_on")
                if d:
                    candidates.append((str(d), "message %s" % (m.get("id") or "?")))
    for e in (channel.get("log") or []):
        d = e.get("date")
        if d:
            candidates.append((str(d), "log entry (%s)" % (e.get("note") or d)))
    if not candidates:
        return None, None
    return max(candidates, key=lambda t: t[0])


def channel_state(c, messages, today, involvements=()):
    """(state, derived_date, evidence) for one channel carrying a next_touch plan."""
    nt = c.get("next_touch") or {}
    plan = str(nt.get("date"))
    touch, evidence = derive_channel_last_touch(c, messages, involvements)
    # THE FULFILMENT RULE. On-or-after fulfils; strictly earlier does not — see module
    # docstring for why the asymmetry is deliberate.
    if touch and touch >= plan:
        return "fulfilled", touch, evidence
    if plan > today:
        return "scheduled", touch, evidence
    return "now", touch, evidence


def classify_channels(channels, messages, today=None, involvements=()):
    """[(channel, state, derived_date, evidence)] for every channel carrying a next_touch
    plan. A channel with no plan at all is not a candidate and is excluded here, unchanged
    from before this module existed."""
    today = today or datetime.date.today().isoformat()
    out = []
    for c in channels:
        nt = c.get("next_touch")
        if not isinstance(nt, dict) or not nt.get("date"):
            continue
        state, touch, evidence = channel_state(c, messages, today, involvements)
        out.append((c, state, touch, evidence))
    return out


def contact_joinability_gaps(channels, involvements=()):
    """Channel ids carrying a next_touch plan but no joinable person anywhere in
    `involvements` (ADR-031 B1 — was: nowhere in `contacts[]`) — the outbound-message half of
    the derivation can then never fire for them, and their last touch silently degrades to
    log[]-only forever. Declaring this is the gate-must-assert-its-own-coverage rule: a
    derivation that can never see half its inputs has to say so, not just return a
    quietly-partial answer."""
    channel_ids_with_people = {i.get("channel_id") for i in involvements
                               if i.get("channel_id") and i.get("person_id")}
    gaps = []
    for c in channels:
        nt = c.get("next_touch")
        if not isinstance(nt, dict) or not nt.get("date"):
            continue
        if c.get("id") not in channel_ids_with_people:
            gaps.append(c.get("id") or c.get("label") or "?")
    return gaps


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFY_PEOPLE — ADR-031 B4, design §14: the correction to Part 1's `network_due.py`, folded
# into this module's own stated ownership of "which group does this row belong in?" A person's
# `access.py`/`graph.warmth()` reach state (the full warm/contacted/known/thin table) is B5's
# own deliverable (design §11/§16 item 5); this classifier needs only ONE narrower fact from
# that future table early — "has this person answered recently" — so it reads it directly here
# rather than waiting on a module that does not exist yet. `access.py` may fold this in later
# without changing this function's own contract.
# ─────────────────────────────────────────────────────────────────────────────

PEOPLE_STATES = ("due", "awaiting-intro", "quiet", "fresh")


def _last_touch_date(person_id, g, as_of, ended_ctx=None):
    """The most recent event (an outbound/inbound touch, or a message) involving this person,
    on or before `as_of` — the same "touches ∪ messages" union design §14 states.

    ⭐ public #95 — a touch whose OWN opportunity has ENDED is excluded from this union
    (`touch_state(..., ended_ctx)[0] == 'ended'`), `ended_ctx` optional so a caller with no
    context yet (or a test exercising the pre-#95 shape) still gets an answer, just without
    the exclusion. Without it, a touch that is really "we told you no" (a rejection, a
    portal close) resets the cadence clock as if it were a genuine relationship touch — the
    scenario `classify_people`'s own docstring below plants: a person touched only through a
    since-ended pursuit reads as freshly touched, when nothing about the RELATIONSHIP
    actually happened recently. Messages are read unfiltered here on purpose — an inbound
    reply is evidence a human engaged, whatever the pursuit's fate, and this module scopes
    the exclusion to what public #95 actually reported (a stale TOUCH, not a stale reply)."""
    dates = []
    for t in g.touches_for_person(person_id):
        if ended_ctx is not None and touch_state(t, ended_ctx)[0] == "ended":
            continue
        d = t.get("date")
        if d and str(d)[:10] <= as_of:
            dates.append(str(d)[:10])
        rd = t.get("responded_on")
        if rd and str(rd)[:10] <= as_of:
            dates.append(str(rd)[:10])
    for m in g.messages_for_person(person_id):
        d = m.get("sent_on")
        if d and str(d)[:10] <= as_of:
            dates.append(str(d)[:10])
    return max(dates) if dates else None


def _has_recent_inbound(person_id, g, as_of, window_days):
    for m in g.messages_for_person(person_id):
        if m.get("direction") != "inbound":
            continue
        d = m.get("sent_on")
        if not d or str(d)[:10] > as_of:
            continue
        try:
            elapsed = (_parse_date(as_of) - _parse_date(str(d)[:10])).days
        except ValueError:
            continue
        if elapsed <= window_days:
            return True
    return False


def _awaiting_intro_object(person_id, g, as_of):
    """design §12/§14 — is `person_id` the OBJECT of a still-open intro-request touch (design
    §12's introduction shape)? Returns the requester's own id, or None."""
    for t in g.stores["touches"]:
        if t.get("touch_type") != "intro-request" or t.get("outcome") != "awaiting":
            continue
        if t.get("object_person_id") == person_id:
            return t.get("person_id")
    return None


def classify_people(root, today=None, warm_days=180):
    """[(person, state, why)] — design §14's classifier, the ONE owner of Your Move people-due
    membership (`network_due.py` folds in here, never a second owner). `root` is the profile
    root; a fresh `graph.Graph` is built once per call (the module's own convention).

    ⭐ public #95 — a cadence-due read must not be driven by a touch whose OWN pursuit has
    ended: `build_ended_context(root)` is built once here and threaded into
    `_last_touch_date` so a person touched only through a since-closed role is judged on
    what is left once that touch is excluded (never touched at all — `elapsed is None` —
    or, when a LIVE pursuit also touched them, that live touch alone)."""
    import graph as _graph
    today = today or datetime.date.today().isoformat()
    g = _graph.Graph(os.path.join(root, "data"))
    ended_ctx = build_ended_context(root)
    out = []
    for p in g.stores["people"]:
        if p.get("status") == "merged":
            continue
        pid = p.get("id")
        requester = _awaiting_intro_object(pid, g, today)
        if requester is not None:
            out.append((p, "awaiting-intro",
                       "an introduction to this person, requested by %s, is still awaiting"
                       % requester))
            continue
        last = _last_touch_date(pid, g, today, ended_ctx=ended_ctx)
        cadence = p.get("cadence")
        if isinstance(cadence, int) and not isinstance(cadence, bool):
            elapsed = None
            if last:
                try:
                    elapsed = (_parse_date(today) - _parse_date(last)).days
                except ValueError:
                    elapsed = None
            if elapsed is None or elapsed >= cadence:
                out.append((p, "due", "cadence %d day(s); last touch %s"
                           % (cadence, last or "never")))
            else:
                out.append((p, "fresh", "touched %s, within the %d-day cadence"
                           % (last, cadence)))
            continue
        if _has_recent_inbound(pid, g, today, warm_days):
            out.append((p, "quiet", "answers within %d days but has no cadence set — the plan "
                       "is missing, not the touch" % warm_days))
        # else: nothing owed, nothing missing — renders nowhere (design §14).
    return out


def network_people_due(root, today=None, warm_days=180):
    """dev #686 / public #139 (E1) — the NETWORK VIEW's membership, the ONE definition the
    dashboard's `People due` block renders and `check_dashboard_coverage.py` holds the page to.

    Built on `classify_people` (which stays the one owner of people-due) and adds exactly one
    rule: a person who has an `involvements` row with an `opp_id` is NOT here, because they
    surface through their pursuit. Merges are followed on both sides (an involvement naming an
    absorbed id counts for its survivor).

    Returns `{"due": [(person, state, why)], "fresh": N}`: `due` the person-only people whose
    state is `due` or `awaiting-intro`, sorted state then name; `fresh` the count of the
    person-only people still within their cadence."""
    import graph as _graph
    g = _graph.Graph(os.path.join(root, "data"))
    with_opp = set()
    for inv in g.stores["involvements"]:
        if not inv.get("opp_id"):
            continue
        try:
            surv = g.resolve_person(inv.get("person_id"))
        except _graph.MergeCycleError:
            surv = None
        with_opp.add((surv or {}).get("id") or inv.get("person_id"))
    due, n_fresh = [], 0
    for person, state, why in classify_people(root, today, warm_days):
        if person.get("id") in with_opp:
            continue
        if state in ("due", "awaiting-intro"):
            due.append((person, state, why))
        elif state == "fresh":
            n_fresh += 1
    due.sort(key=lambda r: (r[1], str(r[0].get("name") or ""), str(r[0].get("id") or "")))
    return {"due": due, "fresh": n_fresh}


# ─────────────────────────────────────────────────────────────────────────────
# THE FOLLOW-UP VIEW'S MEMBERSHIP - dev #539 / public #133 (design-one-dashboard-surface.md r3
# §4). `phase-outreach-approvals` is ONE view of everything owed a message in the next
# OUTREACH_HORIZON_DAYS: the staged drafts (primary rows, bodies always shown - person-outreach
# 1b), plus a REFERENCE row for every other subject that owes one - a relationship touch due or
# planned, an application with no follow-up linked, a person due. `outreach_due` is the ONE
# owner of that membership and of its two dimensions' vocabularies; the renderer declares which
# dimensions exist and never what their values may be (the `_CLOSED_STATUSES` lesson).
#
#   when         now      sendable drafts, owner-blocked drafts (NEEDS_HUMAN: yours to fix), and
#                         every reference due on or before today + the horizon
#                waiting  held or queued drafts - waiting on the other side or on a session
#                later    references due beyond the horizon
#   sendability  precondition.OPEN_STATES, plus `undrafted` - a reference has no draft yet
#
# OURS (r3 §4, stated so a reviewer can refuse it): the default is `when = now`, not literally
# `sendability = sendable`, because the folded-in references are never `sendable` and a
# sendable-only default would hide every row #539 asked to bring in. The literal "ready to send"
# view is one click.
OUTREACH_WHEN = ("now", "waiting", "later")
OUTREACH_SENDABILITY = tuple(sorted(_pre.OPEN_STATES)) + ("undrafted",)


def outreach_when_for_draft(state):
    """`now`, or `waiting` for a draft that is HELD (waiting on the other side) or QUEUED
    (waiting on a session with a keychain). precondition owns both sets; an owner-blocked state
    (NEEDS_HUMAN) is `now` because it is yours to fix, and a sendable one is `now` by definition."""
    if state in _pre.WAITS_ON_SURFACE:
        return "waiting"
    if state in _pre.NOT_SENDABLE and state not in _pre.NEEDS_HUMAN:
        return "waiting"
    return "now"


def outreach_due(root, today=None, horizon=None, pre_rows=None, untriggered=None):
    """{"drafts": [...], "refs": [...]} - the follow-up view's membership.

    `drafts`: one dict per OPEN staged entry (`precondition.report`, terminal entries are not
    here): `{key, file, title, state, when, sendability}`, the key from `entry_keys` (unique
    even when a title repeats). `refs`: one dict per OTHER subject owing a message:
    `{kind, key, label, when, sendability: 'undrafted', due, why}` for
      * a channel relationship touch due or planned (`classify_channels` `now` / `scheduled`;
        `fulfilled` is done) -> `chan:<id>`;
      * an application with no follow-up linked (`untriggered`, trigger.py's own rows, once per
        opportunity and only for a LIVE one - a terminal role owes nothing) -> `opp:<id>`;
      * a person due (`network_people_due`, the one membership People due renders) ->
        `person:<id>`.
    `when` for a reference is `now` when it is due on or before `today + horizon`, else `later`.
    `pre_rows` / `untriggered` are test and renderer seams: a caller that already ran the scan
    passes it, so the page is not scanned twice; absent, they are computed here."""
    today = today or datetime.date.today().isoformat()
    horizon = config_keys.OUTREACH_HORIZON_DAYS if horizon is None else horizon
    limit = (_parse_date(today) + datetime.timedelta(days=horizon)).isoformat()
    import _tree
    drafts_rel, covers_rel = _tree.rel("drafts"), _tree.rel("cover_letters")
    rows = _pre.report(root) if pre_rows is None else pre_rows
    drafts = []
    file_rows = [r for r in rows if r.get("file", drafts_rel) == drafts_rel]
    for r, key in zip(file_rows, entry_keys("draft", [r.get("title") for r in file_rows])):
        st = r.get("state")
        if st in _pre.OPEN_STATES:
            drafts.append({"key": key, "file": drafts_rel, "title": r.get("title"),
                           "state": st, "when": outreach_when_for_draft(st),
                           "sendability": st})
    refs = []
    channels = _load_jsonl(root, "channels.jsonl")
    for c, state, _touch, _ev in classify_channels(
            channels, _load_jsonl(root, "messages.jsonl"), today,
            _load_jsonl(root, "involvements.jsonl")):
        if state not in ("now", "scheduled") or not c.get("id"):
            continue
        nt = c.get("next_touch") or {}
        due = str(nt.get("date"))
        note = " · ".join(str(b) for b in (nt.get("time"), nt.get("note")) if b)
        refs.append({"kind": "chan", "key": "chan:%s" % c["id"],
                     "label": c.get("label") or c["id"], "due": due,
                     "when": "now" if due <= limit else "later", "sendability": "undrafted",
                     "why": "no draft yet" + (": %s" % note if note else "")})
    live = {o.get("id") for o in _load_jsonl(root, "opportunities.jsonl")
            if o.get("id") and o.get("status") not in _vd.TERMINAL_OPP_STATUSES}
    seen = set()
    for u in (untriggered or []):
        oid = u.get("opp_id")
        if not oid or oid in seen or oid not in live:
            continue
        seen.add(oid)
        refs.append({"kind": "opp", "key": "opp:%s" % oid,
                     "label": u.get("title") or oid, "due": u.get("date"),
                     "when": "now", "sendability": "undrafted",
                     "why": "no follow-up drafted"})
    for person, state, why in network_people_due(root, today)["due"]:
        if person.get("id"):
            refs.append({"kind": "person", "key": "person:%s" % person["id"],
                         "label": person.get("name") or person["id"], "due": None,
                         "when": "now", "sendability": "undrafted",
                         "why": "no draft yet: %s" % why})
    return {"drafts": drafts, "refs": refs}


def report(root, today=None):
    """Everything --json / --check need, computed once from the profile at `root`."""
    opps = _load_jsonl(root, "opportunities.jsonl")
    channels = _load_jsonl(root, "channels.jsonl")
    messages = _load_jsonl(root, "messages.jsonl")
    involvements = _load_jsonl(root, "involvements.jsonl")
    # ADR-031 B3 — o["_touches"], the join `role_state`/`_touch_rows` read; never a nested
    # array on the opportunity record any more.
    _touches.enrich_opportunities(root, opps)
    owner = _profile.owner_token()
    roles = classify_opportunities(opps, owner, today)
    chans = classify_channels(channels, messages, today, involvements)
    # public #95 — the terminal-transition cascade, over the same context every row shares.
    ended_ctx = build_ended_context(root)
    letters_rows, _errs, _present = _apps.load_cover_letters(root)
    touches_rows, _t_errs, _t_present = _touches.load(root)
    return {
        "roles": [{"id": o.get("id"), "title": o.get("title"), "state": s, "why": w}
                  for o, s, w in roles],
        "channels": [{"id": c.get("id"), "label": c.get("label") or c.get("id"), "state": s,
                      "derived_last_touch": t, "evidence": ev}
                     for c, s, t, ev in chans],
        "contact_joinability_gaps": contact_joinability_gaps(channels, involvements),
        # ADR-031 B4 (design §14) — the people-due group, folded from the retired
        # `network_due.py`. `plays.py --check`'s stalled-pursuit report is `play_stage
        # 'unresolved'`'s successor (design §19); it is not this module's to compute.
        "people": [{"id": p.get("id"), "name": p.get("name"), "state": s, "why": w}
                  for p, s, w in classify_people(root, today)],
        # dev #154: a ready staged message no ask covers is WORK IN HAND, not silence.
        "ready_staged": ready_staged_without_ask(root),
        # public #95 — every `cover_letters.jsonl` row, derived (never stored back).
        "letters": [{"id": l.get("id"), "opp_id": l.get("opp_id"),
                    "raw_status": l.get("status"), "state": s, "why": w}
                   for l in letters_rows
                   for s, w in (letter_state(l, ended_ctx),)],
        # public #95 — every `data/touches.jsonl` row's ended/active read.
        "touches": [{"id": t.get("id"), "opp_id": t.get("opp_id"),
                    "person_id": t.get("person_id"), "state": s, "why": w}
                   for t in touches_rows
                   for s, w in (touch_state(t, ended_ctx),)],
    }


def _triage_cli(root, args):
    """`--triage-queue` / `--triage-report` (dev #713). Reads the profile at `root`, writes
    nothing. Always exits 0 on a readable profile: the queue is information for the run, not
    a gate that can wedge it. A bad `--per-run` or a `--triage-report` without `--batch` is a
    usage error (2), because a silent default there would print a drain measure of nothing."""
    if args.per_run is not None and not (TRIAGE_PER_RUN_BOUNDS[0] <= args.per_run
                                         <= TRIAGE_PER_RUN_BOUNDS[1]):
        print("--per-run must be %d-%d, got %d" % (TRIAGE_PER_RUN_BOUNDS + (args.per_run,)),
              file=sys.stderr)
        return 2
    if args.triage_report and not args.batch.strip():
        print("--triage-report needs --batch ID,ID (the ids --triage-queue handed this run)",
              file=sys.stderr)
        return 2
    opps = _load_jsonl(root, "opportunities.jsonl")
    _touches.enrich_opportunities(root, opps)
    _apps.enrich_opportunities(root, opps)
    owner = _profile.owner_token()
    if args.triage_queue:
        print(json.dumps(triage_queue(opps, owner, per_run=args.per_run), indent=1))
        return 0
    ids = [i.strip() for i in args.batch.split(",") if i.strip()]
    print(triage_report(opps, owner, ids)["line"])
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any role's blocked_until is unresolved or unreadable")
    ap.add_argument("--triage-queue", action="store_true",
                    help="print, as JSON, the next batch of roles the daily run's triage step "
                         "reads (dev #713): at most --per-run, oldest first sighting first")
    ap.add_argument("--triage-report", action="store_true",
                    help="print the one-line drain measure after the reads; needs --batch")
    ap.add_argument("--per-run", type=int, default=None, metavar="N",
                    help="--triage-queue: override search.triage_per_run for this call")
    ap.add_argument("--batch", default="", metavar="ID,ID",
                    help="--triage-report: the ids --triage-queue handed this run")
    args = ap.parse_args()

    root = profile_root()
    if args.triage_queue or args.triage_report:
        return _triage_cli(root, args)
    data = report(root)

    if args.json:
        print(json.dumps(data, indent=1))
    else:
        print("YOUR MOVE — role and channel group membership\n")
        marks = {"now": "🎯", "scheduled": "🗓️ ", "waiting": "⏳", "unresolved": "🚧",
                 "decide": "🔎", "triaging": "📖"}
        for r in data["roles"]:
            print("  %s %-10s %s" % (marks[r["state"]], r["state"],
                                     (r["title"] or r["id"] or "?")[:60]))
            if r["why"]:
                print("        %s" % r["why"])
        cmarks = {"now": "🤝", "scheduled": "🗓️ ", "fulfilled": "✅"}
        for c in data["channels"]:
            print("  %s %-10s %s" % (cmarks[c["state"]], c["state"], c["label"]))
            if c["state"] == "fulfilled":
                print("        plan fulfilled on %s by %s" % (c["derived_last_touch"],
                                                                c["evidence"]))
        pmarks = {"due": "📇", "awaiting-intro": "🔗", "quiet": "🤫", "fresh": "✅"}
        for p in data["people"]:
            if p["state"] == "fresh":
                continue
            print("  %s %-14s %s" % (pmarks[p["state"]], p["state"], p["name"] or p["id"]))
            print("        %s" % p["why"])
        for r in data["ready_staged"]:
            print("  ✉️  ready       %s › %s" % (r["file"], r["title"][:60]))
            print("        %s — approve and send it, or record the ask that owns it"
                  % r["why"])
        # public #95 — the terminal-transition cascade: only the STILL-PENDING letters are a
        # queue row (used/retired/moot/sent are all over — the whole point of the
        # derivation is that nothing further renders for them).
        for l in data["letters"]:
            if l["state"] != "pending":
                continue
            label = "unrecorded" if l["raw_status"] is None else l["raw_status"]
            print("  📄 pending      cover letter %s (opp %s, status: %s)"
                  % (l["id"] or "?", l["opp_id"] or "?", label))
        n_unres = sum(1 for r in data["roles"] if r["state"] == "unresolved")
        n_fulfilled = sum(1 for c in data["channels"] if c["state"] == "fulfilled")
        print("\n  %d role(s) unresolved · %d channel plan(s) fulfilled but not yet cleared"
              % (n_unres, n_fulfilled))
        n_due = sum(1 for p in data["people"] if p["state"] == "due")
        if n_due:
            print("  %d person/people due for a reconnect" % n_due)
        n_moot_letters = sum(1 for l in data["letters"] if l["state"] == "moot")
        n_ended_touches = sum(1 for t in data["touches"] if t["state"] == "ended")
        print("  %d letter(s) moot by ending, %d touch(es) on ended pursuits"
              % (n_moot_letters, n_ended_touches))
        for gid in data["contact_joinability_gaps"]:
            print("  ⚠️  channel %s has no joinable person in involvements — its derived "
                  "touch can only ever come from log[]" % gid)

    if args.check:
        bad = False
        for r in data["roles"]:
            if r["state"] == "unresolved":
                print("⛔ %s [unresolved]: %s" % ((r["title"] or r["id"] or "?")[:60], r["why"]),
                      file=sys.stderr)
                bad = True
        for c in data["channels"]:
            if c["state"] == "fulfilled":
                print("ℹ️  %s: plan fulfilled on %s by %s; clear next_touch or author the "
                      "next one" % (c["label"], c["derived_last_touch"], c["evidence"]),
                      file=sys.stderr)
        for gid in data["contact_joinability_gaps"]:
            print("⚠️  channel %s: no joinable person in involvements — the outbound-message "
                  "half of its derived touch can never fire" % gid, file=sys.stderr)
        # ⚠️ Loud, but exit 0 — deliberately NOT blocked_until's exit-1 treatment. An
        # unresolved blocked_until makes group membership UNDECIDABLE, so the run must stop.
        # `plays.py --check` is where a STALLED play now goes loud (design §19) — this
        # function's own `--check` stays scoped to blocked_until and channel plans.
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
