"""linking.py -- the `links` and `reachable` families of the site gate (design 4.3). A mixin of
`checker.Checker`.

  Dated note, 2026-11-16 (dev #891): the `reachable` family flagged OFL.txt / LICENSE* beside a published
  font as "published but not referenced". The licence has to travel with the font and nothing links to it,
  so the flag was a false positive; such a file is now exempt ONLY in a folder that holds a font file.

  links        every internal href/src/srcset/css url()/meta-refresh resolves to a file in the tree
               (exact case: Pages is case-sensitive) and every #fragment to an id in that page;
               http:// and protocol-relative links are findings; the unique EXTERNAL links are
               listed by --report (they are never fetched: the gate has no network).
  reachable    every page is reachable from the home page by links (redirect stubs and the 404 page
               excepted) and every published non-page file is referenced by a page or stylesheet
               (the root files robots.txt, sitemap.xml, CNAME, .nojekyll and favicon.* excepted;
               and, from 0.3.1, a font licence file -- OFL.txt, LICENSE*, *.license -- in a folder
               that also holds a .woff2, .woff, .ttf or .otf file).
               THE ONE EXCEPTION to "every page is reachable" (0.4.0, template-fidelity, dated note 2026-11-18,
               owner ruling): the index of a one-piece portfolio built under `onePieceIndex: listing`. Under
               `menuLinks: "single-piece"` the menu links the piece, so that listing is a page nothing links, as
               on the site the person came from, and refusing it would make a faithful conversion unpublishable.
               It is exempt (and a `reachable:` note names it, never a quiet pass) ONLY when ALL of these hold:
               (1) its portfolio's content/<folder>/page.md in the repo says `onePieceIndex: listing` and
               `menuLinks: single-piece` and the build holds exactly one piece page of it; (2) every link inside
               its <main> resolves to that one piece; (3) nothing else in the build is unreachable: if any other
               page is, NO page gets the exception. Without the repo to read, no page gets it. A listing without
               the key, a listing that links another page, an unpublished path or an external address, and any
               extra unlinked page in the same build are each still refused (test_check_site.OnePieceListing).

  Dated note, 2026-11-20 (design-adopt-parity-2 sections 4.7.2 and 4.7.3, owner decision 2 (i)): a CARRIED file
  (`site.json` `carried`, schema 6; `sitechecks/carriedpages.py`) is the person's page as their old site served it.
  `links` HOLDS it: every address inside the site must resolve to a published file, and a root-absolute or own-host
  address is read as `carriedpages.read_address` reads it (inside the site's current path, with that path removed;
  one outside it, or with no site address to read it against, is `basepath`'s finding). The one thing not applied is
  the `http://` finding: the old site served that link, and it loads nothing of this site. `reachable` EXEMPTS a
  carried file, as it exempts the 404 page and a redirect stub: it is an address kept alive, and whether the new
  pages still link it is a difference parity already shows. A tree without the key is judged as before.

  Dated note, 2026-11-25 (design-publish-preflight section 3.4, dev 1068; looser only): under `site.json` `images.sizes` (schema 10,
  `as-written` or `held`) a size copy (`<stem>.w<N>.<ext>` or `<stem>-<N>w.<ext>`) whose ORIGINAL a page or stylesheet references
  counts as referenced: the old site served those addresses and the address guard keeps them. One `reachable:` note counts them. A copy
  whose original nothing references, and any tree without the key, are judged as before.
"""

import os
import posixpath
import re
from configschema import frontmatter
from sitechecks.carriedpages import SITE, read_address
from sitechecks.kinds import FONT_EXTS, ROOT_EXEMPT, is_font_licence
from sitechecks.tree import classify


class LinkChecks(object):
    """The `links` and `reachable` families (a mixin of `Checker`)."""

    # -- links -------------------------------------------------------------------------------
    def links(self):
        fam = "links"
        refs = self.collect_refs()
        self.all_refs = refs
        n = 0
        for rel, kind, url in refs:
            n += 1
            carried = rel in self.carried
            k, rest = classify(url, self.base)
            if carried and k == "rootabs":      # read inside the site's path, or left to `basepath` (the dated note)
                reading, rest = read_address(url, self.base)
                if reading != SITE:
                    continue
                k = "internal"
            if kind == "meta" and k == "internal":
                pass
            if k == "empty":
                if kind in ("a",):
                    self.r.add(fam, rel, "an empty href")
                continue
            if k in ("mail", "tel", "special", "fragment", "rootabs"):
                if k == "fragment":
                    self._check_fragment(rel, rel, rest)
                if k == "special" and rest.lower().startswith("javascript:"):
                    self.r.add(fam, rel, "a javascript: link")
                continue
            if k == "protorel":
                self.r.add(fam, rel, "protocol-relative URL %s: write https://" % url)
                continue
            if k == "external":
                if url.lower().startswith("http://") and not carried:
                    self.r.add(fam, rel, "insecure link %s: use https" % url)
                if kind in ("a", "iframe", "link", "script", "img", "srcset", "css", "meta"):
                    self.r.externals.setdefault(url, set()).add(rel)
                continue
            target, frag, problem = self.resolve(rel, rest if k == "internal" else url)
            if problem and kind != "meta":
                self.r.add(fam, rel, "%s link %s: %s" % (kind, url, problem))
                continue
            if problem:
                self.r.add(fam, rel, "meta URL %s: %s" % (url, problem))
                continue
            if target:
                self.referenced.add(target)
                if frag:
                    self._check_fragment(rel, target, frag)
        self.r.count(fam, n)

    def _check_fragment(self, from_rel, target, frag):
        if frag in ("", "top"):
            return
        p = self.pages.get(target)
        if p is None:
            return
        if frag not in p.ids:
            self.r.add("links", from_rel, "fragment #%s is not an id on %s" % (frag, target))

    # -- reachable ---------------------------------------------------------------------------
    def one_piece_listings(self, unreached):
        """{index page: portfolio folder} for the pages `unreached` that the `reachable` family does NOT refuse: the one exception to
        "every page is reachable from the home page" (the module docstring, dated note 2026-11-18). It holds only when ALL of these
        are true, and when one is not, NO page of the build gets it:
          1. the page is the index of a portfolio built under `onePieceIndex: listing` (its page.md says so, with `menuLinks:
             "single-piece"`, and the build holds exactly one piece page of that portfolio and no redirect in place of the index);
          2. the page links nothing beyond published pieces: every link inside its <main> resolves to that one piece;
          3. nothing else in the build is unreachable: every other unreached page is such a listing too.
        Without the repo (`--out` with no source to read) nothing is exempt: a missing fact reads as a refusal, never as a pass."""
        if not unreached or not self.repo:
            return {}
        found = {}
        for rel in unreached:
            folder = rel[:-len("/index.html")] if rel.endswith("/index.html") and rel.count("/") == 1 else None
            if folder is None or not self._says_listing(folder):
                return {}                                    # condition 1 fails for this page, and 3 for every other
            pieces = [r for r in self.content_pages if r.startswith(folder + "/") and r.count("/") == 2 and r.endswith("/index.html")]
            if len(pieces) != 1 or not self._links_only(rel, pieces[0]):
                return {}                                    # the build holds no single piece, or condition 2 fails
            found[rel] = folder
        return found

    def _says_listing(self, folder):
        """True when `content/<folder>/page.md` in the repo sets `onePieceIndex: listing` and `menuLinks: single-piece`, and does not
        set `view: page` (the build's own rule: `single_piece` and `onePieceIndex`)."""
        try:
            with open(os.path.join(self.repo, "content", folder, "page.md"), "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return False
        pairs = dict((k, v) for k, v, _n in frontmatter.front_matter_pairs(text))
        return (pairs.get("onePieceIndex") == "listing" and pairs.get("menuLinks") == "single-piece"
                and pairs.get("view") != "page")

    def _links_only(self, rel, piece):
        """True when every link inside the <main> of page `rel` resolves to the page `piece`."""
        for a in self.pages[rel].anchors:
            if not a["in_main"]:
                continue
            href = a["href"]
            if href is None:
                continue
            k, rest = classify(href, self.base)
            if k not in ("rel", "internal"):
                return False
            target, _frag, problem = self.resolve(rel, rest if k == "internal" else href)
            if problem or target != piece:
                return False
        return True

    _COPY_NAMES = (re.compile(r"^(?P<stem>.+)\.w\d+(?P<ext>\.\w+)$"), re.compile(r"^(?P<stem>.+)-\d+w(?P<ext>\.\w+)$"))

    def _copy_of_referenced(self, rel):
        """True when `rel` is a size copy (`<stem>.w<N>.<ext>` or `<stem>-<N>w.<ext>`) of an original that a page or stylesheet
        references: under `images.sizes` (either value) the copy is kept as that picture's own, because the old site served its address
        and the address guard keeps it (design-publish-preflight section 3.4)."""
        for rx in self._COPY_NAMES:
            m = rx.match(rel)
            if m and (m.group("stem") + m.group("ext")) in self.referenced:
                return True
        return False

    def reachable(self):
        fam = "reachable"
        if "index.html" not in self.pages:
            self.r.add(fam, ".", "there is no index.html to start from")
            return
        seen = set(["index.html"])
        queue = ["index.html"]
        while queue:
            cur = queue.pop()
            for a in self.pages[cur].anchors:
                href = a["href"]
                if href is None:
                    continue
                k, rest = classify(href, self.base)
                if k not in ("rel", "internal"):
                    continue
                target, _f, problem = self.resolve(cur, rest if k == "internal" else href)
                if target and not problem and target in self.pages and target not in seen:
                    seen.add(target)
                    queue.append(target)
        self.r.count(fam, len(self.pages) + len(self.t.files))
        unreached = [rel for rel in self.content_pages if rel != "404.html" and rel not in seen
                     and rel not in self.carried]       # an address kept alive (the dated note)
        listings = self.one_piece_listings(unreached)
        for rel in unreached:
            if rel in listings:
                self.r.notes.append("reachable: %s is the index of the one-piece portfolio %s, built under `onePieceIndex: listing`: "
                                    "nothing links it (as on the old site) and it links only its piece, so it is not refused"
                                    % (rel, listings[rel]))
                continue
            self.r.add(fam, rel, "page cannot be reached from the home page by following links")
        font_dirs = set(posixpath.dirname(r) for r in self.t.files if r.lower().endswith(FONT_EXTS))
        sizes_key = (getattr(self.cfg, "images", None) or {}).get("sizes")      # schema 10 (design-publish-preflight 3.4, dev 1068)
        kept_copies, kept = sizes_key in ("as-written", "held"), 0
        for rel in sorted(self.t.files):
            low = rel.lower()
            name = posixpath.basename(rel)
            if low.endswith((".html", ".htm")) or ("/" not in rel and name in ROOT_EXEMPT):
                continue
            if "/" not in rel and name.lower().startswith(("favicon", "apple-touch-icon")):
                continue
            if is_font_licence(name) and posixpath.dirname(rel) in font_dirs:
                continue
            if rel in self.flagged or rel in self.carried:
                continue
            if rel not in self.referenced:
                if kept_copies and self._copy_of_referenced(rel):
                    kept += 1
                    continue
                self.r.add(fam, rel, "published but not referenced by any page or stylesheet")
        if kept:
            self.r.notes.append("reachable: %d size copy(ies) of a picture a page uses are kept though no page links them "
                                "(`images.sizes: %s` in site.json; the old site served those addresses)" % (kept, sizes_key))
