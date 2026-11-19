"""Migration 0.39.0: `m_0_39_0_presence_rules()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.39.0"


# The seed for a profile that has no rules file. Every line is one paragraph on purpose —
# the file it seeds is rendered by presence_set.py's paragraph-faithful renderer, and a seed
# that wrapped its own prose would open with a paragraph-drift finding against itself.
PRESENCE_RULES_SEED = """# Presence — standing rules

Settled decisions about the claim union (`presence/claims.md`) and the declared variants. A rule here is DECIDED; an open question belongs on the working set's open-items tab, never here. The two are kept apart on purpose: a decision parked among open items is re-litigated every session, and an open item filed among the rules never gets done.

## Rules

- A variant is a SELECTION from the union: copy its sentences, never paraphrase. A wording a page needs lands in the union first, then on the page.
- A proof point reaches a printed page only through the union — never straight from `presence/projects.md`.
- Adjacent lines are one paragraph. Separate paragraphs, roles and bullets with a blank line: every renderer merges what the file does not separate, and the working set shows that merge rather than hiding it.
"""


def m_0_39_0_presence_rules(profile, apply_it):
    """0.39.0 — `presence/rules.md` exists on every profile (ADR-028 rule 2; public #62).

    The presence working set (`presence_set.py`) renders a rules tab from this file so that
    settled decisions and open items never share a list. A profile that predates the file
    has no such tab to render — a missing thing reading as an empty one — so the file is
    CREATED here, seeded with the three rules the engine already enforces elsewhere, stated
    for the owner to extend. PRESERVE, THEN TRANSFORM: a rules file that already exists is
    never touched (the owner's decisions outrank the seed); nothing is relocated because
    nothing predates this file. Idempotent: the second run finds the file and returns.
    """
    import _tree
    path = _tree.path(profile, "presence_rules")
    rel = _tree.rel("presence_rules")
    if os.path.exists(path):
        return True, ""
    if not apply_it:
        return True, "  would create (0.39.0): %s, seeded with the three standing rules" % rel
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(PRESENCE_RULES_SEED)
        os.replace(tmp, path)
    except OSError as e:
        return False, "  ⚠️ %s could not be created: %s" % (rel, e)
    return True, ("  ✅ %s (0.39.0): created, seeded with the three standing rules — the "
                  "working set's rules tab renders it; extend it with your own decisions" % rel)
