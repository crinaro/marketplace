"""Migration 0.24.0: `m_0_24_0_blocked_until()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.24.0"


def m_0_24_0_blocked_until(profile, apply_it):
    """0.24.0 (part 1 of 2) — Your Move role state gets its own field (GitHub issue #79).

    The "needs you" queue used to select rows by ownership alone, so a role future-dated
    weeks out and one genuinely overdue rendered identically. `your_move.py` now groups by a
    `blocked_until` field; this backfills it from what the profile already has.

    Scans LIVE, candidate-owned opportunities whose `next_action` prose carries a hold phrase
    (`precondition.HOLD_RE`, imported — never restated, same rule m_0_18_0 follows for
    drafts). Exactly one of the record's OWN `outreach[]` rows with `outcome: awaiting` names
    a single plausible contact: writes the real join, `contact:<id>
    outcome:accepted|replied`. Zero or more than one candidate is ambiguous: writes the
    literal `unresolved`, which `your_move.py` treats as its own loud callout, never
    "needs you", until a human structures the real join. No hold phrase: no field written.

    ⭐ PRESERVE, THEN TRANSFORM. `next_action`'s prose is never deleted or rewritten — it
    stays the human-readable evidence; only the FACT that the role is blocked moves into the
    queryable store (the general rule `precondition.py` documents). Additive and idempotent:
    a row already carrying ANY `blocked_until` (from an earlier run, or hand-authored) is
    skipped, so a second run finds nothing left to do.
    """
    import precondition as _pre
    import your_move as _ym
    import profile as _profile
    path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(path):
        return True, ""
    try:
        owner = _profile.owner_token()
    except Exception:
        owner = None
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception as e:
        return False, ("  ⚠️ opportunities.jsonl could not be read, so no blocked_until was "
                       "backfilled: %s" % e)

    changed, marked = 0, []
    for r in rows:
        if "blocked_until" in r:
            continue
        if r.get("next_action_owner") != owner or r.get("status") not in _ym.LIVE_OPP_STATUSES:
            continue
        text = str(r.get("next_action") or "")
        if not _pre.HOLD_RE.search(text):
            continue
        awaiting = sorted({o.get("contact_id") for o in (r.get("outreach") or [])
                           if o.get("contact_id") and o.get("outcome") == "awaiting"})
        if len(awaiting) == 1:
            r["blocked_until"] = "contact:%s outcome:accepted|replied" % awaiting[0]
            marked.append("%s → contact:%s" % (r.get("id", "?"), awaiting[0]))
        else:
            r["blocked_until"] = "unresolved"
            marked.append("%s → unresolved (%s)"
                          % (r.get("id", "?"), "no awaiting touch" if not awaiting
                             else "%d candidate contacts" % len(awaiting)))
        changed += 1

    if not changed:
        return True, ""
    if not apply_it:
        return True, ("  would backfill blocked_until on %d opportunity(ies) whose "
                      "next_action carries a hold phrase" % changed)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written pipeline file
    return True, ("  ✅ opportunities.jsonl — blocked_until backfilled on %d role(s): %s"
                  % (changed, "; ".join(marked)[:300]))
