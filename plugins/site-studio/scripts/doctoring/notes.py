"""doctoring.notes -- the two lines the full report adds in 0.10.0 for a site that could set a key it has not (design-publish-preflight sections 6 and 7;
group `publish-preflight`; dev 1068; O-4 and O-5 chose a key, never a change to a published site, so the owner of a published site is TOLD, here).

  blank rows   pieces hold a front matter line with no value for a key their portfolio lists (`meta`, `cardMeta`), the site has no `blankMeta` for that
               portfolio, so each such piece prints an empty row and a card an empty separator. The line names the key to set.
  sitemap      the site's own hand pages (`site/src`) and carried pages (`site/carried`, named by `carried`) include pages that tell search to leave them
               out (a `noindex` robots meta, a meta refresh), the site has no `sitemap` key, so `sitemap.xml` lists them.

READ-ONLY and CHEAP: no build, no `gh`, no network, no process; `site.json`, each portfolio's `page.md`, each piece's `index.md` and those hand pages are
read from disk and parsed in this process (a few milliseconds for a hundred pieces). Both lines are for a site site-studio manages (`site.json` holds
`schema`) that names a `publicRepo`: the one thing a person can read of "published" without asking GitHub. Never raises: a file that does not read is no line
(the build says what is wrong with it), never a guess. `blank` and `sitechecks.page.search_out` are the build's own rules (`building.readsources.blank` is held
equal by this module's test, since a doctor line must not import the build).
"""
import json
import os

from contentmodel import frontmatter
from contentmodel.errors import ContentError
from sitechecks import page as sitepage

HAND_PAGES = "site/src"
CARRIED_PAGES = "site/carried"
HTML = (".html", ".htm")
FIRST = 3                                   # the pages or pieces a line names before "and N more"
RESERVED = ("media", "resume", "references", "home", "about")


def blank(value):
    """True for a front matter value that says nothing: nothing at all, text of spaces only, an empty list. `False` and `0` are values."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, tuple)) and not value


def _site(repo):
    """site.json as a dict when it is a site this plugin manages that names a public repo, else None."""
    try:
        with open(os.path.join(repo, "site", "site.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    ok = isinstance(cfg, dict) and isinstance(cfg.get("schema"), int) and isinstance(cfg.get("publicRepo"), str) and cfg["publicRepo"]
    return cfg if ok else None


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def _keys(value):
    """The keys of a `meta` or `cardMeta` list: a string, or the first member of a `[key, label]` pair."""
    out = []
    for item in value if isinstance(value, list) else ():
        item = item[0] if isinstance(item, (list, tuple)) and item else item
        if isinstance(item, str):
            out.append(item)
    return out


def _folders(repo):
    path = os.path.join(repo, "content")
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return []
    return [n for n in names if not n.startswith("_") and n not in RESERVED and os.path.isdir(os.path.join(path, n))]


def _portfolio(repo, cfg, name):
    """(listed keys, blankMeta set) for portfolio `name`: its own page.md over site.json's `work` for the portfolio named `work`."""
    settings = dict(cfg.get("work") or {}) if name == "work" and isinstance(cfg.get("work"), dict) else {}
    try:
        settings.update(frontmatter.parse_front_matter(_read(os.path.join(repo, "content", name, "page.md")), name)[0])
    except (OSError, UnicodeDecodeError, ContentError):
        pass
    return set(_keys(settings.get("meta")) + _keys(settings.get("cardMeta"))), "blankMeta" in settings


def blank_pieces(repo, cfg):
    """[(portfolio, piece path, the first blank listed key)] for every piece (a draft is not one) that holds a blank value for a key its portfolio lists, in a
    portfolio with no `blankMeta`."""
    found = []
    for name in _folders(repo):
        listed, has = _portfolio(repo, cfg, name)
        if has or not listed:
            continue
        base = os.path.join(repo, "content", name)
        try:
            slugs = sorted(s for s in os.listdir(base) if not s.startswith("_"))
        except OSError:
            continue
        for slug in slugs:
            rel = "content/%s/%s/index.md" % (name, slug)
            try:
                meta = frontmatter.parse_front_matter(_read(os.path.join(repo, rel)), rel)[0]
            except (OSError, UnicodeDecodeError, ContentError):
                continue
            hit = sorted(k for k in listed if k in meta and blank(meta[k]))
            if hit and meta.get("draft") is not True:
                found.append((name, rel, hit[0]))
    return found


def blank_lines(repo):
    """[the one line] for a published site whose pieces would print empty rows, else []."""
    cfg = _site(repo)
    found = blank_pieces(repo, cfg) if cfg else []
    if not found:
        return []
    ports = sorted(set(p for p, _rel, _k in found))
    first = ", ".join("%s (%s)" % (rel, k) for _p, rel, k in found[:FIRST]) + (" and %d more" % (len(found) - FIRST) if len(found) > FIRST else "")
    return ["%d piece(s) hold a front matter line with no value for a key their portfolio lists, so a page prints an empty row and a card an empty "
            "separator: %s. `blankMeta: \"omit\"` in %s leaves them out (site settings version 10; `build.py raise-schema --to 10`)"
            % (len(found), first, ", ".join("content/%s/page.md" % p for p in ports))]


def sitemap_pages(repo, cfg):
    """[path] of the hand pages and the named carried pages that tell search to leave them out (`sitechecks.page.search_out`), `404.html` excepted
    (the sitemap never lists it)."""
    files = []
    for here, dirs, names in os.walk(os.path.join(repo, *HAND_PAGES.split("/"))):
        dirs.sort()
        files += [os.path.join(here, n) for n in sorted(names)]
    carried = cfg.get("carried")
    files += [os.path.join(repo, *CARRIED_PAGES.split("/"), *c.split("/")) for c in carried if isinstance(c, str)] if isinstance(carried, list) else []
    out = []
    for path in files:
        rel = os.path.relpath(path, repo).replace(os.sep, "/")
        if not rel.lower().endswith(HTML) or os.path.basename(rel).lower() == "404.html":
            continue
        try:
            if sitepage.search_out(sitepage.parse_page(rel, _read(path))):
                out.append(rel)
        except (OSError, UnicodeDecodeError):
            continue
    return out


def sitemap_lines(repo):
    """[the one line] for a published site whose sitemap would list pages that are out of search, with no `sitemap` key, else []."""
    cfg = _site(repo)
    found = sitemap_pages(repo, cfg) if cfg and "sitemap" not in cfg else []
    if not found:
        return []
    return ["sitemap.xml lists %d page(s) that tell search to leave them out (%s%s). `\"sitemap\": \"indexable\"` in site/site.json leaves them out of it "
            "(site settings version 10; `build.py raise-schema --to 10`)"
            % (len(found), ", ".join(found[:FIRST]), " and %d more" % (len(found) - FIRST) if len(found) > FIRST else "")]


def lines(repo):
    """The lines of both notes, in that order. Never raises."""
    out = []
    for fn in (blank_lines, sitemap_lines):
        try:
            out += fn(repo)
        except Exception:                      # a note must never cost the report its other lines
            continue
    return out
