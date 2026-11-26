"""hidden_passes: consecutive LinkedIn passes run with the Browser pane hidden, escalated to the owner (dev #1026 / public #271; jobsearch 0.94.0, dev 1065, design-role-first.md 8.2, criterion LI3).

Capability module of `coordinator.py` (the start lines), `run_summary.py` (the headline, the detail and the post's urgency) and `channel_reach.py` (a due channel that no agent reaches).

A pass run while the pane is hidden reads LinkedIn by text: its job cards carry no links, so it can capture next to nothing. From 0.94.0 two KINDS of pass can be blocked, each by its own streak, each
cleared by the step that records a pass of ITS kind:

  replies  the reply sweep. The last `BLOCK_AFTER` reply `returned` rows (a `pass linkedin returned` row with no `scope`) EACH left a list surface unreachable, and the `recorded` row of that
           run says `mode: hidden`. A reply pass that reached every list is a NOTE (`note_lines`), never part of a streak (before 0.94.0 any hidden recorded pass counted, so a scheduled run, which is
           always hidden, made the block certain). A `returned` row whose run has no `recorded` row cannot be joined: it ENDS the streak and is counted unknown (`reply_streak`'s third value).
           Cleared by `/jobsearch:linkedin` with the pane shown.
  search   the LinkedIn job search. The last `BLOCK_AFTER` `roles` events of the `linkedin-jobsearch` surface that carry a `mode` were all `hidden`. A mode of `normal` or `unreported` ends it.
           Cleared by `/jobsearch:search linkedin attended`, which records a search pass.

THE CLEARANCE IS TEMPORARY, and every 0.94.0 line says so: a pass with the pane shown clears the block, and it returns after `BLOCK_AFTER` more hidden passes (a streak is the TRAILING run, so nothing is
stored and nothing needs resetting).

A PROFILE WITH NO 0.94.0 PIN KEEPS 0.93.0's RULE EXACTLY (RF4, `pinned`): any trailing `recorded` LinkedIn pass with `mode: hidden` counts, one streak, one remedy, the old words. The pin is read from the
rows themselves (a `profile-schema` row whose `min_engine` is 0.94.0 or later), because this package may not import `journaling` (`warning_hold` says why).

Pure: the callers pass the journal records and print; nothing here reads a file or writes one.
"""

BLOCK_AFTER = 3          # consecutive hidden passes: the count lifecycle.HELD_ROUTE_AFTER gives a role before YOUR READ
REMEDY = "run /jobsearch:linkedin once in the desktop app with the Browser pane shown and in view"
SEARCH_REMEDY = "run /jobsearch:search linkedin attended once in the desktop app with the Browser pane shown and in view"
TEMPORARY = "A pass with the pane shown clears it, and it comes back after %d more passes with the pane hidden" % BLOCK_AFTER
REPLIES, SEARCH = "replies", "search"
SURFACE = "linkedin-jobsearch"
PIN_FROM = (0, 94, 0)


def _day(at):
    return str(at or "")[:10] or None


def pinned(recs):
    """True when the journal carries a `profile-schema` pin of 0.94.0 or later (the same fact `journaling.pins.earliest_pin_at` answers, restated here because this package imports no `journaling`)."""
    for r in recs or ():
        if isinstance(r, dict) and r.get("event") == "profile-schema":
            try:
                if tuple(int(x) for x in str(r.get("min_engine")).split(".")) >= PIN_FROM:
                    return True
            except ValueError:
                continue
    return False


def _legacy_streak(recs):
    """0.93.0's rule, unchanged: `(n, first_at)` over the trailing recorded LinkedIn passes whose `mode` is `hidden` (any other recorded pass ends it)."""
    rows = [r for r in recs or () if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "recorded"]
    n = 0
    for r in reversed(rows):
        if r.get("mode") != "hidden":
            break
        n += 1
    return n, (_day(rows[-n].get("at")) if n else None)


def reply_streak(recs):
    """`(n, first_at, unknown)` for the reply sweep. PINNED: `n` of the latest reply `returned` rows, newest first, each left a list surface unreachable AND have a `recorded` row of their run at
    `mode: hidden`; `first_at` the date of the oldest of them (None when n is 0); `unknown` 1 when the streak ended on a row whose run has no `recorded` row, else 0. NOT PINNED: 0.93.0's rule."""
    if not pinned(recs):
        n, first = _legacy_streak(recs)
        return n, first, 0
    rows = [r for r in recs or () if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "returned" and not r.get("scope")]
    recorded = {}
    for r in recs or ():
        if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "recorded":
            recorded[r.get("run_id")] = r
    n, first, unknown = 0, None, 0
    for r in reversed(rows):
        if not r.get("unreachable"):
            break
        rec = recorded.get(r.get("run_id"))
        if rec is None:
            unknown = 1
            break
        if rec.get("mode") != "hidden":
            break
        n, first = n + 1, r.get("at")
    return n, (_day(first) if n else None), unknown


def search_streak(recs):
    """`(n, first_at)` for the job search: the trailing `roles` events of the `linkedin-jobsearch` surface that carry a `mode`, as long as it is `hidden`. `(0, None)` on a profile with no pin
    (an unpinned profile stores no `mode`, and its search ran inside the reply pass)."""
    if not pinned(recs):
        return 0, None
    events = [r for r in recs or () if isinstance(r, dict) and r.get("event") == "roles" and r.get("surface") == SURFACE and r.get("mode") is not None]
    n, first = 0, None
    for r in reversed(events):
        if r.get("mode") != "hidden":
            break
        n, first = n + 1, r.get("at")
    return n, (_day(first) if n else None)


def hidden_streak(recs):
    """`(n, first_at)` of the REPLY sweep's streak (`reply_streak` without the unknown count): the name the earlier callers know."""
    n, first, _unknown = reply_streak(recs)
    return n, first


def blocked_kinds(recs, after=BLOCK_AFTER):
    """`["replies", "search"]` filtered to the kinds whose streak has reached `after` passes."""
    return [k for k, n in ((REPLIES, reply_streak(recs)[0]), (SEARCH, search_streak(recs)[0])) if n >= after]


def blocking(recs, after=BLOCK_AFTER):
    """True when either kind's streak has reached `after` passes: the sweep, or the search, is effectively not running."""
    return bool(blocked_kinds(recs, after))


def remedy(kind):
    """The step that records a pass of `kind` (and so clears its block)."""
    return SEARCH_REMEDY if kind == SEARCH else REMEDY


def start_lines(recs, after=BLOCK_AFTER):
    """The coordinator's start lines, one per blocked kind (empty below `after`)."""
    out = []
    n, since, _u = reply_streak(recs)
    if n >= after and not pinned(recs):
        out.append("LINKEDIN SWEEP NOT RUNNING — BLOCKING: the last %d LinkedIn passes (since %s) ran with the Browser pane hidden, so they read job cards without links and captured "
                   "almost nothing. Only you can clear it: %s." % (n, since or "?", REMEDY))
    elif n >= after:
        out.append("LINKEDIN SWEEP NOT RUNNING — BLOCKING: the last %d LinkedIn passes (since %s) ran with the Browser pane hidden and left a list unread, so they read job cards without links "
                   "and captured almost nothing. Only you can clear it: %s. %s." % (n, since or "?", REMEDY, TEMPORARY))
    n, since = search_streak(recs)
    if n >= after:
        out.append("LINKEDIN JOB SEARCH NOT READING — BLOCKING: the last %d LinkedIn searches (since %s) ran with the Browser pane hidden, so they read job cards without links. "
                   "Only you can clear it: %s. %s." % (n, since or "?", SEARCH_REMEDY, TEMPORARY))
    return out


def headline_clause(recs, after=BLOCK_AFTER):
    """` · BLOCKING: LinkedIn sweep not running (<n> hidden-pane passes)` (and ` · BLOCKING: LinkedIn job search not reading (<n> hidden-pane searches)`) for the run summary's headline, or ``."""
    out = ""
    n = reply_streak(recs)[0]
    if n >= after:
        out += " · BLOCKING: LinkedIn sweep not running (%d hidden-pane passes)" % n
    n = search_streak(recs)[0]
    if n >= after:
        out += " · BLOCKING: LinkedIn job search not reading (%d hidden-pane searches)" % n
    return out


def note_lines(recs, run_id):
    """What a run's own hidden reply pass says when it was NOT a failure: `LinkedIn sweep note: ...` when the run's `recorded` row is `mode: hidden` and its `returned` row left no list
    unreachable (every list read, by text). A note, never a block. A pass that left a list unread says nothing here (it is the streak's). Nothing on a profile with no pin."""
    if not pinned(recs):
        return []
    rec = next((r for r in reversed(recs or ()) if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "recorded"
                and r.get("run_id") == run_id), None)
    ret = next((r for r in reversed(recs or ()) if isinstance(r, dict) and r.get("event") == "pass" and r.get("kind") == "linkedin" and r.get("phase") == "returned"
                and not r.get("scope") and r.get("run_id") == run_id), None)
    if rec is None or ret is None or rec.get("mode") != "hidden" or ret.get("unreachable"):
        return []
    return ["LinkedIn sweep note: this pass ran with the Browser pane hidden and still read every list, by text. It does not count toward a block."]
