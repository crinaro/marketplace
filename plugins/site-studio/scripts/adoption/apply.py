"""adoption.apply -- settings and hooks, CLAUDE.md, .gitignore, facts, `prepare` and the one commit `apply` makes.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

A STANDING RULE OF THE PERSON'S OWN (dev #851, design-site-adoption section 10, criterion O1). A residual unit of
a file adopt removes can be marked `rule`: "a standing rule of mine, keep it for every agent". Apply appends each
one, verbatim and with its source path, to the site repo's `CLAUDE.md` under `## Standing rules carried by
adopt`, after the engine sections are replaced (that heading is not one of them), and lists each in the commit.
Subagents load the project's CLAUDE.md, and tests/probes/PB-RESULT.md measured that `.claude/rules/` reaches a
plugin agent too, so the person may move the rules there. A `rule` unit on a file that stays is refused: a rule
travels only out of a file adopt removes.

HOOKS (design 6.4.3, round 1 S10). A hook command naming a removed file: removed when the plugin's
own hook does the same job (doctor, sync_main), rewritten to the plugin's script keeping its
arguments when the capability has a counterpart script, and otherwise the file is KEPT. Every
change is listed. UNDETERMINED: whether `${CLAUDE_PLUGIN_ROOT}` is defined for a hook in a
project's settings file; the rewrite is listed for the person to read, and the backstop below
guards the rest. The backstop refuses to finish when any remaining hook names a repo path absent
from the new tree.
"""

import difflib
import json
import os
import posixpath
import re
import shutil
import tempfile

import github_url  # noqa: E402
import report_issue  # noqa: E402

from adoption import finish
from adoption.accounting import ARCHIVE_REL, archive_path, dump_archive, parse_archive
from adoption.base import NeedsAnswer, PARITY_RECORD_REL, PLUGIN, PlanError, Refused, git
from adoption.spec import CONVERSION_CLASSES, load_spec
from adoption.classify import _fmt_pct, classify_text, shadow_suffix
from adoption.tree import Tree, TreeFiles, counterpart_of, inventory
from adoption.tokens import detect_resume
from adoption.convert import converted_site_files, old_form_hits
from adoption.features import infer_kind
from adoption.parity import (
    builder_entry, decide_conversions, parity_record_text, preconditions,
    template_fingerprint,
)
from adoption.problems import accept_problems, accept_warnings, broken_chosen
from adoption.plan import load_plan
from adoption.engine import compute_engine
from adoption.outcome import assess
from adoption.blockers import is_stray_warning
from adoption.reports import REPORTS_REL
from adoption.hookpaths import dangling_hook_paths, process_hooks

STARTER_SETTINGS = os.path.join(PLUGIN, "templates", "starter", "dot-claude", "settings.json")
# Named change S8: pinned word for word in tests/test_adopt.py and the starter's test_repos.
POINTER_LINE = ("If /site-studio commands are unknown, this session does not have the plugin (cloud "
                "sessions do not install repo-declared plugins); open the repo on your own computer.")
BRANCH_PREFIX = "site-studio/adopt-"
# Named change S2: the app keeps session worktrees inside the repo.
GITIGNORE_LINES = (".claude/worktrees/", "site/dist/", ".site-studio/review/")
RULES_HEADING = "## Standing rules carried by adopt"


def merge_settings(text, starter_text):
    """The person's settings plus the plugin's registration and ask rules (design 6.3). Keeps every
    key and rule already there. Returns the settings dict (hooks untouched)."""
    cur = json.loads(text) if text else {}
    st = json.loads(starter_text)
    cur.setdefault("extraKnownMarketplaces", {})
    for k, v in st["extraKnownMarketplaces"].items():
        cur["extraKnownMarketplaces"].setdefault(k, v)
    cur.setdefault("enabledPlugins", {})
    for k, v in st["enabledPlugins"].items():
        cur["enabledPlugins"].setdefault(k, v)
    perms = cur.setdefault("permissions", {})
    ask = perms.setdefault("ask", [])
    for rule in st["permissions"]["ask"]:
        if rule not in ask:
            ask.append(rule)
    return cur


_ENGINE_HEADING = re.compile(
    r"\b(repo split|layout|team|agents?|publish(ing)?|gates?|environment|set-?up|deploy(ment)?|build(ing)?|commands?|"
    r"workflow|how (this|it) works|engine|tools|checks?|trees?|branching|landing)\b", re.I)


def transform_claude_md(text):
    """Keep every section about the person; replace the engine sections (the examples' repo split,
    layout, team, publishing, gates, environment...) with one pointer to the plugin and the S8 line.
    A level-1 title and any text before the first heading are kept. Returns the new text."""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)
    pointer_done = False
    pointer = ["This repo's build, checks, publishing and review tools come from the site-studio plugin.", "",
               POINTER_LINE, ""]
    cur_level = None
    skipping = False
    skip_level = 0
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            if skipping and level <= skip_level:
                skipping = False
            if not skipping and level >= 2 and _ENGINE_HEADING.search(m.group(2)):
                skipping, skip_level = True, level
                if not pointer_done:
                    out.extend(pointer)
                    pointer_done = True
                continue
        if skipping:
            continue
        if POINTER_LINE in line:
            pointer_done = True
        out.append(line)
    body = "\n".join(out).rstrip("\n")
    if not pointer_done:
        body = body + "\n\n" + "\n".join(pointer).rstrip("\n")
    return body.rstrip("\n") + "\n"


def append_rules(text, rules):
    """Carry each `rule` unit, verbatim, into CLAUDE.md under RULES_HEADING with the path it came from
    (design 10). The heading is added when it is missing; when it is already there the new blocks go at the end
    of ITS section. Returns the new text (unchanged when there is nothing to carry)."""
    if not rules:
        return text
    blocks = "".join("\n### From %s\n\n%s\n" % (r["source"], r["text"].strip("\n")) for r in rules)
    body = text if text.endswith("\n") else text + "\n"
    m = re.search(r"^%s[ \t]*$" % re.escape(RULES_HEADING), body, re.M)
    if not m:
        return body + "\n" + RULES_HEADING + "\n" + blocks
    nxt = re.compile(r"^## ", re.M).search(body, m.end())
    cut = nxt.start() if nxt else len(body)
    return body[:cut].rstrip("\n") + "\n" + blocks + ("\n" + body[cut:] if nxt else "")


def update_gitignore(text):
    have = set(l.strip().strip("/") for l in text.split("\n") if l.strip() and not l.strip().startswith("#"))
    add = [l for l in GITIGNORE_LINES if l.strip("/") not in have]
    if not add:
        return text, []
    body = text if (not text or text.endswith("\n")) else text + "\n"
    return body + "".join(l + "\n" for l in add), add


def _next_decision_number(tree):
    nums = []
    for p in tree.paths():
        m = re.match(r"^decisions/(\d{2,})-", p)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def _slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "rule"


def write_facts(tree, facts, date):
    """Data files first: append each fact under a heading naming its source file and the date.
    Returns [(source, target)]."""
    moved = []
    by_target = {}
    rule_files = {}
    for fa in facts:
        if fa["kind"] == "context":
            target = "decisions/00-context.md"
        elif fa["kind"] == "voice":
            target = "BRAND.md"
        else:
            name = _slug(fa.get("name") or "rule")
            if name not in rule_files:
                rule_files[name] = "decisions/%02d-%s.md" % (_next_decision_number(tree) + len(rule_files), name)
            target = rule_files[name]
        by_target.setdefault(target, {}).setdefault(fa["source"], []).append(fa["text"].strip())
    for target in sorted(by_target):
        if tree.exists(target):
            body = tree.text(target)
            body = body if body.endswith("\n") else body + "\n"
        else:
            title = {"decisions/00-context.md": "# Context\n", "BRAND.md": "# Brand\n"}.get(
                target, "# %s\n" % posixpath.splitext(posixpath.basename(target))[0].split("-", 1)[-1].replace("-", " ").title())
            body = title
        for source in sorted(by_target[target]):
            body += "\n## From %s (%s)\n\n" % (source, date)
            for t in by_target[target][source]:
                body += "- %s\n" % t.replace("\n", " ")
            moved.append((source, target))
        tree.write(target, body)
    return moved


def check_branch_free(repo, branch):
    if git(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch, check=False).returncode == 0:
        raise Refused("the branch %s already exists; delete it (`git branch -D %s`) or pass another --date" % (branch, branch))


def set_branch(repo, branch, commit):
    """Point a NEW branch at `commit` (the old value "" makes git refuse an existing one)."""
    git(repo, "update-ref", "refs/heads/" + branch, commit, "")


def commit_branch(repo, tree, base, branch, message):
    """One commit on a NEW branch, from `base`, containing `tree`'s pending writes and removals (the commit object first,
    then the branch). Uses a private index and plumbing: the person's index, working tree and HEAD are untouched."""
    check_branch_free(repo, branch)
    commit = commit_object(repo, tree, base, message)
    set_branch(repo, branch, commit)
    return commit


def commit_object(repo, tree, base, message):
    """The commit object (on no branch) for `tree`'s pending writes and removals on top of `base`: the one thing `apply` hands to
    the publish, so a run that is killed before its last step leaves no ref behind."""
    tmp = tempfile.mkdtemp(prefix="adopt-index-")
    try:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git(repo, "read-tree", base, env=env)
        lines = []
        for path in sorted(tree.removed):
            if "\n" in path or "\t" in path:
                raise Refused("a path contains a tab or newline: %r; rename that file with `git mv` and commit, then "
                              "run adopt again" % path)
            lines.append("0 %s\t%s" % ("0" * 40, path))
        for path in sorted(tree.writes):
            if "\n" in path or "\t" in path:
                raise Refused("a path contains a tab or newline: %r; rename that file with `git mv` and commit, then "
                              "run adopt again" % path)
            sha = git(repo, "hash-object", "-w", "--stdin", input=tree.writes[path]).decode().strip()
            lines.append("%s %s\t%s" % (tree.mode(path), sha, path))
        if lines:
            git(repo, "update-index", "--index-info", input=("\n".join(lines) + "\n").encode("utf-8"), env=env)
        new_tree = git(repo, "write-tree", env=env).decode().strip()
        who = git(repo, "var", "GIT_COMMITTER_IDENT", check=False)
        if who.returncode != 0:
            raise Refused("git has no committer identity; set user.name and user.email and run apply again")
        return git(repo, "commit-tree", new_tree, "-p", base, "-m", message).decode().strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _checked_plan(repo, base):
    """The plan the person made. Raises Refused when there is none, or when the parity basis moved since the inventory."""
    try:
        plan = load_plan(repo)
    except PlanError as e:
        raise Refused(str(e))
    if plan is None:
        raise Refused("there is no plan yet; run `adopt.py inventory` and make your decisions first")
    if plan["base"] != base:
        raise Refused("the parity basis moved since the inventory (%s -> %s); run `adopt.py inventory` again"
                      % (plan["base"][:7], base[:7]))
    return plan


def _decided_conversions(tree, data, plan, kw):
    """Which classes of conversion are made. Returns (rows, held, only); raises Refused when a chosen conversion breaks the kept builder."""
    # which classes of conversion are made: one that parity measured as changing a page, or what the person's
    # own builder publishes, is NOT made (design-site-fidelity section 5.0.3): the site stays on its builder
    try:
        _all_files, all_notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), **kw)
        rows = decide_conversions(all_notes, plan["parity"], template_fingerprint(tree), plan["convert"])
    except Refused:
        rows = []
    held = set(r["class"] for r in rows if r["status"] == "you decide")
    only = None if not held else set(c for c, _l, _w in CONVERSION_CLASSES if c not in held)
    # dev #890, B1: a conversion the person CHOSE, on which P1 showed the kept builder exits non-zero, is not written
    # while parity is not EQUAL or ACCEPTED (the builder stays the publisher, and the tree would break it). `--dry-run`
    # asks `prepare` too, so its verdict is the same refusal.
    broken = broken_chosen(rows, plan)
    if broken:
        raise Refused("%s is chosen, but your own builder FAILS on the tree it makes (%s) and parity is %s: apply will not "
                      "write a conversion that breaks the builder that stays your publisher. `adopt.py convert %s --keep` "
                      "leaves it as written; or fix the builder, run `adopt.py parity` again, and accept it once parity "
                      "is EQUAL or ACCEPTED" % (broken[0]["class"], broken[0]["failure"],
                                                (plan["parity"] or {}).get("verdict", "not run"), broken[0]["class"]))
    return rows, held, only


def _build_refusals(tree, data, plan, only, kw, dispositions):
    """What the plugin's own build refuses in the tree adopt would write, as problems."""
    # what the plugin's own build refuses in the tree adopt would write (before anything is written)
    refusals, acc = accept_problems(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), only, **kw)
    refusals = refusals + accept_warnings(acc)
    if dispositions:             # a stray file is disposed by the file accounting, never also a refusal (design R4 row 16 (a))
        refusals = [p for p in refusals if not is_stray_warning(p)]
    return refusals


def _refuse_undecided(tree, infos, decisions, plan, dry_run):
    """Every file proposed for removal needs a decision, and the resume's paper size must be known. Raises Refused or NeedsAnswer."""
    # 1. every file proposed for removal needs a decision
    # An undecided PARTIAL is KEPT (the skill says so: it is removable only when its units are decided or parity
    # passes). An undecided DUPLICATE or AMBIGUOUS proposes a removal, so a real apply refuses; a dry run previews
    # with them (it writes nothing) and says what a real apply would do (F3).
    undecided = [i["path"] for i in infos if i["class"] in ("DUPLICATE", "AMBIGUOUS")
                 and (decisions.get(i["path"]) or {}).get("removal") is None]
    if undecided and not dry_run:
        raise Refused("no decision yet for %d file(s), first %s: run `adopt.py confirm <path>` or `--keep`"
                      % (len(undecided), undecided[0]))
    resume = detect_resume(tree)
    paper = plan["paper"] or resume["paper"]
    if resume["needsAnswer"] and paper is None:
        raise NeedsAnswer("resume.paper needs your answer: the resume PDF's paper size cannot be read from it; "
                          "run `adopt.py paper Letter` or `adopt.py paper A4`")


def _collect_removals(spec, tree, infos, decisions, plan, parity):
    """The files a decision removes, what is kept and why, the facts to move and the standing-rule units. Raises Refused for a decision that is not safe to act on."""
    removals, kept, facts, reasons, unit_facts, rule_units = {}, [], [], {}, [], []
    for i in infos:
        d = decisions.get(i["path"]) or {}
        cls = i["class"]
        if cls in ("CUSTOM", "MIXED"):
            if cls == "CUSTOM":
                kept.append((i["path"], "no plugin counterpart" + shadow_suffix(i)))
            continue
        if d.get("removal") == "keep":
            kept.append((i["path"], "kept by your decision (%s, score %s)" % (cls, _fmt_pct(i["score"]))
                         + shadow_suffix(i)))
            continue
        if d.get("removal") is None:
            kept.append((i["path"], "kept by default (no decision; %s, score %s)%s" % (
                cls, _fmt_pct(i["score"]), "" if cls == "PARTIAL" else
                ": a real apply refuses until you decide, so this is a preview") + shadow_suffix(i)))
            continue
        # a decision to remove
        eff = i
        if cls == "AMBIGUOUS":
            if not d.get("as"):
                raise Refused("%s is AMBIGUOUS between %s: say which with `adopt.py confirm %s --as <capability>`"
                              % (i["path"], " and ".join(c for c, _s in i["candidates"]), i["path"]))
            eff = classify_text(spec, i["path"], i["kind"], tree.text(i["path"]), as_cap=d["as"])
            if eff["capability"] is None:
                raise Refused("%s does not match %s; pass another capability to `adopt.py confirm %s --as`, or keep the file "
                              "with `adopt.py confirm %s --keep`" % (i["path"], d["as"], i["path"], i["path"]))
        prose = i["kind"] in ("agent", "command", "skill")
        if prose:
            if not d.get("reviewed"):
                raise Refused("the facts in %s are unreviewed: read it, record what is yours with `adopt.py "
                              "unit`/`fact`, then run `adopt.py reviewed %s`; nothing is removed before its facts "
                              "are moved" % (i["path"], i["path"]))
            for u in eff["residual_units"]:
                ud = (d.get("units") or {}).get(u["id"])
                if ud is None:
                    raise Refused("%s: unit %s is not dispositioned (person data, or behaviour to keep): %s; give it a "
                                  "disposition with `adopt.py unit %s %s person-data|keep|rule`"
                                  % (i["path"], u["id"], u["text"].split("\n")[0][:60], i["path"], u["id"]))
                if ud["disposition"] == "keep":
                    raise Refused("%s: unit %s is marked keep, so the file stays; run `adopt.py confirm %s --keep`"
                                  % (i["path"], u["id"], i["path"]))
                if ud["disposition"] == "rule":
                    rule_units.append({"source": i["path"], "id": u["id"], "text": u["text"]})
                    continue
                unit_facts.append({"source": i["path"], "kind": ud["kind"], "text": u["text"], "name": ud.get("name")})
        else:
            if spec.caps[eff["capability"]].get("needsParity"):
                if not parity or parity["verdict"] not in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
                    raise Refused("%s is a local builder file and parity is %s: it stays (run `adopt.py parity`)"
                                  % (i["path"], (parity or {}).get("verdict", "not run")))
            elif eff["class"] == "PARTIAL":
                raise Refused("%s is PARTIAL (residual %s) and nothing says its extra behaviour is safe to drop: "
                              "run `adopt.py confirm %s --keep`" % (i["path"], _fmt_pct(eff["residual"]), i["path"]))
        removals[i["path"]] = eff
        reasons[i["path"]] = ("matched by what it does: %s (score %s, residual %s; signals: %s)"
                              % (eff["capability"], _fmt_pct(eff["score"]), _fmt_pct(eff["residual"]),
                                 ", ".join(eff["signals"])))
    for fa in plan["facts"]:
        if fa["source"] in removals:
            facts.append(fa)
    facts = unit_facts + facts
    return removals, kept, facts, reasons, rule_units


def _write_site(tree, data, plan, only, kw, held, rows, infos, base, parity):
    """Write the converted site files and the parity record into the tree. Returns (notes, record)."""
    try:
        site_files, notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), only, **kw)
    except Refused as e:
        if held and str(e).startswith("the converted site.json is not valid"):
            raise Refused("%s; it needs a conversion that is held back (%s), so the plugin's build cannot read it yet: settle "
                          "that first (`adopt.py check` says why)" % (e, ", ".join(sorted(held))))
        raise
    notes["held"] = [r for r in rows if r["status"] == "you decide"]
    for p, blob in sorted(site_files.items()):
        tree.write(p, blob)
    record = parity_record_text(parity, builder_entry(infos) is not None, base)
    tree.write(PARITY_RECORD_REL, record)
    return notes, record


def _site_changes(tree, notes, record, plan):
    """The change lines for what was converted in the site files, in the order the message lists them."""
    changes = []
    changes.append("%s: parity %s%s" % (PARITY_RECORD_REL, json.loads(record)["verdict"],
                                        "" if json.loads(record)["verdict"] in ("EQUAL", "MARKUP-ONLY", "ACCEPTED") else
                                        "; site-studio will not publish this site until `adopt.py remeasure` says "
                                        "EQUAL or you accept the differences"))
    for p in notes["removed"]:
        tree.remove(p)
    changes.append("site/site.json: added schema, engine and resume; every other key kept"
                   + ("; written as schema %d (%s)" % (notes["schema"], "; ".join(
                       "%s %s" % (w, what) for w, what, _e in notes["schemaReasons"]))
                      if notes["schema"] > 1 else ""))
    for _key, _old, _new, line in notes["normalised"]:
        changes.append(line)
    for _old, _new, line in notes["layout"]:
        changes.append(line)
    for r in notes["redirects"]:
        changes.append("redirects: %s -> '%s': %s (the page is deleted and the build writes one at the same "
                       "address%s)" % (r.path, r.key, json.dumps(r.target),
                                       "; its own text is dropped: %s" % json.dumps(r.dropped) if r.dropped else ""))
    for r in notes["redirectBoiler"]:
        changes.append("redirects: %s -> '%s': %s (you chose this: the page is deleted and the build writes one at the "
                       "same address, which DROPS %s from what a visitor loads)"
                       % (r.path, r.key, json.dumps(r.target), ", ".join(r.boiler)))
    for old_key, new_key, _ot, new_target in notes["redirectKeys"]:
        changes.append("redirects: %s -> %s: trailing slash dropped (the build writes the same address, %s)"
                       % (json.dumps(old_key), json.dumps(new_key), json.dumps(new_target)))
    for old, new in notes["pieces"]:
        changes.append("%s -> %s: renamed, content unchanged (the plugin reads a piece from index.md)" % (old, new))
    for path, val in notes["viewKeys"]:
        changes.append("%s: view %s removed (you chose this: the plugin builds that portfolio's index as its grid, which "
                       "a visitor sees as a different page)" % (path, val))
    for folder, src, dst in notes["pieceKeys"]:
        changes.append("%s: front matter key %s -> %s (the plugin reads %s; the value is unchanged)" % (folder, src, dst, dst))
    for key, _val in notes["resumeFields"]:
        changes.append("%s: front matter %s -> a body paragraph (you chose this: it adds visible text)"
                       % (notes["resume"]["md"], key))
    changes.append(kind_change_line(tree, plan.get("siteKind")))
    changes = [c for c in changes if c]
    if notes["labels"]:
        changes.append("work.labels: converted %d labels" % len(notes["labels"]))
        for where, found, key, label in notes["labels"]:
            changes.append("%s: %s -> key %s, label %s" % (where, found, key, json.dumps(label)))
    frozen = set((p, a, b) for p, a, b in notes["tokensFrozen"])
    seen_tokens = set()
    for p, a, b in notes["tokens"]:
        if (p, a, b) in seen_tokens:
            continue
        seen_tokens.add((p, a, b))
        changes.append("%s: token %s -> %s%s" % (p, a, b, " (frozen as text, as your builder wrote it: it does not update "
                                                 "when content/home changes, and parity measures the page)"
                                                 if (p, a, b) in frozen else ""))
    return changes


def _carry_claude_and_gitignore(tree, rule_units, changes):
    """Replace the engine sections of CLAUDE.md, carry the standing rules, update .gitignore. Returns (old, new) CLAUDE.md."""
    claude_old = tree.text("CLAUDE.md") if tree.exists("CLAUDE.md") else "# Rules for this repo\n"
    claude_new = transform_claude_md(claude_old)
    claude_new = append_rules(claude_new, rule_units)
    tree.write("CLAUDE.md", claude_new)
    changes.append("CLAUDE.md: person sections kept, engine sections replaced by one pointer to the plugin")
    for r in rule_units:
        changes.append("CLAUDE.md: standing rule carried from %s (unit %s) under \"%s\""
                       % (r["source"], r["id"], RULES_HEADING))
    gi_old = tree.text(".gitignore") if tree.exists(".gitignore") else ""
    gi_new, gi_add = update_gitignore(gi_old)
    if gi_add:
        tree.write(".gitignore", gi_new)
        changes.append(".gitignore: added %s" % ", ".join(gi_add))
    return claude_old, claude_new


def _settings_and_hooks(tree, spec, removals, kept, by_path, changes):
    """Merge the plugin's registration into .claude/settings.json and handle hooks that name a removed file. Returns (settings, hook_list)."""
    # settings and hooks
    cap_of = dict((p, e["capability"]) for p, e in removals.items())
    st_old = tree.text(".claude/settings.json") if tree.exists(".claude/settings.json") else ""
    with open(STARTER_SETTINGS, "r", encoding="utf-8") as fh:
        starter = fh.read()
    try:
        settings = merge_settings(st_old, starter)
    except ValueError:
        raise Refused(".claude/settings.json is not valid JSON, so adopt cannot merge into it; fix the JSON in that file, "
                      "then run adopt again")
    hook_list = []
    for _round in range(2):
        trial = json.loads(json.dumps(settings))
        trial, hook_list, blocked = process_hooks(trial, set(removals), cap_of, spec)
        if not blocked:
            break
        for p in sorted(blocked):
            removals.pop(p, None)
            kept.append((p, "a hook still calls it and no plugin hook replaces it" + shadow_suffix(by_path.get(p, {}))))
    else:
        raise Refused("hooks still name files adopt would remove; keep those files with `adopt.py file <path> keep`, or "
                      "remove the hook lines that call them from .claude/settings.json")
    settings = trial
    tree.write(".claude/settings.json", json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    changes.append(".claude/settings.json: plugin registration and ask rules added; your own rules kept")
    return settings, hook_list


def _archive_removals(tree, removals, changes):
    """Archive each confirmed removal under archive/ (never delete) and list them in archive/ARCHIVE.json."""
    # 4. removals last
    # decision 18: a confirmed removal is ARCHIVED under archive/ (a leading `.claude/` written `_claude/`, so a skill cannot load
    # again), never deleted, and listed in archive/ARCHIVE.json: rule `claude-config` for what was under `.claude/`, else `person`
    archive_rows = list(parse_archive(tree.text(ARCHIVE_REL))) if tree.exists(ARCHIVE_REL) else []
    archived_here = []

    def archive_file(q, rule):
        dest = archive_path(q)
        if tree.exists(dest):
            raise Refused("%s already exists, so %s cannot be archived there; move or delete it first" % (dest, q))
        tree.write(dest, tree.read(q))
        tree.remove(q)
        if q not in set(r["from"] for r in archive_rows):
            archive_rows.append({"from": q, "disposition": "archived", "rule": rule})
        archived_here.append((q, dest))
    for p in sorted(removals):
        rule = "claude-config" if p.startswith(".claude/") else "person"
        if removals[p]["kind"] == "skill":
            folder = posixpath.dirname(p) + "/"
            for q in [x for x in tree.paths() if x.startswith(folder)]:
                archive_file(q, "claude-config")
        else:
            archive_file(p, rule)
        if posixpath.basename(p) == "package.json":
            lock = posixpath.dirname(p) + "/package-lock.json"
            if tree.exists(lock):
                archive_file(lock, rule)
    if archived_here:
        tree.write(ARCHIVE_REL, dump_archive(archive_rows).encode("utf-8"))
        changes.append("%d file(s) you confirmed for removal are archived, not deleted: %s (listed in %s; nothing under archive/ is "
                       "built or read)" % (len(archived_here), ", ".join("%s -> %s" % m for m in archived_here[:4])
                                           + (", ..." if len(archived_here) > 4 else ""), ARCHIVE_REL))


def _refuse_stray_rules(decisions, removals):
    """A standing rule travels only out of an agent, command or skill file adopt removes."""
    for path, d in sorted(decisions.items()):
        ruled = sorted(uid for uid, u in (d.get("units") or {}).items() if u.get("disposition") == "rule")
        if not ruled:
            continue
        if path not in removals:
            raise Refused("%s: unit %s is marked rule, but the file stays; a standing rule is carried only out of "
                          "a file adopt removes. Mark the unit person-data or keep, or confirm the file for removal"
                          % (path, ruled[0]))
        if removals[path]["kind"] not in ("agent", "command", "skill"):
            raise Refused("%s: unit %s is marked rule, but only an agent, command or skill file carries a "
                          "standing rule" % (path, ruled[0]))


def _assess_outcome(repo, tree, base, data, spec, plan, decisions, parity, refusals, notes, dry_run):
    """Record the leftovers in `notes` and assess the outcome. Returns (engine, outcome)."""
    notes["oldFormHits"] = old_form_hits(tree, notes["olds"])
    notes["refusals"] = [p.line() for p in refusals]
    # the outcome (design 8 AO): blocked or ready, every cause a row, the publish preconditions asked of `deploy.py --preflight`
    engine = compute_engine(Tree(repo, base), data, spec, decisions)
    snapshot = dict((q, tree.read(q)) for q in tree.paths() if q.startswith(("site/", "content/")) or q == ".site-studio/addresses.json")
    outcome = assess(repo, plan, parity, refusals, engine, report_issue.plugin_version(), reports_at(tree),
                     snapshot=snapshot, run_preflight=not dry_run)
    notes["outcome"] = outcome
    return engine, outcome


def _outcome_changes(tree, notes, outcome, changes):
    """The change lines for the outcome record and the conversions `converted_site_files` noted after the first pass."""
    if outcome["rows"]:
        tree.write(REPORTS_REL, report_issue.dump_reports(outcome["rows"]))
        changes.append("%s: %d cause(s) recorded (%s)" % (REPORTS_REL, len(outcome["rows"]),
                                                          ", ".join(sorted(set(r["state"] for r in outcome["rows"])))))
    for a, b in notes.get("archived") or []:
        changes.append("%s -> %s: archived (nothing builds or reads it; nothing is deleted)" % (a, b))
    for path in notes.get("drafted") or []:
        changes.append("%s: draft: true (the plugin would publish a piece your builder did not)" % path)
    for path, line, form in notes.get("blocks") or []:
        changes.append("%s:%d: %s block written as the plugin's container" % (path, line, form))
    for path, a, b in notes.get("references") or []:
        changes.append("%s: key %s -> %s" % (path, a, b))
    for old, new in notes.get("pageFiles") or []:
        changes.append("%s -> %s: renamed, content unchanged" % (old, new))
    for path, what in notes.get("homeKeys") or []:
        changes.append("%s: %s" % (path, what))
    for path, a, b in notes.get("resumeHeader") or []:
        changes.append("%s: front matter %s -> %s" % (path, a, b))
    for path, line, _a, _b in notes.get("navTokens") or []:
        changes.append("%s:%d: {{nav}} inside your own <nav> -> {{navLinks}}" % (path, line))
    for old, new in notes.get("personName") or []:
        changes.append("site.json name: %s -> %s (the name on your resume)" % (old, new))
    for old, new in notes.get("resumePdfName") or []:
        changes.append("%s -> %s: renamed to the name your builder publishes it under" % (old, new))
    for line in notes.get("settings") or []:
        changes.append("setting %s" % line)


def _write_handoff(tree, date, basis, base, removals, moved, kept, outcome):
    """Write the HANDOFF.md entry for the run so far. Returns (branch, handoff), `handoff(status)` being what `finish` rewrites it with."""
    # 5. HANDOFF.md entry: written with the status of the run so far; `finish` rewrites it when the run stops later
    branch = BRANCH_PREFIX + date
    handoff_old = tree.text("HANDOFF.md") if tree.exists("HANDOFF.md") else "# Handoff\n"

    def handoff(status):
        entry = ("\n## Adopt site-studio (%s)\n\n- Branch `%s`, from %s %s. `adopt.py apply` made it; nothing is merged by hand.\n"
                 "- Archived %d confirmed file(s) under archive/ (none is deleted); moved %d fact group(s) into the data files; kept %d "
                 "file(s) as customisations or by decision.\n"
                 % (date, branch, basis.label(), base[:7], len(removals), len(moved), len(kept)))
        return (handoff_old if handoff_old.endswith("\n") else handoff_old + "\n") + entry + "".join(status)
    if outcome["blocked"]:
        status = ["\n### Adopt run: blocked at step 2 of 5 (the checks before publishing)\n\n- %s.\n"
                  "- Nothing was published or pushed; the old builder is still the publisher.\n"
                  "- Next: settle what `adopt.py check` and `adopt.py report` list, delete this branch (`git branch -D %s`), and "
                  "run `adopt.py apply` again.\n" % ((outcome["lines"] or ["the parity verdict blocks"])[-1].strip(), branch)]
    else:
        status = ["- The run goes on to publish the site, wait for Pages, archive the old builder and push this branch to main; "
                  "an `Adopt run` entry below says how it ended.\n"]
    tree.write("HANDOFF.md", handoff(status))
    return branch, handoff


def prepare(repo, date, spec=None, dry_run=False):
    """Everything apply will commit, computed without writing anything. Raises Refused. `dry_run` previews with
    undecided files: a real apply refuses on an undecided DUPLICATE or AMBIGUOUS, a dry run keeps it and says so."""
    spec = spec or load_spec()
    basis, tree, data = preconditions(repo)
    base = basis.sha
    plan = _checked_plan(repo, base)
    infos = inventory(tree, spec)
    by_path = dict((i["path"], i) for i in infos)
    decisions = plan["files"]
    # the measured settings, and the dispositions the last `parity` measured (design 8: every class measured, every file accounted
    # for); what `parity` did not measure is not written
    settings = dict((k, v["value"]) for k, v in (plan.get("settings") or {}).items() if v["how"] in ("measured", "chosen"))
    measured = plan["parity"] or {}
    dispositions = (measured.get("accounting") or {}).get("dispositions") or None
    persons = dict((p, e["disposition"]) for p, e in decisions.items() if e.get("disposition"))
    kw = {"settings": settings, "dispositions": dispositions, "persons": persons, "hints": measured.get("hints") or None}
    rows, held, only = _decided_conversions(tree, data, plan, kw)
    refusals = _build_refusals(tree, data, plan, only, kw, dispositions)
    _refuse_undecided(tree, infos, decisions, plan, dry_run)
    parity = plan["parity"]
    removals, kept, facts, reasons, rule_units = _collect_removals(spec, tree, infos, decisions, plan, parity)
    # 2. data files first
    moved = write_facts(tree, facts, date)
    # 3. config second
    notes, record = _write_site(tree, data, plan, only, kw, held, rows, infos, base, parity)
    changes = _site_changes(tree, notes, record, plan)
    claude_old, claude_new = _carry_claude_and_gitignore(tree, rule_units, changes)
    settings, hook_list = _settings_and_hooks(tree, spec, removals, kept, by_path, changes)
    # 4. removals last
    _archive_removals(tree, removals, changes)
    _refuse_stray_rules(decisions, removals)
    post = set(tree.paths())
    dangling = dangling_hook_paths(settings, post)
    if dangling:
        raise Refused("a hook would still name %s, which is not in the new tree; apply finished nothing"
                      % ", ".join(sorted(set(p for _e, p in dangling))))
    engine, outcome = _assess_outcome(repo, tree, base, data, spec, plan, decisions, parity, refusals, notes, dry_run)
    _outcome_changes(tree, notes, outcome, changes)
    branch, handoff = _write_handoff(tree, date, basis, base, removals, moved, kept, outcome)
    message = build_message(date, basis, removals, reasons, spec, moved, changes, hook_list, kept, parity, notes)
    return {"base": base, "basis": basis, "tree": tree, "branch": branch, "message": message, "removals": removals,
            "kept": kept, "claude": (claude_old, claude_new), "hooks": hook_list, "moved": moved,
            "notes": notes, "problems": refusals, "engine": engine, "handoff": handoff, "date": date,
            "public_repo": data.get("publicRepo") if isinstance(data, dict) else None}


def reports_at(tree):
    """The reports record at the basis, or []."""
    if not tree.exists(REPORTS_REL):
        return []
    try:
        return report_issue.parse_reports(tree.text(REPORTS_REL))
    except report_issue.ReportsError:
        return []


def kind_change_line(tree, confirmed):
    """The commit line about the site kind (design 7.7): what the person confirmed, or, when nothing was
    confirmed and the tree does not look like a portfolio, that none was written and how to set one."""
    if confirmed:
        return "siteKind: %s (you confirmed it%s)" % (confirmed, "" if confirmed != "portfolio" else
                                                      "; it is the default, so site.json does not carry it")
    inferred, why = infer_kind(tree)
    if inferred == "portfolio":
        return ""
    return ("siteKind: not set, so this builds as a portfolio; it looks like a %s site (%s): run `adopt.py kind "
            "%s` and apply again to write it" % (inferred, why, inferred))


def build_message(date, basis, removals, reasons, spec, moved, changes, hook_list, kept, parity, notes):
    if basis.kind == "HEAD":
        src = "Converted from HEAD %s on %s." % (basis.sha[:7], basis.branch)
    else:
        src = "Converted from origin/main %s." % basis.sha[:7]
    L = ["site-studio adopt: retire this repo's local copies of the plugin's tools (%s)" % date, "",
         "%s A commit on a new branch; main is untouched until the run's last step, which pushes only after the publish "
         "succeeded." % src]
    if basis.ahead:
        L.append("Includes %d commit%s not on origin/main %s:" % (len(basis.ahead), "" if len(basis.ahead) == 1 else "s",
                                                                  basis.origin[:7]))
        L += ["- %s %s" % (s[:7], subj) for s, subj in basis.ahead]
    L.append("")
    L.append("Removed (file | counterpart | why):")
    if removals:
        for p in sorted(removals):
            L.append("- %s | %s | %s" % (p, counterpart_of(spec, removals[p]["capability"]), reasons[p]))
    else:
        L.append("- (nothing)")
    L += ["", "Moved data (from | to):"]
    L += ["- %s | %s" % (a, b) for a, b in moved] or ["- (nothing)"]
    L += ["", "Transformed config:"] + ["- %s" % c for c in changes]
    if notes.get("oldFormHits"):
        L += ["", "Your own script may depend on the old form (kept files that still hold a value adopt "
                  "replaced):"]
        L += ["- %s:%d: %s (the old %s)" % (p, n, github_url.redact(old), what)
              for p, n, old, what in notes["oldFormHits"]]
    L += ["", "Hooks removed or rewritten:"]
    L += (["- %s: `%s` -> %s" % (e, o, ("`%s`" % n) if n else "removed (the plugin's own hook does this job)")
           for e, o, n in hook_list] or ["- (none)"])
    L += ["", "Kept (customisations and decisions):"] + (["- %s | %s" % (p, why) for p, why in sorted(kept)] or ["- (none)"])
    if notes.get("redirectsLeft"):
        L += ["", "Meta-refresh pages left as hand pages (adopt could not turn them into redirects):"]
        L += ["- %s: %s" % t for t in notes["redirectsLeft"]]
    if notes["unknown"]:
        L += ["", "Tokens the plugin's build will refuse (fix by hand):"] + ["- %s: %s" % t for t in notes["unknown"]]
    if notes.get("held"):
        L += ["", "Conversions NOT made, because measuring them says they would change what a visitor sees or what "
                  "your own builder publishes (you decide):"]
        L += ["- [%s] %s: %s" % (r["label"], r["class"], r["reason"]) for r in notes["held"]]
    if notes.get("refusals"):
        L += ["", "Everything else the plugin's own build still refuses in this tree (`adopt.py check` lists it "
                  "too; apply wrote the branch, but it cannot be published until each is fixed):"]
        L += ["- %s" % r for r in notes["refusals"]]
    L += ["", "Parity: %s" % (("%s (%s)" % (parity["verdict"], parity.get("reason", ""))) if parity else "not run")]
    out = notes.get("outcome")
    if out:
        L += ["", "Outcome: %s%s" % ("blocked" if out["blocked"] else "every check passed",
                                       (" -- " + "; ".join(out["lines"])) if out["lines"] else
                                       ("" if out["blocked"] else "; the old builder still publishes until site-studio has "
                                        "published and archived it"))]
    return "\n".join(L) + "\n"


def do_apply(repo, date, dry_run=False, hooks=None):
    """The whole adoption in one process (owner rulings 26 and 27): steps 1 and 2 here (`prepare`), steps 3 to 5 in
    `adoption.finish.run`. Returns (text, tip sha or None, outcome) with outcome "completed" or "blocked" (`dry_run`: None).
    `hooks` are the tests' seams (`deploy`, `gh`, `dev_slug`); nothing on the command line reaches them."""
    if not dry_run:
        check_branch_free(repo, BRANCH_PREFIX + date)
    p = prepare(repo, date, dry_run=dry_run)
    out = []
    old, new = p["claude"]
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "CLAUDE.md (%s)" % p["basis"].label(), "CLAUDE.md (adopt)"))
    blocked = p["notes"]["outcome"]["blocked"]
    if dry_run:
        out.append("adopt dry run: would create %s from %s %s; nothing written, published or pushed."
                   % (p["branch"], p["basis"].label(), p["base"][:7]))
        out.append("Then, without --dry-run, apply would%s: publish the converted site through deploy.py (it asks you first), "
                   "wait for Pages to build it, archive %d old-builder file(s), and push the result to this repo's main."
                   % (" stop here, blocked" if blocked else "", len(p["engine"]["files"])))
        out.append(p["message"])
        out.append("CLAUDE.md diff:\n" + (diff or "(no change)"))
        return "\n".join(out), None, None
    commit = commit_object(repo, p["tree"], p["base"], p["message"])
    if blocked:
        set_branch(repo, p["branch"], commit)
        out.append("adopt blocked at step 2 of 5: nothing was published or pushed, and your old builder is still your "
                   "publisher. Branch %s (commit %s) holds the conversion for you to read: `git show %s`."
                   % (p["branch"], commit[:7], p["branch"]))
        out.append(p["message"])
        out.append("CLAUDE.md diff:\n" + (diff or "(no change)"))
        return "\n".join(out), commit, "blocked"
    res = finish.run(repo, p, commit, date, hooks)
    tip = res["tip"]
    if tip is None:                           # stopped before anything of the run could be kept: one commit says where
        printed, entry = finish.stop_lines(res["stop"], p["branch"])
        p["tree"].write("HANDOFF.md", p["handoff"]([entry]))
        tip = commit_object(repo, p["tree"], p["base"], p["message"] + "\n" + "\n".join(printed) + "\n")
        set_branch(repo, p["branch"], tip)
    out += res["lines"]
    out.append("Branch %s (commit %s): read it with `git show %s`." % (p["branch"], tip[:7], p["branch"]))
    out.append(p["message"])
    out.append("CLAUDE.md diff:\n" + (diff or "(no change)"))
    return "\n".join(out), tip, "completed" if res["completed"] else "blocked"
