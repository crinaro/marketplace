"""Migration 0.36.0: `m_0_36_0_message_answers()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl, _rewrite_jsonl

VERSION = "0.36.0"


def m_0_36_0_message_answers(profile, apply_it):
    """0.36.0 — the reply relation becomes a KEY: `messages[].answers` (dev/audit 2026-09-02,
    Class B: public #41/#36/#34). Backfilled ONLY where attribution is unambiguous.

    For every inbound message with no `answers`: the candidate answered messages are the
    OUTBOUND ones to the same contact_id, anchored to the same opportunity or channel, dated
    STRICTLY before it (validate_data.date_part — a same-day pair cannot be ordered from dates
    and is left for a human, exactly as reconcile.py now reports it as ambiguous rather than
    asserting). The latest such message is the one answered; a tie on that latest date is
    ambiguous too and is skipped. Skipped rows are named in the report so the coordinator
    can link them once, as data. History stays valid: the key is optional.

    ⭐ AND THE OUTREACH ROW LEARNS WHAT THE LINK PROVES (G9's second half, 2026-09-03). The
    validator shipped beside this migration flags an outreach row that is still `awaiting`
    while `messages[].answers` names its `message_ref` — so a link written here, on its own,
    CREATED that finding on every profile it touched: the migration manufactured the one
    contradiction that survived it, and left the owner to disposition by hand what the
    engine had just proved. This closes it, and only where nothing is guessed:

    * the link is never same-day: an answered message is dated STRICTLY before its reply
      (and a tie is skipped), so the attribution Class B made ambiguous on purpose is
      never the basis. A hand-written `answers` that already exists is honoured the same
      way — it is data the owner recorded, not an inference.
    * `responded_on` ← the reply's own `sent_on` — RELOCATED from a row that exists to the
      row that names it (preserve, then transform); never set where one already stands.
    * `outcome` ← `replied` only where the row reads `awaiting` or carries none: the
      vocabulary's neutral fact ("a reply exists"), which the linked message proves. A
      finer outcome (`declined`, `meeting-booked`, `accepted`) is a reading of the reply's
      CONTENT and stays the human's — a row already carrying one is left alone. What the
      candidate should DO about the reply is `next_action`, and nothing here touches it.
    Idempotent: a row with `responded_on` is never revisited."""
    import validate_data as _vd
    path = os.path.join(profile, "data", "messages.jsonl")
    if not os.path.exists(path):
        return True, ""
    try:
        rows = _read_jsonl(path)
    except Exception as e:
        return False, "  ⚠️ messages.jsonl could not be read, so no answers were linked: %s" % e
    linked, ambiguous = [], []
    outbound = [m for m in rows if m.get("direction") == "outbound" and m.get("id")]
    for m in rows:
        if m.get("direction") != "inbound" or m.get("answers") is not None:
            continue
        cid, d = m.get("contact_id"), _vd.date_part(m.get("sent_on"))
        if not cid or not d:
            continue
        cands = [o for o in outbound
                 if o.get("contact_id") == cid and _vd.date_part(o.get("sent_on"))
                 and _vd.date_part(o["sent_on"]) < d
                 and (o.get("opp_id") == m.get("opp_id") if m.get("opp_id")
                      else o.get("channel_id") == m.get("channel_id"))]
        if not cands:
            continue
        latest = max(_vd.date_part(o["sent_on"]) for o in cands)
        tied = [o for o in cands if _vd.date_part(o["sent_on"]) == latest]
        if len(tied) > 1:
            ambiguous.append("%s (two outbound on %s)" % (m.get("id"), latest))
            continue
        m["answers"] = tied[0]["id"]
        linked.append("%s→%s" % (m.get("id"), tied[0]["id"]))

    # ---- the outreach row: responded_on (relocated) and the neutral outcome (proved) ----
    # EVERY inbound carrying `answers` counts — the links made just above and any the owner
    # recorded by hand. The earliest reply to a message is when it was responded to.
    replied_when = {}
    for m in rows:
        if m.get("direction") == "inbound" and m.get("answers") and m.get("sent_on"):
            prev = replied_when.get(m["answers"])
            if prev is None or _vd.precedes(m["sent_on"], prev):
                replied_when[m["answers"]] = m["sent_on"]
    opps_path = os.path.join(profile, "data", "opportunities.jsonl")
    opps, answered, stamped = [], [], []
    if replied_when and os.path.exists(opps_path):
        try:
            opps = _read_jsonl(opps_path)
        except Exception as e:
            return False, ("  ⚠️ opportunities.jsonl could not be read, so no outreach row "
                           "learned of its reply: %s" % e)
        for r in opps:
            for i, o in enumerate(r.get("outreach") or []):
                when = replied_when.get(o.get("message_ref"))
                if not when or o.get("responded_on"):
                    continue
                if o.get("date") and _vd.precedes(when, o.get("date")):
                    continue            # the validator names this one; never write it
                o["responded_on"] = when
                where = "%s outreach[%d]" % (r.get("id", "?"), i)
                stamped.append(where)
                if o.get("outcome") in (None, "awaiting"):
                    o["outcome"] = "replied"
                    answered.append(where)

    if not (linked or ambiguous or stamped):
        return True, ""
    bits = []
    if linked:
        bits.append("%d inbound message(s) linked to the message they answer: %s"
                    % (len(linked), "; ".join(linked)[:300]))
    if stamped:
        bits.append("responded_on set from the linked reply on %d outreach row(s)%s: %s"
                    % (len(stamped),
                       (" (outcome awaiting→replied on %d)" % len(answered)) if answered else "",
                       "; ".join(stamped)[:300]))
    if ambiguous:
        bits.append("⚠️ %d left unlinked — ambiguous from dates alone, decide once and "
                    "record `answers`: %s" % (len(ambiguous), "; ".join(ambiguous)[:300]))
    if not apply_it:
        return True, "  would link (0.36.0): " + " · ".join(bits)
    if linked:
        _rewrite_jsonl(path, rows)
    if stamped:
        _rewrite_jsonl(opps_path, opps)
    return True, "  ✅ messages.jsonl (0.36.0): " + " · ".join(bits)
