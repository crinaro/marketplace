#!/usr/bin/env python3
"""The run's own footprint, queried — never composed. Public #85.

WHY THIS EXISTS
----------------
A scheduled daily run posted a coordinator-queue summary asserting "no change across mail, the
professional network, and sourcing." In the same run it had recorded a genuine inbound reply and
repaired a pre-existing gap in the message store — real writes. Neither was committed; both sat
in the working tree until a later, unrelated session happened to run `git status`. The summary
was composed independently of what the run actually did, and the run ended with a dirty tree it
never flagged anywhere.

⭐ THE STANDING RULE (CLAUDE.md): a fact a run knows comes out of the queryable store, never out
of narrative. So the summary is not written; it is COMPUTED — a query over this run's own journal
events (`swept` / `probe` / `note` / `gap`) and its own `git status --porcelain` / `git diff
--stat` at the moment of the call. The model may `--annotate` free text UNDER the generated
headline; it can never alter the headline's CHANGED / NO CHANGE claim, and an annotation that
contradicts the machine-measured footprint is refused outright rather than posted.

⭐⭐ THE FOOTPRINT SHAPE IS DEFINED ONCE, HERE (`footprint()`) — `journal.py --end` imports this
function (lazily, so the foundational ledger module never depends on this higher-level one at
import time — see that file's own comment) and writes its result onto the `end` event; this
script's own `--post` calls the same function again, independently, at its own (earlier) moment
in the run. **The two calls are NOT required to agree in value** — they measure the tree at two
different points on purpose: `--post` runs BEFORE the commit (so a real diff shows up as the
run's substance), `--end` runs AFTER the commit/push attempt, as the run's genuinely last action
(so a clean tree there is the proof the writes actually persisted, and a dirty one is exactly
#85's failure — a run that wrote and never committed). `check_runs.py` reads both independently:
an `end` event with no `footprint` field at all (the computation failed, or the run predates this
feature) is its own loud finding, separate from a `--post` whose OWN headline disagreed with its
OWN stored footprint.

⭐ dev #703 / public #155 — THE POSTED TEXT IS CHECKED WHOLE, AT POST TIME. `--annotate` was
already refused when it contradicted the footprint (public #85), but the detail also carries the
run's own journal `note` rows (`journal.py --note`, append-only), and a note beginning "Quiet
run." was stored beside a footprint that showed writes — `check_runs.py` then went red on it at
the next session start, after the contradiction was already durable. `--post` now runs the SAME
`disagrees()` over the text `check_runs.py` will later read (headline + detail, annotation
included), and the two sources are treated DIFFERENTLY on purpose:

  * An `--annotate` text that disagrees is REFUSED (exit 2, nothing posted, the phrase and the
    text named): the caller can reword it and post again.
  * A JOURNAL NOTE that disagrees is WITHHELD, and the post goes ahead (exit 0). A note already
    in the journal cannot be un-written, so refusing the post would leave a run that wrote
    "Quiet run." unable to post its summary at all — and an unattended run would lose the summary
    entirely, where §14 of the daily-run skill requires one even on a quiet run. The headline is
    still generated from the footprint; the contradicting note is replaced in the detail by
    `note withheld: it claimed '<phrase>' but the footprint shows <N> changed file(s)`, and a line
    naming the phrase goes to stderr. The stored row therefore never carries the contradiction.

`disagrees()` knows that marker (it strips it before scanning), because the marker quotes the very
phrase it withheld: without that, `check_runs.py` would flag every row this script posts with a
withheld note. A row stored BEFORE this change, with the contradiction in its detail, is still
flagged by `check_runs.py` as it always was. One definition: there is no second phrase list here
and none in `check_runs.py`.

⭐ dev #703 — THE FOOTPRINT ALSO COUNTS WHAT THE RUN COMMITTED. `files` is `git diff --stat
HEAD`: only what is still uncommitted. A run that commits mid-way (to settle a tree before a
sync, say) would understate its own change to the point of calling itself quiet. `journal.py
--start` therefore records the HEAD it started on (`start_sha`, a new optional field on new
`start` events only) and the footprint adds `committed`: `git diff --name-only <start_sha> HEAD`.
`None` means NOT MEASURED, never "nothing committed": a run started before this field existed,
a start sha git cannot resolve (history rewritten), or no git at all. The detail line then says
`committed: not measured (no start sha)`, and the rest of the footprint is measured exactly as
before. Two stated limits: (1) the journal file itself (`data/runs.jsonl`) is not counted, since
`--start` writes it, so counting it would make every run that ever commits "changed" by
construction; (2) the range is a plain commit range, so a `git pull` mid-run that brings in
OTHER sessions' commits counts too. That over-states, which fails safe: a quiet claim is
refused when in doubt. Untracked files are not listed by git diff; they still count through
`tree_dirty`.

Usage:
    python3 run_summary.py --run <id>                       # print the generated summary
    python3 run_summary.py --run <id> --post                # ...and post it to the inbox
    python3 run_summary.py --run <id> --post --annotate "…" # + free text UNDER the headline
    python3 run_summary.py --run <id> --check "<posted text>"
        # does <posted text>'s change/no-change claim agree with this run's own footprint?
        # (the check_stale_claims.py shape: scans for 'no change'/'nothing new'/'quiet run'/
        # 'no replies' and is red only when the footprint shows the claim is false)

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root
import journal as _journal
import inbox as _inbox

# ⭐ public #85 (§B.3, the check_stale_claims.py shape) — a posted text is red only when it
# CONTAINS one of these AND the footprint it is describing shows real activity. Absence of a
# phrase is never itself a finding; this scans for the specific claim the incident made.
NO_CHANGE_PHRASES = ("no change", "nothing new", "quiet run", "no replies")

_DIFFSTAT_FILE_RE = re.compile(r"^\s*(.+?)\s+\|\s+\d+")
_DIFFSTAT_SUMMARY_RE = re.compile(
    r"(\d+)\s+files? changed(?:,\s*(\d+)\s+insertions?\(\+\))?(?:,\s*(\d+)\s+deletions?\(-\))?")


class RunSummaryError(ValueError):
    """A footprint that cannot be computed. Loud on purpose — a run id with no `start` event
    has no window to measure anything against, and guessing one would be worse than refusing."""


def _git(root, *args):
    """None means "could not ask" (no git, no repo, a timeout) — NEVER treated as "clean". A
    profile is guaranteed to be a git repository by the time anything here runs (sync.py's own
    precondition), so this is a defensive fallback, not the expected path."""
    try:
        r = subprocess.run(["git", "-C", root] + list(args),
                           capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def _parse_diffstat(text):
    if not text:
        return [], 0, 0
    files, insertions, deletions = [], 0, 0
    for line in text.splitlines():
        m = _DIFFSTAT_FILE_RE.match(line)
        if m:
            files.append(m.group(1).strip())
            continue
        m = _DIFFSTAT_SUMMARY_RE.search(line)
        if m:
            insertions = int(m.group(2) or 0)
            deletions = int(m.group(3) or 0)
    return files, insertions, deletions


def _tree_dirty_count(porcelain):
    if porcelain is None:
        return None
    return len([l for l in porcelain.splitlines() if l.strip()])


def _run_window(recs, run_id, at=None):
    """(start_at, as_of) for this run — the ONLY place this window is computed, because
    `swept`/`probe` rows carry no `run_id` of their own (see journal.py's own shapes) and must
    be attributed by TIME instead. `at`, when given, is the call's own timestamp (tests pass a
    fixed one via `--at`, matching journal.py's own convention); otherwise "now"."""
    starts = [r for r in recs if r.get("event") == "start" and r.get("run_id") == run_id]
    if not starts:
        raise RunSummaryError(
            "no journal 'start' event for run %r — a footprint needs a window to measure "
            "swept/probe coverage against, and there is nothing here to build one from" % run_id)
    start_at = starts[0].get("at") or ""
    as_of = at or _journal.now_iso()
    return start_at, as_of, starts[0].get("kind")


_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _start_sha(recs, run_id):
    """The HEAD `journal.py --start` recorded for this run, or None (an older `start` event, or
    git could not be asked at the time). A malformed value is None too: a start sha is data read
    back from a file, and it is handed to git, so it must look like a sha or it is not used."""
    for r in recs:
        if r.get("event") == "start" and r.get("run_id") == run_id:
            sha = r.get("start_sha")
            return sha if isinstance(sha, str) and _SHA_RE.match(sha) else None
    return None


def committed_paths(root, start_sha):
    """dev #703 / public #155 — the paths this run committed: `git diff --name-only <start_sha>
    HEAD`, minus the journal file (see the module docstring for both limits). None means NOT
    MEASURED — no start sha, or git cannot resolve it — and is never an empty list: an
    unmeasured value must not read as "nothing was committed"."""
    if not start_sha:
        return None
    out = _git(root, "diff", "--name-only", "-z", start_sha, "HEAD", "--")
    if out is None:
        return None
    journal = _journal.JOURNAL.replace(os.sep, "/")
    return sorted(p for p in out.split("\0") if p and p != journal)


def footprint(root, run_id, recs=None, at=None):
    """⭐⭐ THE ONE SHAPE — see the module docstring. Returns a JSON-safe dict:

        files          [changed filename, ...]   — from `git diff --stat HEAD` (uncommitted)
        committed      [path, ...] or None        — dev #703: paths committed since the run's
                                                      recorded `start_sha`; None = NOT MEASURED
                                                      (no usable start sha), never "none"
        insertions     int
        deletions      int
        tree_dirty     int or None                — `git status --porcelain` line count;
                                                      None means "could not be verified"
        swept_ok       int                         — successful `swept` rows in this run's window
        swept_failed   [mailbox, ...]              — failed `swept` rows in this run's window
        probes         int                         — `probe` rows in this run's window
        gaps_open      [gap_id, ...]               — gaps THIS run opened that are still open
        notes          int                         — `note` rows this run wrote (run_id-tagged)

    `notes`, `gaps_open` are attributed by the journal's own `run_id` field (exact); `swept`,
    `probe` have none and are attributed by falling inside [start_at, as_of] instead — stated
    here rather than silently assumed, because it is the one approximation in an otherwise exact
    computation.
    """
    recs = _journal.read(root) if recs is None else recs
    start_at, as_of, _kind = _run_window(recs, run_id, at=at)

    def _in_window(r):
        when = r.get("at") or ""
        return start_at <= when <= as_of

    swept = [r for r in recs if r.get("event") == "swept" and _in_window(r)]
    probes = [r for r in recs if r.get("event") == "probe" and _in_window(r)]
    notes = [r for r in recs if r.get("event") == "note" and r.get("run_id") == run_id]
    gaps = [g for g in _journal.open_gaps(recs) if g.get("run_id") == run_id]

    porcelain = _git(root, "status", "--porcelain")
    diffstat = _git(root, "diff", "--stat", "HEAD")
    files, insertions, deletions = _parse_diffstat(diffstat)

    return {
        "files": files,
        "committed": committed_paths(root, _start_sha(recs, run_id)),
        "insertions": insertions,
        "deletions": deletions,
        "tree_dirty": _tree_dirty_count(porcelain),
        "swept_ok": sum(1 for r in swept if r.get("ok")),
        "swept_failed": [r.get("mailbox") for r in swept if not r.get("ok")],
        "probes": len(probes),
        "gaps_open": [g.get("gap_id") for g in gaps],
        "notes": len(notes),
    }


def changed(fp):
    """Is there anything to report? `swept_ok` (a sweep that ran and found nothing) never
    counts — only a FAILURE or something actually found does. Paths the run COMMITTED count
    (dev #703): a mid-run commit leaves a clean tree and must not read as quiet. `tree_dirty is None` (git could
    not be asked) counts as changed: an unverifiable tree must never be reported as clean."""
    if fp.get("tree_dirty") is None:
        return True
    return bool(fp.get("tree_dirty") or fp.get("notes") or fp.get("probes")
                or fp.get("swept_failed") or fp.get("gaps_open")
                or fp.get("committed"))             # dev #703: None (unmeasured) and [] are falsy


# dev #703 / public #155 — the visible stand-in for a journal note that contradicted the footprint.
# It quotes the phrase it withheld, so `disagrees()` must not read the quote as a claim.
_WITHHELD_RE = re.compile(
    r"note withheld: it claimed '(?:%s)' but the footprint shows \d+ changed file\(s\)"
    % "|".join(re.escape(p) for p in NO_CHANGE_PHRASES))


def withheld_marker(phrase, fp):
    """The marker text that replaces a contradicting journal note (dev #703 / public #155)."""
    n = len(set(fp.get("files") or []) | set(fp.get("committed") or []))
    return "note withheld: it claimed '%s' but the footprint shows %d changed file(s)" % (phrase, n)


def disagrees(text, fp):
    """(bool, phrase) — does `text` claim "no change" (one of NO_CHANGE_PHRASES) while `fp`
    shows the claim is false? The check_stale_claims.py shape: absence of a phrase is never
    itself a finding, and a footprint that genuinely shows nothing makes the same phrase TRUE,
    never flagged (public #85 plant: "the same with an empty footprint ... is correct, green").
    A `withheld_marker()` quotes the phrase it replaced and is not itself a claim (dev #703)."""
    low = _WITHHELD_RE.sub("", (text or "").lower())
    if not changed(fp):
        return False, None
    for phrase in NO_CHANGE_PHRASES:
        if phrase in low:
            return True, phrase
    return False, None


def withheld_notes(recs, run_id, fp):
    """[(note_text, phrase)] — this run's journal notes whose text disagrees with `fp`, by the one
    `disagrees()`. Full note text is checked (not just the 80 characters the detail shows): a
    phrase past the cut-off would still be a claim in the journal."""
    out = []
    for n in recs:
        if n.get("event") == "note" and n.get("run_id") == run_id:
            text = str(n.get("text") or "")
            bad, phrase = disagrees(text, fp)
            if bad:
                out.append((text, phrase))
    return out


def _fmt_when(at):
    try:
        dt = datetime.datetime.fromisoformat(at)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return at or "unknown time"


def render_headline(recs, run_id, fp):
    start_at, _as_of, kind = _run_window(recs, run_id)
    label = "%s run" % kind.capitalize() if kind else "Run"
    when = _fmt_when(start_at)
    swept_total = fp["swept_ok"] + len(fp["swept_failed"])
    if changed(fp):
        if fp.get("tree_dirty") is None:
            head = "%s %s — GIT UNAVAILABLE: tree state could not be verified" % (label, when)
        else:
            head = ("%s %s — CHANGED: %d file(s) (+%d/-%d) · swept %d/%d mailbox(es) · "
                    "%d probe(s) · %d gap(s) open"
                    % (label, when, len(fp["files"]), fp["insertions"], fp["deletions"],
                       fp["swept_ok"], swept_total, fp["probes"], len(fp["gaps_open"])))
            if fp.get("committed"):
                head += " · %d path(s) committed this run" % len(fp["committed"])
    else:
        head = ("%s %s — NO CHANGE: tree clean · swept %d/%d · %d probe(s) · %d gap(s)"
                % (label, when, fp["swept_ok"], swept_total, fp["probes"], len(fp["gaps_open"])))
    if fp.get("swept_failed"):
        # ⭐ public #85 plant — the headline NAMES the incomplete account; a failure is never
        # folded into a bare count nobody can act on.
        head += " · INCOMPLETE: %s" % ", ".join(fp["swept_failed"])
    return head


def _geos(root):
    """The geographies a wide re-scan must cover, from this profile's config (dev #489)."""
    import json
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    return _journal.jobsearch_geos(cfg)


def _quarantine_clause(e):
    """dev #722 / public #156 -- ` · N quarantined (truncated ×a, filter-dropped ×b)` for a `roles`
    event that held any role, else the empty string. COMPUTED from the event's own counts. An event
    written before 0.69.0 has no `quarantined` field and prints nothing."""
    n = e.get("quarantined", 0)
    if not n:
        return ""
    reasons = e.get("quarantine_reasons") or {}
    why = ", ".join("%s ×%d" % (code, reasons[code]) for code in sorted(reasons))
    return " · %d quarantined%s" % (n, (" (%s)" % why) if why else "")


def _query_reads_line(e, label=None):
    """dev #722 / public #156 (R4) -- how each REACHED query read, from the event's own counts:
    `query reads (board): 12 reached · 10 clean · 1 filters unread · 1 degraded (truncated ×1) · 2
    total unknown`. Empty for an event written before 0.69.0 (no `q_reached`), which is not the
    same as a pass that reached nothing. SHAPE, not enforced: these count what the sweep SAID, so a
    sweep that never looks reads all-clean here, and `check_runs.py` flags a week of that."""
    if "q_reached" not in e:
        return None
    degraded = e.get("q_degraded") or {}
    why = (" (%s)" % ", ".join("%s ×%d" % (c, degraded[c]) for c in sorted(degraded))
           if degraded else "")
    return ("query reads%s: %d reached · %d clean · %d filters unread · %d degraded%s · %d total "
            "unknown" % ((" (%s)" % label) if label else " (wide)", e.get("q_reached", 0),
                         e.get("q_clean", 0), e.get("q_unread", 0), e.get("q_degraded_queries", 0),
                         why, e.get("q_total_unknown", 0)))


def feeds_line(e):
    """dev #751 -- the company-feed line, COMPUTED from a `feeds` event's own counts and never composed:

      feeds: 12 polled · 11 covered (7 unchanged) · NOT COVERED 1 (not-found ×1) · 4 selected -> 1 captured · 1 known · 2 carried · 0 role gaps

    A not-covered count of zero is printed as such and a not-covered feed is NEVER read as "0 roles":
    the failure codes and, when a host was marked down, the host and its code are on the line. An
    event that polled nothing says `0 polled` (no tracked company carries a slug), not silence."""
    nc = e.get("not_covered", 0)
    why = e.get("failures") or {}
    line = ("feeds: %d polled · %d covered (%d unchanged) · NOT COVERED %d%s · %d selected -> %d captured "
            "· %d known · %d carried · %d role gap%s"
            % (e.get("polled", 0), e.get("covered", 0), e.get("unchanged", 0), nc,
               (" (%s)" % ", ".join("%s ×%d" % (c, why[c]) for c in sorted(why))) if why else "",
               e.get("selected", 0), e.get("captured", 0), e.get("known", 0), e.get("carried", 0),
               e.get("role_gaps", 0), "" if e.get("role_gaps", 0) == 1 else "s"))
    hosts = e.get("hosts_down") or {}
    if hosts:
        line += " · host down: %s" % ", ".join("%s (%s)" % (h, hosts[h]) for h in sorted(hosts))
    return line


def roles_lines(recs, run_id, root=None, kind=None, at=None):
    """dev #692 / public #140 + #489 / public #102 -- the sourcing lines, COMPUTED from this
    run's `roles` events and gaps, never composed. Returns a list of lines (no indent):

      sourcing (daily): 14 seen · 2 captured · 9 known · 2 carried · 1 role gap · 1 query truncated
      wide re-scan: 5 re-surfaced (62 seen · 57 already known · 0 role gaps · 0 query gaps)
      sourcing (board): 31 seen · 0 captured · 28 known · 3 carried · 0 role gaps
      ROLES NOT ACCOUNTED (linkedin-jobsearch)
      wide re-scan due since 2026-09-30, not run (skipped-for-cost)

    "Re-surfaced" is `captured + carried` on a `window=wide` event. Per-role gaps and per-query
    gaps stay in separate fields. `ROLES NOT ACCOUNTED` is printed for every surface that holds
    an open `jobsearch:roles:<surface>` gap from this run (a pass returned and no ROLES block was
    accepted, or the block was refused), so silence never reads as zero. The wide-due line prints
    for a `daily` run whose pass produced no wide event while wide is due."""
    lines = []
    events = _journal.roles_events(recs, run_id=run_id)
    for e in events:
        seen = e.get("distinct", 0)
        gaps_q = (e.get("query_gaps_window", 0), e.get("query_gaps_truncated", 0))
        quarantine = _quarantine_clause(e)
        if e.get("surface") == "linkedin-jobsearch" and e.get("window") == "wide":
            lines.append("wide re-scan: %d re-surfaced (%d seen · %d already known · %d role gaps "
                         "· %d query gaps%s)"
                         % (e.get("captured", 0) + e.get("carried", 0), seen, e.get("known", 0),
                            e.get("role_gaps", 0), gaps_q[0] + gaps_q[1], quarantine))
            reads = _query_reads_line(e)
            if reads:
                lines.append(reads)
            continue
        label = "board" if e.get("surface") == "board" else (e.get("window") or "daily")
        line = ("sourcing (%s): %d seen · %d captured · %d known · %d carried · %d role gap%s"
                % (label, seen, e.get("captured", 0), e.get("known", 0), e.get("carried", 0),
                   e.get("role_gaps", 0), "" if e.get("role_gaps", 0) == 1 else "s"))
        line += quarantine
        if gaps_q[1]:
            line += " · %d query truncated" % gaps_q[1]
        if gaps_q[0]:
            line += " · %d query gap%s (window)" % (gaps_q[0], "" if gaps_q[0] == 1 else "s")
        lines.append(line)
        reads = _query_reads_line(e, label)
        if reads:
            lines.append(reads)
    for e in _journal.feeds_events(recs, run_id=run_id):
        lines.append(feeds_line(e))
    held = {g.get("scope") for g in _journal.open_gaps(recs, run_id=run_id)}
    for surface in _journal.ROLES_SURFACES:
        if _journal.ROLES_GAP_SCOPE % surface in held:
            lines.append("ROLES NOT ACCOUNTED (%s)" % surface)
    if kind == "daily" and root is not None:
        now = at or _journal.now_iso()
        w = _journal.jobsearch_window(now, recs, _geos(root))
        wide_here = [e for e in events if e.get("surface") == "linkedin-jobsearch"
                     and e.get("window") == "wide"]
        if w["window"] == "wide" and not wide_here:
            passes = [r for r in recs if r.get("event") == "pass" and r.get("run_id") == run_id
                      and r.get("kind") == "linkedin"]
            refused = [r for r in passes if r.get("phase") == "refused"]
            returned = [r for r in passes if r.get("phase") == "returned"]
            if refused:
                why = refused[-1].get("reason") or "refused"
            elif returned and returned[-1].get("jobsearch") not in (None, "reached"):
                why = "job search %s" % returned[-1].get("jobsearch")
            elif returned:
                why = "no wide ROLES block accepted"
            else:
                why = "no LinkedIn pass this run"
            lines.append("wide re-scan due since %s, not run (%s)" % (w["due_since"], why))
        elif w["window"] == "wide" and wide_here:
            lines.append("wide re-scan STILL DUE since %s: the pass did not cover every "
                         "requested geography" % w["due_since"])
    return lines


def render_detail(recs, run_id, fp, root=None, at=None):
    start_at, as_of, _kind = _run_window(recs, run_id)

    def _in_window(r):
        when = r.get("at") or ""
        return start_at <= when <= as_of

    lines = ["  %s" % ln for ln in roles_lines(recs, run_id, root=root, kind=_kind, at=at)]
    swept = [r for r in recs if r.get("event") == "swept" and _in_window(r)]
    if swept:
        parts = ["%s ok" % r.get("mailbox") if r.get("ok")
                else "%s FAILED (%s)" % (r.get("mailbox"), r.get("reason")) for r in swept]
        lines.append("  swept  : %s" % " · ".join(parts))
    probes = [r for r in recs if r.get("event") == "probe" and _in_window(r)]
    if probes:
        lines.append("  probes : %s"
                     % " · ".join("%s -> %s" % (r.get("subject"), r.get("result"))
                                  for r in probes))
    gaps = [g for g in _journal.open_gaps(recs) if g.get("run_id") == run_id]
    if gaps:
        lines.append("  gaps   : %s"
                     % " · ".join("%s %s (open)" % (g.get("scope"), g.get("reason"))
                                  for g in gaps))
    notes = [r for r in recs if r.get("event") == "note" and r.get("run_id") == run_id]
    if notes:
        def _note(n):
            text = str(n.get("text") or "")
            bad, phrase = disagrees(text, fp)       # dev #703: a contradicting note is withheld
            return withheld_marker(phrase, fp) if bad else text[:80]
        lines.append("  notes  : %s" % " · ".join(_note(n) for n in notes))
    if fp.get("files"):
        lines.append("  files  : %s" % ", ".join(fp["files"]))
    committed = fp.get("committed")
    if committed is None:
        lines.append("  committed: not measured (no start sha)")
    elif committed:
        lines.append("  committed: %s" % ", ".join(committed))
    return "\n".join(lines)


def first_disagreement(text, fp):
    """(bool, phrase, line) — `disagrees()` over the whole text, plus the first line it came from
    (found by calling `disagrees()` per line, so there is still one definition of a
    contradiction and no second phrase scan here)."""
    bad, phrase = disagrees(text, fp)
    if not bad:
        return False, None, None
    for ln in (text or "").splitlines():
        if disagrees(ln, fp)[0]:
            return True, phrase, ln.strip()
    return True, phrase, None


def _quote_claim(phrase, line):
    return "%r in: %s" % (phrase, line if line else "(text spans lines)")


def refusal_message(phrase, line, fp, annotated):
    where = ("the --annotate text" if annotated else "a line of the generated detail")
    return ("⛔ %s refused — %s says %s, but this run's own footprint shows real change "
            "(%s). Nothing was posted: a stored summary that contradicts its own footprint is "
            "what check_runs.py goes red on at the next session start. "
            "%s" % ("--annotate" if annotated else "--post", where, _quote_claim(phrase, line),
                    {k: v for k, v in fp.items() if v not in (0, [], None)} or fp,
                    "Reword the annotation without the claim." if annotated else
                    "The footprint above is the true summary; report the refusal in the run's "
                    "final message rather than retyping the claim."))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", metavar="ID", required=True)
    ap.add_argument("--post", action="store_true",
                    help="write the generated summary to the coordinator inbox")
    ap.add_argument("--annotate", metavar="TEXT",
                    help="free text appended UNDER the headline; refused if it contradicts "
                         "the machine-measured footprint")
    ap.add_argument("--check", metavar="TEXT",
                    help="does TEXT's change/no-change claim agree with this run's own "
                         "footprint? Prints the verdict and exits 1 if it disagrees.")
    ap.add_argument("--urgency", choices=("normal", "high"),
                    help="override the deduced urgency on --post (default: high iff a sweep "
                         "failed or a gap is open, else normal)")
    ap.add_argument("--at", help="ISO timestamp; for tests and for replaying a known time")
    args = ap.parse_args()

    root = profile_root()

    try:
        recs = _journal.read(root)
        fp = footprint(root, args.run, recs=recs, at=args.at)
    except RunSummaryError as e:
        print("⛔ %s" % e, file=sys.stderr)
        return 2

    if args.check is not None:
        bad, phrase = disagrees(args.check, fp)
        if bad:
            print("⛔ posted text says %r but the footprint shows real change: %s"
                  % (phrase, fp), file=sys.stderr)
            return 1
        print("OK — the posted text's change/no-change claim agrees with the footprint.")
        return 0

    headline = render_headline(recs, args.run, fp)
    body = render_detail(recs, args.run, fp, root=root, at=args.at)
    detail = body
    if args.annotate:
        detail = (detail + "\n" if detail else "") + "  note: %s" % args.annotate
    text = headline
    if detail:
        text += "\n" + detail

    # ⭐ dev #703 / public #155 — the SAME `disagrees()` `check_runs.py` runs later, over the SAME
    # text it will read later (`summary + detail`). The two sources are handled differently:
    #   * a contradicting `--annotate` is REFUSED (exit 2, nothing posted) whether or not it is
    #     being posted (public #85) — the caller can reword it;
    #   * a contradicting JOURNAL NOTE cannot be un-written, so refusing would leave the run with
    #     no summary at all. `render_detail()` has already replaced it with a visible marker; we
    #     say so on stderr and the post goes ahead, so the stored row never carries it.
    bad, phrase, line = first_disagreement(text, fp)
    if bad:
        from_annotate = bool(args.annotate) and disagrees(args.annotate, fp)[0]
        if from_annotate:
            phrase, line = disagrees(args.annotate, fp)[1], args.annotate
        if args.post or from_annotate:
            print(refusal_message(phrase, line, fp, annotated=from_annotate),
                  file=sys.stderr)
            return 2
        print("⚠️ --post would be REFUSED: %s" % _quote_claim(phrase, line), file=sys.stderr)

    for _text, w_phrase in withheld_notes(recs, args.run, fp):
        print("⚠️ note withheld: a journal note of this run claimed %r but the footprint shows "
              "real change; the summary carries a marker in its place." % w_phrase,
              file=sys.stderr)

    print(text)

    if args.post:
        rec_id = "run-summary-%s" % args.run     # ⭐ deterministic — a second --post for the
                                                  # SAME run replaces this row on replay rather
                                                  # than duplicating it (inbox.replay(), public
                                                  # #85 plant: "--post twice for one run -> one
                                                  # row"), because inbox.py folds by `id`.
        urgency = args.urgency or ("high" if (fp["swept_failed"] or fp["gaps_open"])
                                   else "normal")
        now = datetime.datetime.now()
        rec = {"id": rec_id, "kind": "run-summary", "summary": headline, "detail": detail,
               "urgency": urgency, "status": "pending",
               "found_at": now.isoformat(timespec="seconds"),
               "run_id": args.run, "footprint": fp}
        _inbox.append([rec])          # importing inbox.py's append rather than shelling out
                                       # (B.1) — one writer path, same append-only contract.
        print("\nPosted %s for the coordinator." % rec_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
