"""adoption.verbs -- what each `adopt.py` verb does, one function per verb (the dispatch of `adopt.py` calls them).

Part of the `adoption` package behind the entry point `adopt.py`. The branches of the old `adopt.main` cut into functions: each
takes `(repo, args)`, prints what the verb prints, raises `Refused`, `NeedsAnswer` or `PlanError` for the entry point to turn into
an exit code, and returns an exit code only where the verb has its own (`check` 1, `report` any) and None otherwise.
`apply` is not here: its exit code 4 is the entry point's own constant. `VERBS` maps a verb's name to its function.
"""

from contentmodel import keytables  # noqa: E402

from adoption.accounting import cmd_file
from adoption.base import Refused
from adoption.measure import cmd_parity, cmd_remeasure
from adoption.parity import preconditions
from adoption.plan import _current_base, _plan_for, _set, save_plan
from adoption.problems import analyse_problems, format_problems, held_problems, site_problems, size_copy_note
from adoption.report import _conversion_block, cmd_inventory
from adoption.reports import cmd_report
from adoption.settings import cmd_setting
from adoption.spec import load_spec


def verb_check(repo, args):
    """`adopt.py check`: can the repo be converted, and what stands in the way."""
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


def verb_inventory(repo, args):
    """`adopt.py inventory`: classify every local file by what it does and write the plan."""
    print(cmd_inventory(repo, args.json))


def verb_confirm(repo, args):
    """`adopt.py confirm PATH [--keep] [--as CAPABILITY]`: the decision to remove (or keep) one file."""
    def fn(plan, e, tree):
        e["removal"] = "keep" if args.keep else "confirm"
        if args.as_cap:
            if args.as_cap not in load_spec().caps:
                raise Refused("unknown capability %s; pass one of %s to --as"
                              % (args.as_cap, ", ".join(sorted(load_spec().caps))))
            e["as"] = args.as_cap
    _set(repo, args.path, fn)
    print("adopt: %s -> %s" % (args.path, "keep" if args.keep else "remove (after apply)"))


def verb_unit(repo, args):
    """`adopt.py unit PATH UNIT_ID DISPOSITION`: what becomes of one residual unit of a file."""
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


def verb_fact(repo, args):
    """`adopt.py fact PATH --kind K --text T`: record a fact of the person's own."""
    def fn(plan, e, tree):
        fa = {"source": args.path, "kind": args.kind, "text": args.text}
        if args.name:
            fa["name"] = args.name
        plan["facts"].append(fa)
    _set(repo, args.path, fn)
    print("adopt: recorded a %s fact from %s" % (args.kind, args.path))


def verb_reviewed(repo, args):
    """`adopt.py reviewed PATH`: the facts in a file are read and recorded."""
    def fn(plan, e, tree):
        e["reviewed"] = True
    _set(repo, args.path, fn)
    print("adopt: facts in %s marked reviewed" % args.path)


def verb_paper(repo, args):
    """`adopt.py paper {Letter|A4}`: the resume's paper size."""
    plan = _plan_for(repo, _current_base(repo), print)
    plan["paper"] = args.size
    save_plan(repo, plan)
    print("adopt: resume.paper will be %s" % args.size)


def verb_folder(repo, args):
    """`adopt.py folder NAME {source|portfolio}`: what a content folder is."""
    name = args.name.strip("/")
    if name.startswith("content/"):
        name = name[len("content/"):]
    if not name or "/" in name:
        raise Refused("name one folder directly under content/, for example `adopt.py folder news "
                      "portfolio`")
    if name in keytables.RESERVED_PORTFOLIO_NAMES:
        raise Refused("content/%s is a reserved name (the build reads it as a page or as shared files, "
                      "never as a portfolio), so adopt never moves it and there is no decision to make "
                      "about it; choose a different folder name if you meant a new portfolio" % name)
    plan = _plan_for(repo, _current_base(repo), print)
    plan["folders"][name] = args.choice
    save_plan(repo, plan)
    print("adopt: content/%s -> %s" % (name, "renamed to content/_%s (source material)" % name
                                        if args.choice == "source" else "gets a page.md and is a portfolio"))


def verb_convert(repo, args):
    """`adopt.py convert CLASS [--keep]`: choose an opt-in conversion, or leave it as written."""
    plan = _plan_for(repo, _current_base(repo), print)
    if args.keep:
        plan["convert"] = [c for c in plan["convert"] if c != args.conversion]
    elif args.conversion not in plan["convert"]:
        plan["convert"].append(args.conversion)
    save_plan(repo, plan)
    print("adopt: %s will %s" % (args.conversion, "stay as written" if args.keep else
                                 "be converted (it changes what a visitor loads or reads: parity names "
                                 "the page that differs)"))


def verb_kind(repo, args):
    """`adopt.py kind {portfolio|hub|custom}`: the site kind."""
    plan = _plan_for(repo, _current_base(repo), print)
    plan["siteKind"] = args.site_kind
    save_plan(repo, plan)
    print("adopt: the site kind is %s%s" % (args.site_kind, " (the default; site.json will not carry it)"
                                            if args.site_kind == "portfolio" else
                                            " (apply writes siteKind: %s, schema 2)" % args.site_kind))


def verb_parity(repo, args):
    """`adopt.py parity [--accept] [--keep DIR]`: build both ways and compare."""
    cmd_parity(repo, args.accept, args.keep)


def verb_report(repo, args):
    """`adopt.py report [--file] [--decline]`: the pending cause reports. Returns the exit code."""
    return cmd_report(repo, args.file, args.decline)


def verb_file(repo, args):
    """`adopt.py file PATH DISPOSITION`: the file accounting decision for one file."""
    print(cmd_file(repo, args.path, args.disposition))


def verb_setting(repo, args):
    """`adopt.py setting NAME VALUE | --clear`: a chosen setting."""
    if args.clear == (args.value is not None):
        raise Refused("name the value (`adopt.py setting cardNumber true`), or `--clear` to forget a chosen one")
    print(cmd_setting(repo, args.name, args.value, args.clear))


def verb_remeasure(repo, args):
    """`adopt.py remeasure [--accept]`: measure parity again on the moved basis."""
    print(cmd_remeasure(repo, args.accept))


VERBS = {
    "check": verb_check,
    "inventory": verb_inventory,
    "confirm": verb_confirm,
    "unit": verb_unit,
    "fact": verb_fact,
    "reviewed": verb_reviewed,
    "paper": verb_paper,
    "folder": verb_folder,
    "convert": verb_convert,
    "kind": verb_kind,
    "parity": verb_parity,
    "report": verb_report,
    "file": verb_file,
    "setting": verb_setting,
    "remeasure": verb_remeasure,
}
