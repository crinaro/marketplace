"""carried.py -- `site.json` `carried` (schema 6, design-adopt-parity-2 section 4.7): each path it names is served from
`site/carried/<path>` byte for byte, neither token-expanded nor comment-stripped. An HTML path is a page of kind
`carried`, in the sitemap unless it is `404.html`.

`apply(b)` is the build's one carried step (`_SiteParts.build_carried`, called by `_Builder.build_sitemap` before the
sitemap is written, so every other output is known and a carried page is listed). WITHOUT THE KEY IT RETURNS AT ONCE:
the folder `site/carried/` is then not read, not published and not refused, at every schema, as 0.5.x ignores it
(section 3.2; `Upgrade050Unchanged` builds corpus C2, which holds the folder and no key). With the key:

1. a file under `site/carried/` the key does not name is refused, naming both; a path the key names with no file there
   is refused (section 4.7.1);
2. a page the plugin generates at a carried path gives way; anything else there (a `site/src` file, a redirect, a media
   file, a page whose path differs only in case) is a refusal naming both sources (section 4.7.1). The key itself
   refuses `CNAME`, `.nojekyll`, `robots.txt`, `sitemap.xml` and `site-studio/` (`configschema/sectioncheck.py`);
3. the addresses of every carried page and stylesheet are read as the site gate reads them
   (`sitechecks.carriedpages.read_address`), so the build refuses what the gate would find (section 4.7.3): a
   root-absolute or own-host address must lie inside the site's CURRENT path and name a file this build publishes, and
   no address may name the site's other origin. That is the refusal on the first build after `cutover`, `domain` or
   `previewUrl` moves the site; it names the page, each address, the path the address was evidently written for and the
   current one, and the two ways out. A carried page that holds such an address in a tree whose `site.json` gives no
   address is refused naming `previewUrl` and `domain`; one whose addresses are all relative needs no address;
4. every carried page gets its note: what it does not follow, and how many of its addresses hold the site's path.

The bytes of a carried file are never rewritten: every refusal leaves the correction to the person.
"""

import posixpath
import re
from building.constants import HTML_EXTS
from building.outcomes import BuildError
from building.tokens import nfc
from configschema.configkeys import CARRIED_SOURCE
from sitechecks import carriedpages
from sitechecks.page import parse_page
from sitechecks.tree import site_base

KEEPS_ITS_PATH = ("site", "redirect", "carried")      # page kinds that never give way to a carried page
DEPLOY_FILES = (".nojekyll", "robots.txt", "sitemap.xml")   # written by `build_sitemap` after this step


def apply(b):
    """The carried step of builder `b` (an `_Builder` whose pages, media and redirects are written). See the module
    docstring; nothing happens without the key."""
    named = sorted(nfc(p) for p in (b.cfg.carried or ()))
    if not named:
        return
    _refuse_unnamed(b.files, named)
    for path in named:
        source = CARRIED_SOURCE + path
        if source not in b.files:
            raise BuildError("site.json 'carried' names %s, and %s does not exist" % (path, source), path="site/site.json",
                             fix="add %s (the file as it should be served), or remove %s from carried" % (source, path))
        _give_way(b, path, source)
        b.add(path, b.files[source], source)
        if path.lower().endswith(HTML_EXTS):
            b.pages[path] = {"kind": "carried", "source": source, "lastmod_src": source,
                             "sitemap": posixpath.basename(path) != "404.html"}
    published = set(b.out) | set(DEPLOY_FILES) | (set(["CNAME"]) if b.cfg.cutover else set())
    for path in named:
        if path.lower().endswith(HTML_EXTS + (".css",)):
            held = _check_addresses(b.cfg, path, b.files[CARRIED_SOURCE + path], published)
            if path.lower().endswith(HTML_EXTS):
                b.notes.append(note(path, held, site_base(b.cfg)))


def _refuse_unnamed(files, named):
    for rel in sorted(files):
        if rel.startswith(CARRIED_SOURCE) and nfc(rel[len(CARRIED_SOURCE):]) not in named:
            out = rel[len(CARRIED_SOURCE):]
            raise BuildError("%s is in site/carried/, and site.json 'carried' does not name it (it names %s): a file there "
                             "is served only through that key" % (rel, ", ".join(named)), path=rel,
                             fix="add %s to carried, or remove %s" % (out, rel))


def _give_way(b, path, source):
    """Only a page the plugin generates gives way to a carried page; anything else at the same output path refuses."""
    key = path.casefold()
    if key not in b.owner:
        return
    prev_out, prev_src = b.owner[key]
    page = b.pages.get(prev_out)
    if (prev_out == path and page is not None and page["kind"] not in KEEPS_ITS_PATH
            and path.lower().endswith(HTML_EXTS)):
        del b.owner[key]
        del b.out[prev_out]
        del b.pages[prev_out]
        return
    raise BuildError("two sources write the same output file: %s (from %s) and %s (from %s); only a page site-studio "
                     "generates gives way to a carried one" % (prev_out, prev_src, path, source), path=source,
                     fix="remove %s from carried, or remove the other source of %s" % (path, prev_out))


def addresses(path, data):
    """Every address the carried file `path` (bytes `data`) writes, as the site gate reads them."""
    text = data.decode("utf-8", "replace")
    if path.lower().endswith(".css"):
        return carriedpages.css_refs(path, text)
    return carriedpages.page_refs(path, parse_page(path, text))


def _check_addresses(cfg, path, data, published):
    """Refuse the carried file `path` when an address on it no longer fits where the site is served (section 4.7.3);
    return the sorted addresses that hold the site's path (for the note)."""
    base = site_base(cfg)
    held, bad, unanchored = set(), [], []
    for _rel, _kind, url in addresses(path, data):
        reading, rest = carriedpages.read_address(url, base)
        if reading == carriedpages.UNANCHORED:
            unanchored.append(url)
        elif reading == carriedpages.OUTSIDE or (reading == carriedpages.SITE
                                                 and carriedpages.resolve_site(rest, published) is None):
            bad.append(url)
        elif reading == carriedpages.SITE:
            held.add(url)
    source = CARRIED_SOURCE + path
    if unanchored:
        raise BuildError("%s holds addresses that name the site's path (%s), and site.json gives no address to read them "
                         "against: set previewUrl, or domain with cutover" % (path, ", ".join(_unique(unanchored))),
                         path=source, fix="set previewUrl in site/site.json (or domain with cutover), or make the "
                                          "addresses in %s relative" % source)
    text = data.decode("utf-8", "replace")
    others = [o for o in carriedpages.other_origins(cfg) if re.search(re.escape(o) + r"(?![\w.-])", text)]
    if bad or others:
        shown = []
        for url in _unique(bad):
            was = carriedpages.written_for(url, published) if url.startswith("/") else None
            shown.append("%s (written for %s)" % (url, was) if was else url)
        for o in others:
            shown.append("%s (%s)" % (o, "the preview address, which the site is not served at after cutover"
                                      if cfg.cutover else "the custom domain, which is not live before cutover"))
        raise BuildError("%s is carried, and its addresses no longer fit where the site is served (%s, at %s): %s. A "
                         "carried page is never rewritten" % (path, carriedpages.shown_path(base), base, "; ".join(shown)),
                         path=source, fix="correct the addresses in %s, or remove %s from carried so site-studio builds "
                                          "the page" % (source, path))
    return sorted(held)


def _unique(urls):
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def note(path, held, base):
    """The note every build prints for the carried page `path` (section 4.7.3): both costs, in view."""
    first = ("%s is served as adopted; it does not change when the site does (a new menu item will not appear on it)."
             % path)
    last = "Remove it from `carried` to let site-studio build it."
    if not held:
        return "%s %s" % (first, last)
    return ("%s %d of its addresses hold the site's path %s: the build will stop and ask you to correct them when the "
            "site's address changes. %s" % (first, len(held), carriedpages.shown_path(base), last))
