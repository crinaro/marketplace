#!/usr/bin/env python3
"""look.py -- choose, vendor, check and DERIVE a site's look (design-template-fidelity section R5.4, step 1.8D;
issue #909; decisions 33 and 38; R5N-13, R5N-15, R5N-16). Python 3.9, standard library only.

    look.py list                                  the looks site-studio ships, and the looks this site carries
    look.py use <id|path> [--accept-literals]     copy a look (and the stylesheets it names) into this site
    look.py check                                 read this site's look: omitted constructs, literal words, files
    look.py derive [--build DIR | --url URL] [--owned-host HOST] [--name NAME] [--replace]
                                                  make a look from a site this repository's content built

Every command takes `--repo DIR` (default: the current folder). NOTHING here commits: a command prints each path it
wrote, and the skill that ran it commits them.

`use` copies a shipped look (`templates/looks/<id>.json`, stylesheets from `templates/looks/<id>.css`) or a look file
from another repository (`<path>`, stylesheets from that repository's `site/src/`) to `site/looks/<id>.json`, and
writes the site.json `look` key through `siteconfig` (the one writer) at schema 4. It NEVER OVERWRITES: a target that
exists with other bytes refuses, naming it; identical bytes print "already in place". A look holding literal words
(any letter in a text node or a text attribute) is listed by construct and part and refused without
`--accept-literals`: the person is shown the words first. The finished tree is built in memory before a byte is
written, so a look that makes the site unbuildable refuses and writes nothing.

`derive` reads this repository's CONTENT at HEAD, builds it in memory (recording every `looks.render` call: the values
each slot got), and finds each construct instance in the pages of the site the content produced. Nothing is a model's
guess: the instance's text values are looked for in the page (TEXT ANCHORING, design R5.4(f)).

  1. Anchor. For one instance the plugin knows its slot values. In a page it finds the LOWEST element whose text (and
     attribute values) hold every one of them; it moves the anchor up where the instance is also its own child's
     anchor, and out over single-child wrappers (`li > a`), never past the part that owns it. A child part is anchored
     inside its parent's element. A part with no slot at all (a fixed heading) is placed by its neighbours and its
     page text is kept as the person's own literal text. OURS, deliberately weaker than the design's "in order": the
     lowest element holding every value, in any order, because a value may sit in an attribute and an attribute has
     no place in a text order; the cross-instance check below is what proves the result. Two things the page may not
     hold are left out of the search (step 1.9, finding F-c, from markup a template writes): a value the plugin's own
     markup writes into an ATTRIBUTE only (a `label`, an `alt`) is only used to anchor a part with nothing else to anchor
     on, because the template may carry no such attribute and a word of it found elsewhere (a title that says "Quotes")
     would pull the anchor out over its neighbours; and a value found NOWHERE in the scope (a host name the template
     does not show) is dropped, so the instance anchors on the values the page does show and the template has no slot
     for the rest. A child alone in its wrapper (a block that is all of a piece's body) is read both ways, the wrapper
     the child's or the parent's, and the instances of the part decide (the reading the other instances can share wins).
  2. Template. The anchor's subtree is serialised; each child's element becomes `{{slot}}`; a text node or attribute
     value that equals a slot's value, or holds it as a whole word, becomes that slot; a url attribute equal to a url
     slot's value becomes that slot. A NUMBER becomes `{{n}}` or `{{count}}` only where at least two instances
     disagree on it AND the digits at that place equal the slot's value in every instance (so a digit that happens to
     equal the count, such as the 3 in `col-3`, stays literal; held-out case `look-derived`).
  3. Agree. Every instance of one part yields one template, or the construct is `ambiguous`; the candidate is filled
     back with each instance's values and must equal that instance's own page text. Two non-nested anchors that give
     different templates are `ambiguous` too. Where the instances do not all agree but MORE THAN HALF share one markup,
     that markup is the part's template and the others are named `ambiguous` (a menu link the template points at a
     piece where the plugin points at the portfolio): one odd instance does not take the construct away, and the page
     it is on stays DIFFERENT in parity, which is what says so.
     A WRAPPER NEITHER OWNS ALONE (G3 flip). A part that stands alone in a wrapper can have the wrapper as its own or leave it to
     its parent, and a part used in two places (an image in a card, an image in a showcase tile that wraps it in a span) must
     read the same in both. When the first reading leaves an instance `ambiguous`, the pages are read again preferring, of the
     readings that take one element, the one that leaves the wrapper to the PARENT (the parts below hold the least markup): a
     wrapper a part owns only serves the places that carry it. The reading that maps more instances is the answer, and the first
     reading stays the answer when they tie, so a site that derived cleanly derives as it always did.
     A PART THE TEMPLATE WRITES IN ANOTHER SHAPE (step 1.10, the derive limits G3 left). (a) A part the plugin writes as several sibling
     elements (`heading-multi`: a count span, a name span) that the page holds as one element (an `h3` around the name and a count
     badge) is that element: where no run of siblings matches the plugin's own, the part is read as the one element that holds what
     the page shows of it (`_one`). (b) A part that fills the element its parent owns (`previously-item`: a span around a link and a
     period, which the template writes as a span and an `i` side by side inside the parent's `p`), or two parts that fill one element
     (two earlier roles in one `p`), are RUNS of that element's children, each from where the one before ended to the last child that
     holds one of its values (`_runs_for_sharers`). That reading is offered after the others and is only the one taken where the
     others would reach over a sibling part: the parts of one parent are side by side, never one inside another (`_choose`). (c) A
     slot the plugin's markup does not show, whose value the template shows as the WHOLE text of a line (the employer in a company
     line the plugin's item does not have), is that slot, never the person's own words (`_text_slot`): a word that is merely one of
     several in a line stays literal. (d) A value that is only a part of another value of the same instance ("Client" beside
     "Invented Client") is found at a place of its own: the longer value takes its occurrence out of the text first (`_holds_apart`);
     where no element holds them so, the instance anchors as it always did. (e) A part that could not be mapped does not take the
     parts inside it with it: each of them is read on its own inside the element that held the whole of it (`settle`), one reading
     only (a list of one stays `unmapped`: the parent decided it and the parent is gone), never over an element another of those
     parts holds, and LAST, so it only adds: where it disagrees with what the other instances fixed it is named `ambiguous` and
     what they fixed stands.
  3b. Counting instances, and a heading beside a list of one (G3 derive link 2). A reading may also COUNT INSTANCES (`derive_look`, the
     third and fourth readings): a markup more instances cannot share (`_merge`) than can is OUTVOTED, and an instance every reading
     of which holds an outvoted part is read last, its other parts committed and the outvoted ones offered after every other instance
     has fixed its markup, so one page that wraps its lone reference card in a grid is the page that differs (named `ambiguous`), not
     the home page whose feed and samples write the card bare. Where no reading of an instance agrees with what is accepted, the
     reading with the fewest disagreeing parts is kept and only those parts are named `ambiguous` (a home page keeps its wrapper, its
     heading and every part inside it where one list of links is marked up as the resume page marks it; which markup stands is the one
     accepted first when the instances tie). A part whose own markup is a wrapper around a FIXED element and a slot (the section
     around `<h2>Featured</h2>` and the list) is also read as the wrapper that holds its extent and that element (`_fixed_beside`): a
     list of ONE says nothing else of whose the section is. The fourth reading is told what the third kept, so that list reads as the
     lists of several do.
  4. Validate. A template the grammar refuses (`looks.check_part`: a script, an event attribute, an off-origin link,
     an element a look may not carry) makes the construct `unmapped`; it is never written.
Not expressible, said once: whitespace between items that is not the same between every item, a wrapper two levels
above its part that holds other content, a link the template writes in another form than the plugin does (root-relative
against relative), a construct used inside Markdown text (not at the top of its slot), and first/last/odd/even
classes. Each of them is reported `unmapped` or `ambiguous`; none is guessed.

THE REPORT (R5.4(g)): one line per construct id, `mapped`, `unmapped` (a page was read, nothing anchored),
`ambiguous` (two templates disagree) or `not reached` (the page was never read), with instance counts; then the
text-bearing elements no content explains, counted by element name only (`element/<tag>`), never echoed. A look the
person keeps holds structure PLUS the person's own literal text, and `check` and `use` list each literal. It lives
in whichever repository the person derives into, public or not; nothing here claims it is private. Outside adopt
nothing is filed anywhere; inside adopt an `unmapped` or `ambiguous` construct that leaves parity DIFFERENT is a
`look/` cause.

PRECONDITION (R5.4(c)). derive runs in the repository whose site-studio content produced the pages (`site/site.json`
readable). Not a site-studio tree: "derive needs the content that built the pages; adopt that site first". No instance
anchors on any page read: "these pages were not built from this repository's content", never an all-`unmapped`
report. For a new site, derive in the old site's repository, then `look.py use <path>` in the new one.

WHERE THE PAGES COME FROM. `--build DIR`: a folder of built pages on this machine; no network, no ownership question.
Otherwise the person's published pages, fetched with `urllib`: the start page is the `publicRepo` Pages address
(`gh api repos/<o>/<r>/pages`) or `--url`; at most 40 pages, 2 MB and 10 s each, `text/html` only, no script,
stylesheet, image or font; each response's final address must stay in the owned set; `robots.txt` is read first (2xx
honoured for the token `site-studio`, 404 allows all, any other answer refuses and names `--build`). The pages are
held in memory: nothing is spooled to a scratch folder, so there is nothing to delete after the run.

OWNERSHIP (R5.4(d), decision 33; NOT ENFORCED). The person's own Pages host set (`html_url`'s host and `cname`) is
accepted with no question. Any other host only with `--owned-host <host>` AND a confirmation this script reads from
its own terminal (the person types the host back); with no terminal on stdin it refuses and prints the command to run
in the person's own terminal. NOT ENFORCED, said where it is read (R5N-13): a terminal shows that a pseudo-terminal
exists, not that a person owns the host, and a caller can allocate one; the check stops an ordinary Bash call, nothing
more, and the output prints "ownership not verified". With no person (a cloud session, a scheduled run) only the Pages
set is accepted. Each gh failure refuses with its own fix and never says "not yours": gh missing, not logged in, no
`publicRepo`, Pages not enabled, GitHub not reachable (the error class only). Anything else: "deriving a look from a
site you do not publish is not supported".

SSRF (R5N-15; DOCUMENTED: the OWASP Server-Side Request Forgery Prevention Cheat Sheet, allowlist the destination and
check the RESOLVED address, redirects included). `host_allowed(address)` is the one seam: every connection resolves
its host, every resolved address must pass, and the socket is opened to the address that passed (so a name cannot
change its answer between the check and the connection). Loopback, link-local, private, shared, multicast and
reserved addresses are refused. A redirect is checked before it is followed. Tests reach a local server by patching
`host_allowed`; no environment variable or flag switches it off. With an HTTP(S) proxy configured the connection is
made by the proxy, whose address this script cannot check, so derive refuses: "a proxy is configured: derive with
--build".

THE COMMAND THE PERSON RUNS (R5N-16). `owned_host_command()` builds it fresh each time: the running interpreter's
absolute path, this script's absolute path resolved from the running install, and a `cd` to the site repository, every
piece quoted. It is printed, never stored, never written to a file.

EXIT CODES: 0 done; 1 refused (the line says what to do); `derive` also exits 1 when nothing could be mapped.
"""
import argparse
import collections
import contextlib
import html.parser
import http.client
import ipaddress
import json
import os
import posixpath
import re
import shlex
import shutil
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import addresses  # noqa: E402
import build  # noqa: E402
import content as C  # noqa: E402
import looks  # noqa: E402
import pages_check  # noqa: E402
import platform_check  # noqa: E402
import siteconfig  # noqa: E402

EXIT_OK, EXIT_REFUSED = 0, 1
LOOKS_REL = "site/looks/"
SHIPPED_DIR = os.path.join(os.path.dirname(HERE), "templates", "looks")
DEFAULT_NAME = "derived"
FETCH_PAGES, FETCH_BYTES, FETCH_SECONDS = 40, 2 * 1024 * 1024, 10
ROBOTS_TOKEN = "site-studio"
STATUSES = ("mapped", "unmapped", "ambiguous", "not reached")
NOT_VERIFIED = "ownership not verified: this host is accepted on your word, and site-studio cannot check it"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WS = re.compile(r"\s+")
_SLOT = re.compile(r"\{\{([a-z][a-z0-9]*)\}\}")
_PH_OPEN, _PH_CLOSE = "\ue010", "\ue011"          # a child's place inside a slot value, while it is parsed
_PH = re.compile(_PH_OPEN + r"(\d+)" + _PH_CLOSE)


class LookCommandError(ValueError):
    """A refusal of this command. The message is the line the person reads and says what to do."""


class FetchError(LookCommandError):
    """A fetch that cannot be made or must not be made; `kind` is a short closed label."""

    def __init__(self, message, kind="fetch"):
        LookCommandError.__init__(self, message)
        self.kind = kind


# =================================================================================================== the page DOM
# A small tree of the page (html.parser, stdlib) that keeps what a look can carry: elements, attributes in source
# order, text. Comments and declarations are dropped (a look may carry neither). It is not a conforming HTML5
# parser: it closes an open `p`, `li`, `dt`, `dd`, `td`, `th` and `tr` the way a page that omits the end tag
# means it, and ignores an end tag that closes nothing. A page it misreads is reported `unmapped`, never guessed.

_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_CLOSES_P = frozenset(("address article aside blockquote div dl fieldset figure footer form h1 h2 h3 h4 h5 h6 "
                       "header hr main nav ol p pre section table ul").split())
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
        return C.esc(_collapse(node.data))
    if isinstance(node, Mk):
        return "{{%s}}" % node.name
    inner = "".join(ser(k) for k in node.kids)
    if node.tag == "#root":
        return inner
    head = "<" + node.tag + "".join(" " + k if v is None else ' %s="%s"' % (k, C.esc(v)) for k, v in node.attrs) + ">"
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


# ================================================================================================== the recording
class Call(object):
    """One `looks.render` call: what was rendered, from which values, with what result."""

    def __init__(self, idx, construct, part, values, out, look=None):
        self.idx, self.construct, self.part, self.out = idx, construct, part, out
        self.values = dict(values)
        self.table = looks.CONSTRUCTS[construct]["parts"][part]
        self.parent = None
        self.segments = {}              # html slot -> [("text", html) | ("kid", Call)]
        self.cache = {}                 # memo of items and needles (a Call is read many times while anchoring)
        try:
            text = looks.part_markup(construct, part, look)
        except looks.LookError:
            text = ""
        self.template = text            # the recording look's markup for this part
        used, in_text = [], set()
        for m in _SLOT.finditer(text):
            if m.group(1) in self.table and m.group(1) not in used:
                used.append(m.group(1))
            if text.rfind("<", 0, m.start()) <= text.rfind(">", 0, m.start()):
                in_text.add(m.group(1))     # not inside a tag: the slot's value is page text
        self.used = used                # the slots the recording look wrote into the page, in its order
        self.attr_only = frozenset(s for s in used if s not in in_text)   # written into attributes only (aria-label, alt, ...)

    @property
    def key(self):
        return (self.construct, self.part)

    def slot_order(self):
        """The slots the page shows (the recording look's own): only these can be searched for in a page."""
        return list(self.used)

    def all_slots(self):
        """The slots the page shows, then the ones it may carry as markup (a class token, a data attribute)."""
        return list(self.used) + [s for s in self.table if s not in self.used]


@contextlib.contextmanager
def recording():
    """Record every `looks.render` call made inside the block (build.py and content.py call it through the module,
    so the one wrapper sees them all). Restores the original on exit. Yields the list of `Call`."""
    calls = []
    original = looks.render

    def rec(construct, part, values, look=None):
        out = original(construct, part, values, look)
        calls.append(Call(len(calls), construct, part, values, out, look))
        return out
    looks.render = rec
    try:
        yield calls
    finally:
        looks.render = original


def link_calls(calls):
    """Set each call's `parent` and its html slots' `segments`. A call is a child of the LATEST later call whose html
    slot holds its `out`, taking longest spans first so a grandchild is the child of its own parent, and one earlier
    call per occurrence (the closest not yet taken)."""
    taken = set()
    by_out = collections.defaultdict(list)
    for c in calls:
        if c.out:
            by_out[c.out].append(c)
    for p in calls:
        for slot, kind in p.table.items():
            v = p.values.get(slot)
            if kind != looks.HTML or not isinstance(v, str) or not v:
                continue
            spans = []
            used = []
            for out in sorted((o for o in by_out if o in v), key=len, reverse=True):
                start = 0
                while True:
                    i = v.find(out, start)
                    if i < 0:
                        break
                    j = i + len(out)
                    start = i + 1
                    if any(i < b and a < j for a, b in used):
                        continue
                    cands = [c for c in by_out[out] if c.idx < p.idx and c.idx not in taken]
                    if not cands:
                        continue
                    kid = cands[-1]
                    taken.add(kid.idx)
                    kid.parent = p
                    used.append((i, j))
                    spans.append((i, j, kid))
            spans.sort(key=lambda t: t[0])
            segs, pos = [], 0
            for i, j, kid in spans:
                if i > pos:
                    segs.append(("text", v[pos:i]))
                segs.append(("kid", kid))
                pos = j
            if pos < len(v):
                segs.append(("text", v[pos:]))
            p.segments[slot] = segs


def kids_of(call):
    return [seg[1] for segs in call.segments.values() for seg in segs if seg[0] == "kid"]


def record(files):
    """Build `files` in memory with every render call recorded. Returns (calls, html_outputs). Raises
    LookCommandError when the tree does not build: nothing can be derived from content the build refuses."""
    with recording() as calls:
        acc = build.accept(files)
    if acc.problems:
        first = "; ".join(p.line() for p in acc.problems[:2])
        raise LookCommandError("this repository's content does not build today (%s), so a look cannot be derived from "
                               "it; fix that first, then run derive again" % first)
    link_calls(calls)
    pages = {}
    for path, data in acc.output.items():
        if path.lower().endswith((".html", ".htm")):
            try:
                pages[path] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
    return calls, pages


# ================================================================================================= the derivation
class _Fail(Exception):
    """One instance could not be anchored or templated; `status` is `unmapped` or `ambiguous`."""

    def __init__(self, status, why):
        Exception.__init__(self, why)
        self.status, self.why = status, why
        self.where = None               # (page, anchors) when the instance WAS anchored and then could not be read as a template


def _value_items(call, slot):
    """The top-level items of html slot `slot` of `call`: [("el", tag, squashed text) | ("tx", squashed text) |
    ("kid", Call) | ("wild", n)], or raises _Fail where a child sits inside Markdown markup (not at the top of its
    slot) or the markup cannot be read."""
    memo = call.cache.get(("items", slot))
    if memo is not None:
        if isinstance(memo, _Fail):
            raise memo
        return memo
    try:
        items = _value_items_uncached(call, slot)
    except _Fail as e:
        call.cache[("items", slot)] = e
        raise
    call.cache[("items", slot)] = items
    return items


def _value_items_uncached(call, slot):
    return _parse_items(call.segments.get(slot) or [("text", call.values.get(slot) or "")])


def _out_items(call):
    """The top-level items of the part's own output (a part that writes several sibling elements): its template is
    walked, a slot at the top of it (outside every element) contributes its own segments, so a child there is marked,
    and every other slot is its rendered value."""
    memo = call.cache.get("out-items")
    if memo is None:
        tmpl = call.template
        probe = parse_dom(_SLOT.sub(lambda m: "" + m.group(1) + "", tmpl))
        top = set(re.findall("([a-z0-9]+)", "".join(k.data for k in probe.kids if isinstance(k, Tx))))
        segs, pos = [], 0
        for m in _SLOT.finditer(tmpl):
            if m.start() > pos:
                segs.append(("text", tmpl[pos:m.start()]))
            pos = m.end()
            name, kind, v = m.group(1), call.table.get(m.group(1)), call.values.get(m.group(1))
            if v is None or v == "":
                continue
            if kind == looks.HTML and name in top:
                segs.extend(call.segments.get(name) or [("text", str(v))])
            elif kind == looks.HTML or kind == looks.INT:
                segs.append(("text", str(v)))
            else:
                segs.append(("text", C.esc(str(v))))
        if pos < len(tmpl):
            segs.append(("text", tmpl[pos:]))
        memo = call.cache["out-items"] = _parse_items(segs)
    return memo


def _parse_items(segs):
    kids, text = [], []
    for kind, payload in segs:
        if kind == "text":
            text.append(payload)
        else:
            kids.append(payload)
            text.append(_PH_OPEN + str(len(kids) - 1) + _PH_CLOSE)
    root = parse_dom("".join(text))
    items = []
    for n in root.kids:
        if isinstance(n, El):
            if n.tag in ("link", "script"):     # the plugin's own asset tag (blocks.css, video.js): a look names its own
                continue
            if _PH.search(text_of(n)):
                raise _Fail("unmapped", "a construct is used inside Markdown text, not at the top of its slot")
            items.append(("el", n.tag, squash(text_of(n))))
            continue
        data = n.data
        pos = 0
        for m in _PH.finditer(data):
            if data[pos:m.start()].strip():
                raise _Fail("unmapped", "a construct is used inside a line of Markdown text")
            items.append(("kid", kids[int(m.group(1))]))
            pos = m.end()
        rest = data[pos:]
        if rest.strip():
            items.append(("tx", squash(rest), rest))
    return items


def _own_needles(call):
    """(hard text needles, soft url needles) of `call`'s own values: text slots, the text of an html slot's own
    fragments (never its children's), and the url-kind values."""
    if "own" in call.cache:
        return call.cache["own"]
    hard, soft, opt = [], [], []
    for slot in call.slot_order():
        v = call.values.get(slot)
        kind = call.table[slot]
        if v is None or v == "":
            continue
        if kind == looks.TEXT:
            s = squash(str(v))
            if s:
                # a value the recording look writes into an attribute only (a label, an alt) may not be on the page at
                # all (the template has no such attribute), and a word of it found elsewhere must not pull the anchor out
                (opt if slot in call.attr_only else hard).append(s)
        elif kind == looks.HTML:
            for it in _items_or_empty(call, slot):
                if it[0] == "el" and it[2]:
                    hard.append(it[2])
                elif it[0] == "tx" and it[1]:
                    hard.append(it[1])
        elif kind in (looks.URL, looks.CONTACT, looks.SRCSET, looks.EMBED):
            soft.append(str(v).strip())
    call.cache["own"] = (hard, soft)
    call.cache["own-opt"] = opt
    return hard, soft


def _int_needles(call):
    return [str(call.values[s]) for s in call.slot_order()
            if call.table[s] == looks.INT and call.values.get(s) not in (None, "")]


def _items_or_empty(call, slot):
    try:
        return _value_items(call, slot)
    except _Fail:
        return []


def _full_needles(call):
    if "full" in call.cache:
        return call.cache["full"]
    hard, soft = _own_needles(call)
    hard, soft = list(hard), list(soft)
    for k in kids_of(call):
        h, s = _full_needles(k)
        hard += h
        soft += s
    if not hard:
        hard = list(call.cache["own-opt"])      # nothing else at or under this part to anchor on: its attribute values
    call.cache["full"] = (hard, soft)
    return hard, soft


def _tops(call):
    """How many sibling nodes the part's own output holds at the top (a list item is one; the home page's intro and
    its endorsement are two)."""
    n = call.cache.get("tops")
    if n is None:
        n = call.cache["tops"] = len([k for k in parse_dom(call.out).kids if not is_ws(k)])
    return n


def _fixed_beside(call):
    """The element names of the FIXED elements the plugin's own markup for `call` writes in one element beside a slot: `['h2']` for
    `<section class="featured"><h2>Featured</h2>{{cards}}</section>`, `[]` for a part with none. A list of one carries nothing but
    that heading to say its section is the part's, so a wrapper holding the extent and exactly these elements is a reading of the
    part (`_read_variants`); the element names must agree, so a card's sibling card is never taken for one."""
    got = call.cache.get("beside")
    if got is None:
        got = []
        for el in walk(parse_dom(call.template)):
            if any(isinstance(k, Tx) and _SLOT.search(k.data) for k in el.kids):
                names = sorted(k.tag for k in el.kids if isinstance(k, El) and not _SLOT.search(ser(k)))
                if len(names) > len(got):
                    got = names
        call.cache["beside"] = got
    return got


def _is_wild(call):
    """A part nothing can be searched for: no text, no url, no number (a fixed heading). It is placed by its
    neighbours."""
    h, s = _full_needles(call)
    return not (h or s or _int_needles(call))


_SHARE = "two instances of one construct share one element"


def _above(a, b):
    """Is `a` a proper ancestor of `b`?"""
    p = b.parent
    while p is not None:
        if p is a:
            return True
        p = p.parent
    return False


def _node_holds(page, node, needle):
    """Does this child (a text node, or an element and what is under it) hold `needle`?"""
    if isinstance(node, Tx):
        s = squash(node.data)
        return s == needle if len(needle) < 2 else needle in s
    return isinstance(node, El) and _holds(page, node, [needle])


def _has_nested(needles):
    """True when one needle is only a part of another (a label "Client" and a value "Invented Client")."""
    ns = set(n for n in needles if len(n) >= 2)
    return any(a != b and a in b for a in ns for b in ns)


def _holds_apart(page, el, hard):
    """Does `el` hold every needle at a place of its own? A needle that is only a part of a longer needle ("Client" inside "Invented
    Client") is not held by the longer value alone: the longer needles take their occurrence out of the text first (and out of each
    attribute value), and the shorter ones must still be found in what is left."""
    pool = [page.stext(el)] + [sq for _k, sq, _raw in page.attrs(el)]
    for n in sorted(set(hard), key=lambda s: (-len(s), s)):
        if len(n) < 2:
            if n not in page.words(el):
                return False
            continue
        for i, s in enumerate(pool):
            j = s.find(n)
            if j >= 0:
                pool[i] = s[:j] + "\x00" + s[j + len(n):]
                break
        else:
            return False
    return True


def _holds(page, el, hard, apart=False):
    if apart:
        return _holds_apart(page, el, hard)
    stext = page.stext(el)
    attrs = None
    for n in hard:
        if len(n) < 2:
            if n not in page.words(el):
                return False
            continue
        if n in stext:
            continue
        if attrs is None:
            attrs = page.attrs(el)
        if not any(n in sq for _k, sq, _raw in attrs):
            return False
    return True


def _has_url(page, el, url):
    return any(k in _URL_ATTRS and (raw == url or url in [c.split()[0] for c in raw.split(",") if c.split()])
               for k, _sq, raw in page.attrs(el))


def _can_go(up, bound):
    """May an extent grow to `up`? Not past the document, and, inside a parent, only to a proper descendant of the
    parent's own extent `bound`."""
    if up is None or up.tag in _STOP_UP:
        return False
    if bound is None:
        return True
    p = up.parent
    while p is not None:
        if p is bound:
            return True
        p = p.parent
    return False


def _widened(page, scope, el, hard, bound):
    """The extent a candidate `el` grows to where the page SHOWS a value as text beside it that `el` holds only in an attribute (a
    video's title is the `title` of its iframe and the words of the caption beside it; a play link's `aria-label` repeats the caption
    next to it): the lowest ancestor, within three levels and `bound`, whose text holds those values too. `el` itself when none is
    needed, or none reaches. A value the page shows nowhere as text is left to the attribute (the lowest element still holds it)."""
    lone = [n for n in hard if len(n) >= 2 and n not in page.stext(el) and n in page.stext(scope)]
    top, hops = el, 0
    while lone and not all(n in page.stext(top) for n in lone):
        up = top.parent
        if hops == 3 or not _can_go(up, bound):
            return el
        top, hops = up, hops + 1
    return top


_SUBST_SKIP = frozenset(n for n in _NOT_TEXT_ATTRS if n not in ("class", "id"))


def _word_pattern(value):
    """A pattern for `value` as a whole word (or words) in a page: whitespace between its words is any whitespace,
    and it is not part of a longer word. A one-character value is looked for as the whole of a text or an attribute
    value only, never as a letter inside other text. None for no value at all."""
    words = value.split()
    if not words or not squash(value):
        return None
    if len(squash(value)) < 2:
        return re.compile(r"^(\s*)" + re.escape(words[0]) + r"(\s*)$")
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9])")


def _sub_slot(pat, slot, text):
    """`text` with `slot` written where `pat` matched (keeping the space around a whole-value match)."""
    marker = "{{%s}}" % slot
    if pat.groups:
        return pat.sub(lambda m: m.group(1) + marker + m.group(2), text)
    return pat.sub(marker, text)


class _Derivation(object):
    """The state of one `derive`: the templates found per (construct, part), and what each page's anchors explain."""

    def __init__(self, prefer_parent=False, prior=None):
        self.prefer_parent = prefer_parent                   # of readings that take one element, leave the wrappers to the parent
        self.prior = prior or {}                             # what the counting reading kept: {(construct, part): (markup, a call that holds it)}
        self.agreed = {}                                     # (id(call), markup) -> does it share the prior's markup of its part
        self.alts = collections.defaultdict(set)             # id(call) -> every markup any reading of it (at any wrapper) gives it
        self.vote = prior is not None                        # a reading with a prior (even an empty one) COUNTS INSTANCES (`_derive_look`)
        self.entries = collections.defaultdict(list)        # (construct, part) -> [(template, call)]
        self.explained = collections.defaultdict(set)       # id(page) -> {id(element inside an anchored extent)}
        self.runs = {}                                      # id(call) -> sibling nodes a multi-element part spans
        self.seen = {}                                      # (page, part, scope, bound) -> its readings, or the failure

    # ------------------------------------------------------------------------------------------ anchoring
    def anchors(self, page, scope, call, bound):
        """Candidate extents for `call` inside `scope`: the lowest elements holding every hard needle, moved out to
        the element that carries the call's own address, and, among several, those holding the most addresses."""
        hard, soft = _full_needles(call)
        _own_hard, own_soft = _own_needles(call)
        out = []
        if not hard and not soft:
            ints = _int_needles(call)
            if not ints:
                return []
            want = squash(ints[0])
            for el in walk(scope):
                if el.tag in _STOP_UP or page.stext(el) != want:
                    continue
                if any(isinstance(k, El) and page.stext(k) == want for k in el.kids):
                    continue
                out.append(el)
            return out
        if not hard:
            hard = list(soft)
        # a value the page does not show at all (a host name, a count the template leaves out) cannot place the
        # instance: the template simply has no slot for it. A needle found nowhere in `scope` is left out; the anchor
        # still holds every needle the page does show.
        hard = [n for n in hard if _holds(page, scope, [n])] or hard
        # a value that is only a part of another value of the same instance is looked for at a place of its own first; where no
        # element holds them so, the instance anchors as every earlier release read it
        for apart in ((True, False) if _has_nested(hard) else (False,)):
            for el in walk(scope):
                if el.tag in _STOP_UP or not _holds(page, el, hard, apart):
                    continue
                if any(isinstance(k, El) and _holds(page, k, hard, apart) for k in el.kids):
                    continue
                out.append(el)
            if out:
                break
        out = [_widened(page, scope, el, hard, bound) for el in out]
        if own_soft:
            fixed = []
            for el in out:
                top, hops = el, 0
                while not _has_url(page, top, own_soft[0]) and hops < 3:
                    up = top.parent
                    if not _can_go(up, bound):
                        break
                    top, hops = up, hops + 1
                fixed.append(top if _has_url(page, top, own_soft[0]) else el)
            out = fixed
            if len(out) > 1:
                best = max(sum(1 for u in own_soft if _has_url(page, e, u)) for e in out)
                out = [e for e in out if sum(1 for u in own_soft if _has_url(page, e, u)) == best]
        seen, uniq = set(), []
        for e in out:
            if id(e) not in seen:
                seen.add(id(e))
                uniq.append(e)
        return uniq

    # ------------------------------------------------------------------------------------------ one instance
    def instance(self, page, call, scope, bound):
        """Every way `call` anchors in `scope`: [(template map, extent, place, depth)], best first within a place.
        The map is {id(call): (template, suffix flag)} for the call and its descendants; `place` numbers the anchors
        (two places on one page); `depth` numbers the wrappers the extent includes (0 is the lowest). Raises _Fail
        when it anchors nowhere."""
        key = (id(page), id(call), id(scope), id(bound))
        hit = self.seen.get(key)
        if hit is not None:                 # the same part asked for inside the same element again (every wrapper reading of its parent asks)
            if isinstance(hit, _Fail):
                raise hit
            return hit
        try:
            hit = self.seen[key] = self._instance(page, call, scope, bound)
        except _Fail as e:
            self.seen[key] = e
            raise
        for tm, _e, _pl, _d in hit:
            for c in _tree(call):
                if id(c) in tm:
                    self.alts[id(c)].add(tm[id(c)])
        return hit

    def _instance(self, page, call, scope, bound):
        cands = self.anchors(page, scope, call, bound)
        if not cands:
            raise _Fail("unmapped", "no element of the page holds this instance's values")
        results, last = [], None
        for place, r0 in enumerate(cands):
            try:
                options = self._one(page, call, r0, bound)
                # `depth` is how many wrappers the extent takes in above the lowest one (a reading is the same extent
                # under another wrapper choice of its parts, so it is the extent, not the list position, that says)
                ups = [_height(ext) for _tm, ext in options]
                plain = [u for (tm, _e), u in zip(options, ups) if ("fill", id(call)) not in tm]
                base = max(plain or ups)                  # a reading kept for a parent that needs it does not move the others' depth
                for (tmap, ext), up in zip(options, ups):
                    results.append((tmap, ext, place, base - up))
            except _Fail as e:
                last = e
        if not results:
            last.where = (page, cands)
            raise last
        return results

    def _agrees(self, c, markup):
        """May `c` (read as `markup`, a (template, suffix flag)) share the markup the counting reading kept for its part? True where it
        kept none."""
        got = self.prior.get(c.key)
        text = markup[0] + (" " if markup[1] else "")
        if got is None or text == got[0]:
            return True
        k = (id(c), text)
        if k not in self.agreed:
            self.agreed[k] = _merge([(text, c), got], c.construct, c.part) is not None
        return self.agreed[k]

    def _kids_in(self, page, kids, r, tight=False, runs=False):
        """The extent of each searchable child inside `r`: {id(child): (template map, extent)}. A child takes the
        highest of its own wrapper variants that stays below `r` (a list item is its `li`, not its `a`); with `tight`
        (a number of wrappers, 0 for none) it takes the variant that many wrappers up, or the highest it has when it has
        fewer (the wrappers above a block that is alone in them are then the parent's, such as the element a page's
        body slot sits in). With `runs`, a child that fills `r` with its parent, or an element with another child, is read as a run of
        that element's children (`_runs_for_sharers`) instead of being refused."""
        cands = []
        for k in kids:
            allopts = self.instance(page, k, r, r)

            def own(o, k=k):
                """How much markup the parts BELOW the kid hold in a reading: of readings that take the same element, the one that
                leaves a wrapper to the parent (the parts below it hold the least) is taken, because a wrapper the parent owns serves
                every place the part below is used and one that part owns serves only the places that carry it (a showcase's span
                around an image a card does not wrap). Of those, the one whose parts below hold the markup the counting reading kept
                (`prior`) comes first: a list of ONE cannot say whether the `ul` is the list's or its item's, and the lists of several
                (every other `cards`) have said."""
                if not self.prefer_parent:
                    return (0, 0)
                below = [c for c in _tree(k) if c is not k and id(c) in o[0]]
                return (sum(1 for c in below if not self._agrees(c, o[0][id(c)])), sum(len(o[0][id(c)][0]) for c in below))
            if tight is None or tight is False:
                opts = sorted(allopts, key=lambda o: (("fill", id(k)) in o[0], o[2], -o[3], own(o)))
            else:
                opts = sorted(allopts, key=lambda o: (("fill", id(k)) in o[0], o[2],
                                                      abs(o[3] - tight) if o[3] <= tight else -o[3] + 1000, own(o)))
            cands.append([(tm, ext) for tm, ext, _pl, _d in opts])
        picks = self._choose(cands, runs)
        if picks is None:
            raise _Fail("ambiguous", "two instances of one construct share one element")
        if runs:
            picks = self._runs_for_sharers(page, kids, picks, r)
        extents = {}
        for k, pick in zip(kids, picks):
            self.runs[id(k)] = pick[0].get(("run", id(k)), 1)
            extents[id(k)] = pick
        return extents

    @staticmethod
    def _choose(cands, shared_ok):
        """One reading per child, the first of each child's own order that fits: no two children take the same element (unless
        `shared_ok`) and none takes an element that holds another child's (the children of one part are side by side, never one
        inside another: a wrapper that reaches over a sibling is not that part's own). None when no choice fits."""
        picks, budget = [], [4000]

        def clash(ext):
            for _tm, e in picks:
                if e is ext:
                    if not shared_ok:
                        return True
                elif _above(e, ext) or _above(ext, e):
                    return True
            return False

        def go(i):
            if i == len(cands):
                return True
            for opt in cands[i]:
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                if clash(opt[1]):
                    continue
                picks.append(opt)
                if go(i + 1):
                    return True
                picks.pop()
            return False
        return list(picks) if go(0) else None

    def _runs_for_sharers(self, page, kids, picks, r):
        """The children that fill one element with the parent (or with each other) read as RUNS of the children of that element:
        a part the plugin writes as one element (`previously-item`: a span around a link and a period) that a template writes
        as two siblings in the element the parent owns (`<span>..</span><i>..</i>` in a `p`). Each takes the children from where
        the one before it ended to the last that holds one of its values. Raises _Fail when a part holds no value to place it by."""
        by = collections.OrderedDict()
        for i, (_tm, ext) in enumerate(picks):
            by.setdefault(id(ext), []).append(i)
        out = list(picks)
        for idxs in by.values():
            ext = picks[idxs[0]][1]
            if len(idxs) < 2 and ext is not r:
                continue
            start = 0
            for i in idxs:
                tm, first, start = self._run_reading(page, kids[i], ext, start)
                out[i] = (tm, first)
        return out

    def _run_reading(self, page, call, p, start):
        """(template map, first node, next start) of `call` read as the run of `p`'s children, from the `start`th non-blank child,
        that holds every value the page shows of it and every part inside it."""
        searchable = [k for k in kids_of(call) if not _is_wild(k)]
        extents = self._kids_in(page, searchable, p)
        pos = [i for i, k in enumerate(p.kids) if not is_ws(k)]
        hard, _soft = _full_needles(call)
        lo, hi = len(pos), -1
        for n in hard:
            for j in range(start, len(pos)):
                if _node_holds(page, p.kids[pos[j]], n):
                    lo, hi = min(lo, j), max(hi, j)
                    break
        for _tm, ext in extents.values():
            top = ext
            while top is not None and top.parent is not p:
                top = top.parent
            if top is not None and top in [p.kids[i] for i in pos]:
                j = [p.kids[i] for i in pos].index(top)
                if j >= start:
                    lo, hi = min(lo, j), max(hi, j)
        if hi < 0:
            raise _Fail("unmapped", "no element of the page holds this part's values as a run of neighbouring nodes")
        tm, first = self._run_template(page, call, p, pos[lo], pos[hi], extents)[0]
        return tm, first, hi + 1

    def _one(self, page, call, r0, bound):
        """The options for `call` anchored at `r0`: [(template map, extent)], lowest first. The extent is moved up
        while a child covers it exactly; the options after it are the single-child wrappers above (an instance alone
        in its list cannot say whether `ul` or `li` is its own, so both are offered and the instances of the same part
        decide, in derive_look). A child alone in a wrapper is read both ways too: the wrapper is the child's (the
        reading first, as a list item takes its `li`) or the parent's (`tight`), and the instances of the part decide
        again."""
        kids = kids_of(call)
        searchable = [k for k in kids if not _is_wild(k)]
        if _tops(call) > 1:
            try:
                return self._one_multi(page, call, r0, searchable)
            except _Fail as multi:
                # the template does not write the part as the plugin does (a heading around the name and the count, where the plugin
                # writes two sibling spans): the part is the one element that holds what the page shows of it
                try:
                    return self._one_elements(page, call, r0, bound, searchable)
                except _Fail:
                    raise multi
        return self._one_elements(page, call, r0, bound, searchable)

    def _one_elements(self, page, call, r0, bound, searchable):
        out = self._one_read(page, call, r0, bound, searchable, None)
        if searchable:
            have = set(self._reading_sig(o, call) for o in out)
            for tight in (0, 1):
                try:
                    more = self._one_read(page, call, r0, bound, searchable, tight)
                except _Fail:
                    continue
                for o in more:
                    sig = self._reading_sig(o, call)
                    if sig not in have:
                        have.add(sig)
                        out.append(o)
        return out

    @staticmethod
    def _reading_sig(option, call):
        """What a reading says about the call and its parts: each part's template, in a stable order."""
        tmaps = option[0]
        return tuple(sorted((c.key, tmaps[id(c)]) for c in _tree(call) if id(c) in tmaps))

    def _one_read(self, page, call, r0, bound, searchable, tight):
        """The readings of `call` at `r0`: the extent moved up while a child fills it (the wrapper above is the parent's), then the
        single-child wrappers above; and, where a child filled an element with its parent or with another child, the reading in
        which the parent keeps that element and the children are runs of its children (after the others, so a part that derived as
        it always did derives so)."""
        r, fill, out, failure = r0, None, [], None
        try:
            while True:
                try:
                    extents = self._kids_in(page, searchable, r, tight)
                except _Fail as e:
                    if e.why == _SHARE and fill is None:
                        fill = r
                    raise
                if not any(ext is r for _t, ext in extents.values()):
                    break
                if fill is None:
                    fill = r
                up = r.parent
                if not _can_go(up, bound):
                    raise _Fail("unmapped", "the instance and one of its parts share one element")
                r = up
            out = self._read_variants(page, call, r, extents, bound, searchable, tight)
        except _Fail as e:
            failure = e
        if fill is not None and searchable:
            try:
                runs = self._options(call, [(fill, self._kids_in(page, searchable, fill, tight, True))])
                for tm, _ext in runs:
                    tm[("fill", id(call))] = True       # a reading kept for the parent that needs it (`_choose`), never a root's own
                out = out + runs
            except _Fail:
                pass
        if not out:
            raise failure
        return out

    def _read_variants(self, page, call, r, extents, bound, searchable, tight):
        variants = [(r, extents)]
        cur = r
        beside = _fixed_beside(call)
        while len(variants) < 3:
            up = cur.parent
            if (not _can_go(up, bound)
                    or any(isinstance(k, Tx) and k.data.strip() for k in up.kids)):
                break
            sibs = [k for k in up.kids if isinstance(k, El)]
            # a wrapper alone around the extent, or one that holds the extent and the fixed element(s) the plugin's own markup for
            # the part writes beside it: the section around a heading and a list of ONE, where nothing but the heading says that the
            # section is the part's and the list's wrapper is not (`_fixed_beside`)
            if sibs != [cur] and not (beside and sorted(k.tag for k in sibs if k is not cur) == beside and cur in sibs):
                break
            try:
                variants.append((up, self._kids_in(page, searchable, up, tight)))
            except _Fail:
                break
            cur = up
        return self._options(call, variants)

    def _options(self, call, variants):
        out = []
        for v, exts in variants:
            tmaps = {}
            for tm, _e in exts.values():
                tmaps.update(tm)
            template, flags, fixed = self._template(call, v, exts)
            tmaps[id(call)] = (template, False)
            for cid_, tpl in fixed.items():
                tmaps[cid_] = (tpl, False)
            for key, flag in flags.items():
                if flag and key in tmaps:
                    tmaps[key] = (tmaps[key][0], True)
            out.append((tmaps, v))
        return out

    # ------------------------------------------------------------------------------------------ the template
    def _one_multi(self, page, call, p, searchable):
        """A part that writes several sibling elements (the home page's intro and its endorsement): its extent is the
        run of `p`'s children that holds them, and its template is those nodes one after another."""
        extents = self._kids_in(page, searchable, p)
        items, kid_orig = [], dict((k, ext) for k, (_t, ext) in extents.items())
        for it in _out_items(call):
            if it[0] == "kid" and id(it[1]) not in kid_orig:
                items.append(("wild", max(1, _tops(it[1])), it[1]))
            else:
                items.append(it)
        kidset = set(id(e) for e in kid_orig.values())
        pos = [i for i, k in enumerate(p.kids) if not is_ws(k)]
        for st in range(len(pos)):
            m = self._match(p, pos, st, items, kid_orig, kidset)
            if m is not None:
                break
        else:
            raise _Fail("unmapped", "the page holds this part's elements in no run of neighbouring nodes")
        a, b, _wild = m
        return self._run_template(page, call, p, a, b, extents)

    def _run_template(self, page, call, p, a, b, extents):
        """[(template map, first node)] for `call` read as `p.kids[a..b]`: those nodes one after another are its template."""
        cmap, root = {}, El("#root")
        for node in p.kids[a:b + 1]:
            c = _copy(node, cmap)
            c.parent = root
            root.kids.append(c)
        n = len([k for k in p.kids[a:b + 1] if not is_ws(k)])
        self.runs[id(call)] = n
        first = next(k for k in p.kids[a:b + 1] if not is_ws(k))
        tmaps = {}
        for tm, _e in extents.values():
            tmaps.update(tm)
        template, flags, fixed = self._template_in(call, root, cmap, extents)
        tmaps[id(call)] = (template, False)
        tmaps[("run", id(call))] = n
        for cid_, tpl in fixed.items():
            tmaps[cid_] = (tpl, False)
        for key, flag in flags.items():
            if flag and key in tmaps:
                tmaps[key] = (tmaps[key][0], True)
        return [(tmaps, first)]

    def _template(self, call, r, extents):
        cmap = {}
        return self._template_in(call, _copy(r, cmap), cmap, extents)

    def _template_in(self, call, root, cmap, extents):
        flags, fixed, kid_copy = {}, {}, {}
        for k in kids_of(call):
            if id(k) in extents:
                kid_copy[id(k)] = cmap.get(id(extents[id(k)][1]))
        inside = set()
        for node in kid_copy.values():
            if node is not None:
                inside.update(id(e) for e in walk(node))
        for slot in call.slot_order():
            if call.table[slot] != looks.HTML or not call.values.get(slot):
                continue
            items = _value_items(call, slot)
            if items:
                self._replace_run(root, slot, items, kid_copy, inside, flags, fixed)
        for slot in call.all_slots():
            kind, v = call.table[slot], call.values.get(slot)
            if v is None or v == "":
                continue
            if kind == looks.TEXT:
                # a slot the page does not show can only be a markup hook (a class token, a data attribute)
                self._text_slot(root, slot, str(v), inside, attrs_only=slot not in call.used)
            elif kind in (looks.URL, looks.CONTACT, looks.SRCSET, looks.EMBED, looks.POSITION):
                self._url_slot(root, slot, kind, str(v))
        return ser(root), flags, fixed

    def _replace_run(self, root, slot, items, kid_copy, inside, flags, fixed):
        """Replace the sibling run that holds html slot `slot`'s items by one marker."""
        placed = []
        for it in items:
            if it[0] == "kid" and id(it[1]) not in kid_copy:
                placed.append(("wild", max(1, _tops(it[1])), it[1]))
            else:
                placed.append(it)
        if all(it[0] == "wild" for it in placed):
            raise _Fail("unmapped", "a slot holds only fixed markup, so nothing in the page says where it is")
        kidset = set(id(v) for v in kid_copy.values())
        for p in walk(root):
            if id(p) in inside:
                continue
            pos = [i for i, k in enumerate(p.kids) if not is_ws(k) and not isinstance(k, Mk)]
            for st in range(len(pos)):
                m = self._match(p, pos, st, placed, kid_copy, kidset)
                if m is None:
                    continue
                a, b, wild = m
                self._swap(p, a, b, slot, placed, flags)
                for key, nodes in wild.items():
                    fixed[key] = "".join(ser(n) for n in nodes)
                return
        if len(placed) == 1 and placed[0][0] == "tx" and self._text_slot(root, slot, placed[0][2], inside):
            return
        raise _Fail("unmapped", "the page holds this slot's content in no run of neighbouring nodes that matches it")

    def _span(self, it):
        """How many sibling nodes an item takes: a fixed part, or a part that writes several elements, takes more."""
        if it[0] == "wild":
            return it[1]
        return self.runs.get(id(it[1]), 1) if it[0] == "kid" else 1

    def _match(self, p, pos, st, items, kid_copy, kidset):
        need = sum(self._span(it) for it in items)
        if st + need > len(pos):
            return None
        cur, wild = st, {}
        for it in items:
            if it[0] == "wild":
                nodes = [p.kids[pos[cur + j]] for j in range(it[1])]
                if any(id(n) in kidset for n in nodes):
                    return None
                wild[id(it[2])] = nodes
                cur += it[1]
                continue
            node = p.kids[pos[cur]]
            if it[0] == "kid":
                if node is not kid_copy.get(id(it[1])):
                    return None
                cur += self._span(it)
                continue
            if it[0] == "el":
                if not isinstance(node, El) or node.tag != it[1] or squash(text_of(node)) != it[2]:
                    return None
            elif not isinstance(node, Tx) or squash(node.data) != it[1]:
                return None
            cur += 1
        return pos[st], pos[cur - 1], wild

    def _swap(self, p, a, b, slot, items, flags):
        """Replace p.kids[a..b] by a marker, settling the space between members (module docstring: whitespace)."""
        members = [i for i in range(a, b + 1) if not is_ws(p.kids[i])]
        gaps = [any(is_ws(p.kids[i]) for i in range(m1 + 1, m2)) for m1, m2 in zip(members, members[1:])]
        end = b
        if all(it[0] in ("kid", "wild") for it in items):
            trail = end + 1 < len(p.kids) and is_ws(p.kids[end + 1])
            if gaps and any(gaps) and not all(gaps):
                raise _Fail("unmapped", "the space between items differs from one to the next")
            if (all(gaps) if gaps else trail):
                if not trail:
                    raise _Fail("unmapped", "the items are spaced apart but nothing follows the last one")
                end += 1
                for it in items:
                    flags[id(it[1] if it[0] == "kid" else it[2])] = True
        mk = Mk(slot)
        mk.parent = p
        p.kids[a:end + 1] = [mk]

    def _text_slot(self, root, slot, value, inside=(), attrs_only=False):
        """Write `slot` where `value` stands as a whole word in a text node or a text attribute. True if it did. With `attrs_only` (a slot
        the plugin's own markup does not show) a text node is the slot only where the value is the WHOLE text of the node and is more than
        a couple of letters: a template may show the employer in a line of its own where the plugin does not, and that line is the slot,
        never the person's own words; a word that is merely one of several in a line stays literal (a coincidence is not a slot)."""
        pat = _word_pattern(value)
        if pat is None:
            return False
        done = False
        whole = squash(value) if attrs_only and len(squash(value)) >= 3 else None
        for el in list(walk(root)):
            if id(el) in inside:
                continue
            for i, (name, val) in enumerate(el.attrs):
                if val is None or name in _SUBST_SKIP or name == "style":
                    continue
                if name in ("class", "id") and len(squash(value)) < 3:
                    continue
                if pat.search(val):
                    el.attrs[i] = (name, _sub_slot(pat, slot, val))
                    done = True
            for i, k in enumerate(el.kids):
                if not attrs_only and isinstance(k, Tx) and pat.search(k.data):
                    t = Tx(_sub_slot(pat, slot, k.data))
                    t.parent = el
                    el.kids[i] = t
                    done = True
                elif whole is not None and isinstance(k, Tx) and squash(k.data) == whole:
                    lead, trail = k.data[:len(k.data) - len(k.data.lstrip())], k.data[len(k.data.rstrip()):]
                    t = Tx("%s{{%s}}%s" % (lead, slot, trail))
                    t.parent = el
                    el.kids[i] = t
                    done = True
        return done

    def _url_slot(self, root, slot, kind, value):
        for el in walk(root):
            for i, (name, val) in enumerate(el.attrs):
                if val is None:
                    continue
                same = val.strip() == value.strip()
                if kind in (looks.URL, looks.CONTACT) and name in ("href", "src", "cite") and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.SRCSET and name == "srcset" and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.EMBED and name in ("src", "data-embed") and same:
                    el.attrs[i] = (name, "{{%s}}" % slot)
                elif kind == looks.POSITION and name == "style" and \
                        _WS.sub("", val) == "object-position:" + _WS.sub("", value):
                    el.attrs[i] = (name, "object-position: {{%s}}" % slot)


# --------------------------------------------------------------------------------------------- merge and agree
_PROTECT = dict((ord(d), chr(0xE100 + int(d))) for d in "0123456789")


def _expand(template, call):
    """`template` with each slot of `call`'s values written back as a page would hold it: a text, url, srcset, embed,
    contact or position slot as its escaped value, with its digits PROTECTED (so only a digit the template itself
    holds is ever read as a number); an int slot as its digits; an html slot as its marker when it holds anything,
    and as nothing when it holds nothing."""
    def sub(m):
        slot = m.group(1)
        kind = call.table.get(slot)
        v = call.values.get(slot)
        if kind is None:
            return m.group(0)
        if kind == looks.HTML:
            return m.group(0) if v else ""
        if v is None:
            return ""
        if kind == looks.INT:
            return str(v)
        return C.esc(_collapse(str(v))).translate(_PROTECT)
    return _SLOT.sub(sub, template)


def _align_ints(cand, entries, expanded):
    """`cand` with each of its literal digit runs written as the int slot whose value it is in EVERY instance, where
    the instances differ there; None when the instances are not shaped alike or a varying digit run is no int slot's
    value. `expanded` is [(its own expansion of `cand`, the instance's own expansion)] per instance."""
    int_slots = [s for s, k in looks.CONSTRUCTS[entries[0][1].construct]["parts"][entries[0][1].part].items()
                 if k == looks.INT]
    h_parts = [re.split(r"(\d+)", h) for h, _g in expanded]
    g_parts = [re.split(r"(\d+)", g) for _h, g in expanded]
    if any(len(h) != len(g) for h, g in zip(h_parts, g_parts)):
        return None
    if any(h[i] != g[i] for h, g in zip(h_parts, g_parts) for i in range(0, len(h), 2)):
        return None
    toks = re.split(r"(\d+)", cand)
    if len(toks) != len(h_parts[0]):
        return None
    for i in range(1, len(toks), 2):
        gs = [g[i] for g in g_parts]
        if all(g == h[i] for g, h in zip(gs, h_parts)):
            continue
        for slot in int_slots:
            vals = [str(c.values.get(slot)) for _t, c in entries]
            if len(set(vals)) >= 2 and gs == vals:
                toks[i] = "{{%s}}" % slot
                break
        else:
            return None
    return "".join(toks)


def _merge(entries, construct, part):
    """One template for every instance of a part, or None when they do not share one. A candidate is accepted when,
    written back with each instance's own values, it gives that instance's own page text; a number that differs
    between instances is written as the int slot whose value it is, and only there."""
    templates = []
    for t, _c in entries:
        if t not in templates:
            templates.append(t)
    if len(templates) == 1:
        return templates[0]
    got = [_expand(t, c) for t, c in entries]
    for cand in sorted(templates, key=lambda t: -t.count("{{")):
        for refined in (cand, _align_words(cand, entries, got)):
            if refined is None:
                continue
            mine = [_expand(refined, c) for _t, c in entries]
            if got == mine:
                return refined
            aligned = _align_ints(refined, entries, list(zip(mine, got)))
            if aligned is not None and all(_expand(aligned, c) == g for (_t, c), g in zip(entries, got)):
                return aligned
    return None


def _majority(entries, construct, part):
    """(template, [entries that do not share it]) for the markup MORE THAN HALF of the instances share, or (None, [])
    when no markup has that many. An instance whose own markup differs from the rest (a link the template points
    elsewhere for one page, a wrapper one page lacks) is left out and named, so one odd instance does not take the
    whole construct away; the page it is on stays DIFFERENT in parity, which is what says so."""
    best = (None, [])
    for lead in {t for t, _c in entries}:
        group = [e for e in entries if e[0] == lead]
        rest = [e for e in entries if e[0] != lead]
        for e in list(rest):
            if _merge(group + [e], construct, part) is not None:
                group.append(e)
                rest.remove(e)
        tpl = _merge(group, construct, part)
        if tpl is not None and len(group) * 2 > len(entries) and (
                best[0] is None or len(group) > len(entries) - len(best[1])):
            best = (tpl, rest)
    return best


def _align_words(cand, entries, got):
    """`cand` with each slot marker that does not stand for the slot's value in EVERY instance written as the text it
    stands for: a word that is a slot's value in some instances only is a coincidence (the `work` in `tn-work` is the
    portfolio's name in one portfolio and a fixed class in the next), so it stays literal. None when an instance does
    not fit `cand`'s shape, or a marker is neither its slot's value everywhere nor one text everywhere."""
    parts = re.split(r"(\{\{[a-z][a-z0-9]*\}\})", cand)
    marks = [(i, p[2:-2]) for i, p in enumerate(parts) if i % 2 == 1]
    caps = []
    for (_t, c), g in zip(entries, got):
        rx = []
        for i, p in enumerate(parts):
            if i % 2 == 0:
                rx.append(re.escape(p))
            else:
                slot = p[2:-2]
                kind = c.table.get(slot)
                if kind is None:
                    return None
                if kind == looks.HTML:
                    rx.append(re.escape(p) if c.values.get(slot) else "")
                else:
                    rx.append("(.*?)")
        m = re.fullmatch("".join(rx), g, re.S)
        if m is None:
            return None
        it = iter(m.groups())
        caps.append([None if entries[0][1].table.get(s) == looks.HTML else next(it) for _i, s in marks])
    out = list(parts)
    for k, (i, slot) in enumerate(marks):
        if entries[0][1].table.get(slot) == looks.HTML:
            continue
        vals = [_expand("{{%s}}" % slot, c) for _t, c in entries]
        seen = [cap[k] for cap in caps]
        if seen == vals:
            continue
        if len(set(seen)) == 1 and entries[0][1].table.get(slot) != looks.INT:
            out[i] = seen[0].translate(dict((v, k2) for k2, v in _PROTECT.items()))
            continue
        return None
    return "".join(out)


# ================================================================================================ derive, whole
class Derivation(object):
    def __init__(self):
        self.look = {"look": looks.LOOK_FORMAT, "constructs": {}}
        self.status = collections.OrderedDict()      # construct -> Counter of statuses (by distinct instance)
        self.reasons = {}                             # construct -> first reason it did not map
        self.unexplained = collections.Counter()
        self.pages_read = 0
        self.mapped_instances = 0
        self.consensus = {}                           # (construct, part) -> (the markup it kept, a call that holds it): the next reading's prior

    @property
    def text(self):
        return json.dumps(self.look, indent=2, ensure_ascii=False) + "\n"

    def lines(self):
        out = []
        for cid in looks.CONSTRUCTS:
            if cid not in self.status:
                continue
            c = self.status[cid]
            line = "%s: %s" % (cid, ", ".join("%s %d" % (s, c[s]) for s in STATUSES if c.get(s)))
            if cid in self.reasons and not c.get("mapped"):
                line += " (%s)" % self.reasons[cid]
            out.append(line)
        silent = [cid for cid in looks.CONSTRUCTS if cid not in self.status]
        out.append("%d construct(s) have no instance in this repository's content: the plugin's markup is used"
                   % len(silent))
        if self.unexplained:
            out.append("text no content explains, by element: " + ", ".join(
                "element/%s x%d" % (t, n) for t, n in sorted(self.unexplained.items())))
        return out


def _sanitise(message):
    return re.sub(r"'[^']*'|\"[^\"]*\"", "...", message)[:90]


def _height(el):
    """How many elements stand above `el` in its page."""
    n = 0
    while el.parent is not None:
        el = el.parent
        n += 1
    return n


def _tree(call):
    yield call
    for k in kids_of(call):
        for d in _tree(k):
            yield d


def _opt_sig(root, tmap):
    """What an option says about each part: the key, the template and the suffix flag, in a stable order."""
    return tuple(sorted((c.key, tmap[id(c)]) for c in _tree(root) if id(c) in tmap))


def derive_look(files, pages, never=(), recorded=None, refine=True):
    """`_derive_look`, read again when the first reading leaves an instance `ambiguous` (`refine`; adopt's per-candidate scoring reads
    once, the look it keeps is read up to four times):

      1. the reading every earlier release gave;
      2. the one that prefers, among the readings that take one element, the one that leaves a wrapper to the PARENT (a wrapper that a
         part owns only serves the places that carry it, and two places that do not agree make the part `ambiguous`);
      3. the one that COUNTS INSTANCES (`_derive_look`, THE MARKUP MORE INSTANCES CAN SHARE WINS): a markup more instances cannot share
         than can is read last, so the page that wraps its one reference card in a grid is the page that differs, not the home page;
      4. the one that does both and is told what the third kept (a list of ONE cannot say whether the `ul` is the list's or its item's,
         and the lists of several have said; a wrapper only one place carries is the parent's).

    The reading that maps the most instances is the answer, then the one that names the fewest `ambiguous`; on a tie, the earlier (the
    first is what every earlier release gave, so a site that derived cleanly derives as it did)."""
    calls_pages = recorded if recorded is not None else record(files)
    best = _derive_look(files, pages, never, calls_pages, False)
    if not refine or not any(c.get("ambiguous") for c in best.status.values()):
        return best
    counted = None
    for prefer, prior in ((True, None), (False, {}), (True, "counted")):
        if prior == "counted":
            if counted is None:
                continue
            prior = counted.consensus
        try:
            more = _derive_look(files, pages, never, calls_pages, prefer, prior)
        except LookCommandError:
            continue
        if prior == {} and not prefer:
            counted = more
        if _quality(more) > _quality(best):
            best = more
    return best


def _quality(d):
    """What a reading is worth: the instances it maps, then (of readings that map as many) the fewer it names `ambiguous`."""
    return (d.mapped_instances, -sum(c.get("ambiguous", 0) for c in d.status.values()))


def _derive_look(files, pages, never, recorded, prefer_parent, prior=None):
    """Derive a look from this tree's content and `pages` ({key: html text}; a key is an output path such as
    `work/x/index.html`, or a page's own path). `never` is the output paths of pages the content built that were not
    read (a cap, a refusal): an instance found nowhere on those is `not reached`. `recorded` is `record(files)`'s
    result when the caller already holds it. Returns a `Derivation`. Raises LookCommandError when the tree does not
    build, no page is given, or no instance anchors anywhere (R5.4(c))."""
    calls, built = recorded if recorded is not None else record(files)
    parsed = [Page(k, t) for k, t in pages.items()]
    if not parsed:
        raise LookCommandError("no page was read, so there is nothing to derive a look from; read the pages with "
                               "--build <folder of built pages>, or check the address")
    result = Derivation()
    result.pages_read = len(parsed)
    by_key = dict((p.key, p) for p in parsed)
    never = set(never)
    state = _Derivation(prefer_parent, prior)
    seen_root, outcome, instances = set(), {}, {}
    pending = []                                # (root, page, [(sig, tmap, ext, place, depth)])
    salvaged = []                               # the same, for parts read on their own because their parent could not be mapped
    def read(root, scope=None):
        """(page, options) of the first page that holds `root`, else (None, the failure, the pages it was built into). `scope` is
        (page, element): the part is looked for inside that element of that page only (as it is inside its parent), else page-wide."""
        want = [k for k, h in built.items() if root.out and root.out in h]
        if scope is not None:
            page, el = scope
            try:
                opts = state.instance(page, root, el, el)
            except _Fail as e:
                return None, e, want
            plain = [o for o in opts if ("fill", id(root)) not in o[0]]
            return (page, [(_opt_sig(root, tm), tm, ext, pl, d) for tm, ext, pl, d in (plain or opts)]), None, want
        ordered = [by_key[k] for k in want if k in by_key] + [p for p in parsed if p.key not in want]
        failure = None
        for page in ordered:
            try:
                opts = state.instance(page, root, page.root, None)
            except _Fail as e:
                if failure is None:
                    failure = e
                elif failure.where is None:
                    failure.where = e.where         # the first page that held the part's values at all
                continue
            plain = [o for o in opts if ("fill", id(root)) not in o[0]]
            return (page, [(_opt_sig(root, tm), tm, ext, pl, d) for tm, ext, pl, d in (plain or opts)]), None, want
        return None, failure or _Fail("unmapped", "no page was read"), want

    def settle(root, failure, want, where):
        """`root` could not be mapped: it is named, and the parts inside it that the page DOES hold are read on their own, inside the
        element that held the whole of it (a part that cannot be mapped does not take the parts inside it with it: the home page's body
        is a run the builder writes in one order, a template may set the same parts in another, and the showcase in it is still the
        showcase). Where nothing held the whole of it, its parts are not looked for."""
        status = failure.status
        if status == "unmapped" and not any(k in by_key for k in want) and any(k in never for k in want):
            status = "not reached"
        outcome[id(root)] = (status, failure.why)
        claimed = set()                     # the elements the parts read so far hold: two parts of one parent are never one element
        for kid in kids_of(root):
            got = None
            if where is not None:
                page, cands = where
                for el in cands:
                    first, _fail, _kwant = read(kid, (page, el))
                    if first is None:
                        continue
                    opts = [o for o in first[1] if id(o[2]) not in claimed]
                    if not opts:
                        continue
                    nearest = min(o[3] for o in opts)       # the first place that is still free (the same reference twice on a page)
                    opts = [o for o in opts if o[3] == nearest]
                    # only a part the page reads one way: where it can be read several ways (a list of one: is the `ul` or the `li` its
                    # own?) the parent's own extent decided that, and the parent is gone
                    if len(set(o[0] for o in opts)) == 1:
                        got = (first[0], opts)
                        break
            if got is not None:
                salvaged.append((kid, got[0], got[1]))
                for o in got[1]:
                    claimed.update(id(e) for e in walk(o[2]))
            else:
                settle(kid, failure, want, where)       # the reason is the part's whose parts these are: it is why they were not placed

    for root in [c for c in calls if c.parent is None]:
        sig = (root.construct, root.part, root.out)
        if sig in seen_root:
            continue
        seen_root.add(sig)
        got, failure, want = read(root)
        if got is not None:
            pending.append((root, got[0], got[1]))
            continue
        settle(root, failure, want, failure.where)

    accepted = collections.defaultdict(list)

    def conflicts(root, tmap, hold=()):
        """The calls of `root` whose markup, in the reading `tmap`, cannot be one markup with what the parts accepted so far hold
        (the `hold` calls are not asked: they are offered later)."""
        out = set()
        for c in _tree(root):
            if id(c) in tmap and id(c) not in hold:
                tpl, suf = tmap[id(c)]
                cur = accepted[c.key]
                if cur and _merge(cur + [(tpl + (" " if suf else ""), c)], c.construct, c.part) is None:
                    out.add(id(c))
        return out

    def consistent(root, tmap, hold=()):
        return not conflicts(root, tmap, hold)

    def commit(root, page, tmap, exts, skip=()):
        for c in _tree(root):
            if id(c) in tmap and id(c) not in skip:
                tpl, suf = tmap[id(c)]
                state.entries[c.key].append((tpl + (" " if suf else ""), c))
                accepted[c.key].append((tpl + (" " if suf else ""), c))
                instances[id(c)] = c
        for ext in exts:
            for el in walk(ext):
                state.explained[id(page)].add(id(el))

    # an instance with one reading fixes the templates; an instance with several (a list of one: is the `ul` or the
    # `li` the part's own?) takes the reading the others agree with
    ordered_pending = [p for p in pending if len({o[0] for o in p[2]}) == 1] + \
                      [p for p in pending if len({o[0] for o in p[2]}) != 1]
    # how many instances can read a part with a given markup: of several readings that all fit what is fixed so far, the
    # one the most other instances can share is taken (the wrapper above a block belongs to the block when every other
    # instance of it carries that wrapper, and to its parent when they do not)
    support = collections.Counter()
    for root, _page, opts in pending:
        seen_here = set()
        for o in opts:
            for c in _tree(root):
                if id(c) in o[1]:
                    seen_here.add((c.key, o[1][id(c)]))
        support.update(seen_here)

    def score(reading):
        return sum(support[(c.key, reading[1][id(c)])] for c in _tree(root_now[0]) if id(c) in reading[1])
    root_now = [None]
    # THE MARKUP MORE INSTANCES CAN SHARE WINS (G3 derive link 2). A reading gives a part a markup; every OTHER instance of the part
    # either has a reading that can share it (`_merge`) or has none. A reading that leaves more instances without a shareable reading
    # than there are instances (itself included) that can share it is OUTVOTED, and an instance every reading of which is outvoted is
    # placed LAST: a reference card the home page's feed and samples write as a bare link, and one piece's page wraps in a grid of one,
    # is the bare link (the two cards outvote the one), and the piece's page is the one that differs.
    readings, calls_of = {}, collections.defaultdict(dict)       # id(call) -> the markups any reading of its root gives it; part -> calls
    for root, _page, opts in pending:
        for c in _tree(root):
            ms = set(o[1][id(c)] for o in opts if id(c) in o[1]) | state.alts.get(id(c), set())
            if ms:
                readings[id(c)] = ms
                calls_of[c.key][id(c)] = c
    shares = {}

    def shares_markup(c1, m1, c2, m2):
        """Can the instance `c1` read as `m1` and the instance `c2` read as `m2` be one markup of the part (`_merge`)? A markup that is
        only the more general of two (`{{portfolio}}-item` for the `work-item` of one portfolio) shares."""
        if m1 == m2:
            return True
        k = (id(c1), m1, id(c2), m2)
        if k not in shares:
            shares[k] = _merge([(m1[0] + (" " if m1[1] else ""), c1), (m2[0] + (" " if m2[1] else ""), c2)],
                               c1.construct, c1.part) is not None
        return shares[k]

    def outvoted(root, reading):
        """The calls of `root` whose markup, in `reading`, more instances cannot share than can (themselves included)."""
        own, out = set(id(c) for c in _tree(root)), set()
        for c in _tree(root):
            if not state.vote or id(c) not in reading[1]:          # only a counting reading votes (the first is what every release gave)
                continue
            mine, can, cannot = reading[1][id(c)], 1, 0
            for c2 in calls_of[c.key].values():
                if id(c2) in own:
                    continue
                if any(shares_markup(c, mine, c2, m2) for m2 in readings[id(c2)]):
                    can += 1
                else:
                    cannot += 1
            if cannot > can:
                out.add(id(c))
        return out

    def place(root, page, opts, hold=()):
        root_now[0] = root
        keep = sorted((o for o in opts if consistent(root, o[1], hold)), key=lambda o: -score(o))
        if not keep:
            # no reading agrees with what is accepted: the reading with the fewest such parts is kept, and those parts alone are named
            # `ambiguous` (a home page does not lose its wrapper, its heading and every part inside it because one list of links is
            # marked up as the resume page marks it). Which markup stands is the one accepted first when the instances tie.
            best = min(opts, key=lambda o: (len(conflicts(root, o[1], hold)), -score(o)))
            skip = conflicts(root, best[1], hold)
            if len(skip) == sum(1 for c in _tree(root) if id(c) in best[1] and id(c) not in hold):
                for c in _tree(root):
                    outcome[id(c)] = ("ambiguous", "no reading of this instance agrees with the other instances of the part")
                return
            for c in _tree(root):
                if id(c) in skip:
                    outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
            commit(root, page, best[1], [o[2] for o in opts if o[0] == best[0]], set(skip) | set(hold))
            return
        places = {}
        for o in keep:
            places.setdefault(o[3], []).append(o[0])
        if len(places) > 1 and len({ss[0] for ss in places.values()}) > 1:
            for c in _tree(root):
                outcome[id(c)] = ("ambiguous", "two places in the page hold this instance with different markup")
            return
        commit(root, page, keep[0][1], [o[2] for o in keep if o[0] == keep[0][0]], hold)

    last, held = [], []
    for root, page, opts in ordered_pending:
        root_now[0] = root
        sigs = []
        for o in opts:
            if o[0] not in sigs:
                sigs.append(o[0])
        live = [o for o in opts if not outvoted(root, o)]
        if not live:
            last.append((root, page, opts))
        elif len(sigs) == 1:
            commit(root, page, live[0][1], [o[2] for o in live])
        else:
            place(root, page, live)
    # an instance every reading of which holds a part the majority cannot share: the reading with the fewest such parts is committed
    # WITHOUT them, and each of them is offered last, after every other instance has fixed its markup (the home page keeps its wrapper
    # and every part inside it where one part is another page's odd one out, and the page that differs is the one that says so)
    for root, page, opts in last:
        root_now[0] = root
        best = min(opts, key=lambda o: (len(outvoted(root, o)), -score(o)))
        out = outvoted(root, best)
        held.append((root, best, out))
        place(root, page, [best], out)
    for root, best, out in held:
        for c in _tree(root):
            if id(c) not in out:
                continue
            tpl, suf = best[1][id(c)]
            cur = accepted[c.key]
            if cur and _merge(cur + [(tpl + (" " if suf else ""), c)], c.construct, c.part) is None:
                outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
                continue
            state.entries[c.key].append((tpl + (" " if suf else ""), c))
            accepted[c.key].append((tpl + (" " if suf else ""), c))
            instances[id(c)] = c

    # parts read on their own come LAST and only add: where a reading agrees with everything the other readings fixed it is kept,
    # where it does not it is named `ambiguous` and the others stand (a part another page wrote differently never takes away what
    # an instance of its own parent gave)
    for root, page, opts in salvaged:
        root_now[0] = root
        keep = sorted((o for o in opts if consistent(root, o[1])), key=lambda o: -score(o))
        if not keep:
            for c in _tree(root):
                outcome[id(c)] = ("ambiguous", "no reading of this instance agrees with the other instances of the part")
            continue
        places = {}
        for o in keep:
            places.setdefault(o[3], []).append(o[0])
        if len(places) > 1 and len({ss[0] for ss in places.values()}) > 1:
            for c in _tree(root):
                outcome[id(c)] = ("ambiguous", "two places in the page hold this instance with different markup")
            continue
        commit(root, page, keep[0][1], [o[2] for o in keep if o[0] == keep[0][0]])

    bad = {}
    for (cid, pn), entries in sorted(state.entries.items()):
        tpl = _merge(entries, cid, pn)
        if tpl is None:
            tpl, odd = _majority(entries, cid, pn)
            if tpl is None:
                bad.setdefault(cid, ("ambiguous", "instances of one part do not share one markup"))
                continue
            for _t, c in odd:         # the markup most instances share is used; the others are named, never guessed
                outcome[id(c)] = ("ambiguous", "this instance's markup differs from the one most instances share")
        problems = looks.check_part(cid, pn, tpl)
        if problems:
            bad.setdefault(cid, ("unmapped", _sanitise(problems[0][0])))
            continue
        result.look["constructs"].setdefault(cid, {})[pn] = tpl
        result.consensus[(cid, pn)] = (tpl, entries[0][1])
    counted = set()
    for c in calls:
        sig = (c.construct, c.part, c.out)
        if sig in counted:
            continue
        counted.add(sig)
        cnt = result.status.setdefault(c.construct, collections.Counter())
        if id(c) in outcome:
            st, why = outcome[id(c)]
        elif c.construct in bad:
            st, why = bad[c.construct]
        elif id(c) in instances:
            cnt["mapped"] += 1
            result.mapped_instances += 1
            continue
        else:
            st, why = "unmapped", "an instance of the same markup was read through another page"
        cnt[st] += 1
        result.reasons.setdefault(c.construct, why)
    result.look["constructs"] = dict((cid, result.look["constructs"][cid]) for cid in looks.CONSTRUCTS
                                     if cid in result.look["constructs"] and cid not in bad
                                     and result.status.get(cid, collections.Counter()).get("mapped", 0))
    if not result.mapped_instances:
        raise LookCommandError("these pages were not built from this repository's content: no instance of any construct "
                               "was found in them. Run derive in the repository whose content produced the pages, or "
                               "check which pages were read")
    for p in parsed:
        for el in walk(p.root):
            if el.tag in _STOP_UP or el.tag in ("script", "style", "title") or id(el) in state.explained[id(p)]:
                continue
            if any(isinstance(k, Tx) and re.search(r"[A-Za-z]", k.data) for k in el.kids):
                result.unexplained[el.tag] += 1
    return result


def literals(look):
    """[(construct, part, text)]: the words a look carries itself (text nodes, and attributes that hold text such as
    alt, title and aria-label), slots removed. These are the person's own words in a derived look."""
    out = []
    for cid, parts in sorted(look.constructs.items()):
        for pn, text in sorted(parts.items()):
            p = _Literals()
            p.feed(_SLOT.sub("", text))
            for t in p.found:
                out.append((cid, pn, t))
    return out


class _Literals(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        for name, v in attrs:
            if v and name not in _NOT_TEXT_ATTRS and not name.startswith("data-") and re.search(r"[A-Za-z]", v):
                self.found.append(v.strip())

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        if re.search(r"[A-Za-z]", data):
            self.found.append(_collapse(data).strip())


# ============================================================================================= the fetch (SSRF)
def host_allowed(address):
    """True when `address` (a resolved IP literal) is one a public site is served from. THE test seam: every
    connection, and every redirect, resolves its host and asks this about each answer. Loopback, link-local, private,
    shared (100.64.0.0/10), multicast, unspecified and reserved addresses are refused (R5N-15)."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global) and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
                                       or ip.is_private or ip.is_unspecified)


def _resolve(host, port):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchError("the address %s could not be found; check it, then run derive again" % host, "dns")
    if not infos:
        raise FetchError("the address %s could not be found; check it, then run derive again" % host, "dns")
    for info in infos:
        if not host_allowed(info[4][0]):
            raise FetchError("%s resolves to a private, loopback or link-local address, which derive will not "
                             "fetch; derive from your local build with --build" % host, "blocked")
    return infos[0]


def _pinned_socket(host, port, timeout):
    fam, typ, proto, _cn, addr = _resolve(host, port)
    sock = socket.socket(fam, typ, proto)
    sock.settimeout(timeout)
    sock.connect(addr)
    return sock


class _PinnedHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = _pinned_socket(self.host, self.port, self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = _pinned_socket(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTP, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPS, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, owned):
        self.owned = owned

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl))
        if target.scheme not in ("http", "https") or (target.hostname or "").lower() not in self.owned:
            raise FetchError("a page redirects away from the hosts you publish on; derive will not follow it. Derive "
                             "from your local build with --build", "redirect")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def make_opener(owned):
    """The one opener derive fetches with: no proxy, every connection pinned to a checked address, every redirect
    checked against the owned hosts first."""
    proxies = urllib.request.getproxies()
    if any(proxies.get(s) for s in ("http", "https")):
        raise FetchError("a proxy is configured: derive with --build <folder of built pages> (a connection made by a "
                         "proxy cannot be checked here)", "proxy")
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _HTTPHandler(), _HTTPSHandler(),
                                       _Redirects(frozenset(owned)))


def fetch(opener, url, owned, limit=None):
    """GET `url`. Returns (status, content type, bytes or None, final address). A body past `limit` (default
    FETCH_BYTES) is None. Raises FetchError when the address leaves the owned hosts or cannot be reached."""
    limit = FETCH_BYTES if limit is None else limit
    req = urllib.request.Request(url, headers={"User-Agent": "site-studio-derive", "Accept": "text/html"})
    try:
        resp = opener.open(req, timeout=FETCH_SECONDS)
    except urllib.error.HTTPError as e:
        with contextlib.closing(e):
            if (urllib.parse.urlsplit(e.geturl()).hostname or "").lower() not in owned:
                raise FetchError("a page was served from a host you do not publish on; derive stops. Derive from your "
                                 "local build with --build", "redirect")
            body = e.read(limit + 1) if 200 <= e.code < 300 else b""
            return e.code, (e.headers.get("Content-Type") or ""), (None if len(body) > limit else body), e.geturl()
    except FetchError:
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, FetchError):
            raise e.reason
        raise FetchError("%s could not be reached (%s); check your connection, or derive from your local build with "
                         "--build" % (urllib.parse.urlsplit(url).hostname, e.reason.__class__.__name__), "network")
    except (OSError, http.client.HTTPException) as e:
        raise FetchError("%s could not be reached (%s); check your connection, or derive from your local build with "
                         "--build" % (urllib.parse.urlsplit(url).hostname, e.__class__.__name__), "network")
    with contextlib.closing(resp):
        final = resp.geturl()
        if (urllib.parse.urlsplit(final).hostname or "").lower() not in owned:
            raise FetchError("a page was served from a host you do not publish on; derive stops. Derive from your "
                             "local build with --build", "redirect")
        body = resp.read(limit + 1)
        return resp.status, (resp.headers.get("Content-Type") or ""), (None if len(body) > limit else body), final


class _Links(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def _page_key(base_path, path):
    """The key a fetched page is filed under: its path under the site's base, `index.html` for a folder."""
    rel = path[len(base_path):] if path.startswith(base_path) else path.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return rel


def _is_html_path(path):
    last = posixpath.basename(path)
    return path.endswith("/") or "." not in last or last.lower().endswith((".html", ".htm"))


def fetch_pages(start_url, owned, wanted_keys, out):
    """Read the published pages: the start page, then each page the content built (`wanted_keys`, output paths), then
    pages linked from those, to FETCH_PAGES. Returns ({key: html}, [keys never read]). Raises FetchError for the
    refusals R5.4(e) names."""
    opener = make_opener(owned)
    start = urllib.parse.urlsplit(start_url)
    if start.scheme not in ("http", "https") or not start.hostname:
        raise FetchError("%s is not a web address; give an https address, or derive from your local build with --build"
                         % "that" , "url")
    base_path = start.path if start.path.endswith("/") else posixpath.dirname(start.path.rstrip("/")) + "/"
    origin = "%s://%s" % (start.scheme, start.netloc)
    # robots.txt first: 2xx honoured, 404 allows all, anything else refuses
    rstatus, _rt, rbody, _rf = fetch(opener, origin + "/robots.txt", owned, 512 * 1024)
    rules = urllib.robotparser.RobotFileParser()
    if rstatus == 404:
        rules.parse([])
    elif 200 <= rstatus < 300 and rbody is not None:
        rules.parse(rbody.decode("utf-8", "replace").splitlines())
    else:
        raise FetchError("robots.txt answered %s: nothing was fetched; derive from your local build with --build"
                         % rstatus, "robots")

    def allowed(url):
        return rules.can_fetch(ROBOTS_TOKEN, url)

    def url_of(key):
        rel = key[:-len("index.html")] if key.endswith("index.html") else key
        return origin + urllib.parse.urljoin(base_path, rel)

    pages, queue, queued = {}, [], set()
    sstatus, stype, sbody, sfinal = fetch(opener, start_url, owned)
    if not (200 <= sstatus < 300) or "text/html" not in stype.lower() or sbody is None:
        raise FetchError("the start page answered %s (%s), not a page of HTML; check the address, or derive from your "
                         "local build with --build" % (sstatus, (stype or "no type").split(";")[0] or "no type"), "start")
    if not allowed(sfinal):
        raise FetchError("robots.txt asks robots not to read the start page: nothing was fetched; derive from your "
                         "local build with --build", "robots")
    pages[_page_key(base_path, urllib.parse.urlsplit(sfinal).path)] = sbody.decode("utf-8", "replace")
    queued.add(sfinal)
    disallowed = [k for k in wanted_keys if not allowed(url_of(k))]
    if disallowed:
        raise FetchError("robots.txt asks robots not to read %d of the pages your content built: nothing more was "
                         "fetched; derive from your local build with --build" % len(disallowed), "robots")
    for k in wanted_keys:
        u = url_of(k)
        if u not in queued:
            queued.add(u)
            queue.append(u)
    i = 0
    while i < len(queue) and len(pages) < FETCH_PAGES:
        url = queue[i]
        i += 1
        st, ty, body, final = fetch(opener, url, owned)
        if not (200 <= st < 300) or "text/html" not in ty.lower() or body is None:
            continue
        parts = urllib.parse.urlsplit(final)
        key = _page_key(base_path, parts.path)
        if key in pages:
            continue
        text = body.decode("utf-8", "replace")
        pages[key] = text
        lp = _Links()
        lp.feed(text)
        for href in lp.hrefs:
            t = urllib.parse.urlsplit(urllib.parse.urljoin(final, href))
            if t.scheme != parts.scheme or (t.hostname or "").lower() != (parts.hostname or "").lower():
                continue
            if not t.path.startswith(base_path) or not _is_html_path(t.path):
                continue
            u = urllib.parse.urlunsplit((t.scheme, t.netloc, t.path, "", ""))
            if u not in queued and allowed(u):
                queued.add(u)
                queue.append(u)
    never = [k for k in wanted_keys if k not in pages]
    return pages, never


# =================================================================================================== ownership
class Env(object):
    """The seams a test replaces; main() builds the real one."""

    def __init__(self, out=None, get=None, isatty=None, ask=None, fetch_pages=None):
        self.out = out or sys.stdout
        self.get = get or pages_check._get
        self.isatty = isatty or (lambda: sys.stdin.isatty())
        self.ask = ask or (lambda prompt: input(prompt))
        self.fetch_pages = fetch_pages or globals()["fetch_pages"]

    def say(self, text=""):
        print(text, file=self.out)


def owned_host_command(repo, host, url=None):
    """The command the person runs in their own terminal to confirm a host: every part absolute and quoted, built
    fresh from the running install (R5N-16), never stored."""
    cmd = [os.path.abspath(sys.executable), os.path.abspath(__file__), "derive", "--owned-host", host]
    if url:
        cmd += ["--url", url]
    return "cd %s && %s" % (shlex.quote(os.path.abspath(repo)), " ".join(shlex.quote(c) for c in cmd))


def _gh_class(message):
    low = message.lower()
    if "not installed" in low:
        return "missing"
    if "not logged in" in low:
        return "auth"
    return "network"


def pages_host_set(public_repo, env):
    """(the person's Pages hosts, the Pages address) for `publicRepo`, read with gh. Each failure is its own refusal."""
    if not public_repo:
        raise LookCommandError("site.json has no publicRepo, so there is no published site to read; run /site-studio:setup "
                               "to set it, or derive from your local build with --build <folder of built pages>")
    try:
        resp = env.get("repos/%s/pages" % public_repo)
    except pages_check.GhError as e:
        kind = _gh_class(str(e))
        if kind == "missing":
            raise LookCommandError("the GitHub CLI (gh) is not installed, so your Pages address cannot be read; install "
                                   "it from https://cli.github.com, or derive from your local build with --build", )
        if kind == "auth":
            raise LookCommandError("gh is not logged in, so your Pages address cannot be read; run `gh auth login`, then "
                                   "run derive again")
        raise LookCommandError("GitHub could not be reached (error class: network); check your connection, then run "
                               "derive again, or derive from your local build with --build")
    if resp.status == 404:
        raise LookCommandError("GitHub Pages is not enabled for %s, so there is no published site to read; turn it on "
                               "under the repository's Settings, then Pages, or derive from your local build with "
                               "--build" % public_repo)
    if resp.status != 200 or not isinstance(resp.data, dict):
        raise LookCommandError("GitHub could not be read (error class: HTTP %s); try again later, or derive from your "
                               "local build with --build" % resp.status)
    html_url = resp.data.get("html_url") if isinstance(resp.data.get("html_url"), str) else ""
    cname = resp.data.get("cname") if isinstance(resp.data.get("cname"), str) else ""
    hosts = set()
    for u in (html_url, cname):
        h = (urllib.parse.urlsplit(u if "//" in u else "//" + u).hostname or "").lower() if u else ""
        if h:
            hosts.add(h)
    return hosts, html_url


def settle_ownership(url_host, hosts_from_pages, owned_flag, repo, url, env):
    """The owned host set after the ownership question for `url_host`, and whether the person's word was needed.
    Returns (owned set, on_word)."""
    if url_host in hosts_from_pages:
        return set(hosts_from_pages), False
    if not owned_flag:
        raise LookCommandError("deriving a look from a site you do not publish is not supported. A site you publish "
                               "from another host: confirm it in your own terminal with --owned-host %s" % url_host)
    if owned_flag.lower() != url_host:
        raise LookCommandError("--owned-host names %s, but the address is on %s; name the host the pages come from"
                               % (owned_flag, url_host))
    if not env.isatty():
        raise LookCommandError("this needs you at your own terminal to confirm that you publish %s. Run this in your own "
                               "terminal: %s" % (url_host, owned_host_command(repo, url_host, url)))
    typed = (env.ask("Type the host %s to confirm that you publish it: " % url_host) or "").strip().lower()
    if typed != url_host:
        raise LookCommandError("that is not the host; nothing was fetched. Run derive again and type %s" % url_host)
    return set(hosts_from_pages) | {url_host}, True


# ========================================================================================== reading the pages
def read_build_dir(path):
    """{key: html} for every page under `path` (a folder of built pages). A page larger than the fetch cap is skipped."""
    if not os.path.isdir(path):
        raise LookCommandError("%s is not a folder; give the folder your site was built into" % path)
    pages = {}
    for d, _dirs, names in os.walk(path):
        for n in sorted(names):
            if n.lower().endswith((".html", ".htm")):
                full = os.path.join(d, n)
                if os.path.getsize(full) > FETCH_BYTES:
                    continue
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                with open(full, "rb") as fh:
                    pages[rel] = fh.read().decode("utf-8", "replace")
    if not pages:
        raise LookCommandError("%s holds no HTML page; give the folder your site was built into" % path)
    return pages


def _load_tree(repo, working=False, derive=False):
    """(repository root, {path: bytes} of site/ and content/, parsed site.json). At HEAD, the commit that was published
    and the one a writer checks is clean; with `working`, the files as they are on disk now (what `list` and `check`
    describe, so a look just copied by `use` is there before it is committed)."""
    top = _toplevel(repo)
    try:
        files = build._disk_files(top) if working else build._commit_files(top)
    except build.BuildError as e:
        raise LookCommandError("this repository holds no committed site (%s); run this inside a site-studio site's "
                               "repository, after its first commit" % e)
    if "site/site.json" not in files:
        raise LookCommandError(("derive needs the content that built the pages; adopt that site first" if derive else
                                "this folder holds no site-studio site; adopt that site first, or run this in its "
                                "repository") + " (there is no site/site.json here)")
    try:
        cfg = siteconfig.parse_text(files["site/site.json"].decode("utf-8", "replace"))
    except siteconfig.SiteConfigError as e:
        raise LookCommandError("site/site.json cannot be read (%s); a look is made for a site whose site.json reads, "
                               "so fix it or adopt that site first" % e)
    return top, files, cfg


def _toplevel(repo):
    import subprocess
    try:
        p = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LookCommandError("could not run git (%s); install git, then try again" % e.__class__.__name__)
    if p.returncode != 0:
        raise LookCommandError("%s is not inside a git repo; run this in the site's repository" % repo)
    return os.path.realpath(p.stdout.decode("utf-8", "replace").strip())


def derive_command(repo, build_dir=None, url=None, owned_host=None, name=DEFAULT_NAME, replace=False, env=None):
    """The `derive` command. Returns the exit code; writes the look file only on success."""
    env = env or Env()
    if not _SLUG.match(name or ""):
        raise LookCommandError("the look name %r must be lower-case letters, digits and hyphens" % name)
    top, files, cfg = _load_tree(repo, derive=True)
    target = LOOKS_REL + name + ".json"
    full = os.path.join(top, *target.split("/"))
    never = []
    recorded = record(files)
    if build_dir:
        pages = read_build_dir(build_dir)
    else:
        hosts, html_url = set(), ""
        try:
            hosts, html_url = pages_host_set(cfg.publicRepo, env)
        except LookCommandError:
            if not (url and owned_host):
                raise
        start = url or html_url
        if not start:
            raise LookCommandError("there is no address to read; give one with --url, or derive from your local build "
                                   "with --build <folder of built pages>")
        host = (urllib.parse.urlsplit(start).hostname or "").lower()
        owned, on_word = settle_ownership(host, hosts, owned_host, top, url, env)
        if on_word:
            env.say(NOT_VERIFIED)
        pages, never = env.fetch_pages(start, owned, sorted(recorded[1]), env.out)
    d = derive_look(files, pages, never, recorded)
    text = d.text
    parsed = looks.parse(text, target)
    lits = literals(parsed)
    if os.path.exists(full):
        with open(full, "rb") as fh:
            same = fh.read() == text.encode("utf-8")
        if not same and not replace:
            raise LookCommandError("%s already exists with other content; derive writes nothing over it. Pick another "
                                   "--name, or add --replace to overwrite it" % target)
    for line in d.lines():
        env.say(line)
    if never:
        env.say("%d page(s) the content built were never read (cap of %d pages): those instances are `not reached`"
                % (len(never), FETCH_PAGES))
    addresses.write_bytes(top, target, text.encode("utf-8"))
    env.say("wrote %s (%d construct(s); structure and your own literal text)" % (target, len(parsed.constructs)))
    if lits:
        env.say("literal words this look carries (your own text, kept as the page had it):")
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
    env.say("nothing is committed. Use it with: look.py use %s" % target)
    return EXIT_OK


# ======================================================================================== list, use and check
def shipped_ids():
    try:
        names = sorted(n[:-5] for n in os.listdir(SHIPPED_DIR) if n.endswith(".json"))
    except OSError:
        names = []
    return names


def _read_look(path, where, shipped=False):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return raw, looks.parse(raw.decode("utf-8"), where, shipped=shipped)
    except (OSError, UnicodeDecodeError) as e:
        raise LookCommandError("%s cannot be read (%s); check the path" % (where, e.__class__.__name__))
    except looks.LookError as e:
        raise LookCommandError("%s is refused:\n%s\nfix: %s" % (where, e, e.fix or "fix the lines above"))


def list_command(repo, env=None):
    env = env or Env()
    env.say("looks site-studio ships (copy one into your site with `look.py use <id>`):")
    for sid in shipped_ids():
        _raw, lk = _read_look(os.path.join(SHIPPED_DIR, sid + ".json"), "templates/looks/%s.json" % sid, shipped=True)
        env.say("  %s  %d construct(s), %d literal word(s), %d stylesheet(s)"
                % (sid, len(lk.constructs), len(literals(lk)), len(lk.stylesheets)))
    try:
        top, files, cfg = _load_tree(repo, working=True)
    except LookCommandError:
        env.say("this folder is not a site-studio site, so no site looks are listed")
        return EXIT_OK
    env.say("looks this site carries (%s):" % LOOKS_REL)
    mine = sorted(p for p in files if p.startswith(LOOKS_REL) and p.endswith(".json"))
    if not mine:
        env.say("  none")
    for p in mine:
        mark = "  (in use)" if cfg.look == p else ""
        try:
            lk = looks.parse(files[p].decode("utf-8"), p)
            env.say("  %s  %d construct(s)%s" % (p, len(lk.constructs), mark))
        except (looks.LookError, UnicodeDecodeError):
            env.say("  %s  refused by the look rules; run `look.py check`%s" % (p, mark))
    env.say("the site uses: %s" % (cfg.look or "the plugin's own look (no `look` key in site.json)"))
    return EXIT_OK


def _find_source(source):
    """(kind, look path, display, slug) for a `use` argument."""
    if source in shipped_ids():
        return "shipped", os.path.join(SHIPPED_DIR, source + ".json"), "templates/looks/%s.json" % source, source
    if os.sep in source or "/" in source or source.endswith(".json") or os.path.exists(source):
        path = os.path.abspath(source)
        slug = os.path.basename(path)[:-5] if path.endswith(".json") else os.path.basename(path)
        if not os.path.isfile(path):
            raise LookCommandError("%s is not a file; give the path of a look file, or one of: %s"
                                   % (source, ", ".join(shipped_ids())))
        if not _SLUG.match(slug):
            raise LookCommandError("the look file name %r must be lower-case letters, digits and hyphens before .json; "
                                   "copy it to such a name first" % os.path.basename(path))
        return "path", path, os.path.basename(path), slug
    raise LookCommandError("%r is not a look site-studio ships (%s) and not a file; give one of them, or the path of a "
                           "look file" % (source, ", ".join(shipped_ids())))


def _repo_root_of(look_path):
    """The repository root a look file at `<root>/site/looks/<name>.json` belongs to, else None."""
    d = os.path.dirname(look_path)
    if os.path.basename(d) == "looks" and os.path.basename(os.path.dirname(d)) == "site":
        return os.path.dirname(os.path.dirname(d))
    return None


def use_command(repo, source, accept_literals=False, env=None):
    env = env or Env()
    top, files, cfg = _load_tree(repo)
    kind, path, shown, slug = _find_source(source)
    raw, lk = _read_look(path, shown, shipped=(kind == "shipped"))
    lits = literals(lk)
    if lits and not accept_literals:
        env.say("%s carries %d literal word(s) of its own, which would appear on your pages:" % (shown, len(lits)))
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
        raise LookCommandError("nothing was copied. Read the words above, then run `use` again with --accept-literals "
                               "if you are happy with them")
    _prewrite(cfg, files)
    writes = {}
    target = LOOKS_REL + slug + ".json"
    writes[target] = raw
    # a look derived in this repository and not yet committed is its own source: it is not "uncommitted work"
    own = os.path.realpath(path) == os.path.realpath(os.path.join(top, *target.split("/")))
    dirty = [ln for ln in addresses._git_status(top) if not (own and ln[3:].strip() == target)]
    if dirty:
        raise LookCommandError("the tree has uncommitted changes in site/, content/ or .site-studio/ (%s); commit or "
                               "discard them first, then try again" % dirty[0].strip()[:80])
    src_root = None if kind == "shipped" else _repo_root_of(path)
    for rel in lk.stylesheets:
        if kind == "shipped":
            src = os.path.join(SHIPPED_DIR, posixpath.basename(rel))
            try:
                with open(src, "rb") as fh:
                    data = fh.read()
            except OSError:
                raise LookCommandError("%s names the stylesheet %s, which site-studio does not ship; reinstall the "
                                       "plugin" % (shown, rel))
        else:
            if src_root is None:
                raise LookCommandError("%s names the stylesheet %s, so it must be copied from a repository: use the "
                                       "file at <repository>/site/looks/%s.json" % (shown, rel, slug))
            try:
                looks.check_stylesheet_file(src_root, rel, shown)
                with open(os.path.join(src_root, *rel.split("/")), "rb") as fh:
                    data = fh.read()
            except looks.LookError as e:
                raise LookCommandError("%s\nfix: %s" % (e, e.fix))
        try:
            looks.scan_stylesheet(data.decode("utf-8"), rel)
        except (looks.LookError, UnicodeDecodeError) as e:
            raise LookCommandError("the stylesheet %s is refused: %s; fix the file, or leave it out of the look's "
                                   "stylesheets" % (rel, e))
        writes[rel] = data
    new = dict(files)
    for rel, data in writes.items():
        if rel in files and files[rel] != data:
            raise LookCommandError("%s already exists with other content; nothing was copied over it. Rename or remove "
                                   "that file if you want this look, or pick the other look's name" % rel)
        new[rel] = data
    d = cfg.to_dict()
    d["look"] = target
    d["schema"] = max(4, cfg.schema)          # a `look` key is a schema-4 key; the writer then holds the schema the tree needs
    site_json = siteconfig.canonical_text(siteconfig.parse_data(d), new, C.interpretation_reasons(new), at_least=4)
    new["site/site.json"] = site_json.encode("utf-8")
    acc = build.accept(dict((k, v) for k, v in new.items() if k.startswith(("site/", "content/"))))
    if acc.problems:
        raise LookCommandError("the site would not build with this look (%s); nothing was changed. Fix what the build "
                               "names, or choose another look" % "; ".join(p.line() for p in acc.problems[:2]))
    wrote, placed = [], []
    for rel in sorted(new):
        if files.get(rel) == new[rel]:
            if rel in writes:
                placed.append(rel)
            continue
        full = os.path.join(top, *rel.split("/"))
        if os.path.isfile(full):
            with open(full, "rb") as fh:
                if fh.read() == new[rel]:
                    placed.append(rel)
                    continue
        addresses.write_bytes(top, rel, new[rel])
        wrote.append(rel)
    for rel in placed:
        env.say("already in place: %s" % rel)
    for rel in wrote:
        env.say("wrote %s" % rel)
    env.say("site.json: look is %s" % target)
    env.say("nothing is committed: stage these paths with git add, then commit: %s" % " ".join(wrote + placed))
    return EXIT_OK


def _prewrite(cfg, files):
    """A `look` key is a schema-4 key, reached through schema 3 (the raise-schema pre-write check, R2-3)."""
    if cfg.schema < 3:
        raise LookCommandError("this site is at schema %d, and a look needs schema 4, which is reached through schema 3: "
                               "run `build.py raise-schema` (it lists what changes before it writes), commit, then try "
                               "again" % cfg.schema)
    probs = siteconfig.part_collision_problems(files)
    if probs:
        raise LookCommandError("%s; a site with that part cannot be raised to schema 4, so rename it, then run `build.py "
                               "raise-schema` and try again" % probs[0].line())


def check_command(repo, env=None):
    env = env or Env()
    top, files, cfg = _load_tree(repo, working=True)
    if cfg.look is None:
        env.say("site.json names no look: the plugin's own look renders every construct")
        lk = looks.default_look()
        where = "the plugin's own look"
    else:
        raw = files.get(cfg.look)
        if raw is None:
            raise LookCommandError("site.json names the look %s, which is not committed; commit the file, or remove the "
                                   "look key" % cfg.look)
        try:
            lk = looks.parse(raw.decode("utf-8"), cfg.look)
        except (looks.LookError, UnicodeDecodeError) as e:
            raise LookCommandError("%s is refused:\n%s\nfix: %s" % (cfg.look, e, getattr(e, "fix", None) or "fix the lines above"))
        where = cfg.look
        for rel in lk.stylesheets:
            if rel not in files:
                raise LookCommandError("%s names the stylesheet %s, which is not committed; add the file, or remove it "
                                       "from the look" % (cfg.look, rel))
    env.say("look: %s (%d construct(s) of %d)" % (where, len(lk.constructs), len(looks.CONSTRUCTS)))
    for cid in lk.omitted():
        env.say("the look has no markup for %s; plugin markup is used" % cid)
    for cid, pn in looks.live_players(lk):
        env.say("%s.%s carries a live player: a visitor's browser loads a third party when the page loads" % (cid, pn))
    lits = literals(lk)
    if lits:
        env.say("%d literal word(s) in this look:" % len(lits))
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
    return EXIT_OK


# ==================================================================================================== the command
def main(argv=None):
    rc = platform_check.windows_refusal_rc("look.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="look.py", allow_abbrev=False,
                                 description="Choose, copy, check and derive a site's look.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    for name in ("list", "check"):
        p = sub.add_parser(name, allow_abbrev=False)
        p.add_argument("--repo", default=".", help="the site's repository (default: the current folder)")
    p = sub.add_parser("use", allow_abbrev=False)
    p.add_argument("look", metavar="ID_OR_PATH")
    p.add_argument("--accept-literals", action="store_true", help="copy a look that carries literal words")
    p.add_argument("--repo", default=".")
    p = sub.add_parser("derive", allow_abbrev=False)
    p.add_argument("--build", metavar="DIR", help="read built pages from this folder (no network)")
    p.add_argument("--url", help="start page of the published site (default: your Pages address)")
    p.add_argument("--owned-host", metavar="HOST", help="a host you publish on that is not your Pages address")
    p.add_argument("--name", default=DEFAULT_NAME, help="the look's name (default: %s)" % DEFAULT_NAME)
    p.add_argument("--replace", action="store_true", help="overwrite a look of the same name")
    p.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    env = Env()
    try:
        if args.cmd == "list":
            return list_command(args.repo, env)
        if args.cmd == "check":
            return check_command(args.repo, env)
        if args.cmd == "use":
            return use_command(args.repo, args.look, args.accept_literals, env)
        return derive_command(args.repo, args.build, args.url, args.owned_host, args.name, args.replace, env)
    except (LookCommandError, build.BuildError, addresses.AddressError, siteconfig.SiteConfigError,
            C.ContentError, looks.LookError) as e:
        print("look refused: %s" % e)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
