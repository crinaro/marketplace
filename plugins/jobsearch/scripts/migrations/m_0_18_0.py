"""Migration 0.18.0: `m_0_18_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_prose import _mark_prose_holds

VERSION = "0.18.0"


def m_0_18_0(profile, apply_it):
    """0.18.0 — draft preconditions held in prose become data (GitHub issue #13).

    `precondition.py` shipped the `**Blocked until:**` field with no migration, so a profile
    predating it kept its holds in prose and the tool reported every such draft **sendable** —
    a false green with the authority of a gate, strictly worse than the prose it replaced.

    ⭐ PRESERVE, THEN TRANSFORM. For each drafts.md entry whose text carries a hold phrase
    (`precondition.HOLD_RE`) but no structured field, insert

        **Blocked until:** unresolved (migrated 0.18.0 from prose)

    directly under the title. The prose stays untouched — it is the human-readable evidence —
    and the FACT that the draft is blocked moves into the queryable store, where
    `precondition.py` reports it `unresolved` (never sendable) until someone replaces the
    marker with the real join, `contact:<id> outcome:<...>`. Nothing here guesses the contact:
    a guessed join that resolves against the wrong person is the same false green again.

    Additive and idempotent: entries already carrying ANY `**Blocked until:**` field are
    skipped, so a second run finds nothing to do. SAFE by this module's own rule — inserts a
    line, deletes nothing, reversible from git.
    """
    return _mark_prose_holds(profile, "drafts.md", apply_it, "0.18.0")
