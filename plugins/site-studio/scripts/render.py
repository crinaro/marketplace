#!/usr/bin/env python3
"""render.py -- visual QA material for a built site: full-height PNGs at phone and desktop widths in
light and dark, horizontal-overflow flags, and page weight (dev #835; design 5.3; named change M8).
Python 3.9, standard library only; Chrome through browser.py. The `visual-qa` skill reads the PNGs.

    python3 render.py [--repo R | --site DIR] [--out DIR] [--pages a/index.html,...] [--weight] [--json]

WHAT IT DOES, per page, per (phone 390 | desktop 1440) x (light | dark)
  1. loads the page from a local server under the real base path (preview.py; or --site DIR, a
     folder of built pages served at the root, for a site built elsewhere);
  2. applies `prefers-color-scheme` through the DevTools emulation, before navigation;
  3. does ONE slow scroll from top to bottom and back, so lazy images load (a full-page shot of an
     unscrolled lazy page shows empty boxes: design 5.3);
  4. checks horizontal overflow: `scrollWidth > clientWidth`, naming up to five elements whose box
     reaches past the viewport;
  5. writes <out>/<page>-<phone|desktop>-<light|dark>.png at 1x, the whole document (captureBeyondViewport).
  `--weight` also records the bytes each page costs at 2x and 3x device scale, from Chrome's own
  network events (Network.loadingFinished.encodedDataLength): a separate Chrome per scale, so one
  scale's cache cannot make the next one read as free. It is the weight of the page and every
  resource it loaded, after the scroll.

WRITES <out>/report.json: the Chrome version and platform (named change M8, so a later Chrome
change shows), every PNG, every overflow, every weight. Prints one line per finding.

EXIT: 0 when no page overflows; 1 when any does (the overflow IS the finding) or a page cannot
load; 2 on a usage error. The default --out is a fresh folder under the system temp directory,
printed, never inside the repo.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser   # noqa: E402
import preview   # noqa: E402

VIEWPORTS = (("phone", 390, 844), ("desktop", 1440, 900))
SCHEMES = ("light", "dark")
WEIGHT_SCALES = (2, 3)

OVERFLOW_JS = """(function(){
  var de = document.documentElement, vw = de.clientWidth, bad = [];
  var all = document.querySelectorAll('body *');
  for (var i = 0; i < all.length && bad.length < 5; i++) {
    var r = all[i].getBoundingClientRect();
    if (r.width > 0 && r.right > vw + 1) {
      var e = all[i], s = e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
        (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\\s+/).join('.') : '');
      bad.push(s + ' (right edge ' + Math.round(r.right) + ' px)');
    }
  }
  return {scrollWidth: de.scrollWidth, clientWidth: vw, culprits: bad};
})()"""


def slug(page):
    """A file-name-safe name for a page's output path: 'work/index.html' -> 'work'."""
    s = page[:-len("index.html")] if page.endswith("index.html") else page
    s = re.sub(r"\.html?$", "", s).strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s.replace("/", "--")) or "home"


def pages_in(directory):
    out = []
    for d, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith((".html", ".htm")):
                out.append(os.path.relpath(os.path.join(d, f), directory).replace(os.sep, "/"))
    return sorted(out)


def render_site(serve, pages, out_dir, weight=False, log=print):
    """Render `pages` (output paths) from `serve` (an object with .page_url(path)); returns the report
    dict."""
    os.makedirs(out_dir, exist_ok=True)
    report = {"pages": [], "overflow": [], "weights": {}, "png": [], "errors": []}
    with browser.Browser() as b:
        report["browser"] = b.packet()
        for page in pages:
            url = serve.page_url(page)
            for vname, width, height in VIEWPORTS:
                for scheme in SCHEMES:
                    try:
                        p = b.new_page(width=width, height=height, scale=1, dark=(scheme == "dark"))
                        p.goto(url)
                        if p.status and p.status >= 400 and page != "404.html":
                            raise browser.BrowserError("%s answered HTTP %d" % (url, p.status))
                        p.scroll_through()
                        time.sleep(0.2)
                        ov = p.evaluate(OVERFLOW_JS)
                        png = p.screenshot()
                    except browser.BrowserError as e:
                        report["errors"].append({"page": page, "viewport": vname, "scheme": scheme, "error": str(e)})
                        log("ERROR %s (%s, %s): %s" % (page, vname, scheme, e))
                        continue
                    name = "%s-%s-%s.png" % (slug(page), vname, scheme)
                    with open(os.path.join(out_dir, name), "wb") as fh:
                        fh.write(png)
                    report["png"].append(name)
                    if ov["scrollWidth"] > ov["clientWidth"] + 1:
                        rec = {"page": page, "viewport": vname, "width": width, "scrollWidth": ov["scrollWidth"],
                               "culprits": ov["culprits"]}
                        if not any(o["page"] == page and o["viewport"] == vname for o in report["overflow"]):
                            report["overflow"].append(rec)
                            log("OVERFLOW %s at %s px (%s): the page is %d px wide; %s" % (
                                page, width, vname, ov["scrollWidth"], "; ".join(ov["culprits"]) or "no single element named"))
            report["pages"].append(page)
    if weight:
        for scale in WEIGHT_SCALES:
            with browser.Browser() as b:     # a fresh profile and cache per scale
                for page in pages:
                    try:
                        p = b.new_page(width=390, height=844, scale=scale)
                        p.goto(serve.page_url(page))
                        p.scroll_through()
                        time.sleep(0.4)
                        net = p.network()
                    except browser.BrowserError as e:
                        report["errors"].append({"page": page, "scale": scale, "error": str(e)})
                        log("ERROR weight %s at %dx: %s" % (page, scale, e))
                        continue
                    report["weights"].setdefault(page, {})["%dx" % scale] = net["bytes"]
                    report["weights"][page]["requests_%dx" % scale] = len(net["requests"])
        for page in sorted(report["weights"]):
            w = report["weights"][page]
            log("WEIGHT %s: %s bytes at 2x, %s bytes at 3x" % (page, w.get("2x", "?"), w.get("3x", "?")))
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return report


class _Dir(object):
    """--site DIR: built pages served at the root of a local server."""

    def __init__(self, directory):
        self.server = browser.LocalServer(directory)

    def __enter__(self):
        self.server.start()
        return self

    def __exit__(self, *exc):
        self.server.stop()
        return False

    def page_url(self, out_path):
        rel = out_path[:-len("index.html")] if out_path.endswith("index.html") else out_path
        return self.server.url(rel)


def build_parser():
    ap = argparse.ArgumentParser(prog="render.py", allow_abbrev=False,
                                 description="Full-height PNGs, overflow flags and page weight for a built site.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--repo", help="the dev repo to build (drafts included) and render (default: the current directory)")
    g.add_argument("--site", help="a folder of already-built pages to render, served at the root")
    ap.add_argument("--out", help="where to write the PNGs and report.json (default: a new temp folder)")
    ap.add_argument("--pages", help="comma-separated output paths to render (default: every page)")
    ap.add_argument("--weight", action="store_true", help="also record bytes per page at 2x and 3x")
    ap.add_argument("--json", action="store_true", help="print the report as JSON instead of lines")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = args.out or tempfile.mkdtemp(prefix="site-studio-render-")
    try:
        browser.require_chrome()
        log = (lambda s: None) if args.json else print
        if args.site:
            with _Dir(args.site) as srv:
                pages = pages_in(args.site)
                pages = [p for p in pages if not args.pages or p in args.pages.split(",")]
                rep = render_site(srv, pages, out, args.weight, log)
        else:
            with preview.Preview(args.repo or ".") as pv:
                pages = [p for p, _k in pv.result.pages if p.endswith((".html", ".htm"))]
                pages = [p for p in pages if not args.pages or p in args.pages.split(",")]
                rep = render_site(pv, pages, out, args.weight, log)
        if args.json:
            print(json.dumps(rep, indent=2, sort_keys=True))
        else:
            print("rendered %d page(s) x %d views: %d PNG(s) in %s" % (
                len(rep["pages"]), len(VIEWPORTS) * len(SCHEMES), len(rep["png"]), out))
            print("browser: %s" % rep["browser"]["chrome"])
            print("overflow: %d page(s)" % len(rep["overflow"]))
        return 1 if (rep["overflow"] or rep["errors"]) else 0
    except Exception as e:     # BuildError, SiteConfigError, BrowserError: one line, never a traceback
        if isinstance(e, (browser.BrowserError, ValueError, OSError)):
            print("render refused: %s" % e)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
