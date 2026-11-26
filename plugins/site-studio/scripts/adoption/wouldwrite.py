"""adoption.wouldwrite -- the one converted tree: what `apply` would write, computed once for every stage that asks about it (dev 1068, design 1.1).

Part of the `adoption` package behind the entry point `adopt.py`. `check`, `inventory`, `parity` (after it has chosen its settings), `apply
--dry-run` and `apply` used to judge three different trees: `check` was not given the file dispositions `apply` is, `check` kept a file the
person confirmed for removal, and `prepare` had its own order of work. `conversion` is what `apply.prepare` computes before it writes (the
measured settings through `referencepropose.taken`, the file dispositions, the persons, the hints, the folder decisions still open, the
classes held back, the decisions that remove a file and the hooks that keep one), and `snapshot` is the converted files under `site/` and
`content/` plus the committed `.site-studio/addresses.json`, as `{path: bytes}`: the input of the publish checks (`publishchecks`). `prepare`
then adds only what no build reads (`CLAUDE.md`, `.claude/`, `HANDOFF.md`, the archived copies); it hands the tree it made to `unlisted`, and a
file `apply` writes under those prefixes that the snapshot lacks refuses the run before anything is committed ("a plugin fault"), so the list
the person was shown is never shorter than the commit.

`mode` is `apply` (strict: what `prepare` always did), `dry` (as `apply`, but an undecided file is kept, as the dry run always did) or
`check` (lenient: a decision still missing, or a chosen conversion that breaks the kept builder, does not raise; `Conversion.pending` says what
was assumed, and `check` prints it). The functions moved here from `apply.py` keep their bodies: `merge_settings`, `decided_conversions`,
`build_refusals`, `refuse_undecided`, `collect_removals` and the hook planning of `_settings_and_hooks`.
"""

import json
import os
import posixpath

from adoption import referencepropose
from adoption.accounting import open_folders
from adoption.base import NeedsAnswer, PLUGIN, Refused
from adoption.blockers import is_stray_warning
from adoption.classify import _fmt_pct, classify_text, shadow_suffix
from adoption.convert import _snapshot, converted_site_files
from adoption.hookpaths import process_hooks
from adoption.parity import decide_conversions, template_fingerprint
from adoption.problems import accept_problems, accept_warnings, broken_chosen
from adoption.spec import CONVERSION_CLASSES, load_spec
from adoption.tokens import detect_resume
from adoption.tree import TreeFiles, inventory

STARTER_SETTINGS = os.path.join(PLUGIN, "templates", "starter", "dot-claude", "settings.json")
ADDRESSES_REL = ".site-studio/addresses.json"
OURS = ("site/", "content/")


def is_ours(path):
    """True for a path the publish builds from: `site/`, `content/` and the address record the guard reads."""
    return path.startswith(OURS) or path == ADDRESSES_REL


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


def decided_conversions(tree, data, plan, kw, strict=True):
    """Which classes of conversion are made. Returns (rows, held, only); raises Refused when a chosen conversion breaks the kept builder
    (`strict`; `check` lists that as a problem of its own, `held_problems`, so it asks with `strict` False)."""
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
    if broken and strict:
        raise Refused("%s is chosen, but your own builder FAILS on the tree it makes (%s) and parity is %s: apply will not "
                      "write a conversion that breaks the builder that stays your publisher. `adopt.py convert %s --keep` "
                      "leaves it as written (then `adopt.py parity` measures the tree without it); or fix the builder, run `adopt.py parity` again, and accept it once parity "
                      "is EQUAL or ACCEPTED" % (broken[0]["class"], broken[0]["failure"],
                                                (plan["parity"] or {}).get("verdict", "not run"), broken[0]["class"]))
    return rows, held, only


def build_refusals(tree, data, plan, only, kw, dispositions):
    """What the plugin's own build refuses in the tree adopt would write, as problems."""
    # what the plugin's own build refuses in the tree adopt would write (before anything is written)
    refusals, acc = accept_problems(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), only, **kw)
    refusals = refusals + accept_warnings(acc)
    if dispositions:             # a stray file is disposed by the file accounting, never also a refusal (design R4 row 16 (a))
        refusals = [p for p in refusals if not is_stray_warning(p)]
    return refusals


def refuse_undecided(tree, infos, decisions, plan, dry_run):
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


def collect_removals(spec, tree, infos, decisions, plan, parity):
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
                                  "disposition with `adopt.py unit %s %s person-data|keep|rule|covered`"
                                  % (i["path"], u["id"], u["text"].split("\n")[0][:60], i["path"], u["id"]))
                if ud["disposition"] == "keep":
                    raise Refused("%s: unit %s is marked keep, so the file stays; run `adopt.py confirm %s --keep`"
                                  % (i["path"], u["id"], i["path"]))
                if ud["disposition"] == "rule":
                    rule_units.append({"source": i["path"], "id": u["id"], "text": u["text"]})
                    continue
                if ud["disposition"] == "covered":                # "the plugin covers this; drop it": no fact, no rule; `apply.covered_units` lists it (dev 1068, S6)
                    continue
                unit_facts.append({"source": i["path"], "kind": ud["kind"], "text": u["text"], "name": ud.get("name")})
        else:
            if d.get("covered") and spec.caps[eff["capability"]].get("needsParity"):
                raise Refused("%s is a local builder file: it is dropped only after parity (run `adopt.py parity`), never by `confirm --covered`; "
                              "run `adopt.py confirm %s` instead" % (i["path"], i["path"]))
            if spec.caps[eff["capability"]].get("needsParity"):
                if not parity or parity["verdict"] not in ("EQUAL", "MARKUP-ONLY", "ACCEPTED"):
                    raise Refused("%s is a local builder file and parity is %s: it stays (run `adopt.py parity`)"
                                  % (i["path"], (parity or {}).get("verdict", "not run")))
            elif eff["class"] == "PARTIAL" and not d.get("covered"):
                raise Refused("%s is PARTIAL (residual %s) and nothing says its extra behaviour is safe to drop: "
                              "run `adopt.py confirm %s --keep`, or `adopt.py confirm %s --covered` if the plugin covers what it adds"
                              % (i["path"], _fmt_pct(eff["residual"]), i["path"], i["path"]))
        removals[i["path"]] = eff
        reasons[i["path"]] = ("matched by what it does: %s (score %s, residual %s; signals: %s)"
                              % (eff["capability"], _fmt_pct(eff["score"]), _fmt_pct(eff["residual"]),
                                 ", ".join(eff["signals"])))
    for fa in plan["facts"]:
        if fa["source"] in removals:
            facts.append(fa)
    facts = unit_facts + facts
    return removals, kept, facts, reasons, rule_units


def hook_plan(tree, spec, removals, kept, by_path):
    """The person's settings with the plugin's registration merged in and the hooks that name a removed file handled; a removal a hook
    still needs is dropped from `removals` and listed in `kept`. Returns (settings, hook_list); writes nothing."""
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
    return trial, hook_list


class Conversion(object):
    """What `conversion` found: see the module docstring. `pending` is None, or the refusal a `check` ran past."""

    def __init__(self):
        self.pending = None
        self.removals, self.kept, self.facts, self.reasons, self.rule_units = {}, [], [], {}, []
        self.hook_settings, self.hook_list = None, []


def conversion(tree, data, plan, spec=None, mode="apply"):
    """The conversion of `tree` (the basis) under `plan`, as `apply.prepare` always computed it before it wrote. Raises Refused or NeedsAnswer
    in `apply` and `dry` mode; in `check` mode a decision still missing is `Conversion.pending` and the removals are then none."""
    strict = mode != "check"
    c = Conversion()
    c.spec = spec or load_spec()
    c.tree, c.data, c.mode = tree, data, mode
    c.infos, c.by_path = [], {}
    c.decisions = plan["files"]
    # the measured settings, and the dispositions the last `parity` measured (design 8: every class measured, every file accounted
    # for); what `parity` did not measure is not written
    c.settings = referencepropose.taken(plan.get("settings"), plan["parity"])      # dev 1061: a measured layout waits until site-studio publishes
    measured = plan["parity"] or {}
    c.dispositions = (measured.get("accounting") or {}).get("dispositions") or None
    c.plan = plan = dict(plan, folders=open_folders(plan["folders"], tree.paths(), c.dispositions))      # F1: the archive already settled these
    persons = dict((p, e["disposition"]) for p, e in c.decisions.items() if e.get("disposition"))
    c.kw = {"settings": c.settings, "dispositions": c.dispositions, "persons": persons, "hints": measured.get("hints") or None}
    c.rows, c.held, c.only = decided_conversions(tree, data, plan, c.kw, strict)
    if not strict and not any((e or {}).get("removal") == "confirm" for e in c.decisions.values()):
        return c                      # `check` with no file confirmed for removal: the snapshot is the converted files alone, so nothing is classified
    c.infos = inventory(tree, c.spec)
    c.by_path = dict((i["path"], i) for i in c.infos)
    if strict:
        refuse_undecided(tree, c.infos, c.decisions, plan, mode == "dry")
    try:
        c.removals, c.kept, c.facts, c.reasons, c.rule_units = collect_removals(c.spec, tree, c.infos, c.decisions, plan, plan["parity"])
        c.hook_settings, c.hook_list = hook_plan(tree, c.spec, c.removals, c.kept, c.by_path)
    except Refused as e:
        if strict:
            raise
        c.pending = str(e)
        c.removals, c.kept, c.facts, c.reasons, c.rule_units = {}, [], [], {}, []
    return c


class Snapshot(object):
    """The converted files the publish builds from, `{path: bytes}`, and the notes `converted_site_files` made."""

    def __init__(self, files, notes, gone):
        self.files, self.notes, self.gone = files, notes, gone


def removed_by_decisions(removals, paths):
    """The paths the decisions to remove take out of the tree (`apply._archive_removals`): the file, a skill's whole folder, a
    `package.json`'s lock beside it."""
    paths, gone = set(paths), set()
    for p, eff in removals.items():
        if eff["kind"] == "skill":
            gone.update(q for q in paths if q.startswith(posixpath.dirname(p) + "/"))
        else:
            gone.add(p)
        if posixpath.basename(p) == "package.json":
            lock = posixpath.dirname(p) + "/package-lock.json"
            if lock in paths:
                gone.add(lock)
    return gone


def held_refusal(e, held):
    """`e`, the refusal `converted_site_files` raised, worded for a conversion held back: a site.json that is not valid because the class it needs
    is not made says which class, and what to settle first."""
    if held and str(e).startswith("the converted site.json is not valid"):
        return Refused("%s; it needs a conversion that is held back (%s), so the plugin's build cannot read it yet: settle "
                       "that first (`adopt.py check` says why)" % (e, ", ".join(sorted(held))))
    return e


def snapshot(conv):
    """The files `apply` would leave under `site/` and `content/`, and the committed `.site-studio/addresses.json`: the converted site files
    over the basis, less what the file accounting moves and what a confirmed removal archives. Read-only."""
    tree, plan = conv.tree, conv.plan
    try:
        files, notes = converted_site_files(tree, conv.data, plan["paper"], plan["folders"], plan.get("siteKind"), conv.only, **conv.kw)
    except Refused as e:
        raise held_refusal(e, conv.held)
    gone = removed_by_decisions(conv.removals, tree.paths()) | set(notes["removed"])
    seen = TreeFiles(tree, files, gone)
    out = _snapshot(tree, seen)
    if tree.exists(ADDRESSES_REL) and ADDRESSES_REL not in gone:
        out[ADDRESSES_REL] = tree.read(ADDRESSES_REL)
    return Snapshot(out, notes, gone)


def unlisted(tree, snap):
    """[path]: what `apply` is about to commit under `site/`, `content/` and `.site-studio/addresses.json` that the snapshot the checks ran on
    does not hold, or holds as other bytes. `tree` is the `adoption.tree.Tree` after `prepare` wrote it. A path the commit leaves as the basis
    has the basis's bytes in the snapshot by construction, so only the paths the run wrote are compared by bytes."""
    now = set(p for p in tree.paths() if is_ours(p))
    bad = set(now) ^ set(snap)
    bad.update(p for p in now & set(snap) if p in tree.writes and tree.writes[p] != snap[p])
    return sorted(bad)
