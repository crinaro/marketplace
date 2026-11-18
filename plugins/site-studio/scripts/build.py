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
    to the 0.1.0 digest and the upgrade voids no recorded review (tests/test_building_identity.PortfolioUnchanged).

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
import looks  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402
from content import ContentError, esc  # noqa: E402
from looks import LookError  # noqa: E402
from siteconfig import SiteConfigError  # noqa: E402

# The capability modules live in the `building` package (segmentation standard, docs/design-component-segmentation.md):
# this file keeps the entry point, the acceptance run and the class that combines the builder's parts, and
# re-exports every name its importers read, by explicit named import (never a star). Importers are repointed
# in a later step; until then `import build; build.X` keeps working.
from building.constants import (
    PLUGIN_ASSETS, JUNK_NAMES, HTML_EXTS, IMAGE_EXTS, SIZES_ATTR, PREVIEW_SITE_URL,
    DEFAULT_ASSET_NOTE, ACCEPT_YEAR, ACCEPT_PREVIEW_URL)
from building.outcomes import BuildError, Acceptance, BuildResult, PublishResult
from building.gitfiles import (
    _git, _is_shallow, _decode_path, _is_junk, _commit_files, _disk_files, _last_commit_epoch,
    _utc_date)
from building.imagesize import _SOF, image_size
from building.tokens import (
    _HTML_COMMENT, _CSS_COMMENT, _STYLE_BLOCK, _TOKEN, TOKEN_RE, TOKEN_SCOPES, TOKEN_SINCE,
    SIZE_COPY_SHAPES, token_known, _SECTION, strip_html_comments, strip_css_comments, nfc,
    _page_dir, _line_of, rel_link, _meta_title, _meta_description)
from building.digest import _write_outputs, _check_out_dir, _digest_tree, digest_output_tree
from building.acceptance import (
    _load_model, _problem_from, _not_checked, _cr_problems, _meta_key_problems, warning_line,
    _refusal)
from building.raising import RaiseReport, _first_difference, _keep_text
from building.pagebase import _PageBase
from building.markdownenv import _MarkdownEnv
from building.homepage import _HomePage
from building.portfolios import _Portfolios
from building.siteparts import _SiteParts


# The plugin's own output files (site-fidelity section 7.7): the block stylesheet and the facade script live in
# the PLUGIN at templates/output/, are copied into a site's output only when a page uses a block, and never
# touch the person's source. Each is `{kind: (path under templates/output/ and in the output)}`.
OUTPUT_TEMPLATES = os.path.normpath(os.path.join(HERE, "..", "templates", "output"))

# The content model that SHIPS (dev #876): `reference/content-model.md`, generated from the code's own tables by
# tests/gen_content_model.py and checked against them by tests/test_content_model_generated.py. It is found from this
# file's own location, never from ${CLAUDE_PLUGIN_ROOT}, which Claude Code does not set in the environment of a
# command run through the Bash tool. A message that points a person at it names this absolute, installed path.
CONTENT_MODEL = os.path.normpath(os.path.join(HERE, "..", "reference", "content-model.md"))


# ---------------------------------------------------------------- the builder

class _Builder(_PageBase, _MarkdownEnv, _HomePage, _Portfolios, _SiteParts):
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
        if kind in ("css", "schema-4"):
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
            if kind in ("css", "schema-4"):      # the build publishes no CSS comment (check_site's `comments` family proves it)
                data = strip_css_comments(C.decode_text(data, rel)).lstrip("\n").encode("utf-8")
            self.add(rel, data, "templates/output/" + rel)

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
            if (scope is None or TOKEN_SINCE.get(name, 0) > self.cfg.schema
                    or (scope == "layout" and not (extra and name in extra))):
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
            if name == "navLinks":
                return self.nav_links_html(current_out)
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

    def look_sheets(self, html_text, out_path):
        """The look's stylesheets (`stylesheets` in the look file, paths under site/src/), each linked once before
        </head> on a generated page, except where the layout already links that address. The files are the
        person's own site/src files, which the build publishes as it publishes any of them."""
        if self.look is None or not self.look.stylesheets or "</head>" not in html_text:
            return html_text
        tags = []
        for rel in self.look.stylesheets:
            href = rel_link(out_path, rel[len("site/src/"):])
            if re.search(r"href=[\"']%s[\"']" % re.escape(esc(href)), html_text) or \
                    re.search(r"href=[\"']%s[\"']" % re.escape(href), html_text):
                continue
            tags.append('<link rel="stylesheet" href="%s">' % esc(href))
        if not tags:
            return html_text
        return html_text.replace("</head>", "".join("  %s\n" % t for t in tags) + "</head>", 1)

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
    ok, _ = stage("_Builder.load_look", cfg.look or "site/site.json", b.load_look)  # the look the site names
    if not ok:
        return finish(cfg, model)
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


def raise_report(files, to=3, edited=None):
    """The raise to schema `to`, as a report (design-site-fidelity section 3.4): the site is built twice in
    memory with `accept`, both times with `site.json` declaring schema `to` (so a key 0.2.0 refused is
    admitted), once with the CURRENT grammar and recognitions and once with schema `to`'s. `edited` is the
    tree the second build reads when `--keep-text` has escaped some lines; the first build always reads
    `files`. Writes nothing."""
    raw = files.get("site/site.json")
    if raw is None:
        return RaiseReport([], [], [siteconfig.make_problem("site/site.json is not in the build input",
                                                            "site/site.json", "missing", "a site.json",
                                                            "commit site/site.json, or run /site-studio:setup in "
                                                            "the dev repo")], None)
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


def raise_schema_main(argv):
    """`build.py raise-schema --repo DIR [--to 3|4] [--keep-text PATH:LINE ...] [--confirm]`: move a site to schema 3
    (the default) or 4. Lists every output difference first and refuses until each is confirmed or kept as text; a
    problem the new schema raises is never confirmable (at 4 that includes a custom `:::part` whose name the schema
    now fixes: the refusal names both, and nothing is written). Reads and writes the working tree; the person commits.
    A raise to 4 changes no page when the tree holds no schema-3 reading (design 3.1 rule 2: every schema-4 name is
    a key or token 0.3.x refused), and says "no page changes"."""
    ap = argparse.ArgumentParser(prog="build.py raise-schema", allow_abbrev=False)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--keep-text", action="append", default=[], metavar="PATH:LINE")
    ap.add_argument("--to", type=int, choices=(3, 4), default=3, help="the schema to raise to (default 3)")
    ap.add_argument("--confirm", action="store_true", help="accept the listed differences and write the new schema")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        files = _disk_files(repo)
        raw = files.get("site/site.json")
        if raw is None:
            raise BuildError("site/site.json is not in the working tree", fix="run this inside the dev repo")
        cfg = siteconfig.parse_text(C.decode_text(raw, "site/site.json"))
        if cfg.schema >= args.to:
            print("site.json is already schema %d; nothing to raise" % cfg.schema)
            return 0
        edited = _keep_text(files, args.keep_text) if args.keep_text else None
        clash = siteconfig.part_collision_problems(files) if args.to >= 4 else []
        if clash:          # design 3.1 rule 7: a custom part with a name schema 4 fixes is named, both names, before anything is written
            print("raise-schema refused: schema 4 fixes the home part names %s, and this site has %d custom part(s) "
                  "that use one. Rename each, then raise again:" % (", ".join(siteconfig.V4_PART_FIXED), len(clash)))
            for p in clash:
                print("  - %s" % p.line())
            return 1
        rep = raise_report(files, args.to, edited)
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
        print("raise-schema refused: %s is still read differently at schema %d, so keeping it as text did not "
              "keep the page as it is" % (", ".join(kept), args.to))
        return 1
    if rep.problems:
        print("raise-schema refused: %d problem(s) schema %d raises; none can be confirmed, each needs its own "
              "fix first" % (len(rep.problems), args.to))
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
    print("raised to schema %d: %s" % (args.to, "no page changes" if not rep.differences else
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
                                 description="Build the site from the dev repo.")
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
