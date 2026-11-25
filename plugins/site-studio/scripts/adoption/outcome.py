"""adoption.outcome -- what stops `apply` before it publishes: every cause as a row, and the publish preconditions (design 8 AO,
RP; "Ruled after R3N: one-process apply"; step 1.9f).

Part of the `adoption` package behind the entry point `adopt.py`. `assess` takes what `apply` has measured (steps 1 and 2 of the
flow) and says whether anything BLOCKS:

  blocked   the verdict is DIFFERENT or UNVERIFIED, or a file is `no-landing` or undisposed, or a refusal no conversion clears
            stands, or the publish preconditions refuse; the old builder stays the publisher, nothing of it moves, nothing is
            published or pushed, and the plugin causes are written as `pending` rows in `.site-studio/adopt-reports.json`
  clear     nothing blocks, so `apply` goes on to step 3, the publish through `deploy.py`. It is NOT an outcome: a run ends
            completed or blocked, and `adoption.finish` says which

THE PUBLISH PRECONDITIONS (`preflight`): `deploy.py --preflight <out> --repo <dev> --tree <scratch tree>` as a SUBPROCESS (adopt
cannot import `deploy`, an entry point), on the build apply already made, with the converted `site.json` and
`addresses.json` read from the scratch tree the build used, never HEAD (R3N-9). It inherits the environment, so the tests'
`GIT_CONFIG_*` rewrites and a fake `gh` first on `PATH` reach it. Its answer is `blocks` or `not-checked`: ONLY a network or a
`gh` that cannot answer is NOT CHECKED, and then apply prints it and does not block, because the publish that follows runs the
same checks for real. An environment cause is printed with its fix and never filed (decision 17); a person cause blocks and is
never filed (R3N-13).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from building import running  # noqa: E402
import report_issue  # noqa: E402

from adoption.accounting import no_landing_lines, path_area, path_family, undisposed_lines
from adoption.base import PLUGIN
from adoption.blockers import (
    accounting_occurrences, classify, engine_occurrences, grouped, look_occurrences, parity_occurrences, preflight_occurrences,
    refusal_occurrences, summary_line,
)

PREFLIGHT_TIMEOUT = 180


def preflight(repo, snapshot, runner=None):
    """([cause dicts], [not-checked lines]): `deploy.py --preflight` over the plugin's build of `snapshot` ({path: bytes}, the
    converted tree). Never raises: a failure to run is one NOT CHECKED line."""
    work = tempfile.mkdtemp(prefix="adopt-preflight-")
    try:
        acc = running.accept(snapshot)
        if acc.problems:
            return [], ["publish preconditions: the plugin's build refuses the tree, so they were not run"]
        out_dir, tree_dir = os.path.join(work, "out"), os.path.join(work, "tree")
        for rel, blob in acc.output.items():
            full = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(blob)
        for rel in ("site/site.json", ".site-studio/addresses.json"):
            if rel in snapshot:
                full = os.path.join(tree_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as fh:
                    fh.write(snapshot[rel])
        argv = [sys.executable, "-B", os.path.join(PLUGIN, "scripts", "deploy.py"), "--preflight", out_dir, "--repo", repo,
                "--tree", tree_dir]
        try:
            p = (runner or subprocess.run)(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=PREFLIGHT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            return [], ["publish preconditions NOT CHECKED: deploy.py --preflight did not run (%s)" % e.__class__.__name__]
        try:
            data = json.loads(p.stdout.decode("utf-8", "replace").strip().split("\n")[-1])
            return data["causes"], []
        except (ValueError, KeyError, IndexError):
            tail = (p.stderr.decode("utf-8", "replace").strip().split("\n") or [""])[-1][:140]
            return [], ["publish preconditions NOT CHECKED: deploy.py --preflight gave no answer (%s)" % tail]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def assess(repo, plan, parity, refusals, engine, installed, previous_rows, snapshot=None, runner=None, run_preflight=True):
    """What blocks an apply before it publishes. Returns {"blocked": bool, "causes": [grouped], "rows": [merged record rows],
    "lines": [printed], "notchecked": [lines], "undisposed": [paths]}. `refusals` are the build's problems and warnings over the converted tree;
    `engine` is `engine.compute_engine`'s result; `previous_rows` the record at the basis."""
    verdict = (parity or {}).get("verdict")
    acct = (parity or {}).get("accounting") or {}
    occ = refusal_occurrences(refusals)
    occ += accounting_occurrences(acct, path_family, path_area)
    undisposed = [p for p, (d, _w) in (acct.get("dispositions") or {}).items() if d == "undisposed"]
    if verdict == "DIFFERENT":
        occ += parity_occurrences(None, (parity or {}).get("kinds") or {})
        occ += look_occurrences((parity or {}).get("lookStatus"))
    occ += engine_occurrences(engine["causes"], (parity or {}).get("cause"))
    notchecked = []
    if run_preflight and verdict in ("EQUAL", "MARKUP-ONLY", "ACCEPTED", "NOT APPLICABLE") and not occ and snapshot is not None:
        causes, notchecked = preflight(repo, snapshot, runner)
        pre, extra = preflight_occurrences(causes)
        occ += pre
        notchecked += extra
    blocked = bool(occ) or verdict in ("DIFFERENT", "UNVERIFIED") or bool(undisposed)
    groups = grouped(occ)
    rows = report_issue.merge_causes(previous_rows, groups, installed) if blocked or previous_rows else []
    lines = []
    for c in groups:
        kind = classify(c["id"])
        if kind != "plugin":
            lines.append("  %s cause: %s (x%d)" % (kind, c["id"], c["count"]))
    if blocked:
        lines.append(summary_line(groups) if groups else "blocked: %d file(s) are undisposed" % len(undisposed) if undisposed else
                     "blocked: the parity verdict is %s" % verdict)
    for n in notchecked:
        lines.append("  " + n)
    return {"blocked": blocked, "causes": groups, "rows": rows, "lines": lines,
            "notchecked": notchecked, "undisposed": undisposed, "noLanding": no_landing_lines(acct),
            "undisposedLines": undisposed_lines(acct)}


def dry_run_line(outcome, n_engine):
    """Line 2 of `apply --dry-run` (N2): what a real apply does. Blocked, it says where it STOPS and why, in the words of the
    real stop (`adopt blocked at step 2 of 5`), and describes the rest as what follows once nothing blocks; never "apply would stop
    here" over a list of steps the run does not get to."""
    if not outcome["blocked"]:
        return ("Then, without --dry-run, apply would: publish the converted site through deploy.py (it asks you first), wait for "
                "Pages to build it, archive %d old-builder file(s), and push the result to this repo's main." % n_engine)
    cause = next((l.strip() for l in outcome["lines"] if l.strip().startswith("blocked:")), "something before the publish blocks")
    return ("Then, without --dry-run, a real apply would stop at step 2 of 5 (the checks before publishing): %s. Nothing would be "
            "published or pushed, and your old builder stays your publisher. Once nothing blocks, the run goes on: step 2 is the "
            "publish preconditions (a dry run does not run them), then 3 publish the converted site through deploy.py (it asks "
            "you first), 4 wait for Pages to build it, 5 archive %d old-builder file(s) and push the result to this repo's main."
            % (cause, n_engine))
