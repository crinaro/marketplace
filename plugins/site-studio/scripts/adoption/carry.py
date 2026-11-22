"""adoption.carry -- the `carried` setting on adopt's side (design-adopt-parity-2 sections 4.7, 7.4, 7.6; owner decision 2).

Part of the `adoption` package behind the entry point `adopt.py`. The build side is `building/carried.py` and the gate's
`sitechecks/carriedpages.py` (step 5b); this module says which pages adopt OFFERS to carry, and writes a carried page into
the converted tree from the bytes the measurement stored.

THE CANDIDATE (`offered`, section 7.6): the files only the old build has, each an HTML page or a file whose bytes are no
tracked file's (a file whose bytes ARE a tracked file's is a media address, `mediaPaths`' to answer for), each at most
`CARRY_BYTES`, at most `CARRY_MAX` of them; less every path section 4.7.1 reserves (the `carried` key's own check,
`sectioncheck._carried_path`: `CNAME`, `.nojekyll`, `robots.txt`, `sitemap.xml`, `site-studio/`, a name the site gate never
publishes), and less every page the build would refuse as carried (section 4.7.3, decision 2 (iv)): its addresses are read
as the build reads them (`building.carried.addresses`, `sitechecks.carriedpages.read_address`) against the site's address in
the CONVERTED `site.json`, and a page whose addresses lie outside the path the plugin's build is served at, or that names a
path while `site.json` gives no address, is not offered. Each page left out keeps its reason line (`Offer.excluded`), and
stays an ACCEPT row of kind `page`: nothing is rewritten, and nothing is carried that the next build would refuse.

ONLY WHAT THE COMMITTED TREE PUBLISHES (dated note 2026-11-21, step 10c, step 10b's F14). Parity builds a COPY of the working
copy, ignored files included (it says so in its notes), so the old build can hold a page whose only source is a file no commit
holds: an ignored scratch page the builder copies. The publisher's clean checkout never serves it, and the plugin's publish build
is a pure function of the committed tree, so such a page is never offered: `offer_for` reads the working copy's files no commit
holds (`working_only`: ignored and untracked, less the build's output folders, `node_modules`, `.git` and the app's worktrees),
and `offered` leaves out an old-build file whose bytes are one of them and no tracked file's, with a reason line that names the
file. The evidence is equal bytes (a copied file); a page an old builder MAKES from such a file is not recognised (a limit).

ONLY WHAT A PAGE OF THE NEW SITE LOADS (dated note 2026-11-21, step 10d; coordinator ruling on step 10c's F17). A non-page
file (anything not HTML) only the old build serves is offered only when a page the plugin's build serves, or a page that is
itself offered, loads or links it, directly or through a stylesheet it loads (`unloaded`, `loaded`). A script no page of the
new site loads changes nothing a visitor sees by being carried, and carrying it would hide the real difference: the page that
used it differs, and that stays in the report as the file's `only-local` row. So `template-views`' `js/play.js`, which only
the old click-to-play page loads, is not offered: "js/play.js is not carried: no page of the new site loads or links it, ...".

THE BYTES (section 7.4's `carried` row): the measurement stores each offered page's bytes in the plan's `hints` under
`HINT`, `{path: {"sha256": <hex>, "data": <base64>}}` (`hints_for`); the conversion (`write`) writes `site/carried/<path>`
and the key from them, each checked against its sha256 first (`carried_bytes`), and refuses on a mismatch or a missing
entry rather than write a page that is not the one measured.

WIRED (dated note 2026-11-21, steps 10b, 10c and 10d, step 10's F1). `adoption.measure` asks `offer_for` once per run, against the
converted tree of pass one and the old build, and puts the offered pages' bytes (and those of a `carried` the person chose)
into the plan's `hints` before any setting is measured; `candidates.candidates_for("carried", ...)` offers `[None, <the offered
paths>]` from the same answer; `settings.apply_settings` writes the setting with `write` (a person's `adopt.py setting carried
404.html` is written from the stored bytes); `plan.V6_SETTING_FAMILIES` names it, so a plan holding it is written at schema 3;
and `measure._choose_settings` hands `choose` `candidates.measured_names`, so every run with an old build measures it (the
switch step 10c held, applied at step 10d once `js/play.js` was no longer offered). Rule M judges it on the pages its candidate
names (`scope`), never on `settings.setting_paths("carried")` (`*`): under `*` M2 needed the whole site EQUAL, M3 refused a candidate that builds other
pages and M4 had no scope, so the 404 page an old site served could never be chosen. `scope(local)` is the one place the scoring
reads that set from, keyed by the very old build it was offered against.
"""

import base64
import hashlib
import os
import posixpath

from building import running
from building.carried import addresses
from configschema.configkeys import CARRIED_SOURCE
from configschema.diagnostics import SiteConfigError
from configschema.sectioncheck import _carried_path
from sitechecks import carriedpages
from sitechecks.tree import site_base

from adoption.base import Refused, gitt

CARRY_MAX = 12                       # section 7.6: at most twelve pages offered
CARRY_BYTES = 512 * 1024             # section 7.6: each at most 512 KB
HINT = "carried"                     # the member of the plan's `hints` that holds the bytes
_PAGE = (".html", ".htm")
_CHECKED = _PAGE + (".css",)        # what the build reads addresses on (`building.carried.apply`)
_NOT_SOURCES = ("site/dist/", "dist/", "_site/", ".claude/worktrees/")   # parity empties or skips these (`parity.OUTPUT_DIRS`)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Offer(object):
    """`paths`: the pages offered, sorted (the candidate's value); `excluded`: {path: the reason line it is not offered}."""

    def __init__(self, paths, excluded):
        self.paths, self.excluded = list(paths), dict(excluded)

    def lines(self):
        return [self.excluded[p] for p in sorted(self.excluded)]


def only_old(local, built, tracked):
    """The paths only the old build has (`local` {path: bytes}, `built` the plugin's output paths) that are pages, or files
    whose bytes are no tracked file's (`tracked`: the converted tree, {path: bytes})."""
    shas = set(sha(b) for b in tracked.values())
    return [p for p in sorted(local) if p not in built and (p.lower().endswith(_PAGE) or sha(local[p]) not in shas)]


def _until(cfg):
    return "until cutover" if not getattr(cfg, "cutover", False) else "since cutover"


def misfit(path, data, cfg, local, published):
    """The reason line when the build would refuse `path` (bytes `data`) as carried under `cfg` (the converted `site.json`),
    else None (section 4.7.3): an address outside the site's path, one inside it that names no file of `published` (what the
    plugin's build would serve, the carried pages with it), or one that names a path while `site.json` gives no address.
    `local` is the old build: what a root-absolute address was evidently written for."""
    if not path.lower().endswith(_CHECKED):
        return None
    base = site_base(cfg)
    outside, unanchored = [], []
    for _rel, _kind, url in addresses(path, data):
        reading, rest = carriedpages.read_address(url, base)
        if reading == carriedpages.UNANCHORED:
            unanchored.append(url)
        elif reading == carriedpages.OUTSIDE or (reading == carriedpages.SITE
                                                 and carriedpages.resolve_site(rest, published) is None):
            outside.append(url)
    if unanchored:
        return ("%s is not carried: it holds addresses that name the site's path (%s), and site.json gives no address to read "
                "them against: set previewUrl, or domain with cutover, then carry it (`adopt.py setting carried %s`)"
                % (path, ", ".join(sorted(set(unanchored))[:3]), path))
    if outside:
        was = sorted(set(w for w in (carriedpages.written_for(u, set(local)) for u in outside) if w))
        here = carriedpages.shown_path(base)
        return ("%s is not carried: its addresses assume %s, and site-studio's build is served at %s %s. %s, or correct the "
                "addresses" % (path, " and ".join(was) or "another path", here, _until(cfg),
                               ("Carry it after cutover (`adopt.py setting carried %s`)" % path) if not cfg.cutover else
                               ("Carry it once they fit (`adopt.py setting carried %s`)" % path)))
    return None


def _not_source(rel):
    return rel.startswith(_NOT_SOURCES) or bool({".git", "node_modules"} & set(rel.split("/")))


def working_only(repo, sizes):
    """{path: (bytes, "ignored" | "untracked")} for the files of `repo`'s working copy that no commit holds, of a size in `sizes`
    (only a file of an old-build candidate's size can have its bytes); never under `_NOT_SOURCES`, `node_modules` or `.git`."""
    out = {}
    if not repo or not sizes:
        return out
    for how, extra in (("ignored", ("-i",)), ("untracked", ())):
        listed = gitt(repo, "ls-files", "-z", "-o", "--exclude-standard", "--directory", *extra, check=False)
        for rel in [r for r in listed.split("\0") if r and not _not_source(r)]:
            top = os.path.join(repo, *rel.rstrip("/").split("/"))
            found = [top] if not rel.endswith("/") else [os.path.join(d, n) for d, dirs, names in os.walk(top) for n in names]
            for full in found:
                path = os.path.relpath(full, repo).replace(os.sep, "/")
                if path in out or _not_source(path) or os.path.islink(full) or not os.path.isfile(full) \
                        or os.path.getsize(full) not in sizes:
                    continue
                with open(full, "rb") as fh:
                    out[path] = (fh.read(), how)
    return out


def uncommitted(path, data, tracked, working):
    """The reason line when the bytes `data` of the old-build file `path` are a working-copy file's that no commit holds, and
    no tracked file's, else None: its only source is a file the publisher's clean checkout does not have."""
    mine = sha(data)
    if not working or any(sha(b) == mine for b in tracked.values()):
        return None
    src = sorted((p, how) for p, (b, how) in working.items() if sha(b) == mine)
    if not src:
        return None
    return ("%s is not carried: its only source is %s, a file in your working copy that no commit holds (%s), so a build of "
            "your committed files never publishes it; commit it if the site should serve it" % (path, src[0][0], src[0][1]))


def _named(src, url, base, published):
    """The file of `published` the address `url`, written on the file `src`, names, else None: a relative address is read from
    `src`'s folder, a site address (`carriedpages.read_address`) from the site root, both as the gate resolves them."""
    reading, rest = carriedpages.read_address(url, base)
    if reading == "rel":
        rest = "/" + posixpath.join(posixpath.dirname(src), rest)
    elif reading != carriedpages.SITE:
        return None
    return carriedpages.resolve_site(rest, published)


def loaded(files, pages, cfg, published):
    """The paths of `published` that the pages `pages` load or link (`building.carried.addresses`: anchors, images, scripts,
    link tags, frames, refreshes, `url()`s), through any stylesheet they load in turn. `files` {path: bytes} holds every
    page and stylesheet that may be read; a file of `published` outside it is reached but not read."""
    base, seen, todo = site_base(cfg), set(), sorted(pages)
    while todo:
        src = todo.pop()
        for _rel, _kind, url in addresses(src, files[src]):
            hit = _named(src, url, base, published)
            if hit and hit not in seen:
                seen.add(hit)
                if hit.lower().endswith(".css") and hit in files and hit not in pages:
                    todo.append(hit)
    return seen


def unloaded(paths, local, built, tracked, cfg, published):
    """{path: reason line} for each non-page file of `paths` (the candidates that survived every other test) that no page of
    the new site loads or links: neither a page the plugin's build serves (`built`, {path: bytes}; a set of paths is built
    again from `tracked` to read them) nor a page of `paths` (dated note 2026-11-21, step 10d, the module docstring)."""
    files = [p for p in paths if not p.lower().endswith(_PAGE)]
    if not files:
        return {}
    if not isinstance(built, dict):
        built = dict(running.accept(tracked).output)
    readable = dict((p, b) for p, b in built.items() if p.lower().endswith(_CHECKED))
    readable.update((p, local[p]) for p in paths if p.lower().endswith(_CHECKED))
    pages = [p for p in readable if p.lower().endswith(_PAGE)]
    reached = loaded(readable, pages, cfg, published)
    return dict((p, "%s is not carried: no page of the new site loads or links it, so carrying it would change nothing a "
                    "visitor sees; the page that used it is where your sites differ" % p) for p in files if p not in reached)


def offered(local, built, tracked, cfg, working=None):
    """The `Offer` of the `carried` setting (the module docstring): `local` the old build, `built` the plugin's output under
    the default settings ({path: bytes}; a set of its paths is accepted, and then it is built again only when a non-page file
    is a candidate), `tracked` the converted tree, `cfg` its `site.json` (a `SiteConfig`), `working` the working copy's files
    no commit holds (`working_only`; None when not read)."""
    paths, excluded = [], {}
    olds = only_old(local, built, tracked)
    published = set(built) | set(olds)
    for p in olds:
        why = uncommitted(p, local[p], tracked, working)
        if why:
            excluded[p] = why
            continue
        try:
            _carried_path(p, "carried")
        except SiteConfigError as e:
            excluded[p] = ("your old site publishes a CNAME; site-studio writes one from `domain` once `cutover` is true"
                           if p == "CNAME" else "%s is not carried: %s" % (p, str(e).split("never carried: ", 1)[-1]))
            continue
        if len(local[p]) > CARRY_BYTES:
            excluded[p] = "%s is not carried: it is %d KB, and adopt carries a file of at most %d KB" % (
                p, (len(local[p]) + 1023) // 1024, CARRY_BYTES // 1024)
            continue
        why = misfit(p, local[p], cfg, local, published)
        if why:
            excluded[p] = why
            continue
        paths.append(p)
    for p, why in unloaded(paths, local, built, tracked, cfg, published).items():
        excluded[p] = why
        paths.remove(p)
    for p in paths[CARRY_MAX:]:
        excluded[p] = ("%s is not carried: adopt offers at most %d pages to carry; carry it yourself with `adopt.py setting "
                       "carried`" % (p, CARRY_MAX))
    return Offer(paths[:CARRY_MAX], excluded)


_LAST = [None]


def offer_for(snap, local, repo=None):
    """The `Offer` for the converted tree `snap` against the old build `local`: the plugin's build of `snap` under the default
    settings says which paths it writes and what its `site.json` is; `repo`, the dev repo whose working copy the old build ran
    on, says which of its files no commit holds (`working_only`). Asked again with the same two objects (every pass of
    `choose`, which passes no `repo`), the same answer is returned without a second build."""
    last = _LAST[0]
    if last is not None and last[0] is snap and last[1] is local:
        return last[2]
    acc = running.accept(snap)
    res = Offer([], {})
    if acc.cfg is not None and not acc.problems:
        built = dict(acc.output)
        sizes = set(len(local[p]) for p in only_old(local, built, snap))
        res = offered(local, built, snap, acc.cfg, working_only(repo, sizes))
    _LAST[0] = (snap, local, res)
    return res


def scope(local):
    """The pages `carried`'s candidate names for the old build `local`: the paths of the last `offer_for` asked against that very
    build (the object `choose` judges with), else [] (nothing was offered against it, so nothing is in scope)."""
    last = _LAST[0]
    return list(last[2].paths) if last is not None and last[1] is local else []


def hints_for(local, paths):
    """The `hints` member that carries the bytes of `paths` (each a path of the old build `local`)."""
    return dict((p, {"sha256": sha(local[p]), "data": base64.b64encode(local[p]).decode("ascii")}) for p in sorted(paths)
                if p in local)


def carried_bytes(hints, path):
    """The bytes of the carried page `path` from `hints`, checked against their sha256; Refused when they are missing or
    are not the bytes that were measured."""
    row = ((hints or {}).get(HINT) or {}).get(path)
    if not isinstance(row, dict) or not isinstance(row.get("data"), str) or not isinstance(row.get("sha256"), str):
        raise Refused("carried names %s, and the plan holds no measured bytes for it; run `adopt.py parity` again so the old "
                      "build's page is measured" % path)
    try:
        data = base64.b64decode(row["data"].encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        data = None
    if data is None or sha(data) != row["sha256"]:
        raise Refused("carried names %s, and the bytes the plan holds for it are not the ones measured (their sha256 differs); "
                      "run `adopt.py parity` again" % path)
    return data


def write(files, d, value, hints, notes):
    """Write the `carried` setting `value` (a list of output paths) into the converted tree: `site/carried/<path>` from the
    bytes in `hints` (`carried_bytes`) and the key in `d` (site.json's dict); one note line."""
    paths = sorted(value)
    for p in paths:
        files[CARRIED_SOURCE + p] = carried_bytes(hints, p)
    d["carried"] = paths
    notes["settings"].append("carried: %s (served as your old site served it, byte for byte)" % ", ".join(paths))
