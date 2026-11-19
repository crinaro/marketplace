"""Migration 0.25.0: `m_0_25_0_play_stage()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.25.0"


def m_0_25_0_play_stage(profile, apply_it):
    """0.25.0 — the post-application play position becomes a field (public #19 / dev #95).

    The play sequence (needs application → applied → reach the recruiter through an insider →
    … → awaiting reply) could only be recorded by prefixing free-text NUMBERED MARKERS onto
    `next_action` — "3) …" — which nothing can filter, group, count, sort or validate. The
    schema now carries `play_stage`, enum-gated by validate_data.py.

    ⭐ PRESERVE, THEN TRANSFORM — and never guess. The prose is left verbatim (it remains the
    human-readable evidence); only the FACT that a play position exists moves into the
    queryable store. A number alone cannot say WHICH stage it encodes — the numbering was
    invented per-profile, per-session — so this writes the literal `unresolved`, exactly as
    m_0_24_0_blocked_until does for an ambiguous hold: valid, durable, loudly incomplete. The
    way out is a human (or the coordinator) replacing it:
    `record.py set <id> play_stage <value>`.

    Skips: rows already carrying `play_stage` (idempotent), and terminal rows (`passed`/
    `expired` — the validator refuses a play position on a role that left the funnel).
    """
    import re as _re
    # A leading numbered marker: "1) ", "(2) ", "3. ", "4: ", "[5]", "step 2 …". Anchored at
    # the start so a date ("2026-08-20 call") or a time ("3pm") never matches.
    marker = _re.compile(r"^\s*(?:\(?\d{1,2}\s*[\).:\]]\s|step\s+\d{1,2}\b)", _re.I)
    path = os.path.join(profile, "data", "opportunities.jsonl")
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
        return False, ("  ⚠️ opportunities.jsonl could not be read, so no play_stage was "
                       "backfilled: %s" % e)

    import validate_data as _vd          # the ONE terminal set (build item 1, 2026-09-02)
    changed, marked = 0, []
    for r in rows:
        if "play_stage" in r:
            continue
        if r.get("status") in _vd.TERMINAL_OPP_STATUSES:
            continue
        if not marker.match(str(r.get("next_action") or "")):
            continue
        r["play_stage"] = "unresolved"
        marked.append(r.get("id", "?"))
        changed += 1

    if not changed:
        return True, ""
    if not apply_it:
        return True, ("  would mark play_stage 'unresolved' on %d opportunity(ies) whose "
                      "next_action carries a numbered play marker" % changed)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written pipeline file
    return True, ("  ✅ opportunities.jsonl — play_stage 'unresolved' on %d role(s) with a "
                  "numbered play marker in next_action: %s. Each needs a human to set the real "
                  "value (record.py set <id> play_stage <value>)."
                  % (changed, "; ".join(marked)[:300]))
