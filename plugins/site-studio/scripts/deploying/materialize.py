"""deploying.materialize -- a commit's tree written to a folder (never the working files), its build digest, and the private-path rule.

`forbidden` is the list of paths that must never reach the public repo; `commit_tree_digest` is what the dry run and the
post-push re-read compare with the build's digest.
"""
import os
from building import digest as digest_mod
from deploying.gitrun import DeployError, _git


# Paths that must never reach the public repo: private notes, the review store, the app's folders.
PRIVATE_SEGMENTS = (".site-studio", "decisions", ".claude", ".git", "originals")
PRIVATE_NAMES = ("claude.md", "handoff.md", "brand.md", "site.json")


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
    return digest_mod.digest_output_tree(dest, site_kind), paths


def forbidden(path):
    segs = [s.lower() for s in path.split("/")]
    base = segs[-1]
    return (any(s in PRIVATE_SEGMENTS for s in segs) or base in PRIVATE_NAMES
            or base.endswith(".pdf.json"))
