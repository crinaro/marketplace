"""Migration 0.41.0: `m_0_41_0_app_ids()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
from migrations.support_jsonl import _read_jsonl, _rewrite_jsonl

VERSION = "0.41.0"


def m_0_41_0_app_ids(profile, apply_it):
    """0.41.0 — every applications[] row carries `app_id` (public #27's deferred D3 backfill;
    design pass A, step 1).

    `app_id` was declared optional "until the deferred migration backfills history", so a
    trigger (outreach[].trigger_ref, asks.trigger_ref) resolved by DATE for every row written
    before it — a handle two applications on one day share and nothing guarantees. record.py
    now mints `<opp_id>-aN` at write time; this is the other half: the backfill that makes the
    handle exist on every historical row, so every later reader resolves a key the schema
    guarantees instead of a date somebody remembered.

    ⭐ ARRAY ORDER, NEVER RENUMBERED. Rows are numbered in the order they sit in the array —
    the first row lacking an id becomes a1, the next a2 — and a row that already carries an
    `app_id` (hand-minted since public #27) keeps it, its number skipped rather than reused: a
    trigger naming it must keep naming the same application. Idempotent by construction.

    Then the date refs: an outreach row or ask with `trigger_kind: application` whose
    `trigger_ref` is the date of EXACTLY ONE application on its record is re-pointed to that
    row's id (docs/data_model.json's outreach._note anticipated exactly this). A date shared
    by two rows is left as written — it still resolves by date, and picking one would be a
    guess recorded as a fact; it is REPORTED so the owner can name the row. PRESERVE, THEN
    TRANSFORM: nothing is removed, only added (app_id) or made more specific (a ref naming
    the row instead of its day).
    """
    opp_path = os.path.join(profile, "data", "opportunities.jsonl")
    if not os.path.exists(opp_path):
        return True, ""
    try:
        opps = _read_jsonl(opp_path)
    except Exception as e:                      # noqa: BLE001
        return False, ("  ⚠️ opportunities.jsonl could not be read, so app_id was left "
                       "unminted: %s" % e)
    asks_path = os.path.join(profile, "data", "asks.jsonl")
    asks = []
    if os.path.exists(asks_path):
        try:
            asks = _read_jsonl(asks_path)
        except Exception as e:                  # noqa: BLE001
            return False, ("  ⚠️ asks.jsonl could not be read, so app_id was left "
                           "unminted: %s" % e)

    minted, ambiguous = 0, []
    repointed = {"outreach": 0, "asks": 0}
    by_opp = {}                                 # rid -> (date -> [app_id...], {app_id...})
    for r in opps:
        rid = r.get("id")
        apps = r.get("applications")
        if not rid or not isinstance(apps, list):
            continue
        taken = {a.get("app_id") for a in apps
                 if isinstance(a, dict) and isinstance(a.get("app_id"), str) and a.get("app_id")}
        n = 1
        for a in apps:
            if not isinstance(a, dict) or a.get("app_id"):
                continue
            while "%s-a%d" % (rid, n) in taken:
                n += 1
            a["app_id"] = "%s-a%d" % (rid, n)
            taken.add(a["app_id"])
            minted += 1
            n += 1
        dates = {}
        for a in apps:
            if isinstance(a, dict) and a.get("date"):
                dates.setdefault(str(a["date"]), []).append(a["app_id"])
        by_opp[rid] = (dates, taken)

    def _repoint(row, rid, label, bucket):
        if not isinstance(row, dict) or row.get("trigger_kind") != "application":
            return
        ref = row.get("trigger_ref")
        dates, ids = by_opp.get(rid) or ({}, set())
        if not isinstance(ref, str) or ref in ids:
            return
        owners = dates.get(ref) or []
        if len(owners) == 1:
            row["trigger_ref"] = owners[0]
            repointed[bucket] += 1
        elif len(owners) > 1:
            ambiguous.append("%s: trigger_ref %r is the date of %d applications (%s) — name "
                             "one by app_id" % (label, ref, len(owners), ", ".join(owners)))

    for r in opps:
        for i, o in enumerate(r.get("outreach") or []):
            _repoint(o, r.get("id"), "%s outreach[%d]" % (r.get("id"), i), "outreach")
    for a in asks:
        if isinstance(a, dict) and a.get("opp_id"):
            _repoint(a, a["opp_id"], "ask %s" % a.get("id"), "asks")

    if not minted and not repointed["outreach"] and not repointed["asks"]:
        return True, ""
    summary = ("app_id minted on %d application row(s) in array order; %d outreach and %d "
               "ask date trigger_ref(s) re-pointed to the minted id"
               % (minted, repointed["outreach"], repointed["asks"]))
    notes = "".join("\n  ℹ️ left by date (still resolves): %s" % x for x in ambiguous)
    if not apply_it:
        return True, "  would backfill (0.41.0): %s%s" % (summary, notes)
    _rewrite_jsonl(opp_path, opps)
    if repointed["asks"]:
        _rewrite_jsonl(asks_path, asks)
    return True, "  ✅ opportunities.jsonl (0.41.0) — %s%s" % (summary, notes)
