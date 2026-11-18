"""adoption.fileacct -- run the file accounting: build the pass-1 tree, attribute, run the counterfactual, dispose (design 8 FA).

Part of the `adoption` package behind the entry point `adopt.py`. `accounting` holds the rules and `usage` the measures; this module
runs them over a real tree and a real old builder, in the order the design states (Q1.13 (2), Q2.3):

  1. the engine set E is computed first, from the inventory and the workflows alone (`engine`)
  2. every conversion except `archive` and `draft` is applied in memory: the PASS-1 TREE
  3. the plugin builds the pass-1 tree (its page-to-source map, its output); the old builder has run on the UNCONVERTED tree
     (`local`, its output). A work-in-progress piece the plugin refuses (a required key it lacks) is tried again with `draft: true`
     on exactly the pieces the build named, so the build can still say what it would publish
  4. every file gets its disposition (`accounting.account`); the files attribution leaves open go to the counterfactual
  5. `archive` and `draft` are then applied (by `adoption.apply`) and measured like every class: P2 over the whole result

Evidence is keyed by the path AT THE BASIS (what `git ls-files` lists). A renamed file (`work.md` -> `index.md`, `home.md` ->
`index.md`) is looked up under its converted name. Without a measurement (no node, a builder that fails) nothing here runs and
every file but those rules 1 to 4 settle stays where it is, undisposed.
"""

import posixpath
import re

import build as site_build  # noqa: E402

from adoption.accounting import account, counts, piece_folder_of
from adoption.base import Refused
from adoption.dispose import conv_name
from adoption.convert import _give_resume_sidecar, _snapshot, converted_site_files
from adoption.parity import compare_builds
from adoption.problems import check_only
from adoption.tree import TreeFiles
from adoption.usage import counterfactual, old_attribution, plugin_attribution

PASS_ONE_SKIP = ("archive", "draft")
_PIECE = re.compile(r"^(content/[^/]+/[^/]+)/index\.md$")
_MISSING_KEY = re.compile(r"front matter '[^']*' is required\b")        # what a piece still being written plausibly lacks (both the build's wordings)


def pass_one(tree, data, plan, chosen=(), settings=None, hints=None):
    """(files overlay, notes, snapshot {path: bytes}, Acceptance or None, drafted [piece index.md]): the converted tree without
    `archive` and `draft`, and what the plugin's build says of it. `drafted` lists the pieces tried again as drafts."""
    only = check_only(chosen) - set(PASS_ONE_SKIP)
    files, notes = converted_site_files(tree, data, plan["paper"], plan["folders"], plan.get("siteKind"), only,
                                        settings=settings, hints=hints)
    seen = TreeFiles(tree, files, notes["removed"])
    snap = _snapshot(tree, seen)
    _give_resume_sidecar(snap)
    drafted = []
    for _attempt in range(2):
        try:
            acc = site_build.accept(snap)
        except Exception:      # noqa: BLE001 -- accept does not raise; the belt to its braces
            return files, notes, snap, None, drafted
        pieces = sorted(set(m.group(1) + "/index.md" for p in acc.problems
                            for m in [_PIECE.match(p.path or "")] if m and (m.group(1) + "/index.md") in snap
                            and _MISSING_KEY.search(p.message)))
        if len(pieces) < len(set(p.path for p in acc.problems)):
            pieces = []             # a refusal that is not a missing required key is the person's to settle, never a draft
        if not acc.problems or not pieces or drafted:
            return files, notes, snap, (acc if not acc.problems else None), drafted
        for path in pieces:
            snap[path] = _with_draft(snap[path])
        drafted = pieces
    return files, notes, snap, None, drafted


def _with_draft(blob):
    text = blob.decode("utf-8", "replace")
    if text.startswith("---\n"):
        return ("---\ndraft: true\n" + text[4:]).encode("utf-8")
    return ("---\ndraft: true\n---\n" + text).encode("utf-8")


def named_inputs(snap, cfg):
    """The files the build reads that no page names: site.json, the layout, the resume source's sidecar."""
    out = set(p for p in ("site/site.json", "site/templates/layout.html") if p in snap)
    pdf = (cfg.resume or {}).get("pdf") if cfg is not None and getattr(cfg, "resume", None) else None
    if pdf:
        out.update(p for p in (pdf, pdf + ".json") if p in snap)
    return out


def evidence(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, counter, measured=True,
             drafted=()):
    """The `accounting.disposition_of` evidence for every basis path. A piece tried again as a draft (the plugin refused it as it
    stands) is one the plugin WOULD publish: it counts as attributed."""
    plugin_c = plugin_attribution(acc, snap, named_inputs(snap, acc.cfg)) if acc is not None else set()
    plugin_c = plugin_c | set(drafted)
    old_c = old_attribution(local_out, snap, acc) if acc is not None else set()
    if acc is not None:
        old_c = old_c | named_inputs(snap, acc.cfg)      # a build input lands as "build input": the build needs it, whatever the old builder read
    plugin = set(p for p in basis_paths if conv_name(p, notes) in plugin_c)
    old = set(p for p in basis_paths if conv_name(p, notes) in old_c) | set(counter.used if counter else ())
    return {"engine": set(engine_files), "kept": set(kept), "archived": set(archived), "person": dict(person), "old": old,
            "plugin": plugin, "unsettled": set(p for g in (counter.unsettled if counter else []) for p in g),
            "measured": measured}


def open_candidates(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person):
    """The files attribution leaves open: not engine, kept, archived, not the person's, and neither attributed to the old builder
    nor to the plugin's build as a page source: the counterfactual decides whether the old builder uses them."""
    ev = evidence(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, None)
    skip = ev["engine"] | ev["kept"] | ev["archived"] | set(person)
    return sorted(p for p in basis_paths if p not in skip and p not in ev["old"] and not p.startswith(".site-studio/")
                  and not re.match(r"^(README|LICENSE|CLAUDE\.md|HANDOFF\.md|\.git|\.editorconfig)", posixpath.basename(p))
                  and not p.startswith(".claude/"))


def run_accounting(basis_paths, tree, data, plan, local_out, engine, kept, archived, run_old, chosen=(), settings=None,
                   hints=None):
    """The accounting for every basis path: {"dispositions": {path: [disposition, why]}, "counts": {...}, "lines": [...],
    "cause": id or None, "drafted": [...], "unsettled": [[path]], "refused": reason or None}. `run_old(removed)` is
    `usage.old_runner`'s (or a fake): the old builder on the working copy minus `removed`. `local_out` is the old builder's
    output on the UNCHANGED tree."""
    files, notes, snap, acc, drafted = pass_one(tree, data, plan, chosen, settings, hints)
    person = dict((p, e["disposition"]) for p, e in plan["files"].items() if e.get("disposition"))
    if acc is None:
        return {"dispositions": dict((p, ["undisposed", "the plugin's build refuses the pass-1 tree"]) for p in basis_paths
                                     if p not in engine["files"]),
                "counts": {}, "lines": ["file accounting: the plugin's build refuses the converted tree, so no file was attributed"],
                "cause": None, "drafted": [], "unsettled": [], "refused": "the plugin's build refuses the converted tree"}
    cands = open_candidates(basis_paths, notes, snap, acc, local_out, set(engine["files"]), kept, archived, person)
    counter = counterfactual(cands, run_old, lambda a, b: compare_builds(a, b) == [])
    ev = evidence(basis_paths, notes, snap, acc, local_out, set(engine["files"]), kept, archived, person, counter,
                  drafted=drafted)
    accounted = account(sorted(basis_paths), ev)
    return {"dispositions": dict((p, list(v)) for p, v in accounted.items()), "counts": counts(accounted),
            "lines": counter.lines, "cause": counter.cause, "drafted": drafted,
            "unsettled": [list(g) for g in counter.unsettled], "refused": None}
