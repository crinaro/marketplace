#!/usr/bin/env python3
"""
The LinkedIn reply sweep's two script halves: the WORKLIST it works from, and the verdict on what it
hands back (`record`).

WHY THIS EXISTS (dev #484 / public #109, dev #488 / public #105, dev #481 / public #112)
---------------------------------------------------------------------------------------
Three defects shared one shape: the model was asked to make a judgement a script can make.

* **#488: acceptance was inferred from ABSENCE on a truncated list.** Sent Invitations rendered 10
  of 25; a person missing from it read as "accepted" or "no change". A partial list proves nothing
  about a person beyond the part it showed. `record` is the only thing that turns a hand-back into
  "no change", and it REFUSES that conclusion for any person a surface did not cover to (see
  `covers`): `!! INCOMPLETE COVERAGE`, a `partial-results` gap, no `empty` probe. Acceptance is read
  POSITIVELY from the recency-sorted Connections list. Owner decision 2026-10-03: a routine sweep
  never visits a profile; the degree check is an explicit one-off (`worklist --one-off`).
* **#484 case 3: the runner explored.** It walked every open touch's profile. `worklist` is the
  script-built list the runner works from, and nothing else.
* **#484 case 2: a view that was already happening was thrown away.** A subagent returns only its
  final message, so a page or thread the runner opened exists for the caller only if the hand-back
  carries it. Every view comes back as a `VIEW` line and `record` journals it through the existing
  probe row (`journal.record_probe`), so a later brief cites it instead of dispatching again.
* **#481: a failed pass is still OWED.** `record` closes the owed pass row, and queues one when the
  pass failed, through `deferred.queue_linkedin_pass` (no row while one is pending).

Usage:
    python3 scripts/linkedin_sweep.py worklist --run <id> [--one-off contact:<id>]
    python3 scripts/linkedin_sweep.py record   --run <id> [--one-off contact:<id>] [--file PATH] [--check]

`record` reads the runner's hand-back from `--file` (or stdin). Exit codes (precedence 4 > 2 > 5 > 3 > 0):
    0  every watched person concluded            3  some person NOT concluded (pass still closes)
    2  STRUCTURAL refusal (no block, two blocks, a bad header, a run that is not this call's, no END
       line) or an unreadable --file; no sighting journaled; the raw hand-back is kept (an unreadable
       file cannot be); the owed pass stays owed
    4  the pass FAILED (a reserved first line, or no list surface REACHED, with or without line faults);
       the owed row stands, the raw hand-back is kept when a block was present
    5  RECORDED WITH LINE FAULTS: every readable line is journaled, the owed pass is closed, and each
       faulty line is a gap of its own; do NOT re-dispatch the runner. The raw hand-back is kept.
`record --check` runs the SAME judgement, writes nothing at all, prints each fault and one `verdict:`
line (`verdict: clean` only with exit 0), and exits with the code the real call would.

## One rule, stated once (dev #811 / public #170, dev #812 / public #169)

`handback.py` holds the contract this file shares with `deferred.py --add-roles`: a hand-back block is
refused whole only for a STRUCTURAL fault, every other fault is a LINE fault (the line is dropped, it
is a `partial-results` gap naming the line, its text and the rule, everything else that parsed is
recorded), the raw hand-back is kept whenever a call refuses or records a fault, and `--check` writes
nothing. `record` is `apply(judge(...))`: `judge` is pure and returns a `Verdict`, `apply` is the only
function that writes. Every dropped line gets one taint class (`taint_of`): T1 taints nothing, T2 taints
the contacts it names, T3 taints the block, and a tainted contact or block is NEVER concluded `empty`.

## The JOB SEARCH window rides the same worklist (dev #489 / public #102, dev #692, R5)

A routine worklist also prints one `JOBSEARCH` line: `window=daily f_TPR=r86400 titles=configured`
on an ordinary day and `window=wide f_TPR=r604800 titles=all wide-due-since=<date>` while the
weekly wide re-scan is due, both LinkedIn UI buckets ("Past 24 hours", "Past week") and nothing
computed. The runner takes its `f_TPR`, titles and geographies from that line instead of a
hard-coded `r86400`; what it searched comes back as a `ROLES v1` block that
`deferred.py --add-roles` accepts (it is NOT measured by `record`, which still measures only the
four list surfaces). A one-off worklist carries no `JOBSEARCH` line.

## What closes the owed pass row (dev #481, NAMED CHANGE 2)

`record` closes the owed LinkedIn pass rows ONLY when the SWEEP block has at least one LIST surface
(`inbox`, `requests`, `invitations`, `connections`) REACHED. An all-UNREACHABLE block, with or
without WATCH lines, reached nothing and concluded nothing: it leaves the row pending, queues one
if none is, and exits 4. **JOB SEARCH and NOTIFICATIONS are not measured by `record` and do not
gate closure** — they have their own reporting; a pass that read a list but skipped the bell is
still the pass that was owed. A failed or garbled `record --one-off` hand-back NEVER queues the
daily pass: the one-off runs with the owner present and is not the daily pass.

## The pane rides the block (dev #826 / public #177, jobsearch 0.83.0)

A SWEEP block carries a required `PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>` line.
A hidden Browser pane is not a stalled pane (public #96): the runner reads the harness's own display line,
and when the pane is hidden it reads the lists by text only (HIDDEN MODE). `record` then stores `pane`,
`mode` and `partial` on the pass row and decides what that means, in `_judge_pane`:

* `mode=hidden`: every reached surface is `partial`, a `pane-hidden` gap opens (scope `linkedin:pane-hidden`,
  or `linkedin:chrome-tab-hidden` for the extension) with the user's remedy, and a hidden pass NEVER closes
  one. A hidden pass that reaches a list still closes the owed pass row (the text rows are real rows) and is
  never re-queued;
* `state=displayed` / `not-pane` with `mode=normal` closes that executor's open `pane-hidden` gap;
* `state=unknown` applies the pre-0.83 rule loudly and opens a `pane-unreadable` gap, closed by a pass that
  reads `displayed` or `hidden`;
* no readable line: a block-level fault, `pane: unreported`, every reached surface `partial`;
* a `RENDER STALLED` first line over a block whose PANE line says hidden is a contradiction, not a stall.

THE STATE IS SELF-REPORTED (PARTIAL), and a pane that reads `displayed` but is not painting keeps the
pre-0.83 outcome (UNVERIFIED). One scope per reason, never `linkedin:pane` for the new gaps: that scope
already carries `render-stalled` and `pane-held`, and `journal.record_gap` derives the gap id from (run,
scope) alone, so two reasons on one scope would share an id and one close would close both.

## The grammar (one definition; `agents/linkedin-runner.md` carries it byte-equal, test-enforced)

`SWEEP_GRAMMAR` below. A line inside the block that matches no
form, or breaks a value rule, is a LINE fault (exit 5): it is dropped, printed with its line number and
the rule, filed as a gap, and the rest of the block is recorded. Before 0.82.0 it refused the WHOLE
block (exit 2) and every sighting in it was lost with the dispatch. A `contact:<id>` absent from the
watch set is a line fault that taints the block, `VIEW` included. Principle 4 (a fact a run knows goes
into the queryable store, never narrative; an unparseable value is loud).

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _root import profile_root  # noqa: E402
import deferred  # noqa: E402
import graph as _graph  # noqa: E402
import handback  # noqa: E402     # handback.py: the hand-back contract (dev #811 / #812)
import journal  # noqa: E402

# The four LIST surfaces a reply sweep reads. `notifications` and `degree` are coverage vocabulary
# (journal.LINKEDIN_SWEEP_SURFACES) a SWEEP block may name, but `record` measures neither.
LIST_SURFACES = ("inbox", "requests", "invitations", "connections")

# Whether a surface lists newest-first, so that reading back to a row dated at or before S covers
# everyone since S. `connections` is documented as sortable by Recently added; `inbox` is
# newest-first by construction. ⚠️ UNDETERMINED for `requests` and `invitations` (a probe of one
# read of each, recording no identifiers, settles it): until then their `covers` falls back to
# `shown >= total`, which is the conservative answer either way.
RECENCY_SORTED = {"inbox": True, "connections": True, "requests": False, "invitations": False}

# ⚠️ The in-page position of `requests` is UNDETERMINED (a filter on the messaging page, no
# verified deep link), so it shares the messaging URL and the runner navigates by the UI, as it
# always has. `invitations` is the sent list (verified in reconcile.py's own instructions).
SURFACE_URLS = {
    "inbox": "https://www.linkedin.com/messaging/",
    "requests": "https://www.linkedin.com/messaging/",
    "invitations": "https://www.linkedin.com/mynetwork/invitation-manager/sent/",
    "connections": "https://www.linkedin.com/mynetwork/invite-connect/connections/",
}
POSITIVE_ONLY = frozenset({"invitations"})        # presence means pending; absence proves nothing

OPEN_OUTCOMES = ("awaiting", "accepted")
THREAD_URL_RE = re.compile(r"^https://www\.linkedin\.com/messaging/thread/[^/\s]+/?$")
PROFILE_URL_RE = re.compile(r"^https://www\.linkedin\.com/in/[^/\s]+/?$")

# A hand-back whose FIRST line starts with one of these did not complete a pass. `PANE HELD` is a
# different thing: another run holds the pane and is doing the work, so nothing is queued.
PASS_FAILURES = ("BROWSER UNAVAILABLE", "NOT SIGNED IN", "RENDER STALLED")
PANE_HELD = "PANE HELD"

EXIT_OK, EXIT_REFUSED, EXIT_INCOMPLETE, EXIT_PASS_FAILED, EXIT_LINE_FAULTS = 0, 2, 3, 4, 5

# ⭐ THE GRAMMAR — byte-equal to the fenced copy between `<!-- sweep-grammar:begin -->` and
# `<!-- sweep-grammar:end -->` in plugins/jobsearch/agents/linkedin-runner.md. Edit both in the same
# commit, or `TestSweepGrammarFence` goes red.
SWEEP_GRAMMAR = """\
--- WORKLIST v1 run=<run-id> ---                      (what you are given; you never write one)
SURFACE <token> url=<url> back-to=<YYYY-MM-DD|all|none> [positive-only]
JOBSEARCH window=<daily|wide> f_TPR=<r86400|r604800> titles=<configured|all> geo=<remote[,local]> [wide-due-since=<YYYY-MM-DD|never>]
JOBSEARCH off source=linkedin-jobsearch                              (turned off: run NO job search, record nothing as covered)
WATCH contact:<id> since=<YYYY-MM-DD|?> medium=<linkedin-*|?> name="<display name>" [match=<profile url>]
THREAD contact:<id> url=<messaging thread url>
--- END WORKLIST ---

--- SWEEP v1 run=<run-id> ---                         (what you hand back, in your hand-back file)
PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>
SURFACE <token> REACHED shown=<n> total=<m|?> oldest=<YYYY-MM-DD|?>
SURFACE <token> UNREACHABLE reason=<journal.REASONS code>
SURFACE <token> NOT-ATTEMPTED
SEEN contact:<id> on=<token> state=<accepted|reply|pending> date=<YYYY-MM-DD|?>
VIEW contact:<id> kind=<thread|profile> at=<ISO time> saw=<empty|message:<YYYY-MM-DD>|degree:<1|2|3|pending>>
--- END SWEEP ---"""

_DATE = r"\d{4}-\d{2}-\d{2}"
_SURF_REACHED = re.compile(
    r"^SURFACE (?P<tok>[a-z]+) REACHED shown=(?P<shown>\d+) total=(?P<total>\d+|\?) "
    r"oldest=(?P<oldest>%s|\?)$" % _DATE)
_SURF_UNREACHABLE = re.compile(r"^SURFACE (?P<tok>[a-z]+) UNREACHABLE reason=(?P<reason>[a-z-]+)$")
_SURF_NOT_ATTEMPTED = re.compile(r"^SURFACE (?P<tok>[a-z]+) NOT-ATTEMPTED$")
_SEEN = re.compile(r"^SEEN contact:(?P<id>\S+) on=(?P<on>[a-z]+) "
                   r"state=(?P<state>accepted|reply|pending) date=(?P<date>%s|\?)$" % _DATE)
_VIEW = re.compile(r"^VIEW contact:(?P<id>\S+) kind=(?P<kind>thread|profile) at=(?P<at>\S+) "
                   r"saw=(?P<saw>empty|message:%s|degree:(?:1|2|3|pending))$" % _DATE)
_BEGIN = re.compile(r"^--- SWEEP v1 run=(?P<run>\S+) ---$")
_END = "--- END SWEEP ---"

# ---------------------------------------------------------------------------------------------
# the pane (dev #826 / public #177, jobsearch 0.83.0; design-sweep-misfires.md section 2.4)
# ---------------------------------------------------------------------------------------------
#
# The SWEEP block's required `PANE state=<...> mode=<normal|hidden>` line. `state` is what the runner read
# from the harness (`pane_probe.pane_state`), or `not-pane` for the Chrome extension; `mode` is whether any part
# of the pass ran in HIDDEN MODE (reads by text only, no click). They are separate so that a hidden Chrome tab
# (`state=not-pane mode=hidden`) is never recorded as full coverage. THE STATE IS SELF-REPORTED (PARTIAL): this
# script judges what it is handed, and the hook that would record the harness line itself is a follow-up.
# UNVERIFIED: a pane that reads `displayed` and is not painting (an occluded window, another Space, a sleeping
# display, a locked screen) is reported `displayed mode=normal` and keeps the pre-0.83 outcome.
PANE_LINE_STATES = ("displayed", "hidden", "unknown", "not-pane")
PANE_LINE_MODES = ("normal", "hidden")
_PANE_LINE = re.compile(r"^PANE state=(?P<state>\S+) mode=(?P<mode>\S+)$")

# One scope per REASON, never `linkedin:pane` for all of them. `journal.record_gap` builds the gap id from
# (run, scope) alone and a close is by gap id, so two gaps of different reasons on one scope, opened by one run,
# would share an id and a close of either would close both. `linkedin:pane` already carries `render-stalled` and
# `pane-held` (written by the runner), and a hidden pass must neither be deduped away by them nor close them.
PANE_HIDDEN_SCOPES = {"pane": "linkedin:pane-hidden", "chrome-tab": "linkedin:chrome-tab-hidden"}
PANE_UNREADABLE_SCOPE = "linkedin:pane-unreadable"

# The remedy, worded WITHOUT "this session": a scheduled pass prints it too, and "this session" there would be
# the scheduled session, which the owner cannot put in view (R2-SURF-5).
PANE_REMEDY = {
    "pane": ("Click-dependent LinkedIn work runs only while the Browser pane is shown: run /jobsearch:linkedin "
             "in the desktop app and keep it in view."),
    "chrome-tab": ("Click-dependent LinkedIn work runs only while the browser tab is shown: run "
                   "/jobsearch:linkedin with the Chrome window open and in view."),
}
PANE_HIDDEN_CLOSES_WHEN = {
    "pane": ("a LinkedIn pass runs with the Browser pane shown (PANE state=displayed mode=normal): run "
             "/jobsearch:linkedin in the desktop app and keep it in view"),
    "chrome-tab": ("a LinkedIn pass runs on the Chrome extension with the tab shown (PANE state=not-pane "
                   "mode=normal): run /jobsearch:linkedin with the Chrome window open and in view"),
}
PANE_UNREADABLE_CLOSES_WHEN = ("a LinkedIn pass reads the Browser pane's display line (PANE state=displayed or "
                               "hidden). If every pass reads unknown, the harness wording has changed: report it")


def _executor(state):
    """`pane` (the in-app Browser pane) or `chrome-tab` (the extension, `state=not-pane`)."""
    return "chrome-tab" if state == "not-pane" else "pane"


def close_pane_gaps(root, scope, reason, at=None, out=print):
    """The ONE writer that closes a pane gap: every OPEN gap with exactly this `scope` AND this `reason` gets a
    `gap-closed` row. Keyed on both, so a gap of another reason (`render-stalled`, `pane-held`) is never closed
    by a pane pass that did not examine it. Returns the closed gap ids; a journal that cannot be written is
    reported through `out`, never swallowed."""
    closed = []
    at = at or journal.now_iso()
    try:
        for g in journal.open_gaps(journal.read(root)):
            if g.get("scope") == scope and g.get("reason") == reason:
                journal.append(root, {"event": "gap-closed", "gap_id": g["gap_id"], "at": at})
                closed.append(g["gap_id"])
                out("GAP CLOSED %s (%s)" % (scope, reason))
    except journal.JournalError as e:
        out("⚠️ could not close the gap %s (%s)" % (scope, e))
    return closed

# Which (state, surface) pairs are meaningful. Anything else is a hand-back this parser cannot
# read, and refusing it is the point.
_STATE_SURFACES = {"accepted": ("connections",), "reply": ("inbox", "requests", "invitations"),
                   "pending": ("invitations",)}


class SweepRefused(ValueError):
    """The input cannot be read or does not belong to this run. Nothing is journaled."""


# ---------------------------------------------------------------------------------------------
# the watch set: who the sweep is about, derived from the stores, never from the model
# ---------------------------------------------------------------------------------------------

def _is_date(s):
    return bool(s) and bool(re.match(r"^%s$" % _DATE, str(s)[:10])) and len(str(s)) >= 10


def _person(g, pid):
    try:
        return g.resolve_person(pid)
    except _graph.MergeCycleError:
        raise SweepRefused("people: a merge cycle at %r; run validate_data.py" % pid)


def watch_set(root):
    """`{person_id: {"name", "linkedin", "since", "touches": [row...], "note_touch": bool}}` for
    every person with an OPEN LinkedIn touch (medium `linkedin-*`, outcome awaiting/accepted),
    merges followed. `since` (S) is the date of the person's newest open outbound touch, or None
    when no touch carries a readable date (then no `oldest` can ever cover them)."""
    g = _graph.Graph(os.path.join(root, "data"))
    out = {}
    all_by_person = {}
    for t in g.stores["touches"]:
        person = _person(g, t.get("person_id"))
        pid = person["id"] if person else t.get("person_id")
        if pid:
            all_by_person.setdefault(pid, []).append(t)
    for pid, rows in all_by_person.items():
        open_rows = [t for t in rows if str(t.get("medium") or "").startswith("linkedin-")
                     and t.get("outcome") in OPEN_OUTCOMES]
        if not open_rows:
            continue
        person = g.by_id["people"].get(pid) or {}
        dates = [str(t["date"])[:10] for t in open_rows if _is_date(t.get("date"))]
        # A touch's `message_ref` is a messages.id (validate_data refuses one that does not
        # resolve), never a URL itself; the thread URL is that message's own `source`, when its
        # source IS one. Only then is there a thread the runner may open without a profile walk.
        threads = []
        for t in open_rows:
            src = str((g.by_id["messages"].get(t.get("message_ref")) or {}).get("source") or "")
            if THREAD_URL_RE.match(src) and src not in threads:
                threads.append(src)
        out[pid] = {
            "threads": threads,
            "name": person.get("name") or open_rows[0].get("to") or pid,
            "linkedin": person.get("linkedin"),
            "since": max(dates) if dates else None,
            "touches": sorted(open_rows, key=lambda t: (str(t.get("date") or ""), t.get("id") or "")),
            "note_touch": any(t.get("medium") == "linkedin-connection-note" for t in rows),
        }
    return out


def one_off_watch(root, token):
    """The watch set of a one-off: exactly the person named, whatever their records say. A person
    with no LinkedIn touch at all is the point of a one-off (someone the profile has no LinkedIn
    contact with yet)."""
    pid = _contact_id(token)
    g = _graph.Graph(os.path.join(root, "data"))
    person = _person(g, pid)
    if person is None:
        raise SweepRefused("--one-off %s: no such person in people.jsonl" % token)
    pid = person["id"]
    full = watch_set(root)
    if pid in full:
        return {pid: full[pid]}
    return {pid: {"name": person.get("name") or pid, "linkedin": person.get("linkedin"),
                  "since": None, "touches": [], "note_touch": False, "threads": []}}


def _contact_id(token):
    m = re.match(r"^contact:(\S+)$", token or "")
    if not m:
        raise SweepRefused("%r is not a contact:<id> token" % token)
    return m.group(1)


# ---------------------------------------------------------------------------------------------
# worklist
# ---------------------------------------------------------------------------------------------

def _q(s):
    return re.sub(r'[\r\n"]+', " ", str(s)).strip()


def _normalise_profile_url(raw):
    raw = (raw or "").strip()
    if raw.startswith("linkedin.com/") or raw.startswith("www.linkedin.com/"):
        raw = "https://" + (raw if raw.startswith("www.") else "www." + raw)
    return raw if PROFILE_URL_RE.match(raw) else None


JOBSEARCH_CHANNEL = "linkedin-jobsearch"       # the channel id every LinkedIn job-search sighting is written with


def job_search_is_off(root):
    """dev #774 (design-source-catalog.md section 4.1): True when the user turned the LinkedIn job search off, i.e. the
    `linkedin-jobsearch` channel row is `relationship_status: retired` -- the same off bit `alert_sweep.py`,
    `channels_due.py` and `portfolio_boards.py` already honour for every other channel, written by
    `record.py source off linkedin-jobs`. A MISSING row, or one that is not retired, is NOT off (an install older than
    0.76.0 never had to hold the row, and its search ran). A channels store that cannot be read is not read as off
    either: `validate_data.py` reports the unreadable store at run start; an off switch nobody can read must not
    silently turn a search off."""
    path = os.path.join(root, "data", "channels.jsonl")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id") == JOBSEARCH_CHANNEL:
                    return row.get("relationship_status") == "retired"
    except OSError:
        return False
    return False


def jobsearch_line(root, now=None):
    """dev #489 / public #102 + #692 (R5) -- the `JOBSEARCH` line of the worklist: which LinkedIn
    job-search window THIS pass runs, printed by a script so the runner never hard-codes one.
    `window=wide f_TPR=r604800 titles=all` while the weekly wide re-scan is due, otherwise
    `window=daily f_TPR=r86400 titles=configured`. Only LinkedIn's own UI buckets exist (R5): there
    is no computed window. The geographies are computed here from config (`remote`, plus `local`
    when `geography.commute_anchors` is non-empty), never self-reported by the runner. Wide is due
    until a LinkedIn `roles` event with `window=wide` covered EVERY geography (`journal.
    wide_satisfied_at`); a board event or a refused pass never satisfies it."""
    import json
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    if job_search_is_off(root):
        return "JOBSEARCH off source=%s" % JOBSEARCH_CHANNEL
    geos = journal.jobsearch_geos(cfg)
    w = journal.jobsearch_window(now or journal.now_iso(), journal.read(root), geos)
    line = "JOBSEARCH window=%s f_TPR=%s titles=%s geo=%s" % (
        w["window"], w["f_tpr"], w["titles"], ",".join(geos))
    if w["due_since"]:
        line += " wide-due-since=%s" % w["due_since"]
    return line


def build_worklist(root, run_id, one_off=None):
    """The WORKLIST block, as text. Routine mode holds NO profile URL (dev #488, owner decision
    2026-10-03): the runner reads the recency-sorted lists and, for a person a thread URL is on
    record for, that thread. A one-off holds exactly one: the person's profile."""
    lines = ["--- WORKLIST v1 run=%s ---" % run_id]
    if one_off:
        watch = one_off_watch(root, one_off)
        (pid, w), = watch.items()
        url = _normalise_profile_url(w["linkedin"])
        if not url:
            raise SweepRefused("--one-off %s: people.linkedin holds no profile URL "
                               "(https://www.linkedin.com/in/...), so there is no profile to visit"
                               % one_off)
        for tok in ("requests", "invitations"):
            lines.append("SURFACE %s url=%s back-to=all%s"
                         % (tok, SURFACE_URLS[tok], " positive-only" if tok in POSITIVE_ONLY else ""))
        newest = w["touches"][-1] if w["touches"] else {}
        lines.append('WATCH contact:%s since=%s medium=%s name="%s" match=%s'
                     % (pid, w["since"] or "?", newest.get("medium") or "?", _q(w["name"]), url))
    else:
        watch = watch_set(root)
        sinces = [w["since"] for w in watch.values()]
        if not watch:
            back_to = "none"
        elif any(s is None for s in sinces):
            back_to = "all"
        else:
            back_to = min(sinces)
        for tok in LIST_SURFACES:
            lines.append("SURFACE %s url=%s back-to=%s%s"
                         % (tok, SURFACE_URLS[tok], back_to,
                            " positive-only" if tok in POSITIVE_ONLY else ""))
        lines.append(jobsearch_line(root))
        for pid in sorted(watch):
            w = watch[pid]
            for t in w["touches"]:
                lines.append('WATCH contact:%s since=%s medium=%s name="%s"'
                             % (pid, str(t.get("date"))[:10] if _is_date(t.get("date")) else "?",
                                t.get("medium"), _q(w["name"])))
        for pid in sorted(watch):
            for url in watch[pid]["threads"]:
                lines.append("THREAD contact:%s url=%s" % (pid, url))
    lines.append("--- END WORKLIST ---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# parsing a hand-back: a STRUCTURAL fault refuses, every other fault is a LINE fault
# (dev #812 / public #169; the rule is handback.py's, shared with deferred.py --add-roles)
# ---------------------------------------------------------------------------------------------

SWEEP_LINE_GAP_SCOPE = "linkedin:sweep-line:%s"            # (<line>:<h8> | block:<check>)
ONE_OFF_LINE_GAP_SCOPE = "linkedin:sweep-line-oneoff:%s"   # a family of its own: a one-off never closes the daily pass's gaps
OUTSIDE_BLOCK = "outside-block"

# The key set of each line form, for T2's "no free text" condition (N1, condition 3).
_FORM_KEYS = {"SEEN": ("on", "state", "date"), "VIEW": ("kind", "at", "saw")}
# A line that LOOKS like the sweep grammar. `SEEN distinct=<n>` is the ROLES block's own line (the
# runner writes both blocks into one file), so it is not sweep-shaped.
_GRAMMAR_SHAPED = re.compile(r"^(SEEN|VIEW|SURFACE) ")
_ROLES_SEEN = re.compile(r"^SEEN distinct=\d+$")


def named(line):
    """Every token that follows `contact:` on the line, split on `,` (so a joined pair counts as two).
    An empty `contact:` yields one empty token, which is in no watch set."""
    out = []
    for m in re.finditer(r"contact:(\S*)", line):
        out.extend(m.group(1).split(","))
    return out


def _needles(pid, name):
    """What a remainder must not contain for a person: their id, their display name, and each word of
    the name of three or more characters, compared as case-insensitive substrings."""
    out = [str(pid).lower()]
    full = " ".join(str(name or "").split()).lower()
    if full:
        out.append(full)
        out += [w for w in full.split() if len(w) >= 3]
    return [x for x in out if x]


def taint_of(raw, watch):
    """⭐ dev #812 / public #169 (design §15 N1) -- what a DROPPED line that could have carried a fact
    about a watched person does to the verdict. Returns `("T2", {ids})` when the line taints exactly
    those contacts, else `("T3", None)`, which taints the whole block.

    T2 needs ALL FOUR to hold; anything else is T3:
      1. a recognised prefix: the line starts `SEEN contact:` or `VIEW contact:`;
      2. watched names only: `named(line)` is non-empty and every element is exactly in the watch set;
      3. no free text: after the first token and the `contact:<ids>` token, every remaining token is
         `<key>=<value>` with the key in the form's key set, no key twice (a `;`, `also` or a name fails);
      4. the remainder names no one: with every `contact:<token>` removed, the line contains no watch-set
         id and no watch-set name (case-insensitive substrings; each word of three or more characters of
         a name is also checked alone).

    THE INVARIANT. A dropped line inside the block can withhold a fact about watched person P from
    `judge` in exactly two ways: by naming P, or by being free text. Naming P as `contact:P` is T2 for P
    or T3; naming P anywhere else is T3 (4); free text is T3 (3); a non-prefixed line is T3 (1). A full
    SURFACE line (T1, decided by the caller) can only remove coverage. STATED RESIDUAL: a person referred
    to only inside a `key=value` value, by something that is neither their id nor any word of their name
    (for example `state=her-colleague`), is outside the rule; the grammar ties a value to the line's own
    `contact:`, and a fuzzy rule would need its own proof."""
    if not (raw.startswith("SEEN contact:") or raw.startswith("VIEW contact:")):       # 1
        return "T3", None
    names = named(raw)
    if not names or any(n not in watch for n in names):                                 # 2
        return "T3", None
    toks = raw.split()
    keys, used = _FORM_KEYS[toks[0]], set()
    for tok in toks[2:]:                                                                # 3
        key, eq, val = tok.partition("=")
        if not eq or not val or key not in keys or key in used:
            return "T3", None
        used.add(key)
    rest = re.sub(r"contact:\S*", "", raw).lower()                                      # 4
    for pid, w in watch.items():
        if any(needle in rest for needle in _needles(pid, w.get("name"))):
            return "T3", None
    return "T2", set(names)


def _h8(raw):
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def parse_sweep(text, run_id, watch):
    """`{"surfaces", "seen", "views", "dropped"}` from the one SWEEP block in `text`.

    ⭐ TWO KINDS OF FAULT (dev #812 / public #169, handback.py). A STRUCTURAL fault -- no block, two
    blocks, a header that does not parse, a `run=` that is not this call's, no END line -- raises
    `SweepRefused` naming it: without those nothing says which lines belong to this call. EVERY OTHER
    fault is a LINE fault: the line is dropped and RETURNED in `dropped` as `(line number, text, rule,
    class, names)` where class is `T1` (taints nothing), `T2` (taints `names`) or `T3` (taints the
    block), never raised. A dropped line used to refuse the whole block and lose every sighting in it.
    Prose outside the block is ignored EXCEPT a line that starts `SEEN `, `VIEW ` or `SURFACE `, which
    is a T3 line fault with the rule `outside-block` (N12). T1 is a line that matched the SURFACE form
    in FULL and failed a value check (the surface is then unreported, so it covers nobody); a line that
    only STARTS `SURFACE ` fits no form and goes to `taint_of`."""
    lines = text.splitlines()
    begins = [i for i, ln in enumerate(lines) if ln.startswith("--- SWEEP")]
    if not begins:
        raise SweepRefused("no `--- SWEEP v1 run=%s ---` block in the hand-back" % run_id)
    if len(begins) > 1:
        raise SweepRefused("more than one SWEEP block in the hand-back (lines %s)"
                           % ", ".join(str(i + 1) for i in begins))
    m = _BEGIN.match(lines[begins[0]].strip())
    if not m:
        raise SweepRefused("line %d: %r is not a `--- SWEEP v1 run=<run-id> ---` header"
                           % (begins[0] + 1, lines[begins[0]]))
    if m.group("run") != run_id:
        raise SweepRefused("the block says run=%s but this record is for --run %s"
                           % (m.group("run"), run_id))
    try:
        end = next(i for i in range(begins[0] + 1, len(lines)) if lines[i].strip() == _END)
    except StopIteration:
        raise SweepRefused("the SWEEP block has no `%s` line" % _END)

    surfaces, seen, views, dropped = {}, [], [], []
    panes, pane_shaped = [], False      # every well-formed PANE line; whether any PANE-shaped line was seen
    surface_line = {}                   # token -> (line number, text) of its first report
    doubled = set()                     # tokens reported more than once: every report is dropped

    def drop(n, raw, rule, cls, names=None):
        dropped.append((n, raw, rule, cls, names or set()))

    def classify(n, raw, rule):
        cls, names = taint_of(raw, watch)
        drop(n, raw, rule, cls, names)

    def put_surface(tok, n, raw, info):
        if tok not in journal.LINKEDIN_SWEEP_SURFACES:
            drop(n, raw, "%r is not a surface token (%s)"
                 % (tok, ", ".join(sorted(journal.LINKEDIN_SWEEP_SURFACES))), "T1")
            return
        rule = "surface %s is reported twice (both lines dropped)" % tok
        if tok in doubled:
            drop(n, raw, rule, "T1")
            return
        if tok in surfaces:
            first_n, first_raw = surface_line[tok]
            del surfaces[tok]
            doubled.add(tok)
            drop(first_n, first_raw, rule, "T1")
            drop(n, raw, rule, "T1")
            return
        surfaces[tok] = info
        surface_line[tok] = (n, raw)

    for i in range(begins[0] + 1, end):
        raw = lines[i].strip()
        if not raw:
            continue
        n = i + 1
        if raw.startswith("PANE "):
            # dev #826 / public #177: the pane line names no person, so a bad one is T1 (taints nothing)
            pane_shaped = True
            pm = _PANE_LINE.match(raw)
            if not pm:
                drop(n, raw, "not a `PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>` line",
                     "T1")
            elif pm.group("state") not in PANE_LINE_STATES:
                drop(n, raw, "PANE state=%s is not one of %s"
                     % (pm.group("state"), "|".join(PANE_LINE_STATES)), "T1")
            elif pm.group("mode") not in PANE_LINE_MODES:
                drop(n, raw, "PANE mode=%s is not one of %s"
                     % (pm.group("mode"), "|".join(PANE_LINE_MODES)), "T1")
            else:
                panes.append((n, raw, pm.group("state"), pm.group("mode")))
            continue
        sm = _SURF_REACHED.match(raw)
        if sm:
            shown, total = int(sm.group("shown")), sm.group("total")
            total = None if total == "?" else int(total)
            if total is not None and shown > total:
                drop(n, raw, "shown=%d exceeds total=%d" % (shown, total), "T1")
                continue
            put_surface(sm.group("tok"), n, raw, {
                "status": "REACHED", "shown": shown, "total": total,
                "oldest": None if sm.group("oldest") == "?" else sm.group("oldest")})
            continue
        sm = _SURF_UNREACHABLE.match(raw)
        if sm:
            if sm.group("reason") not in journal.REASONS:
                drop(n, raw, "reason=%s is not a journal.REASONS code" % sm.group("reason"), "T1")
                continue
            put_surface(sm.group("tok"), n, raw,
                        {"status": "UNREACHABLE", "reason": sm.group("reason")})
            continue
        sm = _SURF_NOT_ATTEMPTED.match(raw)
        if sm:
            put_surface(sm.group("tok"), n, raw, {"status": "NOT-ATTEMPTED"})
            continue
        sm = _SEEN.match(raw)
        if sm:
            state, on, d = sm.group("state"), sm.group("on"), sm.group("date")
            if on not in _STATE_SURFACES[state]:
                classify(n, raw, "state=%s is not read on %s" % (state, on))
                continue
            if state == "reply" and d == "?":
                classify(n, raw, "a reply needs its date (it is journaled as thread:<date>)")
                continue
            if sm.group("id") not in watch:
                drop(n, raw, "contact:%s is not in this sweep's watch set (an unwatched person's "
                             "sighting is never recorded)" % sm.group("id"), "T3")
                continue
            seen.append({"id": sm.group("id"), "on": on, "state": state,
                         "date": None if d == "?" else d, "line": n, "raw": raw})
            continue
        sm = _VIEW.match(raw)
        if sm:
            kind, saw = sm.group("kind"), sm.group("saw")
            if (kind == "thread") != (saw == "empty" or saw.startswith("message:")):
                classify(n, raw, "a %s view cannot see %r" % (kind, saw))
                continue
            if journal._parse_iso(sm.group("at")) is None:
                classify(n, raw, "at=%s is not an ISO time" % sm.group("at"))
                continue
            if sm.group("id") not in watch:
                drop(n, raw, "contact:%s is not in this sweep's watch set (an unwatched person's "
                             "sighting is never recorded)" % sm.group("id"), "T3")
                continue
            views.append({"id": sm.group("id"), "kind": kind, "at": sm.group("at"),
                          "saw": saw, "line": n})
            continue
        classify(n, raw, "not a line of the SWEEP grammar")

    kept_seen = []
    for s in seen:
        info = surfaces.get(s["on"])
        if not info or info["status"] != "REACHED":
            classify(s["line"], s["raw"], "SEEN on=%s but that surface is not reported REACHED"
                     % s["on"])
        else:
            kept_seen.append(s)

    # N12 -- a grammar-shaped line outside the block is judged by nobody, so it may hide a fact.
    for i, ln in enumerate(lines):
        if begins[0] <= i <= end:
            continue
        raw = ln.strip()
        if _GRAMMAR_SHAPED.match(raw) and not _ROLES_SEEN.match(raw):
            drop(i + 1, raw, "%s: a SEEN, VIEW or SURFACE line outside the SWEEP block is judged by "
                             "nobody, so it may hold a fact" % OUTSIDE_BLOCK, "T3")
    # dev #826 / public #177 -- the PANE line. Exactly one well-formed line is the pane account. Two are
    # contradictory, so BOTH are dropped (the SURFACE rule); a missing line is a block-level fault the caller
    # files (`pane_missing`); a malformed one is already dropped above. A hidden state claimed with mode=normal
    # contradicts itself: it is dropped as a fault and the pass is recorded as the hidden-mode pass it was.
    pane = None
    if len(panes) > 1:
        for pn, praw, _s, _m in panes:
            drop(pn, praw, "PANE is reported twice (all PANE lines dropped)", "T1")
    elif panes:
        pn, praw, state, mode = panes[0]
        pane = {"state": state, "mode": mode}
        if state == "hidden" and mode == "normal":
            drop(pn, praw, "PANE state=hidden requires mode=hidden (a hidden pane is read without clicks); "
                           "recorded as mode=hidden", "T1")
            pane["mode"] = "hidden"
    dropped.sort(key=lambda d: d[0])
    return {"surfaces": surfaces, "seen": kept_seen, "views": views, "dropped": dropped,
            "pane": pane, "pane_missing": not pane_shaped}


# ---------------------------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------------------------

def covers(surface, token, since):
    """⭐ dev #488 / public #105 — THE gate. Does `surface` (a parsed SURFACE entry, or None for a
    surface the hand-back never mentioned) cover a person whose newest open send is dated
    `since`? Only when it was REACHED and EITHER it listed everything it holds (`shown >= total`,
    total known) OR it is recency-sorted and was read back to a row dated at or before `since`.
    An UNREACHABLE, NOT-ATTEMPTED or absent surface covers nobody; neither does a partial list
    whose `oldest` is newer than `since`. A partial result is a first-class result, never a
    negative (GitHub Search's `incomplete_results`, but this one REFUSES)."""
    if not surface or surface.get("status") != "REACHED":
        return False
    total, shown = surface.get("total"), surface.get("shown")
    if total is not None and shown is not None and shown >= total:
        return True
    oldest = surface.get("oldest")
    return bool(RECENCY_SORTED.get(token) and oldest and since and oldest <= since)


def _slot_gaps(pid, w, surfaces, thread_viewed, profile_viewed):
    """The surfaces whose slot is NOT satisfied for a person with no sighting (§3.2). `[]` means
    all four slots are covered and `empty` may be concluded."""
    s = w["since"]
    missing = []
    if not (covers(surfaces.get("inbox"), "inbox", s) or pid in thread_viewed):
        missing.append("inbox")
    if not covers(surfaces.get("requests"), "requests", s):
        missing.append("requests")
    if not (covers(surfaces.get("invitations"), "invitations", s) or not w["note_touch"]):
        missing.append("invitations")
    if not (covers(surfaces.get("connections"), "connections", s) or pid in profile_viewed):
        missing.append("connections")
    return missing


class Verdict(object):
    """What `judge` decided, as data. `apply` is the only thing that writes; `--check` prints `lines`
    and the `verdict:` line and never calls it. Fields: `name` (one of `journal.RECORD_VERDICTS`),
    `exit`, `detail` (the reason, for a `refused` / `pass-failed` verdict line), `faults` (a list of
    `handback.Fault`), `lines` (what to print, in order), `probes` (`[(pid, result)]` to journal),
    `gaps` (`[(scope, reason, closes_when)]`, the INCOMPLETE COVERAGE gaps), `owed` (`"close"` |
    `"queue"` | `None`: what to do to the owed pass row), `keep` (copy the raw hand-back), `judged`
    (the block's lines were judged, so stale line gaps may close), `reached` / `unreachable` /
    `not_attempted` (the parsed SURFACE statuses), `concluded` / `not_concluded`, `one_off`,
    `not_measured` (print the NOT MEASURED line) and `summary` (print the SWEEP RECORDED line). dev #826:
    `pane` / `mode` / `partial` (the pass row's account of the Browser pane) and `pane_actions` (the pane
    gaps to open or close)."""

    def __init__(self, one_off=False):
        self.name = None
        self.exit = None
        self.detail = None
        self.faults = []
        self.lines = []
        self.probes = []
        self.gaps = []
        self.owed = None
        self.keep = False
        self.judged = False
        self.reached = []
        self.unreachable = []
        self.not_attempted = []
        self.concluded = 0
        self.not_concluded = 0
        self.one_off = one_off
        self.not_measured = False
        self.summary = False
        # dev #826 / public #177: the pane account of a judged block (None until a block is parsed), and the
        # gap writes it implies: [("open"|"close", scope, reason, closes_when)], run by `apply` only.
        self.pane = None
        self.mode = None
        self.partial = []
        self.pane_actions = []

    def verdict_line(self):
        """The one `verdict:` line (§3.4), through `handback.verdict_line`. `verdict: clean` is
        returned only for exit 0."""
        n = len(self.faults)
        if self.name == "clean":
            return handback.verdict_line("clean")
        if self.name == "incomplete":
            return handback.verdict_line("incomplete", detail=self.not_concluded)
        if self.name == "line-faults":
            return handback.verdict_line("line-faults", n, detail=self.not_concluded)
        if self.name == "refused":
            return handback.verdict_line("refused", detail=self.detail)
        if self.name == "pass-failed":
            return handback.verdict_line("pass-failed", detail=self.detail)
        return handback.verdict_line("pane-held")


def _block_says_hidden(lines):
    """True when a well-formed `PANE` line in the hand-back says `state=hidden` or `mode=hidden`. Used
    only to refuse a `RENDER STALLED` first line that contradicts it (a hidden pane is not a stalled pane)."""
    for ln in lines:
        m = _PANE_LINE.match(ln.strip())
        if m and "hidden" in (m.group("state"), m.group("mode")):
            return True
    return False


def _judge_pane(v, pane, surfaces):
    """dev #826 / public #177 (design-sweep-misfires.md section 2.4) -- what a block's `PANE` line means:
    fill `v.pane`, `v.mode`, `v.partial`, print the loud lines, and list the pane gaps to open or close.
    PURE, like `judge`: it writes nothing (`apply` runs `v.pane_actions`).

      * `mode=hidden` (any state): every reached surface is `partial` (read by text from a pane that was not
        painting), one `pane-hidden` gap opens on the EXECUTOR's scope, and a hidden pass NEVER closes one;
      * `mode=normal` with `state` `displayed` / `not-pane`: closes that executor's open `pane-hidden` gap;
      * `state=unknown`: the pre-0.83 rule applied. A `!!` line and a `pane-unreadable` gap say so, and the gap
        stays open until a pass reads one of the two pinned literals;
      * no readable line: `pane` / `mode` are `unreported` and every reached surface is `partial`. A missing
        line is not evidence of a hidden pane, so no pane gap opens or closes (the block fault is the signal).
    `covers()` is untouched: rows read by text from a non-painting pane are real rows, and a lazily-loaded
    list only ever makes `covers` refuse more."""
    if pane is None:
        v.pane = v.mode = "unreported"
        v.partial = sorted(v.reached)
        return
    state, mode = pane["state"], pane["mode"]
    v.pane, v.mode = state, mode
    ex = _executor(state)
    if mode == "hidden":
        v.partial = sorted(v.reached)
        what = "pane" if ex == "pane" else "browser tab"
        for tok in v.partial:
            info = surfaces[tok]
            total = "?" if info.get("total") is None else info["total"]
            v.lines.append("!! PARTIAL linkedin:%s — read from a %s that was not painting (shown %d of %s). %s"
                           % (tok, what, info["shown"], total, PANE_REMEDY[ex]))
        if not v.partial:
            v.lines.append("!! PANE %s mode=hidden — nothing was read from a %s that was not painting. %s"
                           % (state, what, PANE_REMEDY[ex]))
        v.pane_actions.append(("open", PANE_HIDDEN_SCOPES[ex], "pane-hidden", PANE_HIDDEN_CLOSES_WHEN[ex]))
    elif state in ("displayed", "not-pane"):
        v.pane_actions.append(("close", PANE_HIDDEN_SCOPES[ex], "pane-hidden", None))
    if state == "unknown":
        v.lines.append("!! PANE unknown — the Browser pane's display line could not be read; the pre-0.83 "
                       "stall rule applied. A pane-unreadable gap stays open until a pass reads it. Report "
                       "this: the harness wording may have changed.")
        v.pane_actions.append(("open", PANE_UNREADABLE_SCOPE, "pane-unreadable", PANE_UNREADABLE_CLOSES_WHEN))
    elif state in ("displayed", "hidden"):
        v.pane_actions.append(("close", PANE_UNREADABLE_SCOPE, "pane-unreadable", None))


def judge(text, run_id, watch, one_off=False, recs=None):
    """⭐ dev #812 / public #169 -- PURE: judge one hand-back and return a `Verdict`; write nothing.
    `recs` is the journal's records (for the gaps already open). Precedence, highest first: 4 > 2 > 5 >
    3 > 0. A reserved first line is a pass outcome the runner meant to report and wins over a refusal;
    a structural fault refuses before any line is judged; line faults beat an uncovered person (5 over
    3); line faults with NO list surface reached are a failed pass (4, N13), because nothing was
    concluded and the pass is still owed."""
    v = Verdict(one_off)
    lines = text.splitlines()
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    has_block = any(ln.startswith("--- SWEEP") for ln in lines)

    if first.startswith(PANE_HELD):
        v.name, v.exit, v.keep = "pane-held", EXIT_PASS_FAILED, has_block
        v.lines.append("PANE HELD — another run holds the pane and is doing this work; nothing "
                       "queued, no sighting recorded.")
        return v
    stall_contradiction = None
    for token in PASS_FAILURES:
        if first.startswith(token):
            if token == "RENDER STALLED" and has_block and _block_says_hidden(lines):
                # dev #826 / public #177 (P4): a hidden pane is not a stalled pane. The block is judged as the
                # hidden-mode pass it was; the contradiction is a loud, block-tainting fault, and no stall is
                # recorded or queued.
                stall_contradiction = first
                break
            v.name, v.exit, v.keep, v.owed = "pass-failed", EXIT_PASS_FAILED, has_block, "queue"
            v.detail = token.lower()
            v.lines.append("PASS FAILED — %s (the hand-back's first line). The block, if any, was "
                           "not read." % token)
            return v

    try:
        parsed = parse_sweep(text, run_id, watch)
    except SweepRefused as e:
        v.name, v.exit, v.keep, v.owed, v.detail = "refused", EXIT_REFUSED, True, "queue", str(e)
        v.lines.append("⛔ REFUSED — %s. No sighting or conclusion was journaled." % e)
        return v

    v.judged = True
    surfaces, seen, views = parsed["surfaces"], parsed["seen"], parsed["views"]
    tainted, block_taint = set(), False
    for n, raw, rule, cls, names in parsed["dropped"]:
        v.faults.append(handback.Fault(n, " ".join(raw.split())[:200], "%d:%s" % (n, _h8(raw)), rule))
        if cls == "T2":
            tainted |= names
        elif cls == "T3":
            block_taint = True
    pane = parsed["pane"]
    if stall_contradiction:
        n1 = next(i for i, ln in enumerate(lines) if ln.strip()) + 1
        v.faults.append(handback.Fault(
            n1, " ".join(stall_contradiction.split())[:200], "%d:%s" % (n1, _h8(stall_contradiction)),
            "the first line says RENDER STALLED but the PANE line says the pane was hidden: a hidden pane is "
            "not a stalled pane, so no stall is recorded and nothing is queued; the pass is recorded as the "
            "hidden-mode pass it was"))
        block_taint = True
    if pane is None and parsed["pane_missing"]:
        # a missing line is not evidence of a hidden pane: it is a block-level fault, and the pass row says
        # `unreported` rather than guessing a state
        v.faults.append(handback.Fault(
            None, None, "block:pane",
            "the SWEEP block has no `PANE state=<displayed|hidden|unknown|not-pane> mode=<normal|hidden>` line: "
            "every reached surface is recorded partial, because nothing says the pane was painting"))
    v.lines += [handback.describe(f) for f in v.faults]
    for tok, info in sorted(surfaces.items()):
        {"REACHED": v.reached, "UNREACHABLE": v.unreachable,
         "NOT-ATTEMPTED": v.not_attempted}[info["status"]].append(tok)
    _judge_pane(v, pane, surfaces)

    out = v.lines
    exit_incomplete = False
    incomplete = {}                      # surface token -> [(person id, since)]
    seen_by = {}
    for s in seen:
        seen_by.setdefault(s["id"], []).append(s)
    views_by = {}
    for vw in views:
        views_by.setdefault(vw["id"], []).append(vw)

    for pid in sorted(watch):
        w = watch[pid]
        mine, vws = seen_by.get(pid, []), views_by.get(pid, [])
        accepted = [s for s in mine if s["state"] == "accepted"]
        accepted_view = [x for x in vws if x["kind"] == "profile" and x["saw"] == "degree:1"]
        reply_dates = [s["date"] for s in mine if s["state"] == "reply"]
        reply_dates += [x["saw"][len("message:"):] for x in vws
                        if x["kind"] == "thread" and x["saw"].startswith("message:")]
        sighting = False
        for x in vws:                                # a view that proves neither is only printed
            if x["kind"] == "profile" and x["saw"] != "degree:1":
                out.append("VIEWED contact:%s kind=profile %s" % (pid, x["saw"]))
        for s in mine:
            if s["state"] == "pending":
                out.append("PENDING contact:%s on=%s (an invitation still listed; no reply attached)"
                           % (pid, s["on"]))
        if accepted or accepted_view:
            sighting = True
            on = (accepted[0]["date"] or "?") if accepted else accepted_view[0]["at"][:10]
            out.append("ACCEPTED contact:%s on=%s" % (pid, on))
        if reply_dates:
            sighting = True
            newest = max(reply_dates)
            out.append("REPLIED contact:%s %s" % (pid, newest))
            v.probes.append((pid, "thread:%s" % newest))
        if sighting:
            v.concluded += 1
            continue
        if one_off:
            continue                                  # a one-off is a look, not a sweep verdict
        gaps = _slot_gaps(pid, w, surfaces,
                          {x["id"] for x in views if x["kind"] == "thread"},
                          {x["id"] for x in views if x["kind"] == "profile"})
        if gaps:
            v.not_concluded += 1
            for tok in gaps:
                incomplete.setdefault(tok, []).append((pid, w["since"]))
            continue
        if pid in tainted or block_taint:
            # ⭐ a dropped line may have carried a reply for this person: NEVER a NO CHANGE
            v.not_concluded += 1
            out.append("NOT CONCLUDED contact:%s — a faulted line may name this contact, so no "
                       "`empty` probe is written for them" % pid)
            continue
        v.concluded += 1
        out.append("NO CHANGE contact:%s (covered through %s)" % (pid, w["since"] or "?"))
        v.probes.append((pid, "empty"))

    open_scopes = {g.get("scope") for g in journal.open_gaps(recs or [])}
    for tok in LIST_SURFACES:
        people = incomplete.get(tok)
        if not people:
            continue
        info = surfaces.get(tok) or {}
        if info.get("status") == "REACHED":
            total = "?" if info.get("total") is None else info["total"]
            what = "shown %d of %s (oldest %s)" % (info["shown"], total, info.get("oldest") or "?")
            reason = "partial-results"
        else:
            reason = info.get("reason") or "surface-unreachable"
            what = "not reached (%s)" % (info.get("reason") or info.get("status") or "not reported")
        sinces = [s for _p, s in people if s]
        back = min(sinces) if len(sinces) == len(people) else "the start"
        out.append("!! INCOMPLETE COVERAGE linkedin:%s — %s; %d contact(s) not concluded"
                   % (tok, what, len(people)))
        scope = "linkedin:%s" % tok
        if scope not in open_scopes:
            v.gaps.append((scope, reason, "a run reads %s back to %s" % (tok, back)))
            open_scopes.add(scope)
        exit_incomplete = True

    if one_off:
        if v.faults:
            v.name, v.exit, v.keep = "line-faults", EXIT_LINE_FAULTS, True
        else:
            v.name, v.exit = "clean", EXIT_OK
        out.append("ONE-OFF RECORDED run=%s: %d sighting(s). The daily pass row is untouched."
                   % (run_id, v.concluded))
        return v

    if not watch:
        out.append("No open LinkedIn touches to conclude.")
    if not [t for t in LIST_SURFACES if t in v.reached]:
        v.name, v.exit, v.keep, v.owed = "pass-failed", EXIT_PASS_FAILED, True, "queue"
        v.detail = "no list surface reached"
        v.not_measured = True
        out.append("!! NO LIST SURFACE REACHED — the pass read nothing it can conclude from; "
                   "the owed pass row stays pending.")
        if v.mode == "hidden":
            # dev #826 / public #177 (design 2.3 rule 4): a hidden pass is never re-queued. On a scheduled
            # surface nobody is there to show the pane, so a queued pass would recur daily; the open
            # pane-hidden gap and its remedy line are the signal. An owed row already pending stays pending.
            v.owed = None
            out.append("(a hidden pass is not re-queued; the open %s gap carries the remedy)"
                       % PANE_HIDDEN_SCOPES[_executor(pane["state"] if pane else None)])
        return v
    v.owed, v.summary, v.not_measured = "close", True, True
    if v.faults:
        v.name, v.exit, v.keep = "line-faults", EXIT_LINE_FAULTS, True
    elif exit_incomplete:
        v.name, v.exit = "incomplete", EXIT_INCOMPLETE
    else:
        v.name, v.exit = "clean", EXIT_OK
    return v


def _probe_key(p):
    return (p.get("subject"), p.get("thread"), p.get("result"), p.get("medium"), p.get("by"))


def apply(root, run_id, text, v, at=None, out=print, check=False):
    """⭐ dev #812 / public #169 -- the ONLY function that writes. `check=True` (`--check`) prints the
    verdict's lines and its `verdict:` line and returns `v.exit` without writing anything, so that
    `--check` writes nothing BY CONSTRUCTION. Otherwise, in order: copy the raw hand-back when the
    verdict calls for it (a refusal, a fault, a failed pass with a block: byte for byte,
    `handback.keep`); print; journal the probes (one identical to a probe already journaled since this
    run's start is skipped, so a corrected re-record is idempotent); file one `partial-results` gap per
    line fault and close the ones a corrected hand-back no longer has; file the INCOMPLETE COVERAGE
    gaps; close or queue the owed pass row; and append one `recorded` pass row (a daily pass only: a
    one-off is not the daily pass). Returns `v.exit`."""
    at = at or journal.now_iso()
    if check:
        for ln in v.lines:
            out(ln)
        out(v.verdict_line())
        return v.exit

    surface = "linkedin-oneoff" if v.one_off else "linkedin"
    kept_abs = handback.keep(root, "sweep", run_id, surface, text, out) if v.keep else None
    rel = handback.kept_rel("sweep", run_id, surface) if kept_abs else ""
    where = handback.kept_where(rel, run_id) if rel else ""

    if v.exit == EXIT_LINE_FAULTS:
        if v.one_off:
            out("ONE-OFF RECORDED WITH LINE FAULTS (exit 5): every readable line is journaled and the "
                "daily pass row is untouched. The faulty lines are gaps: %s" % (where or "(not kept)"))
        else:
            out("RECORDED WITH LINE FAULTS (exit 5): every readable line is journaled and the owed "
                "pass is closed. Do not re-dispatch the runner. The faulty lines are gaps: %s"
                % (where or "(not kept)"))
    for ln in v.lines:
        out(ln)
    if v.name in ("refused", "pass-failed", "pane-held") and where:
        out("   The raw hand-back is kept at %s" % where)

    recs = journal.read(root)
    starts = [str(r.get("at", "")) for r in recs
              if r.get("event") == "start" and r.get("run_id") == run_id]
    since = min(starts) if starts else str(at)[:10]
    have = {_probe_key(p) for p in recs
            if p.get("event") == "probe" and str(p.get("at", "")) >= since}
    for pid, result in v.probes:
        key = ("contact:%s" % pid, "contact:%s" % pid, result, "linkedin", "linkedin-runner")
        if key in have:
            out("= already recorded: contact:%s %s" % (pid, result))
            continue
        journal.record_probe(root, "contact:%s" % pid, "contact:%s" % pid, result,
                             medium="linkedin", by="linkedin-runner", at=at)
        have.add(key)

    if v.judged:
        scope_fmt = ONE_OFF_LINE_GAP_SCOPE if v.one_off else SWEEP_LINE_GAP_SCOPE

        def closes(f):
            what = ("line %d %r broke: %s" % (f["line"], f["text"], f["rule"])
                    if f["line"] is not None else "block check broke: %s" % f["rule"])
            return ("%s -- fixed when a corrected hand-back for this run is accepted by "
                    "linkedin_sweep.py record%s"
                    % (what, (" (raw hand-back kept at %s)" % where) if where else ""))

        current = handback.file_line_gaps(root, run_id, scope_fmt, v.faults, closes, out)
        handback.close_stale_line_gaps(root, run_id, scope_fmt % "", current, out)
    if v.judged and not v.one_off:
        # dev #826 / public #177: the pane gaps. A one-off is a look the owner is present for and is not the
        # daily pass, so it neither opens nor closes one. Dedupe and close on (scope, reason).
        for act, scope, reason, closes_when in v.pane_actions:
            if act == "open":
                if any(g.get("scope") == scope and g.get("reason") == reason
                       for g in journal.open_gaps(journal.read(root))):
                    continue
                try:
                    journal.record_gap(root, run_id, scope, reason, closes_when=closes_when, at=at)
                except journal.JournalError as e:
                    out("⚠️ could not journal the gap %s (%s)" % (scope, e))
            else:
                close_pane_gaps(root, scope, reason, at=at, out=out)
    for scope, reason, closes_when in v.gaps:
        journal.record_gap(root, run_id, scope, reason, closes_when=closes_when, at=at)

    if v.owed == "queue":
        if v.one_off:
            out("(a one-off never queues the daily pass)")
        else:
            row, added = deferred.queue_linkedin_pass()
            out("LINKEDIN PASS STILL OWED: %s %s" % ("queued" if added else "already pending", row["id"]))
    elif v.owed == "close":
        closed = deferred.close_linkedin_passes()
        if v.summary:
            out("SWEEP RECORDED run=%s: %d concluded, %d not concluded; %d owed pass row(s) closed%s"
                % (run_id, v.concluded, v.not_concluded, len(closed),
                   (" (%s)" % ", ".join(closed)) if closed else ""))
    if v.not_measured:
        out("NOT MEASURED HERE: job search and notifications (they never gate closure of the owed pass)."
            if v.summary else
            "NOT MEASURED HERE: job search and notifications (they never gate closure).")

    if not v.one_off:
        try:
            pane_row = ({"pane": v.pane, "mode": v.mode, "partial": v.partial}
                        if v.pane is not None else {})        # a block that was never read has no pane account
            journal.record_pass(root, run_id, "linkedin", "recorded", reached=v.reached,
                                unreachable=v.unreachable, not_attempted=v.not_attempted, at=at,
                                verdict=v.name, faults=len(v.faults), kept=rel,
                                concluded=v.concluded, not_concluded=v.not_concluded, **pane_row)
        except journal.JournalError as e:
            out("⚠️ could not journal the `recorded` pass row (%s): the quota will count this pass" % e)
    out(v.verdict_line())
    return v.exit


def record(root, run_id, text, watch, one_off=False, at=None, out=print, check=False):
    """Judge one hand-back and (unless `check`) journal what it proves; return the exit code. See the
    module docstring for the codes and for what closes the owed pass row. `judge` decides and `apply`
    writes (dev #812 / public #169)."""
    v = judge(text, run_id, watch, one_off=one_off, recs=journal.read(root))
    return apply(root, run_id, text, v, at=at, out=out, check=check)


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def _read_input(path):
    if path and path != "-":
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError) as e:
            raise SweepRefused("cannot read the hand-back %s: %s" % (path, e))
    return sys.stdin.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description="The LinkedIn reply sweep's worklist and verdict.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worklist", help="print the WORKLIST block the runner works from")
    r = sub.add_parser("record", help="judge the runner's hand-back and journal what it proves")
    for p in (w, r):
        p.add_argument("--run", required=True, help="the journal run id (journal.py --start)")
        p.add_argument("--one-off", metavar="contact:<id>",
                       help="the explicit degree check: one person's profile, journaled as a probe")
    r.add_argument("--file", metavar="PATH", help="the hand-back (default: stdin)")
    r.add_argument("--at", help="ISO timestamp; for tests and for replaying a known time")
    r.add_argument("--check", action="store_true",
                   help="judge the hand-back with the same code as the real call, print each fault and "
                        "one `verdict:` line, write NOTHING, and exit with the code the real call "
                        "would")
    args = ap.parse_args(argv)
    root = profile_root()
    try:
        if args.cmd == "worklist":
            sys.stdout.write(build_worklist(root, args.run, one_off=args.one_off))
            return EXIT_OK
        watch = one_off_watch(root, args.one_off) if args.one_off else watch_set(root)
        try:
            text = _read_input(args.file)
        except SweepRefused as e:
            # dev #812 / public #169 (N14) -- nothing was read, so there is nothing to judge or keep:
            # exit 2 at once, writing nothing (no `recorded` row, no copy, no queue). The pass still
            # counts against the quota (no row, §4 rule 4).
            print("⛔ %s; raw NOT kept" % e, file=sys.stderr)
            return EXIT_REFUSED
        return record(root, args.run, text, watch, one_off=bool(args.one_off), at=args.at,
                      check=args.check)
    except (SweepRefused, journal.JournalError) as e:
        print("⛔ %s" % e, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
