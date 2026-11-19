"""deploying.addressguard -- the address guard (template-fidelity step 1.6, design section 8 A1) and the Pages-source read it needs (R2-5).

`guard_addresses` refuses while a path the public repo serves is neither built nor released in the committed
`.site-studio/addresses.json`; `check_pages_source` refuses unless Pages serves `main` at the root; `print_released` names
what a publish ends on purpose.
"""
import addresses
import json
import os
from pagesaudit import pagesitems
import shutil
import subprocess
from deploying.clone import public_paths
from deploying.constants import LIST_CAP
from deploying.gitrun import DeployError, NotChecked, _git


PAGES_TIMEOUT = 60       # one `gh api .../pages` read, the same bound as `pages_status`


def read_pages(owner_repo, gh="gh"):
    """The decoded `GET repos/<o>/<r>/pages` object, or None when Pages is OFF (a 404: a read, not a failure).
    Raises `NotChecked` when the question cannot be answered: no `gh`, a login that is not there, a timeout, or an
    answer that is not the Pages settings. One call, `PAGES_TIMEOUT` seconds, GET only (R2-5)."""
    exe = shutil.which(gh)
    if not exe:
        raise NotChecked("gh is not installed; install the GitHub CLI from https://cli.github.com")
    try:
        p = subprocess.run([exe, "api", "--method", "GET", "repos/%s/pages" % owner_repo], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=PAGES_TIMEOUT, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except subprocess.TimeoutExpired:
        raise NotChecked("gh did not answer within %d s; check the connection, then retry" % PAGES_TIMEOUT)
    except OSError as e:
        raise NotChecked("could not run gh (%s); reinstall the GitHub CLI, then retry" % e.__class__.__name__)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        last = err[-1] if err else "gh exited %d" % p.returncode
        if "HTTP 404" in last:
            return None
        raise NotChecked(last)
    try:
        d = json.loads(p.stdout.decode("utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except ValueError:
        raise NotChecked("gh returned something that is not the Pages settings; run `gh auth status`, then retry")
    return d


def check_pages_source(owner_repo, gh="gh"):
    """Refuse unless Pages serves `main` at the root, the tree publish pushes (R2-5). Returns a one-line note when
    Pages is off, else None. An unread source REFUSES, naming the error and "retry"; a workflow source (C4) or
    another branch or folder (C5) refuses with the check's own fix."""
    try:
        pages = read_pages(owner_repo, gh)
    except NotChecked as e:
        raise NotChecked("the Pages source of %s was not read (%s), and the address guard needs it: the public "
                         "repo's main is the served tree only when Pages serves it; retry the publish once gh "
                         "answers (`gh auth status` shows the login)" % (owner_repo, e))
    if pages is None:
        return ("Pages is not turned on for %s, so nothing is served from it yet; the address guard compared the "
                "build with the repo's main at the root" % owner_repo)
    item = pagesitems.pages_source(pages)
    if item is not None:
        raise DeployError("the public site is not served from main at the root, so the address guard cannot tell "
                          "which pages are live; the Pages source must be main at the root (%s): %s"
                          % (item.key, item.line))
    return None


def committed_record(repo):
    """`.site-studio/addresses.json` as HEAD holds it (empty when HEAD has none). HEAD is on origin/main by now
    (`require_head_on_origin_main`), so a drop that was never pushed is not honoured. A record the strict reader
    refuses refuses the publish."""
    if not _git(repo, "ls-tree", "--name-only", "HEAD", "--", addresses.RECORD_REL).strip():
        return addresses.empty()
    try:
        return addresses.parse(_git(repo, "show", "HEAD:" + addresses.RECORD_REL))
    except addresses.AddressError as e:
        raise DeployError(str(e))


def guard_addresses(repo, clone, build_paths, cfg=None, gh="gh"):
    """Pages source (when `cfg` names the public repo), then the address guard. Returns (released, note): the
    `[[path, reason]]` this publish ends on purpose, and the Pages note, if any. Refuses, listing each path with its
    own fix, while a public path is neither in the build nor released."""
    note = check_pages_source(cfg.publicRepo, gh) if cfg is not None else None
    record = committed_record(repo)
    public = public_paths(clone)
    left = addresses.dropped(public, build_paths, record)
    if left:
        raise DeployError(addresses.refusal(left, sorted(cfg.redirects) if cfg is not None else ()))
    return addresses.released(public, build_paths, record), note


def print_released(st, out):
    """What this publish ends on purpose: one line per released address, so the dry run names them and the person's
    approval of the publish can be an approval of them."""
    rel = getattr(st, "released", None) or []
    if not rel:
        return
    print("releases %d published address%s (recorded in .site-studio/addresses.json):"
          % (len(rel), "" if len(rel) == 1 else "es"), file=out)
    for path, reason in rel[:LIST_CAP]:
        print("  ! %s (%s)" % (path, reason), file=out)
    if len(rel) > LIST_CAP:
        print("  ... and %d more" % (len(rel) - LIST_CAP), file=out)
