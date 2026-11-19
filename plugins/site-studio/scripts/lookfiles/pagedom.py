"""The page DOM, and the slot syntax of a look's markup. A small tree of the page (html.parser, stdlib) that keeps what a look can carry:
elements, attributes in source order, text. Comments and declarations are dropped (a look may carry neither). It is not a conforming
HTML5 parser: it closes an open `p`, `li`, `dt`, `dd`, `td`, `th` and `tr` the way a page that omits the end tag means it, and ignores
an end tag that closes nothing. A page it misreads is reported `unmapped`, never guessed."""

import html.parser
import looks
import re
from contentmodel import links


_WS = re.compile(r"\s+")
_SLOT = re.compile(r"\{\{([a-z][a-z0-9]*)\}\}")
_PH_OPEN, _PH_CLOSE = "\ue010", "\ue011"          # a child's place inside a slot value, while it is parsed
_PH = re.compile(_PH_OPEN + r"(\d+)" + _PH_CLOSE)


_VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
                  "wbr"))
_CLOSES_P = frozenset(("address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure", "footer", "form", "h1",
                       "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table",
                       "ul"))
_URL_ATTRS = ("href", "src", "srcset", "cite", "data-embed")
_NOT_TEXT_ATTRS = frozenset(("class", "id", "style", "width", "height", "start", "value", "colspan", "rowspan",
                             "tabindex", "lang", "hreflang", "hidden", "allowfullscreen", "dir") +
                            _URL_ATTRS + tuple(looks.CLOSED_VALUES))
_STOP_UP = frozenset(("body", "html", "head", "#root"))


class El(object):
    __slots__ = ("tag", "attrs", "kids", "parent", "pos")

    def __init__(self, tag, attrs=None):
        self.tag, self.attrs, self.kids, self.parent, self.pos = tag, list(attrs or ()), [], None, 0


class Tx(object):
    __slots__ = ("data", "parent")

    def __init__(self, data):
        self.data, self.parent = data, None


class Mk(object):
    """A slot marker in a template under construction; an atom to every later step."""
    __slots__ = ("name", "parent")

    def __init__(self, name):
        self.name, self.parent = name, None


class _DomBuilder(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.root = El("#root")
        self.stack = [self.root]

    def _close_to(self, names, boundary=()):
        for i in range(len(self.stack) - 1, 0, -1):
            t = self.stack[i].tag
            if t in names:
                del self.stack[i:]
                return
            if t in boundary:
                return

    def _start(self, tag, attrs, selfclose):
        if tag in _CLOSES_P and self.stack[-1].tag == "p":
            self.stack.pop()
        if tag == "li":
            self._close_to(("li",), ("ul", "ol"))
        elif tag in ("dt", "dd"):
            self._close_to(("dt", "dd"), ("dl",))
        elif tag in ("td", "th"):
            self._close_to(("td", "th"), ("tr", "table"))
        elif tag == "tr":
            self._close_to(("tr",), ("table",))
        el = El(tag, attrs)
        el.parent = self.stack[-1]
        self.stack[-1].kids.append(el)
        if tag not in _VOID and not selfclose:
            self.stack.append(el)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        top = self.stack[-1]
        if top.kids and isinstance(top.kids[-1], Tx):
            top.kids[-1].data += data
        else:
            t = Tx(data)
            t.parent = top
            top.kids.append(t)


def parse_dom(text):
    p = _DomBuilder()
    p.feed(text)
    p.close()
    n = [0]

    def number(el):
        el.pos = n[0]
        n[0] += 1
        for k in el.kids:
            if isinstance(k, El):
                number(k)
    number(p.root)
    return p.root


def _collapse(s):
    return _WS.sub(" ", s)


def ser(node):
    """The canonical text of a node: tags and attribute names as written, values escaped by `content.esc`, text
    whitespace collapsed to one space, a void element without a slash. `{{slot}}` text stays as it is."""
    if isinstance(node, Tx):
        return links.esc(_collapse(node.data))
    if isinstance(node, Mk):
        return "{{%s}}" % node.name
    inner = "".join(ser(k) for k in node.kids)
    if node.tag == "#root":
        return inner
    head = "<" + node.tag + "".join(" " + k if v is None else ' %s="%s"' % (k, links.esc(v)) for k, v in node.attrs) + ">"
    return head if node.tag in _VOID else head + inner + "</" + node.tag + ">"


def squash(s):
    return _WS.sub("", _PH.sub("", s))


def text_of(node):
    if isinstance(node, Tx):
        return node.data
    if isinstance(node, Mk):
        return ""
    return "".join(text_of(k) for k in node.kids)


def is_ws(node):
    return isinstance(node, Tx) and not node.data.strip()


def walk(el):
    """Every element at or under `el`, in document order (`el` itself, when it is a text node: a part that starts with words)."""
    yield el
    for k in getattr(el, "kids", ()):
        if isinstance(k, El):
            for e in walk(k):
                yield e


def _copy(node, cmap):
    if isinstance(node, Tx):
        c = Tx(node.data)
    elif isinstance(node, Mk):
        c = Mk(node.name)
    else:
        c = El(node.tag, node.attrs)
        for k in node.kids:
            ck = _copy(k, cmap)
            ck.parent = c
            c.kids.append(ck)
    cmap[id(node)] = c
    return c


class Page(object):
    """One parsed page with the caches anchoring needs."""

    def __init__(self, key, text):
        self.key = key
        self.root = parse_dom(text)
        self._text = {}
        self._attrs = {}
        self._words = {}

    def stext(self, el):
        r = self._text.get(id(el))
        if r is None:
            r = self._text[id(el)] = squash(text_of(el))
        return r

    def words(self, el):
        """The squashed text of each text node at or under `el` (a one-character value is looked for by this: as the
        whole of a text node, never as a letter inside a longer text)."""
        r = self._words.get(id(el))
        if r is None:
            r = set()
            for k in el.kids:
                if isinstance(k, Tx):
                    s = squash(k.data)
                    if s:
                        r.add(s)
                elif isinstance(k, El):
                    r |= self.words(k)
            self._words[id(el)] = r
        return r

    def attrs(self, el):
        """[(name, squashed value, stripped value)] for `el` and everything under it."""
        r = self._attrs.get(id(el))
        if r is None:
            r = [(k, squash(v or ""), (v or "").strip()) for k, v in el.attrs]
            for k in el.kids:
                if isinstance(k, El):
                    r.extend(self.attrs(k))
            self._attrs[id(el)] = r
        return r


def _height(el):
    """How many elements stand above `el` in its page."""
    n = 0
    while el.parent is not None:
        el = el.parent
        n += 1
    return n
