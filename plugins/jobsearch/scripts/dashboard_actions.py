#!/usr/bin/env python3
"""dashboard_actions.py - the ONE table that maps a dashboard action block to the write it asks for.
dev #915 (jobsearch 0.88.0, design 7.3); the list form and `work-through` since dashboard-redesign (design 6).

THE PROBLEM. The candidate-facing page used to print `record.py ...` commands as `<code>` verbs. A person
reading a dashboard does not run a CLI, so 0.88.0 removes every command from the page (check_dashboard_
coverage.py's NO CLI gate). Each action is now a copy-as-prompt BLOCK: the candidate presses a button, pastes
the block into Claude Code, and the session follows the coordinator skill's section 5c.

THE BLOCK. Its grammar (the single form with `Record id:`, the list form with `Records:` and record lines, the
action table, the one writer and the one reader) lives in `dashboard/action_block.py` and is re-exported here,
so `dashboard_actions.block`, `.parse`, `.ACTIONS`, `.head`, `.record_line`, `.tail`, `.block_many` are the
same objects. This entry point adds the store checks and the writes:

  * single form: the dry run prints the ONE write (`WOULD RUN ...`), `--apply` runs it; an unknown action, a
    missing `Record id:` or an id absent from its store is refused whole (exit 2), nothing written;
  * list form (design 6.3): each record on its own, a refusal or failure never stopping the others:

      no record line                         REFUSED: the block names no record                     exit 2
      a line that is not a record line       REFUSED: line N is not a record line; nothing applied  exit 2
      the same id twice                      DUPLICATE <id> ignored (applied once)
      a kind the action does not take        REFUSED <id>: action <a> does not take kind <k>        counted refused
      an id absent from its store            REFUSED <id>: no <kind> <id> in data/<store>.jsonl     counted refused
      already in the state the action sets   ALREADY <id> (nothing written)                         counted applied
      record.py exits non-zero               FAILED <id>: record.py exit N                          counted failed
      a route action                         ROUTE N records: <request> (nothing is written ...)    exit 0; 1 if any REFUSED
      a write action, at the end             applied K of N (R refused, F failed)                   exit 0 iff K = N

Usage:
    ~/.claude/jobsearch/run dashboard_actions.py            < block      # dry run: prints the write(s)
    ~/.claude/jobsearch/run dashboard_actions.py --apply    < block      # runs them
    ~/.claude/jobsearch/run dashboard_actions.py --list                  # the table

Python 3.9+. Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))

# The closed list of spans the page renderer did NOT author (the candidate's own words): each is wrapped in
# `data-theirs="<site>"` by `dashboard.markup.theirs()`, and check_dashboard_coverage's NO CLI gate does not scan
# them. It lives with the renderer since dashboard-redesign A (a package module any script may import), and is
# imported back here for the callers that read it as `dashboard_actions.THEIRS_SITES`.
from dashboard.markup import THEIRS_SITES  # noqa: E402,F401
# The block's grammar (dashboard-redesign D3), re-exported: every caller keeps `dashboard_actions.<name>`.
from dashboard.action_block import (  # noqa: E402,F401
    ACTIONS, ANY_KIND, B_COMP_VERBS, FIRST_LINE, JOIN_ONLY, MANIFEST, MORE_PREFIX, STORE_OF, TRIGGER, ActionError,
    block, block_many, compose, head, kind_ok, kinds_of, parse, plugin_version, record_line, tail)


def _rows(root, store):
    path = os.path.join(root, "data", "%s.jsonl" % store)
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def _argv(spec, rid, given, row):
    """The `record.py` argv of a write action for one record. Raises ActionError for a missing field."""
    values = {"id": rid}
    for f in spec["fields"]:
        v = given.get(f, "")
        if not v or v.startswith("<"):
            raise ActionError("the block has no %s: refused, nothing written" % f.capitalize())
        values[f] = v
    for var, column in (spec.get("lookup") or {}).items():
        v = (row or {}).get(column)
        if not v:
            raise ActionError("the record carries no %s: refused, nothing written" % column)
        values[var] = v
    return [a.format(**values) for a in spec["argv"]]


def plan(parsed, root):
    """Single form: ("write", argv) for a one-line `record.py` write, ("already", rec) when the record already holds
    the state the write sets, or ("route", sentence) for an action the session routes itself. Raises ActionError when the id is absent from its store, or a required field is
    missing: nothing is guessed."""
    spec = ACTIONS[parsed["action"]]
    store = STORE_OF.get(parsed["kind"])
    row = None
    if store is not None:
        row = next((r for r in _rows(root, store) if r.get("id") == parsed["id"]), None)
        if row is None:
            raise ActionError("no %s %r in data/%s.jsonl: refused, nothing written"
                              % (parsed["kind"], parsed["id"], store))
    if spec["argv"] is None:
        return "route", spec["request"]
    already = spec.get("already")                  # a re-paste on a later day must not move the date (review R)
    if already and row is not None and row.get(already[0]) == already[1]:
        return "already", "%s:%s" % (parsed["kind"], parsed["id"])
    return "write", _argv(spec, parsed["id"], parsed["fields"], row)


def apply_many(parsed, root, emit, run=None):
    """The list form, one record at a time (design 6.3; the table in the module docstring). `emit(line)` prints;
    `run(argv)` runs one `record.py` write and returns its exit code (None: a dry run, which runs nothing). A
    refused or failed record never stops the others. Returns the exit code: 0 only when every record was applied
    (ALREADY counts) or routed; 1 otherwise."""
    action = parsed["action"]
    spec = ACTIONS[action]
    unique, seen = [], set()
    for rec, label in parsed["records"]:
        if rec in seen:
            emit("DUPLICATE %s ignored" % rec)
            continue
        seen.add(rec)
        unique.append((rec, label))
    cache, routed = {}, []
    applied = refused = failed = 0
    for rec, label in unique:
        kind, _sep, rid = rec.partition(":")
        if not _sep or not rid or not kind_ok(action, kind):
            emit("REFUSED %s: action %s does not take kind %s" % (rec, action, kind if _sep else "(none)"))
            refused += 1
            continue
        store, row = STORE_OF.get(kind), None
        if store is not None:
            if store not in cache:
                cache[store] = {r.get("id"): r for r in _rows(root, store)}
            row = cache[store].get(rid)
            if row is None:
                emit("REFUSED %s: no %s %s in data/%s.jsonl" % (rec, kind, rid, store))
                refused += 1
                continue
        if spec["argv"] is None:
            routed.append((rec, label))
            continue
        already = spec.get("already")
        if already and row is not None and row.get(already[0]) == already[1]:
            emit("ALREADY %s" % rec)
            applied += 1
            continue
        argv = _argv(spec, rid, {}, row)
        if run is None:
            emit("WOULD RUN %s: record.py %s" % (rec, " ".join(argv)))
            applied += 1
            continue
        rc = run(argv)
        if rc == 0:
            applied += 1
        else:
            emit("FAILED %s: record.py exit %d" % (rec, rc))
            failed += 1
    if spec["argv"] is None:
        emit("ROUTE %d records: %s (nothing is written by this script)"
             % (len(routed), spec.get("request_many", spec["request"])))
        for rec, label in routed:
            emit(record_line(rec, label))
        return 0 if not refused else 1
    emit("%s %d of %d (%d refused, %d failed)"
         % ("applied" if run is not None else "would apply", applied, len(unique), refused, failed))
    return 0 if applied == len(unique) else 1


def _say(line):
    print(line)
    sys.stdout.flush()           # before the next record.py child writes to the same stdout


def _run_record(argv):
    """Run one `record.py` write (its own output goes straight to stdout); its exit code."""
    return subprocess.run([sys.executable, os.path.join(HERE, "record.py")] + list(argv)).returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="run the write(s) (default: print them)")
    ap.add_argument("--list", action="store_true", help="print the action table")
    args = ap.parse_args()
    if args.list:
        for a, spec in sorted(ACTIONS.items()):
            kind = {None: "any", ANY_KIND: "every"}.get(spec["kind"], spec["kind"])
            print("%-24s %-9s %s" % (a, kind, " ".join(spec["argv"] or ["(routed)"])))
        return 0
    from _root import profile_root
    root = profile_root()
    try:
        parsed = parse(sys.stdin.read())
        if parsed["form"] == "list":
            if not args.apply and ACTIONS[parsed["action"]]["argv"] is not None:
                _say("DRY RUN (add --apply to run it); nothing is written:")
            return apply_many(parsed, root, _say, _run_record if args.apply else None)
        mode, what = plan(parsed, root)
    except ActionError as e:
        print("REFUSED: %s" % e)
        return 2
    if mode == "route":
        print("ROUTE %s %s: %s (nothing is written by this script)"
              % (parsed["action"], "%s:%s" % (parsed["kind"], parsed["id"]), what))
        return 0
    if mode == "already":
        print("ALREADY %s (nothing written)" % what)
        return 0
    if not args.apply:
        print("WOULD RUN (dry run; add --apply to run it): record.py %s" % " ".join(what))
        return 0
    return _run_record(what)


if __name__ == "__main__":
    sys.exit(main())
