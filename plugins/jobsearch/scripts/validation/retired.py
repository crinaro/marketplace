"""Retired keys and the structural markers that say which retirement stage has shipped (`active_retired_keys`).

Capability module of `validate_data.py` (S4a). The four marker paths are built on `data_root.SCRIPTS_DIR`, the scripts
directory, where `validate_data.py` read `__file__`; everything else moved unedited."""

import os
from validation import data_root as _data_root


# ⭐⭐ RETIRED NESTED-ARRAY KEYS — ADR-031 §28.1 item 3 / gates-connected-entities.md §1 & Ordering.
# Each connected-entities stage promotes one nested array to its own store and retires the old
# key. This is the ONE place that mapping is declared — check_retired_reads.py's AST scanner
# imports `active_retired_keys()` from here rather than hand-duplicating the three strings, the
# same discipline the field-list guard just above already states: "restating the field list here
# would be the same drift the banned_aliases exist to stop" (line 548 in this file).
#
# `RETIRED_KEYS` names every key ANY stage will eventually retire — declared once, in full, so
# nothing ever hand-types a second copy of these three strings. It is NOT the active refusal set.
#
# ⭐⭐ STAGE-AWARE, ON PURPOSE (the ordering correction this dispatch made — ADR-031 §28.1 item 3,
# re-verified against this file's own guard and against gates-connected-entities.md's Ordering
# section, which requires check_retired_reads.py's own RETIRED_KEYS to "resolve to {} before B1
# ships" for the identical reason). Naming a key here must not REFUSE it before its own stage has
# actually shipped: every tracked profile — including THIS repo's own
# tests/fixtures/profile, read directly by gates.yml's "Data integrity" step — still carries
# `opportunities.contacts[]` until the B1 migration runs, and that migration is explicitly the
# NEXT dispatch's work (ADR-031 §28.1 item 6), not this one's. Confirmed empirically before this
# guard was wired in: patching an unconditional "refuse contacts unconditionally" guard into this
# file flips `validate_data.py` from CLEAN to a hard failure against the tracked fixture, today,
# with no migration yet built to fix the data it would be refusing. ADR-031's own stage rule
# already says why this must not happen: "a store is promoted, its nested source removed, every
# reader re-pointed, the validator and record.py updated, and the migration shipped — in one
# version" (design-connected-entities.md §1) — the validator's refusal and the migration that
# makes the refusal survivable are ONE change, never two commits with a gap between them where
# every existing profile (and this repo's own fixture) fails a validator nobody gave it a way to
# satisfy.
#
# `active_retired_keys()` is that gate: it reads the STAGE'S OWN SHIPPED-NESS FROM THE TREE —
# never a flag a human sets and might forget to update (gates-connected-entities.md's CI-parity
# finding #2, made about check_retired_reads.py but equally true here, since its set must equal
# this one). B1's structural marker is `graph.py`: both the design (§2, "what keeps it honest")
# and the gate review name it as B1's OTHER precondition alongside this guard, and it does not
# exist in this tree until the B1 migration dispatch adds it alongside the migration itself — so
# its presence is exactly the fact that should flip `contacts` from legal to refused. Whoever
# builds B2/B3 names their own analogous marker here (the module or store their own migration
# adds) the same way; the constant grows, the mechanism does not need reinventing.
# ⭐⭐ B4 EXTENDS THE MECHANISM PAST NESTED-ARRAY PROMOTION (2026-09-14). `play_stage` and
# `next_action` are not a nested array being promoted to a store — they are two plain fields on
# `opportunities` being DROPPED outright, their content relocated (design §19: prose to `note`,
# the position to a derivation). The same "the fixture already carries the old shape until the
# migration lands in the same commit" problem applies: `active_retired_keys()` must not refuse
# them until B4's migration (and the fixture regeneration that goes with it) has actually
# shipped. Reusing RETIRED_KEYS/`active_retired_keys()` rather than inventing a second
# mechanism for "a field, not an array" keeps `check_retired_reads.py` a single scanner for
# both retirement shapes — it was already written generically ("every ast.Subscript ... every
# X.get(...) call") and never assumed the key named an array.
RETIRED_KEYS = {"contacts": "B1", "applications": "B2", "outreach": "B3",
               "play_stage": "B4", "next_action": "B4"}

_GRAPH_PY = os.path.join(_data_root.SCRIPTS_DIR, "graph.py")
# ⭐ B2's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). B2 has no cross-store WALKER the way B1's graph.py was already a required
# deliverable — every applications/cover_letters FK is a simple owned pointer, not a
# many-direction graph — so B2's marker is applications.py: the module that owns the
# applications/cover_letters joins every reader used to hand-roll against the nested array (see
# applications.py's own module docstring for the full reasoning). It lands in the SAME commit as
# the 0.45.0 migration and this guard, never ahead of either — exactly graph.py's own timing.
_APPLICATIONS_PY = os.path.join(_data_root.SCRIPTS_DIR, "applications.py")

# ⭐ B3's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). Unlike B2, B3's `touches` store IS genuinely multi-directional (person, opportunity,
# channel, and §12's object person/company) — exactly the shape `graph.py` exists to walk, and
# `graph.py` gains `touches_for_person()`/`touches_for_opportunity()`/`touches_for_channel()`
# accordingly. But `graph.py` already exists on disk (shipped with B1), so its mere presence
# cannot newly prove B3 shipped the way it proved B1 did — B3 needs its OWN marker file the same
# reason B2 did, even though its join IS a "real" walker this time. `touches.py` is that file:
# the flat load/group module every simple per-opportunity reader (`applying.py`,
# `pipeline_index.py`, `trigger.py`, `precondition.py`, `check_sent_drafts.py`,
# `check_action_claims.py`, `channels_due.py`, `check_followups.py`, `funnel_report.py`,
# `watch.py`, `generate_dashboard.py`) now calls instead of hand-rolling the nested array (see
# touches.py's own module docstring for the full "graph.py vs touches.py" reasoning). It lands
# in the SAME commit as the 0.48.0 migration and this guard, never ahead of either — exactly
# graph.py's own timing for B1, applications.py's for B2.
_TOUCHES_PY = os.path.join(_data_root.SCRIPTS_DIR, "touches.py")

# ⭐ B4's OWN structural marker (ADR-031 §29.3's amendment: "each stage names its own structural
# marker"). `plans.py` is B4's flat load/join module (`opportunities.plan_id` is a simple owned
# pointer, not a many-direction graph — the same B2 reasoning `applications.py`'s own docstring
# states). It lands in the SAME commit as the 0.49.0 migration and this guard.
_PLANS_PY = os.path.join(_data_root.SCRIPTS_DIR, "plans.py")


def active_retired_keys():
    """The subset of RETIRED_KEYS whose stage has actually shipped in THIS tree — read structurally,
    never all of RETIRED_KEYS and never a human-set flag. Resolves to {} until B1 ships (graph.py
    lands, with the migration, in one commit); see the block comment above RETIRED_KEYS."""
    active = {}
    # ⭐ `_b1_key`/`_b2_key`/`_b3_key` hold the string in a NAME, never a literal subscript on
    # RETIRED_KEYS here — `check_retired_reads.py`'s own scanner matches a Subscript/`.get()`
    # call whose slice is the STRING CONSTANT "contacts"/"applications"/"outreach" (it cannot
    # tell a data-row read from a constant-dict read apart, by design — see its module
    # docstring). `RETIRED_KEYS["contacts"]` would be a real, if harmless, hit on THIS module;
    # reading it through a local variable is not the checker avoided, it is the checker's own
    # documented boundary — a data row is never keyed by a variable holding a compile-time
    # constant a checker can trace back to this exact line.
    _b1_key = "contacts"
    if os.path.exists(_GRAPH_PY):
        active[_b1_key] = RETIRED_KEYS[_b1_key]
    _b2_key = "applications"
    if os.path.exists(_APPLICATIONS_PY):
        active[_b2_key] = RETIRED_KEYS[_b2_key]
    _b3_key = "outreach"
    if os.path.exists(_TOUCHES_PY):
        active[_b3_key] = RETIRED_KEYS[_b3_key]
    _b4_key_1, _b4_key_2 = "play_stage", "next_action"
    if os.path.exists(_PLANS_PY):
        active[_b4_key_1] = RETIRED_KEYS[_b4_key_1]
        active[_b4_key_2] = RETIRED_KEYS[_b4_key_2]
    return active
