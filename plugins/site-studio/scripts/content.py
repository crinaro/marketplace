#!/usr/bin/env python3
"""content.py -- the content model and the Markdown subset (dev #835, design 2.4). Pure: it
reads no file and runs no command. `build.py` hands it a {repo path: bytes} map and gets back a
validated model; every refusal is a `ContentError` naming the file.

THE MODEL (every row of design 2.4 has a loader rule here and a case in test_build.py)
---------------------------------------------------------------------------------------
content/home.md, content/about.md   pages: front matter (title, description, featured, feed,
                                    endorsement, photo, photoAlt, contact) + an intro body
content/<portfolio>/page.md         one portfolio per folder; the FOLDER decides the page. The
                                    folder `work` is the default portfolio: its settings come from
                                    site.json `work`, overridden by its page.md. Folders starting
                                    `_` (`_template`) are skipped. Any other folder without a
                                    page.md is refused (it would be silently unpublished).
content/<portfolio>/<slug>/index.md a piece. Front matter: title (required), shortTitle, teaser,
                                    description, date, draft, group key, cover (`media/x.jpg` or
                                    `ref:<name>`), coverPosition, and any key `meta`/`cardMeta`
                                    lists. `draft: true` never builds (unless drafts=True).
content/<portfolio>/<slug>/media/*  the piece's published files (nothing else in a piece folder
                                    is published)
content/media/*                     shared published files (a home or about photo)
content/references/<name>/          reference.json + text.md + card.<ext>: a captured reference.
                                    `text.md` is raw material and is never published; only the
                                    card of a reference that is actually used is.
content/resume/resume.md (+ .pdf)   the resume page; the PDF and its `.pdf.json` sidecar are
                                    checked for staleness by a publish build

Size copies of an image sit beside it as `<stem>-<width>w.<ext>` (`images.py`, phase 1b, writes
them; the build only discovers them and builds a `srcset`).

MARKDOWN SUBSET: headings (a `#` is rendered as h2: the page title owns h1), paragraphs, one
level of `-`/`*` and `1.` lists, `>` quotes, `---`, `**bold**`, `*em*`, `` `code` ``, links,
images, a line holding only a YouTube, Vimeo or public-Drive URL (an embed), and `ref: <name>`
lines (consecutive lines make a grid). Raw HTML is escaped, never passed through. A link must be
http(s), mailto, an in-page `#anchor` or RELATIVE: a root-absolute href is refused because the
same output serves at `/<repo>/` and at `/`.
"""
import hashlib
import html
import json
import posixpath
import re

from siteconfig import validate_portfolio_settings, SiteConfigError, WORK_KEYS


class ContentError(ValueError):
    """A content file cannot be read or breaks a rule. The message names the file."""


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
POSITION_RE = re.compile(r"^[a-z0-9% .-]{1,40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RESERVED_PORTFOLIO_NAMES = ("media", "resume", "references", "about", "home")
CARD_EXTS = (".jpg", ".jpeg", ".png", ".webp")
REFERENCE_KEYS = ("url", "title", "description", "site", "published", "kind", "captured")
TEXT_EXTS = (".html", ".htm", ".css", ".js", ".mjs", ".json", ".md", ".txt", ".xml", ".svg",
             ".webmanifest")

HOME_KEYS = ("title", "description", "featured", "feed", "endorsement", "photo", "photoAlt",
             "contact")
ABOUT_KEYS = ("title", "description", "endorsement", "photo", "photoAlt", "contact")
RESUME_PAGE_KEYS = ("title", "description")
PORTFOLIO_PAGE_KEYS = ("title",)


# ---------------------------------------------------------------- text and front matter

def decode_text(raw, where):
    """UTF-8, BOM dropped, CR LF and lone CR normalised to LF."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ContentError("%s is not valid UTF-8" % where)
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_flow(s, where):
    items, cur, quote = [], "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if quote:
        raise ContentError("%s: an unterminated quote in a list" % where)
    if cur.strip() or items:
        items.append(cur.strip())
    return items


def _scalar(s, where):
    s = s.strip()
    if s == "true":
        return True
    if s == "false":
        return False
    if re.match(r"^-?\d+$", s):
        return int(s)
    if s[:1] == '"':
        try:
            val = json.loads(s)
        except ValueError:
            val = None
        if not isinstance(val, str):
            raise ContentError("%s: a bad double-quoted string: %s" % (where, s))
        return val
    if s[:1] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise ContentError("%s: a bad single-quoted string: %s" % (where, s))
        return s[1:-1].replace("''", "'")
    return s


def parse_front_matter(text, where):
    """Return (meta dict, body text). A subset of YAML: `key: scalar`, `key: [a, b]`, a block
    list of `- item`, or a one-level block map of `k: v`. A duplicate key or a line it cannot
    read is refused with the file and line number. No front matter means ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        raise ContentError("%s: front matter opens with --- but never closes" % where)
    meta = {}
    i = 1
    while i < end:
        raw = lines[i]
        lineno = i + 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*):(?:\s+(.*)|\s*)$", raw)
        if not m:
            raise ContentError("%s:%d: cannot read this front matter line: %s" % (where, lineno, raw))
        key, val = m.group(1), m.group(2)
        if key in meta:
            raise ContentError("%s:%d: duplicate front matter key '%s'" % (where, lineno, key))
        i += 1
        if val is None or not val.strip():
            block = []
            while i < end and (lines[i].startswith("  ") or lines[i].startswith("\t") or
                               not lines[i].strip()):
                if lines[i].strip():
                    block.append((i + 1, lines[i].strip()))
                i += 1
            if not block:
                meta[key] = ""
            elif all(b.startswith("- ") or b == "-" for _n, b in block):
                meta[key] = [_scalar(b[2:], where) for _n, b in block]
            else:
                d = {}
                for n, b in block:
                    mm = re.match(r"^([^:]+):\s+(.*)$", b)
                    if not mm or b.startswith("- "):
                        raise ContentError("%s:%d: cannot read this nested line: %s" % (where, n, b))
                    k2 = mm.group(1).strip()
                    if k2 in d:
                        raise ContentError("%s:%d: duplicate key '%s'" % (where, n, k2))
                    d[k2] = _scalar(mm.group(2), where)
                meta[key] = d
        elif val.startswith("["):
            if not val.rstrip().endswith("]"):
                raise ContentError("%s:%d: a list opens with [ but does not close" % (where, lineno))
            inner = val.strip()[1:-1]
            meta[key] = [_scalar(p, where) for p in _split_flow(inner, where) if p != ""]
        else:
            meta[key] = _scalar(val, where)
    return meta, "\n".join(lines[end + 1:])


def _check_keys(meta, allowed, where):
    for k in meta:
        if k not in allowed:
            raise ContentError("%s: unknown front matter key '%s' (allowed: %s)"
                               % (where, k, ", ".join(allowed)))


def _need_str(meta, key, where, required=False):
    if key not in meta:
        if required:
            raise ContentError("%s: front matter '%s' is required" % (where, key))
        return None
    v = meta[key]
    if not isinstance(v, str) or not v.strip():
        raise ContentError("%s: front matter '%s' must be a non-empty string" % (where, key))
    return v


def _str_list(meta, key, where):
    v = meta.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise ContentError("%s: front matter '%s' must be a list of strings" % (where, key))
    return v


def meta_text(v):
    """A front matter value as display text."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


# ---------------------------------------------------------------- the model

class Page(object):
    def __init__(self, source, meta, body):
        self.source = source
        self.meta = meta
        self.body = body


class Piece(object):
    def __init__(self, portfolio, slug, source, meta, body):
        self.portfolio = portfolio
        self.slug = slug
        self.source = source
        self.folder = posixpath.dirname(source)
        self.meta = meta
        self.body = body
        self.title = meta["title"]
        self.draft = meta.get("draft", False)
        self.date = meta.get("date")

    @property
    def key(self):
        return "%s/%s" % (self.portfolio, self.slug)

    @property
    def card_title(self):
        return self.meta.get("shortTitle") or self.title


class Portfolio(object):
    def __init__(self, slug, settings, title, intro, page_source):
        self.slug = slug
        self.settings = settings
        self.title = title
        self.intro = intro
        self.page_source = page_source
        self.pieces = []


class Reference(object):
    def __init__(self, name, data, card_path):
        self.name = name
        self.data = data
        self.card_path = card_path


class Content(object):
    def __init__(self):
        self.portfolios = []      # sorted by slug
        self.home = None
        self.about = None
        self.resume = None        # Page or None
        self.resume_pdf = None    # (repo path, bytes) or None
        self.references = {}      # name -> Reference
        self.media = {}           # repo path -> output path, only for what is published
        self.notes = []

    def portfolio(self, slug):
        for p in self.portfolios:
            if p.slug == slug:
                return p
        return None

    def piece(self, key):
        p, _, s = key.partition("/")
        pf = self.portfolio(p)
        if pf is None:
            return None
        for pc in pf.pieces:
            if pc.slug == s:
                return pc
        return None


def _page(files, path, allowed, where_name):
    meta, body = parse_front_matter(decode_text(files[path], path), path)
    _check_keys(meta, allowed, path)
    if "title" in meta:
        _need_str(meta, "title", path)
    if "description" in meta:
        _need_str(meta, "description", path)
    if "photo" in meta:
        _need_str(meta, "photo", path)
        _need_str(meta, "photoAlt", path, required=True)
    if "endorsement" in meta:
        e = meta["endorsement"]
        if not isinstance(e, dict) or "quote" not in e or set(e) - {"quote", "by"}:
            raise ContentError("%s: 'endorsement' must be a map with 'quote' and optionally 'by'" % path)
    if "contact" in meta:
        c = meta["contact"]
        if not isinstance(c, dict) or not c or not all(isinstance(v, str) and v for v in c.values()):
            raise ContentError("%s: 'contact' must be a map of label: value" % path)
    for k in ("featured", "feed"):
        if k in meta:
            _str_list(meta, k, path)
    return Page(path, meta, body)


def _validate_piece(portfolio, slug, path, files, drafts, media_paths):
    meta, body = parse_front_matter(decode_text(files[path], path), path)
    if "draft" in meta and not isinstance(meta["draft"], bool):
        raise ContentError("%s: front matter 'draft' must be true or false" % path)
    if meta.get("draft") and not drafts:
        return None
    _need_str(meta, "title", path, required=True)
    for k in portfolio.settings["required"]:
        v = meta.get(k)
        if v is None or v == "" or v == []:
            raise ContentError("%s: front matter '%s' is required in the %s portfolio"
                               % (path, k, portfolio.slug))
    for k in ("shortTitle", "teaser", "description"):
        if k in meta:
            _need_str(meta, k, path)
    if "date" in meta and not (isinstance(meta["date"], str) and DATE_RE.match(meta["date"])):
        raise ContentError("%s: front matter 'date' must look like 2026-03-04" % path)
    gb = portfolio.settings["groupBy"]
    if gb:
        g = meta.get(gb)
        if g not in portfolio.settings["groups"]:
            raise ContentError("%s: '%s' must be one of %s (the %s portfolio's groups), got %r"
                               % (path, gb, ", ".join(portfolio.settings["groups"]),
                                  portfolio.slug, g))
    if "coverPosition" in meta:
        cp = meta["coverPosition"]
        if not isinstance(cp, str) or not POSITION_RE.match(cp):
            raise ContentError("%s: front matter 'coverPosition' must be a CSS position such as "
                               "'center 30%%'" % path)
    if "cover" in meta:
        cv = _need_str(meta, "cover", path)
        if not cv.startswith("ref:"):
            full = posixpath.normpath(posixpath.join(posixpath.dirname(path), cv))
            if full not in media_paths or not full.startswith(posixpath.dirname(path) + "/media/"):
                raise ContentError("%s: cover '%s' is not a file in this piece's media/ folder" % (path, cv))
    return Piece(portfolio.slug, slug, path, meta, body)


def load_content(files, cfg, drafts=False, check_resume_pdf=False):
    """Build the validated model from {repo path: bytes} (only site/ and content/ paths are
    looked at). `drafts` includes `draft: true` pieces. `check_resume_pdf` is the publish-time
    stale-PDF refusal."""
    c = Content()
    paths = sorted(p for p in files if p.startswith("content/"))
    # the media each folder publishes, by repo path
    media_paths = set()
    top_dirs = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3:
            top_dirs.setdefault(parts[1], []).append(p)
        if "media" in parts[1:-1] or (parts[1] == "media" and len(parts) > 2):
            media_paths.add(p)

    # ---- portfolios and pieces
    for name in sorted(top_dirs):
        if name.startswith("_") or name in ("media", "resume", "references"):
            continue
        folder = "content/" + name + "/"
        page_path = folder + "page.md"
        if page_path not in files and name != "work":
            raise ContentError("%s has no page.md: a folder under content/ is a portfolio only "
                               "when it has one (put non-portfolio files outside content/, or "
                               "start the folder name with _)" % folder)
        if not SLUG_RE.match(name) or name in RESERVED_PORTFOLIO_NAMES:
            raise ContentError("%s: a portfolio folder name must be lower-case letters, digits "
                               "and hyphens (and not %s)" % (folder, ", ".join(RESERVED_PORTFOLIO_NAMES)))
        base = dict(cfg.work) if name == "work" else {}
        title = None
        intro = ""
        if page_path in files:
            meta, intro = parse_front_matter(decode_text(files[page_path], page_path), page_path)
            _check_keys(meta, PORTFOLIO_PAGE_KEYS + WORK_KEYS, page_path)
            if "title" in meta:
                title = _need_str(meta, "title", page_path)
            overrides = dict((k, v) for k, v in meta.items() if k != "title")
            try:
                if name == "work":
                    merged = dict(base)
                    merged.update(overrides)
                    settings = validate_portfolio_settings(merged, "work")
                else:
                    settings = validate_portfolio_settings(overrides, page_path)
            except SiteConfigError as e:
                raise ContentError(str(e).replace("site.json: ", "%s: " % page_path, 1))
        else:
            settings = validate_portfolio_settings(base, "work")
        if name != "work" and "label" not in (meta if page_path in files else {}):
            settings["label"] = name.replace("-", " ").title()
        pf = Portfolio(name, settings, title or settings["label"], intro,
                       page_path if page_path in files else None)
        slugs = {}
        for p in top_dirs[name]:
            parts = p.split("/")
            if len(parts) >= 4 and not parts[2].startswith("_"):
                slugs.setdefault(parts[2], []).append(p)
        for slug in sorted(slugs):
            idx = "content/%s/%s/index.md" % (name, slug)
            if idx not in files:
                raise ContentError("content/%s/%s/ has no index.md: a piece folder needs one "
                                   "(start the folder name with _ to keep it out of the build)"
                                   % (name, slug))
            if not SLUG_RE.match(slug):
                raise ContentError("content/%s/%s: a piece folder name must be lower-case letters, "
                                   "digits and hyphens" % (name, slug))
            piece = _validate_piece(pf, slug, idx, files, drafts, media_paths)
            if piece is None:
                continue
            pf.pieces.append(piece)
            for mp in slugs[slug]:
                if mp in media_paths and mp.startswith(piece.folder + "/media/"):
                    c.media[mp] = mp[len("content/"):]
        pf.pieces = sorted(sorted(pf.pieces, key=lambda x: x.slug), key=lambda x: x.date or "",
                           reverse=True)
        c.portfolios.append(pf)

    # ---- shared media
    for p in paths:
        if p.startswith("content/media/"):
            c.media[p] = p[len("content/"):]

    # ---- home, about
    if "content/home.md" in files:
        c.home = _page(files, "content/home.md", HOME_KEYS, "home")
    if "content/about.md" in files:
        c.about = _page(files, "content/about.md", ABOUT_KEYS, "about")

    # ---- references
    names = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 4 and parts[1] == "references" and not parts[2].startswith("_"):
            names.add(parts[2])
    for name in sorted(names):
        rj = "content/references/%s/reference.json" % name
        if rj not in files:
            raise ContentError("content/references/%s/ has no reference.json" % name)
        try:
            data = json.loads(decode_text(files[rj], rj))
        except ValueError as e:
            raise ContentError("%s is not valid JSON: %s" % (rj, e))
        if not isinstance(data, dict):
            raise ContentError("%s must be an object" % rj)
        for k in data:
            if k not in REFERENCE_KEYS:
                raise ContentError("%s: unknown key '%s'" % (rj, k))
        for k in ("url", "title"):
            if not isinstance(data.get(k), str) or not data[k].strip():
                raise ContentError("%s: '%s' is required" % (rj, k))
        if not re.match(r"^https?://", data["url"]):
            raise ContentError("%s: 'url' must start with http:// or https://" % rj)
        for k in REFERENCE_KEYS:
            if k in data and not isinstance(data[k], str):
                raise ContentError("%s: '%s' must be a string" % (rj, k))
        cards = [p for p in paths if p.startswith("content/references/%s/card." % name)
                 and p.lower().endswith(CARD_EXTS)]
        if len(cards) > 1:
            raise ContentError("content/references/%s/ has more than one card image" % name)
        c.references[name] = Reference(name, data, cards[0] if cards else None)

    # ---- resume
    if cfg.resume is not None:
        src = cfg.resume["path"]
        pdf = cfg.resume["pdf"]
        if src in files:
            meta, body = parse_front_matter(decode_text(files[src], src), src)
            _check_keys(meta, RESUME_PAGE_KEYS, src)
            c.resume = Page(src, meta, body)
        elif check_resume_pdf:
            raise ContentError("site.json configures a resume but %s is not committed" % src)
        if pdf and pdf in files:
            c.resume_pdf = (pdf, files[pdf])
        if check_resume_pdf and c.resume is not None and pdf:
            _check_resume_pdf(files, src, pdf)
    return c


def _check_resume_pdf(files, src, pdf):
    side = pdf + ".json"
    if pdf not in files:
        raise ContentError("the resume PDF %s is not committed; make it with the resume skill" % pdf)
    if side not in files:
        raise ContentError("%s is missing: without it nothing proves %s matches the resume source"
                           % (side, pdf))
    try:
        rec = json.loads(decode_text(files[side], side))
    except ValueError as e:
        raise ContentError("%s is not valid JSON: %s" % (side, e))
    if not isinstance(rec, dict) or set(rec) != {"source_sha256", "pdf_sha256", "text_sha256"} \
            or not all(isinstance(v, str) and SHA_RE.match(v) for v in rec.values()):
        raise ContentError("%s must hold exactly source_sha256, pdf_sha256 and text_sha256 "
                           "(64 hex digits each)" % side)
    if hashlib.sha256(files[src]).hexdigest() != rec["source_sha256"]:
        raise ContentError("the resume PDF is stale: %s changed after %s was made; remake the PDF "
                           "with the resume skill" % (src, pdf))
    if hashlib.sha256(files[pdf]).hexdigest() != rec["pdf_sha256"]:
        raise ContentError("the resume PDF is stale: %s does not match its sidecar %s" % (pdf, side))


# ---------------------------------------------------------------- video embeds

_YT = re.compile(r"^https://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
                 r"([A-Za-z0-9_-]{11})(?:[&?#].*)?$")
_VIMEO = re.compile(r"^https://(?:www\.)?vimeo\.com/(\d+)(?:[/?#].*)?$")
_DRIVE = re.compile(r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)(?:/[^\s]*)?$")


def video_embed(url):
    """The iframe `src` for a YouTube, Vimeo or public Google Drive URL, or None."""
    m = _YT.match(url)
    if m:
        return "https://www.youtube-nocookie.com/embed/" + m.group(1)
    m = _VIMEO.match(url)
    if m:
        return "https://player.vimeo.com/video/" + m.group(1)
    m = _DRIVE.match(url)
    if m:
        return "https://drive.google.com/file/d/%s/preview" % m.group(1)
    return None


# ---------------------------------------------------------------- Markdown subset

def esc(s):
    return html.escape(s, quote=True)


_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_INLINE = re.compile(r"`([^`]+)`|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)"
                     r"|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ULI = re.compile(r"^[-*]\s+(.*)$")
_OLI = re.compile(r"^\d+\.\s+(.*)$")
_REFLINE = re.compile(r"^ref:\s*([A-Za-z0-9_-]+)\s*$")
_IMGLINE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")
_HR = re.compile(r"^(-{3,}|\*{3,})$")


def check_href(url, where):
    scheme = _SCHEME.match(url)
    if scheme:
        if scheme.group(1).lower() not in ("http", "https", "mailto"):
            raise ContentError("%s: a link may be http(s), mailto, #anchor or relative, not '%s:'"
                               % (where, scheme.group(1)))
        return
    if url.startswith("/"):
        raise ContentError("%s: root-absolute link '%s'; links must be relative so one build serves "
                           "at /<repo>/ and at /" % (where, url))


def render_inline(text, env, where):
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(esc(text[pos:m.start()]))
        pos = m.end()
        if m.group(1) is not None:
            out.append("<code>%s</code>" % esc(m.group(1)))
        elif m.group(3) is not None:
            out.append(env.image(m.group(3), m.group(2)))
        elif m.group(5) is not None:
            check_href(m.group(5), where)
            rel = ' rel="noopener"' if re.match(r"^https?://", m.group(5)) else ""
            out.append('<a href="%s"%s>%s</a>' % (esc(m.group(5)), rel,
                                                  render_inline(m.group(4), env, where)))
        elif m.group(6) is not None:
            out.append("<strong>%s</strong>" % render_inline(m.group(6), env, where))
        else:
            out.append("<em>%s</em>" % render_inline(m.group(7), env, where))
    out.append(esc(text[pos:]))
    return "".join(out)


def _starts_block(line):
    return bool(_HEADING.match(line) or _ULI.match(line) or _OLI.match(line)
                or line.startswith(">") or _REFLINE.match(line) or _IMGLINE.match(line)
                or _HR.match(line.strip()) or video_embed(line.strip()))


def render_markdown(body, env, where):
    """Render a Markdown-subset body to HTML. `env.image(src, alt)` and `env.ref_card(name)`
    return HTML (or raise ContentError)."""
    lines = body.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _HEADING.match(line)
        if m:
            level = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (level, render_inline(m.group(2), env, where), level))
            i += 1
            continue
        if _HR.match(line.strip()):
            out.append("<hr>")
            i += 1
            continue
        src = video_embed(line.strip())
        if src:
            out.append('<div class="video"><iframe src="%s" title="Video" loading="lazy" '
                       'allowfullscreen referrerpolicy="strict-origin-when-cross-origin">'
                       '</iframe></div>' % esc(src))
            i += 1
            continue
        m = _REFLINE.match(line)
        if m:
            cards = []
            while i < len(lines) and _REFLINE.match(lines[i]):
                cards.append(env.ref_card(_REFLINE.match(lines[i]).group(1)))
                i += 1
            out.append(cards[0] if len(cards) == 1 else
                       '<div class="ref-grid">%s</div>' % "".join(cards))
            continue
        m = _IMGLINE.match(line)
        if m:
            out.append('<figure class="media">%s</figure>' % env.image(m.group(2), m.group(1)))
            i += 1
            continue
        if line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>"
                       % render_inline(" ".join(quote), env, where))
            continue
        for rx, tag in ((_ULI, "ul"), (_OLI, "ol")):
            if rx.match(line):
                items = []
                while i < len(lines) and rx.match(lines[i]):
                    items.append("<li>%s</li>" % render_inline(rx.match(lines[i]).group(1), env, where))
                    i += 1
                out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
                break
        else:
            para = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % render_inline(" ".join(para), env, where))
    return "\n".join(out)


def plain_excerpt(body, limit=160):
    """The first prose paragraph as plain text, cut on a word boundary: a deterministic
    description when a page gives none."""
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if not block or _starts_block(block.split("\n")[0]):
            continue
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", block)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"[*`]", "", text)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-")
        return cut + "..."
    return ""
