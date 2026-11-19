"""The four commands of look.py (`list`, `use`, `check`, `derive`) and the seams a test replaces (`Env`). Every command returns the exit code."""

import addresses
import looks
import os
from pagesaudit import ghget
import posixpath
import sys
import urllib.parse
from building import gitfiles, outcomes, running
from configschema import diagnostics, model, canonical, partblocks
from contentmodel import grammar
from lookgrammar.stylesheets import check_stylesheet_file, scan_stylesheet
from lookfiles.derive import derive_look
from lookfiles.lookfile import (
    LOOKS_REL,
    SHIPPED_DIR,
    _SLUG,
    _find_source,
    _read_look,
    _repo_root_of,
    literals,
    shipped_ids,
)
from lookfiles.ownership import pages_host_set, settle_ownership
from lookfiles.pagefetch import FETCH_PAGES, fetch_pages, read_build_dir  # fetch_pages: read by name in Env (globals())
from lookfiles.refusals import LookCommandError
from lookfiles.renderlog import record
import subprocess


EXIT_OK, EXIT_REFUSED = 0, 1


DEFAULT_NAME = "derived"


NOT_VERIFIED = "ownership not verified: this host is accepted on your word, and site-studio cannot check it"


# =================================================================================================== ownership
class Env(object):
    """The seams a test replaces; main() builds the real one."""

    def __init__(self, out=None, get=None, isatty=None, ask=None, fetch_pages=None):
        self.out = out or sys.stdout
        self.get = get or ghget._get
        self.isatty = isatty or (lambda: sys.stdin.isatty())
        self.ask = ask or (lambda prompt: input(prompt))
        self.fetch_pages = fetch_pages or globals()["fetch_pages"]

    def say(self, text=""):
        print(text, file=self.out)


def _load_tree(repo, working=False, derive=False):
    """(repository root, {path: bytes} of site/ and content/, parsed site.json). At HEAD, the commit that was published
    and the one a writer checks is clean; with `working`, the files as they are on disk now (what `list` and `check`
    describe, so a look just copied by `use` is there before it is committed)."""
    top = _toplevel(repo)
    try:
        files = gitfiles._disk_files(top) if working else gitfiles._commit_files(top)
    except outcomes.BuildError as e:
        raise LookCommandError("this repository holds no committed site (%s); run this inside a site-studio site's "
                               "repository, after its first commit" % e)
    if "site/site.json" not in files:
        raise LookCommandError(("derive needs the content that built the pages; adopt that site first" if derive else
                                "this folder holds no site-studio site; adopt that site first, or run this in its "
                                "repository") + " (there is no site/site.json here)")
    try:
        cfg = model.parse_text(files["site/site.json"].decode("utf-8", "replace"))
    except diagnostics.SiteConfigError as e:
        raise LookCommandError("site/site.json cannot be read (%s); a look is made for a site whose site.json reads, "
                               "so fix it or adopt that site first" % e)
    return top, files, cfg


def _toplevel(repo):
    try:
        p = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LookCommandError("could not run git (%s); install git, then try again" % e.__class__.__name__)
    if p.returncode != 0:
        raise LookCommandError("%s is not inside a git repo; run this in the site's repository" % repo)
    return os.path.realpath(p.stdout.decode("utf-8", "replace").strip())


def derive_command(repo, build_dir=None, url=None, owned_host=None, name=DEFAULT_NAME, replace=False, env=None):
    """The `derive` command. Returns the exit code; writes the look file only on success."""
    env = env or Env()
    if not _SLUG.match(name or ""):
        raise LookCommandError("the look name %r must be lower-case letters, digits and hyphens" % name)
    top, files, cfg = _load_tree(repo, derive=True)
    target = LOOKS_REL + name + ".json"
    full = os.path.join(top, *target.split("/"))
    never = []
    recorded = record(files)
    if build_dir:
        pages = read_build_dir(build_dir)
    else:
        hosts, html_url = set(), ""
        try:
            hosts, html_url = pages_host_set(cfg.publicRepo, env)
        except LookCommandError:
            if not (url and owned_host):
                raise
        start = url or html_url
        if not start:
            raise LookCommandError("there is no address to read; give one with --url, or derive from your local build "
                                   "with --build <folder of built pages>")
        host = (urllib.parse.urlsplit(start).hostname or "").lower()
        owned, on_word = settle_ownership(host, hosts, owned_host, top, url, env)
        if on_word:
            env.say(NOT_VERIFIED)
        pages, never = env.fetch_pages(start, owned, sorted(recorded[1]), env.out)
    d = derive_look(files, pages, never, recorded)
    text = d.text
    parsed = looks.parse(text, target)
    lits = literals(parsed)
    if os.path.exists(full):
        with open(full, "rb") as fh:
            same = fh.read() == text.encode("utf-8")
        if not same and not replace:
            raise LookCommandError("%s already exists with other content; derive writes nothing over it. Pick another "
                                   "--name, or add --replace to overwrite it" % target)
    for line in d.lines():
        env.say(line)
    if never:
        env.say("%d page(s) the content built were never read (cap of %d pages): those instances are `not reached`"
                % (len(never), FETCH_PAGES))
    addresses.write_bytes(top, target, text.encode("utf-8"))
    env.say("wrote %s (%d construct(s); structure and your own literal text)" % (target, len(parsed.constructs)))
    if lits:
        env.say("literal words this look carries (your own text, kept as the page had it):")
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
    env.say("nothing is committed. Use it with: look.py use %s" % target)
    return EXIT_OK


def list_command(repo, env=None):
    env = env or Env()
    env.say("looks site-studio ships (copy one into your site with `look.py use <id>`):")
    for sid in shipped_ids():
        _raw, lk = _read_look(os.path.join(SHIPPED_DIR, sid + ".json"), "templates/looks/%s.json" % sid, shipped=True)
        env.say("  %s  %d construct(s), %d literal word(s), %d stylesheet(s)"
                % (sid, len(lk.constructs), len(literals(lk)), len(lk.stylesheets)))
    try:
        top, files, cfg = _load_tree(repo, working=True)
    except LookCommandError:
        env.say("this folder is not a site-studio site, so no site looks are listed")
        return EXIT_OK
    env.say("looks this site carries (%s):" % LOOKS_REL)
    mine = sorted(p for p in files if p.startswith(LOOKS_REL) and p.endswith(".json"))
    if not mine:
        env.say("  none")
    for p in mine:
        mark = "  (in use)" if cfg.look == p else ""
        try:
            lk = looks.parse(files[p].decode("utf-8"), p)
            env.say("  %s  %d construct(s)%s" % (p, len(lk.constructs), mark))
        except (looks.LookError, UnicodeDecodeError):
            env.say("  %s  refused by the look rules; run `look.py check`%s" % (p, mark))
    env.say("the site uses: %s" % (cfg.look or "the plugin's own look (no `look` key in site.json)"))
    return EXIT_OK


def use_command(repo, source, accept_literals=False, env=None):
    env = env or Env()
    top, files, cfg = _load_tree(repo)
    kind, path, shown, slug = _find_source(source)
    raw, lk = _read_look(path, shown, shipped=(kind == "shipped"))
    lits = literals(lk)
    if lits and not accept_literals:
        env.say("%s carries %d literal word(s) of its own, which would appear on your pages:" % (shown, len(lits)))
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
        raise LookCommandError("nothing was copied. Read the words above, then run `use` again with --accept-literals "
                               "if you are happy with them")
    _prewrite(cfg, files)
    writes = {}
    target = LOOKS_REL + slug + ".json"
    writes[target] = raw
    # a look derived in this repository and not yet committed is its own source: it is not "uncommitted work"
    own = os.path.realpath(path) == os.path.realpath(os.path.join(top, *target.split("/")))
    dirty = [ln for ln in addresses._git_status(top) if not (own and ln[3:].strip() == target)]
    if dirty:
        raise LookCommandError("the tree has uncommitted changes in site/, content/ or .site-studio/ (%s); commit or "
                               "discard them first, then try again" % dirty[0].strip()[:80])
    src_root = None if kind == "shipped" else _repo_root_of(path)
    for rel in lk.stylesheets:
        if kind == "shipped":
            src = os.path.join(SHIPPED_DIR, posixpath.basename(rel))
            try:
                with open(src, "rb") as fh:
                    data = fh.read()
            except OSError:
                raise LookCommandError("%s names the stylesheet %s, which site-studio does not ship; reinstall the "
                                       "plugin" % (shown, rel))
        else:
            if src_root is None:
                raise LookCommandError("%s names the stylesheet %s, so it must be copied from a repository: use the "
                                       "file at <repository>/site/looks/%s.json" % (shown, rel, slug))
            try:
                check_stylesheet_file(src_root, rel, shown)
                with open(os.path.join(src_root, *rel.split("/")), "rb") as fh:
                    data = fh.read()
            except looks.LookError as e:
                raise LookCommandError("%s\nfix: %s" % (e, e.fix))
        try:
            scan_stylesheet(data.decode("utf-8"), rel)
        except (looks.LookError, UnicodeDecodeError) as e:
            raise LookCommandError("the stylesheet %s is refused: %s; fix the file, or leave it out of the look's "
                                   "stylesheets" % (rel, e))
        writes[rel] = data
    new = dict(files)
    for rel, data in writes.items():
        if rel in files and files[rel] != data:
            raise LookCommandError("%s already exists with other content; nothing was copied over it. Rename or remove "
                                   "that file if you want this look, or pick the other look's name" % rel)
        new[rel] = data
    d = cfg.to_dict()
    d["look"] = target
    d["schema"] = max(4, cfg.schema)          # a `look` key is a schema-4 key; the writer then holds the schema the tree needs
    site_json = canonical.canonical_text(model.parse_data(d), new, grammar.interpretation_reasons(new), at_least=4)
    new["site/site.json"] = site_json.encode("utf-8")
    acc = running.accept(dict((k, v) for k, v in new.items() if k.startswith(("site/", "content/"))))
    if acc.problems:
        raise LookCommandError("the site would not build with this look (%s); nothing was changed. Fix what the build "
                               "names, or choose another look" % "; ".join(p.line() for p in acc.problems[:2]))
    wrote, placed = [], []
    for rel in sorted(new):
        if files.get(rel) == new[rel]:
            if rel in writes:
                placed.append(rel)
            continue
        full = os.path.join(top, *rel.split("/"))
        if os.path.isfile(full):
            with open(full, "rb") as fh:
                if fh.read() == new[rel]:
                    placed.append(rel)
                    continue
        addresses.write_bytes(top, rel, new[rel])
        wrote.append(rel)
    for rel in placed:
        env.say("already in place: %s" % rel)
    for rel in wrote:
        env.say("wrote %s" % rel)
    env.say("site.json: look is %s" % target)
    env.say("nothing is committed: stage these paths with git add, then commit: %s" % " ".join(wrote + placed))
    return EXIT_OK


def _prewrite(cfg, files):
    """A `look` key is a schema-4 key, reached through schema 3 (the raise-schema pre-write check, R2-3)."""
    if cfg.schema < 3:
        raise LookCommandError("this site is at schema %d, and a look needs schema 4, which is reached through schema 3: "
                               "run `build.py raise-schema` (it lists what changes before it writes), commit, then try "
                               "again" % cfg.schema)
    probs = partblocks.part_collision_problems(files)
    if probs:
        raise LookCommandError("%s; a site with that part cannot be raised to schema 4, so rename it, then run `build.py "
                               "raise-schema` and try again" % probs[0].line())


def check_command(repo, env=None):
    env = env or Env()
    top, files, cfg = _load_tree(repo, working=True)
    if cfg.look is None:
        env.say("site.json names no look: the plugin's own look renders every construct")
        lk = looks.default_look()
        where = "the plugin's own look"
    else:
        raw = files.get(cfg.look)
        if raw is None:
            raise LookCommandError("site.json names the look %s, which is not committed; commit the file, or remove the "
                                   "look key" % cfg.look)
        try:
            lk = looks.parse(raw.decode("utf-8"), cfg.look)
        except (looks.LookError, UnicodeDecodeError) as e:
            raise LookCommandError("%s is refused:\n%s\nfix: %s" % (cfg.look, e, getattr(e, "fix", None) or "fix the lines above"))
        where = cfg.look
        for rel in lk.stylesheets:
            if rel not in files:
                raise LookCommandError("%s names the stylesheet %s, which is not committed; add the file, or remove it "
                                       "from the look" % (cfg.look, rel))
    env.say("look: %s (%d construct(s) of %d)" % (where, len(lk.constructs), len(looks.CONSTRUCTS)))
    for cid in lk.omitted():
        env.say("the look has no markup for %s; plugin markup is used" % cid)
    for cid, pn in looks.live_players(lk):
        env.say("%s.%s carries a live player: a visitor's browser loads a third party when the page loads" % (cid, pn))
    lits = literals(lk)
    if lits:
        env.say("%d literal word(s) in this look:" % len(lits))
        for cid, pn, t in lits:
            env.say("  %s.%s: %s" % (cid, pn, t[:80]))
    return EXIT_OK
