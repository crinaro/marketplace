"""Migration 0.4.0: `m_0_4_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import subprocess
import sys
from migrations.paths import HERE

VERSION = "0.4.0"


def m_0_4_0(profile, apply_it):
    """0.4.0 — retire the Process sections that the dashboard no longer renders.

    Delegates to retire_process_sections.py, which refuses when `🔧 Open` still has content.
    That refusal IS the destructive-vs-safe boundary: nothing here forces past it.
    """
    cmd = [sys.executable, os.path.join(HERE, "retire_process_sections.py")]
    if not apply_it:
        cmd.append("--check")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=profile)
    out = (r.stdout or "") + (r.stderr or "")
    if "already clean" in out or "nothing (already clean)" in out:
        return True, ""
    if r.returncode == 0:
        return True, "  ✅ focus.md — retired the Process sections the dashboard no longer renders."
    # The script relocates rather than refusing, so a non-zero here is a genuine failure
    # (unwritable archive, unreadable focus.md) — not a decision waiting on a human.
    return False, ("  ⚠️ focus.md could not be migrated and was left unchanged:\n     %s"
                   % (out.strip().splitlines() or ["unknown error"])[-1][:160])
