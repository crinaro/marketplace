"""The dashboard action BLOCK's grammar: the action table, and the one writer and the one reader of a block
(dev #915; dashboard-redesign D3, design 6.2 and 6.3). Pure: it reads nothing but the plugin manifest's
version, at call time. `dashboard_actions.py` (the entry point the coordinator skill runs) re-exports every
name here and adds the store checks and the writes.

THE SINGLE FORM (`block`, unchanged since 0.88.0):

    Record this from my dashboard (copied from the dashboard; send it to /jobsearch:coordinator).
    Action: target-later
    Record id: company:c-0412
    Name:
    > Example Widgets Ltd
    Request: Ask me about this company next week.
    Date: 2026-11-03                        <- only an action that needs a value adds a named line

`Record id:` is the ONLY identity. `Name:` is for the reader: it is quoted (`> `) because it is the candidate's
own data, and the route never resolves a name to an id.

THE LIST FORM. A page button copies one block for many records. Python writes every character as three
fragments that the page's one script only joins with newlines: `head(action)` (the group button's
`data-head`), `record_line(rec_id, name)` (each tick box's `data-line`) and `tail(more)` (the button's
`data-tail`). `block_many()` is the same three joined by `compose()`, which is the script's join, so there is
one writer:

    Record this from my dashboard (copied from the dashboard; send it to /jobsearch:coordinator).
    Action: work-through
    Request: Go through these with me one at a time, and record what I decide.
    Needs: jobsearch <the version in .claude-plugin/plugin.json, read at call time> or later
    Records:
    - ["commit:cm-0031", "Coffee with Person-088"]
    - ["draft:Re: Note to Person-017#2", "Re: Note to Person-017"]
    Not on the page: 12 more in this group.

A record line is `- ` and a JSON array of two strings (the action record id, the reader's label), so a draft key
holding a colon, a space or `#2` is unambiguous. An action whose spec has required `fields` is single-record
only: `head`, `block_many` and `parse` refuse it as a list. `Needs:` is there for an OLDER coordinator, which
refuses the list form as `unknown action` or `no Record id`: the model reads the line and says to update.
"""

import json
import os

MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        ".claude-plugin", "plugin.json")
FIRST_LINE = ("Record this from my dashboard (copied from the dashboard; "
              "send it to /jobsearch:coordinator).")
TRIGGER = "Record this from my dashboard"
MORE_PREFIX = "Not on the page:"

# record kind -> the store whose row must exist. `send` names a staged draft by reference, not a stored row.
STORE_OF = {"company": "companies", "commit": "commitments", "touch": "touches", "ask": "asks",
            "proposal": "proposals", "opp": "opportunities", "person": "people", "chan": "channels",
            "send": None}
# Kinds `work-through` joins with NO store: a draft or cover letter is named by its page key (its title plus an
# ordinal that moves when an earlier same-titled draft goes). This leaf cannot check it (it must not import the
# drafts reader); the coordinator skill re-resolves it by key, then by the quoted label, and asks when neither
# names exactly one (design 6.2).
JOIN_ONLY = ("draft", "cover")
ANY_KIND = "*"          # an ACTIONS kind: every kind in STORE_OF, plus JOIN_ONLY

# `record.py` verbs another builder of the SAME release adds (B-comp, dev #915 C7: `company-later` writes
# `later_on`, `company-kind` writes `kind`). They are listed so a test can name them, never so a verb may
# go missing: once both land `test_dashboard_actions` requires every verb in `record.OPS`.
B_COMP_VERBS = ("company-later", "company-kind")

# action id -> {kind, argv (a template over {id} and each field; None = routed to a session step, not a
# one-line write), fields (named lines the action needs), request (plain words, no command), request_many
# (the list form's words, when they differ), already (optional: the (field, value) the write sets)}.
#
# `already`: a record whose store row already holds that value is reported ALREADY and nothing is written
# (design 6.3). The UNDETERMINED of 6.3, measured 2026-11-18 and pinned by
# test_dashboard_actions.TestRepeatedCompanyStatus: `record.py company-status` run again on the SAME day writes
# nothing, but on a LATER day it moves `status_on` to that day. Without this test a re-paste would rewrite the
# day the candidate decided.
ACTIONS = {
    # C7: targets to review
    # dev #960: a yes needs the candidate's motivation, which `record.py company-status ... active-target`
    # refuses to do without, so `target-yes` is a ROUTE (the skill asks 1-5 for each company) and the write is
    # `target-active`, one record at a time with its Motivation line. Nothing is defaulted.
    "target-yes": {"kind": "company", "argv": None, "fields": (),
                   "request": "Make this company an active target. Ask me how motivated I am (1-5) first.",
                   "request_many": "Make these companies active targets. Ask me how motivated I am (1-5) "
                                   "about each one first."},
    "target-active": {"kind": "company", "fields": ("motivation",), "already": ("status", "active-target"),
                      "argv": ["company-status", "{id}", "active-target", "--motivation", "{motivation}"],
                      "request": "Make this company an active target, with the motivation below."},
    "target-no": {"kind": "company", "argv": ["company-status", "{id}", "passed"], "fields": (),
                  "already": ("status", "passed"), "request": "I am not interested in this company.",
                  "request_many": "I am not interested in these companies."},
    "target-later": {"kind": "company", "argv": ["company-later", "{id}"], "fields": (),
                     "request": "Ask me about this company next week.",
                     "request_many": "Ask me about these companies next week."},
    "company-kind-employer": {"kind": "company", "argv": ["company-kind", "{id}", "employer"], "fields": (),
                              "already": ("kind", "employer"),
                              "request": "This is an employer, not a staffing firm or aggregator.",
                              "request_many": "These are employers, not staffing firms or aggregators."},
    "company-kind-staffing": {"kind": "company", "argv": ["company-kind", "{id}", "staffing"], "fields": (),
                              "already": ("kind", "staffing"),
                              "request": "This is a staffing firm. Stop listing it as a target.",
                              "request_many": "These are staffing firms. Stop listing them as targets."},
    "company-kind-aggregator": {"kind": "company", "argv": ["company-kind", "{id}", "aggregator"],
                                "fields": (), "already": ("kind", "aggregator"),
                                "request": "This is an aggregator. Stop listing it as a target.",
                                "request_many": "These are aggregators. Stop listing them as targets."},
    # the Network to-record rows (funnel_report.network_rows), the argv each row's verb held, moved verbatim
    "chat-held": {"kind": "commit", "argv": ["attended", "{id}", "held"], "fields": (),
                  "already": ("attendance", "held"), "request": "This chat happened. Record it as held."},
    "chat-no-show": {"kind": "commit", "argv": ["attended", "{id}", "no-show"], "fields": (),
                     "already": ("attendance", "no-show"),
                     "request": "This chat did not happen. Record it as a no-show."},
    "booking-chat": {"kind": "touch", "argv": ["chat", "{person}", "--on", "{date}", "--touch", "{id}"],
                     "fields": ("date",), "lookup": {"person": "person_id"},
                     "request": "Record the chat I had on the date below, for this booking."},
    "suggestion-yes": {"kind": "ask", "argv": ["confirm", "{id}"], "fields": (),
                       "already": ("resolution", "confirmed"), "request": "Yes, confirm this suggestion."},
    "suggestion-no": {"kind": "ask", "argv": ["decline", "{id}"], "fields": (),
                      "already": ("resolution", "declined"), "request": "No, decline this suggestion."},
    "send-observed": {"kind": "send", "argv": None, "fields": (),
                      "request": "I sent this message. Ask me which draft it was and record the send, "
                                 "or tell me to delete the draft."},
    "proposal-sent": {"kind": "proposal", "argv": ["proposal-status", "{id}", "sent"], "fields": (),
                      "already": ("status", "sent"), "request": "I sent this proposal. Record it as sent."},
    # C6: the communication plan's rows, routed to the drafting step (no one-line write)
    "draft-message": {"kind": None, "argv": None, "fields": (),
                      "request": "Draft the next message for this, and show it to me before anything is sent.",
                      "request_many": "Draft the next message for each of these, and show me each draft before "
                                      "anything is sent."},
    # dashboard-redesign (design 6.2): the generic action of a list button. A route, like draft-message: the
    # coordinator skill shows each record in turn, asks the question it needs and records the answer through the
    # single-record route. It takes every kind, a draft and a cover letter included.
    "work-through": {"kind": ANY_KIND, "argv": None, "fields": (),
                     "request": "Go through this with me, and record what I decide.",
                     "request_many": "Go through these with me one at a time, and record what I decide."},
}


class ActionError(ValueError):
    """A block that cannot be applied. Loud on purpose: the route runs nothing."""


def kinds_of(action):
    """The record kinds `action` takes: its one kind; every STORE_OF kind for kind None; and for ANY_KIND those
    plus JOIN_ONLY."""
    want = ACTIONS[action]["kind"]
    if want == ANY_KIND:
        return set(STORE_OF) | set(JOIN_ONLY)
    return set(STORE_OF) if want is None else {want}


def kind_ok(action, kind):
    return kind in kinds_of(action)


def spec_of(action):
    """The action's spec, or ActionError naming the known actions."""
    if action not in ACTIONS:
        raise ActionError("unknown action %r (known: %s)" % (action, ", ".join(sorted(ACTIONS))))
    return ACTIONS[action]


def _single_only(action, spec):
    if spec["fields"]:
        raise ActionError("action %s needs %s for each record: it is single-record only, never a list"
                          % (action, ", ".join(spec["fields"])))


def block(action, rec_id, name=None, **fields):
    """The paste-ready single-form block for `action` on `rec_id` (`<kind>:<id>`). `name` is the reader's label,
    quoted. Raises ActionError for an unknown action or a kind the action does not take."""
    spec = spec_of(action)
    kind = str(rec_id).split(":", 1)[0] if ":" in str(rec_id) else ""
    if not kind_ok(action, kind):
        raise ActionError("action %s does not take a record id of kind %r" % (action, kind))
    lines = [FIRST_LINE, "Action: %s" % action, "Record id: %s" % rec_id]
    if name:
        lines.append("Name:")
        lines.extend("> " + ln for ln in str(name).splitlines() or [""])
    lines.append("Request: %s" % spec["request"])
    for f in spec["fields"]:
        lines.append("%s: %s" % (f.capitalize(), fields.get(f) if fields.get(f) else "<fill in>"))
    return "\n".join(lines)


def plugin_version():
    """The jobsearch version this engine is, read from its own manifest at call time (never hard-coded, so the
    `Needs:` line moves with every release). Raises ActionError when the manifest cannot be read."""
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            v = json.load(fh).get("version")
    except (OSError, ValueError) as e:
        raise ActionError("cannot read the plugin version from %s (%s)" % (MANIFEST, e))
    if not isinstance(v, str) or not v:
        raise ActionError("%s carries no version" % MANIFEST)
    return v


def head(action):
    """The list form's first lines, ending `Records:` (the button's `data-head`). Refuses an unknown action and
    one with required `fields`: such an action is single-record only and never offered as a batch."""
    spec = spec_of(action)
    _single_only(action, spec)
    return "\n".join([FIRST_LINE, "Action: %s" % action,
                      "Request: %s" % spec.get("request_many", spec["request"]),
                      "Needs: jobsearch %s or later" % plugin_version(), "Records:"])


def record_line(rec_id, name):
    """One record line (a tick box's `data-line`): `- ` and a JSON array of two strings, the action record id and
    the reader's label. JSON quoting keeps a colon, a space, `#2` or a newline in either unambiguous."""
    return "- " + json.dumps([str(rec_id), "" if name is None else str(name)], ensure_ascii=False)


def tail(more):
    """`Not on the page: N more in this group.` (the button's `data-tail`), or "" when `more` is 0."""
    more = int(more)
    if more < 0:
        raise ActionError("a negative count of rows not on the page: %d" % more)
    return "%s %d more in this group." % (MORE_PREFIX, more) if more else ""


def compose(head_text, lines, tail_text):
    """The page script's join, in Python: the head, each line, and the tail when it is not empty, with newlines.
    `block_many` uses it, and a test composes a page's attribute values through it."""
    return "\n".join([head_text] + list(lines) + ([tail_text] if tail_text else []))


def block_many(action, rec_ids, names, more=0):
    """The list-form block: `head(action)`, one `record_line` per record, `tail(more)`, joined (one writer).
    Refuses an action with required fields, an empty or mismatched list, and a kind the action does not take."""
    rec_ids, names = list(rec_ids), list(names)
    if not rec_ids or len(rec_ids) != len(names):
        raise ActionError("a list block needs one or more records, each with a name (%d ids, %d names)"
                          % (len(rec_ids), len(names)))
    h = head(action)
    for rec in rec_ids:
        kind = str(rec).partition(":")[0] if ":" in str(rec) else ""
        if not kind_ok(action, kind):
            raise ActionError("action %s does not take a record id of kind %r" % (action, kind))
    return compose(h, [record_line(r, n) for r, n in zip(rec_ids, names)], tail(more))


def _record(ln, n):
    """(rec_id, label) from a record line, or ActionError naming line `n` (1-based)."""
    body = ln.strip()
    try:
        if not body.startswith("- "):
            raise ValueError
        val = json.loads(body[2:])
    except ValueError:
        val = None
    if not (isinstance(val, list) and len(val) == 2 and all(isinstance(x, str) for x in val)):
        raise ActionError("line %d is not a record line; nothing is applied" % n)
    return val[0], val[1]


def parse(text):
    """{action, kind, id, name, fields, records, more, form} from a block. `records` is [(rec_id, label)]: one for
    the single form (`Record id:`), every record line for the list form (`Records:`, where `kind` and `id` are
    None). Raises ActionError, naming what is wrong: an empty block, a first line that is not ours, an unknown
    action, no record, a line in `Records:` that is not a record line, both forms at once."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    if not lines or not lines[0].startswith(TRIGGER):
        raise ActionError("this is not a dashboard action block: its first line must start %r" % TRIGGER)
    action = rec = None
    records, more = None, 0
    name_lines, fields = [], {}
    i = 1
    while i < len(lines):
        ln = lines[i]
        if records is not None and ln.strip() and not ln.startswith(MORE_PREFIX):
            records.append(_record(ln, i + 1))
            i += 1
            continue
        if ln.startswith("Name:"):
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                name_lines.append(lines[i][1:].lstrip())
                i += 1
            continue
        if ln.startswith(MORE_PREFIX):
            count = ln[len(MORE_PREFIX):].strip().split(" ", 1)[0]
            if not count.isdigit():
                raise ActionError("line %d does not say how many records are not on the page" % (i + 1))
            more = int(count)
            i += 1
            continue
        key, sep, val = ln.partition(":")
        if sep:
            k = key.strip().lower()
            if k == "action":
                action = val.strip()
            elif k == "record id":
                rec = val.strip()
            elif k == "records" and not val.strip():
                records = []
            elif k not in ("request", "needs") and k:
                fields[k] = val.strip()
        i += 1
    if not action:
        raise ActionError("the block has no `Action:` line")
    spec = spec_of(action)
    if records is not None:
        if rec:
            raise ActionError("the block has both `Record id:` and `Records:`; nothing is applied")
        if not records:
            raise ActionError("the block names no record")
        _single_only(action, spec)
        return {"action": action, "kind": None, "id": None, "name": None, "fields": fields,
                "records": records, "more": more, "form": "list"}
    if not rec or ":" not in rec:
        raise ActionError("the block has no `Record id:` of the form <kind>:<id> - a name is never "
                          "resolved to an id")
    kind, _sep, rid = rec.partition(":")
    if not rid or not kind_ok(action, kind):
        raise ActionError("action %s does not take a record id of kind %r" % (action, kind))
    name = "\n".join(name_lines) or None
    return {"action": action, "kind": kind, "id": rid, "name": name, "fields": fields,
            "records": [(rec, name or "")], "more": 0, "form": "single"}
