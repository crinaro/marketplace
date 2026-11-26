"""deploying.clone -- the public clone: clone it, replace its tree with the build, stage the explicit list, list the changes.

`stage` runs `git add` without -f and tolerates its errors on purpose: a path an ignore rule drops is caught by the
commit-tree digest check (design 7.3 step 2.5).
"""
import os
import shutil
from deploying.gitrun import _git


def clone_public(url, dest, depth=None):
    """Clone the public repo. `depth` makes the clone shallow (the
    preflight's: it reads the tree of main and its paths, and V4's ancestry test still answers on one commit of history, which
    `test_deploy_preflight` holds, dev 1068 U-6). The publish itself clones in full."""
    _git(os.path.dirname(dest), "clone", "-q", *(("--depth", str(depth)) if depth else ()), url, dest)
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


def public_paths(clone):
    """Every path the clone's HEAD tracks: the addresses the public repo serves."""
    raw = _git(clone, "ls-tree", "-r", "-z", "--name-only", "HEAD", raw=True)
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]
