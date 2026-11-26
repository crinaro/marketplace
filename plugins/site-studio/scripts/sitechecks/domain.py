"""domain.py -- the `domain` family of the site gate (design 4.3). A mixin of `checker.Checker`.

  domain       CNAME present and equal to `domain` after cutover, absent before; canonical, og:url,
               sitemap <loc> and robots Sitemap all start with the site URL; no absolute URL to the
               other origin (the preview URL after cutover, the not-yet-live domain before); every
               page appears in the sitemap and every <loc> is a real page.

  Dated note, 2026-11-20 (design-adopt-parity-2 sections 4.7.2 and 4.7.3, owner decision 2 (i) and (iii)): a CARRIED
  page (`site.json` `carried`, schema 6; `sitechecks/carriedpages.py`) is HELD to the cutover rule in full: no address
  on the site's other origin (`carriedpages.other_origins`, the one list the build's refusal reads too), and a carried
  page other than the 404 page is in the sitemap like any page. The one rule not applied to it is "canonical and
  og:url equal the page's own address": the build's `presence` writes those on its own pages only, a byte-for-byte page
  keeps what the person wrote, and refusing it for that form would change nothing for a visitor. `CNAME` is never
  carried (the key refuses it), so the CNAME rules are unchanged. A tree without the key is judged as before.

  Dated note, 2026-11-25 (design-publish-preflight section 7, dev 1068; looser only, `tests/test_gate_only_looser.py`): under `site.json`
  `sitemap: "indexable"` (schema 10) a page the build leaves out of the sitemap, because a `robots` meta holds `noindex` or `none`
  (`page.search_out`, the function the build asks too; `checker.left_out`), is not asked for: "page is missing from sitemap.xml" is not raised for
  it, carried pages included. A page listed anyway is still a real page, so a listed one passes. Without the key: as before.
"""

import re
from sitechecks.carriedpages import other_origins
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
        for rel in self.held_pages:             # a carried page keeps the canonical it was written with
            p = self.pages[rel]
            expect =self.base + "/" + (rel[:-len("index.html")] if rel.endswith("index.html") else rel)
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
        other = other_origins(cfg)
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
                if rel != "404.html" and rel not in targets and rel not in self.left_out:      # dated note 2026-11-25
                    self.r.add(fam, rel, "page is missing from sitemap.xml")
        if "robots.txt" in self.t.files:
            n += 1
            m = re.search(r"(?im)^sitemap:\s*(\S+)", self.t.text("robots.txt"))
            if m and not m.group(1).startswith(self.base + "/"):
                self.r.add(fam, "robots.txt", "Sitemap line %s is outside %s" % (m.group(1), self.base))
        self.r.count(fam, n)
