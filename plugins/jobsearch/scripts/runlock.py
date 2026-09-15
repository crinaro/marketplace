#!/usr/bin/env python3
"""
A write lock, so two WRITERS never run at once.

WHY THIS EXISTS
---------------
The candidate, 2026-08-02: *"I'm interacting in a session and it conflicts with another session running."*

The watcher (`watch.py`) can never conflict — it is read-only and appends to one queue file. But
two **writers** still can: an interactive session and a scheduled daily run both rewrite
`focus.md`, `log.md`, and git. Until now the only protection was a prose warning in CLAUDE.md
("the daily run and the weekly review must not overlap"), which is not protection.

This is the mechanical version. A writer takes the lock, writes, and releases.

## ⭐⭐ HOLD IT FOR THE WRITE, NOT FOR THE RUN — the correction of 2026-08-03

The candidate: *"Why can't it run concurrently with the coordinator session? That was the main purpose."*
**The candidate was right, and the first design defeated its own purpose.**

As originally written, BOTH sides held this lock for their entire lifetime: the daily run took it
at step 0 and released after the commit (**CLAUDE.md's own note says a run can take 2h15m**), and
the coordinator took it at session start and held until the candidate released by hand. Two long-held
exclusive locks cannot overlap, so "runs every 2 hours in the background" was never achievable
while the candidate was working. **Measured that morning: their coordinator went idle at 07:02 still holding
the lock; at 07:09 it was held 28 minutes, and nothing else could write until the 150-minute
staleness expiry at ~09:11 — so the 07:00 slot was lost and 09:00 would have been degraded too.**

**But nearly all of a run is READS** — the Gmail sweep, the LinkedIn pass, web research, fit
analysis. Reads never conflict. Only the state-write and commit need exclusion, and that is
seconds.

So the rule is now: **do the discovery unlocked, take the lock only for the write, release
immediately.** A run no longer throws away two hours of work because a session was open.

`--wait` is what makes that safe: a writer blocks for a few seconds rather than giving up, because
the holder is now expected to release in seconds rather than hours.

⚠️ **The unlocked read phase means state can move under you before you write** — which is what
`scripts/changed.py` is for. Re-check before writing; that is the other half of this design.

**Deliberately advisory, not mandatory.** It records intent and makes a collision visible; it
cannot stop a determined process, and a stale lock from a crashed session must never wedge an
unattended run — hence `--steal` and the automatic staleness warning.

Usage:
    python3 scripts/runlock.py --take "daily 2pm"           # exit 1 if someone else holds it
    python3 scripts/runlock.py --take "daily" --wait 90     # block up to 90s for it
    python3 scripts/runlock.py --status
    python3 scripts/runlock.py --release
    python3 scripts/runlock.py --steal "daily 2pm"   # take it anyway; says who was displaced

Python 3.9+. Standard library only.
"""

import argparse
import datetime
import json
import os
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root

ROOT = _profile_root()
# ⭐ TEST-ISOLATABLE. Found 2026-08-04: 14 test call sites exercise real lock acquisition against
# the PRODUCTION lock file, so the whole suite failed whenever any session legitimately held it.
# That is the flakiness that produced four false-RED gate sweeps in an afternoon — and it made
# the sensible rule "take the lock before the gate sweep" self-defeating, because holding it
# broke the tests that verify locking works.
#
# A test that exercises a lock must use its OWN lock, or it is testing the environment rather
# than the code.
LOCK = os.environ.get("CLAUDESEARCH_LOCK_PATH") or \
    os.path.join(ROOT, ".git", "run_lock.json")   # inside .git: never committed
# ⭐ 20, not 150. The lock now covers only the WRITE phase (seconds), not a whole run, so a hold
# lasting 20 minutes means a session died holding it — not that a long run is legitimately busy.
# The old 150 was sized for run-length holds and, on 2026-08-03, would have wedged writes from
# 06:41 to 09:11 because an idle coordinator never released.
STALE_MINUTES = 20

# ⭐⭐ design-linkedin-runner-resilience.md §1 (public #47/#96) — A SECOND RESOURCE, NOT A SECOND
# LOCK FILE FORMAT. Two instances of one `run_id` colliding on the Browser pane (#47) and a
# stalled pane re-claimed five sessions running (#96) are both "two writers, one exclusive
# resource" — exactly what this module already exists to serialize. So `--resource pane` reuses
# this file's take/release/status/steal vocabulary against a SECOND, independent lock file
# (never `LOCK` above — the write lock is held for seconds and must never span a pass; the pane
# is held for the whole pass by design, so sharing a file would make the two staleness policies
# fight each other).
#
# Three differences from the write lock, each closing a specific defect:
#   - a per-`--take` NONCE (`os.urandom(8).hex()`), never `run_id` — D-4: two instances of ONE
#     run share a run_id, so a lock keyed on run_id would let a run's second instance walk right
#     past its own first instance's hold. `--release` must present the nonce it was given.
#   - staleness is JOURNAL-DERIVED first (the holder's run_id has an `end`/`dispose` event) and
#     only falls back to an age threshold (`linkedin.pane_stale_minutes`) when the journal has
#     nothing to say — a crashed holder never writes `end`, so age is what recovers the pane.
#   - `--stalled` and `--verdict` write onto the CURRENT holder's record (nonce-gated, same as
#     `--release`) rather than taking or releasing anything — §2's render-stall verdict and §5's
#     signed-in fact are both learned mid-pass, not at take/release time.
PANE_LOCK = os.environ.get("CLAUDESEARCH_PANE_LOCK_PATH") or \
    os.path.join(ROOT, ".git", "pane_lock.json")


def read():
    if not os.path.exists(LOCK):
        return None
    try:
        with open(LOCK, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def age_minutes(rec):
    try:
        t = datetime.datetime.fromisoformat(rec["taken_at"])
    except (KeyError, ValueError):
        return None
    return int((datetime.datetime.now() - t).total_seconds() // 60)


# ---- --resource pane -------------------------------------------------------------------------

def _pane_read():
    if not os.path.exists(PANE_LOCK):
        return None
    try:
        with open(PANE_LOCK, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _pane_write(rec):
    os.makedirs(os.path.dirname(PANE_LOCK), exist_ok=True)
    with open(PANE_LOCK, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)


def _pane_new_nonce():
    return os.urandom(8).hex()


def _pane_stale_minutes():
    """`linkedin.pane_stale_minutes`, config_keys' own registered default when the profile has
    not set one. Reads config.json directly rather than importing `profile.py` — that module
    binds ITS OWN root at import time via `profile_or_fixture()`, which need not be the same
    root this process is pointed at (CLAUDESEARCH_ROOT), and a pane lock must answer for the
    root it actually runs against."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config_keys as _ck
        cfg_path = os.path.join(ROOT, "config.json")
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, ValueError):
            cfg = {}
        value, _ = _ck.describe(cfg, _ck.LINKEDIN_PANE_STALE_MINUTES)
        return value
    except Exception:
        return 90     # config_keys' own default, mirrored defensively if it cannot be imported


def _run_ended_or_disposed(run_id):
    """Staleness rule (i): the holder's run_id has an `end` or `dispose` event in the journal —
    a crashed holder never writes `end`, so this only ever fires for a run that finished (or was
    reviewed and disposed) normally, never for one that is merely slow."""
    if not run_id:
        return False
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import journal as _journal
        recs = _journal.read(ROOT)
        return any(r.get("run_id") == run_id and r.get("event") in ("end", "dispose")
                  for r in recs)
    except Exception:
        return False


def _pane_is_stale(rec):
    """(is_stale, reason) — journal-derived end/dispose first (rule i), then the age threshold
    (rule ii). `reason` is one of the two exact phrases §1/plant 12 name, so a caller (and a
    test) can match on it without re-deriving which rule fired."""
    run_id = rec.get("run_id")
    if _run_ended_or_disposed(run_id):
        return True, "stale (run ended)"
    try:
        t = datetime.datetime.fromisoformat(rec.get("taken_at"))
    except (TypeError, ValueError):
        return False, None
    age_min = (datetime.datetime.now() - t).total_seconds() / 60.0
    limit = _pane_stale_minutes()
    if age_min > limit:
        return True, "stale (%d min)" % int(age_min)
    return False, None


def _main_pane(args):
    cur = _pane_read()

    if args.stalled:
        if not args.nonce:
            print("--stalled requires --nonce")
            return 2
        if not cur or cur.get("nonce") != args.nonce:
            print("REFUSED — nonce does not match the current pane-lock holder; nothing "
                  "recorded.")
            return 1
        cur["stalled_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        _pane_write(cur)
        print("stalled_at recorded for run %s" % cur.get("run_id"))
        return 0

    if args.verdict:
        if not args.nonce:
            print("--verdict requires --nonce")
            return 2
        if not cur or cur.get("nonce") != args.nonce:
            print("REFUSED — nonce does not match the current pane-lock holder; nothing "
                  "recorded.")
            return 1
        cur["last_verdict"] = args.verdict
        cur["verdict_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        _pane_write(cur)
        print("verdict recorded: %s" % args.verdict)
        return 0

    if args.release:
        if not cur:
            print("Nothing to release.")
            return 0
        if not args.nonce or cur.get("nonce") != args.nonce:
            # ⭐ D-7's other half: a refused `--take` never received a nonce, so its exit-path
            # `--release` cannot free the holder's pane. Nothing releases by run_id or by who.
            print("REFUSED — nonce does not match the current pane-lock holder; nothing "
                  "released.")
            return 1
        os.remove(PANE_LOCK)
        print("Released.")
        return 0

    if args.take or args.steal:
        who = args.take or args.steal
        if not args.run_id:
            print("--run-id is required with --take/--steal on --resource pane")
            return 2
        if cur and not args.steal:
            # ⭐ D-4 — no exception for the holder's OWN run_id. #47 is two INSTANCES of one
            # run; a lock that admits its own run_id back in is not a lock for that case.
            stale, reason = _pane_is_stale(cur)
            if not stale:
                print("REFUSED — pane held by %r (run %s) since %s."
                      % (cur.get("who"), cur.get("run_id"), cur.get("taken_at")))
                return 1
            print("%s — taking over." % reason)
        displaced = cur if (cur and args.steal) else None
        nonce = _pane_new_nonce()
        rec = {"who": who, "run_id": args.run_id, "nonce": nonce,
              "surface": args.surface or "pane",
              "taken_at": datetime.datetime.now().isoformat(timespec="seconds"),
              "stalled_at": None, "last_verdict": None, "verdict_at": None}
        _pane_write(rec)
        print("NONCE %s" % nonce)
        if displaced:
            print("STOLE the pane lock from %r (run %s)."
                  % (displaced.get("who"), displaced.get("run_id")))
        return 0

    # --status, or nothing else was asked
    if not cur:
        print("UNLOCKED — the pane is free.")
        return 0
    stale, reason = _pane_is_stale(cur)
    print("PANE %s by %r (run %s, surface %s) since %s"
          % ("LOCKED" if not stale else "STALE", cur.get("who"), cur.get("run_id"),
             cur.get("surface"), cur.get("taken_at")))
    if stale:
        print("  %s — the next --take will succeed without --steal." % reason)
    if cur.get("stalled_at"):
        print("  stalled_at: %s" % cur["stalled_at"])
    if cur.get("last_verdict"):
        print("  last_verdict: %s at %s" % (cur["last_verdict"], cur.get("verdict_at")))
    return 0 if stale else 1


def main():
    ap = argparse.ArgumentParser(description="Advisory write lock for state-mutating runs.")
    ap.add_argument("--take", metavar="WHO")
    ap.add_argument("--steal", metavar="WHO")
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--run", metavar="WHO",
                    help="⭐ TAKE, run the command after `--`, RELEASE IN A FINALLY. The release "
                         "stops depending on anyone remembering it. Use this for every write. "
                         "A refused lock exits non-zero WITHOUT running the command, loudly.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                    help="Block up to SECONDS for the lock instead of failing at once. Correct "
                         "now that holders release in seconds; it is what lets a background run "
                         "write while the candidate has a session open.")
    ap.add_argument("--no-gates", action="store_true",
                    help="With --run: skip the automatic validate_data.py gate after a successful "
                         "command. Gates are ON BY DEFAULT (2026-08-04, per the candidate: validation must "
                         "be systematic, not luck) — opt out only for writes that cannot touch "
                         "data/*.jsonl, and prefer leaving it on even then; it is cheap.")
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="With --run: the command to execute under the lock, after a `--`.")
    ap.add_argument("--resource", choices=("pane",),
                    help="Operate on a SECOND, independent lock — design-linkedin-runner-"
                         "resilience.md §1 (public #47/#96). Omit for the ordinary write lock "
                         "above; '--resource pane' serializes Claude's in-app Browser pane "
                         "(or the Chrome extension, with --surface extension) instead. Its own "
                         "vocabulary: --take/--steal need --run-id; --release/--stalled/"
                         "--verdict need --nonce (printed by --take).")
    ap.add_argument("--run-id", dest="run_id", metavar="ID",
                    help="--resource pane --take/--steal: the caller's own run id (from "
                         "journal.py --start) — carried on the record so a refusal can name it.")
    ap.add_argument("--nonce", metavar="NONCE",
                    help="--resource pane --release/--stalled/--verdict: the nonce --take "
                         "printed. A mismatch (or a refused --take's missing nonce) is a no-op, "
                         "exit 1 — nothing releases or records by run_id or who.")
    ap.add_argument("--surface", choices=("pane", "extension"),
                    help="--resource pane --take/--steal: which browser surface this pass is "
                         "using (default: pane). An extension pass records surface: extension "
                         "and holds the SAME lock — two extension passes collide on the "
                         "candidate's real Chrome exactly as two pane passes collide on the pane.")
    ap.add_argument("--stalled", action="store_true",
                    help="--resource pane: record a confirmed render-stall verdict on the "
                         "current holder (needs --nonce). §2's paint-proof miss twice, 4s apart.")
    ap.add_argument("--verdict", choices=("signed-in", "not-signed-in"),
                    help="--resource pane: record the preflight signed-in fact on the current "
                         "holder (needs --nonce) — §5.2, read by deferred.py --claimable.")
    args = ap.parse_args()

    if args.resource == "pane":
        return _main_pane(args)

    # ---- --run: take / execute / release, with the release in a finally ---------------------
    # ⭐ Added 2026-08-03, per the candidate: "shouldn't this happen when you're done with a write?"
    # The candidate is right, and the manual sequence had already failed twice the same day:
    #   (1) a coordinator held the lock from 06:41 while idle and cost the 07:00 run;
    #   (2) `--take ... >/dev/null && python3 ...` silently SKIPPED a write when the take was
    #       refused, because the refusal went to /dev/null and && short-circuited.
    # Both are the same class of bug: correctness depending on a human or a model remembering a
    # second step. Here the release is structural — it runs even if the command fails or raises.
    if args.run:
        import subprocess
        cmd = [a for a in (args.cmd or []) if a != "--"]
        if not cmd:
            print("--run needs a command: runlock.py --run 'who' -- <command ...>")
            return 2
        if args.wait:
            import time
            deadline = time.time() + args.wait
            while read() is not None and time.time() < deadline:
                time.sleep(2)
        cur = read()
        if cur:
            age = age_minutes(cur)
            # LOUD and non-zero. The command does NOT run — a skipped write must never be silent.
            print("REFUSED — %r has held the lock for %s min. COMMAND NOT RUN." % (cur.get("who"), age))
            if age is not None and age > STALE_MINUTES:
                print("  ⚠️ Looks STALE (> %d min) — `--steal` is probably correct." % STALE_MINUTES)
            return 1
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        with open(LOCK, "w", encoding="utf-8") as fh:
            json.dump({"who": args.run, "pid": os.getpid(),
                       "taken_at": datetime.datetime.now().isoformat(timespec="seconds")}, fh)
        try:
            rc = subprocess.call(cmd)
            if rc != 0:
                # ⭐ 2026-08-04, per the candidate: "fix the validation for the writes so it's systematic
                # versus something that's caught by luck." The luck meant here: a write failed with
                # a SyntaxError, but a `;`-chained validate ran anyway against UNCHANGED data and
                # printed "Clean" directly under the error — a failed write dressed as a passed
                # one. Structural fix: the wrapper itself declares the failure loudly, and gates
                # only ever run on success, inside the same lock.
                print("")
                print("⚠️⚠️ WRITE COMMAND FAILED (exit %d) — TREAT THE WRITE AS NOT HAVING HAPPENED." % rc)
                print("   Gates were NOT run. Any gate output you produce after this validates the")
                print("   PRE-WRITE state and proves nothing about this write. Re-read the target")
                print("   file, fix the command, and re-run; never chain gates with ';' after --run.")
                return rc
            if not args.no_gates:
                grc = subprocess.call(
                    [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "validate_data.py")])
                if grc != 0:
                    print("⚠️ WRITE SUCCEEDED but validate_data.py FAILED (exit %d) — the data is"
                          % grc)
                    print("   now in a bad state. Fix it before any further writes.")
                    return grc
            return 0
        finally:
            if os.path.exists(LOCK):
                os.remove(LOCK)

    # Poll for the lock rather than giving up. A run that has already done an hour of research
    # must not discard it because a write was in flight.
    if args.take and args.wait:
        import time
        deadline = time.time() + args.wait
        while read() is not None and time.time() < deadline:
            time.sleep(2)

    cur = read()

    if args.status or not any((args.take, args.steal, args.release)):
        if not cur:
            print("UNLOCKED — no writer is running. Safe to take it.")
            return 0
        age = age_minutes(cur)
        print("LOCKED by %r since %s (%s min)" % (cur.get("who"), cur.get("taken_at"), age))
        if age is not None and age > STALE_MINUTES:
            print("  ⚠️ STALE — held longer than %d min. The lock now covers only the WRITE"
                  % STALE_MINUTES)
            print("     phase (seconds), so this means a session died or went idle holding it.")
            print("     `--steal` to proceed.")
        else:
            print("  A second writer should WAIT, or work read-only. `watch.py` is always safe.")
        return 1

    if args.release:
        if os.path.exists(LOCK):
            os.remove(LOCK)
            print("Released.")
        else:
            print("Nothing to release.")
        return 0

    who = args.take or args.steal
    if cur and not args.steal:
        age = age_minutes(cur)
        print("REFUSED — %r has held the lock for %s min." % (cur.get("who"), age))
        print("  Wait, or run read-only (`scripts/watch.py` never conflicts), or --steal.")
        if age is not None and age > STALE_MINUTES:
            print("  ⚠️ It looks STALE (> %d min) — stealing is probably correct." % STALE_MINUTES)
        return 1

    displaced = cur.get("who") if cur else None
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w", encoding="utf-8") as fh:
        json.dump({"who": who, "pid": os.getpid(),
                   "taken_at": datetime.datetime.now().isoformat(timespec="seconds")}, fh)
    if displaced:
        print("STOLE the lock from %r. Say so in the run summary — the displaced session's "
              "in-flight writes may be lost." % displaced)
    else:
        print("Locked by %r. Release with --release when the run finishes." % who)
    return 0


if __name__ == "__main__":
    sys.exit(main())
