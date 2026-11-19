"""Migration 0.27.0: `m_0_27_0_cover_preconditions()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

from migrations.support_prose import _mark_prose_holds

VERSION = "0.27.0"


def m_0_27_0_cover_preconditions(profile, apply_it):
    """0.27.0 — cover-letter send-holds in prose become data (GitHub issue #169, dev #169).

    The 0.18.0 migration converted `drafts.md` only, while `precondition.py` and the dashboard
    now treat `drafts.md` / `cover_letters.md` as the pair `check_sent_drafts.py` always said
    they were. Without this step, a legacy prose hold sitting in `cover_letters.md` predates
    the structured field and was never promoted to the loud `unresolved` marker — invisible
    rather than noisy, so the letter rendered READY on the outward-facing artifact.

    Same body as m_0_18_0 (`_mark_prose_holds`), aimed at the other half of the pair:
    ⭐ PRESERVE, THEN TRANSFORM — the prose stays as human-readable evidence, one marker line
    is inserted under the title, nothing is deleted. Additive and idempotent: entries already
    carrying ANY `**Blocked until:**` field are skipped.
    """
    return _mark_prose_holds(profile, "cover_letters.md", apply_it, "0.27.0")
