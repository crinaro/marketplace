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
    adopt.py [--repo R] folder NAME {source|portfolio}
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
features - parity - problems - measure - plan - apply (steps 1 and 2) - finish and publish (steps 3 to 5) - report.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import platform_check  # noqa: E402
import siteconfig  # noqa: E402
import content as site_content  # noqa: E402
from adoption.base import FACT_KINDS, FOLDER_CHOICES, UNIT_DISPOSITIONS, NeedsAnswer, PlanError, Refused  # noqa: E402
from adoption.spec import OPT_IN_CLASSES  # noqa: E402


EXIT_APPLY_BLOCKED = 4           # `apply` ended blocked (never 3: that is NeedsAnswer, a question to the person)


def main(argv=None, hooks=None):
    """`hooks` is the tests' seam for `apply` (`deploy`, `gh`, `dev_slug`: adoption/publish.py); the command line has none."""
    rc = platform_check.windows_refusal_rc("adopt.py")
    if rc is not None:
        return rc
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
    s.add_argument("choice", choices=FOLDER_CHOICES)
    s = sub.add_parser("convert")
    s.add_argument("conversion", choices=OPT_IN_CLASSES)
    s.add_argument("--keep", action="store_true")
    s = sub.add_parser("kind")
    s.add_argument("site_kind", choices=siteconfig.SITE_KINDS)
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
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    try:
        if args.cmd == "check":
            from adoption.parity import preconditions
            from adoption.plan import _plan_for
            from adoption.problems import analyse_problems, format_problems, held_problems, site_problems, size_copy_note
            from adoption.report import _conversion_block
            basis, tree, data = preconditions(repo)
            for line in basis.up_front():
                print(line)
            plan = _plan_for(repo, basis.sha, print)
            probs = site_problems(tree, data, None, plan.get("siteKind"), plan["folders"], plan["convert"]) + held_problems(tree, data, plan)
            for line in format_problems(probs):
                print(line)
            blocked = [p for p in probs if not p.mechanical]
            if blocked:
                n = analyse_problems(probs)["decisions"]
                print("adopt check: %s %s cannot be converted until the %d %s marked "
                      "`you decide` are settled%s" % (basis.label(), basis.sha[:7], n,
                                                      "problem(s)" if n == len(blocked) else "cause(s)",
                                                      "" if n == len(blocked) else
                                                      " (%d problem(s) in all; the rest follow from them or share their cause)"
                                                      % len(blocked)))
                for line in _conversion_block(tree, data, plan):
                    print(line)
                if size_copy_note(tree):
                    print(size_copy_note(tree))
                return 1
            print("adopt ok: %s %s can be converted" % (basis.label(), basis.sha[:7]))
            for line in _conversion_block(tree, data, plan):
                print(line)
            if size_copy_note(tree):
                print(size_copy_note(tree))
        elif args.cmd == "inventory":
            from adoption.report import cmd_inventory
            print(cmd_inventory(repo, args.json))
        elif args.cmd == "confirm":
            from adoption.plan import _set
            from adoption.spec import load_spec
            def fn(plan, e, tree):
                e["removal"] = "keep" if args.keep else "confirm"
                if args.as_cap:
                    if args.as_cap not in load_spec().caps:
                        raise Refused("unknown capability %s; pass one of %s to --as"
                                      % (args.as_cap, ", ".join(sorted(load_spec().caps))))
                    e["as"] = args.as_cap
            _set(repo, args.path, fn)
            print("adopt: %s -> %s" % (args.path, "keep" if args.keep else "remove (after apply)"))
        elif args.cmd == "unit":
            from adoption.plan import _set
            def fn(plan, e, tree):
                if args.disposition == "person-data" and not args.kind:
                    raise Refused("--kind context|voice|rule is required for person data")
                u = {"disposition": args.disposition}
                if args.disposition == "person-data":
                    u["kind"] = args.kind
                    if args.name:
                        u["name"] = args.name
                e.setdefault("units", {})[args.unit_id] = u
            _set(repo, args.path, fn)
            print("adopt: %s %s -> %s" % (args.path, args.unit_id, args.disposition))
        elif args.cmd == "fact":
            from adoption.plan import _set
            def fn(plan, e, tree):
                fa = {"source": args.path, "kind": args.kind, "text": args.text}
                if args.name:
                    fa["name"] = args.name
                plan["facts"].append(fa)
            _set(repo, args.path, fn)
            print("adopt: recorded a %s fact from %s" % (args.kind, args.path))
        elif args.cmd == "reviewed":
            from adoption.plan import _set
            def fn(plan, e, tree):
                e["reviewed"] = True
            _set(repo, args.path, fn)
            print("adopt: facts in %s marked reviewed" % args.path)
        elif args.cmd == "paper":
            from adoption.plan import _current_base, _plan_for, save_plan
            plan = _plan_for(repo, _current_base(repo), print)
            plan["paper"] = args.size
            save_plan(repo, plan)
            print("adopt: resume.paper will be %s" % args.size)
        elif args.cmd == "folder":
            from adoption.plan import _current_base, _plan_for, save_plan
            name = args.name.strip("/")
            if name.startswith("content/"):
                name = name[len("content/"):]
            if not name or "/" in name:
                raise Refused("name one folder directly under content/, for example `adopt.py folder news "
                              "portfolio`")
            if name in site_content.RESERVED_PORTFOLIO_NAMES:
                raise Refused("content/%s is a reserved name (the build reads it as a page or as shared files, "
                              "never as a portfolio), so adopt never moves it and there is no decision to make "
                              "about it; choose a different folder name if you meant a new portfolio" % name)
            plan = _plan_for(repo, _current_base(repo), print)
            plan["folders"][name] = args.choice
            save_plan(repo, plan)
            print("adopt: content/%s -> %s" % (name, "renamed to content/_%s (source material)" % name
                                                if args.choice == "source" else "gets a page.md and is a portfolio"))
        elif args.cmd == "convert":
            from adoption.plan import _current_base, _plan_for, save_plan
            plan = _plan_for(repo, _current_base(repo), print)
            if args.keep:
                plan["convert"] = [c for c in plan["convert"] if c != args.conversion]
            elif args.conversion not in plan["convert"]:
                plan["convert"].append(args.conversion)
            save_plan(repo, plan)
            print("adopt: %s will %s" % (args.conversion, "stay as written" if args.keep else
                                         "be converted (it changes what a visitor loads or reads: parity names "
                                         "the page that differs)"))
        elif args.cmd == "kind":
            from adoption.plan import _current_base, _plan_for, save_plan
            plan = _plan_for(repo, _current_base(repo), print)
            plan["siteKind"] = args.site_kind
            save_plan(repo, plan)
            print("adopt: the site kind is %s%s" % (args.site_kind, " (the default; site.json will not carry it)"
                                                    if args.site_kind == "portfolio" else
                                                    " (apply writes siteKind: %s, schema 2)" % args.site_kind))
        elif args.cmd == "parity":
            from adoption.measure import cmd_parity
            cmd_parity(repo, args.accept, args.keep)
        elif args.cmd == "report":
            from adoption.reports import cmd_report
            return cmd_report(repo, args.file, args.decline)
        elif args.cmd == "file":
            from adoption.accounting import cmd_file
            print(cmd_file(repo, args.path, args.disposition))
        elif args.cmd == "setting":
            from adoption.settings import cmd_setting
            if args.clear == (args.value is not None):
                raise Refused("name the value (`adopt.py setting cardNumber true`), or `--clear` to forget a chosen one")
            print(cmd_setting(repo, args.name, args.value, args.clear))
        elif args.cmd == "remeasure":
            from adoption.measure import cmd_remeasure
            print(cmd_remeasure(repo, args.accept))
        elif args.cmd == "apply":
            from adoption.apply import do_apply
            text, _tip, outcome = do_apply(repo, args.date, args.dry_run, hooks)
            print(text)
            if outcome == "blocked":
                return EXIT_APPLY_BLOCKED
        else:
            ap.print_usage()
            return 2
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
