#!/usr/bin/env python3
"""dashboard_actions.py - the ONE table that maps a dashboard action block to the write it asks for.
dev #915 (jobsearch 0.88.0, design 7.3).

THE PROBLEM. The candidate-facing page used to print `record.py ...` commands as `<code>` verbs. A person
reading a dashboard does not run a CLI, so 0.88.0 removes every command from the page (check_dashboard_
coverage.py's NO CLI gate). Each action is now a copy-as-prompt BLOCK: the candidate presses a button, pastes
the block into Claude Code, and the session follows the coordinator skill's section 5c.

THE BLOCK (modelled on the draft-correction block, SKILL.md 5b):

    Record this from my dashboard (copied from the dashboard; send it to /jobsearch:coordinator).
    Action: target-later
    Record id: company:c-0412
    Name:
    > Example Widgets Ltd
    Request: Ask me about this company next week.
    Date: 2026-11-03                        <- only an action that needs a value adds a named line

`Record id:` is the ONLY identity. `Name:` is for the reader: it is quoted (`> `) because it is the
candidate's own data, and the route never resolves a name to an id.

THIS MODULE IS THE MAPPING, a SKILL table would cost a model turn per paste and could drift:
  * `ACTIONS` maps an action id to its record kind, its `record.py` argv template, its extra fields and its
    plain-words request;
  * `block()` writes a block, `parse()` reads one (the same module, so they cannot disagree);
  * the CLI reads a block on stdin and prints the ONE write it would make (a dry run); `--apply` runs it.
    An unknown action, a missing `Record id:` or an id absent from its store is refused: nothing written.

Usage:
    ~/.claude/jobsearch/run dashboard_actions.py            < block      # dry run: prints the one write
    ~/.claude/jobsearch/run dashboard_actions.py --apply    < block      # runs it
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
FIRST_LINE = ("Record this from my dashboard (copied from the dashboard; "
              "send it to /jobsearch:coordinator).")
TRIGGER = "Record this from my dashboard"

# The closed list of spans the page renderer did NOT author (the candidate's own words): each is wrapped in
# `data-theirs="<site>"` by generate_dashboard.theirs(), and check_dashboard_coverage's NO CLI gate does not scan
# them. Named HERE, a leaf both import, because generate_dashboard.py is a script that cannot be imported.
THEIRS_SITES = ("kdoc-body", "role-title", "company-name", "person-name", "jd-detail", "fit-detail",
                "message-snippet")

# record kind -> the store whose row must exist. `send` names a staged draft by reference, not a stored row.
STORE_OF = {"company": "companies", "commit": "commitments", "touch": "touches", "ask": "asks",
            "proposal": "proposals", "opp": "opportunities", "person": "people", "chan": "channels",
            "send": None}

# `record.py` verbs another builder of the SAME release adds (B-comp, dev #915 C7: `company-later` writes
# `later_on`, `company-kind` writes `kind`). They are listed so a test can name them, never so a verb may
# go missing: once both land `test_dashboard_actions` requires every verb in `record.OPS`.
B_COMP_VERBS = ("company-later", "company-kind")

# action id -> {kind, argv (a template over {id} and each field; None = routed to a session step, not a
# one-line write), fields (named lines the action needs), request (plain words, no command)}.
ACTIONS = {
    # C7: targets to review
    "target-yes": {"kind": "company", "argv": ["company-status", "{id}", "active-target"], "fields": (),
                   "request": "Make this company an active target."},
    "target-no": {"kind": "company", "argv": ["company-status", "{id}", "passed"], "fields": (),
                  "request": "I am not interested in this company."},
    "target-later": {"kind": "company", "argv": ["company-later", "{id}"], "fields": (),
                     "request": "Ask me about this company next week."},
    "company-kind-employer": {"kind": "company", "argv": ["company-kind", "{id}", "employer"], "fields": (),
                              "request": "This is an employer, not a staffing firm or aggregator."},
    "company-kind-staffing": {"kind": "company", "argv": ["company-kind", "{id}", "staffing"], "fields": (),
                              "request": "This is a staffing firm. Stop listing it as a target."},
    "company-kind-aggregator": {"kind": "company", "argv": ["company-kind", "{id}", "aggregator"],
                                "fields": (), "request": "This is an aggregator. Stop listing it as a target."},
    # the Network to-record rows (funnel_report.network_rows), the argv each row's verb held, moved verbatim
    "chat-held": {"kind": "commit", "argv": ["attended", "{id}", "held"], "fields": (),
                  "request": "This chat happened. Record it as held."},
    "chat-no-show": {"kind": "commit", "argv": ["attended", "{id}", "no-show"], "fields": (),
                     "request": "This chat did not happen. Record it as a no-show."},
    "booking-chat": {"kind": "touch", "argv": ["chat", "{person}", "--on", "{date}", "--touch", "{id}"],
                     "fields": ("date",), "lookup": {"person": "person_id"},
                     "request": "Record the chat I had on the date below, for this booking."},
    "suggestion-yes": {"kind": "ask", "argv": ["confirm", "{id}"], "fields": (),
                       "request": "Yes, confirm this suggestion."},
    "suggestion-no": {"kind": "ask", "argv": ["decline", "{id}"], "fields": (),
                      "request": "No, decline this suggestion."},
    "send-observed": {"kind": "send", "argv": None, "fields": (),
                      "request": "I sent this message. Ask me which draft it was and record the send, "
                                 "or tell me to delete the draft."},
    "proposal-sent": {"kind": "proposal", "argv": ["proposal-status", "{id}", "sent"], "fields": (),
                      "request": "I sent this proposal. Record it as sent."},
    # C6: the communication plan's rows, routed to the drafting step (no one-line write)
    "draft-message": {"kind": None, "argv": None, "fields": (),
                      "request": "Draft the next message for this, and show it to me before anything is sent."},
}


class ActionError(ValueError):
    """A block that cannot be applied. Loud on purpose: the route runs nothing."""


def _kind_ok(action, kind):
    want = ACTIONS[action]["kind"]
    return want is None or want == kind


def block(action, rec_id, name=None, **fields):
    """The paste-ready block for `action` on `rec_id` (`<kind>:<id>`). `name` is the reader's label,
    quoted. Raises ActionError for an unknown action or a missing required field."""
    if action not in ACTIONS:
        raise ActionError("unknown action %r" % action)
    spec = ACTIONS[action]
    kind = str(rec_id).split(":", 1)[0] if ":" in str(rec_id) else ""
    if kind not in STORE_OF or not _kind_ok(action, kind):
        raise ActionError("action %s does not take a record id of kind %r" % (action, kind))
    lines = [FIRST_LINE, "Action: %s" % action, "Record id: %s" % rec_id]
    if name:
        lines.append("Name:")
        lines.extend("> " + ln for ln in str(name).splitlines() or [""])
    lines.append("Request: %s" % spec["request"])
    for f in spec["fields"]:
        lines.append("%s: %s" % (f.capitalize(), fields.get(f) if fields.get(f) else "<fill in>"))
    return "\n".join(lines)


def parse(text):
    """{action, kind, id, name, fields} from a block. Raises ActionError, naming what is wrong:
    an empty block, a first line that is not ours, an unknown action, no `Record id:`."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if not lines or not lines[0].startswith(TRIGGER):
        raise ActionError("this is not a dashboard action block: its first line must start %r" % TRIGGER)
    action = rec = None
    name_lines, fields = [], {}
    i = 1
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("Name:"):
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                name_lines.append(lines[i][1:].lstrip())
                i += 1
            continue
        key, sep, val = ln.partition(":")
        if sep:
            k = key.strip().lower()
            if k == "action":
                action = val.strip()
            elif k == "record id":
                rec = val.strip()
            elif k != "request" and k:
                fields[k] = val.strip()
        i += 1
    if not action:
        raise ActionError("the block has no `Action:` line")
    if action not in ACTIONS:
        raise ActionError("unknown action %r (known: %s)" % (action, ", ".join(sorted(ACTIONS))))
    if not rec or ":" not in rec:
        raise ActionError("the block has no `Record id:` of the form <kind>:<id> - a name is never "
                          "resolved to an id")
    kind, _sep, rid = rec.partition(":")
    if kind not in STORE_OF or not rid or not _kind_ok(action, kind):
        raise ActionError("action %s does not take a record id of kind %r" % (action, kind))
    return {"action": action, "kind": kind, "id": rid, "name": "\n".join(name_lines) or None,
            "fields": fields}


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


def plan(parsed, root):
    """("write", argv) for a one-line `record.py` write, or ("route", sentence) for an action the
    session routes itself. Raises ActionError when the id is absent from its store, or a required
    field is missing: nothing is guessed."""
    spec = ACTIONS[parsed["action"]]
    store = STORE_OF[parsed["kind"]]
    row = None
    if store is not None:
        row = next((r for r in _rows(root, store) if r.get("id") == parsed["id"]), None)
        if row is None:
            raise ActionError("no %s %r in data/%s.jsonl: refused, nothing written"
                              % (parsed["kind"], parsed["id"], store))
    if spec["argv"] is None:
        return "route", spec["request"]
    values = {"id": parsed["id"]}
    for f in spec["fields"]:
        v = parsed["fields"].get(f, "")
        if not v or v.startswith("<"):
            raise ActionError("the block has no %s: refused, nothing written" % f.capitalize())
        values[f] = v
    for var, column in (spec.get("lookup") or {}).items():
        v = (row or {}).get(column)
        if not v:
            raise ActionError("the record carries no %s: refused, nothing written" % column)
        values[var] = v
    return "write", [a.format(**values) for a in spec["argv"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="run the one write (default: print it)")
    ap.add_argument("--list", action="store_true", help="print the action table")
    args = ap.parse_args()
    if args.list:
        for a, spec in sorted(ACTIONS.items()):
            print("%-24s %-9s %s" % (a, spec["kind"] or "any", " ".join(spec["argv"] or ["(routed)"])))
        return 0
    from _root import profile_root
    root = profile_root()
    try:
        parsed = parse(sys.stdin.read())
        mode, what = plan(parsed, root)
    except ActionError as e:
        print("REFUSED: %s" % e)
        return 2
    if mode == "route":
        print("ROUTE %s %s: %s (nothing is written by this script)"
              % (parsed["action"], "%s:%s" % (parsed["kind"], parsed["id"]), what))
        return 0
    cmd = [sys.executable, os.path.join(HERE, "record.py")] + what
    if not args.apply:
        print("WOULD RUN (dry run; add --apply to run it): record.py %s" % " ".join(what))
        return 0
    r = subprocess.run(cmd)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
