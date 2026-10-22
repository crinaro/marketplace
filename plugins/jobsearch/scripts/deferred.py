#!/usr/bin/env python3
"""
Work that needs the LAPTOP — queued from anywhere, executed where the resources are.

WHY THIS EXISTS
---------------
The candidate, 2026-08-02: *"How does the coordinator connect with resources only available on the laptop
such as send a LinkedIn message through the chrome extension?"*

**The blunt answer: it doesn't, and everything in this system is laptop-bound.** The repo, the
Gmail credentials (macOS Keychain, service `claudesearch-imap`), `wake_chrome.sh` (`osascript`),
every script, and above all the **Chrome extension — which is the candidate's own logged-in browser** — all
live on the Mac. Scheduled tasks are documented as running only *"while this app is open"*, i.e.
the desktop app.

So a coordinator session that cannot reach the Mac can **decide**, but it cannot **act**.

This is the queue for the gap — the mirror of `data/inbox.jsonl`:

    data/inbox.jsonl            background run  →  coordinator     "here is what I found"
    data/pending_actions.jsonl  coordinator     →  laptop run      "here is what needs your hands"

## ⛔ WHAT THIS QUEUE MUST NEVER CARRY: A SEND

**Deliberately excluded, and this is the important part of the answer.** CLAUDE.md's standing rule
is *"NEVER send messages, emails, or applications without the candidate's explicit fresh approval."* **A
send queued now and executed by an unattended run three hours later is not fresh approval** — it is
approval-at-a-distance for an irreversible, outward-facing act. Building that would quietly convert
a hard rule into a soft one.

**And the constraint bites far less than it looks**, because the candidate sends everything directly anyway.
When Claude has sent a LinkedIn message it was always *"on the candidate's explicit in-session instruction"*,
with them present at that moment. That workflow simply requires the laptop and their attention
together — which is exactly what it required before this queue existed.

**So what belongs here is laptop-bound work that is SAFE unattended and REVERSIBLE:** a contact-path
lookup, a reply/degree check, reading a JD an ATS won't render to a plain fetch, a profile read.
Research and reads. Never a send, never an application, never a profile edit.

⭐ ENGINE-BUILT FORMS vs FREE TEXT (dev #692 / public #140, N2). The send filter below (`FORBIDDEN`)
guards FREE TEXT: `--add "<what>"` is a sentence somebody typed, and a sentence that reads like a
send never queues. It stays an ANYWHERE denylist, byte-unchanged, because free text cannot be
validated structurally and a false refusal costs one rephrase while a false pass costs a send. The
items the ENGINE builds from data fields (`--add-linkedin-pass`, `--add-research <opp_id>`,
`--add-draft <opp_id>`, and `--add-roles` — one `capture-role` item per role seen) are exempt, and
only they: each fills a fixed template whose words cannot say "send", and the claiming worker acts
on the item's `kind`, never on its `what`, so a scraped title such as "Post-Sales Engineer" stays
data. They reach the queue through ONE private writer, `_append_item`, whose callers a test pins.

⭐ A POSTURE-HELD ITEM IS NOT A FAILED ONE (dev #692). `--add-research` / `--add-draft` write
`requires: ["research"]` / `["drafting"]`. A worker claims it only when `claim_capabilities()` grants
that token: from the active posture's `unattended` list (the fixed vocabulary
`posture.MERGEABLE_POSTURE_TOKENS`, never `linkedin`), or because the run was started with the
explicit `--attended` form (owner decision R2). Until then `--claimable` lists it under
`HELD BY POSTURE` and it drains on the first run whose posture permits it.

Usage:
    ~/.claude/jobsearch/run deferred.py                       # what is waiting for the laptop
    ~/.claude/jobsearch/run deferred.py --add "<what>" --why "<why it needs the laptop>"
    ~/.claude/jobsearch/run deferred.py --add-linkedin-pass   # the owed LinkedIn pass (no text argument)
    ~/.claude/jobsearch/run deferred.py --add-research <opp_id>   # research a posture held
    ~/.claude/jobsearch/run deferred.py --add-draft <opp_id>      # a draft a posture held
    ~/.claude/jobsearch/run deferred.py --add-jd-read <opp_id> --run <run id>
                                                                  # a JD only a browser can read
    ~/.claude/jobsearch/run deferred.py --claimable [--attended]
    ~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface board
                                                                  # or linkedin-jobsearch
    ~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface board --check
                                                                  # dry run: faults + verdict, writes nothing
    ~/.claude/jobsearch/run deferred.py --settle              # close items the stores show done
    ~/.claude/jobsearch/run deferred.py --unquarantine <id>   # release a role held from a degraded sweep
    ~/.claude/jobsearch/run deferred.py --done <id>

⭐ EVERY ROLE A PASS SEES IS ACCOUNTED FOR (dev #692 / public #140, #489 / public #102).
`--add-roles` is the gate on a LinkedIn job-search or board-sweeper pass report. The report is a
`ROLES v1` block (`ROLES_GRAMMAR`, fenced byte-equal in both agent files), never a prose count: each
`ROLE` line ends up captured, known (already in the pipeline, active or passed), carried (one
`capture-role` item, `ref` the canonical URL) or a per-role gap. "N seen, top few captured" cannot
be written any more, because the rest are rows. A pass that returns with NO accepted block is a gap
(`journal.py --end`, `ROLES NOT ACCOUNTED`).

⭐ A CAPTURED ROLE CARRIES ITS PAY, ITS POSTING DATE AND ITS WORK SETTING (dev #715 / public #143,
dev #716 / public #142; jobsearch 0.67.0). A `ROLE` line ends in three slots a screen needs and the
sweep used to drop: `posted=` (a date, an `ats:` date, a shown age `<n>d`, or `?`), `pay=` (`none`,
`stated:<range>[;<range>]`, `estimate:<range>[;<range>]`, or `?`) and `setting="<verbatim>"`. The
`pay=` and `setting=` slots are REQUIRED: a line without them is a line fault, because an optional
slot would let a forgetful sweep produce silent NOT CAPTURED rows. `--add-roles` parses them itself
(`parse_pay_slot`, `parse_posted_slot`, never a model) and the `capture-role` item it queues carries
the result as `role` = `{listed_pay, posted, location_declared, location_listed, slots}` in the
shapes the opportunity stores. They reach the opportunity only when the role is created with
`record.py create <opp_id> '<json>' --from-item <that item's id>`, which copies `listed_pay`,
`posted`, `location.declared` and `location.primary` across (`record.py copy_capture_item_facts`),
and infers `location.type: onsite` (`setting_source: inferred`) for a posting whose setting the
sweep read as `none stated` at a concrete place (dev #727 / public #159); a create without
`--from-item` copies nothing, and the screen then reads NOT CAPTURED. `?` in any slot means NOT READ
and is stored as ABSENT, never as "none". A non-annual figure is carried as written (`interval` month, day, hour);
the screen routes it to review and nothing here converts it to a year.

⭐ A JD ONLY A BROWSER CAN READ IS HANDED TO A BROWSER (dev #723; jobsearch 0.69.0). When the triage
step meets a JD it cannot read on its own surface (an authenticated page, on a surface with no
browser), `--add-jd-read <opp_id> --run <run id>` queues ONE `read-jd` item for that role
(`ref` the opportunity id, `requires: [chrome]`, idempotent on `(kind, ref)`, and never served to the
run that queued it: that run could not read it). A browser-holding worker claims it through the
ordinary `--claimable` path and records the read through `record.py`. `--settle` writes
`fit.jd_source = "unavailable: surface-cannot-read"` THROUGH `record.py` once the item has waited
past `search.triage_stuck_days`; `record.py` refuses that value before then
(`introduced_row_violations`), so it cannot be written by hand early.

⭐ A DEGRADED SWEEP IS QUARANTINED, NEVER CAPTURED AS A CLEAN SET (dev #722 / public #156;
jobsearch 0.69.0). A reached `QUERY` now says what the page did NOT do (`dropped=`, `added=`,
`total=<m>+` for a lower bound) and every `ROLE url=` line says which queries showed it (`q=`). A
role every one of whose queries reported a degradation -- a named dropped or added filter,
`unapplied`, a truncated read -- is QUARANTINED: its `capture-role` item is queued with a
`quarantine` field and `--claimable` / `--claim` do not serve it. ONLY a positively reported
degradation quarantines (owner decision R3): `dropped=?`, `added=?` and a reached `total=?` page
file the query gap and are counted, and never hold a role. A later CLEAN sighting releases the
role (an append-only `_unquarantine` record), or `--unquarantine <id>`. The identity is
`distinct = captured + known + carried + quarantined + role_gaps`, refused by
`journal.record_roles` when it does not hold. ⚠️ SHAPE, NOT ENFORCED (R4): `dropped=`, `added=` and
`total=` are the sweep's own report of what a rendered page showed; no script here can tell a
dropped filter from a `none` written without looking. The tests prove the instruction and the
parser are there, never that an agent obeys it, and an acceptance replay of a real degraded board
page is not possible in CI. The defence is COUNTED, not enforced: the `roles` event carries
`q_clean` / `q_unread` / `q_total_unknown` / `q_degraded`, `run_summary.py` prints them, and
`check_runs.py` flags 7 consecutive all-clean board passes.

⭐ A LINE FAULT NEVER DISCARDS A VALID ROLE; A HAND-BACK CAN BE CHECKED FIRST (dev #707 / public
#151). A hand-back with 277 roles and one malformed QUERY line used to be refused whole, and the
hand-back was lost with the dispatch. Now only a STRUCTURAL fault (no block, two blocks, a bad
header, a run or surface that is not this call's, no END line) refuses a block. Every other fault
-- a line that fits no form, a QUERY or ROLE that breaks a rule, a duplicate posting, a SEEN count
that disagrees with the ROLE lines or the largest QUERY -- is a `partial-results` gap of its own
(scope `jobsearch:roles-line:<surface>:<line>`, naming the line, its text and the rule) and every
ROLE that parsed is recorded. The exit code says which happened:

    0  clean                  every line parsed
    4  accepted, line faults  every valid role recorded; each faulty line is a gap
    3  refused                a structural fault: one gap, nothing else written
    2  usage                  a missing --run/--surface, an unreadable file, --check without --add-roles

Whenever the call refuses or records any fault, the raw hand-back is copied byte for byte to
`<profile root>/.jobsearch/handbacks/roles-<run>-<surface>.md` (the PROFILE root, never the engine)
and the message and the gap name it. `--check` is the same parse with nothing written: it prints
each fault with its line number and rule and a one-line `verdict:` (`clean`, `N line faults`,
`refused: <why>`), and exits with the code the real call would. The dispatcher runs it on a
hand-back before accepting it, and the agents that write the block run it on their own first.

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import secrets
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()
QUEUE = os.path.join(ROOT, "data", "pending_actions.jsonl")

# A queued item matching any of these is refused outright. See the docstring: a send executed
# later by an unattended run is not the "explicit fresh approval" the standing rule requires.
FORBIDDEN = re.compile(
    r"\b(send|sending|reply to|respond to|submit|apply to|applying|post|publish|"
    r"accept|connect with|inmail|dm|message (him|her|them)|email (him|her|them))\b", re.I)


# dev #481 / public #112 -- the ONE text a LinkedIn PASS item ever carries, built here by a script
# so that every call site yields a byte-identical `what` and a failed pass can be recognised as
# "already owed". It equals the literal daily-run wrote by hand since 2026-08, so rows already on
# installs match it exactly. `why` is fixed too: no free text about the cause reaches the queue
# (the cause stays where it already goes, the run's journal gap: browser-unavailable /
# render-stalled). `requires` stays ("chrome",), today's value, so can_run()/whoami are untouched.
# A NON-pass dispatch of linkedin-runner (a contact-path lookup for a named company) is different
# work and keeps a free-text `--add "<the work>"`.
LINKEDIN_PASS_WHAT = "LinkedIn pass: reply check + inbox + job search"
LINKEDIN_PASS_WHY = "a LinkedIn pass did not complete; that run's journal gap says why"
LINKEDIN_PASS_REQUIRES = ("chrome",)

# dev #692 / public #140 (692-1b) -- the engine-built research and draft items. The `what` is a
# TEMPLATE over one validated opportunity id, the `kind` fixes the drain procedure, and `requires`
# is the posture token a worker must be granted before it may claim the item. None of the
# templates can read as a send, and none depends on the filter to be safe: the opp id is the only
# interpolated field and `OPP_ID_RE` allows no whitespace.
KIND_RESEARCH = "research-role"
KIND_DRAFT = "draft-message"
RESEARCH_WHAT = ("Research role %s: posting on the employer's own site, full JD, company "
                 "(opportunity-researcher)")
RESEARCH_WHY = "research is posture-gated or over max_agents_per_run"
RESEARCH_REQUIRES = ("research",)
DRAFT_WHAT = "Draft the next message for %s with outreach-drafter. A draft is saved, never sent."
DRAFT_WHY = "drafting is posture-gated"
DRAFT_REQUIRES = ("drafting",)
OPP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

# dev #723 (jobsearch 0.69.0) -- the engine-built JD-read item. Same shape as the two above: the `what`
# is a TEMPLATE over one validated opportunity id, `requires` is the MACHINE capability `chrome` (not a
# posture token, so `held_by_posture` is false and a browserless worker sees it under "needs another
# environment"), and the claiming worker acts on the `kind`, never on the `what`.
KIND_JD_READ = "read-jd"
JD_READ_WHAT = ("Read the JD for %s in a signed-in browser and record it on the role's fit "
                "(record.py set <id> fit ...); a login wall is recorded as unavailable: login-wall.")
JD_READ_WHY = "the JD needs a browser this surface does not have"
JD_READ_REQUIRES = ("chrome",)
SURFACE_CANNOT_READ = "unavailable: surface-cannot-read"

# ⭐ THE ROLES GRAMMAR (dev #692 / public #140, N7) -- byte-equal to the fenced copy between
# `<!-- roles-grammar:begin -->` and `<!-- roles-grammar:end -->` in BOTH
# plugins/jobsearch/agents/linkedin-runner.md and plugins/jobsearch/agents/board-sweeper.md. Edit
# all three in the same commit, or `test_roles_gate.TestRolesGrammarFence` goes red. The window
# buckets are LinkedIn's own UI options only (R5): `r86400` ("Past 24 hours") and `r604800`
# ("Past week"); there is no computed window.
ROLES_GRAMMAR = """\
--- ROLES v1 run=<run-id> surface=<linkedin-jobsearch|board> window=<daily|wide|none> ---
QUERY geo=<remote|local> title="<query>" window=<r86400|r604800|none> shown=<n> total=<m|m+|?> dropped=<none|?|<filter>[,<filter>...]> added=<none|?|<filter>[,<filter>...]> [unapplied] [channel=<channel_id>]
QUERY geo=<remote|local> title="<query>" unreachable reason=<journal.REASONS code> [channel=<channel_id>]
SEEN distinct=<n>
ROLE url=<posting url> q=<k>[,<k>...] title="<t>" company="<c>" location="<l|?>" posted=<YYYY-MM-DD|ats:YYYY-MM-DD|<n>d|?> pay=<pay|?> setting="<verbatim|none stated|?>"
ROLE nourl title="<t>" company="<c>" reason=<journal.REASONS code>
--- END ROLES ---"""

# dev #715 / public #143, dev #716 / public #142 (sourcing-screen, jobsearch 0.67.0) -- the ROLE line
# carries the three facts a screen needs and the sweep used to drop. The slots are REQUIRED: an
# optional slot would let a forgetful sweep produce silent NOT CAPTURED rows (design §4.1).
#   pay=none | stated:<range>[;<range>...] | estimate:<range>[;<range>...] | ?
#       <range> := <min>-<max>/<yr|mo|day|hr>/<CUR> | <min>+/<yr|mo|day|hr>/<CUR>
#       (integers, no separators, a three-letter upper-case ISO currency code)
#       `stated` = the EMPLOYER's figure, `estimate` = a board's own estimate panel, `none` = the
#       listing showed no pay, `?` = not read (stored as ABSENT -- NOT CAPTURED -- never as none).
#   posted=YYYY-MM-DD (a date a board showed: stored `board-relative`, the weaker source) |
#          ats:YYYY-MM-DD (a JSON-LD `datePosted` or an ATS API date: stored `ats-posted`) |
#          <n>d (a shown age: the script stores run date - n as `board-relative`) | ?
#   setting="<the posting's own work-setting text, verbatim>" | none stated | ? (not read: absent)
# Pay intervals are the four postings in scope use. A non-annual interval is carried as written and
# the screen routes it to review; the agents must NEVER code an hourly, daily or monthly figure
# as /yr (R2): a guessed conversion that removes is the defect class this slot exists to end.
# dev #722 / public #156 (sourcing-scope, jobsearch 0.69.0, part a) -- A DEGRADED SWEEP IS
# QUARANTINED, NEVER CAPTURED AS A CLEAN SET. Three new REQUIRED slots, under the unchanged
# `ROLES v1` header (the 0.67.0 precedent: an optional slot would let a forgetful sweep produce
# silent clean-looking rows):
#   dropped=none | ? | <filter>[,<filter>...]   a filter the run ASKED for that the page did not apply
#   added=none   | ? | <filter>[,<filter>...]   a filter the page applied that the run did NOT ask for
#       <filter> := a member of QUERY_FILTERS (closed vocabulary). `none` = the sweep compared and
#       found no difference. `?` = it could not tell (a search-box route with no readable filter
#       state). `none` never combines with a token.
#   total=<m>+     a LOWER BOUND ("99+" badge): never an exact count. (Elasticsearch's `gte`.)
#   q=<k>[,<k>...] on a ROLE url line: the 1-based ordinals of the QUERY lines in this block (reached
#       AND unreachable, in block order, a faulted QUERY line keeps its ordinal) that showed the
#       role. A role is listed once even when several queries showed it, so q= lists EVERY query.
# On linkedin-jobsearch `dropped=date` is a line fault: the window is said with `unapplied`. On a
# board `unapplied` stays forbidden and `dropped=date` is how a board says it.
#
# ⭐ WHAT QUARANTINES (owner decision R3, 2026-10-16 -- Option A): ONLY a POSITIVELY REPORTED
# degradation. A reached query is DEGRADED when it reports `dropped=<filter>` (filter-dropped),
# `added=<filter>` (param-added), `unapplied` or a LinkedIn bucket that is not the run's
# (window-unapplied), or a truncated result set (truncated: an exact total above shown, or a lower
# bound `<m>+` with shown below m). `dropped=?` / `added=?` (filters-unread) and a reached query
# with `total=?` and a page (total-unknown) file the QUERY GAP ONLY and are COUNTED: they NEVER
# quarantine. A role is quarantined when EVERY query in its q= is degraded (or its QUERY line did
# not parse: `query-unparsed`); one clean query that showed it vouches for it.
#
# ⭐ SHAPE, NOT ENFORCED (R4). Everything above is the sweep's SELF-REPORT of what it observed:
# `dropped=`, `added=` and `total=` are read off a rendered page by a model, and nothing in this
# script can tell a filter the page dropped from a `none` the sweep wrote without looking. What the
# tests prove is that the instruction and the parser are there, not that an agent obeys it. The
# defence is COUNTED, not enforced: the `roles` event carries q_clean / q_unread / q_total_unknown /
# q_degraded, `run_summary.py` prints them, and `check_runs.py` flags 7 consecutive all-clean board
# passes (a sweep that never actually looks would produce exactly that). An acceptance replay of a
# real degraded board page is not possible in CI.
QUERY_FILTERS = ("worktype", "location", "date", "pay", "seniority", "jobtype", "other")
DEGRADED_CODES = ("filter-dropped", "param-added", "window-unapplied", "truncated",
                  "query-unparsed")                       # these QUARANTINE
UNREAD_CODES = ("filters-unread", "total-unknown")        # these file the query gap ONLY (R3)
KIND_UNQUARANTINE = "_unquarantine"
KIND_SIBLING = "_sibling"       # dev #728 / public #158 -- a sibling listing joined to a queued item
PAY_INTERVALS = {"yr": "year", "mo": "month", "day": "day", "hr": "hour"}
PAY_STATES = {"stated": "employer-stated", "estimate": "board-estimate"}
PAY_SOURCES = {"employer-stated": "listing-text", "board-estimate": "board-widget",
               "none-shown": "listing-text"}
SETTING_NONE_STATED = "none stated"
POSTED_MAX_AGE_DAYS = 3650      # an `<n>d` older than ten years is a typo, not a posting age

KIND_CAPTURE = "capture-role"
ROLES_FIELD_CAP = 200
# dev #707 / public #151 -- `--add-roles` and `--add-roles --check` answer with ONE of these:
#   0  clean            every line parsed; everything was recorded (or, with --check, would be)
#   4  accepted, with   the valid roles were recorded; each faulty line is a gap of its own and
#      line faults      the raw hand-back is kept (nothing valid is ever discarded for a bad line)
#   3  refused          a STRUCTURAL fault (no block, two blocks, a bad header, a run or surface
#                       that is not this call's, no END line): one gap, nothing else written
#   2  usage            a missing --run/--surface, or an unreadable hand-back file
ROLES_EXIT_OK, ROLES_EXIT_USAGE, ROLES_EXIT_REFUSED, ROLES_EXIT_FAULTS = 0, 2, 3, 4
ROLES_LINE_GAP_SCOPE = "jobsearch:roles-line:%s:%s"     # (surface, line number | block:<check>)
ROLES_HANDBACK_DIR = (".jobsearch", "handbacks")         # under the PROFILE root, never the engine

# A queue id is typed by hand into --claim, so four bytes (eight hex digits), not brief.py's
# eight (dev #680): 2**32 per second is far beyond any add rate this queue sees.
QUEUE_ID_ENTROPY_BYTES = 4


def load(path=None):
    """Every raw row of the queue (`path` defaults to this profile's `data/pending_actions.jsonl`).
    A line that is not JSON raises ValueError: callers that must not treat a broken queue as an empty
    one (`record.py`'s surface-cannot-read gate, dev #723) rely on that."""
    path = path or QUEUE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def replay(rows):
    """Append-only, same as the inbox: newest record per id wins.

    ⭐ CLAIMS ARE APPEND RECORDS TOO. In a distributed model two workers can read this file at
    once, so a claim must be an atomic append and never a rewrite — the same reasoning that made
    the findings queue append-only. Last claim wins, which is safe because a claim is a LEASE:
    it expires, so a worker that dies holding one cannot strand the task forever.

    ⭐ design-linkedin-runner-resilience.md §5.1 (public #47/#96) — `_withheld` is the same
    shape: a fact THIS run already knows (the pane is stalled or not signed in, so a
    `requires: chrome` item cannot actually be finished right now) goes into the queryable
    store, never only into a run's summary prose. It folds onto `withheld_because`, cleared the
    moment a `_claim` succeeds — a claim only ever succeeds past the withholding check in
    `main()` below, so reaching `_claim` at all means the state that justified it has moved on.
    """
    state = {}
    for r in rows:
        rid = r.get("id")
        if not rid:
            continue
        kind = r.get("kind")
        if kind == "_done" and rid in state:
            state[rid] = dict(state[rid], status="done", done_at=r.get("done_at"))
            if r.get("closed_as"):
                # dev #728: `linked:<row id>` -- the item became a listing of an existing row
                state[rid]["closed_as"] = r["closed_as"]
        elif kind == KIND_SIBLING and rid in state:
            # dev #728 / public #158 -- one requisition listed at several places is ONE item: a
            # sibling listing is an APPEND record (`{url, location}`) folded onto `siblings`, in
            # order, never a second item, and never twice for one URL.
            sibs = list(state[rid].get("siblings") or [])
            if r.get("url") and not any(s.get("url") == r["url"] for s in sibs):
                sibs.append({"url": r["url"], "location": r.get("location")})
            state[rid] = dict(state[rid], siblings=sibs)
        elif kind == "_claim" and rid in state:
            state[rid] = dict(state[rid], claimed_by=r.get("claimed_by"),
                              claimed_at=r.get("claimed_at"), withheld_because=None)
        elif kind == "_release" and rid in state:
            state[rid] = dict(state[rid], claimed_by=None, claimed_at=None)
        elif kind == "_withheld" and rid in state:
            state[rid] = dict(state[rid], withheld_because=r.get("because"))
        elif kind == KIND_UNQUARANTINE and rid in state:
            # dev #722 / public #156 -- a quarantine is released by NEW EVIDENCE (a clean
            # sighting) or by the owner, never by a claim: `_withheld` is a property of the
            # surface and a claim clears it; quarantine is a property of the evidence for one role.
            state[rid] = dict(state[rid], quarantine=None)
        elif kind not in ("_done", "_claim", "_release", "_withheld", KIND_UNQUARANTINE,
                          KIND_SIBLING):
            state[rid] = r
    return list(state.values())


# A claim is a LEASE, not a lock. A worker that dies mid-task must not strand the work.
CLAIM_LEASE_MINUTES = 45


def claim_is_live(rec, now):
    at = rec.get("claimed_at")
    if not rec.get("claimed_by") or not at:
        return False
    try:
        held = (now - datetime.datetime.fromisoformat(at)).total_seconds() / 60.0
    except Exception:
        return False
    return held < CLAIM_LEASE_MINUTES


# design-linkedin-runner-resilience.md §5.1 (public #47/#96, D-6) — the skip is DATA, never
# skill prose. `#96` is exactly the loop the old (withdrawn) draft left open: a stalled pane
# was keyed to THIS session's run_id and the rule lived in daily-run's prose, so the next
# scheduled session — a fresh run_id, a fresh reading of the skill — re-claimed the same
# still-stalled item. `pane_withhold_reason()` below reads ANY run_id's record: the fact that
# matters is the SURFACE's state, not who last observed it.

def _pane_lock_path():
    return os.environ.get("CLAUDESEARCH_PANE_LOCK_PATH") or \
        os.path.join(ROOT, ".git", "pane_lock.json")


def _pane_stale_minutes():
    """`linkedin.pane_stale_minutes` — the SAME registered key `runlock.py --resource pane`
    reads for the opposite question (should the lock be taken over). Here it answers "is this
    OBSERVATION still fresh enough to act on" — a `stalled_at`/`verdict_at` older than the
    window is assumed superseded by now, so it stops withholding rather than blocking forever."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config_keys as _ck
        try:
            with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            cfg = {}
        value, _ = _ck.describe(cfg, _ck.LINKEDIN_PANE_STALE_MINUTES)
        return value
    except Exception:
        return 90


def _minutes_since(iso_ts):
    if not iso_ts:
        return None
    try:
        t = datetime.datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return None
    return (datetime.datetime.now() - t).total_seconds() / 60.0


def pane_withhold_reason():
    """Why a `requires: chrome` item should be withheld right now, or None. Two conditions,
    either sufficient: a recent confirmed render-stall (`stalled_at`), or a recent
    not-signed-in preflight verdict (`last_verdict`/`verdict_at`) — both within
    `linkedin.pane_stale_minutes`, both written by `runlock.py --resource pane` (§1, §5.2).
    A missing or unreadable lock file withholds nothing: no evidence of a problem is not
    evidence of one."""
    p = _pane_lock_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    limit = _pane_stale_minutes()
    age = _minutes_since(rec.get("stalled_at"))
    if age is not None and age <= limit:
        return "pane-stalled %s %s" % (rec.get("run_id"), rec.get("stalled_at"))
    if rec.get("last_verdict") == "not-signed-in":
        age = _minutes_since(rec.get("verdict_at"))
        if age is not None and age <= limit:
            return "not-signed-in %s" % rec.get("verdict_at")
    return None


def _record_withheld(rid, reason, now):
    rec = {"id": rid, "kind": "_withheld", "because": reason,
          "at": now.isoformat(timespec="seconds")}
    with open(QUEUE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _append_unquarantine(rid, because, now=None):
    """dev #722 / public #156 -- release one quarantined `capture-role` item: an APPEND-ONLY record
    (`replay` folds it onto `quarantine = None`), never a rewrite. `because` is the new evidence,
    `clean sighting run=<id>` or `owner`. Not the `_withheld` shape's clearing rule: a claim never
    clears a quarantine (see `replay`)."""
    now = now or datetime.datetime.now()
    rec = {"id": rid, "kind": KIND_UNQUARANTINE, "because": because,
           "at": now.isoformat(timespec="seconds")}
    with open(QUEUE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _append_sibling(rid, url, location, now=None):
    """dev #728 / public #158 -- join one sibling listing (`url`, `location`) to the queued
    `capture-role` item `rid`: an APPEND-ONLY record that `replay` folds onto `siblings`, the shape
    `_append_unquarantine` has. `--add-roles` prints `SIBLING <url> (<location>) -> <item id>`."""
    now = now or datetime.datetime.now()
    rec = {"id": rid, "kind": KIND_SIBLING, "url": url, "location": location,
           "at": now.isoformat(timespec="seconds")}
    with open(QUEUE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def close_item(rid, closed_as, now=None):
    """dev #728 / public #158 -- close one queue item as `closed_as` (`linked:<opportunity id>`): the
    `_done` record every close is, plus WHY it closed, so a capture item that became a listing of an
    existing row is not mistaken for one that became a row of its own."""
    now = now or datetime.datetime.now()
    rec = {"id": rid, "kind": "_done", "done_at": now.isoformat(timespec="seconds"),
           "closed_as": closed_as}
    with open(QUEUE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_capture_item(item_id):
    """The replayed `capture-role` item `item_id` (any status), or None."""
    try:
        return next((r for r in replay(load()) if r.get("id") == item_id
                     and r.get("kind") == KIND_CAPTURE), None)
    except (OSError, ValueError):
        return None


class DeferredRefused(ValueError):
    """`--add` refused the text — it reads like a send (FORBIDDEN)."""


def queue_item(what, why="", requires=()):
    """The ONE append path for a new item — factored out of `main()`'s `--add` handling
    (Query or Citation C1, §5.2) so `brief.py --probe --held` can queue a probe's own `what`
    without shelling out to this script. Same FORBIDDEN refusal as the CLI; raises
    `DeferredRefused` rather than printing and returning an exit code, since a caller here is
    a script, not a terminal. Does NOT deduplicate on `what` itself — a caller that must not
    queue the same `what` twice (brief.py's own `queue_probe_if_needed`) checks
    `replay(load())` first, because "already pending" is a judgment about EXISTING rows the
    caller already has in hand, not something this append should silently re-derive."""
    m = FORBIDDEN.search(what)
    if m:
        raise DeferredRefused(
            "REFUSED — NOT QUEUED: %r reads like a send, and sends never queue (CLAUDE.md: no "
            "send without the candidate's explicit fresh approval). For engine work use a script "
            "form:\n  ~/.claude/jobsearch/run deferred.py --add-research <opp_id> | --add-draft "
            "<opp_id> | --add-linkedin-pass\nor describe the work without the send verb."
            % m.group(0))
    return _append_item(what, why, requires)


def _append_item(what, why="", requires=(), kind="action", ref=None, role=None,
                 quarantine=None, queued_run=None, channel_id=None, source=None):
    """dev #692 / public #140 (N2) -- the ONE private writer of a new queue row, and the only
    place a row reaches the queue WITHOUT passing `FORBIDDEN`. Its callers are pinned by
    `test_send_filter.py` (a source scan): `queue_item` (which checks the filter first),
    `queue_linkedin_pass`, `queue_research`, `queue_draft` and `add_roles`, and a sixth fails the
    build. Every one but the first builds `what` from a fixed template over data fields.

    `kind` is `action` for free text and the engine form's own kind otherwise; `ref` (optional,
    omitted from the row when None, so legacy rows are unchanged) is the canonical URL or opp id
    the item stands for, which is what makes the engine forms idempotent on `(kind, ref)`.

    `role` (dev #715 / public #143, dev #716 / public #142; only a `capture-role` item passes one)
    is the SCRIPT-parsed pay, posting date and work setting of the ROLE line (`role_payload`),
    omitted when None, so every legacy row and every other kind is unchanged.

    `quarantine` (dev #722 / public #156; only a `capture-role` item from a degraded sweep passes
    one) is `{run_id, because: [code...], queries: [k...]}`; `queued_run` (dev #723; only a
    `read-jd` item passes one) is the run that queued it, so that run is never served the item it
    could not finish. Both are omitted when None.

    `channel_id` and `source` (dev #751, B7; only a FEED `capture-role` item passes them) are the
    linked company-site channel the posting came from and `feed:<vendor>`. `record.py create
    --from-item` copies the channel into `sightings[0]` and refuses a different one the model
    supplies, so a feed role's channel is a recorded fact, not a thing a model typed. Omitted when
    None, so every other item is unchanged."""
    now = datetime.datetime.now()
    # dev #481 / public #112 -- the timestamp prefix keeps ids sortable; the random suffix is what
    # stops two adds inside one second (two controllers, or a runner and daily-run in the same
    # failed pass) from minting the SAME id, which replay() would fold into one row.
    rid = "act-%s-%s" % (now.strftime("%Y%m%dT%H%M%S"),
                         secrets.token_hex(QUEUE_ID_ENTROPY_BYTES))
    reqs = [r.strip() for r in requires if r and r.strip()] if requires else []
    rec = {"id": rid, "kind": kind, "what": what, "why": why, "requires": reqs,
          "queued_at": now.isoformat(timespec="seconds"), "status": "pending",
          "claimed_by": None, "claimed_at": None, "done_at": None}
    if ref is not None:
        rec["ref"] = ref
    if role is not None:
        rec["role"] = role
    if quarantine is not None:
        rec["quarantine"] = quarantine
    if queued_run is not None:
        rec["queued_run"] = queued_run
    if channel_id is not None:
        rec["channel_id"] = channel_id
    if source is not None:
        rec["source"] = source
    with open(QUEUE, "a", encoding="utf-8") as fh:          # append-only, like the inbox
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _pending_by_key(kind, key, rows=None, exclude_ref=None):
    """The replayed pending row of `kind` whose `role.role_key` is `key` -- the same requisition
    (company + title) as a role being resolved, under a different URL (dev #728 / public #158)."""
    rows = replay(load()) if rows is None else rows
    for r in rows:
        if (r.get("kind") == kind and r.get("status") == "pending" and r.get("ref") != exclude_ref
                and isinstance(r.get("role"), dict) and r["role"].get("role_key") == key):
            return r
    return None


def _link_listing(row_id, sighting, already_locked=False):
    """Add one sibling listing to an EXISTING row through `record.py append <id> sightings` (the one
    writer of `opportunities.jsonl`: the lock, the validator and the rollback all apply; this script
    never opens the store for writing). A subprocess on this interpreter. Returns None, or why not."""
    import subprocess
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.py"),
           "append", str(row_id), "sightings", json.dumps(sighting)]
    if already_locked:
        cmd.append("--already-locked")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return "record.py exit %d: %s" % (r.returncode, " ".join((r.stdout + r.stderr).split())[-300:])
    return None


def _pending_by_ref(kind, ref, rows=None):
    """The replayed pending row of `kind` standing for `ref`, or None -- the idempotency test the
    engine forms share (the `--add-linkedin-pass` precedent, keyed on `(kind, ref)`)."""
    rows = replay(load()) if rows is None else rows
    for r in rows:
        if r.get("kind") == kind and r.get("ref") == ref and r.get("status") == "pending":
            return r
    return None


def _opportunity_exists(opp_id):
    path = os.path.join(ROOT, "data", "opportunities.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            return any(json.loads(l).get("id") == opp_id for l in fh if l.strip())
    except (OSError, ValueError):
        return False


def _checked_opp_id(opp_id):
    if not OPP_ID_RE.match(str(opp_id or "")):
        raise DeferredRefused("REFUSED — %r is not an opportunity id (letters, digits, '.', '_' "
                              "and '-' only); nothing queued." % (opp_id,))
    if not _opportunity_exists(opp_id):
        raise DeferredRefused("REFUSED — no opportunity %r in data/opportunities.jsonl; nothing "
                              "queued." % (opp_id,))
    return opp_id


def queue_research(opp_id, rows=None):
    """dev #692 / public #140 (692-1b) -- queue the research a posture (or max_agents_per_run)
    held, as a script form: `kind` research-role, `ref` the opp id, `requires: [research]`, so it
    drains on the first run whose posture permits research. Idempotent on `(kind, ref)` among
    pending rows. Returns `(row, added)`; raises `DeferredRefused` for an id that is not a real
    opportunity. Engine-built: skips `FORBIDDEN` by construction (the template cannot say send)."""
    _checked_opp_id(opp_id)
    hit = _pending_by_ref(KIND_RESEARCH, opp_id, rows)
    if hit:
        return hit, False
    return _append_item(RESEARCH_WHAT % opp_id, RESEARCH_WHY, RESEARCH_REQUIRES,
                        kind=KIND_RESEARCH, ref=opp_id), True


def queue_draft(opp_id, rows=None):
    """dev #692 / public #140 -- the draft twin of `queue_research`: kind draft-message,
    `requires: [drafting]`. The item asks for a DRAFT; the template says it is never sent."""
    _checked_opp_id(opp_id)
    hit = _pending_by_ref(KIND_DRAFT, opp_id, rows)
    if hit:
        return hit, False
    return _append_item(DRAFT_WHAT % opp_id, DRAFT_WHY, DRAFT_REQUIRES,
                        kind=KIND_DRAFT, ref=opp_id), True


def _opportunity_row(opp_id):
    path = os.path.join(ROOT, "data", "opportunities.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    if row.get("id") == opp_id:
                        return row
    except (OSError, ValueError):
        return None
    return None


def queue_jd_read(opp_id, run_id=None, rows=None):
    """dev #723 -- queue the JD read a surface could not do, as a script form: kind `read-jd`, `ref`
    the opportunity id, `requires: [chrome]`. Returns `(row, added)`; raises `DeferredRefused` for an
    id that is not a real opportunity.

      * a role that no longer lists `jd-read` in `your_move.triage_missing` has been read (or a read
        was tried and failed): nothing is queued and `(None, False)` comes back;
      * idempotent on `(kind, ref)` among pending rows (`_pending_by_ref`): a second call is a no-op;
      * `run_id` is stored as `queued_run`, so `--claimable --run <id>` never serves the item to the
        run that could not read it (the same-run guard, design finding F3).

    Engine-built: skips `FORBIDDEN` by construction. A sibling of `queue_research`, not an extension
    of it: that one is a posture-gated model step, this one a machine-gated browser step."""
    _checked_opp_id(opp_id)
    import your_move as _ym
    opp = _opportunity_row(opp_id)
    if opp is not None and "jd-read" not in _ym.triage_missing(opp):
        return None, False
    hit = _pending_by_ref(KIND_JD_READ, opp_id, rows)
    if hit:
        return hit, False
    return _append_item(JD_READ_WHAT % opp_id, JD_READ_WHY, JD_READ_REQUIRES, kind=KIND_JD_READ,
                        ref=opp_id, queued_run=run_id), True


def jd_read_waited_past_bound(item, stuck_days, now=None):
    """True when a `read-jd` item has waited MORE THAN `stuck_days` days (dev #723, SS-C3): the one
    definition of 'the bound has passed', used by `settle` to write `surface-cannot-read` and by
    `record.py`'s gate to refuse writing it earlier, so the two can never disagree. An item whose
    `queued_at` cannot be read has waited for no known time: False, never a guess."""
    at = item.get("queued_at")
    try:
        queued = datetime.datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return False
    waited = ((now or datetime.datetime.now()) - queued).total_seconds() / 86400.0
    return waited > stuck_days


def _record_refusal_gap(run_id, what):
    """dev #692 / public #140 -- a refused free-text add that belongs to a run leaves a gap
    (scope `deferred:refused`) so the refusal shows in the run summary instead of vanishing with
    the transcript. Best-effort and loud: a journal that cannot be written must not hide the
    refusal itself, which the caller prints either way."""
    import journal as _journal
    try:
        _journal.record_gap(
            ROOT, run_id, "deferred:refused", "other",
            closes_when="re-queued in a script form or reworded: %s" % str(what)[:60].replace("\n", " "))
    except _journal.JournalError as e:
        print("⚠️ could not journal the refusal (%s)" % e, file=sys.stderr)


def queue_linkedin_pass(rows=None):
    """dev #481 / public #112 -- the ONE way a LinkedIn pass is queued. A pending row carrying
    `LINKEDIN_PASS_WHAT` already stands for every failed pass since, so adding while one is
    pending writes NO row. Returns `(row, added)`.

    "Pending" is the replayed `status == "pending"`, claimed or not, and there is no time window:
    a pass stays owed until it is done, so the next one must be queueable the moment this one is.
    NOT atomic across processes (a read, then an append): two controllers adding at once can each
    write one row; the next complete pass closes both (`close_linkedin_passes`)."""
    rows = replay(load()) if rows is None else rows
    for r in rows:
        if r.get("what") == LINKEDIN_PASS_WHAT and r.get("status") == "pending":
            return r, False
    return _append_item(LINKEDIN_PASS_WHAT, LINKEDIN_PASS_WHY, LINKEDIN_PASS_REQUIRES), True


def pending_linkedin_passes(rows=None):
    """Every replayed pending row carrying `LINKEDIN_PASS_WHAT`, oldest queued first."""
    rows = replay(load()) if rows is None else rows
    return sorted((r for r in rows if r.get("what") == LINKEDIN_PASS_WHAT
                   and r.get("status") == "pending"),
                  key=lambda r: r.get("queued_at") or "")


def close_linkedin_passes(rows=None, now=None):
    """dev #481 / public #112 -- append one `_done` per pending pass row and return their ids.
    Called by `linkedin_sweep.py record` once it has recorded a pass that REACHED a list surface,
    so legacy duplicates already on an install close together, append-only, with no user action.
    `--done <id>` checks nothing (it appends for any id), so this iterates the replayed pending
    rows rather than trusting an id list a caller hands in."""
    now = now or datetime.datetime.now()
    closed = []
    for r in pending_linkedin_passes(rows):
        with open(QUEUE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": r["id"], "kind": "_done",
                                 "done_at": now.isoformat(timespec="seconds")}) + "\n")
        closed.append(r["id"])
    return closed


def capabilities():
    """Ask whoami.py, never assume. A worker that guesses its own capability is the bug."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import whoami
        return whoami.probe(), whoami.worker_id(whoami.probe())
    except Exception:
        return {}, "unknown"


# ---------------------------------------------------------------------------------------------
# dev #692 / public #140 (692-2, N5, N6) -- every role a pass sees is accounted for, per role
# ---------------------------------------------------------------------------------------------

_Q = r'"(?P<title>[^"]*)"'
_ROLES_BEGIN = re.compile(r"^--- ROLES v1 run=(?P<run>\S+) surface=(?P<surface>\S+) "
                          r"window=(?P<window>\S+) ---$")
_ROLES_END = "--- END ROLES ---"
# dev #722 / public #156 -- `total=`, `dropped=` and `added=` are matched LOOSELY here and judged in
# `parse_roles`, so a missing slot or a token outside the vocabulary is a fault whose rule NAMES it,
# not the generic "not a line of the ROLES grammar".
_QUERY_REACHED = re.compile(
    r"^QUERY geo=(?P<geo>remote|local) title=" + _Q + r" window=(?P<win>r86400|r604800|none) "
    r"shown=(?P<shown>\d+) total=(?P<total>\S+)(?: dropped=(?P<dropped>\S+))?"
    r"(?: added=(?P<added>\S+))?(?P<unapplied> unapplied)?"
    r"(?: channel=(?P<channel>\S+))?$")
_QUERY_UNREACHABLE = re.compile(
    r"^QUERY geo=(?P<geo>remote|local) title=" + _Q + r" unreachable reason=(?P<reason>[a-z-]+)"
    r"(?: channel=(?P<channel>\S+))?$")
_SEEN_DISTINCT = re.compile(r"^SEEN distinct=(?P<n>\d+)$")
# The ROLE line's `pay=` and `setting=` are matched OPTIONALLY here so that a line without them is a
# line fault with a rule that NAMES the missing slot (see `_role_slot_faults`), not the generic
# "not a line of the ROLES grammar". The slots are required: the fault is raised, never defaulted.
_ROLE_URL = re.compile(
    r'^ROLE url=(?P<url>\S+)(?: q=(?P<q>\S+))? title="(?P<title>[^"]*)" company="(?P<company>[^"]*)" '
    r'location="(?P<location>[^"]*)" posted=(?P<posted>\S+)'
    r'(?: pay=(?P<pay>\S+))?(?: setting="(?P<setting>[^"]*)")?$')
_PAY_RANGE = re.compile(
    r'^(?P<min>\d+)(?:-(?P<max>\d+)|(?P<open>\+))/(?P<unit>[a-z]+)/(?P<cur>[A-Za-z]{3})$')
_POSTED_AGE = re.compile(r'^(?P<n>\d{1,4})d$')
_ROLE_NOURL = re.compile(
    r'^ROLE nourl title="(?P<title>[^"]*)" company="(?P<company>[^"]*)" '
    r'reason=(?P<reason>[a-z-]+)$')


class RolesRefused(ValueError):
    """The ROLES block cannot be accepted. Nothing but one gap is written."""


def _clip(s):
    """A scraped field is DATA: newlines stripped, capped, before it goes into any template."""
    return " ".join(str(s or "").split())[:ROLES_FIELD_CAP]


def parse_pay_slot(slot):
    """`(listed_pay, None)` or `(None, why)` for the `pay=` slot of a ROLE line (dev #715 / public
    #143). `listed_pay` is `None` for `?` (not read: the stored field is ABSENT, which means NOT
    CAPTURED -- never `none`), else `{"state", "ranges"?, "source"}` WITHOUT `captured_on` (the run
    date is known only to `add_roles`). The stored states are the three `validate_data` checks:
    `employer-stated` (`stated:`), `board-estimate` (`estimate:`), `none-shown` (`none`).

    Every refusal names the rule: a pay that fits no form is never guessed at, and a figure is
    never converted (an hourly range stays `interval: hour`; the screen sends it to review)."""
    if slot == "?":
        return None, None
    if slot == "none":
        return {"state": "none-shown", "source": PAY_SOURCES["none-shown"]}, None
    word, sep, body = slot.partition(":")
    if not sep or word not in PAY_STATES:
        return None, ("pay=%s is not `none`, `?`, `stated:<range>[;<range>...]` or "
                      "`estimate:<range>[;<range>...]`" % slot)
    ranges = []
    for piece in body.split(";"):
        rm = _PAY_RANGE.match(piece)
        if not rm:
            return None, ("pay range %r is not `<min>-<max>/<yr|mo|day|hr>/<CUR>` or "
                          "`<min>+/<yr|mo|day|hr>/<CUR>` (whole numbers, no separators)" % piece)
        unit = rm.group("unit")
        if unit not in PAY_INTERVALS:
            return None, ("pay range %r has interval %r: use yr, mo, day or hr, and never code a "
                          "non-annual figure as /yr" % (piece, unit))
        lo = int(rm.group("min"))
        hi = None if rm.group("open") else int(rm.group("max"))
        if lo <= 0 or (hi is not None and hi <= 0):
            return None, "pay range %r has a figure that is not a positive whole number" % piece
        if hi is not None and lo > hi:
            return None, "pay range %r has min above max" % piece
        ranges.append({"min": lo, "max": hi, "currency": rm.group("cur").upper(),
                       "interval": PAY_INTERVALS[unit], "label": None})
    state = PAY_STATES[word]
    return {"state": state, "ranges": ranges, "source": PAY_SOURCES[state]}, None


def parse_posted_slot(slot):
    """`(kind, value, None)` or `(None, None, why)` for the `posted=` slot: kind `unknown` (`?`),
    `board-relative` (a bare `YYYY-MM-DD`), `ats-posted` (`ats:YYYY-MM-DD`) or `age` (`<n>d`, a
    shown age the script turns into a date against the run date). A date must be a real calendar
    date. `ats:` is for a JSON-LD `datePosted` or an ATS API date only (the agent prose says so);
    the script cannot tell, which is why it is the agent's prefix to earn."""
    if slot == "?":
        return "unknown", None, None
    m = _POSTED_AGE.match(slot)
    if m:
        n = int(m.group("n"))
        if n > POSTED_MAX_AGE_DAYS:
            return None, None, "posted=%s is a shown age above %d days" % (slot, POSTED_MAX_AGE_DAYS)
        return "age", n, None
    kind, date_text = "board-relative", slot
    if slot.startswith("ats:"):
        kind, date_text = "ats-posted", slot[4:]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_text):
        return None, None, "posted=%s is not YYYY-MM-DD, ats:YYYY-MM-DD, <n>d or ?" % slot
    try:
        datetime.date.fromisoformat(date_text)
    except ValueError:
        return None, None, "posted=%s is not a real calendar date" % slot
    return kind, date_text, None


def parse_q_slot(slot):
    """`(ordinals, None)` or `(None, why)` for a ROLE line's `q=<k>[,<k>...]` (dev #722 / public
    #156): positive whole numbers, each at most once. Whether an ordinal EXISTS, and whether it
    names an unreachable query, is judged against the block's QUERY lines in `parse_roles`."""
    ks = []
    for piece in slot.split(","):
        if not re.match(r"^[1-9]\d{0,3}$", piece):
            return None, ("q=%s is not a comma-separated list of 1-based QUERY line ordinals "
                          "(%r is not one)" % (slot, piece))
        k = int(piece)
        if k in ks:
            return None, "q=%s repeats ordinal %d: list each QUERY once" % (slot, k)
        ks.append(k)
    return ks, None


def parse_filter_slot(name, slot):
    """`(filters, unread, None)` or `(None, None, why)` for a QUERY's `dropped=` / `added=`
    (dev #722 / public #156). `filters` is the list of named `QUERY_FILTERS` tokens (empty for
    `none` and for `?`), `unread` is True for `?`. `none` and `?` stand alone; a token outside the
    closed vocabulary, a repeat, or an empty member is refused with the vocabulary named."""
    if slot is None:
        return None, None, ("a reached QUERY carries the required `dropped=` and `added=` slots "
                            "(none|?|<filter>[,<filter>...] from %s); this line has no `%s=`"
                            % ("/".join(QUERY_FILTERS), name))
    if slot == "none":
        return [], False, None
    if slot == "?":
        return [], True, None
    seen = []
    for piece in slot.split(","):
        if piece in ("none", "?"):
            return None, None, ("%s=%s combines `%s` with a filter: `none` and `?` stand alone"
                                % (name, slot, piece))
        if piece not in QUERY_FILTERS:
            return None, None, ("%s=%s: %r is not one of %s" % (name, slot, piece,
                                                                 ", ".join(QUERY_FILTERS)))
        if piece in seen:
            return None, None, "%s=%s names %s twice" % (name, slot, piece)
        seen.append(piece)
    return seen, False, None


def parse_total_slot(slot):
    """`(total, lower_bound, None)` or `(None, None, why)` for a QUERY's `total=` (dev #722 /
    public #156): `<m>` exact, `<m>+` a LOWER BOUND (a "99+" badge), `?` unknown (`total` None)."""
    if slot == "?":
        return None, False, None
    m = re.match(r"^(\d+)(\+?)$", slot)
    if not m:
        return None, None, "total=%s is not <m>, <m>+ (a lower bound) or ?" % slot
    return int(m.group(1)), bool(m.group(2)), None


def query_degradation(q):
    """`(degraded, unread)` -- two sorted code lists for a REACHED query (dev #722 / public #156,
    R3). `degraded` (DEGRADED_CODES) QUARANTINES the roles only this query showed; `unread`
    (UNREAD_CODES) files the query gap and is COUNTED, never quarantines.

    SHAPE, not enforced (R4): the inputs are the sweep's own report of what the page showed."""
    degraded, unread = [], []
    if q["window_gap"]:
        degraded.append("window-unapplied")
    if q["dropped"]:
        degraded.append("filter-dropped")
    if q["added"]:
        degraded.append("param-added")
    if q["truncated"]:
        degraded.append("truncated")
    if q["dropped_unread"] or q["added_unread"]:
        unread.append("filters-unread")
    if q["total"] is None and q["shown"] > 0:
        unread.append("total-unknown")
    return sorted(degraded), sorted(unread)


def _role_slots(rm):
    """`(slots, None)` or `(None, why)` for a ROLE url line that matched `_ROLE_URL`: `slots` is
    the parsed `pay`, `posted`, `setting` and the three verbatim, or `why` names the first rule
    broken. The two new slots are REQUIRED (dev #715 / public #143): a line without them is a line
    fault, never a role with the slot defaulted."""
    if rm.group("q") is None:
        return None, ("a ROLE url line carries the required `q=<k>[,<k>...]` slot naming the QUERY "
                      "line(s) that showed it (1-based, in block order); this line has no `q=`")
    qs, why = parse_q_slot(rm.group("q"))
    if why:
        return None, why
    missing = [n for n in ("pay", "setting") if rm.group(n) is None]
    if missing:
        return None, ("a ROLE line carries the required `pay=` and `setting=` slots "
                      "(pay=none|stated:<range>|estimate:<range>|? and "
                      "setting=\"<verbatim|none stated|?>\"); this line has no %s"
                      % " or ".join("`%s=`" % n for n in missing))
    pay, why = parse_pay_slot(rm.group("pay"))
    if why:
        return None, why
    kind, value, why = parse_posted_slot(rm.group("posted"))
    if why:
        return None, why
    setting = _clip(rm.group("setting"))
    if not setting:
        return None, ("setting=\"\" is empty: write the posting's own text, `none stated` when it "
                      "states none, or `?` when you did not read it")
    return {"pay": pay, "posted": (kind, value), "setting": setting, "q": qs,
            "slots": {"pay": rm.group("pay"), "posted": rm.group("posted"),
                      "setting": rm.group("setting")}}, None


def role_payload(r, run_date):
    """The `role` object a `capture-role` queue item carries (dev #715 / public #143, dev #716 /
    public #142, design §2): what `--add-roles` STORES of a ROLE line's three new slots, in the
    shapes the opportunity will hold, so `record.py` copies them and no model re-types a value the
    script already parsed.

      listed_pay         the `opportunities.listed_pay` object (state, ranges, source, captured_on),
                         or None when `pay=?` (not read: the opportunity field is left ABSENT)
      posted             the `opportunities.posted` object (date, source, recorded_on), or None for
                         `posted=?` (age unknown = absent). `<n>d` is `run date - n`, computed here
                         and never by the model
      location_declared  the `location.declared` text: the posting's own words, the literal
                         `none stated`, or None for `setting="?"` (not read)
      role_key           the normalized company + title (`_role_key`): what a sibling listing of the
                         same requisition is matched on (dev #728 / public #158)
      location_listed    the ROLE line's `location=` text, verbatim (dev #727 / public #159), or
                         None for `location="?"`. `record.py create --from-item` copies it to
                         `location.primary` and reads the onsite inference off it
      slots              the three slots verbatim, for the audit trail
    """
    lp = dict(r["pay"], captured_on=run_date) if r.get("pay") else None
    posted = None
    kind, value = r.get("posted_parsed") or ("unknown", None)
    if kind == "age":
        d = datetime.date.fromisoformat(run_date) - datetime.timedelta(days=value)
        posted = {"date": d.isoformat(), "source": "board-relative", "recorded_on": run_date}
    elif kind in ("board-relative", "ats-posted"):
        posted = {"date": value, "source": kind, "recorded_on": run_date}
    setting = r.get("setting")
    listed = _clip(r.get("location"))
    return {"listed_pay": lp, "posted": posted,
            "location_declared": None if setting in (None, "?") else setting,
            "location_listed": None if listed in ("", "?") else listed,
            "role_key": _role_key(_clip(r.get("company")), _clip(r.get("title"))),
            "slots": r.get("slots") or {}}


def parse_roles(text, run_id, surface):
    """`{"header", "queries", "distinct", "listed", "roles", "faults"}` from the one `ROLES v1`
    block in `text`. Prose outside the block is ignored -- the block is the contract.

    ⭐ TWO KINDS OF FAULT (dev #707 / public #151). A STRUCTURAL fault -- no block, two blocks, a
    bad header, a run or surface that is not this call's, no END line -- raises `RolesRefused`
    naming the first problem: without a valid header and END nothing says which lines belong to
    the block. Every other fault is a LINE fault and is RETURNED in `faults`, never raised: a line
    that fits no form, a QUERY or ROLE that breaks a per-line rule, a second posting of the same
    URL, and the block-level count checks (SEEN against the ROLE lines, SEEN against the largest
    QUERY shown, a missing SEEN or QUERY) evaluated over the lines that parsed. One stray line
    used to refuse a pass's whole block and lose every valid role in it; now each valid ROLE is
    kept and each fault is reported on its own. A fault is `{"line": n | None, "text": the line |
    None, "scope_key": str, "rule": why}`; `line` is `None` for a block-level count check.
    `distinct` is the number the block's SEEN line stated (`None` when it has none); `listed` is
    how many ROLE lines were accepted, the number the roles event records."""
    import journal as _journal
    from pipeline_index import canonical_job_url
    lines = text.splitlines()
    begins = [i for i, ln in enumerate(lines) if ln.startswith("--- ROLES")]
    if not begins:
        raise RolesRefused("no `--- ROLES v1 run=%s surface=%s ... ---` block in the hand-back "
                           "(a pass that returned owes one)" % (run_id, surface))
    if len(begins) > 1:
        raise RolesRefused("more than one ROLES block in the hand-back (lines %s)"
                           % ", ".join(str(i + 1) for i in begins))
    m = _ROLES_BEGIN.match(lines[begins[0]].strip())
    if not m:
        raise RolesRefused("line %d: %r is not a `--- ROLES v1 run=<id> surface=<s> window=<w> "
                           "---` header" % (begins[0] + 1, lines[begins[0]]))
    if m.group("run") != run_id:
        raise RolesRefused("the block says run=%s but this call is for --run %s"
                           % (m.group("run"), run_id))
    if m.group("surface") != surface:
        raise RolesRefused("the block says surface=%s but this call is for --surface %s"
                           % (m.group("surface"), surface))
    if surface not in _journal.ROLES_SURFACES:
        raise RolesRefused("surface %r is not one of %s" % (surface, ", ".join(_journal.ROLES_SURFACES)))
    window = m.group("window")
    if surface == "board" and window != "none":
        raise RolesRefused("a board block's window is `none` (board-sweeper has no uniform "
                           "posted window), got window=%s" % window)
    if surface == "linkedin-jobsearch" and window not in ("daily", "wide"):
        raise RolesRefused("a LinkedIn block's window is `daily` or `wide`, got window=%s" % window)
    try:
        end = next(i for i in range(begins[0] + 1, len(lines)) if lines[i].strip() == _ROLES_END)
    except StopIteration:
        raise RolesRefused("the ROLES block has no `%s` line" % _ROLES_END)

    faults = []

    def fault(n, raw, rule):
        faults.append({"line": n, "text": _clip(raw), "scope_key": str(n), "rule": rule})

    def block_fault(key, rule):
        faults.append({"line": None, "text": None, "scope_key": "block:" + key, "rule": rule})

    expected_bucket = _journal.F_TPR_WIDE if window == "wide" else _journal.F_TPR_DAILY
    queries, roles, distinct, role_lines = [], [], None, 0
    qord, ordinals = 0, {}      # dev #722 / public #156: a ROLE's q= counts EVERY QUERY line
    for i in range(begins[0] + 1, end):
        raw = lines[i].strip()
        if not raw:
            continue
        n = i + 1
        if raw.startswith("QUERY"):
            qord += 1           # a faulted QUERY line keeps its ordinal, so its roles can be held
        qm = _QUERY_REACHED.match(raw)
        if qm:
            total, lower, why = parse_total_slot(qm.group("total"))
            if why:
                fault(n, raw, why)
                continue
            dropped, dropped_unread, why = parse_filter_slot("dropped", qm.group("dropped"))
            if why:
                fault(n, raw, why)
                continue
            added, added_unread, why = parse_filter_slot("added", qm.group("added"))
            if why:
                fault(n, raw, why)
                continue
            shown = int(qm.group("shown"))
            if total is not None and not lower and shown > total:
                fault(n, raw, "shown=%d exceeds total=%d" % (shown, total))
                continue
            q = {"geo": qm.group("geo"), "title": qm.group("title"), "status": "reached",
                 "window": qm.group("win"), "shown": shown, "total": total,
                 "total_lower_bound": lower, "dropped": dropped, "added": added,
                 "dropped_unread": dropped_unread, "added_unread": added_unread,
                 "unapplied": bool(qm.group("unapplied")), "channel": qm.group("channel"),
                 "ordinal": qord}
            if surface == "linkedin-jobsearch" and "date" in dropped:
                fault(n, raw, "on linkedin-jobsearch a window the page did not apply is "
                              "`unapplied`, not dropped=date (one spelling per fact)")
                continue
            if surface == "board":
                if q["window"] != "none" or not q["channel"] or q["unapplied"]:
                    fault(n, raw, "a board QUERY has window=none, a channel= and no `unapplied`")
                    continue
            else:
                if q["channel"]:
                    fault(n, raw, "a LinkedIn QUERY has no channel=")
                    continue
                if q["window"] == "none":
                    fault(n, raw, "a LinkedIn QUERY needs a bucket window (r86400 or r604800), "
                                  "got none")
                    continue
            q["window_gap"] = q["unapplied"] or (surface == "linkedin-jobsearch"
                                                 and q["window"] != expected_bucket)
            # truncated: an exact total above shown, or a LOWER BOUND the sweep did not reach
            q["truncated"] = (total is not None and
                              (shown < total if lower else total > shown))
            q["degraded"], q["unread"] = query_degradation(q)
            queries.append(q)
            ordinals[qord] = q
            continue
        qm = _QUERY_UNREACHABLE.match(raw)
        if qm:
            if qm.group("reason") not in _journal.REASONS:
                fault(n, raw, "reason=%s is not a journal.REASONS code" % qm.group("reason"))
                continue
            if surface == "board" and not qm.group("channel"):
                fault(n, raw, "a board QUERY carries a channel=")
                continue
            if surface == "linkedin-jobsearch" and qm.group("channel"):
                fault(n, raw, "a LinkedIn QUERY has no channel=")
                continue
            q = {"geo": qm.group("geo"), "title": qm.group("title"),
                 "status": "unreachable", "reason": qm.group("reason"),
                 "channel": qm.group("channel"), "window_gap": True,
                 "truncated": False, "degraded": [], "unread": [], "ordinal": qord}
            queries.append(q)
            ordinals[qord] = q
            continue
        qm = _SEEN_DISTINCT.match(raw)
        if qm:
            if distinct is not None:
                fault(n, raw, "a second `SEEN distinct=` line (the first one counts)")
                continue
            distinct = int(qm.group("n"))
            continue
        rm = _ROLE_URL.match(raw)
        if rm:
            role_lines += 1
            slots, why = _role_slots(rm)
            if why:
                fault(n, raw, why)
                continue
            roles.append({"url": rm.group("url"), "title": rm.group("title"),
                          "company": rm.group("company"), "location": rm.group("location"),
                          "posted": rm.group("posted"), "line": n,
                          "pay": slots["pay"], "posted_parsed": slots["posted"],
                          "setting": slots["setting"], "slots": slots["slots"],
                          "q": slots["q"]})
            continue
        rm = _ROLE_NOURL.match(raw)
        if rm:
            role_lines += 1
            if rm.group("reason") not in _journal.REASONS:
                fault(n, raw, "reason=%s is not a journal.REASONS code" % rm.group("reason"))
                continue
            roles.append({"url": None, "title": rm.group("title"), "company": rm.group("company"),
                          "location": "?", "posted": "?", "reason": rm.group("reason"), "line": n})
            continue
        if raw.startswith("ROLE"):
            role_lines += 1              # the agent meant a ROLE here: SEEN counted it, so do we
        fault(n, raw, "not a line of the ROLES grammar")

    # dev #722 / public #156 -- each ROLE url line's q= is judged against the block's QUERY lines
    # now that all of them have been seen: an ordinal out of range or naming an UNREACHABLE query
    # (it showed no roles) is a line fault for that ROLE; one naming a QUERY line that did not
    # parse is allowed and counts as DEGRADED (`query-unparsed`), so a broken line can never make
    # its roles look clean. A role is QUARANTINED when EVERY query that showed it is degraded.
    vetted = []
    for r in roles:
        if r["url"] is None:
            vetted.append(r)
            continue
        bad = None
        for k in r["q"]:
            if k > qord:
                bad = "q=%d is out of range: the block has %d QUERY line(s)" % (k, qord)
            elif k in ordinals and ordinals[k]["status"] == "unreachable":
                bad = "q=%d names an unreachable QUERY, which showed no roles" % k
            if bad:
                break
        if bad:
            fault(r["line"], lines[r["line"] - 1], bad)
            continue
        codes, all_degraded = set(), True
        for k in r["q"]:
            q = ordinals.get(k)
            if q is None:
                codes.add("query-unparsed")
            elif q["degraded"]:
                codes.update(q["degraded"])
            else:
                all_degraded = False
        r["quarantine_codes"] = sorted(codes) if all_degraded else None
        vetted.append(r)
    roles = vetted

    canon_seen, kept = {}, []
    for r in roles:
        c = canonical_job_url(r["url"]) if r["url"] else None
        r["canonical"] = c
        if c and c in canon_seen:
            fault(r["line"], lines[r["line"] - 1], "the same posting as line %d (%s): list a role "
                  "once" % (canon_seen[c], c))
            continue
        if c:
            canon_seen[c] = r["line"]
        kept.append(r)
    faults.sort(key=lambda f: f["line"])
    # block-level count checks, over the lines that PARSED: a fault, never a refusal
    if distinct is None:
        block_fault("seen", "the block has no `SEEN distinct=<n>` line")
    elif distinct != role_lines:
        block_fault("seen-vs-roles", "SEEN distinct=%d but the block lists %d ROLE line(s): seen "
                    "must equal accounted, in both directions" % (distinct, role_lines))
    if not queries:
        block_fault("query", "the block has no QUERY line that parsed: a pass that searched "
                    "reports what it searched (a query it could not run is an `unreachable` QUERY)")
    shown_max = max([q["shown"] for q in queries if q["status"] == "reached"] or [0])
    if distinct is not None and distinct < shown_max:
        block_fault("seen-vs-shown", "SEEN distinct=%d is below the largest QUERY shown=%d: a "
                    "query cannot show more roles than the pass saw" % (distinct, shown_max))
    return {"header": {"window": window, "surface": surface}, "queries": queries,
            "distinct": distinct, "listed": len(kept), "roles": kept, "faults": faults}


def _role_key(company, title):
    import hashlib
    from pipeline_index import normalize_company, normalize_title
    raw = "%s|%s" % (normalize_company(company), normalize_title(title))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _load_store(name):
    path = os.path.join(ROOT, "data", name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _earliest_seen(opp):
    dates = [str(s.get("seen_on"))[:10] for s in (opp.get("sightings") or []) if s.get("seen_on")]
    return min(dates) if dates else None


def _file_gap(run_id, scope, reason, closes_when, out):
    """One gap per `(run, scope)` -- a second call in the same run adds nothing. Best-effort and
    loud: a journal that cannot be written (the tracked fixture) is reported, not swallowed."""
    import journal as _journal
    try:
        if any(g.get("scope") == scope for g in _journal.open_gaps(_journal.read(ROOT),
                                                                    run_id=run_id)):
            return None
        return _journal.record_gap(ROOT, run_id, scope, reason, closes_when=closes_when)
    except _journal.JournalError as e:
        out("⚠️ could not journal the gap %s (%s)" % (scope, e))
        return None


def _handback_rel(run_id, surface):
    """The profile-relative path of the kept hand-back for `(run, surface)`. Keyed by both, so a
    re-run of the same call overwrites its own copy and never another pass's."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(run_id))[:80].strip("-") or "run"
    return "/".join(ROLES_HANDBACK_DIR + ("roles-%s-%s.md" % (safe, surface),))


def _keep_handback(text, run_id, surface, out):
    """dev #707 / public #151 (D2) -- copy the raw hand-back under the PROFILE root, byte for byte,
    so a refused or faulty block is never lost with the dispatch that wrote it. Returns the
    absolute path, or `None` (reported, never swallowed) when it cannot be written."""
    path = os.path.join(ROOT, *_handback_rel(run_id, surface).split("/"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as e:
        out("⚠️ could not keep a copy of the hand-back at %s (%s)" % (path, e))
        return None
    return path


def _describe_fault(f):
    if f["line"] is None:
        return "BLOCK FAULT: %s" % f["rule"]
    return "LINE FAULT  line %d: %s -- %r" % (f["line"], f["rule"], f["text"])


def _resolve_roles(roles, run_id, surface, queries, run_date, pass_label, opps, companies, apps,
                   recs, rows, out, already_locked=False):
    """dev #751 (design §3.5, B8) -- resolve each parsed role to exactly ONE outcome. This is the
    per-role half of `add_roles`, split out so the company feed poller (`feed_poll.py`,
    `surface="feed"`) resolves a posting through the SAME code a sweep does: no second de-duplication.
    `add_roles` keeps its behaviour byte for byte (its existing tests are the proof).

    `roles` are the dicts `parse_roles` builds (url, title, company, location, canonical, the three
    slots, `q`); a feed builds the same dicts. THE CHANNEL INPUT (B8): a role dict may carry
    `channel_id` (and `source`, e.g. `feed:lever`); a feed role MUST, and it is used (1) as the
    channel of a sibling listing linked onto a known row and (2) carried on the `capture-role` item it
    queues (B7), so `record.py create --from-item` records the sighting's channel instead of
    trusting a model to name it. `queries` is the QUERY list the `q=` ordinals index (empty for a
    feed, whose roles carry no `q`).

    THE FEED DE-DUP PREDICATE (B8): a posting is KNOWN when its canonical URL equals a live row's
    `jd_url` or any of its sightings' `source_url` -- `pipeline_index.find_known_match`, URL first.
    That is a hit with basis `jd_url` / `sighting url`: counted `known`, NOTHING written, whichever
    channel the sighting names (the URL is the identity; a different channel for the same URL does
    not count), so a daily re-poll writes nothing. A role matching only on company + title is another
    LISTING of a known requisition and appends a sighting, guarded by `feed_sighting_needed`.

    Returns the state `add_roles` reports from: counts (captured / known / carried / quarantined /
    role_gaps), siblings, possible, resolved_keys, screen_ids, quarantine_reasons, captured_degraded.
    `quarantined` is always 0 for a feed (a feed is a complete listing, so no role is held degraded),
    and the feeds event asserts it."""
    import journal as _journal
    from pipeline_index import (find_known_match, resolve_company)
    counts = {"captured": 0, "known": 0, "carried": 0, "quarantined": 0, "role_gaps": 0}
    siblings = possible = 0          # dev #728 / public #158 -- subsets of known/carried, not buckets
    resolved_keys, screen_ids = set(), []
    quarantine_reasons, captured_degraded = {}, 0

    for r in roles:
        title, company, loc = _clip(r["title"]), _clip(r["company"]), _clip(r["location"])
        key = _role_key(company, title)
        if r["canonical"] is None:
            reason = r.get("reason") or "partial-results"
            scope = "jobsearch:role:%s" % key
            counts["role_gaps"] += 1
            out("ROLE GAP    %s at %s -- %s (%s)" % (title, company,
                                                      "no URL" if not r["url"] else
                                                      "no job id in the URL", reason))
            if not any(g.get("scope") == scope for g in _journal.open_gaps(recs)):
                try:
                    _journal.record_gap(ROOT, run_id, scope, reason, closes_when="captured")
                except _journal.JournalError as e:
                    out("⚠️ could not journal the gap %s (%s)" % (scope, e))
            continue
        canon = r["canonical"]
        company_id = resolve_company(company, companies)
        hit = find_known_match(opps, url=canon, company_id=company_id, title=title,
                               applications=apps)
        resolved_keys.add(key)
        # ⭐ dev #728 / public #158 -- ONE REQUISITION LISTED AT SEVERAL PLACES IS ONE DECISION. A
        # role that matches an existing row on company + title (its URL is not on the row) is another
        # LISTING of it: added as a sighting carrying its location, through record.py, whether the
        # row is active or passed -- unless it is strictly NEARER than every place a PASSED row was
        # listed at (R8), which is printed and carried as a fresh capture item instead.
        listing_note = ""
        if hit and hit[1] == "company + title":
            lrow, _lb, lkind = hit
            nearer = False
            if lkind == "excluded" and loc not in ("", "?"):
                try:
                    import pipeline_index as _pidx_l
                    import profile as _pf
                    nearer, near_place, near_state = _pf.nearer_listing(
                        _pidx_l.listing_places(lrow), [loc], _pf.load())
                except (OSError, ValueError, KeyError):
                    nearer = False
            if nearer:
                out("NEARER LISTING of passed %s: %s (%s)" % (lrow.get("id"), near_place, near_state))
                hit = None            # not auto-closed: carried below, so it can become a decision
            else:
                qs = [queries[k - 1] for k in (r.get("q") or [])
                      if 0 < k <= len(queries)]
                channel = (r.get("channel_id")          # a feed role names its own (dev #751)
                           or next((q.get("channel") for q in qs if q.get("channel")), None)
                           or lrow.get("channel_id")
                           or next((s.get("channel_id") for s in (lrow.get("sightings") or [])
                                    if s.get("channel_id")), None))
                if channel and (surface != "feed" or feed_sighting_needed(lrow, canon)):
                    sg = {"channel_id": channel, "seen_on": run_date, "source_url": canon}
                    if loc not in ("", "?"):
                        sg["location"] = loc
                    why = _link_listing(lrow.get("id"), sg, already_locked)
                    if why is None:
                        listing_note = " +listing %s" % (loc if loc not in ("", "?") else "(no place)")
                        siblings += 1
                    else:
                        out("⚠️ could not add the listing %s to %s (%s)" % (canon, lrow.get("id"), why))
        if hit:
            row, basis, kind = hit
            if kind == "active" and _earliest_seen(row) == run_date:
                counts["captured"] += 1
                screen_ids.append(row.get("id"))
                # §3.8 (PARTIAL, named): the runner captured this in-pass, before this script saw
                # the block, so quarantine cannot reach it. It is COUNTED and said, not prevented.
                if r.get("quarantine_codes"):
                    captured_degraded += 1
                    out("CAPTURED    %s (%s) -- the pass captured it this run (DEGRADED QUERY: %s)%s"
                        % (row.get("id"), basis, ", ".join(r["quarantine_codes"]), listing_note))
                else:
                    out("CAPTURED    %s (%s) -- the pass captured it this run%s"
                        % (row.get("id"), basis, listing_note))
            else:
                counts["known"] += 1
                out("KNOWN       %s (%s, %s)%s" % (row.get("id"), basis,
                                                   "passed" if kind == "excluded" else "active",
                                                   listing_note))
            continue
        # a NEAR MISS (titles equal once a trailing place is removed) is printed, counted and NEVER
        # merged: record linkage's clerical-review rule (design §5.2)
        if company_id:
            import pipeline_index as _pidx_p
            near_miss = next((o for o in opps if o.get("company_id") == company_id
                              and not _pidx_p.is_folded(o)
                              and _pidx_p.possible_sibling(title, o.get("title"))), None)
            if near_miss is not None:
                possible += 1
                out("POSSIBLE SIBLING %s ~ %s" % (canon, near_miss.get("id")))
        pending = _pending_by_ref(KIND_CAPTURE, canon, rows)
        if pending is None:
            # the SAME requisition already queued under another URL: this listing joins THAT item
            # (a sibling of a quarantined item stays with it); no second item is made
            sib = _pending_by_key(KIND_CAPTURE, key, rows, exclude_ref=canon)
            if sib is not None:
                counts["carried"] += 1
                if any(s.get("url") == canon for s in (sib.get("siblings") or [])):
                    out("CARRIED     %s (already a sibling listing of %s)" % (canon, sib["id"]))
                else:
                    _append_sibling(sib["id"], canon, None if loc in ("", "?") else loc)
                    sib["siblings"] = list(sib.get("siblings") or []) + [
                        {"url": canon, "location": None if loc in ("", "?") else loc}]
                    siblings += 1
                    out("SIBLING     %s (%s) -> %s" % (canon, loc or "?", sib["id"]))
                continue
        qcodes = r.get("quarantine_codes")
        held = bool(pending and pending.get("quarantine"))
        if qcodes and pending and not held:
            # an earlier CLEAN sighting vouched for this item: a degraded one does not undo it
            counts["carried"] += 1
            out("CARRIED     %s (already pending %s, kept clean: a clean query vouched for it)"
                % (canon, pending["id"]))
            continue
        if qcodes:
            # dev #722 / public #156 -- every query that showed this role is DEGRADED: hold it.
            counts["quarantined"] += 1
            for code in qcodes:
                quarantine_reasons[code] = quarantine_reasons.get(code, 0) + 1
            qks = ",".join(str(k) for k in r["q"])
            if held:
                out("QUARANTINED %s (q=%s: %s) already held as %s"
                    % (canon, qks, ", ".join(qcodes), pending["id"]))
                continue
            what = ("Capture role: %s at %s (%s), seen %s pass: %s"
                    % (title, company, loc or "?", pass_label, canon))
            item = _append_item(what, "seen in a pass; not yet captured", (), kind=KIND_CAPTURE,
                                ref=canon, role=role_payload(r, run_date),
                                quarantine={"run_id": run_id, "because": list(qcodes),
                                            "queries": list(r["q"])})
            rows.append(item)
            out("QUARANTINED %s (q=%s: %s) queued %s" % (canon, qks, ", ".join(qcodes), item["id"]))
            continue
        counts["carried"] += 1
        if held:
            # a CLEAN sighting is new evidence: release exactly this role
            _append_unquarantine(pending["id"], "clean sighting run=%s" % run_id)
            pending["quarantine"] = None
            out("RELEASED    %s (%s) -- a clean query showed it" % (canon, pending["id"]))
            continue
        if pending:
            out("CARRIED     %s (already pending %s)" % (canon, pending["id"]))
            continue
        what = ("Capture role: %s at %s (%s), seen %s pass: %s"
                % (title, company, loc or "?", pass_label, canon))
        item = _append_item(what, "seen in a pass; not yet captured", (), kind=KIND_CAPTURE,
                            ref=canon, role=role_payload(r, run_date),
                            channel_id=r.get("channel_id"), source=r.get("source"))
        rows.append(item)
        out("CARRIED     %s (queued %s)" % (canon, item["id"]))
    return {"counts": counts, "siblings": siblings, "possible": possible,
            "resolved_keys": resolved_keys, "screen_ids": screen_ids,
            "quarantine_reasons": quarantine_reasons, "captured_degraded": captured_degraded}


def feed_sighting_needed(row, url):
    """dev #751 (B8) -- the de-dup predicate for a feed sighting: True only when `url` is NOT already
    the row's `jd_url` or the `source_url` of one of its sightings (compared canonically, as
    `record.py`'s `_link_from_item` compares: its `have` test). A split-off sighting no longer
    evidences the row, as in `find_known_match`."""
    import pipeline_index as _pidx
    have = [row.get("jd_url")] + [s.get("source_url") for s in (row.get("sightings") or [])
                                  if isinstance(s, dict) and not s.get("split_to")]
    return not any(h and _pidx._urls_equal(url, h) for h in have)


def add_roles(text, run_id, surface, out=print, check=False, already_locked=False):
    """dev #692 / public #140 (692-2a/b, N5, N6) -- the gate on a pass report. Returns the exit
    code: 0 clean, 4 accepted with line faults (dev #707 / public #151), 3 refused (ONE
    `partial-results` gap `jobsearch:roles:<surface>`, nothing else written).

    ⭐ A LINE FAULT NEVER DISCARDS A VALID ROLE (dev #707 / public #151). Only a STRUCTURAL fault
    refuses the block (see `parse_roles`). Every other fault -- a stray line, a QUERY or ROLE that
    breaks a rule, a duplicate posting, a SEEN count that disagrees with the lines -- becomes a
    `partial-results` gap of its own (`jobsearch:roles-line:<surface>:<line|block:<check>>`, naming
    the line, the line's text and the rule) while every ROLE that parsed is resolved exactly as
    below. Whenever the call refuses or records any fault, the raw hand-back is copied to
    `<profile root>/.jobsearch/handbacks/roles-<run>-<surface>.md` and the message names it.
    `check=True` (`--check`) runs the SAME parse, prints every fault and a one-line verdict
    (`clean`, `N line faults`, `refused: <why>`), writes NOTHING, and returns the same code the
    real call would.

    An accepted block resolves EVERY `ROLE` line to exactly one outcome (never a prose count):

      * a role gap -- `ROLE nourl`, or a URL with no canonical form (a LinkedIn URL with no job id
        is never guessed at);
      * known (passed) -- matches an EXCLUDED row (`find_known_match`, so a passed role stays passed);
      * captured -- matches an ACTIVE row whose earliest sighting is this run's date (the runner
        captured it in-pass; its opp id is printed so the write phase screens it);
      * known -- matches any other ACTIVE row;
      * quarantined (dev #722 / public #156) -- not known or captured, and EVERY query in its `q=`
        reported a degradation: ONE `capture-role` item carrying a `quarantine` field that no
        worker is served (a clean re-sighting releases it);
      * carried -- anything else, including an EXPIRED row's repost: ONE `capture-role` item,
        `ref` the canonical URL, idempotent on `(kind, ref)`.

    then asserts the identity `distinct = captured + known + carried + quarantined + role_gaps`
    (over the ROLE lines accepted) and writes ONE `roles` event. Query-level gaps (unreachable, window not
    applied, truncated) are filed and counted in their own fields. Re-running the same block writes
    no new row: the queue is idempotent, a gap is filed once per run, and an identical `roles`
    event is not repeated."""
    import journal as _journal
    gap_scope = _journal.ROLES_GAP_SCOPE % surface
    rel = _handback_rel(run_id, surface)
    try:
        parsed = parse_roles(text, run_id, surface)
    except RolesRefused as e:
        if check:
            out("verdict: refused: %s" % e)
            return ROLES_EXIT_REFUSED
        kept = _keep_handback(text, run_id, surface, out)
        out("⛔ REFUSED — %s. Nothing was recorded except a `partial-results` gap (%s)."
            % (e, gap_scope))
        if kept:
            out("   The raw hand-back is kept at %s" % kept)
        _file_gap(run_id, gap_scope, "partial-results",
                  "the pass's ROLES block is accepted by deferred.py --add-roles --surface %s%s"
                  % (surface, (" (raw hand-back kept at %s)" % rel) if kept else ""), out)
        return ROLES_EXIT_REFUSED

    faults = parsed["faults"]
    if check:
        for f in faults:
            out(_describe_fault(f))
        if faults:
            out("verdict: %d line fault%s" % (len(faults), "" if len(faults) == 1 else "s"))
            return ROLES_EXIT_FAULTS
        out("verdict: clean")
        return ROLES_EXIT_OK

    opps = _load_store("opportunities.jsonl")
    companies = _load_store("companies.jsonl")
    apps = _load_store("applications.jsonl")
    recs = _journal.read(ROOT)
    starts = [r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id]
    run_date = str(starts[0].get("at"))[:10] if starts else datetime.date.today().isoformat()
    window = parsed["header"]["window"]
    pass_label = "board" if surface == "board" else window
    rows = replay(load())
    res = _resolve_roles(parsed["roles"], run_id, surface, parsed["queries"], run_date, pass_label,
                         opps, companies, apps, recs, rows, out, already_locked)
    counts, siblings, possible = res["counts"], res["siblings"], res["possible"]
    resolved_keys, screen_ids = res["resolved_keys"], res["screen_ids"]
    quarantine_reasons, captured_degraded = res["quarantine_reasons"], res["captured_degraded"]

    # a role a later block resolves closes its open per-role gap (closes_when: captured)
    closed = {g.get("gap_id") for g in recs if g.get("event") == "gap-closed"}
    for g in [g for g in recs if g.get("event") == "gap" and g.get("gap_id") not in closed
              and str(g.get("scope", "")).startswith("jobsearch:role:")]:
        if g["scope"].split(":", 2)[2] in resolved_keys:
            try:
                _journal.append(ROOT, {"event": "gap-closed", "gap_id": g["gap_id"],
                                       "at": _journal.now_iso()})
                closed.add(g["gap_id"])
                out("GAP CLOSED %s (the role is accounted for now)" % g["scope"])
            except _journal.JournalError as e:
                out("⚠️ could not close the gap %s (%s)" % (g["scope"], e))

    geos_ok, gaps_window, gaps_trunc, gaps_filters = set(), 0, 0, 0
    # dev #722 / public #156 (R4) -- the per-query READ counts. Every reached query is exactly one of
    # clean (dropped=none, added=none, nothing degraded), unread (`?` on a filter slot, nothing
    # degraded) or degraded; `total=?` over a page is counted APART (it can sit under any of the
    # three). SHAPE, not enforced: these are counts of what the sweep SAID.
    q_reached = q_clean = q_unread = q_total_unknown = q_degraded_queries = 0
    q_degraded = {}
    for q in parsed["queries"]:
        scope = "jobsearch:query:%s:%s%s" % (surface, q["geo"],
                                              (":" + q["channel"]) if q.get("channel") else "")
        if q["status"] == "reached" and not q["window_gap"]:
            geos_ok.add(q["geo"])
        if q["status"] == "reached":
            q_reached += 1
            if "total-unknown" in q["unread"]:
                q_total_unknown += 1
            if q["degraded"]:
                q_degraded_queries += 1
                for code in q["degraded"]:
                    q_degraded[code] = q_degraded.get(code, 0) + 1
            elif "filters-unread" in q["unread"]:
                q_unread += 1
            else:
                q_clean += 1
        if q["window_gap"]:
            gaps_window += 1
            reason = q.get("reason") or "partial-results"
            out("QUERY GAP  %s (%s): %s" % (scope, reason,
                                            "unreachable" if q["status"] == "unreachable"
                                            else "window not applied"))
            _file_gap(run_id, scope, reason, "the next pass applies its window on this query", out)
        elif q["truncated"]:
            gaps_trunc += 1
            out("QUERY TRUNCATED %s: shown %d of %s%s" % (scope, q["shown"], q["total"],
                                                          "+" if q.get("total_lower_bound") else ""))
            _file_gap(run_id, scope, "partial-results",
                      "a narrower query shows every result", out)
        if q["status"] == "reached" and (q["dropped"] or q["added"] or q["dropped_unread"]
                                         or q["added_unread"]):
            gaps_filters += 1
            if q["dropped"] or q["added"]:
                named = [x for x in (
                    ("dropped=%s" % ",".join(q["dropped"])) if q["dropped"] else "",
                    ("added=%s" % ",".join(q["added"])) if q["added"] else "") if x]
                out("QUERY FILTERS %s: %s (its roles are quarantined unless a clean query also "
                    "showed them)" % (scope, "; ".join(named)))
            else:
                out("QUERY FILTERS %s: filters unread (dropped/added = ?): a gap, never a "
                    "quarantine" % scope)
            _file_gap(run_id, scope, "partial-results",
                      "the next pass applies the requested filters on this query", out)
        if q["status"] == "reached" and "total-unknown" in q["unread"]:
            out("QUERY TOTAL UNKNOWN %s: shown %d, total not read (counted; never a quarantine)"
                % (scope, q["shown"]))
            _file_gap(run_id, scope, "partial-results",
                      "the next pass reads the result count on this query", out)

    # dev #707 / public #151 -- a line fault is a gap of its own; the roles above are already in
    kept = _keep_handback(text, run_id, surface, out) if faults else None
    fault_scopes = set()
    for f in faults:
        scope = ROLES_LINE_GAP_SCOPE % (surface, f["scope_key"])
        fault_scopes.add(scope)
        out(_describe_fault(f))
        what = ("line %d %r broke: %s" % (f["line"], f["text"], f["rule"])
                if f["line"] is not None else "block check broke: %s" % f["rule"])
        _file_gap(run_id, scope, "partial-results",
                  "%s -- fixed when a corrected hand-back for this run is accepted by deferred.py "
                  "--add-roles --surface %s%s" % (what, surface,
                                                   (" (raw hand-back kept at %s)" % rel)
                                                   if kept else ""), out)
    # a corrected re-submission closes the line gaps it no longer has
    prefix = ROLES_LINE_GAP_SCOPE % (surface, "")
    for g in _journal.open_gaps(_journal.read(ROOT), run_id=run_id):
        sc = str(g.get("scope", ""))
        if sc.startswith(prefix) and sc not in fault_scopes:
            try:
                _journal.append(ROOT, {"event": "gap-closed", "gap_id": g["gap_id"],
                                       "at": _journal.now_iso()})
                out("GAP CLOSED %s (the corrected hand-back no longer has this fault)" % sc)
            except _journal.JournalError as e:
                out("⚠️ could not close the gap %s (%s)" % (sc, e))

    listed = parsed["listed"]
    ident = (counts["captured"] + counts["known"] + counts["carried"] + counts["quarantined"]
             + counts["role_gaps"])
    if ident != listed:                                    # cannot happen; asserted anyway
        out("⛔ the roles identity does not hold (%d != %d); nothing recorded" % (ident, listed))
        return ROLES_EXIT_REFUSED
    f_tpr = None
    if surface == "linkedin-jobsearch":
        f_tpr = _journal.F_TPR_WIDE if window == "wide" else _journal.F_TPR_DAILY
    event = dict(run_id=run_id, surface=surface, window=window, f_tpr=f_tpr,
                 queries=len(parsed["queries"]), geos_ok=sorted(geos_ok),
                 query_gaps_window=gaps_window, query_gaps_truncated=gaps_trunc,
                 distinct=listed, captured=counts["captured"], known=counts["known"],
                 carried=counts["carried"], role_gaps=counts["role_gaps"],
                 quarantined=counts["quarantined"], quarantine_reasons=quarantine_reasons,
                 query_gaps_filters=gaps_filters, captured_degraded=captured_degraded,
                 q_reached=q_reached, q_clean=q_clean, q_unread=q_unread,
                 q_total_unknown=q_total_unknown, q_degraded=q_degraded,
                 q_degraded_queries=q_degraded_queries)
    same = [e for e in _journal.roles_events(recs, run_id=run_id, surface=surface)
            if all(e.get(k) == v for k, v in event.items())]
    if same:
        out("= already recorded: an identical roles event for this run and surface")
    else:
        try:
            _journal.record_roles(ROOT, **event)
        except _journal.JournalError as e:
            out("⚠️ could not journal the roles event (%s)" % e)
    out("ROLES RECORDED run=%s surface=%s window=%s: %d seen = %d captured + %d known + %d carried "
        "+ %d role gap(s) + %d quarantined · %d query gap(s) (window) · %d truncated"
        "%s"
        % (run_id, surface, window, listed, counts["captured"], counts["known"],
           counts["carried"], counts["role_gaps"], counts["quarantined"], gaps_window, gaps_trunc,
           (" · %d sibling listing(s) linked · %d possible sibling(s)" % (siblings, possible))
           if (siblings or possible) else ""))
    out("QUERY READS %d reached: %d clean · %d filters unread · %d degraded%s · %d total unknown"
        % (q_reached, q_clean, q_unread, q_degraded_queries,
           (" (%s)" % ", ".join("%s x%d" % (c, n) for c, n in sorted(q_degraded.items())))
           if q_degraded else "", q_total_unknown))
    if counts["quarantined"]:
        out("HELD %d role(s) (quarantined) from degraded queries: %s -- not captured until a clean "
            "pass sees them, or deferred.py --unquarantine <id>"
            % (counts["quarantined"], " · ".join("%s x%d" % (c, n) for c, n
                                                   in sorted(quarantine_reasons.items()))))
    if screen_ids:
        # dev #729 / public #157: ONE command naming every captured id, so the screen ends with its
        # own summary line (screened, keep, remove by rule, review, the commute split) instead of a
        # tally the model keeps by hand ("75 screened, 0 removed" was a number nobody could read).
        out("SCREEN      ~/.claude/jobsearch/run profile.py --minimal-screen %s"
            % " ".join(str(oid) for oid in screen_ids))
    if faults:
        out("⚠️ ACCEPTED WITH %d LINE FAULT(S): every valid role above was recorded; each faulty "
            "line is a `partial-results` gap (scope %s*). Exit %d."
            % (len(faults), prefix, ROLES_EXIT_FAULTS))
        if kept:
            out("   The raw hand-back is kept at %s -- fix the lines in it and run --add-roles "
                "again (idempotent), or leave the gaps." % kept)
        return ROLES_EXIT_FAULTS
    return ROLES_EXIT_OK


CANNOT_READ_REQUIREMENT = {
    "requirement": "Read the job description", "verdict": "unknown", "evidence": None,
    "pitch_line": None,
    "question_for_candidate": ("No surface that ran could read this JD: read it yourself before "
                               "deciding."),
    "question_status": "open", "answered_on": None, "landed_in": None, "act_by": None}


def _write_cannot_read(opp, now, already_locked, out):
    """dev #723 -- record `fit.jd_source = "unavailable: surface-cannot-read"` on `opp` THROUGH
    `record.py set` (one writer of `opportunities.jsonl`: the lock, the validator, the rollback and
    the surface-cannot-read gate all apply; this script never opens the store for writing). The rest of
    `fit` is kept and `analyzed_on` is set; a role that never had a `fit` gets one open question
    (the validator wants a non-empty `requirements`), so the candidate sees why it is unread. A
    subprocess on this interpreter: `record.py` exposes no in-process dispatch. True when it wrote."""
    import subprocess
    fit = dict(opp.get("fit") or {})
    fit["jd_source"] = SURFACE_CANNOT_READ
    fit["analyzed_on"] = now.date().isoformat()
    if not fit.get("requirements"):
        fit["requirements"] = [dict(CANNOT_READ_REQUIREMENT)]
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.py"),
           "set", str(opp.get("id")), "fit", json.dumps(fit)]
    if already_locked:
        cmd.append("--already-locked")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        out("⚠️ could not record surface-cannot-read on %s (record.py exit %d): %s"
            % (opp.get("id"), r.returncode, " ".join((r.stdout + r.stderr).split())[-300:]))
        return False
    return True


def settle(out=print, now=None, already_locked=False):
    """dev #692 / public #140 -- close the script-built items the stores already show done, so
    a carried role that has been captured stops being listed as owed. Returns the closed ids.

    * a `capture-role` item whose `ref` is the canonical URL of any `jd_url` or
      `sightings[].source_url` in `opportunities` (canonical on both sides, N6: a tracking-
      parameter variant of the URL still closes it);
    * a `research-role` item whose opportunity has a non-empty `research_log`;
    * a `read-jd` item (dev #723) whose opportunity no longer lists `jd-read` in
      `your_move.triage_missing`: someone read it. One that is STILL unread and has waited MORE THAN
      `search.triage_stuck_days` days (`jd_read_waited_past_bound`) is the case no worker with a browser
      came for: it records `fit.jd_source = "unavailable: surface-cannot-read"` through `record.py`
      (`_write_cannot_read`; `already_locked` is passed through, for a call inside a run's write
      phase) and then closes. Before the bound it does nothing.

    A per-role gap closes in `add_roles` itself, the moment a later block resolves the role."""
    from pipeline_index import canonical_job_url
    import your_move as _ym
    opps = _load_store("opportunities.jsonl")
    by_id = {o.get("id"): o for o in opps}
    urls = set()
    for o in opps:
        for u in [o.get("jd_url")] + [s.get("source_url") for s in (o.get("sightings") or [])]:
            c = canonical_job_url(u) if u else None
            if c:
                urls.add(c)
    now = now or datetime.datetime.now()
    closed = []
    for r in replay(load()):
        if r.get("status") != "pending":
            continue
        done = False
        if r.get("kind") == KIND_CAPTURE and r.get("ref"):
            done = (canonical_job_url(r["ref"]) or r["ref"]) in urls
        elif r.get("kind") == KIND_RESEARCH and r.get("ref"):
            done = bool((by_id.get(r["ref"]) or {}).get("research_log"))
        elif r.get("kind") == KIND_JD_READ and r.get("ref"):
            opp = by_id.get(r["ref"])
            if opp is not None and "jd-read" not in _ym.triage_missing(opp):
                done = True
            elif opp is not None and jd_read_waited_past_bound(r, _ym.triage_stuck_days(), now):
                done = _write_cannot_read(opp, now, already_locked, out)
                if done:
                    out("CANNOT READ %s: no worker with a browser read it within %d days; recorded "
                        "%s" % (r["ref"], _ym.triage_stuck_days(), SURFACE_CANNOT_READ))
        if done:
            with open(QUEUE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"id": r["id"], "kind": "_done",
                                     "done_at": now.isoformat(timespec="seconds")}) + "\n")
            closed.append(r["id"])
            out("SETTLED    %s (%s %s)" % (r["id"], r.get("kind"), r.get("ref")))
    out("SETTLE: %d item(s) closed" % len(closed))
    return closed


def claim_capabilities(attended=False):
    """dev #692 / public #140 (N1, R2) -> `(caps, me, report, posture_name)`: the capabilities a
    worker may CLAIM with, which are the machine's (`whoami.probe()`, unchanged) plus the posture
    tokens `posture.merge_tokens` grants, plus `caps["linkedin"]` = `posture.may("linkedin")`.

    * only the fixed vocabulary `posture.MERGEABLE_POSTURE_TOKENS` is ever merged, and
      `linkedin` never is: it is set from `may("linkedin")` (browser + quota) alone, so a
      browserless worker can claim no `requires: linkedin` item under ANY posture, attended or
      not;
    * `attended=True` is the explicit attended form (owner decision R2) and grants every
      mergeable token; it is the only way past a posture's gate, and is never inferred;
    * `report` is one line per token that was NOT granted, printed as `--claimable`'s header so
      a run's transcript shows exactly what it was granted. An unreadable posture merges nothing
      (fails safe, like `may()`) and says so."""
    caps, me = capabilities()
    caps = dict(caps)
    report, name = [], None
    try:
        import posture as _posture
        name, p, err = _posture.load()
        granted, rep = _posture.merge_tokens(p, caps, attended=attended)
        report.extend(rep)
        for token in granted:
            caps[token] = True
        # `may("linkedin")` is False when the posture does not list it, when the browser check
        # fails, or when the quota is spent; it also reads the journal, which can be unreadable.
        try:
            caps["linkedin"] = bool(_posture.may("linkedin"))
        except Exception as e:                                   # noqa: BLE001 -- fail safe
            caps["linkedin"] = False
            report.append("linkedin not granted: %s" % e)
    except Exception as e:                                       # noqa: BLE001 -- fail safe
        report.append("posture unreadable: no posture tokens merged (%s)" % e)
    return caps, me, report, name


def _missing(rec, caps):
    return [t for t in (rec.get("requires") or []) if not caps.get(t)]


def can_run(rec, caps):
    return all(caps.get(r) for r in (rec.get("requires") or []))


def held_by_posture(rec, caps):
    """True when the only thing keeping a worker from `rec` is a posture token (research,
    drafting, sweeps): the item is HELD, not impossible here, and drains once a run's posture (or
    an attended run) grants that token. An item that also needs a machine capability, or
    `linkedin`, is not held by posture: it needs another environment."""
    missing = _missing(rec, caps)
    if not missing:
        return False
    import posture as _posture
    return all(t in _posture.MERGEABLE_POSTURE_TOKENS for t in missing)


def main():
    ap = argparse.ArgumentParser(description="Work that needs the laptop.")
    ap.add_argument("--add", metavar="WHAT")
    ap.add_argument("--add-linkedin-pass", dest="add_linkedin_pass", action="store_true",
                    help="Queue THE owed LinkedIn pass (dev #481 / public #112): fixed text, no "
                         "argument, and no row at all while one is already pending. Used by "
                         "daily-run and by linkedin-runner's PASS failure branches; a non-pass "
                         "dispatch that fails keeps a free-text --add.")
    ap.add_argument("--add-research", dest="add_research", metavar="OPP_ID",
                    help="Queue the research a posture (or max_agents_per_run) held for this "
                         "opportunity (dev #692 / public #140): fixed text, requires the "
                         "`research` posture token, idempotent while one is pending. Drains on "
                         "the first run whose posture permits research, or an --attended run.")
    ap.add_argument("--add-draft", dest="add_draft", metavar="OPP_ID",
                    help="The draft twin of --add-research: requires `drafting`. The item asks "
                         "for a DRAFT; a send is never queued.")
    ap.add_argument("--add-jd-read", dest="add_jd_read", metavar="OPP_ID",
                    help="Queue the JD read this surface could not do (dev #723): fixed text, "
                         "requires `chrome`, idempotent while one is pending, nothing queued for a "
                         "role already read. With --run, the item is never served to that run.")
    ap.add_argument("--add-roles", dest="add_roles", metavar="FILE",
                    help="The gate on a pass report (dev #692 / public #140): FILE is the pass's "
                         "hand-back holding a `ROLES v1` block; needs --run and --surface. Every "
                         "ROLE line resolves to captured / known / carried (one capture-role item "
                         "per role) / a per-role gap. A faulty LINE never discards a valid role: "
                         "it becomes a gap of its own and the call exits 4 (accepted with line "
                         "faults). Only a STRUCTURAL fault (no block, two blocks, a bad header, a "
                         "run or surface that is not this call's, no END line) refuses the block "
                         "(exit 3, one partial-results gap, nothing else written). Exit 0 is "
                         "clean. A refusal or any line fault keeps the raw hand-back under the "
                         "profile's .jobsearch/handbacks/. Idempotent.")
    ap.add_argument("--surface", choices=("linkedin-jobsearch", "board"),
                    help="With --add-roles: the surface the block belongs to.")
    ap.add_argument("--check", action="store_true",
                    help="With --add-roles (dev #707 / public #151): parse the hand-back with the "
                         "SAME code, print every faulty line with its line number and the rule it "
                         "broke, then one verdict line (`verdict: clean`, `verdict: N line "
                         "faults` or `verdict: refused: <why>`). Writes nothing to any store or "
                         "folder. Exit 0 clean, 4 line faults, 3 refused: the real call's codes. "
                         "Run it on a hand-back before accepting it.")
    ap.add_argument("--settle", action="store_true",
                    help="Close the script-built items the stores already show done: a "
                         "capture-role item whose URL now has an opportunity, a research-role "
                         "item whose opportunity has a research_log (dev #692), a read-jd item "
                         "whose role was read; one still unread past search.triage_stuck_days "
                         "records surface-cannot-read through record.py first (dev #723).")
    ap.add_argument("--already-locked", dest="already_locked", action="store_true",
                    help="With --settle or --add-roles: the calling run already holds the run "
                         "lock, so the record.py write that records surface-cannot-read (dev #723) "
                         "or adds a sibling listing to an existing row (dev #728) passes "
                         "--already-locked.")
    ap.add_argument("--attended", action="store_true",
                    help="This run was started with the EXPLICIT attended form (owner decision "
                         "R2): claims may use the research/drafting tokens regardless of the "
                         "posture. NEVER grants `linkedin`. A run is unattended unless it passes "
                         "this; attended is never inferred.")
    ap.add_argument("--run", metavar="ID", default=None,
                    help="With --add: the run this call belongs to. A REFUSED add then leaves a "
                         "`deferred:refused` gap in the run's journal, so a refused carry-forward "
                         "is never lost silently (dev #692). With --add-jd-read: the run that "
                         "queued the item. With --claimable / --claim: this run's id, so an item "
                         "THIS run queued (a read-jd item it could not finish) is not served back "
                         "to it (dev #723).")
    ap.add_argument("--why", metavar="WHY", default="")
    ap.add_argument("--requires", metavar="CAPS", default="",
                    help="Comma-separated capabilities this work NEEDS (e.g. chrome,keychain). "
                         "Routing depends on it: a worker claims only what it can finish.")
    ap.add_argument("--unquarantine", metavar="ID",
                    help="Release one QUARANTINED capture-role item (dev #722 / public #156): a "
                         "role every query of which reported a degradation is held and never "
                         "served by --claimable or --claim. A later CLEAN sighting releases it "
                         "on its own; this is the owner's release. Append-only.")
    ap.add_argument("--claimable", action="store_true",
                    help="Show only what THIS worker can actually execute.")
    ap.add_argument("--claim", metavar="ID", help="Lease an item for this worker.")
    ap.add_argument("--release", metavar="ID", help="Give an item back.")
    ap.add_argument("--done", metavar="ID")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    now = datetime.datetime.now()
    rows = replay(load())

    if args.add_linkedin_pass or (args.add and args.add == LINKEDIN_PASS_WHAT):
        # (a hand-typed copy of the old literal dedupes too: same function, same answer)
        rec, added = queue_linkedin_pass(rows)
        if added:
            print("Queued %s [requires: %s]:\n  %s"
                  % (rec["id"], ", ".join(rec["requires"]), rec["what"]))
        else:
            print("= already pending %s (queued %s) -- a failed LinkedIn pass adds no second row"
                  % (rec["id"], rec.get("queued_at")))
        return 0

    if args.check and not args.add_roles:
        print("⛔ --check goes with --add-roles <file> --run <id> --surface <s>")
        return ROLES_EXIT_USAGE

    if args.add_roles:
        if not (args.run and args.surface):
            print("⛔ --add-roles needs --run <id> and --surface <linkedin-jobsearch|board>")
            return ROLES_EXIT_USAGE
        try:
            with open(args.add_roles, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            print("⛔ cannot read the hand-back %s: %s" % (args.add_roles, e))
            return ROLES_EXIT_USAGE
        return add_roles(text, args.run, args.surface, check=args.check,
                         already_locked=args.already_locked)

    if args.settle:
        settle(already_locked=args.already_locked)
        return 0

    if args.add_jd_read:
        try:
            rec, added = queue_jd_read(args.add_jd_read, args.run, rows)
        except DeferredRefused as e:
            print("⛔ %s" % e)
            return 2
        if rec is None:
            print("= nothing queued: %s already has its JD read recorded" % args.add_jd_read)
        elif added:
            print("Queued %s [requires: %s]:\n  %s"
                  % (rec["id"], ", ".join(rec["requires"]), rec["what"]))
        else:
            print("= already pending %s (queued %s) -- adding again writes no second row"
                  % (rec["id"], rec.get("queued_at")))
        return 0

    if args.unquarantine:
        cur = {r["id"]: r for r in rows}.get(args.unquarantine)
        if not cur:
            print("No such item: %s" % args.unquarantine)
            return 1
        if not cur.get("quarantine"):
            print("= %s is not quarantined; nothing to release" % args.unquarantine)
            return 0
        _append_unquarantine(args.unquarantine, "owner", now)
        print("Released %s from quarantine (owner)" % args.unquarantine)
        return 0

    if args.add_research or args.add_draft:
        # dev #692 / public #140 -- the engine-built forms: no free text, no send filter, an
        # opportunity id the script validates and a fixed template. Idempotent on (kind, ref).
        which = queue_research if args.add_research else queue_draft
        try:
            rec, added = which(args.add_research or args.add_draft, rows)
        except DeferredRefused as e:
            print("⛔ %s" % e)
            return 2
        if added:
            print("Queued %s [requires: %s]:\n  %s"
                  % (rec["id"], ", ".join(rec["requires"]), rec["what"]))
        else:
            print("= already pending %s (queued %s) -- adding again writes no second row"
                  % (rec["id"], rec.get("queued_at")))
        return 0

    if args.add:
        reqs = [r.strip() for r in args.requires.split(",") if r.strip()]
        try:
            rec = queue_item(args.add, why=args.why, requires=reqs)
        except DeferredRefused as e:
            if args.run:
                _record_refusal_gap(args.run, args.add)
            print("⛔ %s" % e)
            print()
            print("   CLAUDE.md: 'NEVER send messages, emails, or applications without the candidate's")
            print("   explicit fresh approval.' A send queued now and executed by an unattended")
            print("   run later is not fresh approval — it is approval-at-a-distance for an")
            print("   irreversible, outward-facing act.")
            print()
            print("   the candidate sends everything directly anyway. Put the DRAFT in drafts.md and let")
            print("   them send it when they are at the laptop with the thread in front of them.")
            return 1
        print("Queued %s%s:\n  %s"
              % (rec["id"], (" [requires: %s]" % ", ".join(rec["requires"])) if rec["requires"] else "",
                 args.add))
        return 0

    caps, me, merge_report, posture_name = claim_capabilities(attended=args.attended)

    if args.claim or args.release:
        rid = args.claim or args.release
        cur = {r["id"]: r for r in rows}.get(rid)
        if not cur:
            print("No such item: %s" % rid)
            return 1
        if args.claim:
            if cur.get("what") == LINKEDIN_PASS_WHAT:
                # dev #481 / public #112 -- the owed pass is satisfied by daily-run's own pass
                # (every run), closed by `linkedin_sweep.py record`; claiming it would run that
                # pass a second time, and N legacy duplicates would each drive one.
                print("⛔ %s is the owed LinkedIn pass -- it is never claimed. daily-run's pass "
                      "satisfies it and `linkedin_sweep.py record` closes it." % rid)
                return 1
            if args.run and cur.get("queued_run") == args.run:
                print("⛔ %s was queued by this run (%s): the run that could not do it does not "
                      "claim it back. Leave it for a later run on a surface that can."
                      % (rid, args.run))
                return 1
            if cur.get("quarantine"):
                qn = cur["quarantine"]
                print("⛔ QUARANTINED (%s) from run %s: %s was seen only through degraded queries, "
                      "so it is not served. A clean pass that sees it releases it, or "
                      "`deferred.py --unquarantine %s`."
                      % (", ".join(qn.get("because") or []), qn.get("run_id"), rid, rid))
                return 1
            if not can_run(cur, caps):
                need = ", ".join(cur.get("requires") or [])
                if held_by_posture(cur, caps):
                    print("⛔ HELD BY POSTURE (%s) — %s requires: %s. It drains on a run whose "
                          "posture permits it, or an explicitly --attended run."
                          % (posture_name or "unknown", rid, need))
                    return 1
                print("⛔ THIS WORKER CANNOT RUN %s — it requires: %s" % (rid, need))
                print("   %s has: %s" % (me, ", ".join(k for k, v in caps.items() if v) or "nothing"))
                print("   Leave it for a worker that can. A claimed task that fails is WORSE than")
                print("   an unclaimed one, because it looks handled.")
                return 1
            # design-linkedin-runner-resilience.md §5.1 — ALWAYS a LIVE check, never the stored
            # `withheld_because`: that field is folded state from whenever `--claimable` last
            # observed a withholding condition, and only `_claim` clears it — a pane that
            # recovered since then must not stay gated on a stale marker. `pane_withhold_reason`
            # is itself time-windowed (stalled_at/verdict_at vs linkedin.pane_stale_minutes), so
            # recomputing it here is cheap and always current.
            reason = pane_withhold_reason() if "chrome" in (cur.get("requires") or []) else None
            if reason:
                print("⛔ WITHHELD — %s. Leave it; the pane is not usable right now." % reason)
                return 1
            if claim_is_live(cur, now) and cur.get("claimed_by") != me:
                print("Already claimed by %s at %s (lease %d min). Not stealing."
                      % (cur["claimed_by"], cur.get("claimed_at"), CLAIM_LEASE_MINUTES))
                return 1
            rec = {"id": rid, "kind": "_claim", "claimed_by": me,
                   "claimed_at": now.isoformat(timespec="seconds")}
        else:
            rec = {"id": rid, "kind": "_release"}
        with open(QUEUE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("%s %s" % ("Claimed" if args.claim else "Released", rid))
        return 0

    if args.done:
        with open(QUEUE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": args.done, "kind": "_done",
                                 "done_at": now.isoformat(timespec="seconds")}) + "\n")
        print("Marked %s done." % args.done)
        return 0

    pending = [r for r in rows if r.get("status") == "pending"]

    # design-linkedin-runner-resilience.md §5.1 — ALWAYS a LIVE recomputation (never gated on a
    # stale folded `withheld_because`, which only `_claim` clears and would otherwise stick
    # past a pane that already recovered): computed for every listing, so the header stat is
    # honest even without --claimable, but only APPENDED as a durable `_withheld` record on
    # --claimable — that is the moment a worker actually attempted to see what it could claim,
    # which is what makes the row worth recording.
    # dev #481 / public #112 -- the owed LinkedIn pass never reaches the claim or withholding
    # paths: it is closed by `linkedin_sweep.py record`, not by a worker, and a `_withheld` row
    # appended for it on every listing while the pane is stalled would grow the raw queue
    # without a pass having failed again.
    owed_ids = {r["id"] for r in pending_linkedin_passes(rows)}
    # dev #722 / public #156 -- a QUARANTINED item (a role seen only through degraded queries) is
    # served to no worker: it leaves the pool here, before capability and pane checks, and is
    # listed apart so a held role is visible rather than missing.
    quarantined = [r for r in pending if r.get("quarantine") and r["id"] not in owed_ids]
    # dev #723 -- an item THIS run queued (`--run <id>`) is not served back to it either.
    claim_pool = [r for r in pending if r["id"] not in owed_ids and not r.get("quarantine")
                  and not (args.run and r.get("queued_run") == args.run)]
    withheld_now = {}
    for r in claim_pool:
        if "chrome" in (r.get("requires") or []) and can_run(r, caps):
            reason = pane_withhold_reason()
            if reason:
                withheld_now[r["id"]] = reason
                if args.claimable:
                    _record_withheld(r["id"], reason, now)
    if args.claimable and withheld_now:
        rows = replay(load())
        pending = [r for r in rows if r.get("status") == "pending"]
        claim_pool = [r for r in pending if r["id"] not in owed_ids and not r.get("quarantine")
                      and not (args.run and r.get("queued_run") == args.run)]

    def _is_withheld(r):
        return r["id"] in withheld_now

    mine = [r for r in claim_pool if can_run(r, caps) and not _is_withheld(r)]
    withheld = [r for r in claim_pool if can_run(r, caps) and _is_withheld(r)]
    # dev #692 / public #140 -- an item held only by a POSTURE token is not "another
    # environment's": it is claimable here the moment a run's posture (or an --attended run)
    # grants the token, and it is counted so the summary can say "3 research items held".
    held = [r for r in claim_pool if not can_run(r, caps) and held_by_posture(r, caps)]
    blocked = [r for r in claim_pool if not can_run(r, caps) and not held_by_posture(r, caps)]
    show = rows if args.all else (mine if args.claimable else pending)

    print("DEFERRED WORK — worker %s" % me)
    print("=" * 72)
    for line in merge_report:
        print("  ⚠️ %s" % line)
    print("  %d pending · %d this worker can run · %d withheld (pane) · %d held by posture · "
          "%d need another environment · %d done"
          % (len(pending), len(mine), len(withheld), len(held), len(blocked),
             len(rows) - len(pending)))
    if quarantined:
        by_code = {}
        for r in quarantined:
            for code in (r["quarantine"].get("because") or []):
                by_code[code] = by_code.get(code, 0) + 1
        print("\n  ⏸ QUARANTINED -- %d item(s) seen only through degraded queries, served to no "
              "worker (%s). A clean pass that sees the role releases it, or "
              "`deferred.py --unquarantine <id>`."
              % (len(quarantined), " · ".join("%s x%d" % (c, n) for c, n in sorted(by_code.items()))))
        for r in quarantined:
            print("     %-52s %s" % ((r.get("what") or "")[:52], r["id"]))
    if held:
        needs = sorted({t for r in held for t in _missing(r, caps)})
        print("\n  ⏸ HELD BY POSTURE (%s): %s -- %d item(s). Not failed: they drain on the first "
              "run whose posture permits %s, or an explicitly --attended run."
              % (posture_name or "unknown", ", ".join(needs), len(held),
                 "it" if len(needs) == 1 else "them"))
        for r in held:
            print("     %-52s requires %s" % ((r.get("what") or "")[:52],
                                              ", ".join(r.get("requires") or [])))
    if owed_ids:
        owed = pending_linkedin_passes(rows)
        print("\n  ⇢ LINKEDIN PASS OWED — %d row(s), oldest queued %s; closed by daily-run's pass "
              "(linkedin_sweep.py record), never claimed" % (len(owed), owed[0].get("queued_at")))
    if withheld and args.claimable:
        print("\n  ⏸ WITHHELD — a stalled or not-signed-in pane makes these unclaimable "
              "right now (the item stays queued for a session whose probe says otherwise):")
        for r in withheld:
            print("     %-52s %s" % ((r.get("what") or "")[:52],
                                     withheld_now.get(r["id"]) or r.get("withheld_because")))
    if blocked and not args.claimable:
        print("\n  ⛔ NEEDS ANOTHER ENVIRONMENT — do not attempt these here:")
        for r in blocked:
            print("     %-52s requires %s" % ((r.get("what") or "")[:52],
                                              ", ".join(r.get("requires") or [])))
    if not show:
        print("\n  Nothing waiting for this worker.")
        return 0
    for r in sorted(show, key=lambda x: x.get("queued_at") or ""):
        mark = "" if r.get("status") == "pending" else "  [done]"
        print("\n  • %s%s" % (r.get("what"), mark))
        if r.get("why"):
            print("      why deferred: %s" % r["why"])
        if r.get("requires"):
            print("      requires: %s" % ", ".join(r["requires"]))
        # Only the CURRENT computation, never the folded `withheld_because` alone — that field
        # is last-observed-at-some-point state and would otherwise keep printing WITHHELD for
        # an item this same run just counted as claimable, once the pane has recovered.
        if r["id"] in withheld_now:
            print("      WITHHELD: %s" % withheld_now[r["id"]])
        if r.get("quarantine"):
            print("      QUARANTINED: %s (run %s) -- not served" % (
                ", ".join(r["quarantine"].get("because") or []), r["quarantine"].get("run_id")))
        if claim_is_live(r, now):
            print("      CLAIMED by %s at %s" % (r.get("claimed_by"), r.get("claimed_at")))
        print("      queued %s · id %s" % (r.get("queued_at"), r.get("id")))
    print("\n" + "=" * 72)
    print("  Claim:     ~/.claude/jobsearch/run deferred.py --claim <id>")
    print("  Mark done: ~/.claude/jobsearch/run deferred.py --done <id>")
    print("  ⛔ Sends are never queued here — the candidate sends those directly, at the laptop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
