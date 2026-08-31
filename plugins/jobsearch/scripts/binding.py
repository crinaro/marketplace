#!/usr/bin/env python3
"""Is this session BOUND to a job-search profile — and by what evidence? (dev #150)

⭐ WHY THIS EXISTS
------------------
The plugin installs at user scope, so its agents are listed in every session on the machine.
Being listed is untidy; being DISPATCHED is the problem: `profile_root()`'s remembered pointer
(`~/.claude/jobsearch/profile_root`) is machine-global, so an agent dispatched from a repository
that has nothing to do with the search does not fail cleanly — it resolves the real profile and,
for the drafting agents, writes to it. The gap was that nothing distinguished *"a job-search
session that lost its cwd"* from *"an unrelated session that should not be here."*

This module makes that distinction explicit. It reports the SIGNAL a resolution rests on:

    env      `CLAUDESEARCH_ROOT` is set — an explicit, deliberate binding.        BOUND
    cwd      a profile marker sits at or above the working directory.             BOUND
    pointer  ONLY the machine-global remembered pointer names a profile.          NOT bound
    none     no evidence of any profile at all.                                   NOT bound

⭐⭐ IT DOES NOT TOUCH `profile_root()` AND MUST NEVER GATE IT. The pointer fallback is what
lets an MCP server — spawned with no env and no meaningful cwd — find the profile at all;
without it the Gmail server once served zero mailboxes for a whole run while reporting "no new
mail." Resolution stays permissive; this module only answers, at a POINT OF USE (agent entry,
skill entry), whether the resolution carries evidence that the session belongs to that profile.
The check runs at use time, never at session start, because a scheduled run's prompt `cd`s into
the profile AFTER its session starts — at session start its cwd is wherever the scheduler chose.

Who calls what:

    agents            `binding.py --assert` as their first command. A pointer-only or empty
                      context REFUSES (exit 2 / 3, loud): a model-initiated dispatch carries no
                      evidence of intent. A dispatching session that IS the search but started
                      elsewhere re-dispatches naming the root, and the agent prefixes commands
                      with `CLAUDESEARCH_ROOT=<root>`, which is the `env` signal.
    skills            `binding.py` (no flag) to ANNOUNCE the binding. A user typing a jobsearch
                      skill by name is itself evidence of intent, so pointer-only is acceptable
                      there — but it is said out loud, never silent.
    MCP servers       nothing. They resolve through `profile_root()` exactly as before.

A refusal also records a coded `binding` event in the diagnostics log, so an attempted
unrelated-context dispatch leaves evidence an operator can read (`doctor`), not just a stopped
agent. Honest limit: this defeats reflexive dispatch, not a determined bypass — nothing stops a
process from reading the pointer and exporting it. The agents' own definitions carry the
behavioural rule; this makes the reflexive path loud and mechanical.

Usage:
    python3 binding.py             # announce: signal + root, exit 0 unless no profile at all
    python3 binding.py --assert    # exit 0 bound · 2 pointer-only (refused) · 3 no profile
    python3 binding.py --json      # the raw record, for tools

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from _root import looks_like_profile, remembered_profile  # noqa: E402

EXIT_BOUND = 0
EXIT_POINTER_ONLY = 2
EXIT_NO_PROFILE = 3


def binding(start=None):
    """{signal, root, bound} — mirrors `profile_root()`'s precedence exactly, but reports
    WHICH rung answered instead of flattening them into one path. Read-only: unlike
    `profile_root()` it never records the pointer, because asking about a binding must not
    manufacture one."""
    env = os.environ.get("CLAUDESEARCH_ROOT")
    if env:
        return {"signal": "env", "root": os.path.abspath(env), "bound": True}
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if looks_like_profile(cur):
            return {"signal": "cwd", "root": cur, "bound": True}
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    pointed = remembered_profile()
    if pointed:
        return {"signal": "pointer", "root": pointed, "bound": False}
    return {"signal": "none", "root": None, "bound": False}


def _diag_event(verdict):
    try:
        from _diag import log as diag
        diag("binding", verdict=verdict)
    except Exception:                                   # noqa: BLE001
        pass                       # evidence is best-effort; the verdict never depends on it


def _epoch(iso_ts):
    """`_diag.py`'s own timestamp shape (`%Y-%m-%dT%H:%M:%SZ`, UTC) -> epoch seconds, or None."""
    import calendar
    import time
    try:
        return calendar.timegm(time.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _pointer_advisory():
    """One advisory line to stderr — never touches the exit code or the stdout contract — when
    the MACHINE diagnostics log shows repeated engine-pointer repairs or a stale-copy-session
    refusal recorded SINCE this engine's version last changed. `doctor.py`'s pointer section
    reads the same two event classes for the same reason (its own docstring: frequency is the
    signal, one repair is housekeeping, many is a live poisoner) — this is the same observable
    surfaced at the one place every agent already passes through first (`--assert`), so a
    poisoner does not require someone to think to run `doctor.py` before it is noticed.

    ⚠️ "since this engine's version last changed" is APPROXIMATED by this install's own
    `.claude-plugin/plugin.json` mtime — no exact "version changed at" timestamp exists anywhere
    on disk, and a file's own write time is the closest honest proxy available without inventing
    a new stamp. Good enough to separate "before this release" from "under it," not exact to the
    second — said here rather than implied, per this file's own rule about honest limits.

    Best-effort and silent on any failure: an advisory that cannot be computed must never affect
    binding's actual verdict or block a caller that only wants that verdict."""
    try:
        from _root import engine_root
        import _diag
        pj = os.path.join(engine_root(), ".claude-plugin", "plugin.json")
        since = os.path.getmtime(pj)
    except Exception:                                    # noqa: BLE001
        return
    try:
        lines = _diag.tail(_diag.MAX_LINES, path=_diag.MACHINE_LOG)
    except Exception:                                     # noqa: BLE001
        return
    repairs = stale = 0
    for l in lines:
        try:
            rec = json.loads(l)
        except ValueError:
            continue
        when = _epoch(rec.get("at"))
        if when is not None and when < since:
            continue                                      # from before this version — stale news
        ev = rec.get("event")
        if ev == "pointer-repair":
            repairs += 1
        elif ev == "stale-copy-session":
            stale += 1
    if stale:
        print("NOTE: %d stale-copy-session refusal(s) recorded since this engine version was "
              "installed — a session somewhere ran an OLDER copy than what is now installed and "
              "refused to regenerate the launcher backward. See doctor.py." % stale,
              file=sys.stderr)
    elif repairs >= 3:
        print("NOTE: %d engine-pointer repair(s) recorded since this engine version was "
              "installed — this may be a live poisoner rewriting the pointer backward, not "
              "one-off housekeeping. See doctor.py." % repairs, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(
        description="Is this session bound to a job-search profile, and by what evidence?")
    ap.add_argument("--assert", dest="assert_", action="store_true",
                    help="exit 0 only when bound by env or cwd; refuse pointer-only, loudly")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    b = binding()
    if args.assert_:
        _pointer_advisory()
    if args.json:
        print(json.dumps(b, sort_keys=True))
        return EXIT_BOUND if b["bound"] else (
            EXIT_POINTER_ONLY if b["signal"] == "pointer" else EXIT_NO_PROFILE)

    if b["bound"]:
        print("BOUND via %s: %s" % (b["signal"], b["root"]))
        return EXIT_BOUND

    if b["signal"] == "pointer":
        if args.assert_:
            _diag_event("refused-pointer-only")
            print("NOT BOUND — REFUSED (pointer-only). The machine remembers a profile at\n"
                  "  %s\n"
                  "but this session shows no evidence it belongs to it: CLAUDESEARCH_ROOT is "
                  "unset and no profile marker (config.json or data/) sits at or above the "
                  "working directory. A jobsearch agent dispatched here must STOP without "
                  "reading or writing that profile (dev #150).\n"
                  "If this dispatch genuinely is part of the job search, either run from the "
                  "profile directory or have the dispatching session name the root so every "
                  "command can be prefixed with CLAUDESEARCH_ROOT=<root>. MCP servers and "
                  "read-only diagnostics are unaffected — they do not call --assert."
                  % b["root"])
            return EXIT_POINTER_ONLY
        print("NOT BOUND (pointer-only): the machine remembers a profile at %s, but this "
              "session carries no evidence of its own (no CLAUDESEARCH_ROOT, no profile at or "
              "above the cwd). Say which profile you are acting on before acting." % b["root"])
        return EXIT_BOUND

    _diag_event("no-profile")
    print("NO PROFILE — nothing bindable: CLAUDESEARCH_ROOT is unset, no profile marker at or "
          "above the working directory, and nothing remembered at ~/.claude/jobsearch/"
          "profile_root. If a job-search profile exists on this machine, run from its "
          "directory; if none exists yet, the jobsearch:onboarding skill creates one.")
    return EXIT_NO_PROFILE


if __name__ == "__main__":
    sys.exit(main())
