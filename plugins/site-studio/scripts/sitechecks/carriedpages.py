"""carriedpages.py -- which files of a built tree are carried, and how an address on one is read (`site.json` `carried`,
schema 6, design-adopt-parity-2 sections 4.7.2 and 4.7.3).

A carried file is served from `site/carried/<path>` byte for byte: the person's page as their old site already served it.
The site gate holds it to what protects a visitor or the person (`privacy`, `links`, `domain`, `basepath`, `size` and the
per-file rules of `structure`) and not to the form the plugin gives its own pages; each family module says which, in its
own dated note. The build (`building/carried.py`) reads a carried file's addresses with the same functions, so the build
refuses exactly what the gate would find.

An address on a carried file is read one of these ways (`read_address`):
  site        root-absolute (`/<site path>/site.css`) or absolute on the site's own host, and inside the site's CURRENT path
              (`SiteConfig.site_path()`): read with that path removed, from the site root. It must name a published file.
  outside     root-absolute and not inside the current path: what a carried page says on the first build after `cutover`,
              `domain` or `previewUrl` moves the site. Refused.
  unanchored  root-absolute while `site.json` gives no address to read it against. Refused: the repo's name is a guess good
              enough to serve a preview, never to accept a person's page on.
  otherwise   `tree.classify`'s reading, unchanged: a relative address resolves as on any page; an address on the site's
              host but outside its path was never this site's file and is listed with the external links, not judged.
"""

import posixpath
import re
from urllib.parse import unquote, urlsplit
from sitechecks.page import _CSS_IMPORT, _CSS_URL, parse_srcset
from sitechecks.tree import classify

PAGE_EXTS = (".html", ".htm")
SITE, OUTSIDE, UNANCHORED = "site", "outside", "unanchored"
NOT_HELD = "head, nav, comments, media, unfinished, performance or page structure"


def carried_in(cfg, files):
    """The output paths `site.json` `carried` names that the tree `files` holds, as a frozenset: empty without the key, so
    a tree 0.5.x builds is judged exactly as before."""
    return frozenset(p for p in (getattr(cfg, "carried", None) or ()) if p in files)


def is_page(rel):
    return rel.lower().endswith(PAGE_EXTS)


def carried_note(n):
    """The gate's line for `n` carried pages: a family that skips them says so, never a quiet pass (section 4.7.2)."""
    return "carried: %d page(s) are served as adopted and are not held to %s" % (n, NOT_HELD)


def page_refs(rel, p):
    """Every address the parsed page `p` writes, as (rel, kind, url), in the order the site gate has always read them:
    the per-page half of `Checker.collect_refs`, one reader for the gate and the build."""
    refs = []
    for a in p.anchors:
        if a["href"] is not None:
            refs.append((rel, "a", a["href"]))
    for im in p.imgs:
        if im["src"] is not None:
            refs.append((rel, "img", im["src"]))
        for u, _d in parse_srcset(im["srcset"]):
            refs.append((rel, "srcset", u))
    for s in p.scripts:
        if s["src"]:
            refs.append((rel, "script", s["src"]))
    for lt in p.linktags:
        if lt.get("href") and lt.get("rel", "").lower() not in ("canonical",):
            refs.append((rel, "link", lt["href"]))
    for fr in p.iframes:
        if fr.get("src"):
            refs.append((rel, "iframe", fr["src"]))
    for m in p.metas:
        if m.get("http-equiv", "").lower() == "refresh":
            mm = re.search(r"url\s*=\s*(.+)$", m.get("content", ""), re.I)
            if mm:
                refs.append((rel, "refresh", mm.group(1).strip().strip("'\"")))
        if m.get("property") in ("og:image", "og:url") or m.get("name") == "twitter:image":
            if m.get("content"):
                refs.append((rel, "meta", m["content"]))
    for st in p.style_text + p.inline_style_attrs:
        for _q, u in _CSS_URL.findall(st):
            refs.append((rel, "css", u))
    return refs


def css_refs(rel, css):
    """Every address the stylesheet text `css` writes, as (rel, "css", url): its `url()`s, then its `@import`s."""
    return [(rel, "css", u) for _q, u in _CSS_URL.findall(css)] + [(rel, "css", u) for u in _CSS_IMPORT.findall(css)]


def other_origins(cfg):
    """The site's other origin, which no published file may name (the `domain` family's rule): the preview address after
    cutover, the custom domain, not yet live, before it."""
    other = []
    if cfg.cutover and cfg.previewUrl:
        other.append(cfg.previewUrl.rstrip("/"))
    if not cfg.cutover and cfg.domain:
        other.append("https://" + cfg.domain)
    return other


def shown_path(base):
    """The site's path as a person reads it (`/site/`, or `/` at the root of a domain), from `tree.site_base`'s value."""
    path = urlsplit(base).path.strip("/") if base else ""
    return "/" + path + "/" if path else "/"


def read_address(url, base):
    """How an address on a carried file is read (the module docstring): (reading, rest). `base` is `tree.site_base(cfg)`,
    None when `site.json` gives no address. A `site` reading's `rest` starts with `/` and is resolved from the site root."""
    k, rest = classify(url, base)
    if k == "internal":
        return (SITE, rest)
    if k != "rootabs":
        return (k, rest)
    if base is None:
        return (UNANCHORED, rest)
    path = urlsplit(base).path.rstrip("/")
    if not path:
        return (SITE, rest)
    if rest == path or rest.startswith((path + "/", path + "?", path + "#")):
        left = rest[len(path):]
        return (SITE, left if left.startswith("/") else "/" + left)
    return (OUTSIDE, rest)


def resolve_site(rest, published):
    """The published output path a `site` reading names, or None: the gate's own resolution (`Checker.resolve` for a
    root-absolute address), over the set `published`."""
    path = unquote(urlsplit(rest).path)
    joined = path.lstrip("/")
    cand = posixpath.normpath(joined) if joined else ""
    if cand == ".":
        cand = ""
    if cand.startswith(".."):
        return None
    if path.endswith("/") or cand == "":
        idx = (cand + "/index.html").lstrip("/")
        return idx if idx in published else None
    if cand in published:
        return cand
    return cand + "/index.html" if (cand + "/index.html") in published else None


def written_for(address, published):
    """The path a root-absolute `address` was evidently written for: `/` when it names a published file read from the
    root, `/<first segment>/` when it does once that segment is removed; None when neither holds. An inference from the
    bytes, said as one: the build keeps no record of the site's old address."""
    if resolve_site(address, published):
        return "/"
    m = re.match(r"^/([^/?#]+)(/[^?#]*)?", address)
    if m and resolve_site(m.group(2) or "/", published):
        return "/%s/" % m.group(1)
    return None
