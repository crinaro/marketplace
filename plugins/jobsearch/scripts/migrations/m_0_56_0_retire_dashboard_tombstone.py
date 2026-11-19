"""Migration 0.56.0: `m_0_56_0_retire_dashboard_tombstone()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil

VERSION = "0.56.0"


# The two phrases the engine's OWN retired stub always carried, in every version of it that
# ever shipped (dev #233 through 0.54.0). Used only to tell that stub apart from a
# `dashboard.html` a candidate wrote themselves, so the summary can say which it moved — the
# move itself is lossless either way, so recognition changes the MESSAGE, never the outcome.
_TOMBSTONE_MARKERS = ("This local copy is retired", "Dashboard has moved")


def m_0_56_0_retire_dashboard_tombstone(profile, apply_it):
    """0.56.0 — dev #546 / public #126: the root `dashboard.html` tombstone is retired the way
    the rulebook says everything is retired — a MOVE to `archive/retired-trackers/`.

    `generate_dashboard.py` wrote a constant stub to that path unconditionally on every run,
    and `_tree.py` listed it as a canonical root entry, so the file was the standing exception
    to the profile's own retirement rule ("a MOVE to archive/retired-trackers/, never a note").
    The effect the reporter hit: deleting it was futile, because the next scheduled run
    recreated it. Worse, a profile created after the 2026-08-29 collapse got a note announcing
    that its local dashboard copy was retired when it had never had one.

    The generator no longer writes it (same release), so this only has to clear what is
    already on disk — and once it has, nothing recreates it.

    ⭐ PRESERVE, THEN TRANSFORM. The file is MOVED, never deleted, even when it is byte-for-byte
    the engine's own stub: a move costs nothing, and the one thing worse than an immortal
    tombstone is silently deleting a file a candidate wrote by hand at the same path. A
    destination that already exists is not overwritten — the root copy is left and named, the
    same rule m_0_56_0_resumes_to_presence follows.

    SAFE: idempotent (a second run finds no root `dashboard.html`), and reversible by hand from
    `archive/retired-trackers/`. A profile that never had the file is a clean no-op.
    """
    old = os.path.join(profile, "dashboard.html")
    if not os.path.exists(old):
        return True, ""

    import _tree
    # The destination comes from the table `audit()` classifies against, so the migration and
    # the audit cannot disagree about where a retired root file goes (_tree.py's own rule).
    rel_dest = _tree.RETIRED_TO["dashboard.html"]
    new = os.path.join(profile, rel_dest)

    try:
        with open(old, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        return False, ("  ⚠️ root dashboard.html exists but cannot be read (%s). Left "
                       "untouched." % e)
    is_engine_stub = any(m in text for m in _TOMBSTONE_MARKERS)
    what = ("the engine's own retired tombstone stub" if is_engine_stub
            else "a root dashboard.html this profile carries that is NOT the engine's stub")

    if os.path.exists(new):
        if not apply_it:
            return True, ("  would leave root dashboard.html alone — %s already exists"
                          % rel_dest)
        return True, ("  ⚠️ root dashboard.html LEFT in place: %s already exists, and this "
                      "migration never overwrites an archived file. Compare the two and "
                      "delete the root copy yourself once you have." % rel_dest)

    if not apply_it:
        return True, "  would move root dashboard.html to %s (%s)" % (rel_dest, what)

    try:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        shutil.move(old, new)
    except (OSError, shutil.Error) as e:
        return False, ("  ⚠️ root dashboard.html could not be moved to %s (%s). Left "
                       "untouched — nothing was lost." % (rel_dest, e))
    return True, ("  retired root dashboard.html -> %s (%s). The generator no longer writes "
                  "it, so it will not come back." % (rel_dest, what))
