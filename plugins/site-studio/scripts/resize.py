#!/usr/bin/env python3
"""resize.py -- the resizer for images.import_media: draw an image into a Chrome canvas, bake in
its EXIF orientation, cap its long edge and make the 480-1440 size copies (dev #835; design 5.1 and
5.3; named change M12(b)). Python 3.9, stdlib only; the pixels are Chrome's, driven by browser.py.

    make_sizes(job) -> {"main": bytes | None, "copies": {width: bytes}}     the images.py contract
    python3 resize.py import <src> <dest>      import one image (strip, orient, cap, size copies)

WHY A BROWSER. No decoder or encoder exists in the standard library, and the design's choice is ONE
resize path on every surface (the examples used Mac-only `sips`) (OURS). The copies are COMMITTED,
so a build never depends on a Chrome version; Chrome is needed only when a photo is imported.

NEVER file://. A canvas that draws a file:// image is tainted and `toDataURL` throws SecurityError
(P-1 item h). The source bytes and the resize page are served from one `LocalServer` on
127.0.0.1, so the canvas stays same-origin.

THE CONTRACT (images.py's ResizeJob, tests/test_images.py)
  * `main`: required when job.orientation != 1 or job.main_size != (job.width, job.height). It is
    UPRIGHT (the orientation is drawn into the pixels and no orientation tag is written: canvas
    output has none) at exactly job.main_size. None otherwise (the stripped original is kept).
  * `copies`: one per width in job.copy_widths, exactly that wide, height round(w * mh / mw)
    (rounded in Python, so JavaScript's rounding cannot differ from the importer's), same format as
    job.fmt. images.py VALIDATES everything this returns and re-strips it.
  * Orientation: job.data has had its EXIF removed, so Chrome decodes the STORED pixels, and this
    module draws them with the transform for job.orientation (1..8, EXIF numbering). Order: read,
    strip (images.py), then apply here. Applying the tag after stripping it is the defect M12(b)
    names (portrait phone photos come out sideways).
  * Encoding: JPEG and WebP at the fixed quality 0.85; PNG is lossless. GIF cannot be encoded by a
    canvas, so a GIF that needs pixels work is refused with the reason (an unchanged GIF needs no
    resizer). A browser that silently answers PNG when asked for another type is caught and refused.
  * Down-scaling draws once with `imageSmoothingQuality = "high"`; tests/test_resize.py proves a
    16x reduction of a 1-pixel checkerboard comes out mid-grey (not aliased). A manual halving loop
    was tried and removed: it changed nothing a test could see.

COLOUR (P-6, named change M12(b)). A wide-gamut (Display P3) source is converted to sRGB by Chrome
when it is drawn, and the output carries no profile. tests/test_resize.py MEASURES the difference
against macOS `sips` on a synthesized P3 image, on flat patches (so the resampling kernel cannot
contribute) and records it in tests/probes/P1-RESULT.md. The bound the test asserts, and the number
measured, are stated there. Where `sips` does not exist (Linux) the comparison is not made, and
the test says so; the P-6 colour question is a Mac-leg question.
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser  # noqa: E402
import images   # noqa: E402

QUALITY = 0.85
MIME = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# EXIF orientation 1..8 -> the canvas transform, in T() inside PAGE (EXIF numbering; 5..8 swap w and h)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>resize</title></head><body>
<script>
function T(o, w, h) {
  var m = {1:[1,0,0,1,0,0], 2:[-1,0,0,1,w,0], 3:[-1,0,0,-1,w,h], 4:[1,0,0,-1,0,h],
           5:[0,1,1,0,0,0], 6:[0,1,-1,0,h,0], 7:[0,-1,-1,0,h,w], 8:[0,-1,1,0,0,w]};
  return m[o];
}
function canvas(w, h) { var c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
function smooth(ctx) { ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; }
// draw `src` (a canvas) into a new canvas of tw x th. Chrome's high-quality smoothing averages a
// 16x down-scale without a manual halving pass (measured: a halving loop changed nothing the test
// could see, so there is none)
function scaleTo(src, tw, th) {
  var out = canvas(tw, th), oc = out.getContext('2d'); smooth(oc);
  oc.drawImage(src, 0, 0, tw, th);
  return out;
}
window.run = async function (job) {
  var img = new Image();
  img.src = job.src;
  await img.decode();
  var w = img.naturalWidth, h = img.naturalHeight;
  if (w !== job.width || h !== job.height) throw new Error('decoded ' + w + 'x' + h + ', expected ' + job.width + 'x' + job.height);
  var upW = job.orientation >= 5 ? h : w, upH = job.orientation >= 5 ? w : h;
  var up = canvas(upW, upH), uc = up.getContext('2d');
  var t = T(job.orientation, w, h);
  uc.setTransform(t[0], t[1], t[2], t[3], t[4], t[5]);
  uc.drawImage(img, 0, 0);
  var result = {main: null, copies: {}};
  var main = up;
  if (job.needMain) {
    main = (upW === job.mainW && upH === job.mainH) ? up : scaleTo(up, job.mainW, job.mainH);
    result.main = main.toDataURL(job.mime, job.quality);
  }
  for (var i = 0; i < job.copies.length; i++) {
    var c = job.copies[i];
    result.copies[String(c[0])] = scaleTo(main, c[0], c[1]).toDataURL(job.mime, job.quality);
  }
  return result;
};
</script></body></html>"""


class ResizeError(images.ImageError):
    pass


def _decode(url, fmt, what):
    head, _, b64 = url.partition(",")
    data = base64.b64decode(b64)
    got = images.detect_format(data)
    if got != fmt:
        raise ResizeError("Chrome could not encode the %s as %s (it produced %s)" % (what, fmt.upper(), got))
    return data


class Resizer(object):
    """A reusable resizer: one Chrome and one local server for many images. Use as a context
    manager, or call make_sizes(job) for a one-shot."""

    def __init__(self, chrome_browser=None):
        self._own = chrome_browser is None
        self.b = chrome_browser
        self.srv = None
        self.n = 0
        self.version = None

    def __enter__(self):
        if self.b is None:
            self.b = browser.Browser().start()
        self.srv = browser.LocalServer(routes={"/resize.html": ("text/html; charset=utf-8", PAGE.encode("utf-8"))})
        self.srv.start()
        self.version = self.b.version
        return self

    def __exit__(self, *exc):
        if self.srv is not None:
            self.srv.stop()
        if self._own and self.b is not None:
            self.b.close()
        return False

    def __call__(self, job):
        if job.fmt not in MIME:
            raise ResizeError("a %s image cannot be resized here (a browser canvas cannot encode it); "
                              "convert it to JPEG or PNG first" % job.fmt.upper())
        mw, mh = job.main_size
        need_main = job.orientation != 1 or (mw, mh) != (job.width, job.height)
        self.n += 1
        route = "/src-%d" % self.n
        self.srv.routes[route] = (MIME[job.fmt], job.data)
        copies = [[int(w), max(1, int(round(w * mh / float(mw))))] for w in job.copy_widths]
        spec = {"src": route, "width": job.width, "height": job.height, "orientation": job.orientation,
                "needMain": need_main, "mainW": mw, "mainH": mh, "mime": MIME[job.fmt],
                "quality": QUALITY, "copies": copies}
        page = self.b.new_page()
        try:
            page.goto(self.srv.url("resize.html"))
            try:
                got = page.evaluate("window.run(%s)" % json.dumps(spec), timeout=120)
            except browser.BrowserError as e:
                raise ResizeError("the resize step failed: %s" % e)
        finally:
            self.srv.routes.pop(route, None)
        out = {"main": None, "copies": {}}
        if got.get("main"):
            out["main"] = _decode(got["main"], job.fmt, "original")
        for w, url in got["copies"].items():
            out["copies"][int(w)] = _decode(url, job.fmt, "%sw copy" % w)
        return out


def make_sizes(job):
    """The resizer images.import_media calls: one Chrome launch per call (about a second)."""
    with Resizer() as r:
        return r(job)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "import":
        print("usage: resize.py import <src> <dest>")
        return 2
    try:
        res = images.import_media(argv[1], argv[2], make_sizes)
    except (images.ImageError, browser.BrowserError) as e:
        print("import refused: %s" % e)
        return 1
    print("imported %s (%dx%d %s, %d bytes); %d size copies%s" % (
        res.path, res.width, res.height, res.fmt, res.bytes, len(res.copies),
        "; orientation %d applied" % res.orientation_applied if res.orientation_applied != 1 else ""))
    for c in res.copies:
        print("  " + c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
