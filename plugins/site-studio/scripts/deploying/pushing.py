"""deploying.pushing -- `push_main`, THE ONLY PUSH, and `push_and_verify`, which wraps it (guard (b), design 7.3 step 5).

`push_main` pushes `<sha>:refs/heads/main` with no --force, no `+` refspec and none of --delete/--mirror/--all/--tags.
`test_deploy_confirm.NoForce` asserts that shape by reading this file and every other script for a push; the file that holds
the push is named in its allow-list.
"""
import os
from deploying.gitrun import DeployError, _git
from deploying.materialize import commit_tree_digest
from deploying.target import PUBLIC_REF, check_remote_main, list_refs


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
