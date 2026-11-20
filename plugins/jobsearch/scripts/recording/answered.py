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
        print("usage: answered <inbound-message-id | contact:<person-id>> --on <date> "
              "--via <medium> [--opp <opp_id>]")
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
    cm = re.match(r"^contact:(.+)$", target)
    if cm:
        person_id = cm.group(1)
        answers, opp_id, channel_id = None, args.opp_id, None
        if not opp_id:
            for row in _load_involvements():
                if (row.get("person_id") == person_id and row.get("channel_id")
                        and not row.get("opp_id")):
                    channel_id = row["channel_id"]
                    break
            if not channel_id:
                print("⛔ REFUSED — contact:%s names no opportunity (--opp) and resolves to "
                      "no channel-only involvement either — a message must anchor to "
                      "SOMETHING." % person_id)
                return 1
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
