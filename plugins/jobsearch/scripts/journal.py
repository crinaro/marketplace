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

⭐⭐ public #85 — THE `end` EVENT NOW CARRIES A `footprint` OBJECT: a scheduled run once posted a
queue summary claiming "no change" while it had, in the same run, recorded a genuine reply and
left real writes uncommitted. `--end` computes `run_summary.footprint()` (defined in that module,
imported lazily right here — see the code) at the moment it is called, and stores the result on
the event: files/insertions/deletions from `git diff --stat`, a `git status --porcelain` count,
and this run's own swept/probe/gap/note counts from the journal itself. `run_summary.py --post`
computes the SAME shape independently, earlier in the run (before the commit, so its numbers are
the run's real diff rather than a post-commit clean tree) — the two calls measure two different
moments on purpose and are not expected to agree in value; `check_runs.py` reads both.

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
    python3 journal.py --check --run <id>  # mid-run (dev #474/public #119): <id> is the
                                         # CALLER's own run, excluded from the dead-run check
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
    python3 journal.py --run <id> --fold-dispatches       # design-script-first.md §8.2 (#90/#111)
    python3 journal.py --dispatches [--today] [--calibrate]
    python3 journal.py --calibrate                        # per-agent tool_use/token quantiles
    python3 journal.py --run <id> --pass linkedin --phase dispatched     # design-script-first.md
    python3 journal.py --run <id> --pass linkedin --phase returned \
                       --reached inbox --not-attempted requests,invitations,degree # §2 (#75/#87/#110)
    python3 journal.py --run <id> --pass linkedin --phase refused --reason skipped-for-cost
    python3 journal.py --passes [--today]                 # every pass row, '0 passes' if none
    python3 journal.py --check [--since YYYY-MM-DD]        # dispatch totals; never refuses on
                                                            # them until §8.3's ceiling lands

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
from _root import profile_root, is_tracked_fixture, transcript_stash_path

JOURNAL = os.path.join("data", "runs.jsonl")
EVENTS = ("fired", "start", "note", "gap", "gap-closed", "end", "dispose", "swept", "probe",
         "triaged", "dispatch", "pass")

# design-script-first.md §2 (public #75/#87/#110) — the three phases ONE LinkedIn pass moves
# through, written by TWO separate calls per §2 item 2 ("the row is written twice, and only the
# second counts"): `dispatched` in the same tool call that launches the runner
# (write-then-dispatch — a crash between the write and the launch still leaves the row, #87),
# `returned` from the hand-back's own REACHED/UNREACHABLE/NOT-ATTEMPTED line once the runner
# actually finishes, `refused` when the gate (browser capability or quota) never let the pass
# start at all — never a printed line with no row behind it (#87). Any other value is refused at
# write, loud, the same discipline `REASONS`/`PROBE_RESULT_RE` already apply to their own fields.
PASS_PHASES = ("dispatched", "returned", "refused")

# design-script-first.md §2 — V0's only LinkedIn pass kind. A tuple, not a bare string field, so
# a second kind (were one ever added) is a vocabulary addition here, never free-text drift —
# `REASONS`/`TRIAGE_VERDICTS`'s own "counted, not narrated" rule, applied to `kind`.
PASS_KINDS = ("linkedin",)

# design-script-first.md §8.2 (public #90/#111) — the ONE required shape for a `dispatch` row.
# Strict parser discipline reused from `scripts/dispatch_ledger.py` (the MAINTENANCE ledger this
# is a sibling of, never a second copy of — see §8.2's own "what this is not" section): an
# unknown key is refused, an incomplete row is refused, both at read time (`read()` below) and
# at write time (`record_dispatch()`).
DISPATCH_FIELDS = ("event", "run_id", "agent", "agent_id", "model", "tokens", "tool_uses",
                   "duration_s", "outcome", "for", "at")

# §3.4's hand-back rule 6 vocabulary (DONE|PARTIAL|BLOCKED — build-list item 6, not landed on any
# plugin agent yet), lower-cased to the maintenance ledger's own outcome words where they
# coincide (dispatch_ledger.py's OUTCOMES: landed|partial|stopped|redone). A hand-back that does
# not (yet) start with one of these three still gets an outcome — its own first word, lower-cased
# — rather than an empty field: "unparseable" is LOUD, never a blank read as fine.
OUTCOME_MAP = {"done": "landed", "partial": "partial", "blocked": "stopped"}

# A reason is a CODE, not a sentence — codes can be counted, sentences cannot. An unrecognised
# one is refused rather than stored, because a taxonomy nobody enforces becomes free text within
# a month and then nothing can group by it. dev #321 (V0): `swept ok:false` rows use this same
# set — a failed sweep is the same shape of "why didn't this complete" as a gap.
REASONS = {"browser-unavailable", "credential-missing", "rate-limited", "timeout",
           "partial-results", "skipped-for-cost", "upstream-error", "interrupted", "other",
           # ⭐ dev #354 / public #91's own gate — `linkedin-runner.md:247` and this file's own
           # D14 refusal message (below) have instructed `--reason surface-unreachable` since
           # public #15, while this set never actually admitted it: every such call was
           # refused by argparse's own `choices=sorted(REASONS)`, the exact "a shipped file
           # instructs a flag/value its own target refuses" shape check_cli_flags.py now scans
           # for. A page that never opened at all — distinct from `browser-unavailable`
           # (nothing answers) and from public #96's `render-stalled` (the page answered, the
           # click landed, nothing painted — a separate, not-yet-built token).
           "surface-unreachable",
           # design-linkedin-runner-resilience.md §8 (public #47/#96) — closing the two tokens
           # the comment above named as not-yet-built. `pane-held`: a `--take` on
           # `runlock.py --resource pane` was refused because another run genuinely holds it
           # (§1) — distinct from `browser-unavailable` (nothing answers at all). `render-stalled`:
           # the pane's own paint-proof missed twice, 4s apart, while the document stayed visible
           # (§2) — the page answered, a click may have landed, nothing painted. Reusing
           # `browser-unavailable` for either would erase exactly the signal these two issues say
           # is missing; a code exists to be counted.
           "pane-held", "render-stalled"}

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

# ⭐ public #99 — the per-uid TRIAGE disposition an alert-digest sweep writes so a LATER run can
# skip a uid it already surfaced instead of re-fetching and re-screening it every day it still
# falls inside the search window. This copies the ATS sweep's own per-uid idempotency discipline
# (design-inbound-resolution.md §5, dev #376) rather than inventing a second mechanism: ONE
# ledger (this file's `data/runs.jsonl`), not two. Unlike the ATS sweep, whose idempotency mark
# is a permanent `messages.jsonl` row (a resolved receipt is never re-seen), a digest sweep never
# writes to any data store — it only surfaces mail for the run to read — so its own disposition
# lives here as a new event kind rather than riding on a store row that does not exist for it.
#
# A verdict is a CODE, matching REASONS' own "counted, not narrated" rule. `alert_sweep.py` does
# not classify a digest's content today — it only surfaces it — so exactly one verdict exists;
# the set stays a set (not a bare string field) so a future verdict (e.g. a script-side
# duplicate-role check) is a vocabulary addition here, not a free-text drift.
TRIAGE_VERDICTS = {"surfaced"}

# How far back a `triaged` row still counts as a live disposition — BOUNDED, never unbounded
# growth of what a sweep must scan to answer "have I seen this uid before". Unlike the ATS
# sweep's mark (permanent, because a resolved receipt is never re-fetched), a digest uid can
# only ever be RE-FOUND by a later run while it still falls inside that run's own
# `newer_than:Nd` search window — `alert_sweep.py`'s own `--days` (default 1, rarely widened).
# A disposition older than the widest window the sweep can reasonably run can never be re-checked
# against a live search hit, so keeping it forever would only grow the ledger scan for no
# caller that could ever ask about it. The natural ceiling is the sweep's own lookback, capped
# the same way `mail_client.COVERAGE_BACKFILL_MAX_DAYS` caps the coverage ledger's own backfill
# reach, for the identical reason — this module cannot import `mail_client` (`mail_client`
# imports THIS module, so the reverse would be circular), so the number is repeated, not shared;
# both name the ceiling they express, not each other. A uid outside this window is simply
# treated as never-triaged and re-triaged the next time it is found — see `triaged_uids()`.
TRIAGE_TTL_DAYS = 30


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


# ⭐⭐ dev #313 — THE ONE CHOKE POINT, GUARDED ONCE. Every write site in this file — `--fired`,
# `--start`, `--note`, `--gap`, `--gap-closed`, `--end` (including its `footprint`), `--dispose`,
# `record_swept`, `record_probe` — funnels through this single `append()`, so a guard here covers
# all of them without touching each call site individually.
#
# `journal.py --fired` is the FIRST SessionStart hook, ahead of `migrate.py` — so it is the first
# shipped write of any session, and `scripts/run_shipped.py`'s DEFAULT (safe-by-construction) pin
# points `CLAUDESEARCH_ROOT` straight at the tracked, checked-in fixture
# (`plugins/jobsearch/tests/fixtures/profile`) precisely so a maintainer verification has
# somewhere synthetic to run against. That is exactly the path that triggers this: running the
# hook chain against the fixture the safe way silently created an untracked
# `tests/fixtures/profile/data/runs.jsonl` (issue #313).
#
# `_root.is_tracked_fixture()` is the existing, already-shared predicate (`check_engine_purity.py`,
# `check_profile_leakage.py`, `install_rulebook.py` all use it) — this file adds no new predicate,
# only a caller. Per `_root.py`'s own docstring ("this module resolves; it does not decide
# whether the resolution is safe to act on... every WRITE-capable caller decides that for
# itself"), the refusal lives HERE, in the write-capable caller, not inside `_root.py` itself.
#
# The guard is the TRACKED PATH, not the fixture's *shape* — `is_tracked_fixture` matches on
# `.../tests/fixtures/...` or `.../fixtures/...` appearing in the resolved path, so a scratch
# COPY of the fixture (no `fixtures` segment in its path — e.g. `check_shipped_package.py`'s own
# `tmp/profile` materialization) is a different path and is correctly left writable.
def append(root, rec):
    if is_tracked_fixture(root):
        raise JournalError(
            "%s is the tracked fixture — journal refuses to write; pin CLAUDESEARCH_ROOT to a "
            "scratch copy" % root)
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
                if rec.get("event") == "dispatch":
                    missing = [k for k in DISPATCH_FIELDS if k not in rec]
                    unknown = [k for k in rec if k not in DISPATCH_FIELDS]
                    if missing:
                        raise JournalError(
                            "%s line %d dispatch row missing field(s): %s"
                            % (JOURNAL, n, ", ".join(missing)))
                    if unknown:
                        raise JournalError(
                            "%s line %d dispatch row has unknown field(s): %s — this parser "
                            "refuses what it cannot read rather than ignoring it"
                            % (JOURNAL, n, ", ".join(unknown)))
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


def open_gaps(recs, run_id=None):
    """Every open (not `gap-closed`) `gap` event, oldest first — journal-wide by default.

    `run_id`, added for design-linkedin-runner-resilience.md §4 (closes D-5's sibling): when
    given, restricts to gaps opened by THAT run. `--end` uses this to report `gaps_open` (this
    run's own count, so a pass that opened nothing ends clean) alongside the unfiltered
    `gaps_open_all` — an older gap standing elsewhere must stay visible, just not blamed on a
    run that never touched it."""
    closed = {r.get("gap_id") for r in recs if r["event"] == "gap-closed"}
    gaps = [r for r in recs if r["event"] == "gap" and r.get("gap_id") not in closed]
    if run_id is not None:
        gaps = [g for g in gaps if g.get("run_id") == run_id]
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


def record_triaged(root, mailbox, uid, verdict, by, at=None):
    """⭐ public #99 — the completion mark for one triaged uid. `mailbox` is REQUIRED and stored
    alongside `uid` (never a bare `"<mailbox>:<uid>"` string) so two mailboxes that happen to
    reuse the same IMAP uid number are never confused by a caller that filters on `mailbox`
    first, the same shape `record_swept`'s own `mailbox` field already has.

    ⭐ Call this ONLY after a uid's disposition is actually decided — for `alert_sweep.py`, after
    its header fetch and its own row is built, never before. A run killed between fetching a uid
    and calling this leaves NO row for it, so the next run finds it un-triaged and processes it
    again — the same crash-safety the ATS sweep's own uid mark has (design-inbound-resolution.md
    §5): an unwritten disposition is re-seen next run, never silently skipped, by construction
    rather than by a recovery pass."""
    at = at or now_iso()
    if not mailbox:
        raise JournalError("record_triaged requires a mailbox")
    if not uid:
        raise JournalError("record_triaged requires a uid")
    if verdict not in TRIAGE_VERDICTS:
        raise JournalError(
            "record_triaged verdict %r is not in TRIAGE_VERDICTS %r — a verdict is a code, not "
            "a sentence" % (verdict, sorted(TRIAGE_VERDICTS)))
    rec = {"event": "triaged", "mailbox": mailbox, "uid": str(uid), "verdict": verdict,
           "at": at, "by": by or ""}
    return append(root, rec)


def record_dispatch(root, run_id, agent, agent_id, model, tokens, tool_uses, duration_s,
                    outcome, for_="", at=None):
    """⭐ design-script-first.md §8.2 (public #90/#111) — the ONE writer for a `dispatch` row.
    Every numeric field is required and type-checked: a dispatch row nobody can trust the
    numbers of is worse than none (this file's own "unparseable value must be LOUD" rule,
    applied to the cost ledger the fold below builds). `agent_id` is the fold's idempotence
    key — refused empty, the same way `record_probe` refuses an empty `subject`/`thread`."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_dispatch requires run_id")
    if not agent:
        raise JournalError("record_dispatch requires agent")
    if not agent_id:
        raise JournalError("record_dispatch requires agent_id — it is the fold's idempotence key")
    for name, v in (("tokens", tokens), ("tool_uses", tool_uses), ("duration_s", duration_s)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise JournalError("record_dispatch: %s must be an int >= 0 (got %r)" % (name, v))
    rec = {"event": "dispatch", "run_id": run_id, "agent": agent, "agent_id": agent_id,
           "model": model or "", "tokens": tokens, "tool_uses": tool_uses,
           "duration_s": duration_s, "outcome": outcome or "unknown", "for": for_ or "", "at": at}
    return append(root, rec)


def dispatch_rows(recs, today_only=False):
    rows = [r for r in recs if r.get("event") == "dispatch"]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def record_pass(root, run_id, kind, phase, reached=None, unreachable=None, not_attempted=None,
                reason=None, at=None):
    """design-script-first.md §2 (public #75/#87/#110) — the ONE writer for a `pass` row.
    `phase` is validated against `PASS_PHASES`, `kind` against `PASS_KINDS`, `reason` against
    `REASONS` (required for `phase="refused"`, refused otherwise — a reason on a row that is not
    a refusal is not a reason for anything). `reached`/`unreachable`/`not_attempted` are each
    validated against `LINKEDIN_SURFACES` when `kind == "linkedin"` when given at all: an
    unrecognised surface token is refused at write, the same "unparseable value must be LOUD"
    rule this whole file applies everywhere else. Every field is stored even when empty ([] is
    written, not omitted) so a reader never has to tell 'absent' from 'empty list' apart."""
    at = at or now_iso()
    if not run_id:
        raise JournalError("record_pass requires run_id")
    if kind not in PASS_KINDS:
        raise JournalError("record_pass kind %r is not in PASS_KINDS %r" % (kind, PASS_KINDS))
    if phase not in PASS_PHASES:
        raise JournalError("record_pass phase %r is not in PASS_PHASES %r" % (phase, PASS_PHASES))
    if phase == "refused" and reason not in REASONS:
        raise JournalError(
            "record_pass(phase='refused') requires --reason from REASONS %r (got %r)"
            % (sorted(REASONS), reason))
    if phase != "refused" and reason is not None:
        raise JournalError("record_pass: --reason is only for phase='refused' (got phase=%r)"
                           % phase)
    reached = list(reached) if reached is not None else []
    unreachable = list(unreachable) if unreachable is not None else []
    not_attempted = list(not_attempted) if not_attempted is not None else []
    if kind == "linkedin":
        for label, tokens in (("reached", reached), ("unreachable", unreachable),
                              ("not_attempted", not_attempted)):
            bad = sorted(set(tokens) - LINKEDIN_SURFACES)
            if bad:
                raise JournalError(
                    "record_pass %s=%r is not in LINKEDIN_SURFACES %r"
                    % (label, bad, sorted(LINKEDIN_SURFACES)))
    rec = {"event": "pass", "run_id": run_id, "kind": kind, "phase": phase,
           "reached": reached, "unreachable": unreachable, "not_attempted": not_attempted,
           "reason": reason or "", "at": at}
    return append(root, rec)


def pass_rows(recs, kind=None, today_only=False):
    rows = [r for r in recs if r.get("event") == "pass"]
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if today_only:
        today = now_iso()[:10]
        rows = [r for r in rows if str(r.get("at", ""))[:10] == today]
    return rows


def linkedin_passes_reached(recs, today=None):
    """design-script-first.md §2 item 2 — how many of TODAY's LinkedIn passes count against the
    quota: a `returned` row dated today whose `reached` carries at least one surface (#75 — the
    count comes from surfaces the pass actually REACHED, never from a `dispatched` row, so a
    browserless launch that read nothing never consumes the quota). A `dispatched` row with no
    matching `returned` row is a crashed pass (see `crashed_passes` below) and is not counted
    here either."""
    today = today or now_iso()[:10]
    return sum(1 for r in recs
              if r.get("event") == "pass" and r.get("kind") == "linkedin"
              and r.get("phase") == "returned" and str(r.get("at", ""))[:10] == today
              and len(r.get("reached") or []) >= 1)


def crashed_passes(recs):
    """design-script-first.md §2 item 2 — every `dispatched` LinkedIn pass, in a run that has
    ENDED, with no matching `returned` row: dispatched, but nothing proves it ever read a page.
    Printed on its own line by `--may linkedin` / `--passes` rather than silently folded into
    either "counted" or "not counted" — a crashed pass is neither."""
    ended = {r.get("run_id") for r in recs if r.get("event") == "end"}
    dispatched = {r.get("run_id") for r in recs
                 if r.get("event") == "pass" and r.get("kind") == "linkedin"
                 and r.get("phase") == "dispatched"}
    returned = {r.get("run_id") for r in recs
               if r.get("event") == "pass" and r.get("kind") == "linkedin"
               and r.get("phase") == "returned"}
    return sorted((dispatched & ended) - returned)


MEDIA = ("email", "linkedin")

# Query or Citation C1, D14 — a LinkedIn `empty` verifies "no reply" only when the look actually
# covered every surface a reply could sit on: the inbox (both tabs a client can show), pending
# message requests, sent invitations (whose acceptance carries no message but does carry a
# reply-shaped signal), and connection degree (a reply can arrive as an acceptance rather than a
# message). A look that skipped one of these is not evidence of silence — see main()'s --probe
# handling, which refuses --result empty unless --read names all four.
#
# design-linkedin-runner-resilience.md §6 (public #47/#96) — renamed from the bare
# `LINKEDIN_SURFACES` this was before: `notifications` (the bell) is real coverage vocabulary a
# gap scope or a run's report can name, but it is NOT one of the four a reply can sit on — the
# bell has never been the surface a reply was found on, and making it part of the silence proof
# would refuse `--result empty` on every pass where it was unreachable for no reason tied to
# replies at all. `LINKEDIN_SURFACES` below is now the five-token superset.
LINKEDIN_REPLY_SURFACES = frozenset({"inbox", "requests", "invitations", "degree"})

# The coverage vocabulary a gap scope (`linkedin:<token>`) or a runner report names — the four
# reply surfaces above, plus `notifications` (the bell; LinkedIn's algorithmic feed and
# saved-search alerts, a distinct surface neither the inbox nor a deliberate job search reads).
LINKEDIN_SURFACES = LINKEDIN_REPLY_SURFACES | frozenset({"notifications"})

# design-linkedin-runner-resilience.md §6 — the old spelling stays ACCEPTED (profiles already
# carry gap rows written this way) but is no longer the canon a shipped file instructs: every
# `--gap` naming it is normalized to `linkedin:requests` at write time, printed once so the
# normalization is never silent. Rows already on disk keep their stored scope — nothing keys on
# scope, `--close-gap` is by id.
LINKEDIN_MESSAGE_REQUESTS_ALIAS = "linkedin:message-requests"
LINKEDIN_MESSAGE_REQUESTS_CANON = "linkedin:requests"


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


def covered_through(recs, mailbox, as_of=None, by=None):
    """⭐⭐ dev #321 (V0) — THE READER every silence consumer imports. The end (ISO string) of
    the contiguous VERIFIED-coverage interval for `mailbox` that CONTAINS `as_of` — or, with no
    `as_of`, the newest merged interval's end. Returns `None` when nothing verifies coverage
    there: no `swept` rows at all, or `as_of` falls in a gap between them. `None` is the honest
    default on an empty ledger — the caller's job (check_followups.py) is to render "unverified"
    rather than fall back to the wall clock, which is dev #321 itself.

    Coverage is the union of `[from, through]` windows from `ok: true` swept rows for this
    mailbox; a `swept ok: false` row (a failed account) contributes nothing, which is what makes
    a partial failure mark that account uncovered rather than merely annotated.

    ⭐ design-inbound-resolution.md §5 amendment D3 (surface pass 2026-09-14) — `by`, optional,
    filters to rows written by that sweep kind ONLY. Before this fix `by` was ignored entirely,
    so `covered_through(recs, mailbox)` merged EVERY sweep's coverage regardless of which one
    wrote it — a mailbox the daily `alert_sweep` has been covering every day reads as covered
    through today even though `reconcile-ats` has never once run there, so the very first
    `--ats` run saw the daily's 3-day floor instead of the 30-day first-run backfill, and a
    25-day-old decline (public #55) was never even in the searched window. `by=None` keeps the
    old, cross-sweep-kind merge every EXISTING caller relies on (check_followups.verified_as_of,
    the plain `mail_client.lookback_days(..., by=None)` call `watch.py`/`alert_sweep.py`/
    `meeting_check.py` already make) — only a caller that asks for its OWN sweep kind's history
    gets the narrower answer.
    """
    intervals = []
    for r in recs:
        if r.get("event") != "swept" or r.get("mailbox") != mailbox or not r.get("ok"):
            continue
        if by is not None and r.get("by") != by:
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


def triaged_uids(recs, mailbox, by=None, as_of=None, ttl_days=TRIAGE_TTL_DAYS):
    """⭐ public #99 — the set of uid strings already triaged for `mailbox`, within the last
    `ttl_days` of `as_of` (default: now) — what a sweep should SKIP rather than re-fetch and
    re-screen. Read BEFORE any mailbox fetch, exactly the way `covered_through()` is read before
    a sweep decides its own search window.

    `by`, optional, narrows to one sweep kind's own history — the same filter
    `covered_through(..., by=...)` already carries (design-inbound-resolution.md §5 amendment
    D3), so a second sweep that someday triages the same mailbox for a different purpose does
    not silently cover for this one. `mailbox` is matched exactly, never merged across accounts
    — two mailboxes sharing an IMAP uid number are two different rows here, filtered apart the
    same way `covered_through()` never merges two mailboxes' coverage.

    A row older than `ttl_days` is treated as though it were never written — see
    `TRIAGE_TTL_DAYS`'s own docstring for why an aged-out disposition is correct rather than a
    leak: the uid can only be re-found inside a sweep's own bounded search window, so a
    disposition that has outlived every window a sweep could plausibly run can never be checked
    against a live hit anyway."""
    if as_of is None:
        as_of_dt = datetime.datetime.now()
    elif isinstance(as_of, datetime.datetime):
        as_of_dt = as_of
    else:
        as_of_dt = _parse_iso(as_of) or datetime.datetime.now()
    floor = as_of_dt - datetime.timedelta(days=ttl_days)
    out = set()
    for r in recs:
        if r.get("event") != "triaged" or r.get("mailbox") != mailbox:
            continue
        if by is not None and r.get("by") != by:
            continue
        at_dt = _parse_iso(r.get("at"))
        if at_dt is None or at_dt < floor:
            continue
        uid = r.get("uid")
        if uid:
            out.add(str(uid))
    return out


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


def pass_durations(recs):
    """design-linkedin-runner-resilience.md §1 (public #47/#96) — the MEASUREMENT tool behind
    `linkedin.pane_stale_minutes`'s UNVERIFIED default. For every run that both started and
    ended AND carries evidence of LinkedIn work, its wall-clock duration in minutes — longest
    first, so the owner reads the worst case off the top rather than guessing.

    "Carries LinkedIn work" is two different correlations, because a `gap` carries `run_id`
    directly but a `probe` never has (it is pointwise, not run-scoped — see `record_probe`):
    a `gap` whose scope starts with `linkedin:` counts its own `run_id` directly; a `probe` on
    medium `linkedin` counts every run whose [start, end] window contains the probe's `at` —
    the same interval-containment idea `covered_through()` uses, applied to run duration
    instead of mailbox coverage."""
    starts, ends = {}, {}
    for r in recs:
        if r.get("event") == "start":
            starts[r.get("run_id")] = r.get("at")
        elif r.get("event") == "end":
            ends[r.get("run_id")] = r.get("at")
    linkedin_run_ids = {r.get("run_id") for r in recs
                        if r.get("event") == "gap"
                        and str(r.get("scope") or "").startswith("linkedin:")}
    # design-script-first.md §2 — a `pass … phase returned` row carries its own `run_id`
    # directly (unlike a `probe`, which is pointwise): a second, free correlation once the
    # `pass` event exists, no new query needed.
    linkedin_run_ids |= {r.get("run_id") for r in recs
                        if r.get("event") == "pass" and r.get("kind") == "linkedin"
                        and r.get("phase") == "returned"}
    probe_ats = [d for d in (_parse_iso(r.get("at")) for r in recs
                            if r.get("event") == "probe" and r.get("medium") == "linkedin")
                if d is not None]
    out = []
    for rid, s in starts.items():
        e = ends.get(rid)
        if not e:
            continue
        sd, ed = _parse_iso(s), _parse_iso(e)
        if sd is None or ed is None:
            continue
        carries = rid in linkedin_run_ids or any(sd <= p <= ed for p in probe_ats)
        if not carries:
            continue
        out.append({"run_id": rid, "minutes": round((ed - sd).total_seconds() / 60.0, 1),
                    "start": s, "end": e})
    return sorted(out, key=lambda d: -d["minutes"])


def _parse_transcript_ts(raw):
    """A transcript record's own `timestamp`, which — unlike every `at` this journal writes
    itself (always `now_iso()`, naive local time) — may carry a trailing 'Z' (UTC) that
    `datetime.fromisoformat` only accepts from Python 3.11 (this file targets 3.9+). Stripped to
    a naive datetime for comparison against a run's `start.at`: an approximation when the two
    clocks disagree (local vs UTC), stated rather than silently assumed exact — the fold's own
    idempotence (keyed on `agent_id`, not on this filter) is what keeps a borderline miss from
    ever duplicating a row, so an imprecise boundary here costs at most one late fold, never a
    wrong one."""
    if not raw:
        return None
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _parse_iso(s)
    if dt is not None and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _is_agent_result(rec):
    """Duck-typed on the §8.1 measurement (`deployment-auditor`, #82): a transcript record whose
    `toolUseResult` carries `agentId` is an `Agent`/`Task` dispatch's return — no other tool's
    `toolUseResult` shape carries that key. Never assumes a chain-walk to the originating
    `tool_use`'s `name`; the key itself is the signal that was actually measured."""
    tur = rec.get("toolUseResult")
    return isinstance(tur, dict) and bool(tur.get("agentId"))


def _hand_back_text(tur):
    """(text, source) — the hand-back to read `outcome`'s first word from. `content` first (§8.1:
    populated in 53 of 349 measured results); else the first line of `outputFile`, opened only
    when `canReadOutputFile` (#82: `content` is `None` in 296 of 349 — the common case). `(None,
    "none")` when neither is available — never a guess."""
    content = tur.get("content")
    if content:
        if isinstance(content, str):
            return content, "content"
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("text")]
            if texts:
                return " ".join(texts), "content"
        return str(content), "content"
    output_file = tur.get("outputFile")
    if output_file and tur.get("canReadOutputFile"):
        try:
            with open(output_file, encoding="utf-8") as fh:
                return fh.read(), "outputFile"
        except OSError:
            return None, "outputFile-unreadable"
    return None, "none"


def _outcome_from_text(text):
    word = (text or "").strip().split()[0] if text and text.strip() else ""
    key = re.sub(r"[^A-Za-z]", "", word).lower()
    if not key:
        return "unknown"
    return OUTCOME_MAP.get(key, key)


def _fields_from_agent_result(rec):
    """(fields, refusal_reason) — `fields` is the writer-ready dict (minus `event`/`run_id`/
    `at`) for ONE `Agent` toolUseResult, or `None` with a reason when a required §8.1 field is
    missing: 'refused loudly' rather than silently defaulted, so a malformed result never reads
    as a free, zero-cost dispatch."""
    tur = rec.get("toolUseResult") or {}
    agent_id = tur.get("agentId")
    agent = tur.get("agentType")
    tokens = tur.get("totalTokens")
    tool_uses = tur.get("totalToolUseCount")
    duration_ms = tur.get("totalDurationMs")
    missing = [k for k, v in (("agentId", agent_id), ("agentType", agent),
                              ("totalTokens", tokens), ("totalToolUseCount", tool_uses),
                              ("totalDurationMs", duration_ms)) if v is None]
    if missing:
        return None, "missing %s" % ", ".join(missing)
    text, _source = _hand_back_text(tur)
    prompt = tur.get("prompt") or ""
    for_ = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
    return {"agent": agent, "agent_id": agent_id, "model": tur.get("resolvedModel") or "",
           "tokens": int(tokens), "tool_uses": int(tool_uses),
           "duration_s": int(round(duration_ms / 1000.0)), "outcome": _outcome_from_text(text),
           "for": for_}, None


def fold_dispatches(root, run_id, transcript_path=None, at=None):
    """design-script-first.md §8.2 (public #82/#90/#91) — the PROVEN path (the `PostToolUse`
    hook is the unverified primary and is not built by this function). Resolves the transcript
    from `transcript_path` when given (tests), else this session's stash
    (`_root.transcript_stash_path()`); a surface with neither prints `no transcript on this
    surface` and writes nothing — never a false zero read as fact. Every `Agent` result strictly
    newer than the run's own `--start` is a candidate; idempotent on `agent_id`, so a second fold
    over the same transcript adds nothing. Returns (written, skipped, refused) — `refused`
    entries are printed loudly to stderr, one per malformed result, and never silently dropped."""
    recs = read(root)
    start_rec = next((r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id),
                     None)
    if start_rec is None:
        raise JournalError("--fold-dispatches --run %r: no matching --start run — get one from "
                           "--start" % run_id)
    start_dt = _parse_iso(start_rec.get("at"))

    if transcript_path is None:
        try:
            with open(transcript_stash_path(), encoding="utf-8") as fh:
                transcript_path = fh.read().strip() or None
        except OSError:
            transcript_path = None
    if not transcript_path:
        print("no transcript on this surface")
        return 0, 0, []
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as e:
        print("no transcript on this surface (%s)" % e)
        return 0, 0, []

    already = {r.get("agent_id") for r in recs if r.get("event") == "dispatch"}
    written, skipped, refused = 0, 0, []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or not _is_agent_result(rec):
            continue
        ts = _parse_transcript_ts(rec.get("timestamp"))
        if ts is None or (start_dt is not None and ts < start_dt):
            continue
        fields, reason = _fields_from_agent_result(rec)
        if fields is None:
            hint = (rec.get("toolUseResult") or {}).get("agentId") or "?"
            print("⛔ dispatch fold: result %s refused — %s" % (hint, reason), file=sys.stderr)
            refused.append(hint)
            continue
        if fields["agent_id"] in already:
            skipped += 1
            continue
        record_dispatch(root, run_id=run_id, agent=fields["agent"],
                        agent_id=fields["agent_id"], model=fields["model"],
                        tokens=fields["tokens"], tool_uses=fields["tool_uses"],
                        duration_s=fields["duration_s"], outcome=fields["outcome"],
                        for_=fields["for"], at=at or now_iso())
        already.add(fields["agent_id"])
        written += 1
    print("folded %d dispatch row(s) for %s (%d already recorded, %d refused)"
         % (written, run_id, skipped, len(refused)))
    return written, skipped, refused


def _percentile(sorted_vals, p):
    """Linear-interpolation percentile over an already-sorted, non-empty list — copied from
    `scripts/dispatch_ledger.py` (the MAINTENANCE ledger, at the marketplace repo root): that
    module is never importable from a SHIPPED file, so the shape is duplicated, not shared, the
    same reasoning `TRIAGE_TTL_DAYS`'s own docstring already states for `mail_client.py`."""
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    k = (p / 100.0) * (n - 1)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return float(sorted_vals[f])
    d = k - f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * d


def cmd_calibrate_dispatches(root):
    rows = dispatch_rows(read(root))
    print("DISPATCH --calibrate (per agent — token/tool_use quantiles, no recommendation)")
    if not rows:
        print("  no dispatch rows yet.")
        return 0
    by_agent = {}
    for r in rows:
        by_agent.setdefault(r.get("agent"), {"tokens": [], "tool_uses": []})
        by_agent[r.get("agent")]["tokens"].append(r.get("tokens", 0))
        by_agent[r.get("agent")]["tool_uses"].append(r.get("tool_uses", 0))
    for agent in sorted(by_agent):
        toks = sorted(by_agent[agent]["tokens"])
        tus = sorted(by_agent[agent]["tool_uses"])
        print("  %-24s n=%-4d tool_uses min=%-5d p50=%-7.1f p90=%-7.1f max=%-5d  "
             "tokens min=%-8d p50=%-9.1f p90=%-9.1f max=%-8d"
             % (agent, len(toks), tus[0], _percentile(tus, 50), _percentile(tus, 90), tus[-1],
                toks[0], _percentile(toks, 50), _percentile(toks, 90), toks[-1]))
    return 0


def cmd_dispatches(root, today_only=False, calibrate=False):
    rows = dispatch_rows(read(root), today_only=today_only)
    print("DISPATCHES%s" % (" (today)" if today_only else ""))
    if not rows:
        print("  none.")
    else:
        for r in sorted(rows, key=lambda r: r.get("at", "")):
            print("  %-19s %-22s run=%-26s tokens=%-7d tool_uses=%-4d %-8s for=%s"
                 % (str(r.get("at", ""))[:19], r.get("agent"), r.get("run_id"),
                    r.get("tokens", 0), r.get("tool_uses", 0), r.get("outcome"),
                    r.get("for") or "-"))
        by_agent, by_run = {}, {}
        for r in rows:
            a = by_agent.setdefault(r.get("agent"), [0, 0])
            a[0] += r.get("tokens", 0)
            a[1] += r.get("tool_uses", 0)
            rn = by_run.setdefault(r.get("run_id"), [0, 0])
            rn[0] += r.get("tokens", 0)
            rn[1] += r.get("tool_uses", 0)
        print("  by agent:")
        for a in sorted(by_agent):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (a, by_agent[a][0], by_agent[a][1]))
        print("  by run:")
        for rn in sorted(by_run):
            print("    %-24s tokens=%-8d tool_uses=%-5d" % (rn, by_run[rn][0], by_run[rn][1]))
    if calibrate:
        print()
        cmd_calibrate_dispatches(root)
    return 0


def cmd_passes(root, today_only=False):
    """design-script-first.md §2 — every `pass` row, oldest first, plus the crashed-pass line
    (a `dispatched` row in an ended run with no matching `returned`). `0 passes` on an empty
    journal, exit 0 either way — this is a report, never a gate."""
    recs = read(root)
    rows = pass_rows(recs, today_only=today_only)
    label = "%d passes%s" % (len(rows), " today" if today_only else "")
    print(label if rows else "0 passes")
    for r in sorted(rows, key=lambda r: r.get("at", "")):
        bits = "%-19s %-8s %-10s run=%s" % (str(r.get("at", ""))[:19], r.get("kind"),
                                            r.get("phase"), r.get("run_id"))
        if r.get("phase") == "returned":
            bits += (" reached=%s unreachable=%s not_attempted=%s"
                    % (",".join(r.get("reached") or []) or "-",
                       ",".join(r.get("unreachable") or []) or "-",
                       ",".join(r.get("not_attempted") or []) or "-"))
        elif r.get("phase") == "refused":
            bits += " reason=%s" % (r.get("reason") or "-")
        print("  %s" % bits)
    crashed = crashed_passes(recs)
    if crashed:
        print("  pass dispatched, never returned (%s)" % ", ".join(crashed))
    return 0


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
    ap.add_argument("--run", metavar="ID",
                    help="the run this call concerns — with --note/--gap/--end/--dispose/"
                         "--pass/--fold-dispatches, the run being written to; with --check "
                         "(or any other read-only report), the CALLER's own still-executing "
                         "run, excluded from the dead-run check (dev #474/public #119)")
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
    ap.add_argument("--pass-durations", dest="pass_durations", action="store_true",
                    help="read: wall-clock duration of every run carrying LinkedIn work (a "
                         "linkedin:* gap, or a linkedin probe inside its [start,end] window), "
                         "longest first — measures linkedin.pane_stale_minutes instead of "
                         "guessing it (design-linkedin-runner-resilience.md §1)")
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
    ap.add_argument("--fold-dispatches", dest="fold_dispatches", action="store_true",
                    help="with --run <id>: fold this run's Agent/Task dispatch results out of "
                         "the session transcript into `dispatch` rows (design-script-first.md "
                         "§8.2, public #90/#111) — idempotent on agent_id")
    ap.add_argument("--transcript", metavar="PATH",
                    help="with --fold-dispatches: read this transcript instead of the session's "
                         "own stash (tests; advanced use)")
    ap.add_argument("--dispatches", action="store_true",
                    help="print dispatch rows, summed per agent and per run")
    ap.add_argument("--today", action="store_true", help="with --dispatches: only today's rows")
    ap.add_argument("--calibrate", action="store_true",
                    help="with --dispatches (or standalone): per-agent tool_use/token quantiles "
                         "— numbers only, no recommendation")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="with --check: only sum dispatch rows dated on/after this date")
    ap.add_argument("--pass", dest="pass_kind", metavar="KIND", choices=PASS_KINDS,
                    help="with --run: record a pass event, e.g. 'linkedin' — needs --phase")
    ap.add_argument("--phase", choices=PASS_PHASES,
                    help="with --pass: dispatched | returned | refused")
    ap.add_argument("--reached", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--unreachable", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--not-attempted", dest="not_attempted", metavar="SURFACES", default="",
                    help="with --pass --phase returned: comma-separated LINKEDIN_SURFACES")
    ap.add_argument("--passes", action="store_true",
                    help="print every pass row by phase, oldest first (design-script-first.md "
                         "§2) — '0 passes' on an empty journal")
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
            # (`--gap linkedin:requests --reason surface-unreachable`) under the run that
            # attempted the look. This refusal is what keeps a partial read from being written
            # as if it were a complete one; it does not invent a second gap mechanism.
            #
            # design-linkedin-runner-resilience.md §6 — checked against LINKEDIN_REPLY_SURFACES
            # (the four a reply can sit on), never the five-token LINKEDIN_SURFACES: `notifications`
            # joining the coverage vocabulary must not make it required for a silence proof.
            if args.medium == "linkedin" and args.result == "empty":
                read_surfaces = {s.strip() for s in (args.read or "").split(",") if s.strip()}
                missing = LINKEDIN_REPLY_SURFACES - read_surfaces
                if missing:
                    raise JournalError(
                        "--result empty refused (D14) — --read did not name %s. A LinkedIn "
                        "look that skips a surface a reply could sit on is not evidence of "
                        "silence. File the gap instead: journal.py --run <id> --gap "
                        "linkedin:requests --reason surface-unreachable ..."
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

        if args.pass_durations:
            durs = pass_durations(read(root))
            if not durs:
                print("No completed run carries LinkedIn evidence (a linkedin:* gap or a "
                      "linkedin probe) yet — nothing to measure linkedin.pane_stale_minutes "
                      "against.")
                return 0
            print("LINKEDIN PASS DURATIONS — longest first "
                  "(measures linkedin.pane_stale_minutes)\n")
            for d in durs:
                print("  %7.1f min  %s  (%s -> %s)"
                      % (d["minutes"], d["run_id"], d["start"], d["end"]))
            return 0

        if args.fold_dispatches:
            if not args.run:
                raise JournalError("--fold-dispatches requires --run <id> (get one from --start)")
            _written, _skipped, refused = fold_dispatches(root, args.run,
                                                          transcript_path=args.transcript, at=at)
            return 2 if refused else 0

        if args.dispatches or args.calibrate:
            if args.dispatches:
                cmd_dispatches(root, today_only=args.today, calibrate=args.calibrate)
            else:
                cmd_calibrate_dispatches(root)
            return 0

        if args.passes:
            cmd_passes(root, today_only=args.today)
            return 0

        if args.note or args.gap or args.end or args.close_gap or args.dispose or args.pass_kind:
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
                scope = args.gap
                if scope == LINKEDIN_MESSAGE_REQUESTS_ALIAS:
                    # design-linkedin-runner-resilience.md §6 — the old spelling is still
                    # ACCEPTED (rows already on disk say it) but is normalized at write time so
                    # the tree never carries two spellings as canon going forward.
                    print("normalizing gap scope %r -> %r"
                          % (LINKEDIN_MESSAGE_REQUESTS_ALIAS, LINKEDIN_MESSAGE_REQUESTS_CANON))
                    scope = LINKEDIN_MESSAGE_REQUESTS_CANON
                covered_by = normalize_citation(args.covered_by) if args.covered_by else ""
                gid = "%s:%s" % (args.run, re.sub(r"[^A-Za-z0-9:._-]+", "-", scope))
                append(root, {"event": "gap", "run_id": args.run, "gap_id": gid,
                              "scope": scope, "reason": args.reason,
                              "covered_by": covered_by,
                              "closes_when": args.closes_when or "", "at": at})
                print(gid)
            if args.end:
                # design-linkedin-runner-resilience.md §4 (closes D-5) — derived at write time,
                # never a new --end argument: THIS run's own open gaps (a pass that opened
                # nothing ends clean) alongside the journal-wide count (an older gap standing
                # elsewhere stays visible in gaps_open_all and --check, never hidden by a clean
                # --end elsewhere).
                recs_before_end = read(root)
                gaps_open_run = len(open_gaps(recs_before_end, run_id=args.run))
                gaps_open_all = len(open_gaps(recs_before_end))
                rec = {"event": "end", "run_id": args.run, "at": at,
                       "gaps_open": gaps_open_run, "gaps_open_all": gaps_open_all}
                # ⭐⭐ public #85 — THE FOOTPRINT IS DEFINED ONCE, in `run_summary.py`, and
                # written HERE, on the `end` event, so `check_runs.py` can ask "did this run
                # leave a footprint nobody flagged?" without recomputing anything itself.
                # Imported LAZILY (never at module top) so this foundational ledger module
                # never depends on the higher-level reporting script at import time — only
                # this branch ever needs it, and by the time it runs, `journal` itself is
                # already fully loaded, so `run_summary`'s own `import journal` cannot see a
                # half-built module (see run_summary.py's own docstring for the full reasoning
                # on why the dependency runs this direction and not the other).
                try:
                    from run_summary import footprint as _footprint
                    rec["footprint"] = _footprint(root, args.run, at=at)
                except Exception as e:                        # noqa: BLE001 — never block --end
                    print("⚠️ journal.py --end: footprint could not be computed (%s) — the end "
                          "event was recorded WITHOUT one; check_runs.py will flag this run"
                          % e, file=sys.stderr)
                append(root, rec)
                print("ended (gaps_open: %d, gaps_open_all: %d)"
                      % (gaps_open_run, gaps_open_all))
            if args.dispose:
                append(root, {"event": "dispose", "run_id": args.run,
                              "because": args.because or "", "at": at})
                print("disposed %s" % args.run)
            if args.pass_kind:
                if not args.phase:
                    raise JournalError("--pass requires --phase (dispatched|returned|refused)")
                reached = [s.strip() for s in args.reached.split(",") if s.strip()]
                unreachable = [s.strip() for s in args.unreachable.split(",") if s.strip()]
                not_attempted = [s.strip() for s in args.not_attempted.split(",") if s.strip()]
                record_pass(root, args.run, args.pass_kind, args.phase,
                           reached=reached, unreachable=unreachable,
                           not_attempted=not_attempted, reason=args.reason, at=at)
                print("pass %s %s recorded" % (args.pass_kind, args.phase))
            return 0

        recs = read(root)
        dead = unfinished(recs)
        if args.run:
            # ⭐ dev #474 (public #119) — a run invoking `--check` (or any of the read-only
            # reports below) WHILE it is still executing is not dead; it is the very run
            # asking. An unmatched `start` with no `end` yet is exactly what an alive,
            # still-in-progress session looks like from the journal's own side — there is no
            # way to distinguish "alive, mid-run" from "actually died" without the run naming
            # itself. `--run <id>` here IS that self-identification: it carves the caller's
            # own id out of the dead-run set before the bare summary, `--json`,
            # `--unfinished`, or `--check`'s own exit code ever sees it. A genuinely dead
            # OTHER run (a different id) is unaffected.
            dead = [d for d in dead if d["run_id"] != args.run]
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
            # design-script-first.md §8.2/§11 item 1 (public #90/#111) — reused shape, not the
            # maintenance ledger's own semantics: `token_ceiling_per_run`/`_per_day` (§8.3) do
            # not exist yet (build-list item 4), so there is no ladder to refuse against. This
            # reports and NEVER refuses until that ceiling lands — stated here rather than
            # silently returning green for a check that cannot yet fail.
            drows = dispatch_rows(recs)
            if args.since:
                drows = [r for r in drows if str(r.get("at", "")) >= args.since]
            print("\nDISPATCH --check%s" % (" (since %s)" % args.since if args.since else ""))
            print("  %d dispatch row(s) · tokens %d · tool_uses %d"
                  % (len(drows), sum(r.get("tokens", 0) for r in drows),
                     sum(r.get("tool_uses", 0) for r in drows)))
            print("  NOT ENFORCED: token_ceiling_per_run/token_ceiling_per_day do not exist yet "
                  "(design-script-first.md §8.3, build-list item 4) — reporting only, never "
                  "refusing.")
            return 1 if (stale or lost) else 0
        return 0

    except JournalError as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
