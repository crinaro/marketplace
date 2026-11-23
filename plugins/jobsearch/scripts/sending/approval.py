"""approval: email `me` puts an approved message in the candidate's drafts (jobsearch 0.93.0, owner ruling 2026-11-23, ADR-043,
which supersedes the send half of ADR-040: "Email should just put it in drafts for you to send. Once you approve the message,
you should automatically put it in drafts.").

    queued --approve (attended)--> approved --the draft call is printed, the session makes it--> staged --a Sent copy--> sent
    queued --approve, the draft call refused (a connector with no draft tool)--> approved, drafted later by `draft`
    approved --draft (any run, attended or not)--> staged

THE PERSON ALWAYS PRESSES SEND. No verb here makes or prints a send call, and `guard_mail_send.py` denies every gmail-multi send,
reply and forward in every session state. A `me` row ends exactly where a `you` row does: `staged`, a draft in the mailbox, and
`outbox.py detect` writes `sent` when the message is found in Sent (`sending/detect.py`).

APPROVING. `approve` needs the explicit `--attended` form (`posture.py`: never inferred), because an approval is the candidate's
own choice of which messages go into their drafts: a scheduled run never approves. It moves each named queued `me` row to
`approved` (all or none) and then drafts each one: the row becomes `staged` and the printed `CALL` is the selected connector's
draft tool (`draft_call`), which the session makes at once, without asking again. Drafting never asks: gmail-multi's
`gmail_create_draft` carries no `requiresUserInteraction` flag (gmail-multi docs/deployment.md, the install-alone matrix,
"drafting unattended").

DRAFTING. `draft` turns every `approved` row (or the named ones) into a draft, in any run: it is what a scheduled run does with
an approval that has not reached the mailbox yet, and with a row a 0.91.0 or 0.92.0 engine left `approved` (an approval to send
then; a draft is strictly less, and the candidate still presses Send). A row whose draft call is refused stays `approved`, with
the reason printed.

ATTACHING (jobsearch 0.93.0, design-resume-docx.md §7.1, §7.3). A row with `attachments` is drafted through `call_for`, which
asks `sending/attachments.py` for the outcome: the file goes on gmail-multi's call and is stamped (`carried: null` until
`outbox.py attached`); a claude.ai connector's call never carries it and the ATTACH BY HAND line is printed (`carried:
false`); a file not ready keeps the row `approved` naming the one command that settles it; a file that cannot be attached is
left off, with the by-hand line and the reason. Microsoft 365's refusal names the file's path.

A row a 0.91.0 or 0.92.0 guard moved to `sending` keeps its state: send detection still looks for it in Sent, and `cancel` puts it
back to `queued`. No new row ever enters `sending`.

Capability module of `outbox.py`. Python 3.9+, standard library only."""

import json
import os

import mail_client
import mail_connectors
from sending import attachments as _attachments
from sending import modes
from sending import outbox_store as store

GMAIL_MULTI_DRAFT_TOOL = "gmail_create_draft"
UNATTENDED = "this run is unattended (no --attended): only the candidate approves a message, so nothing was approved"


class Refused(Exception):
    """A verb that cannot run as asked; the text says why and what stays as it was."""


def load_config(root):
    p = os.path.join(root, "config.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise Refused("config.json at %s cannot be read (%s: %s)" % (p, type(exc).__name__, exc))


def require_me(root):
    try:
        mode = modes.resolve(load_config(root), modes.EMAIL_SEND)
    except modes.ModeError as exc:
        raise Refused(str(exc))
    if mode != "me":
        raise Refused("%s.%s is you: jobsearch shows the text and you draft it (outbox.py stage puts it in your drafts on "
                      "request)" % (modes.KEY, modes.EMAIL_SEND))


def _jsonl(root, name):
    try:
        with open(os.path.join(root, "data", name), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []


def draft_call(root, row, path=None):
    """`(tool, args)`: the one call the session makes to put the row's text in the mailbox's drafts. `path`, the absolute
    path of the file the call carries: gmail-multi's `gmail_create_draft` gains `attachments: [path]` (0.6.0, §7.2); a
    claude.ai connector's args never carry one (§7.3, `mail_connectors.claude_ai_draft_args`); Microsoft 365's refusal
    gains the path sentence."""
    connector = mail_client.selected_connector(root)
    if connector == mail_client.GMAIL_MULTI:
        args = {"account": row["account"], "to": row["to"], "cc": row["cc"], "subject": row["subject"], "body": row["body"]}
        args = dict(args, reply_to_uid=row["reply_uid"]) if row.get("reply_uid") else args
        return GMAIL_MULTI_DRAFT_TOOL, dict(args, attachments=[path]) if path else args
    if row.get("reply_uid"):
        raise Refused("%s publishes no reply argument for its draft tool, so a reply is staged only under gmail-multi"
                      % mail_connectors.label(connector))
    tool = (mail_connectors.row(connector) or {}).get("draft_tool")
    if not tool:
        raise Refused("%s, so staging is refused there%s" % (mail_connectors.no_draft_why(connector), (
            ". " + mail_connectors.path_sentence(path)) if path and row.get("attachments") else ""))
    return tool, mail_connectors.claude_ai_draft_args(connector, row)


def call_for(root, row, probe=None):
    """`(tool, args, lines)`: `draft_call` with the row's attachment decided (design-resume-docx.md §7.1 step 4,
    `sending/attachments.py`), its item stamped in place, and the extra lines to print after the CALL. `Refused` (the
    row stays as it was: approved, or not staged) for an outcome that holds, or when no `probe` was given."""
    items = row.get("attachments") or []
    if not items:
        tool, args = draft_call(root, row)
        return tool, args, []
    if probe is None:
        raise Refused("its attachment %s is resolved only by outbox.py, which passes the gate and the Word file's "
                      "state" % items[0]["ref"])
    res = probe.resolve(items[0]["ref"])
    connector = mail_client.selected_connector(root)
    if connector != mail_client.GMAIL_MULTI and not (mail_connectors.row(connector) or {}).get("draft_tool"):
        draft_call(root, row, res.path)                     # raises Microsoft 365's refusal, naming the file
    if res.outcome == _attachments.HOLD:
        raise Refused("%s is not ready to attach: %s; run %s, then outbox.py draft %s"
                      % (items[0]["ref"], res.why, res.route, row["id"]))
    if res.outcome == _attachments.WITHOUT:
        tool, args = draft_call(root, row)
        _attachments.unstamped_without(items[0], res)
        return tool, args, [_attachments.without_line(row["id"], res)]
    if connector == mail_client.GMAIL_MULTI:
        tool, args = draft_call(root, row, res.path)
        _attachments.stamp(items[0], res)
        return tool, args, []
    tool, args = draft_call(root, row)
    _attachments.stamp(items[0], res, carried=False, why="%s's draft tool takes no attachment from this plugin; "
                       "attached by hand" % mail_connectors.label(connector))
    return tool, args, [mail_connectors.attach_by_hand_line(connector, row["id"], res.path)]


def _draft_rows(root, picked, today, probe=None):
    """Move each `approved` row of `picked` to `staged`, in place; the printed lines (one CALL each, or why it stays approved)."""
    out = []
    for row in picked:
        try:
            tool, args, notes = call_for(root, row, probe)
        except (Refused, ValueError) as exc:                # ValueError: the connector selection cannot be read
            out.append("%s stays approved, not in your drafts yet: %s" % (row["id"], exc))
            continue
        store.transition(row, "staged", staged_on=today)
        out.append("%s staged: in your drafts once this call is made; you press Send" % row["id"])
        out.append("  CALL %s %s" % (tool, json.dumps(args, ensure_ascii=False)))
        out.extend("  " + n for n in notes)
    return out


def approve(root, ids, attended, now, today, probe=None):
    """queued -> approved for each of `ids` (all or none), then each into the drafts (`_draft_rows`). Refused unattended, with mode
    `you`, or for a row that is not a queued `me` row."""
    if not attended:
        raise Refused(UNATTENDED)
    require_me(root)
    if not ids:
        raise Refused("name the rows to approve (outbox.py list --ready)")
    with store.lock(root, why="outbox.py approve"):
        rows = store.load(root)
        picked = []
        for oid in ids:
            row = store.find(rows, oid)
            if row is None or row.get("state") != "queued" or row.get("mode") != "me":
                raise Refused("%s is not a queued `me` row (%s); nothing was approved"
                              % (oid, "no such row" if row is None else row.get("state")))
            picked.append(row)
        for row in picked:
            store.transition(row, "approved", approved_at=store.now_instant(lambda: now))
        out = _draft_rows(root, picked, today, probe)
        store.save(root, rows)
    return out


def draft(root, ids, today, probe=None):
    """approved -> staged for the named rows, or every approved row when `ids` is empty. Needs no `--attended`: the candidate
    already approved each one, and a draft sends nothing."""
    with store.lock(root, why="outbox.py draft"):
        rows = store.load(root)
        if ids:
            picked = []
            for oid in ids:
                row = store.find(rows, oid)
                if row is None or row.get("state") != "approved":
                    raise Refused("%s is not approved (%s); nothing was drafted"
                                  % (oid, "no such row" if row is None else row.get("state")))
                picked.append(row)
        else:
            picked = [r for r in rows if r.get("state") == "approved"]
        if not picked:
            return ["Outbox: no approved message waits for your drafts."]
        out = _draft_rows(root, picked, today, probe)
        store.save(root, rows)
    return out


def cancel(root, oid):
    """approved, or a 0.91.0/0.92.0 `sending` row, -> queued. It goes into the drafts only after a new approval."""
    with store.lock(root, why="outbox.py cancel"):
        rows = store.load(root)
        row = store.find(rows, oid)
        if row is None or row.get("state") not in ("approved", "sending"):
            raise Refused("%s is not approved or sending (%s)" % (oid, "no such row" if row is None else row.get("state")))
        store.transition(row, "queued")
        store.save(root, rows)
    return "%s back to queued: it goes into your drafts only after a new approval (check Sent first if it was sending)" % oid


def ready_lines(root, probe=None):
    """The batch to approve: each queued `me` row with its id, person, address, subject and full text, and the file it
    attaches or why it is not ready (design-resume-docx.md §7.1 step 3; `probe` from `outbox.py`)."""
    people = {p.get("id"): p for p in _jsonl(root, "people.jsonl")}
    out = []
    for r in store.load(root):
        if r.get("state") != "queued" or r.get("mode") != "me":
            continue
        out.append("%s · to %s <%s> · \"%s\"" % (r["id"], (people.get(r["person_id"]) or {}).get("name") or r["person_id"],
                                                ", ".join(r["to"]), r["subject"]))
        if r.get("reply_uid"):
            out.append("  answers message %s on %s; gmail-multi quotes that original below this text" % (r["reply_uid"],
                                                                                                     r["account"]))
        for item in r.get("attachments") or []:
            out.append("  " + (_attachments.ready_note(probe.resolve(item["ref"])) if probe else "attaches " + item["ref"]))
        out.extend("  | " + line for line in (r.get("body") or "").splitlines())
    return out or ["Outbox: nothing queued to approve."]


def state_note(row):
    """The honest name of an in-flight state for `outbox.py list`."""
    if row.get("state") == "sending":
        return ("sending: a 0.91.0/0.92.0 send the guard passed; the outcome is not confirmed. Check Sent (outbox.py detect), "
                "or outbox.py cancel %s" % row["id"])
    if row.get("state") == "approved":
        return "approved, not in your drafts yet: outbox.py draft %s puts it there" % row["id"]
    if row.get("state") == "queued":
        return "queued: approve it in an attended run (outbox.py list --ready) and it goes into your drafts"
    return ""
