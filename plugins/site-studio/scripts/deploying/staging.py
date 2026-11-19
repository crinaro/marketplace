"""deploying.staging -- `stage_and_verify`: clone, address guard, stage, commit locally, refuse private paths, recompute the digest
from the commit's own tree and run the gates on it again (design 7.3 step 2, items 2-6).
"""
import os
from deploying.gates import run_gates
from deploying.addressguard import guard_addresses
from deploying.clone import Staged, change_list, clone_public, replace_tree, stage
from deploying.gitrun import DeployError, _git
from deploying.materialize import commit_tree_digest, forbidden


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
