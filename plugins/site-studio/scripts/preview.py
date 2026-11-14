#!/usr/bin/env python3
"""preview.py -- build the site WITH DRAFTS into a temporary folder and serve it on 127.0.0.1
under the path the public site will really have (dev #835; design 5.3). Python 3.9, standard
library only; no browser needed (a person opens the printed URL, or the preview skill opens it in
the desktop app's pane).

    python3 preview.py [--repo R] [--port N] [--seconds N]
    prints:  preview: http://127.0.0.1:PORT/<base>/     (and how many drafts it shows)

THE PATH IS THE POINT. A GitHub Pages project site lives at https://<user>.github.io/<repo>/, so
the preview is served under that same base path (taken from the site's own address: site.json
`previewUrl`, or `domain` after cutover, so a custom domain is served at the root). A root-absolute
`/css/site.css` that works on a laptop and 404s on the project site is therefore a 404 here too
(design 5.3: "so base-path defects show"). `/` redirects to the base so the bare URL still works.
Anything else under the server's root is a plain 404.

WHAT IT IS NOT. It never writes into the repo (the build goes to a temp folder, removed on exit),
never starts any program but git (through build.preview_build), and binds to 127.0.0.1 only: there
is no flag for another address. The page content is the WORKING TREE, drafts included, so what the
person sees is what they are editing; it is not the digest-bound publish build (design 3.5), and
nothing here can publish.

    Preview(repo)        a context manager: .url .base .out_dir .result .cfg .page_url(out_path)
"""
import argparse
import os
import shutil
import signal
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser    # noqa: E402
import build      # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402


def base_path(cfg):
    """The path the site is served under on the web: the path of its address, else the repo name."""
    url = cfg.site_url()
    if url:
        return urllib.parse.urlsplit(url).path.strip("/")
    repo = (cfg.publicRepo or "").split("/")[-1]
    return repo.strip("/")


class Preview(object):
    """A drafts-included build of `repo`'s working tree, served on 127.0.0.1 under the base path."""

    def __init__(self, repo, port=0):
        self.repo = os.path.abspath(repo)
        self.port = port
        self.tmp = None
        self.server = None
        self.result = None
        self.cfg = None
        self.base = ""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="site-studio-preview-")
        try:
            out = os.path.join(self.tmp, "site")
            self.result = build.preview_build(self.repo, out)
            self.cfg = siteconfig.load(os.path.join(self.repo, "site", "site.json"))
            self.base = base_path(self.cfg)
            self.out_dir = out
            self.server = browser.LocalServer(out, base=self.base, port=self.port).start()
        except Exception:
            self._cleanup()
            raise
        return self

    def __exit__(self, *exc):
        self._cleanup()
        return False

    def _cleanup(self):
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    @property
    def url(self):
        return self.server.url("")

    def page_url(self, out_path):
        """The URL of a built page given its output path ("work/index.html" -> .../work/)."""
        rel = out_path[:-len("index.html")] if out_path.endswith("index.html") else out_path
        return self.server.url(rel)


def build_parser():
    ap = argparse.ArgumentParser(prog="preview.py", allow_abbrev=False,
                                 description="Serve a drafts-included build of the working tree on 127.0.0.1.")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current directory)")
    ap.add_argument("--port", type=int, default=0, help="a port on 127.0.0.1 (default: any free port)")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this many seconds (default: run until interrupted)")
    return ap


def _stop(_signum, _frame):
    raise KeyboardInterrupt()


def main(argv=None):
    rc = platform_check.windows_refusal_rc("preview.py")
    if rc is not None:
        return rc
    args = build_parser().parse_args(argv)
    signal.signal(signal.SIGTERM, _stop)     # a stopped preview still removes its temp folder
    try:
        with Preview(args.repo, args.port) as pv:
            print("preview: %s" % pv.url)
            print("pages: %d (drafts included; this is the working tree, not the publish build)" % len(pv.result.pages))
            for n in pv.result.notes:
                print("note: %s" % n)
            sys.stdout.flush()
            end = time.time() + args.seconds if args.seconds else None
            try:
                while end is None or time.time() < end:
                    time.sleep(0.25)
            except KeyboardInterrupt:
                pass
        return 0
    except (build.BuildError, siteconfig.SiteConfigError, browser.BrowserError, OSError) as e:
        print("preview refused: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
