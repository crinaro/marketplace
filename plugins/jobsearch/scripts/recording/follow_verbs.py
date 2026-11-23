"""follow_verbs: `record.py stop-following <person_id> [--note "<why>"] [--undo] [--dry-run]`, the one writer of the two follow-control
touch types (jobsearch 0.92.0, dev #951 and #1003; docs/design-decision-surface.md B.2, review round 2 G5, H2, H7).

A stop appends a `stop-following` touch: the person leaves "They wrote back" and "Awaiting a reply" until a later message from
them, or one the candidate sends, brings them back (`reach.follow_stop.in_force`). `--undo` appends a `resume-following` touch.
Nothing is edited or removed: the store stays append-only for these rows, so the history of a stop is the rows themselves.

Each write is one locked, validated, rollback-verified write of the touches store (`network_verbs._network_row_write`), refused
(exit 3) below the 0.92.0 profile pin, so an older engine sharing the profile never meets a row it cannot read. The generic
`set`, `set-in`, `append` and `create` refuse to write either touch type or `inbound_seen` (`owned_refusal`, called beside
`row_checks.verb_owned_refusal`); a hand edit of the file is not guarded.

Capability module of record.py (an entry point over `recording/`), reached from `mutation.preflight` beside the employment verbs,
because record.py's own dispatch may not grow (segmentation ratchet)."""

import os

import mail_client
from reach import follow_stop
from reach.person_match import find_duplicates
from recording import profile_paths as _paths
from recording.common import _Refused, _now
from recording.evidence_keys import shape_pin_refusal
from recording.ids import mint_touch_id
from recording.network_verbs import _live_person, _network_row_write
from recording.store_files import _load_or_empty, find
from validation.outbox_rules import STORE_FILE as OUTBOX_FILE, load_file

FOLLOW_OPS = ("stop-following",)
FOLLOW_USAGE = 'stop-following <person_id> [--note "<why>"] [--undo] [--dry-run] [--already-locked]'
PIN = (0, 92, 0)
MIGRATION = "m_0_92_0_decision_surface"
OPEN_OUTBOX = ("queued", "staged", "approved", "sending")       # the outbox states not yet sent, discarded or failed


def owned_refusal(op, store, before_row, after_row):
    """G5: the refusals (a list, empty when none) for a generic write of `op` to `store` that writes a follow-control touch type,
    turns a control row into another type, or changes `inbound_seen`. Those are `record.py stop-following`'s alone."""
    if store != "touches" or not isinstance(after_row, dict):
        return []
    before = before_row or {}
    out = []
    kinds = (before.get("touch_type"), after_row.get("touch_type"))
    if kinds[0] != kinds[1] and (set(kinds) & follow_stop.FOLLOW_CONTROL_TYPES):
        out.append("touch_type %s is written only by `record.py stop-following <person_id>` (`--undo` resumes); `%s` cannot "
                   "write it, and --force does not lift this" % ("/".join(sorted(follow_stop.FOLLOW_CONTROL_TYPES)), op))
    if ("inbound_seen" in before, before.get("inbound_seen")) != ("inbound_seen" in after_row, after_row.get("inbound_seen")):
        out.append("inbound_seen is written only by `record.py stop-following <person_id>`, with the stop it belongs to; `%s` "
                   "cannot change it, and --force does not lift this" % op)
    return out


def _name(row):
    return row.get("name") or row.get("id")


def plan(touches, people, messages, pid, undo, note, today, extra=()):
    """`(row, lines)`: the control row to append to `touches` and the lines to print, or `_Refused` (B.2 conditions 3 to 7). Pure.
    `extra` are lines the caller found about work still open for the person (an outbox row, a staged draft, no mailbox)."""
    if find(people, pid) is None:
        raise _Refused("person %r resolves to no people record." % pid)
    person = _live_person(people, pid)
    ids = follow_stop.ids_of(people, pid)
    own_t = [t for t in touches if t.get("person_id") in ids]
    own_m = [m for m in messages if m.get("person_id") in ids]
    if not own_t and not own_m:
        raise _Refused("nothing to stop: %s (%s) has no message and no touch on file." % (_name(person), pid))
    on, stop, reopened = follow_stop.in_force(own_t, own_m)
    if not undo and on:
        raise _Refused("you already stopped following %s (%s): %s on %s. `--undo` resumes."
                       % (_name(person), pid, stop.get("id"), stop.get("date")))
    if undo and not on:
        if stop is None:
            raise _Refused("no stop is in force for %s (%s): none was recorded, or the last one was already undone."
                           % (_name(person), pid))
        raise _Refused("no stop is in force for %s (%s): the stop %s of %s was reopened by an %s message on %s."
                       % (_name(person), pid, stop.get("id"), stop.get("date"), reopened["by"], reopened["on"]))
    row = {"id": mint_touch_id(pid, touches), "person_id": pid, "date": today,
           "touch_type": follow_stop.RESUME if undo else follow_stop.STOP, "status": "declined", "medium": "other",
           "outcome": None, "note": note}
    if undo:
        return row, ["resumed following %s (%s) on %s: they are listed again when a thread with them needs a reply or a nudge"
                     % (_name(person), pid, today)]
    row["inbound_seen"] = follow_stop.inbound_near(own_t, own_m, today)
    lines = ['stopped following %s (%s) on %s: they leave "They wrote back" and "Awaiting a reply"; a later message from them, '
             "once stored by the mail sweep or `record.py received`, brings them back" % (_name(person), pid, today)]
    if not row["inbound_seen"]:
        lines.append("  no message from them dated yesterday, today or tomorrow is stored yet, so one that a later run stores "
                     "brings them back once; stop again then if you still mean it")
    if person.get("cadence"):
        lines.append("  a cadence is still set on them, so they stay under Relationships due when it falls due")
    for p in find_duplicates(people):
        if pid in (p["a"], p["b"]):
            lines.append("  a possible duplicate record is not stopped: %s" % (p["b"] if p["a"] == pid else p["a"]))
    return row, lines + ["  " + x for x in extra]


def open_work(ids):
    """Lines naming what is still open for the person `ids` names: an outbox row not yet sent or discarded, and the H7 line when no
    mailbox is set up. Read-only; an outbox that cannot be read is said, never taken for an empty one. A draft staged in drafts.md
    with no outbox row is not looked for here: its path is the profile layout's (`_tree`, an entry point), and `sending/`, which
    reads it, cannot be imported from `recording/` without closing a cycle (G6)."""
    out = []
    try:
        rows = [r for r in load_file(os.path.join(_paths.DATA, OUTBOX_FILE))
                if r.get("person_id") in ids and r.get("state") in OPEN_OUTBOX]
        out += ["an outbox row is still open for them (%s, %s): stopping does not withdraw it" % (r.get("id"), r.get("state"))
                for r in rows]
    except (OSError, ValueError) as e:
        out.append("the outbox could not be read (%s): whether a message to them is queued is not known" % e)
    try:
        if not mail_client.configured_accounts():
            out.append("No mailbox is set up here, so record their replies with `record.py received` to bring them back.")
    except Exception:                                     # noqa: BLE001 - a registry that cannot answer is not "no mailbox"
        pass
    return out


def cmd_follow(args):
    """`record.py stop-following ...` (the module docstring). Exit 0 written (or a dry run that predicts a clean write); 1 refused or
    rolled back; 2 usage; 3 the profile is below the 0.92.0 pin."""
    if not args.rid or args.rest:
        print("usage: " + FOLLOW_USAGE)
        return 2
    refusal = shape_pin_refusal(PIN, "a stop-following row", MIGRATION)
    if refusal:
        print(refusal)
        return 3
    pid, undo, note, today = args.rid, bool(args.undo), args.note_text, _now().date().isoformat()

    def edit(rows):
        people = _load_or_empty("people")
        extra = open_work(follow_stop.ids_of(people, pid)) if not undo and find(people, pid) is not None else ()
        row, lines = plan(rows, people, _load_or_empty("messages"), pid, undo, note, today, extra)
        rows.append(row)
        return lines
    return _network_row_write(args, "stop-following", "touches", edit)

