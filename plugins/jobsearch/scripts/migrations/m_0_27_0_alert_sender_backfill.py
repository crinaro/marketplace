"""Migration 0.27.0: `m_0_27_0_alert_sender_backfill()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.27.0"


# The sender fragments alert_sweep.py hardcoded before dev #147 — kept here ONLY as the
# backfill's source of truth for what "already covered" meant. alert_sweep.py itself never
# reads this dict again after the migration runs; it reads channels.jsonl's alert_sender field.
LEGACY_ALERT_SENDERS = {
    "indeed": "from:indeed",
    "linkedin": "from:linkedin",
    "dice": "from:dice",
    "careerbuilder": "from:careerbuilder",
    "ladders": "from:ladders",
    "ziprecruiter": "from:ziprecruiter",
}


def m_0_27_0_alert_sender_backfill(profile, apply_it):
    """0.27.0 — alert_sweep.py's aggregator sender list moves from a hardcoded constant into
    `channels.jsonl` (GitHub issue #147, dev #147).

    Retiring an aggregator channel in the store used to have no effect on the daily alert
    sweep, because the retirement decision (`relationship_status`) and the sweep's source list
    (a Python constant) lived in two disconnected places. `alert_sweep.py` now derives its
    sender list from each channel's own `alert_sender` field and honors `relationship_status:
    retired` automatically — a data decision that no longer needs an engine edit.

    ⭐ PRESERVE, THEN TRANSFORM. This backfills `alert_sender` on any channel whose `id`
    contains one of the six sender keywords the old constant hardcoded (indeed / linkedin /
    dice / careerbuilder / ladders / ziprecruiter), matched as a whole `-`/`_`/`:`-delimited
    token — never a bare substring, so an id like `dice-referral-erin` still matches on `dice`
    but a hypothetical `paradise-health` channel does not. That reproduces EXACTLY the
    coverage the sweep already had (the same six senders), from data instead of code, so
    switching to store-driven sweeping changes no behavior for an existing profile until a
    human acts on it (e.g. retires one). A channel whose id matches no keyword is left alone —
    it was never in the old constant either, so backfilling it would invent coverage that
    never existed.

    Additive and idempotent: a row already carrying `alert_sender` (however it got there,
    including a value of `null`) is never touched.
    """
    import re as _re
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
        return False, ("  ⚠️ channels.jsonl could not be read, so alert_sender was left "
                       "alone: %s" % e)

    changed, backfilled = 0, []
    for r in rows:
        if "alert_sender" in r:
            continue
        cid = str(r.get("id") or "").lower()
        tokens = _re.split(r"[-_:]", cid)
        match = next((kw for kw in LEGACY_ALERT_SENDERS if kw in tokens), None)
        if not match:
            continue
        r["alert_sender"] = LEGACY_ALERT_SENDERS[match]
        backfilled.append("%s -> %s" % (r.get("id", "?"), LEGACY_ALERT_SENDERS[match]))
        changed += 1

    if not changed:
        return True, ""
    if not apply_it:
        return True, ("  would backfill alert_sender on %d channel(s), preserving the old "
                      "sweep coverage: %s" % (changed, "; ".join(backfilled)[:300]))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)               # atomic: never a half-written pipeline file
    return True, ("  ✅ channels.jsonl — alert_sender backfilled on %d channel(s), preserving "
                  "the old hardcoded sweep coverage: %s" % (changed, "; ".join(backfilled)[:300]))
