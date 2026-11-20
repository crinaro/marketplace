"""fetch_key: the `search.posting_fetch` config key as a tri-state, and its one writer (design-browser-fallback.md 6.3).

Capability module of `posting_fetch.py`, which keeps the setter (`--set on|auto|off`) and re-exports these names.

`key_value` reads the key: `absent` (a readable config object with the key genuinely absent: the automatic fetch), `on`, `off` (NO
fetch, ever: owner ruling D-B, 2026-11-16) or `unreadable` (anything else, a malformed or missing config: NO fetch, and the reason
is returned). FAIL CLOSED: only a readable file with the key absent means automatic."""

import json
import os
import _atomic

KEY = "search.posting_fetch"
KEY_VALUES = ("on", "off")                               # what config.json may hold; `--set auto` REMOVES the key
SET_VALUES = ("on", "auto", "off")                       # what `--set` takes
KEY_DEFAULT = "auto"                                     # an absent key (0.90.0, dev 858): the automatic fetch, inside design 6.1


def key_value(root):
    """`(value, why)` for `search.posting_fetch` in `<root>/config.json` (design-browser-fallback.md 6.3). `value` is

        absent      a readable config object with the key genuinely absent: the automatic fetch, inside design 6.1
        on          the user turned it on
        off         the user turned it off: NO fetch, ever (owner ruling D-B, 2026-11-16: an explicit `off` wins)
        unreadable  anything else (`"ON"`, `true`, `"no"`, null), malformed JSON, a config that is not an object, or no
                    config at all: NO fetch, and `why` names it, so the caller says so

    FAIL CLOSED: only a readable file with the key absent means automatic. `why` is None unless the value is `unreadable`."""
    try:
        with open(os.path.join(root, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        return "unreadable", "config.json missing"
    except (OSError, ValueError) as e:
        return "unreadable", "config.json cannot be read (%s)" % e
    if not isinstance(cfg, dict):
        return "unreadable", "config.json is not a JSON object"
    node, path = cfg, []
    for part in KEY.split("."):
        if not isinstance(node, dict):
            return "unreadable", "%s is not an object, so %s cannot be read" % (".".join(path), KEY)
        if part not in node:
            return "absent", None
        node = node[part]
        path.append(part)
    if node == "on":
        return "on", None
    if node == "off":
        return "off", None
    return "unreadable", "%s is %r, not on or off" % (KEY, node)


def write_key(root, value):
    """Set `search.posting_fetch` in `<root>/config.json`, every other key untouched, atomically; `auto` REMOVES the key (an
    absent key is the automatic fetch). Raises ValueError."""
    if value not in SET_VALUES:
        raise ValueError("%r is not on, auto or off" % (value,))
    path = os.path.join(root, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError("cannot read config.json (%s)" % e)
    if not isinstance(cfg, dict):
        raise ValueError("config.json is not a JSON object")
    search = cfg.get("search") if value == "auto" else cfg.setdefault("search", {})
    if value == "auto":
        if search is not None and not isinstance(search, dict):
            raise ValueError("config.search is not an object")
        if isinstance(search, dict):
            search.pop("posting_fetch", None)
    else:
        if not isinstance(search, dict):
            raise ValueError("config.search is not an object")
        search["posting_fetch"] = value
    _atomic.write_json(path, cfg)
