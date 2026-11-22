"""adoption.facts -- what a visitor meets on one page, as a multiset of FACTS (design-adopt-parity-2 section 5.1, rule M4).

Part of the `adoption` package behind the entry point `adopt.py`. `adoption.scoring` judges a setting by the facts in its own scope
(section 5.3); this module only reads a page. It reads over `lookfiles.pagedom`'s parser (no second HTML parser) and resolves an
address with `parityscan.sameresource.resolve` (rule U-a's reading: `./` and `../work/` from `work/index.html` are one address).

A FACT is a tuple `(kind, value, area, in_heading, piece)`. The unit of each kind, exactly (section 5.1's table):

    word     one maximal run of letters and digits inside ONE text node, NFC, case kept. Punctuation and spacing are not facts,
             and no text is joined across an element boundary
    heading  an `h1` to `h6`: (its level, its words in order), so a heading is also matched whole
    img      an `<img>`'s `alt`, the whole value, squashed (an empty or missing `alt` is the fact "no name", the value "")
    imgfile  the address an `<img>` loads (`src`, and each candidate of `srcset`), resolved from the page
    link     the target of an `<a href>`, resolved from the page; a `mailto:` or outside address as written
    frame    an `<iframe>`'s (`title` squashed, host and path it loads)
    current  (an `aria-current` value, the resolved target of the link that carries it)
    title    the `<title>` text, whole and squashed

What is NEVER a fact: anything inside `script`, `style`, `template`, `noscript` or `head` (but `title`); a comment (pagedom drops
them); a subtree whose element carries `hidden`; the inside of an `<svg>`. Text hidden by a stylesheet cannot be known from markup and
is read as shown, in both builds alike.

The three MARKS of a fact: its AREA (`chrome` inside `nav`, or inside a `header` or `footer` that is not inside `main`, `article`,
`section` or `aside`; else `content`: 0.5.0's rule, `scoring._Reading.live`); whether it is IN A HEADING; and its PIECE: a piece link
is an `<a>` in `content` whose resolved target is the address of a piece page (`<portfolio>/<slug>/`, never matched by its text); the
piece's region on the page is, for each of its links, the largest element around the link, below `main` and `body`, that holds no
link to another piece. An old link the conversion's redirects move to a piece counts as that piece (`moved`).

A page the parser cannot read (bytes that are not UTF-8; a parse that ends inside `script`, `style`, `title` or `textarea`, which
swallowed the rest of the page) is `Unreadable`, with what was wrong: its facts are never counted (scoring leaves the page out with
`NOT CHECKED`).

ABOVE THE TITLE (step 8c): `Page.above_title` holds the facts met before the page's first `h1` in `content`, in document order: on
a piece page, the region a back link to the portfolio lives in (`backLink.<p>`'s own scope, `scoring.scopes`). A page with no
such `h1` has no title to be above, and every fact is above it. `links_above_title` reads the links of that region (step 8d), so
`backLink.<p>`'s candidate is read where it is judged: never the site menu's link, which is `chrome`.

    read(path, data, pieces=(), site_path=None, moved=None) -> Page | Unreadable
    piece_addresses(snap) -> {"<portfolio>/<slug>"}            the piece pages of a converted tree
    frame_for(snap, data, local) -> Frame                       each build's path and the redirects, for `choose` (step 8b, F8)
    links_above_title(text) -> [(href, text or None)] | None    the links in `content` above the first `h1` there (step 8d)
"""

import collections
import json
import re
import unicodedata
import urllib.parse

from configschema import model as configmodel
from lookfiles import pagedom
from parityscan import sameresource

KINDS = ("word", "heading", "img", "imgfile", "link", "frame", "current", "title", "file")   # `file`: a published file (scoring's)
_NEVER = frozenset(("script", "style", "template", "noscript", "head"))
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_SECTIONING = frozenset(("main", "article", "section", "aside"))
_SWALLOW = ("script", "style", "title", "textarea")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_WS = re.compile(r"\s+")
_STOP = frozenset(("main", "body", "html", "#root"))

Fact = collections.namedtuple("Fact", "kind value area in_heading piece")


class Unreadable(object):
    """A page whose facts cannot be counted, and what was wrong (`what`)."""

    def __init__(self, path, what):
        self.path, self.what = path, what

    def line(self):
        return "NOT CHECKED: %s could not be read (%s)" % (self.path, self.what)


class Page(object):
    """One page's facts (`facts`, a Counter of `Fact`), the pieces it links (`linked`, a set of `<portfolio>/<slug>`), and the
    facts met before its first `h1` in `content` (`above_title`, a Counter: the module docstring, ABOVE THE TITLE)."""

    def __init__(self, path, facts, linked, above_title=None):
        self.path, self.facts, self.linked = path, facts, linked
        self.above_title = collections.Counter(facts) if above_title is None else above_title


class _Tally(object):
    """The facts of one reading as `_walk` meets them: every fact (`facts`), and those met before the first `h1` in `content`
    (`above`; `titled` turns True at that `h1`, which is itself the title and not above it)."""

    def __init__(self):
        self.facts, self.above, self.titled = collections.Counter(), collections.Counter(), False

    def add(self, fact):
        self.facts[fact] += 1
        if not self.titled:
            self.above[fact] += 1


def squash(text):
    return " ".join((text or "").split())


def words(text):
    """The `word` facts of one text node: maximal runs of letters and digits, NFC, case kept."""
    return _WORD.findall(unicodedata.normalize("NFC", text or ""))


def piece_addresses(snap):
    """{`<portfolio>/<slug>`}: the piece pages of a converted tree (`content/<portfolio>/<slug>/index.md`, under a portfolio that
    has a `page.md`): the address a piece is published at under both builders (a template piece's folder is its address)."""
    ports = set(p.split("/")[1] for p in snap if p.count("/") == 2 and p.startswith("content/") and p.endswith("/page.md"))
    return set("%s/%s" % tuple(p.split("/")[1:3]) for p in snap
               if p.count("/") == 3 and p.startswith("content/") and p.endswith("/index.md") and p.split("/")[1] in ports
               and not p.split("/")[1].startswith("_") and not p.split("/")[2].startswith("_"))


def target(page, href, site_path=None):
    """The address an `href` or `src` names, read from the output page `page`: a site path in the build with `index.html` dropped
    (`work/kiln-house/`, `` for the home), the query and fragment kept (`?q`, `#x`); an address that is not the site's (another
    host, `mailto:`) as written; an address outside the build's path as `outside:<as written>`."""
    r = sameresource.resolve(page, href, site_path)
    if r is None:
        return (href or "").strip()
    if r is sameresource.OUTSIDE:
        return "outside:" + (href or "").strip()
    path, query, frag = r
    path = re.sub(r"(?:^|(?<=/))index\.html$", "", path)
    return path + ("?" + query if query else "") + ("#" + frag if frag else "")


def _piece_of(addr, pieces, moved):
    key = addr.split("?", 1)[0].split("#", 1)[0].strip("/")
    if key in pieces:
        return key
    return (moved or {}).get(key)


def _attrs(el):
    return dict((k, v) for k, v in el.attrs)


def _swallowed(text):
    """What a parse that ends inside a raw-text element swallowed, or None. html.parser reads `script` and `style` as CDATA to their end
    tag; `title` and `textarea` (escapable raw text) are left open on the parser's stack."""
    p = pagedom._DomBuilder(text)
    p.feed(text)
    p.close()
    if getattr(p, "cdata_elem", None):
        return "the page ends inside <%s>" % p.cdata_elem
    for el in p.stack[1:]:
        if el.tag in _SWALLOW:
            return "the page ends inside <%s>" % el.tag
    return None


def read(path, data, pieces=(), site_path=None, moved=None):
    """The facts of the page at output path `path` (its bytes `data`), or `Unreadable`. `pieces` is the set of piece addresses
    (`piece_addresses`), `site_path` the path the build is served under (`preview.base_path`'s form, None the root), `moved` {old
    address: piece} for the old links a recorded redirect moves to a piece."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        return Unreadable(path, "its bytes are not UTF-8 at byte %d" % e.start)
    bad = _swallowed(text)
    if bad:
        return Unreadable(path, bad)
    root = pagedom.parse_dom(text)
    pieces = set(pieces or ())
    region = {}                         # id(element) -> piece: the largest element around a piece link holding no other piece's link
    links = []                          # (element, piece) for every piece link in content
    _collect_links(root, path, pieces, site_path, moved, links, [])
    for el, piece in links:
        top, cur = el, el.parent
        while cur is not None and cur.tag not in _STOP:
            if any(p != piece for p in _pieces_under(cur, path, pieces, site_path, moved)):
                break
            top, cur = cur, cur.parent
        region[id(top)] = piece
    tally = _Tally()
    _walk(root, path, site_path, region, tally, area="content", heading=False, piece=None, stack=())
    return Page(path, tally.facts, set(p for _e, p in links), tally.above)


def _hidden(el):
    return el.tag in _NEVER or el.tag == "svg" or any(k == "hidden" for k, _v in el.attrs)


def _chrome(stack):
    """0.5.0's rule: inside `nav`, or a `header` or `footer` that is not inside `main`, `article`, `section` or `aside`."""
    for i, tag in enumerate(stack):
        if tag == "nav":
            return True
        if tag in ("header", "footer") and not any(t in _SECTIONING for t in stack[:i]):
            return True
    return False


def _collect_links(el, page, pieces, site_path, moved, out, stack):
    for k in el.kids:
        if not isinstance(k, pagedom.El) or _hidden(k):
            continue
        st = stack + [k.tag]
        if k.tag == "a" and not _chrome(st):
            href = _attrs(k).get("href")
            if href is not None:
                piece = _piece_of(target(page, href, site_path), pieces, moved)
                if piece:
                    out.append((k, piece))
        _collect_links(k, page, pieces, site_path, moved, out, st)


def _pieces_under(el, page, pieces, site_path, moved):
    out = set()
    for e in pagedom.walk(el):
        if isinstance(e, pagedom.El) and e.tag == "a" and not _hidden(e):
            href = _attrs(e).get("href")
            if href is not None:
                piece = _piece_of(target(page, href, site_path), pieces, moved)
                if piece:
                    out.add(piece)
    return out


def _walk(el, page, site_path, region, facts, area, heading, piece, stack):
    """`facts` is the reading's `_Tally`."""
    for k in el.kids:
        if isinstance(k, pagedom.Tx):
            for w in words(k.data):
                facts.add(Fact("word", w, area, heading, piece))
            continue
        if not isinstance(k, pagedom.El):
            continue
        if k.tag == "head":
            for t in pagedom.walk(k):
                if isinstance(t, pagedom.El) and t.tag == "title":
                    facts.add(Fact("title", squash(pagedom.text_of(t)), "chrome", False, None))
            continue
        if _hidden(k):
            continue
        if k.tag == "title":                    # a `<title>` the parser put in the body
            facts.add(Fact("title", squash(pagedom.text_of(k)), "chrome", False, None))
            continue
        st = stack + (k.tag,)
        a = "chrome" if _chrome(list(st)) else "content"
        p = region.get(id(k), piece) if a == "content" else piece
        h = heading or k.tag in _HEADINGS
        at = _attrs(k)
        if k.tag == "h1" and a == "content":
            facts.titled = True                 # the page's title: neither it nor what follows it is above it
        if k.tag in _HEADINGS:
            ws = tuple(w for t in _texts(k) for w in words(t))
            facts.add(Fact("heading", (int(k.tag[1]), ws), a, True, p))
        if k.tag == "img":
            facts.add(Fact("img", squash(at.get("alt") or ""), a, h, p))
            for src in ([at["src"]] if at.get("src") else []) + [u for u, _d in sameresource.srcset_candidates(at.get("srcset"))]:
                facts.add(Fact("imgfile", target(page, src, site_path), a, h, p))
        if k.tag == "a" and at.get("href") is not None:
            facts.add(Fact("link", target(page, at["href"], site_path), a, h, p))
        if k.tag == "iframe":
            s = urllib.parse.urlsplit((at.get("src") or "").strip())
            facts.add(Fact("frame", (squash(at.get("title") or ""), s.netloc.lower() + s.path), a, h, p))
        if at.get("aria-current") is not None:
            ref = target(page, at["href"], site_path) if k.tag == "a" and at.get("href") is not None else ""
            facts.add(Fact("current", (at["aria-current"], ref), a, h, p))
        _walk(k, page, site_path, region, facts, a, h, p, st)


def _texts(el):
    """The text nodes under `el` that a visitor meets (not under a hidden, raw or drawing element), in order."""
    for k in el.kids:
        if isinstance(k, pagedom.Tx):
            yield k.data
        elif isinstance(k, pagedom.El) and not _hidden(k):
            for t in _texts(k):
                yield t


def links_above_title(text):
    """The links a visitor meets in `content` before the page's first `h1` there (ABOVE THE TITLE), in document order, as (`href`
    as written, the link's text squashed, or None when the link holds an element): the region `backLink.<p>` is judged in, and the
    one its candidate is read from (`candidates.back_link_texts`, step 8d). A link in `chrome` (the site menu) is never one. None
    when the page has no `h1` in `content` (no title to be above) or cannot be read."""
    if _swallowed(text):
        return None
    out = []

    def walk(el, stack):
        for k in el.kids:
            if not isinstance(k, pagedom.El) or k.tag in ("head", "title") or _hidden(k):
                continue
            st = stack + [k.tag]
            content = not _chrome(st)
            if k.tag == "h1" and content:
                return True
            href = _attrs(k).get("href") if k.tag == "a" and content else None
            if href is not None:
                plain = all(isinstance(t, pagedom.Tx) for t in k.kids)
                out.append((href, squash("".join(t.data for t in k.kids)) if plain else None))
            if walk(k, st):
                return True
        return False
    return out if walk(pagedom.parse_dom(text), []) else None


def pages_of(files, pieces=(), site_path=None, moved=None, cache=None):
    """{path: Page or Unreadable} for every HTML page of a build ({path: bytes}); `cache` ({(path, bytes): reading}) is shared
    across the candidates of one `choose`, so a page both builds print the same is read once."""
    out = {}
    how = (site_path, tuple(sorted((moved or {}).items())))          # one page read under two frames is two readings
    for path in sorted(files):
        if not path.lower().endswith((".html", ".htm")):
            continue
        key = (path, files[path], how)
        if cache is not None and key in cache:
            out[path] = cache[key]
            continue
        out[path] = read(path, files[path], pieces, site_path, moved)
        if cache is not None:
            cache[key] = out[path]
    return out


def describe(fact):
    """A fact in plain words, for a reason line: `the name of a card picture, 'Kiln House'`."""
    kind, value = fact.kind, fact.value
    where = " of a card" if fact.piece else ""
    if kind == "word":
        return "the word %r%s" % (value, where)
    if kind == "heading":
        return "the heading %r" % " ".join(value[1])
    if kind == "img":
        return "the name of a%s picture, %r" % (" card" if fact.piece else "", value) if value else "a picture with no name"
    if kind == "imgfile":
        return "the picture file %r" % value
    if kind == "link":
        return "a link to %r" % (value or "the home page")
    if kind == "frame":
        return "a player %r (%s)" % value
    if kind == "current":
        return "the current mark %r on %r" % value
    if kind == "file":
        return "the published file %r" % value
    return "the title %r" % value


PLURAL = {"word": "words", "heading": "headings", "img": "picture names", "imgfile": "picture files", "link": "links",
          "frame": "players", "current": "current marks", "title": "titles", "file": "published files"}


class Frame(object):
    """How each build's addresses are read (sections 5.1 and 7.1): `new_path` the path the plugin's build is served under (the
    converted `site.json`'s `SiteConfig.site_path()`, None the root), `old_path` the path the old build's own output assumes
    (`sameresource.build_path(old build, new_path)`), and `moved` {old address: piece} for each recorded redirect (`site.json`
    `redirects`) whose target is a piece page, read on the old build's pages only."""

    def __init__(self, old_path=None, new_path=None, moved=None):
        self.old_path, self.new_path, self.moved = old_path, new_path, dict(moved or {})


def frame_for(snap, data, local):
    """The `Frame` of one `choose`: read from the converted tree's `site/site.json` (`data`, the dict `choose` is handed, when the
    tree holds none). A site.json the schema refuses reads at the root, never a guess: `SiteConfig.site_path()` is the one reader."""
    raw = snap.get("site/site.json")
    try:
        d = json.loads(raw.decode("utf-8")) if raw is not None else dict(data or {})
    except ValueError:
        d = dict(data or {})
    try:
        new_path = configmodel.parse_data(d).site_path()
    except Exception:          # noqa: BLE001 -- a refused site.json is the build's to report; here it only means "the root"
        new_path = None
    pieces = piece_addresses(snap)
    moved = {}
    for old, new in sorted((d.get("redirects") or {}).items() if isinstance(d.get("redirects"), dict) else ()):
        key = re.sub(r"(?:^|/)index\.html$", "", str(old).strip("/")).strip("/")
        if isinstance(new, str) and new.strip("/") in pieces:
            moved[key] = new.strip("/")
    return Frame(sameresource.build_path(local or {}, new_path) if new_path else None, new_path, moved)
