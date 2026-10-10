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
    python3 scripts/linkedin_sweep.py record   --run <id> [--one-off contact:<id>] [--file PATH]

`record` reads the runner's hand-back from `--file` (or stdin). Exit codes:
    0  every watched person concluded            3  some person NOT concluded (pass still closes)
    2  input refused; nothing journaled          4  the pass FAILED (a reserved first line, or no
                                                    list surface REACHED); the owed row stands

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

## The grammar (one definition; `agents/linkedin-runner.md` carries it byte-equal, test-enforced)

`SWEEP_GRAMMAR` below. The parser is strict and all-or-nothing: a line inside a block that matches no
form refuses the WHOLE block (exit 2, the line printed, nothing journaled). A `contact:<id>` absent
from the watch set is refused, `VIEW` included. Principle 4 (a fact a run knows goes into the
queryable store, never narrative; an unparseable value is loud).

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from _root import profile_root  # noqa: E402
import deferred  # noqa: E402
import graph as _graph  # noqa: E402
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

EXIT_OK, EXIT_REFUSED, EXIT_INCOMPLETE, EXIT_PASS_FAILED = 0, 2, 3, 4

# ⭐ THE GRAMMAR — byte-equal to the fenced copy between `<!-- sweep-grammar:begin -->` and
# `<!-- sweep-grammar:end -->` in plugins/jobsearch/agents/linkedin-runner.md. Edit both in the same
# commit, or `TestSweepGrammarFence` goes red.
SWEEP_GRAMMAR = """\
--- WORKLIST v1 run=<run-id> ---                      (what you are given; you never write one)
SURFACE <token> url=<url> back-to=<YYYY-MM-DD|all|none> [positive-only]
JOBSEARCH window=<daily|wide> f_TPR=<r86400|r604800> titles=<configured|all> geo=<remote[,local]> [wide-due-since=<YYYY-MM-DD|never>]
WATCH contact:<id> since=<YYYY-MM-DD|?> medium=<linkedin-*|?> name="<display name>" [match=<profile url>]
THREAD contact:<id> url=<messaging thread url>
--- END WORKLIST ---

--- SWEEP v1 run=<run-id> ---                         (what you hand back, in your hand-back file)
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
# parsing a hand-back
# ---------------------------------------------------------------------------------------------

def parse_sweep(text, run_id, watch):
    """`(surfaces, seen, views)` from the one SWEEP block in `text`. Strict, all-or-nothing:
    raises `SweepRefused` naming the first line it cannot read. Prose outside the block is
    ignored — the block is the contract, not the hand-back around it."""
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

    surfaces, seen, views = {}, [], []
    for i in range(begins[0] + 1, end):
        raw = lines[i].strip()
        if not raw:
            continue
        n = i + 1
        sm = _SURF_REACHED.match(raw)
        if sm:
            shown, total = int(sm.group("shown")), sm.group("total")
            total = None if total == "?" else int(total)
            if total is not None and shown > total:
                raise SweepRefused("line %d: shown=%d exceeds total=%d: %r" % (n, shown, total, raw))
            _put_surface(surfaces, sm.group("tok"), n, raw, {
                "status": "REACHED", "shown": shown, "total": total,
                "oldest": None if sm.group("oldest") == "?" else sm.group("oldest")})
            continue
        sm = _SURF_UNREACHABLE.match(raw)
        if sm:
            if sm.group("reason") not in journal.REASONS:
                raise SweepRefused("line %d: reason=%s is not a journal.REASONS code: %r"
                                   % (n, sm.group("reason"), raw))
            _put_surface(surfaces, sm.group("tok"), n, raw,
                         {"status": "UNREACHABLE", "reason": sm.group("reason")})
            continue
        sm = _SURF_NOT_ATTEMPTED.match(raw)
        if sm:
            _put_surface(surfaces, sm.group("tok"), n, raw, {"status": "NOT-ATTEMPTED"})
            continue
        sm = _SEEN.match(raw)
        if sm:
            state, on, d = sm.group("state"), sm.group("on"), sm.group("date")
            if on not in _STATE_SURFACES[state]:
                raise SweepRefused("line %d: state=%s is not read on %s: %r" % (n, state, on, raw))
            if state == "reply" and d == "?":
                raise SweepRefused("line %d: a reply needs its date (it is journaled as "
                                   "thread:<date>): %r" % (n, raw))
            _need_watched(sm.group("id"), watch, n, raw)
            seen.append({"id": sm.group("id"), "on": on, "state": state,
                         "date": None if d == "?" else d, "line": n})
            continue
        sm = _VIEW.match(raw)
        if sm:
            kind, saw = sm.group("kind"), sm.group("saw")
            if (kind == "thread") != (saw == "empty" or saw.startswith("message:")):
                raise SweepRefused("line %d: a %s view cannot see %r: %r" % (n, kind, saw, raw))
            if journal._parse_iso(sm.group("at")) is None:
                raise SweepRefused("line %d: at=%s is not an ISO time: %r" % (n, sm.group("at"), raw))
            _need_watched(sm.group("id"), watch, n, raw)
            views.append({"id": sm.group("id"), "kind": kind, "at": sm.group("at"),
                          "saw": saw, "line": n})
            continue
        raise SweepRefused("line %d is not a line of the SWEEP grammar: %r" % (n, raw))

    for s in seen:
        info = surfaces.get(s["on"])
        if not info or info["status"] != "REACHED":
            raise SweepRefused("line %d: SEEN on=%s but that surface is not reported REACHED"
                               % (s["line"], s["on"]))
    return surfaces, seen, views


def _put_surface(surfaces, tok, n, raw, info):
    if tok not in journal.LINKEDIN_SWEEP_SURFACES:
        raise SweepRefused("line %d: %r is not a surface token (%s): %r"
                           % (n, tok, ", ".join(sorted(journal.LINKEDIN_SWEEP_SURFACES)), raw))
    if tok in surfaces:
        raise SweepRefused("line %d: surface %s is reported twice: %r" % (n, tok, raw))
    surfaces[tok] = info


def _need_watched(pid, watch, n, raw):
    if pid not in watch:
        raise SweepRefused("line %d: contact:%s is not in this sweep's watch set (an unwatched "
                           "person's sighting is never recorded): %r" % (n, pid, raw))


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


def record(root, run_id, text, watch, one_off=False, at=None, out=print):
    """Judge one hand-back; journal what it proves; return the exit code. See the module
    docstring for the codes and for what closes the owed pass row."""
    at = at or journal.now_iso()
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")

    def _owed():
        if one_off:
            out("(a one-off never queues the daily pass)")
            return
        row, added = deferred.queue_linkedin_pass()
        out("LINKEDIN PASS STILL OWED: %s %s" % ("queued" if added else "already pending", row["id"]))

    if first.startswith(PANE_HELD):
        out("PANE HELD — another run holds the pane and is doing this work; nothing queued, "
            "nothing recorded.")
        return EXIT_PASS_FAILED
    for token in PASS_FAILURES:
        if first.startswith(token):
            out("PASS FAILED — %s (the hand-back's first line). The block, if any, was not read." % token)
            _owed()
            return EXIT_PASS_FAILED

    try:
        surfaces, seen, views = parse_sweep(text, run_id, watch)
    except SweepRefused as e:
        out("⛔ REFUSED — %s. Nothing was journaled." % e)
        _owed()
        return EXIT_REFUSED

    by = "linkedin-runner"
    exit_code = EXIT_OK
    concluded, not_concluded = 0, 0
    incomplete = {}                      # surface token -> [(person id, since)]
    seen_by = {}
    for s in seen:
        seen_by.setdefault(s["id"], []).append(s)
    views_by = {}
    for v in views:
        views_by.setdefault(v["id"], []).append(v)

    for pid in sorted(watch):
        w = watch[pid]
        mine, vws = seen_by.get(pid, []), views_by.get(pid, [])
        accepted = [s for s in mine if s["state"] == "accepted"]
        accepted_view = [v for v in vws if v["kind"] == "profile" and v["saw"] == "degree:1"]
        reply_dates = [s["date"] for s in mine if s["state"] == "reply"]
        reply_dates += [v["saw"][len("message:"):] for v in vws
                        if v["kind"] == "thread" and v["saw"].startswith("message:")]
        sighting = False
        for v in vws:                                # a view that proves neither is only printed
            if v["kind"] == "profile" and v["saw"] != "degree:1":
                out("VIEWED contact:%s kind=profile %s" % (pid, v["saw"]))
        for s in mine:
            if s["state"] == "pending":
                out("PENDING contact:%s on=%s (an invitation still listed; no reply attached)"
                    % (pid, s["on"]))
        if accepted or accepted_view:
            sighting = True
            on = (accepted[0]["date"] or "?") if accepted else accepted_view[0]["at"][:10]
            out("ACCEPTED contact:%s on=%s" % (pid, on))
        if reply_dates:
            sighting = True
            newest = max(reply_dates)
            out("REPLIED contact:%s %s" % (pid, newest))
            journal.record_probe(root, "contact:%s" % pid, "contact:%s" % pid,
                                 "thread:%s" % newest, medium="linkedin", by=by, at=at)
        if sighting:
            concluded += 1
            continue
        if one_off:
            continue                                  # a one-off is a look, not a sweep verdict
        gaps = _slot_gaps(pid, w, surfaces,
                          {v["id"] for v in views if v["kind"] == "thread"},
                          {v["id"] for v in views if v["kind"] == "profile"})
        if gaps:
            not_concluded += 1
            for tok in gaps:
                incomplete.setdefault(tok, []).append((pid, w["since"]))
            continue
        concluded += 1
        out("NO CHANGE contact:%s (covered through %s)" % (pid, w["since"] or "?"))
        journal.record_probe(root, "contact:%s" % pid, "contact:%s" % pid, "empty",
                             medium="linkedin", by=by, at=at)

    open_scopes = {g.get("scope") for g in journal.open_gaps(journal.read(root))}
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
        out("!! INCOMPLETE COVERAGE linkedin:%s — %s; %d contact(s) not concluded"
            % (tok, what, len(people)))
        scope = "linkedin:%s" % tok
        if scope not in open_scopes:
            journal.record_gap(root, run_id, scope, reason,
                               closes_when="a run reads %s back to %s" % (tok, back), at=at)
            open_scopes.add(scope)
        exit_code = EXIT_INCOMPLETE

    if one_off:
        out("ONE-OFF RECORDED run=%s: %d sighting(s). The daily pass row is untouched." % (run_id, concluded))
        return EXIT_OK

    reached = [t for t in LIST_SURFACES if (surfaces.get(t) or {}).get("status") == "REACHED"]
    if not watch:
        out("No open LinkedIn touches to conclude.")
    if not reached:
        out("!! NO LIST SURFACE REACHED — the pass read nothing it can conclude from; "
            "the owed pass row stays pending.")
        _owed()
        out("NOT MEASURED HERE: job search and notifications (they never gate closure).")
        return EXIT_PASS_FAILED
    closed = deferred.close_linkedin_passes()
    out("SWEEP RECORDED run=%s: %d concluded, %d not concluded; %d owed pass row(s) closed%s"
        % (run_id, concluded, not_concluded, len(closed), (" (%s)" % ", ".join(closed)) if closed else ""))
    out("NOT MEASURED HERE: job search and notifications (they never gate closure of the owed pass).")
    return exit_code


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
            # An unreadable hand-back is a refused one: say so, then let `record` refuse the empty
            # text (which also keeps the owed pass owed, for a routine pass).
            print("⛔ %s" % e, file=sys.stderr)
            text = ""
        return record(root, args.run, text, watch, one_off=bool(args.one_off), at=args.at)
    except (SweepRefused, journal.JournalError) as e:
        print("⛔ %s" % e, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
