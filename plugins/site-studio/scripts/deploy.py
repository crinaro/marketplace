#!/usr/bin/env python3
"""deploy.py -- build, verify and publish the site to the public repo (dev #835, design 7.3;
named changes S2, M5(a,c), M6, M11; amendment 1 guard (b), named changes AS2, AS5, AM2, AM3, AM8,
AM9). Python 3.9, standard library only.

    deploy.py --dry-run
    deploy.py --confirm <digest> "<commit message>"       [--repo R]

The PERSON'S YES comes between the two (design 7.4): the PreToolUse hook (publish_guard.py) asks
before `--confirm`. This script makes sure the yes approves exactly what was reviewed. It is NOT the
human act and does not pretend to be.

BOTH MODES, first, in order
  1. refuse when CLAUDE_CODE_REMOTE == "true" (the policy sentence, publish_guard.REMOTE_POLICY);
  2. refuse unless HEAD is on origin/main (named changes S2 and M11): `git fetch origin main`, then
     `git merge-base --is-ancestor HEAD origin/main`. The review-row commit that sits between a
     review and a publish is local until pushed, so a repo with an unpushed review commit refuses
     here and says to push it (a PR merge). A `claude/<name>` worktree branch is accepted when its
     HEAD is already on origin/main, never otherwise. The digest binds the BUILD, so this is not a
     reviewed-versus-published gap; it is the "public site matches a reviewed main" claim, measured.
  3. build with `build.publish_build` (design 3.5): the committed tree at HEAD, no drafts, no
     browser. A refusal there is one line.

--dry-run  runs every gate on the build, clones the public repo, replaces its tree with the output
(each file 0644), stages the EXPLICIT list of output paths plus `git rm` for vanished ones, makes a
LOCAL commit, refuses if any private path is in it, recomputes the digest from that commit's own
tree (`git ls-tree -r -z` + `git cat-file --batch`, never the working files) and refuses unless it
equals the build digest (this catches a global or repo `.gitignore` dropping a file, `core.autocrlf`
and a case collision), runs every gate again on that committed tree, and prints the changes, the
review row and `confirm: <digest>`. It writes `.site-studio/review/dryrun.json` ({digest, files,
...}): the record the hook reads, so N in the ask text comes from here and not from the model.

--confirm  repeats all of that for the digest it was given (refusing on a wrong digest or on no
covering review: `clear` or `accepted` for THIS digest), then pushes, confirms with `git ls-remote`
that the remote head IS the pushed commit, RE-READS the public repo (a fresh clone, digest again;
red "pushed, but the public tree differs from what you approved" if it differs), polls
`gh api repos/<o>/<r>/pages/builds/latest` every 10 s for up to 10 minutes, and appends what was
published to HANDOFF.md (left uncommitted: nothing here pushes the dev repo).
  exit 0  published: status built AND the build's commit is the pushed sha
  exit 1  refused, or red: errored build, or the public tree differs
  exit 3  AMBER: "pushed and verified; Pages has not finished building after 10 minutes" -- never
          reported as live

ARGUMENTS (M5(a)): argparse with allow_abbrev=False, so `--conf <digest>` is REFUSED (usage error,
exit 2) rather than accepted by the script and missed by the hook. `--confirm=<digest>` and a
reordered command line are accepted, and the hook matches them. `--dry-run` and `--confirm` are
mutually exclusive.

THE GATES are `check_site.py`, run as a subprocess: `python3 check_site.py <built tree> --repo
<dev repo>`, exit 0 = pass, anything else = a refusal carrying its first lines. That interface is
the SEAM with phase 1b (not merged when this was written): if `check_site.py` is not beside this
file the run is refused with "NOT CHECKED" -- a gate that cannot run is never a pass. Tests point
GATE_SCRIPT at a fake.

NO BROWSER (M6). Nothing here imports or launches one; test_deploy.py patches `subprocess.Popen`
to record every launch and `browser.find_chrome` to raise, and asserts none.

The public clone URL is `https://github.com/<publicRepo>.git`; `main(..., public_url=...)` overrides
it for tests (a local bare repo). The CLI exposes no such override.

GUARD (b) -- ONE TARGET, VERIFIED BEFORE THE PUSH, NEVER FORCED (amendment 1 section A4.2)
  `public_target(cfg)` is the one place the target is computed: ("<publicRepo>",
  "https://github.com/<publicRepo>.git", "refs/heads/main"), from site.json's `publicRepo` ONLY. A
  null publicRepo refuses (a missing value must not read as the repo name "None").
  `verify_public_target(...)` runs, in order, and each failure is a refusal that pushes nothing:
    V1  not the dev repo: the dev origin's owner/name (github_url.py, the one normaliser shared with V3)
        must differ from publicRepo, compared case-insensitively. An origin that does not resolve to
        a github.com owner/name (a local path, an SSH host alias) REFUSES with a named fix.
    V2  `gh api --method GET repos/<publicRepo>`: full_name is publicRepo (a rename redirect is
        named), visibility public, not archived, `permissions.push` true. No gh, or gh failing,
        refuses. WITH SSH, V2'S PERMISSION READ IS ABOUT THE gh LOGIN AND NOT THE KEY THAT PUSHES: it
        measures the account `gh` is logged in as, which is the pushing account only when git pushes
        over the https credential helper. It is a check on the repo's state, not on the key.
    V3  in the clone, `git remote get-url --push origin` names the same github.com repo as the pinned
        URL (a rewrite to SSH of the SAME repo passes; a rewrite to another repo or an alias host
        refuses, naming the rewrite).
    V4  the remote `main` is the base the clone was made from (absent, for a first publish), and the
        base is an ancestor of the commit. Otherwise "main moved": run the dry run again; never forced.
  WHERE THEY RUN: V1-V4 run in run_dry and run_confirm right after stage_and_verify has cloned and
  committed (so a dry run shows a problem before the review); repos.first-publish calls the same
  function. V4 RUNS AGAIN, immediately before the push, inside push_and_verify (after the
  `before_push` hook seam); the first run catches a moved main early, the second closes the window
  between the first and the push. push_and_verify REFUSES a Staged that verify_public_target has not
  passed, so a caller that forgets verification is loud, not unguarded.
  `push_main(clone, sha)` is the ONLY function that pushes: `git -c push.followTags=false push
  --porcelain --no-follow-tags origin <sha>:refs/heads/main`. No `--force`, no `+` refspec, no
  --delete/--mirror/--all/--tags; the porcelain flag for refs/heads/main must be a fast-forward or a
  new ref. test_deploy.NoForce asserts that SHAPE; test_deploy.RulesetStandIn runs it.
  AFTER the push, `ls-remote --heads --tags` before and after are compared: only refs/heads/main may
  differ, and it must equal the pushed sha. This is DETECTION, not prevention (the push has
  happened), and it excludes refs/pull/*, which GitHub changes whenever anyone opens a pull request.
  Test seams (never CLI flags): `public_url=` (a local bare repo), `dev_origin=` (V1's origin string),
  and the hooks `before_push`, `after_push`, `after_ls_remote`.

Imports github_url.py, publish_guard.py, review_record.py, siteconfig.py and platform_check.py as
plain modules; the names are written here so the package's reachable-script closure ships them.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build  # noqa: E402
import github_url  # noqa: E402
import publish_guard  # noqa: E402
import review_record  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402

GATE_SCRIPT = os.path.join(HERE, "check_site.py")
POLL_INTERVAL = 10
POLL_TIMEOUT = 600
GIT_TIMEOUT = 300
LIST_CAP = 60

# Paths that must never reach the public repo: private notes, the review store, the app's folders.
PRIVATE_SEGMENTS = (".site-studio", "decisions", ".claude", ".git", "originals")
PRIVATE_NAMES = ("claude.md", "handoff.md", "brand.md", "site.json")
EXIT_OK, EXIT_RED, EXIT_USAGE, EXIT_AMBER = 0, 1, 2, 3


class DeployError(Exception):
    """A refusal or a red result. The message is the line the person reads."""


# ---------------------------------------------------------------- git, small

def _git(cwd, *args, **kw):
    inp = kw.get("input")
    check = kw.get("check", True)
    timeout = kw.get("timeout", GIT_TIMEOUT)
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.run(("git", "-C", cwd) + args, input=inp, env=env, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise DeployError("git %s timed out after %ds" % (args[0], timeout))
    except OSError as e:
        raise DeployError("could not run git (%s)" % e)
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DeployError("git %s failed: %s" % (args[0], msg[-1] if msg else "exit %d" % p.returncode))
    if kw.get("full"):
        return p
    return p.stdout if kw.get("raw") else p.stdout.decode("utf-8", "replace")


def _toplevel(repo):
    return os.path.realpath(_git(repo, "rev-parse", "--show-toplevel").strip())


# ---------------------------------------------------------------- the refusals before any work

def refuse_if_remote():
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise DeployError(publish_guard.REMOTE_POLICY)


def require_head_on_origin_main(repo):
    """Named changes S2 and M11."""
    f = _git(repo, "fetch", "--quiet", "origin", "main", check=False, full=True, timeout=120)
    if f.returncode != 0:
        raise DeployError("cannot check that HEAD is on origin/main (git fetch origin main failed); "
                          "publishing needs the dev repo's origin")
    head = _git(repo, "rev-parse", "--short", "HEAD").strip()
    r = _git(repo, "merge-base", "--is-ancestor", "HEAD", "origin/main", check=False, full=True)
    if r.returncode == 1:
        branch = _git(repo, "branch", "--show-current").strip() or "a detached HEAD"
        raise DeployError("HEAD (%s, on %s) is not on origin/main: push the reviewed commit to main "
                          "first (a pull request merge), then publish" % (head, branch))
    if r.returncode != 0:
        raise DeployError("could not compare HEAD with origin/main")
    tip = _git(repo, "rev-parse", "origin/main").strip()
    full_head = _git(repo, "rev-parse", "HEAD").strip()
    if tip != full_head:
        n = _git(repo, "rev-list", "--count", "HEAD..origin/main").strip()
        return "note: HEAD is %s commit(s) behind origin/main; publishing it puts the older content live" % n
    return None


# ---------------------------------------------------------------- gates (the seam with check_site.py)

def run_gates(tree, repo, label):
    if not os.path.isfile(GATE_SCRIPT):
        raise DeployError("NOT CHECKED: %s is not present, so the gates (%s) cannot run, and "
                          "publishing is refused" % (os.path.basename(GATE_SCRIPT), label))
    p = subprocess.run([sys.executable, GATE_SCRIPT, "--out", tree, "--repo", repo], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=GIT_TIMEOUT)
    if p.returncode != 0:
        first = "; ".join(l for l in p.stdout.strip().splitlines()[:5])
        raise DeployError("a gate failed on %s: %s" % (label, first or "exit %d" % p.returncode))


# ---------------------------------------------------------------- materialising a commit's tree

def materialize(clone, rev, dest):
    """Write the blobs of `rev`'s tree into `dest`, read with `git ls-tree -r -z` and
    `git cat-file --batch` (never the working files). Returns the sorted list of paths."""
    raw = _git(clone, "ls-tree", "-r", "-z", "--full-tree", rev, raw=True)
    entries = []
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        meta, _tab, path = rec.partition(b"\t")
        mode, kind, sha = meta.decode("ascii").split()
        if kind != "blob" or mode == "120000":
            raise DeployError("the commit holds a %s at %s; only plain files are published"
                              % ("symlink" if mode == "120000" else kind, path.decode("utf-8", "replace")))
        entries.append((path.decode("utf-8", "surrogateescape"), sha))
    paths = []
    if entries:
        out = _git(clone, "cat-file", "--batch", input=("\n".join(s for _p, s in entries) + "\n").encode("ascii"),
                   raw=True)
        pos = 0
        for path, sha in entries:
            nl = out.index(b"\n", pos)
            head = out[pos:nl].split()
            if len(head) != 3 or head[1] != b"blob":
                raise DeployError("could not read blob %s from the commit" % sha)
            size = int(head[2])
            data = out[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
            full = os.path.join(dest, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(data)
            paths.append(path)
    return sorted(paths)


def commit_tree_digest(clone, rev, dest):
    os.makedirs(dest, exist_ok=True)
    paths = materialize(clone, rev, dest)
    return build.digest_output_tree(dest), paths


def forbidden(path):
    segs = [s.lower() for s in path.split("/")]
    base = segs[-1]
    return (any(s in PRIVATE_SEGMENTS for s in segs) or base in PRIVATE_NAMES
            or base.endswith(".pdf.json"))


# ---------------------------------------------------------------- the public clone

def clone_public(url, dest):
    _git(os.path.dirname(dest), "clone", "-q", url, dest)
    heads = _git(dest, "ls-remote", "--heads", "origin", "main").strip()
    if heads:
        _git(dest, "checkout", "-q", "-B", "main", "origin/main")
        return True
    _git(dest, "symbolic-ref", "HEAD", "refs/heads/main")
    return False


def replace_tree(clone, out_dir, files):
    for name in os.listdir(clone):
        if name == ".git":
            continue
        p = os.path.join(clone, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    for rel in files:
        dst = os.path.join(clone, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(os.path.join(out_dir, *rel.split("/")), "rb") as src, open(dst, "wb") as fh:
            fh.write(src.read())
        os.chmod(dst, 0o644)


def _nul(paths):
    return b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p in paths)


def stage(clone, files, had_head):
    """Stage the explicit output list, `git rm` the vanished. `git add` is run WITHOUT -f and its
    errors are tolerated on purpose: a path an ignore rule drops is caught by the commit-tree
    digest check, which is the design's mechanism (7.3 step 2.5), and says so."""
    _git(clone, "add", "--ignore-errors", "--pathspec-from-file=-", "--pathspec-file-nul",
         input=_nul(files), check=False, full=True)
    if had_head:
        old = [p.decode("utf-8", "surrogateescape") for p in
               _git(clone, "ls-tree", "-r", "-z", "--name-only", "HEAD", raw=True).split(b"\0") if p]
        gone = sorted(set(old) - set(files))
        if gone:
            _git(clone, "rm", "-q", "--cached", "--ignore-unmatch", "--pathspec-from-file=-",
                 "--pathspec-file-nul", input=_nul(gone))


def change_list(clone):
    raw = _git(clone, "diff", "--cached", "--name-status", "-z", "--no-renames", raw=True)
    parts = [p for p in raw.split(b"\0") if p]
    out = []
    for i in range(0, len(parts) - 1, 2):
        out.append((parts[i].decode("ascii"), parts[i + 1].decode("utf-8", "replace")))
    return out


class Staged(object):
    pass


def stage_and_verify(repo, out_dir, result, public_url, message, work, hooks=None):
    """Design 7.3 step 2, items 2-6. Returns a Staged (clone, commit, changes, tree_digest)."""
    clone = os.path.join(work, "public")
    had_head = clone_public(public_url, clone)
    replace_tree(clone, out_dir, result.files)
    stage(clone, result.files, had_head)
    changes = change_list(clone)
    st = Staged()
    st.clone, st.changes, st.had_head = clone, changes, had_head
    # The base this publish is built on (guard (b), V4): the public main as cloned, None for an empty repo.
    st.base = _git(clone, "rev-parse", "HEAD").strip() if had_head else None
    st.before = None
    st.verified = False
    if not changes:
        st.commit = None
        return st
    _git(clone, "commit", "-q", "-m", message)
    st.commit = _git(clone, "rev-parse", "HEAD").strip()
    names = [p for p in _git(clone, "ls-tree", "-r", "-z", "--name-only", "HEAD", raw=True).decode(
        "utf-8", "surrogateescape").split("\0") if p]
    bad = sorted(p for p in names if forbidden(p))
    if bad:
        raise DeployError("private path(s) in the commit, refusing: %s" % ", ".join(bad[:8]))
    verified = os.path.join(work, "verified")
    digest, paths = commit_tree_digest(clone, "HEAD", verified)
    if digest != result.digest:
        missing = sorted(set(result.files) - set(paths))
        extra = sorted(set(paths) - set(result.files))
        why = ""
        if missing:
            why = "; missing from the commit: %s (an ignore rule, e.g. core.excludesFile, may be dropping them)" % \
                  ", ".join(missing[:5])
        elif extra:
            why = "; not in the build: %s" % ", ".join(extra[:5])
        raise DeployError("the commit's tree does not match the build (build %s, commit %s)%s"
                          % (result.digest[:12], digest[:12], why))
    run_gates(verified, repo, "the committed tree")
    st.tree_digest = digest
    return st


# ---------------------------------------------------------------- guard (b): the pinned target

PUBLIC_REF = "refs/heads/main"
FIX_ORIGIN = "git remote set-url origin https://github.com/<owner>/<name>.git"


def public_target(cfg):
    """The ONE place the push target is computed: (publicRepo, clone/push URL, ref), from site.json's
    `publicRepo` only. A null publicRepo refuses: a missing value must not read as a repo name."""
    repo = cfg.publicRepo
    if not repo:
        raise DeployError("site.json has no publicRepo: nothing to publish to")
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
                          "github.com repository (%s). %s" % (public_repo, e, fix))
    if dev.lower() == public_repo.lower():
        raise DeployError("site.json's publicRepo is this dev repo. Publishing would overwrite your "
                          "private repo's main.")


def check_public_repo(public_repo, gh="gh"):
    """V2. The public repo is the one named, public, live, and this login can push to it. With SSH this
    is about the gh login, not the pushing key (module docstring)."""
    exe = shutil.which(gh)
    if not exe:
        raise DeployError("cannot check the public repo before pushing (gh is not installed). "
                          "Run /site-studio:setup's step 1.")
    try:
        p = subprocess.run([exe, "api", "--method", "GET", "repos/%s" % public_repo], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DeployError("cannot check the public repo before pushing (%s). Run /site-studio:setup's "
                          "step 1." % e.__class__.__name__)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DeployError("cannot check the public repo before pushing (%s). Run /site-studio:setup's "
                          "step 1." % (err[-1] if err else "gh exit %d" % p.returncode))
    try:
        d = json.loads(p.stdout.decode("utf-8"))
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except ValueError:
        raise DeployError("cannot check the public repo before pushing (gh returned something that is "
                          "not the repository). Run /site-studio:setup's step 1.")
    full = d.get("full_name")
    if not isinstance(full, str) or full.lower() != public_repo.lower():
        raise DeployError("the public repo is now %s. Update publicRepo in site.json"
                          % (full if isinstance(full, str) else "unreadable (no full_name)"))
    if d.get("visibility") != "public":
        raise DeployError("%s is not public (visibility: %s); publishing there would not publish a site"
                          % (public_repo, d.get("visibility")))
    if d.get("archived") is not False:
        raise DeployError("%s is archived, so it cannot be pushed to" % public_repo)
    perms = d.get("permissions")
    if not isinstance(perms, dict) or perms.get("push") is not True:
        raise DeployError("the GitHub login gh uses cannot push to %s" % public_repo)


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
            raise DeployError("git would push to %s, not the pinned target %s" % (push, pinned))
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


def push_main(clone, sha):
    """THE ONLY PUSH (guard (b)). `<sha>:refs/heads/main` is a plain refspec: a fast-forward or a new
    ref, never a `+` one. No --force, --force-with-lease, --mirror, --all, --tags or --delete. The
    porcelain status of refs/heads/main must be ' ' (fast-forward) or '*' (new ref)."""
    r = _git(clone, "-c", "push.followTags=false", "push", "--porcelain", "--no-follow-tags", "origin",
             "%s:refs/heads/main" % sha, check=False, full=True)
    flags = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].split(":")[-1] == PUBLIC_REF:
            flags.append((parts[0], parts[2] if len(parts) > 2 else ""))
    if r.returncode != 0 or not flags or any(f not in (" ", "*") for f, _s in flags):
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        detail = (flags[0][1] if flags and flags[0][1] else (err[-1] if err else "exit %d" % r.returncode))
        raise DeployError("the push to the public main was refused or not a fast-forward: %s" % detail)


# ---------------------------------------------------------------- shared start of both modes

def prepare(repo, hooks=None, build_fn=None):
    """Steps 1-3 and the gates on the build output. Returns (cfg, tmp dir, out_dir, result, note)."""
    refuse_if_remote()
    repo = _toplevel(repo)
    note = require_head_on_origin_main(repo)
    try:
        cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    except (siteconfig.SiteConfigError, OSError) as e:
        raise DeployError(str(e))
    public_target(cfg)      # a null publicRepo refuses here, before any build (dev #835, AM9)
    work = tempfile.mkdtemp(prefix="ss-deploy-")
    out_dir = os.path.join(work, "out")
    try:
        result = (build_fn or build.publish_build)(repo, out_dir)
    except build.BuildError as e:
        shutil.rmtree(work, ignore_errors=True)
        raise DeployError("build refused: %s" % e)
    try:
        run_gates(out_dir, repo, "the build")
    except DeployError:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return repo, cfg, work, out_dir, result, note


def review_summary(repo, digest):
    status, row = review_record.verdict_for(digest, repo)
    if row is None:
        return status, "review: NONE for this digest (run the review step)"
    ids = ", ".join(row["accepted"]) if row["accepted"] else "none"
    return status, "review: %s on %s, %d files opened, accepted %s" % (
        status, row["at"][:10], len(row["opened"]), ids)


# ---------------------------------------------------------------- --dry-run

def run_dry(repo, public_url=None, hooks=None, build_fn=None, out=None, dev_origin=None):
    out = out or sys.stdout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn)
    try:
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, "site-studio dry run", work, hooks)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        status, review = review_summary(repo, result.digest)
        if note:
            print(note, file=out)
        if st.commit is None:
            print("nothing to publish: the public repo already holds this exact build (digest %s)"
                  % result.digest, file=out)
            return EXIT_OK
        counts = {"A": 0, "M": 0, "D": 0}
        for code, _p in st.changes:
            counts[code[0]] = counts.get(code[0], 0) + 1
        print("dry run for %s: %d files in the build; %d added, %d changed, %d removed"
              % (cfg.publicRepo, len(result.files), counts["A"], counts["M"], counts["D"]), file=out)
        for code, path in st.changes[:LIST_CAP]:
            print("  %s %s" % ({"A": "+", "M": "~", "D": "-"}.get(code[0], "?"), path), file=out)
        if len(st.changes) > LIST_CAP:
            print("  ... and %d more" % (len(st.changes) - LIST_CAP), file=out)
        print(review, file=out)
        print("digest: %s" % result.digest, file=out)
        record = {"v": 1, "digest": result.digest, "files": len(result.files), "added": counts["A"],
                  "changed": counts["M"], "removed": counts["D"], "publicRepo": cfg.publicRepo,
                  "head": _git(repo, "rev-parse", "HEAD").strip(),
                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        path = os.path.join(repo, review_record.DRYRUN_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
        if status in ("clear", "accepted"):
            print("confirm: %s" % result.digest, file=out)
        else:
            print("not publishable yet: %s" % ("the review is BLOCKED" if status == "blocked"
                                               else "no review covers this digest"), file=out)
        return EXIT_OK
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- --confirm

def pages_status(owner_repo, gh="gh"):
    """(status, commit) from the latest Pages build, or None when it cannot be read."""
    exe = shutil.which(gh)
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "api", "repos/%s/pages/builds/latest" % owner_repo], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
        if p.returncode != 0:
            return None
        d = json.loads(p.stdout.decode("utf-8"))
        return str(d.get("status")), d.get("commit")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def poll_pages(owner_repo, sha, interval, timeout, sleep, now):
    """Returns ('published'|'errored'|'timeout', last status seen)."""
    deadline = now() + timeout
    last = None
    while True:
        st = pages_status(owner_repo)
        if st is not None:
            last = st[0]
            if st[0] == "built" and st[1] == sha:
                return "published", last
            if st[0] == "errored":
                return "errored", last
        if now() >= deadline:
            return "timeout", last
        sleep(interval)


def push_and_verify(st, url, digest, work, hooks, out):
    """Design 7.3 step 5, items 3-5: push; confirm with `git ls-remote` that the remote head IS the
    pushed commit; RE-READ the public repo (a fresh clone, digest again). Shared with repos.py's
    first publish. Raises DeployError on any difference.

    Guard (b): refuses a Staged that verify_public_target has not passed; the `before_push` hook seam
    (test-only) runs next, then V4 AGAIN immediately before push_main, so a main that moved after the
    first V4 is refused here, by us, rather than rejected by git. After the push the heads-and-tags
    listing is compared with the one taken just before it: DETECTION, not prevention."""
    if not getattr(st, "verified", False):
        raise DeployError("refusing to push: verify_public_target has not passed for this publish "
                          "(the pinned-target checks V1-V4 are not optional)")
    if hooks.get("before_push"):
        hooks["before_push"](url)
    before = check_remote_main(url, st)
    push_main(st.clone, st.commit)
    if hooks.get("after_push"):
        hooks["after_push"](url)
    after = list_refs(url, st.clone)
    remote = after.get(PUBLIC_REF)
    if remote != st.commit:
        raise DeployError("pushed, but the remote head is %s, not the commit that was pushed (%s)"
                          % (remote[:12] if remote else "missing", st.commit[:12]))
    changed = sorted(r for r in set(before) | set(after) if r != PUBLIC_REF and before.get(r) != after.get(r))
    if changed:
        raise DeployError("pushed, but another ref changed in the public repo while it was being "
                          "published (detected after the push, not prevented): %s" % ", ".join(changed[:5]))
    if hooks.get("after_ls_remote"):
        hooks["after_ls_remote"](url)
    reread = os.path.join(work, "reread")
    _git(work, "clone", "-q", "--depth", "1", "--branch", "main", url, os.path.join(work, "reread-clone"))
    rdigest, _paths = commit_tree_digest(os.path.join(work, "reread-clone"), "HEAD", reread)
    if rdigest != digest:
        raise DeployError("pushed, but the public tree differs from what you approved "
                          "(approved %s, public now %s)" % (digest[:12], rdigest[:12]))
    print("pushed %s and verified: the public tree has digest %s" % (st.commit[:12], digest), file=out)


def write_handoff(repo, cfg, sha, digest, files, pages):
    path = os.path.join(repo, "HANDOFF.md")
    old = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            old = fh.read()
    entry = ("%s## Published %s\n\n- public repo: %s\n- public sha: %s\n- digest: %s\n- files: %d\n- Pages: %s\n"
             % ("" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n"),
                time.strftime("%Y-%m-%d", time.gmtime()), cfg.publicRepo, sha, digest, files, pages))
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)


def run_confirm(repo, digest, message, public_url=None, hooks=None, build_fn=None, out=None,
                interval=None, timeout=None, sleep=time.sleep, now=time.time, dev_origin=None):
    out = out or sys.stdout
    hooks = hooks or {}
    interval = POLL_INTERVAL if interval is None else interval
    timeout = POLL_TIMEOUT if timeout is None else timeout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn)
    try:
        if result.digest != digest:
            raise DeployError("wrong digest: this build is %s but %s was confirmed; run --dry-run "
                              "again and confirm the digest it prints" % (result.digest[:12], digest[:12]))
        status, review = review_summary(repo, result.digest)
        if status == "none":
            raise DeployError("no privacy review covers this digest: run the review step first")
        if status == "blocked":
            raise DeployError("the privacy review for this digest is BLOCKED: resolve it and review again")
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, message, work, hooks)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        if st.commit is None:
            print("nothing to publish: the public repo already holds this exact build", file=out)
            return EXIT_OK
        try:
            push_and_verify(st, url, digest, work, hooks, out)
        except DeployError as e:
            if "differs from what you approved" in str(e):
                write_handoff(repo, cfg, st.commit, digest, len(result.files),
                              "NOT LIVE-CHECKED: public tree differs")
            raise
        verdict, last = poll_pages(cfg.publicRepo, st.commit, interval, timeout, sleep, now)
        if verdict == "published":
            write_handoff(repo, cfg, st.commit, digest, len(result.files), "built")
            print("published: Pages built %s" % st.commit[:12], file=out)
            return EXIT_OK
        if verdict == "errored":
            write_handoff(repo, cfg, st.commit, digest, len(result.files), "errored")
            print("RED: the Pages build errored for %s" % st.commit[:12], file=out)
            return EXIT_RED
        write_handoff(repo, cfg, st.commit, digest, len(result.files), "not finished (last status %s)" % last)
        print("AMBER: pushed and verified; Pages has not finished building after %d minutes (last status: %s)"
              % (max(1, int(timeout // 60)), last or "unknown"), file=out)
        return EXIT_AMBER
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- CLI

def main(argv=None, public_url=None, hooks=None, build_fn=None, interval=None, timeout=None,
         sleep=time.sleep, now=time.time, dev_origin=None):
    rc = platform_check.windows_refusal_rc("deploy.py")
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="deploy.py", allow_abbrev=False,
                                 description="Verify and publish the site (dev #835).")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="build, stage and verify; push nothing")
    mode.add_argument("--confirm", metavar="DIGEST", help="publish the build with this digest")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("message", nargs="?", help="the public commit message (with --confirm)")
    args = ap.parse_args(argv)
    if args.confirm is not None and not (args.message or "").strip():
        ap.error("--confirm needs the commit message as the last argument")
    if args.dry_run and args.message:
        ap.error("--dry-run takes no message")
    try:
        if args.dry_run:
            return run_dry(args.repo, public_url, hooks, build_fn, dev_origin=dev_origin)
        return run_confirm(args.repo, args.confirm, args.message.strip(), public_url, hooks, build_fn,
                           interval=interval, timeout=timeout, sleep=sleep, now=now, dev_origin=dev_origin)
    except (DeployError, review_record.ReviewError) as e:
        print("deploy refused: %s" % e)
        return EXIT_RED


if __name__ == "__main__":
    sys.exit(main())
