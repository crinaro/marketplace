#!/usr/bin/env python3
"""looks.py -- a site's look is DATA the site carries (design-template-fidelity section R5, #909).
Python 3.9, standard library only.

A *look* is a JSON file (`site/looks/<name>.json`, or the plugin's own default at
`templates/looks/site-studio.json`) that says which markup each *construct* renders. A construct is a
named piece of generated markup (a quote, a card, the nav); it has fixed named *parts* the plugin chooses
between (a quote's `wrap` and its optional `by`; a nav `item` and `item-current`); a part is HTML holding
`{{slot}}` placeholders and nothing else. There is no logic in a look: no loop, no condition, no script.

    CONSTRUCTS     the closed table: construct id -> parts -> slot name -> slot kind. Written once, here, in
                   full (step 1.2L, named change R5N-2): later steps add default entries and code, never rows.
    parse()        strict, DENY-BY-DEFAULT validation of a look file (R5.2 rules 1 to 9), each refusal naming
                   the file, the construct, the part and the fix.
    render()       fill one part: every slot is escaped or validated by its KIND, whatever the look says.
    safe_url()     the one URL rule for a `url` slot, built on `contentmodel.links.url_as_browser_reads` (dev #912), the
                   same normaliser the content links use (R5N-4): no second normaliser.

THREAT MODEL (R5.1 L5). Slot VALUES are untrusted data (a person's text, a captured page's title). A look
FILE is trusted as markup only inside the allowlist below: the owner of a site can already write its
`layout.html`, so the grammar does not protect a site from its owner. It exists because looks TRAVEL as
data (a shipped look, `look.py use <path>` from another repo, a derived look that copied an old page's
attributes) and because the plugin's own claims (no script; no third party on load, bar the one named
exception) must hold for every look it renders. So an element, an (element, attribute) pair, a URL form or a
slot placement that is not listed is REFUSED, never ignored.

SLOT KINDS (fixed per slot name in CONSTRUCTS, so no context inference is needed; OURS, diverged from Go
`html/template`'s contextual escaping on purpose):
    text      escaped with `contentmodel.links.esc`; element content or a plain attribute value
    int       a non-negative whole number; element content or a plain attribute value
    html      HTML the PLUGIN rendered (an inline-Markdown run, another part); element content only
    url       `safe_url`: relative, http(s); exactly the whole value of `href`, `src` or `cite`
    srcset    a list of relative candidates, each checked by `safe_url`; exactly the value of `srcset`
    embed     one of the three embed hosts, https; exactly `iframe src` or `data-embed`
    contact   `safe_url` that also allows `mailto:`; only `a href` in the `contact` construct
    position  a CSS position (the regex 0.3.1 validates `coverPosition` with); only `style` on `img`

The Markdown renderer's own inline and block markup (`<p>`, `<h2>`, `<a>`, `<strong>`, the map's `<svg>`) is
not a construct: it is the value of an `html` slot, produced by the plugin, never by a look.
"""
import functools
import html.parser
import json
import os
import posixpath
import re
import stat
import urllib.parse

from contentmodel.links import esc, url_as_browser_reads, url_scheme

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
DEFAULT_LOOK_REL = "templates/looks/site-studio.json"
DEFAULT_LOOK_PATH = os.path.join(PLUGIN_ROOT, *DEFAULT_LOOK_REL.split("/"))
LOOK_FORMAT = 1

TEXT, HTML, URL, SRCSET, POSITION, INT, EMBED, CONTACT = (
    "text", "html", "url", "srcset", "position", "int", "embed", "contact")
SLOT_KINDS = (TEXT, HTML, URL, SRCSET, POSITION, INT, EMBED, CONTACT)

# The plugin's own output files a look's `assets` may keep linked (R5.2). `css` and `js` are 0.3.1's
# `site-studio/blocks.css` and `site-studio/video.js`; `schema-4` is 0.4.0's `site-studio/schema-4.css`.
ASSET_KINDS = ("css", "js", "schema-4")


class LookError(ValueError):
    """A look that is refused, or a render that cannot be made. `fix` says what to do."""

    def __init__(self, message, fix=None):
        ValueError.__init__(self, message)
        self.fix = fix


# --------------------------------------------------------------------------------- the construct table
# Written from the code at the `site-studio--v0.3.1` tag (every markup site it has) and from the design's
# sections 3 and 8 (every construct 0.4.0 adds). `first` is the release that introduced the construct;
# PART_FIRST names a part added later to a construct that already existed. A construct a look omits renders
# with the default look's entry. Not expressible, stated: first/last/odd/even classes and any wrapper that
# depends on a value the plugin does not expose as a slot (derive reports such a construct `unmapped`).

def _c(first, **parts):
    # keyword names cannot hold a hyphen, so a part named `item-current` is spelled `item_current` here
    return {"first": first, "parts": dict((k.replace("_", "-"), v) for k, v in parts.items())}


CONSTRUCTS = {
    # ---- 0.3.1: every construct its code builds (content.py `_Renderer`, build.py `_Builder`)
    "tagline": _c("0.3.1", wrap={"text": TEXT}),
    "tiles": _c("0.3.1", wrap={"items": HTML, "label": TEXT, "count": INT},
                item={"figure": TEXT, "text": TEXT, "n": INT}),
    "quote": _c("0.3.1", wrap={"body": HTML, "by": HTML}, by={"who": HTML}),
    "gallery": _c("0.3.1", wrap={"items": HTML, "count": INT},
                  wrap_labelled={"items": HTML, "count": INT, "label": TEXT},
                  item={"image": HTML, "caption": HTML}, caption={"text": TEXT}),
    "videos": _c("0.3.1", wrap={"items": HTML}, wrap_labelled={"items": HTML, "label": TEXT},
                 item_poster={"url": URL, "embed": EMBED, "image": HTML, "title": TEXT, "kind": TEXT},
                 item={"url": URL, "embed": EMBED, "title": TEXT, "host": TEXT, "kind": TEXT}),
    "carousel": _c("0.3.1", wrap={"items": HTML, "label": TEXT}, item={"body": HTML}),
    "video-embed": _c("0.3.1", wrap={"embed": EMBED}),
    "figure": _c("0.3.1", wrap={"image": HTML, "caption": HTML}, caption={"text": TEXT}),
    "image": _c("0.3.1",
                plain={"src": URL, "alt": TEXT},
                sized={"src": URL, "alt": TEXT, "width": INT, "height": INT},
                sized_set={"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET, "sizes": TEXT},
                plain_pos={"src": URL, "alt": TEXT, "focus": POSITION},
                sized_pos={"src": URL, "alt": TEXT, "width": INT, "height": INT, "focus": POSITION},
                sized_set_pos={"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET,
                               "sizes": TEXT, "focus": POSITION}),
    "block-image": _c("0.3.1",
                      plain={"src": URL, "alt": TEXT},
                      sized={"src": URL, "alt": TEXT, "width": INT, "height": INT},
                      sized_set={"src": URL, "alt": TEXT, "width": INT, "height": INT, "srcset": SRCSET,
                                 "sizes": TEXT}),
    "reference-card": _c("0.3.1", wrap={"url": URL, "image": HTML, "title": TEXT, "site": HTML,
                                        "description": HTML, "role": HTML},
                         site={"text": TEXT}, description={"text": TEXT}, role={"text": TEXT}),
    "reference-grid": _c("0.3.1", wrap={"items": HTML}),
    "card": _c("0.3.1", wrap={"url": URL, "image": HTML, "title": TEXT, "teaser": HTML, "meta": HTML,
                              "number": HTML},
               teaser={"text": TEXT}, meta={"text": TEXT}, number={"n": INT}),
    "cards": _c("0.3.1", wrap={"items": HTML}),
    "group": _c("0.3.1", wrap={"title": TEXT, "cards": HTML}),
    "portfolio": _c("0.3.1", wrap={"title": TEXT, "tagline": HTML, "intro": HTML, "cards": HTML, "slug": TEXT}),
    "piece": _c("0.3.1", wrap={"title": TEXT, "meta": HTML, "body": HTML, "back": HTML, "slug": TEXT,
                               "portfolio": TEXT, "group": TEXT}),
    "meta-list": _c("0.3.1", wrap={"items": HTML}, item={"name": TEXT, "value": TEXT}),
    "nav": _c("0.3.1", wrap={"items": HTML}, item={"url": URL, "label": TEXT},
              item_current={"url": URL, "label": TEXT}, link={"url": URL, "label": TEXT},
              link_current={"url": URL, "label": TEXT}),
    "contact": _c("0.3.1", wrap={"items": HTML}, heading={},
                  item_mail={"label": TEXT, "href": CONTACT, "text": TEXT},
                  item_link={"label": TEXT, "url": URL, "text": TEXT},
                  item_text={"label": TEXT, "text": TEXT}),
    "photo": _c("0.3.1", wrap={"image": HTML}),
    "endorsement": _c("0.3.1", wrap={"quote": TEXT, "by": HTML}, by={"who": TEXT}),
    "feed": _c("0.3.1", wrap={"grid": HTML}),
    "home": _c("0.3.1", wrap={"title": TEXT, "body": HTML, "eyebrow": HTML, "role": HTML},
               intro={"photo": HTML, "intro": HTML, "endorsement": HTML}, featured={"cards": HTML},
               eyebrow={"text": TEXT}, role={"text": TEXT}),
    "about": _c("0.3.1", wrap={"title": TEXT, "photo": HTML, "intro": HTML, "endorsement": HTML,
                               "contact": HTML}),
    "resume": _c("0.3.1", wrap={"title": TEXT, "download": HTML, "body": HTML, "contact": HTML, "links": HTML},
                 download={"url": URL}),
    # ---- 0.4.0: constructs new in this release (their default entries and code arrive with steps 1.3 to 1.5)
    "quotes": _c("0.4.0", wrap={"items": HTML, "label": TEXT, "count": INT}, item={"body": HTML, "by": HTML},
                 by={"who": HTML}),
    "gallery-video": _c("0.4.0", item={"url": URL, "embed": EMBED, "image": HTML, "title": TEXT, "caption": HTML},
                        caption={"text": TEXT, "url": URL, "embed": EMBED, "title": TEXT}),
    "back-link": _c("0.4.0", wrap={"url": URL, "label": TEXT}),
    "resume-role": _c("0.4.0", wrap={"role": HTML, "org": HTML, "body": HTML},
                      wrap_bare={"role": HTML, "body": HTML}),
    "roles-view": _c("0.4.0", wrap={"items": HTML},
                     item={"heading": HTML, "url": URL, "titles": TEXT, "period": TEXT, "previously": HTML,
                           "employer": TEXT},
                     item_current={"heading": HTML, "url": URL, "titles": TEXT, "period": TEXT,
                                   "previously": HTML, "employer": TEXT},
                     heading={"employer": TEXT}, heading_multi={"count": INT, "employer": TEXT},
                     previously={"items": HTML}, previously_item={"url": URL, "title": TEXT, "period": TEXT}),
    "showcase-view": _c("0.4.0", wrap={"items": HTML, "label": TEXT},
                        item={"url": URL, "image": HTML, "role": HTML, "title": TEXT}, role={"text": TEXT}),
    "map-view": _c("0.4.0", wrap={"map": HTML, "list": HTML}, list={"items": HTML},
                   list_item={"url": URL, "title": TEXT}),
    "home-showcase": _c("0.4.0", wrap={"items": HTML},
                        item={"url": URL, "image": HTML, "role": HTML, "title": TEXT}, role={"text": TEXT}),
    "home-samples": _c("0.4.0", wrap={"items": HTML}),
    "home-links": _c("0.4.0", wrap={"items": HTML}, item={"url": URL, "label": TEXT}),
}

# A part added to a construct that already existed, with the release that added it. Anything not named
# here was born with its construct.
PART_FIRST = {
    ("reference-card", "role"): "0.4.0",
    ("card", "number"): "0.4.0",
    ("nav", "link"): "0.4.0", ("nav", "link-current"): "0.4.0",
    ("home", "eyebrow"): "0.4.0", ("home", "role"): "0.4.0",
}

_PART_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_SLOT_NAME = re.compile(r"^[a-z][a-z0-9]*$")
_SLOT = re.compile(r"\{\{([^{}]*)\}\}")


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def part_first(construct, part):
    return PART_FIRST.get((construct, part), CONSTRUCTS[construct]["first"])


def table_problems():
    """The table's own consistency: names, kinds. Used by the tests; an empty list is a sound table."""
    out = []
    for cid, c in CONSTRUCTS.items():
        if not _PART_NAME.match(cid):
            out.append("construct %r: not a lower-case slug" % cid)
        if not c["parts"]:
            out.append("construct %r has no parts" % cid)
        for pn, slots in c["parts"].items():
            if not _PART_NAME.match(pn):
                out.append("%s.%s: part name is not a lower-case slug" % (cid, pn))
            for sn, kind in slots.items():
                if not _SLOT_NAME.match(sn):
                    out.append("%s.%s: slot name %r is not lower-case letters and digits" % (cid, pn, sn))
                if kind not in SLOT_KINDS:
                    out.append("%s.%s.%s: unknown slot kind %r" % (cid, pn, sn, kind))
    return out


# ----------------------------------------------------------------------------- the element and attribute lists
# ALLOWED_ELEMENTS: flow and phrasing elements, plus `img picture source time`. `iframe` is allowed only in
# the (construct, part) pairs of IFRAME_PARTS. Everything else is refused; the ones below get their own line.
ALLOWED_ELEMENTS = frozenset((
    "a abbr article aside b blockquote br cite code dd div dl dt em figcaption figure footer "
    "h1 h2 h3 h4 h5 h6 header hr i li nav ol p q section small span strong sub sup table tbody td th thead tr ul "
    "img picture source time").split())
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
    "svg": "inline SVG is plugin-made only (the map's SVG arrives through an `html` slot)",
    "math": "a look may not carry MathML",
    "video": "a hosted video file is a construct of its own in 0.5.0",
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
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
_INTLIT = re.compile(r"^\d{1,6}$")
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
_DIGITS3 = re.compile(r"\d{3,}")
POSITION_RE = re.compile(r"^[a-z0-9% .-]{1,40}$")      # equals content.POSITION_RE (a test pins it)
EMBED_HOSTS = {"www.youtube-nocookie.com": "/embed/", "player.vimeo.com": "/video/",
               "drive.google.com": "/file/d/"}

_SENT_OPEN, _SENT_CLOSE = "", ""
_SENT = re.compile(_SENT_OPEN + r"(\d+)" + _SENT_CLOSE)


# ------------------------------------------------------------------------------------- the URL rule
_BASE = urllib.parse.urlsplit("https://base.invalid/a/")


def url_text(value):
    """`value` as a browser's URL parser reads it before looking for a scheme: leading and trailing C0
    control and space stripped, tab and newline removed (`contentmodel.links.url_as_browser_reads`, the WHATWG
    steps), and a backslash read as a slash, as a browser does for http and https (R5N-4)."""
    return url_as_browser_reads(value).replace("\\", "/")


def classify_url(value):
    """('relative' | 'http' | 'https' | 'mailto' | 'other:<scheme>' | 'off-origin', text). 'relative' means no
    scheme AND, resolved against a fixed base, the result keeps the base's origin (so `//host/x`, `/\\host/x`
    and `\\\\host` are 'off-origin', R5N-4)."""
    seen = url_text(value)
    scheme = url_scheme(seen)
    if scheme is not None:
        return (scheme if scheme in ("http", "https", "mailto") else "other:" + scheme), seen
    joined = urllib.parse.urlsplit(urllib.parse.urljoin(_BASE.geturl(), seen))
    if (joined.scheme, joined.netloc) != (_BASE.scheme, _BASE.netloc):
        return "off-origin", seen
    return "relative", seen


def safe_url(value, allow_mailto=False, relative_only=False):
    """Return `value` unchanged when a browser would read it as a relative link, or an http(s) link (or
    mailto, when `allow_mailto`); raise LookError otherwise. Decided on the normalised text, as a browser
    reads it (dev #912); what is written into the page is the person's own text. `relative_only` refuses
    every scheme (a literal in a look file, and every `srcset` candidate)."""
    if not isinstance(value, str):
        raise LookError("a url slot needs text, not %s" % type(value).__name__)
    kind, _seen = classify_url(value)
    if kind == "relative":
        return value
    if kind == "off-origin":
        raise LookError("the link %r reads as a link to another host (a protocol-relative or backslash "
                        "form)" % value[:60], fix="make the link relative, such as ../work/ or media/photo.jpg")
    if relative_only:
        raise LookError("the link %r is not relative; a look file may carry only relative links" % value[:60],
                        fix="use a {{url}} slot, or a relative path")
    if kind in ("http", "https") or (kind == "mailto" and allow_mailto):
        return value
    scheme = kind.split(":", 1)[1] if kind.startswith("other:") else kind
    raise LookError("a link may be http(s) or relative%s, not '%s:'" % (", or mailto here" if allow_mailto else "", scheme),
                    fix="use an http(s) or relative link")


def safe_srcset(value):
    """A `srcset` value: comma-separated candidates, each a RELATIVE url with an optional `Nw` or `Nx`
    descriptor. Every candidate is checked (R5N-4: an off-origin second candidate is refused)."""
    if not isinstance(value, str) or not value.strip():
        raise LookError("a srcset slot needs a non-empty list of candidates")
    for cand in value.split(","):
        bits = cand.split()
        if not bits:
            raise LookError("a srcset candidate is empty in %r; remove the stray comma or fill the candidate in" % value[:80])
        safe_url(bits[0], relative_only=True)
        if len(bits) > 2 or (len(bits) == 2 and not re.match(r"^\d+(\.\d+)?[wx]$", bits[1])):
            raise LookError("a srcset candidate %r has a descriptor that is not like 480w or 2x; write a whole number "
                            "followed by w or x" % cand.strip()[:60])
    return value


def safe_embed(value):
    """An https embed address on one of the three embed hosts (`content.video_embed`'s forms), nothing else."""
    if not isinstance(value, str):
        raise LookError("an embed slot needs text")
    seen = url_text(value)
    p = urllib.parse.urlsplit(seen)
    host = (p.hostname or "").lower()
    ok = (p.scheme == "https" and host in EMBED_HOSTS and p.username is None and p.port is None
          and p.path.startswith(EMBED_HOSTS[host]) and seen == value)
    if not ok:
        raise LookError("the embed address %r is not an https YouTube, Vimeo or Google Drive embed" % value[:80],
                        fix="the embed address comes from content.video_embed, never from a look or a person's text")
    return value


def safe_position(value):
    if not isinstance(value, str) or not POSITION_RE.match(value):
        raise LookError("the position %r is not a CSS position such as 'center 30%%'" % (value if isinstance(value, str) else "")[:60],
                        fix="write a CSS position such as center 30%")
    return value


def safe_int(value):
    if isinstance(value, bool):
        raise LookError("an int slot needs a whole number, not a boolean")
    if isinstance(value, int) and 0 <= value <= 999999:
        return str(value)
    if isinstance(value, str) and _INTLIT.match(value):
        return value
    raise LookError("an int slot needs a whole number from 0 to 999999, got %r" % (value,))


# ---------------------------------------------------------------------------------------------- parse
def attr_allowed(tag, name):
    """True when (tag, name) is on the allowlist: a global attribute, an `aria-*` or `data-*` one, or one the
    element's own list names. `style` is never here: it has the one exact form of rule 6 and nothing else."""
    if name in GLOBAL_ATTRS or re.match(r"^(aria|data)-[a-z][a-z0-9-]*$", name):
        return True
    return name in ELEMENT_ATTRS.get(tag, ())


def live_players(look):
    """[(construct, part)] of a look that carry an `iframe`: the places a live third-party player loads on
    page load. A template or derived look may hold one in `videos.item` (design decision 34); the
    plugin-authored looks hold none, bar the bare video line the default look has carried since 0.2.0."""
    return sorted((c, p) for c, parts in look.constructs.items() for p, t in parts.items()
                  if re.search(r"<iframe\b", t, re.I))


class _PartParser(html.parser.HTMLParser):
    """Walks one part's text (slots already replaced by sentinels) and records every problem."""

    def __init__(self, ctx, slots, shipped, template):
        html.parser.HTMLParser.__init__(self, convert_charrefs=False)
        self.ctx = ctx                      # "construct.part"
        self.construct, self.part = ctx.split(".", 1)
        self.slots = slots                  # slot name -> kind (the table's)
        self.shipped = shipped
        self.template = template
        self.slots_by_index = ()
        self.stack = []
        self.problems = []
        self.elements = []

    # -- helpers
    def bad(self, message, fix=None):
        self.problems.append((message, fix))

    # -- structure
    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def _start(self, tag, attrs, selfclose):
        if _SENT_OPEN in tag:
            self.bad("%s: a slot inside a tag name" % self.ctx, "a slot may stand in text or in an attribute value only")
            return
        self.elements.append(tag)
        if tag in ELEMENT_REFUSALS and not (tag == "iframe" and (self.construct, self.part) in IFRAME_PARTS):
            self.bad("%s: <%s> is not allowed: %s" % (self.ctx, tag, ELEMENT_REFUSALS[tag]),
                     "remove the <%s>; allowed elements are listed in the content model" % tag)
        elif tag not in ALLOWED_ELEMENTS and tag != "iframe":
            self.bad("%s: <%s> is not an allowed element" % (self.ctx, tag),
                     "use one of the elements the content model lists")
        self._attrs(tag, attrs)
        if tag not in VOID_ELEMENTS and not selfclose:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        if not self.stack or self.stack[-1] != tag:
            self.bad("%s: </%s> closes nothing that is open here (unbalanced tags)" % (self.ctx, tag),
                     "close every element you open, in order")
            return
        self.stack.pop()

    def handle_data(self, data):
        for i in _SENT.findall(data):
            sname, kind = self.slot_by_index(i)
            if kind not in (TEXT, HTML, INT):
                self.bad("%s: the %s slot {{%s}} stands in element content; a %s slot belongs in its attribute"
                         % (self.ctx, kind, sname, kind), "use a text slot for visible words")
        if "<" in data:
            self.bad("%s: a '<' that does not open a tag (or a slot in a tag name)" % self.ctx,
                     "write a literal < as &lt;")
        if self.template and any(ch.isalpha() for ch in _SENT.sub("", data)):
            self.bad("%s: literal text %r in a template look; text comes from a slot" % (self.ctx, data.strip()[:30]),
                     "replace the words with a slot")

    def handle_entityref(self, name):
        self.handle_data("")

    def handle_charref(self, name):
        self.handle_data("")

    def handle_comment(self, data):
        self.bad("%s: an HTML comment" % self.ctx, "remove the comment")

    def handle_decl(self, decl):
        self.bad("%s: a declaration (<!...>)" % self.ctx, "remove it")

    def handle_pi(self, data):
        self.bad("%s: a processing instruction (<?...>)" % self.ctx, "remove it")

    def unknown_decl(self, data):
        self.bad("%s: a marked section (<![...]>)" % self.ctx, "remove it")

    # -- attributes
    def _attrs(self, tag, attrs):
        seen = set()
        names = dict(attrs)
        for name, value in attrs:
            if _SENT_OPEN in name:
                self.bad("%s: a slot inside an attribute name on <%s>" % (self.ctx, tag),
                         "a slot may stand in an attribute VALUE only")
                continue
            if name in seen:
                self.bad("%s: <%s> repeats the attribute %s" % (self.ctx, tag, name), "write it once")
            seen.add(name)
            self._one_attr(tag, name, value, names)

    def _allowed_pair(self, tag, name):
        return attr_allowed(tag, name)

    def _one_attr(self, tag, name, value, names):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        if name == "style":
            ok = (tag == "img" and value is not None and _SENT_OPEN in value
                  and self._style_is_focus(value))
            if not ok:
                self.bad(where + " is refused: " + NAMED_REFUSED_ATTRS["style"], "remove the style attribute")
            return
        if name.startswith("on"):
            self.bad(where + " is refused: an event handler is code", "remove it")
            return
        if name in NAMED_REFUSED_ATTRS:
            self.bad(where + " is refused: " + NAMED_REFUSED_ATTRS[name], "remove it")
            return
        if not self._allowed_pair(tag, name):
            self.bad(where + " is not an allowed attribute of <%s>" % tag, "remove it; allowed pairs are listed in the content model")
            return
        if tag == "iframe" and name not in ELEMENT_ATTRS["iframe"]:
            self.bad(where + " is not allowed on an iframe", "an iframe carries only src, title, loading, allow, allowfullscreen, referrerpolicy")
            return
        if name == "allowfullscreen":
            if value not in (None, "", "allowfullscreen"):
                self.bad(where + " takes no value", "write it bare")
            return
        if name == "hidden":
            if value not in (None, "", "hidden", "until-found"):
                self.bad(where + " has an unknown value %r" % value, "write it bare")
            return
        if value is None:
            value = ""
        slots = [self.slot_by_index(i) for i in _SENT.findall(value)]
        literal = _SENT.sub("", value)
        if name in URL_ATTRS:
            self._url_attr(tag, name, value, slots, literal)
            return
        # rule 7: literals or text and int slots; a url, embed, srcset, contact, position or html slot is refused here
        for (sname, kind) in slots:
            if kind not in (TEXT, INT):
                self.bad("%s holds the %s slot {{%s}}; only a text or int slot may stand in this attribute"
                         % (where, kind, sname), "use a text slot, or put the slot where its kind belongs")
        if name in CLOSED_VALUES:
            if slots:
                self.bad(where + " holds a slot; the plugin chooses its value from a closed list", "write one of: " + ", ".join(CLOSED_VALUES[name]))
                return
            toks = value.split() if name in ("rel", "allow") else [value]
            if name == "allow":
                toks = [t.strip() for t in value.replace(";", " ").split()]
            if not toks or any(t not in CLOSED_VALUES[name] for t in toks):
                self.bad("%s has the value %r, which is not in its closed list" % (where, value),
                         "write one of: " + ", ".join(CLOSED_VALUES[name]))
            if name == "target" and value == "_blank":
                rel = names.get("rel") or ""
                if "noopener" not in rel.split():
                    self.bad(where + " _blank needs a rel containing noopener", "add rel=\"noopener\"")
            return
        if name == "tabindex":
            if value not in ("0", "-1"):
                self.bad(where + " may be the literal 0 or -1 only", "write tabindex=\"0\"")
            return
        if name in ("lang", "hreflang"):
            if slots or not _LANG.match(value):
                self.bad(where + " must be a language code such as en", "write a language code")
            return
        if name in ("width", "height", "start", "value", "colspan", "rowspan"):
            if not (slots and not literal) and not _INTLIT.match(value):
                self.bad(where + " must be a whole number or one int slot", "write a number or {{n}}")
            return
        if self.template:
            self._template_value(tag, name, value, slots, literal)
        if name == "class":
            for tok in literal.split():
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", tok):
                    self.bad("%s has a class token %r that is not a name" % (where, tok), "use letters, digits, - and _")

    def _template_value(self, tag, name, value, slots, literal):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        tokenish = name in ("class", "id") or name.startswith(("data-", "aria-"))
        if tokenish:
            for tok in literal.split():
                if not _TOKEN.match(tok) or _DIGITS3.search(tok):
                    self.bad("%s has the token %r (template looks: a name, at most 40 characters, no run of three digits)"
                             % (where, tok), "write the token as the template names it, with a slot for a number")
        elif any(ch.isalpha() for ch in literal):
            self.bad("%s carries literal text %r in a template look" % (where, literal[:30]), "use a slot, or a closed-list value")

    def _style_is_focus(self, value):
        return _SENT.sub("{{focus}}", value) == STYLE_FORM and self.slot_by_index(
            _SENT.findall(value)[0]) == ("focus", POSITION)

    def _url_attr(self, tag, name, value, slots, literal):
        where = "%s: <%s %s>" % (self.ctx, tag, name)
        allowed = URL_ATTRS[name]
        if slots:
            if literal.strip() or len(slots) != 1:
                self.bad(where + " must be exactly one slot and nothing else", "write %s=\"{{url}}\"" % name)
                return
            sname, kind = slots[0]
            if kind not in allowed:
                self.bad("%s holds the %s slot {{%s}}; a %s attribute takes only a %s slot"
                         % (where, kind, sname, name, "/".join(allowed)),
                         "use a slot of kind %s, or a relative literal" % "/".join(allowed))
                return
            if kind == CONTACT and not (tag == "a" and self.construct == "contact"):
                self.bad(where + " takes a contact slot only on an <a> in the contact construct", "use a url slot")
            if kind == EMBED:
                if not ((tag == "iframe" and name == "src") or name == "data-embed"):
                    self.bad(where + " takes an embed slot only as `iframe src` or `data-embed`", "use a url slot")
            if tag == "iframe" and name == "src" and kind != EMBED:
                self.bad(where + " must be exactly {{embed}}", "write src=\"{{embed}}\"")
            return
        # a literal
        if name == "data-embed" or (tag == "iframe" and name == "src"):
            self.bad(where + " must be exactly the {{embed}} slot, never a literal", "write %s=\"{{embed}}\"" % name)
            return
        try:
            if name == "srcset":
                for cand in literal.split(","):
                    bits = cand.split()
                    if bits:
                        safe_url(bits[0], relative_only=True)
            else:
                safe_url(literal, relative_only=True)
        except LookError as e:
            self.bad("%s: the literal %r is refused: %s" % (where, literal[:60], e), "use a {{url}} slot or a relative path")

    def slot_by_index(self, i):
        return self.slots_by_index[int(i)]


def _replace_slots(text, slots_table, ctx, problems):
    """Replace each valid `{{name}}` by a sentinel; collect (name, kind). A `{{` left over is a problem."""
    found = []

    def sub(m):
        name = m.group(1)
        if name not in slots_table:
            problems.append(("%s: the slot {{%s}} is not one of this part's slots (%s)"
                             % (ctx, name, ", ".join(sorted(slots_table)) or "it has none"),
                             "use only the part's own slots; the content model lists them"))
            found.append((name, TEXT))
        else:
            found.append((name, slots_table[name]))
        return _SENT_OPEN + str(len(found) - 1) + _SENT_CLOSE
    out = _SLOT.sub(sub, text)
    if "{{" in out or "}}" in out:
        problems.append(("%s: a literal '{{' or '}}' that is not a slot" % ctx, "write a slot as {{name}} with a lower-case name"))
    return out, found


def check_part(construct, part, text, shipped=False, template=False):
    """Every problem with one part's text, as [(message, fix)]. [] is a clean part."""
    problems = []
    ctx = "%s.%s" % (construct, part)
    if not isinstance(text, str):
        return [("%s: a part is a string of HTML" % ctx, "write the part as a JSON string")]
    if _SENT_OPEN in text or _SENT_CLOSE in text:
        return [("%s: a private-use character U+E000 or U+E001" % ctx, "remove it")]
    table = CONSTRUCTS[construct]["parts"][part]
    replaced, found = _replace_slots(text, table, ctx, problems)
    p = _PartParser(ctx, table, shipped, template)
    p.slots_by_index = found
    try:
        p.feed(replaced)
        p.close()
    except Exception as e:                                        # noqa: BLE001 -- html.parser's own errors
        problems.append(("%s: the markup cannot be read (%s)" % (ctx, e), "fix the markup"))
    problems.extend(p.problems)
    if p.stack:
        problems.append(("%s: <%s> is never closed" % (ctx, p.stack[-1]), "close every element you open"))
    # an html slot only in element content: a sentinel for an html slot inside any attribute value is caught
    # in _one_attr (kind not text/int); here the same slot in a tag position was caught by the tag-name rule.
    return [(m, f) for m, f in problems]


class Look(object):
    """A parsed look: `constructs` {id: {part: text}}, `stylesheets` [path], `assets` {id: [kind]}."""

    def __init__(self, constructs, stylesheets, assets, where):
        self.constructs = constructs
        self.stylesheets = stylesheets
        self.assets = assets
        self.where = where

    def has(self, construct, part):
        return part in self.constructs.get(construct, {})

    def own_part(self, construct, part):
        return self.constructs.get(construct, {}).get(part)

    def omitted(self):
        """Construct ids this look has no entry for (rendered with the default look's)."""
        return sorted(c for c in CONSTRUCTS if c not in self.constructs)


def check_stylesheet_path(path, where="stylesheets"):
    """A look's stylesheet path, normalised and held under `site/src/` (R5N-11). Returns the normal form."""
    if not isinstance(path, str) or not path:
        raise LookError("%s: a stylesheet path is a non-empty string" % where, fix="write site/src/looks/<name>.css")
    if "\\" in path or "\x00" in path:
        raise LookError("%s: the stylesheet path %r holds a backslash" % (where, path), fix="use forward slashes")
    if path.startswith("/"):
        raise LookError("%s: the stylesheet path %r starts with '/'" % (where, path), fix="start it with site/src/")
    if ".." in path.split("/"):
        raise LookError("%s: the stylesheet path %r climbs out of its folder with '..'" % (where, path), fix="name the file under site/src/")
    norm = posixpath.normpath(path)
    if norm != path or not norm.startswith("site/src/") or not norm.endswith(".css") or norm == "site/src/":
        raise LookError("%s: the stylesheet path %r is not a normalised site/src/**.css path" % (where, path),
                        fix="write it as site/src/looks/<name>.css")
    return norm


def check_stylesheet_file(root, rel, where="stylesheets"):
    """The file a `stylesheets` path names must exist under `root` as a regular file, never a symlink, with
    no symlink among the folders above it (R5N-11)."""
    norm = check_stylesheet_path(rel, where)
    cur = root
    for part in norm.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            raise LookError("%s: %s does not exist" % (where, norm), fix="add the file, or remove it from stylesheets")
        if stat.S_ISLNK(st.st_mode):
            raise LookError("%s: %s goes through a symlink" % (where, norm), fix="make it a regular file")
    if not stat.S_ISREG(os.lstat(cur).st_mode):
        raise LookError("%s: %s is not a regular file" % (where, norm), fix="make it a regular file")
    return norm


_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CSS_STRING = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'", re.S)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s\"']*))\s*\)", re.I)


def scan_stylesheet(css, where="stylesheet"):
    """Refuse a stylesheet that loads another host's file (R5N-11): `@import`, a `url(...)` or an
    `@font-face src` whose address is not relative, and a CSS escape that could spell one of those past
    this scan. Returns None when clean."""
    text = _CSS_COMMENT.sub("", css)
    for m in _CSS_URL.finditer(text):
        arg = next(g for g in m.groups() if g is not None) if any(g is not None for g in m.groups()) else ""
        if "\\" in arg:
            raise LookError("%s: a url(%s) holds a backslash, which could hide a scheme" % (where, arg[:40]), fix="write the address plainly")
        try:
            safe_url(arg, relative_only=True)
        except LookError as e:
            raise LookError("%s: url(%s) is refused: %s" % (where, arg[:40], e), fix="use a file the site carries, by a relative path")
    bare = _CSS_STRING.sub('""', text)
    if re.search(r"@import", bare, re.I):
        raise LookError("%s: @import loads another file" % where, fix="link the stylesheet from the layout instead")
    if "\\" in bare:
        raise LookError("%s: a CSS escape outside a string could spell @import or url(" % where,
                        fix="write the rule without an escape")
    return None


def parse(text, where="look", shipped=False, template=None):
    """Parse and validate a look file's text. Returns a `Look`; raises LookError naming the first
    problem group (every problem is in the message, one per line). `shipped=True` is CI's reading of a
    file in `templates/looks/` (R5.2 rule 8): the same rules, plus, for a TEMPLATE look (`template`,
    default: the file's name starts `template-`), no literal word in text or attribute values and the
    token rules; a plugin-authored look keeps the token and URL rules and may hold literal words, because
    it is engine text written in this repository, not extracted from a site."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LookError("%s: the look is not valid JSON (%s)" % (where, e), fix="fix the JSON")
    if not isinstance(data, dict):
        raise LookError("%s: a look is a JSON object" % where, fix="start from {\"look\": 1, \"constructs\": {}}")
    problems = []
    for k in data:
        if k not in ("look", "constructs", "stylesheets", "assets"):
            problems.append("%s: unknown top-level key %r" % (where, k))
    ver = data.get("look")
    if ver is None or isinstance(ver, bool) or not isinstance(ver, int):
        problems.append("%s: `look` must be the format version, %d" % (where, LOOK_FORMAT))
    elif ver > LOOK_FORMAT:
        raise LookError("%s: this look was made by a newer site-studio (format %d); update the plugin" % (where, ver),
                        fix="update site-studio")
    elif ver != LOOK_FORMAT:
        problems.append("%s: `look` is %r; this version reads format %d" % (where, ver, LOOK_FORMAT))
    if template is None:
        template = bool(shipped) and os.path.basename(where).startswith("template-")
    constructs = data.get("constructs", {})
    if not isinstance(constructs, dict):
        problems.append("%s: `constructs` is an object of construct id -> part -> markup" % where)
        constructs = {}
    clean = {}
    for cid, parts in constructs.items():
        if cid not in CONSTRUCTS:
            problems.append("%s: unknown construct %r (known: see the content model)" % (where, cid))
            continue
        if not isinstance(parts, dict):
            problems.append("%s: construct %s is an object of part -> markup" % (where, cid))
            continue
        clean[cid] = {}
        for pn, ptext in parts.items():
            if pn not in CONSTRUCTS[cid]["parts"]:
                problems.append("%s: construct %s has no part %r (its parts: %s)"
                                % (where, cid, pn, ", ".join(sorted(CONSTRUCTS[cid]["parts"]))))
                continue
            for msg, fix in check_part(cid, pn, ptext, shipped=shipped, template=template):
                problems.append("%s: %s%s" % (where, msg, " -- fix: " + fix if fix else ""))
            clean[cid][pn] = ptext
    sheets = data.get("stylesheets", [])
    if not isinstance(sheets, list):
        problems.append("%s: `stylesheets` is a list of paths" % where)
        sheets = []
    norm_sheets = []
    for sp in sheets:
        try:
            norm_sheets.append(check_stylesheet_path(sp, where))
        except LookError as e:
            problems.append(str(e))
    assets = data.get("assets", {})
    if not isinstance(assets, dict):
        problems.append("%s: `assets` is an object of construct id -> [css, js, schema-4]" % where)
        assets = {}
    for cid, kinds in assets.items():
        if cid not in CONSTRUCTS:
            problems.append("%s: `assets` names the unknown construct %r" % (where, cid))
        if not isinstance(kinds, list) or any(k not in ASSET_KINDS for k in kinds):
            problems.append("%s: `assets` for %s must be a list drawn from %s" % (where, cid, ", ".join(ASSET_KINDS)))
    if shipped and not template:
        problems.extend(_third_party_problems(where, clean))
    if problems:
        raise LookError("\n".join(problems), fix="fix each line above, then run the check again")
    return Look(clean, norm_sheets, dict(assets), where)


def _third_party_problems(where, constructs):
    """`ShippedLooksNoThirdParty`'s rule, applied to a plugin-authored look: no iframe except 0.3.1's bare
    video line (a live embed since 0.2.0, frozen), and no off-origin reference in any attribute."""
    out = []
    for cid, parts in constructs.items():
        for pn, text in parts.items():
            if re.search(r"<iframe\b", text, re.I) and (cid, pn) != ("video-embed", "wrap"):
                out.append("%s: %s.%s holds an iframe; a plugin-authored look carries no live player "
                           "(invariant item 5), bar the bare video line" % (where, cid, pn))
            for m in re.finditer(r"(?:href|src|srcset|cite|data-embed)=\"([^\"]*)\"", text):
                v = _SLOT.sub("", m.group(1)).strip()
                if v and re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", v):
                    out.append("%s: %s.%s holds the off-origin address %r" % (where, cid, pn, v[:50]))
    return out


# -------------------------------------------------------------------------------------- the default look
@functools.lru_cache(maxsize=1)
def default_look():
    """The plugin's own look, `templates/looks/site-studio.json`, parsed once. A missing file is a refusal,
    never an empty look (a missing thing must not read as an empty thing)."""
    try:
        with open(DEFAULT_LOOK_PATH, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise LookError("the plugin's default look %s cannot be read: %s" % (DEFAULT_LOOK_REL, e),
                        fix="reinstall site-studio: the package is missing a file it needs")
    return parse(text, DEFAULT_LOOK_REL, shipped=True)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read(), path)


# ------------------------------------------------------------------------------------------------ render
def part_markup(construct, part, look=None):
    """The template text for one part: the look's own, else the default look's."""
    if construct not in CONSTRUCTS or part not in CONSTRUCTS[construct]["parts"]:
        raise LookError("no such construct part: %s.%s; correct the name in the look file (site/looks/<name>.json), then run `/site-studio:look check`" % (construct, part))
    if look is not None and look.has(construct, part):
        return look.own_part(construct, part)
    base = default_look()
    if not base.has(construct, part):
        raise LookError("the default look has no markup for %s.%s yet; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (construct, part))
    return base.own_part(construct, part)


def assets_for(construct, look=None):
    """The plugin output files (`css`, `js`, `schema-4`) a page links where it holds `construct`, in the order
    the look names them. A look that carries its own entry for the construct decides, by its `assets` (none
    named means none linked: a template look brings its own stylesheet); a construct the look omits is linked
    as the default look says, the same rule as its markup (R5.2: the default look's entries carry 0.3.1's
    links, so `blocks.css` and `video.js` appear exactly where 0.3.1 puts them)."""
    if construct not in CONSTRUCTS:
        raise LookError("no such construct: %s; correct the name in the look file (site/looks/<name>.json), then run `/site-studio:look check`" % construct)
    if look is not None and construct in look.constructs:
        return tuple(look.assets.get(construct, ()))
    return tuple(default_look().assets.get(construct, ()))


_BLOCK_IMG_CLASS = re.compile(r"^<img\s+class=\"([^\"{}]*)\"")


def block_image_tag(tag, look=None):
    """An image tag a plugin block holds, marked the way the look's `block-image` entry marks it: the literal
    classes on its `plain` part's `<img>` (the default look: `ss-img`) are put on `tag`, an `<img ...>` the
    caller's environment already built. This is the ONE place the class is applied (it was a string replace
    in `content.py`); an environment that renders the `block-image` construct itself passes its own tag
    through `env.block_image` and never reaches here. A look whose `block-image` carries no class leaves the
    tag as it was."""
    m = _BLOCK_IMG_CLASS.match(part_markup("block-image", "plain", look))
    if not m:
        return tag
    return tag.replace("<img ", '<img class="%s" ' % m.group(1), 1)


def render(construct, part, values, look=None):
    """Fill one part with `values` ({slot name: python value}). Every slot is escaped or validated by its
    KIND in CONSTRUCTS, whatever the look says. A slot the template uses that `values` lacks, and a value
    for a slot the part does not have, are refused (a programming error, never a blank)."""
    template = part_markup(construct, part, look)
    table = CONSTRUCTS[construct]["parts"][part]
    for k in values:
        if k not in table:
            raise LookError("%s.%s has no slot %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (construct, part, k))
    def fill(m):
        name = m.group(1)
        if name not in values:
            raise LookError("%s.%s: the slot {{%s}} was given no value; correct the slot name in the look file "
                            "(site/looks/<name>.json), then run `/site-studio:look check`" % (construct, part, name))
        v, kind = values[name], table[name]
        if kind == HTML:
            if not isinstance(v, str):
                raise LookError("%s.%s: the html slot {{%s}} needs a string" % (construct, part, name))
            return v
        if kind == INT:
            return safe_int(v)
        if not isinstance(v, str):
            raise LookError("%s.%s: the %s slot {{%s}} needs a string" % (construct, part, kind, name))
        if kind == TEXT:
            return esc(v)
        if kind == URL:
            return esc(safe_url(v))
        if kind == CONTACT:
            return esc(safe_url(v, allow_mailto=True))
        if kind == SRCSET:
            return esc(safe_srcset(v))
        if kind == EMBED:
            return esc(safe_embed(v))
        if kind == POSITION:
            return esc(safe_position(v))
        raise LookError("unknown slot kind %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % kind)
    return _SLOT.sub(fill, template)
