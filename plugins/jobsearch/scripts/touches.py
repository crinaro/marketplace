#!/usr/bin/env python3
"""touches.py — the top-level `touches` store (ADR-031 B3), promoted from
`opportunities.outreach[]` (design-connected-entities.md §1, §4).

⭐ THIS MODULE'S OWN EXISTENCE ON DISK IS validate_data.py's B3 STRUCTURAL MARKER
----------------------------------------------------------------------------------
`validate_data.active_retired_keys()` must not refuse the retired `outreach` key on an
opportunity record until B3 has actually shipped — the same "the guard and the migration that
makes the refusal survivable are ONE change" problem B1 solved by gating on `graph.py`'s
presence on disk, and B2 solved with `applications.py`. This file is B3's own marker.

GRAPH.PY VS. touches.py — WHY BOTH, AND WHAT EACH OWNS
--------------------------------------------------------
Unlike B2's applications (an owned pointer: one opportunity, one cover letter), a touch is
genuinely multi-directional — person, opportunity, channel, and now (§12) an object person or
company — exactly the shape `graph.py` exists to walk. So `graph.py` gains `touches_for_person()`
/ `touches_for_opportunity()` / `touches_for_channel()`, resolving merges the way it already does
for messages and involvements — THE one walker, never re-implemented here.

What `graph.py` does NOT do is serve as B3's structural marker (it already exists, shipped with
B1 — its presence cannot newly prove B3 shipped) or give every simple per-opportunity reader
(`applying.py`, `pipeline_index.py`, `trigger.py`, `precondition.py`, `check_sent_drafts.py`,
`check_action_claims.py`, `channels_due.py`, `check_followups.py`, `funnel_report.py`, `watch.py`,
`generate_dashboard.py`) a cheap load-and-group without paying for a full merge-resolving `Graph`
(eight stores loaded) on every call. THIS FILE is that — `applications.py`'s own role, one store
wider: the join every one of those readers used to hand-roll against the nested array now calls
instead. It lands in the SAME commit as the migration and the guard, never ahead of either —
exactly `graph.py`'s own timing for B1, `applications.py`'s for B2.

Usage (as a library only — nothing here opens a profile at import time):
    import touches as _touches
    rows, errs, present = _touches.load(root)
    by_opp = _touches.group_by_opp(rows)
    _touches.enrich_opportunities(root, opps)   # sets o["_touches"] on each row, in place

Python 3.9+. Standard library only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOUCHES_FILE = os.path.join("data", "touches.jsonl")


def _load_jsonl(path):
    """(rows, errors, present). Absence is legal — a not-yet-migrated older profile — and is a
    DIFFERENT state from present-but-broken (the CLAUDE.md trap: a missing thing must never read
    as an empty thing)."""
    if not os.path.exists(path):
        return [], [], False
    rows, errs = [], []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                errs.append("%s line %d: invalid JSON — %s" % (path, i, e))
    return rows, errs, True


def load(root):
    """(rows, errors, present) for data/touches.jsonl."""
    return _load_jsonl(os.path.join(root, TOUCHES_FILE))


def group_by_opp(rows):
    """opp_id -> [row, ...], in file order — the join every reader that used to walk
    `opportunity["outreach"]` by hand now performs instead. `opp_id` is OPTIONAL on a touch
    (design §1 / public #53 — a channel-level or unanchored touch is a legal row), so a row
    with none is never grouped here, same as a dangling FK anywhere else in this engine."""
    out = {}
    for r in rows:
        oid = r.get("opp_id")
        if oid:
            out.setdefault(oid, []).append(r)
    return out


def group_by_person(rows):
    """person_id -> [row, ...], in file order. Raw grouping only — NOT merge-resolved; a
    caller that needs the merge chain honoured (an absorbed alias joining its survivor's
    touches) wants `graph.touches_for_person()` instead."""
    out = {}
    for r in rows:
        pid = r.get("person_id")
        if pid:
            out.setdefault(pid, []).append(r)
    return out


def group_by_channel(rows):
    """channel_id -> [row, ...], in file order — the channel a touch travelled through
    (design §1: 'unchanged meaning' from the old nested field)."""
    out = {}
    for r in rows:
        cid = r.get("channel_id")
        if cid:
            out.setdefault(cid, []).append(r)
    return out


def attach(opps, by_opp):
    """Sets `o["_touches"]` on every `opps` row, IN PLACE, from `by_opp` (`group_by_opp`'s own
    output) — the underscore prefix is this engine's own convention for a derived,
    never-written-back field. Returns `opps` for chaining."""
    for o in opps:
        o["_touches"] = by_opp.get(o.get("id")) or []
    return opps


def enrich_opportunities(root, opps):
    """Loads data/touches.jsonl and calls `attach(opps, ...)` — the one call every reader of
    opportunities + touches together should make, right after loading opportunities. Returns
    the flat touches list too (for a caller that also wants to walk it directly)."""
    rows, _errs, _present = load(root)
    attach(opps, group_by_opp(rows))
    return rows


def sent(rows):
    """Every row whose status proves it actually went out."""
    return [r for r in rows if r.get("status") == "sent"]


if __name__ == "__main__":
    sys.exit(0)
