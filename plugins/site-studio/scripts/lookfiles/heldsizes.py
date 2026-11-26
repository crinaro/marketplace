"""lookfiles/heldsizes.py -- the sizes a derived look's picture parts gain under `images: {"sizes": "held"}` (site-studio 0.10.0;
design-publish-preflight section 3.3; group `publish-preflight`; dev 1068).

A look derived from pages whose pictures carried no size has `image` parts such as `<img src="{{src}}" alt="{{alt}}" loading="lazy">`: the
table of the `sized` parts has `width` and `height` slots and the markup uses neither. `complete` adds, to such a part and to the per-place
picture parts (`card.image`, `home-showcase.image`, `steps-view.image`) built the same way, the three attributes the held sheet needs:

    data-ss-held width="{{width}}" height="{{height}}"

`data-ss-held` is what `templates/output/site-studio/held.css` selects (it is why a hand `<img width=64>` is never reached), and the build
links that sheet only on a page that prints one. NEVER `srcset` (section 3.1: it changes 54 of 144 layouts and no rule undoes that); a
site that wants one writes its own part. A part is left as it is when it holds a `{{width}}` or `{{height}}` slot, or a literal `width` or
`height` attribute on an `<img>`: the person's own sizes, or an earlier run of this function (so `complete` is idempotent). A part whose
table has no `width` and `height` (`image.plain`, `image.plain-pos`) never gains them, and neither does `block-image` (an image inside a
plugin block: block images are never touched).

PURE: text in, text out. It reads no tree and writes no file; the caller (S7: `adoption/settings.py`, before `lookwrite.carry`, so the stamp
covers the completed text) says when. A look the person wrote (`local.json`) is never passed to it. Imports `lookgrammar.constructs` only."""

import json
import re

from lookgrammar.constructs import CONSTRUCTS, PLACE_PARTS

HELD_ATTR = "data-ss-held"
SIZES = 'width="{{width}}" height="{{height}}"'
ATTRS = HELD_ATTR + " " + SIZES
_IMG = re.compile(r"<img\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_SIZE_SLOT = re.compile(r"\{\{\s*(?:width|height)\s*\}\}")
_SIZE_ATTR = re.compile(r"\s(?:width|height)(?=[\s=/>])", re.I)
_HELD = re.compile(r"\sdata-ss-held(?![\w:.-])", re.I)


def picture_parts():
    """[(construct, part)] whose markup is one picture of the site-wide `image` construct, and whose table holds `width` and `height`: the
    `image` construct's own parts, and the per-place parts whose site-wide part is one of them (`PLACE_PARTS`). Read from the tables, in
    sorted order; `block-image` is not among them."""
    found = [("image", part) for part, table in CONSTRUCTS["image"]["parts"].items()]
    found += [place for place, (site_wide, _part) in PLACE_PARTS.items() if site_wide == "image"]
    return sorted(p for p in found if {"width", "height"} <= set(CONSTRUCTS[p[0]]["parts"][p[1]]))


def wants_sizes(markup):
    """True when `markup` (one part) holds an `<img>` and no size of any kind: no `{{width}}` or `{{height}}` slot anywhere and no
    `width` or `height` attribute on an `<img>`."""
    tags = [m.group(0) for m in _IMG.finditer(markup)]
    if not tags or _SIZE_SLOT.search(markup):
        return False
    return not any(_SIZE_ATTR.search(_QUOTED.sub('""', tag)) for tag in tags)


def complete_part(markup):
    """`markup` with `data-ss-held width="{{width}}" height="{{height}}"` after the name of each `<img>` tag, or `markup` itself when it
    `wants_sizes` no more. A tag that already holds `data-ss-held` gains the two sizes only."""
    if not wants_sizes(markup):
        return markup

    def add(m):
        tag = m.group(0)
        have = bool(_HELD.search(_QUOTED.sub('""', tag)))
        return tag[:4] + " " + (SIZES if have else ATTRS) + tag[4:]
    return _IMG.sub(add, markup)


def complete_constructs(constructs):
    """(constructs, changed): a copy of `{construct: {part: markup}}` with each picture part completed, and the sorted `[(construct,
    part)]` that changed. The input is not modified."""
    out = dict((cid, dict(parts)) for cid, parts in constructs.items())
    changed = []
    for cid, part in picture_parts():
        markup = out.get(cid, {}).get(part)
        if isinstance(markup, str):
            done = complete_part(markup)
            if done != markup:
                out[cid][part] = done
                changed.append((cid, part))
    return out, changed


def complete(text):
    """(text, changed): the look file `text` (JSON) with its picture parts completed, and the `[(construct, part)]` that changed. With none
    changed the text is returned as it came, byte for byte; else the file is written as derive writes one (`indent=2`, no ASCII escapes,
    one final newline). A text that is not a look object, or has no `constructs` object, is returned unchanged: this function judges no look,
    `looks.parse` does."""
    try:
        data = json.loads(text)
    except ValueError:
        return text, []
    if not isinstance(data, dict) or not isinstance(data.get("constructs"), dict):
        return text, []
    constructs, changed = complete_constructs(data["constructs"])
    if not changed:
        return text, []
    data["constructs"] = constructs
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", changed
