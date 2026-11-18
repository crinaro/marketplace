"""Reading the commit's blobs or the working tree: every input of a build comes through here (git plumbing, no
clock beyond the commit dates)."""

import os
import posixpath
import subprocess
import time

from building.constants import JUNK_NAMES
from building.outcomes import BuildError


# ---------------------------------------------------------------- git access

def _git(repo, args, data=None):
    env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))
    env["LC_ALL"] = "C"
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), input=data, env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise BuildError("git cannot be run: %s" % e, fix="install git and make sure it is on your PATH")
    if p.returncode != 0:
        raise BuildError("git %s failed: %s" % (args[0], p.stderr.decode("utf-8", "replace").strip()), fix="run git in the dev repo yourself, fix what it reports, then build again")
    return p.stdout


def _is_shallow(repo):
    return _git(repo, ["rev-parse", "--is-shallow-repository"]).strip() == b"true"


def _decode_path(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise BuildError("a path under site/ or content/ is not valid UTF-8: %r" % raw, fix="rename the file with a UTF-8 name, or remove it from site/ and content/")


def _is_junk(path):
    return posixpath.basename(path) in JUNK_NAMES


def _commit_files(repo):
    """{path: bytes} for site/ and content/ at HEAD, from the commit's blobs."""
    try:
        out = _git(repo, ["ls-tree", "-r", "-z", "HEAD", "--", "site", "content"])
    except BuildError as e:
        raise BuildError("cannot read HEAD (%s)" % e, fix="make at least one commit in the dev repo, then build again")
    entries = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, rawpath = rec.partition(b"\t")
        mode, typ, sha = meta.decode("ascii").split()
        path = _decode_path(rawpath)
        if typ != "blob" or mode == "120000":
            raise BuildError("%s is a symlink or submodule; the build reads regular files only" % path, fix="replace the symlink or submodule with the real file or folder")
        if not _is_junk(path):
            entries.append((path, sha))
    files = {}
    if entries:
        shas = "".join("%s\n" % s for _p, s in entries).encode("ascii")
        blob = _git(repo, ["cat-file", "--batch"], data=shas)
        pos = 0
        for path, sha in entries:
            nl = blob.index(b"\n", pos)
            head = blob[pos:nl].decode("ascii").split()
            if len(head) != 3 or head[1] != "blob":
                raise BuildError("git cat-file could not read %s" % path, fix="run `git fsck` in the dev repo, then build again")
            size = int(head[2])
            files[path] = blob[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1
    return files


def _disk_files(repo):
    """{path: bytes} for tracked and untracked-but-not-ignored files under site/ and content/."""
    out = _git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard",
                      "--", "site", "content"])
    files = {}
    for raw in out.split(b"\0"):
        if not raw:
            continue
        path = _decode_path(raw)
        full = os.path.join(repo, path)
        if _is_junk(path) or not os.path.isfile(full):
            continue
        if os.path.islink(full):
            raise BuildError("%s is a symlink; the build reads regular files only" % path, fix="replace the symlink with the real file")
        with open(full, "rb") as fh:
            files[path] = fh.read()
    return files


def _last_commit_epoch(repo, paths):
    out = _git(repo, ["log", "-1", "--format=%ct", "HEAD", "--"] + list(paths), ).strip()
    return int(out) if out else None


def _utc_date(epoch):
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))
