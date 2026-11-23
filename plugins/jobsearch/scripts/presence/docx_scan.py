"""docx_scan: one expat pass over a Word file's `word/document.xml`, recording every element by byte range
(design-resume-docx.md §4.1, §4.2; B9).

What a scan holds, all offsets into the part's bytes, `end` exclusive:

    nodes          every element in document order: its tag (`{namespace}local`, as ElementTree names it), `start`
                   (the `<`), `open_end` (just past the start tag), `close_start` (the `</`, or `end` when
                   self-closing), `end`, its parent, its children and the character data directly inside it
    paragraphs     each body-level `w:p` (a child of `w:body`), with its `w:pPr`, its direct `w:r` runs, its style,
                   whether it is numbered, its `w:ilvl`, and its text as `resume_import._paragraph` reads it (§4.2)
    body_other     every other child of `w:body` (a table, a block content control, `w:sectPr`, a bookmark)
    protected      the byte ranges no edit may touch: the root's start and end tags (its namespace declarations) and
                   every `w:sectPr`

**The end of an element** (§4.1, M-6): when the end event follows the element's own start event with no event
between and the two bytes before its index are `/>`, the element is self-closing and ends at that index; otherwise
the index is at `</` and the element ends after the next `>`. Expat reports a self-closing element's end event just
past its `/>`, and an end tag's at its `<`. The start tag's own end is found by walking it with quotes honoured, so a
`>` inside an attribute value is not taken for it. Text events (character data, an entity, a CDATA section) are
joined until the next non-text event.

Refused, never guessed (`ScanRefusal`, rule `R8`): a part that is not UTF-8, declares another encoding, declares a
DTD or an entity, or is not well-formed XML. Capability module; nothing here reads or writes a file.
Python 3.9+, standard library only."""

import xml.parsers.expat

from presence.resume_import import GLYPH_RE

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"
_SEP = "}"
_UTF8 = ("utf-8", "utf8")
_BREAKS = (W + "br", W + "cr")


class ScanRefusal(Exception):
    """A document part the scan will not read; `rule` is the design's refusal id, `detail` says why."""

    def __init__(self, rule, detail):
        Exception.__init__(self, "%s: %s" % (rule, detail))
        self.rule = rule
        self.detail = detail


class Node:
    """One element of the part, by byte range."""

    __slots__ = ("tag", "attrs", "start", "open_end", "close_start", "end", "parent", "children", "chars",
                 "self_closing")

    def __init__(self, tag, attrs, start, parent):
        self.tag = tag
        self.attrs = attrs
        self.start = start
        self.open_end = None
        self.close_start = None
        self.end = None
        self.parent = parent
        self.children = []
        self.chars = []
        self.self_closing = False

    @property
    def text(self):
        """The character data directly inside this element, entities and CDATA resolved."""
        return "".join(self.chars)

    def child(self, tag):
        """The first direct child named `tag`, or None."""
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def iter(self):
        """This element and every descendant, in document order (as `ElementTree.Element.iter`)."""
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.children))

    def __repr__(self):
        return "<Node %s %d:%d>" % (self.tag.rsplit("}", 1)[-1], self.start, self.end)


class Paragraph:
    """A body-level `w:p` and what §4.2 and the matcher read of it."""

    __slots__ = ("node", "index", "ppr", "runs", "style", "listed", "ilvl", "text")

    def __init__(self, node, index):
        self.node = node
        self.index = index
        self.ppr = node.child(W + "pPr")
        self.runs = [c for c in node.children if c.tag == W + "r"]
        self.style, self.listed, self.ilvl = _ppr_facts(self.ppr)
        self.text = paragraph_text(node)

    @property
    def start(self):
        return self.node.start

    @property
    def end(self):
        return self.node.end


class Scan:
    """The result of `scan(data)`."""

    def __init__(self, data, nodes, root):
        self.data = data
        self.nodes = nodes
        self.root = root
        self.body = root.child(W + "body") if root is not None else None
        kids = self.body.children if self.body is not None else []
        self.paragraphs = []
        self.body_other = []
        for c in kids:
            if c.tag == W + "p":
                self.paragraphs.append(Paragraph(c, len(self.paragraphs)))
            else:
                self.body_other.append(c)
        self.sectprs = [n for n in nodes if n.tag == W + "sectPr"]

    def raw(self, item):
        """The bytes of a node or paragraph."""
        return self.data[item.start:item.end]

    def protected(self):
        """Byte ranges no edit may overlap: the root's start and end tags, and every `w:sectPr`."""
        out = []
        if self.root is not None:
            out.append((self.root.start, self.root.open_end))
            out.append((self.root.close_start, self.root.end))
        out.extend((s.start, s.end) for s in self.sectprs)
        return out


def _ppr_facts(ppr):
    """(pStyle value, numbered, ilvl as int or None) of a `w:pPr` node, or ("", False, None)."""
    if ppr is None:
        return "", False, None
    ps = ppr.child(W + "pStyle")
    style = (ps.attrs.get(W + "val") or "") if ps is not None else ""
    num = ppr.child(W + "numPr")
    ilvl = None
    if num is not None:
        lv = num.child(W + "ilvl")
        if lv is not None and (lv.attrs.get(W + "val") or "").isdigit():
            ilvl = int(lv.attrs[W + "val"])
    return style, num is not None, ilvl


def paragraph_text(node):
    """A paragraph's text as `resume_import._paragraph` reads it (§4.2): every `w:t` in order, a tab or a break as one
    space, deleted tracked text (`w:delText`) and field codes (`w:instrText`) left out, whitespace collapsed."""
    parts = []
    for el in node.iter():
        if el.tag == W + "t":
            parts.append(el.text)
        elif el.tag == W + "tab":
            parts.append("\t")
        elif el.tag in _BREAKS:
            parts.append(" ")
    return " ".join("".join(parts).split())


def comparison_text(text):
    """`text` with a leading bullet glyph and its separator dropped: for comparison only (§4.2)."""
    return GLYPH_RE.sub("", text)


def _start_tag_end(data, i):
    """The index just past the `>` closing the start tag at `data[i] == '<'`; quotes are honoured, so a `>` inside
    an attribute value does not end it."""
    n = len(data)
    quote = None
    j = i + 1
    while j < n:
        b = data[j]
        if quote is not None:
            if b == quote:
                quote = None
        elif b in (0x22, 0x27):
            quote = b
        elif b == 0x3E:
            return j + 1
        j += 1
    raise ScanRefusal("R8", "a start tag at byte %d never closes" % i)


def _check_encoding(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise ScanRefusal("R8", "the document part is UTF-16, not UTF-8")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ScanRefusal("R8", "the document part is not UTF-8 (byte %d)" % e.start)


def _refuse_dtd(*_args):
    raise ScanRefusal("R8", "the document part declares a DTD or an entity, which no Word document does")


def _xml_decl(_version, encoding, _standalone):
    if encoding and encoding.lower() not in _UTF8:
        raise ScanRefusal("R8", "the document part declares encoding %s, not UTF-8" % encoding)


class _Walker:
    """The expat handlers of one scan; `events` counts every recorded event so the self-closing rule can see whether
    anything came between an element's start and its end."""

    def __init__(self, data, parser):
        self.data = data
        self.p = parser
        self.nodes = []
        self.stack = []
        self.root = None
        self.events = 0
        self.last_start = None      # (node, event number) of the most recent start event
        self.text_node = None       # the node collecting a run of text events

    def start(self, name, attrs):
        self.events += 1
        self.text_node = None
        i = self.p.CurrentByteIndex
        parent = self.stack[-1] if self.stack else None
        node = Node(name, attrs, i, parent)
        node.open_end = _start_tag_end(self.data, i)
        if parent is not None:
            parent.children.append(node)
        elif self.root is None:
            self.root = node
        self.nodes.append(node)
        self.stack.append(node)
        self.last_start = (node, self.events)

    def end(self, _name):
        self.events += 1
        self.text_node = None
        i = self.p.CurrentByteIndex
        node = self.stack.pop()
        own = self.last_start is not None and self.last_start[0] is node and self.last_start[1] == self.events - 1
        if own and self.data[i - 2:i] == b"/>":
            node.self_closing = True
            node.close_start = i
            node.end = i
        else:
            node.close_start = i
            gt = self.data.find(b">", i)
            if gt < 0:
                raise ScanRefusal("R8", "an end tag at byte %d never closes" % i)
            node.end = gt + 1

    def chars(self, text):
        if self.text_node is None:
            self.events += 1
            self.text_node = self.stack[-1] if self.stack else None
        if self.text_node is not None:
            self.text_node.chars.append(text)

    def other(self, *_args):
        self.events += 1
        self.text_node = None


def scan(data):
    """Scan the bytes of a `word/document.xml` part. Returns a `Scan`, or raises `ScanRefusal`."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("scan() takes the part's bytes")
    data = bytes(data)
    _check_encoding(data)
    p = xml.parsers.expat.ParserCreate(encoding="utf-8", namespace_separator=_SEP)
    w = _Walker(data, p)
    p.StartElementHandler = lambda n, a: w.start(_qualify(n), {_qualify(k): v for k, v in a.items()})
    p.EndElementHandler = w.end
    p.CharacterDataHandler = w.chars
    p.CommentHandler = w.other
    p.ProcessingInstructionHandler = w.other
    p.XmlDeclHandler = _xml_decl
    p.StartDoctypeDeclHandler = _refuse_dtd
    p.EntityDeclHandler = _refuse_dtd
    try:
        p.Parse(data, True)
    except xml.parsers.expat.ExpatError as e:
        raise ScanRefusal("R8", "the document part is not well-formed XML (%s)" % e)
    if w.root is None:
        raise ScanRefusal("R8", "the document part has no root element")
    return Scan(data, w.nodes, w.root)


def _qualify(name):
    """expat's `uri}local` as ElementTree's `{uri}local`; an unqualified name unchanged."""
    return "{" + name if _SEP in name else name

