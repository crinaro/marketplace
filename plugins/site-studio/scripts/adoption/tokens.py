"""adoption.tokens -- resume and paper size, and the template's local tokens as the build's own.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE PAPER SIZE (named change S9(a); amended for 0.3.0, design-site-fidelity section 5.5). `resume.paper` is
read from the MediaBox of the repo's existing resume PDF (612x792 is Letter, 595x842 is A4, a few points of
tolerance, either orientation). A PDF whose boxes cannot be read as plain text (an object-stream file) means
adopt REPORTS that it needs the answer, and `apply` refuses until `adopt.py paper Letter|A4` is run. Letter is
never assumed. A site with NO resume PDF is not asked: apply writes `"pdf": null` and no paper (schema 3), since
no page is printed to a paper size.
"""

import base64
import hashlib
import html
import html.parser
import posixpath
import re
from urllib.parse import urlsplit

from building import tokens  # noqa: E402
from building.constants import RESUME_MENU_LABEL  # noqa: E402
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


# The label the plugin's own nav prints for the resume (`building.constants.RESUME_MENU_LABEL`, the default of `pagebase.resume_label`,
# which a site's `nav.labels.resume` replaces, schema 8): a bare `{{resumeLink}}` is written as exactly the anchor the nav would print
# (design-adopt-parity-2 section 7.4, dev 979 / #245; design-adopt-local-reach section 4).
RESUME_LABEL = RESUME_MENU_LABEL


def bare_resume(label=RESUME_LABEL):
    """The wrap a bare `{{resumeLink}}` becomes: `section_for_resume` of the anchor the plugin's nav prints for the resume under the
    menu word `label` (the chosen `nav.labels.resume`, else the plugin's own)."""
    return section_for_link("resume", label)      # the wrap a bare {{<folder>Link}} becomes (dev #889), for the resume

# A token in the query of a same-site stylesheet or script address (design-adopt-parity-2 section 7.4): `<link rel="stylesheet"
# href="css/site.css?v={{cssVersion}}">`, `<script src="app.js?{{build}}">`. Group 1 the tag's name, 2 the attribute's name, 3 the
# address up to the token.
_ASSET_TAG = re.compile(r"<(link|script)\b[^<>]*?\b(href|src)\s*=\s*[\"']([^\"'<>]*)$", re.I | re.S)
_STYLESHEET = re.compile(r"\brel\s*=\s*[\"']?[^\"'<>]*\bstylesheet\b", re.I)


def asset_query_token(m):
    """True when the token match `m` stands in the QUERY of a same-site stylesheet's `href` or a script's `src`, as a whole
    query value (after `?`, `=` or `&`, before `&`, `#` or the closing quote): the old builder's cache-busting version, which
    the plugin writes as `{{assetVersion}}` (section 7.4; not visible by rule U-b, the same bytes at the same path). A
    same-site address is relative or root-absolute (`/`), never `//host` or a scheme. Whether the old builder rendered it as a
    run of letters and digits is not read here: that needs the old build, which `check` does not have (U-b makes the
    query invisible either way)."""
    s, a, b = m.string, m.start(), m.end()
    lt, gt = s.rfind("<", 0, a), s.rfind(">", 0, a)
    if lt <= gt:
        return False
    tag = _ASSET_TAG.match(s, lt, a)
    if not tag or tag.end() != a:
        return False
    name, attr, url = tag.group(1).lower(), tag.group(2).lower(), tag.group(3)
    end = s.find(">", b)
    whole = s[lt:end if end > 0 else len(s)]
    if (name, attr) not in (("link", "href"), ("script", "src")) or (name == "link" and not _STYLESHEET.search(whole)):
        return False
    if "?" not in url or url[-1:] not in ("?", "=", "&") or re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", url):
        return False
    return s[b:b + 1] in ("&", "#", "'", '"')


# A whole anchor to an outside address, as the old builder wrote it where a bare token stood (section 7.4's freeze).
_WHOLE_ANCHOR = re.compile(r"^\s*<a\b[^<>]*\bhref\s*=\s*([\"'])((?:https?://|mailto:)[^\"'<>]*)\1[^<>]*>(?:(?!</?a\b).)*</a\s*>\s*$",
                           re.I | re.S)
_CONTEXT = 60          # characters of the source's own text on each side of a token, matched against the old page


def _evaluated(text, out, known):
    """`text` with the build's own tokens evaluated, as the build prints them (dev #1042): a section marker (`{{#page:X}}`,
    `{{/page}}`) prints nothing when the page `X` is one the plugin's build has (`known`), and `{{link:X}}` prints
    `rel_link(out, X/index.html)` from the page whose output path is `out`. Anything else stays as written (a token the build
    does not print here is a barrier to the context, never guessed)."""
    def marker(x):
        return "" if (x.group(1) is None or x.group(1) in known) else x.group(0)
    text = tokens._SECTION.sub(marker, text)
    if out is None:
        return text
    return tokens.TOKEN_RE.sub(lambda x: tokens.rel_link(out, x.group(2) + "/index.html")
                               if x.group(1) == "link" and x.group(2) in known else x.group(0), text)


def _window(s, a, b, out, known):
    """(before, after): the source's own text on each side of the span `s[a:b]`, as the old page prints it: the build's tokens
    evaluated (`_evaluated`), then up to the nearest token left and `_CONTEXT` characters."""
    pre, post = _evaluated(s[:a], out, known), _evaluated(s[b:], out, known)
    prev = [t.end() for t in tokens.TOKEN_RE.finditer(pre)]
    nxt = tokens.TOKEN_RE.search(post)
    return (pre[max(prev[-1] if prev else 0, len(pre) - _CONTEXT):], post[:min(nxt.start() if nxt else len(post), _CONTEXT)])


def old_spot(m, old, out=None, known=()):
    """What the old page `old` holds where the token match `m` stands, or None. The spot is found by the source's own text on
    both sides of the token, up to the next token or `_CONTEXT` characters: it must be found, and every place it is found must
    hold the same text, else None (never a guess). The text beside it is the build's own, evaluated before it is matched
    (`_evaluated`: a section marker and a `{{link:X}}` beside the token; `out`, the old page's output path, and `known`, the
    pages the plugin's build has; dev #1042). Shared by the freeze and the measured menu anchor (section 7.4)."""
    if not old:
        return None
    before, after = _window(m.string, m.start(), m.end(), out, known)
    if not before.strip() or not after.strip():
        return None
    found = set(x.group(1) for x in re.finditer(re.escape(before) + r"(.*?)" + re.escape(after), old, re.S))
    return found.pop() if len(found) == 1 else None


def frozen_anchor(m, old, own=(), out=None, known=()):
    """The whole anchor the old builder wrote where the bare token match `m` stands, or None (design-adopt-parity-2 section 7.4:
    a bare token the plugin has no token for, which the old page renders AT THAT SPOT as one whole anchor to an outside
    address, is frozen as that anchor). `old` is the text of the page the old builder published from this source; `own` the
    site's own hosts (an `http(s)` anchor to one of them is the site's, not outside; a `mailto:` is always outside). The spot
    is `old_spot`'s: found, and the same one anchor everywhere it is found, else nothing is frozen (never a guess)."""
    middle = old_spot(m, old, out, known)
    if middle is None:
        return None
    w = _WHOLE_ANCHOR.match(middle)
    if not w or (w.group(2).lower().startswith("http") and (urlsplit(w.group(2)).hostname or "").lower() in own):
        return None
    return middle


# One anchor with an `href` and nothing else, as a menu wrap writes it (`section_for_link`, `BARE_RESUME`)
_MENU_ANCHOR = re.compile(r"^\s*<a\s+href\s*=\s*([\"'])([^\"'<>]*)\1\s*>([^<>]*)</a\s*>\s*$", re.I)


def menu_anchor_measured(m, old, page, label, known=()):
    """True when the old page renders, where the bare token match `m` stands, exactly the anchor a menu wrap writes there
    (design-adopt-parity-2 section 7.4, "the template writes exactly that anchor", measured as section 7.5; dev 979): one
    `<a href="ADDRESS">LABEL</a>` with no other attribute and no markup inside, its text `label`, its address the one the
    plugin's `{{link:<page>}}` prints from that page (`building.tokens.rel_link`). `old` is `old_page`'s (text, own hosts,
    output path). Whether the plugin's build has `page` is the caller's to know. Anything else (several links, another label
    or address, an outside anchor, an ambiguous spot) or no old page is False, and the token is not wrapped."""
    if not old or len(old) < 3 or not old[2]:
        return False
    middle = old_spot(m, old[0], old[2], known)
    w = _MENU_ANCHOR.match(middle) if middle is not None else run_anchor(m, old[0], old[2], known)
    if not w:
        return False
    return html.unescape(w.group(3)) == label and html.unescape(w.group(2)) == tokens.rel_link(old[2], page + "/index.html")


_ADJACENT = re.compile(r"^\s*$")


def _is_link_token(t):
    """True for a template link token (`{{<folder>Link}}`, `{{<folder>Link:<slug>}}`): the only tokens that stand for one menu
    anchor in a run. A token the build knows (`{{link:X}}`, `{{nav}}`) is never a member of one (dev #1042)."""
    name, arg = t.group(1), t.group(2)
    return bool(_OLD_TOKEN.match(name + (":" + arg if arg else ""))) and not tokens.token_known(name, False)


def run_anchor(m, old, out=None, known=()):
    """dev #985 (0.7.0): the one anchor the old page shows for the bare token `m` when it stands in a RUN of tokens with nothing
    but white space between them (`{{workLink}}{{resumeLink}}`), so `old_spot` finds no text of the source's own beside it. The
    spot is the whole run's, found as `old_spot` finds one; it must hold exactly one menu anchor per token of the run, separated
    as the source separates them, else None (never a guess). The anchor at the token's place in the run is returned as a
    `_MENU_ANCHOR` match. dev #1042: only template link tokens are members of the run (never a token the build knows), and the
    text beside the run is the build's own, evaluated (`old_spot`)."""
    s = m.string
    run = [t for t in tokens.TOKEN_RE.finditer(s) if _is_link_token(t)]
    i = next((k for k, t in enumerate(run) if t.start() == m.start()), None)
    if i is None:
        return None
    lo = hi = i
    while lo > 0 and _ADJACENT.match(s[run[lo - 1].end():run[lo].start()]):
        lo -= 1
    while hi + 1 < len(run) and _ADJACENT.match(s[run[hi].end():run[hi + 1].start()]):
        hi += 1
    if lo == hi:
        return None
    before, after = _window(s, run[lo].start(), run[hi].end(), out, known)
    if not before.strip() or not after.strip():
        return None
    found = set(x.group(1) for x in re.finditer(re.escape(before) + r"(.*?)" + re.escape(after), old, re.S))
    if len(found) != 1:
        return None
    middle = found.pop()
    parts = []
    for k in range(lo, hi + 1):
        w = re.match(r"\s*<a\s+href\s*=\s*([\"'])([^\"'<>]*)\1\s*>([^<>]*)</a\s*>", middle)
        if not w:
            return None
        parts.append(_MENU_ANCHOR.match(w.group(0)))
        middle = middle[w.end():]
    if middle.strip():
        return None
    return parts[i - lo]


def old_page(hints, path, data):
    """(the old builder's text of the page `site/src/<path>` publishes, the site's own hosts, that page's output path) for
    `frozen_anchor` and `menu_anchor_measured`, or None. Read
    from `hints["oldPages"]` ({output path: bytes}), which the caller that ran the old builder supplies; `check` has no old
    build, so there it is None and no token is frozen this way. The layout prints on every page and has no one page."""
    pages = (hints or {}).get(OLD_PAGES) or {}
    if not path.startswith("site/src/") or path[len("site/src/"):] not in pages:
        return None
    d = data if isinstance(data, dict) else {}
    own = set(h.lower() for h in (urlsplit(d["previewUrl"]).hostname if isinstance(d.get("previewUrl"), str) else None,
                                  d.get("domain") if isinstance(d.get("domain"), str) else None) if h)
    blob = pages[path[len("site/src/"):]]
    if isinstance(blob, dict):          # the plan's form (`old_pages_hint`): the bytes parity measured, checked, else not read
        try:
            raw = base64.b64decode(blob["data"])
        except (KeyError, TypeError, ValueError):
            return None
        if hashlib.sha256(raw).hexdigest() != blob.get("sha256"):
            return None
        blob = raw
    try:
        return blob.decode("utf-8"), own, path[len("site/src/"):]
    except (UnicodeDecodeError, AttributeError):
        return None


OLD_PAGES = "oldPages"          # the member of the plan's `hints` that holds the old pages a token conversion read


def old_pages_hint(sources, local):
    """dev #985, option A (0.7.0): the `hints` member that hands the token conversion the old builder's pages, which parity now
    runs BEFORE the token check. Only the pages whose source (`{site/src/<path>: text}`) holds a token the plugin's build does
    not know, as {output path: {"sha256", "data" (base64)}}: the form the plan stores, so `check` and `apply` make the same
    conversion parity measured. A page the old build did not write is not in it, so its token stays a loud refusal."""
    out = {}
    for path, text in sorted(sources.items()):
        rel = path[len("site/src/"):] if path.startswith("site/src/") else None
        if rel is None or rel not in local:
            continue
        if any(not tokens.token_known(m.group(1), False) for m in tokens.TOKEN_RE.finditer(text)):
            out[rel] = {"sha256": hashlib.sha256(local[rel]).hexdigest(), "data": base64.b64encode(local[rel]).decode("ascii")}
    return out


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


def rewrite_tokens(text, folders, layout=False, home=None, frozen=None, labels=None, home_rows=False, home_samples=False,
                   old=None, pages=None, waiting=None, resume_label=None):
    """(new text, [(old, new)], [unknown tokens]). Old site-specific `{{<folder>Link}}` forms become
    `{{link:<folder>}}` only where the token is an `<a>` tag's whole `href` value (dev #889); a BARE one (in text, as
    `<nav>{{workLink}}</nav>`) was rendered by the template's builder as a whole anchor, so with the portfolio's label
    in `labels` (`site_json_labels`) it becomes `{{#page:<folder>}}<a href="{{link:<folder>}}">LABEL</a>{{/page}}` WHEN THE
    OLD PAGE RENDERS EXACTLY THAT ANCHOR THERE (`menu_anchor_measured`, step 9a3), and
    otherwise, or anywhere else (another attribute, the text of an anchor), it is left as written and listed as
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
    the page. A token the copy cannot feed stays unknown.

    Schema 6 (design-adopt-parity-2 section 7.4): a BARE `{{resumeLink}}` (in text, as `{{workLink}}{{resumeLink}}`) becomes
    `bare_resume(label)`, the anchor the plugin's own nav prints (`label`: the site's chosen `nav.labels.resume`, `resume_label`, else
    the plugin's `Resume`), inside a `{{#page:resume}}` section (dev 979 / #245); an unknown
    token in the query of a same-site stylesheet or script address becomes `{{assetVersion}}` (`asset_query_token`); and a
    bare token the plugin has no token for, which the old page renders at that spot as one whole anchor to an outside address,
    is FROZEN as that anchor (`frozen_anchor`, from `old`: (the old page's text, the site's own hosts, its output path),
    `old_page`'s result).

    A bare menu token is wrapped ONLY when measured (step 9a3, the owner invariant: nothing visible ships silently): the old
    page renders exactly the wrap's anchor at that spot (`menu_anchor_measured`: the same label, the same address) and the
    plugin's build has the page (`folders` for a portfolio; `pages`, the other pages it builds, for `resume`). That check
    runs BEFORE the freeze, so an outside anchor there is frozen; several links there, another label or address, or no such
    page, and the token stays as written and is listed (the build refuses it, `inventory` names the step). With NO old page
    (`old` None: `inventory`, `check`, and every command until one hands the conversion the old pages) a bare `resumeLink`
    stays too; a bare `{{<folder>Link}}` with a label keeps 0.5.x's wrap (dev #889), which parity measures against the old
    build afterwards (making it strict too is an open decision of step 9a3). Before 9a3 both wraps were written
    whatever the old page held there. dev #1042: such an unmeasured wrap is also appended to `waiting` (when given), so a
    command that holds no old page lists it as waiting on parity, never as written."""
    norm = dict((re.sub(r"[-_]", "", f).lower(), f) for f in folders)
    changes, unknown = [], []
    known = set(folders) | set(pages or ())         # the pages the plugin's build has: what a section marker and a link beside a token name
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
        f = norm.get(om.group(1).lower()) if om else None
        if f and link_token_context(m) == "href":
            new = "{{link:%s%s}}" % (f, "/" + om.group(2) if om.group(2) else "")
            changes.append((m.group(0), new))
            return new
        bare = not arg and link_token_context(m) == "text"
        menu = None                                        # (page, label, the wrap): a bare menu token's one anchor
        if bare and name == "resumeLink" and "resume" in (pages or ()):
            word = resume_label or RESUME_LABEL
            menu = ("resume", word, bare_resume(word))     # the anchor the nav prints (dev 979 / #245; the chosen label, schema 8)
        elif bare and f and (labels or {}).get(f):
            menu = (f, labels[f], section_for_link(f, labels[f]))      # dev #889
        unmeasured_889 = menu is not None and old is None and menu[0] == f    # 0.5.x's wrap, which parity then measures
        new = None
        if menu and (menu_anchor_measured(m, old, menu[0], menu[1], known) or unmeasured_889):
            new = menu[2]                                  # measured FIRST: the old page holds exactly this anchor there
            if unmeasured_889 and waiting is not None:
                waiting.append((m.group(0), new))          # dev #1042: written with no old page to measure it on; parity decides
        elif asset_query_token(m):
            new = "{{assetVersion}}"                       # the cache-busting version: the same bytes at the same path (U-b)
        elif bare and old:
            new = frozen_anchor(m, old[0], old[1], old[2] if len(old) > 2 else None, known)
            if new is not None:
                frozen.append((m.group(0), new))
        if new is not None:
            changes.append((m.group(0), new))
            return new
        unknown.append(m.group(0))
        return m.group(0)
    return tokens.TOKEN_RE.sub(sub, text), changes, unknown


def token_files(tree):
    return [p for p in tree.paths() if (p.startswith("site/src/") and p.lower().endswith((".html", ".htm")))
            or p == "site/templates/layout.html"]
