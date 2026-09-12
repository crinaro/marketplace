#!/usr/bin/env python3
"""applications.py — the top-level `applications` / `cover_letters` stores (ADR-031 B2):
`resume_variants`' twin, promoted from `opportunities.applications[]`
(design-connected-entities.md §1, §4).

⭐ THIS MODULE'S OWN EXISTENCE ON DISK IS validate_data.py's B2 STRUCTURAL MARKER
----------------------------------------------------------------------------------
`validate_data.active_retired_keys()` must not refuse the retired `applications` key on an
opportunity record until B2 has actually shipped — the same "the guard and the migration that
makes the refusal survivable are ONE change" problem B1 solved by gating on `graph.py`'s
presence on disk (see validate_data.py's own block comment above `RETIRED_KEYS`). B1's marker
was a module design already REQUIRED it to build (the cross-store walker); B2 promotes
`applications`/`cover_letters` but adds no such walker of its own — every FK here is a simple
owned pointer (an application belongs to exactly one opportunity, points at exactly one
`cover_letters` row), not a many-direction graph `graph.py` already covers fine.

So B2 needed its own genuinely useful deliverable to serve as that same structural fact — design
§29.3's own amendment says every future stage must name one ("each stage names its own
structural marker"). THIS FILE is it: the module that owns the join every reader used to
hand-roll against the nested array (`applying.py`, `resume_variants.py`, `funnel_report.py`,
`generate_dashboard.py`, `trigger.py`, `pipeline_index.py`, `check_action_claims.py`,
`check_sent_drafts.py`, `your_move.py` all walked `opportunity["applications"]` by hand before
B2; every one of them now calls `enrich_opportunities()` or `load()` here instead). It lands in
the SAME commit as the migration and the guard, never ahead of either — exactly `graph.py`'s own
timing for B1.

Usage (as a library only — nothing here opens a profile at import time):
    import applications as _apps
    apps, errs, present = _apps.load(root)
    letters, errs, present = _apps.load_cover_letters(root)
    by_opp = _apps.group_by_opp(apps)
    _apps.enrich_opportunities(root, opps)   # sets o["_applications"] on each row, in place

Python 3.9+. Standard library only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

APPLICATIONS_FILE = os.path.join("data", "applications.jsonl")
COVER_LETTERS_FILE = os.path.join("data", "cover_letters.jsonl")

# Mirrored from validate_data.SUBMITTED_APP_STATUS as a literal — the SAME move
# resume_variants.py already makes for the identical set (its own comment: "a drifted mirror is
# caught by the regression suite, not by an import cycle at run start"; precondition.py's
# OUTCOMES is the original precedent). Kept consistent with that convention here, not
# reinvented — a caller that wants validate_data's own copy can still read it there directly.
SUBMITTED_APP_STATUS = {"submitted", "acknowledged", "rejected", "advanced"}


def _load_jsonl(path):
    """(rows, errors, present). Absence is legal — a not-yet-scaffolded older profile — and is a
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
    """(rows, errors, present) for data/applications.jsonl."""
    return _load_jsonl(os.path.join(root, APPLICATIONS_FILE))


def load_cover_letters(root):
    """(rows, errors, present) for data/cover_letters.jsonl."""
    return _load_jsonl(os.path.join(root, COVER_LETTERS_FILE))


def group_by_opp(rows):
    """opp_id -> [row, ...], in file order — the one join every reader that used to walk
    `opportunity["applications"]` by hand now performs instead. A row with no opp_id
    (unreadable — validate_data.py already refuses this at the door) is never grouped, same as
    a dangling FK anywhere else in this engine."""
    out = {}
    for r in rows:
        oid = r.get("opp_id")
        if oid:
            out.setdefault(oid, []).append(r)
    return out


def group_cover_letters_by_id(rows):
    """id -> row — the lookup `applications[].cover_letter_id` joins against."""
    return {r.get("id"): r for r in rows if r.get("id")}


def attach(opps, by_opp):
    """Sets `o["_applications"]` on every `opps` row, IN PLACE, from `by_opp`
    (`group_by_opp`'s own output) — the underscore prefix is this engine's own convention for a
    derived, never-written-back field (record.py's `_your_move_visibility_note`, the validator's
    own `_active_retired` locals), so this can never be mistaken for a real column and never
    round-trips through a write. Returns `opps` for chaining."""
    for o in opps:
        o["_applications"] = by_opp.get(o.get("id")) or []
    return opps


def enrich_opportunities(root, opps):
    """Loads data/applications.jsonl and calls `attach(opps, ...)` — the one call every reader
    of opportunities + applications together should make, right after loading opportunities.
    Returns the flat applications list too (for a caller that also wants to walk it directly,
    e.g. a report keyed by application rather than by opportunity)."""
    rows, _errs, _present = load(root)
    attach(opps, group_by_opp(rows))
    return rows


def submitted(rows):
    """Every row whose status proves a submission actually happened."""
    return [r for r in rows if r.get("status") in SUBMITTED_APP_STATUS]


def uncovered(root, active_variant_ids):
    """Submitted applications with no resume_variant, while active variants exist — the
    top-level-store successor to resume_variants.py's own (now-retired) nested-array walk of
    the same name. `active_variant_ids` is the caller's own active resume_variants id set (this
    function does not read resume_variants.jsonl itself — one less store for a caller that
    already has it to open twice)."""
    if not active_variant_ids:
        return []
    apps, _errs, _present = load(root)
    return ["%s (opp %s, %s)" % (r.get("id") or "?", r.get("opp_id") or "?",
                                 r.get("date") or "undated")
            for r in submitted(apps) if not r.get("resume_variant")]


if __name__ == "__main__":
    sys.exit(0)
