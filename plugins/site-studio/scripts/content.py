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

SCHEMA 3 ADDS SIX CONTAINER BLOCKS (site-fidelity, dev #865), each opt-in and recognised only at schema 3
(below it every such line is text, byte for byte as 0.2.0 renders it): `:::tiles`, `:::quote`, `:::gallery`,
`:::videos`, `:::carousel` and `:::part <name>`, each closed by a line holding only `:::`, with a titled
image line `![alt](path "title")`. A top-level line starting with a backslash and then one of those forms is
text. `LEAD_INS` is the one table of what changes meaning; `render_markdown(..., grammar=3)` reads it, and
so does `interpretation_reasons`, which `siteconfig` uses to decide a site needs schema 3.
"""
import hashlib
import html
import json
import posixpath
import re

from siteconfig import (validate_portfolio_settings, SiteConfigError, WORK_KEYS, labels_nonempty,
                        make_problem, schema_2_reasons, V3_PAGE_KEYS, page_settings_problems, front_matter_keys,
                        BUILTIN_PIECE_KEYS)


class ContentError(ValueError):
    """A content file cannot be read or breaks a rule. The message names the file.

    `path`, `lineno` and `fix` (design-site-fidelity section 4.1) are what `build.accept` turns into a
    `siteconfig.Problem`: where it is, the 1-based line when the check knows it, and the one-line remedy.
    `str(e)` is the message alone, unchanged, so every existing caller reads what it always read."""

    def __init__(self, message="", path=None, lineno=None, fix=None):
        ValueError.__init__(self, message)
        self.path = path
        self.lineno = lineno
        self.fix = fix


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
        raise ContentError("%s is not valid UTF-8" % where, fix="save the file as UTF-8")
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
        raise ContentError("%s: an unterminated quote in a list" % where, fix="close the quote in the list")
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
            raise ContentError("%s: a bad double-quoted string: %s" % (where, s), fix="close the quotes, or write the value without quotes")
        return val
    if s[:1] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise ContentError("%s: a bad single-quoted string: %s" % (where, s), fix="close the quotes, or write the value without quotes")
        return s[1:-1].replace("''", "'")
    return s


def _block_map(block, where):
    """A block map of `k: v` lines; a `k:` line with nothing after it opens ONE more level of the same
    (dev #853: `labels:` holds `meta:` and `groups:`, each a map of key to display label). `block` is
    [(line number, indent, stripped line)]."""
    base = min(ind for _n, ind, _b in block)
    d = {}
    i = 0
    while i < len(block):
        n, ind, b = block[i]
        mm = re.match(r"^([^:]+):\s+(.*)$", b)
        head = re.match(r"^([^:]+):\s*$", b)
        if ind != base or b.startswith("- ") or not (mm or head):
            raise ContentError("%s:%d: cannot read this nested line: %s" % (where, n, b), fix="write nested values as indented key: value lines")
        k2 = (mm or head).group(1).strip()
        if k2 in d:
            raise ContentError("%s:%d: duplicate key '%s'" % (where, n, k2), fix="remove the repeated key")
        i += 1
        if mm:
            d[k2] = _scalar(mm.group(2), where)
            continue
        sub = []
        while i < len(block) and block[i][1] > base:
            sub.append(block[i])
            i += 1
        if not sub:
            raise ContentError("%s:%d: cannot read this nested line: %s" % (where, n, b), fix="write nested values as indented key: value lines")
        sbase = min(x[1] for x in sub)
        inner = {}
        for sn, sind, sb in sub:
            sm = re.match(r"^([^:]+):\s+(.*)$", sb)
            if sind != sbase or sb.startswith("- ") or not sm:
                raise ContentError("%s:%d: cannot read this nested line: %s" % (where, sn, sb), fix="write nested values as indented key: value lines")
            k3 = sm.group(1).strip()
            if k3 in inner:
                raise ContentError("%s:%d: duplicate key '%s'" % (where, sn, k3), fix="remove the repeated key")
            inner[k3] = _scalar(sm.group(2), where)
        d[k2] = inner
    return d


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
        raise ContentError("%s: front matter opens with --- but never closes" % where, fix="add a closing --- line after the front matter")
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
            raise ContentError("%s:%d: cannot read this front matter line: %s" % (where, lineno, raw), fix="write each front matter line as key: value")
        key, val = m.group(1), m.group(2)
        if key in meta:
            raise ContentError("%s:%d: duplicate front matter key '%s'" % (where, lineno, key), fix="remove the repeated key")
        i += 1
        if val is None or not val.strip():
            block = []
            while i < end and (lines[i].startswith("  ") or lines[i].startswith("\t") or
                               not lines[i].strip()):
                if lines[i].strip():
                    block.append((i + 1, len(lines[i]) - len(lines[i].lstrip(" \t")), lines[i].strip()))
                i += 1
            if not block:
                meta[key] = ""
            elif all(b.startswith("- ") or b == "-" for _n, _ind, b in block):
                meta[key] = [_scalar(b[2:], where) for _n, _ind, b in block]
            else:
                meta[key] = _block_map(block, where)
        elif val.startswith("["):
            if not val.rstrip().endswith("]"):
                raise ContentError("%s:%d: a list opens with [ but does not close" % (where, lineno), fix="close the list with ]")
            inner = val.strip()[1:-1]
            meta[key] = [_scalar(p, where) for p in _split_flow(inner, where) if p != ""]
        else:
            meta[key] = _scalar(val, where)
    return meta, "\n".join(lines[end + 1:])


def _check_keys(meta, allowed, where):
    for k in meta:
        if k not in allowed:
            raise ContentError("%s: unknown front matter key '%s' (allowed: %s)"
                               % (where, k, ", ".join(allowed)), fix="remove the key, or use one of the allowed keys named here")


def _need_str(meta, key, where, required=False):
    if key not in meta:
        if required:
            raise ContentError("%s: front matter '%s' is required" % (where, key), fix="add the required key to the front matter")
        return None
    v = meta[key]
    if not isinstance(v, str) or not v.strip():
        raise ContentError("%s: front matter '%s' must be a non-empty string" % (where, key), fix="write a non-empty text value for that key")
    return v


def _str_list(meta, key, where):
    v = meta.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise ContentError("%s: front matter '%s' must be a list of strings" % (where, key), fix="write the value as a list of text items, such as [a, b]")
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
    def __init__(self, source, meta, body, first_line=1):
        self.source = source
        self.meta = meta
        self.body = body
        self.first_line = first_line      # the file line of the body's first line (a refusal names it)


class Piece(object):
    def __init__(self, portfolio, slug, source, meta, body, first_line=1):
        self.portfolio = portfolio
        self.slug = slug
        self.source = source
        self.folder = posixpath.dirname(source)
        self.meta = meta
        self.body = body
        self.first_line = first_line
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
    def __init__(self, slug, settings, title, intro, page_source, intro_line=1, page_keys=()):
        self.slug = slug
        self.settings = settings
        self.title = title
        self.intro = intro
        self.page_source = page_source
        self.intro_line = intro_line
        self.page_keys = frozenset(page_keys)     # the front matter keys its page.md sets (a refusal names the file)
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

    def menu_portfolios(self):
        """The portfolios in menu order: those with a page.md `order` first, ascending, then the rest by folder
        name (a tie too). Without `order` anywhere this is the folder-name order the nav always had."""
        return sorted(self.portfolios, key=lambda p: ((0, p.settings["order"], p.slug)
                                                      if p.settings.get("order") is not None else (1, 0, p.slug)))

    def piece(self, key):
        p, _, s = key.partition("/")
        pf = self.portfolio(p)
        if pf is None:
            return None
        for pc in pf.pieces:
            if pc.slug == s:
                return pc
        return None


def _check_contact(meta, path):
    c = meta["contact"]
    if not isinstance(c, dict) or not c or not all(isinstance(v, str) and v for v in c.values()):
        raise ContentError("%s: 'contact' must be a map of label: value" % path, fix="write contact as a map of label: value lines")


def _page(files, path, allowed, where_name):
    text = decode_text(files[path], path)
    meta, body = parse_front_matter(text, path)
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
            raise ContentError("%s: 'endorsement' must be a map with 'quote' and optionally 'by'" % path, fix="write endorsement as a map with quote: and optionally by:")
    if "contact" in meta:
        _check_contact(meta, path)
    for k in ("featured", "feed"):
        if k in meta:
            _str_list(meta, k, path)
    return Page(path, meta, body, body_start_line(text))


def _validate_piece(portfolio, slug, path, files, drafts, media_paths, featured_from="home"):
    text = decode_text(files[path], path)
    meta, body = parse_front_matter(text, path)
    if "draft" in meta and not isinstance(meta["draft"], bool):
        raise ContentError("%s: front matter 'draft' must be true or false" % path, fix="write draft: true or draft: false")
    if meta.get("draft") and not drafts:
        return None
    _need_str(meta, "title", path, required=True)
    if featured_from == "flags" and "featured" in meta and not isinstance(meta["featured"], bool):
        raise ContentError("%s: front matter 'featured' must be true or false (featuredFrom is flags)" % path, fix="write featured: true or featured: false")
    for k in portfolio.settings["required"]:
        v = meta.get(k)
        if v is None or v == "" or v == []:
            raise ContentError("%s: front matter '%s' is required in the %s portfolio"
                               % (path, k, portfolio.slug), fix="add the required key to the front matter")
    for k in ("shortTitle", "teaser", "description"):
        if k in meta:
            _need_str(meta, k, path)
    if "date" in meta and not (isinstance(meta["date"], str) and DATE_RE.match(meta["date"])):
        raise ContentError("%s: front matter 'date' must look like 2026-03-04" % path, fix="write the date as YYYY-MM-DD, such as 2026-03-04")
    if portfolio.settings.get("sort") == "order" and "order" in meta:     # read only under sort: "order" (schema 3)
        o = meta["order"]
        if isinstance(o, bool) or not isinstance(o, int):
            raise ContentError("%s: front matter 'order' must be a whole number (the %s portfolio sorts by order)"
                               % (path, portfolio.slug), path=path,
                               fix="write order as a whole number, such as order: 2, or remove it")
    gb = portfolio.settings["groupBy"]
    if gb:
        g = meta.get(gb)
        if g not in portfolio.settings["groups"]:
            raise ContentError("%s: '%s' must be one of %s (the %s portfolio's groups), got %r"
                               % (path, gb, ", ".join(portfolio.settings["groups"]),
                                  portfolio.slug, g), fix="set it to one of the groups listed")
    if "coverPosition" in meta:
        cp = meta["coverPosition"]
        if not isinstance(cp, str) or not POSITION_RE.match(cp):
            raise ContentError("%s: front matter 'coverPosition' must be a CSS position such as "
                               "'center 30%%'" % path, fix="write a CSS position such as center 30%")
    if "cover" in meta:
        cv = _need_str(meta, "cover", path)
        if not cv.startswith("ref:"):
            full = posixpath.normpath(posixpath.join(posixpath.dirname(path), cv))
            if full not in media_paths or not full.startswith(posixpath.dirname(path) + "/media/"):
                raise ContentError("%s: cover '%s' is not a file in this piece's media/ folder" % (path, cv), fix="put the cover image in this piece's media/ folder and name it media/<file>")
    return Piece(portfolio.slug, slug, path, meta, body, body_start_line(text))


# What a `hub` or `custom` site does not build (design-site-adoption section 4.1), found by path.
_KIND_REFUSAL = ("only a portfolio site builds this; set siteKind to portfolio, or prefix the "
                 "folder with _ to keep it as source material")


def kind_layout_problems(files, kind):
    """Every path under `content/` that a `hub` or `custom` site refuses, each with its fix. Empty
    for a portfolio. A silently unbuilt portfolio would read as an empty one (CLAUDE.md, traps 1-4),
    so a stray `content/work/` is refused rather than ignored. Folders starting `_`, shared media
    and captured references stay allowed: nothing builds them on any kind."""
    if kind == "portfolio":
        return []
    out = []
    seen = set()
    for path in sorted(p for p in files if p.startswith("content/")):
        parts = path.split("/")
        if path in ("content/home.md", "content/about.md"):
            out.append("%s: %s" % (path, _KIND_REFUSAL.replace("prefix the folder with _",
                                                                "rename the file with a leading _")))
            continue
        if len(parts) >= 3 and not parts[1].startswith("_") and parts[1] not in ("media", "references"):
            folder = "content/%s/" % parts[1]
            if folder not in seen:
                seen.add(folder)
                what = "a resume source" if parts[1] == "resume" else "a portfolio folder"
                out.append("%s (%s): %s" % (folder, what, _KIND_REFUSAL))
    return out


def no_page_message(folder):
    return ("%s has no page.md: a folder under content/ is a portfolio only when it has one (put "
            "non-portfolio files outside content/, or start the folder name with _)" % folder)


def _home_featured_list(files):
    """True when content/home.md carries a `featured:` entry. An unreadable file is not reported
    here: the loader refuses it, naming the line."""
    where = "content/home.md" if "content/home.md" in files else "content/home/index.md"
    raw = files.get(where)
    if raw is None:
        return False
    try:
        meta, _body = parse_front_matter(decode_text(raw, where), where)
    except ContentError:
        return False
    return "featured" in meta


FOLDER_PAGES = (("home", HOME_KEYS), ("about", ABOUT_KEYS))


def folder_form_problems(files):
    """Schema 3's folder form of the home and about pages (design-site-fidelity section 5.1, F1):
    `content/home/index.md` and `content/about/index.md`, each with a `media/` folder, beside the
    `content/home.md` and `content/about.md` files. Every fault, each a `Problem`: both forms at once, a
    folder with no `index.md`, and any other file in the folder, which nothing would publish (a silently
    unpublished file is refused, never ignored). None is mechanical: adopt never moves a reserved folder."""
    out = []
    for name, _keys in FOLDER_PAGES:
        folder = "content/%s/" % name
        mine = sorted(p for p in files if p.startswith(folder))
        if not mine:
            continue
        index = folder + "index.md"
        if index not in files:
            out.append(make_problem("%s has no index.md: the folder form of the %s page needs one" % (folder, name),
                                    folder, "no index.md", "an index.md",
                                    "add content/%s/index.md (the page's copy and front matter)" % name))
        elif "content/%s.md" % name in files:
            out.append(make_problem("two %s pages: content/%s.md and content/%s/index.md; keep one"
                                    % (name, name, name), index, "two %s pages" % name, "one",
                                    "keep one: delete content/%s.md to use the folder, or the folder's "
                                    "index.md to use the file" % name))
        for p in mine:
            rel = p[len(folder):]
            if rel == "index.md" or rel.startswith("media/") or rel.startswith("_"):
                continue
            out.append(make_problem("%s: nothing publishes a file here; a file in content/%s/ must be index.md "
                                    "or be under media/" % (p, name), p, "a stray file", "index.md, or a file "
                                    "under media/", "move it into media/ or start its name with _"))
    return out


_HOME_TOKEN = re.compile(r"\{\{\s*home\s*:")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def hand_home_is_fed(files):
    """True when the hand-made home page (`site/src/index.html`) uses a `{{home:<part>}}` token outside an HTML
    comment, so `content/home.md` is not a second home page but the page's copy (site-fidelity section 6.1, C1).
    The pair is accepted only then; with no part token the 0.2.0 refusal of two home pages stands."""
    raw = files.get("site/src/index.html")
    if raw is None:
        return False
    try:
        text = decode_text(raw, "site/src/index.html") if isinstance(raw, bytes) else raw
    except ContentError:
        return False
    return bool(_HOME_TOKEN.search(_HTML_COMMENT.sub("", text)))


def layout_problems(files, site_kind, cfg=None):
    """Every problem in the content TREE, all at once, each a `siteconfig.Problem` (design-site-adoption
    sections 7.1, 4.1, 4.3, 6.2 and 3): a folder under content/ with no page.md, a hub or custom site
    holding portfolio content, two home pages, two featured sources, and (when `cfg` is given) a tree
    that needs schema 2 under a schema-1 config.

    `files` is {repo path: bytes} (this module reads no file; the design's `root` is this mapping, so
    adopt can pass a git tree and the build its commit). `cfg` is the parsed site.json, and may be None
    when only the layout is asked about. Empty means the tree has none of these faults."""
    out = []
    if site_kind != "portfolio":
        for text in kind_layout_problems(files, site_kind):
            path = text.split(":", 1)[0].split(" ", 1)[0]
            out.append(make_problem(text, path, "portfolio content", "none, on a %s site" % site_kind,
                                    "set siteKind to portfolio, or prefix the folder with _ to keep it as "
                                    "source material"))
    else:
        seen = set()
        for path in sorted(p for p in files if p.startswith("content/")):
            parts = path.split("/")
            if len(parts) < 3 or parts[1].startswith("_") or parts[1] in RESERVED_PORTFOLIO_NAMES:
                continue            # a reserved name is never a portfolio and is never offered the `_` rename (F1)
            name = parts[1]
            folder = "content/%s/" % name
            if folder in seen or name == "work" or folder + "page.md" in files:
                continue
            seen.add(folder)
            holds_md = any(p.startswith(folder) and p.lower().endswith(".md") for p in files)
            out.append(make_problem(
                no_page_message(folder), folder, "no page.md", "a page.md, or a folder name starting _",
                ("rename it to content/_%s (kept as source material, not built), or add a page.md so it "
                 "becomes a portfolio" % name) if not holds_md else
                ("decide: `adopt.py folder %s source` keeps it as source material (content/_%s, not built, "
                 "so the Markdown in it is not published), or add a page.md so it becomes a portfolio. A "
                 "folder holding Markdown is never moved without your say" % (name, name)), not holds_md))
        if cfg is not None and cfg.schema >= 3:
            out += folder_form_problems(files)
        if ("site/src/index.html" in files and ("content/home.md" in files or "content/home/index.md" in files)
                and not hand_home_is_fed(files)):
            out.append(make_problem(HOME_TWICE if "content/home.md" in files else
                                    HOME_TWICE.replace("content/home.md", "content/home/index.md"),
                                    "site/src/index.html", "two home pages",
                                    "one: site/src/index.html or content/home.md",
                                    "keep one: delete content/home.md to use the hand-made page, or "
                                    "delete site/src/index.html to use the generated home, or feed the "
                                    "hand-made page from content/home.md with {{home:intro}}"))
        if cfg is not None and cfg.featuredFrom == "flags" and _home_featured_list(files):
            out.append(make_problem(FEATURED_TWICE, "content/home.md", "a featured: list under flags",
                                    "no featured: list", "remove the featured: list from content/home.md, "
                                    "or drop featuredFrom"))
    if cfg is not None and cfg.schema < 2:
        for where, what, effect in schema_2_reasons(cfg, files):
            out.append(make_problem("%s %s, which needs \"schema\": 2 in site/site.json (%s)"
                                    % (where, what, effect), where, "schema 1", "schema 2",
                                    "set \"schema\": 2 in site/site.json (a save by site-studio does this)",
                                    True))
    return out


HOME_TWICE = "two home pages: site/src/index.html and content/home.md; keep one"
FEATURED_TWICE = ("featuredFrom is flags, so content/home.md's featured: list would be ignored; remove it, "
                  "or drop featuredFrom")


def _unit(collect, fn, *args):
    """Run one unit of the load. With `collect` None this is a plain call (the first `ContentError`
    raises, as it always did). With a list, a refusal is APPENDED and the unit is skipped, so
    `build.accept` can report every problem at once (design-site-fidelity section 4.1). Returns the
    unit's value, or None when it was skipped."""
    try:
        return fn(*args)
    except (ContentError, SiteConfigError) as e:
        if collect is None:
            raise
        collect.append(e)
        return None


def _key_line(text, v3, probs, key=None):
    """The 1-based line of the page.md key a refusal is about (`key`, else the first schema-3 key the first
    problem names), or None when it cannot be found."""
    wanted = key or next((k for k in v3 if probs and ("'%s'" % k) in probs[0].message), None)
    for k, n in front_matter_keys(text):
        if k == wanted:
            return n
    return None


def _load_portfolio_head(name, files, cfg, folder, page_path):
    """The folder checks, the page.md and the settings of one portfolio, as a `Portfolio` with no pieces."""
    if name in RESERVED_PORTFOLIO_NAMES:
        raise ContentError("%s: a portfolio folder name must be lower-case letters, digits "
                           "and hyphens (and not %s)" % (folder, ", ".join(RESERVED_PORTFOLIO_NAMES)),
                           path=folder, fix="%s is a reserved name: at schema 3 content/%s/index.md is the %s "
                           "page (run `build.py raise-schema`); any other folder needs another name"
                           % (name, name, name))
    if page_path not in files and name != "work":
        raise ContentError(no_page_message(folder), path=folder,
                           fix="add a page.md to the folder, or start its name with _ to keep it out of the build")
    if not SLUG_RE.match(name):
        raise ContentError("%s: a portfolio folder name must be lower-case letters, digits "
                           "and hyphens (and not %s)" % (folder, ", ".join(RESERVED_PORTFOLIO_NAMES)),
                           path=folder, fix="rename the folder to lower-case letters, digits and hyphens")
    base = dict(cfg.work) if name == "work" else {}
    if not labels_nonempty(base.get("labels")):
        base.pop("labels", None)     # the defaulted, empty map is not an entry in a schema-1 file
    title = None
    intro = ""
    meta = {}
    intro_line = 1
    page_text = ""
    v3 = {}
    if page_path in files:
        page_text = decode_text(files[page_path], page_path)
        meta, intro = parse_front_matter(page_text, page_path)
        intro_line = body_start_line(page_text)
        _check_keys(meta, PORTFOLIO_PAGE_KEYS + WORK_KEYS + (V3_PAGE_KEYS if cfg.schema >= 3 else ()), page_path)
        if "title" in meta:
            title = _need_str(meta, "title", page_path)
        overrides = dict((k, v) for k, v in meta.items() if k != "title" and k not in V3_PAGE_KEYS)
        v3 = dict((k, meta[k]) for k in V3_PAGE_KEYS if k in meta)
        try:
            if name == "work":
                merged = dict(base)
                merged.update(overrides)
                settings = validate_portfolio_settings(merged, "work", cfg.schema, cfg.featuredFrom)
            else:
                settings = validate_portfolio_settings(overrides, page_path, cfg.schema, cfg.featuredFrom)
        except SiteConfigError as e:
            raise ContentError("; ".join(p.message.replace("site.json: ", "%s: " % page_path, 1)
                                         for p in e.problems), path=page_path,
                               fix="fix the setting named above in this page.md front matter")
    else:
        settings = validate_portfolio_settings(base, "work", cfg.schema, cfg.featuredFrom)
        v3 = {}
    if name != "work" and "label" not in meta:
        settings["label"] = name.replace("-", " ").title()
    probs, page_settings = page_settings_problems(v3, page_path)      # schema 3's keys (section 6.2); defaults below it
    if probs:
        raise ContentError("; ".join(p.message for p in probs), path=page_path, lineno=_key_line(page_text, v3, probs),
                           fix="fix the key named above: %s" % probs[0].fix)
    settings.update(page_settings)
    if settings["view"] == "page" and "site/src/%s/index.html" % name not in files:
        raise ContentError("%s: view is \"page\", so the portfolio's index is your own page, and "
                           "site/src/%s/index.html is not there" % (page_path, name), path=page_path,
                           lineno=_key_line(page_text, v3, None, "view"),
                           fix="add site/src/%s/index.html, or set view to \"grid\" (the generated index)" % name)
    return Portfolio(name, settings, title or settings["label"], intro,
                     page_path if page_path in files else None, intro_line, meta.keys())


def _load_piece(pf, name, slug, files, drafts, media_paths, featured_from):
    idx = "content/%s/%s/index.md" % (name, slug)
    if idx not in files:
        raise ContentError("content/%s/%s/ has no index.md: a piece folder needs one "
                           "(start the folder name with _ to keep it out of the build)"
                           % (name, slug), path="content/%s/%s/" % (name, slug),
                           fix="rename the piece file to index.md, or start the folder name with _ to "
                               "leave it out of the build")
    if not SLUG_RE.match(slug):
        raise ContentError("content/%s/%s: a piece folder name must be lower-case letters, "
                           "digits and hyphens" % (name, slug), path="content/%s/%s/" % (name, slug),
                           fix="rename the folder to lower-case letters, digits and hyphens")
    return _validate_piece(pf, slug, idx, files, drafts, media_paths, featured_from)


def _load_reference(name, files, paths):
    rj = "content/references/%s/reference.json" % name
    if rj not in files:
        raise ContentError("content/references/%s/ has no reference.json" % name,
                           path="content/references/%s/" % name,
                           fix="add reference.json to the folder, or remove the folder")
    try:
        data = json.loads(decode_text(files[rj], rj))
    except ValueError as e:
        raise ContentError("%s is not valid JSON: %s" % (rj, e), path=rj,
                           fix="fix the JSON syntax in reference.json")
    if not isinstance(data, dict):
        raise ContentError("%s must be an object" % rj, path=rj, fix="make reference.json one JSON object")
    for k in data:
        if k not in REFERENCE_KEYS:
            raise ContentError("%s: unknown key '%s'" % (rj, k), path=rj,
                               fix="remove the key (allowed: %s)" % ", ".join(REFERENCE_KEYS))
    for k in ("url", "title"):
        if not isinstance(data.get(k), str) or not data[k].strip():
            raise ContentError("%s: '%s' is required" % (rj, k), path=rj,
                               fix="add the key to reference.json as non-empty text")
    if not re.match(r"^https?://", data["url"]):
        raise ContentError("%s: 'url' must start with http:// or https://" % rj, path=rj,
                           fix="start the url with https://")
    for k in REFERENCE_KEYS:
        if k in data and not isinstance(data[k], str):
            raise ContentError("%s: '%s' must be a string" % (rj, k), path=rj,
                               fix="write the value as text")
    cards = [p for p in paths if p.startswith("content/references/%s/card." % name)
             and p.lower().endswith(CARD_EXTS)]
    if len(cards) > 1:
        raise ContentError("content/references/%s/ has more than one card image" % name,
                           path="content/references/%s/" % name,
                           fix="keep one card image in the reference folder")
    return Reference(name, data, cards[0] if cards else None)


def _load_resume(files, cfg, check_resume_pdf, c):
    src = cfg.resume["path"]
    pdf = cfg.resume["pdf"]
    if src in files:
        text = decode_text(files[src], src)
        meta, body = parse_front_matter(text, src)
        _check_keys(meta, RESUME_PAGE_KEYS + (("contact",) if cfg.schema >= 3 else ()), src)   # K-5: schema 3 only
        if "contact" in meta:
            _check_contact(meta, src)
        c.resume = Page(src, meta, body, body_start_line(text))
    elif check_resume_pdf:
        raise ContentError("site.json configures a resume but %s is not committed" % src, path=src,
                           fix="commit the resume file, or set resume to null in site.json")
    if pdf and pdf in files:
        c.resume_pdf = (pdf, files[pdf])
    if check_resume_pdf and c.resume is not None and pdf:
        _check_resume_pdf(files, src, pdf)


def load_content(files, cfg, drafts=False, check_resume_pdf=False, collect=None):
    """Build the validated model from {repo path: bytes} (only site/ and content/ paths are
    looked at). `drafts` includes `draft: true` pieces. `check_resume_pdf` is the publish-time
    stale-PDF refusal. `collect`: None raises the first `ContentError`, as the build always did; a list
    receives one `ContentError` per refused unit (a portfolio, a piece, a page, a reference, the resume)
    and the load carries on with the units that are fine, so `build.accept` reports every problem."""
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
    folder_form = cfg.schema >= 3      # schema 3 reads home and about as folders (F1); below it they are refused
    for name in sorted(top_dirs):
        if name.startswith("_") or name in ("media", "resume", "references"):
            continue
        if folder_form and name in ("home", "about"):
            continue
        folder = "content/" + name + "/"
        page_path = folder + "page.md"
        pf = _unit(collect, _load_portfolio_head, name, files, cfg, folder, page_path)
        if pf is None:
            continue
        slugs = {}
        for p in top_dirs[name]:
            parts = p.split("/")
            if len(parts) >= 4 and not parts[2].startswith("_"):
                slugs.setdefault(parts[2], []).append(p)
        for slug in sorted(slugs):
            piece = _unit(collect, _load_piece, pf, name, slug, files, drafts, media_paths, cfg.featuredFrom)
            if piece is None:
                continue
            pf.pieces.append(piece)
            for mp in slugs[slug]:
                if mp in media_paths and mp.startswith(piece.folder + "/media/"):
                    c.media[mp] = mp[len("content/"):]
        pf.pieces = sorted(sorted(pf.pieces, key=lambda x: x.slug), key=lambda x: x.date or "",
                           reverse=True)
        if pf.settings.get("sort") == "order":      # a piece with an `order` first, ascending; the rest stay by date
            pf.pieces = sorted(pf.pieces, key=lambda x: (0, x.meta["order"]) if "order" in x.meta else (1, 0))
        c.portfolios.append(pf)

    # ---- shared media
    for p in paths:
        if p.startswith("content/media/"):
            c.media[p] = p[len("content/"):]

    # ---- home, about
    if "content/home.md" in files:
        c.home = _unit(collect, _page, files, "content/home.md", HOME_KEYS, "home")
    elif folder_form and "content/home/index.md" in files:
        c.home = _unit(collect, _page, files, "content/home/index.md", HOME_KEYS, "home")
    if "content/about.md" in files:
        c.about = _unit(collect, _page, files, "content/about.md", ABOUT_KEYS, "about")
    elif folder_form and "content/about/index.md" in files:
        c.about = _unit(collect, _page, files, "content/about/index.md", ABOUT_KEYS, "about")
    if folder_form:           # a folder page's media/ is published beside it, as a piece's is
        for name, _keys in FOLDER_PAGES:
            if "content/%s/index.md" % name in files:
                for p in paths:
                    if p.startswith("content/%s/media/" % name):
                        c.media[p] = p[len("content/"):]

    # ---- references
    names = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 4 and parts[1] == "references" and not parts[2].startswith("_"):
            names.add(parts[2])
    for name in sorted(names):
        ref = _unit(collect, _load_reference, name, files, paths)
        if ref is not None:
            c.references[name] = ref

    # ---- resume
    if cfg.resume is not None:
        _unit(collect, _load_resume, files, cfg, check_resume_pdf, c)
    return c


# ---------------------------------------------------------------- strays a piece folder carries (dev #885, dev #882)

STRAY_FILE_FIX = "pieces have one page; put this in index.md, or start the name with _ to keep it as source"
UNKNOWN_KEY_FIX = "add the key to meta or cardMeta, or remove it"


def piece_known_keys(portfolio, featured_from="home"):
    """The front matter keys of a piece that the build reads or shows: the built-in ones, `description` (the
    page's meta description), the portfolio's `groupBy` key, every key `meta` or `cardMeta` lists, and
    `featured` under `featuredFrom: flags` (where the piece's own flag picks the featured pieces)."""
    known = set(BUILTIN_PIECE_KEYS) | {"description"}
    known.update(portfolio.settings["meta"])
    known.update(portfolio.settings["cardMeta"])
    if portfolio.settings["groupBy"]:
        known.add(portfolio.settings["groupBy"])
    if featured_from == "flags":
        known.add("featured")
    return known


def stray_warnings(files, model, cfg):
    """WARNINGS (never refusals) for what a piece folder holds that the build does not publish, as
    `make_problem`-shaped items sorted by (path, line, message). Two classes, both named, both with a fix:

    - dev #885: a `.md` in a piece folder other than `index.md` (the piece is ONE page), and a sub-folder
      other than `media/`. A name starting with `_` is the way to keep something as source (the loader's own
      rule for folders; applied to the stray `.md` file too, so the fix this warning names clears it).
    - dev #882 (the unknown-key part): a front matter key that is neither built in nor named in the portfolio's
      `meta` or `cardMeta` (see `piece_known_keys`): the build publishes nothing of it.

    This is the OWNER INVARIANT's shape: the tree 0.3.0 built still builds, to the same bytes, at every schema,
    so the build says it and never refuses it. `build.accept` carries these as `.warnings`, apart from
    `.problems`, so `adopt check` can refuse them where nothing has been converted yet. Pure: it reads only
    `files` ({repo path: bytes}) and the loaded `model`."""
    below = {}      # "content/<portfolio>/<slug>" -> [path parts under the piece folder]
    for p in files:
        parts = p.split("/")
        if len(parts) >= 4 and parts[0] == "content":
            below.setdefault("/".join(parts[:3]), []).append(parts[3:])
    out = []
    for pf in model.portfolios:
        known = piece_known_keys(pf, cfg.featuredFrom)
        for piece in pf.pieces:
            rels = below.get(piece.folder, [])
            for rel in sorted(r for r in rels if len(r) == 1):
                name = rel[0]
                if name.lower().endswith(".md") and name != "index.md" and not name.startswith("_"):
                    path = "%s/%s" % (piece.folder, name)
                    out.append(make_problem(
                        "%s: this file is not published; a piece is one page, its index.md" % path, path,
                        name, "index.md as the only page", STRAY_FILE_FIX))
            subs = {}
            for rel in rels:
                if len(rel) >= 2 and rel[0] != "media" and not rel[0].startswith("_"):
                    subs[rel[0]] = subs.get(rel[0], 0) + 1
            for sub in sorted(subs):
                path = "%s/%s/" % (piece.folder, sub)
                n = subs[sub]
                out.append(make_problem(
                    "%s: this folder is not published (%d file%s in it); a piece is one page, its index.md, "
                    "and its media/ folder" % (path, n, "" if n == 1 else "s"), path, sub,
                    "media/ or a folder starting with _", STRAY_FILE_FIX))
            lines = dict(front_matter_keys(decode_text(files[piece.source], piece.source)))
            for key in piece.meta:
                if key in known:
                    continue
                out.append(make_problem(
                    "%s: front matter key '%s' is not published; it is not a built-in key and the %s "
                    "portfolio's meta and cardMeta do not list it" % (piece.source, key, pf.slug),
                    piece.source, key, "a built-in key, or one listed in meta or cardMeta", UNKNOWN_KEY_FIX,
                    lineno=lines.get(key)))
    return sorted(out, key=lambda p: (p.path or "", p.lineno or 0, p.message))


def _check_resume_pdf(files, src, pdf):
    side = pdf + ".json"
    if pdf not in files:
        raise ContentError("the resume PDF %s is not committed; make it with the resume skill" % pdf, fix="make the PDF with the resume skill and commit it")
    if side not in files:
        raise ContentError("%s is missing: without it nothing proves %s matches the resume source"
                           % (side, pdf), fix="make the PDF again with the resume skill, which writes the sidecar")
    try:
        rec = json.loads(decode_text(files[side], side))
    except ValueError as e:
        raise ContentError("%s is not valid JSON: %s" % (side, e), fix="fix the JSON syntax in the file")
    if not isinstance(rec, dict) or set(rec) != {"source_sha256", "pdf_sha256", "text_sha256"} \
            or not all(isinstance(v, str) and SHA_RE.match(v) for v in rec.values()):
        raise ContentError("%s must hold exactly source_sha256, pdf_sha256 and text_sha256 "
                           "(64 hex digits each)" % side, fix="make the PDF again with the resume skill")
    if hashlib.sha256(files[src]).hexdigest() != rec["source_sha256"]:
        raise ContentError("the resume PDF is stale: %s changed after %s was made; remake the PDF "
                           "with the resume skill" % (src, pdf), fix="remake the PDF with the resume skill")
    if hashlib.sha256(files[pdf]).hexdigest() != rec["pdf_sha256"]:
        raise ContentError("the resume PDF is stale: %s does not match its sidecar %s" % (pdf, side), fix="remake the PDF with the resume skill")


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

# ---- the one grammar table of the schema-3 interpretations (design-site-fidelity section 3.3)
# Each row is a top-level Markdown body line that 0.2.0 renders as plain text and schema 3 reads as
# something else: (form name, pattern, how a reason names it). `siteconfig` cannot import this module,
# so `interpretation_reasons` hands its result to `siteconfig.required_schema(..., interpretations=)`.
# A row is added here BEFORE `render_markdown` gives a line new meaning at schema 3, and a corpus test
# (test_build.py) asserts nothing the renderer special-cases is missing from this table.
LEAD_INS = (
    ("container", re.compile(r"^:::[A-Za-z][A-Za-z0-9_-]*(?:[ \t].*)?$"), "a ::: container line"),
    ("leaf", re.compile(r"^::[A-Za-z][A-Za-z0-9_-]*(?:[ \t].*)?$"), "a :: directive line"),
    ("close", re.compile(r"^:::[ \t]*$"), "a bare ::: line"),
    ("titled-image", re.compile(r"^!\[[^\]]*\]\([^)\s]+\s+\"[^\"]*\"\)$"), "a titled image line"),
)


def body_start_line(text):
    """The 1-based line number of the first body line of a Markdown file (after its front matter, or
    1 when it has none or the block never closes)."""
    if not text.startswith("---\n"):
        return 1
    for i, line in enumerate(text.split("\n")[1:], 2):
        if line.rstrip() == "---":
            return i + 1
    return 1


def interpretation_reasons(files):
    """[(path, lineno, form)] for every top-level Markdown body line in `files` ({path: bytes or str})
    that a `LEAD_INS` row matches: the I-1 and I-2 reasons of schema 3. Front matter is skipped; a
    line inside a `>` quote or a list item is not top level and is never matched (its first column is
    not the form's first character). A file that is not valid UTF-8 is skipped: the build refuses it
    on its own."""
    out = []
    for path in sorted(files):
        if not (path.startswith("content/") and path.lower().endswith(".md")):
            continue
        raw = files[path]
        try:
            text = decode_text(raw, path) if isinstance(raw, bytes) else raw.replace("\r\n", "\n")
        except ContentError:
            continue
        first = body_start_line(text)
        for n, line in enumerate(text.split("\n"), 1):
            if n < first:
                continue
            for _name, rx, form in LEAD_INS:
                if rx.match(line.rstrip()):
                    out.append((path, n, form))
                    break
    return out


def check_href(url, where):
    scheme = _SCHEME.match(url)
    if scheme:
        if scheme.group(1).lower() not in ("http", "https", "mailto"):
            raise ContentError("%s: a link may be http(s), mailto, #anchor or relative, not '%s:'"
                               % (where, scheme.group(1)), fix="use an http(s), mailto, #anchor or relative link")
        return
    if url.startswith("/"):
        raise ContentError("%s: root-absolute link '%s'; links must be relative so one build serves "
                           "at /<repo>/ and at /" % (where, url), fix="make the link relative, such as ../work/ or media/photo.jpg")


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


_IMGLINE3 = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$')
_OPEN = re.compile(r"^:::([A-Za-z][A-Za-z0-9_-]*)(?:[ \t]+(.*))?$")
_PART_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_URL_SCHEME_OR_PROTOREL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")

# The six container blocks (site-fidelity section 7), recognised at schema 3 only. A name is added here and as
# a `block_<name>` method of `_Renderer` together; the grammar corpus test (test_build.py) walks `LEAD_INS`.
BLOCK_NAMES = ("tiles", "quote", "gallery", "videos", "carousel", "part")
# The parts of a home page that `{{home:<part>}}` names without a `:::part` container (section 6.1).
PART_FIXED = ("title", "description", "intro", "photo", "endorsement", "feed", "contact")


def _lead_kind(line):
    """The `LEAD_INS` form a line IS ("container", "leaf" or "close"), or None. The titled-image row is
    handled by `_IMGLINE3`. One table: this reads `LEAD_INS`, so the renderer cannot recognise a form the
    corpus test (and `interpretation_reasons`) does not know."""
    s = line.rstrip()
    for name, rx, _form in LEAD_INS:
        if name != "titled-image" and rx.match(s):
            return name
    return None


def _is_lead_in(line):
    """True for a line any `LEAD_INS` row matches: the lines a backslash escapes at schema 3."""
    s = line.rstrip()
    return any(rx.match(s) for _name, rx, _form in LEAD_INS)


def _starts_block(line, grammar=2):
    """True when `line` ends a paragraph. At grammar 3 and above a fence line and a titled image line end it
    too (a line escaped with a backslash is unescaped first and marked plain, so it never reaches here as a
    fence); below 3 the rule is exactly 0.2.0's."""
    if (_HEADING.match(line) or _ULI.match(line) or _OLI.match(line)
            or line.startswith(">") or _REFLINE.match(line) or _IMGLINE.match(line)
            or _HR.match(line.strip()) or video_embed(line.strip())):
        return True
    return grammar >= 3 and (_lead_kind(line) is not None or bool(_IMGLINE3.match(line)))


def _ss_img(tag):
    """A plugin block's `<img>` carries the `ss-img` class, so the block stylesheet can size it without an
    element selector (every selector in blocks.css ends in an ss- class)."""
    return tag.replace("<img ", '<img class="ss-img" ', 1)


class Fragment(object):
    """A run of Markdown lines, each with its 1-based line number in its file (`nums`), and the set of those
    numbers whose backslash escape was removed (`plain`: they are text, whatever they now look like)."""

    def __init__(self, lines, nums, plain):
        self.lines = lines
        self.nums = nums
        self.plain = plain


def _fragment(body, first_line=1, grammar=2):
    lines = body.split("\n")
    nums = list(range(first_line, first_line + len(lines)))
    plain = set()
    if grammar >= 3:
        for k, ln in enumerate(lines):
            if ln.startswith("\\") and _is_lead_in(ln[1:]):
                lines[k] = ln[1:]
                plain.add(nums[k])
    return Fragment(lines, nums, plain)


class _Renderer(object):
    """The block renderer. Below grammar 3 it is 0.2.0's loop, line for line (the owner invariant); at 3 and
    above a top-level fence line opens a container block. `env` supplies `image`, `ref_card` and, for plugin
    blocks, `asset(kind)`: the `<link>` or `<script>` to emit before the page's first plugin block (or "")."""

    def __init__(self, env, where, grammar, plain):
        self.env = env
        self.where = where
        self.grammar = grammar
        self.plain = plain
        self.asset = getattr(env, "asset", None) or (lambda kind: "")

    def _at(self, n):
        return "%s:%d" % (self.where, n)

    def starts(self, frag, i):
        return frag.nums[i] not in self.plain and _starts_block(frag.lines[i], self.grammar)

    def blocks(self, frag):
        lines, nums = frag.lines, frag.nums
        g3 = self.grammar >= 3
        env, where = self.env, self.where
        out, i = [], 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            plain = nums[i] in self.plain
            if g3 and not plain:
                kind = _lead_kind(line)
                if kind:
                    i = self.fence(frag, i, kind, out)
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
            m = (_IMGLINE3 if g3 and not plain else _IMGLINE).match(line)
            if m:
                title = m.group(3) if m.re is _IMGLINE3 else None
                cap = "<figcaption>%s</figcaption>" % esc(title) if title else ""
                out.append('<figure class="media">%s%s</figure>' % (env.image(m.group(2), m.group(1)), cap))
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
                while i < len(lines) and lines[i].strip() and not self.starts(frag, i):
                    para.append(lines[i].strip())
                    i += 1
                out.append("<p>%s</p>" % render_inline(" ".join(para), env, where))
        return out

    # ---- containers (grammar 3)
    def find_close(self, frag, i, name):
        """The index of the `:::` line that closes the container opened at `i`. A `part` may hold ONE other
        block (not another part); any other container holds none."""
        lines, nums = frag.lines, frag.nums
        open_at = nums[i]
        inner_open, inner_seen = False, 0
        for j in range(i + 1, len(lines)):
            if nums[j] in self.plain:
                continue
            kind = _lead_kind(lines[j])
            if kind == "close":
                if inner_open:
                    inner_open = False
                    continue
                return j
            if kind == "leaf":
                raise ContentError("%s: '%s' is a leaf directive and this Markdown has none"
                                   % (self._at(nums[j]), lines[j].strip()), path=self.where, lineno=nums[j],
                                   fix="show the line as text by putting a backslash in front of it, or "
                                       "write a container block (:::name ... :::)")
            if kind == "container":
                inner = _OPEN.match(lines[j].rstrip()).group(1)
                if name == "part" and inner in BLOCK_NAMES and inner != "part" and not inner_open and not inner_seen:
                    inner_open, inner_seen = True, 1
                    continue
                raise ContentError("%s: ':::%s' opens inside ':::%s' (line %d); blocks do not nest, except "
                                   "that a part may hold one other block"
                                   % (self._at(nums[j]), inner, name, open_at), path=self.where, lineno=nums[j],
                                   fix="close the first block with a ::: line before opening the next, or "
                                       "show the line as text with a backslash in front of it")
        raise ContentError("%s: ':::%s' is never closed" % (self._at(open_at), name), path=self.where,
                           lineno=open_at, fix="add a line holding only ::: after the block, or show the line "
                                               "as text with a backslash in front of it")

    def part_name(self, label, n):
        name = label.split()[0] if label.split() else ""
        if not name or not _PART_NAME.match(name):
            raise ContentError("%s: ':::part' needs a name: lower-case letters, digits and hyphens (got %r)"
                               % (self._at(n), label), path=self.where, lineno=n,
                               fix="write the block as :::part <name>, such as :::part stats")
        if name in PART_FIXED:
            raise ContentError("%s: ':::part %s' collides with the fixed home part '%s'"
                               % (self._at(n), name, name), path=self.where, lineno=n,
                               fix="rename the part; the fixed names are %s" % ", ".join(PART_FIXED))
        return name

    def fence(self, frag, i, kind, out):
        lines, nums = frag.lines, frag.nums
        n = nums[i]
        if kind == "leaf":
            raise ContentError("%s: '%s' is a leaf directive and this Markdown has none"
                               % (self._at(n), lines[i].strip()), path=self.where, lineno=n,
                               fix="show the line as text by putting a backslash in front of it, or write "
                                   "a container block (:::name ... :::)")
        if kind == "close":
            raise ContentError("%s: a ::: line closes a block that was never opened" % self._at(n),
                               path=self.where, lineno=n,
                               fix="remove the stray ::: line, or open the block above it with :::name")
        m = _OPEN.match(lines[i].rstrip())
        name, label = m.group(1), (m.group(2) or "").strip()
        if name not in BLOCK_NAMES:
            raise ContentError("%s: unknown block ':::%s' (the blocks are %s)"
                               % (self._at(n), name, ", ".join(BLOCK_NAMES)), path=self.where, lineno=n,
                               fix="use one of the block names listed, or show the line as text by putting a "
                                   "backslash in front of it")
        close = self.find_close(frag, i, name)
        inner = Fragment(lines[i + 1:close], nums[i + 1:close], self.plain)
        html = getattr(self, "block_" + name)(inner, label, n)
        if html:
            out.append(html)
        return close + 1

    def rows(self, inner, n, what):
        rows = [(inner.nums[k], l.strip()) for k, l in enumerate(inner.lines) if l.strip()]
        if not rows:
            raise ContentError("%s: the :::%s block is empty" % (self._at(n), what), path=self.where,
                               lineno=n, fix="add at least one row inside the block, or remove it")
        return rows

    def block_part(self, inner, label, n):
        self.part_name(label, n)
        return "\n".join(self.blocks(inner))

    def block_tiles(self, inner, label, n):
        items = []
        for ln, row in self.rows(inner, n, "tiles"):
            if "|" not in row:
                raise ContentError("%s: a tile row is 'figure | label' and this one has no '|'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as figure | label, such as 1,200+ | visits")
            figure, _, text = row.partition("|")
            figure, text = figure.strip(), text.strip()
            if not figure or not text:
                raise ContentError("%s: a tile row needs a figure and a label on both sides of '|'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as figure | label, such as 1,200+ | visits")
            items.append('<li class="ss-tile"><span class="ss-tile-figure">%s</span>'
                         '<span class="ss-tile-label">%s</span></li>' % (esc(figure), esc(text)))
        return '%s<ul class="ss-tiles">%s</ul>' % (self.asset("css"), "".join(items))

    def block_quote(self, inner, label, n):
        rows = [(inner.nums[k], l.rstrip()) for k, l in enumerate(inner.lines)]
        while rows and not rows[-1][1].strip():
            rows.pop()
        if not rows:
            raise ContentError("%s: the :::quote block is empty" % self._at(n), path=self.where, lineno=n,
                               fix="write the quoted words inside the block, then an optional line "
                                   "starting '— ' with who said it")
        by = None
        last = rows[-1][1].strip()
        if last.startswith("— ") or last.startswith("-- "):
            by = last[2:].strip() if last.startswith("— ") else last[3:].strip()
            rows.pop()
        paras, cur = [], []
        for _ln, text in rows:
            if text.strip():
                cur.append(text.strip())
            elif cur:
                paras.append(cur)
                cur = []
        if cur:
            paras.append(cur)
        if not paras:
            raise ContentError("%s: the :::quote block holds only an attribution" % self._at(n),
                               path=self.where, lineno=n,
                               fix="write the quoted words above the '— ' line")
        body = "".join("<p>%s</p>" % render_inline(" ".join(p), self.env, self.where) for p in paras)
        cap = ""
        if by:
            cm = re.search(r"\*([^*]+)\*\s*$", by)
            if cm:
                head = by[:cm.start()].rstrip()
                by_html = ((render_inline(head, self.env, self.where) + " ") if head else "") + \
                    "<cite>%s</cite>" % esc(cm.group(1))
            else:
                by_html = render_inline(by, self.env, self.where)
            cap = '<figcaption class="ss-quote-by">%s</figcaption>' % by_html
        return ('%s<figure class="ss-quote"><blockquote class="ss-quote-text">%s</blockquote>%s</figure>'
                % (self.asset("css"), body, cap))

    def block_gallery(self, inner, label, n):
        items = []
        for ln, row in self.rows(inner, n, "gallery"):
            m = _IMGLINE3.match(row)
            if not m:
                raise ContentError("%s: a gallery holds image lines only, and this is not one"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write each line as ![alt](media/file.jpg), one per line")
            cap = '<figcaption class="ss-caption">%s</figcaption>' % esc(m.group(3)) if m.group(3) else ""
            items.append('<figure class="ss-gallery-item">%s%s</figure>'
                         % (_ss_img(self.env.image(m.group(2), m.group(1))), cap))
        aria = ' role="group" aria-label="%s"' % esc(label) if label else ""
        return '%s<div class="ss-gallery" data-count="%d"%s>%s</div>' % (self.asset("css"), len(items), aria,
                                                                         "".join(items))

    def block_videos(self, inner, label, n):
        items = []
        for ln, row in self.rows(inner, n, "videos"):
            cols = [c.strip() for c in row.split("|")]
            if len(cols) not in (2, 3) or not cols[0] or not cols[1]:
                raise ContentError("%s: a video row is 'title | url' or 'title | url | media/poster.jpg'"
                                   % self._at(ln), path=self.where, lineno=ln,
                                   fix="write the row as title | url, and add | media/poster.jpg for a photo "
                                       "that plays the video")
            title, url = cols[0], cols[1]
            embed = video_embed(url)
            if embed is None:
                raise ContentError("%s: %r is not a YouTube, Vimeo or public Google Drive link"
                                   % (self._at(ln), url), path=self.where, lineno=ln,
                                   fix="use the video's https address from YouTube, Vimeo or a public Drive file")
            if embed.startswith("https://player.vimeo.com/"):
                embed += ("&" if "?" in embed else "?") + "dnt=1"
            head = '<a class="ss-video" href="%s" data-embed="%s" rel="noopener">' % (esc(url), esc(embed))
            if len(cols) == 3 and cols[2]:
                poster = cols[2]
                if _URL_SCHEME_OR_PROTOREL.match(poster):
                    raise ContentError("%s: the poster %r is a remote address; a facade loads nothing from "
                                       "a third party before a click" % (self._at(ln), poster),
                                       path=self.where, lineno=ln,
                                       fix="commit the image under media/ and name it as media/poster.jpg")
                face = (_ss_img(self.env.image(poster, "")) + '<span class="ss-play" aria-hidden="true"></span>'
                        '<span class="ss-video-title">%s</span>' % esc(title))
            else:
                host = re.sub(r"^www\.", "", re.sub(r"^https://", "", url).split("/")[0])
                face = ('<span class="ss-video-title">%s</span><span class="ss-video-host">%s</span>'
                        % (esc(title), esc(host)))
            items.append(head + face + "</a>")
        aria = ' role="group" aria-label="%s"' % esc(label) if label else ""
        return '%s%s<div class="ss-videos"%s>%s</div>' % (self.asset("css"), self.asset("js"), aria,
                                                         "".join(items))

    def block_carousel(self, inner, label, n):
        self.rows(inner, n, "carousel")
        heads = []
        for k, l in enumerate(inner.lines):
            m = _HEADING.match(l)
            if m and len(m.group(1)) == 3 and inner.nums[k] not in self.plain:
                heads.append(k)
        if heads:
            cuts = ([0] if heads[0] > 0 and any(l.strip() for l in inner.lines[:heads[0]]) else []) + heads
            cuts.append(len(inner.lines))
            slides = []
            for a, b in zip(cuts, cuts[1:]):
                part = Fragment(inner.lines[a:b], inner.nums[a:b], self.plain)
                slides.append("\n".join(self.blocks(part)))
        else:
            slides = self.blocks(inner)
        lis = "".join('<li class="ss-slide">%s</li>' % s for s in slides if s)
        return ('%s<div class="ss-carousel" role="region" aria-label="%s" tabindex="0">'
                '<ul class="ss-track">%s</ul></div>' % (self.asset("css"), esc(label or "Carousel"), lis))


def render_fragment(frag, env, where, grammar=3):
    """Render a `Fragment` (a body, or a part of one) to HTML."""
    return "\n".join(_Renderer(env, where, grammar, frag.plain).blocks(frag))


def render_markdown(body, env, where, grammar=2, first_line=1):
    """Render a Markdown-subset body to HTML. `env.image(src, alt)` and `env.ref_card(name)`
    return HTML (or raise ContentError). `grammar` is the schema whose reading of a line applies: 3 and
    above read the new block grammar (site-fidelity section 7); below it every line is 0.2.0 text, byte for
    byte (the owner invariant, `Upgrade020Unchanged`). `first_line` is the file line number of the body's first
    line, so a refusal at schema 3 names the line the person wrote."""
    return render_fragment(_fragment(body, first_line, grammar), env, where, grammar)


def parse_parts(body, where, first_line=1):
    """Split a schema-3 body into (intro, {part name: Fragment}) for `{{home:<part>}}` (section 6.1): each
    top-level `:::part <name>` block is taken out of the intro and kept by name; every other line, block
    included, stays in the intro. A duplicate name, an unclosed block and the other grammar refusals raise
    `ContentError` with the file and line. `intro` is a Fragment."""
    frag = _fragment(body, first_line, 3)
    r = _Renderer(None, where, 3, frag.plain)
    keep_l, keep_n, parts, opened = [], [], {}, {}
    i = 0
    while i < len(frag.lines):
        kind = _lead_kind(frag.lines[i]) if frag.nums[i] not in frag.plain else None
        if kind == "container":
            m = _OPEN.match(frag.lines[i].rstrip())
            if m.group(1) in BLOCK_NAMES:
                close = r.find_close(frag, i, m.group(1))
                if m.group(1) == "part":
                    name = r.part_name((m.group(2) or "").strip(), frag.nums[i])
                    if name in parts:
                        raise ContentError("%s: ':::part %s' appears twice (first at line %d)"
                                           % (r._at(frag.nums[i]), name, opened[name]), path=where,
                                           lineno=frag.nums[i], fix="give each part its own name")
                    parts[name] = Fragment(frag.lines[i + 1:close], frag.nums[i + 1:close], frag.plain)
                    opened[name] = frag.nums[i]
                else:
                    keep_l.extend(frag.lines[i:close + 1])
                    keep_n.extend(frag.nums[i:close + 1])
                i = close + 1
                continue
        keep_l.append(frag.lines[i])
        keep_n.append(frag.nums[i])
        i += 1
    return Fragment(keep_l, keep_n, frag.plain), parts


def _drop_containers(frag):
    """The lines of a schema-3 fragment outside every container block, for the excerpt (a block's rows are
    never a page's description)."""
    out_l, depth = [], 0
    for ln, n in zip(frag.lines, frag.nums):
        kind = _lead_kind(ln) if n not in frag.plain else None
        if kind == "container":
            depth += 1
            continue
        if kind == "close":
            depth = max(0, depth - 1)
            continue
        if kind == "leaf" or depth:
            continue
        out_l.append(ln)
    return "\n".join(out_l)


def plain_excerpt(body, limit=160, grammar=2):
    """The first prose paragraph as plain text, cut on a word boundary: a deterministic
    description when a page gives none. At grammar 3 the text of a container block is never the excerpt, and
    a fence line ends a paragraph."""
    if grammar >= 3:
        body = _drop_containers(_fragment(body, 1, 3))
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if not block or _starts_block(block.split("\n")[0], grammar):
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
