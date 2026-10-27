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
(`--may board` adds exit 3: the journal it needs for the schedule cannot be read.)

    ~/.claude/jobsearch/run posture.py --may board [--attended] [--run ID] [--today YYYY-MM-DD]
    ~/.claude/jobsearch/run posture.py --set-board-days mon,thu [--posture NAME]   # or: none

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

⭐ A BOARD SWEEP IS GATED BY DAY, NOT ONLY BY PERMISSION (dev #770-4, jobsearch 0.78.0)
--------------------------------------------------------------------------------------
`board` is a real unattended token on economy, standard and full, never on minimal. Owner ruling
O4 splits the sweep in two: `company_days` (weekday names) says WHICH days a sweep of employer career
pages may start, and `board_days` which days a sweep of job boards and aggregators may; each kind
spends its own slot. A sweep is due on
the first run on or after a scheduled weekday since the last board pass that was not a crashed one
(`board_slot`, `board_spent_on`); the answer is `board_check`, in-process `board_gate`, on the CLI
`posture.py --may board [--attended] [--run ID] [--today D]`. `board` is a GATED token like
`linkedin`: never merged into a claim's capabilities (`GATED_POSTURE_TOKENS`). The days are set
with `--set-company-days` / `--set-board-days` (validated, atomic), and READ strictly: a missing or malformed value refuses
loudly and is never `[]` or a default. design-employer-discovery.md §5.

Python 3.9+, stdlib only.
"""

import argparse
import datetime
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

# dev #770-4 (design-employer-discovery.md §5.1) -- the unattended tokens whose permission is a
# GATE of their own, not a claim capability: `linkedin` (browser + quota) and `board` (the weekday
# schedule). `merge_tokens` skips both SILENTLY (there is nothing to report: the caller sets the
# permission through `may()`), where any other non-mergeable token is ignored AND reported.
GATED_POSTURE_TOKENS = ("linkedin", _ck.BOARD_TOKEN)

# Owner ruling O6 (jobsearch 0.78.0, supersedes O5) -- research is NOT posture-gated: a role found in a run
# whose minimal screen keeps it is researched in that run, on every posture, `minimal` included. The gate on
# research is the screen (`deferred.research_screen_refusal`), never a posture level, which gates the sweeps.
# So `merge_tokens` grants these on every posture (a `research` already listed in `unattended` is not an
# error and is not reported), `may()` answers True, and `--may research` exits 0 with RESEARCH_UNGATED_LINE.
# A 0.77.0 engine on a second machine still reads the token and keeps holding research on a posture that
# lacks it; no token is removed from any profile.
UNGATED_POSTURE_TOKENS = ("research",)
RESEARCH_UNGATED_LINE = "OK: research is not posture-gated (0.78.0)"

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


def load(root=None):
    path = os.path.join(root or ROOT, "config.json")
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
      `may("linkedin")`, set by the caller), so there is nothing to report; `board` likewise
      (`GATED_POSTURE_TOKENS`: its permission is `board_gate`);
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
        report.append("posture unreadable: no posture tokens merged (research is not "
                      "posture-gated and is granted anyway)")
    else:
        for token in (p.get("unattended") or []):
            if token in GATED_POSTURE_TOKENS:
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
    for token in UNGATED_POSTURE_TOKENS:          # O6: on every posture, attended or not
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


def _record_attended_note(run_id, capability, root=None):
    """R2 — an attended run that went past its posture leaves a `note` row, so the run summary
    shows it. Best-effort, loud on stderr: a journal that cannot be written (the tracked fixture)
    must not turn a permitted attended run into a refusal."""
    import journal as _journal
    try:
        _journal.append(root or ROOT, {"event": "note", "run_id": run_id,
                               "text": "attended: %s permitted outside posture" % capability,
                               "at": _journal.now_iso()})
    except _journal.JournalError as e:
        print("⚠️ could not journal the attended note (%s)" % e, file=sys.stderr)


# ── the board-sweep schedule (dev #770-4; design-employer-discovery.md §5.1-§5.3) ───────────────

def weekday_name(d):
    """`mon`..`sun` for a `datetime.date` (the vocabulary of `board_days`)."""
    return _ck.WEEKDAYS[d.weekday()]


def board_slot(board_days, last_spent_on, today):
    """`(due, slot, next_slot)` -- the A7 rule, on or after rather than "today is":

      slot      the latest date d <= today, looking back at most 6 days, whose weekday is in
                `board_days` (None when `board_days` is empty)
      due       a slot exists and (nothing was ever spent, or the last spend is BEFORE the slot)
      next_slot the earliest date d > today whose weekday is in `board_days`

    Pure over dates. A machine asleep through a slot does not replay it one per slot: the sweep is
    due once, on the first run on or after the latest slot. `last_spent_on` is a `datetime.date` or
    None."""
    days = set(board_days)
    slot = next((today - datetime.timedelta(days=back) for back in range(7)
                 if weekday_name(today - datetime.timedelta(days=back)) in days), None)
    due = slot is not None and (last_spent_on is None or last_spent_on < slot)
    next_slot = next((today + datetime.timedelta(days=fwd) for fwd in range(1, 8)
                      if weekday_name(today + datetime.timedelta(days=fwd)) in days), None)
    return due, slot, next_slot


def _sweep_of(r):
    """The kind of board-sweeper work a `pass board` row covered (O4): its `sweep` field, or BOTH
    kinds for a row without one (written before 0.78.0, by a sweep over every board type). A value
    outside `SWEEP_KINDS` raises `ValueError`: a row this cannot read is refused, never skipped."""
    s = r.get("sweep")
    if s is None:
        return set(_ck.SWEEP_KINDS)
    if s not in _ck.SWEEP_KINDS:
        raise ValueError("a board pass row has an unreadable sweep (%r)" % (s,))
    return {s}


def board_spent_on(recs, sweep=None):
    """The latest `datetime.date` a board pass SPENT a slot of kind `sweep` (`company` or `board`,
    owner ruling O4; None counts every kind), over the journal's `recs`, or None. Each kind's slot is
    counted separately: a row whose `sweep` is `company` never spends a `board` slot, or the reverse;
    a row with no `sweep` (before 0.78.0) spends both.

    A row carrying `attended: true` (a pass a person started on demand, `/jobsearch:search ...
    attended` or `/jobsearch:daily-run attended`) spends nothing: the schedule limits unattended work
    only, so attended work neither waits for a slot nor uses one up.

    A slot is spent by every other `pass board dispatched` row EXCEPT a crashed pass: its run has an `end`
    row and neither a `pass board returned` row nor a `roles` event with `surface: board` (a board
    pass returns through the `roles` event today; `returned` is accepted too, so a later writer needs
    no change here). So a pass in flight (run not ended) and a pass that returned, degraded or not,
    spend the slot; a crashed pass does not, and the next run in the slot dispatches again.

    The date is `str(at)[:10]`, the naive local-time date `journal.now_iso()` writes. A row whose
    `at` is not an ISO date raises `ValueError`: a journal this cannot read is refused, never
    skipped. (The generalisation of `journal.crashed_passes` to a second kind is kept here because
    that module is outside this change's file set; the LinkedIn call there is unchanged.)"""
    ended = {r.get("run_id") for r in recs if r.get("event") == "end"}
    returned = {r.get("run_id") for r in recs
                if (r.get("event") == "pass" and r.get("kind") == "board"
                    and r.get("phase") == "returned")
                or (r.get("event") == "roles" and r.get("surface") == "board")}
    spent = []
    for r in recs:
        if not (r.get("event") == "pass" and r.get("kind") == "board"
                and r.get("phase") == "dispatched"):
            continue
        if r.get("attended") is True:
            # dev #770 (/jobsearch:search): an attended pass is outside the schedule and never
            # spends its slot, so the scheduled sweep still runs on its day.
            continue
        kinds = _sweep_of(r)
        if sweep is not None and sweep not in kinds:
            continue                                        # the other kind's slot
        rid = r.get("run_id")
        if rid in ended and rid not in returned:
            continue                                        # a crashed pass spends nothing
        try:
            spent.append(datetime.date.fromisoformat(str(r.get("at"))[:10]))
        except ValueError:
            raise ValueError("a board pass row has an unreadable `at` (%r)" % (r.get("at"),))
    return max(spent) if spent else None


def board_check(p, name, today, recs=None, root=None, fresh=False, sweep="board"):
    """The board gate's one answer for ONE sweep kind (`company`: `company_days`, employer career
    pages; `board`: `board_days`, job boards and aggregators; owner ruling O4), as a dict
    `{state, line, slot, next_slot, last, sweep}`. Each line starts with the kind (`company:` or
    `board:`), so the two answers never read alike.

    `state` is `yes` (a sweep may start unattended), `no` (not permitted, or not due),
    `unreadable` (the posture, its `unattended` list or `board_days` cannot be read: refused
    loudly, never read as `[]` or as a default) or `journal` (`runs.jsonl` cannot be read). `line`
    is the one reason line `--may board` prints. `recs` is the journal's rows (read here when None;
    a MISSING `runs.jsonl` reads as no rows, so a fresh journal is due once, said in the line; a
    caller that read the journal itself passes `fresh=True` when the file did not exist)."""
    if sweep not in _ck.SWEEP_KINDS:
        raise ValueError("sweep %r is not one of %s" % (sweep, ", ".join(_ck.SWEEP_KINDS)))
    key = _ck.SWEEP_DAYS_KEY[sweep]
    out = {"state": "no", "line": "", "slot": None, "next_slot": None, "last": None,
           "sweep": sweep}
    unattended = (p or {}).get("unattended") if isinstance(p, dict) else None
    if not isinstance(unattended, list):
        out.update(state="unreadable",
                   line="%s: unattended list unreadable on posture %s" % (sweep, name))
        return out
    if _ck.BOARD_TOKEN not in unattended:
        out["line"] = "%s: not permitted unattended on posture %s" % (sweep, name)
        return out
    try:
        days = _ck.resolve_days(p, key)
    except ValueError as e:
        out.update(state="unreadable",
                   line="%s: %s unreadable on posture %s (%s)" % (sweep, key, name, e))
        return out
    if not days:
        out["line"] = ("%s: %s is empty on posture %s (never unattended)" % (sweep, key, name))
        return out
    import journal as _journal
    try:
        if recs is None:
            fresh = not os.path.exists(_journal.path(root or ROOT))
            recs = _journal.read(root or ROOT)
        last = board_spent_on(recs, sweep)
    except (_journal.JournalError, ValueError) as e:
        out.update(state="journal", line="%s: journal unreadable (%s)" % (sweep, e))
        return out
    due, slot, next_slot = board_slot(days, last, today)
    out.update(slot=slot, next_slot=next_slot, last=last)
    if due:
        out["state"] = "yes"
        if fresh:
            out["line"] = "%s: due (slot %s %s), first board sweep (no journal yet)" % (
                sweep, weekday_name(slot), slot.isoformat())
        elif last is None:
            out["line"] = "%s: due (slot %s %s, no %s pass spent yet)" % (
                sweep, weekday_name(slot), slot.isoformat(), sweep)
        else:
            out["line"] = "%s: due (slot %s %s, last spent %s %s)" % (
                sweep, weekday_name(slot), slot.isoformat(), weekday_name(last), last.isoformat())
    else:
        out["line"] = "%s: not due until %s %s" % (sweep, weekday_name(next_slot),
                                                  next_slot.isoformat())
    return out


def _any_due(checks):
    """True iff some kind is due AND no kind is unreadable: a posture whose `company_days` or
    `board_days` cannot be read refuses the whole board answer, loudly, rather than half-answering
    (the same rule `channels_due.board_decision` applies with exit 3)."""
    states = {c["state"] for c in checks}
    return "yes" in states and not states & {"unreadable", "journal"}


def board_checks(p, name, today, recs=None, root=None, fresh=False):
    """`board_check` for every sweep kind, in `SWEEP_KINDS` order (company, then board), reading
    the journal ONCE. Returns a list of the per-kind dicts."""
    if recs is None and isinstance(p, dict):
        import journal as _journal
        try:
            fresh = not os.path.exists(_journal.path(root or ROOT))
            recs = _journal.read(root or ROOT)
        except _journal.JournalError as e:
            return [{"state": "journal", "line": "%s: journal unreadable (%s)" % (k, e),
                     "slot": None, "next_slot": None, "last": None, "sweep": k}
                    for k in _ck.SWEEP_KINDS]
    return [board_check(p, name, today, recs=recs, root=root, fresh=fresh, sweep=k)
            for k in _ck.SWEEP_KINDS]


def _as_date(today):
    """A `datetime.date` from a date, an ISO string or None (the system's local today)."""
    if today is None:
        return datetime.date.today()
    if isinstance(today, datetime.date):
        return today
    return datetime.date.fromisoformat(str(today)[:10])


def board_gate(today=None, attended=False, recs=None, root=None):
    """True iff a board sweep of EITHER kind may START now: the in-process form of `--may board`.
    Attended, it is True (a posture limits UNATTENDED work only, R2). Unattended it is True only when
    the posture is readable, `board` is in its `unattended` list, and for at least one kind its days
    key is readable and a slot is due. Fails SAFE: anything unreadable is False."""
    if attended:
        return True
    name, p, err = load(root)
    if err or p is None:
        return False
    return _any_due(board_checks(p, name, _as_date(today), recs=recs, root=root))


def set_company_days(root, days_arg, posture=None):
    """Write `search.postures.<name>.company_days` (O4: employer career pages): `set_board_days`'s
    twin, the same validation, the same atomic write."""
    return set_board_days(root, days_arg, posture, key=_ck.COMPANY_DAYS)


def set_board_days(root, days_arg, posture=None, key=None):
    """Write `search.postures.<name>.board_days` (or `key`, `company_days`) -- the ONE setter (never
    a hand edit of config.json: a typo stored there is refused at read, loudly, but the setter
    refuses it first).
    `days_arg` is a comma-separated list of weekday names, or `none` for `[]`. `posture` defaults to
    the active one. Atomic, every other key untouched. Returns `(name, days, note)`; raises
    `ValueError` naming the problem and writing nothing."""
    key = key or _ck.BOARD_DAYS
    text = (days_arg or "").strip()
    never = text.lower() in ("none", "[]")
    days = [] if never else [d.strip() for d in text.split(",") if d.strip()]
    if not never and not days:
        raise ValueError("no weekday names given (use e.g. mon,thu, or 'none' for never)")
    problems = _ck.validate_days(days, key)
    if problems:
        raise ValueError("; ".join(problems))
    path = os.path.join(root, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError("cannot read config.json (%s)" % e)
    search = cfg.get("search") if isinstance(cfg, dict) else None
    postures = search.get("postures") if isinstance(search, dict) else None
    if not isinstance(postures, dict):
        raise ValueError("config.search.postures is missing or not an object")
    name = posture or search.get("posture")
    if name not in postures or not isinstance(postures[name], dict):
        raise ValueError("posture %r is not defined in config.search.postures (have: %s)"
                         % (name, ", ".join(sorted(postures)) or "none"))
    postures[name][key] = days
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)                       # atomic: never a half-written config.json
    note = ""
    unattended = postures[name].get("unattended")
    if not isinstance(unattended, list) or _ck.BOARD_TOKEN not in unattended:
        note = ("board is not in posture %s's unattended list, so these days take effect only "
                "once it is" % name)
    return name, days, note


def _main_board(args, name, p, err):
    """`--may board`, its OWN branch (the generic `--attended` branch is for MERGEABLE tokens and
    would print REFUSED for `board`). Prints one reason line; exit 0 (a sweep may start), 1 (not
    permitted, not due, or posture/`board_days` unreadable) or 3 (the journal cannot be read).
    `--attended` exits 0 and, when the unattended answer was not yes and `--run` is given, journals
    the existing `attended: board permitted outside posture` note."""
    today = _as_date(args.today)
    if err:
        if args.attended:
            print("OK: attended run; posture limits unattended work only (posture unreadable: "
                  "%s)" % err)
            if args.run:
                _record_attended_note(args.run, _ck.BOARD_TOKEN)
            return 0
        print("POSTURE UNKNOWN (%s) -- refusing %r. Treating as MINIMAL." % (err, args.may))
        return 1
    res = board_checks(p, name, today)
    if args.attended:
        print("OK: attended run; posture limits unattended work only (%s)"
              % "; ".join(r["line"] for r in res))
        if not all(r["state"] == "yes" for r in res) and args.run:
            _record_attended_note(args.run, _ck.BOARD_TOKEN)
        return 0
    for r in res:                                   # one line per kind: company, then board
        print(r["line"])
    states = {r["state"] for r in res}
    if "journal" in states:
        return 3
    return 0 if _any_due(res) else 1


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
    if capability in UNGATED_POSTURE_TOKENS:      # O6: research is gated by the screen, not here
        return True
    _name, p, err = load()
    if err or p is None:
        return False
    if capability == _ck.BOARD_TOKEN:
        # dev #770-4 -- the plain permission is not the answer for `board`: the weekday schedule is.
        try:
            return _any_due(board_checks(p, _name, _as_date(today)))
        except ValueError:
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
    ap.add_argument("--today", metavar="YYYY-MM-DD", type=datetime.date.fromisoformat,
                    help="with --may board: the date to answer for (default: the local date).")
    ap.add_argument("--set-board-days", metavar="DAYS",
                    help="dev #770-4: set board_days on the active posture (or --posture NAME): "
                         "comma-separated weekday names (mon,thu), or 'none' for never. "
                         "Validated; the only way to change it (never a hand edit).")
    ap.add_argument("--set-company-days", metavar="DAYS",
                    help="owner ruling O4: set company_days (employer career-page sweeps) on the "
                         "active posture (or --posture NAME): comma-separated weekday names "
                         "(mon,wed), or 'none' for never. Validated; never a hand edit.")
    ap.add_argument("--posture", metavar="NAME",
                    help="with --set-board-days / --set-company-days: the posture to change "
                         "(default: the active one).")
    args = ap.parse_args()

    for value, key in ((args.set_company_days, _ck.COMPANY_DAYS),
                       (args.set_board_days, _ck.BOARD_DAYS)):
        if value is None:
            continue
        try:
            pname, days, note = set_board_days(ROOT, value, args.posture, key=key)
        except ValueError as e:
            print("REFUSED: %s not changed: %s" % (key, e))
            return 1
        print("OK: posture %r %s = %s" % (pname, key, ", ".join(days) or "none"))
        if note:
            print("   %s" % note)
    if args.set_company_days is not None or args.set_board_days is not None:
        return 0

    name, p, err = load()

    if args.may == _ck.BOARD_TOKEN:
        return _main_board(args, name, p, err)
    if args.may in UNGATED_POSTURE_TOKENS:
        # O6: no posture level gates research, readable or not, attended or not.
        print(RESEARCH_UNGATED_LINE)
        return 0

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
    if _ck.BOARD_TOKEN in (p.get("unattended") or []):
        for label, key in (("career-page days    ", _ck.COMPANY_DAYS),
                           ("job-board days      ", _ck.BOARD_DAYS)):
            try:
                print("  %s%s" % (label, ", ".join(_ck.resolve_days(p, key)) or "none"))
            except ValueError as e:
                print("  %sUNREADABLE (%s)" % (label, e))
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
