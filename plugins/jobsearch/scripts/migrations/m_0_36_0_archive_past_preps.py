"""Migration 0.36.0: `m_0_36_0_archive_past_preps()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

VERSION = "0.36.0"


def m_0_36_0_archive_past_preps(profile, apply_it):
    """0.36.0 — call preps for calls already held move to archive/call-preps/ (dev/audit
    2026-09-02, build item 7). The archive step was a skill line the model was told to
    follow after the call and was skipped every time on the profile measured; it is now
    `archive_preps.py`, a hygiene step of every run. This runs the SAME function once at
    upgrade so the backlog moves on the first session after the release — a change ships as
    a version, never as an instruction. Preserve, then transform: the file moves whole; a
    note with no `**Promoted:**` record gets the `unresolved` marker knowledge.py already
    reports. Idempotent: a second run finds nothing past-dated in the live folder."""
    import archive_preps as _ap
    try:
        res = _ap.archive(profile, apply_it=apply_it)
    except Exception as e:
        return False, "  ⚠️ call-prep archive could not run: %s" % e
    lines = _ap.summary(res, apply_it=apply_it)
    if not lines:
        return True, ""
    prefix = "  ✅ call preps (0.36.0): " if apply_it else "  would archive (0.36.0): "
    return True, prefix + "; ".join(lines)
