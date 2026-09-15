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


def footprint(root, run_id, recs=None, at=None):
    """⭐⭐ THE ONE SHAPE — see the module docstring. Returns a JSON-safe dict:

        files          [changed filename, ...]   — from `git diff --stat HEAD`
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
    counts — only a FAILURE or something actually found does. `tree_dirty is None` (git could
    not be asked) counts as changed: an unverifiable tree must never be reported as clean."""
    if fp.get("tree_dirty") is None:
        return True
    return bool(fp.get("tree_dirty") or fp.get("notes") or fp.get("probes")
                or fp.get("swept_failed") or fp.get("gaps_open"))


def disagrees(text, fp):
    """(bool, phrase) — does `text` claim "no change" (one of NO_CHANGE_PHRASES) while `fp`
    shows the claim is false? The check_stale_claims.py shape: absence of a phrase is never
    itself a finding, and a footprint that genuinely shows nothing makes the same phrase TRUE,
    never flagged (public #85 plant: "the same with an empty footprint ... is correct, green")."""
    low = (text or "").lower()
    if not changed(fp):
        return False, None
    for phrase in NO_CHANGE_PHRASES:
        if phrase in low:
            return True, phrase
    return False, None


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
    else:
        head = ("%s %s — NO CHANGE: tree clean · swept %d/%d · %d probe(s) · %d gap(s)"
                % (label, when, fp["swept_ok"], swept_total, fp["probes"], len(fp["gaps_open"])))
    if fp.get("swept_failed"):
        # ⭐ public #85 plant — the headline NAMES the incomplete account; a failure is never
        # folded into a bare count nobody can act on.
        head += " · INCOMPLETE: %s" % ", ".join(fp["swept_failed"])
    return head


def render_detail(recs, run_id, fp):
    start_at, as_of, _kind = _run_window(recs, run_id)

    def _in_window(r):
        when = r.get("at") or ""
        return start_at <= when <= as_of

    lines = []
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
        lines.append("  notes  : %s"
                     % " · ".join(str(n.get("text") or "")[:80] for n in notes))
    if fp.get("files"):
        lines.append("  files  : %s" % ", ".join(fp["files"]))
    return "\n".join(lines)


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

    if args.annotate is not None:
        bad, phrase = disagrees(args.annotate, fp)
        if bad:
            print("⛔ --annotate refused — %r contradicts the footprint (%s); the headline "
                  "cannot be overridden by annotation" % (phrase, fp), file=sys.stderr)
            return 2

    headline = render_headline(recs, args.run, fp)
    body = render_detail(recs, args.run, fp)
    text = headline
    if body:
        text += "\n" + body
    if args.annotate:
        text += "\n  note: %s" % args.annotate
    print(text)

    if args.post:
        rec_id = "run-summary-%s" % args.run     # ⭐ deterministic — a second --post for the
                                                  # SAME run replaces this row on replay rather
                                                  # than duplicating it (inbox.replay(), public
                                                  # #85 plant: "--post twice for one run -> one
                                                  # row"), because inbox.py folds by `id`.
        detail = body
        if args.annotate:
            detail = (detail + "\n" if detail else "") + "  note: %s" % args.annotate
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
