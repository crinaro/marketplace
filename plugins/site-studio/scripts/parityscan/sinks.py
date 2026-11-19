"""sinks: where a build's stylesheets and scripts NAME a class, id or data token -- the reader behind parity's rules 3 to 5
(moved out of parity_classes.py unchanged, S1b). `Sinks` reads the CSS and JS of one build (CSS escapes decoded, selectors
on an attribute, `attr(`, off-origin loads, `href` fragments, IDREF attributes) and answers whether a token is named; it
reads and never judges, and errs toward visible."""

import html.parser
import parity_whitespace
import re


# Attributes whose value is a list of ids (rule 3's IDREF clause). `<use href>` is covered by the href fragments.
IDREF_ATTRS = frozenset(("for", "aria-labelledby", "aria-describedby", "aria-controls", "aria-owns",
                         "aria-activedescendant", "aria-details", "aria-errormessage", "aria-flowto",
                         "headers", "list", "form", "popovertarget", "commandfor"))


def _is_page(rel):
    return rel.lower().endswith((".html", ".htm"))


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
