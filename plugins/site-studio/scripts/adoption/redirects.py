"""adoption.redirects -- meta-refresh pages read as site.json redirects.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import html
import html.parser
import posixpath
import re
from collections import namedtuple
from urllib.parse import urlsplit

import siteconfig  # noqa: E402

from adoption.spec import HEAD_BOILERPLATE_LINKS, HEAD_BOILERPLATE_METAS
from adoption.tokens import detect_resume, portfolio_folders

STUB_MAX_WORDS = 12     # the words a redirect page may carry in its paragraph and link ("This page has moved: continue")
_STUB_QUOTES = "\"'"


class _Stub(html.parser.HTMLParser):
    """What a page is made of, for the one question: is it NOTHING BUT a redirect? It records the
    refresh, the canonical link, the anchors, the scripts, and everything else it finds (`foreign`: a tag the
    list does not allow; `stray`: text outside a paragraph, a link, the title and a script)."""

    ALLOWED = ("html", "head", "body", "meta", "title", "link", "a", "p", "script")

    def __init__(self):
        html.parser.HTMLParser.__init__(self, convert_charrefs=True)
        self.refresh, self.canon, self.anchors, self.scripts = [], [], [], []
        self.title = ""
        self.foreign, self.stray, self.words, self.texts, self.bare_p = [], [], 0, [], []
        self.boiler = []        # head boilerplate (an icon, a manifest, a theme colour): a redirect, with more in its head
        self._mode = None
        self._p = None
        self._in_a = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict((k.lower(), v or "") for k, v in attrs)
        if tag == "meta":
            if a.get("http-equiv", "").strip().lower() == "refresh":
                self.refresh.append(a.get("content", ""))
            elif a.get("name", "").strip().lower() in HEAD_BOILERPLATE_METAS:
                self.boiler.append("<meta name=%s>" % a.get("name", "").strip().lower())
            elif not ("charset" in a or a.get("name", "").strip().lower() in ("viewport", "robots")):
                self.foreign.append("a <meta> that is not charset, viewport, robots, the refresh, a theme colour or a colour scheme")
        elif tag == "link":
            rel = " ".join(a.get("rel", "").strip().lower().split())
            if rel == "canonical":
                self.canon.append(a.get("href", ""))
            elif rel in HEAD_BOILERPLATE_LINKS:
                self.boiler.append("<link rel=%s>" % rel)
            else:
                self.foreign.append("a <link rel=%s>" % (a.get("rel", "") or "?"))
        elif tag == "a":
            self.anchors.append(a.get("href", ""))
            self._in_a += 1
            if self._p is not None:
                self._p["anchor"] = True
        elif tag == "p":
            self._p = {"text": [], "anchor": False}
        elif tag == "title":
            self._mode = "title"
        elif tag == "script":
            if "src" in a:
                self.foreign.append("a <script src>")
            self._mode = "script"
            self.scripts.append("")
        elif tag not in self.ALLOWED:
            self.foreign.append("a <%s>" % tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._in_a:
            self._in_a -= 1
        elif tag == "p" and self._p is not None:
            p, self._p = self._p, None
            text = " ".join(" ".join(p["text"]).split())
            if text and not p["anchor"]:
                self.bare_p.append(text)
        elif tag in ("title", "script"):
            self._mode = None

    def handle_data(self, data):
        if self._mode == "title":
            self.title += data
        elif self._mode == "script":
            self.scripts[-1] += data
        elif self._p is not None or self._in_a:
            if self._p is not None:
                self._p["text"].append(data)
            self.words += len(data.split())
            self.texts.append(data)
        elif data.strip():
            self.stray.append(" ".join(data.split()))


_SCRIPT_GO = re.compile(r"""^\s*(?:window\.|self\.|top\.)?(?:location(?:\.href)?\s*=\s*|location\.(?:replace|assign)\s*\(\s*)"""
                        r"""(["'])(.*?)\1\s*\)?\s*;?\s*$""", re.S)


def page_key(rel):
    """The `redirects` key (and `{{#page:X}}` / link key) of a `site/src` page, the way the build serves it
    (`build._page_dir`): `old/index.html` is `old`, `old.html` is `old.html`, the root index is ''."""
    if rel in ("index.html", "index.htm"):
        return ""
    for tail in ("/index.html", "/index.htm"):
        if rel.endswith(tail):
            return rel[:-len(tail)]
    return rel


def _refresh_parts(content):
    """(delay seconds as a float or None, target string or None) from a refresh `content` value."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:[;,]\s*(.*?))?\s*$", content or "", re.S)
    if not m:
        return None, None
    target = m.group(2)
    if target is not None:
        target = re.sub(r"^url\s*=\s*", "", target.strip(), flags=re.I).strip()
        if len(target) > 1 and target[0] in _STUB_QUOTES and target[-1] == target[0]:
            target = target[1:-1].strip()
    return float(m.group(1)), (target or None)


def resolve_redirect_target(page_rel, raw):
    """(value, None) or (None, reason). `value` is what a `redirects` entry holds for a refresh target as
    written on the page at `site/src/<page_rel>`: an `http(s)://` address as it stands, or the page key of
    a site-relative address resolved the way a browser would (against the page's own folder)."""
    t = (raw or "").strip()
    if re.match(r"^https?://", t):
        return t, None
    if not t:
        return None, "it names no address to go to"
    if t.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", t):
        return None, "its target %s is neither a page on this site nor an http(s):// address" % t
    if "#" in t or "?" in t:
        return None, "its target %s carries a query or a fragment, which a redirects entry cannot" % t
    path = t.lstrip("/") if t.startswith("/") else posixpath.join(posixpath.dirname(page_rel), t)
    path = posixpath.normpath(path)
    if path == ".." or path.startswith("../"):
        return None, "its target %s points outside the site" % t
    if posixpath.basename(path) in ("index.html", "index.htm"):
        path = posixpath.dirname(path)
    if path in ("", "."):
        return None, ("its target is the home page, which a site.json redirects entry cannot name "
                      "(leave the page, or point it at a page)")
    return path, None


def _same_target(main, other):
    """True when `other` (a canonical link, an anchor, a script's address, already resolved) is `main`."""
    if other == main or other.rstrip("/") == main.rstrip("/"):
        return True
    web_m, web_o = main.startswith(("http://", "https://")), other.startswith(("http://", "https://"))
    if web_m != web_o:      # an absolute address that ends in the site-relative key (a base path ahead of it)
        url, key = (main, other) if web_m else (other, main)
        path = urlsplit(url).path
        if posixpath.basename(path) in ("index.html", "index.htm"):
            path = posixpath.dirname(path)
        path = path.strip("/")
        return path == key or path.endswith("/" + key)
    return False


def built_page_keys(tree, skip=()):
    """The page keys a `redirects` target may name in the converted tree: every `site/src` HTML page that
    stays, the portfolio folders and their pieces, about and resume. A target the plugin's build would not
    find is not in this set (an honest approximation: a page left out here is left as a hand page, never
    converted wrongly)."""
    keys = set()
    for p in tree.paths():
        if p.startswith("site/src/") and p.lower().endswith((".html", ".htm")) and p not in skip:
            keys.add(page_key(p[len("site/src/"):]))
    folders = portfolio_folders(tree)
    keys.update(folders)
    for p in tree.paths():
        parts = p.split("/")
        if len(parts) == 4 and parts[0] == "content" and parts[1] in folders and parts[3] == "index.md":
            keys.add("%s/%s" % (parts[1], parts[2]))
    if detect_resume(tree)["md"]:
        keys.add("resume")
    if tree.exists("content/about.md"):
        keys.add("about")
    return keys


RedirectPage = namedtuple("RedirectPage", "path key target dropped boiler")


def _stub_verdict(rel, text):
    """None when the page is not a meta-refresh page at all; else ('left', reason) or ('ok', target value,
    the page text a conversion drops), before the checks that need the rest of the tree."""
    s = _Stub()
    try:
        s.feed(text)
        s.close()
    except Exception:       # a page the parser cannot read is content, never a redirect
        return None
    if not s.refresh:
        return None
    parts = [_refresh_parts(c) for c in s.refresh]
    if any(d is None or t is None for d, t in parts):
        return ("left", "its refresh names no address to go to, or is not read as `0; url=...`")
    if len(set(parts)) > 1:
        return ("left", "it holds more than one refresh")
    delay, raw = parts[0]
    if delay != 0:
        return ("left", "its refresh waits %g second(s), not 0, so the page is content a visitor reads" % delay)
    extra = (s.foreign[:1] or (["text outside its link: \"%s\"" % s.stray[0][:40]] if s.stray else [])
             or (["a paragraph of its own: \"%s\"" % s.bare_p[0][:40]] if s.bare_p else [])
             or (["more than %d words of text" % STUB_MAX_WORDS] if s.words > STUB_MAX_WORDS else []))
    if extra:
        return ("left", "it carries more than the redirect (%s)" % extra[0])
    value, why = resolve_redirect_target(rel, raw)
    if why:
        return ("left", why)
    for what, urls in (("its canonical link", s.canon), ("its link", s.anchors)):
        for u in urls:
            v, w = resolve_redirect_target(rel, u)
            if w or not _same_target(value, v):
                return ("left", "%s goes to %s, not to %s" % (what, u, raw))
    for code in s.scripts:
        m = _SCRIPT_GO.match(code)
        v = resolve_redirect_target(rel, m.group(2))[0] if m else None
        if v is None or not _same_target(value, v):
            return ("left", "its script does more than send the visitor to %s" % raw)
    title = " ".join(s.title.split())
    dropped = " ".join(x for x in ["" if title.lower() == "redirecting" else title, " ".join("".join(s.texts).split())] if x)
    return ("ok", value, dropped[:80], tuple(s.boiler))


def redirect_pages(tree, existing=None):
    """(convert, left) for every `site/src` page that carries a meta refresh (design 7.5). `convert` is a list
    of RedirectPage (path, redirects key, redirects value, the page text adopt drops); `left` is [(path, reason)]
    for a refresh page that stays a hand page. A page converts only when NOTHING else is on it, its key and
    target are ones `siteconfig` accepts, its target is a page the build will have (or an http(s) address) and
    `existing` (the site.json `redirects`) does not already send that key elsewhere."""
    existing = existing if isinstance(existing, dict) else {}
    cand, left = [], []
    for p in tree.paths():
        if not (p.startswith("site/src/") and p.lower().endswith((".html", ".htm"))):
            continue
        rel = p[len("site/src/"):]
        v = _stub_verdict(rel, tree.text(p))
        if v is None:
            continue
        if v[0] == "left":
            left.append((p, v[1]))
        elif posixpath.basename(rel) == "404.html":
            left.append((p, "it is the 404 page"))
        elif page_key(rel) == "":
            left.append((p, "it is the home page"))
        else:
            cand.append((p, page_key(rel), v[1], v[2], v[3]))
    moving = set(c[0] for c in cand)
    keys = built_page_keys(tree, skip=moving)
    convert = []
    for p, key, value, dropped, boiler in sorted(cand):
        try:
            siteconfig._redirect_entry(key, value)
        except siteconfig.SiteConfigError as e:
            left.append((p, str(e).replace("site.json: ", "", 1)))
            continue
        if not value.startswith(("http://", "https://")) and value not in keys:
            chained = any(c[1] == value for c in cand)
            left.append((p, "its target is another redirect page that adopt also converts" if chained else
                         "the build has no page '%s' to point it at" % value))
            continue
        if key in existing and existing[key] != value:
            left.append((p, "site.json already sends '%s' to '%s'" % (key, existing[key])))
            continue
        convert.append(RedirectPage(p, key, value, dropped, boiler))
    return convert, sorted(left)


def redirect_problems(convert):
    """One mechanical `siteconfig.Problem` per page adopt will turn into a redirects entry, so `check` and
    `inventory` list it beside the others, marked `apply fixes this`."""
    out = []
    for r in convert:
        out.append(siteconfig.make_problem(
            "%s is a meta-refresh page: it belongs in site.json redirects as '%s'" % (r.path, r.key),
            path=r.path, found="a hand-made meta-refresh page", expected="a site.json redirects entry",
            fix="move it into site.json redirects ('%s' -> '%s'); the build writes the page" % (r.key, r.target),
            mechanical=True))
    return out
