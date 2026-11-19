#!/usr/bin/env python3
"""check_site.py -- the site gate (dev #835, design sections 4.3, 7.1, 8.2; named changes M8, M10).
Python 3.9, stdlib only. It only reads; it never writes into the site.

    python3 check_site.py [--repo R] [--json] [--report]            build R at HEAD, then check it
    python3 check_site.py [--repo R] --out DIR [--json] [--report]  check an existing build in DIR
    python3 check_site.py --scan-source PATH [PATH ...] [--json]    shape scan of a SOURCE tree

R supplies site/site.json (the config) and, for the resume PDF, its sidecar. The default mode builds
with build.publish_build into a temp dir: the gate checks what would be PUBLISHED.

THE FAMILIES (design 4.3). A finding names its family. There is NO command-line way to skip, waive
or ignore a family or a finding: a false positive is fixed in the module that holds the family, with a
dated note in that module's docstring. The code is the package `sitechecks/`; its docstrings carry what
each family checks and every dated note:
  report.py         the families, a finding, the report, the two printed forms; coverage
  structure.py      structure, comments
  linking.py        links, reachable (the OFL.txt and one-piece-listing notes)
  domain.py         domain
  contentchecks.py  media, unfinished
  budgets.py        performance, size
  pagemeta.py       head, nav, basepath
  privacy.py        privacy (design 7.1)
  sourcescan.py     --scan-source (design 8.2) and its allow-list
  shapes.py         the phone, address and email shapes

EXIT CODES: 0 no findings; 1 one or more findings; 2 usage or an unreadable config. NOT READ PDFs
alone exit 0 (see privacy.py). --json prints one JSON object per line: each finding ({"level":"error",
"family","path","message"}), each NOT READ PDF ({"level":"not-read",...}), with --report each external
link ({"level":"report","kind":"external-link","url","pages"}), then one {"level":"summary",...}.
"""
import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from configschema import diagnostics, model  # noqa: E402
import platform_check  # noqa: E402
from sitechecks.checker import check_tree  # noqa: E402
from sitechecks.report import render_json, render_text  # noqa: E402
from sitechecks.sourcescan import scan_source  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(prog="check_site.py", allow_abbrev=False, add_help=True,
                                 description="Check a built site. There is no way to skip a family.")
    ap.add_argument("--repo", default=".", help="the dev repo (site/site.json lives here)")
    ap.add_argument("--out", default=None, help="check this existing build instead of building HEAD")
    ap.add_argument("--json", action="store_true", help="one JSON record per line")
    ap.add_argument("--report", action="store_true", help="also list the external links")
    ap.add_argument("--scan-source", nargs="+", default=None, metavar="PATH",
                    help="shape-scan a SOURCE tree (phones, addresses, emails, EXIF GPS) and exit")
    return ap


def main(argv=None):
    rc = platform_check.windows_refusal_rc("check_site.py")
    if rc is not None:
        return rc
    args = build_parser().parse_args(argv)
    if args.scan_source is not None:
        rep = scan_source(args.scan_source)
        print(render_json(rep, False) if args.json else render_text(rep, False, "check_site --scan-source"))
        return 1 if rep.findings else 0
    repo = os.path.abspath(args.repo)
    cfg_path = os.path.join(repo, "site", "site.json")
    try:
        cfg = model.load(cfg_path)
    except (diagnostics.SiteConfigError, OSError) as e:
        print("check_site: cannot read %s: %s" % (cfg_path, e))
        return 2
    tmp = None
    out = args.out
    if out is None:
        from building import outcomes, running
        tmp = tempfile.mkdtemp(prefix="ss-check-")
        out = os.path.join(tmp, "dist")
        try:
            running.publish_build(repo, out)
        except outcomes.BuildError as e:
            print("build refused: %s" % e)
            return 1
    try:
        rep = check_tree(out, cfg, repo)
    finally:
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
    print(render_json(rep, args.report) if args.json else render_text(rep, args.report, "check_site"))
    return 1 if rep.findings else 0


if __name__ == "__main__":
    sys.exit(main())
