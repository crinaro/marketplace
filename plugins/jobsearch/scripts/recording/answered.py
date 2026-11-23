"""answered: the `answered` verb: records that the candidate replied: the outbound message whose `answers` names the inbound
message (or `contact:<id>` touch) it responds to, under one lock hold, propagated to the recipient's involvement.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import re
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.common import _validator_module
from recording.ids import mint_message_id
from recording.persons import _load_involvements, _person_name
from recording.store_files import (
    LockError,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)
from recording.touched import _propagate_touch
from reach import follow_stop as _fstop


def _reply_threads(person_id, involved, messages):
    """The threads a reply from the owner to `person_id` can answer when no `--opp`/`--channel` names one, as
    `(command target, (opp_id, channel_id))` pairs: each channel thread (a channel-only involvement, or a message anchored
    to a channel and no opportunity) and the person-only thread (dev #686: a message, or an ordinary touch, carrying
    neither). The same thread kinds `your_move.conversation_axis` opens, read from the same rows."""
    channels = list(dict.fromkeys(involved + [
        m["channel_id"] for m in messages
        if m.get("person_id") == person_id and m.get("channel_id") and not m.get("opp_id")]))
    out = [("contact:%s --channel %s" % (person_id, c), (None, c)) for c in channels]

    def unanchored(r):
        return r.get("person_id") == person_id and not r.get("opp_id") and not r.get("channel_id")
    if any(unanchored(m) for m in messages) or any(unanchored(t) for t in _fstop.ordinary(load("touches"))):
        out.append(("person:%s" % person_id, (None, None)))
    return out


def _contact_anchor(person_id, args, messages, person_only=False):
    """The `(opp_id, channel_id)` a reply to `contact:<id>` / `person:<id>` anchors to, or the exit code of a refusal it
    has printed. dev #1019 / public #278 (jobsearch 0.93.0): a reply must be recordable on EVERY thread kind the
    owed-reply logic (`your_move.conversation_axis`) lists -- an opportunity, a channel (opened by a channel-only
    involvement OR a channel-anchored message) and the person-only thread (dev #686). Before this, a target with no
    `--opp` resolved only a channel-only involvement and refused the rest, so those reply-owed rows could never be
    closed. `--opp` / `--channel` name the thread and `person:<id>` names the person-only one. With none: the person's one
    thread is used; several are refused naming each (never a guess at which one the reply answers); none anchors to the
    person (a message to a person about no role and no channel is a legal row)."""
    channel_id = getattr(args, "channel_id", None)
    if args.opp_id and channel_id:
        print("⛔ REFUSED — --opp and --channel together: a reply anchors to one thread, never both.")
        return 1
    if person_only and (args.opp_id or channel_id):
        print("⛔ REFUSED — person:%s is the person-only thread; drop --opp/--channel, or target "
              "contact:%s with them." % (person_id, person_id))
        return 1
    if args.opp_id or channel_id:
        return args.opp_id, channel_id
    if person_id not in {p.get("id") for p in load("people")}:
        print("⛔ REFUSED — %r resolves to no person in data/people.jsonl." % person_id)
        return 1
    if person_only:
        return None, None
    involved = [r["channel_id"] for r in _load_involvements()
                if r.get("person_id") == person_id and r.get("channel_id") and not r.get("opp_id")]
    threads = _reply_threads(person_id, involved, messages)
    if len(threads) > 1:
        print("⛔ REFUSED — contact:%s has %d threads with no role; name the one this reply answers:"
              % (person_id, len(threads)))
        for target, _anchor in threads:
            print("    record.py answered %s --via <medium> --on <date>" % target)
        return 1
    return threads[0][1] if threads else (None, None)


def cmd_answered(args):
    """`record.py answered <inbound-message-id | contact:<person-id>> --on <date> --via
    <medium> [--opp <opp_id>]` — cell 4's own action line (design §3/§15.3): records that the
    OWNER replied, appending the outbound message whose `answers` names the inbound it
    responds to. `target` is either a bare message id (an inbound row already in
    messages.jsonl — its own opp_id/channel_id/person_id are inherited) or `contact:<id>` — a
    touch ref, for cell 4's own 'the outreach[] row alone ... no message body in the store'
    case (a LinkedIn or pre-harvest reply with no message row to point `answers` at)."""
    target = args.rid
    if not target or args.rest:
        print("usage: answered <inbound-message-id | contact:<person-id> | person:<person-id>> --on <date> "
              "--via <medium> [--opp <opp_id> | --channel <channel_id>]")
        return 2
    date = args.on_date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % date)
        return 1
    _vd = _validator_module()
    medium = args.via_medium
    if not medium or medium not in _vd.MEDIA:
        print("⛔ REFUSED — --via must be one of %s" % ", ".join(sorted(_vd.MEDIA)))
        return 1
    # dev #479 / public #114 — `--role` is shared with `touched` (same flag, same
    # RECIPIENT_ROLES vocabulary) so `answered`'s own propagation below can fill an
    # involvement's path_type through plays.ROLE_TO_PATH too; validated the same way.
    if args.recipient_role is not None and args.recipient_role not in _vd.RECIPIENT_ROLES:
        print("⛔ REFUSED — --role must be one of %s" % ", ".join(sorted(_vd.RECIPIENT_ROLES)))
        return 1

    messages0 = load("messages")
    cm = re.match(r"^(contact|person):(.+)$", target)
    if cm:
        person_id = cm.group(2)
        anchor = _contact_anchor(person_id, args, messages0, person_only=cm.group(1) == "person")
        if isinstance(anchor, int):
            return anchor
        answers, (opp_id, channel_id) = None, anchor
    else:
        inbound = find(messages0, target)
        if inbound is None:
            print("⛔ REFUSED — %r resolves to no message in data/messages.jsonl, and is not "
                  "`contact:<person-id>` either." % target)
            return 1
        if inbound.get("direction") != "inbound":
            print("⛔ REFUSED — %r is not an inbound message (direction=%r) — 'answered' "
                  "records a REPLY to something THEY sent." % (target, inbound.get("direction")))
            return 1
        answers = inbound.get("id")
        opp_id, channel_id, person_id = (inbound.get("opp_id"), inbound.get("channel_id"),
                                         inbound.get("person_id"))

    msg_id = mint_message_id(opp_id or channel_id, person_id, date)
    if any(m.get("id") == msg_id for m in messages0):
        print("  · message %s already recorded — nothing further to do" % msg_id)
        return 0
    to_label = _person_name(person_id) or person_id or "unknown"

    # ⭐ public #103 — THE FIX. This is the worst shape on record: `answered --dry-run` used to
    # write to `messages`, which is append-only (§15.3) — the resulting row could then never
    # be removed except by hand-editing the store, which the engine's own rules forbid. Every
    # refusal check above (target resolves, medium valid, not already recorded) has already
    # run, so this is the same point the write-shaped verbs stop at.
    if args.dry_run:
        print("answered: %s -> outbound message %s (medium=%s, on=%s)"
             % (target, msg_id, medium, date))
        print("  --dry-run: nothing written.")
        return 0

    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            return 1
    else:
        try:
            take_lock("record.py answered %s" % target, wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        messages = load("messages")
        if any(m.get("id") == msg_id for m in messages):
            print("  · message %s already recorded — nothing further to do" % msg_id)
            return 0
        before = snapshot("messages")
        pre_rc, _, _, pre_problems = validate()
        messages.append({
            "id": msg_id, "opp_id": opp_id, "channel_id": channel_id, "person_id": person_id,
            "direction": "outbound", "medium": medium, "sent_on": date,
            "from": None, "to": to_label, "subject": None,
            "body": "(recorded by `record.py answered` — no body captured)",
            "source": "record.py answered", "variant": None, "answers": answers,
        })
        save_atomic("messages", messages)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("messages", before)
                print("  ⛔ REFUSED — this reply broke the store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
                return 1
        # dev #479 / public #114 — propagate this reply to involvements/next_action_owner/
        # next_action_date, still inside this same lock hold.
        for line in _propagate_touch(opp_id, person_id, date, recipient_role=args.recipient_role):
            print(line)
    finally:
        if not args.already_locked:
            release_lock()
    print("answered: %s -> outbound message %s recorded (medium=%s, on=%s) — written "
         "atomically, validator clean" % (target, msg_id, medium, date))
    return 0
