"""adoption.verbs -- what each `adopt.py` verb does, one function per verb (the dispatch of `adopt.py` calls them).

Part of the `adoption` package behind the entry point `adopt.py`. The branches of the old `adopt.main` cut into functions: each
takes `(repo, args)`, prints what the verb prints, raises `Refused`, `NeedsAnswer` or `PlanError` for the entry point to turn into
an exit code, and returns an exit code only where the verb has its own (`check` 1, `report` any) and None otherwise.
`apply` is not here: its exit code 4 is the entry point's own constant. `VERBS` maps a verb's name to its function.
"""

import json
import os
import shutil
import tempfile

from configschema import model  # noqa: E402
from contentmodel import keytables  # noqa: E402

from adoption import applyrefusals, publishchecks, publishfixes, resumeproof, shots, wouldwrite
from adoption.accounting import cmd_file, no_landing_lines, no_landing_rows, open_folders, said_before_apply, stale_line, undisposed_rows
from adoption.blockers import is_stray_warning
from adoption.classify import classify_text, file_kind, shadow_names
from adoption.units import first_line
from adoption.fileacct import measured_folders
from adoption.keycover import note_lines
from adoption.base import NeedsAnswer, PlanError, Refused, git, gitt
from adoption.measure import cmd_parity, cmd_remeasure
from adoption.parity import current_parity, example_site_json, preconditions
from adoption.tokens import detect_resume
from adoption.tree import Tree
from adoption.plan import _current_base, _plan_for, _set, save_plan
from adoption.problems import plan_settings, analyse_problems, format_problems, held_problems, look_lines, site_problems, size_copy_note
from adoption.report import _conversion_block, cmd_inventory
from adoption.review_cover import run_tool
from adoption.reports import cmd_report
from adoption.settings import cmd_setting
from adoption import suggestions
from adoption.suggest import cmd_suggest
from adoption.spec import load_spec


def _measured(plan):
    """(dispositions, persons, hints): what the last `parity` measured and the person decided, which `apply` converts by."""
    meas = current_parity(plan.get("parity")) or {}
    persons = dict((p, e["disposition"]) for p, e in plan["files"].items() if e.get("disposition"))
    return ((meas.get("accounting") or {}).get("dispositions") or None), persons, (meas.get("hints") or None)


def _publish_lines(repo, tree, data, plan, args, ask_online=False):
    """(Result, lines): the publish checks over the one converted tree (`publishchecks.for_plan`), as `check` prints them. Before a `parity`
    the list is for the plugin's default look and changes no exit code (design 1.1)."""
    res, notes = publishchecks.for_plan(repo, tree, data, plan, ask_online=ask_online)
    lines = ["note: %s" % n for n in notes]
    lines += publishchecks.block_lines(res, before_parity=current_parity(plan.get("parity")) is None, show_all=getattr(args, "all", False))
    return res, lines


def verb_check(repo, args):
    """`adopt.py check [--online] [--all]`: can the repo be converted, what stands in the way, what the publish would refuse, and what `apply` itself would
    refuse (`applyrefusals`: exit 1, before a `parity` too)."""
    basis, tree, data = preconditions(repo)
    for line in basis.up_front():
        print(line)
    plan = _plan_for(repo, basis.sha, print)
    notes = []                                                # design-movement-view 6.1: a note, not a decision
    dispositions, persons, hints = _measured(plan)
    # the layout is judged with the folders `parity` measured as archived (F2); the build is asked about the tree as `apply` converts it, whose folder
    # decisions are the person's own less those the archive satisfied (F1: `wouldwrite.conversion`)
    opened = open_folders(plan["folders"], tree.paths(), dispositions) if dispositions else None
    probs = (site_problems(tree, data, None, plan.get("siteKind"), measured_folders(tree, plan), plan["convert"], plan_settings(plan),
                           plan.get("parity"), notes, dispositions, persons, hints, opened)
             + held_problems(tree, data, plan))               # F2: a folder the last `parity` archived wholly is no question
    if dispositions:                                          # a stray file is disposed by the file accounting, never also a refusal (R4 row 16 (a))
        probs = [p for p in probs if not is_stray_warning(p)]
    look = ["note: %s" % l for l in look_lines(tree, data, ((plan.get("settings") or {}).get("look") or {}).get("value"))]   # P5, P6
    for line in format_problems(probs) + note_lines(notes) + look:
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
        _say(said_before_apply(plan))                  # 4.6: the files that will block apply, and the choices parity has not measured
        return 1
    res, lines = _publish_lines(repo, tree, data, plan, args, ask_online=getattr(args, "online", False))
    after = current_parity(plan.get("parity")) is not None
    refused = after and res.blocks
    decide, stops = applyrefusals.collect(repo, data, plan)                  # dev 1068, review R1 item 2: what `apply` itself would refuse, asked of the same functions
    decide = [d for d in decide if d != res.pending]                         # a decision `check` already named as a note is not named twice
    if refused or stops:
        said = (["the publish would refuse it: %d finding(s)" % len(res.findings)] if refused else []) + (
            ["apply would refuse it: %d refusal(s)" % len(stops)] if stops else [])
        print("adopt check: %s %s can be converted, but %s" % (basis.label(), basis.sha[:7], ", and ".join(said)))
    else:
        print("adopt ok: %s %s can be converted" % (basis.label(), basis.sha[:7]))
    for line in _conversion_block(tree, data, plan):
        print(line)
    if size_copy_note(tree):
        print(size_copy_note(tree))
    _say(said_before_apply(plan))
    _say(lines)
    _say((["apply would refuse (each is a refusal `adopt.py apply` makes before it writes anything; `check` asks the same functions):"]
          + ["  - %s" % r for r in stops]) if stops else [])
    _say((["apply would stop until you decide:"] + ["  - %s" % d for d in decide]) if decide else [])
    if getattr(args, "online", False):
        _say(["note: %s" % n for n in publishchecks.environment_notes(repo)])
        _say(["can still stop apply (each one is answered only by the step that makes it):"] + publishfixes.stop_lines())
    return 1 if refused or stops else None


def _say(lines):
    for line in lines:
        print(line)


def verb_inventory(repo, args):
    """`adopt.py inventory`: classify every local file by what it does and write the plan."""
    out = cmd_inventory(repo, args.json)
    plan = _plan_for(repo, _current_base(repo))
    acct = ((plan.get("parity")) or {}).get("accounting")     # N1: what the last `parity` measured
    tree = Tree(repo, plan["base"])           # the basis `inventory` just wrote the plan for: no second fetch
    res, lines = _publish_lines(repo, tree, example_site_json(tree), plan, args)
    if args.json:
        d = json.loads(out)
        d["noLanding"] = [{"path": p, "why": w} for p, w in no_landing_rows(acct)]
        d["undisposed"] = [{"path": p, "why": w} for p, w in undisposed_rows(acct)]
        d["publish"] = publishchecks.to_json(res)           # every finding, never cut (dev 1068)
        out = json.dumps(d, indent=2, default=list)
    else:
        out += "".join("\n" + l for l in (no_landing_lines(acct) if no_landing_rows(acct) else []) + said_before_apply(plan) + lines)
    print(out)


def _classified(repo, path, entry):
    """The classification `apply` reads a file by (`wouldwrite.collect_removals`): the inventory's, and for an AMBIGUOUS file the one the person's `--as`
    names. Read at the plan's basis; raises Refused for a path adopt reads no units of (dev 1068, S6)."""
    tree = Tree(repo, _current_base(repo))
    kind = file_kind(path)
    if kind in (None, "mixed") or not tree.exists(path):
        raise Refused("%s is not a file adopt classifies (an agent, a command, a skill or a script); run `adopt.py inventory` to see them" % path)
    spec = load_spec()
    info = classify_text(spec, path, kind, tree.text(path), shadows=shadow_names())
    if info["class"] == "AMBIGUOUS" and entry.get("as"):
        info = classify_text(spec, path, kind, tree.text(path), as_cap=entry["as"])
    return info


def verb_confirm(repo, args):
    """`adopt.py confirm PATH [--keep | --covered] [--as CAPABILITY]`: the decision to remove (or keep) one file; `--covered` is the person's word
    that the plugin covers what a PARTIAL script adds, so it goes with the rest (its units are listed in the commit)."""
    covered = getattr(args, "covered", False)
    if covered:
        if args.keep:
            raise Refused("--covered and --keep are opposite answers for %s: give one" % args.path)
        plan = _plan_for(repo, _current_base(repo), print)
        if args.path not in plan["files"]:
            raise Refused("%s is not in the plan; run `adopt.py inventory` first" % args.path)
        info = _classified(repo, args.path, dict(plan["files"][args.path], **({"as": args.as_cap} if args.as_cap else {})))
        if info["kind"] != "code":
            raise Refused("%s has units to answer one by one: `adopt.py unit %s UNIT_ID covered`, or `adopt.py unit %s --rest covered` for the rest"
                          % (args.path, args.path, args.path))
        if info["class"] != "PARTIAL":
            raise Refused("%s is %s, not PARTIAL: only a PARTIAL script has behaviour nothing says is safe to drop, so only it needs `--covered`%s"
                          % (args.path, info["class"], "; `adopt.py confirm %s` removes a DUPLICATE" % args.path if info["class"] == "DUPLICATE" else ""))
        if info["needs_parity"]:
            raise Refused("%s is a local builder file: it is dropped only after parity says the site is the same (run `adopt.py parity`), never on your "
                          "word that the plugin covers it; `adopt.py confirm %s` then removes it" % (args.path, args.path))

    def fn(plan, e, tree):
        e["removal"] = "keep" if args.keep else "confirm"
        if covered:
            e["covered"] = True
        else:
            e.pop("covered", None)                  # a later plain `confirm` or `--keep` takes the answer back
        if args.as_cap:
            if args.as_cap not in load_spec().caps:
                raise Refused("unknown capability %s; pass one of %s to --as"
                              % (args.as_cap, ", ".join(sorted(load_spec().caps))))
            e["as"] = args.as_cap
    _set(repo, args.path, fn)
    print("adopt: %s -> %s" % (args.path, "keep" if args.keep else "remove (after apply)%s" % (
        "; the plugin covers its extra behaviour: every unit is listed in the commit as covered" if covered else "")))


def _unit_rest(repo, args):
    """`adopt.py unit PATH --rest covered`: every unit of the file with no answer yet is answered covered, each one's first line printed first."""
    plan = _plan_for(repo, _current_base(repo), print)
    e = plan["files"].get(args.path)
    if e is None:
        raise Refused("%s is not in the plan; run `adopt.py inventory` first" % args.path)
    left = [u for u in _classified(repo, args.path, e)["residual_units"] if u["id"] not in (e.get("units") or {})]
    if not left:
        raise Refused("%s has no unit without an answer (answered: %s); nothing to do: change one answer with `adopt.py unit %s <id> <disposition>`"
                      % (args.path, ", ".join(sorted(e.get("units") or {})) or "none", args.path))
    for u in left:                                          # said BEFORE it is stored: the person reads what is being dropped
        print("adopt: %s %s -> covered: %s" % (args.path, u["id"], first_line(u["text"])))
    for u in left:
        e.setdefault("units", {})[u["id"]] = {"disposition": "covered"}
    save_plan(repo, plan)
    print("adopt: %d unit(s) of %s covered by the plugin: dropped with the file, which is archived (apply lists each one in its commit)"
          % (len(left), args.path))


def verb_unit(repo, args):
    """`adopt.py unit PATH UNIT_ID DISPOSITION`: what becomes of one residual unit of a file (`PATH --rest covered`: of every one not answered yet)."""
    if getattr(args, "rest", False):
        return _unit_rest(repo, args)

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
    """`adopt.py folder NAME {source|portfolio}`: what a content folder is; `folder NAME --clear` forgets the decision (F3)."""
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
    if args.clear:                          # F3: forget the decision, as `setting --clear` and `convert --keep` do
        if args.choice:
            raise Refused("--clear forgets the decision about content/%s, so it takes no choice: `adopt.py folder %s --clear`"
                          % (name, name))
        if name not in plan["folders"]:
            raise Refused("content/%s has no decision to clear (decisions: %s); decide it with `adopt.py folder %s "
                          "source|portfolio`" % (name, ", ".join(sorted(plan["folders"])) or "none", name))
        del plan["folders"][name]
        save_plan(repo, plan)
        print("adopt: content/%s: your decision is forgotten; the next `parity` measures it again" % name)
        _say(filter(None, [stale_line(plan)]))
        return
    if not args.choice:
        raise Refused("say what content/%s is: `adopt.py folder %s source` or `portfolio`, or forget a decision with "
                      "`adopt.py folder %s --clear`" % (name, name, name))
    plan["folders"][name] = args.choice
    save_plan(repo, plan)
    print("adopt: content/%s -> %s" % (name, "renamed to content/_%s (source material)" % name
                                        if args.choice == "source" else "gets a page.md and is a portfolio"))
    _say(filter(None, [stale_line(plan)]))


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
    _say(filter(None, [stale_line(plan)]))


def verb_kind(repo, args):
    """`adopt.py kind {portfolio|hub|custom}`: the site kind."""
    plan = _plan_for(repo, _current_base(repo), print)
    plan["siteKind"] = args.site_kind
    save_plan(repo, plan)
    print("adopt: the site kind is %s%s" % (args.site_kind, " (the default; site.json will not carry it)"
                                            if args.site_kind == "portfolio" else
                                            " (apply writes siteKind: %s, schema 2)" % args.site_kind))
    _say(filter(None, [stale_line(plan)]))


def verb_parity(repo, args):
    """`adopt.py parity [--accept [--shots DIR/shots]] [--keep DIR]`: build both ways and compare. After the verdict it prints what `apply` itself would
    refuse, as `check` does (dev 1068, review round: one list in every stage; the JSON form carries `publish` only)."""
    rc = cmd_parity(repo, args.accept, args.keep, args.shots, as_json=getattr(args, "json", False))
    if not getattr(args, "json", False):
        _say(_apply_refusal_lines(repo))
    return rc


def _apply_refusal_lines(repo):
    """The `apply would refuse` block of `check`, for the plan as it stands now (after `parity` saved it); [] when apply would refuse nothing, and [] when the
    plan or the basis cannot be read again here: parity has already said what it measured, and `check` asks the same refusals and says why it cannot."""
    try:
        basis, _tree, data = preconditions(repo)
        plan = _plan_for(repo, basis.sha, lambda *_a, **_k: None)
    except (Refused, PlanError):
        return []
    _decide, stops = applyrefusals.collect(repo, data, plan)
    return (["apply would refuse (each is a refusal `adopt.py apply` makes before it writes anything; `check` asks the same functions):"]
            + ["  - %s" % r for r in stops]) if stops else []


def _one(ids, option):
    """The one id an option was given (section 13.5: one id per command, one ask, one issue)."""
    if len(ids) != 1:
        raise Refused("%s takes exactly one id; run the command once per suggestion" % option)
    return ids[0]


def verb_report(repo, args):
    """`adopt.py report [--file] [--decline]`: the pending cause reports; with `--suggestion ID`, one look suggestion (handled
    before the blocker record is read, so a repo that never held one still answers, U-G1). Returns the exit code."""
    if args.suggestion is not None:
        return suggestions.cmd_report_suggestion(repo, _one(args.suggestion, "--suggestion"), args.file, args.decline, args.digest)
    if args.digest is not None:
        raise Refused("--digest belongs to report --suggestion ID --file; blocker reports take none")
    return cmd_report(repo, args.file, args.decline)


def verb_suggest(repo, args):
    """`adopt.py suggest [--offer ID]`: which of the person's look entries could help other sites; `--offer` records a yes."""
    if args.offer is not None:
        suggestions.cmd_offer(repo, _one(args.offer, "--offer"))
        return None
    cmd_suggest(repo, suggestions.states_at(repo))
    return None


def verb_file(repo, args):
    """`adopt.py file PATH DISPOSITION | --clear`: the file accounting decision for one file or a folder, or forgetting it."""
    print(cmd_file(repo, args.path, args.disposition, args.clear))


def _as_is(repo, plan, snap, proof):
    """`adopt.py proof --as-is`: the person's "this PDF is right" for a PDF the plugin's reader finds too little in or cannot read (dev 1068, design 2.2, O-2):
    its hash goes into the plan (`resumeProof`), void when the PDF changes. The privacy review must then open the PDF; the hidden-details findings stand."""
    if proof.state == resumeproof.VOUCHED:
        print("adopt: you already vouched for %s; it holds while the PDF is this file" % proof.pdf)
        return
    if proof.state not in resumeproof.MAY_BE_VOUCHED:
        raise Refused("there is nothing to vouch for: %s; `--as-is` is for a PDF the plugin's reader finds too little in or cannot read, so run `adopt.py proof` to see where yours stands"
                      % " ".join(resumeproof.state_lines(proof)).replace("resume proof: ", "", 1))
    plan["resumeProof"] = resumeproof.vouch_row(snap.files, proof)
    save_plan(repo, plan)
    print("adopt: you vouch for the resume PDF %s (%s). `adopt.py apply` writes its proof and its commit says you vouched for it; the PDF does not change. "
          "The privacy gate still lists the PDF as not read, so the privacy review must open it (`/site-studio:review`), and the `apply` that follows that "
          "review must be run on the same UTC day, or the review has to be made again. This holds only while the PDF is this file: a new PDF voids it. "
          "Findings about the PDF's hidden details (an author, an unknown program, a title that is no page's) still stand: `--as-is` does not answer them."
          % (proof.pdf, proof.read_as()))


def _print_pdf(repo, basis, tree, plan, snap, proof, finder=None, tool=None):
    """`adopt.py proof --print`: print a new resume PDF from the CONVERTED resume page with Chrome, in a scratch repository, and copy only the PDF to the path
    it has at the basis (design 2.3). The sidecar is `apply`'s, so it can never be stale against the converted source."""
    head = gitt(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    if basis.sha != head:
        raise Refused("the new PDF would be committed on a branch adopt does not read (adopt converts %s %s; this checkout is at %s): %s"
                      % (basis.label(), basis.sha[:7], head[:7], basis.reason or "bring this branch and origin/main together (merge or push), then run it again"))
    if current_parity(plan.get("parity")) is None:
        raise Refused("run `adopt.py parity` first: the PDF is printed in the look parity chooses, so one printed before it could be in a look the site does not have")
    if not proof.pdf:
        raise Refused("the converted site configures no resume PDF, so there is nothing to print: commit the PDF beside the resume source (content/resume/resume.pdf), then run `adopt.py inventory` and `adopt.py proof --print` again")
    if detect_resume(tree)["needsAnswer"] and not plan["paper"]:               # the converted site.json carries a guess (Letter) that `apply` refuses to publish
        raise NeedsAnswer("resume.paper needs your answer: the resume PDF's paper size cannot be read from it; run `adopt.py paper Letter` or `adopt.py paper A4`, then print again")
    found, where = (finder or shots.find_chrome)()
    if not found:
        raise Refused("Chrome is needed to print the PDF and was not found (%s); install it, or use `adopt.py proof --as-is` for the PDF you have" % where)
    resume = model.parse_text(snap.files["site/site.json"].decode("utf-8")).resume or {}
    where_at = next((old for old, new in snap.notes.get("resumePdfName") or [] if new == proof.pdf), proof.pdf)      # a pending rename is followed back
    work = tempfile.mkdtemp(prefix="adopt-proof-")
    try:
        for rel, blob in snap.files.items():
            os.makedirs(os.path.dirname(os.path.join(work, *rel.split("/"))), exist_ok=True)
            with open(os.path.join(work, *rel.split("/")), "wb") as fh:
                fh.write(blob)
        ident = {"GIT_AUTHOR_NAME": "adopt proof", "GIT_AUTHOR_EMAIL": "proof@example.invalid", "GIT_COMMITTER_NAME": "adopt proof",
                 "GIT_COMMITTER_EMAIL": "proof@example.invalid"}
        git(work, "init", "-q", "-b", "main", env=ident)
        git(work, "add", "-A", "-f", ".", env=ident)
        git(work, "commit", "-q", "-m", "converted tree", "--allow-empty", env=ident)
        rc, text = (tool or run_tool)("resume_pdf.py", ["--repo", work, "--quiet"], work)
        if rc != 0:
            raise Refused("the PDF was not printed: %s; fix what it says and run `adopt.py proof --print` again"
                          % (([l for l in text.strip().split("\n") if l.strip()] or ["resume_pdf.py printed nothing"])[-1]))
        with open(os.path.join(work, *proof.pdf.split("/")), "rb") as fh:
            blob = fh.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    dest = os.path.join(repo, *where_at.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest + ".part", "wb") as fh:
        fh.write(blob)
    os.replace(dest + ".part", dest)
    print("adopt: printed %s (%d bytes, %s) from the converted resume page; nothing else was written (the proof is made by `apply`)" % (where_at, len(blob), resume["paper"]))
    print("visitors get this PDF the next time either builder publishes; look at it, commit it, then `adopt.py inventory` and `adopt.py parity`")
    print("if your template stamps the PDF's bytes beside it (a `.sha256` file), your old builder may stop after this: the next `parity` says so, as it does for any builder failure")


def verb_proof(repo, args):
    """`adopt.py proof [--as-is | --print]`: the resume PDF's proof (design 2). Alone it prints where the proof stands and what answers it; `--as-is` is the
    person's "this PDF is right", `--print` prints a new PDF. Starts as every verb that reads the basis does (`preconditions`)."""
    if args.as_is and args.print_:
        raise Refused("--as-is and --print answer the same question in two ways; give one")
    basis, tree, data = preconditions(repo)
    for line in basis.up_front():
        print(line)
    plan = _plan_for(repo, basis.sha, print)
    snap = wouldwrite.snapshot(wouldwrite.conversion(tree, data, plan, mode="check"))
    proof = resumeproof.prove(snap.files, resumeproof.vouched_sha(plan))
    if args.as_is:
        return _as_is(repo, plan, snap, proof)
    if args.print_:
        return _print_pdf(repo, basis, tree, plan, snap, proof)
    _say(resumeproof.state_lines(proof))


def verb_setting(repo, args):
    """`adopt.py setting NAME VALUE | --clear`: a chosen setting."""
    if args.clear == (args.value is not None):
        raise Refused("name the value (`adopt.py setting cardNumber true`), or `--clear` to forget a chosen one")
    print(cmd_setting(repo, args.name, args.value, args.clear))


def verb_remeasure(repo, args):
    """`adopt.py remeasure [--accept [--shots DIR/shots]] [--keep DIR]`: measure parity again on the moved basis."""
    print(cmd_remeasure(repo, args.accept, keep=args.keep, shots_dir=args.shots))


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
    "proof": verb_proof,
    "remeasure": verb_remeasure,
    "suggest": verb_suggest,
}
