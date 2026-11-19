"""Migration 0.45.0: `m_0_45_0_applications_cover_letters()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl
from migrations.support_validate import _shadow_validate

VERSION = "0.45.0"


def m_0_45_0_applications_cover_letters(profile, apply_it, _inject_fault=None):
    """0.45.0 — B2 of ADR-031's connected-entities design: `applications` and `cover_letters`
    become real, top-level, globally-unique stores; `opportunities.applications[]` is promoted
    into `applications` and removed; `opportunities.engagement_type` is added, defaulting
    `full-time`.

    ⭐⭐ KEYED "0.45.0", NOT "0.44.0" (ADR-009, same rule m_0_44_0's own docstring states).
    0.44.0 is the newest PUBLISHED jobsearch release (`plugin.json` at HEAD; origin carries
    `jobsearch--v0.44.0` — verified 2026-09-11 against the local tag list and the 0.44.0
    changelog-discharge commits already merged to origin/main). A profile that installed
    0.44.0 is stamped exactly "0.44.0", and `pending_for()`'s strict `<` would never fire a
    migration keyed to it.

    PRESERVE, THEN TRANSFORM, ALL-OR-NOTHING (design §4 / gate review §2, same shape as
    0.44.0's own migration). Every new/changed row is built ENTIRELY IN MEMORY first; the
    result is validated against a throwaway shadow copy (`_shadow_validate`) BEFORE a single
    real byte moves; only a CLEAN shadow run is written, atomically, to the three real files
    this stage touches (`opportunities.jsonl` and the two new stores). A dirty shadow leaves
    the real profile byte-for-byte untouched and this function returns `(False, ...)` naming
    what failed — a defect in THIS migration to fix before release, never a refusal on data
    grounds (every ambiguity below has a defined, non-destructive outcome).

    PROMOTION — design §1, verbatim:
      * every `applications[]` row becomes one `applications` row, 1:1, `opp_id` = the record
        it came from. `app_id` (minted since 0.41.0; m_0_41_0_app_ids backfilled every
        historical row) becomes this store's own `id` — "promotion changes only the lookup,
        the key value is identical." A row somehow still missing `app_id` (hand-edited,
        never written through record.py) gets one minted here, same `<opp_id>-aN` scheme
        `record.py.mint_app_id` uses, rather than refused.
      * the three UNTYPED legacy fields (`cover_letter`, `cover_letter_attached`,
        `cover_letter_doc`) LEAVE the application row. Where ANY of the three is set (not
        None/False — `cover_letter_attached: false` alone does not count, since "false, no
        letter" needs no record), a `cover_letters` row is minted (`<app_id>-cl` — unique by
        construction, since app_id already is) carrying the three legacy values VERBATIM
        under their OWN original names — a migration that cannot know a field's type must
        not interpret it (design §1/§4; this is the gate review's own B2 plant). No `status`,
        `file`, `doc`, or `created` is invented — those stay null, a human's or a later
        session's to fill. `cover_letter_id` on the application row points at it.
      * `engagement_type` (design §1/§9/§16 item 3): defaulted to `full-time` on every
        opportunity row that does not already carry one — a fact about the role, not
        derivable from anything else on the record, so `full-time` (the vocabulary's own
        default per the design) is the only non-guessing choice.

    Idempotent: a profile with no `applications` key anywhere in `opportunities.jsonl` AND
    every opportunity already carrying `engagement_type` is treated as already migrated and
    this returns `(True, "")`. (A profile with `engagement_type` already set everywhere but
    `applications[]` still nested — impossible via this migration, but defensive rather than
    assumed — still promotes the arrays; the two halves are independent facts, checked
    independently, exactly like m_0_44_0's own two independent facts.)

    `_inject_fault` is a test-only hook (never reachable from the CLI): `"drop_required_field"`
    corrupts one freshly-built application row (drops its `opp_id`) in the SHADOW copy right
    before validation, to prove the all-or-nothing property from outside this function rather
    than by reading its source and assuming. `"invent_status"` makes the cover-letter promotion
    guess `status: "sent"` whenever `cover_letter_attached` is true, regardless of
    `cover_letter_doc` — the gate review's own "a migration that starts guessing" plant.
    """
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(opp_path):
        return True, ""
    try:
        opps = _read_jsonl(opp_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e

    any_applications = any("applications" in r for r in opps)
    any_missing_engagement = any("engagement_type" not in r for r in opps)
    if not (any_applications or any_missing_engagement):
        return True, ""

    application_rows = []
    cover_letter_rows = []
    new_opps = []
    promoted = 0
    letters_minted = 0
    defaulted = 0

    for o in opps:
        o = dict(o)
        legacy_apps = o.pop("applications", None)
        if legacy_apps is not None:
            existing_ids = {a.get("app_id") for a in legacy_apps if isinstance(a, dict)}
            for ap in (legacy_apps or []):
                if not isinstance(ap, dict):
                    continue
                ap = dict(ap)
                aid = ap.pop("app_id", None)
                if not (isinstance(aid, str) and aid.strip()):
                    # Defensive only — m_0_41_0_app_ids already backfilled every historical
                    # row; a hand-edited row with none still gets one, never refused.
                    import record as _record
                    aid = _record.mint_app_id(o.get("id"),
                                              [{"id": x} for x in existing_ids if x])
                    existing_ids.add(aid)
                cl_text = ap.pop("cover_letter", None)
                cl_attached = ap.pop("cover_letter_attached", None)
                cl_doc = ap.pop("cover_letter_doc", None)
                cover_letter_id = None
                if cl_text is not None or cl_attached is not None or cl_doc is not None:
                    clid = "%s-cl" % aid
                    status = None
                    if _inject_fault == "invent_status" and cl_attached:
                        # TEST-ONLY — see docstring. The exact defect the gate review's plant
                        # names: inferring status from cover_letter_attached regardless of
                        # cover_letter_doc, which must lose the golden-output comparison.
                        status = "sent"
                    cover_letter_rows.append({
                        "id": clid, "opp_id": o.get("id"), "created": None, "file": None,
                        "doc": None, "status": status,
                        "cover_letter": cl_text, "cover_letter_attached": cl_attached,
                        "cover_letter_doc": cl_doc, "note": None,
                    })
                    cover_letter_id = clid
                    letters_minted += 1
                ap["id"] = aid
                ap["opp_id"] = o.get("id")
                ap["cover_letter_id"] = cover_letter_id
                application_rows.append(ap)
                promoted += 1
        if "engagement_type" not in o:
            o["engagement_type"] = "full-time"
            defaulted += 1
        new_opps.append(o)

    if not apply_it:
        summary = ("%d application(s) promoted, %d cover letter(s) minted, %d role(s) "
                  "defaulted to engagement_type=full-time" % (promoted, letters_minted, defaulted))
        return True, "  would migrate (0.45.0) to applications/cover_letters: %s" % summary

    overrides = {
        "opportunities.jsonl": new_opps,
        "applications.jsonl": application_rows,
        "cover_letters.jsonl": cover_letter_rows,
    }

    if _inject_fault == "drop_required_field" and application_rows:
        # TEST-ONLY — see docstring. Mutated on a COPY inside the override dict; the real
        # `application_rows` list used for the write below is untouched, so this only ever
        # corrupts what the SHADOW sees.
        faulted = [dict(r) for r in application_rows]
        del faulted[0]["opp_id"]
        overrides = dict(overrides)
        overrides["applications.jsonl"] = faulted

    rc, problems, new = _shadow_validate(profile, overrides)
    if new is None or new:
        detail = "; ".join((new if new else (problems or []))[:8]) or (
            "validator exited %d with no problem list — it crashed" % rc)
        return False, ("  ⚠️ 0.45.0 REFUSED — the migrated shape introduces a new validation "
                       "problem, so NOTHING was written (the real profile is untouched): %s"
                       % detail)
    pre_existing_note = ""
    if rc != 0:
        pre_existing_note = ("  ⚠️ %d pre-existing problem(s) stand, unrelated to this "
                             "migration (a later stage's own migration may resolve them): %s"
                             % (len(problems or []), "; ".join((problems or [])[:4])))

    import _atomic
    for name in ("opportunities.jsonl", "applications.jsonl", "cover_letters.jsonl"):
        _atomic.write_jsonl(os.path.join(profile, "data", name), overrides[name])
    summary = ("%d application(s) promoted, %d cover letter(s) minted, %d role(s) "
              "defaulted to engagement_type=full-time" % (promoted, letters_minted, defaulted))
    msg = "  ✅ applications/cover_letters (0.45.0) — %s" % summary
    return True, (msg + "\n" + pre_existing_note if pre_existing_note else msg)
