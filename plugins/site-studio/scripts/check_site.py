#!/usr/bin/env python3
"""check_site.py -- the site gate (dev #835, design sections 4.3, 7.1, 8.2; named changes M8, M10).
Python 3.9, stdlib only. It only reads; it never writes into the site.

    python3 check_site.py [--repo R] [--json] [--report]            build R at HEAD, then check it
    python3 check_site.py [--repo R] --out DIR [--json] [--report]  check an existing build in DIR
    python3 check_site.py --scan-source PATH [PATH ...] [--json]    shape scan of a SOURCE tree

R supplies site/site.json (the config) and, for the resume PDF, its sidecar. The default mode builds
with build.publish_build into a temp dir: the gate checks what would be PUBLISHED.

THE FAMILIES (design 4.3). A finding names its family. There is NO command-line way to skip, waive
or ignore a family or a finding: a false positive is fixed in this file, with a dated note in this
docstring. (No such note exists yet.)

  structure    required files (index.html, 404.html, .nojekyll, and robots.txt + sitemap.xml once a
               site URL is known); files that must never be published (markdown sources, site.json,
               layout.html, *.pdf.json, .site-studio, decisions, originals, OS junk, editor leftovers,
               symlinks); URL-unsafe file names; every page has a doctype, <html lang>, balanced
               structural tags, and exactly one <h1> (the 404 page and redirect stubs excepted).
  comments     no HTML comment in a page, no CSS or SVG comment (the build strips the first two; this
               proves it). JavaScript comments are NOT in scope: the build does not strip them, and
               a private term inside one is caught by the privacy family anyway. A sourceMappingURL
               reference in JS or CSS is a finding (it names a local path).
  links        every internal href/src/srcset/css url()/meta-refresh resolves to a file in the tree
               (exact case: Pages is case-sensitive) and every #fragment to an id in that page;
               http:// and protocol-relative links are findings; the unique EXTERNAL links are
               listed by --report (they are never fetched: the gate has no network).
  reachable    every page is reachable from the home page by links (redirect stubs and the 404 page
               excepted) and every published non-page file is referenced by a page or stylesheet
               (the root files robots.txt, sitemap.xml, CNAME, .nojekyll and favicon.* excepted).
  privacy      design 7.1, below.
  domain       CNAME present and equal to `domain` after cutover, absent before; canonical, og:url,
               sitemap <loc> and robots Sitemap all start with the site URL; no absolute URL to the
               other origin (the preview URL after cutover, the not-yet-live domain before); every
               page appears in the sitemap and every <loc> is a real page.
  media        every <img> has an alt attribute (empty is allowed: decorative), a src that exists,
               width/height equal to the file header's, srcset widths equal to each file's real
               width and a sizes attribute; an alt text that is a file name; formats the web will
               not show (heic, tiff, bmp); a long edge over 2000 px; every <iframe> has a title and
               comes from a recognised video host (youtube-nocookie, player.vimeo, drive.google).
  unfinished   TODO/FIXME/TBD/lorem ipsum/coming soon/under construction in visible text, empty or
               "#" links, development URLs (localhost, 127.0.0.1, file://), a noindex page that is
               not a redirect stub, an untitled or empty page.
  performance  the budgets of site.json (siteconfig.BUDGET_DEFAULTS): an image over sizeCopyOverKB
               that images.plan_copies says needs size copies but has none; per page, the images
               it loads against firstViewMaxMB (non-lazy images and the first image) and
               pageImagesMaxMB (all). An image costs its largest candidate up to 1440 px wide
               (what a 2x screen would fetch from the srcset). OURS: an approximation, stated.
  head         per page: charset, viewport (width=device-width), a non-empty title unique across
               pages, a description, and, when a site URL is known, a canonical equal to the page's
               own URL plus og:title, og:description and og:url.
  nav          every page except the 404 page and redirect stubs carries the primary nav (the first
               <nav>), with the same set of targets as the home page; every page links home.
  basepath     the site is served under /<repo>/ before cutover, so a root-absolute link or url(),
               a <base> tag, a development origin, or an absolute URL on the site's own host but
               outside its path is a finding.
  size         the published tree against treeMaxMB, and any single file near GitHub's limit.

COVERAGE (CLAUDE.md: a green run is never an empty one). The gate prints what it scanned
(`checked: ...`). A tree with no HTML page is a failure in `structure`, not a pass.

PRIVACY (design 7.1) -- what it scans, and how
  Every file path, every text-like file's content (html/css/js/svg/txt/xml/json/webmanifest/
  sitemap), every image's metadata and every PDF's decoded text and metadata.
    * phone numbers: NANP shapes (with optional +1, parentheses, dots, dashes or spaces), +country
      international shapes, a 7-digit local number next to a word such as phone/call/tel, and any
      tel: link. In the BUILD gate nothing is allowed: a reserved 555-01xx number is flagged, because
      a real site never needs one and a planted one must be found (the allow-list belongs only to
      --scan-source, below).
    * street addresses: a house number, up to four capitalised words and a street suffix (Street,
      St, Avenue, Ave, Road, Rd, Lane, Drive, ...), a PO Box, and a city, state and ZIP line.
    * email addresses not listed in `publicEmails`, in text, attributes and mailto: links, and in
      PDF text. A "name@2x.png" style asset name is not an email (a file-extension TLD).
    * every `privateTerms` entry, case-insensitively and NFC/whitespace-normalised, in text, alt
      text, file names, URLs, script contents and PDF text. PDF text is searched in two forms (as
      decoded, and with ALL whitespace removed), because a word Chrome splits across two text runs
      reads as two words.
    * hidden image metadata (images.inspect_metadata): EXIF GPS, owner, serial, any other EXIF,
      XMP, IPTC, comments, PNG text/time chunks. The pipeline strips all of it at import, so any
      survivor is a finding.
    * PDF document metadata: /Author is a finding if present. /Creator is a finding unless it is a
      known generator name (Chromium, Chrome, Skia/PDF, HeadlessChrome). /Title is a finding unless
      it equals the <title> of one of this build's own pages (a public string by construction).
      /Producer, /Subject, /Keywords and the XMP fields are scanned like text. (JUDGEMENT, dated
      2026-11-12: design 7.1 lists author, creator and title; flagging a Chrome PDF's own Creator
      and the page-title Title would reject every resume the plugin prints, so those two are
      judged against what is public rather than refused outright.)
    * PDF text counts as READ only by OUTCOME (pdftext.read_pdf: decoded completely). The family
      prints, every run, `PDFs: N read, M NOT READ (listed below)`. A NOT READ PDF is never counted
      clean and is listed (and is a record with level "not-read" in --json) for privacy-guard; it
      does not by itself fail the gate, because the judgement half (design 7.2) is what answers it.
      For the PDF the plugin printed (the resume, identified by its sidecar's pdf_sha256) rule 2 of
      7.1 also applies: the decoded text must contain at least 95% of the words of the built resume
      page's <main> text, else it is NOT READ. A resume PDF with no matching sidecar is NOT READ.
      Rule 1 of the reader has so far been validated only against generator PDFs (see pdftext.py).

SOURCE SHAPE SCAN (--scan-source; design 8.2, named change M10). The CI half of "no personal
content from the example repos entered this repo". It runs the privacy family's shape checks over a
source tree: phone numbers, street addresses, emails, EXIF GPS/owner/serial in images, and the same
in readable PDFs. It has no privateTerms or publicEmails (those are a site's own). THE ALLOW-LIST
IS EXPLICIT AND LIVES HERE, in ALLOW_PHONE_RESERVED, ALLOW_EMAIL_DOMAINS and ALLOW_FILES:
    phone  the NANP range reserved for fiction, 555-0100 to 555-0199 (anything else, including
           555-0200, is flagged);
    email  RFC 2606/6761 names: example.com, example.org, example.net and their subdomains, and the
           TLDs .test, .invalid, .example, .localhost (a lookalike such as notexample.com is not
           allowed: matching is on whole labels);
    files  named globs, each with the kinds it may carry and the reason (ALLOW_FILES, empty unless
           a real false positive is recorded there with its reason);
    emails ONE named address in ONE named file, with the reason (ALLOW_EMAILS): the marketplace's own
           published contact address, which `.claude-plugin/plugin.json` must carry as `author.email`
           for the plugin directory (dev #835, gate-keeper G2). It is the address, not the file: any
           OTHER address in plugin.json is still flagged, and the same address in any other file is
           still flagged.
Images carrying GPS are NEVER tracked in this repo: the tests that need one make it in a temp dir.
Source files that mention a pattern must not contain a real-shaped example of it; write the
documentation of a shape without a literal instance.

EXIT CODES: 0 no findings; 1 one or more findings; 2 usage or an unreadable config. NOT READ PDFs
alone exit 0 (see above). --json prints one JSON object per line: each finding ({"level":"error",
"family","path","message"}), each NOT READ PDF ({"level":"not-read",...}), with --report each external
link ({"level":"report","kind":"external-link","url","pages"}), then one {"level":"summary",...}.
"""
import argparse
import fnmatch
import hashlib
import html
import json
import os
import posixpath
import re
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import images  # noqa: E402
import pdftext  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402

FAMILIES = ("structure", "comments", "links", "reachable", "privacy", "domain", "media",
            "unfinished", "performance", "head", "nav", "basepath", "size")

# ---- the explicit allow-list of the SOURCE shape scan (named change M10) -----------------------
ALLOW_PHONE_RESERVED = re.compile(r"555[-. ]?01\d\d$")
ALLOW_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
ALLOW_EMAIL_TLDS = ("test", "invalid", "example", "localhost")
# (glob over the path as scanned, kinds allowed, reason). Empty on purpose: add an entry only for a
# real false positive, with the reason, in the commit that adds it.
ALLOW_FILES = ()
# (glob over the path as scanned, ONE exact address, reason). An address, never a whole file or a
# domain: see the docstring. The marketplace publishes this address on purpose (plugin.json `author`,
# also exempt in scripts/publish_manifest.py SHAPE_OK); the scan flagged it as "outside the reserved
# domains" because it is real, and a real address in a source tree is exactly what the scan is for.
ALLOW_EMAILS = (
    (".claude-plugin/plugin.json", "marketplace" + "@" + "crinaro.ai",   # split: the scan reads this file too
     "the marketplace's own published contact address, required as author.email by the plugin directory"),
)

TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".svg", ".txt", ".xml", ".json", ".webmanifest",
             ".md", ".py", ".yml", ".yaml", ".toml", ".jsonl", ".cfg", ".ini", ".csv", ".sh")
SITE_TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".svg", ".txt", ".xml", ".json",
                  ".webmanifest", ".map")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
BAD_IMAGE_EXTS = (".heic", ".heif", ".tif", ".tiff", ".bmp", ".raw", ".cr2", ".nef", ".dng")
KNOWN_GENERATORS = ("chromium", "chrome", "skia/pdf", "headlesschrome", "google chrome")
VIDEO_HOSTS = ("www.youtube-nocookie.com", "player.vimeo.com", "drive.google.com")
ROOT_EXEMPT = ("robots.txt", "sitemap.xml", "CNAME", ".nojekyll", "404.html")
FORBIDDEN_NAMES = ("CLAUDE.md", "HANDOFF.md", "BRAND.md", "site.json", "layout.html", "text.md",
                   "reference.json", "package.json", "package-lock.json")
FORBIDDEN_DIRS = (".git", ".site-studio", ".github", "decisions", "originals", "node_modules",
                  "__MACOSX", "templates")
JUNK_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")
JUNK_SUFFIXES = ("~", ".bak", ".orig", ".part", ".tmp", ".swp", ".md", ".pdf.json", ".jsonl", ".py")
FILE_EXT_TLDS = frozenset(["png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js", "html", "htm",
                           "json", "pdf", "ico", "woff", "woff2", "ttf", "otf", "map", "txt", "md"])


class Finding(object):
    def __init__(self, family, path, message, level="error"):
        self.family, self.path, self.message, self.level = family, path, message, level

    def to_dict(self):
        return {"level": self.level, "family": self.family, "path": self.path,
                "message": self.message}

    def sort_key(self):
        return (FAMILIES.index(self.family) if self.family in FAMILIES else 99, self.path,
                self.message)


class Report(object):
    def __init__(self):
        self.findings = []
        self.not_read = []          # Finding objects, level "not-read"
        self.pdfs_read = 0
        self.externals = {}         # url -> set(pages)
        self.checked = {}
        self.notes = []
        self.skipped = []

    def add(self, family, path, message):
        self.findings.append(Finding(family, path, message))

    def count(self, family, n=1):
        self.checked[family] = self.checked.get(family, 0) + n

    @property
    def ok(self):
        return not self.findings


# ---------------------------------------------------------------------------------------------
# privacy patterns
# ---------------------------------------------------------------------------------------------

_PHONE_NANP = re.compile(
    r"(?<![\w.])(?:\+?1[\s.-]?)?(?:\(\s*[2-9]\d{2}\s*\)|[2-9]\d{2})[\s.-]?[2-9]\d{2}[\s.-]\d{4}(?![\d])")
_PHONE_INTL = re.compile(r"(?<![\w.])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?![\d])")
_PHONE_LOCAL = re.compile(
    r"(?i)\b(?:phone|call|tel|telephone|text|fax|cell|mobile|whatsapp)\b[^\n\d]{0,12}"
    r"(?<![\d.])(\d{3}[-. ]\d{4})(?!\d)")
_STREET = re.compile(
    r"(?<![\w.])\d{1,6}[A-Za-z]?\s+(?:(?:N|S|E|W|NE|NW|SE|SW)\.?\s+)?(?:[A-Z][A-Za-z'’.-]*\s+){1,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|Terrace|"
    r"Ter|Parkway|Pkwy|Highway|Hwy|Circle|Cir|Square|Sq|Trail|Trl|Alley|Crescent|Close)\b\.?")
_POBOX = re.compile(r"(?i)\bP\.?\s?O\.?\s+Box\s+\d+\b")
_CITYZIP = re.compile(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")


def norm_phone_digits(s):
    return re.sub(r"\D", "", s)


def phone_hits(text):
    """[matched text] for every phone-number shape in `text`."""
    out = []
    for rx in (_PHONE_NANP, _PHONE_INTL):
        out.extend(m.group(0).strip() for m in rx.finditer(text))
    out.extend(m.group(1) for m in _PHONE_LOCAL.finditer(text))
    return out


def street_hits(text):
    out = [m.group(0).strip() for m in _STREET.finditer(text)]
    out.extend(m.group(0) for m in _POBOX.finditer(text))
    out.extend(m.group(0) for m in _CITYZIP.finditer(text))
    return out


def email_hits(text):
    out = []
    for m in _EMAIL.finditer(text):
        e = m.group(0)
        tld = e.rsplit(".", 1)[-1].lower()
        if tld in FILE_EXT_TLDS:
            continue
        out.append(e)
    return out


def email_domain_allowed(addr):
    dom = addr.rsplit("@", 1)[-1].lower().rstrip(".")
    for d in ALLOW_EMAIL_DOMAINS:
        if dom == d or dom.endswith("." + d):
            return True
    return dom.rsplit(".", 1)[-1] in ALLOW_EMAIL_TLDS


def phone_allowed_reserved(hit):
    return bool(ALLOW_PHONE_RESERVED.search(norm_phone_digits(hit)))


def norm_for_terms(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).casefold()


def mask(s):
    """A value in a finding without echoing the whole thing: private data stays out of logs."""
    s = s.strip()
    return s if len(s) <= 4 else s[:2] + "*" * (len(s) - 4) + s[-2:]


# ---------------------------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------------------------

_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
_TRACKED = frozenset("a div main nav section article ul ol table form header footer figure script "
                     "style title head body html li button select textarea".split())


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
            if a.get("name", "").lower() == "robots" and "noindex" in a.get("content", "").lower():
                self.has_noindex = True
        elif tag == "link":
            self.linktags.append(a)
        elif tag == "base":
            self.base = a.get("href", "")
        elif tag == "a":
            self._cur_a = {"href": a.get("href"), "text": [], "attrs": a}
            self.anchors.append(self._cur_a)
            if self._in_primary_nav and a.get("href") is not None:
                self.nav_hrefs.append(a["href"])
        elif tag == "img":
            self.imgs.append({"src": a.get("src"), "alt": a.get("alt"), "width": a.get("width"),
                              "height": a.get("height"), "loading": a.get("loading"),
                              "srcset": a.get("srcset"), "sizes": a.get("sizes"),
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


def parse_page(rel, text):
    p = Page(rel, text)
    try:
        p.feed(text)
        p.finish()
    except Exception as e:  # malformed markup the parser cannot take is itself a finding
        p.errors.append("the HTML cannot be parsed (%s)" % e.__class__.__name__)
    return p


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


# ---------------------------------------------------------------------------------------------
# the tree
# ---------------------------------------------------------------------------------------------

class Tree(object):
    def __init__(self, root):
        self.root = root
        self.files = {}      # rel -> size
        self.symlinks = []
        self.dirs = set()
        for d, dirs, names in os.walk(root):
            for dn in list(dirs):
                full = os.path.join(d, dn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                self.dirs.add(rel)
                if os.path.islink(full):
                    self.symlinks.append(rel)
                    dirs.remove(dn)
            for fn in names:
                full = os.path.join(d, fn)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if os.path.islink(full):
                    self.symlinks.append(rel)
                    continue
                self.files[rel] = os.path.getsize(full)
        self._cache = {}

    def read(self, rel):
        if rel not in self._cache:
            with open(os.path.join(self.root, rel), "rb") as fh:
                self._cache[rel] = fh.read()
        return self._cache[rel]

    def text(self, rel):
        return self.read(rel).decode("utf-8", "replace")


def site_base(cfg):
    u = cfg.site_url()
    return u.rstrip("/") if u else None


def classify(url, base):
    """(kind, rest) with kind in empty fragment mail tel special external internal protorel rootabs rel"""
    u = url.strip()
    if u == "":
        return ("empty", "")
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", u)
    if m:
        s = m.group(1).lower()
        if s in ("http", "https"):
            if base and (u == base or u.startswith(base + "/") or u.startswith(base + "?")
                         or u.startswith(base + "#")):
                rest = u[len(base):]
                return ("internal", rest if rest.startswith("/") else "/" + rest)
            return ("external", u)
        if s == "mailto":
            return ("mail", u[7:])
        if s == "tel":
            return ("tel", u[4:])
        return ("special", u)
    if u.startswith("//"):
        return ("protorel", u)
    if u.startswith("/"):
        return ("rootabs", u)
    if u.startswith("#"):
        return ("fragment", u[1:])
    return ("rel", u)


class Checker(object):
    def __init__(self, tree, cfg, repo=None):
        self.t = tree
        self.cfg = cfg
        self.repo = repo
        self.r = Report()
        self.base = site_base(cfg)
        self.pages = {}
        for rel in sorted(tree.files):
            if rel.lower().endswith((".html", ".htm")):
                self.pages[rel] = parse_page(rel, tree.text(rel))
        self.redirects = set(r for r, p in self.pages.items() if self._is_redirect(p))
        self.content_pages = [r for r in sorted(self.pages) if r not in self.redirects]
        self.refs_by_page = {}
        self.referenced = set()
        self.flagged = set()      # files `structure` already refused: not reported again as orphans

    # -- helpers ----------------------------------------------------------------------------
    @staticmethod
    def _is_redirect(p):
        return any(m.get("http-equiv", "").lower() == "refresh" for m in p.metas)

    def site_path(self):
        if not self.base:
            return ""
        return urlsplit(self.base).path.rstrip("/")

    def resolve(self, from_rel, url):
        """(target_rel or None, fragment, problem). `url` is relative or site-internal."""
        sp = urlsplit(url)
        path = unquote(sp.path)
        frag = unquote(sp.fragment)
        if path == "":
            return (from_rel, frag, None)
        if url.startswith("/"):
            # only ever a site-internal absolute URL whose origin and base path were already removed
            joined = path.lstrip("/")
            cand = posixpath.normpath(joined) if joined else "."
            trailing = path.endswith("/") or joined == ""
        else:
            cand = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), path))
            trailing = path.endswith("/")
        if cand.startswith(".."):
            return (None, frag, "the link climbs out of the site root")
        if cand == ".":
            cand = ""
        if trailing or cand == "":
            idx = (cand + "/index.html").lstrip("/")
            if idx in self.t.files:
                return (idx, frag, None)
            miss = "no such page"
        else:
            if cand in self.t.files:
                return (cand, frag, None)
            if (cand + "/index.html") in self.t.files:
                return (cand + "/index.html", frag, None)
            idx = cand
            miss = "no such file"
        lower = dict((k.lower(), k) for k in self.t.files)
        if idx.lower() in lower:
            return (None, frag, "case differs from the file (%s); Pages is case-sensitive" % lower[idx.lower()])
        return (None, frag, miss)

    def collect_refs(self):
        """Every reference in every page and stylesheet: (from_rel, kind, url)."""
        refs = []
        for rel, p in self.pages.items():
            for a in p.anchors:
                if a["href"] is not None:
                    refs.append((rel, "a", a["href"]))
            for im in p.imgs:
                if im["src"] is not None:
                    refs.append((rel, "img", im["src"]))
                for u, _d in parse_srcset(im["srcset"]):
                    refs.append((rel, "srcset", u))
            for s in p.scripts:
                if s["src"]:
                    refs.append((rel, "script", s["src"]))
            for lt in p.linktags:
                if lt.get("href") and lt.get("rel", "").lower() not in ("canonical",):
                    refs.append((rel, "link", lt["href"]))
            for fr in p.iframes:
                if fr.get("src"):
                    refs.append((rel, "iframe", fr["src"]))
            for m in p.metas:
                if m.get("http-equiv", "").lower() == "refresh":
                    mm = re.search(r"url\s*=\s*(.+)$", m.get("content", ""), re.I)
                    if mm:
                        refs.append((rel, "refresh", mm.group(1).strip().strip("'\"")))
                if m.get("property") in ("og:image", "og:url") or m.get("name") == "twitter:image":
                    if m.get("content"):
                        refs.append((rel, "meta", m["content"]))
            for st in p.style_text + p.inline_style_attrs:
                for _q, u in _CSS_URL.findall(st):
                    refs.append((rel, "css", u))
        for rel in sorted(self.t.files):
            if rel.lower().endswith(".css"):
                css = self.t.text(rel)
                for _q, u in _CSS_URL.findall(css):
                    refs.append((rel, "css", u))
                for u in _CSS_IMPORT.findall(css):
                    refs.append((rel, "css", u))
        return refs

    # -- structure --------------------------------------------------------------------------
    def structure(self):
        fam = "structure"
        t = self.t
        self.r.count(fam, len(t.files))
        if not self.pages:
            self.r.add(fam, ".", "the tree holds no HTML page: nothing was checked")
            return
        required = ["index.html", "404.html", ".nojekyll"]
        if self.base:
            required += ["robots.txt", "sitemap.xml"]
        else:
            self.r.notes.append("NOT CHECKED: robots.txt and sitemap.xml (no previewUrl or domain "
                                "gives a site URL)")
        for f in required:
            if f not in t.files:
                self.r.add(fam, f, "required file is missing")
        for rel in sorted(t.files):
            name = posixpath.basename(rel)
            parts = rel.split("/")
            for d in parts[:-1]:
                if d in FORBIDDEN_DIRS:
                    self.r.add(fam, rel, "a %s folder must never be published" % d)
                    self.flagged.add(rel)
                    break
            if name in FORBIDDEN_NAMES:
                self.r.add(fam, rel, "this file is a source or maintenance file and must never be published")
                self.flagged.add(rel)
            elif name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES) or name.startswith("._"):
                self.r.add(fam, rel, "source, editor or OS leftover must never be published")
                self.flagged.add(rel)
            if re.search(r"[\s#?%\\<>\"|*:]", rel):
                self.r.add(fam, rel, "file name is not URL-safe (space or reserved character)")
        for s in t.symlinks:
            self.r.add(fam, s, "a symbolic link must never be published")
        for rel in self.content_pages:
            p = self.pages[rel]
            if not p.doctype:
                self.r.add(fam, rel, "no <!doctype>")
            if not p.html_lang:
                self.r.add(fam, rel, "<html> has no lang attribute")
            for e in p.errors:
                self.r.add(fam, rel, "malformed markup: " + e)
            if rel != "404.html" and p.h1 != 1:
                self.r.add(fam, rel, "expected exactly one <h1>, found %d" % p.h1)

    # -- comments ---------------------------------------------------------------------------
    def comments(self):
        fam = "comments"
        n = 0
        for rel, p in self.pages.items():
            n += 1
            for c in p.comments:
                self.r.add(fam, rel, "HTML comment left in the published page (%d characters)" % len(c))
            for st in p.style_text:
                if _CSS_COMMENT.search(st):
                    self.r.add(fam, rel, "CSS comment left in an inline <style>")
        for rel in sorted(self.t.files):
            low = rel.lower()
            if low.endswith(".css"):
                n += 1
                css = self.t.text(rel)
                if _CSS_COMMENT.search(css.replace("/*# sourceMappingURL", "/*#sourceMappingURL")):
                    self.r.add(fam, rel, "CSS comment left in the published stylesheet")
            elif low.endswith(".svg"):
                n += 1
                if "<!--" in self.t.text(rel):
                    self.r.add(fam, rel, "comment left in the SVG")
            if low.endswith((".js", ".mjs", ".css")):
                if re.search(r"sourceMappingURL=", self.t.text(rel)):
                    self.r.add(fam, rel, "sourceMappingURL names a local file")
        self.r.count(fam, n)

    # -- links -------------------------------------------------------------------------------
    def links(self):
        fam = "links"
        refs = self.collect_refs()
        self.all_refs = refs
        n = 0
        for rel, kind, url in refs:
            n += 1
            k, rest = classify(url, self.base)
            if kind == "meta" and k == "internal":
                pass
            if k == "empty":
                if kind in ("a",):
                    self.r.add(fam, rel, "an empty href")
                continue
            if k in ("mail", "tel", "special", "fragment", "rootabs"):
                if k == "fragment":
                    self._check_fragment(rel, rel, rest)
                if k == "special" and rest.lower().startswith("javascript:"):
                    self.r.add(fam, rel, "a javascript: link")
                continue
            if k == "protorel":
                self.r.add(fam, rel, "protocol-relative URL %s: write https://" % url)
                continue
            if k == "external":
                if url.lower().startswith("http://"):
                    self.r.add(fam, rel, "insecure link %s: use https" % url)
                if kind in ("a", "iframe", "link", "script", "img", "srcset", "css", "meta"):
                    self.r.externals.setdefault(url, set()).add(rel)
                continue
            target, frag, problem = self.resolve(rel, rest if k == "internal" else url)
            if problem and kind != "meta":
                self.r.add(fam, rel, "%s link %s: %s" % (kind, url, problem))
                continue
            if problem:
                self.r.add(fam, rel, "meta URL %s: %s" % (url, problem))
                continue
            if target:
                self.referenced.add(target)
                if frag:
                    self._check_fragment(rel, target, frag)
        self.r.count(fam, n)

    def _check_fragment(self, from_rel, target, frag):
        if frag in ("", "top"):
            return
        p = self.pages.get(target)
        if p is None:
            return
        if frag not in p.ids:
            self.r.add("links", from_rel, "fragment #%s is not an id on %s" % (frag, target))

    # -- reachable ---------------------------------------------------------------------------
    def reachable(self):
        fam = "reachable"
        if "index.html" not in self.pages:
            self.r.add(fam, ".", "there is no index.html to start from")
            return
        seen = set(["index.html"])
        queue = ["index.html"]
        while queue:
            cur = queue.pop()
            for a in self.pages[cur].anchors:
                href = a["href"]
                if href is None:
                    continue
                k, rest = classify(href, self.base)
                if k not in ("rel", "internal"):
                    continue
                target, _f, problem = self.resolve(cur, rest if k == "internal" else href)
                if target and not problem and target in self.pages and target not in seen:
                    seen.add(target)
                    queue.append(target)
        self.r.count(fam, len(self.pages) + len(self.t.files))
        for rel in self.content_pages:
            if rel == "404.html" or rel in seen:
                continue
            self.r.add(fam, rel, "page cannot be reached from the home page by following links")
        for rel in sorted(self.t.files):
            low = rel.lower()
            name = posixpath.basename(rel)
            if low.endswith((".html", ".htm")) or ("/" not in rel and name in ROOT_EXEMPT):
                continue
            if "/" not in rel and name.lower().startswith(("favicon", "apple-touch-icon")):
                continue
            if rel in self.flagged:
                continue
            if rel not in self.referenced:
                self.r.add(fam, rel, "published but not referenced by any page or stylesheet")

    # -- domain ------------------------------------------------------------------------------
    def domain(self):
        fam = "domain"
        cfg = self.cfg
        n = 0
        has_cname = "CNAME" in self.t.files
        n += 1
        if cfg.cutover:
            if not has_cname:
                self.r.add(fam, "CNAME", "cutover is true but the build has no CNAME file")
            elif self.t.text("CNAME").strip() != cfg.domain:
                self.r.add(fam, "CNAME", "CNAME does not hold the domain %s" % cfg.domain)
        elif has_cname:
            self.r.add(fam, "CNAME", "a CNAME is published before cutover; the site would not be served "
                                     "from its preview address")
        if not self.base:
            self.r.notes.append("NOT CHECKED: canonical, og:url, sitemap and robots addresses "
                                "(no previewUrl or domain gives a site URL)")
            self.r.count(fam, n)
            return
        for rel in self.content_pages:
            p = self.pages[rel]
            expect = self.base + "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
            if rel == "index.html":
                expect = self.base + "/"
            for lt in p.linktags:
                if lt.get("rel", "").lower() == "canonical":
                    n += 1
                    if lt.get("href") != expect:
                        self.r.add(fam, rel, "canonical is %s, expected %s" % (lt.get("href"), expect))
            for m in p.metas:
                if m.get("property") == "og:url":
                    n += 1
                    if m.get("content") != expect:
                        self.r.add(fam, rel, "og:url is %s, expected %s" % (m.get("content"), expect))
        other = []
        if cfg.cutover and cfg.previewUrl:
            other.append(cfg.previewUrl.rstrip("/"))
        if not cfg.cutover and cfg.domain:
            other.append("https://" + cfg.domain)
        texts = [(rel, p.source) for rel, p in self.pages.items()]
        for rel in ("sitemap.xml", "robots.txt"):
            if rel in self.t.files:
                texts.append((rel, self.t.text(rel)))
        for rel, src in texts:
            n += 1
            for o in other:
                if re.search(re.escape(o) + r"(?![\w.-])", src):
                    why = "the preview address" if cfg.cutover else "the custom domain, which is not live before cutover"
                    self.r.add(fam, rel, "absolute URL to %s (%s)" % (o, why))
        locs = []
        if "sitemap.xml" in self.t.files:
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", self.t.text("sitemap.xml"), re.S)
            targets = set()
            for loc in locs:
                n += 1
                k, rest = classify(loc, self.base)
                if k != "internal":
                    self.r.add(fam, "sitemap.xml", "<loc> %s is outside %s" % (loc, self.base))
                    continue
                target, _f, problem = self.resolve("index.html", rest)
                if problem or target not in self.pages:
                    self.r.add(fam, "sitemap.xml", "<loc> %s is not a page in this build" % loc)
                else:
                    targets.add(target)
            for rel in self.content_pages:
                if rel != "404.html" and rel not in targets:
                    self.r.add(fam, rel, "page is missing from sitemap.xml")
        if "robots.txt" in self.t.files:
            n += 1
            m = re.search(r"(?im)^sitemap:\s*(\S+)", self.t.text("robots.txt"))
            if m and not m.group(1).startswith(self.base + "/"):
                self.r.add(fam, "robots.txt", "Sitemap line %s is outside %s" % (m.group(1), self.base))
        self.r.count(fam, n)

    # -- media -------------------------------------------------------------------------------
    def media(self):
        fam = "media"
        n = 0
        t = self.t
        for rel in sorted(t.files):
            low = rel.lower()
            if low.endswith(BAD_IMAGE_EXTS):
                self.r.add(fam, rel, "this image format is not shown by browsers; convert it at import")
            if low.endswith(IMAGE_EXTS):
                n += 1
                dims = images.read_dimensions(t.read(rel))
                if dims is None:
                    self.r.add(fam, rel, "the image header cannot be read")
                elif max(dims) > images.LONG_EDGE_CAP:
                    self.r.add(fam, rel, "long edge %d px is over the %d px cap" % (max(dims), images.LONG_EDGE_CAP))
        for rel, p in sorted(self.pages.items()):
            for im in p.imgs:
                n += 1
                src = im["src"]
                if src is None or src == "":
                    self.r.add(fam, rel, "an <img> with no src")
                    continue
                if im["alt"] is None:
                    self.r.add(fam, rel, "<img src=%s> has no alt attribute (use alt=\"\" if decorative)" % src)
                elif re.search(r"\.(jpe?g|png|gif|webp|svg|heic)\s*$", im["alt"], re.I) or \
                        re.match(r"^(IMG|DSC|PXL|P)[_-]?\d{3,}", im["alt"]):
                    self.r.add(fam, rel, "alt text %r is a file name" % im["alt"])
                k, rest = classify(src, self.base)
                if k not in ("rel", "internal"):
                    continue
                target, _f, problem = self.resolve(rel, rest if k == "internal" else src)
                if problem or target not in t.files:
                    continue
                dims = images.read_dimensions(t.read(target))
                if dims is None:
                    if not target.lower().endswith(".svg"):
                        self.r.add(fam, rel, "<img src=%s>: the image header cannot be read" % src)
                    continue
                for attr, want in (("width", dims[0]), ("height", dims[1])):
                    v = im[attr]
                    if v is None or not str(v).isdigit():
                        self.r.add(fam, rel, "<img src=%s> has no %s attribute (layout shift)" % (src, attr))
                    elif int(v) != want:
                        self.r.add(fam, rel, "<img src=%s> %s=%s but the file is %d" % (src, attr, v, want))
                if im["srcset"]:
                    if not im["sizes"]:
                        self.r.add(fam, rel, "<img src=%s> has a srcset but no sizes attribute" % src)
                    for u, d in parse_srcset(im["srcset"]):
                        kk, rr = classify(u, self.base)
                        tt, _f, pr = self.resolve(rel, rr if kk == "internal" else u) \
                            if kk in ("rel", "internal") else (None, "", "skip")
                        if pr or tt not in t.files:
                            continue
                        dd = images.read_dimensions(t.read(tt))
                        m = re.match(r"^(\d+)w$", d)
                        if not m:
                            self.r.add(fam, rel, "srcset candidate %s has no width descriptor" % u)
                        elif dd and int(m.group(1)) != dd[0]:
                            self.r.add(fam, rel, "srcset says %s is %sw but the file is %d wide"
                                       % (u, m.group(1), dd[0]))
            for fr in p.iframes:
                n += 1
                src = fr.get("src", "")
                host = urlsplit(src).netloc.lower()
                if not fr.get("title"):
                    self.r.add(fam, rel, "<iframe src=%s> has no title" % src)
                if host not in VIDEO_HOSTS:
                    self.r.add(fam, rel, "<iframe> from %s, which is not a recognised video host" % (host or src))
        self.r.count(fam, n)

    # -- unfinished --------------------------------------------------------------------------
    _UNFINISHED = re.compile(
        r"\b(?i:lorem ipsum|coming soon|under construction|your text here|insert text here)\b|"
        r"\b(?:TODO|FIXME|TBD|XXX)\b")

    def unfinished(self):
        fam = "unfinished"
        for rel, p in sorted(self.pages.items()):
            text = " ".join([p.visible_text, p.title] + p.attr_text)
            for m in self._UNFINISHED.finditer(text):
                self.r.add(fam, rel, "unfinished marker %r in the page text" % m.group(0))
            for a in p.anchors:
                if a["href"] is not None and a["href"].strip() in ("", "#"):
                    self.r.add(fam, rel, "a link that goes nowhere (href=%r)" % a["href"])
            if rel in self.redirects:
                continue
            if p.has_noindex:
                self.r.add(fam, rel, "noindex page that is not a redirect stub (a draft left in?)")
            if not p.title.strip() or re.match(r"(?i)^\s*(untitled|document|new page)\b", p.title):
                self.r.add(fam, rel, "untitled page")
            if rel != "404.html" and not "".join(p.main_text or p.text).strip() and not p.imgs:
                self.r.add(fam, rel, "the page has no content")
        for rel in sorted(self.t.files):
            if rel.lower().endswith((".html", ".htm", ".js", ".css")):
                for m in re.finditer(r"(?i)\b(?:https?://)?(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?|file://", self.t.text(rel)):
                    self.r.add(fam, rel, "development address %r left in" % m.group(0))
                    break
        self.r.count(fam, len(self.pages))

    # -- performance and size ----------------------------------------------------------------
    def _img_cost(self, rel, im):
        """Bytes this <img> would cost on a 2x screen: its largest candidate up to 1440 wide."""
        cands = []
        for u, d in parse_srcset(im["srcset"]):
            m = re.match(r"^(\d+)w$", d)
            k, rest = classify(u, self.base)
            if k not in ("rel", "internal"):
                continue
            tgt, _f, pr = self.resolve(rel, rest if k == "internal" else u)
            if tgt and not pr and tgt in self.t.files:
                cands.append((int(m.group(1)) if m else 0, tgt))
        src = im["src"]
        if src:
            k, rest = classify(src, self.base)
            if k in ("rel", "internal"):
                tgt, _f, pr = self.resolve(rel, rest if k == "internal" else src)
                if tgt and not pr and tgt in self.t.files:
                    d = images.read_dimensions(self.t.read(tgt))
                    cands.append((d[0] if d else 0, tgt))
        if not cands:
            return None, 0
        under = [c for c in cands if c[0] <= 1440] or [min(cands)]
        w, tgt = max(under)
        return tgt, self.t.files[tgt]

    def performance(self):
        fam = "performance"
        b = self.cfg.effective_budgets()
        n = 0
        over_kb = b["sizeCopyOverKB"]
        for rel in sorted(self.t.files):
            if not rel.lower().endswith(IMAGE_EXTS) or re.search(r"-\d+w\.\w+$", rel):
                continue
            n += 1
            d = images.read_dimensions(self.t.read(rel))
            if not d:
                continue
            stem, ext = os.path.splitext(rel)
            has_copy = any(f.startswith(stem + "-") and re.match(r"-\d+w" + re.escape(ext) + "$", f[len(stem):])
                           for f in self.t.files)
            if images.plan_copies(d[0], self.t.files[rel], over_kb) and not has_copy:
                self.r.add(fam, rel, "%d KB is over the %s KB budget and the image has no size copies "
                                     "(<stem>-<width>w.<ext>); import it again" % (self.t.files[rel] // 1024, over_kb))
        first_cap = b["firstViewMaxMB"] * 1024 * 1024
        page_cap = b["pageImagesMaxMB"] * 1024 * 1024
        for rel, p in sorted(self.pages.items()):
            n += 1
            seen, total, first, first_seen = set(), 0, 0, set()
            for i, im in enumerate(p.imgs):
                tgt, cost = self._img_cost(rel, im)
                if tgt is None:
                    continue
                if tgt not in seen:
                    seen.add(tgt)
                    total += cost
                if (i == 0 or (im["loading"] or "").lower() != "lazy") and tgt not in first_seen:
                    first_seen.add(tgt)
                    first += cost
            if first > first_cap:
                self.r.add(fam, rel, "first-view images weigh %.2f MB at 2x, over the %s MB budget"
                           % (first / 1048576.0, b["firstViewMaxMB"]))
            if total > page_cap:
                self.r.add(fam, rel, "images on the page weigh %.2f MB at 2x, over the %s MB budget"
                           % (total / 1048576.0, b["pageImagesMaxMB"]))
        self.r.count(fam, n)

    def size(self):
        fam = "size"
        total = sum(self.t.files.values())
        cap = self.cfg.effective_budgets()["treeMaxMB"] * 1024 * 1024
        self.r.count(fam, len(self.t.files))
        if total > cap:
            self.r.add(fam, ".", "the published tree is %.1f MB, over the %s MB budget (Pages allows 1 GB)"
                       % (total / 1048576.0, self.cfg.effective_budgets()["treeMaxMB"]))
        for rel, sz in sorted(self.t.files.items()):
            if sz >= 50 * 1024 * 1024:
                self.r.add(fam, rel, "file is %.0f MB; GitHub warns at 50 MB and refuses 100 MB" % (sz / 1048576.0))

    # -- head --------------------------------------------------------------------------------
    def head(self):
        fam = "head"
        titles = {}
        for rel in self.content_pages:
            p = self.pages[rel]
            metas = p.metas
            if not any(m.get("charset", "").lower() == "utf-8" or
                       "charset=utf-8" in m.get("content", "").lower() for m in metas):
                self.r.add(fam, rel, "no <meta charset=\"utf-8\">")
            vp = [m for m in metas if m.get("name", "").lower() == "viewport"]
            if not vp or "width=device-width" not in vp[0].get("content", ""):
                self.r.add(fam, rel, "no <meta name=\"viewport\" content=\"width=device-width, ...\">")
            title = p.title.strip()
            if not title:
                self.r.add(fam, rel, "empty <title>")
            else:
                titles.setdefault(title, []).append(rel)
            desc = [m for m in metas if m.get("name", "").lower() == "description"]
            if not desc or not desc[0].get("content", "").strip():
                self.r.add(fam, rel, "no meta description")
            if self.base:
                have = dict((m.get("property"), m.get("content")) for m in metas if m.get("property"))
                if not any(lt.get("rel", "").lower() == "canonical" for lt in p.linktags):
                    self.r.add(fam, rel, "no canonical link")
                for prop in ("og:title", "og:description", "og:url"):
                    if not have.get(prop):
                        self.r.add(fam, rel, "no %s meta" % prop)
        for title, rels in sorted(titles.items()):
            if len(rels) > 1:
                self.r.add(fam, rels[0], "the title %r is also used by %s" % (title, ", ".join(rels[1:])))
        self.r.count(fam, len(self.content_pages))

    # -- nav ---------------------------------------------------------------------------------
    def nav(self):
        fam = "nav"
        home = self.pages.get("index.html")
        if home is None:
            return

        def targets(rel, p):
            out = set()
            for h in (p.nav_hrefs or []):
                k, rest = classify(h, self.base)
                if k in ("rel", "internal"):
                    t, _f, pr = self.resolve(rel, rest if k == "internal" else h)
                    out.add(t if t and not pr else "?" + h)
                else:
                    out.add(h)
            return out
        want = targets("index.html", home)
        if not want:
            self.r.add(fam, "index.html", "the home page has no primary navigation")
        for rel in self.content_pages:
            p = self.pages[rel]
            links_home = False
            for a in p.anchors:
                if a["href"] is None:
                    continue
                k, rest = classify(a["href"], self.base)
                if k in ("rel", "internal"):
                    t, _f, pr = self.resolve(rel, rest if k == "internal" else a["href"])
                    if t == "index.html" and not pr:
                        links_home = True
                        break
            if not links_home:
                self.r.add(fam, rel, "the page does not link to the home page")
            if rel == "404.html":
                continue
            got = targets(rel, p)
            if p.nav_hrefs is None:
                self.r.add(fam, rel, "the page has no <nav>")
            elif got != want:
                missing = sorted(want - got)
                extra = sorted(got - want)
                self.r.add(fam, rel, "primary nav differs from the home page's (missing %s; extra %s)"
                           % (missing or "nothing", extra or "nothing"))
        self.r.count(fam, len(self.content_pages))

    # -- basepath ----------------------------------------------------------------------------
    def basepath(self):
        fam = "basepath"
        n = 0
        host = urlsplit(self.base).netloc.lower() if self.base else None
        sp = self.site_path()
        for rel, p in sorted(self.pages.items()):
            n += 1
            if p.base is not None:
                self.r.add(fam, rel, "a <base> tag changes how every relative link resolves")
        for rel, kind, url in getattr(self, "all_refs", []):
            k, rest = classify(url, self.base)
            if k == "rootabs":
                self.r.add(fam, rel, "root-absolute %s %s breaks under the /<repo>/ preview path" % (kind, url))
            elif k == "external":
                u = urlsplit(url)
                if u.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or url.lower().startswith("file:"):
                    self.r.add(fam, rel, "development origin %s" % url)
                elif host and u.netloc.lower() == host and sp and not (u.path == sp or u.path.startswith(sp + "/")):
                    self.r.add(fam, rel, "absolute URL %s is on this site's host but outside %s" % (url, sp))
            elif k == "special" and url.lower().startswith("file:"):
                self.r.add(fam, rel, "file: URL %s" % url)
        for rel in sorted(self.t.files):
            low = rel.lower()
            if low.endswith(".js"):
                n += 1
                for m in re.finditer(r"""(?:src|href|fetch|url|location(?:\.href)?)\s*[=(:]\s*['"](/[A-Za-z0-9_.-][^'"]*)['"]""",
                                     self.t.text(rel)):
                    self.r.add(fam, rel, "script uses the root-absolute path %s" % m.group(1))
            elif low.endswith(".css"):
                n += 1
        self.r.count(fam, n)

    # -- privacy -----------------------------------------------------------------------------
    def privacy(self):
        fam = "privacy"
        cfg = self.cfg
        t = self.t
        allowed = set(e.lower() for e in cfg.publicEmails)
        terms = [(x, norm_for_terms(x)) for x in cfg.privateTerms if x.strip()]
        n = 0

        def scan_terms(where, text, label=None):
            if not terms:
                return
            forms = [norm_for_terms(text), norm_for_terms(html.unescape(text)),
                     norm_for_terms(unquote(text))]
            for raw, nt in terms:
                if any(nt in f for f in forms):
                    self.r.add(fam, where, "contains the private term %s%s" % (mask(raw), (" " + label) if label else ""))

        def scan_shapes(where, text, label=""):
            for hit in phone_hits(text):
                self.r.add(fam, where, "phone number %s%s" % (mask(hit), label))
            for hit in street_hits(text):
                self.r.add(fam, where, "street address %s%s" % (mask(hit), label))

        def scan_emails(where, text, label=""):
            for e in email_hits(text):
                if e.lower() not in allowed:
                    self.r.add(fam, where, "email address %s is not in publicEmails%s" % (mask(e), label))

        for rel in sorted(t.files):
            n += 1
            scan_terms(rel, rel, "(in the file name)")
            scan_shapes(rel, rel.replace("/", " "), " (in the file name)")
            scan_emails(rel, rel, " (in the file name)")
        sidecar = None
        if self.repo and cfg.resume and cfg.resume.get("pdf"):
            sc = os.path.join(self.repo, cfg.resume["pdf"] + ".json")
            if os.path.isfile(sc):
                try:
                    with open(sc, "r", encoding="utf-8") as fh:
                        sidecar = json.load(fh)
                except (OSError, ValueError):
                    sidecar = None
        titles = set(p.title.strip() for p in self.pages.values())
        for rel in sorted(t.files):
            low = rel.lower()
            data = None
            if low.endswith((".html", ".htm")):
                p = self.pages[rel]
                text = html.unescape(" ".join([p.visible_text] + p.attr_text))
                scan_terms(rel, p.source)
                scan_terms(rel, p.fused_text, "(text split across tags)")
                scan_shapes(rel, text)
                scan_emails(rel, p.source)
                scan_emails(rel, text)
                for a in p.anchors:
                    h = (a["href"] or "").strip()
                    if h.lower().startswith("tel:"):
                        self.r.add(fam, rel, "tel: link %s" % mask(h[4:]))
            elif low.endswith(".pdf"):
                self._privacy_pdf(rel, allowed, scan_terms, scan_shapes, scan_emails, sidecar, titles)
            elif low.endswith(IMAGE_EXTS):
                for kind, detail in images.inspect_metadata(t.read(rel)):
                    self.r.add(fam, rel, "hidden image metadata (%s): %s" % (kind, detail))
            elif low.endswith(SITE_TEXT_EXTS) or posixpath.basename(rel) in ("CNAME",):
                text = t.text(rel)
                scan_terms(rel, text)
                scan_emails(rel, text)
                if low.endswith((".txt", ".svg")):
                    scan_shapes(rel, html.unescape(re.sub(r"<[^>]+>", " ", text)) if low.endswith(".svg") else text)
        self.r.count(fam, n)
        self.r.notes.append("privacy: images carry text the gate cannot see; every public image is in the "
                            "judgement half's coverage set, never in a read count")

    def _privacy_pdf(self, rel, allowed, scan_terms, scan_shapes, scan_emails, sidecar, titles):
        fam = "privacy"
        data = self.t.read(rel)
        res = pdftext.read_pdf(data)
        reasons = list(res.reasons)
        status_read = res.read
        # metadata is judged even when the text is not read
        info, xmp = res.info, res.xmp
        if info.get("Author"):
            self.r.add(fam, rel, "PDF metadata names an author (%s)" % mask(info["Author"]))
        cr = info.get("Creator")
        if cr and not any(g in cr.lower() for g in KNOWN_GENERATORS):
            self.r.add(fam, rel, "PDF metadata Creator %r is not a known generator" % cr)
        ti = info.get("Title")
        if ti and ti.strip() not in titles:
            self.r.add(fam, rel, "PDF metadata Title %r is not the title of any page in this build" % ti)
        for k, v in list(info.items()) + [("xmp:" + a, b) for a, b in xmp.items()]:
            scan_terms(rel, v, "(PDF metadata %s)" % k)
            scan_shapes(rel, v, " (PDF metadata %s)" % k)
            scan_emails(rel, v, " (PDF metadata %s)" % k)
        for k in ("author", "creator"):
            if xmp.get(k):
                self.r.add(fam, rel, "PDF XMP metadata names a %s (%s)" % (k, mask(xmp[k])))
        # rule 2 for the PDF the plugin printed itself
        sha = hashlib.sha256(data).hexdigest()
        printed = bool(sidecar) and sidecar.get("pdf_sha256") == sha
        resume_cfg = self.cfg.resume
        is_resume_slot = bool(resume_cfg and resume_cfg.get("pdf")) and \
            rel == "resume/" + posixpath.basename(resume_cfg["pdf"])
        if status_read and is_resume_slot:
            if not printed:
                status_read = False
                reasons.append("resume PDF has no sidecar proving it against its source (rule 2)")
            else:
                page = self.pages.get("resume/index.html")
                src = " ".join(page.main_text) if page else ""
                cov = pdftext.word_coverage(src, res.text)
                # the page's text has the download-link caption and headings the print may omit
                # only if the author's print stylesheet hides them; the bound is the design's 95%
                if cov is None or cov < 0.95:
                    status_read = False
                    reasons.append("rule 2: the PDF's text covers %s of the resume page's words (needs 95%%)"
                                   % ("none" if cov is None else "%d%%" % int(cov * 100)))
        if res.text:
            for form in res.search_forms()[:1]:
                scan_shapes(rel, form, " (in the PDF text)")
                scan_emails(rel, form, " (in the PDF text)")
            for form in res.search_forms():
                scan_terms(rel, form, "(in the PDF text)")
        if status_read:
            self.r.pdfs_read += 1
        else:
            self.r.not_read.append(Finding("privacy", rel, "NOT READ: " + "; ".join(reasons), "not-read"))

    # -- run ---------------------------------------------------------------------------------
    def run(self):
        self.structure()
        self.links()      # fills all_refs and the referenced set before reachable/basepath
        self.comments()
        self.reachable()
        self.domain()
        self.media()
        self.unfinished()
        self.performance()
        self.head()
        self.nav()
        self.basepath()
        self.size()
        self.privacy()
        if self.pages:
            for fam in FAMILIES:
                if self.r.checked.get(fam, 0) == 0 and fam not in ("media",):
                    self.r.add("structure", ".", "the %s family examined nothing" % fam)
        seen = set()
        unique = []
        for f in sorted(self.r.findings, key=lambda f: f.sort_key()):
            key = (f.family, f.path, f.message)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        self.r.findings = unique
        self.r.not_read.sort(key=lambda f: f.path)
        return self.r


def check_tree(out_dir, cfg, repo=None):
    return Checker(Tree(out_dir), cfg, repo).run()


# ---------------------------------------------------------------------------------------------
# the source shape scan (CI half of design 8.2)
# ---------------------------------------------------------------------------------------------

SKIP_DIRS = (".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache")


def _file_allowed(path, kind):
    p = path.replace(os.sep, "/")
    for glob, kinds, _why in ALLOW_FILES:
        if kind in kinds and (fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob)):
            return True
    return False


def _email_allowed_in(path, email):
    p = path.replace(os.sep, "/")
    e = email.lower()
    for glob, addr, _why in ALLOW_EMAILS:
        if e == addr.lower() and (fnmatch.fnmatch(p, glob) or fnmatch.fnmatch(p, "*/" + glob)):
            return True
    return False


def scan_source(paths):
    rep = Report()
    files = []
    for top in paths:
        if os.path.isfile(top):
            files.append(top)
            continue
        if not os.path.isdir(top):
            rep.add("privacy", top, "scan path does not exist")
            continue
        for d, dirs, names in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for fn in sorted(names):
                files.append(os.path.join(d, fn))
    rep.count("privacy", len(files))
    n_text = n_img = 0
    for path in files:
        low = path.lower()
        shown = path.replace(os.sep, "/")
        try:
            with open(path, "rb") as fh:
                data = fh.read(40 * 1024 * 1024)
        except OSError as e:
            rep.add("privacy", shown, "cannot read: %s" % (e.strerror or e))
            continue
        if low.endswith(IMAGE_EXTS):
            n_img += 1
            for kind, detail in images.inspect_metadata(data):
                if kind in ("gps", "owner", "serial") and not _file_allowed(path, "image-" + kind):
                    rep.add("privacy", shown, "image carries EXIF %s (%s)" % (kind, detail))
        elif low.endswith(".pdf"):
            res = pdftext.read_pdf(data)
            if res.read:
                rep.pdfs_read += 1
            else:
                rep.not_read.append(Finding("privacy", shown, "NOT READ: " + "; ".join(res.reasons), "not-read"))
            _scan_text_shapes(rep, path, shown, res.text + " " + " ".join(res.info.values()))
        elif low.endswith(TEXT_EXTS):
            n_text += 1
            _scan_text_shapes(rep, path, shown, data.decode("utf-8", "replace"))
        else:
            rep.skipped.append(shown)
    rep.notes.append("scanned %d file(s): %d text, %d image; %d skipped (other types)"
                     % (len(files), n_text, n_img, len(rep.skipped)))
    if not files:
        rep.add("privacy", ",".join(paths), "the scan found no files: nothing was checked")
    rep.findings.sort(key=lambda f: f.sort_key())
    return rep


def _scan_text_shapes(rep, path, shown, text):
    for hit in phone_hits(text):
        if phone_allowed_reserved(hit) or _file_allowed(path, "phone"):
            continue
        rep.add("privacy", shown, "phone number %s outside the reserved 555-01xx range" % mask(hit))
    if not _file_allowed(path, "street"):
        for hit in street_hits(text):
            rep.add("privacy", shown, "street address %s" % mask(hit))
    for e in email_hits(text):
        if not email_domain_allowed(e) and not _file_allowed(path, "email") and not _email_allowed_in(path, e):
            rep.add("privacy", shown, "email address %s outside the reserved domains" % mask(e))


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def render_text(rep, report_links, header):
    lines = []
    for f in rep.findings:
        lines.append("%-11s %s: %s" % (f.family, f.path, f.message))
    lines.append("PDFs: %d read, %d NOT READ (listed below)" % (rep.pdfs_read, len(rep.not_read)))
    for f in rep.not_read:
        lines.append("NOT READ   %s: %s" % (f.path, f.message[len("NOT READ: "):]))
    if rep.not_read:
        lines.append("NOT CHECKED: %d PDF(s) could not be read and are listed for privacy-guard" % len(rep.not_read))
    for note in rep.notes:
        lines.append(note)
    if rep.checked:
        lines.append("checked: " + " · ".join("%s %d" % (k, rep.checked[k]) for k in FAMILIES if k in rep.checked))
    if report_links:
        lines.append("external links (%d):" % len(rep.externals))
        for url in sorted(rep.externals):
            lines.append("  %s  <- %s" % (url, ", ".join(sorted(rep.externals[url]))))
    fams = sorted(set(f.family for f in rep.findings), key=lambda x: FAMILIES.index(x) if x in FAMILIES else 99)
    lines.append("%s: %s (%d finding(s)%s)" % (header, "FAIL" if rep.findings else "PASS", len(rep.findings),
                                                " in " + ", ".join(fams) if fams else ""))
    return "\n".join(lines)


def render_json(rep, report_links):
    out = [json.dumps(f.to_dict(), sort_keys=True) for f in rep.findings]
    out += [json.dumps(f.to_dict(), sort_keys=True) for f in rep.not_read]
    if report_links:
        for url in sorted(rep.externals):
            out.append(json.dumps({"level": "report", "kind": "external-link", "url": url,
                                   "pages": sorted(rep.externals[url])}, sort_keys=True))
    out.append(json.dumps({"level": "summary", "findings": len(rep.findings),
                           "pdfsRead": rep.pdfs_read, "pdfsNotRead": len(rep.not_read),
                           "checked": rep.checked, "notes": rep.notes}, sort_keys=True))
    return "\n".join(out)


def not_read_pdfs(out_dir, repo):
    """The built PDFs the privacy family could NOT read (design 7.1), as sorted relative paths.
    The seam review_record.py's coverage packet reads (dev #835): every path listed here must be
    in the privacy agent's coverage, because no pattern looked inside it."""
    repo = os.path.abspath(repo)
    cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    rep = check_tree(out_dir, cfg, repo)
    return sorted({f.path for f in rep.not_read})


def build_parser():
    ap = argparse.ArgumentParser(prog="check_site.py", allow_abbrev=False, add_help=True,
                                 description="Check a built site. There is no way to skip a family.")
    ap.add_argument("--repo", default=".", help="the dev repo (site/site.json lives here)")
    ap.add_argument("--out", default=None, help="check this existing build instead of building HEAD")
    ap.add_argument("--json", action="store_true", help="one JSON record per line")
    ap.add_argument("--report", action="store_true", help="also list the external links")
    ap.add_argument("--scan-source", nargs="+", default=None, metavar="PATH",
                    help="shape-scan a SOURCE tree (phones, addresses, emails, EXIF GPS) and exit")
    return ap


def main(argv=None):
    rc = platform_check.windows_refusal_rc("check_site.py")
    if rc is not None:
        return rc
    args = build_parser().parse_args(argv)
    if args.scan_source is not None:
        rep = scan_source(args.scan_source)
        print(render_json(rep, False) if args.json else render_text(rep, False, "check_site --scan-source"))
        return 1 if rep.findings else 0
    repo = os.path.abspath(args.repo)
    cfg_path = os.path.join(repo, "site", "site.json")
    try:
        cfg = siteconfig.load(cfg_path)
    except (siteconfig.SiteConfigError, OSError) as e:
        print("check_site: cannot read %s: %s" % (cfg_path, e))
        return 2
    tmp = None
    out = args.out
    if out is None:
        import build
        tmp = tempfile.mkdtemp(prefix="ss-check-")
        out = os.path.join(tmp, "dist")
        try:
            build.publish_build(repo, out)
        except build.BuildError as e:
            print("build refused: %s" % e)
            return 1
    try:
        rep = check_tree(out, cfg, repo)
    finally:
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    print(render_json(rep, args.report) if args.json else render_text(rep, args.report, "check_site"))
    return 1 if rep.findings else 0


if __name__ == "__main__":
    sys.exit(main())
