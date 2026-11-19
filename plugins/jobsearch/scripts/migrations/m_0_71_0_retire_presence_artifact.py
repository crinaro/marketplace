"""Migration 0.71.0: `m_0_71_0_retire_presence_artifact()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os

VERSION = "0.71.0"


# ⭐ 0.71.0 (dev #750, owner decision C) -- THE PRESENCE ARTIFACT IS RETIRED. Its reviews open as mod panes
# from /jobsearch:review-resume and /jobsearch:review-linkedin (text where a pane cannot be drawn), so
# `views/presence_set.html` and its ledger are re-derivable by construction and the URL file is a LIVE page
# that must be stubbed, not lost. PRESERVE, THEN TRANSFORM:
#
#   1. record the URL in the existing retired-URL drain (data/pending_stubs.jsonl, page `presence_set`);
#      if that FAILS (an unwritable data/), return PENDING and touch NOTHING - removing the generated files
#      first would leave a live URL nobody remembers;
#   2. only after the row is written, remove the two generated files. The URL FILE is retired by the drain
#      itself (`pending_stubs.py --published presence_set`, after a confirmed stub publish), never here.
#
# A profile that never published the page has no URL file: nothing to record, the generated files (if any)
# are removed and the migration is DONE. A URL file whose content is not a URL is recorded loudly as
# `unresolved`, as m_0_34_0 does. Idempotent: `pending_stubs.record()` is keyed by page.
PRESENCE_PAGE = "presence_set"


def m_0_71_0_retire_presence_artifact(profile, apply_it):
    """0.71.0 -- retire the presence artifact (see the block above). Returns (done, message): done is
    False ONLY when the URL could not be preserved, in which case nothing was changed."""
    import pending_stubs as _stubs
    import _tree

    url_path = _tree.path(profile, "presence_set_url")
    url_rel = os.path.relpath(url_path, profile)
    generated = [_tree.path(profile, "presence_set"), _tree.path(profile, "presence_set_ledger")]
    present = [g for g in generated if os.path.exists(g)]
    content, have_url = "", os.path.exists(url_path)
    if have_url:
        try:
            with open(url_path, encoding="utf-8") as fh:
                content = fh.read().strip()
        except OSError as e:
            content = ""
            have_url = False
            unread = "url file unreadable (%s)" % e
        else:
            unread = ""
    else:
        unread = ""
    if not (present or have_url or unread):
        return True, ("  presence artifact (0.71.0): nothing to retire - no page, ledger or url file "
                      "(a page that never published has nothing to stub)")
    ok_url = content.startswith(("http://", "https://"))
    recorded = False
    if have_url or unread:
        if unread:
            return False, ("  \u26a0\ufe0f presence artifact (0.71.0): PENDING - %s; nothing was removed. "
                           "Fix the file, then re-run." % unread)
        if apply_it:
            try:
                recorded = _stubs.record(profile, PRESENCE_PAGE, url_rel, content if ok_url else "",
                                         state="pending" if ok_url else "unresolved")
            except (OSError, ValueError) as e:
                return False, ("  \u26a0\ufe0f presence artifact (0.71.0): PENDING - the URL could not be "
                               "preserved in data/pending_stubs.jsonl (%s); nothing was removed, so the "
                               "live URL is not lost. Fix the cause, then re-run." % e)
        else:
            recorded = True
    removed = []
    for g in present:
        if apply_it:
            try:
                os.unlink(g)
            except OSError as e:
                return False, ("  \u26a0\ufe0f presence artifact (0.71.0): PENDING - %s could not be removed "
                               "(%s); the URL row is already preserved" % (os.path.relpath(g, profile), e))
        removed.append(os.path.relpath(g, profile))
    bits = []
    if have_url:
        bits.append("the page URL %s (the drain publishes the 'retired' stub; the url file is kept until "
                    "that publish is CONFIRMED)" % ("recorded as a pending stub" if recorded and ok_url
                                                    else "was already recorded" if ok_url
                                                    else "did not parse as a URL and is recorded LOUDLY as "
                                                         "unresolved"))
    if removed:
        bits.append("removed %d re-derivable generated file(s): %s" % (len(removed), ", ".join(removed)))
    prefix = "  \u2705 presence artifact retired (0.71.0): " if apply_it \
        else "  would retire the presence artifact (0.71.0): "
    return True, prefix + "; ".join(bits)
