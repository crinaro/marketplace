"""adoption.plan -- the plan file (`.site-studio/adopt-plan.json`): a strict parser, carrying a decision across a moved basis.

Part of the `adoption` package behind the entry point `adopt.py`. Documentation that was in `adopt.py`'s docstring about this module's code:

THE PLAN (`.site-studio/adopt-plan.json`, a strict parser) holds only the person's decisions: per
file, remove or keep; which residual units are person data or kept behaviour; whether the facts
were reviewed; the paper size; the parity result. `apply` re-classifies from the tree, so a plan
cannot assert a class. Order inside `apply`: DATA FILES FIRST, CONFIG SECOND, REMOVALS LAST, and
it refuses (changing nothing) while any file proposed for removal has no decision, any removal's
facts are unreviewed, any residual unit is undispositioned or marked keep, a builder's parity is
not EQUAL or ACCEPTED, or a hook would be left naming a file that is not in the new tree.
"""

import json
import os
import re

from configschema import configkeys  # noqa: E402

from adoption.base import FACT_KINDS, FOLDER_CHOICES, PLAN_REL, PlanError, Refused, UNIT_DISPOSITIONS, gitt
from adoption.spec import OPT_IN_CLASSES
from adoption.tree import Tree
from adoption.tokens import detect_resume
from adoption.parity import parity_basis

PLAN_SCHEMA = 1                    # what an empty plan, and a plan with nothing that needs 2, is written at
PLAN_SCHEMA_MAX = 2                # schema 2 adds `settings`, `files[path].disposition` and the verdict MARKUP-ONLY
SETTING_HOWS = ("measured", "chosen", "not measured")
FILE_DISPOSITIONS = ("archive", "draft", "keep", "engine")      # the person's choice for a file (design 8 FA rule 4)
PLAN_VERDICTS = ("EQUAL", "DIFFERENT", "UNVERIFIED", "ACCEPTED", "NOT APPLICABLE")


def empty_plan(base):
    return {"schema": PLAN_SCHEMA, "base": base, "files": {}, "facts": [], "paper": None, "parity": None,
            "folders": {}, "siteKind": None, "convert": [], "settings": {}}


def parse_plan(text):
    try:
        d = json.loads(text)
    except ValueError as e:
        raise PlanError("adopt plan is not valid JSON: %s; edit or delete .site-studio/adopt-plan.json (deleted, it starts "
                        "again), then run `adopt.py check`" % e)
    if not isinstance(d, dict):
        raise PlanError("adopt plan: the top level must be an object")
    two = d.get("schema") == 2 and not isinstance(d.get("schema"), bool)
    # an empty `settings` is what an in-memory plan carries (save_plan does not write it at schema 1); a schema-1 file
    # that holds a setting is refused as an unknown key, as an older install refuses it
    allowed = ("schema", "base", "files", "facts", "paper", "parity", "folders", "siteKind", "convert") + (
        ("settings",) if two or d.get("settings") == {} else ())
    for k in d:
        if k not in allowed:
            raise PlanError("adopt plan: unknown key '%s'; edit or delete .site-studio/adopt-plan.json (deleted, it starts "
                            "again), then run `adopt.py check`" % k)
    for k in allowed:
        if k not in d and k not in ("folders", "siteKind", "convert", "settings"):
            raise PlanError("adopt plan: '%s' is missing; edit or delete .site-studio/adopt-plan.json (deleted, it starts "
                            "again), then run `adopt.py check`" % k)
    d.setdefault("folders", {})
    d.setdefault("settings", {})
    d.setdefault("siteKind", None)
    d.setdefault("convert", [])
    if not isinstance(d["convert"], list) or any(c not in OPT_IN_CLASSES for c in d["convert"]):
        raise PlanError("adopt plan: 'convert' must be a list of conversions you may choose (%s)"
                        % ", ".join(OPT_IN_CLASSES))
    if d["siteKind"] not in (None,) + configkeys.SITE_KINDS:
        raise PlanError("adopt plan: 'siteKind' must be null or one of %s" % ", ".join(configkeys.SITE_KINDS))
    if not isinstance(d["folders"], dict):
        raise PlanError("adopt plan: 'folders' must be an object")
    for name, choice in d["folders"].items():
        if not re.match(r"^[^/\s]+$", name) or choice not in FOLDER_CHOICES:
            raise PlanError("adopt plan: folders[%r] must name one folder under content/ and be %s"
                            % (name, " or ".join("'%s'" % c for c in FOLDER_CHOICES)))
    if isinstance(d["schema"], bool) or d["schema"] not in (1, PLAN_SCHEMA_MAX):
        raise PlanError("adopt plan: schema %r is not understood (this adopt reads 1 and %d); update site-studio if the "
                        "plan came from a newer one, or delete .site-studio/adopt-plan.json and run `adopt.py check`"
                        % (d["schema"], PLAN_SCHEMA_MAX))
    if not isinstance(d["settings"], dict):
        raise PlanError("adopt plan: 'settings' must be an object")
    for name, row in d["settings"].items():
        if (not isinstance(row, dict) or set(row) != {"value", "how", "reason"} or row["how"] not in SETTING_HOWS
                or not isinstance(row["reason"], str) or not re.match(r"^[A-Za-z][A-Za-z0-9.]*$", str(name))):
            raise PlanError("adopt plan: settings[%r] must hold exactly value, how (%s) and reason (text)"
                            % (name, ", ".join(SETTING_HOWS)))
    if not isinstance(d["base"], str) or not re.match(r"^[0-9a-f]{40}$", d["base"]):
        raise PlanError("adopt plan: 'base' must be a 40-hex commit")
    if not isinstance(d["files"], dict):
        raise PlanError("adopt plan: 'files' must be an object")
    for path, f in d["files"].items():
        if not isinstance(f, dict):
            raise PlanError("adopt plan: files[%r] must be an object" % path)
        for k in f:
            if k not in ("removal", "as", "reviewed", "units") + (("disposition",) if two else ()):
                raise PlanError("adopt plan: unknown key files[%r].%s; edit or delete .site-studio/adopt-plan.json (deleted, it "
                                "starts again), then run `adopt.py check`" % (path, k))
        if f.get("removal") not in (None, "confirm", "keep"):
            raise PlanError("adopt plan: files[%r].removal must be null, 'confirm' or 'keep'" % path)
        if f.get("disposition", "archive") not in FILE_DISPOSITIONS:
            raise PlanError("adopt plan: files[%r].disposition must be one of %s" % (path, ", ".join(FILE_DISPOSITIONS)))
        if not isinstance(f.get("reviewed", False), bool):
            raise PlanError("adopt plan: files[%r].reviewed must be true or false" % path)
        if not isinstance(f.get("units", {}), dict):
            raise PlanError("adopt plan: files[%r].units must be an object" % path)
        for uid, u in f.get("units", {}).items():
            if not isinstance(u, dict) or u.get("disposition") not in UNIT_DISPOSITIONS:
                raise PlanError("adopt plan: files[%r].units[%r].disposition must be 'person-data', 'keep' or 'rule'"
                                % (path, uid))
            if u["disposition"] == "person-data" and u.get("kind") not in FACT_KINDS:
                raise PlanError("adopt plan: files[%r].units[%r].kind must be one of %s"
                                % (path, uid, ", ".join(FACT_KINDS)))
    if not isinstance(d["facts"], list):
        raise PlanError("adopt plan: 'facts' must be a list")
    for fa in d["facts"]:
        if (not isinstance(fa, dict) or fa.get("kind") not in FACT_KINDS or not isinstance(fa.get("text"), str)
                or not fa["text"].strip() or not isinstance(fa.get("source"), str)):
            raise PlanError("adopt plan: every fact needs a source, a kind (%s) and text" % ", ".join(FACT_KINDS))
    if d["paper"] not in (None, "Letter", "A4"):
        raise PlanError("adopt plan: 'paper' must be null, \"Letter\" or \"A4\"")
    if d["parity"] is not None:
        if not isinstance(d["parity"], dict) or d["parity"].get("verdict") not in PLAN_VERDICTS + (
                ("MARKUP-ONLY",) if two else ()):
            raise PlanError("adopt plan: 'parity.verdict' is not a known verdict; delete .site-studio/adopt-plan.json and run "
                            "`adopt.py parity` to measure again")
    return d


def plan_path(repo):
    return os.path.join(repo, PLAN_REL)


def load_plan(repo):
    try:
        with open(plan_path(repo), "r", encoding="utf-8") as fh:
            return parse_plan(fh.read())
    except OSError:
        return None


def lowest_schema(plan):
    """The lowest plan schema that holds `plan` (design 3.5: schema 2 is written only when something needs it, so an older
    install reads every plan that has nothing a schema-1 plan cannot hold)."""
    needs = (bool(plan.get("settings")) or any("disposition" in f for f in plan["files"].values())
             or (plan.get("parity") or {}).get("verdict") == "MARKUP-ONLY")
    return PLAN_SCHEMA_MAX if needs else PLAN_SCHEMA


def save_plan(repo, plan):
    plan = dict(plan)
    plan["schema"] = lowest_schema(plan)
    if not plan.get("settings"):
        plan.pop("settings", None)
    parse_plan(json.dumps(plan))
    p = plan_path(repo)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, p)


def carry_plan(repo, old, base):
    """(the plan for `base`, [what was cleared, each by name]) when the parity basis moved since `old` was made (dev
    #887, D2). A decision is KEPT when the path it is about exists on the new basis and its bytes are the same as on
    the old one (a file's removal, review and unit decisions; a fact, by the file it came from; a folder's
    `source`/`portfolio`, by every file under it; the paper size, by the resume PDF it was asked about). What is
    about the whole repo and no path (`convert`, `siteKind`) is kept. Everything else is CLEARED and returned by
    name for the caller to print: the parity result always (it measured another tree), and a decision about a path
    that changed or is gone. The old basis commit not being in this repo means nothing can be compared, so every
    decision is cleared and said to be. The stored shape is the same: only values move between the same keys."""
    new = empty_plan(base)
    new["convert"], new["siteKind"] = list(old.get("convert") or []), old.get("siteKind")
    cleared = []
    # a setting the person CHOSE is about the whole repo and no path, so it is kept like `convert`; a measured one (or one
    # that was not measured) described the tree on the old basis, so it is cleared with the parity result and named (R4 row 19)
    for name, row in sorted((old.get("settings") or {}).items()):
        if row["how"] == "chosen":
            new["settings"][name] = row
        else:
            cleared.append("the %s setting %s (%s on %s; run `adopt.py parity` again)"
                           % (row["how"], name, row["how"], old["base"][:7]))
    try:
        was = Tree(repo, old["base"]).entries
    except Refused:
        was = None
    now = Tree(repo, base).entries

    def same(path):
        return was is not None and path in now and was.get(path) == now[path]

    def same_under(prefix):
        a = dict((p, e) for p, e in (was or {}).items() if p.startswith(prefix))
        b = dict((p, e) for p, e in now.items() if p.startswith(prefix))
        return was is not None and bool(b) and a == b
    for path, d in sorted(old["files"].items()):
        what = [w for w, on in (("removal %s" % d.get("removal"), d.get("removal")), ("--as %s" % d.get("as"), d.get("as")),
                                ("reviewed", d.get("reviewed")), ("%d unit decision(s)" % len(d.get("units") or {}),
                                                                 d.get("units")),
                                ("disposition %s" % d.get("disposition"), d.get("disposition"))) if on]
        if not what:
            continue
        if same(path):
            new["files"][path] = d
        else:
            cleared.append("%s (%s)" % (path, ", ".join(what)))
    for fa in old["facts"]:
        if same(fa["source"]):
            new["facts"].append(fa)
        else:
            cleared.append("the %s fact from %s" % (fa["kind"], fa["source"]))
    for name, choice in sorted(old["folders"].items()):
        if same_under("content/%s/" % name):
            new["folders"][name] = choice
        else:
            cleared.append("content/%s -> %s" % (name, choice))
    if old["paper"] is not None:
        pdf = detect_resume(Tree(repo, base))["pdf"]
        if pdf and same(pdf):
            new["paper"] = old["paper"]
        else:
            cleared.append("the paper size %s (the resume PDF changed or is gone)" % old["paper"])
    if old["parity"] is not None:
        cleared.append("the parity result %s (measured on %s; run `adopt.py parity` again)"
                       % (old["parity"].get("verdict"), old["base"][:7]))
    if was is None and cleared:
        cleared.append("(the old basis %s is not in this repo, so nothing could be compared)" % old["base"][:7])
    return new, cleared


def cleared_line(old_base, base, cleared):
    return ("%d decision(s) cleared because the basis moved (%s -> %s): %s"
            % (len([c for c in cleared if not c.startswith("(")]), old_base[:7], base[:7], "; ".join(cleared)))


def _plan_for(repo, base, say=None):
    """The plan for `base`. A plan made for another basis is CARRIED (`carry_plan`), not dropped, and `say` (when
    given) is called with the one line naming every decision that was cleared."""
    plan = load_plan(repo)
    if plan is None:
        return empty_plan(base)
    if plan["base"] != base:
        old_base = plan["base"]
        plan, cleared = carry_plan(repo, plan, base)
        if cleared and say:
            say(cleared_line(old_base, base, cleared))
    return plan


def _need_plan(repo, base):
    plan = _plan_for(repo, base)
    return plan


def _current_base(repo):
    """The parity basis as of the last fetch (the plan commands make no network call): HEAD when it is a
    fast-forward of origin/main as last fetched, else origin/main. A commit made after the inventory
    changes it, which is the point: the plan was made for another tree."""
    if not gitt(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main", check=False):
        raise Refused("origin/main does not resolve; run `adopt.py inventory` first")
    return parity_basis(repo).sha


def _set(repo, path, fn):
    tree = None
    plan = _plan_for(repo, _current_base(repo), print)
    entry = plan["files"].get(path)
    if entry is None:
        raise Refused("%s is not in the plan; run `adopt.py inventory` first" % path)
    fn(plan, entry, tree)
    save_plan(repo, plan)
