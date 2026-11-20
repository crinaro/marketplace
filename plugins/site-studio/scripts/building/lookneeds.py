"""lookneeds: which release each look file in a tree needs, for the schema check (design-movement-view section 3.4).

`configschema` does not import the look grammar, so the caller that holds a tree computes this and passes it to
`treeschema.schema_5_reasons`, `required_schema`, `check_tree_schema` and `canonical.canonical_text` as `look_needs=`,
as `interpretations` is passed today. The callers that hold a tree: `building/running.py` (the build's schema stage),
`building/raiseschema.py`, `building/listing.py`, `lookfiles/commands.py` (`use` and `derive`), `addresses.py`,
`movepiece/planning.py`, and adopt's conversion (`adoption/convert.py`, design step 5a)."""

import re

import looks

LOOK_PATH_RE = re.compile(r"^site/looks/[a-z0-9][a-z0-9-]*\.json$")
NEWER_THAN_04 = (0, 5, 0)


def _needs(text):
    """The newest release the look `text` needs, as "0.5.0", or None for a look every 0.4.x install reads: `looks.needs`
    (the construct, part, slot, asset kind and decoration tables), kept only when it is newer than 0.4.x."""
    release = looks.needs(text)
    if release and looks.version_tuple(release) >= NEWER_THAN_04:
        return release
    return None


def look_needs(files, needs=None):
    """{repo path: release} for every `site/looks/*.json` in `files` ({repo path: bytes or str}) that needs a release
    newer than 0.4.x: every look in the tree, not only the one `site.json` names. `needs` is the reader of one look's
    text (default `_needs`); a look it answers None for is left out."""
    read = needs or _needs
    out = {}
    for path in sorted(files):
        if not LOOK_PATH_RE.match(path):
            continue
        data = files[path]
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
        release = read(text)
        if release:
            out[path] = release
    return out
