"""`config.json` helpers two or more migrations share: load, rewrite, merge lists.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""

import json
import os


def _load_config(profile):
    """(path, cfg, error) — cfg is None when the file is absent (error None) or unreadable."""
    path = os.path.join(profile, "config.json")
    if not os.path.exists(path):
        return path, None, None
    try:
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh), None
    except Exception as e:                      # noqa: BLE001 — reported, never raised
        return path, None, e


def _rewrite_config(path, cfg):
    """Key order preserved (json.load keeps it) so the owner's diff is the change and nothing
    else; indent=2 is what init_profile.py writes."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)               # atomic: never a half-written config.json


def _merge_lists(keep, extra):
    """`keep` first, then every item of `extra` not already present. Order kept, nothing dropped."""
    out = list(keep)
    for x in extra:
        if x not in out:
            out.append(x)
    return out
