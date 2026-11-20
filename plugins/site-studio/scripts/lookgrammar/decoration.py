"""lookgrammar/decoration.py -- a DECORATION in a look: an allow-listed inline `<svg>` subtree a look part may hold from
site-studio 0.5.0 (design-movement-view sections 3.4 and 9; group movement-view step 6). Python 3.9, standard library only.
Imports nothing from `looks`, which imports this: the look grammar's part parser class is handed in (`reader`).

THE ONE PARSER. The rules are checks on the tags `looks._PartParser` hands over, never a second parser and never a pattern
over raw markup (the standard of review step G2, F1). `reader(looks._PartParser)` is that parser with the rules mixed in:
outside an `<svg>` subtree every tag goes to the part parser's own rules unchanged; from an `<svg>` start tag to its end
tag the decoration rules below decide, and the part parser's `<svg>` refusal (`ELEMENT_REFUSALS`) is never reached. A
subtree that breaks a rule is refused with one line per broken rule, each naming the element or attribute. The part
parser's own refusals of a comment, a CDATA section, a processing instruction and a declaration apply inside the subtree
too, because those handlers are not overridden here (the `--!>` comment form: `test_decoration.py`).

THE FORM (design 9.2; OURS, the allow-list method DOCUMENTED: DOMPurify, OWASP XSS prevention, MDN `<use>` and `fill`):
    root          `<svg>` with only `class viewBox width height preserveAspectRatio aria-hidden focusable role xmlns`
                  and the paint attributes below, under the same value rules (coordinator ruling, step 5c);
                  `role` only `presentation` or `none`, or `img` together with `aria-hidden="true"` (an unnamed image is
                  announced as one); `xmlns` only exactly `http://www.w3.org/2000/svg`. `aria-hidden="true"` is NOT
                  required (a derived look copies the page's markup unchanged); `notes` says so on every look instead.
    descendants   `g path circle ellipse line polyline polygon rect`, and for a gradient `defs linearGradient
                  radialGradient stop`; attributes from the geometry, paint and gradient lists below, `class` and `id`.
    values        `id` a slug; `class` names (the part grammar's own class-token rule); `fill` or `stroke` exactly
                  `url(#<slug>)` naming an `id` defined inside the same subtree; every other value `^[A-Za-z0-9
                  #.,%()+-]*$` holding no `url` in any letter case (CSS function names are case-insensitive).
    look-wide     an `id` written inside a decoration is written once in the look (`look_problems`: a browser resolves
                  `#<slug>` across the whole page). Stated limit: page content outside the look, and a part the build
                  repeats on one page (a card, a step), can still repeat it.
    size, text    no slot, no text node holding a letter (a character reference is read as the character it names), at
                  most `MAX_CHARS` characters from `<svg` to the end of `</svg>`.
Names are compared case-insensitively because `html.parser` hands element and attribute names over in lower case (Prior
art, Python `html.parser`); the look stores and the build emits the part's literal text as the person's page wrote it.

    reader(cls)                       the part parser class with the decoration rules (`looks.check_part` uses it)
    found(constructs, cls)            [(construct, part, decoration)] of every `<svg>` subtree in a look's parts
    holds(constructs, cls)            a subtree that meets every rule is in the look (`looks._decoration_needs`: 0.5.0)
    look_problems(where, constructs, cls)   the look-wide `id` rule, one line per id
    listing(constructs, cls)          the lines `look.py check` and `use` print beside the literal words
"""
import html
import re

RELEASE = "0.5.0"
MAX_CHARS = 20000
SVG_NS = "http://www.w3.org/2000/svg"

# Canonical spellings, for the lines a person reads; every comparison is on the lower-case name `html.parser` gives.
_SPELL = {"viewbox": "viewBox", "preserveaspectratio": "preserveAspectRatio", "pathlength": "pathLength",
          "gradientunits": "gradientUnits", "gradienttransform": "gradientTransform", "spreadmethod": "spreadMethod",
          "lineargradient": "linearGradient", "radialgradient": "radialGradient", "foreignobject": "foreignObject",
          "clippath": "clipPath", "animatemotion": "animateMotion", "animatetransform": "animateTransform"}
SHAPES = ("g", "path", "circle", "ellipse", "line", "polyline", "polygon", "rect")
GRADIENT_ELEMENTS = ("defs", "lineargradient", "radialgradient", "stop")
ELEMENTS = frozenset(SHAPES + GRADIENT_ELEMENTS)
GEOMETRY = ("d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height", "points", "transform",
            "pathlength")
PAINT = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset",
         "stroke-miterlimit", "opacity", "fill-opacity", "stroke-opacity", "fill-rule", "vector-effect")
# The root's own attributes, and the paint attributes, which the root may carry too under the same value rules (coordinator
# ruling, step 5c: a ribbon written `<svg ... fill="none">` paints every shape inside it, as SVG inherits paint).
ROOT_ATTRS = frozenset(("class", "viewbox", "width", "height", "preserveaspectratio", "aria-hidden", "focusable", "role",
                        "xmlns") + PAINT)
GRADIENT = ("offset", "stop-color", "stop-opacity", "gradientunits", "gradienttransform", "spreadmethod", "fx", "fy")
ATTRS = frozenset(GEOMETRY + PAINT + GRADIENT + ("class", "id"))
PAINT_SERVER_ATTRS = ("fill", "stroke")
CLOSED = {"role": ("presentation", "none", "img"), "aria-hidden": ("true", "false"), "focusable": ("true", "false")}

# Every refusal by name, with its own reason (design 9.2: "refused with its own line, by name").
NAMED_ELEMENTS = {
    "script": "a look is markup, never code",
    "style": "a decoration carries no stylesheet text",
    "use": "`<use>` can load another file (MDN)",
    "image": "`<image>` loads a file",
    "a": "a decoration is not a link",
    "foreignobject": "`<foreignObject>` carries markup the decoration rules do not read",
    "text": "a decoration holds no text",
    "title": "a decoration holds no title: it has no name to announce",
    "desc": "a decoration holds no description: it has no name to announce",
    "pattern": "a decoration may reference a gradient in its own subtree, nothing else",
    "mask": "a decoration may reference a gradient in its own subtree, nothing else",
    "clippath": "a decoration may reference a gradient in its own subtree, nothing else",
    "filter": "a decoration may reference a gradient in its own subtree, nothing else",
    "animate": "an animation changes an attribute after the look was checked",
    "animatemotion": "an animation changes an attribute after the look was checked",
    "animatetransform": "an animation changes an attribute after the look was checked",
    "set": "an animation changes an attribute after the look was checked",
}
NAMED_ATTRS = {
    "href": "an `href` can load another file",
    "xlink:href": "an `xlink:href` can load another file",
    "style": "a decoration carries no style; write each property as its own attribute",
}
_SLUG = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")
_VALUE = re.compile(r"[A-Za-z0-9 #.,%()+-]*")
_PAINT_REF = re.compile(r"url\(#([A-Za-z][A-Za-z0-9_-]{0,39})\)")
_CLASS_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_SLOT_CHARS = ("", "")
_FIX = ("a decoration holds only g, path, circle, ellipse, line, polyline, polygon and rect, and for a gradient defs, "
        "linearGradient, radialGradient and stop; with geometry, paint and gradient attributes, class and id; remove the rest "
        "from the look part, or leave the part to the default look")


def spell(name):
    return _SPELL.get(name, name)


class _Subtree(object):
    """One `<svg>` subtree while it is read, then as `found` reports it."""

    def __init__(self, start, depth, nproblems, root):
        self.start, self.end, self.depth, self.nproblems = start, None, depth, nproblems
        self.root, self.ids, self.refs, self.clean = root, [], [], False


class _Rules(object):
    """Mixed in before the part parser class (`reader`); calls it through `super()` for everything outside a subtree."""

    def __init__(self, *args, **kwargs):
        super(_Rules, self).__init__(*args, **kwargs)
        self.text, self.deco, self.decorations, self.ids_outside = "", None, [], []

    def feed(self, data):
        self.text += data
        super(_Rules, self).feed(data)

    def close(self):
        super(_Rules, self).close()
        if self.deco is not None:                 # never closed: the part parser's own stack names the open element
            self._finish(len(self.text))
        ids = [i for d in self.decorations for i in d.ids]
        for i in sorted(set(ids)):
            if ids.count(i) + self.ids_outside.count(i) > 1:
                self.bad("%s: the id %r is written twice in this part; a decoration's id is written once in the look"
                         % (self.ctx, i), "give each element its own id")

    def _offset(self):
        line, col = self.getpos()
        at = 0
        for _ in range(line - 1):
            at = self.text.index("\n", at) + 1
        return at + col

    # -- tags
    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, True)

    def _open(self, tag, attrs, selfclose):
        if self.deco is None and tag != "svg":
            self.ids_outside.extend(v for n, v in attrs if n == "id" and v)
            self._start(tag, attrs, selfclose)
            return
        self.elements.append(tag)
        self.seen_attrs.extend(attrs)
        if self.deco is None:
            self.deco = _Subtree(self._offset(), len(self.stack), len(self.problems), dict(attrs))
            self._root_attrs(attrs)
        elif any(c in tag for c in _SLOT_CHARS):
            self.bad("%s: a slot inside a decoration (in a tag name)" % self.ctx, "a decoration holds no slot")
        elif tag in NAMED_ELEMENTS:
            self.bad("%s: <%s> is refused in a decoration: %s" % (self.ctx, spell(tag), NAMED_ELEMENTS[tag]),
                     "remove the <%s>" % spell(tag))
            self._attrs_of(tag, attrs, False)
        elif tag not in ELEMENTS:
            self.bad("%s: <%s> is not an element a decoration may hold" % (self.ctx, spell(tag)), _FIX)
            self._attrs_of(tag, attrs, False)
        else:
            self._attrs_of(tag, attrs, False)
        if not selfclose:
            self.stack.append(tag)
        elif len(self.stack) == self.deco.depth:   # `<svg/>`: a subtree that ends where it starts
            self._finish(self.deco.start + len(self.get_starttag_text() or ""))

    def handle_endtag(self, tag):
        if self.deco is None:
            super(_Rules, self).handle_endtag(tag)
            return
        super(_Rules, self).handle_endtag(tag)
        if len(self.stack) == self.deco.depth:          # the position is still this end tag's own until it returns
            end = self.text.find(">", self._offset())
            self._finish(end + 1 if end >= 0 else len(self.text))

    def _finish(self, end):
        d, self.deco = self.deco, None
        d.end = end
        if end - d.start > MAX_CHARS:
            self.bad("%s: a decoration of %d characters; at most %d" % (self.ctx, end - d.start, MAX_CHARS),
                     "simplify the drawing, or draw it in the site's own stylesheet")
        for slug, where in d.refs:
            if slug not in d.ids:
                self.bad("%s: %s names url(#%s), and no id %r is defined inside this decoration"
                         % (self.ctx, where, slug, slug), "define the gradient inside the same svg, or remove the reference")
        d.clean = len(self.problems) == d.nproblems
        self.decorations.append(d)

    # -- text
    def handle_data(self, data):
        if self.deco is None:
            super(_Rules, self).handle_data(data)
        elif any(c in data for c in _SLOT_CHARS):
            self.bad("%s: a slot inside a decoration" % self.ctx, "a decoration holds no slot")
        elif "<" in data:
            self.bad("%s: a '<' that does not open a tag, inside a decoration" % self.ctx, "write a literal < as &lt;")
        elif any(ch.isalpha() for ch in data):
            self.bad("%s: text %r inside a decoration; a decoration holds no words" % (self.ctx, data.strip()[:30]),
                     "remove the text")

    def handle_entityref(self, name):
        self._reference("&%s;" % name)

    def handle_charref(self, name):
        self._reference("&#%s;" % name)

    def _reference(self, ref):
        if self.deco is None:
            super(_Rules, self).handle_data("")
        else:
            self.handle_data(html.unescape(ref))

    # -- attributes
    def _root_attrs(self, attrs):
        self._attrs_of("svg", attrs, True)
        names = dict(attrs)
        if names.get("role") == "img" and names.get("aria-hidden") != "true":
            self.bad("%s: a decoration's svg has the role img and no aria-hidden of true: an image with no name is "
                     "announced as one" % self.ctx, "make the role presentation, or set aria-hidden to true")

    def _attrs_of(self, tag, attrs, root):
        seen = set()
        for name, value in attrs:
            value = "" if value is None else value
            where = "<%s %s>" % (spell(tag), spell(name))
            if any(c in name + value for c in _SLOT_CHARS):
                self.bad("%s: a slot inside a decoration (%s)" % (self.ctx, where), "a decoration holds no slot")
            elif name in seen:
                self.bad("%s: %s is written twice" % (self.ctx, where), "write it once")
            elif name.startswith("on"):
                self.bad("%s: %s is refused in a decoration: an event handler is code" % (self.ctx, where), "remove it")
            elif name in NAMED_ATTRS:
                self.bad("%s: %s is refused in a decoration: %s" % (self.ctx, where, NAMED_ATTRS[name]), "remove it")
            elif name not in (ROOT_ATTRS if root else ATTRS):
                self.bad("%s: %s is not an attribute a decoration's <%s> may carry" % (self.ctx, where, spell(tag)), _FIX)
            else:
                self._value(tag, name, value, root, where)
            seen.add(name)

    def _value(self, tag, name, value, root, where):
        bad = None
        ref = _PAINT_REF.fullmatch(value) if name in PAINT_SERVER_ATTRS else None
        if ref:
            self.deco.refs.append((ref.group(1), where))
        elif root and name == "xmlns":
            bad = None if value == SVG_NS else "may be exactly %s only" % SVG_NS
        elif root and name in CLOSED:
            bad = None if value in CLOSED[name] else "may be one of: %s" % ", ".join(CLOSED[name])
        elif name == "id":
            bad = None if _SLUG.fullmatch(value) else "must be a name: a letter, then letters, digits, - or _ (at most 40)"
            if not bad:
                self.deco.ids.append(value)
        elif name == "class":
            bad = None if all(_CLASS_TOKEN.fullmatch(t) for t in value.split()) else "holds a class token that is not a name"
        elif "url" in value.lower():
            bad = "holds `url` (in any letter case); only fill or stroke may be exactly url(#<id>) of a gradient in this decoration"
        elif not _VALUE.fullmatch(value):
            bad = "holds a character a decoration's value may not: letters, digits, spaces and # . , % ( ) + - only"
        if bad:
            self.bad("%s: %s=%r %s" % (self.ctx, where, value[:60], bad), "write the value in that form, or remove it")


_READERS = {}


def reader(parser_cls):
    """`parser_cls` (`looks._PartParser`) with the decoration rules mixed in; one class per parser class."""
    if parser_cls not in _READERS:
        _READERS[parser_cls] = type("DecorationReader", (_Rules, parser_cls), {})
    return _READERS[parser_cls]


def read(construct, part, text, parser_cls):
    """The reader after it has read one part's raw text (slots left as `{{name}}`: a slot inside a decoration is refused
    either way). A part `html.parser` cannot read yields what was read before the error; `parse` refuses it."""
    p = reader(parser_cls)("%s.%s" % (construct, part), {}, False, False)
    try:
        p.feed(text)
        p.close()
    except Exception:                                               # noqa: BLE001 -- html.parser's own errors
        pass
    return p


def found(constructs, parser_cls):
    """[(construct, part, decoration)] of every `<svg>` subtree in `constructs` ({id: {part: markup}}), in order; a
    decoration's `clean` says whether it met every rule, `root` holds its root attributes, `ids` the ids it defines."""
    out = []
    for cid, parts in sorted(constructs.items()):
        for pn, text in sorted(parts.items()):
            if isinstance(text, str):
                out.extend((cid, pn, d) for d in read(cid, pn, text, parser_cls).decorations)
    return out


def holds(constructs, parser_cls):
    """True when a decoration that meets every rule is in the look: such a look needs `RELEASE` (design 3.4)."""
    return any(d.clean for _c, _p, d in found(constructs, parser_cls))


def look_problems(where, constructs, parser_cls):
    """One line per `id` that a decoration writes and another part of the look writes too (design 9.2); an id written
    twice in ONE part is that part's own line (`_Rules.close`)."""
    parts_of, in_deco = {}, set()
    for cid, parts in sorted(constructs.items()):
        for pn, text in sorted(parts.items()):
            p = read(cid, pn, text, parser_cls)
            deco_ids = [i for d in p.decorations for i in d.ids]
            in_deco.update(deco_ids)
            for i in set(deco_ids + p.ids_outside):
                parts_of.setdefault(i, []).append("%s.%s" % (cid, pn))
    return ["%s: the id %r is written in %s; a decoration's id is written once in the look -- fix: give each element "
            "its own id" % (where, i, " and ".join(parts_of[i])) for i in sorted(in_deco) if len(parts_of[i]) > 1]


def listing(constructs, parser_cls):
    """The lines `look.py check` and `use` print beside the literal words: each decoration by construct and part, and a
    note for a root without `aria-hidden="true"` (MDN: a purely decorative image is its named use)."""
    out = []
    for cid, pn, d in found(constructs, parser_cls):
        out.append("decoration in %s.%s: an svg of %d character(s)%s"
                   % (cid, pn, d.end - d.start, "" if d.clean else ", refused by the decoration rules"))
        if d.root.get("aria-hidden") != "true":
            out.append("note: the decoration in %s.%s has no aria-hidden of true on its svg; set it so a screen reader "
                       "skips the drawing" % (cid, pn))
    return out
