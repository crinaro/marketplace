#!/usr/bin/env python3
"""Archive the call-prep notes whose call has been held — a SCRIPT, not a line in a skill.

⭐ WHY THIS EXISTS (dev/audit 2026-09-02, build item 7)
--------------------------------------------------------
`call-prep/SKILL.md` step 6 told the model to archive a prep "after the call", once durable
content had been promoted to the company kb. On the profile measured it had been skipped
every time for weeks: the preps for calls already held were all still in `conversations/`,
every one rendering IN FULL on the one dashboard page — most of a phone page, by bytes, that
existed to show the NEXT call's prep. A step a model is told to remember is a step that is
skipped exactly when the session is busy, which is every session. **A change ships as a
version, never as an instruction** — so the archive is a deterministic step of the run's
HYGIENE (daily-run §1, weekly-review), and the 0.36.0 migration
(`migrate.m_0_36_0_archive_past_preps`) runs the same function once at upgrade so the
backlog moves on the first session after the release, with nobody asked to do anything.

## What "held" means

The call's date is the note's own filename — `call_prep_<date>.md`, `knowledge.prep_date`,
the ONE parser. A note dated BEFORE today is archived; today's stays (the call may be later
today, and the page must still show it). A note whose filename carries no date cannot be
placed at all and is reported LOUDLY, never moved and never silently kept as current.

## Preserve, then transform

The file moves whole from `conversations/` (`_tree` key `call_preps`) to
`archive/call-preps/` (`knowledge.ARCHIVE_DIRS[0]`) — nothing is rewritten except one
addition: a note carrying no `**Promoted:**` line gets `**Promoted:** unresolved` appended,
the migration-marker form `knowledge.py` already reports as "promotion not yet recorded".
The promotion itself is judgement (which lines of a prep are durable) and stays the run's
work; what this script guarantees is that skipping it is VISIBLE — `knowledge.py` in HYGIENE
names every archived prep still carrying the marker — instead of leaving the whole note
sitting in the live folder looking like an upcoming call. `knowledge.prep_hits` scans the
archive too, so a commitment's "prepped" state is unchanged by the move.

A destination that already exists is never overwritten: the file stays, the collision is
reported, and the run decides. An unreadable or unwritable file is reported the same way.

## Under the write lock (dev/audit 2026-09-02, G10)

A file move is a write. `runlock.py`'s rule is "discovery unlocked, the write under the
lock", and this ran in hygiene, unattended, before the daily run takes its lock — so an open
coordinator session could commit a half-moved prep (archive copy present, live copy present)
into its own change. So the CLI takes the lock itself for the seconds the move takes, the
way `compact.py` does, and releases it in a `finally`. A caller that already owns the lock
(the weekly review, which takes it at its step 0) passes `--holding-lock`: the move proceeds
under the caller's hold, which stays theirs to release. A refused lock moves NOTHING and
exits 1, loudly — the next run's hygiene moves the same preps; nothing is lost by waiting.
`--check` reads only and never touches the lock. The migration calls `archive()` directly,
inside `migrate.py`'s own envelope.

Usage:
    python3 scripts/archive_preps.py            # move every past-dated prep; exit 0
    python3 scripts/archive_preps.py --holding-lock   # the caller owns the write lock
    python3 scripts/archive_preps.py --check    # report only; exit 1 if any is owed
    python3 scripts/archive_preps.py --today 2026-01-05   # test seam

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _root import profile_root                                      # noqa: E402
import _tree                                                        # noqa: E402
import knowledge as _kn                                             # noqa: E402

PROMOTED_MARKER = "**Promoted:** unresolved"
LOCK_WHO = "archive preps"
# Seconds. Holders release in seconds by design (runlock.py's contract), so a short wait is
# what lets an unattended hygiene pass slip in beside an open session instead of giving up.
# Env-overridable as a TEST SEAM only (the suite's refusal cases must not wait 10s each).
LOCK_WAIT = int(os.environ.get("CLAUDESEARCH_ARCHIVE_LOCK_WAIT") or 10)


def _runlock(*args):
    return subprocess.run([sys.executable, os.path.join(HERE, "runlock.py")] + list(args),
                          capture_output=True, text=True)


def take_lock():
    """True if this process now holds the write lock."""
    return _runlock("--take", LOCK_WHO, "--wait", str(LOCK_WAIT)).returncode == 0


def release_lock():
    _runlock("--release")


def archive(root, today=None, apply_it=True):
    """Move every prep dated before `today` into the archive. Returns a dict:
    moved · kept (today or future, by relpath) · undated (loud) · collisions · errors."""
    today = today or datetime.date.today()
    src_dir = _tree.path(root, "call_preps")
    dst_dir = os.path.join(root, _kn.ARCHIVE_DIRS[0])
    out = {"moved": [], "kept": [], "undated": [], "collisions": [], "errors": []}
    if not os.path.isdir(src_dir):
        return out
    src_rel = os.path.relpath(src_dir, root)
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".md") or name.lower() in _kn.KB_EXEMPT:
            continue
        rel = os.path.join(src_rel, name)
        d = _kn.prep_date(name)
        if d is None:
            out["undated"].append(rel)
            continue
        if d >= today:
            out["kept"].append(rel)
            continue
        dst = os.path.join(dst_dir, name)
        if os.path.exists(dst):
            out["collisions"].append(rel)
            continue
        if not apply_it:
            out["moved"].append(rel)
            continue
        try:
            with open(os.path.join(src_dir, name), encoding="utf-8") as fh:
                text = fh.read()
            if not _kn.PROMOTED_RE.search(text):
                text = text.rstrip("\n") + "\n\n" + PROMOTED_MARKER + "\n"
            os.makedirs(dst_dir, exist_ok=True)
            tmp = dst + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, dst)                 # the archive copy is complete before...
            os.unlink(os.path.join(src_dir, name))   # ...the live one goes
            out["moved"].append(rel)
        except OSError as e:
            out["errors"].append("%s: %s" % (rel, e))
    return out


def summary(res, apply_it):
    """The lines a run prints — the same text the migration reports."""
    lines = []
    verb = "archived" if apply_it else "would archive"
    if res["moved"]:
        lines.append("%s %d past-dated call prep(s) to %s: %s"
                     % (verb, len(res["moved"]), _kn.ARCHIVE_DIRS[0],
                        ", ".join(os.path.basename(p) for p in res["moved"])))
    for rel in res["undated"]:
        lines.append("⚠️ %s carries no call_prep_<date> in its name — cannot be placed on a "
                     "calendar, so it is neither archived nor shown as current. A prep: "
                     "rename it call_prep_<date>.md. Anything else living here (a case "
                     "study, an assessment note): move it to the store it belongs in — "
                     "pipeline/kb/<company_id>.md for durable knowledge" % rel)
    for rel in res["collisions"]:
        lines.append("⚠️ %s: a file of that name already exists in %s — left in place, "
                     "not overwritten; reconcile the two" % (rel, _kn.ARCHIVE_DIRS[0]))
    for e in res["errors"]:
        lines.append("⚠️ " + e)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report only; exit 1 if any past-dated prep is still live")
    ap.add_argument("--holding-lock", action="store_true",
                    help="The CALLER already owns the write lock (the weekly review). Move "
                         "under its hold and leave the release to it.")
    ap.add_argument("--today", help="ISO date (test seam)")
    args = ap.parse_args()
    today = datetime.date.fromisoformat(args.today) if args.today else None
    root = profile_root()
    print("Call-prep archive — %s" % _tree.rel("call_preps"))
    took_lock = False
    if not args.check:
        if take_lock():
            took_lock = True
        elif args.holding_lock:
            print("  the write lock is held and --holding-lock was passed: the CALLER owns it. "
                  "Moving under the caller's lock; it stays theirs to release.")
        else:
            # LOUD and non-zero, and NOTHING moved. A move is a write; a write beside another
            # writer is the race the lock exists to remove. Nothing is lost by waiting: the
            # next run's hygiene archives the same preps.
            print("  REFUSED — a writer holds the lock (%s). NO PREP WAS MOVED."
                  % (_runlock("--status").stdout.strip().splitlines() or ["?"])[0])
            print("  A file move is a write. The next run's hygiene moves the same preps; if "
                  "the hold looks STALE, `runlock.py --steal` and re-run.")
            return 1
    try:
        res = archive(root, today=today, apply_it=not args.check)
    finally:
        if took_lock:
            release_lock()
    lines = summary(res, apply_it=not args.check)
    for l in lines:
        print("  " + l)
    print("  %d live prep(s) kept (today or upcoming)" % len(res["kept"]))
    if not lines:
        print("  nothing owed — every past-dated prep is already archived")
    bad = res["undated"] or res["collisions"] or res["errors"]
    if args.check:
        return 1 if (res["moved"] or bad) else 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
