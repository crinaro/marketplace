#!/usr/bin/env python3
"""parity_classes.py -- how two builds of one site are compared, and which differences a visitor cannot see
(design-template-fidelity section 5, R2-13, R2-14, R4 rows 10 and 11; step 1.7). Python 3.9, standard library only.

Pure functions over two `{path: bytes}` outputs. No I/O, no import of `adopt`, `build` or `deploy`: the three of
them import THIS module (0.4.0 step 1.4 for the build's raise report, 1.6 for the publish re-check, 1.9 for
adopt), so `build.py` never has to import `adopt`.

    normalise_html()     the comparison form of an HTML page: comments removed, whitespace between tags one
                         space, attributes sorted, character references decoded, PARITY_IGNORED dropped. One
                         token per line. Moved here from `adopt.py` byte for byte (the test file proves it).
    compare_builds()     the (kind, path, detail) list of differing files; empty means EQUAL.
    file_hunks()         every differing hunk of one file, classed head, body or file.
    classify_differences()  the 5.1 classifier: every hunk of every differing file, each either VISIBLE or
                         MARKUP (invisible), with the verdict EQUAL, MARKUP-ONLY or DIFFERENT. NEW in 0.4.0.
    recheck()            rules 3 to 5 for a recorded token set against ONE build (the publish-time re-check,
                         step 1.6): which of the tokens a stylesheet or script now names.
    difference_groups() / difference_report()   the grouped report 0.3.1 printed, now with the `markup` class.
    kind()               the closed, never-echoed label of a hunk, for the blocker report (R3): `head-only`,
                         `text`, `element/<html element>` or `element/other`, `attribute/<standard attribute>` or
                         `attribute/other`, `file/<family>`, `only-local/<family>`, `only-plugin/<family>`.

WHAT IS INVISIBLE (5.1). A differing pair of tokens is invisible only when ALL hold:
    1. both are start tags of the same element at the same position; the streams differ in no text token, no
       end tag and no added or removed element (a hunk of unequal length is never paired);
    2. their attributes differ only in `class` tokens, `data-*` attributes, or an `id` ADDED where the local
       build's tag had none (or, on a link that opens in the same window, the `noopener` and `noreferrer` tokens of `rel`:
       `parity_whitespace.rel_invisible`). A changed or removed `id` is always visible (a fragment is a published address);
    3. neither build names the token in a stylesheet (after CSS escapes are decoded), a script (`.js`/`.mjs`, an
       inline `<script>`, an `on*=` attribute; a `data-*` name in its dashed, `dataset` camelCase and
       prefix-stripped forms), an `href` fragment or `url(#x)`, or, for an `id`, an IDREF attribute. The search is
       a plain substring search, so it errs toward visible;
    4. neither build's CSS selects on that attribute at all (`[class`, `[id`, `[data-<name>`) or uses `attr(`;
    5. neither build loads anything parity cannot read: an off-origin or protocol-relative stylesheet, preload,
       modulepreload, `<script src>` or `@import`, or any absolute URL inside a script (any `<script>` body,
       a JSON-LD block included: it errs toward visible). One of those makes every markup difference visible,
       and each one is named. No exception for font stylesheets (owner decision 13).
Everything else is visible: element names, text, `href`, `src`, `alt`, `title`, `style`, `aria-*`, `role`, a
changed or removed `id`, any other attribute, and any differing non-HTML file. A page's `<meta name="description">` is
VISIBLE too (owner ruling, 2026-11-18): no page shows it, but a search result shows it before the page is opened.
`description_changes` lists each page where it differs, for adopt to name as an ACCEPT.

WHITESPACE (template-fidelity G3, `parity_whitespace.py`). A hunk that is exactly one whitespace token, present in one
build only, is invisible (class `markup`, kind `text`, no token) when a browser collapses it: it touches a block edge,
nothing keeps whitespace there and nothing in either build can make that block inline. Any other hunk is judged as before.

LIMITS, stated once per run by the caller (5.3): the check is static. A script that enumerates attributes
generically (`dataset` iteration, `classList` loops, `querySelectorAll('[class]')`) without naming the token is
not detected; a token built from parts (`'foo' + 'Bar'`) is not detected; anything loaded off-origin is
unreadable and so makes the verdict unreachable; rendered pixels are not compared.

`kind()` IS A LABEL, never an input to a verdict. It reads the hunk's own lines, so it is approximate for an
attribute value that itself holds a quote followed by something that looks like an attribute; it can only
return a member of the closed enumeration (an unknown element or attribute is `other`, a count, never echoed).
"""
import difflib
import html.parser
import posixpath
import re
import parity_whitespace

PARITY_IGNORED = {
    "files": ("sitemap.xml", "robots.txt"),
    "head": ("link[rel=canonical]", "meta[property^=og:]", "meta[name^=twitter:]"),
    "img_attrs": ("srcset", "sizes", "width", "height", "loading", "decoding"),
}

# The stated date rule (named change M13). Applied to both builds' text output.
DATE_RULES = (
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"), "<date>"),
    (re.compile(r"((?:&copy;|&#169;|&#xa9;|©|\(c\))\s*)(?:19|20)\d{2}(?:\s*[-–—]\s*(?:19|20)\d{2})?", re.I),
     r"\1<year>"),
)

VERDICTS = ("EQUAL", "MARKUP-ONLY", "DIFFERENT")

HUNKS_PER_FILE = 20        # hunks read per file by the PRINTED report; classify_differences reads every hunk
CAUSE_LINES_MAX = 40       # cause lines printed; more says how many it did not list
CAUSE_EXAMPLES = 3         # pages named on a cause that spans several
HUNK_CLASSES = {
    "head": "an addition inside <head>, apart from the body",
    "body": "body",
    "file": "file content",
    "markup": "markup a visitor does not see",
}

# The families of a file (the same ten `no-landing` reports, design R3): a closed list, so a file's name never
# reaches a report, only its family.
FAMILIES = ("markdown", "html", "image", "video", "pdf", "data", "script", "style", "font", "other")
_FAMILY_EXTS = (
    ("markdown", (".md", ".markdown")),
    ("html", (".html", ".htm")),
    ("image", (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp")),
    ("video", (".mp4", ".webm", ".mov", ".m4v", ".ogv")),
    ("pdf", (".pdf",)),
    ("data", (".json", ".xml", ".txt", ".csv", ".yml", ".yaml", ".toml", ".webmanifest")),
    ("script", (".js", ".mjs", ".cjs")),
    ("style", (".css",)),
    ("font", (".woff", ".woff2", ".ttf", ".otf", ".eot")),
)

STANDARD_ELEMENTS = frozenset("""
a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption cite code col
colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 h3
h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark math menu meta
meter nav noscript object ol optgroup option output p param picture pre progress q rp rt ruby s samp script search
section select slot small source span strong style sub summary sup svg table tbody td template textarea tfoot th
thead time title tr track u ul var video wbr""".split())

STANDARD_ATTRIBUTES = frozenset("""
accept accept-charset accesskey action allow allowfullscreen alt as async autocapitalize autocomplete autofocus
autoplay charset checked cite class color cols colspan content contenteditable controls coords crossorigin
datetime decoding default defer dir dirname disabled download draggable enctype enterkeyhint fetchpriority for form
formaction headers height hidden high href hreflang http-equiv id imagesizes imagesrcset inert inputmode integrity
is ismap itemid itemprop itemref itemscope itemtype kind label lang list loading loop low max maxlength media
method min minlength multiple muted name nonce novalidate open optimum pattern ping placeholder playsinline popover
poster preload readonly referrerpolicy rel required reversed role rows rowspan sandbox scope selected shape size
sizes slot span spellcheck src srcdoc srclang srcset start step style tabindex target title translate type usemap
value width wrap xmlns
aria-activedescendant aria-atomic aria-autocomplete aria-braillelabel aria-brailleroledescription aria-busy
aria-checked aria-colcount aria-colindex aria-colspan aria-controls aria-current aria-describedby aria-description
aria-details aria-disabled aria-dropeffect aria-errormessage aria-expanded aria-flowto aria-grabbed aria-haspopup
aria-hidden aria-invalid aria-keyshortcuts aria-label aria-labelledby aria-level aria-live aria-modal
aria-multiline aria-multiselectable aria-orientation aria-owns aria-placeholder aria-posinset aria-pressed
aria-readonly aria-relevant aria-required aria-roledescription aria-rowcount aria-rowindex aria-rowspan
aria-selected aria-setsize aria-sort aria-valuemax aria-valuemin aria-valuenow aria-valuetext""".split())

# Attributes whose value is a list of ids (rule 3's IDREF clause). `<use href>` is covered by the href fragments.
IDREF_ATTRS = frozenset(("for", "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns",
                         "aria-activedescendant", "aria-details", "aria-errormessage", "aria-flowto",
                         "headers", "list", "form", "popovertarget", "commandfor"))


# ---------------------------------------------------------------- normalisation (moved from adopt.py, R2-13)

class _Canon(html.parser.HTMLParser):
    """The canonicalising parser. `out` holds `(line, element, attributes, role)`: the line is what `normalise_html`
    writes; the element and the sorted attribute list of a start tag are kept beside it, so the 5.1 classifier
    reads real attributes and never has to re-parse a line; the role (`parity_whitespace.sites`) says what the token
    really is, so a text that merely reads `<ws>` is never whitespace."""
    VOID = ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
            "source", "track", "wbr")

    def __init__(self, ignored):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.out = []
        self.ignored = ignored

    def _skip(self, tag, attrs):
        d = dict((k, (v or "")) for k, v in attrs)
        if tag == "link" and "canonical" in d.get("rel", "").lower().split():
            return "link[rel=canonical]" in self.ignored["head"]
        if tag == "meta":
            if d.get("property", "").lower().startswith("og:"):
                return "meta[property^=og:]" in self.ignored["head"]
            if d.get("name", "").lower().startswith("twitter:"):
                return "meta[name^=twitter:]" in self.ignored["head"]
        return False

    def handle_starttag(self, tag, attrs):
        if self._skip(tag, attrs):
            return
        if tag == "img":
            attrs = [(k, v) for k, v in attrs if k not in self.ignored["img_attrs"]]
        ordered = sorted(attrs, key=lambda kv: kv[0])
        parts = []
        for k, v in ordered:
            parts.append(k if v is None else '%s="%s"' % (k, v))
        self.out.append(("<%s%s>" % (tag, (" " + " ".join(parts)) if parts else ""), tag, tuple(ordered), ("start",)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self.out.append(("</%s>" % tag, None, None, ("end", tag)))

    def handle_data(self, data):
        data = data.replace("\r\n", "\n")
        if not data.strip():
            if self.out and not self.out[-1][0] == " ":
                self.out.append((" ", None, None, ("ws",)))
        else:
            self.out.append((data, None, None, ("text",)))

    def handle_decl(self, decl):
        self.out.append(("<!%s>" % decl.lower(), None, None, ("decl",)))

    def handle_comment(self, data):
        pass


def _tokens(text, ignored=None):
    """[(line, element, attributes, role)] for a page: whitespace merged and trimmed, a whitespace token written `<ws>`."""
    p = _Canon(ignored or PARITY_IGNORED)
    p.feed(text.replace("\r\n", "\n"))
    p.close()
    merged = []
    for t in p.out:
        if t[3][0] == "ws" and merged and merged[-1][3][0] == "ws":
            continue
        merged.append(t)
    while merged and merged[0][3][0] == "ws":
        merged.pop(0)
    while merged and merged[-1][3][0] == "ws":
        merged.pop()
    return [(l if r[0] != "ws" else "<ws>", n, a, r) for l, n, a, r in merged]


def normalise_html(text, ignored=None):
    """The comparison form of an HTML page (design 6.4.5): comments removed, whitespace between tags
    one space, attributes sorted within each tag, character references decoded, and the parts the
    plugin adds that the examples never wrote (PARITY_IGNORED) dropped. One token per line."""
    return "\n".join(t[0] for t in _tokens(text, ignored))


def normalise_dates(text):
    for rx, repl in DATE_RULES:
        text = rx.sub(repl, text)
    return text


def normalise_file(rel, data):
    """A comparable form of one output file: normalised text, or the raw bytes for binary files."""
    low = rel.lower()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    if low.endswith((".html", ".htm")):
        text = normalise_html(text)
    else:
        text = text.replace("\r\n", "\n")
    return normalise_dates(text).encode("utf-8")


def _is_page(rel):
    return rel.lower().endswith((".html", ".htm"))


def _page_form(text, ignored):
    """(the dated, normalised text of a page, a list aligned with its lines). The list holds `(element,
    attributes)` for a line that is exactly one start tag, `(WS, Site)` for a whitespace token (`parity_whitespace`),
    else None: a token that spans lines (a value with a newline), or a date rule that merged lines, is never
    paired, so it can only read as visible."""
    toks = _tokens(text, ignored)
    joined = "\n".join(t[0] for t in toks)
    dated = normalise_dates(joined)
    lines = dated.split("\n")
    if len(lines) != joined.count("\n") + 1:
        return dated, [None] * len(lines)
    places = parity_whitespace.sites(toks)
    info = []
    for i, (line, name, attrs, _role) in enumerate(toks):
        n = line.count("\n") + 1
        info.extend([(parity_whitespace.WS, places[i])] if i in places else
                    [(name, attrs)] if (n == 1 and name is not None) else [None] * n)
    return dated, info


def _comparable(p, a, b, ignored):
    """The two comparison forms (bytes) of one output file present in both builds."""
    if _is_page(p):
        return (_page_form(a.decode("utf-8", "replace"), ignored)[0].encode("utf-8"),
                _page_form(b.decode("utf-8", "replace"), ignored)[0].encode("utf-8"))
    return normalise_file(p, a), normalise_file(p, b)


def compare_builds(local, plugin, ignored=None):
    """Compare two {path: bytes} outputs after the stated exclusions and normalisation. Returns the
    list of differences: (kind, path, detail); empty means EQUAL."""
    ignored = ignored or PARITY_IGNORED
    skip = set(ignored["files"])
    a = dict((p, d) for p, d in local.items() if p not in skip)
    b = dict((p, d) for p, d in plugin.items() if p not in skip)
    diffs = []
    for p in sorted(set(a) - set(b)):
        diffs.append(("only in the local build", p, ""))
    for p in sorted(set(b) - set(a)):
        diffs.append(("only in the plugin build", p, ""))
    for p in sorted(set(a) & set(b)):
        na, nb = _comparable(p, a[p], b[p], ignored)
        if na != nb:
            la = na.decode("utf-8", "replace").split("\n")
            lb = nb.decode("utf-8", "replace").split("\n")
            first = ""
            for i in range(max(len(la), len(lb))):
                x = la[i] if i < len(la) else "(end)"
                y = lb[i] if i < len(lb) else "(end)"
                if x != y:
                    first = "line %d: local %r vs plugin %r" % (i + 1, x[:70], y[:70])
                    break
            diffs.append(("differs", p, first or "binary content differs"))
    return diffs


# ---------------------------------------------------------------- what in a build can see a token (rules 3 to 5)

_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|(.))", re.S)
_URL_FRAGMENT = re.compile(r"url\(\s*[\"']?#([^)\"'\s]+)", re.I)
_CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?[\"']?\s*((?:https?:)?//[^\s\"')]+)", re.I)
_ATTR_FUNCTION = re.compile(r"\battr\s*\(", re.I)
_SCRIPT_URL = re.compile(r"(?:https?|wss?|ftp)://[^\s\"'`)]+|(?<=[\"'`(])//[A-Za-z0-9][^\s\"'`)]*", re.I)
_OFF_ORIGIN = re.compile(r"\s*(?:https?:)?//", re.I)


def css_unescape(text):
    """CSS escapes decoded: `md\\:flex` is `md:flex`, `\\31 0` is `10` (5.1 rule 3)."""
    def one(m):
        if m.group(1):
            cp = int(m.group(1), 16)
            return chr(cp) if 0 < cp <= 0x10FFFF and not 0xD800 <= cp <= 0xDFFF else "�"
        return m.group(2)
    return _CSS_ESCAPE.sub(one, text)


class _SinkParser(html.parser.HTMLParser):
    """Reads one page for the things that can see a token: style and script text, `style` and `on*=` values,
    `href` fragments, IDREF values, and the stylesheets, scripts and preloads loaded off-origin."""

    def __init__(self, sinks, where):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.sinks, self.where, self.open, self.buf = sinks, where, None, []

    def handle_starttag(self, tag, attrs):
        d = dict((k, v if v is not None else "") for k, v in attrs)
        if tag in ("script", "style"):
            self.open, self.buf = tag, []
        if tag == "link" and set(d.get("rel", "").lower().split()) & {"stylesheet", "preload", "modulepreload"} \
                and _OFF_ORIGIN.match(d.get("href", "")):
            self.sinks.external.append((self.where, d["href"].strip(), "link"))
        if tag == "script" and _OFF_ORIGIN.match(d.get("src", "")):
            self.sinks.external.append((self.where, d["src"].strip(), "script"))
        for k, v in d.items():
            if k == "style":
                self.sinks.add_css(self.where, v)
            elif k.startswith("on"):
                self.sinks.add_js(self.where, v)
            if k in ("href", "xlink:href") and "#" in v:
                self.sinks.fragments.setdefault(v.split("#", 1)[1], self.where)
            if k in IDREF_ATTRS:
                for ref in v.split():
                    self.sinks.idrefs.setdefault(ref, self.where)
            for frag in _URL_FRAGMENT.findall(v):
                self.sinks.fragments.setdefault(frag, self.where)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.open = None

    def handle_data(self, data):
        if self.open:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == self.open:
            text = "".join(self.buf)
            (self.sinks.add_css if tag == "style" else self.sinks.add_js)(self.where, text)
            self.open, self.buf = None, []


class Sinks:
    """Everything in the given builds that can see a class token, a `data-*` name or an `id`. `builds` is
    `[(label, {path: bytes})]`; a reason names the build and file, so a refusal can say which file now sees a token."""

    def __init__(self, builds):
        self.css, self.js, self.external = [], [], []
        self.css_raw, self._ws = [], None           # the stylesheets before their escapes are decoded
        self.fragments, self.idrefs = {}, {}
        self._memo = {}
        for label, files in builds:
            for path in sorted(files):
                self._read("%s build: %s" % (label, path), path, files[path])
        seen, out = set(), []
        for item in self.external:
            if item not in seen:
                seen.add(item)
                out.append(item)
        self.external = out

    def ws_facts(self):         # what both builds' CSS and scripts can do to whitespace, read once
        self._ws = self._ws or parity_whitespace.Facts(self.css_raw, [t for _w, t in self.js], self.external, css_unescape)
        return self._ws

    def add_css(self, where, text):
        self.css_raw.append(text)
        text = css_unescape(text)
        self.css.append((where, text))
        for url in _CSS_IMPORT.findall(text):
            self.external.append((where, url, "@import"))

    def add_js(self, where, text):
        self.js.append((where, text))
        for url in _SCRIPT_URL.findall(text):
            self.external.append((where, url, "script"))

    def _read(self, where, path, data):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return
        low = path.lower()
        for frag in _URL_FRAGMENT.findall(text):
            self.fragments.setdefault(frag, where)
        if low.endswith(".css"):
            self.add_css(where, text)
        elif low.endswith((".js", ".mjs")):
            self.add_js(where, text)
        elif _is_page(low):
            p = _SinkParser(self, where)
            p.feed(text)
            p.close()

    def external_reasons(self):
        return ["%s loads %s, which parity cannot read: markup differences count as visible" % (where, url)
                for where, url, _what in self.external]

    def problems(self, kind, name):
        """Why the token `(kind, name)` ("class", "data" or "id") is NOT invisible by rules 3 and 4: a list of
        sentences, empty when no stylesheet, script, fragment or IDREF sees it."""
        key = (kind, name)
        if key not in self._memo:
            self._memo[key] = self._problems(kind, name)
        return self._memo[key]

    def _problems(self, kind, name):
        forms = [name]
        if kind == "data":
            stripped = name[len("data-"):] if name.startswith("data-") else name
            camel = re.sub(r"-([a-z0-9])", lambda m: m.group(1).upper(), stripped)
            forms = [name, camel, stripped]
        attribute = {"class": "class", "id": "id"}.get(kind, name)
        selector = re.compile(r"\[\s*%s(?![\w-])" % re.escape(attribute), re.I)
        out = []
        for where, text in self.css:
            if any(f in text for f in forms):
                out.append("%s names it in a stylesheet" % where)
            if selector.search(text):
                out.append("%s selects on the %s attribute" % (where, attribute))
            if _ATTR_FUNCTION.search(text):
                out.append("%s reads attributes with attr()" % where)
        for where, text in self.js:
            if any(f in text for f in forms):
                out.append("%s names it in a script" % where)
        if kind == "id":
            if name in self.fragments:
                out.append("%s has an href fragment or url(#...) naming it" % self.fragments[name])
            if name in self.idrefs:
                out.append("%s has an IDREF attribute naming it" % self.idrefs[name])
        seen = set()
        return [r for r in out if not (r in seen or seen.add(r))]

    def reasons(self, kind, name):
        """`problems` plus rule 5: while anything off-origin is loaded, every token is visible."""
        return self.problems(kind, name) + self.external_reasons()


def recheck(tokens, files, ignored=None):
    """Rules 3 to 5 for a RECORDED token set against ONE build (the current plugin build; step 1.6's publish re-check).
    `tokens` is `{"class": [...], "data": [...], "id": [...]}`. Returns `[(kind, name, reason)]`: each token a
    stylesheet or script now names, an attribute selector or `attr(` now present, and every off-origin stylesheet or
    script now loaded (named once with kind `external`). Empty means the record still holds."""
    sinks = Sinks((("plugin", files),))
    out = []
    for kind in ("class", "data", "id"):
        for name in tokens.get(kind, ()):
            for reason in sinks.problems(kind, name):
                out.append((kind, name, reason))
    for reason in sinks.external_reasons():
        out.append(("external", "", reason))
    return out


# ---------------------------------------------------------------- the 5.1 pair test

def _class_tokens(value):
    return (value or "").split()


def _pair_tokens(x, y, rel_ok=None):
    """For two start tags `(element, attributes)` at the same position: the invisible tokens `[(kind, name)]` when
    every difference is of the invisible kinds (rules 1 and 2), else None (a visible pair). `x` is the local build's
    tag and `y` the plugin build's: an `id` is invisible only when `y` adds it where `x` had none. `rel_ok(element, a, b)` says
    whether a difference of `rel` alone is one no visitor meets (`parity_whitespace.rel_invisible`); it records no token."""
    if x[0] != y[0] or x[0] == parity_whitespace.WS:
        return None
    da, db = dict((k, normalise_dates(v) if v is not None else None) for k, v in x[1]), \
        dict((k, normalise_dates(v) if v is not None else None) for k, v in y[1])
    if len(da) != len(x[1]) or len(db) != len(y[1]):        # a repeated attribute: never paired
        return None
    tokens = []
    for k in sorted(set(da) | set(db)):
        if k in da and k in db and da[k] == db[k]:
            continue
        if k == "class":
            for t in sorted(set(_class_tokens(da.get(k))) ^ set(_class_tokens(db.get(k)))):
                tokens.append(("class", t))
        elif k.startswith("data-"):
            tokens.append(("data", k))
        elif k == "id" and k not in da and db.get(k):
            tokens.append(("id", db[k]))
        elif k == "rel" and rel_ok is not None and rel_ok(x[0], da, db):
            continue
        else:
            return None
    return tokens


# ---------------------------------------------------------------- hunks

def _head_span(lines):
    """(index of `<head>`, index of `</head>`) in a normalised page's token lines, or None."""
    start = next((i for i, l in enumerate(lines) if l == "<head>" or l.startswith("<head ")), None)
    end = next((i for i, l in enumerate(lines) if l == "</head>"), None)
    return (start, end) if start is not None and end is not None and start < end else None


def _inside(span, k1, k2):
    """True when tokens [k1, k2) (an insertion point when k1 == k2) lie between a page's `<head>` and `</head>`."""
    return span is not None and span[0] < k1 and k2 <= span[1]


def _visible_class(page, a, b, ha, hb, i1, i2, j1, j2):
    if not page:
        return "file"
    if (bool(a) != bool(b)) and _inside(ha, i1, i2) and _inside(hb, j1, j2):
        return "head"
    return "body"


class _Hunk(object):
    __slots__ = ("cls", "a", "b", "line", "why", "tokens")

    def __init__(self, cls, a, b, line, why="", tokens=()):
        self.cls, self.a, self.b, self.line, self.why, self.tokens = cls, a, b, line, why, tuple(tokens)

    def as_tuple(self):
        return (self.cls, self.a, self.b, self.line)


def _hunks(rel, na, nb, ia=None, ib=None, sinks=None):
    """Every differing hunk of one file as `_Hunk`s, from the two normalised forms. With `sinks` and the two aligned
    attribute lists, a block of equal length is paired token by token and each pair is `markup` (invisible) or
    visible by 5.1; without them every hunk is head, body or file, exactly as 0.3.1 classed it."""
    try:
        ta, tb = na.decode("utf-8"), nb.decode("utf-8")
    except UnicodeDecodeError:
        return [_Hunk("file", ["(binary content)"], ["(different binary content)"], 0)]
    la, lb = ta.split("\n"), tb.split("\n")
    page = _is_page(rel)
    ha, hb = (_head_span(la), _head_span(lb)) if page else (None, None)
    rel_ok = None
    if sinks is not None and page:
        base_target = any(l.startswith("<base ") and " target=" in l for l in la + lb)
        rel_ok = lambda el, da, db: parity_whitespace.rel_invisible(                       # noqa: E731
            el, da, db, base_target, [t for _w, t in sinks.css], [t for _w, t in sinks.js], bool(sinks.external))
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if sinks is not None and page and ia is not None and tag == "replace" and (i2 - i1) == (j2 - j1):
            runs = []
            for k in range(i2 - i1):
                x, y = la[i1 + k], lb[j1 + k]
                tokens, why = None, ""
                if ia[i1 + k] is not None and ib[j1 + k] is not None:
                    tokens = _pair_tokens(ia[i1 + k], ib[j1 + k], rel_ok)
                if tokens is not None:
                    reasons = []
                    for kind_, name in tokens:
                        reasons.extend(r for r in sinks.reasons(kind_, name) if r not in reasons)
                    if reasons:
                        tokens, why = None, "; ".join(reasons[:3])
                invisible = tokens is not None
                if runs and runs[-1]["invisible"] == invisible:
                    runs[-1]["pairs"].append((k, x, y))
                    runs[-1]["tokens"].extend(tokens or ())
                    if why and why not in runs[-1]["why"]:
                        runs[-1]["why"] = (runs[-1]["why"] + "; " + why).strip("; ")
                else:
                    runs.append({"invisible": invisible, "pairs": [(k, x, y)], "tokens": list(tokens or ()), "why": why})
            for run in runs:
                first, last = run["pairs"][0][0], run["pairs"][-1][0]
                a = [x for _k, x, _y in run["pairs"] if x != "<ws>"]
                b = [y for _k, _x, y in run["pairs"] if y != "<ws>"]
                if run["invisible"]:
                    cls = "markup"
                else:
                    cls = _visible_class(page, a, b, ha, hb, i1 + first, i1 + last + 1, j1 + first, j1 + last + 1)
                out.append(_Hunk(cls, a, b, i1 + first + 1, run["why"], run["tokens"]))
            continue
        # a whitespace token on one side is no content: a meta line one build writes against a bare newline in the
        # other is an ADDITION, however the diff happened to align the two
        a = [l for l in la[i1:i2] if l != "<ws>"]
        b = [l for l in lb[j1:j2] if l != "<ws>"]
        if sinks is not None and page and not a and not b and parity_whitespace.hunk_invisible(
                sinks.ws_facts(), ia, ib, i1, i2, j1, j2):
            out.append(_Hunk("markup", [], [], i1 + 1))
            continue
        out.append(_Hunk(_visible_class(page, a, b, ha, hb, i1, i2, j1, j2), a, b, i1 + 1))
    return out


def file_hunks(rel, na, nb):
    """[(class, local lines, plugin lines, 1-based line in the local form)] for every differing hunk of one file,
    from the two normalised forms. The class is per HUNK, never per page: `head` is a hunk that only ADDS lines (on
    either side) inside `<head>`; any other hunk of a page is `body`; a file that is not a page is `file`. So a
    page carrying both a head addition and a body change reports two hunks in two classes (dev #879, P3).
    The invisible-markup split needs both builds' sinks, so it lives in `classify_differences`."""
    return [h.as_tuple() for h in _hunks(rel, na, nb)]


def _clip(lines, n=80):
    s = " ".join(l for l in lines if l != "<ws>") or "(whitespace only)"
    return s if len(s) <= n else s[:n - 3] + "..."


def hunk_text(a, b):
    if not a and not b:
        return "the two differ in whitespace only"
    if not a:
        return "the plugin build adds %s" % _clip(b)
    if not b:
        return "the local build has %s and the plugin build does not" % _clip(a)
    return "local %s vs plugin %s" % (_clip(a, 50), _clip(b, 50))


# ---------------------------------------------------------------- kind(): the closed label of a hunk

def family(path):
    """The file's family: one of FAMILIES, from its extension alone (a name never reaches a report)."""
    ext = posixpath.splitext((path or "").lower())[1]
    for name, exts in _FAMILY_EXTS:
        if ext in exts:
            return name
    return "other"


_LINE_START = re.compile(r"<([A-Za-z][^\s>/]*)((?:\s.*)?)>\Z", re.S)
_LINE_END = re.compile(r"</([A-Za-z][^\s>]*)>\Z")
_LINE_ATTR = re.compile(r"\s+([^\s\"'=<>/]+)(?:=\"(.*?)\"(?=\s+[^\s\"'=<>/]+(?:=|\s|\Z)|\Z))?", re.S)


def _line_token(line):
    """("start", element, {attribute: value}) | ("end", element) | ("text",) for one normalised line."""
    m = _LINE_START.match(line)
    if m:
        return ("start", m.group(1).lower(), dict((n, v) for n, v in _LINE_ATTR.findall(m.group(2))))
    m = _LINE_END.match(line)
    if m:
        return ("end", m.group(1).lower())
    return ("text",)


def _body_kind(a, b):
    ta = [_line_token(l) for l in a if l != "<ws>"]
    tb = [_line_token(l) for l in b if l != "<ws>"]
    ea = [(t[0], t[1]) for t in ta if t[0] != "text"]
    eb = [(t[0], t[1]) for t in tb if t[0] != "text"]
    if ea != eb:
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ea, eb, autojunk=False).get_opcodes():
            if tag != "equal":
                name = (ea[i1:i2] or eb[j1:j2])[0][1]
                return "element/" + (name if name in STANDARD_ELEMENTS else "other")
    sa = [t for t in ta if t[0] == "start"]
    sb = [t for t in tb if t[0] == "start"]
    for x, y in zip(sa, sb):
        for name in sorted(set(x[2]) | set(y[2])):
            if x[2].get(name) != y[2].get(name):
                return "attribute/" + (name if name in STANDARD_ATTRIBUTES else "other")
    return "text"


def kind(cls, a=(), b=(), path=None):
    """The closed label of a hunk (design 8 RP, R4 rows 10 and 11), never carrying anything from the site:
        head            -> `head-only`
        file            -> `file/<family>` (a non-page file present in both builds)
        only-local / only-plugin -> `only-local/<family>` / `only-plugin/<family>` (a file in one build only)
        body, markup    -> `element/<html element>` or `element/other` (a custom element such as `<x-foo>` is
                           `other`), else `attribute/<standard attribute>` or `attribute/other`, else `text`
    `a` and `b` are the local and plugin lines of the hunk; `path` names the file."""
    if cls == "head":
        return "head-only"
    if cls in ("file", "only-local", "only-plugin"):
        return "%s/%s" % (cls, family(path))
    if cls in ("body", "markup"):
        return _body_kind(a, b)
    raise ValueError("kind(): unknown hunk class %r; this is a fault in site-studio: update the plugin, and report it on the plugin's GitHub issues page if it persists" % (cls,))


# ---------------------------------------------------------------- the classifier

class Difference(object):
    """One hunk of one file. `cls` is head, body, file, markup, only-local or only-plugin; `local` and `plugin` are
    the hunk's lines; `kind` is `kind()`'s label; `why` says why a markup-shaped pair is visible ("" otherwise)."""
    __slots__ = ("cls", "path", "line", "local", "plugin", "kind", "why", "tokens")

    def __init__(self, cls, path, line, local, plugin, why="", tokens=()):
        self.cls, self.path, self.line = cls, path, line
        self.local, self.plugin, self.why, self.tokens = tuple(local), tuple(plugin), why, tuple(tokens)
        self.kind = kind(cls, local, plugin, path)

    def __repr__(self):
        return "Difference(%s, %s:%s, %s)" % (self.cls, self.path, self.line, self.kind)


def classify_differences(local, plugin, ignored=None):
    """The 5.1 classifier over two `{path: bytes}` builds: `local` is the person's builder's output, `plugin` the
    plugin's. Reads EVERY hunk of every differing file (the print cap is `difference_report`'s). Returns

        verdict    EQUAL (nothing differs), MARKUP-ONLY (every difference is invisible) or DIFFERENT
        visible    [Difference]: every difference a visitor can see (cls head, body, file, only-local, only-plugin)
        markup     [Difference]: every difference a visitor cannot see (cls markup), listed apart, never folded in
        external   [(where, url, what)]: each stylesheet, script or import loaded off-origin (rule 5); while there is
                   one, nothing is invisible and the verdict cannot be MARKUP-ONLY
        tokens     {"class": [...], "data": [...], "id": [...]}: every invisible token, sorted (the record's `tokens`)
        files      `compare_builds`' list, unchanged
    """
    ignored = ignored or PARITY_IGNORED
    diffs = compare_builds(local, plugin, ignored)
    sinks = Sinks((("local", local), ("plugin", plugin)))
    visible, markup = [], []
    for kind_, p, _detail in diffs:
        if kind_ == "only in the local build":
            visible.append(Difference("only-local", p, 0, [], []))
        elif kind_ == "only in the plugin build":
            visible.append(Difference("only-plugin", p, 0, [], []))
        else:
            na, nb, ia, ib = _forms(p, local[p], plugin[p], ignored)
            for h in _hunks(p, na, nb, ia, ib, sinks if _is_page(p) else None):
                d = Difference(h.cls, p, h.line, h.a, h.b, h.why, [t for t in h.tokens])
                (markup if h.cls == "markup" else visible).append(d)
    tokens = {"class": set(), "data": set(), "id": set()}
    for d in markup:
        for k, n in d.tokens:
            tokens[k].add(n)
    if not diffs:
        verdict = "EQUAL"
    elif visible:
        verdict = "DIFFERENT"
    else:
        verdict = "MARKUP-ONLY"
    return {"verdict": verdict, "visible": visible, "markup": markup, "external": list(sinks.external),
            "tokens": dict((k, sorted(v)) for k, v in tokens.items()), "files": diffs}


class _Description(html.parser.HTMLParser):
    """The `content` of the first `<meta name="description">` of one page (whitespace squeezed), or None."""

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.text = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and self.text is None and (a.get("name") or "").strip().lower() == "description":
            self.text = " ".join((a.get("content") or "").split())

    handle_startendtag = handle_starttag


def page_description(text):
    """The description a search result shows for one page: its `<meta name="description">` content, whitespace squeezed; None when the
    page has none."""
    p = _Description()
    p.feed(text)
    p.close()
    return p.text


def description_changes(local, plugin):
    """[(page, old text, new text)], sorted by page: every page both builds write whose `<meta name="description">` differs (None is
    a page with none). The description is VISIBLE by the classifier (`classify_differences` counts it in `visible` like any other
    attribute, kind `attribute/content`, and never lists it as markup a visitor does not see): a search result is what a person
    meets before the page. That is why adopt names each one before publish, as something to ACCEPT (`adoption.report.accept_lines`)."""
    out = []
    for p in sorted(set(local) & set(plugin)):
        if _is_page(p):
            old, new = (page_description(b[p].decode("utf-8", "replace")) for b in (local, plugin))
            if old != new:
                out.append((p, old, new))
    return out


def _forms(p, a, b, ignored):
    """(normalised a, normalised b, aligned attributes of a or None, of b or None) for one file in both builds."""
    if _is_page(p):
        ta, ia = _page_form(a.decode("utf-8", "replace"), ignored)
        tb, ib = _page_form(b.decode("utf-8", "replace"), ignored)
        return ta.encode("utf-8"), tb.encode("utf-8"), ia, ib
    na, nb = _comparable(p, a, b, ignored)
    return na, nb, None, None


# ---------------------------------------------------------------- the printed report (dev #879), now with `markup`

def difference_groups(local, plugin, diffs, ignored=None, markup=True):
    """({(class, local lines, plugin lines): [(path, line)]}, [(path, hunks not read)]): every hunk of every file
    `diffs` says differs, up to HUNKS_PER_FILE per file, grouped across files by the hunk's own text. With `markup`
    (the default) an invisible difference is class `markup`, its own group, never folded into `body`; with it off
    every hunk is head, body or file as 0.3.1 printed it."""
    ignored = ignored or PARITY_IGNORED
    sinks = Sinks((("local", local), ("plugin", plugin))) if markup else None
    groups, omitted = {}, []
    for kind_, p, _detail in diffs:
        if kind_ != "differs" or p not in local or p not in plugin:
            continue
        na, nb, ia, ib = _forms(p, local[p], plugin[p], ignored)
        hunks = _hunks(p, na, nb, ia, ib, sinks)
        for h in hunks[:HUNKS_PER_FILE]:
            places = groups.setdefault((h.cls, tuple(h.a), tuple(h.b)), [])
            if p not in [q for q, _l in places]:
                places.append((p, h.line))
        if len(hunks) > HUNKS_PER_FILE:
            omitted.append((p, len(hunks) - HUNKS_PER_FILE))
    return groups, omitted


def difference_report(local, plugin, diffs, ignored=None, markup=True):
    """The lines `parity` and `remeasure` print for a list of differences (`compare_builds`' output): the files
    present in only one build, then ONE LINE PER CAUSE (a hunk's text, however many pages carry it) with its page
    count, body causes before the causes that are only an addition inside `<head>`, the markup a visitor does not
    see last and apart, and a count of what was not read (a file past HUNKS_PER_FILE hunks, causes past
    CAUSE_LINES_MAX). Empty when nothing differs."""
    lines = []
    for kind_, p, detail in diffs:
        if kind_ != "differs":
            lines.append("  %s: %s%s" % (kind_, p, (" (%s)" % detail) if detail else ""))
    groups, omitted = difference_groups(local, plugin, diffs, ignored, markup)
    if groups:
        order = {"body": 0, "file": 1, "head": 2, "markup": 3}
        rows = sorted(groups.items(), key=lambda kv: (order[kv[0][0]], kv[1][0][0], kv[0][1], kv[0][2]))
        pages = set(p for places in groups.values() for p, _l in places)
        n_head = sum(1 for k in groups if k[0] == "head")
        n_markup = sum(1 for k in groups if k[0] == "markup")
        lines.append("  differences by cause: %d cause(s) over %d file(s); %d only an addition inside <head> (listed after "
                     "the body causes, and never in place of one)%s" % (
                         len(groups), len(pages), n_head,
                         ("; %d markup a visitor does not see (listed last, apart)" % n_markup) if n_markup else ""))
        for (cls, a, b), places in rows[:CAUSE_LINES_MAX]:
            who = ("%s (line %d)" % places[0]) if len(places) == 1 else (
                "%d pages (%s%s)" % (len(places), ", ".join(p for p, _l in places[:CAUSE_EXAMPLES]),
                                     ", and %d more" % (len(places) - CAUSE_EXAMPLES) if len(places) > CAUSE_EXAMPLES else ""))
            lines.append("  differs: %s -- %s: %s" % (who, HUNK_CLASSES[cls], hunk_text(a, b)))
        if len(rows) > CAUSE_LINES_MAX:
            lines.append("  ... and %d more cause(s) not listed" % (len(rows) - CAUSE_LINES_MAX))
    for p, n in omitted:
        lines.append("  differs: %s -- %d more hunk(s) not listed (the first %d are)" % (p, n, HUNKS_PER_FILE))
    return lines
