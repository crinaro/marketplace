"""Migration 0.48.0: `m_0_48_0_touches()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.48.0"


def m_0_48_0_touches(profile, apply_it, _inject_fault=None):
    """0.48.0 — B3 of ADR-031's connected-entities design: `touches` becomes a real,
    top-level, globally-unique store; `opportunities.outreach[]` is promoted into it and
    removed.

    ⭐⭐ KEYED "0.48.0", NOT "0.47.0" (ADR-009, same rule every prior stage's own docstring
    states). 0.47.0 is the newest PUBLISHED jobsearch release (`plugin.json` at HEAD; the
    0.47.0 release record was discharged and its changelog PR merged to origin/main before
    this dispatch started). A profile that installed 0.47.0 is stamped exactly "0.47.0", and
    `pending_for()`'s strict `<` would never fire a migration keyed to it.

    PRESERVE, THEN TRANSFORM, ALL-OR-NOTHING (design §4 / gate review §2, same shape as every
    prior stage's own migration). Every new/changed row is built ENTIRELY IN MEMORY first; the
    result is validated against a throwaway shadow copy (`_shadow_validate`) BEFORE a single
    real byte moves; only a CLEAN shadow run is written, atomically, to the two real files this
    stage touches (`opportunities.jsonl`, `touches.jsonl`) plus `people.jsonl` when an
    unresolved mint occurs. A dirty shadow leaves the real profile byte-for-byte untouched and
    this function returns `(False, ...)` naming what failed.

    PROMOTION — design §1, verbatim:
      * every `outreach[]` row becomes one `touches` row, 1:1, `opp_id` = the record it came
        from. `id` is minted `<person_id>-tN` (record.py's own scheme — design §1: "a touch is
        owned by the PERSON"), counted per resolved person_id across the WHOLE profile, in
        file order (opportunities, then each one's own outreach[] entries) — deterministic,
        reproducible from the input alone.
      * `person_id` was already renamed from `contact_id` by B1's own 0.44.0 migration (its own
        step 5) — this migration does not repeat that rename. What B1's step 5 left behind for
        a row whose raw `contact_id` did not resolve within its own anchor is `person_id: null`
        (preserved, never silently re-guessed there): this migration treats a null OR
        non-resolving `person_id` identically — it MINTS `unresolved-<opp_id>-t<n>` (a fresh,
        active `people` row, `status: active`, a note naming what could not be resolved),
        counted per opportunity, and points the touch at it — preserved and loud, never
        dropped (design §22: "synthesize, never refuse; demotions printed, never hidden" —
        the Scope's own generalisation of that rule to an unresolvable person_id here).
      * every other outreach[] field is carried over VERBATIM — this migration does not
        interpret or invent a value for any of them.

    Idempotent: a profile with no `outreach` key anywhere in `opportunities.jsonl` is treated
    as already migrated and this returns `(True, "")`.

    `_inject_fault` is a test-only hook (never reachable from the CLI): `"drop_required_field"`
    corrupts one freshly-built touch row (drops its `person_id`) in the SHADOW copy right
    before validation, to prove the all-or-nothing property from outside this function rather
    than by reading its source and assuming.
    """
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    people_path = os.path.join(profile, "data", "people.jsonl")
    if not os.path.exists(opp_path):
        return True, ""
    try:
        opps = _read_jsonl(opp_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e
    try:
        people_rows = _read_jsonl(people_path) if os.path.exists(people_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ people.jsonl could not be read — nothing migrated: %s" % e

    any_outreach = any("outreach" in r for r in opps)
    if not any_outreach:
        return True, ""

    people_rows = [dict(p) for p in people_rows]
    people_by_id = {p.get("id") for p in people_rows if p.get("id")}

    touch_rows = []
    new_opps = []
    promoted = 0
    minted_notes = []
    person_touch_counters = {}          # resolved person_id -> next N, for <person_id>-tN
    per_opp_mint_counters = {}          # opp_id -> next N, for unresolved-<opp_id>-t<n>

    def _mint_touch_id(pid):
        n = person_touch_counters.get(pid, 0) + 1
        person_touch_counters[pid] = n
        return "%s-t%d" % (pid, n)

    for o in opps:
        o = dict(o)
        legacy = o.pop("outreach", None)
        if legacy is not None:
            oid = o.get("id")
            for entry in (legacy or []):
                if not isinstance(entry, dict):
                    continue
                entry = dict(entry)
                # Defensive only — B1's own 0.44.0 already renamed contact_id -> person_id on
                # every outreach[] row; a hand-edited row with the old spelling still surviving
                # is handled the same way a raw, never-resolved id would be, below.
                raw_pid = entry.pop("contact_id", None) or entry.get("person_id")
                pid = entry.get("person_id") or raw_pid
                if not pid or pid not in people_by_id:
                    n = per_opp_mint_counters.get(oid, 0) + 1
                    per_opp_mint_counters[oid] = n
                    minted = "unresolved-%s-t%d" % (oid, n)
                    note = ("minted by the 0.48.0 migration: opportunities[%s] outreach "
                            "person_id %r %s — preserved as its own person rather than "
                            "dropped" % (oid, pid, "was empty" if not pid else
                                         "resolves to no people row"))
                    people_rows.append({
                        "id": minted, "name": entry.get("to") or pid or "unknown",
                        "email": None, "email_status": None, "linkedin": None,
                        "company_id": None, "title": None, "cadence": None,
                        "status": "active", "merged_into": None, "not_same_as": [],
                        "created": None, "note": note,
                    })
                    people_by_id.add(minted)
                    minted_notes.append(note)
                    pid = minted
                entry["person_id"] = pid
                entry["opp_id"] = oid
                entry.setdefault("channel_id", None)
                entry.setdefault("object_person_id", None)
                entry.setdefault("object_company_id", None)
                entry["id"] = _mint_touch_id(pid)
                touch_rows.append(entry)
                promoted += 1
        new_opps.append(o)

    if not apply_it:
        summary = "%d touch(es) promoted to touches; %d unresolved person(s) minted" % (
            promoted, len(minted_notes))
        return True, "  would migrate (0.48.0) to touches: %s" % summary

    overrides = {
        "opportunities.jsonl": new_opps,
        "touches.jsonl": touch_rows,
        "people.jsonl": people_rows,
    }

    if _inject_fault == "drop_required_field" and touch_rows:
        # TEST-ONLY — see docstring. Mutated on a COPY inside the override dict; the real
        # `touch_rows` list used for the write below is untouched, so this only ever corrupts
        # what the SHADOW sees.
        faulted = [dict(r) for r in touch_rows]
        del faulted[0]["person_id"]
        overrides = dict(overrides)
        overrides["touches.jsonl"] = faulted

    rc, problems, new = _shadow_validate(profile, overrides)
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.48.0 REFUSED — the migrated shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)
    pre_existing_note = ""
    if rc != 0:
        pre_existing_note = ("  ⚠️ %d pre-existing problem(s) stand, unrelated to this "
                             "migration (a later stage's own migration may resolve them): %s"
                             % (len(problems or []), "; ".join((problems or [])[:4])))

    import _atomic
    for name in ("opportunities.jsonl", "touches.jsonl", "people.jsonl"):
        _atomic.write_jsonl(os.path.join(profile, "data", name), overrides[name])
    summary_bits = ["%d touch(es) promoted to touches" % promoted]
    if minted_notes:
        summary_bits.append("%d unresolved person(s) minted: %s"
                            % (len(minted_notes), " | ".join(minted_notes)))
    summary = "; ".join(summary_bits)
    msg = "  ✅ touches (0.48.0) — %s" % summary
    return True, (msg + "\n" + pre_existing_note if pre_existing_note else msg)
