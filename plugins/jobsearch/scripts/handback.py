#!/usr/bin/env python3
"""The hand-back contract, stated once (dev #811 / public #170, dev #812 / public #169).

A pass hands its work back as a text block (`ROLES v1`, `SWEEP v1`). Two scripts record one --
`deferred.py --add-roles` and `linkedin_sweep.py record` -- and both cite THIS module for the rule
they share, so the rule exists in one place and a third parser would cite it too.

    A hand-back block is refused whole only for a STRUCTURAL fault: no block, two blocks, a header
    that does not parse, a `run=` (or `surface=`) that is not this call's, no END line. Without
    those, nothing says which lines belong to this call. Every other fault is a LINE fault: the
    line is dropped, it becomes a `partial-results` gap of its own naming the line number, its
    text and the rule, and everything else that parsed is recorded. Whenever a call refuses or
    records a fault, the raw hand-back is copied byte for byte under the profile root, and the
    message and the gap name the copy. `--check` runs the same judgement, writes nothing, prints
    each fault and one `verdict:` line, and exits with the code the real call would.

What lives here is only what the two parsers truly share: the fault shape, the printed fault, the
kept raw copy, the line-gap bookkeeping and the `verdict:` line. The GRAMMARS stay in their own
scripts and so do the exit numbers (`deferred.py` uses 4 for "accepted with line faults";
`linkedin_sweep.py` already uses 4 for PASS FAILED and adds 5).

Stdlib only. It reads and writes nothing of its own: every function is given the profile `root`.
`kind="roles"` reproduces `deferred.py`'s 0.81.0 kept path (`roles-<run>-<surface>.md`) exactly, so
no kept file moves; `test_handback.py` pins that against a literal taken from the 0.81.0 function.
"""

import os
import re

# Under the PROFILE root, never the engine. `.jobsearch/` is machine-local (it is not synced);
# `data/runs.jsonl` syncs. `journal.check_recorded_fields` holds a `kept` value to this prefix.
HANDBACK_DIR = (".jobsearch", "handbacks")

# The verdict names -- exactly `journal.RECORD_VERDICTS` (a test pins the equality), restated so
# that a caller can print a `verdict:` line without importing the journal.
VERDICTS = ("clean", "incomplete", "line-faults", "refused", "pass-failed", "pane-held")


class Fault(dict):
    """The one fault shape: `{"line", "text", "scope_key", "rule"}`.

    `line` is the 1-based line number, or `None` for a block-level check; `text` is the line's text
    (or `None`); `scope_key` is the tail of the line gap's scope; `rule` says which rule it broke.

    A `dict` on purpose, with attribute access added: `deferred.parse_roles` has always built plain
    dicts, and `Fault(...) == {"line": ..., ...}` holds, so a caller (or a test) written against the
    dict shape keeps working unchanged."""

    __slots__ = ()

    def __init__(self, line, text, scope_key, rule):
        super().__init__(line=line, text=text, scope_key=scope_key, rule=rule)

    line = property(lambda self: self["line"])
    text = property(lambda self: self["text"])
    scope_key = property(lambda self: self["scope_key"])
    rule = property(lambda self: self["rule"])


def describe(fault):
    """The printed form of a fault (a `Fault`, or a plain dict of the same four keys):
    `LINE FAULT  line N: <rule> -- '<text>'`, or `BLOCK FAULT: <rule>` when `line` is None."""
    if fault["line"] is None:
        return "BLOCK FAULT: %s" % fault["rule"]
    return "LINE FAULT  line %d: %s -- %r" % (fault["line"], fault["rule"], fault["text"])


def kept_rel(kind, run_id, surface):
    """The profile-relative path of the kept raw hand-back: `.jobsearch/handbacks/<kind>-<safe
    run>-<surface>.md`. Keyed by run AND surface, so a re-run of the same call overwrites its own
    copy and never another pass's. (Not keyed by agent: the agent contract names a hand-back
    `<agent>-<date>.md`, which a second same-day dispatch would overwrite.)"""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(run_id))[:80].strip("-") or "run"
    return "/".join(HANDBACK_DIR + ("%s-%s-%s.md" % (kind, safe, surface),))


def kept_where(rel, run_id):
    """Every gap text, refusal message and run-summary line that names a kept copy uses this one
    function, so the wording cannot drift. The engine records no machine name, so the run id
    stands in: `.jobsearch/` is machine-local while `data/runs.jsonl` syncs."""
    return "%s (kept on the machine that recorded run %s)" % (rel, run_id)


def keep(root, kind, run_id, surface, text, out=print):
    """Copy the raw hand-back under the profile `root`, byte for byte, so a refused or faulty block
    is never lost with the dispatch that wrote it. Returns the absolute path, or `None` -- reported
    through `out`, never swallowed -- when it cannot be written."""
    path = os.path.join(root, *kept_rel(kind, run_id, surface).split("/"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as e:
        out("⚠️ could not keep a copy of the hand-back at %s (%s)" % (path, e))
        return None
    return path


def _file_gap(root, run_id, scope, reason, closes_when, out):
    """One gap per `(run, scope)`: a second call in the same run adds nothing. Best-effort and
    loud: a journal that cannot be written (the tracked fixture) is reported, not swallowed."""
    import journal as _journal
    try:
        if any(g.get("scope") == scope
               for g in _journal.open_gaps(_journal.read(root), run_id=run_id)):
            return None
        return _journal.record_gap(root, run_id, scope, reason, closes_when=closes_when)
    except _journal.JournalError as e:
        out("⚠️ could not journal the gap %s (%s)" % (scope, e))
        return None


def file_line_gaps(root, run_id, scope_fmt, faults, closes_when, out=print):
    """File one `partial-results` gap per fault, once per run per scope. The scope is
    `scope_fmt % fault["scope_key"]` (so `scope_fmt` holds exactly one `%s`). `closes_when` is a
    string, or a callable taking the fault and returning one (the gap text usually names the line).
    Returns the scopes of EVERY fault, in order, whether the gap was new or already open, so the
    caller can hand them to `close_stale_line_gaps` as the set that is still current."""
    scopes = []
    for f in faults:
        scope = scope_fmt % f["scope_key"]
        scopes.append(scope)
        _file_gap(root, run_id, scope, "partial-results",
                  closes_when(f) if callable(closes_when) else closes_when, out)
    return scopes


def close_stale_line_gaps(root, run_id, prefix, current, out=print):
    """A corrected re-submission closes the line gaps it no longer has: every OPEN gap of this run
    whose scope starts with `prefix` and is not in `current` is closed. Returns the closed scopes."""
    import journal as _journal
    keep_scopes = set(current)
    closed = []
    for g in _journal.open_gaps(_journal.read(root), run_id=run_id):
        sc = str(g.get("scope", ""))
        if sc.startswith(prefix) and sc not in keep_scopes:
            try:
                _journal.append(root, {"event": "gap-closed", "gap_id": g["gap_id"],
                                       "at": _journal.now_iso()})
            except _journal.JournalError as e:
                out("⚠️ could not close the gap %s (%s)" % (sc, e))
                continue
            closed.append(sc)
            out("GAP CLOSED %s (the corrected hand-back no longer has this fault)" % sc)
    return closed


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def verdict_line(verdict, n_faults=0, detail=None):
    """The one `verdict:` line `--check` and the real call print, for a verdict in `VERDICTS`:

        clean        `verdict: clean`                                      (n_faults 0)
        incomplete   `verdict: incomplete: N not concluded`                (detail = N)
        line-faults  `verdict: N line fault(s)`, plus `; M not concluded`  (n_faults > 0;
                     when detail = M is given -- `deferred.py` gives none)
        refused      `verdict: refused: <detail>`                          (detail = why)
        pass-failed  `verdict: pass failed: <detail>`                      (detail = the reason)
        pane-held    `verdict: pass failed: pane held`

    `deferred.py` passes its own three outcomes and prints exactly today's text. `verdict: clean`
    is printed ONLY for a call with no fault and nothing left unconcluded: a `clean` with faults,
    or `line-faults` with none, is a caller's bug and raises."""
    if verdict not in VERDICTS:
        raise ValueError("verdict_line: %r is not one of %r" % (verdict, VERDICTS))
    if verdict == "clean":
        if n_faults or detail:
            raise ValueError("verdict_line: 'clean' with faults or detail (%r, %r) -- a clean "
                             "verdict is printed only for a call with nothing wrong"
                             % (n_faults, detail))
        return "verdict: clean"
    if verdict == "incomplete":
        return "verdict: incomplete: %s not concluded" % (0 if detail is None else detail)
    if verdict == "line-faults":
        if n_faults <= 0:
            raise ValueError("verdict_line: 'line-faults' with n_faults=%r" % (n_faults,))
        line = "verdict: %s" % _plural(n_faults, "line fault")
        if detail is not None:
            line += "; %s not concluded" % detail
        return line
    if verdict == "refused":
        return "verdict: refused: %s" % detail
    if verdict == "pass-failed":
        return "verdict: pass failed: %s" % detail
    return "verdict: pass failed: pane held"
