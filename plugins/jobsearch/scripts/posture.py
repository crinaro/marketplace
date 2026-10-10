#!/usr/bin/env python3
"""What may this run do? Reads the ACTIVE posture and reports its budget.

WHY THIS EXISTS (2026-08-05)
----------------------------
The owner: *"i want to support multiple tiers, that could be a configuration of the user so it
works according to their budget."*

Cost in this system is almost entirely **runs per day x agents per run**. Deterministic sweeps are
free at any tier. So the tier is not a mode in the code — it is two numbers and a permission list,
and the engine reads them rather than hard-coding a cadence.

⭐ A RUN MUST ASK THIS BEFORE SPAWNING AN AGENT. The prompt cannot know which tier it is on, and
"just one quick research pass" is exactly how a token budget dies quietly.

Postures ship as DATA in `config.json` (`search.postures`), so a user can retune one or add their
own without touching the engine. The engine reads the knobs, never the name.

    ~/.claude/jobsearch/run posture.py              # what am I allowed to do?
    ~/.claude/jobsearch/run posture.py --may research [--attended]
    ~/.claude/jobsearch/run posture.py --cron       # the cron line this posture implies

Advisory; always exits 0 except for an explicit --may miss (exit 1) so a run can branch on it.

⭐ A POSTURE LIMITS HOW OFTEN, NEVER HOW MUCH (dev #692 / public #140, 2026-10-09)
-------------------------------------------------------------------------------
`unattended` lists the MODEL work a run may START without the owner present: a LinkedIn pass, a
research agent, a drafting agent. It never limits how much of what a run already FOUND gets
processed: capture and the minimal screen (`profile.py --minimal-screen`) run under every posture,
`minimal` and `economy` included. What a posture refuses is queued by a SCRIPT form
(`deferred.py --add-research` / `--add-draft` / `--add-linkedin-pass`) and drains on the first run
whose posture permits it (`MERGEABLE_POSTURE_TOKENS` below is the vocabulary `deferred.py` merges
into a worker's claim capabilities).

⭐ A RUN IS UNATTENDED BY DEFAULT (owner decision R2, 2026-10-09). The posture rules apply unless the
run was started with an explicit attended form (`/jobsearch:daily-run attended`, passed to scripts
as `--attended`). Attended is NEVER inferred from the absence of a scheduler marker: Claude Code
documents no in-session marker that tells a scheduled session from a typed one, so the default must
be the safe one (research waits and drains later). `--attended` lifts the research/drafting gate
only: it never grants `linkedin`, whose permission stays `may("linkedin")` (browser + quota).

Python 3.9+, stdlib only.
"""

import argparse
import json
import os
import sys

import os, sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _root import profile_root as _profile_root
import config_keys as _ck

ROOT = _profile_root()

# dev #692 / public #140 (N1) — the ONLY posture tokens that become claim capabilities in
# `deferred.py`: a fixed ENGINE vocabulary, not whatever a config.json happens to say. `linkedin`
# is deliberately absent and is NEVER merged: its permission is `may("linkedin")`, which applies
# the browser-capability check and the per-day quota on top of the plain `unattended` list, and a
# merged plain token would skip that second gate. An unknown or colliding token is IGNORED AND
# REPORTED (RFC 6749 §3.3's shape: a server that grants less than was asked says so), never
# silently granted and never silently dropped.
MERGEABLE_POSTURE_TOKENS = ("research", "drafting", "sweeps")

# Every hint a refusal prints names the LAUNCHER (`~/.claude/jobsearch/run`), never
# `python3 scripts/…`: the bare form resolves no engine on an installed plugin (N7, dev #167).
LAUNCHER = "~/.claude/jobsearch/run"


def queue_hint(capability, name):
    """The one line a refusal prints to say how to queue what the posture refused — a SCRIPT
    form where one exists (so the item carries `requires` and drains), the generic free-text
    `--add` only for a capability with no script form. Always the launcher."""
    if capability == "research":
        return "Queue it:  %s deferred.py --add-research <opp_id>" % LAUNCHER
    if capability == "drafting":
        return "Queue it:  %s deferred.py --add-draft <opp_id>" % LAUNCHER
    if capability == "linkedin":
        return "Queue it:  %s deferred.py --add-linkedin-pass" % LAUNCHER
    return ("Queue it instead:  %s deferred.py --add \"...\" --why \"posture %s\""
            % (LAUNCHER, name))


def load():
    path = os.path.join(ROOT, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        return None, None, "cannot read config.json (%s)" % e
    search = cfg.get("search") or {}
    name = search.get("posture")
    postures = search.get("postures") or {}
    if not name:
        return None, None, "config.search.posture is unset"
    if name not in postures:
        # A named posture with no definition is worse than none: the run cannot tell whether it
        # is permitted to do anything, and the safe reading is the cheapest one.
        return name, None, ("posture %r is not defined in config.search.postures (have: %s)"
                            % (name, ", ".join(sorted(postures)) or "none"))
    return name, postures[name], None


def merge_tokens(p, caps, attended=False):
    """dev #692 / public #140 (N1, R2) — `(granted, report)`: which posture tokens become claim
    capabilities on top of the machine's `caps` (a `whoami.probe()` dict), and one line per token
    that did not.

    * a token in the ACTIVE posture's `unattended` list is granted only if it is in
      `MERGEABLE_POSTURE_TOKENS` and is not already a key of `caps`;
    * `linkedin` is skipped silently: it is never a merged token (its permission is
      `may("linkedin")`, set by the caller), so there is nothing to report;
    * an unknown token, or one colliding with a machine capability, is ignored and REPORTED;
    * `attended=True` (the explicit attended form, R2) grants every mergeable token whatever the
      posture says, collisions still ignored, and NEVER `linkedin`;
    * an unreadable posture (`p is None`) grants nothing unattended and says so, failing safe the
      way `may()` does. An attended run still gets the mergeable tokens: the owner asked."""
    granted, report = [], []

    def _grant(token):
        if token in caps:
            line = "posture token %r ignored: collides with machine capability" % token
            if line not in report:
                report.append(line)
        elif token not in granted:
            granted.append(token)

    if p is None:
        report.append("posture unreadable: no posture tokens merged")
    else:
        for token in (p.get("unattended") or []):
            if token == "linkedin":
                continue
            if token not in MERGEABLE_POSTURE_TOKENS:
                report.append("posture token %r ignored: not in the engine vocabulary (%s)"
                              % (token, ", ".join(MERGEABLE_POSTURE_TOKENS)))
                continue
            _grant(token)
    if attended:
        for token in MERGEABLE_POSTURE_TOKENS:
            if token not in granted:
                _grant(token)
    return granted, report


def _linkedin_check(p, name, today=None):
    """design-script-first.md §2 (public #75/#76/#87/#110), build-list item 3 — the LinkedIn
    pass's own gate, layered ON TOP of the plain `unattended` permission every other capability
    already has: (1) `whoami.py --can chrome` — a browserless environment is refused BEFORE the
    quota is even consulted, so a pass that could never read a page never consumes one (#75);
    (2) the per-day quota, `config_keys.LINKEDIN_RUNS_PER_DAY` — 0 disables the capability on
    this posture outright (#76: reported as DISABLED, never printed as '0 of 0'), otherwise
    today's REACHED passes (`journal.linkedin_passes_reached` — a `returned` row with >= 1
    surface, never a mere `dispatched` one) must be under the key to still permit one more.

    Returns `(allowed, reason, message)`. `reason` is a `journal.REASONS` code — 'skipped-for-cost'
    for both the quota and the disabled-key case (both are cost decisions, not capability ones,
    design §2 item 3's own single-reason reading) — or `None` when permitted; `message` is the
    exact line `--may linkedin` prints."""
    import whoami as _whoami
    if not _whoami.probe().get("chrome"):
        return False, "browser-unavailable", (
            "REFUSED — browser unavailable (whoami.py --can chrome exits 1); no dispatch, no "
            "quota consumed")
    limit, _prov = _ck.describe(p, _ck.LINKEDIN_RUNS_PER_DAY)
    if limit == 0:
        return False, "skipped-for-cost", (
            "REFUSED — linkedin_runs_per_day is 0 on posture %r (LinkedIn passes disabled; "
            "deferred.py queues the work)" % name)
    import journal as _journal
    today = today or _journal.now_iso()[:10]
    count = _journal.linkedin_passes_reached(_journal.read(ROOT), today)
    if count >= limit:
        return False, "skipped-for-cost", (
            "REFUSED — quota: %d of %d LinkedIn passes already reached a surface today"
            % (count, limit))
    return True, None, "OK"


def _record_linkedin_refusal(run_id, reason):
    """#87 — 'a refused pass is a row, never a line'. Best-effort: a journal write that cannot
    land (e.g. --run points at the tracked fixture, which journal.append() itself refuses to
    write) must not crash the gate that is ALREADY reporting the refusal correctly — it is
    reported here, loud, on stderr, rather than silently swallowed."""
    import journal as _journal
    try:
        _journal.record_pass(ROOT, run_id=run_id, kind="linkedin", phase="refused",
                             reason=reason)
    except _journal.JournalError as e:
        print("⚠️ could not record the refused pass (%s) — the refusal above still stands" % e,
              file=sys.stderr)


def _record_attended_note(run_id, capability):
    """R2 — an attended run that went past its posture leaves a `note` row, so the run summary
    shows it. Best-effort, loud on stderr: a journal that cannot be written (the tracked fixture)
    must not turn a permitted attended run into a refusal."""
    import journal as _journal
    try:
        _journal.append(ROOT, {"event": "note", "run_id": run_id,
                               "text": "attended: %s permitted outside posture" % capability,
                               "at": _journal.now_iso()})
    except _journal.JournalError as e:
        print("⚠️ could not journal the attended note (%s)" % e, file=sys.stderr)


def may(capability, today=None, run_id=None):
    """True iff the ACTIVE posture permits `capability` unattended — the in-process form of
    `--may`, so a caller that must ask this before every step (design §26.8: `plays.py --all`
    is the first such caller, dev #292) does not pay a subprocess per step. Fails SAFE: an
    unreadable posture (no config, an undefined name) returns False, never True — the same
    "unreadable looks handled and is not" rule as everywhere else in this engine.

    For `capability == "linkedin"` this ALSO applies `_linkedin_check()` (the browser-capability
    and per-day-quota gate, design-script-first.md §2) on top of the plain permission list. Pass
    `run_id` to have a refusal recorded as a `pass … phase refused` row (#87) — omitted (the
    default) for a dry probe with no run in progress, which writes nothing it cannot attribute."""
    _name, p, err = load()
    if err or p is None:
        return False
    if capability not in (p.get("unattended") or []):
        return False
    if capability != "linkedin":
        return True
    allowed, reason, _msg = _linkedin_check(p, _name, today=today)
    if not allowed and run_id:
        _record_linkedin_refusal(run_id, reason)
    return allowed


def main():
    ap = argparse.ArgumentParser(description="What may this run do?")
    ap.add_argument("--may", metavar="CAPABILITY",
                    help="Exit 0 if the active posture permits it unattended, 1 if not. "
                         "e.g. sweeps, linkedin, research, drafting")
    ap.add_argument("--cron", action="store_true", help="Print the cron line this posture implies.")
    ap.add_argument("--run", metavar="ID",
                    help="with --may linkedin: record a refused pass under this run id (#87) — "
                         "omit for a dry probe with no run in progress. With --may <cap> "
                         "--attended: journal a note that the run went past its posture.")
    ap.add_argument("--attended", action="store_true",
                    help="dev #692 / R2: this run was started with the EXPLICIT attended form "
                         "(/jobsearch:daily-run attended). Lifts the posture's gate on research "
                         "and drafting (posture limits UNATTENDED work only). NEVER lifts "
                         "linkedin, whose permission is browser + quota. A run is unattended "
                         "unless it passes this; it is never inferred.")
    args = ap.parse_args()

    name, p, err = load()

    if err:
        # Fail SAFE, and say so loudly. An unreadable budget must not read as an unlimited one.
        if args.may and args.attended and args.may in MERGEABLE_POSTURE_TOKENS:
            # R2 — the owner asked for an attended run in so many words; an unreadable posture
            # does not take that away, and says so.
            print("OK: attended run; posture limits unattended work only (posture unreadable: "
                  "%s)" % err)
            if args.run:
                _record_attended_note(args.run, args.may)
            return 0
        if args.may:
            print("POSTURE UNKNOWN (%s) — refusing %r. Treating as MINIMAL." % (err, args.may))
            return 1
        print("⚠️ POSTURE UNKNOWN — %s" % err)
        print("   Falling back to the cheapest reading: deterministic sweeps only, no agents.")
        return 0

    if args.cron:
        print(p.get("cron", ""))
        return 0

    if args.may:
        if (args.attended and args.may in MERGEABLE_POSTURE_TOKENS
                and args.may not in (p.get("unattended") or [])):
            # R2 — an explicit attended run is past the posture's unattended limit for the
            # mergeable work. Journaled when a run id is given, so the summary shows it.
            print("OK: attended run; posture limits unattended work only")
            if args.run:
                _record_attended_note(args.run, args.may)
            return 0
        if args.may not in (p.get("unattended") or []):
            print("REFUSED: %r is NOT permitted unattended on posture %r" % (args.may, name))
            print("   %s" % queue_hint(args.may, name))
            return 1
        if args.may == "linkedin":
            # design-script-first.md §2 item 1 — the browser-capability gate runs BEFORE the
            # quota is even consulted, so a browserless launch never consumes it (#75).
            allowed, reason, msg = _linkedin_check(p, name, today=None)
            print(("OK: 'linkedin' is PERMITTED unattended on posture %r" % name) if allowed
                  else msg)
            if not allowed:
                if args.run:
                    _record_linkedin_refusal(args.run, reason)
                if reason == "skipped-for-cost":
                    print("   %s" % queue_hint("linkedin", name))
            return 0 if allowed else 1
        print("OK: %r is PERMITTED unattended on posture %r" % (args.may, name))
        return 0

    print("POSTURE — %s" % name)
    print("=" * 70)
    print("  runs per day        %s" % p.get("runs_per_day", "?"))
    # design-script-first.md §2/§12 (decision 1/4) — printed beside runs per day so a behaviour
    # change on upgrade (an existing profile's LinkedIn cadence decoupling from runs_per_day) is
    # visible on the FIRST run, never only discovered in a later run's refusal line. Provenance
    # follows config_keys.describe()'s own two phrases: "in your config.json" once the 0.54.0
    # migration (or the owner) has written it, "default — not in your file" otherwise.
    if "linkedin" in (p.get("unattended") or []):
        lrpd, lrpd_prov = _ck.describe(p, _ck.LINKEDIN_RUNS_PER_DAY)
        print("  linkedin passes/day %s (%s)" % (lrpd, lrpd_prov))
    print("  cron                %s" % p.get("cron", "?"))
    print("  max agents per run  %s" % p.get("max_agents_per_run", "?"))
    print("  unattended          %s" % ", ".join(p.get("unattended") or ["(nothing)"]))
    if p.get("_for"):
        print("\n  %s" % p["_for"])
    print("\n  ⭐ Deterministic sweeps are FREE at every tier and always run:")
    print("     alert_sweep · meeting_check · check_followups · channels_due · gates · dashboard")
    print("\n  ⭐ A posture limits how OFTEN a run starts model work, never how MUCH of what it found is")
    print("     processed: capture and the minimal screen run on every posture; research a")
    print("     posture refuses is queued and drains on the first run that permits it.")
    print("\n  Check one:  %s posture.py --may research" % LAUNCHER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
