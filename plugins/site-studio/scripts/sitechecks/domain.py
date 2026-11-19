"""domain.py -- the `domain` family of the site gate (design 4.3). A mixin of `checker.Checker`.

  domain       CNAME present and equal to `domain` after cutover, absent before; canonical, og:url,
               sitemap <loc> and robots Sitemap all start with the site URL; no absolute URL to the
               other origin (the preview URL after cutover, the not-yet-live domain before); every
               page appears in the sitemap and every <loc> is a real page.
"""

import re
from sitechecks.tree import classify


class DomainChecks(object):
    """The `domain` family (a mixin of `Checker`)."""

    # -- domain ------------------------------------------------------------------------------
    def domain(self):
        fam = "domain"
        cfg = self.cfg
        n = 0
        has_cname = "CNAME" in self.t.files
        n += 1
        if cfg.cutover:
            if not has_cname:
                self.r.add(fam, "CNAME", "cutover is true but the build has no CNAME file")
            elif self.t.text("CNAME").strip() != cfg.domain:
                self.r.add(fam, "CNAME", "CNAME does not hold the domain %s" % cfg.domain)
        elif has_cname:
            self.r.add(fam, "CNAME", "a CNAME is published before cutover; the site would not be served "
                                     "from its preview address")
        if not self.base:
            self.r.notes.append("NOT CHECKED: canonical, og:url, sitemap and robots addresses "
                                "(no previewUrl or domain gives a site URL)")
            self.r.count(fam, n)
            return
        for rel in self.content_pages:
            p = self.pages[rel]
            expect = self.base + "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
            if rel == "index.html":
                expect = self.base + "/"
            for lt in p.linktags:
                if lt.get("rel", "").lower() == "canonical":
                    n += 1
                    if lt.get("href") != expect:
                        self.r.add(fam, rel, "canonical is %s, expected %s" % (lt.get("href"), expect))
            for m in p.metas:
                if m.get("property") == "og:url":
                    n += 1
                    if m.get("content") != expect:
                        self.r.add(fam, rel, "og:url is %s, expected %s" % (m.get("content"), expect))
        other = []
        if cfg.cutover and cfg.previewUrl:
            other.append(cfg.previewUrl.rstrip("/"))
        if not cfg.cutover and cfg.domain:
            other.append("https://" + cfg.domain)
        texts = [(rel, p.source) for rel, p in self.pages.items()]
        for rel in ("sitemap.xml", "robots.txt"):
            if rel in self.t.files:
                texts.append((rel, self.t.text(rel)))
        for rel, src in texts:
            n += 1
            for o in other:
                if re.search(re.escape(o) + r"(?![\w.-])", src):
                    why = "the preview address" if cfg.cutover else "the custom domain, which is not live before cutover"
                    self.r.add(fam, rel, "absolute URL to %s (%s)" % (o, why))
        locs = []
        if "sitemap.xml" in self.t.files:
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", self.t.text("sitemap.xml"), re.S)
            targets = set()
            for loc in locs:
                n += 1
                k, rest = classify(loc, self.base)
                if k != "internal":
                    self.r.add(fam, "sitemap.xml", "<loc> %s is outside %s" % (loc, self.base))
                    continue
                target, _f, problem = self.resolve("index.html", rest)
                if problem or target not in self.pages:
                    self.r.add(fam, "sitemap.xml", "<loc> %s is not a page in this build" % loc)
                else:
                    targets.add(target)
            for rel in self.content_pages:
                if rel != "404.html" and rel not in targets:
                    self.r.add(fam, rel, "page is missing from sitemap.xml")
        if "robots.txt" in self.t.files:
            n += 1
            m = re.search(r"(?im)^sitemap:\s*(\S+)", self.t.text("robots.txt"))
            if m and not m.group(1).startswith(self.base + "/"):
                self.r.add(fam, "robots.txt", "Sitemap line %s is outside %s" % (m.group(1), self.base))
        self.r.count(fam, n)
