"""Migration 0.13.0: `m_0_13_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.13.0"


def m_0_13_0(profile, apply_it):
    """0.13.0 — the dashboard title becomes DATA, and this preserves the one already in use.

    ⭐ PRESERVE, THEN TRANSFORM. `generate_dashboard.py` used to write a hard-coded title
    naming one person, in three places. It now renders
    `config.dashboard.title_template` × `user.json`'s name, defaulting to a neutral form.

    Left alone, an upgrade would silently rename every existing dashboard. So carry the
    existing title forward — read from the dashboard THIS PROFILE last generated, never from a
    literal in the engine. Copying the string into this file would just move the leak from the
    generator into the migration.

    No dashboard yet, or no title in it: nothing to preserve, and the new default applies.
    """
    import re as _re
    cfg_path = os.path.join(profile, "config.json")
    if not os.path.exists(cfg_path):
        return True, ""
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as e:
        return False, "  ⚠️ config.json is unreadable, so the dashboard title was left alone: %s" % e
    if (cfg.get("dashboard") or {}).get("title_template"):
        return True, ""                      # already carries its own title

    existing = ""
    # dev #233: dashboard.html may be the retired-copy tombstone, whose <title> must
    # never be preserved as the profile's real title — prefer the artifact, skip the stub.
    for candidate in ("dashboard_artifact.html", "dashboard.html"):
        path = os.path.join(profile, candidate)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                m = _re.search(r"<title>(.*?)</title>", fh.read(), _re.S)
            if m and m.group(1).strip() and m.group(1).strip() != "Dashboard has moved":
                existing = m.group(1).strip()
                break
        except Exception:
            continue
    if not existing:
        return True, ""                      # nothing generated yet — the default is correct

    if not apply_it:
        return True, "  would preserve the current dashboard title: %r" % existing
    cfg.setdefault("dashboard", {})["title_template"] = existing
    tmp = cfg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, cfg_path)                # atomic: never a half-written config.json
    return True, "  ✅ config.json — dashboard title preserved as %r" % existing
