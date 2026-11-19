"""Migration 0.54.0: `m_0_54_0_touch_propagation()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.54.0"


def m_0_54_0_touch_propagation(profile, apply_it, _inject_fault=None, today=None):
    """0.54.0 — dev #479 / public #114: `record.py touched`/`answered` now propagates a
    freshly-recorded outbound touch to the recipient's `involvements` row and to the
    opportunity's `next_action_owner`/`next_action_date` (record.py's own `_propagate_touch`).
    Fixing the write path does nothing for a touch that was already recorded under the OLD,
    non-propagating path — its involvement row is still missing or stale, and its opportunity
    can still be stuck reading `next_action_owner` as the candidate's own token forever after
    the send. This is that backfill, run once per profile.

    ⭐⭐ KEYED "0.54.0" — 0.53.0 is the newest PUBLISHED jobsearch release (plugin.json at HEAD
    reads 0.53.0; `jobsearch--v0.53.0` exists in the local tag list), the same fact
    `m_0_54_0_linkedin_quota` above already verified for this same key. A profile that
    installed 0.53.0 is stamped exactly "0.53.0", and `pending_for()`'s strict `<` would never
    fire a migration keyed to it. Re-verified when 0.54.0 is actually cut.

    SAME ALGORITHM AS `record._propagate_touch`, deliberately NOT a call into it — that
    function runs under record.py's own run-lock against `record.ROOT`/`record.DATA` (resolved
    once, at import, from `_root.profile_root()`), which is exactly the wrong thing to depend
    on from a migration that is handed an explicit `profile` path and must act on THAT path
    only (a hook running from inside the profile and one running from the engine repo must
    never resolve to two different roots — trap 2). The shape is copied instead: for every
    `touches.jsonl` row with `status: 'sent'`, group by (person_id, opp_id) and take the
    NEWEST date; upsert that pair's involvement (status -> 'contacted'; `path_type` filled via
    `plays.ROLE_TO_PATH` only when absent, the same "never reclassify" restraint the write path
    keeps); then, for every opportunity with at least one such touch, if its
    `next_action_owner` still names the candidate, clear it to 'me' and clear
    `next_action_date` alongside it — the touch already on file completed the action it was
    waiting on.

    PRESERVE, THEN TRANSFORM, ALL-OR-NOTHING (the `m_0_48_0_touches` shape). The involvements
    upsert is purely additive (never discards a fact) and is written FIRST; the opportunity
    write is the one destructive step (the old `next_action_owner`/`next_action_date` values
    are overwritten) and — preserved rather than merely overwritten — each cleared opportunity
    gets a `research_log` entry naming exactly what the migration changed, appended in the
    SAME write that clears the fields, so the old values survive on the record even though the
    columns themselves move on. Both writes are validated against a throwaway shadow first
    (`_shadow_validate`); a genuinely new validation problem refuses the WHOLE migration and
    touches neither real file.

    ⭐ PENDING, NEVER A FALSE '0 done'. `_inject_fault == 'after_involvements'` (test-only,
    never reachable from the CLI) writes involvements.jsonl for real and then returns
    `(False, ...)` naming the incomplete state — proving, from OUTSIDE this function, that an
    interrupted run (a) reports PENDING rather than claiming nothing was pending, (b) has
    preserved the involvements half it already landed, and (c) a plain re-run finds only the
    remaining opportunities half still to do (the involvements half is now idempotent-clean)
    and completes it — the same discipline `m_0_48_0_touches`'s own fault hook and
    `m_0_47_0_drafts_working_set`'s `today` parameter establish for this file's other
    migrations.

    Idempotent: a profile with no `status: 'sent'` touch at all, or where every such touch's
    pair already has a 'contacted' involvement and no opportunity is still candidate-owned
    underneath one, returns `(True, "")` and writes nothing."""
    import datetime
    today = today or datetime.date.today().isoformat()

    touches_path = os.path.join(profile, "data", "touches.jsonl")
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    inv_path = os.path.join(profile, "data", "involvements.jsonl")
    if not os.path.exists(touches_path):
        return True, ""
    try:
        touches = _read_jsonl(touches_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ touches.jsonl could not be read — nothing migrated: %s" % e
    try:
        opps = _read_jsonl(opp_path) if os.path.exists(opp_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        involvements = _read_jsonl(inv_path) if os.path.exists(inv_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ involvements.jsonl could not be read — nothing migrated: %s" % e

    # The newest 'sent' touch per (person_id, opp_id) — its date feeds the research_log note,
    # its recipient_role feeds the involvement's path_type.
    latest = {}
    for t in touches:
        if t.get("status") != "sent":
            continue
        pid, oid, date = t.get("person_id"), t.get("opp_id"), t.get("date")
        if not pid or not oid or not date:
            continue
        cur = latest.get((pid, oid))
        if cur is None or str(date) > str(cur[0]):
            latest[(pid, oid)] = (date, t.get("recipient_role"))
    if not latest:
        return True, ""

    import plays as _plays

    involvements = [dict(r) for r in involvements]
    inv_index = {(r.get("person_id"), r.get("opp_id")): r
                for r in involvements if r.get("opp_id")}
    created, upserted = [], []
    for (pid, oid), (_date, role) in latest.items():
        inv = inv_index.get((pid, oid))
        mapped = _plays.ROLE_TO_PATH.get(role) if role else None
        if inv is None:
            inv = {"person_id": pid, "opp_id": oid, "channel_id": None, "path_type": mapped,
                  "role": None, "status": "contacted", "note": None}
            involvements.append(inv)
            inv_index[(pid, oid)] = inv
            created.append("%s/%s" % (pid, oid))
        else:
            changed = False
            if inv.get("status") != "contacted":
                inv["status"] = "contacted"
                changed = True
            if mapped and inv.get("path_type") is None:
                inv["path_type"] = mapped
                changed = True
            if changed:
                upserted.append("%s/%s" % (pid, oid))

    import profile as _profile_mod
    owner_token = _profile_mod.owner_token()
    opps = [dict(o) for o in opps]
    opps_by_id = {o.get("id"): o for o in opps if o.get("id")}
    cleared = []
    for oid in {oid for (_pid, oid) in latest}:
        o = opps_by_id.get(oid)
        if o is None or o.get("next_action_owner") != owner_token:
            continue
        old_owner, old_date = o.get("next_action_owner"), o.get("next_action_date")
        o["next_action_owner"] = "me"
        o["next_action_date"] = None
        log = list(o.get("research_log") or [])
        log.append({"date": today,
                    "note": ("0.54.0 migration (dev #479): next_action_owner cleared from %r "
                             "to 'me' (next_action_date was %r) — a touch already on file had "
                             "already completed the action this was waiting on."
                             % (old_owner, old_date))})
        o["research_log"] = log
        cleared.append(oid)

    if not created and not upserted and not cleared:
        return True, ""

    if not apply_it:
        summary = ("%d involvement(s) to create, %d to upsert, %d opportunity(ies) to clear "
                  "off %s" % (len(created), len(upserted), len(cleared), owner_token))
        return True, "  would migrate (0.54.0) touch propagation backfill: %s" % summary

    if _inject_fault == "after_involvements":
        # TEST-ONLY — see docstring. Lands involvements.jsonl for real, then stops before
        # opportunities.jsonl — the PRESERVE half survives; the TRANSFORM half does not
        # happen at all (never a partial write of it either).
        import _atomic
        _atomic.write_jsonl(inv_path, involvements)
        return False, ("  ⏳ 0.54.0 PENDING — TEST FAULT INJECTED: involvements.jsonl written "
                       "(%d created, %d upserted); opportunities.jsonl NOT YET written (%d "
                       "still to clear). Re-run to complete."
                       % (len(created), len(upserted), len(cleared)))

    overrides = {"involvements.jsonl": involvements, "opportunities.jsonl": opps}
    rc, problems, new = _shadow_validate(profile, overrides)
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.54.0 REFUSED — the migrated shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)
    pre_existing_note = ""
    if rc != 0:
        pre_existing_note = ("  ⚠️ %d pre-existing problem(s) stand, unrelated to this "
                             "migration: %s"
                             % (len(problems or []), "; ".join((problems or [])[:4])))

    import _atomic
    _atomic.write_jsonl(inv_path, involvements)
    _atomic.write_jsonl(opp_path, opps)
    summary = ("%d involvement(s) created, %d upserted, %d opportunity(ies) cleared off %s"
              % (len(created), len(upserted), len(cleared), owner_token))
    msg = "  ✅ touch propagation backfill (0.54.0) — %s" % summary
    return True, (msg + "\n" + pre_existing_note if pre_existing_note else msg)
