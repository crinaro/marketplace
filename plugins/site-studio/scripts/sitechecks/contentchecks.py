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
               SchemaFourFacades).
  unfinished   TODO/FIXME/TBD/lorem ipsum/coming soon/under construction in visible text, empty or
               "#" links, development URLs (localhost, 127.0.0.1, file://), a noindex page that is
               not a redirect stub, an untitled or empty page.
"""

from imaging import plan, sniff
import re
from urllib.parse import urlsplit
from sitechecks.kinds import BAD_IMAGE_EXTS, IMAGE_EXTS, VIDEO_HOSTS
from sitechecks.page import _CSS_COMMENT, _CSS_URL, _REMOTE_LOAD, facade_loads, parse_srcset
from sitechecks.tree import classify


class ContentChecks(object):
    """The `media` and `unfinished` families: what a page shows (a mixin of `Checker`)."""

    # -- media -------------------------------------------------------------------------------
    def media(self):
        fam = "media"
        n = 0
        t = self.t
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
            for im in p.imgs:
                n += 1
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
                for attr, want in (("width", dims[0]), ("height", dims[1])):
                    v = im[attr]
                    if v is None or not str(v).isdigit():
                        self.r.add(fam, rel, "<img src=%s> has no %s attribute (layout shift)" % (src, attr))
                    elif int(v) != want:
                        self.r.add(fam, rel, "<img src=%s> %s=%s but the file is %d" % (src, attr, v, want))
                if im["srcset"]:
                    if not im["sizes"]:
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
        for css in ("site-studio/blocks.css", "site-studio/schema-4.css"):
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
        for rel, p in sorted(self.pages.items()):
            text = " ".join([p.visible_text, p.title] + p.attr_text)
            for m in self._UNFINISHED.finditer(text):
                self.r.add(fam, rel, "unfinished marker %r in the page text" % m.group(0))
            for a in p.anchors:
                if a["href"] is not None and a["href"].strip() in ("", "#"):
                    self.r.add(fam, rel, "a link that goes nowhere (href=%r)" % a["href"])
            if rel in self.redirects:
                continue
            if p.has_noindex:
                self.r.add(fam, rel, "noindex page that is not a redirect stub (a draft left in?)")
            if not p.title.strip() or re.match(r"(?i)^\s*(untitled|document|new page)\b", p.title):
                self.r.add(fam, rel, "untitled page")
            if rel != "404.html" and not "".join(p.main_text or p.text).strip() and not p.imgs:
                self.r.add(fam, rel, "the page has no content")
        for rel in sorted(self.t.files):
            if rel.lower().endswith((".html", ".htm", ".js", ".css")):
                for m in re.finditer(r"(?i)\b(?:https?://)?(localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?|file://", self.t.text(rel)):
                    self.r.add(fam, rel, "development address %r left in" % m.group(0))
                    break
        self.r.count(fam, len(self.pages))
