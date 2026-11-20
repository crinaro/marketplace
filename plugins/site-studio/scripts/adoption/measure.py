"""adoption.measure -- running parity (P0 and P1) for `parity` and `remeasure`, and `--keep DIR`.

Part of the `adoption` package behind the entry point `adopt.py`.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile

from building import outcomes, running  # noqa: E402
from lookfiles import derive as look_mod  # noqa: E402
import parity_classes  # noqa: E402
from configschema import model  # noqa: E402

from adoption.base import PARITY_RECORD_REL, PlanError, Refused, git, gitt
from adoption.choose import choose
from adoption.engine import compute_engine, invocation_for, unmeasurable_language
from adoption.template import live_pdf_name
from adoption.tokens import detect_resume
from adoption.spec import load_spec
from adoption.tree import Tree, TreeFiles, inventory
from adoption.convert import _give_resume_sidecar, _snapshot, converted_site_files
from adoption.accounting import no_landing_lines, open_folders
from adoption.fileacct import pass_one, run_accounting, undecided_folders
from adoption.parity import (
    BUILDER_FAILS, TAKEOVER, takeover_class, OUTPUT_DIRS, _NET_BLOCK, _archive_to, _copy_working_copy,
    _run_builder, _walk, active_classes, builder_entry,
    builder_failed, classify_p2, compare_builds, parse_parity_record, preconditions, record_text,
    scrubbed_env, write_kept,
)
from adoption.plan import _plan_for, save_plan
from adoption.problems import accept_problems, check_only, format_problems, problem_dicts, problems_from_dicts
from adoption.report import accept_lines
from adoption.usage import old_runner

def _measure_p1(a_dir, local, entry, node, guard, env, scratch, tree, data, folders, kind, files, cnotes, args=(),
                dispositions=None):
    """P1 (design-site-fidelity section 5.0.2): the person's builder on the original working copy against
    the SAME builder on the CONVERTED tree. When it differs, each class of conversion is applied alone, so each
    differing class is named with its paths. Returns {verdict, reason, differences, classes}."""
    def variant(label, overlay, removed):
        c_dir = os.path.join(scratch, "p1-" + label)
        shutil.copytree(a_dir, c_dir, symlinks=False)
        for out_rel in OUTPUT_DIRS:
            shutil.rmtree(os.path.join(c_dir, *out_rel.split("/")), ignore_errors=True)
        for rel in removed:
            try:
                os.remove(os.path.join(c_dir, rel))
            except OSError:
                pass
        for rel, blob in overlay.items():
            os.makedirs(os.path.dirname(os.path.join(c_dir, rel)), exist_ok=True)
            with open(os.path.join(c_dir, rel), "wb") as fh:
                fh.write(blob)
        out, why = _run_builder(c_dir, entry, node, guard, env, args)
        if out is None:
            return None, why
        return compare_builds(local, _walk(out)), ""
    diffs, why = variant("all", files, cnotes["removed"])
    failed = diffs is None and builder_failed(why)
    if diffs is None and not failed:
        return {"verdict": "UNVERIFIED", "reason": why, "differences": [], "classes": {}}
    if diffs is not None and not diffs:
        return {"verdict": "SAME", "reason": "", "differences": [], "classes": {}}
    classes = {}
    for cls in ["base"] + active_classes(cnotes):
        sf, sn = converted_site_files(tree, data, None, folders, kind, only=set() if cls == "base" else {cls},
                                      strict=False, dispositions=dispositions)
        d, w = variant(cls, sf, sn["removed"])
        classes[cls] = ([list(x) for x in d] if d is not None
                        else [[BUILDER_FAILS if builder_failed(w) else "unverified", w, ""]])
    if failed:
        # dev #890, B1: the kept builder does not merely differ on the converted tree, it EXITS NON-ZERO. Each class
        # was run alone above, so the one(s) that make it fail are named with the builder's own failure line. A builder
        # that fails with NO conversion made is not the conversion's doing: that stays UNVERIFIED, as it was.
        if classes["base"] and classes["base"][0][0] == BUILDER_FAILS:
            return {"verdict": "UNVERIFIED", "reason": why, "differences": [], "classes": {}}
        return {"verdict": "FAILS", "reason": why, "differences": [], "classes": classes}
    return {"verdict": "DIFFERENT", "reason": "", "differences": [list(x) for x in diffs], "classes": classes}


def run_parity(repo, infos, basis, tree, data, which=None, run=None, folders=None, kind=None, chosen=(), keep=None,
               plan=None):
    """Build both ways and compare (named change M13). Returns a dict with `verdict`
    (EQUAL / DIFFERENT / UNVERIFIED / NOT APPLICABLE), `reason`, `differences`, `notes`.

    BOTH SIDES COME FROM `basis.sha` (dev #855, design 7.3): the local builder runs on a copy of the working
    copy, which must hold `basis.sha`'s tree, and the plugin side is built from `basis.sha`'s committed files
    with the adopt transform. A basis that is not buildable (`basis.reason`: HEAD diverged from, or behind,
    origin/main) is UNVERIFIED up front."""
    base = basis.sha
    res = {"verdict": "UNVERIFIED", "reason": "", "differences": [], "notes": [], "problems": [], "p1": None,
           "report": [], "kept": None, "markup": [], "tokens": {"class": [], "data": [], "id": []}, "external": [],
           "accounting": None, "cause": None, "engine": None}
    engine = compute_engine(tree, data, load_spec(), (plan or {}).get("files"))
    res["engine"] = engine["files"]
    entry = builder_entry(infos) or engine["entry"]
    if entry is None:
        lang = unmeasurable_language(tree, engine)
        if lang is not None:
            res.update(reason="the old builder is %s, which parity cannot run, so nothing was measured and the builder stays "
                       "your publisher; a release of site-studio that measures %s resolves this" % (
                           "run only by a workflow" if lang == "workflow" else lang, "it"),
                       cause="builder/unmeasurable/%s" % lang)
            return res
        res.update(verdict="NOT APPLICABLE", reason="no local builder was found (no JavaScript file classified as a builder)")
        return res
    inv, icause, why_inv = invocation_for(tree, engine, entry)
    if icause:
        res.update(reason="the publisher's invocation of the builder cannot be reproduced (%s), so no run would be what it "
                   "publishes; the builder is kept" % why_inv, cause=icause)
        return res
    if basis.reason:
        res["reason"] = "%s; the builder is kept" % basis.reason
        return res
    node = (which or shutil.which)("node")
    if not node:
        res["reason"] = "no Node on this computer, so the local builder cannot run; the builder is kept"
        return res
    if gitt(repo, "rev-parse", "HEAD^{tree}", check=False) != gitt(repo, "rev-parse", base + "^{tree}"):
        res["reason"] = ("the working copy differs from the parity basis %s %s (parity builds the working copy, "
                         "which must be what the basis holds); the builder is kept" % (basis.label(), base[:7]))
        return res
    only = check_only(chosen)         # the tree apply WILL make: an OPT_IN conversion the person has not chosen is not in it
    probs, _acc = accept_problems(tree, data, None, folders, kind, only)
    if plan is not None:      # F2: a page-less folder with no decision is the measured accounting's to settle (archived, or the question stays)
        asked = set(undecided_folders(tree, plan, kind))
        probs = [p for p in probs if not (p.found == "no page.md" and (p.path or "").startswith("content/")
                                          and p.path[len("content/"):].rstrip("/") in asked)]
    if probs and plan is not None and all(re.match(r"^content/[^/]+/[^/]+/index\.md$", p.path or "")
                                          and "is required in" in p.message for p in probs):
        probs = []            # a piece the plugin refuses may be work in progress the old builder never read: the file accounting decides
    if probs:
        res["problems"] = problem_dicts(probs)
        res["reason"] = ("the plugin's build would refuse the converted tree (%d problem(s), listed in the "
                         "format `check` prints); the builder is kept" % len(probs))
        return res
    ignored_present = gitt(repo, "ls-files", "-o", "-i", "--exclude-standard", "--directory", check=False).split("\n")
    ignored_present = [p for p in ignored_present if p and not p.startswith(("node_modules", "site/dist", ".claude/worktrees"))]
    res["notes"].append("the local build ran on a COPY of the working copy of %s %s, which includes ignored files%s"
                        % (basis.label(), base[:7],(" (present: %s)" % ", ".join(ignored_present[:6])) if ignored_present else " (none present)"))
    scratch = tempfile.mkdtemp(prefix="adopt-parity-")
    try:
        a_dir = os.path.join(scratch, "local")
        _copy_working_copy(repo, a_dir)
        for out_rel in OUTPUT_DIRS:
            shutil.rmtree(os.path.join(a_dir, *out_rel.split("/")), ignore_errors=True)
        guard = os.path.join(scratch, "guard.js")
        with open(guard, "w", encoding="utf-8") as fh:
            fh.write(_NET_BLOCK)
        env = scrubbed_env(os.path.join(scratch, "home"), node)
        env.update(inv.env)                       # the workflow's literal env: the builder runs as the publisher runs it
        os.makedirs(scrubbed_home(env), exist_ok=True)
        local_out, why = _run_builder(a_dir, entry, node, guard, env, inv.args)
        if local_out is None:
            res["reason"] = "%s; the builder is kept" % why
            res["cause"] = "env/builder-fails"
            return res
        local = _walk(local_out)
        dispositions = None
        persons = dict((p, e["disposition"]) for p, e in ((plan or {}).get("files") or {}).items() if e.get("disposition"))
        settings = dict((k, v["value"]) for k, v in ((plan or {}).get("settings") or {}).items() if v["how"] == "chosen")
        hints = {}
        resume = detect_resume(tree)
        live = live_pdf_name(tree, resume["pdf"], local) if resume["pdf"] else None
        if live:
            hints["resumePdf"] = live
        res["hints"] = hints
        if plan is not None:                 # design 8 FA, steps 1 to 4: every file accounted for BEFORE P2, so P2 judges the result
            res["accounting"] = _account_files(tree, data, plan, local, engine, infos, a_dir, entry, node, guard, env,
                                               inv.args, scratch, chosen, settings)
            if not res["accounting"].get("refused"):
                dispositions = res["accounting"]["dispositions"]
                folders = open_folders(folders, tree.paths(), dispositions)      # F1: a decision the archive already satisfied
            if res["accounting"].get("cause"):
                res["cause"] = res["cause"] or res["accounting"]["cause"]
            picked = _choose_settings(tree, data, plan, local, folders, kind, chosen, dispositions, persons, hints)
            if picked is not None:
                res["settings"] = picked.plan_rows()
                res["notes"].extend(picked.lines)
                res["lookStatus"] = picked.look_status
                res["notes"].extend("look: %s %s (%s)" % (cid, st, picked.look_why[cid]) for cid, st in sorted(picked.look_status.items())
                                    if st in ("unmapped", "ambiguous") and picked.look_why.get(cid))     # what derive refused, named
                settings.update(picked.values())
            elif plan.get("settings"):
                settings.update(dict((k, v["value"]) for k, v in plan["settings"].items()))
        b_dir, files, cnotes = _plugin_side(repo, base, scratch, tree, data, folders, kind, only, settings, dispositions, persons, hints, res)
        out_dir = os.path.join(scratch, "plugin-out")
        try:
            running.publish_build(b_dir, out_dir)
        except outcomes.BuildError as e:
            res["reason"] = "the plugin's build refused this repo (%s); the builder is kept" % e
            res["problems"] = problem_dicts(e.problems)
            return res
        plugin_files = _walk(out_dir)
        p2 = classify_p2(local, plugin_files)
        res.update(differences=p2["differences"], report=p2["report"], verdict=p2["verdict"], reason=p2["reason"],
                   markup=p2["markup"], tokens=p2["tokens"], external=p2["external"], kinds=p2["kinds"],
                   accepts=[list(c) for c in parity_classes.description_changes(local, plugin_files)])
        if keep:
            res["kept"] = write_kept(keep, local, plugin_files)
        if p2["verdict"] == "DIFFERENT":     # P2 shows a visible difference, so the builder is kept: does the CONVERSION change what it publishes?
            res["p1"] = _measure_p1(a_dir, local, entry, node, guard, env, scratch, tree, data, folders, kind,
                                    files, cnotes, inv.args, dispositions)
        return res
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _plugin_side(repo, base, scratch, tree, data, folders, kind, only, settings, dispositions, persons, hints, res):
    """Build the plugin side of parity in a fresh repo: the committed files of the basis plus the adopt transform. Returns (b_dir, files, cnotes)."""
    # the plugin side: committed files of origin/main + the adopt transform, in a fresh repo
    b_dir = os.path.join(scratch, "plugin")
    os.makedirs(b_dir)
    _archive_to(repo, base, b_dir)
    date = gitt(repo, "log", "-1", "--format=%cI", base)
    ident = {"GIT_AUTHOR_NAME": "adopt parity", "GIT_AUTHOR_EMAIL": "parity@example.invalid",
             "GIT_COMMITTER_NAME": "adopt parity", "GIT_COMMITTER_EMAIL": "parity@example.invalid",
             "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": os.devnull}
    git(b_dir, "init", "-q", "-b", "main", env=ident)
    git(b_dir, "add", "-A", "-f", ".", env=ident)
    git(b_dir, "commit", "-q", "-m", "origin/main", "--allow-empty", env=ident)
    files, cnotes = converted_site_files(tree, data, None, folders, kind, only, settings=settings,
                                         dispositions=dispositions, persons=persons, hints=hints)
    for rel in cnotes["removed"]:
        try:
            os.remove(os.path.join(b_dir, rel))
        except OSError:
            pass
    for rel, blob in files.items():
        os.makedirs(os.path.dirname(os.path.join(b_dir, rel)), exist_ok=True)
        with open(os.path.join(b_dir, rel), "wb") as fh:
            fh.write(blob)
    cfg = model.parse_text(files["site/site.json"].decode("utf-8"))
    if cfg.resume and cfg.resume.get("pdf") and os.path.isfile(os.path.join(b_dir, cfg.resume["pdf"])):
        side = os.path.join(b_dir, cfg.resume["pdf"] + ".json")
        if not os.path.exists(side):
            sha = lambda p: hashlib.sha256(open(os.path.join(b_dir, p), "rb").read()).hexdigest()  # noqa: E731
            with open(side, "w", encoding="utf-8") as fh:
                json.dump({"source_sha256": sha(cfg.resume["path"]), "pdf_sha256": sha(cfg.resume["pdf"]),
                           "text_sha256": "0" * 64}, fh)
            res["notes"].append("the plugin side was given the resume PDF sidecar the examples never wrote")
    git(b_dir, "add", "-A", "-f", ".", env=ident)
    git(b_dir, "commit", "-q", "-m", "adopt transform", "--allow-empty", env=ident)
    return b_dir, files, cnotes


def _choose_settings(tree, data, plan, local, folders, kind, chosen, dispositions, persons, hints):
    """The measured settings for the tree (`adoption.choose`): the plugin side built in memory once per candidate against the ONE
    local build; a look derived from the old builder's own pages when the default look does not agree (R6)."""
    _f, _n, snap, acc, _drafted = pass_one(tree, data, plan, chosen, None, hints)
    if acc is None:
        return None
    only = check_only(chosen)

    def snapshot(settings):
        f, n = converted_site_files(tree, data, None, folders, kind, only, settings=settings, dispositions=dispositions,
                                    persons=persons, hints=hints)
        s2 = _snapshot(tree, TreeFiles(tree, f, n["removed"]))
        _give_resume_sidecar(s2)
        return s2

    built, derived = {}, {}                          # the same settings are asked again by every pass: built and derived once each
    why = {}                                         # construct -> derive's reason it did not map (the element a rule refused)

    def evaluate(settings):
        key = json.dumps(sorted(settings.items()), default=repr)
        if key not in built:
            built[key] = dict(running.accept(snapshot(settings)).output)
        return built[key]

    def derive_under(settings, refine=True):
        """A look derived from the old builder's own pages against the converted content UNDER `settings` (the settings the content
        is built with decide which values the plugin writes, so they decide what a look can be mapped to). Settings that leave the
        converted tree as it was (a default, a key no page reads) derive the same look: asked once per distinct tree. `refine` False
        reads the pages once (the scoring of a candidate); True reads them again where the first reading left an instance ambiguous."""
        files = snapshot(settings)
        key = (hashlib.sha256(json.dumps(sorted((p, hashlib.sha256(b).hexdigest()) for p, b in files.items())).encode()).hexdigest(), refine)
        if key not in derived:
            pages = dict((p, b.decode("utf-8", "replace")) for p, b in local.items() if p.lower().endswith((".html", ".htm")))
            d = look_mod.derive_look(files, pages, refine=refine)
            status = {}
            for cid, counts in d.status.items():
                status[cid] = "mapped" if counts.get("mapped") and not (counts.get("unmapped") or counts.get("ambiguous")) else (
                    "ambiguous" if counts.get("ambiguous") else "unmapped" if counts.get("unmapped") else "not reached")
            why.update((cid, d.reasons[cid]) for cid in status if cid in d.reasons and status[cid] != "mapped")
            derived[key] = ({"id": "derived", "file": d.text}, status)
        return derived[key]
    picked = choose(snap, data, evaluate, local, previous=plan.get("settings"), derive_under=derive_under, no_local_reason=None)
    picked.look_why = why
    return picked


def scrubbed_home(env):
    return env["HOME"]


def _account_files(tree, data, plan, local, engine, infos, a_dir, entry, node, guard, env, args, scratch, chosen,
                   settings=None):
    """The file accounting for the basis tree (`adoption.fileacct`), with the old builder run again for the counterfactual."""
    paths = [p for p in tree.paths() if not p.startswith(".git/")]
    kept = set(i["path"] for i in infos if i["class"] in ("CUSTOM", "MIXED"))
    kept |= set(p for p, e in plan["files"].items() if e.get("removal") == "keep" or e.get("disposition") == "keep")
    kept |= set(p for p, c in engine["workflows"].items() if c in ("not-publishing", "other-publisher", "serves-dev-repo"))
    archived = set(p for p in paths if p.startswith("archive/"))      # ARCHIVE.json lists them; a file there is already placed
    cf_scratch = os.path.join(scratch, "counterfactual")
    os.makedirs(cf_scratch, exist_ok=True)
    runner = old_runner(a_dir, lambda work: _run_builder(work, entry, node, guard, env, args), cf_scratch)
    return run_accounting(paths, tree, data, plan, local, engine, kept, archived, runner, chosen, settings)


def measure_adopted(repo, which=None):
    """Parity for a repo adopt ALREADY converted: the person's kept builder, run on the working copy, against
    the plugin's build of HEAD. Returns the `run_parity` dict (verdict, reason, differences, notes)."""
    res = {"verdict": "UNVERIFIED", "reason": "", "differences": [], "notes": [], "problems": [], "p1": None,
           "report": [], "kept": None, "markup": [], "tokens": {"class": [], "data": [], "id": []}, "external": []}
    tree = Tree(repo, "HEAD")
    entry = builder_entry(inventory(tree))
    if entry is None:
        res.update(verdict="NOT APPLICABLE", reason="no local builder was found, so there is nothing site-studio's "
                   "build could differ from")
        return res
    node = (which or shutil.which)("node")
    if not node:
        res["reason"] = "no Node on this computer, so the local builder cannot run"
        return res
    scratch = tempfile.mkdtemp(prefix="adopt-remeasure-")
    try:
        a_dir = os.path.join(scratch, "local")
        _copy_working_copy(repo, a_dir)
        shutil.rmtree(os.path.join(a_dir, "site", "dist"), ignore_errors=True)
        guard = os.path.join(scratch, "guard.js")
        with open(guard, "w", encoding="utf-8") as fh:
            fh.write(_NET_BLOCK)
        env = scrubbed_env(os.path.join(scratch, "home"), node)
        os.makedirs(env["HOME"], exist_ok=True)
        out, why = _run_builder(a_dir, entry, node, guard, env)
        if out is None:
            res["reason"] = why
            return res
        local = _walk(out)
        b_dir = os.path.join(scratch, "plugin")
        os.makedirs(b_dir)
        _archive_to(repo, "HEAD", b_dir)
        date = gitt(repo, "log", "-1", "--format=%cI", "HEAD")
        ident = {"GIT_AUTHOR_NAME": "adopt remeasure", "GIT_AUTHOR_EMAIL": "parity@example.invalid",
                 "GIT_COMMITTER_NAME": "adopt remeasure", "GIT_COMMITTER_EMAIL": "parity@example.invalid",
                 "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": os.devnull}
        git(b_dir, "init", "-q", "-b", "main", env=ident)
        git(b_dir, "add", "-A", "-f", ".", env=ident)
        git(b_dir, "commit", "-q", "-m", "HEAD", "--allow-empty", env=ident)
        out_dir = os.path.join(scratch, "plugin-out")
        try:
            running.publish_build(b_dir, out_dir)
        except outcomes.BuildError as e:
            res["reason"] = "the plugin's build refuses HEAD (%s)" % e
            res["problems"] = problem_dicts(e.problems)
            return res
        plugin_files = _walk(out_dir)
        p2 = classify_p2(local, plugin_files)
        res.update(differences=p2["differences"], report=p2["report"], verdict=p2["verdict"], reason=p2["reason"],
                   markup=p2["markup"], tokens=p2["tokens"], external=p2["external"], kinds=p2["kinds"],
                   accepts=[list(c) for c in parity_classes.description_changes(local, plugin_files)])
        return res
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def differences_were_shown(prev, res):
    """True when `parity --accept` may record ACCEPTED: the differences it just measured are, triple for triple, the
    ones a previous `parity` ON THIS BASIS stored in the plan as DIFFERENT, so the person was shown them in an earlier
    run (dev #879, P4: `parity --accept` once saved ACCEPTED and only then printed the differences, so a person could
    accept differences they never saw). `prev` is `plan["parity"]`; `carry_plan` clears it when the basis moved, so
    `None` here also covers another basis. A stored ACCEPTED is not a showing: it may predate this rule. Nothing new is
    stored: the three-string `differences` the plan always kept are the comparison."""
    if not prev or prev.get("verdict") != "DIFFERENT" or not res["differences"]:
        return False
    return [list(d) for d in prev.get("differences", [])] == [list(d) for d in res["differences"]]


def cmd_remeasure(repo, accept=False, which=None):
    """`adopt.py remeasure [--accept]`: measure an adopted repo again and rewrite its parity record, in ONE commit
    that touches only the record. `--accept` records ACCEPTED, and only for a measured DIFFERENT (or, with no
    builder, for "site-studio's build replaces my site, unmeasured"); it is never a way past UNVERIFIED."""
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise Refused("adopt runs on your own computer, not in a cloud session; open the repo there")
    if git(repo, "rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise Refused("%s is not a git checkout; run adopt from your site's repo folder, or pass it with --repo" % repo)
    shown = git(repo, "show", "HEAD:" + PARITY_RECORD_REL, check=False)
    if shown.returncode != 0:
        raise Refused("this repo has no %s: it was not converted by a site-studio 0.3.0 adopt, so there is nothing "
                      "to measure again; run `adopt.py check` if you have not adopted this site yet" % PARITY_RECORD_REL)
    try:
        existing = parse_parity_record(shown.stdout.decode("utf-8", "replace"))
    except PlanError as e:
        raise Refused(str(e))
    if accept and existing["verdict"] in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
        raise Refused("there is nothing to accept: the record already says %s; run `adopt.py check` to see the next step"
                      % existing["verdict"])
    dirty = git(repo, "status", "--porcelain", "--untracked-files=no").decode("utf-8", "replace").strip()
    if dirty:
        raise Refused("the repo has uncommitted changes; commit or discard them first (parity builds the working copy)")
    res = measure_adopted(repo, which)
    verdict = res["verdict"]
    causes = res.get("report") or ["  %s: %s%s" % (k, p, (" (%s)" % d) if d else "") for k, p, d in res["differences"]]
    if accept:
        if verdict == "DIFFERENT":
            verdict = "ACCEPTED"
        elif verdict == "NOT APPLICABLE":
            verdict = "ACCEPTED"
        else:
            raise Refused("there is nothing to accept: parity is %s%s" % (
                res["verdict"], " (it could not measure, so nothing was shown to you)" if res["verdict"] == "UNVERIFIED" else "")
                + "; --accept applies only to a measured DIFFERENT, so read the verdict and deal with what it names")
        # dev #879, P4: what is being accepted is printed BEFORE the record that says ACCEPTED is written, grouped by
        # cause exactly as `parity` prints it, so the person has read the differences in the same run that accepts them
        print("\n".join(["remeasure --accept: you are accepting %s, and the record will say ACCEPTED:" % (
            "these differences (one line per cause)" if res["differences"] else
            "no measured difference (there is no local builder: site-studio's build replaces your site, unmeasured)")] + causes
            + accept_lines(res)))
    text = record_text(verdict, gitt(repo, "rev-parse", "HEAD"), res["differences"], res.get("markup", ()), res.get("tokens"))
    path = os.path.join(repo, *PARITY_RECORD_REL.split("/"))
    if text != shown.stdout.decode("utf-8", "replace"):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        who = git(repo, "var", "GIT_COMMITTER_IDENT", check=False)
        if who.returncode != 0:
            raise Refused("git has no committer identity; set user.name and user.email and run remeasure again")
        git(repo, "add", "--", PARITY_RECORD_REL)
        git(repo, "commit", "-q", "-m", "adopt remeasure: parity is %s" % verdict, "--", PARITY_RECORD_REL)
    out = ["remeasure: parity is %s -- %s" % (res["verdict"], res["reason"])]
    if not accept:                  # with --accept they were printed above, before the record was written
        out += causes + accept_lines(res)
    out += ["  " + l for l in format_problems(problems_from_dicts(res.get("problems", [])))]
    if verdict in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
        tail = "; site-studio may publish this site"
    elif verdict == "UNVERIFIED":
        tail = ("; site-studio will not publish over your own builder (`--accept` refuses UNVERIFIED: fix what "
                "stopped the measurement above, such as a missing node, a failing builder or what site-studio's "
                "build refuses, then run `adopt.py remeasure` again)")
    else:
        tail = ("; site-studio will not publish over your own builder (run `adopt.py remeasure --accept` once you "
                "have read the differences)")
    out.append("the record now says %s%s" % (verdict, tail))
    return "\n".join(out)


def keep_dir(repo, given):
    """`parity --keep <dir>` (dev #879, P2): the absolute folder the two builds will be left in. REFUSED, with nothing
    touched, when it exists and is not an empty folder (a build is never mixed into what is already there), when
    it is inside the repo (the working copy would then be dirty, and the next `check` would refuse it), or when it is
    inside ANOTHER worktree of the same repository (dev #879, gap 18: the primary checkout would gain untracked files
    and `sync_main` would stop fast-forwarding `main`; the refusal names that worktree)."""
    dest = os.path.abspath(given)
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        raise Refused("--keep %s exists and is not an empty folder; name one that does not exist yet (or is empty): "
                      "nothing in it was touched" % given)
    if os.path.realpath(dest) == os.path.realpath(repo) or os.path.realpath(dest).startswith(
            os.path.realpath(repo) + os.sep):
        raise Refused("--keep %s is inside the repo, which would leave it with uncommitted files; name a folder "
                      "outside it" % given)
    real = os.path.realpath(dest)
    for wt in _worktree_roots(repo):
        wt = os.path.realpath(wt)
        if real == wt or real.startswith(wt + os.sep):
            raise Refused("--keep %s is inside a worktree of this repository (%s), which would leave that checkout "
                          "with untracked files; choose a directory outside the repository" % (given, wt))
    return dest


def _worktree_roots(repo):
    """Every worktree of the repository `repo` belongs to (`git worktree list --porcelain`), the primary checkout
    first; empty when git cannot say (dev #879, gap 18)."""
    listing = gitt(repo, "worktree", "list", "--porcelain", check=False)
    return [line[len("worktree "):] for line in listing.splitlines() if line.startswith("worktree ")]


def cmd_parity(repo, accept=False, keep=None):
    """`adopt.py parity [--accept] [--keep DIR]` (moved here from adopt.py, the entry point, unchanged in what it prints):
    measure P2 and P1, save the result in the plan (`MARKUP-ONLY` carries its markup and tokens, plan schema 2) and print
    it. `--accept` records ACCEPTED only for the differences an earlier `parity` on this basis showed."""
    basis, tree, data = preconditions(repo)
    keep = keep_dir(repo, keep) if keep else None
    plan = _plan_for(repo, basis.sha, print)
    res = run_parity(repo, inventory(tree), basis, tree, data, folders=plan["folders"],
                     kind=plan.get("siteKind"), chosen=plan["convert"], keep=keep, plan=plan)
    causes = res.get("report") or ["  %s: %s%s" % (k, p, (" (%s)" % d) if d else "")
                                   for k, p, d in res["differences"]]
    prev = plan["parity"]               # what the last `parity` on this basis stored (a moved basis cleared it)
    to_accept = accept_lines(res)       # the pages whose search-result description will read differently, named once as an ACCEPT
    accepted_now = shown_first = False
    if accept:
        if res["verdict"] != "DIFFERENT":
            raise Refused("there are no differences to accept (parity is %s); --accept applies only to a measured DIFFERENT, so "
                          "read the verdict and deal with what it names" % res["verdict"])
        accepted_now = differences_were_shown(prev, res)
        shown_first = not accepted_now
    if accepted_now:
        # dev #879, P4: what is being accepted is printed BEFORE the plan that says ACCEPTED is saved
        print("\n".join(["parity --accept: you are accepting these differences (one line per cause), the "
                         "ones a previous `parity` on this basis showed, and the plan will say ACCEPTED:"] + causes + to_accept))
        res["verdict"] = "ACCEPTED"
    plan["parity"] = {"verdict": res["verdict"], "reason": res["reason"],
                      "differences": [list(d) for d in res["differences"]], "p1": res.get("p1")}
    if res["verdict"] == "MARKUP-ONLY":          # what the record (schema 2) will list: every invisible hunk and token
        plan["parity"].update(markup=res["markup"], tokens=res["tokens"])
    for key in ("accounting", "cause", "engine", "kinds", "hints", "lookStatus", "accepts"):    # what `apply` disposes by, and the causes it records
        if res.get(key):
            plan["parity"][key] = res[key]
    if res.get("settings") is not None:               # the measured rows replace the old measured ones; a `chosen` row is the person's
        kept = dict((k, v) for k, v in (plan.get("settings") or {}).items() if v["how"] == "chosen")
        plan["settings"] = dict(res["settings"], **kept)
        for name, row in sorted(res["settings"].items()):
            if row["how"] == "not measured":
                print("  setting %s: you decide -- %s" % (name, row["reason"]))
            elif row["value"] not in (None,) and name not in kept:
                print("  setting %s: %s (%s)" % (name, "a derived look" if isinstance(row["value"], dict) else row["value"], row["reason"]))
    save_plan(repo, plan)
    print("parity: %s -- %s" % (res["verdict"], res["reason"]))
    for n in res["notes"]:
        print("  note: %s" % n)
    for line in ([] if accepted_now else causes):       # accepted: printed above, before the plan was saved
        print(line)
    for line in ([] if accepted_now else to_accept):    # the descriptions, named once as an ACCEPT (accepted: printed above with the causes)
        print(line)
    acct = res.get("accounting")
    if acct:
        print("file accounting: " + ", ".join("%d %s" % (n, d) for d, n in sorted(acct["counts"].items()) if n)
              if acct.get("counts") else "file accounting: " + (acct.get("refused") or "not run"))
        for line in acct["lines"] + no_landing_lines(acct):         # N1: the count, then every no-landing path with why
            print("  " + line)
    if res.get("engine"):
        print("the old builder's own files (moved only after site-studio has published): %d" % len(res["engine"]))
        for path, rule in sorted(res["engine"].items()):
            print("  %s (%s)" % (path, rule))
    if keep:
        print("  kept: the local build is in %s and the plugin build in %s (as the builders wrote them)"
              % (os.path.join(keep, "local"), os.path.join(keep, "plugin")) if res.get("kept") else
              "  --keep: nothing was kept, because the two builds did not both run (the line above says why)")
    for line in format_problems(problems_from_dicts(res.get("problems", []))):
        print("  " + line)
    p1 = res.get("p1")
    if p1:
        print("P1 (does the conversion change what your own builder publishes?): %s%s"
              % (p1["verdict"], (" -- " + p1["reason"]) if p1.get("reason") else ""))
        for cls, ds in sorted(p1.get("classes", {}).items()):
            print("  %s: %s" % (cls, ("%s: your own builder cannot read what it makes (%s)" % (TAKEOVER, ds[0][1]))
                                if ds and ds[0][0] == BUILDER_FAILS and takeover_class(cls) else
                                ("your own builder FAILS on it: %s" % ds[0][1]) if ds and ds[0][0] == BUILDER_FAILS else
                                ("%d difference(s), first %s %s" % (len(ds), ds[0][0], ds[0][1])) if ds else "no difference"))
    if shown_first:
        print("parity --accept did NOT accept: %s Run `adopt.py parity --accept` again to accept exactly "
              "these." % ("no earlier `parity` on this basis had shown you differences, so the ones listed "
                          "above are shown now, and the plan says DIFFERENT as plain `parity` records it."
                          if not (prev and prev.get("verdict") == "DIFFERENT") else
                          "they are not the differences the last `parity` on this basis showed you, so the "
                          "ones listed above are what is measured now, and the plan says DIFFERENT."))
