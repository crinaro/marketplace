"""received: the `received` verb: an inbound message recorded through `messages.append_message`, anchored to a role,
a channel or a person.

Capability module of record.py (an entry point over `recording/`)."""

import hashlib
import re
from recording.common import _validator_module
from recording.messages import append_message
from recording.store_files import _load_or_empty, find, load


_TIMESTAMP_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$")


def cmd_received(args):
    """`record.py received --opp <opp_id> | --channel <channel_id> | --person <person_id>
    --from <addr> [--to <addr>] --on <ISO ts> --subject <text> --body-file <path>
    --source <token> [--medium email] [--resolves <app_id> --resolved-by
    req-id|url|company-single] [--already-locked]`

    design-inbound-resolution.md §2 — the ONE public writer for an INBOUND message
    (ADR-029). `id` is minted from `--source` (`in-<sha1(source)[:12]>`), deterministic, so a
    second write of the same source is idempotent by construction (see `append_message`).
    dev #686: with `--person` alone (no --opp, no --channel) the message anchors on its person
    and the id also folds in `--on`, so two inbounds in one thread are two messages.
    `--body-file`, never `--body`: an ATS body is thousands of characters and argv is the
    wrong place."""
    if args.rest:
        print("usage: received --opp <opp_id> | --channel <channel_id> | --person <id> "
              "--from <addr> [--to <addr>] --on <ISO ts> --subject <text> "
              "--body-file <path> --source <token> [--medium email] "
              "[--resolves <app_id> --resolved-by req-id|url|company-single]")
        return 2
    if not args.source_token:
        print("⛔ REFUSED — --source is required — a body with no provenance cannot be "
              "re-verified against the mailbox.")
        return 1
    if not args.on_date or not _TIMESTAMP_ARG_RE.match(args.on_date):
        print("⛔ REFUSED — --on must be an ISO date or 'YYYY-MM-DD HH:MM[:SS]' timestamp, "
              "got %r" % args.on_date)
        return 1
    if args.opp_id and args.channel_id:
        print("⛔ REFUSED — pass --opp OR --channel, never both.")
        return 1
    if not args.opp_id and not args.channel_id and not args.resolves:
        # dev #686 / public #139 (rule 1a) — a resolving --person is the THIRD anchor: a
        # message to/from a person about no role and no channel belongs to the relationship.
        if not (args.person_id_arg and find(_load_or_empty("people"), args.person_id_arg)):
            print("⛔ REFUSED — needs an anchor: --opp <opp_id>, --channel <channel_id>, or "
                  "--person <person_id> naming an existing people record (at least one, "
                  "unless --resolves derives one). A message anchored to nothing is "
                  "unfindable.%s"
                  % ((" (--person %r resolves to no people record.)" % args.person_id_arg)
                     if args.person_id_arg else ""))
            return 1
    if not args.body_file:
        print("⛔ REFUSED — --body-file is required — an ATS body belongs in a file, never "
              "argv.")
        return 1
    try:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    except OSError as e:
        print("⛔ REFUSED — could not read --body-file %r: %s" % (args.body_file, e))
        return 1
    # `email-reply` is the default: MEDIA is an OUTREACH taxonomy (validate_data.py's own
    # comment) and bare 'email' is legal only for direction='third-party' — an inbound ATS/
    # employer message is a reply-channel event, not a third party, so it needs a real MEDIA
    # value. Checked BEFORE the write (the touched/answered convention) rather than left to the
    # validator's rollback, so a bad --medium refuses immediately with the legal set named.
    medium = args.medium or "email-reply"
    if medium not in _validator_module().MEDIA:
        print("⛔ REFUSED — --medium must be one of %s"
              % ", ".join(sorted(_validator_module().MEDIA)))
        return 1
    if bool(args.resolves) != bool(args.resolved_by):
        print("⛔ REFUSED — --resolves and --resolved-by are required TOGETHER, or not at "
              "all (ADR-030: the tier that matched is recorded).")
        return 1

    opp_id = args.opp_id
    if args.resolves:
        app = find(load("applications"), args.resolves)
        if app is None:
            print("⛔ REFUSED — --resolves %r does not resolve to any applications row."
                  % args.resolves)
            return 1
        derived_opp = app.get("opp_id")
        if opp_id and opp_id != derived_opp:
            print("⛔ REFUSED — --opp %r conflicts with --resolves %r's own opp_id %r — a "
                  "message cannot point at one role while resolving another's application."
                  % (opp_id, args.resolves, derived_opp))
            return 1
        opp_id = derived_opp
        if args.channel_id:
            print("⛔ REFUSED — --resolves names an application (always role-anchored); "
                  "--channel is refused alongside it.")
            return 1

    # dev #686 / public #139 (P3) — a PERSON-ANCHORED inbound's id is minted from the source AND
    # the message timestamp. Two inbounds in one LinkedIn thread share one `--source` (the
    # thread URL), so a source-only mint gave both the same id and the second was silently
    # swallowed as "already recorded" — the person axis would then be dated by the older
    # message. Role- and channel-anchored inbounds keep the source-only mint, which is what
    # `reconcile.py --harvest` mints for the same mailbox uid.
    if not opp_id and not args.channel_id:
        mid_seed = "%s|%s" % (args.source_token, args.on_date)
    else:
        mid_seed = args.source_token
    mid = "in-%s" % hashlib.sha1(mid_seed.encode("utf-8")).hexdigest()[:12]
    row = {
        "id": mid, "opp_id": opp_id, "channel_id": args.channel_id,
        "person_id": args.person_id_arg, "direction": "inbound",
        "medium": medium, "sent_on": args.on_date,
        "from": args.from_addr, "to": args.to_token, "subject": args.subject, "body": body,
        "source": args.source_token, "variant": None, "answers": None,
        "resolves": args.resolves, "resolved_by": args.resolved_by,
    }

    # ⭐ public #103's own shape, closed for THIS verb too — `received` is its own
    # early-return branch in main(), reached and returned from before main()'s shared
    # dry-run gate ever runs, exactly like `touched`/`answered` were. Every refusal check
    # above has already run, so this is the same point those two verbs stop at.
    if args.dry_run:
        already = any(m.get("id") == mid for m in load("messages"))
        print("received: %s -> inbound message %s (source=%s)"
             % (opp_id or args.channel_id, mid, args.source_token))
        print("  --dry-run: nothing written. (%s)"
             % ("message already recorded" if already
                else "would record message %s" % mid))
        return 0

    rc, msg = append_message(row, already_locked=args.already_locked, wait=args.wait)
    print(msg)
    if rc == 0:
        print("received: %s -> inbound message %s recorded (source=%s)"
             % (opp_id or args.channel_id, mid, args.source_token))
    return rc
