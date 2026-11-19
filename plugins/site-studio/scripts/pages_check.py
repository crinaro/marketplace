#!/usr/bin/env python3
"""pages_check.py -- the report-only check of the public repo's GitHub Pages configuration, of the
protection on its `main`, and of who else can write to it (dev #835, design amendment 1 sections A2,
A3.4, A4.3; owner ruling items 1 and 2 and guard (c); named changes AM6 to AM11, AS4).
Python 3.9, standard library only.

    python3 pages_check.py [--repo DIR] [--json [--raw]]

It READS. It never writes, never turns anything on, never fixes anything: it tells the person, in plain
words, what still needs resolving and WHO resolves it. DNS records and the TXT domain verification stay
with the person (the ruling); the plugin checks them and names them.

EXIT CODES (OURS, following deploy.py):
  0  every item was checked and needs nothing (info and ok lines do not change this)
  3  amber: something to resolve, GitHub is still working, or something is NOT CHECKED
  1  the check could not run: no `gh` or logged out, site.json unreadable, no `publicRepo` (AM9: one
     line, "site.json has no publicRepo ..."), or `GET repos/<o>/<r>` failed
NOT CHECKED is never a pass: it is amber, and the line says why.

The code is the package `pagesaudit/`; each module's docstring carries what it reads and says:
  ghget.py       the ONE process start, `gh api` GET only (READ-ONLY BY CONSTRUCTION, AM10), and the order of reads
  pagesitems.py  Pages source, domain, DNS health, certificate; STATE PRECEDENCE (AM11)
  protection.py  protection on `main`, writers (guard c)
  reporting.py   counts, exit code, summary line, the --json object
  keys.py        the documented key set (AM7)
  values.py      Resp, Item, the errors, exit codes, states
  runcheck.py    `check`
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import platform_check  # noqa: E402
from configschema import diagnostics, model  # noqa: E402
from pagesaudit.ghget import _get  # noqa: E402
from pagesaudit.reporting import as_json, exit_code, summary_line  # noqa: E402
from pagesaudit.runcheck import check  # noqa: E402
from pagesaudit.values import EXIT_RED, LABEL, PagesCheckError  # noqa: E402


def main(argv=None):
    rc = platform_check.windows_refusal_rc("pages_check.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="pages_check.py", allow_abbrev=False,
                                 description="Report the public repo's Pages configuration (read-only).")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    ap.add_argument("--raw", action="store_true", help="with --json: include every raw GitHub response")
    args = ap.parse_args(argv)
    if args.raw and not args.json:
        ap.error("--raw needs --json")
    public_repo = None
    raw = {} if args.raw else None

    def fail(msg):
        if args.json:
            print(json.dumps(as_json(public_repo, [], error=msg), indent=2))
        else:
            print(msg)
        return EXIT_RED

    try:
        cfg = model.load(os.path.join(args.repo, "site", "site.json"))
    except diagnostics.SiteConfigError as e:
        return fail("NOT CHECKED: %s" % e)
    public_repo = cfg.publicRepo

    def recording_get(path, paginate=False):
        r = _get(path, paginate)
        if raw is not None:
            raw[path] = {"status": r.status, "data": r.data}
        return r

    try:
        items = check(public_repo, cfg, get=recording_get)
    except PagesCheckError as e:
        return fail(str(e) if str(e).startswith("site.json") else "NOT CHECKED: %s" % e)
    if args.json:
        print(json.dumps(as_json(public_repo, items, raw), indent=2))
    else:
        for it in items:
            if it.state == "ok":
                continue
            print("[%s] %s%s" % (LABEL[it.state], it.line, " (Who: %s)" % it.who if it.who else ""))
        print(summary_line(public_repo, items))
    return exit_code(items)


if __name__ == "__main__":
    sys.exit(main())
