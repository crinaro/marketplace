"""adoption.tokens -- resume and paper size, and the template's local tokens as the build's own.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE PAPER SIZE (named change S9(a); amended for 0.3.0, design-site-fidelity section 5.5). `resume.paper` is
read from the MediaBox of the repo's existing resume PDF (612x792 is Letter, 595x842 is A4, a few points of
tolerance, either orientation). A PDF whose boxes cannot be read as plain text (an object-stream file) means
adopt REPORTS that it needs the answer, and `apply` refuses until `adopt.py paper Letter|A4` is run. Letter is
never assumed. A site with NO resume PDF is not asked: apply writes `"pdf": null` and no paper (schema 3), since
no page is printed to a paper size.
"""

import html
import html.parser
import posixpath
import re

from building import tokens  # noqa: E402
from contentmodel import errors, frontmatter, keytables  # noqa: E402

_BOX = re.compile(rb"/MediaBox\s*\[\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\]")


def _paper_of(w, h):
    a, b = sorted((w, h))
    if abs(a - 612) <= 5 and abs(b - 792) <= 5:
        return "Letter"
    if abs(a - 595.3) <= 5 and abs(b - 841.9) <= 5:
        return "A4"
    return None


def paper_from_pdf(data):
    """'Letter' or 'A4' from the PDF's plain-text MediaBox entries, else None (never a guess)."""
    sizes = set()
    for m in _BOX.finditer(data):
        x1, y1, x2, y2 = [float(v) for v in m.groups()]
        sizes.add(_paper_of(abs(x2 - x1), abs(y2 - y1)))
    if len(sizes) == 1 and None not in sizes:
        return sizes.pop()
    return None


def detect_resume(tree):
    md = pdf = None
    for cand in ("content/resume/resume.md", "content/resume.md"):
        if tree.exists(cand):
            md = cand
            break
    if md:
        pdf_c = posixpath.splitext(md)[0] + ".pdf"
        if tree.exists(pdf_c):
            pdf = pdf_c
    paper = None
    if pdf:
        paper = paper_from_pdf(tree.read(pdf))
    return {"md": md, "pdf": pdf, "paper": paper,
            "source": ("the MediaBox of %s" % pdf) if paper else None,
            "needsAnswer": bool(md) and bool(pdf) and paper is None}      # no PDF: no paper size to ask about (F4)


_OLD_TOKEN = re.compile(r"^([A-Za-z][A-Za-z0-9]*?)Link(?::([A-Za-z0-9_.-]+))?$")


def portfolio_folders(tree):
    names = set()
    for p in tree.paths():
        parts = p.split("/")
        if parts[0] == "content" and len(parts) >= 3:
            f = parts[1]
            if f in keytables.RESERVED_PORTFOLIO_NAMES or f.startswith("_"):
                continue
            if f == "work" or (len(parts) == 3 and parts[2] == "page.md"):
                names.add(f)
    return sorted(names)


# `<a href="{{resumeLink}}">TEXT</a>`: the anchor whose href is exactly the old resume token (section 6.1)
_RESUME_ANCHOR = re.compile(r"<a\b([^>]*?)\bhref=([\"'])\{\{\s*resumeLink\s*\}\}\2([^>]*)>((?:(?!<a\b).)*?)</a>",
                            re.S | re.I)


def section_for_resume(inner):
    """The page section adopt writes around a resume anchor, for the inventory to show."""
    return "{{#page:resume}}%s{{/page}}" % inner


_HOME_LOCAL = re.compile(r"^home([A-Z][A-Za-z0-9]*)$")
_PLAIN_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.;:?!()/%-]*$")
_SOLE_P = re.compile(r"<p>\s*\{\{\s*homeIntro\s*\}\}\s*</p>")


def home_feed(tree):
    """(front matter dict, body text) of the person's home copy, `content/home/index.md` or `content/home.md`, or
    None when there is none or it cannot be read (then no local home token is rewritten: it stays unknown and the
    build refuses it, `you decide`). Read here only to decide what a local `{{home<Part>}}` token means."""
    for path in ("content/home/index.md", "content/home.md"):
        if tree.exists(path):
            try:
                return frontmatter.parse_front_matter(frontmatter.decode_text(tree.read(path), path), path)
            except errors.ContentError:
                return None
    return None


_ANCHOR_HREF_OPEN = re.compile(r"<a\b[^<>]*?\bhref\s*=\s*([\"'])$", re.I | re.S)
_ANCHOR_OPEN = re.compile(r"<a\b", re.I)
_ANCHOR_CLOSE = re.compile(r"</a\s*>", re.I)


def link_token_context(m):
    """Where a regex match `m` of a token stands in the text it was found in (dev #889): `href` when it is an
    `<a>` tag's WHOLE `href` value (quote, token, the same quote), `tag` when it is anywhere else inside a tag (another
    attribute, or part of an href), `anchor` when it is the content of an open `<a>`, else `text`. A `{{<folder>Link}}`
    token means a URL only in `href`; in `text` the template's builder rendered something else there (a whole anchor)."""
    s, a, b = m.string, m.start(), m.end()
    lt, gt = s.rfind("<", 0, a), s.rfind(">", 0, a)
    if lt > gt:
        q = _ANCHOR_HREF_OPEN.search(s[lt:a])
        return "href" if (q and s[b:b + 1] == q.group(1)) else "tag"
    before = s[:a]
    return "anchor" if len(_ANCHOR_OPEN.findall(before)) > len(_ANCHOR_CLOSE.findall(before)) else "text"


def link_token_folder(token, folders):
    """The portfolio folder an old `{{<folder>Link}}` token (or `{{<folder>Link:<slug>}}`) names, or None."""
    m = tokens.TOKEN_RE.fullmatch(token.strip())
    if not m:
        return None
    om = _OLD_TOKEN.match(m.group(1) + (":" + m.group(2) if m.group(2) else ""))
    norm = dict((re.sub(r"[-_]", "", f).lower(), f) for f in folders)
    return norm.get(om.group(1).lower()) if om else None


def link_step_reason(token, folder, data):
    """Why adopt did not rewrite an old `{{<folder>Link}}` token the inventory lists as a step (dev #889)."""
    if ":" in token:
        return "it names a piece, and no label for that piece is known"
    if folder not in site_json_labels(data):
        return ("site/site.json has no work.label" if folder == "work"
                else "site/site.json states no label for the %s portfolio" % folder)
    return "it is inside a tag or the text of another anchor"


def section_for_link(folder, label):
    """The page section adopt writes around a bare `{{<folder>Link}}` the template's builder rendered as a whole anchor
    (dev #889): an anchor that is there when the page is built and gone when it is not."""
    return '{{#page:%s}}<a href="{{link:%s}}">%s</a>{{/page}}' % (folder, folder, html.escape(label, quote=False))


def site_json_labels(data):
    """{folder: label} for the portfolios whose label `site/site.json` states: `work.label`, the one portfolio the file
    configures. A portfolio the file says nothing about has no label here (its label is `page.md`'s, or the folder's name
    in title case, and adopt does not guess which one the person's builder printed)."""
    work = (data or {}).get("work") if isinstance(data, dict) else None
    label = work.get("label") if isinstance(work, dict) else None
    return {"work": label.strip()} if isinstance(label, str) and label.strip() else {}


# The template's home tokens as the plugin's home parts (design 8 H1), tried BEFORE `_OLD_TOKEN`'s `<x>Link` reading: a
# `{{contactLink}}` is the home's `links`, never a link to a portfolio named `contact`. Offered only when `homeKeys` made the
# home page (`home_rows`), and in a `site/src` page, never the layout (the layout refuses a home part).
HOME_TOKEN_ROWS = (("homeEyebrow", "home:eyebrow"), ("homeHeadline", "home:title"), ("homeRole", "home:role"),
                   ("showcase", "home:showcase"), ("stats", "home:stats"), ("endorsement", "home:endorsement"),
                   ("feed", "home:feed"), ("homeContact", "home:reach"), ("contactLink", "home:links"))


def rewrite_tokens(text, folders, layout=False, home=None, frozen=None, labels=None, home_rows=False, home_samples=False):
    """(new text, [(old, new)], [unknown tokens]). Old site-specific `{{<folder>Link}}` forms become
    `{{link:<folder>}}` only where the token is an `<a>` tag's whole `href` value (dev #889); a BARE one (in text, as
    `<nav>{{workLink}}</nav>`) was rendered by the template's builder as a whole anchor, so with the portfolio's label
    in `labels` (`site_json_labels`) it becomes `{{#page:<folder>}}<a href="{{link:<folder>}}">LABEL</a>{{/page}}`, and
    without one, or anywhere else (another attribute, the text of an anchor), it is left as written and listed as
    unknown, a step for the person, never a silent rename; an anchor whose href is exactly `{{resumeLink}}` becomes a
    `{{#page:resume}}` section (a link that is there when the resume is built and gone when it is not); anything else
    the plugin's build would refuse is listed, never guessed.

    `home` is `home_feed(tree)` (design-site-fidelity section 6.1, C1): a local `{{home<Part>}}` token in a
    site/src page names a part of the home copy, and becomes `{{home:<part>}}` when the copy holds that part
    (a `title` or `description` key, `photo`, `endorsement`, `contact`). `{{homeIntro}}` is the intro: it is
    `{{home:intro}}` only when it is alone in a `<p>` and the copy's intro is one plain line, which the build
    renders as that same paragraph; anywhere else (an attribute, a longer sentence) it is FROZEN, replaced by
    the first line of the copy as escaped text, which is what a builder writes there. A frozen token is
    appended to `frozen` as (old, new): it does not update when the copy changes, and parity still measures
    the page. A token the copy cannot feed stays unknown."""
    norm = dict((re.sub(r"[-_]", "", f).lower(), f) for f in folders)
    changes, unknown = [], []
    frozen = frozen if frozen is not None else []

    def anchor(m):
        old = m.group(0)
        new = section_for_resume('<a%shref=%s{{link:resume}}%s%s>%s</a>' % (
            m.group(1), m.group(2), m.group(2), m.group(3), m.group(4)))
        changes.append((old, new))
        return new
    text = _RESUME_ANCHOR.sub(anchor, text)
    meta, body = home if home is not None else ({}, "")
    first_line = (body.strip().split("\n")[0].strip() if body.strip() else "")
    plain_intro = bool(first_line) and body.strip() == first_line and bool(_PLAIN_LINE.match(first_line))
    if home is not None and not layout and plain_intro:
        def whole_p(m):
            changes.append((m.group(0), "{{home:intro}}"))
            return "{{home:intro}}"
        text = _SOLE_P.sub(whole_p, text)

    def sub(m):
        # the token syntax and what each token is come from the build (`build.TOKEN_RE`, `token_known`):
        # a section marker `{{#page:..}}` is not a token to the build either, so it never reaches here
        name, arg = m.group(1), m.group(2)
        tok = name + (":" + arg if arg else "")
        if home_rows and not layout and not arg:
            row = dict(HOME_TOKEN_ROWS)
            if home_samples:
                row["featured"] = "home:samples"            # the template's reference list: the plugin's `samples`
            if name in row and not (name in ("feed", "endorsement", "stats", "showcase") and False):
                new = "{{%s}}" % row[name]
                changes.append((m.group(0), new))
                return new
        if tokens.token_known(name, layout):
            return m.group(0)
        hm = _HOME_LOCAL.match(name) if (home is not None and not layout and not arg) else None
        if hm:
            part = hm.group(1)[0].lower() + hm.group(1)[1:]
            if part in ("title", "description", "photo", "endorsement", "contact") and meta.get(part):
                new = "{{home:%s}}" % part
                changes.append((m.group(0), new))
                return new
            if part == "intro" and first_line:
                new = html.escape(first_line, quote=True)
                changes.append((m.group(0), new))
                frozen.append((m.group(0), new))
                return new
        om = _OLD_TOKEN.match(tok)
        if om:
            f = norm.get(om.group(1).lower())
            if f:
                where = link_token_context(m)
                if where == "href":
                    new = "{{link:%s%s}}" % (f, "/" + om.group(2) if om.group(2) else "")
                    changes.append((m.group(0), new))
                    return new
                if where == "text" and not om.group(2) and (labels or {}).get(f):
                    new = section_for_link(f, labels[f])
                    changes.append((m.group(0), new))
                    return new
        unknown.append(m.group(0))
        return m.group(0)
    return tokens.TOKEN_RE.sub(sub, text), changes, unknown


def token_files(tree):
    return [p for p in tree.paths() if (p.startswith("site/src/") and p.lower().endswith((".html", ".htm")))
            or p == "site/templates/layout.html"]
