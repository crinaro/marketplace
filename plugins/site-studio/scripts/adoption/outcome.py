"""adoption.outcome -- what stops `apply` before it publishes: every cause as a row, and the publish preconditions (design 8 AO,
RP; "Ruled after R3N: one-process apply"; step 1.9f).

Part of the `adoption` package behind the entry point `adopt.py`. `assess` takes what `apply` has measured (steps 1 and 2 of the
flow) and says whether anything BLOCKS:

  blocked   the verdict is DIFFERENT or UNVERIFIED, or a file is `no-landing` or undisposed, or a refusal no conversion clears
            stands, or the publish preconditions refuse; the old builder stays the publisher, nothing of it moves, nothing is
            published or pushed, and the plugin causes are written as `pending` rows in `.site-studio/adopt-reports.json`
  clear     nothing blocks, so `apply` goes on to step 3, the publish through `deploy.py`. It is NOT an outcome: a run ends
            completed or blocked, and `adoption.finish` says which

THE PUBLISH CHECKS (`adoption.publishchecks`, dev 1068): the same list every stage prints, asked of the one converted tree
(`wouldwrite.snapshot`). `deploy.py --preflight <out> --repo <dev> --tree <scratch tree>` runs as a SUBPROCESS (adopt cannot import
`deploy`, an entry point) on the build apply already made, with the converted `site.json`, `addresses.json` and the pieces' `index.md` read
from the scratch tree the build used, never HEAD (R3N-9). It inherits the environment, so the tests' `GIT_CONFIG_*` rewrites and a fake `gh`
first on `PATH` reach it. A row is `blocks`, or `not-checked`: ONLY a network or a `gh` that cannot answer is NOT CHECKED, and then apply
prints it and does not block, because the publish that follows asks again; a build that REFUSES the tree blocks (as its `refusal/<code>`
cause) and is never "not run". An environment cause is printed with its fix and never filed (decision 17); a person cause blocks and is
never filed (R3N-13). A publish check's finding is a PLUGIN cause only when `publishfixes` says the plugin must fix it (design 1.3): the
site's, the person's and adopt's findings block, are printed with who fixes them, and are never recorded or offered for filing.
"""

import shutil
import tempfile

from reportcause import grammar

import report_issue  # noqa: E402

from adoption import publishchecks, publishfixes
from adoption.accounting import no_landing_lines, path_area, path_family, undisposed_lines
from adoption.blockers import (
    accounting_occurrences, classify, engine_occurrences, grouped, look_occurrences, parity_occurrences, preflight_occurrences,
    refusal_code, refusal_occurrences, summary_line,
)

PASSING = ("EQUAL", "MARKUP-ONLY", "ACCEPTED", "NOT APPLICABLE")


def preflight(repo, snapshot, runner=None):
    """([cause dicts], [not-checked lines]): `deploy.py --preflight` over the plugin's build of `snapshot` ({path: bytes}, the converted tree):
    the ONLINE part of the publish checks (design 1.2; the offline part is `publishchecks.offline`). Never raises: a failure to run is one NOT
    CHECKED line. A tree the build refuses is not "not run" (0.9.0 said so, and the run went on to refuse it at step 3): each refusal is a
    blocking `refusal/<code>` cause, as `assess` records it. The tests' seam: a fake `runner`, or this function patched."""
    work = tempfile.mkdtemp(prefix="adopt-preflight-")
    try:
        acc, _stood, out_dir, tree_dir = publishchecks.scratch(snapshot, work)
        if out_dir is None:
            return [{"cause": "refusal/%s" % refusal_code(p), "state": "blocks", "detail": p.message} for p in acc.problems], []
        rows, final, why = publishchecks.run_process(publishchecks.preflight_argv(out_dir, tree_dir, repo), runner)
        if final:
            return publishchecks.merged(rows, final), (["publish preconditions NOT CHECKED: deploy.py --preflight stopped (%s)" % why] if why else [])
        if rows and why:
            return rows, ["publish preconditions NOT CHECKED: deploy.py --preflight %s, so the rows it had not printed were not asked" % why]
        return [], ["publish preconditions NOT CHECKED: deploy.py --preflight %s" % why]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def publish_occurrences(res):
    """The occurrences a publish-check run raises: a `publish/gate/<family>` cause for the findings the plugin must fix, counted one each
    (design 1.3), and the online causes `deploy.py --preflight` answered. The build's refusals are `assess`'s `refusals`, and the other
    findings (the site's, the person's, adopt's) block without being a cause."""
    out = []
    for fam, n in sorted(publishchecks.plugin_counts(res).items()):
        if fam not in publishfixes.GATE_FAMILIES:
            continue
        out += [{"id": grammar.cause_id("publish", "gate", fam), "row": None} for _ in range(n)]
    pre, _notes = preflight_occurrences([c for c in res.causes if c["state"] == "blocks"])
    return out + pre


def offline_checks(repo, snapshot, parity):
    """The offline publish checks over `snapshot`: the tests' second seam, as `preflight` is the first (the adopt tests patch both: their R3
    shapes are hand layouts the gate would refuse, and what they test is steps 3 to 5, not the gate; `test_adoption_publish_block.py` runs it)."""
    return publishchecks.run(repo, snapshot, parity)


def kept_rows(res, occ, previous_rows):
    """The recorded rows of a `publish/gate/<family>` cause that has findings and none of them the plugin's: neither refreshed nor resolved
    (design 1.3), so a 0.9.0 row keeps its state and is not offered again for a fault that is the site's. Only a cause with no finding at all
    is left to `merge_causes`, which resolves it."""
    now = set(grammar.cause_id("publish", "gate", f["family"]) for f in res.findings
              if f["family"] in publishfixes.GATE_FAMILIES)
    plugin = set(o["id"] for o in occ)
    return [r for r in previous_rows if r["id"] in now and r["id"] not in plugin]


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
    notchecked, res, held = [], None, []
    if run_preflight and verdict in PASSING and snapshot is not None:
        res = offline_checks(repo, snapshot, parity)                          # the same list every stage prints (dev 1068, P1) ...
        if hasattr(res, "out_dir") and not occ:                               # ... and the online rows, only for a build that accepts the tree
            causes, why = preflight(repo, snapshot, runner)
            publishchecks.absorb(res, causes, why)
        else:
            res.not_checked("staging", "not asked: something above already blocks, or the build refuses the tree", publishchecks.HOW_ONLINE)
            res.not_checked("online", "not asked: something above already blocks, or the build refuses the tree", publishchecks.HOW_ONLINE)
        occ += publish_occurrences(res)
        held = kept_rows(res, occ, previous_rows)
        notchecked = ["NOT CHECKED: %s: %s%s" % (r["label"], r["reason"], (" (%s)" % r["how"]) if r["how"] else "") for r in res.unasked()]
    blocked = bool(occ) or verdict in ("DIFFERENT", "UNVERIFIED") or bool(undisposed) or bool(res and res.blocks)
    groups = grouped(occ)
    rows = (report_issue.merge_causes([r for r in previous_rows if r not in held], groups, installed) + held) if blocked or previous_rows else []
    rows.sort(key=lambda r: r["id"])
    lines = []
    for c in groups:
        kind = classify(c["id"])
        if kind != "plugin":
            lines.append("  %s cause: %s (x%d)" % (kind, c["id"], c["count"]))
    if res and res.findings:
        lines += ["  " + l for l in publishchecks.block_lines(res)]
    if blocked:
        own = len(set((f["who"], f["form"]) for f in res.findings if f["who"] != publishfixes.PLUGIN)) if res else 0
        lines.append(summary_line(groups, own) if groups or own else "blocked: %d file(s) are undisposed" % len(undisposed) if undisposed else
                     "blocked: the parity verdict is %s" % verdict)
    for n in notchecked:
        lines.append("  " + n)
    return {"blocked": blocked, "causes": groups, "rows": rows, "lines": lines, "checks": res.counts() if res else None,
            "notchecked": notchecked, "undisposed": undisposed, "noLanding": no_landing_lines(acct),
            "undisposedLines": undisposed_lines(acct), "publish": publishchecks.to_json(res) if res else None}


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
            "publish checks (a dry run asks them too; a check that cannot run says so), then 3 publish the converted site through deploy.py (it asks "
            "you first), 4 wait for Pages to build it, 5 archive %d old-builder file(s) and push the result to this repo's main."
            % (cause, n_engine))
