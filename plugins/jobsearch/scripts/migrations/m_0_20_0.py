"""Migration 0.20.0: `m_0_20_0()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import json
import os

VERSION = "0.20.0"


def m_0_20_0(profile, apply_it):
    """0.20.0 — a config KEY that names the owner becomes generic (GitHub issue #46).

    `compensation.standout_exception_requires_<owner>` carries the owner's first name in the
    KEY. The rulebook's fixture rule is explicit that only structure crosses over and every
    string is synthesized *because even map keys can be personal data* — and this one reached
    a public repository inside the generated test fixture, where the purity gate could not
    see it: the gate matched VALUES, and `\\b` treats `_` as a word character, so a name
    inside an identifier was invisible to it. Both halves are fixed (#45); this is the data.

    ⭐ PRESERVE, THEN TRANSFORM. The value is carried across before the old key is removed,
    so a profile that had it set to false keeps false. Nothing in the engine reads this key
    today, which is what makes the rename safe rather than a behaviour change.

    Idempotent: a profile already carrying the new key, or neither key, is a no-op.
    """
    path = os.path.join(profile, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return True, ""
    comp = cfg.get("compensation")
    if not isinstance(comp, dict):
        return True, ""
    old = [k for k in comp if k.startswith("standout_exception_requires_")
           and k != "standout_exception_requires_owner"]
    if not old:
        return True, ""
    if not apply_it:
        return True, ("  would rename %d compensation key(s) that name the owner to "
                      "`standout_exception_requires_owner`" % len(old))
    for k in old:
        comp.setdefault("standout_exception_requires_owner", comp[k])
        del comp[k]
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            # ⚠️ ensure_ascii=False. The default escapes every non-ASCII character, so a
            # one-key rename rewrote 74 unrelated lines of a HAND-EDITED file as \uXXXX
            # escapes — a diff its owner cannot review, and characters they typed coming
            # back as escape sequences (#3).
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        return False, "  could not rewrite config.json: %s" % e
    return True, ("  renamed %d compensation key(s) naming the owner to "
                  "`standout_exception_requires_owner`" % len(old))
