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

Rule S (design-adopt-parity-2 section 8, `adoption.served`): the plugin's side is what its build used (`Acceptance.used`, S1),
judged against the old side without a run where it can be; the counterfactual removes units (S2); a file the old builder
stops without is asked whether anything of it is published, never counted as used for the crash (S3); the template's
stamp is builder state without a run. The units of source material no page shows are named in one note, never a blocker.

Evidence is keyed by the path AT THE BASIS (what `git ls-files` lists). A renamed file (`work.md` -> `index.md`, `home.md` ->
`index.md`) is looked up under its converted name. Without a measurement (no node, a builder that fails) nothing here runs and
every file but those rules 1 to 4 settle stays where it is, undisposed.
"""

import posixpath
import re

from building import running  # noqa: E402

from adoption.accounting import KEPT_ROOT_FILES, account, address_of, counts, piece_folder_of, plan_choices, wholly_archived
from adoption.base import Refused
from adoption import resumeproof
from adoption.dispose import conv_name
from adoption.convert import _snapshot, converted_site_files, holds_markdown, pageless_folders
from adoption.parity import compare_builds
from adoption.problems import check_only
from adoption.served import (UNUSED_WHY, crash_reading, is_content_unit, old_texts, run_free_use, stamp_why, template_stamp,
                             unit_of, unlinked_removal, unused_lines)
from adoption.tree import TreeFiles
from adoption.usage import counterfactual, old_attribution_why, plugin_attribution, sha

PASS_ONE_SKIP = ("archive", "draft")
_PIECE = re.compile(r"^(content/[^/]+/[^/]+)/index\.md$")
_OWN_FILES = re.compile(r"^(decisions/|BRAND\.md$)")          # the plugin's own dev-repo files (design-reference-layout 4.4)
_LEFT_OUT = re.compile(r"^(README|LICENSE|CLAUDE\.md|HANDOFF\.md|\.git|\.editorconfig)")      # 0.8.0's basename test, unchanged
_MISSING_KEY = re.compile(r"front matter '[^']*' is required\b")        # what a piece still being written plausibly lacks (both the build's wordings)


def pass_one(tree, data, plan, chosen=(), settings=None, hints=None):
    """(files overlay, notes, snapshot {path: bytes}, Acceptance or None, drafted [piece index.md]): the converted tree without
    `archive` and `draft`, and what the plugin's build says of it. `drafted` lists the pieces tried again as drafts."""
    only = check_only(chosen) - set(PASS_ONE_SKIP)
    folders = dict((n, "source") for n in undecided_folders(tree, plan))      # F2: a question the measurement is about to answer
    folders.update(plan["folders"])                                         # is read as `source` for this tree only
    files, notes = converted_site_files(tree, data, plan["paper"], folders, plan.get("siteKind"), only,
                                        settings=settings, hints=hints)
    seen = TreeFiles(tree, files, notes["removed"])
    snap = resumeproof.stand_in(_snapshot(tree, seen))
    drafted = []
    for _attempt in range(2):
        try:
            acc = running.accept(snap)
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
    """The files the build reads that no page names: site.json, the layout, the resume source's sidecar, and the look files
    `look` and `lookLocal` name (design-adopt-ownership-line 3: both look files are adopt's own inputs, never archived)."""
    out = set(p for p in ("site/site.json", "site/templates/layout.html") if p in snap)
    out.update(p for p in (getattr(cfg, "look", None), getattr(cfg, "lookLocal", None)) if isinstance(p, str) and p in snap)
    pdf = (cfg.resume or {}).get("pdf") if cfg is not None and getattr(cfg, "resume", None) else None
    if pdf:
        out.update(p for p in (pdf, pdf + ".json") if p in snap)
    return out


def evidence(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, counter, measured=True,
             drafted=(), read=None, tree=None):
    """The `accounting.disposition_of` evidence for every basis path. A piece tried again as a draft (the plugin refused it as it
    stands) is one the plugin WOULD publish: it counts as attributed. Rule S (`adoption.served`): the plugin's side holds
    what its build used (`acc.used`, S1), and a used file the old side serves is shown so without a run; the counterfactual's
    crashes are judged by S3 (`state`: builder state, `unusedWhy`: source material no page shows); `read(path)` gives a basis
    file's bytes (S1, S3) and `tree` the basis tree (the template's stamp)."""
    plugin_c = plugin_attribution(acc, snap, named_inputs(snap, acc.cfg)) if acc is not None else set()
    plugin_c = plugin_c | set(drafted) | set(getattr(acc, "used", None) or ())
    old_why = old_attribution_why(local_out, snap, acc) if acc is not None else {}
    if acc is not None:       # a build input lands as "build input": the build needs it, whatever the old builder read
        for p in named_inputs(snap, acc.cfg):
            old_why.setdefault(p, "site-studio's build reads it as an input")
    plugin = set(p for p in basis_paths if conv_name(p, notes) in plugin_c)
    why = dict((p, old_why[conv_name(p, notes)]) for p in basis_paths if conv_name(p, notes) in old_why)
    texts = old_texts(local_out or {})
    if read is not None:      # S1: a file the plugin's build used, which the old side serves, is shown so without a run
        why.update(run_free_use([p for p in plugin if p not in why], why, read, texts))
    state, unused = {}, {}
    stamp = _stamp(tree, acc, notes)
    if stamp:
        state[stamp] = stamp_why(conv_name(stamp, notes)[:-len(".sha256")])
    for p in (counter.used if counter else ()):          # N1: how each file the counterfactual found used was judged so
        why.setdefault(p, "your builder publishes something different when %s is missing"
                       % ("its folder %s" % unit_of(p) if is_content_unit(unit_of(p)) else "it"))
    for p in (counter.unused if counter else ()):
        if is_content_unit(unit_of(p)):
            unused[p] = "%s (%s changes no page when it is removed)" % (UNUSED_WHY, unit_of(p))
    for p in sorted(counter.failed if counter else ()):  # S3: a crash is not use
        if p in plugin:          # both builds read it: never archived or builder state under the plugin's own build (S1)
            why.setdefault(p, "your builder exits non-zero when it is missing, and site-studio's build reads it too")
            continue
        kind, line = crash_reading(p, read(p) if read is not None else b"", texts)
        {"old": why, "unused": unused, "state": state}[kind].setdefault(p, line)
    old = set(p for p in basis_paths if p in why)
    serves = _serves(acc, snap, notes, [p for p in plugin - old if person.get(p) == "keep"], local_out, drafted)
    return {"engine": set(engine_files), "kept": set(kept), "archived": set(archived), "person": dict(person), "old": old,
            "plugin": plugin, "serves": serves, "unsettled": set(p for g in (counter.unsettled if counter else []) for p in g),
            "measured": measured, "usedWhy": why, "state": state, "unusedWhy": unused,
            "late": dict(getattr(counter, "late", None) or {}),                       # every late file the counterfactual was asked about
            "lateUnsettled": dict(getattr(counter, "late_unsettled", None) or {}),    # of them the unsettled: {path: keep|own|nested}
            "unsettledWhy": dict(getattr(counter, "why", None) or {})}                # section 4.1: why each unsettled path is


def _serves(acc, snap, notes, paths, local_out, drafted):
    """{basis path: address}: of `paths` (files the person keeps, which the plugin's build uses and the old builder is not shown to),
    the ones the plugin's build SERVES, at an address the old output does not hold (rule K (3), design-reference-layout 4.3). The
    address is where a page it is the source of is written, else the output with equal bytes; a piece the build refuses and adopt
    tried again as a draft is served at no address it knows (""). A file the build only reads as an input, or one whose address the
    old output also holds (P2 judges the bytes there), is not served."""
    if acc is None:
        return {}
    where = dict((info["source"], out) for out, info in sorted(acc.pages.items(), reverse=True) if (info or {}).get("source"))
    by_sha = {}
    for out in sorted(acc.output, reverse=True):
        by_sha[sha(acc.output[out])] = out
    out = {}
    for p in paths:
        conv = conv_name(p, notes)
        at = where.get(conv) or (by_sha.get(sha(snap[conv])) if conv in snap else None)
        if at is not None and at not in (local_out or {}):
            out[p] = address_of(at)
        elif at is None and conv in drafted:
            out[p] = ""
    return out


def _stamp(tree, acc, notes):
    """The basis path of the template's resume stamp (`served.template_stamp`), or None."""
    if tree is None or acc is None or acc.cfg is None:
        return None
    pdf = (getattr(acc.cfg, "resume", None) or {}).get("pdf")
    basis = dict((conv_name(p, notes), p) for p in tree.paths())
    return template_stamp(tree, basis.get(pdf, pdf), sidecar=bool(pdf))


def undecided_folders(tree, plan, kind=None):
    """The page-less `content/<name>/` folders that hold Markdown and have no decision (F2): the ones `layout_changes` leaves
    where they are until the person says `folder NAME source|portfolio`, and that the MEASURED accounting may settle."""
    return [n for n in pageless_folders(TreeFiles(tree), kind or plan.get("siteKind") or "portfolio")
            if n not in plan["folders"] and holds_markdown(tree, "content/%s/" % n)]


def measured_folders(tree, plan, kind=None):
    """`plan["folders"]` plus a `source` decision for every undecided folder the plan's last measured accounting wholly
    archived (F2): what `check` judges by after `parity`, so it asks no question the measurement has already answered."""
    disp = (((plan.get("parity") or {}).get("accounting") or {}).get("dispositions")) or {}
    paths = list(tree.paths())
    out = dict(plan["folders"])
    out.update((n, "source") for n in undecided_folders(tree, plan, kind) if wholly_archived(paths, n, disp))
    return out


def candidate_split(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, read=None, tree=None,
                    keep_paths=()):
    """([first-pass candidates], {late path: kind}): the files attribution leaves open (below), the late ones apart (design-
    reference-layout 4.2). A late file is the person's kept file (`keep_paths`, kind `keep`: measured although kept, unless it is
    engine, archived, builder state, shown used or a root repository file), `decisions/**` or root `BRAND.md` (`own`), or a nested
    file 0.8.0's basename test leaves out (`nested`: `notes/README.md`); the root ones of those are kept and no candidate."""
    ev = evidence(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, None, read=read, tree=tree)
    skip = ev["engine"] | ev["kept"] | ev["archived"] | set(person) | set(ev["state"])
    never = ev["engine"] | ev["archived"] | set(ev["state"]) | ev["old"]
    cands, late = [], {}
    for p in sorted(basis_paths):
        if p.startswith((".site-studio/", ".claude/")) or p in never:
            continue
        if p in keep_paths:
            if not KEPT_ROOT_FILES.match(p):
                late[p] = "keep"
        elif p in skip or p in ev["old"]:
            continue
        elif _OWN_FILES.match(p):
            late[p] = "own"
        elif _LEFT_OUT.match(posixpath.basename(p)):
            if "/" in p:
                late[p] = "nested"
        else:
            cands.append(p)
    return cands, late


def open_candidates(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, read=None, tree=None):
    """The files attribution leaves open: not engine, kept, archived, not the person's, not the template's stamp, and not shown
    used by the old builder (by attribution, or for a file the plugin's build used, without a run: rule S1), and not late
    (`candidate_split`): the counterfactual's first pass decides whether the old builder uses them."""
    return candidate_split(basis_paths, notes, snap, acc, local_out, engine_files, kept, archived, person, read, tree)[0]


def run_accounting(basis_paths, tree, data, plan, local_out, engine, kept, archived, run_old, chosen=(), settings=None,
                   hints=None, settled=None, keep_paths=()):
    """The accounting for every basis path: {"dispositions": {path: [disposition, why]}, "counts": {...}, "lines": [...],
    "cause": id or None, "drafted": [...], "unsettled": [[path]], "refused": reason or None}. `run_old(removed, limit=None)` is
    `usage.old_runner`'s (or a fake): the old builder on the working copy minus `removed`. `local_out` is the old builder's
    output on the UNCHANGED tree. `settled` ({path: (verdict, gone)}) is read and filled: what an accounting of the same parity
    already settled in the counterfactual's steps 2 and 3 (the old builder on the unchanged tree, so as true under other
    settings), `keep_paths` the paths the person keeps, which are the late files measured first (`candidate_split`). `unsettled`
    holds the groups that stay undisposed; a late file left unsettled is no group (`evidence`'s `lateUnsettled`)."""
    files, notes, snap, acc, drafted = pass_one(tree, data, plan, chosen, settings, hints)
    person = dict((p, e["disposition"]) for p, e in plan["files"].items() if e.get("disposition"))
    if acc is None:
        return {"dispositions": dict((p, ["undisposed", "the plugin's build refuses the pass-1 tree"]) for p in basis_paths
                                     if p not in engine["files"]),
                "counts": {}, "lines": ["file accounting: the plugin's build refuses the converted tree, so no file was attributed"],
                "cause": None, "drafted": [], "unsettled": [], "refused": "the plugin's build refuses the converted tree",
                "choices": plan_choices(plan)}
    read = _reader(tree, snap, notes)
    cands, late = candidate_split(basis_paths, notes, snap, acc, local_out, set(engine["files"]), kept, archived, person, read, tree,
                                  keep_paths)
    same = lambda a, b: compare_builds(a, b) == []          # noqa: E731
    counter = counterfactual(cands, run_old, same, unlinked=lambda base, out, unit: unlinked_removal(base, out, unit, same),
                             late=late, settled=settled)
    if settled is not None:
        settled.update(counter.carried)
    ev = evidence(basis_paths, notes, snap, acc, local_out, set(engine["files"]), kept, archived, person, counter,
                  drafted=drafted, read=read, tree=tree)
    accounted = account(sorted(basis_paths), ev)
    return {"dispositions": dict((p, list(v)) for p, v in accounted.items()), "counts": counts(accounted),
            "lines": counter.lines + unused_lines(accounted), "cause": counter.cause, "drafted": drafted,
            "unsettled": [list(g) for g in counter.unsettled], "refused": None,
            "choices": plan_choices(plan)}                 # what was asked: a choice made later is newer than this (`stale_choices`)


def _reader(tree, snap, notes):
    """`read(basis path)`: the bytes of a basis file, read under its converted name where the pass-1 tree holds it."""
    def read(path):
        conv = conv_name(path, notes)
        if conv in snap:
            return snap[conv]
        try:
            return tree.read(path)
        except Exception:      # noqa: BLE001 -- a file the tree cannot give is one with no evidence (S3: UNKNOWN)
            return b""
    return read
