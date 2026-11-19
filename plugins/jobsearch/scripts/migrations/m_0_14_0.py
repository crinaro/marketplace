"""Migration 0.14.0: `m_0_14_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.14.0"


def m_0_14_0(profile, apply_it):
    """0.14.0 — `access` states the REQUIREMENT; the mechanism moves to config.

    Channel records carried values like `login-chrome`, which fused what a channel NEEDS
    (a signed-in session) with how we happened to reach it in 2026 (the Chrome extension).
    The in-app Browser pane and dedicated site plugins both arrived later, so the mechanism
    had to change and every record naming one became wrong at once.

    Rewrites the legacy values in place and seeds `config.sourcing.route_preference` if the
    profile has none. Resolution lives in `route.py`; nothing here decides a mechanism.
    """
    import route as _route
    cpath = os.path.join(profile, "data", "channels.jsonl")
    cfgpath = os.path.join(profile, "config.json")
    if not os.path.exists(cpath):
        return True, ""

    rows, changed = [], 0
    try:
        with open(cpath, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                raw = row.get("access")
                if raw in _route.LEGACY:
                    row["access"] = _route.LEGACY[raw]
                    changed += 1
                rows.append(row)
    except Exception as e:
        return False, "  ⚠️ channels.jsonl could not be read, so routes were left alone: %s" % e

    seed = False
    cfg = {}
    if os.path.exists(cfgpath):
        try:
            with open(cfgpath, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception as e:
            return False, "  ⚠️ config.json is unreadable, so routes were left alone: %s" % e
        seed = not ((cfg.get("sourcing") or {}).get("route_preference"))

    if not changed and not seed:
        return True, ""
    if not apply_it:
        return True, ("  would rewrite %d legacy channel access value(s)%s"
                      % (changed, " and seed config.sourcing.route_preference" if seed else ""))

    if changed:
        tmp = cpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, cpath)          # atomic: never a half-written pipeline file
    if seed:
        cfg.setdefault("sourcing", {})["route_preference"] = list(_route.DEFAULT_PREFERENCE)
        cfg["sourcing"].setdefault("plugins", {})
        tmp = cfgpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, cfgpath)
    bits = []
    if changed:
        bits.append("%d channel access value(s) now state the requirement, not the mechanism"
                    % changed)
    if seed:
        bits.append("config.sourcing.route_preference seeded to %s"
                    % " -> ".join(_route.DEFAULT_PREFERENCE))
    return True, "  ✅ " + "; ".join(bits)
