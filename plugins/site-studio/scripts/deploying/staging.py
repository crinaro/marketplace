"""deploying.staging -- `stage_and_verify`: clone, address guard, stage, commit locally, refuse private paths, recompute the digest
from the commit's own tree and run the gates on it again (design 7.3 step 2, items 2-6).

`staged_mismatch` is the same question asked of the INDEX alone (dev 1068, design 1.2): `git add` and `git write-tree` in a clone of the
public repo, no commit, so no signature and no identity; the tree it writes is read back as the publish reads a commit, and its digest is
compared with the build's. A global ignore rule, a clean filter or a line-ending setting that would change what the public repo holds
shows here, and an ignore rule does not drop a file the public repo already tracks, so only its own clone can answer.
"""
import os
from building import digest as digest_mod
from deploying.gates import run_gates
from deploying.addressguard import guard_addresses
from deploying.clone import Staged, change_list, clone_public, replace_tree, stage
from deploying.gitrun import DeployError, _git, quiet_git
from deploying.materialize import commit_tree_digest, forbidden


def digest_mismatch(files, paths, want, got, what="commit"):
    """The sentence for a staged tree whose digest is not the build's (`want`), or None when it is. `files` are the build's paths and
    `paths` those the tree holds; `what` says which tree ("commit", or "staged" for the index)."""
    if got == want:
        return None
    subject = "the commit's tree" if what == "commit" else "the staged tree"
    holder = "the commit" if what == "commit" else "the staged tree"
    missing = sorted(set(files) - set(paths))
    extra = sorted(set(paths) - set(files))
    why = ""
    if missing:
        why = "; missing from %s: %s (an ignore rule, e.g. core.excludesFile, may be dropping them)" % (holder, ", ".join(missing[:5]))
    elif extra:
        why = "; not in the build: %s" % ", ".join(extra[:5])
    return "%s does not match the build (build %s, %s %s)%s" % (subject, want[:12], what, got[:12], why)


def staged_mismatch(clone, out_dir, files, had_head, site_kind, work):
    """None when the index the build would make in `clone` holds exactly the build, else the sentence that says what differs. Index
    only, and every git call without hooks (`quiet_git`); `clone` is a scratch clone of the public repo."""
    with quiet_git():
        replace_tree(clone, out_dir, files)
        stage(clone, files, had_head)
        tree = _git(clone, "write-tree").strip()
        digest, paths = commit_tree_digest(clone, tree, os.path.join(work, "verified"), site_kind)
    return digest_mismatch(files, paths, digest_mod.digest_output_tree(out_dir, site_kind), digest, "staged")


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
    mismatch = digest_mismatch(result.files, paths, result.digest, digest)
    if mismatch:
        raise DeployError(mismatch)
    run_gates(verified, repo, "the committed tree")
    st.tree_digest = digest
    return st
