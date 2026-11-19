"""deploying.preflight -- `deploy.py --preflight OUT`: the dry run's refusal set, read-only, against a build someone else made
(R3N-9, R3N-13). Prints one JSON object of causes and exits 1 when any BLOCKS.
"""
import addresses
import github_url
import json
import os
import shutil
import sys
import tempfile
from configschema import diagnostics, model
from deploying.gates import _gate_families
from deploying.addressguard import check_pages_source, read_pages
from deploying.clone import clone_public, public_paths
from deploying.constants import EXIT_OK, EXIT_RED
from deploying.gitrun import DeployError, NotChecked, _git, _toplevel
from deploying.target import check_not_dev_repo, check_public_repo, check_push_url, public_target


def run_preflight(out_dir, repo, tree=None, public_url=None, dev_origin=None, gh="gh", out=None):
    """The dry run's refusal set, read-only, against a build someone else made (module docstring, PREFLIGHT).
    Never raises for a cause: every refusal and every unanswered read becomes a row of the printed object."""
    out = out or sys.stdout
    repo = _toplevel(repo)
    tree = os.path.abspath(tree or repo)
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        raise DeployError("%s is not a built output folder; build the site, then pass its folder" % out_dir)
    causes = []

    def cause(name, state, detail):
        causes.append({"cause": name, "state": state, "detail": detail})
    try:
        cfg = model.load(os.path.join(tree, "site", "site.json"))
    except (diagnostics.SiteConfigError, OSError) as e:
        raise DeployError("cannot read site/site.json in %s: %s; point --tree at the folder that holds it" % (tree, e))
    build_paths = []
    for dirpath, _dirs, names in os.walk(out_dir):
        for name in names:
            build_paths.append(os.path.relpath(os.path.join(dirpath, name), out_dir).replace(os.sep, "/"))
    build_paths.sort()
    # the gates, offline, on the output as built
    fams, why = _gate_families(out_dir, tree)
    if why:
        cause("env/gates", "not-checked", "NOT CHECKED: %s, so the publish gates did not run" % why)
    for fam in fams:
        cause("publish/gate/%s" % fam, "blocks", "the %s gate has findings on this build; run check_site.py on it" % fam)
    # the publish target: no publicRepo, V1, V2, V3
    try:
        public_repo, pinned, _ref = public_target(cfg)
    except DeployError as e:
        cause("env/public-target", "blocks", str(e))
        return _print_preflight(causes, out)
    url = public_url or pinned
    dev_slug = None
    try:
        check_not_dev_repo(repo, public_repo, dev_origin)
        dev_slug = github_url.slug(dev_origin if dev_origin is not None else _git(repo, "remote", "get-url", "origin").strip())
    except github_url.GithubUrlError:
        pass
    except NotChecked as e:
        cause("env/public-target", "not-checked", "NOT CHECKED: %s" % e)
    except DeployError as e:
        cause("env/public-target", "blocks", str(e))
    try:
        check_public_repo(public_repo, gh)
    except NotChecked as e:
        cause("env/public-target", "not-checked", "NOT CHECKED: %s" % e)
    except DeployError as e:
        cause("env/public-target", "blocks", str(e))
    # which tree Pages serves: the public repo's, then the dev repo's own (a dev repo that serves Pages blocks)
    pages_readable = True
    try:
        check_pages_source(public_repo, gh)
    except NotChecked as e:
        pages_readable = False
        cause("env/pages-source", "not-checked", "NOT CHECKED: %s" % e)
    except DeployError as e:
        cause("publish/pages-workflow", "blocks", str(e))
    if dev_slug:
        try:
            if read_pages(dev_slug, gh) is not None:
                cause("publish/serves-dev-repo", "blocks", "the dev repo %s serves a Pages site itself, so the old "
                      "setup publishes from the repo that holds your source; move the source to a new private repo "
                      "and keep only the published site in %s, then run adopt again" % (dev_slug, public_repo))
        except NotChecked as e:
            if pages_readable:
                cause("env/pages-source", "not-checked", "NOT CHECKED: the dev repo's own Pages was not read (%s)" % e)
    # the address guard, against a fresh clone of the public repo
    work = tempfile.mkdtemp(prefix="ss-preflight-")
    try:
        clone = os.path.join(work, "public")
        try:
            had_head = clone_public(url, clone)
        except DeployError as e:
            cause("env/public-target", "not-checked", "NOT CHECKED: the public repo was not cloned (%s)" % e)
            return _print_preflight(causes, out)
        try:
            check_push_url(clone, url)
        except DeployError as e:
            cause("env/public-target", "blocks", str(e))
        if had_head:
            try:
                record = addresses.read_record_file(tree)
            except addresses.AddressError as e:
                cause("publish/address", "blocks", str(e))
            else:
                left = addresses.dropped(public_paths(clone), build_paths, record)
                if left:
                    cause("publish/address", "blocks", addresses.refusal(left, sorted(cfg.redirects)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return _print_preflight(causes, out)


def _print_preflight(causes, out):
    print(json.dumps({"v": 1, "causes": causes}, sort_keys=True), file=out)
    return EXIT_RED if any(c["state"] == "blocks" for c in causes) else EXIT_OK
