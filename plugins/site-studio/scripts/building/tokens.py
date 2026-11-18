"""The token table and the text helpers a page is expanded with: which tokens exist and where, comment
stripping, NFC, relative links between output pages."""

import posixpath
import re
import unicodedata


# ---------------------------------------------------------------- text helpers

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)

_STYLE_BLOCK = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.S | re.I)

_TOKEN = re.compile(r"\{\{\s*([A-Za-z]+)(?::([^{}\s]+))?\s*\}\}")

TOKEN_RE = _TOKEN       # the one token syntax: adopt reads it from here, so it cannot disagree with the build

# Every token the build expands, and where it is allowed (design-site-fidelity section 4.2). `_Builder.expand`
# reads this table to decide what a token is, and `adopt.py` reads it (through `token_known`) to decide what
# the build would refuse, so there is ONE rule and nothing for adopt to copy:
#   value    a text value, in every file that is token-expanded
#   nav      the site nav, in every file that is token-expanded
#   link     `{{link:<page>}}`, in every file that is token-expanded
#   featured the featured cards, in site/src pages and the layout (never a Markdown body)
#   home     `{{home:<part>}}`, a part of content/home.md, in site/src pages only (schema 3, design-site-fidelity
#            section 6.1); the argument names the part, and a part the page does not have is refused
#   layout   a value the layout alone receives
TOKEN_SCOPES = {
    "siteUrl": "value", "siteTitle": "value", "name": "value", "year": "value", "root": "value",
    "nav": "nav", "navLinks": "nav", "link": "link", "featured": "featured", "home": "home",
    "title": "layout", "pageTitle": "layout", "description": "layout", "content": "layout",
}

# The schema a token is first read at (template-fidelity 1.4, design section 3.2): below it the token is
# unknown, as it was in 0.3.x. A token not named here is read at every schema.
TOKEN_SINCE = {"navLinks": 4}

# The size-copy namings schema 3 reads IN ADDITION to `<stem>-<w>w.<ext>` (design-site-fidelity section 5.3, I-3):
# a copy sits beside its original and its file keeps its name and its public URL, so nothing is renamed and no
# image address changes. Each pattern takes (stem, extension); below schema 3 such a file is a plain media file.
SIZE_COPY_SHAPES = ((r"^%s\.w(\d+)%s$", ".wNNN"),)


def token_known(name, layout=False, schema=None):
    """True when the build expands `{{name...}}` in a page, or in the layout when `layout` is true, at
    `schema` (None: the newest the build reads, which is what every caller without a tree schema asked
    before 0.4.0). A true answer is not "it will build": `{{link}}` with no page is still refused, by the
    build, with its fix. A token a later schema added (`TOKEN_SINCE`) is unknown below it (design
    template-fidelity section 3.2, named change R4 row 8): adopt passes the converted tree's schema."""
    scope = TOKEN_SCOPES.get(name)
    if schema is not None and TOKEN_SINCE.get(name, 0) > schema:
        return False
    if scope == "home":
        return not layout        # a site/src page only: the layout refuses it (section 6.1)
    return scope is not None and (scope != "layout" or bool(layout))


_SECTION = re.compile(r"\{\{\s*#page:([^{}\s]+)\s*\}\}|\{\{\s*/page\s*\}\}")


def strip_html_comments(text):
    """HTML comments out, and CSS comments out of inline <style> blocks."""
    text = _HTML_COMMENT.sub("", text)
    return _STYLE_BLOCK.sub(lambda m: m.group(1) + _CSS_COMMENT.sub("", m.group(2)) + m.group(3), text)


def strip_css_comments(text):
    return _CSS_COMMENT.sub("", text)


def nfc(s):
    return unicodedata.normalize("NFC", s)


def _page_dir(out_path):
    """The linkable key of an output page: its directory for .../index.html, else the file."""
    if out_path == "index.html":
        return ""
    if out_path.endswith("/index.html"):
        return out_path[:-len("/index.html")]
    return out_path


def _line_of(origin, token_text, nth):
    """The 1-based line of the `nth` (from 0) occurrence of `token_text` in `origin`, the file as the person
    wrote it, or None. The page is expanded after its comments are stripped, so the position in the expanded
    text is not a line of the file; counting the identical tokens before this one finds the right one."""
    at = -1
    for _ in range(nth + 1):
        at = origin.find(token_text, at + 1)
        if at < 0:
            return None
    return origin.count("\n", 0, at) + 1


def rel_link(from_out, to_out):
    """A relative link from one output file to another page or file. Directory pages link
    to `dir/`; a file links to itself."""
    from_dir = posixpath.dirname(from_out) or "."
    target = _page_dir(to_out) or "."
    is_dir = to_out == "index.html" or to_out.endswith("/index.html")
    r = posixpath.relpath(target, from_dir)
    if r == ".":
        return "./"
    return r + "/" if is_dir else r


def _meta_title(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _meta_description(text):
    m = re.search(r"<meta\s+name=[\"']description[\"']\s+content=[\"']([^\"']*)[\"']", text, re.I)
    return m.group(1).strip() if m else None
