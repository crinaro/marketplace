"""running: the acceptance run and the two builds made from it: `accept` (nothing written), `publish_build` and
`preview_build`. One `_accept` path under all three, so what `accept` reports is what a build would refuse."""

import content as C
from contentmodel import frontmatter, grammar as grammar_mod, layout as layout_mod, models, strays
import os
import time
from building.acceptance import (
    _cr_problems,
    _meta_key_problems,
    _not_checked,
    _problem_from,
    _refusal,
    trigger_slot_findings,
)
from building.constants import ACCEPT_PREVIEW_URL, PREVIEW_SITE_URL, ACCEPT_YEAR
from building.digest import _check_out_dir, _write_outputs, _digest_tree
from building.gitfiles import _commit_files, _disk_files, _is_shallow, _last_commit_epoch, _utc_date
from building.lookneeds import look_needs
from building.outcomes import Acceptance, BuildError, PublishResult, BuildResult
from configschema import diagnostics, model as model_mod, treeschema
from configschema.diagnostics import SiteConfigError
from contentmodel.errors import ContentError
from building.builder import _Builder


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
        add(diagnostics.make_problem("site/site.json is not in the build input", "site/site.json", "missing",
                                    "a site.json", "commit site/site.json, or run /site-studio:setup in "
                                    "the dev repo"))
        return finish()

    def config():
        data = model_mod.decode(frontmatter.decode_text(raw, "site/site.json"))
        probs = model_mod.problems(data)
        if probs:
            raise SiteConfigError.of(probs)
        return model_mod.parse_data(data)
    ok, cfg = stage("siteconfig.problems", "site/site.json", config)               # stage 1
    if not ok:
        return finish()
    ok, _ = stage("check_tree_schema", "site/site.json",                                         # stage 2
                  lambda: treeschema.check_tree_schema(cfg, files, look_needs(files)))
    if not ok:
        return finish(cfg)
    ok, layout = stage("content.layout_problems", "content/", layout_mod.layout_problems, files, cfg.siteKind, cfg)
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
        for text in treeschema.kind_conflicts(cfg):
            add(diagnostics.make_problem(text, "site/site.json", "a portfolio-only key", "none, on a %s site"
                                        % cfg.siteKind, "remove the key, or set siteKind to portfolio"))
        if "site/src/index.html" not in files:
            add(diagnostics.make_problem("a %s site's home page is site/src/index.html, and it is missing"
                                        % cfg.siteKind, "site/src/index.html", "missing", "a home page",
                                        "add site/src/index.html"))
        model = models.Content()
    if model is None:
        return finish(cfg)
    if cfg.siteKind == "portfolio":      # never a refusal and never a change to the output (the owner invariant)
        _ok, found = stage("content.stray_warnings", "content/", strays.stray_warnings, files, model, cfg)
        warnings.extend(found or ())
    if cfg.siteKind == "portfolio" and (cfg.schema if grammar is None else grammar) >= 3:
        for p in _meta_key_problems(model, cfg):         # the schema-3 reading only: 0.2.0 trees build as they did
            add(p)
    site_url = cfg.site_url()
    if site_url is None:
        if not drafts:
            add(diagnostics.make_problem(
                "site.json has no 'previewUrl' (and no cutover): share tags and the sitemap need an "
                "absolute address", "site/site.json", "no previewUrl", "an https previewUrl",
                "set previewUrl in site/site.json to your site's https address"))
        site_url = PREVIEW_SITE_URL if drafts else ACCEPT_PREVIEW_URL
    b = _Builder(None, files, cfg, model, site_url, year, None, drafts, grammar)
    if b.grammar < 3:       # a reading schema 3 would change is a NOTE here, never a refusal (section 3.2)
        for r in treeschema.schema_3_reasons(cfg, files, grammar_mod.interpretation_reasons(files), kinds=("I",)):
            notes.append("%s %s, which schema 3 would read differently; it is published as it is today (run "
                         "`build.py raise-schema` to see what would change)"
                         % ("%s:%d:" % (r.where, r.lineno) if r.lineno else r.where, r.what))
    ok, _ = stage("_Builder.load_look", cfg.look or "site/site.json", b.load_look)  # the look the site names
    if not ok:
        return finish(cfg, model)
    ok, found = stage("trigger_slot_findings", cfg.look or "site/site.json",     # a trigger with nowhere to print
                      trigger_slot_findings, model, cfg, files, b.look, b.grammar)
    if ok:
        for p in found[0]:
            add(p)
        notes.extend(found[1])
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
