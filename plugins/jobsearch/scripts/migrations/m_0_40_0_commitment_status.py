"""Migration 0.40.0: `m_0_40_0_commitment_status()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.40.0"


def m_0_40_0_commitment_status(profile, apply_it):
    """0.40.0 — `commitments.jsonl` gains a `status` lifecycle field (public #50).

    A cancelled meeting had nowhere structured to be recorded — the only place to say "this
    was called off" was prose (a handoff note, or hand-editing the title), which decays
    exactly the way ADR-013's `expired` and the asks store's `resolved_on` exist to prevent: a
    fact the run knows, re-typed into narrative instead of the queryable store. `status` is
    additive: `scheduled` (every existing commitment WAS scheduled) or `cancelled` (terminal —
    excluded from the This Week list and conversations.py's prep-owed report regardless of
    date, same shape as an expired opportunity leaving the active pipeline view).

    ⭐ PRESERVE, THEN TRANSFORM, EXPLICIT OVER IMPLICIT. A row that already carries `status`
    (however that happened) is left untouched; only a row with no `status` key at all is
    stamped `scheduled`. This store's sibling (`asks.resolved_on`) lets absence carry meaning,
    but every OTHER additive lifecycle field in this schema (`play_stage`, `blocked_until`)
    seeds an explicit value rather than leaving a reader to know that a missing key defaults —
    the same reasoning applies here, and it is cheap: a bare backfill of one field.

    Idempotent: a second run finds every row already carrying `status` and returns.
    """
    path = os.path.join(profile, "data", "commitments.jsonl")
    if not os.path.exists(path):
        return True, ""
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception as e:
        return False, ("  ⚠️ commitments.jsonl could not be read, so status was left "
                       "unseeded: %s" % e)

    changed = 0
    for r in rows:
        if "status" in r:
            continue
        r["status"] = "scheduled"
        changed += 1

    if not changed:
        return True, ""
    if not apply_it:
        return True, "  would seed status: scheduled on %d commitment(s) (0.40.0)" % changed
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written pipeline file
    return True, ("  ✅ commitments.jsonl (0.40.0) — status: scheduled seeded on %d "
                  "commitment(s); every existing row was in fact scheduled (public #50)"
                  % changed)
