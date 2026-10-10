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
    ~/.claude/jobsearch/run deferred.py --claimable [--attended]
    ~/.claude/jobsearch/run deferred.py --add-roles <hand-back file> --run <id> --surface board
                                                                  # or linkedin-jobsearch
    ~/.claude/jobsearch/run deferred.py --settle              # close items the stores show done
    ~/.claude/jobsearch/run deferred.py --done <id>

⭐ EVERY ROLE A PASS SEES IS ACCOUNTED FOR (dev #692 / public #140, #489 / public #102).
`--add-roles` is the gate on a LinkedIn job-search or board-sweeper pass report. The report is a
`ROLES v1` block (`ROLES_GRAMMAR`, fenced byte-equal in both agent files), never a prose count: each
`ROLE` line ends up captured, known (already in the pipeline, active or passed), carried (one
`capture-role` item, `ref` the canonical URL) or a per-role gap, and the block is refused whole when
`SEEN distinct` does not equal its ROLE lines. "N seen, top few captured" cannot be written any
more, because the rest are rows. A pass that returns with NO accepted block is a gap
(`journal.py --end`, `ROLES NOT ACCOUNTED`).

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

# ⭐ THE ROLES GRAMMAR (dev #692 / public #140, N7) -- byte-equal to the fenced copy between
# `<!-- roles-grammar:begin -->` and `<!-- roles-grammar:end -->` in BOTH
# plugins/jobsearch/agents/linkedin-runner.md and plugins/jobsearch/agents/board-sweeper.md. Edit
# all three in the same commit, or `test_roles_gate.TestRolesGrammarFence` goes red. The window
# buckets are LinkedIn's own UI options only (R5): `r86400` ("Past 24 hours") and `r604800`
# ("Past week"); there is no computed window.
ROLES_GRAMMAR = """\
--- ROLES v1 run=<run-id> surface=<linkedin-jobsearch|board> window=<daily|wide|none> ---
QUERY geo=<remote|local> title="<query>" window=<r86400|r604800|none> shown=<n> total=<m|?> [unapplied] [channel=<channel_id>]
QUERY geo=<remote|local> title="<query>" unreachable reason=<journal.REASONS code> [channel=<channel_id>]
SEEN distinct=<n>
ROLE url=<posting url> title="<t>" company="<c>" location="<l|?>" posted=<YYYY-MM-DD|?>
ROLE nourl title="<t>" company="<c>" reason=<journal.REASONS code>
--- END ROLES ---"""

KIND_CAPTURE = "capture-role"
ROLES_FIELD_CAP = 200
ROLES_EXIT_OK, ROLES_EXIT_USAGE, ROLES_EXIT_REFUSED = 0, 2, 3

# A queue id is typed by hand into --claim, so four bytes (eight hex digits), not brief.py's
# eight (dev #680): 2**32 per second is far beyond any add rate this queue sees.
QUEUE_ID_ENTROPY_BYTES = 4


def load():
    if not os.path.exists(QUEUE):
        return []
    with open(QUEUE, encoding="utf-8") as fh:
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
        elif kind == "_claim" and rid in state:
            state[rid] = dict(state[rid], claimed_by=r.get("claimed_by"),
                              claimed_at=r.get("claimed_at"), withheld_because=None)
        elif kind == "_release" and rid in state:
            state[rid] = dict(state[rid], claimed_by=None, claimed_at=None)
        elif kind == "_withheld" and rid in state:
            state[rid] = dict(state[rid], withheld_because=r.get("because"))
        elif kind not in ("_done", "_claim", "_release", "_withheld"):
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


def _append_item(what, why="", requires=(), kind="action", ref=None):
    """dev #692 / public #140 (N2) -- the ONE private writer of a new queue row, and the only
    place a row reaches the queue WITHOUT passing `FORBIDDEN`. Its callers are pinned by
    `test_send_filter.py` (a source scan): `queue_item` (which checks the filter first),
    `queue_linkedin_pass`, `queue_research`, `queue_draft` and `add_roles`, and a sixth fails the
    build. Every one but the first builds `what` from a fixed template over data fields.

    `kind` is `action` for free text and the engine form's own kind otherwise; `ref` (optional,
    omitted from the row when None, so legacy rows are unchanged) is the canonical URL or opp id
    the item stands for, which is what makes the engine forms idempotent on `(kind, ref)`."""
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
    with open(QUEUE, "a", encoding="utf-8") as fh:          # append-only, like the inbox
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


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
_QUERY_REACHED = re.compile(
    r"^QUERY geo=(?P<geo>remote|local) title=" + _Q + r" window=(?P<win>r86400|r604800|none) "
    r"shown=(?P<shown>\d+) total=(?P<total>\d+|\?)(?P<unapplied> unapplied)?"
    r"(?: channel=(?P<channel>\S+))?$")
_QUERY_UNREACHABLE = re.compile(
    r"^QUERY geo=(?P<geo>remote|local) title=" + _Q + r" unreachable reason=(?P<reason>[a-z-]+)"
    r"(?: channel=(?P<channel>\S+))?$")
_SEEN_DISTINCT = re.compile(r"^SEEN distinct=(?P<n>\d+)$")
_ROLE_URL = re.compile(
    r'^ROLE url=(?P<url>\S+) title="(?P<title>[^"]*)" company="(?P<company>[^"]*)" '
    r'location="(?P<location>[^"]*)" posted=(?P<posted>\d{4}-\d{2}-\d{2}|\?)$')
_ROLE_NOURL = re.compile(
    r'^ROLE nourl title="(?P<title>[^"]*)" company="(?P<company>[^"]*)" '
    r'reason=(?P<reason>[a-z-]+)$')


class RolesRefused(ValueError):
    """The ROLES block cannot be accepted. Nothing but one gap is written."""


def _clip(s):
    """A scraped field is DATA: newlines stripped, capped, before it goes into any template."""
    return " ".join(str(s or "").split())[:ROLES_FIELD_CAP]


def parse_roles(text, run_id, surface):
    """`{"header", "queries", "distinct", "roles"}` from the one `ROLES v1` block in `text`.
    Strict and all-or-nothing, like `linkedin_sweep.parse_sweep`: raises `RolesRefused` naming the
    first problem. Prose outside the block is ignored -- the block is the contract."""
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

    expected_bucket = _journal.F_TPR_WIDE if window == "wide" else _journal.F_TPR_DAILY
    queries, roles, distinct, seen_lines = [], [], None, 0
    for i in range(begins[0] + 1, end):
        raw = lines[i].strip()
        if not raw:
            continue
        n = i + 1
        qm = _QUERY_REACHED.match(raw)
        if qm:
            total = None if qm.group("total") == "?" else int(qm.group("total"))
            shown = int(qm.group("shown"))
            if total is not None and shown > total:
                raise RolesRefused("line %d: shown=%d exceeds total=%d: %r" % (n, shown, total, raw))
            q = {"geo": qm.group("geo"), "title": qm.group("title"), "status": "reached",
                 "window": qm.group("win"), "shown": shown, "total": total,
                 "unapplied": bool(qm.group("unapplied")), "channel": qm.group("channel")}
            if surface == "board":
                if q["window"] != "none" or not q["channel"] or q["unapplied"]:
                    raise RolesRefused("line %d: a board QUERY has window=none, a channel= and no "
                                       "`unapplied`: %r" % (n, raw))
            else:
                if q["channel"]:
                    raise RolesRefused("line %d: a LinkedIn QUERY has no channel=: %r" % (n, raw))
                if q["window"] == "none":
                    raise RolesRefused("line %d: a LinkedIn QUERY needs a bucket window "
                                       "(r86400 or r604800), got none: %r" % (n, raw))
            q["window_gap"] = q["unapplied"] or (surface == "linkedin-jobsearch"
                                                 and q["window"] != expected_bucket)
            q["truncated"] = total is not None and total > shown
            queries.append(q)
            continue
        qm = _QUERY_UNREACHABLE.match(raw)
        if qm:
            if qm.group("reason") not in _journal.REASONS:
                raise RolesRefused("line %d: reason=%s is not a journal.REASONS code: %r"
                                   % (n, qm.group("reason"), raw))
            if surface == "board" and not qm.group("channel"):
                raise RolesRefused("line %d: a board QUERY carries a channel=: %r" % (n, raw))
            if surface == "linkedin-jobsearch" and qm.group("channel"):
                raise RolesRefused("line %d: a LinkedIn QUERY has no channel=: %r" % (n, raw))
            queries.append({"geo": qm.group("geo"), "title": qm.group("title"),
                            "status": "unreachable", "reason": qm.group("reason"),
                            "channel": qm.group("channel"), "window_gap": True,
                            "truncated": False})
            continue
        qm = _SEEN_DISTINCT.match(raw)
        if qm:
            seen_lines += 1
            distinct = int(qm.group("n"))
            continue
        rm = _ROLE_URL.match(raw)
        if rm:
            roles.append({"url": rm.group("url"), "title": rm.group("title"),
                          "company": rm.group("company"), "location": rm.group("location"),
                          "posted": rm.group("posted"), "line": n})
            continue
        rm = _ROLE_NOURL.match(raw)
        if rm:
            if rm.group("reason") not in _journal.REASONS:
                raise RolesRefused("line %d: reason=%s is not a journal.REASONS code: %r"
                                   % (n, rm.group("reason"), raw))
            roles.append({"url": None, "title": rm.group("title"), "company": rm.group("company"),
                          "location": "?", "posted": "?", "reason": rm.group("reason"), "line": n})
            continue
        raise RolesRefused("line %d is not a line of the ROLES grammar: %r" % (n, raw))

    if seen_lines != 1:
        raise RolesRefused("the block needs exactly one `SEEN distinct=<n>` line, found %d" % seen_lines)
    if not queries:
        raise RolesRefused("the block has no QUERY line: a pass that searched reports what it "
                           "searched (a query it could not run is an `unreachable` QUERY)")
    if distinct != len(roles):
        raise RolesRefused("SEEN distinct=%d but the block lists %d ROLE line(s): seen must equal "
                           "accounted, in both directions" % (distinct, len(roles)))
    shown_max = max([q["shown"] for q in queries if q["status"] == "reached"] or [0])
    if distinct < shown_max:
        raise RolesRefused("SEEN distinct=%d is below the largest QUERY shown=%d: a query cannot "
                           "show more roles than the pass saw" % (distinct, shown_max))
    canon_seen = {}
    for r in roles:
        c = canonical_job_url(r["url"]) if r["url"] else None
        r["canonical"] = c
        if c:
            if c in canon_seen:
                raise RolesRefused("lines %d and %d are the same posting (%s): list a role once"
                                   % (canon_seen[c], r["line"], c))
            canon_seen[c] = r["line"]
    return {"header": {"window": window, "surface": surface}, "queries": queries,
            "distinct": distinct, "roles": roles}


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


def add_roles(text, run_id, surface, out=print):
    """dev #692 / public #140 (692-2a/b, N5, N6) -- the gate on a pass report. Returns the exit
    code: 0 accepted, 3 refused (ONE `partial-results` gap `jobsearch:roles:<surface>`, nothing
    else written).

    An accepted block resolves EVERY `ROLE` line to exactly one outcome (never a prose count):

      * a role gap -- `ROLE nourl`, or a URL with no canonical form (a LinkedIn URL with no job id
        is never guessed at);
      * known (passed) -- matches an EXCLUDED row (`find_known_match`, so a passed role stays passed);
      * captured -- matches an ACTIVE row whose earliest sighting is this run's date (the runner
        captured it in-pass; its opp id is printed so the write phase screens it);
      * known -- matches any other ACTIVE row;
      * carried -- anything else, including an EXPIRED row's repost: ONE `capture-role` item,
        `ref` the canonical URL, idempotent on `(kind, ref)`.

    then asserts the identity `distinct = captured + known + carried + role_gaps` and writes ONE
    `roles` event. Query-level gaps (unreachable, window not applied, truncated) are filed and
    counted in their own fields. Re-running the same block writes no new row: the queue is
    idempotent, a gap is filed once per run, and an identical `roles` event is not repeated."""
    import journal as _journal
    from pipeline_index import (find_known_match, resolve_company, normalize_company)
    gap_scope = _journal.ROLES_GAP_SCOPE % surface
    try:
        parsed = parse_roles(text, run_id, surface)
    except RolesRefused as e:
        out("⛔ REFUSED — %s. Nothing was recorded except a `partial-results` gap (%s)."
            % (e, gap_scope))
        _file_gap(run_id, gap_scope, "partial-results",
                  "the pass's ROLES block is accepted by deferred.py --add-roles --surface %s"
                  % surface, out)
        return ROLES_EXIT_REFUSED

    opps = _load_store("opportunities.jsonl")
    companies = _load_store("companies.jsonl")
    apps = _load_store("applications.jsonl")
    recs = _journal.read(ROOT)
    starts = [r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id]
    run_date = str(starts[0].get("at"))[:10] if starts else datetime.date.today().isoformat()
    window = parsed["header"]["window"]
    pass_label = "board" if surface == "board" else window
    rows = replay(load())
    counts = {"captured": 0, "known": 0, "carried": 0, "role_gaps": 0}
    resolved_keys, screen_ids = set(), []

    for r in parsed["roles"]:
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
        if hit:
            row, basis, kind = hit
            if kind == "active" and _earliest_seen(row) == run_date:
                counts["captured"] += 1
                screen_ids.append(row.get("id"))
                out("CAPTURED    %s (%s) -- the pass captured it this run" % (row.get("id"), basis))
            else:
                counts["known"] += 1
                out("KNOWN       %s (%s, %s)" % (row.get("id"), basis,
                                                 "passed" if kind == "excluded" else "active"))
            continue
        counts["carried"] += 1
        pending = _pending_by_ref(KIND_CAPTURE, canon, rows)
        if pending:
            out("CARRIED     %s (already pending %s)" % (canon, pending["id"]))
            continue
        what = ("Capture role: %s at %s (%s), seen %s pass: %s"
                % (title, company, loc or "?", pass_label, canon))
        item = _append_item(what, "seen in a pass; not yet captured", (), kind=KIND_CAPTURE,
                            ref=canon)
        rows.append(item)
        out("CARRIED     %s (queued %s)" % (canon, item["id"]))

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

    geos_ok, gaps_window, gaps_trunc = set(), 0, 0
    for q in parsed["queries"]:
        scope = "jobsearch:query:%s:%s%s" % (surface, q["geo"],
                                              (":" + q["channel"]) if q.get("channel") else "")
        if q["status"] == "reached" and not q["window_gap"]:
            geos_ok.add(q["geo"])
        if q["window_gap"]:
            gaps_window += 1
            reason = q.get("reason") or "partial-results"
            out("QUERY GAP  %s (%s): %s" % (scope, reason,
                                            "unreachable" if q["status"] == "unreachable"
                                            else "window not applied"))
            _file_gap(run_id, scope, reason, "the next pass applies its window on this query", out)
        elif q["truncated"]:
            gaps_trunc += 1
            out("QUERY TRUNCATED %s: shown %d of %d" % (scope, q["shown"], q["total"]))
            _file_gap(run_id, scope, "partial-results",
                      "a narrower query shows every result", out)

    ident = counts["captured"] + counts["known"] + counts["carried"] + counts["role_gaps"]
    if ident != parsed["distinct"]:                        # cannot happen; asserted anyway
        out("⛔ the roles identity does not hold (%d != %d); nothing recorded" % (ident, parsed["distinct"]))
        return ROLES_EXIT_REFUSED
    f_tpr = None
    if surface == "linkedin-jobsearch":
        f_tpr = _journal.F_TPR_WIDE if window == "wide" else _journal.F_TPR_DAILY
    event = dict(run_id=run_id, surface=surface, window=window, f_tpr=f_tpr,
                 queries=len(parsed["queries"]), geos_ok=sorted(geos_ok),
                 query_gaps_window=gaps_window, query_gaps_truncated=gaps_trunc,
                 distinct=parsed["distinct"], captured=counts["captured"], known=counts["known"],
                 carried=counts["carried"], role_gaps=counts["role_gaps"])
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
        "+ %d role gap(s) · %d query gap(s) (window) · %d truncated"
        % (run_id, surface, window, parsed["distinct"], counts["captured"], counts["known"],
           counts["carried"], counts["role_gaps"], gaps_window, gaps_trunc))
    for oid in screen_ids:
        out("SCREEN      ~/.claude/jobsearch/run profile.py --minimal-screen %s" % oid)
    return ROLES_EXIT_OK


def settle(out=print):
    """dev #692 / public #140 -- close the script-built items the stores already show done, so
    a carried role that has been captured stops being listed as owed. Returns the closed ids.

    * a `capture-role` item whose `ref` is the canonical URL of any `jd_url` or
      `sightings[].source_url` in `opportunities` (canonical on both sides, N6: a tracking-
      parameter variant of the URL still closes it);
    * a `research-role` item whose opportunity has a non-empty `research_log`.

    A per-role gap closes in `add_roles` itself, the moment a later block resolves the role."""
    from pipeline_index import canonical_job_url
    opps = _load_store("opportunities.jsonl")
    by_id = {o.get("id"): o for o in opps}
    urls = set()
    for o in opps:
        for u in [o.get("jd_url")] + [s.get("source_url") for s in (o.get("sightings") or [])]:
            c = canonical_job_url(u) if u else None
            if c:
                urls.add(c)
    now = datetime.datetime.now()
    closed = []
    for r in replay(load()):
        if r.get("status") != "pending":
            continue
        done = False
        if r.get("kind") == KIND_CAPTURE and r.get("ref"):
            done = (canonical_job_url(r["ref"]) or r["ref"]) in urls
        elif r.get("kind") == KIND_RESEARCH and r.get("ref"):
            done = bool((by_id.get(r["ref"]) or {}).get("research_log"))
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
    ap.add_argument("--add-roles", dest="add_roles", metavar="FILE",
                    help="The gate on a pass report (dev #692 / public #140): FILE is the pass's "
                         "hand-back holding a `ROLES v1` block; needs --run and --surface. Every "
                         "ROLE line resolves to captured / known / carried (one capture-role item "
                         "per role) / a per-role gap, or the whole block is refused (exit 3, one "
                         "partial-results gap, nothing else written). Idempotent.")
    ap.add_argument("--surface", choices=("linkedin-jobsearch", "board"),
                    help="With --add-roles: the surface the block belongs to.")
    ap.add_argument("--settle", action="store_true",
                    help="Close the script-built items the stores already show done: a "
                         "capture-role item whose URL now has an opportunity, a research-role "
                         "item whose opportunity has a research_log (dev #692).")
    ap.add_argument("--attended", action="store_true",
                    help="This run was started with the EXPLICIT attended form (owner decision "
                         "R2): claims may use the research/drafting tokens regardless of the "
                         "posture. NEVER grants `linkedin`. A run is unattended unless it passes "
                         "this; attended is never inferred.")
    ap.add_argument("--run", metavar="ID", default=None,
                    help="With --add: the run this call belongs to. A REFUSED add then leaves a "
                         "`deferred:refused` gap in the run's journal, so a refused carry-forward "
                         "is never lost silently (dev #692).")
    ap.add_argument("--why", metavar="WHY", default="")
    ap.add_argument("--requires", metavar="CAPS", default="",
                    help="Comma-separated capabilities this work NEEDS (e.g. chrome,keychain). "
                         "Routing depends on it: a worker claims only what it can finish.")
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
        return add_roles(text, args.run, args.surface)

    if args.settle:
        settle()
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
    claim_pool = [r for r in pending if r["id"] not in owed_ids]
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
        claim_pool = [r for r in pending if r["id"] not in owed_ids]

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
