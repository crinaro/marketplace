#!/usr/bin/env python3
#!/usr/bin/env python3
"""adopt.py -- convert a dev repo that carries its own copy of this plugin's tools (dev #835,
design 6.4; named changes S2, S8, S9, S10 (round 1), M9, M13). Python 3.9, standard library only.

    adopt.py [--repo R] check
    adopt.py [--repo R] inventory [--json]
    adopt.py [--repo R] confirm PATH [--keep] [--as CAPABILITY]
    adopt.py [--repo R] unit PATH UNIT_ID {person-data|keep|rule} [--kind context|voice|rule] [--name SLUG]
    adopt.py [--repo R] fact PATH --kind context|voice|rule --text TEXT [--name SLUG]
    adopt.py [--repo R] reviewed PATH
    adopt.py [--repo R] paper {Letter|A4}
    adopt.py [--repo R] folder NAME {source|portfolio} | --clear
    adopt.py [--repo R] convert {redirectBoiler|resumeFields} [--keep]
    adopt.py [--repo R] kind {portfolio|hub|custom}
    adopt.py [--repo R] setting NAME VALUE | --clear
    adopt.py [--repo R] parity [--accept] [--keep DIR]
    adopt.py [--repo R] remeasure [--accept]
    adopt.py [--repo R] apply [--date YYYY-MM-DD] [--dry-run]

WHAT IT IS FOR. The person's dev repo may hold local copies of what the plugin now does (agents,
commands, scripts, a builder). A project agent with the same name outranks a plugin agent, and a
similar one under another name competes for routing, so the copies must go -- but the person's own
content, decisions and facts must not. `inventory` classifies each local file by WHAT IT DOES
(`spec/capabilities.json`: signals, weights, thresholds), `apply` runs the whole adoption in ONE
process (owner rulings 26 and 27) and ends COMPLETED or BLOCKED, never in between:
  1 check, conversions, file accounting and parity;   2 the publish preconditions (`deploy.py --preflight`);
  3 site-studio's publish through `deploy.py` (it asks the person first: `publish_guard.py` treats `apply` as a publish);
  4 wait for Pages to report that publish built;      5 archive the old builder, verify, commit, push to the dev repo's main.
A run that stops leaves the dev repo's main unchanged and the old builder as the publisher; the conversion is on the branch
`site-studio/adopt-<date>`, made with git plumbing, so the person's own checkout, index and branch never move. `apply --dry-run`
writes, publishes and pushes nothing.

THE PUBLIC REPO IS TOUCHED ONLY BY STEP 3, AND ONLY THROUGH `deploy.py`. `adopt.py` never imports it (an entry point): `apply` runs
it as a subprocess (`adoption/publish.py`). Steps 1 and 2 read the public repo (one clone, `gh` GETs) and write nothing to it.

EXIT CODES (every verb). 0 done: `apply` COMPLETED (its first line says `adopt completed`), or a dry run, or any other verb that did
what was asked. 1 refused: the line says what to do. 2 usage, or `report` found a report it would not file. 3 needs an
answer (`NeedsAnswer`: a decision only the person can make). 4 `apply` BLOCKED: the run ended at a step and the old builder is
still the publisher (its first line says `adopt blocked at step N of 5`, and from step 3 on a `cause:` line names the stop's
cause id, `ss-adopt/apply/<stop>` or `ss-adopt/env/...`, `report_issue.py`). A caller tells a completed apply from a blocked one
by the code alone; the first line says why.

THE MODULES. This file is the entry point: the argument grammar, one dispatch, printing and the exit code. The
logic is in the `adoption` package next to it (`adoption/<module>.py`; each module's docstring carries the part of
this file's former documentation that is about its code):
base (shared constants, exceptions, git) - spec - units - classify - tree - tokens - redirects - convert -
features - parity - problems - measure - plan - apply (steps 1 and 2) - finish and publish (steps 3 to 5) - report -
verbs (one function per verb but `apply`, loaded when a verb runs, never for `--help`).
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import platform_check  # noqa: E402
from configschema import configkeys  # noqa: E402
from adoption.base import FACT_KINDS, FOLDER_CHOICES, UNIT_DISPOSITIONS, NeedsAnswer, PlanError, Refused  # noqa: E402
from adoption.spec import OPT_IN_CLASSES  # noqa: E402


EXIT_APPLY_BLOCKED = 4           # `apply` ended blocked (never 3: that is NeedsAnswer, a question to the person)


def _build_parser():
    """The argument grammar: every verb and its flags (what `--help` prints comes from here)."""
    ap = argparse.ArgumentParser(prog="adopt.py", allow_abbrev=False)
    ap.add_argument("--repo", default=os.getcwd())
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check")
    s = sub.add_parser("inventory")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("confirm")
    s.add_argument("path")
    s.add_argument("--keep", action="store_true")
    s.add_argument("--as", dest="as_cap")
    s = sub.add_parser("unit")
    s.add_argument("path")
    s.add_argument("unit_id")
    s.add_argument("disposition", choices=UNIT_DISPOSITIONS)
    s.add_argument("--kind", choices=FACT_KINDS)
    s.add_argument("--name")
    s = sub.add_parser("fact")
    s.add_argument("path")
    s.add_argument("--kind", choices=FACT_KINDS, required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--name")
    s = sub.add_parser("reviewed")
    s.add_argument("path")
    s = sub.add_parser("paper")
    s.add_argument("size", choices=("Letter", "A4"))
    s = sub.add_parser("folder")
    s.add_argument("name")
    s.add_argument("choice", choices=FOLDER_CHOICES, nargs="?")
    s.add_argument("--clear", action="store_true", help="forget the decision about this folder: the next parity measures it again")
    s = sub.add_parser("convert")
    s.add_argument("conversion", choices=OPT_IN_CLASSES)
    s.add_argument("--keep", action="store_true")
    s = sub.add_parser("kind")
    s.add_argument("site_kind", choices=configkeys.SITE_KINDS)
    s = sub.add_parser("parity")
    s.add_argument("--accept", action="store_true")
    s.add_argument("--keep", metavar="DIR")
    s = sub.add_parser("report", allow_abbrev=False)    # the guard reads `--f` to `--file`: no abbreviation may mean another flag
    s.add_argument("--file", action="store_true", help="file the pending reports on the tracker (a publish: the guard asks)")
    s.add_argument("--decline", action="store_true", help="record every pending cause as declined")
    s = sub.add_parser("file", allow_abbrev=False)
    s.add_argument("path")
    s.add_argument("disposition", choices=("archive", "draft", "keep", "engine"))
    s = sub.add_parser("setting", allow_abbrev=False)
    s.add_argument("name", help="a measured setting: look, featuredFrom, sort.<portfolio>, nav.home, resume.headings, cardLabels, "
                                "cardNumber, backLink or view.<portfolio>")
    s.add_argument("value", nargs="?", help="what you choose for it (a chosen value is kept and never measured)")
    s.add_argument("--clear", action="store_true", help="forget the chosen value: the next parity measures it again")
    s = sub.add_parser("remeasure")
    s.add_argument("--accept", action="store_true")
    s = sub.add_parser("apply", allow_abbrev=False)     # the guard reads `--dry-run` literally: no abbreviation may mean it
    s.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    s.add_argument("--dry-run", action="store_true")
    return ap


def main(argv=None, hooks=None):
    """`hooks` is the tests' seam for `apply` (`deploy`, `gh`, `dev_slug`: adoption/publish.py); the command line has none."""
    rc = platform_check.windows_refusal_rc("adopt.py")
    if rc is not None:
        return rc
    ap = _build_parser()
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        if args.cmd is None:
            ap.print_usage()
            return 2
        if args.cmd == "apply":
            from adoption.apply import do_apply
            text, _tip, outcome = do_apply(repo, args.date, args.dry_run, hooks)
            print(text)
            if outcome == "blocked":
                return EXIT_APPLY_BLOCKED
        else:
            from adoption import verbs
            rc = verbs.VERBS[args.cmd](repo, args)
            if rc is not None:
                return rc
    except NeedsAnswer as e:
        print("adopt needs an answer: %s" % e)
        return 3
    except Refused as e:
        print("adopt refused: %s" % e)
        return 1
    except PlanError as e:
        print("adopt refused: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
