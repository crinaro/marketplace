"""pagemeta.py -- the `head`, `nav` and `basepath` families of the site gate (design 4.3). A mixin of
`checker.Checker`.

  head         per page: charset, viewport (width=device-width), a non-empty title unique across
               pages, a description, and, when a site URL is known, a canonical equal to the page's
               own URL plus og:title, og:description and og:url.
  nav          every page except the 404 page and redirect stubs carries the primary nav (the first
               <nav>), with the same set of targets as the home page; every page links home.
  basepath     the site is served under /<repo>/ before cutover, so a root-absolute link or url(),
               a <base> tag, a development origin, or an absolute URL on the site's own host but
               outside its path is a finding.

  Dated note, 2026-11-20 (design-adopt-parity-2 sections 4.7.2 and 4.7.3, owner decision 2 (i) and (ii)): a CARRIED
  file (`site.json` `carried`, schema 6; `sitechecks/carriedpages.py`) is the person's page as their old site served
  it. `head` and `nav` are NOT applied to it: they hold the plugin's output to the plugin's form (a canonical link from
  the build's `presence`, the menu every generated page shares), which a byte-for-byte page cannot have, and refusing
  it would change nothing for a visitor and block the person. `basepath` HOLDS it with one change: a root-absolute
  address is read as `carriedpages.read_address` reads it, so one inside the site's CURRENT path is accepted (`links`
  then requires it to resolve), one outside that path is a finding naming both, and one in a tree whose `site.json`
  gives no address is a finding naming `previewUrl` and `domain`. An absolute address on the site's host but outside
  its path was never this site's file and is not judged (it is listed with the external links). A `<base>` tag, a
  development origin and a `file:` address are refused as on any page. A tree without the key is judged as before.

  Dated note, 2026-11-25 (design-publish-preflight section 4, owner decision O-7 a, dev 1068; looser only): `head`'s duplicate-title
  finding is not raised when EVERY page of the group is a piece's (`checker._piece_pages`, read from the source); the group is one
  note naming the pages. One hand page in the group and the finding stands. A piece's title is its author's words.
"""

import re
from urllib.parse import urlsplit
from sitechecks.carriedpages import OUTSIDE, UNANCHORED, read_address, shown_path
from sitechecks.tree import classify


class PageMetaChecks(object):
    """The `head`, `nav` and `basepath` families (a mixin of `Checker`)."""

    # -- head --------------------------------------------------------------------------------
    def head(self):
        fam = "head"
        titles = {}
        for rel in self.held_pages:             # a carried page keeps its own head (the dated note)
            p = self.pages[rel]
            metas = p.metas
            if not any(m.get("charset", "").lower() == "utf-8" or
                       "charset=utf-8" in m.get("content", "").lower() for m in metas):
                self.r.add(fam, rel, "no <meta charset=\"utf-8\">")
            vp = [m for m in metas if m.get("name", "").lower() == "viewport"]
            if not vp or "width=device-width" not in vp[0].get("content", ""):
                self.r.add(fam, rel, "no <meta name=\"viewport\" content=\"width=device-width, ...\">")
            title = p.title.strip()
            if not title:
                self.r.add(fam, rel, "empty <title>")
            else:
                titles.setdefault(title, []).append(rel)
            desc = [m for m in metas if m.get("name", "").lower() == "description"]
            if not desc or not desc[0].get("content", "").strip():
                self.r.add(fam, rel, "no meta description")
            if self.base:
                have = dict((m.get("property"), m.get("content")) for m in metas if m.get("property"))
                if not any(lt.get("rel", "").lower() == "canonical" for lt in p.linktags):
                    self.r.add(fam, rel, "no canonical link")
                for prop in ("og:title", "og:description", "og:url"):
                    if not have.get(prop):
                        self.r.add(fam, rel, "no %s meta" % prop)
        for title, rels in sorted(titles.items()):
            if len(rels) > 1 and all(r in self.pieces for r in rels):
                # pieces carry the titles their author wrote, any title, in any language (O-7 a): a note, never a finding. ONE
                # hand page in the group and the finding below stands.
                self.r.notes.append("head: %d pieces are titled %r: %s (a piece's title is its author's words, so this is not "
                                    "refused)" % (len(rels), title, ", ".join(rels)))
            elif len(rels) > 1:
                self.r.add(fam, rels[0], "the title %r is also used by %s" % (title, ", ".join(rels[1:])))
        self.r.count(fam, len(self.held_pages))

    # -- nav ---------------------------------------------------------------------------------
    def nav(self):
        fam = "nav"
        home = self.pages.get("index.html")
        if home is None:
            return

        def targets(rel, p):
            out = set()
            for h in (p.nav_hrefs or []):
                k, rest = classify(h, self.base)
                if k in ("rel", "internal"):
                    t, _f, pr = self.resolve(rel, rest if k == "internal" else h)
                    out.add(t if t and not pr else "?" + h)
                else:
                    out.add(h)
            return out
        want = targets("index.html", home)
        if not want:
            self.r.add(fam, "index.html", "the home page has no primary navigation")
        for rel in self.held_pages:             # a carried page keeps its own menu (the dated note)
            p = self.pages[rel]
            links_home = False
            for a in p.anchors:
                if a["href"] is None:
                    continue
                k, rest = classify(a["href"], self.base)
                if k in ("rel", "internal"):
                    t, _f, pr = self.resolve(rel, rest if k == "internal" else a["href"])
                    if t == "index.html" and not pr:
                        links_home = True
                        break
            if not links_home:
                self.r.add(fam, rel, "the page does not link to the home page")
            if rel == "404.html":
                continue
            got = targets(rel, p)
            if p.nav_hrefs is None:
                self.r.add(fam, rel, "the page has no <nav>")
            elif got != want:
                missing = sorted(want - got)
                extra = sorted(got - want)
                self.r.add(fam, rel, "primary nav differs from the home page's (missing %s; extra %s)"
                           % (missing or "nothing", extra or "nothing"))
        self.r.count(fam, len(self.held_pages))

    # -- basepath ----------------------------------------------------------------------------
    def basepath(self):
        fam = "basepath"
        n = 0
        host = urlsplit(self.base).netloc.lower() if self.base else None
        sp = self.site_path()
        for rel, p in sorted(self.pages.items()):
            n += 1
            if p.base is not None:
                self.r.add(fam, rel, "a <base> tag changes how every relative link resolves")
        for rel, kind, url in getattr(self, "all_refs", []):
            k, rest = classify(url, self.base)
            carried = rel in self.carried
            if k == "rootabs" and carried:      # read against the site's current path (the dated note)
                reading, _rest = read_address(url, self.base)
                if reading == OUTSIDE:
                    self.r.add(fam, rel, "carried %s %s lies outside the site's path %s: a carried page is never rewritten, "
                               "so correct the address in site/carried/%s, or remove %s from carried"
                               % (kind, url, shown_path(self.base), rel, rel))
                elif reading == UNANCHORED:
                    self.r.add(fam, rel, "carried %s %s names the site's path, and site.json gives no address to read it "
                               "against: set previewUrl, or domain with cutover" % (kind, url))
            elif k == "rootabs":
                self.r.add(fam, rel, "root-absolute %s %s breaks under the /<repo>/ preview path" % (kind, url))
            elif k == "external":
                u = urlsplit(url)
                if u.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or url.lower().startswith("file:"):
                    self.r.add(fam, rel, "development origin %s" % url)
                elif carried:
                    pass                        # on the host but outside the path: never this site's file, not judged
                elif host and u.netloc.lower() == host and sp and not (u.path == sp or u.path.startswith(sp + "/")):
                    self.r.add(fam, rel, "absolute URL %s is on this site's host but outside %s" % (url, sp))
            elif k == "special" and url.lower().startswith("file:"):
                self.r.add(fam, rel, "file: URL %s" % url)
        for rel in sorted(self.t.files):
            low = rel.lower()
            if low.endswith(".js"):
                n += 1
                for m in re.finditer(r"""(?:src|href|fetch|url|location(?:\.href)?)\s*[=(:]\s*['"](/[A-Za-z0-9_.-][^'"]*)['"]""",
                                     self.t.text(rel)):
                    self.r.add(fam, rel, "script uses the root-absolute path %s" % m.group(1))
            elif low.endswith(".css"):
                n += 1
        self.r.count(fam, n)
