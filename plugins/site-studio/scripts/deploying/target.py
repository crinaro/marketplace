"""deploying.target -- guard (b): ONE pinned target, verified before the push (amendment 1 section A4.2).

`public_target(cfg)` is the one place the target is computed; `verify_public_target` runs V1 (not the dev repo), V2 (the repo
is the one named, public, live, pushable), V3 (the push URL is the pinned repo) and V4 (the remote main is the base), and
marks the Staged verified, which `pushing.push_and_verify` requires.
"""
import github_url
import json
import os
import shutil
import subprocess
from deploying.gitrun import DeployError, NotChecked, _git


PUBLIC_REF = "refs/heads/main"
FIX_ORIGIN = "git remote set-url origin https://github.com/<owner>/<name>.git"


def public_target(cfg):
    """The ONE place the push target is computed: (publicRepo, clone/push URL, ref), from site.json's
    `publicRepo` only. A null publicRepo refuses: a missing value must not read as a repo name."""
    repo = cfg.publicRepo
    if not repo:
        raise DeployError("site.json has no publicRepo: nothing to publish to; set publicRepo to the public site repo (owner/name)")
    return repo, "https://github.com/%s.git" % repo, PUBLIC_REF


def check_not_dev_repo(repo, public_repo, dev_origin=None):
    """V1. The dev repo's origin must not be the public repo. `dev_origin` is the test seam for the
    origin string; otherwise `git remote get-url origin` (which has insteadOf already applied)."""
    origin = dev_origin if dev_origin is not None else _git(repo, "remote", "get-url", "origin").strip()
    try:
        dev = github_url.slug(origin)
    except github_url.GithubUrlError as e:
        if e.host and e.host != github_url.GITHUB_HOST:
            fix = ("your origin uses the host '%s', probably an SSH alias; publishing compares the dev "
                   "repo's origin with publicRepo by name and needs a github.com form. Set one: %s "
                   "(or git\x40github.com:<owner>/<name>.git)" % (e.host, FIX_ORIGIN))
        else:
            fix = "publishing compares the dev repo's origin with publicRepo by name. Set it: %s" % FIX_ORIGIN
        raise DeployError("cannot tell whether publicRepo (%s) is this dev repo: the origin is not a "
                          "github.com repository (%s). Fix: %s" % (public_repo, e, fix))
    if dev.lower() == public_repo.lower():
        raise DeployError("site.json's publicRepo is this dev repo. Publishing would overwrite your "
                          "private repo's main; set publicRepo to the separate public site repo.")


def check_public_repo(public_repo, gh="gh"):
    """V2. The public repo is the one named, public, live, and this login can push to it. With SSH this
    is about the gh login, not the pushing key (module docstring)."""
    exe = shutil.which(gh)
    if not exe:
        raise NotChecked("cannot check the public repo before pushing (gh is not installed). "
                          "Run /site-studio:setup's step 1.")
    try:
        p = subprocess.run([exe, "api", "--method", "GET", "repos/%s" % public_repo], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise NotChecked("cannot check the public repo before pushing (%s). Run /site-studio:setup's "
                          "step 1." % e.__class__.__name__)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise NotChecked("cannot check the public repo before pushing (%s). Run /site-studio:setup's "
                          "step 1." % (err[-1] if err else "gh exit %d" % p.returncode))
    try:
        d = json.loads(p.stdout.decode("utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except ValueError:
        raise NotChecked("cannot check the public repo before pushing (gh returned something that is "
                          "not the repository). Run /site-studio:setup's step 1.")
    full = d.get("full_name")
    if not isinstance(full, str) or full.lower() != public_repo.lower():
        raise DeployError("the public repo is now %s. Update publicRepo in site.json"
                          % (full if isinstance(full, str) else "unreadable (no full_name)"))
    if d.get("visibility") != "public":
        raise DeployError("%s is not public (visibility: %s); publishing there would not publish a site; make the repo public in its "
                          "GitHub settings, or set publicRepo to the public site repo"
                          % (public_repo, d.get("visibility")))
    if d.get("archived") is not False:
        raise DeployError("%s is archived, so it cannot be pushed to; unarchive it in its GitHub settings, or set publicRepo to another repo" % public_repo)
    perms = d.get("permissions")
    if not isinstance(perms, dict) or perms.get("push") is not True:
        raise DeployError("the GitHub login gh uses cannot push to %s; sign in as an account that can push (`gh auth login`), or ask the repo's owner for write access" % public_repo)


def _rewrite_lines(clone):
    r = _git(clone, "config", "--show-origin", "--get-regexp", r"^url\..*insteadof$", check=False, full=True)
    return [l.strip() for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()][:3]


def check_push_url(clone, pinned):
    """V3. In the clone, git's push URL names the pinned repo. `get-url --push` expands insteadOf and
    pushInsteadOf, so a rewrite to ANOTHER repo is caught here and named; a rewrite to SSH of the SAME
    repo passes (github_url normalises both). A pinned URL that is not a github.com URL (the test
    seam's local path) is compared exactly."""
    push = _git(clone, "remote", "get-url", "--push", "origin").strip()
    try:
        pinned_slug = github_url.slug(pinned)
    except github_url.GithubUrlError:
        if push != pinned:
            raise DeployError("git would push to %s, not the pinned target %s; remove the git `url.<base>.insteadOf` setting that rewrites the address, then publish again" % (push, pinned))
        return
    try:
        same = github_url.slug_equals(push, pinned_slug)
        problem = None
    except github_url.GithubUrlError as e:
        same, problem = False, str(e)
    if not same:
        rewrites = _rewrite_lines(clone)
        raise DeployError("git would push to %s, not %s%s%s. A url.<base>.insteadOf or pushInsteadOf "
                          "rewrite in your git config sends the push elsewhere; remove it or point it at "
                          "the same repo"
                          % (github_url.redact(push), pinned, " (%s)" % problem if problem else "",
                             " [%s]" % "; ".join(rewrites) if rewrites else ""))


def list_refs(url, cwd):
    """{ref: sha} from `git ls-remote --heads --tags <url>`. Heads and tags ONLY: GitHub also
    advertises refs/pull/*, which change whenever anyone opens a pull request (named change AM8)."""
    out = _git(cwd, "ls-remote", "--heads", "--tags", url)
    refs = {}
    for line in out.splitlines():
        sha, _tab, ref = line.partition("\t")
        if ref:
            refs[ref.strip()] = sha.strip()
    return refs


def check_remote_main(url, st):
    """V4, and its re-run immediately before the push. The remote main is where this publish started
    (st.base; absent for a first publish) and that base is an ancestor of the commit. Returns the
    `before` listing (heads and tags). Never resolved by forcing."""
    refs = list_refs(url, st.clone)
    now = refs.get(PUBLIC_REF)
    if now != st.base:
        raise DeployError("the public repo's main moved since this publish was prepared (now %s). Run "
                          "the dry run again." % (now[:12] if now else "absent"))
    if st.base and st.commit:
        r = _git(st.clone, "merge-base", "--is-ancestor", st.base, st.commit, check=False, full=True)
        if r.returncode != 0:
            raise DeployError("the public repo's main moved since this publish was prepared (the commit "
                              "is not built on %s). Run the dry run again." % st.base[:12])
    return refs


def verify_public_target(repo, cfg, st, public_url=None, dev_origin=None, gh="gh"):
    """Guard (b), before the push: V1, V2, V3, V4 in order (module docstring). `st` is the Staged that
    stage_and_verify returned (clone, base, commit). Marks it verified, which push_and_verify
    requires, and returns the `before` listing."""
    public_repo, pinned, _ref = public_target(cfg)
    url = public_url or pinned
    check_not_dev_repo(repo, public_repo, dev_origin)
    check_public_repo(public_repo, gh)
    check_push_url(st.clone, url)
    st.before = check_remote_main(url, st)
    st.verified = True
    return st.before
