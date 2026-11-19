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
"""

import re
from urllib.parse import urlsplit
from sitechecks.tree import classify


class PageMetaChecks(object):
    """The `head`, `nav` and `basepath` families (a mixin of `Checker`)."""

    # -- head --------------------------------------------------------------------------------
    def head(self):
        fam = "head"
        titles = {}
        for rel in self.content_pages:
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
            if len(rels) > 1:
                self.r.add(fam, rels[0], "the title %r is also used by %s" % (title, ", ".join(rels[1:])))
        self.r.count(fam, len(self.content_pages))

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
        for rel in self.content_pages:
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
        self.r.count(fam, len(self.content_pages))

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
            if k == "rootabs":
                self.r.add(fam, rel, "root-absolute %s %s breaks under the /<repo>/ preview path" % (kind, url))
            elif k == "external":
                u = urlsplit(url)
                if u.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or url.lower().startswith("file:"):
                    self.r.add(fam, rel, "development origin %s" % url)
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
