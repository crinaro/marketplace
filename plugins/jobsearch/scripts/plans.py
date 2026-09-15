#!/usr/bin/env python3
"""plans.py — the top-level `plans` / `plays` stores (ADR-031 B4): the owner's strategy as
data (design-connected-entities.md §10, §17, §18, §20).

⭐ THIS MODULE'S OWN EXISTENCE ON DISK IS validate_data.py's B4 STRUCTURAL MARKER
----------------------------------------------------------------------------------
`validate_data.active_retired_keys()` must not refuse the retired `play_stage`/`next_action`
keys on an opportunity record until B4 has actually shipped — the same "the guard and the
migration that makes the refusal survivable are ONE change" problem B1 solved by gating on
`graph.py`'s presence on disk, B2 on `applications.py`, B3 on `touches.py`. THIS FILE is B4's
own marker, the same shape as B2's own reasoning: every FK here is a simple owned pointer
(`opportunities.plan_id -> plans.id`, `plans.play_id -> plays.id`), not a many-direction graph,
so it does not belong in `graph.py`. It lands in the SAME commit as the migration and the
guard, never ahead of either.

WHAT THIS MODULE OWNS, PLAYS.PY OWNS THE REST
------------------------------------------------
This is the flat load/join module — `plans.py` reads and reasons about `plans`/`plays` as
DATA (which plan governs a pursuit, which search plans are active, effective targets, the
sourcing-ambiguity refusal of design §26.5). The predicate vocabulary, `next_step()`, and the
whole CLI surface (`--options`/`--show`/`--adopt`/`--confirm`/`--check`/`--all`/`--brief`) live
in `plays.py`, which imports this module rather than re-reading the stores itself — one loader,
one reasoner, the `applications.py`/`your_move.py` split applied here.

Usage (as a library only — nothing here opens a profile at import time):
    import plans as _plans
    rows, errs, present = _plans.load(root)
    plays, errs, present = _plans.load_plays(root)
    _plans.enrich_opportunities(root, opps)     # sets o["_plan"] on each row, in place

Python 3.9+. Standard library only.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PLANS_FILE = os.path.join("data", "plans.jsonl")
PLAYS_FILE = os.path.join("data", "plays.jsonl")

# design §10/§17 — the four subject kinds and which may GOVERN a pursuit (opportunities.plan_id).
SUBJECT_KINDS = {"opportunity", "company", "person", "search"}
GOVERNING_SUBJECT_KINDS = {"opportunity", "company", "search"}
OUTCOMES = {"role", "contract", "access"}
PLAN_STATUS = {"active", "retired"}
RESOLVES_WHEN = {"goal-reached", "access-direct"}
PLAY_STATUS = {"active", "retired"}
# design §17 — the literal sentinel meaning "the owner decides each step", never a shipped
# pattern's id (the `unresolved` precedent: a chosen sentinel, not a guess).
MANUAL_PLAY = "manual"


def _load_jsonl(path):
    """(rows, errors, present). Absence is legal — a not-yet-migrated older profile — and is a
    DIFFERENT state from present-but-broken (the CLAUDE.md trap: a missing thing must never
    read as an empty thing)."""
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
    """(rows, errors, present) for data/plans.jsonl."""
    return _load_jsonl(os.path.join(root, PLANS_FILE))


def load_plays(root):
    """(rows, errors, present) for data/plays.jsonl."""
    return _load_jsonl(os.path.join(root, PLAYS_FILE))


def by_id(rows):
    return {r.get("id"): r for r in rows if r.get("id")}


def attach(opps, plans_by_id):
    """Sets `o["_plan"]` on every `opps` row, IN PLACE (the underscore-prefix, derived,
    never-written-back convention `touches.attach`/`applications.attach` already use)."""
    for o in opps:
        o["_plan"] = plans_by_id.get(o.get("plan_id"))
    return opps


def enrich_opportunities(root, opps):
    """Loads data/plans.jsonl and calls `attach(opps, ...)` — the one call a reader of
    opportunities + plans together should make, right after loading opportunities. Returns the
    flat plans list too (for a caller that also wants to walk it directly)."""
    rows, _errs, _present = load(root)
    attach(opps, by_id(rows))
    return rows


def active(rows):
    return [r for r in rows if (r.get("status") or "active") != "retired"]


def search_plans(rows):
    """Every ACTIVE `search`-subject plan — design §17's amendment: several may be active at
    once (a themed search is a search)."""
    return [r for r in active(rows) if r.get("subject_kind") == "search"]


def union_outcomes(rows):
    """The union of every active search plan's `outcomes` — design §13: the dashboard's
    section order is a function of this set."""
    out = set()
    for p in search_plans(rows):
        out |= set(p.get("outcomes") or [])
    return out


def sourcing_candidates(rows):
    """Active search plans whose `outcomes` names `role` or `contract` — the plans sourcing may
    write `plan_id` from (design §26.5)."""
    return [p for p in search_plans(rows) if set(p.get("outcomes") or []) & {"role", "contract"}]


def effective_targets(plan, cfg):
    """A search plan's own `targets` override if set, else `config.json`'s own `targets`
    (design §26.5) — canonicalized (sorted, deduplicated) so two plans with the same targets in
    different order still compare equal."""
    t = (plan or {}).get("targets") or (cfg or {}).get("targets") or {}
    titles = sorted(set(t.get("titles") or []))
    verticals = sorted(set(t.get("verticals") or []))
    return (tuple(titles), tuple(verticals))


def resolve_sourcing_plan(rows, cfg, explicit_id=None):
    """(plan_id, error) — which search plan a freshly sourced role's `plan_id` should be set
    to. `explicit_id` is a caller-supplied `--plan`, checked first and returned as-is if it
    names an active sourcing candidate (design §26.5's own escape from the refusal). With
    exactly one candidate, that one plan. With none, (None, an explanatory error — nothing
    sources). With more than one, (None, a refusal naming every candidate) UNLESS
    `explicit_id` was given."""
    cands = sourcing_candidates(rows)
    if explicit_id:
        names = {p.get("id") for p in cands}
        if explicit_id not in names:
            return None, ("--plan %r does not name an active search plan whose outcomes "
                          "include role or contract (have: %s)"
                          % (explicit_id, ", ".join(sorted(names)) or "none"))
        return explicit_id, None
    if not cands:
        return None, "no active search plan sources role/contract — nothing to assign plan_id to"
    if len(cands) == 1:
        return cands[0]["id"], None
    ids = ", ".join(sorted(p.get("id") or "?" for p in cands))
    return None, ("%d active search plans source roles: %s; pass --plan <id>"
                  % (len(cands), ids))


def governs(plan, opp):
    """Does `plan` (a plans.jsonl row) legally govern `opp` (an opportunities.jsonl row) — the
    subject rule design §17's table states. `subject_kind: search` governs anything; `company`
    governs a pursuit at that company; `opportunity` governs exactly the one it names; `person`
    governs none."""
    kind = plan.get("subject_kind")
    if kind == "search":
        return True
    if kind == "company":
        return opp.get("company_id") == plan.get("subject_id")
    if kind == "opportunity":
        return opp.get("id") == plan.get("subject_id")
    return False


if __name__ == "__main__":
    sys.exit(0)
