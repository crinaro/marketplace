"""adoption.blockers -- every blocker as a cause id, from the plugin's own enumerations (design 8 RP, R4 rows 9, 10, 13, 16;
step 1.9r).

Part of the `adoption` package behind the entry point `adopt.py`. `reportcause.grammar` owns the grammar and the enumerations (`CAUSE_RE`,
`SHAPES`, `REFUSAL_CODE_IDS`, `cause_id`); this module maps what adopt MEASURES onto them, from structure only. Nothing here reads a
captured group, a path, a key, a token or a block name into an id: a value outside an enumeration becomes that enumeration's
`other` / `unclassified` member and is counted (Q1.8). Sources, and the id each gives:

  a `check` refusal no conversion clears      refusal/<code>        `REFUSAL_CODES`, matched on the problem's plugin-worded text
                                                                    (0.3.1's `Problem` has no kind field, R4 row 9)
  a P2 difference a visitor can see           parity/<kind>/<row>   `parity_classes.kind()` of the hunk; `<row>` the construct
                                                                    of the one conversion touching the page, else `unattributed`
  a file the old builder uses, no landing     no-landing/<family>/<area>
  a group the counterfactual could not split  unobservable/<family>
  a piece the build requires, archived        draft/unsupported/<unit>
  an opt-in or held TEMPLATE class            conversion/<class>
  the kept builder fails on a class           builder/fails/<class> (or `combined`)
  a builder of another language               builder/unmeasurable/<language>; a workflow value that cannot be reproduced,
                                              builder/invocation-differs
  a look construct derive could not map       look/unmapped/<construct>, look/ambiguous/<construct>
  the preflight                               publish/gate/<family>, publish/address, publish/pages-workflow,
                                              publish/serves-dev-repo; `publish/other-publisher` from a `keep` on a publisher
  the environment                             env/<cause>: printed with their fix, never filed

`classify(cid)` says plugin / person / environment (`grammar.cause_kind`); only a plugin cause is ever filed.
"""

import re

import report_issue
from reportcause import grammar

from adoption.problems import analyse_problems

# (code, pattern on the problem's message). A closed table, first match wins; it only asks WHETHER a pattern matched, never what
# it captured. A problem no row matches is `refusal/unclassified`.
REFUSAL_CODES = (
    ("unknown-reference-key", re.compile(r"^content/references/[^/]+/reference\.json(?::\d+)?: unknown key '")),
    ("unknown-page-key", re.compile(r"unknown front matter key '[^']*' \(allowed: ")),
    ("unknown-token", re.compile(r": unknown token \{\{")),
    ("unknown-piece-key", re.compile(r"front matter key '[^']*' is not published; it is not a built-in key")),
    ("piece-both", re.compile(r" holds both work\.md and index\.md$")),
    ("redirect-collision", re.compile(r"^site\.json redirects '[^']*' and '[^']*' are the same address")),
    ("held-choice", re.compile(r" is chosen, but your own builder FAILS on the tree it makes")),
)


# 0.3.1 F1: a stray `.md` or sub-folder in a piece folder. It is a FILE: the file accounting disposes of it (archived, or `no-landing`
# when the old builder uses it), so once FA has run it is no refusal and no cause (R4 row 16 (a)).
STRAY_FILE = re.compile(r": this (?:file|folder) is not published(?: \(\d+ files? in it\))?; a piece is one page")


def is_stray_warning(problem):
    return bool(STRAY_FILE.search(getattr(problem, "message", problem)))


def refusal_code(problem):
    """The `refusal/<code>` member for one `siteconfig.Problem` (or its message), from the closed table."""
    message = getattr(problem, "message", problem)
    for code, rx in REFUSAL_CODES:
        if rx.search(message):
            return code
    return "unclassified"


def refusal_occurrences(problems):
    """[{"id", "row"}]: one occurrence per refusal that is a CAUSE. A mechanical fix is no cause; a consequence that FOLLOWS from
    another problem (a redirect to a portfolio the build refuses) takes its cause's id and is not counted again (R4 row 9)."""
    out = []
    for group, follows in analyse_problems(list(problems))["items"]:
        if follows is not None:
            continue
        for p in group:
            if getattr(p, "mechanical", False) or is_stray_warning(p):
                continue
            out.append({"id": grammar.cause_id("refusal", refusal_code(p)), "row": None})
    return out


def classify(cid):
    return grammar.cause_kind(cid)


def parity_occurrences(differences, kinds, row="unattributed"):
    """`kinds` is a Counter-like {parity kind label: how many}; every visible difference is counted under its kind. A label
    outside the closed set cannot be built (`grammar.cause_id` maps an unknown element or attribute to `other`)."""
    out = []
    for kind, n in sorted(kinds.items()):
        for _ in range(n):
            out.append({"id": grammar.cause_id("parity", kind, row=row), "row": None if row == "unattributed" else row})
    return out


def look_occurrences(look_status):
    """`look/unmapped/<construct>` and `look/ambiguous/<construct>` for each construct the derived look could not map (`look_status` is
    {construct id: mapped|unmapped|ambiguous|not reached}, what `adoption.choose` read from `look.derive_look`): one occurrence per
    construct, the construct its row. A construct outside `looks.CONSTRUCTS` cannot be named and is not a cause, and `not reached`
    (a page the derive never read) is no finding about the construct. Only a verdict DIFFERENT raises them (`outcome.assess`): a
    construct nothing in the pages differs by is no blocker."""
    out = []
    known = grammar.constructs()
    for cid, status in sorted((look_status or {}).items()):
        if status in ("unmapped", "ambiguous") and cid in known:
            out.append({"id": grammar.cause_id("look", status, cid), "row": cid})
    return out


def accounting_occurrences(accounting, family_of, area_of):
    """no-landing and unobservable causes from the file accounting, by family and area; never a path. A path of an unsettled group
    is a cause only where it stayed `undisposed`: one the person kept, or a late file that blocks nothing, is not (4.3)."""
    out = []
    disp = accounting.get("dispositions") or {}
    for path, (d, _why) in sorted(disp.items()):
        if d == "no-landing":
            out.append({"id": grammar.cause_id("no-landing", family_of(path), area_of(path)), "row": None})
    for group in accounting.get("unsettled") or []:
        for path in group:
            if disp.get(path, ("undisposed",))[0] == "undisposed":
                out.append({"id": grammar.cause_id("unobservable", family_of(path)), "row": None})
    return out


def engine_occurrences(engine_causes, cause=None):
    """`builder/unmeasurable/<language>` and `builder/invocation-differs` (from parity's `cause`), and the person causes the
    engine computation found (`publish/serves-dev-repo`, `publish/other-publisher`)."""
    out = [{"id": grammar.cause_id(*group_key), "row": None} for group_key in engine_causes]
    if cause:
        if cause.startswith("builder/unmeasurable/"):
            out.append({"id": grammar.cause_id("builder", "unmeasurable", cause.split("/")[2]), "row": None})
        elif cause == "builder/invocation-differs":
            out.append({"id": grammar.cause_id("builder", "invocation-differs"), "row": None})
        elif cause.startswith("env/"):
            out.append({"id": grammar.cause_id(*cause.split("/")), "row": None})
        elif cause == "unobservable":
            pass
    return out


def preflight_occurrences(causes):
    """The preflight's JSON causes (`deploy.py --preflight`): a `blocks` row is a cause (publish/gate/<family>, publish/address,
    publish/pages-workflow, publish/serves-dev-repo, env/public-target); a `not-checked` row is NOT a blocker."""
    out, notes = [], []
    for c in causes:
        if c["state"] == "not-checked":
            notes.append(c["detail"])
            continue
        if c["cause"] == "publish/staging":      # printed and blocking, never a cause: no new id, and not the plugin's to file (dev 1068)
            continue
        parts = c["cause"].split("/")
        try:
            out.append({"id": grammar.cause_id(*parts), "row": None})
        except grammar.CauseError:
            out.append({"id": grammar.cause_id("refusal", "unclassified"), "row": None})
    return out, notes


def grouped(occurrences):
    """ONE cause per id with its count and rows (`report_issue.group_occurrences`)."""
    return report_issue.group_occurrences(occurrences)


def summary_line(causes, own=0):
    """The line `apply` and `remeasure` print when blocked. `own` counts the groups of publish findings that are the site's, the person's or
    adopt's to fix (dev 1068, design 1.3): they block like a person cause, are printed above with their fix and are never filed, so a block
    made of them alone says "each one only you can resolve", as a person cause does."""
    plugin = [c for c in causes if classify(c["id"]) == "plugin"]
    return "blocked: %d cause(s); run `adopt.py report` to read them" % (len(causes) + own) if plugin else \
        "blocked: %d cause(s), each one only you can resolve (printed above with its fix)" % (len(causes) + own)
