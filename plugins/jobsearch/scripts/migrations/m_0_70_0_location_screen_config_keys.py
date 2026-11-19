"""Migration 0.70.0: `m_0_70_0_location_screen_config_keys()`, whose own docstring says what it does and why.

One module per registered migration (design-component-segmentation.md §5): listed in `registry.py`, moved out of
`migrate.py` unedited by S2, frozen once released (§5.5)."""

import os
import shutil
from migrations.support_config import _load_config, _rewrite_config

VERSION = "0.70.0"


# ⭐⭐ KEYED "0.70.0" -- 0.69.0 is the newest jobsearch release at the branch base (plugin.json read
# 0.69.0 on base b1dbf40; the 0.69.0 cut landed as PR #731). A profile that installed 0.69.0 is
# stamped exactly "0.69.0", and pending_for()'s strict `<` fires a migration keyed to "0.70.0".
# Re-verify when 0.70.0 is actually cut (dev #729 / public #157). It runs LAST: it reads and writes
# only config.json.
LOCATION_SCREEN_PRE_COPY = "config.json.pre-0.70.0"


def m_0_70_0_location_screen_config_keys(profile, apply_it):
    """0.70.0 -- the location screen's one registered key (design-location-screen.md R2, owner
    decision OD-2 of 2026-10-19; dev #729 / public #157).

    Seeds `geography.relocation.keep_outside_radius` = false WHERE ABSENT and never over a value
    already there (`config_keys.LOCATION_SCREEN_SEEDED`; the `m_0_67_0` precedent: a registered key
    is seeded so the owner's file shows it). False is the behaviour change the release makes: with
    `relocation.open` true, an onsite role proven beyond every commute anchor is now removed as
    `outside-radius` unless it names an affirmative destination or this key is true. The seed
    makes that one-key way back visible.

    A profile with NO `geography` section is left alone: seeding one would turn the geography
    rule's "unknown" (a missing section, loudly) into a screen with a half-empty section. A
    `geography.relocation` that is not an object is left alone and reported, never replaced; an
    absent one is created holding only this key, which changes nothing (`open` is false when absent
    either way).

    ⭐ PRESERVE, THEN TRANSFORM, THEN QUERY. Before the first write `config.json` is copied
    byte-for-byte to `config.json.pre-0.70.0` (unless that copy exists); a failed copy writes
    nothing. The success condition -- the key now readable from disk -- is RE-READ rather than
    assumed. A MISSING or unreadable `config.json` returns PENDING (False), never a false "0 done".
    Idempotent: a second run finds the key and says nothing."""
    import config_keys as _ck
    path, cfg, err = _load_config(profile)
    if cfg is None:
        if err is None:
            return False, ("  ⏳ 0.70.0 PENDING -- %s does not exist yet, so the location-screen "
                           "key cannot be seeded; offered again next session." % path)
        return False, ("  ⏳ 0.70.0 PENDING -- config.json is unreadable, so nothing was "
                       "seeded: %s" % err)
    if not isinstance(cfg, dict):
        return False, "  ⏳ 0.70.0 PENDING -- config.json is not a JSON object; nothing seeded."

    def walk(tree, parts):
        """The node at `parts` below `tree`, or None if any step is absent or not an object."""
        node = tree
        for part in parts:
            node = node.get(part) if isinstance(node, dict) else None
        return node

    lines, to_seed, blocked = [], [], []
    for parts, key, default in _ck.LOCATION_SCREEN_SEEDED:
        label = ".".join(parts + (key,))
        node, why = cfg, None
        for i, part in enumerate(parts):
            nxt = node.get(part)
            if nxt is None:
                if i == 0:
                    why = ("no %s section, so geography is still reported unknown; nothing to "
                           "seed into" % part)
                else:
                    node = None         # an absent inner object is created when the key is written
                break
            if not isinstance(nxt, dict):
                why = "%s is %s, not an object" % (".".join(parts[:i + 1]), type(nxt).__name__)
                break
            node = nxt
        if why:
            blocked.append("%s (%s)" % (label, why))
        elif node is None or key not in node:
            to_seed.append((parts, key, default))
    if blocked:
        lines.append("  ⚠️ left alone: %s" % "; ".join(blocked))
    if to_seed:
        label = ", ".join("%s=%r" % (".".join(parts + (key,)), default)
                          for parts, key, default in to_seed)
        if not apply_it:
            lines.append("  would seed (0.70.0) config.json: %s" % label)
        else:
            copy_path = os.path.join(profile, LOCATION_SCREEN_PRE_COPY)
            if not os.path.exists(copy_path):
                try:
                    shutil.copy2(path, copy_path)
                except (OSError, shutil.Error) as e:
                    return False, ("  ⚠️ config.json could not be preserved to %s (%s), so "
                                   "NOTHING was seeded." % (LOCATION_SCREEN_PRE_COPY, e))
            for parts, key, default in to_seed:
                node = cfg
                for part in parts:
                    node = node.setdefault(part, {})
                node[key] = default
            _rewrite_config(path, cfg)
            lines.append("  ✅ config.json (0.70.0) -- seeded %s (the original is kept at %s)"
                         % (label, LOCATION_SCREEN_PRE_COPY))
            # QUERY: the success condition is what the disk says now, not what was just written.
            _p, after, _e = _load_config(profile)
            missing = [(parts, key) for parts, key, _d in to_seed
                       if not isinstance(walk(after, parts), dict)
                       or key not in walk(after, parts)]
            if missing:
                return False, "\n".join(lines + [
                    "  ⏳ 0.70.0 PENDING -- %s still absent after the write; offered again next "
                    "session." % ", ".join(".".join(p + (k,)) for p, k in missing)])
    return True, "\n".join(lines)
