"""hidden_passes: consecutive LinkedIn passes run with the Browser pane hidden, escalated to the owner (dev #1026 / public #271).

Capability module of `coordinator.py` (the start line) and `run_summary.py` (the headline, the detail and the post's urgency).

A pass run while the pane is hidden reads LinkedIn by text: its job cards carry no links, so it captures next to nothing. Each such
pass is still recorded (`pass linkedin recorded`, `mode: hidden`), closes the owed pass and opens ONE `pane-hidden` gap that later
hidden passes leave open without a word. A week of them read as a sweep that runs. This module counts the TRAILING streak of recorded
LinkedIn passes whose `mode` is `hidden` (any other recorded LinkedIn pass ends the streak, so one pass with the pane shown clears it),
and from `BLOCK_AFTER` passes on words the escalation: the start line the coordinator prints, the clause the run summary's headline
carries, and the detail line. The run summary's post is `urgency: high` while the streak stands. Pure: the callers pass the journal
records and print; nothing here reads a file or writes one.
"""

BLOCK_AFTER = 3          # consecutive hidden passes: the count lifecycle.HELD_ROUTE_AFTER gives a role before YOUR READ
REMEDY = "run /jobsearch:linkedin once in the desktop app with the Browser pane shown and in view"


def hidden_streak(recs):
    """`(n, first_at)`: how many of the latest recorded LinkedIn passes, in journal order, ran with `mode: hidden`, and the `at`
    of the first of them (None when n is 0). A recorded LinkedIn pass with any other `mode` (normal, unreported, none) ends it."""
    rows = [r for r in recs or () if isinstance(r, dict) and r.get("event") == "pass"
            and r.get("kind") == "linkedin" and r.get("phase") == "recorded"]
    n = 0
    for r in reversed(rows):
        if r.get("mode") != "hidden":
            break
        n += 1
    return n, (str(rows[-n].get("at") or "")[:10] or None) if n else None


def blocking(recs, after=BLOCK_AFTER):
    """True when the streak has reached `after` passes: the sweep is effectively not running."""
    return hidden_streak(recs)[0] >= after


def start_lines(recs, after=BLOCK_AFTER):
    """The coordinator's start line for the streak, as a list (empty below `after`)."""
    n, since = hidden_streak(recs)
    if n < after:
        return []
    return ["LINKEDIN SWEEP NOT RUNNING — BLOCKING: the last %d LinkedIn passes (since %s) ran with the Browser pane hidden, so "
            "they read job cards without links and captured almost nothing. Only you can clear it: %s." % (n, since or "?", REMEDY)]


def headline_clause(recs, after=BLOCK_AFTER):
    """` · BLOCKING: LinkedIn sweep not running (<n> hidden-pane passes)` for the run summary's headline, or ``."""
    n, _since = hidden_streak(recs)
    return " · BLOCKING: LinkedIn sweep not running (%d hidden-pane passes)" % n if n >= after else ""
