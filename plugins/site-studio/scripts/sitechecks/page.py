"""page.py -- one built HTML page read into what the checks need (`Page`, `parse_page`), the video-facade scan
(`FacadeScan`, `facade_loads`, design 4.3 `media`) and the `srcset` and CSS `url()` readers.
"""

import re
from html.parser import HTMLParser


_VOID = frozenset(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
                    "wbr"])
_TRACKED = frozenset(["a", "div", "main", "nav", "section", "article", "ul", "ol", "table", "form", "header", "footer",
                      "figure", "script", "style", "title", "head", "body", "html", "li", "button", "select", "textarea"])


class Page(HTMLParser):
    def __init__(self, rel, source):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.rel = rel
        self.source = source
        self.doctype = None
        self.html_lang = None
        self.title = ""
        self._in_title = False
        self.metas = []
        self.linktags = []
        self.anchors = []        # dicts: href, text
        self.imgs = []
        self.iframes = []
        self.scripts = []        # dicts: src or None
        self.script_text = []
        self.style_text = []
        self.comments = []
        self.ids = set()
        self.h1 = 0
        self.text = []           # visible text
        self.main_text = []
        self.attr_text = []      # alt, title, aria-label, meta content ...
        self.nav_hrefs = None
        self.base = None
        self.errors = []
        self._stack = []
        self._skip = 0
        self._nav_depth = 0
        self._nav_done = False
        self._in_primary_nav = False
        self._main_depth = 0
        self._cur_a = None
        self.inline_style_attrs = []
        self.has_noindex = False
        self.robots_words = set()    # the lower-cased, comma-separated words of every `robots` meta (`search_out`, dev 1068)

    # -- parsing ---------------------------------------------------------------------------
    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.doctype = decl

    def handle_comment(self, data):
        self.comments.append(data)

    def handle_starttag(self, tag, attrs):
        a = dict((k, (v if v is not None else "")) for k, v in attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "name" in a and tag == "a":
            self.ids.add(a["name"])
        if "style" in a:
            self.inline_style_attrs.append(a["style"])
        for k in ("alt", "title", "aria-label", "placeholder"):
            if k in a and a[k]:
                self.attr_text.append(a[k])
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(a)
            if a.get("content") and (a.get("name") or a.get("property")):
                self.attr_text.append(a["content"])
            if a.get("name", "").lower() == "robots":
                self.robots_words.update(w.strip().lower() for w in a.get("content", "").split(","))
                if "noindex" in a.get("content", "").lower():
                    self.has_noindex = True
        elif tag == "link":
            self.linktags.append(a)
        elif tag == "base":
            self.base = a.get("href", "")
        elif tag == "a":
            self._cur_a = {"href": a.get("href"), "text": [], "attrs": a, "in_main": bool(self._main_depth)}
            self.anchors.append(self._cur_a)
            if self._in_primary_nav and a.get("href") is not None:
                self.nav_hrefs.append(a["href"])
        elif tag == "img":
            self.imgs.append({"src": a.get("src"), "alt": a.get("alt"), "width": a.get("width"),
                              "height": a.get("height"), "loading": a.get("loading"),
                              "srcset": a.get("srcset"), "sizes": a.get("sizes"),
                              "held": "data-ss-held" in a,            # the tag the look's own picture part writes (design-publish-preflight 3.2)
                              "in_main": bool(self._main_depth)})
        elif tag == "iframe":
            self.iframes.append(a)
        elif tag == "script":
            self.scripts.append({"src": a.get("src")})
            self._skip += 1
        elif tag == "style":
            self._skip += 1
        elif tag == "h1":
            self.h1 += 1
        elif tag == "nav":
            if not self._nav_done and self._nav_depth == 0:
                self.nav_hrefs = []
                self._in_primary_nav = True
            self._nav_depth += 1
        elif tag == "main":
            self._main_depth += 1
        if tag in _TRACKED:
            self._stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and tag in _TRACKED and self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            self._cur_a = None
        elif tag == "nav" and self._nav_depth:
            self._nav_depth -= 1
            if self._nav_depth == 0:
                self._nav_done = True
                self._in_primary_nav = False
        elif tag == "main" and self._main_depth:
            self._main_depth -= 1
        if tag in _TRACKED:
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            elif tag in self._stack:
                bad = self._stack[self._stack.index(tag) + 1:]
                self.errors.append("</%s> closes while <%s> is still open" % (tag, bad[-1]))
                del self._stack[self._stack.index(tag):]
            else:
                self.errors.append("</%s> has no matching start tag" % tag)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip:
            if self.scripts and self._stack and self._stack[-1] == "script":
                self.script_text.append(data)
            elif self._stack and self._stack[-1] == "style":
                self.style_text.append(data)
            return
        self.text.append(data)
        in_pdf_link = self._cur_a is not None and (self._cur_a["href"] or "").lower().endswith(".pdf")
        if self._main_depth and not in_pdf_link:
            self.main_text.append(data)   # the "Download as PDF" caption is not resume content
        if self._cur_a is not None:
            self._cur_a["text"].append(data)

    def finish(self):
        self.close()
        for t in self._stack:
            self.errors.append("<%s> is never closed" % t)

    @property
    def visible_text(self):
        """Text chunks joined with a space, so `<dt>Email</dt><dd>a@b.c` cannot fuse into one word."""
        return re.sub(r"[ \t\r\f\v]+", " ", " ".join(self.text))

    @property
    def fused_text(self):
        """The same text with no separator, for a private term split across inline tags."""
        return "".join(self.text)


def main_words(page):
    """The words rule 2 compares a printed PDF against: the page's <main> text, the 'Download as PDF' caption excluded, joined
    with a space. ONE function: the site gate (`privacy.py`) and `resume_pdf.py` both call it (dev 1068, design-publish-preflight
    section 2.2)."""
    return " ".join(page.main_text)


def search_out(page):
    """Why `page` is out of search, or None (design-publish-preflight section 7, S1; dev 1068): "noindex" when a `robots` meta's
    comma-separated words hold `noindex` or `none` (any case; `index,nofollow` holds neither), "refresh" for a `meta refresh`, else
    None. ONE function: the build (`building.carried.left_out`, for `_Builder.build_sitemap`) and the gate (`checker`, `domain`,
    `unfinished`) both ask it, and ask it only under `site.json` `sitemap: "indexable"`: a site without the key is read as before
    (a substring, `_is_redirect`, none), so no 0.9.0 tree changes."""
    if page.robots_words & {"noindex", "none"}:
        return "noindex"
    if any(m.get("http-equiv", "").lower() == "refresh" for m in page.metas):
        return "refresh"
    return None


def parse_page(rel, text):
    p = Page(rel, text)
    try:
        p.feed(text)
        p.finish()
    except Exception as e:  # malformed markup the parser cannot take is itself a finding
        p.errors.append("the HTML cannot be parsed (%s)" % e.__class__.__name__)
    return p


_REMOTE_LOAD = re.compile(r"^\s*(?:https?:|ftp:|//)", re.I)


FACADE_ROOTS = ("ss-video", "ss-videos", "ss-map", "ss-showcase", "ss-gallery-video", "ss-steps")


class FacadeScan(HTMLParser):
    """The facade loading-attribute rule (site-fidelity section 7.3, dev #865; extended at 0.4.0 and 0.5.0). Inside an
    element whose class list holds one of `FACADE_ROOTS` (`ss-video`, `ss-videos`, the schema-4 `ss-map`,
    `ss-showcase`, `ss-gallery-video`, and the schema-5 steps view `ss-steps`), no element may carry a LOADING attribute with a remote value: `src` and
    `srcset` (an <img>, an <iframe>, a <source>, a <video>), `poster`, `data` (an <object>), `href` on a <link>,
    and `href` or `xlink:href` on an SVG <image> or <use>. `href` on an <a> and `data-embed` are exempt: they hold
    the video's address, or the piece a pin or tile links to, and load nothing until a click.

    SHAPE ONLY, and it says so: it reads the markup the build wrote, not what a browser fetches. A script that
    adds a request, a CSS rule the page's own stylesheet adds, or an attribute spelled some other way is not
    seen. The behavioural half is one case in test_build.py that runs `video.js` under node with a stub DOM.
    `found` is [(tag, attribute, value)]."""

    LOADING = ("src", "srcset", "poster", "data")

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.stack = []             # (tag, is a facade root)
        self.found = []

    def handle_starttag(self, tag, attrs):
        a = dict((k, (v if v is not None else "")) for k, v in attrs)
        classes = a.get("class", "").split()
        root = any(c in FACADE_ROOTS for c in classes)
        if root or any(r for _t, r in self.stack):
            names = list(self.LOADING) + (["href"] if tag == "link" else []) + (
                ["href", "xlink:href"] if tag in ("image", "use") else [])
            for k in names:
                v = a.get(k)
                if v is None:
                    continue
                cands = [u for u, _d in parse_srcset(v)] if k == "srcset" else [v]
                for u in cands:
                    if _REMOTE_LOAD.match(u):
                        self.found.append((tag, k, u))
        if tag not in _VOID:
            self.stack.append((tag, root))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def facade_loads(text):
    """[(tag, attribute, value)]: every loading attribute inside a video facade that points off the site."""
    if not any(root in text for root in FACADE_ROOTS):
        return []
    scan = FacadeScan()
    try:
        scan.feed(text)
        scan.close()
    except Exception:       # noqa: BLE001 -- malformed markup is the `structure` family's finding
        pass
    return scan.found


def parse_srcset(s):
    out = []
    for part in (s or "").split(","):
        bits = part.split()
        if bits:
            out.append((bits[0], bits[1] if len(bits) > 1 else ""))
    return out


_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
_CSS_IMPORT = re.compile(r"@import\s+(?:url\()?\s*['\"]([^'\"]+)['\"]", re.I)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
