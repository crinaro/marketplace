"""posture_cfg: read the active posture from a profile's `config.json`, as `(name, posture, err)`.

The body of `posture.load`, moved unchanged except that the root is an argument
(design-presence-report.md §11 B0): `posture.load` reads its module's `ROOT` and delegates here, so a
capability module (`presence/gaps.py`) can tell "not granted" from "unreadable" without importing the
`posture.py` entry point. It lives here, not in `recording/` as §11 names: a second importer of `recording/`
makes that package a node of its own and the jobsearch G6 cycle grows 39 -> 40 (the reason B0 took `pursuits/`).
It reads one file and writes nothing."""

import json
import os


def read(root):
    path = os.path.join(root, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        return None, None, "cannot read config.json (%s)" % e
    search = cfg.get("search") or {}
    name = search.get("posture")
    postures = search.get("postures") or {}
    if not name:
        return None, None, "config.search.posture is unset"
    if name not in postures:
        # A named posture with no definition is worse than none: the run cannot tell whether it
        # is permitted to do anything, and the safe reading is the cheapest one.
        return name, None, ("posture %r is not defined in config.search.postures (have: %s)"
                            % (name, ", ".join(sorted(postures)) or "none"))
    return name, postures[name], None
