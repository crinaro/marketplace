"""deploying.prepare -- the start both modes share: the refusals, the config, the adopt record, the build and the gates on its output.
"""
import adopt_head
import os
import shutil
import tempfile
from building import outcomes, running, acceptance
from configschema import diagnostics, model
from deploying.gates import run_gates
from reviews import rows as review_rows, store
from deploying.adoptgate import check_adopt_record, recheck_markup_only
from deploying.gitrun import DeployError, _git, _toplevel
from deploying.headcheck import refuse_if_remote, require_head_on_origin_main
from deploying.target import public_target


def prepare(repo, hooks=None, build_fn=None, adopt=False):
    """Steps 1-3 and the gates on the build output. Returns (cfg, tmp dir, out_dir, result, note)."""
    refuse_if_remote()
    repo = _toplevel(repo)
    note = adopt_head.require_head_ahead_of_origin_main(_git, repo, DeployError) if adopt else require_head_on_origin_main(repo)
    try:
        cfg = model.load(os.path.join(repo, "site", "site.json"))
    except (diagnostics.SiteConfigError, OSError) as e:
        raise DeployError(str(e))
    public_target(cfg)      # a null publicRepo refuses here, before any build (dev #835, AM9)
    markup_only = check_adopt_record(repo)
    work = tempfile.mkdtemp(prefix="ss-deploy-")
    out_dir = os.path.join(work, "out")
    try:
        result = (build_fn or running.publish_build)(repo, out_dir)
    except outcomes.BuildError as e:
        shutil.rmtree(work, ignore_errors=True)
        raise DeployError("build refused: %s" % e)
    try:
        recheck_markup_only(markup_only, out_dir)       # after the build: it holds the record against THIS output
        run_gates(out_dir, repo, "the build")
    except DeployError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return repo, cfg, work, out_dir, result, note


def print_warnings(result, out):
    """Every `BuildResult.warnings` entry, one `warning: ` line each, as build.py and preview.py print them (dev #885,
    dev #882, gap 19): a publish run names a file the build left out (a stray .md, a sub-folder, an unknown piece key).
    Printing only: a warning never refuses and never changes a byte of the output or its digest."""
    for w in getattr(result, "warnings", None) or ():
        print("warning: " + acceptance.warning_line(w), file=out)


def review_summary(repo, digest):
    status, row = store.verdict_for(digest, repo)
    if row is None:
        return status, "review: NONE for this digest (run the review step)"
    return status, "review: " + review_rows.describe(status, row)      # a stand-in row says so (reviews.rows)
