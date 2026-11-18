"""adoption.publish -- steps 3 and 4 of the one-process `apply`: the publish through the existing `deploy.py` path, and the wait
for Pages (design 8 AO; "Ruled after R3N: one-process apply"; step 1.9f).

Part of the `adoption` package behind the entry point `adopt.py`.

THE CHOICE (named, as the brief asks): `deploy.py` is an entry point and nothing imports it, so `apply` RUNS it, as a
subprocess, `--dry-run` then `--confirm`, in a scratch CLONE of the dev repo checked out at the conversion commit. That is
the same code path `/site-studio:publish` takes (the same build, gates, address guard, V1 to V4, privacy review, push and Pages
poll), with `--adopt` standing in for "HEAD is on origin/main" (`adopt_head.py`: HEAD must be a fast-forward of it, because
step 5 pushes it). No shared module was made: moving `deploy.py`'s publish functions out would have rewritten a 1,229-line
entry point that this step may not grow. The person's yes is the guard's ask at `adopt.py apply` itself
(`publish_guard.py`), exactly as it is at `deploy.py --confirm`; the subprocess is not a Bash call, so nothing asks twice.

WHY A CLONE. The conversion commit is on no branch of the person's repo and is not on `origin/main` (a killed run must leave
that main unchanged), and `deploy.py` builds the committed tree at HEAD. A `git clone --shared` of the dev repo reads the
commit through the dev repo's own object store (an object a branch does not name is still readable), takes the dev repo's
`origin` URL (so V1 and V3 read the real one), the person's git identity, and writes nothing into the person's checkout, index
or refs. Step 5 (`finish.py`) archives the old builder in the same clone.

THE SEAMS (tests only; no flag reaches them): `deploy(argv, cwd) -> (exit code, text)` and `gh(argv, merge=False) -> (exit
code, stdout)`. The defaults run `deploy.py` and `gh`; a test drives `deploy.main` in this process against a local bare "public"
repo, or a fake `gh`, and every other line here runs for real.

A STOP is `Stop(step, why, next, cause=...)`: the run ended BLOCKED at that step, the dev repo's main is unchanged, the old builder
stays the publisher, and the person is told what to do. Every stop carries a CAUSE ID of the reporter's closed grammar
(`report_issue.cause_id`: `ss-adopt/apply/<stop>`, or `ss-adopt/env/pages-*` for what only Pages can answer), printed with the stop
and written in HANDOFF.md, so the reporter names it and says whether it is the person's, the environment's or the plugin's to resolve. The privacy review is a step of `/site-studio:publish` that a script cannot
take (an agent opens the files; the record is bound to the build's digest), so a build no review covers is handled by
`adoption.review_cover` (owner ruling 2026-11-18, F-1): a review made for the SAME digest carries over; failing that, parity EQUAL
stands in for the first review when every automated privacy scan passes on the exact built tree, and the run says so; ACCEPTED parity,
a scan finding, a blocked review and anything the scans could not check each stop at step 3 with that said: see `NEXT_REVIEW`.
"""

import json
import os
import re
import shutil
import subprocess
import sys

import github_url  # noqa: E402
import report_issue  # noqa: E402

from adoption import review_cover
from adoption.base import PLUGIN, git, gitt

DEPLOY = os.path.join(PLUGIN, "scripts", "deploy.py")
DEPLOY_TIMEOUT = 1800
GH_TIMEOUT = 60
PUBLIC_MESSAGE = "site-studio: publish the adopted site"
_DIGEST = re.compile(r"^confirm: ([0-9a-f]{64})$", re.M)
_PRINTED = re.compile(r"^digest: ([0-9a-f]{64})$", re.M)
_HOLDS = re.compile(r"^nothing to publish: the public repo already holds this exact build", re.M)
_REFUSED = re.compile(r"^deploy refused: (.*)$", re.M)
_NOT_YET = re.compile(r"^not publishable yet: (.*)$", re.M)
_RED = re.compile(r"^RED: .*$", re.M)
_AMBER = re.compile(r"^AMBER: .*$", re.M)

NEXT_RETRY = "fix what it says, delete this branch (`git branch -D <branch>`), and run `adopt.py apply` again"
NEXT_REVIEW = ("the privacy review is bound to the digest of the build apply publishes, and no review covers it yet: run "
               "/site-studio:review on a checkout of branch <branch>, then run `adopt.py apply` again with another `--date` (keep "
               "<branch> until then: a review made there for the same build carries over, and only for the same build) (nothing "
               "was published)")
NEXT_PAGES = ("wait until Pages shows the build as built, then run `adopt.py apply` again: it finds the public repo already "
              "holding this build and goes on to archive the old builder (delete the branch first: `git branch -D <branch>`)")


class Stop(Exception):
    """The run ends here, blocked. `step` is 3, 4 or 5 of the flow; `published` says site-studio's publish had already
    happened; `lines` are what to print before the stop."""

    def __init__(self, step, why, next_action, lines=(), published=False, *, cause):
        Exception.__init__(self, why)
        self.step, self.why, self.next_action, self.lines, self.published = step, why, next_action, list(lines), published
        report_issue.parse_cause(cause)           # a stop names a cause of the closed grammar, or it is not built
        self.cause = cause
        self.cover = None                         # the sentence about a carried or stood-in review, when this stop followed one


def run_deploy(argv, cwd):
    try:
        p = subprocess.run([sys.executable, "-B", DEPLOY] + list(argv), cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=DEPLOY_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "deploy refused: deploy.py did not finish in %d minutes" % (DEPLOY_TIMEOUT // 60)
    except OSError as e:
        return 127, "deploy refused: deploy.py could not start (%s)" % e.__class__.__name__
    return p.returncode, p.stdout.decode("utf-8", "replace")


def run_gh(argv, merge=False):
    exe = shutil.which("gh")
    if not exe:
        return 127, ""
    try:
        p = subprocess.run([exe] + list(argv), stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge else subprocess.PIPE,
                           timeout=GH_TIMEOUT, env=dict(os.environ, GH_PROMPT_DISABLED="1"))
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""
    return p.returncode, p.stdout.decode("utf-8", "replace")


def scratch_clone(repo, commit, work):
    """A clone of the dev repo under `work`, with the dev repo's origin URL and identity, checked out detached at `commit`."""
    clone = os.path.join(work, "dev")
    git(work, "clone", "-q", "--shared", "--no-checkout", repo, clone, timeout=300)
    git(clone, "remote", "set-url", "origin", gitt(repo, "remote", "get-url", "origin"))
    for key in ("user.name", "user.email"):
        value = gitt(repo, "config", "--get", key, check=False)
        if value:
            git(clone, "config", key, value)
    git(clone, "checkout", "-q", "--detach", commit)
    return clone


def dev_slug_of(repo):
    """`owner/name` of the dev repo's origin, or None when it is not a github.com repository."""
    try:
        return github_url.slug(gitt(repo, "remote", "get-url", "origin"))
    except github_url.GithubUrlError:
        return None


def _tail(text, n=3):
    return [l for l in text.strip().split("\n") if l.strip()][-n:]


def _reason(text, rc):
    found = _REFUSED.search(text) or _RED.search(text)
    if found:
        return found.group(0).replace("deploy refused: ", "")
    tail = _tail(text, 1)
    return tail[0] if tail else "deploy.py exited %d with no output" % rc


def check_no_run_in_progress(gh, dev_slug):
    """R3N-14: no workflow run is in progress on the dev repo (`gh run list --status in_progress`, read-only) before the
    publish, or the person is told to look. Returns [line]; raises Stop(3) when a run is going."""
    if not dev_slug:
        return ["step 3: NOT CHECKED whether a workflow is running on the dev repo (its origin is not a github.com "
                "repository this run can name); look at its Actions tab before you go on"]
    rc, out = gh(["run", "list", "--repo", dev_slug, "--status", "in_progress", "--json", "databaseId", "--limit", "5"])
    try:
        runs = json.loads(out) if rc == 0 else None
    except ValueError:
        runs = None
    if not isinstance(runs, list):
        return ["step 3: NOT CHECKED whether a workflow is running on %s (gh could not list its runs); look at its Actions "
                "tab before you go on" % dev_slug]
    if runs:
        raise Stop(3, "%d workflow run(s) are in progress on %s, and your old publisher may be one of them, so site-studio "
                      "would publish over it" % (len(runs), dev_slug),
                   "let them finish, then run `adopt.py apply` again (delete the branch first: `git branch -D <branch>`)",
                   cause=report_issue.cause_id("apply", "run-in-progress"))
    return []


def pages_built(gh, public_repo):
    """Step 4 on the path where the public repo already holds the build: Pages' latest build is `built` AND names the public
    repo's current main. Returns None, or raises Stop(4)."""
    rc, out = gh(["api", "repos/%s/pages/builds/latest" % public_repo])
    rc2, head = gh(["api", "repos/%s/branches/main" % public_repo, "--jq", ".commit.sha"])
    try:
        latest = json.loads(out) if rc == 0 else {}
    except ValueError:
        latest = {}
    if rc != 0 or rc2 != 0 or not isinstance(latest, dict) or "status" not in latest:
        raise Stop(4, "Pages' state for %s could not be read (gh), so it is not known that this build is live" % public_repo,
                   NEXT_PAGES, published=True, cause=report_issue.cause_id("env", "pages-unread"))
    if latest.get("status") == "built" and latest.get("commit") == head.strip():
        return None
    raise Stop(4, "the public repo already holds this exact build, but Pages has not reported it built (its latest build is "
                  "%s)" % latest.get("status"), NEXT_PAGES, published=True,
          cause=report_issue.cause_id("env", "pages-not-built"))


def covered(repo, clone, digest, out, cover):
    """The digest the dry run printed, with no review covering it: carry one, stand in, or stop at step 3 (`adoption.review_cover`).
    Returns the cover dict (`kind`, `note`, `lines`)."""
    try:
        return cover(clone, repo, digest)
    except review_cover.CoverRefused as e:
        if e.blocked:
            raise Stop(3, "the build cannot be published yet: %s" % e.reason, NEXT_RETRY, e.lines + _tail(out, 6),
                       cause=report_issue.cause_id("apply", "not-publishable"))
        raise Stop(3, "the build cannot be published yet: no review covers this digest, and neither a carried review nor the "
                      "parity-EQUAL stand-in applies (%s)" % e.reason, NEXT_REVIEW, e.lines + _tail(out, 6),
                   cause=report_issue.cause_id("apply", "no-review"))


def publish(repo, commit, work, deploy=None, gh=None, dev_slug=None, message=PUBLIC_MESSAGE, cover=None):
    """Steps 3 and 4. Returns {"clone", "digest", "lines", "cover"} when Pages reports the build built (`cover` is None, or the
    `review_cover.cover` answer when no review covered the build and one was carried or stood in); raises `Stop` otherwise. `cover`
    is the seam of that call."""
    deploy = deploy or run_deploy
    gh = gh or run_gh
    clone = scratch_clone(repo, commit, work)
    lines = check_no_run_in_progress(gh, dev_slug)
    rc, out = deploy(["--dry-run", "--adopt", "--repo", clone], clone)
    if rc != 0 or _REFUSED.search(out):
        raise Stop(3, "deploy.py --dry-run refused: %s" % _reason(out, rc), NEXT_RETRY, _tail(out, 6),
                   cause=report_issue.cause_id("apply", "publish-refused"))
    try:
        with open(os.path.join(clone, "site", "site.json"), encoding="utf-8") as fh:
            public_repo = json.load(fh).get("publicRepo")
    except (OSError, ValueError):
        public_repo = None
    if _HOLDS.search(out):
        lines.append("step 3: the public repo already holds this exact build; nothing to publish")
        pages_built(gh, public_repo)
        found = re.search(r"digest ([0-9a-f]{64})", out)
        return {"clone": clone, "digest": found.group(1) if found else None, "cover": None,
                "lines": lines + ["step 4: Pages reports it built"]}
    found = _DIGEST.search(out)
    got = None
    if not found:
        held = _NOT_YET.search(out)
        why = held.group(1) if held else "the dry run printed no confirm line"
        printed = _PRINTED.search(out)
        if "no review" not in why or not printed:
            raise Stop(3, "the build cannot be published yet: %s" % why, NEXT_REVIEW if "no review" in why else NEXT_RETRY,
                       _tail(out, 6), cause=report_issue.cause_id("apply", "no-review" if "no review" in why else "not-publishable"))
        got = covered(repo, clone, printed.group(1), out, cover or review_cover.cover)
        lines += got["lines"]
        found = printed
    digest = found.group(1)
    try:
        return _confirm(clone, digest, message, deploy, gh, public_repo, lines, got)
    except Stop as stop:
        if got:                                   # a stop after a carried or stood-in review says which, in its own printed lines
            stop.cover = got["note"]
        raise


def _confirm(clone, digest, message, deploy, gh, public_repo, lines, got):
    """Step 3's `--confirm` and step 4's wait. Returns what `publish` returns; raises `Stop`."""
    rc, out = deploy(["--confirm", digest, message, "--adopt", "--repo", clone], clone)
    if rc == 0 and ("published: Pages built" in out or _HOLDS.search(out)):
        if not _HOLDS.search(out):
            return {"clone": clone, "digest": digest, "cover": got,
                    "lines": lines + ["step 3: published digest %s to %s" % (digest[:12], public_repo or "the public repo"),
                                      "step 4: Pages built it"]}
        pages_built(gh, public_repo)
        return {"clone": clone, "digest": digest, "cover": got, "lines": lines + ["step 4: Pages reports it built"]}
    if rc == 3 or _AMBER.search(out):
        raise Stop(4, "site-studio published digest %s, and Pages has not finished building it" % digest[:12], NEXT_PAGES,
                   _tail(out, 4), published=True, cause=report_issue.cause_id("env", "pages-not-built"))
    if _RED.search(out):
        raise Stop(4, "site-studio published digest %s, and the Pages build errored" % digest[:12], NEXT_PAGES, _tail(out, 4),
                   published=True, cause=report_issue.cause_id("env", "pages-errored"))
    raise Stop(3, "deploy.py --confirm refused: %s" % _reason(out, rc), NEXT_RETRY, _tail(out, 6),
               cause=report_issue.cause_id("apply", "publish-refused"))
