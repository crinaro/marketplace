"""Migration 0.47.0: `m_0_47_0_application_endings()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl

VERSION = "0.47.0"


def m_0_47_0_application_endings(profile, apply_it):
    """0.47.0 — States & Views V1 §3d: the endings vocabulary (`applications[].status:
    closed`, `status_on`, `your_move.ended_because()`) is ADDITIVE ONLY, and this migration
    does the least possible: it invents no reason a value older than the vocabulary should
    have recorded (ADR-013's same call for `parked`-as-expiry-workaround rows).

    1. ASSERTS, never reinterprets: any application row that somehow already carries
       `status: 'closed'` is impossible to write through `record.py` before this release —
       the validator has always refused it — so any found are REPORTED with their ids and
       left completely untouched.
    2. Seeds `status_on: null` on every application row that lacks the key at all — an
       EXPLICIT unknown (the `COMMITMENT_STATUS` seed's own rule: a reader must never guess
       that a missing key means the default), never a date DERIVED from `date` (§3d — that
       would anchor an ATS-silence proposal on the wrong event, §15.4 finding 5).
    3. COUNTS the `unrecorded` population (`your_move.ended_because()` == 'unrecorded') and
       prints it WITH IDS for the next weekly review to carry. Writes NOTHING for them.

    Idempotent for (1) and (2): a second run finds every `status_on` key present and no new
    stray `closed` row. `unrecorded` is DERIVED, not stamped (§2b: "detects the same shape
    going forward"), so it is legitimately recomputed and reported EVERY run — that is not a
    non-idempotence, it is the point.
    """
    apps_path = os.path.join(profile, "data", "applications.jsonl")
    opps_path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(apps_path):
        return True, ""
    try:
        apps = _read_jsonl(apps_path)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ applications.jsonl could not be read — nothing migrated: %s" % e
    try:
        opps = _read_jsonl(opps_path) if os.path.exists(opps_path) else []
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ opportunities.jsonl could not be read — nothing migrated: %s" % e

    stray_closed = [a.get("id") or a.get("opp_id") or "?"
                    for a in apps if a.get("status") == "closed"]
    missing_status_on = [a for a in apps if "status_on" not in a]

    import your_move as _ym
    import applications as _apps_mod
    by_opp = _apps_mod.group_by_opp(apps)
    unrecorded_ids = []
    for o in opps:
        reason = _ym.ended_because(o, by_opp.get(o.get("id"), []))
        if reason == "unrecorded":
            unrecorded_ids.append(o.get("id"))

    if not missing_status_on and not stray_closed and not unrecorded_ids:
        return True, ""

    if not apply_it:
        parts = []
        if missing_status_on:
            parts.append("would seed status_on=null on %d application(s)"
                        % len(missing_status_on))
        if stray_closed:
            parts.append("%d stray 'closed' row(s) predate this vocabulary — reported, "
                        "left untouched" % len(stray_closed))
        if unrecorded_ids:
            parts.append("%d ended pursuit(s) carry no recorded ending (reason unrecorded)"
                        % len(unrecorded_ids))
        return True, "  would migrate (0.47.0) application endings: %s" % "; ".join(parts)

    new_apps = []
    seeded = 0
    for a in apps:
        a = dict(a)
        if "status_on" not in a:
            a["status_on"] = None
            seeded += 1
        new_apps.append(a)

    import _atomic
    _atomic.write_jsonl(apps_path, new_apps)

    msg = ["  ✅ application endings (0.47.0) — seeded status_on=null on %d row(s)" % seeded]
    if stray_closed:
        msg.append("  ⚠️ %d application(s) already carry status='closed' predating this "
                  "release — left untouched, ids: %s"
                  % (len(stray_closed), ", ".join(str(x) for x in stray_closed[:20])))
    if unrecorded_ids:
        msg.append("  ℹ️ %d ended pursuit(s) carry no recorded ending — each shows under "
                  "Ended · reason unrecorded until you write one: `record.py "
                  "application-status <app_id> rejected|withdrawn|closed` — ids: %s"
                  % (len(unrecorded_ids), ", ".join(str(x) for x in unrecorded_ids[:20])))
    return True, "\n".join(msg)
