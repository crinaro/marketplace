#!/usr/bin/env python3
"""The run journal — what a run knows, written the moment it knows it.

⭐ TWO ISSUES, ONE DEFECT (GitHub #4 and #5)
--------------------------------------------
**#4 — a run that dies early loses everything it learned.** Findings are held in the session
buffer and written out in one terminal step, so any early termination discards all of them. One
observed run had, before terminating: resolved a genuine contradiction between a generated
artifact and its underlying data, and enumerated roughly three times more outstanding items in a
channel than the previous run carried forward. **None of it reached any file.** Worse, the next
run cannot tell *did not fire* from *fired and found nothing* from *fired, found things, and died*.

**#5 — a coverage gap is recorded as prose.** When a sweep cannot finish, the gap goes into a
run-log narrative asking a future run to re-check. Nothing sorts it, nothing escalates it, no
run-start check reads it. One gap survived three runs with nothing flagging it.

⭐⭐ THEY ARE THE SAME BUG: **a fact the run ALREADY KNOWS, stored in the one format no check can
read.** So they get one mechanism, not two — fixing the class rather than the instance.

## The shape, copied from `precondition.py` deliberately

A named record · a strict parser that refuses what it cannot read · a resolver over data that
already exists. Append-only, one JSON object per line, because **two runs may journal at once and
an append cannot lose a concurrent write the way a rewrite can.**

    start   a run began              → an unmatched start is a run that DIED
    note    something was learned    → survives termination, because it is written NOW
    gap     a sweep did not complete  → structured, sortable, and closeable
    end     the run finished cleanly

⚠️ **Writing at the end is the bug.** `--note` and `--gap` are worth nothing if a run batches them;
they must be called as the run learns each thing. The whole point is that a crash one line later
still leaves the finding on disk.

⭐⭐⭐ THREE MORE STATES, ONE MORE CLASS (public #65, #69, #72) — a class audit confirmed all
three are the same defect that #4/#5 already are: a real state this journal has no vocabulary
for, so the absence is read as something worse than the truth.

**#65 — a run the SCHEDULER marks fired can leave zero trace.** `start` above is written by the
RUN's own logic (a skill instruction, the model's second action), so a run that dies before that
instruction ever executes is indistinguishable from a scheduler that never created a session at
all — no `start`, same as no session. The fix is a `fired` event, written by the SessionStart
HOOK ITSELF (`--fired`, wired as `hooks.json`'s first SessionStart hook) — deterministically,
before any model turn, so a session's existence is provable independent of whether the run ever
got as far as calling `--start`. A run that dies in the gap between "hook ran" and "skill called
--start" now leaves `fired` with no matching `start`, which is a NEW, narrower state than #65's
old one ("no session at all") and #4's ("session existed, died mid-run") — it means the hook
fired and the model turn that should have called `--start` never completed.

**#69 — a coverage gap has no way to say "this is a KNOWN, ALREADY-FILED limitation."** The same
permanent cause (a surface this profile has deliberately never wired, say) manufactures a fresh,
unexplained-looking gap on every run, forever. `--gap` now takes `--covered-by CITATION` — the
same `dev #N` / `public #N` / `marketplace #N` / `GitHub #N` vocabulary
`check_regression_links.py` already established, so a gap and a regression case cite issues the
same way. A gap that names one is COVERED rather than open-and-unexplained — it still records
every occurrence, because this is a queryable store and not a place to go quiet, but it is no
longer counted as an actionable open gap. ⚠️ **A suppression must not outlive its cause**:
`evaluate_coverage()` is the pure, offline half (which gaps need a live look, and what each
possible answer means) and `--check-coverage` is the on-demand `gh`+network half that actually
asks GitHub whether the cited issue is still open — the exact split `check_regression_links.py`
uses for the identical reason (CI has neither `gh` nor network), and for the same reason NOT
wired into CI. A `covered_by` naming a CLOSED or nonexistent issue is reported, loud, as stale
coverage — the same "cannot quietly outlive its defect" property `KNOWN_EXCEPTIONS` already has.

**#72 — a run that dies mid-flight is reported as an unresolved failure by `--check` forever**,
even after a human reviews its stranded notes and finds nothing worth writing. `--dispose --run
<id> [--because TEXT]` records exactly that outcome. The run is still reported as having died —
that fact is never hidden, because it is true — but it stops counting as a LOST run once its
notes are disposed of. Disposing is not the same as `--end`: `--end` claims the run finished
cleanly, which would be a lie about a run that actually died; `--dispose` tells the truth about a
dead run AND records that someone looked at what it left behind.

⭐⭐⭐⭐ dev #321 (V0) — A FIFTH STATE, AND IT IS AN INTERVAL, NOT A TIMESTAMP: nothing anywhere
recorded WHEN a mailbox was covered, so every "nobody has replied" rested on a mirror
(`data/messages.jsonl`) whose absence could mean either "nothing arrived" or "nothing looked."
`check_followups.py` measured silence against `datetime.now()` regardless of whether a sweep had
run in days — the exact "missing thing read as an empty thing" trap this repo names everywhere
else, sitting under the one path that tells a candidate to chase someone.

Two more events, both **positive** coverage (everything above is either negative — `gap` — or
run-shaped; these are per-mailbox and per-thread):

    swept   a multi-account search covered [from, through] for one mailbox, or failed
    probe   a LinkedIn thread was looked at — pointwise, one look sees the whole thread

`swept` is written by `mail_client.py`'s multi-account search, one row per configured account
per sweep, `ok: true` with the window actually searched or `ok: false` with a reason code — a
failed account is the loud `!! INCOMPLETE COVERAGE` banner **stored**, not just printed, so a
partial failure marks that account uncovered rather than merely annotated. `probe` is written
per LinkedIn thread look (`linkedin-runner`, wired later; V0 defines the shape so the
vocabulary exists — Class C's `probe … result=empty|thread:<date>`).

**Why an interval and not a timestamp:** sweeps are windowed (`watch --since <hours>`,
`alert_sweep --days 1`), so *"swept at T"* is not *"covered through T"* — a scheduler outage
leaves a hole a later sweep does not backfill unless something widens the window over it.
`covered_through(recs, mailbox, as_of=None)` merges every `ok: true` row's `[from, through]`
window for that mailbox and returns the end of the interval that contains `as_of` (or, with no
`as_of`, the newest merged interval's end) — `None` when nothing verifies coverage there. `None`
is the honest, load-bearing answer on an empty ledger: a caller that would otherwise fall back to
the wall clock (`check_followups.py`, fixed here) must render "unverified" instead of a
confidently wrong day count. `probe_covered_through(recs, thread)` is `probe`'s pointwise twin —
one look verifies through its own timestamp, no interval needed.

Usage:
    python3 journal.py --start daily                     # prints the run id
    python3 journal.py --run <id> --note "what was found"
    python3 journal.py --run <id> --gap linkedin:replies --reason browser-unavailable \
                       --closes-when "a run with chrome completes the sweep"
    python3 journal.py --run <id> --gap slack:digest --reason skipped-for-cost \
                       --covered-by "public #58"          # a KNOWN, filed limitation (#69)
    python3 journal.py --run <id> --end
    python3 journal.py --run <id> --dispose --because "reviewed, nothing actionable"  # (#72)
    python3 journal.py --unfinished     # runs that started and never ended, with their notes
    python3 journal.py --open-gaps      # oldest first, covered ones called out separately
    python3 journal.py --close-gap <gap_id>
    python3 journal.py --check          # exit 1 if an UNCOVERED gap is stale, or a run died
                                         # holding findings nobody disposed of
    python3 journal.py --check-coverage # on demand, needs gh+network: is every covered_by
                                         # citation still open? (#69, never run in CI)
    python3 journal.py --fired          # hook use only — see hooks.json's SessionStart entry
    python3 journal.py --probe opp:<id> --thread contact:<id> --result empty      # (dev #321)
    python3 journal.py --probe opp:<id> --thread contact:<id> \
                       --result thread:2026-09-10T09:00:00
    python3 journal.py --probe contact:<id> --thread contact:<id> --medium email \
                       --mailbox acct-a@example.com --result empty       # Query or Citation C1
    python3 journal.py --probe contact:<id> --thread contact:<id> --medium linkedin \
                       --result empty --read inbox,requests,invitations,degree   # D14

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root

JOURNAL = os.path.join("data", "runs.jsonl")
EVENTS = ("fired", "start", "note", "gap", "gap-closed", "end", "dispose", "swept", "probe")

# A reason is a CODE, not a sentence — codes can be counted, sentences cannot. An unrecognised
# one is refused rather than stored, because a taxonomy nobody enforces becomes free text within
# a month and then nothing can group by it. dev #321 (V0): `swept ok:false` rows use this same
# set — a failed sweep is the same shape of "why didn't this complete" as a gap.
REASONS = {"browser-unavailable", "credential-missing", "rate-limited", "timeout",
           "partial-results", "skipped-for-cost", "upstream-error", "interrupted", "other"}

# ⭐ dev #321 — a `probe` result is either the literal "empty" or "thread:<ISO timestamp>" (the
# newest inbound's date/time) — Class C's own vocabulary, settled here since V0 is the first
# design to ship it. Anything else is refused, loud, at write time (the precondition.py rule).
PROBE_RESULT_RE = re.compile(r"^(empty|thread:\d{4}-\d{2}-\d{2}.*)$")

STALE_DAYS = 3

# ⭐ public #69 — the SAME citation vocabulary `check_regression_links.py` already established
# for regression-case docstrings, reused here so a gap's `covered_by` and a test's class
# docstring speak one language rather than inventing a second. Case-insensitive; canonicalized
# to lowercase-kind + a single space before storing, so two spellings of the same issue never
# look like two different suppressions.
CITATION_RE = re.compile(r"^\s*(dev|github|marketplace|public)\s*#\s*([1-9]\d*)\s*$",
                         re.IGNORECASE)


class JournalError(ValueError):
    """Unparseable or unrecognised. Loud on purpose."""


def normalize_citation(raw):
    """Validate and canonicalize a `--covered-by` citation. Loud on anything else — an
    unparseable value is worse than none, because it looks handled and is not (the same rule
    this marketplace states for `precondition.py`, applied here to #69)."""
    m = CITATION_RE.match(raw or "")
    if not m:
        raise JournalError(
            "--covered-by %r is not a recognised citation — use 'dev #N', 'public #N', "
            "'marketplace #N' or 'GitHub #N' (check_regression_links.py's own vocabulary)"
            % raw)
    return "%s #%s" % (m.group(1).lower(), m.group(2))


def path(root):
    return os.path.join(root, JOURNAL)


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def append(root, rec):
    p = path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def read(root):
    out = []
    try:
        with open(path(root), encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    raise JournalError("%s line %d is not valid JSON — a journal that cannot be "
                                       "read is a journal that is not protecting anything"
                                       % (JOURNAL, n))
                if rec.get("event") not in EVENTS:
                    raise JournalError("%s line %d has unknown event %r"
                                       % (JOURNAL, n, rec.get("event")))
                out.append(rec)
    except FileNotFoundError:
        pass
    return out


def new_run_id(kind, at):
    slug = re.sub(r"[^a-z0-9]+", "-", (kind or "run").lower()).strip("-") or "run"
    return "%s-%s" % (slug, re.sub(r"[^0-9]", "", at)[:14])


def unfinished(recs):
    """Runs with a start and no end. ⭐ Their notes are the recoverable work.

    ⭐ public #72 — a dead run also carries whether its stranded notes were REVIEWED
    (`dispose`), so `--check` can tell "nobody has looked at this yet" from "looked at, nothing
    to write" instead of flagging both as an unresolved failure forever."""
    started, ended, disposed = {}, set(), {}
    for r in recs:
        if r["event"] == "start":
            started[r["run_id"]] = r
        elif r["event"] == "end":
            ended.add(r["run_id"])
        elif r["event"] == "dispose":
            disposed[r["run_id"]] = r          # last dispose wins if it ever happens twice
    out = []
    for rid, s in started.items():
        if rid in ended:
            continue
        notes = [r for r in recs if r.get("run_id") == rid and r["event"] == "note"]
        gaps = [r for r in recs if r.get("run_id") == rid and r["event"] == "gap"]
        d = disposed.get(rid)
        out.append({"run_id": rid, "at": s.get("at"), "kind": s.get("kind"),
                    "notes": [n.get("text") for n in notes], "gaps": len(gaps),
                    "disposed": bool(d), "disposed_at": d.get("at") if d else None,
                    "disposed_because": d.get("because") if d else None})
    return sorted(out, key=lambda x: x.get("at") or "")


def open_gaps(recs):
    closed = {r.get("gap_id") for r in recs if r["event"] == "gap-closed"}
    gaps = [r for r in recs if r["event"] == "gap" and r.get("gap_id") not in closed]
    return sorted(gaps, key=lambda g: g.get("at") or "")


def split_gaps(gaps):
    """⭐ public #69 — (uncovered, covered). An uncovered gap is unexplained and is what ages
    into `--check`'s stale list; a covered one names the issue that already explains it and is
    reported every run (queryable, never silent) but never chased as if it were new."""
    uncovered = [g for g in gaps if not g.get("covered_by")]
    covered = [g for g in gaps if g.get("covered_by")]
    return uncovered, covered


def fired_events(recs):
    """Every `fired` record — proof a SessionStart hook ran, independent of whether the run's
    own `--start` ever followed it. See the module docstring, public #65."""
    return sorted((r for r in recs if r.get("event") == "fired"), key=lambda r: r.get("at") or "")


def record_swept(root, mailbox, frm, through, by, ok, reason=None, at=None):
    """⭐ dev #321 (V0) — the ONE writer for positive mailbox coverage. `ok=True` needs `frm`
    and `through` (the window this sweep actually searched, ISO timestamps) — a positive
    coverage row with no window is not verifiable, so that shape is refused rather than stored
    with nulls. `ok=False` needs a REASON CODE from `REASONS` (the same "a code can be counted,
    a sentence cannot" rule the rest of this journal already enforces) and stores no window: a
    failed sweep covers nothing, which is the whole point — this is the `!! INCOMPLETE COVERAGE`
    banner stored instead of merely printed, so `covered_through()` for that mailbox does not
    advance past whatever it already had."""
    at = at or now_iso()
    if not mailbox:
        raise JournalError("record_swept requires a mailbox")
    if ok:
        if not (frm and through):
            raise JournalError(
                "record_swept(ok=True) requires frm and through — the window this sweep "
                "actually searched. A positive coverage row with no window is not verifiable.")
        rec = {"event": "swept", "mailbox": mailbox, "from": frm, "through": through,
               "at": at, "by": by or "", "ok": True}
    else:
        if reason not in REASONS:
            raise JournalError(
                "record_swept(ok=False) requires reason in REASONS, got %r — a failure without "
                "a reason code cannot be counted or grouped" % reason)
        rec = {"event": "swept", "mailbox": mailbox, "from": None, "through": None,
               "at": at, "by": by or "", "ok": False, "reason": reason}
    return append(root, rec)


MEDIA = ("email", "linkedin")

# Query or Citation C1, D14 — a LinkedIn `empty` verifies "no reply" only when the look actually
# covered every surface a reply could sit on: the inbox (both tabs a client can show), pending
# message requests, sent invitations (whose acceptance carries no message but does carry a
# reply-shaped signal), and connection degree (a reply can arrive as an acceptance rather than a
# message). A look that skipped one of these is not evidence of silence — see main()'s --probe
# handling, which refuses --result empty unless --read names all four.
LINKEDIN_SURFACES = frozenset({"inbox", "requests", "invitations", "degree"})


def record_probe(root, subject, thread, result, medium="linkedin", mailbox=None, by=None,
                 at=None):
    """⭐ dev #321 item 2 (V0), extended by Query or Citation C1 (D1) — one thread look, on
    either medium. Pointwise: unlike a mailbox sweep, which searches a window, a probe OPENS the
    thread (or, for email, searches an address/name-term set — see brief.py §4.3) and sees
    everything relevant, so one probe at T verifies that thread through T with no interval to
    merge.

    `medium` defaults to `"linkedin"` so every V0 caller (none existed before C1, but the
    default keeps the shape backward-compatible on principle) is unaffected. `mailbox` names the
    email account this probe searched — required when `medium="email"`, refused otherwise (a
    LinkedIn probe has no per-account shape; carrying a stray value there would let a reader
    mistake it for an email probe of that account). `by="owner"` marks the owner's own
    `--i-checked` attestation (brief.py §4.4) rather than a script-run search.

    C1's writers: `brief.py`'s mailbox probe (medium="email", one row per configured account)
    and `journal.py --probe --medium linkedin` (`linkedin-runner`, via --read — see main())."""
    at = at or now_iso()
    if not (subject and thread):
        raise JournalError("record_probe requires subject and thread")
    if medium not in MEDIA:
        raise JournalError("medium %r is not recognised — use 'email' or 'linkedin'" % medium)
    if medium == "email" and not mailbox and by != "owner":
        raise JournalError("record_probe(medium='email') requires mailbox (unless by='owner' "
                           "— the owner's own attestation names no specific account)")
    if medium == "linkedin" and mailbox:
        raise JournalError("record_probe(medium='linkedin') takes no mailbox — a LinkedIn probe "
                           "is not per-account")
    if not PROBE_RESULT_RE.match(result or ""):
        raise JournalError(
            "--result %r is not recognised — use 'empty' or 'thread:<ISO timestamp>' "
            "(Class C's probe vocabulary)" % result)
    rec = {"event": "probe", "medium": medium, "mailbox": mailbox, "subject": subject,
           "thread": thread, "result": result, "at": at}
    if by:
        rec["by"] = by
    return append(root, rec)


def _parse_iso(raw):
    try:
        return datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _merge_intervals(intervals):
    """[(from_dt, through_dt), ...] -> the same list with every overlapping or touching pair
    merged into one. Adjacency is guaranteed across a healthy run history by the ledger-derived
    lookback in `mail_client.py` (each sweep reaches back to the end of the last covered
    interval), so a gap that survives this merge is a REAL hole, not a rounding artefact."""
    merged = []
    for f, t in sorted(intervals, key=lambda p: p[0]):
        if merged and f <= merged[-1][1]:
            if t > merged[-1][1]:
                merged[-1] = (merged[-1][0], t)
        else:
            merged.append((f, t))
    return merged


def covered_through(recs, mailbox, as_of=None):
    """⭐⭐ dev #321 (V0) — THE READER every silence consumer imports. The end (ISO string) of
    the contiguous VERIFIED-coverage interval for `mailbox` that CONTAINS `as_of` — or, with no
    `as_of`, the newest merged interval's end. Returns `None` when nothing verifies coverage
    there: no `swept` rows at all, or `as_of` falls in a gap between them. `None` is the honest
    default on an empty ledger — the caller's job (check_followups.py) is to render "unverified"
    rather than fall back to the wall clock, which is dev #321 itself.

    Coverage is the union of `[from, through]` windows from `ok: true` swept rows for this
    mailbox; a `swept ok: false` row (a failed account) contributes nothing, which is what makes
    a partial failure mark that account uncovered rather than merely annotated.
    """
    intervals = []
    for r in recs:
        if r.get("event") != "swept" or r.get("mailbox") != mailbox or not r.get("ok"):
            continue
        fd, td = _parse_iso(r.get("from")), _parse_iso(r.get("through"))
        if fd is None or td is None:
            continue
        intervals.append((fd, td))
    if not intervals:
        return None
    merged = _merge_intervals(intervals)
    if as_of is None:
        return merged[-1][1].isoformat()
    as_of_dt = as_of if isinstance(as_of, datetime.datetime) else _parse_iso(as_of)
    if as_of_dt is None:
        return None
    for f, t in merged:
        if f <= as_of_dt <= t:
            return t.isoformat()
    return None


def probe_covered_through(recs, thread, medium):
    """⭐ dev #321 item 2 (V0), medium-filtered by Query or Citation C1 (D1) — the newest
    `probe` row's `at` for this `thread` ON THIS MEDIUM, or `None`. A probe is pointwise (see
    `record_probe`), so the newest one alone verifies coverage through its own timestamp; no
    interval merge applies.

    `medium` carries NO DEFAULT on purpose: V0 had exactly one caller and none existed yet, so a
    default was harmless; C1 adds the first real consumers (`your_move.conversation_axis()`),
    and a caller that does not say which medium it means would silently accept an email probe
    as LinkedIn coverage of the same `contact:<id>` thread (or vice versa) — the exact
    cross-medium confusion D1 exists to prevent."""
    ats = [r.get("at") for r in recs
          if r.get("event") == "probe" and r.get("thread") == thread
          and r.get("medium") == medium and r.get("at")]
    return max(ats) if ats else None


def age_days(at):
    try:
        then = datetime.datetime.fromisoformat(at)
        return (datetime.datetime.now() - then).days
    except Exception:
        return 0


# ⭐⭐ public #69 — THE PURE/IMPURE SPLIT, copied deliberately from
# `check_regression_links.py`'s own split for the identical reason: "is issue #N still open"
# needs `gh` and the network, and CI has neither. So the DECISION logic below (`evaluate_coverage`)
# is pure and exercised in CI against a fake `issue_state`; the ANSWER (`issue_state` itself) is
# impure, lives only here, and is never called by any CI-run gate — `--check-coverage` is a tool
# gate-keeper/release-manager run locally, on demand, exactly like that script's own `main()`.

def evaluate_coverage(gaps, issue_state):
    """Which covered_by citations are still doing their job? De-duplicates by citation first —
    ten gaps covered by the same filed issue need exactly one live lookup, not ten.

    `issue_state(citation) -> "OPEN" | "CLOSED" | "MISSING" | None` is the one impure call this
    function makes; everything else here is deterministic. Returns three lists of
    `(citation, [gap_id, ...])`: verified-open, stale (CLOSED or MISSING — the citation has
    outlived its cause, or never named a real issue), and unverifiable (no `gh`, no network, or —
    for a `dev`/`github`/`marketplace` citation checked from an INSTALLED copy — no private-repo
    remote to even ask; that last case is normal and not itself a failure)."""
    by_citation = {}
    for g in gaps:
        c = g.get("covered_by")
        if c:
            by_citation.setdefault(c, []).append(g.get("gap_id"))
    verified_open, stale, unverifiable = [], [], []
    for citation in sorted(by_citation):
        gap_ids = by_citation[citation]
        state = issue_state(citation)
        if state == "OPEN":
            verified_open.append((citation, gap_ids))
        elif state in ("CLOSED", "MISSING"):
            stale.append((citation, gap_ids))
        else:
            unverifiable.append((citation, gap_ids))
    return verified_open, stale, unverifiable


def _split_citation(citation):
    kind, _, num = (citation or "").partition("#")
    return kind.strip().lower(), num.strip()


def _public_repo():
    """This plugin's OWN public tracker, read from its manifest — the same derivation
    `report_issue.py`'s `tracker()` uses, so this resolves from an INSTALLED copy with no
    knowledge of the private repo at all."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(os.path.dirname(here), ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            repo = str(json.load(fh).get("repository") or "")
        m = re.search(r"github\.com[:/]([\w.\-]+/[\w.\-]+?)(?:\.git)?/?$", repo)
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def _private_repo():
    """This CHECKOUT's own origin — resolvable only from a maintainer checkout. An installed
    copy is not a git repository at all, so `git remote` simply fails here, which is correct: an
    installed copy has no business knowing the private repo's name, let alone querying it."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run(["git", "-C", here, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", (out.stdout or "").strip())
        return m.group(1) if m else None
    except Exception:                                     # noqa: BLE001
        return None


def issue_state(citation):
    """LIVE, IMPURE, NEVER CALLED IN CI. Returns 'OPEN', 'CLOSED', 'MISSING' (the repo resolved
    but the issue did not), or None — unverifiable from here, which covers "no `gh` on PATH",
    "no network", and "a dev/github/marketplace citation asked from an installed copy with no
    private remote" alike. `evaluate_coverage()` above is what gives that None a name."""
    kind, num = _split_citation(citation)
    if not num.isdigit():
        return None
    repo = _public_repo() if kind == "public" else _private_repo()
    if not repo:
        return None
    try:
        out = subprocess.run(["gh", "issue", "view", num, "--repo", repo, "--json", "state"],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError):
        return None
    if out.returncode != 0:
        return "MISSING" if "could not resolve" in (out.stderr or "").lower() else None
    try:
        return str(json.loads(out.stdout or "{}").get("state") or "").upper() or None
    except ValueError:
        return None


def _record_fired(root, at):
    """⭐⭐ public #65 — called ONLY from `hooks.json`'s SessionStart entry, before any model
    turn. This is the whole fix: a `fired` event written by the HOOK, deterministically, is
    evidence a session existed that does not depend on the run's own logic ever getting a turn
    to call `--start`. MUST NEVER block a session — every failure is swallowed and reported to
    stderr only, the same contract `ensure_connectors.py`'s SessionStart hook already keeps."""
    try:
        session_id, cwd = "", ""
        try:
            if not sys.stdin.isatty():
                payload = json.loads(sys.stdin.read() or "{}") or {}
                session_id = str(payload.get("session_id") or "")
                cwd = str(payload.get("cwd") or "")
        except Exception:                                 # noqa: BLE001 — stdin is best-effort
            pass
        append(root, {"event": "fired", "session_id": session_id, "cwd": cwd, "at": at})
    except Exception as e:                                # noqa: BLE001 — never block a session
        print("journal.py --fired: could not record (%s) — session continues unaffected" % e,
              file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", metavar="KIND")
    ap.add_argument("--run", metavar="ID")
    ap.add_argument("--note")
    ap.add_argument("--gap", metavar="SCOPE")
    ap.add_argument("--reason", choices=sorted(REASONS))
    ap.add_argument("--closes-when", dest="closes_when")
    ap.add_argument("--covered-by", dest="covered_by", metavar="CITATION",
                    help="with --gap: a KNOWN, already-filed limitation explains this every "
                         "time — 'dev #N' / 'public #N' / 'marketplace #N' / 'GitHub #N' "
                         "(public #69)")
    ap.add_argument("--end", action="store_true")
    ap.add_argument("--dispose", action="store_true",
                    help="with --run: a dead run's stranded notes were reviewed and needed no "
                         "write (public #72)")
    ap.add_argument("--because", help="optional free text: why --dispose needed no write")
    ap.add_argument("--unfinished", action="store_true")
    ap.add_argument("--open-gaps", dest="open_gaps", action="store_true")
    ap.add_argument("--close-gap", dest="close_gap", metavar="GAP_ID")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--check-coverage", dest="check_coverage", action="store_true",
                    help="on demand, needs gh+network: is every covered_by still open? "
                         "(public #69, never run in CI)")
    ap.add_argument("--fired", action="store_true",
                    help="hook use only — SessionStart wrote this before any model turn "
                         "(public #65); see hooks.json")
    ap.add_argument("--probe", metavar="SUBJECT",
                    help="record a thread/mailbox look (dev #321; extended C1) — needs --thread "
                         "and --result")
    ap.add_argument("--thread", metavar="THREAD",
                    help="with --probe: the thread this probe looked at (e.g. contact:<id>)")
    ap.add_argument("--result", metavar="RESULT",
                    help="with --probe: 'empty' or 'thread:<ISO timestamp>'")
    ap.add_argument("--medium", choices=sorted(MEDIA), default="linkedin",
                    help="with --probe: which medium this look covered (default: linkedin, "
                         "V0's original and only medium)")
    ap.add_argument("--mailbox", metavar="ADDRESS",
                    help="with --probe --medium email: the account this probe searched — "
                         "required for medium=email, refused for medium=linkedin")
    ap.add_argument("--read", metavar="SURFACES",
                    help="with --probe --medium linkedin --result empty: comma-separated "
                         "surfaces this look actually covered. `empty` is refused unless this "
                         "names all four of inbox,requests,invitations,degree (D14) — a look "
                         "that skipped one is not evidence of silence, and is recorded as a "
                         "'gap' instead, with no probe row")
    ap.add_argument("--by", choices=("owner",),
                    help="with --probe: 'owner' marks this as the owner's own attestation "
                         "(brief.py --i-checked), not a script-run search")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--at", help="ISO timestamp; for tests and for replaying a known time")
    args = ap.parse_args()

    root = profile_root()
    at = args.at or now_iso()

    # ⭐ public #65 — MUST NEVER BLOCK A SESSION, so this bypasses the JournalError contract
    # entirely: `_record_fired` swallows its own failures and this always returns 0.
    if args.fired:
        _record_fired(root, at)
        return 0

    try:
        if args.probe:
            if not args.thread:
                raise JournalError("--probe requires --thread")
            if not args.result:
                raise JournalError("--probe requires --result ('empty' or 'thread:<ISO ts>')")
            # ⭐ D14 — a LinkedIn `empty` verifies silence only when every surface a reply
            # could sit on was actually read. A look that skipped one is NOT evidence, and gets
            # NO probe row — linkedin-runner's own standing rules (agents/linkedin-runner.md)
            # already say what to do instead: file the existing gap vocabulary
            # (`--gap linkedin:message-requests --reason surface-unreachable`) under the run
            # that attempted the look. This refusal is what keeps a partial read from being
            # written as if it were a complete one; it does not invent a second gap mechanism.
            if args.medium == "linkedin" and args.result == "empty":
                read_surfaces = {s.strip() for s in (args.read or "").split(",") if s.strip()}
                missing = LINKEDIN_SURFACES - read_surfaces
                if missing:
                    raise JournalError(
                        "--result empty refused (D14) — --read did not name %s. A LinkedIn "
                        "look that skips a surface a reply could sit on is not evidence of "
                        "silence. File the gap instead: journal.py --run <id> --gap "
                        "linkedin:message-requests --reason surface-unreachable ..."
                        % ", ".join(sorted(missing)))
            record_probe(root, args.probe, args.thread, args.result,
                        medium=args.medium, mailbox=args.mailbox, by=args.by, at=at)
            print("probed")
            return 0

        if args.start:
            rid = new_run_id(args.start, at)
            append(root, {"event": "start", "run_id": rid, "kind": args.start, "at": at})
            print(rid)
            return 0

        if args.check_coverage:
            gaps = open_gaps(read(root))
            verified_open, stale, unverifiable = evaluate_coverage(gaps, issue_state)
            print("COVERAGE CHECK — live lookup against each covered_by citation\n")
            for citation, gap_ids in verified_open:
                print("  OK      %-16s covers %d gap(s), still open" % (citation, len(gap_ids)))
            for citation, gap_ids in unverifiable:
                print("  ??      %-16s NOT VERIFIED (no gh, no network, or no reachable repo)"
                      % citation)
            if stale:
                print("\n  !! %d STALE COVERAGE — the citation is CLOSED or does not exist, so "
                      "it has outlived whatever it was covering:" % len(stale))
                for citation, gap_ids in stale:
                    print("      %-16s covers %d gap(s): %s"
                          % (citation, len(gap_ids), ", ".join(gap_ids)))
            if not (verified_open or stale or unverifiable):
                print("  No covered gaps open. Nothing to verify.")
            return 1 if stale else 0

        if args.note or args.gap or args.end or args.close_gap or args.dispose:
            if args.close_gap:
                append(root, {"event": "gap-closed", "gap_id": args.close_gap, "at": at})
                print("closed %s" % args.close_gap)
                return 0
            if not args.run:
                raise JournalError("--run <id> is required (get one from --start)")
            if args.note:
                append(root, {"event": "note", "run_id": args.run, "text": args.note, "at": at})
                print("noted")
            if args.gap:
                if not args.reason:
                    raise JournalError(
                        "--reason is required with --gap. A gap without a reason code cannot be "
                        "counted or grouped, which is the whole reason this is not prose.")
                covered_by = normalize_citation(args.covered_by) if args.covered_by else ""
                gid = "%s:%s" % (args.run, re.sub(r"[^A-Za-z0-9:._-]+", "-", args.gap))
                append(root, {"event": "gap", "run_id": args.run, "gap_id": gid,
                              "scope": args.gap, "reason": args.reason,
                              "covered_by": covered_by,
                              "closes_when": args.closes_when or "", "at": at})
                print(gid)
            if args.end:
                append(root, {"event": "end", "run_id": args.run, "at": at})
                print("ended")
            if args.dispose:
                append(root, {"event": "dispose", "run_id": args.run,
                              "because": args.because or "", "at": at})
                print("disposed %s" % args.run)
            return 0

        recs = read(root)
        dead = unfinished(recs)
        gaps = open_gaps(recs)
        uncovered, covered = split_gaps(gaps)
        fired = fired_events(recs)

        if args.json:
            print(json.dumps({"unfinished": dead, "open_gaps": gaps,
                              "uncovered_gaps": uncovered, "covered_gaps": covered,
                              "fired": fired[-20:]}, indent=1))
        elif args.open_gaps:
            print("OPEN COVERAGE GAPS — oldest first\n")
            for g in uncovered:
                print("  [%2dd] %s  (%s)" % (age_days(g.get("at", "")), g.get("scope"),
                                             g.get("reason")))
                print("        %s · closes when: %s" % (g.get("gap_id"),
                                                        g.get("closes_when") or "unstated"))
            if not uncovered:
                print("  None. Every sweep that started has been completed, closed, or is "
                      "covered below.")
            if covered:
                print("\nCOVERED — a filed issue already explains these; not counted as open "
                      "(public #69)\n")
                for g in covered:
                    print("  [%2dd] %s  (%s)  covered by %s"
                          % (age_days(g.get("at", "")), g.get("scope"), g.get("reason"),
                             g.get("covered_by")))
        elif args.unfinished:
            print("RUNS THAT STARTED AND NEVER ENDED\n")
            for d in dead:
                tag = "  [reviewed — no write needed]" if d.get("disposed") else ""
                print("  %s  (%s)  %d note(s), %d gap(s)%s"
                      % (d["run_id"], d.get("at"), len(d["notes"]), d["gaps"], tag))
                for n in d["notes"][:5]:
                    print("      · %s" % str(n)[:110])
            if not dead:
                print("  None. Every run that started also finished.")
        else:
            lost_now = [d for d in dead if d["notes"] and not d.get("disposed")]
            print("RUN JOURNAL\n")
            print("  %d run(s) died mid-flight (%d unresolved) · %d open coverage gap(s) "
                  "(%d covered) · %d session(s) fired"
                  % (len(dead), len(lost_now), len(uncovered), len(covered), len(fired)))
            if dead:
                print("\n  ⭐ A run that started and never ended did NOT necessarily do nothing —")
                print("     its notes below are work that would otherwise have been lost.")
                for d in dead[:3]:
                    tag = " [reviewed]" if d.get("disposed") else ""
                    print("     %s: %d note(s)%s" % (d["run_id"], len(d["notes"]), tag))
            if uncovered:
                print("\n  ⏳ oldest unresolved gap: %s (%dd, %s)"
                      % (uncovered[0].get("scope"), age_days(uncovered[0].get("at", "")),
                         uncovered[0].get("reason")))

        if args.check:
            stale = [g for g in uncovered if age_days(g.get("at", "")) >= STALE_DAYS]
            lost = [d for d in dead if d["notes"] and not d.get("disposed")]
            for g in stale:
                print("⛔ coverage gap %r open %d days (%s)"
                      % (g.get("scope"), age_days(g.get("at", "")), g.get("reason")),
                      file=sys.stderr)
            for d in lost:
                print("⛔ run %s died holding %d unwritten finding(s)"
                      % (d["run_id"], len(d["notes"])), file=sys.stderr)
            return 1 if (stale or lost) else 0
        return 0

    except JournalError as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
