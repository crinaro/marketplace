"""lookgrammar/needs.py -- the release a look file needs (design-movement-view section 3.4), moved out of `looks.py` by
`split_module.py` (design-adopt-ownership-line section 11 step 1). Python 3.9, standard library only.

    version_tuple(v)        "0.10.0" as (0, 10, 0): releases compare as versions, never as strings
    part_first(c, p)        the release a part needs (`PART_FIRST`, else its construct's `first`)
    slot_release(c, p, s)   the release a slot added to an older part needs (`SLOT_FIRST`, `OPEN_SLOT_FIRST`), else None
    ASSET_FIRST             each asset kind released after 0.3.1, with its release
    release_needs(text, decoration_needs)   the newest release a look file needs

Imports nothing from `looks`, which imports this: the one input that needs the part parser, a decoration
(`lookgrammar/decoration.py`), is read by the caller's `decoration_needs` (`looks.needs` passes `looks._decoration_needs`)."""

import json
import re
from lookgrammar.constructs import CONSTRUCTS, PART_FIRST, OPEN_SLOT_FIRST, PLACE_PARTS, SLOT_FIRST, TOP_KEY_FIRST
from lookgrammar.reads import READS         # imports only `re` and `constructs`: no cycle


_SLOT = re.compile(r"\{\{([^{}]*)\}\}")


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def part_first(construct, part):
    return PART_FIRST.get((construct, part), CONSTRUCTS[construct]["first"])


def slot_release(construct, part, slot):
    """The release a slot added to an older part needs (`SLOT_FIRST`, gated; `OPEN_SLOT_FIRST`, ungated), else None. A
    place part's slot (`PLACE_PARTS`) is the site-wide part's slot, so it needs what that slot needs."""
    construct, part = PLACE_PARTS.get((construct, part), (construct, part))
    row = SLOT_FIRST.get((construct, part, slot))
    return row[0] if row else OPEN_SLOT_FIRST.get((construct, part, slot))


# ------------------------------------------------------------- the release a look needs (design-movement-view 3.4)
# An asset kind first released after 0.3.1 (`css` and `js` are 0.3.1's), with its release.
ASSET_FIRST = {"schema-4": "0.4.0", "schema-5": "0.5.0", "schema-6": "0.6.0"}


def release_needs(look_text, decoration_needs):
    """The newest release the look file `look_text` (its JSON text) needs to be read, as "0.5.0": the newest of the
    `first` of every construct it names, every part it writes (`part_first`, `PART_FIRST`), every slot it places that
    `SLOT_FIRST` gates or `OPEN_SLOT_FIRST` adds (`slot_release`), every asset kind it links (`ASSET_FIRST`), every
    top-level key it holds that `TOP_KEY_FIRST` names (0.7.0: `reads`, `named`; the key, whatever it holds), every target
    its `reads` names that the table knows (`READS[target]["first"]`: 0.7.0 for the nine, 0.8.0 for the five of 0.8.0; 0.8.0
    reads each target's own release, where 0.7.0 counted `reads` as needing 0.7.0 whatever it held) and every
    decoration it holds (`decoration_needs`, called with {construct id: {part: markup}} of the known parts: `looks`
    passes `_decoration_needs`).
    None for a look that names nothing, or that is not a look at all (`parse` refuses that with its own line). A name
    this release does not know is left to `parse`, which refuses it as unknown. The schema check reads this through
    `building.lookneeds`, because `configschema` does not import the look grammar."""
    try:
        data = json.loads(look_text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    found, clean = [TOP_KEY_FIRST[k] for k in sorted(data) if k in TOP_KEY_FIRST], {}
    reads = data.get("reads")
    for target in (sorted(reads) if isinstance(reads, dict) else ()):
        if target in READS:
            found.append(READS[target]["first"])
    constructs = data.get("constructs")
    for cid, parts in (constructs.items() if isinstance(constructs, dict) else ()):
        if cid not in CONSTRUCTS or not isinstance(parts, dict):
            continue
        found.append(CONSTRUCTS[cid]["first"])
        clean[cid] = {}
        for pn, text in parts.items():
            if pn not in CONSTRUCTS[cid]["parts"] or not isinstance(text, str):
                continue
            clean[cid][pn] = text
            found.append(part_first(cid, pn))
            found.extend(r for r in (slot_release(cid, pn, m.group(1)) for m in _SLOT.finditer(text)) if r)
    assets = data.get("assets")
    for kinds in (assets.values() if isinstance(assets, dict) else ()):
        found.extend(ASSET_FIRST[k] for k in (kinds if isinstance(kinds, list) else ())
                     if isinstance(k, str) and k in ASSET_FIRST)
    decoration = decoration_needs(clean)
    if decoration:
        found.append(decoration)
    return max(found, key=version_tuple) if found else None
