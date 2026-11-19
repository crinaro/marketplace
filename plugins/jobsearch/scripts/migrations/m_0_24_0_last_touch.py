"""Migration 0.24.0: `m_0_24_0_last_touch()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.24.0"


def m_0_24_0_last_touch(profile, apply_it):
    """0.24.0 (part 2 of 2) — `last_touch` is removed from the channel schema (GitHub #79).

    `your_move.py`'s derived-touch computation replaces it: the max of an outbound message in
    messages.jsonl joined by contact_id, and the latest log[] entry. Nothing ever wrote
    last_touch mechanically (only two hand-written test cases and a dead read in
    check_action_claims.py did), so removing it costs no live capability. REQUIRED, not
    optional tidying: unknown keys are rejected at write time (schema.md), so a channel still
    carrying this key would fail record.py's write guard the next time anything touched it.

    ⭐ PRESERVE, THEN TRANSFORM. Any hand-authored value is folded into `log[]` as
    `{"date": <its value>, "note": "(migrated from last_touch)"}` before the key is dropped —
    nothing is discarded, it just moves to where the schema still allows it. Additive from
    log[]'s point of view and idempotent: a row with no last_touch is untouched.
    """
    path = os.path.join(profile, "data", "channels.jsonl")
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
        return False, "  ⚠️ channels.jsonl could not be read, so last_touch was left alone: %s" % e

    changed, folded = 0, []
    for r in rows:
        if "last_touch" not in r:
            continue
        val = r.pop("last_touch")
        r.setdefault("log", []).append({"date": val, "note": "(migrated from last_touch)"})
        folded.append("%s (%s)" % (r.get("id", "?"), val))
        changed += 1

    if not changed:
        return True, ""
    if not apply_it:
        return True, ("  would fold last_touch into log[] and remove it on %d channel(s): %s"
                      % (changed, "; ".join(folded)[:300]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written pipeline file
    return True, ("  ✅ channels.jsonl — last_touch folded into log[] and removed on %d "
                  "channel(s): %s" % (changed, "; ".join(folded)[:300]))
