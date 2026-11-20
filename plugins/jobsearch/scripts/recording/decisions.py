"""decisions: the decision verbs on the shared write: `decide` (verdict and decision in one write),
`application-status` (status and status_on together) and `networking-closed` (refused on unverified silence), plus
the advisory note when a written row names the candidate but is on no Your Move list.

Capability module of record.py (an entry point over `recording/`)."""

import datetime
import re
from recording import profile_paths as _paths
from recording.common import Mutation, _validator_module
from recording.store_files import load


def _your_move_visibility_note(rec):
    """dev #142 (public #24) — close the SILENCE at the moment the record is made. The
    reporter's row (user-owned, backlog, future date) was invisible on the decisions
    surface with no warning at creation; the membership fix handles that combination, and
    this covers the residue: any row that names the owner as next_action_owner but lands in
    NO Your Move group (a parked backlog row, `in-motion`, a closed status). Advisory only —
    it never blocks a write, and it fails open, because a broken profile must not make the
    write API refuse."""
    try:
        import your_move as _ym
        import profile as _profile
        reason = _ym.invisible_reason(rec or {}, _profile.owner_token())
    except Exception:
        return
    if reason:
        print("  ℹ️ NOT ON YOUR MOVE — this row names you as next_action_owner, but %s."
              % reason)
        print("  (dev #142: a decision recorded invisibly looks handled and is not.)")


def decide_verdict(args):
    """`decide <opp_id> pursue|pass|park`: the verdict, checked before anything is imported or loaded (moved out of
    record.py main). Returns the stored verdict, or the exit code of a refusal it has printed."""
    # design-states-and-views.md §3a — writes `verdict` + `decision{}` ATOMICALLY, in the
    # SAME write: a verdict with no recorded suggestion (or a diverging one with no reason)
    # is the exact gap this verb closes.
    if len(args.rest) != 1:
        print("usage: decide <opp_id> pursue|pass|park [--why-kind K --why \"...\"]")
        return 2
    _verdict_alias = {"park": "parked"}
    new_verdict = _verdict_alias.get(args.rest[0], args.rest[0])
    if new_verdict not in ("pursue", "pass", "parked"):
        print("⛔ REFUSED — verdict must be one of pursue, pass, park (parked) — 'undecided' "
              "is the state before a decision, never something you decide TO.")
        return 1
    return new_verdict


def decide_mutation(args, rec, new_verdict, _ym, _profile_mod):
    """decide: `verdict` and `decision{}` in ONE write (moved out of record.py main). `_ym` and `_profile_mod` are
    record.py's `your_move` and `profile` modules. Returns a Mutation, or the exit code of a refusal it has printed."""
    _companies = {c.get("id"): c for c in load("companies")}
    _company = _companies.get(rec.get("company_id"))
    _cfg = _profile_mod.config()
    try:
        suggested, _missing = _ym.triage_suggestion(rec, _cfg, company=_company,
                                                    fit=rec.get("fit"))
    except Exception as e:                              # noqa: BLE001 — comp screen can
        suggested, _missing = None, "screen-error:%s" % type(e).__name__   # raise on bad data
    diverges = suggested is not None and suggested != new_verdict
    if diverges and not (args.why_kind and (args.why or "").strip()):
        print("⛔ REFUSED — the engine's own suggestion today is %r; your decision (%r) "
              "diverges. Pass --why-kind <%s> and --why \"...\" so the override is "
              "auditable later (design §3a)."
              % (suggested, new_verdict, "|".join(sorted(_validator_module().DECISION_REASON_KINDS))))
        return 1
    if args.why_kind and args.why_kind not in _validator_module().DECISION_REASON_KINDS:
        print("⛔ REFUSED — --why-kind must be one of %s"
              % ", ".join(sorted(_validator_module().DECISION_REASON_KINDS)))
        return 1
    decision_obj = {"on": datetime.date.today().isoformat(), "suggested": suggested,
                    "reason_kind": args.why_kind, "reason": args.why}
    desc = "decide verdict=%s (engine suggested %s)" % (new_verdict, suggested)

    def apply(r):
        r["verdict"] = new_verdict
        r["decision"] = decision_obj
        # ⭐ dev #722 / public #156 (jobsearch 0.69.0, §5): a decided pass on a BACKLOG role is
        # terminal in the SAME write -- `status: passed`, `stage: closed` (the validator
        # requires passed at closed), the way back kept in `passed_from` so a later
        # `decide pursue|park` restores it. Before this, `verdict: pass` left the row
        # `status: backlog`: excluded but not terminal, so the rest of the engine still saw a
        # live backlog role. A pass on any other status (a live pursuit) is unchanged and out of
        # scope; a `passed` row with no `passed_from` (passed some other way) is not guessed at.
        if new_verdict == "pass" and r.get("status") == "backlog":
            r["passed_from"] = {"status": "backlog", "stage": r.get("stage")}
            r["status"], r["stage"] = "passed", "closed"
        elif (new_verdict in ("pursue", "parked") and r.get("status") == "passed"
                and isinstance(r.get("passed_from"), dict)):
            back = r.pop("passed_from")
            r["status"], r["stage"] = back.get("status"), back.get("stage")
    return Mutation(desc, apply)


def application_status_mutation(args, rec):
    """`application-status <app_id> <status> [--on D] [--note T]` (moved out of record.py main). Returns a
    Mutation, or the exit code of a refusal it has printed."""
    # §3c — `status` + `status_on` in ONE transaction. `closed` presupposes a submission
    # (what was never sent is `withdrawn`, never `closed`) — refused below `submitted`.
    if len(args.rest) != 1:
        print("usage: application-status <app_id> <status> [--on <date>]")
        return 2
    new_status = args.rest[0]
    if new_status not in _validator_module().APPLICATION_STATUS:
        print("⛔ REFUSED — status must be one of %s"
              % ", ".join(sorted(_validator_module().APPLICATION_STATUS)))
        return 1
    current = rec.get("status")
    if new_status == "closed" and current in ("not-started", "started", None):
        print("⛔ REFUSED — 'closed' presupposes a submission; this application's status "
              "is %r. What was never sent is 'withdrawn', not 'closed' (§3c)." % current)
        return 1
    if args.on_date is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.on_date):
        print("⛔ REFUSED — --on must be an ISO date (YYYY-MM-DD), got %r" % args.on_date)
        return 1
    on_date = args.on_date or datetime.date.today().isoformat()
    desc = "application-status %s -> %s (status_on=%s)" % (current, new_status, on_date)
    if args.note_text:
        desc += " · note: %s" % args.note_text[:60]

    def apply(r, _note=args.note_text):
        r["status"] = new_status
        r["status_on"] = on_date
        # design-inbound-resolution.md §2 — `--note` APPENDS to the existing `note`, never
        # overwrites it: an owner's hand note (or an earlier sweep's own evidence line)
        # must survive a later status write, not be silently replaced by it.
        if _note:
            r["note"] = ("%s | %s" % (r["note"], _note)) if r.get("note") else _note
    return Mutation(desc, apply)


def networking_closed_check(args):
    """`networking-closed <opp_id> [--i-checked D]`: the argument checks, made before anything is imported (moved
    out of record.py main). Returns the exit code of a refusal it has printed, else None."""
    # §3b/§15.1 — refuses on UNVERIFIED silence unless the owner says they looked personally.
    if len(args.rest) != 0:
        print("usage: networking-closed <opp_id> [--i-checked <date>]")
        return 2
    if args.i_checked is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.i_checked):
        print("⛔ REFUSED — --i-checked must be an ISO date (YYYY-MM-DD)")
        return 1


def networking_closed_mutation(args, _ym):
    """networking-closed: refused on UNVERIFIED silence unless `--i-checked` (moved out of record.py main). `_ym` is
    record.py's `your_move`. Returns a Mutation, or the exit code of a refusal it has printed."""
    today = datetime.date.today().isoformat()
    conv_axis, _newest = _ym.opportunity_conversation_axis(_paths.ROOT, args.rid, today=today)
    if conv_axis == "silence-unverified" and not args.i_checked:
        print("⛔ REFUSED — silence on this pursuit is UNVERIFIED (no mailbox coverage "
              "confirms nobody wrote back). Pass --i-checked <date> to assert you looked "
              "yourself (§15.1) — or 'you are the sensor' if no mailbox is configured.")
        return 1
    closed_on = args.i_checked or today
    desc = "networking-closed on %s (conversation axis at write time: %s)" % (closed_on,
                                                                              conv_axis)

    def apply(r):
        r["networking_closed_on"] = closed_on
    return Mutation(desc, apply)
