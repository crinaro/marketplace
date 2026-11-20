"""lookgrammar/constructs.py -- the look grammar's closed tables, as data (design-template-fidelity R5, #909).
Python 3.9, standard library only. Imports nothing.

Moved out of `looks.py` unchanged by `split_module.py` (design-movement-view section 10 step 1), so the
renderer and validator there can grow without the tables. `looks` re-exports every name below; the tables
are the same objects whichever module a caller reads them from.

    SLOT_KINDS          the eight slot kinds (`looks.py`'s docstring says what each one accepts)
    ASSET_KINDS         the plugin output files a look's `assets` may keep linked
    CONSTRUCTS          construct id -> {"first": release, "parts": part -> slot name -> slot kind}
    PART_FIRST          a part added to a construct that already existed, with its release
    SLOT_FIRST          a GATED slot added to a part that already existed (rule L3a), with its release and the
                        schema-N trigger without which the build fills it with ""
    OPEN_SLOT_FIRST     an UNGATED slot added to a part that already existed, with its release: always filled, so no
                        default-look part holds it (design-movement-view step G, O4a `fullTitle`)
    OPTIONAL_PARTS      parts the default look has no entry for: rendered only where the site's own look writes one, else
                        the place renders as it did before the part existed (step G, O2 and O3)
    TEXT_ONLY_PARTS     parts that are literal text only: no slot, no element (step G, O2 `steps-view.role-sep`)
    ALLOWED_ELEMENTS, VOID_ELEMENTS, IFRAME_PARTS, ELEMENT_REFUSALS
                        the element allowlist and the refusals that get a line of their own
    GLOBAL_ATTRS, ELEMENT_ATTRS, NAMED_REFUSED_ATTRS, STYLE_FORM, URL_ATTRS, SCRIPT_READ_ATTRS, CLOSED_VALUES
                        the attribute allowlist, its named refusals and the closed attribute values

The slot-kind constants live here, not in `looks`, because the construct table is written in them and
`looks` imports this module: defining them there would make an import cycle.

Every table is a literal, so importing this module runs no code (segmentation rule G3). In `looks.py` the
construct table was built by calling `_c(first, **parts)`, which spells a hyphenated part name with an
underscore, and ALLOWED_ELEMENTS by splitting one string; the move wrote out the values those built (checked
equal, in order, to the tables `looks.py` built before the move). A part name here is written with its hyphen.
`_c` stays, unchanged, for the tests that plant a row with it; the table itself no longer calls it.
"""


TEXT, HTML, URL, SRCSET, POSITION, INT, EMBED, CONTACT = (
    "text", "html", "url", "srcset", "position", "int", "embed", "contact")
SLOT_KINDS = (TEXT, HTML, URL, SRCSET, POSITION, INT, EMBED, CONTACT)

# The plugin's own output files a look's `assets` may keep linked (R5.2). `css` and `js` are 0.3.1's
# `site-studio/blocks.css` and `site-studio/video.js`; `schema-4` is 0.4.0's `site-studio/schema-4.css`; `schema-5` is
# 0.5.0's `site-studio/schema-5.css`, linked only by the five 0.5.0 constructs (design-movement-view section 4.2).
ASSET_KINDS = ("css", "js", "schema-4", "schema-5")


# --------------------------------------------------------------------------------- the construct table
# Written from the code at the `site-studio--v0.3.1` tag (every markup site it has) and from the design's
# sections 3 and 8 (every construct 0.4.0 adds). `first` is the release that introduced the construct;
# PART_FIRST names a part added later to a construct that already existed. A construct a look omits renders
# with the default look's entry. Not expressible, stated: first/last/odd/even classes and any wrapper that
# depends on a value the plugin does not expose as a slot (derive reports such a construct `unmapped`).

def _c(first, **parts):
    # keyword names cannot hold a hyphen, so a part named `item-current` is spelled `item_current` here
    return {"first": first, "parts": dict((k.replace("_", "-"), v) for k, v in parts.items())}


# The slots of the site-wide `image` construct's largest part, which a per-place picture part (`steps-view.image`,
# `home-showcase.image`; step G, O3) takes: the build fills those the picture has, and an attribute holding a slot the
# picture has none for is left out, as the site-wide construct's smaller parts leave it out.
PLACE_IMAGE_SLOTS = {"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET, "sizes": TEXT,
                     "focus": POSITION}

CONSTRUCTS = {
    # ---- 0.3.1: every construct its code builds (content.py `_Renderer`, build.py `_Builder`)
    "tagline": {"first": "0.3.1", "parts": {"wrap": {"text": TEXT}}},
    "tiles": {"first": "0.3.1", "parts": {"wrap": {"items": HTML, "label": TEXT, "count": INT},
        "item": {"figure": TEXT, "text": TEXT, "n": INT}}},
    "quote": {"first": "0.3.1", "parts": {"wrap": {"body": HTML, "by": HTML}, "by": {"who": HTML}}},
    "gallery": {"first": "0.3.1", "parts": {"wrap": {"items": HTML, "count": INT},
        "wrap-labelled": {"items": HTML, "count": INT, "label": TEXT}, "item": {"image": HTML, "caption": HTML},
        "caption": {"text": TEXT}}},
    "videos": {"first": "0.3.1", "parts": {"wrap": {"items": HTML},
        "wrap-labelled": {"items": HTML, "label": TEXT},
        "item-poster": {"url": URL, "embed": EMBED, "image": HTML, "title": TEXT, "kind": TEXT},
        "item": {"url": URL, "embed": EMBED, "title": TEXT, "host": TEXT, "kind": TEXT}}},
    "carousel": {"first": "0.3.1", "parts": {"wrap": {"items": HTML, "label": TEXT}, "item": {"body": HTML}}},
    "video-embed": {"first": "0.3.1", "parts": {"wrap": {"embed": EMBED}}},
    "figure": {"first": "0.3.1", "parts": {"wrap": {"image": HTML, "caption": HTML}, "caption": {"text": TEXT}}},
    "image": {"first": "0.3.1", "parts": {"plain": {"src": URL, "alt": TEXT},
        "sized": {"src": URL, "alt": TEXT, "width": INT, "height": INT},
        "sized-set": {"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET, "sizes": TEXT},
        "plain-pos": {"src": URL, "alt": TEXT, "focus": POSITION},
        "sized-pos": {"src": URL, "alt": TEXT, "width": INT, "height": INT, "focus": POSITION},
        "sized-set-pos": {"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET, "sizes": TEXT,
            "focus": POSITION}}},
    "block-image": {"first": "0.3.1", "parts": {"plain": {"src": URL, "alt": TEXT},
        "sized": {"src": URL, "alt": TEXT, "width": INT, "height": INT},
        "sized-set": {"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET, "sizes": TEXT}}},
    "reference-card": {"first": "0.3.1", "parts": {
        "wrap": {"url": URL, "image": HTML, "title": TEXT, "site": HTML, "description": HTML, "role": HTML},
        "site": {"text": TEXT}, "description": {"text": TEXT}, "role": {"text": TEXT}}},
    "reference-grid": {"first": "0.3.1", "parts": {"wrap": {"items": HTML}}},
    "card": {"first": "0.3.1", "parts": {
        "wrap": {"url": URL, "image": HTML, "title": TEXT, "teaser": HTML, "meta": HTML, "number": HTML,
            "kicker": HTML, "fullTitle": TEXT},
        "teaser": {"text": TEXT}, "meta": {"text": TEXT}, "number": {"n": INT}}},
    "cards": {"first": "0.3.1", "parts": {"wrap": {"items": HTML}}},
    "group": {"first": "0.3.1", "parts": {"wrap": {"title": TEXT, "cards": HTML}}},
    "portfolio": {"first": "0.3.1", "parts": {
        "wrap": {"title": TEXT, "tagline": HTML, "intro": HTML, "cards": HTML, "slug": TEXT}}},
    "piece": {"first": "0.3.1", "parts": {
        "wrap": {"title": TEXT, "meta": HTML, "body": HTML, "back": HTML, "slug": TEXT, "portfolio": TEXT,
            "group": TEXT, "link": HTML, "teaser": HTML}}},
    "meta-list": {"first": "0.3.1", "parts": {"wrap": {"items": HTML}, "item": {"name": TEXT, "value": TEXT}}},
    "nav": {"first": "0.3.1", "parts": {"wrap": {"items": HTML}, "item": {"url": URL, "label": TEXT},
        "item-current": {"url": URL, "label": TEXT}, "link": {"url": URL, "label": TEXT},
        "link-current": {"url": URL, "label": TEXT}}},
    "contact": {"first": "0.3.1", "parts": {"wrap": {"items": HTML}, "heading": {},
        "item-mail": {"label": TEXT, "href": CONTACT, "text": TEXT},
        "item-link": {"label": TEXT, "url": URL, "text": TEXT}, "item-text": {"label": TEXT, "text": TEXT}}},
    "photo": {"first": "0.3.1", "parts": {"wrap": {"image": HTML}}},
    "endorsement": {"first": "0.3.1", "parts": {"wrap": {"quote": TEXT, "by": HTML}, "by": {"who": TEXT}}},
    "feed": {"first": "0.3.1", "parts": {"wrap": {"grid": HTML}}},
    "home": {"first": "0.3.1", "parts": {"wrap": {"title": TEXT, "body": HTML, "eyebrow": HTML, "role": HTML},
        "intro": {"photo": HTML, "intro": HTML, "endorsement": HTML}, "featured": {"cards": HTML},
        "eyebrow": {"text": TEXT}, "role": {"text": TEXT}}},
    "about": {"first": "0.3.1", "parts": {
        "wrap": {"title": TEXT, "photo": HTML, "intro": HTML, "endorsement": HTML, "contact": HTML}}},
    "resume": {"first": "0.3.1", "parts": {
        "wrap": {"title": TEXT, "download": HTML, "body": HTML, "contact": HTML, "links": HTML},
        "download": {"url": URL}}},
    # ---- 0.4.0: constructs new in this release (their default entries and code arrive with steps 1.3 to 1.5)
    "quotes": {"first": "0.4.0", "parts": {"wrap": {"items": HTML, "label": TEXT, "count": INT},
        "item": {"body": HTML, "by": HTML}, "by": {"who": HTML}}},
    "gallery-video": {"first": "0.4.0", "parts": {
        "item": {"url": URL, "embed": EMBED, "image": HTML, "title": TEXT, "caption": HTML},
        "caption": {"text": TEXT, "url": URL, "embed": EMBED, "title": TEXT}}},
    "back-link": {"first": "0.4.0", "parts": {"wrap": {"url": URL, "label": TEXT}}},
    "resume-role": {"first": "0.4.0", "parts": {"wrap": {"role": HTML, "org": HTML, "body": HTML},
        "wrap-bare": {"role": HTML, "body": HTML}}},
    "roles-view": {"first": "0.4.0", "parts": {"wrap": {"items": HTML},
        "item": {"heading": HTML, "url": URL, "titles": TEXT, "period": TEXT, "previously": HTML, "employer": TEXT,
            "image": HTML, "kicker": HTML},
        "item-current": {"heading": HTML, "url": URL, "titles": TEXT, "period": TEXT, "previously": HTML,
            "employer": TEXT, "image": HTML, "kicker": HTML}, "heading": {"employer": TEXT}, "heading-multi": {"count": INT, "employer": TEXT},
        "previously": {"items": HTML}, "previously-item": {"url": URL, "title": TEXT, "period": TEXT}}},
    "showcase-view": {"first": "0.4.0", "parts": {"wrap": {"items": HTML, "label": TEXT},
        "item": {"url": URL, "image": HTML, "role": HTML, "title": TEXT, "kicker": HTML, "fullTitle": TEXT},
        "role": {"text": TEXT}}},
    "map-view": {"first": "0.4.0", "parts": {"wrap": {"map": HTML, "list": HTML}, "list": {"items": HTML},
        "list-item": {"url": URL, "title": TEXT}}},
    "home-showcase": {"first": "0.4.0", "parts": {"wrap": {"items": HTML},
        "item": {"url": URL, "image": HTML, "role": HTML, "title": TEXT, "kicker": HTML, "fullTitle": TEXT},
        "role": {"text": TEXT}, "image": PLACE_IMAGE_SLOTS}},
    "home-samples": {"first": "0.4.0", "parts": {"wrap": {"items": HTML}}},
    "home-links": {"first": "0.4.0", "parts": {"wrap": {"items": HTML}, "item": {"url": URL, "label": TEXT}}},
    # ---- 0.5.0 (design-movement-view section 4.2): new plugin markup lives in new constructs only, each linking
    # `schema-5.css` by its own `assets` entry. A value printed inside an existing part reaches it through a gated slot
    # (SLOT_FIRST below), filled with the new construct's markup by the call site that links that construct's asset.
    "steps-view": {"first": "0.5.0", "parts": {"wrap": {"items": HTML, "label": TEXT, "count": INT},
        "item": {"url": URL, "image": HTML, "number": HTML, "kicker": HTML, "title": TEXT, "role": HTML,
            "fullTitle": TEXT},
        "number": {"n": INT}, "role": {"text": TEXT}, "role-sep": {}, "image": PLACE_IMAGE_SLOTS}},
    "kicker": {"first": "0.5.0", "parts": {"wrap": {"text": TEXT}}},
    "card-picture": {"first": "0.5.0", "parts": {"wrap": {"image": HTML}}},
    "piece-link": {"first": "0.5.0", "parts": {"wrap": {"url": URL, "label": TEXT}}},
    "piece-teaser": {"first": "0.5.0", "parts": {"wrap": {"text": TEXT}}},
}

# A part added to a construct that already existed, with the release that added it. Anything not named
# here was born with its construct.
PART_FIRST = {
    ("reference-card", "role"): "0.4.0",
    ("card", "number"): "0.4.0",
    ("nav", "link"): "0.4.0", ("nav", "link-current"): "0.4.0",
    ("home", "eyebrow"): "0.4.0", ("home", "role"): "0.4.0",
    ("home-showcase", "image"): "0.5.0",
}

# Rule L3a (design-movement-view section 4.3; OURS, amends 0.4.0 L3): a slot added to a part that already existed,
# {(construct, part, slot): (release, trigger)}. The slot is GATED: the build fills it with "" unless the piece's own
# portfolio holds the schema-N trigger named here (`keytables.active_triggers`), so a default-look part may gain the
# placeholder and no tree an earlier release accepted changes by a byte. `DefaultLookFrozen` removes only these
# placeholders, and only while their release is newer than the compared tag; that test holds the entries as a literal.
SLOT_FIRST = {
    ("card", "wrap", "kicker"): ("0.5.0", "cardKicker"),
    ("roles-view", "item", "image"): ("0.5.0", "cardImage"),
    ("roles-view", "item", "kicker"): ("0.5.0", "cardKicker"),
    ("roles-view", "item-current", "image"): ("0.5.0", "cardImage"),
    ("roles-view", "item-current", "kicker"): ("0.5.0", "cardKicker"),
    ("piece", "wrap", "link"): ("0.5.0", "pieceLink"),
    ("piece", "wrap", "teaser"): ("0.5.0", "pieceTeaser"),
    ("showcase-view", "item", "kicker"): ("0.5.0", "cardKicker"),
    ("home-showcase", "item", "kicker"): ("0.5.0", "cardKicker"),
}

# Step G (O4a; coordinator 2026-11-19): an UNGATED slot added to a part that already existed, {(construct, part, slot):
# release}. The build always fills it (`fullTitle`: the piece's own `title`, never `shortTitle`), so a default-look part
# may NEVER hold it: every tree's output would change. `looks.needs` reads it as it reads SLOT_FIRST; `DefaultLookFrozen`
# holds it as a second literal beside the gated one and refuses it in any default part. `steps-view.item` holds
# `fullTitle` too, born with its 0.5.0 construct, so it is not a row here (as `steps-view`'s new parts are not PART_FIRST).
OPEN_SLOT_FIRST = {
    ("card", "wrap", "fullTitle"): "0.5.0",
    ("showcase-view", "item", "fullTitle"): "0.5.0",
    ("home-showcase", "item", "fullTitle"): "0.5.0",
}

# Step G (O2, O3): parts the default look has NO entry for. A site's own look may write one; where it does not, the
# place renders exactly as before the part existed (the separator " / ", the site-wide `image` construct).
OPTIONAL_PARTS = frozenset((("steps-view", "role-sep"), ("steps-view", "image"), ("home-showcase", "image")))
# Parts that are literal text and nothing else (no slot: the table gives none; no element: `looks.check_part`).
TEXT_ONLY_PARTS = frozenset((("steps-view", "role-sep"),))
# The slots of PLACE_IMAGE_SLOTS a picture may have no value for, so the build may leave them unfilled (`img_tag` fills
# width and height only for a file with a pixel size, srcset and sizes only with size copies, focus only with a
# position; src and alt always). Each must be the whole value of its own attribute (`lookgrammar/optionalparts.py`).
PLACE_IMAGE_MAY_BE_EMPTY = ("width", "height", "srcset", "sizes", "focus")
# The two private-use characters a part's slot stands as while its markup is checked (`looks._replace_slots`), here so
# `lookgrammar/optionalparts.py` reads the same ones `looks` writes.
SENT_OPEN, SENT_CLOSE = "", ""


# ----------------------------------------------------------------------------- the element and attribute lists
# ALLOWED_ELEMENTS: flow and phrasing elements, plus `img picture source time`. `iframe` is allowed only in
# the (construct, part) pairs of IFRAME_PARTS. Everything else is refused; the ones below get their own line.
ALLOWED_ELEMENTS = frozenset((
    "a", "abbr", "article", "aside", "b", "blockquote", "br", "cite", "code", "dd", "div", "dl", "dt", "em",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "li", "nav",
    "ol", "p", "q", "section", "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead",
    "tr", "ul", "img", "picture", "source", "time",
))
VOID_ELEMENTS = frozenset(("br", "hr", "img", "source"))
# `videos.item` is where a look MAY place a live player (design decision 34); `video-embed.wrap` is 0.3.1's
# bare video line, which has been a live embed since 0.2.0 and so is frozen as one (the default look carries it).
IFRAME_PARTS = frozenset((("videos", "item"), ("videos", "item-poster"), ("video-embed", "wrap")))

ELEMENT_REFUSALS = {
    "script": "a look is markup, never code",
    "style": "a look carries no stylesheet text; name a stylesheet file in `stylesheets` instead",
    "link": "a look may not load a file; name a stylesheet in `stylesheets` instead",
    "meta": "a look renders part of a page, never its head",
    "base": "a look may not change how every link on the page resolves",
    "form": "a look is not a form",
    "input": "a look is not a form",
    "button": "a look is not a form",
    "textarea": "a look is not a form",
    "select": "a look is not a form",
    "object": "a look may not embed a plugin object",
    "embed": "a look may not embed a plugin object",
    "svg": "a look's own SVG is a decoration only, read by the decoration rules (the map's SVG arrives through an `html` slot)",
    "math": "a look may not carry MathML",
    "video": "a hosted video file is not a look element; a look links a video through the `videos` construct",
    "audio": "a look may not load media",
    "template": "a look may not carry an inert document fragment",
    "iframe": "an iframe is allowed only in `videos.item` and `video-embed.wrap`",
}

GLOBAL_ATTRS = frozenset(("class", "id", "lang", "dir", "title", "hidden", "role", "tabindex"))
ELEMENT_ATTRS = {
    "a": frozenset(("href", "rel", "target", "hreflang")),
    "img": frozenset(("src", "srcset", "sizes", "alt", "width", "height", "loading", "decoding", "style")),
    "source": frozenset(("srcset", "sizes", "media", "type")),
    "time": frozenset(("datetime",)),
    "ol": frozenset(("start", "reversed")),
    "li": frozenset(("value",)),
    "td": frozenset(("colspan", "rowspan")),
    "th": frozenset(("colspan", "rowspan")),
    "blockquote": frozenset(("cite",)),
    "q": frozenset(("cite",)),
    "iframe": frozenset(("src", "title", "loading", "allow", "allowfullscreen", "referrerpolicy")),
}
# the (element, attribute) pairs the 0.3.1 code writes that are NOT look markup: kept here so the inventory
# test can print and reason about each (R5N-7). `link`/`script` are the plugin-asset tags `asset_html` writes,
# `meta`/`link`/`html` the page head and redirect page `emit_page` and `build_index_redirect` write.
NAMED_REFUSED_ATTRS = {
    "srcdoc": "an inline document would run as a page of its own",
    "poster": "a poster loads a file; a video facade's image is an `img` made by the plugin",
    "ping": "a ping sends a request to a third party on click",
    "formaction": "a look is not a form",
    "action": "a look is not a form",
    "background": "a background attribute loads a file",
    "xlink:href": "a look may not carry SVG links",
    "style": "`style` is refused except the one exact form `style=\"object-position: {{focus}}\"` on `img`",
}
STYLE_FORM = "object-position: {{focus}}"

# URL-bearing attributes: only a slot of the named kinds, alone, or a relative literal (rule 4). The plugin's
# own scripts read `data-embed`; every attribute a shipped script reads is URL-bearing with an exact slot
# form (R5N-5), derived by a test from the script text so a new one fails there until it is listed here.
URL_ATTRS = {"href": (URL, CONTACT), "src": (URL, EMBED), "srcset": (SRCSET,), "cite": (URL,),
             "data-embed": (EMBED,)}
SCRIPT_READ_ATTRS = {"data-embed": "embed"}

# Attribute VALUES that carry letters are a closed set per attribute (R5N-9). A literal outside its set is
# refused in every look; a `text` slot is never accepted where a closed set applies (the plugin chooses).
_ROLES = ("region", "group", "img", "list", "listitem", "navigation", "presentation", "none", "figure",
          "article", "banner", "contentinfo", "main", "complementary", "heading", "link", "separator",
          "term", "definition", "note")
CLOSED_VALUES = {
    "rel": ("noopener", "noreferrer", "nofollow", "external", "author", "me"),
    "loading": ("lazy", "eager"),
    "decoding": ("async", "sync", "auto"),
    "target": ("_blank", "_self"),
    "dir": ("ltr", "rtl", "auto"),
    "type": ("image/avif", "image/webp", "image/jpeg", "image/png", "image/gif"),
    "role": _ROLES,
    "referrerpolicy": ("no-referrer", "no-referrer-when-downgrade", "origin", "origin-when-cross-origin",
                       "same-origin", "strict-origin", "strict-origin-when-cross-origin"),
    "allow": ("fullscreen", "picture-in-picture", "encrypted-media", "autoplay", "clipboard-write"),
}
