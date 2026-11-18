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

ARGUMENTS (M5(a)): argparse with allow_abbrev=False, so `--conf <digest>` is REFUSED (usage error, exit 2) rather than
accepted by the script and missed by the hook. `--confirm=<digest>` and a reordered command line are accepted, and the
hook matches them. `--dry-run` and `--confirm` are mutually exclusive. `--adopt` (with either) is `adopt.py apply`'s own:
HEAD may be one fast-forward ahead of origin/main instead of on it (adopt_head.py; 1.9f).

THE GATES are `check_site.py`, run as a subprocess: `python3 check_site.py <built tree> --repo <dev repo>`, exit 0 =
pass, anything else = a refusal carrying its first lines. If `check_site.py` is not beside this file the run is refused
with "NOT CHECKED" -- a gate that cannot run is never a pass. Tests point GATE_SCRIPT at a fake.

NO BROWSER (M6). Nothing here launches one; test_deploy.py patches `subprocess.Popen` and `browser.find_chrome`.

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

THE ADDRESS GUARD (template-fidelity step 1.6, design section 8 A1; `addresses.py` is its rules and its record).
  Every path the public repo's `main` serves today is an address someone may hold. In `run_dry` and `run_confirm`,
  right after `clone_public` and BEFORE `stage` (inside `stage_and_verify`), `guard_addresses` compares the
  clone's tracked paths with the build's output paths and REFUSES while any public path is neither built nor
  released in the committed `.site-studio/addresses.json` (read from HEAD, which `require_head_on_origin_main` has
  already put on origin/main, so a drop that was never pushed is not honoured and the existing "push the commit"
  line is what the person sees: R2-8). The refusal names each path's own fix. The guard applies to every site at
  every schema once 0.4.0 publishes (owner decision 6) and changes no byte of the build.
  WHICH TREE IS SERVED (R2-5, amends decision 14). The public `main /` is the served tree only when Pages says so.
  Before the guard, `check_pages_source` reads `gh api --method GET repos/<o>/<r>/pages` ONCE, with `pages_status`'s
  60 s timeout, and classifies it with `pages_check.pages_source` (C4 a workflow, C5 another branch or folder):
  either refuses with that item's own fix. A source that cannot be READ (no gh, no login, an API error, a timeout)
  REFUSES too, naming the error and "retry": publishing already needs `gh`, so an unread source is a stop, never a
  quiet assumption. A 404 is a read: Pages is off, nothing is served yet, and the guard says so and goes on.
  `deploy.py` never calls `pages_check.check()`. Both steps are skipped for an EMPTY public repo (nothing is
  public, so nothing can be released); `repos.py first-publish` is such a call.
  THE DRY RUN names what a publish ends on purpose: `released` (path and reason, a moved piece's files included), and
  records it in `dryrun.json` v2 (review_record.write_dryrun, step 1.6r). The publish ask names those addresses
  (publish_guard) and `run_confirm` refuses a list that is not the recorded one (review_record.released_refusal).
  `deploy.py drop <path>... --reason TEXT` releases addresses (U-8 answered: a subcommand dispatched before
  argparse, as `build.py raise-schema` is, so `--dry-run` and `--confirm` and the hook's reading of them are
  untouched; the publish guard decides nothing on it because it names no `--confirm`). It writes the record and
  `site.json` at the schema the tree then needs, commits exactly those two paths, and publishes nothing.
  THE MARKUP-ONLY RE-CHECK (R2-12). `check_adopt_record` hands back a MARKUP-ONLY record, and `prepare` re-runs
  `parity_classes.recheck` for its tokens against the build it has just made (so it needs `out_dir`): any token a
  stylesheet or script now names, any attribute selector or `attr(` now present, any off-origin stylesheet or script
  now loaded refuses, naming the token, with the fix `adopt.py remeasure`.

PREFLIGHT, `deploy.py --preflight OUT [--repo DEV] [--tree TREE]` (R3N-9, R3N-13): the dry run's refusal set,
read-only, against a build someone else made (section 8 AO step 2). `OUT` is a built output folder, `TREE` the
folder whose `site/site.json` and `.site-studio/addresses.json` that build used (the scratch tree adopt converted,
NOT HEAD; default DEV), `DEV` the dev repo whose `origin` V1 reads. It pushes nothing, writes no `dryrun.json` and
does not need HEAD on origin/main. It prints ONE JSON object, `{"v": 1, "causes": [{"cause", "state", "detail"}]}`,
and exits 1 when any cause BLOCKS, else 0. The causes, each from a plugin enumeration and never the site's text:
`publish/gate/<family>` (check_site's findings), `publish/address` (the guard), `publish/pages-workflow` (C4/C5, a
person cause), `publish/serves-dev-repo` (the DEV repo itself serves Pages, a person cause) and `env/public-target`
(no publicRepo, V1, V3, a V2 refusal: blocking, never filed). `state` is `blocks` or `not-checked`; ONLY a network
or `gh` that cannot answer (gh missing or not logged in, a timeout, an unreachable public repo) reads
`not-checked` (`env/public-target`, `env/pages-source`, `env/gates`) and lets the hand-over proceed: the first
publish runs the same checks for real.

Imports adopt_head.py, addresses.py, github_url.py, pages_check.py, parity_classes.py, publish_guard.py,
review_record.py, siteconfig.py and platform_check.py as plain modules; the names are written here so the package's
reachable-script closure ships them.
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

from adoption import parity as adopt  # noqa: E402     (the one strict reader of the adopt parity record: adoption/parity.py, which holds PARITY_RECORD_REL and PlanError by name too)
import adopt_head  # noqa: E402     (`--adopt`: the check that replaces "HEAD is on origin/main", step 1.9f)
import addresses  # noqa: E402     (the address record and the guard's rules, step 1.6)
import build  # noqa: E402
import github_url  # noqa: E402
import pages_check  # noqa: E402     (`pages_source`, the one classifier of the Pages source: R2-5)
import parity_classes  # noqa: E402     (the MARKUP-ONLY re-check: R2-12)
import publish_guard  # noqa: E402
import review_record  # noqa: E402
import siteconfig  # noqa: E402
import platform_check  # noqa: E402

GATE_SCRIPT = os.path.join(HERE, "check_site.py")
POLL_INTERVAL = 10
POLL_TIMEOUT = 600
GIT_TIMEOUT = 300
LIST_CAP = 60
PAGES_TIMEOUT = 60       # one `gh api .../pages` read, the same bound as `pages_status`

# Paths that must never reach the public repo: private notes, the review store, the app's folders.
PRIVATE_SEGMENTS = (".site-studio", "decisions", ".claude", ".git", "originals")
PRIVATE_NAMES = ("claude.md", "handoff.md", "brand.md", "site.json")
EXIT_OK, EXIT_RED, EXIT_USAGE, EXIT_AMBER = 0, 1, 2, 3


class DeployError(Exception):
    """A refusal or a red result. The message is the line the person reads."""


class NotChecked(DeployError):
    """A read that could not be made (no `gh`, not logged in, a timeout, an unreadable answer): the question was
    never answered. A DeployError to `run_dry` and `run_confirm`, which refuse on it; `--preflight` alone tells it
    apart, because there it is NOT CHECKED rather than a refusal."""


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
        raise DeployError("git %s timed out after %ds; check that git works in this repo (no prompt waiting for a credential), then publish again" % (args[0], timeout))
    except OSError as e:
        raise DeployError("could not run git (%s); install git, or check that `git --version` works in a terminal, then publish again" % e)
    if check and p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DeployError("git %s failed: %s; fix what git reports, then publish again" % (args[0], msg[-1] if msg else "exit %d" % p.returncode))
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
        raise DeployError("could not compare HEAD with origin/main; run `git fetch origin` in the dev repo, then publish again")
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
                          "publishing is refused; update or reinstall the plugin, then publish again" % (os.path.basename(GATE_SCRIPT), label))
    p = subprocess.run([sys.executable, GATE_SCRIPT, "--out", tree, "--repo", repo], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=GIT_TIMEOUT)
    if p.returncode != 0:
        first = "; ".join(l for l in p.stdout.strip().splitlines()[:5])
        raise DeployError("a gate failed on %s: %s; fix what it reports, then publish again" % (label, first or "exit %d" % p.returncode))


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
                raise DeployError("could not read blob %s from the commit; run the dry run again, and if it repeats, check the dev repo with `git fsck`" % sha)
            size = int(head[2])
            data = out[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
            full = os.path.join(dest, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(data)
            paths.append(path)
    return sorted(paths)


def commit_tree_digest(clone, rev, dest, site_kind="portfolio"):
    """The build digest of what a commit holds. `site_kind` is the kind the BUILD was made with
    (`PublishResult.site_kind`): a hub or custom build's digest carries one final `siteKind` line and the
    public clone holds no `site.json` to say so, so the caller names it, or every hub publish is
    refused as a tree that does not match its own build (dev #857, site-adoption D2)."""
    os.makedirs(dest, exist_ok=True)
    paths = materialize(clone, rev, dest)
    return build.digest_output_tree(dest, site_kind), paths


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


# ---------------------------------------------------------------- the address guard (design section 8 A1)

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
    item = pages_check.pages_source(pages)
    if item is not None:
        raise DeployError("the public site is not served from main at the root, so the address guard cannot tell "
                          "which pages are live; the Pages source must be main at the root (%s): %s"
                          % (item.key, item.line))
    return None


def public_paths(clone):
    """Every path the clone's HEAD tracks: the addresses the public repo serves."""
    raw = _git(clone, "ls-tree", "-r", "-z", "--name-only", "HEAD", raw=True)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


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


def stage_and_verify(repo, out_dir, result, public_url, message, work, hooks=None, cfg=None, gh="gh"):
    """Design 7.3 step 2, items 2-6. Returns a Staged (clone, commit, changes, tree_digest). `cfg` is the site
    config: with it, and a public repo that holds something, the Pages source is read first (R2-5). The address
    guard runs right after the clone, before anything is staged (section 8 A1)."""
    clone = os.path.join(work, "public")
    had_head = clone_public(public_url, clone)
    released, pages_note = guard_addresses(repo, clone, result.files, cfg, gh) if had_head else ([], None)
    replace_tree(clone, out_dir, result.files)
    stage(clone, result.files, had_head)
    changes = change_list(clone)
    st = Staged()
    st.clone, st.changes, st.had_head = clone, changes, had_head
    st.released, st.pages_note = released, pages_note
    st.site_kind = getattr(result, "site_kind", "portfolio")     # push_and_verify's read-back digests with it
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
        raise DeployError("private path(s) in the commit, refusing: %s; nothing was pushed. Run the dry run again, and if it names the same path, do not publish: this is a plugin fault to report" % ", ".join(bad[:8]))
    verified = os.path.join(work, "verified")
    digest, paths = commit_tree_digest(clone, "HEAD", verified, st.site_kind)
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
        raise DeployError("the push to the public main was refused or not a fast-forward: %s; run the dry run again, then publish, and if it repeats act on the reason above" % detail)


# ---------------------------------------------------------------- the adopt publish gate (site-fidelity 5.0.4)

def check_adopt_record(repo):
    """Refuse to publish over a site whose adopt measured a difference from the person's own builder. When
    HEAD carries `.site-studio/adopt-parity.json` and its verdict is not EQUAL, ACCEPTED or MARKUP-ONLY,
    site-studio's build differs from what that builder publishes, so the builder stays the publisher until
    `adopt.py remeasure` says otherwise. No record is 0.2.0's behaviour (a site made by setup, or adopted by
    0.2.0); an unreadable record refuses, naming the file. Returns the record when its verdict is MARKUP-ONLY, for
    `recheck_markup_only` to hold against the build once it is made (R2-12), else None."""
    shown = _git(repo, "show", "HEAD:" + adopt.PARITY_RECORD_REL, check=False, full=True)
    if shown.returncode != 0:
        return None
    try:
        rec = adopt.parse_parity_record(shown.stdout.decode("utf-8", "replace"))
    except adopt.PlanError as e:
        raise DeployError("%s (fix or delete the file, or run `adopt.py remeasure`)" % e)
    if rec["verdict"] in ("EQUAL", "ACCEPTED"):
        return None
    if rec["verdict"] == "MARKUP-ONLY":
        return rec
    raise DeployError(adopt_refusal(rec))


def recheck_markup_only(rec, out_dir):
    """R2-12. MARKUP-ONLY is a property of the CSS and scripts PRESENT, not of the class names alone, so an
    unrelated later commit can make a recorded token visible. Re-run rules 3 to 5 (`parity_classes.recheck`) for
    the record's `tokens` against the build just made, in `out_dir`, and refuse on any token a stylesheet or script
    now names, an attribute selector or `attr(` now present, or an off-origin stylesheet or script now loaded. The
    cheap record parse and the refusal of every other verdict stay in `check_adopt_record`, before the build."""
    if rec is None:
        return
    files = {}
    for dirpath, _dirs, names in os.walk(out_dir):
        for name in names:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                files[os.path.relpath(full, out_dir).replace(os.sep, "/")] = fh.read()
    tokens = rec.get("tokens")
    if not isinstance(tokens, dict):
        raise DeployError("the adopt parity record says MARKUP-ONLY but lists no tokens to hold against the build; "
                          "run `adopt.py remeasure`")
    now = parity_classes.recheck(tokens, files)
    if now:
        first = ["%s %s: %s" % (k, n, why) if n else why for k, n, why in now[:3]]
        raise DeployError("this site was adopted with parity MARKUP-ONLY, but the build now has %d reason%s a "
                          "recorded difference is visible (%s%s); the record no longer holds. Run `adopt.py "
                          "remeasure`" % (len(now), "" if len(now) == 1 else "s", "; ".join(first),
                                          "; ..." if len(now) > 3 else ""))


def adopt_refusal(rec):
    """The refusal sentence for a record whose verdict is not EQUAL or ACCEPTED. One per verdict, because each has
    a different truth and a different way out (design-site-fidelity 5.0.4 and 8.3; deployment-auditor gap 15):
    DIFFERENT was measured and listed (`remeasure --accept` after reading it); NOT APPLICABLE measured nothing
    because no builder was found (`remeasure --accept` is "site-studio's build replaces my site, unmeasured");
    UNVERIFIED could not measure and `--accept` refuses it, so the only way out is to make it measurable (install
    node) and run `remeasure` again. The gate itself is unchanged: all three refuse."""
    verdict = rec["verdict"]
    if verdict == "NOT APPLICABLE":
        return ("this site was adopted with parity NOT APPLICABLE: adopt found no builder of your own to compare "
                "site-studio's build against, so nothing was measured, and publishing with site-studio would "
                "replace what your site publishes today, unmeasured. If you accept that, run `adopt.py remeasure "
                "--accept`. If a builder of yours should be compared, put it in the repo and run `adopt.py "
                "remeasure`.")
    if verdict == "UNVERIFIED":
        return ("this site was adopted with parity UNVERIFIED: adopt could not measure (there is no node on this "
                "computer, your builder failed, or site-studio's build refused the converted tree; `adopt.py "
                "remeasure` prints which), so it is not known whether site-studio's build differs from what your "
                "builder publishes. Your builder stays your publisher. `adopt.py remeasure --accept` refuses "
                "UNVERIFIED, because nothing was measured to show you. Install node if it is missing, fix the "
                "builder if it failed, or settle what site-studio's build refuses, then run `adopt.py remeasure` "
                "again.")
    diffs = rec["differences"]
    first = ("; first: %s %s" % (diffs[0][1], diffs[0][0])) if diffs else ""
    return ("this site was adopted with parity %s: site-studio's build differs from what your own builder "
            "publishes (%d difference%s%s). Your builder stays your publisher. Run `adopt.py remeasure`, "
            "or accept the listed differences with `adopt.py remeasure --accept`."
            % (verdict, len(diffs), "" if len(diffs) == 1 else "s", first))


# ---------------------------------------------------------------- shared start of both modes

def prepare(repo, hooks=None, build_fn=None, adopt=False):
    """Steps 1-3 and the gates on the build output. Returns (cfg, tmp dir, out_dir, result, note)."""
    refuse_if_remote()
    repo = _toplevel(repo)
    note = adopt_head.require_head_ahead_of_origin_main(_git, repo, DeployError) if adopt else require_head_on_origin_main(repo)
    try:
        cfg = siteconfig.load(os.path.join(repo, "site", "site.json"))
    except (siteconfig.SiteConfigError, OSError) as e:
        raise DeployError(str(e))
    public_target(cfg)      # a null publicRepo refuses here, before any build (dev #835, AM9)
    markup_only = check_adopt_record(repo)
    work = tempfile.mkdtemp(prefix="ss-deploy-")
    out_dir = os.path.join(work, "out")
    try:
        result = (build_fn or build.publish_build)(repo, out_dir)
    except build.BuildError as e:
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
        print("warning: " + build.warning_line(w), file=out)


def review_summary(repo, digest):
    status, row = review_record.verdict_for(digest, repo)
    if row is None:
        return status, "review: NONE for this digest (run the review step)"
    return status, "review: " + review_record.review_rows.describe(status, row)      # a stand-in row says so (reviews.rows)


# ---------------------------------------------------------------- --dry-run

def run_dry(repo, public_url=None, hooks=None, build_fn=None, out=None, dev_origin=None, adopt=False):
    out = out or sys.stdout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn, adopt)
    try:
        print_warnings(result, out)
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, "site-studio dry run", work, hooks, cfg=cfg)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        status, review = review_summary(repo, result.digest)
        if note:
            print(note, file=out)
        if st.pages_note:
            print(st.pages_note, file=out)
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
        print_released(st, out)
        print(review, file=out)
        print("digest: %s" % result.digest, file=out)
        review_record.write_dryrun(repo, {
            "v": review_record.DRYRUN_VERSION, "digest": result.digest, "files": len(result.files), "added": counts["A"],
            "changed": counts["M"], "removed": counts["D"], "publicRepo": cfg.publicRepo, "released": st.released,
            "head": _git(repo, "rev-parse", "HEAD").strip(), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
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
                          "(the pinned-target checks V1-V4 are not optional); run the dry run again, then publish with the digest it prints")
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
                          "published (detected after the push, not prevented): %s; check those refs on GitHub before you publish again" % ", ".join(changed[:5]))
    if hooks.get("after_ls_remote"):
        hooks["after_ls_remote"](url)
    reread = os.path.join(work, "reread")
    _git(work, "clone", "-q", "--depth", "1", "--branch", "main", url, os.path.join(work, "reread-clone"))
    rdigest, _paths = commit_tree_digest(os.path.join(work, "reread-clone"), "HEAD", reread,
                                         getattr(st, "site_kind", "portfolio"))
    if rdigest != digest:
        raise DeployError("pushed, but the public tree differs from what you approved "
                          "(approved %s, public now %s); run /site-studio:publish again to review what is public now" % (digest[:12], rdigest[:12]))
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
                interval=None, timeout=None, sleep=time.sleep, now=time.time, dev_origin=None, adopt=False):
    out = out or sys.stdout
    hooks = hooks or {}
    interval = POLL_INTERVAL if interval is None else interval
    timeout = POLL_TIMEOUT if timeout is None else timeout
    repo, cfg, work, out_dir, result, note = prepare(repo, hooks, build_fn, adopt)
    try:
        print_warnings(result, out)
        if result.digest != digest:
            raise DeployError("wrong digest: this build is %s but %s was confirmed; run --dry-run "
                              "again and confirm the digest it prints" % (result.digest[:12], digest[:12]))
        status, review = review_summary(repo, result.digest)
        if status == "none":
            raise DeployError("no privacy review covers this digest: run /site-studio:review first")
        if status == "blocked":
            raise DeployError("the privacy review for this digest is BLOCKED: resolve it and review again")
        url = public_url or public_target(cfg)[1]
        st = stage_and_verify(repo, out_dir, result, url, message, work, hooks, cfg=cfg)
        verify_public_target(repo, cfg, st, public_url, dev_origin)
        if st.pages_note:
            print(st.pages_note, file=out)
        print_released(st, out)
        refusal = review_record.released_refusal(repo, digest, st.released)
        if refusal:
            raise DeployError(refusal)
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


# ---------------------------------------------------------------- drop: release a published address on purpose

def run_drop(repo, paths, reason, out=None):
    """`deploy.py drop <path>... --reason TEXT` (design section 8 A1). Records each path as released in
    `.site-studio/addresses.json`, writes `site.json` at the schema that then needs (4: the guard reason, so every
    0.3.x install refuses the tree), and COMMITS those two paths and nothing else. It publishes nothing and asks
    nothing: the next dry run lists the released addresses and the publish ask names them. It refuses, writing
    nothing, on a dirty `site/`, `content/` or `.site-studio/`, a tree below schema 3 or holding a part name schema
    4 fixes (the raise-schema pre-write check, R2-3), a path that is not an output path, and a tree the build would
    refuse once the record exists. A cloud session is NOT refused (R2-6): this is a content edit."""
    out = out or sys.stdout
    reason = (reason or "").strip()
    if not reason or "\n" in reason:
        raise DeployError("--reason needs one line saying why the address is released (a visitor or a search "
                          "result may still use it)")
    try:
        repo = _toplevel(repo)
        for path in paths:
            addresses.check_path(path, "the path")
        addresses.require_clean(repo)
        files = build._disk_files(repo)
        raw = files.get("site/site.json")
        if raw is None:
            raise DeployError("site/site.json is not in this folder; run this inside the dev repo")
        cfg = siteconfig.parse_text(raw.decode("utf-8", "replace"))
        addresses.check_prewrite(cfg, files)
        before = addresses.read_record_file(repo)
        after = addresses.merge(before, dropped=[(p, reason) for p in sorted(set(paths))])
        if after == before:
            print("nothing to record: %s already released" % ", ".join(sorted(set(paths))), file=out)
            return EXIT_OK
        text = addresses.dump(after)
        site_json = addresses.site_json_text(cfg, files, text)
        tree = dict(files)
        tree["site/site.json"] = site_json.encode("utf-8")
        tree[addresses.RECORD_REL] = text.encode("utf-8")
        acc = build.accept(dict((k, v) for k, v in tree.items() if k.startswith(("site/", "content/"))))
        if acc.problems:
            raise DeployError("the site would not build once the address record exists (%s); fix that first, "
                              "then run drop again" % acc.problems[0].line())
    except (addresses.AddressError, build.BuildError, siteconfig.SiteConfigError) as e:
        raise DeployError(str(e))
    addresses.write_text(repo, addresses.RECORD_REL, text)
    addresses.write_text(repo, "site/site.json", site_json)
    new = sorted(set(paths) - set(d["path"] for d in before["dropped"]))
    _git(repo, "add", "--", addresses.RECORD_REL, "site/site.json")
    _git(repo, "commit", "-q", "-m", "site-studio: release %d published address%s" % (
        len(new), "" if len(new) == 1 else "es"), "--", addresses.RECORD_REL, "site/site.json")
    print("released %d published address%s, committed (%s and site/site.json):"
          % (len(new), "" if len(new) == 1 else "es", addresses.RECORD_REL), file=out)
    for path in new:
        print("  ! %s (%s)" % (path, reason), file=out)
    print("nothing is published yet. Push this commit to the main branch (a pull request merge), run the dry run, "
          "which lists these addresses, then confirm.", file=out)
    return EXIT_OK


def drop_main(argv):
    ap = argparse.ArgumentParser(prog="deploy.py drop", allow_abbrev=False,
                                 description="Release published addresses on purpose; publishes nothing.")
    ap.add_argument("paths", nargs="+", metavar="PATH", help="an output path the live site serves today")
    ap.add_argument("--reason", required=True, help="one line: why the address is released")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    args = ap.parse_args(argv)
    try:
        return run_drop(args.repo, args.paths, args.reason)
    except DeployError as e:
        print("drop refused: %s" % e)
        return EXIT_RED


# ---------------------------------------------------------------- --preflight

def _gate_families(out_dir, tree):
    """(families that have findings, NOT CHECKED reason or None) from `check_site.py --out --json`, offline."""
    if not os.path.isfile(GATE_SCRIPT):
        return [], "%s is not present" % os.path.basename(GATE_SCRIPT)
    p = subprocess.run([sys.executable, GATE_SCRIPT, "--out", out_dir, "--repo", tree, "--json"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=GIT_TIMEOUT)
    if p.returncode not in (0, 1):
        return [], "the gates exited %d" % p.returncode
    fams = set()
    for line in p.stdout.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("level") == "error" and isinstance(rec.get("family"), str):
            fams.add(rec["family"])
    return sorted(fams), None


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
        cfg = siteconfig.load(os.path.join(tree, "site", "site.json"))
    except (siteconfig.SiteConfigError, OSError) as e:
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


# ---------------------------------------------------------------- CLI

def main(argv=None, public_url=None, hooks=None, build_fn=None, interval=None, timeout=None,
         sleep=time.sleep, now=time.time, dev_origin=None):
    rc = platform_check.windows_refusal_rc("deploy.py")
    if rc is not None:
        return rc
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "drop":          # a subcommand, dispatched as `build.py raise-schema` is (U-8)
        return drop_main(argv[1:])
    ap = argparse.ArgumentParser(prog="deploy.py", allow_abbrev=False,
                                 description="Verify and publish the site. `deploy.py drop PATH...` releases a "
                                             "published address on purpose and publishes nothing.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="build, stage and verify; push nothing")
    mode.add_argument("--confirm", metavar="DIGEST", help="publish the build with this digest")
    mode.add_argument("--preflight", metavar="OUT", help="the dry run's refusals against a build in OUT; read-only")
    ap.add_argument("--repo", default=".", help="the dev repo (default: the current folder)")
    ap.add_argument("--tree", default=None, help="with --preflight: the folder holding the site/site.json and "
                                                 ".site-studio/addresses.json the build used (default: --repo)")
    ap.add_argument("--adopt", action="store_true", help="adopt.py apply only: HEAD may be one fast-forward ahead of origin/main")
    ap.add_argument("message", nargs="?", help="the public commit message (with --confirm)")
    args = ap.parse_args(argv)
    if args.adopt and args.preflight is not None:
        ap.error("--adopt is for --dry-run and --confirm")
    if args.tree is not None and args.preflight is None:
        ap.error("--tree is only for --preflight")
    if args.preflight is not None and args.message:
        ap.error("--preflight takes no message")
    if args.confirm is not None and not (args.message or "").strip():
        ap.error("--confirm needs the commit message as the last argument")
    if args.dry_run and args.message:
        ap.error("--dry-run takes no message")
    try:
        if args.preflight is not None:
            return run_preflight(args.preflight, args.repo, args.tree, public_url, dev_origin)
        if args.dry_run:
            return run_dry(args.repo, public_url, hooks, build_fn, dev_origin=dev_origin, adopt=args.adopt)
        return run_confirm(args.repo, args.confirm, args.message.strip(), public_url, hooks, build_fn, interval=interval,
                           timeout=timeout, sleep=sleep, now=now, dev_origin=dev_origin, adopt=args.adopt)
    except (DeployError, review_record.ReviewError) as e:
        print("deploy refused: %s" % e)
        return EXIT_RED


if __name__ == "__main__":
    sys.exit(main())
