"""contentchecks.py -- the `media` and `unfinished` families of the site gate (design 4.3): what a page
shows. A mixin of `checker.Checker`.

  media        every <img> has an alt attribute (empty is allowed: decorative), a src that exists,
               width/height equal to the file header's, srcset widths equal to each file's real
               width and a sizes attribute; an alt text that is a file name; formats the web will
               not show (heic, tiff, bmp); a long edge over 2000 px; every <iframe> has a title and
               comes from a recognised video host (youtube-nocookie, player.vimeo, drive.google); and,
               from 0.3.0 (dev #865, site-fidelity section 7.3), the FACADE RULE: inside a `.ss-video` or
               `.ss-videos` block no `src`, `srcset`, `poster`, `data` or `<link href>` is remote, and
               the shipped `site-studio/blocks.css` has no remote `url()`. `href` and `data-embed`
               are exempt (they hold the video's address and load nothing before a click). SHAPE ONLY:
               it reads the markup the build wrote, not what a browser fetches; the behavioural half
               is test_build.py's `video.js` case, run under node.
               Since 0.4.0 (template-fidelity step 1.10, design 8 INV (d)) the rule's roots also
               include `.ss-map`, `.ss-showcase` and `.ss-gallery-video` (the schema-4 views and the
               gallery video item), the SVG elements `<image>` and `<use>` count their `href` and
               `xlink:href` as loading attributes (the map is an SVG), and the shipped
               `site-studio/schema-4.css` is held to the same no-remote-`url()` rule as `blocks.css`.
               A planted `<image href="https://...">` inside the map goes red (test_check_site.py
               SchemaFourFacades). Since 0.5.0 (design-movement-view section 4.1) `.ss-steps`, the steps
               view, is a root too, and `site-studio/schema-5.css` is held to the same rule; since 0.6.0
               (design-adopt-parity-2 section 4.8) `site-studio/schema-6.css` is too (`PLUGIN_STYLESHEETS`).
  unfinished   TODO/FIXME/TBD/lorem ipsum/coming soon/under construction in visible text, empty or
               "#" links, development URLs (localhost, 127.0.0.1, file://), a noindex page that is
               not a redirect stub, an untitled or empty page.

  Dated note, 2026-11-20 (design-adopt-parity-2 section 4.7.2, owner decision 2 (i)): a CARRIED file (`site.json`
  `carried`, schema 6; `sitechecks/carriedpages.py`) is the person's page as their old site served it. `media`'s
  per-page rules (an <img>'s alt, size and srcset, an <iframe>'s title and host, the facade rule) and the whole
  `unfinished` family are NOT applied to it: they hold the plugin's output to the plugin's form, and refusing the page
  now would change nothing for a visitor and block the person. `media`'s per-file rules (an image format browsers do
  not show, an unreadable header, a long edge over the cap, the plugin stylesheets' remote loads) hold every file,
  carried or not; an address on a carried page that names a development origin is still `basepath`'s finding. `checker.run` prints the
  `carried:` note, so the skip is never a quiet pass. A tree without the key is judged as before.

  Dated note, 2026-11-25 (design-publish-preflight sections 3.2 and 4, dev 1068; looser only, `tests/test_gate_only_looser.py`):
  (1) under `site.json` `images: {"sizes": "as-written"}` (schema 10) an <img> of ANY page the gate judges, hand-written pages
  included on every site kind, need not carry `width` and `height`, and a `srcset` need not carry `sizes`: the gate cannot tell a
  generated page from a hand-written one, and the old site's own pages are the commonest case. A WRITTEN value must still be
  true, and one note per page counts what was let through, so it is never quiet. No key: 0.9.0's rules. `held` (review R4, 2026-11-25): the same
  relief for every <img> WITHOUT `data-ss-held` (a hand page's picture, or a look's that the build did not size: the visitor invariant forbids
  changing a hand page's markup unasked, so the gate must not ask for it), with the same per-page note; an <img data-ss-held> is the build's
  own and is held to 0.9.0's rule (a size missing or wrong is refused). An empty `width=""` is as absent under the relief; a value that is
  not a number ("100%") is refused with the text "has an empty or non-numeric width", which is true, where it was told "no width attribute".
  (2) "untitled page" is not raised for a PIECE's own title, found from the source (`checker._piece_pages`: the page is
  `<portfolio>/<slug>/index.html`, `content/<portfolio>/<slug>/index.md` holds a `title` the page's `<title>` begins with, in the
  repo the gate is given, on a portfolio site); an empty title still is. With no repo, nothing is exempt.
  (3) under `site.json` `sitemap: "indexable"` (schema 10; section 7) "noindex page that is not a redirect stub" is not raised for a page the
  build leaves out of search (`page.search_out`) that is carried or whose source is `site/src/<same path>` in the repo the gate is given: the
  person put it there. One note per such page says so ("left out of search on purpose"). A noindex page with no such source, and every one when
  there is no repo, is refused as before; a `none` page was never refused, and is only noted. Without the key: as before.
"""

from imaging import plan, sniff
import os
import re
from urllib.parse import urlsplit
from sitechecks.kinds import BAD_IMAGE_EXTS, IMAGE_EXTS, VIDEO_HOSTS
from sitechecks.page import _CSS_COMMENT, _CSS_URL, _REMOTE_LOAD, facade_loads, parse_srcset
from sitechecks.tree import classify

# The plugin's own stylesheets a built site may hold, each held to the no-remote-load rule of the `media` family. A literal,
# not read from `building.constants`: no module of `sitechecks/` imports the builder. Each `.css` of
# `building.constants.PLUGIN_ASSETS` must be here (tests/test_content_css.py `Schema6Css`).
PLUGIN_STYLESHEETS = ("site-studio/blocks.css", "site-studio/schema-4.css", "site-studio/schema-5.css",
                      "site-studio/schema-6.css", "site-studio/held.css")


class ContentChecks(object):
    """The `media` and `unfinished` families: what a page shows (a mixin of `Checker`)."""

    # -- media -------------------------------------------------------------------------------
    def media(self):
        fam = "media"
        n = 0
        t = self.t
        mode = (getattr(self.cfg, "images", None) or {}).get("sizes")       # schema 10 (L1): "as-written", "held" or absent
        for rel in sorted(t.files):
            low = rel.lower()
            if low.endswith(BAD_IMAGE_EXTS):
                self.r.add(fam, rel, "this image format is not shown by browsers; convert it at import")
            if low.endswith(IMAGE_EXTS):
                n += 1
                dims = sniff.read_dimensions(t.read(rel))
                if dims is None:
                    self.r.add(fam, rel, "the image header cannot be read")
                elif max(dims) > plan.LONG_EDGE_CAP:
                    self.r.add(fam, rel, "long edge %d px is over the %d px cap" % (max(dims), plan.LONG_EDGE_CAP))
        for rel, p in sorted(self.pages.items()):
            if rel in self.carried:             # the page as the person wrote it (the dated note)
                continue
            unsized = unsized_set = 0           # under `images.sizes` as-written or held: counted in one note, never quiet
            for im in p.imgs:
                n += 1
                # relief: as-written, any picture; held, any picture the build did not size (no `data-ss-held`: a hand page's, or a look's that holds none)
                as_written = mode == "as-written" or (mode == "held" and not im["held"])
                src = im["src"]
                if src is None or src == "":
                    self.r.add(fam, rel, "an <img> with no src")
                    continue
                if im["alt"] is None:
                    self.r.add(fam, rel, "<img src=%s> has no alt attribute (use alt=\"\" if decorative)" % src)
                elif re.search(r"\.(jpe?g|png|gif|webp|svg|heic)\s*$", im["alt"], re.I) or \
                        re.match(r"^(IMG|DSC|PXL|P)[_-]?\d{3,}", im["alt"]):
                    self.r.add(fam, rel, "alt text %r is a file name" % im["alt"])
                k, rest = classify(src, self.base)
                if k not in ("rel", "internal"):
                    continue
                target, _f, problem = self.resolve(rel, rest if k == "internal" else src)
                if problem or target not in t.files:
                    continue
                dims = sniff.read_dimensions(t.read(target))
                if dims is None:
                    if not target.lower().endswith(".svg"):
                        self.r.add(fam, rel, "<img src=%s>: the image header cannot be read" % src)
                    continue
                bare = False
                for attr, want in (("width", dims[0]), ("height", dims[1])):
                    v = im[attr]
                    if as_written and (v is None or not str(v).strip()):
                        bare = True             # not carried (an empty `width=""` is as absent): as the old page had it. A WRITTEN value is still judged.
                    elif v is None:
                        self.r.add(fam, rel, "<img src=%s> has no %s attribute (layout shift)" % (src, attr))
                    elif not str(v).isdigit():
                        self.r.add(fam, rel, "<img src=%s> has an empty or non-numeric %s (%r): write the picture's %s in pixels, or leave the attribute "
                                   "out under images.sizes as-written" % (src, attr, v, attr))
                    elif int(v) != want:
                        self.r.add(fam, rel, "<img src=%s> %s=%s but the file is %d" % (src, attr, v, want))
                unsized += bare
                if im["srcset"]:
                    if not im["sizes"] and as_written:
                        unsized_set += 1
                    elif not im["sizes"]:
                        self.r.add(fam, rel, "<img src=%s> has a srcset but no sizes attribute" % src)
                    for u, d in parse_srcset(im["srcset"]):
                        kk, rr = classify(u, self.base)
                        tt, _f, pr = self.resolve(rel, rr if kk == "internal" else u) \
                            if kk in ("rel", "internal") else (None, "", "skip")
                        if pr or tt not in t.files:
                            continue
                        dd = sniff.read_dimensions(t.read(tt))
                        m = re.match(r"^(\d+)w$", d)
                        if not m:
                            self.r.add(fam, rel, "srcset candidate %s has no width descriptor" % u)
                        elif dd and int(m.group(1)) != dd[0]:
                            self.r.add(fam, rel, "srcset says %s is %sw but the file is %d wide"
                                       % (u, m.group(1), dd[0]))
            if unsized or unsized_set:
                self.r.notes.append("media: %s: %d <img> without a width or height and %d srcset without sizes, left as written "
                                    "(`images.sizes: \"%s\"` in site.json%s)" % (rel, unsized, unsized_set, mode,
                                     "; a picture the build did not size stays as it is" if mode == "held" else ""))
            for fr in p.iframes:
                n += 1
                src = fr.get("src", "")
                host = urlsplit(src).netloc.lower()
                if not fr.get("title"):
                    self.r.add(fam, rel, "<iframe src=%s> has no title" % src)
                if host not in VIDEO_HOSTS:
                    self.r.add(fam, rel, "<iframe> from %s, which is not a recognised video host" % (host or src))
            for tag, attr, val in facade_loads(p.source):
                n += 1
                self.r.add(fam, rel, "a video facade loads %s from another address before any click (<%s %s>); "
                           "a facade may load only a poster committed under media/" % (val, tag, attr))
        for css in PLUGIN_STYLESHEETS:
            if css in t.files:
                n += 1
                for m in _CSS_URL.finditer(_CSS_COMMENT.sub("", t.text(css))):
                    if _REMOTE_LOAD.match(m.group(2)):
                        self.r.add(fam, css, "the block stylesheet loads %s from another address; it may load "
                                   "nothing from outside the site" % m.group(2))
        self.r.count(fam, n)

    # -- unfinished --------------------------------------------------------------------------
    _UNFINISHED = re.compile(
        r"\b(?i:lorem ipsum|coming soon|under construction|your text here|insert text here)\b|"
        r"\b(?:TODO|FIXME|TBD|XXX)\b")

    def unfinished(self):
        fam = "unfinished"
        held = dict((rel, p) for rel, p in self.pages.items() if rel not in self.carried)    # the dated note
        for rel, p in sorted(held.items()):
            text =" ".join([p.visible_text, p.title] + p.attr_text)
            for m in self._UNFINISHED.finditer(text):
                self.r.add(fam, rel, "unfinished marker %r in the page text" % m.group(0))
            for a in p.anchors:
                if a["href"] is not None and a["href"].strip() in ("", "#"):
                    self.r.add(fam, rel, "a link that goes nowhere (href=%r)" % a["href"])
            if rel in self.redirects:
                continue
            if p.has_noindex and not self._on_purpose(rel):
                self.r.add(fam, rel, "noindex page that is not a redirect stub (a draft left in?)")
            # a PIECE's own title is its author's words ("Untitled", "Sans titre": design-publish-preflight section 4, T1; dev 1068): the
            # word is judged for any page but a piece's, found from the source (`checker._piece_pages`). An EMPTY title is refused for all.
            if not p.title.strip() or (rel not in self.pieces and
                                       re.match(r"(?i)^\s*(untitled|document|new page)\b", p.title)):
                self.r.add(fam, rel, "untitled page")
            if rel != "404.html" and not "".join(p.main_text or p.text).strip() and not p.imgs:
                self.r.add(fam, rel, "the page has no content")
        for rel in sorted(self.t.files):
            if rel.lower().endswith((".html", ".htm", ".js", ".css")) and rel not in self.carried:
                for m in re.finditer(r"(?i)\b(?:https?://)?(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?|file://", self.t.text(rel)):
                    self.r.add(fam, rel, "development address %r left in" % m.group(0))
                    break
        for rel in sorted(self.left_out):       # dated note, 2026-11-25 (3): never a quiet pass
            if rel in self.carried or self._on_purpose(rel) or not self.pages[rel].has_noindex:
                self.r.notes.append("unfinished: %s: left out of search on purpose (a `robots` meta says so, `sitemap: \"indexable\"` in "
                                    "site.json)" % rel)
        self.r.count(fam, len(held))

    def _on_purpose(self, rel):
        """True when the page `rel` is a noindex page the person put there (design-publish-preflight section 7, dev 1068): `site.json`
        `sitemap: "indexable"` is set, the page is one the build leaves out of search (`checker.left_out`), and its source is
        `site/src/<same path>` in the repo the gate is given. With no key, no repo or no such source: False (the page is refused). A CARRIED
        page never reaches here: the family does not judge it (dated note 2026-11-20)."""
        if rel not in self.left_out:
            return False
        return bool(self.repo) and os.path.isfile(os.path.join(self.repo, "site", "src", *rel.split("/")))
