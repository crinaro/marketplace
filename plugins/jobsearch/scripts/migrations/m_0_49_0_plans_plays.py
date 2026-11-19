"""Migration 0.49.0: `m_0_49_0_plans_plays()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.49.0"


# Frozen, historical copies — the SHAPE `play_stage` used before B4 retired it, kept here only
# so this migration can print a demotion line comparing a hand-set position to the derived
# one (design §23's own risk mitigation). Never read by anything else; validate_data.py no
# longer defines PLAY_SEQUENCE (design §19 — retired).
_OLD_PLAY_SEQUENCE = ("needs-application", "applied", "needs-recruiter-contact",
                     "verify-req-live", "identify-recruiter", "reach-insider",
                     "contact-recruiter", "awaiting-reply")
# A rough old-stage -> new-step mapping, ordinal only, for the demotion comparison — never
# exact (the two vocabularies do not correspond 1:1), and never written back onto a record.
_OLD_TO_NEW_ROUGH = {
    "needs-application": "apply", "applied": "apply",
    "needs-recruiter-contact": "identify-recruiter", "verify-req-live": "verify-open",
    "identify-recruiter": "identify-recruiter", "reach-insider": "reach-insider",
    "contact-recruiter": "contact-recruiter", "awaiting-reply": "contact-recruiter",
}
_NEW_STEP_ORDER = ("apply", "identify-insider", "reach-insider", "identify-recruiter",
                  "verify-open", "contact-recruiter")


def m_0_49_0_plans_plays(profile, apply_it, _inject_fault=None, today=None):
    """0.49.0 — B4 of ADR-031's connected-entities design: the owner's strategy becomes data.
    `plans`/`plays` become real, top-level stores; `opportunities.plan_id` becomes mandatory
    on every non-terminal pursuit; `play_stage`/`next_action` are retired (design §19, §22).

    PRESERVE, THEN TRANSFORM, ALL-OR-NOTHING — the same shape every prior connected-entities
    stage's own migration uses. In memory, in order:

      1. Adopt `referral-first` into `data/plays.jsonl`, stamped.
      2. Seed `default-plan` (subject_kind=search, subject_id=default, outcomes=[role],
         play_id=referral-first, play_confirmed=FALSE — design §26.1(d): an unconfirmed play
         acts on nothing outward until the owner looks).
      3. `opportunities.plan_id = default-plan` on EVERY row (terminal ones too — history
         needs attribution); `plan_assigned_on` = migration day.
      4. `next_action` text -> `note` (prefixed `[next_action, retired B4]`), key dropped.
         `play_stage` dropped; a row whose hand-set position was LATER than the position the
         stores now derive prints a demotion line naming the gap and the command to close it —
         the migration's REPORT, never a refusal (design §22 step 4, §23's risk mitigation).
      5. `touches.plan_id = default-plan` (only touches anchored to an opportunity — a
         network touch has no opp to derive a plan from, design §21); `play_step` by
         unambiguous touch_type (`referral-ask` -> `reach-insider`), else the literal
         `unresolved` marker, counted and excluded from any future step funnel.
      6. Validate against a shadow copy; write atomically only if clean.

    Idempotent: a profile whose `opportunities.jsonl` already carries `plan_id` on every row
    (and no `plays.jsonl`/`plans.jsonl` exist yet only on a genuinely fresh, never-migrated
    profile) is treated as done. `_inject_fault="drop_required_field"` corrupts one freshly
    built plan row (drops its `status`) in the SHADOW copy only, to prove the all-or-nothing
    property from outside this function (the m_0_48_0_touches precedent).

    `today` is test-only (never passed by the MIGRATIONS runner, which calls every migration
    with exactly `(profile, apply_it=...)` — see TestMessyMigrationChain, which runs this
    function unmodified alongside every other migration and gets the real date, same as
    before this parameter existed): `pattern_reconciled_on` and every row's
    `plan_assigned_on` are stamped `today` when given, so the golden-output test
    (`TestB4MigrationGoldenOutput`) can pin it to the date the committed `post-b4` fixture was
    generated on, the same seam `m_0_47_0_drafts_working_set` already uses for the identical
    reason — a byte-for-byte comparison against a committed golden file must never depend on
    which day the SUITE happens to run; real runs always take the actual date."""
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    touches_path = os.path.join(profile, "data", "touches.jsonl")
    if not os.path.exists(opp_path):
        return True, ""
    try:
        opps = _read_jsonl(opp_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        touches = _read_jsonl(touches_path) if os.path.exists(touches_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ touches.jsonl could not be read — nothing migrated: %s" % e

    already_done = opps and all("plan_id" in o for o in opps)
    if already_done:
        return True, ""

    import plays as _plays_mod
    import datetime as _datetime

    patterns = _plays_mod.load_patterns()
    referral_first = patterns.get("referral-first")
    if referral_first is None:
        return False, ("  ⚠️ 0.49.0 REFUSED — the shipped pattern 'referral-first' is missing "
                       "from plugins/jobsearch/plays/; nothing migrated.")

    today_iso = today or _datetime.date.today().isoformat()
    play_row = {
        "id": "referral-first", "pattern": "referral-first",
        "pattern_sha": _plays_mod.pattern_sha(referral_first),
        "pattern_reconciled_on": today_iso,
        "params": referral_first.get("params") or {},
        "steps": referral_first.get("steps") or [], "goal": referral_first.get("goal"),
        "status": "active", "note": None,
    }
    plan_row = {
        "id": "default-plan", "subject_kind": "search", "subject_id": "default",
        "outcomes": ["role"], "goal": None, "approach": None, "cadence": None,
        "status": "active", "play_id": "referral-first", "play_confirmed": False,
        "resolves_when": None, "resolved_on": None, "resolution": None, "targets": None,
        "note": None,
    }

    # ⭐ Neither store is ever hand-authored by a migration for anything but a FRESH id —
    # a profile that already carries plans.jsonl/plays.jsonl (a rerun, or an owner who has
    # already added a plan by hand) keeps every existing row untouched; this only ADDS the
    # two seeds when they are not already present.
    plans_path = os.path.join(profile, "data", "plans.jsonl")
    plays_path = os.path.join(profile, "data", "plays.jsonl")
    try:
        existing_plans = _read_jsonl(plans_path) if os.path.exists(plans_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ plans.jsonl could not be read — nothing migrated: %s" % e
    try:
        existing_plays = _read_jsonl(plays_path) if os.path.exists(plays_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ plays.jsonl could not be read — nothing migrated: %s" % e
    new_plans = list(existing_plans)
    if not any(p.get("id") == "default-plan" for p in new_plans):
        new_plans.append(plan_row)
    new_plays = list(existing_plays)
    if not any(p.get("id") == "referral-first" for p in new_plays):
        new_plays.append(play_row)

    new_opps, demotions, na_relocated = [], [], 0
    for o in opps:
        o = dict(o)
        if not o.get("plan_id"):
            o["plan_id"] = "default-plan"
            o["plan_assigned_on"] = today_iso
        old_play_stage = o.pop("play_stage", None)
        na = o.pop("next_action", None)
        if na and str(na).strip():
            prefixed = "[next_action, retired B4] %s" % str(na).strip()
            existing_note = (o.get("note") or "").strip()
            o["note"] = ("%s\n%s" % (existing_note, prefixed)) if existing_note else prefixed
            na_relocated += 1
        new_opps.append((o, old_play_stage))

    # `touches.plan_id`/`play_step` — built from the (already plan_id-assigned) opportunities
    # above, so the class-fallback `done:<step>` reading (design §26.1(a)) resolves correctly
    # even though most touches get `play_step: unresolved`.
    opp_by_id = {o.get("id"): o for o, _old in new_opps}
    new_touches, unresolved_step_count = [], 0
    for t in touches:
        t = dict(t)
        oid = t.get("opp_id")
        if oid and oid in opp_by_id:
            t.setdefault("plan_id", opp_by_id[oid].get("plan_id"))
            if not t.get("play_step"):
                if t.get("touch_type") == "referral-ask":
                    t["play_step"] = "reach-insider"
                else:
                    t["play_step"] = "unresolved"
                    unresolved_step_count += 1
        new_touches.append(t)

    # Demotion report (design §22 step 4 / §23) — computed AFTER plan_id/touches are built,
    # by asking the play engine itself what it derives for each row, so the comparison is
    # against the real mechanism a future run will use, not a guess made inside this function.
    final_opps = [o for o, _old in new_opps]
    for o, old_play_stage in new_opps:
        if not old_play_stage or old_play_stage == "unresolved":
            continue
        old_target = _OLD_TO_NEW_ROUGH.get(old_play_stage)
        if old_target not in _NEW_STEP_ORDER:
            continue
        old_ordinal = _NEW_STEP_ORDER.index(old_target)
        t_by_opp = {}
        for t in new_touches:
            if t.get("opp_id"):
                t_by_opp.setdefault(t["opp_id"], []).append(t)
        a_by_opp = {}
        try:
            apps = _read_jsonl(os.path.join(profile, "data", "applications.jsonl"))
        except Exception:                                            # noqa: BLE001
            apps = []
        for a in apps:
            if a.get("opp_id"):
                a_by_opp.setdefault(a["opp_id"], []).append(a)

        class _ShadowGraph:
            def __init__(self, opps_, touches_):
                self.stores = {"opportunities": opps_, "involvements": [], "touches": touches_}
                self.by_id = {"opportunities": {x.get("id"): x for x in opps_}}

        class _ShadowCtx:
            pass

        shadow_ctx = _ShadowCtx()
        shadow_ctx.opps = final_opps
        shadow_ctx.opps_by_id = opp_by_id
        shadow_ctx.apps_by_opp = a_by_opp
        shadow_ctx.touches_by_opp = t_by_opp
        shadow_ctx.involvements_by_opp = {}
        shadow_ctx.plans_by_id = {p.get("id"): p for p in new_plans}
        shadow_ctx.plays_by_id = {p.get("id"): p for p in new_plays}
        ns = _plays_mod.next_step(plan_row, play_row, o, shadow_ctx, today_iso)
        derived_ordinal = None
        if ns.kind == "step" and ns.step in _NEW_STEP_ORDER:
            derived_ordinal = _NEW_STEP_ORDER.index(ns.step)
        elif ns.kind == "goal-reached":
            derived_ordinal = len(_NEW_STEP_ORDER)
        if derived_ordinal is not None and derived_ordinal < old_ordinal:
            demotions.append(
                "%s: hand-set %r, derived %r — record the missing act "
                "(record.py touch ...) or the derivation stands"
                % (o.get("id"), old_play_stage, ns.step or "goal-reached"))

    if not apply_it:
        summary = ("would adopt referral-first, seed default-plan (unconfirmed), assign "
                  "plan_id to %d opportunit(y/ies), relocate %d next_action(s) to note, "
                  "backfill plan_id/play_step on %d touch(es) (%d unresolved), print %d "
                  "demotion(s)" % (len(final_opps), na_relocated, len(new_touches),
                                   unresolved_step_count, len(demotions)))
        return True, "  would migrate (0.49.0) to plans/plays: %s" % summary

    overrides = {
        "opportunities.jsonl": final_opps,
        "touches.jsonl": new_touches,
        "plans.jsonl": new_plans,
        "plays.jsonl": new_plays,
    }
    if _inject_fault == "drop_required_field":
        faulted_plans = [dict(p) for p in new_plans]
        for p in faulted_plans:
            if p.get("id") == "default-plan":
                del p["status"]
        overrides = dict(overrides)
        overrides["plans.jsonl"] = faulted_plans

    rc, problems, new = _shadow_validate(profile, overrides)
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.49.0 REFUSED — the migrated shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)
    pre_existing_note = ""
    if rc != 0:
        pre_existing_note = ("  ⚠️ %d pre-existing problem(s) stand, unrelated to this "
                             "migration: %s" % (len(problems or []), "; ".join((problems or [])[:4])))

    import _atomic
    for name in ("opportunities.jsonl", "touches.jsonl", "plans.jsonl", "plays.jsonl"):
        _atomic.write_jsonl(os.path.join(profile, "data", name), overrides[name])

    bits = ["adopted referral-first", "seeded default-plan (unconfirmed)",
           "plan_id assigned on %d opportunit(y/ies)" % len(final_opps),
           "%d next_action(s) relocated to note" % na_relocated,
           "%d touch(es) backfilled (%d play_step unresolved)" % (len(new_touches),
                                                                  unresolved_step_count)]
    if demotions:
        bits.append(("%d DEMOTION(s) — hand-set positions the store cannot yet prove:\n    "
                    % len(demotions)) + "\n    ".join(demotions[:20]))
    summary = "; ".join(bits)
    msg = ("  ✅ plans/plays (0.49.0) — %s\n  ⚠️ default-plan's play is UNCONFIRMED: nothing "
          "automated acts on it until `plays.py --confirm default-plan` (or --adopt another "
          "pattern, or --manual). See `plays.py --check` for what confirming would unleash."
          % summary)
    return True, (msg + "\n" + pre_existing_note if pre_existing_note else msg)
