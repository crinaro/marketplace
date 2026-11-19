"""deploying.headcheck -- the refusals before any work: a cloud session, and HEAD not on origin/main (named changes S2 and M11).
"""
import os
from guarding import texts
from deploying.gitrun import DeployError, _git


def refuse_if_remote():
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        raise DeployError(texts.REMOTE_POLICY)


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
