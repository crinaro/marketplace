"""Where the profile and the engine are, for every `recording/` module: the one owner of `ROOT` and `DATA`.

Capability module of `record.py`. `record.py` resolved `ROOT = _profile_root()` and `DATA` at import; a package
module may not do that work at import (design §3.2), so `record.py` calls `bind(_profile_root())` at its own
import, at the same moment as before, and every reader reads `paths.ROOT` / `paths.DATA` as an attribute of this
module (design §9.3: shared state stays in one module). A test points the write API at a scratch profile with
`bind(root)`. `ENGINE_SCRIPTS` is the scripts directory, one level above this package: the value `record.py`'s
own `ENGINE_SCRIPTS` had."""

import os

ENGINE_SCRIPTS = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# `record.py` itself, spelled as `os.path.abspath(__file__)` spelled it inside `record.py` (the sightings append
# re-runs the CLI on itself).
RECORD_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "record.py")

ROOT = None
DATA = None


def bind(root):
    """Point every `recording/` module at the profile `root` (its `data/` directory is `DATA`)."""
    global ROOT, DATA
    ROOT = root
    DATA = os.path.join(root, "data")
