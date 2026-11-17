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
  * the digest is the SHA-256 of `<NFC path> NUL <sha256 of content> LF` per file, in that order,
    followed by ONE final line, `siteKind NUL <kind> LF`, when and only when the site's `siteKind`
    is not `portfolio` (dev #857, design-site-adoption section 9). A `hub` and a `custom` site build
    identically from the same `site/src`, yet the reviewers' briefs differ by kind, so a kind change
    must void every recorded verdict. A portfolio's digest has no such line, so it is byte-identical
    to the 0.1.0 digest and the upgrade voids no recorded review (test_build.PortfolioUnchanged).

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

SITE KINDS (dev #857, design-site-adoption section 4). `site.json` `siteKind` is `portfolio` (the
default: the generated home, portfolios, about and resume, as 0.1.0), `hub` or `custom`. A `hub` or
`custom` site builds every page from `site/src/` as written, with tokens expanded, and GENERATES
NOTHING: no home, no portfolio, no resume. It refuses portfolio content (`content/home.md`,
`content/about.md`, portfolio folders, a resume source) and the `work`, `resume` and `featuredFrom`
keys, and it requires `site/src/index.html`. `{{nav}}` on such a site is exactly one Home item.
Every other site.json key (redirects, budgets, privateTerms, publicEmails, cutover) applies
unchanged. Before it builds, `siteconfig.check_tree_schema` refuses a schema-1 `site.json` over a
tree that needs schema 2.

ONE HOME SOURCE (dev #856, design-site-adoption section 4.3). For a portfolio the home page has ONE
authored source: a hand-made `site/src/index.html` (the generated home is skipped; the site is schema
2) or `content/home.md` (the generated home, as 0.1.0), never both: two refuse, naming both files. With
neither, the generated home is built from the site title, as 0.1.0 does.

DISPLAY LABELS (dev #853, section 5). `work.labels` (or a portfolio's `page.md` `labels`) names what a
meta key and a group are CALLED where they are printed: the `<dt>` on a piece page, a labelled key's
value on a card (`Label: value`; a bare key prints its value alone, as 0.1.0), and a group heading on
the index. A key with no label keeps today's derived label.

SECTIONS AND THE FEATURED SELECTION (dev #852, section 6). `{{#page:X}}...{{/page}}` renders its block
only when page X is built in this build, and nothing otherwise; an X that could not exist for the site,
an unclosed section and a nested one are refused. `{{featured}}` renders the selection as cards: the
`content/home.md` `featured:` list (the default, as 0.1.0) or, under `featuredFrom: "flags"`, the pieces
whose front matter says `featured: true`, in portfolio then piece order, a draft never.

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
from siteconfig import SiteConfigError  # noqa: E402

# The plugin's own output files (site-fidelity section 7.7): the block stylesheet and the facade script live in
# the PLUGIN at templates/output/, are copied into a site's output only when a page uses a block, and never
# touch the person's source. Each is `{kind: (path under templates/output/ and in the output)}`.
OUTPUT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates", "output"))
PLUGIN_ASSETS = {"css": "site-studio/blocks.css", "js": "site-studio/video.js"}
# The content model that SHIPS (dev #876): `reference/content-model.md`, generated from the code's own tables by
# tests/gen_content_model.py and checked against them by tests/test_content_model_generated.py. It is found from this
# file's own location, never from ${CLAUDE_PLUGIN_ROOT}, which Claude Code does not set in the environment of a
# command run through the Bash tool. A message that points a person at it names this absolute, installed path.
CONTENT_MODEL = os.path.normpath(os.path.join(HERE, "..", "reference", "content-model.md"))

JUNK_NAMES = (".DS_Store", "Thumbs.db")
HTML_EXTS = (".html", ".htm")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
SIZES_ATTR = "(min-width: 60rem) 60rem, 100vw"
PREVIEW_SITE_URL = "http://localhost"


class BuildError(ValueError):
    """The build refuses. The message is one line and names the cause.

    `path`, `lineno` and `fix` (design-site-fidelity section 4.1) say where, on which line when the check
    knows it, and the one-line remedy; `build.accept` turns them into a `siteconfig.Problem`. `problems`
    is the whole list when the build refused for several things at once (the message is then the join of
    theirs; with one problem it is exactly that problem's message)."""

    def __init__(self, message="", path=None, lineno=None, fix=None, problems=None):
        ValueError.__init__(self, message)
        self.path = path
        self.lineno = lineno
        self.fix = fix
        self.problems = list(problems or [])


class Acceptance(object):
    """What `accept` returns: every `problem` (a `siteconfig.Problem`, ordered by path), the `notes`, and
    what was built in memory when it got that far (`cfg`, `model`, `output` {output path: bytes}, `pages`).
    `warnings` is a list of the same `make_problem` shape, kept APART from `problems`: `problems` means the
    build refuses, a warning means it builds and says what it does not publish (a stray `.md` or folder in a
    piece folder, an unknown piece key; dev #885, dev #882). Empty `problems` with warnings is still an
    accepted tree whose output bytes the warnings never change; `adopt check` may refuse one."""

    def __init__(self, problems, notes, cfg, model, output, pages, warnings=None):
        self.problems = problems
        self.notes = notes
        self.warnings = list(warnings or [])
        self.cfg = cfg
        self.model = model
        self.output = output
        self.pages = pages


class BuildResult(object):
    """What a build produced. `preview_build` returns exactly this: it has no digest."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes, warnings=None):
        self.out_dir = out_dir
        self.files = files          # sorted output paths (NFC, relative)
        self.pages = pages          # sorted [(output path, kind)]
        self.site_url = site_url
        self.drafts = drafts
        self.notes = notes
        self.warnings = list(warnings or [])      # `Acceptance.warnings` of this build (dev #885, dev #882)


class PublishResult(BuildResult):
    """What `publish_build` returns: a BuildResult plus the digest and the site kind it covers."""

    def __init__(self, out_dir, files, pages, site_url, drafts, notes, digest, site_kind="portfolio",
                 warnings=None):
        BuildResult.__init__(self, out_dir, files, pages, site_url, drafts, notes, warnings)
        self.digest = digest
        self.site_kind = site_kind


# ---------------------------------------------------------------- git access

def _git(repo, args, data=None):
    env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))
    env["LC_ALL"] = "C"
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), input=data, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise BuildError("git cannot be run: %s" % e, fix="install git and make sure it is on your PATH")
    if p.returncode != 0:
        raise BuildError("git %s failed: %s" % (args[0], p.stderr.decode("utf-8", "replace").strip()), fix="run git in the dev repo yourself, fix what it reports, then build again")
    return p.stdout


def _is_shallow(repo):
    return _git(repo, ["rev-parse", "--is-shallow-repository"]).strip() == b"true"


def _decode_path(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BuildError("a path under site/ or content/ is not valid UTF-8: %r" % raw, fix="rename the file with a UTF-8 name, or remove it from site/ and content/")


def _is_junk(path):
    return posixpath.basename(path) in JUNK_NAMES


def _commit_files(repo):
    """{path: bytes} for site/ and content/ at HEAD, from the commit's blobs."""
    try:
        out = _git(repo, ["ls-tree", "-r", "-z", "HEAD", "--", "site", "content"])
    except BuildError as e:
        raise BuildError("cannot read HEAD (%s)" % e, fix="make at least one commit in the dev repo, then build again")
    entries = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, rawpath = rec.partition(b"\t")
        mode, typ, sha = meta.decode("ascii").split()
        path = _decode_path(rawpath)
        if typ != "blob" or mode == "120000":
            raise BuildError("%s is a symlink or submodule; the build reads regular files only" % path, fix="replace the symlink or submodule with the real file or folder")
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
                raise BuildError("git cat-file could not read %s" % path, fix="run `git fsck` in the dev repo, then build again")
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
            raise BuildError("%s is a symlink; the build reads regular files only" % path, fix="replace the symlink with the real file")
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
    "nav": "nav", "link": "link", "featured": "featured", "home": "home",
    "title": "layout", "pageTitle": "layout", "description": "layout", "content": "layout",
}


# The size-copy namings schema 3 reads IN ADDITION to `<stem>-<w>w.<ext>` (design-site-fidelity section 5.3, I-3):
# a copy sits beside its original and its file keeps its name and its public URL, so nothing is renamed and no
# image address changes. Each pattern takes (stem, extension); below schema 3 such a file is a plain media file.
SIZE_COPY_SHAPES = ((r"^%s\.w(\d+)%s$", ".wNNN"),)


def token_known(name, layout=False):
    """True when the build expands `{{name...}}` in a page, or in the layout when `layout` is true. A true
    answer is not "it will build": `{{link}}` with no page is still refused, by the build, with its fix."""
    scope = TOKEN_SCOPES.get(name)
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


DEFAULT_ASSET_NOTE = "unreadable image dimensions"


# ---------------------------------------------------------------- the builder

class _Builder(object):
    def __init__(self, repo, files, cfg, model, site_url, year, repo_for_dates, drafts, grammar=None):
        self.repo = repo
        self.grammar = cfg.schema if grammar is None else grammar     # the schema whose Markdown reading applies
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
        self._selection = None
        self._home_split = {}            # output page -> (intro, parts) of content/home.md for `{{home:<part>}}`
        self.assets_emitted = set()      # (page, kind) already linked, so a page links each plugin file once
        self.assets_used = set()         # kinds ("css", "js") some page links: those files are written

    def asset_html(self, from_out, kind):
        """The tag that links a plugin output file from `from_out`, the FIRST time a page uses a block that
        needs it; "" after that (design-site-fidelity section 7.7). A stylesheet is linked from the body (a
        link a body may hold), so the person's layout is never edited, and a page with no plugin block links
        nothing."""
        key = (from_out, kind)
        if key in self.assets_emitted:
            return ""
        self.assets_emitted.add(key)
        self.assets_used.add(kind)
        href = esc(rel_link(from_out, PLUGIN_ASSETS[kind]))
        if kind == "css":
            return '<link rel="stylesheet" href="%s">' % href
        return '<script src="%s" defer></script>' % href

    def build_plugin_assets(self):
        """Write each plugin output file some page linked, from the plugin's templates/output/. A missing
        template is a refusal, never a page that links a file the build did not write."""
        for kind in sorted(self.assets_used):
            rel = PLUGIN_ASSETS[kind]
            path = os.path.join(OUTPUT_TEMPLATES, *rel.split("/"))
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                raise BuildError("the site-studio install is missing templates/output/%s; reinstall the plugin"
                                 % rel, fix="reinstall the site-studio plugin, which ships that file")
            if kind == "css":      # the build publishes no CSS comment (check_site's `comments` family proves it)
                data = strip_css_comments(C.decode_text(data, rel)).lstrip("\n").encode("utf-8")
            self.add(rel, data, "templates/output/" + rel)

    # ---- output registry
    def add(self, out_path, data, source):
        out_path = nfc(out_path)
        key = out_path.casefold()
        if key in self.owner:
            prev_out, prev_src = self.owner[key]
            raise BuildError("two sources write the same output file: %s (from %s) and %s (from %s)"
                             % (prev_out, prev_src, out_path, source), fix="rename or remove one of the two files so each output path has one source")
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
        # what a `{{#page:X}}` may NAME: a page that could exist for this site, built or not (a draft,
        # a resume not yet committed), so a misspelt X is refused instead of rendering nothing forever
        exist = {"home"}
        for path in self.files:
            if path.startswith("site/src/") and path.lower().endswith(HTML_EXTS):
                exist.add(_page_dir(nfc(path[len("site/src/"):])))
        if self.cfg.siteKind == "portfolio":
            exist |= {"about", "resume", "work"}
            slugs = set(pf.slug for pf in self.model.portfolios)
            exist |= slugs
            for path in self.files:
                parts = path.split("/")
                if (len(parts) == 4 and parts[0] == "content" and parts[1] in slugs
                        and parts[3] == "index.md"):
                    exist.add("%s/%s" % (parts[1], parts[2]))
        self.could_exist = exist

    def page_key_to_out(self):
        return dict((_page_dir(o), o) for o in self.known)

    @staticmethod
    def single_piece(pf):
        """True when `menuLinks: "single-piece"` applies: the portfolio builds exactly one piece and its index is
        the generated one. The nav then links the piece, and the index URL is served as a redirect page to it, so
        the old address keeps working and the published site has no page that nothing links (dev #864 C2: the
        build accepted a page `check_site.py` refuses as unreachable). Under `view: "page"` the index is the
        person's own page, which the build never replaces, so the nav keeps linking it."""
        st = pf.settings
        return st["menuLinks"] == "single-piece" and len(pf.pieces) == 1 and st["view"] != "page"

    def nav_html(self, current_out):
        items = [("", "Home")]
        for pf in self.model.menu_portfolios():
            if self.single_piece(pf):       # schema 3: the one piece
                items.append(("%s/%s" % (pf.slug, pf.pieces[0].slug), pf.settings["label"]))
            else:
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

    def sections(self, text, source):
        """Resolve `{{#page:X}}...{{/page}}` before any token is read: a block whose page is built stays
        (its markers gone), any other block is dropped whole, so a `{{link:X}}` inside an absent section
        is never looked up. Refuses an unclosed, a stray and a nested section, and an X that could not
        exist for this site (design section 6.1)."""
        keys = self.page_key_to_out()
        keys.setdefault("home", keys.get(""))
        out, pos, name = [], 0, None
        for m in _SECTION.finditer(text):
            if m.group(1) is not None:
                if name is not None:
                    raise BuildError("%s: {{#page:%s}} opens inside the section {{#page:%s}}; sections do "
                                     "not nest" % (source, m.group(1), name), fix="close the first section with {{/page}} before opening the next")
                name = m.group(1).strip("/")
                if name not in self.could_exist and name not in keys:
                    raise BuildError("%s: {{#page:%s}} names a page this site cannot have (a misspelt "
                                     "name would render nothing for ever)" % (source, name), fix="fix the page name in {{#page:...}}, or remove the section")
                out.append(text[pos:m.start()])
                pos = m.end()
            else:
                if name is None:
                    raise BuildError("%s: {{/page}} closes a section that was never opened" % source, fix="remove the stray {{/page}}, or add the opening {{#page:name}}")
                if name in keys:
                    out.append(text[pos:m.start()])
                name, pos = None, m.end()
        if name is not None:
            raise BuildError("%s: {{#page:%s}} is never closed with {{/page}}" % (source, name), fix="add {{/page}} after the section's content, or remove the opening {{#page:...}}")
        out.append(text[pos:])
        return "".join(out)

    def selection(self):
        """The featured pieces, once per build: `content/home.md`'s `featured:` list in its order
        (featuredFrom home, as 0.1.0), or the pieces flagged `featured: true` (featuredFrom flags), in
        portfolio then piece order, a draft never (section 6.2)."""
        if self._selection is None:
            if self.cfg.featuredFrom == "flags":
                self._selection = [pc for pf in self.model.portfolios for pc in pf.pieces
                                   if pc.meta.get("featured") is True and not pc.draft]
            else:
                meta = self.model.home.meta if self.model.home else {}
                pieces = []
                for key in meta.get("featured", []):
                    pc = self.model.piece(key)
                    if pc is None:
                        raise BuildError("content/home.md: featured '%s' is not a built piece (a draft "
                                         "never builds)" % key, fix="fix the name in featured:, or publish the draft piece")
                    pieces.append(pc)
                self._selection = pieces
        return self._selection

    def expand(self, text, current_out, source, extra=None, escape=True, featured=False, origin=None, home=False):
        """`origin` is the file's own text, when the caller has changed `text` (comments stripped): an
        unknown token's line number is then read from the file as the person wrote it. `home` is true only for
        a site/src page, the one place `{{home:<part>}}` is read."""
        text = self.sections(text, source)
        keys = self.page_key_to_out()
        keys.setdefault("home", keys.get(""))
        root = rel_link(current_out, "index.html")
        fix = esc if escape else (lambda s: s)
        values = {"siteUrl": self.site_url, "siteTitle": fix(self.cfg.siteTitle),
                  "name": fix(self.cfg.name), "year": str(self.year), "root": root}

        def sub(m):
            name, arg = m.group(1), m.group(2)
            scope = TOKEN_SCOPES.get(name)
            if scope is None or (scope == "layout" and not (extra and name in extra)):
                at = (origin or "").find(m.group(0))
                raise BuildError("%s: unknown token {{%s}}" % (source, name),
                                 lineno=(origin.count("\n", 0, at) + 1) if origin and at >= 0 else None,
                                 fix="check the spelling of the token, or remove it (the tokens are listed in "
                                     "%s)" % CONTENT_MODEL)
            if name == "home":
                nth = text.count(m.group(0), 0, m.start())
                return self.home_part(arg, current_out, source, _line_of(origin, m.group(0), nth) if origin else None, home)
            if name == "link":
                if arg is None:
                    raise BuildError("%s: {{link}} needs a page, such as {{link:work/slug}}" % source, fix="write {{link:work}} or {{link:work/slug}}")
                to = keys.get(arg.strip("/"))
                if to is None:
                    raise BuildError("%s: {{link:%s}} names no built page (a draft never builds)"
                                     % (source, arg), fix="check the page name, or build that page (a draft never builds)")
                return rel_link(current_out, to)
            if name == "nav":
                return self.nav_html(current_out)
            if name == "featured" and arg is None:
                if self.cfg.siteKind != "portfolio":
                    raise BuildError("%s: {{featured}} is only for a portfolio site; a %s site has no pieces"
                                     % (source, self.cfg.siteKind), fix="remove {{featured}} from this page, or set siteKind to portfolio")
                if not featured:
                    raise BuildError("%s: {{featured}} is for site/src pages and the layout; a Markdown "
                                     "body is escaped, so it would print as text" % source, fix="move {{featured}} to a site/src page or the layout")
                sel = self.selection()
                return self.cards_html(sel, current_out) if sel else ""
            if name in values:
                return values[name]
            if extra and name in extra:
                return extra[name]
            raise BuildError("%s: unknown token {{%s}}" % (source, name), fix="check the spelling of the token, or remove it (the tokens are listed in %s)" % CONTENT_MODEL)
        return _TOKEN.sub(sub, text)

    # ---- images
    def _img_data(self, repo_path):
        data = self.files.get(repo_path)
        if data is None:
            raise BuildError("%s is not in the build input" % repo_path, fix="commit the file, or fix the path that names it")
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
                                 "a valid image" % repo_path, fix="replace the file with a valid PNG, JPEG, GIF or WebP image")
            attrs.append('width="%d" height="%d"' % size)
            stem, ext = posixpath.splitext(posixpath.basename(repo_path))
            copies = []
            rx = re.compile(r"^%s-(\d+)w%s$" % (re.escape(stem), re.escape(ext)))
            folder = posixpath.dirname(repo_path)
            shapes = [rx] if self.grammar < 3 else [rx] + [      # I-3: schema 3 reads these namings too (F4)
                re.compile(pat % (re.escape(stem), re.escape(ext))) for pat, _name in SIZE_COPY_SHAPES]
            for p in sorted(self.media_out):
                if posixpath.dirname(p) == folder and any(r.match(posixpath.basename(p)) for r in shapes):
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
            raise BuildError("ref: %s names no reference under content/references/" % name, fix="capture the reference with /site-studio:capture, or fix its name")
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
    def markdown(self, body, source, from_out, base_dir, first_line=1):
        env = self.md_env(source, from_out, base_dir)
        text = self.expand(body, from_out, source, escape=False)
        try:
            return C.render_markdown(text, env, source, grammar=self.grammar, first_line=first_line)
        except ContentError as e:
            raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")

    def md_env(self, source, from_out, base_dir):
        """The environment a Markdown render reads images, references and plugin assets through."""
        builder = self

        class Env(object):
            def asset(self, kind):
                return builder.asset_html(from_out, kind)

            def image(self, src, alt):
                if re.match(r"^https?://", src):
                    return '<img src="%s" alt="%s" loading="lazy" decoding="async">' % (esc(src), esc(alt))
                if src.startswith("/") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", src):
                    raise ContentError("%s: image '%s' must be a relative path or an https URL"
                                       % (source, src), fix="use a relative path to a file in media/, or an https URL")
                full = posixpath.normpath(posixpath.join(base_dir, src))
                if full not in builder.media_out:
                    raise ContentError("%s: image '%s' is not a file in a media/ folder" % (source, src), fix="put the image in a media/ folder and link it by its relative path")
                return builder.img_tag(full, alt, from_out)

            def ref_card(self, name):
                try:
                    return builder.ref_card(name, from_out)
                except BuildError as e:
                    raise ContentError("%s: %s" % (source, e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        return Env()

    # ---- `{{home:<part>}}`: a hand-made home page fed by content/home.md (schema 3, design section 6.1)
    def home_split(self, out):
        """(intro Fragment, {part name: Fragment}) of content/home.md's body, its tokens expanded for the page at
        `out`. Cached per page: a part's links are relative to it."""
        cache = self._home_split
        if out not in cache:
            page = self.model.home
            text = self.expand(page.body, out, page.source, escape=False)
            try:
                cache[out] = C.parse_parts(text, page.source, page.first_line)
            except ContentError as e:
                raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None),
                                 fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        return cache[out]

    def home_part(self, part, out, source, lineno, allowed):
        """The HTML of one named part of the home page, for a `{{home:<part>}}` token in `source` (line `lineno`
        when the check knows it). Every part but `title` and `description` is rendered by the generated home's
        own code, so the fed page and the generated one print it the same way. A part the page does not hold is
        refused, naming the token's file:line and the part."""
        at = "%s:%d" % (source, lineno) if lineno else source
        if not allowed:
            raise BuildError("%s: {{home:...}} is read in site/src pages only; this is %s" % (at, source),
                             path=source, lineno=lineno,
                             fix="move the token to a page under site/src, or remove it")
        if part is None:
            raise BuildError("%s: {{home}} needs the part it names, such as {{home:intro}}" % at, path=source, lineno=lineno,
                             fix="write {{home:<part>}} with one of: %s" % ", ".join(C.PART_FIXED))
        page = self.model.home
        if self.cfg.siteKind != "portfolio" or page is None:
            raise BuildError("%s: {{home:%s}} is fed by content/home.md, and this site has none" % (at, part),
                             path=source, lineno=lineno,
                             fix="add content/home.md (a hub or custom site has none), or remove the token")
        meta = page.meta
        intro, parts = self.home_split(out)
        env = self.md_env(page.source, out, posixpath.dirname(page.source))

        def render(frag):
            try:
                return C.render_fragment(frag, env, page.source, 3)
            except ContentError as e:
                raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None),
                                 fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
        html = None
        if part in ("title", "description"):
            html = esc(meta[part]) if meta.get(part) else None
        elif part == "intro":
            html = render(intro) or None
        elif part in ("photo", "endorsement", "contact"):
            html = self.page_extras(page, out)[part] or None
        elif part == "feed":
            cards = [self.ref_card(n, out) for n in meta.get("feed", [])]
            html = ('<section class="feed"><h2>Elsewhere</h2><div class="ref-grid">%s</div></section>'
                    % "".join(cards)) if cards else None
        elif part in parts:
            html = render(parts[part]) or None
        else:
            raise BuildError("%s: {{home:%s}} names no part of %s (its parts are %s)"
                             % (at, part, page.source, ", ".join(list(C.PART_FIXED) + sorted(parts))),
                             path=source, lineno=lineno,
                             fix="write :::part %s ... ::: in %s, or use one of the parts listed" % (part, page.source))
        if html is None:
            raise BuildError("%s: {{home:%s}} is a part %s does not have, or holds nothing" % (at, part, page.source),
                             path=source, lineno=lineno,
                             fix="add what the part shows to %s (a '%s' key, the intro text, or the :::part block), "
                                 "or remove the token" % (page.source, part))
        return html

    # ---- page assembly
    def layout(self):
        raw = self.files.get("site/templates/layout.html")
        if raw is None:
            raise BuildError("site/templates/layout.html is missing (the page shell for generated pages)", fix="add site/templates/layout.html, which holds {{content}}")
        text = strip_html_comments(C.decode_text(raw, "site/templates/layout.html"))
        if "{{content}}" not in text and not re.search(r"\{\{\s*content\s*\}\}", text):
            raise BuildError("site/templates/layout.html must contain {{content}}", fix="put {{content}} in site/templates/layout.html where the page body goes")
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
        text = self.expand(layout, out_path, "site/templates/layout.html", extra=extra, featured=True)
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
        names = pf.settings["labels"]["meta"]
        cm = [("%s: %s" % (names[k], C.meta_text(piece.meta[k])) if k in names
               else C.meta_text(piece.meta[k])) for k in pf.settings["cardMeta"] if k in piece.meta]
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
                raise BuildError("%s: cover %s names no reference with a card image" % (piece.source, cv), fix="capture the reference first, or point cover at an image in media/")
            self.used_refs.add(name)
            return ref.card_path, self._card_out(ref)
        full = posixpath.normpath(posixpath.join(piece.folder, cv))
        return full, self.media_out[full]

    def cards_html(self, pieces, from_out):
        return '<ul class="cards">%s</ul>' % "".join(self.card_html(p, from_out) for p in pieces)

    # ---- the pages
    def build_portfolios(self):
        for pf in self.model.portfolios:
            self.build_portfolio(pf)
            for piece in pf.pieces:
                self.build_piece(pf, piece)

    def build_portfolio(self, pf):
        out = "%s/index.html" % pf.slug
        st = pf.settings
        if st["view"] == "page":      # schema 3: the index is the person's own site/src page, served as written
            return
        if self.single_piece(pf):     # schema 3: the nav links the piece; the index URL redirects to it (no orphan page)
            self.build_index_redirect(out, "%s/%s/index.html" % (pf.slug, pf.pieces[0].slug))
            return
        if st["groupBy"]:
            body = []
            for g in st["groups"]:
                ps = [p for p in pf.pieces if p.meta.get(st["groupBy"]) == g]
                if ps:
                    body.append('<section class="group"><h2>%s</h2>%s</section>'
                                % (esc(st["labels"]["groups"].get(g, g)), self.cards_html(ps, out)))
            cards = "".join(body)
        else:
            cards = self.cards_html(pf.pieces, out) if pf.pieces else ""
        intro = self.markdown(pf.intro, pf.page_source or "content/%s" % pf.slug, out,
                              "content/" + pf.slug, pf.intro_line) if pf.intro.strip() else ""
        desc = st["description"] or C.plain_excerpt(pf.intro, grammar=self.grammar) or \
            "%s: %s" % (self.cfg.siteTitle, st["label"])
        tagline = ('%s<p class="ss-tagline">%s</p>' % (self.asset_html(out, "css"), esc(st["tagline"]))
                   if st["tagline"] else "")
        self.emit_page(out, "portfolio", pf.page_source or "content/%s/" % pf.slug,
                       self.full_title(pf.title), pf.title, desc,
                       '<article class="portfolio"><h1>%s</h1>%s%s%s</article>'
                       % (esc(pf.title), tagline, intro, cards))

    def build_piece(self, pf, piece):
        out = "%s/%s/index.html" % (piece.portfolio, piece.slug)
        names = pf.settings["labels"]["meta"]
        meta_rows = "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(names.get(k) or k[:1].upper() + k[1:]),
                            esc(C.meta_text(piece.meta[k]))) for k in pf.settings["meta"]
                            if k in piece.meta)
        dl = '<dl class="meta">%s</dl>' % meta_rows if meta_rows else ""
        body = self.markdown(piece.body, piece.source, out, piece.folder, piece.first_line)
        desc = piece.meta.get("description") or piece.meta.get("teaser") or \
            C.plain_excerpt(piece.body, grammar=self.grammar) or "%s: %s" % (piece.title, self.cfg.siteTitle)
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
            base = posixpath.dirname(page.source)       # `content` for home.md; the page's own folder for index.md
            full = posixpath.normpath(base + "/" + meta["photo"])
            if full not in self.media_out:
                raise BuildError("%s: photo '%s' is not a file in %s/media/" % (page.source, meta["photo"], base), fix="put the photo in %s/media/ and name it as media/<file>" % base)
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
        pieces = self.selection()
        feed = []
        for name in meta.get("feed", []):
            feed.append(self.ref_card(name, out))
        extras = self.page_extras(page, out) if page else {"photo": "", "endorsement": "", "contact": ""}
        intro = self.markdown(page.body, page.source, out, posixpath.dirname(page.source),
                              page.first_line) if page else ""
        body = '<section class="intro">%s%s</section>%s' % (extras["photo"], intro, extras["endorsement"])
        if pieces:
            body += '<section class="featured"><h2>Featured</h2>%s</section>' % self.cards_html(pieces, out)
        if feed:
            body += ('<section class="feed"><h2>Elsewhere</h2><div class="ref-grid">%s</div></section>'
                     % "".join(feed))
        body += extras["contact"]
        desc = meta.get("description") or (C.plain_excerpt(page.body, grammar=self.grammar) if page else "") \
            or self.cfg.siteTitle
        image = (self.media_out.get(posixpath.normpath(posixpath.dirname(page.source) + "/" + meta["photo"]))
                 if (page and "photo" in meta) else None)
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
        intro = self.markdown(page.body, page.source, out, posixpath.dirname(page.source), page.first_line)
        desc = meta.get("description") or C.plain_excerpt(page.body, grammar=self.grammar) or \
            "About %s" % self.cfg.name
        image = (self.media_out.get(posixpath.normpath(posixpath.dirname(page.source) + "/" + meta["photo"]))
                 if "photo" in meta else None)
        self.emit_page(out, "about", page.source, self.full_title(title), title, desc,
                       '<article class="about"><h1>%s</h1>%s%s%s%s</article>'
                       % (esc(title), extras["photo"], intro, extras["endorsement"], extras["contact"]),
                       image_out=image, lastmod_src=page.source)

    def build_resume(self):
        page = self.model.resume
        out = "resume/index.html"
        title = page.meta.get("title") or "Resume"
        body = self.markdown(page.body, page.source, out, posixpath.dirname(page.source), page.first_line)
        link = ""
        if self.model.resume_pdf:
            pdf_path, pdf = self.model.resume_pdf
            pdf_out = "resume/" + posixpath.basename(pdf_path)
            self.add(pdf_out, pdf, pdf_path)
            link = '<p class="download"><a href="%s">Download as PDF</a></p>' % esc(
                rel_link(out, pdf_out))
        desc = page.meta.get("description") or "Resume of %s" % self.cfg.name
        contact = ("<h2>Contact</h2>" + self.contact_html(page.meta["contact"])) if "contact" in page.meta else ""
        self.emit_page(out, "resume", page.source, self.full_title(title), title, desc,
                       '<article class="resume"><h1>%s</h1>%s%s%s</article>' % (esc(title), link, body, contact),
                       lastmod_src=page.source)

    # ---- site/src
    def build_site_src(self):
        for path in sorted(self.files):
            if path.startswith("site/src/"):
                self.build_site_src_file(path)

    def build_site_src_file(self, path):
        rel = path[len("site/src/"):]
        raw = self.files[path]
        low = rel.lower()
        if low.endswith(HTML_EXTS):
            origin = C.decode_text(raw, path)
            text = strip_html_comments(origin)
            text = self.expand(text, nfc(rel), path, featured=True, origin=origin, home=True)
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
        for old in sorted(self.cfg.redirects):
            self.build_redirect(old)

    def build_redirect(self, old):
        targets = self.page_key_to_out()
        new = self.cfg.redirects[old]
        old_clean = old.strip("/")
        out = old_clean if old_clean.lower().endswith(HTML_EXTS) else old_clean + "/index.html"
        if nfc(out).casefold() in self.owner:
            raise BuildError("redirect '%s' would replace a real page (%s from %s)"
                             % (old, self.owner[nfc(out).casefold()][0],
                                self.owner[nfc(out).casefold()][1]), fix="remove the redirect, or rename the page it would replace")
        if re.match(r"^https?://", new):
            href, canonical = new, new
        else:
            to = targets.get(new.strip("/"))
            if to is None:
                raise BuildError("redirect '%s' points at '%s', which is not a built page" % (old, new), fix="point the redirect at a page that is built, or build that page")
            href, canonical = rel_link(out, to), self.abs_url(to)
        self.emit_redirect(out, href, canonical, "site.json redirects")

    def build_index_redirect(self, out, to):
        """A portfolio index served as a redirect page to its one piece (`menuLinks: "single-piece"`)."""
        self.emit_redirect(out, rel_link(out, to), self.abs_url(to), "content/ (menuLinks: single-piece)")

    def emit_redirect(self, out, href, canonical, source):
        text = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<title>Redirecting</title>\n<meta name="robots" content="noindex">\n'
                '<link rel="canonical" href="%s">\n<meta http-equiv="refresh" content="0; url=%s">\n'
                '</head>\n<body>\n<p>This page has moved: <a href="%s">continue</a>.</p>\n'
                '</body>\n</html>\n' % (esc(canonical), esc(href), esc(href)))
        self.pages[nfc(out)] = {"kind": "redirect", "source": source,
                                "lastmod_src": None, "sitemap": False}
        self.add(out, text.encode("utf-8"), source)

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
                raise BuildError("%s would be written with a carriage return" % rel, fix="save the file with LF line endings")
        with open(full, "wb") as fh:
            fh.write(data)
        os.chmod(full, 0o644)


def _check_out_dir(out_dir):
    if os.path.exists(out_dir) and (not os.path.isdir(out_dir) or os.listdir(out_dir)):
        raise BuildError("%s already exists and is not empty; build into a new or empty folder"
                         % out_dir, fix="build into a new or empty folder, or delete the old output")


def _digest_tree(out_dir, site_kind="portfolio"):
    """The digest of design 3.5: SHA-256 of `<NFC path> NUL <hex sha256 of content> LF` per
    regular file, in the order of the UTF-8 bytes of the NFC path, then `siteKind NUL <kind> LF`
    when the kind is not `portfolio` (see the module docstring). Private: only `publish_build`
    calls it."""
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
    if site_kind != "portfolio":
        h.update(b"siteKind\0" + site_kind.encode("ascii") + b"\n")
    return h.hexdigest()


def digest_output_tree(path, site_kind="portfolio"):
    """The design 3.5 digest of an arbitrary DIRECTORY of output files (dev #835, finding F1).

    A public wrapper over the private `_digest_tree`, same formula, so `deploy.py` can digest the
    PUBLIC clone's tree (publish step 2.5 and 5.5) without a second implementation that could
    drift. It does NOT build anything and is not reachable from `preview_build`, whose result
    still has no digest attribute. The caller owns what the directory holds.

    `site_kind` is the kind of the site the directory was built from (`PublishResult.site_kind`). A
    `hub` or `custom` site's digest carries one final kind line (module docstring), and a public
    clone's tree holds no `site.json`, so the CALLER must say the kind or the two digests differ."""
    if not os.path.isdir(path):
        raise BuildError("%s is not a folder" % path, fix="pass a folder that holds the built output")
    return _digest_tree(path, site_kind)


def _load_model(files, cfg, drafts, check_resume_pdf):
    """The content model for a site. A `portfolio` loads `content/`; a `hub` or `custom` builds
    nothing from it, so it gets an empty model after every refusal of design section 4.1 is
    checked: portfolio-only keys, portfolio content, and a missing `site/src/index.html`."""
    layout = [p.message for p in C.layout_problems(files, cfg.siteKind, cfg)]
    if cfg.siteKind == "portfolio":
        if layout:
            raise ContentError("; ".join(layout), fix="fix each problem listed, then build again")
        return C.load_content(files, cfg, drafts=drafts, check_resume_pdf=check_resume_pdf)
    problems = siteconfig.kind_conflicts(cfg) + layout
    if "site/src/index.html" not in files:
        problems.append("a %s site's home page is site/src/index.html, and it is missing" % cfg.siteKind)
    if problems:
        raise ContentError("; ".join(problems), fix="fix each problem listed, then build again")
    return C.Content()


ACCEPT_YEAR = 2000          # a placeholder: `accept` writes and publishes nothing, and `{{year}}` is its only reader
ACCEPT_PREVIEW_URL = "https://example.invalid"      # stands in for a missing previewUrl, once it is reported


def _problem_from(e, default_path=None):
    """One `siteconfig.Problem` for a `BuildError` or `ContentError`: its message, its `path`/`lineno`/`fix`
    when it carries them, else the file named at the head of the message (`path:12: ...`), else the
    unit being built. Never mechanical: only the person can fix a refusal the build raises."""
    msg = str(e)
    path = getattr(e, "path", None)
    lineno = getattr(e, "lineno", None)
    if path is None:
        m = re.match(r"^([^\s:][^\s]*?)(?::(\d+))?: ", msg)
        if m and ("/" in m.group(1) or "." in m.group(1)):
            path = m.group(1)
            if lineno is None and m.group(2):
                lineno = int(m.group(2))
    fix = getattr(e, "fix", None) or "fix the problem named here, then run the check again"
    return siteconfig.make_problem(msg, path or default_path, "refused by the build", "accepted by the build",
                                   fix, False, lineno)


def _not_checked(stage_name, e, default_path=None):
    """A refusal that is not a refusal: an exception the build did not mean to raise. It is loud, never a
    traceback and never a quiet pass (CLAUDE.md: a missing thing reads as an empty thing)."""
    return siteconfig.make_problem("NOT CHECKED: %s raised %s: %s" % (stage_name, type(e).__name__, e),
                                   default_path, "an exception the build did not mean to raise",
                                   "a refusal with a fix", "report this to site-studio, with the file named "
                                   "here", False)


def _cr_problems(out):
    probs = []
    for rel in sorted(out, key=lambda p: p.encode("utf-8")):
        if (rel.lower().endswith(C.TEXT_EXTS) or rel in ("CNAME", "robots.txt")
                or rel.lower().endswith(HTML_EXTS)) and b"\r" in out[rel]:
            probs.append(siteconfig.make_problem("%s would be written with a carriage return" % rel, rel,
                                                 "a carriage return", "LF line endings",
                                                 "save the file with LF line endings"))
    return probs


def _meta_key_problems(model, cfg):
    """Schema 3 only (design-site-fidelity section 6.2): a `meta` or `cardMeta` list that names a key the build
    already reads or shows (`siteconfig.BUILTIN_PIECE_KEYS`) is refused, because the build shows it already and
    a second copy would print it twice. Below schema 3 such a list builds exactly as 0.2.0 built it, so this is
    never asked of a schema-1 or schema-2 reading. The Problem names the file the list is in: the portfolio's
    page.md when that page sets the list, else site.json (`work`'s base)."""
    out = []
    for pf in model.portfolios:
        for part in ("meta", "cardMeta"):
            for key in pf.settings[part]:
                if key not in siteconfig.BUILTIN_PIECE_KEYS:
                    continue
                path = pf.page_source if (pf.page_source and part in pf.page_keys) else "site/site.json"
                out.append(siteconfig.make_problem(
                    "%s: '%s' lists the built-in key '%s', which the build shows already" % (path, part, key),
                    path, "'%s' in %s" % (key, part), "no built-in key in %s" % part,
                    "remove '%s' from %s; the build shows it already" % (key, part)))
    return out


def warning_line(w):
    """One warning as the build prints it: where (with the line when known), what is not published, the fix."""
    at = "%s:%d: " % (w.path, w.lineno) if (w.lineno and w.path) else ""
    msg = w.message
    if at and msg.startswith(w.path + ": "):
        msg = msg[len(w.path) + 2:]
    return "%s%s -- fix: %s" % (at, msg, w.fix)


def _refusal(problems):
    """One `BuildError` that carries every problem; its message is the join of theirs (exactly the one
    problem's message when there is one)."""
    first = problems[0]
    return BuildError("; ".join(p.message for p in problems), path=first.path, lineno=first.lineno,
                      fix=first.fix, problems=problems)


def _accept(files, drafts, year, lastmod, grammar=None):
    """The one acceptance function behind `accept`, `publish_build` and `preview_build` (design-site-
    fidelity section 4.1): five stages, each collecting what it refuses, over {repo path: bytes}.
    Nothing is written, no git call is made. `year` and `lastmod` are what a real build prints; `accept`
    passes placeholders."""
    problems, notes, warnings = [], [], []
    seen = set()

    def add(p):
        key = (p.path, p.message)
        if key not in seen:
            seen.add(key)
            problems.append(p)

    def stage(label, default_path, fn, *args):
        """Run `fn`; every refusal becomes a Problem and the stage carries on. Returns (ok, value)."""
        try:
            return True, fn(*args)
        except SiteConfigError as e:
            for p in e.problems:
                add(p)
        except (BuildError, ContentError) as e:
            add(_problem_from(e, default_path))
        except Exception as e:      # noqa: BLE001 -- NOT CHECKED, never a traceback
            add(_not_checked(label, e, default_path))
        return False, None

    def finish(cfg=None, model=None, out=None, pages=None):
        ordered = sorted(problems, key=lambda p: (p.path or "", p.lineno or 0, p.message))
        return Acceptance(ordered, notes, cfg, model, out if out is not None else {}, pages or {}, warnings)

    raw = files.get("site/site.json")
    if raw is None:
        add(siteconfig.make_problem("site/site.json is not in the build input", "site/site.json", "missing",
                                    "a site.json", "commit site/site.json, or run /site-studio:setup in "
                                    "the dev repo"))
        return finish()

    def config():
        data = siteconfig.decode(C.decode_text(raw, "site/site.json"))
        probs = siteconfig.problems(data)
        if probs:
            raise SiteConfigError.of(probs)
        return siteconfig.parse_data(data)
    ok, cfg = stage("siteconfig.problems", "site/site.json", config)               # stage 1
    if not ok:
        return finish()
    ok, _ = stage("check_tree_schema", "site/site.json", siteconfig.check_tree_schema, cfg, files)   # stage 2
    if not ok:
        return finish(cfg)
    ok, layout = stage("content.layout_problems", "content/", C.layout_problems, files, cfg.siteKind, cfg)
    for p in layout or ():                                                          # stage 3
        add(p)
    model = None
    if cfg.siteKind == "portfolio":
        errors = []
        ok, model = stage("content.load_content", "content/", C.load_content, files, cfg, drafts,
                          not drafts, errors)                                       # stage 4
        for e in errors:
            if isinstance(e, SiteConfigError):
                for p in e.problems:
                    add(p)
            else:
                add(_problem_from(e, "content/"))
    else:
        for text in siteconfig.kind_conflicts(cfg):
            add(siteconfig.make_problem(text, "site/site.json", "a portfolio-only key", "none, on a %s site"
                                        % cfg.siteKind, "remove the key, or set siteKind to portfolio"))
        if "site/src/index.html" not in files:
            add(siteconfig.make_problem("a %s site's home page is site/src/index.html, and it is missing"
                                        % cfg.siteKind, "site/src/index.html", "missing", "a home page",
                                        "add site/src/index.html"))
        model = C.Content()
    if model is None:
        return finish(cfg)
    if cfg.siteKind == "portfolio":      # never a refusal and never a change to the output (the owner invariant)
        _ok, found = stage("content.stray_warnings", "content/", C.stray_warnings, files, model, cfg)
        warnings.extend(found or ())
    if cfg.siteKind == "portfolio" and (cfg.schema if grammar is None else grammar) >= 3:
        for p in _meta_key_problems(model, cfg):         # the schema-3 reading only: 0.2.0 trees build as they did
            add(p)
    site_url = cfg.site_url()
    if site_url is None:
        if not drafts:
            add(siteconfig.make_problem(
                "site.json has no 'previewUrl' (and no cutover): share tags and the sitemap need an "
                "absolute address", "site/site.json", "no previewUrl", "an https previewUrl",
                "set previewUrl in site/site.json to your site's https address"))
        site_url = PREVIEW_SITE_URL if drafts else ACCEPT_PREVIEW_URL
    b = _Builder(None, files, cfg, model, site_url, year, None, drafts, grammar)
    if b.grammar < 3:       # a reading schema 3 would change is a NOTE here, never a refusal (section 3.2)
        for r in siteconfig.schema_3_reasons(cfg, files, C.interpretation_reasons(files), kinds=("I",)):
            notes.append("%s %s, which schema 3 would read differently; it is published as it is today (run "
                         "`build.py raise-schema` to see what would change)"
                         % ("%s:%d:" % (r.where, r.lineno) if r.lineno else r.where, r.what))
    ok, _ = stage("_Builder.preregister", "site/", b.preregister)                  # stage 5
    if not ok:
        return finish(cfg, model)
    for path in sorted(files):
        if path.startswith("site/src/"):
            stage("_Builder.build_site_src", path, b.build_site_src_file, path)
    if cfg.siteKind == "portfolio":
        for pf in model.portfolios:
            stage("_Builder.build_portfolio", pf.page_source or "content/%s/" % pf.slug, b.build_portfolio, pf)
            for piece in pf.pieces:
                stage("_Builder.build_piece", piece.source, b.build_piece, pf, piece)
        if model.about is not None:
            stage("_Builder.build_about", model.about.source, b.build_about)
        if model.resume is not None:
            stage("_Builder.build_resume", model.resume.source, b.build_resume)
        if "site/src/index.html" not in files:      # a hand-made home is the home page (H1, section 4.3)
            stage("_Builder.build_home", "content/home.md", b.build_home)
    stage("_Builder.build_plugin_assets", "templates/output/", b.build_plugin_assets)
    stage("_Builder.build_media", "content/", b.build_media)
    for old in sorted(cfg.redirects):
        stage("_Builder.build_redirect", "site/site.json", b.build_redirect, old)
    stage("_Builder.build_sitemap", "sitemap.xml", b.build_sitemap, lastmod)
    for p in _cr_problems(b.out):
        add(p)
    notes.extend(b.notes)
    return finish(cfg, model, b.out, b.pages)


def accept(files, drafts=False):
    """Run the publish build's own acceptance over an in-memory tree and say everything it refuses
    (design-site-fidelity section 4.1). `files` is {repo path: bytes} for `site/` and `content/`; nothing
    is written, no git call is made, no date is computed. Returns an `Acceptance`: `.problems` empty means
    the build would accept the tree. `adopt check`, `inventory`, `apply --dry-run` and parity read this, so
    adopt can never say "can be converted" about a tree the build refuses."""
    return _accept(files, drafts, ACCEPT_YEAR, lambda _src: None)


def _run(repo, out_dir, drafts):
    repo = os.path.abspath(repo)
    out_dir = os.path.abspath(out_dir)
    _check_out_dir(out_dir)
    if drafts:
        files = _disk_files(repo)
    else:
        if _is_shallow(repo):
            raise BuildError("this clone is shallow, so build dates cannot be trusted; run "
                             "`git fetch --unshallow` and build again",
                             fix="run `git fetch --unshallow` and build again")
        files = _commit_files(repo)
    epoch = _last_commit_epoch(repo, ["site", "content"])
    if epoch is None:
        year = time.gmtime().tm_year if drafts else ACCEPT_YEAR    # drafts: a repo with nothing committed yet
    else:
        year = time.gmtime(epoch).tm_year

    def lastmod(src):
        if drafts:
            return None
        e = _last_commit_epoch(repo, [src])
        return _utc_date(e) if e is not None else None

    acc = _accept(files, drafts, year, lastmod)
    if acc.problems:
        raise _refusal(acc.problems)
    if epoch is None and not drafts:
        raise BuildError("no commit touches site/ or content/, so there is nothing to build",
                         fix="commit your site/ and content/ files, then build again")
    os.makedirs(out_dir, exist_ok=True)
    _write_outputs(out_dir, acc.output)
    files_out = sorted(acc.output, key=lambda p: p.encode("utf-8"))
    pages = sorted((p, acc.pages[p]["kind"]) for p in acc.pages)
    return (out_dir, files_out, pages, acc.cfg.site_url() or PREVIEW_SITE_URL, acc.notes, acc.cfg.siteKind,
            acc.warnings)


def publish_build(repo, out_dir):
    """The one digested build: committed tree at HEAD, no drafts. Returns a PublishResult."""
    out_dir, files, pages, site_url, notes, site_kind, warnings = _run(repo, out_dir, drafts=False)
    return PublishResult(out_dir, files, pages, site_url, False, notes, _digest_tree(out_dir, site_kind),
                         site_kind, warnings)


def preview_build(repo, out_dir):
    """A drafts-included build of the working tree. Returns a BuildResult with NO digest."""
    out_dir, files, pages, site_url, notes, _kind, warnings = _run(repo, out_dir, drafts=True)
    return BuildResult(out_dir, files, pages, site_url, True, notes, warnings)


# ---------------------------------------------------------------- the raise to schema 3 (design section 3.4)

class RaiseReport(object):
    """What `raise_report` found. `differences` is [(output path, source, detail)]: every output file whose
    bytes differ between the old reading and schema 3's (`source` is the page's source file, when it has one).
    `problems` is what schema 3 refuses that the old reading accepted (never confirmable). `base_problems` is
    what the site refuses TODAY, before any raise. `site_json` is the text a raise would write."""

    def __init__(self, differences, problems, base_problems, site_json):
        self.differences = differences
        self.problems = problems
        self.base_problems = base_problems
        self.site_json = site_json


def _first_difference(a, b):
    la = a.decode("utf-8", "replace").split("\n")
    lb = b.decode("utf-8", "replace").split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "(end)"
        y = lb[i] if i < len(lb) else "(end)"
        if x != y:
            return "line %d: %r -> %r" % (i + 1, x[:70], y[:70])
    return "binary content differs"


def raise_report(files, to=3, edited=None):
    """The raise to schema `to`, as a report (design-site-fidelity section 3.4): the site is built twice in
    memory with `accept`, both times with `site.json` declaring schema `to` (so a key 0.2.0 refused is
    admitted), once with the CURRENT grammar and recognitions and once with schema `to`'s. `edited` is the
    tree the second build reads when `--keep-text` has escaped some lines; the first build always reads
    `files`. Writes nothing."""
    raw = files.get("site/site.json")
    if raw is None:
        return RaiseReport([], [], [siteconfig.make_problem("site/site.json is not in the build input",
                                                            "site/site.json")], None)
    cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
    cur = cfg.schema

    def raised(tree):
        tree = dict(tree)
        interps = C.interpretation_reasons(tree)
        text = siteconfig.canonical_text(cfg, tree, interps, at_least=to)
        tree["site/site.json"] = text.encode("utf-8")
        return tree, text
    old_tree, _t = raised(files)
    new_tree, site_json = raised(edited if edited is not None else files)
    a = _accept(old_tree, False, ACCEPT_YEAR, lambda _s: None, grammar=cur)
    b = _accept(new_tree, False, ACCEPT_YEAR, lambda _s: None, grammar=to)
    seen = set((p.path, p.message) for p in a.problems)
    problems = [p for p in b.problems if (p.path, p.message) not in seen]
    diffs = []
    for path in sorted(set(a.output) | set(b.output)):
        x, y = a.output.get(path), b.output.get(path)
        if x != y:
            info = b.pages.get(path) or a.pages.get(path) or {}
            diffs.append((path, info.get("source"),
                          "only after the raise" if x is None else "gone after the raise" if y is None
                          else _first_difference(x, y)))
    return RaiseReport(diffs, problems, list(a.problems), site_json)


def _keep_text(files, specs):
    """The tree with a `\\` put at the start of each PATH:LINE the person wants kept as text. Raises
    BuildError naming a line that is not one schema 3 reads differently."""
    out = dict(files)
    reasons = set((p, n) for p, n, _form in C.interpretation_reasons(files))
    for spec in specs:
        path, _, n = spec.rpartition(":")
        if not n.isdigit() or path not in files:
            raise BuildError("--keep-text %s: write it as PATH:LINE, naming a file under content/" % spec,
                             fix="use --keep-text content/<folder>/index.md:<line number>")
        if (path, int(n)) not in reasons:
            raise BuildError("%s is not a line schema 3 reads differently, so there is nothing to keep as text"
                             % spec, fix="run raise-schema without --keep-text to see the lines it lists")
        lines = C.decode_text(out[path], path).split("\n")
        lines[int(n) - 1] = "\\" + lines[int(n) - 1]
        out[path] = "\n".join(lines).encode("utf-8")
    return out


def raise_schema_main(argv):
    """`build.py raise-schema --repo DIR [--keep-text PATH:LINE ...] [--confirm]`: move a site to schema 3.
    Lists every output difference first and refuses until each is confirmed or kept as text; a problem
    schema 3 raises is never confirmable. Reads and writes the working tree; the person commits."""
    ap = argparse.ArgumentParser(prog="build.py raise-schema", allow_abbrev=False)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--keep-text", action="append", default=[], metavar="PATH:LINE")
    ap.add_argument("--confirm", action="store_true", help="accept the listed differences and write schema 3")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        files = _disk_files(repo)
        raw = files.get("site/site.json")
        if raw is None:
            raise BuildError("site/site.json is not in the working tree", fix="run this inside the dev repo")
        cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
        if cfg.schema >= 3:
            print("site.json is already schema %d; nothing to raise" % cfg.schema)
            return 0
        edited = _keep_text(files, args.keep_text) if args.keep_text else None
        rep = raise_report(files, 3, edited)
    except (BuildError, SiteConfigError, ContentError) as e:
        print("raise-schema refused: %s" % e)
        return 1
    if rep.base_problems:
        print("raise-schema refused: this site does not build today, so there is nothing to compare. "
              "Fix these first:")
        for p in rep.base_problems:
            print("  - %s" % p.line())
        return 1
    for p in rep.problems:
        print("you decide: %s" % p.line())
    for path, source, detail in rep.differences:
        print("would change: %s%s (%s)" % (path, " from %s" % source if source else "", detail))
    kept = [s for s in args.keep_text if any(src and s.rpartition(":")[0] == src for _p, src, _d in rep.differences)]
    if kept:
        print("raise-schema refused: %s is still read differently at schema 3, so keeping it as text did not "
              "keep the page as it is" % ", ".join(kept))
        return 1
    if rep.problems:
        print("raise-schema refused: %d problem(s) schema 3 raises; none can be confirmed, each needs its own "
              "fix first" % len(rep.problems))
        return 1
    if rep.differences and not args.confirm:
        print("raise-schema refused: %d page(s) would change. Keep a line as text with --keep-text PATH:LINE, "
              "or accept every change listed with --confirm" % len(rep.differences))
        return 1
    tree = edited if edited is not None else files
    for path in sorted(args.keep_text and set(s.rpartition(":")[0] for s in args.keep_text) or ()):
        with open(os.path.join(repo, *path.split("/")), "wb") as fh:
            fh.write(tree[path])
    with open(os.path.join(repo, "site", "site.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rep.site_json)
    print("raised to schema 3: %s" % ("no page changes" if not rep.differences else
                                      "%d page change(s) confirmed" % len(rep.differences)))
    return 0


# ---------------------------------------------------------------- inventory

def inventory(repo):
    """`--list`: what the working tree holds, drafts included."""
    repo = os.path.abspath(repo)
    files = _disk_files(repo)
    raw = files.get("site/site.json")
    if raw is None:
        raise BuildError("site/site.json is not in the working tree", fix="add site/site.json, or run /site-studio:setup in the dev repo")
    try:
        cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
        siteconfig.check_tree_schema(cfg, files)
        model = _load_model(files, cfg, True, False)
    except (siteconfig.SiteConfigError, ContentError) as e:
        raise BuildError(str(e), path=getattr(e, "path", None), lineno=getattr(e, "lineno", None), fix=getattr(e, "fix", None) or "fix the problem named above, then try again")
    inv = {"portfolios": [], "references": sorted(model.references),
           "pages": [n for n, p in (("home", model.home), ("about", model.about),
                                    ("resume", model.resume)) if p is not None]}
    if cfg.siteKind != "portfolio":
        inv["siteKind"] = cfg.siteKind
    for pf in model.portfolios:
        inv["portfolios"].append({
            "slug": pf.slug, "label": pf.settings["label"],
            "pieces": [{"slug": p.slug, "title": p.title, "draft": p.draft, "date": p.date,
                        "group": p.meta.get(pf.settings["groupBy"]) if pf.settings["groupBy"] else None}
                       for p in pf.pieces]})
    return inv


def format_inventory(inv):
    lines = []
    if inv.get("siteKind"):
        lines.append("site kind: %s (every page is site/src as written; nothing is generated)"
                     % inv["siteKind"])
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
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "raise-schema":
        return raise_schema_main(argv[1:])
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
        for w in res.warnings:      # printed on every build, at every schema; the output is the same without them
            print("warning: " + warning_line(w))
        if args.digest:
            print("digest: %s" % res.digest)
        return 0
    except BuildError as e:
        print("build refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
