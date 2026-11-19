"""adoption.usage -- what each build USES: attribution in both outputs, and the counterfactual archive run (design 8 FA; Q1.2,
Q1.7, Q2.3; R3N-7; step 1.9r).

Part of the `adoption` package behind the entry point `adopt.py`.

TWO MEASURES; A BARE READ IS NEITHER. A read log only NOMINATES a file, because a builder reads files it then skips (a draft it
parses and drops) and the plugin's own validation reads every `page.md`. What counts:

  plugin(f)   f is the source of a page the plugin's build wrote (its page-to-source map), or its sha256 equals a file in the
              plugin's output, or it is one of the build's named inputs (`site/site.json`, the layout, the resume sidecar)
  old(f)      f's sha256 equals a file in the old output; or f is the source of a plugin page whose output path also exists in
              the old output (the plugin's routing is the hypothesis, the old output the evidence); or, COUNTERFACTUALLY,
              removing f changes the old output

THE COUNTERFACTUAL (`counterfactual`). For the files attribution leaves open, the old builder is run again with a GROUP of them
removed, the group being a directory's worth; a group whose output equals the untouched run's (after P2's own normalisation,
`parity_classes.compare_builds`) holds no used file; a group that differs is HALVED until single files remain. It is bounded two
ways, both printed: `COUNTERFACTUAL_RUNS` builder runs and `COUNTERFACTUAL_SECONDS` of wall time. A group still unsplit at either
bound is `unsettled`: cause `unobservable/<family>` (a count, never a name), the files stay undisposed and block. A builder run
that TIMES OUT on a variant makes that group unsettled, never `no-landing` (R3N-7). A builder that CRASHES when ONE file is
removed needs that file (it threw on the missing read): that file is used (a group that crashes is halved like one that
differs, so the crash is pinned to a file); a crash is therefore never a reason to leave a file unsettled. Before any variant the builder runs
once more on the UNCHANGED tree: if it differs from itself beyond normalisation, nothing is run and the files stay undisposed
with cause `env/builder-nondeterministic` (never filed).

Pure over a `run(removed) -> (outcome, files)` callable that the caller supplies (`outcome` is "ok", "fails" or "timeout"; `files`
is the output as `{path: bytes}`), so the bisection is tested over fake builders and the real runner (`old_runner`) over a node one.
"""

import hashlib
import os
import posixpath
import shutil
import time

from adoption.parity import _walk, builder_failed

COUNTERFACTUAL_RUNS = 32
COUNTERFACTUAL_SECONDS = 120.0


def sha(data):
    return hashlib.sha256(data).hexdigest()


def plugin_attribution(acc, files, extra_inputs=()):
    """{path} the plugin's build uses. `acc` is `build.accept(files)`'s Acceptance (`.pages`: {output path: {"source": ...}},
    `.output`: {output path: bytes}); `files` is the input {path: bytes}; `extra_inputs` the named inputs (`site/site.json`, the
    layout, the resume sidecar: paths `siteconfig` names)."""
    used = set(extra_inputs)
    for info in acc.pages.values():
        src = (info or {}).get("source")
        if src:
            used.add(src)
    out_shas = set(sha(b) for b in acc.output.values())
    for p, b in files.items():
        if sha(b) in out_shas:
            used.add(p)
    return used & set(files)


def old_attribution_why(old_out, files, acc):
    """{path: why} the old builder is shown to use WITHOUT running it again: a file whose bytes it published (named by the
    first output path that holds them), and the source of a plugin page whose output path it also wrote (N1: the `why` is what
    `no-landing` prints beside the path)."""
    used = {}
    out_by_sha = {}
    for out_path in sorted(old_out):
        out_by_sha.setdefault(sha(old_out[out_path]), out_path)
    for p, b in files.items():
        if sha(b) in out_by_sha:
            used[p] = "its bytes are published as %s" % out_by_sha[sha(b)]
    for out_path, info in sorted(acc.pages.items()):
        src = (info or {}).get("source")
        if src and out_path in old_out and src in files:
            used.setdefault(src, "it is the source of %s, a page the old builder also writes" % out_path)
    return dict((p, w) for p, w in used.items() if p in files)


def old_attribution(old_out, files, acc):
    """{path} the old builder is shown to use WITHOUT running it again: a file whose bytes it published, and the source of a
    plugin page whose output path it also wrote."""
    return set(old_attribution_why(old_out, files, acc))


def groups_of(paths):
    """The first counterfactual groups: the files in one directory. Sorted, so a run is repeatable."""
    by = {}
    for p in sorted(paths):
        by.setdefault(posixpath.dirname(p), []).append(p)
    return [by[d] for d in sorted(by)]


class Counterfactual(object):
    """The result: `used` (removing it changed the output), `unused` (a group whose removal changed nothing), `unsettled`
    (a group the run cap, the time bound or a crash left unsplit), `runs`, `cause` (a closed id or None) and `lines` (printed).
    `failed` is the part of `used` whose removal made the builder exit non-zero (it threw on the missing read)."""

    def __init__(self):
        self.used, self.unused, self.unsettled, self.runs, self.cause, self.lines = set(), set(), [], 0, None, []
        self.failed = set()


def counterfactual(candidates, run, same, runs=COUNTERFACTUAL_RUNS, seconds=COUNTERFACTUAL_SECONDS, clock=time.monotonic):
    """Bisect `candidates` ([path]) against `run(removed) -> (outcome, files)`. `same(a, b)` says two outputs are equal after P2's
    normalisation. See the module docstring for the bounds."""
    res = Counterfactual()
    if not candidates:
        return res
    start = clock()
    o1, base = run(())
    o2, again = run(())
    res.runs = 2
    if o1 != "ok" or o2 != "ok":
        res.cause = "env/builder-fails"
        res.unsettled = [list(sorted(candidates))]
        res.lines.append("counterfactual: the builder does not run on the unchanged tree (%s), so no file was tested" % (o1 if o1 != "ok" else o2))
        return res
    if not same(base, again):
        res.cause = "env/builder-nondeterministic"
        res.unsettled = [list(sorted(candidates))]
        res.lines.append("counterfactual: the builder differs from itself on the unchanged tree beyond the stated normalisation, "
                         "so no file was tested and each stays where it is")
        return res
    todo = groups_of(candidates)
    while todo:
        group = todo.pop(0)
        if res.runs >= runs + 2 or clock() - start > seconds:
            res.unsettled.append(group)
            continue
        outcome, files = run(tuple(group))
        res.runs += 1
        if outcome != "ok":
            if len(group) > 1 and res.runs < runs + 2:
                mid = len(group) // 2
                todo[0:0] = [group[:mid], group[mid:]]
            elif len(group) == 1 and outcome == "fails":
                res.used.add(group[0])             # the builder threw when this one file was gone: it reads it
                res.failed.add(group[0])
            else:
                res.unsettled.append(group)
            continue
        if same(base, files):
            res.unused.update(group)
        elif len(group) == 1:
            res.used.add(group[0])
        else:
            mid = len(group) // 2
            todo[0:0] = [group[:mid], group[mid:]]
    res.lines.append("counterfactual: %d builder run(s) (bound %d runs, %d seconds); %d file(s) used, %d unused, %d group(s) not "
                     "settled" % (res.runs, runs + 2, int(seconds), len(res.used), len(res.unused), len(res.unsettled)))
    if res.unsettled and res.cause is None:
        res.cause = "unobservable"
    return res


def old_runner(copy_root, run_builder, scratch):
    """The real `run(removed)`: copy the working copy, delete `removed`, run the builder with `run_builder(workdir) -> (out_dir
    or None, why)`, read its output. `copy_root` is the folder holding the working copy as it stands; each variant gets its own
    copy under `scratch` and is deleted after."""
    def run(removed):
        work = os.path.join(scratch, "cf-%d" % len(os.listdir(scratch)))
        shutil.copytree(copy_root, work, symlinks=False)
        try:
            shutil.rmtree(os.path.join(work, "site", "dist"), ignore_errors=True)
            for rel in removed:
                try:
                    os.remove(os.path.join(work, *rel.split("/")))
                except OSError:
                    pass
            out, why = run_builder(work)
            if out is None:
                return ("fails" if builder_failed(why) else "timeout"), {}
            return "ok", _walk(out)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return run
