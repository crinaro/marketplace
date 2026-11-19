"""Migration 0.48.0: `m_0_48_0_application_endings_restamp()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.48.0"


def m_0_48_0_application_endings_restamp(profile, apply_it):
    """0.48.0 — public #94, the repair half. The 0.47.0 migration's own count was wrong
    (`your_move.ended_because()`'s precedence bug, fixed at the source above: a `passed`
    verdict now wins over the `stage == closed` catch-all), and its remainder was N printed
    `record.py application-status <app_id> ...` commands — a per-row hand-off the 'never
    mechanical work' rule (CLAUDE.md) never allowed in the first place, and worse, most of
    those ids were OPPORTUNITY ids on rows with no application at all, so the printed verb
    could never even apply.

    This recomputes `unrecorded` with the FIXED precedence and replaces the printed hand-off
    with ONE queryable `asks.jsonl` row (`kind: system`) — never N printed commands. Re-run
    safe: the row's id is stable (`system-application-endings`), so a second run REPLACES it
    with the fresh count rather than appending a second one, and removes it outright once the
    corrected count reaches zero.

    `resolves_when` is deliberately left UNSET — `validate_data.ASK_RESOLVES_WHEN` only ever
    means "one recorded action on ONE `opp_id` answers this" (application/outreach), and this
    ask spans however many opportunities the corrected count still names; setting it here
    would be exactly the 'resolves_when that can never fire' shape `validate_data.py` refuses
    for good reason. The ask stays on the manual review path (its own `ask` text names every
    id), and a future run of this SAME migration (impossible — it is one-shot per profile) or
    a later periodic pass is the mechanism that shrinks the count as the owner acts; for now
    it is a correct, queryable count where an unbounded printed list stood before.
    """
    apps_path = os.path.join(profile, "data", "applications.jsonl")
    opps_path = os.path.join(profile, "data", "opportunities.jsonl")
    asks_path = os.path.join(profile, "data", "asks.jsonl")
    if not os.path.exists(opps_path):
        return True, ""
    try:
        opps = _read_jsonl(opps_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        apps = _read_jsonl(apps_path) if os.path.exists(apps_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ applications.jsonl could not be read — nothing migrated: %s" % e
    try:
        asks = _read_jsonl(asks_path) if os.path.exists(asks_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ asks.jsonl could not be read — nothing migrated: %s" % e

    import your_move as _ym
    import applications as _apps_mod
    by_opp = _apps_mod.group_by_opp(apps)
    unrecorded_ids = sorted(o.get("id") for o in opps
                            if _ym.ended_because(o, by_opp.get(o.get("id"), [])) == "unrecorded")

    ASK_ID = "system-application-endings"
    existing = [a for a in asks if a.get("id") == ASK_ID]

    if not unrecorded_ids:
        if not existing:
            return True, ""
        if not apply_it:
            return True, "  would remove system ask %r (0.48.0) — the corrected count is 0" % ASK_ID
        new_asks = [a for a in asks if a.get("id") != ASK_ID]
        rc, problems, new = _shadow_validate(profile, {"asks.jsonl": new_asks})
        if new is None or new:
            detail = "; ".join((new if new else (problems or []))[:8]) or (
                "validator exited %d with no problem list — it crashed" % rc)
            return False, ("  ⚠️ 0.48.0 restamp REFUSED — removing %r introduces a new "
                          "validation problem, so NOTHING was written: %s" % (ASK_ID, detail))
        import _atomic
        _atomic.write_jsonl(asks_path, new_asks)
        return True, ("  ✅ application endings restamp (0.48.0) — removed %r, corrected "
                     "count is 0 (public #94)" % ASK_ID)

    if not apply_it:
        return True, ("  would write system ask %r (0.48.0): %d ended pursuit(s) carry no "
                      "recorded ending under the CORRECTED precedence (was over-counted by "
                      "public #94's bug)" % (ASK_ID, len(unrecorded_ids)))

    import datetime
    today = datetime.date.today().isoformat()
    ask_row = {
        "id": ASK_ID, "kind": "system",
        "title": "%d ended pursuit(s) carry no recorded ending" % len(unrecorded_ids),
        "ask": ("Each of these opportunities ended (closed/passed) with nothing recorded "
                "saying why — `record.py application-status <app_id> rejected|withdrawn|"
                "closed` where an application exists, or a plain read for the rest (public "
                "#94's over-count is fixed; this is the corrected remainder). ids: %s"
                % ", ".join(unrecorded_ids[:40])
                + (" … (%d more)" % (len(unrecorded_ids) - 40) if len(unrecorded_ids) > 40
                   else "")),
        "created": today, "act_by": None, "opp_id": None, "channel_id": None,
        "resolves_when": None, "resolved_on": None, "resolution": None,
        "trigger_kind": None, "trigger_ref": None, "note": None,
    }
    new_asks = [a for a in asks if a.get("id") != ASK_ID] + [ask_row]
    rc, problems, new = _shadow_validate(profile, {"asks.jsonl": new_asks})
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.48.0 restamp REFUSED — the system ask introduces a new "
                       "validation problem, so NOTHING was written: %s" % detail)
    import _atomic
    _atomic.write_jsonl(asks_path, new_asks)
    verb = "replaced" if existing else "wrote"
    return True, ("  ✅ application endings restamp (0.48.0) — %s system ask %r: %d ended "
                 "pursuit(s), corrected count (public #94)"
                 % (verb, ASK_ID, len(unrecorded_ids)))
