"""touched: the `touched` verb: a touch made outside the draft-and-send flow: a `touches` row and, for an email medium, the
message row that documents it, under one lock hold, propagated to the recipient's involvement and the role's next action.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import re
from recording.row_checks import _diagnostic_lines, new_problems, validate
from recording.common import _profile_mod, _validator_module
from recording.ids import mint_message_id, mint_touch_id
from recording.persons import _load_involvements, _person_name, _upsert_involvement
from recording.store_files import (
    LockError,
    _load_or_empty,
    find,
    load,
    lock_is_held,
    release_lock,
    restore,
    save_atomic,
    snapshot,
    take_lock,
)


def _propagate_touch(opp_id, person_id, date, recipient_role=None):
    """Runs INSIDE the caller's lock hold, best-effort, AFTER the write that recorded the
    touch (or the reply message) has already landed and validated clean — the same shape
    `_resolve_plan_goal`/`resolve_linked_asks_dated` use above: a failure here is loud and
    never un-lands the primary write.

    Two independent updates, each verified by its own validate-and-roll-back:

      1. Upsert the (person_id, opp_id) involvement: create it if absent (never was there to
         upsert), or set `status` to 'contacted' on an existing one. `path_type` is filled from
         the touch's own `recipient_role` via `plays.ROLE_TO_PATH` (§26.2's existing bridge,
         "it is simply never applied when a touch is recorded" per the report) only when the
         row does not already carry one — reclassifying an existing 'cold'/'hiring-context'
         path_type is the report's SECOND, separate finding and out of this dispatch's scope.

      2. If this opportunity's `next_action_owner` names the candidate, the touch just
         recorded is the action it was waiting on: clear ownership to 'me' and clear the now-
         stale `next_action_date` alongside it, in the SAME write — never re-derive a new date,
         only retire the one that named this now-completed action.

    Returns the printable lines describing what changed (possibly empty)."""
    if not opp_id or not person_id:
        return []
    lines, _outcome = _upsert_involvement(opp_id, person_id, recipient_role)

    # ---- 2. opportunity: clear ownership off the candidate --------------------------------
    owner_token = _profile_mod().owner_token()
    opps = load("opportunities")
    opp = find(opps, opp_id)
    if opp is not None and opp.get("next_action_owner") == owner_token:
        before_opp = snapshot("opportunities")
        pre_rc, _o, _e, pre_problems = validate()
        opp["next_action_owner"] = "me"
        opp["next_action_date"] = None
        save_atomic("opportunities", opps)
        rc, out, err, problems = validate()
        if rc != 0:
            added = new_problems(pre_problems, problems)
            if not (pre_rc != 0 and added == []):
                restore("opportunities", before_opp)
                print("  ⚠️ the write landed, but clearing next_action_owner broke the "
                      "store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc, out, err)))
            else:
                lines.append("  ✦ next_action_owner cleared off %s on %s (this touch was "
                             "the action it was waiting on)" % (owner_token, opp_id))
        else:
            lines.append("  ✦ next_action_owner cleared off %s on %s (this touch was the "
                         "action it was waiting on)" % (owner_token, opp_id))
    return lines


TOUCHED_USAGE = ("usage: touched [<opp_id>] --to contact:<person-id> --medium <medium> "
                 "[--on <date>] [--role <role>] [--touch-type <type>]  "
                 "(no <opp_id> = a person-anchored touch: a relationship with no role)")
# jobsearch 0.92.0 (dev #951): the two follow-control types are not outreach, so `touched` refuses them and names their one writer.
STOP_ROUTE = (". Stopping or resuming follow-up with a person is `record.py stop-following <person_id>` (`--undo` resumes), "
              "never a touch you record")


def cmd_touched(args):
    """`record.py touched [<opp_id>] --to contact:<person-id> --on <date> --medium <medium>
    [--role <role>] [--touch-type <type>]` — cell 3's own action line (design §3): a touch made
    OUTSIDE the normal draft-and-send flow (a handshake, a phone call, any medium this API does
    not draft for). Writes a row on the top-level `touches` store (ADR-031 B3 — was: appended
    to the opportunity's own `outreach[]`) and, for an EMAIL medium, the message row that
    documents it.

    ⭐ dev #686 / public #139 (rule 3) — THE `<opp_id>` IS OPTIONAL. Without one this records a
    PERSON-ANCHORED touch: `opp_id`/`channel_id` null, owned by the person alone (a legal shape
    since public #53; only this PATH was missing). Every field the validator will require is
    filled here and every up-front check runs BEFORE the lock and before any write, each
    refusal naming the field: `--to` resolves to a non-merged person, `--medium` in MEDIA,
    `--on` an ISO date, `--role` and `--touch-type` in their enums. No opportunity means no
    involvement to upsert; the output says so. `--touch-type` is valid on both forms (it is the
    only otherwise-unsettable required field). `record.py fields --file touches` lists the
    conditional requirements from the validator's own named constants.

    `--_inject-fault after-message` is a TEST-ONLY hook (never reachable except by passing the
    flag explicitly): after the message half lands, it exits before the touch half — so the
    half-written case and its repair are proven from OUTSIDE this function, by actually
    breaking it and re-running, the same discipline `migrate.py`'s own `_inject_fault` plants
    use rather than trusting the mechanism by reading the source."""
    opp_id = args.rid or None
    if args.rest:
        print(TOUCHED_USAGE)
        return 2
    if not args.to_token:
        print("⛔ REFUSED — --to contact:<person-id> is required.")
        return 1
    tm = re.match(r"^contact:(.+)$", args.to_token)
    if not tm:
        print("⛔ REFUSED — --to must be `contact:<person-id>`, got %r" % args.to_token)
        return 1
    person_id = tm.group(1)
    date = args.on_date or datetime.date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % date)
        return 1
    _vd = _validator_module()
    medium = args.medium
    if not medium or medium not in _vd.MEDIA:
        print("⛔ REFUSED — --medium must be one of %s" % ", ".join(sorted(_vd.MEDIA)))
        return 1
    if args.recipient_role is not None and args.recipient_role not in _vd.RECIPIENT_ROLES:
        print("⛔ REFUSED — --role must be one of %s" % ", ".join(sorted(_vd.RECIPIENT_ROLES)))
        return 1
    if args.touch_type is not None and args.touch_type not in _vd.TOUCH_TYPES:
        print("⛔ REFUSED — --touch-type must be one of %s%s" % (", ".join(sorted(_vd.TOUCH_TYPES)), STOP_ROUTE
                                                                  if args.touch_type in _vd.FOLLOW_CONTROL_TYPES else ""))
        return 1

    if opp_id:
        opps0 = load("opportunities")
        if find(opps0, opp_id) is None:
            print("No opportunities record with id %r." % opp_id)
            return 1
        # The join validate_data.py itself enforces on every touch naming an opp_id — checked
        # here too so a bad --to refuses BEFORE any write, not two steps later via a rollback.
        if not any(r.get("person_id") == person_id and r.get("opp_id") == opp_id
                  for r in _load_involvements()):
            print("⛔ REFUSED — person_id %r has no involvement on opportunity %r. Every touch "
                  "naming an opportunity must name a person actually involved in THIS pursuit "
                  "— add the involvement first (`record.py involve %s --opp %s`), or check "
                  "the --to id." % (person_id, opp_id, person_id, opp_id))
            return 1
    # dev #686 — the recipient must be a real, non-merged person on EITHER form. A merged id is
    # refused naming its survivor: a touch written to the absorbed row would be a touch on a
    # person nobody reads any more.
    _prow = find(_load_or_empty("people"), person_id)
    if _prow is None:
        print("⛔ REFUSED — --to names person_id %r, which resolves to no people record. A "
              "touch with no person is unfindable; create the person first "
              "(`record.py create <id> '{...}' --file people --reuse`)." % person_id)
        return 1
    if _prow.get("status") == "merged":
        print("⛔ REFUSED — --to names person_id %r, which was merged into %r. Touch the "
              "survivor: --to contact:%s" % (person_id, _prow.get("merged_into"),
                                             _prow.get("merged_into")))
        return 1

    is_email = medium.startswith("email")
    msg_id = mint_message_id(opp_id, person_id, date) if is_email else None
    to_label = _person_name(person_id) or person_id

    # ⭐ public #103 — THE FIX. `touched` used to have no --dry-run gate at all: every check
    # above (opp exists, involvement exists, medium/role valid) already ran, so this is the
    # exact point the write-shaped verbs (decide/set-in/…) stop at too. No lock is taken and
    # neither append below ever runs.
    if args.dry_run:
        preview = []
        if is_email:
            already_msg = any(m.get("id") == msg_id for m in load("messages"))
            preview.append(("message %s already recorded" % msg_id) if already_msg
                           else ("would record message %s" % msg_id))
        touches_rows = load("touches")
        already_touch = any(o.get("person_id") == person_id and o.get("opp_id") == opp_id
                            and o.get("date") == date and o.get("medium") == medium
                            and o.get("message_ref") == msg_id
                            for o in touches_rows)
        preview.append("touch already recorded" if already_touch
                       else "would record a touch on %s"
                       % (opp_id or "the person alone (no opportunity)"))
        print("touched: %s -> %s via %s on %s" % (opp_id or "(no opportunity)", person_id,
                                                  medium, date))
        print("  --dry-run: nothing written. (%s)" % "; ".join(preview))
        return 0

    if args.already_locked:
        if not lock_is_held():
            print("  REFUSED — --already-locked, but NOBODY holds the run lock.")
            print("  Take it first (runlock.py --take), or drop the flag.")
            return 1
    else:
        try:
            take_lock("record.py touched %s" % (opp_id or person_id), wait=args.wait)
        except LockError as e:
            print("  REFUSED — %s" % e)
            return 1
    try:
        if is_email:
            messages = load("messages")
            if not any(m.get("id") == msg_id for m in messages):
                # ⭐ NO validate-and-rollback dance for THIS append. §15.3 point 2 is explicit
                # that the store may be legitimately, TEMPORARILY invalid between the two
                # halves — a message with `source: 'record.py touched'` and no completing
                # touches row is EXACTLY the shape validate_data.py's own orphan check exists
                # to name, and it would fire on this half by construction, every time, even on
                # the ordinary (uninterrupted) path. Rolling back on that 'new problem' would
                # make a normal `touched` call refuse itself. The real commit point is the
                # touch write below, which DOES get the full validate-and-rollback treatment —
                # a genuine defect in the message's own shape (an unknown medium, a dangling
                # person_id) is already refused by the checks earlier in this function, before
                # the lock was even taken.
                messages.append({
                    "id": msg_id, "opp_id": opp_id, "channel_id": None,
                    "person_id": person_id, "direction": "outbound", "medium": medium,
                    "sent_on": date, "from": None, "to": to_label, "subject": None,
                    "body": "(recorded by `record.py touched` — no body captured)",
                    "source": "record.py touched", "variant": None, "answers": None,
                })
                save_atomic("messages", messages)
                print("  ✦ message %s recorded" % msg_id)
            else:
                print("  · message %s already recorded (completing the touch half)"
                     % msg_id)

            if args.inject_fault == "after-message":
                print("  ⚠️ TEST FAULT INJECTED — stopping before the touch half is "
                      "written. Re-run the SAME command to complete it.")
                return 1

        # ADR-031 B3 — the touch itself is a row on the TOP-LEVEL `touches` store now, never
        # an append to `opp["outreach"]` (which no longer exists — the retired-key guard
        # would refuse it). `mint_touch_id` mints `<person_id>-tN` the same way applications'
        # own `create auto` path mints `<opp_id>-aN`.
        touches_rows = load("touches")
        already = any(o.get("person_id") == person_id and o.get("opp_id") == opp_id
                     and o.get("date") == date and o.get("medium") == medium
                     and o.get("message_ref") == msg_id
                     for o in touches_rows)
        if already:
            print("  · touch already recorded — nothing further to do")
            return 0

        before_touches = snapshot("touches")
        pre_rc2, _, _, pre_problems2 = validate()
        new_touch_id = mint_touch_id(person_id, touches_rows)
        touches_rows.append({
            "id": new_touch_id, "person_id": person_id, "opp_id": opp_id, "channel_id": None,
            "object_person_id": None, "object_company_id": None,
            "status": "sent", "date": date, "medium": medium, "to": to_label,
            "outcome": "awaiting",
            # COMMS_CUTOVER (validate_data.py) requires touch_type/recipient_role on any row
            # dated 2026-08-02 or later — "unknown" is the enum's own explicit-unknown value,
            # never a guess at which one actually applies.
            "touch_type": args.touch_type or "unknown",
            "recipient_role": args.recipient_role or "unknown",
            "address_status": "unknown", "delivery": "unknown", "message_ref": msg_id,
        })
        save_atomic("touches", touches_rows)
        rc2, out2, err2, problems2 = validate()
        if rc2 != 0:
            added2 = new_problems(pre_problems2, problems2)
            if not (pre_rc2 != 0 and added2 == []):
                restore("touches", before_touches)
                print("  ⛔ REFUSED — the touch write broke the store; rolled back.")
                print("  " + "\n  ".join(_diagnostic_lines(rc2, out2, err2)))
                return 1
        print("  ✦ touch %s recorded on %s" % (new_touch_id, opp_id or person_id))
        # dev #479 / public #114 — propagate the just-landed touch to involvements/
        # next_action_owner/next_action_date, still inside this same lock hold.
        if not opp_id:
            print("  · no opportunity: no involvement to upsert (person-anchored touch) — "
                  "link later with `record.py involve %s --opp <opp_id>`" % person_id)
        for line in _propagate_touch(opp_id, person_id, date, recipient_role=args.recipient_role):
            print(line)
    finally:
        if not args.already_locked:
            release_lock()
    print("touched: %s -> %s via %s on %s — written atomically, validator clean"
         % (opp_id or "(no opportunity)", person_id, medium, date))
    return 0
