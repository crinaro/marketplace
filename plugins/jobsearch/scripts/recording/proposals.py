"""proposals: the `proposal` and `proposal-status` verbs: the candidate's own record of a proposal to a prospective
client of a fractional, interim, advisory or contract engagement.

Capability module of record.py (an entry point over `recording/`)."""

import json
import re
from recording.common import _Refused, _now, _validator_module
from recording.network_verbs import _network_row_write, _parse_on
from recording.store_files import _load_or_empty, find


PROPOSAL_USAGE = {
    "proposal": "proposal <opp_id> [--scope \"<text>\"] [--rate <amount>/<hour|day|month|year|project>/<CURRENCY>] [--on YYYY-MM-DD] "
                "[--note \"<text>\"] [--dry-run] [--already-locked]",
    "proposal-status": "proposal-status <proposal_id> sent|accepted|declined|withdrawn|expired [--on YYYY-MM-DD] "
                       "[--dry-run] [--already-locked]",
    "suggest": "suggest --store companies|plans|people --action set|create --target-id <id> --values '<json object>' "
               "--ask \"<the question and the reason>\" [--dry-run] [--already-locked]",
    "confirm": "confirm <ask_id> [--set field=value ...] [--dry-run] [--already-locked]",
    "decline": "decline <ask_id> [--why \"<text>\"] [--dry-run] [--already-locked]",
}
_RATE_RE = re.compile(r"^(\d+(?:\.\d+)?)/([a-z]+)/([A-Za-z]{3})$")


def _deep(rows):
    return json.loads(json.dumps(rows))


def _parse_rate(text):
    """`{amount, per, currency}` for `1500/day/USD`, or `_Refused`. The amount is a positive number (a whole one stays an int), `per`
    one of `validate_data.RATE_PER`, the currency three letters (upper-cased). Nothing is converted or defaulted."""
    _vd = _validator_module()
    m = _RATE_RE.match((text or "").strip())
    if not m:
        raise _Refused("--rate %r is not <amount>/<per>/<CURRENCY>, e.g. 1500/day/USD (per is one of %s)."
                       % (text, ", ".join(_vd.RATE_PER)))
    amount = float(m.group(1))
    if amount <= 0:
        raise _Refused("--rate %r: the amount must be more than zero." % text)
    if m.group(2) not in _vd.RATE_PER:
        raise _Refused("--rate %r: %r is not one of %s." % (text, m.group(2), ", ".join(_vd.RATE_PER)))
    return {"amount": int(amount) if amount == int(amount) else amount, "per": m.group(2), "currency": m.group(3).upper()}


def cmd_proposal(args):
    """`record.py proposal <opp_id> [--scope T] [--rate 1500/day/USD] [--on D] [--note T]`: start a proposal to the prospective client of
    a non-employee engagement (design-network-first.md 6). The row is minted `<opp_id>-pN`, `status: drafting`, `status_on` (`--on`,
    default today), `date` null: what the proposal says is the candidate's, and nothing is inferred. The opportunity's own
    `engagement_type` must be one of `config_keys.ENGAGEMENT_NON_EMPLOYEE` (a full-time role's path is `applications`). Several
    proposals per engagement are legal. `conceptual_agreement` and `doc_ref` are set afterwards with the generic `set`. Exit 0 written;
    1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + PROPOSAL_USAGE["proposal"]
    if not args.rid or args.rest:
        print(usage)
        return 2
    oid = args.rid
    try:
        import config_keys as _ck
        opp = find(_load_or_empty("opportunities"), oid)
        if opp is None:
            raise _Refused("%r resolves to no opportunities record." % oid)
        if opp.get("engagement_type") not in _ck.ENGAGEMENT_NON_EMPLOYEE:
            raise _Refused("%s has engagement_type %r: a proposal belongs to a %s engagement (a full-time role's path is "
                           "`applications`). If this is one, say so first: `record.py set %s engagement_type <type>`."
                           % (oid, opp.get("engagement_type"), "/".join(_ck.ENGAGEMENT_NON_EMPLOYEE), oid))
        rate = _parse_rate(args.rate_arg) if args.rate_arg is not None else None
        scope = None
        if args.scope_text is not None:
            scope = args.scope_text.strip()
            if not scope:
                raise _Refused("--scope is empty: leave it off, or say what the proposal covers.")
        on = _parse_on(args.on_date, default=_now().date())
        note = None
        if args.note_text is not None:
            note = args.note_text.strip() or None
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        n = 1
        for r in rows:
            m = re.match(r"^%s-p(\d+)$" % re.escape(oid), str(r.get("id")))
            if m:
                n = max(n, int(m.group(1)) + 1)
        pid = "%s-p%d" % (oid, n)
        row = {"id": pid, "opp_id": oid, "conceptual_agreement": None, "scope": scope, "rate": rate, "status": "drafting",
               "status_on": on.isoformat(), "date": None, "doc_ref": None}
        if note:
            row["note"] = note
        rows.append(row)
        return ["proposal: %s drafting for %s%s%s -- `record.py proposal-status %s sent` when it goes out"
                % (pid, oid, (" (%s)" % scope) if scope else "",
                   (", rate %s/%s %s" % (rate["amount"], rate["per"], rate["currency"])) if rate else "", pid)]
    return _network_row_write(args, "proposal", "proposals", edit)


def cmd_proposal_status(args):
    """`record.py proposal-status <proposal_id> sent|accepted|declined|withdrawn|expired [--on D]`: the ONE writer of a proposal's
    `status`, `status_on` and `date` (design-network-first.md 6). `sent` is only from `drafting` and writes `date` (the day it went
    out); `accepted`, `declined` and `expired` need a `date` already and are not dated before it; `withdrawn` may be a draft never
    sent. The opportunity's own `status` is untouched: an accepted proposal does not end the opportunity (the candidate decides that).
    `--on` defaults to today and is never after it. Exit 0 written; 1 refused; 2 usage; 3 the profile is not ready."""
    usage = "usage: " + PROPOSAL_USAGE["proposal-status"]
    if not args.rid or len(args.rest) != 1:
        print(usage)
        return 2
    pid, status = args.rid, args.rest[0]
    _vd = _validator_module()
    try:
        if status not in _vd.PROPOSAL_STATUS or status == "drafting":
            raise _Refused("%r is not a status to move a proposal to: one of %s.\n%s"
                           % (status, ", ".join(s for s in _vd.PROPOSAL_STATUS if s != "drafting"), usage))
        on = _parse_on(args.on_date, default=_now().date())
    except _Refused as e:
        print("⛔ REFUSED — %s" % e)
        return 1

    def edit(rows):
        row = find(rows, pid)
        if row is None:
            raise _Refused("%r resolves to no proposals record." % pid)
        was = row.get("status")
        if status == "sent":
            if was != "drafting":
                raise _Refused("%s is %s: only a drafting proposal is marked sent." % (pid, was))
            row["date"] = on.isoformat()
        elif status in _vd.PROPOSAL_NEEDS_SENT_ON:
            if not row.get("date"):
                raise _Refused("%s was never marked sent, so it cannot be %s: `record.py proposal-status %s sent --on <the day it "
                               "went out>` first." % (pid, status, pid))
            if on.isoformat() < row["date"]:
                raise _Refused("--on %s is before the day the proposal went out (%s)." % (on.isoformat(), row["date"]))
        if was == status and row.get("status_on") == on.isoformat():
            return ["proposal-status: %s is already %s on %s" % (pid, status, on.isoformat())]
        row["status"], row["status_on"] = status, on.isoformat()
        return ["proposal-status: %s %s -> %s (status_on %s%s)"
                % (pid, was, status, on.isoformat(), (", date %s" % row["date"]) if row.get("date") else "")]
    return _network_row_write(args, "proposal-status", "proposals", edit)
