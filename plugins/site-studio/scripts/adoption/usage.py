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
removed is pinned to that file (a group that crashes is halved like one that differs) and the file is `failed`, NOT `used`:
a crash is not use (design-adopt-parity-2 rule S3; `adoption.served.crash_reading` asks whether anything of it is published).
The groups are UNITS (rule S2, `served.units_of`: a piece's or a reference's folder whole, else a directory), and a folder a
variant leaves empty is removed with its files, as a checkout without those files has no such folder. Before any variant the builder runs
once more on the UNCHANGED tree: if it differs from itself beyond normalisation, nothing is run and the files stay undisposed
with cause `env/builder-nondeterministic` (never filed).

THREE STEPS, EACH UNDER ITS OWN BOUND (design-reference-layout 4.2, dev 1059), so no file takes a run from another: (1) the pass
above, as 0.8.0 ran it, over the candidates less the late files; (2) the groups it left unsettled, exactly as it left them (a half
stays a half), tried in groups: all in one run, a batch that is `same` is unused whole, one that differs, fails or times out is
split in two by groups, one group alone is judged as in (1); (3) the LATE files (`late`: the person's kept files, then the plugin's
own `decisions/**` and `BRAND.md`, then nested README-like files), as single-file groups with the same batching and no `unlinked`
question. A batch of two or more groups runs under `batch_limit` seconds, a limited run. What batching can miss, stated: two removals
that undo each other, in steps 2 and 3 only; P1 and P2 judge the whole result. Every unsettled file says why (`Counterfactual.why`).

Pure over a `run(removed, limit=None) -> (outcome, files)` callable that the caller supplies (`outcome` is "ok", "fails" or
"timeout"; `files` is the output as `{path: bytes}`; `limit` only on a batch), so the bisection is tested over fake builders and
the real runner (`old_runner`) over a node one.
"""

import hashlib
import os
import posixpath
import shutil
import time

from adoption.parity import _walk, builder_failed
from adoption.served import unit_of, units_of

COUNTERFACTUAL_RUNS = 32
COUNTERFACTUAL_SECONDS = 120.0
BATCH_FLOOR, BATCH_CEILING, BATCH_FACTOR = 10.0, 120.0, 4
LATE_KINDS = ("keep", "own", "nested")          # step 3's order: the person's kept files, the plugin's own, nested repository files
WHY_RUNS = "not tried: the bound of %d runs (and %d more in groups) was reached"      # what an unsettled file is told (section 4.1)
WHY_TIME = "not tried: the time bound was reached"
WHY_TIMEOUT = "tried, and your builder timed out without it"
WHY_FAILS = "not tested: your builder does not run on the unchanged tree"
WHY_DIFFERS = "not tested: your builder differs from itself on the unchanged tree"


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


class Counterfactual(object):
    """The result: `used` (removing it changed the output), `unused` (a group whose removal changed nothing), `unsettled`
    (a group the run cap, the time bound or a crash left unsplit), `runs`, `cause` (a closed id or None) and `lines` (printed).
    `failed` holds the files whose removal alone made the builder exit non-zero: never `used` (rule S3, a crash is not use).
    `unlinked` ({unit: [old output path]}) the units S2 found unused although their removal took their own unlinked files.
    `why` ({path: the reason it is unsettled}, section 4.1) names each unsettled path's reason. `late` ({path: kind}) holds the
    late files asked about (step 3), `late_unsettled` the ones left unsettled, and `carried` ({path: (verdict, gone)}) every verdict
    steps 2 and 3 reached (or were handed), for the next accounting of the same parity (`settled=`)."""

    def __init__(self):
        self.used, self.unused, self.unsettled, self.runs, self.cause, self.lines = set(), set(), [], 0, None, []
        self.failed, self.unlinked = set(), {}
        self.why, self.late, self.late_unsettled, self.carried = {}, {}, {}, {}


class _Bound(object):
    """One step's bound: `runs` more builder runs than `res.runs` holds now, and `seconds` from `start` (default: now)."""

    def __init__(self, res, runs, seconds, clock, start=None):
        self.res, self.runs, self.seconds, self.clock = res, runs, seconds, clock
        self.limit = res.runs + runs
        self.start = clock() if start is None else start

    def left(self):
        return self.res.runs < self.limit

    def over(self):
        return not self.left() or self.clock() - self.start > self.seconds

    def why(self):
        """Which bound it was, as a file is told (section 4.1)."""
        return WHY_TIME if self.left() else WHY_RUNS % (self.runs + 2, self.runs)


class _Search(object):
    """What the three steps of one `counterfactual` share: the run, `same`, the unchanged tree's output and the result."""

    def __init__(self, res, run, same, base, unlinked, clock):
        self.res, self.run, self.same, self.base, self.unlinked, self.clock = res, run, same, base, unlinked, clock
        self.timed_out = set()

    def leave(self, group, bound, timed_out=False):
        """`group` stays unsettled, with the reason: a single file that timed out was tried; any other was not."""
        self.res.unsettled.append(group)
        for p in group:
            self.res.why[p] = WHY_TIMEOUT if timed_out else bound.why()
        if timed_out:
            self.timed_out.update(group)

    def bisect(self, todo, bound, whole):
        """0.8.0's pass over `todo` (a list of groups, consumed): run a group, halve it while it differs, and settle what the
        bound allows. `whole` ({tuple of paths}) names the groups S2's `unlinked` question may be asked of."""
        res, same = self.res, self.same
        while todo:
            group = todo.pop(0)
            if bound.over():
                self.leave(group, bound)
                continue
            outcome, files = self.run(tuple(group))
            res.runs += 1
            if outcome != "ok":
                if len(group) > 1 and bound.left():
                    mid = len(group) // 2
                    todo[0:0] = [group[:mid], group[mid:]]
                elif len(group) == 1 and outcome == "fails":
                    res.failed.add(group[0])           # the builder threw when this one file was gone: S3 judges it, never as use
                else:
                    self.leave(group, bound, timed_out=len(group) == 1 and outcome == "timeout")
                continue
            equal = same(self.base, files)
            gone = (None if equal or self.unlinked is None or tuple(group) not in whole
                    else self.unlinked(self.base, files, unit_of(group[0])))
            if equal:
                res.unused.update(group)
            elif gone:
                res.unused.update(group)            # S2: only its own published files went, at addresses no old page links
                res.unlinked[unit_of(group[0])] = gone
            elif len(group) == 1:
                res.used.add(group[0])
            else:
                mid = len(group) // 2
                todo[0:0] = [group[:mid], group[mid:]]

    def batches(self, groups, bound, limit, whole):
        """Steps 2 and 3 (section 4.2): all of `groups` in one run under the builder limit `limit`; a batch that is `same` is
        unused whole, one that differs, fails or times out is split in two by groups, in order, and one group alone is judged
        as the first pass judges it (`bisect`: the full builder limit, halved to files)."""
        res = self.res
        queue = [list(groups)]
        while queue:
            gs = queue.pop(0)
            if len(gs) == 1:
                self.bisect([gs[0]], bound, whole)
            elif bound.over():
                for g in gs:
                    self.leave(g, bound)
            else:
                removed = tuple(p for g in gs for p in g)
                outcome, files = self.run(removed, limit=limit)
                res.runs += 1
                if outcome == "ok" and self.same(self.base, files):
                    res.unused.update(removed)
                else:
                    mid = len(gs) // 2
                    queue[0:0] = [gs[:mid], gs[mid:]]

    def hand_on(self, groups, settled):
        """`groups` less the paths `settled` ({path: (verdict, gone)}, an earlier accounting of this parity's steps 2 and 3) holds a
        verdict for: they are applied here. A first-pass verdict wins: a path it settled is in no group."""
        if not settled:
            return groups
        res = self.res
        sets = {"used": res.used, "unused": res.unused, "failed": res.failed}
        out = []
        for g in groups:
            rest = []
            for p in g:
                got = settled.get(p)
                if got is None:
                    rest.append(p)
                    continue
                sets[got[0]].add(p)
                if got[1]:
                    res.unlinked.setdefault(unit_of(p), list(got[1]))
            if rest:
                out.append(rest)
        return out


def groups_of(paths):
    """The first counterfactual groups: the files of one unit (rule S2, `served.units_of`). Sorted, so a run is repeatable."""
    return units_of(paths)


def batch_limit(slower):
    """The builder limit of a batch of two or more groups (section 4.2): 4 times the slower baseline run, at least 10 seconds,
    at most the 120 a single run gets."""
    return min(BATCH_CEILING, max(BATCH_FLOOR, BATCH_FACTOR * slower))


def not_tested(res, candidates, late, why, cause, line):
    """The builder cannot be asked (it fails, or differs from itself, on the unchanged tree): nothing was tested, and every file
    says so. A late file alone is no `cause`: a site with a nested README must not gain a blocker by it."""
    res.cause = cause if candidates else None
    res.unsettled = [list(sorted(candidates))] if candidates else []
    res.late_unsettled = dict(late)
    res.why.update((p, why) for p in list(candidates) + list(late))
    res.lines.append(line)
    return res


def settle_leftovers(search, runs, seconds, limit, whole, settled):
    """Step 2 (section 4.2): the groups the first pass left unsettled, exactly as it left them (a half stays a half), in groups
    under a bound of their own. A single file that timed out in the first pass was tried and stays as it is."""
    res = search.res
    todo = [g for g in res.unsettled if not (len(g) == 1 and g[0] in search.timed_out)]
    if not todo:
        return
    res.unsettled = [g for g in res.unsettled if len(g) == 1 and g[0] in search.timed_out]
    for g in todo:
        for p in g:
            res.why.pop(p, None)            # each is told again, by this step's bound, if it stays unsettled
    todo = search.hand_on(todo, settled)
    if todo:
        search.batches(todo, _Bound(res, runs, seconds, search.clock), limit, whole)
    res.unsettled.sort(key=lambda g: g[0])


def settle_late(search, runs, seconds, limit, settled):
    """Step 3 (section 4.2): the late files, one single-file group each, the person's kept files first, then the plugin's own
    (`decisions/**`, `BRAND.md`), then the nested repository files, under a third bound; `unlinked` is never asked of them.
    What stays unsettled goes to `late_unsettled` with its kind, never to `unsettled`."""
    res = search.res
    groups = search.hand_on([[p] for p in res.late], settled)
    if not groups:
        return
    kept, res.unsettled = res.unsettled, []
    search.batches(groups, _Bound(res, runs, seconds, search.clock), limit, set())
    res.late_unsettled.update((g[0], res.late[g[0]]) for g in res.unsettled)
    res.unsettled = kept


def carry(res, before):
    """`res.carried`: what steps 2 and 3 settled since `before` (the used, unused, failed and unlinked sets after the first pass)."""
    for verdict, now, was in (("used", res.used, before[0]), ("unused", res.unused, before[1]), ("failed", res.failed, before[2])):
        for p in sorted(now - was):
            unit = unit_of(p)
            gone = res.unlinked.get(unit) if verdict == "unused" and unit not in before[3] else None
            res.carried[p] = (verdict, list(gone) if gone else None)


def counterfactual(candidates, run, same, runs=COUNTERFACTUAL_RUNS, seconds=COUNTERFACTUAL_SECONDS, clock=time.monotonic,
                   unlinked=None, late=None, settled=None):
    """Bisect `candidates` ([path]) against `run(removed) -> (outcome, files)`. `same(a, b)` says two outputs are equal after P2's
    normalisation. `unlinked(base, files, unit)` (`served.unlinked_removal`), when given, is asked of a WHOLE unit whose removal
    differs: the old addresses it took, when they are all it changed and no old page links them (rule S2), and then the unit is
    unused like one that changes nothing (`Counterfactual.unlinked`). See the module docstring for the three steps and their bounds.
    `late` ({path: kind}, kind one of `LATE_KINDS`) are the files of step 3; `settled` ({path: (verdict, gone)}) the earlier
    accounting's step 2 and 3 verdicts of this parity (read here, and `Counterfactual.carried` is what to hand on).
    `run(removed, limit=seconds)` is asked of a batch of two or more groups only."""
    res = Counterfactual()
    late = dict((p, late[p]) for p in sorted(late or (), key=lambda p: (LATE_KINDS.index(late[p]), p)))
    if not candidates and not late:
        return res
    start = clock()
    o1, base = run(())
    t1 = clock()
    o2, again = run(())
    t2 = clock()
    res.runs, res.late = 2, late
    if o1 != "ok" or o2 != "ok":
        return not_tested(res, candidates, late, WHY_FAILS, "env/builder-fails",
                          "counterfactual: the builder does not run on the unchanged tree (%s), so no file was tested"
                          % (o1 if o1 != "ok" else o2))
    if not same(base, again):
        return not_tested(res, candidates, late, WHY_DIFFERS, "env/builder-nondeterministic",
                          "counterfactual: the builder differs from itself on the unchanged tree beyond the stated "
                          "normalisation, so no file was tested and each stays where it is")
    todo = groups_of(candidates)
    whole = set(tuple(g) for g in todo)
    search = _Search(res, run, same, base, unlinked, clock)
    search.bisect(todo, _Bound(res, runs, seconds, clock, start), whole)
    before = (set(res.used), set(res.unused), set(res.failed), set(res.unlinked))
    limit = batch_limit(max(t1 - start, t2 - t1))
    settle_leftovers(search, runs, seconds, limit, whole, settled)
    settle_late(search, runs, seconds, limit, settled)
    carry(res, before)
    more = (", and %d more runs and the same seconds for each of what was left and the files no page names" % runs
            if res.runs > runs + 2 or late else "")
    res.lines.append("counterfactual: %d builder run(s) (bound %d runs, %d seconds%s); %d file(s) used, %d unused, %d the builder "
                     "stops without, %d group(s) not settled%s"
                     % (res.runs, runs + 2, int(seconds), more, len(res.used), len(res.unused), len(res.failed), len(res.unsettled),
                        ", %d late file(s) not settled" % len(res.late_unsettled) if res.late_unsettled else ""))
    for unit, gone in sorted(res.unlinked.items()):
        res.lines.append("counterfactual: removing %s takes only its own %d published file(s), which no old page links (first %s): "
                         "source material no page shows" % (unit, len(gone), gone[0]))
    if res.unsettled and res.cause is None:
        res.cause = "unobservable"
    return res


def old_runner(copy_root, run_builder, scratch):
    """The real `run(removed, limit=None)`: copy the working copy, delete `removed`, run the builder with `run_builder(workdir) ->
    (out_dir or None, why)`, read its output. `copy_root` is the folder holding the working copy as it stands; each variant gets
    its own copy under `scratch` and is deleted after. A `limit` (seconds, a batch's) is handed on as `run_builder(workdir,
    limit)`; without one the builder is called as it always was, at its own 120."""
    def run(removed, limit=None):
        work = os.path.join(scratch, "cf-%d" % len(os.listdir(scratch)))
        shutil.copytree(copy_root, work, symlinks=False)
        try:
            shutil.rmtree(os.path.join(work, "site", "dist"), ignore_errors=True)
            for rel in removed:
                try:
                    os.remove(os.path.join(work, *rel.split("/")))
                except OSError:
                    pass
                prune(work, posixpath.dirname(rel))
            out, why = run_builder(work) if limit is None else run_builder(work, limit)
            if out is None:
                return ("fails" if builder_failed(why) else "timeout"), {}
            return "ok", _walk(out)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return run


def prune(root, folder):
    """Remove `folder` (relative to `root`) and each parent that a removal left empty: a unit removed whole leaves no folder."""
    while folder:
        try:
            os.rmdir(os.path.join(root, *folder.split("/")))
        except OSError:
            return
        folder = posixpath.dirname(folder)
