#!/usr/bin/env python3
"""The LinkedIn search pass's two page scripts and what they return, read by a script and never by the agent (jobsearch 0.94.0, dev 1064, 1065; docs/design-role-first.md 7, 19.3, 19.6).

  search_page.py links --run <id> --n <plan n> --match <roles file> --result '<json>' [--tool-error]
      The `LINKS_JS` result of one results page set against the ROLE lines of the roles file: prints the `LINKS ...` line the ROLES block carries, then `ID <k> <id> <url>` for each role that gets an id
      (exactly one card holds its title AND its company) and `NOURL <k>` for each that does not (`k`: the 1-based position among the file's ROLE lines). `--tool-error` says the tool call itself
      failed. `browser_fallback/link_read.py` holds the rules; `journaling/search_links.py` holds the owner's limits (a page `search-warning` judged ordinary, its links taken once, at most 25 ids a
      search and 500 a pass, counted in the journal): `LINKS REFUSED reason=<word>` (exit 3) takes no id, `STOP ...` (exit 3) means the run ended, `LIMIT links kept=<k> of <m>` says ids were cut.
  search_page.py address --sent '<query>' --settled '<query>'
      N14: prints `ADDRESS dropped=<none|a,b> added=<none|a,b>[ unapplied]`, the slots of this search's QUERY line: a location or filter the pass sent that the page's settled address lacks. When the
      settled address names other `keywords` than the pass sent, or another `start` than its first page, it prints `ADDRESS REFUSED reason=other-search|not-first-page ...` and exits 3: a stale or
      reused tab, or another page of results; take nothing from it.
  search_page.py print links|warning|warning-posting|warning-reply
      The shipped constant verbatim: `warning` is the results page's, `warning-posting` a LinkedIn posting page's (`agents/jd-reader.md` takes its copy from here, once a dispatch) and `warning-reply`
      a reply-pass page's. The runner fences each of the first, third and fourth byte-equal (`<!-- page-warning:begin -->`, `-posting`, `-reply`) and a test holds the fence to this output.

The page-warning verdict is NOT here: `linkedin_sweep.py search-warning` judges the results script's result and records what a warning ends; `linkedin_sweep.py page-warning --kind posting|reply` judges the other two.

Python 3.9+. Standard library only."""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_fallback import link_read, page_warning  # noqa: E402


def _roles_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        print("search_page.py: cannot read the roles file %s: %s" % (path, e), file=sys.stderr)
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ln = sub.add_parser("links", help="match a LINKS_JS result to the roles file, within the owner's limits")
    ln.add_argument("--run", required=True, help="the journal run id of the search")
    ln.add_argument("--n", type=int, required=True, help="the plan entry (SEARCH n=) whose results page this is")
    ln.add_argument("--match", required=True, metavar="ROLES_FILE", help="the file holding the pass's ROLE lines")
    ln.add_argument("--result", default="", help="the javascript_tool result of LINKS_JS (JSON, or its error text with --tool-error)")
    ln.add_argument("--tool-error", action="store_true", help="the javascript_tool call itself failed")
    ad = sub.add_parser("address", help="what the settled address dropped or added (N14), or another search's page")
    ad.add_argument("--sent", required=True, help="the query string the pass sent")
    ad.add_argument("--settled", required=True, help="the query string of the page's settled address")
    pr = sub.add_parser("print", help="emit a shipped constant verbatim")
    pr.add_argument("which", choices=("links", "warning", "warning-posting", "warning-reply"))
    args = ap.parse_args(argv)
    if args.cmd == "links":
        text = _roles_text(args.match)
        if text is None:
            return 2
        # The gate reads and writes the journal, and an entry point imports neither another entry point (G5.L2) nor `journaling` (a second importer of it grows the plugin's largest cycle,
        # G6, measured), so the call is `linkedin_sweep.py search-links`, which owns that import; its output and exit code are this command's.
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_sweep.py"), "search-links", "--run", args.run, "--n", str(args.n),
               "--match", args.match, "--result", args.result] + (["--tool-error"] if args.tool_error else [])
        sys.stdout.flush()
        return subprocess.call(cmd)
    elif args.cmd == "address":
        line = link_read.address_line(args.sent, args.settled)
        print(line)
        return 3 if line.startswith("ADDRESS REFUSED") else 0
    else:
        print(link_read.LINKS_JS if args.which == "links" else page_warning.script({"warning": "results", "warning-posting": "posting", "warning-reply": "reply"}[args.which]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
