"""Migration 0.56.0: `m_0_56_0_resumes_to_presence()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil

VERSION = "0.56.0"


def m_0_56_0_resumes_to_presence(profile, apply_it):
    """0.56.0 — dev #545 / public #127: the rendered-resume directory moves from a bare root
    `resumes/` to `presence/resumes`, the location `_tree.LAYOUT` now declares for it.

    `variant_out.py`'s shipped default wrote to root, which `_tree.py --audit` classified as
    UNKNOWN — the `nonexistent/` class, the one finding that fails its exit code. So the
    engine's own default tripped the engine's own layout audit the moment a resume was
    rendered, and the only escape was overriding `local_dir` in config.json. The default was
    the thing that was wrong: root holds ANCHORS (profile markers, external pointer targets),
    and a rendered-output directory is none of those.

    ⭐ PRESERVE, THEN TRANSFORM. Nothing is deleted and nothing is overwritten:
      - no root `resumes/` at all is a clean no-op (a profile that never rendered one, and
        every profile created after this ships);
      - no `presence/resumes` yet means the whole directory MOVES, contents intact;
      - both present means each entry moves individually and a same-name collision is LEFT
        WHERE IT IS and named in the summary, never clobbered — a rendered resume is a
        document the candidate may have already sent, so the safe side is obvious;
      - an emptied root `resumes/` is removed, because an empty directory it left behind
        would audit as UNMIGRATED forever and keep telling every session a move is pending.

    SAFE: idempotent (a second run finds no root `resumes/` and does nothing) and reversible
    by hand — the files are moved, not rewritten. `_tree.path()`'s legacy fallback means a
    profile this has not reached yet keeps rendering to, and reading from, the old location,
    so nothing depends on this having run.
    """
    old = os.path.join(profile, "resumes")
    new = os.path.join(profile, "presence", "resumes")
    if not os.path.isdir(old):
        return True, ""

    entries = sorted(os.listdir(old))
    if not entries:
        if not apply_it:
            return True, "  would remove the empty root resumes/ (nothing to move)"
        try:
            os.rmdir(old)
        except OSError as e:
            return False, "  ⚠️ empty root resumes/ could not be removed (%s)." % e
        return True, "  removed the empty root resumes/ — nothing was in it"

    if not apply_it:
        collisions = [n for n in entries if os.path.exists(os.path.join(new, n))]
        note = ("" if not collisions else
                " (%d name(s) already present at the destination would be LEFT at root: %s)"
                % (len(collisions), ", ".join(collisions[:4])))
        return True, ("  would move %d rendered resume(s) from resumes/ to presence/resumes/%s"
                      % (len(entries), note))

    try:
        os.makedirs(new, exist_ok=True)
    except OSError as e:
        return False, ("  ⚠️ presence/resumes could not be created (%s). Root resumes/ is "
                       "untouched." % e)

    moved, left = [], []
    for n in entries:
        src, dst = os.path.join(old, n), os.path.join(new, n)
        if os.path.exists(dst):
            left.append(n)
            continue
        try:
            shutil.move(src, dst)
        except (OSError, shutil.Error) as e:
            left.append("%s (%s)" % (n, e))
            continue
        moved.append(n)

    removed = False
    if not os.listdir(old):
        try:
            os.rmdir(old)
            removed = True
        except OSError:
            pass

    msg = "  moved %d rendered resume(s) to presence/resumes/" % len(moved)
    if removed:
        msg += "; root resumes/ removed"
    if left:
        msg += ("\n  ⚠️ %d LEFT at root because the destination already has that name — "
                "compare them by hand, then delete the duplicate you do not want: %s"
                % (len(left), ", ".join(left[:6])))
    return True, msg
