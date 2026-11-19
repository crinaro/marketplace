"""Migration 0.48.0: `m_0_48_0_brief_line_restamp()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.48.0"


def m_0_48_0_brief_line_restamp(profile, apply_it):
    """0.48.0 — public #92, the repair half. The ORIGINAL `m_0_46_0_brief_line` (a) never
    consulted a `**Contact:**` meta line before falling back to `unaddressed`, and (b) could
    run — and did, on the owner's own profile — before its own prerequisite (0.44.0) had
    actually landed, attributing against an empty people store. Both are fixed at the SOURCE
    now (`precondition.resolve_entry_contact`; `_people_prerequisite_pending` above), which
    protects every future run, but an entry ALREADY stamped `**To:** unaddressed` by the old,
    blind code is "already stamped" as far as 0.46.0's own idempotency is concerned and would
    never be revisited on its own.

    This calls `brief.restamp_unaddressed(profile)` — a RE-RUNNABLE query-and-fix pass, not a
    one-shot private to this migration — exactly once, so an entry that was stamped blind and
    NOW resolves (because `**Contact:**` is read, or because 0.44.0 has since landed) gets its
    real `**To:**` line. An entry that still does not resolve is left exactly as it was.
    """
    import _tree
    path = _tree.resolve_rel(profile, _tree.rel("drafts"))
    if not os.path.exists(path):
        return True, ""
    import brief as _brief
    try:
        result = _brief.restamp_unaddressed(profile, apply=apply_it)
    except Exception as e:                                          # noqa: BLE001
        return False, "  ⚠️ 0.48.0 restamp could not run — nothing changed: %s" % e
    if not apply_it:
        if result["restamped"]:
            return True, ("  would re-stamp (0.48.0): %d entr%s currently 'unaddressed' now "
                          "resolve a contact (public #92)"
                          % (result["restamped"],
                             "y" if result["restamped"] == 1 else "ies"))
        return True, ""
    if result["restamped"]:
        return True, ("  ✅ **To:** restamp (0.48.0) — %d entr%s moved from unaddressed to a "
                     "resolved contact (public #92)"
                     % (result["restamped"],
                        "y" if result["restamped"] == 1 else "ies"))
    return True, ""
