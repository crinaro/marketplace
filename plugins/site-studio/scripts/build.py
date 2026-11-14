#!/usr/bin/env python3
"""build.py -- the site builder (dev #835, design sections 2.4, 3.3, 3.4, 3.5). Python 3.9, stdlib
only. It launches no browser and processes no media: size copies, metadata stripping and the
resume PDF are made at import time and committed; the build copies them and reads their
dimensions from the file headers.

TWO BUILDS, ONE FUNCTION EACH
-----------------------------
  publish_build(repo, out_dir) -> PublishResult      the only digested build
  preview_build(repo, out_dir) -> BuildResult        drafts included; has no digest, by design

`publish_build` is "one publish build, reproducible" (design 3.5). The output is a pure function of
the committed tree at HEAD (only `site/` and `content/` are ever read) and of nothing else:

  * every input comes from the commit's blobs (`git ls-tree -r -z`, `git cat-file --batch`), never
    the working tree, so uncommitted edits, ignored files and `core.autocrlf` cannot reach it;
  * no clock, no mtime, no mode, no locale, no TZ, no cwd, no PYTHONHASHSEED, no SOURCE_DATE_EPOCH;
  * every walk is sorted by the UTF-8 bytes of the NFC path; text is LF; JSON (none today) would
    be sort_keys with compact separators;
  * the digest is the SHA-256 of `<NFC path> NUL <sha256 of content> LF` per file, in that order.

BUILD DATES (named changes S6 and M2). A date the build prints comes from the newest commit that
touched BUILD INPUT -- `git log -1 --format=%ct HEAD -- site content` -- never from HEAD itself,
because HEAD moves on every commit, including the review-row commit (touching only
`.site-studio/`) that sits between a privacy review and a publish. It is rendered with
`time.gmtime`, so it is UTC and no time zone is read. `{{year}}` is that commit's UTC year; a
sitemap `<lastmod>` is the last commit touching that page's one source file or folder, as a UTC
`YYYY-MM-DD`. `SOURCE_DATE_EPOCH` is deliberately NOT read: a Nix shell exports it as 315532800
(1980), which would make the same commit build differently there and in the desktop app.
Because dates come from history, a SHALLOW repo is refused with one line (a shallow clone returns
the boundary commit's date), and a HISTORY REWRITE (rebase, squash, filter-branch) changes the
committer dates and therefore the digest: it VOIDS every privacy review recorded against the old
digest, and the content must be reviewed again. That is intended: the review is of what was built.

`preview_build` reads the working tree (tracked and untracked-but-not-ignored files), so a draft
the person is writing shows. It has no digest function and no digest attribute; the CLI's
`--digest` flag refuses together with `--drafts`.

DEFAULT LAYOUT AND TOKENS. `site/templates/layout.html` is the page shell for generated pages and
must hold `{{content}}`. Tokens, in the layout, in `site/src` HTML pages and in Markdown bodies:
`{{siteUrl}} {{siteTitle}} {{name}} {{year}} {{root}} {{nav}} {{link:<page>}}`, and in the layout
only `{{title}} {{pageTitle}} {{description}} {{content}}`. An unknown token refuses the build.
`{{link:work}}` and `{{link:work/slug}}` give a RELATIVE link to a built page (generalised from
the examples' site-specific tokens). The convention for size copies is `<stem>-<width>w.<ext>`.
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import struct
import subprocess
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import content as C  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402
from content import ContentError, esc  # noqa: E402

JUNK_NAMES = (".DS_Store", "Thumbs.db")
HTML_EXTS = (".html", ".htm")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
SIZES_ATTR = "(min-width: 60rem) 60rem, 100vw"
PREVIEW_SITE_URL = "http://localhost"


class BuildError(ValueError):
    """The build refuses. The message is one line and names the cause."""


class BuildResult(object):
    """What a build produced. `preview_build` returns exactly this: it has no digest."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes):
        self.out_dir = out_dir
        self.files = files          # sorted output paths (NFC, relative)
        self.pages = pages          # sorted [(output path, kind)]
        self.site_url = site_url
        self.drafts = drafts
        self.notes = notes


class PublishResult(BuildResult):
    """What `publish_build` returns: a BuildResult plus the digest."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes, digest):
        BuildResult.__init__(self, out_dir, files, pages, site_url, drafts, notes)
        self.digest = digest


# ---------------------------------------------------------------- git access

def _git(repo, args, data=None):
    env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))
    env["LC_ALL"] = "C"
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), input=data, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise BuildError("git cannot be run: %s" % e)
    if p.returncode != 0:
        raise BuildError("git %s failed: %s" % (args[0], p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout


def _is_shallow(repo):
    return _git(repo, ["rev-parse", "--is-shallow-repository"]).strip() == b"true"


def _decode_path(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BuildError("a path under site/ or content/ is not valid UTF-8: %r" % raw)


def _is_junk(path):
    return posixpath.basename(path) in JUNK_NAMES


def _commit_files(repo):
    """{path: bytes} for site/ and content/ at HEAD, from the commit's blobs."""
    try:
        out = _git(repo, ["ls-tree", "-r", "-z", "HEAD", "--", "site", "content"])
    except BuildError as e:
        raise BuildError("cannot read HEAD (%s)" % e)
    entries = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, rawpath = rec.partition(b"\t")
        mode, typ, sha = meta.decode("ascii").split()
        path = _decode_path(rawpath)
        if typ != "blob" or mode == "120000":
            raise BuildError("%s is a symlink or submodule; the build reads regular files only" % path)
        if not _is_junk(path):
            entries.append((path, sha))
    files = {}
    if entries:
        shas = "".join("%s\n" % s for _p, s in entries).encode("ascii")
        blob = _git(repo, ["cat-file", "--batch"], data=shas)
        pos = 0
        for path, sha in entries:
            nl = blob.index(b"\n", pos)
            head = blob[pos:nl].decode("ascii").split()
            if len(head) != 3 or head[1] != "blob":
                raise BuildError("git cat-file could not read %s" % path)
            size = int(head[2])
            files[path] = blob[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
    return files


def _disk_files(repo):
    """{path: bytes} for tracked and untracked-but-not-ignored files under site/ and content/."""
    out = _git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard",
                      "--", "site", "content"])
    files = {}
    for raw in out.split(b"\0"):
        if not raw:
            continue
        path = _decode_path(raw)
        full = os.path.join(repo, path)
        if _is_junk(path) or not os.path.isfile(full):
            continue
        if os.path.islink(full):
            raise BuildError("%s is a symlink; the build reads regular files only" % path)
        with open(full, "rb") as fh:
            files[path] = fh.read()
    return files


def _last_commit_epoch(repo, paths):
    out = _git(repo, ["log", "-1", "--format=%ct", "HEAD", "--"] + list(paths), ).strip()
    return int(out) if out else None


def _utc_date(epoch):
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


# ---------------------------------------------------------------- image headers (no media work)

_SOF = (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)


def image_size(data):
    """(width, height) read from the file header, or None when it is not a readable PNG, JPEG,
    GIF or WebP. Nothing is decoded."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            i = 2
            while i + 4 <= len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                while i < len(data) and data[i] == 0xFF:
                    i += 1
                marker = data[i]
                i += 1
                if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
                    continue
                if marker == 0xD9:
                    return None
                seglen = struct.unpack(">H", data[i:i + 2])[0]
                if marker in _SOF:
                    h, w = struct.unpack(">HH", data[i + 3:i + 7])
                    return (w, h)
                i += seglen
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return (w & 0x3FFF, h & 0x3FFF)
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            if chunk == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
    except (struct.error, IndexError):
        return None
    return None


# ---------------------------------------------------------------- text helpers

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STYLE_BLOCK = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.S | re.I)
_TOKEN = re.compile(r"\{\{\s*([A-Za-z]+)(?::([^{}\s]+))?\s*\}\}")


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


DEFAULT_ASSET_NOTE = "unreadable image dimensions"


# ---------------------------------------------------------------- the builder

class _Builder(object):
    def __init__(self, repo, files, cfg, model, site_url, year, repo_for_dates, drafts):
        self.repo = repo
        self.files = files
        self.cfg = cfg
        self.model = model
        self.site_url = site_url
        self.year = year
        self.date_repo = repo_for_dates
        self.drafts = drafts
        self.out = {}            # output path -> bytes
        self.owner = {}          # collision key -> (output path, source)
        self.pages = {}          # output path -> dict(kind, source, title, desc, image, lastmod_src, sitemap)
        self.used_refs = set()
        self.notes = []
        self.media_out = dict((p, nfc(o)) for p, o in model.media.items())

    # ---- output registry
    def add(self, out_path, data, source):
        out_path = nfc(out_path)
        key = out_path.casefold()
        if key in self.owner:
            prev_out, prev_src = self.owner[key]
            raise BuildError("two sources write the same output file: %s (from %s) and %s (from %s)"
                             % (prev_out, prev_src, out_path, source))
        self.owner[key] = (out_path, source)
        self.out[out_path] = data

    # ---- links and tokens
    def preregister(self):
        """Every page's output path, known before any page renders, so {{link:...}} and the nav
        can point at a page that is built later."""
        known = {"index.html"}
        for pf in self.model.portfolios:
            known.add("%s/index.html" % pf.slug)
            for piece in pf.pieces:
                known.add("%s/%s/index.html" % (piece.portfolio, piece.slug))
        if self.model.about is not None:
            known.add("about/index.html")
        if self.model.resume is not None:
            known.add("resume/index.html")
        for path in self.files:
            if path.startswith("site/src/") and path.lower().endswith(HTML_EXTS):
                known.add(nfc(path[len("site/src/"):]))
        self.known = known

    def page_key_to_out(self):
        return dict((_page_dir(o), o) for o in self.known)

    def nav_html(self, current_out):
        items = [("", "Home")]
        for pf in self.model.portfolios:
            items.append((pf.slug, pf.settings["label"]))
        if self.model.about is not None:
            items.append(("about", "About"))
        if self.model.resume is not None:
            items.append(("resume", "Resume"))
        lis = []
        for key, label in items:
            to = "index.html" if key == "" else key + "/index.html"
            cur = ' aria-current="page"' if to == current_out else ""
            lis.append('<li><a href="%s"%s>%s</a></li>' % (rel_link(current_out, to), cur, esc(label)))
        return '<nav class="site-nav"><ul>%s</ul></nav>' % "".join(lis)

    def expand(self, text, current_out, source, extra=None, escape=True):
        keys = self.page_key_to_out()
        keys.setdefault("home", keys.get(""))
        root = rel_link(current_out, "index.html")
        fix = esc if escape else (lambda s: s)
        values = {"siteUrl": self.site_url, "siteTitle": fix(self.cfg.siteTitle),
                  "name": fix(self.cfg.name), "year": str(self.year), "root": root}

        def sub(m):
            name, arg = m.group(1), m.group(2)
            if name == "link":
                if arg is None:
                    raise BuildError("%s: {{link}} needs a page, such as {{link:work/slug}}" % source)
                to = keys.get(arg.strip("/"))
                if to is None:
                    raise BuildError("%s: {{link:%s}} names no built page (a draft never builds)"
                                     % (source, arg))
                return rel_link(current_out, to)
            if name == "nav":
                return self.nav_html(current_out)
            if name in values:
                return values[name]
            if extra and name in extra:
                return extra[name]
            raise BuildError("%s: unknown token {{%s}}" % (source, name))
        return _TOKEN.sub(sub, text)

    # ---- images
    def _img_data(self, repo_path):
        data = self.files.get(repo_path)
        if data is None:
            raise BuildError("%s is not in the build input" % repo_path)
        return data

    def img_tag(self, repo_path, alt, from_out, out_path=None, extra=""):
        """An <img> for a published file: width and height from the header, a srcset from the
        `<stem>-<w>w.<ext>` copies beside it."""
        out_path = out_path or self.media_out[repo_path]
        data = self._img_data(repo_path)
        attrs = ['src="%s"' % esc(rel_link(from_out, out_path)), 'alt="%s"' % esc(alt)]
        if repo_path.lower().endswith(IMAGE_EXTS):
            size = image_size(data)
            if size is None:
                raise BuildError("%s: cannot read the image dimensions from its header; it is not "
                                 "a valid image" % repo_path)
            attrs.append('width="%d" height="%d"' % size)
            stem, ext = posixpath.splitext(posixpath.basename(repo_path))
            copies = []
            rx = re.compile(r"^%s-(\d+)w%s$" % (re.escape(stem), re.escape(ext)))
            folder = posixpath.dirname(repo_path)
            for p in sorted(self.media_out):
                if posixpath.dirname(p) == folder and rx.match(posixpath.basename(p)):
                    s2 = image_size(self.files[p])
                    if s2 is not None:
                        copies.append((s2[0], rel_link(from_out, self.media_out[p])))
            if copies:
                copies.append((size[0], rel_link(from_out, out_path)))
                seen, parts = set(), []
                for w, url in sorted(copies):
                    if w not in seen:
                        seen.add(w)
                        parts.append("%s %dw" % (url, w))
                attrs.append('srcset="%s" sizes="%s"' % (esc(", ".join(parts)), SIZES_ATTR))
        attrs.append('loading="lazy" decoding="async"')
        if extra:
            attrs.append(extra)
        return "<img %s>" % " ".join(attrs)

    def ref_card(self, name, from_out):
        ref = self.model.references.get(name)
        if ref is None:
            raise BuildError("ref: %s names no reference under content/references/" % name)
        self.used_refs.add(name)
        d = ref.data
        img = ""
        if ref.card_path:
            img = self.img_tag(ref.card_path, "", from_out, out_path=self._card_out(ref))
        parts = ['<a class="ref-card" href="%s" rel="noopener">%s' % (esc(d["url"]), img),
                 '<span class="ref-title">%s</span>' % esc(d["title"])]
        if d.get("site"):
            parts.append('<span class="ref-site">%s</span>' % esc(d["site"]))
        if d.get("description"):
            parts.append('<span class="ref-desc">%s</span>' % esc(d["description"]))
        parts.append("</a>")
        return "".join(parts)

    def _card_out(self, ref):
        ext = posixpath.splitext(ref.card_path)[1].lower()
        return "references/%s/card%s" % (ref.name, ext)

    # ---- markdown
    def markdown(self, body, source, from_out, base_dir):
        builder = self

        class Env(object):
            def image(self, src, alt):
                if re.match(r"^https?://", src):
                    return '<img src="%s" alt="%s" loading="lazy" decoding="async">' % (esc(src), esc(alt))
                if src.startswith("/") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", src):
                    raise ContentError("%s: image '%s' must be a relative path or an https URL"
                                       % (source, src))
                full = posixpath.normpath(posixpath.join(base_dir, src))
                if full not in builder.media_out:
                    raise ContentError("%s: image '%s' is not a file in a media/ folder" % (source, src))
                return builder.img_tag(full, alt, from_out)

            def ref_card(self, name):
                try:
                    return builder.ref_card(name, from_out)
                except BuildError as e:
                    raise ContentError("%s: %s" % (source, e))
        text = self.expand(body, from_out, source, escape=False)
        try:
            return C.render_markdown(text, Env(), source)
        except ContentError as e:
            raise BuildError(str(e))

    # ---- page assembly
    def layout(self):
        raw = self.files.get("site/templates/layout.html")
        if raw is None:
            raise BuildError("site/templates/layout.html is missing (the page shell for generated pages)")
        text = strip_html_comments(C.decode_text(raw, "site/templates/layout.html"))
        if "{{content}}" not in text and not re.search(r"\{\{\s*content\s*\}\}", text):
            raise BuildError("site/templates/layout.html must contain {{content}}")
        return text

    def abs_url(self, out_path):
        d = _page_dir(out_path)
        return self.site_url + "/" + d + ("/" if d and (out_path.endswith("index.html")) else "")

    def presence(self, html_text, out_path, title, desc, image_out, og_type):
        """Inject canonical and og/twitter tags before </head>, only those not already present."""
        if "</head>" not in html_text:
            self.notes.append("%s: no </head>, so no canonical or og tags were added" % out_path)
            return html_text
        tags = []
        if not re.search(r"rel=[\"']canonical[\"']", html_text, re.I):
            tags.append('<link rel="canonical" href="%s">' % esc(self.abs_url(out_path)))
        metas = [("og:title", title), ("og:description", desc), ("og:url", self.abs_url(out_path)),
                 ("og:type", og_type), ("og:site_name", self.cfg.siteTitle)]
        if image_out:
            metas.append(("og:image", self.site_url + "/" + image_out))
        for prop, val in metas:
            if val and not re.search(r"property=[\"']%s[\"']" % re.escape(prop), html_text, re.I):
                tags.append('<meta property="%s" content="%s">' % (prop, esc(val)))
        if not re.search(r"name=[\"']twitter:card[\"']", html_text, re.I):
            tags.append('<meta name="twitter:card" content="%s">'
                        % ("summary_large_image" if image_out else "summary"))
        if not tags:
            return html_text
        return html_text.replace("</head>", "".join("  %s\n" % t for t in tags) + "</head>", 1)

    def emit_page(self, out_path, kind, source, title, page_title, desc, content_html, image_out=None,
                  og_type="website", lastmod_src=None, sitemap=True):
        layout = self.layout()
        extra = {"title": esc(title), "pageTitle": esc(page_title), "description": esc(desc),
                 "content": content_html}
        text = self.expand(layout, out_path, "site/templates/layout.html", extra=extra)
        text = self.presence(text, out_path, title, desc, image_out, og_type)
        self.pages[out_path] = {"kind": kind, "source": source, "lastmod_src": lastmod_src,
                                "sitemap": sitemap}
        self.add(out_path, text.encode("utf-8"), source)

    def full_title(self, page_title, home=False):
        return self.cfg.siteTitle if home else "%s | %s" % (page_title, self.cfg.siteTitle)

    # ---- cards
    def card_html(self, piece, from_out):
        to = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        pf = self.model.portfolio(piece.portfolio)
        img = ""
        cover = self.cover_of(piece)
        if cover:
            repo_path, out_path = cover
            pos = piece.meta.get("coverPosition")
            style = 'style="object-position: %s"' % esc(pos) if pos else ""
            img = self.img_tag(repo_path, "", from_out, out_path=out_path, extra=style)
        parts = ['<li class="card"><a href="%s">%s' % (esc(rel_link(from_out, to)), img),
                 '<span class="card-title">%s</span>' % esc(piece.card_title)]
        if piece.meta.get("teaser"):
            parts.append('<span class="card-teaser">%s</span>' % esc(piece.meta["teaser"]))
        cm = [C.meta_text(piece.meta[k]) for k in pf.settings["cardMeta"] if k in piece.meta]
        if cm:
            parts.append('<span class="card-meta">%s</span>' % esc(" · ".join(cm)))
        parts.append("</a></li>")
        return "".join(parts)

    def cover_of(self, piece):
        cv = piece.meta.get("cover")
        if not cv:
            return None
        if cv.startswith("ref:"):
            name = cv[4:]
            ref = self.model.references.get(name)
            if ref is None or not ref.card_path:
                raise BuildError("%s: cover %s names no reference with a card image" % (piece.source, cv))
            self.used_refs.add(name)
            return ref.card_path, self._card_out(ref)
        full = posixpath.normpath(posixpath.join(piece.folder, cv))
        return full, self.media_out[full]

    def cards_html(self, pieces, from_out):
        return '<ul class="cards">%s</ul>' % "".join(self.card_html(p, from_out) for p in pieces)

    # ---- the pages
    def build_portfolios(self):
        for pf in self.model.portfolios:
            out = "%s/index.html" % pf.slug
            st = pf.settings
            if st["groupBy"]:
                body = []
                for g in st["groups"]:
                    ps = [p for p in pf.pieces if p.meta.get(st["groupBy"]) == g]
                    if ps:
                        body.append('<section class="group"><h2>%s</h2>%s</section>'
                                    % (esc(g), self.cards_html(ps, out)))
                cards = "".join(body)
            else:
                cards = self.cards_html(pf.pieces, out) if pf.pieces else ""
            intro = self.markdown(pf.intro, pf.page_source or "content/%s" % pf.slug, out,
                                  "content/" + pf.slug) if pf.intro.strip() else ""
            desc = st["description"] or C.plain_excerpt(pf.intro) or \
                "%s: %s" % (self.cfg.siteTitle, st["label"])
            self.emit_page(out, "portfolio", pf.page_source or "content/%s/" % pf.slug,
                           self.full_title(pf.title), pf.title, desc,
                           '<article class="portfolio"><h1>%s</h1>%s%s</article>'
                           % (esc(pf.title), intro, cards))
            for piece in pf.pieces:
                self.build_piece(pf, piece)

    def build_piece(self, pf, piece):
        out = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        meta_rows = "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(k[:1].upper() + k[1:]),
                            esc(C.meta_text(piece.meta[k]))) for k in pf.settings["meta"]
                            if k in piece.meta)
        dl = '<dl class="meta">%s</dl>' % meta_rows if meta_rows else ""
        body = self.markdown(piece.body, piece.source, out, piece.folder)
        desc = piece.meta.get("description") or piece.meta.get("teaser") or \
            C.plain_excerpt(piece.body) or "%s: %s" % (piece.title, self.cfg.siteTitle)
        cover = self.cover_of(piece)
        self.emit_page(out, "piece", piece.source, self.full_title(piece.title), piece.title, desc,
                       '<article class="piece"><h1>%s</h1>%s%s</article>' % (esc(piece.title), dl, body),
                       image_out=cover[1] if cover else None, og_type="article",
                       lastmod_src=piece.folder)

    def contact_html(self, contact):
        rows = []
        for label, value in contact.items():
            if re.match(r"^[^@\s]+@[^@\s]+$", value):
                v = '<a href="mailto:%s">%s</a>' % (esc(value), esc(value))
            elif re.match(r"^https?://", value):
                v = '<a href="%s" rel="noopener">%s</a>' % (esc(value), esc(value))
            else:
                v = esc(value)
            rows.append("<div><dt>%s</dt><dd>%s</dd></div>" % (esc(label), v))
        return '<dl class="contact">%s</dl>' % "".join(rows)

    def page_extras(self, page, out):
        """photo, endorsement, contact blocks shared by home and about."""
        parts = {"photo": "", "endorsement": "", "contact": ""}
        meta = page.meta
        if "photo" in meta:
            full = posixpath.normpath(posixpath.join("content", meta["photo"]))
            if full not in self.media_out:
                raise BuildError("%s: photo '%s' is not a file in content/media/" % (page.source, meta["photo"]))
            parts["photo"] = '<figure class="photo">%s</figure>' % self.img_tag(full, meta["photoAlt"], out)
        if "endorsement" in meta:
            e = meta["endorsement"]
            by = "<footer>%s</footer>" % esc(e["by"]) if e.get("by") else ""
            parts["endorsement"] = ('<blockquote class="endorsement"><p>%s</p>%s</blockquote>'
                                    % (esc(e["quote"]), by))
        if "contact" in meta:
            parts["contact"] = "<h2>Contact</h2>" + self.contact_html(meta["contact"])
        return parts

    def build_home(self):
        out = "index.html"
        page = self.model.home
        meta = page.meta if page else {}
        title = meta.get("title") or self.cfg.siteTitle
        pieces = []
        for key in meta.get("featured", []):
            pc = self.model.piece(key)
            if pc is None:
                raise BuildError("content/home.md: featured '%s' is not a built piece (a draft "
                                 "never builds)" % key)
            pieces.append(pc)
        feed = []
        for name in meta.get("feed", []):
            feed.append(self.ref_card(name, out))
        extras = self.page_extras(page, out) if page else {"photo": "", "endorsement": "", "contact": ""}
        intro = self.markdown(page.body, page.source, out, "content") if page else ""
        body = '<section class="intro">%s%s</section>%s' % (extras["photo"], intro, extras["endorsement"])
        if pieces:
            body += '<section class="featured"><h2>Featured</h2>%s</section>' % self.cards_html(pieces, out)
        if feed:
            body += ('<section class="feed"><h2>Elsewhere</h2><div class="ref-grid">%s</div></section>'
                     % "".join(feed))
        body += extras["contact"]
        desc = meta.get("description") or (C.plain_excerpt(page.body) if page else "") or self.cfg.siteTitle
        image = self.media_out.get(posixpath.normpath("content/" + meta["photo"])) if "photo" in meta else None
        self.emit_page(out, "home", page.source if page else "(generated)",
                       self.full_title(title, home=True), title, desc,
                       '<article class="home"><h1>%s</h1>%s</article>' % (esc(title), body),
                       image_out=image, lastmod_src=None)

    def build_about(self):
        page = self.model.about
        out = "about/index.html"
        meta = page.meta
        title = meta.get("title") or "About"
        extras = self.page_extras(page, out)
        intro = self.markdown(page.body, page.source, out, "content")
        desc = meta.get("description") or C.plain_excerpt(page.body) or \
            "About %s" % self.cfg.name
        image = self.media_out.get(posixpath.normpath("content/" + meta["photo"])) if "photo" in meta else None
        self.emit_page(out, "about", page.source, self.full_title(title), title, desc,
                       '<article class="about"><h1>%s</h1>%s%s%s%s</article>'
                       % (esc(title), extras["photo"], intro, extras["endorsement"], extras["contact"]),
                       image_out=image, lastmod_src=page.source)

    def build_resume(self):
        page = self.model.resume
        out = "resume/index.html"
        title = page.meta.get("title") or "Resume"
        body = self.markdown(page.body, page.source, out, posixpath.dirname(page.source))
        link = ""
        if self.model.resume_pdf:
            pdf_path, pdf = self.model.resume_pdf
            pdf_out = "resume/" + posixpath.basename(pdf_path)
            self.add(pdf_out, pdf, pdf_path)
            link = '<p class="download"><a href="%s">Download as PDF</a></p>' % esc(
                rel_link(out, pdf_out))
        desc = page.meta.get("description") or "Resume of %s" % self.cfg.name
        self.emit_page(out, "resume", page.source, self.full_title(title), title, desc,
                       '<article class="resume"><h1>%s</h1>%s%s</article>' % (esc(title), link, body),
                       lastmod_src=page.source)

    # ---- site/src
    def build_site_src(self):
        for path in sorted(self.files):
            if not path.startswith("site/src/"):
                continue
            rel = path[len("site/src/"):]
            raw = self.files[path]
            low = rel.lower()
            if low.endswith(HTML_EXTS):
                text = strip_html_comments(C.decode_text(raw, path))
                text = self.expand(text, nfc(rel), path)
                title = _meta_title(text) or rel
                desc = _meta_description(text) or ""
                text = self.presence(text, nfc(rel), title, desc, None, "website")
                self.pages[nfc(rel)] = {"kind": "site", "source": path, "lastmod_src": path,
                                        "sitemap": posixpath.basename(rel) != "404.html"}
                self.add(rel, text.encode("utf-8"), path)
            elif low.endswith(".css"):
                self.add(rel, strip_css_comments(C.decode_text(raw, path)).encode("utf-8"), path)
            elif low.endswith(C.TEXT_EXTS):
                self.add(rel, C.decode_text(raw, path).encode("utf-8"), path)
            else:
                self.add(rel, raw, path)

    def build_media(self):
        for repo_path, out_path in sorted(self.media_out.items()):
            self.add(out_path, self.files[repo_path], repo_path)
        for name in sorted(self.used_refs):
            ref = self.model.references[name]
            if ref.card_path:
                self.add(self._card_out(ref), self.files[ref.card_path], ref.card_path)

    def build_redirects(self):
        targets = self.page_key_to_out()
        for old in sorted(self.cfg.redirects):
            new = self.cfg.redirects[old]
            old_clean = old.strip("/")
            out = old_clean if old_clean.lower().endswith(HTML_EXTS) else old_clean + "/index.html"
            if nfc(out).casefold() in self.owner:
                raise BuildError("redirect '%s' would replace a real page (%s from %s)"
                                 % (old, self.owner[nfc(out).casefold()][0],
                                    self.owner[nfc(out).casefold()][1]))
            if re.match(r"^https?://", new):
                href, canonical = new, new
            else:
                to = targets.get(new.strip("/"))
                if to is None:
                    raise BuildError("redirect '%s' points at '%s', which is not a built page" % (old, new))
                href, canonical = rel_link(out, to), self.abs_url(to)
            text = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                    '<title>Redirecting</title>\n<meta name="robots" content="noindex">\n'
                    '<link rel="canonical" href="%s">\n<meta http-equiv="refresh" content="0; url=%s">\n'
                    '</head>\n<body>\n<p>This page has moved: <a href="%s">continue</a>.</p>\n'
                    '</body>\n</html>\n' % (esc(canonical), esc(href), esc(href)))
            self.pages[nfc(out)] = {"kind": "redirect", "source": "site.json redirects",
                                    "lastmod_src": None, "sitemap": False}
            self.add(out, text.encode("utf-8"), "site.json redirects")

    # ---- sitemap, robots, markers
    def build_sitemap(self, lastmod):
        entries = []
        for out_path in sorted(self.pages):
            info = self.pages[out_path]
            if not info["sitemap"]:
                continue
            loc = self.abs_url(out_path)
            lm = lastmod(info["lastmod_src"]) if info["lastmod_src"] else None
            entries.append((loc, lm))
        entries.sort()
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for loc, lm in entries:
            lines.append("  <url><loc>%s</loc>%s</url>" % (esc(loc), "<lastmod>%s</lastmod>" % lm if lm else ""))
        lines.append("</urlset>")
        self.add("sitemap.xml", ("\n".join(lines) + "\n").encode("utf-8"), "generated")
        self.add("robots.txt", ("User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n"
                                % self.site_url).encode("utf-8"), "generated")
        self.add(".nojekyll", b"", "generated")
        if self.cfg.cutover:
            self.add("CNAME", (self.cfg.domain + "\n").encode("utf-8"), "site.json cutover")


def _write_outputs(out_dir, out):
    for rel in sorted(out, key=lambda p: p.encode("utf-8")):
        full = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        data = out[rel]
        if rel.lower().endswith(C.TEXT_EXTS) or rel in ("CNAME", "robots.txt") or \
                rel.lower().endswith(HTML_EXTS):
            if b"\r" in data:
                raise BuildError("%s would be written with a carriage return" % rel)
        with open(full, "wb") as fh:
            fh.write(data)
        os.chmod(full, 0o644)


def _check_out_dir(out_dir):
    if os.path.exists(out_dir) and (not os.path.isdir(out_dir) or os.listdir(out_dir)):
        raise BuildError("%s already exists and is not empty; build into a new or empty folder"
                         % out_dir)


def _digest_tree(out_dir):
    """The digest of design 3.5: SHA-256 of `<NFC path> NUL <hex sha256 of content> LF` per
    regular file, in the order of the UTF-8 bytes of the NFC path. Private: only
    `publish_build` calls it."""
    entries = []
    for d, _dirs, names in os.walk(out_dir):
        for n in names:
            full = os.path.join(d, n)
            rel = nfc(os.path.relpath(full, out_dir).replace(os.sep, "/"))
            with open(full, "rb") as fh:
                entries.append((rel.encode("utf-8"), hashlib.sha256(fh.read()).hexdigest()))
    h = hashlib.sha256()
    for rel_b, sha in sorted(entries):
        h.update(rel_b + b"\0" + sha.encode("ascii") + b"\n")
    return h.hexdigest()


def digest_output_tree(path):
    """The design 3.5 digest of an arbitrary DIRECTORY of output files (dev #835, finding F1).

    A public wrapper over the private `_digest_tree`, same formula, so `deploy.py` can digest the
    PUBLIC clone's tree (publish step 2.5 and 5.5) without a second implementation that could
    drift. It does NOT build anything and is not reachable from `preview_build`, whose result
    still has no digest attribute. The caller owns what the directory holds."""
    if not os.path.isdir(path):
        raise BuildError("%s is not a folder" % path)
    return _digest_tree(path)


def _run(repo, out_dir, drafts):
    repo = os.path.abspath(repo)
    out_dir = os.path.abspath(out_dir)
    _check_out_dir(out_dir)
    if drafts:
        files = _disk_files(repo)
    else:
        if _is_shallow(repo):
            raise BuildError("this clone is shallow, so build dates cannot be trusted; run "
                             "`git fetch --unshallow` and build again")
        files = _commit_files(repo)
    raw = files.get("site/site.json")
    if raw is None:
        raise BuildError("site/site.json is not in the build input")
    try:
        cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
        model = C.load_content(files, cfg, drafts=drafts, check_resume_pdf=not drafts)
    except (siteconfig.SiteConfigError, ContentError) as e:
        raise BuildError(str(e))
    site_url = cfg.site_url()
    if site_url is None:
        if not drafts:
            raise BuildError("site.json has no 'previewUrl' (and no cutover): share tags and the "
                             "sitemap need an absolute address")
        site_url = PREVIEW_SITE_URL
    epoch = _last_commit_epoch(repo, ["site", "content"])
    if epoch is None:
        if not drafts:
            raise BuildError("no commit touches site/ or content/, so there is nothing to build")
        year = time.gmtime().tm_year    # preview only: a repo with nothing committed yet
    else:
        year = time.gmtime(epoch).tm_year

    def lastmod(src):
        if drafts:
            return None
        e = _last_commit_epoch(repo, [src])
        return _utc_date(e) if e is not None else None

    b = _Builder(repo, files, cfg, model, site_url, year, repo, drafts)
    b.preregister()
    b.build_site_src()
    b.build_portfolios()
    if model.about is not None:
        b.build_about()
    if model.resume is not None:
        b.build_resume()
    b.build_home()
    b.build_media()
    b.build_redirects()
    b.build_sitemap(lastmod)
    os.makedirs(out_dir, exist_ok=True)
    _write_outputs(out_dir, b.out)
    files_out = sorted(b.out, key=lambda p: p.encode("utf-8"))
    pages = sorted((p, b.pages[p]["kind"]) for p in b.pages)
    return out_dir, files_out, pages, site_url, b.notes


def publish_build(repo, out_dir):
    """The one digested build: committed tree at HEAD, no drafts. Returns a PublishResult."""
    out_dir, files, pages, site_url, notes = _run(repo, out_dir, drafts=False)
    return PublishResult(out_dir, files, pages, site_url, False, notes, _digest_tree(out_dir))


def preview_build(repo, out_dir):
    """A drafts-included build of the working tree. Returns a BuildResult with NO digest."""
    out_dir, files, pages, site_url, notes = _run(repo, out_dir, drafts=True)
    return BuildResult(out_dir, files, pages, site_url, True, notes)


# ---------------------------------------------------------------- inventory

def inventory(repo):
    """`--list`: what the working tree holds, drafts included."""
    repo = os.path.abspath(repo)
    files = _disk_files(repo)
    raw = files.get("site/site.json")
    if raw is None:
        raise BuildError("site/site.json is not in the working tree")
    try:
        cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
        model = C.load_content(files, cfg, drafts=True)
    except (siteconfig.SiteConfigError, ContentError) as e:
        raise BuildError(str(e))
    inv = {"portfolios": [], "references": sorted(model.references),
           "pages": [n for n, p in (("home", model.home), ("about", model.about),
                                    ("resume", model.resume)) if p is not None]}
    for pf in model.portfolios:
        inv["portfolios"].append({
            "slug": pf.slug, "label": pf.settings["label"],
            "pieces": [{"slug": p.slug, "title": p.title, "draft": p.draft, "date": p.date,
                        "group": p.meta.get(pf.settings["groupBy"]) if pf.settings["groupBy"] else None}
                       for p in pf.pieces]})
    return inv


def format_inventory(inv):
    lines = []
    for pf in inv["portfolios"]:
        lines.append("portfolio %s (%s): %d piece(s)" % (pf["slug"], pf["label"], len(pf["pieces"])))
        for p in pf["pieces"]:
            extra = " [draft]" if p["draft"] else ""
            if p["group"]:
                extra += " group=%s" % p["group"]
            lines.append("  %s/%s  %s%s" % (pf["slug"], p["slug"], p["title"], extra))
    if inv["references"]:
        lines.append("references: %s" % ", ".join(inv["references"]))
    lines.append("pages: %s" % (", ".join(inv["pages"]) or "none"))
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    rc = platform_check.windows_refusal_rc("build.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="build.py", allow_abbrev=False,
                                 description="Build the site from the dev repo (dev #835).")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--out", help="output folder (default <repo>/site/dist, replaced each time)")
    ap.add_argument("--drafts", action="store_true", help="a preview build of the working tree")
    ap.add_argument("--digest", action="store_true", help="print the build digest (publish build only)")
    ap.add_argument("--list", action="store_true", help="list pieces, references and pages")
    ap.add_argument("--json", action="store_true", help="with --list: JSON")
    args = ap.parse_args(argv)
    if args.digest and args.drafts:
        ap.error("--digest refuses --drafts: a draft build has no digest")
    try:
        if args.list:
            inv = inventory(args.repo)
            print(json.dumps(inv, indent=2, sort_keys=True) if args.json else format_inventory(inv))
            return 0
        out = args.out
        if out is None:
            out = os.path.join(os.path.abspath(args.repo), "site", "dist")
            if os.path.isdir(out):
                import shutil
                shutil.rmtree(out)
        if args.drafts:
            res = preview_build(args.repo, out)
        else:
            res = publish_build(args.repo, out)
        print("built %d files into %s" % (len(res.files), res.out_dir))
        for n in res.notes:
            print("note: " + n)
        if args.digest:
            print("digest: %s" % res.digest)
        return 0
    except BuildError as e:
        print("build refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
